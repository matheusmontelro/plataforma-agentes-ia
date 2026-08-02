import logging
import redis
from datetime import datetime, timedelta
from typing import List, Callable, Optional
from celery import current_app
from backend.worker.celery_app import app

logger = logging.getLogger(__name__)

# Redis connection for debounce buffers
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# Debounce interval in seconds
DEBOUNCE_INTERVAL = 20


def _debounce_keys(
    phone: str,
    company_id: int,
    operational_epoch: Optional[int],
) -> tuple[str, str]:
    epoch_part = (
        "legacy"
        if operational_epoch is None
        else str(int(operational_epoch))
    )
    identity = f"{int(company_id)}:{epoch_part}:{phone}"
    return (
        f"debounce_buffer:{identity}",
        f"debounce_task:{identity}",
    )


@app.task(bind=True, ignore_result=True)
def process_debounced_messages(self, phone: str, callback_data: dict):
    """
    Celery task que processa mensagens após o debounce.
    Esta task é agendada com ETA e substitui o threading.Timer
    """
    try:
        company_id = int(callback_data["company_id"])
        operational_epoch = callback_data.get("_operational_epoch")
        buffer_key, task_key = _debounce_keys(
            phone,
            company_id,
            operational_epoch,
        )

        from backend.db import SessionLocal
        from backend.services.company_access_control import validate_company_job_epoch

        gate_db = SessionLocal()
        try:
            epoch_is_valid = validate_company_job_epoch(
                gate_db,
                company_id,
                operational_epoch,
            )
        finally:
            gate_db.close()
        if not epoch_is_valid:
            redis_client.delete(buffer_key, task_key)
            logger.info(
                "[debounce] Epoch obsoleto descartado company=%s epoch=%s",
                company_id,
                operational_epoch,
            )
            return

        # Recuperar mensagens do buffer Redis
        messages = redis_client.lrange(buffer_key, 0, -1)

        if not messages:
            logger.info(f"[debounce] Nenhuma mensagem encontrada para {phone}")
            return

        logger.info(f"[debounce] Processando {len(messages)} mensagens para {phone}")

        # Limpar buffer e task_id do Redis
        pipe = redis_client.pipeline()
        pipe.delete(buffer_key)
        pipe.delete(task_key)
        pipe.execute()

        # Reconstituir callback function e executar
        from backend.integrations.burst_processor import process_burst_messages
        db = SessionLocal()
        try:
            # O processamento segue a mesma fila genérica para todas as empresas.
            # O burst_processor já tem toda a lógica implementada para:
            # 1. Chamar agents_sdk se a empresa estiver habilitada
            # 2. Salvar mensagens no banco de dados
            # 3. Enviar via Z-API
            # 4. Fazer broadcast via WebSocket

            # Processar TODAS as empresas através do burst_processor
            process_burst_messages(
                contact_phone=phone,
                messages=messages,
                db=db,
                company_id=company_id,
                client_id_db=callback_data['client_id_db'],
                msg_category=callback_data.get('msg_category'),
                funnel_stage=callback_data.get('funnel_stage'),
                funnel_status=callback_data.get('funnel_status')
            )

            logger.info(f"[debounce] Processamento concluído para {phone}")
        finally:
            db.close()

    except Exception as e:
        logger.error(f"[debounce] Erro ao processar mensagens para {phone}: {e}", exc_info=True)


def schedule_debounced_processing(
    phone: str,
    message_text: str,
    callback_data: dict,
    operational_epoch: Optional[int] = None,
):
    """
    Agenda o processamento de mensagens com debounce usando Celery ETA.
    Substitui o sistema de threading anterior.

    Args:
        phone: Telefone do contato
        message_text: Texto da mensagem
        callback_data: Dados necessários para o callback (company_id, etc.)
    """
    try:
        company_id = int(callback_data["company_id"])
        from backend.db import SessionLocal
        from backend.services.company_access_control import capture_company_job_epoch

        gate_db = SessionLocal()
        try:
            captured_epoch = capture_company_job_epoch(
                gate_db,
                company_id,
                expected_epoch=operational_epoch,
            )
        finally:
            try:
                gate_db.rollback()
            finally:
                gate_db.close()
        callback_data = dict(callback_data)
        callback_data["_operational_epoch"] = int(captured_epoch)

        # Adicionar mensagem ao buffer Redis
        buffer_key, task_key = _debounce_keys(
            phone,
            company_id,
            captured_epoch,
        )

        redis_client.lpush(buffer_key, message_text)
        redis_client.expire(buffer_key, DEBOUNCE_INTERVAL + 60)  # TTL extra para segurança

        # Cancelar task anterior se existir
        old_task_id = redis_client.get(task_key)
        if old_task_id:
            try:
                current_app.control.revoke(old_task_id, terminate=True)
                logger.info(f"[debounce] Task anterior cancelada para {phone}: {old_task_id}")
            except Exception as e:
                logger.warning(f"[debounce] Erro ao cancelar task anterior para {phone}: {e}")

        # Schedule every tenant on the shared, generic message queue.
        eta = datetime.utcnow() + timedelta(seconds=DEBOUNCE_INTERVAL)

        result = process_debounced_messages.apply_async(
            args=[phone, callback_data],
            eta=eta,
            queue="messages_queue",
        )

        # Armazenar task_id no Redis
        redis_client.set(task_key, result.id, ex=DEBOUNCE_INTERVAL + 60)

        logger.info(f"[debounce] Nova task agendada para {phone}: {result.id} (ETA: {eta})")

    except Exception as e:
        logger.error(f"[debounce] Erro ao agendar processamento para {phone}: {e}", exc_info=True)
        # Fail closed. An immediate fallback could execute an old buffered
        # conversation after an access-status transition.


def clear_debounce_buffer(phone: str):
    """
    Limpa o buffer de debounce para um telefone específico.
    Útil para casos de teste ou limpeza manual.
    """
    try:
        buffer_key = f"debounce_buffer:{phone}"
        task_key = f"debounce_task:{phone}"

        # Cancelar task pendente
        task_id = redis_client.get(task_key)
        if task_id:
            current_app.control.revoke(task_id, terminate=True)

        # Limpar Redis
        pipe = redis_client.pipeline()
        pipe.delete(buffer_key)
        pipe.delete(task_key)
        pipe.execute()

        logger.info(f"[debounce] Buffer limpo para {phone}")

    except Exception as e:
        logger.error(f"[debounce] Erro ao limpar buffer para {phone}: {e}")
