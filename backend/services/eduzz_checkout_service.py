"""Eduzz Checkout Sun integration for prepaid AI credits."""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, Mapping, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

from backend.services.account_profile_service import clean_text, only_digits
from backend.runtime_settings import APP_NAME, PUBLIC_APP_URL, app_slug


EDUZZ_API_BASE_URL = "https://api.eduzz.com"


class EduzzConfigurationError(RuntimeError):
    """Raised when Eduzz checkout cannot run due missing environment config."""


class EduzzAPIError(RuntimeError):
    """Raised when Eduzz rejects or fails a checkout request."""

    def __init__(self, message: str, *, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class EduzzCheckoutConfig:
    access_token: str
    product_id: str
    webhook_secret: str
    api_base_url: str
    public_app_origin: str
    postback_url: str
    return_url_base: str
    timeout_seconds: int


@dataclass(frozen=True)
class EduzzCartResult:
    payment_url: str
    eduzz_cart_id: Optional[str]
    eduzz_cart_key: Optional[str]
    request_payload: Dict[str, Any]
    response_payload: Dict[str, Any]


def _clean_url(value: str) -> str:
    return value.strip().strip("\"'").rstrip("/")


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value or not value.strip():
        raise EduzzConfigurationError(f"{name} não configurada")
    return value.strip()


def _optional_origin() -> str:
    return _clean_url(
        os.getenv("EDUZZ_PUBLIC_APP_URL")
        or os.getenv("PUBLIC_APP_URL")
        or os.getenv("PUBLIC_BASE_URL")
        or PUBLIC_APP_URL
    )


def get_eduzz_checkout_config() -> EduzzCheckoutConfig:
    access_token = _required_env("EDUZZ_ACCESS_TOKEN")
    product_id = _required_env("EDUZZ_AI_CREDIT_PRODUCT_ID")
    webhook_secret = _required_env("EDUZZ_WEBHOOK_SECRET")
    api_base_url = _clean_url(os.getenv("EDUZZ_API_BASE_URL") or EDUZZ_API_BASE_URL)
    public_origin = _optional_origin()
    postback_url = _clean_url(os.getenv("EDUZZ_POSTBACK_URL") or f"{public_origin}/payments/eduzz/webhook")
    return_url_base = _clean_url(os.getenv("EDUZZ_RETURN_URL") or f"{public_origin}/company/ai-credits")
    timeout_seconds = int(os.getenv("EDUZZ_API_TIMEOUT_SECONDS", "20"))
    return EduzzCheckoutConfig(
        access_token=access_token,
        product_id=product_id,
        webhook_secret=webhook_secret,
        api_base_url=api_base_url,
        public_app_origin=public_origin,
        postback_url=postback_url,
        return_url_base=return_url_base,
        timeout_seconds=timeout_seconds,
    )


def is_eduzz_checkout_configured() -> bool:
    try:
        get_eduzz_checkout_config()
        return True
    except (EduzzConfigurationError, ValueError):
        return False


def is_eduzz_credit_product_configured() -> bool:
    return bool((os.getenv("EDUZZ_ACCESS_TOKEN") or "").strip() and (os.getenv("EDUZZ_AI_CREDIT_PRODUCT_ID") or "").strip())


def _append_query(url: str, params: Mapping[str, Any]) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: str(value) for key, value in params.items() if value is not None})
    return urlunparse(parsed._replace(query=urlencode(query)))


def _price_cents_to_brl(price_cents: int) -> float:
    value = (Decimal(price_cents) / Decimal("100")).quantize(Decimal("0.01"))
    return float(value)


def _safe_customer_name(raw_name: Any) -> str:
    text = str(raw_name or "").strip()
    if not text or "@" in text:
        return "Cliente"

    normalized = "".join(ch if ch.isalpha() or ch.isspace() else " " for ch in text)
    words = [word for word in normalized.split() if len(word) >= 2]
    if len(words) >= 2:
        return " ".join(words[:4]).title()
    if len(words) == 1:
        return f"{words[0].title()} Cliente"
    return "Cliente"


def _customer_payload(user: Any, billing_profile: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    profile = billing_profile or {}
    email = clean_text(profile.get("email") or getattr(user, "email", None), max_length=255)
    name = _safe_customer_name(profile.get("full_name") or getattr(user, "name", None))
    cellphone = only_digits(profile.get("cellphone"))[:13]
    document = only_digits(profile.get("document"))[:14]
    postal_code = only_digits(profile.get("postal_code"))[:8]
    state = clean_text(profile.get("state"), max_length=2).upper()
    payload: Dict[str, Any] = {}
    if email:
        payload["email"] = email
    payload["name"] = name
    if cellphone:
        payload["cellphone"] = cellphone
    if document:
        payload["document"] = document

    address = {
        "street": clean_text(profile.get("street"), max_length=120),
        "number": clean_text(profile.get("number"), max_length=30),
        "neighborhood": clean_text(profile.get("neighborhood"), max_length=80),
        "complement": clean_text(profile.get("complement"), max_length=120),
        "postalCode": postal_code,
        "state": state,
    }
    address = {key: value for key, value in address.items() if value}
    if address:
        payload["address"] = address
    return payload


def build_eduzz_cart_payload(
    *,
    order_id: str,
    package: Any,
    user: Any,
    config: EduzzCheckoutConfig,
    billing_profile: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "orderId": order_id,
        "postbackUrl": config.postback_url,
        "returnUrl": config.return_url_base,
        "installments": 1,
        "items": [
            {
                "productId": str(config.product_id),
                "description": f"{APP_NAME} - Créditos IA - {package.name} ({int(package.credits)} créditos)",
                "price": {
                    "value": _price_cents_to_brl(int(package.price_cents)),
                    "currency": package.currency,
                },
                "quantity": 1,
            }
        ],
    }
    customer = _customer_payload(user, billing_profile=billing_profile)
    if customer:
        payload["customer"] = customer
    return payload


def create_ai_credit_cart(
    *,
    order_id: str,
    package: Any,
    user: Any,
    billing_profile: Optional[Mapping[str, Any]] = None,
) -> EduzzCartResult:
    config = get_eduzz_checkout_config()
    payload = build_eduzz_cart_payload(
        order_id=order_id,
        package=package,
        user=user,
        config=config,
        billing_profile=billing_profile,
    )
    try:
        response = requests.post(
            f"{config.api_base_url}/sun/v1/cart",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {config.access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=config.timeout_seconds,
        )
    except requests.RequestException as exc:
        raise EduzzAPIError("Falha de comunicação com a Eduzz") from exc

    if response.status_code >= 400:
        raise EduzzAPIError("Eduzz recusou a criação do checkout", status_code=response.status_code)

    try:
        body = response.json()
    except ValueError as exc:
        raise EduzzAPIError("Eduzz retornou uma resposta inválida") from exc

    if not isinstance(body, dict):
        raise EduzzAPIError("Eduzz retornou uma resposta inesperada")

    raw_payment_url = body.get("paymentUrl")
    if not raw_payment_url:
        raise EduzzAPIError("Eduzz não retornou URL de pagamento")

    payment_url = _append_query(
        str(raw_payment_url),
        {
            "utm_source": app_slug(),
            "utm_medium": "ai_credits",
            "utm_campaign": package.code,
            "utm_content": order_id,
        },
    )
    response_payload = dict(body)
    response_payload["paymentUrl"] = payment_url
    return EduzzCartResult(
        payment_url=payment_url,
        eduzz_cart_id=str(body.get("id")) if body.get("id") is not None else None,
        eduzz_cart_key=str(body.get("key")) if body.get("key") is not None else None,
        request_payload=payload,
        response_payload=response_payload,
    )


def verify_eduzz_signature(*, raw_body: bytes, signature: Optional[str]) -> bool:
    config = get_eduzz_checkout_config()
    if not signature:
        return False
    expected = hmac.new(config.webhook_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    normalized = signature.strip()
    if normalized.startswith("sha256="):
        normalized = normalized.split("=", 1)[1]
    return hmac.compare_digest(expected, normalized)


def _first_string(values: Iterable[Any]) -> Optional[str]:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def extract_eduzz_order_id(payload: Mapping[str, Any]) -> Optional[str]:
    data = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(data, Mapping):
        data = {}

    direct = _first_string(
        [
            payload.get("orderId"),
            payload.get("order_id"),
            data.get("orderId"),
            data.get("order_id"),
        ]
    )
    if direct:
        return direct

    for tracker_key in ("tracker", "tracking", "utm"):
        tracker = data.get(tracker_key)
        if isinstance(tracker, Mapping):
            tracked = _first_string(
                [
                    tracker.get("utmContent"),
                    tracker.get("utm_content"),
                    tracker.get("content"),
                    tracker.get("code1"),
                    tracker.get("code2"),
                    tracker.get("code3"),
                ]
            )
            if tracked:
                return tracked

    items = data.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, Mapping):
                sku_reference = _first_string([item.get("skuReference"), item.get("sku_reference")])
                if sku_reference:
                    return sku_reference

    checkout_url = _first_string([data.get("checkoutUrl"), data.get("checkout_url")])
    if checkout_url:
        try:
            query = dict(parse_qsl(urlparse(checkout_url).query, keep_blank_values=True))
        except ValueError:
            query = {}
        tracked = _first_string(
            [
                query.get("utm_content"),
                query.get("utmContent"),
                query.get("code1"),
                query.get("order_id"),
                query.get("orderId"),
            ]
        )
        if tracked:
            return tracked

    return None


def _money_value_to_cents(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except Exception:
        return None
    return int((amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _extract_money_cents(payload: Mapping[str, Any]) -> Optional[int]:
    data = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(data, Mapping):
        return None

    for key in ("paid", "price"):
        money = data.get(key)
        if isinstance(money, Mapping):
            cents = _money_value_to_cents(money.get("value"))
            if cents is not None:
                return cents

    items = data.get("items")
    if isinstance(items, list):
        total = 0
        found = False
        for item in items:
            if not isinstance(item, Mapping):
                continue
            price = item.get("price")
            if not isinstance(price, Mapping):
                continue
            cents = _money_value_to_cents(price.get("value"))
            if cents is None:
                continue
            total += cents
            found = True
        if found:
            return total
    return None


def _extract_product_ids(payload: Mapping[str, Any]) -> set[str]:
    data = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(data, Mapping):
        return set()
    ids: set[str] = set()
    raw_ids = data.get("productId")
    if isinstance(raw_ids, list):
        ids.update(str(item) for item in raw_ids if item is not None)
    elif raw_ids is not None:
        ids.add(str(raw_ids))

    items = data.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, Mapping) and item.get("productId") is not None:
                ids.add(str(item.get("productId")))
    return ids


def validate_paid_invoice_for_purchase(*, payload: Mapping[str, Any], expected_product_id: str, expected_price_cents: int) -> tuple[bool, str]:
    product_ids = _extract_product_ids(payload)
    if product_ids and str(expected_product_id) not in product_ids:
        return False, "product_mismatch"

    paid_cents = _extract_money_cents(payload)
    if paid_cents is not None and paid_cents != int(expected_price_cents):
        return False, "price_mismatch"

    return True, "ok"
