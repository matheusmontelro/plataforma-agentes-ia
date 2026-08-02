import asyncio
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-with-at-least-32-chars")

from backend.routes import password_reset_routes
from backend.services.company_access_control import (
    IdentityOperationBusyError,
)


async def _allow_rate_limit(*_args, **_kwargs):
    return None


def _request():
    return SimpleNamespace(
        headers={},
        client=SimpleNamespace(host="127.0.0.1"),
    )


def test_forgot_password_busy_is_generic_503_with_retry_after(monkeypatch):
    monkeypatch.setattr(
        password_reset_routes.auth_rate_limiter,
        "check",
        _allow_rate_limit,
    )

    def busy(*_args, **_kwargs):
        raise IdentityOperationBusyError("capacity")

    monkeypatch.setattr(password_reset_routes, "request_password_reset", busy)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            password_reset_routes.request_password_reset_endpoint(
                request=_request(),
                data=SimpleNamespace(email="owner@example.com"),
                db=object(),
            )
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == password_reset_routes.PASSWORD_RESET_BUSY_MESSAGE
    assert int(exc.value.headers["Retry-After"]) >= 1
    assert "owner@example.com" not in exc.value.detail


def test_confirm_password_busy_preserves_transient_http_contract(monkeypatch):
    monkeypatch.setattr(
        password_reset_routes.auth_rate_limiter,
        "check",
        _allow_rate_limit,
    )

    def busy(*_args, **_kwargs):
        raise IdentityOperationBusyError("external_identity")

    monkeypatch.setattr(password_reset_routes, "confirm_password_reset", busy)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            password_reset_routes.confirm_password_reset_endpoint(
                request=_request(),
                data=SimpleNamespace(
                    token="reset-token-value-long-enough-for-test",
                    new_password="nova-senha",
                    confirm_password="nova-senha",
                ),
                db=object(),
            )
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == password_reset_routes.PASSWORD_RESET_BUSY_MESSAGE
    assert int(exc.value.headers["Retry-After"]) >= 1
