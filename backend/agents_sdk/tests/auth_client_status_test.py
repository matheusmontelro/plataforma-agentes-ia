import os
import asyncio

import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ENVIRONMENT", "development")

from backend import auth
from backend.models import Client, User


class FakeQuery:
    def __init__(self, result=None):
        self.result = result

    def filter_by(self, **kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.result


class FakeDB:
    def __init__(self, *, client=None, user=None, master=None, sql_results=None):
        self.client = client
        self.user = user
        self.master = master
        self.sql_results = list(sql_results or [])
        self.executed_sql = []
        self.rollback_calls = 0
        self.close_calls = 0

    def query(self, model):
        if model is Client:
            return FakeQuery(self.master if self.master is not None else self.client)
        if model is User:
            return FakeQuery(self.user)
        return FakeQuery()

    def execute(self, statement, params=None):
        self.executed_sql.append(str(statement))
        result = self.sql_results.pop(0) if self.sql_results else None
        return FakeExecutionResult(result)

    def rollback(self):
        self.rollback_calls += 1

    def expire_all(self):
        return None

    def close(self):
        self.close_calls += 1


class FakeExecutionResult:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


def test_websocket_barrier_releases_transaction_without_closing_session():
    db = FakeDB()

    auth.release_websocket_db_transaction(db)

    assert db.rollback_calls == 1
    assert db.close_calls == 0


def test_get_current_user_rejects_inactive_master(monkeypatch):
    client = Client(id=7, email="owner@example.com", is_active=False)
    db = FakeDB(client=client)

    monkeypatch.setattr(
        auth,
        "decode_token",
        lambda token: {"sub": "owner@example.com", "user_id": "7", "user_type": "master"},
    )

    with pytest.raises(HTTPException) as exc:
        auth.get_current_user(token="access-token", db=db)

    assert exc.value.status_code == 401
    assert "Usuário inativo" in str(exc.value.detail)


def test_login_with_invalid_password_rejects_before_account_state_checks(monkeypatch):
    client = Client(
        id=7,
        email="owner@example.com",
        company_id=3,
        is_active=False,
        **{"password": "hash"},
    )
    db = FakeDB(client=client)

    monkeypatch.setattr(auth, "verify_password", lambda *_args: False)
    with pytest.raises(HTTPException) as exc:
        auth.authenticate_login_and_issue_tokens(
            db,
            email="owner@example.com",
            **{"password": "wrong-password"},
        )

    assert exc.value.status_code == 401
    assert exc.value.detail == "Credenciais inválidas"


def test_login_reports_company_operational_block_only_after_valid_password(monkeypatch):
    client = Client(
        id=7,
        email="owner@example.com",
        company_id=3,
        is_active=True,
        **{"password": "hash"},
    )
    db = FakeDB(client=client)
    monkeypatch.setattr(auth, "verify_password", lambda *_args: True)
    monkeypatch.setattr(
        auth,
        "try_lock_entities_for_access",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        auth,
        "ensure_company_operational",
        lambda *_args: (_ for _ in ()).throw(
            auth.CompanyOperationallyBlockedError(3, "suspended")
        ),
    )
    monkeypatch.setattr(
        auth,
        "create_tokens_for_user",
        lambda *_args: pytest.fail("bloqueio não pode emitir token"),
    )

    with pytest.raises(HTTPException) as exc:
        auth.authenticate_login_and_issue_tokens(
            db,
            email="owner@example.com",
            password="correct-password",
        )

    assert exc.value.status_code == 423
    assert exc.value.detail == auth.OPERATIONAL_ACCESS_BLOCKED_MESSAGE


def test_refresh_access_token_rejects_user_when_master_is_inactive(monkeypatch):
    user = User(id=11, client_id=7, company_id=3, email="staff@example.com", is_active=True)
    master = Client(id=7, email="owner@example.com", is_active=False)
    db = FakeDB(user=user, master=master)

    monkeypatch.setattr(
        auth,
        "decode_token",
        lambda token, verify_access=False: {
            "sub": "staff@example.com",
            "user_id": "11",
            "user_type": "user",
        },
    )

    with pytest.raises(HTTPException) as exc:
        auth._refresh_access_token_with_db("refresh-token", db)

    assert exc.value.status_code == 401
    assert "Cliente master não encontrado" in str(exc.value.detail)


def test_refresh_infrastructure_failure_is_sanitized(monkeypatch, caplog):
    class ExplodingDB(FakeDB):
        def query(self, _model):
            raise RuntimeError("database failure contained secret credential marker")

    db = ExplodingDB()
    monkeypatch.setattr(
        auth,
        "decode_token",
        lambda token, verify_access=False: {
            "sub": "staff@example.com",
            "user_id": "11",
            "user_type": "user",
        },
    )

    with pytest.raises(auth.AuthenticationInfrastructureError) as exc:
        auth._refresh_access_token_with_db("refresh-token", db)

    assert "secret" not in str(exc.value)
    assert "secret" not in caplog.text
    assert db.rollback_calls == 1


def test_verify_company_access_requires_active_master_in_sql(monkeypatch):
    db = FakeDB(sql_results=[None, object()])

    monkeypatch.setattr(auth, "ensure_managed_workspace_access", lambda db, company_id: None)

    assert asyncio.run(auth.verify_company_access("7", 3, db)) is True
    sql = "\n".join(db.executed_sql)
    assert "c.is_active = true" in sql
    assert "JOIN clients c ON c.id = cc.client_id" in sql


def test_websocket_auth_rejects_user_when_master_is_inactive(monkeypatch):
    user = User(id=11, client_id=7, company_id=3, email="staff@example.com", is_active=True)
    master = Client(id=7, email="owner@example.com", is_active=False)
    db = FakeDB(user=user, master=master)

    monkeypatch.setattr(
        auth,
        "decode_token",
        lambda token: {
            "sub": "staff@example.com",
            "user_id": "11",
            "client_id": "7",
            "company_id": "3",
            "user_type": "user",
        },
    )

    with pytest.raises(auth.WebSocketAuthError) as exc:
        asyncio.run(auth.get_current_user_ws("access-token", db))

    assert exc.value.code == 4001
    assert "Cliente master não encontrado" in exc.value.message
