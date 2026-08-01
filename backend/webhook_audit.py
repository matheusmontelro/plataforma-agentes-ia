# backend/webhook_audit.py
"""
Sistema de auditoria para rastrear todas as mensagens recebidas via webhook Z-API
"""
from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
from backend.runtime_settings import FALLBACK_MESSAGES_DIR, INVALID_MESSAGES_DIR

logger = logging.getLogger(__name__)

def save_webhook_audit(
    db: Session,
    instance_id: str,
    data: dict,
    *,
    company_id: Optional[int] = None,
    message_id: Optional[str] = None,
    event_type: Optional[str] = None,
) -> int:
    """
    Salva mensagem recebida na tabela de auditoria

    Args:
        db: Sessão do banco de dados
        instance_id: ID da instância Z-API
        data: Payload completo recebido do provider
        company_id: Empresa já resolvida para o webhook, quando disponível
        message_id: ID normalizado da mensagem, quando disponível
        event_type: Evento do provider para auditoria e dedupe por namespace

    Returns:
        int: ID do registro criado na tabela webhook_audit
    """
    try:
        resolved_message_id = (
            message_id
            if message_id is not None
            else data.get('messageId') or data.get('id') or ''
        )
        phone = data.get('phone') or data.get('from') or ''

        # Detectar tipo de mensagem
        if event_type:
            message_type = f'waha:{event_type}'
        elif 'text' in data:
            message_type = 'text'
        elif 'image' in data:
            message_type = 'image'
        elif 'audio' in data:
            message_type = 'audio'
        elif 'video' in data:
            message_type = 'video'
        elif 'pollVote' in data:
            message_type = 'poll_response'
        elif data.get('type'):
            message_type = str(data['type'])
        else:
            message_type = 'unknown'

        result = db.execute(text("""
            INSERT INTO webhook_audit
            (instance_id, company_id, message_id, phone, message_type, message_data, status)
            VALUES (:instance_id, :company_id, :message_id, :phone, :message_type, :message_data, 'received')
            RETURNING id
        """), {
            'instance_id': instance_id,
            'company_id': company_id,
            'message_id': resolved_message_id,
            'phone': phone,
            'message_type': message_type,
            'message_data': json.dumps(data)
        })
        db.commit()

        audit_id = result.fetchone()[0]
        logger.info(f"[WEBHOOK_AUDIT] Mensagem registrada: id={audit_id}, type={message_type}, phone={phone}")
        return audit_id

    except Exception as e:
        logger.error(f"[WEBHOOK_AUDIT] Erro ao salvar auditoria: {e}")
        db.rollback()
        raise

def update_audit_status(db: Session, audit_id: int, status: str, task_id: str = None, error: str = None):
    """
    Atualiza status da mensagem na auditoria

    Args:
        db: Sessão do banco de dados
        audit_id: ID do registro na webhook_audit
        status: Novo status (queued, processing, completed, failed, etc)
        task_id: ID da task do Celery (opcional)
        error: Mensagem de erro (opcional)
    """
    try:
        params = {'id': audit_id, 'status': status}

        extra_fields = []
        if task_id:
            extra_fields.append("task_id = :task_id")
            params['task_id'] = task_id
        if error:
            extra_fields.append("error_message = :error")
            params['error'] = error
        if status == 'completed':
            extra_fields.append("processed_at = NOW()")
        if status in ['failed', 'queue_failed', 'company_not_found']:
            extra_fields.append("retry_count = retry_count + 1")

        extra_sql = ', '.join(extra_fields)
        if extra_sql:
            extra_sql = ', ' + extra_sql

        db.execute(text(f"""
            UPDATE webhook_audit
            SET status = :status, updated_at = NOW(){extra_sql}
            WHERE id = :id
        """), params)
        db.commit()

        logger.info(f"[WEBHOOK_AUDIT] Status atualizado: id={audit_id}, status={status}")

    except Exception as e:
        logger.error(f"[WEBHOOK_AUDIT] Erro ao atualizar status: {e}")
        db.rollback()
        raise

def update_audit_company_id(db: Session, audit_id: int, company_id: int):
    """
    Atualiza company_id na auditoria após identificar a empresa

    Args:
        db: Sessão do banco de dados
        audit_id: ID do registro na webhook_audit
        company_id: ID da empresa identificada
    """
    try:
        db.execute(text("""
            UPDATE webhook_audit
            SET company_id = :company_id, updated_at = NOW()
            WHERE id = :id
        """), {
            'id': audit_id,
            'company_id': company_id
        })
        db.commit()

    except Exception as e:
        logger.error(f"[WEBHOOK_AUDIT] Erro ao atualizar company_id: {e}")
        db.rollback()

def save_to_fallback_queue(instance_id: str, data: dict):
    """
    Salva mensagem em arquivo quando Celery falha
    Sistema de fallback para garantir que nenhuma mensagem seja perdida

    Args:
        instance_id: ID da instância Z-API
        data: Payload completo recebido do Z-API
    """
    try:
        fallback_dir = FALLBACK_MESSAGES_DIR
        fallback_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{instance_id}_{timestamp}.json"
        filepath = fallback_dir / filename

        with open(filepath, 'w') as f:
            json.dump({
                'instance_id': instance_id,
                'data': data,
                'timestamp': timestamp,
                'created_at': datetime.now().isoformat()
            }, f, indent=2)

        logger.error(f"[FALLBACK] Mensagem salva em: {filepath}")
        return str(filepath)

    except Exception as e:
        logger.critical(f"[FALLBACK] ERRO CRÍTICO ao salvar fallback: {e}")
        # Como último recurso, log o payload completo
        logger.critical(f"[FALLBACK] Payload perdido: {json.dumps(data)}")

def save_invalid_json(instance_id: str, raw_data: bytes):
    """
    Salva dados inválidos para análise posterior

    Args:
        instance_id: ID da instância Z-API
        raw_data: Dados brutos recebidos
    """
    try:
        invalid_dir = INVALID_MESSAGES_DIR
        invalid_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"invalid_{instance_id}_{timestamp}.bin"
        filepath = invalid_dir / filename

        with open(filepath, 'wb') as f:
            f.write(raw_data)

        logger.error(f"[INVALID_JSON] Dados salvos em: {filepath}")

        # Tentar salvar também como texto para análise
        try:
            text_content = raw_data.decode('utf-8', errors='replace')
            text_filepath = invalid_dir / f"invalid_{instance_id}_{timestamp}.txt"
            with open(text_filepath, 'w') as f:
                f.write(text_content)
        except:
            pass

    except Exception as e:
        logger.critical(f"[INVALID_JSON] Erro ao salvar dados inválidos: {e}")

def get_audit_stats(db: Session, hours: int = 24) -> dict:
    """
    Retorna estatísticas de auditoria para monitoramento

    Args:
        db: Sessão do banco de dados
        hours: Quantas horas para trás buscar (padrão: 24)

    Returns:
        dict: Estatísticas de processamento
    """
    try:
        stats = db.execute(text(f"""
            SELECT
                status,
                COUNT(*) as count,
                MAX(created_at) as last_message,
                AVG(EXTRACT(EPOCH FROM (processed_at - created_at))) as avg_processing_time
            FROM webhook_audit
            WHERE created_at > NOW() - INTERVAL '{hours} hours'
            GROUP BY status
            ORDER BY count DESC
        """)).fetchall()

        total = db.execute(text(f"""
            SELECT COUNT(*) as total
            FROM webhook_audit
            WHERE created_at > NOW() - INTERVAL '{hours} hours'
        """)).fetchone()

        return {
            'period_hours': hours,
            'total_messages': total[0] if total else 0,
            'by_status': [
                {
                    'status': s.status,
                    'count': s.count,
                    'last_message': s.last_message.isoformat() if s.last_message else None,
                    'avg_processing_time': float(s.avg_processing_time) if s.avg_processing_time else None
                }
                for s in stats
            ]
        }

    except Exception as e:
        logger.error(f"[WEBHOOK_AUDIT] Erro ao obter estatísticas: {e}")
        return {}

def get_failed_messages(db: Session, hours: int = 24, limit: int = 100) -> list:
    """
    Retorna mensagens que falharam para reprocessamento

    Args:
        db: Sessão do banco de dados
        hours: Quantas horas para trás buscar
        limit: Limite de mensagens a retornar

    Returns:
        list: Lista de mensagens falhadas
    """
    try:
        failed = db.execute(text(f"""
            SELECT
                id,
                instance_id,
                company_id,
                message_id,
                phone,
                message_type,
                message_data,
                status,
                error_message,
                retry_count,
                created_at
            FROM webhook_audit
            WHERE status IN ('received', 'queued', 'queue_failed', 'failed')
            AND created_at > NOW() - INTERVAL '{hours} hours'
            ORDER BY created_at ASC
            LIMIT :limit
        """), {'limit': limit}).fetchall()

        return [
            {
                'id': f.id,
                'instance_id': f.instance_id,
                'company_id': f.company_id,
                'message_id': f.message_id,
                'phone': f.phone,
                'message_type': f.message_type,
                'message_data': f.message_data,
                'status': f.status,
                'error_message': f.error_message,
                'retry_count': f.retry_count,
                'created_at': f.created_at.isoformat() if f.created_at else None
            }
            for f in failed
        ]

    except Exception as e:
        logger.error(f"[WEBHOOK_AUDIT] Erro ao buscar mensagens falhadas: {e}")
        return []
