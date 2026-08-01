"""
Worker dedicado para processar mensagens da Evolution API
Segue o mesmo padrão do process_message.py mas adaptado para estrutura Evolution
"""

import logging
import uuid
import json
from datetime import datetime, timedelta
import datetime as dt
from typing import Dict, Any, Union
import os
from sqlalchemy import text
from sqlalchemy.orm import Session
import pytz
from backend.db import SessionLocal
from backend.ws_manager import manager
from backend.prompt.memory.memory_manager import append_message_to_chat_file
from backend.prompt.media.audio_processing import transcribe_audio, transcribe_video
from backend.prompt.media.image_analysis import analyze_image_with_google_vision
from backend.prompt.llm.llm_manager import create_llm_chain_with_memory, extract_json_from_llm_response
from backend.prompt.db_integration.agendamento_logic import processar_json_do_llm
from backend.worker.celery_app import app
from backend.integrations.burst_processor import process_burst_messages
from backend.integrations.broadcast_redis import publish_to_redis
from backend.models import NPSResponse
from backend.runtime_settings import AD_CAMPAIGN_DIR

# Importar funções auxiliares do process_message.py
from backend.worker.process_message import (
    is_ia_enabled_now,
    append_message_to_chat_file
)

logger = logging.getLogger(__name__)

BASE_AD_CAMPAIGN_DIR = str(AD_CAMPAIGN_DIR)


def convert_evolution_to_zapi_format(evolution_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converte payload Evolution API para formato compatível com Z-API

    Evolution payload (messages.upsert):
    {
        "key": {
            "remoteJid": "5500000000003@s.whatsapp.net",
            "fromMe": false,
            "id": "3EB0XXXXXXXX"
        },
        "message": {
            "conversation": "Texto da mensagem",
            "imageMessage": {...},
            "audioMessage": {...},
            "videoMessage": {...}
        },
        "messageType": "conversation",
        "messageTimestamp": 1704672000,
        "pushName": "João Silva"
    }

    Z-API formato esperado:
    {
        "instanceId": "instance_name",
        "messageId": "message_id",
        "phone": "5500000000003",
        "fromMe": false,
        "momment": 1704672000,
        "status": "RECEIVED",
        "chatName": "João Silva",
        "senderPhoto": "",
        "senderName": "João Silva",
        "participantPhone": null,
        "photo": "",
        "broadcast": false,
        "type": "ReceivedCallback",
        "text": {"message": "Texto da mensagem"},
        "image": {...},
        "audio": {...},
        "video": {...}
    }
    """

    key = evolution_data.get("key", {})
    message = evolution_data.get("message", {})
    message_type = evolution_data.get("messageType", "conversation")

    # Extrair telefone do remoteJid (remove @s.whatsapp.net)
    remote_jid = key.get("remoteJid", "")
    phone = remote_jid.split("@")[0] if "@" in remote_jid else remote_jid

    # Estrutura base compatível com Z-API
    zapi_format = {
        "instanceId": evolution_data.get("instance", ""),
        "messageId": key.get("id", ""),
        "phone": phone,
        "fromMe": key.get("fromMe", False),
        "momment": evolution_data.get("messageTimestamp", int(datetime.now().timestamp())),
        "status": "RECEIVED",
        "chatName": evolution_data.get("pushName", ""),
        "senderPhoto": "",
        "senderName": evolution_data.get("pushName", ""),
        "participantPhone": None,
        "photo": "",
        "broadcast": False,
        "type": "ReceivedCallback"
    }

    # Processar tipo de mensagem
    if message_type == "conversation" or "conversation" in message:
        zapi_format["text"] = {
            "message": message.get("conversation", "")
        }

    elif message_type == "extendedTextMessage" or "extendedTextMessage" in message:
        ext_msg = message.get("extendedTextMessage", {})
        zapi_format["text"] = {
            "message": ext_msg.get("text", "")
        }

    elif message_type == "imageMessage" or "imageMessage" in message:
        img_msg = message.get("imageMessage", {})
        zapi_format["image"] = {
            "mimeType": img_msg.get("mimetype", "image/jpeg"),
            "imageUrl": img_msg.get("url", ""),
            "thumbnailUrl": img_msg.get("thumbnail", ""),
            "caption": img_msg.get("caption", "")
        }
        zapi_format["text"] = {
            "message": img_msg.get("caption", "")
        }

    elif message_type == "audioMessage" or "audioMessage" in message:
        audio_msg = message.get("audioMessage", {})
        zapi_format["audio"] = {
            "audioUrl": audio_msg.get("url", ""),
            "mimeType": audio_msg.get("mimetype", "audio/ogg; codecs=opus")
        }

    elif message_type == "videoMessage" or "videoMessage" in message:
        video_msg = message.get("videoMessage", {})
        zapi_format["video"] = {
            "videoUrl": video_msg.get("url", ""),
            "mimeType": video_msg.get("mimetype", "video/mp4"),
            "caption": video_msg.get("caption", "")
        }
        zapi_format["text"] = {
            "message": video_msg.get("caption", "")
        }

    elif message_type == "documentMessage" or "documentMessage" in message:
        doc_msg = message.get("documentMessage", {})
        zapi_format["document"] = {
            "documentUrl": doc_msg.get("url", ""),
            "mimeType": doc_msg.get("mimetype", ""),
            "fileName": doc_msg.get("fileName", "documento")
        }

    logger.info(f"[EVOLUTION→ZAPI] Convertido {message_type} para formato Z-API")

    return zapi_format


@app.task(name='process_incoming_evolution_message', bind=True, max_retries=3)
def process_incoming_evolution_message(self, evolution_data: Dict[str, Any], instance_name: str, audit_id: int = None):
    """
    Tarefa Celery para processar mensagens da Evolution API

    Args:
        evolution_data: Payload do evento messages.upsert da Evolution API
        instance_name: Nome da instância Evolution (evolution_instance_id)
        audit_id: ID do registro na tabela webhook_audit (opcional)

    Fluxo:
      1) Converte payload Evolution → formato Z-API
      2) Reutiliza toda lógica do process_incoming_zapi_message
      3) Responde via Evolution API (em vez de Z-API)
    """

    db: Session = SessionLocal()
    try:
        logger.info(f"[EVOLUTION-WORKER] Iniciando processamento. instance={instance_name}, audit_id={audit_id}")
        logger.info(f"[EVOLUTION-WORKER] Payload Evolution: {evolution_data}")

        # 1. Ignorar mensagens enviadas por nós (fromMe=True)
        key = evolution_data.get("key", {})
        if key.get("fromMe", False):
            logger.info("[EVOLUTION-WORKER] Mensagem enviada por nós, ignorando")
            return {"status": "ignored", "reason": "fromMe=True"}

        # 2. Buscar company_id baseado no instance_name
        company_row = db.execute(
            text("SELECT id FROM companies WHERE evolution_instance_id = :instance_name"),
            {"instance_name": instance_name}
        ).fetchone()

        if not company_row:
            logger.error(f"[EVOLUTION-WORKER] Empresa não encontrada para instance={instance_name}")
            return {"status": "error", "reason": "company_not_found"}

        company_id = company_row.id
        logger.info(f"[EVOLUTION-WORKER] Empresa encontrada: company_id={company_id}")

        # 3. Converter payload Evolution → Z-API format
        zapi_format_data = convert_evolution_to_zapi_format(evolution_data)
        zapi_format_data["instanceId"] = instance_name

        logger.info(f"[EVOLUTION-WORKER] Payload convertido para Z-API format: {zapi_format_data}")

        # 4. Importar e executar a lógica principal do Z-API
        from backend.worker.process_message import process_incoming_zapi_message

        # A função process_incoming_zapi_message espera (data, instance_id, audit_id)
        # Vamos passar nosso formato convertido
        result = process_incoming_zapi_message(zapi_format_data, instance_name, audit_id)

        logger.info(f"[EVOLUTION-WORKER] Processamento concluído com sucesso")

        return {
            "status": "success",
            "company_id": company_id,
            "instance_name": instance_name,
            "result": result
        }

    except Exception as e:
        logger.error(f"[EVOLUTION-WORKER] Erro ao processar mensagem: {e}", exc_info=True)

        # Atualizar audit se disponível
        if audit_id:
            try:
                from backend.webhook_audit import update_audit_status
                update_audit_status(db, audit_id, "processing_failed", error=str(e))
            except Exception as audit_err:
                logger.error(f"[EVOLUTION-WORKER] Erro ao atualizar audit: {audit_err}")

        # Retry com backoff exponencial
        raise self.retry(exc=e, countdown=2 ** self.request.retries)

    finally:
        db.close()
