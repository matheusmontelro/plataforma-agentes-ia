from decimal import Decimal
from types import SimpleNamespace

from backend.services import ai_usage_service


class FakeDB:
    def __init__(self):
        self.added = []
        self.committed = 0
        self.rolled_back = 0
        self._next_id = 100

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = self._next_id
                self._next_id += 1

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1


def test_credit_calculation_uses_configurable_rates(monkeypatch):
    monkeypatch.setenv("AI_INTERNAL_CREDITS_PER_1K_TOKENS", "2.5")
    monkeypatch.setenv("AI_INTERNAL_CREDITS_PER_TTS_1K_CHARS", "0.5")

    assert ai_usage_service.calculate_text_internal_credits(2000) == Decimal("5.000000")
    assert ai_usage_service.calculate_tts_internal_credits(3000) == Decimal("1.500000")


def test_financial_estimate_uses_openai_model_pricing(monkeypatch):
    monkeypatch.setenv("AI_USD_BRL_EXCHANGE_RATE", "5")
    monkeypatch.setenv("AI_INTERNAL_BRL_PER_CREDIT", "0.01")
    monkeypatch.setenv("AI_CREDIT_REVENUE_FEE_PERCENT", "0")

    financials = ai_usage_service.estimate_usage_financials(
        provider="openai",
        operation="llm_response",
        status="success",
        model="gpt-5.4-mini",
        input_tokens=1000,
        output_tokens=500,
        cached_tokens=100,
        total_tokens=1500,
        text_characters=None,
        internal_credits_charged=Decimal("10"),
    )

    assert financials["estimated_cost_usd"] == Decimal("0.00293250")
    assert financials["estimated_cost_brl"] == Decimal("0.01466250")
    assert financials["revenue_brl"] == Decimal("0.10000000")
    assert financials["gross_profit_brl"] == Decimal("0.08533750")
    assert financials["pricing_snapshot"]["pricing_status"] == "priced"


def test_openai_byok_usage_keeps_cost_audit_without_internal_revenue(monkeypatch):
    monkeypatch.setenv("AI_INTERNAL_PRICING_MODE", "cost_margin")
    monkeypatch.setenv("AI_TARGET_GROSS_MARGIN_PERCENT", "60")
    monkeypatch.setenv("AI_USD_BRL_EXCHANGE_RATE", "6")
    monkeypatch.setenv("AI_INTERNAL_BRL_PER_CREDIT", "0.000998")
    monkeypatch.setenv("AI_CREDIT_REVENUE_FEE_PERCENT", "0")
    wallet = SimpleNamespace(
        id=11,
        balance_credits=Decimal("1000.000000"),
        total_used_credits=Decimal("0.000000"),
    )
    monkeypatch.setattr(
        ai_usage_service,
        "_get_or_create_wallet",
        lambda db, company_id: wallet,
    )
    db = FakeDB()
    usage = {"input_tokens": 4000, "output_tokens": 250, "total_tokens": 4250}

    expensive_event = ai_usage_service.safe_record_openai_text_usage(
        db=db,
        company_id=7,
        usage=usage,
        model="gpt-5.5",
    )
    cheap_event = ai_usage_service.safe_record_openai_text_usage(
        db=db,
        company_id=7,
        usage=usage,
        model="gpt-4o-mini",
    )

    assert expensive_event is not None
    assert cheap_event is not None
    assert expensive_event.internal_credits_charged == Decimal("0")
    assert cheap_event.internal_credits_charged == Decimal("0")
    assert expensive_event.margin_percent is None
    assert cheap_event.margin_percent is None
    assert expensive_event.gross_profit_brl < Decimal("0")
    assert cheap_event.gross_profit_brl < Decimal("0")
    assert wallet.balance_credits == Decimal("1000.000000")
    assert wallet.total_used_credits == Decimal("0.000000")


def test_cost_margin_pricing_keeps_target_margin_for_elevenlabs(monkeypatch):
    monkeypatch.setenv("AI_INTERNAL_PRICING_MODE", "cost_margin")
    monkeypatch.setenv("AI_TARGET_GROSS_MARGIN_PERCENT", "60")
    monkeypatch.setenv("AI_USD_BRL_EXCHANGE_RATE", "6")
    monkeypatch.setenv("AI_INTERNAL_BRL_PER_CREDIT", "0.000998")
    monkeypatch.setenv("AI_CREDIT_REVENUE_FEE_PERCENT", "0")
    wallet = SimpleNamespace(
        id=11,
        balance_credits=Decimal("1000.000000"),
        total_used_credits=Decimal("0.000000"),
    )
    monkeypatch.setattr(
        ai_usage_service,
        "_get_or_create_wallet",
        lambda db, company_id: wallet,
    )
    db = FakeDB()

    event = ai_usage_service.safe_record_tts_usage(
        db=db,
        company_id=7,
        provider="elevenlabs",
        model="eleven_flash_v2_5",
        text_characters=1000,
        status="success",
    )

    assert event is not None
    assert event.internal_credits_charged == Decimal("751.503007")
    assert event.provider_usage_units == Decimal("500.000000")
    assert event.margin_percent == Decimal("60.0000")
    assert event.gross_profit_brl == Decimal("0.45000000")


def test_elevenlabs_provider_credits_follow_model_multiplier(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_TTS_PRICING_JSON", raising=False)

    assert ai_usage_service.calculate_elevenlabs_provider_credits("eleven_flash_v2_5", 1000) == Decimal("500.000000")
    assert ai_usage_service.calculate_elevenlabs_provider_credits("eleven_multilingual_v2", 1000) == Decimal("1000.000000")


def test_extract_openai_usage_supports_chat_usage_objects():
    usage = SimpleNamespace(
        prompt_tokens=120,
        completion_tokens=30,
        total_tokens=None,
        prompt_tokens_details=SimpleNamespace(cached_tokens=8),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=4),
    )

    assert ai_usage_service.extract_openai_usage(usage) == {
        "input_tokens": 120,
        "output_tokens": 30,
        "cached_tokens": 8,
        "reasoning_tokens": 4,
        "total_tokens": 150,
    }


def test_record_openai_usage_event_keeps_wallet_untouched_for_byok(monkeypatch):
    monkeypatch.setenv("AI_USD_BRL_EXCHANGE_RATE", "5")
    monkeypatch.setenv("AI_INTERNAL_BRL_PER_CREDIT", "0.01")
    wallet = SimpleNamespace(
        id=11,
        balance_credits=Decimal("10.000000"),
        total_used_credits=Decimal("1.000000"),
    )
    monkeypatch.setattr(
        ai_usage_service,
        "_get_or_create_wallet",
        lambda db, company_id: wallet,
    )
    db = FakeDB()

    event = ai_usage_service.record_ai_usage_event(
        db=db,
        company_id=7,
        provider="openai",
        operation="llm_response",
        status="success",
        model="gpt-5.4-mini",
        agent_execution_id=123,
        total_tokens=1250,
        internal_credits_charged=Decimal("1.25"),
    )

    transactions = [
        obj for obj in db.added if obj.__class__.__name__ == "AICreditTransaction"
    ]

    assert event.id == 100
    assert event.agent_execution_id == 123
    assert not event.__table__.c.agent_execution_id.foreign_keys
    assert event.internal_credits_charged == Decimal("0.000000")
    assert event.estimated_cost_usd == Decimal("0.00093750")
    assert event.estimated_cost_brl == Decimal("0.00468750")
    assert event.revenue_brl == Decimal("0E-8")
    assert event.gross_profit_brl == Decimal("-0.00468750")
    assert event.margin_percent is None
    assert event.pricing_snapshot["pricing_status"] == "priced"
    assert wallet.balance_credits == Decimal("10.000000")
    assert wallet.total_used_credits == Decimal("1.000000")
    assert transactions == []
    assert db.committed == 1


def test_managed_workspace_trial_credit_map():
    assert ai_usage_service.managed_workspace_trial_credits_for_days(0) == Decimal("0.000000")
    assert ai_usage_service.managed_workspace_trial_credits_for_days(3) == Decimal("500.000000")
    assert ai_usage_service.managed_workspace_trial_credits_for_days(7) == Decimal("1000.000000")
    assert ai_usage_service.managed_workspace_trial_credits_for_days(14) == Decimal("2500.000000")
    assert ai_usage_service.managed_workspace_trial_credits_for_days(30) == Decimal("5000.000000")
    assert ai_usage_service.managed_workspace_trial_credits_for_days(99) == Decimal("0.000000")


def test_grant_managed_workspace_trial_ai_credits_creates_credit_transaction(monkeypatch):
    wallet = SimpleNamespace(
        id=22,
        balance_credits=Decimal("100.000000"),
        total_granted_credits=Decimal("100.000000"),
    )
    monkeypatch.setattr(
        ai_usage_service,
        "_get_or_create_wallet",
        lambda db, company_id: wallet,
    )
    db = FakeDB()

    result_wallet, transaction = ai_usage_service.grant_managed_workspace_trial_ai_credits(
        db=db,
        company_id=8,
        owner_company_id=3,
        customer_id=44,
        managed_link_id=55,
        trial_days=14,
    )

    assert result_wallet is wallet
    assert wallet.balance_credits == Decimal("2600.000000")
    assert wallet.total_granted_credits == Decimal("2600.000000")
    assert transaction.id == 100
    assert transaction.transaction_type == "credit"
    assert transaction.amount_credits == Decimal("2500.000000")
    assert transaction.balance_after == Decimal("2600.000000")
    assert transaction.transaction_metadata["source"] == "managed_workspace_trial_bonus"
    assert transaction.transaction_metadata["trial_days"] == 14
    assert transaction.transaction_metadata["owner_company_id"] == 3
    assert transaction.transaction_metadata["customer_id"] == 44
    assert transaction.transaction_metadata["managed_link_id"] == 55
    assert db.committed == 0


def test_safe_record_tts_usage_does_not_debit_failed_generation(monkeypatch):
    wallet = SimpleNamespace(
        id=11,
        balance_credits=Decimal("10.000000"),
        total_used_credits=Decimal("1.000000"),
    )
    monkeypatch.setattr(
        ai_usage_service,
        "_get_or_create_wallet",
        lambda db, company_id: wallet,
    )
    db = FakeDB()

    event = ai_usage_service.safe_record_tts_usage(
        db=db,
        company_id=7,
        provider="elevenlabs",
        model="eleven_flash_v2_5",
        text_characters=2000,
        status="failed",
        error_message="insufficient credits",
    )

    transactions = [
        obj for obj in db.added if obj.__class__.__name__ == "AICreditTransaction"
    ]

    assert event is not None
    assert event.internal_credits_charged == Decimal("0.000000")
    assert wallet.balance_credits == Decimal("10.000000")
    assert wallet.total_used_credits == Decimal("1.000000")
    assert transactions == []
    assert db.committed == 1


def test_safe_record_ai_usage_event_rolls_back_without_raising(monkeypatch):
    db = FakeDB()

    def fail(**kwargs):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(ai_usage_service, "record_ai_usage_event", fail)

    assert ai_usage_service.safe_record_ai_usage_event(db=db) is None
    assert db.rolled_back == 1
