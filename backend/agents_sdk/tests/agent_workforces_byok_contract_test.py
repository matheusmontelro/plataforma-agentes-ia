import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/agentive_test")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-secret-key-with-at-least-32-characters",
)

from backend.routes import agent_workforces as routes


def _state(
    *,
    model: str = "gpt-5.4-mini",
    allow_audio: bool = False,
    voice_provider: str = "elevenlabs",
    status: str = "active",
):
    return {
        "status": status,
        "agent_configs": {
            "atendimento": {
                "model": {"model": model},
                "channel": {
                    "allow_audio": allow_audio,
                    "voice": {
                        "provider": voice_provider,
                        "voice_id": "voice-legacy",
                    },
                },
            }
        }
    }


def test_company_model_contract_accepts_only_models_available_to_company(
    monkeypatch,
):
    credential = SimpleNamespace(
        status="valid",
        available_models=["gpt-4o-mini"],
    )
    monkeypatch.setattr(
        routes.ai_provider_service,
        "get_company_ai_provider_credential",
        lambda db, company_id: credential
        if db == "db" and company_id == 7
        else None,
    )

    routes._validate_company_models(
        "db",
        7,
        _state(model="gpt-4o-mini"),
    )

    with pytest.raises(HTTPException) as exc_info:
        routes._validate_company_models(
            "db",
            7,
            _state(model="gpt-5.4-mini"),
        )

    assert exc_info.value.status_code == 422
    assert "gpt-5.4-mini" in str(exc_info.value.detail)


def test_company_model_contract_requires_validated_credential(monkeypatch):
    monkeypatch.setattr(
        routes.ai_provider_service,
        "get_company_ai_provider_credential",
        lambda _db, _company_id: None,
    )

    with pytest.raises(HTTPException) as exc_info:
        routes._validate_company_models(
            "db",
            7,
            _state(),
        )

    assert exc_info.value.status_code == 409
    assert "chave OpenAI" in str(exc_info.value.detail)


def test_audio_contract_blocks_new_activation_but_preserves_legacy():
    with pytest.raises(HTTPException) as exc_info:
        routes._reject_new_audio_activations(
            _state(allow_audio=True),
        )

    assert exc_info.value.status_code == 410

    routes._reject_new_audio_activations(
        _state(allow_audio=True),
        previous_state=_state(allow_audio=True),
    )
    routes._reject_new_audio_activations(
        _state(allow_audio=False),
        previous_state=_state(allow_audio=True),
    )


def test_audio_contract_rejects_switching_legacy_voice_to_openai():
    with pytest.raises(HTTPException) as exc_info:
        routes._reject_new_audio_activations(
            _state(allow_audio=True, voice_provider="openai"),
            previous_state=_state(
                allow_audio=True,
                voice_provider="elevenlabs",
            ),
        )

    assert exc_info.value.status_code == 410
    assert "ElevenLabs" in str(exc_info.value.detail)


def test_audio_contract_allows_deactivating_legacy_workforce_without_rewrite():
    routes._reject_new_audio_activations(
        _state(allow_audio=True, status="inactive"),
        previous_state=_state(allow_audio=True, status="active"),
    )


def test_generic_create_strips_server_managed_knowledge_ids():
    settings = {
        "agent_context": {
            "knowledge": {
                "file_search": {
                    "enabled": True,
                    "max_num_results": 8,
                    "vector_store_id": "vs-other-tenant",
                    "files": [{"file_id": "file-other-tenant"}],
                    "links": [{"file_id": "file-link-other-tenant"}],
                    "provider_scope": "company_byok",
                    "api_key_fingerprint": "forged",
                }
            }
        }
    }

    protected = routes._protect_server_managed_knowledge_settings(settings)
    file_search = protected["agent_context"]["knowledge"]["file_search"]

    assert file_search == {
        "enabled": True,
        "max_num_results": 8,
    }
    assert settings["agent_context"]["knowledge"]["file_search"][
        "vector_store_id"
    ] == "vs-other-tenant"


def test_generic_update_preserves_existing_server_managed_knowledge_ids():
    previous = {
        "agent_context": {
            "knowledge": {
                "file_search": {
                    "enabled": True,
                    "vector_store_id": "vs-company",
                    "files": [{"file_id": "file-company"}],
                    "links": [],
                    "provider_scope": "company_byok",
                    "api_key_fingerprint": "trusted",
                }
            }
        }
    }
    forged = {
        "agent_context": {
            "knowledge": {
                "file_search": {
                    "enabled": False,
                    "vector_store_id": "vs-other-tenant",
                    "files": [{"file_id": "file-other-tenant"}],
                    "provider_scope": "company_byok",
                    "api_key_fingerprint": "forged",
                }
            }
        }
    }

    protected = routes._protect_server_managed_knowledge_settings(
        forged,
        previous_settings=previous,
    )
    file_search = protected["agent_context"]["knowledge"]["file_search"]

    assert file_search["enabled"] is False
    assert file_search["vector_store_id"] == "vs-company"
    assert file_search["files"] == [{"file_id": "file-company"}]
    assert file_search["links"] == []
    assert file_search["api_key_fingerprint"] == "trusted"


def test_generic_update_cannot_drop_server_managed_knowledge_ids():
    previous = {
        "agent_context": {
            "knowledge": {
                "file_search": {
                    "vector_store_id": "vs-company",
                    "files": [{"file_id": "file-company"}],
                    "links": [],
                    "provider_scope": "company_byok",
                    "api_key_fingerprint": "trusted",
                }
            }
        }
    }

    protected = routes._protect_server_managed_knowledge_settings(
        {"performance": {"response_delay_seconds": 2}},
        previous_settings=previous,
    )
    file_search = protected["agent_context"]["knowledge"]["file_search"]

    assert file_search["vector_store_id"] == "vs-company"
    assert file_search["files"] == [{"file_id": "file-company"}]
    assert file_search["provider_scope"] == "company_byok"


def test_knowledge_client_uses_company_key(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        routes.ai_provider_service,
        "get_company_openai_api_key",
        lambda db, company_id: "company-seven-key"
        if db == "db" and company_id == 7
        else "",
    )

    class FakeOpenAI:
        def __init__(self, *, api_key):
            captured["api_key"] = api_key

    monkeypatch.setattr(routes, "OpenAI", FakeOpenAI)

    routes._ensure_openai_client("db", 7)

    assert captured == {"api_key": "company-seven-key"}
