from __future__ import annotations

from collections.abc import Callable
from typing import Any


def build_database_health_payload(
    stats: dict[str, Any],
    *,
    database_reachable: bool,
    timestamp: float,
) -> dict[str, Any]:
    """Build the database health response without performing I/O."""
    total_capacity = max(int(stats.get("total_capacity", 0)), 1)
    checked_out = int(stats.get("checked_out", 0))
    usage_percent = (checked_out / total_capacity) * 100

    if not database_reachable or usage_percent >= 90:
        status = "critical"
    elif usage_percent >= 70:
        status = "warning"
    else:
        status = "healthy"

    return {
        "status": status,
        "database_reachable": database_reachable,
        "usage_percent": round(usage_percent, 2),
        "connections": stats,
        "timestamp": timestamp,
    }


def probe_database_health(
    stats: dict[str, Any],
    *,
    check_connection: Callable[[], None],
    timestamp: float,
) -> tuple[dict[str, Any], str | None]:
    """Run the real database probe and return a safe error type when it fails."""
    try:
        check_connection()
    except Exception as exc:
        return (
            build_database_health_payload(
                stats,
                database_reachable=False,
                timestamp=timestamp,
            ),
            type(exc).__name__,
        )

    return (
        build_database_health_payload(
            stats,
            database_reachable=True,
            timestamp=timestamp,
        ),
        None,
    )
