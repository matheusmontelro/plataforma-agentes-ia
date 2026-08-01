"""
Flow Execution Tasks

Celery tasks for executing FlowBuilder flows in the backend.
Handles both webhook-triggered and WhatsApp-triggered flows.
"""

import logging
from typing import Dict, Any, Optional
from celery import Task

from backend.db import SessionLocal
from backend.worker.celery_app import app as celery_app

logger = logging.getLogger(__name__)


class FlowExecutionTask(Task):
    """Base task class with error handling and retries"""

    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 300  # Max 5 minutes between retries
    retry_kwargs = {'max_retries': 3}

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(f"[FlowTask] Task {task_id} failed: {exc}")
        super().on_failure(exc, task_id, args, kwargs, einfo)


@celery_app.task(
    bind=True,
    base=FlowExecutionTask,
    name='backend.worker.tasks_flow.execute_flow_task'
)
def execute_flow_task(
    self,
    flow_id: int,
    trigger_data: Dict[str, Any],
    company_id: int,
    trigger_type: str = 'webhook',
    webhook_uuid: Optional[str] = None,
    enrollment_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Executes a flow completely in the backend.

    Args:
        flow_id: ID of the flow to execute
        trigger_data: Data from the trigger (webhook payload or WhatsApp message)
        company_id: ID of the company
        trigger_type: 'webhook' or 'whatsapp'
        webhook_uuid: UUID of the webhook trigger (for logging)

    Returns:
        Dict with execution results including:
        - success: bool
        - nodes_executed: int
        - execution_log: list of executed nodes
        - error: str (if failed)
    """
    from backend.models import FlowEnrollment
    from backend.services.flow_executor import FlowExecutor
    from backend.services.company_access_control import validate_company_job_epoch

    gate_db = SessionLocal()
    try:
        expected_epoch = trigger_data.get("_operational_epoch")
        access_valid = validate_company_job_epoch(
            gate_db,
            company_id,
            expected_epoch,
        )
        enrollment_active = bool(
            enrollment_id is None
            or gate_db.query(FlowEnrollment.id)
            .filter(
                FlowEnrollment.id == enrollment_id,
                FlowEnrollment.status == "active",
            )
            .first()
        )
        if not access_valid or not enrollment_active:
            return {"success": False, "status": "cancelled", "error": "company_access_suspended"}
    finally:
        gate_db.close()

    logger.info(f"[FlowTask] Starting flow {flow_id} execution (trigger_type={trigger_type})")
    logger.debug(f"[FlowTask] Trigger data: {trigger_data}")

    try:
        # Create executor instance
        executor = FlowExecutor(
            flow_id=flow_id,
            company_id=company_id,
            trigger_data=trigger_data,
            trigger_type=trigger_type,
            enrollment_id=enrollment_id
        )

        # Execute the flow
        result = executor.execute()

        logger.info(
            f"[FlowTask] Flow {flow_id} completed. "
            f"Nodes executed: {result.get('nodes_executed', 0)}, "
            f"Success: {result.get('success', False)}"
        )

        return result

    except Exception as e:
        logger.exception(f"[FlowTask] Error executing flow {flow_id}: {e}")
        raise  # Will trigger retry


@celery_app.task(
    bind=True,
    name='backend.worker.tasks_flow.execute_delayed_node'
)
def execute_delayed_node(
    self,
    flow_id: int,
    node_id: str,
    company_id: int,
    variables: Dict[str, Any],
    trigger_data: Dict[str, Any],
    execution_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Executes a specific node after a delay.
    Used for delay nodes that schedule future execution.

    Args:
        flow_id: ID of the flow
        node_id: ID of the node to execute (and continue from)
        company_id: ID of the company
        variables: Current flow variables state
        trigger_data: Original trigger data

    Returns:
        Dict with execution results
    """
    from backend.services.flow_executor import FlowExecutor
    from backend.services.company_access_control import validate_company_job_epoch

    gate_db = SessionLocal()
    try:
        if not validate_company_job_epoch(
            gate_db,
            company_id,
            trigger_data.get("_operational_epoch"),
        ):
            _finish_delayed_execution(
                execution_id,
                {"success": False, "error": "company_access_suspended"},
            )
            return {"success": False, "status": "cancelled", "error": "company_access_suspended"}
    finally:
        gate_db.close()

    logger.info(f"[FlowTask] Resuming flow {flow_id} from node {node_id} after delay")

    validation = _prepare_delayed_execution(execution_id)
    if validation.get("skip"):
        return validation

    try:
        executor = FlowExecutor(
            flow_id=flow_id,
            company_id=company_id,
            trigger_data=trigger_data,
            trigger_type='delayed',
            enrollment_id=variables.get("flow_enrollment_id")
        )

        # Resume from specific node
        result = executor.execute_from_node(node_id, variables)

        logger.info(f"[FlowTask] Delayed execution completed for flow {flow_id}")
        _finish_delayed_execution(execution_id, result)

        return result

    except Exception as e:
        logger.exception(f"[FlowTask] Error in delayed execution: {e}")
        _finish_delayed_execution(execution_id, {"success": False, "error": str(e)})
        raise


def _prepare_delayed_execution(execution_id: Optional[int]) -> Dict[str, Any]:
    if not execution_id:
        return {"skip": False}

    from datetime import datetime, timezone
    from backend.models import Agendamento, FlowEnrollment, FlowStepExecution, Lead

    db = SessionLocal()
    try:
        execution = db.query(FlowStepExecution).filter(FlowStepExecution.id == execution_id).first()
        if not execution:
            return {"skip": True, "success": False, "error": "flow_step_execution_not_found"}

        enrollment = db.query(FlowEnrollment).filter(FlowEnrollment.id == execution.enrollment_id).first()
        if not enrollment or enrollment.status != "active" or execution.status != "scheduled":
            return {"skip": True, "success": True, "status": "skipped", "reason": "inactive_enrollment_or_execution"}

        if enrollment.appointment_id:
            appointment = db.query(Agendamento).filter(
                Agendamento.id == enrollment.appointment_id,
                Agendamento.company_id == enrollment.company_id,
            ).first()
            if not appointment:
                _mark_execution(db, execution, "cancelled", "appointment_not_found")
                return {"skip": True, "success": True, "status": "cancelled", "reason": "appointment_not_found"}

            if str(appointment.status or "").upper() in {"CANCELLED", "CANCELED", "CANCELADO", "DELETED"}:
                _mark_execution(db, execution, "cancelled", "appointment_cancelled")
                return {"skip": True, "success": True, "status": "cancelled", "reason": "appointment_cancelled"}

            if appointment.consulta_data and enrollment.anchor_at:
                current_anchor = appointment.consulta_data
                expected_anchor = enrollment.anchor_at
                if current_anchor.tzinfo is None:
                    current_anchor = current_anchor.replace(tzinfo=timezone.utc)
                if expected_anchor.tzinfo is None:
                    expected_anchor = expected_anchor.replace(tzinfo=timezone.utc)
                if current_anchor.astimezone(timezone.utc) != expected_anchor.astimezone(timezone.utc):
                    _mark_execution(db, execution, "skipped", "appointment_rescheduled")
                    return {"skip": True, "success": True, "status": "skipped", "reason": "appointment_rescheduled"}

        if enrollment.stage_id and enrollment.lead_id:
            lead = db.query(Lead).filter(
                Lead.id == enrollment.lead_id,
                Lead.company_id == enrollment.company_id,
            ).first()
            if not lead or lead.current_stage_id != enrollment.stage_id:
                _mark_execution(db, execution, "skipped", "lead_left_stage")
                return {"skip": True, "success": True, "status": "skipped", "reason": "lead_left_stage"}

        execution.status = "running"
        execution.updated_at = datetime.now(timezone.utc)
        db.commit()
        return {"skip": False}
    finally:
        db.close()


def _finish_delayed_execution(execution_id: Optional[int], result: Dict[str, Any]) -> None:
    if not execution_id:
        return

    from datetime import datetime, timezone
    from backend.models import FlowStepExecution

    db = SessionLocal()
    try:
        execution = db.query(FlowStepExecution).filter(FlowStepExecution.id == execution_id).first()
        if not execution:
            return

        execution.status = "sent" if result.get("success") else "failed"
        execution.sent_at = datetime.now(timezone.utc) if result.get("success") else None
        execution.error_message = None if result.get("success") else str(result.get("error") or "flow_node_failed")
        execution.updated_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()


def _mark_execution(db, execution, status: str, reason: str) -> None:
    from datetime import datetime, timezone

    execution.status = status
    execution.error_message = reason
    execution.updated_at = datetime.now(timezone.utc)
    db.commit()
