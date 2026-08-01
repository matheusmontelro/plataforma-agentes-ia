"""
WhatsApp scheduled follow-up tools for frontend-created agents.

The agent can schedule one future text message for the current WhatsApp
conversation. The delivery uses the existing ContactTask scheduled-message
pipeline and Celery worker.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agents import RunContextWrapper, function_tool
from pydantic import Field
from sqlalchemy.orm import Session

from backend.services.company_access_control import (
    CompanyOperationallyBlockedError,
    enqueue_company_job_if_active,
    fence_company_job_mutation,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "America/Sao_Paulo"
DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
)
WEEKDAY_ALIASES = {
    "segunda": 0,
    "segunda_feira": 0,
    "terca": 1,
    "terca_feira": 1,
    "terça": 1,
    "terça_feira": 1,
    "quarta": 2,
    "quarta_feira": 2,
    "quinta": 3,
    "quinta_feira": 3,
    "sexta": 4,
    "sexta_feira": 4,
    "sabado": 5,
    "sábado": 5,
    "domingo": 6,
}


def create_whatsapp_scheduled_followup_tools(
    *,
    company_id: int,
    default_replace_existing_pending: bool = True,
) -> List[Any]:
    """Create WhatsApp scheduled follow-up tools scoped to a workspace."""

    @function_tool
    async def schedule_whatsapp_followup_message(
        context: RunContextWrapper,
        scheduled_for: Annotated[str, Field(description="Data e hora combinadas com o lead. Aceita ISO/local ou frases como 'amanhã às 09:20'. Deve conter horário exato.")],
        message_content: Annotated[str, Field(description="Texto exato que será enviado automaticamente no horário agendado.")],
        reason: Annotated[str, Field(description="Motivo curto do agendamento, baseado no contexto da conversa.")] = "",
        timezone_name: Annotated[str, Field(description="Fuso opcional. Vazio usa o fuso da agenda ativa da empresa.")] = "",
        lead_name: Annotated[str, Field(description="Nome do lead, se conhecido. Vazio usa o nome do contexto.")] = "",
        replace_existing_pending: Annotated[bool, Field(description="True cancela follow-ups automáticos pendentes anteriores deste contato antes de criar o novo.")] = default_replace_existing_pending,
    ) -> Dict[str, Any]:
        """
        Agenda uma mensagem futura de WhatsApp para o lead atual.

        Use somente quando o lead aceitou ser chamado depois e informou uma data
        com horário exato. Se o lead informou apenas dia ou período, pergunte o
        horário antes de chamar esta ferramenta.
        """

        from backend.db import get_db

        runtime_context = getattr(context, "context", None)
        context_phone = _normalize_phone(getattr(runtime_context, "contact_phone", "") or "")
        context_name = str(getattr(runtime_context, "contact_name", "") or "").strip()

        if not context_phone:
            return {
                "success": False,
                "error": "conversation_phone_required",
                "message_for_agent": "Não foi possível identificar o WhatsApp da conversa atual.",
            }

        if not str(message_content or "").strip():
            return {
                "success": False,
                "error": "message_content_required",
                "message_for_agent": "Escreva o texto exato da mensagem futura antes de agendar.",
            }

        db = next(get_db())
        try:
            result = schedule_followup_message_for_context(
                db=db,
                company_id=company_id,
                contact_phone=context_phone,
                contact_name=lead_name or context_name,
                scheduled_for=scheduled_for,
                message_content=message_content,
                reason=reason,
                timezone_name=timezone_name,
                replace_existing_pending=replace_existing_pending,
                runtime_context={
                    "workforce_id": getattr(runtime_context, "workforce_id", None),
                    "workforce_name": getattr(runtime_context, "workforce_name", None),
                    "root_agent_key": getattr(runtime_context, "root_agent_key", None),
                    "flow_id": getattr(runtime_context, "flow_id", None),
                    "node_id": getattr(runtime_context, "node_id", None),
                    "channel": getattr(runtime_context, "channel", None),
                },
            )
            if result.get("success") and runtime_context is not None:
                setattr(runtime_context, "scheduled_followup_message", result)
            return result
        except Exception as exc:
            logger.exception("[WhatsAppScheduledFollowupTool] schedule failed")
            db.rollback()
            return {
                "success": False,
                "error": "internal_error",
                "message_for_agent": "Não foi possível agendar a mensagem agora.",
                "details": str(exc),
            }
        finally:
            db.close()

    return [schedule_whatsapp_followup_message]


def schedule_followup_message_for_context(
    *,
    db: Session,
    company_id: int,
    contact_phone: str,
    contact_name: str,
    scheduled_for: str,
    message_content: str,
    reason: str = "",
    timezone_name: str = "",
    replace_existing_pending: bool = True,
    runtime_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create and enqueue a scheduled WhatsApp text message for a contact."""

    from backend.models import ContactTask, ScheduledMessageExecution
    from backend.worker.tasks_scheduled_messages import enviar_mensagem_agendada

    resolved_timezone = _resolve_company_timezone(
        db=db,
        company_id=company_id,
        timezone_name=timezone_name,
    )
    parsed = _parse_scheduled_for(scheduled_for, resolved_timezone)
    if not parsed["success"]:
        return parsed

    scheduled_local: datetime = parsed["scheduled_local"]
    scheduled_utc: datetime = parsed["scheduled_utc"]
    now_utc = datetime.now(timezone.utc)
    if scheduled_utc <= now_utc + timedelta(seconds=30):
        return {
            "success": False,
            "error": "scheduled_time_must_be_future",
            "timezone": resolved_timezone,
            "current_time": now_utc.astimezone(_safe_timezone(resolved_timezone)).isoformat(),
            "message_for_agent": "O horário precisa estar no futuro. Confirme outro horário com o lead.",
        }

    try:
        fence_company_job_mutation(db, company_id)
    except CompanyOperationallyBlockedError:
        return {
            "success": False,
            "error": "company_access_suspended",
            "message_for_agent": "O acesso da empresa está suspenso e a mensagem não foi agendada.",
        }

    contact_result = _get_or_create_contact(
        db=db,
        company_id=company_id,
        phone=contact_phone,
        name=contact_name,
    )
    if not contact_result["success"]:
        return contact_result
    contact = contact_result["contact"]

    canceled_task_ids: List[int] = []
    if replace_existing_pending:
        canceled_task_ids = _cancel_existing_agent_followups(
            db=db,
            company_id=company_id,
            contact_id=int(contact.id),
        )

    metadata = {
        "source": "agents_sdk_scheduled_followup",
        "reason": str(reason or "").strip(),
        "timezone": resolved_timezone,
        "scheduled_local": scheduled_local.isoformat(),
        "scheduled_utc": scheduled_utc.isoformat(),
        "replace_existing_pending": replace_existing_pending,
        "canceled_task_ids": canceled_task_ids,
        "runtime": runtime_context or {},
    }
    task = ContactTask(
        contact_id=contact.id,
        company_id=company_id,
        created_by=None,
        assigned_to=None,
        task_type="scheduled_message",
        title="Mensagem automática agendada",
        description=_build_task_description(
            scheduled_local=scheduled_local,
            timezone_name=resolved_timezone,
            reason=reason,
        ),
        message_content=str(message_content).strip(),
        message_type="text",
        scheduled_for=scheduled_utc,
        reminder_minutes=0,
        status="pending",
        priority="medium",
        tags=["agents_sdk", "scheduled_followup"],
        task_metadata=metadata,
    )
    db.add(task)
    db.flush()

    execution = ScheduledMessageExecution(
        task_id=task.id,
        contact_id=contact.id,
        company_id=company_id,
        message_type="text",
        message_content=str(message_content).strip(),
        message_file_path=None,
        status="SCHEDULED",
        scheduled_for=scheduled_utc,
    )
    db.add(execution)
    db.commit()
    db.refresh(task)

    # The currently active message worker consumes messages_queue. Explicitly
    # routing avoids relying on the inactive broad worker for scheduled queue.
    try:
        enqueued, celery_result = enqueue_company_job_if_active(
            db,
            company_id,
            is_still_pending=lambda: bool(
                db.query(ScheduledMessageExecution.id)
                .filter(
                    ScheduledMessageExecution.id == execution.id,
                    ScheduledMessageExecution.status == "SCHEDULED",
                )
                .first()
                and db.query(ContactTask.id)
                .filter(
                    ContactTask.id == task.id,
                    ContactTask.status == "pending",
                )
                .first()
            ),
            enqueue=lambda: enviar_mensagem_agendada.apply_async(
                args=[task.id],
                eta=scheduled_utc,
                queue="messages_queue",
            ),
        )
    except CompanyOperationallyBlockedError:
        enqueued, celery_result = False, None
    if not enqueued:
        return {
            "success": False,
            "error": "company_access_suspended",
            "task_id": task.id,
            "message_for_agent": "O acesso da empresa foi suspenso e a mensagem ficou cancelada.",
        }

    return {
        "success": True,
        "task_id": task.id,
        "contact_id": contact.id,
        "scheduled_for": scheduled_local.isoformat(),
        "scheduled_for_utc": scheduled_utc.isoformat(),
        "timezone": resolved_timezone,
        "message_content": task.message_content,
        "reason": str(reason or "").strip(),
        "canceled_task_ids": canceled_task_ids,
        "celery_task_id": getattr(celery_result, "id", None),
        "message_for_agent": "Mensagem agendada. Confirme ao lead, de forma curta, que você vai chamar nesse horário.",
    }


def _resolve_company_timezone(*, db: Session, company_id: int, timezone_name: str = "") -> str:
    from backend.models import Agenda

    requested = str(timezone_name or "").strip()
    if requested and _is_valid_timezone(requested):
        return requested

    agenda = (
        db.query(Agenda)
        .filter(Agenda.company_id == company_id, Agenda.active.is_(True))
        .order_by(Agenda.id.asc())
        .first()
    )
    if agenda and _is_valid_timezone(agenda.timezone):
        return agenda.timezone
    if agenda and _is_valid_timezone(agenda.google_calendar_time_zone):
        return agenda.google_calendar_time_zone
    return DEFAULT_TIMEZONE


def _parse_scheduled_for(
    value: str,
    timezone_name: str,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    tz = _safe_timezone(timezone_name)
    now_local = now.astimezone(tz) if now else datetime.now(tz)
    raw_value = str(value or "").strip()
    if not raw_value:
        return {
            "success": False,
            "error": "scheduled_for_required",
            "message_for_agent": "Peça ao lead uma data e um horário antes de agendar.",
        }

    explicit = _parse_explicit_datetime(raw_value, tz)
    if explicit:
        return _parsed_datetime_payload(explicit, timezone_name)

    normalized = _normalize_text(raw_value)
    target_date = _relative_target_date(normalized, now_local.date())
    if target_date is None:
        return {
            "success": False,
            "error": "scheduled_date_unclear",
            "message_for_agent": "A data não ficou clara. Confirme o dia e horário com o lead.",
        }

    parsed_time = _extract_time(normalized)
    if parsed_time is None:
        return {
            "success": False,
            "error": "scheduled_time_required",
            "timezone": timezone_name,
            "date": target_date.isoformat(),
            "message_for_agent": "O lead informou o dia, mas falta o horário exato. Pergunte qual horário fica melhor.",
        }

    scheduled_local = datetime.combine(target_date, parsed_time, tzinfo=tz)
    return _parsed_datetime_payload(scheduled_local, timezone_name)


def _parse_explicit_datetime(raw_value: str, tz: ZoneInfo) -> Optional[datetime]:
    if not _contains_explicit_time(raw_value):
        return None

    iso_candidate = raw_value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_candidate)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=tz)
        return parsed.astimezone(tz)
    except ValueError:
        pass

    cleaned = (
        raw_value.replace("T", " ")
        .replace(" às ", " ")
        .replace(" as ", " ")
        .replace(",", " ")
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=tz)
        except ValueError:
            continue
    return None


def _parsed_datetime_payload(scheduled_local: datetime, timezone_name: str) -> Dict[str, Any]:
    scheduled_utc = scheduled_local.astimezone(timezone.utc)
    return {
        "success": True,
        "timezone": timezone_name,
        "scheduled_local": scheduled_local,
        "scheduled_utc": scheduled_utc,
    }


def _relative_target_date(normalized: str, today: date) -> Optional[date]:
    if "depois_de_amanha" in normalized:
        return today + timedelta(days=2)
    if "amanha" in normalized:
        return today + timedelta(days=1)
    if "hoje" in normalized:
        return today

    for weekday_name, weekday in WEEKDAY_ALIASES.items():
        pattern = weekday_name.replace("_", "[ _-]?")
        if re.search(rf"\b{pattern}\b", normalized):
            days_ahead = (weekday - today.weekday()) % 7
            if days_ahead == 0 or "proxim" in normalized:
                days_ahead = days_ahead or 7
            return today + timedelta(days=days_ahead)
    return None


def _extract_time(normalized: str) -> Optional[time]:
    matches = list(re.finditer(r"(?:^|_)([01]?\d|2[0-3])(?:h|:)([0-5]\d)?(?:_|$)", normalized))
    if not matches:
        matches = list(re.finditer(r"(?:^|_)as_([01]?\d|2[0-3])(?:_|$)", normalized))
    if not matches:
        return None

    match = matches[-1]
    hour = int(match.group(1))
    minute = int(match.group(2) or 0) if match.lastindex and match.lastindex >= 2 else 0
    return time(hour=hour, minute=minute)


def _contains_explicit_time(value: str) -> bool:
    return bool(re.search(r"\b([01]?\d|2[0-3])(?::|h)[0-5]?\d?\b", value))


def _safe_timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(str(timezone_name or DEFAULT_TIMEZONE))
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TIMEZONE)


def _is_valid_timezone(timezone_name: Any) -> bool:
    try:
        ZoneInfo(str(timezone_name or ""))
        return True
    except Exception:
        return False


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
            "message_for_agent": "Não encontrei a conta vinculada a esta empresa para criar a mensagem agendada.",
        }

    contact = Contact(
        client_id=client_id,
        company_id=company_id,
        phone=_normalize_phone(phone),
        name=name or None,
        human_mode=False,
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


def _cancel_existing_agent_followups(
    *,
    db: Session,
    company_id: int,
    contact_id: int,
) -> List[int]:
    from backend.models import ContactTask, ScheduledMessageExecution

    now_utc = datetime.now(timezone.utc)
    tasks = (
        db.query(ContactTask)
        .filter(
            ContactTask.company_id == company_id,
            ContactTask.contact_id == contact_id,
            ContactTask.task_type == "scheduled_message",
            ContactTask.status == "pending",
            ContactTask.scheduled_for > now_utc,
        )
        .all()
    )
    canceled: List[int] = []
    for task in tasks:
        metadata = task.task_metadata if isinstance(task.task_metadata, dict) else {}
        if metadata.get("source") != "agents_sdk_scheduled_followup":
            continue
        task.status = "canceled"
        metadata["canceled_by"] = "agents_sdk_scheduled_followup_replace"
        metadata["canceled_at"] = now_utc.isoformat()
        task.task_metadata = metadata
        (
            db.query(ScheduledMessageExecution)
            .filter(ScheduledMessageExecution.task_id == task.id)
            .update({"status": "CANCELED", "error_message": "Substituída por novo follow-up agendado"})
        )
        canceled.append(int(task.id))
    return canceled


def _build_task_description(
    *,
    scheduled_local: datetime,
    timezone_name: str,
    reason: str,
) -> str:
    parts = [
        f"Mensagem automática agendada para {scheduled_local.strftime('%d/%m/%Y às %H:%M')} ({timezone_name}).",
        f"Motivo: {str(reason).strip()}" if str(reason or "").strip() else "",
    ]
    return "\n".join(part for part in parts if part)


def _normalize_phone(phone: Any) -> str:
    return re.sub(r"\D+", "", str(phone or ""))


def _phone_candidates(phone: Any) -> List[str]:
    digits = _normalize_phone(phone)
    candidates = [digits] if digits else []
    if digits.startswith("55") and len(digits) > 11:
        candidates.append(digits[2:])
    elif len(digits) in {10, 11}:
        candidates.append(f"55{digits}")
    return list(dict.fromkeys(candidates))


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower()
    ascii_text = ascii_text.replace("depois de amanha", "depois_de_amanha")
    ascii_text = re.sub(r"[^a-z0-9:]+", "_", ascii_text)
    return re.sub(r"_+", "_", ascii_text).strip("_")
