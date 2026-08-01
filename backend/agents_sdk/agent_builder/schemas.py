"""
Schemas for agent creation payloads sent by the frontend.

These models intentionally mirror OpenAI Agents SDK concepts while keeping the
frontend contract product-friendly: identity, objective, prompt techniques,
model tuning, tools, handoffs, guardrails, and output contract.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PromptFramework = Literal[
    "agent_standard",
    "structured_instruction",
    "consultative_sales",
    "bant",
    "spin",
    "support_triage",
    "custom",
]

QualificationType = Literal["none", "BANT", "SPIN", "MEDDIC", "custom"]
ConversationChannelType = Literal[
    "whatsapp",
    "webchat",
    "voice",
    "email",
    "instagram",
    "other",
]
AudioProvider = Literal["elevenlabs", "openai"]
ToolChoice = Literal["auto", "required", "none"]
ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh"]
Verbosity = Literal["low", "medium", "high"]
OutputMode = Literal["text", "structured"]
GuardrailStage = Literal["input", "output", "tool"]
GuardrailCheckType = Literal[
    "llm_classifier",
    "keyword_filter",
    "regex",
    "moderation",
    "pii_detection",
]
GuardrailAction = Literal["block", "handoff", "redact", "warn"]
SupportedAgentModel = Literal[
    "gpt-4o-mini",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.4",
    "gpt-5.4-pro",
    "gpt-5.5",
    "gpt-5.5-pro",
]


class AgentBuilderModel(BaseModel):
    """Base model for strict frontend contracts."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AgentProfileConfig(AgentBuilderModel):
    """Human-facing and trace-facing identity for a specialist."""

    key: str = Field(..., min_length=2, description="Stable internal agent key")
    name: str = Field(..., min_length=2, description="Trace-facing display name")
    role: str = Field(..., min_length=3, description="Business responsibility")
    organization_type: str = Field(default="generic")
    language: str = Field(default="pt-BR")
    tone: str = Field(default="consultivo, claro e simpatico")
    description: str = ""
    handoff_description: str | None = Field(
        default=None,
        description="Short routing hint shown to other agents during handoffs",
    )

    @field_validator("key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "_")
        if not normalized:
            raise ValueError("agent key cannot be blank")
        return normalized


class AudioVoiceConfig(AgentBuilderModel):
    """Voice used when a channel response is rendered as audio."""

    provider: AudioProvider = "elevenlabs"
    voice_id: str = ""
    label: str = ""
    model_id: str = "eleven_flash_v2_5"
    output_format: str = "mp3_44100_128"
    stability: float | None = Field(default=None, ge=0, le=1)
    similarity_boost: float | None = Field(default=None, ge=0, le=1)
    style: float | None = Field(default=None, ge=0, le=1)
    use_speaker_boost: bool | None = None


class ChannelConfig(AgentBuilderModel):
    """Channel-specific conversation style."""

    type: ConversationChannelType = "whatsapp"
    message_style: str = "curto, natural e objetivo"
    max_response_sentences: int | None = Field(default=3, ge=1, le=12)
    allow_audio: bool = False
    voice: AudioVoiceConfig | None = None
    business_timezone: str | None = "America/Sao_Paulo"


class ObjectiveConfig(AgentBuilderModel):
    """Goal and success criteria for the agent."""

    primary_goal: str = Field(..., min_length=5)
    user_outcome: str = ""
    success_criteria: list[str] = Field(default_factory=list)
    failure_conditions: list[str] = Field(default_factory=list)


class QualificationMethodConfig(AgentBuilderModel):
    """Lead/client qualification method exposed as product controls."""

    type: QualificationType = "none"
    required_fields: list[str] = Field(default_factory=list)
    optional_fields: list[str] = Field(default_factory=list)
    disqualifiers: list[str] = Field(default_factory=list)


class FewShotExample(AgentBuilderModel):
    """A short input/output example used to steer style and decisions."""

    user: str = Field(..., min_length=1)
    assistant: str = Field(..., min_length=1)
    context: str | None = None


class ObjectionHandlingRule(AgentBuilderModel):
    """How the agent should handle a recurring objection."""

    objection: str = Field(..., min_length=2)
    response_strategy: str = Field(..., min_length=5)


class ToolPolicyConfig(AgentBuilderModel):
    """Prompt-level policy for when a tool should be considered."""

    tool: str = Field(..., min_length=2)
    when: str = Field(..., min_length=3)
    requires: list[str] = Field(default_factory=list)
    side_effect: bool = False
    retry_safety: str = "nao repetir se houver risco de duplicar uma acao"


class PromptTechniqueConfig(AgentBuilderModel):
    """Prompt engineering controls available in the frontend."""

    framework: PromptFramework = "agent_standard"
    context: str = ""
    instructions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    conversation_rules: list[str] = Field(default_factory=list)
    variables: list[str] = Field(default_factory=list)
    qualification_method: QualificationMethodConfig = Field(
        default_factory=QualificationMethodConfig
    )
    few_shots: list[FewShotExample] = Field(default_factory=list)
    objection_handling: list[ObjectionHandlingRule] = Field(default_factory=list)
    tool_policy: list[ToolPolicyConfig] = Field(default_factory=list)
    custom_sections: dict[str, str] = Field(default_factory=dict)

    @field_validator("variables")
    @classmethod
    def normalize_variables(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value.strip()]


class ModelRuntimeConfig(AgentBuilderModel):
    """Model and tuning parameters that belong near the agent definition."""

    model: SupportedAgentModel = Field(default="gpt-5.4-mini")
    temperature: float | None = Field(default=0.4, ge=0, le=2)
    max_turns: int = Field(default=10, ge=1, le=50)
    reasoning_effort: ReasoningEffort | None = "low"
    verbosity: Verbosity | None = "medium"
    tool_choice: ToolChoice = "auto"
    parallel_tool_calls: bool | None = None
    max_tokens: int | None = Field(default=None, ge=1)

    @model_validator(mode="before")
    @classmethod
    def default_reasoning_for_model(cls, data: Any) -> Any:
        if isinstance(data, dict):
            model = str(data.get("model", ""))
            if not model.startswith("gpt-5"):
                return {**data, "reasoning_effort": "none"}
            if model.endswith("-pro") and data.get("reasoning_effort") in {None, "none", "low"}:
                return {**data, "reasoning_effort": "medium"}
        return data

    @model_validator(mode="after")
    def validate_reasoning_for_model(self) -> "ModelRuntimeConfig":
        if not self.model.startswith("gpt-5"):
            self.reasoning_effort = "none"
        elif self.model.endswith("-pro") and self.reasoning_effort in {None, "none", "low"}:
            self.reasoning_effort = "medium"
        return self


class StoredPromptConfig(AgentBuilderModel):
    """Reference to an OpenAI dashboard prompt configuration."""

    id: str = Field(..., min_length=3)
    version: str | None = None
    variables: dict[str, Any] = Field(default_factory=dict)


class ToolSelectionConfig(AgentBuilderModel):
    """Frontend-selected capability from the backend tool registry."""

    id: str = Field(..., min_length=2)
    enabled: bool = True
    requires_approval: bool = False
    notes: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)


class HandoffRuleConfig(AgentBuilderModel):
    """Routing rule to another specialist or human queue."""

    target_agent: str = Field(..., min_length=2)
    when: str = Field(..., min_length=3)
    owns_final_response: bool = True
    description: str = ""


class GuardrailSelectionConfig(AgentBuilderModel):
    """Guardrails selected by ID from backend registries."""

    input: list[str] = Field(default_factory=list)
    output: list[str] = Field(default_factory=list)
    tool: list[str] = Field(default_factory=list)
    approvals: list[str] = Field(default_factory=list)


class CustomGuardrailConfig(AgentBuilderModel):
    """User-defined guardrail policy to be executed by backend validation code."""

    key: str = Field(..., min_length=2, description="Stable custom guardrail key")
    name: str = Field(..., min_length=2)
    stage: GuardrailStage = "input"
    target_tool_id: str | None = Field(
        default=None,
        description="Product tool id that receives this guardrail when stage is tool",
    )
    check_type: GuardrailCheckType = "llm_classifier"
    condition: str = Field(..., min_length=3)
    action: GuardrailAction = "block"
    enabled: bool = True
    message: str = ""
    threshold: float | None = Field(default=None, ge=0, le=1)

    @field_validator("key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "_")
        if not normalized:
            raise ValueError("custom guardrail key cannot be blank")
        return normalized

    @field_validator("target_tool_id")
    @classmethod
    def normalize_target_tool_id(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None


class OutputContractConfig(AgentBuilderModel):
    """Output expectations for plain text or structured responses."""

    mode: OutputMode = "text"
    schema_name: str | None = None
    json_schema: dict[str, Any] | None = Field(default=None, alias="schema")
    notes: str = ""


class AgentCreationConfig(AgentBuilderModel):
    """
    Canonical payload for creating an agent from the frontend.

    The `runtime` attribute is exposed to the API as `model` so the JSON contract
    matches OpenAI naming while avoiding Pydantic's own `model_config` attribute.
    """

    schema_version: str = "2026-05-01"
    agent: AgentProfileConfig
    channel: ChannelConfig = Field(default_factory=ChannelConfig)
    objective: ObjectiveConfig
    prompt_techniques: PromptTechniqueConfig = Field(
        default_factory=PromptTechniqueConfig
    )
    runtime: ModelRuntimeConfig = Field(
        default_factory=ModelRuntimeConfig,
        alias="model",
    )
    stored_prompt: StoredPromptConfig | None = None
    tools: list[ToolSelectionConfig] = Field(default_factory=list)
    handoffs: list[HandoffRuleConfig] = Field(default_factory=list)
    guardrails: GuardrailSelectionConfig = Field(default_factory=GuardrailSelectionConfig)
    custom_guardrails: list[CustomGuardrailConfig] = Field(default_factory=list)
    output: OutputContractConfig = Field(default_factory=OutputContractConfig)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self) -> "AgentCreationConfig":
        tool_ids = [tool.id for tool in self.tools]
        if len(tool_ids) != len(set(tool_ids)):
            raise ValueError("tools must not contain duplicate ids")

        handoff_targets = [handoff.target_agent for handoff in self.handoffs]
        if len(handoff_targets) != len(set(handoff_targets)):
            raise ValueError("handoffs must not contain duplicate target_agent values")

        if self.agent.key in handoff_targets:
            raise ValueError("agent cannot handoff to itself")

        custom_guardrail_keys = [
            guardrail.key
            for guardrail in self.custom_guardrails
            if guardrail.enabled
        ]
        if len(custom_guardrail_keys) != len(set(custom_guardrail_keys)):
            raise ValueError("custom_guardrails must not contain duplicate keys")

        variables = self.prompt_techniques.variables
        if len(variables) != len(set(variables)):
            raise ValueError("prompt variables must be unique")

        if self.output.mode == "structured" and not (
            self.output.json_schema or self.output.schema_name
        ):
            raise ValueError("structured output requires schema or schema_name")

        return self
