import os
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/agentive_ai_credits_routes_test.db")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from backend.routes import ai_credits_routes


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
