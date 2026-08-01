"""
Gerador de instruções contextuais dinâmicas usando LangChain.
"""

import logging
from typing import Dict, Any, Optional
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_core.runnables import RunnablePassthrough

from .models import ContextAnalysis, InterventionType
from ..llm_config import create_llm_for_use_case, log_cache_metrics

logger = logging.getLogger(__name__)


class InstructionGenerator:
    """Gerador inteligente de instruções contextuais para o LLM"""

    def __init__(self, model_name: str = "gpt-4.1-mini-2025-04-14", temperature: float = 0.3, company_id: Optional[int] = None):
        """
        Inicializa o gerador de instruções com cache otimizado.

        Args:
            model_name: Modelo OpenAI para geração
            temperature: Criatividade na geração (0.3 = balanceado)
            company_id: ID da empresa para contexto de cache
        """
        # Usa configuração otimizada para geração de instruções
        self.llm = create_llm_for_use_case(
            "memory",
            company_id=company_id,
            temperature=temperature,
            model=model_name,
            user_context=f"instruction_gen_company_{company_id}" if company_id else "instruction_gen"
        )
        self.company_id = company_id

        # Templates específicos por tipo de intervenção
        self.templates = {
            InterventionType.OPERATOR: self._create_operator_template(),
            InterventionType.USER_CONFIRMATION: self._create_confirmation_template(),
            InterventionType.URGENCY_DETECTED: self._create_urgency_template(),
            InterventionType.REFERENCE_PREVIOUS: self._create_reference_template(),
            InterventionType.TOPIC_CHANGE: self._create_topic_change_template(),
            InterventionType.CONTEXT_SHIFT: self._create_context_shift_template()
        }

        # Template genérico para casos não específicos
        self.generic_template = self._create_generic_template()

    def generate_instruction(
        self,
        analysis: ContextAnalysis,
        intervention_data: Dict[str, Any] = None
    ) -> str:
        """
        Gera instrução contextual baseada na análise.

        Args:
            analysis: Resultado da análise de contexto
            intervention_data: Dados específicos da intervenção detectada

        Returns:
            String com instrução contextual para o LLM
        """
        try:
            # Seleciona template apropriado
            template = self.templates.get(
                analysis.intervention_type,
                self.generic_template
            )

            # Prepara variáveis para o template
            variables = self._prepare_variables(analysis, intervention_data)

            # Gera instrução
            response = template.invoke(variables)

            # Loga métricas de cache
            log_cache_metrics(response, f"instruction_{analysis.intervention_type.value}_company_{self.company_id}")

            instruction = response.content.strip()

            logger.info(f"[InstructionGenerator] Instrução gerada para {analysis.intervention_type}")

            return instruction

        except Exception as e:
            logger.error(f"[InstructionGenerator] Erro ao gerar instrução: {e}")
            return self._get_fallback_instruction(analysis, intervention_data)

    def _create_operator_template(self) -> ChatPromptTemplate:
        """Template para intervenções de operador"""
        return ChatPromptTemplate.from_messages([
            ("system", """Você é um especialista em continuidade conversacional.

Um operador humano interveio na conversa. Sua tarefa é gerar uma instrução clara
para o assistente virtual continuar a conversa de forma natural, incorporando
as informações fornecidas pelo operador.

A instrução deve:
1. Ser específica sobre o que incorporar na resposta
2. Manter fluxo natural da conversa
3. Evitar repetições desnecessárias
4. Focar na continuidade do contexto"""),

            ("human", """INTERVENÇÃO DO OPERADOR DETECTADA:

Conteúdo da intervenção: "{operator_content}"
Conteúdo limpo: "{clean_content}"

ANÁLISE DE CONTEXTO:
- Entidades encontradas: {entities}
- Tópicos principais: {topics}
- Referências temporais: {temporal_refs}
- Ações mencionadas: {actions}
- É primeira resposta após operador: {is_first_response}

Gere uma instrução específica e clara para o assistente virtual incorporar
naturalmente essas informações em sua próxima resposta.

A instrução deve começar com [CONTEXTO OPERADOR] e ser direta e acionável.""")
        ])

    def _create_confirmation_template(self) -> ChatPromptTemplate:
        """Template para confirmações do usuário"""
        return ChatPromptTemplate.from_messages([
            ("system", """O usuário confirmou ou aceitou informações anteriores.
            Gere uma instrução para o assistente continuar naturalmente."""),

            ("human", """CONFIRMAÇÃO DO USUÁRIO DETECTADA:

Frase de confirmação: "{confirmation_phrase}"
Tipo: {confirmation_type}
Confiança: {confidence}

Gere uma instrução breve para o assistente continuar a conversa
sem repetir informações já confirmadas.""")
        ])

    def _create_urgency_template(self) -> ChatPromptTemplate:
        """Template para situações de urgência"""
        return ChatPromptTemplate.from_messages([
            ("system", """Urgência detectada na conversa. O assistente deve
            responder de forma mais direta e focada na solução rápida."""),

            ("human", """URGÊNCIA DETECTADA:

Indicadores de urgência: {urgency_indicators}
Nível de urgência: {urgency_level}
Score: {urgency_score}

Gere uma instrução para o assistente responder de forma mais
direta e focada em resolver a situação urgente.""")
        ])

    def _create_reference_template(self) -> ChatPromptTemplate:
        """Template para referências a conversas anteriores"""
        return ChatPromptTemplate.from_messages([
            ("system", """O usuário fez referência a uma conversa ou informação anterior.
            O assistente deve reconhecer essa referência e dar continuidade."""),

            ("human", """REFERÊNCIA A CONVERSA ANTERIOR:

Padrões detectados: {reference_patterns}
Confiança: {reference_confidence}

Gere uma instrução para o assistente reconhecer a referência
e continuar a partir do contexto mencionado.""")
        ])

    def _create_topic_change_template(self) -> ChatPromptTemplate:
        """Template para mudanças de tópico"""
        return ChatPromptTemplate.from_messages([
            ("system", """Mudança de tópico detectada. O assistente deve
            fazer uma transição natural para o novo assunto."""),

            ("human", """MUDANÇA DE TÓPICO:

Tópico anterior: {from_topic}
Novo tópico: {to_topic}
Confiança: {topic_confidence}

Gere uma instrução para o assistente fazer uma transição
natural para o novo tópico.""")
        ])

    def _create_context_shift_template(self) -> ChatPromptTemplate:
        """Template para mudanças gerais de contexto"""
        return ChatPromptTemplate.from_messages([
            ("system", """Mudança significativa de contexto detectada.
            Gere instrução apropriada para a continuação."""),

            ("human", """MUDANÇA DE CONTEXTO:

Entidades: {entities}
Tópicos: {topics}
Tom emocional: {emotional_tone}
Ações: {actions}

Gere instrução contextual apropriada.""")
        ])

    def _create_generic_template(self) -> ChatPromptTemplate:
        """Template genérico para casos não específicos"""
        return ChatPromptTemplate.from_messages([
            ("system", """Gere uma instrução contextual baseada na análise fornecida."""),

            ("human", """ANÁLISE DE CONTEXTO:

Tipo de intervenção: {intervention_type}
Entidades: {entities}
Tópicos: {topics}
Referências temporais: {temporal_refs}
Ações: {actions}
Requer mudança de contexto: {requires_shift}

Gere uma instrução contextual apropriada.""")
        ])

    def _prepare_variables(
        self,
        analysis: ContextAnalysis,
        intervention_data: Dict[str, Any]
    ) -> Dict[str, str]:
        """Prepara variáveis para os templates"""

        # Variáveis básicas da análise
        variables = {
            "intervention_type": analysis.intervention_type.value,
            "entities": self._format_entities(analysis.key_entities),
            "topics": ", ".join(analysis.key_topics) if analysis.key_topics else "Nenhum",
            "temporal_refs": ", ".join(analysis.temporal_references) if analysis.temporal_references else "Nenhuma",
            "actions": ", ".join(analysis.action_items) if analysis.action_items else "Nenhuma",
            "emotional_tone": analysis.emotional_tone or "Neutro",
            "requires_shift": "Sim" if analysis.requires_context_shift else "Não"
        }

        # Adiciona variáveis específicas da intervenção
        if intervention_data:
            if analysis.intervention_type == InterventionType.OPERATOR:
                op_info = intervention_data.get('operator_info', {})
                variables.update({
                    "operator_content": op_info.get('content', ''),
                    "clean_content": op_info.get('clean_content', ''),
                    "is_first_response": "Sim" if op_info.get('is_first_response') else "Não"
                })

            elif analysis.intervention_type == InterventionType.USER_CONFIRMATION:
                conf_info = intervention_data.get('confirmation_info', {})
                variables.update({
                    "confirmation_phrase": conf_info.get('phrase', ''),
                    "confirmation_type": conf_info.get('type', ''),
                    "confidence": str(conf_info.get('confidence', 0))
                })

            elif analysis.intervention_type == InterventionType.URGENCY_DETECTED:
                urg_info = intervention_data.get('urgency_info', {})
                variables.update({
                    "urgency_indicators": ", ".join(urg_info.get('indicators', [])),
                    "urgency_level": urg_info.get('level', 'medium'),
                    "urgency_score": str(urg_info.get('score', 0))
                })

            elif analysis.intervention_type == InterventionType.REFERENCE_PREVIOUS:
                ref_info = intervention_data.get('reference_info', {})
                variables.update({
                    "reference_patterns": ", ".join(ref_info.get('patterns', [])),
                    "reference_confidence": str(ref_info.get('confidence', 0))
                })

            elif analysis.intervention_type == InterventionType.TOPIC_CHANGE:
                topic_info = intervention_data.get('topic_change_info', {})
                variables.update({
                    "from_topic": topic_info.get('from_topic', 'Desconhecido'),
                    "to_topic": topic_info.get('to_topic', 'Desconhecido'),
                    "topic_confidence": str(topic_info.get('confidence', 0))
                })

        return variables

    def _format_entities(self, entities) -> str:
        """Formata lista de entidades para o template"""
        if not entities:
            return "Nenhuma"

        formatted = []
        for entity in entities[:5]:  # Limita a 5 entidades
            if hasattr(entity, 'text') and hasattr(entity, 'type'):
                formatted.append(f"{entity.text} ({entity.type})")
            else:
                formatted.append(str(entity))

        return ", ".join(formatted)

    def _get_fallback_instruction(
        self,
        analysis: ContextAnalysis,
        intervention_data: Dict[str, Any]
    ) -> str:
        """Instrução de fallback caso a geração principal falhe"""

        parts = ["[CONTEXTO DETECTADO]"]

        # Adiciona informações básicas
        if analysis.intervention_type != InterventionType.NONE:
            parts.append(f"Tipo: {analysis.intervention_type.value}")

        if analysis.key_entities:
            entities_text = ", ".join([e.text if hasattr(e, 'text') else str(e) for e in analysis.key_entities[:3]])
            parts.append(f"Entidades: {entities_text}")

        if analysis.key_topics:
            parts.append(f"Tópicos: {', '.join(analysis.key_topics[:3])}")

        # Adiciona informações específicas da intervenção
        if intervention_data and analysis.intervention_type == InterventionType.OPERATOR:
            op_info = intervention_data.get('operator_info', {})
            if op_info.get('clean_content'):
                parts.append(f"Operador disse: {op_info['clean_content'][:100]}...")

        parts.append("\nIncorpore essas informações naturalmente em sua resposta.")

        return "\n".join(parts)
