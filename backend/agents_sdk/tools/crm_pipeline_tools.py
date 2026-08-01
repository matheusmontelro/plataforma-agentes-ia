"""
CRM pipeline tools for frontend-created agents.

These tools let an agent inspect the company's CRM stages and move the current
lead only through the existing PipelineService, preserving history and triggers.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Annotated, Any, Dict, List, Optional

from agents import RunContextWrapper, function_tool
from fastapi import HTTPException
from pydantic import Field
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

VALID_ACTIONS = {"advance", "recede", "move_to_stage"}


def create_crm_pipeline_tools(
    *,
    company_id: int,
    configured_pipeline_id: Optional[int] = None,
    stage_rules: Optional[List[Dict[str, Any]]] = None,
) -> List[Any]:
    """Create CRM pipeline tools scoped to a workspace."""

    configured_stage_rules = _normalize_stage_rules(stage_rules or [])

    @function_tool
    async def list_crm_pipeline_stages(
        context: RunContextWrapper,
        lead_phone: Annotated[str, Field(description="Telefone do lead. Vazio usa o telefone do contexto da conversa.")] = "",
    ) -> Dict[str, Any]:
        """Lista as etapas do CRM disponíveis para o lead atual."""

        from backend.db import get_db

        runtime_context = getattr(context, "context", None)
        resolved_phone = _normalize_phone(
            lead_phone or getattr(runtime_context, "contact_phone", None) or ""
        )

        db = next(get_db())
        try:
            lead = _find_lead(db=db, company_id=company_id, phone=resolved_phone)
            pipeline = _resolve_pipeline(
                db=db,
                company_id=company_id,
                lead=lead,
                configured_pipeline_id=configured_pipeline_id,
            )
            if not pipeline:
                return {
                    "success": False,
                    "error": "pipeline_not_found",
                    "message_for_agent": "Nenhum pipeline ativo encontrado para esta empresa.",
                }

            stages = _ordered_stages(pipeline)
            return {
                "success": True,
                "pipeline": _serialize_pipeline(pipeline),
                "lead": _serialize_lead(lead),
                "current_stage": _serialize_stage(lead.current_stage) if lead and lead.current_stage else None,
                "stages": [_serialize_stage(stage) for stage in stages],
                "transition_rules": _rules_payload(configured_stage_rules, stages),
            }
        finally:
            db.close()

    @function_tool
    async def move_lead_crm_stage(
        context: RunContextWrapper,
        action: Annotated[str, Field(description="Ação: advance, recede ou move_to_stage.")],
        reason: Annotated[str, Field(description="Motivo objetivo, baseado nas regras configuradas, para mover o lead.")],
        target_stage_id: Annotated[int, Field(description="ID da etapa de destino. Use 0 quando action for advance/recede ou quando usar target_stage_name.")] = 0,
        target_stage_name: Annotated[str, Field(description="Nome da etapa de destino quando target_stage_id não for informado.")] = "",
        lead_phone: Annotated[str, Field(description="Telefone do lead. Vazio usa o telefone do contexto da conversa.")] = "",
    ) -> Dict[str, Any]:
        """Move o lead atual no CRM quando uma regra de avanço ou recuo for atendida."""

        from backend.db import get_db
        from backend.services.pipeline_service import PipelineService

        runtime_context = getattr(context, "context", None)
        resolved_phone = _normalize_phone(
            lead_phone or getattr(runtime_context, "contact_phone", None) or ""
        )
        normalized_action = _normalize_action(action)
        if normalized_action not in VALID_ACTIONS:
            return {
                "success": False,
                "error": "invalid_action",
                "message_for_agent": "Use action=advance, action=recede ou action=move_to_stage.",
            }

        db = next(get_db())
        try:
            lead = _find_lead(db=db, company_id=company_id, phone=resolved_phone)
            if not lead:
                return {
                    "success": False,
                    "error": "lead_not_found",
                    "message_for_agent": "Não encontrei este lead no CRM da empresa.",
                }

            pipeline = _resolve_pipeline(
                db=db,
                company_id=company_id,
                lead=lead,
                configured_pipeline_id=configured_pipeline_id,
            )
            if not pipeline:
                return {
                    "success": False,
                    "error": "pipeline_not_found",
                    "message_for_agent": "Nenhum pipeline ativo encontrado para esta empresa.",
                }

            stages = _ordered_stages(pipeline)
            target_stage = _resolve_target_stage(
                action=normalized_action,
                stages=stages,
                current_stage_id=lead.current_stage_id,
                target_stage_id=target_stage_id,
                target_stage_name=target_stage_name,
            )
            if not target_stage:
                return {
                    "success": False,
                    "error": "target_stage_not_found",
                    "current_stage": _serialize_stage(lead.current_stage) if lead.current_stage else None,
                    "stages": [_serialize_stage(stage) for stage in stages],
                    "message_for_agent": "Não encontrei uma etapa de destino válida para essa movimentação.",
                }

            if lead.current_stage_id == target_stage.id:
                return {
                    "success": True,
                    "changed": False,
                    "lead": _serialize_lead(lead),
                    "current_stage": _serialize_stage(target_stage),
                    "message_for_agent": "O lead já está nessa etapa do CRM.",
                }

            history = PipelineService.move_lead_to_stage(
                lead_id=lead.id,
                new_stage_id=target_stage.id,
                user_id=None,
                notes=_movement_notes(action=normalized_action, reason=reason),
                db=db,
            )
            db.refresh(lead)

            return {
                "success": True,
                "changed": True,
                "history_id": history.id,
                "lead": _serialize_lead(lead),
                "from_stage_id": history.from_stage_id,
                "to_stage": _serialize_stage(target_stage),
                "reason": reason,
                "message_for_agent": "Lead movido no CRM com histórico registrado.",
            }
        except HTTPException as exc:
            return {
                "success": False,
                "error": "pipeline_service_error",
                "message_for_agent": str(exc.detail),
            }
        except Exception as exc:
            db.rollback()
            logger.exception("[CrmPipelineTool] move_lead_crm_stage failed")
            return {
                "success": False,
                "error": "internal_error",
                "details": str(exc),
                "message_for_agent": "Não foi possível mover o lead no CRM agora.",
            }
        finally:
            db.close()

    return [list_crm_pipeline_stages, move_lead_crm_stage]


def _normalize_stage_rules(rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        stage_id = _safe_positive_int(rule.get("stage_id") or rule.get("stageId"))
        stage_name = str(rule.get("stage_name") or rule.get("stageName") or "").strip()
        advance_rule = str(rule.get("advance_rule") or rule.get("advanceRule") or "").strip()
        recede_rule = str(rule.get("recede_rule") or rule.get("recedeRule") or "").strip()
        if not stage_id and not stage_name:
            continue
        normalized.append(
            {
                "stage_id": stage_id,
                "stage_name": stage_name,
                "advance_rule": advance_rule,
                "recede_rule": recede_rule,
            }
        )
    return normalized


def _rules_payload(rules: List[Dict[str, Any]], stages: List[Any]) -> List[Dict[str, Any]]:
    stage_lookup = {int(stage.id): stage for stage in stages}
    payload = []
    for rule in rules:
        stage_id = rule.get("stage_id")
        stage = stage_lookup.get(int(stage_id)) if stage_id else None
        payload.append(
            {
                **rule,
                "stage_name": rule.get("stage_name") or (stage.name if stage else ""),
            }
        )
    return payload


def _find_lead(*, db: Session, company_id: int, phone: str) -> Optional[Any]:
    from backend.models import Lead

    candidates = _phone_candidates(phone)
    if not candidates:
        return None
    return (
        db.query(Lead)
        .filter(Lead.company_id == company_id, Lead.phone.in_(candidates))
        .order_by(Lead.id.desc())
        .first()
    )


def _resolve_pipeline(
    *,
    db: Session,
    company_id: int,
    lead: Optional[Any],
    configured_pipeline_id: Optional[int],
) -> Optional[Any]:
    from backend.models import Pipeline

    if lead and lead.pipeline:
        return lead.pipeline
    if configured_pipeline_id:
        pipeline = (
            db.query(Pipeline)
            .filter(
                Pipeline.id == configured_pipeline_id,
                Pipeline.company_id == company_id,
            )
            .first()
        )
        if pipeline:
            return pipeline
    return (
        db.query(Pipeline)
        .filter(Pipeline.company_id == company_id, Pipeline.is_active == True)
        .order_by(Pipeline.id.asc())
        .first()
    )


def _ordered_stages(pipeline: Any) -> List[Any]:
    return sorted(list(pipeline.stages or []), key=lambda stage: (stage.order, stage.id))


def _resolve_target_stage(
    *,
    action: str,
    stages: List[Any],
    current_stage_id: Optional[int],
    target_stage_id: int,
    target_stage_name: str,
) -> Optional[Any]:
    if action == "move_to_stage":
        return _find_stage_by_id_or_name(stages, target_stage_id, target_stage_name)

    if action == "advance" and not current_stage_id:
        return stages[0] if stages else None

    current_index = next(
        (index for index, stage in enumerate(stages) if stage.id == current_stage_id),
        None,
    )
    if current_index is None:
        return None
    if action == "advance" and current_index + 1 < len(stages):
        return stages[current_index + 1]
    if action == "recede" and current_index - 1 >= 0:
        return stages[current_index - 1]
    return None


def _find_stage_by_id_or_name(
    stages: List[Any],
    stage_id: int,
    stage_name: str,
) -> Optional[Any]:
    if stage_id:
        for stage in stages:
            if int(stage.id) == int(stage_id):
                return stage
    normalized_name = _slugify(stage_name)
    if normalized_name:
        for stage in stages:
            if _slugify(stage.name) == normalized_name:
                return stage
    return None


def _movement_notes(*, action: str, reason: str) -> str:
    action_label = {
        "advance": "avancar",
        "recede": "recuar",
        "move_to_stage": "mover_para_etapa",
    }.get(action, action)
    clean_reason = str(reason or "").strip() or "Regra do agente atendida"
    return f"Movido pela IA via Agents SDK.\nAcao: {action_label}\nMotivo: {clean_reason}"


def _serialize_pipeline(pipeline: Any) -> Dict[str, Any]:
    return {
        "id": pipeline.id,
        "name": pipeline.name,
    }


def _serialize_lead(lead: Optional[Any]) -> Optional[Dict[str, Any]]:
    if not lead:
        return None
    return {
        "id": lead.id,
        "name": lead.name,
        "phone": lead.phone,
        "pipeline_id": lead.pipeline_id,
        "current_stage_id": lead.current_stage_id,
    }


def _serialize_stage(stage: Optional[Any]) -> Optional[Dict[str, Any]]:
    if not stage:
        return None
    return {
        "id": stage.id,
        "name": stage.name,
        "order": stage.order,
        "is_first_stage": bool(stage.is_first_stage),
        "is_converted_stage": bool(stage.is_converted_stage),
        "is_lost_stage": bool(stage.is_lost_stage),
    }


def _normalize_action(action: str) -> str:
    value = _slugify(action)
    aliases = {
        "avancar": "advance",
        "advance": "advance",
        "proxima": "advance",
        "proximo": "advance",
        "recuar": "recede",
        "recede": "recede",
        "voltar": "recede",
        "anterior": "recede",
        "mover": "move_to_stage",
        "move": "move_to_stage",
        "move_to_stage": "move_to_stage",
        "mover_para_etapa": "move_to_stage",
    }
    return aliases.get(value, value)


def _normalize_phone(phone: Any) -> str:
    return re.sub(r"\D+", "", str(phone or ""))


def _phone_candidates(phone: str) -> List[str]:
    digits = _normalize_phone(phone)
    candidates = [digits] if digits else []
    if digits.startswith("55") and len(digits) > 11:
        candidates.append(digits[2:])
    elif len(digits) in {10, 11}:
        candidates.append(f"55{digits}")
    return list(dict.fromkeys(candidates))


def _safe_positive_int(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _slugify(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    ascii_value = re.sub(r"[^a-z0-9]+", "_", ascii_value)
    return re.sub(r"_+", "_", ascii_value).strip("_")
