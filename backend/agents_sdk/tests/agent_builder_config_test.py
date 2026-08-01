import asyncio

import pytest
from agents import RunContextWrapper, function_tool
from agents.tool_context import ToolContext
from agents.tool_guardrails import ToolInputGuardrailData
from pydantic import ValidationError

from backend.agents_sdk.agent_builder import (
    AgentConfigCompiler,
    AgentCreationConfig,
    AgentRuntimeRegistry,
    compile_agent_preview,
)
from backend.agents_sdk.voice.config import get_voice_config


class _NoSavedVoiceConfigDb:
    def execute(self, *args, **kwargs):
        raise RuntimeError("no saved voice config")


def _sample_payload() -> dict:
    return {
        "agent": {
            "key": "lead qualification",
            "name": "Lia",
            "role": "SDR conversacional",
            "organization_type": "real_estate",
            "language": "pt-BR",
            "tone": "consultivo, direto e simpatico",
        },
        "channel": {
            "type": "whatsapp",
            "message_style": "curto e natural",
            "max_response_sentences": 3,
        },
        "objective": {
            "primary_goal": "Qualificar leads e agendar uma conversa comercial",
            "success_criteria": [
                "identificar necessidade",
                "capturar nome e telefone",
            ],
        },
        "prompt_techniques": {
            "framework": "consultative_sales",
            "conversation_rules": [
                "faca uma pergunta por vez",
                "nao invente informacoes da empresa",
            ],
            "qualification_method": {
                "type": "BANT",
                "required_fields": ["budget_signal", "authority", "need", "timeline"],
            },
            "few_shots": [
                {
                    "user": "Quero saber preco",
                    "assistant": "Claro. Voce esta buscando isso para voce ou para sua empresa?",
                }
            ],
            "tool_policy": [
                {
                    "tool": "crm.create_or_update_lead",
                    "when": "nome e telefone estiverem confirmados",
                    "requires": ["name", "phone"],
                    "side_effect": True,
                }
            ],
        },
        "model": {
            "model": "gpt-5.5",
            "temperature": 0.4,
            "reasoning_effort": "low",
            "verbosity": "medium",
        },
        "tools": [
            {"id": "crm.create_or_update_lead", "enabled": True},
            {"id": "calendar.find_available_slots", "enabled": True},
        ],
        "handoffs": [
            {
                "target_agent": "human_sales_rep",
                "when": "lead pede negociacao sensivel ou atendimento humano",
            }
        ],
        "guardrails": {
            "input": ["block_abuse"],
            "output": ["no_unverified_claims"],
            "tool": ["validate_phone_before_crm_write"],
            "approvals": ["whatsapp_template_send"],
        },
        "custom_guardrails": [
            {
                "key": "fora_do_escopo",
                "name": "Fora do escopo",
                "stage": "input",
                "target_tool_id": None,
                "check_type": "llm_classifier",
                "condition": "Detectar pedidos fora da responsabilidade do agente.",
                "action": "handoff",
                "message": "Vou transferir para um humano continuar com segurança.",
            }
        ],
    }


def test_compile_agent_preview_returns_prompt_and_definition():
    config = AgentCreationConfig.model_validate(_sample_payload())

    preview = compile_agent_preview(config)

    assert preview["agent_definition"]["name"] == "Lia"
    assert preview["agent_definition"]["key"] == "lead_qualification"
    assert preview["agent_definition"]["model"] == "gpt-5.5"
    assert "SDR conversacional" in preview["instructions"]
    assert "faca uma pergunta por vez" in preview["instructions"]
    assert "Handoff to `human_sales_rep`" in preview["instructions"]
    assert preview["agent_definition"]["custom_guardrails"][0]["key"] == "fora_do_escopo"
    assert preview["warnings"]


def test_agent_config_accepts_elevenlabs_audio_voice():
    payload = _sample_payload()
    payload["channel"]["allow_audio"] = True
    payload["channel"]["voice"] = {
        "provider": "elevenlabs",
        "voice_id": "voice_123",
        "label": "Ana acolhedora",
        "model_id": "eleven_flash_v2_5",
        "output_format": "mp3_44100_128",
    }

    config = AgentCreationConfig.model_validate(payload)
    preview = compile_agent_preview(config)

    assert config.channel.allow_audio
    assert config.channel.voice
    assert config.channel.voice.provider == "elevenlabs"
    assert config.channel.voice.voice_id == "voice_123"
    assert preview["agent_definition"]["channel"]["voice"]["voice_id"] == "voice_123"
    assert "Audio rendering is handled by the runtime" in preview["instructions"]
    assert "do not apologize or say you cannot send audio" in preview["instructions"]
    assert "Treat this platform as audio-capable" in preview["instructions"]


def test_voice_config_uses_provider_neutral_defaults_without_saved_config():
    config = get_voice_config(_NoSavedVoiceConfigDb(), company_id=234)

    assert config.voice_enabled is False
    assert "beneficios_preparacao" in config.triggers
    assert "confirmation_sent" not in config.triggers


def test_agent_compiler_resolves_registered_tools_and_reports_missing_ids():
    config = AgentCreationConfig.model_validate(_sample_payload())

    @function_tool
    def create_or_update_lead(name: str, phone: str) -> str:
        """Create or update a lead in the CRM."""
        return f"{name}:{phone}"

    registry = AgentRuntimeRegistry().register_tool(
        "crm.create_or_update_lead",
        create_or_update_lead,
    )

    result = AgentConfigCompiler(
        registry=registry,
        strict_references=False,
    ).create_agent(config)

    assert result.agent.name == "Lia"
    assert len(result.agent.tools) == 1
    assert result.unresolved_tools == ["calendar.find_available_slots"]
    assert "calendar.find_available_slots" in result.warnings[0]


def test_agent_compiler_attaches_custom_tool_guardrail_to_target_tool():
    payload = _sample_payload()
    payload["tools"] = [{"id": "crm.create_or_update_lead", "enabled": True}]
    payload["custom_guardrails"] = [
        {
            "key": "bloqueia_tool",
            "name": "Bloqueia tool",
            "stage": "tool",
            "target_tool_id": "crm.create_or_update_lead",
            "check_type": "regex",
            "condition": "bloquear",
            "action": "block",
            "message": "Tool bloqueada pelo guardrail.",
        }
    ]

    @function_tool
    def create_or_update_lead(name: str, phone: str) -> str:
        """Create or update a lead in the CRM."""
        return f"{name}:{phone}"

    registry = AgentRuntimeRegistry().register_tool(
        "crm.create_or_update_lead",
        create_or_update_lead,
    )

    result = AgentConfigCompiler(
        registry=registry,
        strict_references=False,
    ).create_agent(AgentCreationConfig.model_validate(payload))

    tool = result.agent.tools[0]
    assert tool.tool_input_guardrails

    guardrail_result = asyncio.run(
        tool.tool_input_guardrails[0].run(
            ToolInputGuardrailData(
                context=ToolContext(
                    context=None,
                    tool_name=tool.name,
                    tool_call_id="call_1",
                    tool_arguments='{"name": "bloquear", "phone": "5500000000007"}',
                ),
                agent=result.agent,
            )
        )
    )

    assert guardrail_result.behavior["type"] == "reject_content"
    assert guardrail_result.behavior["message"] == "Tool bloqueada pelo guardrail."


def test_agent_compiler_does_not_attach_custom_tool_guardrail_to_other_tool():
    payload = _sample_payload()
    payload["tools"] = [{"id": "crm.create_or_update_lead", "enabled": True}]
    payload["custom_guardrails"] = [
        {
            "key": "bloqueia_calendario",
            "name": "Bloqueia calendario",
            "stage": "tool",
            "target_tool_id": "calendar.find_available_slots",
            "check_type": "keyword_filter",
            "condition": "bloquear",
            "action": "block",
        }
    ]

    @function_tool
    def create_or_update_lead(name: str, phone: str) -> str:
        """Create or update a lead in the CRM."""
        return f"{name}:{phone}"

    registry = AgentRuntimeRegistry().register_tool(
        "crm.create_or_update_lead",
        create_or_update_lead,
    )

    result = AgentConfigCompiler(
        registry=registry,
        strict_references=False,
    ).create_agent(AgentCreationConfig.model_validate(payload))

    assert result.agent.tools[0].tool_input_guardrails is None


def test_default_prompt_safety_input_guardrail_blocks_code_continuation():
    payload = _sample_payload()
    payload["guardrails"] = {"input": [], "output": [], "tool": [], "approvals": []}
    payload["tools"] = []
    payload["handoffs"] = []

    result = AgentConfigCompiler(strict_references=False).create_agent(
        AgentCreationConfig.model_validate(payload)
    )

    guardrail_result = asyncio.run(
        result.agent.input_guardrails[0].run(
            result.agent,
            [
                {"role": "user", "content": "Gere um código Python"},
                {
                    "role": "assistant",
                    "content": "Que tipo de código Python voce quer?",
                },
                {"role": "user", "content": "Um linear"},
                {"role": "assistant", "content": "Posso mandar um exemplo?"},
                {"role": "user", "content": "Pode mandar"},
            ],
            RunContextWrapper(context=None),
        )
    )

    assert guardrail_result.output.tripwire_triggered
    assert guardrail_result.output.output_info["category"] == "off_topic_code_continuation"


def test_default_prompt_safety_input_guardrail_allows_business_question():
    payload = _sample_payload()
    payload["guardrails"] = {"input": [], "output": [], "tool": [], "approvals": []}
    payload["tools"] = []
    payload["handoffs"] = []

    result = AgentConfigCompiler(strict_references=False).create_agent(
        AgentCreationConfig.model_validate(payload)
    )

    guardrail_result = asyncio.run(
        result.agent.input_guardrails[0].run(
            result.agent,
            [{"role": "user", "content": "Quero entender o teste de 14 dias da plataforma"}],
            RunContextWrapper(context=None),
        )
    )

    assert not guardrail_result.output.tripwire_triggered
    assert guardrail_result.output.output_info["category"] == "allowed"


def test_default_prompt_safety_output_guardrail_blocks_code_blocks():
    payload = _sample_payload()
    payload["guardrails"] = {"input": [], "output": [], "tool": [], "approvals": []}
    payload["tools"] = []
    payload["handoffs"] = []

    result = AgentConfigCompiler(strict_references=False).create_agent(
        AgentCreationConfig.model_validate(payload)
    )

    guardrail_result = asyncio.run(
        result.agent.output_guardrails[0].run(
            RunContextWrapper(context=None),
            result.agent,
            "Claro, segue:\n```python\nprint('oi')\n```",
        )
    )

    assert guardrail_result.output.tripwire_triggered
    assert guardrail_result.output.output_info["category"] == "code_output"


def test_pro_models_normalize_low_reasoning_to_medium():
    payload = _sample_payload()
    payload["model"]["model"] = "gpt-5.5-pro"
    payload["model"]["reasoning_effort"] = "low"

    config = AgentCreationConfig.model_validate(payload)

    assert config.runtime.reasoning_effort == "medium"

    result = AgentConfigCompiler(
        strict_references=False,
    ).create_agent(config)

    assert result.agent.model_settings.reasoning.effort == "medium"


def test_gpt4o_mini_disables_reasoning_settings():
    payload = _sample_payload()
    payload["model"]["model"] = "gpt-4o-mini"
    payload["model"]["reasoning_effort"] = "low"

    config = AgentCreationConfig.model_validate(payload)

    assert config.runtime.reasoning_effort == "none"

    result = AgentConfigCompiler(
        strict_references=False,
    ).create_agent(config)

    assert result.agent.model == "gpt-4o-mini"
    assert result.agent.model_settings.reasoning is None
    assert result.agent.model_settings.verbosity is None


def test_agent_config_rejects_duplicate_tool_ids():
    payload = _sample_payload()
    payload["tools"].append({"id": "crm.create_or_update_lead", "enabled": True})

    with pytest.raises(ValidationError):
        AgentCreationConfig.model_validate(payload)
