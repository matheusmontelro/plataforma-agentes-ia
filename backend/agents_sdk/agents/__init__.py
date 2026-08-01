"""
Business Company Agents

Pure agent definitions following OpenAI SDK patterns.
No business logic - only agent configuration.
"""

from .coordinator_agent import coordinator_agent

__all__ = ["coordinator_agent"]