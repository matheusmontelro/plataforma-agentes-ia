
import logging
from datetime import datetime, timedelta, timezone
from celery import Celery
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload
import asyncio
import redis
import json

from .celery_app import app
from backend.db import SessionLocal
from backend.events.websocket_channels import websocket_channel, websocket_redis_url
from backend.models import ContactTask, User, Contact

logger = logging.getLogger(__name__)

@app.task(bind=True, max_retries=3)
def send_task_reminder(self, task_id: int):
    """
    Envia lembrete de tarefa para o usuário responsável
    """
    logger.info(f"Processando lembrete para tarefa {task_id}")

    with SessionLocal() as db:
        try:
            # Buscar tarefa com relacionamentos
            task = db.query(ContactTask).options(
                joinedload(ContactTask.contact),
                joinedload(ContactTask.assignee),
                joinedload(ContactTask.creator)
            ).filter(ContactTask.id == task_id).first()

            if not task:
                logger.warning(f"Tarefa {task_id} não encontrada")
                return

            if task.status != 'pending':
                logger.info(f"Tarefa {task_id} não está mais pendente (status: {task.status})")
                return

            # Verificar se ainda está no tempo de lembrete
            current_time = datetime.now(timezone.utc)
            task_time = task.scheduled_for.replace(tzinfo=timezone.utc) if task.scheduled_for.tzinfo is None else task.scheduled_for
            time_until_task = (task_time - current_time).total_seconds() / 60  # em minutos

            if time_until_task > task.reminder_minutes + 5:  # 5 minutos de tolerância
                logger.info(f"Tarefa {task_id} ainda não está no tempo de lembrete")
                return

            # Determinar destinatário do lembrete
            recipient_user = task.assignee if task.assigned_to else task.creator

            # Verificar se foi criada por um Client
            client_creator = None
            if not recipient_user and task.task_metadata:
                metadata = task.task_metadata if isinstance(task.task_metadata, dict) else {}
                if 'created_by_client' in metadata:
                    client_creator = metadata['created_by_client']
                    logger.info(f"Tarefa {task_id} criada por Client: {client_creator}")
                    # Para tarefas criadas por Client, sempre usar broadcast global
                    recipient_user = None

            # Preparar dados do lembrete
            reminder_data = {
                'type': 'task_reminder',
                'task': {
                    'id': task.id,
                    'title': task.title,
                    'task_type': task.task_type,
                    'priority': task.priority,
                    'scheduled_for': task.scheduled_for.isoformat(),
                    'contact': {
                        'id': task.contact.id,
                        'name': task.contact.name,
                        'phone': task.contact.phone
                    }
                },
                'minutes_until': int(time_until_task) if time_until_task > 0 else 0,
                'is_overdue': time_until_task < 0,
                'created_by_client': client_creator is not None,
                'company_id': task.company_id,  # CRÍTICO: Necessário para o filtro de segurança no frontend
                'user_id': recipient_user.id if recipient_user else None  # Adicionar user_id para filtro adicional
            }

            # Enviar via Redis
            redis_client = redis.Redis.from_url(websocket_redis_url())

            try:
                if recipient_user:
                    # Enviar para o canal pessoal do usuário
                    channel = websocket_channel(
                        f"task_reminder_{recipient_user.id}"
                    )
                    redis_client.publish(channel, json.dumps(reminder_data))
                    logger.info(f"Lembrete enviado para usuário {recipient_user.id} sobre tarefa {task_id}")
                else:
                    logger.info(f"Lembrete de tarefa {task_id} será enviado apenas via broadcast")

                # CORREÇÃO: Enviar broadcast somente para usuários da mesma empresa
                # Isso garante que apenas usuários da empresa correta recebam a notificação
                channel = websocket_channel(
                    f"company_global:{task.company_id}"
                )
                redis_client.publish(channel, json.dumps(reminder_data))
                logger.info(f"Lembrete publicado no canal {channel} para empresa {task.company_id}")

            finally:
                redis_client.close()

            # Se a tarefa está próxima ou atrasada, agendar próximo lembrete em 30 minutos
            if time_until_task <= 5 and task.status == 'pending':
                send_task_reminder.apply_async(
                    args=[task_id],
                    countdown=1800  # 30 minutos
                )

        except Exception as e:
            logger.error(f"Erro ao enviar lembrete da tarefa {task_id}: {e}")
            raise self.retry(exc=e, countdown=60)


@app.task
def schedule_task_reminders():
    """
    Tarefa periódica que agenda lembretes para tarefas futuras
    Deve ser executada a cada hora
    """
    logger.info("Iniciando agendamento de lembretes de tarefas")

    with SessionLocal() as db:
        try:
            # Buscar tarefas pendentes nas próximas 24 horas
            now = datetime.now(timezone.utc)
            tomorrow = now + timedelta(hours=24)

            upcoming_tasks = db.query(ContactTask).filter(
                ContactTask.status == 'pending',
                ContactTask.scheduled_for >= now,
                ContactTask.scheduled_for <= tomorrow,
                ContactTask.reminder_minutes > 0  # Apenas tarefas com lembrete configurado
            ).all()

            scheduled_count = 0

            for task in upcoming_tasks:
                # Calcular quando enviar o lembrete
                task_time = task.scheduled_for.replace(tzinfo=timezone.utc) if task.scheduled_for.tzinfo is None else task.scheduled_for
                reminder_time = task_time - timedelta(minutes=task.reminder_minutes)

                # Se o lembrete deve ser enviado nas próximas horas
                if now <= reminder_time <= now + timedelta(hours=1):
                    # Calcular delay em segundos
                    delay_seconds = int((reminder_time - now).total_seconds())

                    # Agendar lembrete
                    send_task_reminder.apply_async(
                        args=[task.id],
                        countdown=max(delay_seconds, 0)
                    )

                    scheduled_count += 1
                    logger.info(f"Lembrete agendado para tarefa {task.id} em {delay_seconds} segundos")

            logger.info(f"Total de {scheduled_count} lembretes agendados")

        except Exception as e:
            logger.error(f"Erro ao agendar lembretes: {e}")


@app.task
def check_overdue_tasks():
    """
    Verifica tarefas atrasadas e envia notificações
    Deve ser executada a cada 30 minutos
    """
    logger.info("Verificando tarefas atrasadas")

    with SessionLocal() as db:
        try:
            now = datetime.now(timezone.utc)

            # Buscar tarefas atrasadas
            overdue_tasks = db.query(ContactTask).options(
                joinedload(ContactTask.contact),
                joinedload(ContactTask.assignee),
                joinedload(ContactTask.creator)
            ).filter(
                ContactTask.status.in_(['pending', 'in_progress']),
                ContactTask.scheduled_for < now
            ).all()

            # Agrupar por usuário responsável
            tasks_by_user = {}
            for task in overdue_tasks:
                user = task.assignee if task.assigned_to else task.creator
                if user.id not in tasks_by_user:
                    tasks_by_user[user.id] = []
                tasks_by_user[user.id].append(task)

            # Enviar notificações agregadas
            for user_id, user_tasks in tasks_by_user.items():
                # Pegar company_id da primeira tarefa (todas devem ser da mesma empresa)
                company_id = user_tasks[0].company_id if user_tasks else None

                overdue_data = {
                    'type': 'overdue_tasks',
                    'count': len(user_tasks),
                    'company_id': company_id,  # CRÍTICO: Adicionar company_id para filtro de segurança
                    'user_id': user_id,
                    'tasks': [{
                        'id': task.id,
                        'title': task.title,
                        'priority': task.priority,
                        'scheduled_for': task.scheduled_for.isoformat(),
                        'overdue_minutes': int((now - task.scheduled_for).total_seconds() / 60),
                        'contact': {
                            'name': task.contact.name,
                            'phone': task.contact.phone
                        }
                    } for task in user_tasks[:5]]  # Limitar a 5 tarefas na notificação
                }

                # Enviar via Redis
                redis_client = redis.Redis.from_url(websocket_redis_url())
                try:
                    channel = websocket_channel(
                        f"task_notifications:{user_id}"
                    )
                    redis_client.publish(channel, json.dumps(overdue_data))

                    # Também enviar para o canal global da empresa
                    if user_tasks and len(user_tasks) > 0:
                        company_id = user_tasks[0].company_id
                        channel = websocket_channel(
                            f"company_global:{company_id}"
                        )
                        redis_client.publish(channel, json.dumps(overdue_data))
                finally:
                    redis_client.close()

            logger.info(f"Notificações de atraso enviadas para {len(tasks_by_user)} usuários")

        except Exception as e:
            logger.error(f"Erro ao verificar tarefas atrasadas: {e}")


@app.task
def create_task_from_flow(contact_id: int, company_id: int, flow_type: str, step_info: dict):
    """
    Cria uma tarefa automaticamente a partir de um flow
    """
    logger.info(f"Criando tarefa automática para contato {contact_id} do flow {flow_type}")

    with SessionLocal() as db:
        try:
            # Buscar contato
            contact = db.query(Contact).filter(
                Contact.id == contact_id
            ).first()

            if not contact:
                logger.error(f"Contato {contact_id} não encontrado")
                return

            # Determinar tipo de tarefa baseado no flow
            task_type_map = {
                'follow_up': 'message',
                'confirmation': 'message',
                'noshow': 'call',
                'pos_consulta': 'message',
                'pos_venda': 'email'
            }

            task_type = task_type_map.get(flow_type, 'custom')

            # Criar tarefa
            task = ContactTask(
                contact_id=contact_id,
                company_id=company_id,
                created_by=1,  # Sistema
                task_type=task_type,
                title=f"Follow-up automático - {flow_type}",
                description=f"Tarefa criada automaticamente pelo flow {flow_type}",
                scheduled_for=datetime.fromisoformat(step_info.get('scheduled_for', datetime.now().isoformat())),
                reminder_minutes=0,  # Sem lembrete para tarefas automáticas
                priority='medium',
                flow_type=flow_type,
                flow_execution_id=step_info.get('execution_id'),
                metadata={
                    'auto_generated': True,
                    'flow_step': step_info.get('step_number', 1)
                }
            )

            db.add(task)
            db.commit()

            logger.info(f"Tarefa {task.id} criada com sucesso para flow {flow_type}")

        except Exception as e:
            logger.error(f"Erro ao criar tarefa do flow: {e}")
            db.rollback()


# Registrar tarefas periódicas no Celery Beat
from celery.schedules import crontab

app.conf.beat_schedule.update({
    'schedule-task-reminders': {
        'task': 'backend.worker.tasks_reminders.schedule_task_reminders',
        'schedule': crontab(minute=0),  # A cada hora
    },
    'check-overdue-tasks': {
        'task': 'backend.worker.tasks_reminders.check_overdue_tasks',
        'schedule': crontab(minute='*/30'),  # A cada 30 minutos
    },
})
