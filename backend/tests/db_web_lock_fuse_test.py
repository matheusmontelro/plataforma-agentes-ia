import asyncio
import os
import time
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool


os.environ.setdefault(
    "DATABASE_URL",
    "sqlite:////tmp/agentive-db-web-lock-fuse-test.db",
)

from backend import db as db_module  # noqa: E402
from backend.services import company_access_control  # noqa: E402
from backend.services import refund_access_service  # noqa: E402
from backend.worker import db_pool_lifecycle  # noqa: E402


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _FakePostgresSession:
    def __init__(self, results=(), *, web=False):
        self.info = {}
        if web:
            self.info[db_module.WEB_REQUEST_SESSION_INFO_KEY] = True
        self.results = iter(results)
        self.executed = []
        self.rollbacks = 0
        self.bind = SimpleNamespace(
            dialect=SimpleNamespace(name="postgresql")
        )

    def get_bind(self):
        return self.bind

    def execute(self, statement, parameters):
        self.executed.append((str(statement), parameters))
        try:
            result = next(self.results)
        except StopIteration:
            result = True
        return _ScalarResult(result)

    def rollback(self):
        self.rollbacks += 1


def test_get_db_marks_request_session_before_first_transaction():
    dependency = db_module.get_db()
    session = next(dependency)
    try:
        assert session.info[db_module.WEB_REQUEST_SESSION_INFO_KEY] is True
    finally:
        dependency.close()


def test_celery_child_replaces_inherited_sqlalchemy_pool(monkeypatch):
    dispose_calls = []

    class FakeEngine:
        def dispose(self, *, close):
            dispose_calls.append(close)

    monkeypatch.setattr(db_module, "engine", FakeEngine())

    db_pool_lifecycle.dispose_inherited_sqlalchemy_pool(
        signal="worker_process_init"
    )

    assert dispose_calls == [False]


def test_after_begin_applies_transaction_local_lock_timeout_only_to_web_pg():
    statements = []

    class _Connection:
        dialect = SimpleNamespace(name="postgresql")

        def exec_driver_sql(self, statement):
            statements.append(statement)

    marked = SimpleNamespace(
        info={db_module.WEB_REQUEST_SESSION_INFO_KEY: True}
    )
    explicitly_bounded = SimpleNamespace(
        info={db_module.TRANSACTION_LOCK_TIMEOUT_MS_INFO_KEY: 2500}
    )
    unmarked = SimpleNamespace(info={})

    db_module.apply_web_transaction_lock_timeout(marked, object(), _Connection())
    db_module.apply_web_transaction_lock_timeout(
        explicitly_bounded,
        object(),
        _Connection(),
    )
    db_module.apply_web_transaction_lock_timeout(unmarked, object(), _Connection())

    assert statements == [
        "SET LOCAL lock_timeout = "
        f"'{db_module.WEB_TRANSACTION_LOCK_TIMEOUT_MS}ms'",
        "SET LOCAL lock_timeout = '2500ms'",
    ]


def test_web_identity_lock_is_try_only_and_exposes_retry_after():
    session = _FakePostgresSession([False], web=True)

    with pytest.raises(
        company_access_control.RefundIdentityOperationBusyError
    ) as error:
        company_access_control.lock_refund_identity_for_creation(
            session,
            "owner@example.com",
        )

    assert "pg_try_advisory_xact_lock" in session.executed[0][0]
    assert "pg_advisory_xact_lock(" not in session.executed[0][0]
    assert session.rollbacks == 1
    assert error.value.retry_after_seconds >= 1


def test_web_entity_lock_is_try_only_and_exposes_retry_after():
    session = _FakePostgresSession([True, False], web=True)

    with pytest.raises(
        company_access_control.CompanyOperationalLockBusyError
    ) as error:
        company_access_control.lock_refund_entities_for_mutation(
            session,
            company_ids=[7],
            client_ids=[11],
        )

    assert all(
        "pg_try_advisory_xact_lock" in statement
        and "pg_advisory_xact_lock(" not in statement
        for statement, _parameters in session.executed
    )
    assert session.rollbacks == 1
    assert error.value.company_id == 7
    assert error.value.retry_after_seconds >= 1


def test_unmarked_sessionlocal_paths_keep_blocking_refund_locks():
    identity_session = _FakePostgresSession()
    entity_session = _FakePostgresSession()

    company_access_control.lock_refund_identity_for_creation(
        identity_session,
        "owner@example.com",
    )
    company_access_control.lock_refund_entities_for_mutation(
        entity_session,
        company_ids=[7],
    )

    for statement, _parameters in (
        identity_session.executed + entity_session.executed
    ):
        assert "pg_advisory_xact_lock(" in statement
        assert "pg_try_advisory_xact_lock" not in statement


def test_internal_refund_timeout_is_applied_only_from_session_info():
    class _LockConnection:
        def __init__(self):
            self.executed = []

        def execute(self, statement, parameters):
            self.executed.append((str(statement), parameters))

    configured_connection = _LockConnection()
    configured_db = SimpleNamespace(
        info={
            refund_access_service.REFUND_ACCESS_LOCK_TIMEOUT_MS_INFO_KEY: 2500,
        }
    )
    refund_access_service._apply_refund_access_lock_timeout(
        configured_connection,
        configured_db,
    )
    assert "set_config('lock_timeout'" in configured_connection.executed[0][0]
    assert configured_connection.executed[0][1] == {
        "lock_timeout": "2500ms",
    }

    celery_connection = _LockConnection()
    refund_access_service._apply_refund_access_lock_timeout(
        celery_connection,
        SimpleNamespace(info={}),
    )
    assert celery_connection.executed == []


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_DATABASE_URL"),
    reason="TEST_POSTGRES_DATABASE_URL not configured",
)
def test_real_postgres_shared_holder_web_trylock_and_worker_wait_keep_heartbeat():
    """Integration proof for the application-level deadlock shape.

    A shared WebSocket admission fence stays open across awaits. A marked web
    request must fail immediately, while an unmarked refund/worker session
    deliberately waits until that shared holder is released. The event-loop
    heartbeat must continue throughout both paths.
    """
    engine = create_engine(
        os.environ["TEST_POSTGRES_DATABASE_URL"],
        pool_pre_ping=True,
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    company_id = int(uuid.uuid4().int % 1_000_000_000) + 1_000_000_000
    holder = Session()
    web_request = db_module.mark_session_as_web_request(Session())
    worker = Session()
    try:
        company_access_control.try_lock_refund_entities_for_access(
            holder,
            company_ids=[company_id],
        )

        async def scenario():
            heartbeat_ticks = 0
            stop = asyncio.Event()

            async def heartbeat():
                nonlocal heartbeat_ticks
                while not stop.is_set():
                    heartbeat_ticks += 1
                    await asyncio.sleep(0.002)

            heartbeat_task = asyncio.create_task(heartbeat())
            await asyncio.sleep(0.01)

            started = time.monotonic()
            with pytest.raises(
                company_access_control.CompanyOperationalLockBusyError
            ):
                company_access_control.lock_refund_entities_for_mutation(
                    web_request,
                    company_ids=[company_id],
                )
            assert time.monotonic() - started < 0.5
            configured_timeout_ms = web_request.execute(
                text(
                    "SELECT EXTRACT(EPOCH FROM "
                    "current_setting('lock_timeout')::interval) * 1000"
                )
            ).scalar()
            assert int(configured_timeout_ms) == (
                db_module.WEB_TRANSACTION_LOCK_TIMEOUT_MS
            )

            worker_wait = asyncio.create_task(
                asyncio.to_thread(
                    company_access_control.lock_refund_entities_for_mutation,
                    worker,
                    company_ids=[company_id],
                )
            )
            await asyncio.sleep(0.05)
            assert not worker_wait.done()
            ticks_while_worker_waited = heartbeat_ticks

            # This await models the bounded WebSocket send while the shared
            # transaction fence remains held.
            await asyncio.sleep(0.02)
            holder.rollback()
            await asyncio.wait_for(worker_wait, timeout=1.0)
            worker.rollback()

            stop.set()
            await heartbeat_task
            assert heartbeat_ticks > ticks_while_worker_waited
            assert heartbeat_ticks >= 20

        asyncio.run(scenario())
    finally:
        for session in (holder, web_request, worker):
            try:
                session.rollback()
            finally:
                session.close()
        engine.dispose()


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_DATABASE_URL"),
    reason="TEST_POSTGRES_DATABASE_URL not configured",
)
def test_real_postgres_web_lock_timeout_fuses_implicit_blocking_lock():
    """A trigger-equivalent blocking lock is bounded off the event loop."""
    engine = create_engine(
        os.environ["TEST_POSTGRES_DATABASE_URL"],
        pool_pre_ping=True,
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    lock_key = f"agentive-test:web-lock-fuse:{uuid.uuid4()}"
    holder = Session()
    web_request = db_module.mark_session_as_web_request(Session())
    try:
        holder.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended(:lock_key, 0))"
            ),
            {"lock_key": lock_key},
        )

        async def scenario():
            heartbeat_ticks = 0
            stop = asyncio.Event()

            async def heartbeat():
                nonlocal heartbeat_ticks
                while not stop.is_set():
                    heartbeat_ticks += 1
                    await asyncio.sleep(0.005)

            def trigger_equivalent_wait():
                web_request.execute(
                    text(
                        "SELECT pg_advisory_xact_lock("
                        "hashtextextended(:lock_key, 0))"
                    ),
                    {"lock_key": lock_key},
                )

            heartbeat_task = asyncio.create_task(heartbeat())
            started = time.monotonic()
            with pytest.raises(OperationalError):
                await asyncio.wait_for(
                    asyncio.to_thread(trigger_equivalent_wait),
                    timeout=(
                        db_module.WEB_TRANSACTION_LOCK_TIMEOUT_MS / 1000
                        + 1.0
                    ),
                )
            elapsed = time.monotonic() - started
            stop.set()
            await heartbeat_task

            assert elapsed < (
                db_module.WEB_TRANSACTION_LOCK_TIMEOUT_MS / 1000 + 0.75
            )
            assert heartbeat_ticks >= 20

        asyncio.run(scenario())
    finally:
        for session in (holder, web_request):
            try:
                session.rollback()
            finally:
                session.close()
        engine.dispose()


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_DATABASE_URL"),
    reason="TEST_POSTGRES_DATABASE_URL not configured",
)
def test_real_postgres_refund_main_session_lock_timeout_is_reapplied():
    """The refund data transaction is bounded, not only its lock connection."""
    engine = create_engine(
        os.environ["TEST_POSTGRES_DATABASE_URL"],
        pool_pre_ping=True,
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    lock_key = f"agentive-test:refund-main-lock-fuse:{uuid.uuid4()}"
    holder = Session()
    refund_db = db_module.mark_session_with_transaction_lock_timeout(
        Session(),
        100,
    )
    try:
        holder.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended(:lock_key, 0))"
            ),
            {"lock_key": lock_key},
        )

        started = time.monotonic()
        with pytest.raises(OperationalError) as timeout_error:
            refund_db.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended(:lock_key, 0))"
                ),
                {"lock_key": lock_key},
            )
        assert time.monotonic() - started < 1.0
        assert getattr(timeout_error.value.orig, "pgcode", None) == "55P03"

        # The timeout aborts the current transaction. A new transaction must
        # receive the same fuse because refund processing commits in phases.
        refund_db.rollback()
        configured_timeout_ms = refund_db.execute(
            text(
                "SELECT EXTRACT(EPOCH FROM "
                "current_setting('lock_timeout')::interval) * 1000"
            )
        ).scalar()
        assert int(configured_timeout_ms) == 100
    finally:
        for session in (holder, refund_db):
            try:
                session.rollback()
            finally:
                session.close()
        engine.dispose()


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_DATABASE_URL"),
    reason="TEST_POSTGRES_DATABASE_URL not configured",
)
def test_real_postgres_partial_refund_timeout_releases_all_session_locks(
    monkeypatch,
):
    """A mid-entity timeout must not leak identity/entity locks into the pool."""
    url = os.environ["TEST_POSTGRES_DATABASE_URL"]
    target_engine = create_engine(
        url,
        pool_size=1,
        max_overflow=0,
        pool_pre_ping=True,
    )
    blocker_engine = create_engine(url, poolclass=NullPool)
    verifier_engine = create_engine(url, poolclass=NullPool)
    TargetSession = sessionmaker(
        bind=target_engine,
        autocommit=False,
        autoflush=False,
    )
    unique = str(uuid.uuid4())
    command = refund_access_service.RefundAccessCommand(
        event_id=f"timeout-event-{unique}",
        idempotency_key=f"timeout-idempotency-{unique}",
        invoice_id=f"timeout-invoice-{unique}",
        email=f"timeout-{unique}@example.com",
        state="refund_pending",
        occurred_at=datetime.now(timezone.utc),
        source="eduzz",
    )
    entity_lock_keys = [
        f"refund-access:entity:company:{unique}:1",
        f"refund-access:entity:company:{unique}:2",
    ]
    identity_lock_keys = sorted(
        {
            f"refund-access:invoice:{command.source}:{command.invoice_id}",
            f"refund-access:event:{command.event_id}",
            f"refund-access:idempotency:{command.idempotency_key}",
            "refund-access:email:"
            f"{refund_access_service._email_hash(command.email)}",
        }
    )
    scope = refund_access_service.AccountScope(
        root_client_id=0,
        company_ids=(),
        client_ids=(),
        user_ids=(),
    )
    monkeypatch.setattr(
        refund_access_service,
        "_resolve_command_scope",
        lambda _db, _command: scope,
    )
    monkeypatch.setattr(
        refund_access_service,
        "_command_entity_lock_keys",
        lambda _db, _command, _scope: list(entity_lock_keys),
    )
    monkeypatch.setattr(
        refund_access_service,
        "_process_refund_access_locked",
        lambda *_args, **_kwargs: pytest.fail(
            "processing must not run after lock timeout"
        ),
    )

    target_db = TargetSession()
    target_db.info[
        refund_access_service.REFUND_ACCESS_LOCK_TIMEOUT_MS_INFO_KEY
    ] = 100
    blocker = blocker_engine.connect()
    try:
        with target_engine.connect() as initial_target:
            target_backend_pid = int(
                initial_target.execute(text("SELECT pg_backend_pid()")).scalar()
            )

        blocker.execute(
            text("SELECT pg_advisory_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": entity_lock_keys[1]},
        )

        started = time.monotonic()
        with pytest.raises(OperationalError) as timeout_error:
            refund_access_service.process_refund_access(target_db, command)
        assert time.monotonic() - started < 1.0
        assert getattr(timeout_error.value.orig, "pgcode", None) == "55P03"

        # pool_size=1 guarantees this is the same physical connection that
        # timed out. Keep it checked out while an independent connection probes
        # every lock acquired before the timeout.
        with target_engine.connect() as reused_target:
            assert int(
                reused_target.execute(text("SELECT pg_backend_pid()")).scalar()
            ) == target_backend_pid
            with verifier_engine.connect() as verifier:
                for lock_key in [*identity_lock_keys, entity_lock_keys[0]]:
                    acquired = bool(
                        verifier.execute(
                            text(
                                "SELECT pg_try_advisory_lock("
                                "hashtextextended(:lock_key, 0))"
                            ),
                            {"lock_key": lock_key},
                        ).scalar()
                    )
                    assert acquired is True, lock_key
                    verifier.execute(
                        text(
                            "SELECT pg_advisory_unlock("
                            "hashtextextended(:lock_key, 0))"
                        ),
                        {"lock_key": lock_key},
                    )
    finally:
        try:
            blocker.execute(
                text(
                    "SELECT pg_advisory_unlock("
                    "hashtextextended(:lock_key, 0))"
                ),
                {"lock_key": entity_lock_keys[1]},
            )
        finally:
            blocker.close()
        target_db.close()
        target_engine.dispose()
        blocker_engine.dispose()
        verifier_engine.dispose()
