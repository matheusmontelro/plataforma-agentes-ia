"""Fail-closed operational gates shared by HTTP and worker execution paths."""

from __future__ import annotations

import hashlib
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Iterator, Optional, Tuple

from sqlalchemy import and_, exists, func, or_, text
from sqlalchemy.orm import Session

from backend.models import (
    Client,
    Company,
    RefundAccessEvent,
    RefundAccessSuspension,
    User,
)


def _env_nonnegative_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return max(0, int(default))


ACTIVE_OPERATIONAL_STATUS = "active"
BLOCKED_OPERATIONAL_STATUSES = frozenset({"refund_pending", "refunded"})
REFUND_IDENTITY_OPERATION_RETRY_AFTER_SECONDS = max(
    1,
    _env_nonnegative_int("REFUND_IDENTITY_OPERATION_RETRY_AFTER_SECONDS", 2),
)


class CompanyOperationallyBlockedError(RuntimeError):
    def __init__(self, company_id: int, status: str):
        super().__init__(f"company_operationally_blocked:{status}")
        self.company_id = int(company_id)
        self.status = status


class CompanyOperationalLockBusyError(RuntimeError):
    """Transient company-fence contention that must be retried off-request."""

    def __init__(self, company_id: int):
        super().__init__("company_operational_lock_busy")
        self.company_id = int(company_id)
        self.retry_after_seconds = (
            REFUND_IDENTITY_OPERATION_RETRY_AFTER_SECONDS
        )


class AccountEmailCollisionError(RuntimeError):
    pass


class RefundIdentityOperationBusyError(RuntimeError):
    """Transient identity-lock contention in a user-driven operation."""

    def __init__(self, reason: str):
        super().__init__(f"refund_identity_operation_busy:{reason}")
        self.reason = reason
        self.retry_after_seconds = REFUND_IDENTITY_OPERATION_RETRY_AFTER_SECONDS


@dataclass(frozen=True)
class AccountEmailIdentity:
    normalized_email: str
    client: Optional[Client]
    user: Optional[User]


@dataclass
class RefundIdentityOperationReservation:
    """A process-local capacity slot reserved before any Session query."""

    _guard: Optional["_IdentityOperationGuard"]
    _active: bool


@dataclass
class _LocalIdentityLockEntry:
    lock: threading.Lock
    references: int = 0


class _IdentityOperationGuard:
    """Bound user-driven identity locks without consuming the whole DB pool."""

    def __init__(self, capacity_limit: int):
        self.capacity_limit = max(0, int(capacity_limit))
        self._capacity = threading.BoundedSemaphore(self.capacity_limit)
        self._capacity_state_lock = threading.Lock()
        self._capacity_in_use = 0
        self._local_locks_guard = threading.Lock()
        self._local_locks: dict[str, _LocalIdentityLockEntry] = {}

    @property
    def capacity_in_use(self) -> int:
        with self._capacity_state_lock:
            return self._capacity_in_use

    @property
    def local_lock_count(self) -> int:
        with self._local_locks_guard:
            return len(self._local_locks)

    @contextmanager
    def local_lock(self, key: str) -> Iterator[None]:
        with self._local_locks_guard:
            entry = self._local_locks.get(key)
            if entry is None:
                entry = _LocalIdentityLockEntry(lock=threading.Lock())
                self._local_locks[key] = entry
            entry.references += 1

        acquired = entry.lock.acquire(blocking=False)
        if not acquired:
            self._release_local_reference(key, entry)
            raise RefundIdentityOperationBusyError("local_identity")

        try:
            yield
        finally:
            entry.lock.release()
            self._release_local_reference(key, entry)

    def _release_local_reference(
        self,
        key: str,
        entry: _LocalIdentityLockEntry,
    ) -> None:
        with self._local_locks_guard:
            entry.references -= 1
            if entry.references == 0 and not entry.lock.locked():
                self._local_locks.pop(key, None)

    @contextmanager
    def reserve_capacity(self) -> Iterator[RefundIdentityOperationReservation]:
        if not self._capacity.acquire(blocking=False):
            raise RefundIdentityOperationBusyError("capacity")

        with self._capacity_state_lock:
            self._capacity_in_use += 1
        reservation = RefundIdentityOperationReservation(
            _guard=self,
            _active=True,
        )
        try:
            yield reservation
        finally:
            reservation._active = False
            with self._capacity_state_lock:
                self._capacity_in_use -= 1
            self._capacity.release()

    @contextmanager
    def reuse_or_reserve_capacity(
        self,
        reservation: Optional[RefundIdentityOperationReservation],
    ) -> Iterator[None]:
        if reservation is not None:
            if reservation._guard is not self or not reservation._active:
                raise RuntimeError("invalid_refund_identity_operation_reservation")
            yield
            return

        with self.reserve_capacity():
            yield


def _calculate_identity_operation_capacity(
    *,
    pool_capacity: int,
    pool_headroom: int,
    configured_max: int,
    connections_per_operation: int = 2,
) -> int:
    """Return safe slots after reserving pool headroom for normal traffic."""
    connection_cost = max(1, int(connections_per_operation))
    available_connections = max(
        0,
        int(pool_capacity) - max(0, int(pool_headroom)),
    )
    return min(
        max(0, int(configured_max)),
        available_connections // connection_cost,
    )


_IDENTITY_OPERATION_POOL_CAPACITY = (
    _env_nonnegative_int("DB_POOL_SIZE", 50)
    + _env_nonnegative_int("DB_MAX_OVERFLOW", 50)
)
_IDENTITY_OPERATION_CAPACITY = _calculate_identity_operation_capacity(
    pool_capacity=_IDENTITY_OPERATION_POOL_CAPACITY,
    pool_headroom=_env_nonnegative_int(
        "REFUND_IDENTITY_OPERATION_POOL_HEADROOM",
        20,
    ),
    configured_max=_env_nonnegative_int(
        "REFUND_IDENTITY_OPERATION_MAX_CONCURRENCY",
        4,
    ),
)
_REFUND_IDENTITY_OPERATION_GUARD = _IdentityOperationGuard(
    _IDENTITY_OPERATION_CAPACITY
)


def normalize_account_email(email: str) -> str:
    return str(email or "").strip().casefold()


def _is_web_request_session(db: Session) -> bool:
    """Return whether ``get_db`` marked this as request-owned work."""
    info = getattr(db, "info", None)
    return bool(
        isinstance(info, dict)
        and info.get("agentive_web_request")
    )


def get_company_operational_status(db: Session, company_id: int) -> Optional[str]:
    return (
        db.query(Company.operational_status)
        .filter(Company.id == int(company_id))
        .scalar()
    )


def get_company_operational_epoch(db: Session, company_id: int) -> Optional[int]:
    value = (
        db.query(Company.operational_epoch)
        .filter(Company.id == int(company_id))
        .scalar()
    )
    return int(value) if value is not None else None


def is_company_operational(db: Session, company_id: int) -> bool:
    return get_company_operational_status(db, company_id) == ACTIVE_OPERATIONAL_STATUS


def ensure_company_operational(db: Session, company_id: int) -> None:
    status = get_company_operational_status(db, company_id)
    if status != ACTIVE_OPERATIONAL_STATUS:
        raise CompanyOperationallyBlockedError(
            company_id=int(company_id),
            status=status or "not_found",
        )


def is_refund_suspension_superseded(
    db: Session,
    suspension: RefundAccessSuspension,
    *,
    provisional_active_invoice_id: Optional[str] = None,
    provisional_active_occurred_at: Optional[Any] = None,
    provisional_active_is_entitlement: bool = False,
    provisional_active_email_hash: Optional[str] = None,
    provisional_active_root_client_id: Optional[int] = None,
) -> bool:
    """Whether a newer paid entitlement from another invoice supersedes a block."""
    if suspension.state != "refunded":
        return False
    provisional_at = provisional_active_occurred_at
    blocked_at = suspension.latest_occurred_at
    if isinstance(provisional_at, datetime) and provisional_at.tzinfo is None:
        provisional_at = provisional_at.replace(tzinfo=timezone.utc)
    if isinstance(blocked_at, datetime) and blocked_at.tzinfo is None:
        blocked_at = blocked_at.replace(tzinfo=timezone.utc)
    provisional_identity_matches = bool(
        provisional_active_email_hash
        and provisional_active_email_hash == suspension.email_hash
    )
    if (
        not provisional_identity_matches
        and suspension.root_client_id is not None
        and provisional_active_root_client_id is not None
    ):
        provisional_identity_matches = (
            int(suspension.root_client_id)
            == int(provisional_active_root_client_id)
        )
    if (
        provisional_active_is_entitlement
        and provisional_identity_matches
        and provisional_active_invoice_id
        and provisional_active_invoice_id != suspension.invoice_id
        and provisional_at is not None
        and provisional_at > blocked_at
    ):
        return True

    completed_identity_matches = (
        RefundAccessEvent.email_hash == suspension.email_hash
    )
    if suspension.root_client_id is not None:
        completed_identity_matches = or_(
            completed_identity_matches,
            exists().where(
                and_(
                    RefundAccessSuspension.id
                    == RefundAccessEvent.suspension_id,
                    RefundAccessSuspension.root_client_id
                    == int(suspension.root_client_id),
                )
            ),
        )
    return (
        db.query(RefundAccessEvent.id)
        .filter(
            completed_identity_matches,
            RefundAccessEvent.source == suspension.source,
            RefundAccessEvent.requested_state == "active",
            RefundAccessEvent.status == "completed",
            RefundAccessEvent.response_payload["state"].as_string()
            == "active",
            RefundAccessEvent.response_payload["newEntitlement"].as_boolean()
            == True,
            RefundAccessEvent.invoice_id != suspension.invoice_id,
            RefundAccessEvent.occurred_at > suspension.latest_occurred_at,
        )
        .first()
        is not None
    )


def is_email_hash_refund_blocked(db: Session, email_hash: str) -> bool:
    newer_completed_entitlement = exists().where(
        RefundAccessEvent.email_hash == RefundAccessSuspension.email_hash,
        RefundAccessEvent.source == RefundAccessSuspension.source,
        RefundAccessEvent.requested_state == "active",
        RefundAccessEvent.status == "completed",
        RefundAccessEvent.response_payload["state"].as_string() == "active",
        RefundAccessEvent.response_payload["newEntitlement"].as_boolean()
        == True,
        RefundAccessEvent.invoice_id != RefundAccessSuspension.invoice_id,
        RefundAccessEvent.occurred_at
        > RefundAccessSuspension.latest_occurred_at,
    )
    return (
        db.query(RefundAccessSuspension.id)
        .filter(
            RefundAccessSuspension.email_hash == email_hash,
            or_(
                RefundAccessSuspension.state == "refund_pending",
                and_(
                    RefundAccessSuspension.state == "refunded",
                    ~newer_completed_entitlement,
                ),
            ),
        )
        .first()
        is not None
    )


def is_email_refund_blocked(db: Session, email: str) -> bool:
    normalized = normalize_account_email(email)
    if not normalized:
        return True
    email_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return is_email_hash_refund_blocked(db, email_hash)


def is_account_refund_blocked(db: Session, account) -> bool:
    if is_email_refund_blocked(db, str(getattr(account, "email", "") or "")):
        return True
    if isinstance(account, User):
        master_email = (
            db.query(Client.email)
            .filter(Client.id == account.client_id)
            .scalar()
        )
        return bool(master_email and is_email_refund_blocked(db, master_email))
    return False


def lock_refund_identity_for_creation(db: Session, email: str) -> None:
    """Serialize provisioning with refund events for the same normalized email."""
    get_bind = getattr(db, "get_bind", None)
    if not callable(get_bind) or get_bind().dialect.name != "postgresql":
        return
    normalized = normalize_account_email(email)
    email_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    lock_key = f"refund-access:email:{email_hash}"
    if _is_web_request_session(db):
        acquired = bool(
            db.execute(
                text(
                    "SELECT pg_try_advisory_xact_lock("
                    "hashtextextended(:lock_key, 0))"
                ),
                {"lock_key": lock_key},
            ).scalar()
        )
        if not acquired:
            db.rollback()
            raise RefundIdentityOperationBusyError("external_identity")
        return

    # Refund workers and other explicit SessionLocal owners intentionally keep
    # the blocking form: those paths serialize durable offboarding work outside
    # the web event loop and must eventually acquire the lock.
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": lock_key},
    )


@contextmanager
def refund_identity_operation_reservation(
    db: Session,
    reservation_key: str,
) -> Iterator[RefundIdentityOperationReservation]:
    """Reserve process capacity before a token-based operation queries the DB."""
    get_bind = getattr(db, "get_bind", None)
    if not callable(get_bind):
        yield RefundIdentityOperationReservation(_guard=None, _active=False)
        return
    bind = get_bind()
    if bind.dialect.name != "postgresql":
        yield RefundIdentityOperationReservation(_guard=None, _active=False)
        return

    local_key = (
        "preflight:"
        + hashlib.sha256(str(reservation_key).encode("utf-8")).hexdigest()
    )
    with _REFUND_IDENTITY_OPERATION_GUARD.local_lock(local_key):
        with _REFUND_IDENTITY_OPERATION_GUARD.reserve_capacity() as reservation:
            yield reservation


@contextmanager
def refund_identity_operation_lock(
    db: Session,
    email: str,
    *,
    reservation: Optional[RefundIdentityOperationReservation] = None,
) -> Iterator[None]:
    """Try-lock a user-driven identity operation without exhausting the pool.

    Process-local email contention and the global capacity guard both happen
    before checking out the dedicated advisory-lock connection. Refund
    processing intentionally keeps its separate blocking lock path.
    """
    normalized = normalize_account_email(email)
    get_bind = getattr(db, "get_bind", None)
    if not callable(get_bind):
        yield
        return
    bind = get_bind()
    if bind.dialect.name != "postgresql":
        yield
        return

    lock_key = (
        "refund-access:email:"
        + hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    )
    local_key = f"email:{lock_key}"
    with _REFUND_IDENTITY_OPERATION_GUARD.local_lock(local_key):
        with _REFUND_IDENTITY_OPERATION_GUARD.reuse_or_reserve_capacity(
            reservation
        ):
            with bind.connect() as lock_connection:
                acquired = bool(
                    lock_connection.execute(
                        text(
                            "SELECT pg_try_advisory_lock("
                            "hashtextextended(:lock_key, 0))"
                        ),
                        {"lock_key": lock_key},
                    ).scalar()
                )
                if not acquired:
                    raise RefundIdentityOperationBusyError("external_identity")
                try:
                    yield
                finally:
                    lock_connection.execute(
                        text(
                            "SELECT pg_advisory_unlock("
                            "hashtextextended(:lock_key, 0))"
                        ),
                        {"lock_key": lock_key},
                    )


def lock_and_resolve_account_email_identity(
    db: Session,
    email: str,
) -> AccountEmailIdentity:
    """Resolve both login namespaces under the refund identity lock."""
    normalized = normalize_account_email(email)
    if not normalized:
        raise AccountEmailCollisionError("invalid_account_email")
    lock_refund_identity_for_creation(db, normalized)

    clients = (
        db.query(Client)
        .filter(func.lower(Client.email) == normalized)
        .order_by(Client.id)
        .all()
    )
    users = (
        db.query(User)
        .filter(func.lower(User.email) == normalized)
        .order_by(User.id)
        .all()
    )
    if len(clients) > 1 or len(users) > 1 or (clients and users):
        raise AccountEmailCollisionError("account_email_identity_collision")
    return AccountEmailIdentity(
        normalized_email=normalized,
        client=clients[0] if clients else None,
        user=users[0] if users else None,
    )


def lock_and_validate_account_email_available(
    db: Session,
    email: str,
    *,
    ignore_client_id: Optional[int] = None,
    ignore_user_id: Optional[int] = None,
) -> str:
    """Reject Client/User collisions atomically for account creation/update."""
    normalized = normalize_account_email(email)
    if not normalized:
        raise AccountEmailCollisionError("invalid_account_email")
    lock_refund_identity_for_creation(db, normalized)

    client_query = db.query(Client.id).filter(func.lower(Client.email) == normalized)
    if ignore_client_id is not None:
        client_query = client_query.filter(Client.id != int(ignore_client_id))
    user_query = db.query(User.id).filter(func.lower(User.email) == normalized)
    if ignore_user_id is not None:
        user_query = user_query.filter(User.id != int(ignore_user_id))
    if client_query.first() or user_query.first():
        raise AccountEmailCollisionError("account_email_already_in_use")
    return normalized


def lock_refund_entities_for_mutation(
    db: Session,
    *,
    company_ids: Iterable[int] = (),
    client_ids: Iterable[int] = (),
    user_ids: Iterable[int] = (),
) -> None:
    """Serialize provisioning/mutations with refund scope snapshots.

    The ordering is the same global company -> client -> user order used by
    refund_access_service, preventing deadlocks between provisioning and
    offboarding transactions.
    """
    get_bind = getattr(db, "get_bind", None)
    if not callable(get_bind) or get_bind().dialect.name != "postgresql":
        return
    normalized_company_ids = sorted({int(value) for value in company_ids})
    lock_keys = [
        *(
            f"refund-access:entity:company:{entity_id}"
            for entity_id in normalized_company_ids
        ),
        *(
            f"refund-access:entity:client:{entity_id}"
            for entity_id in sorted({int(value) for value in client_ids})
        ),
        *(
            f"refund-access:entity:user:{entity_id}"
            for entity_id in sorted({int(value) for value in user_ids})
        ),
    ]
    if _is_web_request_session(db):
        busy_company_id = (
            normalized_company_ids[0]
            if normalized_company_ids
            else 0
        )
        for lock_key in lock_keys:
            acquired = bool(
                db.execute(
                    text(
                        "SELECT pg_try_advisory_xact_lock("
                        "hashtextextended(:lock_key, 0))"
                    ),
                    {"lock_key": lock_key},
                ).scalar()
            )
            if not acquired:
                db.rollback()
                raise CompanyOperationalLockBusyError(busy_company_id)
        return

    for lock_key in lock_keys:
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": lock_key},
        )


def try_lock_refund_entities_for_access(
    db: Session,
    *,
    company_ids: Iterable[int] = (),
    client_ids: Iterable[int] = (),
    user_ids: Iterable[int] = (),
) -> None:
    """Acquire non-blocking shared admission fences for account access.

    Refund/offboarding mutations use the matching exclusive advisory locks.
    Shared admission locks therefore allow normal concurrent access while
    preserving the global company -> client -> user ordering and linearizing
    every successful admission with a concurrent refund.  The caller owns the
    transaction and must commit or roll it back when the protected operation
    ends.

    On contention the transaction is rolled back before reporting a transient
    busy result.  This is intentionally fail-fast: request/event-loop callers
    must retry asynchronously instead of waiting in PostgreSQL.
    """
    get_bind = getattr(db, "get_bind", None)
    if not callable(get_bind) or get_bind().dialect.name != "postgresql":
        return

    normalized_company_ids = sorted({int(value) for value in company_ids})
    lock_keys = [
        *(
            f"refund-access:entity:company:{entity_id}"
            for entity_id in normalized_company_ids
        ),
        *(
            f"refund-access:entity:client:{entity_id}"
            for entity_id in sorted({int(value) for value in client_ids})
        ),
        *(
            f"refund-access:entity:user:{entity_id}"
            for entity_id in sorted({int(value) for value in user_ids})
        ),
    ]
    busy_company_id = normalized_company_ids[0] if normalized_company_ids else 0
    for lock_key in lock_keys:
        acquired = bool(
            db.execute(
                text(
                    "SELECT pg_try_advisory_xact_lock_shared("
                    "hashtextextended(:lock_key, 0))"
                ),
                {"lock_key": lock_key},
            ).scalar()
        )
        if not acquired:
            db.rollback()
            raise CompanyOperationalLockBusyError(busy_company_id)


def fence_company_job_mutation(db: Session, company_id: int) -> None:
    """Linearize durable job creation/status activation with refund blocking."""
    normalized_company_id = int(company_id)
    lock_refund_entities_for_mutation(
        db,
        company_ids=[normalized_company_id],
    )
    ensure_company_operational(db, normalized_company_id)


def capture_company_job_epoch(
    db: Session,
    company_id: int,
    *,
    expected_epoch: Optional[int] = None,
) -> int:
    """Capture the active epoch under the same transaction fence as refunds."""
    normalized_company_id = int(company_id)
    fence_company_job_mutation(db, normalized_company_id)
    epoch = get_company_operational_epoch(db, normalized_company_id)
    if epoch is None:
        raise CompanyOperationallyBlockedError(
            normalized_company_id,
            "not_found",
        )
    if expected_epoch is not None and epoch != int(expected_epoch):
        raise CompanyOperationallyBlockedError(
            normalized_company_id,
            "stale_operational_epoch",
        )
    return epoch


def try_capture_company_job_epoch(
    db: Session,
    company_id: int,
    *,
    expected_epoch: Optional[int] = None,
) -> int:
    """Capture an active epoch without waiting on a concurrent company fence.

    Intended for durable workers that can safely retry the original payload.
    Callers must finish or roll back the transaction after a successful capture
    so the advisory lock is released before long-running processing begins.
    """
    normalized_company_id = int(company_id)
    get_bind = getattr(db, "get_bind", None)
    if callable(get_bind) and get_bind().dialect.name == "postgresql":
        acquired = bool(
            db.execute(
                text(
                    "SELECT pg_try_advisory_xact_lock("
                    "hashtextextended(:lock_key, 0))"
                ),
                {
                    "lock_key": (
                        f"refund-access:entity:company:{normalized_company_id}"
                    )
                },
            ).scalar()
        )
        if not acquired:
            db.rollback()
            raise CompanyOperationalLockBusyError(normalized_company_id)

    ensure_company_operational(db, normalized_company_id)
    epoch = get_company_operational_epoch(db, normalized_company_id)
    if epoch is None:
        raise CompanyOperationallyBlockedError(
            normalized_company_id,
            "not_found",
        )
    if expected_epoch is not None and epoch != int(expected_epoch):
        raise CompanyOperationallyBlockedError(
            normalized_company_id,
            "stale_operational_epoch",
        )
    return epoch


def validate_company_job_epoch(
    db: Session,
    company_id: int,
    expected_epoch: Optional[int],
) -> bool:
    """Reject backlog created before any refund block, even after restoration."""
    if not is_company_operational(db, int(company_id)):
        return False
    current_epoch = get_company_operational_epoch(db, int(company_id))
    if current_epoch is None:
        return False
    if expected_epoch is None:
        # Compatibility for tasks published before the epoch deployment. The
        # first refund block increments the epoch and permanently invalidates
        # this legacy backlog, including after a later restore.
        return current_epoch == 0
    return current_epoch == int(expected_epoch)


def enqueue_company_job_if_active(
    db: Session,
    company_id: int,
    *,
    is_still_pending: Callable[[], bool],
    enqueue: Callable[[], Any],
) -> Tuple[bool, Any]:
    """Publish broker work while holding the company refund transaction fence.

    The durable row must already be committed. A refund that wins the gap
    cancels it and makes either the operational recheck or `is_still_pending`
    fail. If enqueue wins, refund waits for this transaction and then cancels
    the durable row, so ETA work remains terminal after a later restore.
    """
    try:
        fence_company_job_mutation(db, int(company_id))
        if not is_still_pending():
            db.rollback()
            return False, None
        result = enqueue()
        db.commit()
        return True, result
    except Exception:
        db.rollback()
        raise
