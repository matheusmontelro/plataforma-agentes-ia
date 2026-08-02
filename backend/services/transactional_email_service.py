"""Optional provider-neutral transactional email delivery over SMTP."""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from html import escape
from typing import Optional

from backend.runtime_settings import APP_NAME, PUBLIC_APP_URL


logger = logging.getLogger(__name__)
SMTP_TIMEOUT_SECONDS = 12


@dataclass(frozen=True)
class TransactionalEmailResult:
    sent: bool
    skipped: bool = False
    reason: Optional[str] = None
    message_id: Optional[str] = None


@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    username: Optional[str]
    password: Optional[str]
    from_email: str
    from_name: str
    starttls: bool


def _clean_env(value: Optional[str]) -> str:
    return (value or "").strip().strip("\"'")


def _clean_header(value: Optional[str]) -> str:
    return " ".join(_clean_env(value).splitlines()).strip()


def _bool_env(name: str, default: bool) -> bool:
    value = _clean_env(os.getenv(name)).casefold()
    if not value:
        return default
    if value in {"1", "true", "yes", "on", "sim"}:
        return True
    if value in {"0", "false", "no", "off", "nao", "não"}:
        return False
    logger.warning("%s inválida; usando o valor seguro padrão", name)
    return default


def get_public_app_origin() -> str:
    return _clean_env(os.getenv("PUBLIC_APP_URL") or PUBLIC_APP_URL).rstrip("/")


def get_smtp_config() -> Optional[SMTPConfig]:
    host = _clean_env(os.getenv("SMTP_HOST"))
    from_email = _clean_header(os.getenv("SMTP_FROM_EMAIL"))
    if not host or not from_email:
        return None

    try:
        port = int(_clean_env(os.getenv("SMTP_PORT")) or "587")
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        logger.warning("SMTP_PORT inválida; usando a porta 587")
        port = 587

    username = _clean_env(os.getenv("SMTP_USERNAME")) or None
    password = _clean_env(os.getenv("SMTP_PASSWORD")) or None
    if bool(username) != bool(password):
        logger.warning(
            "SMTP ignorado: SMTP_USERNAME e SMTP_PASSWORD devem ser configurados juntos"
        )
        return None

    starttls = _bool_env("SMTP_STARTTLS", True)
    if username and not starttls:
        logger.warning(
            "SMTP ignorado: autenticação exige SMTP_STARTTLS=true para proteger as credenciais"
        )
        return None

    return SMTPConfig(
        host=host,
        port=port,
        username=username,
        password=password,
        from_email=from_email,
        from_name=_clean_header(os.getenv("SMTP_FROM_NAME")) or APP_NAME,
        starttls=starttls,
    )


def _send_email(
    *,
    to_email: str,
    to_name: Optional[str],
    subject: str,
    text_body: str,
    html_body: str,
) -> TransactionalEmailResult:
    config = get_smtp_config()
    if not config:
        logger.info("Email transacional ignorado: SMTP não configurado")
        return TransactionalEmailResult(
            sent=False,
            skipped=True,
            reason="smtp_not_configured",
        )

    recipient = _clean_header(to_email)
    if not recipient:
        return TransactionalEmailResult(
            sent=False,
            skipped=True,
            reason="missing_recipient",
        )

    message = EmailMessage()
    message_id = make_msgid()
    message["Message-ID"] = message_id
    message["Subject"] = _clean_header(subject)
    message["From"] = formataddr((config.from_name, config.from_email))
    message["To"] = formataddr((_clean_header(to_name), recipient)) if to_name else recipient
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(
            config.host,
            config.port,
            timeout=SMTP_TIMEOUT_SECONDS,
        ) as smtp:
            smtp.ehlo()
            if config.starttls:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if config.username and config.password:
                smtp.login(config.username, config.password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        logger.warning(
            "Falha ao enviar email transacional erro=%s",
            exc.__class__.__name__,
        )
        return TransactionalEmailResult(
            sent=False,
            reason="smtp_delivery_failed",
        )

    return TransactionalEmailResult(sent=True, message_id=message_id)


def _password_action_template(
    *,
    recipient_name: Optional[str],
    heading: str,
    introduction: str,
    action_label: str,
    action_url: str,
    expires_minutes: int,
) -> tuple[str, str]:
    safe_name = _clean_env(recipient_name) or "Olá"
    expiration = f"Este link expira em {int(expires_minutes)} minutos."
    text_body = (
        f"{safe_name},\n\n"
        f"{introduction}\n\n"
        f"{action_label}: {action_url}\n\n"
        f"{expiration}\n\n"
        "Se você não solicitou esta ação, ignore esta mensagem."
    )
    html_body = f"""
<!doctype html>
<html lang="pt-BR">
  <body style="font-family:Arial,sans-serif;color:#172033;line-height:1.5">
    <h1 style="font-size:22px">{escape(heading)}</h1>
    <p>{escape(safe_name)},</p>
    <p>{escape(introduction)}</p>
    <p>
      <a href="{escape(action_url, quote=True)}"
         style="display:inline-block;padding:12px 18px;border-radius:8px;background:#2563eb;color:#fff;text-decoration:none">
        {escape(action_label)}
      </a>
    </p>
    <p>{escape(expiration)}</p>
    <p style="color:#64748b">Se você não solicitou esta ação, ignore esta mensagem.</p>
  </body>
</html>
""".strip()
    return text_body, html_body


def send_password_reset_email(
    *,
    to_email: str,
    to_name: Optional[str],
    reset_url: str,
    expires_minutes: int,
) -> TransactionalEmailResult:
    text_body, html_body = _password_action_template(
        recipient_name=to_name,
        heading="Redefinição de senha",
        introduction=f"Recebemos uma solicitação para redefinir sua senha na {APP_NAME}.",
        action_label="Redefinir senha",
        action_url=reset_url,
        expires_minutes=expires_minutes,
    )
    return _send_email(
        to_email=to_email,
        to_name=to_name,
        subject=f"Redefina sua senha na {APP_NAME}",
        text_body=text_body,
        html_body=html_body,
    )


def send_password_setup_email(
    *,
    to_email: str,
    to_name: Optional[str],
    workspace_name: str,
    setup_url: str,
    expires_minutes: int,
) -> TransactionalEmailResult:
    text_body, html_body = _password_action_template(
        recipient_name=to_name,
        heading="Defina sua senha",
        introduction=(
            f"Uma conta foi criada para você no workspace {workspace_name}. "
            "Use o link abaixo para definir sua senha."
        ),
        action_label="Definir senha",
        action_url=setup_url,
        expires_minutes=expires_minutes,
    )
    return _send_email(
        to_email=to_email,
        to_name=to_name,
        subject=f"Defina sua senha em {workspace_name}",
        text_body=text_body,
        html_body=html_body,
    )
