from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import ensure_user_can_access_company, get_current_user
from backend.db import get_db
from backend.models import TelegramIntegration
from backend.services.telegram_service import (
    TelegramAPIError,
    TelegramConfigurationError,
    decrypt_bot_token,
    encrypt_bot_token,
    get_company_telegram_integration,
    send_telegram_text,
    validate_telegram_bot_token,
)
from backend.runtime_settings import APP_NAME


router = APIRouter()


class TelegramIntegrationUpsert(BaseModel):
    bot_token: Optional[str] = None
    default_chat_id: Optional[str] = None
    default_chat_title: Optional[str] = None


class TelegramIntegrationResponse(BaseModel):
    configured: bool
    bot_name: Optional[str] = None
    bot_username: Optional[str] = None
    default_chat_id: Optional[str] = None
    default_chat_title: Optional[str] = None
    last_error: Optional[str] = None
    last_validated_at: Optional[datetime] = None
    status: str = "not_configured"


class TelegramTestMessageRequest(BaseModel):
    chat_id: Optional[str] = None
    message: str = f"Teste de integração Telegram - {APP_NAME}"


def require_telegram_company_access(
    company_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    ensure_user_can_access_company(current_user, company_id, db)
    return current_user


def _integration_response(integration: Optional[TelegramIntegration]) -> TelegramIntegrationResponse:
    if not integration:
        return TelegramIntegrationResponse(configured=False)

    return TelegramIntegrationResponse(
        configured=True,
        bot_name=integration.bot_name,
        bot_username=integration.bot_username,
        default_chat_id=integration.default_chat_id,
        default_chat_title=integration.default_chat_title,
        last_error=integration.last_error,
        last_validated_at=integration.last_validated_at,
        status=integration.status or "connected",
    )


@router.get("/{company_id}", response_model=TelegramIntegrationResponse)
def get_telegram_integration(
    company_id: int,
    db: Session = Depends(get_db),
    _current_user=Depends(require_telegram_company_access),
):
    integration = get_company_telegram_integration(db, company_id)
    return _integration_response(integration)


@router.put("/{company_id}", response_model=TelegramIntegrationResponse)
def upsert_telegram_integration(
    company_id: int,
    payload: TelegramIntegrationUpsert,
    db: Session = Depends(get_db),
    _current_user=Depends(require_telegram_company_access),
):
    integration = get_company_telegram_integration(db, company_id)
    raw_token = (payload.bot_token or "").strip()

    if not integration and not raw_token:
        raise HTTPException(status_code=400, detail="Informe o token do bot Telegram")

    bot_info = None
    encrypted_token = integration.bot_token_encrypted if integration else None

    if raw_token:
        try:
            bot_info = validate_telegram_bot_token(raw_token)
            encrypted_token = encrypt_bot_token(raw_token)
        except (TelegramConfigurationError, TelegramAPIError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not encrypted_token:
        raise HTTPException(status_code=400, detail="Token do bot Telegram ausente")

    if not integration:
        integration = TelegramIntegration(company_id=company_id, bot_token_encrypted=encrypted_token)
        db.add(integration)

    integration.bot_token_encrypted = encrypted_token
    integration.default_chat_id = (payload.default_chat_id or "").strip() or None
    integration.default_chat_title = (payload.default_chat_title or "").strip() or None
    integration.status = "connected"
    integration.last_error = None

    if bot_info:
        integration.bot_username = bot_info.get("username")
        integration.bot_name = bot_info.get("first_name") or bot_info.get("username")
        integration.last_validated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(integration)
    return _integration_response(integration)


@router.post("/{company_id}/test-message")
def send_telegram_test_message(
    company_id: int,
    payload: TelegramTestMessageRequest,
    db: Session = Depends(get_db),
    _current_user=Depends(require_telegram_company_access),
):
    integration = get_company_telegram_integration(db, company_id)
    if not integration:
        raise HTTPException(status_code=400, detail="Telegram nao configurado para esta empresa")

    chat_id = (payload.chat_id or integration.default_chat_id or "").strip()
    if not chat_id:
        raise HTTPException(status_code=400, detail="Informe um chat ID para testar o Telegram")

    try:
        bot_token = decrypt_bot_token(integration.bot_token_encrypted)
        result = send_telegram_text(
            bot_token=bot_token,
            chat_id=chat_id,
            message=payload.message,
            parse_mode=None,
        )
    except (TelegramConfigurationError, TelegramAPIError, RuntimeError) as exc:
        integration.status = "error"
        integration.last_error = str(exc)
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    integration.status = "connected"
    integration.last_error = None
    db.commit()

    return {
        "success": True,
        "chat_id": str(result.get("chat", {}).get("id", chat_id)),
        "message_id": result.get("message_id"),
    }


@router.delete("/{company_id}")
def delete_telegram_integration(
    company_id: int,
    db: Session = Depends(get_db),
    _current_user=Depends(require_telegram_company_access),
):
    integration = get_company_telegram_integration(db, company_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Telegram nao configurado para esta empresa")

    db.delete(integration)
    db.commit()
    return {"status": "success", "message": "Integração Telegram removida com sucesso."}
