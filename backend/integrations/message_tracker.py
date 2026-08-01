# backend/integrations/message_tracker.py
"""
Sistema de tracking para evitar duplicação de mensagens enviadas via frontend
Utiliza Redis com TTL para armazenar temporariamente mensagens enviadas
"""

import redis
import json
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import hashlib

logger = logging.getLogger(__name__)

class MessageTracker:
    """
    Rastreia mensagens enviadas via frontend para evitar duplicação quando
    o WhatsApp provider (WAHA/Z-API) envia callbacks de confirmação
    """

    def __init__(self):
        self.redis = redis.Redis(host='localhost', port=6379, db=1, decode_responses=True)
        self.TTL_SECONDS = 300  # 5 minutos

    def _generate_fingerprint(self, company_id: int, phone: str, message_type: str, content: Any) -> str:
        """
        Gera um fingerprint único para a mensagem baseado no conteúdo

        Args:
            company_id: ID da empresa
            phone: Telefone do contato
            message_type: Tipo da mensagem (image, video, audio, text)
            content: Conteúdo da mensagem (base64, URL ou texto)

        Returns:
            String hash fingerprint
        """
        # Para conteúdo base64, usar apenas os primeiros 100 caracteres para evitar hash enorme
        content_str = content
        if isinstance(content, str):
            if content.startswith('data:'):
                # Extrair tipo e primeiros 100 chars do base64
                parts = content.split(',')
                if len(parts) == 2:
                    content_type = parts[0]
                    base64_content = parts[1][:100]
                    content_str = f"{content_type},{base64_content}"
            elif len(content) > 100:
                content_str = content[:100]

        fingerprint_data = f"{company_id}:{phone}:{message_type}:{content_str}"
        return hashlib.md5(fingerprint_data.encode()).hexdigest()

    def track_outgoing_message(self, company_id: int, phone: str, message_type: str, content: Any, local_message_id: str = None) -> str:
        """
        Registra uma mensagem enviada via frontend para evitar duplicação

        Args:
            company_id: ID da empresa
            phone: Telefone do contato
            message_type: Tipo da mensagem
            content: Conteúdo da mensagem
            local_message_id: ID local da mensagem (gerado pelo frontend)

        Returns:
            fingerprint da mensagem
        """
        fingerprint = self._generate_fingerprint(company_id, phone, message_type, content)

        try:
            track_data = {
                'fingerprint': fingerprint,
                'company_id': company_id,
                'phone': phone,
                'message_type': message_type,
                'local_message_id': local_message_id,
                'created_at': datetime.utcnow().isoformat(),
                'from_frontend': True
            }

            # Salvar no Redis com fingerprint como chave
            key = f"message_tracker:{fingerprint}"
            self.redis.setex(key, self.TTL_SECONDS, json.dumps(track_data))

            # Também salvar por local_message_id se fornecido
            if local_message_id:
                local_key = f"message_tracker:local:{local_message_id}"
                self.redis.setex(local_key, self.TTL_SECONDS, json.dumps(track_data))

            logger.info(f"[MessageTracker] Mensagem registrada: fingerprint={fingerprint}, local_id={local_message_id}")

            return fingerprint

        except Exception as e:
            logger.error(f"[MessageTracker] Erro ao registrar mensagem: {e}")
            return fingerprint

    def is_duplicate_message(self, company_id: int, phone: str, message_type: str, content: Any, from_me: bool = False) -> Optional[Dict[str, Any]]:
        """
        Verifica se a mensagem é duplicata de uma enviada via frontend

        Args:
            company_id: ID da empresa
            phone: Telefone do contato
            message_type: Tipo da mensagem
            content: Conteúdo da mensagem
            from_me: Se a mensagem foi enviada por mim

        Returns:
            Dados da mensagem original se for duplicata, None caso contrário
        """
        # Se não for from_me, não pode ser duplicata de envio nosso
        if not from_me:
            return None

        fingerprint = self._generate_fingerprint(company_id, phone, message_type, content)

        try:
            key = f"message_tracker:{fingerprint}"
            tracked_data = self.redis.get(key)

            if tracked_data:
                data = json.loads(tracked_data)
                logger.info(f"[MessageTracker] Duplicata detectada: fingerprint={fingerprint}")
                return data

            return None

        except Exception as e:
            logger.error(f"[MessageTracker] Erro ao verificar duplicata: {e}")
            return None

    def clear_message_tracking(self, local_message_id: str = None, fingerprint: str = None):
        """
        Remove tracking de uma mensagem (útil para cleanup)

        Args:
            local_message_id: ID local da mensagem
            fingerprint: Fingerprint da mensagem
        """
        try:
            if local_message_id:
                local_key = f"message_tracker:local:{local_message_id}"
                tracked_data = self.redis.get(local_key)
                if tracked_data:
                    data = json.loads(tracked_data)
                    fingerprint = data['fingerprint']
                    self.redis.delete(local_key)

            if fingerprint:
                key = f"message_tracker:{fingerprint}"
                self.redis.delete(key)

                logger.info(f"[MessageTracker] Tracking removido: local_id={local_message_id}, fingerprint={fingerprint}")

        except Exception as e:
            logger.error(f"[MessageTracker] Erro ao limpar tracking: {e}")

# Instância global do tracker
message_tracker = MessageTracker()