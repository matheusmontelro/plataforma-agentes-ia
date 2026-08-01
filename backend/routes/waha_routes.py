"""
Webhook endpoint para WAHA (WhatsApp HTTP API)

IMPORTANTE: Este arquivo é NOVO e NÃO modifica o sistema Z-API existente.
Z-API continua funcionando normalmente em backend/routes/webhook.py
"""

import logging
import uuid
import os
from typing import Dict, Any
from fastapi import APIRouter, Request, Depends, HTTPException, File, Form, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.db import get_db
from backend.webhook_audit import save_webhook_audit, update_audit_status
from backend.models import User
from backend.auth import get_current_user
from backend.services.company_access_control import get_company_operational_epoch
from starlette.concurrency import run_in_threadpool
import redis

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter()

# Redis para enfileirar mensagens
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=False)


def _resolve_waha_company_id(db: Session, session_name: str) -> int:
    rows = db.execute(
        text("""
            SELECT id FROM companies
             WHERE lower(btrim(waha_session_name)) = lower(btrim(:session_name))
               AND waha_enabled = true
               AND operational_status = 'active'
             ORDER BY id
        """),
        {"session_name": session_name},
    ).fetchall()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No company found with session '{session_name}' or WAHA not enabled",
        )
    if len(rows) > 1:
        company_ids = [row.id for row in rows]
        logger.error(
            "[WAHA Webhook] Sessão ambígua rejeitada: session=%s company_ids=%s",
            session_name,
            company_ids,
        )
        raise HTTPException(status_code=409, detail="Ambiguous WAHA session mapping")

    return rows[0].id


def _waha_webhook_summary(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return operational metadata without logging message or media contents."""
    payload = data.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    media = payload.get("media")
    media = media if isinstance(media, dict) else {}
    return {
        "event": data.get("event"),
        "session": data.get("session"),
        "engine": data.get("engine"),
        "payload_keys": sorted(str(key) for key in payload),
        "message_id_present": bool(payload.get("id")),
        "from_me": bool(payload.get("fromMe")),
        "message_type": payload.get("type"),
        "has_media": bool(media.get("url") or payload.get("mediaUrl")),
        "media_mimetype": media.get("mimetype"),
    }


@router.post("/waha/callback")
async def waha_message_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Recebe callbacks do WAHA e enfileira para processamento Celery

    WAHA envia payloads no formato (OpenAPI.json - WAHAWebhookMessage):
    {
      "id": "evt_01aaaaaaaaaaaaaaaaaaaaaaaa",  // ID do evento (ULID)
      "timestamp": 1634567890123,               // Unix timestamp em ms
      "session": "default",                     // Nome da sessão
      "engine": "GOWS",                         // Engine (WEBJS/NOWEB/GOWS)
      "event": "message",                       // Tipo de evento
      "payload": {                              // WAMessage
        "id": "false_11111111111@c.us_AAAA...",
        "from": "5500000000004@c.us",
        "body": "texto da mensagem",
        "timestamp": 1666943582,
        "fromMe": false,
        "hasMedia": false,
        ...
      },
      "me": { ... }                             // Informações do próprio número
    }

    Documentação: https://waha.devlike.pro/docs/how-to/webhooks/
    OpenAPI Spec: backend/integrations/waha_sdk/OpenAPI.json (schema: WAHAWebhookMessage)
    """
    try:
        logger.info("[WAHA Webhook] Recebendo callback do WAHA")

        # Parse do payload
        try:
            data = await request.json()
        except Exception as e:
            logger.error(f"[WAHA Webhook] Erro ao parsear JSON: {e}")
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        logger.info("[WAHA Webhook] Resumo recebido: %s", _waha_webhook_summary(data))

        # Extrair informações básicas
        event_type = data.get("event", "")
        session_name = data.get("session", "")
        payload = data.get("payload", {})

        # Validar campos obrigatórios
        if not session_name:
            logger.warning("[WAHA Webhook] Session name não fornecido")
            raise HTTPException(status_code=400, detail="Session name is required")

        # 🔥 FILTRO DE EVENTOS: aceitar mensagens e updates incrementais sem tratar ACK/reaction como nova bolha.
        logger.info(f"[WAHA Webhook] 📌 Tipo de evento recebido: '{event_type}'")

        # ✅ Aceitar eventos que o worker processa com semântica própria:
        # - message.any contém TODAS as criações de mensagem, incluindo as próprias
        # - message é aceito como fallback para engines/sessões que o enviam separado
        # - message.ack atualiza status da mensagem existente
        # - message.reaction atualiza metadados da mensagem existente
        # - poll.vote é necessário para processar votos NPS
        # - session.status é ESSENCIAL para auto-renovação de QR code
        accepted_events = ["message", "message.any", "message.ack", "message.reaction", "poll.vote", "session.status"]

        if event_type not in accepted_events:
            logger.info(f"[WAHA Webhook] ⏭️ Evento '{event_type}' ignorado para evitar duplicação (aceitos: {', '.join(accepted_events)})")
            return {"status": "ignored", "reason": "event_type_not_supported", "event_type": event_type}

        logger.info(f"[WAHA Webhook] ✅ Evento '{event_type}' aceito para processamento")

        # Identificar empresa sem aceitar mapeamento ambíguo entre tenants.
        company_id = _resolve_waha_company_id(db, session_name)
        logger.info(f"[WAHA Webhook] Empresa identificada: company_id={company_id}")

        # 🔒 DEDUPLICAÇÃO: cada evento de criação tem namespace próprio.
        # Assim "message" nunca suprime o download/enriquecimento de "message.any".
        message_id_waha = payload.get("id", "")
        if event_type == "poll.vote":
            vote = payload.get("vote")
            vote = vote if isinstance(vote, dict) else {}
            message_id_waha = vote.get("id", "")

        if message_id_waha and event_type in {"message", "message.any", "poll.vote"}:
            audit_message_type = f"waha:{event_type}"
            dedupe_key = f"waha:{company_id}:{event_type}:{message_id_waha}"
            db.execute(
                text("""
                    SELECT pg_advisory_xact_lock(
                        hashtextextended(:dedupe_key, 0)
                    )
                """),
                {"dedupe_key": dedupe_key},
            )
            existing_audit = db.execute(
                text("""
                    SELECT id FROM webhook_audit
                    WHERE company_id = :company_id
                    AND message_id = :message_id
                    AND message_type = :message_type
                    AND status <> 'queue_failed'
                    AND created_at > NOW() - INTERVAL '5 minutes'
                    LIMIT 1
                """),
                {
                    "company_id": company_id,
                    "message_id": message_id_waha,
                    "message_type": audit_message_type,
                }
            ).fetchone()

            if existing_audit:
                logger.warning(f"[WAHA Webhook] ⚠️ Mensagem {message_id_waha} já foi processada recentemente (audit_id={existing_audit.id})")
                logger.warning(f"[WAHA Webhook] IGNORANDO para evitar duplicação por race condition")
                db.rollback()
                return {
                    "status": "duplicate",
                    "reason": "message_already_processed",
                    "audit_id": existing_audit.id
                }

        # Criar registro de auditoria
        audit_id = None
        try:
            # 🔧 CORREÇÃO: Usar save_webhook_audit com instance_id e payload completo
            audit_id = save_webhook_audit(
                db=db,
                instance_id=f"company_{company_id}_waha",
                data=payload,
                company_id=company_id,
                message_id=message_id_waha,
                event_type=event_type,
            )
            logger.info(f"[WAHA Webhook] Auditoria criada: audit_id={audit_id}, message_id={payload.get('id', 'N/A')}")
        except Exception as e:
            logger.warning(f"[WAHA Webhook] Erro ao criar auditoria: {e}", exc_info=True)

        # Enfileirar mensagem para processamento assíncrono via Celery
        try:
            from backend.worker.process_message_waha import process_incoming_waha_message

            # Adicionar dados de contexto (incluindo TODOS os tipos de eventos)
            # A leitura MVCC não espera o fence. O worker durável revalida este
            # epoch sob try-lock e reagenda o payload se houver disputa.
            operational_epoch = get_company_operational_epoch(db, company_id)
            task_data = {
                "payload": data,
                "session_name": session_name,
                "audit_id": audit_id,
                "company_id": company_id,
                "operational_epoch": operational_epoch,
                "debug_mode": True  # Flag para debug de eventos especiais
            }

            # Enfileirar task Celery
            task = process_incoming_waha_message.apply_async(
                args=[task_data],
                queue='waha_messages_queue'
            )

            logger.info(f"[WAHA Webhook] Mensagem enfileirada: task_id={task.id}, queue=waha_messages_queue")

            # Atualizar status da auditoria
            if audit_id:
                update_audit_status(db, audit_id, "queued")
            else:
                db.commit()

            return {
                "status": "queued",
                "task_id": task.id,
                "audit_id": audit_id,
                "company_id": company_id
            }

        except Exception as e:
            logger.error(f"[WAHA Webhook] Erro ao enfileirar mensagem: {e}")
            if audit_id:
                update_audit_status(db, audit_id, "queue_failed", error=str(e))
            raise HTTPException(status_code=500, detail=f"Failed to queue message: {str(e)}")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[WAHA Webhook] Erro inesperado: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/waha/send-voice")
async def send_voice_direct(
    phone: str = Form(...),
    audio: UploadFile = File(...),
    convert: bool = Form(True),
    session: str = Form(None),  # Opcional - backend descobre se não fornecido
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Endpoint otimizado para envio direto de áudio via WAHA

    🔥 NOVO: Formato simplificado compatível com frontend
    - Aceita Blob diretamente (sem base64)
    - Usa mesma lógica do agents_sdk/waha_utils
    - Performance ~60% melhor que fluxo atual

    Args:
        phone: Telefone destino (ex: "5500000000004")
        session: Nome da sessão WAHA (ex: "default")
        audio: Arquivo de áudio (UploadFile)
        convert: Converter formato automaticamente (default: True)

    Returns:
        Dict com resposta do WAHA

    Example:
        FormData:
        - phone: "5500000000004"
        - session: "default"
        - audio: [File WebM/OGG/MP3]
        - convert: "true"
    """
    logger.info(f"[WAHA Direct Voice] Enviando áudio para {phone} (session: {session})")
    logger.info(f"[WAHA Direct Voice] Arquivo: {audio.filename}, Tipo: {audio.content_type}")

    try:
        # Validar arquivo de áudio
        if not audio.content_type or not audio.content_type.startswith('audio/'):
            logger.error(f"[WAHA Direct Voice] Tipo de arquivo inválido: {audio.content_type}")
            raise HTTPException(status_code=400, detail="O arquivo deve ser um áudio")

        # Ler bytes diretos do arquivo (sem base64!)
        audio_bytes = await audio.read()
        logger.info(f"[WAHA Direct Voice] Áudio lido: {len(audio_bytes)} bytes, tipo: {audio.content_type}")

        if len(audio_bytes) == 0:
            raise HTTPException(status_code=400, detail="Arquivo de áudio vazio")

        # 🔥 CONVERSÃO CRUCIAL: WebM/Opus -> MP3 (como no sistema tradicional)
        # WAHA precisa de áudio com metadados de duração para evitar corrupção
        converted_audio_bytes = audio_bytes
        try:
            import magic
            import tempfile
            import subprocess

            # Detectar formato real do áudio
            mime = magic.Magic(mime=True)
            audio_format = mime.from_buffer(audio_bytes)
            logger.info(f"[WAHA Direct Voice] Formato detectado: {audio_format}")

            # 🎯 CONVERSÃO CORRETA: WebM -> OGG/Opus (formato nativo WhatsApp)
            # Documentação WAHA: "mimetype": "audio/ogg; codecs=opus"
            if 'webm' in audio_format.lower():
                logger.info(f"[WAHA Direct Voice] Convertendo {audio_format} para OGG/Opus (formato WAHA)")

                # Salvar WebM temporário
                with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as temp_input:
                    temp_input.write(audio_bytes)
                    temp_input_path = temp_input.name

                # Arquivo OGG de saída
                with tempfile.NamedTemporaryFile(suffix='.opus', delete=False) as temp_output:
                    temp_output_path = temp_output.name

                try:
                    # Converter WebM para OGG/Opus usando ffmpeg
                    result = subprocess.run(
                        [
                            'ffmpeg', '-i', temp_input_path,
                            '-c:a', 'libopus', '-b:a', '32k',  # Taxa de bits otimizada para voz
                            '-ar', '48000', '-ac', '1',       # Sample rate e mono como WhatsApp
                            '-vbr', 'on',                    # Variable bitrate para melhor qualidade
                            '-y', temp_output_path
                        ],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )

                    if result.returncode != 0:
                        logger.error(f"[WAHA Direct Voice] Erro ffmpeg: {result.stderr}")
                        logger.warning("[WAHA Direct Voice] Falha na conversão, usando WebM original")
                    else:
                        # Ler arquivo OGG/Opus convertido
                        with open(temp_output_path, 'rb') as f:
                            converted_audio_bytes = f.read()
                        logger.info(f"[WAHA Direct Voice] Conversão WebM->OGG/Opus bem sucedida: {len(converted_audio_bytes)} bytes")

                except subprocess.TimeoutExpired:
                    logger.error("[WAHA Direct Voice] Timeout na conversão ffmpeg")
                except Exception as e:
                    logger.error(f"[WAHA Direct Voice] Erro na conversão: {e}")
                finally:
                    # Limpar arquivos temporários
                    import os
                    try:
                        os.unlink(temp_input_path)
                        os.unlink(temp_output_path)
                    except:
                        pass
            elif 'ogg' in audio_format.lower():
                logger.info("[WAHA Direct Voice] Áudio já está em OGG, usando sem conversão")
            else:
                logger.warning(f"[WAHA Direct Voice] Formato {audio_format} não é WebM/Opus, usando original")

        except ImportError:
            logger.warning("[WAHA Direct Voice] python-magic não instalado, pulando conversão automática")
        except Exception as e:
            logger.error(f"[WAHA Direct Voice] Erro ao detectar/converter formato: {e}")
            logger.warning("[WAHA Direct Voice] Usando áudio original como fallback")

        # Se session não fornecida, descobrir pela empresa do usuário logado
        if not session:
            company_id = current_user.company_id
            logger.info(f"[WAHA Direct Voice] Descobrindo session para company_id: {company_id}")

            company_row = db.execute(
                text("""
                    SELECT waha_session_name FROM companies
                    WHERE id = :company_id
                    AND waha_enabled = true
                """),
                {"company_id": company_id}
            ).fetchone()

            if not company_row or not company_row.waha_session_name:
                logger.error(f"[WAHA Direct Voice] Empresa {company_id} não tem WAHA habilitado ou sessão configurada")
                raise HTTPException(
                    status_code=404,
                    detail=f"Empresa não tem WAHA habilitado ou sessão não configurada"
                )

            session = company_row.waha_session_name
            logger.info(f"[WAHA Direct Voice] Session descoberta: {session}")
        else:
            # Obter company_id a partir da session fornecida
            company_row = db.execute(
                text("""
                    SELECT id FROM companies
                    WHERE waha_session_name = :session_name
                    AND waha_enabled = true
                """),
                {"session_name": session}
            ).fetchone()

            if not company_row:
                logger.error(f"[WAHA Direct Voice] Empresa não encontrada para session: {session}")
                raise HTTPException(
                    status_code=404,
                    detail=f"Nenhuma empresa encontrada com session '{session}' ou WAHA não habilitado"
                )

            company_id = company_row.id

        logger.info(f"[WAHA Direct Voice] Empresa identificada: {company_id}, session: {session}")

        # Usar lógica existente do waha_utils (NÃO modificar função existente!)
        from backend.integrations.waha_utils import send_audio_to_waha

        result = await run_in_threadpool(
            send_audio_to_waha,
            waha_session_name=session,
            phone=phone,
            audio_bytes=converted_audio_bytes,
            company_id=company_id,
        )

        logger.info(f"[WAHA Direct Voice] ✅ Áudio enviado com sucesso!")
        return {
            "status": "success",
            "message": "Áudio enviado via WAHA com sucesso!",
            "phone": phone,
            "session": session,
            "audio_size": len(audio_bytes),
            "audio_type": audio.content_type,
            "waha_response": result
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[WAHA Direct Voice] ❌ Erro ao enviar áudio: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao enviar áudio via WAHA: {str(e)}")


@router.post("/send-voice")
async def send_voice_direct_api(
    phone: str = Form(...),
    audio: UploadFile = File(...),
    convert: bool = Form(True),
    session: str = Form(None),  # Opcional - backend descobre se não fornecido
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Alias endpoint otimizado para envio direto de áudio via WAHA

    Rota alternativa: /api/waha/send-voice (mesma funcionalidade)
    """
    # Reutiliza a lógica da função original
    return await send_voice_direct(phone, audio, convert, session, db, current_user)


@router.get("/waha/health")
async def waha_webhook_health():
    """Health check endpoint para webhook WAHA"""
    return {
        "status": "healthy",
        "provider": "waha",
        "webhook_endpoint": "/webhook/waha/callback",
        "direct_voice_endpoint": "/api/waha/send-voice",
        "engine": os.getenv("WAHA_DEFAULT_ENGINE") or os.getenv("WHATSAPP_DEFAULT_ENGINE") or "GOWS",
        "documentation": "https://waha.devlike.pro/docs/"
    }
