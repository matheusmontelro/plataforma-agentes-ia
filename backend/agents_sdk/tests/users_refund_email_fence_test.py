import asyncio
import hashlib
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ENVIRONMENT", "development")

from backend.db import Base
from backend.models import (
    BusinessType,
    Client,
    ClientCompany,
    Company,
    RefundAccessEvent,
    RefundAccessSuspension,
    Team,
    User,
)
from backend.routes import users as users_routes


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(type_, compiler, **kwargs):
    return "JSON"


@compiles(BigInteger, "sqlite")
def _compile_bigint_for_sqlite(type_, compiler, **kwargs):
    return "INTEGER"


CORE_TABLES = [
    BusinessType.__table__,
    Company.__table__,
    Client.__table__,
    ClientCompany.__table__,
    Team.__table__,
    User.__table__,
    RefundAccessSuspension.__table__,
    RefundAccessEvent.__table__,
]


@pytest.fixture()
def staff_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=CORE_TABLES)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    company = Company(
        id=71,
        name="Conta principal",
        cnpj="00000000000071",
        business_type_id=1,
        operational_status="active",
    )
    master = Client(
        id=72,
        email="owner@example.com",
        password="master-hash",
        company_id=company.id,
        ownership_company_id=company.id,
        is_active=True,
    )
    user = User(
        id=73,
        client_id=master.id,
        company_id=company.id,
        email="existing-staff@example.com",
        password="old-hash",
        name="Existing Staff",
        role="staff",
        is_active=True,
    )
    db.add_all(
        [
            BusinessType(id=1, name="Empresa", code="business_company"),
            company,
            master,
            ClientCompany(client_id=master.id, company_id=company.id),
            user,
        ]
    )
    db.commit()
    try:
        yield db, company, master, user
    finally:
        db.close()
        engine.dispose()


def _new_user_payload(email: str) -> users_routes.UserCreate:
    password = "A" * 12
    return users_routes.UserCreate(
        email=email,
        name="New Staff",
        role="staff",
        company_id=71,
        password=password,
        confirm_password=password,
    )


def test_staff_welcome_sends_after_locked_post_commit_revalidation(
    staff_db,
    monkeypatch,
):
    db, _company, master, _existing_user = staff_db
    provider_calls = []
    monkeypatch.setattr(
        users_routes,
        "send_internal_user_welcome_email",
        lambda *_args, **_kwargs: (
            provider_calls.append(True)
            or SimpleNamespace(sent=True, skipped=False, reason=None)
        ),
    )

    created = asyncio.run(
        users_routes.create_user(
            _new_user_payload("new-staff@example.com"),
            db=db,
            current_user=master,
        )
    )

    assert created.id is not None
    assert provider_calls == [True]
    assert db.query(User).filter_by(email="new-staff@example.com").count() == 1


def test_staff_creation_refund_first_blocks_commit_and_email(
    staff_db,
    monkeypatch,
):
    db, _company, master, _existing_user = staff_db
    blocked_email = "blocked-staff@example.com"
    db.add(
        RefundAccessSuspension(
            source="eduzz",
            invoice_id="staff-refund-first",
            email_hash=hashlib.sha256(blocked_email.encode()).hexdigest(),
            state="refund_pending",
            latest_event_id="staff-refund-first-event",
            latest_occurred_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    monkeypatch.setattr(
        users_routes,
        "send_internal_user_welcome_email",
        lambda *_args, **_kwargs: pytest.fail("provider must not be called"),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            users_routes.create_user(
                _new_user_payload(blocked_email),
                db=db,
                current_user=master,
            )
        )

    assert exc.value.status_code == 423
    assert db.query(User).filter_by(email=blocked_email).count() == 0


def test_staff_creation_commit_survives_refund_before_email(
    staff_db,
    monkeypatch,
):
    db, company, master, _existing_user = staff_db
    new_email = "race-staff@example.com"

    @contextmanager
    def refund_wins_before_email(_db, _emails, *, reservation):
        assert reservation is not None
        company.operational_status = "refund_pending"
        master.is_active = False
        for staff_user in db.query(User).all():
            staff_user.is_active = False
        db.commit()
        yield

    monkeypatch.setattr(
        users_routes,
        "_refund_identity_locks",
        refund_wins_before_email,
    )
    monkeypatch.setattr(
        users_routes,
        "send_internal_user_welcome_email",
        lambda *_args, **_kwargs: pytest.fail("provider must not be called"),
    )

    asyncio.run(
        users_routes.create_user(
            _new_user_payload(new_email),
            db=db,
            current_user=master,
        )
    )

    assert db.query(User).filter_by(email=new_email).count() == 1


def test_staff_creation_busy_after_commit_never_sends(
    staff_db,
    monkeypatch,
):
    db, _company, master, _existing_user = staff_db
    provider_calls = []

    @contextmanager
    def busy_identity_fence(_db, _emails, *, reservation):
        assert reservation is not None
        raise users_routes.RefundIdentityOperationBusyError("test_busy")
        yield

    monkeypatch.setattr(users_routes, "_refund_identity_locks", busy_identity_fence)
    monkeypatch.setattr(
        users_routes,
        "send_internal_user_welcome_email",
        lambda *_args, **_kwargs: provider_calls.append(True),
    )
    asyncio.run(
        users_routes.create_user(
            _new_user_payload("busy-staff@example.com"),
            db=db,
            current_user=master,
        )
    )

    assert db.query(User).filter_by(email="busy-staff@example.com").count() == 1
    assert provider_calls == []


def test_staff_creation_db_failure_after_commit_never_sends(
    staff_db,
    monkeypatch,
):
    db, _company, master, _existing_user = staff_db
    provider_calls = []
    monkeypatch.setattr(
        users_routes,
        "_revalidate_internal_user_email_delivery",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("database unavailable")
        ),
    )
    monkeypatch.setattr(
        users_routes,
        "send_internal_user_welcome_email",
        lambda *_args, **_kwargs: provider_calls.append(True),
    )

    asyncio.run(
        users_routes.create_user(
            _new_user_payload("db-failure-staff@example.com"),
            db=db,
            current_user=master,
        )
    )

    assert (
        db.query(User)
        .filter_by(email="db-failure-staff@example.com")
        .count()
        == 1
    )
    assert provider_calls == []


def test_password_change_sends_only_after_second_revalidation(
    staff_db,
    monkeypatch,
):
    db, _company, master, user = staff_db
    provider_calls = []
    monkeypatch.setattr(
        users_routes,
        "send_internal_user_password_changed_email",
        lambda *_args, **_kwargs: (
            provider_calls.append(True)
            or SimpleNamespace(sent=True, skipped=False, reason=None)
        ),
    )

    old_hash = user.password
    asyncio.run(
        users_routes.change_user_password(
            user.id,
            {"new_password": "B" * 12, "confirm_password": "B" * 12},
            db=db,
            current_user=master,
        )
    )

    assert db.query(User).filter_by(id=user.id).first().password != old_hash
    assert provider_calls == [True]


def test_password_commit_survives_refund_before_email(
    staff_db,
    monkeypatch,
):
    db, company, master, user = staff_db
    original_revalidate = users_routes._revalidate_internal_user_email_delivery
    revalidation_calls = 0

    def refund_wins_on_second_revalidation(*args, **kwargs):
        nonlocal revalidation_calls
        revalidation_calls += 1
        if revalidation_calls == 2:
            company.operational_status = "refund_pending"
            master.is_active = False
            user.is_active = False
            db.commit()
            return None
        return original_revalidate(*args, **kwargs)

    monkeypatch.setattr(
        users_routes,
        "_revalidate_internal_user_email_delivery",
        refund_wins_on_second_revalidation,
    )
    monkeypatch.setattr(
        users_routes,
        "send_internal_user_password_changed_email",
        lambda *_args, **_kwargs: pytest.fail("provider must not be called"),
    )
    old_hash = user.password

    asyncio.run(
        users_routes.change_user_password(
            user.id,
            {"new_password": "C" * 12, "confirm_password": "C" * 12},
            db=db,
            current_user=master,
        )
    )

    assert db.query(User).filter_by(id=user.id).first().password != old_hash
