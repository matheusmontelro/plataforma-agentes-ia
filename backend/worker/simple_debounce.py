"""
Sistema de debounce simplificado usando apenas Redis TTL
"""
import redis
import logging
import json
from typing import Optional

logger = logging.getLogger(__name__)
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# Intervalo de debounce compartilhado por todas as empresas (em segundos).
DEFAULT_DEBOUNCE_INTERVAL_SECONDS = 15

def get_debounce_interval(company_id: int) -> int:
    """Retorna o intervalo de debounce genérico da plataforma."""
    return DEFAULT_DEBOUNCE_INTERVAL_SECONDS


def should_process_message(phone: str, company_id: int, message_text: str) -> bool:
    """
    Verifica se deve processar a mensagem usando debounce simples.

    Returns:
        True se deve processar (primeira mensagem ou após intervalo)
        False se deve ignorar (dentro do intervalo de debounce)
    """
    try:
        # Chave para controlar o debounce
        debounce_key = f"debounce:{company_id}:{phone}"

        # Chave para acumular mensagens
        buffer_key = f"buffer:{company_id}:{phone}"

        # Verifica se está em debounce
        if redis_client.exists(debounce_key):
            # Ainda em debounce - adiciona mensagem ao buffer
            logger.info(f"[SIMPLE_DEBOUNCE] Phone {phone} em debounce - adicionando ao buffer")

            # Adiciona mensagem ao buffer
            message_data = json.dumps({
                "text": message_text,
                "timestamp": str(datetime.now())
            })
            redis_client.rpush(buffer_key, message_data)

            # Mantém o buffer pelo tempo do debounce + margem
            interval = get_debounce_interval(company_id)
            redis_client.expire(buffer_key, interval + 5)

            return False  # Não processa agora

        # Não está em debounce - pode processar
        interval = get_debounce_interval(company_id)

        # Define a chave de debounce
        redis_client.setex(debounce_key, interval, "1")

        # Se houver mensagens no buffer, recupera todas
        buffered_messages = []
        if redis_client.exists(buffer_key):
            buffered_messages = redis_client.lrange(buffer_key, 0, -1)
            redis_client.delete(buffer_key)
            logger.info(f"[SIMPLE_DEBOUNCE] Recuperadas {len(buffered_messages)} mensagens do buffer")

        # Adiciona mensagem atual
        current_message = json.dumps({
            "text": message_text,
            "timestamp": str(datetime.now())
        })

        # Salva todas as mensagens para processar
        all_messages_key = f"process:{company_id}:{phone}"

        # Adiciona mensagens bufferizadas + atual
        for msg in buffered_messages:
            redis_client.rpush(all_messages_key, msg)
        redis_client.rpush(all_messages_key, current_message)

        # Define TTL curto para limpeza
        redis_client.expire(all_messages_key, 60)

        logger.info(f"[SIMPLE_DEBOUNCE] ✅ Liberado para processar - {phone} (company {company_id})")
        logger.info(f"[SIMPLE_DEBOUNCE] Próxima mensagem permitida em {interval}s")

        return True

    except Exception as e:
        logger.error(f"[SIMPLE_DEBOUNCE] Erro: {e}")
        # Em caso de erro, processa para não perder mensagem
        return True


def get_accumulated_messages(phone: str, company_id: int) -> str:
    """
    Recupera todas as mensagens acumuladas para processar
    """
    try:
        process_key = f"process:{company_id}:{phone}"
        messages = redis_client.lrange(process_key, 0, -1)

        if not messages:
            return ""

        # Limpa após recuperar
        redis_client.delete(process_key)

        # Extrai apenas os textos
        texts = []
        for msg_json in messages:
            try:
                msg = json.loads(msg_json)
                texts.append(msg.get("text", ""))
            except:
                texts.append(msg_json)  # Fallback se não for JSON

        combined_text = " ".join(texts).strip()
        logger.info(f"[SIMPLE_DEBOUNCE] Texto combinado: {combined_text[:100]}...")

        return combined_text

    except Exception as e:
        logger.error(f"[SIMPLE_DEBOUNCE] Erro ao recuperar mensagens: {e}")
        return ""


def clear_debounce(phone: str, company_id: int):
    """
    Limpa o debounce manualmente (útil para testes)
    """
    try:
        debounce_key = f"debounce:{company_id}:{phone}"
        buffer_key = f"buffer:{company_id}:{phone}"
        process_key = f"process:{company_id}:{phone}"

        redis_client.delete(debounce_key)
        redis_client.delete(buffer_key)
        redis_client.delete(process_key)

        logger.info(f"[SIMPLE_DEBOUNCE] Debounce limpo para {phone} (company {company_id})")

    except Exception as e:
        logger.error(f"[SIMPLE_DEBOUNCE] Erro ao limpar: {e}")


# Importar datetime que faltou
from datetime import datetime
