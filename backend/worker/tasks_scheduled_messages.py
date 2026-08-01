import logging
import os
import base64
import json
import redis
import uuid
from datetime import datetime
from .celery_app import app
from sqlalchemy import text
from sqlalchemy.orm import Session
from backend.db import SessionLocal
from backend.models import Message, ContactTask, ScheduledMessageExecution
from backend.runtime_settings import LOG_DIR as RUNTIME_LOG_DIR
from .flow_control import check_flow_control

# Configuração de logs
LOG_DIR = str(RUNTIME_LOG_DIR)
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "scheduled_messages.log")

logger = logging.getLogger(__name__)
file_handler = logging.FileHandler(LOG_FILE)
file_formatter = logging.Formatter('%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s')
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)
logger.setLevel(logging.INFO)

# Conexão Redis
redis_client = redis.Redis(host='localhost', port=6379, db=0)

def publish_message_to_redis(msg_type: str, content: str, phone: str, from_me: bool = True):
    """Publica mensagem no Redis para broadcast via WebSocket."""
    try:
        message = {
            "type": msg_type,
            "content": content,
            "phone": phone,
            "senderName": "Mensagem Agendada",
            "photo": "",
            "fromMe": from_me,
            "messageId": f"scheduled_{int(datetime.utcnow().timestamp() * 1000)}",
            "momment": datetime.utcnow().isoformat(),
            "caption": None
        }

        logger.info(f"[SCHED_MSG] Publicando mensagem no Redis: {json.dumps(message)}")
        redis_client.publish('chat_messages', json.dumps(message))
        logger.info("[SCHED_MSG] Mensagem publicada com sucesso no Redis")

    except Exception as e:
        logger.error(f"[SCHED_MSG] Erro ao publicar mensagem no Redis: {str(e)}", exc_info=True)

def insert_or_update_scheduled_execution(db: Session, task_id: int, contact_id: int,
                                       company_id: int, message_type: str, message_content: str,
                                       message_file_path: str = None, status: str = 'SCHEDULED',
                                       scheduled_for: datetime = None, error_message: str = None):
    """Insere ou atualiza a execução da mensagem agendada - padrão das outras tasks"""
    try:
        db.execute(
            text("""
                INSERT INTO scheduled_message_executions (
                    task_id, contact_id, company_id, message_type, message_content,
                    message_file_path, status, scheduled_for, error_message
                )
                VALUES (
                    :task_id, :contact_id, :company_id, :message_type, :message_content,
                    :message_file_path, :status, :scheduled_for, :error_message
                )
                ON CONFLICT (task_id)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    scheduled_for = EXCLUDED.scheduled_for,
                    error_message = EXCLUDED.error_message,
                    updated_at = now()
            """),
            {
                "task_id": task_id,
                "contact_id": contact_id,
                "company_id": company_id,
                "message_type": message_type,
                "message_content": message_content,
                "message_file_path": message_file_path,
                "status": status,
                "scheduled_for": scheduled_for,
                "error_message": error_message
            }
        )
        db.commit()
    except Exception as e:
        logger.error(f"[SCHED_MSG] Erro ao inserir/atualizar execução: {str(e)}")
        db.rollback()

@app.task
@check_flow_control('scheduled_message')
def enviar_mensagem_agendada(task_id: int):
    """
    Task para enviar mensagem agendada via WAHA
    Recebe o ID da task já criada no banco e executa o envio.
    """
    db = SessionLocal()
    try:
        # Buscar a task no banco
        task = db.query(ContactTask).filter(ContactTask.id == task_id).first()

        if not task:
            logger.error(f"[SCHED_MSG] Task {task_id} não encontrada")
            return

        if task.status != 'pending':
            logger.info(f"[SCHED_MSG] Task {task_id} já processada ou cancelada. Status: {task.status}")
            return
        from backend.services.company_access_control import is_company_operational
        if not is_company_operational(db, int(task.company_id)):
            task.status = "canceled"
            task.task_metadata = task.task_metadata or {}
            task.task_metadata["error"] = "company_access_suspended"
            db.commit()
            return

        # Atualizar status para in_progress
        task.status = 'in_progress'
        db.commit()

        contact_phone = task.contact.phone
        company_id = task.company_id
        message_content = task.message_content
        message_type = task.message_type or "text"

        logger.info(f"[SCHED_MSG] Iniciando envio da task {task_id} para {contact_phone} (empresa {company_id}) via WAHA")

        # Lock para evitar duplicação (usando task_id no lock)
        lock_key = f"lock:scheduled_message:task:{task_id}"
        lock_value = str(uuid.uuid4())

        if not redis_client.set(lock_key, lock_value, ex=60, nx=True):
            logger.info(f"[SCHED_MSG] Task {task_id} já em processamento (lock)")
            return

        try:
            # Buscar configuração WAHA da empresa
            company_data = db.execute(
                text("""
                    SELECT waha_session_name, waha_enabled
                    FROM companies
                    WHERE id = :company_id
                """),
                {"company_id": company_id}
            ).fetchone()

            if not company_data or not company_data.waha_session_name:
                logger.error(f"[SCHED_MSG] Empresa {company_id} sem sessão WAHA configurada")
                task.status = 'failed'
                task.task_metadata = task.task_metadata or {}
                task.task_metadata['error'] = "Empresa sem sessão WAHA configurada"
                db.commit()
                return

            waha_session = company_data.waha_session_name

            # Enviar mensagem via WAHA
            mensagem_enviada = False
            error_msg = None
            waha_response = None

            try:
                if message_type == "text":
                    from backend.integrations.waha_utils import send_text_to_waha

                    waha_response = send_text_to_waha(
                        waha_session_name=waha_session,
                        phone=contact_phone,
                        message=message_content,
                        company_id=company_id
                    )
                    logger.info(f"[SCHED_MSG] Resposta WAHA texto: {waha_response}")

                    if waha_response and (waha_response.get('id') or waha_response.get('messageId')):
                         publish_message_to_redis("text", message_content, contact_phone)
                         mensagem_enviada = True

                elif message_type == "audio":
                    from backend.integrations.waha_utils import send_audio_to_waha
                    import base64

                    logger.info(f"[SCHED_MSG] Enviando áudio via WAHA para {contact_phone}")

                    # Preparar bytes do áudio
                    # message_content deve conter base64 (com ou sem prefixo)
                    audio_b64_clean = message_content
                    if "base64," in message_content:
                        audio_b64_clean = message_content.split("base64,")[1]

                    try:
                        audio_bytes = base64.b64decode(audio_b64_clean)

                        waha_response = send_audio_to_waha(
                            waha_session_name=waha_session,
                            phone=contact_phone,
                            audio_bytes=audio_bytes,
                            company_id=company_id
                        )

                        if waha_response and (waha_response.get('id') or waha_response.get('messageId')):
                            logger.info(f"[SCHED_MSG] Áudio enviado com sucesso via WAHA")
                            publish_message_to_redis("audio", f"data:audio/ogg;base64,{audio_b64_clean}", contact_phone)
                            mensagem_enviada = True
                    except Exception as e:
                        logger.error(f"[SCHED_MSG] Erro ao decodificar/enviar áudio: {e}")
                        error_msg = f"Erro áudio: {str(e)}"

                elif message_type == "image":
                    from backend.integrations.waha_utils import send_image_to_waha
                    import base64

                    logger.info(f"[SCHED_MSG] Enviando imagem via WAHA para {contact_phone}")

                    # message_file_path pode conter o base64 ou path (assumindo base64 no content por enquanto para simplificar, ou path se implementado upload)
                    # O frontend TaskPanel envia file, mas o backend create_task salva path.
                    # Se o frontend enviar base64 no message_content (para media), usamos ele.
                    # Se for path, precisaríamos ler o arquivo.
                    # Assumindo que message_content tem o base64 ou message_file_path tem o caminho.

                    # Verificando implementação do create_task:
                    # Ele salva message_file_path. Se o arquivo foi salvo no disco, precisamos ler.

                    image_bytes = None
                    mime_type = "image/jpeg"

                    if task.message_file_path and os.path.exists(task.message_file_path):
                        with open(task.message_file_path, "rb") as f:
                            image_bytes = f.read()
                        # Tentar adivinhar mime
                        if task.message_file_path.lower().endswith(".png"):
                            mime_type = "image/png"
                    elif message_content and "base64," in message_content:
                        # Fallback se estiver no content
                        img_b64_clean = message_content.split("base64,")[1]
                        image_bytes = base64.b64decode(img_b64_clean)

                    if image_bytes:
                        waha_response = send_image_to_waha(
                            waha_session_name=waha_session,
                            phone=contact_phone,
                            image_bytes=image_bytes,
                            mime_type=mime_type,
                            company_id=company_id,
                            caption=task.description or ""
                        )
                        if waha_response and (waha_response.get('id') or waha_response.get('messageId')):
                             publish_message_to_redis("image", "Imagem enviada", contact_phone)
                             mensagem_enviada = True
                    else:
                        error_msg = "Imagem não encontrada ou inválida"

                elif message_type == "video":
                    from backend.integrations.waha_utils import send_video_to_waha
                    import base64

                    logger.info(f"[SCHED_MSG] Enviando vídeo via WAHA para {contact_phone}")

                    video_bytes = None
                    mime_type = "video/mp4"

                    if task.message_file_path and os.path.exists(task.message_file_path):
                        with open(task.message_file_path, "rb") as f:
                            video_bytes = f.read()
                    elif message_content and "base64," in message_content:
                        vid_b64_clean = message_content.split("base64,")[1]
                        video_bytes = base64.b64decode(vid_b64_clean)

                    if video_bytes:
                        waha_response = send_video_to_waha(
                            waha_session_name=waha_session,
                            phone=contact_phone,
                            video_bytes=video_bytes,
                            mime_type=mime_type,
                            company_id=company_id,
                            caption=task.description or ""
                        )
                        if waha_response and (waha_response.get('id') or waha_response.get('messageId')):
                             publish_message_to_redis("video", "Vídeo enviado", contact_phone)
                             mensagem_enviada = True
                    else:
                        error_msg = "Vídeo não encontrado ou inválido"

            except Exception as e:
                logger.error(f"[SCHED_MSG] Erro ao enviar mensagem WAHA: {str(e)}")
                error_msg = str(e)

            # Finalizar task
            if mensagem_enviada:
                task.status = 'completed'
                task.completed_at = datetime.utcnow()

                # Salvar mensagem no histórico
                try:
                    # Extrair ID do WAHA
                    waha_msg_id = waha_response.get('id') or waha_response.get('messageId') if waha_response else f"waha_{uuid.uuid4()}"

                    # Salvar no banco de mensagens
                    new_message = Message(
                        client_id=task.contact.client_id,
                        company_id=company_id,
                        contact_phone=contact_phone,
                        message_type=message_type,
                        content=message_content if message_type == "text" else (task.message_file_path or "Mídia enviada"),
                        sender_phone="ScheduledMessage",
                        sender_name="Mensagem Agendada",
                        from_me=True,
                        timestamp=datetime.utcnow(),
                        zapi_message_id=waha_msg_id # Usando coluna zapi_message_id para guardar ID do WAHA
                    )
                    db.add(new_message)
                except Exception as msg_error:
                        logger.error(f"[SCHED_MSG] Erro ao salvar mensagem no histórico: {msg_error}")

                db.commit()
                logger.info(f"[SCHED_MSG] Task {task_id} finalizada com SUCESSO via WAHA")
            else:
                task.status = 'failed'
                task.task_metadata = task.task_metadata or {}
                task.task_metadata['error'] = error_msg or "Falha no envio WAHA"
                db.commit()
                logger.info(f"[SCHED_MSG] Task {task_id} finalizada com FALHA via WAHA")

        finally:
            redis_client.delete(lock_key)

    except Exception as e:
        logger.error(f"[SCHED_MSG] Erro fatal na task {task_id}: {str(e)}", exc_info=True)
        try:
            if 'task' in locals() and task:
                 task.status = 'failed'
                 task.task_metadata = task.task_metadata or {}
                 task.task_metadata['error'] = f"Fatal error: {str(e)}"
                 db.commit()
        except:
            pass
        raise
    finally:
        try:
            db.close()
        except:
            pass
