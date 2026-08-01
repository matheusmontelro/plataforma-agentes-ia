"""
Gerenciamento de Memória Otimizado
==================================

Implementa estratégias eficientes de memória para conversas longas.
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import logging
import tiktoken

from langchain.memory import ConversationSummaryBufferMemory
from langchain.schema import BaseMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


class OptimizedSchedulingMemory(ConversationSummaryBufferMemory):
    """
    Memória otimizada para conversas de agendamento.

    Features:
    - Summarização automática de mensagens antigas
    - Preservação de informações críticas de agendamento
    - Window sliding para manter contexto relevante
    - Token counting preciso
    """

    def __init__(
        self,
        llm: ChatOpenAI,
        max_token_limit: int = 2000,
        max_messages: int = 20,
        preserve_scheduling_info: bool = True,
        **kwargs
    ):
        super().__init__(
            llm=llm,
            max_token_limit=max_token_limit,
            return_messages=True,
            **kwargs
        )
        self.max_messages = max_messages
        self.preserve_scheduling_info = preserve_scheduling_info
        self.scheduling_info_extracted = {}
        self.token_counter = TokenCounter()

    def save_context(self, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        """Salva contexto com otimizações"""
        # Salva normalmente
        super().save_context(inputs, outputs)

        # Extrai informações de agendamento se necessário
        if self.preserve_scheduling_info:
            self._extract_scheduling_info(inputs, outputs)

        # Aplica window sliding se necessário
        if len(self.chat_memory.messages) > self.max_messages:
            self._apply_sliding_window()

        # Verifica limite de tokens
        self._check_token_limit()

    def _extract_scheduling_info(self, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        """Extrai e preserva informações críticas de agendamento"""
        # Busca por padrões de data/hora nas mensagens
        import re

        date_pattern = r'\d{1,2}/\d{1,2}/\d{4}'
        time_pattern = r'\d{1,2}:\d{2}'

        text = f"{inputs.get('input', '')} {outputs.get('output', '')}"

        dates = re.findall(date_pattern, text)
        times = re.findall(time_pattern, text)

        if dates or times:
            self.scheduling_info_extracted.update({
                'last_mentioned_dates': dates[-3:] if dates else [],
                'last_mentioned_times': times[-3:] if times else [],
                'extracted_at': datetime.now().isoformat()
            })

    def _apply_sliding_window(self) -> None:
        """Aplica janela deslizante mantendo mensagens importantes"""
        messages = self.chat_memory.messages

        # Sempre mantém primeira mensagem (contexto inicial)
        first_message = messages[0] if messages else None

        # Identifica mensagens importantes
        important_indices = self._identify_important_messages(messages)

        # Mantém últimas N mensagens + importantes
        recent_start = max(0, len(messages) - self.max_messages)
        indices_to_keep = set(range(recent_start, len(messages)))
        indices_to_keep.update(important_indices)
        if first_message:
            indices_to_keep.add(0)

        # Filtra mensagens
        new_messages = [msg for i, msg in enumerate(messages) if i in indices_to_keep]

        # Adiciona summary das mensagens removidas
        removed_count = len(messages) - len(new_messages)
        if removed_count > 0:
            summary = self._create_summary(messages, indices_to_keep)
            if summary:
                new_messages.insert(0, AIMessage(content=f"[Resumo de {removed_count} mensagens anteriores]: {summary}"))

        self.chat_memory.messages = new_messages

    def _identify_important_messages(self, messages: List[BaseMessage]) -> List[int]:
        """Identifica mensagens importantes que devem ser preservadas"""
        important_indices = []

        keywords = [
            'agendamento confirmado', 'marquei para', 'horário escolhido',
            'nome completo', 'cancelar', 'remarcar', 'reagendar'
        ]

        for i, msg in enumerate(messages):
            content_lower = msg.content.lower()
            if any(keyword in content_lower for keyword in keywords):
                important_indices.append(i)

        return important_indices

    def _create_summary(self, messages: List[BaseMessage], indices_to_keep: set) -> str:
        """Cria resumo das mensagens que serão removidas"""
        messages_to_summarize = [
            msg for i, msg in enumerate(messages)
            if i not in indices_to_keep
        ]

        if not messages_to_summarize:
            return ""

        # Usa o LLM para criar um resumo conciso
        summary_prompt = """Resuma as seguintes mensagens de forma concisa,
        preservando apenas informações relevantes para agendamento:

        {messages}

        Resumo (máximo 100 palavras):"""

        messages_text = "\n".join([
            f"{'Usuário' if isinstance(msg, HumanMessage) else 'Assistente'}: {msg.content}"
            for msg in messages_to_summarize
        ])

        try:
            response = self.llm.predict(
                summary_prompt.format(messages=messages_text)
            )
            return response.strip()
        except Exception as e:
            logger.error(f"Erro ao criar resumo: {e}")
            return "Conversa anterior sobre agendamento."

    def _check_token_limit(self) -> None:
        """Verifica e ajusta se excedeu limite de tokens"""
        total_tokens = self.token_counter.count_messages(self.chat_memory.messages)

        if total_tokens > self.max_token_limit:
            logger.info(f"Token limit exceeded: {total_tokens} > {self.max_token_limit}")
            # Remove mensagens mais antigas até ficar dentro do limite
            while total_tokens > self.max_token_limit and len(self.chat_memory.messages) > 2:
                self.chat_memory.messages.pop(1)  # Mantém primeira mensagem
                total_tokens = self.token_counter.count_messages(self.chat_memory.messages)

    def get_scheduling_context(self) -> Dict[str, Any]:
        """Retorna contexto específico de agendamento"""
        return {
            'scheduling_info': self.scheduling_info_extracted,
            'message_count': len(self.chat_memory.messages),
            'total_tokens': self.token_counter.count_messages(self.chat_memory.messages)
        }


class TokenCounter:
    """Contador preciso de tokens para diferentes modelos"""

    def __init__(self, model_name: str = "gpt-4"):
        try:
            self.encoding = tiktoken.encoding_for_model(model_name)
        except:
            self.encoding = tiktoken.get_encoding("cl100k_base")

    def count_text(self, text: str) -> int:
        """Conta tokens em um texto"""
        return len(self.encoding.encode(text))

    def count_messages(self, messages: List[BaseMessage]) -> int:
        """Conta tokens em uma lista de mensagens"""
        total = 0
        for msg in messages:
            # Overhead por mensagem (role, etc)
            total += 4
            total += self.count_text(msg.content)
        return total


class ConversationCache:
    """Cache para conversas recentes com TTL"""

    def __init__(self, ttl_minutes: int = 15):
        self.cache: Dict[str, Tuple[OptimizedSchedulingMemory, datetime]] = {}
        self.ttl = timedelta(minutes=ttl_minutes)

    def get(self, key: str) -> Optional[OptimizedSchedulingMemory]:
        """Recupera memória do cache se ainda válida"""
        if key in self.cache:
            memory, timestamp = self.cache[key]
            if datetime.now() - timestamp < self.ttl:
                return memory
            else:
                # Expirou, remove do cache
                del self.cache[key]
        return None

    def set(self, key: str, memory: OptimizedSchedulingMemory) -> None:
        """Armazena memória no cache"""
        self.cache[key] = (memory, datetime.now())

    def cleanup(self) -> None:
        """Remove entradas expiradas"""
        now = datetime.now()
        expired_keys = [
            key for key, (_, timestamp) in self.cache.items()
            if now - timestamp >= self.ttl
        ]
        for key in expired_keys:
            del self.cache[key]

        logger.info(f"Cache cleanup: removed {len(expired_keys)} expired entries")