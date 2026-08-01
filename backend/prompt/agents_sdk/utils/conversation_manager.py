# Conversation Manager for Agents SDK
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Cache global para resultados de runs (por conversa)
# Em produção, usar Redis ou similar
CONVERSATION_RESULTS = {}
LAST_AGENTS = {}


class ConversationManager:
    """
    Gerencia conversas usando RunResults do OpenAI Agents SDK.
    Mantém continuidade entre mensagens e rastreia último agent usado.
    """

    @staticmethod
    def get_conversation_key(company_id: int, contact_phone: str) -> str:
        """Gera chave única para a conversa."""
        return f"{company_id}_{contact_phone}"

    @staticmethod
    def get_previous_result(company_id: int, contact_phone: str):
        """Recupera resultado anterior da conversa, se houver."""
        key = ConversationManager.get_conversation_key(company_id, contact_phone)
        return CONVERSATION_RESULTS.get(key)

    @staticmethod
    def save_result(company_id: int, contact_phone: str, result):
        """Salva resultado da conversa para uso futuro."""
        key = ConversationManager.get_conversation_key(company_id, contact_phone)
        CONVERSATION_RESULTS[key] = result
        logger.info(f"[ConversationManager] Resultado salvo para {key}")

    @staticmethod
    def get_last_agent(company_id: int, contact_phone: str):
        """Recupera último agent usado na conversa."""
        key = ConversationManager.get_conversation_key(company_id, contact_phone)
        return LAST_AGENTS.get(key)

    @staticmethod
    def save_last_agent(company_id: int, contact_phone: str, agent):
        """Salva último agent usado."""
        key = ConversationManager.get_conversation_key(company_id, contact_phone)
        LAST_AGENTS[key] = agent
        logger.info(f"[ConversationManager] Último agent salvo: {agent.name}")

    @staticmethod
    def clear_conversation(company_id: int, contact_phone: str):
        """Limpa dados de uma conversa específica."""
        key = ConversationManager.get_conversation_key(company_id, contact_phone)
        CONVERSATION_RESULTS.pop(key, None)
        LAST_AGENTS.pop(key, None)
        logger.info(f"[ConversationManager] Conversa {key} limpa")

    @staticmethod
    def build_conversation_input(previous_result, user_input: str, max_context_length: int = 20) -> List[Dict[str, str]]:
        """
        Constrói input para o Runner usando resultado anterior ou iniciando nova conversa.

        Args:
            previous_result: RunResult anterior ou None
            user_input: Nova mensagem do usuário
            max_context_length: Número máximo de mensagens no contexto

        Returns:
            Lista de mensagens formatadas para o Runner
        """
        if previous_result:
            # Usa to_input_list() para manter continuidade
            messages = previous_result.to_input_list()

            # Otimiza contexto se muito longo
            if len(messages) > max_context_length * 2:
                # Mantém primeira mensagem (system) e últimas N mensagens
                system_messages = [m for m in messages if m.get("role") == "system"]
                other_messages = [m for m in messages if m.get("role") != "system"]

                # Pega últimas mensagens mantendo pares user/assistant
                recent_messages = other_messages[-(max_context_length):]

                # Reconstrói lista otimizada
                messages = system_messages + recent_messages

                logger.info(f"[ConversationManager] Contexto otimizado de {len(previous_result.to_input_list())} para {len(messages)} mensagens")

            # Adiciona nova mensagem do usuário
            messages.append({"role": "user", "content": user_input})

        else:
            # Nova conversa - apenas a mensagem do usuário
            messages = [{"role": "user", "content": user_input}]
            logger.info("[ConversationManager] Iniciando nova conversa")

        return messages

    @staticmethod
    def sync_with_memory_system(company_id: int, contact_phone: str):
        """
        Sincroniza com sistema de memória existente.
        Pode ser usado para persistir conversas em arquivo.
        """
        # Esta função pode ser expandida para salvar RunResults
        # no sistema de memória existente se necessário
        pass