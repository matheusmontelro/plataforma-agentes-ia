"""Public Eduzz payment/delivery callbacks."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.models import AICreditPurchase, AICreditTransaction, AICreditWallet, Client
from backend.services.brevo_email_service import send_ai_credit_purchase_email
from backend.services.eduzz_checkout_service import (
    EduzzConfigurationError,
    extract_eduzz_order_id,
    validate_paid_invoice_for_purchase,
    verify_eduzz_signature,
)


router = APIRouter(prefix="/eduzz", tags=["eduzz-payments"])
logger = logging.getLogger(__name__)
CREDIT_QUANT = Decimal("0.000001")


def _delivery_validation_payload(method: str) -> dict[str, object]:
    return {
        "status": "ok",
        "provider": "eduzz",
        "delivery": True,
        "method": method,
    }


@router.get("/delivery")
async def validate_eduzz_delivery_get(request: Request) -> dict[str, object]:
    """Return 200 so Eduzz can validate the custom delivery URL."""

    return _delivery_validation_payload(request.method)


@router.post("/delivery")
async def validate_eduzz_delivery_post(request: Request) -> dict[str, object]:
    """Accept Eduzz delivery validation POSTs without granting credits."""

    return _delivery_validation_payload(request.method)


@router.head("/delivery")
async def validate_eduzz_delivery_head() -> Response:
    return Response(status_code=200)


def _to_credit_decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(CREDIT_QUANT)


def _get_or_create_wallet(db: Session, company_id: int) -> AICreditWallet:
    wallet = (
        db.query(AICreditWallet)
        .filter(AICreditWallet.company_id == company_id)
        .with_for_update()
        .one_or_none()
    )
    if wallet:
        return wallet

    wallet = AICreditWallet(company_id=company_id)
    db.add(wallet)
    db.flush()
    return wallet


def _nested_text(payload: Mapping[str, Any], *path: str) -> Optional[str]:
    current: Any = payload
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    if current is None:
        return None
    text = str(current).strip()
    return text or None


def _transaction_metadata_from_webhook(
    *,
    payload: Mapping[str, Any],
    purchase: AICreditPurchase,
) -> dict[str, Any]:
    return {
        "source": "eduzz_checkout",
        "provider": "eduzz",
        "order_id": purchase.order_id,
        "package_code": purchase.package_code,
        "package_name": purchase.package_name,
        "credits": str(purchase.credits),
        "price_cents": int(purchase.price_cents),
        "currency": purchase.currency,
        "eduzz_event_id": payload.get("id"),
        "eduzz_invoice_id": _nested_text(payload, "data", "id"),
        "eduzz_transaction_id": _nested_text(payload, "data", "transaction", "id"),
        "eduzz_payment_method": _nested_text(payload, "data", "paymentMethod")
        or _nested_text(payload, "data", "payment", "method"),
    }


def _format_credit_amount(value: Any) -> str:
    amount = _to_credit_decimal(value)
    normalized = amount.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _format_money_from_cents(price_cents: int, currency: str) -> str:
    value = Decimal(int(price_cents)) / Decimal("100")
    formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if currency.upper() == "BRL":
        return f"R$ {formatted}"
    return f"{formatted} {currency.upper()}"


def _purchase_recipient(db: Session, purchase: AICreditPurchase) -> tuple[Optional[str], Optional[str]]:
    metadata = purchase.purchase_metadata or {}
    actor_email = str(metadata.get("actor_email") or "").strip()
    client = db.query(Client).filter(Client.company_id == purchase.company_id).order_by(Client.id.asc()).first()

    if client:
        profile = getattr(client, "billing_profile", None) or {}
        email = str(profile.get("email") or client.email or actor_email or "").strip()
        name = str(profile.get("full_name") or getattr(client, "email", "") or "").strip()
        return email or None, name or None

    return actor_email or None, actor_email or None


def _send_ai_credit_purchase_email_best_effort(
    *,
    db: Session,
    purchase: AICreditPurchase,
    wallet: AICreditWallet,
) -> dict[str, Any]:
    to_email, to_name = _purchase_recipient(db, purchase)
    if not to_email:
        return {"sent": False, "skipped": True, "reason": "missing_recipient"}

    company_name = purchase.company.name if purchase.company else None
    try:
        result = send_ai_credit_purchase_email(
            to_email=to_email,
            to_name=to_name,
            company_name=company_name,
            package_name=purchase.package_name,
            credits=_format_credit_amount(purchase.credits),
            price=_format_money_from_cents(int(purchase.price_cents), purchase.currency),
            balance_after=_format_credit_amount(wallet.balance_credits),
            order_id=purchase.order_id,
        )
    except Exception as exc:
        logger.warning(
            "[EduzzCredits] Falha inesperada ao enviar email de recarga: order_id=%s erro=%s",
            purchase.order_id,
            exc.__class__.__name__,
        )
        return {"sent": False, "skipped": False, "reason": "unexpected_error"}

    if result.sent:
        logger.info("[EduzzCredits] Email de recarga enviado: order_id=%s", purchase.order_id)
    elif result.skipped:
        logger.info("[EduzzCredits] Email de recarga ignorado: order_id=%s reason=%s", purchase.order_id, result.reason)
    else:
        logger.warning("[EduzzCredits] Email de recarga não enviado: order_id=%s reason=%s", purchase.order_id, result.reason)

    return {
        "sent": result.sent,
        "skipped": result.skipped,
        "reason": result.reason,
        "message_id": result.message_id,
    }


@router.post("/webhook")
async def eduzz_webhook(
    request: Request,
    x_signature: Optional[str] = Header(None, alias="x-signature"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    raw_body = await request.body()
    try:
        if not verify_eduzz_signature(raw_body=raw_body, signature=x_signature):
            raise HTTPException(status_code=401, detail="Assinatura Eduzz inválida")
    except EduzzConfigurationError as exc:
        raise HTTPException(status_code=503, detail="Webhook Eduzz não configurado") from exc

    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Payload Eduzz inválido") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload Eduzz inválido")

    event_name = str(payload.get("event") or "")
    if event_name != "myeduzz.invoice_paid":
        return {"status": "ignored", "reason": "unsupported_event", "event": event_name}

    order_id = extract_eduzz_order_id(payload)
    if not order_id:
        logger.warning("[EduzzCredits] invoice_paid sem order_id rastreável; event_id=%s", payload.get("id"))
        return {"status": "ignored", "reason": "missing_order_id"}

    purchase = (
        db.query(AICreditPurchase)
        .filter(AICreditPurchase.order_id == order_id)
        .with_for_update()
        .one_or_none()
    )
    if not purchase:
        logger.warning("[EduzzCredits] invoice_paid para order_id desconhecido: %s", order_id)
        return {"status": "ignored", "reason": "unknown_order_id"}

    if purchase.status == "credited":
        return {
            "status": "ok",
            "credited": False,
            "idempotent": True,
            "order_id": purchase.order_id,
        }

    valid, reason = validate_paid_invoice_for_purchase(
        payload=payload,
        expected_product_id=str(purchase.provider_product_id),
        expected_price_cents=int(purchase.price_cents),
    )
    if not valid:
        purchase.status = "failed"
        purchase.webhook_payload = payload
        purchase.purchase_metadata = {
            **(purchase.purchase_metadata or {}),
            "failure_reason": reason,
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }
        db.commit()
        logger.warning("[EduzzCredits] invoice_paid recusado: order_id=%s reason=%s", order_id, reason)
        return {"status": "ignored", "reason": reason, "order_id": purchase.order_id}

    wallet = _get_or_create_wallet(db, int(purchase.company_id))
    credits = _to_credit_decimal(purchase.credits)
    current_balance = _to_credit_decimal(wallet.balance_credits)
    current_granted = _to_credit_decimal(wallet.total_granted_credits)
    wallet.balance_credits = _to_credit_decimal(current_balance + credits)
    wallet.total_granted_credits = _to_credit_decimal(current_granted + credits)

    transaction = AICreditTransaction(
        company_id=purchase.company_id,
        wallet_id=wallet.id,
        transaction_type="credit",
        amount_credits=credits,
        balance_after=wallet.balance_credits,
        description=f"Recarga Eduzz: pacote {purchase.package_name}",
        transaction_metadata=_transaction_metadata_from_webhook(payload=payload, purchase=purchase),
    )
    db.add(transaction)
    db.flush()

    purchase.status = "credited"
    purchase.webhook_payload = payload
    purchase.eduzz_webhook_event_id = str(payload.get("id")) if payload.get("id") is not None else None
    purchase.eduzz_invoice_id = _nested_text(payload, "data", "id")
    purchase.eduzz_transaction_id = _nested_text(payload, "data", "transaction", "id")
    purchase.credited_transaction_id = transaction.id
    purchase.credited_at = datetime.now(timezone.utc)
    purchase.purchase_metadata = {
        **(purchase.purchase_metadata or {}),
        "credited_by": "eduzz_webhook",
    }
    db.commit()
    db.refresh(purchase)
    db.refresh(wallet)

    email_result = _send_ai_credit_purchase_email_best_effort(db=db, purchase=purchase, wallet=wallet)
    purchase.purchase_metadata = {
        **(purchase.purchase_metadata or {}),
        "credited_email": email_result,
    }
    db.commit()

    return {
        "status": "success",
        "credited": True,
        "order_id": purchase.order_id,
        "transaction_id": transaction.id,
    }
