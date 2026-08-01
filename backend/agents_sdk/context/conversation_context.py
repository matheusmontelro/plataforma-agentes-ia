"""
Generic conversation context for WhatsApp-first agent teams.

This module is intentionally domain-neutral. Business/company/customer concepts can
adapt to it, but new agent teams should speak in terms of organization, contact,
lead/client lifecycle, channel, and active workflow.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ConversationChannel(str, Enum):
    """Supported inbound/outbound conversation channels."""

    WHATSAPP = "whatsapp"
    WEBCHAT = "webchat"
    VOICE = "voice"
    SMS = "sms"
    EMAIL = "email"
    OTHER = "other"


class ContactLifecycle(str, Enum):
    """Business relationship stage for the person talking to the agent."""

    UNKNOWN = "unknown"
    LEAD = "lead"
    PROSPECT = "prospect"
    CLIENT = "client"
    CUSTOMER = "customer"
    PARTNER = "partner"


class ConversationContext(BaseModel):
    """
    Domain-neutral state passed to agents and tools.

    Keep runtime-only dependencies here when tools need them, and keep facts the
    model should see in instructions, tool results, or prompt variables.
    """

    organization_id: int = Field(..., description="Tenant or organization id")
    organization_type: str = Field(default="generic", description="Business vertical")
    organization_data: Dict[str, Any] = Field(default_factory=dict)

    channel: ConversationChannel = ConversationChannel.WHATSAPP
    contact_id: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_name: Optional[str] = None
    lifecycle: ContactLifecycle = ContactLifecycle.UNKNOWN

    current_stage: str = ""
    conversation_step: int = 0
    active_flow: Optional[str] = None
    flow_data: Dict[str, Any] = Field(default_factory=dict)

    captured_profile: Dict[str, Any] = Field(default_factory=dict)
    captured_preferences: Dict[str, Any] = Field(default_factory=dict)
    completed_actions: List[Dict[str, Any]] = Field(default_factory=list)
    pending_actions: List[Dict[str, Any]] = Field(default_factory=list)

    db: Optional[Any] = Field(default=None, exclude=True)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    last_interaction: Optional[str] = None

    @property
    def company_id(self) -> int:
        """Backward-compatible alias for legacy business integrations."""

        return self.organization_id

    @property
    def phone(self) -> str:
        """Backward-compatible alias for legacy phone-based integrations."""

        return self.contact_phone or self.contact_id or ""

    @property
    def company_data(self) -> Dict[str, Any]:
        """Backward-compatible alias for existing prompt/templates."""

        return self.organization_data

    def advance_stage(self, new_stage: str, user_input: str = "") -> None:
        self.current_stage = new_stage
        self.conversation_step += 1
        self.updated_at = datetime.now()
        self.last_interaction = user_input[:200] if user_input else self.last_interaction

    def set_flow(self, flow_name: Optional[str], data: Optional[Dict[str, Any]] = None) -> None:
        self.active_flow = flow_name
        self.flow_data = data or {}
        self.updated_at = datetime.now()

    def capture_profile(self, key: str, value: Any) -> None:
        self.captured_profile[key] = value
        self.updated_at = datetime.now()

    def capture_preference(self, key: str, value: Any) -> None:
        self.captured_preferences[key] = value
        self.updated_at = datetime.now()

    def record_action(self, action: str, result: Dict[str, Any]) -> None:
        self.completed_actions.append(
            {
                "action": action,
                "result": result,
                "timestamp": datetime.now().isoformat(),
            }
        )
        self.updated_at = datetime.now()

    def to_prompt_variables(self) -> Dict[str, str]:
        return {
            "organization_id": str(self.organization_id),
            "organization_type": self.organization_type,
            "channel": self.channel.value,
            "contact_id": self.contact_id or "",
            "contact_phone": self.contact_phone or "",
            "contact_name": self.contact_name or "",
            "contact_lifecycle": self.lifecycle.value,
            "current_stage_info": self.current_stage,
            "conversation_step": str(self.conversation_step),
            "active_flow": self.active_flow or "",
            "last_interaction": self.last_interaction or "",
        }


ContactContext = ConversationContext
LeadContext = ConversationContext
ClientContext = ConversationContext
