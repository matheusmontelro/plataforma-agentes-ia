# backend/integrations/waha_utils.py

import os
import requests
import logging
import base64
import hashlib
import io
from pathlib import Path
from typing import Dict, Any, Optional
from urllib.parse import urlparse
from fastapi import HTTPException
from dotenv import load_dotenv
from PIL import Image, ImageOps, UnidentifiedImageError

from backend.runtime_settings import MEDIA_BASE_PATH, app_user_agent

logger = logging.getLogger(__name__)

# Configuração WAHA
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
WAHA_BASE_URL = os.getenv("WAHA_BASE_URL", "http://localhost:3000")
WAHA_API_KEY = os.getenv("WAHA_API_KEY", "")

PROFILE_PICTURE_DIR = os.getenv(
    "WAHA_PROFILE_PICTURE_DIR",
    str(MEDIA_BASE_PATH / "profile_pictures"),
)
PROFILE_PICTURE_PUBLIC_PREFIX = "/media/profile-pictures"
WHATSAPP_PROFILE_PICTURE_HOST = "pps.whatsapp.net"
MAX_PROFILE_PICTURE_BYTES = 5 * 1024 * 1024
PROFILE_PICTURE_MAX_DIMENSION = 256
PROFILE_PICTURE_WEBP_QUALITY = 80


def _post_for_operational_company(
    company_id: int,
    url: str,
    *,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout: int,
):
    """Serialize a WAHA side effect with company state changes."""
    from backend.db import SessionLocal
    from backend.services.company_access_control import (
        CompanyOperationallyBlockedError,
        ensure_company_operational,
        lock_entities_for_mutation,
    )

    db = SessionLocal()
    try:
        lock_entities_for_mutation(db, company_ids=[company_id])
        ensure_company_operational(db, company_id)
        return requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout,
        )
    except CompanyOperationallyBlockedError as exc:
        raise HTTPException(
            status_code=423,
            detail="Acesso da empresa suspenso",
        ) from exc
    finally:
        rollback = getattr(db, "rollback", None)
        try:
            if callable(rollback):
                rollback()
        finally:
            db.close()


def send_text_to_waha(
    waha_session_name: str,
    phone: str,
    message: str,
    company_id: int
) -> Dict[str, Any]:
    """
    Envia mensagem de texto via WAHA

    Modelado em: send_text_to_zapi() de zapi_utils.py
    WAHA OpenAPI: POST /api/sendText (MessageTextRequest)

    Args:
        waha_session_name: Nome da sessão WAHA (ex: "default")
        phone: Telefone (5500000000004)
        message: Texto da mensagem
        company_id: ID da empresa (para logs)

    Returns:
        Response JSON da WAHA com ID da mensagem

    Example:
        >>> send_text_to_waha("default", "5500000000004", "Olá!", 68)
        {'id': 'false_5500900000005@c.us_ABC123...'}
    """
    url = f"{WAHA_BASE_URL}/api/sendText"
    headers = {
        "X-Api-Key": WAHA_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # Converter phone para chatId (adicionar @c.us se necessário)
    # Aceitar também @lid (canais/empresas do WhatsApp)
    if phone.endswith("@c.us") or phone.endswith("@lid"):
        chat_id = phone
    else:
        chat_id = f"{phone}@c.us"

    payload = {
        "session": waha_session_name,
        "chatId": chat_id,
        "text": message,
        "linkPreview": True,
        "linkPreviewHighQuality": True,
    }

    logger.info(f"[WAHA] Enviando texto para {chat_id} (company {company_id})")
    logger.info(f"[WAHA] URL: {url}, Payload: {payload}")

    try:
        response = _post_for_operational_company(
            company_id,
            url,
            headers=headers,
            payload=payload,
            timeout=30,
        )
        logger.info(f"[WAHA] Status code send-text: {response.status_code}, response: {response.text}")

        if response.status_code not in (200, 201):
            logger.error(f"[WAHA] Falha ao enviar texto: {response.text}")
            raise HTTPException(
                status_code=400,
                detail=f"Falha ao enviar mensagem via WAHA: {response.text}"
            )

        return response.json()

    except requests.exceptions.Timeout as e:
        logger.error(f"[WAHA] Timeout ao enviar texto para {chat_id}: {e}")
        raise HTTPException(status_code=408, detail="Timeout ao enviar mensagem via WAHA")

    except requests.exceptions.RequestException as e:
        logger.error(f"[WAHA] Erro na requisição: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao enviar mensagem via WAHA: {str(e)}")


def send_audio_to_waha(
    waha_session_name: str,
    phone: str,
    audio_bytes: bytes,
    company_id: int
) -> Dict[str, Any]:
    """
    Envia áudio via WAHA

    Modelado em: send_audio_to_zapi() de zapi_utils.py
    WAHA OpenAPI: POST /api/sendVoice (MessageVoiceRequest + VoiceBinaryFile)

    IMPORTANTE: Formato do áudio difere do Z-API:
    - Z-API: "audio": "data:audio/mpeg;base64,ABC..." (COM prefixo)
    - WAHA: "data": "ABC..." (SEM prefixo) + campos separados

    Args:
        waha_session_name: Nome da sessão WAHA
        phone: Telefone (5500000000004)
        audio_bytes: Bytes do áudio (MP3 ou OGG)
        company_id: ID da empresa (para logs)

    Returns:
        Response JSON da WAHA

    Example:
        >>> with open("audio.mp3", "rb") as f:
        ...     audio_data = f.read()
        >>> send_audio_to_waha("default", "5500000000004", audio_data, 68)
        {'id': 'false_5500900000005@c.us_XYZ456...'}
    """
    url = f"{WAHA_BASE_URL}/api/sendVoice"
    headers = {
        "X-Api-Key": WAHA_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # Converter para base64 SEM prefixo (diferente do Z-API!)
    audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')

    # Chat ID com sufixo
    # Aceitar também @lid (canais/empresas do WhatsApp)
    if phone.endswith("@c.us") or phone.endswith("@lid"):
        chat_id = phone
    else:
        chat_id = f"{phone}@c.us"

    # Payload seguindo VoiceBinaryFile schema do OpenAPI.json
    # 🎯 Formato correto conforme documentação WAHA: "mimetype": "audio/ogg; codecs=opus"
    payload = {
        "session": waha_session_name,
        "chatId": chat_id,
        "file": {
            "mimetype": "audio/ogg; codecs=opus",
            "filename": "voice-message.opus",
            "data": audio_base64  # SEM prefixo data:audio/ogg;base64,
        },
        "convert": True  # Converter formato automaticamente
    }

    logger.info(f"[WAHA] Enviando áudio para {chat_id} (company {company_id})")
    logger.info(f"[WAHA] Tamanho do áudio: {len(audio_bytes)} bytes")
    logger.info(f"[WAHA] Payload (truncated): {str(payload)[:200]}...")

    try:
        response = _post_for_operational_company(
            company_id,
            url,
            headers=headers,
            payload=payload,
            timeout=60,
        )
        logger.info(f"[WAHA] Status code send-audio: {response.status_code}, response: {response.text}")

        if response.status_code not in (200, 201):
            logger.error(f"[WAHA] Falha ao enviar áudio: {response.text}")
            raise HTTPException(
                status_code=400,
                detail=f"Falha ao enviar áudio via WAHA: {response.text}"
            )

        return response.json()

    except requests.exceptions.Timeout as e:
        logger.error(f"[WAHA] Timeout ao enviar áudio para {chat_id}: {e}")
        raise HTTPException(status_code=408, detail="Timeout ao enviar áudio via WAHA")

    except requests.exceptions.RequestException as e:
        logger.error(f"[WAHA] Erro na requisição: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao enviar áudio via WAHA: {str(e)}")


def get_contact_profile_picture(
    waha_session_name: str,
    phone: str,
    refresh: bool = False
) -> str:
    """
    Busca URL da foto de perfil do contato via WAHA

    WAHA API: GET /api/contacts/profile-picture

    Args:
        waha_session_name: Nome da sessão WAHA (ex: "default")
        phone: Telefone do contato (5500000000004) ou chatId (5500000000004@c.us)
        refresh: Se True, força refresh do cache (default 24h). Use com cuidado para evitar rate limit.

    Returns:
        URL da foto de perfil ou string vazia se não disponível

    Example:
        >>> get_contact_profile_picture("default", "5500000000004")
        'https://pps.whatsapp.net/v/t61.24694-24/...'
    """
    url = f"{WAHA_BASE_URL}/api/contacts/profile-picture"
    headers = {
        "X-Api-Key": WAHA_API_KEY,
        "Accept": "application/json"
    }

    # Converter phone para chatId se necessário
    if phone.endswith("@c.us") or phone.endswith("@lid"):
        contact_id = phone
    else:
        contact_id = f"{phone}@c.us"

    params = {
        "contactId": contact_id,
        "session": waha_session_name,
        "refresh": str(refresh).lower()
    }

    logger.debug(f"[WAHA] Buscando foto de perfil para {contact_id}")

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()
            profile_url = data.get("profilePictureURL", "")

            if profile_url:
                logger.info(f"[WAHA] Foto de perfil encontrada para {contact_id}")
                return profile_url
            else:
                logger.info(f"[WAHA] Foto de perfil não disponível para {contact_id} (privacidade ou sem foto)")
                return ""
        else:
            logger.warning(f"[WAHA] Erro ao buscar foto de perfil ({response.status_code}): {response.text}")
            return ""

    except requests.exceptions.Timeout:
        logger.warning(f"[WAHA] Timeout ao buscar foto de perfil para {contact_id}")
        return ""

    except requests.exceptions.RequestException as e:
        logger.warning(f"[WAHA] Erro ao buscar foto de perfil para {contact_id}: {e}")
        return ""

    except Exception as e:
        logger.error(f"[WAHA] Erro inesperado ao buscar foto de perfil: {e}")
        return ""


def is_local_profile_picture_url(photo_url: Optional[str]) -> bool:
    """
    Retorna True quando a foto ja aponta para a copia WebP local.
    """
    return bool(
        photo_url
        and photo_url.startswith(f"{PROFILE_PICTURE_PUBLIC_PREFIX}/")
        and photo_url.lower().endswith(".webp")
    )


def is_whatsapp_profile_picture_url(photo_url: Optional[str]) -> bool:
    """
    Retorna True para URLs temporarias/protegidas de foto do WhatsApp.
    """
    if not photo_url:
        return False

    try:
        hostname = urlparse(photo_url).hostname or ""
    except ValueError:
        return False

    return (
        hostname == WHATSAPP_PROFILE_PICTURE_HOST
        or hostname.endswith(f".{WHATSAPP_PROFILE_PICTURE_HOST}")
    )


def should_refresh_contact_profile_picture(existing_photo: Optional[str]) -> bool:
    """
    Forca refresh somente quando a foto atual e uma URL externa instavel.
    """
    return (
        bool(existing_photo)
        and not is_local_profile_picture_url(existing_photo)
        and is_whatsapp_profile_picture_url(existing_photo)
    )


def _download_profile_picture_bytes(profile_url: str) -> bytes:
    """
    Baixa a foto remota com limite de tamanho para evitar consumo excessivo.
    """
    try:
        response = requests.get(
            profile_url,
            headers={"User-Agent": app_user_agent("waha-profile")},
            stream=True,
            timeout=15,
        )

        if response.status_code != 200:
            logger.warning(
                "[WAHA] Falha ao baixar foto de perfil: status=%s",
                response.status_code,
            )
            return b""

        content_type = response.headers.get("content-type", "")
        if content_type and not content_type.lower().startswith("image/"):
            logger.warning(
                "[WAHA] Foto de perfil retornou content-type inesperado: %s",
                content_type,
            )
            return b""

        chunks = []
        total_size = 0
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue

            total_size += len(chunk)
            if total_size > MAX_PROFILE_PICTURE_BYTES:
                logger.warning(
                    "[WAHA] Foto de perfil excedeu limite de %s bytes",
                    MAX_PROFILE_PICTURE_BYTES,
                )
                return b""

            chunks.append(chunk)

        return b"".join(chunks)

    except requests.exceptions.Timeout:
        logger.warning("[WAHA] Timeout ao baixar foto de perfil")
        return b""
    except requests.exceptions.RequestException as exc:
        logger.warning("[WAHA] Erro ao baixar foto de perfil: %s", exc)
        return b""


def _convert_profile_picture_to_webp(image_bytes: bytes) -> bytes:
    """
    Converte qualquer imagem suportada pelo Pillow para WebP pequeno.
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail(
                (PROFILE_PICTURE_MAX_DIMENSION, PROFILE_PICTURE_MAX_DIMENSION),
                Image.Resampling.LANCZOS,
            )

            if image.mode in ("RGBA", "LA") or (
                image.mode == "P" and "transparency" in image.info
            ):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")

            output = io.BytesIO()
            image.save(
                output,
                format="WEBP",
                quality=PROFILE_PICTURE_WEBP_QUALITY,
                method=6,
            )
            return output.getvalue()

    except UnidentifiedImageError:
        logger.warning("[WAHA] Foto de perfil baixada nao e uma imagem valida")
        return b""
    except Exception as exc:
        logger.warning("[WAHA] Erro ao converter foto de perfil para WebP: %s", exc)
        return b""


def persist_contact_profile_picture_as_webp(
    waha_session_name: str,
    phone: str,
    company_id: int,
    refresh: bool = False,
    existing_photo: Optional[str] = None,
) -> str:
    """
    Busca a foto do contato na WAHA, baixa a imagem e persiste uma copia WebP local.

    Retorna a URL relativa servida pelo backend, ou string vazia quando nao houver
    foto disponivel ou a persistencia falhar.
    """
    if is_local_profile_picture_url(existing_photo):
        return existing_photo or ""

    profile_url = get_contact_profile_picture(
        waha_session_name=waha_session_name,
        phone=phone,
        refresh=refresh,
    )
    if not profile_url:
        return ""

    image_bytes = _download_profile_picture_bytes(profile_url)
    if not image_bytes:
        return ""

    webp_bytes = _convert_profile_picture_to_webp(image_bytes)
    if not webp_bytes:
        return ""

    try:
        phone_hash = hashlib.sha256(f"{company_id}:{phone}".encode("utf-8")).hexdigest()[:24]
        filename = f"contact_{phone_hash}.webp"
        company_dir = Path(PROFILE_PICTURE_DIR) / f"company_{company_id}"
        company_dir.mkdir(parents=True, exist_ok=True)

        file_path = company_dir / filename
        tmp_path = company_dir / f".{filename}.tmp"
        with open(tmp_path, "wb") as file:
            file.write(webp_bytes)
        os.replace(tmp_path, file_path)

        logger.info(
            "[WAHA] Foto de perfil persistida em WebP: company_id=%s, bytes=%s",
            company_id,
            len(webp_bytes),
        )
        return f"{PROFILE_PICTURE_PUBLIC_PREFIX}/company_{company_id}/{filename}"

    except Exception as exc:
        logger.warning("[WAHA] Erro ao persistir foto de perfil WebP: %s", exc)
        return ""


def send_image_to_waha(
    waha_session_name: str,
    phone: str,
    image_bytes: bytes,
    mime_type: str,
    company_id: int,
    caption: str = None
) -> Dict[str, Any]:
    """
    Envia imagem via WAHA

    WAHA OpenAPI: POST /api/sendImage
    """
    url = f"{WAHA_BASE_URL}/api/sendImage"
    headers = {
        "X-Api-Key": WAHA_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # Converter para base64 SEM prefixo
    image_base64 = base64.b64encode(image_bytes).decode('utf-8')

    if phone.endswith("@c.us") or phone.endswith("@lid"):
        chat_id = phone
    else:
        chat_id = f"{phone}@c.us"

    payload = {
        "session": waha_session_name,
        "chatId": chat_id,
        "file": {
            "mimetype": mime_type,
            "filename": "image.jpg", # Nome genérico, WAHA lida bem
            "data": image_base64
        }
    }

    if caption:
        payload["caption"] = caption

    logger.info(f"[WAHA] Enviando imagem para {chat_id} (company {company_id})")

    try:
        response = _post_for_operational_company(
            company_id,
            url,
            headers=headers,
            payload=payload,
            timeout=60,
        )

        if response.status_code not in (200, 201):
            logger.error(f"[WAHA] Falha ao enviar imagem: {response.text}")
            raise HTTPException(
                status_code=400,
                detail=f"Falha ao enviar imagem via WAHA: {response.text}"
            )

        return response.json()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[WAHA] Erro ao enviar imagem: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao enviar imagem via WAHA: {str(e)}")


def send_video_to_waha(
    waha_session_name: str,
    phone: str,
    video_bytes: bytes,
    mime_type: str,
    company_id: int,
    caption: str = None
) -> Dict[str, Any]:
    """
    Envia vídeo via WAHA

    WAHA OpenAPI: POST /api/sendVideo
    """
    url = f"{WAHA_BASE_URL}/api/sendVideo"
    headers = {
        "X-Api-Key": WAHA_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # Converter para base64 SEM prefixo
    video_base64 = base64.b64encode(video_bytes).decode('utf-8')

    if phone.endswith("@c.us") or phone.endswith("@lid"):
        chat_id = phone
    else:
        chat_id = f"{phone}@c.us"

    payload = {
        "session": waha_session_name,
        "chatId": chat_id,
        "file": {
            "mimetype": mime_type,
            "filename": "video.mp4",
            "data": video_base64
        }
    }

    if caption:
        payload["caption"] = caption

    logger.info(f"[WAHA] Enviando vídeo para {chat_id} (company {company_id})")

    try:
        response = _post_for_operational_company(
            company_id,
            url,
            headers=headers,
            payload=payload,
            timeout=120,
        )

        if response.status_code not in (200, 201):
            logger.error(f"[WAHA] Falha ao enviar vídeo: {response.text}")
            raise HTTPException(
                status_code=400,
                detail=f"Falha ao enviar vídeo via WAHA: {response.text}"
            )

        return response.json()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[WAHA] Erro ao enviar vídeo: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao enviar vídeo via WAHA: {str(e)}")


def check_number_exists(
    waha_session_name: str,
    phone: str
) -> str:
    """
    Verifica se o número existe no WhatsApp via WAHA e retorna o chatId correto.
    Útil quando o envio falha com 'no LID found' devido a formatação incorreta (ex: 9º dígito).

    WAHA API: GET /api/contacts/check-exists
    """
    url = f"{WAHA_BASE_URL}/api/contacts/check-exists"
    headers = {
        "X-Api-Key": WAHA_API_KEY,
        "Accept": "application/json"
    }

    params = {
        "session": waha_session_name,
        "phone": phone
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)

        if response.status_code == 200:
            data = response.json()
            # {"numberExists": true, "chatId": "550000000014@c.us"}
            if data.get("numberExists"):
                return data.get("chatId")

        logger.warning(f"[WAHA] Check exists falhou ou número desconhecido para {phone}: {response.text}")
        return None

    except Exception as e:
        logger.error(f"[WAHA] Erro ao verificar existência do número {phone}: {e}")
        return None
