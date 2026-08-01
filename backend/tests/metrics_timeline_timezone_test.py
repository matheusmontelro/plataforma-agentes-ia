from datetime import datetime, timezone

import pytest

from backend.routes.metrics_funnels import (
    _normalize_timeline_datetime,
    _resolve_timeline_timezone,
    _timeline_date_bounds,
    get_timeline,
)


@pytest.mark.parametrize(
    ("timezone_name", "date_value", "expected_start", "expected_end"),
    [
        ("America/Sao_Paulo", "2026-07-10", "2026-07-10T03:00:00+00:00", "2026-07-11T03:00:00+00:00"),
        ("America/New_York", "2026-03-08", "2026-03-08T05:00:00+00:00", "2026-03-09T04:00:00+00:00"),
        ("Europe/Lisbon", "2026-03-29", "2026-03-29T00:00:00+00:00", "2026-03-29T23:00:00+00:00"),
    ],
)
def test_timeline_date_bounds_follow_browser_calendar_days(
    timezone_name: str,
    date_value: str,
    expected_start: str,
    expected_end: str,
) -> None:
    start, end = _timeline_date_bounds(date_value, date_value, timezone_name)

    assert start is not None and start.isoformat() == expected_start
    assert end is not None and end.isoformat() == expected_end


def test_timeline_timezone_falls_back_to_utc() -> None:
    assert _resolve_timeline_timezone("timezone/inexistente") is timezone.utc


def test_timeline_normalizes_naive_and_aware_timestamps_to_utc() -> None:
    naive = datetime(2026, 7, 10, 12, 30)
    aware = datetime.fromisoformat("2026-07-10T09:30:00-03:00")

    assert _normalize_timeline_datetime(naive).isoformat() == "2026-07-10T12:30:00+00:00"
    assert _normalize_timeline_datetime(aware).isoformat() == "2026-07-10T12:30:00+00:00"


class RecordingQuery:
    def __init__(self, columns, row):
        self.columns = columns
        self.row = row
        self.operations: list[str] = []

    def filter(self, *_args):
        self.operations.append("filter")
        return self

    def order_by(self, *_args):
        self.operations.append("order_by")
        return self

    def limit(self, _value):
        self.operations.append("limit")
        return self

    def all(self):
        self.operations.append("all")
        return [self.row]


class RecordingSession:
    def __init__(self):
        self.rows = iter(
            [
                (1, datetime.fromisoformat("2026-07-10T10:00:00+00:00"), "Lead"),
                (2, datetime(2026, 7, 10, 12, 0), "Agendamento"),
                (3, datetime.fromisoformat("2026-07-10T11:00:00-03:00"), "Comparecimento"),
                (4, datetime.fromisoformat("2026-07-10T09:00:00+00:00"), "Ausência"),
                (5, datetime.fromisoformat("2026-07-10T13:00:00+00:00"), "Venda"),
            ]
        )
        self.queries: list[RecordingQuery] = []

    def query(self, *columns):
        query = RecordingQuery(columns, next(self.rows))
        self.queries.append(query)
        return query


def test_timeline_orders_each_source_before_limit_and_then_orders_globally() -> None:
    db = RecordingSession()

    result = get_timeline(limit=2, db=db)

    assert str(db.queries[0].columns[1]).startswith("CAST(leads.created_at AS DATETIME")
    assert all(query.operations == ["order_by", "limit", "all"] for query in db.queries)
    assert [event["event_type"] for event in result] == ["comparecimento", "venda"]
    assert [event["event_date"] for event in result] == [
        "2026-07-10T14:00:00Z",
        "2026-07-10T13:00:00Z",
    ]
