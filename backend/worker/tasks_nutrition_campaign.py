import logging
import time as pytime
import os
import base64
import json
import redis
import uuid
import random
from datetime import datetime, timedelta
from .celery_app import app
from sqlalchemy import text
from sqlalchemy.orm import Session
from pytz import timezone, UTC
import pytz
from datetime import time as dt_time
from typing import Optional
from backend.db import SessionLocal
from backend.models import Message
from backend.prompt.memory import memory_manager
from backend.runtime_settings import LOG_DIR as RUNTIME_LOG_DIR, MEDIA_BASE_PATH as RUNTIME_MEDIA_BASE_PATH
from .flow_control import check_flow_control

# Configuração de logs
LOG_DIR = str(RUNTIME_LOG_DIR)
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "nutrition_campaign_tasks.log")

logger = logging.getLogger(__name__)
file_handler = logging.FileHandler(LOG_FILE)
file_formatter = logging.Formatter(
    '%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s'
)
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)
logger.setLevel(logging.INFO)

# Conexão Redis
redis_client = redis.Redis(host='localhost', port=6379, db=0)

# Base path para arquivos de mídia
MEDIA_BASE_PATH = str(RUNTIME_MEDIA_BASE_PATH)

def get_media_content(file_path: str, media_type: str) -> Optional[str]:
    """
    Converte arquivo de mídia em base64 ou retorna URL completa.
    Reutilizado dos outros tasks
    """
    try:
        if file_path.startswith(('http://', 'https://')):
            return file_path

        full_path = os.path.join(MEDIA_BASE_PATH, file_path)
        logger.info(f"[NutritionCampaign] Tentando acessar arquivo em: {full_path}")

        if not os.path.exists(full_path):
            logger.error(f"[NutritionCampaign] Arquivo não encontrado: {full_path}")
            return None

        with open(full_path, 'rb') as file:
            file_content = file.read()
            base64_content = base64.b64encode(file_content).decode('utf-8')

            if media_type == 'image':
                mime_type = 'image/png' if file_path.endswith('.png') else 'image/jpeg'
                return f"data:{mime_type};base64,{base64_content}"
            elif media_type == 'video':
                return f"data:video/mp4;base64,{base64_content}"
            elif media_type == 'audio':
                mime_type = 'audio/mp3' if file_path.endswith('.mp3') else 'audio/mpeg'
                return f"data:{mime_type};base64,{base64_content}"

            return base64_content
    except Exception as e:
        logger.error(f"[NutritionCampaign] Erro ao processar arquivo de mídia: {str(e)}", exc_info=True)
        return None

def publish_message_to_redis(msg_type: str, content: str, phone: str, from_me: bool = True):
    """Publica mensagem no Redis para broadcast via WebSocket."""
    try:
        message = {
            "type": msg_type,
            "content": content,
            "phone": phone,
            "senderName": "NutritionCampaign System",
            "photo": "",
            "fromMe": from_me,
            "messageId": f"nutrition_{int(datetime.utcnow().timestamp() * 1000)}",
            "momment": datetime.utcnow().isoformat(),
            "caption": None
        }

        logger.info(f"[NutritionCampaign] Publicando mensagem no Redis: {json.dumps(message)}")
        redis_client.publish('chat_messages', json.dumps(message))
        logger.info("[NutritionCampaign] Mensagem publicada com sucesso no Redis")

    except Exception as e:
        logger.error(f"[NutritionCampaign] Erro ao publicar mensagem no Redis: {str(e)}", exc_info=True)

def adjust_eta_to_schedule(eta_utc: datetime, schedule_data_str: str, tz_name: str = "America/Sao_Paulo") -> datetime:
    """
    Ajusta a data/hora para cair dentro das janelas de envio.
    Reutilizado dos outros tasks
    """
    try:
        schedule_data = json.loads(schedule_data_str) if isinstance(schedule_data_str, str) else schedule_data_str
    except Exception:
        return eta_utc

    tz_local = pytz.timezone(tz_name)
    dt_local = eta_utc.astimezone(tz_local)

    for _ in range(14):
        weekday_name = dt_local.strftime("%A").lower()
        day_config = schedule_data.get(weekday_name)

        if not day_config:
            dt_local += timedelta(days=1)
            dt_local = dt_local.replace(hour=0, minute=0, second=0, microsecond=0)
            continue

        start_str = day_config.get("start")
        end_str = day_config.get("end")
        if not start_str or not end_str:
            dt_local += timedelta(days=1)
            dt_local = dt_local.replace(hour=0, minute=0, second=0, microsecond=0)
            continue

        sh, sm = map(int, start_str.split(":"))
        eh, em = map(int, end_str.split(":"))
        start_time = dt_time(sh, sm)
        end_time = dt_time(eh, em)

        current_time = dt_local.time()

        if current_time < start_time:
            dt_local = dt_local.replace(hour=sh, minute=sm, second=0, microsecond=0)
            return dt_local.astimezone(pytz.UTC)

        if current_time > end_time:
            dt_local += timedelta(days=1)
            dt_local = dt_local.replace(hour=0, minute=0, second=0, microsecond=0)
            continue

        return dt_local.astimezone(pytz.UTC)

    return eta_utc

def get_random_delay(min_seconds: int, max_seconds: int) -> int:
    """Gera delay aleatório entre min e max segundos para evitar detecção de spam."""
    return random.randint(min_seconds, max_seconds)

def check_contact_matches_criteria(db: Session, contact_id: int, company_id: int, sequence_id: int) -> Optional[dict]:
    """
    Verifica se o contato ainda atende aos critérios de targeting da sequência.
    Retorna dict com critérios matched ou None se não atender.
    """
    try:
        # Buscar critérios da sequência
        sequence_data = db.execute(
            text("""
                SELECT target_contact_status, target_contact_categories, target_contact_tags
                FROM nutrition_campaign_sequences
                WHERE id = :seq_id AND company_id = :company_id
            """),
            {"seq_id": sequence_id, "company_id": company_id}
        ).fetchone()

        if not sequence_data:
            return None

        # Buscar dados do contato
        contact_data = db.execute(
            text("""
                SELECT c.phone, c.name, p.status, p.categoria, p.tags
                FROM contacts c
                LEFT JOIN clientes p ON p.contact_id = c.id AND p.company_id = c.company_id
                WHERE c.id = :contact_id AND c.company_id = :company_id
            """),
            {"contact_id": contact_id, "company_id": company_id}
        ).fetchone()

        if not contact_data:
            return None

        matched_criteria = {}

        # Verificar status (se especificado)
        if sequence_data.target_contact_status and contact_data.status:
            if contact_data.status in sequence_data.target_contact_status:
                matched_criteria['status'] = contact_data.status
            else:
                logger.info(f"[NutritionCampaign] Contato {contact_id} status '{contact_data.status}' não atende critérios {sequence_data.target_contact_status}")
                return None

        # Verificar categoria (se especificado)
        if sequence_data.target_contact_categories and contact_data.categoria:
            if contact_data.categoria in sequence_data.target_contact_categories:
                matched_criteria['categoria'] = contact_data.categoria
            else:
                logger.info(f"[NutritionCampaign] Contato {contact_id} categoria '{contact_data.categoria}' não atende critérios {sequence_data.target_contact_categories}")
                return None

        # Verificar tags (se especificado)
        if sequence_data.target_contact_tags and contact_data.tags:
            contact_tags = contact_data.tags if isinstance(contact_data.tags, list) else []
            matching_tags = [tag for tag in sequence_data.target_contact_tags if tag in contact_tags]
            if matching_tags:
                matched_criteria['tags'] = matching_tags
            else:
                logger.info(f"[NutritionCampaign] Contato {contact_id} tags {contact_tags} não atendem critérios {sequence_data.target_contact_tags}")
                return None

        matched_criteria['phone'] = contact_data.phone
        matched_criteria['name'] = contact_data.name

        return matched_criteria

    except Exception as e:
        logger.error(f"[NutritionCampaign] Erro ao verificar critérios do contato: {str(e)}")
        return None

def insert_or_update_nutrition_execution(db: Session,
                                        contact_id: int,
                                        company_id: int,
                                        sequence_id: int,
                                        step_id: int,
                                        step_number: int,
                                        status: str,
                                        scheduled_for: Optional[datetime] = None,
                                        executed_at: Optional[datetime] = None,
                                        error_message: Optional[str] = None,
                                        random_delay_applied: Optional[int] = None,
                                        targeting_criteria_matched: Optional[dict] = None):
    """
    Insere ou atualiza a execução do nutrition campaign
    """
    try:
        db.execute(
            text("""
                INSERT INTO nutrition_campaign_executions (
                    contact_id, company_id, nutrition_campaign_sequence_id,
                    nutrition_campaign_step_id, step_number, status,
                    scheduled_for, executed_at, error_message,
                    random_delay_applied, targeting_criteria_matched
                )
                VALUES (
                    :contact_id, :company_id, :sequence_id, :step_id, :step_number,
                    :status, :scheduled_for, :executed_at, :error_message,
                    :random_delay_applied, :targeting_criteria_matched
                )
                ON CONFLICT (contact_id, nutrition_campaign_sequence_id, nutrition_campaign_step_id)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    scheduled_for = EXCLUDED.scheduled_for,
                    executed_at = EXCLUDED.executed_at,
                    error_message = EXCLUDED.error_message,
                    random_delay_applied = EXCLUDED.random_delay_applied,
                    targeting_criteria_matched = EXCLUDED.targeting_criteria_matched,
                    updated_at = now()
            """),
            {
                "contact_id": contact_id,
                "company_id": company_id,
                "sequence_id": sequence_id,
                "step_id": step_id,
                "step_number": step_number,
                "status": status,
                "scheduled_for": scheduled_for,
                "executed_at": executed_at,
                "error_message": error_message,
                "random_delay_applied": random_delay_applied,
                "targeting_criteria_matched": json.dumps(targeting_criteria_matched) if targeting_criteria_matched else None
            }
        )
        db.commit()
    except Exception as e:
        logger.error(f"[NutritionCampaign] Erro ao inserir/atualizar execução: {str(e)}")

@app.task
@check_flow_control('nutrition_campaign')
def enviar_passo_nutrition_campaign(
    contact_id: int,
    step_number: int,
    company_id: int,
    phone: str,
    operational_epoch: Optional[int] = None,
):
    """
    Task para enviar passo de campanha de nutrição
    Objetivo: engajamento com contatos através de mensagens automatizadas com timing aleatório
    """
    db = SessionLocal()
    try:
        from backend.services.company_access_control import validate_company_job_epoch
        if not validate_company_job_epoch(db, int(company_id), operational_epoch):
            db.execute(
                text("""
                    UPDATE nutrition_campaign_executions
                       SET status = 'CANCELED',
                           error_message = 'company_access_suspended',
                           updated_at = now()
                     WHERE contact_id = :contact_id
                       AND company_id = :company_id
                       AND status IN ('SCHEDULED', 'PROCESSING')
                """),
                {"contact_id": contact_id, "company_id": company_id},
            )
            db.commit()
            return
        logger.info(f"[NutritionCampaign] Iniciando step={step_number} para contato={contact_id}")

        # Lock para evitar duplicação
        lock_key = f"lock:nutrition_campaign:{contact_id}:{step_number}"
        lock_value = str(uuid.uuid4())

        if not redis_client.set(lock_key, lock_value, ex=60, nx=True):
            logger.info(f"[NutritionCampaign] Task já em processamento")
            return

        try:
            # Buscar sequência ativa
            seq = db.execute(
                text("""
                    SELECT id, name, message_delay_min, message_delay_max,
                           contact_delay_min, contact_delay_max, contact_delay_unit
                    FROM nutrition_campaign_sequences
                    WHERE company_id = :company_id AND active = true
                    LIMIT 1
                """),
                {"company_id": company_id}
            ).fetchone()

            if not seq:
                logger.warning(f"[NutritionCampaign] Nenhuma sequência ativa para company_id={company_id}")
                return

            # Verificar se já foi executado
            existing = db.execute(
                text("""
                    SELECT id, status FROM nutrition_campaign_executions
                    WHERE contact_id = :contact_id
                      AND step_number = :step_num
                      AND status IN ('SUCCESS', 'PROCESSING', 'CANCELED')
                    LIMIT 1
                """),
                {"contact_id": contact_id, "step_num": step_number}
            ).fetchone()

            if existing:
                logger.info(f"[NutritionCampaign] Step já executado com status={existing.status}")
                return

            # Verificar critérios de targeting
            criteria_match = check_contact_matches_criteria(db, contact_id, company_id, seq.id)
            if not criteria_match:
                logger.info(f"[NutritionCampaign] Contato {contact_id} não atende mais aos critérios de targeting")
                insert_or_update_nutrition_execution(
                    db, contact_id, company_id, seq.id, None, step_number,
                    'CANCELED', error_message='Contato não atende critérios de targeting'
                )
                return

            phone = criteria_match.get('phone', phone)  # Usar phone atualizado do contato

            # Buscar step atual
            step_obj = db.execute(
                text("""
                    SELECT id, send_after, send_after_unit, random_delay_min, random_delay_max
                    FROM nutrition_campaign_steps
                    WHERE nutrition_campaign_sequence_id = :seq_id
                      AND step_number = :step_num
                    LIMIT 1
                """),
                {"seq_id": seq.id, "step_num": step_number}
            ).fetchone()

            if not step_obj:
                logger.info(f"[NutritionCampaign] Step {step_number} não encontrado para sequência {seq.id}")
                return

            # Se for o primeiro passo, verificar janela de envio
            if step_number == 1:
                schedule_conf = db.execute(
                    text("""
                        SELECT schedule_data FROM nutrition_campaign_schedule_configs
                        WHERE company_id = :company_id
                          AND nutrition_campaign_sequence_id = :seq_id
                        LIMIT 1
                    """),
                    {"company_id": company_id, "seq_id": seq.id}
                ).fetchone()

                if schedule_conf and schedule_conf.schedule_data:
                    logger.info("[NutritionCampaign] Verificando janela de envio...")
                    now_utc = datetime.utcnow().replace(tzinfo=pytz.UTC)
                    now_adjusted = adjust_eta_to_schedule(now_utc, schedule_conf.schedule_data, "America/Sao_Paulo")

                    if now_adjusted > now_utc:
                        logger.info(f"[NutritionCampaign] Fora do horário. Reagendando para {now_adjusted}")
                        insert_or_update_nutrition_execution(
                            db, contact_id, company_id, seq.id, step_obj.id, step_number,
                            'SCHEDULED', scheduled_for=now_adjusted,
                            targeting_criteria_matched=criteria_match
                        )
                        enviar_passo_nutrition_campaign.apply_async(
                            args=[
                                contact_id,
                                step_number,
                                company_id,
                                phone,
                                operational_epoch,
                            ],
                            eta=now_adjusted
                        )
                        return

            # Marcar como PROCESSING
            insert_or_update_nutrition_execution(
                db, contact_id, company_id, seq.id, step_obj.id, step_number,
                'PROCESSING', targeting_criteria_matched=criteria_match
            )

            # Buscar dados da empresa para Z-API
            company_data = db.execute(
                text("""
                    SELECT zapi_instance_id, zapi_token
                    FROM companies
                    WHERE id = :company_id
                """),
                {"company_id": company_id}
            ).fetchone()

            if not company_data or not company_data.zapi_instance_id or not company_data.zapi_token:
                logger.error(f"[NutritionCampaign] Empresa {company_id} sem configuração Z-API")
                insert_or_update_nutrition_execution(
                    db, contact_id, company_id, seq.id, step_obj.id, step_number,
                    'FAILED', error_message='Sem configuração Z-API'
                )
                return

            instance_id = company_data.zapi_instance_id
            instance_token = company_data.zapi_token

            # Imports para envio
            from backend.routes.webhook import (
                send_text_to_zapi,
                send_image_to_zapi,
                send_audio_to_zapi,
                send_video_to_zapi,
                WhatsAppSendImageBody,
                WhatsAppSendAudioBody,
                WhatsAppSendVideoBody
            )

            # Buscar mensagens do step
            messages = db.execute(
                text("""
                    SELECT id, type, content
                    FROM nutrition_campaign_messages
                    WHERE nutrition_campaign_step_id = :step_id
                    ORDER BY id
                """),
                {"step_id": step_obj.id}
            ).fetchall()

            logger.info(f"[NutritionCampaign] Encontradas {len(messages)} mensagens para enviar")

            mensagens_enviadas = False
            envio_com_erro = False
            error_msg = None

            for idx, msg in enumerate(messages):
                try:
                    # Aplicar delay aleatório entre mensagens (exceto primeira)
                    if idx > 0:
                        delay = get_random_delay(seq.message_delay_min, seq.message_delay_max)
                        logger.info(f"[NutritionCampaign] Aguardando {delay}s antes da próxima mensagem")
                        pytime.sleep(delay)

                    logger.info(f"[NutritionCampaign] Processando mensagem: id={msg.id}, tipo={msg.type}")

                    if msg.type == "text":
                        response = send_text_to_zapi(
                            instance_id=instance_id,
                            instance_token=instance_token,
                            phone=phone,
                            message=msg.content,
                            company_id=company_id,
                            human_mode=False
                        )
                        logger.info(f"[NutritionCampaign] Resposta envio texto: {response}")
                        publish_message_to_redis("text", msg.content, phone)
                        mensagens_enviadas = True

                        # Persistir no banco
                        try:
                            new_message = Message(
                                client_id=None,  # Nutrition campaigns podem não ter client_id específico
                                company_id=company_id,
                                contact_phone=phone,
                                message_type="text",
                                content=msg.content,
                                sender_phone="NutritionCampaignFlow",
                                sender_name="Nutrition Campaign System",
                                from_me=True,
                                timestamp=datetime.utcnow()
                            )
                            db.add(new_message)
                            db.commit()

                            # Gravar no arquivo de chat
                            memory_manager.append_message_to_chat_file(
                                company_id=company_id,
                                contact_phone=phone,
                                from_me=True,
                                content=msg.content
                            )

                        except Exception as e:
                            logger.error(f"[NutritionCampaign] Erro ao salvar mensagem: {str(e)}")

                    elif msg.type in ["image", "video", "audio"]:
                        media_content = get_media_content(msg.content, msg.type)

                        if not media_content:
                            logger.error(f"[NutritionCampaign] Falha ao processar mídia: {msg.content}")
                            continue

                        if msg.type == "image":
                            response = send_image_to_zapi(
                                instance_id=instance_id,
                                instance_token=instance_token,
                                body=WhatsAppSendImageBody(
                                    phone=phone,
                                    image=media_content,
                                    caption=None
                                )
                            )
                            publish_message_to_redis("image", msg.content, phone)
                            mensagens_enviadas = True

                        elif msg.type == "audio":
                            response = send_audio_to_zapi(
                                instance_id=instance_id,
                                instance_token=instance_token,
                                body=WhatsAppSendAudioBody(
                                    phone=phone,
                                    audio=media_content
                                )
                            )
                            publish_message_to_redis("audio", msg.content, phone)
                            mensagens_enviadas = True

                        elif msg.type == "video":
                            response = send_video_to_zapi(
                                instance_id=instance_id,
                                instance_token=instance_token,
                                body=WhatsAppSendVideoBody(
                                    phone=phone,
                                    video=media_content,
                                    caption=None
                                )
                            )
                            publish_message_to_redis("video", msg.content, phone)
                            mensagens_enviadas = True

                    elif msg.type == "nps":
                        # Usar mensagem padrão do sistema se conteúdo estiver vazio
                        nps_question = msg.content if msg.content.strip() else "Em uma escala de 1 a 5, como você avalia nosso interesse em nutrição?"

                        # Usar a rota NPS existente
                        try:
                            from backend.routes.nps_routes import send_nps_internal

                            response = send_nps_internal(
                                phone=phone,
                                question=nps_question,
                                campaign_name="nutrition_campaign",
                                context="nutrition_campaign",
                                company_id=company_id,
                                db=db
                            )
                            logger.info(f"[NutritionCampaign] Resposta envio NPS: {response}")

                            # Publicar no Redis com estrutura correta para NPS
                            nps_content = {
                                "nps_data": {
                                    "question": nps_question,
                                    "status": "sent",
                                    "message_id": response.get('message_id')
                                }
                            }
                            publish_message_to_redis("nps", json.dumps(nps_content), phone)
                            mensagens_enviadas = True

                        except Exception as e:
                            logger.error(f"[NutritionCampaign] Erro ao enviar NPS via rota: {str(e)}")
                            envio_com_erro = True
                            error_msg = str(e)

                except Exception as e:
                    logger.error(f"[NutritionCampaign] Erro ao processar mensagem: {str(e)}", exc_info=True)
                    envio_com_erro = True
                    error_msg = str(e)
                    continue

            # Definir status final
            if mensagens_enviadas:
                final_status = 'SUCCESS' if not envio_com_erro else 'FAILED'
            else:
                final_status = 'FAILED'
                if not error_msg:
                    error_msg = "Nenhuma mensagem enviada"

            # Atualizar execução
            insert_or_update_nutrition_execution(
                db, contact_id, company_id, seq.id, step_obj.id, step_number,
                final_status, executed_at=datetime.utcnow(), error_message=error_msg
            )

            if final_status == 'FAILED':
                logger.error(f"[NutritionCampaign] Falha no envio. Encerrando sem agendar próximo.")
                return

            # Verificar e agendar próximo step
            next_step = db.execute(
                text("""
                    SELECT id, step_number, send_after, send_after_unit, random_delay_min, random_delay_max
                    FROM nutrition_campaign_steps
                    WHERE nutrition_campaign_sequence_id = :seq_id
                      AND step_number = :next_step_num
                    LIMIT 1
                """),
                {"seq_id": seq.id, "next_step_num": step_number + 1}
            ).fetchone()

            if next_step:
                # Calcular ETA base
                unit = next_step.send_after_unit
                delta = {}
                if unit == "days":
                    delta["days"] = next_step.send_after
                elif unit == "hours":
                    delta["hours"] = next_step.send_after
                elif unit == "minutes":
                    delta["minutes"] = next_step.send_after

                eta = datetime.utcnow() + timedelta(**delta)

                # Aplicar delay aleatório do step
                random_delay = get_random_delay(next_step.random_delay_min, next_step.random_delay_max)
                eta += timedelta(seconds=random_delay)
                logger.info(f"[NutritionCampaign] Delay aleatório aplicado: {random_delay}s")

                # Ajustar por schedule se existir
                schedule_conf = db.execute(
                    text("""
                        SELECT schedule_data FROM nutrition_campaign_schedule_configs
                        WHERE company_id = :company_id
                          AND nutrition_campaign_sequence_id = :seq_id
                        LIMIT 1
                    """),
                    {"company_id": company_id, "seq_id": seq.id}
                ).fetchone()

                if schedule_conf and schedule_conf.schedule_data:
                    eta_original = eta
                    eta = adjust_eta_to_schedule(eta, schedule_conf.schedule_data, "America/Sao_Paulo")
                    logger.info(f"[NutritionCampaign] Horário ajustado de {eta_original} para {eta}")

                # Registrar agendamento
                insert_or_update_nutrition_execution(
                    db, contact_id, company_id, seq.id, next_step.id, next_step.step_number,
                    'SCHEDULED', scheduled_for=eta, random_delay_applied=random_delay,
                    targeting_criteria_matched=criteria_match
                )

                # Agendar próximo
                enviar_passo_nutrition_campaign.apply_async(
                    args=[
                        contact_id,
                        next_step.step_number,
                        company_id,
                        phone,
                        operational_epoch,
                    ],
                    eta=eta
                )
                logger.info(f"[NutritionCampaign] Próximo step={next_step.step_number} agendado para {eta}")
            else:
                logger.info("[NutritionCampaign] Não há próximo step. Campanha encerrada.")

        finally:
            redis_client.delete(lock_key)

    except Exception as e:
        logger.error(f"[NutritionCampaign] Erro na task: {str(e)}", exc_info=True)
        try:
            if 'step_obj' in locals() and 'seq' in locals():
                insert_or_update_nutrition_execution(
                    db, contact_id, company_id, seq.id, step_obj.id if step_obj else None,
                    step_number, 'FAILED', error_message=str(e)
                )
        except:
            pass
        raise
    finally:
        db.close()

@app.task
def iniciar_nutrition_campaign_para_contatos(
    company_id: int,
    sequence_id: int = None,
    operational_epoch: Optional[int] = None,
):
    """
    Task para iniciar campanha de nutrição para todos os contatos que atendem aos critérios.
    Pode ser chamada manualmente ou via cron job.
    """
    db = SessionLocal()
    try:
        from backend.services.company_access_control import validate_company_job_epoch
        if not validate_company_job_epoch(db, int(company_id), operational_epoch):
            return
        logger.info(f"[NutritionCampaign] Iniciando varredura de contatos para company_id={company_id}")

        # Buscar sequência ativa
        where_clause = "WHERE company_id = :company_id AND active = true"
        params = {"company_id": company_id}

        if sequence_id:
            where_clause += " AND id = :sequence_id"
            params["sequence_id"] = sequence_id

        sequences = db.execute(
            text(f"""
                SELECT id, name, target_contact_status, target_contact_categories, target_contact_tags,
                       contact_delay_min, contact_delay_max, contact_delay_unit
                FROM nutrition_campaign_sequences
                {where_clause}
            """),
            params
        ).fetchall()

        if not sequences:
            logger.info(f"[NutritionCampaign] Nenhuma sequência ativa encontrada")
            return

        total_disparos = 0

        for seq in sequences:
            logger.info(f"[NutritionCampaign] Processando sequência: {seq.name}")

            # Montar query dinâmica baseada nos critérios
            contact_query = """
                SELECT DISTINCT c.id, c.phone, c.name
                FROM contacts c
                LEFT JOIN clientes p ON p.contact_id = c.id AND p.company_id = c.company_id
                WHERE c.company_id = :company_id
                  AND c.phone IS NOT NULL
                  AND c.phone != ''
            """
            query_params = {"company_id": company_id}

            # Filtrar por status se especificado
            if seq.target_contact_status:
                contact_query += " AND p.status = ANY(:target_status)"
                query_params["target_status"] = seq.target_contact_status

            # Filtrar por categoria se especificado
            if seq.target_contact_categories:
                contact_query += " AND p.categoria = ANY(:target_categories)"
                query_params["target_categories"] = seq.target_contact_categories

            # Filtrar por tags se especificado
            if seq.target_contact_tags:
                contact_query += " AND p.tags && :target_tags"
                query_params["target_tags"] = seq.target_contact_tags

            # Excluir contatos que já estão em execução
            contact_query += """
                AND NOT EXISTS (
                    SELECT 1 FROM nutrition_campaign_executions nce
                    WHERE nce.contact_id = c.id
                      AND nce.nutrition_campaign_sequence_id = :seq_id
                      AND nce.status IN ('SCHEDULED', 'PROCESSING', 'SUCCESS')
                )
            """
            query_params["seq_id"] = seq.id

            contacts = db.execute(text(contact_query), query_params).fetchall()

            logger.info(f"[NutritionCampaign] Encontrados {len(contacts)} contatos elegíveis para sequência {seq.name}")

            # Agendar primeiro step para cada contato com delay entre contatos
            for idx, contact in enumerate(contacts):
                try:
                    # Calcular delay entre contatos (MAIS IMPORTANTE)
                    contact_delay_seconds = get_random_delay(seq.contact_delay_min, seq.contact_delay_max)

                    # Converter para segundos baseado na unidade
                    if seq.contact_delay_unit == 'minutes':
                        contact_delay_seconds *= 60
                    elif seq.contact_delay_unit == 'hours':
                        contact_delay_seconds *= 3600
                    elif seq.contact_delay_unit == 'days':
                        contact_delay_seconds *= 86400

                    # Delay progressivo: cada contato recebe com mais delay que o anterior
                    progressive_delay = idx * contact_delay_seconds
                    eta = datetime.utcnow() + timedelta(seconds=progressive_delay)

                    enviar_passo_nutrition_campaign.apply_async(
                        args=[
                            contact.id,
                            1,
                            company_id,
                            contact.phone,
                            operational_epoch,
                        ],
                        eta=eta
                    )

                    total_disparos += 1
                    delay_formatted = f"{contact_delay_seconds // 60}min" if seq.contact_delay_unit == 'minutes' else f"{contact_delay_seconds // 3600}h" if seq.contact_delay_unit == 'hours' else f"{contact_delay_seconds // 86400}d"
                    logger.info(f"[NutritionCampaign] Contato {idx+1}/{len(contacts)} agendado para {eta} (delay: {delay_formatted})")

                except Exception as e:
                    logger.error(f"[NutritionCampaign] Erro ao agendar para contato {contact.id}: {str(e)}")
                    continue

        logger.info(f"[NutritionCampaign] Campanha iniciada com {total_disparos} disparos agendados")

    except Exception as e:
        logger.error(f"[NutritionCampaign] Erro ao iniciar campanha: {str(e)}", exc_info=True)
        raise
    finally:
        db.close()
