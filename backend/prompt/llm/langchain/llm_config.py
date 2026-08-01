"""
Configuração centralizada para LLMs com otimização de Prompt Caching
=====================================================================

Este módulo fornece funções helper para criar instâncias de ChatOpenAI
otimizadas para o Prompt Caching da OpenAI.

Como funciona o Prompt Caching:
- Reduz latência em até 80% e custo em até 75%
- Ativado automaticamente para prompts >= 1024 tokens
- Cache baseado em prefixo exato (primeiros 256 tokens)
- Parâmetro 'user' ajuda no roteamento de cache
"""

import logging
from typing import Optional, Dict, Any
from langchain_openai import ChatOpenAI

from backend.services.ai_provider_service import (
    AIProviderNotConfiguredError,
    get_company_openai_api_key,
)

logger = logging.getLogger(__name__)

# Modelo padrão para todos os componentes
DEFAULT_MODEL = "gpt-4o-mini"


def create_optimized_llm(
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    user_context: Optional[str] = None,
    enable_cache_logging: bool = True,
    company_id: Optional[int] = None,
    db: Any = None,
    **kwargs
) -> ChatOpenAI:
    """
    Cria uma instância de ChatOpenAI otimizada para Prompt Caching.

    Args:
        model: Nome do modelo (padrão: gpt-4o-mini)
        temperature: Temperatura para geração (0.0-1.0)
        max_tokens: Máximo de tokens na resposta
        user_context: Contexto do usuário para roteamento de cache
                     Ex: "company_42", "parser_chain", "slots_agent"
        enable_cache_logging: Se deve logar métricas de cache
        company_id: Empresa cuja credencial OpenAI validada será usada
        db: Sessão SQLAlchemy opcional. Se ausente, uma sessão curta é aberta
            apenas para resolver a credencial da empresa.
        **kwargs: Argumentos adicionais para ChatOpenAI

    Returns:
        ChatOpenAI: Instância configurada e otimizada

    Exemplo:
        ```python
        # Para um parser
        llm = create_optimized_llm(
            temperature=0.1,
            user_context="parser_extraction",
            company_id=company_id,
            enable_cache_logging=True
        )

        # Para agente de slots
        llm = create_optimized_llm(
            temperature=0.3,
            user_context=f"slots_company_{company_id}",
            company_id=company_id,
            max_tokens=1000
        )
        ```
    """
    api_key = _resolve_company_openai_api_key(
        company_id=company_id,
        db=db,
    )

    # Configuração base
    config = {
        "model": model,
        "temperature": temperature,
    }

    # Adiciona max_tokens se especificado
    if max_tokens:
        config["max_tokens"] = max_tokens

    # Adiciona user para melhor roteamento de cache
    # O user é combinado com o hash do prefixo do prompt
    if user_context:
        config["model_kwargs"] = kwargs.get("model_kwargs", {})
        config["model_kwargs"]["user"] = user_context
        logger.info(f"[LLMConfig] Configurando user context: {user_context}")

    # Mescla kwargs adicionais
    config.update(kwargs)

    # A credencial resolvida da empresa sempre prevalece. Isso impede que um
    # chamador reintroduza acidentalmente uma chave global via kwargs.
    config["openai_api_key"] = api_key

    # Cria instância
    llm = ChatOpenAI(**config)

    # Se cache logging está ativo, configura wrapper
    if enable_cache_logging:
        llm = _add_cache_logging_wrapper(llm, user_context)

    return llm


def _resolve_company_openai_api_key(
    *,
    company_id: Optional[int],
    db: Any = None,
) -> str:
    """Resolve a chave BYOK sem depender de estado global do processo."""

    if company_id is None:
        raise AIProviderNotConfiguredError(
            "Empresa ativa não informada para resolver a chave OpenAI"
        )

    if db is not None:
        return get_company_openai_api_key(db, int(company_id))

    # Alguns consumidores legados criam o LLM apenas com company_id. Mantemos
    # esse contrato abrindo uma sessão curta e fechando-a imediatamente após a
    # leitura da credencial criptografada.
    from backend.db import SessionLocal

    scoped_db = SessionLocal()
    try:
        return get_company_openai_api_key(scoped_db, int(company_id))
    finally:
        scoped_db.close()


def _add_cache_logging_wrapper(llm: ChatOpenAI, context: Optional[str]) -> ChatOpenAI:
    """
    Adiciona wrapper para logar métricas de cache.

    Nota: Por limitações do LangChain, não podemos interceptar diretamente
    a resposta da API. Use a função log_cache_metrics() após invocar o chain.
    """
    # Por ora, apenas retorna o LLM original
    # TODO: Implementar wrapper quando LangChain suportar
    return llm


def log_cache_metrics(response: Any, context: Optional[str] = None) -> None:
    """
    Loga métricas de cache de uma resposta da API.

    Args:
        response: Resposta do LLM/Chain
        context: Contexto opcional para o log

    Exemplo:
        ```python
        response = chain.invoke({"input": "..."})
        log_cache_metrics(response, "parser_chain")
        ```
    """
    try:
        # Tenta extrair métricas de diferentes formatos de resposta
        usage = None

        # Para respostas diretas do LLM
        if hasattr(response, 'response_metadata'):
            usage = response.response_metadata.get('usage', {})
        # Para respostas de chains
        elif isinstance(response, dict) and 'usage' in response:
            usage = response['usage']
        # Para objetos com atributo usage
        elif hasattr(response, 'usage'):
            usage = response.usage

        if usage and 'prompt_tokens_details' in usage:
            details = usage['prompt_tokens_details']
            if details and 'cached_tokens' in details:
                cached_tokens = details['cached_tokens']
                total_prompt = usage.get('prompt_tokens', 0)

                if total_prompt > 0:
                    cache_rate = (cached_tokens / total_prompt) * 100
                    prefix = f"[CacheMetrics-{context}]" if context else "[CacheMetrics]"

                    logger.info(
                        f"{prefix} Cache hit: {cache_rate:.1f}% "
                        f"({cached_tokens}/{total_prompt} tokens cached)"
                    )

                    # Log adicional se cache rate for alta
                    if cache_rate >= 50:
                        cost_reduction = cache_rate * 0.75  # 75% de redução no custo
                        logger.info(
                            f"{prefix} Economia estimada: {cost_reduction:.1f}% no custo do prompt"
                        )
    except Exception as e:
        logger.debug(f"[CacheMetrics] Erro ao extrair métricas: {e}")


def create_cache_optimized_prompt(
    static_content: str,
    dynamic_placeholders: Dict[str, str],
    min_static_tokens: int = 1024
) -> str:
    """
    Helper para criar prompts otimizados para cache.

    Args:
        static_content: Conteúdo estático (instruções, exemplos)
        dynamic_placeholders: Placeholders dinâmicos no formato {key: description}
        min_static_tokens: Mínimo de tokens estáticos para ativar cache

    Returns:
        str: Template de prompt otimizado

    Exemplo:
        ```python
        prompt = create_cache_optimized_prompt(
            static_content='''
            Você é um assistente especializado em agendamentos.

            REGRAS:
            1. Seja sempre cordial
            2. Confirme horários disponíveis
            3. Use formato DD/MM HH:MM

            EXEMPLOS:
            - "Tenho disponível amanhã às 14h"
            - "Posso agendar para segunda-feira às 9h"
            ''',
            dynamic_placeholders={
                "company_name": "Nome da empresa",
                "user_message": "Mensagem atual do usuário",
                "available_slots": "Horários disponíveis"
            }
        )
        ```
    """
    # Monta template com conteúdo estático primeiro
    template_parts = [static_content.strip()]

    # Adiciona seção dinâmica no final
    template_parts.append("\n\n--- INFORMAÇÕES DINÂMICAS ---\n")

    for key, description in dynamic_placeholders.items():
        template_parts.append(f"{description}: {{{key}}}")

    full_template = "\n".join(template_parts)

    # Estima tokens (aproximado)
    estimated_tokens = len(static_content.split()) * 1.3

    if estimated_tokens < min_static_tokens:
        logger.warning(
            f"[CacheOptimizer] Conteúdo estático tem ~{int(estimated_tokens)} tokens. "
            f"Recomenda-se pelo menos {min_static_tokens} tokens para ativar cache."
        )

    return full_template


# Configurações recomendadas por tipo de uso
RECOMMENDED_CONFIGS = {
    "parser": {
        "temperature": 0.1,
        "user_context": "parser",
        "max_tokens": 500
    },
    "validator": {
        "temperature": 0.0,
        "user_context": "validator",
        "max_tokens": 200
    },
    "agent": {
        "temperature": 0.3,
        "user_context": "agent",
        "max_tokens": 1000
    },
    "memory": {
        "temperature": 0.2,
        "user_context": "memory",
        "max_tokens": 800
    },
    "conversation": {
        "temperature": 0.7,
        "user_context": "conversation",
        "max_tokens": 1500
    }
}


def create_llm_for_use_case(
    use_case: str,
    company_id: Optional[int] = None,
    db: Any = None,
    **overrides
) -> ChatOpenAI:
    """
    Cria LLM com configuração recomendada para caso de uso específico.

    Args:
        use_case: Tipo de uso ("parser", "validator", "agent", "memory", "conversation")
        company_id: ID obrigatório da empresa cuja chave BYOK será usada
        db: Sessão SQLAlchemy opcional para resolver a credencial
        **overrides: Sobrescreve configurações padrão

    Returns:
        ChatOpenAI: LLM configurado

    Exemplo:
        ```python
        # Parser para uma empresa de exemplo
        llm = create_llm_for_use_case("parser", company_id=42)

        # Agente com temperatura customizada
        llm = create_llm_for_use_case("agent", company_id=42, temperature=0.5)
        ```
    """
    if use_case not in RECOMMENDED_CONFIGS:
        logger.warning(
            f"[LLMConfig] Caso de uso '{use_case}' não reconhecido. "
            f"Casos válidos: {list(RECOMMENDED_CONFIGS.keys())}"
        )
        config = {}
    else:
        config = RECOMMENDED_CONFIGS[use_case].copy()

    # Adiciona company_id ao contexto se fornecido
    if company_id and "user_context" in config:
        config["user_context"] = f"{config['user_context']}_company_{company_id}"

    # Aplica overrides
    config.update(overrides)

    return create_optimized_llm(
        company_id=company_id,
        db=db,
        **config,
    )
