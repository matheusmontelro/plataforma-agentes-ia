from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from backend.agents_sdk.tools.whatsapp_scheduled_followup_tools import (
    create_whatsapp_scheduled_followup_tools,
    _parse_scheduled_for,
)


def test_parse_scheduled_followup_relative_tomorrow_uses_company_timezone():
    now = datetime(2026, 6, 1, 9, 10, tzinfo=ZoneInfo("America/Sao_Paulo"))

    result = _parse_scheduled_for(
        "amanhã às 09:20",
        "America/Sao_Paulo",
        now=now,
    )

    assert result["success"] is True
    assert result["scheduled_local"].isoformat() == "2026-06-02T09:20:00-03:00"
    assert result["scheduled_utc"].astimezone(timezone.utc).isoformat() == "2026-06-02T12:20:00+00:00"


def test_parse_scheduled_followup_requires_exact_time_for_relative_day():
    now = datetime(2026, 6, 1, 9, 10, tzinfo=ZoneInfo("America/Sao_Paulo"))

    result = _parse_scheduled_for(
        "amanhã",
        "America/Sao_Paulo",
        now=now,
    )

    assert result["success"] is False
    assert result["error"] == "scheduled_time_required"
    assert "horário exato" in result["message_for_agent"]


def test_parse_scheduled_followup_iso_keeps_local_timezone():
    result = _parse_scheduled_for(
        "2026-06-02 09:20",
        "America/Sao_Paulo",
        now=datetime(2026, 6, 1, 9, 10, tzinfo=ZoneInfo("America/Sao_Paulo")),
    )

    assert result["success"] is True
    assert result["scheduled_local"].isoformat() == "2026-06-02T09:20:00-03:00"


def test_scheduled_followup_tool_uses_configured_replace_default():
    tool = create_whatsapp_scheduled_followup_tools(
        company_id=1,
        default_replace_existing_pending=False,
    )[0]

    assert tool.params_json_schema["properties"]["replace_existing_pending"]["default"] is False
