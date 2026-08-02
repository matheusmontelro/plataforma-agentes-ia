"""Master account profile routes."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Optional, Union

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import Client, User
from backend.services.account_profile_service import (
    fill_account_billing_profile_defaults,
    is_account_billing_profile_complete,
    normalize_account_billing_profile,
)
from backend.runtime_settings import ACCOUNT_PROFILE_PHOTO_DIR as RUNTIME_ACCOUNT_PROFILE_PHOTO_DIR


router = APIRouter(prefix="/account/profile", tags=["account-profile"])

ACCOUNT_PROFILE_PHOTO_DIR = str(RUNTIME_ACCOUNT_PROFILE_PHOTO_DIR)
ACCOUNT_PROFILE_PHOTO_PUBLIC_PREFIX = os.getenv("ACCOUNT_PROFILE_PHOTO_PUBLIC_PREFIX", "/media/account-profiles")
MAX_PROFILE_PHOTO_BYTES = 4 * 1024 * 1024
ALLOWED_PROFILE_PHOTO_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class AccountBillingProfilePayload(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    cellphone: Optional[str] = None
    document: Optional[str] = None
    postal_code: Optional[str] = None
    street: Optional[str] = None
    number: Optional[str] = None
    neighborhood: Optional[str] = None
    complement: Optional[str] = None
    state: Optional[str] = None
    profile_picture_url: Optional[str] = None


class AccountProfileResponse(BaseModel):
    billing_profile: dict[str, str]
    profile_complete: bool
    email: str
    id: int


def _require_master_account(current_user: Union[Client, User]) -> Client:
    if not isinstance(current_user, Client):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Perfil da conta disponível apenas para o usuário master",
        )
    return current_user


def _build_response(client: Client) -> AccountProfileResponse:
    profile = fill_account_billing_profile_defaults(client.billing_profile, fallback_email=client.email)
    return AccountProfileResponse(
        id=int(client.id),
        email=str(client.email),
        billing_profile=profile,
        profile_complete=is_account_billing_profile_complete(profile),
    )


def _payload_data(payload: AccountBillingProfilePayload) -> dict[str, str]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(exclude_unset=True)
    return payload.dict(exclude_unset=True)


@router.get("", response_model=AccountProfileResponse)
def get_account_profile(current_user: Union[Client, User] = Depends(get_current_user)) -> AccountProfileResponse:
    client = _require_master_account(current_user)
    return _build_response(client)


@router.put("", response_model=AccountProfileResponse)
def update_account_profile(
    payload: AccountBillingProfilePayload,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user),
) -> AccountProfileResponse:
    client = _require_master_account(current_user)
    try:
        merged_profile = dict(client.billing_profile or {})
        merged_profile.update(_payload_data(payload))
        merged_profile["email"] = client.email
        profile = normalize_account_billing_profile(merged_profile, fallback_email=client.email)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    client.billing_profile = profile
    db.commit()
    db.refresh(client)
    return _build_response(client)


@router.post("/photo", response_model=AccountProfileResponse)
async def upload_account_profile_photo(
    photo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user),
) -> AccountProfileResponse:
    client = _require_master_account(current_user)
    content_type = (photo.content_type or "").lower()
    extension = ALLOWED_PROFILE_PHOTO_TYPES.get(content_type)
    if not extension:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Envie uma imagem JPG, PNG ou WebP",
        )

    contents = await photo.read()
    if not contents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Imagem vazia")
    if len(contents) > MAX_PROFILE_PHOTO_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Imagem deve ter até 4MB")

    target_dir = Path(ACCOUNT_PROFILE_PHOTO_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"client_{client.id}_{uuid.uuid4().hex}{extension}"
    target_path = (target_dir / filename).resolve()
    safe_dir = target_dir.resolve()
    if not str(target_path).startswith(f"{safe_dir}{os.sep}"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nome de imagem inválido")

    target_path.write_bytes(contents)

    profile = fill_account_billing_profile_defaults(client.billing_profile, fallback_email=client.email)
    profile["profile_picture_url"] = f"{ACCOUNT_PROFILE_PHOTO_PUBLIC_PREFIX.rstrip('/')}/{filename}"
    client.billing_profile = normalize_account_billing_profile(
        profile,
        fallback_email=client.email,
        validate_document=False,
    )
    db.commit()
    db.refresh(client)
    return _build_response(client)
