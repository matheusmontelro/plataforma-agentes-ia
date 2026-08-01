import hashlib
import hmac
from types import SimpleNamespace

import pytest

from backend.services import eduzz_checkout_service as service


@pytest.fixture(autouse=True)
def _public_app_url(monkeypatch):
    monkeypatch.setenv("EDUZZ_PUBLIC_APP_URL", "https://app.example.com")


def test_build_cart_payload_uses_single_eduzz_product_with_package_price(monkeypatch):
    monkeypatch.setenv("EDUZZ_ACCESS_TOKEN", "token")
    monkeypatch.setenv("EDUZZ_AI_CREDIT_PRODUCT_ID", "3027605")
    monkeypatch.setenv("EDUZZ_WEBHOOK_SECRET", "secret")

    payload = service.build_eduzz_cart_payload(
        order_id="aic-7-growth-test",
        package=SimpleNamespace(code="growth", name="Crescimento", credits=150_000, price_cents=24_700, currency="BRL"),
        user=SimpleNamespace(email="owner@example.com", name="Owner"),
        config=service.get_eduzz_checkout_config(),
    )

    assert payload["orderId"] == "aic-7-growth-test"
    assert payload["postbackUrl"] == "https://app.example.com/payments/eduzz/webhook"
    assert payload["returnUrl"] == "https://app.example.com/company/ai-credits"
    assert payload["items"][0]["productId"] == "3027605"
    assert payload["items"][0]["price"] == {"value": 247.0, "currency": "BRL"}
    assert payload["customer"] == {"email": "owner@example.com", "name": "Owner Cliente"}


def test_build_cart_payload_uses_safe_customer_name_when_profile_name_is_invalid(monkeypatch):
    monkeypatch.setenv("EDUZZ_ACCESS_TOKEN", "token")
    monkeypatch.setenv("EDUZZ_AI_CREDIT_PRODUCT_ID", "3027605")
    monkeypatch.setenv("EDUZZ_WEBHOOK_SECRET", "secret")

    payload = service.build_eduzz_cart_payload(
        order_id="aic-7-essential-test",
        package=SimpleNamespace(code="essential", name="Essencial", credits=50_000, price_cents=9_700, currency="BRL"),
        user=SimpleNamespace(email="owner@example.com", name="owner@example.com"),
        config=service.get_eduzz_checkout_config(),
    )

    assert payload["customer"] == {"email": "owner@example.com", "name": "Cliente"}


def test_build_cart_payload_uses_master_billing_profile(monkeypatch):
    monkeypatch.setenv("EDUZZ_ACCESS_TOKEN", "token")
    monkeypatch.setenv("EDUZZ_AI_CREDIT_PRODUCT_ID", "3027605")
    monkeypatch.setenv("EDUZZ_WEBHOOK_SECRET", "secret")

    payload = service.build_eduzz_cart_payload(
        order_id="aic-7-essential-test",
        package=SimpleNamespace(code="essential", name="Essencial", credits=50_000, price_cents=9_700, currency="BRL"),
        user=SimpleNamespace(email="owner@example.com", name="owner@example.com"),
        config=service.get_eduzz_checkout_config(),
        billing_profile={
            "full_name": "Cliente Exemplo",
            "email": "financeiro@example.com",
            "cellphone": "11988887777",
            "document": "12345678909",
            "postal_code": "18044390",
            "street": "Av. Sorocaba",
            "number": "500",
            "neighborhood": "Centro",
            "complement": "Sala 1",
            "state": "SP",
        },
    )

    assert payload["customer"] == {
        "email": "financeiro@example.com",
        "name": "Cliente Exemplo",
        "cellphone": "11988887777",
        "document": "12345678909",
        "address": {
            "street": "Av. Sorocaba",
            "number": "500",
            "neighborhood": "Centro",
            "complement": "Sala 1",
            "postalCode": "18044390",
            "state": "SP",
        },
    }


def test_create_cart_appends_order_tracking_to_payment_url(monkeypatch):
    monkeypatch.setenv("EDUZZ_ACCESS_TOKEN", "token")
    monkeypatch.setenv("EDUZZ_AI_CREDIT_PRODUCT_ID", "3027605")
    monkeypatch.setenv("EDUZZ_WEBHOOK_SECRET", "secret")

    class FakeResponse:
        status_code = 201

        def json(self):
            return {"id": "cart-1", "key": "key-1", "paymentUrl": "https://sun.eduzz.com/c_abc?contentId=123"}

    def fake_post(*args, **kwargs):
        assert kwargs["json"]["orderId"] == "aic-7-essential-test"
        return FakeResponse()

    monkeypatch.setattr(service.requests, "post", fake_post)

    result = service.create_ai_credit_cart(
        order_id="aic-7-essential-test",
        package=SimpleNamespace(code="essential", name="Essencial", credits=50_000, price_cents=9_700, currency="BRL"),
        user=SimpleNamespace(email="owner@example.com"),
    )

    assert result.payment_url.startswith("https://sun.eduzz.com/c_abc?")
    assert "utm_content=aic-7-essential-test" in result.payment_url
    assert result.eduzz_cart_id == "cart-1"


def test_verify_signature_accepts_hmac_sha256(monkeypatch):
    monkeypatch.setenv("EDUZZ_ACCESS_TOKEN", "token")
    monkeypatch.setenv("EDUZZ_AI_CREDIT_PRODUCT_ID", "3027605")
    monkeypatch.setenv("EDUZZ_WEBHOOK_SECRET", "secret")
    raw_body = b'{"event":"myeduzz.invoice_paid"}'
    signature = hmac.new(b"secret", raw_body, hashlib.sha256).hexdigest()

    assert service.verify_eduzz_signature(raw_body=raw_body, signature=signature) is True
    assert service.verify_eduzz_signature(raw_body=raw_body, signature=f"sha256={signature}") is True
    assert service.verify_eduzz_signature(raw_body=raw_body, signature="invalid") is False


def test_extract_order_id_from_invoice_tracking_payload():
    payload = {
        "event": "myeduzz.invoice_paid",
        "data": {
            "utm": {"utmContent": "aic-7-growth-test"},
            "items": [{"productId": "3027605", "price": {"value": 247.0}}],
            "paid": {"value": 247.0},
        },
    }

    assert service.extract_eduzz_order_id(payload) == "aic-7-growth-test"
    assert service.validate_paid_invoice_for_purchase(
        payload=payload,
        expected_product_id="3027605",
        expected_price_cents=24_700,
    ) == (True, "ok")
