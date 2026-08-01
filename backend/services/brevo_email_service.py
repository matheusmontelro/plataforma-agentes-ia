"""Brevo transactional email integration."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional

import requests

from backend.runtime_settings import APP_NAME, PUBLIC_APP_URL


logger = logging.getLogger(__name__)

BREVO_API_BASE_URL = "https://api.brevo.com/v3"


@dataclass(frozen=True)
class BrevoEmailResult:
    sent: bool
    skipped: bool = False
    reason: Optional[str] = None
    message_id: Optional[str] = None


@dataclass(frozen=True)
class BrevoConfig:
    api_key: str
    sender_email: str
    sender_name: str
    api_base_url: str
    timeout_seconds: int
    public_app_origin: str
    contact_list_id: Optional[int]


def _clean_env(value: Optional[str]) -> str:
    return (value or "").strip().strip("\"'")


def _clean_url(value: str) -> str:
    return _clean_env(value).rstrip("/")


def _optional_int_env(name: str) -> Optional[int]:
    value = _clean_env(os.getenv(name))
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        logger.warning("%s ignorada porque não é um número inteiro", name)
        return None


def _template_id_env(name: str) -> Optional[int]:
    return _optional_int_env(name)


def get_public_app_origin() -> str:
    return _clean_url(
        os.getenv("BREVO_PUBLIC_APP_URL")
        or os.getenv("PUBLIC_APP_URL")
        or os.getenv("PUBLIC_BASE_URL")
        or PUBLIC_APP_URL
    )


def get_brevo_config() -> Optional[BrevoConfig]:
    api_key = _clean_env(os.getenv("BREVO_API_KEY"))
    sender_email = _clean_env(os.getenv("BREVO_SENDER_EMAIL"))
    if not api_key or not sender_email:
        return None

    try:
        timeout_seconds = int(_clean_env(os.getenv("BREVO_API_TIMEOUT_SECONDS")) or "12")
    except ValueError:
        logger.warning("BREVO_API_TIMEOUT_SECONDS inválida; usando timeout padrão")
        timeout_seconds = 12

    return BrevoConfig(
        api_key=api_key,
        sender_email=sender_email,
        sender_name=_clean_env(os.getenv("BREVO_SENDER_NAME")) or APP_NAME,
        api_base_url=_clean_url(os.getenv("BREVO_API_BASE_URL") or BREVO_API_BASE_URL),
        timeout_seconds=timeout_seconds,
        public_app_origin=get_public_app_origin(),
        contact_list_id=_optional_int_env("BREVO_CONTACT_LIST_ID"),
    )


def _safe_name(value: Any, fallback_email: str) -> str:
    text = str(value or "").strip()
    if text and "@" not in text:
        return text[:120]
    local_part = fallback_email.split("@", 1)[0].replace(".", " ").replace("_", " ").strip()
    return local_part.title()[:120] or "Cliente"


def _contact_attributes(name: str, company_name: Optional[str] = None) -> dict[str, Any]:
    attributes: dict[str, Any] = {"NOME": name}
    if company_name:
        attributes["EMPRESA"] = company_name[:120]
    return attributes


def upsert_brevo_contact(
    *,
    email: str,
    name: Optional[str] = None,
    company_name: Optional[str] = None,
) -> BrevoEmailResult:
    config = get_brevo_config()
    if not config:
        return BrevoEmailResult(sent=False, skipped=True, reason="brevo_not_configured")

    payload: dict[str, Any] = {
        "email": email,
        "attributes": _contact_attributes(name or _safe_name(None, email), company_name),
        "updateEnabled": True,
    }
    if config.contact_list_id:
        payload["listIds"] = [config.contact_list_id]

    try:
        response = requests.post(
            f"{config.api_base_url}/contacts",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "api-key": config.api_key,
            },
            json=payload,
            timeout=config.timeout_seconds,
        )
        if response.status_code in {200, 201, 204}:
            return BrevoEmailResult(sent=True)

        logger.warning("Brevo não confirmou contato email=%s status=%s", email, response.status_code)
        return BrevoEmailResult(sent=False, reason="brevo_contact_rejected")
    except requests.RequestException as exc:
        logger.warning("Falha ao sincronizar contato Brevo email=%s erro=%s", email, exc.__class__.__name__)
        return BrevoEmailResult(sent=False, reason="brevo_contact_request_failed")


def send_brevo_template_email(
    *,
    to_email: str,
    to_name: Optional[str],
    template_id: Optional[int],
    params: Mapping[str, Any],
    tags: Optional[list[str]] = None,
) -> BrevoEmailResult:
    config = get_brevo_config()
    if not config:
        logger.info("Email Brevo ignorado para %s: integração não configurada", to_email)
        return BrevoEmailResult(sent=False, skipped=True, reason="brevo_not_configured")

    if not template_id:
        logger.info("Email Brevo ignorado para %s: template não configurado", to_email)
        return BrevoEmailResult(sent=False, skipped=True, reason="brevo_template_not_configured")

    payload: dict[str, Any] = {
        "sender": {"email": config.sender_email, "name": config.sender_name},
        "to": [{"email": to_email, "name": to_name or _safe_name(None, to_email)}],
        "templateId": template_id,
        "params": dict(params),
    }
    if tags:
        payload["tags"] = tags

    try:
        response = requests.post(
            f"{config.api_base_url}/smtp/email",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "api-key": config.api_key,
            },
            json=payload,
            timeout=config.timeout_seconds,
        )
        if response.status_code in {200, 201, 202}:
            message_id = None
            try:
                message_id = response.json().get("messageId")
            except ValueError:
                message_id = None
            return BrevoEmailResult(sent=True, message_id=message_id)

        logger.warning("Brevo rejeitou email transacional para %s status=%s", to_email, response.status_code)
        return BrevoEmailResult(sent=False, reason="brevo_email_rejected")
    except requests.RequestException as exc:
        logger.warning("Falha ao enviar email Brevo para %s erro=%s", to_email, exc.__class__.__name__)
        return BrevoEmailResult(sent=False, reason="brevo_email_request_failed")


def send_master_welcome_email(client: Any, *, company_name: Optional[str] = None) -> BrevoEmailResult:
    email = str(getattr(client, "email", "") or "").strip()
    if not email:
        return BrevoEmailResult(sent=False, skipped=True, reason="missing_email")

    billing_profile = getattr(client, "billing_profile", None) or {}
    name = _safe_name(billing_profile.get("full_name"), email)
    upsert_brevo_contact(email=email, name=name, company_name=company_name)

    return send_brevo_template_email(
        to_email=email,
        to_name=name,
        template_id=_template_id_env("BREVO_WELCOME_TEMPLATE_ID"),
        params={
            "email": email,
            "name": name,
            "company_name": company_name or APP_NAME,
            "login_url": f"{get_public_app_origin()}/login",
        },
        tags=["welcome", "master"],
    )


def send_internal_user_welcome_email(
    user: Any,
    *,
    temporary_password: str,
    company_name: Optional[str] = None,
    master_email: Optional[str] = None,
) -> BrevoEmailResult:
    email = str(getattr(user, "email", "") or "").strip()
    if not email:
        return BrevoEmailResult(sent=False, skipped=True, reason="missing_email")

    name = _safe_name(getattr(user, "name", None), email)
    upsert_brevo_contact(email=email, name=name, company_name=company_name)

    return send_brevo_template_email(
        to_email=email,
        to_name=name,
        template_id=_template_id_env("BREVO_USER_PASSWORD_TEMPLATE_ID"),
        params={
            "email": email,
            "name": name,
            "password": temporary_password,
            "company_name": company_name or APP_NAME,
            "master_email": master_email or "",
            "login_url": f"{get_public_app_origin()}/login",
        },
        tags=["welcome", "internal-user"],
    )


def send_internal_user_password_changed_email(
    user: Any,
    *,
    new_password: str,
    company_name: Optional[str] = None,
) -> BrevoEmailResult:
    email = str(getattr(user, "email", "") or "").strip()
    if not email:
        return BrevoEmailResult(sent=False, skipped=True, reason="missing_email")

    name = _safe_name(getattr(user, "name", None), email)
    template_id = _template_id_env("BREVO_PASSWORD_CHANGED_TEMPLATE_ID") or _template_id_env(
        "BREVO_USER_PASSWORD_TEMPLATE_ID"
    )

    return send_brevo_template_email(
        to_email=email,
        to_name=name,
        template_id=template_id,
        params={
            "email": email,
            "name": name,
            "password": new_password,
            "company_name": company_name or APP_NAME,
            "login_url": f"{get_public_app_origin()}/login",
        },
        tags=["password", "internal-user"],
    )


def send_password_reset_email(
    *,
    to_email: str,
    to_name: Optional[str],
    reset_url: str,
    expires_minutes: int,
) -> BrevoEmailResult:
    name = _safe_name(to_name, to_email)
    return send_brevo_template_email(
        to_email=to_email,
        to_name=name,
        template_id=_template_id_env("BREVO_PASSWORD_RESET_TEMPLATE_ID"),
        params={
            "email": to_email,
            "name": name,
            "reset_url": reset_url,
            "expires_minutes": expires_minutes,
            "login_url": f"{get_public_app_origin()}/login",
        },
        tags=["password-reset"],
    )


def send_managed_workspace_welcome_email(
    client: Any,
    *,
    workspace_name: str,
    owner_company_name: Optional[str] = None,
    owner_email: Optional[str] = None,
    trial_days: int = 0,
    trial_ends_at: Optional[Any] = None,
    trial_credits: float = 0.0,
    password_setup_url: Optional[str] = None,
    password_setup_expires_minutes: Optional[int] = None,
) -> BrevoEmailResult:
    email = str(getattr(client, "email", "") or "").strip()
    if not email:
        return BrevoEmailResult(sent=False, skipped=True, reason="missing_email")

    billing_profile = getattr(client, "billing_profile", None) or {}
    name = _safe_name(billing_profile.get("full_name"), email)
    upsert_brevo_contact(email=email, name=name, company_name=workspace_name)

    trial_ends_at_iso = trial_ends_at.isoformat() if hasattr(trial_ends_at, "isoformat") else trial_ends_at
    return send_brevo_template_email(
        to_email=email,
        to_name=name,
        template_id=_template_id_env("BREVO_MANAGED_WORKSPACE_WELCOME_TEMPLATE_ID"),
        params={
            "email": email,
            "name": name,
            "workspace_name": workspace_name,
            "company_name": workspace_name,
            "owner_company_name": owner_company_name or APP_NAME,
            "owner_email": owner_email or "",
            "trial_days": trial_days,
            "trial_ends_at": trial_ends_at_iso or "",
            "trial_credits": trial_credits,
            "password_setup_url": password_setup_url or "",
            "password_setup_expires_minutes": password_setup_expires_minutes or "",
            "login_url": f"{get_public_app_origin()}/login",
        },
        tags=["welcome", "managed-workspace", "trial" if trial_days else "active"],
    )


def send_ai_credit_purchase_email(
    *,
    to_email: str,
    to_name: Optional[str],
    company_name: Optional[str],
    package_name: str,
    credits: str,
    price: str,
    balance_after: str,
    order_id: str,
) -> BrevoEmailResult:
    name = _safe_name(to_name, to_email)
    return send_brevo_template_email(
        to_email=to_email,
        to_name=name,
        template_id=_template_id_env("BREVO_AI_CREDIT_PURCHASE_TEMPLATE_ID"),
        params={
            "email": to_email,
            "name": name,
            "company_name": company_name or APP_NAME,
            "package_name": package_name,
            "credits": credits,
            "price": price,
            "balance_after": balance_after,
            "order_id": order_id,
            "credits_url": f"{get_public_app_origin()}/company/ai-credits",
        },
        tags=["ai-credits", "purchase"],
    )


def send_communication_template_email(
    *,
    to_email: str,
    to_name: Optional[str],
    template_id: int,
    params: Mapping[str, Any],
    tags: Optional[list[str]] = None,
) -> BrevoEmailResult:
    return send_brevo_template_email(
        to_email=to_email,
        to_name=to_name,
        template_id=template_id,
        params=params,
        tags=tags,
    )
