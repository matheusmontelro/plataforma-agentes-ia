from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.services import eduzz_registration_service as service
from backend.services.eduzz_checkout_service import EduzzAPIError, EduzzConfigurationError


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body


def _set_registration_env(monkeypatch):
    monkeypatch.setenv("EDUZZ_ACCESS_TOKEN", "token")
    monkeypatch.setenv("EDUZZ_REGISTRATION_PRODUCT_IDS", "111, 222")
    monkeypatch.setenv("EDUZZ_REGISTRATION_LOOKBACK_DAYS", "30")
    monkeypatch.setenv("EDUZZ_API_TIMEOUT_SECONDS", "7")


def test_verify_registration_purchase_accepts_paid_sale(monkeypatch):
    _set_registration_env(monkeypatch)
    calls = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        if kwargs["params"]["productId"] == "111":
            return FakeResponse(body={"totalItems": 0, "items": []})
        return FakeResponse(body={"totalItems": 1, "items": [{"id": "sale-1", "status": "paid"}]})

    monkeypatch.setattr(service.requests, "get", fake_get)

    result = service.verify_registration_purchase(
        "BUYER@EXAMPLE.COM",
        now=datetime(2026, 5, 15, tzinfo=timezone.utc),
    )

    assert result.allowed is True
    assert result.product_id == "222"
    assert result.sale_id == "sale-1"
    assert calls[0]["headers"]["Authorization"] == "Bearer token"
    assert calls[0]["params"]["buyerEmail"] == "buyer@example.com"
    assert calls[0]["params"]["itemsPerPage"] == 5
    assert calls[0]["params"]["startDate"] == "2026-04-15"
    assert calls[0]["params"]["endDate"] == "2026-05-15"
    assert calls[0]["params"]["status"] == "paid"
    assert calls[0]["params"]["referenceDate"] == "paidAt"
    assert calls[0]["timeout"] == 7


def test_verify_registration_purchase_blocks_when_no_paid_sale(monkeypatch):
    _set_registration_env(monkeypatch)
    monkeypatch.setattr(service.requests, "get", lambda *args, **kwargs: FakeResponse(body={"totalItems": 0, "items": []}))

    result = service.verify_registration_purchase("buyer@example.com")

    assert result.allowed is False


def test_verify_registration_purchase_requires_product_ids(monkeypatch):
    monkeypatch.setenv("EDUZZ_ACCESS_TOKEN", "token")
    monkeypatch.delenv("EDUZZ_REGISTRATION_PRODUCT_IDS", raising=False)

    with pytest.raises(EduzzConfigurationError):
        service.verify_registration_purchase("buyer@example.com")


def test_verify_registration_purchase_raises_api_error(monkeypatch):
    _set_registration_env(monkeypatch)
    monkeypatch.setattr(service.requests, "get", lambda *args, **kwargs: FakeResponse(status_code=401, body={}))

    with pytest.raises(EduzzAPIError) as exc:
        service.verify_registration_purchase("buyer@example.com")

    assert exc.value.status_code == 401
