from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend import auth


class FakeQuery:
    def __init__(self, result):
        self.result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.result

    def scalar(self):
        return "active"


class FakeDB:
    def __init__(self, link=None):
        self.link = link
        self.flushed = 0

    def query(self, model):
        return FakeQuery(self.link)

    def flush(self):
        self.flushed += 1


def test_managed_workspace_trial_state_reports_progress_and_remaining_days():
    started_at = datetime(2026, 5, 1, 12, tzinfo=timezone.utc)
    ends_at = started_at + timedelta(days=7)
    now = started_at + timedelta(days=2, hours=12)
    link = SimpleNamespace(
        trial_days=7,
        trial_started_at=started_at,
        trial_ends_at=ends_at,
        lifecycle_status="trialing",
    )

    state = auth.get_managed_workspace_trial_state(link, now=now)

    assert state["lifecycle_status"] == "trialing"
    assert state["trial_days_remaining"] == 5
    assert state["trial_progress_percent"] == 35.71
    assert state["is_trial_expired"] is False


def test_managed_workspace_trial_state_marks_expired_by_date():
    started_at = datetime(2026, 5, 1, tzinfo=timezone.utc)
    ends_at = started_at + timedelta(days=3)
    link = SimpleNamespace(
        trial_days=3,
        trial_started_at=started_at,
        trial_ends_at=ends_at,
        lifecycle_status="trialing",
    )

    state = auth.get_managed_workspace_trial_state(link, now=ends_at + timedelta(seconds=1))

    assert state["lifecycle_status"] == "expired"
    assert state["trial_days_remaining"] == 0
    assert state["trial_progress_percent"] == 100.0
    assert state["is_trial_expired"] is True


def test_refresh_managed_workspace_lifecycle_persists_expired_status():
    started_at = datetime(2026, 5, 1, tzinfo=timezone.utc)
    link = SimpleNamespace(
        trial_days=3,
        trial_started_at=started_at,
        trial_ends_at=started_at + timedelta(days=3),
        lifecycle_status="trialing",
    )
    db = FakeDB()

    changed = auth.refresh_managed_workspace_lifecycle(
        db,
        link,
        now=started_at + timedelta(days=4),
    )

    assert changed is True
    assert link.lifecycle_status == "expired"
    assert db.flushed == 1


def test_ensure_managed_workspace_access_blocks_expired_trial():
    started_at = datetime.now(timezone.utc) - timedelta(days=10)
    link = SimpleNamespace(
        trial_days=7,
        trial_started_at=started_at,
        trial_ends_at=started_at + timedelta(days=7),
        lifecycle_status="trialing",
    )

    with pytest.raises(HTTPException) as exc_info:
        auth.ensure_managed_workspace_access(FakeDB(link), company_id=123)

    assert exc_info.value.status_code == 403
    assert "período de teste acabou" in str(exc_info.value.detail)
