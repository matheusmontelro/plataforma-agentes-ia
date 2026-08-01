from datetime import datetime, timedelta, time
from backend.api_integration import list_events  # Ajustado
from backend.clients_manager import get_zapi_data_for_client
import pytz

def get_available_slots(client_id: str, days=7):
    zapi_data = get_zapi_data_for_client(client_id)

    tz = pytz.timezone(zapi_data["timezone"])

    morning_start_h, morning_start_m = map(int, zapi_data["morning_start"].split(":"))
    morning_end_h, morning_end_m = map(int, zapi_data["morning_end"].split(":"))
    afternoon_start_h, afternoon_start_m = map(int, zapi_data["afternoon_start"].split(":"))
    afternoon_end_h, afternoon_end_m = map(int, zapi_data["afternoon_end"].split(":"))

    morning_start = time(morning_start_h, morning_start_m)
    morning_end = time(morning_end_h, morning_end_m)
    afternoon_start = time(afternoon_start_h, afternoon_start_m)
    afternoon_end = time(afternoon_end_h, afternoon_end_m)

    workdays = zapi_data["workdays"]  # lista de ints (0=segunda, ..., 6=domingo)

    now = datetime.now(tz)
    available_slots = []

    for i in range(days):
        day = now + timedelta(days=i)
        # Verifica se o day.weekday() está na lista de workdays do cliente
        if day.weekday() in workdays:
            # Manhã
            current = day.replace(hour=morning_start.hour, minute=morning_start.minute, second=0, microsecond=0)
            while current.time() < morning_end:
                available_slots.append(current)
                current += timedelta(hours=1)

            # Tarde
            current = day.replace(hour=afternoon_start.hour, minute=afternoon_start.minute, second=0, microsecond=0)
            while current.time() < afternoon_end:
                available_slots.append(current)
                current += timedelta(hours=1)

    # Remover slots ocupados
    events = list_events(client_id)
    occupied = []
    for e in events:
        start = e['start'].get('dateTime')
        if start:
            start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            start_dt = start_dt.astimezone(tz)
            occupied.append(start_dt)

    # Remove slots que conflitam com eventos
    final_slots = [slot for slot in available_slots if not any(abs((slot - occ).total_seconds()) < 1 for occ in occupied)]

    final_slots_str = [slot.strftime("%d/%m/%Y %H:%M") for slot in final_slots]
    return final_slots_str
