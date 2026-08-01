"""
Estratégias de parsing por tipo de resposta
"""
from abc import ABC, abstractmethod
from typing import Optional
import re
from .models import ExtractedData, ConversationContext
from .chains import create_simple_confirmation_chain, create_explicit_choice_chain
import logging

logger = logging.getLogger(__name__)


class ParsingStrategy(ABC):
    """Interface base para estratégias de parsing"""

    @abstractmethod
    def can_handle(self, context: ConversationContext) -> bool:
        """Verifica se esta estratégia pode processar o contexto"""
        pass

    @abstractmethod
    def parse(self, context: ConversationContext) -> ExtractedData:
        """Executa o parsing segundo a estratégia"""
        pass


class SimpleConfirmationStrategy(ParsingStrategy):
    """
    Handles: sim, ok, pode ser, claro, etc.
    NÃO extrai data/hora - apenas confirma intenção
    """

    def can_handle(self, context: ConversationContext) -> bool:
        return context.is_simple_response

    def parse(self, context: ConversationContext) -> ExtractedData:
        logger.info(f"[SimpleConfirmation] Processando resposta simples: '{context.user_input}'")

        # Para respostas simples, só marca confirmação se:
        # 1. O assistente perguntou especificamente sobre confirmação de AGENDAMENTO
        # 2. O usuário respondeu positivamente

        assistant_lower = context.assistant_output.lower()
        user_lower = context.user_input.lower()

        # Palavras de confirmação do usuário
        user_confirmations = ['sim', 'ok', 'pode', 'claro', 'confirmo', 'aceito', 'quero']
        user_said_yes = any(word in user_lower for word in user_confirmations)

        # Verifica se assistente estava perguntando sobre confirmação de AGENDAMENTO
        asking_to_confirm_appointment = (
            ('posso confirmar' in assistant_lower or
             'confirma o agendamento' in assistant_lower or
             'confirmar o agendamento' in assistant_lower or
             'confirmar seu agendamento' in assistant_lower or
             'confirmar sua consulta' in assistant_lower) and
            ('R$' in context.assistant_output or 'valor' in assistant_lower or 'custo' in assistant_lower)
        )

        # Só marca como confirmado se ambas condições forem verdadeiras
        is_confirming = asking_to_confirm_appointment and user_said_yes

        if is_confirming:
            logger.info("[SimpleConfirmation] Detectada confirmação de agendamento")

        return ExtractedData(
            agendamento_confirmado=is_confirming,
            # NÃO preenche data/hora em respostas simples
        )


class ExplicitChoiceStrategy(ParsingStrategy):
    """
    Handles: "quero o primeiro", "prefiro às 14h", "pode ser amanhã às 9"
    Extrai escolhas específicas
    """

    def can_handle(self, context: ConversationContext) -> bool:
        # Padrões que indicam escolha explícita
        choice_patterns = [
            r'\b(primeiro|segundo|1º|2º|1|2)\b',
            r'\b\d{1,2}h|\d{1,2}:\d{2}\b',
            r'\b(manhã|tarde|noite)\b',
            r'\b(segunda|terça|quarta|quinta|sexta|sábado)\b',
            r'às \d{1,2}',
            r'dia \d{1,2}',
        ]

        user_lower = context.user_input.lower()
        return any(re.search(pattern, user_lower) for pattern in choice_patterns)

    def parse(self, context: ConversationContext) -> ExtractedData:
        logger.info(f"[ExplicitChoice] Processando escolha explícita: '{context.user_input}'")

        chain = create_explicit_choice_chain()
        result = chain.invoke({
            "assistant_message": context.assistant_output,
            "user_choice": context.user_input
        })

        return result


class DirectDataStrategy(ParsingStrategy):
    """
    Handles: respostas diretas com nome, tratamento, etc.
    Ex: "Meu nome é João", "Quero fazer um implante"
    """

    def can_handle(self, context: ConversationContext) -> bool:
        direct_patterns = [
            r'meu nome é',
            r'me chamo',
            r'sou (o|a)',
            r'quero (fazer|marcar|agendar)',
            r'preciso de',
            r'primeira vez',
            r'já sou cliente',
        ]

        user_lower = context.user_input.lower()
        return any(re.search(pattern, user_lower) for pattern in direct_patterns)

    def parse(self, context: ConversationContext) -> ExtractedData:
        logger.info(f"[DirectData] Processando dados diretos: '{context.user_input}'")

        extracted = ExtractedData()
        user_lower = context.user_input.lower()

        # Extrai nome
        name_match = re.search(r'(?:meu nome é|me chamo|sou (?:o|a)?)\s+([A-Za-zÀ-ÿ\s]+)',
                              context.user_input, re.IGNORECASE)
        if name_match:
            extracted.nome = name_match.group(1).strip().title()

        # Extrai tipo de cliente
        if 'primeira vez' in user_lower or 'nunca fui' in user_lower:
            extracted.cliente = 'novo'
        elif 'já sou cliente' in user_lower or 'já fui' in user_lower:
            extracted.cliente = 'antigo'

        # Extrai tratamento mencionado
        treatments = {
            'implante': 'Implante',
            'canal': 'Canal',
            'limpeza': 'Limpeza',
            'clareamento': 'Clareamento',
            'aparelho': 'Aparelho',
            'extração': 'Extração'
        }

        for key, value in treatments.items():
            if key in user_lower:
                extracted.tratamento = value
                break

        return extracted