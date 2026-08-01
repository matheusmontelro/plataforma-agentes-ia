"""Eduzz purchase verification used to gate public account registration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional

import requests

from backend.services.account_profile_service import clean_text
from backend.services.eduzz_checkout_service import EDUZZ_API_BASE_URL, EduzzAPIError, EduzzConfigurationError


@dataclass(frozen=True)
class EduzzRegistrationConfig:
    access_token: str
    product_ids: tuple[str, ...]
    api_base_url: str
    lookback_days: int
    timeout_seconds: int


@dataclass(frozen=True)
class EduzzRegistrationVerification:
    allowed: bool
    product_id: Optional[str] = None
    sale_id: Optional[str] = None


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value or not value.strip():
        raise EduzzConfigurationError(f"{name} não configurada")
    return value.strip()


def _parse_product_ids(raw: str) -> tuple[str, ...]:
    product_ids = tuple(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))
    if not product_ids:
        raise EduzzConfigurationError("EDUZZ_REGISTRATION_PRODUCT_IDS não configurada")
    return product_ids


def get_eduzz_registration_config() -> EduzzRegistrationConfig:
    return EduzzRegistrationConfig(
        access_token=_required_env("EDUZZ_ACCESS_TOKEN"),
        product_ids=_parse_product_ids(_required_env("EDUZZ_REGISTRATION_PRODUCT_IDS")),
        api_base_url=(os.getenv("EDUZZ_API_BASE_URL") or EDUZZ_API_BASE_URL).strip().strip("\"'").rstrip("/"),
        lookback_days=max(1, int(os.getenv("EDUZZ_REGISTRATION_LOOKBACK_DAYS", "730"))),
        timeout_seconds=max(1, int(os.getenv("EDUZZ_API_TIMEOUT_SECONDS", "20"))),
    )


def _iso_date(value: datetime) -> str:
    return value.astimezone(timezone.utc).date().isoformat()


def _iter_sales_items(body: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    items = body.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, Mapping):
                yield item


def _first_sale_id(body: Mapping[str, Any]) -> Optional[str]:
    for item in _iter_sales_items(body):
        sale_id = item.get("id")
        if sale_id is not None:
            return str(sale_id)
    return None


def _has_paid_sale(body: Mapping[str, Any]) -> bool:
    total_items = body.get("totalItems")
    if isinstance(total_items, int) and total_items > 0:
        return True
    if isinstance(total_items, str) and total_items.isdigit() and int(total_items) > 0:
        return True

    for item in _iter_sales_items(body):
        status = clean_text(item.get("status"), max_length=40).lower()
        if not status or status == "paid":
            return True
    return False


def verify_registration_purchase(email: str, *, now: Optional[datetime] = None) -> EduzzRegistrationVerification:
    config = get_eduzz_registration_config()
    buyer_email = clean_text(email, max_length=255).lower()
    if not buyer_email:
        return EduzzRegistrationVerification(allowed=False)

    end_date = now or datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=config.lookback_days)
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {config.access_token}",
    }

    for product_id in config.product_ids:
        try:
            response = requests.get(
                f"{config.api_base_url}/myeduzz/v1/sales",
                headers=headers,
                params={
                    "page": 1,
                    "itemsPerPage": 5,
                    "startDate": _iso_date(start_date),
                    "endDate": _iso_date(end_date),
                    "referenceDate": "paidAt",
                    "status": "paid",
                    "productId": product_id,
                    "buyerEmail": buyer_email,
                },
                timeout=config.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise EduzzAPIError("Falha de comunicação ao validar compra") from exc

        if response.status_code >= 400:
            raise EduzzAPIError("Eduzz recusou a validação de compra", status_code=response.status_code)

        try:
            body = response.json()
        except ValueError as exc:
            raise EduzzAPIError("Eduzz retornou validação de compra inválida") from exc

        if not isinstance(body, Mapping):
            raise EduzzAPIError("Eduzz retornou validação de compra inesperada")

        if _has_paid_sale(body):
            return EduzzRegistrationVerification(
                allowed=True,
                product_id=product_id,
                sale_id=_first_sale_id(body),
            )

    return EduzzRegistrationVerification(allowed=False)
