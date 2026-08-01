# backend/integrations/zapi_utils.py

import os
import requests
import logging
import base64
from typing import List, Dict, Any, Optional
from fastapi import HTTPException
from pydantic import BaseModel
from backend.config import CLIENT_TOKEN
from backend.runtime_settings import CHAT_MEMORY_DIR

logger = logging.getLogger(__name__)

# Modelos Pydantic para validação
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

class SendCallRequest(BaseModel):
    phone: str
    callDuration: Optional[int] = 5

class MetaAIRequest(BaseModel):
    phone: str
    message: str
    delayMessage: Optional[int] = None
    delayTyping: Optional[int] = None
    mentioned: Optional[List[int]] = None

# Modelos para NPS
class NPSPollRequest(BaseModel):
    phone: str
    question: str = "De 0 a 10, como você avalia nosso atendimento?"
    campaign_name: Optional[str] = "satisfacao_geral"
    context: Optional[Dict[str, Any]] = None
    delayMessage: Optional[int] = None

class NPSResponse(BaseModel):
    company_id: int
    contact_phone: str
    contact_name: Optional[str] = None
    lead_id: Optional[int] = None
    question: str
    campaign_name: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


def send_text_to_zapi(instance_id: str, instance_token: str, phone: str, message: str, company_id: int, human_mode: bool = False):
    """
    Envia uma mensagem de texto via Z-API para o WhatsApp.
    -> Antiga lógica do webhook.py
    """
    url = f"https://api.z-api.io/instances/{instance_id}/token/{instance_token}/send-text"
    headers = {
        "client-token": CLIENT_TOKEN,
        "accept": "application/json",
        "content-type": "application/json"
    }
    payload = {
        "phone": phone,
        "message": message,
        "delayTyping": 6
    }

    logger.info(f"Enviando mensagem para {phone} via Z-API. URL: {url}, Payload: {payload}")
    response = requests.post(url, headers=headers, json=payload)
    logger.info(f"Status code send-text: {response.status_code}, response: {response.text}")

    if response.status_code != 200:
        logger.error("Falha ao enviar mensagem pelo Z-API.")
        raise HTTPException(status_code=400, detail="Falha ao enviar mensagem ao lead.")

    # Se você precisar gravar no .txt quando human_mode=True,
    # mova também para cá (ou chame outra função).
    # Exemplo:
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


def send_audio_to_zapi(instance_id: str, instance_token: str, phone: str, audio_bytes: bytes, company_id: int) -> Dict[str, Any]:
    """
    Envia áudio via Z-API para o WhatsApp.
    Seguindo o formato do webhook.py que está funcionando
    """
    url = f"https://api.z-api.io/instances/{instance_id}/token/{instance_token}/send-audio"
    headers = {
        "client-token": CLIENT_TOKEN,
        "accept": "application/json",
        "content-type": "application/json"
    }

    # Converter para base64 com formato correto (seguindo webhook.py)
    audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
    audio_content = f"data:audio/mpeg;base64,{audio_base64}"

    # Payload seguindo exato formato do webhook.py
    payload = {
        "phone": phone,
        "audio": audio_content,
        "waveform": True
    }

    logger.info(f"Enviando áudio para {phone} via Z-API. Tamanho: {len(audio_bytes)} bytes")
    logger.info(f"Payload: {str(payload)[:200]}...")  # Log payload (truncated)

    response = requests.post(url, headers=headers, json=payload)
    logger.info(f"Status code send-audio: {response.status_code}, response: {response.text}")

    if response.status_code != 200:
        logger.error(f"Falha ao enviar áudio pelo Z-API. Response: {response.text}")
        raise HTTPException(status_code=400, detail=f"Falha ao enviar áudio ao lead. Z-API retornou: {response.text}")

    return response.json()


def send_poll(instance_id: str, instance_token: str, data: SendPollRequest) -> Dict[str, Any]:
    """
    Envia uma enquete via Z-API para o WhatsApp.
    """
    url = f"https://api.z-api.io/instances/{instance_id}/token/{instance_token}/send-poll"
    headers = {
        "client-token": CLIENT_TOKEN,
        "accept": "application/json",
        "content-type": "application/json"
    }

    payload = {
        "phone": data.phone,
        "message": data.message,
        "poll": [item.dict() for item in data.poll]
    }

    if data.delayMessage:
        payload["delayMessage"] = data.delayMessage
    if data.pollMaxOptions:
        payload["pollMaxOptions"] = data.pollMaxOptions

    logger.info(f"Enviando enquete para {data.phone} via Z-API. URL: {url}")
    response = requests.post(url, headers=headers, json=payload)
    logger.info(f"Status code send-poll: {response.status_code}, response: {response.text}")

    if response.status_code != 200:
        logger.error("Falha ao enviar enquete pelo Z-API.")
        raise HTTPException(status_code=400, detail="Falha ao enviar enquete.")

    return response.json()


def delete_message(instance_id: str, instance_token: str, data: DeleteMessageRequest) -> bool:
    """
    Deleta uma mensagem via Z-API.
    """
    url = f"https://api.z-api.io/instances/{instance_id}/token/{instance_token}/messages"
    headers = {
        "client-token": CLIENT_TOKEN,
        "accept": "application/json",
        "content-type": "application/json"
    }

    params = {
        "messageId": data.messageId,
        "phone": data.phone,
        "owner": str(data.owner).lower()
    }

    logger.info(f"Deletando mensagem {data.messageId} para {data.phone} via Z-API")
    response = requests.delete(url, headers=headers, params=params)
    logger.info(f"Status code delete-message: {response.status_code}")

    if response.status_code != 204:
        logger.error(f"Falha ao deletar mensagem pelo Z-API. Status: {response.status_code}")
        raise HTTPException(status_code=400, detail="Falha ao deletar mensagem.")

    return True


def send_reaction(instance_id: str, instance_token: str, data: SendReactionRequest) -> Dict[str, Any]:
    """
    Envia uma reação a uma mensagem via Z-API.
    """
    url = f"https://api.z-api.io/instances/{instance_id}/token/{instance_token}/send-reaction"
    headers = {
        "client-token": CLIENT_TOKEN,
        "accept": "application/json",
        "content-type": "application/json"
    }

    payload = {
        "phone": data.phone,
        "reaction": data.reaction,
        "messageId": data.messageId
    }

    if data.delayMessage:
        payload["delayMessage"] = data.delayMessage

    logger.info(f"Enviando reação {data.reaction} para mensagem {data.messageId} via Z-API")
    response = requests.post(url, headers=headers, json=payload)
    logger.info(f"Status code send-reaction: {response.status_code}, response: {response.text}")

    if response.status_code != 200:
        logger.error("Falha ao enviar reação pelo Z-API.")
        raise HTTPException(status_code=400, detail="Falha ao enviar reação.")

    return response.json()


def remove_reaction(instance_id: str, instance_token: str, data: RemoveReactionRequest) -> Dict[str, Any]:
    """
    Remove uma reação de uma mensagem via Z-API.
    """
    url = f"https://api.z-api.io/instances/{instance_id}/token/{instance_token}/send-remove-reaction"
    headers = {
        "client-token": CLIENT_TOKEN,
        "accept": "application/json",
        "content-type": "application/json"
    }

    payload = {
        "phone": data.phone,
        "messageId": data.messageId
    }

    if data.delayMessage:
        payload["delayMessage"] = data.delayMessage

    logger.info(f"Removendo reação da mensagem {data.messageId} via Z-API")
    response = requests.post(url, headers=headers, json=payload)
    logger.info(f"Status code remove-reaction: {response.status_code}, response: {response.text}")

    if response.status_code != 200:
        logger.error("Falha ao remover reação pelo Z-API.")
        raise HTTPException(status_code=400, detail="Falha ao remover reação.")

    return response.json()


def send_call(instance_id: str, instance_token: str, data: SendCallRequest) -> Dict[str, Any]:
    """
    Faz uma ligação via Z-API.
    """
    url = f"https://api.z-api.io/instances/{instance_id}/token/{instance_token}/send-call"

    payload = f'{{"phone": "{data.phone}", "callDuration": {data.callDuration}}}'
    headers = {'client-token': CLIENT_TOKEN}

    logger.info(f"Fazendo ligação para {data.phone} via Z-API (duração: {data.callDuration}s)")
    response = requests.request("POST", url, data=payload, headers=headers)
    logger.info(f"Status code send-call: {response.status_code}, response: {response.text}")

    if response.status_code != 200:
        logger.error(f"Falha ao fazer ligação pelo Z-API. Response: {response.text}")
        raise HTTPException(status_code=400, detail=f"Falha ao fazer ligação. Z-API retornou: {response.text}")

    return response.json()


def send_nps_poll(instance_id: str, instance_token: str, data: NPSPollRequest) -> Dict[str, Any]:
    """
    Envia enquete NPS de satisfação (1-5 estrelas) via Z-API.
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
        result = send_poll(instance_id, instance_token, poll_data)
        logger.info(f"NPS poll enviado com sucesso: {result}")
        return result
    except Exception as e:
        logger.error(f"Erro ao enviar NPS poll: {str(e)}")
        raise


def send_to_meta_ai(instance_id: str, instance_token: str, data: MetaAIRequest) -> Dict[str, Any]:
    """
    Envia mensagem para Meta AI via Z-API.
    Para chat privado: phone = "13135550002"
    Para grupos: phone = "ID_DO_GRUPO-group" e mentioned = [13135550002]
    """
    url = f"https://api.z-api.io/instances/{instance_id}/token/{instance_token}/send-text"
    headers = {
        "client-token": CLIENT_TOKEN,
        "accept": "application/json",
        "content-type": "application/json"
    }

    payload = {
        "phone": data.phone,
        "message": data.message
    }

    if data.delayMessage:
        payload["delayMessage"] = data.delayMessage
    if data.delayTyping:
        payload["delayTyping"] = data.delayTyping
    if data.mentioned:
        payload["mentioned"] = data.mentioned

    logger.info(f"Enviando mensagem para Meta AI via Z-API. Phone: {data.phone}")
    response = requests.post(url, headers=headers, json=payload)
    logger.info(f"Status code send-meta-ai: {response.status_code}, response: {response.text}")

    if response.status_code != 200:
        logger.error("Falha ao enviar mensagem para Meta AI pelo Z-API.")
        raise HTTPException(status_code=400, detail="Falha ao enviar mensagem para Meta AI.")

    return response.json()
