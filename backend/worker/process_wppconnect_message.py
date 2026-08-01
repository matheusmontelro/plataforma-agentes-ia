"""
Worker otimizado para processar mensagens do WPPConnect
Integração completa com Agents SDK e fallback para LangChain
Versão: 1.0 - 2025-10-07
"""

import logging
import json
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import SessionLocal
from backend.worker.celery_app import app
from backend.ws_manager import manager
from backend.prompt.memory.memory_manager import append_message_to_chat_file

logger = logging.getLogger(__name__)


def convert_wppconnect_to_zapi_format(wppconnect_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converte payload WPPConnect para formato compatível com Z-API

    WPPConnect payload real (onmessage event):
    {
        "event": "onmessage",
        "session": "teste",
        "id": "false_5500900000001@c.us_3FC36C78A83217FF51BD",
        "body": "oi",
        "type": "chat",
        "from": "5500000000001@c.us",
        "to": "5500000000008@c.us",
        "notifyName": "Cliente Exemplo",
        "t": 1759880310,
        "ack": 1,
        "isNewMsg": true
    }

    Z-API formato esperado:
    {
        "instanceId": "session_name",
        "messageId": "message_id",
        "phone": "5500000000001",
        "fromMe": false,
        "momment": 1704672000,
        "status": "RECEIVED",
        "chatName": "Contato Exemplo",
        "senderPhoto": "",
        "senderName": "Contato Exemplo",
        "participantPhone": null,
        "photo": "",
        "broadcast": false,
        "type": "ReceivedCallback",
        "text": {"message": "Texto da mensagem"}
    }
    """

    # Verificar se mensagem é enviada por mim
    # fromMe pode estar na raiz ou dentro de "id" (dependendo do evento)
    id_obj = wppconnect_data.get("id", {})
    from_me = False

    if isinstance(id_obj, dict):
        from_me = id_obj.get("fromMe", False)

    # Fallback: verificar na raiz também
    if not from_me:
        from_me = wppconnect_data.get("fromMe", False)

    # Extrair telefone (se fromMe=true, usar "to", senão usar "from")
    if from_me:
        # Mensagem ENVIADA por nós: usar "to" (destinatário)
        phone_jid = wppconnect_data.get("to", "")
    else:
        # Mensagem RECEBIDA: usar "from" (remetente)
        phone_jid = wppconnect_data.get("from", "")

    phone = phone_jid.split("@")[0] if "@" in phone_jid else phone_jid
    to_jid = wppconnect_data.get("to", "")

    # Extrair tipo de mensagem
    msg_type = wppconnect_data.get("type", "chat")

    # Timestamp (WPPConnect usa "t" em segundos)
    timestamp = wppconnect_data.get("t", int(datetime.now().timestamp()))

    # Estrutura base compatível com Z-API
    zapi_format = {
        "instanceId": wppconnect_data.get("session", ""),
        "messageId": wppconnect_data.get("id", ""),
        "phone": phone,
        "fromMe": from_me,
        "momment": timestamp,
        "status": "RECEIVED",
        "chatName": wppconnect_data.get("notifyName", ""),
        "senderPhoto": "",
        "senderName": wppconnect_data.get("notifyName", ""),
        "participantPhone": None,
        "photo": "",
        "broadcast": False,
        "type": "ReceivedCallback"
    }

    # Processar tipo de mensagem
    if msg_type == "chat":
        # Mensagem de texto simples
        zapi_format["text"] = {
            "message": wppconnect_data.get("body", "")
        }

    elif msg_type == "image":
        # Mensagem de imagem
        zapi_format["image"] = {
            "mimeType": wppconnect_data.get("mimetype", "image/jpeg"),
            "imageUrl": wppconnect_data.get("body", ""),  # WPPConnect pode ter URL aqui
            "thumbnailUrl": wppconnect_data.get("thumbnail", ""),
            "caption": wppconnect_data.get("caption", "")
        }
        zapi_format["text"] = {
            "message": wppconnect_data.get("caption", "")
        }

    elif msg_type in ["ptt", "audio"]:
        # Mensagem de áudio
        zapi_format["audio"] = {
            "audioUrl": wppconnect_data.get("body", ""),
            "mimeType": wppconnect_data.get("mimetype", "audio/ogg; codecs=opus")
        }

    elif msg_type == "video":
        # Mensagem de vídeo
        zapi_format["video"] = {
            "videoUrl": wppconnect_data.get("body", ""),
            "mimeType": wppconnect_data.get("mimetype", "video/mp4"),
            "caption": wppconnect_data.get("caption", "")
        }
        zapi_format["text"] = {
            "message": wppconnect_data.get("caption", "")
        }

    elif msg_type == "document":
        # Mensagem de documento
        zapi_format["document"] = {
            "documentUrl": wppconnect_data.get("body", ""),
            "mimeType": wppconnect_data.get("mimetype", ""),
            "fileName": wppconnect_data.get("filename", "documento")
        }

    logger.info(f"[WPPCONNECT→ZAPI] Convertido {msg_type} para formato Z-API")

    return zapi_format


@app.task(name='process_incoming_wppconnect_message', bind=True, max_retries=3)
def process_incoming_wppconnect_message(
    self,
    wppconnect_data: Dict[str, Any],
    session_name: str,
    audit_id: Optional[int] = None
):
    """
    Tarefa Celery para processar mensagens do WPPConnect
    Integração completa com Agents SDK e whatsapp_provider

    Args:
        wppconnect_data: Payload do evento messages-upsert do WPPConnect
        session_name: Nome da sessão WPPConnect (wppconnect_session_name)
        audit_id: ID do registro na tabela webhook_audit (opcional)

    Fluxo:
      1) Validações básicas (fromMe, empresa existe)
      2) Converte payload WPPConnect → formato Z-API
      3) Verifica se empresa tem Agents SDK habilitado
      4) Se SIM: Processa com Agents SDK
      5) Se NÃO: Processa com LangChain legado (burst_processor)
      6) Responde via WPPConnect usando whatsapp_provider
    """

    db: Session = SessionLocal()

    try:
        logger.info(
            f"[WPPCONNECT-WORKER] Iniciando processamento. "
            f"session={session_name}, audit_id={audit_id}"
        )

        # 🔍 DEBUG: Log completo do payload para monitorar futuros campos de Meta Ads
        # Campos esperados de Meta Ads (se implementado no futuro): source_id, sender_lid,
        # thumbnail_url, referral, ctwa_clid, ad_id, campaign_id
        logger.info(f"[WPPCONNECT-WORKER] 🔍 PAYLOAD COMPLETO (DEBUG): {json.dumps(wppconnect_data, indent=2)}")

        # ============================================
        # 1. VALIDAÇÕES BÁSICAS
        # ============================================

        # 1.1. Detectar tipo de evento e fromMe
        event_type = wppconnect_data.get("event", "")

        # fromMe pode estar em diferentes lugares dependendo do formato
        id_obj = wppconnect_data.get("id", {})
        from_me = id_obj.get("fromMe", False) if isinstance(id_obj, dict) else False

        # Também verificar na raiz (fallback)
        if not from_me:
            from_me = wppconnect_data.get("fromMe", False)

        # 1.2. Decidir fluxo de processamento
        # - onmessage com fromMe=false: Mensagem RECEBIDA (processar normalmente)
        # - onack com fromMe=true: Mensagem ENVIADA pelo sistema (salvar no banco)
        # - Outros: Ignorar

        if event_type == "onmessage" and not from_me:
            # Fluxo normal: mensagem recebida do usuário
            logger.info("[WPPCONNECT-WORKER] 📥 Mensagem RECEBIDA do usuário")

        elif event_type == "onack" and from_me:
            # Fluxo especial: confirmação de mensagem ENVIADA pelo sistema
            logger.info("[WPPCONNECT-WORKER] 📤 Confirmação de mensagem ENVIADA (onack + fromMe=true)")
            # Este fluxo será tratado em seção separada abaixo

        else:
            # Ignorar outros eventos
            logger.info(
                f"[WPPCONNECT-WORKER] Evento ignorado: event={event_type}, "
                f"fromMe={from_me} (apenas onmessage com fromMe=false ou onack com fromMe=true)"
            )
            return {"status": "ignored", "reason": f"event={event_type}, fromMe={from_me}"}

        # 1.3. Buscar company_id baseado no session_name
        company_row = db.execute(
            text("SELECT id FROM companies WHERE wppconnect_session_name = :session_name"),
            {"session_name": session_name}
        ).fetchone()

        if not company_row:
            logger.error(f"[WPPCONNECT-WORKER] Empresa não encontrada para session={session_name}")
            return {"status": "error", "reason": "company_not_found"}

        company_id = company_row.id
        logger.info(f"[WPPCONNECT-WORKER] Empresa encontrada: company_id={company_id}")

        # ============================================
        # 2. CONVERSÃO DE FORMATO
        # ============================================

        # 2.1. Converter payload WPPConnect → Z-API format
        zapi_format_data = convert_wppconnect_to_zapi_format(wppconnect_data)
        zapi_format_data["instanceId"] = session_name

        logger.info(
            f"[WPPCONNECT-WORKER] Payload convertido para Z-API format: "
            f"{json.dumps(zapi_format_data)[:500]}"
        )

        # 2.2. Extrair dados básicos
        phone = zapi_format_data.get("phone", "")
        sender_name = zapi_format_data.get("senderName", "")
        message_text = zapi_format_data.get("text", {}).get("message", "")

        if not phone:
            logger.error("[WPPCONNECT-WORKER] Telefone não encontrado no payload")
            return {"status": "error", "reason": "phone_not_found"}

        logger.info(
            f"[WPPCONNECT-WORKER] Dados extraídos: "
            f"phone={phone}, sender={sender_name}, message_length={len(message_text)}"
        )

        # ============================================
        # FLUXO ESPECIAL: onack com fromMe=true
        # Salvar mensagens ENVIADAS pelo sistema no banco
        # ============================================

        if event_type == "onack" and from_me:
            logger.info("[WPPCONNECT-WORKER] 📤 Processando mensagem ENVIADA (onack + fromMe=true)")

            # Buscar client_id
            row_owner = db.execute(
                text("""
                    SELECT client_id
                      FROM client_companies
                     WHERE company_id = :cid
                     ORDER BY id
                     LIMIT 1
                """),
                {"cid": company_id}
            ).fetchone()

            if not row_owner:
                logger.warning(f"[WPPCONNECT-WORKER] Nenhum client_id encontrado para company_id={company_id}")
                return {"status": "error", "reason": "client_not_found"}

            client_id_db = row_owner.client_id

            # Extrair messageId
            message_id = id_obj.get("id", "") if isinstance(id_obj, dict) else ""
            if not message_id:
                message_id = wppconnect_data.get("messageId", "")

            # Verificar se mensagem já existe no banco (evitar duplicação)
            if message_id:
                existing = db.execute(text("""
                    SELECT id FROM messages
                    WHERE zapi_message_id = :msg_id
                    LIMIT 1
                """), {"msg_id": message_id}).fetchone()

                if existing:
                    logger.info(f"[WPPCONNECT-WORKER] ✅ Mensagem enviada já existe no banco: {message_id}")
                    return {"status": "success", "reason": "already_saved"}

            # Salvar no messages table
            try:
                db.execute(text("""
                    INSERT INTO messages
                        (client_id, company_id, contact_phone, message_type, content,
                        sender_phone, sender_name, from_me, zapi_message_id)
                    VALUES (:client_id, :company_id, :contact_phone, 'text', :content,
                            'me', 'Sistema', true, :zapi_message_id)
                """), {
                    "client_id": client_id_db,
                    "company_id": company_id,
                    "contact_phone": phone,
                    "content": message_text,
                    "zapi_message_id": message_id
                })
                db.commit()
                logger.info(f"[WPPCONNECT-WORKER] ✅ Mensagem ENVIADA salva no banco: {phone}")
            except Exception as save_err:
                logger.warning(f"[WPPCONNECT-WORKER] Erro ao salvar mensagem enviada: {save_err}")
                try:
                    db.rollback()
                except:
                    pass

            # Salvar no .txt file
            try:
                append_message_to_chat_file(company_id, phone, True, message_text)
                logger.info(f"[WPPCONNECT-WORKER] ✅ Mensagem ENVIADA salva no .txt: {phone}")
            except Exception as txt_err:
                logger.warning(f"[WPPCONNECT-WORKER] Erro ao salvar .txt: {txt_err}")

            # WebSocket broadcast
            try:
                import uuid
                from datetime import datetime
                from backend.integrations.broadcast_redis import publish_to_redis

                ws_payload = {
                    "type": "text",
                    "content": message_text,
                    "phone": phone,
                    "senderName": "Sistema",
                    "photo": "",
                    "fromMe": True,
                    "fromApi": False,  # Mensagem do WhatsApp (não da API) - necessário para o frontend exibir
                    "messageId": message_id or f"onack_{uuid.uuid4()}",
                    "momment": datetime.utcnow().isoformat(),
                    "company_id": company_id
                }
                publish_to_redis(company_id, ws_payload)
                logger.info(f"[WPPCONNECT-WORKER] ✅ WebSocket broadcast: {phone}")
            except Exception as ws_err:
                logger.warning(f"[WPPCONNECT-WORKER] Erro no WebSocket: {ws_err}")

            return {
                "status": "success",
                "company_id": company_id,
                "phone": phone,
                "message_type": "sent_confirmation"
            }

        # ============================================
        # FLUXO NORMAL: onmessage com fromMe=false
        # Processar mensagens RECEBIDAS do usuário
        # ============================================

        # 2.3. Buscar client_id associado à empresa
        row_owner = db.execute(
            text("""
                SELECT client_id
                  FROM client_companies
                 WHERE company_id = :cid
                 ORDER BY id
                 LIMIT 1
            """),
            {"cid": company_id}
        ).fetchone()

        if not row_owner:
            logger.error("[WPPCONNECT-WORKER] Nenhum client associado a esta empresa")
            return {"status": "error", "reason": "client_not_found"}

        client_id_db = row_owner.client_id
        logger.info(f"[WPPCONNECT-WORKER] Client encontrado: client_id={client_id_db}")

        # ============================================
        # 2.5. ETAPAS DE SALVAMENTO (REPLICAR Z-API)
        # ============================================

        # ETAPA 4: Salvar mensagem em 'messages'
        msg_type = "text"
        content = message_text
        from_me = False  # WPPConnect só processa mensagens recebidas
        from_api = False  # Mensagens do WPPConnect não são via API

        # Extrair message_id do payload convertido
        message_id = zapi_format_data.get("messageId", "")

        # Verificar duplicação (evitar salvar mensagem duplicada)
        if message_id:
            existing_msg = db.execute(text("""
                SELECT id FROM messages
                WHERE zapi_message_id = :msg_id
                LIMIT 1
            """), {"msg_id": message_id}).fetchone()

            if existing_msg:
                logger.info(f"[WPPCONNECT-WORKER] Mensagem {message_id} já existe, ignorando duplicação")
            else:
                # Salvar mensagem
                db.execute(text("""
                    INSERT INTO messages
                           (client_id, company_id, contact_phone, message_type, content,
                            sender_phone, sender_name, from_me, zapi_message_id)
                    VALUES (:client_id, :company_id, :contact_phone, :message_type, :content,
                            :sender_phone, :sender_name, :from_me, :zapi_message_id)
                """), {
                    "client_id": client_id_db,
                    "company_id": company_id,
                    "contact_phone": phone,
                    "message_type": msg_type,
                    "content": content,
                    "sender_phone": phone,
                    "sender_name": sender_name,
                    "from_me": from_me,
                    "zapi_message_id": message_id
                })

                # Atualizar last_message_at no contato
                db.execute(text("""
                    UPDATE contacts
                    SET last_message_at = NOW()
                    WHERE client_id = :client_id AND phone = :contact_phone
                """), {
                    "client_id": client_id_db,
                    "contact_phone": phone
                })

                db.commit()
                logger.info(f"[WPPCONNECT-WORKER] Mensagem salva: {message_id}")

        # ETAPA 5: Salvar em arquivo de memória
        if not from_me:
            append_message_to_chat_file(company_id, phone, False, content)

        # ETAPA 6: Criar/atualizar contacts
        contact_name = sender_name if sender_name else phone
        contact_exists = db.execute(text("""
            SELECT id, name FROM contacts
            WHERE client_id = :client_id AND phone = :phone
        """), {"client_id": client_id_db, "phone": phone}).fetchone()

        if contact_exists:
            logger.info("[WPPCONNECT-WORKER] Contato existe, atualizando")
            db.execute(text("""
                UPDATE contacts
                SET name = CASE
                           WHEN name IS NULL OR name = '' OR name = :phone
                           THEN :name
                           ELSE name
                           END
                WHERE client_id = :client_id
                  AND phone = :phone
            """), {
                "name": contact_name,
                "phone": phone,
                "client_id": client_id_db
            })
        else:
            logger.info("[WPPCONNECT-WORKER] Criando novo contato")
            db.execute(text("""
                INSERT INTO contacts
                    (client_id, company_id, phone, name)
                VALUES (:client_id, :company_id, :phone, :name)
            """), {
                "client_id": client_id_db,
                "company_id": company_id,
                "phone": phone,
                "name": contact_name
            })

        # ETAPA 7: Criar/atualizar leads
        # WPPConnect não possui source_id/sender_lid de Meta Ads (só Z-API tem)
        # Mas criamos lead para rastreamento e preparação para futuras integrações

        # Extrair campos de Meta Ads (se existirem no futuro)
        source_id = wppconnect_data.get("source_id") or wppconnect_data.get("ad_id")
        sender_lid = wppconnect_data.get("sender_lid")
        thumbnail_url = wppconnect_data.get("thumbnail_url")
        referral_obj = wppconnect_data.get("referral")
        ctwa_clid = wppconnect_data.get("ctwa_clid")

        # Debug para monitorar se campos de anúncios chegarem no futuro
        logger.info(
            f"[WPPCONNECT-WORKER] 🔍 Meta Ads Check: "
            f"source_id={source_id}, sender_lid={sender_lid}, "
            f"thumbnail_url={thumbnail_url}, referral={bool(referral_obj)}, "
            f"ctwa_clid={ctwa_clid}"
        )

        # Verificar se lead já existe
        existing_lead = db.execute(text("""
            SELECT id FROM leads
            WHERE company_id = :company_id AND phone = :phone
            LIMIT 1
        """), {"company_id": company_id, "phone": phone}).fetchone()

        if not existing_lead:
            # Criar novo lead (sempre, mesmo sem dados de anúncio)
            try:
                # created_at é VARCHAR, não timestamp - usar formato string
                from datetime import datetime
                import pytz

                tz = pytz.timezone('America/Sao_Paulo')
                created_at_str = datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')

                db.execute(text("""
                    INSERT INTO leads (
                        client_id, company_id, phone, name,
                        source_id, sender_lid, thumbnail_url, created_at
                    ) VALUES (
                        :client_id, :company_id, :phone, :name,
                        :source_id, :sender_lid, :thumbnail_url, :created_at
                    )
                """), {
                    "client_id": str(client_id_db),
                    "company_id": company_id,
                    "phone": phone,
                    "name": sender_name or phone,
                    "source_id": source_id,
                    "sender_lid": sender_lid,
                    "thumbnail_url": thumbnail_url,
                    "created_at": created_at_str
                })
                db.commit()
                logger.info(
                    f"[WPPCONNECT-WORKER] ✅ Lead criado: phone={phone}, "
                    f"has_ad_data={bool(source_id or sender_lid)}"
                )
            except Exception as e:
                logger.warning(f"[WPPCONNECT-WORKER] Lead já existe ou erro ao criar: {e}")
                db.rollback()
        else:
            logger.info(f"[WPPCONNECT-WORKER] Lead já existe: phone={phone}")

        # ETAPA 8: Incrementar unread_count
        db.execute(text("""
            UPDATE contacts
            SET unread_count = unread_count + 1
            WHERE client_id = :client_id
              AND company_id = :company_id
              AND phone = :phone
        """), {
            "client_id": client_id_db,
            "company_id": company_id,
            "phone": phone
        })

        db.commit()
        logger.info("[WPPCONNECT-WORKER] Unread count incrementado")

        # ETAPA 10: Broadcast WebSocket
        from backend.integrations.broadcast_redis import publish_to_redis
        message_payload = {
            "type": msg_type,
            "content": content,
            "phone": phone,
            "senderName": sender_name,
            "fromMe": from_me,
            "messageId": message_id,
            "company_id": company_id,
            "fromApi": from_api
        }
        publish_to_redis(company_id, message_payload)
        logger.info("[WPPCONNECT-WORKER] Mensagem publicada no Redis")

        # ETAPA 13: Verificar human_mode (antes de processar LLM)
        row_human_mode = db.execute(text("""
            SELECT human_mode FROM contacts
            WHERE client_id = :client_id
              AND company_id = :company_id
              AND phone = :phone
            LIMIT 1
        """), {
            "client_id": client_id_db,
            "company_id": company_id,
            "phone": phone
        }).fetchone()

        if row_human_mode and row_human_mode.human_mode:
            logger.info("[WPPCONNECT-WORKER] Human mode ativo - pulando LLM")
            return {
                "status": "ignored",
                "reason": "human_mode",
                "company_id": company_id,
                "session_name": session_name
            }

        # ETAPA 15: Verificar horário de IA (antes de processar LLM)
        row_ai = db.execute(text("""
            SELECT timezone, time_windows
            FROM ai_response_windows
            WHERE company_id = :cid
            ORDER BY id DESC
            LIMIT 1
        """), {"cid": company_id}).fetchone()

        if row_ai and row_ai.time_windows:
            import json as json_lib
            time_windows = row_ai.time_windows if isinstance(row_ai.time_windows, dict) else json_lib.loads(row_ai.time_windows)

            # Importar função de verificação de horário
            from backend.worker.process_message import is_ia_enabled_now

            if not is_ia_enabled_now(row_ai.timezone, time_windows):
                logger.info("[WPPCONNECT-WORKER] Fora do horário de IA - pulando LLM")
                return {
                    "status": "ignored",
                    "reason": "outside_ai_hours",
                    "company_id": company_id,
                    "session_name": session_name
                }
        else:
            logger.info("[WPPCONNECT-WORKER] Sem configuração de horário IA - pulando LLM")
            return {
                "status": "ignored",
                "reason": "no_ai_config",
                "company_id": company_id,
                "session_name": session_name
            }

        from backend.services.ai_credit_guard import ai_credit_block_result_from_balance, is_ai_credit_block_result

        credit_block = ai_credit_block_result_from_balance(
            db=db,
            company_id=company_id,
            source="wppconnect_worker",
        )
        if credit_block:
            logger.info("[WPPCONNECT-WORKER] IA bloqueada por saldo de créditos")
            return {
                "status": "ignored",
                "reason": credit_block.get("reason", "insufficient_ai_credits"),
                "company_id": company_id,
                "session_name": session_name,
                "blocked_by_ai_credits": True,
            }

        # ============================================
        # 3. VERIFICAR AGENTS SDK
        # ============================================

        # 3.1. Verificar se empresa tem Agents SDK habilitado
        try:
            from backend.agents_sdk.config import is_company_enabled as is_agents_sdk_enabled

            agents_sdk_enabled = is_agents_sdk_enabled(company_id, db)
            logger.info(f"[WPPCONNECT-WORKER] Agents SDK enabled: {agents_sdk_enabled}")

        except Exception as e:
            logger.warning(f"[WPPCONNECT-WORKER] Erro ao verificar Agents SDK: {e}")
            agents_sdk_enabled = False

        # ============================================
        # 4. PROCESSAR COM AGENTS SDK (SE HABILITADO)
        # ============================================

        if agents_sdk_enabled:
            logger.info("[WPPCONNECT-WORKER] 🤖 Processando com Agents SDK")

            try:
                from backend.agents_sdk.integrations.integration import (
                    process_with_agents_sdk_if_enabled_sync
                )

                # 4.1. Processar com Agents SDK
                agents_result = process_with_agents_sdk_if_enabled_sync(
                    db=db,
                    company_id=company_id,
                    contact_phone=phone,
                    user_input=message_text,
                    msg_category="",  # Agents SDK detecta automaticamente
                    funnel_stage="",
                    funnel_status=""
                )

                if is_ai_credit_block_result(agents_result):
                    logger.info("[WPPCONNECT-WORKER] Agents SDK bloqueado por saldo de créditos")
                    return {
                        "status": "ignored",
                        "reason": "insufficient_ai_credits",
                        "company_id": company_id,
                        "session_name": session_name,
                        "blocked_by_ai_credits": True,
                    }

                if agents_result and isinstance(agents_result, dict):
                    response_text = agents_result.get("response", "")
                    audio_data = agents_result.get("audio")
                    should_send_audio = agents_result.get("should_send_audio", False)

                    logger.info(
                        f"[WPPCONNECT-WORKER] Agents SDK respondeu: "
                        f"response_length={len(response_text)}, "
                        f"should_send_audio={should_send_audio}"
                    )

                    # 4.2. Enviar resposta via WPPConnect
                    try:
                        from backend.integrations.whatsapp_provider import send_text, send_audio

                        if should_send_audio and audio_data:
                            logger.info("[WPPCONNECT-WORKER] Enviando resposta em áudio")
                            send_audio(
                                company_id=company_id,
                                phone=phone,
                                audio_bytes=audio_data,
                                db=db
                            )
                        else:
                            logger.info("[WPPCONNECT-WORKER] Enviando resposta em texto")
                            send_text(
                                company_id=company_id,
                                phone=phone,
                                message=response_text,
                                db=db,
                                human_mode=False
                            )

                        # 4.3. Salvar AI response no messages table (paridade com Z-API)
                        try:
                            db.execute(text("""
                                INSERT INTO messages
                                    (client_id, company_id, contact_phone, message_type, content,
                                    sender_phone, sender_name, from_me)
                                VALUES (:client_id, :company_id, :contact_phone, 'text', :content,
                                        'me', 'Agents SDK', true)
                            """), {
                                "client_id": client_id_db,
                                "company_id": company_id,
                                "contact_phone": phone,
                                "content": response_text
                            })
                            db.commit()
                            logger.info("[WPPCONNECT-WORKER] ✅ AI response salva no messages table")
                        except Exception as save_err:
                            logger.warning(f"[WPPCONNECT-WORKER] Erro ao salvar AI response no BD: {save_err}")
                            try:
                                db.rollback()
                            except:
                                pass

                        # 4.4. Salvar na memória .txt (paridade com Z-API)
                        try:
                            append_message_to_chat_file(company_id, phone, True, response_text)
                            logger.info("[WPPCONNECT-WORKER] ✅ AI response salva no .txt file")
                        except Exception as mem_err:
                            logger.warning(f"[WPPCONNECT-WORKER] Erro ao salvar memória: {mem_err}")

                        # 4.5. WebSocket broadcast da AI response (paridade com Z-API)
                        try:
                            import uuid
                            from datetime import datetime
                            from backend.integrations.broadcast_redis import publish_to_redis

                            ws_payload = {
                                "type": "text",
                                "content": response_text,
                                "phone": phone,
                                "senderName": "Agents SDK",
                                "photo": "",
                                "fromMe": True,
                                "fromApi": True,  # Mensagem da API (Agents SDK) - frontend pode otimizar duplicação
                                "messageId": f"agents_{uuid.uuid4()}",
                                "momment": datetime.utcnow().isoformat(),
                                "company_id": company_id
                            }
                            publish_to_redis(company_id, ws_payload)
                            logger.info("[WPPCONNECT-WORKER] ✅ AI response broadcast via WebSocket")
                        except Exception as ws_err:
                            logger.warning(f"[WPPCONNECT-WORKER] Erro no WebSocket broadcast: {ws_err}")

                        logger.info("[WPPCONNECT-WORKER] ✅ Processamento Agents SDK concluído com sucesso")

                        return {
                            "status": "success",
                            "company_id": company_id,
                            "session_name": session_name,
                            "processor": "agents_sdk",
                            "response_length": len(response_text),
                            "sent_audio": should_send_audio
                        }

                    except Exception as send_err:
                        logger.error(f"[WPPCONNECT-WORKER] Erro ao enviar resposta Agents SDK: {send_err}")
                        raise

                else:
                    logger.warning("[WPPCONNECT-WORKER] Agents SDK retornou None, usando fallback")

            except Exception as agents_err:
                logger.error(f"[WPPCONNECT-WORKER] Erro no Agents SDK: {agents_err}", exc_info=True)
                logger.info("[WPPCONNECT-WORKER] Usando fallback LangChain")

        # ============================================
        # 5. FALLBACK: PROCESSAR COM LANGCHAIN LEGADO
        # ============================================

        logger.info("[WPPCONNECT-WORKER] 🔄 Processando com LangChain legado (burst_processor)")

        try:
            # 5.1. Importar lógica legada de processamento Z-API
            from backend.worker.process_message import process_incoming_zapi_message

            # 5.2. Processar usando a mesma lógica do Z-API
            # A função process_incoming_zapi_message espera (data, instance_id, audit_id)
            result = process_incoming_zapi_message(
                data=zapi_format_data,
                instance_id=session_name,
                audit_id=audit_id
            )

            logger.info("[WPPCONNECT-WORKER] ✅ Processamento LangChain concluído com sucesso")

            return {
                "status": "success",
                "company_id": company_id,
                "session_name": session_name,
                "processor": "langchain",
                "result": result
            }

        except Exception as langchain_err:
            logger.error(
                f"[WPPCONNECT-WORKER] Erro no LangChain legado: {langchain_err}",
                exc_info=True
            )
            raise

    except Exception as e:
        logger.error(f"[WPPCONNECT-WORKER] Erro crítico ao processar mensagem: {e}", exc_info=True)

        # Atualizar audit se disponível
        if audit_id:
            try:
                db.execute(
                    text("""
                        UPDATE webhook_audit
                        SET processing_status = 'processing_failed',
                            error_message = :error,
                            updated_at = NOW()
                        WHERE id = :audit_id
                    """),
                    {"audit_id": audit_id, "error": str(e)}
                )
                db.commit()
            except Exception as audit_err:
                logger.error(f"[WPPCONNECT-WORKER] Erro ao atualizar audit: {audit_err}")

        # Retry com backoff exponencial
        raise self.retry(exc=e, countdown=2 ** self.request.retries)

    finally:
        db.close()
