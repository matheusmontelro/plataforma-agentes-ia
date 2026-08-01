import asyncio
import json
import logging
import os
from contextlib import contextmanager
from types import SimpleNamespace

from agents import RunContextWrapper

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://agentive_test@127.0.0.1:5432/agentive_test",
)

from backend.agents_sdk.agents import contact_identification_agent as contact_module
from backend.agents_sdk.tools import scheduling_tools
from backend.agents_sdk.tools import smart_referral_collector
from backend.agents_sdk.tools import third_party_detection


GLOBAL_KEY_MARKER = "global-openai-key-must-not-be-used"
COMPANY_KEY = "company-scoped-openai-key"


def _chat_response(content: str):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
            )
        ]
    )


def test_third_party_detection_uses_company_key(monkeypatch):
    db = object()
    captured = {}

    class FakeOpenAI:
        def __init__(self, *, api_key):
            captured["api_key"] = api_key
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_kwargs: _chat_response(
                        json.dumps(
                            {
                                "intent": "third_party_booking",
                                "is_third_party": True,
                                "relationship": "mãe",
                                "confidence": 0.99,
                                "reasoning": "Pedido explícito",
                            }
                        )
                    )
                )
            )

    def fake_company_key(received_db, company_id):
        assert received_db is db
        assert company_id == 41
        return COMPANY_KEY

    monkeypatch.setenv("OPENAI_API_KEY", GLOBAL_KEY_MARKER)
    monkeypatch.setattr(
        third_party_detection,
        "get_company_openai_api_key",
        fake_company_key,
    )
    monkeypatch.setattr(third_party_detection, "OpenAI", FakeOpenAI)

    result = third_party_detection.detect_third_party_booking_intent(
        "Quero marcar para minha mãe",
        {"current_stage": "etapa_4"},
        db=db,
        company_id=41,
    )

    assert result["is_third_party"] is True
    assert captured["api_key"] == COMPANY_KEY
    assert captured["api_key"] != GLOBAL_KEY_MARKER


def test_third_party_detection_does_not_log_provider_exception_payload(
    monkeypatch,
    caplog,
):
    secret_marker = "provider-key-should-never-reach-the-log"

    def explode(_db, _company_id):
        raise RuntimeError(secret_marker)

    monkeypatch.setattr(
        third_party_detection,
        "get_company_openai_api_key",
        explode,
    )

    with caplog.at_level(logging.ERROR):
        result = third_party_detection.detect_third_party_booking_intent(
            "Mensagem ambígua",
            {},
            db=object(),
            company_id=7,
        )

    assert result["intent"] == "unclear"
    assert secret_marker not in caplog.text
    assert secret_marker not in json.dumps(result)


def test_scheduling_semantic_analysis_uses_company_key(monkeypatch):
    db = object()
    captured = {}

    class FakeCompletions:
        async def create(self, **_kwargs):
            return _chat_response(
                json.dumps(
                    {
                        "weekday_name": None,
                        "specific_date": None,
                        "time_periods": [],
                        "time_preference": "flexible",
                        "specific_times": [],
                        "time_restrictions": {
                            "type": "none",
                            "min_time": None,
                            "max_time": None,
                        },
                        "urgency": "flexible",
                    }
                )
            )

    class FakeAsyncOpenAI:
        def __init__(self, *, api_key):
            captured["api_key"] = api_key
            self.chat = SimpleNamespace(completions=FakeCompletions())

    def fake_company_key(received_db, company_id):
        assert received_db is db
        assert company_id == 52
        return COMPANY_KEY

    monkeypatch.setenv("OPENAI_API_KEY", GLOBAL_KEY_MARKER)
    monkeypatch.setattr(
        scheduling_tools,
        "get_company_openai_api_key",
        fake_company_key,
    )
    monkeypatch.setattr("openai.AsyncOpenAI", FakeAsyncOpenAI)

    result = asyncio.run(
        scheduling_tools._analyze_scheduling_preferences_with_context(
            "Quero consultar horários disponíveis",
            company_id=52,
            db=db,
        )
    )

    assert result["urgency"] == "flexible"
    assert captured["api_key"] == COMPANY_KEY
    assert captured["api_key"] != GLOBAL_KEY_MARKER


def test_smart_referral_openai_helpers_receive_only_explicit_key(monkeypatch):
    captured_keys = []

    class FakeCompletions:
        def create(self, *, messages, **_kwargs):
            prompt = messages[0]["content"]
            if "dados PENDENTES" in prompt:
                content = json.dumps(
                    {
                        "pending_phones": [],
                        "pending_names": ["Maria Silva"],
                        "last_request_type": "phone",
                    }
                )
            elif "Formate este telefone" in prompt:
                content = "5500000000007"
            else:
                content = json.dumps(
                    {
                        "type": "names_only",
                        "complete_pairs": [],
                        "phones": [],
                        "names": ["Maria Silva"],
                    }
                )
            return _chat_response(content)

    class FakeOpenAI:
        def __init__(self, *, api_key):
            captured_keys.append(api_key)
            self.chat = SimpleNamespace(completions=FakeCompletions())

    class FakeDB:
        def execute(self, *_args, **_kwargs):
            return SimpleNamespace(
                fetchall=lambda: [
                    SimpleNamespace(
                        from_me=False,
                        content="Maria Silva",
                        timestamp=None,
                    )
                ]
            )

    monkeypatch.setenv("OPENAI_API_KEY", GLOBAL_KEY_MARKER)
    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    smart_referral_collector._analyze_user_input(
        "Maria Silva",
        api_key=COMPANY_KEY,
    )
    smart_referral_collector._get_pending_referral_data(
        FakeDB(),
        61,
        "5500000000007",
        api_key=COMPANY_KEY,
    )
    smart_referral_collector._format_phone(
        "(11) 99999-9999",
        api_key=COMPANY_KEY,
    )

    assert captured_keys == [COMPANY_KEY, COMPANY_KEY, COMPANY_KEY]
    assert GLOBAL_KEY_MARKER not in captured_keys


def test_smart_referral_tool_binds_company_and_disables_trace(monkeypatch):
    db = object()
    captured = {}

    @contextmanager
    def fake_trace(_name, *, disabled=False):
        captured["trace_disabled"] = disabled
        yield

    def fake_company_key(received_db, company_id):
        captured["key_lookup"] = (received_db, company_id)
        return COMPANY_KEY

    def fake_analysis(user_input, *, api_key):
        captured["analysis"] = (user_input, api_key)
        return {"type": "unknown", "complete_pairs": [], "phones": [], "names": []}

    def fake_pending(received_db, company_id, phone, *, api_key):
        captured["pending"] = (received_db, company_id, phone, api_key)
        return {}

    def fake_process(
        *,
        db,
        company_id,
        referrer_phone,
        current_input,
        pending_data,
        api_key,
    ):
        captured["process"] = (
            db,
            company_id,
            referrer_phone,
            current_input,
            pending_data,
            api_key,
        )
        return {"status": "complete", "message": "Indicação concluída"}

    monkeypatch.setattr(smart_referral_collector, "trace", fake_trace)
    monkeypatch.setattr(
        smart_referral_collector,
        "_check_referral_eligibility",
        lambda *_args: True,
    )
    monkeypatch.setattr(
        smart_referral_collector,
        "_set_referral_collection_mode",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        smart_referral_collector,
        "get_company_openai_api_key",
        fake_company_key,
    )
    monkeypatch.setattr(
        smart_referral_collector,
        "_analyze_user_input",
        fake_analysis,
    )
    monkeypatch.setattr(
        smart_referral_collector,
        "_get_pending_referral_data",
        fake_pending,
    )
    monkeypatch.setattr(
        smart_referral_collector,
        "_process_combined_data",
        fake_process,
    )

    runtime_context = SimpleNamespace(
        company_id=71,
        phone="5500000000016",
        db=db,
    )
    result = asyncio.run(
        smart_referral_collector.collect_referral_data_incrementally.on_invoke_tool(
            RunContextWrapper(context=runtime_context),
            json.dumps({"user_input": "Maria Silva"}),
        )
    )

    assert result == "Indicação concluída"
    assert captured["trace_disabled"] is True
    assert captured["key_lookup"] == (db, 71)
    assert captured["analysis"] == ("Maria Silva", COMPANY_KEY)
    assert "company_id" not in (
        smart_referral_collector.collect_referral_data_incrementally
        .params_json_schema["properties"]
    )
    assert "phone" not in (
        smart_referral_collector.collect_referral_data_incrementally
        .params_json_schema["properties"]
    )


def test_contact_identification_tool_uses_context_key(monkeypatch):
    db = object()
    captured = {}

    class FakeOpenAI:
        def __init__(self, *, api_key):
            captured["api_key"] = api_key
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_kwargs: _chat_response(
                        json.dumps(
                            {
                                "claims_to_be_customer": True,
                                "confidence": 0.98,
                                "reasoning": "Cliente confirmou vínculo",
                                "user_intent": "Agendar retorno",
                                "recently_evaluated": True,
                            }
                        )
                    )
                )
            )

    def fake_company_key(received_db, company_id):
        assert received_db is db
        assert company_id == 81
        return COMPANY_KEY

    monkeypatch.setenv("OPENAI_API_KEY", GLOBAL_KEY_MARKER)
    monkeypatch.setattr(
        contact_module,
        "get_company_openai_api_key",
        fake_company_key,
    )
    monkeypatch.setattr(contact_module.openai, "OpenAI", FakeOpenAI)

    runtime_context = SimpleNamespace(company_id=81, db=db)
    result = asyncio.run(
        contact_module.analyze_customer_status_with_llm.on_invoke_tool(
            RunContextWrapper(context=runtime_context),
            json.dumps({"request": {"user_response": "Já sou cliente"}}),
        )
    )

    assert captured["api_key"] == COMPANY_KEY
    assert captured["api_key"] != GLOBAL_KEY_MARKER
    assert result.claims_to_be_customer is True
    assert "company_id" not in (
        contact_module.analyze_customer_status_with_llm
        .params_json_schema["properties"]
    )


def test_contact_identification_does_not_echo_secret_errors(
    monkeypatch,
    caplog,
):
    secret_marker = "provider-key-exception-payload"

    def explode(_db, _company_id):
        raise RuntimeError(secret_marker)

    monkeypatch.setattr(
        contact_module,
        "get_company_openai_api_key",
        explode,
    )
    runtime_context = SimpleNamespace(company_id=91, db=object())

    with caplog.at_level(logging.ERROR):
        result = asyncio.run(
            contact_module.analyze_customer_intent_with_llm.on_invoke_tool(
                RunContextWrapper(context=runtime_context),
                json.dumps({"request": {"user_response": "Quero retornar"}}),
            )
        )

    assert secret_marker not in str(result)
    assert secret_marker not in caplog.text
    assert result.reasoning == (
        "Não foi possível concluir a análise de intenção"
    )
