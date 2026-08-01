"""Legacy credit helpers kept for the ElevenLabs transition.

Text agents now run with the workspace's own OpenAI credential, so a missing or
empty internal wallet must never block an LLM execution. The balance reader is
still used by the temporary ElevenLabs compatibility path.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from backend.models import AICreditWallet

logger = logging.getLogger(__name__)

AI_CREDIT_BLOCK_REASON = "insufficient_ai_credits"
AI_CREDIT_BLOCK_MESSAGE = "Créditos de IA esgotados para a empresa"
ZERO_CREDITS = Decimal("0")


def get_ai_credit_balance(db: Session, company_id: int) -> Decimal:
    """Return the current AI credit balance; missing wallet means zero balance."""
    wallet = (
        db.query(AICreditWallet)
        .filter(AICreditWallet.company_id == company_id)
        .one_or_none()
    )
    if not wallet:
        return ZERO_CREDITS
    return Decimal(str(wallet.balance_credits or 0))


def should_block_ai_execution(db: Session, company_id: int) -> Tuple[bool, Decimal]:
    """Return the legacy balance without blocking BYOK text execution."""
    balance = get_ai_credit_balance(db, company_id)
    return False, balance


def build_ai_credit_block_result(
    *,
    company_id: int,
    balance: Decimal,
    source: str,
    response: str = "",
) -> Dict[str, Any]:
    return {
        "success": False,
        "response": response,
        "error": AI_CREDIT_BLOCK_REASON,
        "reason": AI_CREDIT_BLOCK_REASON,
        "blocked_by_ai_credits": True,
        "company_id": company_id,
        "ai_credit_balance": float(balance),
        "metadata": {
            "blocked_by_ai_credits": True,
            "reason": AI_CREDIT_BLOCK_REASON,
            "source": source,
            "ai_credit_balance": float(balance),
        },
    }


def ai_credit_block_result_from_balance(
    *,
    db: Session,
    company_id: int,
    source: str,
) -> Optional[Dict[str, Any]]:
    del db, company_id, source
    return None


def is_ai_credit_block_result(result: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(result, dict):
        return False
    return (
        bool(result.get("blocked_by_ai_credits"))
        or result.get("reason") == AI_CREDIT_BLOCK_REASON
        or result.get("error") == AI_CREDIT_BLOCK_REASON
    )
