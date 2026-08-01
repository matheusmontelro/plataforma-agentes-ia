"""
Gerenciador principal de contexto usando LangChain.
Implementa gerenciamento de contexto robusto e reutilizável.
"""

import logging
from typing import List, Tuple, Dict, Any, Optional
from langchain_core.messages import BaseMessage

from .models import ContextAnalysis, InterventionType
from .extraction_chain import ContextExtractionChain
from .intervention_detector import InterventionDetector
from .instruction_generator import InstructionGenerator
from .context_aware_memory import SimpleContextTracker
from .semantic_customer_analyzer import SemanticCustomerAnalyzer

logger = logging.getLogger(__name__)


class ContextManager:
    """
    Gerenciador profissional de contexto para conversas usando LangChain.

    Gerencia o contexto de qualquer empresa com uma abordagem inteligente,
    flexível e manutenível.
    """

    def __init__(
        self,
        company_id: int,
        model_name: str = "gpt-4.1-mini-2025-04-14",
        enable_context_tracking: bool = True,
        enable_semantic_analysis: bool = True
    ):
        """
        Inicializa o gerenciador de contexto.

        Args:
            company_id: ID da empresa
            model_name: Modelo OpenAI para análise
            enable_context_tracking: Se deve manter histórico de mudanças
            enable_semantic_analysis: Se deve usar análise semântica avançada
        """
        self.company_id = company_id
        self.model_name = model_name

        # Componentes principais
        self.extraction_chain = ContextExtractionChain(model_name)
        self.intervention_detector = InterventionDetector()
        self.instruction_generator = InstructionGenerator(model_name)

        # Analisador semântico (novo)
        self.semantic_analyzer = SemanticCustomerAnalyzer(model_name) if enable_semantic_analysis else None

        # Tracker opcional de contexto
        self.context_tracker = SimpleContextTracker() if enable_context_tracking else None

        logger.info(f"[ContextManager] Inicializado para company_id={company_id}, "
                   f"semantic_analysis={enable_semantic_analysis}")

    def check_context(
        self,
        messages: List[BaseMessage],
        user_input: str = "",
        company_config: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str]:
        """
        Verifica e analisa o contexto da conversa usando análise semântica.

        Esta é a função principal para analisar mudanças de contexto.

        Args:
            messages: Histórico de mensagens da conversa
            user_input: Input atual do usuário
            company_config: Configurações da empresa para enriquecimento

        Returns:
            Tuple[bool, str]: (requer_contexto_especial, instrucao_contextual)
        """
        try:
            logger.info(f"[ContextManager] Analisando contexto - {len(messages)} mensagens, "
                       f"input: '{user_input[:50]}...' ")

            # 1. NOVA ABORDAGEM: Análise semântica prioritária
            if self.semantic_analyzer and len(messages) > 0:
                customer_analysis = self.semantic_analyzer.analyze_customer_status(messages, user_input)

                # Se análise semântica detectou contexto especial
                if customer_analysis.requires_special_handling or customer_analysis.confidence > 0.7:
                    # Gera instrução enriquecida com contexto semântico
                    if company_config:
                        instruction = self.semantic_analyzer.get_context_enrichment(
                            customer_analysis, company_config
                        )
                    else:
                        instruction = self._generate_semantic_instruction(customer_analysis)

                    logger.info(f"[ContextManager] Análise semântica detectou: {customer_analysis.primary_status} "
                               f"(confiança: {customer_analysis.confidence:.2f})")

                    # Registra no tracker
                    self._track_semantic_context(customer_analysis)

                    return True, instruction

            # 2. FALLBACK: Análise tradicional com detector de intervenção
            intervention_result = self.intervention_detector.detect(messages, user_input)
            intervention_type = intervention_result['type']

            # Se não há intervenção significativa, retorna sem contexto especial
            if intervention_type == InterventionType.NONE:
                logger.info("[ContextManager] Nenhuma intervenção significativa detectada")
                return False, ""

            # Para intervenções simples, usa lógica rápida
            if intervention_type in [InterventionType.USER_CONFIRMATION]:
                instruction = self._handle_simple_intervention(intervention_result)
                self._track_context_change(intervention_type, intervention_result)
                return True, instruction

            # Para intervenções complexas, usa análise LLM completa
            analysis = self.extraction_chain.analyze(messages)

            # Atualiza tipo de intervenção na análise se necessário
            if intervention_type != InterventionType.NONE:
                analysis.intervention_type = intervention_type
                analysis.requires_context_shift = True

            # Gera instrução contextual usando LLM
            instruction = self.instruction_generator.generate_instruction(
                analysis,
                intervention_result
            )

            # Registra mudança de contexto
            self._track_context_change(intervention_type, intervention_result, analysis)

            logger.info(f"[ContextManager] Contexto especial requerido - "
                       f"Tipo: {intervention_type}, Instrução: {len(instruction)} chars")

            return True, instruction

        except Exception as e:
            logger.error(f"[ContextManager] Erro na análise de contexto: {e}")
            return False, ""

    def _handle_simple_intervention(self, intervention_result: Dict[str, Any]) -> str:
        """Lida com intervenções simples sem usar LLM"""
        intervention_type = intervention_result['type']

        if intervention_type == InterventionType.USER_CONFIRMATION:
            return """[CONTEXTO: Confirmação]
O usuário confirmou recebimento/entendimento da informação anterior.
Continue a conversa naturalmente sem repetir o que já foi dito.
Avance para o próximo passo lógico da interação."""

        return "[CONTEXTO] Continue naturalmente a partir do contexto atual."

    def _generate_semantic_instruction(self, customer_analysis) -> str:
        """Gera instrução baseada na análise semântica quando company_config não está disponível"""
        status_instructions = {
            'appointment_confirmed': """[CONTEXTO DETECTADO] CONSULTA JÁ AGENDADA
O cliente tem consulta confirmada. NÃO ofereça agendamento.
- Confirme a consulta
- Esclareça dúvidas sobre chegada/preparação
- Mantenha tom de confirmação e assistência""",

            'emergency_customer': """[CONTEXTO DETECTADO] SITUAÇÃO DE URGÊNCIA
Cliente com necessidade urgente identificada.
- Priorize atendimento rápido
- Demonstre empatia
- Ofereça soluções imediatas""",

            'active_customer': """[CONTEXTO DETECTADO] CLIENTE ATIVO
Cliente com histórico na empresa.
- Use tom personalizado
- Referencie histórico se apropriado
- Mantenha continuidade do atendimento""",

            'qualified_lead': """[CONTEXTO DETECTADO] LEAD QUALIFICADO
Lead já informado sobre tratamentos/valores.
- Foque no fechamento
- Não repita informações já fornecidas
- Conduza para agendamento""",

            'new_lead': """[CONTEXTO DETECTADO] LEAD NOVO
Primeiro contato com a empresa.
- Use abordagem educativa
- Qualifique necessidades
- Apresente a empresa gradualmente"""
        }

        base_instruction = status_instructions.get(
            customer_analysis.primary_status,
            "[CONTEXTO] Proceda de acordo com o contexto identificado."
        )

        # Adiciona informações específicas da análise
        if customer_analysis.context_summary:
            base_instruction += f"\n\nCONTEXTO ESPECÍFICO: {customer_analysis.context_summary}"

        if customer_analysis.urgent_needs:
            base_instruction += f"\n\nNECESSIDADES URGENTES: {', '.join(customer_analysis.urgent_needs)}"

        return base_instruction

    def _track_semantic_context(self, customer_analysis) -> None:
        """Registra análise semântica no tracker"""
        if not self.context_tracker:
            return

        # Converte status semântico para InterventionType
        status_to_intervention = {
            'appointment_confirmed': InterventionType.OPERATOR,
            'emergency_customer': InterventionType.URGENCY_DETECTED,
            'qualified_lead': InterventionType.REFERENCE_PREVIOUS,
            'new_lead': InterventionType.NONE,
            'active_customer': InterventionType.REFERENCE_PREVIOUS
        }

        intervention_type = status_to_intervention.get(
            customer_analysis.primary_status,
            InterventionType.NONE
        )

        # Cria análise simples para compatibilidade
        analysis = ContextAnalysis(
            intervention_type=intervention_type,
            requires_context_shift=customer_analysis.requires_special_handling
        )

        trigger = f"Semântico: {customer_analysis.primary_status} ({customer_analysis.confidence:.2f})"

        self.context_tracker.track_context_change(
            intervention_type=intervention_type,
            analysis=analysis,
            trigger=trigger
        )

    def _track_context_change(
        self,
        intervention_type: InterventionType,
        intervention_result: Dict[str, Any],
        analysis: Optional[ContextAnalysis] = None
    ) -> None:
        """Registra mudança de contexto no tracker"""
        if not self.context_tracker:
            return

        # Cria análise simples se não fornecida
        if not analysis:
            analysis = ContextAnalysis(
                intervention_type=intervention_type,
                requires_context_shift=True
            )

        # Determina trigger
        trigger = self._get_trigger_description(intervention_type, intervention_result)

        self.context_tracker.track_context_change(
            intervention_type=intervention_type,
            analysis=analysis,
            trigger=trigger
        )

    def _get_trigger_description(
        self,
        intervention_type: InterventionType,
        intervention_result: Dict[str, Any]
    ) -> str:
        """Gera descrição do que disparou a mudança de contexto"""
        if intervention_type == InterventionType.OPERATOR:
            op_info = intervention_result.get('operator_info', {})
            content = op_info.get('clean_content', '')[:100]
            return f"Operador: {content}..."

        elif intervention_type == InterventionType.USER_CONFIRMATION:
            conf_info = intervention_result.get('confirmation_info', {})
            phrase = conf_info.get('phrase', '')
            return f"Confirmação: '{phrase}'"

        elif intervention_type == InterventionType.URGENCY_DETECTED:
            urg_info = intervention_result.get('urgency_info', {})
            indicators = urg_info.get('indicators', [])
            return f"Urgência: {', '.join(indicators[:3])}"

        elif intervention_type == InterventionType.TOPIC_CHANGE:
            topic_info = intervention_result.get('topic_change_info', {})
            from_topic = topic_info.get('from_topic', '')
            to_topic = topic_info.get('to_topic', '')
            return f"Mudança: {from_topic} → {to_topic}"

        return f"Intervenção: {intervention_type.value}"

    def get_context_summary(self) -> Dict[str, Any]:
        """
        Retorna resumo do contexto atual.

        Returns:
            Dicionário com informações sobre o contexto
        """
        if not self.context_tracker:
            return {"tracking_disabled": True}

        recent_shifts = self.context_tracker.get_recent_shifts(5)

        return {
            "company_id": self.company_id,
            "total_shifts": len(self.context_tracker.context_shifts),
            "recent_shifts": [
                {
                    "type": shift.intervention_type.value,
                    "trigger": shift.trigger,
                    "timestamp": shift.timestamp.isoformat()
                }
                for shift in recent_shifts
            ],
            "has_recent_operator": self.context_tracker.has_recent_type(
                InterventionType.OPERATOR, max_ago=5
            ),
            "has_recent_urgency": self.context_tracker.has_recent_type(
                InterventionType.URGENCY_DETECTED, max_ago=3
            )
        }

    def analyze_conversation_flow(self, messages: List[BaseMessage]) -> Dict[str, Any]:
        """
        Analisa o fluxo geral da conversa para insights.

        Args:
            messages: Histórico completo da conversa

        Returns:
            Análise do fluxo conversacional
        """
        try:
            analysis = self.extraction_chain.analyze(messages, max_messages=20)

            return {
                "total_messages": len(messages),
                "key_entities": [
                    {"text": e.text, "type": e.type}
                    for e in analysis.key_entities
                ] if analysis.key_entities else [],
                "main_topics": analysis.key_topics,
                "temporal_references": analysis.temporal_references,
                "action_items": analysis.action_items,
                "emotional_tone": analysis.emotional_tone,
                "conversation_health": self._assess_conversation_health(analysis),
                "recommendations": self._get_conversation_recommendations(analysis)
            }

        except Exception as e:
            logger.error(f"[ContextManager] Erro na análise de fluxo: {e}")
            return {"error": str(e)}

    def _assess_conversation_health(self, analysis: ContextAnalysis) -> str:
        """Avalia a 'saúde' da conversa baseada na análise"""
        score = 0

        # Pontos positivos
        if analysis.key_entities:
            score += len(analysis.key_entities) * 10
        if analysis.action_items:
            score += len(analysis.action_items) * 15
        if analysis.temporal_references:
            score += len(analysis.temporal_references) * 5

        # Penalizações
        if analysis.emotional_tone in ['frustrated', 'angry']:
            score -= 20
        if analysis.requires_context_shift:
            score -= 5

        if score >= 50:
            return "healthy"
        elif score >= 20:
            return "moderate"
        else:
            return "needs_attention"

    def _get_conversation_recommendations(self, analysis: ContextAnalysis) -> List[str]:
        """Gera recomendações para melhorar a conversa"""
        recommendations = []

        if not analysis.action_items:
            recommendations.append("Definir próximos passos claros")

        if not analysis.temporal_references and analysis.key_topics:
            if any(topic in ['agendamento', 'consulta'] for topic in analysis.key_topics):
                recommendations.append("Estabelecer timeline para agendamento")

        if analysis.emotional_tone in ['frustrated', 'urgent']:
            recommendations.append("Priorizar resolução rápida")

        if len(analysis.key_entities) > 10:
            recommendations.append("Focar em informações mais relevantes")

        return recommendations


# Função de conveniência para integrações existentes
def check_context_enhanced(
    messages: List[BaseMessage],
    user_input: str,
    company_id: int,
) -> Tuple[bool, str]:
    """
    Função de conveniência que usa o ContextManager genérico.

    Args:
        messages: Histórico de mensagens
        user_input: Input do usuário
        company_id: ID da empresa

    Returns:
        Tuple[bool, str]: (requer_contexto, instrucao)
    """
    manager = ContextManager(company_id)
    return manager.check_context(messages, user_input)


# Exemplo de uso e teste
def test_context_manager():
    """Testa o ContextManager com exemplos reais"""
    from langchain_core.messages import HumanMessage, AIMessage

    # Simula conversa com intervenção de operador
    messages = [
        HumanMessage(content="Olá, gostaria de agendar uma consulta"),
        AIMessage(content="Olá! Sou a assistente virtual. Como posso ajudar?"),
        AIMessage(content="[Operador] Cliente já conversou comigo sobre implante business, valor R$ 3.500 à vista ou 10x no cartão. Quer marcar para próxima terça-feira às 14h"),
        HumanMessage(content="Sim, como combinamos")
    ]

    manager = ContextManager(company_id=42)

    # Testa detecção de contexto
    requires_context, instruction = manager.check_context(messages, "Sim, como combinamos")

    print(f"Requer contexto especial: {requires_context}")
    print(f"Instrução gerada: {instruction[:200]}...")

    # Testa análise de fluxo
    flow_analysis = manager.analyze_conversation_flow(messages)
    print(f"Análise de fluxo: {flow_analysis}")

    # Testa resumo de contexto
    context_summary = manager.get_context_summary()
    print(f"Resumo do contexto: {context_summary}")


if __name__ == "__main__":
    test_context_manager()
