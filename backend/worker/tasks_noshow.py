import logging
import time as pytime
import os
import base64
import json
import redis
from datetime import datetime, timedelta, time as dt_time
from .celery_app import app
from sqlalchemy import text
from sqlalchemy.orm import Session
from pytz import timezone, UTC
from dotenv import load_dotenv
from typing import Optional
from fastapi import HTTPException
import pytz
import uuid
from backend.db import SessionLocal
from backend.runtime_settings import (
    GOOGLE_VISION_CREDENTIALS,
    LOG_DIR as RUNTIME_LOG_DIR,
    MEDIA_BASE_PATH as RUNTIME_MEDIA_BASE_PATH,
)
from .flow_control import check_flow_control
from backend.models import (
    NoShowFollowUpSequence,
    NoShowFollowUpStep,
    NoShowFollowUpMessage,
    NoShowFollowUpScheduleConfig,
    Message
)

# >>> IMPORTS EXISTENTES (NÃO ALTERAR)

load_dotenv()
CLIENT_TOKEN = os.getenv("CLIENT_TOKEN")
MEDIA_BASE_PATH = str(RUNTIME_MEDIA_BASE_PATH)

# ----------------------------------------------------------------------------
# >>> NOVA CONFIGURAÇÃO DE LOG PARA ARQUIVO noshow_tasks.log <<<
# ----------------------------------------------------------------------------

LOG_DIR = str(RUNTIME_LOG_DIR)
os.makedirs(LOG_DIR, exist_ok=True)  # Garante que o diretório exista
LOG_FILE = os.path.join(LOG_DIR, "noshow_tasks.log")

logger = logging.getLogger(__name__)
file_handler = logging.FileHandler(LOG_FILE)
file_formatter = logging.Formatter(
    '%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s'
)
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)
logger.setLevel(logging.INFO)

# ----------------------------------------------------------------------------

# Conexão Redis
redis_client = redis.Redis(host='localhost', port=6379, db=0)

# >>> NOVOS IMPORTS (apenas o necessário para transcrição/análise e gravação no .txt)
import speech_recognition as sr
from pydub import AudioSegment
from google.cloud import vision
from google.oauth2 import service_account
from backend.prompt.memory import memory_manager

# ------------------------------------------------
#  >>> NOVAS FUNÇÕES (somente o necessário) <<<
# ------------------------------------------------

def transcribe_audio_local(file_path: str) -> str:
    """
    Versão local para transcrever arquivo de áudio (p. ex. .mp3) usando SpeechRecognition.
    """
    try:
        audio = AudioSegment.from_file(file_path)
        temp_wav = "temp_audio_noshow.wav"
        audio.export(temp_wav, format="wav")

        recognizer = sr.Recognizer()
        with sr.AudioFile(temp_wav) as source:
            audio_content = recognizer.record(source)
            transcription = recognizer.recognize_google(audio_content, language="pt-BR")
        return transcription
    except Exception as e:
        logger.error(f"[NoShow] Erro ao transcrever áudio local: {str(e)}", exc_info=True)
        return ""

def transcribe_video_local(file_path: str) -> str:
    """
    Versão local para transcrever arquivo de vídeo (p. ex. .mp4) extraindo áudio e usando SpeechRecognition.
    """
    try:
        video_audio = AudioSegment.from_file(file_path, format="mp4")
        temp_video_audio = "temp_video_audio_noshow.wav"
        video_audio.export(temp_video_audio, format="wav")

        recognizer = sr.Recognizer()
        with sr.AudioFile(temp_video_audio) as source:
            audio_content = recognizer.record(source)
            transcription = recognizer.recognize_google(audio_content, language="pt-BR")
        return transcription
    except Exception as e:
        logger.error(f"[NoShow] Erro ao transcrever vídeo local: {str(e)}", exc_info=True)
        return ""

def analyze_image_local(file_path: str) -> str:
    """
    Versão local para análise de imagem via Google Vision, lendo arquivo de disco.
    """
    try:
        with open(file_path, "rb") as f:
            image_content = f.read()

        creds_path = str(GOOGLE_VISION_CREDENTIALS)
        credentials = service_account.Credentials.from_service_account_file(creds_path)
        client = vision.ImageAnnotatorClient(credentials=credentials)

        image = vision.Image(content=image_content)
        response = client.label_detection(image=image)
        labels = response.label_annotations
        if not labels:
            return "Nenhum rótulo encontrado na imagem."

        label_names = [label.description for label in labels]
        return "Itens detectados na imagem: " + ", ".join(label_names)
    except Exception as e:
        logger.error(f"[NoShow] Erro ao analisar imagem local com Google Vision: {str(e)}", exc_info=True)
        return "Falha ao analisar imagem no Google Vision."

# ------------------------------------------------
#    >>> CÓDIGO ORIGINAL (APENAS AJUSTES) <<<
# ------------------------------------------------

def get_last_step_time(company_id: int, lead_id: int) -> Optional[datetime]:
    """Recupera o timestamp do último step enviado (compatível com formato antigo)."""
    try:
        key = f"noshow:last_step:{company_id}:{lead_id}"
        timestamp = redis_client.get(key)
        if timestamp:
            return datetime.fromtimestamp(float(timestamp))
        return None
    except Exception as e:
        logger.error(f"[NoShow] Erro ao obter último step: {str(e)}")
        return None

def set_last_step_time(company_id: int, lead_id: int, step_time: datetime) -> None:
    """Armazena o timestamp do último step enviado."""
    try:
        key = f"noshow:last_step:{company_id}:{lead_id}"
        redis_client.set(key, step_time.timestamp())
    except Exception as e:
        logger.error(f"[NoShow] Erro ao salvar último step: {str(e)}")

def publish_message_to_redis(msg_type: str, content: str, phone: str, from_me: bool = True):
    """Publica mensagem no Redis para broadcast via WebSocket."""
    try:
        message = {
            "type": msg_type,
            "content": content,
            "phone": phone,
            "senderName": "NoShow System",
            "photo": "",
            "fromMe": from_me,
            "messageId": f"noshow_{int(datetime.utcnow().timestamp() * 1000)}",
            "momment": datetime.utcnow().isoformat(),
            "caption": None
        }

        logger.info(f"[NoShow] Publicando mensagem no Redis: {json.dumps(message)}")
        redis_client.publish('chat_messages', json.dumps(message))
        logger.info("[NoShow] Mensagem publicada com sucesso no Redis")

    except Exception as e:
        logger.error(f"[NoShow] Erro ao publicar mensagem no Redis: {str(e)}", exc_info=True)

def get_media_content(file_path: str, media_type: str) -> Optional[str]:
    """
    Converte arquivo de mídia em base64 ou retorna URL completa.
    Args:
        file_path: Caminho relativo (ex: client_6/company_1/video/file.mp4)
        media_type: Tipo de mídia (image, video, audio)
    """
    try:
        if file_path.startswith(('http://', 'https://')):
            return file_path

        full_path = os.path.join(MEDIA_BASE_PATH, file_path)
        logger.info(f"[NoShow] Tentando acessar arquivo em: {full_path}")

        if not os.path.exists(full_path):
            logger.error(f"[NoShow] Arquivo não encontrado: {full_path}")
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
        logger.error(f"[NoShow] Erro ao processar arquivo de mídia: {str(e)}", exc_info=True)
        return None

def adjust_eta_to_schedule(eta_utc: datetime, schedule_data_str: str, tz_name: str = "America/Sao_Paulo") -> datetime:
    """
    Ajusta a data/hora 'eta_utc' (que está em UTC) para cair dentro das janelas
    de envio definidas em 'schedule_data_str' (JSON), considerando o fuso horário tz_name.
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
        end_str   = day_config.get("end")
        if not start_str or not end_str:
            dt_local += timedelta(days=1)
            dt_local = dt_local.replace(hour=0, minute=0, second=0, microsecond=0)
            continue

        sh, sm = map(int, start_str.split(":"))
        eh, em = map(int, end_str.split(":"))
        start_time = dt_time(sh, sm)
        end_time   = dt_time(eh, em)

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

def get_last_noshow_step(company_id: int, lead_id: int) -> Optional[dict]:
    """
    Recupera informações do último step de no-show enviado
    Retorna dict com: {
        "step_number": int,
        "timestamp": datetime,
        "sequence_id": int
    } ou None se não houver registro
    """
    try:
        key = f"noshow:last_step:{company_id}:{lead_id}"
        data = redis_client.get(key)
        if data:
            try:
                info = json.loads(data)
                info["timestamp"] = datetime.fromtimestamp(float(info["timestamp"]))
                return info
            except json.JSONDecodeError:
                # Compatibilidade com formato antigo (apenas timestamp)
                timestamp = float(data)
                return {
                    "step_number": None,
                    "timestamp": datetime.fromtimestamp(timestamp),
                    "sequence_id": None
                }
        return None
    except Exception as e:
        logger.error(f"[NoShow] Erro ao obter último step: {str(e)}")
        return None

def set_last_noshow_step(company_id: int, lead_id: int, step_number: int, sequence_id: int) -> None:
    """
    Armazena informações do último step de no-show enviado
    """
    try:
        key = f"noshow:last_step:{company_id}:{lead_id}"
        data = {
            "step_number": step_number,
            "timestamp": datetime.utcnow().timestamp(),
            "sequence_id": sequence_id
        }
        redis_client.set(key, json.dumps(data))
        redis_client.expire(key, 60 * 60 * 24 * 30)  # 30 dias
    except Exception as e:
        logger.error(f"[NoShow] Erro ao salvar último step: {str(e)}")

def clear_noshow_steps(company_id: int, lead_id: int) -> None:
    """Limpa o registro de steps para um lead no Redis e cancela tasks Celery pendentes."""
    try:
        # Limpar Redis
        key = f"noshow:last_step:{company_id}:{lead_id}"
        redis_client.delete(key)

        # Cancelar tasks Celery pendentes para este lead
        try:
            # Buscar tasks ativas/agendadas no Celery para este lead
            active_tasks = app.control.inspect().active()
            scheduled_tasks = app.control.inspect().scheduled()

            tasks_to_revoke = []

            # Verificar tasks ativas
            if active_tasks:
                for worker, task_list in active_tasks.items():
                    for task in task_list:
                        if 'enviar_passo_noshow' in task.get('name', ''):
                            # Verificar se é para este lead (primeiro argumento)
                            args = task.get('args', [])
                            if args and len(args) > 0 and args[0] == lead_id:
                                tasks_to_revoke.append(task['id'])

            # Verificar tasks agendadas
            if scheduled_tasks:
                for worker, task_dict in scheduled_tasks.items():
                    for task in task_dict.values():
                        for scheduled_task in task:
                            if 'enviar_passo_noshow' in scheduled_task.get('name', ''):
                                args = scheduled_task.get('args', [])
                                if args and len(args) > 0 and args[0] == lead_id:
                                    tasks_to_revoke.append(scheduled_task['id'])

            # Cancelar todas as tasks encontradas
            if tasks_to_revoke:
                for task_id in tasks_to_revoke:
                    app.control.revoke(task_id, terminate=True)
                    logger.info(f"[NoShow] Task Celery cancelada: {task_id} para lead {lead_id}")
                logger.info(f"[NoShow] Canceladas {len(tasks_to_revoke)} tasks Celery para lead {lead_id}")
            else:
                logger.info(f"[NoShow] Nenhuma task Celery encontrada para cancelar (lead {lead_id})")

        except Exception as celery_error:
            logger.error(f"[NoShow] Erro ao cancelar tasks Celery para lead {lead_id}: {str(celery_error)}")

    except Exception as e:
        logger.error(f"[NoShow] Erro ao limpar steps: {str(e)}")


# >>> NOVO: Funções utilitárias para a tabela noshow_follow_up_executions
def insert_or_update_noshow_execution(db: Session,
                                      lead_id: int,
                                      company_id: int,
                                      sequence_id: int,
                                      step_id: int,
                                      step_number: int,
                                      status: str,
                                      scheduled_for: Optional[datetime] = None,
                                      error_message: Optional[str] = None):
    """
    Insere ou atualiza a execução do no-show follow-up na tabela noshow_follow_up_executions.
    """
    try:
        db.execute(
            text("""
                INSERT INTO noshow_follow_up_executions (
                    lead_id, company_id, noshow_follow_up_sequence_id,
                    noshow_follow_up_step_id, step_number, status, scheduled_for, error_message
                )
                VALUES (
                    :lead_id, :company_id, :sequence_id, :step_id, :step_number,
                    :status, :scheduled_for, :error_message
                )
                ON CONFLICT (lead_id, noshow_follow_up_sequence_id, noshow_follow_up_step_id)
                DO UPDATE SET
                    status        = EXCLUDED.status,
                    scheduled_for = EXCLUDED.scheduled_for,
                    error_message = EXCLUDED.error_message,
                    updated_at    = now()
            """),
            {
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
        logger.error(f"[NoShow] Erro ao inserir/atualizar noshow_follow_up_executions: {str(e)}")


def get_noshow_execution_success(db: Session, lead_id: int, step_number: int) -> bool:
    """
    Verifica se já existe um registro com status='SUCCESS' para esse lead e step_number
    """
    try:
        row = db.execute(
            text("""
                SELECT id
                FROM noshow_follow_up_executions
                WHERE lead_id = :lead_id
                  AND step_number = :step_number
                  AND status = 'SUCCESS'
                LIMIT 1
            """),
            {"lead_id": lead_id, "step_number": step_number}
        ).fetchone()
        return row is not None
    except Exception as e:
        logger.error(f"[NoShow] Erro ao buscar noshow_follow_up_executions SUCCESS: {str(e)}")
        return False


@app.task
@check_flow_control('noshow')
def enviar_passo_noshow(
    lead_id: int,
    step_number: int,
    company_id: int,
    phone: str,
    operational_epoch: Optional[int] = None,
):
    """Task que envia mensagens de no-show e agenda próximos passos,
       agora registrando execuções em noshow_follow_up_executions.
    """
    db = SessionLocal()
    try:
        from backend.services.company_access_control import validate_company_job_epoch
        if not validate_company_job_epoch(db, int(company_id), operational_epoch):
            db.execute(
                text("""
                    UPDATE noshow_follow_up_executions
                       SET status = 'CANCELED',
                           error_message = 'company_access_suspended',
                           updated_at = now()
                     WHERE lead_id = :lead_id
                       AND company_id = :company_id
                       AND status IN ('SCHEDULED', 'PROCESSING')
                """),
                {"lead_id": lead_id, "company_id": company_id},
            )
            db.commit()
            return
        logger.info(f"[NoShow] Disparando passo={step_number} para lead_id={lead_id}, company_id={company_id}")

        # Verificação mais robusta para evitar duplicações
        # 1. Verificar se já existe uma execução em PROCESSING ou SUCCESS
        existing_execution = db.execute(
            text("""
                SELECT id, status
                FROM noshow_follow_up_executions
                WHERE lead_id = :lead_id
                  AND step_number = :step_number
                  AND company_id = :company_id
                  AND status IN ('PROCESSING', 'SUCCESS', 'CANCELED')
                LIMIT 1
            """),
            {"lead_id": lead_id, "step_number": step_number, "company_id": company_id}
        ).fetchone()

        if existing_execution:
            logger.info(f"[NoShow] Já existe execução com status '{existing_execution.status}' para lead={lead_id}, step={step_number}. Evitando duplicação.")
            return

        # >>> NOVO: Verificar se este step já foi marcado como SUCCESS na tabela
        if get_noshow_execution_success(db, lead_id, step_number):
            logger.info(f"[NoShow] Step {step_number} já consta como 'SUCCESS' em noshow_follow_up_executions.")
            return

        # Verificar último step em Redis
        last_step = get_last_noshow_step(company_id, lead_id)
        if last_step and last_step["step_number"] and last_step["step_number"] >= step_number:
            logger.info(f"[NoShow] Step {step_number} já foi enviado anteriormente. Último={last_step['step_number']}")
            return

        # 1) Verificar se existe sequência configurada
        seq = db.query(NoShowFollowUpSequence).filter_by(company_id=company_id).first()
        if not seq:
            logger.warning(f"[NoShow] Nenhuma sequência de no-show configurada para company_id={company_id}")
            return

        # NOVO: Verificar mudança de sequência no Redis
        if last_step and last_step["sequence_id"] and last_step["sequence_id"] != seq.id:
            logger.info("[NoShow] Sequência mudou. Limpando histórico de steps.")
            clear_noshow_steps(company_id, lead_id)

        # (NOVO) Verificar status do agendamento ainda é NO_SHOW
        agendamento_status = db.execute(
            text("""
                SELECT status
                FROM agendamentos
                WHERE company_id = :company_id
                  AND lead_id = :lead_id
                ORDER BY id DESC
                LIMIT 1
            """),
            {"company_id": company_id, "lead_id": lead_id}
        ).fetchone()

        if agendamento_status:
            if agendamento_status.status != "NO_SHOW":
                logger.info(f"[NoShow] Status='{agendamento_status.status}' != 'NO_SHOW'. Encerrando fluxo.")
                return
        else:
            logger.info("[NoShow] Nenhum agendamento encontrado. Encerrando fluxo.")
            return

        # >>> NOVO: Buscar step atual para inserir SCHEDULED se for reagendado
        step_obj = db.query(NoShowFollowUpStep).filter(
            NoShowFollowUpStep.noshow_follow_up_sequence_id == seq.id,
            NoShowFollowUpStep.step_number == step_number
        ).first()
        if not step_obj:
            logger.info(f"[NoShow] Step={step_number} não encontrado para seq_id={seq.id}. Encerrando.")
            return

        # IMPORTANTE: Adquirir lock no Redis para evitar processamento concorrente
        lock_key = f"lock:noshow:{company_id}:{lead_id}:{step_number}"
        lock_value = str(uuid.uuid4())  # Valor único para identificar o lock

        # Tenta adquirir lock por 10 segundos
        lock_acquired = redis_client.set(lock_key, lock_value, ex=10, nx=True)
        if not lock_acquired:
            logger.info(f"[NoShow] Outra task já está processando este step. Lock ativo para lead={lead_id}, step={step_number}")
            return

        try:
            # Se for o passo 1, checar a janela ANTES de enviar mensagens:
            if step_number == 1:
                schedule_conf_check = db.query(NoShowFollowUpScheduleConfig).filter_by(
                    company_id=company_id,
                    noshow_follow_up_sequence_id=seq.id
                ).first()
                if schedule_conf_check and schedule_conf_check.schedule_data:
                    logger.info("[NoShow] Verificando janela de envio (antes do passo 1)...")
                    now_utc = datetime.utcnow().replace(tzinfo=pytz.UTC)
                    now_adjusted = adjust_eta_to_schedule(now_utc, schedule_conf_check.schedule_data, "America/Sao_Paulo")

                    if now_adjusted > now_utc:
                        logger.info(f"[NoShow] Passo 1 fora do horário. Reagendando para {now_adjusted}")
                        # >>> NOVO: registra SCHEDULED
                        insert_or_update_noshow_execution(
                            db,
                            lead_id=lead_id,
                            company_id=company_id,
                            sequence_id=seq.id,
                            step_id=step_obj.id,
                            step_number=step_number,
                            status='SCHEDULED',
                            scheduled_for=now_adjusted
                        )
                        db.close()
                        # Reagendar a task para o horário correto
                        enviar_passo_noshow.apply_async(
                            args=[
                                lead_id,
                                step_number,
                                company_id,
                                phone,
                                operational_epoch,
                            ],
                            eta=now_adjusted
                        )
                        return

            # 2) Se não for o primeiro passo, verificar tempo de espera
            if step_number > 1:
                if last_step and last_step["timestamp"]:
                    previous_step = db.query(NoShowFollowUpStep).filter(
                        NoShowFollowUpStep.noshow_follow_up_sequence_id == seq.id,
                        NoShowFollowUpStep.step_number == step_number - 1
                    ).first()

                    if previous_step:
                        unit = previous_step.send_after_unit
                        delta = {}
                        if unit == "days":
                            delta["days"] = previous_step.send_after
                        elif unit == "hours":
                            delta["hours"] = previous_step.send_after
                        elif unit == "minutes":
                            delta["minutes"] = previous_step.send_after

                        next_allowed_time = last_step["timestamp"] + timedelta(**delta)
                        utc_now = datetime.utcnow()

                        if utc_now < next_allowed_time:
                            logger.info(f"[NoShow] Ainda não é hora de executar o passo {step_number}. Reagendando p/ {next_allowed_time}")
                            # >>> NOVO: registra SCHEDULED
                            insert_or_update_noshow_execution(
                                db,
                                lead_id=lead_id,
                                company_id=company_id,
                                sequence_id=seq.id,
                                step_id=step_obj.id,
                                step_number=step_number,
                                status='SCHEDULED',
                                scheduled_for=next_allowed_time
                            )
                            db.close()
                            enviar_passo_noshow.apply_async(
                                args=[
                                    lead_id,
                                    step_number,
                                    company_id,
                                    phone,
                                    operational_epoch,
                                ],
                                eta=next_allowed_time
                            )
                            return

            # >>> NOVO: Se chegamos até aqui, vamos marcar PROCESSING
            insert_or_update_noshow_execution(
                db,
                lead_id=lead_id,
                company_id=company_id,
                sequence_id=seq.id,
                step_id=step_obj.id,
                step_number=step_number,
                status='PROCESSING',
                scheduled_for=None
            )

            # 4) Carregar config do schedule
            schedule_conf = db.query(NoShowFollowUpScheduleConfig).filter_by(
                company_id=company_id,
                noshow_follow_up_sequence_id=seq.id
            ).first()

            # 5) Obter dados da empresa para Z-API
            company_data = db.execute(
                text("""
                    SELECT zapi_instance_id, zapi_token
                    FROM companies
                    WHERE id = :company_id
                """),
                {"company_id": company_id}
            ).fetchone()

            if not company_data or not company_data.zapi_instance_id or not company_data.zapi_token:
                logger.error(f"[NoShow] Empresa {company_id} sem configuração Z-API")
                # >>> NOVO: marcar FAILED
                insert_or_update_noshow_execution(
                    db,
                    lead_id=lead_id,
                    company_id=company_id,
                    sequence_id=seq.id,
                    step_id=step_obj.id,
                    step_number=step_number,
                    status='FAILED',
                    error_message='Sem zapi_instance_id/token'
                )
                return

            instance_id = company_data.zapi_instance_id
            instance_token = company_data.zapi_token

            # 6) Import interno para evitar loop de imports
            from backend.routes.webhook import (
                send_text_to_zapi,
                send_image_to_zapi,
                send_audio_to_zapi,
                send_video_to_zapi,
                WhatsAppSendImageBody,
                WhatsAppSendAudioBody,
                WhatsAppSendVideoBody
            )
            from backend.integrations.zapi_utils import send_call, SendCallRequest

            # 7) Buscar mensagens do step atual
            messages = db.query(NoShowFollowUpMessage).filter_by(
                noshow_follow_up_step_id=step_obj.id
            ).order_by(NoShowFollowUpMessage.id.asc()).all()

            logger.info(f"[NoShow] Encontradas {len(messages)} mensagens para enviar")

            mensagens_enviadas = False
            envio_com_erro = False
            error_msg = None

            for msg in messages:
                try:
                    logger.info(f"[NoShow] Processando mensagem: id={msg.id}, tipo={msg.type}")
                    logger.info(f"[NoShow] Dados envio: instance={instance_id}, phone={phone}")

                    if msg.type == "text":
                        response = send_text_to_zapi(
                            instance_id=instance_id,
                            instance_token=instance_token,
                            phone=phone,
                            message=msg.content,
                            company_id=company_id,
                            human_mode=False
                        )
                        logger.info(f"[NoShow] Resposta envio texto: {response}")
                        publish_message_to_redis("text", msg.content, phone)
                        mensagens_enviadas = True

                        # Persistir no DB (mensagem de texto)
                        try:
                            client_id_result = db.execute(
                                text("SELECT client_id FROM leads WHERE id = :lead_id"),
                                {"lead_id": lead_id}
                            ).fetchone()

                            parsed_client_id = None
                            if client_id_result and client_id_result.client_id is not None:
                                if client_id_result.client_id.isdigit():
                                    parsed_client_id = int(client_id_result.client_id)

                            new_message = Message(
                                client_id=parsed_client_id,
                                company_id=company_id,
                                contact_phone=phone,
                                message_type="text",
                                content=msg.content,
                                sender_phone="NoShowFlow",
                                sender_name="NoShow System",
                                from_me=True,
                                timestamp=datetime.utcnow()
                            )
                            db.add(new_message)
                            db.commit()
                            logger.info(f"[NoShow] Mensagem (texto) ID={new_message.id} salva em 'messages'")

                            # >>> NOVO: Gravar no arquivo .txt
                            memory_manager.append_message_to_chat_file(
                                company_id=company_id,
                                contact_phone=phone,
                                from_me=True,  # enviado pelo sistema
                                content=msg.content
                            )

                        except Exception as e:
                            logger.error(f"[NoShow] Erro ao salvar msg texto no DB: {str(e)}", exc_info=True)

                    elif msg.type in ["image", "video", "audio"]:
                        try:
                            logger.info(f"[NoShow] Iniciando processamento de mídia: {msg.content}")
                            media_content = get_media_content(msg.content, msg.type)

                            if not media_content:
                                logger.error(f"[NoShow] Falha ao processar mídia: {msg.content}")
                                continue

                            if msg.type == "image":
                                response = send_image_to_zapi(
                                    instance_id=instance_id,
                                    instance_token=instance_token,
                                    body=WhatsAppSendImageBody(
                                        phone=phone,
                                        image=media_content,
                                        caption=msg.caption if hasattr(msg, 'caption') else None
                                    )
                                )
                                logger.info(f"[NoShow] Resposta envio imagem: {response}")
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
                                logger.info(f"[NoShow] Resposta envio áudio: {response}")
                                publish_message_to_redis("audio", msg.content, phone)
                                mensagens_enviadas = True

                            elif msg.type == "video":
                                response = send_video_to_zapi(
                                    instance_id=instance_id,
                                    instance_token=instance_token,
                                    body=WhatsAppSendVideoBody(
                                        phone=phone,
                                        video=media_content,
                                        caption=msg.caption if hasattr(msg, 'caption') else None
                                    )
                                )
                                logger.info(f"[NoShow] Resposta envio vídeo: {response}")
                                publish_message_to_redis("video", msg.content, phone)
                                mensagens_enviadas = True

                            # Persistir no DB (mensagem de mídia)
                            try:
                                client_id_result = db.execute(
                                    text("SELECT client_id FROM leads WHERE id = :lead_id"),
                                    {"lead_id": lead_id}
                                ).fetchone()

                                parsed_client_id = None
                                if client_id_result and client_id_result.client_id is not None:
                                    if client_id_result.client_id.isdigit():
                                        parsed_client_id = int(client_id_result.client_id)

                                new_message = Message(
                                    client_id=parsed_client_id,
                                    company_id=company_id,
                                    contact_phone=phone,
                                    message_type=msg.type,
                                    content=msg.content,
                                    sender_phone="NoShowFlow",
                                    sender_name="NoShow System",
                                    from_me=True,
                                    timestamp=datetime.utcnow()
                                )
                                db.add(new_message)
                                db.commit()
                                logger.info(f"[NoShow] Mensagem (mídia) ID={new_message.id} salva em 'messages'")

                                # >>> NOVO: Lógica para obter texto e gravar no .txt
                                text_to_history = ""
                                # Precisamos do caminho local, se não for URL
                                full_path = os.path.join(MEDIA_BASE_PATH, msg.content) if not msg.content.startswith(('http://', 'https://')) else None

                                if msg.type == "image" and full_path and os.path.exists(full_path):
                                    text_to_history = analyze_image_local(full_path) or "[Imagem sem análise]"
                                elif msg.type == "audio" and full_path and os.path.exists(full_path):
                                    text_to_history = transcribe_audio_local(full_path) or "[Áudio sem transcrição]"
                                elif msg.type == "video" and full_path and os.path.exists(full_path):
                                    text_to_history = transcribe_video_local(full_path) or "[Vídeo sem transcrição]"
                                else:
                                    text_to_history = "[Mídia sem análise]"

                                memory_manager.append_message_to_chat_file(
                                    company_id=company_id,
                                    contact_phone=phone,
                                    from_me=True,
                                    content=text_to_history
                                )

                            except Exception as e:
                                logger.error(f"[NoShow] Erro ao salvar msg mídia no DB: {str(e)}", exc_info=True)

                        except HTTPException as http_e:
                            logger.error(f"[NoShow] Erro HTTP ao enviar mídia {msg.id}: {str(http_e)}")
                            envio_com_erro = True
                            error_msg = str(http_e)
                            continue
                        except Exception as e:
                            logger.error(f"[NoShow] Erro ao enviar mídia {msg.id}: {str(e)}", exc_info=True)
                            envio_com_erro = True
                            error_msg = str(e)
                            continue

                    elif msg.type == "call":
                        logger.info(f"[NoShow] Fazendo ligação de {msg.content}s para {phone}")
                        try:
                            # Validar duração
                            duration = int(msg.content) if msg.content and str(msg.content).isdigit() else 10
                            duration = max(5, min(60, duration))  # Entre 5 e 60 segundos

                            # Criar request para ligação
                            call_data = SendCallRequest(
                                phone=phone,
                                callDuration=duration
                            )

                            # Fazer ligação
                            response = send_call(instance_id, instance_token, call_data)
                            logger.info(f"[NoShow] Ligação de {duration}s enviada com sucesso para {phone}")
                            publish_message_to_redis("call", f"Ligação de {duration}s", phone)
                            mensagens_enviadas = True

                            # Persistir no DB (mensagem de ligação)
                            try:
                                client_id_result = db.execute(
                                    text("SELECT client_id FROM leads WHERE id = :lead_id"),
                                    {"lead_id": lead_id}
                                ).fetchone()

                                parsed_client_id = None
                                if client_id_result and client_id_result.client_id is not None:
                                    if client_id_result.client_id.isdigit():
                                        parsed_client_id = int(client_id_result.client_id)

                                new_message = Message(
                                    client_id=parsed_client_id,
                                    company_id=company_id,
                                    contact_phone=phone,
                                    message_type="call",
                                    content=f"Ligação de {duration}s",
                                    sender_phone="NoShowFlow",
                                    sender_name="NoShow System",
                                    from_me=True,
                                    timestamp=datetime.utcnow()
                                )
                                db.add(new_message)
                                db.commit()

                                # Salvar no chat memory
                                memory_manager.append_message_to_chat_file(
                                    company_id=company_id,
                                    contact_phone=phone,
                                    from_me=True,
                                    content=f"[Ligação de {duration}s realizada]"
                                )

                            except Exception as e:
                                logger.error(f"[NoShow] Erro ao salvar msg ligação no DB: {str(e)}", exc_info=True)

                        except Exception as call_error:
                            logger.error(f"[NoShow] Erro ao fazer ligação: {str(call_error)}")
                            envio_com_erro = True
                            error_msg = f"Erro na ligação: {str(call_error)}"
                            continue

                    pytime.sleep(1)  # Delay entre mensagens

                except Exception as e:
                    logger.error(f"[NoShow] Erro ao processar mensagem: {str(e)}", exc_info=True)
                    envio_com_erro = True
                    error_msg = str(e)
                    continue

            # >>> NOVO: Concluímos o passo, definir status
            if mensagens_enviadas:
                final_status = 'SUCCESS' if not envio_com_erro else 'FAILED'
            else:
                final_status = 'FAILED'
                if not error_msg:
                    error_msg = "Nenhuma mensagem enviada"

            # Atualiza noshow_follow_up_executions
            insert_or_update_noshow_execution(
                db,
                lead_id=lead_id,
                company_id=company_id,
                sequence_id=seq.id,
                step_id=step_obj.id,
                step_number=step_number,
                status=final_status,
                error_message=error_msg
            )

            if final_status == 'FAILED':
                logger.error(f"[NoShow] Falha no envio do step={step_number}. Encerrando sem agendar próximo.")
                return

            # Se SUCCESS, registra no Redis e agenda próximo step
            set_last_noshow_step(company_id, lead_id, step_number, seq.id)

            # 9) Verificar e agendar próximo step se existir
            next_step = db.query(NoShowFollowUpStep).filter(
                NoShowFollowUpStep.noshow_follow_up_sequence_id == seq.id,
                NoShowFollowUpStep.step_number == step_number + 1
            ).first()

            if next_step:
                unit = next_step.send_after_unit
                delta = {}
                if unit == "days":
                    delta["days"] = next_step.send_after
                elif unit == "hours":
                    delta["hours"] = next_step.send_after
                elif unit == "minutes":
                    delta["minutes"] = next_step.send_after

                eta = datetime.utcnow() + timedelta(**delta)

                if schedule_conf and schedule_conf.schedule_data:
                    logger.info("[NoShow] Ajustando horário de envio para respeitar a configuração do schedule...")
                    eta_original = eta
                    eta = adjust_eta_to_schedule(eta, schedule_conf.schedule_data, "America/Sao_Paulo")
                    logger.info(f"[NoShow] Horário anterior (UTC): {eta_original}, horário ajustado (UTC): {eta}")

                # >>> NOVO: registra como SCHEDULED
                insert_or_update_noshow_execution(
                    db,
                    lead_id=lead_id,
                    company_id=company_id,
                    sequence_id=seq.id,
                    step_id=next_step.id,
                    step_number=next_step.step_number,
                    status='SCHEDULED',
                    scheduled_for=eta
                )

                enviar_passo_noshow.apply_async(
                    args=[
                        lead_id,
                        step_number + 1,
                        company_id,
                        phone,
                        operational_epoch,
                    ],
                    eta=eta
                )
                logger.info(f"[NoShow] Próximo passo={step_number+1} agendado para {eta}")
            else:
                logger.info("[NoShow] Não há próximo step. Fluxo encerrado.")

        finally:
            # Libera o lock independente do resultado
            redis_client.delete(lock_key)

    except Exception as e:
        logger.error(f"[NoShow] Erro na task enviar_passo_noshow: {str(e)}", exc_info=True)
        # >>> NOVO: se der erro geral, poderia marcar FAILED se tivermos step_obj
        try:
            if 'step_obj' in locals() and 'seq' in locals():
                insert_or_update_noshow_execution(
                    db,
                    lead_id=lead_id,
                    company_id=company_id,
                    sequence_id=seq.id,
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
