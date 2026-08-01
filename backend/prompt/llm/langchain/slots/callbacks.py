"""
Callbacks para Monitoring e Error Handling
==========================================

Implementa callbacks customizados para observabilidade completa.
"""

from typing import Dict, Any, List, Optional, Union
from datetime import datetime
import logging
import traceback
import json

from langchain.callbacks.base import BaseCallbackHandler
from langchain.schema import LLMResult, BaseMessage

logger = logging.getLogger(__name__)


class SchedulingErrorHandler(BaseCallbackHandler):
    """
    Handler para erros específicos de agendamento.

    Features:
    - Recuperação graceful de erros
    - Sugestões alternativas em falhas
    - Logging estruturado
    """

    def __init__(self, company_id: int, contact_phone: str):
        self.company_id = company_id
        self.contact_phone = contact_phone
        self.error_count = 0
        self.error_log = []

    def on_llm_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        **kwargs: Any
    ) -> Any:
        """Handle errors no LLM"""
        self.error_count += 1
        error_data = {
            'timestamp': datetime.now().isoformat(),
            'error_type': type(error).__name__,
            'error_message': str(error),
            'traceback': traceback.format_exc(),
            'company_id': self.company_id,
            'contact_phone': self.contact_phone,
            'context': kwargs
        }

        self.error_log.append(error_data)
        logger.error(f"LLM Error: {json.dumps(error_data, indent=2)}")

        # Estratégias de recuperação baseadas no tipo de erro
        if isinstance(error, TimeoutError):
            return self._handle_timeout_error()
        elif "rate_limit" in str(error).lower():
            return self._handle_rate_limit_error()
        elif "invalid_request" in str(error).lower():
            return self._handle_invalid_request_error(error)
        else:
            return self._handle_generic_error(error)

    def on_chain_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        **kwargs: Any
    ) -> Any:
        """Handle errors em chains"""
        # Delega para on_llm_error com contexto adicional
        kwargs['chain_context'] = True
        return self.on_llm_error(error, **kwargs)

    def _handle_timeout_error(self) -> str:
        """Estratégia para timeout"""
        logger.info("Aplicando estratégia de recuperação para timeout")
        return (
            "Desculpe, estou processando muitas informações no momento. "
            "Você poderia repetir sua solicitação de forma mais simples?"
        )

    def _handle_rate_limit_error(self) -> str:
        """Estratégia para rate limit"""
        logger.info("Aplicando estratégia de recuperação para rate limit")
        return (
            "Nosso sistema está com alta demanda no momento. "
            "Por favor, aguarde alguns segundos e tente novamente."
        )

    def _handle_invalid_request_error(self, error: Exception) -> str:
        """Estratégia para requisição inválida"""
        logger.info(f"Aplicando estratégia de recuperação para requisição inválida: {error}")
        return (
            "Não consegui processar sua solicitação. "
            "Você poderia reformular de outra forma?"
        )

    def _handle_generic_error(self, error: Exception) -> str:
        """Estratégia genérica"""
        logger.info(f"Aplicando estratégia de recuperação genérica: {error}")
        return (
            "Ocorreu um erro ao processar sua solicitação. "
            "Vou transferir você para um atendente humano que poderá ajudar melhor."
        )

    def get_error_summary(self) -> Dict[str, Any]:
        """Retorna resumo dos erros"""
        return {
            'total_errors': self.error_count,
            'error_types': self._count_error_types(),
            'recent_errors': self.error_log[-5:] if self.error_log else []
        }

    def _count_error_types(self) -> Dict[str, int]:
        """Conta erros por tipo"""
        type_counts = {}
        for error in self.error_log:
            error_type = error['error_type']
            type_counts[error_type] = type_counts.get(error_type, 0) + 1
        return type_counts


class TokenUsageHandler(BaseCallbackHandler):
    """
    Handler para tracking de uso de tokens.

    Features:
    - Contagem precisa por chain
    - Alertas de limite
    - Estatísticas de uso
    """

    def __init__(self, max_tokens_per_request: int = 4000):
        self.max_tokens = max_tokens_per_request
        self.usage_log = []
        self.total_tokens = 0
        self.chain_tokens = {}

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        **kwargs: Any
    ) -> Any:
        """Início de chamada LLM"""
        # Estima tokens do prompt
        import tiktoken
        encoding = tiktoken.get_encoding("cl100k_base")

        prompt_tokens = sum(len(encoding.encode(prompt)) for prompt in prompts)

        self.current_request = {
            'start_time': datetime.now(),
            'prompt_tokens': prompt_tokens,
            'chain_id': kwargs.get('tags', [None])[0] if 'tags' in kwargs else 'unknown'
        }

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> Any:
        """Fim de chamada LLM"""
        if hasattr(self, 'current_request'):
            # Calcula tokens da resposta
            completion_tokens = 0
            for generation in response.generations:
                if generation and generation[0].text:
                    import tiktoken
                    encoding = tiktoken.get_encoding("cl100k_base")
                    completion_tokens += len(encoding.encode(generation[0].text))

            # Registra uso
            usage_data = {
                'timestamp': datetime.now().isoformat(),
                'chain_id': self.current_request['chain_id'],
                'prompt_tokens': self.current_request['prompt_tokens'],
                'completion_tokens': completion_tokens,
                'total_tokens': self.current_request['prompt_tokens'] + completion_tokens,
                'duration_ms': (datetime.now() - self.current_request['start_time']).total_seconds() * 1000
            }

            self.usage_log.append(usage_data)
            self.total_tokens += usage_data['total_tokens']

            # Atualiza contagem por chain
            chain_id = usage_data['chain_id']
            if chain_id not in self.chain_tokens:
                self.chain_tokens[chain_id] = 0
            self.chain_tokens[chain_id] += usage_data['total_tokens']

            # Alerta se próximo do limite
            if usage_data['total_tokens'] > self.max_tokens * 0.8:
                logger.warning(
                    f"Alto uso de tokens: {usage_data['total_tokens']} "
                    f"(limite: {self.max_tokens})"
                )

            # Limpa request atual
            delattr(self, 'current_request')

    def get_usage_summary(self) -> Dict[str, Any]:
        """Retorna resumo de uso de tokens"""
        if not self.usage_log:
            return {'total_tokens': 0, 'requests': 0}

        return {
            'total_tokens': self.total_tokens,
            'total_requests': len(self.usage_log),
            'average_tokens_per_request': self.total_tokens / len(self.usage_log),
            'tokens_by_chain': self.chain_tokens,
            'peak_usage': max(log['total_tokens'] for log in self.usage_log),
            'recent_usage': self.usage_log[-10:]
        }


class PerformanceMonitor(BaseCallbackHandler):
    """
    Monitor de performance das chains.

    Features:
    - Latência por componente
    - Identificação de gargalos
    - Métricas de qualidade
    """

    def __init__(self):
        self.chain_times = {}
        self.current_chain_start = {}

    def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        **kwargs: Any
    ) -> Any:
        """Marca início da chain"""
        chain_name = serialized.get('name', 'unknown')
        self.current_chain_start[chain_name] = datetime.now()

    def on_chain_end(
        self,
        outputs: Dict[str, Any],
        **kwargs: Any
    ) -> Any:
        """Marca fim da chain e calcula duração"""
        # Identifica chain pelo output ou contexto
        for chain_name, start_time in list(self.current_chain_start.items()):
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            if chain_name not in self.chain_times:
                self.chain_times[chain_name] = []

            self.chain_times[chain_name].append({
                'timestamp': datetime.now().isoformat(),
                'duration_ms': duration_ms,
                'outputs': list(outputs.keys()) if outputs else []
            })

            # Remove do tracking atual
            del self.current_chain_start[chain_name]

            # Alerta se muito lento
            if duration_ms > 5000:  # 5 segundos
                logger.warning(f"Chain {chain_name} demorou {duration_ms}ms")

            break

    def get_performance_summary(self) -> Dict[str, Any]:
        """Retorna resumo de performance"""
        summary = {}

        for chain_name, times in self.chain_times.items():
            if not times:
                continue

            durations = [t['duration_ms'] for t in times]
            summary[chain_name] = {
                'avg_duration_ms': sum(durations) / len(durations),
                'min_duration_ms': min(durations),
                'max_duration_ms': max(durations),
                'total_calls': len(times),
                'p95_duration_ms': sorted(durations)[int(len(durations) * 0.95)] if len(durations) > 1 else durations[0]
            }

        return summary


class DebugHandler(BaseCallbackHandler):
    """Handler para debugging detalhado"""

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.trace = []

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> Any:
        """Log início do LLM"""
        if self.verbose:
            logger.debug(f"LLM Start: {serialized.get('name', 'unknown')}")
            logger.debug(f"Prompts: {prompts}")

        self.trace.append({
            'event': 'llm_start',
            'timestamp': datetime.now().isoformat(),
            'data': {'name': serialized.get('name'), 'prompt_preview': prompts[0][:200] if prompts else ''}
        })

    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs: Any) -> Any:
        """Log início da chain"""
        if self.verbose:
            logger.debug(f"Chain Start: {serialized.get('name', 'unknown')}")
            logger.debug(f"Inputs: {list(inputs.keys())}")

        self.trace.append({
            'event': 'chain_start',
            'timestamp': datetime.now().isoformat(),
            'data': {'name': serialized.get('name'), 'input_keys': list(inputs.keys())}
        })

    def get_trace(self) -> List[Dict[str, Any]]:
        """Retorna trace completo"""
        return self.trace