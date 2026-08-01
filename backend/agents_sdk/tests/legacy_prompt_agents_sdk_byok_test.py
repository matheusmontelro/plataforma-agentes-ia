import asyncio
import logging
import os
from types import SimpleNamespace

import pytest


os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://agentive_test@127.0.0.1:5432/agentive_test",
)

from backend.prompt.agents_sdk.config import sdk_config
from backend.prompt.agents_sdk.utils import state_triggers


GLOBAL_KEY_MARKER = "global-openai-key-must-not-be-used"
COMPANY_KEY = "company-scoped-openai-key"


def test_legacy_sdk_config_requires_an_explicit_company_key(monkeypatch):
    captured = {}

    class FakeOpenAIProvider:
        def __init__(self, *, api_key):
            captured["api_key"] = api_key

    monkeypatch.setenv("OPENAI_API_KEY", GLOBAL_KEY_MARKER)
    monkeypatch.setattr(sdk_config, "OpenAIProvider", FakeOpenAIProvider)

    with pytest.raises(ValueError, match="explícita da empresa"):
        sdk_config.configure_agents_sdk()

    run_config = sdk_config.configure_agents_sdk(
        sdk_config.AgentsConfig(api_key=COMPANY_KEY)
    )

    assert captured["api_key"] == COMPANY_KEY
    assert captured["api_key"] != GLOBAL_KEY_MARKER
    assert run_config.model == "gpt-4o-mini"
    assert run_config.tracing_disabled is True
    assert run_config.trace_include_sensitive_data is False


def test_state_trigger_client_never_falls_back_to_environment(monkeypatch):
    captured = {}

    class FakeOpenAI:
        def __init__(self, *, api_key):
            captured["api_key"] = api_key

    monkeypatch.setenv("OPENAI_API_KEY", GLOBAL_KEY_MARKER)
    monkeypatch.setattr(state_triggers, "OpenAI", FakeOpenAI)

    with pytest.raises(ValueError, match="explícita da empresa"):
        state_triggers.StateTriggerHandler._openai_client("")

    state_triggers.StateTriggerHandler._openai_client(COMPANY_KEY)

    assert captured["api_key"] == COMPANY_KEY
    assert captured["api_key"] != GLOBAL_KEY_MARKER


def test_state_trigger_semantic_call_uses_explicit_company_key(monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, **_kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="true"),
                    )
                ]
            )

    class FakeOpenAI:
        def __init__(self, *, api_key):
            captured["api_key"] = api_key
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("OPENAI_API_KEY", GLOBAL_KEY_MARKER)
    monkeypatch.setattr(state_triggers, "OpenAI", FakeOpenAI)

    result = asyncio.run(
        state_triggers.StateTriggerHandler._extract_cancellation_intent(
            "Quero cancelar",
            COMPANY_KEY,
        )
    )

    assert result is True
    assert captured["api_key"] == COMPANY_KEY
    assert captured["api_key"] != GLOBAL_KEY_MARKER


def test_state_trigger_does_not_log_provider_exception_payload(
    monkeypatch,
    caplog,
):
    secret_marker = "provider-sensitive-provider-marker"

    class FailingOpenAI:
        def __init__(self, *, api_key):
            assert api_key == COMPANY_KEY
            raise RuntimeError(secret_marker)

    monkeypatch.setattr(state_triggers, "OpenAI", FailingOpenAI)

    with caplog.at_level(logging.WARNING):
        result = asyncio.run(
            state_triggers.StateTriggerHandler._extract_treatment_intent(
                "Quero implante",
                COMPANY_KEY,
            )
        )

    assert result == "implante"
    assert secret_marker not in caplog.text
