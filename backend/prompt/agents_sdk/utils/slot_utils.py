# Slot Utilities for Agents SDK
import logging
from typing import Dict, Any, List
from datetime import datetime, timedelta
import random
import pytz

logger = logging.getLogger(__name__)
SP_TZ = pytz.timezone('America/Sao_Paulo')


def analyze_slot_request_with_llm(user_input: str) -> Dict[str, Any]:
    """
    Versão legacy mantida para compatibilidade.
    Usar analyze_scheduling_intent (tool) para análise completa.
    """
    # Análise básica para compatibilidade
    result = {
        "has_request": False,
        "period": None,
        "weekday": None,
        "date": None
    }

    user_lower = user_input.lower()

    # Período
    if "manhã" in user_lower:
        result["period"] = "manhã"
        result["has_request"] = True
    elif "tarde" in user_lower:
        result["period"] = "tarde"
        result["has_request"] = True
    elif "noite" in user_lower:
        result["period"] = "noite"
        result["has_request"] = True

    # Dia
    days = ["hoje", "amanhã", "segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    for day in days:
        if day in user_lower:
            result["weekday"] = day
            result["has_request"] = True
            break

    # Solicitação genérica
    keywords = ["horário", "agendar", "marcar", "consulta"]
    if any(kw in user_lower for kw in keywords):
        result["has_request"] = True

    return result


def filter_slots_by_request(
    all_slots: List[str],
    slot_request: Dict[str, Any]
) -> List[str]:
    """
    Filtra slots baseado na solicitação do usuário.
    Versão simplificada para Agents SDK.
    """
    if not slot_request.get("has_request"):
        return all_slots

    filtered = []

    for slot in all_slots:
        try:
            dt = datetime.strptime(slot, "%d/%m/%Y %H:%M")

            # Filtra por período
            if slot_request.get("period"):
                period = slot_request["period"]
                hour = dt.hour

                if period == "manhã" and not (6 <= hour < 12):
                    continue
                elif period == "tarde" and not (12 <= hour < 18):
                    continue
                elif period == "noite" and not (18 <= hour < 22):
                    continue

            # Filtra por dia da semana
            if slot_request.get("weekday"):
                weekday_map = {
                    "segunda": 0, "terça": 1, "quarta": 2,
                    "quinta": 3, "sexta": 4, "sábado": 5, "domingo": 6
                }
                target_weekday = weekday_map.get(slot_request["weekday"])
                if target_weekday is not None and dt.weekday() != target_weekday:
                    continue

            filtered.append(slot)

        except ValueError:
            continue

    return filtered


def diversify_slot_selection(slots: List[str], limit: int = 10, timezone=None) -> List[str]:
    """
    [DEPRECATED] Use smart_slot_selection para seleção inteligente.

    Mantida apenas para compatibilidade.
    Seleciona slots APENAS DE AMANHÃ de forma aleatória.

    Args:
        slots: Lista de slots disponíveis
        limit: Número máximo de slots a retornar
        timezone: Timezone da empresa (opcional, usa SP_TZ se não fornecido)
    """
    if not slots:
        return []

    logger.info(f"[Slots] diversify_slot_selection recebeu {len(slots)} slots")
    if slots and len(slots) > 0:
        logger.info(f"[Slots] Primeiros 5 slots recebidos: {slots[:5]}")

    # Usa o timezone fornecido ou o padrão
    tz = timezone if timezone else SP_TZ

    # Obtém a data de amanhã no timezone correto
    now = datetime.now(tz)
    tomorrow = (now + timedelta(days=1)).date()

    # Filtra apenas slots de amanhã
    tomorrow_slots = []
    for slot in slots:
        try:
            dt = datetime.strptime(slot, "%d/%m/%Y %H:%M")
            if dt.date() == tomorrow:
                tomorrow_slots.append((dt, slot))
        except:
            continue

    if not tomorrow_slots:
        logger.warning(f"Nenhum slot encontrado para amanhã ({tomorrow})")
        logger.warning(f"[DEBUG] Primeiros 10 slots disponíveis eram: {slots[:10]}")
        return []

    # Separa manhã e tarde
    morning = [(dt, s) for dt, s in tomorrow_slots if dt.hour < 12]
    afternoon = [(dt, s) for dt, s in tomorrow_slots if dt.hour >= 12]

    selected_slots = []

    # Se tem manhã e tarde, pega metade de cada
    if morning and afternoon:
        morning_count = limit // 2
        afternoon_count = limit - morning_count

        # Seleciona aleatoriamente da manhã
        if len(morning) <= morning_count:
            selected_slots.extend([s for _, s in morning])
        else:
            morning_sample = random.sample(morning, morning_count)
            selected_slots.extend([s for _, s in morning_sample])

        # Seleciona aleatoriamente da tarde
        if len(afternoon) <= afternoon_count:
            selected_slots.extend([s for _, s in afternoon])
        else:
            afternoon_sample = random.sample(afternoon, afternoon_count)
            selected_slots.extend([s for _, s in afternoon_sample])

    # Se só tem um período, pega aleatoriamente dele
    else:
        available = morning if morning else afternoon
        if len(available) <= limit:
            selected_slots = [s for _, s in available]
        else:
            sample = random.sample(available, limit)
            selected_slots = [s for _, s in sample]

    # Ordena cronologicamente os slots selecionados
    selected_slots.sort(key=lambda x: datetime.strptime(x, "%d/%m/%Y %H:%M"))

    logger.info(f"[Slots] Selecionados {len(selected_slots)} slots aleatórios de amanhã")

    return selected_slots[:limit]


def smart_slot_selection(slots: List[str], limit: int = 10, timezone=None) -> List[str]:
    """
    Seleção inteligente de slots com diversificação temporal.

    Estratégia:
    1. Distribui slots entre diferentes dias (não apenas amanhã)
    2. Garante diversidade de horários (manhã/tarde)
    3. Prioriza próximos 7 dias mas inclui opções posteriores

    Args:
        slots: Lista de slots disponíveis
        limit: Número máximo de slots a retornar
        timezone: Timezone da empresa (opcional, usa SP_TZ se não fornecido)
    """
    if not slots:
        return []

    logger.info(f"[SmartSlots] Processando {len(slots)} slots para seleção inteligente")

    # Usa o timezone fornecido ou o padrão
    tz = timezone if timezone else SP_TZ
    now = datetime.now(tz)
    today = now.date()

    # Organiza slots por dia
    slots_by_day = {}
    for slot in slots:
        try:
            dt = datetime.strptime(slot, "%d/%m/%Y %H:%M")
            day = dt.date()

            # Ignora slots de hoje (muito em cima da hora)
            if day <= today:
                continue

            if day not in slots_by_day:
                slots_by_day[day] = []
            slots_by_day[day].append((dt, slot))
        except:
            continue

    if not slots_by_day:
        logger.warning("[SmartSlots] Nenhum slot futuro encontrado")
        return []

    selected_slots = []

    # Ordena dias por proximidade
    sorted_days = sorted(slots_by_day.keys())

    # Estratégia: distribui slots entre os dias
    # Prioriza próximos 7 dias
    week_ahead = today + timedelta(days=7)
    near_days = [d for d in sorted_days if d <= week_ahead]
    far_days = [d for d in sorted_days if d > week_ahead]

    # Se tem dias próximos, usa 80% do limite para eles
    if near_days:
        near_limit = int(limit * 0.8) if far_days else limit
        slots_per_day = max(2, near_limit // len(near_days))

        for day in near_days:
            day_slots = slots_by_day[day]
            # Ordena por hora
            day_slots.sort(key=lambda x: x[0])

            # Separa manhã e tarde
            morning = [s for s in day_slots if s[0].hour < 12]
            afternoon = [s for s in day_slots if s[0].hour >= 12]

            # Pega alguns de cada período
            if morning and afternoon:
                # Metade de cada
                selected_slots.extend([s[1] for s in morning[:slots_per_day//2]])
                selected_slots.extend([s[1] for s in afternoon[:slots_per_day//2]])
            elif morning:
                selected_slots.extend([s[1] for s in morning[:slots_per_day]])
            elif afternoon:
                selected_slots.extend([s[1] for s in afternoon[:slots_per_day]])

            if len(selected_slots) >= near_limit:
                break

    # Completa com dias mais distantes se necessário
    if len(selected_slots) < limit and far_days:
        remaining = limit - len(selected_slots)
        for day in far_days[:3]:  # Máximo 3 dias distantes
            day_slots = slots_by_day[day]
            day_slots.sort(key=lambda x: x[0])
            selected_slots.extend([s[1] for s in day_slots[:remaining//2]])
            if len(selected_slots) >= limit:
                break

    # Ordena resultado final cronologicamente
    selected_slots = selected_slots[:limit]
    selected_slots.sort(key=lambda x: datetime.strptime(x, "%d/%m/%Y %H:%M"))

    logger.info(f"[SmartSlots] Selecionados {len(selected_slots)} slots distribuídos em {len(set(datetime.strptime(s, '%d/%m/%Y %H:%M').date() for s in selected_slots))} dias")

    return selected_slots