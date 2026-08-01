import base64
import logging
import mimetypes
import os
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

import requests

from backend.runtime_settings import GOOGLE_VISION_CREDENTIALS, MEDIA_BASE_PATH

logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
SUPPORTED_IMAGE_DETAIL_LEVELS = {"low", "high", "original", "auto"}
MAX_IMAGE_ANALYSIS_BYTES = int(os.getenv("OPENAI_IMAGE_MAX_BYTES", str(20 * 1024 * 1024)))
WAHA_MEDIA_ROUTE_PREFIX = "/api/waha/media/"
WAHA_FILES_MARKER = "/api/files/"


def _waha_media_dir() -> Path:
    media_root = str(MEDIA_BASE_PATH)
    return Path(os.getenv("WAHA_MEDIA_DIR", os.path.join(media_root, "waha"))).resolve()


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
            logger.warning("[image_analysis] Caminho de midia WAHA fora do diretorio permitido")
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


def _normalize_image_mime(mime_type: str, source: str = "") -> str:
    clean_mime = (mime_type or "").split(";", 1)[0].strip().lower()
    if clean_mime in SUPPORTED_IMAGE_MIME_TYPES:
        return clean_mime

    guessed = mimetypes.guess_type(source)[0] if source else None
    if guessed in SUPPORTED_IMAGE_MIME_TYPES:
        return guessed

    suffix = Path(urlparse(source).path or source).suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"

    return "image/jpeg"


def _read_image_source(image_source: str) -> tuple[bytes, str]:
    if not image_source:
        raise ValueError("Imagem vazia")

    local_path = _resolve_local_media_path(image_source)
    if local_path:
        image_bytes = local_path.read_bytes()
        mime_type = _normalize_image_mime(mimetypes.guess_type(str(local_path))[0] or "", str(local_path))
        return image_bytes, mime_type

    if image_source.startswith("data:"):
        header, encoded = image_source.split(",", 1)
        mime_type = header.split(":", 1)[1].split(";", 1)[0]
        image_bytes = base64.b64decode(encoded)
        return image_bytes, _normalize_image_mime(mime_type)

    if image_source.startswith(("http://", "https://")):
        request_url, headers = _build_internal_waha_file_request(image_source)
        response = requests.get(request_url, headers=headers or None, timeout=30)
        response.raise_for_status()
        mime_type = _normalize_image_mime(response.headers.get("content-type", ""), image_source)
        return response.content, mime_type

    raise ValueError("Fonte de imagem nao suportada")


def _image_source_to_data_url(image_source: str) -> str:
    image_bytes, mime_type = _read_image_source(image_source)
    if len(image_bytes) > MAX_IMAGE_ANALYSIS_BYTES:
        raise ValueError("Imagem excede o limite configurado para analise")

    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def image_source_to_data_url(image_source: str) -> str:
    """Return an OpenAI-compatible image data URL without calling a model."""
    return _image_source_to_data_url(image_source)


def normalize_image_detail(detail: Optional[str], *, default: str = "auto") -> str:
    normalized = str(detail or default).strip().lower()
    if normalized not in SUPPORTED_IMAGE_DETAIL_LEVELS:
        return default
    return normalized


def build_openai_image_input_part(
    image_source: str,
    *,
    detail: Optional[str] = None,
) -> dict[str, str]:
    """Build a Responses API input_image content part from local/WAHA media."""
    return {
        "type": "input_image",
        "image_url": image_source_to_data_url(image_source),
        "detail": normalize_image_detail(detail),
    }


def _response_output_text(response: object) -> str:
    output_text = getattr(response, "output_text", "")
    if output_text:
        return str(output_text).strip()

    output = getattr(response, "output", []) or []
    texts: list[str] = []
    for item in output:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", "")
            if text:
                texts.append(str(text))
    return "\n".join(texts).strip()


def analyze_image_with_openai(
    image_source: str,
    *,
    api_key: str,
    conversation_context: str = "",
    caption: str = "",
) -> str:
    """Analisa uma imagem com OpenAI Vision e retorna texto pronto para o agente."""
    if not image_source:
        return ""

    if not api_key:
        logger.warning("[image_analysis] Chave OpenAI da empresa nao configurada")
        return ""

    try:
        from openai import OpenAI

        data_url = _image_source_to_data_url(image_source)
        model = os.getenv("OPENAI_IMAGE_VISION_MODEL", "gpt-4o-mini")
        detail = os.getenv("OPENAI_IMAGE_DETAIL", "low")
        max_output_tokens = int(os.getenv("OPENAI_IMAGE_MAX_OUTPUT_TOKENS", "450"))

        prompt = (
            "Analise a imagem recebida por WhatsApp no contexto de atendimento ao cliente. "
            "Descreva objetivamente o que aparece, texto legivel, documentos, produtos, "
            "comprovantes, datas, valores e qualquer pedido claro do cliente. "
            "Nao invente informacoes que nao estejam visiveis. Responda em portugues do Brasil."
        )
        if caption:
            prompt += f"\nLegenda enviada pelo cliente: {caption[:600]}"
        if conversation_context:
            prompt += f"\nContexto recente da conversa:\n{conversation_context[:1800]}"

        response = OpenAI(api_key=api_key).responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": data_url, "detail": detail},
                    ],
                }
            ],
            max_output_tokens=max_output_tokens,
        )

        analysis = _response_output_text(response)
        if not analysis:
            return ""

        return f"[Imagem recebida]\n{analysis}"
    except Exception:
        logger.warning("[image_analysis] Falha ao analisar imagem com OpenAI")
        return ""


def analyze_image_with_google_vision(image_url: str) -> str:
    """Fallback legado de Google Vision, mantido para compatibilidade operacional."""
    try:
        from google.cloud import vision
        from google.oauth2 import service_account

        image_content, _ = _read_image_source(image_url)
        creds_path = os.getenv(
            "GOOGLE_VISION_CREDENTIALS_PATH",
            str(GOOGLE_VISION_CREDENTIALS),
        )

        credentials = service_account.Credentials.from_service_account_file(creds_path)
        client = vision.ImageAnnotatorClient(credentials=credentials)
        image = vision.Image(content=image_content)
        response = client.label_detection(image=image)
        labels = response.label_annotations

        if not labels:
            return "Nenhum rótulo encontrado na imagem."

        label_names = [label.description for label in labels]
        return "Itens detectados na imagem: " + ", ".join(label_names)
    except Exception as exc:
        logger.warning("[image_analysis] Falha no fallback Google Vision: %s", exc)
        return ""
