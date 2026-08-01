"""
Pydantic models for appointment state management.
Type-safe data structures for company conversation flows.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Literal, Dict, Any
from datetime import datetime
import re


class AppointmentState(BaseModel):
    """Complete state of an appointment conversation"""

    # Identification
    phone: str = Field(..., description="Customer phone number")
    company_id: int = Field(..., description="Company identifier")

    # Appointment data
    treatment: Optional[str] = Field(None, description="Type of treatment requested")
    customer_type: Optional[Literal["novo", "existente"]] = Field(None, description="New or existing customer")
    customer_name: Optional[str] = Field(None, description="Customer full name")
    appointment_date: Optional[str] = Field(None, description="Appointment date in DD/MM/YYYY format")
    appointment_time: Optional[str] = Field(None, description="Appointment time in HH:MM format")

    # Conversation state
    current_step: int = Field(0, ge=0, le=8, description="Current conversation step")

    # Confirmation flags
    confirmed: bool = Field(False, description="If appointment is confirmed")
    price_shown: bool = Field(False, description="If price was shown to customer")
    slot_verified: bool = Field(False, description="If slot availability was verified")
    user_confirmed_slot: bool = Field(False, description="If user explicitly confirmed the slot")

    # Tracking fields
    last_offered_slots: List[str] = Field(default_factory=list, description="Last slots offered to customer")
    confirmation_attempts: int = Field(0, description="Number of confirmation attempts")

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    conversation_id: Optional[str] = Field(None, description="Unique conversation identifier")

    # Additional context
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional context data")

    @field_validator('appointment_date')
    @classmethod
    def validate_date_format(cls, v: Optional[str]) -> Optional[str]:
        """Validate date format DD/MM/YYYY"""
        if v is None:
            return v
        pattern = r'^\d{2}/\d{2}/\d{4}$'
        if not re.match(pattern, v):
            raise ValueError("Date must be in DD/MM/YYYY format")
        return v

    @field_validator('appointment_time')
    @classmethod
    def validate_time_format(cls, v: Optional[str]) -> Optional[str]:
        """Validate time format HH:MM"""
        if v is None:
            return v
        pattern = r'^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$'
        if not re.match(pattern, v):
            raise ValueError("Time must be in HH:MM format")
        return v

    def is_ready_for_confirmation(self) -> bool:
        """Check if all required fields are filled for confirmation"""
        required_fields = [
            self.treatment,
            self.customer_type,
            self.customer_name,
            self.appointment_date,
            self.appointment_time
        ]
        return all(required_fields) and self.slot_verified and self.price_shown

    def get_missing_fields(self) -> List[str]:
        """Get list of missing required fields"""
        missing = []
        field_mapping = {
            'treatment': 'tratamento',
            'customer_type': 'tipo de cliente',
            'customer_name': 'nome completo',
            'appointment_date': 'data',
            'appointment_time': 'horário'
        }

        for field, label in field_mapping.items():
            if not getattr(self, field):
                missing.append(label)

        return missing

    def reset_slot_selection(self):
        """Reset slot selection fields"""
        self.appointment_date = None
        self.appointment_time = None
        self.slot_verified = False
        self.user_confirmed_slot = False
        self.last_offered_slots = []


class TransitionContext(BaseModel):
    """Context for state transition decisions"""

    current_state: AppointmentState
    user_input: str
    extracted_data: Dict[str, Any] = Field(default_factory=dict, description="Data extracted from user input")
    available_slots: List[str] = Field(default_factory=list, description="Available appointment slots")

    # LLM response context
    llm_response: Optional[str] = Field(None, description="Last LLM response to user")
    offered_slots_in_response: List[str] = Field(default_factory=list, description="Slots offered in LLM response")

    def has_slot_selection(self) -> bool:
        """Check if user selected a slot"""
        return bool(
            self.extracted_data.get('data') or
            self.extracted_data.get('horario') or
            self.extracted_data.get('appointment_date') or
            self.extracted_data.get('appointment_time')
        )

    def get_selected_slot(self) -> Optional[str]:
        """Get selected slot in DD/MM/YYYY HH:MM format"""
        date = (self.extracted_data.get('data') or
                self.extracted_data.get('appointment_date') or
                self.current_state.appointment_date)
        time = (self.extracted_data.get('horario') or
                self.extracted_data.get('appointment_time') or
                self.current_state.appointment_time)

        if date and time:
            return f"{date} {time}"
        return None


class TransitionDecision(BaseModel):
    """Decision for state transition"""

    should_advance: bool = Field(description="Whether to advance to next step")
    next_step: Optional[int] = Field(None, description="Next step number if advancing")
    reason: str = Field(description="Reason for the decision")

    # Validation results
    missing_fields: List[str] = Field(default_factory=list, description="Missing required fields")
    validation_errors: List[str] = Field(default_factory=list, description="Validation errors found")

    # Actions to take
    actions: List[str] = Field(default_factory=list, description="Actions to perform")
    update_fields: Dict[str, Any] = Field(default_factory=dict, description="Fields to update in state")

    # Confirmation tracking
    needs_confirmation: bool = Field(False, description="If user confirmation is needed")
    confirmation_message: Optional[str] = Field(None, description="Message to confirm with user")

    def has_errors(self) -> bool:
        """Check if there are any validation errors"""
        return bool(self.validation_errors)

    def has_missing_fields(self) -> bool:
        """Check if there are missing fields"""
        return bool(self.missing_fields)
