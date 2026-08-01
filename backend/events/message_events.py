import json
import redis
from typing import Dict, Any

redis_client = redis.Redis(host='localhost', port=6379, db=0)

def publish_message_event(message_data: Dict[str, Any]):
    """Publica um evento de mensagem no Redis"""
    try:
        redis_client.publish('chat_messages', json.dumps(message_data))
    except Exception as e:
        print(f"Erro ao publicar mensagem no Redis: {e}")
