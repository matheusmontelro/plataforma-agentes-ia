"""
Frontend-driven agent configuration.

This package turns a structured payload from the product UI into an OpenAI
Agents SDK definition. It keeps prompt techniques, model settings, tools,
handoffs, and guardrails as first-class configuration instead of one large
free-form prompt.
"""

from .factory import (
    AgentBuildResult,
    AgentConfigCompiler,
    AgentRuntimeRegistry,
    AgentReferenceError,
    DEFAULT_PROMPT_SAFETY_BLOCK_MESSAGE,
    compile_agent_preview,
)
from .prompt_compiler import (
    build_agent_instructions,
    create_dynamic_instructions,
    extract_runtime_context,
)
from .schemas import (
    AgentCreationConfig,
    AgentProfileConfig,
    ChannelConfig,
    CustomGuardrailConfig,
    FewShotExample,
    GuardrailSelectionConfig,
    HandoffRuleConfig,
    ModelRuntimeConfig,
    ObjectiveConfig,
    ObjectionHandlingRule,
    OutputContractConfig,
    PromptTechniqueConfig,
    QualificationMethodConfig,
    StoredPromptConfig,
    ToolPolicyConfig,
    ToolSelectionConfig,
)

__all__ = [
    "AgentBuildResult",
    "AgentConfigCompiler",
    "AgentCreationConfig",
    "AgentProfileConfig",
    "AgentReferenceError",
    "AgentRuntimeRegistry",
    "ChannelConfig",
    "CustomGuardrailConfig",
    "DEFAULT_PROMPT_SAFETY_BLOCK_MESSAGE",
    "FewShotExample",
    "GuardrailSelectionConfig",
    "HandoffRuleConfig",
    "ModelRuntimeConfig",
    "ObjectiveConfig",
    "ObjectionHandlingRule",
    "OutputContractConfig",
    "PromptTechniqueConfig",
    "QualificationMethodConfig",
    "StoredPromptConfig",
    "ToolPolicyConfig",
    "ToolSelectionConfig",
    "build_agent_instructions",
    "compile_agent_preview",
    "create_dynamic_instructions",
    "extract_runtime_context",
]
