# backend/worker/celery_app.py
import os
from celery import Celery
from dotenv import load_dotenv
from celery.schedules import crontab
from celery.signals import worker_process_init

from backend.worker.db_pool_lifecycle import dispose_inherited_sqlalchemy_pool

# Carrega variáveis de ambiente do .env (se existir)
load_dotenv()

worker_process_init.connect(
    dispose_inherited_sqlalchemy_pool,
    weak=False,
)

# Variáveis de ambiente para Redis/Celery
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)

# Criação da instância principal do Celery
app = Celery("saas_business", broker=BROKER_URL, backend=RESULT_BACKEND)

# Configurações gerais
app.conf.update(
    broker_url=BROKER_URL,
    result_backend=RESULT_BACKEND,

    broker_connection_retry=True,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=10,
    broker_pool_limit=None,  # Permite conexões dinâmicas ao broker

    # Configurações de Redis
    redis_max_connections=20,
    redis_socket_timeout=5.0,

    timezone="America/Sao_Paulo",
    enable_utc=True,

    # Configurações de ACK e Retry
    task_acks_late=True,
    task_reject_on_worker_lost=True,

    task_default_retry_delay=5,
    task_max_retries=3,

    # Evitar múltiplas execuções da mesma tarefa
    task_track_started=True,
    task_send_sent_event=True,
    worker_prefetch_multiplier=1,  # Cada worker pega apenas 1 tarefa por vez
    worker_max_tasks_per_child=150,  # Recicla worker após 150 tarefas (evita perda de debounce)

    # Inclui os módulos com as tasks
    include=[
        'backend.worker.tasks',
        'backend.worker.tasks_noshow',
        'backend.worker.tasks_confirmation',
        'backend.worker.tasks_scheduling',  # NOVO: para tasks de agendamento
        'backend.worker.tasks_pos_consulta',  # NOVO: para tasks pós-consulta
        'backend.worker.tasks_pos_venda',  # NOVO: para tasks pós-venda
        'backend.worker.tasks_reminders',  # NOVO: para lembretes de tarefas
        'backend.worker.tasks_reminder_check',  # NOVO: verificação de lembretes
        'backend.worker.tasks_scheduled_messages',  # NOVO: para mensagens agendadas
        'backend.worker.tasks_agent_dynamic_followup',  # NOVO: follow-up dinamico do Agent Builder
        'backend.worker.tasks_nutrition_campaign',  # NOVO: para campanhas de nutrição
        # 'backend.agents_sdk.tasks.celery_tasks',  # NOVO: para Agents SDK Database (DESABILITADO TEMPORARIAMENTE: Erro de import SQLiteSession)
        'backend.worker.process_message_waha',  # NOVO: para processamento WAHA
        'backend.worker.agent_workforce_debounce',
        'backend.worker.tasks_flow',  # NOVO: para execução de flows FlowBuilder
        'backend.worker.tasks_whatsapp_campaign',  # NOVO: para campanhas de WhatsApp
    ],

    # Roteamento de tasks para filas específicas
    task_routes={
        # Fila já existente para tasks de confirmação
        'backend.worker.tasks_confirmation.enviar_lote_confirmacao': {
            'queue': 'confirmation_queue',
        },
        'backend.worker.tasks_confirmation.enviar_passo_confirmacao': {
            'queue': 'confirmation_queue',
        },

        # Roteamento para WAHA
        'backend.worker.process_message_waha.process_incoming_waha_message': {
            'queue': 'waha_messages_queue',
        },
        'backend.worker.agent_workforce_debounce.process_debounced_whatsapp_flow': {
            'queue': 'waha_messages_queue',
        },

        # NOVO: Fila específica para tasks de followup
        'backend.worker.tasks.enviar_passo_followup': {
            'queue': 'followup_queue',
        },
        'backend.worker.tasks_agent_dynamic_followup.enviar_passo_agent_dynamic_followup': {
            'queue': 'waha_messages_queue',
        },

        # NOVO: Fila específica para tasks de noshow
        'backend.worker.tasks_noshow.enviar_passo_noshow': {
            'queue': 'noshow_queue',
        },

        # NOVO: Fila específica para tasks pós-consulta
        'backend.worker.tasks_pos_consulta.enviar_passo_pos_consulta': {
            'queue': 'pos_consulta_queue',
        },

        # NOVO: Fila específica para tasks pós-venda
        'backend.worker.tasks_pos_venda.enviar_passo_pos_venda': {
            'queue': 'pos_venda_queue',
        },

        # Incluir rota para tasks_scheduling
        'backend.worker.tasks_scheduling.update_one_company_availabilities': {
            'queue': 'scheduling_queue',
        },

        # NOVO: Rotas para tarefas de lembretes
        'backend.worker.tasks_reminders.send_task_reminder': {
            'queue': 'reminders_queue',
        },

        # NOVO: Rota para task de debounce
        'backend.worker.debounce_tasks.process_debounced_messages': {
            'queue': 'messages_queue',
        },
        'backend.worker.tasks_reminder_check.check_and_schedule_reminders': {
            'queue': 'reminders_queue',
        },
        'backend.worker.tasks_scheduling.update_all_companies_availabilities': {
            'queue': 'scheduling_queue',
        },

        # NOVO: Roteamento para tasks de lembretes
        'backend.worker.tasks_reminders.send_task_reminder': {
            'queue': 'reminders_queue',
        },
        'backend.worker.tasks_reminders.schedule_task_reminders': {
            'queue': 'reminders_queue',
        },
        'backend.worker.tasks_reminders.check_overdue_tasks': {
            'queue': 'reminders_queue',
        },

        # NOVO: Roteamento para mensagens agendadas
        'backend.worker.tasks_scheduled_messages.enviar_mensagem_agendada': {
            'queue': 'scheduled_messages_queue',
        },

        # NOVO: Roteamento para campanhas de nutrição
        'backend.worker.tasks_nutrition_campaign.enviar_passo_nutrition_campaign': {
            'queue': 'nutrition_campaign_queue',
        },
        'backend.worker.tasks_nutrition_campaign.iniciar_nutrition_campaign_para_contatos': {
            'queue': 'nutrition_campaign_queue',
        },

        # NOVO: Roteamento para Agents SDK Database tasks
        'agents_sdk.fetch_and_store_company_slots': {
            'queue': 'agents_sdk_queue',
        },
        'agents_sdk.cleanup_expired_slots': {
            'queue': 'agents_sdk_queue',
        },
        'agents_sdk.refresh_all_companies_slots': {
            'queue': 'agents_sdk_queue',
        },
        'agents_sdk.populate_sample_slots': {
            'queue': 'agents_sdk_queue',
        },

        # NOVO: Roteamento para execução de Flows
        'backend.worker.tasks_flow.execute_flow_task': {
            'queue': 'flow_execution_queue',
        },
        'backend.worker.tasks_flow.execute_delayed_node': {
            'queue': 'flow_execution_queue',
        },

        # NOVO: Roteamento para Campanhas de WhatsApp
        'backend.worker.tasks_whatsapp_campaign.process_whatsapp_campaign': {
            'queue': 'whatsapp_campaign_queue',
        },
        'backend.worker.tasks_whatsapp_campaign.send_single_message_task': {
            'queue': 'whatsapp_campaign_queue',
        },
    },

    # Definir as filas disponíveis
    task_queues={
        'messages_queue': {},
        'waha_messages_queue': {}, # NOVA fila para WAHA
        'confirmation_queue': {},
        'scheduling_queue': {},
        'followup_queue': {},  # NOVA fila para followup
        'noshow_queue': {},    # NOVA fila para noshow
        'pos_consulta_queue': {},  # NOVA fila para pós-consulta
        'pos_venda_queue': {},  # NOVA fila para pós-venda
        'reminders_queue': {},  # NOVA fila para lembretes de tarefas
        'scheduled_messages_queue': {},  # NOVA fila para mensagens agendadas
        'nutrition_campaign_queue': {},  # NOVA fila para campanhas de nutrição
        'agents_sdk_queue': {},  # NOVA fila para Agents SDK Database
        'flow_execution_queue': {},  # NOVA fila para execução de flows
        'whatsapp_campaign_queue': {},  # NOVA fila para campanhas de WhatsApp
    },
)

# Exemplo de agendamento Celery Beat: atualiza todas as empresas a cada 15min
app.conf.beat_schedule = {
    'update-all-companies-availability-every-5min': {
        'task': 'backend.worker.tasks_scheduling.update_all_companies_availabilities',
        'schedule': 300,  # 300 segundos = 5 minutos
    },

    # NOVO: Verificação de lembretes de tarefas a cada 5 minutos
    'check-task-reminders-every-5min': {
        'task': 'backend.worker.tasks_reminder_check.check_and_schedule_reminders',
        'schedule': 300,  # 300 segundos = 5 minutos
        'options': {
            'queue': 'reminders_queue',
            'priority': 5,
        }
    },

    # NOVO: Agents SDK Database tasks
    'refresh-all-companies-slots-database-every-5min': {
        'task': 'agents_sdk.refresh_all_companies_slots',
        'schedule': 300,  # 300 segundos = 5 minutos
        'options': {
            'queue': 'agents_sdk_queue',
            'priority': 7,
        }
    },

    'cleanup-expired-slots-every-hour': {
        'task': 'agents_sdk.cleanup_expired_slots',
        'schedule': 3600,  # 3600 segundos = 1 hora
        'options': {
            'queue': 'agents_sdk_queue',
            'priority': 3,
        }
    },
}

# Importar tasks para registrá-las no Celery
from backend.worker import debounce_tasks

if __name__ == "__main__":
    """
    Caso você queira rodar o worker diretamente:
       python celery_app.py worker --loglevel=INFO

    Porém, na prática você costuma usar:
       celery -A backend.worker.celery_app:app worker --loglevel=INFO

    Para rodar o beat (agendador) em paralelo, use:
       celery -A backend.worker.celery_app:app beat --loglevel=INFO

    ou via systemctl / docker-compose, etc.
    """
    app.start()
