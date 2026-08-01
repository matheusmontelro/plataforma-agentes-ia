# backend/routes/call_routes.py

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.orm import Session
from backend.db import get_db
from backend.integrations.whatsapp_provider import send_call
from backend.auth import get_current_user
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

class CallResponse(BaseModel):
    success: bool
    message: str
    call_id: str = None

@router.post("/call/send", response_model=CallResponse)
async def send_call_endpoint(
    phone: str = Query(..., description="Número de telefone para fazer a ligação"),
    callDuration: int = Query(10, description="Duração da ligação em segundos"),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Endpoint para fazer ligação via WhatsApp.
    """
    try:
        logger.info(f"Iniciando ligação para {phone} - duração: {callDuration}s - usuário: {current_user.id}")

        result = send_call(
            company_id=current_user.company_id,
            phone=phone,
            call_duration=callDuration,
            db=db,
        )

        logger.info(f"Ligação para {phone} iniciada com sucesso: {result}")

        return CallResponse(
            success=True,
            message=f"Ligação iniciada para {phone}",
            call_id=result.get("messageId", "unknown")
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao fazer ligação para {phone}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao fazer ligação: {str(e)}"
        )

@router.get("/call/status")
async def get_call_status(
    current_user = Depends(get_current_user)
):
    """
    Endpoint para verificar status das ligações (futuro)
    """
    return {
        "message": "Endpoint de status de ligações - implementação futura",
        "user": current_user.id
    }
