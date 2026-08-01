"""Regression tests for DB-off-loop WebSocket authentication."""

from __future__ import annotations

import ast
import asyncio
import inspect
import os
import textwrap
import threading
import time
import logging
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import anyio
import pytest
from fastapi import WebSocketDisconnect
from starlette.concurrency import run_in_threadpool as shared_run_in_threadpool


os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-with-at-least-32-chars")

from backend import auth
from backend.routes import chat_optimized, chat_ws


def _principal(*, operational_epoch=None) -> auth.WebSocketAccessSnapshot:
    return auth.WebSocketAccessSnapshot(
        user_id="7",
        client_id="9",
        company_id="3",
        user_type="user",
        auth_token_version=4,
        operational_epoch=operational_epoch,
    )


def test_fresh_ws_helpers_keep_session_inside_one_dedicated_worker(monkeypatch):
    async def scenario():
        event_loop_thread = threading.get_ident()
        sessions = []
        heartbeat_ticks = 0
        stop_heartbeat = asyncio.Event()

        class FakeSession:
            def __init__(self):
                self.owner_thread = threading.get_ident()
                self.events = [("created", self.owner_thread)]
                self.info = {}
                sessions.append(self)

            def record(self, name):
                current_thread = threading.get_ident()
                assert current_thread == self.owner_thread
                self.events.append((name, current_thread))

            def rollback(self):
                self.record("rollback")

            def close(self):
                self.record("close")

        def mark_session(db):
            db.record("marked")
            db.info["agentive_web_request"] = True
            return db

        def authenticate_core(token, db):
            assert token == "token"
            db.record("authenticate")
            time.sleep(0.04)
            return {
                "id": "7",
                "client_id": "9",
                "company_id": "3",
                "user_type": "user",
                "auth_token_version": 4,
            }

        def verify_core(user_id, company_id, db):
            assert (str(user_id), int(company_id)) == ("7", 3)
            db.record("verify_company")
            return True

        def revalidate_core(token, company_id, db, **kwargs):
            assert token == "token"
            assert int(company_id) == 3
            assert kwargs == {
                "expected_user_id": "7",
                "expected_client_id": "9",
            }
            db.record("revalidate")
            time.sleep(0.04)
            return {
                "id": "7",
                "client_id": "9",
                "company_id": "3",
                "user_type": "user",
                "auth_token_version": 4,
                "operational_epoch": 11,
            }

        def resource_validator(db, user):
            assert user["id"] == "7"
            db.record("resource")
            return True

        async def heartbeat():
            nonlocal heartbeat_ticks
            while not stop_heartbeat.is_set():
                heartbeat_ticks += 1
                await asyncio.sleep(0.001)

        monkeypatch.setattr(auth, "SessionLocal", FakeSession)
        monkeypatch.setattr(auth, "mark_session_as_web_request", mark_session)
        monkeypatch.setattr(auth, "get_current_user_ws_sync", authenticate_core)
        monkeypatch.setattr(auth, "verify_company_access_sync", verify_core)
        monkeypatch.setattr(auth, "revalidate_websocket_access_sync", revalidate_core)

        heartbeat_task = asyncio.create_task(heartbeat())
        first = await auth.authenticate_websocket_access_off_loop(
            "token",
            3,
            resource_validator=resource_validator,
        )
        second = await auth.revalidate_websocket_access_off_loop(
            "token",
            3,
            expected_user_id="7",
            expected_client_id="9",
            resource_validator=resource_validator,
        )
        stop_heartbeat.set()
        await heartbeat_task

        assert first == _principal()
        assert second == _principal(operational_epoch=11)
        assert len(sessions) == 2
        assert sessions[0] is not sessions[1]
        assert all(session.owner_thread != event_loop_thread for session in sessions)
        assert [name for name, _ in sessions[0].events] == [
            "created",
            "marked",
            "authenticate",
            "verify_company",
            "resource",
            "rollback",
            "close",
        ]
        assert [name for name, _ in sessions[1].events] == [
            "created",
            "marked",
            "revalidate",
            "resource",
            "rollback",
            "close",
        ]
        assert heartbeat_ticks >= 20
        with pytest.raises(FrozenInstanceError):
            first.user_id = "changed"

    asyncio.run(scenario())


def test_generic_websocket_auth_failures_do_not_expose_database_details(
    monkeypatch,
    caplog,
):
    secret_detail = "database failure contained secret credentials and SQL params"

    class FailingQuery:
        def filter_by(self, **kwargs):
            return self

        def first(self):
            raise RuntimeError(secret_detail)

    class FailingSession:
        def query(self, entity):
            return FailingQuery()

        def execute(self, *args, **kwargs):
            raise RuntimeError(secret_detail)

    monkeypatch.setattr(
        auth,
        "decode_token",
        lambda token: {
            "sub": "user@example.com",
            "user_type": "master",
            "user_id": "7",
            "client_id": "7",
            "company_id": "3",
        },
    )

    with caplog.at_level(logging.ERROR), pytest.raises(auth.WebSocketAuthError) as exc_info:
        auth.get_current_user_ws_sync("token", FailingSession())

    assert exc_info.value.message == "Falha ao autenticar"
    assert secret_detail not in caplog.text
    assert auth.verify_company_access_sync("7", 3, FailingSession()) is False
    assert secret_detail not in caplog.text


def test_dedicated_ws_executor_does_not_starve_shared_login_pool():
    async def exercise_dedicated_executor(runner, worker_count):
        release_workers = threading.Event()
        workers_started = 0
        workers_guard = threading.Lock()

        def blocker():
            nonlocal workers_started
            with workers_guard:
                workers_started += 1
            release_workers.wait(timeout=2)

        blockers = [
            asyncio.create_task(runner(blocker))
            for _ in range(worker_count)
        ]
        try:
            for _ in range(500):
                with workers_guard:
                    if workers_started == worker_count:
                        break
                await asyncio.sleep(0.001)
            assert workers_started == worker_count
            login_result = await asyncio.wait_for(
                shared_run_in_threadpool(lambda: "login-ok"),
                timeout=0.25,
            )
            assert login_result == "login-ok"
        finally:
            release_workers.set()
            await asyncio.gather(*blockers)

    async def scenario():
        limiter = anyio.to_thread.current_default_thread_limiter()
        original_tokens = limiter.total_tokens
        limiter.total_tokens = 1
        try:
            await exercise_dedicated_executor(
                auth._run_websocket_auth_executor,
                auth.WEBSOCKET_AUTH_EXECUTOR_WORKERS,
            )
        finally:
            limiter.total_tokens = original_tokens

    asyncio.run(scenario())


def test_websocket_auth_executor_rejects_overload_until_running_work_finishes():
    async def scenario():
        release_workers = threading.Event()
        workers_started = 0
        workers_guard = threading.Lock()

        def blocker():
            nonlocal workers_started
            with workers_guard:
                workers_started += 1
            release_workers.wait(timeout=2)

        blockers = [
            asyncio.create_task(auth._run_websocket_auth_executor(blocker))
            for _ in range(auth.WEBSOCKET_AUTH_EXECUTOR_WORKERS)
        ]
        try:
            for _ in range(500):
                with workers_guard:
                    if workers_started == auth.WEBSOCKET_AUTH_EXECUTOR_WORKERS:
                        break
                await asyncio.sleep(0.001)
            assert workers_started == auth.WEBSOCKET_AUTH_EXECUTOR_WORKERS

            blockers[0].cancel()
            with pytest.raises(asyncio.CancelledError):
                await blockers[0]

            with pytest.raises(auth.WebSocketAuthError) as exc_info:
                await auth._run_websocket_auth_executor(lambda: "queued")
            assert exc_info.value.code == 1013
            assert exc_info.value.message == "Serviço temporariamente ocupado"
        finally:
            release_workers.set()
            await asyncio.gather(*blockers, return_exceptions=True)

        assert await auth._run_websocket_auth_executor(lambda: "available") == "available"

    asyncio.run(scenario())


class _FakeWebSocket:
    def __init__(self):
        self.cookies = {}
        self.client_state = SimpleNamespace(name="CONNECTED")
        self.application_state = SimpleNamespace(name="CONNECTED")
        self.accepted = False
        self.sent = []
        self.closed = []
        self.receive_count = 0

    async def accept(self):
        self.accepted = True

    async def receive_json(self):
        self.receive_count += 1
        if self.receive_count == 1:
            return {"type": "ping"}
        raise WebSocketDisconnect(code=1000)

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self, code=1000, reason=None):
        self.closed.append((code, reason))


class _FakeManager:
    def __init__(self):
        self.barrier_epochs = []
        self.connect_calls = []
        self.disconnect_calls = []

    async def connect_with_access_barrier(
        self,
        websocket,
        client_id,
        company_id,
        topics,
        access_check,
        **metadata,
    ):
        self.connect_calls.append((websocket.accepted, client_id, company_id, topics, metadata))
        epoch = await access_check()
        self.barrier_epochs.append(epoch)
        return epoch is not None

    async def disconnect(self, websocket, client_id, company_id, topic):
        self.disconnect_calls.append((client_id, company_id, topic))


@pytest.mark.parametrize(
    ("route_module", "endpoint_name", "endpoint_kwargs"),
    (
        (
            chat_ws,
            "chat_websocket_endpoint",
            {"company_id": 3, "phone": "5500000000007"},
        ),
        (
            chat_optimized,
            "unified_websocket_endpoint",
            {"company_id": 3, "topics": "5500000000007,__global__"},
        ),
    ),
)
def test_critical_websocket_routes_preserve_barrier_and_heartbeat(
    monkeypatch,
    route_module,
    endpoint_name,
    endpoint_kwargs,
):
    async def scenario():
        websocket = _FakeWebSocket()
        manager = _FakeManager()
        validators = []

        async def authenticate(token, company_id, **kwargs):
            assert token == "token"
            assert company_id == 3
            validators.append(kwargs.get("resource_validator"))
            return _principal()

        async def revalidate(token, company_id, **kwargs):
            assert token == "token"
            assert company_id == 3
            assert kwargs["expected_user_id"] == "7"
            assert kwargs["expected_client_id"] == "9"
            validators.append(kwargs.get("resource_validator"))
            return _principal(operational_epoch=12)

        monkeypatch.setattr(route_module, "manager", manager)
        monkeypatch.setattr(
            route_module,
            "authenticate_websocket_access_off_loop",
            authenticate,
        )
        monkeypatch.setattr(
            route_module,
            "revalidate_websocket_access_off_loop",
            revalidate,
        )

        endpoint = getattr(route_module, endpoint_name)
        await endpoint(websocket=websocket, token="token", **endpoint_kwargs)

        assert websocket.accepted is True
        assert manager.barrier_epochs == [12]
        assert any(message.get("type") == "pong" for message in websocket.sent)
        assert manager.connect_calls[0][0] is True
        assert validators == [None, None]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("route_module", "endpoint_name", "endpoint_kwargs"),
    (
        (
            chat_ws,
            "chat_websocket_endpoint",
            {"company_id": 3, "phone": "5500000000007"},
        ),
        (
            chat_optimized,
            "unified_websocket_endpoint",
            {"company_id": 3, "topics": "__global__"},
        ),
    ),
)
def test_critical_websocket_routes_sanitize_authentication_failures(
    monkeypatch,
    caplog,
    route_module,
    endpoint_name,
    endpoint_kwargs,
):
    secret_detail = "database failure contained secret credentials and SQL params"

    async def scenario():
        websocket = _FakeWebSocket()

        async def fail_authentication(*args, **kwargs):
            raise RuntimeError(secret_detail)

        monkeypatch.setattr(
            route_module,
            "authenticate_websocket_access_off_loop",
            fail_authentication,
        )

        endpoint = getattr(route_module, endpoint_name)
        await endpoint(websocket=websocket, token="token", **endpoint_kwargs)

        assert websocket.closed

    with caplog.at_level(logging.ERROR):
        asyncio.run(scenario())

    assert "RuntimeError" in caplog.text
    assert secret_detail not in caplog.text


@pytest.mark.parametrize(
    ("route_module", "endpoint_name", "endpoint_kwargs"),
    (
        (
            chat_ws,
            "chat_websocket_endpoint",
            {"company_id": 3, "phone": "5500000000007"},
        ),
        (
            chat_optimized,
            "unified_websocket_endpoint",
            {"company_id": 3, "topics": "__global__"},
        ),
    ),
)
def test_critical_websocket_routes_preserve_retryable_auth_close_code(
    monkeypatch,
    route_module,
    endpoint_name,
    endpoint_kwargs,
):
    async def scenario():
        websocket = _FakeWebSocket()

        async def reject_overload(*args, **kwargs):
            raise auth.WebSocketAuthError(
                "Serviço temporariamente ocupado",
                1013,
            )

        monkeypatch.setattr(
            route_module,
            "authenticate_websocket_access_off_loop",
            reject_overload,
        )

        endpoint = getattr(route_module, endpoint_name)
        await endpoint(websocket=websocket, token="token", **endpoint_kwargs)

        assert websocket.closed == [(1013, None)]

    asyncio.run(scenario())


def test_critical_websocket_coroutines_do_not_use_sync_db_sessions():
    violations = []

    class AsyncDbVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            # Synchronous validators nested in an endpoint run inside the
            # dedicated executor and are intentionally excluded.
            return

        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id in {
                "SessionLocal",
                "get_db",
            }:
                violations.append(node.func.id)
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "db"
                and node.func.attr
                in {"query", "execute", "rollback", "close", "expire", "expire_all"}
            ):
                violations.append(f"db.{node.func.attr}")
            self.generic_visit(node)

    for endpoint in (
        chat_ws.chat_websocket_endpoint,
        chat_optimized.unified_websocket_endpoint,
    ):
        tree = ast.parse(textwrap.dedent(inspect.getsource(endpoint)))
        AsyncDbVisitor().visit(tree)

    assert violations == []
