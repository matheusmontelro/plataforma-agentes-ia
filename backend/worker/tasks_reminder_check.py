
import logging
from datetime import datetime, timedelta, timezone
from celery import Celery
from sqlalchemy import and_

from .celery_app import app
from backend.db import SessionLocal
from backend.models import ContactTask

# Import custom logger
try:
    from backend.config_logging import reminder_logger as logger
except ImportError:
    logger = logging.getLogger(__name__)

@app.task
def check_and_schedule_reminders():
    """
    Verifica tarefas que precisam de lembretes e agenda o envio
    Esta tarefa deve ser executada a cada 5 minutos pelo Celery Beat
    """
    logger.info("Iniciando verificação de lembretes de tarefas")

    with SessionLocal() as db:
        try:
            # Buscar tarefas pendentes com lembretes
            current_time = datetime.now(timezone.utc)

            # Buscar tarefas que devem ter lembretes enviados nos próximos 10 minutos
            check_until = current_time + timedelta(minutes=10)

            # Buscar TODAS as tarefas pendentes com lembretes configurados
            # Depois filtraremos pelo horário do lembrete, não da tarefa
            tasks = db.query(ContactTask).filter(
                and_(
                    ContactTask.status == 'pending',
                    ContactTask.reminder_minutes > 0
                )
            ).all()

            logger.info(f"Encontradas {len(tasks)} tarefas para verificar lembretes")

            for task in tasks:
                # Calcular quando o lembrete deve ser enviado
                reminder_time = task.scheduled_for - timedelta(minutes=task.reminder_minutes)

                # Se o tempo do lembrete está entre agora e os próximos 10 minutos
                if current_time <= reminder_time <= check_until:
                    # Calcular delay para o lembrete
                    delay_seconds = (reminder_time - current_time).total_seconds()

                    if delay_seconds > 0:
                        # Agendar o lembrete
                        from .tasks_reminders import send_task_reminder
                        send_task_reminder.apply_async(
                            args=[task.id],
                            countdown=int(delay_seconds)
                        )
                        logger.info(f"Lembrete agendado para tarefa {task.id} em {delay_seconds} segundos")
                    else:
                        # Enviar imediatamente se já passou do tempo
                        from .tasks_reminders import send_task_reminder
                        send_task_reminder.delay(task.id)
                        logger.info(f"Lembrete enviado imediatamente para tarefa {task.id}")

            return f"Verificação concluída. {len(tasks)} tarefas processadas."

        except Exception as e:
            logger.error(f"Erro ao verificar lembretes: {str(e)}", exc_info=True)
            raise
