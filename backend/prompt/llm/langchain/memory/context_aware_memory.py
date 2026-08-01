"""
Memória contextual que mantém awareness de mudanças importantes na conversa.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from langchain.memory import ConversationSummaryBufferMemory
from langchain_core.messages import BaseMessage

from .models import ContextShift, ContextAnalysis, InterventionType

logger = logging.getLogger(__name__)


class ContextAwareMemory(ConversationSummaryBufferMemory):
    """
    Memória que mantém awareness de mudanças de contexto significativas.
    Extende ConversationSummaryBufferMemory do LangChain.
    """

    def __init__(
        self,
        context_manager=None,
        max_context_shifts: int = 10,
        **kwargs
    ):
        """
        Inicializa a memória contextual.

        Args:
            context_manager: Instância do ContextManager para análise
            max_context_shifts: Máximo de mudanças de contexto a manter
            **kwargs: Argumentos para ConversationSummaryBufferMemory
        """
        super().__init__(**kwargs)
        self.context_manager = context_manager
        self.max_context_shifts = max_context_shifts

        # Histórico de mudanças de contexto
        self.context_shifts: List[ContextShift] = []

        # Cache de análises para evitar reprocessamento
        self._analysis_cache: Dict[int, ContextAnalysis] = {}

        # Contador de mensagens para indexação
        self._message_counter = 0

    def save_context(self, inputs: Dict[str, Any], outputs: Dict[str, str]) -> None:
        """
        Salva contexto e detecta mudanças importantes.

        Args:
            inputs: Entradas da conversa
            outputs: Saídas geradas
        """
        # Salva usando método pai
        super().save_context(inputs, outputs)

        # Incrementa contador
        self._message_counter += 1

        # Analisa contexto se tiver manager disponível
        if self.context_manager:
            self._analyze_and_store_context()

    def _analyze_and_store_context(self) -> None:
        """Analisa contexto atual e armazena mudanças significativas"""
        try:
            messages = self.chat_memory.messages

            # Só analisa se tiver mensagens suficientes
            if len(messages) < 2:
                return

            # Verifica se já analisou esta configuração de mensagens
            cache_key = len(messages)
            if cache_key in self._analysis_cache:
                return

            # Analisa contexto atual
            analysis = self.context_manager.extraction_chain.analyze(messages)

            # Armazena no cache
            self._analysis_cache[cache_key] = analysis

            # Se requer mudança de contexto, registra
            if analysis.requires_context_shift or analysis.intervention_type != InterventionType.NONE:
                context_shift = ContextShift(
                    timestamp=datetime.now(),
                    message_index=len(messages) - 1,
                    intervention_type=analysis.intervention_type,
                    analysis=analysis,
                    trigger=self._determine_trigger(analysis, messages)
                )

                self._add_context_shift(context_shift)

                logger.info(f"[ContextAwareMemory] Nova mudança de contexto registrada: "
                           f"{analysis.intervention_type} no índice {len(messages) - 1}")

        except Exception as e:
            logger.error(f"[ContextAwareMemory] Erro ao analisar contexto: {e}")

    def _determine_trigger(self, analysis: ContextAnalysis, messages: List[BaseMessage]) -> str:
        """Determina o que disparou a mudança de contexto"""
        if analysis.intervention_type == InterventionType.OPERATOR:
            return "Intervenção de operador"
        elif analysis.intervention_type == InterventionType.USER_CONFIRMATION:
            return "Confirmação do usuário"
        elif analysis.intervention_type == InterventionType.URGENCY_DETECTED:
            return "Urgência detectada"
        elif analysis.intervention_type == InterventionType.TOPIC_CHANGE:
            return "Mudança de tópico"
        elif analysis.intervention_type == InterventionType.REFERENCE_PREVIOUS:
            return "Referência a conversa anterior"
        elif analysis.requires_context_shift:
            return "Mudança significativa de contexto"
        else:
            return "Mudança geral"

    def _add_context_shift(self, shift: ContextShift) -> None:
        """Adiciona mudança de contexto ao histórico"""
        self.context_shifts.append(shift)

        # Mantém apenas as N mudanças mais recentes
        if len(self.context_shifts) > self.max_context_shifts:
            self.context_shifts = self.context_shifts[-self.max_context_shifts:]

    def get_recent_context_shifts(self, n: int = 3) -> List[ContextShift]:
        """
        Retorna mudanças de contexto recentes.

        Args:
            n: Número de mudanças a retornar

        Returns:
            Lista das N mudanças mais recentes
        """
        return self.context_shifts[-n:] if self.context_shifts else []

    def get_context_shifts_by_type(self, intervention_type: InterventionType) -> List[ContextShift]:
        """
        Retorna mudanças de contexto de um tipo específico.

        Args:
            intervention_type: Tipo de intervenção a filtrar

        Returns:
            Lista de mudanças do tipo especificado
        """
        return [
            shift for shift in self.context_shifts
            if shift.intervention_type == intervention_type
        ]

    def has_recent_operator_intervention(self, max_messages_ago: int = 5) -> bool:
        """
        Verifica se houve intervenção de operador recente.

        Args:
            max_messages_ago: Máximo de mensagens atrás para considerar

        Returns:
            True se houve intervenção recente
        """
        current_index = len(self.chat_memory.messages) - 1

        for shift in reversed(self.context_shifts):
            if shift.intervention_type == InterventionType.OPERATOR:
                messages_ago = current_index - shift.message_index
                if messages_ago <= max_messages_ago:
                    return True

        return False

    def get_context_summary(self) -> Dict[str, Any]:
        """
        Retorna resumo do contexto atual.

        Returns:
            Dicionário com resumo do contexto
        """
        recent_shifts = self.get_recent_context_shifts(5)

        # Conta tipos de intervenção
        type_counts = {}
        for shift in self.context_shifts:
            type_name = shift.intervention_type.value
            type_counts[type_name] = type_counts.get(type_name, 0) + 1

        # Última análise
        last_analysis = None
        if self._analysis_cache:
            last_key = max(self._analysis_cache.keys())
            last_analysis = self._analysis_cache[last_key]

        return {
            "total_messages": len(self.chat_memory.messages),
            "total_context_shifts": len(self.context_shifts),
            "recent_shifts": [
                {
                    "type": shift.intervention_type.value,
                    "timestamp": shift.timestamp.isoformat(),
                    "trigger": shift.trigger
                }
                for shift in recent_shifts
            ],
            "intervention_counts": type_counts,
            "has_recent_operator": self.has_recent_operator_intervention(),
            "last_analysis": {
                "intervention_type": last_analysis.intervention_type.value if last_analysis else None,
                "requires_shift": last_analysis.requires_context_shift if last_analysis else False,
                "emotional_tone": last_analysis.emotional_tone if last_analysis else None
            } if last_analysis else None
        }

    def clear_context_shifts(self) -> None:
        """Limpa histórico de mudanças de contexto"""
        self.context_shifts.clear()
        self._analysis_cache.clear()
        logger.info("[ContextAwareMemory] Histórico de contexto limpo")

    def export_context_history(self) -> List[Dict[str, Any]]:
        """
        Exporta histórico de contexto para análise externa.

        Returns:
            Lista com dados de todas as mudanças de contexto
        """
        return [
            {
                "timestamp": shift.timestamp.isoformat(),
                "message_index": shift.message_index,
                "intervention_type": shift.intervention_type.value,
                "trigger": shift.trigger,
                "analysis": {
                    "key_entities": [
                        {"text": e.text, "type": e.type}
                        for e in shift.analysis.key_entities
                    ] if shift.analysis.key_entities else [],
                    "key_topics": shift.analysis.key_topics,
                    "emotional_tone": shift.analysis.emotional_tone,
                    "confidence_score": shift.analysis.confidence_score
                }
            }
            for shift in self.context_shifts
        ]


class SimpleContextTracker:
    """
    Tracker simples de contexto para casos onde ConversationSummaryBufferMemory
    não é necessária, mas tracking de mudanças contextuais é desejado.
    """

    def __init__(self, max_shifts: int = 20):
        """
        Args:
            max_shifts: Máximo de mudanças de contexto a manter
        """
        self.max_shifts = max_shifts
        self.context_shifts: List[ContextShift] = []
        self.message_counter = 0

    def track_context_change(
        self,
        intervention_type: InterventionType,
        analysis: ContextAnalysis,
        trigger: str = ""
    ) -> None:
        """
        Registra uma mudança de contexto.

        Args:
            intervention_type: Tipo da intervenção
            analysis: Análise de contexto completa
            trigger: Descrição do que disparou a mudança
        """
        shift = ContextShift(
            timestamp=datetime.now(),
            message_index=self.message_counter,
            intervention_type=intervention_type,
            analysis=analysis,
            trigger=trigger or f"Mudança tipo {intervention_type.value}"
        )

        self.context_shifts.append(shift)

        # Mantém apenas os N mais recentes
        if len(self.context_shifts) > self.max_shifts:
            self.context_shifts = self.context_shifts[-self.max_shifts:]

        self.message_counter += 1

    def get_recent_shifts(self, n: int = 3) -> List[ContextShift]:
        """Retorna N mudanças mais recentes"""
        return self.context_shifts[-n:] if self.context_shifts else []

    def has_recent_type(self, intervention_type: InterventionType, max_ago: int = 5) -> bool:
        """Verifica se houve intervenção de tipo específico recentemente"""
        for shift in reversed(self.context_shifts[-max_ago:]):
            if shift.intervention_type == intervention_type:
                return True
        return False
