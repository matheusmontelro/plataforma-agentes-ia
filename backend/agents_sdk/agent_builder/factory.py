"""
Compiler from frontend agent config to OpenAI Agents SDK objects.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agents import (
    Agent,
    FunctionTool,
    GuardrailFunctionOutput,
    ModelSettings,
    ToolInputGuardrail,
    input_guardrail,
    output_guardrail,
)
from agents.model_settings import Reasoning
from agents.tool_guardrails import ToolGuardrailFunctionOutput, ToolInputGuardrailData

from .prompt_compiler import build_agent_instructions, create_dynamic_instructions
from .schemas import AgentCreationConfig, CustomGuardrailConfig, ToolSelectionConfig


logger = logging.getLogger(__name__)

SUPPORTED_CUSTOM_GUARDRAIL_CHECK_TYPES = {"regex", "keyword_filter"}
DEFAULT_PROMPT_SAFETY_BLOCK_MESSAGE = (
    "Consigo ajudar com duvidas sobre a plataforma, informacoes comerciais "
    "ou agendar uma demonstracao. Qual desses assuntos voce quer tratar?"
)
DEFAULT_PROMPT_SAFETY_OUTPUT_MESSAGE = (
    "Para manter a conversa segura e dentro do atendimento, vou voltar ao que importa: "
    "posso ajudar com duvidas sobre a plataforma ou agendar uma demonstracao."
)
_PROMPT_INJECTION_PATTERNS = (
    r"\b(ignore|ignora|desconsidere|desconsidera)\b.{0,90}\b(instrucoes|mensagens|prompt|system|developer|anteriores|acima)\b",
    r"\b(revele|mostre|exiba|vaze|exponha)\b.{0,90}\b(prompt|instrucoes|system|developer|politica|regras internas)\b",
    r"\b(jailbreak|modo desenvolvedor|developer mode|system prompt|prompt interno|instrucoes internas|chain of thought|raciocinio oculto)\b",
)
_OFF_TOPIC_CODE_PATTERNS = (
    r"\b(gere|gerar|crie|criar|escreva|faca|me de|mande|mandar)\b.{0,90}\b(codigo|script|programa)\b",
    r"\b(codigo|script|programa)\b.{0,90}\b(python|javascript|typescript|java|node|react|sql|scikit|sklearn)\b",
    r"\b(regressao linear|linear regression|machine learning|sklearn|scikit|numpy|pandas)\b",
)
_SHORT_CONTINUATION_PATTERNS = (
    r"^(sim|s|ok|pode|pode mandar|manda|mande|quero|isso|isso mesmo|claro|bora|vai)[\s.!?]*$",
)
_OUTPUT_CODE_PATTERNS = (
    r"```",
    r"(?mi)^\s*(from\s+[a-zA-Z0-9_.]+\s+import|import\s+[a-zA-Z0-9_.]+|def\s+[a-zA-Z_]\w*\(|class\s+[a-zA-Z_]\w*)",
    r"\b(LinearRegression|sklearn|scikit-learn|numpy|pandas)\b",
)
_OUTPUT_SECRET_PATTERNS = (
    r"\b(instrucoes internas|prompt interno|system prompt|developer message|hidden policy|chain of thought)\b",
)


class AgentReferenceError(ValueError):
    """Raised when config references tools, handoffs, or guardrails not registered."""


@dataclass
class AgentRuntimeRegistry:
    """
    Backend-owned registry for safe references selected by the frontend.

    The UI should send IDs only. Actual tool functions, handoff agents, and
    guardrail implementations stay in the backend.
    """

    tools: dict[str, Any] = field(default_factory=dict)
    tool_factories: dict[str, Callable[[ToolSelectionConfig], Any]] = field(
        default_factory=dict
    )
    handoffs: dict[str, Any] = field(default_factory=dict)
    input_guardrails: dict[str, Any] = field(default_factory=dict)
    output_guardrails: dict[str, Any] = field(default_factory=dict)
    tool_guardrails: dict[str, Any] = field(default_factory=dict)

    def register_tool(self, tool_id: str, tool: Any) -> "AgentRuntimeRegistry":
        self.tools[tool_id] = tool
        return self

    def register_tool_factory(
        self,
        tool_id: str,
        factory: Callable[[ToolSelectionConfig], Any],
    ) -> "AgentRuntimeRegistry":
        self.tool_factories[tool_id] = factory
        return self

    def register_handoff(self, agent_id: str, handoff_agent: Any) -> "AgentRuntimeRegistry":
        self.handoffs[agent_id] = handoff_agent
        return self

    def register_input_guardrail(
        self,
        guardrail_id: str,
        guardrail: Any,
    ) -> "AgentRuntimeRegistry":
        self.input_guardrails[guardrail_id] = guardrail
        return self

    def register_output_guardrail(
        self,
        guardrail_id: str,
        guardrail: Any,
    ) -> "AgentRuntimeRegistry":
        self.output_guardrails[guardrail_id] = guardrail
        return self

    def register_tool_guardrail(
        self,
        guardrail_id: str,
        guardrail: Any,
    ) -> "AgentRuntimeRegistry":
        self.tool_guardrails[guardrail_id] = guardrail
        return self


@dataclass
class AgentBuildResult:
    """Result of compiling a frontend config."""

    agent: Agent[Any]
    instructions_preview: str
    unresolved_tools: list[str] = field(default_factory=list)
    unresolved_handoffs: list[str] = field(default_factory=list)
    unresolved_guardrails: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def warnings(self) -> list[str]:
        warnings: list[str] = []
        if self.unresolved_tools:
            warnings.append(f"Unresolved tool ids: {', '.join(self.unresolved_tools)}")
        if self.unresolved_handoffs:
            warnings.append(
                f"Unresolved handoff ids: {', '.join(self.unresolved_handoffs)}"
            )
        if self.unresolved_guardrails:
            warnings.append(
                f"Unresolved guardrail ids: {', '.join(self.unresolved_guardrails)}"
            )
        return warnings


class AgentConfigCompiler:
    """Build OpenAI Agents SDK definitions from frontend config."""

    def __init__(
        self,
        registry: AgentRuntimeRegistry | None = None,
        *,
        strict_references: bool = True,
    ) -> None:
        self.registry = registry or AgentRuntimeRegistry()
        self.strict_references = strict_references

    def create_agent(self, config: AgentCreationConfig) -> AgentBuildResult:
        tools, unresolved_tools = self._resolve_tools(config)
        handoffs, unresolved_handoffs = self._resolve_handoffs(config)
        input_guardrails, unresolved_input_guardrails = self._resolve_guardrails(
            config.guardrails.input,
            self.registry.input_guardrails,
        )
        output_guardrails, unresolved_output_guardrails = self._resolve_guardrails(
            config.guardrails.output,
            self.registry.output_guardrails,
        )
        if _default_prompt_safety_enabled(config):
            input_guardrails = [
                _build_default_prompt_safety_input_guardrail(),
                *input_guardrails,
            ]
            output_guardrails = [
                _build_default_prompt_safety_output_guardrail(),
                *output_guardrails,
            ]

        unresolved_guardrails = unresolved_input_guardrails + unresolved_output_guardrails
        self._raise_if_strict(
            unresolved_tools=unresolved_tools,
            unresolved_handoffs=unresolved_handoffs,
            unresolved_guardrails=unresolved_guardrails,
        )

        prompt = _build_stored_prompt(config)
        instructions = None if prompt else create_dynamic_instructions(config)

        agent = Agent(
            name=config.agent.name,
            handoff_description=config.agent.handoff_description or config.agent.role,
            instructions=instructions,
            prompt=prompt,
            model=config.runtime.model,
            model_settings=_build_model_settings(config),
            tools=tools,
            handoffs=handoffs,
            input_guardrails=input_guardrails,
            output_guardrails=output_guardrails,
        )

        return AgentBuildResult(
            agent=agent,
            instructions_preview=build_agent_instructions(config),
            unresolved_tools=unresolved_tools,
            unresolved_handoffs=unresolved_handoffs,
            unresolved_guardrails=unresolved_guardrails,
            metadata={
                "agent_key": config.agent.key,
                "schema_version": config.schema_version,
                "model": config.runtime.model,
                "stored_prompt": bool(prompt),
                "max_turns": config.runtime.max_turns,
                "tool_guardrails": config.guardrails.tool,
                "approvals": config.guardrails.approvals,
                "default_prompt_safety": _default_prompt_safety_enabled(config),
                "custom_guardrails": [
                    guardrail.model_dump(by_alias=True)
                    for guardrail in config.custom_guardrails
                ],
            },
        )

    def preview(self, config: AgentCreationConfig) -> dict[str, Any]:
        """Return a serializable preview without constructing SDK objects."""

        registered_tool_ids = set(self.registry.tools) | set(self.registry.tool_factories)
        unresolved_tools = [
            tool.id
            for tool in config.tools
            if tool.enabled and tool.id not in registered_tool_ids
        ]
        unresolved_handoffs = [
            rule.target_agent
            for rule in config.handoffs
            if rule.target_agent not in self.registry.handoffs
        ]
        unresolved_guardrails = [
            guardrail_id
            for guardrail_id in config.guardrails.input
            if guardrail_id not in self.registry.input_guardrails
        ] + [
            guardrail_id
            for guardrail_id in config.guardrails.output
            if guardrail_id not in self.registry.output_guardrails
        ]

        warnings = []
        if unresolved_tools:
            warnings.append(f"Unresolved tool ids: {', '.join(unresolved_tools)}")
        if unresolved_handoffs:
            warnings.append(f"Unresolved handoff ids: {', '.join(unresolved_handoffs)}")
        if unresolved_guardrails:
            warnings.append(
                f"Unresolved guardrail ids: {', '.join(unresolved_guardrails)}"
            )
        unsupported_custom_guardrails = [
            guardrail.name
            for guardrail in config.custom_guardrails
            if guardrail.enabled
            and guardrail.check_type not in SUPPORTED_CUSTOM_GUARDRAIL_CHECK_TYPES
        ]
        if unsupported_custom_guardrails:
            warnings.append(
                "Custom guardrails with AI/moderation/PII checks require backend validation before they enforce policy: "
                + ", ".join(unsupported_custom_guardrails)
            )
        untargeted_tool_guardrails = [
            guardrail.name
            for guardrail in config.custom_guardrails
            if guardrail.enabled
            and guardrail.stage == "tool"
            and not (guardrail.target_tool_id or "").strip()
        ]
        if untargeted_tool_guardrails:
            warnings.append(
                "Custom tool guardrails without a target tool will not be attached: "
                + ", ".join(untargeted_tool_guardrails)
            )
        selected_tool_ids = {tool.id for tool in config.tools if tool.enabled}
        unmatched_tool_guardrails = [
            guardrail.name
            for guardrail in config.custom_guardrails
            if guardrail.enabled
            and guardrail.stage == "tool"
            and guardrail.target_tool_id
            and guardrail.target_tool_id not in selected_tool_ids
        ]
        if unmatched_tool_guardrails:
            warnings.append(
                "Custom tool guardrails targeting inactive tools will not be attached: "
                + ", ".join(unmatched_tool_guardrails)
            )

        return {
            "instructions": build_agent_instructions(config),
            "agent_definition": {
                "name": config.agent.name,
                "key": config.agent.key,
                "role": config.agent.role,
                "channel": config.channel.model_dump(by_alias=True),
                "model": config.runtime.model,
                "model_settings": {
                    "temperature": config.runtime.temperature,
                    "reasoning_effort": config.runtime.reasoning_effort,
                    "verbosity": config.runtime.verbosity,
                    "tool_choice": config.runtime.tool_choice,
                    "parallel_tool_calls": config.runtime.parallel_tool_calls,
                    "max_tokens": config.runtime.max_tokens,
                },
                "stored_prompt": config.stored_prompt.model_dump(by_alias=True)
                if config.stored_prompt
                else None,
                "tools": [tool.model_dump(by_alias=True) for tool in config.tools],
                "handoffs": [rule.model_dump(by_alias=True) for rule in config.handoffs],
                "guardrails": config.guardrails.model_dump(by_alias=True),
                "custom_guardrails": [
                    guardrail.model_dump(by_alias=True)
                    for guardrail in config.custom_guardrails
                ],
                "output": config.output.model_dump(by_alias=True),
                "max_turns": config.runtime.max_turns,
            },
            "warnings": warnings,
        }

    def _resolve_tools(self, config: AgentCreationConfig) -> tuple[list[Any], list[str]]:
        resolved: list[Any] = []
        unresolved: list[str] = []

        for tool in config.tools:
            if not tool.enabled:
                continue
            implementation = self.registry.tools.get(tool.id)
            if implementation is None:
                factory = self.registry.tool_factories.get(tool.id)
                if factory is not None:
                    implementation = factory(tool)
            if implementation is None:
                unresolved.append(tool.id)
                continue
            tool_guardrails = _custom_tool_input_guardrails_for_tool(config, tool.id)
            if isinstance(implementation, (list, tuple)):
                resolved.extend(
                    _with_custom_tool_input_guardrails(item, tool_guardrails)
                    for item in implementation
                )
                continue
            resolved.append(_with_custom_tool_input_guardrails(implementation, tool_guardrails))

        return resolved, unresolved

    def _resolve_handoffs(
        self,
        config: AgentCreationConfig,
    ) -> tuple[list[Any], list[str]]:
        resolved: list[Any] = []
        unresolved: list[str] = []

        for rule in config.handoffs:
            handoff_agent = self.registry.handoffs.get(rule.target_agent)
            if handoff_agent is None:
                unresolved.append(rule.target_agent)
                continue
            resolved.append(handoff_agent)

        return resolved, unresolved

    def _resolve_guardrails(
        self,
        requested: list[str],
        registry: dict[str, Any],
    ) -> tuple[list[Any], list[str]]:
        resolved: list[Any] = []
        unresolved: list[str] = []

        for guardrail_id in requested:
            guardrail = registry.get(guardrail_id)
            if guardrail is None:
                unresolved.append(guardrail_id)
                continue
            resolved.append(guardrail)

        return resolved, unresolved

    def _raise_if_strict(
        self,
        *,
        unresolved_tools: list[str],
        unresolved_handoffs: list[str],
        unresolved_guardrails: list[str],
    ) -> None:
        if not self.strict_references:
            return

        problems = []
        if unresolved_tools:
            problems.append(f"tools={unresolved_tools}")
        if unresolved_handoffs:
            problems.append(f"handoffs={unresolved_handoffs}")
        if unresolved_guardrails:
            problems.append(f"guardrails={unresolved_guardrails}")

        if problems:
            raise AgentReferenceError(
                "Agent config references backend IDs that are not registered: "
                + "; ".join(problems)
            )


def _default_prompt_safety_enabled(config: AgentCreationConfig) -> bool:
    metadata = config.metadata if isinstance(config.metadata, dict) else {}
    safety = metadata.get("prompt_safety")
    if isinstance(safety, dict) and safety.get("enabled") is False:
        return False
    return metadata.get("disable_prompt_safety") is not True


def _build_default_prompt_safety_input_guardrail() -> Any:
    @input_guardrail(name="agentive_prompt_safety_input", run_in_parallel=False)
    def _guardrail(context: Any, agent: Agent[Any], agent_input: Any) -> GuardrailFunctionOutput:
        latest_user_text = _latest_user_text_from_agent_input(agent_input)
        recent_text = _recent_agent_input_text(agent_input)
        evaluation = _evaluate_prompt_safety_input(latest_user_text, recent_text)
        return GuardrailFunctionOutput(
            output_info=evaluation,
            tripwire_triggered=bool(evaluation["triggered"]),
        )

    return _guardrail


def _build_default_prompt_safety_output_guardrail() -> Any:
    @output_guardrail(name="agentive_prompt_safety_output")
    def _guardrail(context: Any, agent: Agent[Any], output: Any) -> GuardrailFunctionOutput:
        evaluation = _evaluate_prompt_safety_output(str(output or ""))
        return GuardrailFunctionOutput(
            output_info=evaluation,
            tripwire_triggered=bool(evaluation["triggered"]),
        )

    return _guardrail


def _evaluate_prompt_safety_input(latest_user_text: str, recent_text: str = "") -> dict[str, Any]:
    latest_normalized = _normalize_guardrail_text(latest_user_text)
    recent_normalized = _normalize_guardrail_text(recent_text)

    prompt_injection_reason = _first_matching_pattern(
        latest_normalized,
        _PROMPT_INJECTION_PATTERNS,
    )
    if prompt_injection_reason:
        return _prompt_safety_evaluation(
            triggered=True,
            stage="input",
            category="prompt_injection",
            reason=prompt_injection_reason,
            message=DEFAULT_PROMPT_SAFETY_BLOCK_MESSAGE,
        )

    off_topic_reason = _first_matching_pattern(
        latest_normalized,
        _OFF_TOPIC_CODE_PATTERNS,
    )
    if off_topic_reason:
        return _prompt_safety_evaluation(
            triggered=True,
            stage="input",
            category="off_topic_code_request",
            reason=off_topic_reason,
            message=DEFAULT_PROMPT_SAFETY_BLOCK_MESSAGE,
        )

    if (
        _first_matching_pattern(latest_normalized, _SHORT_CONTINUATION_PATTERNS)
        and _first_matching_pattern(recent_normalized, _OFF_TOPIC_CODE_PATTERNS)
    ):
        return _prompt_safety_evaluation(
            triggered=True,
            stage="input",
            category="off_topic_code_continuation",
            reason="short_confirmation_after_code_request",
            message=DEFAULT_PROMPT_SAFETY_BLOCK_MESSAGE,
        )

    return _prompt_safety_evaluation(triggered=False, stage="input")


def _evaluate_prompt_safety_output(output_text: str) -> dict[str, Any]:
    normalized = _normalize_guardrail_text(output_text)
    secret_reason = _first_matching_pattern(normalized, _OUTPUT_SECRET_PATTERNS)
    if secret_reason:
        return _prompt_safety_evaluation(
            triggered=True,
            stage="output",
            category="sensitive_instruction_leak",
            reason=secret_reason,
            message=DEFAULT_PROMPT_SAFETY_OUTPUT_MESSAGE,
        )

    code_reason = _first_matching_pattern(output_text, _OUTPUT_CODE_PATTERNS)
    if code_reason:
        return _prompt_safety_evaluation(
            triggered=True,
            stage="output",
            category="code_output",
            reason=code_reason,
            message=DEFAULT_PROMPT_SAFETY_OUTPUT_MESSAGE,
        )

    return _prompt_safety_evaluation(triggered=False, stage="output")


def _prompt_safety_evaluation(
    *,
    triggered: bool,
    stage: str,
    category: str = "allowed",
    reason: str = "",
    message: str = "",
) -> dict[str, Any]:
    return {
        "key": "agentive_prompt_safety",
        "name": "Prompt safety",
        "stage": stage,
        "action": "block" if triggered else "allow",
        "triggered": triggered,
        "category": category,
        "reason": reason,
        "message": message or (DEFAULT_PROMPT_SAFETY_BLOCK_MESSAGE if triggered else ""),
    }


def _latest_user_text_from_agent_input(agent_input: Any) -> str:
    if isinstance(agent_input, str):
        return agent_input
    if not isinstance(agent_input, list):
        return ""

    for item in reversed(agent_input):
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        text = _content_to_text(item.get("content"))
        if text:
            return text
    return ""


def _recent_agent_input_text(agent_input: Any, limit: int = 6) -> str:
    if isinstance(agent_input, str):
        return agent_input
    if not isinstance(agent_input, list):
        return ""

    texts: list[str] = []
    for item in agent_input[-limit:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = _content_to_text(item.get("content"))
        if role and content:
            texts.append(f"{role}: {content}")
    return "\n".join(texts)


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return " ".join(parts)


def _normalize_guardrail_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", normalized.casefold()).strip()


def _first_matching_pattern(text: str, patterns: tuple[str, ...]) -> str:
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL):
            return pattern
    return ""


def compile_agent_preview(config: AgentCreationConfig) -> dict[str, Any]:
    """Convenience helper for API preview endpoints."""

    registry = AgentRuntimeRegistry()
    registry.register_tool_factory("calendar.scheduling", lambda _tool: [])
    registry.register_tool_factory("human_handoff.create_task", lambda _tool: [])
    registry.register_tool_factory("crm.pipeline_stage", lambda _tool: [])
    registry.register_tool_factory("crm.dynamic_followup", lambda _tool: [])
    registry.register_tool_factory("whatsapp.send_contact_card", lambda _tool: [])
    registry.register_tool_factory("whatsapp.schedule_followup_message", lambda _tool: [])
    registry.register_tool_factory("audio.request_response", lambda _tool: [])
    registry.register_tool("knowledge.file_search", object())
    registry.register_tool("knowledge.web_search", object())
    return AgentConfigCompiler(registry=registry, strict_references=False).preview(config)


def _custom_tool_input_guardrails_for_tool(
    config: AgentCreationConfig,
    tool_id: str,
) -> list[ToolInputGuardrail[Any]]:
    guardrails: list[ToolInputGuardrail[Any]] = []
    for guardrail in config.custom_guardrails:
        if (
            not guardrail.enabled
            or guardrail.stage != "tool"
            or guardrail.target_tool_id != tool_id
            or guardrail.check_type not in SUPPORTED_CUSTOM_GUARDRAIL_CHECK_TYPES
        ):
            continue
        guardrails.append(_build_custom_tool_input_guardrail(guardrail))
    return guardrails


def _build_custom_tool_input_guardrail(
    guardrail: CustomGuardrailConfig,
) -> ToolInputGuardrail[Any]:
    def _run_tool_guardrail(data: ToolInputGuardrailData) -> ToolGuardrailFunctionOutput:
        text = _tool_guardrail_evaluation_text(data)
        triggered = _custom_guardrail_condition_matches(guardrail, text)
        output_info = {
            "key": guardrail.key,
            "name": guardrail.name,
            "stage": guardrail.stage,
            "target_tool_id": guardrail.target_tool_id,
            "check_type": guardrail.check_type,
            "action": guardrail.action,
            "triggered": triggered,
        }
        if not triggered or guardrail.action == "warn":
            return ToolGuardrailFunctionOutput.allow(output_info=output_info)
        return ToolGuardrailFunctionOutput.reject_content(
            _custom_tool_guardrail_message(guardrail),
            output_info=output_info,
        )

    return ToolInputGuardrail(
        guardrail_function=_run_tool_guardrail,
        name=f"custom_tool_guardrail_{guardrail.key}",
    )


def _tool_guardrail_evaluation_text(data: ToolInputGuardrailData) -> str:
    tool_context = data.context
    raw_arguments = str(getattr(tool_context, "tool_arguments", "") or "")
    try:
        tool_arguments: Any = json.loads(raw_arguments)
    except json.JSONDecodeError:
        tool_arguments = raw_arguments

    runtime_context = getattr(tool_context, "context", None)
    payload = {
        "tool_name": getattr(tool_context, "tool_name", ""),
        "tool_arguments": tool_arguments,
        "latest_user_message": getattr(runtime_context, "latest_user_message", ""),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _custom_guardrail_condition_matches(
    guardrail: CustomGuardrailConfig,
    text: str,
) -> bool:
    if guardrail.check_type == "regex":
        try:
            return bool(re.search(guardrail.condition, text, flags=re.IGNORECASE))
        except re.error:
            logger.warning("Invalid custom tool guardrail regex: %s", guardrail.key)
            return False
    if guardrail.check_type == "keyword_filter":
        keywords = [
            item.strip().lower()
            for item in re.split(r"[,;\n]", guardrail.condition)
            if item.strip()
        ]
        lowered = text.lower()
        return any(keyword in lowered for keyword in keywords)
    return False


def _custom_tool_guardrail_message(guardrail: CustomGuardrailConfig) -> str:
    return (
        guardrail.message.strip()
        or "A ferramenta foi bloqueada por um guardrail de segurança. Responda com o próximo passo seguro."
    )


def _with_custom_tool_input_guardrails(
    implementation: Any,
    guardrails: list[ToolInputGuardrail[Any]],
) -> Any:
    if not guardrails or not isinstance(implementation, FunctionTool):
        return implementation

    return FunctionTool(
        name=implementation.name,
        description=implementation.description,
        params_json_schema=implementation.params_json_schema,
        on_invoke_tool=implementation.on_invoke_tool,
        strict_json_schema=implementation.strict_json_schema,
        is_enabled=implementation.is_enabled,
        tool_input_guardrails=[
            *(implementation.tool_input_guardrails or []),
            *guardrails,
        ],
        tool_output_guardrails=implementation.tool_output_guardrails,
    )


def _build_model_settings(config: AgentCreationConfig) -> ModelSettings:
    runtime = config.runtime
    is_gpt5 = runtime.model.startswith("gpt-5")
    temperature = None if is_gpt5 else runtime.temperature
    reasoning_effort = runtime.reasoning_effort
    if not is_gpt5:
        reasoning_effort = None
    elif runtime.model.endswith("-pro") and reasoning_effort in {None, "none", "low"}:
        reasoning_effort = "medium"
    elif reasoning_effort in {None, "none"}:
        reasoning_effort = None

    return ModelSettings(
        temperature=temperature,
        tool_choice=runtime.tool_choice,
        parallel_tool_calls=runtime.parallel_tool_calls,
        max_tokens=runtime.max_tokens,
        reasoning=Reasoning(effort=reasoning_effort)
        if reasoning_effort
        else None,
        verbosity=runtime.verbosity if is_gpt5 else None,
    )


def _build_stored_prompt(config: AgentCreationConfig) -> dict[str, Any] | None:
    stored_prompt = config.stored_prompt
    if stored_prompt is None:
        return None

    prompt: dict[str, Any] = {
        "id": stored_prompt.id,
        "variables": stored_prompt.variables,
    }
    if stored_prompt.version:
        prompt["version"] = stored_prompt.version
    return prompt
