import asyncio
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-with-at-least-32-chars")

from backend import webhook_stripe
from backend.models import Client, ClientCompany, Company, RefundAccessSuspension, User


class FakeQuery:
    def __init__(self, items):
        self.items = list(items)

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None

    def all(self):
        return list(self.items)


class FakeDB:
    def __init__(self, *, refund_blocked=False):
        self.clients = []
        self.users = []
        self.companies = []
        self.links = []
        self.refund_blocked = refund_blocked
        self.commits = []
        self.rollbacks = 0

    def query(self, model):
        if model is Client:
            return FakeQuery(self.clients)
        if model is User:
            return FakeQuery(self.users)
        if model is RefundAccessSuspension.id:
            return FakeQuery([1] if self.refund_blocked else [])
        raise AssertionError(f"Modelo inesperado no teste: {model}")

    def add(self, obj):
        if isinstance(obj, Company):
            obj.id = obj.id or (100 + len(self.companies))
            self.companies.append(obj)
            return
        if isinstance(obj, Client):
            obj.id = obj.id or (200 + len(self.clients))
            self.clients.append(obj)
            return
        if isinstance(obj, ClientCompany):
            obj.id = obj.id or (300 + len(self.links))
            self.links.append(obj)
            return
        raise AssertionError(f"Objeto inesperado no teste: {obj}")

    def flush(self):
        return None

    def commit(self):
        self.commits.append(
            (len(self.companies), len(self.clients), len(self.links))
        )

    def refresh(self, obj):
        return None

    def rollback(self):
        self.rollbacks += 1


class FakeRequest:
    headers = {"stripe-signature": "signed"}

    async def body(self):
        return b"payload"


def _paid_event():
    return {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test",
                "payment_status": "paid",
                "customer_details": {"email": "buyer@example.com"},
                "custom_fields": [
                    {"key": "cnpj", "text": {"value": "12345678000199"}},
                    {"key": "razaosocial", "text": {"value": "Buyer Ltda"}},
                ],
            }
        },
    }


def test_stripe_provisions_company_client_and_link_in_one_commit(monkeypatch):
    monkeypatch.setattr(
        webhook_stripe.stripe.Webhook,
        "construct_event",
        lambda **kwargs: _paid_event(),
    )
    monkeypatch.setattr(webhook_stripe, "hash_password", lambda value: "hashed")
    db = FakeDB()

    result = asyncio.run(webhook_stripe.stripe_webhook(FakeRequest(), db=db))

    assert result["status"] == "success"
    assert db.commits == [(1, 1, 1)]
    assert db.clients[0].company_id == db.companies[0].id
    assert db.links[0].client_id == db.clients[0].id
    assert db.links[0].company_id == db.companies[0].id


def test_stripe_refund_tombstone_prevents_provisioning(monkeypatch):
    monkeypatch.setattr(
        webhook_stripe.stripe.Webhook,
        "construct_event",
        lambda **kwargs: _paid_event(),
    )
    db = FakeDB(refund_blocked=True)

    result = asyncio.run(webhook_stripe.stripe_webhook(FakeRequest(), db=db))

    assert result == {"status": "ignored", "reason": "access_suspended"}
    assert db.commits == []
    assert db.clients == []
    assert db.companies == []
    assert db.links == []


def test_stripe_rejects_email_already_owned_by_internal_user(monkeypatch):
    monkeypatch.setattr(
        webhook_stripe.stripe.Webhook,
        "construct_event",
        lambda **kwargs: _paid_event(),
    )
    db = FakeDB()
    db.users.append(User(id=7, email="buyer@example.com"))

    result = asyncio.run(webhook_stripe.stripe_webhook(FakeRequest(), db=db))

    assert result == {"status": "ignored", "reason": "email_in_use_by_user"}
    assert db.commits == []
    assert db.clients == []
    assert db.companies == []
