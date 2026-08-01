"""Dynamic CRM follow-up orchestration for Agent Builder workforces."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as datetime_time, timedelta, timezone
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agents import Agent, Runner
from sqlalchemy.orm import Session

from backend.integrations.whatsapp_provider import send_text
from backend.models import (
    Agendamento,
    AgentDynamicFollowupEnrollment,
    AgentDynamicFollowupExecution,
    AgentWorkforce,
    Contact,
    Lead,
    Message,
    PipelineStage,
)
from backend.services.ai_usage_service import (
    extract_openai_usage,
    safe_record_openai_text_usage,
)
from backend.services.ai_provider_service import (
    build_company_openai_run_config,
    openai_run_trace,
    safe_ai_provider_runtime_error,
)
from backend.services.company_access_control import (
    CompanyOperationallyBlockedError,
    enqueue_company_job_if_active,
    fence_company_job_mutation,
)

logger = logging.getLogger(__name__)

DYNAMIC_FOLLOWUP_TOOL_ID = "crm.dynamic_followup"
DEFAULT_DYNAMIC_FOLLOWUP_MODEL = "gpt-5.4-mini"
DEFAULT_DYNAMIC_FOLLOWUP_TIMEZONE = "America/Sao_Paulo"
MAX_MESSAGE_CHARS = 1500
MAX_PROMPT_CHARS = 12000
MAX_DELAY_DAYS = 365

ENROLLMENT_ACTIVE = "active"
ENROLLMENT_COMPLETED = "completed"
ENROLLMENT_CANCELLED = "cancelled"
ENROLLMENT_FAILED = "failed"

EXECUTION_SCHEDULED = "SCHEDULED"
EXECUTION_PROCESSING = "PROCESSING"
EXECUTION_SUCCESS = "SUCCESS"
EXECUTION_FAILED = "FAILED"
EXECUTION_CANCELED = "CANCELED"
EXECUTION_SKIPPED = "SKIPPED"

VALID_DELAY_UNITS = {"minutes", "hours", "days"}
VALID_DELIVERY_WEEKDAYS = set(range(7))
DEFAULT_DELIVERY_WEEKDAYS = [0, 1, 2, 3, 4]
DEFAULT_DELIVERY_WINDOW_START = "09:00"
DEFAULT_DELIVERY_WINDOW_END = "18:00"
TERMINAL_APPOINTMENT_STATUS_PREFIXES = ("CANCELLED", "CANCELED", "CANCELADO", "DELETED")
TIME_PATTERN = re.compile(r"^\d{2}:\d{2}$")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware_utc(value: Optional[datetime | str]) -> datetime:
    if value is None:
        return _now_utc()
    if isinstance(value, str):
        raw_value = value.strip()
        if not raw_value:
            return _now_utc()
        normalized_value = raw_value.replace("Z", "+00:00")
        try:
            value = datetime.fromisoformat(normalized_value)
        except ValueError:
            logger.warning("[DynamicFollowup] Invalid datetime anchor received: %r", raw_value[:80])
            return _now_utc()
    if not isinstance(value, datetime):
        logger.warning("[DynamicFollowup] Unsupported datetime anchor type: %s", type(value).__name__)
        return _now_utc()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _as_int(value: Any) -> Optional[int]:
    try:
        if value is None or str(value).strip() == "":
            return None
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _as_non_negative_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "sim", "on"}:
        return True
    if normalized in {"false", "0", "no", "nao", "não", "off"}:
        return False
    return default


def _as_list_int(value: Any) -> list[int]:
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else [value]
    result: list[int] = []
    for item in raw_items:
        parsed = _as_int(item)
        if parsed and parsed not in result:
            result.append(parsed)
    return result


def _clean_text(value: Any, limit: int = 4000) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return text[:limit]


def _json_safe(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=str))
    except Exception:
        return {"raw": str(value)}


def _delay_delta(amount: int, unit: str) -> timedelta:
    normalized_amount = max(0, min(int(amount or 0), MAX_DELAY_DAYS * 24 * 60))
    normalized_unit = unit if unit in VALID_DELAY_UNITS else "hours"
    if normalized_unit == "minutes":
        return timedelta(minutes=normalized_amount)
    if normalized_unit == "days":
        return timedelta(days=min(normalized_amount, MAX_DELAY_DAYS))
    return timedelta(hours=min(normalized_amount, MAX_DELAY_DAYS * 24))


def _valid_hhmm(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not TIME_PATTERN.match(value.strip()):
        return None
    hours, minutes = value.strip().split(":", 1)
    try:
        parsed_hours = int(hours)
        parsed_minutes = int(minutes)
    except ValueError:
        return None
    if 0 <= parsed_hours <= 23 and 0 <= parsed_minutes <= 59:
        return f"{parsed_hours:02d}:{parsed_minutes:02d}"
    return None


def _parse_hhmm(value: str) -> datetime_time:
    hours, minutes = value.split(":", 1)
    return datetime_time(hour=int(hours), minute=int(minutes))


def _timezone_info(timezone_name: Any) -> ZoneInfo:
    cleaned = _clean_text(timezone_name, 80) or DEFAULT_DYNAMIC_FOLLOWUP_TIMEZONE
    try:
        return ZoneInfo(cleaned)
    except ZoneInfoNotFoundError:
        logger.warning("[DynamicFollowup] Invalid timezone %r; using default", cleaned)
        return ZoneInfo(DEFAULT_DYNAMIC_FOLLOWUP_TIMEZONE)


def _normalize_delivery_weekdays(value: Any) -> list[int]:
    raw_items = value if isinstance(value, list) else []
    weekdays: list[int] = []
    for item in raw_items:
        try:
            parsed = int(item)
        except (TypeError, ValueError):
            continue
        if parsed in VALID_DELIVERY_WEEKDAYS and parsed not in weekdays:
            weekdays.append(parsed)
    return weekdays or DEFAULT_DELIVERY_WEEKDAYS.copy()


def _normalize_delivery_window(raw_window: Any, fallback_timezone: str) -> dict[str, Any]:
    raw = raw_window if isinstance(raw_window, dict) else {}
    timezone_name = _clean_text(
        raw.get("timezone") or raw.get("business_timezone") or raw.get("businessTimezone"),
        80,
    ) or fallback_timezone or DEFAULT_DYNAMIC_FOLLOWUP_TIMEZONE
    start_time = _valid_hhmm(raw.get("start_time") or raw.get("startTime")) or DEFAULT_DELIVERY_WINDOW_START
    end_time = _valid_hhmm(raw.get("end_time") or raw.get("endTime")) or DEFAULT_DELIVERY_WINDOW_END
    if _parse_hhmm(start_time) >= _parse_hhmm(end_time):
        start_time = DEFAULT_DELIVERY_WINDOW_START
        end_time = DEFAULT_DELIVERY_WINDOW_END

    return {
        "enabled": _as_bool(raw.get("enabled"), default=False) if raw else False,
        "timezone": timezone_name,
        "allowed_weekdays": _normalize_delivery_weekdays(
            raw.get("allowed_weekdays") or raw.get("allowedWeekdays")
        ),
        "start_time": start_time,
        "end_time": end_time,
    }


def _adjust_to_delivery_window(candidate_at: datetime, delivery_window: Any) -> datetime:
    candidate_utc = _as_aware_utc(candidate_at)
    raw = delivery_window if isinstance(delivery_window, dict) else {}
    if not raw.get("enabled"):
        return candidate_utc

    window = _normalize_delivery_window(raw, str(raw.get("timezone") or DEFAULT_DYNAMIC_FOLLOWUP_TIMEZONE))
    if not window["enabled"]:
        return candidate_utc

    tzinfo = _timezone_info(window["timezone"])
    local_candidate = candidate_utc.astimezone(tzinfo)
    start_time = _parse_hhmm(window["start_time"])
    end_time = _parse_hhmm(window["end_time"])
    allowed_weekdays = set(window["allowed_weekdays"])

    for day_offset in range(8):
        day = (local_candidate + timedelta(days=day_offset)).date()
        if day.weekday() not in allowed_weekdays:
            continue

        window_start = datetime.combine(day, start_time, tzinfo=tzinfo)
        window_end = datetime.combine(day, end_time, tzinfo=tzinfo)
        if day_offset == 0:
            if local_candidate < window_start:
                return window_start.astimezone(timezone.utc)
            if window_start <= local_candidate < window_end:
                return local_candidate.astimezone(timezone.utc)
            continue

        return window_start.astimezone(timezone.utc)

    return candidate_utc


def _scheduled_for_step(anchor_at: Optional[datetime | str], step: dict[str, Any], settings: Optional[dict[str, Any]] = None) -> datetime:
    scheduled_for = _as_aware_utc(anchor_at) + _delay_delta(
        int(step.get("send_after") or 0),
        str(step.get("send_after_unit") or "hours"),
    )
    now = _now_utc()
    candidate = scheduled_for if scheduled_for > now else now
    return _adjust_to_delivery_window(candidate, (settings or {}).get("delivery_window"))


def _normalize_dynamic_followup_settings(settings: Any) -> dict[str, Any]:
    raw = settings if isinstance(settings, dict) else {}
    pipeline_id = _as_int(raw.get("pipeline_id") or raw.get("pipelineId"))
    target_stage_ids = _as_list_int(
        raw.get("target_stage_ids")
        or raw.get("targetStageIds")
        or raw.get("stop_stage_ids")
        or raw.get("stopStageIds")
    )
    timezone_name = _clean_text(
        raw.get("timezone") or raw.get("business_timezone") or raw.get("businessTimezone"),
        80,
    ) or DEFAULT_DYNAMIC_FOLLOWUP_TIMEZONE
    delivery_window = _normalize_delivery_window(
        raw.get("delivery_window") or raw.get("deliveryWindow"),
        timezone_name,
    )

    normalized_steps: list[dict[str, Any]] = []
    raw_steps = raw.get("steps") if isinstance(raw.get("steps"), list) else []
    for index, step in enumerate(raw_steps):
        if not isinstance(step, dict):
            continue
        mini_prompt = _clean_text(step.get("mini_prompt") or step.get("miniPrompt"), 5000)
        objective = _clean_text(step.get("objective") or step.get("objetivo"), 1000)
        if not mini_prompt:
            continue
        unit = str(step.get("send_after_unit") or step.get("sendAfterUnit") or "hours").strip()
        if unit not in VALID_DELAY_UNITS:
            unit = "hours"
        normalized_steps.append(
            {
                "step_number": _as_non_negative_int(
                    step.get("step_number") or step.get("stepNumber"),
                    default=index + 1,
                )
                or index + 1,
                "send_after": _as_non_negative_int(
                    step.get("send_after") or step.get("sendAfter"),
                    default=0,
                ),
                "send_after_unit": unit,
                "channel": "whatsapp",
                "objective": objective,
                "mini_prompt": mini_prompt,
            }
        )

    normalized_steps = sorted(normalized_steps, key=lambda item: item["step_number"])
    for index, step in enumerate(normalized_steps, start=1):
        step["step_number"] = index

    return {
        "enabled": raw.get("enabled", True) is not False,
        "pipeline_id": pipeline_id,
        "target_stage_ids": target_stage_ids,
        "stop_on_appointment_created": _as_bool(
            raw.get("stop_on_appointment_created", raw.get("stopOnAppointmentCreated")),
            default=True,
        ),
        "timezone": timezone_name,
        "delivery_window": delivery_window,
        "steps": normalized_steps,
    }


def _iter_dynamic_followup_tools(workforce: AgentWorkforce) -> Iterable[tuple[str, dict[str, Any], dict[str, Any]]]:
    agent_configs = workforce.agent_configs or {}
    if not isinstance(agent_configs, dict):
        return

    for fallback_key, agent_config in agent_configs.items():
        if not isinstance(agent_config, dict):
            continue
        agent_profile = agent_config.get("agent") if isinstance(agent_config.get("agent"), dict) else {}
        agent_key = str(agent_profile.get("key") or fallback_key or "").strip()
        if not agent_key:
            continue
        tools = agent_config.get("tools") if isinstance(agent_config.get("tools"), list) else []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            if str(tool.get("id") or "").strip() != DYNAMIC_FOLLOWUP_TOOL_ID:
                continue
            if tool.get("enabled", True) is False:
                continue
            normalized = _normalize_dynamic_followup_settings(tool.get("settings") or {})
            if not normalized["enabled"]:
                continue
            yield agent_key, agent_config, normalized


def _phone_candidates(phone: Any) -> list[str]:
    raw = str(phone or "").strip()
    digits = re.sub(r"\D+", "", raw)
    candidates: list[str] = []
    for value in (raw, digits):
        if value and value not in candidates:
            candidates.append(value)
    if digits.startswith("55") and len(digits) > 11:
        local = digits[2:]
        if local not in candidates:
            candidates.append(local)
    elif len(digits) in {10, 11}:
        brazil = f"55{digits}"
        if brazil not in candidates:
            candidates.append(brazil)
    return candidates


def _find_contact_id(db: Session, lead: Lead) -> Optional[int]:
    phones = _phone_candidates(getattr(lead, "phone", None))
    if not phones:
        return None
    contact = (
        db.query(Contact)
        .filter(Contact.company_id == lead.company_id, Contact.phone.in_(phones))
        .order_by(Contact.id.desc())
        .first()
    )
    return int(contact.id) if contact else None


def _lead_anchor_at(lead: Lead, event_anchor: Optional[datetime]) -> datetime:
    return _as_aware_utc(
        event_anchor
        or getattr(lead, "pipeline_entered_at", None)
        or getattr(lead, "created_at", None)
        or getattr(lead, "data_entrada", None)
    )


def _lead_reached_target_stage(lead: Lead, target_stage_ids: list[int]) -> bool:
    if not target_stage_ids:
        return False
    current_stage_id = _as_int(getattr(lead, "current_stage_id", None))
    return bool(current_stage_id and current_stage_id in target_stage_ids)


def _dynamic_followup_stops_on_appointment(settings: Any) -> bool:
    raw = settings if isinstance(settings, dict) else {}
    return _as_bool(
        raw.get("stop_on_appointment_created", raw.get("stopOnAppointmentCreated")),
        default=True,
    )


def _enrollment_stops_on_appointment(enrollment: AgentDynamicFollowupEnrollment) -> bool:
    snapshot = enrollment.config_snapshot if isinstance(enrollment.config_snapshot, dict) else {}
    settings = snapshot.get("tool_settings") if isinstance(snapshot.get("tool_settings"), dict) else {}
    return _dynamic_followup_stops_on_appointment(settings)


def _lead_has_active_appointment(db: Session, lead: Lead) -> bool:
    if not lead or not getattr(lead, "id", None) or not getattr(lead, "company_id", None):
        return False

    query = db.query(Agendamento.id).filter(
        Agendamento.company_id == lead.company_id,
        Agendamento.lead_id == lead.id,
        Agendamento.consulta_data.isnot(None),
        Agendamento.consulta_data >= _now_utc(),
    )
    for status_prefix in TERMINAL_APPOINTMENT_STATUS_PREFIXES:
        query = query.filter(~Agendamento.status.ilike(f"{status_prefix}%"))

    return query.first() is not None


def _config_matches_lead(settings: dict[str, Any], lead: Lead) -> bool:
    if not getattr(lead, "phone", None):
        return False
    configured_pipeline_id = settings.get("pipeline_id")
    lead_pipeline_id = _as_int(getattr(lead, "pipeline_id", None))
    if not lead_pipeline_id:
        return False
    if configured_pipeline_id and lead_pipeline_id != configured_pipeline_id:
        return False
    if _lead_reached_target_stage(lead, settings.get("target_stage_ids") or []):
        return False
    return bool(settings.get("target_stage_ids") and settings.get("steps"))


def _agent_model(agent_config: dict[str, Any]) -> str:
    model_config = agent_config.get("model")
    if isinstance(model_config, dict):
        return str(model_config.get("model") or DEFAULT_DYNAMIC_FOLLOWUP_MODEL)
    if isinstance(model_config, str) and model_config.strip():
        return model_config.strip()
    return DEFAULT_DYNAMIC_FOLLOWUP_MODEL


def _agent_name(agent_config: dict[str, Any], fallback: str) -> str:
    agent_profile = agent_config.get("agent") if isinstance(agent_config.get("agent"), dict) else {}
    return _clean_text(agent_profile.get("name") or fallback, 120) or "Agente de follow-up"


def _agent_summary(agent_config: dict[str, Any], agent_key: str) -> dict[str, Any]:
    agent_profile = agent_config.get("agent") if isinstance(agent_config.get("agent"), dict) else {}
    objective = agent_config.get("objective") if isinstance(agent_config.get("objective"), dict) else {}
    prompt = agent_config.get("prompt_techniques") if isinstance(agent_config.get("prompt_techniques"), dict) else {}
    channel = agent_config.get("channel") if isinstance(agent_config.get("channel"), dict) else {}
    return {
        "key": agent_key,
        "name": agent_profile.get("name"),
        "role": agent_profile.get("role"),
        "tone": agent_profile.get("tone"),
        "language": agent_profile.get("language") or "pt-BR",
        "primary_goal": objective.get("primary_goal"),
        "prompt_context": prompt.get("context"),
        "instructions": prompt.get("instructions") if isinstance(prompt.get("instructions"), list) else [],
        "constraints": prompt.get("constraints") if isinstance(prompt.get("constraints"), list) else [],
        "conversation_rules": prompt.get("conversation_rules") if isinstance(prompt.get("conversation_rules"), list) else [],
        "message_style": channel.get("message_style"),
        "model": _agent_model(agent_config),
    }


def _config_snapshot(
    *,
    workforce: AgentWorkforce,
    agent_key: str,
    agent_config: dict[str, Any],
    settings: dict[str, Any],
    event_name: str,
) -> dict[str, Any]:
    return {
        "tool_id": DYNAMIC_FOLLOWUP_TOOL_ID,
        "event_name": event_name,
        "tool_settings": settings,
        "workforce": {
            "id": workforce.id,
            "name": workforce.name,
            "version": workforce.version,
            "channel": workforce.channel,
        },
        "agent": _agent_summary(agent_config, agent_key),
    }


def _step_by_number(config_snapshot: dict[str, Any], step_number: int) -> Optional[dict[str, Any]]:
    settings = config_snapshot.get("tool_settings") if isinstance(config_snapshot, dict) else {}
    steps = settings.get("steps") if isinstance(settings, dict) else []
    if not isinstance(steps, list):
        return None
    for step in steps:
        if isinstance(step, dict) and int(step.get("step_number") or 0) == step_number:
            return step
    return None


def _create_scheduled_execution(
    db: Session,
    enrollment: AgentDynamicFollowupEnrollment,
    step: dict[str, Any],
    scheduled_for: datetime,
) -> AgentDynamicFollowupExecution:
    execution = AgentDynamicFollowupExecution(
        enrollment_id=enrollment.id,
        company_id=enrollment.company_id,
        workforce_id=enrollment.workforce_id,
        lead_id=enrollment.lead_id,
        agent_key=enrollment.agent_key,
        step_number=int(step["step_number"]),
        channel=str(step.get("channel") or "whatsapp"),
        objective=step.get("objective"),
        mini_prompt=step["mini_prompt"],
        status=EXECUTION_SCHEDULED,
        scheduled_for=_as_aware_utc(scheduled_for),
    )
    db.add(execution)
    db.flush()
    return execution


def enqueue_dynamic_followup_execution(
    db: Session,
    execution: AgentDynamicFollowupExecution,
) -> bool:
    from backend.worker.tasks_agent_dynamic_followup import enviar_passo_agent_dynamic_followup

    eta = _as_aware_utc(execution.scheduled_for)
    try:
        enqueued, _ = enqueue_company_job_if_active(
            db,
            int(execution.company_id),
            is_still_pending=lambda: (
                db.query(AgentDynamicFollowupExecution.status)
                .filter(AgentDynamicFollowupExecution.id == execution.id)
                .scalar()
                == EXECUTION_SCHEDULED
            ),
            enqueue=lambda: enviar_passo_agent_dynamic_followup.apply_async(
                args=[int(execution.id)],
                eta=eta,
                queue="waha_messages_queue",
            ),
        )
        return enqueued
    except CompanyOperationallyBlockedError:
        return False


def cancel_dynamic_followups_for_lead_stage(
    db: Session,
    *,
    lead: Lead,
    reason: str = "target_stage_reached",
) -> int:
    if not lead or not getattr(lead, "id", None):
        return 0

    active_enrollments = (
        db.query(AgentDynamicFollowupEnrollment)
        .filter(
            AgentDynamicFollowupEnrollment.company_id == lead.company_id,
            AgentDynamicFollowupEnrollment.lead_id == lead.id,
            AgentDynamicFollowupEnrollment.status == ENROLLMENT_ACTIVE,
        )
        .all()
    )
    if not active_enrollments:
        return 0

    now = _now_utc()
    cancelled = 0
    for enrollment in active_enrollments:
        target_stage_ids = _as_list_int(enrollment.target_stage_ids)
        if not _lead_reached_target_stage(lead, target_stage_ids):
            continue
        enrollment.status = ENROLLMENT_COMPLETED
        enrollment.completed_at = now
        enrollment.cancel_reason = reason
        enrollment.updated_at = now
        cancelled += 1

        db.query(AgentDynamicFollowupExecution).filter(
            AgentDynamicFollowupExecution.enrollment_id == enrollment.id,
            AgentDynamicFollowupExecution.status.in_([EXECUTION_SCHEDULED, EXECUTION_PROCESSING]),
        ).update(
            {
                AgentDynamicFollowupExecution.status: EXECUTION_CANCELED,
                AgentDynamicFollowupExecution.error_message: reason,
                AgentDynamicFollowupExecution.updated_at: now,
            },
            synchronize_session=False,
        )

    if cancelled:
        db.commit()
        logger.info(
            "[DynamicFollowup] Cancelled %s enrollment(s) for lead_id=%s reason=%s",
            cancelled,
            lead.id,
            reason,
        )
    return cancelled


def cancel_dynamic_followups_for_lead_appointment(
    db: Session,
    *,
    lead: Lead,
    reason: str = "appointment_created",
) -> int:
    if not lead or not getattr(lead, "id", None):
        return 0

    active_enrollments = (
        db.query(AgentDynamicFollowupEnrollment)
        .filter(
            AgentDynamicFollowupEnrollment.company_id == lead.company_id,
            AgentDynamicFollowupEnrollment.lead_id == lead.id,
            AgentDynamicFollowupEnrollment.status == ENROLLMENT_ACTIVE,
        )
        .all()
    )
    if not active_enrollments:
        return 0

    now = _now_utc()
    cancelled = 0
    for enrollment in active_enrollments:
        if not _enrollment_stops_on_appointment(enrollment):
            continue
        enrollment.status = ENROLLMENT_COMPLETED
        enrollment.completed_at = now
        enrollment.cancel_reason = reason
        enrollment.updated_at = now
        cancelled += 1

        db.query(AgentDynamicFollowupExecution).filter(
            AgentDynamicFollowupExecution.enrollment_id == enrollment.id,
            AgentDynamicFollowupExecution.status.in_([EXECUTION_SCHEDULED, EXECUTION_PROCESSING]),
        ).update(
            {
                AgentDynamicFollowupExecution.status: EXECUTION_CANCELED,
                AgentDynamicFollowupExecution.error_message: reason,
                AgentDynamicFollowupExecution.updated_at: now,
            },
            synchronize_session=False,
        )

    if cancelled:
        db.commit()
        logger.info(
            "[DynamicFollowup] Cancelled %s enrollment(s) for lead_id=%s reason=%s",
            cancelled,
            lead.id,
            reason,
        )
    return cancelled


def cancel_dynamic_followups_for_appointment(
    db: Session,
    *,
    appointment: Agendamento,
    reason: str = "appointment_created",
) -> int:
    if not appointment or not getattr(appointment, "lead_id", None):
        return 0

    status = str(getattr(appointment, "status", "") or "").upper()
    if any(status.startswith(prefix) for prefix in TERMINAL_APPOINTMENT_STATUS_PREFIXES):
        return 0

    lead = (
        db.query(Lead)
        .filter(
            Lead.id == appointment.lead_id,
            Lead.company_id == appointment.company_id,
        )
        .first()
    )
    if not lead:
        return 0

    return cancel_dynamic_followups_for_lead_appointment(db, lead=lead, reason=reason)


def handle_dynamic_followup_for_lead(
    db: Session,
    *,
    lead: Lead,
    event_name: str,
    anchor_at: Optional[datetime] = None,
) -> dict[str, int]:
    """Start or stop dynamic follow-up enrollments for a CRM lead event."""

    if not lead or not getattr(lead, "company_id", None) or not getattr(lead, "id", None):
        return {"started": 0, "cancelled": 0, "skipped": 0}

    cancelled = cancel_dynamic_followups_for_lead_stage(
        db,
        lead=lead,
        reason=f"{event_name}:target_stage_reached",
    )

    workforces = (
        db.query(AgentWorkforce)
        .filter(
            AgentWorkforce.company_id == lead.company_id,
            AgentWorkforce.status == "active",
            AgentWorkforce.channel == "whatsapp",
        )
        .all()
    )

    started = 0
    skipped = 0
    anchor = _lead_anchor_at(lead, anchor_at)
    contact_id = _find_contact_id(db, lead)

    for workforce in workforces:
        for agent_key, agent_config, settings in _iter_dynamic_followup_tools(workforce):
            if not _config_matches_lead(settings, lead):
                skipped += 1
                continue
            if settings.get("stop_on_appointment_created") and _lead_has_active_appointment(db, lead):
                skipped += 1
                continue

            existing = (
                db.query(AgentDynamicFollowupEnrollment)
                .filter(
                    AgentDynamicFollowupEnrollment.company_id == lead.company_id,
                    AgentDynamicFollowupEnrollment.lead_id == lead.id,
                    AgentDynamicFollowupEnrollment.workforce_id == workforce.id,
                    AgentDynamicFollowupEnrollment.agent_key == agent_key,
                    AgentDynamicFollowupEnrollment.status == ENROLLMENT_ACTIVE,
                )
                .first()
            )
            if existing:
                skipped += 1
                continue

            snapshot = _config_snapshot(
                workforce=workforce,
                agent_key=agent_key,
                agent_config=agent_config,
                settings=settings,
                event_name=event_name,
            )
            try:
                fence_company_job_mutation(db, int(lead.company_id))
            except CompanyOperationallyBlockedError:
                logger.info(
                    "[DynamicFollowup] Company blocked before enrollment company_id=%s",
                    lead.company_id,
                )
                return {
                    "started": started,
                    "cancelled": cancelled,
                    "skipped": skipped + 1,
                }
            enrollment = AgentDynamicFollowupEnrollment(
                company_id=lead.company_id,
                workforce_id=workforce.id,
                agent_key=agent_key,
                lead_id=lead.id,
                contact_id=contact_id,
                pipeline_id=lead.pipeline_id,
                start_stage_id=lead.current_stage_id,
                target_stage_ids=settings["target_stage_ids"],
                status=ENROLLMENT_ACTIVE,
                next_step_number=1,
                anchor_at=anchor,
                started_at=_now_utc(),
                config_snapshot=snapshot,
            )
            db.add(enrollment)
            db.flush()

            first_step = settings["steps"][0]
            execution = _create_scheduled_execution(
                db,
                enrollment,
                first_step,
                _scheduled_for_step(anchor, first_step, settings),
            )
            db.commit()
            if enqueue_dynamic_followup_execution(db, execution):
                started += 1
            else:
                skipped += 1
            logger.info(
                "[DynamicFollowup] Started enrollment_id=%s execution_id=%s lead_id=%s workforce_id=%s agent_key=%s",
                enrollment.id,
                execution.id,
                lead.id,
                workforce.id,
                agent_key,
            )

    return {"started": started, "cancelled": cancelled, "skipped": skipped}


def _lead_payload(db: Session, lead: Lead) -> dict[str, Any]:
    stage = None
    if getattr(lead, "current_stage_id", None):
        stage = db.query(PipelineStage).filter(PipelineStage.id == lead.current_stage_id).first()
    return {
        "id": lead.id,
        "name": lead.name,
        "phone": lead.phone,
        "company_id": lead.company_id,
        "client_id": lead.client_id,
        "source_id": lead.source_id,
        "pipeline_id": lead.pipeline_id,
        "current_stage_id": lead.current_stage_id,
        "current_stage_name": stage.name if stage else None,
        "created_at": getattr(lead, "created_at", None),
        "data_entrada": getattr(lead, "data_entrada", None),
        "pipeline_entered_at": getattr(lead, "pipeline_entered_at", None),
        "last_stage_move_at": getattr(lead, "last_stage_move_at", None),
    }


def _load_recent_conversation_context(
    db: Session,
    *,
    company_id: int,
    phone: str,
    limit: int = 14,
) -> list[dict[str, Any]]:
    phones = _phone_candidates(phone)
    if not phones:
        return []
    messages = (
        db.query(Message)
        .filter(Message.company_id == company_id, Message.contact_phone.in_(phones))
        .order_by(Message.timestamp.desc())
        .limit(limit)
        .all()
    )
    rows: list[dict[str, Any]] = []
    for message in reversed(messages):
        content = _clean_text(getattr(message, "content", ""), 900)
        message_type = str(getattr(message, "message_type", "") or "text")
        if message_type != "text" and not content:
            content = f"[{message_type}]"
        rows.append(
            {
                "from": "empresa" if message.from_me else "lead",
                "type": message_type,
                "content": content,
                "timestamp": getattr(message, "timestamp", None),
            }
        )
    return rows


def _load_previous_followups(
    db: Session,
    *,
    enrollment_id: int,
    current_step_number: int,
) -> list[dict[str, Any]]:
    executions = (
        db.query(AgentDynamicFollowupExecution)
        .filter(
            AgentDynamicFollowupExecution.enrollment_id == enrollment_id,
            AgentDynamicFollowupExecution.step_number < current_step_number,
            AgentDynamicFollowupExecution.status == EXECUTION_SUCCESS,
        )
        .order_by(AgentDynamicFollowupExecution.step_number.asc())
        .all()
    )
    return [
        {
            "step_number": execution.step_number,
            "objective": execution.objective,
            "message": _clean_text(execution.generated_message, 1200),
            "sent_at": execution.executed_at,
        }
        for execution in executions
    ]


def _truncate_prompt_payload(payload: dict[str, Any]) -> dict[str, Any]:
    serialized = json.dumps(_json_safe(payload), ensure_ascii=False, default=str)
    if len(serialized) <= MAX_PROMPT_CHARS:
        return _json_safe(payload)
    payload = dict(payload)
    payload["conversation"] = payload.get("conversation", [])[-8:]
    payload["previous_followups"] = payload.get("previous_followups", [])[-4:]
    serialized = json.dumps(_json_safe(payload), ensure_ascii=False, default=str)
    if len(serialized) > MAX_PROMPT_CHARS:
        payload["conversation"] = []
    return _json_safe(payload)


def _build_generation_payload(
    db: Session,
    *,
    enrollment: AgentDynamicFollowupEnrollment,
    execution: AgentDynamicFollowupExecution,
    lead: Lead,
) -> dict[str, Any]:
    snapshot = enrollment.config_snapshot or {}
    agent = snapshot.get("agent") if isinstance(snapshot, dict) else {}
    return _truncate_prompt_payload(
        {
            "task": "generate_dynamic_crm_followup_message",
            "channel": "whatsapp",
            "step_number": execution.step_number,
            "objective": execution.objective,
            "mini_prompt": execution.mini_prompt,
            "lead": _lead_payload(db, lead),
            "target_stage_ids": enrollment.target_stage_ids or [],
            "agent": agent if isinstance(agent, dict) else {},
            "conversation": _load_recent_conversation_context(
                db,
                company_id=int(enrollment.company_id),
                phone=str(lead.phone or ""),
            ),
            "previous_followups": _load_previous_followups(
                db,
                enrollment_id=int(enrollment.id),
                current_step_number=int(execution.step_number),
            ),
            "current_time": _now_utc(),
        }
    )


def _generation_instructions(agent_summary: dict[str, Any]) -> str:
    agent_name = _clean_text(agent_summary.get("name"), 120) or "Agente"
    agent_role = _clean_text(agent_summary.get("role"), 240)
    tone = _clean_text(agent_summary.get("tone"), 240) or "consultivo, claro e humano"
    primary_goal = _clean_text(agent_summary.get("primary_goal"), 1000)
    instructions = agent_summary.get("instructions") if isinstance(agent_summary.get("instructions"), list) else []
    constraints = agent_summary.get("constraints") if isinstance(agent_summary.get("constraints"), list) else []
    rules = agent_summary.get("conversation_rules") if isinstance(agent_summary.get("conversation_rules"), list) else []

    extra_lines = []
    for label, values in (
        ("Instrucoes do agente", instructions),
        ("Restricoes", constraints),
        ("Regras de conversa", rules),
    ):
        clean_values = [_clean_text(value, 500) for value in values if _clean_text(value, 500)]
        if clean_values:
            extra_lines.append(f"{label}:\n- " + "\n- ".join(clean_values[:8]))

    return "\n".join(
        [
            f"Voce e {agent_name}.",
            f"Papel: {agent_role or 'gerar follow-up comercial por WhatsApp'}.",
            f"Tom: {tone}.",
            f"Objetivo principal do agente: {primary_goal or 'avancar o lead no funil sem soar robotico'}.",
            "",
            "Gere apenas a mensagem final para WhatsApp, sem aspas, sem markdown e sem explicacoes.",
            "Use o contexto da conversa, o mini-prompt do passo e o estado atual do CRM.",
            "Nao invente fatos, promessas, descontos, disponibilidade ou dados que nao estejam no contexto.",
            "Se houver nome do lead, use de forma natural. Prefira mensagens curtas e acionaveis.",
            "Nao mencione que a mensagem foi gerada por IA ou por uma automacao.",
            *extra_lines,
        ]
    )


def _sanitize_generated_message(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^```(?:\w+)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip().strip('"').strip("'").strip()
    if len(text) > MAX_MESSAGE_CHARS:
        text = text[:MAX_MESSAGE_CHARS].rstrip()
    if not text:
        raise ValueError("Agents SDK returned an empty follow-up message")
    return text


async def _run_generation_agent(
    *,
    agent: Agent[Any],
    payload: dict[str, Any],
    trace_context: dict[str, Any],
    run_config: Any,
) -> Any:
    with openai_run_trace(
        run_config,
        workflow_name=trace_context["workflow_name"],
        group_id=trace_context["group_id"],
        trace_id=trace_context["trace_id"],
        metadata=trace_context["metadata"],
    ):
        return await Runner.run(
            agent,
            [
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False, default=str),
                }
            ],
            max_turns=3,
            run_config=run_config,
        )


def _run_coroutine_sync(coro_factory: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(lambda: asyncio.run(coro_factory()))
        return future.result()


def _generate_dynamic_followup_message(
    db: Session,
    *,
    enrollment: AgentDynamicFollowupEnrollment,
    execution: AgentDynamicFollowupExecution,
    lead: Lead,
) -> tuple[str, dict[str, Any], Any, str]:
    payload = _build_generation_payload(
        db,
        enrollment=enrollment,
        execution=execution,
        lead=lead,
    )
    snapshot = enrollment.config_snapshot or {}
    agent_summary = snapshot.get("agent") if isinstance(snapshot.get("agent"), dict) else {}
    model = _clean_text(agent_summary.get("model"), 80) or DEFAULT_DYNAMIC_FOLLOWUP_MODEL
    agent_name = _agent_name({"agent": agent_summary, "model": {"model": model}}, execution.agent_key)
    sdk_agent = Agent(
        name=f"{agent_name} Follow-up",
        instructions=_generation_instructions(agent_summary),
        model=model,
    )
    trace_id = f"trace_dynamic_followup_{enrollment.company_id}_{execution.id}_{uuid.uuid4().hex[:12]}"
    trace_context = {
        "workflow_name": f"agent_dynamic_followup.{enrollment.company_id}.{enrollment.workforce_id}",
        "group_id": f"conv_{lead.phone}_company{enrollment.company_id}",
        "trace_id": trace_id,
        "metadata": {
            "source": "agent_dynamic_followup",
            "company_id": str(enrollment.company_id),
            "lead_id": str(enrollment.lead_id),
            "workforce_id": str(enrollment.workforce_id),
            "agent_key": str(enrollment.agent_key),
            "execution_id": str(execution.id),
            "step_number": str(execution.step_number),
            "phone": str(lead.phone or ""),
        },
    }
    run_config = build_company_openai_run_config(
        db,
        int(enrollment.company_id),
        tracing_disabled=True,
        model_override=None,
    )

    result = _run_coroutine_sync(
        lambda: _run_generation_agent(
            agent=sdk_agent,
            payload=payload,
            trace_context=trace_context,
            run_config=run_config,
        )
    )
    message = _sanitize_generated_message(getattr(result, "final_output", ""))
    usage = getattr(getattr(result, "context_wrapper", None), "usage", None)
    return message, payload, usage, model


def _mark_execution_terminal(
    db: Session,
    *,
    execution: AgentDynamicFollowupExecution,
    enrollment: AgentDynamicFollowupEnrollment,
    status: str,
    reason: str,
    complete_enrollment: bool = False,
) -> None:
    now = _now_utc()
    execution.status = status
    execution.executed_at = now
    execution.error_message = reason
    execution.updated_at = now
    if complete_enrollment:
        enrollment.status = ENROLLMENT_COMPLETED if status in {EXECUTION_SKIPPED, EXECUTION_CANCELED} else ENROLLMENT_FAILED
        enrollment.completed_at = now
        enrollment.cancel_reason = reason if enrollment.status == ENROLLMENT_COMPLETED else None
        enrollment.last_error = reason if enrollment.status == ENROLLMENT_FAILED else None
        enrollment.updated_at = now
    db.commit()


def execute_dynamic_followup_execution(db: Session, execution_id: int) -> dict[str, Any]:
    execution = (
        db.query(AgentDynamicFollowupExecution)
        .filter(AgentDynamicFollowupExecution.id == execution_id)
        .with_for_update()
        .first()
    )
    if not execution:
        logger.warning("[DynamicFollowup] Execution %s not found", execution_id)
        return {"status": "not_found"}

    enrollment = execution.enrollment
    if execution.status != EXECUTION_SCHEDULED:
        return {"status": "ignored", "execution_status": execution.status}
    if not enrollment or enrollment.status != ENROLLMENT_ACTIVE:
        execution.status = EXECUTION_SKIPPED
        execution.executed_at = _now_utc()
        execution.error_message = "enrollment_not_active"
        db.commit()
        return {"status": "skipped", "reason": "enrollment_not_active"}

    lead = db.query(Lead).filter(Lead.id == execution.lead_id).first()
    if not lead or not getattr(lead, "phone", None):
        _mark_execution_terminal(
            db,
            execution=execution,
            enrollment=enrollment,
            status=EXECUTION_FAILED,
            reason="lead_or_phone_not_found",
            complete_enrollment=True,
        )
        return {"status": "failed", "reason": "lead_or_phone_not_found"}

    if _lead_reached_target_stage(lead, _as_list_int(enrollment.target_stage_ids)):
        _mark_execution_terminal(
            db,
            execution=execution,
            enrollment=enrollment,
            status=EXECUTION_SKIPPED,
            reason="target_stage_reached",
            complete_enrollment=True,
        )
        return {"status": "skipped", "reason": "target_stage_reached"}

    if _enrollment_stops_on_appointment(enrollment) and _lead_has_active_appointment(db, lead):
        _mark_execution_terminal(
            db,
            execution=execution,
            enrollment=enrollment,
            status=EXECUTION_SKIPPED,
            reason="appointment_exists",
            complete_enrollment=True,
        )
        return {"status": "skipped", "reason": "appointment_exists"}

    execution.status = EXECUTION_PROCESSING
    execution.updated_at = _now_utc()
    db.commit()

    usage = None
    model = DEFAULT_DYNAMIC_FOLLOWUP_MODEL
    try:
        generated_message, prompt_payload, usage, model = _generate_dynamic_followup_message(
            db,
            enrollment=enrollment,
            execution=execution,
            lead=lead,
        )

        db.refresh(lead)
        execution = db.query(AgentDynamicFollowupExecution).filter(
            AgentDynamicFollowupExecution.id == execution_id
        ).first()
        enrollment = execution.enrollment if execution else enrollment
        if not execution or not enrollment:
            return {"status": "failed", "reason": "execution_missing_before_send"}
        if execution.status != EXECUTION_PROCESSING or enrollment.status != ENROLLMENT_ACTIVE:
            return {
                "status": "skipped",
                "reason": "execution_or_enrollment_cancelled_before_send",
            }

        if _lead_reached_target_stage(lead, _as_list_int(enrollment.target_stage_ids)):
            _mark_execution_terminal(
                db,
                execution=execution,
                enrollment=enrollment,
                status=EXECUTION_SKIPPED,
                reason="target_stage_reached_before_send",
                complete_enrollment=True,
            )
            return {"status": "skipped", "reason": "target_stage_reached_before_send"}

        if _enrollment_stops_on_appointment(enrollment) and _lead_has_active_appointment(db, lead):
            _mark_execution_terminal(
                db,
                execution=execution,
                enrollment=enrollment,
                status=EXECUTION_SKIPPED,
                reason="appointment_exists_before_send",
                complete_enrollment=True,
            )
            return {"status": "skipped", "reason": "appointment_exists_before_send"}

        provider_response = send_text(
            company_id=int(enrollment.company_id),
            phone=str(lead.phone),
            message=generated_message,
            db=db,
            human_mode=False,
        )

        now = _now_utc()
        execution = db.query(AgentDynamicFollowupExecution).filter(
            AgentDynamicFollowupExecution.id == execution_id
        ).first()
        enrollment = execution.enrollment if execution else enrollment
        if not execution or not enrollment:
            return {"status": "failed", "reason": "execution_missing_after_send"}

        execution.status = EXECUTION_SUCCESS
        execution.executed_at = now
        execution.generated_message = generated_message
        execution.prompt_payload = prompt_payload
        execution.openai_usage = extract_openai_usage(usage)
        execution.provider_response = _json_safe(provider_response)
        execution.updated_at = now
        enrollment.last_sent_at = now
        enrollment.next_step_number = int(execution.step_number) + 1
        enrollment.updated_at = now

        next_step = _step_by_number(enrollment.config_snapshot or {}, int(execution.step_number) + 1)
        next_execution_id = None
        if next_step:
            snapshot_settings = (enrollment.config_snapshot or {}).get("tool_settings")
            if not isinstance(snapshot_settings, dict):
                snapshot_settings = {}
            next_execution = _create_scheduled_execution(
                db,
                enrollment,
                next_step,
                _scheduled_for_step(now, next_step, snapshot_settings),
            )
            next_execution_id = next_execution.id
        else:
            enrollment.status = ENROLLMENT_COMPLETED
            enrollment.completed_at = now

        db.commit()

        if next_execution_id:
            next_execution = db.query(AgentDynamicFollowupExecution).filter(
                AgentDynamicFollowupExecution.id == next_execution_id
            ).first()
            if next_execution:
                enqueue_dynamic_followup_execution(db, next_execution)

        safe_record_openai_text_usage(
            db=db,
            company_id=int(enrollment.company_id),
            usage=usage,
            model=model,
            status="success",
            agent_key=str(enrollment.agent_key),
            agent_name=str((enrollment.config_snapshot or {}).get("agent", {}).get("name") or ""),
            phone=str(lead.phone or ""),
            conversation_group=f"conv_{lead.phone}_company{enrollment.company_id}",
            usage_metadata={
                "source": "agent_dynamic_followup",
                "workforce_id": int(enrollment.workforce_id),
                "enrollment_id": int(enrollment.id),
                "execution_id": int(execution.id),
                "step_number": int(execution.step_number),
            },
        )

        return {
            "status": "success",
            "execution_id": execution.id,
            "next_execution_id": next_execution_id,
        }
    except Exception as exc:
        safe_error = safe_ai_provider_runtime_error(
            exc,
            fallback="Não foi possível gerar o follow-up com IA",
        )
        logger.error(
            "[DynamicFollowup] Failed execution_id=%s error_type=%s",
            execution_id,
            type(exc).__name__,
        )
        db.rollback()
        execution = db.query(AgentDynamicFollowupExecution).filter(
            AgentDynamicFollowupExecution.id == execution_id
        ).first()
        if execution:
            enrollment = execution.enrollment
            now = _now_utc()
            execution.status = EXECUTION_FAILED
            execution.executed_at = now
            execution.openai_usage = extract_openai_usage(usage)
            execution.error_message = safe_error
            execution.updated_at = now
            if enrollment:
                enrollment.status = ENROLLMENT_FAILED
                enrollment.last_error = safe_error
                enrollment.completed_at = now
                enrollment.updated_at = now
            db.commit()
        safe_record_openai_text_usage(
            db=db,
            company_id=int(execution.company_id) if execution else 0,
            usage=usage,
            model=model,
            status="failed",
            agent_key=str(execution.agent_key) if execution else None,
            phone=str(getattr(lead, "phone", "") or ""),
            usage_metadata={
                "source": "agent_dynamic_followup",
                "execution_id": execution_id,
            },
            error_message=safe_error,
        )
        return {"status": "failed", "reason": safe_error}
