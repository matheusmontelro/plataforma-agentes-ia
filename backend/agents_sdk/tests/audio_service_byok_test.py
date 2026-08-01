import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/agentive_test")

import openai

from backend.agents_sdk.voice import audio_service as module
from backend.agents_sdk.voice.models import AudioRequest


def _service():
    service = object.__new__(module.AudioService)
    service.db = "db"
    service.company_id = 7
    service.voice_config = SimpleNamespace(
        max_text_length=500,
        default_voice="nova",
        speed=1.0,
        model="gpt-4o-mini-tts",
        provider="elevenlabs",
    )
    return service


def test_openai_tts_uses_company_credential(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        module,
        "get_company_openai_api_key",
        lambda db, company_id: "company-seven-key"
        if db == "db" and company_id == 7
        else "",
    )

    async def fake_voice(*_args, **_kwargs):
        return "nova"

    monkeypatch.setattr(module, "get_assistant_voice_from_db", fake_voice)

    class _Speech:
        async def create(self, **kwargs):
            captured["request"] = kwargs
            return SimpleNamespace(content=b"mp3-content")

    class _AsyncOpenAI:
        def __init__(self, *, api_key):
            captured["api_key"] = api_key
            self.audio = SimpleNamespace(speech=_Speech())

    monkeypatch.setattr(openai, "AsyncOpenAI", _AsyncOpenAI)
    request = SimpleNamespace(
        text="Olá por áudio",
        voice_override=None,
        speed_override=None,
    )

    generated = asyncio.run(
        _service()._generate_audio_openai(request, "audio_requested")
    )

    assert generated is not None
    assert generated.audio_data == b"mp3-content"
    assert captured["api_key"] == "company-seven-key"
    assert captured["request"]["input"] == "Olá por áudio"


def test_elevenlabs_generation_stops_when_legacy_balance_is_empty(monkeypatch):
    service = _service()
    called = False
    monkeypatch.setattr(
        module,
        "get_ai_credit_balance",
        lambda db, company_id: 0 if db == "db" and company_id == 7 else 1,
    )

    async def fake_generate(*_args, **_kwargs):
        nonlocal called
        called = True
        return SimpleNamespace(audio_data=b"should-not-run")

    service._generate_audio_elevenlabs = fake_generate
    request = SimpleNamespace(provider_override=None)

    generated = asyncio.run(
        service._generate_audio(request, "audio_requested")
    )

    assert generated is None
    assert called is False


def test_forced_audio_cannot_bypass_disabled_voice():
    service = _service()
    service.voice_config.voice_enabled = False
    generated = False

    async def unexpected_generation(*_args, **_kwargs):
        nonlocal generated
        generated = True
        return SimpleNamespace(audio_data=b"should-not-run")

    service._generate_audio = unexpected_generation
    request = AudioRequest(
        text="Resposta longa que antes forçava áudio.",
        user_message="Olá",
        company_id=7,
    )

    response = asyncio.run(
        service.process_audio_request(request, force_audio=True)
    )

    assert response.should_send_audio is False
    assert response.audio_data is None
    assert generated is False
