"""
LangChain modular conversation flow system.

This package implements a modular, step-based conversation flow
for business company appointment scheduling.
"""

from .adapters.burst_adapter import handle_user_input_v2, process_llm_v2_message
from .chains.conversation_chain import ConversationFlowChain
from .core.state_manager import ConversationStateManager
from .prompts.templates import get_step_template, get_all_step_names

__version__ = "1.0.0"

__all__ = [
    "handle_user_input_v2",
    "process_llm_v2_message",
    "ConversationFlowChain",
    "ConversationStateManager",
    "get_step_template",
    "get_all_step_names"
]