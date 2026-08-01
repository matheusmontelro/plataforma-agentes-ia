
"""
Módulo para verificação de disponibilidade real de slots antes de confirmar agendamentos.
Funciona como uma camada adicional de segurança junto com a validação contextual.
"""

import logging
import re
from datetime import datetime
from typing import Tuple, Optional
from ..scheduling.scheduling_service import SchedulingService, SP_TZ

logger = logging.getLogger(__name__)

def format_date_time(date_str: str, time_str: str) -> str:
    """
    Formata strings de data e hora para o formato padrão "DD/MM/YYYY HH:MM".
    Aceita formatos variados de entrada.

    Args:
        date_str: String de data (ex: "13/03", "13/03/2025", "13-03-2025")
        time_str: String de horário (ex: "14:00", "14h", "14", "2 da tarde")

    Returns:
        String formatada "DD/MM/YYYY HH:MM" ou None se não for possível formatar
    """
    # Processar data
    try:
        # Detectar formato da data
        if len(date_str.split('/')) == 2:  # Formato "DD/MM"
            day, month = date_str.split('/')
            year = datetime.now(SP_TZ).year
            date_str = f"{day.zfill(2)}/{month.zfill(2)}/{year}"
        elif '-' in date_str:  # Formato com hífen "DD-MM-YYYY"
            parts = date_str.split('-')
            if len(parts) == 3:
                day, month, year = parts
            else:
                day, month = parts
                year = datetime.now(SP_TZ).year
            date_str = f"{day.zfill(2)}/{month.zfill(2)}/{year}"
    except Exception as e:
        logger.error(f"[SlotVerification] Erro ao processar data '{date_str}': {e}")
        return None

    # Processar horário
    try:
        # Converter formato de horário
        if 'h' in time_str.lower() and ':' not in time_str:
            time_str = time_str.lower().replace('h', ':00')

        # Lidar com "da tarde" (adicionar 12 horas)
        if 'tarde' in time_str.lower() or 'noite' in time_str.lower():
            hour_parts = time_str.split()
            try:
                hour = int(hour_parts[0])
                if hour < 12:
                    hour += 12
                time_str = f"{hour}:00"
            except (ValueError, IndexError):
                pass

        # Garantir formato HH:MM
        if ':' not in time_str:
            time_str = f"{time_str}:00"

        # Garantir 2 dígitos para hora
        hour, minute = time_str.split(':')
        time_str = f"{hour.zfill(2)}:{minute}"

    except Exception as e:
        logger.error(f"[SlotVerification] Erro ao processar horário '{time_str}': {e}")
        return None

    return f"{date_str} {time_str}"

def verify_slot_availability(db, company_id: int, date_str: str, time_str: str) -> Tuple[bool, Optional[str]]:
    """
    Verifica se o slot escolhido está realmente disponível na lista de slots da empresa.

    Args:
        db: Sessão do banco de dados
        company_id: ID da empresa
        date_str: String de data (ex: "13/03", "13/03/2025")
        time_str: String de horário (ex: "14:00", "14h", "14")

    Returns:
        Tupla (disponível, slot_formatado)
        - disponível: Boolean indicando se o slot está disponível
        - slot_formatado: String no formato "DD/MM/YYYY HH:MM" ou None se inválido
    """
    # Formatar data e hora para padrão
    formatted_slot = format_date_time(date_str, time_str)
    if not formatted_slot:
        logger.error(f"[SlotVerification] Não foi possível formatar data '{date_str}' e hora '{time_str}'")
        return False, None

    # Registrar para debugging
    logger.info(f"[SlotVerification] Verificando disponibilidade para: '{formatted_slot}'")

    try:
        # Obter lista de slots disponíveis
        scheduling_service = SchedulingService(db=db, company_id=company_id)
        available_slots = scheduling_service.get_next_available_slots()

        # Verificar se o slot formatado está na lista
        if formatted_slot in available_slots:
            logger.info(f"[SlotVerification] Slot '{formatted_slot}' está disponível")

            # ADICIONAR AQUI - Marcar no state_machine se estiver disponível
            # Recuperar state_machine se possível a partir dos parâmetros do request
            try:
                from flask import g
                if hasattr(g, 'state_machine'):
                    g.state_machine.set_state_data("confirmation_asked", True)
                    logger.info("[SlotVerification] Marcando confirmation_asked=True")
            except:
                # Caso não consiga acessar o state_machine aqui, isso será tratado em outro lugar
                pass

            return True, formatted_slot

        # Verificar pela lógica de proximidade se houver erro na formatação
        slot_day_month = formatted_slot.split()[0].rsplit('/', 1)[0]  # "DD/MM" da data formatada
        slot_hour = formatted_slot.split()[1].split(':')[0]  # "HH" do horário formatado

        # Procurar alternativas próximas
        close_matches = []
        for available in available_slots:
            avail_day_month = available.split()[0].rsplit('/', 1)[0]  # "DD/MM"
            avail_hour = available.split()[1].split(':')[0]  # "HH"

            # Se for mesmo dia e hora próxima
            if avail_day_month == slot_day_month and abs(int(avail_hour) - int(slot_hour)) <= 1:
                close_matches.append(available)

        if close_matches:
            logger.warning(
                f"[SlotVerification] Slot '{formatted_slot}' não está disponível, "
                f"mas há {len(close_matches)} slots próximos: {close_matches}"
            )
            return False, formatted_slot

        logger.error(f"[SlotVerification] Slot '{formatted_slot}' não está disponível. Slots disponíveis: {available_slots}")
        return False, formatted_slot

    except Exception as e:
        logger.error(f"[SlotVerification] Erro ao verificar disponibilidade: {e}")
        return False, formatted_slot

def suggest_alternative_slots(db, company_id: int, date_str: str, time_str: str, max_suggestions: int = 2) -> list:
    """
    Sugere slots alternativos se o solicitado não estiver disponível.

    Args:
        db: Sessão do banco de dados
        company_id: ID da empresa
        date_str: String de data (ex: "13/03", "13/03/2025")
        time_str: String de horário (ex: "14:00", "14h")
        max_suggestions: Número máximo de slots alternativos a sugerir

    Returns:
        Lista de slots alternativos no formato "DD/MM/YYYY HH:MM"
    """
    try:
        # Tentar formatar a data e hora recebidas
        formatted_slot = format_date_time(date_str, time_str)
        if not formatted_slot:
            return []

        # Obter slots disponíveis
        scheduling_service = SchedulingService(db=db, company_id=company_id)
        available_slots = scheduling_service.get_next_available_slots()

        if not available_slots:
            return []

        # Extrair componentes da data/hora solicitada
        try:
            requested_dt = datetime.strptime(formatted_slot, "%d/%m/%Y %H:%M").replace(tzinfo=SP_TZ)
            requested_date = requested_dt.date()
            requested_hour = requested_dt.hour
            is_morning = requested_hour < 12
        except Exception:
            # Fallback para extração mais simples se o parsing falhar
            date_part = formatted_slot.split()[0]
            time_part = formatted_slot.split()[1]
            hour = int(time_part.split(':')[0])
            is_morning = hour < 12

        # Tentar encontrar slots no mesmo dia primeiro
        same_day_slots = [
            slot for slot in available_slots
            if slot.startswith(date_str.split('/')[0])
        ]

        # Se temos slots no mesmo dia, priorizar período semelhante (manhã/tarde)
        if same_day_slots:
            # Separar por período
            morning_slots = [slot for slot in same_day_slots if int(slot.split()[1].split(':')[0]) < 12]
            afternoon_slots = [slot for slot in same_day_slots if int(slot.split()[1].split(':')[0]) >= 12]

            # Escolher com base no período solicitado
            if is_morning and morning_slots:
                return morning_slots[:max_suggestions]
            elif not is_morning and afternoon_slots:
                return afternoon_slots[:max_suggestions]
            else:
                # Se não há slots no período desejado, usar o que estiver disponível
                return same_day_slots[:max_suggestions]

        # Se não temos slots no mesmo dia, sugerir os primeiros disponíveis
        return available_slots[:max_suggestions]

    except Exception as e:
        logger.error(f"[SlotVerification] Erro ao sugerir alternativas: {e}")
        return []

def check_time_in_available_slots(time_str: str, date_str: str, available_slots: list) -> bool:
    """
    Verifica se um horário específico está disponível para uma data.
    Faz verificação flexível considerando variações de formato.

    Args:
        time_str: Horário a verificar (ex: "17:00", "17h")
        date_str: Data a verificar (ex: "10/03/2025")
        available_slots: Lista de slots disponíveis

    Returns:
        Boolean indicando se o horário está disponível
    """
    # Normalizar o horário
    hour = None

    # Extrair a hora localmente; não é necessário consumir IA para um formato
    # determinístico como "17:00", "17h" ou simplesmente "17".
    match = re.search(r"(?<!\d)([01]?\d|2[0-3])(?=\s*(?::|h|$))", time_str.strip().lower())
    if match:
        hour = int(match.group(1))

    if hour is None:
        return False

    # Verificar se existe algum slot disponível com a mesma data e hora
    for slot in available_slots:
        slot_date, slot_time = slot.split()
        slot_hour = int(slot_time.split(':')[0])

        if slot_date == date_str and slot_hour == hour:
            return True

    return False
