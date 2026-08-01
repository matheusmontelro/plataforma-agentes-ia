"""
Modelos Pydantic para o sistema de gerenciamento de contexto.
"""

from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime


class InterventionType(str, Enum):
    """Tipos de intervenção detectados no contexto"""
    OPERATOR = "operator"
    USER_CONFIRMATION = "user_confirmation"
    CONTEXT_SHIFT = "context_shift"
    TOPIC_CHANGE = "topic_change"
    URGENCY_DETECTED = "urgency_detected"
    REFERENCE_PREVIOUS = "reference_previous"
    EMOTIONAL_SHIFT = "emotional_shift"
    NONE = "none"


class Entity(BaseModel):
    """Entidade extraída do contexto"""
    text: str = Field(description="Texto da entidade")
    type: str = Field(description="Tipo da entidade (pessoa, tratamento, data, etc)")
    confidence: float = Field(default=1.0, description="Confiança na extração")


class ContextAnalysis(BaseModel):
    """Resultado completo da análise de contexto"""
    intervention_type: InterventionType = Field(
        default=InterventionType.NONE,
        description="Tipo de intervenção detectada"
    )

    key_entities: List[Entity] = Field(
        default_factory=list,
        description="Entidades importantes extraídas (nomes, tratamentos, etc)"
    )

    key_topics: List[str] = Field(
        default_factory=list,
        description="Tópicos principais detectados na conversa"
    )

    temporal_references: List[str] = Field(
        default_factory=list,
        description="Referências temporais (datas, horários, períodos)"
    )

    action_items: List[str] = Field(
        default_factory=list,
        description="Ações mencionadas ou solicitadas"
    )

    emotional_tone: Optional[str] = Field(
        default=None,
        description="Tom emocional detectado (neutro, urgente, frustrado, satisfeito)"
    )

    requires_context_shift: bool = Field(
        default=False,
        description="Se requer mudança significativa de contexto"
    )

    context_instruction: str = Field(
        default="",
        description="Instrução de contexto gerada para o LLM"
    )

    confidence_score: float = Field(
        default=1.0,
        description="Confiança geral na análise"
    )

    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Metadados adicionais da análise"
    )


class ContextShift(BaseModel):
    """Registro de uma mudança de contexto na conversa"""
    timestamp: datetime = Field(description="Momento da mudança")
    message_index: int = Field(description="Índice da mensagem onde ocorreu")
    intervention_type: InterventionType = Field(description="Tipo de mudança")
    analysis: ContextAnalysis = Field(description="Análise completa do contexto")
    trigger: str = Field(description="O que disparou a mudança")


class InstructionTemplate(BaseModel):
    """Template para geração de instruções contextuais"""
    intervention_type: InterventionType = Field(description="Tipo de intervenção")
    template: str = Field(description="Template da instrução")
    variables: List[str] = Field(default_factory=list, description="Variáveis necessárias")
    priority: int = Field(default=1, description="Prioridade do template")
