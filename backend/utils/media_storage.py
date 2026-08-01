"""
Media Storage Utils

Funções para salvar e gerenciar arquivos de mídia (áudio, imagem)
usados no sistema WhatsApp.
"""

import os
import uuid
import tempfile
import logging
from typing import Optional
from datetime import datetime

from backend.runtime_settings import MEDIA_BASE_PATH, PUBLIC_BASE_URL

logger = logging.getLogger(__name__)

# Diretório base para armazenamento de mídia
MEDIA_BASE_DIR = str(MEDIA_BASE_PATH / "generated")
AUDIO_DIR = os.path.join(MEDIA_BASE_DIR, "audio")
IMAGE_DIR = os.path.join(MEDIA_BASE_DIR, "images")
VIDEO_DIR = os.path.join(MEDIA_BASE_DIR, "videos")

# Garantir que diretórios existem
for directory in [MEDIA_BASE_DIR, AUDIO_DIR, IMAGE_DIR, VIDEO_DIR]:
    os.makedirs(directory, exist_ok=True)


def get_media_public_base_url() -> str:
    """Return the public base URL WAHA can use to download locally saved media."""
    explicit_url = os.getenv("WAHA_MEDIA_PUBLIC_BASE_URL") or os.getenv("PUBLIC_BASE_URL")
    if explicit_url:
        return explicit_url.rstrip("/")

    return PUBLIC_BASE_URL


def save_audio_and_get_url(audio_bytes: bytes, filename: Optional[str] = None, company_id: Optional[int] = None, extension: str = "webm") -> tuple[str, str]:
    """
    Salva bytes de áudio e retorna URL para acesso.

    Args:
        audio_bytes: Bytes do arquivo de áudio
        filename: Nome opcional do arquivo
        company_id: ID da empresa (para organização)
        extension: Extensão do arquivo (webm, mp3, wav, etc.)

    Returns:
        tuple: (file_path, url) - caminho completo do arquivo e URL de acesso
    """
    try:
        # Gerar nome único se não fornecido
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_id = str(uuid.uuid4())[:8]
            filename = f"audio_{timestamp}_{unique_id}.{extension}"

        # Criar subdiretório por empresa se company_id fornecido
        if company_id:
            company_audio_dir = os.path.join(AUDIO_DIR, f"company_{company_id}")
            os.makedirs(company_audio_dir, exist_ok=True)
            filepath = os.path.join(company_audio_dir, filename)
        else:
            filepath = os.path.join(AUDIO_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(audio_bytes)

        logger.info(f"[MediaStorage] Áudio salvo: {filepath} ({len(audio_bytes)} bytes)")

        # Retornar path completo e URL de acesso completa
        # WAHA precisa de URL absoluta para acessar o arquivo
        if company_id:
            relative_url = f"/media/audio/{company_id}/{filename}"
        else:
            relative_url = f"/media/audio/{filename}"

        # URL absoluta que WAHA pode acessar
        backend_url = get_media_public_base_url()
        absolute_url = f"{backend_url}{relative_url}"

        return filepath, absolute_url

    except Exception as e:
        logger.error(f"[MediaStorage] Erro ao salvar áudio: {e}")
        raise

def save_image_and_get_url(image_bytes: bytes, filename: Optional[str] = None, company_id: Optional[int] = None, extension: str = "jpg") -> tuple[str, str]:
    """
    Salva bytes de imagem e retorna URL para acesso.

    Args:
        image_bytes: Bytes do arquivo de imagem
        filename: Nome opcional do arquivo
        company_id: ID da empresa (para organização)
        extension: Extensão do arquivo (jpg, png, webp, etc.)

    Returns:
        tuple: (file_path, url) - caminho completo do arquivo e URL de acesso
    """
    try:
        # Gerar nome único se não fornecido
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_id = str(uuid.uuid4())[:8]
            filename = f"image_{timestamp}_{unique_id}.{extension}"

        # Criar subdiretório por empresa se company_id fornecido
        if company_id:
            company_image_dir = os.path.join(IMAGE_DIR, f"company_{company_id}")
            os.makedirs(company_image_dir, exist_ok=True)
            filepath = os.path.join(company_image_dir, filename)
        else:
            filepath = os.path.join(IMAGE_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(image_bytes)

        logger.info(f"[MediaStorage] Imagem salva: {filepath} ({len(image_bytes)} bytes)")

        # Retornar path completo e URL de acesso completa
        if company_id:
            relative_url = f"/media/images/company_{company_id}/{filename}"
        else:
            relative_url = f"/media/images/{filename}"

        # URL absoluta que WAHA pode acessar
        backend_url = get_media_public_base_url()
        absolute_url = f"{backend_url}{relative_url}"

        return filepath, absolute_url

    except Exception as e:
        logger.error(f"[MediaStorage] Erro ao salvar imagem: {e}")
        raise

def cleanup_old_media(max_age_hours: int = 24):
    """
    Limpa arquivos de mídia antigos.

    Args:
        max_age_hours: Idade máxima em horas para manter arquivos
    """
    import time

    try:
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600

        for directory in [AUDIO_DIR, IMAGE_DIR, VIDEO_DIR]:
            for filename in os.listdir(directory):
                filepath = os.path.join(directory, filename)
                file_age = current_time - os.path.getctime(filepath)

                if file_age > max_age_seconds:
                    os.remove(filepath)
                    logger.info(f"[MediaStorage] Arquivo antigo removido: {filepath}")

    except Exception as e:
        logger.error(f"[MediaStorage] Erro ao limpar mídia antiga: {e}")


def save_video_and_get_url(video_bytes: bytes, filename: Optional[str] = None, company_id: Optional[int] = None, extension: str = "mp4") -> tuple[str, str]:
    """
    Salva bytes de vídeo e retorna URL para acesso.

    Args:
        video_bytes: Bytes do arquivo de vídeo
        filename: Nome opcional do arquivo
        company_id: ID da empresa (para organização)
        extension: Extensão do arquivo (mp4, avi, mov, etc.)

    Returns:
        tuple: (file_path, url) - caminho completo do arquivo e URL de acesso
    """
    try:
        # Gerar nome único se não fornecido
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_id = str(uuid.uuid4())[:8]
            filename = f"video_{timestamp}_{unique_id}.{extension}"

        # Criar subdiretório por empresa se company_id fornecido
        if company_id:
            company_video_dir = os.path.join(VIDEO_DIR, f"company_{company_id}")
            os.makedirs(company_video_dir, exist_ok=True)
            filepath = os.path.join(company_video_dir, filename)
        else:
            filepath = os.path.join(VIDEO_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(video_bytes)

        logger.info(f"[MediaStorage] Vídeo salvo: {filepath} ({len(video_bytes)} bytes)")

        # Retornar path completo e URL de acesso completa
        if company_id:
            relative_url = f"/media/videos/company_{company_id}/{filename}"
        else:
            relative_url = f"/media/videos/{filename}"

        # URL absoluta que WAHA pode acessar
        backend_url = get_media_public_base_url()
        absolute_url = f"{backend_url}{relative_url}"

        return filepath, absolute_url

    except Exception as e:
        logger.error(f"[MediaStorage] Erro ao salvar vídeo: {e}")
        raise
