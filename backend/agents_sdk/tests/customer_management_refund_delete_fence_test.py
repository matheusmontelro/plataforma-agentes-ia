import asyncio
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault(
    "DATABASE_URL",
    "sqlite:////tmp/agentive-customer-refund-delete-fence-test.db",
)
os.environ.setdefault("CLIENT_TOKEN", "test-client-token")

from backend.routes import contacts_import
from backend.routes import leads_routes
from backend.models import Client


class _ResultQuery:
    def __init__(self, result):
        self.result = result

    def filter(self, *_args, **_kwargs):
        return self

    def join(self, *_args, **_kwargs):
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self.result


class _SequencedDB:
    def __init__(self, results):
        self.results = iter(results)
        self.events = []

    def query(self, *_args, **_kwargs):
        return _ResultQuery(next(self.results))

    def execute(self, *_args, **_kwargs):
        raise AssertionError("nenhuma exclusão SQL deve ocorrer após detectar o vínculo")

    def rollback(self):
        self.events.append("rollback")


def test_lead_delete_never_cascades_a_managed_workspace(monkeypatch):
    db = _SequencedDB(
        [
            SimpleNamespace(id=7, is_active=True),
            SimpleNamespace(id=41, phone="5500000000002"),
            SimpleNamespace(id=91),
        ]
    )
    fence_events = []
    monkeypatch.setattr(
        leads_routes,
        "lock_refund_entities_for_mutation",
        lambda _db, **kwargs: fence_events.append(kwargs),
    )
    monkeypatch.setattr(
        leads_routes,
        "ensure_company_operational",
        lambda _db, company_id: fence_events.append({"operational": company_id}),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            leads_routes.deletar_lead(
                client_id=7,
                company_id=11,
                lead_id=41,
                db=db,
                _=SimpleNamespace(id=7),
            )
        )

    assert exc_info.value.status_code == 409
    assert db.events == ["rollback"]
    assert fence_events == [
        {"company_ids": [11], "client_ids": [7]},
        {"operational": 11},
    ]


def test_contact_delete_never_cascades_a_managed_workspace(monkeypatch):
    contact = SimpleNamespace(
        id=51,
        company_id=11,
        phone="5500000000020",
    )
    db = _SequencedDB(
        [
            contact,
            Client(
                id=7,
                email="actor@example.com",
                company_id=11,
                ownership_company_id=11,
                is_active=True,
            ),
            contact,
            SimpleNamespace(id=92),
        ]
    )
    fence_events = []
    monkeypatch.setattr(
        contacts_import,
        "lock_refund_entities_for_mutation",
        lambda _db, **kwargs: fence_events.append(kwargs),
    )
    monkeypatch.setattr(
        contacts_import,
        "ensure_company_operational",
        lambda _db, company_id: fence_events.append({"operational": company_id}),
    )
    monkeypatch.setattr(
        contacts_import,
        "is_account_refund_blocked",
        lambda _db, _actor: False,
    )
    actor = Client(
        id=7,
        email="actor@example.com",
        company_id=11,
        ownership_company_id=11,
        is_active=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            contacts_import.delete_contact(
                contact_id=51,
                user=actor,
                db=db,
            )
        )

    assert exc_info.value.status_code == 409
    assert db.events == ["rollback"]
    assert fence_events == [
        {"company_ids": [11], "client_ids": [7], "user_ids": []},
        {"operational": 11},
    ]


def test_contact_delete_rechecks_actor_after_refund_fence(monkeypatch):
    contact = SimpleNamespace(
        id=51,
        company_id=11,
        phone="5500000000020",
    )
    stale_actor = Client(
        id=7,
        email="actor@example.com",
        company_id=11,
        ownership_company_id=11,
        is_active=True,
    )
    blocked_actor = Client(
        id=7,
        email="actor@example.com",
        company_id=11,
        ownership_company_id=11,
        is_active=False,
    )
    db = _SequencedDB([contact, blocked_actor])
    monkeypatch.setattr(
        contacts_import,
        "lock_refund_entities_for_mutation",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        contacts_import,
        "ensure_company_operational",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        contacts_import,
        "is_account_refund_blocked",
        lambda _db, actor: not actor.is_active,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            contacts_import.delete_contact(
                contact_id=51,
                user=stale_actor,
                db=db,
            )
        )

    assert exc_info.value.status_code == 423
    assert db.events == ["rollback"]
