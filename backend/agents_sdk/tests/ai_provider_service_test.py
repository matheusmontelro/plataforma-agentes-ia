import os
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/agentive_test")

from backend.models import AIProviderCredential
from backend.services import ai_provider_service as service


class _FakeQuery:
    def __init__(self, credential):
        self.credential = credential

    def filter(self, *_args, **_kwargs):
        return self

    def one_or_none(self):
        return self.credential


class _FakeDB:
    def __init__(self, credential=None):
        self.credential = credential
        self.added = []

    def query(self, *_args, **_kwargs):
        return _FakeQuery(self.credential)

    def add(self, value):
        self.added.append(value)
        self.credential = value


def _clear_encryption_env(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER_TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("INTEGRATION_TOKEN_ENCRYPTION_KEY", raising=False)


def test_dedicated_key_encrypts_without_persisting_plaintext(monkeypatch):
    _clear_encryption_env(monkeypatch)
    monkeypatch.setenv(
        "AI_PROVIDER_TOKEN_ENCRYPTION_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    api_key = "provider-key-company-secret-value"

    ciphertext = service.encrypt_openai_api_key(api_key)

    assert api_key not in ciphertext
    assert service.decrypt_openai_api_key(ciphertext) == api_key


def test_dedicated_key_is_required_even_when_other_keys_exist(monkeypatch):
    _clear_encryption_env(monkeypatch)
    monkeypatch.setenv(
        "INTEGRATION_TOKEN_ENCRYPTION_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    with pytest.raises(
        service.AIProviderConfigurationError,
        match="AI_PROVIDER_TOKEN_ENCRYPTION_KEY não configurada",
    ):
        service.encrypt_openai_api_key("provider-key-no-cross-domain-fallback")


def test_configuration_rotation_uses_company_scoped_transaction_lock():
    class _LockDB:
        def __init__(self):
            self.calls = []

        def get_bind(self):
            return SimpleNamespace(
                dialect=SimpleNamespace(name="postgresql")
            )

        def execute(self, statement, params):
            self.calls.append((str(statement), params))

    db = _LockDB()

    service.lock_company_ai_provider_configuration(db, 31)

    assert len(db.calls) == 1
    statement, params = db.calls[0]
    assert "pg_advisory_xact_lock" in statement
    assert params == {
        "lock_key": "agentive:ai-provider:configuration:31"
    }


def test_validate_openai_key_filters_and_orders_supported_models(monkeypatch):
    closed = []
    probe_requests = []

    class _FakeModels:
        def list(self):
            return SimpleNamespace(
                data=[
                    SimpleNamespace(id="unrelated-model"),
                    SimpleNamespace(id="gpt-4o-transcribe"),
                    SimpleNamespace(id="gpt-4o-mini"),
                    SimpleNamespace(id="gpt-5.6-sol"),
                    SimpleNamespace(id="gpt-5.4-mini"),
                ]
            )

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            assert kwargs["api_key"] == "provider-key-valid"
            assert kwargs["max_retries"] == 0
            self.models = _FakeModels()
            self.responses = SimpleNamespace(
                create=lambda **request: probe_requests.append(request)
            )

        def close(self):
            closed.append(True)

    monkeypatch.setattr(service, "OpenAI", _FakeOpenAI)

    models = service.validate_openai_api_key("provider-key-valid")

    assert models == ["gpt-5.6-sol", "gpt-5.4-mini", "gpt-4o-mini"]
    assert closed == [True]
    assert probe_requests == [
        {
            "model": "gpt-4o-mini",
            "input": "Responda apenas OK.",
            "max_output_tokens": 1,
            "store": False,
        }
    ]


def test_validation_requires_the_legacy_runtime_base_model(monkeypatch):
    class _FakeModels:
        def list(self):
            return SimpleNamespace(
                data=[
                    SimpleNamespace(id="gpt-5.4-mini"),
                    SimpleNamespace(id="gpt-4o-transcribe"),
                ]
            )

    class _FakeOpenAI:
        def __init__(self, **_kwargs):
            self.models = _FakeModels()

        def close(self):
            return None

    monkeypatch.setattr(service, "OpenAI", _FakeOpenAI)

    with pytest.raises(
        service.AIProviderValidationError,
        match="modelo base",
    ):
        service.validate_openai_api_key("provider-key-without-runtime-model")


def test_validation_requires_the_runtime_transcription_model(monkeypatch):
    class _FakeModels:
        def list(self):
            return SimpleNamespace(
                data=[SimpleNamespace(id="gpt-4o-mini")]
            )

    class _FakeOpenAI:
        def __init__(self, **_kwargs):
            self.models = _FakeModels()

        def close(self):
            return None

    monkeypatch.setattr(service, "OpenAI", _FakeOpenAI)

    with pytest.raises(
        service.AIProviderValidationError,
        match="modelo de transcrição",
    ):
        service.validate_openai_api_key(
            "provider-key-without-transcription-model"
        )


def test_validation_failure_never_exposes_provider_exception(monkeypatch):
    secret = "provider-key-never-return-this"

    class _FakeModels:
        def list(self):
            raise RuntimeError(f"transport payload contained {secret}")

    class _FakeOpenAI:
        def __init__(self, **_kwargs):
            self.models = _FakeModels()

        def close(self):
            return None

    monkeypatch.setattr(service, "OpenAI", _FakeOpenAI)

    with pytest.raises(service.AIProviderValidationError) as exc_info:
        service.validate_openai_api_key(secret)

    assert secret not in str(exc_info.value)
    assert exc_info.value.credential_status == "error"


def test_company_key_resolution_and_run_config_are_per_execution(monkeypatch):
    _clear_encryption_env(monkeypatch)
    monkeypatch.setenv(
        "AI_PROVIDER_TOKEN_ENCRYPTION_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    encrypted = service.encrypt_openai_api_key("provider-key-company-seven")
    credential = AIProviderCredential(
        company_id=7,
        provider="openai",
        api_key_encrypted=encrypted,
        status="valid",
        available_models=["gpt-5.4-mini"],
    )
    db = _FakeDB(credential)

    assert service.get_company_openai_api_key(db, 7) == "provider-key-company-seven"

    run_config = service.build_company_openai_run_config(db, 7)
    assert run_config.model == service.REQUIRED_OPENAI_RUNTIME_MODEL
    assert run_config.tracing_disabled is True
    assert run_config.trace_include_sensitive_data is False
    assert run_config.model_provider is not None

    workforce_run_config = service.build_company_openai_run_config(
        db,
        7,
        model_override=None,
    )
    assert workforce_run_config.model is None


def test_company_key_resolution_rejects_non_valid_credential():
    credential = AIProviderCredential(
        company_id=9,
        provider="openai",
        api_key_encrypted="ciphertext",
        status="invalid",
        available_models=[],
    )

    with pytest.raises(
        service.AIProviderNotConfiguredError,
        match="não está validada",
    ):
        service.get_company_openai_api_key(_FakeDB(credential), 9)


def test_two_company_run_configs_never_share_provider_credentials(monkeypatch):
    _clear_encryption_env(monkeypatch)
    monkeypatch.setenv(
        "AI_PROVIDER_TOKEN_ENCRYPTION_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    captured_keys = []

    class _FakeProvider:
        def __init__(self, *, api_key):
            self.api_key = api_key
            captured_keys.append(api_key)

    monkeypatch.setattr(service, "OpenAIProvider", _FakeProvider)

    company_seven = AIProviderCredential(
        company_id=7,
        provider="openai",
        api_key_encrypted=service.encrypt_openai_api_key("sk-company-seven"),
        status="valid",
        available_models=["gpt-4o-mini"],
    )
    company_eight = AIProviderCredential(
        company_id=8,
        provider="openai",
        api_key_encrypted=service.encrypt_openai_api_key("sk-company-eight"),
        status="valid",
        available_models=["gpt-4o-mini"],
    )

    run_seven = service.build_company_openai_run_config(
        _FakeDB(company_seven),
        7,
    )
    run_eight = service.build_company_openai_run_config(
        _FakeDB(company_eight),
        8,
    )

    assert captured_keys == ["sk-company-seven", "sk-company-eight"]
    assert run_seven.model_provider is not run_eight.model_provider


def test_runtime_error_sanitizer_never_returns_provider_payload():
    secret = "provider-sensitive-runtime-marker"

    safe_error = service.safe_ai_provider_runtime_error(
        RuntimeError(f"provider rejected bearer {secret}"),
    )

    assert safe_error == "Não foi possível executar a operação de IA"
    assert secret not in safe_error


def test_explicit_trace_honors_run_config_tracing_disabled(monkeypatch):
    captured = {}

    class _TraceContext:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_trace(**kwargs):
        captured.update(kwargs)
        return _TraceContext()

    monkeypatch.setattr(service, "trace", fake_trace)

    with service.openai_run_trace(
        SimpleNamespace(tracing_disabled=True),
        workflow_name="byok-test",
        group_id="safe-group",
    ):
        pass

    assert captured["disabled"] is True
    assert captured["workflow_name"] == "byok-test"


def test_key_compatibility_rejects_models_already_saved_by_company():
    workforce = SimpleNamespace(
        agent_configs={
            "sales": {"model": {"model": "gpt-5.4-mini"}},
            "support": {"model": {"model": "gpt-4o-mini"}},
        }
    )

    class _WorkforceQuery:
        def filter(self, *_args, **_kwargs):
            return self

        def all(self):
            return [workforce]

    class _WorkforceDB:
        def query(self, *_args, **_kwargs):
            return _WorkforceQuery()

    with pytest.raises(
        service.AIProviderCompatibilityError,
        match="gpt-5.4-mini",
    ):
        service.ensure_company_workforce_models_are_supported(
            _WorkforceDB(),
            7,
            ["gpt-4o-mini"],
        )

    service.ensure_company_workforce_models_are_supported(
        _WorkforceDB(),
        7,
        ["gpt-4o-mini", "gpt-5.4-mini"],
    )
