import logging
import uuid
import json
from datetime import datetime, timedelta
import datetime as dt
from typing import Dict, Any, Union
import os
import requests
from sqlalchemy import text
from sqlalchemy.orm import Session
import pytz
from backend.db import SessionLocal
from backend.ws_manager import manager
from backend.prompt.memory.memory_manager import append_message_to_chat_file
from backend.runtime_settings import AD_CAMPAIGN_DIR
from backend.prompt.media.audio_processing import transcribe_audio, transcribe_video
from backend.prompt.media.image_analysis import analyze_image_with_google_vision
from backend.prompt.llm.llm_manager import create_llm_chain_with_memory, extract_json_from_llm_response
from backend.prompt.db_integration.agendamento_logic import processar_json_do_llm
from backend.worker.celery_app import app
from backend.integrations.burst_processor import process_burst_messages
from backend.integrations.broadcast_redis import publish_to_redis
from backend.models import NPSResponse
from backend.services.ai_provider_service import (
    AIProviderCredentialError,
    get_company_openai_api_key,
)

logger = logging.getLogger(__name__)

BASE_AD_CAMPAIGN_DIR = str(AD_CAMPAIGN_DIR)


def _company_openai_key_for_media(db: Session, company_id: int) -> str:
    try:
        return get_company_openai_api_key(db, int(company_id))
    except AIProviderCredentialError:
        logger.info(
            "[Celery] Midia sem transcricao: chave OpenAI da empresa indisponivel company_id=%s",
            company_id,
        )
        return ""

import pytz
from datetime import datetime

def is_ia_enabled_now(timezone_str: str, time_windows: dict) -> bool:
    """
    Verifica se o horário local atual (de acordo com `timezone_str`)
    está dentro de algum período habilitado em `time_windows`.
    Exemplo de time_windows (em inglês):
        {
          "monday": {
            "morning":   { "enabled": true,  "start": "08:00",  "end": "12:00" },
            "afternoon": { "enabled": true,  "start": "13:00",  "end": "18:00" },
            "night":     { "enabled": false, "start": "18:00",  "end": "23:59" },
            "dawn":      { "enabled": false, "start": "00:00",  "end": "06:00" }
          },
          "tuesday": { ... },
          ...
        }
    """

    # 1) Hora UTC agora
    utc_now = dt.datetime.utcnow()

    # 2) Cria objeto timezone (ex.: "America/Sao_Paulo")
    local_tz = pytz.timezone(timezone_str)

    # 3) Converte para horário local
    local_now = utc_now.replace(tzinfo=pytz.utc).astimezone(local_tz)

    # Log para debug
    logger.info(
        f"[is_ia_enabled_now] timezone='{timezone_str}', "
        f"utc_now={utc_now}, local_now={local_now}"
    )

    # 4) Mapeia weekday() do Python => 0=monday ... 6=sunday
    weekday_map = {
        0: "monday",
        1: "tuesday",
        2: "wednesday",
        3: "thursday",
        4: "friday",
        5: "saturday",
        6: "sunday"
    }

    weekday_num = local_now.weekday()  # Monday=0, Sunday=6
    day_key = weekday_map.get(weekday_num, None)

    # Se o dia não existe ou não está no JSON, IA desabilitada
    if not day_key or day_key not in time_windows:
        return False

    configs_dia = time_windows[day_key]  # ex: { "morning": {...}, "afternoon": {...}, ... }

    # 5) Percorre cada período (morning, afternoon, night, dawn, etc.)
    for period_name, period_data in configs_dia.items():
        if period_data.get("enabled"):
            start_str = period_data.get("start")
            end_str   = period_data.get("end")
            if not start_str or not end_str:
                continue

            # Ex.: "08:00" -> hora=8, minuto=0
            sh, sm = map(int, start_str.split(":"))
            eh, em = map(int, end_str.split(":"))

            # Monta datetime local com a data de hoje
            date_hoje = local_now.date()
            start_dt = local_tz.localize(datetime(date_hoje.year, date_hoje.month, date_hoje.day, sh, sm))
            end_dt   = local_tz.localize(datetime(date_hoje.year, date_hoje.month, date_hoje.day, eh, em))

            # 5.1) Verificação normal (start < end, não cruza meia-noite)
            if start_dt < end_dt:
                if start_dt <= local_now < end_dt:
                    return True
            else:
                # 5.2) Caso cruza a meia-noite (ex.: start=22:00, end=06:00)
                # Nesse caso, se local_now >= start_dt (22:00+)  ou  local_now < end_dt (até 06:00)
                #  => IA habilitada
                if local_now >= start_dt or local_now < end_dt:
                    return True

    # Se nenhum período habilitado abrange local_now
    return False

def store_ad_campaign_media_once(db: Session, company_id: int, source_id: str, thumbnail_url: str):
    """
    Se (company_id, source_id) já existir em ad_campaign_media, sai.
    Caso contrário, tenta baixar 'thumbnail_url' e salva localmente:
      var/ad-campaign/company_{company_id}/source_{source_id}.jpg
    Depois insere um registro na tabela ad_campaign_media com (company_id, source_id, file_name, file_path).
    """
    if not source_id or not thumbnail_url:
        logger.info(f"[store_ad_campaign_media_once] Dados insuficientes: source_id='{source_id}', thumbnail_url='{thumbnail_url}' (saindo).")
        return  # Sem source_id ou thumbnail_url, nada a fazer

    logger.info(f"[store_ad_campaign_media_once] Iniciando para company_id={company_id}, source_id={source_id}.")

    # Verifica se já existe (company_id, source_id) em ad_campaign_media
    row_exists = db.execute(text("""
        SELECT id
          FROM ad_campaign_media
         WHERE company_id = :cid
           AND source_id = :sid
         LIMIT 1
    """), {"cid": company_id, "sid": source_id}).fetchone()

    if row_exists:
        logger.info(f"[store_ad_campaign_media_once] Já existe registro em ad_campaign_media para (company_id={company_id}, source_id={source_id}). Nenhuma ação realizada.")
        return

    company_folder = os.path.join(BASE_AD_CAMPAIGN_DIR, f"company_{company_id}")
    os.makedirs(company_folder, exist_ok=True)

    file_name = f"source_{source_id}.jpg"  # Se quiser algo mais único, inclua um UUID
    file_path = os.path.join(company_folder, file_name)

    try:
        logger.info(f"[store_ad_campaign_media_once] Baixando thumbnail_url={thumbnail_url}.")
        resp = requests.get(thumbnail_url, timeout=10)
        if resp.status_code == 200:
            logger.info(f"[store_ad_campaign_media_once] Download OK. Salvando em {file_path}")
            with open(file_path, "wb") as f:
                f.write(resp.content)

            # Insere na tabela ad_campaign_media
            db.execute(text("""
                INSERT INTO ad_campaign_media (company_id, source_id, file_name, file_path)
                VALUES (:company_id, :source_id, :file_name, :file_path)
                ON CONFLICT DO NOTHING
            """), {
                "company_id": company_id,
                "source_id": source_id,
                "file_name": file_name,
                "file_path": file_path
            })
            db.commit()
            logger.info(f"[store_ad_campaign_media_once] Inserido ad_campaign_media com (company_id={company_id}, source_id={source_id}).")
        else:
            logger.warning(f"[store_ad_campaign_media_once] Falha ao baixar thumbnail (HTTP {resp.status_code}) source_id={source_id}.")
    except requests.exceptions.RequestException as e:
        logger.warning(f"[store_ad_campaign_media_once] Erro ao baixar thumbnail source_id={source_id}: {e}")


@app.task
def process_incoming_zapi_message(data: Dict[str, Any], instance_id: str, audit_id: int = None):
    """
    Tarefa Celery que reproduz a lógica completa do zapi_message_webhook.
    Recebe o payload original do Z-API (data) + instance_id + audit_id (opcional).

    Args:
        data: Payload completo do Z-API
        instance_id: ID da instância Z-API
        audit_id: ID do registro na tabela webhook_audit (opcional, para retrocompatibilidade)

    Faz TUDO o que o webhook fazia:
      1) Verifica se é "ReceivedCallback", se é 1x1, etc.
      2) Identifica company_id e client_id
      3) Salva mensagem em 'messages'
      4) Atualiza/insere 'contacts', 'leads'
      5) Verifica e agenda follow-up (enviar_passo_followup)
      6) Envia broadcast WebSocket (via Redis)
      7) Transcreve áudio/vídeo, analisa imagem
      8) Verifica human_mode
      9) Classifica msg com scikit-learn
      10) Detecta estágio do funil (vendas > comparecimentos > agendamentos > leads)
      11) Faz o 'debounce' e chama LLM se necessário
      12) Salva tudo no BD e finaliza
      13) Atualiza status na webhook_audit se audit_id fornecido
    """

    db: Session = SessionLocal()
    try:
        logger.info(f"[Celery] process_incoming_zapi_message iniciado. instance_id={instance_id}, audit_id={audit_id}")
        logger.info(f"[Celery] Payload (raw): {data}")

        # Atualizar status para 'processing' se audit_id fornecido
        if audit_id:
            from backend.webhook_audit import update_audit_status
            update_audit_status(db, audit_id, "processing")

        # Verificar se veio da fila
        if data.get("isFromQueue"):
            logger.warning(f"[QUEUE_RECOVERY] Processando mensagem recuperada da fila Z-API")
            logger.warning(f"[QUEUE_RECOVERY] Phone: {data.get('phone')}, MessageId: {data.get('messageId')}")

        # 1) Verificar tipo de evento
        event_type = data.get("type", "")
        if event_type != "ReceivedCallback":
            logger.info("[Celery] Não é 'ReceivedCallback'. Ignorando.")
            return

        # 2) Filtrar mensagens que não são 1x1 (ex.: grupo, edit, newsletter, broadcast)
        # CORRIGIDO: Defaults alterados para False para evitar rejeição de leads válidos com waitingMessage: true
        is_group = data.get("isGroup", False)
        is_edit = data.get("isEdit", False)
        is_newsletter = data.get("isNewsletter", False)
        broadcast = data.get("broadcast", False)

        logger.info(f"[DEBUG] Filtros 1x1: isGroup={is_group}, isEdit={is_edit}, isNewsletter={is_newsletter}, broadcast={broadcast}")
        if is_group or is_edit or is_newsletter or broadcast:
            logger.info(f"[Celery] Mensagem filtrada (não 1x1). Ignorando. Motivo: isGroup={is_group}, isEdit={is_edit}, isNewsletter={is_newsletter}, broadcast={broadcast}")
            if audit_id:
                from backend.webhook_audit import update_audit_status
                update_audit_status(db, audit_id, "ignored", error="Mensagem de grupo/newsletter/broadcast")
            return

        # 2.1) Filtrar tipos de mensagem - processar apenas tipos conhecidos
        ALLOWED_MESSAGE_TYPES = ['text', 'image', 'audio', 'video', 'pollVote', 'contact']

        # Detectar tipo de mensagem
        message_type = 'unknown'
        if 'pollVote' in data:
            message_type = 'pollVote'
        elif 'text' in data:
            message_type = 'text'
        elif 'image' in data:
            message_type = 'image'
        elif 'audio' in data:
            message_type = 'audio'
        elif 'video' in data:
            message_type = 'video'
        elif 'contact' in data:
            message_type = 'contact'

        # Se não for um tipo permitido, verificar se é caso especial de anúncio
        if message_type not in ALLOWED_MESSAGE_TYPES:
            # CORREÇÃO: Processar mensagens unknown com waitingMessage=true (bug Z-API em anúncios)
            waiting_message = data.get('waitingMessage', False)
            if message_type == 'unknown' and waiting_message:
                logger.info(f"[Celery] Mensagem unknown com waitingMessage=true detectada. Processando como lead de anúncio (bug Z-API).")
                message_type = 'text'  # Forçar processamento como texto
            else:
                logger.info(f"[Celery] Tipo de mensagem '{message_type}' não é processado. Ignorando.")
                if audit_id:
                    from backend.webhook_audit import update_audit_status
                    update_audit_status(db, audit_id, "ignored", error=f"Tipo de mensagem '{message_type}' não suportado")
                return

        # 3) Extrair dados básicos
        phone = data.get("phone", "desconhecido")
        chat_name = data.get("chatName", "desconhecido")
        sender_name = data.get("senderName", chat_name)
        from_me = data.get("fromMe", False)
        momment = data.get("momment", "")
        message_id = data.get("messageId", f"ws_{momment or str(uuid.uuid4())}")

        # 4) Identificar a company
        company_row = db.execute(
            text("SELECT id FROM companies WHERE zapi_instance_id = :iid"),
            {"iid": instance_id}
        ).fetchone()

        if not company_row:
            logger.warning(f"[Celery] Instância {instance_id} não encontrada em companies.")
            return

        company_id = company_row.id

        # 5) Obter client_id associado
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
            logger.warning("[Celery] Nenhum usuário (client) associado a esta empresa.")
            return

        client_id_db = row_owner.client_id

        # 6) Salvar a mensagem bruta em 'messages'
        msg_type = "unknown"
        content = ""

        if "text" in data:
            msg_type = "text"
            content = data["text"].get("message", "")
            logger.info(f"[Celery] Mensagem de texto: '{content}'")
        elif message_type == 'text' and data.get('waitingMessage', False):
            # CORREÇÃO: Mensagem unknown foi forçada para text, definir conteúdo padrão
            msg_type = "text"
            content = "Usuário demonstrou interesse através do anúncio e iniciou a conversa"
            logger.info(f"[Celery] Mensagem unknown+waitingMessage forçada como texto: '{content}'")
        elif "image" in data:
            msg_type = "image"
            content = data["image"].get("imageUrl", "")
            logger.info(f"[Celery] Imagem: {content}")
        elif "audio" in data:
            msg_type = "audio"
            content = data["audio"].get("audioUrl", "")

            # CORREÇÃO: Adicionar prefixo data:audio se não existir
            # Áudios do Z-API podem vir como URL ou base64 sem prefixo
            if content and not content.startswith("data:") and not content.startswith("http"):
                # Se for base64 puro, adicionar prefixo
                content = f"data:audio/mpeg;base64,{content}"
                logger.info(f"[Celery] Áudio corrigido com prefixo: {content[:100]}...")
            else:
                logger.info(f"[Celery] Áudio: {content}")
        elif "video" in data:
            msg_type = "video"
            content = data["video"].get("videoUrl", "")
            logger.info(f"[Celery] Vídeo: {content}")
        elif "contact" in data:
            msg_type = "contact"
            contact_info = data["contact"]
            display_name = contact_info.get("displayName", "Sem nome")
            phones = contact_info.get("phones", [])

            # Formatar conteúdo do contato para salvar e processar
            content = f"📇 Contato compartilhado: {display_name}"
            if phones:
                # Pegar o primeiro telefone da lista
                contact_phone = phones[0] if phones else ""
                content = f"{display_name} - {contact_phone}"
                logger.info(f"[Celery] Contato recebido: {display_name} ({contact_phone})")
            else:
                logger.info(f"[Celery] Contato recebido: {display_name} (sem telefone)")

        sender_phone_db = "me" if from_me else phone
        sender_name_db = sender_name if sender_name else None

        # NOVO: Verificar se é mensagem enviada via API para evitar duplicação
        from_api = data.get("fromApi", True)  # Assume True por padrão (comportamento anterior)

        # Extrair ID da mensagem do Z-API
        zapi_message_id = data.get("messageId") or data.get("message", {}).get("messageId")

        # CORREÇÃO: Verificar duplicação de áudio enviado recentemente (echo Z-API)
        skip_save = False

        if from_me and msg_type == "audio":
            # Verificar se já existe áudio enviado nos últimos 10 segundos
            recent_audio = db.execute(text("""
                SELECT id FROM messages
                WHERE contact_phone = :phone
                AND company_id = :company_id
                AND message_type = 'audio'
                AND from_me = true
                AND timestamp > NOW() - INTERVAL '10 seconds'
                LIMIT 1
            """), {"phone": phone, "company_id": company_id}).fetchone()

            if recent_audio:
                logger.info(f"[Celery] Áudio echo detectado para {phone} - ignorando duplicação (audio recente ID: {recent_audio.id})")
                skip_save = True

        # Lógica para salvamento no BD
        if from_me and from_api:
            logger.info("[Celery] Mensagem fromMe=True e fromApi=True detectada. Pulando salvamento no BD (já foi salvo no endpoint de envio).")
        elif skip_save:
            logger.info("[Celery] Salvamento pulado devido a detecção de echo de áudio")
        else:
            # Verificar se a mensagem já existe antes de inserir
            if zapi_message_id:
                existing = db.execute(text("""
                    SELECT id FROM messages
                    WHERE zapi_message_id = :zapi_message_id
                    LIMIT 1
                """), {"zapi_message_id": zapi_message_id}).fetchone()

                if existing:
                    logger.warning(f"[Celery] Mensagem com ID {zapi_message_id} já existe. Pulando inserção duplicada.")
                else:
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
                        "sender_phone": sender_phone_db,
                        "sender_name": sender_name_db,
                        "from_me": from_me,
                        "zapi_message_id": zapi_message_id
                    })
                    # CORREÇÃO: Forçar atualização do last_message_at (backup do trigger)
                    db.execute(text("""
                        UPDATE contacts
                        SET last_message_at = NOW()
                        WHERE client_id = :client_id AND phone = :contact_phone
                    """), {
                        "client_id": client_id_db,
                        "contact_phone": phone
                    })

                    db.commit()
                    logger.info(f"[Celery] Mensagem salva em 'messages' com ID Z-API: {zapi_message_id}")
                    logger.info(f"[Celery] last_message_at atualizado para contato {phone}")
            else:
                # Se não tiver zapi_message_id, inserir sem verificação (retrocompatibilidade)
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
                    "sender_phone": sender_phone_db,
                    "sender_name": sender_name_db,
                    "from_me": from_me,
                    "zapi_message_id": zapi_message_id
                })
                # CORREÇÃO: Forçar atualização do last_message_at (backup do trigger)
                db.execute(text("""
                    UPDATE contacts
                    SET last_message_at = NOW()
                    WHERE client_id = :client_id AND phone = :contact_phone
                """), {
                    "client_id": client_id_db,
                    "contact_phone": phone
                })

                db.commit()
                logger.info("[Celery] Mensagem salva em 'messages' sem ID Z-API")
                logger.info(f"[Celery] last_message_at atualizado para contato {phone}")

        # Se não for 'from_me', salva no .txt para histórico
        if not from_me:
            append_message_to_chat_file(company_id, phone, from_me=False, content=content)
        else:
            # NOVO: Verificar se é mensagem manual (celular) para salvar como operador
            if not from_api:  # fromApi=False significa manual
                from backend.prompt.memory.memory_manager import append_message_to_chat_file_as_operator
                append_message_to_chat_file_as_operator(company_id, phone, content=content)
                logger.info(f"[Celery] Mensagem do operador salva para {phone}")

        # 7) Atualizar ou inserir 'contacts'
        # IMPORTANTE: Para mensagens com fromMe=true, o nome correto do contato está em chatName
        # Para mensagens com fromMe=false, o nome do contato está em senderName
        # MAS: Se fromMe=true e o contato já existe com nome, preservamos o nome existente
        contact_name = chat_name if from_me else sender_name
        logger.info(f"[Celery] Nome do contato inicial: '{contact_name}' (fromMe={from_me}, chatName='{chat_name}', senderName='{sender_name}')")
        contact_exists = db.execute(
            text("""
                SELECT id, company_id, name
                FROM contacts
                WHERE client_id = :client_id
                  AND phone = :phone
            """),
            {"client_id": client_id_db, "phone": phone}
        ).fetchone()

        if contact_exists:
            logger.info("[Celery] Contato já existe, atualizando informações.")

            # Se fromMe=true e o contato já tem um nome, preservamos o nome existente
            if from_me and contact_exists.name and contact_exists.name.strip():
                logger.info(f"[NAME_TRACKING] ANTES: contact_exists.name='{contact_exists.name}', contact_name='{contact_name}', fromMe={from_me}")
                logger.info(f"[Celery] Preservando nome existente do contato: '{contact_exists.name}' (não sobrescrevendo com '{contact_name}')")
                contact_name = contact_exists.name
                logger.info(f"[NAME_TRACKING] DEPOIS: contact_name='{contact_name}' (preservado)")

            if contact_exists.company_id != company_id:
                logger.info("[Celery] Contato existe para outra empresa, criando novo registro.")
                db.execute(text("""
                    INSERT INTO contacts
                        (client_id, company_id, phone, name, photo, sender_lid, source_id, thumbnail_url)
                    VALUES (:client_id, :company_id, :phone, :name, :photo, :sender_lid,
                            :source_id, :thumbnail_url)
                    ON CONFLICT (client_id, company_id, phone) DO UPDATE
                    SET name = EXCLUDED.name,
                        photo = EXCLUDED.photo,
                        sender_lid = EXCLUDED.sender_lid,
                        source_id = EXCLUDED.source_id,
                        thumbnail_url = EXCLUDED.thumbnail_url
                """), {
                    "client_id": client_id_db,
                    "company_id": company_id,
                    "phone": phone,
                    "name": contact_name,
                    "photo": data.get("photo", ""),
                    "sender_lid": data.get("senderLid") or data.get("chatLid"),
                    "source_id": data.get("externalAdReply", {}).get("sourceId"),
                    "thumbnail_url": data.get("externalAdReply", {}).get("thumbnailUrl")
                })
            else:
                db.execute(text("""
                    UPDATE contacts
                    SET name = CASE
                               WHEN name IS NULL OR name = '' OR name = :phone
                               THEN :name
                               ELSE name
                               END,
                        photo = :photo,
                        sender_lid = :sender_lid,
                        source_id = :source_id,
                        thumbnail_url = :thumbnail_url
                    WHERE client_id = :client_id
                      AND company_id = :company_id
                      AND phone = :phone
                """), {
                    "name": contact_name,
                    "photo": data.get("photo", ""),
                    "sender_lid": data.get("senderLid") or data.get("chatLid"),
                    "source_id": data.get("externalAdReply", {}).get("sourceId"),
                    "thumbnail_url": data.get("externalAdReply", {}).get("thumbnailUrl"),
                    "client_id": client_id_db,
                    "company_id": company_id,
                    "phone": phone
                })
            logger.info("[Celery] Contato atualizado em 'contacts'.")
        else:
            logger.info("[Celery] Contato não existe, inserindo em 'contacts'.")
            db.execute(text("""
                INSERT INTO contacts
                    (client_id, company_id, phone, name, photo, sender_lid, source_id, thumbnail_url)
                VALUES (:client_id, :company_id, :phone, :name, :photo, :sender_lid,
                        :source_id, :thumbnail_url)
            """), {
                "client_id": client_id_db,
                "company_id": company_id,
                "phone": phone,
                "name": contact_name,
                "photo": data.get("photo", ""),
                "sender_lid": data.get("senderLid") or data.get("chatLid"),
                "source_id": data.get("externalAdReply", {}).get("sourceId"),
                "thumbnail_url": data.get("externalAdReply", {}).get("thumbnailUrl")
            })
            logger.info("[Celery] Contato inserido em 'contacts'.")

        # 8) Inserir/atualizar leads
        final_sender_lid = data.get("senderLid") or data.get("chatLid")
        source_id = data.get("externalAdReply", {}).get("sourceId")
        thumbnail_url = data.get("externalAdReply", {}).get("thumbnailUrl")

        lead_id_found = None
        lead_id_inserted = None
        logger.info(f"[DEBUG_LEAD_CREATION] Checking conditions: final_sender_lid={final_sender_lid}, source_id={source_id}, thumbnail_url={thumbnail_url}")
        if final_sender_lid or source_id or thumbnail_url:
            logger.info(f"[DEBUG_LEAD_CREATION] Conditions met - checking if {phone} is customer...")
            # VERIFICAR SE JÁ É CLIENTE ANTES DE CRIAR LEAD
            is_customer = db.execute(text("""
                SELECT p.id FROM clientes p
                JOIN contacts c ON p.contact_id = c.id
                WHERE c.phone = :phone AND c.company_id = :company_id
                LIMIT 1
            """), {"phone": phone, "company_id": company_id}).fetchone()

            if is_customer:
                logger.info(f"[DEBUG_LEAD_CREATION] ✅ {phone} já é CLIENTE (id={is_customer.id}) - NÃO criando lead")
            else:
                logger.info(f"[DEBUG_LEAD_CREATION] ❌ {phone} NÃO é cliente - processando lead...")
                logger.info("[Celery] Identificado um lead; verificando se já existe.")
                existing_lead = db.execute(text("""
                    SELECT id, name
                    FROM leads
                    WHERE phone = :phone
                      AND company_id = :company_id
                    LIMIT 1
                """), {
                    "phone": phone,
                    "company_id": company_id
                }).fetchone()

                if existing_lead:
                    lead_id_found = existing_lead.id
                    logger.info(f"[Celery] Lead já existe (id={lead_id_found}). Atualizando dados se necessário...")

                    # Determinar o nome a ser usado para o lead
                    lead_name = contact_name
                    if from_me and existing_lead.name and existing_lead.name.strip():
                        logger.info(f"[NAME_TRACKING_LEAD] ANTES: existing_lead.name='{existing_lead.name}', contact_name='{contact_name}', fromMe={from_me}")
                        logger.info(f"[Celery] Preservando nome existente do lead: '{existing_lead.name}' (não sobrescrevendo com '{contact_name}')")
                        lead_name = existing_lead.name
                        logger.info(f"[NAME_TRACKING_LEAD] DEPOIS: lead_name='{lead_name}' (preservado)")

                    db.execute(text("""
                        UPDATE leads
                        SET source_id      = COALESCE(:source_id, source_id),
                            thumbnail_url  = COALESCE(:thumbnail_url, thumbnail_url),
                            sender_lid     = COALESCE(:sender_lid, sender_lid),
                            name           = CASE
                                           WHEN name IS NULL OR name = '' OR name = :phone
                                           THEN :name
                                           ELSE name
                                           END
                        WHERE id = :lead_id
                          AND company_id = :company_id
                          AND client_id = :client_id
                    """), {
                        "source_id": source_id,
                        "thumbnail_url": thumbnail_url,
                        "sender_lid": final_sender_lid,
                        "name": lead_name,
                        "phone": phone,
                        "lead_id": lead_id_found,
                        "company_id": company_id,
                        "client_id": str(client_id_db)
                    })
                    logger.info("[Celery] Lead existente atualizado em 'leads'.")

                else:
                    # VERIFICAR SE JÁ É CLIENTE ANTES DE CRIAR LEAD
                    is_customer = db.execute(text("""
                        SELECT p.id FROM clientes p
                        JOIN contacts c ON p.contact_id = c.id
                        WHERE c.phone = :phone AND c.company_id = :company_id
                        LIMIT 1
                    """), {"phone": phone, "company_id": company_id}).fetchone()

                    if is_customer:
                        logger.info(f"[Celery] {phone} já é CLIENTE (id={is_customer.id}) - NÃO criando lead")
                    else:
                        logger.info("[Celery] Lead não existe, inserindo em 'leads'.")
                        row_followup_seq = db.execute(text("""
                            SELECT id
                            FROM follow_up_sequences
                            WHERE company_id = :company_id
                              AND client_id = :client_id
                            ORDER BY id
                            LIMIT 1
                        """), {
                            "company_id": company_id,
                            "client_id": str(client_id_db)
                        }).fetchone()

                        sequence_id = row_followup_seq.id if row_followup_seq else None

                        from pytz import timezone
                        sp_tz = timezone('America/Sao_Paulo')
                        data_entrada = dt.datetime.utcnow().astimezone(sp_tz).strftime("%Y-%m-%d %H:%M:%S")

                        # Inserindo o lead
                        result_insert = db.execute(text("""
                            INSERT INTO leads
                                (client_id, company_id, name, phone, source_id, thumbnail_url,
                                 sender_lid, created_at, data_entrada, follow_up_sequence_id)
                            VALUES (:client_id, :company_id, :name, :phone, :source_id,
                                    :thumbnail_url, :sender_lid, :created_at, :data_entrada, :sequence_id)
                            RETURNING id
                        """), {
                            "client_id": str(client_id_db),
                            "company_id": company_id,
                            "name": contact_name,
                            "phone": phone,
                            "source_id": source_id,
                            "thumbnail_url": thumbnail_url,
                            "sender_lid": final_sender_lid,
                            "created_at": data_entrada,
                            "data_entrada": data_entrada,
                            "sequence_id": sequence_id
                        })
                        lead_id_inserted = result_insert.fetchone().id
                        logger.info(f"[Celery] Novo lead inserido em 'leads'. (sequence_id={sequence_id}, lead_id={lead_id_inserted})")

                        # Se houver follow_up_sequence_id, buscar dados do primeiro step e agendar
                        if sequence_id:
                            first_step = db.execute(text("""
                                SELECT send_after, send_after_unit, step_number
                                FROM follow_up_steps
                                WHERE follow_up_sequence_id = :seq_id
                                  AND step_number = 1
                                LIMIT 1
                            """), {
                                "seq_id": sequence_id
                            }).fetchone()

                            if first_step:
                                company_data = db.execute(
                                    text("""
                                        SELECT zapi_instance_id, zapi_token
                                        FROM companies
                                        WHERE id = :company_id
                                    """),
                                    {"company_id": company_id}
                                ).fetchone()

                                if company_data and company_data.zapi_instance_id and company_data.zapi_token:
                                    from pytz import timezone
                                    sp_tz = timezone('America/Sao_Paulo')
                                    data_entrada_naive = dt.datetime.strptime(data_entrada, "%Y-%m-%d %H:%M:%S")
                                    data_entrada_dt = sp_tz.localize(data_entrada_naive)

                                    # Carregar schedule_data (se existir)
                                    row_sched_config = db.execute(text("""
                                        SELECT schedule_data
                                        FROM follow_up_schedule_configs
                                        WHERE company_id = :company_id
                                          AND follow_up_sequence_id = :sequence_id
                                        LIMIT 1
                                    """), {
                                        "company_id": company_id,
                                        "sequence_id": sequence_id
                                    }).fetchone()

                                    if row_sched_config and row_sched_config.schedule_data:
                                        try:
                                            # Se já for dict, não chamar json.loads
                                            if isinstance(row_sched_config.schedule_data, dict):
                                                schedule_data_json = row_sched_config.schedule_data
                                            else:
                                                schedule_data_json = json.loads(row_sched_config.schedule_data)

                                            day_of_week = data_entrada_dt.strftime('%A').lower()
                                            day_config = schedule_data_json.get(day_of_week, {})
                                            if day_config:
                                                start_str = day_config.get('start', '08:00')
                                                end_str   = day_config.get('end',   '18:00')
                                                start_hour, start_minute = map(int, start_str.split(':'))
                                                end_hour,   end_minute   = map(int, end_str.split(':'))
                                                start_time = data_entrada_dt.replace(hour=start_hour, minute=start_minute, second=0)
                                                end_time   = data_entrada_dt.replace(hour=end_hour,   minute=end_minute,   second=0)

                                                if data_entrada_dt < start_time:
                                                    data_entrada_dt = start_time
                                                elif data_entrada_dt > end_time:
                                                    data_entrada_dt = (data_entrada_dt + timedelta(days=1)).replace(
                                                        hour=start_hour, minute=start_minute, second=0
                                                    )
                                        except Exception as e:
                                            logger.error(f"[Celery] Erro ao interpretar schedule_data: {str(e)}")

                                    # Cálculo do ETA com base em send_after / send_after_unit
                                    if first_step.send_after_unit == "minutes":
                                        eta = data_entrada_dt + timedelta(minutes=first_step.send_after)
                                    elif first_step.send_after_unit == "hours":
                                        eta = data_entrada_dt + timedelta(hours=first_step.send_after)
                                    elif first_step.send_after_unit == "days":
                                        eta = data_entrada_dt + timedelta(days=first_step.send_after)
                                    else:
                                        eta = data_entrada_dt

                                    # Converter para UTC para o Celery
                                    from pytz import UTC
                                    eta_utc = eta.astimezone(UTC)
                                    logger.info(f"[Celery] Agendando primeiro follow-up para {eta} (UTC: {eta_utc})")

                                    db.commit()
                                    from backend.services.company_access_control import capture_company_job_epoch
                                    from backend.worker.tasks import enviar_passo_followup

                                    operational_epoch = capture_company_job_epoch(
                                        db,
                                        company_id,
                                    )
                                    enviar_passo_followup.apply_async(
                                        args=[
                                            lead_id_inserted,
                                            first_step.step_number,
                                            sequence_id,
                                            sequence_id,
                                            operational_epoch,
                                        ],
                                        eta=eta_utc
                                    )
                                    db.commit()
                                    logger.info("[Celery] Follow-up agendado com sucesso.")

        db.commit()

        # 8.1) Incrementa unread_count se for do lead (e não do LLM)
        # Se a mensagem não é do usuário (from_me=False) e não é do LLM
        if not from_me and sender_name != "LLM":
            db.execute(text("""
                UPDATE contacts
                SET unread_count = unread_count + 1
                WHERE client_id  = :client_id
                AND company_id  = :company_id
                AND phone      = :phone
            """), {
                "client_id": client_id_db,
                "company_id": company_id,
                "phone": phone
            })
            db.commit()
            logger.info(f"[Celery] unread_count incrementado para o contato {phone}.")

        # === Chamar a função para armazenar a imagem do anúncio (se existir)
        store_ad_campaign_media_once(db, company_id, source_id, thumbnail_url)

        # 9) Publicar no Redis (WebSocket)
        # SEMPRE publicar todas as mensagens no Redis
        # O frontend já tem lógica para evitar duplicação baseada em localMessageId
        message_payload = {
            "type": msg_type,
            "content": content,
            "phone": phone,
            "senderName": sender_name,
            "photo": data.get("photo", ""),
            "fromMe": from_me,
            "messageId": message_id,
            "momment": momment,
            "company_id": company_id,
            "fromApi": from_api  # Incluir este campo para o frontend saber a origem
        }
        publish_to_redis(company_id, message_payload)
        logger.info(f"[Celery] Mensagem publicada no Redis (fromMe={from_me}, fromApi={from_api})")

        # Inicializar user_text antes de qualquer processamento
        user_text = ""

        # 9.5) NOVO: Processar contatos compartilhados como indicações
        if msg_type == "contact" and not from_me:
            logger.info(f"[Celery] 📇 Processando contato compartilhado como possível indicação")
            try:
                # Extrair informações do contato
                contact_info = data.get("contact", {})
                display_name = contact_info.get("displayName", "")
                phones = contact_info.get("phones", [])

                if display_name and phones:
                    # Processar como indicação automaticamente
                    referral_phone = phones[0] if phones else ""

                    # Verificar se há campanha de indicação ativa
                    from backend.models import ReferralCampaign
                    campaign = db.query(ReferralCampaign).filter(
                        ReferralCampaign.company_id == company_id,
                        ReferralCampaign.active == True
                    ).first()

                    if campaign:
                        logger.info(f"[Celery] ✅ Campanha de indicação ativa encontrada. Processando {display_name} - {referral_phone}")

                        # Criar lead automaticamente
                        from backend.models import Lead, Contact as ContactModel
                        from datetime import datetime

                        # Verificar se já existe lead com esse telefone
                        existing_lead = db.query(Lead).filter(
                            Lead.phone == referral_phone,
                            Lead.company_id == company_id
                        ).first()

                        if not existing_lead:
                            # Criar novo lead
                            new_lead = Lead(
                                client_id=str(client_id_db),
                                company_id=company_id,
                                name=display_name,
                                phone=referral_phone,
                                source_id="Indicação",
                                created_at=dt.datetime.utcnow(),
                                data_entrada=dt.datetime.utcnow()
                            )
                            db.add(new_lead)
                            db.flush()

                            logger.info(f"[Celery] ✅ Lead criado para indicação: {display_name} ({referral_phone})")

                            # Criar/atualizar contato
                            contact = db.query(ContactModel).filter(
                                ContactModel.phone == referral_phone,
                                ContactModel.company_id == company_id
                            ).first()

                            if not contact:
                                contact = ContactModel(
                                    client_id=client_id_db,
                                    company_id=company_id,
                                    phone=referral_phone,
                                    name=display_name
                                )
                                db.add(contact)

                            db.commit()

                            # Agendar mensagem de boas-vindas usando ReferralService existente
                            if campaign.contact_referees_immediately:
                                try:
                                    from backend.agents_sdk.services.referral_service import ReferralService

                                    # Usar o serviço existente que já tem toda a lógica
                                    referral_service = ReferralService(db)

                                    # Buscar nome do indicador (quem está indicando)
                                    referrer_contact = db.query(ContactModel).filter(
                                        ContactModel.phone == phone,
                                        ContactModel.company_id == company_id
                                    ).first()
                                    referrer_name = referrer_contact.name if referrer_contact else "Um amigo"

                                    # Usar o método existente que já gera mensagem com IA e agenda
                                    success = referral_service._schedule_referee_welcome(
                                        company_id=company_id,
                                        referee_phone=referral_phone,
                                        referee_name=display_name,
                                        referrer_name=referrer_name,
                                        campaign=campaign
                                    )

                                    if success:
                                        logger.info(f"[Celery] ✅ Mensagem de boas-vindas agendada via ReferralService para {display_name}")
                                    else:
                                        logger.warning(f"[Celery] ⚠️ Falha ao agendar boas-vindas para {display_name}")

                                except Exception as e:
                                    logger.error(f"[Celery] ❌ Erro ao agendar boas-vindas via ReferralService: {e}")

                            # Enviar mensagem de confirmação
                            confirmation_msg = f"🎉 Perfeito! Recebi o contato do(a) {display_name}! Vou entrar em contato em breve para oferecer nosso desconto especial de indicação.\n\nVocê ainda pode indicar mais 2 pessoas! Tem mais alguém que precisa de tratamento de serviços?"

                            # Definir user_text para que o LLM processe a confirmação
                            user_text = f"Usuário compartilhou contato para indicação: {display_name} - {referral_phone}"

                            # Adicionar mensagem de confirmação ao chat
                            append_message_to_chat_file(company_id, phone, from_me=False, content=user_text)
                            append_message_to_chat_file(company_id, phone, from_me=True, content=confirmation_msg)

                            logger.info(f"[Celery] 📲 Mensagem de confirmação preparada para envio")
                        else:
                            logger.info(f"[Celery] ⚠️ Lead já existe para {referral_phone}")
                            user_text = f"Contato {display_name} já foi indicado anteriormente."
                    else:
                        logger.info(f"[Celery] ⚠️ Nenhuma campanha de indicação ativa para company_id={company_id}")
                        user_text = f"Recebi o contato de {display_name}. Obrigado!"
                else:
                    logger.info(f"[Celery] ⚠️ Contato compartilhado sem nome ou telefone completo")
                    user_text = "Recebi o contato compartilhado. Obrigado!"

            except Exception as e:
                logger.error(f"[Celery] ❌ Erro ao processar contato como indicação: {str(e)}")
                user_text = content  # Fallback para o conteúdo original

        # 10) Se não for from_me => transcrever/analise imagem/vídeo
        if not from_me and msg_type != "contact":
            if msg_type == "text":
                user_text = content.strip() if content else ""
                logger.info(f"[Celery] Texto extraído: '{user_text}'")
            elif msg_type == "image" and content:
                logger.info(f"[Celery] Processando imagem via Google Vision: {content}")
                user_text = analyze_image_with_google_vision(content)
            elif msg_type == "audio" and content:
                logger.info(f"[Celery] Transcrevendo áudio: {content}")
                user_text = transcribe_audio(
                    content,
                    api_key=_company_openai_key_for_media(db, company_id),
                )
            elif msg_type == "video" and content:
                logger.info(f"[Celery] Transcrevendo vídeo: {content}")
                user_text = transcribe_video(
                    content,
                    api_key=_company_openai_key_for_media(db, company_id),
                )

            if user_text and (msg_type != "text"):
                logger.info("[Celery] Transcrição obtida. Salvando no .txt (não sobrescrevendo BD).")
                append_message_to_chat_file(company_id, phone, from_me=False, content=user_text)
            else:
                user_text = user_text or content

            # CORREÇÃO FINAL: Garantir que mensagens waitingMessage tenham texto para o LLM
            if not user_text and data.get('waitingMessage', False):
                user_text = "Usuário demonstrou interesse através do anúncio e iniciou a conversa"
                logger.info(f"[Celery] Definindo texto padrão para waitingMessage sem conteúdo: '{user_text}'")

        if not from_me and not user_text:
            logger.info("[Celery] Nenhum texto extraído. Sem LLM.")

            # ANTES DE SAIR: Verificar se é resposta de enquete NPS
            poll_vote_data = data.get('pollVote')
            logger.info(f"[Celery] 🔍 Verificando pollVote antes de sair: {poll_vote_data}")

            if poll_vote_data:
                logger.info(f"[Celery] 🎯 DETECTADA RESPOSTA DE ENQUETE NPS! pollVote: {poll_vote_data}")
                try:
                    process_nps_response(db, company_id, data)
                    logger.info(f"[Celery] ✅ Resposta NPS processada com sucesso!")
                except Exception as e:
                    logger.error(f"[Celery] ❌ Erro ao processar resposta NPS: {str(e)}")

            return

        # 11) Verificar human_mode
        if not from_me:
            row_human_mode = db.execute(text("""
                SELECT human_mode
                FROM contacts
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
                logger.info("[Celery] Contato com human_mode=True. Pulando LLM.")
                # Atualizar status para completed antes de retornar
                if audit_id:
                    from backend.webhook_audit import update_audit_status
                    update_audit_status(db, audit_id, "completed", error="Human mode ativo - processamento manual")
                return

        # 12) Classificar mensagem + detectar estágio do funil
        msg_category = "desconhecida"
        if not from_me and user_text:
            model_path = os.getenv("MESSAGE_CATEGORY_MODEL_PATH")
            if model_path and os.path.exists(model_path):
                from joblib import load
                try:
                    classification_pipeline = load(model_path)
                    msg_category = classification_pipeline.predict([user_text])[0]
                    logger.info(f"[Celery] Mensagem classificada como: {msg_category}")
                except Exception as e:
                    logger.error(f"[Celery] Erro ao classificar com scikit-learn: {str(e)}")
            else:
                logger.debug("[Celery] MESSAGE_CATEGORY_MODEL_PATH não configurado; classificação local ignorada")

        lead_id = lead_id_found if lead_id_found else lead_id_inserted
        funnel_stage = "leads"
        funnel_status = None

        if lead_id:
            vendas_exists = db.execute(text("""
                SELECT id FROM vendas
                WHERE lead_id = :lid
                  AND company_id = :cid
                LIMIT 1
            """), {"lid": lead_id, "cid": company_id}).fetchone()
            if vendas_exists:
                funnel_stage = "vendas"
            else:
                compare_exists = db.execute(text("""
                    SELECT id FROM comparecimentos
                    WHERE lead_id = :lid
                      AND company_id = :cid
                    LIMIT 1
                """), {"lid": lead_id, "cid": company_id}).fetchone()
                if compare_exists:
                    funnel_stage = "comparecimentos"
                else:
                    agend_exists = db.execute(text("""
                        SELECT id, status
                        FROM agendamentos
                        WHERE lead_id = :lid
                          AND company_id = :cid
                        LIMIT 1
                    """), {"lid": lead_id, "cid": company_id}).fetchone()
                    if agend_exists:
                        funnel_stage = "agendamentos"
                        funnel_status = agend_exists.status

        logger.info(f"[Celery] Etapa do funil: {funnel_stage}, status={funnel_status}")

        # (NOVO) [13] Verificação de horário de IA
        if not from_me and user_text:
            # Carrega config da tabela 'ai_response_windows'
            row_ai = db.execute(text("""
                SELECT timezone, time_windows
                FROM ai_response_windows
                WHERE company_id = :cid
                ORDER BY id DESC
                LIMIT 1
            """), {"cid": company_id}).fetchone()

            # Faça logs adicionais para debug:
            logger.info(f"[DEBUG] row_ai completo => {row_ai}")

            if row_ai:
                logger.info(f"[DEBUG] timezone => {row_ai.timezone}")
                logger.info(f"[DEBUG] time_windows => {row_ai.time_windows}")
                # se row_ai.time_windows for dict, exiba .keys()
                if isinstance(row_ai.time_windows, dict):
                    logger.info(f"[DEBUG] time_windows keys => {list(row_ai.time_windows.keys())}")
            else:
                logger.info("[DEBUG] Nenhum registro encontrado em ai_response_windows.")

            if row_ai:
                timezone_str = row_ai.timezone
                time_windows_obj = row_ai.time_windows  # Pode ser dict ou str

                if time_windows_obj:
                    import json
                    # Se já for dict, não precisa de json.loads
                    if isinstance(time_windows_obj, dict):
                        time_windows = time_windows_obj
                    else:
                        time_windows = json.loads(time_windows_obj)

                    # LOG adicional para debug
                    logger.info(f"[Celery] Comparando com timezone configurado pelo cliente: {timezone_str}")

                    # Verifica se está dentro de algum período habilitado
                    ia_enabled_result = is_ia_enabled_now(timezone_str, time_windows)
                    logger.info(f"[DEBUG] is_ia_enabled_now() retornou: {ia_enabled_result}")
                    if not ia_enabled_result:
                        logger.info("[Celery] Fora do horário habilitado. Não chamando LLM.")
                        # Atualizar status para completed antes de retornar
                        if audit_id:
                            from backend.webhook_audit import update_audit_status
                            update_audit_status(db, audit_id, "completed", error="Fora do horário de atendimento da IA")
                        return
                else:
                    logger.info("[Celery] time_windows vazio. IA desabilitada.")
                    # Atualizar status para completed antes de retornar
                    if audit_id:
                        from backend.webhook_audit import update_audit_status
                        update_audit_status(db, audit_id, "completed", error="Configuração de horário vazia - IA desabilitada")
                    return
            else:
                logger.info("[Celery] Nenhuma config ai_response_windows. IA desabilitada.")
                # Atualizar status para completed antes de retornar
                if audit_id:
                    from backend.webhook_audit import update_audit_status
                    update_audit_status(db, audit_id, "completed", error="Sem configuração de horário - IA desabilitada")
                return

        # 14) Debounce + LLM (Nova implementação com Celery ETA)
        logger.info(f"[DEBUG] Chegou na seção debounce: from_me={from_me}, user_text='{user_text}'")
        if not from_me and user_text:
            logger.info(f"[DEBUG] Condições atendidas para debounce - iniciando com Celery ETA...")

            # Preparar dados do callback para a task Celery
            callback_data = {
                'company_id': company_id,
                'client_id_db': client_id_db,
                'msg_category': msg_category,
                'funnel_stage': funnel_stage,
                'funnel_status': funnel_status
            }

            from backend.worker.debounce_tasks import schedule_debounced_processing
            schedule_debounced_processing(phone, user_text, callback_data)

        # 15) Verificar se é resposta de enquete NPS
        poll_vote_data = data.get('pollVote')
        logger.info(f"[Celery] 🔍 Verificando pollVote: {poll_vote_data}")

        if poll_vote_data:
            logger.info(f"[Celery] 🎯 DETECTADA RESPOSTA DE ENQUETE NPS! pollVote: {poll_vote_data}")
            try:
                process_nps_response(db, company_id, data)
                logger.info(f"[Celery] ✅ Resposta NPS processada com sucesso!")
            except Exception as e:
                logger.error(f"[Celery] ❌ Erro ao processar resposta NPS: {str(e)}")
        else:
            logger.info(f"[Celery] ℹ️ Não é resposta de enquete (sem pollVote)")

        logger.info("[Celery] process_incoming_zapi_message finalizado com sucesso.")

        # Atualizar status para 'completed' se audit_id fornecido
        if audit_id:
            from backend.webhook_audit import update_audit_status
            update_audit_status(db, audit_id, "completed")

    except Exception as e:
        logger.exception(f"[Celery] Erro ao processar mensagem: {str(e)}")

        # Atualizar status para 'failed' se audit_id fornecido
        if audit_id:
            try:
                from backend.webhook_audit import update_audit_status
                update_audit_status(db, audit_id, "failed", error=str(e))
            except:
                pass

    finally:
        db.close()


def process_nps_response(db: Session, company_id: int, payload: dict):
    """
    Processa resposta de enquete NPS
    """
    try:
        logger.info(f"[NPS] 🎯 Iniciando processamento de resposta NPS para empresa {company_id}")

        poll_vote = payload.get('pollVote', {})
        poll_message_id = poll_vote.get('pollMessageId')
        options = poll_vote.get('options', [])
        phone = payload.get('phone')
        response_message_id = payload.get('messageId')

        logger.info(f"[NPS] 📊 Dados extraídos: poll_message_id={poll_message_id}, options={options}, phone={phone}")

        if not poll_message_id or not options or not phone:
            logger.warning(f"[NPS] ❌ Dados insuficientes para processar resposta NPS: poll_message_id={poll_message_id}, options={options}, phone={phone}")
            return

        # Extrair nota da resposta (1-5 estrelas, formato: "3 ⭐")
        try:
            option_text = options[0].get('name', '')
            logger.info(f"[NPS] 📝 Texto da opção selecionada: '{option_text}'")

            # Extrair apenas o número da string "3 ⭐"
            score = int(option_text.split(' ')[0])
            logger.info(f"[NPS] ⭐ Score extraído: {score}")

            if score < 1 or score > 5:
                logger.warning(f"[NPS] ❌ Score inválido: {score}")
                return
        except (ValueError, IndexError) as e:
            logger.warning(f"[NPS] ❌ Não foi possível extrair score da resposta: {options}. Erro: {e}")
            return

        # Buscar registro NPS pendente
        nps_record = db.execute(text("""
            UPDATE nps_responses
            SET score = :score,
                response_message_id = :response_message_id,
                response_text = :response_text,
                status = 'answered',
                answered_at = NOW()
            WHERE poll_message_id = :poll_message_id
            AND company_id = :company_id
            RETURNING id
        """), {
            "score": score,
            "response_message_id": response_message_id,
            "response_text": f"Nota: {score}",
            "poll_message_id": poll_message_id,
            "company_id": company_id
        }).fetchone()

        if nps_record:
            db.commit()
            logger.info(f"[NPS] Resposta processada com sucesso - Score: {score}, Phone: {phone}")

            # Atualizar também a mensagem na tabela messages
            import json
            try:
                db.execute(text("""
                    UPDATE messages
                    SET content = (
                        content::jsonb
                        || jsonb_build_object(
                            'nps_data',
                            (content::jsonb->'nps_data')
                            || jsonb_build_object('status', 'answered')
                            || jsonb_build_object('score', :score)
                            || jsonb_build_object('answered_at', :answered_at)
                        )
                    )::text
                    WHERE content::jsonb->'nps_data'->>'message_id' = :poll_message_id
                    AND company_id = :company_id
                    AND message_type = 'nps'
                """), {
                    "score": score,
                    "answered_at": dt.datetime.now().isoformat(),
                    "poll_message_id": poll_message_id,
                    "company_id": company_id
                })
                db.commit()
                logger.info(f"[NPS] Mensagem atualizada na tabela messages")
            except Exception as e:
                logger.error(f"[NPS] Erro ao atualizar mensagem: {str(e)}")

            # Publicar no Redis para atualização em tempo real
            nps_update_data = {
                'type': 'nps_update',
                'nps_id': nps_record.id,
                'phone': phone,
                'score': score,
                'answered_at': dt.datetime.now().isoformat(),
                'poll_message_id': poll_message_id
            }
            logger.info(f"[NPS] 📡 Enviando nps_update via Redis: {nps_update_data}")

            publish_to_redis(company_id, nps_update_data)
            logger.info(f"[NPS] ✅ nps_update enviado via Redis para empresa {company_id}")
        else:
            logger.warning(f"[NPS] Nenhum registro NPS encontrado para message_id: {poll_message_id}")

    except Exception as e:
        logger.error(f"[NPS] Erro ao processar resposta: {str(e)}")
        db.rollback()
    finally:
        db.close()
