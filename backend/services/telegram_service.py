"""
Telegram Service

Utility helpers for sending Telegram Bot API messages.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import requests
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from backend.models import TelegramIntegration

logger = logging.getLogger(__name__)


DEFAULT_TIMEOUT_SECONDS = 15


class TelegramConfigurationError(RuntimeError):
    """Raised when the Telegram integration is missing required configuration."""


class TelegramAPIError(RuntimeError):
    """Raised when Telegram rejects or fails a request."""


def _clean_env_value(value: Optional[str]) -> str:
    return (value or "").strip().strip("\"'")


def _token_encryption_key() -> str:
    raw_key = (
        _clean_env_value(os.getenv("TELEGRAM_TOKEN_ENCRYPTION_KEY"))
        or _clean_env_value(os.getenv("INTEGRATION_TOKEN_ENCRYPTION_KEY"))
    )
    if not raw_key:
        raise TelegramConfigurationError(
            "Chave de criptografia do Telegram nao configurada"
        )
    return raw_key


def _fernet() -> Fernet:
    try:
        return Fernet(_token_encryption_key().encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise TelegramConfigurationError(
            "Chave de criptografia do Telegram invalida; use uma chave Fernet"
        ) from exc


def encrypt_bot_token(bot_token: str) -> str:
    token = (bot_token or "").strip()
    if not token:
        raise TelegramConfigurationError("Token do bot Telegram ausente")
    return _fernet().encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_bot_token(encrypted_token: str) -> str:
    token = (encrypted_token or "").strip()
    if not token:
        raise TelegramConfigurationError("Token do bot Telegram criptografado ausente")
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise TelegramConfigurationError("Token do bot Telegram criptografado invalido") from exc


def ensure_token_encryption_configured() -> None:
    _fernet()


def validate_telegram_bot_token(
    bot_token: str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """
    Validate a Telegram Bot API token using getMe.

    Returns Telegram's `result` payload when the token is valid.
    """
    token = (bot_token or "").strip()
    if not token:
        raise TelegramConfigurationError("Token do bot Telegram ausente")

    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        resp = requests.get(url, timeout=timeout_seconds)
        data = resp.json() if resp.content else {}
    except Exception as exc:
        logger.warning("Telegram getMe failed (transport): %s", exc)
        raise TelegramAPIError(f"Falha ao validar token Telegram: {exc}") from exc

    if not resp.ok:
        description = data.get("description") if isinstance(data, dict) else None
        raise TelegramAPIError(f"Telegram HTTP {resp.status_code}: {description or 'token invalido'}")

    if not isinstance(data, dict) or data.get("ok") is False:
        raise TelegramAPIError(f"Telegram API error: {data.get('description') if isinstance(data, dict) else 'unknown error'}")

    result = data.get("result")
    if not isinstance(result, dict):
        raise TelegramAPIError("Telegram API returned invalid getMe response")

    return result


def get_company_telegram_integration(
    db: Session,
    company_id: int,
) -> Optional[TelegramIntegration]:
    if not company_id:
        return None
    return (
        db.query(TelegramIntegration)
        .filter(TelegramIntegration.company_id == int(company_id))
        .first()
    )


def send_telegram_text(
    *,
    bot_token: str,
    chat_id: str,
    message: str,
    parse_mode: Optional[str] = "HTML",
    disable_web_page_preview: bool = True,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """
    Send a text message using Telegram Bot API.

    Returns the `result` payload from Telegram when successful.
    Raises RuntimeError on API or transport failures.
    """
    if not bot_token:
        raise RuntimeError("Telegram bot token is required")
    if not chat_id:
        raise RuntimeError("Telegram chat_id is required")
    if not message:
        raise RuntimeError("Telegram message is required")

    payload: Dict[str, Any] = {
        "chat_id": str(chat_id),
        "text": str(message),
        "disable_web_page_preview": bool(disable_web_page_preview),
    }

    if parse_mode:
        payload["parse_mode"] = parse_mode

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    try:
        resp = requests.post(url, json=payload, timeout=timeout_seconds)
        data = resp.json() if resp.content else {}
    except Exception as e:
        logger.error("Telegram send failed (transport): %s", e)
        raise RuntimeError(f"Telegram transport error: {e}") from e

    if not resp.ok:
        description = data.get("description") if isinstance(data, dict) else None
        raise RuntimeError(f"Telegram HTTP {resp.status_code}: {description or resp.text}")

    if isinstance(data, dict) and data.get("ok") is False:
        raise RuntimeError(f"Telegram API error: {data.get('description') or 'unknown error'}")

    if not isinstance(data, dict):
        raise RuntimeError("Telegram API returned invalid response format")

    return data.get("result") or {}
