import os
import hashlib
import hmac
from decimal import Decimal
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/agentive_eduzz_payments_routes_test.db")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("EDUZZ_ACCESS_TOKEN", "token")
os.environ.setdefault("EDUZZ_AI_CREDIT_PRODUCT_ID", "3027605")
os.environ.setdefault("EDUZZ_WEBHOOK_SECRET", "secret")

from backend.models import AICreditPurchase, AICreditWallet, Client
from backend.routes import eduzz_payments_routes as routes


router = routes.router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/payments")
    return TestClient(app)


def test_eduzz_delivery_get_returns_validation_payload():
    response = _client().get("/payments/eduzz/delivery")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "provider": "eduzz",
        "delivery": True,
        "method": "GET",
    }


def test_eduzz_delivery_post_returns_200_without_crediting():
    response = _client().post("/payments/eduzz/delivery", json={"event": "validation"})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["method"] == "POST"


def test_eduzz_delivery_head_returns_200_without_body():
    response = _client().head("/payments/eduzz/delivery")

    assert response.status_code == 200
    assert response.content == b""


def test_eduzz_webhook_rejects_invalid_signature():
    response = _client().post(
        "/payments/eduzz/webhook",
        json={"event": "myeduzz.invoice_paid"},
        headers={"x-signature": "invalid"},
    )

    assert response.status_code == 401


def test_eduzz_webhook_valid_signature_without_order_is_ignored():
    raw_body = b'{"event":"myeduzz.invoice_paid","data":{"id":"invoice-1"}}'
    signature = hmac.new(b"secret", raw_body, hashlib.sha256).hexdigest()

    response = _client().post(
        "/payments/eduzz/webhook",
        content=raw_body,
        headers={"x-signature": signature, "content-type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json()["reason"] == "missing_order_id"


class FakeQuery:
    def __init__(self, client):
        self.client = client

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.client


class FakeDB:
    def __init__(self, client):
        self.client = client

    def query(self, model):
        assert model is Client
        return FakeQuery(self.client)


def test_send_ai_credit_purchase_email_best_effort_targets_master_billing_email(monkeypatch):
    purchase = AICreditPurchase(
        order_id="aic-3-essential-test",
        company_id=3,
        package_name="Essencial",
        credits=Decimal("50000"),
        price_cents=9700,
        currency="BRL",
        purchase_metadata={"actor_email": "operator@example.com"},
    )
    wallet = AICreditWallet(company_id=3, balance_credits=Decimal("75000"))
    client = Client(
        id=1,
        company_id=3,
        email="owner@example.com",
        billing_profile={"email": "finance@example.com", "full_name": "Finance Owner"},
    )
    sent_payload = {}

    def fake_send(**kwargs):
        sent_payload.update(kwargs)
        return SimpleNamespace(sent=True, skipped=False, reason=None, message_id="msg-1")

    monkeypatch.setattr(routes, "send_ai_credit_purchase_email", fake_send)

    result = routes._send_ai_credit_purchase_email_best_effort(
        db=FakeDB(client),
        purchase=purchase,
        wallet=wallet,
    )

    assert result == {"sent": True, "skipped": False, "reason": None, "message_id": "msg-1"}
    assert sent_payload["to_email"] == "finance@example.com"
    assert sent_payload["to_name"] == "Finance Owner"
    assert sent_payload["package_name"] == "Essencial"
    assert sent_payload["credits"] == "50000"
    assert sent_payload["price"] == "R$ 97,00"
    assert sent_payload["balance_after"] == "75000"
