import asyncio
import ast
import inspect
import json
import threading
import time
from contextlib import suppress
from types import SimpleNamespace

import pytest
import anyio
from starlette.concurrency import run_in_threadpool as shared_run_in_threadpool

from backend.services.company_access_control import (
    CompanyOperationalLockBusyError,
    try_lock_entities_for_access,
)
from backend.ws_manager import (
    BROADCAST_BUSY,
    BROADCAST_DEDUPLICATED,
    BROADCAST_DELIVERED,
    BROADCAST_NO_LOCAL_SOCKET,
    ConnectionManager,
    WEBSOCKET_AUTH_EXECUTOR_WORKERS,
    _RedisDispatchItem,
)


class _ConnectedState:
    name = "CONNECTED"


class _DisconnectedState:
    name = "DISCONNECTED"


class _FakeWebSocket:
    def __init__(self):
        self.client_state = _ConnectedState()
        self.application_state = _ConnectedState()
        self.sent = []
        self.closed = []

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self, code, reason):
        self.closed.append((code, reason))
        self.application_state = _DisconnectedState()


class _BlockingWebSocket(_FakeWebSocket):
    def __init__(self):
        super().__init__()
        self.send_started = asyncio.Event()
        self.send_cancelled = asyncio.Event()

    async def send_json(self, payload):
        self.send_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.send_cancelled.set()
            raise


class _BlockingCloseWebSocket(_FakeWebSocket):
    def __init__(self):
        super().__init__()
        self.close_started = asyncio.Event()
        self.close_cancelled = asyncio.Event()

    async def close(self, code, reason):
        self.close_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.close_cancelled.set()
            raise


class _FakeRedis:
    def __init__(self):
        self.published = []

    async def publish(self, channel, payload):
        self.published.append((channel, payload))


class _FenceDB:
    def __init__(self):
        self.rolled_back = False
        self.is_closed = False

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.is_closed = True


class _FenceObservingWebSocket(_FakeWebSocket):
    def __init__(self, fence):
        super().__init__()
        self.fence_released_when_closed = None
        self.fence = fence

    async def close(self, code, reason):
        self.fence_released_when_closed = (
            self.fence.rolled_back and self.fence.is_closed
        )
        await super().close(code, reason)


class _LockObservingWebSocket(_FakeWebSocket):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.send_lock_states = []

    async def send_json(self, payload):
        self.send_lock_states.append(self.manager.lock.locked())
        await super().send_json(payload)


class _SerializingWebSocket(_FakeWebSocket):
    def __init__(self):
        super().__init__()
        self.active_sends = 0
        self.max_active_sends = 0

    async def send_json(self, payload):
        self.active_sends += 1
        self.max_active_sends = max(self.max_active_sends, self.active_sends)
        try:
            await asyncio.sleep(0.01)
            self.sent.append(payload)
        finally:
            self.active_sends -= 1


class _FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _FakePostgresSession:
    def __init__(self, results):
        self.results = iter(results)
        self.executed = []
        self.rollback_count = 0
        self.bind = SimpleNamespace(
            dialect=SimpleNamespace(name="postgresql")
        )

    def get_bind(self):
        return self.bind

    def execute(self, statement, parameters):
        self.executed.append((str(statement), parameters["lock_key"]))
        return _FakeScalarResult(next(self.results))

    def rollback(self):
        self.rollback_count += 1


async def _connect_after_prior_webhook_event():
    manager = ConnectionManager()

    await manager.broadcast_to_phone(
        10,
        "webhook_listener_10",
        {"type": "webhook_event", "payload": {"name": "Evento antigo"}},
    )

    websocket = _FakeWebSocket()
    await manager.connect(websocket, client_id="6", company_id=10, phone="webhook_listener_10")

    assert [message["type"] for message in websocket.sent] == ["connection_established"]


def test_connect_does_not_replay_cached_webhook_event():
    asyncio.run(_connect_after_prior_webhook_event())


async def _publish_revocation_closes_local_before_redis():
    manager = ConnectionManager()
    manager.redis = _FakeRedis()
    websocket = _FakeWebSocket()
    await manager.connect(websocket, client_id="6", company_id=10, phone="__global__")

    await manager.publish_access_revocation([10])

    assert websocket.closed == [(4003, "access_revoked")]
    assert 10 not in manager.connections
    assert manager.redis.published[0][0] == manager._websocket_channel(
        "access_revocations"
    )


def test_publish_revocation_closes_local_socket_and_notifies_other_workers():
    asyncio.run(_publish_revocation_closes_local_before_redis())


async def _selective_revocation_closes_deactivated_principal_in_shared_workspace():
    manager = ConnectionManager()
    manager.redis = _FakeRedis()
    deactivated_socket = _FakeWebSocket()
    third_party_socket = _FakeWebSocket()
    await manager.connect(
        deactivated_socket,
        client_id="10",
        company_id=20,
        phone="__global__",
        send_confirmation=False,
        access_epoch=7,
        user_id="10",
        user_type="master",
        auth_token_version=1,
    )
    await manager.connect(
        third_party_socket,
        client_id="30",
        company_id=20,
        phone="__global__",
        send_confirmation=False,
        access_epoch=7,
        user_id="30",
        user_type="master",
        auth_token_version=4,
    )

    await manager.publish_access_revocation(
        [],
        client_ids=[10],
        user_ids=[11],
    )

    assert deactivated_socket.closed == [(4003, "access_revoked")]
    assert third_party_socket.closed == []
    assert set(manager.connections[20]) == {"30"}
    channel, raw_payload = manager.redis.published[0]
    assert channel == manager._websocket_channel("access_revocations")
    assert json.loads(raw_payload) == {
        "company_ids": [],
        "client_ids": [10],
        "user_ids": [11],
    }


def test_selective_revocation_crosses_shared_workspace_without_closing_owner():
    asyncio.run(
        _selective_revocation_closes_deactivated_principal_in_shared_workspace()
    )


async def _redis_failure_does_not_leave_local_deactivated_socket_open():
    manager = ConnectionManager()

    class _UnavailableRedis:
        async def publish(self, *_args, **_kwargs):
            raise RuntimeError("redis unavailable")

    manager.redis = _UnavailableRedis()
    websocket = _FakeWebSocket()
    await manager.connect(
        websocket,
        client_id="10",
        company_id=20,
        phone="__global__",
        send_confirmation=False,
    )

    await manager.publish_access_revocation([], client_ids=[10])

    assert websocket.closed == [(4003, "access_revoked")]
    assert 20 not in manager.connections


def test_redis_failure_is_fail_closed_locally_and_does_not_escape():
    asyncio.run(_redis_failure_does_not_leave_local_deactivated_socket_open())


async def _publish_revocation_bounds_stalled_close():
    manager = ConnectionManager()
    manager.websocket_close_timeout_seconds = 0.03
    manager.redis = _FakeRedis()
    websocket = _BlockingCloseWebSocket()
    await manager.connect(
        websocket,
        client_id="6",
        company_id=10,
        phone="__global__",
        send_confirmation=False,
    )

    await asyncio.wait_for(manager.publish_access_revocation([10]), timeout=0.2)

    assert websocket.close_started.is_set()
    assert websocket.close_cancelled.is_set()
    assert 10 not in manager.connections
    assert manager.redis.published[0][0] == manager._websocket_channel(
        "access_revocations"
    )


def test_publish_revocation_is_not_stalled_by_socket_close():
    asyncio.run(_publish_revocation_bounds_stalled_close())


def test_start_fails_readiness_and_cleans_partial_state_when_redis_is_unavailable(
    monkeypatch,
):
    async def scenario():
        manager = ConnectionManager()

        def redis_unavailable(*_args, **_kwargs):
            raise RuntimeError("redis unavailable")

        monkeypatch.setattr(
            "backend.ws_manager.aioredis.from_url",
            redis_unavailable,
        )
        with pytest.raises(RuntimeError, match="redis unavailable"):
            await manager.start()

        assert manager.redis is None
        assert manager.task is None
        assert manager.reconciliation_task is None


    asyncio.run(scenario())


def test_start_fails_readiness_when_initial_subscription_fails(monkeypatch):
    async def scenario():
        manager = ConnectionManager()

        class FailingPubSub:
            def __init__(self):
                self.closed = False

            async def psubscribe(self, _pattern):
                raise RuntimeError("subscription unavailable")

            async def aclose(self):
                self.closed = True

        class Redis:
            def __init__(self):
                self.closed = False
                self.pubsub_resource = FailingPubSub()

            async def ping(self):
                return True

            def pubsub(self):
                return self.pubsub_resource

            async def aclose(self):
                self.closed = True

        redis_client = Redis()
        monkeypatch.setattr(
            "backend.ws_manager.aioredis.from_url",
            lambda *_args, **_kwargs: redis_client,
        )

        with pytest.raises(RuntimeError, match="subscription unavailable"):
            await manager.start()

        assert redis_client.closed is True
        assert redis_client.pubsub_resource.closed is True
        assert manager.redis is None
        assert manager.task is None
        assert manager.reconciliation_task is None

    asyncio.run(scenario())


async def _revocation_before_post_registration_recheck_is_rejected():
    manager = ConnectionManager()
    websocket = _FakeWebSocket()
    check_started = asyncio.Event()
    release_check = asyncio.Event()

    async def access_check():
        check_started.set()
        await release_check.wait()
        return None

    connecting = asyncio.create_task(
        manager.connect_with_access_barrier(
            websocket,
            client_id="6",
            company_id=10,
            phones=["__global__"],
            access_check=access_check,
        )
    )
    await check_started.wait()

    assert 10 in manager.connections
    assert websocket.sent == []

    await manager.close_company_connections([10])
    release_check.set()

    assert await connecting is False
    assert 10 not in manager.connections
    assert websocket.closed == [(4003, "access_revoked")]


def test_revocation_before_post_registration_recheck_cannot_leave_socket_open():
    asyncio.run(_revocation_before_post_registration_recheck_is_rejected())


async def _revocation_after_post_registration_recheck_reaches_registered_socket():
    manager = ConnectionManager()
    websocket = _FakeWebSocket()

    async def access_check():
        return 0

    connected = await manager.connect_with_access_barrier(
        websocket,
        client_id="6",
        company_id=10,
        phones=["contact", "__global__"],
        access_check=access_check,
    )

    assert connected is True
    assert 10 in manager.connections
    assert websocket.sent == []

    await manager.close_company_connections([10])

    assert 10 not in manager.connections
    assert websocket.closed == [(4003, "access_revoked")]


def test_revocation_after_post_registration_recheck_closes_registered_socket():
    asyncio.run(_revocation_after_post_registration_recheck_reaches_registered_socket())


async def _missed_pubsub_revocation_is_caught_before_broadcast():
    manager = ConnectionManager()
    stale_socket = _FakeWebSocket()
    await manager.connect(
        stale_socket,
        client_id="6",
        company_id=10,
        phone="contact",
        send_confirmation=False,
        access_epoch=0,
    )

    fence_sessions = []

    def current_epoch(_company_id, _connections=()):
        db = _FenceDB()
        fence_sessions.append(db)
        return db, 1

    manager._open_company_access_fence = current_epoch
    await manager.broadcast_to_phone(
        10,
        "contact",
        {"type": "message", "content": "não pode vazar"},
    )

    assert stale_socket.sent == []
    assert stale_socket.closed == [(4003, "access_revoked")]
    assert 10 not in manager.connections or not manager.connections[10]
    assert fence_sessions[0].rolled_back is True
    assert fence_sessions[0].is_closed is True

    fresh_socket = _FakeWebSocket()
    await manager.connect(
        fresh_socket,
        client_id="6",
        company_id=10,
        phone="contact",
        send_confirmation=False,
        access_epoch=1,
    )
    await manager.broadcast_to_phone(
        10,
        "contact",
        {"type": "message", "content": "permitida"},
    )

    assert [item["content"] for item in fresh_socket.sent] == ["permitida"]
    assert fresh_socket.closed == []


def test_missed_pubsub_revocation_blocks_stale_broadcast_and_allows_fresh_reconnect():
    asyncio.run(_missed_pubsub_revocation_is_caught_before_broadcast())


async def _global_fallback_is_fenced_for_active_and_blocked_companies():
    active_manager = ConnectionManager()
    active_socket = _LockObservingWebSocket(active_manager)
    await active_manager.connect(
        active_socket,
        client_id="6",
        company_id=10,
        phone="__global__",
        send_confirmation=False,
        access_epoch=4,
    )
    active_fence = _FenceDB()
    active_manager._open_company_access_fence = (
        lambda _company_id, _connections=(): (active_fence, 4)
    )

    await active_manager.broadcast_global(
        10,
        {"type": "global_notification", "content": "permitida"},
    )

    assert [item["content"] for item in active_socket.sent] == ["permitida"]
    assert active_socket.send_lock_states == [False]
    assert active_fence.rolled_back is True
    assert active_fence.is_closed is True

    blocked_manager = ConnectionManager()
    blocked_socket = _LockObservingWebSocket(blocked_manager)
    await blocked_manager.connect(
        blocked_socket,
        client_id="7",
        company_id=11,
        phone="__global__",
        send_confirmation=False,
        access_epoch=2,
    )
    blocked_manager._open_company_access_fence = (
        lambda _company_id, _connections=(): (_ for _ in ()).throw(
            RuntimeError("inactive")
        )
    )

    await blocked_manager.broadcast_global(
        11,
        {"type": "global_notification", "content": "não pode sair"},
    )

    assert blocked_socket.sent == []
    assert blocked_socket.closed == [(4003, "access_revoked")]
    assert 11 not in blocked_manager.connections


def test_global_fallback_uses_durable_fence_and_never_sends_under_manager_lock():
    asyncio.run(_global_fallback_is_fenced_for_active_and_blocked_companies())


async def _reconciliation_closes_socket_when_durable_access_cannot_be_read():
    manager = ConnectionManager()
    websocket = _FakeWebSocket()
    await manager.connect(
        websocket,
        client_id="6",
        company_id=10,
        phone="__global__",
        send_confirmation=False,
        access_epoch=2,
    )

    def unavailable(_company_id, _connections=()):
        raise RuntimeError("database unavailable")

    manager._open_company_access_fence = unavailable

    assert await manager.reconcile_company_access(10) is False
    assert websocket.closed == [(4003, "access_revoked")]
    assert 10 not in manager.connections


def test_reconciliation_is_fail_closed_when_durable_state_is_unavailable():
    asyncio.run(_reconciliation_closes_socket_when_durable_access_cannot_be_read())


def test_reconciliation_revalidates_principal_in_shared_active_company(monkeypatch):
    async def scenario():
        manager = ConnectionManager()
        deactivated_socket = _FakeWebSocket()
        owner_socket = _FakeWebSocket()
        stale_token_socket = _FakeWebSocket()
        for websocket, client_id, token_version in (
            (deactivated_socket, "10", 1),
            (owner_socket, "30", 4),
            (stale_token_socket, "40", 1),
        ):
            await manager.connect(
                websocket,
                client_id=client_id,
                company_id=20,
                phone="__global__",
                send_confirmation=False,
                access_epoch=7,
                user_id=client_id,
                user_type="master",
                auth_token_version=token_version,
            )

        clients = {
            10: SimpleNamespace(
                id=10,
                email="deactivated@example.com",
                is_active=False,
                auth_token_version=1,
            ),
            30: SimpleNamespace(
                id=30,
                email="owner@example.com",
                is_active=True,
                auth_token_version=4,
            ),
            40: SimpleNamespace(
                id=40,
                email="stale@example.com",
                is_active=True,
                auth_token_version=2,
            ),
        }

        class _Query:
            def __init__(self, model):
                self.model = model
                self.entity_id = None

            def filter(self, *criteria):
                for criterion in criteria:
                    left = getattr(criterion, "left", None)
                    right = getattr(criterion, "right", None)
                    if getattr(left, "key", None) == "id":
                        self.entity_id = int(getattr(right, "value"))
                return self

            def first(self):
                if self.model.__name__ == "Client":
                    return clients.get(self.entity_id)
                return None

        class _PrincipalFenceDB(_FenceDB):
            def query(self, model):
                return _Query(model)

        fence = _PrincipalFenceDB()
        manager._open_company_access_fence = lambda _company_id, _connections=(): (fence, 7)
        assert await manager.reconcile_company_access(20) is True
        assert deactivated_socket.closed == [(4003, "access_revoked")]
        assert stale_token_socket.closed == [(4003, "access_revoked")]
        assert owner_socket.closed == []
        assert set(manager.connections[20]) == {"30"}
        assert fence.rolled_back is True
        assert fence.is_closed is True

    asyncio.run(scenario())


async def _reconciliation_releases_fence_before_closing_stale_socket():
    manager = ConnectionManager()
    fence = _FenceDB()
    websocket = _FenceObservingWebSocket(fence)
    await manager.connect(
        websocket,
        client_id="6",
        company_id=10,
        phone="__global__",
        send_confirmation=False,
        access_epoch=1,
    )

    manager._open_company_access_fence = lambda _company_id, _connections=(): (fence, 2)

    assert await manager.reconcile_company_access(10) is True
    assert websocket.closed == [(4003, "access_revoked")]
    assert websocket.fence_released_when_closed is True
    assert 10 not in manager.connections


def test_reconciliation_releases_db_fence_before_network_close():
    asyncio.run(_reconciliation_releases_fence_before_closing_stale_socket())


async def _stalled_broadcast_times_out_and_releases_fence():
    manager = ConnectionManager()
    manager.websocket_send_timeout_seconds = 0.03
    fence = _FenceDB()
    websocket = _BlockingWebSocket()
    await manager.connect(
        websocket,
        client_id="6",
        company_id=10,
        phone="contact",
        send_confirmation=False,
        access_epoch=1,
    )
    manager._open_company_access_fence = lambda _company_id, _connections=(): (fence, 1)

    broadcasting = asyncio.create_task(
        manager.broadcast_to_phone(
            10,
            "contact",
            {"type": "message", "content": "bounded"},
        )
    )
    await asyncio.wait_for(websocket.send_started.wait(), timeout=0.1)

    await asyncio.wait_for(manager.lock.acquire(), timeout=0.02)
    manager.lock.release()
    assert fence.rolled_back is False
    assert fence.is_closed is False

    await asyncio.wait_for(broadcasting, timeout=0.2)

    assert websocket.send_cancelled.is_set()
    assert fence.rolled_back is True
    assert fence.is_closed is True
    assert 10 not in manager.connections
    assert websocket.closed == [(1011, "send_failed")]


def test_stalled_websocket_send_is_bounded_and_does_not_hold_fence_forever():
    asyncio.run(_stalled_broadcast_times_out_and_releases_fence())


def test_access_fence_uses_shared_try_locks_in_global_entity_order():
    db = _FakePostgresSession([True] * 6)

    try_lock_entities_for_access(
        db,
        company_ids=[20, 10, 20],
        client_ids=[4, 2],
        user_ids=[9, 8],
    )

    assert [lock_key for _sql, lock_key in db.executed] == [
        "entity-mutation:company:10",
        "entity-mutation:company:20",
        "entity-mutation:client:2",
        "entity-mutation:client:4",
        "entity-mutation:user:8",
        "entity-mutation:user:9",
    ]
    assert all(
        "pg_try_advisory_xact_lock_shared" in sql
        and "pg_advisory_xact_lock(" not in sql
        for sql, _lock_key in db.executed
    )
    assert db.rollback_count == 0


def test_access_fence_rolls_back_immediately_on_exclusive_lock_contention():
    db = _FakePostgresSession([True, False, True])

    with pytest.raises(CompanyOperationalLockBusyError):
        try_lock_entities_for_access(
            db,
            company_ids=[10],
            client_ids=[2],
            user_ids=[8],
        )

    assert [lock_key for _sql, lock_key in db.executed] == [
        "entity-mutation:company:10",
        "entity-mutation:client:2",
    ]
    assert db.rollback_count == 1


async def _concurrent_broadcasts_are_serialized_per_company():
    manager = ConnectionManager()
    websocket = _SerializingWebSocket()
    await manager.connect(
        websocket,
        client_id="6",
        company_id=10,
        phone="contact",
        send_confirmation=False,
        access_epoch=1,
    )

    fences = []

    def active_fence(_company_id, _connections=()):
        fence = _FenceDB()
        fences.append(fence)
        return fence, 1

    manager._open_company_access_fence = active_fence
    await asyncio.gather(
        *(
            manager.broadcast_to_phone(
                10,
                "contact",
                {"type": "message", "sequence": sequence},
            )
            for sequence in range(3)
        )
    )

    assert websocket.max_active_sends == 1
    assert [payload["sequence"] for payload in websocket.sent] == [0, 1, 2]
    assert len(fences) == 3
    assert all(fence.rolled_back and fence.is_closed for fence in fences)


def test_concurrent_broadcasts_are_serialized_per_company():
    asyncio.run(_concurrent_broadcasts_are_serialized_per_company())


async def _busy_access_fence_retries_without_stalling_event_loop():
    manager = ConnectionManager()
    manager.access_fence_retry_attempts = 4
    manager.access_fence_retry_delay_seconds = 0.01
    websocket = _FakeWebSocket()
    await manager.connect(
        websocket,
        client_id="6",
        company_id=10,
        phone="contact",
        send_confirmation=False,
        access_epoch=1,
    )

    attempts = 0
    fence = _FenceDB()

    def eventually_available(_company_id, _connections=()):
        nonlocal attempts
        attempts += 1
        if attempts < 4:
            raise CompanyOperationalLockBusyError(10)
        return fence, 1

    manager._open_company_access_fence = eventually_available
    heartbeat_ticks = 0
    stop_heartbeat = asyncio.Event()

    async def heartbeat():
        nonlocal heartbeat_ticks
        while not stop_heartbeat.is_set():
            heartbeat_ticks += 1
            await asyncio.sleep(0.001)

    heartbeat_task = asyncio.create_task(heartbeat())
    await asyncio.wait_for(
        manager.broadcast_to_phone(
            10,
            "contact",
            {"type": "message", "content": "after access fence"},
        ),
        timeout=0.2,
    )
    stop_heartbeat.set()
    await heartbeat_task

    assert attempts == 4
    assert heartbeat_ticks >= 20
    assert [item["content"] for item in websocket.sent] == [
        "after access fence"
    ]
    assert websocket.closed == []
    assert fence.rolled_back is True
    assert fence.is_closed is True


def test_busy_access_fence_retries_asynchronously_and_keeps_heartbeat_alive():
    asyncio.run(_busy_access_fence_retries_without_stalling_event_loop())


async def _persistent_busy_fence_does_not_impersonate_access_revocation():
    manager = ConnectionManager()
    manager.access_fence_retry_attempts = 3
    manager.access_fence_retry_delay_seconds = 0.005
    websocket = _FakeWebSocket()
    await manager.connect(
        websocket,
        client_id="6",
        company_id=10,
        phone="contact",
        send_confirmation=False,
        access_epoch=1,
    )

    attempts = 0

    def always_busy(_company_id, _connections=()):
        nonlocal attempts
        attempts += 1
        raise CompanyOperationalLockBusyError(10)

    manager._open_company_access_fence = always_busy
    await asyncio.wait_for(
        manager.broadcast_to_phone(
            10,
            "contact",
            {"type": "message", "content": "not delivered while busy"},
        ),
        timeout=0.1,
    )

    assert attempts == 3
    assert websocket.sent == []
    assert websocket.closed == []
    assert 10 in manager.connections
    assert manager._company_operation_lock(10).locked() is False


def test_persistent_busy_fence_is_bounded_and_does_not_close_socket():
    asyncio.run(_persistent_busy_fence_does_not_impersonate_access_revocation())


async def _broadcast_without_local_socket_does_not_open_fence():
    manager = ConnectionManager()
    fence_opened = False

    def forbidden_fence(_company_id, _connections=()):
        nonlocal fence_opened
        fence_opened = True
        raise AssertionError("fence must not open without a local socket")

    manager._open_company_access_fence = forbidden_fence
    await manager.broadcast_to_phone(
        10,
        "contact",
        {"type": "message"},
    )

    assert fence_opened is False


def test_broadcast_checks_local_socket_before_opening_database_fence():
    asyncio.run(_broadcast_without_local_socket_does_not_open_fence())


def test_explicit_event_id_is_deduplicated_per_worker_and_channel():
    async def scenario():
        manager = ConnectionManager()
        payload = {"event_id": "support:602"}

        assert manager._claim_event_id("chat_messages:3", payload) is True
        assert manager._claim_event_id("chat_messages:3", payload) is False
        assert manager._claim_event_id("company_global:3", payload) is True

    asyncio.run(scenario())


def test_redis_publish_is_bounded():
    async def scenario():
        manager = ConnectionManager()
        manager.redis_publish_timeout_seconds = 0.01

        class _StalledRedis:
            async def publish(self, _channel, _payload):
                await asyncio.Event().wait()

        manager.redis = _StalledRedis()
        with pytest.raises(asyncio.TimeoutError):
            await manager._publish_redis("channel", "payload")

    asyncio.run(scenario())


def test_fence_prepare_revalidation_and_cleanup_never_run_on_event_loop_thread():
    async def scenario():
        manager = ConnectionManager()
        websocket = _FakeWebSocket()
        await manager.connect(
            websocket,
            client_id="6",
            company_id=10,
            phone="contact",
            send_confirmation=False,
            access_epoch=1,
        )

        loop_thread_id = threading.get_ident()
        db_thread_ids = []
        heartbeat_ticks = 0
        stop_heartbeat = asyncio.Event()

        class _ThreadTrackingFence(_FenceDB):
            def rollback(self):
                db_thread_ids.append(threading.get_ident())
                super().rollback()

            def close(self):
                db_thread_ids.append(threading.get_ident())
                super().close()

        fence = _ThreadTrackingFence()

        def delayed_open(_company_id, _connections=()):
            db_thread_ids.append(threading.get_ident())
            time.sleep(0.05)
            return fence, 1

        original_revalidate = manager._connection_principal_is_active

        def tracked_revalidate(db, connection):
            db_thread_ids.append(threading.get_ident())
            return original_revalidate(db, connection)

        manager._open_company_access_fence = delayed_open
        manager._connection_principal_is_active = tracked_revalidate

        async def heartbeat():
            nonlocal heartbeat_ticks
            while not stop_heartbeat.is_set():
                heartbeat_ticks += 1
                await asyncio.sleep(0.001)

        heartbeat_task = asyncio.create_task(heartbeat())
        result = await manager.broadcast_to_phone(
            10,
            "contact",
            {"type": "message", "content": "threadpool"},
        )
        stop_heartbeat.set()
        await heartbeat_task

        assert result == BROADCAST_DELIVERED
        assert heartbeat_ticks >= 20
        assert db_thread_ids
        assert all(thread_id != loop_thread_id for thread_id in db_thread_ids)
        assert fence.rolled_back is True
        assert fence.is_closed is True

    asyncio.run(scenario())


def test_company_serializer_releases_even_when_database_cleanup_fails():
    async def scenario():
        manager = ConnectionManager()
        websocket = _FakeWebSocket()
        await manager.connect(
            websocket,
            client_id="6",
            company_id=10,
            phone="contact",
            send_confirmation=False,
            access_epoch=1,
        )

        class _CleanupFailureFence(_FenceDB):
            def rollback(self):
                raise RuntimeError("rollback unavailable")

        fence = _CleanupFailureFence()
        manager._open_company_access_fence = (
            lambda _company_id, _connections=(): (fence, 1)
        )

        result = await manager.broadcast_to_phone(
            10,
            "contact",
            {"type": "message", "content": "cleanup failure"},
        )

        assert result == "failed"
        assert fence.is_closed is True
        assert manager._company_operation_lock(10).locked() is False
        assert websocket.closed == [(4003, "access_revoked")]
        assert 10 not in manager.connections

    asyncio.run(scenario())


def test_per_company_redis_queues_isolate_slow_sockets_and_preserve_order():
    async def scenario():
        manager = ConnectionManager()
        first_company_started = asyncio.Event()
        release_first_company = asyncio.Event()
        second_company_delivered = asyncio.Event()
        deliveries = []

        async def fake_broadcast(company_id, _phone, payload, **_kwargs):
            if company_id == 10 and payload["sequence"] == 1:
                first_company_started.set()
                await release_first_company.wait()
            deliveries.append((company_id, payload["sequence"]))
            if company_id == 20:
                second_company_delivered.set()
            return BROADCAST_DELIVERED

        manager.broadcast_to_phone = fake_broadcast
        manager._enqueue_redis_dispatch_item(
            _RedisDispatchItem(
                company_id=10,
                channel="chat_messages:10",
                steps=[("contact", {"sequence": 1})],
            )
        )
        manager._enqueue_redis_dispatch_item(
            _RedisDispatchItem(
                company_id=10,
                channel="chat_messages:10",
                steps=[("contact", {"sequence": 2})],
            )
        )
        manager._enqueue_redis_dispatch_item(
            _RedisDispatchItem(
                company_id=20,
                channel="chat_messages:20",
                steps=[("contact", {"sequence": 1})],
            )
        )
        company_tasks = list(manager._redis_company_tasks.values())

        await asyncio.wait_for(first_company_started.wait(), timeout=0.1)
        await asyncio.wait_for(second_company_delivered.wait(), timeout=0.1)
        assert deliveries == [(20, 1)]

        release_first_company.set()
        await asyncio.gather(*company_tasks)
        assert deliveries == [(20, 1), (10, 1), (10, 2)]

    asyncio.run(scenario())


def test_redis_busy_fence_retries_current_event_without_reordering():
    async def scenario():
        manager = ConnectionManager()
        manager.redis_busy_requeue_log_interval = 3
        manager.redis_busy_requeue_delay_seconds = 0.001
        attempts = 0
        deliveries = []

        async def fake_broadcast(_company_id, _phone, payload, **_kwargs):
            nonlocal attempts
            attempts += 1
            if attempts <= 2:
                return BROADCAST_BUSY
            deliveries.append(payload["sequence"])
            return BROADCAST_DELIVERED

        manager.broadcast_to_phone = fake_broadcast
        manager._enqueue_redis_dispatch_item(
            _RedisDispatchItem(
                company_id=10,
                channel="chat_messages:10",
                steps=[("contact", {"sequence": 1, "event_id": "event-1"})],
            )
        )
        task = manager._redis_company_tasks[10]
        await asyncio.wait_for(task, timeout=0.1)

        assert attempts == 3
        assert deliveries == [1]

    asyncio.run(scenario())


def test_access_revocation_dispatch_bypasses_blocked_company_queue():
    async def scenario():
        manager = ConnectionManager()
        ordinary_started = asyncio.Event()
        release_ordinary = asyncio.Event()
        revocation_applied = asyncio.Event()

        async def slow_broadcast(*_args, **_kwargs):
            ordinary_started.set()
            await release_ordinary.wait()
            return BROADCAST_DELIVERED

        async def record_revocation(**_kwargs):
            revocation_applied.set()
            return 0

        manager.broadcast_to_phone = slow_broadcast
        manager.close_access_connections = record_revocation
        manager._enqueue_redis_dispatch_item(
            _RedisDispatchItem(
                company_id=10,
                channel="chat_messages:10",
                steps=[("contact", {"sequence": 1})],
            )
        )
        company_task = manager._redis_company_tasks[10]
        await ordinary_started.wait()

        manager._schedule_access_revocation({"company_ids": [10]})
        await asyncio.wait_for(revocation_applied.wait(), timeout=0.1)
        assert not company_task.done()

        release_ordinary.set()
        await company_task

    asyncio.run(scenario())


def test_local_fallback_and_late_redis_delivery_share_dedupe_claim():
    async def scenario():
        manager = ConnectionManager()
        websocket = _FakeWebSocket()
        await manager.connect(
            websocket,
            client_id="6",
            company_id=10,
            phone="contact:5",
            send_confirmation=False,
            access_epoch=1,
        )
        fences = []

        def active_fence(_company_id, _connections=()):
            fence = _FenceDB()
            fences.append(fence)
            return fence, 1

        manager._open_company_access_fence = active_fence
        payload = {
            "event_id": "chat:602:pending",
            "type": "chat_message",
        }

        first = await manager.broadcast_to_phone(
            10,
            "contact:5",
            payload,
        )
        late_redis = await manager.broadcast_to_phone(
            10,
            "contact:5",
            payload,
        )

        assert first == BROADCAST_DELIVERED
        assert late_redis == BROADCAST_DEDUPLICATED
        assert websocket.sent == [payload]
        assert len(fences) == 1

    asyncio.run(scenario())


def test_async_websocket_methods_do_not_call_sync_database_primitives():
    tree = ast.parse(inspect.getsource(ConnectionManager))
    violations = []
    for function in (
        node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef)
    ):
        for call in (
            node for node in ast.walk(function) if isinstance(node, ast.Call)
        ):
            if isinstance(call.func, ast.Name) and call.func.id == "SessionLocal":
                violations.append((function.name, "SessionLocal"))
            if (
                isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "db"
                and call.func.attr
                in {"execute", "query", "rollback", "close", "expire", "expire_all"}
            ):
                violations.append((function.name, f"db.{call.func.attr}"))

    assert violations == []


def test_websocket_fence_marks_internal_session_for_transaction_fuse(monkeypatch):
    manager = ConnectionManager()
    fence = _FenceDB()
    marked = []

    monkeypatch.setattr("backend.db.SessionLocal", lambda: fence)
    monkeypatch.setattr(
        "backend.db.mark_session_as_web_request",
        lambda session: marked.append(session) or session,
    )
    monkeypatch.setattr(
        "backend.services.company_access_control.try_lock_entities_for_access",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "backend.services.company_access_control.ensure_company_operational",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "backend.services.company_access_control.get_company_operational_epoch",
        lambda *_args, **_kwargs: 3,
    )

    opened, epoch = manager._open_company_access_fence(10, [])

    assert opened is fence
    assert epoch == 3
    assert marked == [fence]
    manager._cleanup_company_access_fence(opened)


def test_fence_cleanup_uses_reserved_executor_when_anyio_pool_is_saturated():
    async def scenario():
        limiter = anyio.to_thread.current_default_thread_limiter()
        original_tokens = limiter.total_tokens
        limiter.total_tokens = 2
        release_waiters = threading.Event()
        waiters_started = 0
        waiters_guard = threading.Lock()

        def blocking_access_waiter():
            nonlocal waiters_started
            with waiters_guard:
                waiters_started += 1
            release_waiters.wait(timeout=2)

        waiters = [
            asyncio.create_task(
                shared_run_in_threadpool(blocking_access_waiter)
            )
            for _ in range(2)
        ]
        try:
            for _ in range(100):
                with waiters_guard:
                    if waiters_started == 2:
                        break
                await asyncio.sleep(0.001)
            assert waiters_started == 2

            manager = ConnectionManager()
            websocket = _FakeWebSocket()
            await manager.connect(
                websocket,
                client_id="6",
                company_id=10,
                phone="contact",
                send_confirmation=False,
                access_epoch=1,
            )
            fence = _FenceDB()
            manager._open_company_access_fence = (
                lambda _company_id, _connections=(): (fence, 1)
            )
            heartbeat_ticks = 0
            stop_heartbeat = asyncio.Event()

            async def heartbeat():
                nonlocal heartbeat_ticks
                while not stop_heartbeat.is_set():
                    heartbeat_ticks += 1
                    await asyncio.sleep(0.001)

            heartbeat_task = asyncio.create_task(heartbeat())
            result = await asyncio.wait_for(
                manager.broadcast_to_phone(
                    10,
                    "contact",
                    {"type": "message", "content": "reserved cleanup"},
                ),
                timeout=0.5,
            )
            await asyncio.sleep(0.01)
            stop_heartbeat.set()
            await heartbeat_task

            assert result == BROADCAST_DELIVERED
            assert fence.rolled_back is True
            assert fence.is_closed is True
            assert heartbeat_ticks >= 5
            assert manager._company_operation_lock(10).locked() is False
        finally:
            release_waiters.set()
            await asyncio.gather(*waiters)
            limiter.total_tokens = original_tokens

    asyncio.run(scenario())


def test_company_queue_overflow_is_ordered_and_does_not_drop_claimed_events():
    async def scenario():
        manager = ConnectionManager()
        manager.redis_company_queue_maxsize = 1
        delivered = []

        async def fake_broadcast(_company_id, _phone, payload, **_kwargs):
            delivered.append(payload["sequence"])
            await asyncio.sleep(0)
            return BROADCAST_DELIVERED

        manager.broadcast_to_phone = fake_broadcast
        for sequence in range(1, 7):
            payload = {
                "sequence": sequence,
                "event_id": f"overflow:{sequence}",
            }
            channel = "chat_messages:10"
            assert manager.claim_event_for_local_delivery(channel, payload)
            assert manager._enqueue_redis_dispatch_item(
                _RedisDispatchItem(
                    company_id=10,
                    channel=channel,
                    steps=[("contact", payload)],
                )
            )

        task = manager._redis_company_tasks[10]
        await asyncio.wait_for(task, timeout=0.2)

        assert delivered == [1, 2, 3, 4, 5, 6]
        assert manager._redis_company_overflows == {}
        assert manager._redis_company_queues == {}

    asyncio.run(scenario())


def test_failed_enqueue_releases_reservation_for_fallback(monkeypatch):
    manager = ConnectionManager()
    channel = "chat_messages:10"
    payload = {"event_id": "chat:700:pending"}
    item = _RedisDispatchItem(
        company_id=10,
        channel=channel,
        steps=[("contact", payload)],
    )

    def fail_enqueue(_item):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(manager, "_enqueue_redis_dispatch_item", fail_enqueue)

    with pytest.raises(RuntimeError, match="queue unavailable"):
        manager._claim_and_enqueue_redis_item(channel, payload, item)

    assert manager.claim_event_for_local_delivery(channel, payload) is True


def test_busy_event_remains_at_queue_head_past_log_threshold_until_delivered():
    async def scenario():
        manager = ConnectionManager()
        manager.redis_busy_requeue_log_interval = 2
        manager.redis_busy_requeue_delay_seconds = 0.001
        manager.redis_busy_requeue_max_delay_seconds = 0.002
        attempts = 0
        delivered = []

        async def fake_broadcast(_company_id, _phone, payload, **_kwargs):
            nonlocal attempts
            attempts += 1
            if attempts <= 5:
                return BROADCAST_BUSY
            delivered.append(payload["event_id"])
            return BROADCAST_DELIVERED

        manager.broadcast_to_phone = fake_broadcast
        manager._enqueue_redis_dispatch_item(
            _RedisDispatchItem(
                company_id=10,
                channel="chat_messages:10",
                steps=[("contact", {"event_id": "eventual:1"})],
            )
        )
        await asyncio.wait_for(
            manager._redis_company_tasks[10],
            timeout=0.2,
        )

        assert attempts == 6
        assert delivered == ["eventual:1"]

    asyncio.run(scenario())


def test_persistent_busy_saturation_is_memory_bounded_and_closes_1013():
    async def scenario():
        manager = ConnectionManager()
        manager.redis_company_queue_maxsize = 1
        manager.redis_company_overflow_maxsize = 2
        manager.redis_busy_requeue_delay_seconds = 0.001
        manager.redis_busy_requeue_max_delay_seconds = 0.002
        websocket = _FakeWebSocket()
        await manager.connect(
            websocket,
            client_id="6",
            company_id=10,
            phone="contact",
            send_confirmation=False,
        )

        first_dispatch_started = asyncio.Event()
        keep_busy = True

        async def fake_broadcast(*_args, **_kwargs):
            first_dispatch_started.set()
            return BROADCAST_BUSY if keep_busy else BROADCAST_NO_LOCAL_SOCKET

        manager.broadcast_to_phone = fake_broadcast
        channel = manager._websocket_channel("chat_messages:10")

        def enqueue(sequence):
            payload = {
                "sequence": sequence,
                "event_id": f"bounded-overflow:{sequence}",
            }
            return manager._claim_and_enqueue_redis_item(
                channel,
                payload,
                _RedisDispatchItem(
                    company_id=10,
                    channel=channel,
                    steps=[("contact", payload)],
                ),
            )

        assert enqueue(1) is True
        await asyncio.wait_for(first_dispatch_started.wait(), timeout=0.1)
        dispatch_task = manager._redis_company_tasks[10]
        assert [enqueue(sequence) for sequence in range(2, 5)] == [
            True,
            True,
            True,
        ]

        heartbeat_ticks = 0
        stop_heartbeat = asyncio.Event()

        async def heartbeat():
            nonlocal heartbeat_ticks
            while not stop_heartbeat.is_set():
                heartbeat_ticks += 1
                await asyncio.sleep(0)

        heartbeat_task = asyncio.create_task(heartbeat())
        rejected = [enqueue(sequence) for sequence in range(5, 105)]
        overload_tasks = list(manager._redis_overload_tasks.values())
        await asyncio.sleep(0.01)

        assert rejected == [False] * 100
        assert len(overload_tasks) == 1
        assert heartbeat_ticks > 0

        await asyncio.gather(*overload_tasks)
        assert manager._redis_pending_items == 0
        assert 10 not in manager._redis_company_queues
        assert 10 not in manager._redis_company_overflows
        assert 10 not in manager._redis_company_inflight
        assert websocket.closed == [(1013, "redis_backpressure")]
        assert 10 not in manager.connections
        # The in-flight item keeps its claim because delivery may already have
        # happened; queued, never-started items release theirs for recovery.
        assert manager.claim_event_for_local_delivery(
            channel,
            {"event_id": "bounded-overflow:1"},
        ) is False
        for sequence in range(2, 5):
            purged_payload = {"event_id": f"bounded-overflow:{sequence}"}
            assert manager.claim_event_for_local_delivery(
                channel,
                purged_payload,
            ) is True
            manager.release_event_delivery_claim(channel, purged_payload)

        # A rejected event does not retain its dedupe claim, so another local
        # recovery path remains free to own it.
        rejected_payload = {
            "event_id": "bounded-overflow:104",
        }
        assert manager.claim_event_for_local_delivery(
            channel,
            rejected_payload,
        ) is True
        manager.release_event_delivery_claim(channel, rejected_payload)
        assert len(manager._recent_event_ids) <= 4

        assert dispatch_task.cancelled() is True
        stop_heartbeat.set()
        await heartbeat_task

    asyncio.run(scenario())


def test_global_dispatch_caps_reject_new_company_without_retaining_claim():
    async def scenario():
        manager = ConnectionManager()
        manager.redis_global_queue_maxsize = 1
        manager._redis_pending_items = 1
        channel = manager._websocket_channel("chat_messages:99")
        payload = {"event_id": "global-cap:1"}

        retained = manager._claim_and_enqueue_redis_item(
            channel,
            payload,
            _RedisDispatchItem(
                company_id=99,
                channel=channel,
                steps=[("contact", payload)],
            ),
        )
        overload_tasks = list(manager._redis_overload_tasks.values())

        assert retained is False
        assert len(overload_tasks) == 1
        assert manager.claim_event_for_local_delivery(channel, payload) is True
        manager.release_event_delivery_claim(channel, payload)
        await asyncio.gather(*overload_tasks)
        assert 99 not in manager._redis_company_queues
        assert 99 not in manager._redis_overloaded_companies

    asyncio.run(scenario())


def test_busy_local_requeue_releases_claim_when_cap_is_full():
    async def scenario():
        manager = ConnectionManager()
        manager.redis_company_queue_maxsize = 1
        manager.redis_company_overflow_maxsize = 0
        websocket = _FakeWebSocket()
        await manager.connect(
            websocket,
            client_id="6",
            company_id=10,
            phone="contact",
            send_confirmation=False,
        )

        queue = asyncio.Queue(maxsize=1)
        queue.put_nowait(object())
        manager._redis_company_queues[10] = queue
        channel = manager._websocket_channel("chat_messages:10")
        payload = {"event_id": "local-busy:full"}
        assert manager.claim_event_for_local_delivery(channel, payload) is True

        manager._enqueue_busy_local_broadcast(
            10,
            "contact",
            payload,
            channel,
        )
        overload_tasks = list(manager._redis_overload_tasks.values())
        assert manager.claim_event_for_local_delivery(channel, payload) is True
        manager.release_event_delivery_claim(channel, payload)

        await asyncio.gather(*overload_tasks)
        assert websocket.closed == [(1013, "redis_backpressure")]

    asyncio.run(scenario())


def test_redis_listener_ignores_foreign_namespace_and_subscribes_scoped():
    async def scenario():
        manager = ConnectionManager()
        valid_channel = manager._websocket_channel("chat_messages:10")
        foreign_channel = "agentive:staging:chat_messages:10"
        payload = {
            "event_id": "namespace:1",
            "phone": "contact",
            "content": "hello",
        }

        class FakePubSub:
            def __init__(self):
                self.patterns = []
                self.closed = False

            async def psubscribe(self, pattern):
                self.patterns.append(pattern)

            async def listen(self):
                for channel in (foreign_channel, valid_channel):
                    yield {
                        "type": "pmessage",
                        "channel": channel.encode("utf-8"),
                        "data": json.dumps(payload),
                    }
                raise asyncio.CancelledError

            async def aclose(self):
                self.closed = True

        pubsub = FakePubSub()
        manager.redis = SimpleNamespace(pubsub=lambda: pubsub)
        captured = []
        manager._claim_and_enqueue_redis_item = (
            lambda channel, data, item: captured.append(
                (channel, data, item)
            )
            or True
        )

        with suppress(asyncio.CancelledError):
            await manager._listen_to_redis()

        assert [entry[0] for entry in captured] == [valid_channel]
        assert all(
            pattern.startswith(f"{manager.websocket_channel_namespace}:")
            for pattern in pubsub.patterns
        )
        assert pubsub.closed is True

    asyncio.run(scenario())


def test_fence_session_open_validate_rollback_and_close_share_one_thread():
    async def scenario():
        manager = ConnectionManager()
        websocket = _FakeWebSocket()
        await manager.connect(
            websocket,
            client_id="6",
            company_id=10,
            phone="contact",
            send_confirmation=False,
            access_epoch=7,
        )
        thread_ids = {}

        class ThreadAffineFence:
            def rollback(self):
                thread_ids["rollback"] = threading.get_ident()

            def close(self):
                thread_ids["close"] = threading.get_ident()

        def open_fence(_company_id, _connections=()):
            thread_ids["open"] = threading.get_ident()
            return ThreadAffineFence(), 7

        manager._open_company_access_fence = open_fence
        result = await manager.broadcast_to_phone(
            10,
            "contact",
            {"event_id": "thread-affinity:1"},
        )

        assert result == BROADCAST_DELIVERED
        assert websocket.sent == [{"event_id": "thread-affinity:1"}]
        assert thread_ids["open"] == thread_ids["rollback"] == thread_ids["close"]
        assert thread_ids["open"] != threading.get_ident()
        assert manager._active_fence_handles == set()

    asyncio.run(scenario())


def test_stop_releases_active_same_thread_fence_and_does_not_hang():
    async def scenario():
        manager = ConnectionManager()
        websocket = _BlockingWebSocket()
        await manager.connect(
            websocket,
            client_id="6",
            company_id=10,
            phone="contact",
            send_confirmation=False,
            access_epoch=3,
        )
        thread_ids = {}

        class ThreadAffineFence:
            def rollback(self):
                thread_ids["rollback"] = threading.get_ident()

            def close(self):
                thread_ids["close"] = threading.get_ident()

        def open_fence(_company_id, _connections=()):
            thread_ids["open"] = threading.get_ident()
            return ThreadAffineFence(), 3

        manager._open_company_access_fence = open_fence
        broadcast_task = asyncio.create_task(
            manager.broadcast_to_phone(
                10,
                "contact",
                {"event_id": "shutdown-fence:1"},
            )
        )
        await asyncio.wait_for(websocket.send_started.wait(), timeout=0.2)
        assert manager._active_fence_handles

        await asyncio.wait_for(manager.stop(), timeout=0.5)
        await asyncio.wait_for(manager.stop(), timeout=0.1)

        assert thread_ids["open"] == thread_ids["rollback"] == thread_ids["close"]
        assert manager._active_fence_handles == set()
        assert websocket.closed == [(1012, "service_restart")]
        assert manager._stopped is True

        broadcast_task.cancel()
        with suppress(asyncio.CancelledError):
            await broadcast_task

    asyncio.run(scenario())


def test_auth_holder_pool_saturation_is_cancel_safe_and_loop_keeps_ticking():
    async def scenario():
        manager = ConnectionManager()
        sockets = []
        fences = {}
        for company_id in range(1, WEBSOCKET_AUTH_EXECUTOR_WORKERS + 2):
            websocket = _BlockingWebSocket()
            sockets.append(websocket)
            await manager.connect(
                websocket,
                client_id=str(company_id),
                company_id=company_id,
                phone="contact",
                send_confirmation=False,
                access_epoch=1,
            )

        def open_fence(company_id, _connections=()):
            fence = _FenceDB()
            fences[int(company_id)] = fence
            return fence, 1

        manager._open_company_access_fence = open_fence
        broadcasts = [
            asyncio.create_task(
                manager.broadcast_to_phone(
                    company_id,
                    "contact",
                    {"event_id": f"holder-saturation:{company_id}"},
                )
            )
            for company_id in range(1, WEBSOCKET_AUTH_EXECUTOR_WORKERS + 2)
        ]

        for websocket in sockets[:WEBSOCKET_AUTH_EXECUTOR_WORKERS]:
            await asyncio.wait_for(websocket.send_started.wait(), timeout=0.3)

        heartbeat_ticks = 0
        stop_heartbeat = asyncio.Event()

        async def heartbeat():
            nonlocal heartbeat_ticks
            while not stop_heartbeat.is_set():
                heartbeat_ticks += 1
                await asyncio.sleep(0.001)

        heartbeat_task = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.03)
        assert sockets[-1].send_started.is_set() is False
        assert heartbeat_ticks >= 15

        broadcasts[0].cancel()
        with suppress(asyncio.CancelledError):
            await broadcasts[0]
        await asyncio.wait_for(sockets[-1].send_started.wait(), timeout=0.3)

        for task in broadcasts[1:]:
            task.cancel()
        await asyncio.gather(*broadcasts[1:], return_exceptions=True)
        stop_heartbeat.set()
        await heartbeat_task
        for _ in range(100):
            if not manager._active_fence_handles:
                break
            await asyncio.sleep(0.001)

        assert manager._active_fence_handles == set()
        assert all(
            fence.rolled_back and fence.is_closed
            for fence in fences.values()
        )

    asyncio.run(scenario())
