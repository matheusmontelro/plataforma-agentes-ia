# backend/worker/tasks_confirmation.py

import logging
import os
import time
import asyncio
from uuid import uuid4
from datetime import datetime, timedelta
from pytz import timezone
from sqlalchemy import text
from celery import Celery
import redis
from .celery_app import app
from backend.db import SessionLocal
from backend.runtime_settings import GOOGLE_VISION_CREDENTIALS, LOG_DIR as RUNTIME_LOG_DIR
from .flow_control import check_flow_control

# ----------------------------------------------------------------------------
# >>> NOVO: Configurar FileHandler para logs de confirmação <<<
# ----------------------------------------------------------------------------

# Diretório e arquivo de log
LOG_DIR = str(RUNTIME_LOG_DIR)
os.makedirs(LOG_DIR, exist_ok=True)  # Garante que o diretório exista
LOG_FILE = os.path.join(LOG_DIR, "confirmation_tasks.log")

# Cria um logger local baseado no nome do módulo
logger = logging.getLogger(__name__)

# Cria e adiciona um FileHandler para registrar logs de confirmação.
file_handler = logging.FileHandler(LOG_FILE)
file_formatter = logging.Formatter(
    '%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s'
)
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# (Opcional) Ajuste o nível de log, caso queira garantir logs INFO+:
logger.setLevel(logging.INFO)

# ----------------------------------------------------------------------------

redis_client = redis.Redis(host='localhost', port=6379, db=0)

import pytz
import json
import speech_recognition as sr
from pydub import AudioSegment
from google.cloud import vision
from google.oauth2 import service_account
from backend.prompt.memory import memory_manager

# ----------------------------------------------------------------------------
# >>> NOVAS FUNÇÕES para processar arquivos locais (áudio, vídeo, imagem) <<<
# ----------------------------------------------------------------------------

def transcribe_audio_local(file_path: str) -> str:
    """
    Transcreve arquivo de áudio local usando SpeechRecognition.
    """
    try:
        audio = AudioSegment.from_file(file_path)
        temp_wav = "temp_audio_confirm.wav"
        audio.export(temp_wav, format="wav")

        recognizer = sr.Recognizer()
        with sr.AudioFile(temp_wav) as source:
            audio_content = recognizer.record(source)
            transcription = recognizer.recognize_google(audio_content, language="pt-BR")
        return transcription
    except Exception as e:
        logger.error(f"[CONF] Erro ao transcrever áudio local: {str(e)}", exc_info=True)
        return ""

def transcribe_video_local(file_path: str) -> str:
    """
    Extrai áudio de vídeo local usando pydub e transcreve via SpeechRecognition.
    """
    try:
        video_audio = AudioSegment.from_file(file_path, format="mp4")
        temp_video_audio = "temp_video_audio_confirm.wav"
        video_audio.export(temp_video_audio, format="wav")

        recognizer = sr.Recognizer()
        with sr.AudioFile(temp_video_audio) as source:
            audio_content = recognizer.record(source)
            transcription = recognizer.recognize_google(audio_content, language="pt-BR")
        return transcription
    except Exception as e:
        logger.error(f"[CONF] Erro ao transcrever vídeo local: {str(e)}", exc_info=True)
        return ""

def analyze_image_local(file_path: str) -> str:
    """
    Análise local de imagem via Google Vision (label_detection) lendo do disco.
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
        logger.error(f"[CONF] Erro ao analisar imagem local: {str(e)}", exc_info=True)
        return "Falha ao analisar imagem no Google Vision."

# -----------------------------------------------------------------------------
# >>> FUNÇÕES AUXILIARES (janelas de envio, Redis, etc.) <<<
# -----------------------------------------------------------------------------

def adjust_eta_to_schedule(eta_local: datetime, schedule_data_str, tz_name="America/Sao_Paulo") -> datetime:
    """
    Ajusta a data/hora 'eta_local' (time-zone aware) de acordo com o JSON de 'schedule_data_str',
    garantindo que caia dentro de [start, end]. Se cair fora, pula para o próximo dia/hora.
    Retorna um datetime (no mesmo timezone de eta_local) ajustado ou None se não for possível.
    """
    try:
        if isinstance(schedule_data_str, str):
            schedule_data = json.loads(schedule_data_str)
        else:
            schedule_data = schedule_data_str
    except Exception:
        return eta_local  # se não conseguir parsear, retorna o original

    for _ in range(14):  # tenta no máximo 14 dias à frente
        weekday_name = eta_local.strftime("%A").lower()  # ex: "monday"
        config_day = schedule_data.get(weekday_name)

        if not config_day:
            eta_local += timedelta(days=1)
            eta_local = eta_local.replace(hour=0, minute=0, second=0, microsecond=0)
            continue

        start_str = config_day.get("start")
        end_str   = config_day.get("end")
        if not start_str or not end_str:
            eta_local += timedelta(days=1)
            eta_local = eta_local.replace(hour=0, minute=0, second=0, microsecond=0)
            continue

        sh, sm = map(int, start_str.split(":"))
        eh, em = map(int, end_str.split(":"))
        start_time = eta_local.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end_time   = eta_local.replace(hour=eh, minute=em, second=0, microsecond=0)

        if eta_local < start_time:
            return start_time
        if eta_local > end_time:
            eta_local += timedelta(days=1)
            eta_local = eta_local.replace(hour=0, minute=0, second=0, microsecond=0)
            continue

        # está dentro de [start_time, end_time]
        return eta_local

    return None

def get_last_confirmation_step(agendamento_id: int) -> dict:
    """
    Recupera do Redis o último step de confirmação enviado para um agendamento.
    Retorna dict com: {
        "step_number": int,
        "timestamp": datetime,
        "sequence_id": int
    } ou None se não houver registro
    """
    try:
        key = f"confirm:last_step:{agendamento_id}"
        data = redis_client.get(key)
        if data:
            info = json.loads(data)
            info["timestamp"] = datetime.fromisoformat(info["timestamp"])
            return info
        return None
    except Exception as e:
        logger.error(f"[CONF] Erro ao obter último step de confirmação: {str(e)}")
        return None

def set_last_confirmation_step(agendamento_id: int, step_number: int, sequence_id: int) -> None:
    """
    Armazena no Redis o último step de confirmação enviado
    """
    try:
        key = f"confirm:last_step:{agendamento_id}"
        data = {
            "step_number": step_number,
            "timestamp": datetime.utcnow().isoformat(),
            "sequence_id": sequence_id
        }
        redis_client.set(key, json.dumps(data))
        # Expira em 30 dias
        redis_client.expire(key, 60 * 60 * 24 * 30)
    except Exception as e:
        logger.error(f"[CONF] Erro ao salvar último step de confirmação: {str(e)}")

def clear_confirmation_steps(agendamento_id: int) -> None:
    """
    Limpa o registro de steps para um agendamento e cancela tasks Celery pendentes
    """
    try:
        # Limpar Redis
        key = f"confirm:last_step:{agendamento_id}"
        redis_client.delete(key)

        # Cancelar tasks Celery pendentes para este agendamento
        try:
            # Buscar tasks ativas/agendadas no Celery para este agendamento
            active_tasks = app.control.inspect().active()
            scheduled_tasks = app.control.inspect().scheduled()

            tasks_to_revoke = []

            # Verificar tasks ativas
            if active_tasks:
                for worker, task_list in active_tasks.items():
                    for task in task_list:
                        if ('enviar_passo_confirmacao' in task.get('name', '') or
                            'enviar_lote_confirmacao' in task.get('name', '')):
                            # Verificar se é para este agendamento (primeiro argumento)
                            args = task.get('args', [])
                            if args and len(args) > 0 and args[0] == agendamento_id:
                                tasks_to_revoke.append(task['id'])

            # Verificar tasks agendadas
            if scheduled_tasks:
                for worker, task_dict in scheduled_tasks.items():
                    for task in task_dict.values():
                        for scheduled_task in task:
                            if ('enviar_passo_confirmacao' in scheduled_task.get('name', '') or
                                'enviar_lote_confirmacao' in scheduled_task.get('name', '')):
                                args = scheduled_task.get('args', [])
                                if args and len(args) > 0 and args[0] == agendamento_id:
                                    tasks_to_revoke.append(scheduled_task['id'])

            # Cancelar todas as tasks encontradas
            if tasks_to_revoke:
                for task_id in tasks_to_revoke:
                    app.control.revoke(task_id, terminate=True)
                    logger.info(f"[CONF] Task Celery cancelada: {task_id} para agendamento {agendamento_id}")
                logger.info(f"[CONF] Canceladas {len(tasks_to_revoke)} tasks Celery para agendamento {agendamento_id}")
            else:
                logger.info(f"[CONF] Nenhuma task Celery encontrada para cancelar (agendamento {agendamento_id})")

        except Exception as celery_error:
            logger.error(f"[CONF] Erro ao cancelar tasks Celery para agendamento {agendamento_id}: {str(celery_error)}")

    except Exception as e:
        logger.error(f"[CONF] Erro ao limpar steps de confirmação: {str(e)}")


# -----------------------------------------------------------------------------
# >>> TASKS DE CONFIRMAÇÃO
# -----------------------------------------------------------------------------

@app.task
@check_flow_control('confirmation')
def enviar_passo_confirmacao(agendamento_id: int, step_number: int,
                             instance_id: str, instance_token: str, phone: str,
                             operational_epoch: int | None = None):
    """
    Calcula o momento ideal de disparo do step_number e agenda
    o envio (enviar_lote_confirmacao) naquele horário.
    Usa a tabela confirmation_executions, Redis etc.
    """
    # Lock distribuído para evitar execução simultânea
    lock_key = f"confirm:lock:passo:{agendamento_id}:{step_number}"
    lock_timeout = 30  # segundos
    worker_id = f"{os.getpid()}_{uuid4().hex[:8]}"

    # Tentar adquirir o lock
    if not redis_client.set(lock_key, worker_id, nx=True, ex=lock_timeout):
        current_owner = redis_client.get(lock_key)
        logger.info(f"[CONF] Worker {worker_id} bloqueado. Lock já pertence a {current_owner} para step={step_number}, agendamento={agendamento_id}")
        return

    logger.info(f"[CONF] Worker {worker_id} adquiriu lock para step={step_number}, agendamento={agendamento_id}")

    db = SessionLocal()
    try:
        logger.info(f"[CONF] Iniciando enviar_passo_confirmacao p/ agendamento_id={agendamento_id}, step={step_number}")

        # >>> FIX DUPLICAÇÃO <<< (1)
        existing_exec = db.execute(
            text("""
                SELECT id, status
                FROM confirmation_executions
                WHERE agendamento_id = :ag_id
                  AND step_number = :step_number
                  AND status IN ('SCHEDULED','PROCESSING','SUCCESS','CANCELED')
                LIMIT 1
            """),
            {"ag_id": agendamento_id, "step_number": step_number}
        ).fetchone()

        if existing_exec:
            logger.info(
                f"[CONF] Step {step_number} para agendamento {agendamento_id} já está em "
                f"status {existing_exec.status}. Não vamos reagendar."
            )
            return

        # Verificar em Redis se já enviou step >= step_number
        last_step = get_last_confirmation_step(agendamento_id)
        if last_step and last_step["step_number"] >= step_number:
            logger.info(
                f"[CONF] Step {step_number} já foi enviado anteriormente (Redis). "
                f"Último={last_step['step_number']}"
            )
            return

        # 1) Buscar agendamento e consulta_data
        ag_row = db.execute(
            text("""
                SELECT
                    a.consulta_data,
                    a.phone,
                    a.company_id,
                    a.status,
                    COALESCE(ag.timezone, 'America/Sao_Paulo') AS agenda_timezone
                FROM agendamentos a
                LEFT JOIN agendas ag ON ag.id = a.agenda_id
                WHERE a.id = :ag_id
                LIMIT 1
            """),
            {"ag_id": agendamento_id}
        ).fetchone()

        if not ag_row:
            logger.warning(f"[CONF] Agendamento {agendamento_id} não encontrado. Encerrando.")
            return
        from backend.services.company_access_control import validate_company_job_epoch
        if not validate_company_job_epoch(
            db,
            int(ag_row.company_id),
            operational_epoch,
        ):
            db.execute(
                text("""
                    UPDATE confirmation_executions
                       SET status = 'CANCELED',
                           error_message = 'company_access_suspended',
                           updated_at = now()
                     WHERE agendamento_id = :ag_id
                       AND status IN ('SCHEDULED', 'PROCESSING')
                """),
                {"ag_id": agendamento_id},
            )
            db.commit()
            return

        if ag_row.status not in ('SCHEDULED'):
            logger.info(f"[CONF] Status do agendamento é '{ag_row.status}'. Encerrando fluxo.")
            return

        try:
            consulta_dt_db = ag_row.consulta_data
            if not isinstance(consulta_dt_db, datetime):
                logger.error(f"[CONF] consulta_data não é datetime. Valor: {consulta_dt_db}")
                return
            local_tz = timezone(ag_row.agenda_timezone or "America/Sao_Paulo")
            consulta_dt_local = (
                consulta_dt_db.astimezone(local_tz)
                if consulta_dt_db.tzinfo
                else local_tz.localize(consulta_dt_db)
            )
            consulta_dt_naive = consulta_dt_local.replace(tzinfo=None)
        except Exception as e:
            logger.error(f"[CONF] Erro ao tratar consulta_data: {e}")
            return

        # 2) confirmation_sequence
        seq_row = db.execute(
            text("""
                SELECT cs.id
                  FROM confirmation_sequences cs
                  JOIN agendamentos a
                    ON a.client_id::varchar = cs.client_id
                   AND a.company_id = cs.company_id
                 WHERE a.id = :ag_id
                   AND cs.company_id = :cid
                 LIMIT 1
            """),
            {
                "ag_id": agendamento_id,
                "cid": ag_row.company_id
            }
        ).fetchone()

        if not seq_row:
            logger.warning(
                f"[CONF] Nenhuma confirmation_sequence encontrada p/ "
                f"company_id={ag_row.company_id}, agendamento_id={agendamento_id}"
            )
            return

        sequence_id = seq_row.id
        logger.info(f"[CONF] Usando sequência id={sequence_id} para empresa {ag_row.company_id}")

        # Se mudou a sequence, limpa cache
        last_step = get_last_confirmation_step(agendamento_id)
        if last_step and last_step["sequence_id"] != sequence_id:
            logger.info("[CONF] Sequência mudou. Limpando histórico de steps.")
            clear_confirmation_steps(agendamento_id)

        step_row = db.execute(
            text("""
                SELECT id, send_after, send_after_unit
                FROM confirmation_steps
                WHERE confirmation_sequence_id = :seq_id
                  AND step_number = :step_number
                LIMIT 1
            """),
            {"seq_id": sequence_id, "step_number": step_number}
        ).fetchone()

        if not step_row:
            logger.info(f"[CONF] step_number={step_number} não existe p/ sequence_id={sequence_id}. Encerrando.")
            return

        step_id = step_row.id
        send_before = step_row.send_after
        send_before_unit = step_row.send_after_unit

        now_local = datetime.now(local_tz)

        # 3) data/hora de disparo
        if send_before_unit == "minutes":
            disparo_dt_naive = consulta_dt_naive - timedelta(minutes=send_before)
        elif send_before_unit == "hours":
            disparo_dt_naive = consulta_dt_naive - timedelta(hours=send_before)
        elif send_before_unit == "days":
            disparo_dt_naive = consulta_dt_naive - timedelta(days=send_before)
        else:
            disparo_dt_naive = consulta_dt_naive

        disparo_dt_local = local_tz.localize(disparo_dt_naive)

        # Se já passou, skip
        if disparo_dt_local < now_local:
            logger.info("[CONF] Disparo já passou (disparo_dt < agora). Pulando step atual e chamando próximo...")

            try:
                db.execute(
                    text("""
                        INSERT INTO confirmation_executions (
                            agendamento_id, company_id, confirmation_sequence_id,
                            confirmation_step_id, step_number, status,
                            error_message
                        )
                        VALUES (
                            :ag_id, :company_id, :seq_id, :step_id, :step_number,
                            'SUCCESS', 'Enviado automaticamente p/ skip'
                        )
                        ON CONFLICT (agendamento_id, confirmation_sequence_id, confirmation_step_id)
                        DO UPDATE SET
                            status = 'SUCCESS',
                            error_message = 'Enviado automaticamente p/ skip',
                            updated_at = now()
                    """),
                    {
                        "ag_id": agendamento_id,
                        "company_id": ag_row.company_id,
                        "seq_id": sequence_id,
                        "step_id": step_id,
                        "step_number": step_number
                    }
                )
                db.commit()
            except Exception as e:
                logger.error(f"[CONF] Erro ao registrar skip na confirmation_executions: {e}")

            set_last_confirmation_step(
                agendamento_id=agendamento_id,
                step_number=step_number,
                sequence_id=sequence_id
            )

            # Buscar próximo step
            next_step_row = db.execute(
                text("""
                    SELECT id, step_number
                    FROM confirmation_steps
                    WHERE confirmation_sequence_id = :seq_id
                      AND step_number = :next_step
                """),
                {"seq_id": sequence_id, "next_step": step_number + 1}
            ).fetchone()

            if next_step_row:
                logger.info(f"[CONF] Step {step_number+1} existe. Chamando enviar_passo_confirmacao p/ prox step.")
                enviar_passo_confirmacao.delay(
                    agendamento_id=agendamento_id,
                    step_number=step_number+1,
                    instance_id=instance_id,
                    instance_token=instance_token,
                    phone=phone,
                    operational_epoch=operational_epoch,
                )
            return

        # 4) Ajusta p/ janela
        sched_row = db.execute(
            text("""
                SELECT schedule_data
                FROM confirmation_schedule_configs
                WHERE company_id = :cid
                  AND confirmation_sequence_id = :seq_id
                LIMIT 1
            """),
            {"cid": ag_row.company_id, "seq_id": sequence_id}
        ).fetchone()

        if sched_row and sched_row.schedule_data:
            logger.info("[CONF] Ajustando disparo_dt p/ janela de envio (confirmation_schedule_configs).")
            adjusted_dt = adjust_eta_to_schedule(
                disparo_dt_local,
                sched_row.schedule_data,
                ag_row.agenda_timezone or "America/Sao_Paulo",
            )
            if not adjusted_dt:
                logger.info("[CONF] Não foi possível ajustar disparo_dt à janela. Encerrando.")
                return
            disparo_dt_local = adjusted_dt

        # 5) Registra SCHEDULED
        try:
            db.execute(
                text("""
                    INSERT INTO confirmation_executions (
                        agendamento_id, company_id, confirmation_sequence_id,
                        confirmation_step_id, step_number, status, scheduled_for,
                        original_consulta_data
                    )
                    VALUES (
                        :ag_id, :company_id, :seq_id, :step_id,
                        :step_number, 'SCHEDULED', :scheduled_for,
                        :original_consulta_data
                    )
                    ON CONFLICT (agendamento_id, confirmation_sequence_id, confirmation_step_id)
                    DO UPDATE SET
                        status = EXCLUDED.status,
                        scheduled_for = EXCLUDED.scheduled_for,
                        original_consulta_data = EXCLUDED.original_consulta_data,
                        updated_at = now()
                """),
                {
                    "ag_id": agendamento_id,
                    "company_id": ag_row.company_id,
                    "seq_id": sequence_id,
                    "step_id": step_id,
                    "step_number": step_number,
                    "scheduled_for": disparo_dt_local.astimezone(timezone('UTC')),
                    "original_consulta_data": ag_row.consulta_data
                }
            )
            db.commit()
        except Exception as e:
            logger.error(f"[CONF] Erro ao inserir SCHEDULED em confirmation_executions: {e}")
            return

        set_last_confirmation_step(
            agendamento_id=agendamento_id,
            step_number=step_number,
            sequence_id=sequence_id
        )

        # 6) Agenda lote
        import pytz
        disparo_dt_utc = disparo_dt_local.astimezone(pytz.UTC)

        enviar_lote_confirmacao.apply_async(
            args=[
                agendamento_id,
                step_number,
                instance_id,
                instance_token,
                phone,
                operational_epoch,
            ],
            eta=disparo_dt_utc
        )
        logger.info(
            f"[CONF] Lote de mensagens do step {step_number} agendado "
            f"para {disparo_dt_local.isoformat()} SP / {disparo_dt_utc.isoformat()} UTC"
        )

    except Exception as e:
        logger.error(f"[CONF] Erro no enviar_passo_confirmacao: {e}")
    finally:
        db.close()
        # Liberar o lock
        redis_client.delete(lock_key)


@app.task
@check_flow_control('confirmation')
def enviar_lote_confirmacao(agendamento_id: int, step_number: int,
                            instance_id: str, instance_token: str, phone: str,
                            operational_epoch: int | None = None):
    """
    Dispara efetivamente as mensagens do step no horário calculado.
    Agora com a lógica de registrar PROCESSING/SUCCESS/FAILED em confirmation_executions.
    Também checa se a consulta_data mudou (reagendamento).
    """
    from backend.integrations.whatsapp_provider import (
        WhatsAppConfig,
        send_audio as send_whatsapp_audio,
        send_image as send_whatsapp_image,
        send_text as send_whatsapp_text,
        send_video as send_whatsapp_video,
    )

    # Lock distribuído para evitar execução simultânea
    lock_key = f"confirm:lock:lote:{agendamento_id}:{step_number}"
    lock_timeout = 60  # segundos (mais tempo para processar o lote)
    worker_id = f"{os.getpid()}_{uuid4().hex[:8]}"

    # Tentar adquirir o lock
    if not redis_client.set(lock_key, worker_id, nx=True, ex=lock_timeout):
        current_owner = redis_client.get(lock_key)
        logger.info(f"[CONF] Worker {worker_id} bloqueado. Lock já pertence a {current_owner} para lote step={step_number}, agendamento={agendamento_id}")
        return

    logger.info(f"[CONF] Worker {worker_id} adquiriu lock para lote step={step_number}, agendamento={agendamento_id}")

    db = SessionLocal()
    try:
        logger.info(f"[CONF] enviar_lote_confirmacao => agendamento_id={agendamento_id}, step={step_number}")

        # 1) Buscar SCHEDULED
        exec_row = db.execute(
            text("""
                SELECT
                    id,
                    company_id,
                    confirmation_sequence_id,
                    confirmation_step_id,
                    original_consulta_data
                FROM confirmation_executions
                WHERE agendamento_id = :ag_id
                  AND step_number = :step_number
                  AND status = 'SCHEDULED'
                ORDER BY id DESC
                LIMIT 1
            """),
            {"ag_id": agendamento_id, "step_number": step_number}
        ).fetchone()

        if not exec_row:
            logger.info(
                f"[CONF] Nenhum registro SCHEDULED p/ step={step_number}, agendamento={agendamento_id} "
                f"(talvez já executou?). Encerrando."
            )
            return
        from backend.services.company_access_control import validate_company_job_epoch
        if not validate_company_job_epoch(
            db,
            int(exec_row.company_id),
            operational_epoch,
        ):
            db.execute(
                text("""
                    UPDATE confirmation_executions
                       SET status = 'CANCELED',
                           error_message = 'company_access_suspended',
                           updated_at = now()
                     WHERE id = :id
                """),
                {"id": exec_row.id},
            )
            db.commit()
            return

        db.execute(
            text("""
                UPDATE confirmation_executions
                SET status = 'PROCESSING',
                    updated_at = now(),
                    executed_at = now()
                WHERE id = :id
            """),
            {"id": exec_row.id}
        )
        db.commit()

        # 2) Reagendamento?
        consulta_dt_row = db.execute(
            text("""
                SELECT
                    a.consulta_data,
                    COALESCE(ag.timezone, 'America/Sao_Paulo') AS agenda_timezone
                FROM agendamentos a
                LEFT JOIN agendas ag ON ag.id = a.agenda_id
                WHERE a.id = :ag_id
                LIMIT 1
            """),
            {"ag_id": agendamento_id}
        ).fetchone()

        if consulta_dt_row and consulta_dt_row.consulta_data and exec_row.original_consulta_data:
            current_cd = consulta_dt_row.consulta_data
            original_cd = exec_row.original_consulta_data
            if current_cd.replace(microsecond=0) != original_cd.replace(microsecond=0):
                logger.info("[CONF] Detectado reagendamento. Cancelando este step e reiniciando do step 1.")
                db.execute(
                    text("""
                        UPDATE confirmation_executions
                        SET status = 'CANCELED',
                            error_message = 'Consulta reagendada. Reiniciando fluxo.'
                        WHERE id = :id
                    """),
                    {"id": exec_row.id}
                )
                db.commit()

                clear_confirmation_steps(agendamento_id)

                company_id_row = db.execute(
                    text("""
                        SELECT company_id, phone
                        FROM agendamentos
                        WHERE id = :ag_id
                        LIMIT 1
                    """),
                    {"ag_id": agendamento_id}
                ).fetchone()

                if company_id_row:
                    enviar_passo_confirmacao.delay(
                        agendamento_id=agendamento_id,
                        step_number=1,
                        instance_id="",
                        instance_token="",
                        phone=company_id_row.phone,
                        operational_epoch=operational_epoch,
                    )
                return

        # 3) Formatar data
        consulta_data_formatada = None
        if consulta_dt_row and isinstance(consulta_dt_row.consulta_data, datetime):
            consulta_timezone = timezone(consulta_dt_row.agenda_timezone or "America/Sao_Paulo")
            consulta_dt = consulta_dt_row.consulta_data
            if consulta_dt.tzinfo:
                consulta_dt = consulta_dt.astimezone(consulta_timezone)
            else:
                consulta_dt = consulta_timezone.localize(consulta_dt)
            consulta_data_formatada = consulta_dt.strftime("%d/%m/%Y %H:%M")

        # 4) Validar step
        step_info = db.execute(
            text("""
                SELECT s.id AS step_id,
                       s.confirmation_sequence_id AS seq_id
                  FROM confirmation_steps s
                  JOIN confirmation_sequences cs
                    ON cs.id = s.confirmation_sequence_id
                  JOIN agendamentos a
                    ON a.client_id::varchar = cs.client_id
                   AND a.company_id = cs.company_id
                 WHERE a.id = :ag_id
                   AND s.step_number = :step_number
                 LIMIT 1
            """),
            {"ag_id": agendamento_id, "step_number": step_number}
        ).fetchone()

        if not step_info:
            logger.warning("[CONF] Step não encontrado. Encerrando.")
            db.execute(
                text("""
                    UPDATE confirmation_executions
                    SET status = 'FAILED',
                        error_message = 'Step não encontrado.',
                        updated_at = now()
                    WHERE id = :id
                """),
                {"id": exec_row.id}
            )
            db.commit()
            return

        # 5) Mensagens do step
        msg_rows = db.execute(
            text("""
                SELECT
                    m.id,
                    m.type,
                    m.content,
                    mf.file_path,
                    mf.mime_type
                FROM confirmation_messages m
                LEFT JOIN media_files mf ON mf.relative_path = m.content
                WHERE m.confirmation_step_id = :step_id
                ORDER BY m.id ASC
            """),
            {"step_id": step_info.step_id}
        ).fetchall()

        if not msg_rows:
            logger.info("[CONF] Nenhuma mensagem para este step.")
            db.execute(
                text("""
                    UPDATE confirmation_executions
                    SET status = 'SUCCESS',
                        error_message = 'Nenhuma mensagem no step.',
                        updated_at = now()
                    WHERE id = :id
                """),
                {"id": exec_row.id}
            )
            db.commit()
            return

        # 6) Dados do agendamento e configuração WAHA
        ag_data = db.execute(
            text("""
                SELECT client_id, company_id, phone
                FROM agendamentos
                WHERE id = :ag_id
            """),
            {"ag_id": agendamento_id}
        ).fetchone()

        if ag_data:
            ag_client_id = ag_data.client_id
            ag_company_id = ag_data.company_id
            ag_phone     = ag_data.phone
        else:
            ag_client_id = None
            ag_company_id = None
            ag_phone     = phone

        if not ag_company_id or not WhatsAppConfig.from_company(ag_company_id, db):
            logger.warning("[CONF] Sem configuração WAHA ativa. Encerrando.")
            db.execute(
                text("""
                    UPDATE confirmation_executions
                    SET status = 'FAILED',
                        error_message = 'Sem configuração WAHA ativa',
                        updated_at = now()
                    WHERE id = :id
                """),
                {"id": exec_row.id}
            )
            db.commit()
            return

        success = True
        error_msg = None

        # 7) Enviar mensagens
        for m in msg_rows:
            try:
                final_content = m.content
                if consulta_data_formatada and "[data-consulta]" in final_content:
                    final_content = final_content.replace("[data-consulta]", consulta_data_formatada)

                resp = None
                if m.type == "text":
                    resp = send_whatsapp_text(
                        company_id=ag_company_id,
                        phone=phone,
                        message=final_content,
                        db=db,
                        human_mode=False
                    )
                elif m.type in ("image", "audio", "video") and m.file_path:
                    if m.type == "image":
                        resp = send_whatsapp_image(
                            company_id=ag_company_id,
                            phone=phone,
                            image_path=m.file_path,
                            db=db,
                        )
                    elif m.type == "audio":
                        resp = send_whatsapp_audio(
                            company_id=ag_company_id,
                            phone=phone,
                            audio_path=m.file_path,
                            db=db,
                        )
                    elif m.type == "video":
                        resp = send_whatsapp_video(
                            company_id=ag_company_id,
                            phone=phone,
                            video_path=m.file_path,
                            db=db,
                        )

                if resp:
                    logger.info(f"[CONF] Mensagem {m.id} enviada com sucesso.")
                    # Salvar no DB p/ aparecer no front
                    try:
                        db.execute(
                            text("""
                                INSERT INTO messages (
                                    client_id, company_id, contact_phone,
                                    message_type, content, sender_phone,
                                    sender_name, from_me, timestamp
                                )
                                VALUES (
                                    :client_id, :company_id, :contact_phone,
                                    :message_type, :content, :sender_phone,
                                    :sender_name, true, now()
                                )
                            """),
                            {
                                "client_id": ag_client_id,
                                "company_id": ag_company_id,
                                "contact_phone": ag_phone,
                                "message_type": m.type,
                                "content": final_content,
                                "sender_phone": "ConfirmationFlow",
                                "sender_name": "System Confirm",
                            }
                        )
                        db.commit()

                        # Registrar no histórico .txt
                        text_for_history = ""
                        if m.type == "text":
                            text_for_history = final_content
                        else:
                            # Tentar transcrever/analisar
                            if m.file_path and os.path.exists(m.file_path):
                                if m.type == "image":
                                    text_for_history = analyze_image_local(m.file_path) or "[Imagem sem análise]"
                                elif m.type == "audio":
                                    text_for_history = transcribe_audio_local(m.file_path) or "[Áudio sem transcrição]"
                                elif m.type == "video":
                                    text_for_history = transcribe_video_local(m.file_path) or "[Vídeo sem transcrição]"
                            else:
                                text_for_history = "[Mídia sem análise]"

                        memory_manager.append_message_to_chat_file(
                            company_id=ag_company_id,
                            contact_phone=ag_phone,
                            from_me=True,
                            content=text_for_history
                        )

                    except Exception as e:
                        logger.error(f"[CONF] Erro ao salvar mensagem no DB ou gravar no .txt: {e}", exc_info=True)

                    time.sleep(1)
            except Exception as e:
                logger.error(f"[CONF] Erro ao enviar msg_id={m.id}: {e}")
                success = False
                error_msg = str(e)
                break

        # 9) Finaliza
        final_status = "SUCCESS" if success else "FAILED"

        db.execute(
            text("""
                UPDATE confirmation_executions
                SET status = :status,
                    error_message = :error_msg,
                    updated_at = now()
                WHERE id = :id
            """),
            {
                "status": final_status,
                "error_msg": error_msg,
                "id": exec_row.id
            }
        )
        db.commit()

        if not success:
            logger.error("[CONF] Falha ao enviar pelo menos uma mensagem do lote. Encerrando.")
            return

        # 10) Próximo passo
        next_step = db.execute(
            text("""
                SELECT id, step_number
                FROM confirmation_steps
                WHERE confirmation_sequence_id = :seq_id
                  AND step_number = :next_step
            """),
            {"seq_id": step_info.seq_id, "next_step": step_number + 1}
        ).fetchone()

        if next_step:
            logger.info(f"[CONF] Step {step_number+1} existe. Chamando enviar_passo_confirmacao.")
            enviar_passo_confirmacao.delay(
                agendamento_id=agendamento_id,
                step_number=step_number+1,
                instance_id="",
                instance_token="",
                phone=phone,
                operational_epoch=operational_epoch,
            )

    except Exception as e:
        logger.error(f"[CONF] Erro em enviar_lote_confirmacao: {e}")
    finally:
        db.close()
        # Liberar o lock
        redis_client.delete(lock_key)
