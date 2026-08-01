import os

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/agentive_test")

from backend.agents_sdk.voice import config


def test_legacy_prompt_voice_preferences_do_not_enable_audio(monkeypatch):
    legacy = config.get_default_voice_config().model_copy(
        update={"voice_enabled": True, "provider": "elevenlabs"}
    )
    monkeypatch.setattr(
        config,
        "_load_voice_config_from_agent_workforce",
        lambda _db, _company_id: None,
    )
    monkeypatch.setattr(
        config,
        "_load_voice_config_from_agent_configuration",
        lambda _db, _company_id: legacy,
    )

    resolved = config.get_voice_config("db", 9)

    assert resolved.voice_enabled is False
    assert resolved.provider == "elevenlabs"


def test_active_workforce_voice_exception_remains_enabled(monkeypatch):
    active = config.get_default_voice_config().model_copy(
        update={"voice_enabled": True, "provider": "elevenlabs"}
    )
    monkeypatch.setattr(
        config,
        "_load_voice_config_from_agent_workforce",
        lambda _db, _company_id: active,
    )
    monkeypatch.setattr(
        config,
        "_load_voice_config_from_agent_configuration",
        lambda _db, _company_id: None,
    )

    resolved = config.get_voice_config("db", 7)

    assert resolved.voice_enabled is True
    assert resolved.provider == "elevenlabs"


def test_voice_override_cannot_switch_legacy_exception_to_openai(monkeypatch):
    active = config.get_default_voice_config().model_copy(
        update={"voice_enabled": True, "provider": "elevenlabs"}
    )
    monkeypatch.setattr(
        config,
        "_load_voice_config_from_agent_workforce",
        lambda _db, _company_id: active,
    )
    monkeypatch.setattr(
        config,
        "_load_voice_config_from_agent_configuration",
        lambda _db, _company_id: None,
    )

    resolved = config.get_voice_config(
        "db",
        7,
        {"provider": "openai", "voice_enabled": True},
    )

    assert resolved.voice_enabled is False
    assert resolved.provider == "openai"
