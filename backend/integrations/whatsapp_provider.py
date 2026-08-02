# backend/integrations/whatsapp_provider.py

"""
Abstração de WhatsApp para o provider ativo do produto.

WAHA é o único provider WhatsApp habilitado. Integrações legadas podem existir
no banco/código, mas não devem ser usadas como fallback de envio ou status.
"""

import os
import logging
import json
import time
import base64
import inspect
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from sqlalchemy import text
from sqlalchemy.orm import Session
from fastapi import HTTPException
from backend.config import CLIENT_TOKEN
from datetime import datetime

from backend.models import Message, Lead, Contact
from backend.runtime_settings import MEDIA_BASE_PATH as RUNTIME_MEDIA_BASE_PATH

logger = logging.getLogger(__name__)

# Base path para arquivos de mídia
MEDIA_BASE_PATH = str(RUNTIME_MEDIA_BASE_PATH)
MAX_AGENT_RESPONSE_DELAY_SECONDS = 60

# Import dos providers
from backend.integrations import zapi_utils
# from backend.integrations.wppconnect_sdk import get_client as get_wppconnect_client, WPPConnectSDKError  # Comentado - módulo não existe

# Funções stub para WPPConnect (módulo não existe mais)
class WPPConnectSDKError(Exception):
    """Exception stub para WPPConnectSDKError"""
    pass

def get_wppconnect_client(*args, **kwargs):
    """Função stub para get_wppconnect_client - levanta erro indicando que WPPConnect não está disponível"""
    raise WPPConnectSDKError("WPPConnect SDK não está disponível. Use WAHA provider.")
from backend.integrations.waha_sdk import get_client as get_waha_client, WAHAException, WAHAConnectionError


@contextmanager
def _locked_company_remote_operation(company_id: int, db: Optional[Session]):
    """Hold the company mutation lock through a remote side effect."""
    from backend.services.company_access_control import (
        CompanyOperationallyBlockedError,
        ensure_company_operational,
        lock_entities_for_mutation,
    )

    owns_session = db is None
    if owns_session:
        from backend.db import SessionLocal

        db = SessionLocal()

    try:
        try:
            lock_entities_for_mutation(db, company_ids=[company_id])
            ensure_company_operational(db, company_id)
        except CompanyOperationallyBlockedError as exc:
            raise HTTPException(
                status_code=423,
                detail="Acesso da empresa suspenso",
            ) from exc

        yield db
    finally:
        if owns_session:
            try:
                db.rollback()
            finally:
                db.close()


def _serialize_company_remote_operation(function: Callable) -> Callable:
    """Apply the operational lock to the complete provider operation."""
    signature = inspect.signature(function)

    @wraps(function)
    def wrapped(*args, **kwargs):
        arguments = signature.bind(*args, **kwargs)
        arguments.apply_defaults()
        company_id = int(arguments.arguments["company_id"])
        current_db = arguments.arguments.get("db")

        with _locked_company_remote_operation(company_id, current_db) as locked_db:
            if "db" in signature.parameters:
                arguments.arguments["db"] = locked_db
            return function(**arguments.arguments)

    return wrapped


def get_public_media_url(file_path: str, company_id: int = None) -> str:
    """
    Gera URL pública para acesso a arquivos de mídia salvos localmente.

    Esta função deve ser usada para converter caminhos de arquivo locais
    em URLs públicas que podem ser acessadas pelo WAHA e pelo frontend.

    Args:
        file_path: Caminho completo do arquivo (ex: /tmp/agentive-media/videos/company_3/video.mp4)
        company_id: ID da empresa para organização das URLs (obrigatório para novo sistema)

    Returns:
        URL pública para acesso ao arquivo
    """
    try:
        # Extrair informações do caminho
        path_obj = Path(file_path)

        # Verificar se o arquivo está no novo diretório de mídia
        if "/tmp/agentive-media/" in file_path:
            # Novo sistema de mídia
            if company_id is None:
                logger.error(f"[get_public_media_url] company_id é obrigatório para novo sistema de mídia")
                return ""

            # Identificar tipo de mídia e nome do arquivo
            if "/videos/" in file_path:
                media_type = "videos"
            elif "/images/" in file_path:
                media_type = "images"
            elif "/audio/" in file_path:
                media_type = "audio"
            else:
                logger.warning(f"[get_public_media_url] Tipo de mídia não identificado em: {file_path}")
                return ""

            # Extrair nome do arquivo
            filename = path_obj.name

            # Construir URL usando base pública acessível pelo WAHA.
            from backend.utils.media_storage import get_media_public_base_url

            backend_url = get_media_public_base_url()
            public_url = f"{backend_url}/media/{media_type}/company_{company_id}/{filename}"

            logger.debug("[get_public_media_url] URL gerada no novo sistema: present=%s", bool(public_url))
            return public_url

        else:
            # Sistema legado / Arquivos (MediaFile)
            # Esperamos algo como: .../arquivos/media/client_1/company_3/video/file.mp4
            from backend.config import PUBLIC_BASE_URL
            relative_path = ""
            if file_path.startswith(MEDIA_BASE_PATH):
                relative_path = file_path[len(MEDIA_BASE_PATH):].lstrip('/')
            elif 'arquivos/media/' in file_path:
                relative_path = file_path.split('arquivos/media/', 1)[1]
            else:
                relative_path = file_path

            # Tentativa de parse para usar endpoint oficial de arquivos
            try:
                parts = relative_path.split('/')
                # Esperado: ['client_1', 'company_3', 'video', 'filename.mp4']
                if len(parts) >= 4:
                    client_part = parts[0] # client_1
                    company_part = parts[1] # company_3
                    # type_part = parts[2] # video
                    filename = parts[-1]   # filename.mp4

                    c_id = client_part.split('_')[1]
                    cl_id = company_part.split('_')[1]

                    # Endpoint: /api/arquivos/files/view/{company_id}/{client_id}/{file_name}
                    public_url = f"{PUBLIC_BASE_URL}/api/arquivos/files/view/{cl_id}/{c_id}/{filename}"
                    logger.info("[get_public_media_url] URL gerada em arquivos: present=%s", bool(public_url))
                    return public_url
            except Exception as e:
                logger.warning(f"[get_public_media_url] Falha ao parsear path '{relative_path}': {e}")

            # Fallback (caso path seja diferente) -> tenta rota genérica antiga (vai dar 404 se n existir, mas mantemos o fallback)
            public_url = f"{PUBLIC_BASE_URL}/api/arquivos/media/{relative_path}"
            logger.info("[get_public_media_url] URL gerada em fallback: present=%s", bool(public_url))
            return public_url

    except Exception as e:
        logger.error("[get_public_media_url] Erro ao gerar URL: path_present=%s error=%s", bool(file_path), e)
        return ""


def _detect_audio_mime(audio_bytes: Optional[bytes]) -> str:
    """Detect audio MIME type, using python-magic when available."""
    if not audio_bytes:
        return "application/octet-stream"

    try:
        import magic

        mime = magic.Magic(mime=True)
        detected = str(mime.from_buffer(audio_bytes) or "").strip()
        if detected:
            return detected
    except ImportError:
        logger.info("[send_audio WAHA] python-magic indisponível; usando detecção por cabeçalho")
    except Exception as exc:
        logger.warning("[send_audio WAHA] Falha ao detectar áudio com python-magic: %s", exc)

    return _detect_audio_mime_from_header(audio_bytes)


def _detect_audio_mime_from_header(audio_bytes: bytes) -> str:
    """Best-effort MIME detection for common WhatsApp/TTS audio formats."""
    header = bytes(audio_bytes[:32])
    if header.startswith(b"ID3") or header[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}:
        return "audio/mpeg"
    if header.startswith(b"OggS"):
        return "audio/ogg"
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return "audio/webm"
    if header.startswith(b"RIFF") and b"WAVE" in header[:16]:
        return "audio/wav"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return "audio/mp4"
    return "application/octet-stream"


def _audio_filename_for_mime(mimetype: str) -> str:
    """Return a WAHA-friendly filename for a detected audio MIME type."""
    mime = (mimetype or "").lower()
    if "mpeg" in mime or "mp3" in mime:
        return "audio.mp3"
    if "ogg" in mime:
        return "audio.ogg"
    if "webm" in mime:
        return "audio.webm"
    if "wav" in mime:
        return "audio.wav"
    if "mp4" in mime or "m4a" in mime:
        return "audio.m4a"
    return "audio.mp3"


def _save_message(
    db: Session,
    company_id: int,
    phone: str,
    message_type: str,
    content: str,
    direction: str = "outgoing",
    status: str = "sent",
    message_id: str = None
):
    """
    Função interna para persistir mensagem no banco.
    Tenta associar ao lead e contact corretos.
    """
    try:
        if not db:
            return

        # Buscar Client ID (assumindo 1:1 por enquanto ou via lead)
        # Mais seguro buscar lead pelo telefone + company_id
        lead = db.query(Lead).filter(
            Lead.company_id == company_id,
            Lead.phone == phone
        ).first()

        client_id = lead.client_id if lead else None

        # Se não achou lead, tenta contact
        contact_id = None
        if not client_id:
             # Tenta achar cliente via contact?
             # Por simplicidade, se não tem lead, logamos aviso
             # Mas persistimos mesmo assim se possível (precisa de client_id na tabela messages?)
             # Verificando model: client_id É obrigatório em Message? Geralmente sim.
             # Se não temos lead, tentamos pegar o client_id da company? (Tabela companies tem client_id?)
             # Assumindo query na tabela companies:
             pass

        # Se ainda não temos client_id, buscamos da empresa
        if not client_id:
             try:
                 # Query raw para evitar import circular de Company se não estiver importado
                 res = db.execute(text("SELECT client_id FROM companies WHERE id = :cid"), {"cid": company_id}).fetchone()
                 if res:
                     client_id = str(res.client_id)
             except Exception:
                 pass

        if not client_id:
            logger.warning(f"[_save_message] Não foi possível determinar client_id para company={company_id}, phone={phone}. Mensagem não salva.")
            return

        new_msg = Message(
            client_id=str(client_id),
            company_id=company_id,
            contact_phone=phone,
            message_type=message_type,
            from_me=(direction == "outgoing"),
            sender_phone='me' if direction == "outgoing" else phone,
            sender_name="System",
            content=content,
            timestamp=datetime.utcnow()
        )
        db.add(new_msg)
        db.commit()
        # logger.info(f"[_save_message] Mensagem salva id={new_msg.id}")

    except Exception as e:
        logger.error(f"[_save_message] Erro ao salvar mensagem: {e}")
        db.rollback()


def _log_waha_deferred_persistence(company_id: int, phone: str, msg_type: str, result: Dict[str, Any]) -> None:
    message_id = result.get("id") or result.get("messageId") or "unknown_id_waha"
    logger.info(
        "[WAHA] Persistência local adiada para callback fromMe: company=%s phone=%s type=%s message_id=%s",
        company_id,
        phone,
        msg_type,
        message_id,
    )


def _normalize_response_delay_seconds(value: Any) -> int:
    try:
        parsed = int(round(float(value or 0)))
    except (TypeError, ValueError):
        parsed = 0
    return max(0, min(MAX_AGENT_RESPONSE_DELAY_SECONDS, parsed))


def _apply_waha_response_delay(client: Any, session_name: str, phone: str, delay_seconds: int) -> None:
    delay_seconds = _normalize_response_delay_seconds(delay_seconds)
    if delay_seconds <= 0:
        return

    typing_started = False
    try:
        try:
            client.start_typing(session=session_name, phone=phone)
            typing_started = True
        except Exception as exc:
            logger.warning("[WAHA] Nao foi possivel iniciar digitacao antes do delay: %s", exc)

        logger.info("[WAHA] Aguardando %ss antes de enviar resposta automatica para %s", delay_seconds, phone)
        time.sleep(delay_seconds)
    finally:
        if typing_started:
            try:
                client.stop_typing(session=session_name, phone=phone)
            except Exception as exc:
                logger.warning("[WAHA] Nao foi possivel parar digitacao antes do envio: %s", exc)


class WhatsAppConfig:
    """Configuração do WhatsApp para uma empresa"""

    def __init__(self, provider: str, **kwargs):
        self.provider = provider
        self.config = kwargs

    @classmethod
    def from_company(cls, company_id: int, db: Session = None) -> Optional['WhatsAppConfig']:
        """
        Cria configuração WAHA a partir do ID da empresa.
        """
        # Se db=None, criar uma sessão temporária
        should_close_db = False
        if db is None:
            from backend.db import SessionLocal
            db = SessionLocal()
            should_close_db = True

        try:
            company_data = db.execute(
                text("""
                    SELECT waha_session_name, waha_enabled, operational_status
                    FROM companies
                    WHERE id = :company_id
                """),
                {"company_id": company_id}
            ).fetchone()

            if not company_data:
                logger.warning(f"Empresa {company_id} não encontrada")
                return None

            if company_data.operational_status != "active":
                logger.warning("Empresa %s bloqueada para operação WhatsApp", company_id)
                return None

            if company_data.waha_enabled and company_data.waha_session_name:
                from backend.config import WAHA_BASE_URL, WAHA_API_KEY
                logger.info(f"Empresa {company_id} usando WAHA (sessão: {company_data.waha_session_name})")
                return cls(
                    provider="waha",
                    session_name=company_data.waha_session_name,
                    base_url=WAHA_BASE_URL,
                    api_key=WAHA_API_KEY
                )

            logger.warning(f"Empresa {company_id} sem configuração WAHA ativa")
            return None
        finally:
            # Fechar a sessão temporária se foi criada aqui
            if should_close_db:
                db.close()

    def is_waha(self) -> bool:
        return self.provider == "waha"

    def is_zapi(self) -> bool:
        return self.provider == "zapi"

    def is_wppconnect(self) -> bool:
        return self.provider == "wppconnect"


# ==========================================
# FUNÇÕES UNIFICADAS (Auto-detect provider)
# ==========================================

def _persist_waha_message(
    db: Session,
    company_id: int,
    phone: str,
    content: str,
    msg_type: str,
    message_id: str,
    media_url: str = None
):
    """
    Persiste mensagem enviada via WAHA no banco de dados para histórico.
    """
    try:
        # Get Client ID
        client_data = db.execute(text(
            "SELECT client_id FROM client_companies WHERE company_id = :company_id LIMIT 1"
        ), {"company_id": company_id}).fetchone()

        if not client_data:
            logger.warning(f"[Persistence] Client not found for company {company_id}")
            return

        client_id = client_data.client_id

        # Content handling for media
        final_content = content
        if not final_content and media_url:
            final_content = media_url

        # Insert Message
        db.execute(text("""
            INSERT INTO messages
            (client_id, company_id, contact_phone, message_type, content, from_me, sender_phone, zapi_message_id, timestamp)
            VALUES
            (:client_id, :company_id, :phone, :msg_type, :content, true, 'me', :message_id, NOW())
        """), {
            "client_id": client_id,
            "company_id": company_id,
            "phone": phone,
            "msg_type": msg_type,
            "content": final_content,
            "message_id": message_id
        })

        # Update Contact
        db.execute(text("""
            UPDATE contacts
            SET last_message_at = NOW()
            WHERE client_id = :client_id AND company_id = :company_id AND phone = :phone
        """), {
            "client_id": client_id,
            "company_id": company_id,
            "phone": phone
        })

        db.commit()
        logger.info(f"[Persistence] WAHA message {message_id} saved for {phone}")

    except Exception as e:
        logger.error(f"[Persistence] Failed to save WAHA message: {e}")
        try:
            db.rollback()
        except:
            pass

@_serialize_company_remote_operation
def send_text(
    company_id: int,
    phone: str,
    message: str,
    db: Session,
    human_mode: bool = False,
    response_delay_seconds: int = 0,
    reply_to: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Envia mensagem de texto usando o provider configurado para a empresa.
    """
    config = WhatsAppConfig.from_company(company_id, db)
    if not config:
        raise HTTPException(status_code=400, detail="Configuração WhatsApp não encontrada")

    if config.is_waha():
        try:
            client = get_waha_client(
                base_url=config.config["base_url"],
                api_key=config.config["api_key"]
            )
            _apply_waha_response_delay(
                client=client,
                session_name=config.config["session_name"],
                phone=phone,
                delay_seconds=response_delay_seconds,
            )
            result = client.send_text(
                session=config.config["session_name"],
                phone=phone,
                text=message,
                reply_to=reply_to,
            )

            _log_waha_deferred_persistence(company_id, phone, "text", result)

            return result
        except (WAHAException, WAHAConnectionError) as e:
            logger.error(f"Erro ao enviar texto via WAHA: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    elif config.is_zapi():
        return zapi_utils.send_text_to_zapi(
            instance_id=config.config["instance_id"],
            instance_token=config.config["token"],
            phone=phone,
            message=message,
            company_id=company_id,
            human_mode=human_mode
        )

        if db:
             # Z-API utils já salva? Verificar. Se não, salvar.
             # Por consistência, vamos salvar aqui também, mas precisa cuidar com duplicação.
             # O ideal é que o provider abstraia. Assumindo que zapi_utils NÃO salva (ou que queremos uniformizar).
             # Mas wait, ZAPI utils geralmente retorna direto.
             pass
        return result
    elif config.is_wppconnect():
        try:
            client = get_wppconnect_client(
                session_name=config.config["session_name"],
                base_url=config.config["base_url"],
                secret_key=config.config["secret_key"]
            )
            return client.send_text(phone, message)
        except WPPConnectSDKError as e:
            logger.error(f"Erro ao enviar texto via WPPConnect: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@_serialize_company_remote_operation
def send_contact_card(
    company_id: int,
    phone: str,
    contacts: list[Dict[str, Any]],
    db: Session = None,
    reply_to: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Envia card de contato pelo provider configurado.

    WAHA é o provider operacional para cards de contato. A persistência local
    segue o padrão dos outros envios WAHA: o callback fromMe grava a mensagem.
    """
    config = WhatsAppConfig.from_company(company_id, db)
    if not config:
        raise HTTPException(status_code=400, detail="Configuração WhatsApp não encontrada")

    normalized_contacts = [contact for contact in (contacts or []) if isinstance(contact, dict)]
    if not normalized_contacts:
        raise HTTPException(status_code=400, detail="Contato não informado")

    if config.is_waha():
        try:
            client = get_waha_client(
                base_url=config.config["base_url"],
                api_key=config.config["api_key"],
            )
            result = client.send_contact_vcard(
                session=config.config["session_name"],
                phone=phone,
                contacts=normalized_contacts,
                reply_to=reply_to,
            )

            _log_waha_deferred_persistence(company_id, phone, "contact", result)

            return result
        except (WAHAException, WAHAConnectionError) as e:
            logger.error(f"Erro ao enviar contato via WAHA: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    raise HTTPException(
        status_code=501,
        detail="Envio de card de contato é suportado apenas pelo WAHA",
    )


@_serialize_company_remote_operation
def send_audio(
    company_id: int,
    phone: str,
    audio_bytes: Optional[bytes] = None,
    audio_path: Optional[str] = None,
    db: Session = None
) -> Dict[str, Any]:
    """
    Envia áudio usando o provider configurado para a empresa.

    Note:
        WAHA recebe bytes como base64 para evitar dependência de URL pública
        temporária entre worker e backend.
    """
    config = WhatsAppConfig.from_company(company_id, db)
    if not config:
        raise HTTPException(status_code=400, detail="Configuração WhatsApp não encontrada")

    if config.is_waha():
        if not audio_bytes and audio_path:
            try:
                with open(audio_path, "rb") as f:
                    audio_bytes = f.read()
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Erro ao ler arquivo de áudio: {str(e)}")

        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Áudio não informado")

        try:
            audio_format = _detect_audio_mime(audio_bytes)
            if not audio_format.startswith("audio/"):
                logger.warning(
                    "[send_audio WAHA] Formato não reconhecido (%s); usando audio/mpeg como fallback",
                    audio_format,
                )
                audio_format = "audio/mpeg"
            filename = _audio_filename_for_mime(audio_format)
            audio_base64 = base64.b64encode(audio_bytes).decode("ascii")

            logger.info(
                "[send_audio WAHA] Enviando áudio base64 para empresa %s como %s (%s, %s bytes)",
                company_id,
                filename,
                audio_format,
                len(audio_bytes),
            )

            client = get_waha_client(
                base_url=config.config["base_url"],
                api_key=config.config["api_key"]
            )

            result = client.send_voice_base64(
                session=config.config["session_name"],
                phone=phone,
                audio_data=audio_base64,
                filename=filename,
                mimetype=audio_format,
            )

            _log_waha_deferred_persistence(company_id, phone, "audio", result)

            return result

        except (WAHAException, WAHAConnectionError) as e:
            logger.error(f"Erro ao enviar áudio via WAHA: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        except Exception as e:
            logger.error(f"Erro ao processar áudio para WAHA: {e}")
            raise HTTPException(status_code=500, detail=f"Erro ao processar áudio: {str(e)}")

    elif config.is_zapi():
        return zapi_utils.send_audio_to_zapi(
            instance_id=config.config["instance_id"],
            instance_token=config.config["token"],
            phone=phone,
            audio_bytes=audio_bytes,
            company_id=company_id
        )
    elif config.is_wppconnect():
        # Se não tem bytes mas tem path, ler
        if not audio_bytes and audio_path:
             try:
                with open(audio_path, "rb") as f:
                    audio_bytes = f.read()
             except Exception as e:
                raise HTTPException(status_code=500, detail=f"Erro ao ler arquivo de áudio: {str(e)}")

        try:
            client = get_wppconnect_client(
                session_name=config.config["session_name"],
                base_url=config.config["base_url"],
                secret_key=config.config["secret_key"]
            )
            return client.send_audio(phone, audio_bytes=audio_bytes)
        except WPPConnectSDKError as e:
            logger.error(f"Erro ao enviar áudio via WPPConnect: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@_serialize_company_remote_operation
def send_image(
    company_id: int,
    phone: str,
    image_bytes: Optional[bytes] = None,
    image_path: Optional[str] = None,
    db: Session = None,
    caption: Optional[str] = None
) -> Dict[str, Any]:
    """
    Envia imagem usando o provider configurado para a empresa.

    Envia imagem usando o provider configurado para a empresa.

    Note:
        WAHA requer URL pública.
        - Se image_path fornecido: gera URL pública direta.
        - Se apenas image_bytes: salva arquivo e gera URL.
    """
    config = WhatsAppConfig.from_company(company_id, db)
    if not config:
        raise HTTPException(status_code=400, detail="Configuração WhatsApp não encontrada")

    if config.is_waha():
        # WAHA trabalha com URLs

        # Caso 1: Temos o caminho do arquivo (Melhor performance)
        if image_path:
            try:
                image_url = get_public_media_url(image_path, company_id)
                logger.info(f"[send_image WAHA] Usando arquivo existente: {image_path}")
                logger.info("[send_image WAHA] URL gerada: present=%s", bool(image_url))

                client = get_waha_client(
                    base_url=config.config["base_url"],
                    api_key=config.config["api_key"]
                )

                return client.send_image(
                    session=config.config["session_name"],
                    phone=phone,
                    image_url=image_url,
                    caption=caption
                )
            except Exception as e:
                logger.error(f"[send_image WAHA] Erro ao usar arquivo existente: {e}")

        # Caso 2: Temos apenas bytes (ou fallback)
        if not image_bytes and image_path:
             try:
                with open(image_path, "rb") as f:
                    image_bytes = f.read()
             except Exception as e:
                raise HTTPException(status_code=500, detail=f"Erro ao ler arquivo de imagem: {str(e)}")

        # Salvar arquivo automaticamente e gerar URL (Código original)
        try:
            from backend.utils.media_storage import save_image_and_get_url

            logger.info(f"[send_image WAHA] Salvando imagem para empresa {company_id}")
            file_path, image_url = save_image_and_get_url(
                image_bytes=image_bytes,
                company_id=company_id
            )
            logger.info(f"[send_image WAHA] Imagem salva: {file_path}")
            logger.info("[send_image WAHA] URL pública gerada: present=%s", bool(image_url))

            client = get_waha_client(
                base_url=config.config["base_url"],
                api_key=config.config["api_key"]
            )

            result = client.send_image(
                session=config.config["session_name"],
                phone=phone,
                image_url=image_url,
                caption=caption
            )

            _log_waha_deferred_persistence(company_id, phone, "image", result)

            return result

        except (WAHAException, WAHAConnectionError) as e:
            logger.error(f"Erro ao enviar imagem via WAHA: {e}")
            raise HTTPException(status_code=500, detail=str(e))
            raise HTTPException(status_code=500, detail=str(e))
        except Exception as e:
            logger.error(f"Erro ao processar imagem para WAHA: {e}")
            raise HTTPException(status_code=500, detail=f"Erro ao processar imagem: {str(e)}")

    elif config.is_zapi():
        # Se não tem bytes mas tem path, ler
        if not image_bytes and image_path:
             try:
                with open(image_path, "rb") as f:
                    image_bytes = f.read()
             except Exception as e:
                raise HTTPException(status_code=500, detail=f"Erro ao ler arquivo de imagem: {str(e)}")

        # Chama a função Z-API existente em webhook.py
        from backend.routes.webhook import send_image_to_zapi, WhatsAppSendImageBody
        import base64

        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        image_content = f"data:image/jpeg;base64,{image_base64}"

        return send_image_to_zapi(
            instance_id=config.config["instance_id"],
            instance_token=config.config["token"],
            body=WhatsAppSendImageBody(phone=phone, image=image_content)
        )
    elif config.is_wppconnect():
        try:
            client = get_wppconnect_client(
                session_name=config.config["session_name"],
                base_url=config.config["base_url"],
                secret_key=config.config["secret_key"]
            )
            return client.send_image(phone, image_bytes=image_bytes, caption=caption)
        except WPPConnectSDKError as e:
            logger.error(f"Erro ao enviar imagem via WPPConnect: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@_serialize_company_remote_operation
def send_video(
    company_id: int,
    phone: str,
    video_bytes: Optional[bytes] = None,
    video_path: Optional[str] = None,
    db: Session = None,
    caption: Optional[str] = None
) -> Dict[str, Any]:
    """
    Envia vídeo usando o provider configurado para a empresa.

    Args:
        company_id: ID da empresa
        phone: Telefone do destinatário
        video_bytes: Bytes do vídeo (usado por Z-API)
        video_path: Caminho do arquivo de vídeo (usado por WAHA e WPPConnect via URL)
        db: Sessão do banco de dados
        caption: Legenda do vídeo

    Note:
        - WAHA: Usa video_path e envia via URL pública (SEM TIMEOUT!) ✅
        - Z-API: Usa video_bytes e envia via base64
        - WPPConnect: Prefere video_path mas tem limitação de 4 MB
    """
    config = WhatsAppConfig.from_company(company_id, db)
    if not config:
        raise HTTPException(status_code=400, detail="Configuração WhatsApp não encontrada")

    if config.is_waha():
        # WAHA usa URL e NÃO TEM TIMEOUT! 🎉
        if not video_path:
            raise ValueError("video_path é obrigatório para WAHA")

        try:
            # Converter caminho local em URL pública
            video_url = get_public_media_url(video_path, company_id)

            logger.info("[send_video WAHA] Enviando vídeo via URL: present=%s", bool(video_url))

            client = get_waha_client(
                base_url=config.config["base_url"],
                api_key=config.config["api_key"]
            )

            # WAHA envia vídeo via URL (sem limitação de tamanho!)
            result = client.send_video(
                session=config.config["session_name"],
                phone=phone,
                video_url=video_url,
                caption=caption,
                timeout=120  # 2 minutos para o WAHA baixar e processar
            )

            _log_waha_deferred_persistence(company_id, phone, "video", result)

            return result

        except (WAHAException, WAHAConnectionError) as e:
            logger.error(f"Erro ao enviar vídeo via WAHA: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    elif config.is_zapi():
        # Z-API usa bytes e envia via base64
        if not video_bytes:
            raise ValueError("video_bytes é obrigatório para Z-API")

        from backend.routes.webhook import send_video_to_zapi, WhatsAppSendVideoBody
        import base64

        video_base64 = base64.b64encode(video_bytes).decode('utf-8')
        video_content = f"data:video/mp4;base64,{video_base64}"

        return send_video_to_zapi(
            instance_id=config.config["instance_id"],
            instance_token=config.config["token"],
            body=WhatsAppSendVideoBody(phone=phone, video=video_content)
        )

    elif config.is_wppconnect():
        # WPPConnect tem limitação conhecida com vídeos grandes
        # Issue: https://github.com/wppconnect-team/wa-js/issues/2681
        # Recomendação: vídeos < 4 MB
        # Usando base64 (URL não funciona devido a problemas de rede)

        if not video_bytes:
            raise ValueError("video_bytes é obrigatório para WPPConnect")

        try:
            # Verificar tamanho do vídeo
            file_size_mb = len(video_bytes) / (1024 * 1024)
            logger.info(f"[send_video] Tamanho do vídeo: {file_size_mb:.2f} MB")

            # LIMITAÇÃO CONHECIDA DO WPPCONNECT
            if file_size_mb > 4.0:
                error_msg = (
                    f"Vídeo muito grande ({file_size_mb:.2f} MB) para WPPConnect. "
                    f"Limite recomendado: 4 MB. "
                    f"Issue conhecida: https://github.com/wppconnect-team/wa-js/issues/2681"
                )
                logger.error(f"[send_video] {error_msg}")
                raise HTTPException(
                    status_code=413,  # Payload Too Large
                    detail=error_msg
                )

            logger.info(f"[send_video] WPPConnect usando base64 (timeout 180s)")

            client = get_wppconnect_client(
                session_name=config.config["session_name"],
                base_url=config.config["base_url"],
                secret_key=config.config["secret_key"]
            )

            # Enviar via base64
            return client.send_video(phone, video_bytes=video_bytes, caption=caption)

        except WPPConnectSDKError as e:
            logger.error(f"Erro ao enviar vídeo via WPPConnect: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@_serialize_company_remote_operation
def send_poll(company_id: int, data: Any, db: Session) -> Dict[str, Any]:
    """
    Envia enquete usando o provider configurado para a empresa.

    Args:
        company_id: ID da empresa
        data: Dicionário com dados da enquete (phone, message, poll, etc.)
        db: Sessão do banco de dados
    """
    config = WhatsAppConfig.from_company(company_id, db)
    if not config:
        raise HTTPException(status_code=400, detail="Configuração WhatsApp não encontrada")

    if config.is_waha():
        try:
            client = get_waha_client(
                base_url=config.config["base_url"],
                api_key=config.config["api_key"]
            )

            # Extrair dados da enquete
            phone = data.get('phone', '')
            message = data.get('message', '')
            poll_options = data.get('poll', [])
            poll_max_options = data.get('pollMaxOptions', 1)  # escolha única por padrão

            # Se poll_options for lista de objetos com 'name', extrair apenas os nomes
            if poll_options and isinstance(poll_options[0], dict):
                poll_options = [opt.get('name', str(opt)) for opt in poll_options]

            return client.send_poll(
                session=config.config["session_name"],
                phone=phone,
                poll_name=message,
                poll_options=poll_options,
                multiple_answers=(poll_max_options > 1)
            )

        except (WAHAException, WAHAConnectionError) as e:
            logger.error(f"Erro ao enviar enquete via WAHA: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    elif config.is_zapi():
        return zapi_utils.send_poll(
            instance_id=config.config["instance_id"],
            instance_token=config.config["token"],
            data=data
        )
    elif config.is_wppconnect():
        raise HTTPException(
            status_code=501,
            detail="Enquetes não são suportadas pelo WPPConnect no momento"
        )


@_serialize_company_remote_operation
def delete_message(company_id: int, data: Any, db: Session) -> bool:
    """
    Deleta mensagem usando o provider configurado para a empresa.
    """
    config = WhatsAppConfig.from_company(company_id, db)
    if not config:
        raise HTTPException(status_code=400, detail="Configuração WhatsApp não encontrada")

    if config.is_zapi():
        return zapi_utils.delete_message(
            instance_id=config.config["instance_id"],
            instance_token=config.config["token"],
            data=data
        )
    elif config.is_wppconnect():
        raise HTTPException(
            status_code=501,
            detail="Deletar mensagens não é suportado pelo WPPConnect no momento"
        )


@_serialize_company_remote_operation
def send_reaction(company_id: int, data: Any, db: Session) -> Dict[str, Any]:
    """
    Envia reação usando o provider configurado para a empresa.
    """
    config = WhatsAppConfig.from_company(company_id, db)
    if not config:
        raise HTTPException(status_code=400, detail="Configuração WhatsApp não encontrada")

    message_id = data.get("messageId") if isinstance(data, dict) else getattr(data, "messageId", None)
    reaction = data.get("reaction", "") if isinstance(data, dict) else getattr(data, "reaction", "")

    if config.is_waha():
        try:
            client = get_waha_client(
                base_url=config.config["base_url"],
                api_key=config.config["api_key"]
            )
            return client.send_reaction(
                session=config.config["session_name"],
                message_id=message_id,
                reaction=reaction,
            )
        except (WAHAException, WAHAConnectionError) as e:
            logger.error(f"Erro ao enviar reação via WAHA: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    elif config.is_zapi():
        return zapi_utils.send_reaction(
            instance_id=config.config["instance_id"],
            instance_token=config.config["token"],
            data=data
        )
    elif config.is_wppconnect():
        raise HTTPException(
            status_code=501,
            detail="Reações não são suportadas pelo WPPConnect no momento"
        )


@_serialize_company_remote_operation
def remove_reaction(company_id: int, data: Any, db: Session) -> Dict[str, Any]:
    """
    Remove reação usando o provider configurado para a empresa.
    """
    config = WhatsAppConfig.from_company(company_id, db)
    if not config:
        raise HTTPException(status_code=400, detail="Configuração WhatsApp não encontrada")

    if config.is_waha():
        payload = dict(data) if isinstance(data, dict) else {
            "messageId": getattr(data, "messageId", None),
        }
        payload["reaction"] = ""
        return send_reaction(company_id, payload, db)
    elif config.is_zapi():
        return zapi_utils.remove_reaction(
            instance_id=config.config["instance_id"],
            instance_token=config.config["token"],
            data=data
        )
    elif config.is_wppconnect():
        raise HTTPException(
            status_code=501,
            detail="Remover reações não é suportado pelo WPPConnect no momento"
        )


@_serialize_company_remote_operation
def send_nps_poll(company_id: int, data: Any, db: Session) -> Dict[str, Any]:
    """
    Envia enquete NPS usando o provider configurado para a empresa.

    Args:
        company_id: ID da empresa
        data: Dicionário com dados NPS (phone, question, campaign_name, etc.)
        db: Sessão do banco de dados
    """
    config = WhatsAppConfig.from_company(company_id, db)
    if not config:
        raise HTTPException(status_code=400, detail="Configuração WhatsApp não encontrada")

    if config.is_waha():
        try:
            client = get_waha_client(
                base_url=config.config["base_url"],
                api_key=config.config["api_key"]
            )

            # Extrair dados do NPS
            phone = data.get('phone', '')
            question = data.get('question', 'De 0 a 10, como você avalia nosso atendimento?')
            scale_type = data.get('scale_type', 'stars')  # compatibilidade com Z-API
            delay_message = data.get('delayMessage')

            result = client.send_nps_poll(
                session=config.config["session_name"],
                phone=phone,
                question=question,
                scale_type=scale_type,
                delay_message=delay_message
            )

            # 🔍 DEBUG: Analisar resposta do WAHA para entender o formato
            logger.info("[WhatsAppProvider] WAHA send_nps_poll resultado recebido: present=%s", bool(result))
            logger.info(f"[WhatsAppProvider] WAHA send_nps_poll chaves: {list(result.keys()) if result else 'None'}")

            # WAHA retorna objeto WAMessage com campo 'id' (confirmado pelo OpenAPI.json)
            if result and 'id' in result:
                logger.info(f"[WhatsAppProvider] WAHA NPS message ID encontrado: {result['id']}")
            else:
                logger.warning("[WhatsAppProvider] WAHA NPS sem ID na resposta")

            return result

        except (WAHAException, WAHAConnectionError) as e:
            logger.error(f"Erro ao enviar NPS via WAHA: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    elif config.is_zapi():
        return zapi_utils.send_nps_poll(
            instance_id=config.config["instance_id"],
            instance_token=config.config["token"],
            data=data
        )
    elif config.is_wppconnect():
        raise HTTPException(
            status_code=501,
            detail="Enquetes NPS não são suportadas pelo WPPConnect no momento"
        )


def get_instance_status(company_id: int, db: Session) -> Dict[str, Any]:
    """
    Obtém status da instância usando o provider configurado.
    """
    config = WhatsAppConfig.from_company(company_id, db)
    if not config:
        raise HTTPException(status_code=400, detail="Configuração WhatsApp não encontrada")

    if config.is_waha():
        try:
            client = get_waha_client(
                base_url=config.config["base_url"],
                api_key=config.config["api_key"]
            )
            session = client.get_session(config.config["session_name"])
            return {
                "connected": session.status.value == "WORKING",
                "status": session.status.value,
                "session": session.name,
                "engine": session.engine.value,
                "me": session.me
            }
        except WAHAException as e:
            if "404" in str(e) or "Not Found" in str(e):
                logger.info(f"[WAHA Status] Sessão '{config.config['session_name']}' não existe")
                return {
                    "connected": False,
                    "status": "NOT_FOUND",
                    "session": config.config["session_name"],
                    "engine": "GOWS",
                    "me": None,
                    "message": "Sessão não encontrada. Use 'Iniciar Sessão' para criar uma nova sessão."
                }
            else:
                logger.error(f"Erro ao obter status via WAHA: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        except WAHAConnectionError as e:
            logger.error(f"Erro de conexão WAHA: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    elif config.is_zapi():
        from backend.routes.webhook import get_instance_status_from_zapi
        return get_instance_status_from_zapi(
            instance_id=config.config["instance_id"],
            instance_token=config.config["token"],
            client_token=CLIENT_TOKEN
        )
    elif config.is_wppconnect():
        try:
            client = get_wppconnect_client(
                session_name=config.config["session_name"],
                base_url=config.config["base_url"],
                secret_key=config.config["secret_key"]
            )
            status = client.get_session_status()
            return {
                "connected": status.get("status") == "CONNECTED",
                "status": status.get("status"),
                "session": config.config["session_name"]
            }
        except WPPConnectSDKError as e:
            logger.error(f"Erro ao obter status via WPPConnect: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@_serialize_company_remote_operation
def get_qrcode(company_id: int, db: Session) -> str:
    """
    Obtém QR Code usando o provider configurado.

    Returns:
        Base64 PNG do QR Code (data:image/png;base64,...)
    """
    config = WhatsAppConfig.from_company(company_id, db)
    if not config:
        raise HTTPException(status_code=400, detail="Configuração WhatsApp não encontrada")

    if config.is_waha():
        try:
            client = get_waha_client(
                base_url=config.config["base_url"],
                api_key=config.config["api_key"]
            )

            # Verificar status da sessão primeiro
            from backend.integrations.waha_sdk import SessionStatus
            session = client.get_session(config.config["session_name"])

            logger.info(f"[WAHA QR] Status atual da sessão: {session.status.value}")

            # Se a sessão está FAILED, fazer restart primeiro
            if session.status == SessionStatus.FAILED:
                logger.warning(f"[WAHA QR] Sessão em FAILED, fazendo restart...")
                client.restart_session(config.config["session_name"])

                # Aguardar alguns segundos para o restart
                import time
                time.sleep(3)

                # Verificar status novamente
                session = client.get_session(config.config["session_name"])
                logger.info(f"[WAHA QR] Status após restart: {session.status.value}")

            # Se já está WORKING (conectado), retornar erro apropriado
            if session.status == SessionStatus.WORKING:
                raise HTTPException(
                    status_code=400,
                    detail="WhatsApp já está conectado. Desconecte primeiro para gerar novo QR Code."
                )

            # Tentar obter QR Code
            qr_code = client.get_qr_code(config.config["session_name"])
            if not qr_code:
                raise HTTPException(
                    status_code=400,
                    detail="QR Code não disponível. Tente novamente em alguns segundos."
                )
            return qr_code

        except HTTPException:
            raise
        except (WAHAException, WAHAConnectionError) as e:
            logger.error(f"Erro ao obter QR Code via WAHA: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    elif config.is_zapi():
        from backend.routes.webhook import get_qrcode_from_zapi
        return get_qrcode_from_zapi(
            instance_id=config.config["instance_id"],
            instance_token=config.config["token"],
            client_token=CLIENT_TOKEN
        )
    elif config.is_wppconnect():
        try:
            client = get_wppconnect_client(
                session_name=config.config["session_name"],
                base_url=config.config["base_url"],
                secret_key=config.config["secret_key"]
            )
            qr_code = client.get_qr_code()
            if not qr_code:
                raise HTTPException(
                    status_code=400,
                    detail="QR Code não disponível. Sessão já conectada ou erro ao gerar."
                )
            return qr_code
        except WPPConnectSDKError as e:
            logger.error(f"Erro ao obter QR Code via WPPConnect: {e}")
            raise HTTPException(status_code=500, detail=str(e))


def get_device_data(company_id: int, db: Session) -> Dict[str, Any]:
    """
    Obtém dados do device usando o provider configurado.
    """
    config = WhatsAppConfig.from_company(company_id, db)
    if not config:
        raise HTTPException(status_code=400, detail="Configuração WhatsApp não encontrada")

    if config.is_waha():
        try:
            client = get_waha_client(
                base_url=config.config["base_url"],
                api_key=config.config["api_key"]
            )
            session = client.get_session(config.config["session_name"])

            # Mapear dados do 'me' para o formato esperado pelo frontend
            me = session.me or {}
            phone_number = ""
            if me.get("id"):
                # Extrair número do formato "550000000010@c.us"
                phone_number = me["id"].split("@")[0]

            # Buscar foto de perfil via endpoint /profile
            profile_pic_url = ""
            try:
                if session.status.value == "WORKING":
                    profile = client.get_profile(config.config["session_name"])
                    profile_pic_url = profile.get("picture", "")
                    logger.info("[WAHA] Foto de perfil obtida: present=%s", bool(profile_pic_url))
            except Exception as e:
                logger.warning(f"[WAHA] Não foi possível obter foto de perfil: {e}")

            return {
                "id": me.get("id", ""),
                "name": me.get("pushName", ""),
                "pushname": me.get("pushName", ""),  # Compatibilidade
                "phone": phone_number,
                "profilePicUrl": profile_pic_url,
                "isBusiness": False,
                "platform": "WhatsApp",
                "session_name": session.name,
                "status": session.status.value,
                "connected": session.status.value == "WORKING",
                "engine": session.engine.value,
                "me": me
            }
        except (WAHAException, WAHAConnectionError) as e:
            logger.error(f"Erro ao obter dados do device via WAHA: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    elif config.is_zapi():
        from backend.routes.webhook import get_device_data as zapi_get_device
        return zapi_get_device(
            instance_id=config.config["instance_id"],
            instance_token=config.config["token"],
            client_token=CLIENT_TOKEN
        )
    elif config.is_wppconnect():
        try:
            client = get_wppconnect_client(
                session_name=config.config["session_name"],
                base_url=config.config["base_url"],
                secret_key=config.config["secret_key"]
            )
            # WPPConnect não tem endpoint específico para device data
            # Retornar informações básicas da sessão
            status = client.get_session_status()
            return {
                "session_name": config.config["session_name"],
                "status": status.get("status"),
                "connected": status.get("status") == "CONNECTED"
            }
        except WPPConnectSDKError as e:
            logger.error(f"Erro ao obter dados do device via WPPConnect: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@_serialize_company_remote_operation
def send_call(company_id: int, phone: str, call_duration: int = 10, db: Session = None) -> Dict[str, Any]:
    """
    Envia chamada de voz via WhatsApp usando o provider configurado para a empresa.

    Args:
        company_id: ID da empresa
        phone: Telefone do destinatário
        call_duration: Duração da chamada em segundos (padrão: 10)
        db: Sessão do banco de dados

    Note:
        Apenas Z-API suporta chamadas de voz atualmente.
        WAHA e WPPConnect não suportam esta funcionalidade.
    """
    config = WhatsAppConfig.from_company(company_id, db)
    if not config:
        raise HTTPException(status_code=400, detail="Configuração WhatsApp não encontrada")

    if config.is_zapi():
        try:
            from backend.integrations.zapi_utils import send_call, SendCallRequest

            call_data = SendCallRequest(
                phone=phone,
                callDuration=call_duration
            )

            return send_call(
                instance_id=config.config["instance_id"],
                instance_token=config.config["token"],
                data=call_data
            )
        except Exception as e:
            logger.error(f"Erro ao enviar chamada via Z-API: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    elif config.is_waha():
        raise HTTPException(
            status_code=501,
            detail="Chamadas de voz não são suportadas pelo WAHA no momento"
        )
    elif config.is_wppconnect():
        raise HTTPException(
            status_code=501,
            detail="Chamadas de voz não são suportadas pelo WPPConnect no momento"
        )
