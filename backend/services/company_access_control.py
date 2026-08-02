"""Provider-independent identity and company operational gates."""

from __future__ import annotations

import hashlib
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Optional, Tuple

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.models import Client, Company, User


def _env_nonnegative_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return max(0, int(default))


ACTIVE_OPERATIONAL_STATUS = "active"
IDENTITY_OPERATION_RETRY_AFTER_SECONDS = max(
    1,
    _env_nonnegative_int("IDENTITY_OPERATION_RETRY_AFTER_SECONDS", 2),
)


class CompanyOperationallyBlockedError(RuntimeError):
    def __init__(self, company_id: int, status: str):
        super().__init__(f"company_operationally_blocked:{status}")
        self.company_id = int(company_id)
        self.status = status


class CompanyOperationalLockBusyError(RuntimeError):
    """Transient company-fence contention that callers should retry."""

    def __init__(self, company_id: int):
        super().__init__("company_operational_lock_busy")
        self.company_id = int(company_id)
        self.retry_after_seconds = IDENTITY_OPERATION_RETRY_AFTER_SECONDS


class AccountEmailCollisionError(RuntimeError):
    pass


class IdentityOperationBusyError(RuntimeError):
    """Transient identity-lock contention in a user-driven operation."""

    def __init__(self, reason: str):
        super().__init__(f"identity_operation_busy:{reason}")
        self.reason = reason
        self.retry_after_seconds = IDENTITY_OPERATION_RETRY_AFTER_SECONDS


@dataclass(frozen=True)
class AccountEmailIdentity:
    normalized_email: str
    client: Optional[Client]
    user: Optional[User]


@dataclass
class IdentityOperationReservation:
    """A process-local capacity slot reserved before a database query."""

    _guard: Optional["_IdentityOperationGuard"]
    _active: bool


@dataclass
class _LocalIdentityLockEntry:
    lock: threading.Lock
    references: int = 0


class _IdentityOperationGuard:
    """Bound identity operations before they consume database connections."""

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
            raise IdentityOperationBusyError("local_identity")

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
    def reserve_capacity(self) -> Iterator[IdentityOperationReservation]:
        if not self._capacity.acquire(blocking=False):
            raise IdentityOperationBusyError("capacity")

        with self._capacity_state_lock:
            self._capacity_in_use += 1
        reservation = IdentityOperationReservation(
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
        reservation: Optional[IdentityOperationReservation],
    ) -> Iterator[None]:
        if reservation is not None:
            if reservation._guard is not self or not reservation._active:
                raise RuntimeError("invalid_identity_operation_reservation")
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
    pool_headroom=_env_nonnegative_int("IDENTITY_OPERATION_POOL_HEADROOM", 20),
    configured_max=_env_nonnegative_int("IDENTITY_OPERATION_MAX_CONCURRENCY", 4),
)
_IDENTITY_OPERATION_GUARD = _IdentityOperationGuard(
    _IDENTITY_OPERATION_CAPACITY
)


def normalize_account_email(email: str) -> str:
    return str(email or "").strip().casefold()


def _is_web_request_session(db: Session) -> bool:
    info = getattr(db, "info", None)
    return bool(isinstance(info, dict) and info.get("agentive_web_request"))


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


def _identity_lock_key(email: str) -> str:
    normalized = normalize_account_email(email)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"account-identity:{digest}"


def lock_account_identity_for_creation(db: Session, email: str) -> None:
    """Serialize creation of accounts that share a normalized email."""

    get_bind = getattr(db, "get_bind", None)
    if not callable(get_bind) or get_bind().dialect.name != "postgresql":
        return
    lock_key = _identity_lock_key(email)
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
            raise IdentityOperationBusyError("external_identity")
        return

    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": lock_key},
    )


@contextmanager
def account_identity_operation_reservation(
    db: Session,
    reservation_key: str,
) -> Iterator[IdentityOperationReservation]:
    get_bind = getattr(db, "get_bind", None)
    if not callable(get_bind) or get_bind().dialect.name != "postgresql":
        yield IdentityOperationReservation(_guard=None, _active=False)
        return

    local_key = (
        "preflight:"
        + hashlib.sha256(str(reservation_key).encode("utf-8")).hexdigest()
    )
    with _IDENTITY_OPERATION_GUARD.local_lock(local_key):
        with _IDENTITY_OPERATION_GUARD.reserve_capacity() as reservation:
            yield reservation


@contextmanager
def account_identity_operation_lock(
    db: Session,
    email: str,
    *,
    reservation: Optional[IdentityOperationReservation] = None,
) -> Iterator[None]:
    """Try-lock an account identity without exhausting the connection pool."""

    get_bind = getattr(db, "get_bind", None)
    if not callable(get_bind) or get_bind().dialect.name != "postgresql":
        yield
        return

    lock_key = _identity_lock_key(email)
    local_key = f"email:{lock_key}"
    with _IDENTITY_OPERATION_GUARD.local_lock(local_key):
        with _IDENTITY_OPERATION_GUARD.reuse_or_reserve_capacity(reservation):
            with get_bind().connect() as lock_connection:
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
                    raise IdentityOperationBusyError("external_identity")
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
    normalized = normalize_account_email(email)
    if not normalized:
        raise AccountEmailCollisionError("invalid_account_email")
    lock_account_identity_for_creation(db, normalized)

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
    normalized = normalize_account_email(email)
    if not normalized:
        raise AccountEmailCollisionError("invalid_account_email")
    lock_account_identity_for_creation(db, normalized)

    client_query = db.query(Client.id).filter(func.lower(Client.email) == normalized)
    if ignore_client_id is not None:
        client_query = client_query.filter(Client.id != int(ignore_client_id))
    user_query = db.query(User.id).filter(func.lower(User.email) == normalized)
    if ignore_user_id is not None:
        user_query = user_query.filter(User.id != int(ignore_user_id))
    if client_query.first() or user_query.first():
        raise AccountEmailCollisionError("account_email_already_in_use")
    return normalized


def _entity_lock_keys(
    *,
    company_ids: Iterable[int] = (),
    client_ids: Iterable[int] = (),
    user_ids: Iterable[int] = (),
) -> tuple[list[int], list[str]]:
    normalized_company_ids = sorted({int(value) for value in company_ids})
    lock_keys = [
        *(f"entity-mutation:company:{value}" for value in normalized_company_ids),
        *(
            f"entity-mutation:client:{value}"
            for value in sorted({int(item) for item in client_ids})
        ),
        *(
            f"entity-mutation:user:{value}"
            for value in sorted({int(item) for item in user_ids})
        ),
    ]
    return normalized_company_ids, lock_keys


def lock_entities_for_mutation(
    db: Session,
    *,
    company_ids: Iterable[int] = (),
    client_ids: Iterable[int] = (),
    user_ids: Iterable[int] = (),
) -> None:
    """Serialize mutations using a stable company/client/user lock order."""

    get_bind = getattr(db, "get_bind", None)
    if not callable(get_bind) or get_bind().dialect.name != "postgresql":
        return
    normalized_company_ids, lock_keys = _entity_lock_keys(
        company_ids=company_ids,
        client_ids=client_ids,
        user_ids=user_ids,
    )
    if _is_web_request_session(db):
        busy_company_id = normalized_company_ids[0] if normalized_company_ids else 0
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


def try_lock_entities_for_access(
    db: Session,
    *,
    company_ids: Iterable[int] = (),
    client_ids: Iterable[int] = (),
    user_ids: Iterable[int] = (),
) -> None:
    """Acquire non-blocking shared admission locks for account access."""

    get_bind = getattr(db, "get_bind", None)
    if not callable(get_bind) or get_bind().dialect.name != "postgresql":
        return
    normalized_company_ids, lock_keys = _entity_lock_keys(
        company_ids=company_ids,
        client_ids=client_ids,
        user_ids=user_ids,
    )
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
    normalized_company_id = int(company_id)
    lock_entities_for_mutation(db, company_ids=[normalized_company_id])
    ensure_company_operational(db, normalized_company_id)


def capture_company_job_epoch(
    db: Session,
    company_id: int,
    *,
    expected_epoch: Optional[int] = None,
) -> int:
    normalized_company_id = int(company_id)
    fence_company_job_mutation(db, normalized_company_id)
    epoch = get_company_operational_epoch(db, normalized_company_id)
    if epoch is None:
        raise CompanyOperationallyBlockedError(normalized_company_id, "not_found")
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
    normalized_company_id = int(company_id)
    get_bind = getattr(db, "get_bind", None)
    if callable(get_bind) and get_bind().dialect.name == "postgresql":
        lock_key = f"entity-mutation:company:{normalized_company_id}"
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
            raise CompanyOperationalLockBusyError(normalized_company_id)

    ensure_company_operational(db, normalized_company_id)
    epoch = get_company_operational_epoch(db, normalized_company_id)
    if epoch is None:
        raise CompanyOperationallyBlockedError(normalized_company_id, "not_found")
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
    if not is_company_operational(db, int(company_id)):
        return False
    current_epoch = get_company_operational_epoch(db, int(company_id))
    if current_epoch is None:
        return False
    if expected_epoch is None:
        return current_epoch == 0
    return current_epoch == int(expected_epoch)


def enqueue_company_job_if_active(
    db: Session,
    company_id: int,
    *,
    is_still_pending: Callable[[], bool],
    enqueue: Callable[[], Any],
) -> Tuple[bool, Any]:
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
