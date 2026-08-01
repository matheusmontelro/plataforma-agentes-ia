import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ENVIRONMENT", "development")

from backend import auth
from backend.db import Base
from backend.integrations import whatsapp_provider
from backend.integrations.waha_sdk import WAHAException
from backend.integrations.whatsapp_provider import WhatsAppConfig
from backend.routes import customer_management_routes, webhook
from backend.routes import users as users_routes
from backend.models import (
    BusinessType,
    Client,
    ClientCompany,
    Company,
    Contact,
    Customer,
    CustomerManagedCompany,
    PasswordResetToken,
    RefundAccessEntityState,
    RefundAccessEvent,
    RefundAccessSuspension,
    RefundAccessTarget,
    Team,
    User,
    UserSession,
)
from backend.services import password_reset_service
from backend.services import registration_eligibility_service
from backend.services import refund_access_service as service
from backend.services.company_access_control import is_email_refund_blocked
from backend.services.registration_eligibility_service import ensure_registration_eligibility

_REAL_RUN_WAHA_BLOCK_ACTIONS = service._run_waha_block_actions


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(type_, compiler, **kwargs):
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_for_sqlite(type_, compiler, **kwargs):
    return "JSON"


@compiles(UUID, "sqlite")
def _compile_uuid_for_sqlite(type_, compiler, **kwargs):
    return "CHAR(36)"


@compiles(BigInteger, "sqlite")
def _compile_bigint_for_sqlite(type_, compiler, **kwargs):
    return "INTEGER"


CORE_TABLES = [
    BusinessType.__table__,
    Company.__table__,
    Client.__table__,
    ClientCompany.__table__,
    Contact.__table__,
    Customer.__table__,
    CustomerManagedCompany.__table__,
    Team.__table__,
    User.__table__,
    UserSession.__table__,
    PasswordResetToken.__table__,
    RefundAccessSuspension.__table__,
    RefundAccessEvent.__table__,
    RefundAccessTarget.__table__,
    RefundAccessEntityState.__table__,
]


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=CORE_TABLES)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    session.add(BusinessType(id=1, name="Empresa", code="business_company"))
    session.commit()

    monkeypatch.setattr(service, "_cancel_pending_work", lambda db, company_ids: 0)
    monkeypatch.setattr(service, "_run_waha_block_actions", lambda db, suspension, state: None)
    monkeypatch.setattr(
        service,
        "_run_waha_restore_actions",
        lambda *_args, **_kwargs: None,
    )
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_account(
    db,
    *,
    email="aluno@example.com",
    company_id=10,
    client_active=True,
    user_active=True,
    waha_enabled=True,
):
    company = Company(
        id=company_id,
        name=f"Empresa {company_id}",
        cnpj=f"{company_id:014d}",
        business_type_id=1,
        waha_session_name=f"company_{company_id}",
        waha_enabled=waha_enabled,
        operational_status="active",
    )
    client = Client(
        id=company_id,
        email=email,
        password="hash",
        company_id=company_id,
        api_key=f"key-{company_id}",
        is_active=client_active,
        auth_token_version=0,
    )
    user = User(
        id=company_id,
        client_id=client.id,
        company_id=company.id,
        email=f"staff-{company_id}@example.com",
        password="hash",
        name="Staff",
        is_active=user_active,
        auth_token_version=0,
    )
    db.add_all(
        [
            company,
            client,
            ClientCompany(client_id=client.id, company_id=company.id),
            user,
            UserSession(
                user_id=user.id,
                client_id=client.id,
                token="session-token",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            PasswordResetToken(
                client_id=client.id,
                email=email,
                token_hash=f"{company_id:064d}",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
        ]
    )
    db.commit()
    return company, client, user


def _command(
    *,
    event_id,
    invoice_id,
    state,
    email="aluno@example.com",
    minute=0,
):
    return service.RefundAccessCommand(
        event_id=event_id,
        idempotency_key=f"idem-{event_id}",
        invoice_id=invoice_id,
        email=email,
        state=state,
        occurred_at=datetime(2026, 7, 19, 12, minute, tzinfo=timezone.utc),
        source="eduzz",
    )


def test_pending_blocks_credentials_sessions_reset_jwt_api_and_ws(db, monkeypatch):
    company, client, user = _seed_account(db)
    old_api_key = client.api_key
    old_token = auth.create_access_token(
        {
            "sub": client.email,
            "user_id": str(client.id),
            "client_id": str(client.id),
            "user_type": "master",
            "tv": 0,
        }
    )

    result = service.process_refund_access(
        db,
        _command(event_id="wait-1", invoice_id="sale-1", state="refund_pending"),
    )
    db.refresh(company)
    db.refresh(client)
    db.refresh(user)

    assert result.status == "processed"
    assert company.operational_status == "refund_pending"
    assert company.operational_epoch == 1
    assert company.waha_enabled is False
    assert client.is_active is False
    assert client.api_key is None
    assert client.auth_token_version == 1
    assert user.is_active is False
    assert db.query(UserSession).count() == 0
    assert db.query(PasswordResetToken).filter(PasswordResetToken.used_at.is_(None)).count() == 0
    assert password_reset_service._find_account_by_email(db, client.email) is None

    with pytest.raises(HTTPException):
        auth.get_current_user(token=old_token, db=db)
    with pytest.raises(HTTPException):
        auth.verify_client_or_bearer_api_key(
            client_id=client.id,
            company_id=company.id,
            api_key=old_api_key,
            db=db,
        )
    with pytest.raises(auth.WebSocketAuthError):
        asyncio.run(auth.get_current_user_ws(old_token, db))


def test_overlapping_invoices_restore_shared_baseline_only_after_last_block(db):
    company, client, user = _seed_account(db)
    inactive_user = User(
        id=999,
        client_id=client.id,
        company_id=company.id,
        email="inactive@example.com",
        password="hash",
        name="Inactive",
        is_active=False,
        auth_token_version=0,
    )
    db.add(inactive_user)
    db.commit()

    service.process_refund_access(
        db,
        _command(event_id="wait-a", invoice_id="sale-a", state="refund_pending", minute=0),
    )
    service.process_refund_access(
        db,
        _command(event_id="wait-b", invoice_id="sale-b", state="refund_pending", minute=1),
    )
    first_restore = service.process_refund_access(
        db,
        _command(event_id="paid-a", invoice_id="sale-a", state="active", minute=2),
    )
    db.refresh(client)
    assert first_restore.state == "refund_pending"
    assert client.is_active is False

    final_restore = service.process_refund_access(
        db,
        _command(event_id="paid-b", invoice_id="sale-b", state="active", minute=3),
    )
    for value in (company, client, user, inactive_user):
        db.refresh(value)
    assert company.operational_status == "active"
    assert company.operational_epoch == 1
    assert company.waha_enabled is True
    assert client.is_active is True
    assert client.api_key is None
    assert user.is_active is True
    assert inactive_user.is_active is False
    assert db.query(RefundAccessEntityState).count() == 0
    assert final_restore.state == "active"


def test_restore_reports_refunded_when_another_invoice_is_terminal(db):
    company, client, _ = _seed_account(db)
    service.process_refund_access(
        db,
        _command(event_id="wait-a", invoice_id="sale-a", state="refund_pending", minute=0),
    )
    service.process_refund_access(
        db,
        _command(event_id="wait-b", invoice_id="sale-b", state="refund_pending", minute=1),
    )
    service.process_refund_access(
        db,
        _command(event_id="refund-b", invoice_id="sale-b", state="refunded", minute=2),
    )

    result = service.process_refund_access(
        db,
        _command(event_id="paid-a", invoice_id="sale-a", state="active", minute=3),
    )

    db.refresh(company)
    db.refresh(client)
    assert result.state == "refunded"
    assert company.operational_status == "refunded"
    assert client.is_active is False


def test_newer_different_invoice_supersedes_terminal_without_restoring_waha(db):
    company, client, user = _seed_account(db)
    service.process_refund_access(
        db,
        _command(event_id="refund-a", invoice_id="sale-a", state="refunded", minute=0),
    )

    repurchase = service.process_refund_access(
        db,
        _command(event_id="paid-b", invoice_id="sale-b", state="active", minute=1),
    )

    for entity in (company, client, user):
        db.refresh(entity)
    terminal = db.query(RefundAccessSuspension).filter_by(invoice_id="sale-a").one()
    assert terminal.state == "refunded"
    assert repurchase.state == "active"
    assert repurchase.supersedes_prior_terminal is True
    assert company.operational_status == "active"
    assert company.waha_enabled is False
    assert client.is_active is True
    assert client.api_key is None
    assert user.is_active is True
    assert is_email_refund_blocked(db, "aluno@example.com") is False


def test_completed_terminal_replay_recomputes_newer_entitlement_shadow(db):
    _seed_account(db)
    terminal_command = _command(
        event_id="refund-a-before-repurchase",
        invoice_id="sale-a",
        state="refunded",
        minute=0,
    )
    original = service.process_refund_access(db, terminal_command)
    service.process_refund_access(
        db,
        _command(
            event_id="paid-b-after-terminal",
            invoice_id="sale-b",
            state="active",
            minute=1,
        ),
    )

    replay = service.process_refund_access(db, terminal_command)

    suspension = (
        db.query(RefundAccessSuspension).filter_by(invoice_id="sale-a").one()
    )
    event = (
        db.query(RefundAccessEvent)
        .filter_by(event_id=terminal_command.event_id)
        .one()
    )
    assert original.status == "processed"
    assert original.shadowed_by_newer_entitlement is False
    assert replay.status == "stale"
    assert replay.state == "active"
    assert replay.shadowed_by_newer_entitlement is True
    assert service._aware_utc(suspension.latest_occurred_at) == datetime(
        2026, 7, 19, 12, 0, tzinfo=timezone.utc
    )
    assert event.response_payload["shadowedByNewerEntitlement"] is False


def test_late_older_terminal_is_audited_but_shadowed_by_prior_entitlement(db):
    company, client, user = _seed_account(db)
    paid = _command(
        event_id="paid-b",
        invoice_id="sale-b",
        state="active",
        minute=2,
    )
    paid_result = service.process_refund_access(db, paid)

    shadowed = _command(
        event_id="refund-a-late",
        invoice_id="sale-a",
        state="refunded",
        minute=1,
    )
    result = service.process_refund_access(db, shadowed)
    duplicate = service.process_refund_access(db, shadowed)

    for entity in (company, client, user):
        db.refresh(entity)
    terminal = db.query(RefundAccessSuspension).filter_by(invoice_id="sale-a").one()
    assert paid_result.new_entitlement is True
    assert paid_result.as_payload()["newEntitlement"] is True
    assert result.status == "stale"
    assert result.state == "active"
    assert result.shadowed_by_newer_entitlement is True
    assert result.as_payload()["shadowedByNewerEntitlement"] is True
    assert duplicate.status == "stale"
    assert duplicate.state == "active"
    assert duplicate.shadowed_by_newer_entitlement is True
    assert terminal.state == "refunded"
    assert company.operational_status == "active"
    assert company.waha_enabled is True
    assert client.is_active is True
    assert client.api_key == "key-10"
    assert user.is_active is True
    assert is_email_refund_blocked(db, "aluno@example.com") is False


def test_cross_email_entitlement_shadows_old_terminal_through_pending_cycle(
    db,
    monkeypatch,
):
    old_email = "aluno-antigo@example.com"
    new_email = "aluno-novo@example.com"
    company, client, user = _seed_account(db, email=old_email)
    block_actions = []
    monkeypatch.setattr(
        service,
        "_run_waha_block_actions",
        lambda _db, suspension, state: block_actions.append(
            (str(suspension.invoice_id), state)
        ),
    )

    service.process_refund_access(
        db,
        _command(
            event_id="paid-a-old-email",
            invoice_id="sale-a",
            state="active",
            email=old_email,
            minute=0,
        ),
    )
    client.email = new_email
    db.commit()
    paid_b = service.process_refund_access(
        db,
        _command(
            event_id="paid-b-new-email",
            invoice_id="sale-b",
            state="active",
            email=new_email,
            minute=3,
        ),
    )

    late_a_command = _command(
        event_id="refund-a-old-email",
        invoice_id="sale-a",
        state="refunded",
        email=old_email,
        minute=2,
    )
    late_a = service.process_refund_access(db, late_a_command)

    for entity in (company, client, user):
        db.refresh(entity)
    suspension_a = (
        db.query(RefundAccessSuspension).filter_by(invoice_id="sale-a").one()
    )
    suspension_b = (
        db.query(RefundAccessSuspension).filter_by(invoice_id="sale-b").one()
    )
    assert paid_b.new_entitlement is True
    assert late_a.status == "stale"
    assert late_a.state == "active"
    assert late_a.shadowed_by_newer_entitlement is True
    assert suspension_a.state == "refunded"
    assert suspension_a.root_client_id == client.id
    assert suspension_b.root_client_id == client.id
    assert suspension_a.email_hash != suspension_b.email_hash
    assert block_actions == []
    assert company.operational_status == "active"
    assert client.is_active is True
    assert user.is_active is True

    pending_b = service.process_refund_access(
        db,
        _command(
            event_id="wait-b-new-email",
            invoice_id="sale-b",
            state="refund_pending",
            email=new_email,
            minute=4,
        ),
    )
    db.refresh(company)
    db.refresh(client)
    assert pending_b.status == "processed"
    assert pending_b.state == "refund_pending"
    assert pending_b.shadowed_by_newer_entitlement is False
    assert company.operational_status == "refund_pending"
    assert client.is_active is False

    restored_b = service.process_refund_access(
        db,
        _command(
            event_id="paid-b-after-wait",
            invoice_id="sale-b",
            state="active",
            email=new_email,
            minute=5,
        ),
    )
    replay_a = service.process_refund_access(db, late_a_command)
    db.refresh(company)
    db.refresh(client)
    assert restored_b.state == "active"
    assert restored_b.new_entitlement is False
    assert replay_a.status == "stale"
    assert replay_a.state == "active"
    assert replay_a.shadowed_by_newer_entitlement is True
    assert company.operational_status == "active"
    assert client.is_active is True

    terminal_b = service.process_refund_access(
        db,
        _command(
            event_id="refund-b-new-email",
            invoice_id="sale-b",
            state="refunded",
            email=new_email,
            minute=6,
        ),
    )
    assert terminal_b.state == "refunded"
    with pytest.raises(
        service.RefundAccessConflict,
        match="refunded_state_is_terminal",
    ):
        service.process_refund_access(
            db,
            _command(
                event_id="paid-b-after-terminal",
                invoice_id="sale-b",
                state="active",
                email=new_email,
                minute=7,
            ),
        )


def test_cross_email_new_invoice_restores_same_internal_account_terminal(db):
    old_email = "aluno-antigo@example.com"
    new_email = "aluno-novo@example.com"
    company, client, user = _seed_account(db, email=old_email)
    service.process_refund_access(
        db,
        _command(
            event_id="refund-a-old-email",
            invoice_id="sale-a",
            state="refunded",
            email=old_email,
            minute=1,
        ),
    )
    client.email = new_email
    db.commit()

    result = service.process_refund_access(
        db,
        _command(
            event_id="paid-b-new-email",
            invoice_id="sale-b",
            state="active",
            email=new_email,
            minute=2,
        ),
    )

    for entity in (company, client, user):
        db.refresh(entity)
    assert result.state == "active"
    assert result.new_entitlement is True
    assert result.supersedes_prior_terminal is True
    assert company.operational_status == "active"
    assert company.waha_enabled is False
    assert client.is_active is True
    assert user.is_active is True


def test_cross_email_entitlement_must_be_strictly_newer_than_old_terminal(db):
    old_email = "aluno-antigo@example.com"
    new_email = "aluno-novo@example.com"
    company, client, _ = _seed_account(db, email=old_email)
    service.process_refund_access(
        db,
        _command(
            event_id="paid-a-old-email",
            invoice_id="sale-a",
            state="active",
            email=old_email,
            minute=0,
        ),
    )
    client.email = new_email
    db.commit()
    service.process_refund_access(
        db,
        _command(
            event_id="paid-b-new-email",
            invoice_id="sale-b",
            state="active",
            email=new_email,
            minute=2,
        ),
    )

    result = service.process_refund_access(
        db,
        _command(
            event_id="refund-a-same-time",
            invoice_id="sale-a",
            state="refunded",
            email=old_email,
            minute=2,
        ),
    )

    db.refresh(company)
    db.refresh(client)
    assert result.state == "refunded"
    assert result.shadowed_by_newer_entitlement is False
    assert company.operational_status == "refunded"
    assert client.is_active is False


def test_cross_email_entitlement_does_not_correlate_distinct_shared_accounts(db):
    old_company, old_client, _ = _seed_account(
        db,
        email="conta-antiga@example.com",
        company_id=10,
    )
    new_company, new_client, _ = _seed_account(
        db,
        email="conta-nova@example.com",
        company_id=20,
    )
    shared_company = Company(
        id=30,
        name="Workspace compartilhado",
        cnpj=f"{30:014d}",
        business_type_id=1,
        operational_status="active",
        waha_enabled=True,
    )
    db.add_all(
        [
            shared_company,
            ClientCompany(client_id=old_client.id, company_id=shared_company.id),
            ClientCompany(client_id=new_client.id, company_id=shared_company.id),
        ]
    )
    db.commit()
    service.process_refund_access(
        db,
        _command(
            event_id="paid-old-account",
            invoice_id="sale-a",
            state="active",
            email=old_client.email,
            minute=0,
        ),
    )
    service.process_refund_access(
        db,
        _command(
            event_id="paid-new-account",
            invoice_id="sale-b",
            state="active",
            email=new_client.email,
            minute=3,
        ),
    )

    result = service.process_refund_access(
        db,
        _command(
            event_id="refund-old-account",
            invoice_id="sale-a",
            state="refunded",
            email=old_client.email,
            minute=2,
        ),
    )

    for entity in (
        old_company,
        old_client,
        new_company,
        new_client,
        shared_company,
    ):
        db.refresh(entity)
    assert result.state == "refunded"
    assert result.shadowed_by_newer_entitlement is False
    assert result.excluded_shared_company_ids == (shared_company.id,)
    assert old_company.operational_status == "refunded"
    assert old_client.is_active is False
    assert new_company.operational_status == "active"
    assert new_client.is_active is True
    assert shared_company.operational_status == "active"


@pytest.mark.parametrize("refund_minute", [2, 3])
def test_late_terminal_at_same_or_newer_time_reblocks_prior_entitlement(
    db,
    refund_minute,
):
    company, client, _ = _seed_account(db)
    paid = service.process_refund_access(
        db,
        _command(event_id="paid-b", invoice_id="sale-b", state="active", minute=2),
    )

    result = service.process_refund_access(
        db,
        _command(
            event_id=f"refund-a-{refund_minute}",
            invoice_id="sale-a",
            state="refunded",
            minute=refund_minute,
        ),
    )

    db.refresh(company)
    db.refresh(client)
    assert paid.new_entitlement is True
    assert result.state == "refunded"
    assert result.shadowed_by_newer_entitlement is False
    assert company.operational_status == "refunded"
    assert client.is_active is False
    assert is_email_refund_blocked(db, "aluno@example.com") is True


def test_new_invoice_never_supersedes_pending_refund(db):
    company, client, _ = _seed_account(db)
    service.process_refund_access(
        db,
        _command(event_id="wait-a", invoice_id="sale-a", state="refund_pending", minute=0),
    )

    result = service.process_refund_access(
        db,
        _command(event_id="paid-b", invoice_id="sale-b", state="active", minute=1),
    )

    db.refresh(company)
    db.refresh(client)
    assert result.state == "refund_pending"
    assert result.supersedes_prior_terminal is False
    assert company.operational_status == "refund_pending"
    assert client.is_active is False


@pytest.mark.parametrize("minute", [0, 1])
def test_new_invoice_must_be_strictly_newer_than_terminal(db, minute):
    company, client, _ = _seed_account(db)
    service.process_refund_access(
        db,
        _command(event_id="refund-a", invoice_id="sale-a", state="refunded", minute=1),
    )

    result = service.process_refund_access(
        db,
        _command(event_id=f"paid-b-{minute}", invoice_id="sale-b", state="active", minute=minute),
    )

    db.refresh(company)
    db.refresh(client)
    assert result.state == "refunded"
    assert result.supersedes_prior_terminal is False
    assert company.operational_status == "refunded"
    assert client.is_active is False


def test_completed_active_with_effective_block_is_not_entitlement_watermark(db):
    _seed_account(db)
    service.process_refund_access(
        db,
        _command(event_id="refund-a", invoice_id="sale-a", state="refunded", minute=0),
    )
    db.add(
        RefundAccessEvent(
            event_id="paid-ineffective",
            idempotency_key="idem-paid-ineffective",
            source="eduzz",
            invoice_id="sale-b",
            email_hash=service._email_hash("aluno@example.com"),
            requested_state="active",
            occurred_at=datetime(2026, 7, 19, 12, 1, tzinfo=timezone.utc),
            status="completed",
            response_payload={
                "status": "processed",
                "state": "refunded",
                "supersedesPriorTerminal": True,
            },
        )
    )
    db.commit()

    assert is_email_refund_blocked(db, "aluno@example.com") is True


def test_terminal_repair_after_repurchase_does_not_reblock_or_move_watermark(db):
    company, client, _ = _seed_account(db)
    service.process_refund_access(
        db,
        _command(event_id="refund-a", invoice_id="sale-a", state="refunded", minute=0),
    )
    service.process_refund_access(
        db,
        _command(event_id="paid-b", invoice_id="sale-b", state="active", minute=1),
    )

    repair = service.process_refund_access(
        db,
        _command(event_id="refund-a-repair", invoice_id="sale-a", state="refunded", minute=2),
    )

    db.refresh(company)
    db.refresh(client)
    terminal = db.query(RefundAccessSuspension).filter_by(invoice_id="sale-a").one()
    assert repair.status == "stale"
    assert repair.state == "active"
    assert service._aware_utc(terminal.latest_occurred_at) == datetime(
        2026, 7, 19, 12, 0, tzinfo=timezone.utc
    )
    assert company.operational_status == "active"
    assert client.is_active is True


def test_repurchase_local_failure_stays_retryable_and_then_converges(db, monkeypatch):
    company, client, _ = _seed_account(db)
    service.process_refund_access(
        db,
        _command(event_id="refund-a", invoice_id="sale-a", state="refunded", minute=0),
    )
    original_restore = service._restore_local_entities
    calls = {"count": 0}

    def fail_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise service.RefundAccessRemoteError("local_restore_failed")
        return original_restore(*args, **kwargs)

    monkeypatch.setattr(service, "_restore_local_entities", fail_once)
    repurchase = _command(
        event_id="paid-b",
        invoice_id="sale-b",
        state="active",
        minute=1,
    )
    with pytest.raises(service.RefundAccessRemoteError):
        service.process_refund_access(db, repurchase)

    failed = db.query(RefundAccessEvent).filter_by(event_id="paid-b").one()
    db.refresh(company)
    db.refresh(client)
    assert failed.status == "failed"
    assert company.operational_status == "refunded"
    assert client.is_active is False
    assert is_email_refund_blocked(db, "aluno@example.com") is True

    retry = service.process_refund_access(db, repurchase)
    db.refresh(failed)
    db.refresh(company)
    db.refresh(client)
    assert retry.state == "active"
    assert failed.status == "completed"
    assert failed.response_payload["state"] == "active"
    assert company.operational_status == "active"
    assert client.is_active is True
    assert calls["count"] == 2


def test_repurchase_recovers_missing_baseline_without_credentials_or_waha(db):
    company, client, user = _seed_account(db)
    service.process_refund_access(
        db,
        _command(event_id="refund-a", invoice_id="sale-a", state="refunded", minute=0),
    )
    db.query(RefundAccessEntityState).delete(synchronize_session=False)
    db.commit()

    result = service.process_refund_access(
        db,
        _command(event_id="paid-b", invoice_id="sale-b", state="active", minute=1),
    )

    for entity in (company, client, user):
        db.refresh(entity)
    assert result.state == "active"
    assert company.operational_status == "active"
    assert company.waha_enabled is False
    assert client.is_active is True
    assert client.api_key is None
    assert user.is_active is True


def test_historical_scope_blocks_after_master_email_changes(db):
    company, client, user = _seed_account(db)
    service.process_refund_access(
        db,
        _command(event_id="wait-a", invoice_id="sale-a", state="refund_pending", minute=0),
    )
    service.process_refund_access(
        db,
        _command(event_id="paid-a", invoice_id="sale-a", state="active", minute=1),
    )
    client.email = "alterado@example.com"
    db.commit()

    result = service.process_refund_access(
        db,
        _command(event_id="wait-a-again", invoice_id="sale-a", state="refund_pending", minute=2),
    )

    for entity in (company, client, user):
        db.refresh(entity)
    assert result.state == "refund_pending"
    assert company.operational_status == "refund_pending"
    assert client.is_active is False
    assert user.is_active is False


def test_historical_scope_restores_pending_after_master_email_changes(db):
    company, client, user = _seed_account(db)
    service.process_refund_access(
        db,
        _command(event_id="wait-a", invoice_id="sale-a", state="refund_pending", minute=0),
    )
    client.email = "alterado@example.com"
    db.commit()

    result = service.process_refund_access(
        db,
        _command(event_id="paid-a", invoice_id="sale-a", state="active", minute=1),
    )

    for entity in (company, client, user):
        db.refresh(entity)
    assert result.state == "active"
    assert company.operational_status == "active"
    assert client.is_active is True
    assert user.is_active is True


def test_historical_invoice_scope_wins_when_old_email_is_reused(db):
    old_email = "titular-antigo@example.com"
    new_email = "titular-novo@example.com"
    original_company, original_client, original_user = _seed_account(
        db,
        email=old_email,
        company_id=10,
    )
    service.process_refund_access(
        db,
        _command(
            event_id="paid-original-invoice",
            invoice_id="sale-original",
            state="active",
            email=old_email,
            minute=0,
        ),
    )
    original_client.email = new_email
    db.commit()
    replacement_company, replacement_client, replacement_user = _seed_account(
        db,
        email=old_email,
        company_id=20,
    )

    result = service.process_refund_access(
        db,
        _command(
            event_id="refund-original-after-email-reuse",
            invoice_id="sale-original",
            state="refunded",
            email=old_email,
            minute=1,
        ),
    )

    for entity in (
        original_company,
        original_client,
        original_user,
        replacement_company,
        replacement_client,
        replacement_user,
    ):
        db.refresh(entity)
    assert result.status == "processed"
    assert result.state == "refunded"
    assert result.company_ids == (original_company.id,)
    assert result.client_ids == (original_client.id,)
    assert original_company.operational_status == "refunded"
    assert original_client.is_active is False
    assert original_user.is_active is False
    assert replacement_company.operational_status == "active"
    assert replacement_client.is_active is True
    assert replacement_user.is_active is True


def test_bound_invoice_uses_current_root_graph_after_email_changes(db):
    old_email = "grafo-antigo@example.com"
    new_email = "grafo-novo@example.com"
    root_company, root_client, _ = _seed_account(
        db,
        email=old_email,
        company_id=10,
    )
    service.process_refund_access(
        db,
        _command(
            event_id="paid-before-current-graph-expands",
            invoice_id="sale-current-graph",
            state="active",
            email=old_email,
            minute=0,
        ),
    )
    root_client.email = new_email
    later_workspace = Company(
        id=20,
        name="Workspace criado depois",
        cnpj=f"{20:014d}",
        business_type_id=1,
        operational_status="active",
        waha_enabled=True,
    )
    db.add_all(
        [
            later_workspace,
            ClientCompany(
                client_id=root_client.id,
                company_id=later_workspace.id,
            ),
        ]
    )
    db.commit()

    result = service.process_refund_access(
        db,
        _command(
            event_id="refund-after-current-graph-expands",
            invoice_id="sale-current-graph",
            state="refunded",
            email=old_email,
            minute=1,
        ),
    )

    db.refresh(root_company)
    db.refresh(root_client)
    db.refresh(later_workspace)
    assert result.status == "processed"
    assert result.state == "refunded"
    assert result.company_ids == (root_company.id, later_workspace.id)
    assert root_company.operational_status == "refunded"
    assert later_workspace.operational_status == "refunded"
    assert root_client.is_active is False


def test_refunded_is_terminal_and_later_waiting_is_stale(db):
    company, client, _ = _seed_account(db)
    service.process_refund_access(
        db,
        _command(event_id="refund-1", invoice_id="sale-1", state="refunded", minute=1),
    )
    result = service.process_refund_access(
        db,
        _command(event_id="wait-late", invoice_id="sale-1", state="refund_pending", minute=2),
    )
    db.refresh(company)
    db.refresh(client)
    assert result.status == "stale"
    assert result.state == "refunded"
    assert company.operational_status == "refunded"
    assert client.is_active is False


def test_not_found_creates_tombstone_and_replay_blocks_later_account(db):
    command = _command(event_id="wait-1", invoice_id="sale-1", state="refund_pending")
    first = service.process_refund_access(db, command)
    assert first.status == "not_found"
    assert db.query(RefundAccessSuspension).filter_by(state="refund_pending").count() == 1

    with pytest.raises(HTTPException) as exc:
        ensure_registration_eligibility("aluno@example.com", db)
    assert exc.value.status_code == 403

    company, client, _ = _seed_account(db)
    replay = service.process_refund_access(db, command)
    db.refresh(company)
    db.refresh(client)
    assert replay.status == "processed"
    assert company.operational_status == "refund_pending"
    assert client.is_active is False


def test_tombstone_restore_reports_other_open_invoice_without_account(db):
    service.process_refund_access(
        db,
        _command(
            event_id="wait-tombstone-a",
            invoice_id="sale-tombstone-a",
            state="refund_pending",
            minute=0,
        ),
    )
    service.process_refund_access(
        db,
        _command(
            event_id="wait-tombstone-b",
            invoice_id="sale-tombstone-b",
            state="refund_pending",
            minute=1,
        ),
    )
    paid_a = _command(
        event_id="paid-tombstone-a",
        invoice_id="sale-tombstone-a",
        state="active",
        minute=2,
    )

    result = service.process_refund_access(db, paid_a)
    duplicate = service.process_refund_access(db, paid_a)

    assert result.status == "processed"
    assert result.state == "refund_pending"
    assert duplicate.status == "duplicate"
    assert duplicate.state == "refund_pending"


def test_scoped_restore_keeps_account_blocked_by_other_invoice_tombstone(db):
    service.process_refund_access(
        db,
        _command(
            event_id="wait-unbound-b",
            invoice_id="sale-unbound-b",
            state="refund_pending",
            minute=0,
        ),
    )
    company, client, user = _seed_account(db)
    service.process_refund_access(
        db,
        _command(
            event_id="wait-bound-a",
            invoice_id="sale-bound-a",
            state="refund_pending",
            minute=1,
        ),
    )

    first_restore = service.process_refund_access(
        db,
        _command(
            event_id="paid-bound-a",
            invoice_id="sale-bound-a",
            state="active",
            minute=2,
        ),
    )
    for entity in (company, client, user):
        db.refresh(entity)

    assert first_restore.state == "refund_pending"
    assert company.operational_status == "refund_pending"
    assert company.waha_enabled is False
    assert client.is_active is False
    assert user.is_active is False
    assert db.query(RefundAccessEntityState).count() > 0

    final_restore = service.process_refund_access(
        db,
        _command(
            event_id="paid-unbound-b",
            invoice_id="sale-unbound-b",
            state="active",
            minute=3,
        ),
    )
    for entity in (company, client, user):
        db.refresh(entity)

    assert final_restore.state == "active"
    assert company.operational_status == "active"
    assert company.waha_enabled is True
    assert client.is_active is True
    assert user.is_active is True
    assert db.query(RefundAccessEntityState).count() == 0


def test_old_not_found_replay_cannot_reblock_after_newer_active_event(db):
    old_wait = _command(
        event_id="wait-old",
        invoice_id="sale-1",
        state="refund_pending",
        minute=0,
    )
    assert service.process_refund_access(db, old_wait).status == "not_found"
    assert (
        service.process_refund_access(
            db,
            _command(
                event_id="paid-new",
                invoice_id="sale-1",
                state="active",
                minute=1,
            ),
        ).status
        == "processed"
    )

    company, client, _ = _seed_account(db)
    replay = service.process_refund_access(db, old_wait)
    db.refresh(company)
    db.refresh(client)

    assert replay.status == "stale"
    assert replay.state == "active"
    assert company.operational_status == "active"
    assert client.is_active is True


def test_active_without_previous_suspension_is_an_ordering_barrier(db):
    active = service.process_refund_access(
        db,
        _command(
            event_id="paid-first",
            invoice_id="sale-active-first",
            state="active",
            minute=2,
        ),
    )
    stale_waiting = service.process_refund_access(
        db,
        _command(
            event_id="wait-old",
            invoice_id="sale-active-first",
            state="refund_pending",
            minute=1,
        ),
    )

    suspension = db.query(RefundAccessSuspension).filter_by(
        invoice_id="sale-active-first"
    ).one()
    assert active.status == "processed"
    assert active.state == "active"
    assert stale_waiting.status == "stale"
    assert stale_waiting.state == "active"
    assert suspension.state == "active"
    assert suspension.latest_event_id == "paid-first"


def test_refunded_is_terminal_even_when_observed_after_newer_active_event(db):
    company, client, _ = _seed_account(db)
    service.process_refund_access(
        db,
        _command(
            event_id="paid-newer",
            invoice_id="sale-terminal-order",
            state="active",
            minute=2,
        ),
    )
    refunded = service.process_refund_access(
        db,
        _command(
            event_id="refund-observed-late",
            invoice_id="sale-terminal-order",
            state="refunded",
            minute=1,
        ),
    )

    db.refresh(company)
    db.refresh(client)
    suspension = db.query(RefundAccessSuspension).filter_by(
        invoice_id="sale-terminal-order"
    ).one()
    assert refunded.status == "processed"
    assert refunded.state == "refunded"
    assert suspension.state == "refunded"
    assert service._aware_utc(suspension.latest_occurred_at) == datetime(
        2026, 7, 19, 12, 2, tzinfo=timezone.utc
    )
    assert company.operational_status == "refunded"
    assert client.is_active is False

    with pytest.raises(service.RefundAccessConflict):
        service.process_refund_access(
            db,
            _command(
                event_id="paid-after-terminal",
                invoice_id="sale-terminal-order",
                state="active",
                minute=3,
            ),
        )


def test_replayed_completed_event_returns_effective_current_state(db):
    company, client, _ = _seed_account(db)
    waiting = _command(
        event_id="wait-replay",
        invoice_id="sale-replay",
        state="refund_pending",
        minute=0,
    )
    service.process_refund_access(db, waiting)
    service.process_refund_access(
        db,
        _command(
            event_id="paid-later",
            invoice_id="sale-replay",
            state="active",
            minute=1,
        ),
    )

    replay = service.process_refund_access(db, waiting)
    db.refresh(company)
    db.refresh(client)
    assert replay.status == "duplicate"
    assert replay.state == "active"
    assert company.operational_status == "active"
    assert client.is_active is True


def test_shared_managed_workspace_is_excluded_without_leaving_root_active(db):
    root_company, root_client, _ = _seed_account(db)
    shared_company = Company(
        id=20,
        name="Workspace compartilhado",
        cnpj="00000000000020",
        business_type_id=1,
        operational_status="active",
        waha_enabled=True,
    )
    external_owner = Company(
        id=30,
        name="Owner externo",
        cnpj="00000000000030",
        business_type_id=1,
        operational_status="active",
        waha_enabled=True,
    )
    shared_client = Client(
        id=20,
        email="shared@example.com",
        password="hash",
        company_id=shared_company.id,
        api_key="shared-key",
        is_active=True,
    )
    db.add_all(
        [
            shared_company,
            external_owner,
            shared_client,
            ClientCompany(client_id=shared_client.id, company_id=shared_company.id),
            CustomerManagedCompany(
                owner_company_id=root_company.id,
                customer_id=101,
                managed_company_id=shared_company.id,
                created_by_client_id=root_client.id,
                trial_days=0,
                lifecycle_status="active",
            ),
            CustomerManagedCompany(
                owner_company_id=external_owner.id,
                customer_id=102,
                managed_company_id=shared_company.id,
                trial_days=0,
                lifecycle_status="active",
            ),
        ]
    )
    db.commit()

    result = service.process_refund_access(
        db,
        _command(event_id="wait-shared", invoice_id="sale-shared", state="refund_pending"),
    )
    for entity in (root_company, root_client, shared_company, shared_client, external_owner):
        db.refresh(entity)

    assert result.status == "processed"
    assert result.excluded_shared_company_ids == (shared_company.id,)
    assert root_client.id in result.client_ids
    assert shared_client.id not in result.client_ids
    assert root_company.operational_status == "refund_pending"
    assert root_client.is_active is False
    assert shared_company.operational_status == "active"
    assert shared_client.is_active is True
    assert external_owner.operational_status == "active"


def test_diamond_descendant_with_direct_root_path_remains_blocked(db):
    root_company, root_client, _ = _seed_account(db)
    shared_company = Company(
        id=20,
        name="Shared branch",
        cnpj="00000000000020",
        business_type_id=1,
        operational_status="active",
        waha_enabled=True,
    )
    external_owner = Company(
        id=30,
        name="External owner",
        cnpj="00000000000030",
        business_type_id=1,
        operational_status="active",
        waha_enabled=True,
    )
    direct_descendant = Company(
        id=40,
        name="Direct descendant",
        cnpj="00000000000040",
        business_type_id=1,
        operational_status="active",
        waha_enabled=True,
    )
    db.add_all(
        [
            shared_company,
            external_owner,
            direct_descendant,
            CustomerManagedCompany(
                owner_company_id=root_company.id,
                customer_id=201,
                managed_company_id=shared_company.id,
                created_by_client_id=root_client.id,
                trial_days=0,
                lifecycle_status="active",
            ),
            CustomerManagedCompany(
                owner_company_id=external_owner.id,
                customer_id=202,
                managed_company_id=shared_company.id,
                trial_days=0,
                lifecycle_status="active",
            ),
            CustomerManagedCompany(
                owner_company_id=shared_company.id,
                customer_id=203,
                managed_company_id=direct_descendant.id,
                trial_days=0,
                lifecycle_status="active",
            ),
            CustomerManagedCompany(
                owner_company_id=root_company.id,
                customer_id=204,
                managed_company_id=direct_descendant.id,
                created_by_client_id=root_client.id,
                trial_days=0,
                lifecycle_status="active",
            ),
        ]
    )
    db.commit()

    result = service.process_refund_access(
        db,
        _command(event_id="wait-diamond", invoice_id="sale-diamond", state="refund_pending"),
    )
    db.refresh(shared_company)
    db.refresh(direct_descendant)

    assert result.excluded_shared_company_ids == (shared_company.id,)
    assert shared_company.operational_status == "active"
    assert direct_descendant.operational_status == "refund_pending"


def test_exclusive_client_company_workspace_is_included_without_customer_link(db):
    _, root_client, _ = _seed_account(db)
    admin_workspace = Company(
        id=20,
        name="Admin workspace",
        cnpj="00000000000020",
        business_type_id=1,
        operational_status="active",
        waha_enabled=True,
    )
    db.add_all(
        [
            admin_workspace,
            ClientCompany(client_id=root_client.id, company_id=admin_workspace.id),
        ]
    )
    db.commit()

    result = service.process_refund_access(
        db,
        _command(
            event_id="wait-direct-exclusive",
            invoice_id="sale-direct-exclusive",
            state="refund_pending",
        ),
    )
    db.refresh(admin_workspace)

    assert admin_workspace.id in result.company_ids
    assert admin_workspace.operational_status == "refund_pending"


def test_customer_managed_workspace_with_creator_access_remains_in_scope(db):
    root_company, root_client, _ = _seed_account(db)
    managed_company = Company(
        id=20,
        name="Customer managed",
        cnpj="00000000000020",
        business_type_id=1,
        operational_status="active",
        waha_enabled=True,
    )
    customer_client = Client(
        id=20,
        email="customer@example.com",
        password="hash",
        company_id=managed_company.id,
        is_active=True,
    )
    db.add_all(
        [
            managed_company,
            customer_client,
            ClientCompany(client_id=customer_client.id, company_id=managed_company.id),
            ClientCompany(client_id=root_client.id, company_id=managed_company.id),
            CustomerManagedCompany(
                owner_company_id=root_company.id,
                customer_id=301,
                managed_company_id=managed_company.id,
                created_by_client_id=root_client.id,
                trial_days=0,
                lifecycle_status="active",
            ),
        ]
    )
    db.commit()

    result = service.process_refund_access(
        db,
        _command(
            event_id="wait-managed-real-shape",
            invoice_id="sale-managed-real-shape",
            state="refund_pending",
        ),
    )
    db.refresh(managed_company)
    db.refresh(customer_client)

    assert managed_company.id in result.company_ids
    assert managed_company.id not in result.excluded_shared_company_ids
    assert managed_company.operational_status == "refund_pending"
    assert customer_client.is_active is False


def test_shared_client_company_workspace_is_not_captured(db):
    _, root_client, _ = _seed_account(db)
    shared_workspace = Company(
        id=20,
        name="Third-party workspace",
        cnpj="00000000000020",
        business_type_id=1,
        operational_status="active",
        waha_enabled=True,
    )
    external_company = Company(
        id=30,
        name="External company",
        cnpj="00000000000030",
        business_type_id=1,
        operational_status="active",
        waha_enabled=True,
    )
    external_client = Client(
        id=30,
        email="external@example.com",
        password="hash",
        company_id=external_company.id,
        is_active=True,
    )
    db.add_all(
        [
            shared_workspace,
            external_company,
            external_client,
            ClientCompany(client_id=root_client.id, company_id=shared_workspace.id),
            ClientCompany(client_id=external_client.id, company_id=external_company.id),
            ClientCompany(client_id=external_client.id, company_id=shared_workspace.id),
        ]
    )
    db.commit()

    result = service.process_refund_access(
        db,
        _command(
            event_id="wait-direct-shared",
            invoice_id="sale-direct-shared",
            state="refund_pending",
        ),
    )
    db.refresh(shared_workspace)
    db.refresh(external_client)

    assert result.excluded_shared_company_ids == (shared_workspace.id,)
    assert shared_workspace.operational_status == "active"
    assert external_client.is_active is True


def test_selected_shared_workspace_does_not_change_refund_ownership_scope(db):
    root_company, root_client, _ = _seed_account(db)
    shared_workspace = Company(
        id=20,
        name="Shared selected context",
        cnpj="00000000000020",
        business_type_id=1,
        operational_status="active",
        waha_enabled=True,
    )
    external_company = Company(
        id=30,
        name="External root",
        cnpj="00000000000030",
        business_type_id=1,
        operational_status="active",
        waha_enabled=True,
    )
    managed_workspace = Company(
        id=40,
        name="Exclusive managed workspace",
        cnpj="00000000000040",
        business_type_id=1,
        operational_status="active",
        waha_enabled=True,
    )
    external_client = Client(
        id=30,
        email="external-selected@example.com",
        password="hash",
        company_id=shared_workspace.id,
        ownership_company_id=external_company.id,
        is_active=True,
    )
    managed_client = Client(
        id=40,
        email="managed@example.com",
        password="hash",
        company_id=managed_workspace.id,
        ownership_company_id=managed_workspace.id,
        is_active=True,
    )
    root_client.company_id = shared_workspace.id
    db.add_all(
        [
            shared_workspace,
            external_company,
            managed_workspace,
            external_client,
            managed_client,
            ClientCompany(client_id=root_client.id, company_id=shared_workspace.id),
            ClientCompany(client_id=root_client.id, company_id=managed_workspace.id),
            ClientCompany(client_id=external_client.id, company_id=external_company.id),
            ClientCompany(client_id=external_client.id, company_id=shared_workspace.id),
            ClientCompany(client_id=managed_client.id, company_id=managed_workspace.id),
            CustomerManagedCompany(
                owner_company_id=root_company.id,
                customer_id=401,
                managed_company_id=managed_workspace.id,
                created_by_client_id=root_client.id,
                trial_days=0,
                lifecycle_status="active",
            ),
        ]
    )
    db.commit()

    result = service.process_refund_access(
        db,
        _command(
            event_id="wait-selected-shared",
            invoice_id="sale-selected-shared",
            state="refund_pending",
        ),
    )
    for entity in (
        root_company,
        root_client,
        shared_workspace,
        external_company,
        external_client,
        managed_workspace,
        managed_client,
    ):
        db.refresh(entity)

    assert set(result.company_ids) == {root_company.id, managed_workspace.id}
    assert result.excluded_shared_company_ids == (shared_workspace.id,)
    assert root_company.operational_status == "refund_pending"
    assert root_client.is_active is False
    assert managed_workspace.operational_status == "refund_pending"
    assert managed_client.is_active is False
    assert shared_workspace.operational_status == "active"
    assert external_company.operational_status == "active"
    assert external_client.is_active is True


def test_selected_exclusive_workspace_keeps_original_root_in_scope(db):
    root_company, root_client, _ = _seed_account(db)
    exclusive_workspace = Company(
        id=20,
        name="Exclusive selected context",
        cnpj="00000000000020",
        business_type_id=1,
        operational_status="active",
        waha_enabled=True,
    )
    db.add_all(
        [
            exclusive_workspace,
            ClientCompany(client_id=root_client.id, company_id=exclusive_workspace.id),
        ]
    )
    root_client.company_id = exclusive_workspace.id
    db.commit()

    result = service.process_refund_access(
        db,
        _command(
            event_id="wait-selected-exclusive",
            invoice_id="sale-selected-exclusive",
            state="refund_pending",
        ),
    )
    db.refresh(root_company)
    db.refresh(exclusive_workspace)

    assert set(result.company_ids) == {root_company.id, exclusive_workspace.id}
    assert root_company.operational_status == "refund_pending"
    assert exclusive_workspace.operational_status == "refund_pending"


def test_scope_entity_lock_keys_have_stable_global_order():
    scope = service.AccountScope(
        root_client_id=4,
        company_ids=(12, 2),
        client_ids=(9, 3),
        user_ids=(18, 1),
    )

    assert service._scope_entity_lock_keys(scope) == [
        "refund-access:entity:company:2",
        "refund-access:entity:company:12",
        "refund-access:entity:client:3",
        "refund-access:entity:client:9",
        "refund-access:entity:user:1",
        "refund-access:entity:user:18",
    ]


def test_command_lock_keys_include_historical_restore_targets(db):
    company, client, user = _seed_account(db)
    command = _command(
        event_id="wait-lock-history",
        invoice_id="sale-lock-history",
        state="refund_pending",
    )
    service.process_refund_access(db, command)

    assert service._command_entity_lock_keys(db, command, None) == [
        f"refund-access:entity:company:{company.id}",
        f"refund-access:entity:client:{client.id}",
        f"refund-access:entity:user:{user.id}",
    ]


def test_staff_creation_rechecks_company_after_refund_scope_lock(db):
    company, client, _ = _seed_account(db)
    company.operational_status = "refund_pending"
    db.commit()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            users_routes.create_user(
                users_routes.UserCreate(
                    email="new-staff@example.com",
                    name="New Staff",
                    role="staff",
                    company_id=company.id,
                    password="secret-123",
                    confirm_password="secret-123",
                ),
                db=db,
                current_user=client,
            )
        )

    assert exc.value.status_code == 423
    assert db.query(User).filter(User.email == "new-staff@example.com").count() == 0


def test_staff_creation_rejects_refund_tombstone_for_new_email(db):
    company, client, _ = _seed_account(db)
    blocked_email = "new-staff@example.com"
    db.add(
        RefundAccessSuspension(
            source="eduzz",
            invoice_id="staff-refund",
            email_hash=service._email_hash(blocked_email),
            state="refund_pending",
            latest_event_id="wait-staff",
            latest_occurred_at=datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc),
        )
    )
    db.commit()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            users_routes.create_user(
                users_routes.UserCreate(
                    email=blocked_email,
                    name="New Staff",
                    role="staff",
                    company_id=company.id,
                    password="secret-123",
                    confirm_password="secret-123",
                ),
                db=db,
                current_user=client,
            )
        )

    assert exc.value.status_code == 423
    assert db.query(User).filter(User.email == blocked_email).count() == 0


def test_staff_auth_is_blocked_by_master_refund_tombstone_even_before_row_update(db):
    company, client, user = _seed_account(db)
    db.add(
        RefundAccessSuspension(
            source="eduzz",
            invoice_id="master-tombstone",
            email_hash=service._email_hash(client.email),
            state="refund_pending",
            latest_event_id="wait-master",
            latest_occurred_at=datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc),
        )
    )
    db.commit()
    token = auth.create_access_token(
        {
            "sub": user.email,
            "user_id": str(user.id),
            "client_id": str(client.id),
            "company_id": str(company.id),
            "user_type": "user",
            "tv": 0,
        }
    )

    with pytest.raises(HTTPException):
        auth.get_current_user(token=token, db=db)


def test_registration_post_commit_effects_skip_when_refund_wins_entity_fence(
    db,
    monkeypatch,
):
    company, client, _ = _seed_account(db)

    def refund_wins(_db, **_kwargs):
        company.operational_status = "refund_pending"
        client.is_active = False
        _db.flush()

    monkeypatch.setattr(
        registration_eligibility_service,
        "lock_refund_entities_for_mutation",
        refund_wins,
    )
    monkeypatch.setattr(
        registration_eligibility_service.PipelineService,
        "create_minimal_pipeline_for_company",
        lambda *_args, **_kwargs: pytest.fail(
            "Pipeline não deve ser criado depois do bloqueio"
        ),
    )
    monkeypatch.setattr(
        registration_eligibility_service,
        "send_master_welcome_email",
        lambda *_args, **_kwargs: pytest.fail(
            "Email não deve ser enviado depois do bloqueio"
        ),
    )

    result = (
        registration_eligibility_service.run_registration_post_commit_effects(
            db,
            client_id=client.id,
            company_id=company.id,
            email=client.email,
            company_name=company.name,
            billing_profile={},
        )
    )

    assert result["skipped"] == "refund_blocked"
    assert result["pipeline_created"] is False
    assert result["welcome_email_sent"] is False


def test_registration_post_commit_effects_run_after_locked_revalidation(
    db,
    monkeypatch,
):
    company, client, _ = _seed_account(db)
    calls = []

    monkeypatch.setattr(
        registration_eligibility_service.PipelineService,
        "create_minimal_pipeline_for_company",
        lambda company_id, _db: calls.append(("pipeline", company_id)),
    )
    monkeypatch.setattr(
        registration_eligibility_service,
        "send_master_welcome_email",
        lambda welcome_client, *, company_name: (
            calls.append(("email", welcome_client.id, company_name))
            or SimpleNamespace(sent=True, skipped=False, reason=None)
        ),
    )

    result = (
        registration_eligibility_service.run_registration_post_commit_effects(
            db,
            client_id=client.id,
            company_id=company.id,
            email=client.email,
            company_name=company.name,
            billing_profile={},
        )
    )

    assert result["skipped"] is None
    assert result["pipeline_created"] is True
    assert result["welcome_email_sent"] is True
    assert calls == [
        ("pipeline", company.id),
        ("email", client.id, company.name),
    ]


def test_registration_post_commit_effects_skip_when_identity_lock_is_busy(
    db,
    monkeypatch,
):
    company, client, _ = _seed_account(db)

    class BusyIdentityLock:
        def __enter__(self):
            raise registration_eligibility_service.RefundIdentityOperationBusyError(
                "external_identity"
            )

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        registration_eligibility_service,
        "refund_identity_operation_lock",
        lambda *_args, **_kwargs: BusyIdentityLock(),
    )
    monkeypatch.setattr(
        registration_eligibility_service.PipelineService,
        "create_minimal_pipeline_for_company",
        lambda *_args, **_kwargs: pytest.fail(
            "Pipeline não deve rodar com lock ocupado"
        ),
    )
    monkeypatch.setattr(
        registration_eligibility_service,
        "send_master_welcome_email",
        lambda *_args, **_kwargs: pytest.fail(
            "Email não deve sair com lock ocupado"
        ),
    )

    result = (
        registration_eligibility_service.run_registration_post_commit_effects(
            db,
            client_id=client.id,
            company_id=company.id,
            email=client.email,
            company_name=company.name,
            billing_profile={},
        )
    )

    assert result["skipped"] == "refund_lock_busy"
    assert result["pipeline_created"] is False
    assert result["welcome_email_sent"] is False


def test_websocket_old_master_token_cannot_authenticate_recreated_email(db):
    company, client, _ = _seed_account(db)
    old_token = auth.create_tokens_for_user(client)["access_token"]
    authenticated = asyncio.run(auth.get_current_user_ws(old_token, db))
    assert authenticated["id"] == str(client.id)

    db.query(Client).filter(Client.id == client.id).delete(synchronize_session=False)
    db.flush()
    replacement = Client(
        id=999,
        email=client.email,
        password="new-hash",
        company_id=company.id,
        is_active=True,
        auth_token_version=0,
    )
    db.add_all(
        [
            replacement,
            ClientCompany(client_id=replacement.id, company_id=company.id),
        ]
    )
    db.commit()
    db.expire_all()

    with pytest.raises(auth.WebSocketAuthError) as exc:
        asyncio.run(auth.get_current_user_ws(old_token, db))
    assert exc.value.code == 4001


def test_websocket_legacy_master_token_derives_company_after_identity_validation(db):
    company, client, _ = _seed_account(db)
    legacy_token = auth.create_access_token(
        {
            "sub": client.email,
            "user_id": str(client.id),
            "client_id": str(client.id),
            "user_type": "master",
            "tv": 0,
        }
    )

    authenticated = asyncio.run(auth.get_current_user_ws(legacy_token, db))

    assert authenticated["id"] == str(client.id)
    assert authenticated["client_id"] == str(client.id)
    assert authenticated["company_id"] == str(company.id)


def test_websocket_old_staff_token_cannot_authenticate_recreated_email(db):
    company, client, user = _seed_account(db)
    old_token = auth.create_tokens_for_user(user)["access_token"]
    authenticated = asyncio.run(auth.get_current_user_ws(old_token, db))
    assert authenticated["id"] == str(user.id)

    db.query(User).filter(User.id == user.id).delete(synchronize_session=False)
    db.flush()
    replacement = User(
        id=999,
        client_id=client.id,
        company_id=company.id,
        email=user.email,
        password="new-hash",
        name="Replacement",
        is_active=True,
        auth_token_version=0,
    )
    db.add(replacement)
    db.commit()
    db.expire_all()

    with pytest.raises(auth.WebSocketAuthError) as exc:
        asyncio.run(auth.get_current_user_ws(old_token, db))
    assert exc.value.code == 4001


def _seed_customer_managed_link_context(db):
    owner, client, _ = _seed_account(db)
    managed = Company(
        id=20,
        name="Managed",
        cnpj="00000000000020",
        business_type_id=1,
        operational_status="active",
        waha_enabled=True,
    )
    contact = Contact(
        id=501,
        client_id=client.id,
        company_id=owner.id,
        phone="5500000000007",
        name="Customer",
    )
    customer = Customer(
        id=501,
        contact_id=contact.id,
        company_id=owner.id,
        nome="Customer",
        telefone=contact.phone,
        status="ativo",
        categoria="cliente",
    )
    db.add_all(
        [
            managed,
            ClientCompany(client_id=client.id, company_id=managed.id),
            contact,
            customer,
        ]
    )
    db.commit()
    return owner, managed, client, customer


def test_managed_company_link_rechecks_refund_state_after_entity_lock(db, monkeypatch):
    owner, managed, client, customer = _seed_customer_managed_link_context(db)

    def refund_wins_lock(_db, **_kwargs):
        owner.operational_status = "refund_pending"
        _db.flush()

    monkeypatch.setattr(
        customer_management_routes,
        "lock_refund_entities_for_mutation",
        refund_wins_lock,
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            customer_management_routes.link_customer_managed_company(
                client_id=client.id,
                company_id=owner.id,
                customer_id=customer.id,
                payload=customer_management_routes.ManagedCompanyLinkCreate(
                    managed_company_id=managed.id
                ),
                db=db,
                _=client,
            )
        )

    assert exc.value.status_code == 423
    assert db.query(CustomerManagedCompany).count() == 0


def test_managed_company_unlink_rechecks_refund_state_after_entity_lock(db, monkeypatch):
    owner, managed, client, customer = _seed_customer_managed_link_context(db)
    link = CustomerManagedCompany(
        owner_company_id=owner.id,
        customer_id=customer.id,
        managed_company_id=managed.id,
        created_by_client_id=client.id,
        trial_days=0,
        lifecycle_status="active",
    )
    db.add(link)
    db.commit()

    def refund_wins_lock(_db, **_kwargs):
        managed.operational_status = "refund_pending"
        _db.flush()

    monkeypatch.setattr(
        customer_management_routes,
        "lock_refund_entities_for_mutation",
        refund_wins_lock,
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            customer_management_routes.unlink_customer_managed_company(
                client_id=client.id,
                company_id=owner.id,
                customer_id=customer.id,
                link_id=link.id,
                db=db,
                _=client,
            )
        )

    assert exc.value.status_code == 423
    assert db.query(CustomerManagedCompany).filter_by(id=link.id).count() == 1


def test_waha_failure_keeps_local_block_and_same_event_can_retry(db, monkeypatch):
    company, client, _ = _seed_account(db)
    calls = {"count": 0}

    def fail_once(db, suspension, state):
        calls["count"] += 1
        if calls["count"] == 1:
            raise service.RefundAccessRemoteError(
                "waha_down",
                company_ids=[company.id],
            )

    monkeypatch.setattr(service, "_run_waha_block_actions", fail_once)
    command = _command(event_id="wait-1", invoice_id="sale-1", state="refund_pending")
    with pytest.raises(service.RefundAccessRemoteError):
        service.process_refund_access(db, command)

    db.refresh(company)
    db.refresh(client)
    assert company.operational_status == "refund_pending"
    assert company.waha_enabled is False
    assert client.is_active is False
    assert db.query(RefundAccessEvent).filter_by(event_id="wait-1").one().status == "failed"

    retry = service.process_refund_access(db, command)
    assert retry.status == "processed"
    assert calls["count"] == 2


@pytest.mark.parametrize(
    ("refund_state", "expected_action"),
    [
        ("refund_pending", "stop"),
        ("refunded", "delete"),
    ],
)
def test_failed_whatsapp_reset_preserves_session_for_refund_cleanup(
    db,
    monkeypatch,
    refund_state,
    expected_action,
):
    company, client, _ = _seed_account(db)
    original_session = str(company.waha_session_name)
    monkeypatch.setattr(
        whatsapp_provider.WhatsAppConfig,
        "from_company",
        classmethod(
            lambda cls, company_id, db=None: WhatsAppConfig(
                "waha",
                session_name=original_session,
                base_url="http://waha.local",
                api_key="test-key",
            )
        ),
    )

    class _FailingWAHAClient:
        def delete_session(self, session_name, logout):
            assert session_name == original_session
            assert logout is True
            raise WAHAException("upstream timeout")

    monkeypatch.setattr(
        "backend.integrations.waha_sdk.get_client",
        lambda **_kwargs: _FailingWAHAClient(),
    )

    with pytest.raises(HTTPException) as reset_error:
        webhook.reset_whatsapp_config(user=client, db=db)
    assert reset_error.value.status_code == 503

    db.refresh(company)
    assert company.waha_session_name == original_session
    cleanup_actions = []

    class _RefundWAHAClient:
        timeout = 60

        def logout_session(self, session_name):
            assert session_name == original_session

        def stop_session(self, session_name):
            cleanup_actions.append(("stop", session_name))

        def delete_session(self, session_name, logout):
            assert logout is False
            cleanup_actions.append(("delete", session_name))

    monkeypatch.setattr(
        service,
        "get_waha_client",
        lambda **_kwargs: _RefundWAHAClient(),
    )
    monkeypatch.setattr(
        service,
        "_run_waha_block_actions",
        _REAL_RUN_WAHA_BLOCK_ACTIONS,
    )
    result = service.process_refund_access(
        db,
        _command(
            event_id=f"{refund_state}-after-reset",
            invoice_id=f"sale-{refund_state}",
            state=refund_state,
        ),
    )

    assert result.status == "processed"
    assert cleanup_actions == [(expected_action, original_session)]


def test_refund_delete_shares_one_deadline_between_logout_and_delete(monkeypatch):
    calls = []

    class _Client:
        timeout = 60

        def logout_session(self, session_name):
            calls.append(("logout", session_name, self.timeout))

        def delete_session(self, session_name, logout):
            calls.append(("delete", session_name, logout, self.timeout))

    client = _Client()
    clock = iter((1.0, 5.5))
    monkeypatch.setattr(service.time, "monotonic", lambda: next(clock))

    service._delete_waha_session_with_deadline(client, "company_10", 6.0)

    assert calls == [
        ("logout", "company_10", 2.0),
        ("delete", "company_10", False, 0.5),
    ]


def test_refund_waha_budget_stops_new_remote_request(monkeypatch):
    client = SimpleNamespace(timeout=60)
    monkeypatch.setattr(service.time, "monotonic", lambda: 10.0)

    with pytest.raises(service._RefundAccessWahaBudgetExceeded):
        service._apply_remaining_waha_timeout(client, 9.0)

    assert client.timeout == 60


def test_failed_old_event_cannot_override_newer_active_transition(db, monkeypatch):
    company, client, _ = _seed_account(db)

    def always_fail(db, suspension, state):
        raise service.RefundAccessRemoteError("waha_down", company_ids=[company.id])

    monkeypatch.setattr(service, "_run_waha_block_actions", always_fail)
    old_wait = _command(event_id="wait-old", invoice_id="sale-1", state="refund_pending", minute=0)
    with pytest.raises(service.RefundAccessRemoteError):
        service.process_refund_access(db, old_wait)

    monkeypatch.setattr(service, "_run_waha_block_actions", lambda db, suspension, state: None)
    service.process_refund_access(
        db,
        _command(event_id="paid-new", invoice_id="sale-1", state="active", minute=1),
    )
    retry = service.process_refund_access(db, old_wait)
    db.refresh(company)
    db.refresh(client)
    assert retry.status == "stale"
    assert company.operational_status == "active"
    assert client.is_active is True
