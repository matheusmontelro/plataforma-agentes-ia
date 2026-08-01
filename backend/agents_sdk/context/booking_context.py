"""
Booking Context - Shared context for appointment booking across agents
Enables seamless handoffs between coordinator_agent and specialized agents
"""

from pydantic import BaseModel
from typing import Optional, Dict, Any

class BookingContext(BaseModel):
    """
    Unified context for appointment booking.
    Shared between coordinator_agent and third_party_booking_agent.
    """

    # Core company information
    company_id: int
    company_data: Dict[str, Any]

    # Database connection for agent config access
    db: Optional[Any] = None

    # Requester information (who is making the appointment)
    requester_phone: str
    requester_name: Optional[str] = None

    # Appointment details
    selected_date: Optional[str] = None
    selected_time: Optional[str] = None
    treatment_type: Optional[str] = "Consulta de Avaliação"

    # Third-party specific fields
    is_third_party: bool = False
    relationship: Optional[str] = None  # mãe, pai, filho, esposa, marido, etc.
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None

    # Collection state tracking
    collection_stage: str = "initial"  # initial, collecting_name, collecting_phone, checking_customer_status, confirming
    is_existing_customer: Optional[bool] = None  # True if already customer, False if first time

    # Conversation context
    current_stage: Optional[str] = None
    conversation_step: Optional[int] = None

    # Detection results
    detection_confidence: Optional[float] = None
    detection_reasoning: Optional[str] = None

    @property
    def phone(self) -> str:
        """Alias for requester_phone to maintain compatibility"""
        return self.requester_phone

    def is_ready_for_confirmation(self) -> bool:
        """Check if all required data for third-party booking is collected"""
        if not self.is_third_party:
            return False

        return all([
            self.customer_name,
            self.customer_phone,
            self.selected_date,
            self.selected_time,
            self.relationship
        ])

    def get_missing_fields(self) -> list:
        """Return list of missing required fields"""
        missing = []
        if not self.customer_name:
            missing.append("nome_cliente")
        if not self.customer_phone:
            missing.append("telefone_cliente")
        if not self.selected_date:
            missing.append("data")
        if not self.selected_time:
            missing.append("horario")
        return missing