"""
Customer Context Module - Contexto estruturado para conversas de clientes

Este módulo implementa contexto estruturado que trabalha EM CONJUNTO com o prompt atual,
não substitui. Adiciona visibilidade e tracing sem alterar o comportamento existente.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
import logging
import json

logger = logging.getLogger(__name__)

class CustomerContext(BaseModel):
    """
    Contexto estruturado do cliente - compatível com prompt atual

    Este contexto mapeia as etapas do prompt existente em prompts.py,
    fornecendo visibilidade e tracing sem alterar o comportamento.
    """

    # ========== IDENTIFICAÇÃO ==========
    company_id: int = Field(..., description="ID da empresa")
    phone: str = Field(..., description="Telefone do cliente")

    # ========== DADOS DA EMPRESA (para compatibilidade com tools) ==========
    company_data: Dict[str, Any] = Field(default_factory=dict, description="Dados da empresa")
    db: Optional[Any] = Field(default=None, exclude=True, description="Conexão com banco (não serializada)")

    # ========== CONTROLE DE FLUXO ==========
    current_stage: str = Field(
        default="etapa_0",
        description="Etapa atual do fluxo (mapeia prompt existente)"
    )
    conversation_step: int = Field(default=0, description="Número da interação")

    # ========== INFORMAÇÕES CAPTURADAS ==========
    # Essas variáveis mapeiam diretamente para as [VARIAVEL:X=VALOR] do prompt atual
    pain_description: Optional[str] = Field(
        default=None,
        description="Descrição da dor/sintoma - mapeia [VARIAVEL:dor=VALOR]"
    )
    treatment_interest: Optional[str] = Field(
        default=None,
        description="Tratamento de interesse - mapeia [VARIAVEL:tratamento=VALOR]"
    )
    customer_type: Optional[str] = Field(
        default=None,
        description="Tipo de cliente - mapeia [VARIAVEL:cliente=VALOR]"
    )
    customer_name: Optional[str] = Field(default=None, description="Nome completo do cliente")

    # ========== ESTADO DO AGENDAMENTO ==========
    selected_date: Optional[str] = Field(default=None, description="Data selecionada para consulta")
    selected_time: Optional[str] = Field(default=None, description="Horário selecionado")
    suggested_slots: List[str] = Field(default_factory=list, description="Horários sugeridos ao usuário")
    appointment_confirmed: bool = Field(default=False, description="Se agendamento foi confirmado")
    appointment_protocol: Optional[str] = Field(default=None, description="Protocolo do agendamento")
    price_accepted: bool = Field(default=False, description="Se o cliente aceitou o valor da consulta")

    # Aliases para compatibilidade
    @property
    def selected_appointment_date(self):
        return self.selected_date

    @property
    def selected_appointment_time(self):
        return self.selected_time

    # ========== HISTÓRICO DE ETAPAS ==========
    stage_history: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Histórico de mudanças de etapa para análise"
    )

    # ========== ESTADO DE COLETA ==========
    collection_state: Optional[str] = Field(
        default=None,
        description="Estado de coleta ativo: 'referral', 'scheduling', 'confirmation', None"
    )
    collection_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Dados temporários da coleta em andamento"
    )
    collection_started_at: Optional[datetime] = Field(
        default=None,
        description="Quando a coleta atual começou"
    )

    # ========== METADADOS ==========
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    last_interaction: Optional[str] = Field(default=None, description="Última mensagem do usuário")

    # ========== CONFIGURAÇÃO ==========
    model_config = {
        "json_encoders": {
            datetime: lambda v: v.isoformat()
        }
    }

    def advance_stage(self, new_stage: str, captured_info: str = "", user_input: str = "") -> None:
        """
        Avança para próxima etapa com logging automático

        Args:
            new_stage: Nova etapa (etapa_0, etapa_1, etc.)
            captured_info: Informação capturada nesta etapa
            user_input: Entrada do usuário que causou a mudança
        """
        old_stage = self.current_stage
        old_step = self.conversation_step

        # Atualizar estado
        self.current_stage = new_stage
        self.conversation_step += 1
        self.updated_at = datetime.now()
        self.last_interaction = user_input[:200] if user_input else None

        # Registrar no histórico
        stage_change = {
            "from_stage": old_stage,
            "to_stage": new_stage,
            "step": self.conversation_step,
            "captured_info": captured_info[:100] if captured_info else "",
            "timestamp": self.updated_at.isoformat(),
            "user_input": user_input[:100] if user_input else ""
        }
        self.stage_history.append(stage_change)

        # Log estruturado para tracing
        active_logger = logging.getLogger(__name__)
        active_logger.info(
            f"Stage transition: {old_stage} → {new_stage}",
            extra={
                "event": "stage_transition",
                "company_id": self.company_id,
                "phone": self.phone,
                "from_stage": old_stage,
                "to_stage": new_stage,
                "conversation_step": self.conversation_step,
                "captured_info": captured_info[:100] if captured_info else "",
                "timestamp": self.updated_at.isoformat()
            }
        )

    def capture_information(self, field: str, value: str, advance_to: Optional[str] = None) -> None:
        """
        Captura informação específica com logging

        Args:
            field: Campo a ser atualizado (pain_description, treatment_interest, etc.)
            value: Valor capturado
            advance_to: Se deve avançar para nova etapa
        """
        if hasattr(self, field):
            old_value = getattr(self, field)
            setattr(self, field, value)
            self.updated_at = datetime.now()

            # Log estruturado
            active_logger = logging.getLogger(__name__)
            active_logger.info(
                f"Information captured: {field} = {value[:50]}...",
                extra={
                    "event": "info_capture",
                    "company_id": self.company_id,
                    "phone": self.phone,
                    "field": field,
                    "old_value": old_value[:50] if old_value else None,
                    "new_value": value[:50],
                    "current_stage": self.current_stage,
                    "timestamp": self.updated_at.isoformat()
                }
            )

            # Avançar etapa se especificado
            if advance_to:
                self.advance_stage(advance_to, f"captured {field}: {value[:30]}")
        else:
            logging.getLogger(__name__).warning(f"Field '{field}' not found in CustomerContext")

    def get_stage_summary(self) -> Dict[str, Any]:
        """Retorna resumo do estado atual para debugging"""
        return {
            "company_id": self.company_id,
            "phone": self.phone,
            "current_stage": self.current_stage,
            "conversation_step": self.conversation_step,
            "captured_data": {
                "pain": self.pain_description,
                "treatment": self.treatment_interest,
                "customer_type": self.customer_type,
                "name": self.customer_name
            },
            "appointment": {
                "date": self.selected_date,
                "time": self.selected_time,
                "confirmed": self.appointment_confirmed,
                "protocol": self.appointment_protocol
            },
            "updated_at": self.updated_at.isoformat()
        }

    def to_prompt_variables(self) -> Dict[str, Any]:
        """
        Converte contexto em variáveis para o prompt atual

        Retorna variáveis que podem ser adicionadas ao _build_prompt_variables()
        sem quebrar o sistema existente.
        """
        return {
            # Informações de estado para o prompt
            'current_stage_info': self.current_stage,
            'conversation_step': str(self.conversation_step),

            # Informações capturadas (compatível com sistema atual)
            'captured_pain': self.pain_description or '',
            'captured_treatment': self.treatment_interest or '',
            'captured_customer_type': self.customer_type or '',
            'captured_name': self.customer_name or '',

            # Estado do agendamento
            'selected_appointment_date': self.selected_date or '',
            'selected_appointment_time': self.selected_time or '',
            'suggested_slots': ','.join(self.suggested_slots) if self.suggested_slots else '',
            'appointment_confirmed': str(self.appointment_confirmed).lower(),
            'appointment_protocol': self.appointment_protocol or '',

            # Metadados úteis
            'last_interaction': self.last_interaction or '',
            'stage_history_count': str(len(self.stage_history)),
        }

    def is_information_complete(self) -> Dict[str, bool]:
        """Verifica quais informações já foram capturadas"""
        return {
            "has_pain_or_treatment": bool(self.pain_description or self.treatment_interest),
            "has_customer_type": bool(self.customer_type),
            "has_name": bool(self.customer_name and len(self.customer_name.split()) >= 2),
            "has_appointment_selection": bool(self.selected_date and self.selected_time),
            "is_appointment_confirmed": self.appointment_confirmed
        }

    def get_next_required_info(self) -> Optional[str]:
        """Retorna próxima informação necessária baseada no fluxo do prompt"""
        completeness = self.is_information_complete()

        if not completeness["has_pain_or_treatment"]:
            return "pain_or_treatment"
        elif not completeness["has_customer_type"]:
            return "customer_type"
        elif not completeness["has_appointment_selection"]:
            return "appointment_time"
        elif not completeness["has_name"]:
            return "customer_name"
        elif not completeness["is_appointment_confirmed"]:
            return "confirmation"
        else:
            return None  # Fluxo completo

    def set_collection_mode(self, mode: str, data: Dict[str, Any] = None) -> None:
        """
        Ativa modo de coleta específico

        Args:
            mode: Tipo de coleta ('referral', 'scheduling', 'confirmation')
            data: Dados iniciais para a coleta
        """
        self.collection_state = mode
        self.collection_data = data or {}
        self.collection_started_at = datetime.now()
        self.updated_at = datetime.now()

        logger.info(
            f"Collection mode activated: {mode}",
            extra={
                "event": "collection_mode_set",
                "company_id": self.company_id,
                "phone": self.phone,
                "mode": mode,
                "data": json.dumps(self.collection_data)[:100],
                "timestamp": self.collection_started_at.isoformat()
            }
        )

    def clear_collection_mode(self) -> None:
        """Limpa modo de coleta e dados temporários"""
        old_mode = self.collection_state
        old_data = self.collection_data.copy()

        self.collection_state = None
        self.collection_data = {}
        self.collection_started_at = None
        self.updated_at = datetime.now()

        logger.info(
            f"Collection mode cleared: {old_mode}",
            extra={
                "event": "collection_mode_cleared",
                "company_id": self.company_id,
                "phone": self.phone,
                "old_mode": old_mode,
                "old_data": json.dumps(old_data)[:100],
                "timestamp": self.updated_at.isoformat()
            }
        )

    def is_in_collection_mode(self) -> bool:
        """Verifica se está em modo de coleta ativo"""
        return self.collection_state is not None

    def get_collection_context(self) -> Optional[Dict[str, Any]]:
        """Retorna contexto da coleta atual se ativo"""
        if not self.is_in_collection_mode():
            return None

        return {
            "mode": self.collection_state,
            "data": self.collection_data,
            "started_at": self.collection_started_at.isoformat() if self.collection_started_at else None,
            "duration_seconds": (datetime.now() - self.collection_started_at).total_seconds() if self.collection_started_at else 0
        }


class CustomerContextManager:
    """
    Gerenciador de contexto de clientes

    Responsável por carregar, salvar e gerenciar contextos de clientes
    de forma compatível com o sistema atual.
    """

    def __init__(self, db_session=None):
        self.db_session = db_session
        self.logger = logging.getLogger(f"{__name__}.CustomerContextManager")

    def create_context(self, company_id: int, phone: str) -> CustomerContext:
        """Cria novo contexto para cliente"""
        context = CustomerContext(company_id=company_id, phone=phone)

        self.logger.info(
            f"Created new customer context",
            extra={
                "event": "context_created",
                "company_id": company_id,
                "phone": phone,
                "timestamp": context.created_at.isoformat()
            }
        )

        return context

    def load_context(self, company_id: int, phone: str) -> Optional[CustomerContext]:
        """
        Carrega contexto existente do banco de dados

        TODO: Implementar persistência no banco quando necessário
        Por enquanto retorna None (fallback para criação)
        """
        # Futura implementação com banco de dados
        # context_data = self.db_session.query(...).filter_by(company_id=company_id, phone=phone).first()
        # if context_data:
        #     return CustomerContext(**context_data.to_dict())
        return None

    def save_context(self, context: CustomerContext) -> None:
        """
        Salva contexto no banco de dados

        TODO: Implementar persistência no banco quando necessário
        Por enquanto apenas loga (para não quebrar sistema atual)
        """
        self.logger.info(
            f"Saving customer context",
            extra={
                "event": "context_saved",
                "company_id": context.company_id,
                "phone": context.phone,
                "current_stage": context.current_stage,
                "conversation_step": context.conversation_step,
                "timestamp": context.updated_at.isoformat()
            }
        )

        # Futura implementação com banco de dados
        # context_record = CustomerContextTable(**context.dict())
        # self.db_session.merge(context_record)
        # self.db_session.commit()

    def get_or_create_context(self, company_id: int, phone: str) -> CustomerContext:
        """
        Obtém contexto existente ou cria novo

        Este é o método principal usado pelo sistema
        """
        context = self.load_context(company_id, phone)
        if context is None:
            context = self.create_context(company_id, phone)

        return context
