"""Loopback-only contract for upstream commerce refund access events."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import secrets
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Literal, TypeVar

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from backend.db import SessionLocal, mark_session_with_transaction_lock_timeout
from backend.services.refund_access_service import (
    REFUND_ACCESS_LOCK_TIMEOUT_MAX_MS,
    REFUND_ACCESS_LOCK_TIMEOUT_MIN_MS,
    REFUND_ACCESS_LOCK_TIMEOUT_MS_INFO_KEY,
    RefundAccessCommand,
    RefundAccessError,
    process_refund_access,
)
from backend.ws_manager import manager


router = APIRouter(prefix="/internal", tags=["internal-refund-access"])

_T = TypeVar("_T")


class RefundAccessExecutorBusyError(RuntimeError):
    """The bounded refund lane is full; callers should retry later."""

    retry_after_seconds = 2

    def __init__(self):
        super().__init__("refund_access_executor_busy")


def _refund_executor_worker_count() -> int:
    """Keep blocking refund locks isolated without creating unbounded capacity."""
    raw_value = os.getenv("REFUND_ACCESS_EXECUTOR_WORKERS", "2").strip()
    try:
        configured = int(raw_value)
    except ValueError:
        configured = 2
    return max(1, min(configured, 2))


def _refund_lock_timeout_ms() -> int:
    raw_value = os.getenv("REFUND_ACCESS_INTERNAL_LOCK_TIMEOUT_MS", "1000").strip()
    try:
        configured = int(raw_value)
    except ValueError:
        configured = 1_000
    return max(
        REFUND_ACCESS_LOCK_TIMEOUT_MIN_MS,
        min(configured, REFUND_ACCESS_LOCK_TIMEOUT_MAX_MS),
    )


# Refund processing can intentionally wait for PostgreSQL advisory locks.  It
# must not consume Starlette/AnyIO's shared worker tokens, which are also used by
# login and other request handlers needed to make progress during contention.
REFUND_ACCESS_EXECUTOR_WORKERS = _refund_executor_worker_count()
REFUND_ACCESS_INTERNAL_LOCK_TIMEOUT_MS = _refund_lock_timeout_ms()
_REFUND_ACCESS_EXECUTOR = ThreadPoolExecutor(
    max_workers=REFUND_ACCESS_EXECUTOR_WORKERS,
    thread_name_prefix="refund-access",
)
_REFUND_ACCESS_ADMISSION = threading.BoundedSemaphore(
    REFUND_ACCESS_EXECUTOR_WORKERS
)
_REFUND_ACCESS_EXECUTOR_STOPPING = False


async def _run_in_refund_executor(operation: Callable[[], _T]) -> _T:
    if (
        _REFUND_ACCESS_EXECUTOR_STOPPING
        or not _REFUND_ACCESS_ADMISSION.acquire(blocking=False)
    ):
        raise RefundAccessExecutorBusyError()

    loop = asyncio.get_running_loop()
    try:
        future = _REFUND_ACCESS_EXECUTOR.submit(operation)
    except BaseException:
        _REFUND_ACCESS_ADMISSION.release()
        raise

    # Cancellation or client disconnect must not free capacity while the
    # non-cancellable worker is still mutating data. Release only on real exit.
    future.add_done_callback(lambda _done: _REFUND_ACCESS_ADMISSION.release())
    return await asyncio.wrap_future(future, loop=loop)


def shutdown_refund_access_executor() -> None:
    """Reject new refund jobs and cancel work that has not started."""

    global _REFUND_ACCESS_EXECUTOR_STOPPING
    _REFUND_ACCESS_EXECUTOR_STOPPING = True
    _REFUND_ACCESS_EXECUTOR.shutdown(wait=False, cancel_futures=True)


class RefundAccessRequest(BaseModel):
    eventId: str = Field(min_length=1, max_length=255)
    invoiceId: str = Field(min_length=1, max_length=255)
    email: EmailStr
    state: Literal["refund_pending", "refunded", "active"]
    occurredAt: datetime
    source: Literal["eduzz"]


def validate_refund_access_internal_config() -> None:
    environment = os.getenv("ENVIRONMENT", "production").strip().lower()
    configured_key = os.getenv("REFUND_ACCESS_INTERNAL_KEY", "").strip()
    if environment == "production" and len(configured_key) < 32:
        raise RuntimeError(
            "REFUND_ACCESS_INTERNAL_KEY must contain at least 32 characters in production"
        )


def _is_loopback(value: str) -> bool:
    try:
        return ipaddress.ip_address(value.strip()).is_loopback
    except ValueError:
        return False


def _verify_internal_request(
    request: Request,
    supplied_key: str,
) -> None:
    peer = request.client.host if request.client else ""
    forwarded = request.headers.get("x-forwarded-for", "")
    real_ip = request.headers.get("x-real-ip", "")
    forwarded_hops = [part.strip() for part in forwarded.split(",") if part.strip()]
    if (
        not _is_loopback(peer)
        or any(not _is_loopback(value) for value in forwarded_hops)
        or (real_ip and not _is_loopback(real_ip))
    ):
        raise HTTPException(status_code=403, detail="internal_origin_required")

    configured_key = os.getenv("REFUND_ACCESS_INTERNAL_KEY", "").strip()
    if not configured_key:
        raise HTTPException(status_code=503, detail="internal_refund_access_not_configured")
    if not supplied_key or not secrets.compare_digest(configured_key, supplied_key):
        raise HTTPException(status_code=401, detail="invalid_internal_service_key")


@router.post("/refund-access")
async def refund_access(
    payload: RefundAccessRequest,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    internal_key: str = Header(..., alias="X-Internal-Service-Key"),
):
    _verify_internal_request(request, internal_key)
    company_ids = []
    client_ids = []
    user_ids = []
    command = RefundAccessCommand(
        event_id=payload.eventId,
        idempotency_key=idempotency_key,
        invoice_id=payload.invoiceId,
        email=str(payload.email),
        state=payload.state,
        occurred_at=payload.occurredAt,
        source=payload.source,
    )

    def _process_in_worker():
        db = SessionLocal()
        try:
            # Bound both the refund data transaction and its dedicated advisory
            # lock connection. This deliberately does not mark the session as a
            # generic web request or alter Celery worker behavior.
            mark_session_with_transaction_lock_timeout(
                db,
                REFUND_ACCESS_INTERNAL_LOCK_TIMEOUT_MS,
            )
            return process_refund_access(db, command)
        finally:
            db.close()

    try:
        result = await _run_in_refund_executor(_process_in_worker)
        company_ids = list(result.company_ids)
        client_ids = list(result.client_ids)
        user_ids = list(result.user_ids)
    except RefundAccessExecutorBusyError as exc:
        raise HTTPException(
            status_code=503,
            detail="refund_access_busy",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from None
    except RefundAccessError as exc:
        company_ids = list(exc.company_ids)
        client_ids = list(exc.client_ids)
        user_ids = list(exc.user_ids)
        if company_ids or client_ids or user_ids:
            await manager.publish_access_revocation(
                company_ids,
                client_ids=client_ids,
                user_ids=user_ids,
            )
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc

    if (
        result.state in {"refund_pending", "refunded"}
        and (company_ids or client_ids or user_ids)
    ):
        await manager.publish_access_revocation(
            company_ids,
            client_ids=client_ids,
            user_ids=user_ids,
        )
    return result.as_payload()
