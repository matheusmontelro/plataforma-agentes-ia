import asyncio
import os
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from celery.exceptions import Retry
from fastapi import HTTPException


os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("CLIENT_TOKEN", "test-client-token")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/agentive-refund-race-guards-test.db")
os.environ.setdefault("WAHA_API_KEY", "test-waha-key")
os.environ.setdefault("WAHA_BASE_URL", "http://waha.local")

from backend.integrations import waha_utils, whatsapp_provider  # noqa: E402
from backend.integrations.waha_sdk import WAHAException  # noqa: E402
from backend.integrations.whatsapp_provider import WhatsAppConfig  # noqa: E402
from backend.routes import waha_routes, webhook  # noqa: E402
from backend.services import company_access_control  # noqa: E402
from backend.services.flow_executor import FlowExecutor  # noqa: E402
from backend.worker import process_message_waha  # noqa: E402


class _FakeResponse:
    status_code = 201
    text = '{"id":"message-1"}'

    def json(self):
        return {"id": "message-1"}


class _LockTrackingDB:
    def __init__(self, events):
        self.events = events
        self.locked = False
        self.closed = False

    def rollback(self):
        self.events.append("rollback")

    def close(self):
        self.closed = True
        self.events.append("close")


class _JobFenceDB:
    def __init__(self, events):
        self.events = events

    def commit(self):
        self.events.append("commit")

    def rollback(self):
        self.events.append("rollback")


class _RollbackOnlyDB:
    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


def test_legacy_job_without_epoch_only_runs_before_first_refund(monkeypatch):
    state = {"status": "active", "epoch": 0}
    monkeypatch.setattr(
        company_access_control,
        "is_company_operational",
        lambda _db, _company_id: state["status"] == "active",
    )
    monkeypatch.setattr(
        company_access_control,
        "get_company_operational_epoch",
        lambda _db, _company_id: state["epoch"],
    )

    assert company_access_control.validate_company_job_epoch(object(), 7, None)

    state.update(status="refund_pending", epoch=1)
    assert not company_access_control.validate_company_job_epoch(object(), 7, None)

    state["status"] = "active"
    assert not company_access_control.validate_company_job_epoch(object(), 7, None)
    assert not company_access_control.validate_company_job_epoch(object(), 7, 0)
    assert company_access_control.validate_company_job_epoch(object(), 7, 1)


def test_worker_company_epoch_fence_fails_fast_when_lock_is_busy():
    events = []

    class _Result:
        def scalar(self):
            return False

    class _DB:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, query, params):
            assert "pg_try_advisory_xact_lock" in str(query)
            assert params == {"lock_key": "refund-access:entity:company:7"}
            events.append("try-lock")
            return _Result()

        def rollback(self):
            events.append("rollback")

    with pytest.raises(
        company_access_control.CompanyOperationalLockBusyError
    ) as error:
        company_access_control.try_capture_company_job_epoch(_DB(), 7)

    assert error.value.company_id == 7
    assert events == ["try-lock", "rollback"]


def test_job_enqueue_wins_before_refund_under_company_fence(monkeypatch):
    events = []
    db = _JobFenceDB(events)

    monkeypatch.setattr(
        company_access_control,
        "lock_refund_entities_for_mutation",
        lambda _db, *, company_ids=(), **_kwargs: events.append(
            f"lock:{list(company_ids)}"
        ),
    )
    monkeypatch.setattr(
        company_access_control,
        "ensure_company_operational",
        lambda _db, company_id: events.append(f"recheck:{company_id}"),
    )

    enqueued, result = company_access_control.enqueue_company_job_if_active(
        db,
        7,
        is_still_pending=lambda: events.append("pending") or True,
        enqueue=lambda: events.append("enqueue") or "task-1",
    )

    assert enqueued is True
    assert result == "task-1"
    assert events == ["lock:[7]", "recheck:7", "pending", "enqueue", "commit"]


def test_refund_wins_before_job_enqueue_and_blocks_publication(monkeypatch):
    events = []
    db = _JobFenceDB(events)

    monkeypatch.setattr(
        company_access_control,
        "lock_refund_entities_for_mutation",
        lambda _db, *, company_ids=(), **_kwargs: events.append(
            f"lock:{list(company_ids)}"
        ),
    )

    def blocked(_db, company_id):
        events.append(f"recheck:{company_id}")
        raise company_access_control.CompanyOperationallyBlockedError(
            company_id,
            "refund_pending",
        )

    monkeypatch.setattr(
        company_access_control,
        "ensure_company_operational",
        blocked,
    )

    with pytest.raises(company_access_control.CompanyOperationallyBlockedError):
        company_access_control.enqueue_company_job_if_active(
            db,
            7,
            is_still_pending=lambda: pytest.fail("estado não deve ser consultado"),
            enqueue=lambda: pytest.fail("broker não deve ser chamado"),
        )

    assert events == ["lock:[7]", "recheck:7", "rollback"]


def test_cancelled_durable_job_never_reenqueues_after_restore(monkeypatch):
    events = []
    db = _JobFenceDB(events)

    monkeypatch.setattr(
        company_access_control,
        "lock_refund_entities_for_mutation",
        lambda _db, *, company_ids=(), **_kwargs: events.append(
            f"lock:{list(company_ids)}"
        ),
    )
    monkeypatch.setattr(
        company_access_control,
        "ensure_company_operational",
        lambda _db, company_id: events.append(f"recheck:{company_id}"),
    )

    enqueued, result = company_access_control.enqueue_company_job_if_active(
        db,
        7,
        is_still_pending=lambda: events.append("cancelled") or False,
        enqueue=lambda: pytest.fail("job cancelado não pode ser republicado"),
    )

    assert enqueued is False
    assert result is None
    assert events == ["lock:[7]", "recheck:7", "cancelled", "rollback"]


def test_waha_utils_holds_company_lock_through_remote_send(monkeypatch):
    events = []
    db = _LockTrackingDB(events)

    def fake_lock(current_db, *, company_ids=(), **_kwargs):
        assert list(company_ids) == [7]
        current_db.locked = True
        events.append("lock")

    def fake_ensure(current_db, company_id):
        assert company_id == 7
        assert current_db.locked
        events.append("recheck")

    def fake_post(*_args, **_kwargs):
        assert db.locked
        assert not db.closed
        events.append("remote")
        return _FakeResponse()

    monkeypatch.setattr("backend.db.SessionLocal", lambda: db)
    monkeypatch.setattr(
        company_access_control,
        "lock_refund_entities_for_mutation",
        fake_lock,
    )
    monkeypatch.setattr(
        company_access_control,
        "ensure_company_operational",
        fake_ensure,
    )
    monkeypatch.setattr(waha_utils.requests, "post", fake_post)

    result = waha_utils.send_text_to_waha(
        waha_session_name="sessao-teste",
        phone="5500000000004",
        message="Oi",
        company_id=7,
    )

    assert result == {"id": "message-1"}
    assert events == ["lock", "recheck", "remote", "rollback", "close"]


def test_whatsapp_provider_rechecks_under_lock_before_remote_send(monkeypatch):
    events = []
    db = _LockTrackingDB(events)

    def fake_lock(current_db, *, company_ids=(), **_kwargs):
        assert current_db is db
        assert list(company_ids) == [7]
        current_db.locked = True
        events.append("lock")

    def fake_ensure(current_db, company_id):
        assert current_db is db
        assert company_id == 7
        assert current_db.locked
        events.append("recheck")

    monkeypatch.setattr(
        company_access_control,
        "lock_refund_entities_for_mutation",
        fake_lock,
    )
    monkeypatch.setattr(
        company_access_control,
        "ensure_company_operational",
        fake_ensure,
    )
    monkeypatch.setattr(
        whatsapp_provider.WhatsAppConfig,
        "from_company",
        classmethod(
            lambda cls, company_id, db=None: WhatsAppConfig(
                "waha",
                session_name="sessao-teste",
                base_url="http://waha.local",
                api_key="test-key",
            )
        ),
    )

    class _FakeWAHAClient:
        def send_text(self, **_kwargs):
            assert db.locked
            assert not db.closed
            events.append("remote")
            return {"id": "message-1"}

    monkeypatch.setattr(
        whatsapp_provider,
        "get_waha_client",
        lambda **_kwargs: _FakeWAHAClient(),
    )

    result = whatsapp_provider.send_text(
        company_id=7,
        phone="5500000000004",
        message="Oi",
        db=db,
    )

    assert result == {"id": "message-1"}
    assert events == ["lock", "recheck", "remote"]


def test_restart_route_locks_and_rechecks_before_waha_side_effect(monkeypatch):
    events = []

    class _Result:
        def fetchone(self):
            return SimpleNamespace(
                waha_enabled=True,
                waha_session_name="sessao-teste",
            )

    class _DB:
        def execute(self, _query, params):
            assert params == {"cid": 7}
            events.append("config-query")
            return _Result()

        def rollback(self):
            events.append("rollback")

    def fake_lock(_db, *, company_ids=(), **_kwargs):
        assert list(company_ids) == [7]
        events.append("lock")

    def fake_ensure(_db, company_id):
        assert company_id == 7
        events.append("recheck")

    class _FakeWAHAClient:
        def restart_session(self, session_name):
            assert session_name == "sessao-teste"
            events.append("remote")
            return {"status": "STARTING"}

    monkeypatch.setattr(webhook, "lock_refund_entities_for_mutation", fake_lock)
    monkeypatch.setattr(webhook, "ensure_company_operational", fake_ensure)
    monkeypatch.setattr(
        "backend.integrations.waha_sdk.get_client",
        lambda **_kwargs: _FakeWAHAClient(),
    )

    result = webhook.restart_instance(
        user=SimpleNamespace(id=11, email="owner@example.com", company_id=7),
        db=_DB(),
    )

    assert result["result"] == {"status": "STARTING"}
    assert events == ["lock", "recheck", "config-query", "remote", "rollback"]


def test_waha_callback_enqueues_before_worker_operational_fence(monkeypatch):
    events = []
    queued = {}
    audit_call = {}

    class _Result:
        def __init__(self, *, rows=None, row=None):
            self.rows = rows or []
            self.row = row

        def fetchall(self):
            return self.rows

        def fetchone(self):
            return self.row

    class _DB:
        def __init__(self):
            self.dedupe_locked = False

        def execute(self, query, params):
            sql = " ".join(str(query).split())
            if "FROM companies" in sql:
                assert params == {"session_name": "sessao-teste"}
                events.append("resolve-company")
                return _Result(rows=[SimpleNamespace(id=7)])
            if "pg_advisory_xact_lock" in sql:
                assert params == {
                    "dedupe_key": "waha:7:message.any:message-event-1"
                }
                self.dedupe_locked = True
                events.append("dedupe-lock")
                return _Result()
            if "FROM webhook_audit" in sql:
                assert self.dedupe_locked
                assert "message_type = :message_type" in sql
                assert "status <> 'queue_failed'" in sql
                assert params == {
                    "company_id": 7,
                    "message_id": "message-event-1",
                    "message_type": "waha:message.any",
                }
                events.append("dedupe")
                return _Result()
            raise AssertionError(f"Query inesperada: {sql}")

        def commit(self):
            events.append("commit")

    class _Request:
        async def json(self):
            return {
                "event": "message.any",
                "session": "sessao-teste",
                "payload": {
                    "id": "message-event-1",
                    "from": "5500000000007@c.us",
                    "type": "chat",
                    "body": "Teste",
                },
            }

    def fake_save_webhook_audit(**kwargs):
        audit_call.update(kwargs)
        events.append("audit")
        return 101

    monkeypatch.setattr(
        waha_routes,
        "save_webhook_audit",
        fake_save_webhook_audit,
    )
    monkeypatch.setattr(
        waha_routes,
        "update_audit_status",
        lambda _db, audit_id, status, **_kwargs: events.append(
            f"audit:{audit_id}:{status}"
        ),
    )
    monkeypatch.setattr(
        waha_routes,
        "get_company_operational_epoch",
        lambda _db, company_id: events.append(f"epoch:{company_id}") or 4,
    )

    def fake_apply_async(*, args, queue):
        queued.update(task_data=args[0], queue=queue)
        events.append("enqueue")
        return SimpleNamespace(id="task-1")

    monkeypatch.setattr(
        process_message_waha.process_incoming_waha_message,
        "apply_async",
        fake_apply_async,
    )

    result = asyncio.run(
        waha_routes.waha_message_webhook(_Request(), db=_DB())
    )

    assert result["status"] == "queued"
    assert queued["queue"] == "waha_messages_queue"
    assert queued["task_data"]["company_id"] == 7
    assert queued["task_data"]["operational_epoch"] == 4
    assert audit_call["company_id"] == 7
    assert audit_call["message_id"] == "message-event-1"
    assert audit_call["event_type"] == "message.any"
    assert events == [
        "resolve-company",
        "dedupe-lock",
        "dedupe",
        "audit",
        "epoch:7",
        "enqueue",
        "audit:101:queued",
    ]


def test_waha_webhook_summary_omits_message_and_media_contents():
    summary = waha_routes._waha_webhook_summary(
        {
            "event": "message.any",
            "session": "sessao-teste",
            "engine": "GOWS",
            "payload": {
                "id": "message-1",
                "from": "5500000000007@c.us",
                "type": "image",
                "body": "conteúdo sigiloso",
                "media": {
                    "url": "http://waha.local/api/files/private/image.jpg",
                    "filename": "documento-confidencial.jpg",
                    "mimetype": "image/jpeg",
                },
            },
        }
    )

    serialized = repr(summary)
    assert "conteúdo sigiloso" not in serialized
    assert "http://waha.local/api/files/private/image.jpg" not in serialized
    assert "documento-confidencial.jpg" not in serialized
    assert summary["message_id_present"] is True
    assert summary["has_media"] is True
    assert summary["media_mimetype"] == "image/jpeg"


@pytest.mark.parametrize(
    ("event_type", "payload", "message_id"),
    [
        (
            "message",
            {
                "id": "duplicate-message-1",
                "from": "5500000000007@c.us",
                "type": "chat",
                "body": "Teste",
            },
            "duplicate-message-1",
        ),
        (
            "poll.vote",
            {
                "vote": {
                    "id": "duplicate-poll-vote-1",
                    "from": "5500000000007@c.us",
                    "selectedOptions": ["10"],
                },
                "poll": {"id": "poll-1"},
            },
            "duplicate-poll-vote-1",
        ),
    ],
)
def test_waha_callback_deduplicates_same_event_before_enqueue(
    monkeypatch,
    event_type,
    payload,
    message_id,
):
    events = []

    class _Result:
        def __init__(self, *, rows=None, row=None):
            self.rows = rows or []
            self.row = row

        def fetchall(self):
            return self.rows

        def fetchone(self):
            return self.row

    class _DB:
        def execute(self, query, params):
            sql = " ".join(str(query).split())
            if "FROM companies" in sql:
                events.append("resolve-company")
                return _Result(rows=[SimpleNamespace(id=7)])
            if "pg_advisory_xact_lock" in sql:
                assert params == {
                    "dedupe_key": f"waha:7:{event_type}:{message_id}"
                }
                events.append("dedupe-lock")
                return _Result()
            if "FROM webhook_audit" in sql:
                assert params == {
                    "company_id": 7,
                    "message_id": message_id,
                    "message_type": f"waha:{event_type}",
                }
                events.append("dedupe-hit")
                return _Result(row=SimpleNamespace(id=202))
            raise AssertionError(f"Query inesperada: {sql}")

        def rollback(self):
            events.append("rollback")

    class _Request:
        async def json(self):
            return {
                "event": event_type,
                "session": "sessao-teste",
                "payload": payload,
            }

    monkeypatch.setattr(
        waha_routes,
        "save_webhook_audit",
        lambda **_kwargs: pytest.fail("audit duplicado não deve ser inserido"),
    )
    monkeypatch.setattr(
        process_message_waha.process_incoming_waha_message,
        "apply_async",
        lambda **_kwargs: pytest.fail("evento duplicado não deve ser enfileirado"),
    )

    result = asyncio.run(
        waha_routes.waha_message_webhook(_Request(), db=_DB())
    )

    assert result == {
        "status": "duplicate",
        "reason": "message_already_processed",
        "audit_id": 202,
    }
    assert events == [
        "resolve-company",
        "dedupe-lock",
        "dedupe-hit",
        "rollback",
    ]


def test_waha_callback_marks_queue_failed_and_allows_webhook_retry(monkeypatch):
    events = []

    class _Result:
        def __init__(self, *, rows=None):
            self.rows = rows or []

        def fetchall(self):
            return self.rows

        def fetchone(self):
            return None

    class _DB:
        def execute(self, query, _params):
            sql = " ".join(str(query).split())
            if "FROM companies" in sql:
                events.append("resolve-company")
                return _Result(rows=[SimpleNamespace(id=7)])
            if "pg_advisory_xact_lock" in sql:
                events.append("dedupe-lock")
                return _Result()
            if "FROM webhook_audit" in sql:
                assert "status <> 'queue_failed'" in sql
                events.append("dedupe-miss")
                return _Result()
            raise AssertionError(f"Query inesperada: {sql}")

    class _Request:
        async def json(self):
            return {
                "event": "message.any",
                "session": "sessao-teste",
                "payload": {
                    "id": "queue-failure-1",
                    "from": "5500000000007@c.us",
                    "type": "chat",
                    "body": "Teste",
                },
            }

    monkeypatch.setattr(
        waha_routes,
        "save_webhook_audit",
        lambda **_kwargs: events.append("audit") or 303,
    )
    monkeypatch.setattr(
        waha_routes,
        "get_company_operational_epoch",
        lambda _db, _company_id: events.append("epoch") or 4,
    )

    def fail_enqueue(*, args, queue):
        assert args[0]["company_id"] == 7
        assert queue == "waha_messages_queue"
        events.append("enqueue-failed")
        raise RuntimeError("broker indisponível")

    monkeypatch.setattr(
        process_message_waha.process_incoming_waha_message,
        "apply_async",
        fail_enqueue,
    )
    monkeypatch.setattr(
        waha_routes,
        "update_audit_status",
        lambda _db, audit_id, status, **_kwargs: events.append(
            f"audit:{audit_id}:{status}"
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            waha_routes.waha_message_webhook(_Request(), db=_DB())
        )

    assert exc_info.value.status_code == 500
    assert events == [
        "resolve-company",
        "dedupe-lock",
        "dedupe-miss",
        "audit",
        "epoch",
        "enqueue-failed",
        "audit:303:queue_failed",
    ]


def test_waha_worker_retries_same_payload_when_company_fence_is_busy(monkeypatch):
    events = []
    task_data = {
        "payload": {"event": "session.status", "payload": {}},
        "session_name": "sessao-teste",
        "audit_id": 101,
        "company_id": 7,
        "operational_epoch": 4,
    }

    class _DB:
        def rollback(self):
            events.append("rollback")

        def close(self):
            events.append("close")

    monkeypatch.setattr(process_message_waha, "SessionLocal", _DB)

    def busy(_db, company_id, *, expected_epoch):
        assert company_id == 7
        assert expected_epoch == 4
        events.append("try-lock")
        raise company_access_control.CompanyOperationalLockBusyError(company_id)

    monkeypatch.setattr(
        company_access_control,
        "try_capture_company_job_epoch",
        busy,
    )

    def retry(*, exc, countdown):
        assert isinstance(
            exc,
            company_access_control.CompanyOperationalLockBusyError,
        )
        assert countdown == process_message_waha.WAHA_OPERATIONAL_LOCK_RETRY_SECONDS
        assert process_message_waha.process_incoming_waha_message.max_retries is None
        assert task_data["company_id"] == 7
        events.append("retry")
        raise Retry("company fence busy")

    monkeypatch.setattr(
        process_message_waha.process_incoming_waha_message,
        "retry",
        retry,
    )

    with pytest.raises(Retry):
        process_message_waha.process_incoming_waha_message.run(task_data)

    assert events == ["try-lock", "rollback", "retry", "close"]


def test_waha_worker_releases_admission_fence_before_processing(monkeypatch):
    events = []

    class _DB:
        def rollback(self):
            events.append("rollback")

        def close(self):
            events.append("close")

    monkeypatch.setattr(process_message_waha, "SessionLocal", _DB)
    monkeypatch.setattr(
        company_access_control,
        "try_capture_company_job_epoch",
        lambda _db, company_id, *, expected_epoch: (
            events.append(f"capture:{company_id}:{expected_epoch}") or 4
        ),
    )

    def validate(_db, company_id, epoch):
        assert events == ["capture:7:4", "rollback"]
        assert company_id == 7
        assert epoch == 4
        events.append("validate")
        return False

    monkeypatch.setattr(
        company_access_control,
        "validate_company_job_epoch",
        validate,
    )

    result = process_message_waha.process_incoming_waha_message.run(
        {
            "payload": {"event": "session.status", "payload": {}},
            "session_name": "sessao-teste",
            "audit_id": None,
            "company_id": 7,
            "operational_epoch": 4,
        }
    )

    assert result == {
        "status": "cancelled",
        "reason": "company_access_epoch_invalid",
    }
    assert events == ["capture:7:4", "rollback", "validate", "close"]


@pytest.mark.parametrize(
    ("conversation_fields", "expected_reason"),
    [
        (
            {
                "from": "000000000000000001@g.us",
                "author": "5500000000007@c.us",
            },
            "group_message",
        ),
        (
            {"from": "120363000000000000@newsletter"},
            "newsletter_message",
        ),
        (
            {"from": "status@broadcast"},
            "status_broadcast",
        ),
    ],
)
def test_waha_worker_ignores_non_direct_media_before_download(
    monkeypatch,
    conversation_fields,
    expected_reason,
):
    events = []

    class _DB:
        def rollback(self):
            events.append("rollback")

        def close(self):
            events.append("close")

    monkeypatch.setattr(process_message_waha, "SessionLocal", _DB)
    monkeypatch.setattr(
        company_access_control,
        "try_capture_company_job_epoch",
        lambda _db, company_id, *, expected_epoch: (
            events.append(f"capture:{company_id}:{expected_epoch}") or 4
        ),
    )
    monkeypatch.setattr(
        company_access_control,
        "validate_company_job_epoch",
        lambda _db, company_id, epoch: (
            events.append(f"validate:{company_id}:{epoch}") or True
        ),
    )

    def fail_if_downloaded(*_args, **_kwargs):
        raise AssertionError("mídia não deve ser baixada para conversa ignorada")

    monkeypatch.setattr(
        process_message_waha,
        "download_waha_media",
        fail_if_downloaded,
    )

    result = process_message_waha.process_incoming_waha_message.run(
        {
            "payload": {
                "event": "message.any",
                "session": "sessao-teste",
                "payload": {
                    "id": "ignored-media-message",
                    "type": "image",
                    "media": {
                        "url": "http://waha.local/api/files/sessao-teste/media.jpg",
                        "mimetype": "image/jpeg",
                    },
                    **conversation_fields,
                },
            },
            "session_name": "sessao-teste",
            "audit_id": None,
            "company_id": 7,
            "operational_epoch": 4,
        }
    )

    assert result == {"status": "ignored", "reason": expected_reason}
    assert events == [
        "capture:7:4",
        "rollback",
        "validate:7:4",
        "close",
    ]


def test_waha_worker_downloads_direct_media_before_common_pipeline(monkeypatch):
    events = []

    class _Result:
        def fetchone(self):
            return None

    class _DB:
        def rollback(self):
            events.append("rollback")

        def execute(self, query, params):
            assert "FROM client_companies" in str(query)
            assert params == {"cid": 7}
            events.append("owner-query")
            return _Result()

        def close(self):
            events.append("close")

    monkeypatch.setattr(process_message_waha, "SessionLocal", _DB)
    monkeypatch.setattr(
        company_access_control,
        "try_capture_company_job_epoch",
        lambda _db, company_id, *, expected_epoch: (
            events.append(f"capture:{company_id}:{expected_epoch}") or 4
        ),
    )
    monkeypatch.setattr(
        company_access_control,
        "validate_company_job_epoch",
        lambda _db, company_id, epoch: (
            events.append(f"validate:{company_id}:{epoch}") or True
        ),
    )

    def fake_download(url, company_id, message_id):
        assert url == "http://waha.local/api/files/sessao-teste/media.jpg"
        assert company_id == 7
        assert message_id == "direct-media-message"
        events.append("download")
        return "/api/waha/media/company_7/direct-media-message_media.jpg"

    monkeypatch.setattr(
        process_message_waha,
        "download_waha_media",
        fake_download,
    )

    result = process_message_waha.process_incoming_waha_message.run(
        {
            "payload": {
                "event": "message.any",
                "session": "sessao-teste",
                "payload": {
                    "id": "direct-media-message",
                    "from": "5500000000007@c.us",
                    "type": "image",
                    "media": {
                        "url": "http://waha.local/api/files/sessao-teste/media.jpg",
                        "mimetype": "image/jpeg",
                    },
                },
            },
            "session_name": "sessao-teste",
            "audit_id": None,
            "company_id": 7,
            "operational_epoch": 4,
        }
    )

    assert result is None
    assert events == [
        "capture:7:4",
        "rollback",
        "validate:7:4",
        "download",
        "owner-query",
        "close",
    ]


def test_waha_worker_keeps_legacy_epoch_rule_after_refund(monkeypatch):
    events = []

    class _DB:
        def rollback(self):
            events.append("rollback")

        def close(self):
            events.append("close")

    monkeypatch.setattr(process_message_waha, "SessionLocal", _DB)

    def capture(_db, company_id, *, expected_epoch):
        assert company_id == 7
        assert expected_epoch is None
        events.append("capture-current")
        return 1

    monkeypatch.setattr(
        company_access_control,
        "try_capture_company_job_epoch",
        capture,
    )

    def validate(_db, company_id, epoch):
        assert company_id == 7
        assert epoch is None
        events.append("validate-legacy")
        return False

    monkeypatch.setattr(
        company_access_control,
        "validate_company_job_epoch",
        validate,
    )

    result = process_message_waha.process_incoming_waha_message.run(
        {
            "payload": {"event": "session.status", "payload": {}},
            "session_name": "sessao-teste",
            "audit_id": None,
            "company_id": 7,
        }
    )

    assert result == {
        "status": "cancelled",
        "reason": "company_access_epoch_invalid",
    }
    assert events == [
        "capture-current",
        "rollback",
        "validate-legacy",
        "close",
    ]


def test_whatsapp_reset_holds_refund_fence_through_remote_and_commit(monkeypatch):
    events = []

    class _Result:
        rowcount = 1

    class _DB:
        def execute(self, _query, params):
            assert params == {"cid": 7}
            events.append("update")
            return _Result()

        def commit(self):
            events.append("commit")

    def fake_lock(_db, *, company_ids=(), **_kwargs):
        assert list(company_ids) == [7]
        events.append("lock")

    def fake_ensure(_db, company_id):
        assert company_id == 7
        events.append("recheck")

    monkeypatch.setattr(webhook, "lock_refund_entities_for_mutation", fake_lock)
    monkeypatch.setattr(webhook, "ensure_company_operational", fake_ensure)
    monkeypatch.setattr(
        whatsapp_provider.WhatsAppConfig,
        "from_company",
        classmethod(
            lambda cls, company_id, db=None: (
                events.append("config")
                or WhatsAppConfig(
                    "waha",
                    session_name="sessao-teste",
                    base_url="http://waha.local",
                    api_key="test-key",
                )
            )
        ),
    )

    class _FakeWAHAClient:
        def delete_session(self, session_name, logout):
            assert session_name == "sessao-teste"
            assert logout is True
            events.append("remote")

    monkeypatch.setattr(
        "backend.integrations.waha_sdk.get_client",
        lambda **_kwargs: _FakeWAHAClient(),
    )

    result = webhook.reset_whatsapp_config(
        user=SimpleNamespace(id=11, email="owner@example.com", company_id=7),
        db=_DB(),
    )

    assert result["message"].startswith("Configurações do WhatsApp removidas")
    assert events == ["lock", "recheck", "config", "remote", "update", "commit"]


def test_whatsapp_reset_remote_failure_rolls_back_and_preserves_config(monkeypatch):
    events = []

    class _DB:
        def execute(self, *_args, **_kwargs):
            pytest.fail("configuração local não pode ser limpa após falha WAHA")

        def rollback(self):
            events.append("rollback")

    monkeypatch.setattr(
        webhook,
        "_lock_operational_whatsapp_company",
        lambda _db, company_id: events.append(f"fence:{company_id}"),
    )
    monkeypatch.setattr(
        whatsapp_provider.WhatsAppConfig,
        "from_company",
        classmethod(
            lambda cls, company_id, db=None: WhatsAppConfig(
                "waha",
                session_name="sessao-teste",
                base_url="http://waha.local",
                api_key="test-key",
            )
        ),
    )

    class _FailingWAHAClient:
        def delete_session(self, session_name, logout):
            events.append(f"delete:{session_name}:{logout}")
            raise WAHAException("upstream timeout")

    monkeypatch.setattr(
        "backend.integrations.waha_sdk.get_client",
        lambda **_kwargs: _FailingWAHAClient(),
    )

    with pytest.raises(HTTPException) as error:
        webhook.reset_whatsapp_config(
            user=SimpleNamespace(id=11, email="owner@example.com", company_id=7),
            db=_DB(),
        )

    assert error.value.status_code == 503
    assert error.value.headers["Retry-After"] == "30"
    assert events == ["fence:7", "delete:sessao-teste:True", "rollback"]


def test_whatsapp_reset_missing_remote_session_clears_local_config(monkeypatch):
    events = []

    class _Result:
        rowcount = 1

    class _DB:
        def execute(self, _query, params):
            assert params == {"cid": 7}
            events.append("update")
            return _Result()

        def rollback(self):
            events.append("rollback")

        def commit(self):
            events.append("commit")

    monkeypatch.setattr(
        webhook,
        "_lock_operational_whatsapp_company",
        lambda _db, company_id: events.append(f"fence:{company_id}"),
    )
    monkeypatch.setattr(
        whatsapp_provider.WhatsAppConfig,
        "from_company",
        classmethod(
            lambda cls, company_id, db=None: WhatsAppConfig(
                "waha",
                session_name="sessao-teste",
                base_url="http://waha.local",
                api_key="test-key",
            )
        ),
    )

    class _MissingWAHAClient:
        def delete_session(self, session_name, logout):
            events.append(f"delete:{session_name}:{logout}")
            raise WAHAException("404 session not found")

    monkeypatch.setattr(
        "backend.integrations.waha_sdk.get_client",
        lambda **_kwargs: _MissingWAHAClient(),
    )

    result = webhook.reset_whatsapp_config(
        user=SimpleNamespace(id=11, email="owner@example.com", company_id=7),
        db=_DB(),
    )

    assert result["message"].startswith("Configurações do WhatsApp removidas")
    assert events == ["fence:7", "delete:sessao-teste:True", "update", "commit"]


def test_refund_wins_whatsapp_reset_before_any_remote_or_config_mutation(
    monkeypatch,
):
    def blocked(_db, _company_id):
        raise HTTPException(status_code=423, detail="Acesso da empresa suspenso")

    monkeypatch.setattr(webhook, "_lock_operational_whatsapp_company", blocked)
    monkeypatch.setattr(
        whatsapp_provider.WhatsAppConfig,
        "from_company",
        classmethod(
            lambda cls, company_id, db=None: pytest.fail(
                "configuração não deve ser lida após bloqueio"
            )
        ),
    )
    monkeypatch.setattr(
        "backend.integrations.waha_sdk.get_client",
        lambda **_kwargs: pytest.fail("WAHA não deve ser chamado após bloqueio"),
    )

    with pytest.raises(HTTPException) as error:
        webhook.reset_whatsapp_config(
            user=SimpleNamespace(id=11, email="owner@example.com", company_id=7),
            db=object(),
        )

    assert error.value.status_code == 423


@pytest.mark.parametrize(
    "invoke",
    [
        lambda db, user: webhook.restart_instance(user=user, db=db),
        lambda db, user: webhook.connect_waha(user=user, db=db),
        lambda db, user: webhook.request_waha_pairing_code(
            request=webhook.WAHAPairingCodeRequest(
                phone_number="5500000000007",
            ),
            user=user,
            db=db,
        ),
        lambda db, user: webhook.start_waha_session(user=user, db=db),
    ],
)
def test_waha_start_connect_pairing_routes_fail_closed_before_remote(
    monkeypatch,
    invoke,
):
    def blocked(_db, _company_id):
        raise HTTPException(status_code=423, detail="Acesso da empresa suspenso")

    monkeypatch.setattr(webhook, "_lock_operational_whatsapp_company", blocked)
    monkeypatch.setattr(
        "backend.integrations.waha_sdk.get_client",
        lambda **_kwargs: pytest.fail("WAHA não deve ser chamado após bloqueio"),
    )

    db = _RollbackOnlyDB()
    with pytest.raises(HTTPException) as error:
        invoke(
            db,
            SimpleNamespace(
                id=11,
                email="owner@example.com",
                company_id=7,
            ),
        )

    assert error.value.status_code == 423
    assert db.rollbacks == 1


def test_waha_enable_update_is_conditional_on_active_company():
    class _Result:
        rowcount = 0

    class _DB:
        def __init__(self):
            self.sql = ""
            self.params = {}
            self.rolled_back = False
            self.committed = False

        def execute(self, query, params):
            self.sql = " ".join(str(query).split())
            self.params = params
            return _Result()

        def rollback(self):
            self.rolled_back = True

        def commit(self):
            self.committed = True

    db = _DB()

    with pytest.raises(HTTPException) as error:
        webhook._persist_active_waha_configuration(db, 7, "sessao-teste")

    assert error.value.status_code == 423
    assert "operational_status = 'active'" in db.sql
    assert db.params == {"session_name": "sessao-teste", "cid": 7}
    assert db.rolled_back is True
    assert db.committed is False


def test_flow_executor_rechecks_company_before_every_node(monkeypatch):
    events = []
    db = object()
    executor = FlowExecutor(
        flow_id=10,
        company_id=7,
        trigger_data={},
    )
    executor.nodes = [
        {"id": "first", "type": "action", "data": {}},
        {"id": "second", "type": "action", "data": {}},
    ]
    executor.edges = [{"source": "first", "target": "second"}]

    def fake_lock(current_db, *, company_ids=(), **_kwargs):
        assert current_db is db
        assert list(company_ids) == [7]
        events.append("lock")

    checks = iter(["active", "refund_pending"])

    def fake_ensure(current_db, company_id):
        assert current_db is db
        status = next(checks)
        events.append(f"recheck:{status}")
        if status != "active":
            raise company_access_control.CompanyOperationallyBlockedError(
                company_id,
                status,
            )

    class _Handler:
        def execute(self, **kwargs):
            events.append(f"handler:{kwargs['node_data'].get('name', 'node')}")
            return {"success": True}

    monkeypatch.setattr(
        company_access_control,
        "lock_refund_entities_for_mutation",
        fake_lock,
    )
    monkeypatch.setattr(
        company_access_control,
        "ensure_company_operational",
        fake_ensure,
    )
    monkeypatch.setattr(
        "backend.services.flow_node_handlers.get_node_handler",
        lambda _node_type: _Handler(),
    )
    executor.nodes[0]["data"]["name"] = "first"
    executor.nodes[1]["data"]["name"] = "second"

    executor._execute_chain(db, executor.nodes[0])

    assert events == [
        "lock",
        "recheck:active",
        "handler:first",
        "lock",
        "recheck:refund_pending",
    ]
    assert executor.nodes_executed == 1
    assert executor.execution_log[-1]["error"] == "company_access_suspended"
