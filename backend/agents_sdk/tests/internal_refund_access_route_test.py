import asyncio
import os
import threading
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool as shared_run_in_threadpool
from starlette.requests import Request

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-with-at-least-32-chars")

from backend.routes import internal_refund_access
from backend.services.refund_access_service import RefundAccessResult


def _request(*, peer="127.0.0.1", headers=None):
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/internal/refund-access",
            "headers": raw_headers,
            "client": (peer, 12345),
            "server": ("127.0.0.1", 8002),
            "scheme": "http",
            "query_string": b"",
        }
    )


def test_internal_refund_route_accepts_only_loopback_and_matching_key(monkeypatch):
    secret = "s" * 32
    monkeypatch.setenv("REFUND_ACCESS_INTERNAL_KEY", secret)

    internal_refund_access._verify_internal_request(_request(), secret)

    with pytest.raises(HTTPException) as external:
        internal_refund_access._verify_internal_request(
            _request(peer="10.0.0.8"),
            secret,
        )
    assert external.value.status_code == 403

    with pytest.raises(HTTPException) as forwarded:
        internal_refund_access._verify_internal_request(
            _request(headers={"x-forwarded-for": "203.0.113.4"}),
            secret,
        )
    assert forwarded.value.status_code == 403

    with pytest.raises(HTTPException) as wrong_key:
        internal_refund_access._verify_internal_request(_request(), "wrong")
    assert wrong_key.value.status_code == 401


def test_production_requires_strong_internal_key(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("REFUND_ACCESS_INTERNAL_KEY", raising=False)
    with pytest.raises(RuntimeError):
        internal_refund_access.validate_refund_access_internal_config()

    monkeypatch.setenv("REFUND_ACCESS_INTERNAL_KEY", "k" * 32)
    internal_refund_access.validate_refund_access_internal_config()


def test_replayed_waiting_event_does_not_revoke_after_effective_active_state(monkeypatch):
    secret = "s" * 32
    monkeypatch.setenv("REFUND_ACCESS_INTERNAL_KEY", secret)
    published = []

    class _DB:
        def __init__(self):
            self.info = {}

        def close(self):
            return None

    async def _run_in_refund_executor(call):
        return call()

    async def _publish(company_ids):
        published.append(list(company_ids))

    def _process_refund(db, _command):
        assert db.info[
            internal_refund_access.REFUND_ACCESS_LOCK_TIMEOUT_MS_INFO_KEY
        ] == internal_refund_access.REFUND_ACCESS_INTERNAL_LOCK_TIMEOUT_MS
        assert "agentive_web_request" not in db.info
        return RefundAccessResult(
            status="duplicate",
            state="active",
            company_ids=(10,),
        )

    monkeypatch.setattr(internal_refund_access, "SessionLocal", _DB)
    monkeypatch.setattr(
        internal_refund_access,
        "_run_in_refund_executor",
        _run_in_refund_executor,
    )
    monkeypatch.setattr(
        internal_refund_access,
        "process_refund_access",
        _process_refund,
    )
    monkeypatch.setattr(
        internal_refund_access.manager,
        "publish_access_revocation",
        _publish,
    )

    response = asyncio.run(
        internal_refund_access.refund_access(
            payload=internal_refund_access.RefundAccessRequest(
                eventId="wait-1",
                invoiceId="sale-1",
                email="student@example.com",
                state="refund_pending",
                occurredAt=datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc),
                source="eduzz",
            ),
            request=_request(),
            idempotency_key="idem-wait-1",
            internal_key=secret,
        )
    )

    assert response["status"] == "duplicate"
    assert response["state"] == "active"
    assert published == []


def test_blocked_result_revokes_companies_and_principals(monkeypatch):
    secret = "s" * 32
    monkeypatch.setenv("REFUND_ACCESS_INTERNAL_KEY", secret)
    published = []

    class _DB:
        def __init__(self):
            self.info = {}

        def close(self):
            return None

    async def _run_in_refund_executor(call):
        return call()

    async def _publish(company_ids, *, client_ids=(), user_ids=()):
        published.append(
            {
                "company_ids": list(company_ids),
                "client_ids": list(client_ids),
                "user_ids": list(user_ids),
            }
        )

    monkeypatch.setattr(internal_refund_access, "SessionLocal", _DB)
    monkeypatch.setattr(
        internal_refund_access,
        "_run_in_refund_executor",
        _run_in_refund_executor,
    )
    monkeypatch.setattr(
        internal_refund_access,
        "process_refund_access",
        lambda _db, _command: RefundAccessResult(
            status="processed",
            state="refund_pending",
            company_ids=(10,),
            client_ids=(20,),
            user_ids=(30,),
        ),
    )
    monkeypatch.setattr(
        internal_refund_access.manager,
        "publish_access_revocation",
        _publish,
    )

    response = asyncio.run(
        internal_refund_access.refund_access(
            payload=internal_refund_access.RefundAccessRequest(
                eventId="wait-principal",
                invoiceId="sale-principal",
                email="student@example.com",
                state="refund_pending",
                occurredAt=datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc),
                source="eduzz",
            ),
            request=_request(),
            idempotency_key="idem-wait-principal",
            internal_key=secret,
        )
    )

    assert response["companyIds"] == [10]
    assert response["clientIds"] == [20]
    assert response["userIds"] == [30]
    assert published == [
        {
            "company_ids": [10],
            "client_ids": [20],
            "user_ids": [30],
        }
    ]


def test_refund_executor_worker_count_is_clamped(monkeypatch):
    monkeypatch.setenv("REFUND_ACCESS_EXECUTOR_WORKERS", "0")
    assert internal_refund_access._refund_executor_worker_count() == 1

    monkeypatch.setenv("REFUND_ACCESS_EXECUTOR_WORKERS", "50")
    assert internal_refund_access._refund_executor_worker_count() == 2

    monkeypatch.setenv("REFUND_ACCESS_EXECUTOR_WORKERS", "invalid")
    assert internal_refund_access._refund_executor_worker_count() == 2


def test_internal_refund_lock_timeout_is_configurable_and_clamped(monkeypatch):
    monkeypatch.setenv("REFUND_ACCESS_INTERNAL_LOCK_TIMEOUT_MS", "50")
    assert internal_refund_access._refund_lock_timeout_ms() == 100

    monkeypatch.setenv("REFUND_ACCESS_INTERNAL_LOCK_TIMEOUT_MS", "120000")
    assert internal_refund_access._refund_lock_timeout_ms() == 60_000

    monkeypatch.setenv("REFUND_ACCESS_INTERNAL_LOCK_TIMEOUT_MS", "invalid")
    assert internal_refund_access._refund_lock_timeout_ms() == 1_000

def test_saturated_refund_executor_does_not_starve_shared_login_pool():
    async def _scenario():
        release_refunds = threading.Event()
        refunds_started = [threading.Event(), threading.Event()]

        def _blocking_refund(index):
            refunds_started[index].set()
            release_refunds.wait(timeout=2)
            return index

        refund_tasks = [
            asyncio.create_task(
                internal_refund_access._run_in_refund_executor(
                    lambda index=index: _blocking_refund(index)
                )
            )
            for index in range(2)
        ]

        try:
            async def _wait_until_refunds_saturate():
                while not all(started.is_set() for started in refunds_started):
                    await asyncio.sleep(0.005)

            await asyncio.wait_for(_wait_until_refunds_saturate(), timeout=0.5)

            with pytest.raises(
                internal_refund_access.RefundAccessExecutorBusyError
            ):
                await internal_refund_access._run_in_refund_executor(
                    lambda: "must-not-queue"
                )

            # This represents a synchronous login dependency executed through
            # Starlette's shared AnyIO pool. It must remain schedulable while
            # both dedicated refund workers are blocked on database locks.
            login_result = await asyncio.wait_for(
                shared_run_in_threadpool(lambda: "login-ok"),
                timeout=0.5,
            )
            assert login_result == "login-ok"
            assert not any(task.done() for task in refund_tasks)
        finally:
            release_refunds.set()
            await asyncio.gather(*refund_tasks)

    asyncio.run(_scenario())
