"""Public password reset endpoints."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.security import auth_rate_limiter, get_client_ip
from backend.services.company_access_control import IdentityOperationBusyError
from backend.services.password_reset_service import confirm_password_reset, request_password_reset


router = APIRouter()

AUTH_PASSWORD_RESET_RATE_LIMIT = int(os.getenv("AUTH_PASSWORD_RESET_RATE_LIMIT", "5"))
AUTH_PASSWORD_RESET_RATE_WINDOW_SECONDS = int(os.getenv("AUTH_PASSWORD_RESET_RATE_WINDOW_SECONDS", "3600"))
AUTH_PASSWORD_RESET_CONFIRM_RATE_LIMIT = int(os.getenv("AUTH_PASSWORD_RESET_CONFIRM_RATE_LIMIT", "10"))
AUTH_PASSWORD_RESET_CONFIRM_RATE_WINDOW_SECONDS = int(os.getenv("AUTH_PASSWORD_RESET_CONFIRM_RATE_WINDOW_SECONDS", "3600"))
PASSWORD_RESET_BUSY_MESSAGE = "Serviço temporariamente indisponível. Tente novamente em instantes."


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(..., min_length=20)
    new_password: str = Field(..., min_length=6)
    confirm_password: str = Field(..., min_length=6)


def _password_reset_busy_response(
    exc: IdentityOperationBusyError,
) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=PASSWORD_RESET_BUSY_MESSAGE,
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


@router.post("/password-reset/request")
async def request_password_reset_endpoint(
    request: Request,
    data: PasswordResetRequest,
    db: Session = Depends(get_db),
):
    await auth_rate_limiter.check(
        request,
        "auth.password_reset.request",
        str(data.email),
        limit=AUTH_PASSWORD_RESET_RATE_LIMIT,
        window_seconds=AUTH_PASSWORD_RESET_RATE_WINDOW_SECONDS,
    )
    try:
        request_password_reset(
            db,
            email=str(data.email),
            requested_ip=get_client_ip(request),
        )
    except IdentityOperationBusyError as exc:
        raise _password_reset_busy_response(exc) from None
    return {"message": "Se o email existir, enviaremos instruções para redefinir sua senha."}


@router.post("/password-reset/confirm")
async def confirm_password_reset_endpoint(
    request: Request,
    data: PasswordResetConfirm,
    db: Session = Depends(get_db),
):
    await auth_rate_limiter.check(
        request,
        "auth.password_reset.confirm",
        data.token[:32],
        limit=AUTH_PASSWORD_RESET_CONFIRM_RATE_LIMIT,
        window_seconds=AUTH_PASSWORD_RESET_CONFIRM_RATE_WINDOW_SECONDS,
    )
    try:
        confirm_password_reset(
            db,
            token=data.token,
            new_password=data.new_password,
            confirm_password=data.confirm_password,
        )
    except IdentityOperationBusyError as exc:
        raise _password_reset_busy_response(exc) from None
    return {"message": "Senha redefinida com sucesso."}
