"""
FlowBuilder business event bridge.

This module connects product events such as appointment changes and CRM stage
movement to FlowBuilder without changing existing webhook/WhatsApp flows.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from sqlalchemy.orm import Session

from backend.models import Agendamento, Flow, FlowEnrollment, FlowStepExecution, Lead, PipelineStage
from backend.services.company_access_control import (
    CompanyOperationallyBlockedError,
    capture_company_job_epoch,
    enqueue_company_job_if_active,
)

logger = logging.getLogger(__name__)

TERMINAL_APPOINTMENT_STATUSES = {"CANCELLED", "CANCELED", "CANCELADO", "DELETED"}


def _as_int(value: Any) -> Optional[int]:
    try:
        if value is None or str(value).strip() == "":
            return None
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def _appointment_payload(appointment: Agendamento, event_name: str) -> Dict[str, Any]:
    anchor_at = appointment.consulta_data
    return {
        "event": event_name,
        "anchor_at": _iso(anchor_at),
        "phone": appointment.phone,
        "name": appointment.nome,
        "lead_id": appointment.lead_id,
        "appointment_id": appointment.id,
        "appointment": {
            "id": appointment.id,
            "lead_id": appointment.lead_id,
            "agenda_id": appointment.agenda_id,
            "status": appointment.status,
            "starts_at": _iso(anchor_at),
            "consulta_data": _iso(anchor_at),
            "created_at": _iso(getattr(appointment, "agendamento_realizado_em", None)),
            "name": appointment.nome,
            "phone": appointment.phone,
            "interest": appointment.interesse,
            "media": appointment.midia,
        },
    }


def _crm_payload(lead: Lead, stage: PipelineStage, moved_at: Optional[datetime]) -> Dict[str, Any]:
    anchor_at = moved_at or datetime.now(timezone.utc)
    return {
        "event": "crm_stage_entered",
        "anchor_at": _iso(anchor_at),
        "phone": lead.phone,
        "name": lead.name,
        "lead_id": lead.id,
        "lead": _lead_payload_data(lead),
        "crm": {
            "event": "crm_stage_entered",
            "event_label": "Entrada em etapa",
        },
        "crm_stage": {
            "lead_id": lead.id,
            "pipeline_id": stage.pipeline_id,
            "stage_id": stage.id,
            "stage_name": stage.name,
            "entered_at": _iso(anchor_at),
        },
    }


def _lead_payload_data(lead: Lead) -> Dict[str, Any]:
    return {
        "id": lead.id,
        "name": lead.name,
        "phone": lead.phone,
        "company_id": lead.company_id,
        "client_id": lead.client_id,
        "source_id": lead.source_id,
        "thumbnail_url": lead.thumbnail_url,
        "sender_lid": lead.sender_lid,
        "pipeline_id": lead.pipeline_id,
        "current_stage_id": lead.current_stage_id,
        "created_at": _iso(lead.created_at),
        "data_entrada": _iso(lead.data_entrada),
    }


def _lead_created_payload(lead: Lead, created_at: Optional[datetime]) -> Dict[str, Any]:
    anchor_at = created_at or lead.created_at or lead.data_entrada or datetime.now(timezone.utc)
    stage_name = "Novo Lead"
    try:
        if lead.current_stage and lead.current_stage.name:
            stage_name = lead.current_stage.name
    except Exception:
        stage_name = "Novo Lead"

    return {
        "event": "lead_created",
        "anchor_at": _iso(anchor_at),
        "phone": lead.phone,
        "name": lead.name,
        "lead_id": lead.id,
        "lead": _lead_payload_data(lead),
        "crm": {
            "event": "lead_created",
            "event_label": "Lead criado",
        },
        "crm_stage": {
            "lead_id": lead.id,
            "pipeline_id": lead.pipeline_id,
            "stage_id": lead.current_stage_id,
            "stage_name": stage_name,
            "entered_at": _iso(anchor_at),
        },
    }


def _flow_events(config: Dict[str, Any]) -> Iterable[str]:
    raw_events = config.get("events")
    if raw_events is None:
        raw_events = config.get("event")
    return [str(event).strip() for event in _as_list(raw_events) if str(event).strip()]


def _matches_appointment_flow(flow: Flow, appointment: Agendamento, event_name: str) -> bool:
    config = flow.trigger_config or {}
    events = _flow_events(config)
    if events and event_name not in events:
        return False

    agenda_id = _as_int(config.get("agenda_id"))
    if agenda_id and appointment.agenda_id != agenda_id:
        return False

    status_filter = str(config.get("status") or "").strip()
    if status_filter and str(appointment.status or "").upper() != status_filter.upper():
        return False

    return True


def _matches_crm_flow(
    flow: Flow,
    lead: Lead,
    stage: Optional[PipelineStage],
    event_name: str,
) -> bool:
    config = flow.trigger_config or {}
    events = _flow_events(config)
    if events:
        if event_name not in events:
            return False
    elif event_name != "crm_stage_entered":
        # Fluxos antigos de CRM nao gravavam o evento e significam "entrada em etapa".
        return False

    stage_id = _as_int(config.get("stage_id"))
    if stage_id and (not stage or stage.id != stage_id):
        return False

    pipeline_id = _as_int(config.get("pipeline_id"))
    if pipeline_id:
        flow_pipeline_id = stage.pipeline_id if stage else lead.pipeline_id
        if flow_pipeline_id != pipeline_id:
            return False

    if event_name == "crm_stage_entered" and not stage:
        return False

    return True


def cancel_appointment_flow_enrollments(
    db: Session,
    *,
    company_id: int,
    appointment_id: int,
    reason: str,
) -> int:
    enrollments = db.query(FlowEnrollment).filter(
        FlowEnrollment.company_id == company_id,
        FlowEnrollment.appointment_id == appointment_id,
        FlowEnrollment.status == "active",
    ).all()

    if not enrollments:
        return 0

    enrollment_ids = [enrollment.id for enrollment in enrollments]
    now = datetime.now(timezone.utc)
    for enrollment in enrollments:
        enrollment.status = "cancelled"
        enrollment.cancel_reason = reason
        enrollment.updated_at = now

    db.query(FlowStepExecution).filter(
        FlowStepExecution.enrollment_id.in_(enrollment_ids),
        FlowStepExecution.status.in_(["scheduled", "running"]),
    ).update(
        {
            FlowStepExecution.status: "cancelled",
            FlowStepExecution.error_message: reason,
            FlowStepExecution.updated_at: now,
        },
        synchronize_session=False,
    )
    db.commit()
    logger.info(
        "[FlowEventService] Cancelled %s appointment flow enrollment(s), appointment_id=%s reason=%s",
        len(enrollments),
        appointment_id,
        reason,
    )
    return len(enrollments)


def _cancel_existing_crm_enrollment(db: Session, flow_id: int, lead_id: int, reason: str) -> None:
    now = datetime.now(timezone.utc)
    enrollments = db.query(FlowEnrollment).filter(
        FlowEnrollment.flow_id == flow_id,
        FlowEnrollment.lead_id == lead_id,
        FlowEnrollment.status == "active",
    ).all()
    if not enrollments:
        return

    enrollment_ids = [enrollment.id for enrollment in enrollments]
    for enrollment in enrollments:
        enrollment.status = "cancelled"
        enrollment.cancel_reason = reason
        enrollment.updated_at = now

    db.query(FlowStepExecution).filter(
        FlowStepExecution.enrollment_id.in_(enrollment_ids),
        FlowStepExecution.status.in_(["scheduled", "running"]),
    ).update(
        {
            FlowStepExecution.status: "cancelled",
            FlowStepExecution.error_message: reason,
            FlowStepExecution.updated_at: now,
        },
        synchronize_session=False,
    )


def _start_flow(
    db: Session,
    *,
    flow: Flow,
    trigger_payload: Dict[str, Any],
    lead_id: Optional[int],
    appointment_id: Optional[int],
    pipeline_id: Optional[int],
    stage_id: Optional[int],
    anchor_at: Optional[datetime],
) -> Optional[int]:
    try:
        operational_epoch = capture_company_job_epoch(db, int(flow.company_id))
    except CompanyOperationallyBlockedError:
        logger.info(
            "[FlowEventService] Company blocked before enrollment company_id=%s",
            flow.company_id,
        )
        return None
    trigger_payload = dict(trigger_payload)
    trigger_payload["_operational_epoch"] = operational_epoch

    enrollment = FlowEnrollment(
        flow_id=flow.id,
        company_id=flow.company_id,
        lead_id=lead_id,
        appointment_id=appointment_id,
        pipeline_id=pipeline_id,
        stage_id=stage_id,
        trigger_type=flow.trigger_type,
        anchor_at=anchor_at,
        trigger_payload=trigger_payload,
        status="active",
    )
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)

    from backend.worker.tasks_flow import execute_flow_task

    try:
        enqueued, _ = enqueue_company_job_if_active(
            db,
            int(flow.company_id),
            is_still_pending=lambda: (
                db.query(FlowEnrollment.status)
                .filter(FlowEnrollment.id == enrollment.id)
                .scalar()
                == "active"
            ),
            enqueue=lambda: execute_flow_task.apply_async(
                args=[flow.id, trigger_payload, flow.company_id],
                kwargs={
                    "trigger_type": flow.trigger_type,
                    "enrollment_id": enrollment.id,
                },
                queue="flow_execution_queue",
            ),
        )
    except CompanyOperationallyBlockedError:
        enqueued = False
    if not enqueued:
        logger.info(
            "[FlowEventService] Enrollment cancelled before enqueue enrollment_id=%s",
            enrollment.id,
        )
        return None
    logger.info(
        "[FlowEventService] Started FlowBuilder flow_id=%s enrollment_id=%s trigger_type=%s",
        flow.id,
        enrollment.id,
        flow.trigger_type,
    )
    return enrollment.id


def _handle_dynamic_followup_lead_event(
    db: Session,
    *,
    lead: Lead,
    event_name: str,
    anchor_at: Optional[datetime],
) -> None:
    try:
        from backend.services.agent_dynamic_followup_service import handle_dynamic_followup_for_lead

        result = handle_dynamic_followup_for_lead(
            db,
            lead=lead,
            event_name=event_name,
            anchor_at=anchor_at,
        )
        if result.get("started") or result.get("cancelled"):
            logger.info(
                "[DynamicFollowup] CRM event=%s lead_id=%s result=%s",
                event_name,
                lead.id,
                result,
            )
    except Exception as err:
        try:
            db.rollback()
        except Exception:
            pass
        logger.exception(
            "[DynamicFollowup] Failed to handle CRM event=%s lead_id=%s: %s",
            event_name,
            getattr(lead, "id", None),
            err,
        )


def trigger_appointment_event(db: Session, appointment: Agendamento, event_name: str) -> int:
    if not appointment or not appointment.company_id:
        return 0

    if event_name in {"appointment_rescheduled", "appointment_deleted", "appointment_cancelled"}:
        cancel_appointment_flow_enrollments(
            db,
            company_id=int(appointment.company_id),
            appointment_id=int(appointment.id),
            reason=event_name,
        )

    if event_name in {"appointment_deleted", "appointment_cancelled"}:
        return 0

    if not appointment.consulta_data:
        logger.info(
            "[FlowEventService] Appointment %s has no consulta_data; appointment flows skipped",
            appointment.id,
        )
        return 0

    if str(appointment.status or "").upper() in TERMINAL_APPOINTMENT_STATUSES:
        return 0

    try:
        from backend.services.agent_dynamic_followup_service import cancel_dynamic_followups_for_appointment

        cancelled_dynamic_followups = cancel_dynamic_followups_for_appointment(
            db,
            appointment=appointment,
            reason=f"{event_name}:appointment_active",
        )
        if cancelled_dynamic_followups:
            logger.info(
                "[DynamicFollowup] Appointment event=%s appointment_id=%s cancelled=%s",
                event_name,
                appointment.id,
                cancelled_dynamic_followups,
            )
    except Exception as err:
        try:
            db.rollback()
        except Exception:
            pass
        logger.exception(
            "[DynamicFollowup] Failed to process appointment event=%s appointment_id=%s: %s",
            event_name,
            getattr(appointment, "id", None),
            err,
        )

    flows = db.query(Flow).filter(
        Flow.company_id == appointment.company_id,
        Flow.is_active == True,
        Flow.trigger_type == "appointment",
    ).all()

    started = 0
    payload = _appointment_payload(appointment, event_name)
    for flow in flows:
        if not _matches_appointment_flow(flow, appointment, event_name):
            continue
        if _start_flow(
            db,
            flow=flow,
            trigger_payload=payload,
            lead_id=appointment.lead_id,
            appointment_id=appointment.id,
            pipeline_id=None,
            stage_id=None,
            anchor_at=appointment.consulta_data,
        ):
            started += 1

    return started


def trigger_crm_stage_entered(
    db: Session,
    *,
    lead: Lead,
    stage: PipelineStage,
    moved_at: Optional[datetime],
) -> int:
    if not lead or not stage:
        return 0

    flows = db.query(Flow).filter(
        Flow.company_id == lead.company_id,
        Flow.is_active == True,
        Flow.trigger_type == "crm_stage",
    ).all()

    started = 0
    payload = _crm_payload(lead, stage, moved_at)
    anchor_at = moved_at or datetime.now(timezone.utc)
    for flow in flows:
        if not _matches_crm_flow(flow, lead, stage, "crm_stage_entered"):
            continue
        _cancel_existing_crm_enrollment(db, flow.id, lead.id, "crm_stage_reentered")
        if _start_flow(
            db,
            flow=flow,
            trigger_payload=payload,
            lead_id=lead.id,
            appointment_id=None,
            pipeline_id=stage.pipeline_id,
            stage_id=stage.id,
            anchor_at=anchor_at,
        ):
            started += 1

    if started:
        db.commit()

    _handle_dynamic_followup_lead_event(
        db,
        lead=lead,
        event_name="crm_stage_entered",
        anchor_at=anchor_at,
    )

    return started


def trigger_crm_lead_created(
    db: Session,
    *,
    lead: Lead,
    created_at: Optional[datetime] = None,
    exclude_flow_id: Optional[int] = None,
) -> int:
    if not lead:
        return 0

    query = db.query(Flow).filter(
        Flow.company_id == lead.company_id,
        Flow.is_active == True,
        Flow.trigger_type == "crm_stage",
    )
    if exclude_flow_id:
        query = query.filter(Flow.id != exclude_flow_id)

    started = 0
    anchor_at = created_at or lead.created_at or lead.data_entrada or datetime.now(timezone.utc)
    payload = _lead_created_payload(lead, anchor_at)
    flows = query.all()

    for flow in flows:
        if not _matches_crm_flow(flow, lead, None, "lead_created"):
            continue
        _cancel_existing_crm_enrollment(db, flow.id, lead.id, "lead_created_retriggered")
        if _start_flow(
            db,
            flow=flow,
            trigger_payload=payload,
            lead_id=lead.id,
            appointment_id=None,
            pipeline_id=lead.pipeline_id,
            stage_id=lead.current_stage_id,
            anchor_at=anchor_at,
        ):
            started += 1

    if started:
        db.commit()

    _handle_dynamic_followup_lead_event(
        db,
        lead=lead,
        event_name="lead_created",
        anchor_at=anchor_at,
    )

    return started
