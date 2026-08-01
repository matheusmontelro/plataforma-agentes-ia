import os
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/agentive_ai_credits_routes_test.db")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from backend.routes import ai_credits_routes


class FakeDB:
    def __init__(self):
        self.added = []
        self.flushed = 0
        self.committed = 0
        self.rolled_back = 0

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        self.flushed += 1
        for index, obj in enumerate(self.added, start=1):
            if getattr(obj, "id", None) is None:
                obj.id = index

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = len(self.added)


def test_packages_response_is_retired(monkeypatch):
    user = SimpleNamespace(company_id=7)
    monkeypatch.delenv("AI_CREDIT_ENABLE_MANUAL_PACKAGE_PURCHASE", raising=False)
    monkeypatch.delenv("EDUZZ_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("EDUZZ_AI_CREDIT_PRODUCT_ID", raising=False)
    monkeypatch.delenv("EDUZZ_WEBHOOK_SECRET", raising=False)

    response = ai_credits_routes.get_ai_credit_packages(user=user)

    assert response.packages == []
    assert response.checkout_available is False
    assert response.manual_purchase_available is False

    monkeypatch.setenv("AI_CREDIT_ENABLE_MANUAL_PACKAGE_PURCHASE", "true")

    response = ai_credits_routes.get_ai_credit_packages(user=user)

    assert response.packages == []
    assert response.manual_purchase_available is False


def test_packages_response_ignores_legacy_checkout_configuration(monkeypatch):
    user = SimpleNamespace(company_id=7)
    monkeypatch.setenv("EDUZZ_ACCESS_TOKEN", "token")
    monkeypatch.setenv("EDUZZ_AI_CREDIT_PRODUCT_ID", "3027605")
    monkeypatch.setenv("EDUZZ_WEBHOOK_SECRET", "secret")

    response = ai_credits_routes.get_ai_credit_packages(user=user)

    assert response.packages == []
    assert response.checkout_available is False


def test_checkout_package_returns_gone():
    db = FakeDB()

    with pytest.raises(HTTPException) as exc:
        ai_credits_routes.create_ai_credit_package_checkout(
            package_code="growth",
            db=db,
            user=SimpleNamespace(company_id=7, id=5, email="owner@example.com"),
        )

    assert exc.value.status_code == 410
    assert db.added == []


def test_grant_manual_package_credits_adds_wallet_credit(monkeypatch):
    wallet = SimpleNamespace(
        id=11,
        balance_credits=Decimal("10.000000"),
        total_granted_credits=Decimal("20.000000"),
    )
    package = ai_credits_routes.AICreditPackage(
        code="essential",
        name="Essencial",
        credits=50_000,
        price_cents=9_700,
        description="Teste",
    )
    monkeypatch.setattr(
        ai_credits_routes,
        "_get_or_create_wallet",
        lambda db, company_id: wallet,
    )
    db = FakeDB()

    _, transaction = ai_credits_routes._grant_manual_package_credits(
        db=db,
        company_id=7,
        package=package,
        user=SimpleNamespace(id=5, email="owner@example.com"),
    )

    assert wallet.balance_credits == Decimal("50010.000000")
    assert wallet.total_granted_credits == Decimal("50020.000000")
    assert transaction.transaction_type == "credit"
    assert transaction.amount_credits == Decimal("50000.000000")
    assert transaction.balance_after == Decimal("50010.000000")
    assert transaction.transaction_metadata["source"] == "manual_no_checkout_purchase"
    assert transaction.transaction_metadata["package_code"] == "essential"
    assert db.flushed == 1


def test_purchase_manual_package_returns_gone():
    with pytest.raises(HTTPException) as exc:
        ai_credits_routes.purchase_ai_credit_package(
            package_code="essential",
            db=FakeDB(),
            user=SimpleNamespace(company_id=7),
        )

    assert exc.value.status_code == 410


def test_transaction_item_uses_financial_metadata_fallback():
    transaction = SimpleNamespace(
        id=31,
        transaction_type="debit",
        amount_credits=Decimal("3.000000"),
        balance_after=Decimal("7.000000"),
        description="openai:llm_response",
        created_at=datetime(2026, 5, 13, tzinfo=timezone.utc),
        usage_event=None,
        transaction_metadata={
            "provider": "openai",
            "operation": "llm_response",
            "status": "success",
            "model": "gpt-5.4-mini",
            "estimated_cost_brl": "0.01250000",
            "revenue_brl": "0.03000000",
            "gross_profit_brl": "0.01750000",
            "margin_percent": "58.3333",
            "pricing_status": "priced",
        },
    )

    item = ai_credits_routes._build_transaction_item(transaction)

    assert item.usage is not None
    assert item.usage.estimated_cost_brl == 0.0125
    assert item.usage.gross_profit_brl == 0.0175
    assert item.usage.pricing_status == "priced"
