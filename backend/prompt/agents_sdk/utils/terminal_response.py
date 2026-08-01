# Terminal Response Handler for Agents SDK
"""
Implementação profissional de respostas terminais no OpenAI Agents SDK.
Uma resposta terminal é uma resposta que deve ser enviada exatamente como está,
sem processamento adicional pelo LLM.
"""
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TerminalResponse:
    """
    Resposta terminal que indica ao agent para não processar mais.
    Usado para mensagens que devem ser enviadas exatamente como estão.
    """
    message: str
    metadata: Optional[Dict[str, Any]] = None

    def __str__(self):
        return self.message


class TerminalResponseHandler:
    """
    Gerencia respostas terminais no fluxo do Agents SDK.
    """

    # Marcador especial para respostas terminais
    TERMINAL_MARKER = "__TERMINAL_RESPONSE__"

    @staticmethod
    def create_terminal_response(message: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Cria uma resposta terminal com marcador especial.

        Args:
            message: Mensagem que deve ser enviada sem modificações
            metadata: Metadados opcionais sobre a resposta

        Returns:
            str: Mensagem com marcador terminal
        """
        # Adiciona marcador invisível no final da mensagem
        # Isso permite detectar respostas terminais sem afetar o conteúdo
        return f"{message}{TerminalResponseHandler.TERMINAL_MARKER}"

    @staticmethod
    def is_terminal_response(message: str) -> bool:
        """
        Verifica se uma mensagem é uma resposta terminal.

        Args:
            message: Mensagem a verificar

        Returns:
            bool: True se é resposta terminal
        """
        return message.endswith(TerminalResponseHandler.TERMINAL_MARKER)

    @staticmethod
    def extract_terminal_message(message: str) -> str:
        """
        Extrai a mensagem limpa de uma resposta terminal.

        Args:
            message: Mensagem com marcador terminal

        Returns:
            str: Mensagem sem o marcador
        """
        if TerminalResponseHandler.is_terminal_response(message):
            return message.replace(TerminalResponseHandler.TERMINAL_MARKER, "")
        return message

    @staticmethod
    def process_agent_response(response: str) -> str:
        """
        Processa a resposta do agent, preservando respostas terminais.

        Args:
            response: Resposta do agent

        Returns:
            str: Resposta processada
        """
        if TerminalResponseHandler.is_terminal_response(response):
            logger.info("[TerminalResponse] Detectada resposta terminal - preservando conteúdo original")
            return TerminalResponseHandler.extract_terminal_message(response)

        return response