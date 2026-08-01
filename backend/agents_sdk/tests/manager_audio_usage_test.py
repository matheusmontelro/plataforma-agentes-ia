import os
from decimal import Decimal
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/agentive_test")

from backend.agents_sdk import manager
from backend.agents_sdk.voice.models import AudioResponse


def test_manager_records_successful_elevenlabs_usage(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        manager,
        "safe_record_tts_usage",
        lambda **kwargs: captured.update(kwargs),
    )
    db = SimpleNamespace()

    manager._record_generated_audio_usage(
        db=db,
        company_id=7,
        audio_response=AudioResponse(
            should_send_audio=True,
            provider_used="elevenlabs",
            model_used="eleven_flash_v2_5",
            characters_used=321,
            provider_usage_units=321,
            provider_request_id="request-123",
            trigger_detected="long_response",
        ),
        fallback_text="fallback",
        phone="5500000000007",
        conversation_group="group-7",
        trace_id="trace-7",
        workflow_name="support",
    )

    assert captured["db"] is db
    assert captured["company_id"] == 7
    assert captured["provider"] == "elevenlabs"
    assert captured["text_characters"] == 321
    assert captured["provider_usage_units"] == Decimal("321")
    assert captured["status"] == "success"
    assert captured["usage_metadata"]["workflow_name"] == "support"


def test_manager_does_not_record_when_audio_was_not_generated(monkeypatch):
    calls = []
    monkeypatch.setattr(
        manager,
        "safe_record_tts_usage",
        lambda **kwargs: calls.append(kwargs),
    )

    manager._record_generated_audio_usage(
        db=SimpleNamespace(),
        company_id=8,
        audio_response=AudioResponse(should_send_audio=False),
        fallback_text="somente texto",
        phone=None,
        conversation_group=None,
        trace_id=None,
        workflow_name=None,
    )

    assert calls == []
