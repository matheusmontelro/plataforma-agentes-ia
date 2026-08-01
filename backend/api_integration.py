#api_integration.py
import os
from datetime import datetime, timedelta
import requests
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from backend.clients_manager import get_zapi_data_for_client  # Ajustado
from threading import Lock
from sqlalchemy.orm import Session
from backend.models import Lead
from typing import Optional
from dotenv import load_dotenv
import os

load_dotenv()

GOOGLE_CALENDAR_CREDENTIALS_PATH = os.getenv("GOOGLE_CALENDAR_CREDENTIALS_PATH")
calendar_scopes = ["https://www.googleapis.com/auth/calendar"]
calendar_creds = Credentials.from_service_account_file(
    GOOGLE_CALENDAR_CREDENTIALS_PATH,
    scopes=calendar_scopes
)
calendar_service = build('calendar', 'v3', credentials=calendar_creds)

GOOGLE_SHEETS_CREDENTIALS_PATH = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH")
sheets_scopes = ["https://www.googleapis.com/auth/spreadsheets"]
sheets_creds = Credentials.from_service_account_file(
    GOOGLE_SHEETS_CREDENTIALS_PATH,
    scopes=sheets_scopes
)
sheets_client = gspread.authorize(sheets_creds)

# ========================================
# Cache em memória
# Estrutura:
# {
#   ("list_leads", client_id): {"data": [...], "expires": datetime},
#   ("list_events", client_id): {"data": [...], "expires": datetime}
# }
# ========================================

cache = {}
cache_lock = Lock()
CACHE_TTL_SECONDS = 60  # 1 minuto de cache

def get_from_cache(key):
    with cache_lock:
        entry = cache.get(key)
        if entry and entry["expires"] > datetime.utcnow():
            return entry["data"]
        elif entry:
            # Expirou, remover
            del cache[key]
        return None

def set_in_cache(key, data):
    with cache_lock:
        cache[key] = {
            "data": data,
            "expires": datetime.utcnow() + timedelta(seconds=CACHE_TTL_SECONDS)
        }

def send_whatsapp_message(client_id: str, phone: str, message: str):
    zapi_data = get_zapi_data_for_client(client_id)
    payload = {"phone": phone, "message": message}
    try:
        response = requests.post(f"{zapi_data['zapi_url']}/send-text", json=payload)
        response.raise_for_status()
    except requests.exceptions.RequestException:
        raise ConnectionError("Falha na comunicação com ZAPI")
    return response.json()

def send_appointment_webhook(client_id: str, data: dict):
    zapi_data = get_zapi_data_for_client(client_id)
    webhook_url = zapi_data["webhook_url"]
    try:
        response = requests.post(webhook_url, json=data)
        response.raise_for_status()
    except requests.exceptions.RequestException:
        raise ConnectionError("Falha ao enviar webhook de agendamento")
    return response.status_code

def list_events(client_id: str):
    key = ("list_events", client_id)
    cached = get_from_cache(key)
    if cached is not None:
        return cached

    zapi_data = get_zapi_data_for_client(client_id)
    calendar_id = zapi_data["google_calendar_id"]
    now = datetime.utcnow().isoformat() + 'Z'
    try:
        events_result = calendar_service.events().list(
            calendarId=calendar_id,
            timeMin=now,
            maxResults=10,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
    except Exception:
        raise ConnectionError("Falha ao obter eventos do Google Calendar")

    events = events_result.get('items', [])
    set_in_cache(key, events)
    return events

def create_event(client_id: str, summary: str, start_time, end_time):
    # Ao criar um evento, invalidar o cache de events para garantir dados atualizados
    key = ("list_events", client_id)
    with cache_lock:
        if key in cache:
            del cache[key]

    zapi_data = get_zapi_data_for_client(client_id)
    calendar_id = zapi_data["google_calendar_id"]
    event = {
        'summary': summary,
        'start': {
            'dateTime': start_time.isoformat(),
            'timeZone': 'America/Sao_Paulo'
        },
        'end': {
            'dateTime': end_time.isoformat(),
            'timeZone': 'America/Sao_Paulo'
        }
    }
    try:
        event_result = calendar_service.events().insert(
            calendarId=calendar_id,
            body=event
        ).execute()
    except Exception:
        raise ConnectionError("Falha ao criar evento no Google Calendar")
    return event_result

def add_lead(client_id: str, name: str, phone: str):
    # Ao adicionar lead, invalidar o cache de leads
    key = ("list_leads", client_id)
    with cache_lock:
        if key in cache:
            del cache[key]

    zapi_data = get_zapi_data_for_client(client_id)
    sheets_url = zapi_data["google_sheets_url"]
    try:
        sheet = sheets_client.open_by_url(sheets_url).worksheet("LEADS")
    except Exception:
        raise ConnectionError("Falha ao acessar a planilha de leads")
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    try:
        sheet.append_row([name, phone, now_str])
    except Exception:
        raise ConnectionError("Falha ao adicionar lead na planilha")
    return True

def list_leads(client_id: str,
               start_date: Optional[str] = None,
               end_date: Optional[str] = None,
               page: int = 1,
               page_size: int = 10,
               db: Session = None):
    # Precisamos ajustar as rotas para passar db: Session via Depends(get_db)

    query = db.query(Lead).filter(Lead.client_id == client_id)

    # Filtro por data
    # Convertendo start_date e end_date para datetime
    if start_date:
        start_dt = datetime.strptime(start_date, "%d/%m/%Y")
        # Considerar o dia inteiro
        query = query.filter(Lead.created_at >= start_dt.strftime("%d/%m/%Y 00:00"))

    if end_date:
        end_dt = datetime.strptime(end_date, "%d/%m/%Y")
        # considerar até o fim do dia
        query = query.filter(Lead.created_at <= end_dt.strftime("%d/%m/%Y 23:59"))

    total = query.count()

    # Paginação
    offset = (page - 1) * page_size
    leads_result = query.offset(offset).limit(page_size).all()

    # Retornar no formato [[name, phone, "DD/MM/YYYY HH:MM"], ...]
    leads_list = [[l.name, l.phone, l.created_at] for l in leads_result]
    return leads_list, total
