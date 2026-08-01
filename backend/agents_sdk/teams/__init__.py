"""
Agent team blueprints.

These classes describe ownership, hierarchy, and handoff intent without binding
the platform to a specific vertical such as business companies.
"""

from .org_chart import AgentTeamBlueprint, AgentTeamMember

__all__ = ["AgentTeamBlueprint", "AgentTeamMember"]
