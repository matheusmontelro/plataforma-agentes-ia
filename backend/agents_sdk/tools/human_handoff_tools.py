"""
Human handoff tools for frontend-created agents.

The frontend sends human queues as safe configuration IDs. This module exposes a
single Agents SDK function tool that creates the operational task for the team
and pauses the bot for the contact when a handoff is needed.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from agents import RunContextWrapper, function_tool
from pydantic import Field
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

VALID_PRIORITIES = {"low", "medium", "high", "urgent"}


def create_human_handoff_tools(
    *,
    company_id: int,
    targets: Optional[List[Dict[str, Any]]] = None,
) -> List[Any]:
    """Create human handoff tools scoped to a workspace."""

    configured_targets = _normalize_targets(targets or [])

    @function_tool
    async def create_human_handoff_task(
        context: RunContextWrapper,
        reason: Annotated[str, Field(description="Motivo objetivo para transferir este lead para atendimento humano.")],
        summary: Annotated[str, Field(description="Resumo curto do que o lead pediu e do que ja foi coletado.")] = "",
        queue_key: Annotated[str, Field(description="Chave ou nome da fila humana configurada. Obrigatorio quando houver mais de uma fila.")] = "",
        lead_phone: Annotated[str, Field(description="Telefone do lead. Vazio usa o telefone do contexto da conversa.")] = "",
        lead_name: Annotated[str, Field(description="Nome do lead, se conhecido.")] = "",
        priority: Annotated[str, Field(description="Prioridade opcional: low, medium, high ou urgent. Vazio usa a fila configurada.")] = "",
        pause_bot: Annotated[bool, Field(description="True para pausar a IA neste contato apos criar o handoff.")] = True,
    ) -> Dict[str, Any]:
        """
        Cria uma tarefa de atendimento humano para um lead.

        Use quando a politica do agente indicar handoff, quando a conversa sair
        do escopo seguro do agente, ou quando o lead pedir atendimento humano.
        Se a fila estiver configurada como silenciosa, nao avise o lead; apenas
        crie a tarefa e deixe a equipe humana assumir.
        """

        from backend.db import get_db
        from backend.models import Contact, ContactTask

        runtime_context = getattr(context, "context", None)
        context_phone = getattr(runtime_context, "contact_phone", None)
        context_name = getattr(runtime_context, "contact_name", None)
        selected_target = _select_target(configured_targets, queue_key)

        if selected_target is None:
            return {
                "success": False,
                "error": "queue_not_found",
                "available_queues": _queue_payloads(configured_targets),
                "message_for_agent": "Escolha uma das filas humanas configuradas antes de criar o handoff.",
            }

        resolved_phone = _normalize_phone(lead_phone or context_phone or "")
        if not resolved_phone:
            return {
                "success": False,
                "error": "lead_phone_required",
                "message_for_agent": "Peça o telefone do lead antes de transferir para atendimento humano.",
            }

        db = next(get_db())
        try:
            contact = _get_or_create_contact(
                db=db,
                company_id=company_id,
                phone=resolved_phone,
                name=lead_name or context_name or "",
            )
            if not contact["success"]:
                return contact

            db_contact: Contact = contact["contact"]
            if pause_bot:
                db_contact.human_mode = True

            assignment = selected_target.get("assignment") or {}
            assigned_to = _safe_positive_int(assignment.get("userId") or assignment.get("user_id"))
            effective_priority = _normalize_priority(
                priority or assignment.get("priority") or "medium"
            )
            transfer_message = str(assignment.get("transferMessage") or "").strip()
            silent_transfer = _is_silent_transfer(assignment)

            task = ContactTask(
                contact_id=db_contact.id,
                company_id=company_id,
                assigned_to=assigned_to,
                task_type="message",
                title=f"Atender lead - {selected_target['queue_name']}",
                description=_build_task_description(
                    reason=reason,
                    summary=summary,
                    lead_name=lead_name or db_contact.name or "",
                    lead_phone=resolved_phone,
                ),
                scheduled_for=datetime.now(timezone.utc),
                reminder_minutes=0,
                priority=effective_priority,
                tags=_handoff_tags(selected_target),
                task_metadata={
                    "source": "agents_sdk_human_handoff",
                    "queue_key": selected_target["queue_key"],
                    "queue_name": selected_target["queue_name"],
                    "reason": reason,
                    "summary": summary,
                    "pause_bot": pause_bot,
                    "assignment": assignment,
                    "runtime": {
                        "workforce_id": getattr(runtime_context, "workforce_id", None),
                        "workforce_name": getattr(runtime_context, "workforce_name", None),
                        "root_agent_key": getattr(runtime_context, "root_agent_key", None),
                        "flow_id": getattr(runtime_context, "flow_id", None),
                        "node_id": getattr(runtime_context, "node_id", None),
                        "channel": getattr(runtime_context, "channel", None),
                    },
                },
            )
            db.add(task)
            db.commit()
            db.refresh(task)

            task_payload = {
                "task_id": task.id,
                "contact_id": db_contact.id,
                "queue_key": selected_target["queue_key"],
                "queue_name": selected_target["queue_name"],
                "assigned_to": assigned_to,
                "priority": effective_priority,
                "bot_paused": pause_bot,
                "silent": silent_transfer,
            }
            if runtime_context is not None:
                setattr(runtime_context, "human_handoff_task", task_payload)
                if silent_transfer:
                    setattr(runtime_context, "suppress_whatsapp_send", True)

            return {
                "success": True,
                "task_id": task.id,
                "contact_id": db_contact.id,
                "queue": {
                    "key": selected_target["queue_key"],
                    "name": selected_target["queue_name"],
                },
                "assigned_to": assigned_to,
                "priority": effective_priority,
                "bot_paused": pause_bot,
                "silent": silent_transfer,
                "suppress_whatsapp_send": silent_transfer,
                "message_for_agent": ""
                if silent_transfer
                else transfer_message
                or "Avise o lead que a equipe vai assumir a conversa por aqui.",
            }
        except Exception as exc:
            db.rollback()
            logger.exception("[HumanHandoffTool] create_human_handoff_task failed")
            return {
                "success": False,
                "error": "internal_error",
                "message_for_agent": "Não foi possível criar o handoff humano agora.",
                "details": str(exc),
            }
        finally:
            db.close()

    return [create_human_handoff_task]


def _normalize_targets(targets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for target in targets:
        if not isinstance(target, dict):
            continue
        queue_key = str(target.get("queue_key") or target.get("key") or "").strip()
        queue_name = str(target.get("queue_name") or target.get("name") or queue_key).strip()
        if not queue_key and queue_name:
            queue_key = _slugify(queue_name)
        if not queue_key:
            continue
        assignment = target.get("assignment") if isinstance(target.get("assignment"), dict) else {}
        normalized.append(
            {
                "queue_key": queue_key,
                "queue_name": queue_name or queue_key,
                "when": str(target.get("when") or "").strip(),
                "assignment": assignment,
            }
        )
    return normalized


def _is_silent_transfer(assignment: Dict[str, Any]) -> bool:
    if not isinstance(assignment, dict):
        return False
    if assignment.get("silentTransfer") is True or assignment.get("silent_transfer") is True:
        return True
    if assignment.get("sendTransferMessage") is False or assignment.get("send_transfer_message") is False:
        return True
    return False


def _select_target(
    targets: List[Dict[str, Any]],
    queue_key: str,
) -> Optional[Dict[str, Any]]:
    if not targets:
        return {
            "queue_key": "humano",
            "queue_name": "Atendimento humano",
            "when": "",
            "assignment": {},
        }

    requested = str(queue_key or "").strip().lower()
    if not requested and len(targets) == 1:
        return targets[0]
    if not requested:
        return None

    requested_slug = _slugify(requested)
    for target in targets:
        if requested in {
            target["queue_key"].lower(),
            target["queue_name"].lower(),
        }:
            return target
        if requested_slug in {
            _slugify(target["queue_key"]),
            _slugify(target["queue_name"]),
        }:
            return target
    return None


def _get_or_create_contact(
    *,
    db: Session,
    company_id: int,
    phone: str,
    name: str,
) -> Dict[str, Any]:
    from backend.models import Client, ClientCompany, Contact

    candidates = _phone_candidates(phone)
    contact = (
        db.query(Contact)
        .filter(Contact.company_id == company_id, Contact.phone.in_(candidates))
        .first()
    )
    if contact:
        if name and not contact.name:
            contact.name = name
        return {"success": True, "contact": contact}

    client_id = _resolve_client_id(db=db, company_id=company_id)
    if not client_id:
        return {
            "success": False,
            "error": "client_not_found",
            "message_for_agent": "Não encontrei a conta vinculada a esta empresa para criar a tarefa.",
        }

    contact = Contact(
        client_id=client_id,
        company_id=company_id,
        phone=phone,
        name=name or None,
        human_mode=True,
    )
    db.add(contact)
    db.flush()
    return {"success": True, "contact": contact}


def _resolve_client_id(*, db: Session, company_id: int) -> Optional[int]:
    from backend.models import Client, ClientCompany

    association = (
        db.query(ClientCompany)
        .filter(ClientCompany.company_id == company_id)
        .order_by(ClientCompany.id.asc())
        .first()
    )
    if association:
        return int(association.client_id)

    client = db.query(Client).filter(Client.company_id == company_id).first()
    return int(client.id) if client else None


def _build_task_description(
    *,
    reason: str,
    summary: str,
    lead_name: str,
    lead_phone: str,
) -> str:
    parts = [
        f"Motivo: {reason.strip()}",
        f"Resumo: {summary.strip()}" if summary.strip() else "",
        f"Lead: {lead_name.strip()}" if lead_name.strip() else "",
        f"Telefone: {lead_phone}",
    ]
    return "\n".join(part for part in parts if part)


def _handoff_tags(target: Dict[str, Any]) -> List[str]:
    tags = ["agentive_handoff", f"queue:{target['queue_key']}"]
    assignment_tags = target.get("assignment", {}).get("tags")
    if isinstance(assignment_tags, list):
        tags.extend(str(tag).strip() for tag in assignment_tags if str(tag).strip())
    return tags


def _queue_payloads(targets: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    return [
        {
            "queue_key": target["queue_key"],
            "queue_name": target["queue_name"],
            "when": target.get("when", ""),
        }
        for target in targets
    ]


def _normalize_priority(priority: str) -> str:
    value = str(priority or "").strip().lower()
    return value if value in VALID_PRIORITIES else "medium"


def _normalize_phone(phone: str) -> str:
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


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return slug or "humano"
