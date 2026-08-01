"""
Sistema de Controle de Fluxos - Decorator para pausar/retomar fluxos automatizados
"""
from functools import wraps
from datetime import datetime, timedelta
from sqlalchemy import text
import logging
import random
from typing import Optional, Dict, Tuple
from backend.db import SessionLocal

logger = logging.getLogger(__name__)

# Cache em memória com TTL de 5 minutos
_flow_control_cache = {}
_contact_flow_cache = {}  # Cache para controles individuais
CACHE_TTL = 300  # 5 minutos

def get_flow_state(company_id: int, flow_type: str) -> bool:
    """
    Verifica se um fluxo está pausado (com cache)

    Args:
        company_id: ID da empresa
        flow_type: Tipo do fluxo ('follow_up', 'noshow', etc.)

    Returns:
        bool: True se o fluxo está pausado, False caso contrário
    """
    cache_key = f"{company_id}:{flow_type}"
    cached = _flow_control_cache.get(cache_key)

    # Verificar cache
    if cached and (datetime.utcnow() - cached['timestamp']).seconds < CACHE_TTL:
        return cached['is_paused']

    db = SessionLocal()
    try:
        result = db.execute(
            text("""
                SELECT is_paused
                FROM flow_control_states
                WHERE company_id = :company_id
                  AND flow_type = :flow_type
                LIMIT 1
            """),
            {"company_id": company_id, "flow_type": flow_type}
        ).fetchone()

        is_paused = result.is_paused if result else False

        # Atualizar cache
        _flow_control_cache[cache_key] = {
            'is_paused': is_paused,
            'timestamp': datetime.utcnow()
        }

        return is_paused

    except Exception as e:
        logger.error(f"[FlowControl] Erro ao verificar estado do fluxo: {str(e)}")
        # Em caso de erro, assumir que não está pausado para não bloquear o sistema
        return False
    finally:
        db.close()

def get_step_timing(flow_type: str, step_number: int, company_id: int = None):
    """
    Busca as configurações de tempo do step

    Args:
        flow_type: Tipo do fluxo
        step_number: Número do step
        company_id: ID da empresa (opcional para alguns fluxos)

    Returns:
        tuple: (send_after, send_after_unit) ou (None, None) se não encontrar
    """
    db = SessionLocal()
    try:
        if flow_type == 'follow_up':
            result = db.execute(
                text("""
                    SELECT send_after, send_after_unit
                    FROM follow_up_steps
                    WHERE step_number = :step_number
                    LIMIT 1
                """),
                {"step_number": step_number}
            ).fetchone()

        elif flow_type == 'noshow':
            result = db.execute(
                text("""
                    SELECT nfs.send_after, nfs.send_after_unit
                    FROM noshow_follow_up_steps nfs
                    JOIN noshow_follow_up_sequences seq ON seq.id = nfs.noshow_follow_up_sequence_id
                    WHERE nfs.step_number = :step_number
                      AND seq.company_id = :company_id
                    LIMIT 1
                """),
                {"step_number": step_number, "company_id": company_id}
            ).fetchone()

        elif flow_type == 'confirmation':
            result = db.execute(
                text("""
                    SELECT cs.send_after, cs.send_after_unit
                    FROM confirmation_steps cs
                    JOIN confirmation_sequences seq ON seq.id = cs.confirmation_sequence_id
                    WHERE cs.step_number = :step_number
                      AND seq.company_id = :company_id
                    LIMIT 1
                """),
                {"step_number": step_number, "company_id": company_id}
            ).fetchone()

        elif flow_type == 'pos_consulta':
            result = db.execute(
                text("""
                    SELECT pcs.send_after, pcs.send_after_unit
                    FROM pos_consulta_steps pcs
                    JOIN pos_consulta_sequences seq ON seq.id = pcs.pos_consulta_sequence_id
                    WHERE pcs.step_number = :step_number
                      AND seq.company_id = :company_id
                    LIMIT 1
                """),
                {"step_number": step_number, "company_id": company_id}
            ).fetchone()

        elif flow_type == 'pos_venda':
            result = db.execute(
                text("""
                    SELECT pvs.send_after, pvs.send_after_unit
                    FROM pos_venda_steps pvs
                    JOIN pos_venda_sequences seq ON seq.id = pvs.pos_venda_sequence_id
                    WHERE pvs.step_number = :step_number
                      AND seq.company_id = :company_id
                    LIMIT 1
                """),
                {"step_number": step_number, "company_id": company_id}
            ).fetchone()
        else:
            return None, None

        if result:
            return result.send_after, result.send_after_unit
        return None, None

    except Exception as e:
        logger.error(f"[FlowControl] Erro ao buscar timing do step: {str(e)}")
        return None, None
    finally:
        db.close()

def calculate_distributed_eta(base_time: datetime, send_after: int, send_after_unit: str,
                            distribute: bool = True) -> datetime:
    """
    Calcula o ETA respeitando o send_after do step e distribuindo as mensagens

    Args:
        base_time: Tempo base para cálculo
        send_after: Tempo de espera
        send_after_unit: Unidade (minutes, hours, days)
        distribute: Se deve distribuir aleatoriamente

    Returns:
        datetime: ETA calculado
    """
    # Calcular tempo base conforme configuração do step
    if send_after_unit == "minutes":
        eta = base_time + timedelta(minutes=send_after)
    elif send_after_unit == "hours":
        eta = base_time + timedelta(hours=send_after)
    elif send_after_unit == "days":
        eta = base_time + timedelta(days=send_after)
    else:
        eta = base_time

    # Se deve distribuir, adicionar variação aleatória
    if distribute and send_after_unit in ["hours", "days"]:
        # Adicionar variação de até 2 horas para distribuir melhor
        random_minutes = random.randint(0, 120)
        eta = eta + timedelta(minutes=random_minutes)

        # Garantir que está dentro do horário comercial (8h às 18h)
        if eta.hour < 8:
            eta = eta.replace(hour=8, minute=random.randint(0, 59))
        elif eta.hour >= 18:
            # Mover para o próximo dia útil
            eta = eta + timedelta(days=1)
            eta = eta.replace(hour=8, minute=random.randint(0, 59))

    return eta

def check_flow_control(flow_type: str, get_company_id_func=None):
    """
    Decorator inteligente para verificar se o fluxo está pausado.
    Se pausado, reagenda a task respeitando as configurações de tempo do step.

    Args:
        flow_type: Tipo do fluxo ('follow_up', 'noshow', 'confirmation', 'pos_consulta', 'pos_venda')
        get_company_id_func: Função opcional que extrai company_id dos argumentos da task
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Extrair parâmetros dos argumentos
            company_id = None
            lead_id = None
            step_number = None

            # Se foi fornecida uma função para obter company_id, usá-la
            if get_company_id_func:
                try:
                    company_id = get_company_id_func(*args, **kwargs)
                except Exception as e:
                    logger.error(f"[FlowControl] Erro ao obter company_id com função customizada: {str(e)}")

            # Caso contrário, tentar obter dos parâmetros padrão
            if not company_id:
                # Tentar pegar do kwargs primeiro
                if 'company_id' in kwargs:
                    company_id = kwargs['company_id']
                # Remover a lógica genérica de pegar da posição 3
                # pois cada tipo de fluxo tem sua própria estrutura

            # Para noshow, o company_id vem como terceiro parâmetro
            if not company_id and flow_type == 'noshow':
                if len(args) >= 3 and isinstance(args[2], int):
                    company_id = args[2]
                    logger.debug(f"[FlowControl] company_id={company_id} obtido do args[2] para noshow")

            # Para follow_up, se não achou company_id e tem lead_id, buscar no banco
            if not company_id and flow_type == 'follow_up':
                if 'lead_id' in kwargs:
                    lead_id = kwargs['lead_id']
                elif len(args) >= 1:
                    lead_id = args[0]

                if lead_id:
                    # Buscar company_id do lead
                    db = SessionLocal()
                    try:
                        result = db.execute(
                            text("SELECT company_id FROM leads WHERE id = :lead_id"),
                            {"lead_id": lead_id}
                        ).fetchone()
                        if result:
                            company_id = result.company_id
                    except Exception as e:
                        logger.error(f"[FlowControl] Erro ao buscar company_id do lead: {str(e)}")
                    finally:
                        db.close()

            # Para confirmation, buscar company_id através do agendamento_id
            if not company_id and flow_type == 'confirmation':
                agendamento_id = None
                if 'agendamento_id' in kwargs:
                    agendamento_id = kwargs['agendamento_id']
                elif len(args) >= 1:
                    agendamento_id = args[0]

                if agendamento_id:
                    # Buscar company_id do agendamento
                    db = SessionLocal()
                    try:
                        result = db.execute(
                            text("SELECT company_id FROM agendamentos WHERE id = :agendamento_id"),
                            {"agendamento_id": agendamento_id}
                        ).fetchone()
                        if result:
                            company_id = result.company_id
                            logger.info(f"[FlowControl] company_id={company_id} obtido do agendamento_id={agendamento_id}")
                    except Exception as e:
                        logger.error(f"[FlowControl] Erro ao buscar company_id do agendamento: {str(e)}")
                    finally:
                        db.close()

            # Para pos_consulta, buscar company_id através do comparecimento_id
            if not company_id and flow_type == 'pos_consulta':
                comparecimento_id = None
                if 'comparecimento_id' in kwargs:
                    comparecimento_id = kwargs['comparecimento_id']
                elif len(args) >= 1:
                    comparecimento_id = args[0]

                if comparecimento_id:
                    # Buscar company_id do comparecimento
                    db = SessionLocal()
                    try:
                        result = db.execute(
                            text("SELECT company_id FROM comparecimentos WHERE id = :comparecimento_id"),
                            {"comparecimento_id": comparecimento_id}
                        ).fetchone()
                        if result:
                            company_id = result.company_id
                            logger.info(f"[FlowControl] company_id={company_id} obtido do comparecimento_id={comparecimento_id}")
                    except Exception as e:
                        logger.error(f"[FlowControl] Erro ao buscar company_id do comparecimento: {str(e)}")
                    finally:
                        db.close()

            # Para pos_venda, buscar company_id através do venda_id
            if not company_id and flow_type == 'pos_venda':
                venda_id = None
                if 'venda_id' in kwargs:
                    venda_id = kwargs['venda_id']
                elif len(args) >= 1:
                    venda_id = args[0]

                if venda_id:
                    # Buscar company_id da venda
                    db = SessionLocal()
                    try:
                        result = db.execute(
                            text("SELECT company_id FROM vendas WHERE id = :venda_id"),
                            {"venda_id": venda_id}
                        ).fetchone()
                        if result:
                            company_id = result.company_id
                            logger.info(f"[FlowControl] company_id={company_id} obtido do venda_id={venda_id}")
                    except Exception as e:
                        logger.error(f"[FlowControl] Erro ao buscar company_id da venda: {str(e)}")
                    finally:
                        db.close()

            # Obter lead_id e step_number se ainda não temos
            if not lead_id:
                if 'lead_id' in kwargs:
                    lead_id = kwargs['lead_id']
                elif len(args) >= 1:
                    lead_id = args[0]

            if not step_number:
                if 'step_number' in kwargs:
                    step_number = kwargs['step_number']
                elif len(args) >= 2:
                    step_number = args[1]

            if not company_id:
                logger.error(f"[FlowControl] company_id não encontrado para {flow_type}")
                return func(*args, **kwargs)

            # Verificar se está pausado
            if get_flow_state(company_id, flow_type):
                logger.info(
                    f"[FlowControl] Fluxo {flow_type} pausado para company_id={company_id}, "
                    f"lead_id={lead_id}, step={step_number}"
                )

                # SOLUÇÃO CORRETA: Cancelar task pausada ao invés de reagendar
                logger.info(
                    f"[FlowControl] Task {flow_type} cancelada - "
                    f"fluxo pausado para company_id={company_id}, lead_id={lead_id}, step={step_number}"
                )

                # Retornar sem executar nem reagendar
                return None

            # Verificar controle individual de contato
            contact_identifier = None

            # Tentar obter phone dos kwargs ou args
            if 'phone' in kwargs:
                contact_identifier = kwargs['phone']
            else:
                # Buscar telefone em qualquer posição dos args
                for i, arg in enumerate(args):
                    if isinstance(arg, str) and len(arg) >= 10:
                        # Verificar se parece um telefone (apenas dígitos ou começa com +)
                        if arg.isdigit() or (arg.startswith('+') and arg[1:].isdigit()):
                            contact_identifier = arg
                            logger.debug(f"[FlowControl] contact_identifier obtido de args[{i}]: {contact_identifier}")
                            break

            # Se não tem phone, tentar obter do banco baseado no lead_id/agendamento/etc
            if not contact_identifier:
                if flow_type == 'follow_up' and lead_id:
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

                elif flow_type == 'confirmation' and 'agendamento_id' in kwargs:
                    agendamento_id = kwargs['agendamento_id']
                    db = SessionLocal()
                    try:
                        result = db.execute(
                            text("SELECT l.phone FROM agendamentos a JOIN leads l ON l.id = a.lead_id WHERE a.id = :agendamento_id"),
                            {"agendamento_id": agendamento_id}
                        ).fetchone()
                        if result:
                            contact_identifier = result.phone
                    finally:
                        db.close()

            # Verificar se está pausado individualmente
            if company_id and contact_identifier:
                is_paused, pause_info = is_contact_flow_paused(company_id, contact_identifier, flow_type)

                if is_paused:
                    logger.info(
                        f"[FlowControl] Fluxo {flow_type} pausado individualmente para "
                        f"contato {contact_identifier}, company_id={company_id}. "
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

                    # SOLUÇÃO CORRETA: Cancelar task pausada individualmente
                    expire_info = f" (expira: {pause_info.get('expire_at')})" if pause_info.get('expire_at') else " (permanente)"
                    logger.info(
                        f"[FlowControl] Task {flow_type} cancelada - "
                        f"contato {contact_identifier} pausado individualmente{expire_info}"
                    )

                    return None

            # Se não está pausado, executar normalmente
            return func(*args, **kwargs)

        return wrapper
    return decorator

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

def clear_cache(company_id: int = None, flow_type: str = None):
    """
    Limpa o cache de controle de fluxo

    Args:
        company_id: ID da empresa (opcional, se não fornecido limpa todo o cache)
        flow_type: Tipo do fluxo (opcional, requer company_id)
    """
    global _flow_control_cache

    if company_id and flow_type:
        cache_key = f"{company_id}:{flow_type}"
        if cache_key in _flow_control_cache:
            del _flow_control_cache[cache_key]
            logger.info(f"[FlowControl] Cache limpo para {cache_key}")
    elif company_id:
        # Limpar todos os fluxos da empresa
        keys_to_remove = [k for k in _flow_control_cache.keys() if k.startswith(f"{company_id}:")]
        for key in keys_to_remove:
            del _flow_control_cache[key]
        logger.info(f"[FlowControl] Cache limpo para company_id={company_id} ({len(keys_to_remove)} entradas)")
    else:
        # Limpar todo o cache
        _flow_control_cache.clear()
        logger.info("[FlowControl] Todo o cache foi limpo")

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

def get_cache_stats():
    """
    Retorna estatísticas do cache (útil para debug)

    Returns:
        dict: Estatísticas do cache
    """
    now = datetime.utcnow()
    stats = {
        'total_entries': len(_flow_control_cache),
        'entries': []
    }

    for key, value in _flow_control_cache.items():
        age_seconds = (now - value['timestamp']).seconds
        stats['entries'].append({
            'key': key,
            'is_paused': value['is_paused'],
            'age_seconds': age_seconds,
            'expired': age_seconds >= CACHE_TTL
        })

    return stats