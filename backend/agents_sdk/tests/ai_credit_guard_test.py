from decimal import Decimal
import os
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/agentive_test")

from backend.services.ai_credit_guard import (
    AI_CREDIT_BLOCK_REASON,
    ai_credit_block_result_from_balance,
    get_ai_credit_balance,
    is_ai_credit_block_result,
    should_block_ai_execution,
)


class _FakeQuery:
    def __init__(self, wallet):
        self.wallet = wallet

    def filter(self, *_args, **_kwargs):
        return self

    def one_or_none(self):
        return self.wallet


class _FakeDB:
    def __init__(self, wallet=None):
        self.wallet = wallet

    def query(self, *_args, **_kwargs):
        return _FakeQuery(self.wallet)


def test_missing_wallet_counts_as_zero_without_blocking_byok_ai():
    db = _FakeDB()

    assert get_ai_credit_balance(db, 3) == Decimal("0")
    assert should_block_ai_execution(db, 3) == (False, Decimal("0"))


def test_positive_balance_allows_ai():
    db = _FakeDB(SimpleNamespace(balance_credits=Decimal("1.000000")))

    assert should_block_ai_execution(db, 3) == (False, Decimal("1.000000"))


def test_credit_guard_no_longer_blocks_byok_ai():
    db = _FakeDB(SimpleNamespace(balance_credits=Decimal("0.000000")))

    result = ai_credit_block_result_from_balance(
        db=db,
        company_id=3,
        source="test",
    )

    assert result is None
    assert is_ai_credit_block_result({"error": AI_CREDIT_BLOCK_REASON}) is True
