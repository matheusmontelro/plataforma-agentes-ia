"""OpenAI BYOK credential storage and per-company runtime helpers."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from agents import RunConfig, trace
from agents.models.openai_provider import OpenAIProvider
from cryptography.fernet import Fernet, InvalidToken
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.models import AIProviderCredential, AgentWorkforce
from backend.runtime_settings import APP_NAME


OPENAI_PROVIDER = "openai"
AI_PROVIDER_TOKEN_ENCRYPTION_KEY_ENV = "AI_PROVIDER_TOKEN_ENCRYPTION_KEY"
DEFAULT_OPENAI_VALIDATION_TIMEOUT_SECONDS = 15.0
REQUIRED_OPENAI_RUNTIME_MODEL = "gpt-4o-mini"
REQUIRED_OPENAI_TRANSCRIPTION_MODEL = "gpt-4o-transcribe"
AI_PROVIDER_CONFIGURATION_LOCK_PREFIX = "agentive:ai-provider:configuration"

OPENAI_MODEL_ALLOWLIST = (
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "gpt-5.5-pro",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.4-pro",
    "gpt-4o-mini",
)


class AIProviderCredentialError(RuntimeError):
    """Base error whose message is safe to expose without credential material."""


class AIProviderConfigurationError(AIProviderCredentialError):
    """Server-side encryption configuration is missing or invalid."""


class AIProviderNotConfiguredError(AIProviderCredentialError):
    """The active company has no usable OpenAI credential."""


class AIProviderValidationError(AIProviderCredentialError):
    """OpenAI rejected the credential or validation could not complete."""

    def __init__(
        self,
        message: str,
        *,
        credential_status: str,
        http_status_code: int,
    ) -> None:
        super().__init__(message)
        self.credential_status = credential_status
        self.http_status_code = http_status_code


class AIProviderCompatibilityError(AIProviderCredentialError):
    """A valid credential cannot run models already saved by the company."""


def safe_ai_provider_runtime_error(
    exc: Exception,
    *,
    fallback: str = "Não foi possível executar a operação de IA",
) -> str:
    """Return a user-safe runtime message without provider exception payloads."""

    if isinstance(exc, AIProviderCredentialError):
        return str(exc)
    if isinstance(
        exc,
        (
            AuthenticationError,
            PermissionDeniedError,
            RateLimitError,
            APIConnectionError,
            APITimeoutError,
            APIStatusError,
        ),
    ):
        return str(_validation_error_from_exception(exc))
    return fallback


def openai_run_trace(run_config: Any, **trace_kwargs: Any) -> Any:
    """Create an explicit trace that honors the per-run tracing contract."""

    return trace(
        **trace_kwargs,
        disabled=bool(getattr(run_config, "tracing_disabled", False)),
    )


def _clean_env_value(value: Optional[str]) -> str:
    return (value or "").strip().strip("\"'")


def _validated_fernet_key(raw_key: str, env_name: str) -> str:
    try:
        Fernet(raw_key.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise AIProviderConfigurationError(
            f"{env_name} inválida; use uma chave Fernet"
        ) from exc
    return raw_key


def _token_encryption_key() -> str:
    dedicated_key = _clean_env_value(
        os.getenv(AI_PROVIDER_TOKEN_ENCRYPTION_KEY_ENV)
    )
    if dedicated_key:
        return _validated_fernet_key(
            dedicated_key,
            AI_PROVIDER_TOKEN_ENCRYPTION_KEY_ENV,
        )

    raise AIProviderConfigurationError(
        f"{AI_PROVIDER_TOKEN_ENCRYPTION_KEY_ENV} não configurada"
    )


def _fernet() -> Fernet:
    return Fernet(_token_encryption_key().encode("utf-8"))


def encrypt_openai_api_key(api_key: str) -> str:
    secret = (api_key or "").strip()
    if not secret:
        raise AIProviderConfigurationError("Chave OpenAI ausente")
    return _fernet().encrypt(secret.encode("utf-8")).decode("utf-8")


def decrypt_openai_api_key(encrypted_api_key: str) -> str:
    ciphertext = (encrypted_api_key or "").strip()
    if not ciphertext:
        raise AIProviderConfigurationError(
            "Credencial OpenAI criptografada ausente"
        )
    try:
        plaintext = _fernet().decrypt(ciphertext.encode("utf-8"))
        secret = plaintext.decode("utf-8").strip()
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise AIProviderConfigurationError(
            "Credencial OpenAI não pôde ser descriptografada"
        ) from exc
    if not secret:
        raise AIProviderConfigurationError(
            "Credencial OpenAI descriptografada está vazia"
        )
    return secret


def get_company_ai_provider_credential(
    db: Session,
    company_id: int,
) -> Optional[AIProviderCredential]:
    if not company_id:
        return None
    return (
        db.query(AIProviderCredential)
        .filter(
            AIProviderCredential.company_id == int(company_id),
            AIProviderCredential.provider == OPENAI_PROVIDER,
        )
        .one_or_none()
    )


def lock_company_ai_provider_configuration(
    db: Session,
    company_id: int,
) -> None:
    """Serialize credential rotations and their remote knowledge migration."""

    get_bind = getattr(db, "get_bind", None)
    if not callable(get_bind):
        return
    bind = get_bind()
    if bind.dialect.name != "postgresql":
        return
    db.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtextextended(:lock_key, 0))"
        ),
        {
            "lock_key": (
                f"{AI_PROVIDER_CONFIGURATION_LOCK_PREFIX}:{int(company_id)}"
            )
        },
    )


def _model_id(model: Any) -> str:
    if isinstance(model, dict):
        return str(model.get("id") or "").strip()
    return str(getattr(model, "id", "") or "").strip()


def _filter_supported_models(models: Iterable[Any]) -> list[str]:
    available_ids = {_model_id(model) for model in models}
    return [
        model_id
        for model_id in OPENAI_MODEL_ALLOWLIST
        if model_id in available_ids
    ]


def _validation_error_from_exception(exc: Exception) -> AIProviderValidationError:
    if isinstance(exc, AuthenticationError):
        return AIProviderValidationError(
            "Chave OpenAI inválida ou sem autorização",
            credential_status="invalid",
            http_status_code=400,
        )
    if isinstance(exc, PermissionDeniedError):
        return AIProviderValidationError(
            "A chave OpenAI não possui permissão para listar modelos",
            credential_status="invalid",
            http_status_code=400,
        )
    if isinstance(exc, RateLimitError):
        return AIProviderValidationError(
            "A OpenAI recusou temporariamente a validação por limite de uso",
            credential_status="error",
            http_status_code=503,
        )
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return AIProviderValidationError(
            "Não foi possível conectar à OpenAI para validar a chave",
            credential_status="error",
            http_status_code=503,
        )
    if isinstance(exc, APIStatusError):
        return AIProviderValidationError(
            "A OpenAI recusou a validação da chave",
            credential_status="invalid",
            http_status_code=400,
        )
    return AIProviderValidationError(
        "Não foi possível validar a chave OpenAI",
        credential_status="error",
        http_status_code=503,
    )


def validate_openai_api_key(
    api_key: str,
    *,
    timeout_seconds: float = DEFAULT_OPENAI_VALIDATION_TIMEOUT_SECONDS,
) -> list[str]:
    secret = (api_key or "").strip()
    if not secret:
        raise AIProviderValidationError(
            "Informe uma chave OpenAI",
            credential_status="invalid",
            http_status_code=400,
        )

    client = None
    try:
        client = OpenAI(
            api_key=secret,
            timeout=timeout_seconds,
            max_retries=0,
        )
        models_page = client.models.list()
        models = getattr(models_page, "data", models_page)
        model_items = list(models or [])
        available_model_ids = {
            _model_id(model)
            for model in model_items
            if _model_id(model)
        }
        supported_models = _filter_supported_models(model_items)
        if (
            REQUIRED_OPENAI_RUNTIME_MODEL in supported_models
            and REQUIRED_OPENAI_TRANSCRIPTION_MODEL in available_model_ids
        ):
            client.responses.create(
                model=REQUIRED_OPENAI_RUNTIME_MODEL,
                input="Responda apenas OK.",
                max_output_tokens=1,
                store=False,
            )
    except Exception as exc:
        raise _validation_error_from_exception(exc) from None
    finally:
        close = getattr(client, "close", None) if client is not None else None
        if callable(close):
            try:
                close()
            except Exception:
                pass

    if not supported_models:
        raise AIProviderValidationError(
            f"A chave OpenAI não possui acesso a modelos compatíveis com a {APP_NAME}",
            credential_status="invalid",
            http_status_code=400,
        )
    if REQUIRED_OPENAI_RUNTIME_MODEL not in supported_models:
        raise AIProviderValidationError(
            f"A chave OpenAI não possui acesso ao modelo base usado pela {APP_NAME}",
            credential_status="invalid",
            http_status_code=400,
        )
    if REQUIRED_OPENAI_TRANSCRIPTION_MODEL not in available_model_ids:
        raise AIProviderValidationError(
            f"A chave OpenAI não possui acesso ao modelo de transcrição usado pela {APP_NAME}",
            credential_status="invalid",
            http_status_code=400,
        )
    return supported_models


def configure_company_openai_api_key(
    db: Session,
    company_id: int,
    api_key: str,
) -> AIProviderCredential:
    supported_models = validate_openai_api_key(api_key)
    encrypted_api_key = encrypt_openai_api_key(api_key)
    credential = get_company_ai_provider_credential(db, company_id)
    if credential is None:
        credential = AIProviderCredential(
            company_id=int(company_id),
            provider=OPENAI_PROVIDER,
            api_key_encrypted=encrypted_api_key,
        )
        db.add(credential)

    credential.api_key_encrypted = encrypted_api_key
    credential.status = "valid"
    credential.available_models = supported_models
    credential.last_validated_at = datetime.now(timezone.utc)
    credential.last_error = None
    return credential


def ensure_company_workforce_models_are_supported(
    db: Session,
    company_id: int,
    available_models: Iterable[str],
) -> None:
    """Prevent a key replacement from silently breaking saved agents."""

    supported = {
        str(model_id).strip()
        for model_id in available_models
        if str(model_id).strip()
    }
    unsupported: set[str] = set()
    workforces = (
        db.query(AgentWorkforce)
        .filter(AgentWorkforce.company_id == int(company_id))
        .all()
    )
    for workforce in workforces:
        agent_configs = workforce.agent_configs
        if not isinstance(agent_configs, dict):
            continue
        for raw_config in agent_configs.values():
            if not isinstance(raw_config, dict):
                continue
            model_config = raw_config.get("model")
            if not isinstance(model_config, dict):
                continue
            model_id = str(model_config.get("model") or "").strip()
            if model_id and model_id not in supported:
                unsupported.add(model_id)

    if unsupported:
        raise AIProviderCompatibilityError(
            "A chave é válida, mas não oferece os modelos já usados pela empresa: "
            + ", ".join(sorted(unsupported))
        )


def validate_saved_company_openai_api_key(
    db: Session,
    company_id: int,
) -> AIProviderCredential:
    credential = get_company_ai_provider_credential(db, company_id)
    if credential is None:
        raise AIProviderNotConfiguredError(
            "Chave OpenAI não configurada para a empresa ativa"
        )
    api_key = decrypt_openai_api_key(credential.api_key_encrypted)
    supported_models = validate_openai_api_key(api_key)
    credential.status = "valid"
    credential.available_models = supported_models
    credential.last_validated_at = datetime.now(timezone.utc)
    credential.last_error = None
    return credential


def mark_company_openai_validation_error(
    credential: AIProviderCredential,
    exc: AIProviderValidationError,
) -> None:
    credential.status = exc.credential_status
    credential.available_models = []
    credential.last_validated_at = datetime.now(timezone.utc)
    credential.last_error = str(exc)


def get_company_openai_api_key(db: Session, company_id: int) -> str:
    """Resolve one validated company credential without global process state."""

    credential = get_company_ai_provider_credential(db, company_id)
    if credential is None:
        raise AIProviderNotConfiguredError(
            "Chave OpenAI não configurada para a empresa ativa"
        )
    if credential.status != "valid":
        raise AIProviderNotConfiguredError(
            "Chave OpenAI da empresa ativa não está validada"
        )
    return decrypt_openai_api_key(credential.api_key_encrypted)


def build_company_openai_run_config(
    db: Session,
    company_id: int,
    *,
    tracing_disabled: bool = True,
    model_override: Optional[str] = REQUIRED_OPENAI_RUNTIME_MODEL,
) -> RunConfig:
    """Build an Agents SDK config whose provider exists only for this run."""

    api_key = get_company_openai_api_key(db, company_id)
    return RunConfig(
        model=model_override,
        model_provider=OpenAIProvider(api_key=api_key),
        tracing_disabled=tracing_disabled,
        trace_include_sensitive_data=False,
    )
