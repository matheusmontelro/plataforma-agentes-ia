import os
from types import SimpleNamespace

import pytest

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://agentive_test@127.0.0.1:5432/agentive_test",
)

from backend.prompt.llm.langchain import llm_config
from backend.services.ai_provider_service import AIProviderNotConfiguredError


GLOBAL_KEY_MARKER = "global-openai-key-must-not-be-used"
COMPANY_KEY = "company-scoped-openai-key"


class _FakeChatOpenAI:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.__class__.instances.append(self)


def test_optimized_llm_uses_company_key_and_overrides_legacy_kwarg(monkeypatch):
    db = object()
    _FakeChatOpenAI.instances = []

    def fake_company_key(received_db, company_id):
        assert received_db is db
        assert company_id == 41
        return COMPANY_KEY

    monkeypatch.setenv("OPENAI_API_KEY", GLOBAL_KEY_MARKER)
    monkeypatch.setattr(
        llm_config,
        "get_company_openai_api_key",
        fake_company_key,
    )
    monkeypatch.setattr(llm_config, "ChatOpenAI", _FakeChatOpenAI)

    llm = llm_config.create_optimized_llm(
        company_id=41,
        db=db,
        openai_api_key=GLOBAL_KEY_MARKER,
        enable_cache_logging=False,
    )

    assert llm.kwargs["openai_api_key"] == COMPANY_KEY
    assert llm.kwargs["openai_api_key"] != GLOBAL_KEY_MARKER


def test_optimized_llm_rejects_missing_company_without_using_global_key(
    monkeypatch,
):
    monkeypatch.setenv("OPENAI_API_KEY", GLOBAL_KEY_MARKER)
    monkeypatch.setattr(
        llm_config,
        "ChatOpenAI",
        lambda **_kwargs: pytest.fail("ChatOpenAI não deveria ser criado"),
    )

    with pytest.raises(
        AIProviderNotConfiguredError,
        match="Empresa ativa não informada",
    ):
        llm_config.create_optimized_llm(enable_cache_logging=False)


def test_llm_for_use_case_keeps_company_only_call_contract(monkeypatch):
    db = SimpleNamespace(closed=False)
    _FakeChatOpenAI.instances = []

    def fake_session_local():
        return db

    def fake_company_key(received_db, company_id):
        assert received_db is db
        assert company_id == 7
        return COMPANY_KEY

    db.close = lambda: setattr(db, "closed", True)
    monkeypatch.setattr("backend.db.SessionLocal", fake_session_local)
    monkeypatch.setattr(
        llm_config,
        "get_company_openai_api_key",
        fake_company_key,
    )
    monkeypatch.setattr(llm_config, "ChatOpenAI", _FakeChatOpenAI)

    llm = llm_config.create_llm_for_use_case("parser", company_id=7)

    assert llm.kwargs["openai_api_key"] == COMPANY_KEY
    assert db.closed is True
