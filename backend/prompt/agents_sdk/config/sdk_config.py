# SDK Configuration
import os
import logging
from typing import Optional
from dataclasses import dataclass
from agents import RunConfig, enable_verbose_stdout_logging
from agents.models.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)


@dataclass
class AgentsConfig:
    """Configuration for OpenAI Agents SDK"""

    api_key: Optional[str] = None
    enable_tracing: bool = False
    verbose_logging: bool = False
    model_name: str = "gpt-4o-mini"
    max_tokens: int = 300
    temperature: float = 0.7


def configure_agents_sdk(config: Optional[AgentsConfig] = None) -> RunConfig:
    """
    Build an isolated Agents SDK run configuration.

    The API key must be supplied explicitly by the caller after resolving the
    active company's BYOK credential. It is deliberately not installed as the
    SDK process-wide default because workers can serve multiple companies.

    Args:
        config: Configuration containing the explicit company API key.
    """
    api_key = (config.api_key if config else "") or ""
    api_key = api_key.strip()
    if not api_key:
        raise ValueError(
            "Chave OpenAI explícita da empresa é obrigatória para o Agents SDK"
        )

    # Configure logging
    if config and config.verbose_logging:
        enable_verbose_stdout_logging()
        logger.info("Verbose logging enabled for Agents SDK")

    # Log sensitive data settings
    if os.getenv("OPENAI_AGENTS_DONT_LOG_MODEL_DATA"):
        logger.info("Model data logging disabled")
    if os.getenv("OPENAI_AGENTS_DONT_LOG_TOOL_DATA"):
        logger.info("Tool data logging disabled")

    return RunConfig(
        model=(config.model_name if config else "gpt-4o-mini"),
        model_provider=OpenAIProvider(api_key=api_key),
        tracing_disabled=not bool(config and config.enable_tracing),
        trace_include_sensitive_data=False,
    )
