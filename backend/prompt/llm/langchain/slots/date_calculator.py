"""
Calculadora de Datas Dinâmica para Prompts
==========================================

Calcula todas as datas de referência de forma precisa e consistente.
"""

from datetime import datetime, timedelta
from typing import Dict, Any


def calculate_reference_dates(current_date: datetime = None) -> Dict[str, Any]:
    """
    Calcula todas as datas de referência para o prompt.
    Retorna datas formatadas e estruturadas para o LLM usar diretamente.

    Args:
        current_date: Data atual (default: datetime.now())

    Returns:
        Dict com todas as datas calculadas
    """
    if current_date is None:
        current_date = datetime.now()

    dates = {}

    # Data atual formatada
    dates['current_datetime'] = current_date.strftime('%d/%m/%Y %H:%M')
    dates['current_weekday'] = get_weekday_name_pt(current_date.weekday())

    # Próximos dias básicos
    tomorrow = current_date + timedelta(days=1)
    day_after_tomorrow = current_date + timedelta(days=2)

    dates['tomorrow_date'] = tomorrow.strftime('%d/%m/%Y')
    dates['day_after_tomorrow'] = day_after_tomorrow.strftime('%d/%m/%Y')

    # Próximos dias da semana (sempre futuro)
    weekday_names = ['segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'domingo']
    for i, day_name in enumerate(weekday_names):
        next_date = get_next_weekday(current_date, i)
        dates[f'proxima_{day_name}'] = next_date.strftime('%d/%m/%Y')
        dates[f'proxima_{day_name}_full'] = f"{get_weekday_name_pt(i)}, {next_date.strftime('%d/%m/%Y')}"

    # Semanas
    next_monday = get_next_weekday(current_date, 0)  # 0 = segunda
    dates['next_week_start'] = next_monday.strftime('%d/%m/%Y')
    dates['next_week_end'] = (next_monday + timedelta(days=6)).strftime('%d/%m/%Y')

    # Meses
    end_of_month = get_end_of_month(current_date)
    next_month_start, next_month_end = get_next_month_range(current_date)

    dates['end_of_month'] = end_of_month.strftime('%d/%m/%Y')
    dates['next_month_start'] = next_month_start.strftime('%d/%m/%Y')
    dates['next_month_end'] = next_month_end.strftime('%d/%m/%Y')

    return dates


def get_next_weekday(current_date: datetime, target_weekday: int) -> datetime:
    """
    Calcula a próxima ocorrência de um dia da semana.

    Args:
        current_date: Data atual
        target_weekday: Dia da semana (0=segunda, 6=domingo)

    Returns:
        Data da próxima ocorrência
    """
    days_ahead = target_weekday - current_date.weekday()
    if days_ahead <= 0:  # Se é hoje ou já passou
        days_ahead += 7  # Próxima semana
    return current_date + timedelta(days=days_ahead)


def get_weekday_name_pt(weekday: int) -> str:
    """Retorna nome do dia da semana em português"""
    names = ['Segunda-feira', 'Terça-feira', 'Quarta-feira',
             'Quinta-feira', 'Sexta-feira', 'Sábado', 'Domingo']
    return names[weekday]


def get_end_of_month(current_date: datetime) -> datetime:
    """Calcula o último dia do mês atual"""
    if current_date.month == 12:
        return datetime(current_date.year + 1, 1, 1) - timedelta(days=1)
    else:
        return datetime(current_date.year, current_date.month + 1, 1) - timedelta(days=1)


def get_next_month_range(current_date: datetime) -> tuple:
    """Retorna primeiro e último dia do próximo mês"""
    if current_date.month == 12:
        next_month_start = datetime(current_date.year + 1, 1, 1)
        next_month_end = datetime(current_date.year + 1, 2, 1) - timedelta(days=1)
    else:
        next_month_start = datetime(current_date.year, current_date.month + 1, 1)
        if current_date.month + 1 == 12:
            next_month_end = datetime(current_date.year + 1, 1, 1) - timedelta(days=1)
        else:
            next_month_end = datetime(current_date.year, current_date.month + 2, 1) - timedelta(days=1)

    return next_month_start, next_month_end


def create_temporal_reference_prompt(current_date: datetime = None) -> str:
    """
    Cria uma seção do prompt com todas as referências temporais calculadas.

    Returns:
        String formatada para inserir no prompt
    """
    dates = calculate_reference_dates(current_date)

    prompt_section = f"""
REFERÊNCIAS TEMPORAIS CALCULADAS:
Data/Hora atual: {dates['current_datetime']}
Dia da semana atual: {dates['current_weekday']}

PRÓXIMOS DIAS:
- "amanhã" = {dates['tomorrow_date']}
- "depois de amanhã" = {dates['day_after_tomorrow']}

PRÓXIMOS DIAS DA SEMANA:
- "segunda" ou "próxima segunda" = {dates['proxima_segunda_full']}
- "terça" ou "próxima terça" = {dates['proxima_terca_full']}
- "quarta" ou "próxima quarta" = {dates['proxima_quarta_full']}
- "quinta" ou "próxima quinta" = {dates['proxima_quinta_full']}
- "sexta" ou "próxima sexta" = {dates['proxima_sexta_full']}
- "sábado" ou "próximo sábado" = {dates['proxima_sabado_full']}
- "domingo" ou "próximo domingo" = {dates['proxima_domingo_full']}

PERÍODOS MAIORES:
- "semana que vem" = {dates['next_week_start']} a {dates['next_week_end']}
- "fim do mês" = {dates['end_of_month']}
- "mês que vem" = {dates['next_month_start']} a {dates['next_month_end']}

IMPORTANTE: Use EXATAMENTE essas datas calculadas. NÃO faça seus próprios cálculos.
"""

    return prompt_section