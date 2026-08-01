"""
Parser principal que orquestra as estratégias
"""
from typing import Optional, List, Union
from .models import ExtractedData, ConversationContext
from .strategies import (
    SimpleConfirmationStrategy,
    ExplicitChoiceStrategy,
    DirectDataStrategy,
    ParsingStrategy
)
from .chains import create_full_extraction_chain
import logging

logger = logging.getLogger(__name__)


class SmartParser:
    """
    Parser inteligente que seleciona a estratégia apropriada
    baseado no contexto da conversa
    """

    def __init__(self, company_id: Optional[int] = None):
        self.company_id = company_id
        self.strategies: List[ParsingStrategy] = [
            SimpleConfirmationStrategy(),
            ExplicitChoiceStrategy(),
            DirectDataStrategy(),
        ]

    def parse(
        self,
        user_input: str,
        assistant_output: str,
        conversation_history: Optional[list] = None
    ) -> ExtractedData:
        """
        Processa input do usuário com a estratégia mais apropriada

        Args:
            user_input: Última mensagem do usuário
            assistant_output: Última mensagem do assistente
            conversation_history: Histórico completo (opcional)

        Returns:
            ExtractedData com os campos extraídos
        """

        # Cria contexto
        context = ConversationContext(
            user_input=user_input,
            assistant_output=assistant_output,
            full_history=conversation_history or []
        )

        # Log para debug
        logger.info(f"[SmartParser] Processando input: '{user_input[:50]}...'")
        logger.info(f"[SmartParser] É resposta simples? {context.is_simple_response}")

        # Tenta cada estratégia em ordem
        for strategy in self.strategies:
            if strategy.can_handle(context):
                logger.info(f"[SmartParser] Usando estratégia: {strategy.__class__.__name__}")
                try:
                    result = strategy.parse(context)

                    # Validação extra para respostas simples
                    if context.is_simple_response and (result.data or result.horario):
                        logger.warning(
                            f"[SmartParser] Estratégia extraiu data/hora de resposta simples. "
                            f"Limpando campos..."
                        )
                        result.data = None
                        result.horario = None

                    return result

                except Exception as e:
                    logger.error(f"[SmartParser] Erro na estratégia {strategy.__class__.__name__}: {e}")
                    continue

        # Fallback: usa chain completa como último recurso
        logger.info("[SmartParser] Nenhuma estratégia específica. Usando extração completa...")
        try:
            chain = create_full_extraction_chain(company_id=self.company_id)
            result = chain.invoke({
                "assistant_message": assistant_output,
                "user_input": user_input
            })

            # Loga métricas de cache
            from ..llm_config import log_cache_metrics
            log_cache_metrics(result, f"smart_parser_company_{self.company_id}")

            return result
        except Exception as e:
            logger.error(f"[SmartParser] Erro na extração completa: {e}")
            return ExtractedData()

    def merge_with_existing(
        self,
        new_data: ExtractedData,
        existing_data: dict
    ) -> ExtractedData:
        """
        Mescla dados novos com existentes, priorizando novos

        Args:
            new_data: Dados recém extraídos
            existing_data: Dados existentes (dict)

        Returns:
            ExtractedData mesclado
        """

        # Converte dict existente para ExtractedData
        current = ExtractedData(**existing_data)

        # Atualiza apenas campos não-nulos
        for field in new_data.__fields__:
            new_value = getattr(new_data, field)
            if new_value is not None:
                setattr(current, field, new_value)

        return current