"""
Temporal Context Utilities for LLM-friendly slot metadata
"""

from datetime import date, datetime, time
from typing import Dict, Any


def calculate_temporal_context(slot_date: date, slot_time: time, reference_datetime: datetime = None) -> Dict[str, Any]:
    """
    Calculate temporal context fields for a slot to help LLM understanding

    Args:
        slot_date: Date of the appointment slot
        slot_time: Time of the appointment slot
        reference_datetime: Reference time (default: now)

    Returns:
        Dict with temporal context fields for JSON metadata
    """
    if reference_datetime is None:
        reference_datetime = datetime.now()

    reference_date = reference_datetime.date()

    # Calculate relative days
    days_diff = (slot_date - reference_date).days

    # Weekday name in Portuguese
    weekday_names = {
        0: "Segunda-feira",
        1: "Terça-feira",
        2: "Quarta-feira",
        3: "Quinta-feira",
        4: "Sexta-feira",
        5: "Sábado",
        6: "Domingo"
    }
    weekday_name = weekday_names.get(slot_date.weekday(), "Desconhecido")

    # Time period classification
    hour = slot_time.hour
    if hour < 12:
        time_period = "manha"
    elif hour < 18:
        time_period = "tarde"
    else:
        time_period = "noite"

    # Day type classification
    day_type = _calculate_day_type(days_diff, slot_date, slot_time, reference_datetime)

    return {
        "weekday_name": weekday_name,
        "day_type": day_type,
        "time_period": time_period,
        "relative_days": days_diff,
        "is_weekend": slot_date.weekday() >= 5,  # Saturday or Sunday
        "is_today": days_diff == 0,
        "is_this_week": 0 <= days_diff <= 6,
        "is_next_week": 7 <= days_diff <= 13,
        "is_this_month": slot_date.month == reference_date.month and slot_date.year == reference_date.year,
        "is_next_month": _is_next_month(slot_date, reference_date)
    }


def _calculate_day_type(days_diff: int, slot_date: date, slot_time: time, reference_datetime: datetime) -> str:
    """Calculate human-friendly day type"""

    # Same day - check if it's soon
    if days_diff == 0:
        current_time = reference_datetime.time()
        slot_datetime = datetime.combine(slot_date, slot_time)
        ref_datetime = reference_datetime

        time_diff = (slot_datetime - ref_datetime).total_seconds() / 3600  # hours

        if time_diff <= 1:
            return "daqui_1_hora"
        elif time_diff <= 3:
            return "daqui_poucas_horas"
        else:
            return "hoje"

    # Next few days
    elif days_diff == 1:
        return "amanha"
    elif days_diff == 2:
        return "depois_amanha"
    elif 3 <= days_diff <= 6:
        return "essa_semana"
    elif 7 <= days_diff <= 13:
        return "semana_que_vem"
    elif 14 <= days_diff <= 20:
        return "outra_semana"
    elif 21 <= days_diff <= 31:
        if _is_next_month(slot_date, reference_datetime.date()):
            return "mes_que_vem"
        else:
            return "fim_do_mes"
    else:
        return "futuro_distante"


def _is_next_month(slot_date: date, reference_date: date) -> bool:
    """Check if slot_date is in the next month relative to reference_date"""

    if slot_date.year > reference_date.year:
        return slot_date.month == 1 and reference_date.month == 12
    elif slot_date.year == reference_date.year:
        return slot_date.month == reference_date.month + 1
    else:
        return False


def format_slot_for_llm(
    company_id: int,
    slot_date: date,
    slot_time: time,
    is_available: bool,
    metadata: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Format complete slot information for LLM consumption

    Returns:
        Dictionary with all slot information in LLM-friendly format
    """

    # Basic slot info
    date_str = slot_date.strftime("%d/%m/%Y")
    time_str = slot_time.strftime("%H:%M")
    slot_string = f"{date_str} {time_str}"

    # Get temporal context from metadata
    if metadata and isinstance(metadata, dict):
        temporal = {
            "weekday_name": metadata.get("weekday_name", ""),
            "day_type": metadata.get("day_type", ""),
            "time_period": metadata.get("time_period", ""),
            "relative_days": metadata.get("relative_days", 0)
        }
    else:
        # Calculate if not in metadata
        temporal = calculate_temporal_context(slot_date, slot_time)

    return {
        "company_id": company_id,
        "slot_string": slot_string,
        "date": date_str,
        "time": time_str,
        "is_available": is_available,
        "weekday": temporal["weekday_name"],
        "when": temporal["day_type"],
        "period": temporal["time_period"],
        "days_from_now": temporal["relative_days"],
        "human_context": _generate_human_context(temporal)
    }


def _generate_human_context(temporal: Dict[str, Any]) -> str:
    """Generate human-readable context for LLM"""

    weekday = temporal.get("weekday_name", "")
    day_type = temporal.get("day_type", "")
    time_period = temporal.get("time_period", "")

    # Create natural language description
    context_parts = []

    if weekday:
        context_parts.append(weekday)

    if day_type == "hoje":
        context_parts.append("hoje")
    elif day_type == "amanha":
        context_parts.append("amanhã")
    elif day_type == "depois_amanha":
        context_parts.append("depois de amanhã")
    elif day_type == "essa_semana":
        context_parts.append("ainda esta semana")
    elif day_type == "semana_que_vem":
        context_parts.append("semana que vem")
    elif day_type == "mes_que_vem":
        context_parts.append("mês que vem")

    if time_period == "manha":
        context_parts.append("de manhã")
    elif time_period == "tarde":
        context_parts.append("à tarde")
    elif time_period == "noite":
        context_parts.append("à noite")

    return " ".join(context_parts) if context_parts else "horário disponível"


# Example of temporal context categories
DAY_TYPE_CATEGORIES = {
    "daqui_1_hora": "Muito próximo (< 1 hora)",
    "daqui_poucas_horas": "Próximo (1-3 horas)",
    "hoje": "Hoje",
    "amanha": "Amanhã",
    "depois_amanha": "Depois de amanhã",
    "essa_semana": "Esta semana (3-6 dias)",
    "semana_que_vem": "Semana que vem (7-13 dias)",
    "outra_semana": "Outra semana (14-20 dias)",
    "fim_do_mes": "Fim do mês (21-31 dias)",
    "mes_que_vem": "Mês que vem",
    "futuro_distante": "Futuro distante (> 31 dias)"
}

TIME_PERIOD_CATEGORIES = {
    "manha": "Manhã (até 12h)",
    "tarde": "Tarde (12h-18h)",
    "noite": "Noite (após 18h)"
}