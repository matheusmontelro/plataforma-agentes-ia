"""Password reset token lifecycle for master and internal users."""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from urllib.parse import quote

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.auth import hash_password
from backend.models import Client, Company, PasswordResetToken, User
from backend.services.company_access_control import (
    account_identity_operation_lock,
    account_identity_operation_reservation,
    lock_entities_for_mutation,
    normalize_account_email,
)
from backend.services.transactional_email_service import (
    get_public_app_origin,
    send_password_reset_email,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PasswordResetRequestResult:
    account_found: bool
    email_sent: bool
    email_skipped: bool = False


@dataclass(frozen=True)
class PasswordSetupTokenResult:
    reset_url: str
    expires_minutes: int


@dataclass(frozen=True)
class PasswordResetConfirmResult:
    email: str
    account_type: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_email(email: str) -> str:
    return normalize_account_email(email)


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_ttl_minutes(*, min_ttl_minutes: Optional[int] = None) -> int:
    raw_value = os.getenv("PASSWORD_RESET_TOKEN_TTL_MINUTES", "60").strip()
    try:
        ttl_minutes = max(5, min(int(raw_value), 24 * 60))
    except ValueError:
        ttl_minutes = 60

    if min_ttl_minutes is None:
        return ttl_minutes

    return max(ttl_minutes, int(min_ttl_minutes))


def _find_account_by_email(db: Session, email: str) -> Optional[Any]:
    normalized_email = _normalize_email(email)
    client = (
        db.query(Client)
        .join(Company, Company.id == Client.ownership_company_id)
        .filter(
            func.lower(Client.email) == normalized_email,
            Client.is_active.is_(True),
            Company.operational_status == "active",
        )
        .first()
    )
    if client:
        return client

    user = (
        db.query(User)
        .join(Client, Client.id == User.client_id)
        .join(Company, Company.id == User.company_id)
        .filter(
            func.lower(User.email) == normalized_email,
            User.is_active.is_(True),
            Client.is_active.is_(True),
            Company.operational_status == "active",
        )
        .first()
    )
    return user


def _lock_and_validate_account(db: Session, account: Any) -> Optional[Any]:
    if isinstance(account, Client):
        return (
            db.query(Client)
            .join(Company, Company.id == Client.ownership_company_id)
            .filter(
                Client.id == account.id,
                Client.is_active.is_(True),
                Company.operational_status == "active",
            )
            .with_for_update()
            .first()
        )
    if isinstance(account, User):
        return (
            db.query(User)
            .join(Client, Client.id == User.client_id)
            .join(Company, Company.id == User.company_id)
            .filter(
                User.id == account.id,
                User.is_active.is_(True),
                Client.is_active.is_(True),
                Company.operational_status == "active",
            )
            .with_for_update()
            .first()
        )
    return None


def _lock_account_entities(db: Session, account: Any) -> None:
    if isinstance(account, Client):
        ownership_company_id = (
            getattr(account, "ownership_company_id", None)
            or account.company_id
        )
        lock_entities_for_mutation(
            db,
            company_ids=[int(ownership_company_id)],
            client_ids=[int(account.id)],
        )
    elif isinstance(account, User):
        lock_entities_for_mutation(
            db,
            company_ids=[int(account.company_id)],
            client_ids=[int(account.client_id)],
            user_ids=[int(account.id)],
        )


def _account_display_name(account: Any) -> Optional[str]:
    name = getattr(account, "name", None)
    if name:
        return str(name)

    billing_profile = getattr(account, "billing_profile", None) or {}
    return billing_profile.get("full_name")


def create_password_setup_token_for_account(
    db: Session,
    *,
    account: Any,
    requested_ip: Optional[str] = None,
    min_ttl_minutes: Optional[int] = None,
    _identity_lock_held: bool = False,
) -> PasswordSetupTokenResult:
    normalized_email = _normalize_email(str(getattr(account, "email", "") or ""))
    if not normalized_email:
        raise ValueError("Conta sem email para definição de senha")

    is_client = isinstance(account, Client)
    is_user = isinstance(account, User)
    if not is_client and not is_user:
        raise ValueError("Tipo de conta inválido para definição de senha")

    def _create_locked() -> PasswordSetupTokenResult:
        nonlocal account
        _lock_account_entities(db, account)
        account = _lock_and_validate_account(db, account)
        if not account:
            raise ValueError("Conta inativa para definição de senha")

        raw_token = secrets.token_urlsafe(48)
        ttl_minutes = _token_ttl_minutes(min_ttl_minutes=min_ttl_minutes)
        reset_token = PasswordResetToken(
            client_id=account.id if is_client else None,
            user_id=account.id if is_user else None,
            email=normalized_email,
            token_hash=_hash_reset_token(raw_token),
            expires_at=_utcnow() + timedelta(minutes=ttl_minutes),
            requested_ip=(requested_ip or "")[:64] or None,
        )
        db.add(reset_token)
        db.commit()

        return PasswordSetupTokenResult(
            reset_url=f"{get_public_app_origin()}/reset-password?token={quote(raw_token)}",
            expires_minutes=ttl_minutes,
        )

    if _identity_lock_held:
        return _create_locked()
    with account_identity_operation_lock(db, normalized_email):
        return _create_locked()


def request_password_reset(db: Session, *, email: str, requested_ip: Optional[str] = None) -> PasswordResetRequestResult:
    normalized_email = _normalize_email(email)
    with account_identity_operation_lock(db, normalized_email):
        account = _find_account_by_email(db, normalized_email)
        if not account:
            return PasswordResetRequestResult(
                account_found=False,
                email_sent=False,
                email_skipped=True,
            )

        token_result = create_password_setup_token_for_account(
            db,
            account=account,
            requested_ip=requested_ip,
            _identity_lock_held=True,
        )
        try:
            email_result = send_password_reset_email(
                to_email=normalized_email,
                to_name=_account_display_name(account),
                reset_url=token_result.reset_url,
                expires_minutes=token_result.expires_minutes,
            )
        except Exception as exc:
            logger.warning(
                "Falha inesperada no envio de reset de senha email=%s erro=%s",
                normalized_email,
                exc.__class__.__name__,
            )
            return PasswordResetRequestResult(
                account_found=True,
                email_sent=False,
                email_skipped=False,
            )

        return PasswordResetRequestResult(
            account_found=True,
            email_sent=email_result.sent,
            email_skipped=email_result.skipped,
        )


def _invalidate_active_tokens(db: Session, *, client_id: Optional[int], user_id: Optional[int], used_at: datetime) -> None:
    query = db.query(PasswordResetToken).filter(PasswordResetToken.used_at.is_(None))
    if client_id:
        query = query.filter(PasswordResetToken.client_id == client_id)
    if user_id:
        query = query.filter(PasswordResetToken.user_id == user_id)

    for token in query.all():
        token.used_at = used_at


def confirm_password_reset(
    db: Session,
    *,
    token: str,
    new_password: str,
    confirm_password: str,
) -> PasswordResetConfirmResult:
    if not token or len(token.strip()) < 20:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token inválido ou expirado")

    if len(new_password) < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A senha deve ter pelo menos 6 caracteres")

    if new_password != confirm_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Senhas não conferem")

    token_hash = _hash_reset_token(token.strip())
    with account_identity_operation_reservation(
        db,
        token_hash,
    ) as capacity_reservation:
        token_snapshot = db.query(PasswordResetToken).filter(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
        ).first()

        if not token_snapshot or _aware_utc(token_snapshot.expires_at) <= _utcnow():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Token inválido ou expirado",
            )

        normalized_email = _normalize_email(token_snapshot.email)
        rollback = getattr(db, "rollback", None)
        if callable(rollback):
            # Return the preflight query connection before checking out the
            # dedicated advisory-lock connection. Everything is re-read under
            # the identity lock below.
            rollback()

        with account_identity_operation_lock(
            db,
            normalized_email,
            reservation=capacity_reservation,
        ):
            # Re-read without a row lock after the identity lock, then acquire
            # the compatible entity locks before locking account/token rows.
            # This keeps identity -> company -> client -> user -> token order.
            current_snapshot = db.query(PasswordResetToken).filter(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
            ).first()
            if (
                not current_snapshot
                or _aware_utc(current_snapshot.expires_at) <= _utcnow()
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Token inválido ou expirado",
                )

            account_type = "client"
            if current_snapshot.client_id:
                account_snapshot = (
                    db.query(Client)
                    .filter(Client.id == current_snapshot.client_id)
                    .first()
                )
            elif current_snapshot.user_id:
                account_type = "user"
                account_snapshot = (
                    db.query(User)
                    .filter(User.id == current_snapshot.user_id)
                    .first()
                )
            else:
                account_snapshot = None

            if not account_snapshot:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Token inválido ou expirado",
                )

            _lock_account_entities(db, account_snapshot)
            account = _lock_and_validate_account(db, account_snapshot)
            if not account:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Token inválido ou expirado",
                )

            reset_token = (
                db.query(PasswordResetToken)
                .filter(
                    PasswordResetToken.token_hash == token_hash,
                    PasswordResetToken.used_at.is_(None),
                )
                .with_for_update()
                .first()
            )
            if (
                not reset_token
                or _aware_utc(reset_token.expires_at) <= _utcnow()
                or _normalize_email(reset_token.email) != normalized_email
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Token inválido ou expirado",
                )

            now = _utcnow()
            account.password = hash_password(new_password)
            _invalidate_active_tokens(
                db,
                client_id=reset_token.client_id,
                user_id=reset_token.user_id,
                used_at=now,
            )
            db.commit()
            return PasswordResetConfirmResult(
                email=account.email,
                account_type=account_type,
            )
