import asyncio
import os
import time
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker


os.environ.setdefault(
    "DATABASE_URL",
    "sqlite:////tmp/agentive-db-web-lock-fuse-test.db",
)

from backend import db as db_module  # noqa: E402
from backend.services import company_access_control  # noqa: E402
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
        company_access_control.IdentityOperationBusyError
    ) as error:
        company_access_control.lock_account_identity_for_creation(
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
        company_access_control.lock_entities_for_mutation(
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


def test_unmarked_sessionlocal_paths_keep_blocking_identity_locks():
    identity_session = _FakePostgresSession()
    entity_session = _FakePostgresSession()

    company_access_control.lock_account_identity_for_creation(
        identity_session,
        "owner@example.com",
    )
    company_access_control.lock_entities_for_mutation(
        entity_session,
        company_ids=[7],
    )

    for statement, _parameters in (
        identity_session.executed + entity_session.executed
    ):
        assert "pg_advisory_xact_lock(" in statement
        assert "pg_try_advisory_xact_lock" not in statement


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_DATABASE_URL"),
    reason="TEST_POSTGRES_DATABASE_URL not configured",
)
def test_real_postgres_shared_holder_web_trylock_and_worker_wait_keep_heartbeat():
    """Integration proof for the application-level deadlock shape.

    A shared WebSocket admission fence stays open across awaits. A marked web
    request must fail immediately, while an unmarked worker session
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
        company_access_control.try_lock_entities_for_access(
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
                company_access_control.lock_entities_for_mutation(
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
                    company_access_control.lock_entities_for_mutation,
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
def test_real_postgres_bounded_session_lock_timeout_is_reapplied():
    """A configured data transaction remains bounded across rollbacks."""
    engine = create_engine(
        os.environ["TEST_POSTGRES_DATABASE_URL"],
        pool_pre_ping=True,
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    lock_key = f"platform-test:bounded-main-lock:{uuid.uuid4()}"
    holder = Session()
    bounded_db = db_module.mark_session_with_transaction_lock_timeout(
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
            bounded_db.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended(:lock_key, 0))"
                ),
                {"lock_key": lock_key},
            )
        assert time.monotonic() - started < 1.0
        assert getattr(timeout_error.value.orig, "pgcode", None) == "55P03"

        # The timeout aborts the current transaction. A new transaction must
        # receive the same fuse after a rollback.
        bounded_db.rollback()
        configured_timeout_ms = bounded_db.execute(
            text(
                "SELECT EXTRACT(EPOCH FROM "
                "current_setting('lock_timeout')::interval) * 1000"
            )
        ).scalar()
        assert int(configured_timeout_ms) == 100
    finally:
        for session in (holder, bounded_db):
            try:
                session.rollback()
            finally:
                session.close()
        engine.dispose()
