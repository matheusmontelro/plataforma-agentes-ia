import logging
from google.oauth2.service_account import Credentials
from typing import Any
from googleapiclient.discovery import build
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.models import CalendarIntegration
from backend.routes.integrations.google_calendar_service import build_google_oauth_service
from datetime import datetime, timedelta
from typing import List, Dict
from zoneinfo import ZoneInfo

from backend.runtime_settings import GOOGLE_CALENDAR_CREDENTIALS

logger = logging.getLogger(__name__)

CREDENTIALS_PATH = str(GOOGLE_CALENDAR_CREDENTIALS)
SP_TZ = ZoneInfo("America/Sao_Paulo")

def get_google_calendar_service():
    """
    Autentica e retorna o serviço do Google Calendar.
    As credenciais devem estar definidas em um arquivo JSON,
    cujo caminho está fixo ou definido em outro lugar.
    """
    logger.info("Autenticando com o Google Calendar...")
    try:
        scopes = [
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]

        # Caminho local do arquivo com credenciais da service account
        credentials_path = CREDENTIALS_PATH

        credentials = Credentials.from_service_account_file(credentials_path, scopes=scopes)
        service = build("calendar", "v3", credentials=credentials)
        return service

    except Exception as e:
        logger.error(f"Erro ao autenticar com o Google Calendar: {e}")
        return None

def get_company_google_calendar_id(db: Session, company_id: int) -> str:
    """
    Retorna o 'google_calendar_id' da tabela 'calendar_integrations'
    se a 'provider' for 'google', caso contrário retorna None.
    """
    logger.info(f"Buscando google_calendar_id para company_id={company_id}...")
    row = db.execute(
        text("""
            SELECT google_calendar_id
              FROM calendar_integrations
             WHERE company_id = :cid
               AND provider = 'google'
             LIMIT 1
        """),
        {"cid": company_id}
    ).fetchone()

    if row and row.google_calendar_id:
        logger.info(f"Encontrado google_calendar_id='{row.google_calendar_id}' para company_id={company_id}.")
        return row.google_calendar_id

    linked_agenda = db.execute(
        text("""
            SELECT google_calendar_id
              FROM agendas
             WHERE company_id = :cid
               AND google_calendar_id IS NOT NULL
             ORDER BY id ASC
             LIMIT 1
        """),
        {"cid": company_id}
    ).fetchone()

    if linked_agenda and linked_agenda.google_calendar_id:
        logger.info(f"Encontrado google_calendar_id em agenda local para company_id={company_id}.")
        return linked_agenda.google_calendar_id

    logger.warning(f"Não foi encontrada integração Google para company_id={company_id}.")
    return None

def obter_eventos_calendario(service, calendar_id: str, start_dt, end_dt):
    """
    start_dt e end_dt podem ser 'datetime' ou 'str' no formato RFC3339.
    """
    logger.info(f"Obtendo eventos do calendário {calendar_id} entre {start_dt} e {end_dt}")

    try:
        # Se for datetime, converte. Se for string, assume que já é RFC3339.
        if isinstance(start_dt, datetime):
            time_min = start_dt.isoformat()
        else:
            time_min = start_dt

        if isinstance(end_dt, datetime):
            time_max = end_dt.isoformat()
        else:
            time_max = end_dt

        eventos_result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        eventos = eventos_result.get("items", [])
        logger.info(f"Encontrados {len(eventos)} eventos no período.")
        return eventos

    except Exception as e:
        logger.error(f"Erro ao obter eventos do Google Calendar: {e}")
        raise

def get_unavailable_periods_from_google_calendar(
    db: Session,
    company_id: int,
    start_date: datetime,
    end_date: datetime
) -> List[Dict[str, str]]:
    """
    Retorna a lista de períodos indisponíveis (eventos) do Google Calendar,
    mesclando eventos consecutivos do mesmo dia.
    Usa o timezone específico da empresa configurado na tabela ai_response_windows.
    """
    # 0. Obter o timezone da empresa
    company_timezone_row = db.execute(
        text("""
            SELECT timezone
            FROM ai_response_windows
            WHERE company_id = :cid
            LIMIT 1
        """),
        {"cid": company_id}
    ).fetchone()

    # Use o timezone da empresa ou caia no padrão se não encontrar
    if company_timezone_row and company_timezone_row.timezone:
        company_tz = ZoneInfo(company_timezone_row.timezone)
        logger.info(f"Usando timezone personalizado para company_id={company_id}: {company_timezone_row.timezone}")
    else:
        company_tz = SP_TZ
        logger.info(f"Timezone não encontrado para company_id={company_id}, usando padrão: America/Sao_Paulo")

    # 1. Obter o calendar_id
    gcal_id = get_company_google_calendar_id(db, company_id)
    if not gcal_id:
        logger.warning("Nenhum google_calendar_id. Retornando lista vazia.")
        return []

    # 2. Obter serviço do Google Calendar com OAuth da empresa
    integration = db.query(CalendarIntegration).filter(
        CalendarIntegration.company_id == company_id,
        CalendarIntegration.provider == "google",
    ).first()
    if not integration or not integration.google_oauth_token:
        logger.warning("Integração Google sem OAuth conectado. Retornando lista vazia.")
        return []

    service = build_google_oauth_service(integration, db)
    if not service:
        logger.error("Falha ao criar service do Google Calendar.")
        return []

    # 3. Obter eventos
    try:
        events = obter_eventos_calendario(service, gcal_id, start_date, end_date)
        if not events:
            logger.info("Nenhum evento encontrado no período.")
            return []
    except Exception as e:
        logger.error(f"Erro ao obter eventos: {e}")
        return []

    # 4. Converter todos os eventos para datetime
    raw_periods = []
    for evt in events:
        try:
            start_info = evt.get("start", {})
            end_info = evt.get("end", {})

            start_str = start_info.get("dateTime") or start_info.get("date")
            end_str = end_info.get("dateTime") or end_info.get("date")

            if not start_str or not end_str:
                continue

            if "T" not in start_str:  # Evento de dia inteiro
                dt_start = datetime.fromisoformat(f"{start_str}T00:00:00")
                dt_end = datetime.fromisoformat(f"{end_str}T23:59:59")
            else:
                dt_start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                dt_end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))

            # Garantir timezone usando o timezone específico da empresa
            if dt_start.tzinfo is None:
                dt_start = dt_start.replace(tzinfo=company_tz)
            else:
                dt_start = dt_start.astimezone(company_tz)

            if dt_end.tzinfo is None:
                dt_end = dt_end.replace(tzinfo=company_tz)
            else:
                dt_end = dt_end.astimezone(company_tz)

            raw_periods.append({
                "start": dt_start,
                "end": dt_end
            })

            logger.debug(f"Evento processado: {dt_start} até {dt_end}")

        except Exception as e:
            logger.error(f"Erro ao processar evento: {e}")
            continue

    # 5. Agrupar eventos por data
    events_by_date = {}
    for period in raw_periods:
        date_key = period["start"].date()
        if date_key not in events_by_date:
            events_by_date[date_key] = []
        events_by_date[date_key].append(period)

    # 6. Para cada dia, ordenar e mesclar eventos consecutivos
    final_periods = []
    for date_key, daily_events in events_by_date.items():
        # Ordenar eventos do dia por horário de início
        daily_events.sort(key=lambda x: x["start"])

        merged = []
        current = None

        for event in daily_events:
            if current is None:
                current = event.copy()
            else:
                # Se o evento atual começa quando (ou antes) o anterior termina
                if event["start"] <= current["end"]:
                    # Estender o período até o final do evento atual, se necessário
                    if event["end"] > current["end"]:
                        current["end"] = event["end"]
                else:
                    # Eventos não são consecutivos, adicionar o atual e começar novo
                    merged.append(current)
                    current = event.copy()

        if current:
            merged.append(current)

        final_periods.extend(merged)

        logger.debug(f"Períodos mesclados para {date_key}: {merged}")

    # 7. Converter para o formato final (string)
    result = [{
        "start": period["start"].strftime("%d/%m/%Y %H:%M"),
        "end": period["end"].strftime("%d/%m/%Y %H:%M")
    } for period in final_periods]

    logger.info(f"Total de períodos indisponíveis após mesclagem: {len(result)}")
    return result
