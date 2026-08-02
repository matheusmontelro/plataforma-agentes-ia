import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ENVIRONMENT", "development")

from backend.services import company_access_control as access_control


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class FakeLockConnection:
    def __init__(self, *, try_lock_result, statements):
        self.try_lock_result = try_lock_result
        self.statements = statements

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, statement, params):
        sql = str(statement)
        self.statements.append((sql, dict(params)))
        if "pg_try_advisory_lock" in sql:
            return FakeResult(self.try_lock_result)
        if "pg_advisory_unlock" in sql:
            return FakeResult(True)
        raise AssertionError(f"SQL inesperado: {sql}")


class FakePostgresBind:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, *, try_lock_results=None):
        self.try_lock_results = list(try_lock_results or [True])
        self.connect_calls = 0
        self.statements = []

    def connect(self):
        self.connect_calls += 1
        result = self.try_lock_results.pop(0)
        return FakeLockConnection(
            try_lock_result=result,
            statements=self.statements,
        )


class FakePostgresDB:
    def __init__(self, bind):
        self.bind = bind

    def get_bind(self):
        return self.bind


def _install_guard(monkeypatch, capacity_limit):
    guard = access_control._IdentityOperationGuard(capacity_limit)
    monkeypatch.setattr(
        access_control,
        "_IDENTITY_OPERATION_GUARD",
        guard,
    )
    return guard


def test_same_email_contention_fails_before_another_pool_checkout(monkeypatch):
    guard = _install_guard(monkeypatch, capacity_limit=2)
    bind = FakePostgresBind(try_lock_results=[True])
    db = FakePostgresDB(bind)

    with access_control.account_identity_operation_lock(
        db,
        "Owner@Example.com",
    ):
        with pytest.raises(
            access_control.IdentityOperationBusyError
        ) as exc:
            with access_control.account_identity_operation_lock(
                db,
                " owner@example.com ",
            ):
                raise AssertionError("same email must not enter twice")

        assert exc.value.reason == "local_identity"
        assert bind.connect_calls == 1
        assert guard.capacity_in_use == 1

    assert guard.capacity_in_use == 0
    assert guard.local_lock_count == 0


def test_capacity_reserves_headroom_and_rejects_before_pool_checkout(monkeypatch):
    capacity = access_control._calculate_identity_operation_capacity(
        pool_capacity=7,
        pool_headroom=3,
        configured_max=10,
        connections_per_operation=2,
    )
    assert capacity == 2

    guard = _install_guard(monkeypatch, capacity_limit=capacity)
    bind = FakePostgresBind(try_lock_results=[True, True])
    db = FakePostgresDB(bind)

    with access_control.account_identity_operation_lock(db, "first@example.com"):
        with access_control.account_identity_operation_lock(
            db,
            "second@example.com",
        ):
            with pytest.raises(
                access_control.IdentityOperationBusyError
            ) as exc:
                with access_control.account_identity_operation_lock(
                    db,
                    "third@example.com",
                ):
                    raise AssertionError("capacity overflow must not enter")

            assert exc.value.reason == "capacity"
            assert bind.connect_calls == 2
            assert guard.capacity_in_use == 2

    assert guard.capacity_in_use == 0
    assert guard.local_lock_count == 0


def test_external_advisory_lock_contention_is_fail_fast(monkeypatch):
    guard = _install_guard(monkeypatch, capacity_limit=1)
    bind = FakePostgresBind(try_lock_results=[False])
    db = FakePostgresDB(bind)

    with pytest.raises(access_control.IdentityOperationBusyError) as exc:
        with access_control.account_identity_operation_lock(
            db,
            "owner@example.com",
        ):
            raise AssertionError("external lock contention must not enter")

    assert exc.value.reason == "external_identity"
    assert bind.connect_calls == 1
    assert len(bind.statements) == 1
    assert "pg_try_advisory_lock" in bind.statements[0][0]
    assert "pg_advisory_unlock" not in bind.statements[0][0]
    assert guard.capacity_in_use == 0
    assert guard.local_lock_count == 0
