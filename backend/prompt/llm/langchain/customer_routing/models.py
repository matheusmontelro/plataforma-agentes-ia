"""
Pydantic Models for Customer Status Routing System
=================================================

Type-safe models for customer status detection and routing decisions.
"""

from enum import Enum
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from pydantic import BaseModel, Field, validator


class CustomerStatus(str, Enum):
    """
    Customer status hierarchy based on database state.

    Priority order (highest to lowest):
    1. PURCHASED - Customer bought treatment (highest priority)
    2. ATTENDED - Customer attended consultation
    3. SCHEDULED - Customer has future appointment
    4. NO_SHOW - Customer missed appointment
    5. LEAD - New lead without history (lowest priority)
    """
    PURCHASED = "purchased"   # Comprou - só dúvidas/objeções
    ATTENDED = "attended"     # Compareceu - só dúvidas/objeções
    SCHEDULED = "scheduled"   # Agendado - pode reagendar/cancelar
    NO_SHOW = "no_show"      # Faltou - pode reagendar/cancelar
    LEAD = "lead"            # Lead sem histórico - pode agendar


class ActionType(str, Enum):
    """Available actions for each customer status"""
    # Scheduling actions
    SCHEDULE_NEW = "schedule_new"
    RESCHEDULE = "reschedule"
    CANCEL = "cancel"
    CONFIRM = "confirm"

    # Support actions
    CLARIFY = "clarify"
    SUPPORT = "support"
    OBJECTION_HANDLING = "objection_handling"
    POST_SALE_SUPPORT = "post_sale_support"

    # Lead qualification
    QUALIFY = "qualify"
    INFORM = "inform"


class CustomerStatusResult(BaseModel):
    """
    Result of customer status detection with context.
    """
    status: CustomerStatus = Field(..., description="Detected customer status")

    # Context data
    last_appointment: Optional[datetime] = Field(None, description="Date of last appointment")
    appointment_id: Optional[int] = Field(None, description="Current/last appointment ID")
    attendance_id: Optional[int] = Field(None, description="Attendance record ID")
    sale_id: Optional[int] = Field(None, description="Sale record ID")

    # Status metadata
    confidence: float = Field(1.0, description="Confidence in status detection (0-1)")
    detection_method: str = Field("database", description="How status was detected")
    cached: bool = Field(False, description="Whether result came from cache")

    # Business context
    days_since_last_appointment: Optional[int] = Field(None, description="Days since last appointment")
    total_appointments: int = Field(0, description="Total appointments for this customer")
    total_purchases: int = Field(0, description="Total purchases for this customer")

    @validator('confidence')
    def validate_confidence(cls, v):
        if not 0 <= v <= 1:
            raise ValueError("Confidence must be between 0 and 1")
        return v

    def get_status_description(self) -> str:
        """Get human-readable status description"""
        descriptions = {
            CustomerStatus.PURCHASED: f"Cliente que comprou tratamento",
            CustomerStatus.ATTENDED: f"Cliente que compareceu à consulta",
            CustomerStatus.SCHEDULED: f"Cliente com consulta agendada",
            CustomerStatus.NO_SHOW: f"Cliente que faltou à consulta",
            CustomerStatus.LEAD: f"Novo lead sem histórico"
        }

        base_desc = descriptions[self.status]

        if self.last_appointment:
            base_desc += f" em {self.last_appointment.strftime('%d/%m/%Y')}"

        return base_desc

    def is_active_customer(self) -> bool:
        """Check if this is an active customer (not just a lead)"""
        return self.status in [
            CustomerStatus.PURCHASED,
            CustomerStatus.ATTENDED,
            CustomerStatus.SCHEDULED,
            CustomerStatus.NO_SHOW
        ]


class StatusDetectionContext(BaseModel):
    """
    Context for status detection including conversation history.
    """
    contact_phone: str = Field(..., description="Customer phone number")
    company_id: int = Field(..., description="Company ID")

    # Optional semantic context - accepts both LangChain messages and dict format
    conversation_history: Optional[List[Union[Dict[str, Any], Any]]] = Field(None, description="Recent conversation")
    user_input: Optional[str] = Field(None, description="Current user input")

    # Detection preferences
    use_cache: bool = Field(True, description="Whether to use Redis cache")
    cache_ttl: int = Field(300, description="Cache TTL in seconds")
    include_semantic_analysis: bool = Field(False, description="Whether to use LLM for ambiguous cases")

    class Config:
        arbitrary_types_allowed = True


class AllowedActions(BaseModel):
    """
    Actions allowed for a specific customer status.
    """
    actions: List[ActionType] = Field(..., description="List of allowed actions")
    restrictions: List[str] = Field(default_factory=list, description="Specific restrictions")

    def can_perform(self, action: ActionType) -> bool:
        """Check if action is allowed"""
        return action in self.actions

    def get_restriction_message(self, action: ActionType) -> Optional[str]:
        """Get restriction message for forbidden action"""
        if self.can_perform(action):
            return None

        # Generate context-aware restriction messages
        messages = {
            ActionType.SCHEDULE_NEW: "Este cliente já possui histórico. Para agendamentos, entre em contato com nossa recepção.",
            ActionType.RESCHEDULE: "Reagendamentos não estão disponíveis para este tipo de cliente.",
            ActionType.CANCEL: "Cancelamentos devem ser feitos diretamente com a recepção.",
        }

        return messages.get(action, f"Ação '{action.value}' não permitida para este cliente.")


class RoutingResult(BaseModel):
    """
    Result of customer routing with chain selection and context.
    """
    selected_chain: str = Field(..., description="Name of selected chain")
    customer_status: CustomerStatusResult = Field(..., description="Customer status data")
    allowed_actions: AllowedActions = Field(..., description="Actions allowed for this status")

    # Routing metadata
    routing_time_ms: float = Field(..., description="Time taken for routing decision")
    cache_hit: bool = Field(False, description="Whether status came from cache")

    # Chain context
    chain_context: Dict[str, Any] = Field(default_factory=dict, description="Context passed to chain")
    restrictions_applied: List[str] = Field(default_factory=list, description="Applied restrictions")


class ValidationResult(BaseModel):
    """
    Result of action validation.
    """
    valid: bool = Field(..., description="Whether action is valid")
    action: ActionType = Field(..., description="Validated action")
    customer_status: CustomerStatus = Field(..., description="Customer status context")

    # Validation details
    reason: Optional[str] = Field(None, description="Reason if invalid")
    suggested_response: Optional[str] = Field(None, description="Suggested response for invalid action")
    alternative_actions: List[ActionType] = Field(default_factory=list, description="Alternative allowed actions")


class ChainExecutionResult(BaseModel):
    """
    Result of chain execution with metadata.
    """
    response: str = Field(..., description="Generated response")
    used_chain: str = Field(..., description="Chain that generated response")
    customer_status: CustomerStatus = Field(..., description="Customer status")

    # Execution metadata
    execution_time_ms: float = Field(..., description="Chain execution time")
    tokens_used: Optional[int] = Field(None, description="Tokens consumed")
    cached_response: bool = Field(False, description="Whether response was cached")

    # Validation results
    actions_detected: List[ActionType] = Field(default_factory=list, description="Actions detected in response")
    restrictions_violated: List[str] = Field(default_factory=list, description="Any restrictions violated")
    response_filtered: bool = Field(False, description="Whether response was filtered")

    # Context preservation
    customer_context: Dict[str, Any] = Field(default_factory=dict, description="Customer context used")
    conversation_state: Dict[str, Any] = Field(default_factory=dict, description="Updated conversation state")


# Status-specific configuration models
class ScheduledCustomerConfig(BaseModel):
    """Configuration for scheduled customer chain"""
    allow_reschedule: bool = Field(True, description="Allow rescheduling")
    allow_cancel: bool = Field(True, description="Allow cancellation")
    require_confirmation: bool = Field(True, description="Require confirmation for changes")
    max_reschedule_attempts: int = Field(3, description="Max reschedule attempts")


class AttendedCustomerConfig(BaseModel):
    """Configuration for attended customer chain"""
    focus_on_objections: bool = Field(True, description="Focus on objection handling")
    allow_additional_info: bool = Field(True, description="Allow providing additional treatment info")
    escalate_complex_questions: bool = Field(True, description="Escalate complex questions")


class PurchasedCustomerConfig(BaseModel):
    """Configuration for purchased customer chain"""
    focus_on_support: bool = Field(True, description="Focus on post-sale support")
    allow_upselling: bool = Field(False, description="Allow upselling other treatments")
    provide_care_instructions: bool = Field(True, description="Provide post-treatment care instructions")


# Factory functions for common configurations
def get_status_allowed_actions(status: CustomerStatus) -> AllowedActions:
    """Get allowed actions for a customer status"""

    action_map = {
        CustomerStatus.SCHEDULED: AllowedActions(
            actions=[
                ActionType.RESCHEDULE,
                ActionType.CANCEL,
                ActionType.CONFIRM,
                ActionType.CLARIFY
            ],
            restrictions=[
                "Não pode agendar nova consulta (já possui agendamento)",
                "Foque em resolver situação da consulta existente"
            ]
        ),

        CustomerStatus.NO_SHOW: AllowedActions(
            actions=[
                ActionType.RESCHEDULE,
                ActionType.CANCEL,
                ActionType.CLARIFY
            ],
            restrictions=[
                "Não pode agendar nova consulta (possui no-show)",
                "Priorize reagendamento da consulta perdida"
            ]
        ),

        CustomerStatus.ATTENDED: AllowedActions(
            actions=[
                ActionType.CLARIFY,
                ActionType.SUPPORT,
                ActionType.OBJECTION_HANDLING
            ],
            restrictions=[
                "Não pode agendar consultas",
                "Foque em suporte pós-consulta e quebra de objeções"
            ]
        ),

        CustomerStatus.PURCHASED: AllowedActions(
            actions=[
                ActionType.CLARIFY,
                ActionType.SUPPORT,
                ActionType.POST_SALE_SUPPORT,
                ActionType.OBJECTION_HANDLING
            ],
            restrictions=[
                "Não pode agendar consultas",
                "Foque em suporte pós-venda"
            ]
        ),

        CustomerStatus.LEAD: AllowedActions(
            actions=[
                ActionType.SCHEDULE_NEW,
                ActionType.QUALIFY,
                ActionType.INFORM,
                ActionType.CLARIFY
            ],
            restrictions=[
                "Lead sem histórico - pode realizar agendamento completo"
            ]
        )
    }

    return action_map[status]


def create_routing_context(
    contact_phone: str,
    company_id: int,
    user_input: str = "",
    conversation_history: Optional[List[Union[Dict[str, Any], Any]]] = None
) -> StatusDetectionContext:
    """Factory function to create detection context"""
    return StatusDetectionContext(
        contact_phone=contact_phone,
        company_id=company_id,
        user_input=user_input,
        conversation_history=conversation_history or []
    )