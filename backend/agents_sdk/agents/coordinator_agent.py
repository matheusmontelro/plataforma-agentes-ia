"""
Business Assistant Agent - Clean agent definition following OpenAI patterns
"""

from agents import Agent, ModelSettings, handoff
from ..config.model_config import get_model_config

# Clean agent definition following OpenAI patterns - NO business logic here

# Import dynamic instructions function
def get_business_instructions(run_context, agent) -> str:
    """Dynamic instructions - now routed via Registry"""
    from ..prompts import PromptRegistry
    return PromptRegistry.get_instructions(run_context, agent)

# Get model configuration
model_config = get_model_config()

# Handoffs removidos - usando apenas tools diretas

# Agent definition with no tools initially (all tools injected by manager)
# This follows the openai-agents-python pattern where tools are provided at runtime
coordinator_agent = Agent(
    name="CRC Agent",
    instructions=get_business_instructions,
    model=model_config['model'],  # Use configured model
    model_settings=ModelSettings(
        temperature=model_config.get('temperature', 0.7),
        # Let agent decide when to use tools with strong prompt guidance
        tool_choice="auto"  # Agent decides based on prompt instructions
    ),
    tools=[],  # All tools injected by manager at runtime
    # Sem handoffs para indicações - usando tools diretas
)