"""Celery tasks for Agent Builder dynamic CRM follow-up."""

from __future__ import annotations

import logging
import os

from backend.db import SessionLocal
from backend.runtime_settings import LOG_DIR as RUNTIME_LOG_DIR
from backend.services.agent_dynamic_followup_service import execute_dynamic_followup_execution

from .celery_app import app

LOG_DIR = str(RUNTIME_LOG_DIR)
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "agent_dynamic_followup.log")

logger = logging.getLogger(__name__)
file_handler = logging.FileHandler(LOG_FILE)
file_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s"
)
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)
logger.setLevel(logging.INFO)


@app.task(name="backend.worker.tasks_agent_dynamic_followup.enviar_passo_agent_dynamic_followup")
def enviar_passo_agent_dynamic_followup(execution_id: int) -> dict:
    """Execute one scheduled dynamic follow-up step."""

    db = SessionLocal()
    try:
        from backend.models import AgentDynamicFollowupExecution
        from backend.services.company_access_control import is_company_operational
        execution = db.query(AgentDynamicFollowupExecution).filter(
            AgentDynamicFollowupExecution.id == int(execution_id)
        ).first()
        if not execution or not is_company_operational(db, int(execution.company_id)):
            return {"status": "cancelled", "reason": "company_access_suspended"}
        logger.info("[DynamicFollowupTask] Starting execution_id=%s", execution_id)
        result = execute_dynamic_followup_execution(db, int(execution_id))
        logger.info("[DynamicFollowupTask] Finished execution_id=%s result=%s", execution_id, result)
        return result
    except Exception as exc:
        logger.exception("[DynamicFollowupTask] Unhandled error execution_id=%s: %s", execution_id, exc)
        db.rollback()
        return {"status": "failed", "reason": str(exc)}
    finally:
        db.close()
