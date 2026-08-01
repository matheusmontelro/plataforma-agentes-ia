# backend/routes/waha_media.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.responses import Response
import logging
import os
import glob
import mimetypes
import tempfile
import subprocess
import hashlib
import requests
import io

from backend.runtime_settings import MEDIA_BASE_PATH

logger = logging.getLogger(__name__)
router = APIRouter()

CONVERSION_CACHE_DIR = "/tmp/waha_media_cache"  # Cache separado para WAHA
MEDIA_ROOT_DIR = str(MEDIA_BASE_PATH)
WAHA_MEDIA_DIR = os.getenv("WAHA_MEDIA_DIR", os.path.join(MEDIA_ROOT_DIR, "waha"))


def _normalize_waha_media_path(waha_path: str) -> str:
    parts = [part for part in (waha_path or "").split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise HTTPException(status_code=400, detail="Caminho de mídia inválido")
    return "/".join(parts)


def _build_waha_file_url(waha_path: str) -> str:
    from backend.config import WAHA_BASE_URL

    return f"{WAHA_BASE_URL.rstrip('/')}/api/files/{waha_path.lstrip('/')}"

def needs_conversion(mime_type: str) -> bool:
    """
    Verifica se o formato de vídeo precisa ser convertido para MP4.
    """
    problematic_formats = [
        'video/webm',
        'video/x-matroska',  # .mkv
        'video/x-msvideo',   # .avi
        'video/quicktime',   # .mov
    ]
    return any(problematic in mime_type.lower() for problematic in problematic_formats)

def get_cache_key(file_path: str) -> str:
    """
    Gera chave de cache baseada no arquivo e timestamp de modificação.
    """
    try:
        stat = os.stat(file_path)
        content_hash = hashlib.md5(f"{file_path}_{stat.st_mtime}_{stat.st_size}".encode()).hexdigest()
        return f"waha_{content_hash}.mp4"
    except:
        import random
        return f"waha_{random.randint(1000000, 9999999)}.mp4"

def convert_video_to_mp4(input_path: str, mime_type: str) -> str:
    """
    Converte vídeo para MP4 e retorna caminho do arquivo convertido.
    """
    try:
        os.makedirs(CONVERSION_CACHE_DIR, exist_ok=True)

        cache_key = get_cache_key(input_path)
        cache_path = os.path.join(CONVERSION_CACHE_DIR, cache_key)

        # Verificar cache
        if os.path.exists(cache_path):
            logger.info(f"[WAHA Media] Usando vídeo cacheado: {cache_key}")
            return cache_path

        output_path = cache_path
        logger.info(f"[WAHA Media] Convertendo vídeo: {input_path} -> MP4")

        # Comando FFmpeg
        cmd = [
            'ffmpeg',
            '-i', input_path,
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-preset', 'medium',
            '-crf', '23',
            '-movflags', '+faststart',
            '-y',
            output_path
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode != 0:
            logger.error(f"[WAHA Media] FFmpeg falhou: {result.stderr}")
            return input_path  # Retorna original se falhar

        logger.info(f"[WAHA Media] Conversão concluída: {cache_path}")
        return cache_path

    except subprocess.TimeoutExpired:
        logger.error("[WAHA Media] Timeout na conversão (300s)")
        return input_path
    except Exception as e:
        logger.error(f"[WAHA Media] Erro na conversão: {e}")
        return input_path

@router.get("/media/{waha_path:path}")
@router.head("/media/{waha_path:path}")
async def serve_waha_media(waha_path: str):
    """
    Serve mídias do WAHA diretamente do filesystem

    URL: /api/waha/media/sessao-exemplo/A515E2CD1D350ACFA4A609BB052687BD.jpeg
    Busca o arquivo no diretório WAHA configurado para a instalação.
    """
    try:
        safe_waha_path = _normalize_waha_media_path(waha_path)
        filename = os.path.basename(safe_waha_path)
        first_segment = safe_waha_path.split("/", 1)[0]

        logger.info("[WAHA Media] Servindo arquivo: path_present=%s filename=%s", bool(safe_waha_path), filename)

        # Base directory para WAHA media
        base_dir = WAHA_MEDIA_DIR

        # 🔥 CORREÇÃO: Busca mais flexível para encontrar arquivos
        matching_files = []

        # 1. Se username parece ser um ID de empresa (company_X), buscar diretamente nessa pasta
        if first_segment.startswith('company_'):
            direct_path = os.path.join(base_dir, first_segment)
            if os.path.isdir(direct_path):
                search_pattern = f"{direct_path}/*{glob.escape(filename)}*"
                matching_files = glob.glob(search_pattern)
                logger.info(f"[WAHA Media] Busca direta em {first_segment}: encontrou {len(matching_files)} arquivos")

        # 2. Se não encontrou, buscar em todas as pastas company_*
        if not matching_files:
            search_pattern = f"{base_dir}/company_*/*{glob.escape(filename)}*"
            matching_files = glob.glob(search_pattern)
            logger.info(f"[WAHA Media] Busca em company_*: encontrou {len(matching_files)} arquivos")

        # 3. Se ainda não encontrou, buscar recursivamente em qualquer subpasta
        if not matching_files:
            search_pattern = f"{base_dir}/**/*{glob.escape(filename)}*"
            matching_files = glob.glob(search_pattern, recursive=True)
            logger.info(f"[WAHA Media] Busca recursiva: encontrou {len(matching_files)} arquivos")

        # 4. Tentar buscar pelo nome exato do arquivo (sem glob pattern)
        if not matching_files:
            # Verificar se filename é um nome de arquivo completo
            for company_dir in glob.glob(f"{base_dir}/company_*"):
                exact_path = os.path.join(company_dir, filename)
                if os.path.exists(exact_path):
                    matching_files = [exact_path]
                    logger.info(f"[WAHA Media] Encontrado por nome exato: {exact_path}")
                    break

        if not matching_files:
            logger.warning(f"[WAHA Media] Nenhum arquivo encontrado localmente para: {filename}")
            # Tentar buscar do WAHA diretamente
            return fetch_from_waha_directly(safe_waha_path)

        # Usar o primeiro arquivo encontrado
        file_path = matching_files[0]
        logger.info(f"[WAHA Media] Arquivo encontrado: {file_path}")

        # Verificar se é um arquivo
        if not os.path.isfile(file_path):
            logger.error(f"[WAHA Media] Caminho não é um arquivo: {file_path}")
            raise HTTPException(
                status_code=404,
                detail="Arquivo não encontrado"
            )

        # Determinar MIME type
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = "application/octet-stream"

        logger.info(f"[WAHA Media] MIME type detectado: {mime_type}")

        # Para vídeos em formatos problemáticos, converter para MP4
        if mime_type.startswith('video/') and needs_conversion(mime_type):
            logger.info(f"[WAHA Media] Convertendo vídeo de {mime_type} para MP4")
            converted_file = convert_video_to_mp4(file_path, mime_type)

            return FileResponse(
                converted_file,
                media_type="video/mp4",
                filename=filename.replace('.webm', '.mp4').replace('.avi', '.mp4').replace('.mov', '.mp4'),
                headers={
                    "Cache-Control": "public, max-age=3600",
                    "Access-Control-Allow-Origin": "*",
                    "X-Video-Converted": "true"
                }
            )

        return FileResponse(
            file_path,
            media_type=mime_type,
            filename=filename,
            headers={
                "Cache-Control": "public, max-age=3600",  # Cache de 1 hora
                "Access-Control-Allow-Origin": "*",
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[WAHA Media] Erro inesperado: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Erro interno ao processar mídia"
        )

def fetch_from_waha_directly(waha_path: str):
    """
    Busca mídia diretamente do WAHA quando não existe localmente.
    """
    try:
        safe_waha_path = _normalize_waha_media_path(waha_path)
        filename = os.path.basename(safe_waha_path)
        waha_url = _build_waha_file_url(safe_waha_path)

        # Importar API key do WAHA
        try:
            from backend.config import WAHA_API_KEY
            headers = {'X-Api-Key': WAHA_API_KEY}
        except ImportError:
            headers = {}

        logger.info(f"[WAHA Media] Buscando do WAHA: {waha_url}")

        # Fazer request para WAHA com autenticação
        response = requests.get(waha_url, stream=True, timeout=30, headers=headers)

        if response.status_code != 200:
            logger.error(f"[WAHA Media] WAHA retornou status {response.status_code}")
            raise HTTPException(
                status_code=404,
                detail=f"Arquivo {filename} não encontrado no WAHA"
            )

        # Obter content type
        content_type = response.headers.get('content-type', 'application/octet-stream')
        logger.info(f"[WAHA Media] Content-Type do WAHA: {content_type}")

        # Se for vídeo problemático, converter
        if content_type.startswith('video/') and needs_conversion(content_type):
            logger.info(f"[WAHA Media] Convertendo vídeo WAHA de {content_type} para MP4")

            # Baixar dados completos
            video_data = response.content

            # Salvar em arquivo temporário para conversão
            with tempfile.NamedTemporaryFile(delete=False, suffix='.tmp') as temp_file:
                temp_file.write(video_data)
                temp_path = temp_file.name

            try:
                # Converter
                converted_path = convert_video_to_mp4(temp_path, content_type)

                # Ler convertido
                with open(converted_path, 'rb') as f:
                    converted_data = f.read()

                # Limpar arquivos temporários
                os.unlink(temp_path)
                if converted_path != temp_path:  # Se converteu com sucesso
                    os.unlink(converted_path)

                return StreamingResponse(
                    io.BytesIO(converted_data),
                    media_type="video/mp4",
                    headers={
                        "Cache-Control": "public, max-age=3600",
                        "Access-Control-Allow-Origin": "*",
                        "X-Video-Converted": "true",
                        "X-Source": "waha-direct"
                    }
                )
            except Exception as e:
                logger.error(f"[WAHA Media] Erro na conversão: {e}")
                os.unlink(temp_path)  # Limpar temporário
                # Fallback para original
                return StreamingResponse(
                    io.BytesIO(video_data),
                    media_type=content_type,
                    headers={
                        "Cache-Control": "public, max-age=3600",
                        "Access-Control-Allow-Origin": "*",
                        "X-Source": "waha-direct"
                    }
                )
        else:
            # Retornar streaming direto para outros formatos
            return StreamingResponse(
                io.BytesIO(response.content),
                media_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=3600",
                    "Access-Control-Allow-Origin": "*",
                    "X-Source": "waha-direct"
                }
            )

    except HTTPException:
        raise
    except requests.RequestException as e:
        logger.error(f"[WAHA Media] Erro ao buscar do WAHA: {e}")
        raise HTTPException(
            status_code=502,
            detail="Não foi possível acessar o WAHA"
        )
    except Exception as e:
        logger.error(f"[WAHA Media] Erro inesperado ao buscar do WAHA: {e}")
        raise HTTPException(
            status_code=500,
            detail="Erro interno ao processar mídia do WAHA"
        )
