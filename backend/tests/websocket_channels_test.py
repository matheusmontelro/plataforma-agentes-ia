from pathlib import Path

import pytest

from backend.events.websocket_channels import (
    strip_websocket_channel_namespace,
    websocket_channel,
    websocket_channel_namespace,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_namespace_is_explicit_or_safely_derived(monkeypatch):
    monkeypatch.delenv("WEBSOCKET_CHANNEL_NAMESPACE", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "Review / QA")
    assert websocket_channel_namespace() == "agentive:review-qa"
    assert websocket_channel("chat_messages:3") == (
        "agentive:review-qa:chat_messages:3"
    )

    monkeypatch.setenv("WEBSOCKET_CHANNEL_NAMESPACE", "Platform:Production")
    assert websocket_channel_namespace() == "platform:production"


def test_invalid_explicit_namespace_fails_closed(monkeypatch):
    monkeypatch.setenv("WEBSOCKET_CHANNEL_NAMESPACE", "shared channel*")
    with pytest.raises(RuntimeError, match="invalid_websocket_channel_namespace"):
        websocket_channel_namespace()


def test_foreign_namespace_is_not_decoded(monkeypatch):
    monkeypatch.setenv("WEBSOCKET_CHANNEL_NAMESPACE", "platform:production")
    assert strip_websocket_channel_namespace(
        "platform:production:chat_messages:3"
    ) == "chat_messages:3"
    assert strip_websocket_channel_namespace(
        "agentive:staging:chat_messages:3"
    ) is None


def test_all_websocket_publishers_use_shared_channel_helper():
    publisher_paths = [
        "backend/ws_manager.py",
        "backend/integrations/broadcast_redis.py",
        "backend/worker/tasks_pos_consulta.py",
        "backend/worker/tasks_reminders.py",
    ]
    logical_channel_tokens = (
        "chat_messages:",
        "company_global:",
        "task_notifications:",
        "task_reminder_",
        "access_revocations",
    )

    for relative_path in publisher_paths:
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "websocket_channel" in source
        for line in source.splitlines():
            if ".publish(" not in line:
                continue
            assert not any(token in line for token in logical_channel_tokens), (
                f"raw WebSocket Redis channel in {relative_path}: {line.strip()}"
            )


def test_celery_workers_dispose_inherited_sqlalchemy_pool():
    for celery_app_path in (REPO_ROOT / "backend/worker/celery_app.py",):
        celery_app_source = celery_app_path.read_text(encoding="utf-8")
        assert "worker_process_init.connect(" in celery_app_source
        assert "dispose_inherited_sqlalchemy_pool" in celery_app_source
