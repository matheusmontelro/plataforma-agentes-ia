import asyncio
import os
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")

from backend.models import Client
from backend.routes import contacts_import, customer_management_routes, users, webhook
from backend.services.company_access_control import (
    CompanyOperationalLockBusyError,
    IdentityOperationReservation,
)


class _Query:
    def __init__(self, result):
        self.result = result

    def filter(self, *_args):
        return self

    def first(self):
        return self.result


class _DB:
    def __init__(self, result=None):
        self.result = result
        self.commit_calls = 0
        self.rollback_calls = 0

    def query(self, _model):
        return _Query(self.result)

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1


def _lock_timeout_error() -> OperationalError:
    original = RuntimeError("database details must stay internal")
    original.pgcode = "55P03"
    return OperationalError(
        "SELECT * FROM private_table WHERE token=:token",
        {"token": "secret-value"},
        original,
    )


@pytest.fixture(params=["company_busy", "lock_timeout"])
def transient_contention(request):
    if request.param == "company_busy":
        return CompanyOperationalLockBusyError(3)
    return _lock_timeout_error()


def test_change_password_preserves_transient_contention(
    monkeypatch,
    transient_contention,
):
    master = Client(id=7, email="owner@example.com", company_id=3, is_active=True)
    target = SimpleNamespace(
        id=11,
        client_id=7,
        company_id=3,
        email="staff@example.com",
    )
    db = _DB(target)
    monkeypatch.setattr(users, "_account_identity_locks", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(
        users,
        "_revalidate_internal_user_mutation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(transient_contention),
    )

    with pytest.raises(type(transient_contention)) as exc:
        asyncio.run(
            users._change_user_password_with_identity_reservation(
                user_id=11,
                password_data={
                    "new_password": "new-password",
                    "confirm_password": "new-password",
                },
                db=db,
                current_user=master,
                reservation=IdentityOperationReservation(
                    _guard=None,
                    _active=False,
                ),
            )
        )

    assert exc.value is transient_contention
    assert db.rollback_calls == 2


def test_delete_contact_preserves_transient_contention(
    monkeypatch,
    transient_contention,
):
    contact = SimpleNamespace(
        id=9,
        phone="5500000000007",
        company_id=3,
        name="Contato",
    )
    actor = Client(id=7, email="owner@example.com", company_id=3, is_active=True)
    db = _DB(contact)
    monkeypatch.setattr(
        contacts_import,
        "lock_entities_for_mutation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(transient_contention),
    )

    with pytest.raises(type(transient_contention)) as exc:
        asyncio.run(
            contacts_import.delete_contact(
                contact_id=9,
                user=actor,
                db=db,
            )
        )

    assert exc.value is transient_contention
    assert db.rollback_calls == 1


def test_waha_pairing_preserves_transient_contention(
    monkeypatch,
    transient_contention,
):
    db = _DB()
    monkeypatch.setattr(
        webhook,
        "_lock_operational_whatsapp_company",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(transient_contention),
    )

    with pytest.raises(type(transient_contention)) as exc:
        webhook.request_waha_pairing_code(
            request=webhook.WAHAPairingCodeRequest(
                phone_number="5500000000007",
            ),
            user=SimpleNamespace(company_id=3),
            db=db,
        )

    assert exc.value is transient_contention
    assert db.rollback_calls == 2


@pytest.mark.parametrize(
    "operation",
    [
        webhook.connect_waha,
        webhook.start_waha_session,
    ],
)
def test_waha_session_mutation_preserves_transient_contention(
    monkeypatch,
    transient_contention,
    operation,
):
    db = _DB()
    monkeypatch.setattr(
        webhook,
        "_lock_operational_whatsapp_company",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(transient_contention),
    )

    with pytest.raises(type(transient_contention)) as exc:
        operation(
            user=SimpleNamespace(
                company_id=3,
                email="owner@example.com",
            ),
            db=db,
        )

    assert exc.value is transient_contention
    assert db.rollback_calls == 2


def test_customer_delete_preserves_transient_contention(
    monkeypatch,
    transient_contention,
):
    db = _DB()
    customer = SimpleNamespace(
        id=9,
        dados_adicionais={},
    )
    lock_calls = 0

    def lock_scope(*_args, **_kwargs):
        nonlocal lock_calls
        lock_calls += 1
        raise transient_contention

    monkeypatch.setattr(
        customer_management_routes,
        "_lock_customer_delete_scope",
        lock_scope,
    )
    monkeypatch.setattr(
        customer_management_routes,
        "_load_deletable_customer_financial_records",
        lambda *_args, **_kwargs: ([], []),
    )
    with pytest.raises(type(transient_contention)) as exc:
        asyncio.run(
            customer_management_routes.delete_customer(
                client_id=7,
                company_id=3,
                customer_id=9,
                db=db,
                _=Client(id=7),
            )
        )

    assert exc.value is transient_contention
    assert lock_calls == 1
    assert db.commit_calls == 0
    assert db.rollback_calls == 1
