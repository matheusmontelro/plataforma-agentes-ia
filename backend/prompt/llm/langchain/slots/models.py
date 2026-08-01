"""
Modelos Pydantic para o Sistema de Agendamento
==============================================

Define estruturas de dados validadas para todo o fluxo de agendamento.
"""

from datetime import datetime, time
from typing import Optional, List, Literal, Dict, Any
from pydantic import BaseModel, Field, validator
import pytz

SP_TZ = pytz.timezone('America/Sao_Paulo')


class TimeConstraints(BaseModel):
    """Restrições temporais para agendamento"""
    earliest_time: Optional[time] = Field(None, description="Horário mais cedo aceitável")
    latest_time: Optional[time] = Field(None, description="Horário mais tarde aceitável")
    preferred_time: Optional[time] = Field(None, description="Horário preferencial")

    @validator('earliest_time', 'latest_time', 'preferred_time')
    def validate_business_hours(cls, v):
        if v:
            if v.hour < 6 or v.hour > 22:
                raise ValueError("Horário deve estar entre 6:00 e 22:00")
        return v


class SchedulingIntent(BaseModel):
    """Intenção de agendamento extraída da mensagem do usuário"""
    has_scheduling_intent: bool = Field(
        default=False,
        description="Se o usuário demonstrou intenção de agendar"
    )

    # Preferências temporais
    preferred_date: Optional[datetime] = Field(None, description="Data preferida")
    preferred_day_of_week: Optional[int] = Field(
        None,
        description="Dia da semana (0=Segunda, 6=Domingo)"
    )
    preferred_period: Optional[Literal["morning", "afternoon", "evening", "night"]] = Field(
        None,
        description="Período do dia preferido"
    )

    # Restrições
    time_constraints: Optional[TimeConstraints] = None
    date_flexibility_days: int = Field(
        default=7,
        description="Flexibilidade em dias para encontrar horário"
    )

    # Contexto
    urgency_level: Literal["low", "medium", "high"] = Field(
        default="medium",
        description="Nível de urgência do agendamento"
    )
    specific_requests: List[str] = Field(
        default_factory=list,
        description="Pedidos específicos mencionados"
    )

    # Metadados
    confidence_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confiança na extração da intenção"
    )
    extraction_reasoning: str = Field(
        default="",
        description="Raciocínio da extração para debug"
    )

    @validator('preferred_date')
    def validate_future_date(cls, v):
        if v:
            now = datetime.now(SP_TZ)
            if v.replace(tzinfo=SP_TZ) < now:
                raise ValueError("Data deve ser futura")
        return v

    @validator('preferred_day_of_week')
    def validate_day_of_week(cls, v):
        if v is not None and (v < 0 or v > 6):
            raise ValueError("Dia da semana deve estar entre 0 e 6")
        return v


class SlotInfo(BaseModel):
    """Informações detalhadas de um slot disponível"""
    datetime_obj: datetime
    formatted_string: str = Field(..., description="String formatada DD/MM/YYYY HH:MM")
    period: Literal["morning", "afternoon", "evening", "night"]
    day_of_week: int
    day_name_pt: str
    is_today: bool = False
    is_tomorrow: bool = False
    days_from_today: int

    # Metadados para ranking
    compatibility_score: float = Field(default=1.0, ge=0.0, le=1.0)
    distance_from_preferred: Optional[int] = Field(None, description="Minutos de diferença")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class SlotSelection(BaseModel):
    """Resultado da seleção de slots"""
    selected_slots: List[SlotInfo] = Field(
        ...,
        description="Slots selecionados ordenados por relevância"
    )

    # Estatísticas da busca
    total_available: int = Field(..., description="Total de slots disponíveis")
    total_filtered: int = Field(..., description="Total após filtros")
    filters_applied: List[str] = Field(default_factory=list)

    # Fallback info
    used_fallback: bool = Field(default=False)
    fallback_reason: Optional[str] = None
    expanded_search_days: int = Field(default=0)

    # Sugestões
    suggested_count: int = Field(default=2, le=100)
    suggestion_reasoning: str = Field(
        default="",
        description="Por que estes slots foram sugeridos"
    )

    # Removido validador de contagem - agora permite retornar todos os slots filtrados


class ConversationContext(BaseModel):
    """Contexto completo da conversa para decisões"""
    phone: str
    company_id: int
    current_step: int = Field(default=0, ge=0, le=8)

    # Estado da conversa
    collected_data: Dict[str, Any] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)

    # Histórico
    message_count: int = Field(default=0)
    last_bot_message: Optional[str] = None
    last_user_message: Optional[str] = None

    # Flags
    has_existing_appointment: bool = False
    is_rescheduling: bool = False
    is_cancelling: bool = False
    in_cooldown: bool = False
    cooldown_remaining_seconds: int = 0

    # Análise
    user_sentiment: Literal["positive", "neutral", "negative"] = "neutral"
    conversation_quality_score: float = Field(default=0.5, ge=0.0, le=1.0)


class SchedulingResult(BaseModel):
    """Resultado final do processamento de agendamento"""
    success: bool
    message: str

    # Dados do agendamento
    appointment_data: Optional[Dict[str, Any]] = None
    selected_slot: Optional[SlotInfo] = None

    # Próximas ações
    next_step: int
    requires_confirmation: bool = False
    missing_information: List[str] = Field(default_factory=list)

    # Debugging
    processing_time_ms: int
    tokens_used: int
    chain_trace: List[str] = Field(default_factory=list)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }