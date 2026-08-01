"""Authenticated OpenAI BYOK configuration for the active company."""

from __future__ import annotations

from datetime import datetime
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import AIProviderCredential, Client, User
from backend.services import (
    ai_provider_knowledge_migration,
    ai_provider_service,
)


router = APIRouter(prefix="/ai-provider", tags=["AI Provider"])


class AIProviderUpsertRequest(BaseModel):
    api_key: SecretStr

    def validated_api_key(self) -> str:
        """Validate after SecretStr parsing so a 422 never echoes the raw key."""

        secret = self.api_key.get_secret_value().strip()
        if not 10 <= len(secret) <= 512:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A chave OpenAI deve ter entre 10 e 512 caracteres",
            )
        return secret


class AIProviderResponse(BaseModel):
    configured: bool
    status: str
    last_validated_at: datetime | None = None
    last_error: str | None = None
    models: list[str] = Field(default_factory=list)


def require_ai_provider_management_access(
    current_user: Union[Client, User] = Depends(get_current_user),
) -> Union[Client, User]:
    if isinstance(current_user, Client):
        return current_user
    if isinstance(current_user, User) and current_user.role in {"admin", "manager"}:
        return current_user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Acesso permitido apenas para titulares, administradores e gerentes",
    )


def _active_company_id(current_user: Union[Client, User]) -> int:
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empresa ativa não selecionada",
        )
    return int(company_id)


def _credential_response(
    credential: AIProviderCredential | None,
) -> AIProviderResponse:
    if credential is None:
        return AIProviderResponse(
            configured=False,
            status="not_configured",
        )
    return AIProviderResponse(
        configured=True,
        status=credential.status,
        last_validated_at=credential.last_validated_at,
        last_error=credential.last_error,
        models=list(credential.available_models or []),
    )


def _raise_provider_error(exc: ai_provider_service.AIProviderCredentialError) -> None:
    if isinstance(
        exc,
        ai_provider_knowledge_migration.AIProviderKnowledgeMigrationError,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    if isinstance(exc, ai_provider_service.AIProviderCompatibilityError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    if isinstance(exc, ai_provider_service.AIProviderValidationError):
        raise HTTPException(
            status_code=exc.http_status_code,
            detail=str(exc),
        ) from exc
    if isinstance(exc, ai_provider_service.AIProviderNotConfiguredError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=str(exc),
    ) from exc


@router.get("", response_model=AIProviderResponse)
def get_ai_provider(
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user),
) -> AIProviderResponse:
    company_id = _active_company_id(current_user)
    credential = ai_provider_service.get_company_ai_provider_credential(
        db,
        company_id,
    )
    return _credential_response(credential)


@router.put("", response_model=AIProviderResponse)
def put_ai_provider(
    payload: AIProviderUpsertRequest,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(
        require_ai_provider_management_access
    ),
) -> AIProviderResponse:
    company_id = _active_company_id(current_user)
    new_api_key = ""
    migration_result = (
        ai_provider_knowledge_migration.KnowledgeMigrationResult()
    )
    try:
        new_api_key = payload.validated_api_key()
        ai_provider_service.lock_company_ai_provider_configuration(
            db,
            company_id,
        )
        previous_credential = (
            ai_provider_service.get_company_ai_provider_credential(
                db,
                company_id,
            )
        )
        previous_api_key = None
        if previous_credential is not None:
            try:
                previous_api_key = ai_provider_service.decrypt_openai_api_key(
                    previous_credential.api_key_encrypted
                )
            except ai_provider_service.AIProviderCredentialError:
                previous_api_key = None

        credential = ai_provider_service.configure_company_openai_api_key(
            db,
            company_id,
            new_api_key,
        )
        ai_provider_service.ensure_company_workforce_models_are_supported(
            db,
            company_id,
            credential.available_models or [],
        )
        migration_result = (
            ai_provider_knowledge_migration
            .migrate_company_workforce_knowledge(
                db,
                company_id,
                new_api_key=new_api_key,
                previous_company_api_key=previous_api_key,
            )
        )
        db.commit()
    except ai_provider_service.AIProviderCredentialError as exc:
        db.rollback()
        ai_provider_knowledge_migration.cleanup_company_workforce_knowledge_migration(
            new_api_key,
            migration_result,
        )
        _raise_provider_error(exc)
    except Exception:
        db.rollback()
        ai_provider_knowledge_migration.cleanup_company_workforce_knowledge_migration(
            new_api_key,
            migration_result,
        )
        raise
    db.refresh(credential)
    return _credential_response(credential)


@router.post("/validate", response_model=AIProviderResponse)
def validate_ai_provider(
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(
        require_ai_provider_management_access
    ),
) -> AIProviderResponse:
    company_id = _active_company_id(current_user)
    ai_provider_service.lock_company_ai_provider_configuration(
        db,
        company_id,
    )
    credential = ai_provider_service.get_company_ai_provider_credential(
        db,
        company_id,
    )
    if credential is None:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chave OpenAI não configurada para a empresa ativa",
        )

    try:
        credential = ai_provider_service.validate_saved_company_openai_api_key(
            db,
            company_id,
        )
    except ai_provider_service.AIProviderValidationError as exc:
        ai_provider_service.mark_company_openai_validation_error(
            credential,
            exc,
        )
    except ai_provider_service.AIProviderCredentialError as exc:
        db.rollback()
        _raise_provider_error(exc)

    db.commit()
    db.refresh(credential)
    return _credential_response(credential)


@router.delete("", response_model=AIProviderResponse)
def delete_ai_provider(
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(
        require_ai_provider_management_access
    ),
) -> AIProviderResponse:
    company_id = _active_company_id(current_user)
    ai_provider_service.lock_company_ai_provider_configuration(
        db,
        company_id,
    )
    credential = ai_provider_service.get_company_ai_provider_credential(
        db,
        company_id,
    )
    if credential is not None:
        if ai_provider_knowledge_migration.company_has_workforce_knowledge(
            db,
            company_id,
        ):
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Esta chave protege uma base de conhecimento ativa. "
                    "Substitua a chave em vez de removê-la para migrar os arquivos com segurança."
                ),
            )
        db.delete(credential)
        db.commit()
    else:
        db.rollback()
    return _credential_response(None)
