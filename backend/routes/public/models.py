from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Dict, List, Optional, Any
from datetime import time
import re


class UserSetup(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    name: str = Field(..., min_length=2, max_length=100)
    phone: str = Field(..., pattern=r"^\d{10,11}$")


class CompanySetup(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    cnpj: str = Field(..., pattern=r"^\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}$")
    address: str = Field(..., min_length=5, max_length=300)
    city: str = Field(..., min_length=2, max_length=100)
    state: str = Field(..., pattern=r"^[A-Z]{2}$")
    phone: Optional[str] = Field(None, pattern=r"^\d{10,11}$")
    name_company: Optional[str] = Field(None, min_length=2, max_length=200, description="Nome customizado da empresa")
    logo_base64: Optional[str] = Field(None, description="Logo da empresa em base64")
    business_type_id: Optional[int] = Field(default=1, description="ID do tipo de negócio (padrão: 1 = business_company)")


class AIWindowPeriod(BaseModel):
    enabled: bool = True
    start: str = Field(..., pattern=r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$")
    end: str = Field(..., pattern=r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$")


class AIWindowDay(BaseModel):
    morning: Optional[AIWindowPeriod] = None
    afternoon: Optional[AIWindowPeriod] = None
    night: Optional[AIWindowPeriod] = None
    dawn: Optional[AIWindowPeriod] = None


class AIWindowSetup(BaseModel):
    timezone: str = Field(default="America/Sao_Paulo")
    time_windows: Dict[str, AIWindowDay] = Field(
        default_factory=lambda: {
            "monday": AIWindowDay(
                morning=AIWindowPeriod(enabled=True, start="08:00", end="12:00"),
                afternoon=AIWindowPeriod(enabled=True, start="13:00", end="18:00"),
                night=AIWindowPeriod(enabled=False, start="18:00", end="22:00"),
                dawn=AIWindowPeriod(enabled=False, start="22:00", end="06:00")
            ),
            "tuesday": AIWindowDay(
                morning=AIWindowPeriod(enabled=True, start="08:00", end="12:00"),
                afternoon=AIWindowPeriod(enabled=True, start="13:00", end="18:00"),
                night=AIWindowPeriod(enabled=False, start="18:00", end="22:00"),
                dawn=AIWindowPeriod(enabled=False, start="22:00", end="06:00")
            ),
            "wednesday": AIWindowDay(
                morning=AIWindowPeriod(enabled=True, start="08:00", end="12:00"),
                afternoon=AIWindowPeriod(enabled=True, start="13:00", end="18:00"),
                night=AIWindowPeriod(enabled=False, start="18:00", end="22:00"),
                dawn=AIWindowPeriod(enabled=False, start="22:00", end="06:00")
            ),
            "thursday": AIWindowDay(
                morning=AIWindowPeriod(enabled=True, start="08:00", end="12:00"),
                afternoon=AIWindowPeriod(enabled=True, start="13:00", end="18:00"),
                night=AIWindowPeriod(enabled=False, start="18:00", end="22:00"),
                dawn=AIWindowPeriod(enabled=False, start="22:00", end="06:00")
            ),
            "friday": AIWindowDay(
                morning=AIWindowPeriod(enabled=True, start="08:00", end="12:00"),
                afternoon=AIWindowPeriod(enabled=True, start="13:00", end="18:00"),
                night=AIWindowPeriod(enabled=False, start="18:00", end="22:00"),
                dawn=AIWindowPeriod(enabled=False, start="22:00", end="06:00")
            ),
            "saturday": AIWindowDay(
                morning=AIWindowPeriod(enabled=False, start="08:00", end="12:00"),
                afternoon=AIWindowPeriod(enabled=False, start="13:00", end="18:00"),
                night=AIWindowPeriod(enabled=False, start="18:00", end="22:00"),
                dawn=AIWindowPeriod(enabled=False, start="22:00", end="06:00")
            ),
            "sunday": AIWindowDay(
                morning=AIWindowPeriod(enabled=False, start="08:00", end="12:00"),
                afternoon=AIWindowPeriod(enabled=False, start="13:00", end="18:00"),
                night=AIWindowPeriod(enabled=False, start="18:00", end="22:00"),
                dawn=AIWindowPeriod(enabled=False, start="22:00", end="06:00")
            )
        }
    )


class GoogleCalendarSetup(BaseModel):
    calendar_id: str = Field(..., pattern=r"^[a-zA-Z0-9]+@group\.calendar\.google\.com$")
    enabled: bool = True


class Treatment(BaseModel):
    treatmentTitle: str
    description: str


class DaySchedule(BaseModel):
    open: bool = True
    morningEnabled: bool = True
    morningStart: str = "08:00"
    morningEnd: str = "12:00"
    afternoonEnabled: bool = True
    afternoonStart: str = "14:00"
    afternoonEnd: str = "18:00"


class PromptConfigSetup(BaseModel):
    # Assistant Identity
    assistant_name: str = Field(..., min_length=2, max_length=100)
    assistant_role: str = Field(default="Consultora de Atendimento")
    assistant_responsibility: str = Field(default="Agendar consultas e tirar dúvidas sobre tratamentos")
    assistant_formality: str = Field(default="intermediário")
    assistant_tone: str = Field(default="empático")
    assistant_language: str = Field(default="Português")

    # Company Info
    company_name: str
    company_location: str
    company_address: str
    company_phone_fixed: Optional[str] = ""
    company_whatsapp: str
    company_maps: Optional[str] = ""
    company_instagram: Optional[str] = ""
    company_facebook: Optional[str] = ""
    company_site: Optional[str] = ""
    company_history: Optional[str] = ""

    # Team and Specialties
    technical_responsible: str
    treatments: List[Treatment] = Field(default_factory=list)

    # Scheduling Config (dias individuais)
    scheduling_config_monday: Optional[DaySchedule] = Field(default_factory=DaySchedule)
    scheduling_config_tuesday: Optional[DaySchedule] = Field(default_factory=DaySchedule)
    scheduling_config_wednesday: Optional[DaySchedule] = Field(default_factory=DaySchedule)
    scheduling_config_thursday: Optional[DaySchedule] = Field(default_factory=DaySchedule)
    scheduling_config_friday: Optional[DaySchedule] = Field(default_factory=DaySchedule)
    scheduling_config_saturday: Optional[DaySchedule] = Field(default_factory=lambda: DaySchedule(afternoonEnabled=False))
    scheduling_config_sunday: Optional[DaySchedule] = Field(default_factory=lambda: DaySchedule(open=False, morningEnabled=False, afternoonEnabled=False))

    consultation_duration: int = Field(default=60)
    number_of_suggestions: int = Field(default=3)

    # Financial Config
    accepts_health_insurance: bool = False
    health_insurance_plans: Optional[str] = ""
    payment_methods: List[str] = Field(default_factory=lambda: ["Pix", "Cartão de Crédito", "Cartão de Débito", "Dinheiro"])
    installment_conditions: Optional[str] = ""
    evaluation_price: Optional[str] = ""
    treatment_prices: Optional[str] = ""

    # Conversation Flow
    step0: str
    step1First: Optional[str] = ""
    step1Second: Optional[str] = ""
    step2: Optional[str] = ""
    step3: Optional[str] = ""
    max_tokens: int = Field(default=1000)

    # Redirect configurations
    financial_redirect_type: str = Field(default="fixo")
    financial_redirect_number: Optional[str] = ""
    regular_redirect_type: str = Field(default="fixo")
    regular_redirect_number: Optional[str] = ""
    maintenance_redirect_type: str = Field(default="fixo")
    maintenance_redirect_number: Optional[str] = ""
    active_customers_redirect_type: str = Field(default="fixo")
    active_customers_redirect_number: Optional[str] = ""

    few_shots: List[Dict[str, Any]] = Field(default_factory=list)


class CompleteCompanySetup(BaseModel):
    """Modelo completo para setup de uma nova empresa"""
    user: UserSetup
    company: CompanySetup
    ai_window: Optional[AIWindowSetup] = Field(default_factory=AIWindowSetup)
    google_calendar: GoogleCalendarSetup
    prompt_config: PromptConfigSetup
    api_key: Optional[str] = Field(None, description="API Key para autenticação da requisição")


class CompanySetupResponse(BaseModel):
    """Resposta do setup completo"""
    success: bool
    data: Dict[str, Any]
    message: str = "Empresa configurada com sucesso"


class CompanySetupError(BaseModel):
    """Modelo de erro para o setup"""
    success: bool = False
    error: str
    details: Optional[Dict[str, Any]] = None