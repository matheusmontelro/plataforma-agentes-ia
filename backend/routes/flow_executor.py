"""
Flow Executor API Routes

Provides endpoints for executing flow nodes from the FlowBuilder.
"""

import logging
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.models import User
from backend.auth import get_current_user
from backend.services.flow_agent_runner import run_agent_response
from backend.services.flow_agent_workforce_runner import run_agent_workforce_response
from backend.services.telegram_service import (
    TelegramConfigurationError,
    decrypt_bot_token,
    get_company_telegram_integration,
    send_telegram_text,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class AgentExecutionRequest(BaseModel):
    """Request model for agent execution"""
    agent_config_id: int
    message: str
    conversation_history: Optional[List[Dict[str, str]]] = None


class AgentExecutionResponse(BaseModel):
    """Response model for agent execution"""
    success: bool
    response: str
    error: Optional[str] = None
    tokens_used: Optional[int] = None


class AgentWorkforceExecutionRequest(BaseModel):
    workforce_id: int
    message: str
    conversation_history: Optional[List[Dict[str, str]]] = None
    allow_inactive: bool = False


class AgentWorkforceExecutionResponse(BaseModel):
    success: bool
    response: str
    error: Optional[str] = None
    tokens_used: Optional[int] = None
    workforce_id: Optional[int] = None
    workforce_name: Optional[str] = None
    root_agent_key: Optional[str] = None
    root_agent_name: Optional[str] = None
    handoff_target: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class TelegramExecutionRequest(BaseModel):
    message: str
    chat_id: Optional[str] = None
    parse_mode: Optional[str] = "HTML"
    disable_web_page_preview: bool = True


class TelegramExecutionResponse(BaseModel):
    success: bool
    message_id: Optional[int] = None
    chat_id: Optional[str] = None
    error: Optional[str] = None


@router.post("/flow/run-agent", response_model=AgentExecutionResponse)
async def execute_agent_node(
    request: AgentExecutionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Executes an Agent SDK node in the FlowBuilder.

    This endpoint is called by the AgentResponseNode in the frontend
    to generate AI responses using the saved agent prompt.

    Args:
        request: Contains agent_config_id, message, and optional conversation_history

    Returns:
        AgentExecutionResponse with the AI-generated response
    """
    logger.info(f"[FlowExecutor] Running agent {request.agent_config_id} for user {current_user.id}")
    logger.info(f"[FlowExecutor] Message length: {len(request.message)}")
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    try:
        result = run_agent_response(
            db=db,
            company_id=int(current_user.company_id),
            agent_config_id=request.agent_config_id,
            message=request.message,
            conversation_history=request.conversation_history
        )

        return AgentExecutionResponse(
            success=result.get("success", False),
            response=result.get("response", ""),
            error=result.get("error"),
            tokens_used=result.get("tokens_used")
        )

    except Exception as e:
        logger.exception(f"[FlowExecutor] Error executing agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run-agent-workforce", response_model=AgentWorkforceExecutionResponse)
async def execute_agent_workforce_node(
    request: AgentWorkforceExecutionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    logger.info(
        "[FlowExecutor] Running agent workforce %s for user %s",
        request.workforce_id,
        current_user.id,
    )

    try:
        result = run_agent_workforce_response(
            db=db,
            workforce_id=request.workforce_id,
            company_id=int(current_user.company_id),
            message=request.message,
            conversation_history=request.conversation_history or [],
            runtime_variables={},
            allow_inactive=request.allow_inactive,
        )

        return AgentWorkforceExecutionResponse(
            success=result.get("success", False),
            response=result.get("response", ""),
            error=result.get("error"),
            tokens_used=result.get("tokens_used"),
            workforce_id=result.get("workforce_id"),
            workforce_name=result.get("workforce_name"),
            root_agent_key=result.get("root_agent_key"),
            root_agent_name=result.get("root_agent_name"),
            handoff_target=result.get("handoff_target"),
            metadata=result.get("metadata"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[FlowExecutor] Error executing agent workforce: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run-telegram", response_model=TelegramExecutionResponse)
async def run_telegram_node(
    request: TelegramExecutionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    integration = get_company_telegram_integration(db, int(current_user.company_id))
    if not integration:
        raise HTTPException(
            status_code=400,
            detail="Telegram nao configurado para esta empresa. Configure em Conexoes > Integracoes."
        )

    chat_id = (request.chat_id or integration.default_chat_id or "").strip()
    if not chat_id:
        raise HTTPException(
            status_code=400,
            detail="Telegram chat_id nao configurado no node nem na integracao da empresa"
        )

    parse_mode = request.parse_mode
    if parse_mode and str(parse_mode).lower() == "none":
        parse_mode = None

    logger.info("[FlowExecutor] run-telegram requested by user=%s company=%s", current_user.id, current_user.company_id)

    try:
        bot_token = decrypt_bot_token(integration.bot_token_encrypted)
        result = send_telegram_text(
            bot_token=bot_token,
            chat_id=str(chat_id),
            message=request.message,
            parse_mode=parse_mode,
            disable_web_page_preview=request.disable_web_page_preview,
        )
        return TelegramExecutionResponse(
            success=True,
            message_id=result.get("message_id"),
            chat_id=str(result.get("chat", {}).get("id", chat_id)),
        )
    except TelegramConfigurationError as e:
        logger.warning("[FlowExecutor] Telegram configuration error: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("[FlowExecutor] Error executing telegram node: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
