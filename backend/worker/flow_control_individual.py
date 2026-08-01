"""
Sistema de Controle de Fluxos Individual - Extensão para controle por contato
"""
from functools import wraps
from datetime import datetime, timedelta
from sqlalchemy import text
import logging
from typing import Optional, Dict, Tuple
from backend.db import SessionLocal
from backend.worker.flow_control import (
    get_flow_state,
    get_step_timing,
    calculate_distributed_eta,
    _flow_control_cache,
    CACHE_TTL
)

logger = logging.getLogger(__name__)

# Cache separado para controles individuais
_contact_flow_cache = {}

def is_contact_flow_paused(
    company_id: int,
    contact_identifier: str,
    flow_type: str
) -> Tuple[bool, Optional[Dict]]:
    """
    Verifica se o fluxo está pausado para um contato específico

    Returns:
        Tuple[bool, Optional[Dict]]: (is_paused, pause_info)
    """
    cache_key = f"contact:{company_id}:{contact_identifier}:{flow_type}"

    # Verificar cache primeiro
    cached = _contact_flow_cache.get(cache_key)
    if cached and (datetime.utcnow() - cached['timestamp']).seconds < CACHE_TTL:
        return cached['is_paused'], cached.get('info')

    db = SessionLocal()
    try:
        # Verificar pausa específica do fluxo
        result = db.execute(
            text("""
                SELECT is_paused, pause_reason, expire_at
                FROM contact_flow_control
                WHERE company_id = :company_id
                  AND contact_identifier = :contact_identifier
                  AND flow_type = :flow_type
                  AND is_paused = true
                  AND (expire_at IS NULL OR expire_at > NOW())
                LIMIT 1
            """),
            {
                "company_id": company_id,
                "contact_identifier": contact_identifier,
                "flow_type": flow_type
            }
        ).fetchone()

        # Se não encontrou, verificar se tem pausa para "all" (todos os fluxos)
        if not result:
            result = db.execute(
                text("""
                    SELECT is_paused, pause_reason, expire_at
                    FROM contact_flow_control
                    WHERE company_id = :company_id
                      AND contact_identifier = :contact_identifier
                      AND flow_type = 'all'
                      AND is_paused = true
                      AND (expire_at IS NULL OR expire_at > NOW())
                    LIMIT 1
                """),
                {
                    "company_id": company_id,
                    "contact_identifier": contact_identifier
                }
            ).fetchone()

        if result:
            pause_info = {
                'pause_reason': result.pause_reason,
                'expire_at': result.expire_at
            }

            # Atualizar cache
            _contact_flow_cache[cache_key] = {
                'is_paused': True,
                'info': pause_info,
                'timestamp': datetime.utcnow()
            }

            return True, pause_info
        else:
            # Atualizar cache - não pausado
            _contact_flow_cache[cache_key] = {
                'is_paused': False,
                'info': None,
                'timestamp': datetime.utcnow()
            }

            return False, None

    except Exception as e:
        logger.error(f"[FlowControl] Erro ao verificar controle individual: {str(e)}")
        return False, None
    finally:
        db.close()

def check_flow_control_with_individual(flow_type: str, get_company_id_func=None):
    """
    Decorator aprimorado que verifica tanto controle por empresa quanto individual

    Args:
        flow_type: Tipo do fluxo
        get_company_id_func: Função opcional para extrair company_id
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Importar aqui para evitar circular import
            from backend.worker.flow_control import check_flow_control

            # Primeiro aplicar o decorator original (controle por empresa)
            original_decorator = check_flow_control(flow_type, get_company_id_func)
            result = original_decorator(func)(*args, **kwargs)

            # Se foi bloqueado pelo controle da empresa, retornar
            if result is None:
                return None

            # Agora verificar controle individual
            # Extrair informações necessárias
            company_id = None
            contact_identifier = None
            step_number = None

            # Obter company_id (mesma lógica do decorator original)
            if get_company_id_func:
                try:
                    company_id = get_company_id_func(*args, **kwargs)
                except Exception as e:
                    logger.error(f"[FlowControl] Erro ao obter company_id: {str(e)}")

            if not company_id and 'company_id' in kwargs:
                company_id = kwargs['company_id']

            # Para diferentes tipos de fluxo, buscar company_id apropriadamente
            if not company_id:
                if flow_type == 'follow_up' and 'lead_id' in kwargs:
                    lead_id = kwargs['lead_id']
                    db = SessionLocal()
                    try:
                        result = db.execute(
                            text("SELECT company_id FROM leads WHERE id = :lead_id"),
                            {"lead_id": lead_id}
                        ).fetchone()
                        if result:
                            company_id = result.company_id
                    finally:
                        db.close()
                # ... (outras lógicas para diferentes flow_types)

            # Obter identificador do contato
            if 'phone' in kwargs:
                contact_identifier = kwargs['phone']
            elif len(args) >= 5 and isinstance(args[4], str):
                contact_identifier = args[4]

            # Se não tem phone, tentar obter do lead_id/agendamento/etc
            if not contact_identifier:
                if flow_type == 'follow_up' and 'lead_id' in kwargs:
                    lead_id = kwargs['lead_id']
                    db = SessionLocal()
                    try:
                        result = db.execute(
                            text("SELECT phone FROM leads WHERE id = :lead_id"),
                            {"lead_id": lead_id}
                        ).fetchone()
                        if result:
                            contact_identifier = result.phone
                    finally:
                        db.close()

            # Verificar se está pausado individualmente
            if company_id and contact_identifier:
                is_paused, pause_info = is_contact_flow_paused(
                    company_id, contact_identifier, flow_type
                )

                if is_paused:
                    logger.info(
                        f"[FlowControl] Fluxo {flow_type} pausado individualmente "
                        f"para contato {contact_identifier}, company_id={company_id}. "
                        f"Motivo: {pause_info.get('pause_reason', 'Não especificado')}"
                    )

                    # Registrar tentativa bloqueada
                    try:
                        db = SessionLocal()
                        db.execute(
                            text("""
                                INSERT INTO contact_flow_control_history (
                                    contact_flow_control_id, action, reason, metadata
                                )
                                SELECT id, 'blocked', 'Mensagem bloqueada',
                                       jsonb_build_object('flow_type', :flow_type,
                                                         'task_name', :task_name)
                                FROM contact_flow_control
                                WHERE company_id = :company_id
                                  AND contact_identifier = :contact_identifier
                                  AND flow_type IN (:flow_type, 'all')
                                  AND is_paused = true
                                LIMIT 1
                            """),
                            {
                                "company_id": company_id,
                                "contact_identifier": contact_identifier,
                                "flow_type": flow_type,
                                "task_name": func.__name__
                            }
                        )
                        db.commit()
                    except Exception as e:
                        logger.error(f"[FlowControl] Erro ao registrar bloqueio: {str(e)}")
                    finally:
                        db.close()

                    # Verificar se deve reagendar ou cancelar definitivamente
                    if pause_info.get('expire_at'):
                        # Pausa temporária - reagendar para depois da expiração
                        expire_at = pause_info['expire_at']
                        if isinstance(expire_at, str):
                            expire_at = datetime.fromisoformat(expire_at)

                        if expire_at > datetime.utcnow():
                            # Reagendar para depois da expiração
                            try:
                                from celery import current_task

                                if current_task and hasattr(current_task, 'name'):
                                    task_func = current_task.app.tasks.get(current_task.name)
                                    if task_func:
                                        # Adicionar pequena margem após expiração
                                        eta = expire_at + timedelta(minutes=5)

                                        task_func.apply_async(
                                            args=args,
                                            kwargs=kwargs,
                                            eta=eta
                                        )

                                        logger.info(
                                            f"[FlowControl] Task reagendada para após "
                                            f"expiração da pausa: {eta}"
                                        )
                            except Exception as e:
                                logger.error(
                                    f"[FlowControl] Erro ao reagendar após pausa "
                                    f"temporária: {str(e)}"
                                )

                    # Retornar None para não executar a task
                    return None

            # Se não está pausado individualmente, executar normalmente
            return result

        return wrapper
    return decorator

def pause_contact_flow(
    company_id: int,
    contact_identifier: str,
    identifier_type: str,
    flow_type: str,
    reason: str,
    user_id: int,
    expire_at: Optional[datetime] = None
) -> bool:
    """
    Pausa um fluxo para um contato específico

    Args:
        company_id: ID da empresa
        contact_identifier: Telefone ou lead_id
        identifier_type: 'phone' ou 'lead_id'
        flow_type: Tipo do fluxo ou 'all' para todos
        reason: Motivo da pausa
        user_id: ID do usuário que está pausando
        expire_at: Data/hora de expiração (None = permanente)

    Returns:
        bool: True se pausou com sucesso
    """
    db = SessionLocal()
    try:
        # Inserir ou atualizar registro
        db.execute(
            text("""
                INSERT INTO contact_flow_control (
                    company_id, contact_identifier, identifier_type,
                    flow_type, is_paused, pause_reason, paused_at,
                    paused_by, expire_at
                ) VALUES (
                    :company_id, :contact_identifier, :identifier_type,
                    :flow_type, true, :reason, NOW(), :user_id, :expire_at
                )
                ON CONFLICT (company_id, contact_identifier, flow_type)
                DO UPDATE SET
                    is_paused = true,
                    pause_reason = EXCLUDED.pause_reason,
                    paused_at = NOW(),
                    paused_by = EXCLUDED.paused_by,
                    expire_at = EXCLUDED.expire_at,
                    resumed_at = NULL,
                    resumed_by = NULL,
                    updated_at = NOW()
                RETURNING id
            """),
            {
                "company_id": company_id,
                "contact_identifier": contact_identifier,
                "identifier_type": identifier_type,
                "flow_type": flow_type,
                "reason": reason,
                "user_id": user_id,
                "expire_at": expire_at
            }
        )

        # Obter o ID do registro
        control_id = db.execute(
            text("""
                SELECT id FROM contact_flow_control
                WHERE company_id = :company_id
                  AND contact_identifier = :contact_identifier
                  AND flow_type = :flow_type
            """),
            {
                "company_id": company_id,
                "contact_identifier": contact_identifier,
                "flow_type": flow_type
            }
        ).scalar()

        # Registrar no histórico
        if control_id:
            db.execute(
                text("""
                    INSERT INTO contact_flow_control_history (
                        contact_flow_control_id, action, reason, performed_by
                    ) VALUES (
                        :control_id, 'paused', :reason, :user_id
                    )
                """),
                {
                    "control_id": control_id,
                    "reason": reason,
                    "user_id": user_id
                }
            )

        db.commit()

        # Limpar cache
        clear_contact_cache(company_id, contact_identifier, flow_type)

        logger.info(
            f"[FlowControl] Fluxo {flow_type} pausado para contato "
            f"{contact_identifier} na empresa {company_id}. "
            f"Expira em: {expire_at if expire_at else 'Nunca'}"
        )

        return True

    except Exception as e:
        logger.error(f"[FlowControl] Erro ao pausar fluxo individual: {str(e)}")
        db.rollback()
        return False
    finally:
        db.close()

def resume_contact_flow(
    company_id: int,
    contact_identifier: str,
    flow_type: str,
    user_id: int
) -> bool:
    """
    Retoma um fluxo pausado para um contato
    """
    db = SessionLocal()
    try:
        # Atualizar registro
        result = db.execute(
            text("""
                UPDATE contact_flow_control
                SET is_paused = false,
                    resumed_at = NOW(),
                    resumed_by = :user_id,
                    updated_at = NOW()
                WHERE company_id = :company_id
                  AND contact_identifier = :contact_identifier
                  AND flow_type = :flow_type
                  AND is_paused = true
                RETURNING id
            """),
            {
                "company_id": company_id,
                "contact_identifier": contact_identifier,
                "flow_type": flow_type,
                "user_id": user_id
            }
        )

        control_id = result.scalar()
        if control_id:
            # Registrar no histórico
            db.execute(
                text("""
                    INSERT INTO contact_flow_control_history (
                        contact_flow_control_id, action, reason, performed_by
                    ) VALUES (
                        :control_id, 'resumed', 'Fluxo retomado manualmente', :user_id
                    )
                """),
                {
                    "control_id": control_id,
                    "user_id": user_id
                }
            )

            db.commit()

            # Limpar cache
            clear_contact_cache(company_id, contact_identifier, flow_type)

            logger.info(
                f"[FlowControl] Fluxo {flow_type} retomado para contato "
                f"{contact_identifier} na empresa {company_id}"
            )

            return True
        else:
            logger.warning(
                f"[FlowControl] Tentativa de retomar fluxo não pausado: "
                f"{flow_type} para {contact_identifier}"
            )
            return False

    except Exception as e:
        logger.error(f"[FlowControl] Erro ao retomar fluxo: {str(e)}")
        db.rollback()
        return False
    finally:
        db.close()

def clear_contact_cache(
    company_id: int = None,
    contact_identifier: str = None,
    flow_type: str = None
):
    """
    Limpa o cache de controle individual
    """
    global _contact_flow_cache

    if company_id and contact_identifier and flow_type:
        # Limpar entrada específica
        cache_key = f"contact:{company_id}:{contact_identifier}:{flow_type}"
        if cache_key in _contact_flow_cache:
            del _contact_flow_cache[cache_key]

        # Também limpar entrada "all" se existir
        cache_key_all = f"contact:{company_id}:{contact_identifier}:all"
        if cache_key_all in _contact_flow_cache:
            del _contact_flow_cache[cache_key_all]

    elif company_id and contact_identifier:
        # Limpar todas as entradas do contato
        prefix = f"contact:{company_id}:{contact_identifier}:"
        keys_to_remove = [k for k in _contact_flow_cache.keys() if k.startswith(prefix)]
        for key in keys_to_remove:
            del _contact_flow_cache[key]

    elif company_id:
        # Limpar todas as entradas da empresa
        prefix = f"contact:{company_id}:"
        keys_to_remove = [k for k in _contact_flow_cache.keys() if k.startswith(prefix)]
        for key in keys_to_remove:
            del _contact_flow_cache[key]

    else:
        # Limpar todo o cache
        _contact_flow_cache.clear()

def get_contact_pause_stats(company_id: int) -> Dict:
    """
    Retorna estatísticas de pausas individuais da empresa
    """
    db = SessionLocal()
    try:
        stats = db.execute(
            text("""
                SELECT
                    flow_type,
                    COUNT(*) as total_paused,
                    COUNT(*) FILTER (WHERE pause_reason ILIKE '%opt%out%') as opt_outs,
                    COUNT(*) FILTER (WHERE expire_at IS NOT NULL) as temporary,
                    COUNT(*) FILTER (WHERE expire_at IS NULL) as permanent
                FROM contact_flow_control
                WHERE company_id = :company_id
                  AND is_paused = true
                  AND (expire_at IS NULL OR expire_at > NOW())
                GROUP BY flow_type
                ORDER BY flow_type
            """),
            {"company_id": company_id}
        ).fetchall()

        return {
            "by_flow_type": [
                {
                    "flow_type": s.flow_type,
                    "total_paused": s.total_paused,
                    "opt_outs": s.opt_outs,
                    "temporary": s.temporary,
                    "permanent": s.permanent
                }
                for s in stats
            ],
            "cache_size": len([k for k in _contact_flow_cache.keys()
                             if k.startswith(f"contact:{company_id}:")])
        }

    except Exception as e:
        logger.error(f"[FlowControl] Erro ao obter estatísticas: {str(e)}")
        return {"error": str(e)}
    finally:
        db.close()