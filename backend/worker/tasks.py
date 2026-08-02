from datetime import datetime, timedelta
import time
import logging
import json
import base64
import asyncio
from uuid import uuid4
from pytz import timezone
import redis
from celery import Celery
from sqlalchemy import text
import time as pytime

# >>> NOVOS IMPORTS removidos do topo para Lazy Loading <<<

from .celery_app import app
from backend.db import SessionLocal
from backend.routes.webhook import (
    WhatsAppSendAudioBody,
    WhatsAppSendImageBody,
    WhatsAppSendVideoBody,
    send_text_to_zapi,
    send_image_to_zapi,
    send_audio_to_zapi,
    send_video_to_zapi,
)
from backend.integrations.zapi_utils import send_call, SendCallRequest
from backend.ws_manager import manager
from backend.runtime_settings import GOOGLE_VISION_CREDENTIALS, LOG_DIR as RUNTIME_LOG_DIR
from .flow_control import check_flow_control

# >>> NOVO: Config de logs <<<
from backend.integrations.waha_utils import send_text_to_waha, send_audio_to_waha, send_image_to_waha, send_video_to_waha
import os
LOG_DIR = str(RUNTIME_LOG_DIR)
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "followup_tasks.log")

logger = logging.getLogger(__name__)

file_handler = logging.FileHandler(LOG_FILE)
file_formatter = logging.Formatter(
    '%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s'
)
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)
logger.setLevel(logging.INFO)
# >>> FIM NOVO <<<

redis_client = redis.Redis(host='localhost', port=6379, db=0)

# >>> NOVAS FUNÇÕES (Apenas para lidar com arquivos locais) <<<
# Como "audio_processing.py" e "image_analysis.py" esperam URL, criamos
# versões que aceitam arquivo local (sem alterar os scripts originais).
# Mantém-se a lógica sem mudar código não solicitado.

import requests
# Imports heavy libs moved to inside functions

def transcribe_audio_local(file_path: str) -> str:
    """
    Versão local da transcrição de áudio, similar à 'transcribe_audio',
    mas lendo o arquivo diretamente de um caminho local.
    """
    try:
        from pydub import AudioSegment
        import speech_recognition as sr

        audio = AudioSegment.from_file(file_path)
        temp_wav = "temp_audio.wav"
        audio.export(temp_wav, format="wav")

        recognizer = sr.Recognizer()
        with sr.AudioFile(temp_wav) as source:
            audio_content = recognizer.record(source)
            transcription = recognizer.recognize_google(audio_content, language="pt-BR")
        return transcription

    except Exception as e:
        logger.error(f"[Worker] Erro ao transcrever áudio local: {e}")
        return ""

def transcribe_video_local(file_path: str) -> str:
    """
    Versão local da transcrição de vídeo, similar à 'transcribe_video'.
    """
    try:
        from pydub import AudioSegment
        import speech_recognition as sr

        video_audio = AudioSegment.from_file(file_path, format="mp4")
        temp_video_audio = "temp_video_audio.wav"
        video_audio.export(temp_video_audio, format="wav")

        recognizer = sr.Recognizer()
        with sr.AudioFile(temp_video_audio) as source:
            audio_content = recognizer.record(source)
            transcription = recognizer.recognize_google(audio_content, language="pt-BR")
        return transcription

    except Exception as e:
        logger.error(f"[Worker] Erro ao transcrever vídeo local: {e}")
        return ""

def analyze_image_local(file_path: str) -> str:
    """
    Versão local da análise de imagem, usando Google Vision,
    mas lendo diretamente de um arquivo em disco.
    """
    try:
        from google.cloud import vision
        from google.oauth2 import service_account

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
        logger.error(f"[Worker] Erro ao processar imagem local com Google Vision: {e}")
        return "Falha ao analisar imagem no Google Vision."

def calc_eta(amount, unit, base_date=None):
    """
    Calcula a data/hora para execução da tarefa, considerando UTC caso não seja fornecida data base.
    """
    if base_date is None:
        base_date = datetime.utcnow()
    elif isinstance(base_date, str):
        base_date = datetime.fromisoformat(base_date)

    if unit == "days":
        return base_date + timedelta(days=amount)
    elif unit == "hours":
        return base_date + timedelta(hours=amount)
    elif unit == "minutes":
        return base_date + timedelta(minutes=amount)

    return base_date

# >>> NOVO HELPER PARA AGENDAR PRÓXIMO PASSO <<<
def _schedule_next_followup_step(
    db,
    lead_id,
    company_id,
    sequence_id,
    current_step_number,
    execution_trace_id,
    operational_epoch=None,
):
    """
    Helper function to check and schedule the next step in a follow-up sequence.
    Can be called after successful execution OR when skipping a completed step.
    """
    from datetime import datetime
    from pytz import timezone
    from sqlalchemy import text
    from datetime import timedelta
    import logging

    logger = logging.getLogger(__name__)

    logger.info(f"[TASK:{execution_trace_id}] Verificando agendamento do próximo passo (APÓS SKIPPING/SUCCESS)")
    next_step = db.execute(
        text("""
            SELECT id, send_after, send_after_unit
            FROM follow_up_steps
            WHERE follow_up_sequence_id = :seq_id
              AND step_number = :n_step
            LIMIT 1
        """),
        {"seq_id": sequence_id, "n_step": current_step_number + 1}
    ).fetchone()

    if next_step:
        logger.info(f"[TASK:{execution_trace_id}] Próximo passo encontrado: step_number={current_step_number+1}, id={next_step.id}, atraso={next_step.send_after} {next_step.send_after_unit}")
        next_step_exists = db.execute(
            text("""
                SELECT 1 FROM follow_up_executions
                WHERE lead_id = :lead_id
                  AND follow_up_sequence_id = :seq_id
                  AND follow_up_step_id = :step_id
                LIMIT 1
            """),
            {
                "lead_id": lead_id,
                "seq_id": sequence_id,
                "step_id": next_step.id
            }
        ).fetchone()

        if next_step_exists:
            logger.info(
                f"[TASK:{execution_trace_id}] Já existe registro para o passo "
                f"(step_number={current_step_number+1}) (id={next_step.id}). Não reagendando."
            )
        else:
            sp_tz = timezone('America/Sao_Paulo')
            base_now = datetime.utcnow().replace(tzinfo=timezone('UTC')).astimezone(sp_tz)
            logger.info(f"[TASK:{execution_trace_id}] Calculando ETA a partir de {base_now.isoformat()}")

            if next_step.send_after_unit == "minutes":
                eta = base_now + timedelta(minutes=next_step.send_after)
            elif next_step.send_after_unit == "hours":
                eta = base_now + timedelta(hours=next_step.send_after)
            elif next_step.send_after_unit == "days":
                eta = base_now + timedelta(days=next_step.send_after)
            else:
                eta = base_now

            logger.info(f"[TASK:{execution_trace_id}] ETA calculado: {eta.isoformat()}")

            try:
                logger.info(f"[TASK:{execution_trace_id}] Registrando próximo passo no banco de dados")
                db.execute(
                    text("""
                        INSERT INTO follow_up_executions
                            (lead_id, company_id, follow_up_sequence_id, follow_up_step_id,
                             step_number, status, scheduled_for)
                        VALUES
                            (:lead_id, :company_id, :seq_id, :step_id,
                             :step_number, 'SCHEDULED', :scheduled_for)
                        ON CONFLICT (lead_id, follow_up_sequence_id, follow_up_step_id)
                        DO UPDATE SET
                            status = 'SCHEDULED',
                            scheduled_for = EXCLUDED.scheduled_for,
                            updated_at = now()
                    """),
                    {
                        "lead_id": lead_id,
                        "company_id": company_id,
                        "seq_id": sequence_id,
                        "step_id": next_step.id,
                        "step_number": current_step_number + 1,
                        "scheduled_for": eta
                    }
                )
                db.commit()

                eta_utc = eta.astimezone(timezone('UTC'))
                logger.info(f"[TASK:{execution_trace_id}] Agendando Celery task para {eta_utc.isoformat()}")

                enviar_passo_followup.apply_async(
                    args=[
                        lead_id,
                        current_step_number + 1,
                        sequence_id,
                        sequence_id,
                        operational_epoch,
                    ],
                    eta=eta_utc
                )
            except Exception as e:
                logger.error(f"[TASK:{execution_trace_id}] Erro ao agendar próximo passo: {e}")
    else:
         logger.info(f"[TASK:{execution_trace_id}] Nenhum próximo passo encontrado (Fim da sequência).")


def get_last_followup_step(lead_id: int) -> dict:
    """
    Recupera informações do último step de follow-up enviado para um lead
    Retorna dict com: {
        "step_number": int,
        "timestamp": datetime,
        "sequence_id": int
    } ou None se não houver registro
    """
    try:
        key = f"followup:last_step:{lead_id}"
        data = redis_client.get(key)
        if data:
            info = json.loads(data)
            info["timestamp"] = datetime.fromisoformat(info["timestamp"])
            return info
        return None
    except Exception as e:
        logger.error(f"[Worker] Erro ao obter último step do follow-up: {str(e)}")
        return None

def set_last_followup_step(lead_id: int, step_number: int, sequence_id: int) -> None:
    """
    Armazena informações do último step de follow-up enviado
    """
    try:
        key = f"followup:last_step:{lead_id}"
        data = {
            "step_number": step_number,
            "timestamp": datetime.utcnow().isoformat(),
            "sequence_id": sequence_id
        }
        redis_client.set(key, json.dumps(data))
        redis_client.expire(key, 60 * 60 * 24 * 30)  # Expira em 30 dias
    except Exception as e:
        logger.error(f"[Worker] Erro ao salvar último step do follow-up: {str(e)}")

def clear_followup_steps(lead_id: int) -> None:
    """
    Limpa o registro de steps para um lead (útil quando precisar reiniciar)
    """
    try:
        key = f"followup:last_step:{lead_id}"
        redis_client.delete(key)
    except Exception as e:
        logger.error(f"[Worker] Erro ao limpar steps do follow-up: {str(e)}")

@app.task
@check_flow_control('follow_up')
def enviar_passo_followup(
    lead_id: int,
    step_number: int,
    expected_sequence_id: int = None,
    sequence_id: int = None,
    operational_epoch: int | None = None,
):
    """
    Task para enviar o passo 'step_number' do follow-up ao lead 'lead_id',
    com controle de execução via tabela follow_up_executions.

    expected_sequence_id: Se fornecido, valida se o lead ainda está nesta sequência.
    sequence_id: ID da sequência atual (usado para lock único).
    """
    import time
    import base64
    import asyncio
    import os
    from uuid import uuid4
    from datetime import datetime, timedelta
    from pytz import timezone
    from sqlalchemy import text

    from backend.db import SessionLocal
    from backend.ws_manager import manager
    from backend.integrations.whatsapp_provider import (
        send_text,
        send_image,
        send_audio,
        send_video
    )
    from backend.prompt.media.audio_processing import transcribe_audio, transcribe_video
    from backend.prompt.media.image_analysis import analyze_image_with_google_vision
    from backend.prompt.memory import memory_manager
    from .celery_app import app
    import redis
    import logging

    # >>> Config de logs e Redis <<<
    logger = logging.getLogger(__name__)
    redis_client = redis.Redis(host='localhost', port=6379, db=0)

    # Criar diretório para logs detalhados de vídeo se não existir
    VIDEO_LOG_DIR = str(RUNTIME_LOG_DIR / "video-logs")
    os.makedirs(VIDEO_LOG_DIR, exist_ok=True)

    # Gerar ID único para esta execução (para rastreamento nos logs)
    execution_trace_id = f"{lead_id}_{step_number}_{uuid4().hex[:8]}"

    logger.info(f"[TASK:{execution_trace_id}] Inicializando task.")

    # >>> Versões locais para transcrever/analisar arquivos <<<
    def transcribe_audio_local(file_path: str) -> str:
        """Versão local da transcrição de áudio."""
        try:
            from pydub import AudioSegment
            import speech_recognition as sr

            # Converte para WAV
            audio = AudioSegment.from_file(file_path)
            wav_path = file_path + ".wav"
            audio.export(wav_path, format="wav")

            recognizer = sr.Recognizer()
            with sr.AudioFile(wav_path) as source:
                audio_data = recognizer.record(source)
                text = recognizer.recognize_google(audio_data, language="pt-BR")

            # Limpa arquivo temporário
            if os.path.exists(wav_path):
                os.remove(wav_path)

            return text
        except Exception as e:
            logger.error(f"[Worker] Erro ao transcrever áudio local: {e}")
            return ""

    def transcribe_video_local(file_path: str) -> str:
        """Versão local da transcrição de vídeo (extrai áudio e transcreve)."""
        try:
            from moviepy.editor import VideoFileClip

            # Extrai áudio
            video = VideoFileClip(file_path)
            audio_path = file_path + ".mp3"
            video.audio.write_audiofile(audio_path)
            video.close()

            # Transcreve áudio
            text = transcribe_audio_local(audio_path)

            # Limpa arquivo temporário
            if os.path.exists(audio_path):
                os.remove(audio_path)

            return text
        except Exception as e:
            logger.error(f"[Worker] Erro ao transcrever vídeo local: {e}")
            return ""

    def analyze_image_local(file_path: str) -> str:
        """Versão local da análise de imagem usando Google Vision."""
        try:
            from google.cloud import vision
            from google.oauth2 import service_account

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
            logger.error(f"[Worker] Erro ao processar imagem local com Google Vision: {e}")
            return "Falha ao analisar imagem no Google Vision."

    # Função auxiliar para escrever logs detalhados de vídeo
    def log_video_details(msg_id, file_path, action, details):
        """Escreve logs detalhados de vídeo em um arquivo separado."""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_file_path = os.path.join(VIDEO_LOG_DIR, f"video_log_{lead_id}_{execution_trace_id}.txt")

            with open(log_file_path, "a") as f:
                f.write(f"[{timestamp}] {action}: msg_id={msg_id}, file_path={file_path}\n")
                f.write(f"[{timestamp}] Detalhes: {details}\n\n")

            logger.info(f"[VIDEO:{execution_trace_id}] Log detalhado gravado em {log_file_path}")
        except Exception as e:
            logger.error(f"[VIDEO:{execution_trace_id}] Erro ao gravar log detalhado: {str(e)}")

    # ----------------------------------------------------------------------------
    # A função principal
    # ----------------------------------------------------------------------------

    if sequence_id:
        lock_key = f"followup_lock:{lead_id}:{sequence_id}:{step_number}"
    else:
        lock_key = f"followup_lock:{lead_id}:{step_number}"

    execution_lock = False
    db = SessionLocal()

    try:
        # 1) TENTATIVA DE LOCK
        logger.info(f"[TASK:{execution_trace_id}] Iniciando enviar_passo_followup para lead_id={lead_id}, step_number={step_number}")

        # Verificar se já existe lock
        existing_lock = redis_client.get(lock_key)
        if existing_lock:
            logger.info(f"[LOCK:{execution_trace_id}] Lock existente detectado para {lock_key}: {existing_lock}")

        # Tenta adquirir lock
        lock_acquired = redis_client.set(lock_key, execution_trace_id, nx=True, ex=300)  # 5 min de lock

        if not lock_acquired:
            current_lock = redis_client.get(lock_key)
            logger.info(f"[LOCK:{execution_trace_id}] Outra task já está processando lead={lead_id}, step={step_number}. Lock atual: {current_lock}. Saindo.")
            return

        logger.info(f"[LOCK:{execution_trace_id}] Lock obtido com sucesso: {lock_key}={execution_trace_id}")
        execution_lock = True

        # 2) VERIFICA SE O LEAD JÁ AGENDOU CONSULTA
        row_agendamento = db.execute(
            text("SELECT 1 FROM agendamentos WHERE lead_id = :lead_id LIMIT 1"),
            {"lead_id": lead_id}
        ).fetchone()
        if row_agendamento:
            logger.info(f"[TASK:{execution_trace_id}] Lead {lead_id} já possui agendamento. Encerrando.")
            return

        # 3) OBTÉM DADOS DO LEAD
        lead_row = db.execute(
            text("""
                SELECT follow_up_sequence_id, data_entrada, company_id, name, phone
                FROM leads
                WHERE id = :lead_id
            """),
            {"lead_id": lead_id}
        ).fetchone()
        if not lead_row or not lead_row.follow_up_sequence_id:
            logger.warning(f"[TASK:{execution_trace_id}] Lead {lead_id} sem follow_up_sequence_id. Encerrando.")
            return

        sequence_id = lead_row.follow_up_sequence_id
        data_entrada = lead_row.data_entrada
        company_id = lead_row.company_id
        from backend.services.company_access_control import validate_company_job_epoch
        if not validate_company_job_epoch(db, int(company_id), operational_epoch):
            db.execute(
                text("""
                    UPDATE follow_up_executions
                       SET status = 'CANCELED',
                           error_message = 'company_access_suspended',
                           updated_at = now()
                     WHERE lead_id = :lead_id
                       AND status IN ('SCHEDULED', 'PROCESSING')
                """),
                {"lead_id": lead_id},
            )
            db.commit()
            return
        lead_name = lead_row.name or ""
        phone = lead_row.phone

        # >>> FIX: Normalizar telefone (garantir formato BR 55...) <<<
        if phone:
            # Remover caracteres não numéricos
            clean_phone = ''.join(filter(str.isdigit, str(phone)))
            # Se tiver 10 ou 11 dígitos (com DDD mas sem DDI), adiciona 55
            if len(clean_phone) in [10, 11]:
                phone = '55' + clean_phone
            else:
                phone = clean_phone

        # Extrair primeiro nome para variável {first_name}
        first_name = lead_name.split()[0] if lead_name.strip() else ""
        logger.info(f"[TASK:{execution_trace_id}] Lead {lead_id} -> sequence_id={sequence_id}, data_entrada={data_entrada}, company_id={company_id}, first_name={first_name}")

        # 3.1) VALIDAÇÃO DE SEQUÊNCIA ESPERADA (Evita tarefas zumbis)
        if expected_sequence_id and expected_sequence_id != sequence_id:
            logger.warning(f"[TASK:{execution_trace_id}] Sequência esperada ({expected_sequence_id}) difere da atual ({sequence_id}). Abortando tarefa antiga.")
            return

        # 4) VERIFICA STEP ATUAL
        step_data = db.execute(
            text("""
                SELECT id, send_after, send_after_unit
                FROM follow_up_steps
                WHERE follow_up_sequence_id = :seq_id
                  AND step_number = :step_number
                LIMIT 1
            """),
            {"seq_id": sequence_id, "step_number": step_number}
        ).fetchone()
        if not step_data:
            logger.info(f"[TASK:{execution_trace_id}] Não há step_number={step_number} para sequence_id={sequence_id}. Encerrando.")
            return

        step_id = step_data.id
        logger.info(f"[TASK:{execution_trace_id}] Step encontrado: id={step_id}, send_after={step_data.send_after} {step_data.send_after_unit}")

        # 5) VERIFICA STATUS JÁ EXISTENTE
        existing_execution = db.execute(
            text("""
                SELECT id, status
                FROM follow_up_executions
                WHERE lead_id = :lead_id
                  AND follow_up_sequence_id = :seq_id
                  AND follow_up_step_id = :step_id
                LIMIT 1
            """),
            {
                "lead_id": lead_id,
                "seq_id": sequence_id,
                "step_id": step_id
            }
        ).fetchone()

        # CANCELED remains terminal across company reactivation. A delayed
        # broker message must never reactivate it after access is restored.
        if existing_execution and existing_execution.status == "CANCELED":
            logger.info(
                f"[TASK:{execution_trace_id}] Passo {step_number} cancelado; "
                "não será reativado."
            )
            return
        # Se achar e estiver SUCCESS ou PROCESSING => não reexecuta
        if existing_execution and existing_execution.status in ('SUCCESS', 'PROCESSING'):
            logger.info(f"[TASK:{execution_trace_id}] Passo {step_number} já está em '{existing_execution.status}'. Tentando agendar próximo passo (Skip and Continue).")
            # >>> SKIP AND CONTINUE <<<
            _schedule_next_followup_step(
                db,
                lead_id,
                company_id,
                sequence_id,
                step_number,
                execution_trace_id,
                operational_epoch,
            )
            return
        elif existing_execution and existing_execution.status in ('SCHEDULED', 'FAILED'):
            # Tenta atualizar para PROCESSING
            try:
                db.execute(
                    text("""
                        UPDATE follow_up_executions
                        SET status = 'PROCESSING',
                            updated_at = now()
                        WHERE id = :id
                    """),
                    {"id": existing_execution.id}
                )
                db.commit()
                execution_id = existing_execution.id
                logger.info(f"[TASK:{execution_trace_id}] Atualizando execução existente id={execution_id} para PROCESSING.")
            except Exception as e:
                logger.error(f"[TASK:{execution_trace_id}] Erro ao atualizar execução existente: {str(e)}")
                # Continua, mas não impede a execução
        else:
            # Se não existe, cria um registro PROCESSING
            try:
                res = db.execute(
                    text("""
                        INSERT INTO follow_up_executions
                            (lead_id, company_id, follow_up_sequence_id, follow_up_step_id,
                             step_number, status)
                        VALUES
                            (:lead_id, :company_id, :seq_id, :step_id,
                             :step_number, 'PROCESSING')
                        ON CONFLICT (lead_id, follow_up_sequence_id, follow_up_step_id)
                        DO UPDATE SET
                            status = 'PROCESSING',
                            updated_at = now()
                        RETURNING id
                    """),
                    {
                        "lead_id": lead_id,
                        "company_id": company_id,
                        "seq_id": sequence_id,
                        "step_id": step_id,
                        "step_number": step_number
                    }
                )
                row = res.fetchone()
                db.commit()
                execution_id = row.id if row else None
                logger.info(f"[TASK:{execution_trace_id}] Inserido/atualizado PROCESSING (id={execution_id}).")
            except Exception as e:
                logger.error(f"[TASK:{execution_trace_id}] Erro ao inserir PROCESSING: {str(e)}")
                # Tenta buscar se existe
                existing_rec = db.execute(
                    text("""
                        SELECT id FROM follow_up_executions
                        WHERE lead_id = :lead_id
                          AND follow_up_sequence_id = :seq_id
                          AND follow_up_step_id = :step_id
                        LIMIT 1
                    """),
                    {
                        "lead_id": lead_id,
                        "seq_id": sequence_id,
                        "step_id": step_id
                    }
                ).fetchone()
                execution_id = existing_rec.id if existing_rec else None
                if existing_rec:
                    logger.info(f"[TASK:{execution_trace_id}] Usando registro existente id={execution_id}")
                else:
                    logger.error(f"[TASK:{execution_trace_id}] Não foi possível obter um ID de execução. Encerrando.")
                    return



        # 6) BUSCA CREDENCIAIS (Z-API ou WAHA)
        company_data = db.execute(
            text("SELECT zapi_instance_id, zapi_token, waha_session_name, waha_enabled FROM companies WHERE id = :cid"),
            {"cid": company_id}
        ).fetchone()

        has_zapi = company_data and company_data.zapi_instance_id and company_data.zapi_token
        has_waha = company_data and company_data.waha_enabled and company_data.waha_session_name

        if not has_zapi and not has_waha:
            logger.warning(f"[TASK:{execution_trace_id}] Empresa {company_id} sem credenciais Z-API nem WAHA. Encerrando.")
            if 'execution_id' in locals() and execution_id:
                db.execute(
                    text("""
                        UPDATE follow_up_executions
                        SET status = 'FAILED',
                        error_message = 'Falta credenciais (Z-API/WAHA)',
                        updated_at = CURRENT_TIMESTAMP
                        WHERE id = :exec_id
                    """),
                    {"exec_id": execution_id}
                )
                db.commit()
            return

        # Extract credentials
        zapi_instance = company_data.zapi_instance_id if company_data else None
        zapi_token = company_data.zapi_token if company_data else None
        waha_session = company_data.waha_session_name if company_data else None
        use_waha = has_waha

        # Aliases para compatibilidade com código legado (send_call)
        instance_id = zapi_instance
        instance_token = zapi_token

        sp_tz = timezone('America/Sao_Paulo')
        base_date = datetime.utcnow().replace(tzinfo=timezone('UTC')).astimezone(sp_tz)
        logger.info(f"[TASK:{execution_trace_id}] Data base para agendamento: {base_date.isoformat()}")

        # 7) AJUSTA base_date SE É O 1º PASSO
        if step_number == 1:
            from datetime import datetime as dt_
            if isinstance(data_entrada, dt_):
                # Se já tem timezone, converte. Se não, assume UTC (banco) e converte para SP.
                data_entrada_dt = data_entrada.astimezone(sp_tz) if data_entrada.tzinfo else data_entrada.replace(tzinfo=timezone('UTC')).astimezone(sp_tz)
            else:
                data_entrada_dt = datetime.strptime(str(data_entrada), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone('UTC')).astimezone(sp_tz)

            if base_date <= data_entrada_dt + timedelta(seconds=30):
                base_date = data_entrada_dt
                logger.info(f"[TASK:{execution_trace_id}] Primeira execução do passo 1 -> usando data_entrada: {base_date.isoformat()}")
            else:
                logger.info(f"[TASK:{execution_trace_id}] Reexecução do passo 1 -> usando horário atual: {base_date.isoformat()}")

        # 8) CHECA schedule_config
        row_sched_config = db.execute(
            text("""
                SELECT schedule_data
                FROM follow_up_schedule_configs
                WHERE company_id = :company_id
                  AND follow_up_sequence_id = :sequence_id
                LIMIT 1
            """),
            {"company_id": company_id, "sequence_id": sequence_id}
        ).fetchone()

        def schedule_for(new_datetime):
            """Auxiliar: seta status=SCHEDULED e faz apply_async(eta=...)."""
            db.execute(
                text("""
                    INSERT INTO follow_up_executions
                        (lead_id, company_id, follow_up_sequence_id, follow_up_step_id,
                         step_number, status, scheduled_for)
                    VALUES
                        (:lead_id, :company_id, :seq_id, :step_id,
                         :step_number, 'SCHEDULED', :scheduled_for)
                    ON CONFLICT (lead_id, follow_up_sequence_id, follow_up_step_id)
                    DO UPDATE SET
                        status = 'SCHEDULED',
                        scheduled_for = EXCLUDED.scheduled_for,
                        updated_at = now()
                """),
                {
                    "lead_id": lead_id,
                    "company_id": company_id,
                    "seq_id": sequence_id,
                    "step_id": step_id,
                    "step_number": step_number,
                    "scheduled_for": new_datetime
                }
            )
            db.commit()

            eta_utc = new_datetime.astimezone(timezone('UTC'))
            enviar_passo_followup.apply_async(
                args=[
                    lead_id,
                    step_number,
                    sequence_id,
                    sequence_id,
                    operational_epoch,
                ],
                eta=eta_utc
            )
            logger.info(f"[TASK:{execution_trace_id}] Reagendado para {eta_utc.isoformat()}")

        if row_sched_config and row_sched_config.schedule_data:
            try:
                schedule_data_json = row_sched_config.schedule_data
                day_of_week = base_date.strftime('%A').lower()
                day_config = schedule_data_json.get(day_of_week)

                logger.info(f"[TASK:{execution_trace_id}] Verificando configuração de agenda para {day_of_week}")

                if day_config is None:
                    logger.info(f"[TASK:{execution_trace_id}] Sem configuração para o dia {day_of_week}")
                    existing_scheduled = db.execute(text("""
                        SELECT 1 FROM follow_up_executions
                        WHERE lead_id = :lead_id
                          AND follow_up_sequence_id = :seq_id
                          AND follow_up_step_id = :step_id
                          AND status = 'SCHEDULED'
                    """), {
                        "lead_id": lead_id,
                        "seq_id": sequence_id,
                        "step_id": step_id
                    }).fetchone()
                    if existing_scheduled:
                        logger.info(f"[TASK:{execution_trace_id}] Já existe SCHEDULED para este dia (sem config). Não reagendando.")
                        return

                    new_date = (base_date + timedelta(days=1)).replace(hour=8, minute=0, second=0)
                    logger.info(f"[TASK:{execution_trace_id}] Reagendando para dia seguinte às 8h: {new_date.isoformat()}")
                    schedule_for(new_date)
                    return

                start_str = day_config.get('start', '08:00')
                end_str = day_config.get('end', '18:00')
                start_hour, start_minute = map(int, start_str.split(':'))
                end_hour, end_minute = map(int, end_str.split(':'))

                logger.info(f"[TASK:{execution_trace_id}] Horário configurado: {start_str} - {end_str}")

                start_time = base_date.replace(hour=start_hour, minute=start_minute, second=0)
                end_time = base_date.replace(hour=end_hour, minute=end_minute, second=0)

                if base_date < start_time:
                    logger.info(f"[TASK:{execution_trace_id}] Horário atual ({base_date.isoformat()}) anterior ao início do expediente ({start_time.isoformat()})")
                    existing_scheduled = db.execute(text("""
                        SELECT 1 FROM follow_up_executions
                        WHERE lead_id = :lead_id
                          AND follow_up_sequence_id = :seq_id
                          AND follow_up_step_id = :step_id
                          AND status = 'SCHEDULED'
                    """), {
                        "lead_id": lead_id,
                        "seq_id": sequence_id,
                        "step_id": step_id
                    }).fetchone()
                    if existing_scheduled:
                        logger.info(f"[TASK:{execution_trace_id}] Já existe SCHEDULED. Não reagendando.")
                        return
                    schedule_for(start_time)
                    return
                elif base_date > end_time:
                    logger.info(f"[TASK:{execution_trace_id}] Horário atual ({base_date.isoformat()}) posterior ao fim do expediente ({end_time.isoformat()})")
                    existing_scheduled = db.execute(text("""
                        SELECT 1 FROM follow_up_executions
                        WHERE lead_id = :lead_id
                          AND follow_up_sequence_id = :seq_id
                          AND follow_up_step_id = :step_id
                          AND status = 'SCHEDULED'
                    """), {
                        "lead_id": lead_id,
                        "seq_id": sequence_id,
                        "step_id": step_id
                    }).fetchone()
                    if existing_scheduled:
                        logger.info(f"[TASK:{execution_trace_id}] Já existe SCHEDULED. Não reagendando.")
                        return
                    tomorrow = base_date + timedelta(days=1)
                    new_date = tomorrow.replace(hour=start_hour, minute=start_minute, second=0)
                    logger.info(f"[TASK:{execution_trace_id}] Reagendando para amanhã no início do expediente: {new_date.isoformat()}")
                    schedule_for(new_date)
                    return

            except Exception as e:
                logger.error(f"[TASK:{execution_trace_id}] Erro ao interpretar schedule_data: {str(e)}")
                # Se der erro, apenas segue para envio imediato

        # 9) ENVIA AS MENSAGENS
        success = True
        error_msg = None
        execution_id_local = execution_id if 'execution_id' in locals() else None

        try:
            messages = db.execute(
                text("""
                    SELECT m.id, m.type, m.content, mf.file_path, mf.mime_type
                    FROM follow_up_messages m
                    LEFT JOIN media_files mf ON mf.relative_path = m.content
                    WHERE m.follow_up_step_id = :step_id
                    ORDER BY m.id ASC
                """),
                {"step_id": step_id}
            ).fetchall()

            logger.info(f"[TASK:{execution_trace_id}] Encontradas {len(messages) if messages else 0} mensagens para enviar")

            # Se não há mensagens, marcamos SUCCESS e seguimos
            if not messages:
                logger.warning(f"[TASK:{execution_trace_id}] Nenhuma mensagem para step_id={step_id}. Marcando SUCCESS e seguindo.")
                db.execute(
                    text("""
                        UPDATE follow_up_executions
                        SET status = 'SUCCESS',
                            error_message = 'No messages',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = :exec_id
                    """),
                    {"exec_id": execution_id_local}
                )
                db.commit()
                schedule_next_step = True
            else:
                # Enviamos as mensagens
                schedule_next_step = True
                for msg in messages:
                    try:
                        logger.info(f"[TASK:{execution_trace_id}] Processando mensagem id={msg.id}, type={msg.type}")
                        response = None
                        message_content = msg.content

                        if msg.type == "text":
                            # Substituir variáveis na mensagem
                            final_text = msg.content.replace("{first_name}", first_name)
                            final_text = final_text.replace("{nome}", first_name)  # Suporte também para {nome}
                            message_content = final_text

                            logger.info(f"[TASK:{execution_trace_id}] Enviando texto: {final_text[:50]}..." if len(final_text) > 50 else f"[TASK:{execution_trace_id}] Enviando texto: {final_text}")

                            # USAR PROVIDER UNIFICADO (WAHA/Z-API)
                            # O provider lida com:
                            # 1. Normalização de telefone (checkNumberStatus para WAHA)
                            # 2. Persistência de mensagem (messages table)
                            # 3. Escolha do canal correto
                            response = send_text(
                                company_id=company_id,
                                phone=phone,
                                message=final_text,
                                db=db,
                                human_mode=True  # Follow-ups aparecem como enviados por humano
                            )

                        elif msg.type in ["image", "audio", "video"] and msg.file_path:
                            if not os.path.exists(msg.file_path):
                                logger.error(f"[TASK:{execution_trace_id}] Arquivo não encontrado: {msg.file_path}")
                                success = False
                                error_msg = f"Arquivo não encontrado: {msg.file_path}"
                                break

                            # Log básico
                            file_size = os.path.getsize(msg.file_path)
                            logger.info(f"[TASK:{execution_trace_id}] Enviando {msg.type}: {msg.file_path} ({file_size/1024/1024:.2f} MB)")

                            if msg.type == "video":
                                # Log específico para vídeo
                                log_video_details(msg.id, msg.file_path, "INIT", f"Size: {file_size/1024/1024:.2f} MB")

                            # USAR PROVIDER UNIFICADO
                            # Passamos o path do arquivo e o provider decide:
                            # - WAHA: Gera URL pública (sem ler bytes = rápido)
                            # - Z-API: Lê bytes e converte base64 (se necessário)
                            try:
                                if msg.type == "image":
                                    response = send_image(
                                        company_id=company_id,
                                        phone=phone,
                                        image_path=msg.file_path,
                                        db=db
                                    )
                                elif msg.type == "audio":
                                    response = send_audio(
                                        company_id=company_id,
                                        phone=phone,
                                        audio_path=msg.file_path,
                                        db=db
                                    )
                                elif msg.type == "video":
                                    response = send_video(
                                        company_id=company_id,
                                        phone=phone,
                                        video_path=msg.file_path,
                                        db=db
                                    )
                                    log_video_details(msg.id, msg.file_path, "SUCCESS", "Vídeo enviado")

                            except Exception as e:
                                if msg.type == "video":
                                    log_video_details(msg.id, msg.file_path, "ERROR", str(e))
                                raise e


                        elif msg.type == "call":
                            logger.info(f"[TASK:{execution_trace_id}] Fazendo ligação de {msg.content}s para {phone}")
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
                                message_content = f"Ligação de {duration}s"

                                logger.info(f"[TASK:{execution_trace_id}] Ligação de {duration}s enviada com sucesso para {phone}")

                            except Exception as call_error:
                                logger.error(f"[TASK:{execution_trace_id}] Erro ao fazer ligação: {str(call_error)}")
                                success = False
                                error_msg = f"Erro na ligação: {str(call_error)}"
                                break

                        # Se enviou...
                        if response:
                            logger.info(f"[TASK:{execution_trace_id}] Mensagem enviada com sucesso para {phone}")


                            # Faz a transcrição/análise
                            logger.info(f"[TASK:{execution_trace_id}] Iniciando transcrição/análise de mídia")
                            text_to_history = "[Mídia sem análise]"
                            try:
                                if msg.type == "text":
                                    text_to_history = message_content
                                elif msg.type == "audio" and msg.file_path:
                                    logger.info(f"[TASK:{execution_trace_id}] Transcrevendo áudio: {msg.file_path}")
                                    text_to_history = transcribe_audio_local(msg.file_path) or "[Áudio sem transcrição]"
                                elif msg.type == "video" and msg.file_path:
                                    logger.info(f"[TASK:{execution_trace_id}] Transcrevendo vídeo: {msg.file_path}")
                                    text_to_history = transcribe_video_local(msg.file_path) or "[Vídeo sem transcrição]"
                                elif msg.type == "image" and msg.file_path:
                                    logger.info(f"[TASK:{execution_trace_id}] Analisando imagem: {msg.file_path}")
                                    text_to_history = analyze_image_local(msg.file_path) or "[Imagem sem análise]"

                                logger.info(f"[TASK:{execution_trace_id}] Resultado da transcrição/análise: {text_to_history[:100]}..." if len(text_to_history) > 100 else f"[TASK:{execution_trace_id}] Resultado da transcrição/análise: {text_to_history}")
                            except Exception as e_tr:
                                logger.error(f"[TASK:{execution_trace_id}] Erro na transcrição/análise: {str(e_tr)}")

                            # Salva no chatmemory
                            logger.info(f"[TASK:{execution_trace_id}] Salvando na memória de chat")
                            memory_manager.append_message_to_chat_file(
                                company_id=company_id,
                                contact_phone=phone,
                                from_me=True,
                                content=text_to_history
                            )

                            # Envia via WebSocket
                            try:
                                logger.info(f"[TASK:{execution_trace_id}] Enviando notificação via WebSocket")
                                ws_payload = {
                                    "type": msg.type,
                                    "content": message_content,
                                    "phone": phone,
                                    "senderName": "Follow Up",
                                    "photo": "",
                                    "fromMe": True,
                                    "messageId": f"worker_{uuid4()}",
                                    "momment": datetime.utcnow().isoformat()
                                }
                                try:
                                    if hasattr(manager, 'broadcast_to_company'):
                                        asyncio.run(manager.broadcast_to_company(company_id, ws_payload))
                                    else:
                                        asyncio.run(manager.broadcast(ws_payload))
                                except TypeError:
                                    asyncio.run(manager.broadcast(json.dumps(ws_payload)))
                                logger.info(f"[TASK:{execution_trace_id}] Notificação WebSocket enviada com sucesso")
                            except Exception as ws_error:
                                logger.warning(f"[TASK:{execution_trace_id}] Erro WS (não crítico): {str(ws_error)}")

                            time.sleep(1)
                    except Exception as e_msg:
                        logger.error(f"[TASK:{execution_trace_id}] Erro ao enviar msg_id={msg.id}: {str(e_msg)}")
                        if msg.type == "video":
                            log_video_details(msg.id, msg.file_path if hasattr(msg, 'file_path') else "desconhecido",
                                             "ERROR", f"Exceção: {type(e_msg).__name__}: {str(e_msg)}")
                        success = False
                        error_msg = str(e_msg)
                        break

                # Marca status final
                final_status = 'SUCCESS' if success else 'FAILED'
                logger.info(f"[TASK:{execution_trace_id}] Finalizando com status: {final_status}")
                db.execute(
                    text("""
                        UPDATE follow_up_executions
                        SET status = :status,
                            error_message = :error_msg,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = :exec_id
                    """),
                    {
                        "status": final_status,
                        "error_msg": error_msg,
                        "exec_id": execution_id_local
                    }
                )
                db.commit()

                if not success:
                    schedule_next_step = False
                    logger.error(f"[TASK:{execution_trace_id}] Falha ao enviar mensagens do passo {step_number}. Encerrando.")

            # 10) AGENDAR PRÓXIMO PASSO (se tudo ok)
            if schedule_next_step:
                _schedule_next_followup_step(
                    db,
                    lead_id,
                    company_id,
                    sequence_id,
                    step_number,
                    execution_trace_id,
                    operational_epoch,
                )

        except Exception as e_proc:
            logger.error(f"[TASK:{execution_trace_id}] Erro ao processar mensagens: {str(e_proc)}")
            if 'execution_id_local' in locals() and execution_id_local:
                db.execute(
                    text("""
                        UPDATE follow_up_executions
                        SET status = 'FAILED',
                            error_message = :error_msg,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = :exec_id
                    """),
                    {
                        "error_msg": str(e_proc),
                        "exec_id": execution_id_local
                    }
                )
                db.commit()
            raise

    except Exception as e_main:
        logger.error(f"[TASK:{execution_trace_id}] Erro geral ao enviar follow-up para lead {lead_id}, passo {step_number}: {str(e_main)}")
        raise
    finally:
        # LIBERA LOCK E FECHA DB
        if execution_lock:
            try:
                # Verificar se o lock ainda é nosso
                current_lock = redis_client.get(lock_key)
                if current_lock == execution_trace_id:
                    logger.info(f"[LOCK:{execution_trace_id}] Liberando lock: {lock_key}")
                    redis_client.delete(lock_key)
                    logger.info(f"[LOCK:{execution_trace_id}] Lock liberado com sucesso")
                else:
                    logger.warning(f"[LOCK:{execution_trace_id}] Lock atual ({current_lock}) difere do nosso ({execution_trace_id}). Não liberando.")
            except Exception as e_unlock:
                logger.error(f"[LOCK:{execution_trace_id}] Erro ao liberar lock: {str(e_unlock)}")
        db.close()
        logger.info(f"[TASK:{execution_trace_id}] Conexão com o banco de dados fechada")
