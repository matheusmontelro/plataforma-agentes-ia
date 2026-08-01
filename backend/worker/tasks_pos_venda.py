import logging
import time as pytime
import os
import base64
import json
import redis
import uuid
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
LOG_FILE = os.path.join(LOG_DIR, "pos_venda_tasks.log")

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
    Reutilizado do tasks_noshow.py
    """
    try:
        if file_path.startswith(('http://', 'https://')):
            return file_path

        full_path = os.path.join(MEDIA_BASE_PATH, file_path)
        logger.info(f"[PosVenda] Tentando acessar arquivo em: {full_path}")

        if not os.path.exists(full_path):
            logger.error(f"[PosVenda] Arquivo não encontrado: {full_path}")
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
        logger.error(f"[PosVenda] Erro ao processar arquivo de mídia: {str(e)}", exc_info=True)
        return None

def publish_message_to_redis(msg_type: str, content: str, phone: str, from_me: bool = True):
    """Publica mensagem no Redis para broadcast via WebSocket."""
    try:
        message = {
            "type": msg_type,
            "content": content,
            "phone": phone,
            "senderName": "PosVenda System",
            "photo": "",
            "fromMe": from_me,
            "messageId": f"posvenda_{int(datetime.utcnow().timestamp() * 1000)}",
            "momment": datetime.utcnow().isoformat(),
            "caption": None
        }

        logger.info(f"[PosVenda] Publicando mensagem no Redis: {json.dumps(message)}")
        redis_client.publish('chat_messages', json.dumps(message))
        logger.info("[PosVenda] Mensagem publicada com sucesso no Redis")

    except Exception as e:
        logger.error(f"[PosVenda] Erro ao publicar mensagem no Redis: {str(e)}", exc_info=True)

def adjust_eta_to_schedule(eta_utc: datetime, schedule_data_str: str, tz_name: str = "America/Sao_Paulo") -> datetime:
    """
    Ajusta a data/hora para cair dentro das janelas de envio.
    Reutilizado do tasks_noshow.py
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

def get_last_pos_venda_step(company_id: int, venda_id: int) -> Optional[dict]:
    """
    Recupera informações do último step enviado
    """
    try:
        key = f"posvenda:last_step:{company_id}:{venda_id}"
        data = redis_client.get(key)
        if data:
            info = json.loads(data)
            info["timestamp"] = datetime.fromtimestamp(float(info["timestamp"]))
            return info
        return None
    except Exception as e:
        logger.error(f"[PosVenda] Erro ao obter último step: {str(e)}")
        return None

def set_last_pos_venda_step(company_id: int, venda_id: int, step_number: int, sequence_id: int) -> None:
    """
    Armazena informações do último step enviado
    """
    try:
        key = f"posvenda:last_step:{company_id}:{venda_id}"
        data = {
            "step_number": step_number,
            "timestamp": datetime.utcnow().timestamp(),
            "sequence_id": sequence_id
        }
        redis_client.set(key, json.dumps(data))
        redis_client.expire(key, 60 * 60 * 24 * 30)  # 30 dias
    except Exception as e:
        logger.error(f"[PosVenda] Erro ao salvar último step: {str(e)}")

def clear_pos_venda_steps(company_id: int, venda_id: int) -> None:
    """Limpa o registro de steps para uma venda no Redis."""
    try:
        key = f"posvenda:last_step:{company_id}:{venda_id}"
        redis_client.delete(key)
        logger.info(f"[PosVenda] Limpou steps do Redis para venda={venda_id}")
    except Exception as e:
        logger.error(f"[PosVenda] Erro ao limpar steps: {str(e)}")

def cancel_pending_pos_venda_executions(db: Session, venda_id: int, reason: str = "Venda recriada") -> None:
    """Cancela execuções pendentes para uma venda."""
    try:
        db.execute(
            text("""
                UPDATE pos_venda_executions
                SET status = 'CANCELED',
                    error_message = :reason,
                    updated_at = NOW()
                WHERE venda_id = :venda_id
                  AND status IN ('SCHEDULED', 'PROCESSING')
            """),
            {"venda_id": venda_id, "reason": reason}
        )
        db.commit()
        logger.info(f"[PosVenda] Cancelou execuções pendentes para venda={venda_id}")
    except Exception as e:
        logger.error(f"[PosVenda] Erro ao cancelar execuções: {str(e)}")

def insert_or_update_pos_venda_execution(db: Session,
                                       venda_id: int,
                                       lead_id: int,
                                       company_id: int,
                                       sequence_id: int,
                                       step_id: int,
                                       step_number: int,
                                       status: str,
                                       scheduled_for: Optional[datetime] = None,
                                       error_message: Optional[str] = None):
    """
    Insere ou atualiza a execução do follow-up pós-venda
    """
    try:
        db.execute(
            text("""
                INSERT INTO pos_venda_executions (
                    venda_id, lead_id, company_id, pos_venda_sequence_id,
                    pos_venda_step_id, step_number, status, scheduled_for, error_message
                )
                VALUES (
                    :venda_id, :lead_id, :company_id, :sequence_id, :step_id, :step_number,
                    :status, :scheduled_for, :error_message
                )
                ON CONFLICT (venda_id, pos_venda_sequence_id, pos_venda_step_id)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    scheduled_for = EXCLUDED.scheduled_for,
                    error_message = EXCLUDED.error_message,
                    updated_at = now()
            """),
            {
                "venda_id": venda_id,
                "lead_id": lead_id,
                "company_id": company_id,
                "sequence_id": sequence_id,
                "step_id": step_id,
                "step_number": step_number,
                "status": status,
                "scheduled_for": scheduled_for,
                "error_message": error_message
            }
        )
        db.commit()
    except Exception as e:
        logger.error(f"[PosVenda] Erro ao inserir/atualizar execução: {str(e)}")

@app.task
@check_flow_control('pos_venda')
def enviar_passo_pos_venda(venda_id: int, step_number: int,
                          company_id: int, lead_id: int, phone: str):
    """
    Task para enviar follow-up após venda
    Objetivo: fidelizar cliente e obter feedback através de mensagens automatizadas
    """
    db = SessionLocal()
    try:
        from backend.services.company_access_control import is_company_operational
        if not is_company_operational(db, int(company_id)):
            db.execute(
                text("""
                    UPDATE pos_venda_executions
                       SET status = 'CANCELED',
                           error_message = 'company_access_suspended',
                           updated_at = now()
                     WHERE venda_id = :venda_id
                       AND company_id = :company_id
                       AND status IN ('SCHEDULED', 'PROCESSING')
                """),
                {"venda_id": venda_id, "company_id": company_id},
            )
            db.commit()
            return
        logger.info(f"[PosVenda] Iniciando step={step_number} para venda={venda_id}")

        # Lock para evitar duplicação
        lock_key = f"lock:pos_venda:{venda_id}:{step_number}"
        lock_value = str(uuid.uuid4())

        if not redis_client.set(lock_key, lock_value, ex=30, nx=True):
            logger.info(f"[PosVenda] Task já em processamento")
            return

        # Proteção contra loop infinito de reagendamento
        reagenda_key = f"reagenda:pos_venda:{venda_id}:{step_number}"
        reagenda_count = redis_client.get(reagenda_key)

        if reagenda_count and int(reagenda_count) >= 3:
            logger.warning(f"[PosVenda] Task reagendada {reagenda_count} vezes. Evitando loop infinito.")
            # Marcar como falha para evitar reagendamento contínuo
            insert_or_update_pos_venda_execution(
                db,
                venda_id=venda_id,
                lead_id=lead_id,
                company_id=company_id,
                sequence_id=0,  # Temporário
                step_id=0,      # Temporário
                step_number=step_number,
                status='FAILED',
                error_message='Excesso de reagendamentos - possível loop infinito'
            )
            return

        try:
            # Verificar se já foi executado
            existing = db.execute(
                text("""
                    SELECT id, status FROM pos_venda_executions
                    WHERE venda_id = :venda_id
                      AND step_number = :step_num
                      AND status IN ('SUCCESS', 'PROCESSING', 'CANCELED')
                    LIMIT 1
                """),
                {"venda_id": venda_id, "step_num": step_number}
            ).fetchone()

            if existing:
                logger.info(f"[PosVenda] Step já executado com status={existing.status}")
                return

            # Buscar sequência configurada
            seq = db.execute(
                text("""
                    SELECT id, name FROM pos_venda_sequences
                    WHERE company_id = :company_id AND active = true
                    LIMIT 1
                """),
                {"company_id": company_id}
            ).fetchone()

            if not seq:
                logger.warning(f"[PosVenda] Nenhuma sequência ativa para company_id={company_id}")
                return

            # Verificar último step no Redis
            last_step = get_last_pos_venda_step(company_id, venda_id)
            if last_step and last_step["step_number"] and last_step["step_number"] >= step_number:
                logger.info(f"[PosVenda] Step {step_number} já foi enviado. Último={last_step['step_number']}")
                return

            # Buscar step atual
            step_obj = db.execute(
                text("""
                    SELECT id, send_after, send_after_unit
                    FROM pos_venda_steps
                    WHERE pos_venda_sequence_id = :seq_id
                      AND step_number = :step_num
                    LIMIT 1
                """),
                {"seq_id": seq.id, "step_num": step_number}
            ).fetchone()

            if not step_obj:
                logger.info(f"[PosVenda] Step {step_number} não encontrado para sequência {seq.id}")
                return

            # Se for o primeiro passo, verificar janela de envio
            if step_number == 1:
                schedule_conf = db.execute(
                    text("""
                        SELECT schedule_data FROM pos_venda_schedule_configs
                        WHERE company_id = :company_id
                          AND pos_venda_sequence_id = :seq_id
                        LIMIT 1
                    """),
                    {"company_id": company_id, "seq_id": seq.id}
                ).fetchone()

                if schedule_conf and schedule_conf.schedule_data:
                    logger.info("[PosVenda] Verificando janela de envio...")
                    now_utc = datetime.utcnow().replace(tzinfo=pytz.UTC)
                    now_adjusted = adjust_eta_to_schedule(now_utc, schedule_conf.schedule_data, "America/Sao_Paulo")

                    if now_adjusted > now_utc:
                        # Incrementar contador de reagendamentos
                        current_count = int(reagenda_count) if reagenda_count else 0
                        redis_client.set(reagenda_key, current_count + 1, ex=86400)  # 24h TTL

                        logger.info(f"[PosVenda] Fora do horário. Reagendando para {now_adjusted} (tentativa {current_count + 1})")
                        insert_or_update_pos_venda_execution(
                            db,
                            venda_id=venda_id,
                            lead_id=lead_id,
                            company_id=company_id,
                            sequence_id=seq.id,
                            step_id=step_obj.id,
                            step_number=step_number,
                            status='SCHEDULED',
                            scheduled_for=now_adjusted
                        )
                        enviar_passo_pos_venda.apply_async(
                            args=[venda_id, step_number, company_id, lead_id, phone],
                            eta=now_adjusted
                        )
                        return

            # Marcar como PROCESSING
            insert_or_update_pos_venda_execution(
                db,
                venda_id=venda_id,
                lead_id=lead_id,
                company_id=company_id,
                sequence_id=seq.id,
                step_id=step_obj.id,
                step_number=step_number,
                status='PROCESSING'
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
                logger.error(f"[PosVenda] Empresa {company_id} sem configuração Z-API")
                insert_or_update_pos_venda_execution(
                    db,
                    venda_id=venda_id,
                    lead_id=lead_id,
                    company_id=company_id,
                    sequence_id=seq.id,
                    step_id=step_obj.id,
                    step_number=step_number,
                    status='FAILED',
                    error_message='Sem configuração Z-API'
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
                    FROM pos_venda_messages
                    WHERE pos_venda_step_id = :step_id
                    ORDER BY id
                """),
                {"step_id": step_obj.id}
            ).fetchall()

            logger.info(f"[PosVenda] Encontradas {len(messages)} mensagens para enviar")

            mensagens_enviadas = False
            envio_com_erro = False
            error_msg = None

            for msg in messages:
                try:
                    logger.info(f"[PosVenda] Processando mensagem: id={msg.id}, tipo={msg.type}")

                    if msg.type == "text":
                        response = send_text_to_zapi(
                            instance_id=instance_id,
                            instance_token=instance_token,
                            phone=phone,
                            message=msg.content,
                            company_id=company_id,
                            human_mode=False
                        )
                        logger.info(f"[PosVenda] Resposta envio texto: {response}")
                        publish_message_to_redis("text", msg.content, phone)
                        mensagens_enviadas = True

                        # Persistir no banco
                        try:
                            client_id_result = db.execute(
                                text("SELECT client_id FROM leads WHERE id = :lead_id"),
                                {"lead_id": lead_id}
                            ).fetchone()

                            parsed_client_id = None
                            if client_id_result and client_id_result.client_id is not None:
                                if str(client_id_result.client_id).isdigit():
                                    parsed_client_id = int(client_id_result.client_id)

                            new_message = Message(
                                client_id=parsed_client_id,
                                company_id=company_id,
                                contact_phone=phone,
                                message_type="text",
                                content=msg.content,
                                sender_phone="PosVendaFlow",
                                sender_name="PosVenda System",
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
                            logger.error(f"[PosVenda] Erro ao salvar mensagem: {str(e)}")

                    elif msg.type in ["image", "video", "audio"]:
                        media_content = get_media_content(msg.content, msg.type)

                        if not media_content:
                            logger.error(f"[PosVenda] Falha ao processar mídia: {msg.content}")
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
                        nps_question = msg.content if msg.content.strip() else "Em uma escala de 1 a 5, como você avalia nosso atendimento?"

                        # Usar a rota NPS existente em vez de duplicar lógica
                        try:
                            from backend.routes.nps_routes import send_nps_internal

                            response = send_nps_internal(
                                phone=phone,
                                question=nps_question,
                                campaign_name="pos_venda_followup",
                                context="pos_venda",
                                company_id=company_id,
                                db=db
                            )
                            logger.info(f"[PosVenda] Resposta envio NPS: {response}")

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
                            logger.error(f"[PosVenda] Erro ao enviar NPS via rota: {str(e)}")
                            envio_com_erro = True
                            error_msg = str(e)

                    pytime.sleep(1)  # Delay entre mensagens

                except Exception as e:
                    logger.error(f"[PosVenda] Erro ao processar mensagem: {str(e)}", exc_info=True)
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
            insert_or_update_pos_venda_execution(
                db,
                venda_id=venda_id,
                lead_id=lead_id,
                company_id=company_id,
                sequence_id=seq.id,
                step_id=step_obj.id,
                step_number=step_number,
                status=final_status,
                error_message=error_msg
            )

            if final_status == 'FAILED':
                logger.error(f"[PosVenda] Falha no envio. Encerrando sem agendar próximo.")
                return

            # Registrar no Redis
            set_last_pos_venda_step(company_id, venda_id, step_number, seq.id)

            # Limpar contador de reagendamentos (task executada com sucesso)
            redis_client.delete(reagenda_key)

            # Verificar e agendar próximo step
            next_step = db.execute(
                text("""
                    SELECT id, step_number, send_after, send_after_unit
                    FROM pos_venda_steps
                    WHERE pos_venda_sequence_id = :seq_id
                      AND step_number = :next_step_num
                    LIMIT 1
                """),
                {"seq_id": seq.id, "next_step_num": step_number + 1}
            ).fetchone()

            if next_step:
                # Calcular ETA
                unit = next_step.send_after_unit
                delta = {}
                if unit == "days":
                    delta["days"] = next_step.send_after
                elif unit == "hours":
                    delta["hours"] = next_step.send_after
                elif unit == "minutes":
                    delta["minutes"] = next_step.send_after

                eta = datetime.utcnow() + timedelta(**delta)

                # Ajustar por schedule se existir
                schedule_conf = db.execute(
                    text("""
                        SELECT schedule_data FROM pos_venda_schedule_configs
                        WHERE company_id = :company_id
                          AND pos_venda_sequence_id = :seq_id
                        LIMIT 1
                    """),
                    {"company_id": company_id, "seq_id": seq.id}
                ).fetchone()

                if schedule_conf and schedule_conf.schedule_data:
                    eta_original = eta
                    eta = adjust_eta_to_schedule(eta, schedule_conf.schedule_data, "America/Sao_Paulo")
                    logger.info(f"[PosVenda] Horário ajustado de {eta_original} para {eta}")

                # Registrar agendamento
                insert_or_update_pos_venda_execution(
                    db,
                    venda_id=venda_id,
                    lead_id=lead_id,
                    company_id=company_id,
                    sequence_id=seq.id,
                    step_id=next_step.id,
                    step_number=next_step.step_number,
                    status='SCHEDULED',
                    scheduled_for=eta
                )

                # Agendar próximo
                enviar_passo_pos_venda.apply_async(
                    args=[venda_id, next_step.step_number, company_id, lead_id, phone],
                    eta=eta
                )
                logger.info(f"[PosVenda] Próximo step={next_step.step_number} agendado para {eta}")
            else:
                logger.info("[PosVenda] Não há próximo step. Fluxo encerrado.")

        finally:
            redis_client.delete(lock_key)

    except Exception as e:
        logger.error(f"[PosVenda] Erro na task: {str(e)}", exc_info=True)
        try:
            if 'step_obj' in locals() and 'seq' in locals():
                insert_or_update_pos_venda_execution(
                    db,
                    venda_id=venda_id,
                    lead_id=lead_id,
                    company_id=company_id,
                    sequence_id=seq.id if seq else None,
                    step_id=step_obj.id if step_obj else None,
                    step_number=step_number,
                    status='FAILED',
                    error_message=str(e)
                )
        except:
            pass
        raise
    finally:
        db.close()
