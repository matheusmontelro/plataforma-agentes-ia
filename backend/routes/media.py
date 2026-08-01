import logging
import requests
import base64
import subprocess
import tempfile
import hashlib
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from pathlib import Path
import os

from backend.db import get_db
from backend.auth import get_current_user
from backend.models import Message
from backend.runtime_settings import (
    ACCOUNT_PROFILE_PHOTO_DIR,
    MEDIA_BASE_PATH as RUNTIME_MEDIA_BASE_PATH,
)

logger = logging.getLogger(__name__)
media_router = APIRouter()

BASE_MEDIA_DIR = str(RUNTIME_MEDIA_BASE_PATH)
CONVERSION_CACHE_DIR = "/tmp/media_cache"  # Cache para vídeos convertidos
PROFILE_PICTURES_DIR = os.path.join(BASE_MEDIA_DIR, "profile_pictures")
ACCOUNT_PROFILE_PHOTOS_DIR = str(ACCOUNT_PROFILE_PHOTO_DIR)
ACCOUNT_PROFILE_PHOTO_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


@media_router.get("/media/account-profiles/{filename}")
async def get_account_profile_photo(filename: str):
    """
    Serve fotos do perfil da conta master salvas localmente.
    """
    extension = Path(filename).suffix.lower()
    if os.path.basename(filename) != filename or extension not in ACCOUNT_PROFILE_PHOTO_TYPES:
        raise HTTPException(status_code=400, detail="Arquivo de foto inválido")

    photo_dir = Path(ACCOUNT_PROFILE_PHOTOS_DIR)
    safe_base = photo_dir.resolve()
    safe_path = (photo_dir / filename).resolve()

    if not str(safe_path).startswith(f"{safe_base}{os.sep}"):
        raise HTTPException(status_code=403, detail="Acesso negado")

    if not safe_path.exists() or not safe_path.is_file():
        raise HTTPException(status_code=404, detail="Foto de perfil não encontrada")

    return FileResponse(
        str(safe_path),
        media_type=ACCOUNT_PROFILE_PHOTO_TYPES[extension],
        headers={"Cache-Control": "public, max-age=604800"},
    )


@media_router.get("/media/profile-pictures/company_{company_id}/{filename}")
async def get_contact_profile_picture_media(company_id: int, filename: str):
    """
    Serve fotos de perfil do WhatsApp persistidas localmente em WebP.
    """
    if os.path.basename(filename) != filename or not filename.lower().endswith(".webp"):
        raise HTTPException(status_code=400, detail="Arquivo de foto inválido")

    company_dir = Path(PROFILE_PICTURES_DIR) / f"company_{company_id}"
    safe_base = company_dir.resolve()
    safe_path = (company_dir / filename).resolve()

    if not str(safe_path).startswith(f"{safe_base}{os.sep}"):
        raise HTTPException(status_code=403, detail="Acesso negado")

    if not safe_path.exists() or not safe_path.is_file():
        raise HTTPException(status_code=404, detail="Foto de perfil não encontrada")

    return FileResponse(
        str(safe_path),
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=604800"},
    )

@media_router.get("/media/messages/{client_id}/{company_id}/{file_path:path}")
async def get_message_media(
    client_id: int,
    company_id: int,
    file_path: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Endpoint para servir vídeos/imagens/áudios em 3 formatos:
      1) 'data:video/mp4;base64,...'
      2) 'https://...'
      3) 'client_6/company_6/video/...mp4'
    """
    # Primeiramente, checar se user.company_id == company_id
    if user.company_id != company_id:
        raise HTTPException(status_code=403, detail="Acesso negado (empresa incorreta)")

    # Buscar a mensagem no DB que tenha .content == file_path ou algum prefixo
    # Se você usa "file_path" como rota, pode ser que no DB esteja igual ao file_path,
    # ou com prefixo "client_{client_id}/company_{company_id}/..."
    possible_paths = [
        file_path,
        f"client_{client_id}/company_{company_id}/{file_path}"
    ]

    # Filtrar messages do tipo video/audio/image e from_me, se necessário
    message = db.query(Message).filter(
        and_(
            Message.client_id == client_id,
            Message.company_id == company_id,
            Message.content.in_(possible_paths),
            Message.message_type.in_(["video", "audio", "image"])
        )
    ).first()

    if not message:
        raise HTTPException(status_code=404, detail="Mensagem não encontrada no DB")

    # OK, achamos a mensagem. Vamos analisar se .content é data:..., http..., ou local
    content_val = message.content.strip() if message.content else ""
    logger.info(f"[get_message_media] ID={message.id}, content={content_val[:50]}...")

    # 1) Se começar com "data:" => base64 inline
    if content_val.startswith("data:"):
        return serve_base64_inline(content_val)

    # 2) Se começar com "http://" ou "https://" => URL externa
    if content_val.startswith("http://") or content_val.startswith("https://"):
        return serve_external_url(content_val)

    # 3) Caso contrário, assume caminho local
    return serve_local_file(content_val)


@media_router.head("/media/audio/{company_id}/{filename}")
@media_router.get("/media/audio/{company_id}/{filename}")
async def get_agentive_audio(
    company_id: int,
    filename: str
):
    """
    Endpoint para servir arquivos de áudio salvos pelo media_storage.py
    """
    from backend.utils.media_storage import MEDIA_BASE_DIR, AUDIO_DIR

    # Construir caminho completo do arquivo
    company_audio_dir = os.path.join(AUDIO_DIR, f"company_{company_id}")
    file_path = os.path.join(company_audio_dir, filename)

    # Verificar se arquivo existe
    if not os.path.exists(file_path):
        logger.error(f"[get_agentive_audio] Arquivo não encontrado: {file_path}")
        raise HTTPException(status_code=404, detail="Arquivo de áudio não encontrado")

    logger.info(f"[get_agentive_audio] Servindo arquivo: {file_path}")

    # Determinar MIME type baseado na extensão
    if filename.endswith('.mp3'):
        media_type = 'audio/mpeg'
    elif filename.endswith('.webm'):
        media_type = 'audio/webm'
    elif filename.endswith('.wav'):
        media_type = 'audio/wav'
    elif filename.endswith('.ogg'):
        media_type = 'audio/ogg'
    else:
        media_type = 'audio/webm'  # Padrão

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename
    )


@media_router.head("/media/images/company_{company_id}/{filename}")
@media_router.get("/media/images/company_{company_id}/{filename}")
async def get_agentive_image(
    company_id: int,
    filename: str
):
    """
    Endpoint para servir arquivos de imagem salvos pelo media_storage.py
    """
    from backend.utils.media_storage import MEDIA_BASE_DIR, IMAGE_DIR

    # Construir caminho completo do arquivo
    company_image_dir = os.path.join(IMAGE_DIR, f"company_{company_id}")
    file_path = os.path.join(company_image_dir, filename)

    # Verificar se arquivo existe
    if not os.path.exists(file_path):
        logger.error(f"[get_agentive_image] Arquivo não encontrado: {file_path}")
        raise HTTPException(status_code=404, detail="Arquivo de imagem não encontrado")

    logger.info(f"[get_agentive_image] Servindo arquivo: {file_path}")

    # Determinar MIME type baseado na extensão
    if filename.lower().endswith('.jpg') or filename.lower().endswith('.jpeg'):
        media_type = 'image/jpeg'
    elif filename.lower().endswith('.png'):
        media_type = 'image/png'
    elif filename.lower().endswith('.gif'):
        media_type = 'image/gif'
    elif filename.lower().endswith('.webp'):
        media_type = 'image/webp'
    else:
        media_type = 'image/jpeg'  # Padrão

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename
    )


@media_router.head("/media/videos/company_{company_id}/{filename}")
@media_router.get("/media/videos/company_{company_id}/{filename}")
async def get_agentive_video(
    company_id: int,
    filename: str
):
    """
    Endpoint para servir arquivos de vídeo salvos pelo media_storage.py
    """
    from backend.utils.media_storage import MEDIA_BASE_DIR, VIDEO_DIR

    # Construir caminho completo do arquivo
    company_video_dir = os.path.join(VIDEO_DIR, f"company_{company_id}")
    file_path = os.path.join(company_video_dir, filename)

    # Verificar se arquivo existe
    if not os.path.exists(file_path):
        logger.error(f"[get_agentive_video] Arquivo não encontrado: {file_path}")
        raise HTTPException(status_code=404, detail="Arquivo de vídeo não encontrado")

    logger.info(f"[get_agentive_video] Servindo arquivo: {file_path}")

    # Determinar MIME type baseado na extensão
    if filename.lower().endswith('.mp4'):
        media_type = 'video/mp4'
    elif filename.lower().endswith('.avi'):
        media_type = 'video/x-msvideo'
    elif filename.lower().endswith('.mov'):
        media_type = 'video/quicktime'
    elif filename.lower().endswith('.webm'):
        media_type = 'video/webm'
    elif filename.lower().endswith('.mkv'):
        media_type = 'video/x-matroska'
    else:
        media_type = 'video/mp4'  # Padrão

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename
    )


def serve_base64_inline(data_uri: str):
    """
    Decodifica e retorna via StreamingResponse com conversão de formato se necessário.
    """
    import re
    import io

    # Expressão regular melhorada para capturar MIMEs mais complexos como 'audio/webm;codecs=opus'
    match = re.match(r"data:(?P<mime>[^,]+);base64,(?P<data>.+)", data_uri)
    if not match:
        raise HTTPException(status_code=400, detail="Formato base64 inválido")

    mime_type = match.group("mime")
    base64_str = match.group("data")

    # Log para depuração
    logger.info(f"Processando mídia base64: MIME={mime_type}, tamanho={len(base64_str)}")

    try:
        raw_bytes = base64.b64decode(base64_str)
    except Exception as e:
        logger.error(f"Falha ao decodificar base64 inline: {e}")
        raise HTTPException(status_code=400, detail="Base64 corrompido")

    # Para vídeos em formatos problemáticos, converter para MP4
    if mime_type.startswith('video/') and needs_conversion(mime_type):
        logger.info(f"Convertendo vídeo de {mime_type} para MP4")
        converted_data = convert_video_to_mp4(raw_bytes, mime_type)
        return StreamingResponse(io.BytesIO(converted_data), media_type="video/mp4")

    return StreamingResponse(io.BytesIO(raw_bytes), media_type=mime_type)


def serve_external_url(url: str):
    """
    Faz requests.get(url, stream=True) e retorna StreamingResponse com conversão se necessário.
    """
    import requests
    import io

    resp = requests.get(url, stream=True, timeout=30)
    if resp.status_code != 200:
        raise HTTPException(status_code=404, detail=f"Não foi possível obter mídia externa {url}")

    # Content-Type do cabeçalho remoto
    content_type = resp.headers.get("content-type", "application/octet-stream")

    logger.info(f"Processando URL externa: {url}, Content-Type: {content_type}")

    # Para vídeos em formatos problemáticos, baixar e converter
    if content_type.startswith('video/') and needs_conversion(content_type):
        logger.info(f"Convertendo vídeo externo de {content_type} para MP4")

        # Baixar o conteúdo completo
        video_data = resp.content

        # Converter para MP4
        converted_data = convert_video_to_mp4(video_data, content_type)

        return StreamingResponse(io.BytesIO(converted_data), media_type="video/mp4")

    return StreamingResponse(resp.raw, media_type=content_type)


def serve_local_file(path_str: str):
    """
    Retorna o arquivo local do disco usando FileResponse.
    path_str seria algo como 'client_6/company_6/video/xxx.mp4'
    """
    # Montar caminho absoluto
    full_path = os.path.join(BASE_MEDIA_DIR, path_str)
    safe_path = Path(full_path).resolve()

    # Proteção para não ler fora da pasta base
    if not str(safe_path).startswith(BASE_MEDIA_DIR):
        raise HTTPException(status_code=403, detail="Acesso negado")

    if not safe_path.exists():
        raise HTTPException(status_code=404, detail=f"Arquivo não encontrado: {path_str}")

    return FileResponse(str(safe_path))


def needs_conversion(mime_type: str) -> bool:
    """
    Verifica se o formato de vídeo precisa ser convertido para MP4.
    """
    # Formatos que podem ter problemas de compatibilidade
    problematic_formats = [
        'video/webm',
        'video/x-matroska',  # .mkv
        'video/x-msvideo',   # .avi (às vezes)
        'video/quicktime',   # .mov (às vezes)
    ]

    return any(problematic in mime_type.lower() for problematic in problematic_formats)


def get_cache_key(data: bytes, mime_type: str) -> str:
    """
    Gera uma chave de cache baseada no conteúdo e MIME type.
    """
    content_hash = hashlib.md5(data).hexdigest()
    mime_hash = hashlib.md5(mime_type.encode()).hexdigest()
    return f"{content_hash}_{mime_hash}.mp4"


def convert_video_to_mp4(video_data: bytes, input_mime: str) -> bytes:
    """
    Converte vídeo de qualquer formato para MP4/H.264 usando FFmpeg.
    Usa cache para evitar conversões duplicadas.
    """
    try:
        # Criar diretório de cache se não existir
        os.makedirs(CONVERSION_CACHE_DIR, exist_ok=True)

        # Gerar chave de cache
        cache_key = get_cache_key(video_data, input_mime)
        cache_path = os.path.join(CONVERSION_CACHE_DIR, cache_key)

        # Verificar se já existe em cache
        if os.path.exists(cache_path):
            logger.info(f"Usando vídeo cacheado: {cache_key}")
            with open(cache_path, 'rb') as f:
                return f.read()

        # Criar arquivos temporários
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tmp') as input_file:
            input_file.write(video_data)
            input_path = input_file.name

        output_path = cache_path

        logger.info(f"Iniciando conversão de vídeo: {input_mime} -> MP4")

        # Comando FFmpeg para conversão
        cmd = [
            'ffmpeg',
            '-i', input_path,
            '-c:v', 'libx264',      # Codificar vídeo com H.264
            '-c:a', 'aac',          # Codificar áudio com AAC
            '-preset', 'medium',     # Balance entre速度 e qualidade
            '-crf', '23',           # Qualidade padrão (23 = bom balance)
            '-movflags', '+faststart',  # Otimizar para streaming
            '-y',                   # Sobrescrever arquivo de saída
            output_path
        ]

        # Executar FFmpeg
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300  # Timeout de 5 minutos
        )

        # Limpar arquivo temporário
        os.unlink(input_path)

        if result.returncode != 0:
            logger.error(f"FFmpeg falhou: {result.stderr}")
            # Retornar dados originais se conversão falhar
            return video_data

        # Ler arquivo convertido
        with open(output_path, 'rb') as f:
            converted_data = f.read()

        logger.info(f"Conversão concluída: {len(video_data)} -> {len(converted_data)} bytes")
        return converted_data

    except subprocess.TimeoutExpired:
        logger.error("Timeout na conversão de vídeo (300s)")
        return video_data
    except Exception as e:
        logger.error(f"Erro na conversão de vídeo: {e}")
        return video_data
