# Memory Integration for Agents SDK
"""
Integra o Agents SDK com o sistema de memória existente.
Usa o memory_manager.py para persistir conversas em arquivos.
"""
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime
import pytz

# Import do sistema de memória existente
from backend.prompt.memory.memory_manager import (
    get_chat_history,
    append_message_to_chat_file,
    append_message_to_chat_file_as_operator
)

# Import dos tipos do Agents SDK (removido - não existe ToolCall exportado)

logger = logging.getLogger(__name__)

class AgentsSDKMemoryIntegration:
    """
    Classe que integra o Agents SDK com o sistema de memória existente.
    """

    def __init__(self, company_id: int, contact_phone: str):
        """
        Inicializa a integração de memória.

        Args:
            company_id: ID da empresa
            contact_phone: Telefone do contato
        """
        self.company_id = company_id
        self.contact_phone = contact_phone

    def load_chat_history(self) -> List[Dict[str, str]]:
        """
        Carrega o histórico de chat do sistema de arquivos.

        Returns:
            Lista de mensagens no formato do Agents SDK
        """
        # Usa o sistema existente para carregar histórico
        langchain_messages = get_chat_history(self.company_id, self.contact_phone)

        # Converte para formato do Agents SDK
        agents_history = []
        for msg in langchain_messages:
            if hasattr(msg, 'content'):
                if msg.__class__.__name__ == 'HumanMessage':
                    agents_history.append({
                        "role": "user",
                        "content": msg.content
                    })
                elif msg.__class__.__name__ == 'AIMessage':
                    # Verifica se é mensagem de operador
                    if msg.content.startswith("[Operador]:"):
                        agents_history.append({
                            "role": "assistant",
                            "content": msg.content,
                            "metadata": {"source": "operator"}
                        })
                    else:
                        agents_history.append({
                            "role": "assistant",
                            "content": msg.content
                        })

        logger.info(f"[MemoryIntegration] Carregadas {len(agents_history)} mensagens do histórico")
        return agents_history

    def save_user_message(self, content: str) -> None:
        """
        Salva mensagem do usuário no histórico.

        Args:
            content: Conteúdo da mensagem
        """
        # from_me=False significa que é mensagem do usuário
        append_message_to_chat_file(
            self.company_id,
            self.contact_phone,
            from_me=False,
            content=content
        )
        logger.info(f"[MemoryIntegration] Mensagem do usuário salva no histórico")

    def save_assistant_message(self, content: str) -> None:
        """
        Salva mensagem do assistente no histórico.

        Args:
            content: Conteúdo da mensagem
        """
        # from_me=True significa que é mensagem do AI
        append_message_to_chat_file(
            self.company_id,
            self.contact_phone,
            from_me=True,
            content=content
        )
        logger.info(f"[MemoryIntegration] Mensagem do assistente salva no histórico")

    def save_operator_message(self, content: str) -> None:
        """
        Salva mensagem do operador humano no histórico.

        Args:
            content: Conteúdo da mensagem
        """
        append_message_to_chat_file_as_operator(
            self.company_id,
            self.contact_phone,
            content=content
        )
        logger.info(f"[MemoryIntegration] Mensagem do operador salva no histórico")

    def save_tool_call(self, tool_call: Any, output: str) -> None:
        """
        Salva chamada de ferramenta no histórico como mensagem do assistente.

        Args:
            tool_call: Objeto de chamada de ferramenta do Agents SDK
            output: Resultado da ferramenta
        """
        # Formata a chamada de ferramenta de forma legível
        tool_name = getattr(tool_call, 'tool_name', 'Ferramenta')
        tool_message = f"[Ação: {tool_name}]"

        if hasattr(tool_call, 'parameters') and tool_call.parameters:
            tool_message += f" com parâmetros: {tool_call.parameters}"

        # Salva como mensagem do assistente
        self.save_assistant_message(tool_message)

        # Se houver output significativo, salva também
        if output and not output.startswith("❌"):
            self.save_assistant_message(f"[Resultado: {output}]")

    def get_recent_context(self, max_messages: int = 10) -> str:
        """
        Retorna um resumo do contexto recente da conversa.

        Args:
            max_messages: Número máximo de mensagens recentes a incluir

        Returns:
            String com contexto resumido
        """
        history = self.load_chat_history()

        if not history:
            return "Sem histórico de conversa anterior."

        # Pega as últimas mensagens
        recent = history[-max_messages:] if len(history) > max_messages else history

        # Formata contexto
        context_parts = ["Contexto da conversa:"]
        for msg in recent:
            role = "Cliente" if msg["role"] == "user" else "Assistente"
            # Limita tamanho de cada mensagem
            content = msg["content"][:200] + "..." if len(msg["content"]) > 200 else msg["content"]
            context_parts.append(f"- {role}: {content}")

        return "\n".join(context_parts)

    def extract_customer_preferences(self) -> Dict[str, Any]:
        """
        Extrai preferências do cliente do histórico.

        Returns:
            Dicionário com preferências identificadas
        """
        history = self.load_chat_history()
        preferences = {
            "horarios_preferidos": [],
            "tratamentos_mencionados": [],
            "restricoes": [],
            "interacoes_anteriores": len(history)
        }

        # Análise simples do histórico
        for msg in history:
            if msg["role"] == "user":
                content_lower = msg["content"].lower()

                # Detecta preferências de horário
                if any(word in content_lower for word in ["manhã", "tarde", "noite"]):
                    if "manhã" in content_lower and "manhã" not in preferences["horarios_preferidos"]:
                        preferences["horarios_preferidos"].append("manhã")
                    if "tarde" in content_lower and "tarde" not in preferences["horarios_preferidos"]:
                        preferences["horarios_preferidos"].append("tarde")
                    if "noite" in content_lower and "noite" not in preferences["horarios_preferidos"]:
                        preferences["horarios_preferidos"].append("noite")

                # Detecta tratamentos mencionados
                tratamentos = ["limpeza", "clareamento", "ortodontia", "implante", "canal", "restauração"]
                for trat in tratamentos:
                    if trat in content_lower and trat not in preferences["tratamentos_mencionados"]:
                        preferences["tratamentos_mencionados"].append(trat)

        return preferences

    def clear_old_history(self, days: int = 90) -> None:
        """
        Limpa histórico antigo (não implementado - arquivos são mantidos).

        Args:
            days: Dias de histórico a manter
        """
        # Por enquanto, não vamos deletar histórico
        # Isso pode ser implementado futuramente se necessário
        logger.info(f"[MemoryIntegration] Limpeza de histórico não implementada - arquivos são mantidos")