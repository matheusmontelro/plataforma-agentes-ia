from backend.health_checks import build_database_health_payload, probe_database_health


def _stats(*, checked_out: int, total_capacity: int = 100) -> dict[str, int]:
    return {
        "pool_size": 50,
        "checked_out": checked_out,
        "overflow": 0,
        "checked_in": 50,
        "max_overflow": 50,
        "total_capacity": total_capacity,
    }


def test_database_health_is_critical_when_query_fails() -> None:
    payload = build_database_health_payload(
        _stats(checked_out=1),
        database_reachable=False,
        timestamp=123.0,
    )

    assert payload["status"] == "critical"
    assert payload["database_reachable"] is False
    assert payload["timestamp"] == 123.0


def test_database_health_preserves_pool_pressure_statuses() -> None:
    warning = build_database_health_payload(
        _stats(checked_out=75),
        database_reachable=True,
        timestamp=123.0,
    )
    critical = build_database_health_payload(
        _stats(checked_out=95),
        database_reachable=True,
        timestamp=123.0,
    )

    assert warning["status"] == "warning"
    assert warning["usage_percent"] == 75.0
    assert critical["status"] == "critical"


def test_database_health_handles_zero_capacity_defensively() -> None:
    payload = build_database_health_payload(
        _stats(checked_out=0, total_capacity=0),
        database_reachable=True,
        timestamp=123.0,
    )

    assert payload["status"] == "healthy"
    assert payload["usage_percent"] == 0.0


def test_database_probe_returns_safe_critical_result_on_query_error() -> None:
    def fail_query() -> None:
        raise RuntimeError("sensitive database details")

    payload, error_type = probe_database_health(
        _stats(checked_out=1),
        check_connection=fail_query,
        timestamp=123.0,
    )

    assert payload["status"] == "critical"
    assert payload["database_reachable"] is False
    assert error_type == "RuntimeError"
    assert "sensitive" not in str(payload)


def test_database_probe_marks_successful_real_query_as_reachable() -> None:
    calls: list[bool] = []

    payload, error_type = probe_database_health(
        _stats(checked_out=1),
        check_connection=lambda: calls.append(True),
        timestamp=123.0,
    )

    assert calls == [True]
    assert payload["status"] == "healthy"
    assert payload["database_reachable"] is True
    assert error_type is None
