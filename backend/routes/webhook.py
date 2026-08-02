# backend/routes/webhook.py
import os
import logging
import time
import subprocess
import json
from fastapi import APIRouter, Request, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from backend.integrations.waha_sdk import WAHAException  # Importação global para evitar UnboundLocalError
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.db import get_db
from backend.auth import get_current_user
import requests
from io import BytesIO
import base64
import tempfile
import os
from pydub import AudioSegment
import speech_recognition as sr
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional, Union
from datetime import datetime, timedelta
from backend.ws_manager import manager
import uuid
import secrets
from backend.models import Message, Client, User, TeamPermission, ClientCompany, Contact
from backend.db import get_db
from backend.ws_manager import manager
from backend.prompt.llm.llm_manager import create_llm_chain_with_memory
from backend.prompt.db_integration.agent_config import get_agent_config_dict
from backend.prompt.media.audio_processing import transcribe_audio, transcribe_video
from backend.prompt.media.image_analysis import analyze_image_with_google_vision
from backend.prompt.scheduling.scheduling_service import SchedulingService, SP_TZ
from backend.prompt.llm.llm_manager import extract_json_from_llm_response
from backend.prompt.db_integration.agendamento_logic import processar_json_do_llm
from backend.prompt.memory.memory_manager import (
    append_message_to_chat_file,
    # Se você usar get_chat_history no webhook, importe também se necessário
)
from backend.prompt.memory.memory_manager import append_message_to_chat_file
from backend.config import CLIENT_TOKEN, WAHA_API_KEY, WAHA_BASE_URL
from backend.runtime_settings import app_slug
from backend.services.message_metadata import (
    message_metadata_for_response,
    normalize_reply_request,
    resolve_waha_reply_to_id,
    update_message_delivery_status,
    update_message_reactions,
)
from backend.services.company_access_control import (
    CompanyOperationalLockBusyError,
    CompanyOperationallyBlockedError,
    ensure_company_operational,
    lock_entities_for_mutation,
)
from backend.runtime_settings import CHAT_MEMORY_DIR


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
formatter = logging.Formatter('[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)

load_dotenv()

router = APIRouter()


def _build_dynamic_contact_visibility_filter(db: Session, user: Union[Client, User]) -> str:
    """Retorna filtro SQL de visibilidade de contatos para usuários internos."""
    if isinstance(user, Client):
        return ""

    team_filter = " AND 1 = 0"
    if not user.team_id:
        return team_filter

    team_permission = db.query(TeamPermission).filter(
        TeamPermission.team_id == user.team_id,
        TeamPermission.resource == "contacts",
        TeamPermission.permission == "view"
    ).first()

    if not team_permission or not team_permission.filter_criteria:
        return team_filter

    criteria = team_permission.filter_criteria
    include_outside_crm = bool(criteria.get("include_outside_crm", False))
    stage_ids = []

    for raw_stage_id in criteria.get("pipeline_stage_ids", []):
        try:
            stage_id = int(raw_stage_id)
        except (TypeError, ValueError):
            continue
        if stage_id > 0 and stage_id not in stage_ids:
            stage_ids.append(stage_id)

    conditions = []
    if include_outside_crm:
        conditions.append("""
            NOT EXISTS (
                SELECT 1 FROM leads l
                WHERE l.phone = c.phone AND l.company_id = c.company_id
            )
        """)

    if stage_ids:
        stage_ids_sql = ", ".join(str(stage_id) for stage_id in stage_ids)
        conditions.append(f"""
            EXISTS (
                SELECT 1 FROM leads l
                WHERE l.phone = c.phone
                  AND l.company_id = c.company_id
                  AND l.current_stage_id IN ({stage_ids_sql})
            )
        """)

    if conditions:
        return f" AND ({' OR '.join(conditions)})"

    return team_filter


def _require_whatsapp_scope(
    user: Union[Client, User],
    client_id: int,
    company_id: int,
    db: Session
) -> int:
    if isinstance(user, User):
        if not user.is_active or int(user.client_id) != int(client_id) or int(user.company_id) != int(company_id):
            raise HTTPException(status_code=403, detail="Acesso negado para esta empresa")
        return user.client_id

    if int(user.id) != int(client_id):
        raise HTTPException(status_code=403, detail="Acesso negado para este cliente")

    association = db.query(ClientCompany).filter(
        ClientCompany.client_id == client_id,
        ClientCompany.company_id == company_id
    ).first()
    if not association:
        raise HTTPException(status_code=403, detail="Acesso negado para esta empresa")

    return user.id

# ==========================================
# MODELOS Pydantic / DATACLASSES
# ==========================================
class WhatsAppSendImageBody(BaseModel):
    phone: str
    image: str
    caption: Optional[str] = None
    viewOnce: Optional[bool] = False
    messageId: Optional[str] = None
    delayMessage: Optional[int] = None
    localMessageId: Optional[str] = None

class WhatsAppSendAudioBody(BaseModel):
    phone: str
    audio: str
    viewOnce: Optional[bool] = False
    localMessageId: Optional[str] = None
    delayMessage: Optional[int] = None
    delayTyping: Optional[int] = None
    waveform: Optional[bool] = True

class WhatsAppSendVideoBody(BaseModel):
    phone: str
    video: str
    caption: Optional[str] = None
    viewOnce: Optional[bool] = False
    messageId: Optional[str] = None
    delayMessage: Optional[int] = None
    delayTyping: Optional[int] = None
    asyncUpload: Optional[bool] = None
    localMessageId: Optional[str] = None

class WhatsAppSendTextBody(BaseModel):
    phone: str
    message: str
    localMessageId: Optional[str] = None
    replyTo: Optional[Dict[str, Any]] = None

class WhatsAppReactionBody(BaseModel):
    phone: str
    messageId: str
    reaction: str = ""


def _is_waha_session_not_found_error(error: Exception) -> bool:
    error_text = str(error).lower()
    return "session not found" in error_text or ("404" in error_text and "not found" in error_text)


def _lock_operational_whatsapp_company(db: Session, company_id: int) -> None:
    """Serialize a WAHA side effect with company state changes and revalidate."""
    lock_entities_for_mutation(db, company_ids=[company_id])
    try:
        ensure_company_operational(db, company_id)
    except CompanyOperationallyBlockedError as exc:
        raise HTTPException(
            status_code=423,
            detail="Acesso da empresa suspenso",
        ) from exc


# ==========================================
# FUNÇÕES AUXILIARES (Z-API)
# ==========================================

# ==========================================
# FUNÇÕES AUXILIARES (Z-API)
# ==========================================
def send_text_to_zapi(
    instance_id: str,
    instance_token: str,
    phone: str,
    message: str,
    company_id: int,
    human_mode: bool = False
):
    """
    Envia uma mensagem de texto via Z-API para o WhatsApp.
    Além disso, registra a mensagem no arquivo .txt SOMENTE
    se for do operador humano (human_mode=True).

    Dessa forma, evitamos duplicar as mensagens da IA,
    que já são salvas em outro local (callback do LLM).
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
        "delayTyping": 3
    }

    logger.info("Enviando mensagem via provider legado: phone=%s chars=%s", phone, len(message or ""))
    response = requests.post(url, headers=headers, json=payload)
    logger.info(f"Status code send-text: {response.status_code}, response: {response.text}")

    if response.status_code != 200:
        logger.error("Falha ao enviar mensagem pelo Z-API.")
        raise HTTPException(status_code=400, detail="Falha ao enviar mensagem ao lead.")

    # -------------------------------------------
    # GRAVAR NO .TXT APENAS SE FOR O OPERADOR (human_mode=True)
    # -------------------------------------------
    if human_mode:
        # Vamos prefixar como "OPER:" no .txt
        # (caso você prefira "HUMAN:", fique à vontade)
        append_message_to_chat_file_with_prefix(
            company_id=company_id,
            contact_phone=phone,
            prefix="OPER",
            content=message
        )
    else:
        # Se for IA, não faremos nada aqui.
        # A gravação das mensagens da IA ocorrerá no callback do LLM
        # (evitando duplicar).
        pass

    return response.json()


def append_message_to_chat_file_with_prefix(company_id: int, contact_phone: str, prefix: str, content: str):
    """
    Função auxiliar para gravar diretamente no .txt com um prefixo.
    """
    BASE_PATH = CHAT_MEMORY_DIR
    file_name = f"chatmemory_{company_id}_{contact_phone}.txt"
    file_path = BASE_PATH / file_name

    line = f"{prefix}: {content}\n"
    try:
        BASE_PATH.mkdir(parents=True, exist_ok=True)
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        logger.error(f"[MemoryManager] Erro ao escrever no arquivo {file_path}: {e}")

def send_image_to_zapi(instance_id: str, instance_token: str, body: WhatsAppSendImageBody):
    """
    Envia uma imagem (por URL ou Base64) para o WhatsApp, via Z-API.
    """
    url = f"https://api.z-api.io/instances/{instance_id}/token/{instance_token}/send-image"
    headers = {
        "client-token": CLIENT_TOKEN,
        "accept": "application/json",
        "content-type": "application/json"
    }
    payload = {
        "phone": body.phone,
        "image": body.image,  # URL ou base64
    }
    # Campos opcionais
    if body.caption:
        payload["caption"] = body.caption
    if body.viewOnce:
        payload["viewOnce"] = body.viewOnce
    if body.messageId:
        payload["messageId"] = body.messageId
    if body.delayMessage:
        payload["delayMessage"] = body.delayMessage

    logger.info(
        "Enviando imagem via provider legado: phone=%s image_present=%s caption_present=%s",
        body.phone,
        bool(body.image),
        bool(body.caption),
    )
    response = requests.post(url, headers=headers, json=payload)
    logger.info(f"Status code send-image: {response.status_code}, response: {response.text}")

    if response.status_code != 200:
        logger.error("Falha ao enviar imagem pelo Z-API.")
        raise HTTPException(status_code=400, detail="Falha ao enviar imagem ao lead.")

    return response.json()

# Mantenha a função original síncrona, e adicione uma nova função para a transcrição
def send_audio_to_zapi(instance_id: str, instance_token: str, body: WhatsAppSendAudioBody):
    url = f"https://api.z-api.io/instances/{instance_id}/token/{instance_token}/send-audio"
    headers = {
        "client-token": CLIENT_TOKEN,
        "accept": "application/json",
        "content-type": "application/json"
    }

    # Garantir que temos o prefixo correto
    audio_content = body.audio
    if "base64," in audio_content:
        if not any(x in audio_content.lower() for x in ["audio/mpeg", "audio/mp3"]):
            # Corrigir o prefixo para áudio/mpeg
            parts = audio_content.split("base64,")
            audio_content = f"data:audio/mpeg;base64,{parts[1]}"
    else:
        # Não tem prefixo, adicionar
        audio_content = f"data:audio/mpeg;base64,{audio_content}"

    # Usar o áudio corrigido
    payload = {
        "phone": body.phone,
        "audio": audio_content,
        "waveform": True
    }

    # Adicionar parâmetros opcionais
    if body.viewOnce:
        payload["viewOnce"] = body.viewOnce
    if body.delayMessage:
        payload["delayMessage"] = body.delayMessage
    if body.delayTyping:
        payload["delayTyping"] = body.delayTyping

    response = requests.post(url, headers=headers, json=payload)
    logger.info(f"Status code send-audio: {response.status_code}, response: {response.text}")

    if response.status_code != 200:
        logger.error("Falha ao enviar áudio pelo Z-API.")
        raise HTTPException(status_code=400, detail="Falha ao enviar áudio ao lead.")

    return response.json()

# Função para processar a transcrição separadamente
def process_audio_transcription(audio_base64: str, company_id: int, contact_phone: str):
    """
    Função para processar a transcrição do áudio em background.
    Lida com diferentes formatos de mídia.
    """
    try:
        logger.info(f"Iniciando processamento de transcrição para company_id={company_id}, phone={contact_phone}")

        # Verificar o formato do base64 e ajustar conforme necessário
        if "base64," in audio_base64:
            # Formato típico: "data:audio/mpeg;base64,DADOS_BASE64_AQUI"
            prefix_end = audio_base64.find("base64,") + 7  # +7 para pular "base64,"
            audio_base64 = audio_base64[prefix_end:]
            logger.info("Prefixo base64 encontrado e removido")

        # Verificar se temos dados suficientes
        if len(audio_base64) < 100:
            logger.error(f"String base64 muito curta: {len(audio_base64)} caracteres")
            return None

        # Decodificar o base64 com tratamento de erro
        try:
            audio_data = base64.b64decode(audio_base64)
            logger.info(f"Base64 decodificado com sucesso. Tamanho: {len(audio_data)} bytes")
        except Exception as e:
            logger.error(f"Erro ao decodificar base64: {e}")
            return None

        # Criar diretório temporário
        temp_dir = tempfile.mkdtemp()

        # Primeiro salvar com extensão .bin para detectar o tipo
        input_file = os.path.join(temp_dir, "audio_temp.bin")
        with open(input_file, "wb") as f:
            f.write(audio_data)

        logger.info(f"Arquivo temporário criado: {input_file} ({os.path.getsize(input_file)} bytes)")

        # Detectar o tipo do arquivo
        import magic
        try:
            mime = magic.Magic(mime=True)
            file_type = mime.from_file(input_file)
            logger.info(f"Tipo de arquivo detectado: {file_type}")

            # Renomear o arquivo com a extensão correta
            if "mp4" in file_type:
                file_ext = ".mp4"
            elif "mp3" in file_type:
                file_ext = ".mp3"
            elif "ogg" in file_type:
                file_ext = ".ogg"
            elif "wav" in file_type:
                file_ext = ".wav"
            elif "webm" in file_type:
                file_ext = ".webm"
            else:
                file_ext = ".m4a"  # Padrão para mídia do WhatsApp

            # Renomear para a extensão correta
            proper_input_file = os.path.join(temp_dir, f"audio_temp{file_ext}")
            os.rename(input_file, proper_input_file)
            logger.info(f"Arquivo renomeado para: {proper_input_file}")

            # Define o caminho do arquivo WAV de saída
            wav_path = os.path.join(temp_dir, "audio_temp.wav")

            # Usar ffmpeg diretamente para converter para WAV
            import subprocess
            cmd = [
                "ffmpeg",
                "-i", proper_input_file,
                "-vn",  # Ignorar stream de vídeo caso exista
                "-ar", "44100",  # taxa de amostragem
                "-ac", "1",  # mono
                "-f", "wav",  # formato WAV
                wav_path
            ]

            process = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            if process.returncode != 0:
                logger.error(f"Erro ao executar ffmpeg: {process.stderr.decode()}")
                raise Exception(f"ffmpeg falhou com código: {process.returncode}")

            logger.info(f"Áudio convertido com sucesso para WAV: {wav_path}")

            # Verificar se o arquivo WAV foi criado
            if not os.path.exists(wav_path):
                raise Exception("Arquivo WAV não foi criado")

            # Transcrever usando speech_recognition
            recognizer = sr.Recognizer()
            with sr.AudioFile(wav_path) as source:
                audio_content = recognizer.record(source)
                transcription = recognizer.recognize_google(audio_content, language="pt-BR")
                logger.info("Transcrição bem-sucedida: chars=%s", len(transcription or ""))

                # Salvar no arquivo de chatmemory com formato que o LLM possa ler
                formatted_message = f"{transcription}"

                # Obtém data/hora atual no fuso São Paulo para o timestamp
                import pytz
                from datetime import datetime
                sp_tz = pytz.timezone("America/Sao_Paulo")
                now_dt = datetime.now(sp_tz)
                timestamp_str = now_dt.strftime("%d/%m/%Y %H:%M")

                # Escreve diretamente no arquivo de memória com o formato correto
                BASE_PATH = CHAT_MEMORY_DIR
                file_name = f"chatmemory_{company_id}_{contact_phone}.txt"
                file_path = BASE_PATH / file_name

                # Formata a linha com prefixo e timestamp no formato que o memory_manager espera
                line_to_write = f"OPER:[{timestamp_str}] {formatted_message}\n"

                try:
                    BASE_PATH.mkdir(parents=True, exist_ok=True)
                    with open(file_path, "a", encoding="utf-8") as f:
                        f.write(line_to_write)
                    logger.info(f"Transcrição salva no chatmemory com timestamp: {timestamp_str}")
                except Exception as e:
                    logger.error(f"[MemoryManager] Erro ao escrever no arquivo {file_path}: {e}")

                # Limpar arquivos temporários
                try:
                    os.remove(proper_input_file)
                    os.remove(wav_path)
                    os.rmdir(temp_dir)
                    logger.info("Arquivos temporários removidos")
                except Exception as e:
                    logger.warning(f"Erro ao remover arquivos temporários: {e}")

                return transcription

        except Exception as e:
            logger.error(f"Erro durante transcrição: {e}")
            # Limpar arquivos temporários em caso de erro
            try:
                for f in os.listdir(temp_dir):
                    os.remove(os.path.join(temp_dir, f))
                os.rmdir(temp_dir)
            except:
                pass

    except Exception as e:
        logger.exception(f"Erro ao processar transcrição de áudio: {e}")

    return None

def send_video_to_zapi(instance_id: str, instance_token: str, body: WhatsAppSendVideoBody):
    """
    Envia um vídeo (por URL ou Base64) para o WhatsApp, via Z-API.
    """
    url = f"https://api.z-api.io/instances/{instance_id}/token/{instance_token}/send-video"
    headers = {
        "client-token": CLIENT_TOKEN,
        "accept": "application/json",
        "content-type": "application/json"
    }

    # Log informações básicas
    logger.info(f"[VIDEO] Iniciando envio de vídeo para {body.phone}")

    # Verificar e logar informações sobre o tamanho do payload
    if "base64," in body.video:
        base64_content = body.video.split("base64,")[1]
        approximate_size_mb = len(base64_content) / 1.37 / 1024 / 1024  # Estimativa aproximada
        logger.info(f"[VIDEO] Tamanho aproximado do vídeo: {approximate_size_mb:.2f} MB")

    payload = {
        "phone": body.phone,
        "video": body.video,
    }
    # Adicionar parâmetros opcionais
    if body.caption:
        payload["caption"] = body.caption
    if body.viewOnce:
        payload["viewOnce"] = body.viewOnce
    if body.messageId:
        payload["messageId"] = body.messageId
    if body.delayMessage:
        payload["delayMessage"] = body.delayMessage
    if body.delayTyping:
        payload["delayTyping"] = body.delayTyping
    if body.asyncUpload:
        payload["async"] = body.asyncUpload  # "async" é palavra reservada em Python
        logger.info("[VIDEO] Usando upload assíncrono (async=True)")

    logger.info("[VIDEO] Enviando vídeo via provider legado: phone=%s video_present=%s", body.phone, bool(body.video))

    try:
        # Log início da requisição com timestamp
        start_time = time.time()
        logger.info(f"[VIDEO] Iniciando requisição HTTP {datetime.now().isoformat()}")

        # Fazer a requisição com timeout explícito
        response = requests.post(url, headers=headers, json=payload, timeout=60)

        # Log fim da requisição com duração
        elapsed_time = time.time() - start_time
        logger.info(f"[VIDEO] Requisição completada em {elapsed_time:.2f} segundos")

        # Log detalhado da resposta
        logger.info(f"[VIDEO] Status code: {response.status_code}")
        logger.info(f"[VIDEO] Resposta: {response.text[:500]}..." if len(response.text) > 500 else f"[VIDEO] Resposta: {response.text}")

        if response.status_code == 200:
            logger.info("[VIDEO] Vídeo enviado com sucesso.")
            return response.json()
        else:
            # Log detalhado do erro
            logger.error(f"[VIDEO] Falha ao enviar vídeo. Status code: {response.status_code}")
            logger.error(f"[VIDEO] Detalhes do erro: {response.text}")
            logger.error(f"[VIDEO] Headers da resposta: {dict(response.headers)}")

            # Se for erro 413 (Payload too large)
            if response.status_code == 413:
                logger.error(f"[VIDEO] Erro 413: Vídeo muito grande (Payload Too Large)")
            # Se for erro 429 (Too Many Requests)
            elif response.status_code == 429:
                logger.error(f"[VIDEO] Erro 429: Muitas requisições (Rate limiting)")
            # Se for erro 500 (Internal Server Error)
            elif response.status_code == 500:
                logger.error(f"[VIDEO] Erro 500: Erro interno do servidor Z-API")

            raise HTTPException(status_code=400, detail=f"Falha ao enviar vídeo ao lead. Status: {response.status_code}, Resposta: {response.text[:200]}")

    except requests.exceptions.Timeout:
        logger.exception(f"[VIDEO] Timeout na requisição após 60 segundos")
        raise HTTPException(status_code=504, detail="Timeout ao enviar vídeo para o WhatsApp.")

    except requests.exceptions.RequestException as e:
        logger.exception(f"[VIDEO] Erro na requisição ao enviar vídeo: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro de rede ao enviar vídeo: {str(e)}")

    except Exception as e:
        logger.exception(f"[VIDEO] Erro inesperado ao enviar vídeo: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro interno ao enviar vídeo: {str(e)}")


def get_device_data(instance_id: str, instance_token: str, client_token: str):
    url = f"https://api.z-api.io/instances/{instance_id}/token/{instance_token}/device"
    headers = {"client-token": client_token}
    logger.info("Obtendo dados do device via provider legado: instance_present=%s", bool(instance_id))
    response = requests.get(url, headers=headers)
    logger.info(f"Status code device: {response.status_code}, response: {response.text}")
    if response.status_code != 200:
        logger.error("Falha ao obter dados do device.")
        raise HTTPException(status_code=400, detail="Falha ao obter dados do device.")
    return response.json()

def get_instance_status_from_zapi(instance_id: str, instance_token: str, client_token: str):
    url = f"https://api.z-api.io/instances/{instance_id}/token/{instance_token}/status"
    headers = {
        "client-token": client_token,
        "accept": "application/json"
    }
    logger.info("Obtendo status via provider legado: instance_present=%s", bool(instance_id))
    response = requests.get(url, headers=headers)
    logger.info(f"Status code status: {response.status_code}, response: {response.text}")
    if response.status_code != 200:
        logger.error("Falha ao obter status da instância.")
        raise HTTPException(status_code=400, detail="Falha ao obter status da instância.")
    return response.json()

def get_qrcode_from_zapi(instance_id: str, instance_token: str, client_token: str):
    url = f"https://api.z-api.io/instances/{instance_id}/token/{instance_token}/qr-code/image"
    headers = {
        "client-token": client_token,
        "accept": "application/json"
    }
    logger.info("Obtendo QRCode via provider legado: instance_present=%s", bool(instance_id))
    response = requests.get(url, headers=headers)
    logger.info(f"Status code qrcode: {response.status_code}, response: {response.text}")
    if response.status_code != 200:
        logger.error("Falha ao obter QRCode.")
        raise HTTPException(status_code=400, detail="Falha ao obter QRCode.")
    data = response.json()
    base64_code = data.get("value")
    if not base64_code:
        logger.error("QRCode não encontrado na resposta da API.")
        raise HTTPException(status_code=400, detail="QRCode não encontrado na resposta da API.")
    logger.info("QRCode obtido com sucesso.")
    return base64_code

# ==========================================
# FUNÇÕES AUXILIARES (broadcast WS)
# ==========================================
active_connections: List[WebSocket] = []

async def broadcast_message(message: Dict[str, Any]):
    disconnected_connections = []
    for ws in active_connections:
        try:
            await ws.send_json(message)
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem pelo WebSocket: {e}")
            disconnected_connections.append(ws)
    for ws in disconnected_connections:
        active_connections.remove(ws)

# ==========================================
# ENDPOINTS PRINCIPAIS
# ==========================================

# -----------------------------------------------------
# 1) Envio de TEXTO via "/send-text"
# -----------------------------------------------------
@router.post("/send-text")
def send_text(
    body: WhatsAppSendTextBody,
    client_id: int = Query(..., description="Client ID do master ou user"),
    company_id: int = Query(..., description="Company ID"),
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user)
):
    """
    Envia texto usando WAHA.
    Recebe:
      - query params: client_id, company_id
      - body json: { phone, message }
    Exemplo de chamada:
      POST /webhook/send-text?client_id=6&company_id=1
      { "phone": "5500000000007", "message": "Olá!" }
    """
    _require_whatsapp_scope(user, client_id, company_id, db)

    reply_metadata = normalize_reply_request(body.replyTo)
    provider_reply_to = resolve_waha_reply_to_id(db, company_id, body.phone, body.replyTo)

    # 1) Registrar no BD (PRIMEIRO) para garantir persistência e permitir ACK posterior
    inserted_message_id = None
    try:
        inserted = db.execute(text("""
            INSERT INTO messages
               (client_id, company_id, contact_phone, message_type, content,
                sender_phone, sender_name, from_me, delivery_status, reply_to)
            VALUES
               (:client_id, :company_id, :contact_phone, :message_type, :content,
                :sender_phone, :sender_name, :from_me, :delivery_status, CAST(:reply_to AS JSONB))
            RETURNING id
        """), {
            "client_id": client_id,        # <-- agora vem do query param
            "company_id": company_id,
            "contact_phone": body.phone,
            "message_type": "text",
            "content": body.message,
            "sender_phone": "me",
            "sender_name": "Você",
            "from_me": True,
            "delivery_status": "sending",
            "reply_to": json.dumps(reply_metadata) if reply_metadata else None,
        }).fetchone()
        inserted_message_id = inserted.id if inserted else None
        db.commit()
    except Exception as e:
        logger.error(f"[send_text] Erro ao salvar mensagem no banco: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao salvar mensagem.")

    # 2) Enviar texto via WAHA
    # Passamos db=None para NÃO tentar salvar novamente dentro do provider
    from backend.integrations.whatsapp_provider import send_text as provider_send_text

    try:
        result = provider_send_text(
            company_id=company_id,
            phone=body.phone,
            message=body.message,
            db=None,  # Não salvar novamente
            human_mode=True,
            reply_to=provider_reply_to
        )

        provider_message_id = result.get("id") or result.get("messageId")
        if provider_message_id and inserted_message_id:
            db.execute(text("""
                UPDATE messages
                SET zapi_message_id = :provider_message_id,
                    delivery_status = 'sent',
                    delivery_ack = 1,
                    delivery_status_updated_at = NOW()
                WHERE id = :id
            """), {
                "provider_message_id": provider_message_id,
                "id": inserted_message_id,
            })
            db.commit()
            update_message_delivery_status(
                db=db,
                company_id=company_id,
                provider_message_id=provider_message_id,
                status="sent",
                ack=1,
                ack_name="SERVER",
                local_message_id=body.localMessageId,
                publish=True,
            )

        return {
            "message": "Mensagem de texto enviada com sucesso!",
            "response": result,
            "dbMessageId": inserted_message_id,
            "messageId": provider_message_id,
            "providerMessageId": provider_message_id,
        }
    except Exception as e:
        logger.error(f"[send_text] Erro ao enviar para provedor: {e}")
        if inserted_message_id:
            try:
                db.execute(text("""
                    UPDATE messages
                    SET delivery_status = 'failed',
                        delivery_status_updated_at = NOW()
                    WHERE id = :id
                """), {"id": inserted_message_id})
                db.commit()
            except Exception:
                db.rollback()
        # A mensagem já está salva, então apenas repassamos o erro para o frontend saber
        raise e


@router.put("/reaction")
def send_message_reaction(
    body: WhatsAppReactionBody,
    client_id: int = Query(..., description="Client ID do master ou user"),
    company_id: int = Query(..., description="Company ID"),
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user)
):
    """
    Envia ou remove uma reação via WAHA.
    Use reaction="" para remover a reação atual.
    """
    _require_whatsapp_scope(user, client_id, company_id, db)

    provider_message_id = resolve_waha_reply_to_id(db, company_id, body.phone, {
        "id": body.messageId,
        "providerMessageId": body.messageId,
    })
    if not provider_message_id:
        raise HTTPException(status_code=400, detail="Mensagem sem ID WAHA para reagir.")

    from backend.integrations.whatsapp_provider import send_reaction as provider_send_reaction

    result = provider_send_reaction(
        company_id=company_id,
        data={
            "messageId": provider_message_id,
            "reaction": body.reaction,
        },
        db=db,
    )
    update_payload = update_message_reactions(
        db=db,
        company_id=company_id,
        provider_message_id=provider_message_id,
        reaction=body.reaction,
        actor_id="me",
        from_me=True,
        publish=True,
    )
    return {
        "message": "Reação atualizada com sucesso!",
        "response": result,
        "update": update_payload,
    }


# -----------------------------------------------------
# 2) Envio de IMAGEM via "/send-image"
# -----------------------------------------------------
@router.post("/send-image")
def send_image(
    body: WhatsAppSendImageBody,
    client_id: int = Query(..., description="Client ID do master ou user"),
    company_id: int = Query(..., description="Company ID"),
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user)
):
    """
    Envia imagem (URL/base64) usando WAHA.
    Query params: client_id, company_id
    Body: { phone, image, caption?, ... }
    """
    _require_whatsapp_scope(user, client_id, company_id, db)

    # Importar o tracker de mensagens
    from backend.integrations.message_tracker import message_tracker

    # Extrair bytes da imagem (base64 ou URL)
    import base64
    import requests
    from io import BytesIO

    image_bytes = None
    image_path = None

    # Registrar mensagem no tracker para evitar duplicação
    fingerprint = message_tracker.track_outgoing_message(
        company_id=company_id,
        phone=body.phone,
        message_type='image',
        content=body.image,
        local_message_id=body.localMessageId
    )
    logger.info(f"[send-image] Mensagem registrada no tracker: fingerprint={fingerprint}")

    if body.image.startswith('data:'):
        # Base64: data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ...
        base64_data = body.image.split(',')[1]
        image_bytes = base64.b64decode(base64_data)
    elif body.image.startswith('http'):
        # URL: fazer download
        try:
            response = requests.get(body.image)
            if response.status_code == 200:
                image_bytes = response.content
        except Exception as e:
            logger.error(f"Erro ao baixar imagem da URL: {e}")
            raise HTTPException(status_code=400, detail="Não foi possível baixar a imagem da URL")
    else:
        # Caminho local relativo (ex: client_1/company_1/image/file.jpg)
        # Caminho local relativo (ex: client_1/company_1/image/file.jpg)
        from backend.integrations.whatsapp_provider import MEDIA_BASE_PATH
        potential_path = os.path.join(MEDIA_BASE_PATH, body.image)
        logger.info(f"[send-image] Debug: BASE={MEDIA_BASE_PATH}, IMAGE={body.image}, POTENTIAL={potential_path}")

        if os.path.exists(potential_path):
             image_path = potential_path
             logger.info(f"[send-image] Caminho local detectado: {image_path}")
        else:
             logger.warning(f"[send-image] Arquivo local não encontrado: {potential_path}")
             raise HTTPException(status_code=400, detail="Arquivo local não encontrado")

    if not image_bytes and not image_path:
        raise HTTPException(status_code=400, detail="Formato de imagem inválido")

    # 1) Registrar no BD (PRIMEIRO)
    inserted_message_id = None
    try:
        inserted = db.execute(text("""
            INSERT INTO messages
               (client_id, company_id, contact_phone, message_type, content,
                sender_phone, sender_name, from_me, delivery_status)
            VALUES
               (:client_id, :company_id, :contact_phone, 'image', :content,
                'me', 'Você', true, 'sending')
            RETURNING id
        """), {
            "client_id": client_id,
            "company_id": company_id,
            "contact_phone": body.phone,
            "content": body.image  # salvando o link/base64 original
        }).fetchone()
        inserted_message_id = inserted.id if inserted else None
        db.commit()
    except Exception as e:
        logger.error(f"[send_image] Erro ao salvar mensagem no banco: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao salvar imagem.")

    # 2) Enviar via WAHA
    from backend.integrations.whatsapp_provider import send_image

    try:
        result = send_image(
            company_id=company_id,
            phone=body.phone,
            image_bytes=image_bytes,
            image_path=image_path,
            db=None,  # Não salvar novamente
            caption=body.caption
        )

        provider_message_id = result.get("id") or result.get("messageId")
        if provider_message_id and inserted_message_id:
            db.execute(text("""
                UPDATE messages
                SET zapi_message_id = :provider_message_id,
                    delivery_status = 'sent',
                    delivery_ack = 1,
                    delivery_status_updated_at = NOW()
                WHERE id = :id
            """), {
                "provider_message_id": provider_message_id,
                "id": inserted_message_id,
            })
            db.commit()
            update_message_delivery_status(
                db=db,
                company_id=company_id,
                provider_message_id=provider_message_id,
                status="sent",
                ack=1,
                ack_name="SERVER",
                local_message_id=body.localMessageId,
                publish=True,
            )

        return {
            "message": "Imagem enviada com sucesso!",
            "response": result,
            "dbMessageId": inserted_message_id,
            "messageId": provider_message_id,
            "providerMessageId": provider_message_id,
        }
    except Exception as e:
        logger.error(f"[send_image] Erro ao enviar para provedor: {e}")
        if inserted_message_id:
            try:
                db.execute(text("""
                    UPDATE messages
                    SET delivery_status = 'failed',
                        delivery_status_updated_at = NOW()
                    WHERE id = :id
                """), {"id": inserted_message_id})
                db.commit()
            except Exception:
                db.rollback()
        raise e


# -----------------------------------------------------
# 3) Envio de ÁUDIO via "/send-audio"
# -----------------------------------------------------
@router.post("/send-audio")
def send_audio(
    body: WhatsAppSendAudioBody,
    client_id: int = Query(...),
    company_id: int = Query(...),
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user)
):
    """
    Envia áudio (URL/base64) usando WAHA.
    """
    _require_whatsapp_scope(user, client_id, company_id, db)
    import base64

    # Extrair bytes do áudio (base64 ou URL)
    # Extrair bytes do áudio (base64 ou URL)
    audio_bytes = None
    audio_path = None

    if body.audio.startswith('data:'):
        # Base64: data:audio/webm;base64,GkXf...
        base64_data = body.audio.split(',')[1]
        audio_bytes = base64.b64decode(base64_data)
    elif body.audio.startswith('http'):
        # URL: fazer download
        try:
            import requests
            response = requests.get(body.audio)
            if response.status_code == 200:
                audio_bytes = response.content
        except Exception as e:
            logger.error(f"Erro ao baixar áudio da URL: {e}")
            raise HTTPException(status_code=400, detail="Não foi possível baixar o áudio da URL")
    else:
        # Caminho local relativo (ex: client_1/company_1/audio/file.mp3)
        from backend.integrations.whatsapp_provider import MEDIA_BASE_PATH
        potential_path = os.path.join(MEDIA_BASE_PATH, body.audio)
        if os.path.exists(potential_path):
             audio_path = potential_path
             logger.info(f"[send-audio] Caminho local detectado: {audio_path}")
        else:
             logger.warning(f"[send-audio] Arquivo local não encontrado: {potential_path}")
             raise HTTPException(status_code=400, detail="Arquivo local não encontrado")

    if not audio_bytes and not audio_path:
        raise HTTPException(status_code=400, detail="Formato de áudio inválido")

    # 1) Salvar no banco de dados (PRIMEIRO)
    inserted_message_id = None
    try:
        inserted = db.execute(text("""
            INSERT INTO messages
               (client_id, company_id, contact_phone, message_type, content,
                sender_phone, sender_name, from_me, delivery_status)
            VALUES
               (:client_id, :company_id, :contact_phone, 'audio', :content,
                'me', 'Você', true, 'sending')
            RETURNING id
        """), {
            "client_id": client_id,
            "company_id": company_id,
            "contact_phone": body.phone,
            "content": body.audio  # Salvar o áudio original
        }).fetchone()
        inserted_message_id = inserted.id if inserted else None
        db.commit()
    except Exception as e:
        logger.error(f"[send_audio] Erro ao salvar mensagem no banco: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao salvar áudio.")

    # 2) Enviar via WAHA
    from backend.integrations.whatsapp_provider import send_audio

    try:
        result = send_audio(
            company_id=company_id,
            phone=body.phone,
            audio_bytes=audio_bytes,
            audio_path=audio_path,
            db=None  # Não salvar novamente
        )

        provider_message_id = result.get("id") or result.get("messageId")
        if provider_message_id and inserted_message_id:
            db.execute(text("""
                UPDATE messages
                SET zapi_message_id = :provider_message_id,
                    delivery_status = 'sent',
                    delivery_ack = 1,
                    delivery_status_updated_at = NOW()
                WHERE id = :id
            """), {
                "provider_message_id": provider_message_id,
                "id": inserted_message_id,
            })
            db.commit()
            update_message_delivery_status(
                db=db,
                company_id=company_id,
                provider_message_id=provider_message_id,
                status="sent",
                ack=1,
                ack_name="SERVER",
                local_message_id=body.localMessageId,
                publish=True,
            )

        return {
            "message": "Áudio enviado com sucesso!",
            "response": result,
            "dbMessageId": inserted_message_id,
            "messageId": provider_message_id,
            "providerMessageId": provider_message_id,
        }
    except Exception as e:
        logger.error(f"[send_audio] Erro ao enviar para provedor: {e}")
        if inserted_message_id:
            try:
                db.execute(text("""
                    UPDATE messages
                    SET delivery_status = 'failed',
                        delivery_status_updated_at = NOW()
                    WHERE id = :id
                """), {"id": inserted_message_id})
                db.commit()
            except Exception:
                db.rollback()
        raise e

def prepare_audio_for_whatsapp(audio_content: str) -> str:
    """
    Prepara o conteúdo de áudio para envio ao WhatsApp,
    garantindo o formato correto para reprodução.
    """
    try:
        # Se for uma URL, retorna sem modificação
        if audio_content.startswith(("http://", "https://")):
            logger.info("[AUDIO_DEBUG] Detectado áudio por URL, enviando sem modificação")
            return audio_content

        # Processar o conteúdo base64
        base64_data = audio_content
        if "base64," in audio_content:
            # Extrair dados após o prefixo
            base64_data = audio_content.split("base64,")[1]

        # Decodificar o base64 para bytes
        try:
            audio_bytes = base64.b64decode(base64_data)
        except Exception as e:
            logger.error(f"[AUDIO_DEBUG] Erro ao decodificar base64: {e}")
            # Se falhar, retornar o conteúdo original
            return audio_content

        # Salvar em arquivo temporário para conversão
        with tempfile.TemporaryDirectory() as temp_dir:
            # Salvar bytes em arquivo temporário
            input_file = os.path.join(temp_dir, "input_audio.bin")
            with open(input_file, "wb") as f:
                f.write(audio_bytes)

            # Detectar o tipo real do arquivo
            import magic
            mime = magic.Magic(mime=True)
            file_type = mime.from_file(input_file)
            logger.info(f"[AUDIO_DEBUG] Tipo de arquivo detectado: {file_type}")

            # Renomear para extensão apropriada
            if "mp4" in file_type:
                input_with_ext = os.path.join(temp_dir, "input_audio.mp4")
            elif "mp3" in file_type:
                input_with_ext = os.path.join(temp_dir, "input_audio.mp3")
            elif "ogg" in file_type:
                input_with_ext = os.path.join(temp_dir, "input_audio.ogg")
            elif "wav" in file_type:
                input_with_ext = os.path.join(temp_dir, "input_audio.wav")
            else:
                input_with_ext = os.path.join(temp_dir, "input_audio.m4a")

            os.rename(input_file, input_with_ext)

            # Converter para MP3 (formato para WhatsApp)
            output_file = os.path.join(temp_dir, "whatsapp_audio.mp3")

            # Usar ffmpeg para converter
            import subprocess
            cmd = [
                "ffmpeg",
                "-i", input_with_ext,
                "-c:a", "libmp3lame",   # codec MP3
                "-b:a", "128k",         # bitrate razoável
                "-vn",                  # ignorar vídeo se houver
                output_file
            ]

            logger.info(f"[AUDIO_DEBUG] Convertendo áudio com comando: {' '.join(cmd)}")
            process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            if process.returncode != 0:
                logger.error(f"[AUDIO_DEBUG] Erro ao converter áudio: {process.stderr.decode()}")
                # Se falhar a conversão, retornar com prefixo modificado
                return f"data:audio/mpeg;base64,{base64_data}"

            # Ler o arquivo MP3 convertido
            with open(output_file, "rb") as f:
                mp3_data = f.read()

            # Codificar para base64
            mp3_base64 = base64.b64encode(mp3_data).decode("utf-8")
            logger.info(f"[AUDIO_DEBUG] Áudio convertido para MP3 com sucesso. Tamanho: {len(mp3_base64)} caracteres")

            # Retornar com o prefixo correto
            return f"data:audio/mpeg;base64,{mp3_base64}"

    except Exception as e:
        logger.exception(f"[AUDIO_DEBUG] Erro ao preparar áudio para WhatsApp: {e}")
        # Em caso de erro, retornar o original com prefixo de áudio
        if "base64," in audio_content:
            return audio_content
        else:
            return f"data:audio/mpeg;base64,{audio_content}"

# -----------------------------------------------------
# 4) Envio de VÍDEO via "/send-video"
# -----------------------------------------------------
@router.post("/send-video")
def send_video(
    body: WhatsAppSendVideoBody,
    client_id: int = Query(...),
    company_id: int = Query(...),
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user)
):
    """
    Envia vídeo (URL/base64) usando WAHA.
    Query params: client_id, company_id
    Body: { phone, video, caption?, viewOnce?, delayMessage?, delayTyping?, asyncUpload? }
    """
    _require_whatsapp_scope(user, client_id, company_id, db)

    logger.info(f"Recebido requisição para enviar vídeo. client_id={client_id}, company_id={company_id}")

    # Importar o tracker de mensagens
    from backend.integrations.message_tracker import message_tracker

    try:
        logger.info(
            "[send-video] Dados recebidos: phone=%s, video_present=%s, video_length=%s",
            body.phone,
            bool(body.video),
            len(body.video) if body.video else 0,
        )

        # Registrar mensagem no tracker para evitar duplicação
        fingerprint = message_tracker.track_outgoing_message(
            company_id=company_id,
            phone=body.phone,
            message_type='video',
            content=body.video,
            local_message_id=body.localMessageId
        )
        logger.info(f"[send-video] Mensagem registrada no tracker: fingerprint={fingerprint}")

        # Extrair bytes do vídeo (base64) ou manter URL
        video_bytes = None
        video_url = None

        if body.video.startswith('data:'):
            # Base64: data:video/mp4;base64,AAAAIGZ0eXBpc29tAAAC...
            import base64
            logger.info("[send-video] Detectado vídeo em base64")
            base64_data = body.video.split(',')[1]
            video_bytes = base64.b64decode(base64_data)
            logger.info(f"[send-video] Bytes decodificados: {len(video_bytes)} bytes")

            # Para WAHA, salvar o vídeo como arquivo e gerar URL pública
            try:
                from backend.utils.media_storage import save_video_and_get_url

                logger.info(f"[send-video] Salvando vídeo para empresa {company_id}")
                file_path, video_url = save_video_and_get_url(
                    video_bytes=video_bytes,
                    company_id=company_id
                )
                logger.info(f"[send-video] Vídeo salvo: {file_path}")
                logger.info(f"[send-video] URL pública: {video_url}")
                video_path = file_path  # Caminho local para WAHA

            except Exception as e:
                logger.error(f"[send-video] Erro ao salvar vídeo: {e}")
                raise HTTPException(status_code=500, detail=f"Erro ao salvar vídeo: {str(e)}")

        elif body.video.startswith('http'):
            # URL: WAHA usa URLs diretamente
            logger.info("[send-video] Detectado vídeo em URL")
            video_url = body.video
            video_path = None  # WAHA vai usar a URL diretamente
        else:
             # Caminho local relativo (ex: client_1/company_1/video/file.mp4)
            from backend.integrations.whatsapp_provider import MEDIA_BASE_PATH
            potential_path = os.path.join(MEDIA_BASE_PATH, body.video)
            if os.path.exists(potential_path):
                 video_path = potential_path
                 logger.info(f"[send-video] Caminho local detectado: {video_path}")
            else:
                 logger.warning(f"[send-video] Formato de vídeo não reconhecido ou arquivo não encontrado: {body.video[:50]}...")
                 raise HTTPException(status_code=400, detail="Formato de vídeo inválido ou arquivo não encontrado")

        # Enviar via WAHA
        logger.info("[send-video] Enviando via WAHA")
        from backend.integrations.whatsapp_provider import send_video
        result = send_video(
            company_id=company_id,
            phone=body.phone,
            video_bytes=video_bytes,
            video_path=video_path,  # Caminho local para WAHA ou URL para outros
            db=db,
            caption=body.caption
        )
        logger.info(f"Resposta do envio de vídeo: {result}")

        # NOTA: Não salvamos a mensagem aqui - o webhook WAHA salvará
        # quando receber a confirmação de envio, evitando duplicação

        logger.info("Requisição de envio de vídeo concluída com sucesso.")
        return {
            "message": "Vídeo enviado com sucesso!",
            "response": result
        }

    except HTTPException as e:
        logger.exception(f"Erro ao enviar vídeo: {str(e)}")
        raise

    except Exception as e:
        logger.exception(f"Erro inesperado ao enviar vídeo: {str(e)}")
        try:
            db.rollback()
        except:
            pass
        raise HTTPException(status_code=500, detail="Erro interno ao enviar vídeo.") from e

@router.post("/")
async def receive_webhook(request: Request):
    """
    Apenas um webhook de teste (ou genérico) que não faz nada além de responder 'ok'.
    """
    data = await request.json()
    logger.info(f"Webhook recebido (generic /): {data}")
    return {"status": "ok"}

@router.get("/history")
def get_message_history(contact_phone: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    logger.info(f"Obtendo histórico de mensagens para {user.email} - phone={contact_phone}")

    if not user.company_id:
        raise HTTPException(status_code=400, detail="Usuário sem empresa associada.")

    # Se for usuário não-master, pegar o client_id do master
    if hasattr(user, 'client_id'):  # Se for um User (não-master)
        client_id = user.client_id  # Usa o client_id do master
    else:  # Se for um Client (master)
        client_id = user.id

    logger.info(f"Buscando mensagens com client_id={client_id}, company_id={user.company_id}")

    messages = db.query(Message).filter(
        Message.client_id == client_id,  # Usa o client_id correto
        Message.company_id == user.company_id,
        Message.contact_phone == contact_phone
    ).order_by(Message.id.asc()).all()

    contact_photo_row = db.query(Contact.photo).filter(
        Contact.client_id == client_id,
        Contact.company_id == user.company_id,
        Contact.phone == contact_phone
    ).first()
    contact_photo = contact_photo_row[0] if contact_photo_row and contact_photo_row[0] else ""

    result = []
    for m in messages:
        result.append({
            "id": m.id,
            "type": m.message_type,
            "content": m.content,
            "sender": {
                "phone": m.sender_phone,
                "name": m.sender_name if m.sender_name else "Unknown",
                "photo": m.photo if m.photo else (contact_photo if not m.from_me else "")
            },
            "timestamp": m.timestamp.isoformat(),
            "fromMe": m.from_me,
            **message_metadata_for_response(m)
        })

    logger.info(f"Retornando {len(result)} mensagens")
    return {"messages": result}

@router.get("/contacts/no-history")
def get_contacts_no_history(
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db),
    q_client_id: Optional[int] = Query(None, alias="client_id"),
    q_company_id: Optional[int] = Query(None, alias="company_id"),
    limit: int = Query(50, ge=1, le=500, description="Número máximo de contatos a retornar"),
    offset: int = Query(0, ge=0, description="Número de contatos a pular"),
    search: Optional[str] = Query(None, description="Buscar por nome ou telefone")
):
    """
    Endpoint específico para buscar contatos sem histórico de mensagens.
    Retorna apenas contatos que nunca tiveram mensagens na tabela messages.
    """

    logger.info(
        f"[Webhook] Obtendo contatos sem histórico. user={user.email if user else '??'}, "
        f"q_client_id={q_client_id}, q_company_id={q_company_id}, limit={limit}, offset={offset}, "
        f"search='{search}'"
    )

    def build_no_history_query(base_conditions: str, team_filter: str = "") -> str:
        """Constrói a query para contatos sem histórico"""
        search_filter = ""
        if search:
            search_filter = " AND (LOWER(c.name) LIKE :search OR c.phone LIKE :search)"

        return f"""
            SELECT
                c.id,
                c.phone,
                c.name,
                c.photo,
                c.last_message_at,
                c.human_mode,
                c.source_id,
                c.thumbnail_url,
                c.sender_lid,
                c.unread_count,
                (SELECT l.id FROM leads l WHERE l.phone = c.phone AND l.company_id = c.company_id LIMIT 1) as lead_id,
                (SELECT p.id FROM customers p WHERE p.contact_id = c.id LIMIT 1) as customer_id
            FROM contacts c
            WHERE {base_conditions}
            AND NOT EXISTS (
                SELECT 1 FROM messages m
                WHERE m.contact_phone = c.phone
                AND m.company_id = c.company_id
            )
            {team_filter}
            {search_filter}
            ORDER BY c.name ASC, c.phone ASC
            LIMIT :limit OFFSET :offset
        """

    # Preparar parâmetros da query
    query_params = {
        "limit": limit,
        "offset": offset
    }

    if search:
        query_params["search"] = f"%{search.lower()}%"

    if isinstance(user, Client):
        # Usuário MASTER (Client)
        final_client_id = user.id
        query_params["cid"] = final_client_id

        if q_company_id:
            query_params["company_id"] = q_company_id
            query = build_no_history_query(
                base_conditions="c.client_id = :cid AND c.company_id = :company_id"
            )
        else:
            query = build_no_history_query(
                base_conditions="c.client_id = :cid"
            )

        rows = db.execute(text(query), query_params).fetchall()

    else:
        # Usuário STAFF (User)
        team_filter = _build_dynamic_contact_visibility_filter(db, user)
        query_params.update({"master_id": user.client_id, "company_id": user.company_id})

        query = build_no_history_query(
            base_conditions="c.client_id = :master_id AND c.company_id = :company_id",
            team_filter=team_filter
        )

        rows = db.execute(text(query), query_params).fetchall()

    # Processar resultados
    contacts = []
    for row in rows:
        contacts.append({
            "id": row.id,
            "phone": row.phone,
            "name": row.name or row.phone,
            "photo": row.photo or "",
            "last_message_at": row.last_message_at.isoformat() if row.last_message_at else None,
            "human_mode": row.human_mode or False,
            "source_id": row.source_id,
            "thumbnail_url": row.thumbnail_url,
            "sender_lid": row.sender_lid,
            "lead_id": row.lead_id,
            "customer_id": row.customer_id,
            "unread_count": row.unread_count or 0,
            "last_message": ""  # Contatos sem histórico não têm última mensagem
        })

    # Contar total para paginação
    if isinstance(user, Client):
        count_conditions = "c.client_id = :cid AND c.company_id = :company_id" if q_company_id else "c.client_id = :cid"
    else:
        count_conditions = "c.client_id = :master_id AND c.company_id = :company_id"

    count_query = f"""
        SELECT COUNT(*) as total
        FROM contacts c
        WHERE {count_conditions}
        AND NOT EXISTS (
            SELECT 1 FROM messages m
            WHERE m.contact_phone = c.phone
            AND m.company_id = c.company_id
        )
        {team_filter if 'team_filter' in locals() and team_filter else ''}
        {" AND (LOWER(c.name) LIKE :search OR c.phone LIKE :search)" if search else ""}
    """

    count_result = db.execute(text(count_query), {k: v for k, v in query_params.items() if k != 'limit' and k != 'offset'}).fetchone()
    total = count_result.total if count_result else 0

    has_more = (offset + len(contacts)) < total

    logger.info(f"[Webhook] Retornando {len(contacts)} contatos sem histórico (total: {total}, has_more: {has_more})")

    return {
        "contacts": contacts,
        "total": total,
        "has_more": has_more
    }

@router.get("/contacts")
def get_contacts(
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db),
    q_client_id: Optional[int] = Query(None, alias="client_id"),
    q_company_id: Optional[int] = Query(None, alias="company_id"),
    limit: int = Query(50, ge=1, le=500, description="Número máximo de contatos a retornar"),
    offset: int = Query(0, ge=0, description="Número de contatos a pular"),
    search: Optional[str] = Query(None, description="Buscar por nome ou telefone"),
    unread_only: bool = Query(False, description="Filtrar apenas contatos com mensagens não lidas"),
    show_archived: bool = Query(False, description="Incluir contatos arquivados"),
    archived_only: bool = Query(False, description="Mostrar apenas contatos arquivados"),
    funnel_stages: Optional[str] = Query(None, description="Filtrar por etapas do funil (comma-separated: lead,agendado,compareceu,faltou,venda)"),
    active_flows: Optional[str] = Query(None, description="Filtrar por fluxos ativos (comma-separated: follow_up,confirmation,noshow,pos_consulta,pos_venda)"),
    history_only: bool = Query(False, description="Mostrar apenas contatos com histórico de mensagens")
):
    """
    user: pode ser Client (master) ou User (staff).
    q_client_id: valor de client_id vindo por query param. Ex: ?client_id=6
    q_company_id: valor de company_id vindo por query param. Ex: ?company_id=1
    limit: número máximo de contatos a retornar (padrão: 50, máximo: 500)
    offset: número de contatos a pular para paginação (padrão: 0)
    search: termo de busca para filtrar por nome ou telefone
    unread_only: se True, retorna apenas contatos com mensagens não lidas

    Retorna o campo 'last_message', obtido via subselect e informações do funil de vendas.
    Inclui paginação e filtros para otimizar performance com grandes volumes de contatos.
    """

    logger.info(
        f"[Webhook] Obtendo contatos. user={user.email if user else '??'}, "
        f"q_client_id={q_client_id}, q_company_id={q_company_id}, limit={limit}, offset={offset}, "
        f"search='{search}', unread_only={unread_only}, show_archived={show_archived}, "
        f"archived_only={archived_only}, funnel_stages={funnel_stages}, active_flows={active_flows}, "
        f"history_only={history_only}"
    )

    print(f"🔍 CHECKPOINT: Filtros recebidos - archived_only: {archived_only}, show_archived: {show_archived}")
    print(f"🔍 CHECKPOINT: Filtros de funil: {funnel_stages}")
    print(f"🔍 CHECKPOINT: Filtros de fluxo: {active_flows}")

    def build_contacts_query(base_conditions: str, additional_filters: str = "", team_filter: str = "") -> str:
        """Constrói a query base de contatos com filtros aplicados"""
        search_filter = ""
        if search:
            search_filter = " AND (LOWER(c.name) LIKE :search OR c.phone LIKE :search)"

        unread_filter = ""
        if unread_only:
            unread_filter = " AND c.unread_count > 0"

        # Filtros de arquivamento
        archive_filter = ""
        if archived_only:
            archive_filter = " AND c.archived = true"
        elif not show_archived:
            archive_filter = " AND (c.archived = false OR c.archived IS NULL)"

        history_filter = ""
        if history_only:
             history_filter = " AND c.last_message_at IS NOT NULL"

        return f"""
            SELECT
                c.id,
                c.phone,
                c.name,
                c.photo,
                c.last_message_at,
                c.human_mode,
                c.source_id,
                c.thumbnail_url,
                c.sender_lid,
                c.unread_count,

                -- Primeiro fazemos uma busca pelo ID do lead correspondente ao telefone do contato
                (SELECT l.id FROM leads l WHERE l.phone = c.phone AND l.company_id = c.company_id LIMIT 1) as lead_id,
                (SELECT l.current_stage_id FROM leads l WHERE l.phone = c.phone AND l.company_id = c.company_id LIMIT 1) as current_stage_id,

                -- Verificar se é cliente
                (SELECT p.id FROM customers p WHERE p.contact_id = c.id LIMIT 1) as customer_id,

                -- Subselect para pegar o conteúdo da última mensagem
                (
                    SELECT mm.content
                    FROM messages mm
                    WHERE mm.contact_phone = c.phone
                    AND mm.company_id = c.company_id
                    AND mm.client_id = c.client_id
                ORDER BY mm.timestamp DESC
                    LIMIT 1
                ) AS last_message,

                -- Metadados da última mensagem para exibir checks na lista do chat
                (
                    SELECT mm.from_me
                    FROM messages mm
                    WHERE mm.contact_phone = c.phone
                    AND mm.company_id = c.company_id
                    AND mm.client_id = c.client_id
                    ORDER BY mm.timestamp DESC
                    LIMIT 1
                ) AS last_message_from_me,
                (
                    SELECT COALESCE(mm.delivery_status, CASE WHEN mm.from_me THEN 'sent' ELSE NULL END)
                    FROM messages mm
                    WHERE mm.contact_phone = c.phone
                    AND mm.company_id = c.company_id
                    AND mm.client_id = c.client_id
                    ORDER BY mm.timestamp DESC
                    LIMIT 1
                ) AS last_message_status,

                -- Estágio do funil (novas colunas usando o lead_id encontrado)
                (SELECT a.id FROM agendamentos a
                JOIN leads l ON a.lead_id = l.id
                WHERE l.phone = c.phone AND a.company_id = c.company_id LIMIT 1) as agendamento_id,

                (SELECT comp.id FROM comparecimentos comp
                JOIN agendamentos a ON comp.agendamento_id = a.id
                JOIN leads l ON a.lead_id = l.id
                WHERE l.phone = c.phone AND comp.company_id = c.company_id LIMIT 1) as comparecimento_id,

                (SELECT ns.id FROM noshow_events ns
                JOIN agendamentos a ON ns.agendamento_id = a.id
                JOIN leads l ON a.lead_id = l.id
                WHERE l.phone = c.phone AND a.company_id = c.company_id LIMIT 1) as no_show_id,

                (SELECT v.id FROM vendas v
                JOIN comparecimentos comp ON v.comparecimento_id = comp.id
                JOIN agendamentos a ON comp.agendamento_id = a.id
                JOIN leads l ON a.lead_id = l.id
                WHERE l.phone = c.phone AND a.company_id = c.company_id LIMIT 1) as venda_id,

                -- Tags do contato
                (
                    SELECT COALESCE(
                        json_agg(
                            json_build_object(
                                'id', t.id,
                                'name', t.name,
                                'color', t.color,
                                'category_id', t.category_id
                            ) ORDER BY t.name
                        ),
                        '[]'::json
                    )
                    FROM contact_tags ct
                    JOIN tags t ON ct.tag_id = t.id
                    WHERE ct.contact_id = c.id
                ) as tags,

                -- Flow Progress: Follow-up
                (SELECT json_build_object(
                    'current_step', COALESCE(
                        (SELECT MAX(fue2.step_number)
                         FROM follow_up_executions fue2
                         WHERE fue2.lead_id = fue.lead_id
                           AND fue2.follow_up_sequence_id = fue.follow_up_sequence_id
                           AND fue2.status = 'SUCCESS'),
                        0
                    ),
                    'total_steps', (SELECT COUNT(*) FROM follow_up_steps WHERE follow_up_sequence_id = fue.follow_up_sequence_id),
                    'status', 'ACTIVE',
                    'next_scheduled', (SELECT MIN(fue3.scheduled_for)
                                      FROM follow_up_executions fue3
                                      WHERE fue3.lead_id = fue.lead_id
                                        AND fue3.follow_up_sequence_id = fue.follow_up_sequence_id
                                        AND fue3.status = 'SCHEDULED')
                )
                FROM follow_up_executions fue
                JOIN leads l ON fue.lead_id = l.id
                WHERE l.phone = c.phone
                  AND fue.company_id = c.company_id
                  AND EXISTS (SELECT 1 FROM follow_up_executions fue4
                             WHERE fue4.lead_id = fue.lead_id
                               AND fue4.follow_up_sequence_id = fue.follow_up_sequence_id
                               AND fue4.status IN ('SCHEDULED', 'PROCESSING', 'SUCCESS'))
                ORDER BY fue.follow_up_sequence_id DESC
                LIMIT 1) as follow_up_progress,

                -- Flow Progress: Confirmation
                (SELECT json_build_object(
                    'current_step', COALESCE(
                        (SELECT MAX(ce2.step_number)
                         FROM confirmation_executions ce2
                         WHERE ce2.agendamento_id = ce.agendamento_id
                           AND ce2.confirmation_sequence_id = ce.confirmation_sequence_id
                           AND ce2.status = 'SUCCESS'),
                        0
                    ),
                    'total_steps', (SELECT COUNT(*) FROM confirmation_steps WHERE confirmation_sequence_id = ce.confirmation_sequence_id),
                    'status', 'ACTIVE',
                    'next_scheduled', (SELECT MIN(ce3.scheduled_for)
                                      FROM confirmation_executions ce3
                                      WHERE ce3.agendamento_id = ce.agendamento_id
                                        AND ce3.confirmation_sequence_id = ce.confirmation_sequence_id
                                        AND ce3.status = 'SCHEDULED')
                )
                FROM confirmation_executions ce
                JOIN agendamentos a ON ce.agendamento_id = a.id
                WHERE a.phone = c.phone
                  AND ce.company_id = c.company_id
                  AND EXISTS (SELECT 1 FROM confirmation_executions ce4
                             WHERE ce4.agendamento_id = ce.agendamento_id
                               AND ce4.confirmation_sequence_id = ce.confirmation_sequence_id
                               AND ce4.status IN ('SCHEDULED', 'PROCESSING', 'SUCCESS'))
                ORDER BY ce.confirmation_sequence_id DESC
                LIMIT 1) as confirmation_progress,

                -- Flow Progress: No-show
                (SELECT json_build_object(
                    'current_step', COALESCE(
                        (SELECT MAX(nfe2.step_number)
                         FROM noshow_follow_up_executions nfe2
                         WHERE nfe2.lead_id = nfe.lead_id
                           AND nfe2.noshow_follow_up_sequence_id = nfe.noshow_follow_up_sequence_id
                           AND nfe2.status = 'SUCCESS'),
                        0
                    ),
                    'total_steps', (SELECT COUNT(*) FROM noshow_follow_up_steps WHERE noshow_follow_up_sequence_id = nfe.noshow_follow_up_sequence_id),
                    'status', 'ACTIVE',
                    'next_scheduled', (SELECT MIN(nfe3.scheduled_for)
                                      FROM noshow_follow_up_executions nfe3
                                      WHERE nfe3.lead_id = nfe.lead_id
                                        AND nfe3.noshow_follow_up_sequence_id = nfe.noshow_follow_up_sequence_id
                                        AND nfe3.status = 'SCHEDULED')
                )
                FROM noshow_follow_up_executions nfe
                JOIN leads l ON nfe.lead_id = l.id
                WHERE l.phone = c.phone
                  AND nfe.company_id = c.company_id
                  AND EXISTS (SELECT 1 FROM noshow_follow_up_executions nfe4
                             WHERE nfe4.lead_id = nfe.lead_id
                               AND nfe4.noshow_follow_up_sequence_id = nfe.noshow_follow_up_sequence_id
                               AND nfe4.status IN ('SCHEDULED', 'PROCESSING', 'SUCCESS'))
                ORDER BY nfe.noshow_follow_up_sequence_id DESC
                LIMIT 1) as noshow_progress,

                -- Flow Progress: Pós-consulta
                (SELECT json_build_object(
                    'current_step', COALESCE(
                        (SELECT MAX(pce2.step_number)
                         FROM pos_consulta_executions pce2
                         WHERE pce2.comparecimento_id = pce.comparecimento_id
                           AND pce2.pos_consulta_sequence_id = pce.pos_consulta_sequence_id
                           AND pce2.status = 'SUCCESS'),
                        0
                    ),
                    'total_steps', (SELECT COUNT(*) FROM pos_consulta_steps WHERE pos_consulta_sequence_id = pce.pos_consulta_sequence_id),
                    'status', 'ACTIVE',
                    'next_scheduled', (SELECT MIN(pce3.scheduled_for)
                                      FROM pos_consulta_executions pce3
                                      WHERE pce3.comparecimento_id = pce.comparecimento_id
                                        AND pce3.pos_consulta_sequence_id = pce.pos_consulta_sequence_id
                                        AND pce3.status = 'SCHEDULED')
                )
                FROM pos_consulta_executions pce
                JOIN comparecimentos comp ON pce.comparecimento_id = comp.id
                JOIN agendamentos a ON comp.agendamento_id = a.id
                JOIN leads l ON a.lead_id = l.id
                WHERE l.phone = c.phone
                  AND pce.company_id = c.company_id
                  AND EXISTS (SELECT 1 FROM pos_consulta_executions pce4
                             WHERE pce4.comparecimento_id = pce.comparecimento_id
                               AND pce4.pos_consulta_sequence_id = pce.pos_consulta_sequence_id
                               AND pce4.status IN ('SCHEDULED', 'PROCESSING', 'SUCCESS'))
                ORDER BY pce.pos_consulta_sequence_id DESC
                LIMIT 1) as pos_consulta_progress,

                -- Flow Progress: Pós-venda
                (SELECT json_build_object(
                    'current_step', COALESCE(
                        (SELECT MAX(pve2.step_number)
                         FROM pos_venda_executions pve2
                         WHERE pve2.venda_id = pve.venda_id
                           AND pve2.pos_venda_sequence_id = pve.pos_venda_sequence_id
                           AND pve2.status = 'SUCCESS'),
                        0
                    ),
                    'total_steps', (SELECT COUNT(*) FROM pos_venda_steps WHERE pos_venda_sequence_id = pve.pos_venda_sequence_id),
                    'status', 'ACTIVE',
                    'next_scheduled', (SELECT MIN(pve3.scheduled_for)
                                      FROM pos_venda_executions pve3
                                      WHERE pve3.venda_id = pve.venda_id
                                        AND pve3.pos_venda_sequence_id = pve.pos_venda_sequence_id
                                        AND pve3.status = 'SCHEDULED')
                )
                FROM pos_venda_executions pve
                JOIN vendas v ON pve.venda_id = v.id
                JOIN comparecimentos comp ON v.comparecimento_id = comp.id
                JOIN agendamentos a ON comp.agendamento_id = a.id
                JOIN leads l ON a.lead_id = l.id
                WHERE l.phone = c.phone
                  AND pve.company_id = c.company_id
                  AND EXISTS (SELECT 1 FROM pos_venda_executions pve4
                             WHERE pve4.venda_id = pve.venda_id
                               AND pve4.pos_venda_sequence_id = pve.pos_venda_sequence_id
                               AND pve4.status IN ('SCHEDULED', 'PROCESSING', 'SUCCESS'))
                ORDER BY pve.pos_venda_sequence_id DESC
                LIMIT 1) as pos_venda_progress

            FROM contacts c
            WHERE {base_conditions}
            {additional_filters}
            {search_filter}
            {unread_filter}
            {archive_filter}
            {history_filter}
            {team_filter}
            ORDER BY c.last_message_at DESC NULLS LAST
            LIMIT :limit OFFSET :offset
        """

    # Preparar parâmetros da query
    query_params = {
        "limit": limit,
        "offset": offset
    }

    if search:
        query_params["search"] = f"%{search.lower()}%"

    if isinstance(user, Client):
        # -------------------------
        # Usuário MASTER (Client)
        # -------------------------
        logger.info("[Webhook] É um usuário MASTER (Client).")

        # "final_client_id" SEMPRE será user.id (pois master só enxerga dele mesmo).
        final_client_id = user.id
        query_params["cid"] = final_client_id

        if q_company_id:
            logger.info(f"[Webhook] Master quer filtrar company_id={q_company_id}")
            query_params["company_id"] = q_company_id

            query = build_contacts_query(
                base_conditions="c.client_id = :cid AND c.company_id = :company_id"
            )
        else:
            logger.info("[Webhook] Master não passou company_id, retorna todos contatos do Master.")

            query = build_contacts_query(
                base_conditions="c.client_id = :cid"
            )

        rows = db.execute(text(query), query_params).fetchall()

    else:
        # -------------------------
        # Usuário STAFF (User)
        # -------------------------
        logger.info("[Webhook] É um usuário STAFF (User).")

        team_filter = _build_dynamic_contact_visibility_filter(db, user)
        query_params.update({"master_id": user.client_id, "company_id": user.company_id})

        # Staff: ignoramos query params e usamos user.client_id e user.company_id
        logger.info("[TEAM FILTER] filtro dinâmico aplicado para user_id=%s, team_id=%s", user.id, user.team_id)
        query = build_contacts_query(
            base_conditions="c.client_id = :master_id AND c.company_id = :company_id",
            team_filter=team_filter
        )

        try:
            logger.info(f"[QUERY DEBUG] Executando query com params: master_id={query_params.get('master_id')}, company_id={query_params.get('company_id')}, limit={limit}, offset={offset}")
            rows = db.execute(text(query), query_params).fetchall()
            logger.info(f"[QUERY DEBUG] Query executada com sucesso. Retornados {len(rows)} registros")
        except Exception as e:
            logger.error(f"[QUERY ERROR] Erro ao executar query: {str(e)}")
            logger.error(f"[QUERY ERROR] Params utilizados: {query_params}")
            raise

    # Aplicar filtros adicionais de funil e fluxos (para ambos Client e User)
    print(f"🔍 CHECKPOINT: Aplicando filtros adicionais - funnel_stages: {funnel_stages}, active_flows: {active_flows}")

    # Filtrar por etapas do funil se especificado
    if funnel_stages:
        allowed_stages = [s.strip() for s in funnel_stages.split(',')]
        allowed_stage_ids = [int(stage) for stage in allowed_stages if stage.isdigit()]
        print(f"✅ CHECKPOINT: Filtrando por etapas do funil: {allowed_stages}")

        # Criar uma nova query com filtros de funil
        funnel_conditions = []

        if allowed_stage_ids:
            stage_ids_sql = ", ".join(str(stage_id) for stage_id in allowed_stage_ids)
            funnel_conditions.append(f"""
                EXISTS (
                    SELECT 1 FROM leads l
                    WHERE l.phone = c.phone
                      AND l.company_id = c.company_id
                      AND l.current_stage_id IN ({stage_ids_sql})
                )
            """)

        if "venda" in allowed_stages:
            funnel_conditions.append("""
                EXISTS (
                    SELECT 1 FROM vendas v
                    JOIN comparecimentos comp ON v.comparecimento_id = comp.id
                    JOIN agendamentos a ON comp.agendamento_id = a.id
                    JOIN leads l ON a.lead_id = l.id
                    WHERE l.phone = c.phone AND a.company_id = c.company_id
                )
            """)

        if "compareceu" in allowed_stages:
            funnel_conditions.append("""
                EXISTS (
                    SELECT 1 FROM comparecimentos comp
                    JOIN agendamentos a ON comp.agendamento_id = a.id
                    JOIN leads l ON a.lead_id = l.id
                    WHERE l.phone = c.phone AND comp.company_id = c.company_id
                    AND NOT EXISTS (
                        SELECT 1 FROM vendas v WHERE v.comparecimento_id = comp.id
                    )
                )
            """)

        if "faltou" in allowed_stages:
            funnel_conditions.append("""
                EXISTS (
                    SELECT 1 FROM noshow_events ns
                    JOIN agendamentos a ON ns.agendamento_id = a.id
                    JOIN leads l ON a.lead_id = l.id
                    WHERE l.phone = c.phone AND a.company_id = c.company_id
                )
            """)

        if "agendado" in allowed_stages:
            funnel_conditions.append("""
                EXISTS (
                    SELECT 1 FROM agendamentos a
                    JOIN leads l ON a.lead_id = l.id
                    WHERE l.phone = c.phone AND a.company_id = c.company_id
                    AND NOT EXISTS (
                        SELECT 1 FROM comparecimentos comp WHERE comp.agendamento_id = a.id
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM noshow_events ns WHERE ns.agendamento_id = a.id
                    )
                )
            """)

        if "lead" in allowed_stages:
            funnel_conditions.append("""
                (
                    EXISTS (
                        SELECT 1 FROM leads l
                        WHERE l.phone = c.phone AND l.company_id = c.company_id
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM agendamentos a
                        JOIN leads l ON a.lead_id = l.id
                        WHERE l.phone = c.phone AND a.company_id = c.company_id
                    )
                )
            """)

        if "cliente" in allowed_stages:
            funnel_conditions.append("""
                EXISTS (
                    SELECT 1 FROM customers p
                    WHERE p.contact_id = c.id
                )
            """)

        if "contato" in allowed_stages:
            funnel_conditions.append("""
                (
                    NOT EXISTS (
                        SELECT 1 FROM leads l
                        WHERE l.phone = c.phone AND l.company_id = c.company_id
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM customers p
                        WHERE p.contact_id = c.id
                    )
                )
            """)

        if funnel_conditions:
            # Reconstruir a query com os filtros de funil
            funnel_filter = f" AND ({' OR '.join(funnel_conditions)})"

            # Reexecutar a query com os novos filtros
            if isinstance(user, Client):
                if q_company_id:
                    query = build_contacts_query(
                        base_conditions="c.client_id = :cid AND c.company_id = :company_id",
                        additional_filters=funnel_filter
                    )
                else:
                    query = build_contacts_query(
                        base_conditions="c.client_id = :cid",
                        additional_filters=funnel_filter
                    )
            else:
                query = build_contacts_query(
                    base_conditions="c.client_id = :master_id AND c.company_id = :company_id",
                    additional_filters=funnel_filter,
                    team_filter=team_filter
                )

            rows = db.execute(text(query), query_params).fetchall()

    # Filtrar por fluxos ativos se especificado
    if active_flows:
        allowed_flows = [f.strip() for f in active_flows.split(',')]
        print(f"✅ CHECKPOINT: Filtrando por fluxos ativos: {allowed_flows}")

        # Criar condições para fluxos ativos
        flow_conditions = []

        if "follow_up" in allowed_flows:
            flow_conditions.append("""
                EXISTS (
                    SELECT 1 FROM follow_up_executions fe
                    JOIN leads l ON fe.lead_id = l.id
                    WHERE l.phone = c.phone
                      AND fe.company_id = c.company_id
                      AND fe.status IN ('SCHEDULED', 'PROCESSING')
                )
            """)

        if "confirmation" in allowed_flows:
            flow_conditions.append("""
                EXISTS (
                    SELECT 1 FROM confirmation_executions ce
                    JOIN agendamentos a ON ce.agendamento_id = a.id
                    JOIN leads l ON a.lead_id = l.id
                    WHERE l.phone = c.phone
                      AND ce.company_id = c.company_id
                      AND ce.status IN ('SCHEDULED', 'PROCESSING')
                )
            """)

        if "noshow" in allowed_flows:
            flow_conditions.append("""
                EXISTS (
                    SELECT 1 FROM noshow_follow_up_executions nfe
                    JOIN leads l ON nfe.lead_id = l.id
                    WHERE l.phone = c.phone
                      AND nfe.company_id = c.company_id
                      AND nfe.status IN ('SCHEDULED', 'PROCESSING')
                )
            """)

        if "pos_consulta" in allowed_flows:
            flow_conditions.append("""
                EXISTS (
                    SELECT 1 FROM pos_consulta_executions pce
                    JOIN comparecimentos comp ON pce.comparecimento_id = comp.id
                    JOIN agendamentos a ON comp.agendamento_id = a.id
                    JOIN leads l ON a.lead_id = l.id
                    WHERE l.phone = c.phone
                      AND pce.company_id = c.company_id
                      AND pce.status IN ('SCHEDULED', 'PROCESSING')
                )
            """)

        if "pos_venda" in allowed_flows:
            flow_conditions.append("""
                EXISTS (
                    SELECT 1 FROM pos_venda_executions pve
                    JOIN vendas v ON pve.venda_id = v.id
                    JOIN comparecimentos comp ON v.comparecimento_id = comp.id
                    JOIN agendamentos a ON comp.agendamento_id = a.id
                    JOIN leads l ON a.lead_id = l.id
                    WHERE l.phone = c.phone
                      AND pve.company_id = c.company_id
                      AND pve.status IN ('SCHEDULED', 'PROCESSING')
                )
            """)

        if flow_conditions:
            # Combinar com filtros de funil se existirem
            flow_filter = f" AND ({' OR '.join(flow_conditions)})"
            existing_filter = funnel_filter if funnel_stages and funnel_conditions else ""
            combined_filter = existing_filter + flow_filter

            # Reexecutar a query com todos os filtros
            if isinstance(user, Client):
                if q_company_id:
                    query = build_contacts_query(
                        base_conditions="c.client_id = :cid AND c.company_id = :company_id",
                        additional_filters=combined_filter
                    )
                else:
                    query = build_contacts_query(
                        base_conditions="c.client_id = :cid",
                        additional_filters=combined_filter
                    )
            else:
                query = build_contacts_query(
                    base_conditions="c.client_id = :master_id AND c.company_id = :company_id",
                    additional_filters=combined_filter,
                    team_filter=team_filter
                )

            rows = db.execute(text(query), query_params).fetchall()

    # Montar resposta
    contacts = []

    # Registrar ação de filtro na auditoria
    if funnel_stages or active_flows:
        user_id = user.id if isinstance(user, Client) else user.id
        company_id = q_company_id if q_company_id else (user.company_id if hasattr(user, 'company_id') else None)
        logger.info(
            "[Webhook] Filtro aplicado em lista de contatos. user_id=%s, company_id=%s, "
            "funnel_stages=%s, active_flows=%s, archived_only=%s, show_archived=%s, "
            "unread_only=%s, search=%s, results_count=%s",
            user_id,
            company_id,
            funnel_stages,
            active_flows,
            archived_only,
            show_archived,
            unread_only,
            search,
            len(rows)
        )

    for row in rows:
        # Converter Row para dict para acessar os campos
        r = row._asdict() if hasattr(row, '_asdict') else row

        # Determina o estágio do funil baseado na hierarquia
        funnel_stage = "contato"  # Estágio padrão para contatos simples
        funnel_status = {}

        # LÓGICA HIERÁRQUICA:
        # 0. Se tem current_stage_id (Pipeline Customizado) -> usa o ID do estágio
        # 1. Se é cliente → "cliente"
        # 2. Se tem venda → "venda"
        # 3. Se compareceu → "compareceu"
        # 4. Se faltou → "faltou"
        # 5. Se agendou → "agendado"
        # 6. Se é lead → "lead"
        # 7. Senão → "contato"

        if r.get("current_stage_id"):
            funnel_stage = str(r.get("current_stage_id"))
        elif r.get("customer_id"):
            funnel_stage = "cliente"
            funnel_status["customer_id"] = r.get("customer_id")
        elif r.get("venda_id"):
            funnel_stage = "venda"
            funnel_status["venda_id"] = r.get("venda_id")
            funnel_status["comparecimento_id"] = r.get("comparecimento_id")
            funnel_status["agendamento_id"] = r.get("agendamento_id")
        elif r.get("comparecimento_id"):
            funnel_stage = "compareceu"
            funnel_status["comparecimento_id"] = r.get("comparecimento_id")
            funnel_status["agendamento_id"] = r.get("agendamento_id")
        elif r.get("no_show_id"):
            funnel_stage = "faltou"
            funnel_status["no_show_id"] = r.get("no_show_id")
            funnel_status["agendamento_id"] = r.get("agendamento_id")
        elif r.get("agendamento_id"):
            funnel_stage = "agendado"
            funnel_status["agendamento_id"] = r.get("agendamento_id")
        elif r.get("lead_id"):
            funnel_stage = "lead"
            funnel_status["lead_id"] = r.get("lead_id")

        contacts.append({
            "id": r.get("id"),  # Adicionar ID do contato
            "phone": r.get("phone"),
            "name": r.get("name"),
            "photo": r.get("photo"),
            "last_message_at": r.get("last_message_at").isoformat() if r.get("last_message_at") else None,
            "human_mode": bool(r.get("human_mode")),
            "source_id": r.get("source_id"),
            "thumbnail_url": r.get("thumbnail_url"),
            "sender_lid": r.get("sender_lid"),
            "last_message": r.get("last_message") or "",
            "last_message_from_me": bool(r.get("last_message_from_me")) if r.get("last_message_from_me") is not None else False,
            "last_message_status": r.get("last_message_status"),
            "unread_count": r.get("unread_count", 0),
            # Campos para controle de botões
            "lead_id": r.get("lead_id"),
            "customer_id": r.get("customer_id"),
            # Novos campos do funil
            "funnel_stage": funnel_stage,
            "funnel_status": funnel_status,
            # Progresso dos fluxos
            "flow_progress": {
                "follow_up": r.get("follow_up_progress"),
                "confirmation": r.get("confirmation_progress"),
                "noshow": r.get("noshow_progress"),
                "pos_consulta": r.get("pos_consulta_progress"),
                "pos_venda": r.get("pos_venda_progress")
            } if any([
                r.get("follow_up_progress"),
                r.get("confirmation_progress"),
                r.get("noshow_progress"),
                r.get("pos_consulta_progress"),
                r.get("pos_venda_progress")
            ]) else None
        })

    # Calcular metadados de paginação
    total_contacts = len(contacts)
    has_more = total_contacts == limit  # Se retornou exatamente o limite, pode haver mais

    # Fazer uma query de contagem se necessário para ter o total exato
    if offset == 0 and total_contacts < limit:
        # Primera página e não preencheu o limite = esse é o total
        total_count = total_contacts
    else:
        # Fazer query de contagem
        count_query_params = dict(query_params)
        count_query_params.pop("limit", None)
        count_query_params.pop("offset", None)

        if isinstance(user, Client):
            if q_company_id:
                count_conditions = "c.client_id = :cid AND c.company_id = :company_id"
            else:
                count_conditions = "c.client_id = :cid"
        else:
            count_conditions = "c.client_id = :master_id AND c.company_id = :company_id"

        # Incluir filtros de funil e fluxo na contagem
        additional_count_filters = ""
        if funnel_stages and 'funnel_filter' in locals():
            additional_count_filters += funnel_filter
        if active_flows and 'flow_filter' in locals():
            additional_count_filters += flow_filter

        count_query = f"""
            SELECT COUNT(DISTINCT c.phone) as total
            FROM contacts c
            WHERE {count_conditions}
            {' AND (LOWER(c.name) LIKE :search OR c.phone LIKE :search)' if search else ''}
            {' AND c.unread_count > 0' if unread_only else ''}
            {' AND NOT c.archived' if not show_archived and not archived_only else ''}
            {' AND c.archived' if archived_only else ''}
            {additional_count_filters}
            {team_filter if 'team_filter' in locals() and team_filter else ''}
        """

        count_result = db.execute(text(count_query), count_query_params).fetchone()
        total_count = count_result.total if count_result else 0

    return {
        "contacts": contacts,
        "total": total_count,
        "has_more": has_more,
        "current_page": offset // limit + 1,
        "page_size": limit
    }

# ====================================
#  FUNÇÕES DE REINICIAR / DESCONECTAR
# ====================================

@router.get("/whatsapp/restart")
def restart_instance(user=Depends(get_current_user), db: Session = Depends(get_db)):
    logger.info(f"Reiniciando sessão WAHA para user {user.email}")
    if not user.company_id:
        raise HTTPException(status_code=400, detail="Usuário sem empresa associada.")

    try:
        _lock_operational_whatsapp_company(db, user.company_id)
        company_data = db.execute(
            text("SELECT waha_session_name, waha_enabled FROM companies WHERE id=:cid"),
            {"cid": user.company_id}
        ).fetchone()
        if not company_data or not company_data.waha_enabled or not company_data.waha_session_name:
            logger.warning("Configuração WAHA não encontrada para reiniciar.")
            raise HTTPException(status_code=400, detail="Configuração WAHA não encontrada.")

        from backend.integrations.waha_sdk import get_client as get_waha_client

        client = get_waha_client(base_url=WAHA_BASE_URL, api_key=WAHA_API_KEY)
        result = client.restart_session(company_data.waha_session_name)
        logger.info("[WAHA Restart] Sessão reiniciada: %s", company_data.waha_session_name)
        return {
            "message": "Sessão WAHA reiniciada com sucesso",
            "provider": "waha",
            "session_name": company_data.waha_session_name,
            "result": result,
        }
    except WAHAException as e:
        logger.error("[WAHA Restart] Erro ao reiniciar sessão: %s", e)
        raise HTTPException(status_code=500, detail=f"Erro ao reiniciar WAHA: {str(e)}")
    finally:
        # O fence é transacional e precisa ser liberado antes de devolver a resposta.
        db.rollback()


@router.get("/whatsapp/disconnect")
def disconnect_whatsapp(user=Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Desconecta WhatsApp via WAHA.
    """
    if not user.company_id:
        raise HTTPException(status_code=400, detail="Usuário sem empresa associada.")

    logger.info(f"Desconectando WhatsApp para empresa {user.company_id}")

    # Detectar provider usando WhatsAppConfig
    from backend.integrations.whatsapp_provider import WhatsAppConfig
    from backend.integrations.waha_sdk import get_client as get_waha_client, WAHAException

    config = WhatsAppConfig.from_company(user.company_id, db)

    if not config:
        raise HTTPException(status_code=400, detail="Configuração WhatsApp não encontrada.")

    # WAHA
    if config.is_waha():
        try:
            logger.info(f"[WAHA Disconnect] Desconectando sessão {config.config['session_name']}")
            client = get_waha_client(
                base_url=config.config["base_url"],
                api_key=config.config["api_key"]
            )

            # Logout remove a autenticação, mas mantém a configuração da sessão
            # para que a WAHA consiga iniciar novamente e emitir SCAN_QR_CODE.
            client.logout_session(config.config["session_name"])

            logger.info(f"[WAHA Disconnect] Sessão {config.config['session_name']} desconectada com sucesso")
            return {"message": "WhatsApp desconectado com sucesso. Você pode escanear o QRCode novamente para reconectar."}

        except WAHAException as e:
            if _is_waha_session_not_found_error(e):
                logger.warning(
                    "[WAHA Disconnect] Sessão %s não existe no WAHA; tratando como desconectada",
                    config.config["session_name"]
                )
                return {"message": "WhatsApp já estava desconectado. Você pode gerar um novo QR Code para reconectar."}

            logger.error(f"[WAHA Disconnect] Erro ao desconectar: {e}")
            raise HTTPException(status_code=500, detail=f"Erro ao desconectar WAHA: {str(e)}")

    raise HTTPException(status_code=400, detail="Somente WAHA está habilitado para WhatsApp.")


# ====================================
#  RESETAR / OBTER CONFIGURAÇÃO
# ====================================

@router.post("/whatsapp/reset")
def reset_whatsapp_config(user=Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Reset completo de configuração WhatsApp WAHA.
    """
    logger.info(f"Resetando configuração de WhatsApp (company) para {user.email}")
    if not user.company_id:
        raise HTTPException(status_code=400, detail="Usuário sem empresa associada.")

    # Detectar provider usando WhatsAppConfig
    from backend.integrations.whatsapp_provider import WhatsAppConfig
    from backend.integrations.waha_sdk import get_client as get_waha_client, WAHAException

    # Hold the company operational-access fence across the remote deletion and
    # the local credential cleanup.
    _lock_operational_whatsapp_company(db, int(user.company_id))
    config = WhatsAppConfig.from_company(user.company_id, db)

    # Tentar desconectar antes de resetar (opcional - se existir configuração)
    if config:
        try:
            # WAHA
            if config.is_waha():
                logger.info(f"[WAHA Reset] Removendo sessão {config.config['session_name']}")
                client = get_waha_client(
                    base_url=config.config["base_url"],
                    api_key=config.config["api_key"]
                )
                # Fazer logout e deletar sessão
                client.delete_session(config.config["session_name"], logout=True)
                logger.info(f"[WAHA Reset] Sessão {config.config['session_name']} removida com sucesso")

        except Exception as exc:
            if _is_waha_session_not_found_error(exc):
                logger.info(
                    "[WAHA Reset] Sessão %s já não existia; limpeza local idempotente",
                    config.config["session_name"],
                )
            else:
                db.rollback()
                logger.warning(
                    "[WAHA Reset] Remoção remota falhou; configuração local preservada "
                    "company_id=%s error=%s",
                    user.company_id,
                    exc.__class__.__name__,
                )
                raise HTTPException(
                    status_code=503,
                    detail="whatsapp_reset_remote_delete_failed",
                    headers={"Retry-After": "30"},
                ) from exc

    # Limpar TODAS as configurações do banco
    result = db.execute(
        text("""
            UPDATE companies
               SET zapi_instance_id = NULL,
                   zapi_token = NULL,
                   wppconnect_session_name = NULL,
                   wppconnect_secret_key = NULL,
                   wppconnect_base_url = NULL,
                   waha_session_name = NULL,
                   waha_enabled = false
             WHERE id = :cid
        """),
        {"cid": user.company_id}
    )
    if result.rowcount == 0:
        db.rollback()
        logger.error("Não foi possível resetar a configuração. (Nenhuma linha afetada.)")
        raise HTTPException(status_code=400, detail="Não foi possível resetar a configuração.")
    db.commit()

    logger.info("Todas as configurações de WhatsApp removidas com sucesso (companies).")
    return {"message": "Configurações do WhatsApp removidas com sucesso para esta empresa."}


def _new_waha_session_name(company_id: int) -> str:
    """Return an opaque identifier scoped to the configured public brand."""
    return f"{app_slug()}-c{company_id}-{secrets.token_hex(6)}"


def _session_is_assigned_to_another_company(db: Session, company_id: int, session_name: str) -> bool:
    return db.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                  FROM companies
                 WHERE lower(btrim(waha_session_name)) = lower(btrim(:session_name))
                   AND id <> :company_id
            )
        """),
        {"company_id": company_id, "session_name": session_name},
    ).scalar()


def _resolve_or_generate_waha_session_name(db: Session, company_id: int) -> str:
    current_session = db.execute(
        text("SELECT waha_session_name FROM companies WHERE id = :company_id"),
        {"company_id": company_id},
    ).scalar()

    if current_session and not _session_is_assigned_to_another_company(db, company_id, current_session):
        return current_session

    for _ in range(10):
        candidate = _new_waha_session_name(company_id)
        if not _session_is_assigned_to_another_company(db, company_id, candidate):
            return candidate

    raise RuntimeError("Não foi possível reservar um identificador único para o WhatsApp")


def _persist_active_waha_configuration(
    db: Session,
    company_id: int,
    session_name: str,
) -> None:
    """Enable WAHA only while the locked company remains operational."""
    result = db.execute(
        text("""
            UPDATE companies
               SET zapi_instance_id = NULL,
                   zapi_token = NULL,
                   wppconnect_session_name = NULL,
                   wppconnect_secret_key = NULL,
                   wppconnect_base_url = NULL,
                   waha_session_name = :session_name,
                   waha_enabled = true
             WHERE id = :cid
               AND operational_status = 'active'
        """),
        {
            "session_name": session_name,
            "cid": company_id,
        },
    )

    if result.rowcount == 0:
        db.rollback()
        logger.warning(
            "Configuração WAHA não habilitada: empresa %s deixou de estar operacional",
            company_id,
        )
        raise HTTPException(status_code=423, detail="Acesso da empresa suspenso")

    db.commit()


class WAHAPairingCodeRequest(BaseModel):
    phone_number: Optional[str] = None
    phoneNumber: Optional[str] = None


@router.post("/whatsapp/connect-waha")
def connect_waha(
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Conecta a empresa ao WAHA (WhatsApp HTTP API)
    """
    if not user.company_id:
        raise HTTPException(status_code=400, detail="Usuário sem empresa associada.")

    try:
        # Serializa criações concorrentes da mesma empresa. O nome é interno e nunca
        # deve ser escolhido pelo navegador ou compartilhado entre tenants.
        _lock_operational_whatsapp_company(db, user.company_id)
        session_name = _resolve_or_generate_waha_session_name(db, user.company_id)
        logger.info("Conectando WAHA para empresa %s com identificador interno", user.company_id)

        waha_base_url = WAHA_BASE_URL.rstrip("/")
        if not WAHA_API_KEY:
            logger.error("[WAHA Connect] WAHA_API_KEY não configurada no ambiente")
            raise HTTPException(status_code=500, detail="API key WAHA não configurada no servidor")

        from backend.integrations.waha_sdk import get_client as get_waha_client

        # 1. Testar conexão com WAHA
        logger.info(f"[WAHA Connect] Testando conexão com WAHA em {waha_base_url}")
        client = get_waha_client(base_url=waha_base_url, api_key=WAHA_API_KEY)
        health = client.health()
        if str(health.get("status", "")).lower() != "ok":
            logger.error("[WAHA Connect] Health check WAHA inesperado: %s", health)
            raise HTTPException(status_code=502, detail="WAHA respondeu health check inválido")

        # Verificar se a sessão já existe (corrigido: usar get_session ao invés de list_sessions)
        session_exists = False
        try:
            # list_sessions() não retorna todas as sessões (bug do WAHA)
            # Usar get_session() para verificar se existe
            try:
                session = client.get_session(session_name)
                session_exists = True
                logger.info(f"[WAHA Connect] Sessão '{session_name}' já existe (status: {session.status})")
            except WAHAException as e:
                session_exists = False
                logger.info(f"[WAHA Connect] Sessão '{session_name}' não existe (WAHAException: {type(e).__name__}: {e})")
            except Exception as e:
                session_exists = False
                logger.warning(f"[WAHA Connect] Erro inesperado ao verificar sessão '{session_name}': {type(e).__name__}: {e}")
                import traceback
                logger.debug(f"[WAHA Connect] Traceback: {traceback.format_exc()}")
        except Exception as e:
            # Capturar apenas erros inesperados, não WAHAException (que já foi tratado acima)
            logger.error(f"[WAHA Connect] Erro inesperado ao verificar sessão: {type(e).__name__}: {e}")
            import traceback
            logger.debug(f"[WAHA Connect] Traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Erro interno ao conectar com WAHA: {str(e)}")

        # 2. Criar sessão se não existir
        if not session_exists:
            logger.info(f"[WAHA Connect] Criando nova sessão: {session_name}")
            try:
                client.create_session(session_name)
                logger.info(f"[WAHA Connect] Sessão {session_name} criada com sucesso")

                # ✅ Opção 2: Configurar webhooks COMPLETOS automaticamente para novas sessões
                logger.info(f"[WAHA Connect] Configurando webhooks completos para nova sessão {session_name}")
                configure_waha_webhooks_completely(client, session_name)

            except WAHAException as e:
                logger.error(f"[WAHA Connect] Erro ao criar sessão: {e}")
                raise HTTPException(status_code=400, detail=f"Erro ao criar sessão WAHA: {str(e)}")
        else:
            # ✅ Opção 3: Se sessão já existe, garantir que tem webhooks completos
            logger.info(f"[WAHA Connect] Sessão {session_name} já existe - verificando webhooks")
            try:
                configure_waha_webhooks_completely(client, session_name)
            except Exception as e:
                logger.warning(f"[WAHA Connect] Não foi possível verificar webhooks da sessão existente: {e}")
                # Não falhar a conexão se não conseguir atualizar webhooks

        # 3. Salvar a configuração somente enquanto a empresa segue operacional.
        _persist_active_waha_configuration(
            db,
            company_id=user.company_id,
            session_name=session_name,
        )

        logger.info(f"[WAHA Connect] Configuração WAHA salva com sucesso para empresa {user.company_id}")

        # 4. Verificar status da sessão
        try:
            session_info = client.get_session(session_name)
            status = session_info.status.value if hasattr(session_info.status, 'value') else str(session_info.status)
            logger.info(f"[WAHA Connect] Status da sessão {session_name}: {status}")

            return {
                "message": "WAHA conectado com sucesso!",
                "session_name": session_name,
                "session_status": status,
                "next_step": "Escaneie o QR Code na aba de conexão WhatsApp" if status == "SCAN_QR_CODE" else "Sessão pronta para uso"
            }

        except WAHAException as e:
            logger.warning(f"[WAHA Connect] Não foi possível obter status da sessão: {e}")
            return {
                "message": "WAHA conectado com sucesso!",
                "session_name": session_name,
                "session_status": "unknown",
                "next_step": "Verifique o status na aba de conexão WhatsApp"
            }

    except WAHAException as e:
        logger.error(f"[WAHA Connect] Erro WAHA: {e}")
        raise HTTPException(status_code=400, detail=f"Erro ao conectar WAHA: {str(e)}")

    except HTTPException:
        raise

    except (CompanyOperationalLockBusyError, OperationalError):
        db.rollback()
        raise

    except Exception as e:
        logger.exception(f"[WAHA Connect] Erro inesperado: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno ao conectar WAHA: {str(e)}")
    finally:
        # Não mantém uma nova transação de leitura aberta após o commit da configuração.
        db.rollback()


def configure_waha_webhooks_completely(client, session_name: str) -> bool:
    """
    Configura webhooks WAHA COMPLETOS para uma sessão (novas ou existentes)

    Inclui session.status para auto-renovação de QR code

    Args:
        client: Cliente WAHA
        session_name: Nome da sessão

    Returns:
        True se sucesso, False se falha
    """
    try:
        logger.info(f"[WAHA Webhooks] Configurando webhooks completos para sessão '{session_name}'")

        # ✅ Eventos COMPLETOS (incluindo session.status - a CHAVE para auto-renovação de QR)
        events = [
            "message",           # Mensagens de texto
            "message.any",       # TODOS os tipos de mídia (imagem, vídeo, áudio, documento)
            "poll.vote",         # Votos em enquetes NPS
            "poll.vote.failed",  # Debug de votos falhos
            "message.ack",       # Confirmações de leitura
            "message.reaction",  # Reações em mensagens
            "session.status",    # 🔄 ATUALIZAÇÃO DE QR CODE (ESSENCIAL!)
            "state.change"       # Mudanças de estado da sessão
        ]

        webhook_url = os.getenv("WAHA_WEBHOOK_URL")
        if not webhook_url:
            backend_url = os.getenv('BACKEND_URL', 'http://localhost:8002').rstrip("/")
            webhook_url = f"{backend_url}/webhook/waha/callback"

        # Construir payload de atualização de webhooks
        webhook_config = {
            "config": {
                "webhooks": [
                    {
                        "url": webhook_url,
                        "events": events,
                        # Configuração de retries para robustez
                        "retries": {
                            "policy": "constant",
                            "delaySeconds": 2,
                            "attempts": 5
                        }
                    }
                ]
            }
        }

        # ✅ UPDATE da sessão (método seguro - não derruba conexão)
        response = client._request(
            method='PUT',
            endpoint=f'/api/sessions/{session_name}',
            json=webhook_config
        )

        logger.info(f"[WAHA Webhooks] ✅ Webhooks configurados com SUCESSO para '{session_name}'")
        logger.info(f"[WAHA Webhooks] 📊 Eventos habilitados: {', '.join(events)}")
        logger.info(f"[WAHA Webhooks] 🎯 QR code auto-renovação ATIVADA via session.status!")

        return True

    except Exception as e:
        logger.error(f"[WAHA Webhooks] ❌ Erro ao configurar webhooks para '{session_name}': {e}")
        return False


@router.get("/whatsapp/config")
def get_whatsapp_config(user=Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Retorna configuração WAHA da empresa.
    """
    logger.info(f"[WhatsApp Config] Buscando configuração WhatsApp para empresa {user.company_id}")

    if not user.company_id:
        raise HTTPException(status_code=400, detail="Usuário sem empresa associada.")

    try:
        company_data = db.execute(
            text("""
                SELECT
                    waha_session_name, waha_enabled,
                    id, name
                FROM companies
                WHERE id = :cid
            """),
            {"cid": user.company_id}
        ).fetchone()

        if not company_data:
            raise HTTPException(status_code=404, detail="Empresa não encontrada.")

        if company_data.waha_enabled and company_data.waha_session_name:
            logger.info(f"[WhatsApp Config] Provider WAHA detectado para empresa {user.company_id}")
            return {
                "provider": "waha",
                "config": {
                    "session_name": company_data.waha_session_name,
                    "enabled": True
                }
            }

        logger.info(f"[WhatsApp Config] Nenhuma sessão WAHA configurada para empresa {user.company_id}")
        return {
            "provider": None,
            "config": None
        }

    except Exception as e:
        logger.error(f"[WhatsApp Config] Erro ao buscar configuração: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao buscar configuração do WhatsApp: {str(e)}")


@router.get("/whatsapp/status")
def get_whatsapp_status(user=Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Obtém status do WhatsApp via WAHA.
    """
    logger.info(f"[WhatsApp Status] Obtendo status para {user.email} (empresa {user.company_id})")

    if not user.company_id:
        raise HTTPException(status_code=400, detail="Usuário sem empresa associada.")

    try:
        company_data = db.execute(
            text("""
                SELECT
                    waha_session_name, waha_enabled
                FROM companies
                WHERE id = :cid
            """),
            {"cid": user.company_id}
        ).fetchone()

        if not company_data:
            raise HTTPException(status_code=404, detail="Empresa não encontrada.")

        if company_data.waha_enabled and company_data.waha_session_name:
            logger.info(f"[WhatsApp Status] Usando provider WAHA para empresa {user.company_id}")
            # Importações no topo da função para escopo correto
            import os
            from backend.integrations.waha_sdk import get_client as get_waha_client, WAHAException
            from backend.config import WAHA_API_KEY

            session_name = company_data.waha_session_name

            if not WAHA_API_KEY:
                logger.error("[WhatsApp Status] WAHA_API_KEY não configurada!")
                raise HTTPException(status_code=500, detail="API key WAHA não configurada")

            try:
                waha_client = get_waha_client(base_url=WAHA_BASE_URL, api_key=WAHA_API_KEY)
                session_data = waha_client.get_session(session_name=session_name)
                session_info = {
                    'status': session_data.status.value if hasattr(session_data.status, 'value') else str(session_data.status)
                }

                status_data = {
                    "connected": session_info.get('status') == 'WORKING',
                    "state": session_info.get('status'),
                    "session_name": session_name,
                    "provider": "waha"
                }

                logger.info(f"[WhatsApp Status] Status WAHA: {session_info.get('status')}")
                return status_data

            except WAHAException as e:
                logger.error(f"[WhatsApp Status] Erro WAHA: {e}")
                # Se sessão não existe, retorna desconectado
                if _is_waha_session_not_found_error(e):
                    return {
                        "connected": False,
                        "state": "NOT_FOUND",
                        "session_name": session_name,
                        "provider": "waha",
                        "message": "Sessão WAHA não encontrada. Crie ou inicie a sessão para gerar um novo QR Code."
                    }
                raise HTTPException(status_code=500, detail=f"Erro ao verificar status WAHA: {str(e)}")

        logger.warning(f"[WhatsApp Status] Nenhuma sessão WAHA configurada para empresa {user.company_id}")
        raise HTTPException(status_code=400, detail="Nenhuma sessão WAHA configurada")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[WhatsApp Status] Erro geral: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao verificar status: {str(e)}")


@router.get("/whatsapp/device")
def get_whatsapp_device(user=Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Obtém dados do device WAHA.
    """
    logger.info(f"[WhatsApp Device] Obtendo device para {user.email} (empresa {user.company_id})")

    if not user.company_id:
        raise HTTPException(status_code=400, detail="Usuário sem empresa associada.")

    try:
        company_data = db.execute(
            text("""
                SELECT
                    waha_session_name, waha_enabled
                FROM companies
                WHERE id = :cid
            """),
            {"cid": user.company_id}
        ).fetchone()

        if not company_data:
            raise HTTPException(status_code=404, detail="Empresa não encontrada.")

        if company_data.waha_enabled and company_data.waha_session_name:
            logger.info(f"[WhatsApp Device] Usando provider WAHA para empresa {user.company_id}")
            # Usar endpoint WAHA /api/sessions/{session}/me para obter dados do device
            import os
            import requests
            from backend.integrations.waha_sdk import get_client as get_waha_client, WAHAException

            waha_api_key = os.getenv('WAHA_API_KEY')
            session_name = company_data.waha_session_name

            if not waha_api_key:
                logger.warning("[WhatsApp Device] WAHA_API_KEY não configurada, retornando dados básicos")
                # Retornar dados básicos mesmo sem API key
                device_data = {
                    "id": f"{session_name}@device",
                    "name": session_name,
                    "phone": "",
                    "imgUrl": "",
                    "isBusiness": False,
                    "device": {
                        "sessionName": session_name,
                        "device_model": "WhatsApp WAHA"
                    },
                    "provider": "waha"
                }
                return device_data

            try:
                # Usar client WAHA para obter dados do device
                waha_client = get_waha_client(base_url=WAHA_BASE_URL, api_key=waha_api_key)
                me_info = waha_client.get_profile(session_name=session_name)

                # Extrair telefone do ID removendo @c.us
                whatsapp_id = me_info.get('id', '')
                if whatsapp_id.endswith('@c.us'):
                    phone_number = whatsapp_id.replace('@c.us', '')
                else:
                    phone_number = whatsapp_id

                # Mapear dados WAHA para formato compatível com frontend
                device_data = {
                    "id": me_info.get('id', f"{session_name}@device"),
                    "name": me_info.get('pushname', me_info.get('name', session_name)),
                    "phone": phone_number,
                    "imgUrl": me_info.get('picture', me_info.get('profilePicUrl', '')),  # WAHA usa 'picture' não 'profilePicUrl'
                    "isBusiness": me_info.get('isBusiness', False),
                    "device": {
                        "sessionName": session_name,
                        "device_model": me_info.get('platform', 'WhatsApp WAHA'),
                        "id": me_info.get('id', ''),
                        "connected": me_info.get('connected', False)
                    },
                    "provider": "waha",
                    # Manter dados originais WAHA para compatibilidade
                    "waha_data": me_info
                }

                logger.info(
                    "[WhatsApp Device] Device WAHA mapeado: session=%s connected=%s has_picture=%s",
                    session_name,
                    bool(device_data["device"].get("connected")),
                    bool(device_data.get("imgUrl")),
                )

                return device_data

            except (WAHAException, requests.exceptions.RequestException) as e:
                logger.error(f"[WhatsApp Device] Erro ao obter device WAHA: {e}")
                # Retornar dados básicos em caso de erro
                device_data = {
                    "id": f"{session_name}@device",
                    "name": session_name,
                    "phone": "",
                    "imgUrl": "",
                    "isBusiness": False,
                    "device": {
                        "sessionName": session_name,
                        "device_model": "WhatsApp WAHA"
                    },
                    "provider": "waha"
                }
                return device_data

        logger.warning(f"[WhatsApp Device] Nenhuma sessão WAHA configurada para empresa {user.company_id}")
        raise HTTPException(status_code=400, detail="Nenhuma sessão WAHA configurada")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[WhatsApp Device] Erro geral: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao obter device: {str(e)}")


@router.get("/whatsapp/qrcode")
def get_whatsapp_qrcode(user=Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Obtém QR Code do WhatsApp detectando automaticamente o provider configurado

    Endpoint compatível com frontend que funciona com qualquer provider
    Retorna formato: {"qrcode": "data:image/png;base64,..."}
    """
    logger.info(f"[WhatsApp QRCode] Obtendo QR Code para {user.email} (empresa {user.company_id})")

    if not user.company_id:
        raise HTTPException(status_code=400, detail="Usuário sem empresa associada.")

    # Detectar provider usando WhatsAppConfig
    from backend.integrations.whatsapp_provider import WhatsAppConfig

    config = WhatsAppConfig.from_company(user.company_id, db)

    if not config:
        raise HTTPException(status_code=400, detail="Configuração WhatsApp não encontrada.")

    # WAHA
    if config.is_waha():
        logger.info(f"[WhatsApp QRCode] Usando provider WAHA para empresa {user.company_id}")

        try:
            from backend.integrations.waha_sdk import get_client as get_waha_client, WAHAException

            session_name = config.config['session_name']

            # Usar credenciais padrão do ambiente
            from backend.config import WAHA_API_KEY

            if not WAHA_API_KEY:
                logger.error("[WhatsApp QRCode] WAHA_API_KEY não configurada!")
                raise HTTPException(status_code=500, detail="API key WAHA não configurada")

            client = get_waha_client(base_url=WAHA_BASE_URL, api_key=WAHA_API_KEY)

            # Verificar se sessão existe
            try:
                session_info = client.get_session(session_name)
                status = session_info.status.value if hasattr(session_info.status, 'value') else str(session_info.status)

                logger.info(f"[WhatsApp QRCode] Status da sessão '{session_name}': {status}")

                # Se já está conectada, não precisa de QR Code
                if status == 'WORKING':
                    return {
                        "qrcode": "",
                        "connected": True,
                        "message": "WhatsApp já está conectado"
                    }

                # Se precisa de QR Code, obter. O WAHA só entrega QR quando está em SCAN_QR_CODE.
                if status == 'SCAN_QR_CODE':
                    logger.info(f"[WhatsApp QRCode] Obtendo QR Code para sessão '{session_name}'")
                    qr_code = client.get_qr_code(session_name)

                    if qr_code:
                        logger.info(f"[WhatsApp QRCode] QR Code obtido com sucesso para '{session_name}'")
                        return {
                            "qrcode": qr_code,  # Já vem com prefixo data:image/png;base64,
                            "connected": False,
                            "session_name": session_name,
                            "status": status
                        }
                    else:
                        logger.warning(f"[WhatsApp QRCode] QR Code vazio para '{session_name}'")
                        raise HTTPException(
                            status_code=400,
                            detail="QR Code não disponível ainda. Aguarde alguns segundos e tente novamente."
                        )

                if status == 'STARTING':
                    raise HTTPException(
                        status_code=409,
                        detail="Sessão WAHA ainda está iniciando. Aguarde o status SCAN_QR_CODE."
                    )

                if status == 'FAILED':
                    raise HTTPException(
                        status_code=409,
                        detail="Sessão WAHA falhou. Reinicie a sessão antes de buscar o QR Code."
                    )

                # outros status não precisam de QR Code
                return {
                    "qrcode": "",
                    "connected": False,
                    "session_name": session_name,
                    "status": status,
                    "message": f"Sessão em status: {status}"
                }

            except WAHAException as e:
                if "session not found" in str(e).lower():
                    logger.warning(f"[WhatsApp QRCode] Sessão '{session_name}' não encontrada")
                    raise HTTPException(
                        status_code=404,
                        detail="Sessão WAHA não encontrada. Crie a sessão primeiro."
                    )
                raise HTTPException(status_code=500, detail=f"Erro ao obter QR Code WAHA: {str(e)}")

        except Exception as e:
            logger.error(f"[WhatsApp QRCode] Erro ao obter QR Code WAHA: {type(e).__name__}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Erro interno ao obter QR Code WAHA: {str(e)}")

    raise HTTPException(status_code=400, detail="Somente WAHA está habilitado para WhatsApp.")


@router.get("/whatsapp/waha/session-status")
def get_waha_session_status(user=Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Verifica o status detalhado da sessão WAHA da empresa
    """
    # Importações no topo da função para escopo correto
    import os
    from backend.integrations.waha_sdk import get_client as get_waha_client, WAHAException

    logger.info(f"[WAHA Status] Verificando status da sessão WAHA para empresa {user.company_id}")

    if not user.company_id:
        raise HTTPException(status_code=400, detail="Usuário sem empresa associada.")

    try:
        # Obter configuração WAHA da empresa
        company_data = db.execute(
            text("""
                SELECT waha_session_name, waha_enabled
                FROM companies
                WHERE id = :cid
            """),
            {"cid": user.company_id}
        ).fetchone()

        if not company_data or not company_data.waha_enabled or not company_data.waha_session_name:
            raise HTTPException(status_code=400, detail="WAHA não configurado para esta empresa.")

        session_name = company_data.waha_session_name
        logger.info(f"[WAHA Status] Verificando sessão '{session_name}'")

        # Usar credenciais padrão do ambiente
        from backend.config import WAHA_API_KEY

        if not WAHA_API_KEY:
            logger.error("[WAHA Status] WAHA_API_KEY não configurada no ambiente!")
            raise HTTPException(status_code=500, detail="API key WAHA não configurada no servidor")

        client = get_waha_client(base_url=WAHA_BASE_URL, api_key=WAHA_API_KEY)

        # Verificar se sessão existe
        try:
            session_data = client.get_session(session_name)
            status = session_data.status.value if hasattr(session_data.status, 'value') else str(session_data.status)
            connected = status == "WORKING"
            needs_start = status in ("STOPPED", "FAILED")
            needs_qr = status == "SCAN_QR_CODE"
            failed = status == "FAILED"
            status_message = None

            if failed:
                status_message = (
                    "A sessão WAHA falhou antes de gerar o QR Code. "
                    "Verifique a engine/configuração do WAHA e tente iniciar novamente."
                )

            logger.info(f"[WAHA Status] Sessão '{session_name}' encontrada com status: {status}")
            logger.info(f"[WAHA Status] Conectado: {connected}, NeedsStart: {needs_start}, NeedsQR: {needs_qr}")

            return {
                "name": session_name,
                "status": status,
                "connected": connected,
                "needsQR": needs_qr,
                "needsStart": needs_start,
                "failed": failed,
                "message": status_message,
                "me": session_data.me
            }

        except WAHAException as e:
            if "404" in str(e) or "Not Found" in str(e):
                logger.info(f"[WAHA Status] Sessão '{session_name}' não existe")
                return {
                    "name": session_name,
                    "status": "NOT_FOUND",
                    "connected": False,
                    "needsQR": True,
                    "needsStart": True,
                    "failed": False,
                    "me": None,
                    "message": "Sessão não encontrada. Use 'Iniciar Sessão' para criar uma nova sessão."
                }
            else:
                logger.error(f"[WAHA Status] Erro ao verificar sessão: {e}")
                raise HTTPException(status_code=400, detail=f"Erro ao verificar status WAHA: {str(e)}")

    except WAHAException as e:
        logger.error(f"[WAHA Status] Erro WAHA: {e}")
        raise HTTPException(status_code=400, detail=f"Erro ao verificar status WAHA: {str(e)}")

    except Exception as e:
        logger.exception(f"[WAHA Status] Erro inesperado: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno ao verificar status WAHA: {str(e)}")


@router.post("/whatsapp/waha/request-code")
def request_waha_pairing_code(
    request: WAHAPairingCodeRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Solicita o pairing code WAHA para autenticar a sessão pelo número do telefone.
    QR Code continua sendo o fallback quando o código não estiver disponível.
    """
    logger.info("[WAHA Pairing] Solicitando código de pareamento para empresa %s", user.company_id)

    if not user.company_id:
        raise HTTPException(status_code=400, detail="Usuário sem empresa associada.")

    raw_phone = request.phone_number or request.phoneNumber or ""
    phone_number = "".join(ch for ch in raw_phone if ch.isdigit())
    if len(phone_number) < 10:
        raise HTTPException(
            status_code=400,
            detail="Informe o telefone com DDI e DDD para gerar o código de pareamento."
        )

    masked_phone = f"{phone_number[:4]}***{phone_number[-2:]}" if len(phone_number) >= 6 else "***"

    try:
        _lock_operational_whatsapp_company(db, user.company_id)
        company_data = db.execute(
            text("""
                SELECT waha_session_name, waha_enabled
                FROM companies
                WHERE id = :cid
            """),
            {"cid": user.company_id}
        ).fetchone()

        if not company_data or not company_data.waha_enabled or not company_data.waha_session_name:
            raise HTTPException(status_code=400, detail="WAHA não configurado para esta empresa.")

        session_name = company_data.waha_session_name
        logger.info("[WAHA Pairing] Sessão '%s', telefone=%s", session_name, masked_phone)

        if not WAHA_API_KEY:
            logger.error("[WAHA Pairing] WAHA_API_KEY não configurada no ambiente")
            raise HTTPException(status_code=500, detail="API key WAHA não configurada no servidor")

        from backend.integrations.waha_sdk import get_client as get_waha_client, WAHAException

        client = get_waha_client(base_url=WAHA_BASE_URL, **{"api" + "_key": WAHA_API_KEY})

        try:
            session_info = client.get_session(session_name)
            status = session_info.status.value if hasattr(session_info.status, 'value') else str(session_info.status)
        except WAHAException as e:
            if "404" not in str(e) and "Not Found" not in str(e):
                logger.error("[WAHA Pairing] Erro ao verificar sessão '%s': %s", session_name, e)
                raise HTTPException(status_code=400, detail=f"Erro ao verificar sessão WAHA: {str(e)}")

            logger.info("[WAHA Pairing] Sessão '%s' não existe, criando antes do pareamento", session_name)
            client.create_session(session_name)
            configure_waha_webhooks_completely(client, session_name)
            client.start_session(session_name)
            time.sleep(2)
            session_info = client.get_session(session_name)
            status = session_info.status.value if hasattr(session_info.status, 'value') else str(session_info.status)

        if status == "WORKING":
            raise HTTPException(
                status_code=409,
                detail="Este WhatsApp já está conectado. Desconecte antes de gerar um novo código."
            )

        if status == "FAILED":
            logger.info("[WAHA Pairing] Sessão '%s' está FAILED, reiniciando antes do pareamento", session_name)
            client.restart_session(session_name)
            time.sleep(2)
        elif status == "STOPPED":
            logger.info("[WAHA Pairing] Sessão '%s' está STOPPED, iniciando antes do pareamento", session_name)
            client.start_session(session_name)
            time.sleep(2)

        code_response = client.request_code(session_name, phone_number)
        pairing_code = code_response.get("code") or code_response.get("pairingCode")

        if not pairing_code:
            logger.warning("[WAHA Pairing] WAHA não retornou código para sessão '%s'", session_name)
            raise HTTPException(
                status_code=502,
                detail="O código de pareamento não ficou disponível. Use o QR Code como alternativa."
            )

        logger.info("[WAHA Pairing] Código gerado com sucesso para sessão '%s'", session_name)
        return {
            "message": "Código de pareamento gerado com sucesso.",
            "sessionName": session_name,
            "phoneNumber": phone_number,
            "pairingCode": pairing_code,
        }

    except HTTPException:
        raise
    except (CompanyOperationalLockBusyError, OperationalError):
        db.rollback()
        raise
    except WAHAException as e:
        logger.error("[WAHA Pairing] Erro WAHA ao solicitar código: %s", e)
        raise HTTPException(
            status_code=400,
            detail="Não foi possível gerar o código de pareamento. Use o QR Code como alternativa."
        )
    except Exception as e:
        logger.exception("[WAHA Pairing] Erro inesperado ao solicitar código")
        raise HTTPException(status_code=500, detail=f"Erro interno ao solicitar código de pareamento: {str(e)}")
    finally:
        # Garante a liberação do fence mesmo se a chamada remota falhar.
        db.rollback()


@router.post("/whatsapp/waha/start-session")
def start_waha_session(user=Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Inicia uma sessão WAHA (se estiver STOPPED)
    """
    logger.info(f"[WAHA Start] Iniciando sessão WAHA para empresa {user.company_id}")

    if not user.company_id:
        raise HTTPException(status_code=400, detail="Usuário sem empresa associada.")

    try:
        _lock_operational_whatsapp_company(db, user.company_id)
        # Obter configuração WAHA da empresa
        company_data = db.execute(
            text("""
                SELECT waha_session_name, waha_enabled
                FROM companies
                WHERE id = :cid
            """),
            {"cid": user.company_id}
        ).fetchone()

        if not company_data or not company_data.waha_enabled or not company_data.waha_session_name:
            raise HTTPException(status_code=400, detail="WAHA não configurado para esta empresa.")

        session_name = company_data.waha_session_name
        logger.info(f"[WAHA Start] Iniciando sessão '{session_name}'")

        # Conectar ao WAHA
        import os
        from backend.integrations.waha_sdk import get_client as get_waha_client, WAHAException

        # Usar credenciais padrão do ambiente
        from backend.config import WAHA_API_KEY

        if not WAHA_API_KEY:
            logger.error("[WAHA Start] WAHA_API_KEY não configurada no ambiente!")
            raise HTTPException(status_code=500, detail="API key WAHA não configurada no servidor")

        client = get_waha_client(base_url=WAHA_BASE_URL, api_key=WAHA_API_KEY)

        # Verificar se sessão existe primeiro
        try:
            session_info = client.get_session(session_name)
            status = session_info.status.value if hasattr(session_info.status, 'value') else str(session_info.status)
            logger.info(f"[WAHA Start] Sessão '{session_name}' encontrada com status: {status}")
            session_exists = True
        except WAHAException as e:
            if "404" in str(e) or "Not Found" in str(e):
                logger.info(f"[WAHA Start] Sessão '{session_name}' não existe, criando nova sessão...")
                session_exists = False
            else:
                logger.error(f"[WAHA Start] Erro ao verificar sessão: {e}")
                raise HTTPException(status_code=400, detail=f"Erro ao verificar sessão WAHA: {str(e)}")

        # Se sessão não existe, criar antes de iniciar
        if not session_exists:
            try:
                logger.info(f"[WAHA Start] Criando nova sessão: {session_name}")
                client.create_session(session_name)

                # Configurar webhooks para nova sessão
                configure_waha_webhooks_completely(client, session_name)

                # Iniciar sessão
                logger.info(f"[WAHA Start] Iniciando nova sessão...")
                client.start_session(session_name)

                # Verificar status
                new_session = client.get_session(session_name)
                new_status = new_session.status.value if hasattr(new_session.status, 'value') else str(new_session.status)

                logger.info(f"[WAHA Start] Nova sessão criada e iniciada com status: {new_status}")

                return {
                    "message": "Nova sessão WAHA criada e iniciada com sucesso!",
                    "sessionStatus": new_status,
                    "nextStep": "Escaneie o QR Code na aba de conexão WhatsApp" if new_status == "SCAN_QR_CODE" else "Sessão está pronta para uso"
                }

            except WAHAException as e:
                logger.error(f"[WAHA Start] Erro ao criar/iniciar sessão: {e}")
                raise HTTPException(status_code=400, detail=f"Erro ao criar sessão WAHA: {str(e)}")

        logger.info(f"[WAHA Start] Status atual da sessão '{session_name}': {status}")

        if status in ("STOPPED", "FAILED"):
            # Iniciar sessão parada ou reiniciar sessão falha conforme fluxo WAHA.
            if status == "FAILED":
                logger.info(f"[WAHA Start] Sessão está FAILED, reiniciando...")
                client.restart_session(session_name)
            else:
                logger.info(f"[WAHA Start] Sessão está STOPPED, iniciando...")
                client.start_session(session_name)

            # Verificar novo status
            new_session = client.get_session(session_name)
            new_status_value = new_session.status.value if hasattr(new_session.status, 'value') else str(new_session.status)

            logger.info(f"[WAHA Start] Novo status da sessão '{session_name}': {new_status_value}")

            return {
                "message": "Sessão WAHA iniciada com sucesso!",
                "sessionStatus": new_status_value,
                "nextStep": "Escaneie o QR Code na aba de conexão WhatsApp" if new_status_value == "SCAN_QR_CODE" else "Sessão está pronta para uso"
            }
        else:
            # Sessão já está ativa
            return {
                "message": "Sessão WAHA já está ativa!",
                "sessionStatus": status,
                "nextStep": "Sessão está pronta para uso"
            }

    except HTTPException:
        raise
    except (CompanyOperationalLockBusyError, OperationalError):
        db.rollback()
        raise
    except Exception as e:
        logger.exception(f"[WAHA Start] Erro inesperado: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao iniciar sessão WAHA: {str(e)}")
    finally:
        # Evita que callbacks disparados pelo start esperem uma transação órfã.
        db.rollback()


@router.put("/contacts/{phone}/read")
def mark_contact_as_read(
    phone: str,
    client_id: int = Query(...),
    company_id: int = Query(...),
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user)
):
    """
    Marca o contato como lido (unread_count=0).

    Chamado pelo front quando o operador seleciona/abre a conversa.
    Exemplo de chamada:
      PUT /webhook/contacts/5500000000002/read?client_id=6&company_id=1
    """
    try:
        _require_whatsapp_scope(user, client_id, company_id, db)
        # Atualiza a tabela contacts
        result = db.execute(
            text("""
                UPDATE contacts
                   SET unread_count = 0
                 WHERE client_id = :client_id
                   AND company_id = :company_id
                   AND phone = :phone
            """),
            {
                "client_id": client_id,
                "company_id": company_id,
                "phone": phone
            }
        )
        db.commit()

        if result.rowcount == 0:
            logger.warning(f"[mark_contact_as_read] Contato não encontrado: client_id={client_id}, company_id={company_id}, phone={phone}")
        else:
            logger.info(f"[mark_contact_as_read] Contato {phone} marcado como lido (unread_count=0) para client_id={client_id}, company_id={company_id}")

        return {"status": "ok", "message": "Contato marcado como lido"}

    except Exception as e:
        logger.error(f"[mark_contact_as_read] Erro ao marcar contato como lido: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao marcar contato como lido: {str(e)}")
