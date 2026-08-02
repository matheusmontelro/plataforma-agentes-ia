import base64
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from agents import InputGuardrailTripwireTriggered, RunContextWrapper
from fastapi import HTTPException

from backend.agents_sdk.agent_builder import AgentCreationConfig, compile_agent_preview
from backend.agents_sdk.tools.audio_delivery_tools import record_audio_delivery_request
from backend.agents_sdk.voice import AudioResponse
from backend.services import flow_agent_workforce_runner
from backend.services.ai_provider_service import AIProviderNotConfiguredError
from backend.agents_sdk.agent_builder.prompt_compiler import build_agent_instructions
from backend.routes.integrations.google_calendar_service import extract_google_meeting_link
from backend.routes.agent_workforces import _validate_workforce_contract
from backend.models import AgentWorkforce
from backend.services.flow_agent_workforce_runner import (
    _agent_audio_trigger_type,
    _apply_requested_audio_failure_text_fallback,
    _audio_history_text_from_execution_metadata,
    _build_agent_audio_delivery_plan,
    _build_runner_input,
    _compile_workforce_agents,
    _contains_audio_capability_refusal,
    _evaluate_custom_guardrails,
    _generate_configured_agent_audio,
    _is_workforce_schedule_open,
    _match_audio_history_transcripts,
    _message_content_for_agent_history,
    _normalize_workforce_schedule,
    _phone_candidates,
    _response_delay_seconds,
    _runtime_image_input_parts,
    _sanitize_agent_response_punctuation,
    _sanitize_audio_refusal_response,
    _sanitize_false_customer_file_reference,
    _sanitize_whatsapp_markdown_links,
    _voice_override_from_agent_config,
    run_agent_workforce_response,
)
from backend.routes.integrations.google_calendar_flow_service import (
    _build_google_event_summary,
)


def _agent_payload(key: str = "coordenador", target: str | None = None) -> dict:
    handoffs = []
    if target:
        handoffs.append(
            {
                "target_agent": target,
                "when": "quando outro especialista tiver melhor contexto",
            }
        )

    return {
        "schema_version": "2026-05-01",
        "agent": {
            "key": key,
            "name": key.title(),
            "role": "Atendimento",
        },
        "objective": {
            "primary_goal": "Responder o contato com clareza",
        },
        "model": {
            "model": "gpt-5.4-mini",
            "reasoning_effort": "low",
        },
        "handoffs": handoffs,
    }


def _workforce_payload() -> dict:
    root = _agent_payload("coordenador", target="suporte")
    support = _agent_payload("suporte")
    return {
        "name": "Equipe",
        "status": "draft",
        "channel": "whatsapp",
        "root_agent_key": "coordenador",
        "nodes": [
            {"id": "a", "data": {"kind": "custom", "key": "coordenador"}},
            {"id": "b", "data": {"kind": "custom", "key": "suporte"}},
        ],
        "edges": [],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "agent_configs": {
            "coordenador": root,
            "suporte": support,
        },
        "settings": {},
    }


def test_validate_workforce_contract_rejects_missing_root_agent():
    payload = _workforce_payload()
    payload["root_agent_key"] = "inexistente"

    with pytest.raises(HTTPException) as exc:
        _validate_workforce_contract(payload)

    assert exc.value.status_code == 422
    assert "root_agent_key" in exc.value.detail


def test_validate_workforce_contract_accepts_empty_draft():
    _validate_workforce_contract(
        {
            "name": "Equipe em rascunho",
            "status": "draft",
            "channel": "whatsapp",
            "root_agent_key": None,
            "nodes": [],
            "edges": [],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
            "agent_configs": {},
            "settings": {},
        }
    )


def test_validate_workforce_contract_rejects_empty_active_workforce():
    payload = {
        "name": "Equipe ativa",
        "status": "active",
        "channel": "whatsapp",
        "root_agent_key": None,
        "nodes": [],
        "edges": [],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "agent_configs": {},
        "settings": {},
    }

    with pytest.raises(HTTPException) as exc:
        _validate_workforce_contract(payload)

    assert exc.value.status_code == 422
    assert "at least one AI agent" in exc.value.detail


def test_validate_workforce_contract_accepts_agent_configs():
    _validate_workforce_contract(_workforce_payload())


def test_compile_preview_accepts_dynamic_crm_followup_tool():
    payload = _agent_payload()
    payload["tools"] = [
        {
            "id": "crm.dynamic_followup",
            "enabled": True,
            "requires_approval": True,
            "settings": {
                "pipeline_id": 7,
                "target_stage_ids": [33],
                "steps": [
                    {
                        "step_number": 1,
                        "send_after": 2,
                        "send_after_unit": "hours",
                        "channel": "whatsapp",
                        "objective": "Reconhecer cadastro",
                        "mini_prompt": "Gere uma mensagem curta para o lead.",
                    }
                ],
            },
        }
    ]

    preview = compile_agent_preview(AgentCreationConfig.model_validate(payload))

    assert preview["warnings"] == []
    assert "crm.dynamic_followup" in preview["instructions"]
    assert "background CRM automation" in preview["instructions"]


def test_compile_workforce_agents_preserves_dynamic_followup_appointment_stop_setting():
    payload = _agent_payload("coordenador")
    payload["tools"] = [
        {
            "id": "crm.dynamic_followup",
            "enabled": True,
            "settings": {
                "pipeline_id": 7,
                "target_stage_ids": [33],
                "stop_on_appointment_created": False,
                "steps": [
                    {
                        "step_number": 1,
                        "send_after": 2,
                        "send_after_unit": "hours",
                        "channel": "whatsapp",
                        "objective": "Reconhecer cadastro",
                        "mini_prompt": "Gere uma mensagem curta para o lead.",
                    }
                ],
            },
        }
    ]

    compiled = _compile_workforce_agents(
        agent_configs={"coordenador": payload},
        root_agent_key="coordenador",
        company_id=1,
    )

    settings = compiled.configs_by_key["coordenador"].tools[0].settings

    assert settings["stop_on_appointment_created"] is False
    assert not compiled.warnings


def test_regex_guardrail_blocks_matching_input():
    config = AgentCreationConfig.model_validate(
        {
            **_agent_payload(),
            "custom_guardrails": [
                {
                    "key": "bloquear_cpf",
                    "name": "Bloquear CPF",
                    "stage": "input",
                    "check_type": "regex",
                    "condition": r"\d{3}\.\d{3}\.\d{3}-\d{2}",
                    "action": "block",
                    "message": "Nao envie CPF por aqui.",
                }
            ],
        }
    )

    result = _evaluate_custom_guardrails(config, "input", "Meu CPF e 123.456.789-10")

    assert result
    assert result["action"] == "block"
    assert result["message"] == "Nao envie CPF por aqui."


def test_compile_workforce_agents_wires_sdk_handoffs():
    agent_configs = {
        "coordenador": _agent_payload("coordenador", "suporte"),
        "suporte": _agent_payload("suporte"),
    }

    compiled = _compile_workforce_agents(
        agent_configs=agent_configs,
        root_agent_key="coordenador",
    )

    assert compiled.root_agent.name == "Coordenador"
    assert [agent.name for agent in compiled.root_agent.handoffs] == ["Suporte"]


def test_run_agent_workforce_records_usage_with_runtime_model(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    payload = _agent_payload("coordenador")
    workforce = AgentWorkforce(
        id=2,
        company_id=7,
        name="Equipe",
        status="active",
        channel="whatsapp",
        root_agent_key="coordenador",
        agent_configs={"coordenador": payload},
        settings={},
        nodes=[],
        edges=[],
        viewport={},
    )

    class QueryStub:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return workforce

    class DBStub:
        def query(self, model):
            return QueryStub()

    runner_kwargs = {}

    async def fake_run_agent_sdk(**kwargs):
        runner_kwargs.update(kwargs)
        return SimpleNamespace(
            final_output="Olá! Como posso ajudar?",
            context_wrapper=SimpleNamespace(usage=None),
            last_agent=kwargs["agent"],
            last_response_id="resp_test",
        )

    captured = {}
    company_run_config = object()

    def fake_record_usage(**kwargs):
        captured.update(kwargs)

    def fake_company_run_config(
        db,
        company_id,
        tracing_disabled,
        model_override,
    ):
        assert db is not None
        assert company_id == 7
        assert tracing_disabled is True
        assert model_override is None
        return company_run_config

    monkeypatch.setattr(
        flow_agent_workforce_runner,
        "build_company_openai_run_config",
        fake_company_run_config,
    )
    monkeypatch.setattr(flow_agent_workforce_runner, "_run_agent_sdk", fake_run_agent_sdk)
    monkeypatch.setattr(flow_agent_workforce_runner, "_log_agent_execution", lambda **kwargs: 123)
    monkeypatch.setattr(flow_agent_workforce_runner, "safe_record_openai_text_usage", fake_record_usage)
    monkeypatch.setattr(flow_agent_workforce_runner, "_record_audio_usage_event", lambda **kwargs: None)
    monkeypatch.setattr(flow_agent_workforce_runner, "ai_credit_block_result_from_balance", lambda **kwargs: None)

    result = run_agent_workforce_response(
        db=DBStub(),
        workforce_id=2,
        company_id=7,
        message="oi",
        runtime_variables={"contact_phone": "5500000000001"},
        allow_inactive=True,
    )

    assert result["success"] is True
    assert result["response"] == "Olá! Como posso ajudar?"
    assert captured["model"] == "gpt-5.4-mini"
    assert captured["agent_execution_id"] == 123
    assert runner_kwargs["run_config"] is company_run_config


def test_run_agent_workforce_sanitizes_unsupported_customer_file_reference(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    payload = _agent_payload("coordenador")
    workforce = AgentWorkforce(
        id=4,
        company_id=10,
        name="Equipe Principal",
        status="active",
        channel="whatsapp",
        root_agent_key="coordenador",
        agent_configs={"coordenador": payload},
        settings={
            "agent_context": {
                "knowledge": {
                    "file_search": {
                        "enabled": True,
                        "vector_store_id": "vs_test",
                    }
                }
            }
        },
        nodes=[],
        edges=[],
        viewport={},
    )

    class QueryStub:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return workforce

    class DBStub:
        def query(self, model):
            return QueryStub()

    async def fake_run_agent_sdk(**kwargs):
        return SimpleNamespace(
            final_output=(
                "Você poderia me informar o que você gostaria de saber "
                "sobre os arquivos que você enviou?"
            ),
            context_wrapper=SimpleNamespace(usage=None),
            last_agent=kwargs["agent"],
            last_response_id="resp_test",
        )

    logged = {}

    def fake_log_agent_execution(**kwargs):
        logged.update(kwargs)
        return 588

    monkeypatch.setattr(flow_agent_workforce_runner, "_run_agent_sdk", fake_run_agent_sdk)
    monkeypatch.setattr(
        flow_agent_workforce_runner,
        "build_company_openai_run_config",
        lambda db, company_id, tracing_disabled, model_override: object(),
    )
    monkeypatch.setattr(flow_agent_workforce_runner, "_log_agent_execution", fake_log_agent_execution)
    monkeypatch.setattr(flow_agent_workforce_runner, "safe_record_openai_text_usage", lambda **kwargs: None)
    monkeypatch.setattr(flow_agent_workforce_runner, "_record_audio_usage_event", lambda **kwargs: None)
    monkeypatch.setattr(flow_agent_workforce_runner, "ai_credit_block_result_from_balance", lambda **kwargs: None)

    result = run_agent_workforce_response(
        db=DBStub(),
        workforce_id=4,
        company_id=10,
        message="oi",
        runtime_variables={"trigger": {"body": "oi", "type": "text"}},
        allow_inactive=True,
    )

    assert result["success"] is True
    assert result["response"] == "Olá, tudo bem? Como posso te ajudar?"
    assert "arquivos" not in result["response"].lower()
    assert result["metadata"]["false_customer_file_reference_sanitized"] is True
    assert logged["agent_response"] == "Olá, tudo bem? Como posso te ajudar?"


def test_run_agent_workforce_returns_safe_response_when_sdk_guardrail_trips(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    payload = _agent_payload("coordenador")
    workforce = AgentWorkforce(
        id=2,
        company_id=7,
        name="Equipe",
        status="active",
        channel="whatsapp",
        root_agent_key="coordenador",
        agent_configs={"coordenador": payload},
        settings={},
        nodes=[],
        edges=[],
        viewport={},
    )

    class QueryStub:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return workforce

    class DBStub:
        def query(self, model):
            return QueryStub()

    async def fake_run_agent_sdk(**kwargs):
        guardrail_result = await kwargs["agent"].input_guardrails[0].run(
            kwargs["agent"],
            kwargs["runner_input"],
            RunContextWrapper(context=kwargs["runtime_context"]),
        )
        raise InputGuardrailTripwireTriggered(guardrail_result)

    logged = {}

    def fake_log_agent_execution(**kwargs):
        logged.update(kwargs)
        return 123

    monkeypatch.setattr(flow_agent_workforce_runner, "_run_agent_sdk", fake_run_agent_sdk)
    monkeypatch.setattr(
        flow_agent_workforce_runner,
        "build_company_openai_run_config",
        lambda db, company_id, tracing_disabled, model_override: object(),
    )
    monkeypatch.setattr(flow_agent_workforce_runner, "_log_agent_execution", fake_log_agent_execution)
    monkeypatch.setattr(flow_agent_workforce_runner, "_record_audio_usage_event", lambda **kwargs: None)
    monkeypatch.setattr(flow_agent_workforce_runner, "ai_credit_block_result_from_balance", lambda **kwargs: None)

    result = run_agent_workforce_response(
        db=DBStub(),
        workforce_id=2,
        company_id=7,
        message="Gere um código Python",
        runtime_variables={"contact_phone": "5500000000001"},
        allow_inactive=True,
    )

    assert result["success"] is True
    assert result["tokens_used"] == 0
    assert result["metadata"]["execution_mode"] == "guardrail_block"
    assert result["metadata"]["guardrail"]["category"] == "off_topic_code_request"
    assert "plataforma" in result["response"]
    assert logged["status"] == "success"


def test_run_agent_workforce_returns_safe_error_when_company_key_is_missing(monkeypatch):
    workforce = AgentWorkforce(
        id=5,
        company_id=12,
        name="Equipe sem chave",
        status="active",
        channel="whatsapp",
        root_agent_key="coordenador",
        agent_configs={"coordenador": _agent_payload("coordenador")},
        settings={},
        nodes=[],
        edges=[],
        viewport={},
    )

    class QueryStub:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return workforce

    class DBStub:
        def query(self, _model):
            return QueryStub()

    def missing_company_key(*_args, **_kwargs):
        raise AIProviderNotConfiguredError(
            "Chave OpenAI não configurada para a empresa ativa"
        )

    logged = {}
    monkeypatch.setattr(
        flow_agent_workforce_runner,
        "ai_credit_block_result_from_balance",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        flow_agent_workforce_runner,
        "build_company_openai_run_config",
        missing_company_key,
    )
    monkeypatch.setattr(
        flow_agent_workforce_runner,
        "_log_agent_execution",
        lambda **kwargs: logged.update(kwargs) or 1,
    )

    result = run_agent_workforce_response(
        db=DBStub(),
        workforce_id=5,
        company_id=12,
        message="Olá",
        allow_inactive=True,
    )

    assert result["success"] is False
    assert result["response"] == ""
    assert result["error"] == "Chave OpenAI não configurada para a empresa ativa"
    assert logged["status"] == "error"
    assert logged["error_message"] == result["error"]


def test_run_agent_workforce_never_persists_or_logs_provider_secret(
    monkeypatch,
    caplog,
):
    workforce = AgentWorkforce(
        id=6,
        company_id=12,
        name="Equipe com falha do provider",
        status="active",
        channel="whatsapp",
        root_agent_key="coordenador",
        agent_configs={"coordenador": _agent_payload("coordenador")},
        settings={},
        nodes=[],
        edges=[],
        viewport={},
    )
    secret = "provider-sensitive-workforce-marker"

    class QueryStub:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return workforce

    class DBStub:
        def query(self, _model):
            return QueryStub()

    def provider_failure(*_args, **_kwargs):
        raise RuntimeError(f"provider rejected bearer {secret}")

    logged = {}
    monkeypatch.setattr(
        flow_agent_workforce_runner,
        "ai_credit_block_result_from_balance",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        flow_agent_workforce_runner,
        "build_company_openai_run_config",
        provider_failure,
    )
    monkeypatch.setattr(
        flow_agent_workforce_runner,
        "_log_agent_execution",
        lambda **kwargs: logged.update(kwargs) or 1,
    )

    result = run_agent_workforce_response(
        db=DBStub(),
        workforce_id=6,
        company_id=12,
        message="Olá",
        allow_inactive=True,
    )

    assert result["success"] is False
    assert result["error"] == "Não foi possível executar a equipe de agentes de IA"
    assert logged["error_message"] == result["error"]
    assert secret not in str(result)
    assert secret not in str(logged)
    assert secret not in caplog.text


def test_voice_override_from_agent_config_requires_enabled_audio_voice():
    payload = _agent_payload("coordenador")
    payload["channel"] = {
        "allow_audio": True,
        "voice": {
            "provider": "elevenlabs",
            "voice_id": "voice_123",
            "label": "Ana",
            "model_id": "eleven_flash_v2_5",
            "output_format": "mp3_44100_128",
        },
    }

    override = _voice_override_from_agent_config(
        AgentCreationConfig.model_validate(payload)
    )

    assert override
    assert override["provider"] == "elevenlabs"
    assert override["voice_id"] == "voice_123"

    payload["channel"]["allow_audio"] = False
    assert _voice_override_from_agent_config(
        AgentCreationConfig.model_validate(payload)
    ) is None

    payload["channel"]["allow_audio"] = True
    payload["channel"]["voice"]["provider"] = "openai"
    assert _voice_override_from_agent_config(
        AgentCreationConfig.model_validate(payload)
    ) is None


def test_agent_audio_trigger_type_no_longer_decides_semantic_user_audio_request():
    assert _agent_audio_trigger_type("me explica por audio como funciona") == "channel_audio_enabled"
    assert _agent_audio_trigger_type("Manda o áudio") == "channel_audio_enabled"
    assert _agent_audio_trigger_type("oi, tudo bem?") == "channel_audio_enabled"


def test_audio_request_tool_marks_runtime_context_semantically():
    context = SimpleNamespace()

    request = record_audio_delivery_request(
        context,
        spoken_text="Plataforma Exemplo se fala assim: Ismaine eiai.",
        reason="usuario pediu para ouvir a pronuncia",
    )

    assert request["trigger_type"] == "audio_requested"
    assert request["delivery_mode"] == "llm_requested_full"
    assert context.audio_delivery_request == request
    assert context.audio_delivery_tool_calls == [request]


def test_compile_workforce_agents_injects_semantic_audio_tool_for_voice_channel():
    payload = _agent_payload("sabrina")
    payload["channel"] = {
        "allow_audio": True,
        "voice": {
            "provider": "elevenlabs",
            "voice_id": "voice_123",
        },
    }

    compiled = _compile_workforce_agents(
        agent_configs={"sabrina": payload},
        root_agent_key="sabrina",
        company_id=7,
    )
    config = compiled.configs_by_key["sabrina"]
    instructions = build_agent_instructions(config)

    assert any(tool.id == "audio.request_response" for tool in config.tools)
    assert any(policy.tool == "audio.request_response" for policy in config.prompt_techniques.tool_policy)
    assert "request_whatsapp_audio_response" in instructions
    assert "Do not depend on exact wording" in instructions


def test_audio_refusal_detection_matches_accented_capability_refusals():
    assert _contains_audio_capability_refusal("Desculpe, não consigo enviar áudio.")
    assert _contains_audio_capability_refusal("Sou apenas um assistente de texto.")
    assert not _contains_audio_capability_refusal("Claro, vou explicar por áudio.")


def test_sanitize_audio_refusal_response_replaces_empty_refusal():
    payload = _agent_payload("sabrina")
    payload["channel"] = {
        "allow_audio": True,
        "voice": {
            "provider": "elevenlabs",
            "voice_id": "voice_123",
            "label": "Ana",
            "model_id": "eleven_flash_v2_5",
            "output_format": "mp3_44100_128",
        },
    }

    sanitized, changed = _sanitize_audio_refusal_response(
        config=AgentCreationConfig.model_validate(payload),
        response_text="Desculpe, não consigo enviar áudio. Posso explicar por texto.",
        user_message="me explica por audio como funciona",
    )

    assert changed
    assert "nao consigo" not in sanitized.lower()
    assert "audio no WhatsApp" in sanitized


def test_sanitize_audio_refusal_response_keeps_useful_remaining_content():
    payload = _agent_payload("sabrina")
    payload["channel"] = {
        "allow_audio": True,
        "voice": {
            "provider": "elevenlabs",
            "voice_id": "voice_123",
        },
    }

    sanitized, changed = _sanitize_audio_refusal_response(
        config=AgentCreationConfig.model_validate(payload),
        response_text=(
            "Não consigo enviar áudio. "
            "O processo funciona em tres etapas: recebemos sua mensagem, "
            "preparamos a resposta e enviamos pelo WhatsApp."
        ),
        user_message="me explica por audio como funciona",
    )

    assert changed
    assert "Não consigo" not in sanitized
    assert "tres etapas" in sanitized


def test_sanitize_false_customer_file_reference_replaces_greeting_without_file_context():
    sanitized, changed = _sanitize_false_customer_file_reference(
        response_text=(
            "Você poderia me informar o que você gostaria de saber "
            "sobre os arquivos que você enviou?"
        ),
        user_message="oi",
        runtime_variables={"trigger": {"body": "oi", "type": "text"}},
    )

    assert changed is True
    assert sanitized == "Olá, tudo bem? Como posso te ajudar?"


def test_sanitize_false_customer_file_reference_keeps_explicit_file_context():
    response = "Posso te explicar os documentos que você enviou."

    sanitized, changed = _sanitize_false_customer_file_reference(
        response_text=response,
        user_message="Enviei um pdf, consegue verificar?",
        runtime_variables={"trigger": {"body": "Enviei um pdf", "type": "text"}},
    )

    assert changed is False
    assert sanitized == response


def test_agent_audio_delivery_plan_skips_short_automatic_response():
    payload = _agent_payload("sabrina")
    payload["channel"] = {
        "allow_audio": True,
        "voice": {
            "provider": "elevenlabs",
            "voice_id": "voice_123",
        },
    }

    plan = _build_agent_audio_delivery_plan(
        config=AgentCreationConfig.model_validate(payload),
        response_text="Perfeito! Qual horario voce prefere?",
        user_message="oi",
    )

    assert plan is None


def test_agent_audio_delivery_plan_uses_split_tail_for_automatic_audio():
    payload = _agent_payload("sabrina")
    payload["channel"] = {
        "allow_audio": True,
        "voice": {
            "provider": "elevenlabs",
            "voice_id": "voice_123",
        },
    }
    response_text = (
        "Ola! Tudo bem? "
        "Vou te explicar de forma objetiva como funciona nossa plataforma. "
        "Primeiro, ela centraliza os contatos que chegam pelo WhatsApp e organiza "
        "cada conversa para o time acompanhar sem perder historico. "
        "Depois, o agente identifica a etapa do atendimento, responde duvidas "
        "frequentes e encaminha quando precisa de uma acao humana. "
        "Por fim, conseguimos acompanhar follow-up, agendamentos e confirmacoes "
        "com mais previsibilidade. Qual parte voce quer ver primeiro?"
    )

    plan = _build_agent_audio_delivery_plan(
        config=AgentCreationConfig.model_validate(payload),
        response_text=response_text,
        user_message="oi",
    )

    assert plan is not None
    assert plan.delivery_mode == "text_then_audio_tail"
    assert plan.trigger_type == "channel_audio_enabled"
    assert plan.text_intro.startswith("Ola! Tudo bem?")
    assert len(plan.request_text) > 180
    assert "Qual parte voce quer ver primeiro?" in plan.request_text


def test_audio_history_metadata_uses_spoken_text_from_tool_request():
    metadata = {
        "audio": {"should_send_audio": True, "delivery_mode": "llm_requested_full"},
        "audio_delivery_request": {
            "spoken_text": "Voce quer que eu envie o link ou prefere agendar uma demonstracao?",
        },
    }

    assert (
        _audio_history_text_from_execution_metadata(metadata)
        == "Voce quer que eu envie o link ou prefere agendar uma demonstracao?"
    )


def test_audio_history_metadata_uses_tail_from_split_parts():
    metadata = {
        "audio": {
            "should_send_audio": True,
            "delivery_mode": "text_then_audio_tail",
            "split_parts": [
                "Voce tem razao em desconfiar.",
                "Quer que eu envie os depoimentos ou prefere agendar uma demonstracao?",
            ],
        },
    }

    assert (
        _audio_history_text_from_execution_metadata(metadata)
        == "Quer que eu envie os depoimentos ou prefere agendar uma demonstracao?"
    )


def test_message_content_for_agent_history_includes_generated_company_audio_text():
    row = SimpleNamespace(
        id=4355,
        message_type="audio",
        from_me=True,
        content="/api/waha/media/audio.oga",
    )

    assert _message_content_for_agent_history(
        row,
        audio_transcripts={4355: "Quer que eu envie os depoimentos?"},
    ) == "[Audio enviada pela empresa: Quer que eu envie os depoimentos?]"


def test_match_audio_history_transcripts_pairs_audio_message_to_nearest_audio_execution():
    base = datetime(2026, 6, 2, 0, 53, 43, tzinfo=timezone.utc)
    audio_message = SimpleNamespace(
        id=4340,
        message_type="audio",
        from_me=True,
        timestamp=base + timedelta(seconds=31),
    )
    text_only_execution = SimpleNamespace(
        id=529,
        created_at=(base + timedelta(seconds=20)).replace(tzinfo=None),
        agent_response="Texto que nao virou audio",
        execution_metadata={},
    )
    audio_execution = SimpleNamespace(
        id=530,
        created_at=base.replace(tzinfo=None),
        agent_response="Resposta completa por audio",
        execution_metadata={
            "audio": {"should_send_audio": True, "delivery_mode": "llm_requested_full"},
            "audio_delivery_request": {
                "spoken_text": "Explicacao do teste gratuito em audio.",
            },
        },
    )

    transcripts = _match_audio_history_transcripts(
        [audio_message],
        [text_only_execution, audio_execution],
    )

    assert transcripts == {4340: "Explicacao do teste gratuito em audio."}


def test_agent_audio_delivery_plan_uses_full_audio_after_prior_audio_offer_acceptance():
    payload = _agent_payload("sabrina")
    payload["channel"] = {
        "allow_audio": True,
        "voice": {
            "provider": "elevenlabs",
            "voice_id": "voice_123",
        },
    }
    response_text = (
        "Perfeito, funciona assim: o teste dura 14 dias corridos. "
        "Eu te envio um link para preencher as informacoes basicas da clinica, "
        "como nome, endereco, tratamentos e regras de comunicacao. "
        "Depois disso a IA ja consegue conversar com os leads, responder duvidas, "
        "fazer follow-up e encaminhar os casos mais quentes para o time. "
        "No final do teste, voce avalia se fez sentido continuar."
    )

    plan = _build_agent_audio_delivery_plan(
        config=AgentCreationConfig.model_validate(payload),
        response_text=response_text,
        user_message="Sim",
        conversation_history=[
            {
                "role": "assistant",
                "content": "Posso te enviar um audio explicando como funciona o teste?",
            }
        ],
    )

    assert plan is not None
    assert plan.delivery_mode == "accepted_audio_offer_full"
    assert plan.trigger_type == "channel_audio_enabled"
    assert plan.text_intro is None
    assert plan.request_text == response_text


def test_agent_audio_delivery_plan_blocks_audio_after_prior_text_offer_acceptance():
    payload = _agent_payload("sabrina")
    payload["channel"] = {
        "allow_audio": True,
        "voice": {
            "provider": "elevenlabs",
            "voice_id": "voice_123",
        },
    }
    response_text = (
        "Claro. O teste dura 14 dias corridos e comeca pelo cadastro das "
        "informacoes basicas da clinica. Depois voce conecta o WhatsApp, "
        "acompanha as conversas no CRM e mede se os leads estao sendo atendidos "
        "com mais velocidade. Se fizer sentido, seguimos para o plano mensal."
    )

    plan = _build_agent_audio_delivery_plan(
        config=AgentCreationConfig.model_validate(payload),
        response_text=response_text,
        user_message="sim",
        conversation_history=[
            {
                "role": "assistant",
                "content": "Se quiser, eu tambem te explico por texto como funciona o teste.",
            }
        ],
    )

    assert plan is None


def test_agent_audio_delivery_plan_blocks_current_text_promise():
    payload = _agent_payload("sabrina")
    payload["channel"] = {
        "allow_audio": True,
        "voice": {
            "provider": "elevenlabs",
            "voice_id": "voice_123",
        },
    }
    response_text = (
        "Claro, por texto fica mais facil: primeiro voce recebe o link de teste, "
        "preenche os dados da clinica, conecta o WhatsApp e acompanha a IA "
        "respondendo os leads. Depois avaliamos os resultados juntos."
    )

    plan = _build_agent_audio_delivery_plan(
        config=AgentCreationConfig.model_validate(payload),
        response_text=response_text,
        user_message="oi",
    )

    assert plan is None


def test_agent_audio_delivery_plan_uses_full_audio_when_response_promises_audio():
    payload = _agent_payload("sabrina")
    payload["channel"] = {
        "allow_audio": True,
        "voice": {
            "provider": "elevenlabs",
            "voice_id": "voice_123",
        },
    }
    response_text = (
        "Vou te explicar em audio como funciona o teste gratuito. "
        "Ele dura 14 dias corridos, comecando pelo cadastro das informacoes "
        "da clinica. Em seguida, a IA conversa com os leads no WhatsApp, "
        "faz follow-up e ajuda o time a priorizar quem tem maior chance de agendar."
    )

    plan = _build_agent_audio_delivery_plan(
        config=AgentCreationConfig.model_validate(payload),
        response_text=response_text,
        user_message="como funciona?",
    )

    assert plan is not None
    assert plan.delivery_mode == "agent_audio_promise_full"
    assert plan.trigger_type == "channel_audio_enabled"
    assert plan.text_intro is None
    assert plan.request_text == response_text


def test_agent_audio_delivery_plan_uses_semantic_tool_request_as_full_response():
    payload = _agent_payload("sabrina")
    payload["channel"] = {
        "allow_audio": True,
        "voice": {
            "provider": "elevenlabs",
            "voice_id": "voice_123",
        },
    }
    response_text = "Claro, vou explicar em audio como funciona."

    plan = _build_agent_audio_delivery_plan(
        config=AgentCreationConfig.model_validate(payload),
        response_text=response_text,
        user_message="grava isso pra eu ouvir",
        audio_delivery_request={
            "trigger_type": "audio_requested",
            "delivery_mode": "llm_requested_full",
            "source": "agent_tool",
        },
    )

    assert plan is not None
    assert plan.delivery_mode == "llm_requested_full"
    assert plan.trigger_type == "audio_requested"
    assert plan.text_intro is None
    assert plan.request_text == response_text


def test_agent_audio_delivery_plan_handles_short_semantic_audio_request():
    payload = _agent_payload("sabrina")
    payload["channel"] = {
        "allow_audio": True,
        "voice": {
            "provider": "elevenlabs",
            "voice_id": "voice_123",
        },
    }
    response_text = "Plataforma Exemplo se fala assim: Ismaine eiaí."

    plan = _build_agent_audio_delivery_plan(
        config=AgentCreationConfig.model_validate(payload),
        response_text=response_text,
        user_message="fala a pronuncia pra mim",
        audio_delivery_request={
            "trigger_type": "audio_requested",
            "delivery_mode": "llm_requested_full",
            "spoken_text": "",
            "source": "agent_tool",
        },
    )

    assert plan is not None
    assert plan.delivery_mode == "llm_requested_full"
    assert plan.trigger_type == "audio_requested"
    assert plan.request_text == response_text


def test_agent_audio_delivery_plan_uses_agent_config_audio_rule_content():
    payload = _agent_payload("sabrina")
    payload["channel"] = {
        "allow_audio": True,
        "voice": {
            "provider": "elevenlabs",
            "voice_id": "voice_123",
        },
    }
    payload["prompt_techniques"] = {
        "instructions": [
            "Pede permissao para enviar um audio explicando o periodo de teste.",
            "Envia o audio explicando o periodo de teste e finaliza com uma pergunta.",
            (
                'Conteudo do audio a ser enviado: "otimo [nome], '
                'o periodo de teste dura 14 dias corridos."'
            ),
        ],
        "conversation_rules": [],
    }

    plan = _build_agent_audio_delivery_plan(
        config=AgentCreationConfig.model_validate(payload),
        response_text="Otimo! Vou te enviar o audio agora.",
        user_message="Sim",
        contact_name="Maria",
    )

    assert plan is not None
    assert plan.delivery_mode == "agent_config_full"
    assert plan.trigger_type == "channel_audio_enabled"
    assert plan.text_intro is None
    assert plan.request_text == "otimo Maria, o periodo de teste dura 14 dias corridos."


def test_agent_audio_delivery_plan_uses_config_content_for_company_audio_placeholder():
    payload = _agent_payload("sabrina")
    payload["channel"] = {
        "allow_audio": True,
        "voice": {
            "provider": "elevenlabs",
            "voice_id": "voice_123",
        },
    }
    payload["prompt_techniques"] = {
        "instructions": [
            "Perguntar se pode enviar um audio explicando como funciona o teste.",
            (
                'Enviar o audio explicando o teste. Conteudo do audio a ser enviado: '
                '"otimo [nome], o periodo de teste dura 14 dias corridos."'
            ),
        ],
        "conversation_rules": [],
    }

    plan = _build_agent_audio_delivery_plan(
        config=AgentCreationConfig.model_validate(payload),
        response_text="[Audio enviada pela empresa]",
        user_message="manda um audio falando",
        contact_name="Maria",
    )

    assert plan is not None
    assert plan.delivery_mode == "agent_config_full"
    assert plan.request_text == "otimo Maria, o periodo de teste dura 14 dias corridos."


def test_agent_audio_delivery_plan_does_not_synthesize_company_audio_placeholder():
    payload = _agent_payload("sabrina")
    payload["channel"] = {
        "allow_audio": True,
        "voice": {
            "provider": "elevenlabs",
            "voice_id": "voice_123",
        },
    }

    plan = _build_agent_audio_delivery_plan(
        config=AgentCreationConfig.model_validate(payload),
        response_text="[Audio enviada pela empresa]",
        user_message="manda um audio falando",
    )

    assert plan is None


def test_agent_audio_delivery_plan_preserves_inner_quotes_in_config_audio_content():
    payload = _agent_payload("sabrina")
    payload["channel"] = {
        "allow_audio": True,
        "voice": {
            "provider": "elevenlabs",
            "voice_id": "voice_123",
        },
    }
    payload["prompt_techniques"] = {
        "instructions": [
            "Envia o audio explicando o periodo de teste quando o lead aceitar.",
            (
                'Conteudo do audio a ser enviado: "otimo [nome], '
                'o periodo de teste dura 14 dias. '
                'Esse valor e essas condicoes estao "ok" pra voce?"'
            ),
        ],
        "conversation_rules": [],
    }

    plan = _build_agent_audio_delivery_plan(
        config=AgentCreationConfig.model_validate(payload),
        response_text="Otimo! Vou te enviar um audio explicando como funciona.",
        user_message="Sim",
        contact_name="Cliente Exemplo",
    )

    assert plan is not None
    assert plan.delivery_mode == "agent_config_full"
    assert 'essas condicoes estao "ok" pra voce?' in plan.request_text
    assert plan.request_text.endswith('"ok" pra voce?')


def test_agent_audio_delivery_plan_waits_for_audio_step_from_agent_config():
    payload = _agent_payload("sabrina")
    payload["channel"] = {
        "allow_audio": True,
        "voice": {
            "provider": "elevenlabs",
            "voice_id": "voice_123",
        },
    }
    payload["prompt_techniques"] = {
        "instructions": [
            "Envia o audio explicando o periodo de teste quando o lead aceitar.",
            'Conteudo do audio a ser enviado: "explicacao do periodo de teste."',
        ],
        "conversation_rules": [],
    }

    plan = _build_agent_audio_delivery_plan(
        config=AgentCreationConfig.model_validate(payload),
        response_text="Perfeito! Posso te explicar como funciona o periodo de teste?",
        user_message="Quero testar",
    )

    assert plan is None


def test_generate_configured_agent_audio_uses_company_id_contract(monkeypatch):
    payload = _agent_payload("sabrina")
    payload["channel"] = {
        "allow_audio": True,
        "voice": {
            "provider": "elevenlabs",
            "voice_id": "voice_123",
            "label": "Ana",
            "model_id": "eleven_flash_v2_5",
            "output_format": "mp3_44100_128",
        },
    }
    captured = {}

    class FakeAudioService:
        def __init__(self, *, db, company_id, voice_config_override):
            captured["service"] = {
                "db": db,
                "company_id": company_id,
                "voice_config_override": voice_config_override,
            }

        async def process_audio_request(self, request):
            captured["request"] = request
            return AudioResponse(
                audio_data=b"audio-bytes",
                should_send_audio=True,
                trigger_detected="audio_requested",
                text_processed=request.text,
            )

    monkeypatch.setattr(
        flow_agent_workforce_runner,
        "AudioService",
        FakeAudioService,
    )
    monkeypatch.setattr(
        flow_agent_workforce_runner,
        "get_ai_credit_balance",
        lambda _db, _company_id: Decimal("1"),
    )

    response = _generate_configured_agent_audio(
        db="db-session",
        company_id=7,
        config=AgentCreationConfig.model_validate(payload),
        response_text="Explicacao por audio",
        user_message="grava isso pra eu ouvir",
        audio_plan=flow_agent_workforce_runner.AgentAudioDeliveryPlan(
            request_text="Explicacao por audio",
            trigger_type="audio_requested",
            delivery_mode="llm_requested_full",
        ),
    )

    assert response
    assert response.should_send_audio
    assert captured["service"]["db"] == "db-session"
    assert captured["service"]["company_id"] == 7
    assert captured["service"]["voice_config_override"]["voice_id"] == "voice_123"
    assert captured["request"].company_id == 7
    assert captured["request"].trigger_type == "audio_requested"
    assert response.provider_used == "elevenlabs"
    assert response.model_used == "eleven_flash_v2_5"
    assert response.voice_used == "voice_123"


def test_generate_configured_agent_audio_preserves_text_when_legacy_allowance_is_exhausted(
    monkeypatch,
):
    payload = _agent_payload("sabrina")
    payload["channel"] = {
        "allow_audio": True,
        "voice": {
            "provider": "elevenlabs",
            "voice_id": "voice_123",
            "model_id": "eleven_flash_v2_5",
        },
    }
    monkeypatch.setattr(
        flow_agent_workforce_runner,
        "get_ai_credit_balance",
        lambda _db, _company_id: Decimal("0"),
    )

    class UnexpectedAudioService:
        def __init__(self, **_kwargs):
            raise AssertionError("TTS should not run after the legacy allowance is exhausted")

    monkeypatch.setattr(flow_agent_workforce_runner, "AudioService", UnexpectedAudioService)

    response = _generate_configured_agent_audio(
        db="db-session",
        company_id=7,
        config=AgentCreationConfig.model_validate(payload),
        response_text="Explicacao por texto",
        user_message="pode mandar em audio?",
        audio_plan=flow_agent_workforce_runner.AgentAudioDeliveryPlan(
            request_text="Explicacao por audio",
            trigger_type="audio_requested",
            delivery_mode="llm_requested_full",
        ),
    )

    assert response is not None
    assert response.should_send_audio is False
    assert response.provider_used == "elevenlabs"
    assert response.error == "Legacy ElevenLabs allowance exhausted"


@pytest.mark.parametrize(
    ("response_text", "request_text"),
    [
        (
            "Esse link é da landing page. Acesse https://app.example.com/login para continuar.",
            "Texto sem link que normalmente poderia virar áudio.",
        ),
        (
            "Segue a explicação por áudio.",
            "Para continuar, acesse https://app.example.com/login.",
        ),
    ],
)
def test_generate_configured_agent_audio_blocks_links_before_tts(
    monkeypatch,
    response_text,
    request_text,
):
    payload = _agent_payload("sabrina")
    payload["channel"] = {
        "allow_audio": True,
        "voice": {
            "provider": "elevenlabs",
            "voice_id": "voice_123",
            "label": "Ana",
            "model_id": "eleven_flash_v2_5",
            "output_format": "mp3_44100_128",
        },
    }

    class UnexpectedAudioService:
        def __init__(self, **_kwargs):
            raise AssertionError("TTS should not be called when text contains a link")

    monkeypatch.setattr(
        flow_agent_workforce_runner,
        "AudioService",
        UnexpectedAudioService,
    )

    response = _generate_configured_agent_audio(
        db="db-session",
        company_id=7,
        config=AgentCreationConfig.model_validate(payload),
        response_text=response_text,
        user_message="pode mandar em audio?",
        audio_plan=flow_agent_workforce_runner.AgentAudioDeliveryPlan(
            request_text=request_text,
            trigger_type="audio_requested",
            delivery_mode="llm_requested_full",
        ),
    )

    assert response is not None
    assert response.should_send_audio is False
    assert response.audio_data is None
    assert response.error == flow_agent_workforce_runner.AUDIO_LINK_BLOCKED_ERROR
    assert response.provider_used == "elevenlabs"
    assert response.model_used == "eleven_flash_v2_5"
    assert response.voice_used == "voice_123"


def test_record_audio_usage_event_skips_link_blocked_audio(monkeypatch):
    calls = []

    monkeypatch.setattr(
        flow_agent_workforce_runner,
        "safe_record_tts_usage",
        lambda **kwargs: calls.append(kwargs),
    )

    flow_agent_workforce_runner._record_audio_usage_event(
        db="db-session",
        company_id=3,
        audio_response=AudioResponse(
            should_send_audio=False,
            error=flow_agent_workforce_runner.AUDIO_LINK_BLOCKED_ERROR,
        ),
        audio_plan=flow_agent_workforce_runner.AgentAudioDeliveryPlan(
            request_text="Acesse https://app.example.com/login para continuar.",
            trigger_type="audio_requested",
            delivery_mode="llm_requested_full",
        ),
        agent_execution_id=574,
        agent_key="empresa_exemplo",
        agent_name="Empresa Exemplo",
        phone="5500000000001",
        conversation_group="group",
        trace_id="trace",
        flow_id=7,
        node_id=None,
    )

    assert calls == []


def test_requested_audio_failure_adds_text_fallback_notice():
    plan = flow_agent_workforce_runner.AgentAudioDeliveryPlan(
        request_text="Claro, vou explicar como funciona.",
        trigger_type="audio_requested",
        delivery_mode="requested_full",
    )
    audio_response = AudioResponse(
        should_send_audio=False,
        error="Audio generation failed",
    )

    text, fallback_used = _apply_requested_audio_failure_text_fallback(
        response_text="Claro, vou explicar como funciona.",
        audio_response=audio_response,
        audio_plan=plan,
    )

    assert fallback_used is True
    assert text.startswith("No momento não consegui te responder em áudio")
    assert "Claro, vou explicar como funciona." in text


def test_automatic_audio_failure_does_not_add_text_fallback_notice():
    plan = flow_agent_workforce_runner.AgentAudioDeliveryPlan(
        request_text="Trecho longo para audio automatico.",
        trigger_type="channel_audio_enabled",
        delivery_mode="text_then_audio_tail",
        text_intro="Oi.",
    )
    audio_response = AudioResponse(
        should_send_audio=False,
        error="Audio generation failed",
    )

    text, fallback_used = _apply_requested_audio_failure_text_fallback(
        response_text="Oi. Trecho longo para audio automatico.",
        audio_response=audio_response,
        audio_plan=plan,
    )

    assert fallback_used is False
    assert text == "Oi. Trecho longo para audio automatico."


def test_compile_workforce_agents_injects_relevant_global_few_shots():
    compiled = _compile_workforce_agents(
        agent_configs={"coordenador": _agent_payload("coordenador")},
        root_agent_key="coordenador",
        latest_user_message="qual o preço?",
        workforce_settings={
            "agent_context": {
                "global_few_shots": {
                    "enabled": True,
                    "examples": [
                        {
                            "title": "Objeção de preço",
                            "tags": "preço, orçamento",
                            "user": "Achei caro",
                            "assistant": "Entendo. Posso te mostrar as opções de pagamento?",
                        },
                        {
                            "title": "Agenda",
                            "tags": "horário",
                            "user": "Tem horário amanhã?",
                            "assistant": "Vou verificar os horários disponíveis.",
                        },
                    ],
                },
                "performance": {"max_global_few_shots": 1},
            }
        },
    )

    examples = compiled.configs_by_key["coordenador"].prompt_techniques.few_shots

    assert len(examples) == 1
    assert examples[0].user == "Achei caro"


def test_compile_workforce_agents_registers_file_search_tool():
    compiled = _compile_workforce_agents(
        agent_configs={"coordenador": _agent_payload("coordenador")},
        root_agent_key="coordenador",
        workforce_settings={
            "agent_context": {
                "knowledge": {
                    "file_search": {
                        "enabled": True,
                        "vector_store_id": "vs_test",
                        "max_num_results": 2,
                    }
                }
            }
        },
    )

    tool_names = [getattr(tool, "name", "") for tool in compiled.root_agent.tools]

    assert "file_search" in tool_names


def test_agent_instructions_treat_file_search_as_internal_knowledge():
    instructions = build_agent_instructions(
        AgentCreationConfig.model_validate(_agent_payload("coordenador"))
    )

    assert "Knowledge files, vector stores, and indexed links are internal company knowledge" in instructions
    assert "never files sent by the lead" in instructions


def test_response_delay_seconds_reads_and_clamps_workforce_performance_setting():
    assert _response_delay_seconds({}) == 15
    assert _response_delay_seconds({
        "agent_context": {
            "performance": {
                "response_delay_seconds": 0,
            }
        }
    }) == 0
    assert _response_delay_seconds({
        "agent_context": {
            "performance": {
                "response_delay_seconds": 12.6,
            }
        }
    }) == 13
    assert _response_delay_seconds({
        "agent_context": {
            "performance": {
                "response_delay_seconds": 999,
            }
        }
    }) == 60
    assert _response_delay_seconds({
        "agent_context": {
            "performance": {
                "response_delay_seconds": "invalido",
            }
        }
    }) == 0


def test_workforce_schedule_defaults_to_always_on():
    schedule = _normalize_workforce_schedule({})

    assert schedule["mode"] == "always_on"
    assert _is_workforce_schedule_open(
        schedule,
        now=datetime(2026, 5, 17, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo")),
    )


def test_custom_workforce_schedule_allows_enabled_period_only():
    schedule = _normalize_workforce_schedule({
        "agent_context": {
            "schedule": {
                "mode": "custom",
                "timezone": "America/Sao_Paulo",
                "days": {
                    "monday": {
                        "enabled": True,
                        "periods": {
                            "morning": {"enabled": True, "start": "09:00", "end": "12:00"},
                            "afternoon": {"enabled": False, "start": "13:00", "end": "18:00"},
                        },
                    }
                },
            }
        }
    })

    assert _is_workforce_schedule_open(
        schedule,
        now=datetime(2026, 5, 18, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo")),
    )
    assert not _is_workforce_schedule_open(
        schedule,
        now=datetime(2026, 5, 18, 13, 0, tzinfo=ZoneInfo("America/Sao_Paulo")),
    )


def test_custom_workforce_schedule_blocks_disabled_day():
    schedule = _normalize_workforce_schedule({
        "agent_context": {
            "schedule": {
                "mode": "custom",
                "timezone": "America/Sao_Paulo",
                "days": {
                    "sunday": {
                        "enabled": False,
                        "periods": {
                            "morning": {"enabled": True, "start": "08:00", "end": "12:00"},
                        },
                    }
                },
            }
        }
    })

    assert not _is_workforce_schedule_open(
        schedule,
        now=datetime(2026, 5, 17, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo")),
    )


def test_compile_workforce_agents_applies_calendar_tool_settings():
    payload = _agent_payload("coordenador")
    payload["tools"] = [
        {
            "id": "calendar.scheduling",
            "enabled": True,
            "settings": {
                "agenda_id": 42,
                "allowed_actions": ["find_slots"],
                "require_confirmation": False,
                "max_suggestions": 4,
            },
        }
    ]

    compiled = _compile_workforce_agents(
        agent_configs={"coordenador": payload},
        root_agent_key="coordenador",
        company_id=1,
    )

    tool_names = [getattr(tool, "name", "") for tool in compiled.root_agent.tools]

    assert tool_names == ["find_available_lead_slots"]
    assert compiled.configs_by_key["coordenador"].tools[0].settings["agenda_id"] == 42
    assert compiled.configs_by_key["coordenador"].tools[0].settings["max_suggestions"] == 4
    assert not compiled.warnings


def test_compile_workforce_agents_passes_google_meet_setting(monkeypatch):
    captured_kwargs = {}

    def fake_calendar_tools(**kwargs):
        captured_kwargs.update(kwargs)
        return []

    monkeypatch.setattr(
        "backend.agents_sdk.tools.calendar_scheduling_tools.create_calendar_scheduling_tools",
        fake_calendar_tools,
    )

    payload = _agent_payload("coordenador")
    payload["tools"] = [
        {
            "id": "calendar.scheduling",
            "enabled": True,
            "settings": {
                "agenda_id": 42,
                "allowed_actions": ["find_slots", "create_appointment"],
                "create_google_meet": True,
            },
        }
    ]

    compiled = _compile_workforce_agents(
        agent_configs={"coordenador": payload},
        root_agent_key="coordenador",
        company_id=1,
    )

    assert captured_kwargs["configured_agenda_id"] == 42
    assert captured_kwargs["create_google_meet"] is True
    assert compiled.configs_by_key["coordenador"].tools[0].settings["create_google_meet"] is True


def test_compile_workforce_agents_hydrates_calendar_settings_from_metadata():
    payload = _agent_payload("coordenador")
    payload["tools"] = [{"id": "calendar.scheduling", "enabled": True}]
    payload["metadata"] = {
        "tool_settings": {
            "calendar.scheduling": {
                "agenda_id": 42,
                "allowed_actions": ["find_slots"],
                "require_confirmation": False,
                "max_suggestions": 2,
            }
        }
    }

    compiled = _compile_workforce_agents(
        agent_configs={"coordenador": payload},
        root_agent_key="coordenador",
        company_id=1,
    )

    tool_names = [getattr(tool, "name", "") for tool in compiled.root_agent.tools]

    assert tool_names == ["find_available_lead_slots"]
    assert compiled.configs_by_key["coordenador"].tools[0].settings["agenda_id"] == 42
    assert compiled.configs_by_key["coordenador"].tools[0].settings["max_suggestions"] == 2


def test_compile_workforce_agents_enables_calendar_management_actions():
    payload = _agent_payload("coordenador")
    payload["tools"] = [
        {
            "id": "calendar.scheduling",
            "enabled": True,
            "settings": {
                "allowed_actions": [
                    "find_slots",
                    "create_appointment",
                    "reschedule_appointment",
                    "cancel_appointment",
                ],
            },
        }
    ]

    compiled = _compile_workforce_agents(
        agent_configs={"coordenador": payload},
        root_agent_key="coordenador",
        company_id=1,
    )

    tool_names = [getattr(tool, "name", "") for tool in compiled.root_agent.tools]

    assert tool_names == [
        "find_available_lead_slots",
        "create_lead_appointment",
        "reschedule_lead_appointment",
        "cancel_lead_appointment",
    ]


def test_compile_workforce_agents_registers_human_handoff_tool():
    payload = _agent_payload("coordenador")
    payload["tools"] = [{"id": "human_handoff.create_task", "enabled": True}]
    payload["metadata"] = {
        "human_handoff_targets": [
            {
                "queue_key": "comercial",
                "queue_name": "Comercial",
                "when": "quando o lead pedir humano",
                "assignment": {"priority": "high", "slaMinutes": 10},
            }
        ]
    }

    compiled = _compile_workforce_agents(
        agent_configs={"coordenador": payload},
        root_agent_key="coordenador",
        company_id=1,
    )

    tool_names = [getattr(tool, "name", "") for tool in compiled.root_agent.tools]
    settings = compiled.configs_by_key["coordenador"].tools[0].settings

    assert tool_names == ["create_human_handoff_task"]
    assert settings["targets"][0]["queue_key"] == "comercial"
    assert not compiled.warnings


def test_compile_workforce_agents_registers_crm_pipeline_tools():
    payload = _agent_payload("coordenador")
    payload["tools"] = [
        {
            "id": "crm.pipeline_stage",
            "enabled": True,
            "settings": {
                "pipeline_id": 10,
                "stage_rules": [
                    {
                        "stage_id": 20,
                        "stage_name": "Qualificado",
                        "advance_rule": "lead confirmou interesse",
                        "recede_rule": "lead voltou a ter duvidas basicas",
                    }
                ],
            },
        }
    ]

    compiled = _compile_workforce_agents(
        agent_configs={"coordenador": payload},
        root_agent_key="coordenador",
        company_id=1,
    )

    tool_names = [getattr(tool, "name", "") for tool in compiled.root_agent.tools]
    settings = compiled.configs_by_key["coordenador"].tools[0].settings

    assert tool_names == ["list_crm_pipeline_stages", "move_lead_crm_stage"]
    assert settings["pipeline_id"] == 10
    assert settings["stage_rules"][0]["stage_id"] == 20
    assert not compiled.warnings


def test_compile_workforce_agents_registers_whatsapp_contact_card_tool():
    payload = _agent_payload("coordenador")
    payload["tools"] = [
        {
            "id": "whatsapp.send_contact_card",
            "enabled": True,
            "settings": {
                "contact_cards": [
                    {
                        "key": "comercial",
                        "full_name": "Cliente Exemplo",
                        "phone_number": "+55 00 00000-0000",
                        "organization": "Empresa Exemplo",
                        "when_to_use": "quando o lead pedir contato comercial",
                    }
                ]
            },
        }
    ]

    compiled = _compile_workforce_agents(
        agent_configs={"coordenador": payload},
        root_agent_key="coordenador",
        company_id=1,
    )

    tool_names = [getattr(tool, "name", "") for tool in compiled.root_agent.tools]
    settings = compiled.configs_by_key["coordenador"].tools[0].settings

    assert tool_names == ["send_whatsapp_contact_card"]
    assert settings["contact_cards"][0]["key"] == "comercial"
    assert not compiled.warnings


def test_compile_workforce_agents_registers_whatsapp_scheduled_followup_tool():
    payload = _agent_payload("coordenador")
    payload["tools"] = [
        {
            "id": "whatsapp.schedule_followup_message",
            "enabled": True,
            "settings": {
                "when_to_use": "quando o lead pedir retorno amanhã com horário",
                "message_instruction": "mensagem curta lembrando do link de teste",
                "replace_existing_pending": False,
            },
        }
    ]

    compiled = _compile_workforce_agents(
        agent_configs={"coordenador": payload},
        root_agent_key="coordenador",
        company_id=1,
    )

    tool_names = [getattr(tool, "name", "") for tool in compiled.root_agent.tools]
    settings = compiled.configs_by_key["coordenador"].tools[0].settings

    assert tool_names == ["schedule_whatsapp_followup_message"]
    assert settings["when_to_use"] == "quando o lead pedir retorno amanhã com horário"
    assert settings["message_instruction"] == "mensagem curta lembrando do link de teste"
    assert settings["replace_existing_pending"] is False
    assert "Configured trigger for this agent" in compiled.root_agent.instructions(None, compiled.root_agent)
    assert not compiled.warnings


def test_build_runner_input_keeps_prior_history_before_current_message():
    runner_input = _build_runner_input(
        "Minha empresa chama Empresa Exemplo",
        [
            {"role": "user", "content": "oi"},
            {"role": "assistant", "content": "Olá! Qual é seu nome?"},
            {"role": "user", "content": "Cliente Exemplo"},
            {"role": "assistant", "content": "Qual o nome da sua empresa?"},
        ],
    )

    assert runner_input == [
        {"role": "user", "content": "oi"},
        {"role": "assistant", "content": "Olá! Qual é seu nome?"},
        {"role": "user", "content": "Cliente Exemplo"},
        {"role": "assistant", "content": "Qual o nome da sua empresa?"},
        {"role": "user", "content": "Minha empresa chama Empresa Exemplo"},
    ]


def test_build_runner_input_supports_openai_multimodal_image_parts():
    runner_input = _build_runner_input(
        "Analise a imagem enviada pelo cliente",
        [{"role": "assistant", "content": "Pode enviar a foto."}],
        image_input_parts=[
            {
                "type": "input_image",
                "image_url": "data:image/png;base64,cG5n",
                "detail": "auto",
            }
        ],
    )

    assert runner_input == [
        {"role": "assistant", "content": "Pode enviar a foto."},
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Analise a imagem enviada pelo cliente"},
                {
                    "type": "input_image",
                    "image_url": "data:image/png;base64,cG5n",
                    "detail": "auto",
                },
            ],
        },
    ]


def test_runtime_image_input_parts_resolve_waha_media_to_data_url(monkeypatch, tmp_path):
    monkeypatch.setenv("WAHA_MEDIA_DIR", str(tmp_path / "waha"))

    image_path = tmp_path / "waha" / "company_7" / "foto.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"png-bytes")

    parts = _runtime_image_input_parts(
        {
            "trigger": {
                "type": "image",
                "mediaUrl": "/api/waha/media/company_7/foto.png",
                "caption": "comprovante",
                "mimetype": "image/png",
            }
        }
    )

    assert len(parts) == 1
    assert parts[0]["type"] == "input_image"
    assert parts[0]["detail"] == "auto"
    assert parts[0]["image_url"].startswith("data:image/png;base64,")
    encoded = parts[0]["image_url"].split(",", 1)[1]
    assert base64.b64decode(encoded) == b"png-bytes"


def test_phone_candidates_support_brazilian_local_and_ddi_formats():
    assert _phone_candidates("00000000001") == ["00000000001", "5500000000001"]
    assert _phone_candidates("5500000000001") == ["5500000000001", "00000000001"]


def test_preview_treats_registered_product_tools_as_available():
    payload = _agent_payload("coordenador")
    payload["tools"] = [
        {"id": "calendar.scheduling", "enabled": True},
        {"id": "human_handoff.create_task", "enabled": True},
        {"id": "crm.pipeline_stage", "enabled": True},
        {
            "id": "whatsapp.send_contact_card",
            "enabled": True,
            "settings": {
                "contact_cards": [
                    {
                        "key": "comercial",
                        "full_name": "Cliente Exemplo",
                        "phone_number": "+55 00 00000-0000",
                    }
                ]
            },
        },
        {
            "id": "whatsapp.schedule_followup_message",
            "enabled": True,
            "settings": {
                "when_to_use": "quando combinar teste futuro",
                "message_instruction": "lembrar o lead do link combinado",
            },
        },
    ]
    payload["metadata"] = {
        "human_handoff_targets": [
            {
                "queue_key": "comercial",
                "queue_name": "Comercial",
                "when": "quando precisar de humano",
            }
        ]
    }

    preview = compile_agent_preview(AgentCreationConfig.model_validate(payload))

    assert preview["warnings"] == []
    assert "pass queue_key=`comercial`" in preview["instructions"]
    assert "move_lead_crm_stage" in preview["instructions"]
    assert "send_whatsapp_contact_card" in preview["instructions"]
    assert "contact_key=`comercial`" in preview["instructions"]
    assert "schedule_whatsapp_followup_message" in preview["instructions"]
    assert "quando combinar teste futuro" in preview["instructions"]
    assert "lembrar o lead do link combinado" in preview["instructions"]


def test_human_handoff_policy_marks_silent_queue():
    payload = _agent_payload("coordenador")
    payload["tools"] = [{"id": "human_handoff.create_task", "enabled": True}]
    payload["metadata"] = {
        "human_handoff_targets": [
            {
                "queue_key": "suporte",
                "queue_name": "Suporte",
                "when": "quando precisar de humano",
                "assignment": {"silentTransfer": True},
            }
        ]
    }

    instructions = build_agent_instructions(AgentCreationConfig.model_validate(payload))

    assert "This queue is silent" in instructions
    assert "do not send a final message" in instructions


def test_debounced_messages_are_removed_from_recent_history():
    history = [
        {"role": "user", "content": "oi"},
        {"role": "assistant", "content": "Olá!"},
        {"role": "user", "content": "quero preço"},
        {"role": "user", "content": "e agenda amanhã"},
    ]

    trimmed = flow_agent_workforce_runner._drop_debounced_messages_from_history(
        history,
        ["quero preço", "e agenda amanhã"],
    )

    assert trimmed == [
        {"role": "user", "content": "oi"},
        {"role": "assistant", "content": "Olá!"},
    ]


def test_calendar_tool_policy_instructs_availability_lookup_and_runtime_now():
    payload = _agent_payload("coordenador")
    payload["channel"] = {"business_timezone": "America/Sao_Paulo"}
    payload["tools"] = [
        {
            "id": "calendar.scheduling",
            "enabled": True,
            "settings": {"max_suggestions": 4},
        }
    ]

    instructions = build_agent_instructions(AgentCreationConfig.model_validate(payload))

    assert "Current local date/time:" in instructions
    assert "Use `find_available_lead_slots` before answering availability questions" in instructions
    assert "offer up to 4 exact options" in instructions
    assert "next_available_slots" in instructions
    assert "appointment_display" in instructions
    assert "relative_day" in instructions
    assert "do not call it hoje/amanha/depois de amanha" in instructions
    assert "never claim that the agenda is unstable" in instructions
    assert "do not create a human handoff merely because of that lookup" in instructions


def _calendar_tool_call(name: str, call_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="tool_call_item",
        raw_item=SimpleNamespace(name=name, call_id=call_id),
        agent=SimpleNamespace(name="Agente"),
    )


def _calendar_tool_output(call_id: str, payload: dict) -> SimpleNamespace:
    serialized = json.dumps(payload)
    return SimpleNamespace(
        type="tool_call_output_item",
        raw_item={"call_id": call_id, "output": serialized},
        output=serialized,
        agent=SimpleNamespace(name="Agente"),
    )


def _calendar_events(*items: SimpleNamespace) -> list[dict]:
    return flow_agent_workforce_runner._calendar_tool_events(
        SimpleNamespace(new_items=list(items))
    )


def test_calendar_availability_replaces_false_instability_with_real_slots():
    events = _calendar_events(
        _calendar_tool_call("find_available_lead_slots", "lookup-1"),
        _calendar_tool_output(
            "lookup-1",
            {
                "success": True,
                "max_suggestions": 2,
                "slots": [
                    {"display": "30/07/2026 às 11:00"},
                    {"display": "30/07/2026 às 14:00"},
                    {"display": "30/07/2026 às 15:00"},
                ],
                "next_available_slots": [],
            },
        ),
    )

    response, repaired, reason = (
        flow_agent_workforce_runner._enforce_calendar_availability_response(
            response_text="A agenda está instável. Tento novamente depois.",
            calendar_tool_events=events,
        )
    )

    assert repaired is True
    assert reason == "successful_lookup_reported_as_failure"
    assert "1. 30/07/2026 às 11:00" in response
    assert "2. 30/07/2026 às 14:00" in response
    assert "15:00" not in response
    assert "instável" not in response
    assert flow_agent_workforce_runner._calendar_tool_result_summaries(events) == [
        {
            "tool_name": "find_available_lead_slots",
            "success": True,
            "error": None,
            "slot_count": 3,
            "next_slot_count": 0,
        }
    ]


def test_calendar_availability_preserves_response_with_returned_slot():
    events = _calendar_events(
        _calendar_tool_call("find_available_lead_slots", "lookup-2"),
        _calendar_tool_output(
            "lookup-2",
            {
                "success": True,
                "slots": [{"display": "30/07/2026 às 11:00"}],
                "next_available_slots": [],
            },
        ),
    )
    original = "Tenho 30/07/2026 às 11:00. Esse horário funciona para você?"

    response, repaired, reason = (
        flow_agent_workforce_runner._enforce_calendar_availability_response(
            response_text=original,
            calendar_tool_events=events,
        )
    )

    assert response == original
    assert repaired is False
    assert reason is None


def test_calendar_availability_offers_next_slots_for_requested_period():
    events = _calendar_events(
        _calendar_tool_call("find_available_lead_slots", "lookup-3"),
        _calendar_tool_output(
            "lookup-3",
            {
                "success": True,
                "max_suggestions": 3,
                "slots": [],
                "next_available_slots": [
                    {"display": "31/07/2026 às 10:00"},
                    {"display": "31/07/2026 às 10:30"},
                ],
            },
        ),
    )

    response, repaired, reason = (
        flow_agent_workforce_runner._enforce_calendar_availability_response(
            response_text="Você prefere manhã ou tarde?",
            calendar_tool_events=events,
        )
    )

    assert repaired is True
    assert reason == "successful_lookup_slots_missing_from_response"
    assert "Não encontrei horários no período solicitado" in response
    assert "31/07/2026 às 10:00" in response
    assert "31/07/2026 às 10:30" in response


def test_calendar_availability_preserves_real_tool_failure():
    events = _calendar_events(
        _calendar_tool_call("find_available_lead_slots", "lookup-4"),
        _calendar_tool_output(
            "lookup-4",
            {
                "success": False,
                "error": "internal_error",
                "details": "sensitive diagnostic detail",
            },
        ),
    )
    original = "A agenda está instável. Posso tentar novamente em alguns minutos."

    response, repaired, reason = (
        flow_agent_workforce_runner._enforce_calendar_availability_response(
            response_text=original,
            calendar_tool_events=events,
        )
    )

    assert response == original
    assert repaired is False
    assert reason is None
    assert flow_agent_workforce_runner._calendar_tool_result_summaries(events) == [
        {
            "tool_name": "find_available_lead_slots",
            "success": False,
            "error": "internal_error",
            "slot_count": 0,
            "next_slot_count": 0,
        }
    ]


def test_calendar_availability_does_not_override_subsequent_appointment_creation():
    events = _calendar_events(
        _calendar_tool_call("find_available_lead_slots", "lookup-5"),
        _calendar_tool_output(
            "lookup-5",
            {
                "success": True,
                "slots": [{"display": "30/07/2026 às 11:00"}],
                "next_available_slots": [],
            },
        ),
        _calendar_tool_call("create_lead_appointment", "create-1"),
        _calendar_tool_output(
            "create-1",
            {
                "success": True,
                "appointment_display": "30/07/2026 às 11:00",
            },
        ),
    )
    original = "Perfeito, ficou agendado para 30/07/2026 às 11:00."

    response, repaired, reason = (
        flow_agent_workforce_runner._enforce_calendar_availability_response(
            response_text=original,
            calendar_tool_events=events,
        )
    )

    assert response == original
    assert repaired is False
    assert reason is None


def test_agent_instructions_avoid_long_dashes():
    instructions = build_agent_instructions(
        AgentCreationConfig.model_validate(_agent_payload("coordenador"))
    )

    assert "Do not use em dashes or en dashes" in instructions


def test_agent_response_punctuation_sanitizer_removes_long_dashes():
    sanitized, changed = _sanitize_agent_response_punctuation(
        "Claro — consigo te ajudar no horario 10–11."
    )

    assert changed is True
    assert "—" not in sanitized
    assert "–" not in sanitized
    assert sanitized == "Claro, consigo te ajudar no horario 10-11."


def test_whatsapp_markdown_link_sanitizer_collapses_duplicate_url():
    sanitized, changed = _sanitize_whatsapp_markdown_links(
        "O link para agendamento é: [https://agenda.example.com/servico](https://agenda.example.com/servico).",
        channel="whatsapp",
    )

    assert changed is True
    assert (
        sanitized
        == "O link para agendamento é: https://agenda.example.com/servico."
    )


def test_whatsapp_markdown_link_sanitizer_keeps_label_with_url():
    sanitized, changed = _sanitize_whatsapp_markdown_links(
        "Vou te enviar o link: [Link de Agendamento](https://agenda.example.com/localizacao/).",
        channel="whatsapp",
    )

    assert changed is True
    assert (
        sanitized
        == "Vou te enviar o link: Link de Agendamento: https://agenda.example.com/localizacao/."
    )


def test_whatsapp_markdown_link_sanitizer_preserves_plain_urls_and_other_channels():
    plain_text = "Link da reunião: https://meet.google.com/jcd-savy-ohb"
    markdown_text = "Veja aqui: [Link](https://example.com/agendar)."

    assert _sanitize_whatsapp_markdown_links(plain_text, channel="whatsapp") == (
        plain_text,
        False,
    )
    assert _sanitize_whatsapp_markdown_links(markdown_text, channel="email") == (
        markdown_text,
        False,
    )


def test_google_calendar_summary_uses_meeting_prefix():
    assert (
        _build_google_event_summary(SimpleNamespace(nome="Maria Silva"))
        == "Reunião | Maria Silva"
    )
    assert _build_google_event_summary(SimpleNamespace(nome="  ")) == "Reunião | Cliente"


def test_calendar_tool_policy_instructs_google_meet_link_when_enabled():
    payload = _agent_payload("coordenador")
    payload["tools"] = [
        {
            "id": "calendar.scheduling",
            "enabled": True,
            "settings": {"create_google_meet": True},
        }
    ]

    instructions = build_agent_instructions(AgentCreationConfig.model_validate(payload))

    assert "Google Meet" in instructions
    assert "`meeting_link`" in instructions
    assert "Do not invent or promise a meeting link" in instructions


def test_extract_google_meeting_link_prefers_video_entry_point():
    event = {
        "conferenceData": {
            "entryPoints": [
                {"entryPointType": "phone", "uri": "tel:+550000000013"},
                {"entryPointType": "video", "uri": "https://meet.google.com/abc-defg-hij"},
            ]
        }
    }

    assert extract_google_meeting_link(event) == "https://meet.google.com/abc-defg-hij"
