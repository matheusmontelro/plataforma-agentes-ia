import redis
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo  # disponível no Python 3.9+

from backend.events.websocket_channels import websocket_channel, websocket_redis_url

logger = logging.getLogger(__name__)

def publish_to_redis(company_id: int, message: dict):
    """
    Publica 'message' no canal 'chat_messages:{company_id}' via redis-py (síncrono).
    Caso não haja 'momment', insere um com timezone 'America/Sao_Paulo'.
    """
    r = redis.Redis.from_url(websocket_redis_url())
    channel = websocket_channel(f"chat_messages:{company_id}")

    # Garante que cada mensagem tenha um campo "momment" (ISO-8601) no fuso SP
    if "momment" not in message:
        tz_sp = ZoneInfo("America/Sao_Paulo")
        # Se preferir, pode usar timespec='seconds' ou 'microseconds'
        message["momment"] = datetime.now(tz_sp).isoformat(timespec='seconds')

    try:
        r.publish(channel, json.dumps(message))
        logger.info(
            f"[RedisPublish] Mensagem publicada no canal {channel} "
            f"(momment={message['momment']})"
        )
    except Exception as e:
        logger.error(
            f"[RedisPublish] Erro ao publicar no Redis: {e}",
            exc_info=True
        )
    finally:
        r.close()
