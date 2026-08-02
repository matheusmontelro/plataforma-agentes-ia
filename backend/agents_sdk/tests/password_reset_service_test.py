import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ENVIRONMENT", "development")

from backend.models import Client, PasswordResetToken
from backend.services import password_reset_service as service
from backend.services.company_access_control import IdentityOperationBusyError


class FakeQuery:
    def __init__(self, db, model):
        self.db = db
        self.model = model

    def filter(self, *args, **kwargs):
        return self

    def join(self, *args, **kwargs):
        return self

    def with_for_update(self, *args, **kwargs):
        return self

    def first(self):
        if self.model is Client:
            return self.db.client
        if self.model is PasswordResetToken:
            return self.db.reset_token
        return None

    def all(self):
        if self.model is PasswordResetToken:
            return self.db.tokens
        return []


class FakeDB:
    def __init__(self, *, client=None, reset_token=None):
        self.client = client
        self.reset_token = reset_token
        self.tokens = [reset_token] if reset_token else []
        self.commits = 0
        self.rollbacks = 0

    def query(self, model):
        return FakeQuery(self, model)

    def add(self, value):
        if isinstance(value, PasswordResetToken):
            self.reset_token = value
            self.tokens.append(value)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_request_password_reset_creates_token_and_sends_generic_email(monkeypatch):
    client = Client(
        id=7,
        email="owner@example.com",
        company_id=3,
        billing_profile={"full_name": "Owner Name"},
    )
    db = FakeDB(client=client)
    sent_payload = {}

    monkeypatch.setattr(service.secrets, "token_urlsafe", lambda size: "raw-reset-token")
    monkeypatch.setattr(
        service,
        "send_password_reset_email",
        lambda **kwargs: sent_payload.update(kwargs) or SimpleNamespace(sent=True, skipped=False),
    )

    result = service.request_password_reset(db, email="OWNER@example.com", requested_ip="10.0.0.1")

    assert result.account_found is True
    assert db.reset_token.client_id == 7
    assert db.reset_token.email == "owner@example.com"
    assert db.reset_token.requested_ip == "10.0.0.1"
    assert sent_payload["to_email"] == "owner@example.com"
    assert "raw-reset-token" in sent_payload["reset_url"]


def test_password_setup_token_respects_minimum_ttl(monkeypatch):
    fixed_now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    client = Client(id=7, email="owner@example.com", company_id=3)
    db = FakeDB(client=client)

    monkeypatch.setattr(service, "_utcnow", lambda: fixed_now)
    monkeypatch.setattr(service.secrets, "token_urlsafe", lambda size: "raw-reset-token")

    result = service.create_password_setup_token_for_account(
        db,
        account=client,
        min_ttl_minutes=7 * 24 * 60,
    )

    assert result.expires_minutes == 7 * 24 * 60
    assert db.reset_token.expires_at == fixed_now + timedelta(days=7)


def test_confirm_password_reset_updates_password_and_consumes_tokens(monkeypatch):
    raw_token = "reset-token-value-long-enough-for-test"
    client = Client(
        id=9,
        email="owner@example.com",
        company_id=3,
        password="old-hash",
    )
    reset_token = PasswordResetToken(
        client_id=9,
        email="owner@example.com",
        token_hash=service._hash_reset_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    db = FakeDB(client=client, reset_token=reset_token)

    monkeypatch.setattr(service, "hash_password", lambda password: f"hashed:{password}")

    result = service.confirm_password_reset(
        db,
        token=raw_token,
        new_password="nova-senha",
        confirm_password="nova-senha",
    )

    assert result.email == "owner@example.com"
    assert result.account_type == "client"
    assert client.password == "hashed:nova-senha"
    assert reset_token.used_at is not None
    assert db.commits == 1
    assert db.rollbacks == 1


def test_password_reset_holds_identity_lock_through_commit_and_email(monkeypatch):
    events = []
    client = Client(id=7, email="owner@example.com", company_id=3)
    db = FakeDB(client=client)
    original_commit = db.commit

    @contextmanager
    def identity_lock(_db, email, **_kwargs):
        assert email == "owner@example.com"
        events.append("identity-enter")
        try:
            yield
        finally:
            events.append("identity-exit")

    def entity_lock(_db, **kwargs):
        assert kwargs == {"company_ids": [3], "client_ids": [7]}
        events.append("entity-lock")

    def commit():
        events.append("token-commit")
        original_commit()

    def send_email(**_kwargs):
        assert events[-1] == "token-commit"
        events.append("email-side-effect")
        return SimpleNamespace(sent=True, skipped=False)

    monkeypatch.setattr(service, "account_identity_operation_lock", identity_lock)
    monkeypatch.setattr(service, "lock_entities_for_mutation", entity_lock)
    monkeypatch.setattr(service, "send_password_reset_email", send_email)
    monkeypatch.setattr(service.secrets, "token_urlsafe", lambda size: "raw-reset-token")
    db.commit = commit

    result = service.request_password_reset(
        db,
        email="OWNER@example.com",
        requested_ip="10.0.0.1",
    )

    assert result.email_sent is True
    assert events == [
        "identity-enter",
        "entity-lock",
        "token-commit",
        "email-side-effect",
        "identity-exit",
    ]


def test_password_reset_confirmation_orders_identity_before_entities_and_token_commit(
    monkeypatch,
):
    events = []
    raw_token = "reset-token-value-long-enough-for-test"
    client = Client(
        id=9,
        email="owner@example.com",
        company_id=3,
        password="old-hash",
    )
    reset_token = PasswordResetToken(
        client_id=9,
        email="owner@example.com",
        token_hash=service._hash_reset_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    db = FakeDB(client=client, reset_token=reset_token)
    original_commit = db.commit

    @contextmanager
    def identity_lock(_db, email, **_kwargs):
        assert email == "owner@example.com"
        events.append("identity-enter")
        try:
            yield
        finally:
            events.append("identity-exit")

    def entity_lock(_db, **kwargs):
        assert kwargs == {"company_ids": [3], "client_ids": [9]}
        events.append("entity-lock")

    def commit():
        events.append("password-commit")
        original_commit()

    monkeypatch.setattr(service, "account_identity_operation_lock", identity_lock)
    monkeypatch.setattr(service, "lock_entities_for_mutation", entity_lock)
    monkeypatch.setattr(service, "hash_password", lambda password: f"hashed:{password}")
    db.commit = commit

    service.confirm_password_reset(
        db,
        token=raw_token,
        new_password="nova-senha",
        confirm_password="nova-senha",
    )

    assert events == [
        "identity-enter",
        "entity-lock",
        "password-commit",
        "identity-exit",
    ]


def test_confirm_reserves_capacity_before_first_token_query(monkeypatch):
    class ProbeDB:
        def __init__(self):
            self.query_calls = 0

        def query(self, *_args, **_kwargs):
            self.query_calls += 1
            raise AssertionError("token query must not run while capacity is full")

    @contextmanager
    def busy_reservation(*_args, **_kwargs):
        raise IdentityOperationBusyError("capacity")
        yield

    monkeypatch.setattr(service, "account_identity_operation_reservation", busy_reservation)
    db = ProbeDB()

    with pytest.raises(IdentityOperationBusyError) as exc:
        service.confirm_password_reset(
            db,
            token="reset-token-value-long-enough-for-capacity-test",
            new_password="nova-senha",
            confirm_password="nova-senha",
        )

    assert exc.value.reason == "capacity"
    assert db.query_calls == 0
