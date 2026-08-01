"""
API Routes for Agents SDK
Independent endpoint for testing the new agent system
"""

import logging
import os
from typing import Dict, Any, Optional, Union
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth import ensure_user_can_access_company, get_current_user
from backend.db import get_db
from backend.models import Client, User
from backend.agents_sdk.agent_builder import AgentCreationConfig, compile_agent_preview
from backend.agents_sdk.tools import SlotsService
from backend.agents_sdk.context import CompanyDataService
from backend.agents_sdk.config import is_company_enabled

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents-sdk", tags=["Agents SDK"])


AuthenticatedUser = Union[Client, User]


def _authorize_company(
    current_user: AuthenticatedUser,
    company_id: int,
    db: Session,
) -> int:
    """Bind request-selected company IDs to the authenticated tenant."""

    ensure_user_can_access_company(current_user, company_id, db)
    return int(company_id)


class ChatRequest(BaseModel):
    company_id: int
    phone: str
    message: str
    include_history: bool = True

class ChatResponse(BaseModel):
    response: str
    metadata: Dict[str, Any]

class SlotsTestRequest(BaseModel):
    company_id: int
    days: int = 7

class SchedulingTestRequest(BaseModel):
    company_id: int
    phone: str
    customer_name: str
    slot_datetime: str  # "dd/mm/yyyy HH:MM"
    service_type: str = "Consulta"

class AgentConfigPreviewResponse(BaseModel):
    instructions: str
    agent_definition: Dict[str, Any]
    warnings: list[str]

class AgentVoiceOption(BaseModel):
    provider: str = "elevenlabs"
    voice_id: str
    name: str
    category: Optional[str] = None
    labels: Dict[str, Any] = Field(default_factory=dict)
    preview_url: Optional[str] = None

class AgentVoiceOptionsResponse(BaseModel):
    provider: str = "elevenlabs"
    voices: list[AgentVoiceOption]
    default_voice_id: Optional[str] = None
    model_id: str = "eleven_flash_v2_5"
    output_format: str = "mp3_44100_128"
    error: Optional[str] = None

@router.post("/agent-config/preview", response_model=AgentConfigPreviewResponse)
async def preview_agent_config(request: AgentCreationConfig):
    """
    Compile a frontend-created agent configuration into an SDK-ready preview.

    This endpoint does not persist or execute the agent. It lets the frontend
    validate prompt techniques, model settings, tools, handoffs, guardrails, and
    the final instruction preview before enabling the agent.
    """
    try:
        return compile_agent_preview(request)
    except Exception as e:
        logger.error(f"Error previewing agent config: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/voice/voices", response_model=AgentVoiceOptionsResponse)
async def list_agent_voice_options(
    current_user: User = Depends(get_current_user)
):
    """
    List ElevenLabs voices available for the authenticated workspace.

    The API key stays server-side; the frontend receives only voice metadata.
    """
    elevenlabs_token = os.getenv("ELEVENLABS_API_KEY")
    model_id = os.getenv("ELEVENLABS_TTS_MODEL_ID", "eleven_flash_v2_5")
    output_format = os.getenv("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128")
    default_voice_id = os.getenv("ELEVENLABS_DEFAULT_VOICE_ID")

    if not elevenlabs_token:
        return AgentVoiceOptionsResponse(
            voices=[],
            default_voice_id=default_voice_id,
            model_id=model_id,
            output_format=output_format,
            error="ELEVENLABS_API_KEY not configured"
        )

    try:
        import httpx

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": elevenlabs_token, "Accept": "application/json"},
            )
            response.raise_for_status()

        payload = response.json()
        raw_voices = payload.get("voices") if isinstance(payload, dict) else []
        voices = [
            AgentVoiceOption(
                voice_id=str(voice.get("voice_id") or ""),
                name=str(voice.get("name") or "Voz sem nome"),
                category=voice.get("category"),
                labels=voice.get("labels") if isinstance(voice.get("labels"), dict) else {},
                preview_url=voice.get("preview_url"),
            )
            for voice in raw_voices
            if isinstance(voice, dict) and voice.get("voice_id")
        ]

        return AgentVoiceOptionsResponse(
            voices=voices,
            default_voice_id=default_voice_id or (voices[0].voice_id if voices else None),
            model_id=model_id,
            output_format=output_format,
        )
    except Exception as e:
        logger.warning("Could not list ElevenLabs voices: %s", e)
        return AgentVoiceOptionsResponse(
            voices=[],
            default_voice_id=default_voice_id,
            model_id=model_id,
            output_format=output_format,
            error="Could not load ElevenLabs voices"
        )

@router.post("/chat", response_model=ChatResponse)
async def chat_with_agent(
    request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Chat with business agent using OpenAI Agents SDK

    Test endpoint for the independent agent system
    """
    company_id = _authorize_company(current_user, request.company_id, db)

    try:
        from backend.agents_sdk.manager import BusinessCompanyManager

        # Create manager instance
        manager = BusinessCompanyManager(company_id=company_id, db=db)

        # Get conversation history if requested
        conversation_history = None
        if request.include_history:
            conversation_history = manager.get_conversation_history(
                phone=request.phone,
                limit=6  # Last 3 exchanges (6 messages)
            )

        # Process conversation
        result = await manager.process_conversation(
            phone=request.phone,
            user_input=request.message,
            conversation_history=conversation_history
        )

        return ChatResponse(
            response=result["response"],
            metadata=result["metadata"]
        )

    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/company/{company_id}/info")
async def get_company_info(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Get company information and embedding status
    """
    company_id = _authorize_company(current_user, company_id, db)

    try:
        organization_data_service = CompanyDataService(db)
        info = organization_data_service.get_company_info_summary(company_id)

        return {
            "company_id": company_id,
            "embedding_info": info,
            "status": "success"
        }

    except Exception as e:
        logger.error(f"Error getting company info: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/company/{company_id}/refresh-embedding")
async def refresh_company_embedding(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Force refresh of company embedding
    """
    company_id = _authorize_company(current_user, company_id, db)

    try:
        organization_data_service = CompanyDataService(db)
        organization_data_service.invalidate_embedding(company_id)

        # Generate new company data
        new_data = organization_data_service.get_company_data(company_id)

        return {
            "company_id": company_id,
            "status": "refreshed",
            "company_data_preview": {
                "company_name": new_data.get("company_info", {}).get("name", ""),
                "specialties_count": len(new_data.get("services_info", {}).get("specialties", [])),
                "professionals_count": len(new_data.get("services_info", {}).get("professionals", []))
            }
        }

    except Exception as e:
        logger.error(f"Error refreshing embedding: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/company/{company_id}/slots")
async def get_company_slots(
    company_id: int,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Get available slots for company
    """
    company_id = _authorize_company(current_user, company_id, db)

    try:
        slots_service = SlotsService(db)
        slots = slots_service.get_available_slots(company_id, limit)
        stats = slots_service.get_slots_stats(company_id)

        return {
            "company_id": company_id,
            "available_slots": slots,
            "stats": stats,
            "total_returned": len(slots)
        }

    except Exception as e:
        logger.error(f"Error getting company slots: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/company/{company_id}/slots/sample")
async def create_sample_slots(
    company_id: int,
    request: SlotsTestRequest,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Create sample slots for testing
    """
    company_id = _authorize_company(current_user, company_id, db)

    try:
        slots_service = SlotsService(db)
        created_count = slots_service.populate_sample_slots(company_id, request.days)

        return {
            "company_id": company_id,
            "created_slots": created_count,
            "days": request.days,
            "status": "success"
        }

    except Exception as e:
        logger.error(f"Error creating sample slots: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/test-scheduling")
async def test_scheduling(
    request: SchedulingTestRequest,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Test scheduling functionality directly
    """
    company_id = _authorize_company(current_user, request.company_id, db)

    try:
        agent = BusinessAgent(company_id=company_id, db=db)

        # Test scheduling
        import json
        scheduling_data = {
            "customer_name": request.customer_name,
            "customer_phone": request.phone,
            "slot_datetime": request.slot_datetime,
            "service_type": request.service_type
        }

        result = await agent.schedule_appointment(json.dumps(scheduling_data))

        return {
            "test_type": "direct_scheduling",
            "request": request.dict(),
            "result": result
        }

    except Exception as e:
        logger.error(f"Error in test scheduling: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/company/{company_id}/conversations/{phone}")
async def get_conversation_history(
    company_id: int,
    phone: str,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Get conversation history for a phone number
    """
    company_id = _authorize_company(current_user, company_id, db)

    try:
        from backend.agents_sdk.manager import BusinessCompanyManager

        manager = BusinessCompanyManager(company_id=company_id, db=db)
        history = manager.get_conversation_history(phone, limit)

        return {
            "company_id": company_id,
            "phone": phone,
            "conversation_history": history,
            "total_messages": len(history)
        }

    except Exception as e:
        logger.error(f"Error getting conversation history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/company/{company_id}/stats")
async def get_company_stats(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Get comprehensive stats for company
    """
    company_id = _authorize_company(current_user, company_id, db)

    try:
        # Get company data info
        organization_data_service = CompanyDataService(db)
        company_data_info = organization_data_service.get_company_info_summary(company_id)

        # Get slots stats
        slots_service = SlotsService(db)
        slots_stats = slots_service.get_slots_stats(company_id)

        # Get conversation stats
        from sqlalchemy import text
        conv_result = db.execute(text("""
            SELECT
                COUNT(*) as total_conversations,
                COUNT(DISTINCT phone) as unique_phones,
                COUNT(DISTINCT conversation_group) as conversation_groups,
                AVG(execution_time_ms) as avg_response_time,
                COUNT(CASE WHEN status = 'success' THEN 1 END) as successful_interactions,
                COUNT(CASE WHEN status = 'error' THEN 1 END) as failed_interactions
            FROM agent_executions
            WHERE company_id = :company_id
        """), {"company_id": company_id}).fetchone()

        conversation_stats = {
            "total_conversations": conv_result.total_conversations if conv_result else 0,
            "unique_phones": conv_result.unique_phones if conv_result else 0,
            "conversation_groups": conv_result.conversation_groups if conv_result else 0,
            "avg_response_time_ms": float(conv_result.avg_response_time or 0) if conv_result else 0,
            "successful_interactions": conv_result.successful_interactions if conv_result else 0,
            "failed_interactions": conv_result.failed_interactions if conv_result else 0,
            "success_rate": (conv_result.successful_interactions / conv_result.total_conversations * 100) if conv_result and conv_result.total_conversations > 0 else 0
        }

        return {
            "company_id": company_id,
            "company_data": company_data_info,
            "slots": slots_stats,
            "conversations": conversation_stats,
            "status": "success"
        }

    except Exception as e:
        logger.error(f"Error getting company stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/config/company/{company_id}/status")
async def get_company_config_status(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Return whether the workspace has a persisted agent configuration."""
    company_id = _authorize_company(current_user, company_id, db)
    enabled = is_company_enabled(company_id, db)
    return {
        "company_id": company_id,
        "enabled": enabled,
        "source": "agent_configurations",
    }
