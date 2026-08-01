"""
Workflow Principal com LangGraph
================================

Orquestra todo o fluxo de agendamento usando state machines.
"""

from typing import Dict, Any, List, Optional, Literal
from datetime import datetime
import logging
from dataclasses import dataclass, field

from langgraph.graph import StateGraph, END
from langchain.callbacks.manager import CallbackManagerForChainRun
from langchain_openai import ChatOpenAI
from sqlalchemy.orm import Session

from .models import (
    SchedulingIntent, SlotSelection, ConversationContext,
    SchedulingResult, SlotInfo
)
from .chains import create_scheduling_chain
from .memory import OptimizedSchedulingMemory, ConversationCache
from .callbacks import (
    SchedulingErrorHandler, TokenUsageHandler,
    PerformanceMonitor, DebugHandler
)
from .agents import create_scheduling_agent
from .utils import get_weekday_name_pt

logger = logging.getLogger(__name__)


@dataclass
class SchedulingState:
    """Estado completo do workflow de agendamento"""
    # Contexto
    company_id: int
    contact_phone: str
    user_message: str

    # Memória
    conversation_memory: Optional[OptimizedSchedulingMemory] = None
    conversation_context: Optional[ConversationContext] = None

    # Processamento
    scheduling_intent: Optional[SchedulingIntent] = None
    available_slots: List[str] = field(default_factory=list)
    slot_selection: Optional[SlotSelection] = None

    # Resultado
    response_text: str = ""
    scheduling_result: Optional[SchedulingResult] = None

    # Metadados
    processing_start: datetime = field(default_factory=datetime.now)
    errors: List[str] = field(default_factory=list)
    trace: List[str] = field(default_factory=list)


class SchedulingWorkflow:
    """
    Workflow principal para processamento de agendamento.

    Features:
    - State machine com LangGraph
    - Error handling robusto
    - Observabilidade completa
    - Cache de conversas
    """

    def __init__(
        self,
        db: Session,
        company_id: int,
        llm: Optional[ChatOpenAI] = None,
        enable_cache: bool = True,
        debug: bool = False
    ):
        self.db = db
        self.company_id = company_id
        self.debug = debug

        # LLM
        self.llm = llm or ChatOpenAI(
            model="gpt-4.1-mini-2025-04-14",
            temperature=0.7
        )

        # Cache
        self.cache = ConversationCache() if enable_cache else None

        # Callbacks
        self.callbacks = self._setup_callbacks()

        # Workflow
        self.workflow = self._build_workflow()

    def _setup_callbacks(self) -> list:
        """Configura callbacks para monitoramento"""
        handlers = [
            SchedulingErrorHandler(self.company_id, ""),
            TokenUsageHandler(max_tokens_per_request=4000),
            PerformanceMonitor()
        ]

        if self.debug:
            handlers.append(DebugHandler(verbose=True))

        return handlers

    def _build_workflow(self) -> StateGraph:
        """Constrói o grafo do workflow"""
        workflow = StateGraph(SchedulingState)

        # Define nós
        workflow.add_node("load_context", self.load_context)
        workflow.add_node("detect_intent", self.detect_intent)
        workflow.add_node("filter_slots", self.filter_slots)
        workflow.add_node("validate_slots", self.validate_slots)
        workflow.add_node("generate_response", self.generate_response)
        workflow.add_node("save_context", self.save_context)

        # Define transições
        workflow.set_entry_point("load_context")

        workflow.add_edge("load_context", "detect_intent")

        # Decisão baseada na intenção
        workflow.add_conditional_edges(
            "detect_intent",
            self.route_by_intent,
            {
                "scheduling": "filter_slots",
                "question": "generate_response",
                "other": "generate_response"
            }
        )

        workflow.add_edge("filter_slots", "validate_slots")
        workflow.add_edge("validate_slots", "generate_response")
        workflow.add_edge("generate_response", "save_context")
        workflow.add_edge("save_context", END)

        return workflow.compile()

    def process_user_input(
        self,
        user_input: str,
        contact_phone: str,
        **kwargs
    ) -> SchedulingResult:
        """
        Processa entrada do usuário através do workflow.

        Args:
            user_input: Mensagem do usuário
            contact_phone: Telefone do contato
            **kwargs: Parâmetros adicionais

        Returns:
            SchedulingResult com resposta e metadados
        """
        # Estado inicial
        initial_state = SchedulingState(
            company_id=self.company_id,
            contact_phone=contact_phone,
            user_message=user_input,
            processing_start=datetime.now()
        )

        # Atualiza phone no error handler
        if self.callbacks and len(self.callbacks) > 0:
            self.callbacks[0].contact_phone = contact_phone

        try:
            # Executa workflow
            final_state = self.workflow.invoke(
                initial_state,
                {"callbacks": self.callbacks}
            )

            # Monta resultado
            result = self._build_result(final_state)

            # Log de sucesso
            logger.info(f"Workflow concluído com sucesso para {contact_phone}")

            return result

        except Exception as e:
            logger.error(f"Erro no workflow: {e}")

            # Resultado de erro
            return SchedulingResult(
                success=False,
                message="Desculpe, ocorreu um erro. Por favor, tente novamente.",
                next_step=initial_state.conversation_context.current_step if initial_state.conversation_context else 0,
                processing_time_ms=int((datetime.now() - initial_state.processing_start).total_seconds() * 1000),
                tokens_used=0,
                chain_trace=initial_state.trace
            )

    # Funções dos nós do workflow

    def load_context(self, state: SchedulingState) -> SchedulingState:
        """Carrega contexto da conversa"""
        state.trace.append("load_context: início")

        # Tenta cache primeiro
        cache_key = f"{state.company_id}:{state.contact_phone}"

        if self.cache:
            cached_memory = self.cache.get(cache_key)
            if cached_memory:
                state.conversation_memory = cached_memory
                state.trace.append("load_context: memória do cache")
            else:
                # Cria nova memória
                state.conversation_memory = OptimizedSchedulingMemory(
                    llm=self.llm,
                    max_token_limit=2000
                )
                # Carrega histórico do banco
                self._load_history_from_db(state)
                # Salva no cache
                self.cache.set(cache_key, state.conversation_memory)
                state.trace.append("load_context: nova memória criada")
        else:
            # Sem cache
            state.conversation_memory = OptimizedSchedulingMemory(
                llm=self.llm,
                max_token_limit=2000
            )
            self._load_history_from_db(state)

        # Carrega contexto da conversa
        state.conversation_context = self._load_conversation_context(state)

        # Carrega slots disponíveis
        state.available_slots = self._load_available_slots(state)

        state.trace.append(f"load_context: {len(state.available_slots)} slots carregados")
        return state

    def detect_intent(self, state: SchedulingState) -> SchedulingState:
        """Detecta intenção de agendamento"""
        state.trace.append("detect_intent: início")

        try:
            # Prepara histórico para o chain
            conversation_history = []
            if state.conversation_memory:
                for msg in state.conversation_memory.chat_memory.messages[-5:]:
                    conversation_history.append(msg.content)

            # Chain de detecção
            chain = create_scheduling_chain(self.llm, self.callbacks)

            # Executa
            result = chain.invoke({
                "user_message": state.user_message,
                "conversation_history": "\n".join(conversation_history),
                "current_datetime": datetime.now().isoformat(),
                "current_weekday": get_weekday_name_pt(datetime.now().weekday()),
                "available_slots": state.available_slots,
                "suggested_count": 2
            })

            state.scheduling_intent = result.get("scheduling_intent")
            state.trace.append(f"detect_intent: intenção={state.scheduling_intent.has_scheduling_intent if state.scheduling_intent else False}")

        except Exception as e:
            logger.error(f"Erro na detecção de intenção: {e}")
            state.errors.append(f"detect_intent: {str(e)}")
            # Assume sem intenção de agendamento
            state.scheduling_intent = SchedulingIntent(has_scheduling_intent=False)

        return state

    def filter_slots(self, state: SchedulingState) -> SchedulingState:
        """Filtra slots baseado na intenção"""
        state.trace.append("filter_slots: início")

        if not state.scheduling_intent or not state.scheduling_intent.has_scheduling_intent:
            state.trace.append("filter_slots: sem intenção de agendamento")
            return state

        try:
            # Chain já inclui a filtragem
            # O resultado já vem do detect_intent
            # Aqui podemos fazer filtragens adicionais se necessário

            state.trace.append(f"filter_slots: {len(state.available_slots)} slots disponíveis")

        except Exception as e:
            logger.error(f"Erro na filtragem: {e}")
            state.errors.append(f"filter_slots: {str(e)}")

        return state

    def validate_slots(self, state: SchedulingState) -> SchedulingState:
        """Valida slots com agent inteligente"""
        state.trace.append("validate_slots: início")

        if not state.slot_selection or not state.slot_selection.selected_slots:
            state.trace.append("validate_slots: sem slots para validar")
            return state

        try:
            # Cria agent para validação
            from ..scheduling.scheduling_service import SchedulingService
            scheduling_service = SchedulingService(self.db, self.company_id)

            agent = create_scheduling_agent(
                self.db,
                scheduling_service,
                self.llm,
                verbose=self.debug
            )

            # Valida primeiros slots
            slots_to_validate = state.slot_selection.selected_slots[:3]
            validated_slots = []

            for slot in slots_to_validate:
                validation_result = agent.invoke({
                    "input": f"Verifique se o horário {slot.formatted_string} está disponível",
                    "current_datetime": datetime.now().isoformat(),
                    "user_intent": str(state.scheduling_intent),
                    "filtered_slots": [s.formatted_string for s in slots_to_validate]
                })

                # Analisa resultado do agent
                if "available': True" in str(validation_result):
                    validated_slots.append(slot)

                if len(validated_slots) >= 2:
                    break

            # Atualiza seleção com slots validados
            state.slot_selection.selected_slots = validated_slots
            state.trace.append(f"validate_slots: {len(validated_slots)} slots válidos")

        except Exception as e:
            logger.error(f"Erro na validação: {e}")
            state.errors.append(f"validate_slots: {str(e)}")
            # Mantém slots sem validação

        return state

    def generate_response(self, state: SchedulingState) -> SchedulingState:
        """Gera resposta final"""
        state.trace.append("generate_response: início")

        try:
            # Se tem slots selecionados, gera sugestão
            if state.slot_selection and state.slot_selection.selected_slots:
                slots_text = self._format_slot_suggestions(state.slot_selection)
                state.response_text = slots_text
            else:
                # Resposta genérica baseada no contexto
                state.response_text = self._generate_contextual_response(state)

            state.trace.append(f"generate_response: {len(state.response_text)} caracteres")

        except Exception as e:
            logger.error(f"Erro na geração de resposta: {e}")
            state.errors.append(f"generate_response: {str(e)}")
            state.response_text = "Desculpe, tive um problema ao processar sua mensagem. Pode repetir?"

        return state

    def save_context(self, state: SchedulingState) -> SchedulingState:
        """Salva contexto atualizado"""
        state.trace.append("save_context: início")

        try:
            # Salva na memória
            if state.conversation_memory:
                state.conversation_memory.save_context(
                    {"input": state.user_message},
                    {"output": state.response_text}
                )

            # Atualiza cache
            if self.cache:
                cache_key = f"{state.company_id}:{state.contact_phone}"
                self.cache.set(cache_key, state.conversation_memory)

            state.trace.append("save_context: concluído")

        except Exception as e:
            logger.error(f"Erro ao salvar contexto: {e}")
            state.errors.append(f"save_context: {str(e)}")

        return state

    def route_by_intent(self, state: SchedulingState) -> Literal["scheduling", "question", "other"]:
        """Decide rota baseada na intenção"""
        if not state.scheduling_intent:
            return "other"

        if state.scheduling_intent.has_scheduling_intent:
            return "scheduling"

        # Adicionar lógica para detectar perguntas
        question_keywords = ["quanto", "como", "onde", "qual", "quais", "?"]
        if any(kw in state.user_message.lower() for kw in question_keywords):
            return "question"

        return "other"

    # Funções auxiliares

    def _load_history_from_db(self, state: SchedulingState) -> None:
        """Carrega histórico do banco"""
        # TODO: Implementar carregamento real do banco
        # Por ora, simulação
        pass

    def _load_conversation_context(self, state: SchedulingState) -> ConversationContext:
        """Carrega contexto da conversa"""
        # TODO: Implementar carregamento real
        return ConversationContext(
            phone=state.contact_phone,
            company_id=state.company_id,
            current_step=0
        )

    def _load_available_slots(self, state: SchedulingState) -> List[str]:
        """Carrega slots disponíveis"""
        # TODO: Implementar carregamento real
        from ..scheduling.scheduling_service import SchedulingService

        try:
            service = SchedulingService(self.db, state.company_id)
            return service.get_next_available_slots()
        except:
            return []

    def _format_slot_suggestions(self, selection: SlotSelection) -> str:
        """Formata sugestões de slots"""
        if not selection.selected_slots:
            return "Desculpe, não encontrei horários disponíveis com seus critérios."

        slots = selection.selected_slots[:2]  # Máximo 2

        if len(slots) == 1:
            slot = slots[0]
            return f"Tenho disponível {slot.day_name_pt} ({slot.formatted_string}). Gostaria de agendar?"
        else:
            options = []
            for slot in slots:
                if slot.is_today:
                    when = "hoje"
                elif slot.is_tomorrow:
                    when = "amanhã"
                else:
                    when = f"{slot.day_name_pt}"

                options.append(f"- {when} às {slot.datetime_obj.strftime('%H:%M')}")

            return f"Tenho estes horários disponíveis:\n" + "\n".join(options) + "\n\nQual prefere?"

    def _generate_contextual_response(self, state: SchedulingState) -> str:
        """Gera resposta contextual genérica"""
        # TODO: Implementar geração baseada em contexto
        return "Como posso ajudar você hoje?"

    def _build_result(self, state: SchedulingState) -> SchedulingResult:
        """Constrói resultado final"""
        processing_time = int((datetime.now() - state.processing_start).total_seconds() * 1000)

        # Calcula tokens usados
        tokens_used = 0
        if self.callbacks:
            for handler in self.callbacks:
                if isinstance(handler, TokenUsageHandler):
                    summary = handler.get_usage_summary()
                    tokens_used = summary.get('total_tokens', 0)
                    break

        return SchedulingResult(
            success=len(state.errors) == 0,
            message=state.response_text,
            next_step=state.conversation_context.current_step + 1 if state.conversation_context else 0,
            processing_time_ms=processing_time,
            tokens_used=tokens_used,
            chain_trace=state.trace,
            selected_slot=state.slot_selection.selected_slots[0] if state.slot_selection and state.slot_selection.selected_slots else None
        )