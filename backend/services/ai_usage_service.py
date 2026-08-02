"""Internal AI usage and credit ledger helpers."""

from __future__ import annotations

import json
import logging
import os
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, ROUND_UP
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from backend.models import AICreditTransaction, AICreditWallet, AIUsageEvent

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
SIX_PLACES = Decimal("0.000001")
MONEY_PLACES = Decimal("0.00000001")
PERCENT_PLACES = Decimal("0.0001")
ONE_THOUSAND = Decimal("1000")
ONE_MILLION = Decimal("1000000")
MANAGED_WORKSPACE_TRIAL_BONUS_SOURCE = "managed_workspace_trial_bonus"
MANAGED_WORKSPACE_TRIAL_CREDITS_BY_DAYS: Dict[int, Decimal] = {
    0: ZERO,
    3: Decimal("500"),
    7: Decimal("1000"),
    14: Decimal("2500"),
    30: Decimal("5000"),
}

DEFAULT_OPENAI_PRICING: Dict[str, Dict[str, str]] = {
    "gpt-5.5": {"input_per_1m_usd": "5.00", "cached_input_per_1m_usd": "0.50", "output_per_1m_usd": "30.00"},
    "gpt-5.5-pro": {"input_per_1m_usd": "30.00", "output_per_1m_usd": "180.00"},
    "gpt-5.4": {"input_per_1m_usd": "2.50", "cached_input_per_1m_usd": "0.25", "output_per_1m_usd": "15.00"},
    "gpt-5.4-mini": {"input_per_1m_usd": "0.75", "cached_input_per_1m_usd": "0.075", "output_per_1m_usd": "4.50"},
    "gpt-5.4-nano": {"input_per_1m_usd": "0.20", "cached_input_per_1m_usd": "0.02", "output_per_1m_usd": "1.25"},
    "gpt-5.4-pro": {"input_per_1m_usd": "30.00", "output_per_1m_usd": "180.00"},
    "gpt-4o-mini": {"input_per_1m_usd": "0.15", "cached_input_per_1m_usd": "0.075", "output_per_1m_usd": "0.60"},
    "gpt-4o-mini-2024-07-18": {"input_per_1m_usd": "0.15", "cached_input_per_1m_usd": "0.075", "output_per_1m_usd": "0.60"},
}

DEFAULT_ELEVENLABS_TTS_PRICING: Dict[str, Dict[str, str]] = {
    "eleven_flash_v2": {"usd_per_1k_chars": "0.05", "provider_credits_per_char": "0.5"},
    "eleven_flash_v2_5": {"usd_per_1k_chars": "0.05", "provider_credits_per_char": "0.5"},
    "eleven_turbo_v2": {"usd_per_1k_chars": "0.05", "provider_credits_per_char": "0.5"},
    "eleven_turbo_v2_5": {"usd_per_1k_chars": "0.05", "provider_credits_per_char": "0.5"},
    "eleven_multilingual_v1": {"usd_per_1k_chars": "0.10", "provider_credits_per_char": "1"},
    "eleven_multilingual_v2": {"usd_per_1k_chars": "0.10", "provider_credits_per_char": "1"},
    "eleven_v3": {"usd_per_1k_chars": "0.10", "provider_credits_per_char": "1"},
}


def _decimal_from_env(name: str, default: str) -> Decimal:
    raw = os.getenv(name, default)
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        logger.warning("Invalid decimal env %s=%r; using %s", name, raw, default)
        return Decimal(default)


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(SIX_PLACES, rounding=ROUND_HALF_UP)


def _ceil_quantize(value: Decimal) -> Decimal:
    return value.quantize(SIX_PLACES, rounding=ROUND_UP)


def _money_quantize(value: Decimal) -> Decimal:
    return value.quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


def _percent_quantize(value: Decimal) -> Decimal:
    return value.quantize(PERCENT_PLACES, rounding=ROUND_HALF_UP)


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pricing_map_from_env(name: str, default: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    pricing = {key: dict(value) for key, value in default.items()}
    raw = os.getenv(name)
    if not raw:
        return pricing
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON env %s; using built-in pricing defaults", name)
        return pricing
    if not isinstance(parsed, dict):
        logger.warning("Invalid pricing env %s; expected object, using defaults", name)
        return pricing
    for model, values in parsed.items():
        if isinstance(values, dict):
            pricing[str(model)] = {str(key): str(value) for key, value in values.items()}
    return pricing


def _find_model_pricing(
    model: Optional[str],
    pricing: Dict[str, Dict[str, str]],
) -> tuple[Optional[str], Optional[Dict[str, str]]]:
    if not model:
        return None, None
    normalized = str(model).strip()
    if normalized in pricing:
        return normalized, pricing[normalized]

    matches = [
        key for key in pricing
        if normalized.startswith(f"{key}-") or normalized.startswith(f"{key}.")
    ]
    if matches:
        key = max(matches, key=len)
        return key, pricing[key]
    return None, None


def _decimal_from_mapping(mapping: Dict[str, Any], key: str, default: Optional[Decimal] = None) -> Optional[Decimal]:
    if key not in mapping:
        return default
    try:
        return Decimal(str(mapping[key]))
    except (InvalidOperation, ValueError):
        logger.warning("Invalid decimal pricing value for %s=%r", key, mapping.get(key))
        return default


def _snapshot_decimal(value: Optional[Decimal]) -> Optional[str]:
    return str(value) if value is not None else None


def _internal_pricing_mode() -> str:
    return os.getenv("AI_INTERNAL_PRICING_MODE", "fixed_rate").strip().lower() or "fixed_rate"


def _target_gross_margin_percent() -> Decimal:
    percent = _decimal_from_env("AI_TARGET_GROSS_MARGIN_PERCENT", "60")
    if percent < ZERO or percent >= Decimal("100"):
        logger.warning("Invalid AI_TARGET_GROSS_MARGIN_PERCENT=%s; using 60", percent)
        return Decimal("60")
    return percent


def _calculate_revenue_brl(internal_credits_charged: Decimal) -> tuple[Decimal, Dict[str, Any]]:
    credit_value_brl = _decimal_from_env("AI_INTERNAL_BRL_PER_CREDIT", "0.001")
    gateway_fee_percent = _decimal_from_env("AI_CREDIT_REVENUE_FEE_PERCENT", "0")
    revenue_brl = _money_quantize(internal_credits_charged * credit_value_brl)
    gateway_fee_brl = _money_quantize(revenue_brl * gateway_fee_percent / Decimal("100"))
    return revenue_brl, {
        "internal_brl_per_credit": str(credit_value_brl),
        "gateway_fee_percent": str(gateway_fee_percent),
        "gateway_fee_brl": str(gateway_fee_brl),
    }


def calculate_elevenlabs_provider_credits(model: Optional[str], text_characters: int) -> Decimal:
    """Estimate ElevenLabs provider credits from the fixed TTS model."""

    if text_characters <= 0:
        return ZERO
    pricing = _pricing_map_from_env("ELEVENLABS_TTS_PRICING_JSON", DEFAULT_ELEVENLABS_TTS_PRICING)
    _, model_pricing = _find_model_pricing(model, pricing)
    credits_per_char = _decimal_from_mapping(
        model_pricing or {},
        "provider_credits_per_char",
        Decimal("1"),
    )
    return _quantize(Decimal(text_characters) * (credits_per_char or Decimal("1")))


def estimate_usage_financials(
    *,
    provider: str,
    operation: str,
    status: str,
    model: Optional[str],
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    cached_tokens: Optional[int],
    total_tokens: Optional[int],
    text_characters: Optional[int],
    internal_credits_charged: Decimal,
) -> Dict[str, Any]:
    """Estimate provider cost and gross margin from model-specific pricing."""

    revenue_brl, revenue_snapshot = _calculate_revenue_brl(internal_credits_charged)
    snapshot: Dict[str, Any] = {
        "pricing_version": "platform-ai-cost-v1",
        "provider": provider,
        "operation": operation,
        "model": model,
        "status": status,
        "revenue": revenue_snapshot,
        "internal_credit_pricing": {
            "mode": _internal_pricing_mode(),
            "target_gross_margin_percent": str(_target_gross_margin_percent()),
        },
    }

    if status != "success":
        return {
            "estimated_cost_usd": ZERO,
            "estimated_cost_brl": ZERO,
            "revenue_brl": ZERO,
            "gross_profit_brl": ZERO,
            "margin_percent": None,
            "pricing_snapshot": {**snapshot, "pricing_status": "not_billable_status"},
        }

    exchange_rate = _decimal_from_env("AI_USD_BRL_EXCHANGE_RATE", "5.30")
    gateway_fee_brl = Decimal(revenue_snapshot["gateway_fee_brl"])
    cost_usd: Optional[Decimal] = None
    provider_pricing: Dict[str, Any] = {}
    pricing_status = "priced"

    if provider == "openai" and operation == "llm_response":
        pricing = _pricing_map_from_env("OPENAI_MODEL_PRICING_JSON", DEFAULT_OPENAI_PRICING)
        matched_model, model_pricing = _find_model_pricing(model, pricing)
        if not model_pricing:
            pricing_status = "missing_openai_model_pricing"
        else:
            input_rate = _decimal_from_mapping(model_pricing, "input_per_1m_usd", ZERO) or ZERO
            cached_rate = _decimal_from_mapping(model_pricing, "cached_input_per_1m_usd", input_rate) or input_rate
            output_rate = _decimal_from_mapping(model_pricing, "output_per_1m_usd", ZERO) or ZERO
            input_count = Decimal(input_tokens or total_tokens or 0)
            cached_count = Decimal(cached_tokens or 0)
            output_count = Decimal(output_tokens or 0)
            uncached_input_count = max(input_count - cached_count, ZERO)
            cost_usd = _money_quantize(
                (uncached_input_count / ONE_MILLION * input_rate)
                + (cached_count / ONE_MILLION * cached_rate)
                + (output_count / ONE_MILLION * output_rate)
            )
            provider_pricing = {
                "matched_model": matched_model,
                "input_per_1m_usd": str(input_rate),
                "cached_input_per_1m_usd": str(cached_rate),
                "output_per_1m_usd": str(output_rate),
                "input_tokens": int(input_count),
                "cached_tokens": int(cached_count),
                "output_tokens": int(output_count),
            }
    elif provider == "elevenlabs" and operation == "tts":
        pricing = _pricing_map_from_env("ELEVENLABS_TTS_PRICING_JSON", DEFAULT_ELEVENLABS_TTS_PRICING)
        matched_model, model_pricing = _find_model_pricing(model, pricing)
        if not model_pricing:
            pricing_status = "missing_elevenlabs_model_pricing"
        else:
            usd_per_1k_chars = _decimal_from_mapping(model_pricing, "usd_per_1k_chars", ZERO) or ZERO
            credits_per_char = _decimal_from_mapping(model_pricing, "provider_credits_per_char", Decimal("1")) or Decimal("1")
            characters = Decimal(text_characters or 0)
            cost_usd = _money_quantize(characters / ONE_THOUSAND * usd_per_1k_chars)
            provider_pricing = {
                "matched_model": matched_model,
                "usd_per_1k_chars": str(usd_per_1k_chars),
                "provider_credits_per_char": str(credits_per_char),
                "text_characters": int(characters),
            }
    else:
        pricing_status = "unsupported_provider_operation"

    snapshot.update({
        "pricing_status": pricing_status,
        "exchange_rate_usd_brl": str(exchange_rate),
        "provider_pricing": provider_pricing,
    })

    if cost_usd is None:
        return {
            "estimated_cost_usd": None,
            "estimated_cost_brl": None,
            "revenue_brl": revenue_brl,
            "gross_profit_brl": None,
            "margin_percent": None,
            "pricing_snapshot": snapshot,
        }

    cost_brl = _money_quantize(cost_usd * exchange_rate)
    gross_profit_brl = _money_quantize(revenue_brl - cost_brl - gateway_fee_brl)
    margin_percent = None
    if revenue_brl > ZERO:
        margin_percent = _percent_quantize((gross_profit_brl / revenue_brl) * Decimal("100"))

    return {
        "estimated_cost_usd": cost_usd,
        "estimated_cost_brl": cost_brl,
        "revenue_brl": revenue_brl,
        "gross_profit_brl": gross_profit_brl,
        "margin_percent": margin_percent,
        "pricing_snapshot": snapshot,
    }


def calculate_text_internal_credits(total_tokens: int) -> Decimal:
    """Convert OpenAI token usage to internal credits.

    Default: 1 internal credit per 1k tokens. This is intentionally configurable
    because commercial pricing will be a product decision, not a provider fact.
    """

    if total_tokens <= 0:
        return ZERO
    rate = _decimal_from_env("AI_INTERNAL_CREDITS_PER_1K_TOKENS", "1")
    return _quantize((Decimal(total_tokens) / Decimal(1000)) * rate)


def calculate_tts_internal_credits(text_characters: int) -> Decimal:
    """Convert TTS characters to internal credits.

    Default: 1 internal credit per 1k characters. Provider-side ElevenLabs
    credits are stored separately as provider usage units when available.
    """

    if text_characters <= 0:
        return ZERO
    rate = _decimal_from_env("AI_INTERNAL_CREDITS_PER_TTS_1K_CHARS", "1")
    return _quantize((Decimal(text_characters) / Decimal(1000)) * rate)


def _calculate_fixed_rate_internal_credits(
    *,
    provider: str,
    operation: str,
    total_tokens: Optional[int],
    text_characters: Optional[int],
) -> Decimal:
    if provider == "openai" and operation == "llm_response":
        return calculate_text_internal_credits(total_tokens or 0)
    if provider == "elevenlabs" and operation == "tts":
        return calculate_tts_internal_credits(text_characters or 0)
    return ZERO


def calculate_required_internal_credits_for_cost(cost_brl: Decimal) -> Optional[Decimal]:
    """Calculate credits needed to cover provider cost and target gross margin."""

    if cost_brl <= ZERO:
        return ZERO

    credit_value_brl = _decimal_from_env("AI_INTERNAL_BRL_PER_CREDIT", "0.001")
    gateway_fee_percent = _decimal_from_env("AI_CREDIT_REVENUE_FEE_PERCENT", "0")
    target_margin_percent = _target_gross_margin_percent()
    retained_revenue_fraction = (
        Decimal("1")
        - (target_margin_percent / Decimal("100"))
        - (gateway_fee_percent / Decimal("100"))
    )

    if credit_value_brl <= ZERO:
        logger.warning("AI_INTERNAL_BRL_PER_CREDIT must be greater than zero for cost-margin pricing")
        return None
    if retained_revenue_fraction <= ZERO:
        logger.warning(
            "AI target margin plus gateway fee leaves no retained revenue: margin=%s fee=%s",
            target_margin_percent,
            gateway_fee_percent,
        )
        return None

    required_revenue_brl = cost_brl / retained_revenue_fraction
    return _ceil_quantize(required_revenue_brl / credit_value_brl)


def calculate_usage_internal_credits(
    *,
    provider: str,
    operation: str,
    status: str,
    model: Optional[str],
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    cached_tokens: Optional[int],
    total_tokens: Optional[int],
    text_characters: Optional[int],
) -> Decimal:
    """Calculate internal credits from fixed rates or provider cost plus margin."""

    if status != "success":
        return ZERO

    fixed_credits = _calculate_fixed_rate_internal_credits(
        provider=provider,
        operation=operation,
        total_tokens=total_tokens,
        text_characters=text_characters,
    )
    if _internal_pricing_mode() not in {"cost_margin", "margin"}:
        return fixed_credits

    financials = estimate_usage_financials(
        provider=provider,
        operation=operation,
        status=status,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        total_tokens=total_tokens,
        text_characters=text_characters,
        internal_credits_charged=ZERO,
    )
    cost_brl = financials.get("estimated_cost_brl")
    if cost_brl is None:
        return fixed_credits

    required_credits = calculate_required_internal_credits_for_cost(Decimal(str(cost_brl)))
    return required_credits if required_credits is not None else fixed_credits


def extract_openai_usage(usage: Any) -> Dict[str, Optional[int]]:
    """Normalize OpenAI usage objects/dicts from Responses or Chat APIs."""

    if not usage:
        return {
            "input_tokens": None,
            "output_tokens": None,
            "cached_tokens": None,
            "reasoning_tokens": None,
            "total_tokens": None,
        }

    if hasattr(usage, "model_dump"):
        usage_data = usage.model_dump()
    elif isinstance(usage, dict):
        usage_data = usage
    else:
        usage_data = {
            "input_tokens": getattr(usage, "input_tokens", None),
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
            "input_tokens_details": getattr(usage, "input_tokens_details", None),
            "prompt_tokens_details": getattr(usage, "prompt_tokens_details", None),
            "output_tokens_details": getattr(usage, "output_tokens_details", None),
            "completion_tokens_details": getattr(usage, "completion_tokens_details", None),
        }

    input_details = usage_data.get("input_tokens_details") or usage_data.get("prompt_tokens_details") or {}
    output_details = usage_data.get("output_tokens_details") or usage_data.get("completion_tokens_details") or {}
    if hasattr(input_details, "model_dump"):
        input_details = input_details.model_dump()
    if hasattr(output_details, "model_dump"):
        output_details = output_details.model_dump()
    if input_details and not isinstance(input_details, dict):
        input_details = {"cached_tokens": getattr(input_details, "cached_tokens", None)}
    if output_details and not isinstance(output_details, dict):
        output_details = {"reasoning_tokens": getattr(output_details, "reasoning_tokens", None)}

    input_tokens = _safe_int(usage_data.get("input_tokens") or usage_data.get("prompt_tokens"))
    output_tokens = _safe_int(usage_data.get("output_tokens") or usage_data.get("completion_tokens"))
    total_tokens = _safe_int(usage_data.get("total_tokens"))
    if total_tokens is None and (input_tokens is not None or output_tokens is not None):
        total_tokens = (input_tokens or 0) + (output_tokens or 0)

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": _safe_int(input_details.get("cached_tokens") if isinstance(input_details, dict) else None),
        "reasoning_tokens": _safe_int(output_details.get("reasoning_tokens") if isinstance(output_details, dict) else None),
        "total_tokens": total_tokens,
    }


def _get_or_create_wallet(db: Session, company_id: int) -> AICreditWallet:
    wallet = (
        db.query(AICreditWallet)
        .filter(AICreditWallet.company_id == company_id)
        .one_or_none()
    )
    if wallet:
        return wallet

    wallet = AICreditWallet(company_id=company_id)
    db.add(wallet)
    db.flush()
    return wallet


def managed_workspace_trial_credits_for_days(trial_days: Optional[int]) -> Decimal:
    """Return the internal AI credits granted for a managed workspace trial."""

    try:
        days = int(trial_days or 0)
    except (TypeError, ValueError):
        days = 0
    return _quantize(MANAGED_WORKSPACE_TRIAL_CREDITS_BY_DAYS.get(days, ZERO))


def grant_managed_workspace_trial_ai_credits(
    *,
    db: Session,
    company_id: int,
    owner_company_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    managed_link_id: Optional[int] = None,
    trial_days: Optional[int] = None,
) -> tuple[Optional[AICreditWallet], Optional[AICreditTransaction]]:
    credits = managed_workspace_trial_credits_for_days(trial_days)
    if credits <= ZERO:
        return None, None

    wallet = _get_or_create_wallet(db, company_id)
    current_balance = Decimal(str(wallet.balance_credits or 0))
    current_granted = Decimal(str(wallet.total_granted_credits or 0))
    wallet.balance_credits = _quantize(current_balance + credits)
    wallet.total_granted_credits = _quantize(current_granted + credits)

    transaction = AICreditTransaction(
        company_id=company_id,
        wallet_id=wallet.id,
        transaction_type="credit",
        amount_credits=credits,
        balance_after=wallet.balance_credits,
        description="Bônus inicial de trial para workspace de cliente",
        transaction_metadata={
            "source": MANAGED_WORKSPACE_TRIAL_BONUS_SOURCE,
            "credits": int(credits),
            "trial_days": int(trial_days or 0),
            "owner_company_id": int(owner_company_id) if owner_company_id is not None else None,
            "customer_id": int(customer_id) if customer_id is not None else None,
            "managed_link_id": int(managed_link_id) if managed_link_id is not None else None,
        },
    )
    db.add(transaction)
    db.flush()
    return wallet, transaction


def record_ai_usage_event(
    *,
    db: Session,
    company_id: int,
    provider: str,
    operation: str,
    status: str,
    model: Optional[str] = None,
    agent_execution_id: Optional[int] = None,
    agent_key: Optional[str] = None,
    agent_name: Optional[str] = None,
    phone: Optional[str] = None,
    conversation_group: Optional[str] = None,
    trace_id: Optional[str] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    cached_tokens: Optional[int] = None,
    reasoning_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    text_characters: Optional[int] = None,
    provider_usage_units: Optional[Decimal] = None,
    internal_credits_charged: Optional[Decimal] = None,
    estimated_cost_usd: Optional[Decimal] = None,
    estimated_cost_brl: Optional[Decimal] = None,
    revenue_brl: Optional[Decimal] = None,
    gross_profit_brl: Optional[Decimal] = None,
    margin_percent: Optional[Decimal] = None,
    pricing_snapshot: Optional[Dict[str, Any]] = None,
    provider_request_id: Optional[str] = None,
    provider_response_id: Optional[str] = None,
    usage_metadata: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
) -> AIUsageEvent:
    # OpenAI usage is billed directly to the workspace credential (BYOK).
    # Keep the technical usage event, but never debit the legacy platform
    # wallet. ElevenLabs remains temporarily on the previous balance for the
    # two already-active voice workspaces during the migration.
    credits = ZERO if provider == "openai" else (
        _quantize(internal_credits_charged)
        if internal_credits_charged is not None
        else calculate_usage_internal_credits(
            provider=provider,
            operation=operation,
            status=status,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            total_tokens=total_tokens,
            text_characters=text_characters,
        )
    )
    provider_units = _quantize(provider_usage_units) if provider_usage_units is not None else None
    if provider == "elevenlabs" and operation == "tts" and text_characters:
        provider_units = calculate_elevenlabs_provider_credits(model, text_characters)

    financials = estimate_usage_financials(
        provider=provider,
        operation=operation,
        status=status,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        total_tokens=total_tokens,
        text_characters=text_characters,
        internal_credits_charged=credits,
    )
    final_cost_usd = (
        _money_quantize(estimated_cost_usd)
        if estimated_cost_usd is not None
        else financials["estimated_cost_usd"]
    )
    final_cost_brl = (
        _money_quantize(estimated_cost_brl)
        if estimated_cost_brl is not None
        else financials["estimated_cost_brl"]
    )
    final_revenue_brl = (
        _money_quantize(revenue_brl)
        if revenue_brl is not None
        else financials["revenue_brl"]
    )
    final_profit_brl = (
        _money_quantize(gross_profit_brl)
        if gross_profit_brl is not None
        else financials["gross_profit_brl"]
    )
    final_margin_percent = (
        _percent_quantize(margin_percent)
        if margin_percent is not None
        else financials["margin_percent"]
    )
    final_pricing_snapshot = {
        **(financials.get("pricing_snapshot") or {}),
        **(pricing_snapshot or {}),
    }

    event = AIUsageEvent(
        company_id=company_id,
        agent_execution_id=agent_execution_id,
        agent_key=agent_key,
        agent_name=agent_name,
        phone=phone,
        conversation_group=conversation_group,
        trace_id=trace_id,
        provider=provider,
        operation=operation,
        model=model,
        status=status,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        reasoning_tokens=reasoning_tokens,
        total_tokens=total_tokens,
        text_characters=text_characters,
        provider_usage_units=provider_units,
        estimated_cost_usd=final_cost_usd,
        estimated_cost_brl=final_cost_brl,
        revenue_brl=final_revenue_brl,
        gross_profit_brl=final_profit_brl,
        margin_percent=final_margin_percent,
        internal_credits_charged=credits,
        provider_request_id=provider_request_id,
        provider_response_id=provider_response_id,
        pricing_snapshot=final_pricing_snapshot,
        usage_metadata=usage_metadata or {},
        error_message=error_message,
    )

    db.add(event)
    db.flush()

    if status == "success" and credits > ZERO:
        wallet = _get_or_create_wallet(db, company_id)
        current_balance = Decimal(str(wallet.balance_credits or 0))
        current_used = Decimal(str(wallet.total_used_credits or 0))
        wallet.balance_credits = _quantize(current_balance - credits)
        wallet.total_used_credits = _quantize(current_used + credits)

        db.add(
            AICreditTransaction(
                company_id=company_id,
                wallet_id=wallet.id,
                usage_event_id=event.id,
                transaction_type="debit",
                amount_credits=credits,
                balance_after=wallet.balance_credits,
                description=f"{provider}:{operation}",
                transaction_metadata={
                    "provider": provider,
                    "operation": operation,
                    "model": model,
                    "status": status,
                    "estimated_cost_usd": _snapshot_decimal(final_cost_usd),
                    "estimated_cost_brl": _snapshot_decimal(final_cost_brl),
                    "revenue_brl": _snapshot_decimal(final_revenue_brl),
                    "gross_profit_brl": _snapshot_decimal(final_profit_brl),
                    "margin_percent": _snapshot_decimal(final_margin_percent),
                    "pricing_status": final_pricing_snapshot.get("pricing_status"),
                },
            )
        )

    db.commit()
    return event


def safe_record_ai_usage_event(**kwargs: Any) -> Optional[AIUsageEvent]:
    """Record usage without allowing accounting failures to break messaging."""

    db = kwargs.get("db")
    try:
        return record_ai_usage_event(**kwargs)
    except Exception as exc:
        if db is not None:
            try:
                db.rollback()
            except Exception:
                pass
        logger.exception("[AIUsage] Failed to record AI usage event: %s", exc)
        return None


def safe_record_openai_text_usage(
    *,
    db: Session,
    company_id: int,
    usage: Any,
    model: Optional[str],
    status: str = "success",
    **metadata: Any,
) -> Optional[AIUsageEvent]:
    normalized = extract_openai_usage(usage)
    internal_credits_charged = metadata.pop("internal_credits_charged", None)

    return safe_record_ai_usage_event(
        db=db,
        company_id=company_id,
        provider="openai",
        operation="llm_response",
        status=status,
        model=model,
        input_tokens=normalized["input_tokens"],
        output_tokens=normalized["output_tokens"],
        cached_tokens=normalized["cached_tokens"],
        reasoning_tokens=normalized["reasoning_tokens"],
        total_tokens=normalized["total_tokens"],
        internal_credits_charged=internal_credits_charged,
        usage_metadata={"raw_usage": _usage_to_plain_dict(usage), **metadata.pop("usage_metadata", {})},
        **metadata,
    )


def safe_record_tts_usage(
    *,
    db: Session,
    company_id: int,
    provider: str,
    model: Optional[str],
    text_characters: int,
    status: str,
    provider_usage_units: Optional[Decimal] = None,
    **metadata: Any,
) -> Optional[AIUsageEvent]:
    internal_credits_charged = metadata.pop("internal_credits_charged", None)

    return safe_record_ai_usage_event(
        db=db,
        company_id=company_id,
        provider=provider,
        operation="tts",
        status=status,
        model=model,
        text_characters=text_characters,
        provider_usage_units=provider_usage_units,
        internal_credits_charged=internal_credits_charged,
        **metadata,
    )


def _usage_to_plain_dict(usage: Any) -> Dict[str, Any]:
    if not usage:
        return {}
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if isinstance(usage, dict):
        return usage
    return {
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }
