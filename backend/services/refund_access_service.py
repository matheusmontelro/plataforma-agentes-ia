"""Idempotent, fail-closed access offboarding for refund lifecycle events."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from sqlalchemy import and_, bindparam, func, inspect, or_, text
from sqlalchemy.orm import Session

from backend.db import TRANSACTION_LOCK_TIMEOUT_MS_INFO_KEY
from backend.integrations.waha_sdk import WAHAException, get_client as get_waha_client
from backend.models import (
    AgentDynamicFollowupEnrollment,
    AgentDynamicFollowupExecution,
    Client,
    ClientCompany,
    Company,
    ContactTask,
    CustomerManagedCompany,
    FlowEnrollment,
    FlowStepExecution,
    NutritionCampaignExecution,
    PasswordResetToken,
    PosConsultaExecution,
    RefundAccessEntityState,
    RefundAccessEvent,
    RefundAccessSuspension,
    RefundAccessTarget,
    ScheduledMessageExecution,
    User,
    UserSession,
    WhatsAppCampaign,
    WhatsAppCampaignExecution,
)
from backend.services.company_access_control import (
    is_refund_suspension_superseded,
    normalize_account_email,
)


logger = logging.getLogger(__name__)

BLOCKING_STATES = ("refund_pending", "refunded")
VALID_STATES = frozenset((*BLOCKING_STATES, "active"))
STATE_PRECEDENCE = {"active": 0, "refund_pending": 1, "refunded": 2}
QUEUE_CANCEL_REASON = "refund_access_suspended"
REFUND_ACCESS_LOCK_TIMEOUT_MS_INFO_KEY = TRANSACTION_LOCK_TIMEOUT_MS_INFO_KEY
REFUND_ACCESS_LOCK_TIMEOUT_MIN_MS = 100
REFUND_ACCESS_LOCK_TIMEOUT_MAX_MS = 60_000


def _bounded_float_env(
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    try:
        configured = float(os.getenv(name, str(default)).strip())
    except ValueError:
        configured = default
    return max(minimum, min(configured, maximum))


# The upstream caller currently gives the whole request ten seconds. Keep the
# remote portion below that boundary so a disconnected caller cannot leave a
# refund worker and its advisory locks occupied for minutes.
REFUND_ACCESS_WAHA_REQUEST_TIMEOUT_SECONDS = _bounded_float_env(
    "REFUND_ACCESS_WAHA_REQUEST_TIMEOUT_SECONDS",
    2.0,
    minimum=0.25,
    maximum=5.0,
)
REFUND_ACCESS_WAHA_TOTAL_BUDGET_SECONDS = _bounded_float_env(
    "REFUND_ACCESS_WAHA_TOTAL_BUDGET_SECONDS",
    6.0,
    minimum=0.5,
    maximum=8.0,
)


class RefundAccessError(RuntimeError):
    status_code = 500
    code = "refund_access_error"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        company_ids: Optional[Sequence[int]] = None,
        client_ids: Optional[Sequence[int]] = None,
        user_ids: Optional[Sequence[int]] = None,
    ):
        super().__init__(message)
        self.company_ids = [int(value) for value in (company_ids or [])]
        self.client_ids = [int(value) for value in (client_ids or [])]
        self.user_ids = [int(value) for value in (user_ids or [])]


class RefundAccessConflict(RefundAccessError):
    status_code = 409
    code = "refund_access_conflict"


class RefundAccessRemoteError(RefundAccessError):
    status_code = 503
    code = "refund_access_remote_action_failed"
    retryable = True


class _RefundAccessWahaBudgetExceeded(TimeoutError):
    """Internal marker used to stop issuing remote actions after the budget."""


@dataclass(frozen=True)
class RefundAccessCommand:
    event_id: str
    idempotency_key: str
    invoice_id: str
    email: str
    state: str
    occurred_at: datetime
    source: str


@dataclass(frozen=True)
class AccountScope:
    root_client_id: int
    company_ids: Tuple[int, ...]
    client_ids: Tuple[int, ...]
    user_ids: Tuple[int, ...]
    excluded_shared_company_ids: Tuple[int, ...] = ()


@dataclass(frozen=True)
class RefundAccessResult:
    status: str
    state: str
    company_ids: Tuple[int, ...] = ()
    client_ids: Tuple[int, ...] = ()
    user_ids: Tuple[int, ...] = ()
    clients_affected: int = 0
    users_affected: int = 0
    companies_affected: int = 0
    queues_cancelled: int = 0
    excluded_shared_company_ids: Tuple[int, ...] = ()
    supersedes_prior_terminal: bool = False
    new_entitlement: bool = False
    shadowed_by_newer_entitlement: bool = False

    def as_payload(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "state": self.state,
            "companyIds": list(self.company_ids),
            "clientIds": list(self.client_ids),
            "userIds": list(self.user_ids),
            "clientsAffected": self.clients_affected,
            "usersAffected": self.users_affected,
            "companiesAffected": self.companies_affected,
            "queuesCancelled": self.queues_cancelled,
            "excludedSharedCompanyIds": list(self.excluded_shared_company_ids),
            "supersedesPriorTerminal": self.supersedes_prior_terminal,
            "newEntitlement": self.new_entitlement,
            "shadowedByNewerEntitlement": self.shadowed_by_newer_entitlement,
        }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_command(command: RefundAccessCommand) -> RefundAccessCommand:
    state = str(command.state or "").strip().lower()
    if state not in VALID_STATES:
        raise RefundAccessConflict("invalid_state")

    event_id = str(command.event_id or "").strip()
    idempotency_key = str(command.idempotency_key or "").strip()
    invoice_id = str(command.invoice_id or "").strip()
    email = normalize_account_email(command.email)
    source = str(command.source or "").strip().lower()
    if not all((event_id, idempotency_key, invoice_id, email, source)):
        raise RefundAccessConflict("missing_required_identity")
    if any(len(value) > 255 for value in (event_id, idempotency_key, invoice_id)):
        raise RefundAccessConflict("identity_too_long")
    if len(source) > 40 or len(email) > 320:
        raise RefundAccessConflict("identity_too_long")
    if source != "eduzz":
        raise RefundAccessConflict("unsupported_source")

    return RefundAccessCommand(
        event_id=event_id,
        idempotency_key=idempotency_key,
        invoice_id=invoice_id,
        email=email,
        state=state,
        occurred_at=_aware_utc(command.occurred_at),
        source=source,
    )


def _email_hash(email: str) -> str:
    return hashlib.sha256(email.encode("utf-8")).hexdigest()


def _resolve_scope(db: Session, email: str) -> Optional[AccountScope]:
    clients = (
        db.query(Client)
        .filter(func.lower(Client.email) == email)
        .order_by(Client.id)
        .all()
    )
    if len(clients) > 1:
        raise RefundAccessConflict("ambiguous_master_identity")
    if not clients:
        staff_match = db.query(User.id).filter(func.lower(User.email) == email).first()
        if staff_match:
            raise RefundAccessConflict("staff_identity_is_not_master")
        return None

    root = clients[0]
    root_company_id = int(root.ownership_company_id)

    # Client.ownership_company_id is immutable; Client.company_id is only the
    # currently selected UI context. Some admin-created
    # workspaces have no CustomerManagedCompany row and are represented only by
    # ClientCompany, so include those associations only when this root client is
    # their sole account owner. A shared/third-party association remains out of
    # scope even though the root client can access it.
    seed_company_ids: Set[int] = {root_company_id}
    direct_shared_company_ids: Set[int] = set()
    direct_associations = (
        db.query(ClientCompany)
        .filter(ClientCompany.client_id == root.id)
        .all()
    )
    for association in direct_associations:
        company_id = int(association.company_id)
        if company_id == root_company_id:
            continue
        has_other_account_owner = (
            db.query(ClientCompany.id)
            .filter(
                ClientCompany.company_id == company_id,
                ClientCompany.client_id != root.id,
            )
            .first()
            is not None
        )
        has_other_primary_owner = (
            db.query(Client.id)
            .filter(
                Client.ownership_company_id == company_id,
                Client.id != root.id,
            )
            .first()
            is not None
        )
        if has_other_account_owner or has_other_primary_owner:
            direct_shared_company_ids.add(company_id)
        else:
            seed_company_ids.add(company_id)

    # First discover the complete graph reachable from the ownership anchor.
    # A legacy/corrupt multi-owner association must not make the root account
    # fail open, but globally disabling the shared workspace could affect an
    # unrelated owner. Shared nodes and everything reachable only through them
    # are therefore excluded while the unambiguous root subgraph is blocked.
    reachable_company_ids: Set[int] = set(seed_company_ids)
    reachable_links: List[CustomerManagedCompany] = []
    changed = True
    while changed:
        changed = False
        owned_links = (
            db.query(CustomerManagedCompany)
            .filter(CustomerManagedCompany.owner_company_id.in_(reachable_company_ids))
            .all()
        )
        reachable_links = owned_links
        for link in owned_links:
            managed_id = int(link.managed_company_id)
            if managed_id not in reachable_company_ids:
                reachable_company_ids.add(managed_id)
                changed = True

    inbound_links = (
        db.query(CustomerManagedCompany)
        .filter(CustomerManagedCompany.managed_company_id.in_(reachable_company_ids))
        .all()
    )
    shared_seeds: Set[int] = {
        int(link.managed_company_id)
        for link in inbound_links
        if int(link.managed_company_id) != root_company_id
        and int(link.owner_company_id) not in reachable_company_ids
    }
    # Keep every node that still has at least one safe path from an exclusive
    # seed. This matters for a diamond graph: a descendant reached directly
    # from the root must remain blocked even when another path passes through a
    # shared node.
    safe_company_ids: Set[int] = {
        company_id
        for company_id in seed_company_ids
        if company_id == root_company_id or company_id not in shared_seeds
    }
    changed = True
    while changed:
        changed = False
        for link in reachable_links:
            owner_id = int(link.owner_company_id)
            managed_id = int(link.managed_company_id)
            if (
                owner_id in safe_company_ids
                and managed_id not in shared_seeds
                and managed_id not in safe_company_ids
            ):
                safe_company_ids.add(managed_id)
                changed = True

    excluded_company_ids = (
        reachable_company_ids - safe_company_ids
    ) | {
        company_id
        for company_id in direct_shared_company_ids
        if company_id not in safe_company_ids
    }
    if excluded_company_ids:
        logger.warning(
            "Workspaces compartilhados excluídos do offboarding automático "
            "root_company_id=%s excluded_company_ids=%s",
            root.ownership_company_id,
            sorted(excluded_company_ids),
        )

    company_ids = reachable_company_ids - excluded_company_ids

    target_clients = (
        db.query(Client)
        .filter(
            or_(
                Client.id == root.id,
                Client.ownership_company_id.in_(company_ids),
            )
        )
        .all()
    )
    client_ids = {int(client.id) for client in target_clients}

    users = (
        db.query(User.id)
        .filter(or_(User.client_id.in_(client_ids), User.company_id.in_(company_ids)))
        .all()
    )
    return AccountScope(
        root_client_id=int(root.id),
        company_ids=tuple(sorted(company_ids)),
        client_ids=tuple(sorted(client_ids)),
        user_ids=tuple(sorted(int(row.id) for row in users)),
        excluded_shared_company_ids=tuple(sorted(excluded_company_ids)),
    )


def _event_matches(event: RefundAccessEvent, command: RefundAccessCommand) -> bool:
    return (
        event.event_id == command.event_id
        and event.idempotency_key == command.idempotency_key
        and event.source == command.source
        and event.invoice_id == command.invoice_id
        and event.email_hash == _email_hash(command.email)
        and event.requested_state == command.state
        and _aware_utc(event.occurred_at) == command.occurred_at
    )


def _find_existing_event(db: Session, command: RefundAccessCommand) -> Optional[RefundAccessEvent]:
    event = (
        db.query(RefundAccessEvent)
        .filter(
            or_(
                RefundAccessEvent.event_id == command.event_id,
                RefundAccessEvent.idempotency_key == command.idempotency_key,
            )
        )
        .first()
    )
    if event and not _event_matches(event, command):
        raise RefundAccessConflict("idempotency_identity_reused")
    return event


def _create_event(db: Session, command: RefundAccessCommand) -> RefundAccessEvent:
    event = RefundAccessEvent(
        event_id=command.event_id,
        idempotency_key=command.idempotency_key,
        source=command.source,
        invoice_id=command.invoice_id,
        email_hash=_email_hash(command.email),
        requested_state=command.state,
        occurred_at=command.occurred_at,
        status="processing",
    )
    db.add(event)
    db.flush()
    return event


def _is_stale(suspension: RefundAccessSuspension, command: RefundAccessCommand) -> bool:
    latest_at = _aware_utc(suspension.latest_occurred_at)
    if command.occurred_at < latest_at:
        return True
    if command.occurred_at > latest_at:
        return False
    return STATE_PRECEDENCE[command.state] <= STATE_PRECEDENCE[suspension.state]


def _get_or_create_entity_baseline(
    db: Session,
    entity_type: str,
    entity_id: int,
    *,
    active: Optional[bool],
    waha_enabled: Optional[bool] = None,
) -> RefundAccessEntityState:
    marker = (
        db.query(RefundAccessEntityState)
        .filter(
            RefundAccessEntityState.entity_type == entity_type,
            RefundAccessEntityState.entity_id == entity_id,
        )
        .with_for_update()
        .first()
    )
    if marker:
        return marker
    marker = RefundAccessEntityState(
        entity_type=entity_type,
        entity_id=entity_id,
        restore_active=active,
        restore_waha_enabled=waha_enabled,
        waha_was_finalized=False,
    )
    db.add(marker)
    db.flush()
    return marker


def _add_target(
    db: Session,
    suspension_id: int,
    entity_type: str,
    entity_id: int,
    *,
    previous_active: Optional[bool],
    previous_waha_enabled: Optional[bool] = None,
) -> None:
    exists = (
        db.query(RefundAccessTarget.id)
        .filter(
            RefundAccessTarget.suspension_id == suspension_id,
            RefundAccessTarget.entity_type == entity_type,
            RefundAccessTarget.entity_id == entity_id,
        )
        .first()
    )
    if not exists:
        db.add(
            RefundAccessTarget(
                suspension_id=suspension_id,
                entity_type=entity_type,
                entity_id=entity_id,
                previous_active=previous_active,
                previous_waha_enabled=previous_waha_enabled,
            )
        )


def _cancel_pending_work(db: Session, company_ids: Sequence[int]) -> int:
    if not company_ids:
        return 0
    total = 0
    total += (
        db.query(ContactTask)
        .filter(
            ContactTask.company_id.in_(company_ids),
            ContactTask.task_type == "scheduled_message",
            ContactTask.status.in_(["pending", "in_progress"]),
        )
        .update({ContactTask.status: "canceled"}, synchronize_session=False)
    )
    total += (
        db.query(AgentDynamicFollowupEnrollment)
        .filter(
            AgentDynamicFollowupEnrollment.company_id.in_(company_ids),
            AgentDynamicFollowupEnrollment.status == "active",
        )
        .update(
            {
                AgentDynamicFollowupEnrollment.status: "cancelled",
                AgentDynamicFollowupEnrollment.cancel_reason: QUEUE_CANCEL_REASON,
            },
            synchronize_session=False,
        )
    )
    for model in (
        AgentDynamicFollowupExecution,
        PosConsultaExecution,
        ScheduledMessageExecution,
        NutritionCampaignExecution,
    ):
        total += (
            db.query(model)
            .filter(model.company_id.in_(company_ids), model.status.in_(["SCHEDULED", "PROCESSING"]))
            .update(
                {model.status: "CANCELED", model.error_message: QUEUE_CANCEL_REASON},
                synchronize_session=False,
            )
        )
    total += (
        db.query(FlowEnrollment)
        .filter(FlowEnrollment.company_id.in_(company_ids), FlowEnrollment.status == "active")
        .update(
            {
                FlowEnrollment.status: "cancelled",
                FlowEnrollment.cancel_reason: QUEUE_CANCEL_REASON,
            },
            synchronize_session=False,
        )
    )
    total += (
        db.query(FlowStepExecution)
        .filter(
            FlowStepExecution.company_id.in_(company_ids),
            FlowStepExecution.status.in_(["scheduled", "running"]),
        )
        .update(
            {
                FlowStepExecution.status: "cancelled",
                FlowStepExecution.error_message: QUEUE_CANCEL_REASON,
            },
            synchronize_session=False,
        )
    )
    campaign_ids = [
        int(row.id)
        for row in db.query(WhatsAppCampaign.id)
        .filter(
            WhatsAppCampaign.company_id.in_(company_ids),
            WhatsAppCampaign.status.in_(["DRAFT", "PROCESSING", "PAUSED"]),
        )
        .all()
    ]
    if campaign_ids:
        total += (
            db.query(WhatsAppCampaign)
            .filter(WhatsAppCampaign.id.in_(campaign_ids))
            .update({WhatsAppCampaign.status: "CANCELED"}, synchronize_session=False)
        )
        total += (
            db.query(WhatsAppCampaignExecution)
            .filter(
                WhatsAppCampaignExecution.campaign_id.in_(campaign_ids),
                WhatsAppCampaignExecution.status.in_(["PENDING", "SCHEDULED", "PROCESSING"]),
            )
            .update(
                {
                    WhatsAppCampaignExecution.status: "SKIPPED",
                    WhatsAppCampaignExecution.error_message: QUEUE_CANCEL_REASON,
                },
                synchronize_session=False,
            )
        )

    # Legacy execution tables are maintained by workers with SQL rather than
    # ORM models. Cancel their durable schedules so broker ETA messages cannot
    # replay after a later account restoration.
    inspector = inspect(db.get_bind())
    for table_name in (
        "follow_up_executions",
        "confirmation_executions",
        "noshow_follow_up_executions",
        "pos_venda_executions",
    ):
        if not inspector.has_table(table_name):
            continue
        statement = text(
            f"""
            UPDATE {table_name}
               SET status = 'CANCELED',
                   error_message = :reason,
                   updated_at = now()
             WHERE company_id IN :company_ids
               AND status IN ('SCHEDULED', 'PROCESSING')
            """
        ).bindparams(bindparam("company_ids", expanding=True))
        result = db.execute(
            statement,
            {"company_ids": list(company_ids), "reason": QUEUE_CANCEL_REASON},
        )
        total += int(result.rowcount or 0)
    return int(total)


def _apply_local_block(
    db: Session,
    suspension: RefundAccessSuspension,
    scope: AccountScope,
    state: str,
) -> Tuple[int, int, int, int]:
    companies = db.query(Company).filter(Company.id.in_(scope.company_ids)).all()
    clients = db.query(Client).filter(Client.id.in_(scope.client_ids)).all()
    users = db.query(User).filter(User.id.in_(scope.user_ids)).all() if scope.user_ids else []

    for company in companies:
        was_operational = company.operational_status == "active"
        _get_or_create_entity_baseline(
            db,
            "company",
            int(company.id),
            active=company.operational_status == "active",
            waha_enabled=bool(company.waha_enabled),
        )
        _add_target(
            db,
            int(suspension.id),
            "company",
            int(company.id),
            previous_active=company.operational_status == "active",
            previous_waha_enabled=bool(company.waha_enabled),
        )
        if state == "refunded":
            company.operational_status = "refunded"
            marker = (
                db.query(RefundAccessEntityState)
                .filter_by(entity_type="company", entity_id=company.id)
                .first()
            )
            marker.waha_was_finalized = True
        elif company.operational_status != "refunded":
            company.operational_status = "refund_pending"
        if was_operational:
            company.operational_epoch = int(company.operational_epoch or 0) + 1
        company.waha_enabled = False

    for client in clients:
        _get_or_create_entity_baseline(
            db,
            "client",
            int(client.id),
            active=bool(client.is_active),
        )
        _add_target(
            db,
            int(suspension.id),
            "client",
            int(client.id),
            previous_active=bool(client.is_active),
        )
        if client.is_active:
            client.auth_token_version = int(client.auth_token_version or 0) + 1
        client.is_active = False
        client.api_key = None

    for user in users:
        _get_or_create_entity_baseline(
            db,
            "user",
            int(user.id),
            active=bool(user.is_active),
        )
        _add_target(
            db,
            int(suspension.id),
            "user",
            int(user.id),
            previous_active=bool(user.is_active),
        )
        if user.is_active:
            user.auth_token_version = int(user.auth_token_version or 0) + 1
        user.is_active = False

    if scope.client_ids:
        db.query(UserSession).filter(UserSession.client_id.in_(scope.client_ids)).delete(
            synchronize_session=False
        )
        now = _utcnow()
        db.query(PasswordResetToken).filter(
            PasswordResetToken.used_at.is_(None),
            or_(
                PasswordResetToken.client_id.in_(scope.client_ids),
                PasswordResetToken.user_id.in_(scope.user_ids) if scope.user_ids else False,
            ),
        ).update({PasswordResetToken.used_at: now}, synchronize_session=False)

    queues_cancelled = _cancel_pending_work(db, scope.company_ids)
    return len(companies), len(clients), len(users), queues_cancelled


def _other_open_blocks(
    db: Session,
    excluded_suspension_ids: Iterable[int],
    entity_type: str,
    entity_id: int,
    *,
    provisional_active_invoice_id: Optional[str] = None,
    provisional_active_occurred_at: Optional[datetime] = None,
    provisional_active_is_entitlement: bool = False,
    provisional_active_email_hash: Optional[str] = None,
    provisional_active_root_client_id: Optional[int] = None,
) -> List[str]:
    excluded_ids = {int(value) for value in excluded_suspension_ids}
    return [
        str(suspension.state)
        for suspension in db.query(RefundAccessSuspension)
        .join(
            RefundAccessTarget,
            RefundAccessTarget.suspension_id == RefundAccessSuspension.id,
        )
        .filter(
            ~RefundAccessSuspension.id.in_(excluded_ids),
            RefundAccessSuspension.state.in_(BLOCKING_STATES),
            RefundAccessTarget.entity_type == entity_type,
            RefundAccessTarget.entity_id == entity_id,
        )
        .all()
        if not is_refund_suspension_superseded(
            db,
            suspension,
            provisional_active_invoice_id=provisional_active_invoice_id,
            provisional_active_occurred_at=provisional_active_occurred_at,
            provisional_active_is_entitlement=provisional_active_is_entitlement,
            provisional_active_email_hash=provisional_active_email_hash,
            provisional_active_root_client_id=provisional_active_root_client_id,
        )
    ]


def _other_open_email_blocks(
    db: Session,
    email_hash: str,
    *,
    excluded_suspension_ids: Iterable[int] = (),
    provisional_active_invoice_id: Optional[str] = None,
    provisional_active_occurred_at: Optional[datetime] = None,
    provisional_active_is_entitlement: bool = False,
    provisional_active_email_hash: Optional[str] = None,
    provisional_active_root_client_id: Optional[int] = None,
) -> List[str]:
    """Return identity tombstones not yet bound to the same live scope."""
    excluded_ids = {int(value) for value in excluded_suspension_ids}
    return [
        str(suspension.state)
        for suspension in db.query(RefundAccessSuspension)
        .filter(
            ~RefundAccessSuspension.id.in_(excluded_ids),
            RefundAccessSuspension.email_hash == email_hash,
            RefundAccessSuspension.state.in_(BLOCKING_STATES),
        )
        .all()
        if not is_refund_suspension_superseded(
            db,
            suspension,
            provisional_active_invoice_id=provisional_active_invoice_id,
            provisional_active_occurred_at=provisional_active_occurred_at,
            provisional_active_is_entitlement=provisional_active_is_entitlement,
            provisional_active_email_hash=provisional_active_email_hash,
            provisional_active_root_client_id=provisional_active_root_client_id,
        )
    ]


def _bind_scope_targets(
    db: Session,
    suspension: RefundAccessSuspension,
    scope: AccountScope,
) -> None:
    """Attach a previously account-less tombstone to its discovered entities."""
    companies = db.query(Company).filter(Company.id.in_(scope.company_ids)).all()
    clients = db.query(Client).filter(Client.id.in_(scope.client_ids)).all()
    users = (
        db.query(User).filter(User.id.in_(scope.user_ids)).all()
        if scope.user_ids
        else []
    )
    for company in companies:
        _add_target(
            db,
            int(suspension.id),
            "company",
            int(company.id),
            previous_active=company.operational_status == "active",
            previous_waha_enabled=bool(company.waha_enabled),
        )
    for client in clients:
        _add_target(
            db,
            int(suspension.id),
            "client",
            int(client.id),
            previous_active=bool(client.is_active),
        )
    for user in users:
        _add_target(
            db,
            int(suspension.id),
            "user",
            int(user.id),
            previous_active=bool(user.is_active),
        )
    # Production sessions disable autoflush. Persist the bindings now so a
    # subsequent block pass sees them instead of attempting duplicate targets.
    db.flush()


def _effective_scope_state(
    db: Session,
    scope: AccountScope,
    *,
    email_hash: Optional[str] = None,
    provisional_active_invoice_id: Optional[str] = None,
    provisional_active_occurred_at: Optional[datetime] = None,
    provisional_active_is_entitlement: bool = False,
) -> str:
    """Return the strongest durable block currently affecting this account.

    Historical ``not_found`` events have no entity targets until the account is
    discovered. They still belong to the same durable identity and therefore
    must participate in the effective ACK even when another invoice already
    resolved a live scope.
    """
    states = {"active"}
    company_states = (
        db.query(Company.operational_status)
        .filter(Company.id.in_(scope.company_ids))
        .all()
    )
    states.update(
        str(row.operational_status)
        for row in company_states
        if str(row.operational_status) in VALID_STATES
    )

    target_filters = []
    if scope.company_ids:
        target_filters.append(
            and_(
                RefundAccessTarget.entity_type == "company",
                RefundAccessTarget.entity_id.in_(scope.company_ids),
            )
        )
    if scope.client_ids:
        target_filters.append(
            and_(
                RefundAccessTarget.entity_type == "client",
                RefundAccessTarget.entity_id.in_(scope.client_ids),
            )
        )
    if scope.user_ids:
        target_filters.append(
            and_(
                RefundAccessTarget.entity_type == "user",
                RefundAccessTarget.entity_id.in_(scope.user_ids),
            )
        )
    if target_filters:
        open_suspensions = (
            db.query(RefundAccessSuspension)
            .join(
                RefundAccessTarget,
                RefundAccessTarget.suspension_id == RefundAccessSuspension.id,
            )
            .filter(
                RefundAccessSuspension.state.in_(BLOCKING_STATES),
                or_(*target_filters),
            )
            .all()
        )
        states.update(
            str(suspension.state)
            for suspension in open_suspensions
            if not is_refund_suspension_superseded(
                db,
                suspension,
                provisional_active_invoice_id=provisional_active_invoice_id,
                provisional_active_occurred_at=provisional_active_occurred_at,
                provisional_active_is_entitlement=provisional_active_is_entitlement,
                provisional_active_email_hash=email_hash,
                provisional_active_root_client_id=scope.root_client_id,
            )
        )
    if email_hash:
        email_suspensions = (
            db.query(RefundAccessSuspension)
            .filter(
                RefundAccessSuspension.email_hash == email_hash,
                RefundAccessSuspension.state.in_(BLOCKING_STATES),
            )
            .all()
        )
        states.update(
            str(suspension.state)
            for suspension in email_suspensions
            if not is_refund_suspension_superseded(
                db,
                suspension,
                provisional_active_invoice_id=provisional_active_invoice_id,
                provisional_active_occurred_at=provisional_active_occurred_at,
                provisional_active_is_entitlement=provisional_active_is_entitlement,
                provisional_active_email_hash=email_hash,
                provisional_active_root_client_id=scope.root_client_id,
            )
        )
    return max(states, key=lambda value: STATE_PRECEDENCE.get(value, -1))


def _effective_email_state(
    db: Session,
    email_hash: str,
    *,
    provisional_active_invoice_id: Optional[str] = None,
    provisional_active_occurred_at: Optional[datetime] = None,
    provisional_active_is_entitlement: bool = False,
) -> str:
    """Aggregate tombstones when no local platform account exists yet."""
    states = {"active"}
    states.update(
        str(suspension.state)
        for suspension in db.query(RefundAccessSuspension)
        .filter(
            RefundAccessSuspension.email_hash == email_hash,
            RefundAccessSuspension.state.in_(BLOCKING_STATES),
        )
        .all()
        if not is_refund_suspension_superseded(
            db,
            suspension,
            provisional_active_invoice_id=provisional_active_invoice_id,
            provisional_active_occurred_at=provisional_active_occurred_at,
            provisional_active_is_entitlement=provisional_active_is_entitlement,
            provisional_active_email_hash=email_hash,
        )
    )
    return max(states, key=lambda value: STATE_PRECEDENCE.get(value, -1))


def _superseded_terminal_suspensions(
    db: Session,
    command: RefundAccessCommand,
    *,
    root_client_id: Optional[int] = None,
) -> List[RefundAccessSuspension]:
    """Terminal blocks superseded provisionally by a newer different invoice."""
    if not _active_command_is_new_entitlement(db, command):
        return []
    if root_client_id is None:
        root_client_id = (
            db.query(RefundAccessSuspension.root_client_id)
            .filter(
                RefundAccessSuspension.source == command.source,
                RefundAccessSuspension.invoice_id == command.invoice_id,
                RefundAccessSuspension.email_hash == _email_hash(command.email),
            )
            .scalar()
        )
    identity_filters = [
        RefundAccessSuspension.email_hash == _email_hash(command.email)
    ]
    if root_client_id is not None:
        identity_filters.append(
            RefundAccessSuspension.root_client_id == int(root_client_id)
        )
    return [
        suspension
        for suspension in db.query(RefundAccessSuspension)
        .filter(
            RefundAccessSuspension.source == command.source,
            or_(*identity_filters),
            RefundAccessSuspension.state == "refunded",
            RefundAccessSuspension.invoice_id != command.invoice_id,
        )
        .all()
        if is_refund_suspension_superseded(
            db,
            suspension,
            provisional_active_invoice_id=command.invoice_id,
            provisional_active_occurred_at=command.occurred_at,
            provisional_active_is_entitlement=True,
            provisional_active_email_hash=_email_hash(command.email),
            provisional_active_root_client_id=root_client_id,
        )
    ]


def _active_command_is_new_entitlement(
    db: Session,
    command: RefundAccessCommand,
) -> bool:
    """Only an invoice with no refund history can supersede another sale."""
    if command.state != "active":
        return False
    return (
        db.query(RefundAccessEvent.id)
        .filter(
            RefundAccessEvent.source == command.source,
            RefundAccessEvent.invoice_id == command.invoice_id,
            RefundAccessEvent.email_hash == _email_hash(command.email),
            RefundAccessEvent.requested_state.in_(BLOCKING_STATES),
        )
        .first()
        is None
    )


def _targets_for_suspensions(
    db: Session,
    suspensions: Sequence[RefundAccessSuspension],
) -> List[RefundAccessTarget]:
    suspension_ids = {int(value.id) for value in suspensions}
    if not suspension_ids:
        return []
    rows = (
        db.query(RefundAccessTarget)
        .filter(RefundAccessTarget.suspension_id.in_(suspension_ids))
        .order_by(RefundAccessTarget.id)
        .all()
    )
    unique: Dict[Tuple[str, int], RefundAccessTarget] = {}
    for row in rows:
        unique.setdefault((str(row.entity_type), int(row.entity_id)), row)
    return list(unique.values())


def _historical_scope_for_command(
    db: Session,
    command: RefundAccessCommand,
) -> Optional[AccountScope]:
    own_suspension = (
        db.query(RefundAccessSuspension)
        .filter(
            RefundAccessSuspension.source == command.source,
            RefundAccessSuspension.invoice_id == command.invoice_id,
            RefundAccessSuspension.email_hash == _email_hash(command.email),
        )
        .first()
    )
    suspensions = [
        *([own_suspension] if own_suspension is not None else []),
        *_superseded_terminal_suspensions(
            db,
            command,
            root_client_id=(
                int(own_suspension.root_client_id)
                if own_suspension is not None
                and own_suspension.root_client_id is not None
                else None
            ),
        ),
    ]
    targets = _targets_for_suspensions(db, suspensions)
    if not targets:
        return None
    company_ids = tuple(
        sorted(
            {
                int(target.entity_id)
                for target in targets
                if target.entity_type == "company"
            }
        )
    )
    client_ids = tuple(
        sorted(
            {
                int(target.entity_id)
                for target in targets
                if target.entity_type == "client"
            }
        )
    )
    user_ids = tuple(
        sorted(
            {
                int(target.entity_id)
                for target in targets
                if target.entity_type == "user"
            }
        )
    )
    root_client_id = next(
        (
            int(suspension.root_client_id)
            for suspension in suspensions
            if suspension.root_client_id is not None
        ),
        client_ids[0] if client_ids else 0,
    )
    return AccountScope(
        root_client_id=root_client_id,
        company_ids=company_ids,
        client_ids=client_ids,
        user_ids=user_ids,
    )


def _resolve_command_scope(
    db: Session,
    command: RefundAccessCommand,
) -> Optional[AccountScope]:
    """Prefer an invoice's immutable owner when its old email was reused.

    The current email lookup remains authoritative while it still resolves to
    the same root, because that live graph can include workspaces created after
    the invoice was first observed. If the email now belongs to another root,
    however, the invoice targets are the only safe ownership evidence: applying
    the refund to the new email owner would block an unrelated account, while
    rejecting the event would leave the historical owner active.
    """
    own_suspension = (
        db.query(RefundAccessSuspension)
        .filter(
            RefundAccessSuspension.source == command.source,
            RefundAccessSuspension.invoice_id == command.invoice_id,
            RefundAccessSuspension.email_hash == _email_hash(command.email),
        )
        .first()
    )
    if own_suspension is not None and own_suspension.root_client_id is not None:
        bound_root = (
            db.query(Client)
            .filter(Client.id == int(own_suspension.root_client_id))
            .first()
        )
        if bound_root is not None and normalize_account_email(bound_root.email):
            bound_scope = _resolve_scope(db, str(bound_root.email))
            if (
                bound_scope is not None
                and int(bound_scope.root_client_id)
                == int(own_suspension.root_client_id)
            ):
                return bound_scope

    historical_scope = _historical_scope_for_command(db, command)
    if own_suspension is not None:
        own_targets_exist = (
            db.query(RefundAccessTarget.id)
            .filter(RefundAccessTarget.suspension_id == own_suspension.id)
            .first()
            is not None
        )
        if own_targets_exist and historical_scope is not None:
            return historical_scope

    live_scope = _resolve_scope(db, command.email)
    if live_scope is not None:
        return live_scope
    return historical_scope


def _companies_to_restart_for_restore(
    db: Session,
    targets: Sequence[RefundAccessTarget],
    *,
    email_hash: str,
    provisional_active_root_client_id: int,
    provisional_active_invoice_id: str,
    provisional_active_occurred_at: datetime,
    provisional_active_is_entitlement: bool,
    excluded_suspension_ids: Iterable[int] = (),
) -> List[Tuple[int, str]]:
    if _other_open_email_blocks(
        db,
        email_hash,
        excluded_suspension_ids=excluded_suspension_ids,
        provisional_active_invoice_id=provisional_active_invoice_id,
        provisional_active_occurred_at=provisional_active_occurred_at,
        provisional_active_is_entitlement=provisional_active_is_entitlement,
        provisional_active_email_hash=email_hash,
        provisional_active_root_client_id=provisional_active_root_client_id,
    ):
        return []

    result: List[Tuple[int, str]] = []
    company_targets = [
        target for target in targets if target.entity_type == "company"
    ]
    for target in company_targets:
        if _other_open_blocks(
            db,
            excluded_suspension_ids,
            "company",
            int(target.entity_id),
            provisional_active_invoice_id=provisional_active_invoice_id,
            provisional_active_occurred_at=provisional_active_occurred_at,
            provisional_active_is_entitlement=provisional_active_is_entitlement,
            provisional_active_email_hash=email_hash,
            provisional_active_root_client_id=provisional_active_root_client_id,
        ):
            continue
        marker = (
            db.query(RefundAccessEntityState)
            .filter_by(entity_type="company", entity_id=target.entity_id)
            .first()
        )
        company = db.query(Company).filter(Company.id == target.entity_id).first()
        if (
            marker
            and marker.restore_waha_enabled
            and not marker.waha_was_finalized
            and company
            and company.waha_session_name
        ):
            result.append((int(company.id), str(company.waha_session_name)))
    return result


def _restore_local_entities(
    db: Session,
    targets: Sequence[RefundAccessTarget],
    *,
    email_hash: str,
    provisional_active_root_client_id: int,
    provisional_active_invoice_id: str,
    provisional_active_occurred_at: datetime,
    provisional_active_is_entitlement: bool,
    excluded_suspension_ids: Iterable[int] = (),
) -> Tuple[int, int, int]:
    counts = {"company": 0, "client": 0, "user": 0}
    email_open_states = _other_open_email_blocks(
        db,
        email_hash,
        excluded_suspension_ids=excluded_suspension_ids,
        provisional_active_invoice_id=provisional_active_invoice_id,
        provisional_active_occurred_at=provisional_active_occurred_at,
        provisional_active_is_entitlement=provisional_active_is_entitlement,
        provisional_active_email_hash=email_hash,
        provisional_active_root_client_id=provisional_active_root_client_id,
    )
    for target in targets:
        entity_type = str(target.entity_type)
        entity_id = int(target.entity_id)
        open_states = [
            *_other_open_blocks(
                db,
                excluded_suspension_ids,
                entity_type,
                entity_id,
                provisional_active_invoice_id=provisional_active_invoice_id,
                provisional_active_occurred_at=provisional_active_occurred_at,
                provisional_active_is_entitlement=provisional_active_is_entitlement,
                provisional_active_email_hash=email_hash,
                provisional_active_root_client_id=provisional_active_root_client_id,
            ),
            *email_open_states,
        ]
        if open_states:
            if entity_type == "company":
                company = db.query(Company).filter(Company.id == entity_id).first()
                if company:
                    company.operational_status = (
                        "refunded" if "refunded" in open_states else "refund_pending"
                    )
                    company.waha_enabled = False
            continue

        marker = (
            db.query(RefundAccessEntityState)
            .filter_by(entity_type=entity_type, entity_id=entity_id)
            .with_for_update()
            .first()
        )
        if not marker:
            # A prior failed attempt may have removed the shared baseline after
            # restoring only part of the scope. The immutable target snapshot
            # is sufficient to converge local access, but never to recreate
            # credentials or a finalized WhatsApp session.
            if entity_type == "company":
                company = db.query(Company).filter(Company.id == entity_id).first()
                if company and company.operational_status != "active":
                    company.operational_status = "active"
                    company.waha_enabled = False
                    counts["company"] += 1
            elif entity_type == "client":
                client = db.query(Client).filter(Client.id == entity_id).first()
                if client and bool(client.is_active) != bool(target.previous_active):
                    client.is_active = bool(target.previous_active)
                    client.api_key = None
                    counts["client"] += 1
            elif entity_type == "user":
                user = db.query(User).filter(User.id == entity_id).first()
                if user and bool(user.is_active) != bool(target.previous_active):
                    user.is_active = bool(target.previous_active)
                    counts["user"] += 1
            continue
        if entity_type == "company":
            company = db.query(Company).filter(Company.id == entity_id).first()
            if company:
                company.operational_status = "active"
                company.waha_enabled = bool(
                    marker.restore_waha_enabled and not marker.waha_was_finalized
                )
                counts["company"] += 1
        elif entity_type == "client":
            client = db.query(Client).filter(Client.id == entity_id).first()
            if client:
                client.is_active = bool(marker.restore_active)
                # API keys are deliberately never restored.
                client.api_key = None
                counts["client"] += 1
        elif entity_type == "user":
            user = db.query(User).filter(User.id == entity_id).first()
            if user:
                user.is_active = bool(marker.restore_active)
                counts["user"] += 1
        db.delete(marker)
    return counts["company"], counts["client"], counts["user"]


def _ensure_restore_converged(
    db: Session,
    targets: Sequence[RefundAccessTarget],
) -> None:
    """Fail retryably instead of acknowledging a partially restored account."""
    failures: List[str] = []
    for target in targets:
        entity_type = str(target.entity_type)
        entity_id = int(target.entity_id)
        marker_exists = (
            db.query(RefundAccessEntityState.id)
            .filter_by(entity_type=entity_type, entity_id=entity_id)
            .first()
            is not None
        )
        if marker_exists:
            failures.append(f"{entity_type}:{entity_id}:marker")
            continue
        if entity_type == "company":
            entity = db.query(Company).filter(Company.id == entity_id).first()
            if entity is not None and entity.operational_status != "active":
                failures.append(f"company:{entity_id}:status")
        elif entity_type == "client":
            entity = db.query(Client).filter(Client.id == entity_id).first()
            if entity is not None and (
                bool(entity.is_active) != bool(target.previous_active)
                or entity.api_key is not None
            ):
                failures.append(f"client:{entity_id}:access")
        elif entity_type == "user":
            entity = db.query(User).filter(User.id == entity_id).first()
            if entity is not None and bool(entity.is_active) != bool(
                target.previous_active
            ):
                failures.append(f"user:{entity_id}:access")
    if failures:
        logger.warning(
            "Restauração local de reembolso não convergiu targets=%s",
            ",".join(failures),
        )
        raise RefundAccessRemoteError(
            "refund_access_restore_not_converged",
            company_ids=[
                int(target.entity_id)
                for target in targets
                if target.entity_type == "company"
            ],
            client_ids=[
                int(target.entity_id)
                for target in targets
                if target.entity_type == "client"
            ],
            user_ids=[
                int(target.entity_id)
                for target in targets
                if target.entity_type == "user"
            ],
        )


def _is_waha_missing_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "404" in message or "not found" in message


def _is_waha_already_started_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in ("already started", "already running", "already working", "status': 'working")
    )


def _apply_remaining_waha_timeout(client: Any, deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _RefundAccessWahaBudgetExceeded("refund_access_waha_budget_exhausted")
    # WAHAClient uses this value on every requests call. Recompute it between
    # calls so logout + deletion share one overall deadline.
    client.timeout = max(
        0.1,
        min(REFUND_ACCESS_WAHA_REQUEST_TIMEOUT_SECONDS, remaining),
    )


def _delete_waha_session_with_deadline(
    client: Any,
    session_name: str,
    deadline: float,
) -> None:
    _apply_remaining_waha_timeout(client, deadline)
    try:
        client.logout_session(session_name)
    except WAHAException as exc:
        # Preserve the SDK's existing best-effort logout semantics: deletion is
        # still the authoritative revocation action.
        logger.warning(
            "Falha no logout WAHA anterior à exclusão error=%s",
            exc.__class__.__name__,
        )
    _apply_remaining_waha_timeout(client, deadline)
    client.delete_session(session_name, logout=False)


def _run_waha_block_actions(
    db: Session,
    suspension: RefundAccessSuspension,
    state: str,
) -> None:
    from backend.config import WAHA_API_KEY, WAHA_BASE_URL

    targets = (
        db.query(RefundAccessTarget)
        .filter(RefundAccessTarget.suspension_id == suspension.id)
        .all()
    )
    company_ids = [
        int(row.entity_id) for row in targets if row.entity_type == "company"
    ]
    client_ids = [
        int(row.entity_id) for row in targets if row.entity_type == "client"
    ]
    user_ids = [
        int(row.entity_id) for row in targets if row.entity_type == "user"
    ]
    company_rows = db.query(Company).filter(Company.id.in_(company_ids)).all() if company_ids else []
    companies = [
        (int(company.id), str(company.waha_session_name or "").strip())
        for company in company_rows
    ]
    # Do not leave a database transaction idle while requests is waiting on
    # WAHA. The outer advisory locks remain on their dedicated connection.
    db.rollback()
    deadline = time.monotonic() + REFUND_ACCESS_WAHA_TOTAL_BUDGET_SECONDS
    try:
        client = get_waha_client(
            base_url=WAHA_BASE_URL,
            api_key=WAHA_API_KEY,
            timeout=REFUND_ACCESS_WAHA_REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning(
            "Falha ao inicializar cliente WAHA para bloqueio error=%s",
            exc.__class__.__name__,
        )
        raise RefundAccessRemoteError(
            "waha_block_client_initialization_failed",
            company_ids=company_ids,
            client_ids=client_ids,
            user_ids=user_ids,
        ) from exc
    failures: List[int] = []
    for company_id, session_name in companies:
        if not session_name:
            continue
        try:
            _apply_remaining_waha_timeout(client, deadline)
            if state == "refunded":
                _delete_waha_session_with_deadline(client, session_name, deadline)
            else:
                client.stop_session(session_name)
        except _RefundAccessWahaBudgetExceeded:
            logger.warning(
                "Orçamento WAHA esgotado durante bloqueio company_id=%s action=%s",
                company_id,
                state,
            )
            failures.append(company_id)
            break
        except WAHAException as exc:
            if _is_waha_missing_error(exc):
                continue
            logger.warning(
                "Falha em ação WAHA de bloqueio company_id=%s action=%s error=%s",
                company_id,
                state,
                exc.__class__.__name__,
            )
            failures.append(company_id)
        except Exception as exc:
            logger.warning(
                "Falha inesperada em ação WAHA de bloqueio company_id=%s "
                "action=%s error=%s",
                company_id,
                state,
                exc.__class__.__name__,
            )
            failures.append(company_id)
    if failures:
        raise RefundAccessRemoteError(
            "waha_block_action_failed",
            company_ids=company_ids,
            client_ids=client_ids,
            user_ids=user_ids,
        )


def _run_waha_restore_actions(
    db: Session,
    targets: Sequence[RefundAccessTarget],
    *,
    email_hash: str,
    provisional_active_root_client_id: int,
    provisional_active_invoice_id: str,
    provisional_active_occurred_at: datetime,
    provisional_active_is_entitlement: bool,
    excluded_suspension_ids: Iterable[int] = (),
) -> None:
    from backend.config import WAHA_API_KEY, WAHA_BASE_URL

    companies = _companies_to_restart_for_restore(
        db,
        targets,
        email_hash=email_hash,
        provisional_active_root_client_id=provisional_active_root_client_id,
        provisional_active_invoice_id=provisional_active_invoice_id,
        provisional_active_occurred_at=provisional_active_occurred_at,
        provisional_active_is_entitlement=provisional_active_is_entitlement,
        excluded_suspension_ids=excluded_suspension_ids,
    )
    if not companies:
        return
    client_ids = [
        int(target.entity_id)
        for target in targets
        if target.entity_type == "client"
    ]
    user_ids = [
        int(target.entity_id)
        for target in targets
        if target.entity_type == "user"
    ]
    # Close the read transaction before blocking on the remote service.
    db.rollback()
    deadline = time.monotonic() + REFUND_ACCESS_WAHA_TOTAL_BUDGET_SECONDS
    try:
        client = get_waha_client(
            base_url=WAHA_BASE_URL,
            api_key=WAHA_API_KEY,
            timeout=REFUND_ACCESS_WAHA_REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning(
            "Falha ao inicializar cliente WAHA para restauração error=%s",
            exc.__class__.__name__,
        )
        raise RefundAccessRemoteError(
            "waha_restore_client_initialization_failed",
            company_ids=[company_id for company_id, _ in companies],
            client_ids=client_ids,
            user_ids=user_ids,
        ) from exc
    failures: List[int] = []
    for company_id, session_name in companies:
        try:
            _apply_remaining_waha_timeout(client, deadline)
            client.start_session(session_name)
        except _RefundAccessWahaBudgetExceeded:
            logger.warning(
                "Orçamento WAHA esgotado durante restauração company_id=%s",
                company_id,
            )
            failures.append(company_id)
            break
        except WAHAException as exc:
            if _is_waha_already_started_error(exc):
                continue
            logger.warning(
                "Falha ao restaurar WAHA company_id=%s error=%s",
                company_id,
                exc.__class__.__name__,
            )
            failures.append(company_id)
        except Exception as exc:
            logger.warning(
                "Falha inesperada ao restaurar WAHA company_id=%s error=%s",
                company_id,
                exc.__class__.__name__,
            )
            failures.append(company_id)
    if failures:
        raise RefundAccessRemoteError(
            "waha_restore_action_failed",
            company_ids=[company_id for company_id, _ in companies],
            client_ids=client_ids,
            user_ids=user_ids,
        )


def _complete_event(
    db: Session,
    event: RefundAccessEvent,
    result: RefundAccessResult,
) -> RefundAccessResult:
    event.status = "completed"
    event.error_code = None
    event.response_payload = result.as_payload()
    event.completed_at = _utcnow()
    db.commit()
    return result


def _fail_event(
    db: Session,
    event: RefundAccessEvent,
    error: RefundAccessError,
) -> None:
    event.status = "failed"
    event.error_code = error.code
    event.response_payload = {"retryable": error.retryable}
    db.commit()


def _process_refund_access_locked(
    db: Session,
    raw_command: RefundAccessCommand,
    scope: Optional[AccountScope],
) -> RefundAccessResult:
    """Apply one event. Local suspension survives any remote WAHA failure."""

    command = _normalize_command(raw_command)
    event = _find_existing_event(db, command)
    rediscovered = False
    completed_payload: Optional[Dict[str, Any]] = None
    completed_not_found = False
    if event and event.status == "completed":
        payload = dict(event.response_payload or {})
        if payload.get("status") != "not_found":
            completed_payload = payload
        else:
            completed_not_found = True

    suspension = (
        db.query(RefundAccessSuspension)
        .filter(
            RefundAccessSuspension.source == command.source,
            RefundAccessSuspension.invoice_id == command.invoice_id,
        )
        .with_for_update()
        .first()
    )
    if suspension and suspension.email_hash != _email_hash(command.email):
        raise RefundAccessConflict("invoice_email_mismatch")
    if scope is None:
        scope = _historical_scope_for_command(db, command)

    # The stored ACK reflects the world when the event first completed. A
    # later, strictly newer entitlement may make that terminal harmless, so a
    # replay must expose the current temporal decision instead of returning the
    # old ``shadowed=false`` payload. Keep the audit row and watermark immutable.
    if (
        event
        and event.status == "completed"
        and command.state == "refunded"
        and suspension
        and is_refund_suspension_superseded(db, suspension)
    ):
        return RefundAccessResult(
            status="stale",
            state=(
                _effective_scope_state(
                    db,
                    scope,
                    email_hash=_email_hash(command.email),
                )
                if scope
                else _effective_email_state(db, _email_hash(command.email))
            ),
            company_ids=scope.company_ids if scope else (),
            client_ids=scope.client_ids if scope else (),
            user_ids=scope.user_ids if scope else (),
            excluded_shared_company_ids=(
                scope.excluded_shared_company_ids if scope else ()
            ),
            shadowed_by_newer_entitlement=True,
        )

    if completed_payload is not None:
        return RefundAccessResult(
            status="duplicate",
            state=(
                _effective_scope_state(
                    db,
                    scope,
                    email_hash=_email_hash(command.email),
                )
                if scope
                else _effective_email_state(db, _email_hash(command.email))
            ),
            company_ids=scope.company_ids if scope else (),
            client_ids=scope.client_ids if scope else (),
            user_ids=scope.user_ids if scope else (),
            clients_affected=int(completed_payload.get("clientsAffected") or 0),
            users_affected=int(completed_payload.get("usersAffected") or 0),
            companies_affected=int(completed_payload.get("companiesAffected") or 0),
            queues_cancelled=int(completed_payload.get("queuesCancelled") or 0),
            excluded_shared_company_ids=(
                scope.excluded_shared_company_ids if scope else ()
            ),
            supersedes_prior_terminal=bool(
                completed_payload.get("supersedesPriorTerminal")
            ),
            new_entitlement=bool(completed_payload.get("newEntitlement")),
            shadowed_by_newer_entitlement=bool(
                completed_payload.get("shadowedByNewerEntitlement")
            ),
        )
    if scope is None:
        if completed_not_found:
            return RefundAccessResult(
                status="duplicate",
                state=_effective_email_state(db, _email_hash(command.email)),
            )
        if not event:
            event = _create_event(db, command)
        if command.state in BLOCKING_STATES:
            if not suspension:
                suspension = RefundAccessSuspension(
                    source=command.source,
                    invoice_id=command.invoice_id,
                    email_hash=_email_hash(command.email),
                    root_client_id=None,
                    state=command.state,
                    latest_event_id=command.event_id,
                    latest_occurred_at=command.occurred_at,
                )
                db.add(suspension)
                db.flush()
            elif suspension.state == "refunded" and command.state == "refund_pending":
                result = RefundAccessResult(
                    status="stale",
                    state=_effective_email_state(db, _email_hash(command.email)),
                )
                event.suspension_id = suspension.id
                return _complete_event(db, event, result)
            elif (
                suspension.state == "refunded"
                and command.state == "refunded"
                and is_refund_suspension_superseded(db, suspension)
            ):
                event.suspension_id = suspension.id
                return _complete_event(
                    db,
                    event,
                    RefundAccessResult(
                        status="stale",
                        state=_effective_email_state(
                            db,
                            _email_hash(command.email),
                        ),
                        shadowed_by_newer_entitlement=True,
                    ),
                )
            elif (
                suspension.state == "refunded"
                and command.state == "refunded"
                and _is_stale(suspension, command)
            ):
                event.suspension_id = suspension.id
                return _complete_event(
                    db,
                    event,
                    RefundAccessResult(
                        status="stale",
                        state=_effective_email_state(db, _email_hash(command.email)),
                    ),
                )
            elif (
                command.state != "refunded"
                and _is_stale(suspension, command)
            ):
                event.suspension_id = suspension.id
                return _complete_event(
                    db,
                    event,
                    RefundAccessResult(
                        status="stale",
                        state=_effective_email_state(db, _email_hash(command.email)),
                    ),
                )
            else:
                # The first terminal transition fixes the temporal watermark.
                # Later repair events for the same invoice remain auditable but
                # cannot move the block past a legitimate newer repurchase.
                if not (
                    suspension.state == "refunded"
                    and command.state == "refunded"
                ):
                    suspension.state = command.state
                    suspension.latest_event_id = command.event_id
                    suspension.latest_occurred_at = max(
                        _aware_utc(suspension.latest_occurred_at),
                        command.occurred_at,
                    )
            event.suspension_id = suspension.id
        elif suspension:
            if suspension.state == "refunded":
                raise RefundAccessConflict("refunded_state_is_terminal")
            if _is_stale(suspension, command):
                event.suspension_id = suspension.id
                return _complete_event(
                    db,
                    event,
                    RefundAccessResult(
                        status="stale",
                        state=_effective_email_state(db, _email_hash(command.email)),
                    ),
                )
            suspension.state = "active"
            suspension.latest_event_id = command.event_id
            suspension.latest_occurred_at = command.occurred_at
            event.suspension_id = suspension.id
        else:
            suspension = RefundAccessSuspension(
                source=command.source,
                invoice_id=command.invoice_id,
                email_hash=_email_hash(command.email),
                root_client_id=None,
                state="active",
                latest_event_id=command.event_id,
                latest_occurred_at=command.occurred_at,
            )
            db.add(suspension)
            db.flush()
            event.suspension_id = suspension.id
        if (
            command.state == "refunded"
            and suspension is not None
            and is_refund_suspension_superseded(db, suspension)
        ):
            return _complete_event(
                db,
                event,
                RefundAccessResult(
                    status="stale",
                    state=_effective_email_state(
                        db,
                        _email_hash(command.email),
                    ),
                    shadowed_by_newer_entitlement=True,
                ),
            )
        result = RefundAccessResult(
            status="processed" if command.state == "active" else "not_found",
            state=_effective_email_state(
                db,
                _email_hash(command.email),
                provisional_active_invoice_id=(
                    command.invoice_id if command.state == "active" else None
                ),
                provisional_active_occurred_at=(
                    command.occurred_at if command.state == "active" else None
                ),
                provisional_active_is_entitlement=(
                    _active_command_is_new_entitlement(db, command)
                ),
            ),
            supersedes_prior_terminal=bool(
                command.state == "active"
                and _superseded_terminal_suspensions(db, command)
            ),
            new_entitlement=bool(
                command.state == "active"
                and _active_command_is_new_entitlement(db, command)
                and _effective_email_state(
                    db,
                    _email_hash(command.email),
                    provisional_active_invoice_id=command.invoice_id,
                    provisional_active_occurred_at=command.occurred_at,
                    provisional_active_is_entitlement=True,
                )
                == "active"
            ),
        )
        return _complete_event(db, event, result)

    if completed_not_found:
        can_bind_latest_tombstone = bool(
            suspension
            and command.state in BLOCKING_STATES
            and suspension.root_client_id is None
            and suspension.latest_event_id == command.event_id
            and suspension.state == command.state
        )
        if not can_bind_latest_tombstone:
            if suspension:
                if suspension.email_hash != _email_hash(command.email):
                    raise RefundAccessConflict("invoice_email_mismatch")
                event.suspension_id = suspension.id
                return _complete_event(
                    db,
                    event,
                    RefundAccessResult(
                        status="stale",
                        state=_effective_scope_state(
                            db,
                            scope,
                            email_hash=_email_hash(command.email),
                        ),
                        company_ids=scope.company_ids,
                        client_ids=scope.client_ids,
                        user_ids=scope.user_ids,
                        excluded_shared_company_ids=scope.excluded_shared_company_ids,
                    ),
                )
            return RefundAccessResult(
                status="duplicate",
                state=_effective_scope_state(
                    db,
                    scope,
                    email_hash=_email_hash(command.email),
                ),
                company_ids=scope.company_ids,
                client_ids=scope.client_ids,
                user_ids=scope.user_ids,
                excluded_shared_company_ids=scope.excluded_shared_company_ids,
            )
        event.status = "processing"
        event.completed_at = None
        event.response_payload = {}
        rediscovered = True

    if command.state == "active" and suspension is None:
        if not event:
            event = _create_event(db, command)
        suspension = RefundAccessSuspension(
            source=command.source,
            invoice_id=command.invoice_id,
            email_hash=_email_hash(command.email),
            root_client_id=scope.root_client_id,
            state="active",
            latest_event_id=command.event_id,
            latest_occurred_at=command.occurred_at,
        )
        db.add(suspension)
        db.flush()
        _bind_scope_targets(db, suspension, scope)
        event.suspension_id = suspension.id

    if suspension and suspension.root_client_id not in (None, scope.root_client_id):
        raise RefundAccessConflict("invoice_identity_mismatch")
    if suspension and suspension.email_hash != _email_hash(command.email):
        raise RefundAccessConflict("invoice_email_mismatch")
    if suspension and suspension.state == "refunded" and command.state == "active":
        raise RefundAccessConflict(
            "refunded_state_is_terminal",
            company_ids=scope.company_ids,
            client_ids=scope.client_ids,
            user_ids=scope.user_ids,
        )
    if suspension and suspension.state == "refunded" and command.state == "refund_pending":
        if not event:
            event = _create_event(db, command)
        event.suspension_id = suspension.id
        return _complete_event(
            db,
            event,
            RefundAccessResult(
                status="stale",
                state=_effective_scope_state(
                    db,
                    scope,
                    email_hash=_email_hash(command.email),
                ),
                company_ids=scope.company_ids,
                client_ids=scope.client_ids,
                user_ids=scope.user_ids,
                excluded_shared_company_ids=scope.excluded_shared_company_ids,
            ),
        )
    if (
        suspension
        and suspension.state == "refunded"
        and command.state == "refunded"
        and is_refund_suspension_superseded(db, suspension)
    ):
        if not event:
            event = _create_event(db, command)
        event.suspension_id = suspension.id
        return _complete_event(
            db,
            event,
            RefundAccessResult(
                status="stale",
                state=_effective_scope_state(
                    db,
                    scope,
                    email_hash=_email_hash(command.email),
                ),
                company_ids=scope.company_ids,
                client_ids=scope.client_ids,
                user_ids=scope.user_ids,
                excluded_shared_company_ids=scope.excluded_shared_company_ids,
                shadowed_by_newer_entitlement=True,
            ),
        )

    was_unbound_tombstone = bool(suspension and suspension.root_client_id is None)
    retrying = bool(event and event.status in {"failed", "processing"} and not rediscovered)
    same_applied_transition = bool(
        retrying
        and suspension
        and suspension.latest_event_id == command.event_id
        and suspension.state == command.state
    )
    if (
        suspension
        and not same_applied_transition
        and not (rediscovered and was_unbound_tombstone)
        and not (
            command.state == "refunded"
            and suspension.state != "refunded"
        )
        and _is_stale(suspension, command)
    ):
        if not event:
            event = _create_event(db, command)
        event.suspension_id = suspension.id
        result = RefundAccessResult(
            status="stale",
            state=_effective_scope_state(
                db,
                scope,
                email_hash=_email_hash(command.email),
            ),
            company_ids=scope.company_ids,
            client_ids=scope.client_ids,
            user_ids=scope.user_ids,
            excluded_shared_company_ids=scope.excluded_shared_company_ids,
        )
        return _complete_event(db, event, result)

    if suspension and suspension.root_client_id is None:
        _bind_scope_targets(db, suspension, scope)
        suspension.root_client_id = scope.root_client_id

    if not event:
        event = _create_event(db, command)

    if command.state in BLOCKING_STATES:
        suspension_was_missing = suspension is None
        if not suspension:
            suspension = RefundAccessSuspension(
                source=command.source,
                invoice_id=command.invoice_id,
                email_hash=_email_hash(command.email),
                root_client_id=scope.root_client_id,
                state=command.state,
                latest_event_id=command.event_id,
                latest_occurred_at=command.occurred_at,
            )
            db.add(suspension)
            db.flush()

        if (
            command.state == "refunded"
            and is_refund_suspension_superseded(db, suspension)
        ):
            if suspension_was_missing:
                _bind_scope_targets(db, suspension, scope)
            event.suspension_id = suspension.id
            return _complete_event(
                db,
                event,
                RefundAccessResult(
                    status="stale",
                    state=_effective_scope_state(
                        db,
                        scope,
                        email_hash=_email_hash(command.email),
                    ),
                    company_ids=scope.company_ids,
                    client_ids=scope.client_ids,
                    user_ids=scope.user_ids,
                    excluded_shared_company_ids=scope.excluded_shared_company_ids,
                    shadowed_by_newer_entitlement=True,
                ),
            )

        if not retrying or suspension.state != command.state:
            already_terminal = (
                suspension.state == "refunded"
                and command.state == "refunded"
            )
            if not already_terminal:
                suspension.state = command.state
                suspension.latest_event_id = command.event_id
                suspension.latest_occurred_at = (
                    max(
                        _aware_utc(suspension.latest_occurred_at),
                        command.occurred_at,
                    )
                    if command.state == "refunded"
                    else command.occurred_at
                )
            if (
                command.state == "refunded"
                and is_refund_suspension_superseded(db, suspension)
            ):
                if suspension_was_missing:
                    _bind_scope_targets(db, suspension, scope)
                event.suspension_id = suspension.id
                return _complete_event(
                    db,
                    event,
                    RefundAccessResult(
                        status="stale",
                        state=_effective_scope_state(
                            db,
                            scope,
                            email_hash=_email_hash(command.email),
                        ),
                        company_ids=scope.company_ids,
                        client_ids=scope.client_ids,
                        user_ids=scope.user_ids,
                        excluded_shared_company_ids=scope.excluded_shared_company_ids,
                        shadowed_by_newer_entitlement=True,
                    ),
                )
            companies_count, clients_count, users_count, queues_count = _apply_local_block(
                db,
                suspension,
                scope,
                command.state,
            )
            event.suspension_id = suspension.id
            db.commit()
        else:
            companies_count = len(scope.company_ids)
            clients_count = len(scope.client_ids)
            users_count = len(scope.user_ids)
            queues_count = 0
            event.suspension_id = suspension.id
            db.commit()

        try:
            _run_waha_block_actions(db, suspension, command.state)
        except RefundAccessRemoteError as exc:
            _fail_event(db, event, exc)
            raise
        result = RefundAccessResult(
            status="processed",
            state=_effective_scope_state(
                db,
                scope,
                email_hash=_email_hash(command.email),
            ),
            company_ids=scope.company_ids,
            client_ids=scope.client_ids,
            user_ids=scope.user_ids,
            clients_affected=clients_count,
            users_affected=users_count,
            companies_affected=companies_count,
            queues_cancelled=queues_count,
            excluded_shared_company_ids=scope.excluded_shared_company_ids,
        )
        return _complete_event(db, event, result)

    # Restore is deliberately two-phase: remote session readiness first, then
    # local access. A failed start leaves every local gate closed.
    event.suspension_id = suspension.id
    active_is_entitlement = _active_command_is_new_entitlement(db, command)
    superseded_terminals = _superseded_terminal_suspensions(
        db,
        command,
        root_client_id=scope.root_client_id,
    )
    restore_suspensions = [suspension, *superseded_terminals]
    restore_targets = _targets_for_suspensions(db, restore_suspensions)
    excluded_suspension_ids = (int(suspension.id),)
    db.commit()
    try:
        _run_waha_restore_actions(
            db,
            restore_targets,
            email_hash=_email_hash(command.email),
            provisional_active_root_client_id=scope.root_client_id,
            provisional_active_invoice_id=command.invoice_id,
            provisional_active_occurred_at=command.occurred_at,
            provisional_active_is_entitlement=active_is_entitlement,
            excluded_suspension_ids=excluded_suspension_ids,
        )
    except RefundAccessRemoteError as exc:
        _fail_event(db, event, exc)
        raise

    try:
        suspension.state = "active"
        suspension.latest_event_id = command.event_id
        suspension.latest_occurred_at = command.occurred_at
        companies_count, clients_count, users_count = _restore_local_entities(
            db,
            email_hash=_email_hash(command.email),
            provisional_active_root_client_id=scope.root_client_id,
            provisional_active_invoice_id=command.invoice_id,
            provisional_active_occurred_at=command.occurred_at,
            provisional_active_is_entitlement=active_is_entitlement,
            excluded_suspension_ids=excluded_suspension_ids,
            targets=restore_targets,
        )
        effective_state = _effective_scope_state(
            db,
            scope,
            email_hash=_email_hash(command.email),
            provisional_active_invoice_id=command.invoice_id,
            provisional_active_occurred_at=command.occurred_at,
            provisional_active_is_entitlement=active_is_entitlement,
        )
        if superseded_terminals:
            if effective_state != "active":
                raise RefundAccessRemoteError(
                    "refund_access_restore_effective_state_blocked",
                    company_ids=scope.company_ids,
                    client_ids=scope.client_ids,
                    user_ids=scope.user_ids,
                )
            _ensure_restore_converged(db, restore_targets)
        result = RefundAccessResult(
            status="processed",
            state=effective_state,
            company_ids=scope.company_ids,
            client_ids=scope.client_ids,
            user_ids=scope.user_ids,
            clients_affected=clients_count,
            users_affected=users_count,
            companies_affected=companies_count,
            excluded_shared_company_ids=scope.excluded_shared_company_ids,
            supersedes_prior_terminal=bool(
                superseded_terminals and active_is_entitlement
            ),
            new_entitlement=bool(
                active_is_entitlement and effective_state == "active"
            ),
        )
    except RefundAccessRemoteError as exc:
        _fail_event(db, event, exc)
        raise
    return _complete_event(db, event, result)


def process_refund_access(
    db: Session,
    raw_command: RefundAccessCommand,
) -> RefundAccessResult:
    """Serialize identities and every entity in scope before state mutation."""

    command = _normalize_command(raw_command)
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        scope = _resolve_command_scope(db, command)
        return _process_refund_access_locked(
            db,
            command,
            scope,
        )

    identity_lock_keys = sorted(
        {
            f"refund-access:invoice:{command.source}:{command.invoice_id}",
            f"refund-access:event:{command.event_id}",
            f"refund-access:idempotency:{command.idempotency_key}",
            f"refund-access:email:{_email_hash(command.email)}",
        }
    )
    with bind.connect() as lock_connection:
        acquired_lock_keys: List[str] = []
        entity_lock_keys: List[str] = []
        try:
            _apply_refund_access_lock_timeout(lock_connection, db)
            for lock_key in identity_lock_keys:
                lock_connection.execute(
                    text("SELECT pg_advisory_lock(hashtextextended(:lock_key, 0))"),
                    {"lock_key": lock_key},
                )
                acquired_lock_keys.append(lock_key)

            scope = _resolve_command_scope(db, command)
            for _ in range(5):
                candidate_entity_lock_keys = _command_entity_lock_keys(
                    db,
                    command,
                    scope,
                )
                for lock_key in candidate_entity_lock_keys:
                    lock_connection.execute(
                        text("SELECT pg_advisory_lock(hashtextextended(:lock_key, 0))"),
                        {"lock_key": lock_key},
                    )
                    # Session advisory locks survive transaction rollback.
                    # Track each successful acquisition immediately so a
                    # timeout halfway through the candidate set cannot leak a
                    # lock into the SQLAlchemy pool.
                    entity_lock_keys.append(lock_key)
                    acquired_lock_keys.append(lock_key)

                locked_scope = _resolve_command_scope(db, command)
                if (
                    _command_entity_lock_keys(db, command, locked_scope)
                    == entity_lock_keys
                ):
                    return _process_refund_access_locked(db, command, locked_scope)

                _release_selected_session_advisory_locks(
                    lock_connection,
                    entity_lock_keys,
                    acquired_lock_keys,
                )
                entity_lock_keys = []
                scope = locked_scope
            raise RefundAccessConflict("scope_changed_during_lock")
        finally:
            _release_all_session_advisory_locks(
                lock_connection,
                acquired_lock_keys,
            )


def _refund_access_lock_timeout_ms(db: Session) -> Optional[int]:
    info = getattr(db, "info", None)
    if not isinstance(info, dict):
        return None
    configured = info.get(REFUND_ACCESS_LOCK_TIMEOUT_MS_INFO_KEY)
    if configured is None:
        return None
    try:
        timeout_ms = int(configured)
    except (TypeError, ValueError):
        return None
    return max(
        REFUND_ACCESS_LOCK_TIMEOUT_MIN_MS,
        min(timeout_ms, REFUND_ACCESS_LOCK_TIMEOUT_MAX_MS),
    )


def _apply_refund_access_lock_timeout(lock_connection, db: Session) -> None:
    timeout_ms = _refund_access_lock_timeout_ms(db)
    if timeout_ms is None:
        return
    lock_connection.execute(
        text("SELECT set_config('lock_timeout', :lock_timeout, true)"),
        {"lock_timeout": f"{timeout_ms}ms"},
    )


def _remove_last_lock_key(lock_keys: List[str], lock_key: str) -> None:
    for index in range(len(lock_keys) - 1, -1, -1):
        if lock_keys[index] == lock_key:
            del lock_keys[index]
            return


def _release_selected_session_advisory_locks(
    lock_connection,
    selected_lock_keys: Sequence[str],
    acquired_lock_keys: List[str],
) -> None:
    for lock_key in reversed(selected_lock_keys):
        lock_connection.execute(
            text("SELECT pg_advisory_unlock(hashtextextended(:lock_key, 0))"),
            {"lock_key": lock_key},
        )
        _remove_last_lock_key(acquired_lock_keys, lock_key)


def _release_all_session_advisory_locks(
    lock_connection,
    acquired_lock_keys: List[str],
) -> None:
    if not acquired_lock_keys:
        return

    # lock_timeout aborts the transaction that was waiting. Roll it back first;
    # session advisory locks remain held and can then be explicitly released.
    try:
        lock_connection.rollback()
    except Exception as exc:
        logger.warning(
            "[RefundAccess] Falha ao limpar transação do lock connection "
            "error_type=%s",
            exc.__class__.__name__,
        )

    cleanup_failed = False
    for lock_key in reversed(list(acquired_lock_keys)):
        try:
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:lock_key, 0))"),
                {"lock_key": lock_key},
            )
            _remove_last_lock_key(acquired_lock_keys, lock_key)
        except Exception as exc:
            cleanup_failed = True
            logger.error(
                "[RefundAccess] Falha ao liberar advisory lock; conexão será "
                "invalidada lock_key_hash=%s error_type=%s",
                hashlib.sha256(lock_key.encode("utf-8")).hexdigest()[:12],
                exc.__class__.__name__,
            )
            try:
                lock_connection.rollback()
            except Exception:
                pass

    if cleanup_failed or acquired_lock_keys:
        # Closing the physical PostgreSQL session is the final fail-safe for
        # session advisory locks. Never return a possibly locked connection to
        # the pool.
        lock_connection.invalidate()


def _scope_entity_lock_keys(scope: Optional[AccountScope]) -> List[str]:
    if scope is None:
        return []
    keys: List[str] = []
    keys.extend(
        f"refund-access:entity:company:{entity_id}"
        for entity_id in sorted(scope.company_ids)
    )
    keys.extend(
        f"refund-access:entity:client:{entity_id}"
        for entity_id in sorted(scope.client_ids)
    )
    keys.extend(
        f"refund-access:entity:user:{entity_id}"
        for entity_id in sorted(scope.user_ids)
    )
    return keys


def _command_entity_lock_keys(
    db: Session,
    command: RefundAccessCommand,
    scope: Optional[AccountScope],
) -> List[str]:
    """Lock both the live scope and historical targets restored by this invoice."""
    company_ids = set(scope.company_ids if scope else ())
    client_ids = set(scope.client_ids if scope else ())
    user_ids = set(scope.user_ids if scope else ())
    historical_targets = (
        db.query(RefundAccessTarget.entity_type, RefundAccessTarget.entity_id)
        .join(
            RefundAccessSuspension,
            RefundAccessSuspension.id == RefundAccessTarget.suspension_id,
        )
        .filter(
            RefundAccessSuspension.source == command.source,
            RefundAccessSuspension.invoice_id == command.invoice_id,
        )
        .all()
    )
    superseded_targets = _targets_for_suspensions(
        db,
        _superseded_terminal_suspensions(
            db,
            command,
            root_client_id=scope.root_client_id if scope else None,
        ),
    )
    for target in [*historical_targets, *superseded_targets]:
        entity_type = str(target.entity_type)
        entity_id = int(target.entity_id)
        if entity_type == "company":
            company_ids.add(entity_id)
        elif entity_type == "client":
            client_ids.add(entity_id)
        elif entity_type == "user":
            user_ids.add(entity_id)
    return _scope_entity_lock_keys(
        AccountScope(
            root_client_id=scope.root_client_id if scope else 0,
            company_ids=tuple(company_ids),
            client_ids=tuple(client_ids),
            user_ids=tuple(user_ids),
        )
    )
