# backend/worker/process_message_waha.py
"""
Processamento de mensagens recebidas do WAHA

WAHA é o único provider WhatsApp ativo para recebimento/envio neste produto.
"""

import logging
import uuid
import json
import os
import re
import base64
import requests
import time
from celery.exceptions import Retry
from datetime import datetime, timedelta
import datetime as dt
from typing import Dict, Any, Optional
from urllib.parse import urlparse
from sqlalchemy import text
from sqlalchemy.orm import Session
from backend.db import SessionLocal
from backend.worker.celery_app import app
from backend.prompt.memory.memory_manager import append_message_to_chat_file
from backend.prompt.media.audio_processing import transcribe_audio, transcribe_video
from backend.integrations.broadcast_redis import publish_to_redis
from backend.webhook_audit import update_audit_status
from backend.services.pipeline_service import PipelineService
from backend.services.ai_provider_service import (
    AIProviderCredentialError,
    get_company_openai_api_key,
)
from backend.services.message_metadata import (
    extract_waha_reply_to,
    map_waha_ack_to_delivery_status,
    update_message_delivery_status,
    update_message_reactions,
)
from backend.runtime_settings import MEDIA_BASE_PATH
logger = logging.getLogger(__name__)

# Cache Redis removido - agora usando BD como única fonte de verdade
WAHA_OPERATIONAL_LOCK_RETRY_SECONDS = 5

# Diretório base para mídias baixadas do WAHA
MEDIA_ROOT_DIR = str(MEDIA_BASE_PATH)
WAHA_MEDIA_DIR = os.getenv("WAHA_MEDIA_DIR", os.path.join(MEDIA_ROOT_DIR, "waha"))
WAHA_FILES_MARKER = "/api/files/"
WAHA_MEDIA_ROUTE_PREFIX = "/api/waha/media/"


def _company_openai_key_for_media(db: Session, company_id: int) -> str:
    try:
        return get_company_openai_api_key(db, int(company_id))
    except AIProviderCredentialError:
        logger.info(
            "[WAHA Task] Midia sem transcricao: chave OpenAI da empresa indisponivel company_id=%s",
            company_id,
        )
        return ""


def _extract_waha_file_path(waha_url: str) -> str:
    """Return the path after /api/files/ without logging or exposing full URLs."""
    if not waha_url or WAHA_FILES_MARKER not in waha_url:
        return ""

    file_path = waha_url.split(WAHA_FILES_MARKER, 1)[1].split("?", 1)[0]
    return file_path.lstrip("/")


def _build_internal_waha_file_url(file_path: str) -> str:
    if not file_path:
        return ""

    from backend.config import WAHA_BASE_URL

    return f"{WAHA_BASE_URL.rstrip('/')}/api/files/{file_path.lstrip('/')}"


def _waha_proxy_media_url(waha_url: str) -> str:
    file_path = _extract_waha_file_path(waha_url)
    if not file_path:
        return waha_url
    return f"{WAHA_MEDIA_ROUTE_PREFIX}{file_path}"


def _absolute_waha_proxy_media_url(waha_url: str) -> str:
    proxy_url = _waha_proxy_media_url(waha_url)
    if proxy_url == waha_url:
        return waha_url

    from backend.config import PUBLIC_BASE_URL

    return f"{PUBLIC_BASE_URL.rstrip('/')}{proxy_url}"


def _is_waha_proxy_media_url(media_url: str) -> bool:
    if not media_url:
        return False
    parsed = urlparse(media_url)
    path = parsed.path if parsed.scheme in {"http", "https"} else media_url
    return path.startswith(WAHA_MEDIA_ROUTE_PREFIX)


def _materialize_audio_content(audio_url: str, mimetype: str) -> str:
    if not audio_url:
        return ""

    if audio_url.startswith("data:"):
        logger.info("[WAHA Task] Áudio base64 já processado: chars=%s", _len_or_zero(audio_url))
        return audio_url

    if _is_waha_proxy_media_url(audio_url):
        logger.info("[WAHA Task] Áudio WAHA local preservado para transcrição: url_present=%s", bool(audio_url))
        return audio_url

    try:
        from backend.config import WAHA_BASE_URL, WAHA_API_KEY

        logger.info("[WAHA Task] Convertendo URL WAHA para base64: url_present=%s", bool(audio_url))

        file_path = _extract_waha_file_path(audio_url)
        if file_path:
            internal_url = f"{WAHA_BASE_URL.rstrip('/')}/api/files/{file_path}"
            headers = {"X-Api-Key": WAHA_API_KEY} if WAHA_API_KEY else {}

            logger.info("[WAHA Task] Fazendo download via API interna: url_present=%s", bool(internal_url))
            response = requests.get(internal_url, headers=headers or None, timeout=30)
            response.raise_for_status()
        else:
            response = requests.get(audio_url, timeout=30)
            response.raise_for_status()

        base64_audio = base64.b64encode(response.content).decode("utf-8")
        content = f"data:{mimetype};base64,{base64_audio}"
        logger.info("[WAHA Task] Áudio convertido para base64: mimetype=%s size=%s", mimetype, len(base64_audio))
        return content
    except Exception as e:
        logger.error("[WAHA Task] Erro ao converter áudio para base64: %s", e)
        return audio_url


def _len_or_zero(value: Any) -> int:
    return len(str(value or ""))


def _iter_flow_results(flow_result: Optional[Dict[str, Any]]):
    if isinstance(flow_result, dict):
        yield flow_result
        for entry in flow_result.get("execution_log", []):
            if not isinstance(entry, dict):
                continue
            result = entry.get("result")
            if isinstance(result, dict):
                yield result


def _flow_result_has_flag(flow_result: Optional[Dict[str, Any]], flag: str) -> bool:
    return any(bool(result.get(flag)) for result in _iter_flow_results(flow_result))


def _flow_result_workforce_status(flow_result: Optional[Dict[str, Any]]) -> Optional[str]:
    for result in _iter_flow_results(flow_result):
        status = result.get("workforce_status")
        if status and status != "active":
            return str(status)
    return None


def _flow_result_error(flow_result: Optional[Dict[str, Any]]) -> str:
    if not isinstance(flow_result, dict):
        return ""
    if flow_result.get("error"):
        return str(flow_result.get("error"))
    for entry in flow_result.get("execution_log", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("error"):
            return str(entry.get("error"))
        result = entry.get("result")
        if isinstance(result, dict) and result.get("error"):
            return str(result.get("error"))
    return "FlowBuilder falhou"


def _waha_payload_summary(waha_payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = waha_payload.get("payload", {}) if isinstance(waha_payload, dict) else {}
    _data = payload.get("_data", {}) if isinstance(payload, dict) else {}
    message = _data.get("Message", {}) if isinstance(_data, dict) else {}
    media = payload.get("media", {}) if isinstance(payload, dict) else {}

    return {
        "event": waha_payload.get("event") if isinstance(waha_payload, dict) else None,
        "session": waha_payload.get("session") if isinstance(waha_payload, dict) else None,
        "payload_keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
        "message_keys": sorted(message.keys()) if isinstance(message, dict) else [],
        "media": {
            "has_url": bool(media.get("url")) if isinstance(media, dict) else False,
            "mimetype": media.get("mimetype") if isinstance(media, dict) else None,
            "filename_present": bool(media.get("filename")) if isinstance(media, dict) else False,
        },
        "body_len": _len_or_zero(payload.get("body")) if isinstance(payload, dict) else 0,
    }


def _normalized_summary(normalized_data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "phone": normalized_data.get("phone"),
        "reply_to_chat_id": normalized_data.get("reply_to_chat_id"),
        "type": normalized_data.get("type"),
        "fromMe": normalized_data.get("fromMe"),
        "messageId": normalized_data.get("messageId"),
        "text_len": _len_or_zero(normalized_data.get("text", {}).get("message"))
        if isinstance(normalized_data.get("text"), dict)
        else 0,
        "has_image": bool(normalized_data.get("image")),
        "has_audio": bool(normalized_data.get("audio")),
        "has_video": bool(normalized_data.get("video")),
        "has_contact": bool(normalized_data.get("contact")),
    }


def _clean_waha_chat_id(value: Any) -> str:
    text_value = str(value or "").strip()
    return (
        text_value
        .replace("@c.us", "")
        .replace("@s.whatsapp.net", "")
        .replace("@g.us", "")
        .replace("@lid", "")
    )


def _waha_conversation_kind(payload: Dict[str, Any]) -> Optional[str]:
    """Classify non-direct WAHA chats using identifier fields only."""
    data = payload.get("_data")
    data = data if isinstance(data, dict) else {}
    info = data.get("Info")
    info = info if isinstance(info, dict) else {}
    data_id = data.get("id")
    data_id = data_id if isinstance(data_id, dict) else {}

    identifiers = (
        payload.get("from"),
        payload.get("to"),
        payload.get("author"),
        payload.get("participant"),
        payload.get("chatId"),
        payload.get("id"),
        data_id.get("remote"),
        data_id.get("participant"),
        info.get("Chat"),
        info.get("Sender"),
        info.get("SenderAlt"),
        info.get("Recipient"),
        info.get("RecipientAlt"),
    )
    normalized_identifiers = [
        str(identifier).strip().lower()
        for identifier in identifiers
        if identifier is not None
    ]

    if any("status@broadcast" in identifier for identifier in normalized_identifiers):
        return "status"
    if any("@newsletter" in identifier for identifier in normalized_identifiers):
        return "newsletter"
    if any("@g.us" in identifier for identifier in normalized_identifiers):
        return "group"
    return None


def _waha_message_source(payload: Dict[str, Any]) -> str:
    return str(payload.get("source") or "").strip().lower()


def _waha_media_info(payload: Dict[str, Any]) -> Dict[str, Any]:
    media = payload.get("media")
    return media if isinstance(media, dict) else {}


def _waha_media_url(payload: Dict[str, Any]) -> str:
    media_url = _waha_media_info(payload).get("url")
    if media_url:
        return str(media_url)
    legacy_media_url = payload.get("mediaUrl")
    return str(legacy_media_url or "")


def _waha_text_body(payload: Dict[str, Any]) -> str:
    body = payload.get("body")
    if body:
        return str(body)

    message_data = payload.get("_data", {}).get("Message", {})
    if not isinstance(message_data, dict):
        return ""

    for candidate in (
        message_data.get("conversation"),
        message_data.get("extendedTextMessage", {}).get("text")
        if isinstance(message_data.get("extendedTextMessage"), dict)
        else None,
    ):
        if candidate:
            return str(candidate)
    return ""


def _message_tracker_content_for_check(msg_type: str, normalized_data: Dict[str, Any], content: Any) -> Any:
    if msg_type == "image":
        return normalized_data.get("image", {}).get("imageUrl") or content
    if msg_type == "video":
        return normalized_data.get("video", {}).get("videoUrl") or content
    if msg_type == "audio":
        return normalized_data.get("audio", {}).get("audioUrl") or content
    if msg_type == "text":
        return normalized_data.get("text", {}).get("message") or content
    return content


def _update_waha_ack_delivery_status(
    db: Session,
    company_id: int,
    message_id: str,
    delivery_status: str,
    ack_status: Any,
    ack_name: Any,
    retry_attempts: int = 2,
    retry_delay_seconds: float = 0.6,
) -> Optional[Dict[str, Any]]:
    attempts = max(1, retry_attempts)
    for attempt in range(attempts):
        updated = update_message_delivery_status(
            db=db,
            company_id=company_id,
            provider_message_id=message_id,
            status=delivery_status,
            ack=ack_status,
            ack_name=ack_name,
            publish=True,
        )
        if updated:
            return updated

        if attempt < attempts - 1:
            logger.info(
                "[WAHA Task] ACK sem mensagem local; retentando status update: message_id=%s attempt=%s/%s",
                message_id,
                attempt + 2,
                attempts,
            )
            time.sleep(retry_delay_seconds)

    return None


def download_waha_media(waha_url: str, company_id: int, message_id: str) -> str:
    """
    Faz download da mídia do WAHA e salva localmente para evitar perda por cleanup

    Args:
        waha_url: URL do WAHA (ex: http://localhost:3000/api/files/company68/arquivo.jpg)
        company_id: ID da empresa
        message_id: ID da mensagem para nome único

    Returns:
        URL do proxy backend para o arquivo salvo ou string vazia se falhar
    """
    try:
        # Extrair informações da URL da WAHA, independente do host informado no webhook.
        file_path = _extract_waha_file_path(waha_url)
        if not file_path:
            logger.warning("[WAHA Download] URL inválida: present=%s", bool(waha_url))
            return ""

        original_filename = file_path.rsplit("/", 1)[-1]
        file_extension = ""
        if "." in original_filename:
            file_extension = f".{original_filename.split('.')[-1]}"

        # Criar diretório da empresa se não existir
        company_dir = os.path.join(WAHA_MEDIA_DIR, f"company_{company_id}")
        os.makedirs(company_dir, exist_ok=True)

        # Gerar nome único de arquivo
        unique_filename = f"{message_id}_{original_filename}"
        local_path = os.path.join(company_dir, unique_filename)

        # Fazer download usando a base interna configurada para a WAHA.
        logger.info("[WAHA Download] Baixando mídia: company_id=%s path=%s", company_id, local_path)

        from backend.config import WAHA_API_KEY

        headers = {'X-Api-Key': WAHA_API_KEY} if WAHA_API_KEY else {}
        response = requests.get(
            _build_internal_waha_file_url(file_path),
            timeout=30,
            stream=True,
            headers=headers
        )

        if response.status_code != 200:
            logger.error(f"[WAHA Download] Erro {response.status_code}: {response.text[:200]}")
            return ""

        # Salvar arquivo
        with open(local_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        file_size = os.path.getsize(local_path)
        logger.info(f"[WAHA Download] ✅ Arquivo salvo: {local_path} ({file_size} bytes)")

        # Retornar URL same-origin do proxy para salvar/renderizar em dev e produção.
        return f"/api/waha/media/company_{company_id}/{unique_filename}"

    except Exception as e:
        logger.error(f"[WAHA Download] ❌ Erro ao baixar mídia: {e}", exc_info=True)
        return ""


# Funções de cache removidas - agora usando BD como única fonte de verdade


def _create_waha_referral_lead(
    db: Session,
    company_id: int,
    client_id_db: int,
    name: str,
    phone: str,
    referrer_phone: str,
    campaign
) -> bool:
    """
    Cria lead a partir de vCard recebido via WAHA para sistema de indicações

    Args:
        db: Sessão do banco
        company_id: ID da empresa
        client_id_db: ID do client
        name: Nome do contato indicado
        phone: Telefone do contato indicado
        referrer_phone: Telefone de quem indicou
        campaign: Campanha de indicação ativa

    Returns:
        True se lead criado com sucesso
    """
    from backend.models import Customer, Lead

    try:
        # Verificar se cliente já existe
        existing_customer = db.query(Customer).filter(
            Customer.phone == phone,
            Customer.company_id == company_id
        ).first()

        if existing_customer:
            logger.info(f"[WAHA Referral] Cliente {name} ({phone}) já existe na empresa {company_id}")
            return True

        # Verificar se lead já existe
        existing_lead = db.query(Lead).filter(
            Lead.phone == phone,
            Lead.company_id == company_id
        ).first()

        if existing_lead:
            logger.info(f"[WAHA Referral] Lead para {name} ({phone}) já existe")
            return True

        # Encontrar cliente que indicou (agora Customer)
        referrer_customer = db.query(Customer).filter(
            Customer.phone == referrer_phone,
            Customer.company_id == company_id
        ).first()

        # Criar novo lead
        new_lead = Lead(
            name=name,
            phone=phone,
            company_id=company_id,
            status="new",
            source="referral",
            referral_campaign_id=campaign.id,
            referred_by_customer_id=referrer_customer.id if referrer_customer else None,
            notes=f"Indicado via WhatsApp por {referrer_phone} - Campanha: {campaign.name}"
        )

        db.add(new_lead)
        db.commit()
        db.refresh(new_lead)

        # Atribuir lead ao pipeline padrão da empresa
        try:
            PipelineService.assign_lead_to_first_stage(new_lead, db)
            logger.info(f"[WAHA Referral] ✅ Lead atribuído ao pipeline com sucesso")
        except Exception as pipeline_error:
            logger.error(f"[WAHA Referral] ❌ Erro ao atribuir lead ao pipeline: {pipeline_error}")
            # Não falhar a operação principal se o pipeline falhar

        logger.info(
            f"[WAHA Referral] ✅ Lead criado com sucesso: "
            f"ID={new_lead.id}, Nome={name}, Telefone={phone}, "
            f"Indicado por={referrer_phone}, Campanha={campaign.name}"
        )

        return True

    except Exception as e:
        logger.error(f"[WAHA Referral] Erro ao criar lead para {name} ({phone}): {e}", exc_info=True)
        db.rollback()
        return False




def normalize_waha_payload(waha_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza payload WAHA para formato interno (compatível com Z-API)

    WAHA Format:
    {
      "event": "message",
      "session": "default",
      "payload": {
        "id": "...",
        "from": "5500000000004@c.us",
        "fromMe": false,
        "body": "texto",
        "type": "chat",  # ou "image", "video", "audio", etc
        "timestamp": 1234567890,
        "mediaUrl": "http://...",  # se for mídia
        ...
      }
    }

    Internal Format (Z-API compatible):
    {
      "type": "ReceivedCallback",
      "phone": "5500000000004",
      "chatName": "Nome do Contato",
      "senderName": "Nome do Contato",
      "fromMe": false,
      "messageId": "...",
      "momment": "...",
      "text": {"message": "texto"},  # ou "image", "audio", "video"
      "isGroup": false,
      "isEdit": false,
      "isNewsletter": false,
      "broadcast": false,
      "waitingMessage": false
    }
    """

    payload = waha_data.get("payload", {})
    conversation_kind = _waha_conversation_kind(payload)

    # Extrair telefone REAL e chat ID para resposta
    # _data.Info.SenderAlt contém o telefone real: "5500000000004:96@s.whatsapp.net"
    # from contém o chat para responder: "000000000000002@lid" (ID oculto)
    # Extrair telefone REAL e chat ID para resposta
    # _data.Info.SenderAlt contém o telefone real: "5500000000004:96@s.whatsapp.net"
    # from contém o chat para responder: "000000000000002@lid" (ID oculto)
    sender_alt = payload.get("_data", {}).get("Info", {}).get("SenderAlt", "")
    from_field = payload.get("from", "")
    to_field = payload.get("to", "")
    from_me = payload.get("fromMe", False)

    # 🔥 CORREÇÃO: Se for mensagem enviada (fromMe=True), o contato é o destinatário (to)
    if from_me and to_field:
        phone = _clean_waha_chat_id(to_field)
        logger.info(f"[WAHA Normalize] Mensagem enviada (fromMe), usando destinatário: {phone}")

    # Extrair telefone real do SenderAlt (formato: "5500000000004:96@s.whatsapp.net")
    elif sender_alt and "@s.whatsapp.net" in sender_alt:
        # Remove ":96@s.whatsapp.net" para pegar apenas o telefone
        phone = sender_alt.split(":")[0] if ":" in sender_alt else sender_alt.split("@")[0]
    elif payload.get("author"):
        # Fallback: usar author (para grupos)
        phone = _clean_waha_chat_id(payload["author"])
    else:
    # Fallback final: usar from normalizado
        # 🔥 PROTEÇÃO CONTRA IDs LID (Linked Device)
        # Se vier de @lid e não tivermos conseguido extrair do SenderAlt ou author,
        # tentar resolver o LID via API do WAHA.
        if "@lid" in from_field:
            if not sender_alt and not payload.get("author"):
                # Tentar extrair de _data.id.remote se for diferente e não for LID
                remote = payload.get("_data", {}).get("id", {}).get("remote", "")
                if remote and "@lid" not in remote:
                    phone = _clean_waha_chat_id(remote)
                else:
                    # TENTATIVA DE RESOLUÇÃO VIA API
                    # Precisamos resolver o LID para um número real
                    try:
                        from backend.integrations.waha_sdk import get_client
                        from backend.config import WAHA_API_KEY, WAHA_BASE_URL

                        session_name = waha_data.get("session", "default")

                        if WAHA_API_KEY:
                            logger.info(f"[WAHA Normalize] Tentando resolver LID {from_field} via API...")
                            client = get_client(base_url=WAHA_BASE_URL, api_key=WAHA_API_KEY)
                            resolved_phone = client.get_phone_by_lid(session_name, from_field)

                            if resolved_phone:
                                phone = resolved_phone
                                logger.info(f"[WAHA Normalize] ✅ LID resolvido com sucesso: {from_field} -> {phone}")
                            else:
                                logger.warning(f"[WAHA Normalize] ⚠️ Falha ao resolver LID via API: {from_field}")
                                phone = None
                        else:
                             logger.warning(f"[WAHA Normalize] WAHA_API_KEY não configurada, não é possível resolver LID.")
                             phone = None

                    except Exception as e:
                        logger.error(f"[WAHA Normalize] Erro ao tentar resolver LID: {e}")
                        phone = None
            else:
                 phone = _clean_waha_chat_id(from_field)
        else:
             phone = _clean_waha_chat_id(from_field)

    # Preservar o "from" original para responder (pode ser @lid, @c.us, etc)
    reply_to_chat_id = from_field  # Usar este ID para enviar resposta

    # Extrair tipo de mensagem
    # WAHA guarda o tipo real em _data.Info.MediaType (ex: "vcard", "image", "audio")
    media_type = payload.get("_data", {}).get("Info", {}).get("MediaType", "chat")

    # 🔥 CORREÇÃO: Se MediaType vier vazio (string vazia), forçar "chat"
    if not media_type:
        media_type = "chat"

    # CORREÇÃO: Para áudios, WAHA não preenche MediaType. Precisamos verificar _data.Message
    if media_type == "chat":
        # Verificar se existe audioMessage, imageMessage, videoMessage, etc em _data.Message
        message_data = payload.get("_data", {}).get("Message", {})
        if "audioMessage" in message_data:
            media_type = "audio"
        elif "imageMessage" in message_data:
            media_type = "image"
        elif "videoMessage" in message_data:
            media_type = "video"
        elif "contactMessage" in message_data:
            media_type = "vcard"
        elif "stickerMessage" in message_data:
             media_type = "sticker"
        elif "documentMessage" in message_data:
             media_type = "document"
        elif "locationMessage" in message_data:
             media_type = "location"

    # Fallback para type normal caso MediaType não exista
    msg_type = payload.get("type", media_type)

    # 🔥 CORREÇÃO: Se msg_type ainda for vazio, forçar "chat"
    if not msg_type:
        msg_type = "chat"
    from_me = payload.get("fromMe", False)
    message_id = payload.get("id", f"waha_{uuid.uuid4()}")
    timestamp = payload.get("timestamp", int(dt.datetime.now().timestamp()))
    message_source = _waha_message_source(payload)

    # Mapear tipo WAHA → formato interno
    # WAHA types: chat, image, video, audio, document, ptt (voice), location, vcard, etc
    type_mapping = {
        "chat": "text",
        "image": "image",
        "video": "video",
        "audio": "audio",
        "ptt": "audio",  # Push-to-talk (voice message)
        "document": "file",
        "vcard": "contact",
        "media": "contact",  # WAHA usa MediaType="media" para vCards
        "sticker": "sticker",
        "location": "location",
        "e2e_notification": "ignore", # Notificações de criptografia
        "ciphertext": "ignore",       # Mensagens aguardando descritografia
        "protocol": "ignore",         # Protocolos de sistema
        "revoked": "ignore",          # Mensagens apagadas
        "groups_v4_invite": "ignore", # Convites de grupo
        "notification_template": "ignore", # Templates de notificação
        "call_log": "ignore",         # Logs de chamada
        "gp2": "ignore",              # Outros tipos de sistema
        "broadcast_notification": "ignore" # Notificações de lista de transmissão
    }

    # Default to "ignore" if unknown to prevent ghost messages
    internal_type = type_mapping.get(msg_type, "ignore")

    # Log para debug
    logger.info(f"[WAHA Normalize] Tipo detectado: msg_type={msg_type}, media_type={media_type}, internal_type={internal_type}")

    # Extrair nome do contato (WAHA usa _data.Info.PushName)
    push_name = payload.get("_data", {}).get("Info", {}).get("PushName", phone)
    logger.info(f"[WAHA Normalize] Nome extraído: '{push_name}' (PushName)")

    # Construir payload normalizado
    normalized = {
        "type": "ReceivedCallback",
        "phone": phone,
        "reply_to_chat_id": reply_to_chat_id,  # Preservar ID original para resposta
        "chatName": push_name,  # CORRIGIDO: Usar PushName ao invés de notifyName
        "senderName": push_name,  # CORRIGIDO: Usar PushName ao invés de notifyName
        "fromMe": from_me,
        "messageId": message_id,
        "momment": str(timestamp),
        "isGroup": conversation_kind == "group",
        "isEdit": False,
        "isNewsletter": conversation_kind == "newsletter",
        "broadcast": conversation_kind == "status",
        "waitingMessage": False,
        "photo": "",  # WAHA não fornece foto no payload de mensagem
        "fromApi": bool(from_me and message_source == "api"),
        "source": message_source,
    }

    reply_to_metadata = extract_waha_reply_to(payload)
    if reply_to_metadata:
        normalized["replyTo"] = reply_to_metadata

    # 🆕 EXTRAÇÃO DE DADOS DE ANÚNCIO (compatível com Z-API)
    data_obj = waha_data.get("payload", {}).get("_data", {})
    if data_obj:
        # TENTATIVA 1: Caminho extendedTextMessage.contextInfo.externalAdReply
        external_ad_reply = (
            data_obj
            .get("Message", {})
            .get("extendedTextMessage", {})
            .get("contextInfo", {})
            .get("externalAdReply", {})
        )

        if external_ad_reply:
            normalized.update({
                "sourceId": external_ad_reply.get("sourceID"),
                "thumbnailUrl": external_ad_reply.get("thumbnailURL"),
                "originalImageURL": external_ad_reply.get("originalImageURL"),
                "sourceApp": external_ad_reply.get("sourceApp"),
                "sourceType": external_ad_reply.get("sourceType", "ad"),
                "sourceURL": external_ad_reply.get("sourceURL"),
                "externalAdReply": external_ad_reply  # Para debug/futuro
            })
            logger.info(f"[WAHA Normalize] Anúncio extraído via extendedTextMessage: sourceId={external_ad_reply.get('sourceID')}")

    # Adicionar conteúdo conforme o tipo
    if internal_type == "text":
        normalized["text"] = {
            "message": _waha_text_body(payload)
        }
    elif internal_type == "image":
        media_info = _waha_media_info(payload)
        normalized["image"] = {
            "imageUrl": _waha_media_url(payload),
            "caption": payload.get("caption") or payload.get("body", ""),
            "mimetype": media_info.get("mimetype", ""),
        }
    elif internal_type == "audio":
        # 🔥 CORREÇÃO CRÍTICA: WAHA fornece áudio como base64 em _data.Message.audioMessage
        audio_message = payload.get("_data", {}).get("Message", {}).get("audioMessage", {})

        if audio_message:
            # Extrair dados base64 do áudio
            audio_base64 = audio_message.get("base64", "")
            mimetype = audio_message.get("mimetype", "audio/ogg; codecs=opus")

            if audio_base64:
                # Construir data URL para compatibilidade com transcrição
                audio_data_url = f"data:{mimetype};base64,{audio_base64}"
                normalized["audio"] = {
                    "audioUrl": audio_data_url,
                    "mimetype": mimetype
                }
                logger.info(f"[WAHA Normalize] Áudio base64 extraído: mimetype={mimetype}, size={len(audio_base64)}")
            else:
                # Fallback: tentar mediaUrl (para áudios legacy)
                audio_url = _waha_media_url(payload)
                normalized["audio"] = {
                    "audioUrl": audio_url
                }
                logger.warning(
                    "[WAHA Normalize] Áudio base64 não encontrado, usando fallback mediaUrl (present=%s)",
                    bool(audio_url),
                )
        else:
            # Fallback: tentar mediaUrl (para áudios legacy)
            audio_url = _waha_media_url(payload)
            normalized["audio"] = {
                "audioUrl": audio_url
            }
            logger.warning(
                "[WAHA Normalize] audioMessage não encontrado, usando fallback mediaUrl (present=%s)",
                bool(audio_url),
            )
    elif internal_type == "video":
        # 🔥 CORREÇÃO: WAHA usa payload.media.url para vídeos
        video_url = _waha_media_url(payload)
        normalized["video"] = {
            "videoUrl": video_url,
            "caption": payload.get("caption") or payload.get("body", "")
        }
    elif internal_type == "contact":
        # vCard - extrair informações do contato (baseado na documentação WAHA)
        # WAHA guarda vCard em _data.Message.contactMessage
        contact_message = payload.get("_data", {}).get("Message", {}).get("contactMessage", {})
        vcard_string = contact_message.get("vcard", "")
        display_name = contact_message.get("displayName", "")

        if vcard_string:
            # Parse inteligente do vCard (formato VCARD 3.0)
            parsed_contact = _parse_waha_vcard_string(vcard_string, display_name)
            normalized["contact"] = parsed_contact
            logger.info(f"[WAHA Normalize] vCard parseado: {parsed_contact}")
        else:
            logger.warning(f"[WAHA Normalize] vCard não encontrado em contactMessage")

    elif internal_type == "sticker":
        normalized["sticker"] = {
            "stickerUrl": _waha_media_url(payload)
        }
        logger.info(f"[WAHA Normalize] Sticker detectado: {normalized['sticker']}")

    elif internal_type == "file":
        normalized["file"] = {
            "fileUrl": _waha_media_url(payload),
            "fileName": payload.get("filename", "") or _waha_media_info(payload).get("filename", "arquivo")
        }
        logger.info(f"[WAHA Normalize] Arquivo detectado: {normalized['file']}")

    logger.info(f"[WAHA Normalize] Payload normalizado: phone={phone}, reply_to={reply_to_chat_id}, type={internal_type}, fromMe={from_me}")

    return normalized


def _parse_waha_vcard_string(vcard_string: str, body_text: str) -> Dict[str, Any]:
    """
    Parse de string vCard WAHA (baseado em documentação oficial)

    Exemplo real:
    "BEGIN:VCARD\nVERSION:3.0\nFN:João Silva\nTEL;type=CELL;waid=5500000000009:+55 00 00000-0000\nEND:VCARD"
    """

    result = {
        "displayName": body_text or "Contato",
        "phones": []
    }

    try:
        # Extrair nome do FN (Full Name)
        fn_match = re.search(r'FN:([^\n]+)', vcard_string)
        if fn_match:
            result["displayName"] = fn_match.group(1).strip()

        # Extrair telefone do TEL
        # Formato: TEL;type=CELL;waid=5500000000009:+55 00 00000-0000
        tel_match = re.search(r'TEL[^:]*:([^\n]+)', vcard_string)
        if tel_match:
            phone_raw = tel_match.group(1).strip()
            # Limpar e formatar telefone, removendo o + no início
            phone_formatted = re.sub(r'[^\d]', '', phone_raw)
            if phone_formatted:
                result["phones"].append(phone_formatted)

        logger.info(f"[WAHA vCard Parse] Nome: {result['displayName']}, Telefone: {result['phones']}")

    except Exception as e:
        logger.warning(f"[WAHA vCard Parse] Erro: {e}")
        # Fallback: usar body como nome
        result["displayName"] = body_text or "Contato"

    return result


@app.task(bind=True, max_retries=None)
def process_incoming_waha_message(self, task_data: Dict[str, Any]):
    """
    Processa mensagem recebida do WAHA

    Implementa TODA a lógica de processamento (similar ao Z-API):
    1. Normalizar payload WAHA
    2. Identificar empresa
    3. Salvar mensagem no BD
    4. Criar/atualizar contacts e leads
    5. Transcrever mídia se necessário
    6. Publicar no Redis (WebSocket)
    7. Chamar LLM via burst_processor
    8. Atualizar auditoria

    Args:
        task_data: {
            "payload": {...},  # Payload original WAHA
            "session_name": "default",
            "audit_id": 123,
            "company_id": 68
        }
    """

    db: Session = SessionLocal()

    try:
        waha_payload = task_data.get("payload", {})
        session_name = task_data.get("session_name")
        audit_id = task_data.get("audit_id")
        company_id = task_data.get("company_id")
        requested_operational_epoch = task_data.get("operational_epoch")
        from backend.services.company_access_control import (
            CompanyOperationalLockBusyError,
            CompanyOperationallyBlockedError,
            try_capture_company_job_epoch,
            validate_company_job_epoch,
        )
        if not company_id:
            logger.warning("[WAHA Task] Empresa bloqueada; evento descartado company_id=%s", company_id)
            return {"status": "cancelled", "reason": "company_access_epoch_invalid"}

        try:
            captured_operational_epoch = try_capture_company_job_epoch(
                db,
                int(company_id),
                expected_epoch=requested_operational_epoch,
            )
        except CompanyOperationalLockBusyError as exc:
            db.rollback()
            logger.info(
                "[WAHA Task] Fence operacional ocupado; reagendando evento company_id=%s",
                company_id,
            )
            raise self.retry(
                exc=exc,
                countdown=WAHA_OPERATIONAL_LOCK_RETRY_SECONDS,
            )
        except CompanyOperationallyBlockedError:
            db.rollback()
            logger.warning(
                "[WAHA Task] Empresa bloqueada antes da admissão; evento cancelado company_id=%s",
                company_id,
            )
            return {"status": "cancelled", "reason": "company_access_epoch_invalid"}
        else:
            # Libera o fence antes do processamento potencialmente longo.
            db.rollback()

        if not validate_company_job_epoch(
            db,
            int(company_id),
            requested_operational_epoch,
        ):
            logger.warning("[WAHA Task] Empresa bloqueada; evento descartado company_id=%s", company_id)
            return {"status": "cancelled", "reason": "company_access_epoch_invalid"}

        operational_epoch = (
            captured_operational_epoch
            if requested_operational_epoch is None
            else int(requested_operational_epoch)
        )

        # Extrair campos do payload original para uso em toda a função
        payload_original = waha_payload.get("payload", {})
        sender_lid = payload_original.get("from", "")  # Ex: 000000000000002@lid
        debug_mode = task_data.get("debug_mode", False)

        logger.info(f"[WAHA Task] Processando mensagem WAHA para company_id={company_id}, session={session_name}")
        if debug_mode:
            logger.warning(f"[WAHA Task] 🔍 DEBUG MODE ATIVO - Processando TODOS os tipos de eventos")

        # 🔍 DEBUG COMPLETO DO PAYLOAD WAHA
        logger.info("[WAHA Task] Payload recebido: %s", _waha_payload_summary(waha_payload))

        # Analisar estrutura em detalhes
        event_type = waha_payload.get("event", "N/A")
        payload = waha_payload.get("payload", {})
        _data = payload.get("_data", {})

        logger.info(f"[WAHA Task] 🎯 Event type: {event_type}")
        logger.info(f"[WAHA Task] 📦 Payload keys: {list(payload.keys())}")

        # Verificar especificamente por dados de poll
        if "pollVote" in payload:
            logger.info("[WAHA Task] pollVote presente no payload")

        if "vote" in payload:
            logger.info("[WAHA Task] vote presente no payload")

        # Analisar _data profundamente
        if _data:
            logger.info(f"[WAHA Task] 🔍 _data existe com keys: {list(_data.keys())}")

            if "Message" in _data:
                message_obj = _data["Message"]
                logger.info(f"[WAHA Task] 🔍 Message keys: {list(message_obj.keys())}")
                logger.info(f"[WAHA Task] 🔍 Message keys: {list(message_obj.keys())}")

                # Procurar por qualquer coisa relacionada a poll
                for key, value in message_obj.items():
                    if "poll" in key.lower():
                        logger.info(f"[WAHA Task] 🎯 Campo com 'poll' encontrado: {key}")

        # Atualizar status auditoria
        if audit_id:
            update_audit_status(db, audit_id, "processing")

        if event_type == "message.ack":
            payload = waha_payload.get("payload", {})
            message_id = payload.get("id", "")
            ack_status = payload.get("ack")
            ack_name = payload.get("ackName")
            payload_data = payload.get("_data", {}) if isinstance(payload.get("_data"), dict) else {}
            from_me_original = bool(payload.get("fromMe") or payload_data.get("IsFromMe"))
            delivery_status = map_waha_ack_to_delivery_status(ack_status, ack_name)

            logger.info(
                "[WAHA Task] ACK recebido: message_id=%s ack=%s ackName=%s fromMe=%s status=%s",
                message_id,
                ack_status,
                ack_name,
                from_me_original,
                delivery_status,
            )

            if message_id and from_me_original and delivery_status:
                updated = _update_waha_ack_delivery_status(
                    db=db,
                    company_id=company_id,
                    message_id=message_id,
                    delivery_status=delivery_status,
                    ack_status=ack_status,
                    ack_name=ack_name,
                )
                if audit_id:
                    update_audit_status(
                        db,
                        audit_id,
                        "completed" if updated else "ignored",
                        error="Message.ack atualizado" if updated else "ACK sem mensagem local",
                    )
            else:
                if audit_id:
                    update_audit_status(db, audit_id, "ignored", error="ACK incompleto ou de mensagem recebida")
            return

        if event_type == "message.reaction":
            payload = waha_payload.get("payload", {})
            reaction_data = payload.get("reaction", {}) if isinstance(payload.get("reaction"), dict) else {}
            target_message_id = reaction_data.get("messageId")
            reaction_text = reaction_data.get("text", "")
            actor_id = payload.get("participant") or payload.get("from")
            from_me_reaction = bool(payload.get("fromMe"))

            logger.info(
                "[WAHA Task] Reacao recebida: target_message_id=%s reaction_present=%s fromMe=%s",
                target_message_id,
                bool(reaction_text),
                from_me_reaction,
            )

            updated = None
            if target_message_id:
                updated = update_message_reactions(
                    db=db,
                    company_id=company_id,
                    provider_message_id=target_message_id,
                    reaction=reaction_text,
                    actor_id=actor_id,
                    from_me=from_me_reaction,
                    reaction_message_id=payload.get("id"),
                    timestamp=payload.get("timestamp"),
                    publish=True,
                )

            if audit_id:
                update_audit_status(
                    db,
                    audit_id,
                    "completed" if updated else "ignored",
                    error="Message.reaction atualizado" if updated else "Reaction sem mensagem local",
                )
            return

        # Normalizar payload WAHA → formato interno
        normalized_data = normalize_waha_payload(waha_payload)
        event_type = waha_payload.get("event", "")

        # 🔕 IGNORAR MENSAGENS DE SISTEMA (e2e, protocol, etc) OU SEM TELEFONE VÁLIDO
        if normalized_data.get("type") == "ignore":
            logger.info(f"[WAHA Task] 🔕 MENSAGEM IGNORADA: Tipo '{waha_payload.get('payload', {}).get('type')}' mapeado para 'ignore'")
            if audit_id:
                update_audit_status(db, audit_id, "ignored")
            return {"status": "ignored", "reason": "message_type_ignored"}

        if not normalized_data.get("phone"):
            logger.warning(f"[WAHA Task] 🔕 MENSAGEM IGNORADA: Telefone não pôde ser extraído (provável ID interno/LID)")
            if audit_id:
                update_audit_status(db, audit_id, "ignored", error="Telefone inválido/não extraído")
            return {"status": "ignored", "reason": "invalid_phone"}

        logger.info("[WAHA Task] Payload normalizado: %s", _normalized_summary(normalized_data))

        ignored_conversation = None
        if event_type in {"message", "message.any"} and normalized_data.get("broadcast"):
            ignored_conversation = (
                "status_broadcast",
                "Mensagem de status/broadcast",
            )
        elif event_type in {"message", "message.any"} and normalized_data.get("isNewsletter"):
            ignored_conversation = (
                "newsletter_message",
                "Mensagem de newsletter",
            )
        elif event_type in {"message", "message.any"} and normalized_data.get("isGroup"):
            ignored_conversation = (
                "group_message",
                "Mensagem de grupo",
            )

        if ignored_conversation:
            reason, audit_error = ignored_conversation
            logger.info(
                "[WAHA Task] Conversa ignorada antes do download: reason=%s message_id=%s",
                reason,
                normalized_data.get("messageId"),
            )
            if audit_id:
                update_audit_status(db, audit_id, "ignored", error=audit_error)
            return {"status": "ignored", "reason": reason}

        # A partir daqui, reutilizar a lógica do process_incoming_zapi_message
        # Importar função compartilhada
        from backend.worker.process_message import (
            store_ad_campaign_media_once,
            publish_to_redis,
        )

        # Extrair dados básicos do payload normalizado
        phone = normalized_data.get("phone", "desconhecido")
        chat_name = normalized_data.get("chatName", "desconhecido")
        sender_name = normalized_data.get("senderName", chat_name)
        from_me = normalized_data.get("fromMe", False)
        message_id = normalized_data.get("messageId", f"waha_{uuid.uuid4()}")

        # Processar eventos especiais - especialmente poll.vote e message.ack
        # 🆕 CAPTURAR CONTEÚDO NO MESSAGE.ANY (antes do message.ack)
        # 🔥 CORREÇÃO CRÍTICA: message.any deve processar APENAS mensagens recebidas (fromMe=false)
        # Mensagens fromMe=true serão processadas no message.ack para evitar duplicação
        if event_type == "message.any":
            logger.info(f"[WAHA Task] 📥 Capturando conteúdo do message.any para cache")

            try:
                payload = waha_payload.get("payload", {})
                message_id = payload.get("id", "")
                from_me = payload.get("fromMe", False)

                message_source = _waha_message_source(payload)

                if from_me and message_source == "api":
                    logger.info(f"[WAHA Task] ✅ PROCESSANDO mensagem fromMe=true da API (Agents SDK): {message_id}")
                elif from_me:
                    logger.info(f"[WAHA Task] ✅ PROCESSANDO mensagem fromMe=true do app/celular: {message_id}")

                # Processar TODAS mensagens:
                # 1. fromMe=false (mensagens do cliente)
                # 2. fromMe=true (mensagens do Agent SDK OU celular)
                should_process = True

                if should_process and message_id:
                    # 🎯 PRIORIDADE 1: Usar media.url do WAHA (já baixado e disponível)
                    media_info = payload.get("media", {})
                    if media_info is None:
                        media_info = {}
                    wa_media_url = media_info.get("url", "")
                    wa_mimetype = media_info.get("mimetype", "")
                    wa_filename = media_info.get("filename", "")
                    wa_body = payload.get("body", "")  # caption/legenda

                    logger.info(
                        "[WAHA Task] Media WAHA encontrado: has_url=%s mimetype=%s filename_present=%s body_len=%s",
                        bool(wa_media_url),
                        wa_mimetype or None,
                        bool(wa_filename),
                        _len_or_zero(wa_body),
                    )

                    # Fallback para dados internos se media.url não estiver disponível
                    _data_raw = payload.get("_data", {})
                    _data_safe = _data_raw if _data_raw is not None else {}
                    message_data = _data_safe.get("Message", {}) if isinstance(_data_safe, dict) else {}
                    conversation_content = _waha_text_body(payload)

                    # Detectar tipo de mídia e extrair dados correspondentes
                    message_type = "text"
                    media_url = ""
                    caption = ""

                    if wa_media_url:
                        # WAHA já fez download e disponibilizou a mídia
                        if wa_mimetype:
                            if wa_mimetype.startswith("image/"):
                                message_type = "image"
                            elif wa_mimetype.startswith("video/"):
                                message_type = "video"
                            elif wa_mimetype.startswith("audio/"):
                                message_type = "audio"
                            else:
                                message_type = "file"  # fallback para outros tipos

                        # Baixar mídia para evitar perda após expiração do storage local da WAHA.
                        local_media_url = download_waha_media(wa_media_url, company_id, message_id)

                        # Usar proxy local se download funcionou, senão URL original da WAHA.
                        media_url = local_media_url if local_media_url else wa_media_url
                        caption = wa_body or wa_filename or ""

                        if local_media_url:
                            logger.info(
                                "[WAHA Task] Mídia WAHA baixada: tipo=%s local_saved=%s original_url_present=%s",
                                message_type,
                                bool(local_media_url),
                                bool(wa_media_url),
                            )
                        else:
                            logger.warning(f"[WAHA Task] Falha no download, usando URL original: tipo={message_type}")
                            logger.info(
                                "[WAHA Task] Mídia WAHA com URL original: tipo=%s caption_len=%s",
                                message_type,
                                _len_or_zero(caption),
                            )

                    else:
                        # Fallback: extrair dos dados internos (URL criptografada)
                        logger.warning(f"[WAHA Task] ⚠️ media.url não encontrado, usando dados internos (URL criptografada)")

                        if "imageMessage" in message_data:
                            message_type = "image"
                            image_data = message_data["imageMessage"]
                            media_url = image_data.get("URL", "")
                            caption = image_data.get("caption", "")
                            logger.info(
                                "[WAHA Task] Imagem detectada no message.any: has_url=%s caption_len=%s",
                                bool(media_url),
                                _len_or_zero(caption),
                            )

                        elif "videoMessage" in message_data:
                            message_type = "video"
                            video_data = message_data["videoMessage"]
                            # Para vídeos do message.any, também precisaria fazer download
                            # pois são URLs criptografadas do WhatsApp
                            encrypted_url = video_data.get("URL", "")
                            caption = video_data.get("caption", "")

                            # Fazer download apenas para vídeos criptografados (message.any)
                            local_video_path = download_waha_media(encrypted_url, company_id, message_id)
                            media_url = local_video_path if local_video_path else encrypted_url

                            logger.info(
                                "[WAHA Task] Vídeo criptografado detectado: local_saved=%s original_url_present=%s caption_len=%s",
                                bool(local_video_path),
                                bool(encrypted_url),
                                _len_or_zero(caption),
                            )

                        elif "audioMessage" in message_data:
                            message_type = "audio"
                            audio_data = message_data["audioMessage"]
                            media_url = audio_data.get("URL", "")
                            logger.info("[WAHA Task] Áudio detectado no message.any: has_url=%s", bool(media_url))

                        elif conversation_content:
                            message_type = "text"
                            normalized_data["text"] = {"message": conversation_content}
                            logger.info(
                                "[WAHA Task] Texto detectado no message.any: chars=%s",
                                _len_or_zero(conversation_content),
                            )

                    if media_url:
                        if message_type == "image":
                            normalized_data["image"] = {"imageUrl": media_url, "caption": caption, "mimetype": wa_mimetype}
                        elif message_type == "audio":
                            normalized_data["audio"] = {"audioUrl": media_url, "mimetype": wa_mimetype}
                        elif message_type == "video":
                            normalized_data["video"] = {"videoUrl": media_url, "caption": caption, "mimetype": wa_mimetype}
                        elif message_type == "file":
                            normalized_data["file"] = {"fileUrl": media_url, "fileName": wa_filename or os.path.basename(media_url)}

                    # Cache removido - dados serão salvos diretamente no BD via message.ack
                    logger.info(f"[WAHA Task] ✅ Dados do message.any processados: tipo={message_type}")

            except Exception as e:
                logger.error(f"[WAHA Task] ❌ Erro ao processar message.any: {e}", exc_info=True)

        # PROCESSAR EVENTO MESSAGE.ACK (MENSAGENS ENVIADAS PELA EMPRESA VIA CELULAR)
        if event_type == "message.ack":
            logger.info(f"[WAHA Task] 📤 PROCESSANDO EVENTO MESSAGE.ACK - Mensagem enviada pela empresa")

            try:
                # Extrair dados do ack
                payload = waha_payload.get("payload", {})

                # ID da mensagem original
                message_id = payload.get("id", "")

                # Status do ack (1, 2, 3, 4 - pendente, enviada, recebida, lida)
                # No WAHA, "ack" é um inteiro direto, não um objeto
                ack_status = payload.get("ack", 0)

                # 🔥 CORREÇÃO CRÍTICA: Determinar corretamente quem enviou a mensagem original
                # Usar _data.IsFromMe em vez de payload.fromMe
                _data = payload.get("_data", {})
                is_from_me_original = _data.get("IsFromMe", False)

                logger.info(f"[WAHA Task] 🔍 ACK - _data.IsFromMe: {is_from_me_original}, payload.fromMe: {payload.get('fromMe', False)}")

                # Telefone do contato (para quem a mensagem foi enviada)
                # Em message.ack do WAHA, "to" pode ser null, então usamos o "from" do contato original
                to_phone_raw = payload.get("to") or payload.get("from", "")
                to_phone = (to_phone_raw or "").replace("@c.us", "").replace("@s.whatsapp.net", "").replace("@g.us", "").replace("@lid", "")

                # Timestamp
                timestamp = payload.get("timestamp", int(dt.datetime.now().timestamp()))

                # 🔥 CORREÇÃO: Usar _data.IsFromMe para determinar fromMe correto
                from_me = is_from_me_original

                logger.info(f"[WAHA Task] 📊 Dados do ACK extraídos:")
                logger.info(f"  - Message ID: {message_id}")
                logger.info(f"  - Para: {to_phone}")
                logger.info(f"  - Status: {ack_status}")
                logger.info(f"  - fromMe: {from_me}")

                if message_id and to_phone and ack_status >= 2 and from_me:  # status 2+ E fromMe=true = mensagem enviada pela empresa
                    # Obter client_id associado à empresa (necessário para inserir mensagem)
                    row_owner = db.execute(text("""
                        SELECT client_id
                        FROM client_companies
                        WHERE company_id = :cid
                        ORDER BY id
                        LIMIT 1
                    """), {"cid": company_id}).fetchone()

                    if not row_owner:
                        logger.error(f"[WAHA Task] Nenhum client associado à empresa {company_id} para processar ACK")
                        if audit_id:
                            update_audit_status(db, audit_id, "failed", error="Nenhum client associado")
                        return

                    client_id_db = row_owner.client_id

                    # 🥈 PRIORIDADE 2: Tentar extrair do conversation (pode não vir no ack)
                    message_data = payload.get("_data", {}).get("Message", {})
                    conversation_content = message_data.get("conversation", "")

                    logger.info(f"[WAHA Task] 📄 Conversation: '{conversation_content}'")

                    # Buscar se a mensagem já existe no banco (pode ter sido enviada via frontend)
                    existing_message = db.execute(text("""
                        SELECT id, content, message_type
                        FROM messages
                        WHERE company_id = :company_id
                        AND zapi_message_id = :message_id
                        LIMIT 1
                    """), {
                        "company_id": company_id,
                        "message_id": message_id
                    }).fetchone()

                    message_content = ""
                    message_type = "text"

                    if existing_message:
                        # Mensagem já existe (enviada via frontend) - usar dados do BD
                        message_content = existing_message.content or ""
                        message_type = existing_message.message_type or "text"
                        logger.info(f"[WAHA Task] ✅ Mensagem {message_id} já existe no banco (enviada via frontend)")
                    else:
                        # Mensagem NÃO existe (enviada diretamente pelo celular) - criar nova entrada
                        logger.info(f"[WAHA Task] 📝 Mensagem {message_id} não existe no banco (enviada pelo celular)")

                        # 🥇 PRIORIDADE 1: Usar conteúdo do conversation (se disponível no ack)
                        if conversation_content:
                            message_content = conversation_content
                            message_type = "text"
                            logger.info(
                                "[WAHA Task] Usando conteúdo do conversation: chars=%s",
                                _len_or_zero(message_content),
                            )

                        else:
                            # Fallback: Buscar último conteúdo enviado para este contato (para inferir o que foi enviado)
                            last_sent = db.execute(text("""
                                SELECT content, message_type
                                FROM messages
                                WHERE company_id = :company_id
                                AND contact_phone = :to_phone
                                AND from_me = true
                                ORDER BY timestamp DESC
                                LIMIT 1
                            """), {
                                "company_id": company_id,
                                "to_phone": to_phone
                            }).fetchone()

                            if last_sent:
                                # Tentar usar o último conteúdo como referência
                                try:
                                    if isinstance(last_sent.content, str):
                                        message_content = json.loads(last_sent.content) if last_sent.content.startswith('{') else last_sent.content
                                    else:
                                        message_content = last_sent.content
                                    message_type = last_sent.message_type or "text"
                                except:
                                    message_content = last_sent.content or "Mensagem enviada pelo celular"
                                    message_type = last_sent.message_type or "text"
                            else:
                                # Último recurso - conteúdo genérico
                                message_content = "Mensagem enviada pelo celular"
                                message_type = "text"

                        # Inserir nova mensagem no banco
                        try:
                            db.execute(text("""
                                INSERT INTO messages
                                       (client_id, company_id, contact_phone, message_type, content,
                                        sender_phone, sender_name, from_me, zapi_message_id, timestamp)
                                VALUES (:client_id, :company_id, :contact_phone, :message_type, :content,
                                        :sender_phone, :sender_name, :from_me, :zapi_message_id, :timestamp)
                            """), {
                                "client_id": client_id_db,
                                "company_id": company_id,
                                "contact_phone": to_phone,
                                "message_type": message_type,
                                "content": message_content,
                                "sender_phone": "me",
                                "sender_name": "Você",
                                "from_me": True,
                                "zapi_message_id": message_id,
                                "timestamp": dt.datetime.fromtimestamp(timestamp)
                            })

                            db.commit()
                            logger.info(f"[WAHA Task] ✅ Mensagem de ACK criada no banco: message_id={message_id}")

                        except Exception as e:
                            # Race condition ou duplicata
                            if "duplicate key" in str(e).lower() or "unique constraint" in str(e).lower():
                                logger.warning(f"[WAHA Task] Mensagem ACK já existe (race condition): {message_id}")
                                db.rollback()
                            else:
                                raise

                    # 🔄 PUBLICAR NO REDIS PARA ATUALIZAR FRONTEND (APENAS UMA VEZ!)
                    # Preparar payload para frontend baseado no tipo de mensagem
                    frontend_payload = {
                        "type": message_type,
                        "content": message_content,
                        "phone": to_phone,
                        "senderName": "Você",
                        "photo": "",
                        "fromMe": True,
                        "messageId": message_id,
                        "momment": str(timestamp),
                        "company_id": company_id,
                        "fromApi": False,
                        "provider": "waha"
                    }

                    # Adicionar campos específicos por tipo com dados completos do cache
                    if message_type == "text":
                        if isinstance(message_content, dict):
                            frontend_payload["text"] = message_content
                        else:
                            frontend_payload["text"] = {"message": str(message_content)}
                    elif message_type == "image":
                        # Usar dados completos do cache se disponíveis
                        if cached_content:
                            frontend_payload["image"] = {
                                "imageUrl": cached_content.get("media_url", str(message_content)),
                                "caption": cached_content.get("caption", "")
                            }
                        else:
                            frontend_payload["image"] = {"imageUrl": str(message_content), "caption": ""}
                    elif message_type == "audio":
                        frontend_payload["audio"] = {"audioUrl": str(message_content)}
                    elif message_type == "video":
                        # Usar dados completos do cache se disponíveis
                        if cached_content:
                            frontend_payload["video"] = {
                                "videoUrl": cached_content.get("media_url", str(message_content)),
                                "caption": cached_content.get("caption", "")
                            }
                        else:
                            frontend_payload["video"] = {"videoUrl": str(message_content), "caption": ""}

                    # Publicar no Redis APENAS se mensagem NÃO existe no banco (enviada pelo celular)
                    # Se já existe, foi enviada via frontend e não precisa ser notificada novamente
                    if not existing_message:
                        publish_to_redis(company_id, frontend_payload)
                        logger.info(f"[WAHA Task] 🔄 Mensagem do celular publicada no Redis (não existe no banco)")
                    else:
                        logger.info(f"[WAHA Task] ℹ️ Mensagem já existe no banco (enviada via frontend) - não publicando no Redis")

                    if audit_id:
                        update_audit_status(db, audit_id, "completed", error="Message.ack processado")

                else:
                    if not from_me:
                        logger.info(f"[WAHA Task] ℹ️ ACK de mensagem recebida (fromMe=false) - ignorando, pois mensagem já foi processada no evento 'message'")
                        if audit_id:
                            update_audit_status(db, audit_id, "ignored", error="ACK de mensagem recebida")
                    else:
                        logger.warning(f"[WAHA Task] ⚠️ Dados insuficientes no ACK ou status < 2")
                        if audit_id:
                            update_audit_status(db, audit_id, "ignored", error="ACK incompleto")

            except Exception as e:
                logger.error(f"[WAHA Task] ❌ Erro ao processar message.ack: {str(e)}", exc_info=True)
                if audit_id:
                    update_audit_status(db, audit_id, "failed", error=str(e))

            # 🔥 CORREÇÃO: Retornar AQUI para evitar duplicação no final do processamento
            return

        # PROCESSAR EVENTO POLL.VOTE
        if event_type == "poll.vote":
            logger.info(f"[WAHA Task] 🎯 PROCESSANDO EVENTO POLL.VOTE")

            try:
                # Extrair dados do voto
                payload = waha_payload.get("payload", {})
                vote_data = payload.get("vote", {})
                poll_data = payload.get("poll", {})

                # Telefone de quem votou
                voter_phone = vote_data.get("from", "").replace("@c.us", "").replace("@s.whatsapp.net", "")

                # Opções selecionadas
                selected_options = vote_data.get("selectedOptions", [])

                # ID da enquete original (pollCreationMessageKey)
                poll_message_data = payload.get("_data", {}).get("Message", {}).get("pollUpdateMessage", {}).get("pollCreationMessageKey", {})
                poll_message_id = poll_message_data.get("ID", "")

                logger.info(f"[WAHA Task] 📊 Dados do voto extraídos:")
                logger.info(f"  - Telefone: {voter_phone}")
                logger.info(f"  - Opções: {len(selected_options) if selected_options else 0}")
                logger.info(f"  - Poll ID: {poll_message_id}")

                if voter_phone and selected_options and poll_message_id:
                    # Converter para formato esperado pelo process_nps_response
                    nps_payload = {
                        "phone": voter_phone,
                        "messageId": vote_data.get("id", ""),
                        "pollVote": {
                            "pollMessageId": poll_message_id,
                            "options": [{"name": opt} for opt in selected_options]
                        }
                    }

                    logger.info(f"[WAHA Task] 📤 Enviando para processar resposta NPS")

                    # Processar resposta NPS
                    from backend.worker.process_message import process_nps_response
                    process_nps_response(db, company_id, nps_payload)

                    logger.info(f"[WAHA Task] ✅ Voto de enquete processado com sucesso!")

                    if audit_id:
                        update_audit_status(db, audit_id, "completed", error="Poll vote processado")
                else:
                    logger.error(f"[WAHA Task] ❌ Dados incompletos do voto")
                    if audit_id:
                        update_audit_status(db, audit_id, "failed", error="Dados incompletos do voto")

            except Exception as e:
                logger.error(f"[WAHA Task] ❌ Erro ao processar poll.vote: {str(e)}", exc_info=True)
                if audit_id:
                    update_audit_status(db, audit_id, "failed", error=str(e))

            return  # Retornar após processar poll.vote

        # Para outros eventos especiais em debug mode (excluir message.any que é mensagem recebida)
        if debug_mode and event_type not in ["message", "message.any"]:
            logger.warning(f"[WAHA Task] 🚨 EVENTO ESPECIAL EM DEBUG: {event_type}")
            logger.warning("[WAHA Task] Payload do evento especial: %s", _waha_payload_summary(waha_payload))

            if audit_id:
                update_audit_status(db, audit_id, "debug_logged", error=f"Evento especial: {event_type}")
            return

        # Obter client_id associado à empresa
        row_owner = db.execute(text("""
            SELECT client_id
            FROM client_companies
            WHERE company_id = :cid
            ORDER BY id
            LIMIT 1
        """), {"cid": company_id}).fetchone()

        if not row_owner:
            logger.warning(f"[WAHA Task] Nenhum client associado à empresa {company_id}")
            if audit_id:
                update_audit_status(db, audit_id, "failed", error="Nenhum client associado")
            return

        client_id_db = row_owner.client_id

        # Detectar tipo de mensagem e extrair conteúdo
        msg_type = "unknown"
        content = ""
        reply_to_metadata = normalized_data.get("replyTo")

        if "text" in normalized_data:
            msg_type = "text"
            content = normalized_data["text"].get("message", "")
            logger.info("[WAHA Task] Mensagem de texto: chars=%s", _len_or_zero(content))
        elif "image" in normalized_data:
            msg_type = "image"
            # Preferir a URL local/proxy criada durante o processamento WAHA.
            content = normalized_data["image"].get("imageUrl", "")
            logger.info("[WAHA Task] Imagem URL WAHA: present=%s", bool(content))

            # Fallback para compatibilidade
            if not content:
                content = payload.get("media", {}).get("url", "")
                logger.info("[WAHA Task] Imagem fallback: present=%s", bool(content))
        elif "audio" in normalized_data:
            msg_type = "audio"
            audio_url = normalized_data["audio"].get("audioUrl", "")
            mimetype = normalized_data["audio"].get("mimetype", "audio/ogg; codecs=opus")
            content = _materialize_audio_content(audio_url, mimetype)
        elif "video" in normalized_data:
            msg_type = "video"
            # Preferir a URL local/proxy criada durante o processamento WAHA.
            content = normalized_data["video"].get("videoUrl", "")
            if not content:
                content = normalized_data.get("payload", {}).get("media", {}).get("url", "")
            logger.info("[WAHA Task] Vídeo URL extraída: present=%s", bool(content))
        elif "contact" in normalized_data:
            msg_type = "contact"
            contact_info = normalized_data["contact"]
            display_name = contact_info.get("displayName", "Sem nome")
            content = f"{display_name}"
            logger.info("[WAHA Task] Contato recebido: name_present=%s", bool(display_name))
        elif "sticker" in normalized_data:
            msg_type = "sticker"
            content = normalized_data["sticker"].get("stickerUrl", "")
            logger.info("[WAHA Task] Sticker recebido: url_present=%s", bool(content))
        elif "file" in normalized_data:
            msg_type = "file"
            file_url = normalized_data["file"].get("fileUrl", "")
            file_name = normalized_data["file"].get("fileName", "")
            content = file_url  # Salvar URL no content
            logger.info(
                "[WAHA Task] Arquivo recebido: url_present=%s file_name_present=%s",
                bool(content),
                bool(file_name),
            )

        # Salvar mensagem no BD (se não for fromMe ou não for fromApi)
        sender_phone_db = "me" if from_me else phone
        sender_name_db = sender_name if sender_name else None
        contact_photo_for_payload = ""

        # WAHA informa a origem em source=api|app para mensagens fromMe.
        # Apenas source=api representa envio pela plataforma/API. Mensagens
        # source=app vieram do WhatsApp Web/celular e precisam aparecer como
        # mensagens próprias externas, sem serem deduplicadas como eco do frontend.
        message_source = _waha_message_source(payload) or str(normalized_data.get("source") or "").strip().lower()
        from_api = (message_source == "api") or bool(normalized_data.get("fromApi", False))

        # Flags usadas na decisão de publicação no Redis.
        # Precisam existir em todos os caminhos (from_api=True/False).
        was_inserted = False
        was_updated = False

        if from_api:
            logger.info(f"[WAHA Task] 🎯 Mensagem marcada como fromApi=true (source={message_source})")
        elif from_me:
            logger.info(f"[WAHA Task] 🎯 Mensagem própria externa marcada como fromApi=false (source={message_source or 'unknown'})")

        # Verificar duplicação e necessidade de atualização (enrichment)
        # IMPORTANTE: isso precisa rodar para mensagens recebidas também (from_api=False),
        # caso contrário elas não são persistidas na tabela messages.
        zapi_message_id = message_id  # Usar message_id do WAHA
        existing = db.execute(text("""
                SELECT id, message_type, content, sender_name
                FROM messages
                WHERE zapi_message_id = :zapi_message_id
                LIMIT 1
        """), {"zapi_message_id": zapi_message_id}).fetchone()

        if not existing:
            try:
                    # ---------------------------------------------------------
                    # FIX: Converter URL interna do WAHA para Rota Proxy (ANTES DE SALVAR)
                    # ---------------------------------------------------------
                    if content and _extract_waha_file_path(content):
                        logger.info("[FIX] URL WAHA detectada; content do banco mantido para compatibilidade")
                    # ---------------------------------------------------------

                    # 🔥 GUARD CLAUSE: Impedir salvamento de mensagens unknown ou vazias
                    if msg_type == 'unknown' or (not content and msg_type != 'contact'):
                        logger.warning(f"[WAHA Task] 🛑 BLOQUEANDO salvamento de mensagem inválida: type={msg_type}, content_len={len(str(content)) if content else 0}")
                        if audit_id:
                            update_audit_status(db, audit_id, "ignored", error="Tipo desconhecido ou contudo vazio")
                        return

                    db.execute(text("""
                        INSERT INTO messages
                               (client_id, company_id, contact_phone, message_type, content,
                                sender_phone, sender_name, from_me, zapi_message_id, delivery_status, reply_to)
                        VALUES (:client_id, :company_id, :contact_phone, :message_type, :content,
                                :sender_phone, :sender_name, :from_me, :zapi_message_id, :delivery_status, CAST(:reply_to AS JSONB))
                    """), {
                        "client_id": client_id_db,
                        "company_id": company_id,
                        "contact_phone": phone,
                        "message_type": msg_type,
                        "content": content,
                        "sender_phone": sender_phone_db,
                        "sender_name": sender_name_db,
                        "from_me": from_me,
                        "zapi_message_id": zapi_message_id,
                        "delivery_status": "sent" if from_me else None,
                        "reply_to": json.dumps(reply_to_metadata) if reply_to_metadata else None,
                    })

                    # Atualizar last_message_at
                    db.execute(text("""
                        UPDATE contacts
                        SET last_message_at = NOW()
                        WHERE client_id = :client_id AND phone = :contact_phone
                    """), {
                        "client_id": client_id_db,
                        "contact_phone": phone
                    })

                    db.commit()
                    was_inserted = True
                    logger.info(f"[WAHA Task] Mensagem salva: message_id={zapi_message_id}")

                    # 🆕 RASTREAR RESPOSTA DE CAMPANHA (se não for from_me)
                    if not from_me:
                        try:
                            from backend.utils.campaign_reply_tracker import check_and_mark_campaign_reply
                            check_and_mark_campaign_reply(db, company_id, phone)
                        except Exception as e:
                            logger.error(f"[WAHA Task] Erro ao rastrear resposta de campanha: {e}")
            except Exception as e:
                # Race condition: outro worker salvou primeiro
                if "duplicate key" in str(e).lower() or "unique constraint" in str(e).lower():
                    logger.warning(f"[WAHA Task] Mensagem já foi salva por outro worker (race condition): {zapi_message_id}")
                    db.rollback()
                    # Re-lerificar para possível update
                    existing = db.execute(text("""
                            SELECT id, message_type, content, sender_name
                            FROM messages
                            WHERE zapi_message_id = :zapi_message_id
                            LIMIT 1
                    """), {"zapi_message_id": zapi_message_id}).fetchone()
                else:
                    # Outro erro - propagar
                    raise

        # Se a mensagem já existe (ou foi encontrada após o rollback da race condition)
        # Verificar se é caso de Enriquecimento (ex: msg pobre do ACK sendo substituída por rica do ANY)
        if existing:
            is_enrichment = False

            # Caso clássico: Mensagem salva como "text" (pelo ACK) mas agora chega como "video/image/audio/file" (pelo ANY)
            # Verifica se o tipo mudou de text para algo mais específico
            if existing.message_type == 'text' and msg_type in ['video', 'image', 'audio', 'file']:
                 is_enrichment = True

            # Caso de texto placeholder ("Mensagem enviada pelo celular") sendo substituído por conteúdo real
            elif existing.message_type == 'text' and msg_type == 'text':
                 if existing.content == "Mensagem enviada pelo celular" and content != "Mensagem enviada pelo celular":
                     is_enrichment = True

            if is_enrichment:
                logger.info(f"[WAHA Task] 💎 ENRIQUECIMENTO DETECTADO: message_id={zapi_message_id} ({existing.message_type} -> {msg_type})")
                try:
                    db.execute(text("""
                            UPDATE messages
                            SET message_type = :message_type,
                                content = :content,
                                sender_name = COALESCE(:sender_name, sender_name)
                            WHERE id = :id
                    """), {
                         "message_type": msg_type,
                         "content": content,
                         "sender_name": sender_name_db,
                         "id": existing.id
                    })
                    db.commit()
                    was_updated = True
                    logger.info(f"[WAHA Task] ✅ Mensagem atualizada com conteúdo rico.")
                except Exception as exc:
                    logger.error(f"[WAHA Task] ❌ Erro ao atualizar enriquecimento: {exc}")
                    db.rollback()
            else:
                logger.info(f"[WAHA Task] ℹ️ Mensagem já existe e não requer atualização: {zapi_message_id}")

        # Salvar no arquivo de memória (se não for from_me)
        if not from_me:
            append_message_to_chat_file(company_id, phone, from_me=False, content=content)

        # 🆕 PROCESSAR VCARDS COMO INDICAÇÕES (INTEGRAÇÃO COM AGENTS SDK COMO Z-API)
        if msg_type == "contact" and not from_me and normalized_data.get("contact"):
            logger.info(f"[WAHA Task] 📇 Processando vCard WAHA como indicação")

            try:
                contact_data = normalized_data["contact"]
                display_name = contact_data.get("displayName", "")
                phones = contact_data.get("phones", [])

                if display_name and phones:
                    # Usar lógica idêntica à Z-API (referência: linhas 647-761 do process_message.py)
                    referral_phone = phones[0]  # Primeiro telefone

                    # Verificar campanha ativa
                    from backend.models import ReferralCampaign
                    campaign = db.query(ReferralCampaign).filter(
                        ReferralCampaign.company_id == company_id,
                        ReferralCampaign.active == True
                    ).first()

                    if campaign:
                        logger.info(f"[WAHA Task] ✅ Campanha ativa. Processando indicação: {display_name} - {referral_phone}")

                        # Criar lead automaticamente usando Agents SDK ReferralService
                        from backend.models import Lead, Contact as ContactModel
                        from datetime import datetime

                        # Verificar se já existe lead com esse telefone
                        existing_lead = db.query(Lead).filter(
                            Lead.phone == referral_phone,
                            Lead.company_id == company_id
                        ).first()

                        if not existing_lead:
                            try:
                                # Criar novo lead
                                new_lead = Lead(
                                    client_id=str(client_id_db),
                                    company_id=company_id,
                                    name=display_name,
                                    phone=referral_phone,
                                    source_id="Indicação",  # CORRIGIDO: "Indicação" em vez de "referral"
                                    created_at=dt.datetime.utcnow(),
                                    data_entrada=dt.datetime.utcnow()
                                )
                                db.add(new_lead)
                                db.flush()

                                # Atribuir lead ao pipeline padrão da empresa
                                try:
                                    PipelineService.assign_lead_to_first_stage(new_lead, db)
                                    logger.info(f"[WAHA Task] ✅ Lead atribuído ao pipeline com sucesso")
                                except Exception as pipeline_error:
                                    logger.error(f"[WAHA Task] ❌ Erro ao atribuir lead ao pipeline: {pipeline_error}")
                                    # Não falhar a operação principal se o pipeline falhar

                                logger.info(f"[WAHA Task] ✅ Lead criado para indicação: {display_name} ({referral_phone})")
                            except Exception as db_error:
                                # Tratar race condition - outro worker pode ter criado o lead
                                if "duplicate key" in str(db_error).lower() or "unique constraint" in str(db_error).lower():
                                    logger.warning(f"[WAHA Task] ⚠️ Lead já existe para {referral_phone} (race condition) - buscando lead existente...")
                                    db.rollback()  # Recuperar sessão após erro

                                    # Buscar lead existente após rollback
                                    existing_lead = db.query(Lead).filter(
                                        Lead.phone == referral_phone,
                                        Lead.company_id == company_id
                                    ).first()

                                    if existing_lead:
                                        logger.info(f"[WAHA Task] ✅ Lead existente recuperado: {existing_lead.name} ({existing_lead.phone})")
                                else:
                                    # Erro inesperado - propagar
                                    raise db_error

                            # Criar/atualizar contato
                            try:
                                contact = db.query(ContactModel).filter(
                                    ContactModel.phone == referral_phone,
                                    ContactModel.company_id == company_id
                                ).first()

                                if not contact:
                                    contact = ContactModel(
                                        client_id=client_id_db,
                                        company_id=company_id,
                                        phone=referral_phone,
                                        name=display_name
                                    )
                                    db.add(contact)
                                    db.flush()
                                    logger.info(f"[WAHA Task] ✅ Contato criado para indicação: {display_name}")
                                else:
                                    logger.info(f"[WAHA Task] ✅ Contato já existe: {display_name}")

                                db.commit()
                            except Exception as contact_error:
                                # Tratar race condition na criação de contato
                                if "duplicate key" in str(contact_error).lower() or "unique constraint" in str(contact_error).lower():
                                    logger.warning(f"[WAHA Task] ⚠️ Contato já existe para {referral_phone} (race condition)")
                                    db.rollback()
                                    # Buscar contato existente e continuar
                                    contact = db.query(ContactModel).filter(
                                        ContactModel.phone == referral_phone,
                                        ContactModel.company_id == company_id
                                    ).first()
                                    if contact:
                                        logger.info(f"[WAHA Task] ✅ Contato existente recuperado: {contact.name}")
                                else:
                                    # Outro erro - propagar
                                    raise contact_error

                            # 🤖 INTEGRAÇÃO COM AGENTS SDK - AGENDAR MENSAGEM AUTOMÁTICA
                            try:
                                from backend.agents_sdk.services.referral_service import ReferralService

                                # Usar o serviço existente que já tem toda a lógica
                                referral_service = ReferralService(db)

                                # Buscar nome do indicador (quem está indicando)
                                referrer_contact = db.query(ContactModel).filter(
                                    ContactModel.phone == phone,
                                    ContactModel.company_id == company_id
                                ).first()
                                referrer_name = referrer_contact.name if referrer_contact else "Um amigo"

                                # Usar o método existente que já gera mensagem com IA e agenda
                                success = referral_service._schedule_referee_welcome(
                                    company_id=company_id,
                                    referee_phone=referral_phone,
                                    referee_name=display_name,
                                    referrer_name=referrer_name,
                                    campaign=campaign
                                )

                                if success:
                                    logger.info(f"[WAHA Task] ✅ Mensagem de boas-vindas agendada via ReferralService para {display_name}")
                                else:
                                    logger.warning(f"[WAHA Task] ⚠️ Falha ao agendar boas-vindas para {display_name}")

                            except Exception as e:
                                logger.error(f"[WAHA Task] ❌ Erro ao agendar boas-vindas via ReferralService: {e}")

                            # Enviar mensagem de confirmação
                            confirmation_msg = f"🎉 Perfeito! Recebi o contato do(a) {display_name}! Vou entrar em contato em breve para oferecer nosso desconto especial de indicação.\n\nVocê ainda pode indicar mais 2 pessoas! Tem mais alguém que precisa de tratamento de serviços?"

                            # Definir user_text para que o LLM processe a confirmação
                            user_text = f"Usuário compartilhou contato para indicação: {display_name} - {referral_phone}"

                            # Adicionar mensagem de confirmação ao chat
                            append_message_to_chat_file(company_id, phone, from_me=False, content=user_text)
                            append_message_to_chat_file(company_id, phone, from_me=True, content=confirmation_msg)

                            logger.info(f"[WAHA Task] 📲 Mensagem de confirmação preparada para envio")
                        else:
                            logger.info(f"[WAHA Task] ⚠️ Lead já existe para {referral_phone}")
                            user_text = f"Contato {display_name} já foi indicado anteriormente."
                    else:
                        logger.info(f"[WAHA Task] ⚠️ Sem campanha ativa para empresa {company_id}")
                else:
                    logger.info(f"[WAHA Task] ⚠️ vCard incompleto: nome='{display_name}', phones={phones}")

            except Exception as e:
                logger.error(f"[WAHA Task] ❌ Erro ao processar vCard como indicação: {e}")

        # 🔥 CORREÇÃO: APENAS criar/atualizar contatos para mensagens RECEBIDAS (fromMe=false)
        # Mensagens fromMe=true (enviadas por nós) não devem criar contatos
        # Isso evita criar contatos com IDs de canais (@lid) ou números falsos
        if not from_me:
            contact_name = sender_name

            contact_exists = db.execute(text("""
                SELECT id, company_id, name
                FROM contacts
                WHERE client_id = :client_id
                  AND phone = :phone
            """), {"client_id": client_id_db, "phone": phone}).fetchone()

            if contact_exists:
                if contact_exists.company_id != company_id:
                    # Criar novo contato para esta empresa
                    db.execute(text("""
                        INSERT INTO contacts
                            (client_id, company_id, phone, name, sender_lid, source_id, thumbnail_url, last_message_at)
                        VALUES (:client_id, :company_id, :phone, :name, :sender_lid, :source_id, :thumbnail_url, NOW())
                        ON CONFLICT (client_id, company_id, phone) DO UPDATE
                        SET name = EXCLUDED.name,
                            sender_lid = EXCLUDED.sender_lid,
                            source_id = EXCLUDED.source_id,
                            thumbnail_url = EXCLUDED.thumbnail_url,
                            last_message_at = NOW()
                    """), {
                        "client_id": client_id_db,
                        "company_id": company_id,
                        "phone": phone,
                        "name": contact_name,
                        "sender_lid": sender_lid,
                        "source_id": None,  # Indicações não usam source_id de anúncios
                        "thumbnail_url": None  # Indicações não usam thumbnail_url de anúncios
                    })
                else:
                    # Atualizar contato existente
                    db.execute(text("""
                        UPDATE contacts
                        SET name = CASE
                                   WHEN name IS NULL OR name = '' OR name = :phone
                                   THEN :name
                                   ELSE name
                                   END,
                            sender_lid = COALESCE(:sender_lid, sender_lid),
                            source_id = CASE
                                         WHEN :source_id IS NOT NULL AND :source_id != ''
                                         THEN :source_id
                                         ELSE source_id
                                         END,
                            thumbnail_url = CASE
                                             WHEN :thumbnail_url IS NOT NULL AND :thumbnail_url != ''
                                             THEN :thumbnail_url
                                             ELSE thumbnail_url
                                             END,
                            last_message_at = NOW()
                        WHERE client_id = :client_id
                          AND company_id = :company_id
                          AND phone = :phone
                    """), {
                        "name": contact_name,
                        "phone": phone,
                        "client_id": client_id_db,
                        "company_id": company_id,
                        "sender_lid": sender_lid,
                        "source_id": None,  # Indicações não usam source_id de anúncios
                        "thumbnail_url": None  # Indicações não usam thumbnail_url de anúncios
                    })
            else:
                # Criar novo contato
                db.execute(text("""
                    INSERT INTO contacts
                        (client_id, company_id, phone, name, sender_lid, source_id, thumbnail_url, last_message_at)
                    VALUES (:client_id, :company_id, :phone, :name, :sender_lid, :source_id, :thumbnail_url, NOW())
                """), {
                    "client_id": client_id_db,
                    "company_id": company_id,
                    "phone": phone,
                    "name": contact_name,
                    "sender_lid": sender_lid,
                    "source_id": None,  # Indicações não usam source_id de anúncios
                    "thumbnail_url": None  # Indicações não usam thumbnail_url de anúncios
                })

            db.commit()
            logger.info(f"[WAHA Task] Contato atualizado: phone={phone}, name={contact_name}")
        else:
            logger.info(f"[WAHA Task] ⏭️ Mensagem fromMe=true ignorada para criação de contato: phone={phone}")

        # ===== INCREMENTAR UNREAD_COUNT =====
        # Incrementar contador apenas para mensagens recebidas (não do operador/LLM)
        if not from_me and sender_name_db != "LLM":
            db.execute(text("""
                UPDATE contacts
                SET unread_count = unread_count + 1
                WHERE client_id = :client_id
                  AND company_id = :company_id
                  AND phone = :phone
            """), {
                "client_id": client_id_db,
                "company_id": company_id,
                "phone": phone
            })
            db.commit()
            logger.info(f"[WAHA Task] unread_count incrementado para o contato {phone}.")

        # ===== BUSCAR FOTO DE PERFIL DO CONTATO =====
        # Buscar foto via WAHA, persistir localmente como WebP e atualizar o contato.
        if not from_me and session_name:
            try:
                from backend.integrations.waha_utils import (
                    is_local_profile_picture_url,
                    persist_contact_profile_picture_as_webp,
                    should_refresh_contact_profile_picture,
                )

                current_photo_row = db.execute(text("""
                    SELECT photo
                    FROM contacts
                    WHERE client_id = :client_id
                      AND company_id = :company_id
                      AND phone = :phone
                    LIMIT 1
                """), {
                    "client_id": client_id_db,
                    "company_id": company_id,
                    "phone": phone
                }).fetchone()
                existing_photo = current_photo_row.photo if current_photo_row else ""
                contact_photo_for_payload = existing_photo or ""
                refresh_profile_photo = should_refresh_contact_profile_picture(existing_photo)

                profile_photo_url = persist_contact_profile_picture_as_webp(
                    waha_session_name=session_name,
                    phone=phone,
                    company_id=company_id,
                    existing_photo=existing_photo,
                    refresh=refresh_profile_photo
                )

                if profile_photo_url:
                    contact_photo_for_payload = profile_photo_url

                    if profile_photo_url != existing_photo:
                        db.execute(text("""
                            UPDATE contacts
                            SET photo = :photo
                            WHERE client_id = :client_id
                              AND company_id = :company_id
                              AND phone = :phone
                        """), {
                            "photo": profile_photo_url,
                            "client_id": client_id_db,
                            "company_id": company_id,
                            "phone": phone
                        })
                        db.execute(text("""
                            UPDATE messages
                            SET photo = :photo
                            WHERE client_id = :client_id
                              AND company_id = :company_id
                              AND contact_phone = :phone
                              AND zapi_message_id = :message_id
                        """), {
                            "photo": profile_photo_url,
                            "client_id": client_id_db,
                            "company_id": company_id,
                            "phone": phone,
                            "message_id": zapi_message_id
                        })
                        db.commit()
                        logger.info(f"[WAHA Task] Foto de perfil WebP atualizada: {phone}")
                    elif is_local_profile_picture_url(existing_photo):
                        logger.debug(f"[WAHA Task] Foto de perfil local já existente: {phone}")
                else:
                    logger.debug(f"[WAHA Task] Sem foto de perfil para: {phone}")

            except Exception as e:
                logger.warning(f"[WAHA Task] Erro ao buscar foto de perfil (não crítico): {e}")

        # ===== VERIFICAR RESPOSTA DE ENQUETE NPS =====
        # WAHA envia polls com estrutura diferente da Z-API
        # Para eventos "poll.vote", o voto está em payload.vote
        # Para mensagens com pollVote embutido, está em payload.pollVote

        # CORREÇÃO: Verificar tipo de evento primeiro
        event_type = waha_payload.get("event", "")

        # TENTATIVA 1: Evento separado "poll.vote" (formato correto do WAHA)
        if event_type == "poll.vote":
            poll_vote_data = waha_payload.get("payload", {}).get("vote", {})
            logger.info(f"[WAHA Task] 🎯 Evento poll.vote detectado, extraindo de payload.vote")

        # TENTATIVA 2: Mensagem com pollVote embutido (fallback)
        else:
            poll_vote_data = waha_payload.get("payload", {}).get("pollVote")

            # TENTATIVA 3: Aninhado em _data.Message.pollVote (fallback)
            if not poll_vote_data:
                poll_vote_data = waha_payload.get("payload", {}).get("_data", {}).get("Message", {}).get("pollVote")

        # Log completo para debug
        logger.info(f"[WAHA Task] 🔍 Verificação pollVote (event_type={event_type}):")
        logger.info(f"[WAHA Task]   - waha_payload.payload.vote: {bool(waha_payload.get('payload', {}).get('vote', {}))}")
        logger.info(f"[WAHA Task]   - waha_payload.payload.pollVote: {bool(waha_payload.get('payload', {}).get('pollVote'))}")
        logger.info(f"[WAHA Task]   - _data.Message.pollVote: {bool(waha_payload.get('payload', {}).get('_data', {}).get('Message', {}).get('pollVote'))}")
        logger.info(f"[WAHA Task]   - Final (não nulo): {bool(poll_vote_data)}")

        if poll_vote_data and not from_me:
            logger.info("[WAHA Task] 🎯 DETECTADA RESPOSTA DE ENQUETE NPS!")
            try:
                # Adaptar formato WAHA para o processamento NPS existente
                # WAHA usa selectedOptions (array de strings), Z-API usa options (array de objetos)

                # Extrair dados do formato WAHA
                poll_message_id = poll_vote_data.get('pollMessageId')
                selected_options = poll_vote_data.get('selectedOptions', [])

                logger.info(
                    "[WAHA Task] Dados WAHA NPS: pollMessageId_present=%s selectedOptions_count=%s messageId_present=%s",
                    bool(poll_message_id),
                    len(selected_options) if selected_options else 0,
                    bool(message_id),
                )
                logger.info(f"[WAHA Task] 📊 Tipo de selectedOptions: {type(selected_options)}")
                logger.info(f"[WAHA Task] 📊 Tamanho de selectedOptions: {len(selected_options) if selected_options else 0}")

                # NOVO: Buscar o NPS correto no banco de dados usando múltiplas estratégias
                final_poll_message_id = None

                # Estratégia 1: Usar pollMessageId retornado pelo WAHA
                if poll_message_id:
                    nps_lookup = db.execute(text("""
                        SELECT poll_message_id, id
                        FROM nps_responses
                        WHERE company_id = :company_id
                        AND poll_message_id = :poll_message_id
                        LIMIT 1
                    """), {
                        "company_id": company_id,
                        "poll_message_id": poll_message_id
                    }).fetchone()

                    if nps_lookup:
                        final_poll_message_id = nps_lookup.poll_message_id
                        logger.info(f"[WAHA Task] ✅ Encontrado NPS por pollMessageId: {final_poll_message_id}")

                # Estratégia 2: Se não encontrar, buscar por message_id atual
                if not final_poll_message_id:
                    nps_lookup = db.execute(text("""
                        SELECT poll_message_id, id
                        FROM nps_responses
                        WHERE company_id = :company_id
                        AND poll_message_id = :message_id
                        LIMIT 1
                    """), {
                        "company_id": company_id,
                        "message_id": message_id
                    }).fetchone()

                    if nps_lookup:
                        final_poll_message_id = nps_lookup.poll_message_id
                        logger.info(f"[WAHA Task] ✅ Encontrado NPS por messageId: {final_poll_message_id}")

                # Estratégia 3: Se não encontrar, buscar por qualquer NPS recente para este contato
                if not final_poll_message_id:
                    nps_lookup = db.execute(text("""
                        SELECT poll_message_id, id
                        FROM nps_responses
                        WHERE company_id = :company_id
                        AND contact_phone = :phone
                        AND status = 'sent'
                        ORDER BY sent_at DESC
                        LIMIT 1
                    """), {
                        "company_id": company_id,
                        "phone": phone
                    }).fetchone()

                    if nps_lookup:
                        final_poll_message_id = nps_lookup.poll_message_id
                        logger.warning(f"[WAHA Task] ⚠️ Usando NPS mais recente para contato: {final_poll_message_id}")

                # Se ainda não encontrou, usar o pollMessageId original como fallback
                if not final_poll_message_id:
                    final_poll_message_id = poll_message_id or message_id
                    logger.warning(f"[WAHA Task] ❌ Nenhum NPS encontrado, usando fallback: {final_poll_message_id}")

                # Converter selectedOptions do WAHA para options do Z-API
                # WAHA: ['5 ⭐⭐⭐⭐⭐'] → Z-API: [{'name': '5 ⭐⭐⭐⭐⭐'}]
                options = []
                logger.info(f"[WAHA Task] 🔄 Iniciando conversão selectedOptions → options")
                logger.info(f"[WAHA Task] 🔄 selected_options count: {len(selected_options) if selected_options else 0}")

                for i, option in enumerate(selected_options):
                    logger.info(f"[WAHA Task] 🔄 Processando option[{i}] tipo={type(option)}")
                    if isinstance(option, str):
                        new_option = {"name": option}
                        options.append(new_option)
                        logger.info(f"[WAHA Task] 🔄 ✅ String convertida: option[{i}] chars={_len_or_zero(option)}")
                    elif isinstance(option, dict) and 'name' in option:
                        options.append(option)
                        logger.info(f"[WAHA Task] 🔄 ✅ Dict mantido: option[{i}] name_present={bool(option.get('name'))}")
                    else:
                        logger.warning(f"[WAHA Task] 🔄 ❌ Option ignorada (tipo não suportado): tipo={type(option)}")

                logger.info(f"[WAHA Task] 🔄 Options finais: count={len(options)}")

                # NOVO: Buscar o message_id correto da mensagem NPS na tabela messages
                # Isso é necessário para que o frontend encontre a mensagem correta para atualizar
                message_nps_id = None
                try:
                    message_lookup = db.execute(text("""
                        SELECT id, content::jsonb->'nps_data' as nps_data
                        FROM messages
                        WHERE company_id = :company_id
                        AND message_type = 'nps'
                        AND (
                            -- Busca por waha_message_id
                            content::jsonb->'nps_data'->>'waha_message_id' = :poll_message_id
                            OR
                            -- Busca por message_id genérico
                            content::jsonb->'nps_data'->>'message_id' = :poll_message_id
                            OR
                            -- Busca por nps_id relacionado
                            content::jsonb->'nps_data'->>'nps_id' IN (
                                SELECT id::text FROM nps_responses
                                WHERE poll_message_id = :poll_message_id
                                AND company_id = :company_id
                            )
                        )
                        LIMIT 1
                    """), {
                        "company_id": company_id,
                        "poll_message_id": final_poll_message_id
                    }).fetchone()

                    if message_lookup and message_lookup.nps_data:
                        # Extrair o message_id correto do nps_data
                        nps_data = message_lookup.nps_data if isinstance(message_lookup.nps_data, dict) else json.loads(message_lookup.nps_data)
                        # Usar waha_message_id se disponível, senão message_id genérico
                        message_nps_id = nps_data.get('waha_message_id') or nps_data.get('message_id')
                        logger.info(f"[WAHA Task] 🎯 Message ID da mensagem NPS encontrado: {message_nps_id}")
                except Exception as e:
                    logger.error(f"[WAHA Task] ⚠️ Erro ao buscar message_id da mensagem NPS: {e}")

                # Se não encontrou, usar o final_poll_message_id como fallback
                if not message_nps_id:
                    message_nps_id = final_poll_message_id
                    logger.warning(f"[WAHA Task] ⚠️ Usando poll_message_id como fallback para message_nps_id: {message_nps_id}")

                # Construir payload no formato Z-API esperado pela process_nps_response
                nps_payload = {
                    "phone": phone,
                    "messageId": message_id,
                    "pollVote": {
                        "pollMessageId": message_nps_id,  # Usar o message_id correto para o frontend
                        "options": options
                    }
                }

                logger.info(
                    "[WAHA Task] Payload NPS adaptado: message_nps_id=%s options_count=%s",
                    message_nps_id,
                    len(options),
                )

                # ===== CORREÇÃO: Processar NPS igual Z-API (sem mensagem pollVote separada) =====
                # A Z-API não salva mensagem pollVote separada, apenas processa o NPS
                # O processo_nps_response já atualiza a mensagem NPS existente e envia nps_update

                # Processar NPS (atualiza mensagem NPS existente e envia nps_update)
                from backend.worker.process_message import process_nps_response
                process_nps_response(db, company_id, nps_payload)
                logger.info(f"[WAHA Task] ✅ Resposta NPS processada com sucesso (modelo Z-API)!")

                # ===== CORREÇÃO: Retornar imediatamente como Z-API =====
                # A Z-API retorna após processar NPS, não continua processamento
                if audit_id:
                    update_audit_status(db, audit_id, "completed")
                logger.info("[WAHA Task] Processamento NPS finalizado - retornando como Z-API")
                return

            except Exception as e:
                logger.error(f"[WAHA Task] ❌ Erro ao processar resposta NPS: {str(e)}", exc_info=True)
                if audit_id:
                    update_audit_status(db, audit_id, "failed", error=str(e))
                return
        else:
            logger.info(f"[WAHA Task] ℹ️ Não é resposta de enquete (sem pollVote)")

        # ===== LÓGICA DE CRIAÇÃO DE LEADS (Similar ao Z-API) =====


        lead_id_found = None
        lead_id_inserted = None

        # 🔥 CORREÇÃO: APENAS criar/atualizar leads para mensagens RECEBIDAS (fromMe=false)
        # Mensagens fromMe=true (enviadas por nós) não devem criar leads
        if not from_me:
            logger.info(f"[WAHA Task] Verificando se {phone} deve ser lead...")

            # VERIFICAR SE JÁ É CLIENTE ANTES DE CRIAR LEAD
            is_customer = db.execute(text("""
                SELECT p.id FROM customers p
                JOIN contacts c ON p.contact_id = c.id
                WHERE c.phone = :phone AND c.company_id = :company_id
                LIMIT 1
            """), {"phone": phone, "company_id": company_id}).fetchone()

            if is_customer:
                logger.info(f"[WAHA Task] ✅ {phone} já é CLIENTE (id={is_customer.id}) - NÃO criando lead")
            else:
                logger.info(f"[WAHA Task] ❌ {phone} NÃO é cliente - processando lead...")

            # Verificar se já existe lead
            existing_lead = db.execute(text("""
                SELECT id, name
                FROM leads
                WHERE phone = :phone
                  AND company_id = :company_id
                LIMIT 1
            """), {
                "phone": phone,
                "company_id": company_id
            }).fetchone()

            if existing_lead:
                lead_id_found = existing_lead.id
                logger.info(f"[WAHA Task] Lead já existe (id={lead_id_found}). Atualizando dados...")

                # Determinar o nome a ser usado para o lead
                # 🔥 Como estamos dentro de `if not from_me:`, não precisamos verificar from_me
                lead_name = contact_name
                if existing_lead.name and existing_lead.name.strip():
                    logger.info(f"[WAHA Task] Preservando nome existente do lead: '{existing_lead.name}'")
                    lead_name = existing_lead.name

                # Atualizar lead existente (extrair dados de anúncio do payload normalizado)
                ad_source_id = normalized_data.get('sourceId')
                ad_thumbnail_url = normalized_data.get('thumbnailUrl')

                db.execute(text("""
                    UPDATE leads
                    SET sender_lid     = COALESCE(:sender_lid, sender_lid),
                        source_id      = :source_id,
                        thumbnail_url  = :thumbnail_url,
                        name           = CASE
                                       WHEN name IS NULL OR name = '' OR name = :phone
                                       THEN :name
                                       ELSE name
                                       END
                    WHERE id = :lead_id
                      AND company_id = :company_id
                      AND client_id = :client_id
                """), {
                    "sender_lid": sender_lid,
                    "source_id": ad_source_id,
                    "thumbnail_url": ad_thumbnail_url,
                    "name": lead_name,
                    "phone": phone,
                    "lead_id": lead_id_found,
                    "company_id": company_id,
                    "client_id": str(client_id_db)
                })
                logger.info("[WAHA Task] Lead existente atualizado em 'leads'.")
            else:
                # Criar novo lead
                logger.info(f"[WAHA Task] ⏭️ Lead não encontrado para {phone}. Auto-criação desativada. Apenas contato criado/atualizado.")
        else:
            logger.info(f"[WAHA Task] ⏭️ Mensagem fromMe=true ignorada para criação de lead: phone={phone}")

        db.commit()

        # Salvar mídia de campanha de anúncios (se existir)
        # Extrair dados do payload normalizado
        source_id = normalized_data.get('sourceId')
        original_image_url = normalized_data.get('originalImageURL')
        thumbnail_url = normalized_data.get('thumbnailUrl')

        if source_id:
            from backend.worker.process_message import store_ad_campaign_media_once
            try:
                # Priorizar originalImageURL (fallback para thumbnail_url)
                image_url = None
                if original_image_url:
                    image_url = original_image_url
                elif thumbnail_url:
                    image_url = thumbnail_url

                if image_url:
                    store_ad_campaign_media_once(db, company_id, source_id, image_url)
                    logger.info(
                        "[WAHA Task] Mídia de campanha salva: source_id=%s image_url_present=%s",
                        source_id,
                        bool(image_url),
                    )
                else:
                    logger.warning(f"[WAHA Task] source_id={source_id} encontrado mas sem URL de imagem para salvar")
            except Exception as e:
                logger.error(f"[WAHA Task] Erro ao salvar mídia de campanha: {e}")

        # Publicar no Redis (WebSocket) - TODAS AS MENSAGENS
        # ✅ Publicação reativada para todas as mensagens (fromMe=true e fromMe=false)
        # As proteções contra duplicação já existem no frontend e no backend
        # ✅ Publicar mensagens no WebSocket (reativado)
        logger.info(f"[WAHA Task] 📨 PUBLICANDO MENSAGEM RECEBIDA NO REDIS:")
        logger.info(f"  - Phone: {phone}")
        logger.info(f"  - FromMe: {from_me}")
        logger.info(f"  - FromApi: {from_api}")
        logger.info(f"  - Type: {msg_type}")
        logger.info(f"  - Content chars: {_len_or_zero(content)}")
        logger.info(f"  - MessageId: {message_id}")
        logger.info(f"  - SenderName: {sender_name}")

        # 🔥 CORREÇÃO: Construir payload completo conforme o tipo de mensagem
        message_payload = {
            "type": msg_type,
            "content": content,
            "phone": phone,
            "senderName": sender_name,
            "photo": contact_photo_for_payload,
            "fromMe": from_me,
            "messageId": message_id,
            "providerMessageId": message_id,
            "momment": normalized_data.get("momment", ""),
            "company_id": company_id,
            "fromApi": from_api,
            "source": message_source,
            "status": "sent" if from_me else None,
            "replyTo": reply_to_metadata,
            "reactions": [],
            "provider": "waha"  # Identificador do provider
        }

        # 🔥 CORREÇÃO: Adicionar campos específicos por tipo para mídias
        if msg_type == "text":
            message_payload["text"] = {"message": content}
        elif msg_type == "image":
            # Converter URL WAHA para proxy se necessário
            proxy_image_url = _waha_proxy_media_url(content)
            if proxy_image_url != content:
                logger.info(
                    "[WAHA Task] Convertendo imagem URL para proxy: content_present=%s proxy_present=%s",
                    bool(content),
                    bool(proxy_image_url),
                )

            message_payload["image"] = {
                "imageUrl": proxy_image_url,
                "caption": normalized_data.get("image", {}).get("caption", "")
            }
        elif msg_type == "audio":
            # 🔥 CORREÇÃO: Áudio agora é base64 (como Z-API)
            if content.startswith("data:"):
                # Áudio base64 - enviar diretamente (como Z-API)
                logger.info("[WAHA Task] Enviando áudio base64 no WebSocket: chars=%s", _len_or_zero(content))
                message_payload["audio"] = {"audioUrl": content}
            else:
                # Fallback para URLs legadas WAHA
                proxy_audio_url = _waha_proxy_media_url(content)
                if proxy_audio_url != content:
                    logger.info(
                        "[WAHA Task] Convertendo áudio URL legada para proxy: content_present=%s proxy_present=%s",
                        bool(content),
                        bool(proxy_audio_url),
                    )
                message_payload["audio"] = {"audioUrl": proxy_audio_url}
        elif msg_type == "video":
            # 🔥 CORREÇÃO: Converter URL WAHA para proxy (mesmo padrão de imagens)
            proxy_video_url = _waha_proxy_media_url(content)
            logger.info(
                "[WAHA Task] Vídeo detectado: fromMe=%s content_present=%s content_chars=%s",
                from_me,
                bool(content),
                _len_or_zero(content),
            )

            if proxy_video_url != content:
                logger.info(
                    "[WAHA Task] Convertendo vídeo URL para proxy: content_present=%s proxy_present=%s",
                    bool(content),
                    bool(proxy_video_url),
                )

            logger.info("[WAHA Task] Usando URL vídeo: present=%s", bool(proxy_video_url))

            message_payload["video"] = {
                "videoUrl": proxy_video_url,
                "caption": normalized_data.get("video", {}).get("caption", "")
            }
            logger.info("[WAHA Task] Payload vídeo criado: video_url_present=%s", bool(proxy_video_url))
        elif msg_type == "contact":
            message_payload["contact"] = normalized_data.get("contact", {})

        # VERIFICAÇÃO DE DUPLICAÇÃO: Verificar se é uma mensagem enviada via frontend
        from backend.integrations.message_tracker import message_tracker

        # Verificar duplicata somente para echoes da API. Mensagens próprias do
        # app/celular são eventos reais do operador e não podem ser suprimidas.
        duplicate_check = None
        if from_api:
            content_for_check = _message_tracker_content_for_check(msg_type, normalized_data, content)
            duplicate_check = message_tracker.is_duplicate_message(
                company_id=company_id,
                phone=phone,
                message_type=msg_type,
                content=content_for_check,
                from_me=from_me
            )

        if duplicate_check:
            logger.info(f"[WAHA Task] 🚫 Mensagem duplicada detectada e IGNORADA: fingerprint={duplicate_check.get('fingerprint')}, local_id={duplicate_check.get('local_message_id')}")

            # Limpar tracking após processar duplicata
            message_tracker.clear_message_tracking(
                local_message_id=duplicate_check.get('local_message_id'),
                fingerprint=duplicate_check.get('fingerprint')
            )
        else:
            # Publicar apenas quando esta execução criou ou enriqueceu o registro.
            # Webhooks repetidos da WAHA chegam com o mesmo message_id e não devem
            # republicar nem reacionar o frontend.

            should_publish = was_inserted or was_updated

            if should_publish:
                publish_to_redis(company_id, message_payload)
                action_type = "INSERIDA" if was_inserted else "ATUALIZADA" if was_updated else "RECEBIDA"
                logger.info(f"[WAHA Task] 📤 Mensagem {action_type} publicada no Redis (provider=waha)")
            else:
                logger.info(f"[WAHA Task] 🔇 Publicação no Redis SILENCIADA (Mensagem já existia e não houve atualização)")

        logger.info("[WAHA Task] ✅ Etapa de publicação no WebSocket concluída")

        # Processar mídia (transcrição de áudio/vídeo, análise de imagem)
        user_text = ""

        if not from_me:
            if msg_type == "text":
                user_text = content.strip() if content else ""
            elif msg_type == "image" and content:
                caption = normalized_data.get("image", {}).get("caption", "")
                logger.info(
                    "[WAHA Task] Preparando imagem para AgentWorkforce multimodal: content_present=%s caption_len=%s",
                    bool(content),
                    _len_or_zero(caption),
                )
                if caption:
                    user_text = f"[Imagem recebida via WhatsApp]\nLegenda do cliente: {caption.strip()}"
                else:
                    user_text = "[Imagem recebida via WhatsApp]"
            elif msg_type == "audio" and content:
                logger.info("[WAHA Task] Transcrevendo áudio: content_present=%s", bool(content))
                user_text = transcribe_audio(
                    content,
                    api_key=_company_openai_key_for_media(db, company_id),
                )
                if not user_text:
                    user_text = "[Áudio recebido - Não foi possível transcrever o áudio]"
            elif msg_type == "video" and content:
                logger.info("[WAHA Task] Transcrevendo vídeo: content_present=%s", bool(content))
                user_text = transcribe_video(
                    content,
                    api_key=_company_openai_key_for_media(db, company_id),
                )
                if not user_text:
                    user_text = "[Vídeo recebido - Não foi possível transcrever o áudio do vídeo]"
            elif msg_type == "contact":
                # Para contatos, o user_text já foi definido no processamento de indicação acima
                if not user_text:  # Apenas se não foi definido pelo processamento de indicação
                    contact_info = normalized_data.get("contact", {})
                    display_name = contact_info.get("displayName", "Contato")
                    user_text = f"Usuário compartilhou contato: {display_name}"

            # Salvar transcrição no arquivo de memória
            if user_text and (msg_type != "text"):
                append_message_to_chat_file(company_id, phone, from_me=False, content=user_text)

        if not from_me and user_text and not (was_inserted or was_updated):
            logger.info(
                "[WAHA Task] Mensagem recebida já existia e não mudou; pulando automações para evitar resposta duplicada"
            )
            if audit_id:
                update_audit_status(db, audit_id, "completed", error="Mensagem duplicada ignorada")
            return

        # Verificar human_mode
        if not from_me:
            row_human_mode = db.execute(text("""
                SELECT human_mode
                FROM contacts
                WHERE client_id = :client_id
                  AND company_id = :company_id
                  AND phone = :phone
                LIMIT 1
            """), {
                "client_id": client_id_db,
                "company_id": company_id,
                "phone": phone
            }).fetchone()

            if row_human_mode and row_human_mode.human_mode:
                logger.info("[WAHA Task] Contato com human_mode=True. Pulando LLM.")
                if audit_id:
                    update_audit_status(db, audit_id, "completed", error="Human mode ativo")
                return

        # FlowBuilder/AgentWorkforce owns WAHA auto responses. The legacy
        # ai_response_windows gate is intentionally not used in this path.
        if not from_me and user_text:
            try:
                from backend.services.flow_executor_waha import (
                    execute_flow_message,
                    get_active_whatsapp_agent_workforce_context,
                )

                flow_message_data = {
                    "phone": phone,
                    "name": sender_name,
                    "body": user_text,
                    "type": msg_type if msg_type == "image" else "text",
                    "timestamp": normalized_data.get("momment", ""),
                    "messageId": normalized_data.get("messageId"),
                }
                if msg_type == "image" and content:
                    image_payload = {
                        "imageUrl": content,
                        "caption": normalized_data.get("image", {}).get("caption", ""),
                        "mimetype": normalized_data.get("image", {}).get("mimetype", ""),
                    }
                    flow_message_data.update(
                        {
                            "mediaUrl": content,
                            "caption": image_payload["caption"],
                            "mimetype": image_payload["mimetype"],
                            "image": image_payload,
                            "images": [image_payload],
                        }
                    )

                debounce_context = get_active_whatsapp_agent_workforce_context(db, company_id)
                if debounce_context and int(debounce_context.get("response_delay_seconds") or 0) > 0:
                    from backend.worker.agent_workforce_debounce import schedule_debounced_whatsapp_flow

                    scheduled = schedule_debounced_whatsapp_flow(
                        company_id=company_id,
                        operational_epoch=int(operational_epoch),
                        phone=phone,
                        message_text=user_text,
                        message_data=flow_message_data,
                        flow_id=int(debounce_context["flow_id"]),
                        workforce_id=int(debounce_context["workforce_id"]),
                        delay_seconds=int(debounce_context["response_delay_seconds"]),
                    )
                    if scheduled:
                        logger.info(
                            "[WAHA Task] FlowBuilder agendado com agrupamento: company=%s phone=%s flow=%s workforce=%s delay=%ss",
                            company_id,
                            phone,
                            debounce_context.get("flow_id"),
                            debounce_context.get("workforce_id"),
                            debounce_context.get("response_delay_seconds"),
                        )
                        if audit_id:
                            update_audit_status(
                                db,
                                audit_id,
                                "completed",
                                error="FlowBuilder agendado com agrupamento de mensagens",
                            )
                        return

                    logger.warning(
                        "[WAHA Task] Falha ao agendar agrupamento; executando FlowBuilder imediatamente"
                    )

                flow_result = execute_flow_message(db, company_id, flow_message_data)

                if flow_result:
                    flow_sent_message = any(
                        entry.get("node_type") == "sendMessage" and entry.get("success")
                        for entry in flow_result.get("execution_log", [])
                    )

                    logger.info(
                        "[WAHA Task] 🚀 FlowBuilder executed: success=%s nodes=%s flow_id=%s",
                        flow_result.get("success"),
                        flow_result.get("nodes_executed", 0),
                        flow_result.get("flow_id"),
                    )

                    from backend.services.ai_credit_guard import is_ai_credit_block_result

                    flow_credit_blocked = is_ai_credit_block_result(flow_result) or any(
                        is_ai_credit_block_result(entry.get("result"))
                        for entry in flow_result.get("execution_log", [])
                        if isinstance(entry, dict)
                    )
                    if flow_credit_blocked:
                        logger.info("[WAHA Task] IA bloqueada por saldo de créditos; sem fallback para IA normal")
                        if audit_id:
                            update_audit_status(db, audit_id, "completed", error="Créditos de IA esgotados")
                        return

                    if _flow_result_has_flag(flow_result, "blocked_by_schedule"):
                        logger.info("[WAHA Task] Equipe de agentes fora do horário configurado; sem fallback legado")
                        if audit_id:
                            update_audit_status(db, audit_id, "completed", error="Fora do horário da equipe de agentes")
                        return

                    inactive_workforce_status = _flow_result_workforce_status(flow_result)
                    if inactive_workforce_status:
                        logger.info(
                            "[WAHA Task] Equipe de agentes status=%s; sem fallback legado",
                            inactive_workforce_status,
                        )
                        if audit_id:
                            update_audit_status(
                                db,
                                audit_id,
                                "completed",
                                error=f"Equipe de agentes {inactive_workforce_status}",
                            )
                        return

                    if flow_result.get("success") or flow_sent_message:
                        if audit_id:
                            status_detail = "FlowBuilder executado" if flow_result.get("success") else flow_result.get("error", "FlowBuilder falhou após envio")
                            update_audit_status(db, audit_id, "completed", error=status_detail)
                        return  # Skip normal AI processing while an active flow owns this message

                    flow_error_detail = _flow_result_error(flow_result)
                    logger.warning(
                        "[WAHA Task] FlowBuilder falhou antes de enviar mensagem; sem fallback legado. error=%s",
                        flow_error_detail,
                    )
                    if audit_id:
                        update_audit_status(db, audit_id, "completed", error=flow_error_detail)
                    return
                else:
                    logger.info(
                        "[WAHA Task] Sem fluxo WhatsApp ativo para company_id=%s; sem fallback legado",
                        company_id,
                    )
                    if audit_id:
                        update_audit_status(db, audit_id, "completed", error="Sem fluxo WhatsApp ativo")
                    return

            except Exception as flow_error:
                logger.exception("[WAHA Task] ❌ Erro no FlowBuilder; sem fallback legado")
                if audit_id:
                    update_audit_status(db, audit_id, "completed", error=f"Erro no FlowBuilder: {flow_error}")
                return

        # Classificar mensagem e detectar estágio do funil
        msg_category = "desconhecida"
        if not from_me and user_text:
            model_path = os.getenv("MESSAGE_CATEGORY_MODEL_PATH")
            if model_path and os.path.exists(model_path):
                from joblib import load
                try:
                    classification_pipeline = load(model_path)
                    msg_category = classification_pipeline.predict([user_text])[0]
                    logger.info(f"[WAHA Task] Mensagem classificada como: {msg_category}")
                except Exception as e:
                    logger.error(f"[WAHA Task] Erro ao classificar: {e}")
            else:
                logger.debug("[WAHA Task] MESSAGE_CATEGORY_MODEL_PATH não configurado; classificação local ignorada")

        # Detectar estágio do funil baseado no lead_id
        lead_id = lead_id_found if lead_id_found else lead_id_inserted
        funnel_stage = "leads"
        funnel_status = None

        if lead_id:
            # Verificar hierarquia: vendas > comparecimentos > agendamentos > leads
            vendas_exists = db.execute(text("""
                SELECT id FROM vendas
                WHERE lead_id = :lid
                  AND company_id = :cid
                LIMIT 1
            """), {"lid": lead_id, "cid": company_id}).fetchone()

            if vendas_exists:
                funnel_stage = "vendas"
                logger.info(f"[WAHA Task] Lead {lead_id} está no estágio: VENDAS")
            else:
                compare_exists = db.execute(text("""
                    SELECT id FROM comparecimentos
                    WHERE lead_id = :lid
                      AND company_id = :cid
                    LIMIT 1
                """), {"lid": lead_id, "cid": company_id}).fetchone()

                if compare_exists:
                    funnel_stage = "comparecimentos"
                    logger.info(f"[WAHA Task] Lead {lead_id} está no estágio: COMPARECIMENTOS")
                else:
                    agend_exists = db.execute(text("""
                        SELECT id, status
                        FROM agendamentos
                        WHERE lead_id = :lid
                          AND company_id = :cid
                        LIMIT 1
                    """), {"lid": lead_id, "cid": company_id}).fetchone()

                    if agend_exists:
                        funnel_stage = "agendamentos"
                        funnel_status = agend_exists.status
                        logger.info(f"[WAHA Task] Lead {lead_id} está no estágio: AGENDAMENTOS (status={funnel_status})")
                    else:
                        logger.info(f"[WAHA Task] Lead {lead_id} está no estágio: LEADS (novo)")

        logger.info(f"[WAHA Task] Etapa do funil: {funnel_stage}, status={funnel_status}")

        # Processar com LLM via debounce
        if not from_me and user_text:
            # Extrair reply_to_chat_id do payload normalizado
            reply_to_chat_id = normalized_data.get("reply_to_chat_id", phone)

            callback_data = {
                'company_id': company_id,
                'client_id_db': client_id_db,
                'msg_category': msg_category,
                'funnel_stage': funnel_stage,
                'funnel_status': funnel_status,
                'reply_to_chat_id': reply_to_chat_id,  # Preservar ID original para resposta
                '_operational_epoch': int(operational_epoch),
            }

            from backend.worker.debounce_tasks import schedule_debounced_processing
            schedule_debounced_processing(
                phone,
                user_text,
                callback_data,
                operational_epoch=int(operational_epoch),
            )

            logger.info(f"[WAHA Task] Processamento LLM agendado via debounce para phone={phone}, reply_to={reply_to_chat_id}")

        # Atualizar status auditoria
        if audit_id:
            update_audit_status(db, audit_id, "completed")

        logger.info("[WAHA Task] Processamento finalizado com sucesso")

    except Retry:
        raise
    except Exception as e:
        logger.exception(f"[WAHA Task] Erro ao processar mensagem: {e}")

        # Atualizar status auditoria
        if audit_id:
            try:
                update_audit_status(db, audit_id, "failed", error=str(e))
            except:
                pass

        # Retry se possível
        raise self.retry(exc=e, countdown=60, max_retries=3)

    finally:
        db.close()
