"""
Modelos de dados para o parser
"""
from typing import Optional, Literal
from datetime import date, time, datetime
from pydantic import BaseModel, Field, validator
import pytz

SP_TZ = pytz.timezone("America/Sao_Paulo")


class ExtractedData(BaseModel):
    """Dados extraídos da conversa - compatível com LLMUserData existente"""

    tratamento: Optional[str] = Field(
        None,
        description="Tipo de tratamento mencionado pelo usuário (ex: implante, clareamento, limpeza, etc). Use 'Consulta de Avaliação' APENAS se o usuário não especificou nenhum tratamento"
    )
    cliente: Optional[Literal["novo", "antigo"]] = Field(
        None,
        description="novo ou antigo"
    )
    nome: Optional[str] = Field(
        None,
        description="Nome do cliente",
        min_length=2
    )
    data: Optional[str] = Field(
        None,
        description="Data no formato DD/MM/YYYY"
    )
    horario: Optional[str] = Field(
        None,
        description="Horário no formato HH:MM"
    )
    agendamento_confirmado: bool = Field(
        False,
        description="Se o agendamento foi confirmado"
    )
    cancelar_agendamento: bool = Field(
        False,
        description="Se solicitou cancelamento"
    )
    motivo_cancelamento: Optional[str] = Field(
        None,
        description="Motivo do cancelamento"
    )

    @validator('data')
    def validate_date_format(cls, v):
        if v:
            try:
                # Valida formato DD/MM/YYYY
                datetime.strptime(v, "%d/%m/%Y")
            except ValueError:
                return None
        return v

    @validator('horario')
    def validate_time_format(cls, v):
        if v:
            try:
                # Valida formato HH:MM
                datetime.strptime(v, "%H:%M")
            except ValueError:
                return None
        return v


class ConversationContext(BaseModel):
    """Contexto da conversa para análise"""
    user_input: str
    assistant_output: str
    full_history: Optional[list] = []

    @property
    def is_simple_response(self) -> bool:
        """Verifica se é uma resposta simples como 'sim', 'ok', etc"""
        simple_responses = {
            'sim', 'ok', 'pode', 'pode ser', 'beleza', 'tá bom',
            'certo', 'isso', 'uhum', 'aham', 'claro', 'com certeza',
            'perfeito', 'ótimo', 'ta', 'tá', 'blz', 'fechou'
        }
        normalized = self.user_input.lower().strip()
        return normalized in simple_responses or len(normalized) < 5