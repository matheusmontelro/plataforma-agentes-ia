# backend/integrations/evolution_api_utils.py

import os
import requests
import logging
import base64
from typing import List, Dict, Any, Optional
from fastapi import HTTPException
from pydantic import BaseModel

from backend.runtime_settings import CHAT_MEMORY_DIR

logger = logging.getLogger(__name__)

# Modelos Pydantic (compatíveis com zapi_utils.py)
class PollItem(BaseModel):
    name: str

class SendPollRequest(BaseModel):
    phone: str
    message: str
    poll: List[PollItem]
    delayMessage: Optional[int] = None
    pollMaxOptions: Optional[int] = None

class DeleteMessageRequest(BaseModel):
    messageId: str
    phone: str
    owner: bool

class SendReactionRequest(BaseModel):
    phone: str
    reaction: str
    messageId: str
    delayMessage: Optional[int] = None

class RemoveReactionRequest(BaseModel):
    phone: str
    messageId: str
    delayMessage: Optional[int] = None

class NPSPollRequest(BaseModel):
    phone: str
    question: str = "De 0 a 10, como você avalia nosso atendimento?"
    campaign_name: Optional[str] = "satisfacao_geral"
    context: Optional[Dict[str, Any]] = None
    delayMessage: Optional[int] = None


def send_text_to_evolution(base_url: str, instance_id: str, api_key: str, phone: str, message: str, company_id: int, human_mode: bool = False):
    """
    Envia uma mensagem de texto via Evolution API para o WhatsApp.
    Equivalente ao send_text_to_zapi
    """
    url = f"{base_url}/message/sendText/{instance_id}"
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json"
    }

    # Garantir formato correto do número (sem + ou espaços)
    clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "")

    payload = {
        "number": clean_phone,
        "text": message,
        "delay": 6000  # 6 segundos (equivalente ao delayTyping do Z-API)
    }

    logger.info(f"Enviando mensagem para {phone} via Evolution API. URL: {url}, Payload: {payload}")
    response = requests.post(url, headers=headers, json=payload)
    logger.info(f"Status code send-text: {response.status_code}, response: {response.text}")

    if response.status_code not in [200, 201]:
        logger.error(f"Falha ao enviar mensagem pelo Evolution API. Response: {response.text}")
        raise HTTPException(status_code=400, detail="Falha ao enviar mensagem ao lead.")

    # Salvar no arquivo se human_mode=True (igual Z-API)
    if human_mode:
        from pathlib import Path
        line = f"OPER: {message}\n"
        base_path = CHAT_MEMORY_DIR
        file_name = f"chatmemory_{company_id}_{phone}.txt"
        file_path = base_path / file_name
        try:
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as e:
            logger.error(f"Erro ao escrever no arquivo {file_path}: {e}")

    return response.json()


def send_audio_to_evolution(base_url: str, instance_id: str, api_key: str, phone: str, audio_bytes: bytes, company_id: int) -> Dict[str, Any]:
    """
    Envia áudio via Evolution API para o WhatsApp.
    Equivalente ao send_audio_to_zapi
    """
    url = f"{base_url}/message/sendWhatsAppAudio/{instance_id}"
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json"
    }

    # Converter para base64
    audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')

    # Formato Evolution API
    clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "")

    payload = {
        "number": clean_phone,
        "audioBase64": audio_base64,
        "encoding": True
    }

    logger.info(f"Enviando áudio para {phone} via Evolution API. Tamanho: {len(audio_bytes)} bytes")

    response = requests.post(url, headers=headers, json=payload)
    logger.info(f"Status code send-audio: {response.status_code}, response: {response.text}")

    if response.status_code not in [200, 201]:
        logger.error(f"Falha ao enviar áudio pelo Evolution API. Response: {response.text}")
        raise HTTPException(status_code=400, detail=f"Falha ao enviar áudio ao lead. Evolution API retornou: {response.text}")

    return response.json()


def send_poll(base_url: str, instance_id: str, api_key: str, data: SendPollRequest) -> Dict[str, Any]:
    """
    Envia uma enquete via Evolution API para o WhatsApp.
    """
    url = f"{base_url}/message/sendPoll/{instance_id}"
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json"
    }

    clean_phone = data.phone.replace("+", "").replace(" ", "").replace("-", "")

    payload = {
        "number": clean_phone,
        "name": data.message,
        "selectableCount": data.pollMaxOptions or 1,
        "values": [item.name for item in data.poll]
    }

    logger.info(f"Enviando enquete para {data.phone} via Evolution API. URL: {url}")
    response = requests.post(url, headers=headers, json=payload)
    logger.info(f"Status code send-poll: {response.status_code}, response: {response.text}")

    if response.status_code not in [200, 201]:
        logger.error("Falha ao enviar enquete pelo Evolution API.")
        raise HTTPException(status_code=400, detail="Falha ao enviar enquete.")

    return response.json()


def delete_message(base_url: str, instance_id: str, api_key: str, data: DeleteMessageRequest) -> bool:
    """
    Deleta uma mensagem via Evolution API.
    """
    url = f"{base_url}/message/delete/{instance_id}"
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json"
    }

    payload = {
        "messageId": data.messageId
    }

    logger.info(f"Deletando mensagem {data.messageId} via Evolution API")
    response = requests.delete(url, headers=headers, json=payload)
    logger.info(f"Status code delete-message: {response.status_code}")

    if response.status_code not in [200, 201, 204]:
        logger.error(f"Falha ao deletar mensagem pelo Evolution API. Status: {response.status_code}")
        raise HTTPException(status_code=400, detail="Falha ao deletar mensagem.")

    return True


def send_reaction(base_url: str, instance_id: str, api_key: str, data: SendReactionRequest) -> Dict[str, Any]:
    """
    Envia uma reação a uma mensagem via Evolution API.
    """
    url = f"{base_url}/message/sendReaction/{instance_id}"
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json"
    }

    payload = {
        "messageId": data.messageId,
        "emoji": data.reaction
    }

    logger.info(f"Enviando reação {data.reaction} para mensagem {data.messageId} via Evolution API")
    response = requests.post(url, headers=headers, json=payload)
    logger.info(f"Status code send-reaction: {response.status_code}, response: {response.text}")

    if response.status_code not in [200, 201]:
        logger.error("Falha ao enviar reação pelo Evolution API.")
        raise HTTPException(status_code=400, detail="Falha ao enviar reação.")

    return response.json()


def remove_reaction(base_url: str, instance_id: str, api_key: str, data: RemoveReactionRequest) -> Dict[str, Any]:
    """
    Remove uma reação de uma mensagem via Evolution API.
    """
    # Evolution API usa o mesmo endpoint com emoji vazio
    url = f"{base_url}/message/sendReaction/{instance_id}"
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json"
    }

    payload = {
        "messageId": data.messageId,
        "emoji": ""  # Emoji vazio remove a reação
    }

    logger.info(f"Removendo reação da mensagem {data.messageId} via Evolution API")
    response = requests.post(url, headers=headers, json=payload)
    logger.info(f"Status code remove-reaction: {response.status_code}, response: {response.text}")

    if response.status_code not in [200, 201]:
        logger.error("Falha ao remover reação pelo Evolution API.")
        raise HTTPException(status_code=400, detail="Falha ao remover reação.")

    return response.json()


def send_nps_poll(base_url: str, instance_id: str, api_key: str, data: NPSPollRequest) -> Dict[str, Any]:
    """
    Envia enquete NPS de satisfação (1-5 estrelas) via Evolution API.
    """
    # Criar opções de 1 a 5 (escala de estrelas)
    poll_options = [PollItem(name=f"{i} ⭐") for i in range(1, 6)]

    # Criar enquete usando a função existente
    poll_data = SendPollRequest(
        phone=data.phone,
        message=data.question,
        poll=poll_options,
        pollMaxOptions=1,  # Escolha única
        delayMessage=data.delayMessage
    )

    logger.info(f"Enviando NPS poll para {data.phone}: {data.question}")

    try:
        result = send_poll(base_url, instance_id, api_key, poll_data)
        logger.info(f"NPS poll enviado com sucesso: {result}")
        return result
    except Exception as e:
        logger.error(f"Erro ao enviar NPS poll: {str(e)}")
        raise


def get_instance_status(base_url: str, instance_id: str, api_key: str) -> Dict[str, Any]:
    """
    Obtém o status da instância na Evolution API.
    Equivalente ao get_instance_status_from_zapi
    """
    url = f"{base_url}/instance/connectionState/{instance_id}"
    headers = {
        "apikey": api_key
    }

    logger.info(f"Obtendo status da instância {instance_id} via Evolution API")
    response = requests.get(url, headers=headers)
    logger.info(f"Status code: {response.status_code}, response: {response.text}")

    if response.status_code != 200:
        logger.error(f"Falha ao obter status. Response: {response.text}")
        raise HTTPException(status_code=400, detail="Falha ao obter status da instância.")

    data = response.json()

    # Normalizar resposta para formato compatível com Z-API
    return {
        "connected": data.get("state") == "open",
        "state": data.get("state", "unknown")
    }


def get_qrcode_from_evolution(base_url: str, instance_id: str, api_key: str) -> str:
    """
    Obtém o QR Code da instância na Evolution API.
    Equivalente ao get_qrcode_from_zapi
    """
    url = f"{base_url}/instance/connect/{instance_id}"
    headers = {
        "apikey": api_key
    }

    logger.info(f"Obtendo QR Code da instância {instance_id} via Evolution API")
    response = requests.get(url, headers=headers)
    logger.info(f"Status code: {response.status_code}")

    if response.status_code != 200:
        logger.error(f"Falha ao obter QR Code. Response: {response.text}")
        raise HTTPException(status_code=400, detail="Falha ao obter QR Code.")

    data = response.json()

    # Evolution API retorna o QR Code em base64
    return data.get("base64", "")


def get_device_data(base_url: str, instance_id: str, api_key: str) -> Dict[str, Any]:
    """
    Obtém dados do device conectado na Evolution API.
    Equivalente ao get_device_data do Z-API
    """
    url = f"{base_url}/instance/fetchInstances/{instance_id}"
    headers = {
        "apikey": api_key
    }

    logger.info(f"Obtendo dados do device {instance_id} via Evolution API")
    response = requests.get(url, headers=headers)
    logger.info(f"Status code: {response.status_code}")

    if response.status_code != 200:
        logger.error(f"Falha ao obter dados do device. Response: {response.text}")
        raise HTTPException(status_code=400, detail="Falha ao obter dados do device.")

    data = response.json()

    # Normalizar resposta para formato compatível com Z-API
    instance = data[0] if isinstance(data, list) and len(data) > 0 else data

    return {
        "id": instance.get("instanceName", ""),
        "name": instance.get("profileName", ""),
        "phone": instance.get("ownerJid", "").split("@")[0],
        "imgUrl": instance.get("profilePictureUrl", ""),
        "isBusiness": instance.get("businessId") is not None,
        "device": {
            "sessionName": instance.get("instanceName", ""),
            "device_model": instance.get("platform", "")
        }
    }
