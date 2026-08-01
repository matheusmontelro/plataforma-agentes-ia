"""
Data models for multi-agent team organization charts.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class AgentTeamMember(BaseModel):
    """One role in a conversational agent team."""

    key: str = Field(..., description="Stable internal agent key")
    name: str = Field(..., description="Trace-facing agent name")
    role: str = Field(..., description="Business responsibility")
    reports_to: Optional[str] = Field(default=None, description="Parent agent key")
    handoff_description: str = ""
    owns_final_response: bool = True
    capabilities: List[str] = Field(default_factory=list)
    escalation_targets: List[str] = Field(default_factory=list)


class AgentTeamBlueprint(BaseModel):
    """
    Domain-neutral org chart for a WhatsApp conversational team.

    Example members: intake, qualification, scheduling, support, billing,
    human_handoff. The root agent is usually a triage/coordinator.
    """

    name: str
    organization_type: str = "generic"
    channel: str = "whatsapp"
    root_agent_key: str
    members: List[AgentTeamMember]

    @model_validator(mode="after")
    def validate_tree(self) -> "AgentTeamBlueprint":
        keys = {member.key for member in self.members}
        if self.root_agent_key not in keys:
            raise ValueError("root_agent_key must match one team member")

        for member in self.members:
            if member.reports_to and member.reports_to not in keys:
                raise ValueError(f"reports_to '{member.reports_to}' is not a team member")
            for target in member.escalation_targets:
                if target not in keys:
                    raise ValueError(f"escalation target '{target}' is not a team member")

        return self

    def by_key(self) -> Dict[str, AgentTeamMember]:
        return {member.key: member for member in self.members}

    def children_of(self, key: str) -> List[AgentTeamMember]:
        return [member for member in self.members if member.reports_to == key]

    def handoff_targets_for(self, key: str) -> List[AgentTeamMember]:
        members = self.by_key()
        current = members[key]
        targets = self.children_of(key)
        targets.extend(members[target] for target in current.escalation_targets)
        return targets
