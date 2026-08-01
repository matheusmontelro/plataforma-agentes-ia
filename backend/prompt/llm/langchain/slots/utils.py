"""
Funções Utilitárias para o Sistema de Slots
===========================================

Funções auxiliares para parsing, formatação e validação.
"""

from typing import Optional, List, Dict, Any, Literal
from datetime import datetime, time, timedelta
import pytz
import re
import logging

logger = logging.getLogger(__name__)

SP_TZ = pytz.timezone('America/Sao_Paulo')


def parse_slot_datetime(slot_str: str) -> Optional[datetime]:
    """
    Converte string de slot para objeto datetime.

    Args:
        slot_str: String no formato "DD/MM/YYYY HH:MM"

    Returns:
        datetime com timezone SP ou None se inválido
    """
    try:
        # Tenta formato padrão
        dt = datetime.strptime(slot_str.strip(), "%d/%m/%Y %H:%M")
        return dt.replace(tzinfo=SP_TZ)
    except ValueError:
        # Tenta outros formatos comuns
        formats = [
            "%d/%m/%Y %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%d-%m-%Y %H:%M"
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(slot_str.strip(), fmt)
                return dt.replace(tzinfo=SP_TZ)
            except ValueError:
                continue

        logger.warning(f"Formato de slot inválido: {slot_str}")
        return None


def format_slot_datetime(dt: datetime, include_weekday: bool = True) -> str:
    """
    Formata datetime para exibição amigável.

    Args:
        dt: Objeto datetime
        include_weekday: Se deve incluir dia da semana

    Returns:
        String formatada
    """
    if include_weekday:
        weekday = get_weekday_name_pt(dt.weekday())
        return f"{weekday}, {dt.strftime('%d/%m/%Y às %H:%M')}"
    else:
        return dt.strftime("%d/%m/%Y %H:%M")


def get_period_from_hour(hour: int) -> Literal["morning", "afternoon", "evening", "night"]:
    """
    Determina período do dia baseado na hora.

    Args:
        hour: Hora (0-23)

    Returns:
        Período do dia
    """
    if 6 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 20:
        return "evening"
    else:
        return "night"


def get_weekday_name_pt(weekday: int, abbreviated: bool = False) -> str:
    """
    Retorna nome do dia da semana em português.

    Args:
        weekday: Índice do dia (0=Segunda, 6=Domingo)
        abbreviated: Se deve abreviar

    Returns:
        Nome do dia da semana
    """
    weekdays_full = [
        "Segunda-feira", "Terça-feira", "Quarta-feira",
        "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"
    ]

    weekdays_abbr = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

    return weekdays_abbr[weekday] if abbreviated else weekdays_full[weekday]


def parse_time_expression(expression: str, reference_date: datetime = None) -> Optional[datetime]:
    """
    Interpreta expressões temporais em linguagem natural.

    Args:
        expression: Expressão como "próxima sexta", "amanhã de manhã"
        reference_date: Data de referência (default: agora)

    Returns:
        datetime interpretado ou None
    """
    if not reference_date:
        reference_date = datetime.now(SP_TZ)

    expression_lower = expression.lower().strip()

    # Expressões de dias relativos
    if "hoje" in expression_lower:
        target_date = reference_date.date()
    elif "amanhã" in expression_lower:
        target_date = (reference_date + timedelta(days=1)).date()
    elif "depois de amanhã" in expression_lower:
        target_date = (reference_date + timedelta(days=2)).date()
    else:
        # Tenta identificar dia da semana
        weekday_map = {
            "segunda": 0, "terça": 1, "quarta": 2,
            "quinta": 3, "sexta": 4, "sábado": 5, "domingo": 6
        }

        target_date = None
        for day_name, day_idx in weekday_map.items():
            if day_name in expression_lower:
                # Calcula próxima ocorrência deste dia
                days_ahead = (day_idx - reference_date.weekday()) % 7
                if days_ahead == 0 and "próxim" in expression_lower:
                    days_ahead = 7
                target_date = (reference_date + timedelta(days=days_ahead)).date()
                break

        if not target_date:
            return None

    # Expressões de horário
    target_time = time(9, 0)  # Default

    if "manhã" in expression_lower or "cedo" in expression_lower:
        target_time = time(9, 0)
    elif "tarde" in expression_lower:
        target_time = time(14, 0)
    elif "noite" in expression_lower:
        target_time = time(18, 0)
    else:
        # Tenta extrair horário específico
        time_match = re.search(r'(\d{1,2})(?::(\d{2}))?(?:\s*h)?', expression_lower)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                target_time = time(hour, minute)

    # Combina data e hora
    return datetime.combine(target_date, target_time).replace(tzinfo=SP_TZ)


def calculate_slot_proximity_score(
    slot_dt: datetime,
    preferred_dt: Optional[datetime] = None,
    preferred_period: Optional[str] = None
) -> float:
    """
    Calcula score de proximidade de um slot em relação às preferências.

    Args:
        slot_dt: DateTime do slot
        preferred_dt: DateTime preferido
        preferred_period: Período preferido

    Returns:
        Score entre 0 e 1
    """
    score = 1.0

    if preferred_dt:
        # Penaliza por diferença de dias
        days_diff = abs((slot_dt.date() - preferred_dt.date()).days)
        score -= min(days_diff * 0.1, 0.5)  # Máximo -0.5

        # Penaliza por diferença de horário
        hours_diff = abs((slot_dt.hour - preferred_dt.hour))
        score -= min(hours_diff * 0.05, 0.3)  # Máximo -0.3

    if preferred_period:
        slot_period = get_period_from_hour(slot_dt.hour)
        if slot_period != preferred_period:
            score -= 0.2

    return max(0.0, score)


def group_slots_by_criteria(
    slots: List[str],
    group_by: Literal["day", "period", "week"] = "day"
) -> Dict[str, List[str]]:
    """
    Agrupa slots por diferentes critérios.

    Args:
        slots: Lista de slots
        group_by: Critério de agrupamento

    Returns:
        Dicionário com grupos
    """
    grouped = {}

    for slot_str in slots:
        dt = parse_slot_datetime(slot_str)
        if not dt:
            continue

        if group_by == "day":
            key = dt.date().isoformat()
        elif group_by == "period":
            key = get_period_from_hour(dt.hour)
        elif group_by == "week":
            # Número da semana no ano
            key = f"Semana {dt.isocalendar()[1]}"
        else:
            key = "outros"

        if key not in grouped:
            grouped[key] = []
        grouped[key].append(slot_str)

    return grouped


def validate_slot_availability(
    slot_dt: datetime,
    business_hours: Dict[int, tuple],
    holidays: List[datetime.date] = None
) -> tuple[bool, Optional[str]]:
    """
    Valida se um slot está dentro do horário comercial.

    Args:
        slot_dt: DateTime do slot
        business_hours: Dict com horários por dia da semana
        holidays: Lista de feriados

    Returns:
        (is_valid, reason)
    """
    # Verifica feriados
    if holidays and slot_dt.date() in holidays:
        return False, "Feriado"

    # Verifica dia da semana
    weekday = slot_dt.weekday()
    if weekday not in business_hours:
        return False, "Dia não disponível"

    hours = business_hours[weekday]
    if hours is None:
        return False, "Empresa fechada neste dia"

    start_hour, end_hour = hours
    if not (start_hour <= slot_dt.hour < end_hour):
        return False, f"Fora do horário ({start_hour}h-{end_hour}h)"

    # Verifica se não é passado
    if slot_dt < datetime.now(SP_TZ):
        return False, "Horário já passou"

    return True, None


def estimate_tokens(text: str, model: str = "gpt-4") -> int:
    """
    Estima número de tokens em um texto.

    Args:
        text: Texto para contar
        model: Modelo para encoding

    Returns:
        Número estimado de tokens
    """
    try:
        import tiktoken
        encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(text))
    except:
        # Fallback simples
        return len(text) // 4