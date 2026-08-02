"""Read APIs for the internal AI credit ledger."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import AICreditTransaction, AICreditWallet, AIUsageEvent

router = APIRouter(prefix="/ai-credits", tags=["AI Credits"])

def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def _to_int(value: Any) -> int:
    if value is None:
        return 0
    return int(value)


def _company_id_from_user(user: Any) -> int:
    company_id = getattr(user, "company_id", None)
    if not company_id:
        raise HTTPException(status_code=400, detail="Empresa ativa não selecionada")
    return int(company_id)


def _mask_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) <= 4:
        return "****"
    return f"***{digits[-4:]}"


def _period_start(days: int) -> datetime:
    now = datetime.now(timezone.utc)
    start_date = (now - timedelta(days=days - 1)).date()
    return datetime.combine(start_date, time.min, tzinfo=timezone.utc)


class AICreditWalletSummary(BaseModel):
    balance_credits: float = 0
    total_granted_credits: float = 0
    total_used_credits: float = 0
    currency: str = "internal_credit"
    status: str = "active"
    updated_at: Optional[datetime] = None


class AICreditUsageSummary(BaseModel):
    period_days: int
    today_credits: float
    period_credits: float
    month_credits: float
    estimated_cost_usd: float
    estimated_cost_brl: float
    revenue_brl: float
    gross_profit_brl: float
    margin_percent: Optional[float] = None
    text_credits: float
    audio_credits: float
    text_tokens: int
    audio_characters: int
    success_events: int
    failed_events: int
    unpriced_events: int
    negative_profit_events: int
    last_event_at: Optional[datetime] = None


class AICreditSummaryResponse(BaseModel):
    wallet: AICreditWalletSummary
    usage: AICreditUsageSummary


class AICreditUsagePoint(BaseModel):
    date: str
    text_credits: float
    audio_credits: float
    total_credits: float
    estimated_cost_brl: float
    revenue_brl: float
    gross_profit_brl: float
    text_tokens: int
    audio_characters: int


class AICreditUsageResponse(BaseModel):
    period_days: int
    series: List[AICreditUsagePoint]


class AICreditTransactionUsage(BaseModel):
    provider: Optional[str] = None
    operation: Optional[str] = None
    status: Optional[str] = None
    model: Optional[str] = None
    agent_name: Optional[str] = None
    phone_masked: Optional[str] = None
    total_tokens: Optional[int] = None
    text_characters: Optional[int] = None
    provider_usage_units: Optional[float] = None
    estimated_cost_usd: Optional[float] = None
    estimated_cost_brl: Optional[float] = None
    revenue_brl: Optional[float] = None
    gross_profit_brl: Optional[float] = None
    margin_percent: Optional[float] = None
    pricing_status: Optional[str] = None


class AICreditTransactionItem(BaseModel):
    id: int
    transaction_type: str
    amount_credits: float
    balance_after: float
    description: Optional[str] = None
    created_at: datetime
    usage: Optional[AICreditTransactionUsage] = None


class AICreditTransactionsResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[AICreditTransactionItem]


def _build_wallet_summary(wallet: Optional[AICreditWallet]) -> AICreditWalletSummary:
    return AICreditWalletSummary(
        balance_credits=_to_float(wallet.balance_credits if wallet else 0),
        total_granted_credits=_to_float(wallet.total_granted_credits if wallet else 0),
        total_used_credits=_to_float(wallet.total_used_credits if wallet else 0),
        currency=(wallet.currency if wallet else "internal_credit"),
        status=(wallet.status if wallet else "active"),
        updated_at=(wallet.updated_at if wallet else None),
    )


def _transaction_usage_from_metadata(transaction: AICreditTransaction) -> Optional[AICreditTransactionUsage]:
    metadata = transaction.transaction_metadata or {}
    if transaction.transaction_type != "debit":
        return None
    if not metadata:
        return None

    return AICreditTransactionUsage(
        provider=metadata.get("provider"),
        operation=metadata.get("operation"),
        status=metadata.get("status"),
        model=metadata.get("model"),
        estimated_cost_usd=_to_float(metadata.get("estimated_cost_usd")) if metadata.get("estimated_cost_usd") is not None else None,
        estimated_cost_brl=_to_float(metadata.get("estimated_cost_brl")) if metadata.get("estimated_cost_brl") is not None else None,
        revenue_brl=_to_float(metadata.get("revenue_brl")) if metadata.get("revenue_brl") is not None else None,
        gross_profit_brl=_to_float(metadata.get("gross_profit_brl")) if metadata.get("gross_profit_brl") is not None else None,
        margin_percent=_to_float(metadata.get("margin_percent")) if metadata.get("margin_percent") is not None else None,
        pricing_status=metadata.get("pricing_status"),
    )


def _build_transaction_item(transaction: AICreditTransaction) -> AICreditTransactionItem:
    event = transaction.usage_event
    usage = None
    if event:
        usage = AICreditTransactionUsage(
            provider=event.provider,
            operation=event.operation,
            status=event.status,
            model=event.model,
            agent_name=event.agent_name,
            phone_masked=_mask_phone(event.phone),
            total_tokens=event.total_tokens,
            text_characters=event.text_characters,
            provider_usage_units=_to_float(event.provider_usage_units),
            estimated_cost_usd=_to_float(event.estimated_cost_usd) if event.estimated_cost_usd is not None else None,
            estimated_cost_brl=_to_float(event.estimated_cost_brl) if event.estimated_cost_brl is not None else None,
            revenue_brl=_to_float(event.revenue_brl) if event.revenue_brl is not None else None,
            gross_profit_brl=_to_float(event.gross_profit_brl) if event.gross_profit_brl is not None else None,
            margin_percent=_to_float(event.margin_percent) if event.margin_percent is not None else None,
            pricing_status=(event.pricing_snapshot or {}).get("pricing_status"),
        )
    else:
        usage = _transaction_usage_from_metadata(transaction)

    return AICreditTransactionItem(
        id=int(transaction.id),
        transaction_type=transaction.transaction_type,
        amount_credits=_to_float(transaction.amount_credits),
        balance_after=_to_float(transaction.balance_after),
        description=transaction.description,
        created_at=transaction.created_at,
        usage=usage,
    )


@router.get("/summary", response_model=AICreditSummaryResponse)
def get_ai_credit_summary(
    period_days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user),
) -> AICreditSummaryResponse:
    company_id = _company_id_from_user(user)
    now = datetime.now(timezone.utc)
    today_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    start = _period_start(period_days)

    wallet = (
        db.query(AICreditWallet)
        .filter(AICreditWallet.company_id == company_id)
        .one_or_none()
    )

    period_row = (
        db.query(
            func.coalesce(func.sum(AIUsageEvent.internal_credits_charged), Decimal("0")).label("period_credits"),
            func.coalesce(func.sum(AIUsageEvent.estimated_cost_usd), Decimal("0")).label("estimated_cost_usd"),
            func.coalesce(func.sum(AIUsageEvent.estimated_cost_brl), Decimal("0")).label("estimated_cost_brl"),
            func.coalesce(func.sum(AIUsageEvent.revenue_brl), Decimal("0")).label("revenue_brl"),
            func.coalesce(func.sum(AIUsageEvent.gross_profit_brl), Decimal("0")).label("gross_profit_brl"),
            func.coalesce(func.sum(case((AIUsageEvent.operation == "llm_response", AIUsageEvent.internal_credits_charged), else_=0)), Decimal("0")).label("text_credits"),
            func.coalesce(func.sum(case((AIUsageEvent.operation == "tts", AIUsageEvent.internal_credits_charged), else_=0)), Decimal("0")).label("audio_credits"),
            func.coalesce(func.sum(AIUsageEvent.total_tokens), 0).label("text_tokens"),
            func.coalesce(func.sum(AIUsageEvent.text_characters), 0).label("audio_characters"),
            func.count(AIUsageEvent.id).label("success_events"),
            func.coalesce(func.sum(case((AIUsageEvent.estimated_cost_usd.is_(None), 1), else_=0)), 0).label("unpriced_events"),
            func.coalesce(func.sum(case((AIUsageEvent.gross_profit_brl < 0, 1), else_=0)), 0).label("negative_profit_events"),
        )
        .filter(
            AIUsageEvent.company_id == company_id,
            AIUsageEvent.status == "success",
            AIUsageEvent.created_at >= start,
        )
        .one()
    )

    today_credits = (
        db.query(func.coalesce(func.sum(AIUsageEvent.internal_credits_charged), Decimal("0")))
        .filter(
            AIUsageEvent.company_id == company_id,
            AIUsageEvent.status == "success",
            AIUsageEvent.created_at >= today_start,
        )
        .scalar()
    )
    month_credits = (
        db.query(func.coalesce(func.sum(AIUsageEvent.internal_credits_charged), Decimal("0")))
        .filter(
            AIUsageEvent.company_id == company_id,
            AIUsageEvent.status == "success",
            AIUsageEvent.created_at >= month_start,
        )
        .scalar()
    )
    failed_events = (
        db.query(func.count(AIUsageEvent.id))
        .filter(
            AIUsageEvent.company_id == company_id,
            AIUsageEvent.status == "failed",
            AIUsageEvent.created_at >= start,
        )
        .scalar()
    )
    last_event_at = (
        db.query(func.max(AIUsageEvent.created_at))
        .filter(AIUsageEvent.company_id == company_id)
        .scalar()
    )
    revenue_brl = Decimal(str(period_row.revenue_brl or 0))
    gross_profit_brl = Decimal(str(period_row.gross_profit_brl or 0))
    margin_percent = None
    if revenue_brl > 0:
        margin_percent = float((gross_profit_brl / revenue_brl * Decimal("100")).quantize(Decimal("0.0001")))

    return AICreditSummaryResponse(
        wallet=_build_wallet_summary(wallet),
        usage=AICreditUsageSummary(
            period_days=period_days,
            today_credits=_to_float(today_credits),
            period_credits=_to_float(period_row.period_credits),
            month_credits=_to_float(month_credits),
            estimated_cost_usd=_to_float(period_row.estimated_cost_usd),
            estimated_cost_brl=_to_float(period_row.estimated_cost_brl),
            revenue_brl=_to_float(period_row.revenue_brl),
            gross_profit_brl=_to_float(period_row.gross_profit_brl),
            margin_percent=margin_percent,
            text_credits=_to_float(period_row.text_credits),
            audio_credits=_to_float(period_row.audio_credits),
            text_tokens=_to_int(period_row.text_tokens),
            audio_characters=_to_int(period_row.audio_characters),
            success_events=_to_int(period_row.success_events),
            failed_events=_to_int(failed_events),
            unpriced_events=_to_int(period_row.unpriced_events),
            negative_profit_events=_to_int(period_row.negative_profit_events),
            last_event_at=last_event_at,
        ),
    )


@router.get("/usage", response_model=AICreditUsageResponse)
def get_ai_credit_usage(
    period_days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user),
) -> AICreditUsageResponse:
    company_id = _company_id_from_user(user)
    start = _period_start(period_days)
    day_expr = func.date_trunc("day", AIUsageEvent.created_at).label("day")

    rows = (
        db.query(
            day_expr,
            func.coalesce(func.sum(case((AIUsageEvent.operation == "llm_response", AIUsageEvent.internal_credits_charged), else_=0)), Decimal("0")).label("text_credits"),
            func.coalesce(func.sum(case((AIUsageEvent.operation == "tts", AIUsageEvent.internal_credits_charged), else_=0)), Decimal("0")).label("audio_credits"),
            func.coalesce(func.sum(AIUsageEvent.estimated_cost_brl), Decimal("0")).label("estimated_cost_brl"),
            func.coalesce(func.sum(AIUsageEvent.revenue_brl), Decimal("0")).label("revenue_brl"),
            func.coalesce(func.sum(AIUsageEvent.gross_profit_brl), Decimal("0")).label("gross_profit_brl"),
            func.coalesce(func.sum(AIUsageEvent.total_tokens), 0).label("text_tokens"),
            func.coalesce(func.sum(AIUsageEvent.text_characters), 0).label("audio_characters"),
        )
        .filter(
            AIUsageEvent.company_id == company_id,
            AIUsageEvent.status == "success",
            AIUsageEvent.created_at >= start,
        )
        .group_by(day_expr)
        .order_by(day_expr)
        .all()
    )

    by_date = {}
    for row in rows:
        day = row.day.date().isoformat()
        text_credits = _to_float(row.text_credits)
        audio_credits = _to_float(row.audio_credits)
        by_date[day] = AICreditUsagePoint(
            date=day,
            text_credits=text_credits,
            audio_credits=audio_credits,
            total_credits=text_credits + audio_credits,
            estimated_cost_brl=_to_float(row.estimated_cost_brl),
            revenue_brl=_to_float(row.revenue_brl),
            gross_profit_brl=_to_float(row.gross_profit_brl),
            text_tokens=_to_int(row.text_tokens),
            audio_characters=_to_int(row.audio_characters),
        )

    start_date = start.date()
    series = [
        by_date.get(
            (start_date + timedelta(days=offset)).isoformat(),
            AICreditUsagePoint(
                date=(start_date + timedelta(days=offset)).isoformat(),
                text_credits=0,
                audio_credits=0,
                total_credits=0,
                estimated_cost_brl=0,
                revenue_brl=0,
                gross_profit_brl=0,
                text_tokens=0,
                audio_characters=0,
            ),
        )
        for offset in range(period_days)
    ]

    return AICreditUsageResponse(period_days=period_days, series=series)


@router.get("/transactions", response_model=AICreditTransactionsResponse)
def get_ai_credit_transactions(
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    transaction_type: Optional[str] = Query(None, pattern="^(debit|credit|refund|adjustment)$"),
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user),
) -> AICreditTransactionsResponse:
    company_id = _company_id_from_user(user)
    query = (
        db.query(AICreditTransaction)
        .options(joinedload(AICreditTransaction.usage_event))
        .filter(AICreditTransaction.company_id == company_id)
    )
    if transaction_type:
        query = query.filter(AICreditTransaction.transaction_type == transaction_type)

    total = query.count()
    transactions = (
        query.order_by(AICreditTransaction.created_at.desc(), AICreditTransaction.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    items: List[AICreditTransactionItem] = []
    for transaction in transactions:
        items.append(_build_transaction_item(transaction))

    return AICreditTransactionsResponse(total=total, limit=limit, offset=offset, items=items)
