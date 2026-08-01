"""Shared Redis transport contract for cross-process WebSocket events.

Redis Pub/Sub ignores logical database numbers.  Every publisher and consumer
must therefore use the same explicit application/environment namespace.
"""

from __future__ import annotations

import os
import re
from typing import Optional


DEFAULT_WEBSOCKET_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_WEBSOCKET_APPLICATION_NAMESPACE = "agentive"
_NAMESPACE_PART_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")


def websocket_redis_url() -> str:
    return os.getenv(
        "WEBSOCKET_REDIS_URL",
        DEFAULT_WEBSOCKET_REDIS_URL,
    ).strip() or DEFAULT_WEBSOCKET_REDIS_URL


def _safe_environment_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower())
    normalized = normalized.strip("-._")[:63]
    return normalized or "development"


def _validate_namespace(namespace: str) -> str:
    normalized = namespace.strip().lower()
    parts = normalized.split(":")
    if not parts or any(not _NAMESPACE_PART_RE.fullmatch(part) for part in parts):
        raise RuntimeError("invalid_websocket_channel_namespace")
    return normalized


def websocket_channel_namespace() -> str:
    """Return an explicit namespace or a safe app/environment default."""
    configured = os.getenv("WEBSOCKET_CHANNEL_NAMESPACE", "").strip()
    if configured:
        return _validate_namespace(configured)
    environment = _safe_environment_name(
        os.getenv("ENVIRONMENT", "development")
    )
    return f"{DEFAULT_WEBSOCKET_APPLICATION_NAMESPACE}:{environment}"


def websocket_channel(
    logical_channel: str,
    *,
    namespace: Optional[str] = None,
) -> str:
    logical = str(logical_channel).strip()
    if not logical or logical.startswith(":"):
        raise ValueError("invalid_websocket_logical_channel")
    resolved_namespace = _validate_namespace(
        namespace or websocket_channel_namespace()
    )
    return f"{resolved_namespace}:{logical}"


def strip_websocket_channel_namespace(
    published_channel: str,
    *,
    namespace: Optional[str] = None,
) -> Optional[str]:
    """Return the logical channel, or None for another environment/app."""
    resolved_namespace = _validate_namespace(
        namespace or websocket_channel_namespace()
    )
    prefix = f"{resolved_namespace}:"
    channel = str(published_channel)
    if not channel.startswith(prefix):
        return None
    logical = channel[len(prefix):]
    return logical or None
