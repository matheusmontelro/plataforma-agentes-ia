import base64
import logging
import mimetypes
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import unquote, urlparse

import requests

from backend.runtime_settings import MEDIA_BASE_PATH

logger = logging.getLogger(__name__)

SUPPORTED_TRANSCRIPTION_EXTENSIONS = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm", ".ogg"}
PASSTHROUGH_EXTENSION_ALIASES = {
    ".oga": ".ogg",
    ".opus": ".ogg",
}
MAX_TRANSCRIPTION_UPLOAD_BYTES = int(os.getenv("OPENAI_TRANSCRIPTION_MAX_BYTES", str(25 * 1024 * 1024)))
WAHA_MEDIA_ROUTE_PREFIX = "/api/waha/media/"
WAHA_FILES_MARKER = "/api/files/"


def _waha_media_dir() -> Path:
    media_root = str(MEDIA_BASE_PATH)
    return Path(os.getenv("WAHA_MEDIA_DIR", os.path.join(media_root, "waha"))).resolve()


def _safe_unlink(path: Optional[Path]) -> None:
    if not path:
        return
    try:
        path.unlink(missing_ok=True)
    except Exception:
        logger.debug("[media_transcription] Falha ao remover arquivo temporario", exc_info=True)


def _find_binary(binary_name: str, env_name: str) -> str:
    configured = os.getenv(env_name)
    candidates = [
        configured,
        shutil.which(binary_name),
        f"/usr/bin/{binary_name}",
        f"/usr/local/bin/{binary_name}",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return ""


def _configure_audio_segment_binaries(audio_segment_cls: object) -> None:
    ffmpeg_path = _find_binary("ffmpeg", "FFMPEG_BINARY")
    ffprobe_path = _find_binary("ffprobe", "FFPROBE_BINARY")

    if ffmpeg_path:
        audio_segment_cls.converter = ffmpeg_path
        audio_segment_cls.ffmpeg = ffmpeg_path
        _prepend_binary_dir_to_path(ffmpeg_path)
    if ffprobe_path:
        audio_segment_cls.ffprobe = ffprobe_path
        _prepend_binary_dir_to_path(ffprobe_path)


def _prepend_binary_dir_to_path(binary_path: str) -> None:
    binary_dir = str(Path(binary_path).parent)
    current_path = os.getenv("PATH", "")
    path_parts = [part for part in current_path.split(os.pathsep) if part]
    if binary_dir in path_parts:
        return
    os.environ["PATH"] = os.pathsep.join([binary_dir, *path_parts])


def _extension_from_mime(mime_type: str, default: str = ".bin") -> str:
    clean_mime = (mime_type or "").split(";", 1)[0].strip().lower()
    explicit = {
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/mpga": ".mpga",
        "audio/mp4": ".m4a",
        "audio/x-m4a": ".m4a",
        "audio/ogg": ".ogg",
        "audio/opus": ".opus",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "audio/webm": ".webm",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
    }
    if clean_mime in explicit:
        return explicit[clean_mime]

    guessed = mimetypes.guess_extension(clean_mime) if clean_mime else None
    return guessed or default


def _extension_from_source(source: str, default: str = ".bin") -> str:
    parsed = urlparse(source)
    path = parsed.path or source
    suffix = Path(path).suffix.lower()
    return suffix or default


def _resolve_local_media_path(source: str) -> Optional[Path]:
    if not source:
        return None
    if source.startswith("data:"):
        return None

    parsed = urlparse(source)
    route_path = parsed.path if parsed.scheme in {"http", "https"} else source
    route_path = unquote(route_path)

    if route_path.startswith(WAHA_MEDIA_ROUTE_PREFIX):
        relative_path = route_path[len(WAHA_MEDIA_ROUTE_PREFIX):].lstrip("/")
        base_dir = _waha_media_dir()
        candidate = (base_dir / relative_path).resolve()
        try:
            candidate.relative_to(base_dir)
        except ValueError:
            logger.warning("[media_transcription] Caminho de midia WAHA fora do diretorio permitido")
            return None
        if candidate.is_file():
            return candidate

    if parsed.scheme in {"http", "https"}:
        return None

    plain_path = Path(source)
    if plain_path.is_file():
        return plain_path.resolve()

    return None


def _build_internal_waha_file_request(source: str) -> tuple[str, dict[str, str]]:
    if WAHA_FILES_MARKER not in source:
        return source, {}

    from backend.config import WAHA_API_KEY, WAHA_BASE_URL

    file_path = source.split(WAHA_FILES_MARKER, 1)[1].split("?", 1)[0].lstrip("/")
    internal_url = f"{WAHA_BASE_URL.rstrip('/')}{WAHA_FILES_MARKER}{file_path}"
    return internal_url, {"X-Api-Key": WAHA_API_KEY}


@contextmanager
def _materialize_media_source(source: str) -> Iterator[Path]:
    local_path = _resolve_local_media_path(source)
    if local_path:
        yield local_path
        return

    temp_path: Optional[Path] = None
    try:
        if source.startswith("data:"):
            header, encoded = source.split(",", 1)
            mime_type = header.split(":", 1)[1].split(";", 1)[0]
            suffix = _extension_from_mime(mime_type)
            fd, path = tempfile.mkstemp(suffix=suffix, prefix="agentive-media-")
            temp_path = Path(path)
            with os.fdopen(fd, "wb") as tmp:
                tmp.write(base64.b64decode(encoded))
            yield temp_path
            return

        if source.startswith(("http://", "https://")):
            request_url, headers = _build_internal_waha_file_request(source)
            response = requests.get(request_url, headers=headers or None, timeout=30)
            response.raise_for_status()

            suffix = _extension_from_mime(
                response.headers.get("content-type", ""),
                default=_extension_from_source(source),
            )
            fd, path = tempfile.mkstemp(suffix=suffix, prefix="agentive-media-")
            temp_path = Path(path)
            with os.fdopen(fd, "wb") as tmp:
                tmp.write(response.content)
            yield temp_path
            return

        raise ValueError("Fonte de midia nao suportada para transcricao")
    finally:
        _safe_unlink(temp_path)


@contextmanager
def _ensure_supported_upload_file(source_path: Path) -> Iterator[Path]:
    source_suffix = source_path.suffix.lower()

    if source_suffix in SUPPORTED_TRANSCRIPTION_EXTENSIONS:
        if source_path.stat().st_size > MAX_TRANSCRIPTION_UPLOAD_BYTES:
            raise ValueError("Arquivo excede o limite configurado para transcricao")
        yield source_path
        return

    alias_suffix = PASSTHROUGH_EXTENSION_ALIASES.get(source_suffix)
    if alias_suffix:
        converted_path: Optional[Path] = None
        try:
            if source_path.stat().st_size > MAX_TRANSCRIPTION_UPLOAD_BYTES:
                raise ValueError("Arquivo excede o limite configurado para transcricao")

            fd, path = tempfile.mkstemp(suffix=alias_suffix, prefix="agentive-transcription-")
            os.close(fd)
            converted_path = Path(path)
            shutil.copyfile(source_path, converted_path)
            yield converted_path
            return
        finally:
            _safe_unlink(converted_path)

    converted_path: Optional[Path] = None
    try:
        from pydub import AudioSegment

        _configure_audio_segment_binaries(AudioSegment)

        fd, path = tempfile.mkstemp(suffix=".mp3", prefix="agentive-transcription-")
        os.close(fd)
        converted_path = Path(path)

        audio = AudioSegment.from_file(str(source_path))
        audio.export(str(converted_path), format="mp3")

        if converted_path.stat().st_size > MAX_TRANSCRIPTION_UPLOAD_BYTES:
            raise ValueError("Arquivo convertido excede o limite configurado para transcricao")

        yield converted_path
    finally:
        _safe_unlink(converted_path)


def _openai_transcribe_file(
    file_path: Path,
    media_kind: str,
    *,
    api_key: str,
) -> str:
    if not api_key:
        logger.warning("[media_transcription] Chave OpenAI da empresa nao configurada")
        return ""

    from openai import OpenAI

    model = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-transcribe")
    prompt = os.getenv(
        "OPENAI_TRANSCRIPTION_PROMPT",
        "Transcreva em portugues do Brasil. Preserve nomes, telefones, datas e valores quando forem mencionados.",
    )

    with file_path.open("rb") as media_file:
        transcription = OpenAI(api_key=api_key).audio.transcriptions.create(
            model=model,
            file=media_file,
            response_format="text",
            prompt=prompt,
        )

    text = transcription if isinstance(transcription, str) else getattr(transcription, "text", "")
    text = (text or "").strip()
    if not text:
        return ""

    label = "Vídeo" if media_kind == "video" else "Áudio"
    return f"[{label} recebido/transcrição]\n{text}"


def _transcribe_media(
    source: str,
    media_kind: str,
    *,
    api_key: str,
) -> str:
    if not source:
        return ""

    try:
        with _materialize_media_source(source) as source_path:
            with _ensure_supported_upload_file(source_path) as upload_path:
                return _openai_transcribe_file(
                    upload_path,
                    media_kind,
                    api_key=api_key,
                )
    except Exception:
        logger.warning(
            "[media_transcription] Falha ao transcrever %s",
            media_kind,
        )
        return ""


def transcribe_audio(audio_url: str, *, api_key: str) -> str:
    """Transcreve audio recebido em data URL, URL HTTP, proxy WAHA ou arquivo local."""
    return _transcribe_media(audio_url, "audio", api_key=api_key)


def transcribe_video(video_url: str, *, api_key: str) -> str:
    """Transcreve a faixa de audio de video recebido em URL/proxy/arquivo local."""
    return _transcribe_media(video_url, "video", api_key=api_key)
