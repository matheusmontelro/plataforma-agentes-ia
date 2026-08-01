"""
Monitor de Fila Z-API - Recupera mensagens perdidas do webhook
"""
import os
import logging
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import json
from sqlalchemy import text
from celery import Task

from backend.worker.celery_app import app as celery_app
from backend.db import get_db
from backend.worker.process_message import process_incoming_zapi_message
from backend.config import CLIENT_TOKEN
from backend.runtime_settings import LOG_DIR

# Configurar diretório de logs
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Configurações
QUEUE_MIN_AGE_MINUTES = int(os.getenv("QUEUE_MIN_AGE_MINUTES", "5"))
QUEUE_PAGE_SIZE = int(os.getenv("QUEUE_PAGE_SIZE", "100"))


def setup_logger(name: str, filename: str) -> logging.Logger:
    """Configura logger com arquivo específico"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Remover handlers existentes para evitar duplicação
    logger.handlers = []

    # Handler para arquivo
    file_handler = logging.FileHandler(LOG_DIR / filename, encoding='utf-8')
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Handler para console também
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


# Configurar loggers
monitor_logger = setup_logger(
    'queue_monitor',
    f'queue_monitor_daily_{datetime.now().strftime("%Y%m%d")}.log'
)
recovery_logger = setup_logger(
    'queue_recovery',
    f'queue_recovery_{datetime.now().strftime("%Y%m")}.log'
)
alert_logger = setup_logger('queue_alerts', 'queue_alerts.log')


def log_message_recovery(
    company_id: int,
    company_name: str,
    phone: str,
    message_id: str,
    time_in_queue: int,
    content: str,
    status: str = "SUCCESS"
):
    """Registra detalhes de mensagem recuperada"""

    # Log resumido no monitor
    if status == "SUCCESS":
        monitor_logger.info(
            f"SUCCESS - Mensagem recuperada: Company={company_id}, Phone={phone}, ID={message_id}"
        )
    else:
        monitor_logger.warning(
            f"Empresa {company_id}: Processando mensagem antiga - "
            f"ID: {message_id}, Phone: {phone}, Idade: {time_in_queue} min"
        )

    # Log detalhado para recuperação
    recovery_logger.info("=" * 80)
    recovery_logger.info("MENSAGEM RECUPERADA DA FILA")
    recovery_logger.info("=" * 80)
    recovery_logger.info(f"Timestamp: {datetime.now()}")
    recovery_logger.info(f"Company ID: {company_id}")
    recovery_logger.info(f"Company Name: {company_name}")
    recovery_logger.info(f"Phone: {phone}")
    recovery_logger.info(f"Message ID: {message_id}")
    recovery_logger.info(f"Tempo na Fila: {time_in_queue} minutos")
    recovery_logger.info(f"Conteúdo: {content[:200]}...")
    recovery_logger.info(f"Status: {status}")
    recovery_logger.info("=" * 80)
    recovery_logger.info("")

    # Alerta se mensagem ficou muito tempo na fila
    if time_in_queue > 30:
        alert_logger.critical(
            f"ALERTA CRÍTICO: Mensagem ficou {time_in_queue} min na fila! "
            f"Company={company_id}, Phone={phone}, ID={message_id}"
        )


def check_message_exists(db, company_id: int, message_id: str, phone: str) -> bool:
    """Verifica se mensagem já foi processada para evitar duplicatas"""

    # Primeiro verificar por ID único do Z-API
    if message_id:
        result = db.execute(
            text("""
                SELECT 1 FROM messages
                WHERE company_id = :company_id
                AND zapi_message_id = :message_id
                LIMIT 1
            """),
            {"company_id": company_id, "message_id": message_id}
        ).fetchone()

        if result:
            return True

    # Verificar por mensagens recentes do mesmo telefone (janela de 10 minutos)
    result = db.execute(
        text("""
            SELECT 1 FROM messages
            WHERE company_id = :company_id
            AND contact_phone = :phone
            AND timestamp > :time_threshold
            AND from_me = false
            LIMIT 1
        """),
        {
            "company_id": company_id,
            "phone": phone,
            "time_threshold": datetime.now() - timedelta(minutes=10)
        }
    ).fetchone()

    return result is not None


def get_queue_messages(instance_id: str, token: str, page: int = 1) -> Tuple[List[Dict], Optional[str]]:
    """Busca mensagens da fila do Z-API"""
    url = f"https://api.z-api.io/instances/{instance_id}/token/{token}/queue"
    headers = {
        "Client-Token": CLIENT_TOKEN,
        "accept": "application/json"
    }
    params = {
        "page": page,
        "pageSize": QUEUE_PAGE_SIZE
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)

        if response.status_code == 200:
            messages = response.json()
            if isinstance(messages, list):
                return messages, None
            else:
                return [], "Resposta inválida da API"
        else:
            error_msg = f"Erro HTTP {response.status_code}: {response.text[:200]}"
            return [], error_msg

    except requests.exceptions.Timeout:
        return [], "Timeout ao consultar fila"
    except Exception as e:
        return [], f"Erro ao conectar: {str(e)}"


def convert_queue_to_webhook_format(queue_msg: Dict, instance_id: str) -> Dict:
    """Converte mensagem da fila para formato compatível com webhook"""

    # Extrair dados da mensagem da fila
    message_id = queue_msg.get('MessageId') or queue_msg.get('_id', '')
    phone = queue_msg.get('Phone', '')
    content = queue_msg.get('Message', '')
    timestamp = queue_msg.get('Created', 0)

    # Converter para formato do webhook
    webhook_data = {
        # Dados principais
        "phone": phone,
        "sender": phone,
        "message": content,
        "messageId": message_id,

        # Metadados
        "isFromQueue": True,
        "queueTimestamp": timestamp,
        "instanceId": instance_id,

        # Estrutura esperada pelo process_message
        "text": {
            "message": content
        },
        "messageTimestamp": str(int(timestamp / 1000)) if timestamp else str(int(datetime.now().timestamp()))
    }

    return webhook_data


def process_company_queue(company_id: int, company_name: str, instance_id: str, token: str) -> Dict[str, int]:
    """Processa fila de uma empresa específica"""

    stats = {
        "total": 0,
        "processed": 0,
        "skipped": 0,
        "errors": 0
    }

    monitor_logger.info(f"Verificando fila da empresa {company_name} (ID: {company_id})")

    # Buscar mensagens da fila
    messages, error = get_queue_messages(instance_id, token)

    if error:
        monitor_logger.error(f"Erro ao buscar fila da empresa {company_id}: {error}")
        return stats

    stats["total"] = len(messages)

    if not messages:
        monitor_logger.info(f"Empresa {company_id} ({company_name}): 0 mensagens na fila")
        return stats

    monitor_logger.info(f"Empresa {company_id} ({company_name}): {len(messages)} mensagens na fila")

    # Processar cada mensagem
    db = next(get_db())
    try:
        cutoff_time = int((datetime.now() - timedelta(minutes=QUEUE_MIN_AGE_MINUTES)).timestamp() * 1000)

        for msg in messages:
            try:
                # Verificar idade da mensagem
                created_time = msg.get('Created', 0)
                if created_time > cutoff_time:
                    monitor_logger.debug(f"Mensagem muito recente, ignorando: {msg.get('_id')}")
                    stats["skipped"] += 1
                    continue

                # Calcular tempo na fila
                time_in_queue = int((datetime.now().timestamp() * 1000 - created_time) / 1000 / 60)

                # Extrair informações
                message_id = msg.get('MessageId') or msg.get('_id', '')
                phone = msg.get('Phone', '')
                content = msg.get('Message', '')

                # Verificar se já foi processada
                if check_message_exists(db, company_id, message_id, phone):
                    monitor_logger.debug(f"Mensagem já processada: {message_id}")
                    stats["skipped"] += 1
                    continue

                # Log de início de processamento
                log_message_recovery(
                    company_id,
                    company_name,
                    phone,
                    message_id,
                    time_in_queue,
                    content,
                    "PROCESSING"
                )

                # Converter e processar
                webhook_data = convert_queue_to_webhook_format(msg, instance_id)

                # Enviar para processamento assíncrono
                monitor_logger.info(f"Enviando mensagem {message_id} para processamento")
                process_incoming_zapi_message.delay(webhook_data, instance_id)

                # Log de sucesso
                log_message_recovery(
                    company_id,
                    company_name,
                    phone,
                    message_id,
                    time_in_queue,
                    content,
                    "SUCCESS"
                )

                stats["processed"] += 1

            except Exception as e:
                monitor_logger.error(f"Erro ao processar mensagem: {str(e)}")
                stats["errors"] += 1

    finally:
        db.close()

    # Alertar se muitas mensagens foram recuperadas
    if stats["processed"] > 10:
        alert_logger.warning(
            f"ALERTA: {stats['processed']} mensagens recuperadas para empresa {company_name} (ID: {company_id}). "
            f"Possível problema recorrente com webhook!"
        )

    return stats


@celery_app.task(bind=True, name='check_zapi_queues', max_retries=3)
def check_zapi_queues(self):
    """
    Task principal que monitora filas de todas as empresas
    Deve ser executada a cada 5 minutos via Celery Beat
    """

    start_time = datetime.now()
    monitor_logger.info("=" * 80)
    monitor_logger.info("Iniciando monitor de fila Z-API")
    monitor_logger.info("=" * 80)

    total_stats = {
        "companies_checked": 0,
        "total_messages": 0,
        "total_processed": 0,
        "total_errors": 0
    }

    db = next(get_db())
    try:
        # Buscar empresas com Z-API configurado
        companies = db.execute(
            text("""
                SELECT id, name, zapi_instance_id, zapi_token
                FROM companies
                WHERE zapi_instance_id IS NOT NULL
                AND zapi_token IS NOT NULL
                ORDER BY id
            """)
        ).fetchall()

        total_stats["companies_checked"] = len(companies)
        monitor_logger.info(f"Encontradas {len(companies)} empresas ativas com Z-API configurado")

        # Processar cada empresa
        for company in companies:
            try:
                stats = process_company_queue(
                    company.id,
                    company.name,
                    company.zapi_instance_id,
                    company.zapi_token
                )

                total_stats["total_messages"] += stats["total"]
                total_stats["total_processed"] += stats["processed"]
                total_stats["total_errors"] += stats["errors"]

            except Exception as e:
                monitor_logger.error(f"Erro ao processar empresa {company.id}: {str(e)}")
                total_stats["total_errors"] += 1

        # Log de resumo
        duration = (datetime.now() - start_time).total_seconds()
        monitor_logger.info("=" * 80)
        monitor_logger.info(
            f"Monitor finalizado em {duration:.2f}s: "
            f"{total_stats['total_processed']} mensagens recuperadas de "
            f"{total_stats['companies_checked']} empresas verificadas"
        )
        monitor_logger.info("=" * 80)
        monitor_logger.info("")

        # Alerta se muitos erros
        if total_stats["total_errors"] > 5:
            alert_logger.critical(
                f"ALERTA CRÍTICO: {total_stats['total_errors']} erros durante monitoramento!"
            )

        return total_stats

    except Exception as e:
        monitor_logger.error(f"Erro crítico no monitor: {str(e)}")
        alert_logger.critical(f"Monitor de fila falhou completamente: {str(e)}")
        raise self.retry(exc=e, countdown=300)  # Retry em 5 minutos

    finally:
        db.close()


# Task para processar uma empresa específica (útil para debug)
@celery_app.task(name='check_single_company_queue')
def check_single_company_queue(company_id: int):
    """Verifica fila de uma empresa específica"""

    monitor_logger.info(f"Verificação manual da fila - Empresa {company_id}")

    db = next(get_db())
    try:
        company = db.execute(
            text("""
                SELECT id, name, zapi_instance_id, zapi_token
                FROM companies
                WHERE id = :company_id
                AND zapi_instance_id IS NOT NULL
            """),
            {"company_id": company_id}
        ).fetchone()

        if not company:
            monitor_logger.error(f"Empresa {company_id} não encontrada ou sem Z-API configurado")
            return {"error": "Empresa não encontrada"}

        stats = process_company_queue(
            company.id,
            company.name,
            company.zapi_instance_id,
            company.zapi_token
        )

        monitor_logger.info(f"Verificação manual concluída: {stats}")
        return stats

    finally:
        db.close()
