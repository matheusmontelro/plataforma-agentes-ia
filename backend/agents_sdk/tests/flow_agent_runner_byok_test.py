from types import SimpleNamespace

from backend.services import flow_agent_runner
from backend.services.ai_provider_service import AIProviderNotConfiguredError


class _QueryStub:
    def __init__(self, config):
        self.config = config

    def filter_by(self, **filters):
        if self.config is not None and any(
            getattr(self.config, key, None) != value
            for key, value in filters.items()
        ):
            self.config = None
        return self

    def first(self):
        return self.config


class _DBStub:
    def __init__(self, config):
        self.config = config

    def query(self, _model):
        return _QueryStub(self.config)


def _agent_config(company_id: int = 17, config_id: int = 8):
    return SimpleNamespace(
        id=config_id,
        company_id=company_id,
        generated_prompt="Responda com clareza.",
        conversation_flow={},
    )


def test_flow_agent_runner_uses_active_company_openai_key(monkeypatch):
    db = _DBStub(_agent_config(company_id=17))
    captured = {}

    class _FakeCompletions:
        def create(self, **kwargs):
            captured["request"] = kwargs
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="Resposta da empresa")
                    )
                ],
                usage=SimpleNamespace(total_tokens=23),
            )

    class _FakeOpenAI:
        def __init__(self, *, api_key):
            captured["api_key"] = api_key
            self.chat = SimpleNamespace(completions=_FakeCompletions())

    def fake_company_key(fake_db, company_id):
        assert fake_db is db
        assert company_id == 17
        return "provider-key-company-seventeen"

    monkeypatch.setattr(
        flow_agent_runner,
        "ai_credit_block_result_from_balance",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        flow_agent_runner,
        "get_company_openai_api_key",
        fake_company_key,
    )
    monkeypatch.setattr(flow_agent_runner, "OpenAI", _FakeOpenAI)

    result = flow_agent_runner.run_agent_response(
        db,
        company_id=17,
        agent_config_id=8,
        message="Olá",
    )

    assert result == {
        "success": True,
        "response": "Resposta da empresa",
        "tokens_used": 23,
    }
    assert captured["api_key"] == "provider-key-company-seventeen"
    assert captured["request"]["messages"][-1] == {
        "role": "user",
        "content": "Olá",
    }


def test_flow_agent_runner_returns_safe_error_when_key_is_missing(monkeypatch):
    db = _DBStub(_agent_config(company_id=29, config_id=9))
    monkeypatch.setattr(
        flow_agent_runner,
        "ai_credit_block_result_from_balance",
        lambda **_kwargs: None,
    )

    def missing_key(_db, _company_id):
        raise AIProviderNotConfiguredError(
            "Chave OpenAI não configurada para a empresa ativa"
        )

    monkeypatch.setattr(
        flow_agent_runner,
        "get_company_openai_api_key",
        missing_key,
    )

    result = flow_agent_runner.run_agent_response(
        db,
        company_id=29,
        agent_config_id=9,
        message="Olá",
    )

    assert result["success"] is False
    assert result["response"] == ""
    assert result["error"] == "Chave OpenAI não configurada para a empresa ativa"


def test_flow_agent_runner_cannot_use_configuration_from_another_company(monkeypatch):
    db = _DBStub(_agent_config(company_id=17))
    monkeypatch.setattr(
        flow_agent_runner,
        "get_company_openai_api_key",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("cross-company configuration must be rejected before key lookup")
        ),
    )

    result = flow_agent_runner.run_agent_response(
        db,
        company_id=99,
        agent_config_id=8,
        message="Olá",
    )

    assert result == {
        "success": False,
        "response": "",
        "error": "Agent configuration 8 not found",
    }


def test_flow_agent_runner_never_reflects_provider_secret(monkeypatch, caplog):
    db = _DBStub(_agent_config(company_id=17, config_id=8))
    secret = "provider-sensitive-provider-marker"

    class _FailingCompletions:
        def create(self, **_kwargs):
            raise RuntimeError(f"provider rejected bearer {secret}")

    class _FakeOpenAI:
        def __init__(self, *, api_key):
            assert api_key == secret
            self.chat = SimpleNamespace(completions=_FailingCompletions())

    monkeypatch.setattr(
        flow_agent_runner,
        "ai_credit_block_result_from_balance",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        flow_agent_runner,
        "get_company_openai_api_key",
        lambda _db, _company_id: secret,
    )
    monkeypatch.setattr(flow_agent_runner, "OpenAI", _FakeOpenAI)

    result = flow_agent_runner.run_agent_response(
        db,
        company_id=17,
        agent_config_id=8,
        message="Olá",
    )

    assert result["success"] is False
    assert result["error"] == "Não foi possível executar o agente de IA"
    assert secret not in str(result)
    assert secret not in caplog.text
