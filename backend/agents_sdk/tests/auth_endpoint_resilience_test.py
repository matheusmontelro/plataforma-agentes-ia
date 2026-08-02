import asyncio
import os
import sys
import time
import types
from inspect import signature
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy.exc import OperationalError

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")

# This deployment-only router is intentionally absent from clean worktrees.
test_notification_module = types.ModuleType("backend.routes.test_notification")
test_notification_module.router = APIRouter()
sys.modules.setdefault(
    "backend.routes.test_notification",
    test_notification_module,
)

from backend import auth, main
from backend.services import company_access_control


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("test", 123),
            "server": ("test", 80),
        }
    )


def _set_cookie_headers(response: Response) -> list[bytes]:
    return [
        value
        for name, value in response.raw_headers
        if name.lower() == b"set-cookie"
    ]


async def _allow_rate_limit(*_args, **_kwargs) -> None:
    return None


def test_login_runs_synchronous_authentication_off_event_loop(monkeypatch):
    monkeypatch.setattr(main.auth_rate_limiter, "check", _allow_rate_limit)

    def slow_login(*, email, password):
        assert email == "owner@example.com"
        assert password == "correct-password"
        time.sleep(0.15)
        return (
            {"access_token": "access", "refresh_token": "refresh"},
            {
                "token_type": "bearer",
                "company_id": 3,
                "clinic_id": 3,
                "client_id": 7,
                "user_type": "master",
                "user_id": 7,
                "team": None,
                "sidebar_permissions": [],
                "contact_permissions": {},
                "business_type": "business_company",
                "settings": {},
            },
        )

    monkeypatch.setattr(main, "_authenticate_login_request", slow_login)

    async def scenario():
        response = Response()
        login_task = asyncio.create_task(
            main.login(
                request=_request("/auth/login"),
                response=response,
                form_data=SimpleNamespace(
                    username="Owner@Example.com",
                    password="correct-password",
                ),
            )
        )
        heartbeat_ticks = 0
        while not login_task.done():
            await asyncio.sleep(0.01)
            heartbeat_ticks += 1
        payload = await login_task
        return response, payload, heartbeat_ticks

    response, payload, heartbeat_ticks = asyncio.run(scenario())

    assert heartbeat_ticks >= 5
    assert payload["user_id"] == 7
    assert len(_set_cookie_headers(response)) == 3
    assert "db" not in signature(main.login).parameters


def test_login_busy_returns_retry_after_without_cookies(monkeypatch):
    monkeypatch.setattr(main.auth_rate_limiter, "check", _allow_rate_limit)
    monkeypatch.setattr(
        main,
        "_authenticate_login_request",
        lambda **_kwargs: (_ for _ in ()).throw(
            main.CompanyOperationalLockBusyError(3)
        ),
    )
    response = Response()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            main.login(
                request=_request("/auth/login"),
                response=response,
                form_data=SimpleNamespace(
                    username="owner@example.com",
                    password="correct-password",
                ),
            )
        )

    assert exc.value.status_code == 503
    assert exc.value.headers == {"Retry-After": "2"}
    assert exc.value.detail == main.AUTH_BUSY_MESSAGE
    assert _set_cookie_headers(response) == []


def test_login_operational_block_propagates_without_cookies(monkeypatch):
    monkeypatch.setattr(main.auth_rate_limiter, "check", _allow_rate_limit)
    monkeypatch.setattr(
        main,
        "_authenticate_login_request",
        lambda **_kwargs: (_ for _ in ()).throw(
            HTTPException(
                status_code=423,
                detail=auth.OPERATIONAL_ACCESS_BLOCKED_MESSAGE,
            )
        ),
    )
    response = Response()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            main.login(
                request=_request("/auth/login"),
                response=response,
                form_data=SimpleNamespace(
                    username="owner@example.com",
                    password="correct-password",
                ),
            )
        )

    assert exc.value.status_code == 423
    assert _set_cookie_headers(response) == []


def test_login_unexpected_infrastructure_failure_is_sanitized(monkeypatch):
    monkeypatch.setattr(main.auth_rate_limiter, "check", _allow_rate_limit)
    monkeypatch.setattr(
        main,
        "_authenticate_login_request",
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("database failure contained secret credential marker")
        ),
    )
    response = Response()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            main.login(
                request=_request("/auth/login"),
                response=response,
                form_data=SimpleNamespace(
                    username="owner@example.com",
                    password="correct-password",
                ),
            )
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == main.AUTH_BUSY_MESSAGE
    assert "secret" not in str(exc.value.detail)
    assert _set_cookie_headers(response) == []


def test_refresh_infrastructure_failure_is_503_without_cookies(monkeypatch):
    monkeypatch.setattr(main.auth_rate_limiter, "check", _allow_rate_limit)
    monkeypatch.setattr(
        main,
        "refresh_access_token",
        lambda _token: (_ for _ in ()).throw(
            auth.AuthenticationInfrastructureError()
        ),
    )
    response = Response()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            main.refresh_token_endpoint(
                request=_request("/auth/refresh"),
                response=response,
                refresh_token="refresh-token",
            )
        )

    assert exc.value.status_code == 503
    assert exc.value.headers == {"Retry-After": "2"}
    assert exc.value.detail == main.AUTH_BUSY_MESSAGE
    assert _set_cookie_headers(response) == []
    assert "db" not in signature(main.refresh_token_endpoint).parameters


def test_login_worker_owns_session_until_payload_is_materialized(monkeypatch):
    company = SimpleNamespace(
        settings={"locale": "pt-BR"},
        business_type=SimpleNamespace(code="aesthetic_clinic"),
    )
    account = SimpleNamespace(id=7)

    class FakeQuery:
        def __init__(self, result):
            self.result = result

        def options(self, *_args):
            return self

        def filter(self, *_args):
            return self

        def first(self):
            return self.result

    class FakeSession:
        def __init__(self):
            self.closed = False
            self.commit_calls = 0
            self.rollback_calls = 0
            self.info = {}

        def query(self, model):
            assert not self.closed
            if model is main.Company:
                return FakeQuery(company)
            if model is main.Client:
                return FakeQuery(account)
            raise AssertionError(f"consulta inesperada: {model}")

        def close(self):
            self.closed = True

        def commit(self):
            self.commit_calls += 1

        def rollback(self):
            self.rollback_calls += 1

    db = FakeSession()
    authenticated = auth.LoginAuthenticationResult(
        account_id=7,
        client_id=7,
        company_id=3,
        user_type="master",
        team_id=None,
        tokens={"access_token": "access", "refresh_token": "refresh"},
    )
    monkeypatch.setattr(main, "SessionLocal", lambda: db)
    auth_call = {}

    def authenticate(*_args, **kwargs):
        auth_call.update(kwargs)
        return authenticated

    monkeypatch.setattr(main, "authenticate_login_and_issue_tokens", authenticate)
    monkeypatch.setattr(
        main,
        "build_user_permissions_payload",
        lambda _db, _account: {
            "team": None,
            "sidebar_permissions": ["dashboard"],
            "contact_permissions": {"pipeline_stage_ids": []},
        },
    )

    tokens, payload = main._authenticate_login_request(
        email="owner@example.com",
        password="correct-password",
    )

    assert db.closed is True
    assert db.commit_calls == 0
    assert db.rollback_calls == 1
    assert auth_call["finalize_transaction"] is False
    assert tokens["access_token"] == "access"
    assert payload["business_type"] == "aesthetic_clinic"
    assert payload["settings"] == {"locale": "pt-BR"}
    assert payload["sidebar_permissions"] == ["dashboard"]


def test_login_payload_failure_rolls_back_pending_staff_session(monkeypatch):
    company = SimpleNamespace(settings={}, business_type=None)
    account = SimpleNamespace(id=11)

    class FakeQuery:
        def __init__(self, result):
            self.result = result

        def options(self, *_args):
            return self

        def filter(self, *_args):
            return self

        def first(self):
            return self.result

    class FakeSession:
        def __init__(self):
            self.closed = False
            self.pending_user_session = False
            self.commit_calls = 0
            self.rollback_calls = 0
            self.info = {}

        def query(self, model):
            if model is main.Company:
                return FakeQuery(company)
            if model is main.User:
                return FakeQuery(account)
            raise AssertionError(f"consulta inesperada: {model}")

        def commit(self):
            self.commit_calls += 1
            self.pending_user_session = False

        def rollback(self):
            self.rollback_calls += 1
            self.pending_user_session = False

        def close(self):
            self.closed = True

    db = FakeSession()

    def authenticate(*_args, **kwargs):
        assert kwargs["finalize_transaction"] is False
        db.pending_user_session = True
        return auth.LoginAuthenticationResult(
            account_id=11,
            client_id=7,
            company_id=3,
            user_type="user",
            team_id=None,
            tokens={"access_token": "access", "refresh_token": "refresh"},
        )

    monkeypatch.setattr(main, "SessionLocal", lambda: db)
    monkeypatch.setattr(main, "authenticate_login_and_issue_tokens", authenticate)
    monkeypatch.setattr(
        main,
        "build_user_permissions_payload",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("payload unavailable")),
    )

    with pytest.raises(auth.AuthenticationInfrastructureError):
        main._authenticate_login_request(
            email="staff@example.com",
            password="correct-password",
        )

    assert db.pending_user_session is False
    assert db.commit_calls == 0
    assert db.rollback_calls == 1
    assert db.closed is True


@pytest.mark.parametrize(
    "busy_error",
    [
        main.CompanyOperationalLockBusyError(3),
        main.IdentityOperationBusyError("external_identity"),
    ],
)
def test_global_lock_busy_handler_returns_retryable_503(busy_error):
    response = asyncio.run(
        main.transient_lock_busy_exception_handler(
            _request("/api/leads/3"),
            busy_error,
        )
    )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "2"
    assert response.body == (
        b'{"detail":"Servi\xc3\xa7o temporariamente indispon\xc3\xadvel. '
        b'Tente novamente em instantes."}'
    )


def test_global_database_lock_timeout_handler_is_sanitized():
    original = RuntimeError("database details must stay internal")
    original.pgcode = "55P03"
    error = OperationalError("UPDATE private_table", {"token": "secret"}, original)

    response = asyncio.run(
        main.database_operational_error_handler(
            _request("/api/leads/3"),
            error,
        )
    )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert b"private_table" not in response.body
    assert b"secret" not in response.body


def test_global_database_pool_timeout_handler_is_retryable_and_sanitized():
    error = main.SQLAlchemyTimeoutError(
        "QueuePool limit reached for private database configuration"
    )

    response = asyncio.run(
        main.database_operational_error_handler(
            _request("/auth/login"),
            error,
        )
    )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "2"
    assert b"QueuePool" not in response.body
    assert b"private" not in response.body


def test_production_pool_contract_still_admits_all_auth_workers():
    assert (
        company_access_control._calculate_identity_operation_capacity(
            pool_capacity=20,
            pool_headroom=12,
            configured_max=4,
        )
        == 4
    )


def test_current_user_preserves_lock_timeout_for_retryable_503():
    original = RuntimeError("database details must stay internal")
    original.pgcode = "55P03"
    lock_error = OperationalError(
        "SELECT * FROM private_table WHERE token=:token",
        {"token": "secret-value"},
        original,
    )

    class _Query:
        def filter_by(self, **_kwargs):
            return self

        def first(self):
            raise lock_error

    class _DB:
        def query(self, _model):
            return _Query()

    token = auth.create_access_token(
        {
            "sub": "owner@example.com",
            "user_id": 7,
            "client_id": 7,
            "user_type": "master",
            "tv": 0,
        }
    )
    with pytest.raises(OperationalError) as exc:
        auth.get_current_user(token=token, cookie_token=None, db=_DB())

    response = asyncio.run(
        main.database_operational_error_handler(
            _request("/api/company"),
            exc.value,
        )
    )
    assert response.status_code == 503
    assert b"private_table" not in response.body
    assert b"secret-value" not in response.body
