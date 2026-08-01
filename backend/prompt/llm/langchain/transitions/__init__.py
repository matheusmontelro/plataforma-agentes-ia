"""
LangChain-based transition system for company conversations.
Professional state management with type safety and validation.
"""

from .models import AppointmentState, TransitionContext, TransitionDecision
from .state_manager import LangChainStateManager
from .transition_chain import create_transition_chain
from .validators import StateValidator

__all__ = [
    "AppointmentState",
    "TransitionContext",
    "TransitionDecision",
    "LangChainStateManager",
    "create_transition_chain",
    "StateValidator"
]
