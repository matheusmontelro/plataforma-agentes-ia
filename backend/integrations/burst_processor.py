# backend/integrations/burst_processor.py

import logging
import uuid
from datetime import datetime
from typing import List, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
# Removido import asyncio pois não é mais necessário aqui

from backend.prompt.llm.llm_manager_lead import handle_user_input as lead_llm_handler
from backend.prompt.llm.llm_manager_agendado import handle_user_input as scheduled_llm_handler

# Configure logger first
logger = logging.getLogger(__name__)

# Nova importação - Agents SDK para substituição gradual
try:
    from backend.agents_sdk.integrations.integration import process_with_agents_sdk_if_enabled_sync
    AGENTS_SDK_AVAILABLE = True
    logger.info("✓ Agents SDK carregado com sucesso!")
except ImportError as e:
    logger.warning(f"Agents SDK não disponível ({e}) - usando sistema atual")
    AGENTS_SDK_AVAILABLE = False

# Debug imports
logger.info("=== BURST PROCESSOR LOADING ===")

from backend.integrations.whatsapp_provider import (
    WhatsAppConfig,
    send_audio as send_whatsapp_audio,
    send_text as send_whatsapp_text,
)
from backend.services.ai_credit_guard import (
    ai_credit_block_result_from_balance,
    is_ai_credit_block_result,
)
from backend.ws_manager import manager
from backend.integrations.broadcast_redis import publish_to_redis
from backend.prompt.memory.memory_manager import append_message_to_chat_file

# REMOVIDA a constante NANO_TEST_PHONE_NUMBER e a flag NANO_TEST_MODULE_LOADED

def has_future_scheduled_appointment(db: Session, contact_phone: str, company_id: int) -> bool:
    """
    Verifica se o cliente tem um agendamento futuro com status 'SCHEDULED'.
    Consulta diretamente a tabela agendamentos.
    """
    try:
        query = text("""
            SELECT EXISTS (
                SELECT 1
                FROM agendamentos
                WHERE phone = :phone
                  AND company_id = :company_id
                  AND consulta_data > CURRENT_TIMESTAMP -- Garante que é um agendamento futuro
            )
        """)
        result = db.execute(query, {"phone": contact_phone, "company_id": company_id}).scalar_one_or_none()
        return result is True
    except Exception as e:
        logger.error(f"[has_future_scheduled_appointment] Erro ao verificar agendamento futuro para {contact_phone}: {e}")
        return False # Assume que não tem em caso de erro

def process_burst_messages(
    contact_phone: str,
    messages: List[str],
    db: Session,
    company_id: int,
    client_id_db: int,
    msg_category: Optional[str] = None,
    funnel_stage: Optional[str] = None,
    funnel_status: Optional[str] = None
):
    """
    Função chamada quando o 'debounce' expira. Ela irá:
    1) Concatenar as mensagens do usuário.
    2) Chamar o Agents SDK configurado ou o processador LLM legado genérico.
    3) Retornar a resposta e enviar ao WhatsApp.
    4) Salvar no BD e .txt, e notificar WS.
    """

    user_full_text = "\n".join(messages).strip()
    logger.info(f"[DebounceCallback] Consolidando {len(messages)} msgs para {contact_phone}")
    logger.info(f"[DebounceCallback] Texto final:\n{user_full_text}")

    if not user_full_text:
        logger.info("[DebounceCallback] Sem texto para processar. Retornando.")
        return

    credit_block = ai_credit_block_result_from_balance(
        db=db,
        company_id=company_id,
        source="burst_processor",
    )
    if credit_block:
        logger.info(
            "[DebounceCallback] IA bloqueada por saldo de créditos para company %s",
            company_id,
        )
        return

    # --- PRIORITY: Try Agents SDK first (only for enabled companies) ---
    final_response = None
    agents_response = None
    llm_version_tag = None

    if AGENTS_SDK_AVAILABLE:
        try:
            agents_response = process_with_agents_sdk_if_enabled_sync(
                db=db,
                company_id=company_id,
                contact_phone=contact_phone,
                user_input=user_full_text,
                msg_category=msg_category or "",
                funnel_stage=funnel_stage or "",
                funnel_status=funnel_status or ""
            )

            if agents_response is not None:
                if is_ai_credit_block_result(agents_response):
                    logger.info(
                        "[DebounceCallback] Agents SDK bloqueado por créditos para company %s",
                        company_id,
                    )
                    return

                # Agents SDK returns dict with response and audio
                if isinstance(agents_response, dict):
                    final_response = agents_response.get("response", agents_response)
                    # Process audio if present
                    if agents_response.get("should_send_audio") and agents_response.get("audio"):
                        # Will be processed later in audio sending section
                        pass
                else:
                    final_response = agents_response

                llm_version_tag = f"Agents SDK v2 (Company {company_id})"
                logger.info(f"[DebounceCallback] Processado com Agents SDK para company {company_id}")
        except Exception as e:
            logger.error(f"[DebounceCallback] Erro no Agents SDK para company {company_id}: {e}")
            logger.info(f"[DebounceCallback] Fallback para sistema legado")

    # Generic legacy fallback when the workspace has no Agents SDK config or
    # the SDK could not complete the request.
    if not final_response:
        # Verifica se o lead tem agendamento futuro (sistema tradicional)
        try:
            has_appointment = has_future_scheduled_appointment(db, contact_phone, company_id)
        except Exception as e:
            logger.error(f"[DebounceCallback] Erro ao verificar agendamento futuro para {contact_phone}: {e}")
            has_appointment = False  # Assume sem agendamento em caso de erro

        if has_appointment:
            logger.info(f"[DebounceCallback] Lead {contact_phone} com agendamento futuro encontrado. Roteando para LLM AGENDADO.")
            handler_to_call = scheduled_llm_handler
            llm_version_tag = "LLM Agendado"
        else:
            logger.info(f"[DebounceCallback] Company ID {company_id} sem agendamento. Roteando para LLM LEAD.")
            handler_to_call = lead_llm_handler
            llm_version_tag = "LLM Lead"

        # Executa handler tradicional
        try:
            final_response = handler_to_call(
                db=db,
                company_id=company_id,
                contact_phone=contact_phone,
                user_input=user_full_text,
                msg_category=msg_category or "",
                funnel_stage=funnel_stage or "",
                funnel_status=funnel_status or ""
            )

            if not final_response or not final_response.strip():
                logger.warning(f"[DebounceCallback] {llm_version_tag} retornou resposta vazia para {contact_phone}")
                final_response = "Olá! Como posso ajudar você hoje?"
            else:
                logger.info(f"[DebounceCallback] Resposta do {llm_version_tag}: {len(final_response)} chars")

        except Exception as e:
            logger.error(f"Erro ao processar com {llm_version_tag} para {contact_phone} (Company: {company_id}): {e}", exc_info=True)
            final_response = "Desculpe, ocorreu um erro interno ao processar sua solicitação. Como posso ajudar?"
            llm_version_tag = f"{llm_version_tag} (Error)"

    # Validação final
    if not final_response:
        # Caso de segurança (não deve acontecer com a lógica atual)
        logger.error(f"[DebounceCallback] Nenhum handler LLM selecionado para company_id {company_id}. Usando fallback.")
        final_response = "Desculpe, não consegui processar sua mensagem no momento."
        llm_version_tag = "Error Fallback"


    # --- Lógica Pós-LLM (Envio, Persistência, Notificação - SEM ALTERAÇÕES AQUI) ---

    # Verifica se houve uma resposta válida do LLM
    if not final_response:
        logger.error(f"[DebounceCallback] Não houve resposta do LLM para {contact_phone}. Abortando pós-processamento.")
        return

    # (O código para buscar api_key e company_data permanece o mesmo)
    try:
        try:
            db.rollback()
        except:
            pass
        row_client_data = db.execute(text("""
            SELECT c.api_key
                FROM clients c
                JOIN client_companies cc ON cc.client_id = c.id
                WHERE cc.company_id = :company_id
                LIMIT 1
        """), {"company_id": company_id}).fetchone()
        client_api_key = row_client_data.api_key if (row_client_data and row_client_data.api_key) else None
    except Exception as e:
        logger.warning(f"Erro ao buscar client_api_key: {e}")
        client_api_key = None

    whatsapp_config = WhatsAppConfig.from_company(company_id, db)

    if whatsapp_config:
        # Verifica se deve enviar APENAS áudio (Agents SDK feature)
        should_send_only_audio = (
            AGENTS_SDK_AVAILABLE and agents_response and
            isinstance(agents_response, dict) and
            agents_response.get("should_send_audio") and
            agents_response.get("audio")
        )

        # Debug logs for audio mode
        if agents_response and isinstance(agents_response, dict):
            logger.info(f"[AUDIO_DEBUG] agents_response keys: {list(agents_response.keys())}")
            logger.info(f"[AUDIO_DEBUG] should_send_audio: {agents_response.get('should_send_audio')}")
            logger.info(f"[AUDIO_DEBUG] has audio: {bool(agents_response.get('audio'))}")
            logger.info(f"[AUDIO_DEBUG] should_send_only_audio: {should_send_only_audio}")

        if should_send_only_audio:
            # APENAS áudio para Agents SDK quando solicitado
            try:
                logger.info(f"[DebounceCallback] Enviando APENAS áudio para {contact_phone} - trigger: {agents_response.get('metadata', {}).get('audio_trigger', 'unknown')}")

                response = send_whatsapp_audio(
                    company_id=company_id,
                    phone=contact_phone,
                    audio_bytes=agents_response["audio"],
                    db=db,
                )

                logger.info(f"[DebounceCallback] Áudio enviado com sucesso para {contact_phone}")

                # Salvar áudio na tabela messages (mesmo padrão do webhook.py)
                try:
                    import base64
                    audio_base64 = base64.b64encode(agents_response["audio"]).decode('utf-8')
                    audio_content = f"data:audio/mpeg;base64,{audio_base64}"

                    # Extrair zapi_message_id para evitar duplicação
                    zapi_msg_id = response.get('zaapId') or response.get('messageId') or response.get('id') if response else None

                    db.execute(text("""
                        INSERT INTO messages
                            (client_id, company_id, contact_phone, message_type, content,
                            sender_phone, sender_name, from_me, zapi_message_id)
                        VALUES (:client_id, :company_id, :contact_phone, 'audio', :content,
                                'me', 'Você', true, :zapi_message_id)
                    """), {
                        "client_id": client_id_db,
                        "company_id": company_id,
                        "contact_phone": contact_phone,
                        "content": audio_content,
                        "zapi_message_id": zapi_msg_id
                    })
                    db.commit()
                    logger.info(f"[DebounceCallback] Áudio salvo no banco de dados para {contact_phone}")
                except Exception as save_error:
                    logger.warning(f"Erro ao salvar áudio no banco de dados: {save_error}")
                    try:
                        db.rollback()
                    except:
                        pass

            except Exception as e:
                logger.error(f"[DebounceCallback] Erro ao enviar áudio para {contact_phone}: {e}")
                logger.info(f"[DebounceCallback] Fallback: enviando texto devido a falha no áudio")
                # Fallback para texto se áudio falhar
                send_whatsapp_text(
                    company_id=company_id,
                    phone=contact_phone,
                    message=final_response,
                    db=db,
                    human_mode=False
                )
        else:
            # Envio padrão - mensagem única sem split
            # REMOVED: Lógica de processamento de ||| (conflito com debounce)
            send_whatsapp_text(
                company_id=company_id,
                phone=contact_phone,
                message=final_response,
                db=db,
                human_mode=False  # A resposta é sempre do LLM aqui
            )

        # Salva no BD
        try:
            db.execute(text("""
                INSERT INTO messages
                    (client_id, company_id, contact_phone, message_type, content,
                    sender_phone, sender_name, from_me)
                VALUES (:client_id, :company_id, :contact_phone, 'text', :content,
                        'LLM', :llm_version, true)
            """), {
                "client_id": client_id_db,
                "company_id": company_id,
                "contact_phone": contact_phone,
                "content": final_response,
                "llm_version": llm_version_tag # Usa a tag padrão "LLM v1"
            })
            db.commit()
        except Exception as e:
            logger.warning(f"Erro ao salvar mensagem no banco de dados: {e}")
            try:
                db.rollback()
            except:
                pass

        # Adiciona no .txt (Necessário para o llm_manager v1)
        try:
            append_message_to_chat_file(
                company_id,
                contact_phone,
                from_me=True,  # A mensagem é do LLM (nosso sistema)
                content=final_response
            )
        except Exception as e:
            logger.error(f"Erro ao chamar append_message_to_chat_file para {contact_phone}: {e}", exc_info=True)


        # Notifica WS
        ws_payload = {
            "type": "text",
            "content": final_response,
            "phone": contact_phone,
            "senderName": llm_version_tag, # Usa a tag padrão "LLM v1"
            "photo": "", # Adicionar path da foto se disponível/necessário
            "fromMe": True,
            "messageId": f"llm_{uuid.uuid4()}", # Gera um ID único para a mensagem do LLM
            "momment": datetime.utcnow().isoformat(),
            "company_id": company_id
        }
        publish_to_redis(company_id, ws_payload)
        logger.info("[DebounceCallback] Mensagem publicada no Redis para WS broadcast.")
    else:
        logger.warning(f"[DebounceCallback] Empresa {company_id} sem WAHA ativo. Sem envio da resposta LLM para {contact_phone}.")
