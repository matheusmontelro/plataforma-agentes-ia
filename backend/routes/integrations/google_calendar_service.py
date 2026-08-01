
import json
import os
import logging
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any

# --- Bibliotecas Google API Client (Importação Direta) ---
# Garanta que estão instaladas: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2 import service_account
from googleapiclient.discovery import build, Resource # Resource é sempre importado
from googleapiclient.errors import HttpError
# --- Fim Bibliotecas Google ---
# ----------------------------------

logger = logging.getLogger(__name__)

DEFAULT_GOOGLE_CREDENTIALS_PATH = str(
    Path(__file__).resolve().parents[3] / "arquivos" / "google_calendar.json"
)

# --- Configuração (como antes) ---
GOOGLE_CREDENTIALS_PATH = os.getenv(
    "GOOGLE_CALENDAR_CREDENTIALS_PATH",
    os.getenv("GOOGLE_APPLICATION_CREDENTIALS", DEFAULT_GOOGLE_CREDENTIALS_PATH)
)
SCOPES = [
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/calendar.readonly' # <-- ADICIONAR ESTE ESCOPO
]

GOOGLE_OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    "https://www.googleapis.com/auth/calendar.app.created",
    "https://www.googleapis.com/auth/calendar.events.owned",
]


# --- Inicialização do Serviço ---
_calendar_service: Optional[Resource] = None # Agora Pylance entende Resource
_calendar_credentials: Optional[service_account.Credentials] = None


def _format_google_http_error(error: HttpError) -> str:
    """Extrai uma mensagem legível dos erros da API Google."""
    try:
        payload = json.loads(error.content.decode("utf-8"))
        message = payload.get("error", {}).get("message")
        if message:
            return message
    except Exception:
        pass
    return getattr(error, "reason", None) or str(error)


def _get_calendar_credentials() -> Optional[service_account.Credentials]:
    """Carrega as credenciais da service account usada pelo Google Calendar."""
    global _calendar_credentials
    if _calendar_credentials:
        return _calendar_credentials

    if not os.path.exists(GOOGLE_CREDENTIALS_PATH):
        logger.error(f"Arquivo de credenciais Google Calendar não encontrado em: {GOOGLE_CREDENTIALS_PATH}")
        logger.error("Verifique a variável de ambiente GOOGLE_CALENDAR_CREDENTIALS_PATH ou o caminho padrão.")
        return None

    try:
        creds = service_account.Credentials.from_service_account_file(
            GOOGLE_CREDENTIALS_PATH, scopes=SCOPES
        )
        _calendar_credentials = creds
        return _calendar_credentials
    except Exception as e:
        logger.exception(f"Falha ao carregar credenciais Google Calendar usando {GOOGLE_CREDENTIALS_PATH}: {e}")
        return None


def get_google_calendar_service_account_email() -> Optional[str]:
    """Retorna o e-mail da service account, sem expor dados sensíveis do JSON."""
    creds = _get_calendar_credentials()
    if not creds:
        return None
    return getattr(creds, "service_account_email", None)


def _get_calendar_service() -> Optional[Resource]: # Agora Pylance entende Resource
    """Autentica e constrói o objeto da API Calendar."""
    global _calendar_service
    if _calendar_service:
        return _calendar_service

    logger.debug("Inicializando serviço da API Google Calendar...")
    creds = _get_calendar_credentials()
    if not creds:
        return None

    try:
        # Constrói o objeto de serviço da API
        # cache_discovery=False é recomendado para aplicações de longa duração/servidores
        service = build('calendar', 'v3', credentials=creds, cache_discovery=False)

        _calendar_service = service # Armazena em cache
        logger.info("Serviço da API Google Calendar inicializado com sucesso.")
        return _calendar_service
    except Exception as e:
        logger.exception(f"Falha ao inicializar serviço Google Calendar usando {GOOGLE_CREDENTIALS_PATH}: {e}")
        return None

# --- Funções de Interação com API ---

def build_google_oauth_service(integration: Any, db: Any = None) -> Optional[Resource]:
    """Cria um cliente Calendar API usando o OAuth do cliente conectado."""
    token_info = getattr(integration, "google_oauth_token", None)
    if not token_info:
        logger.warning("Integração Google sem token OAuth salvo.")
        return None

    try:
        creds = OAuthCredentials.from_authorized_user_info(token_info, scopes=GOOGLE_OAUTH_SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(GoogleAuthRequest())
            if db is not None:
                integration.google_oauth_token = json.loads(creds.to_json())
                db.add(integration)
                db.commit()
        if not creds.valid:
            logger.warning("Token OAuth Google inválido ou expirado sem refresh token.")
            return None
        return build("calendar", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        logger.exception(f"Falha ao criar serviço OAuth do Google Calendar: {e}")
        return None


def _resolve_calendar_service(service: Optional[Resource] = None) -> Optional[Resource]:
    return service or _get_calendar_service()


def extract_google_meeting_link(event: Optional[Dict[str, Any]]) -> Optional[str]:
    """Extrai o link de vídeo/Google Meet de uma resposta de evento."""
    if not event:
        return None

    hangout_link = event.get("hangoutLink")
    if hangout_link:
        return str(hangout_link)

    conference_data = event.get("conferenceData") or {}
    entry_points = conference_data.get("entryPoints") or []
    for entry_point in entry_points:
        if not isinstance(entry_point, dict):
            continue
        uri = entry_point.get("uri")
        if entry_point.get("entryPointType") == "video" and uri:
            return str(uri)

    for entry_point in entry_points:
        if not isinstance(entry_point, dict):
            continue
        uri = str(entry_point.get("uri") or "")
        if uri.startswith("http"):
            return uri

    return None


def _conference_create_request() -> Dict[str, Any]:
    return {
        "createRequest": {
            "requestId": f"agentive-{uuid.uuid4().hex}",
            "conferenceSolutionKey": {"type": "hangoutsMeet"},
        }
    }


def _hydrate_conference_event(
    service: Resource,
    calendar_id: str,
    event: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not event or extract_google_meeting_link(event):
        return event

    event_id = event.get("id")
    if not event_id:
        return event

    for attempt in range(3):
        if attempt:
            time.sleep(0.5)
        try:
            refreshed = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
        except Exception:
            logger.debug("Não foi possível recarregar evento Google %s para obter Meet.", event_id, exc_info=True)
            return event
        if extract_google_meeting_link(refreshed):
            return refreshed
        status_code = (
            (refreshed.get("conferenceData") or {})
            .get("createRequest", {})
            .get("status", {})
            .get("statusCode")
        )
        if status_code and status_code != "pending":
            return refreshed

    return event


def _event_return_value(event: Dict[str, Any], return_event: bool) -> Any:
    return event if return_event else event.get("id")

def validate_google_calendar_access(calendar_id: str) -> Dict[str, Any]:
    """
    Verifica se o backend consegue acessar o calendário informado com a service account.

    Isso valida as credenciais no servidor, o ID do calendário e a permissão de leitura.
    A permissão de escrita ainda precisa ser concedida no Google Calendar para criar eventos.
    """
    normalized_calendar_id = (calendar_id or "").strip()
    service_account_email = get_google_calendar_service_account_email()

    if not normalized_calendar_id:
        return {
            "ok": False,
            "error": "Informe o ID do calendário Google.",
            "service_account_email": service_account_email,
        }

    service = _get_calendar_service()
    if not service:
        return {
            "ok": False,
            "error": (
                "Credenciais do Google Calendar não encontradas ou inválidas no servidor. "
                f"Configure GOOGLE_CALENDAR_CREDENTIALS_PATH ou envie o JSON para {GOOGLE_CREDENTIALS_PATH}."
            ),
            "service_account_email": service_account_email,
        }

    try:
        calendar_metadata = service.calendars().get(calendarId=normalized_calendar_id).execute()
        service.events().list(
            calendarId=normalized_calendar_id,
            timeMin=datetime.now(timezone.utc).isoformat(),
            maxResults=1,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        return {
            "ok": True,
            "calendar_id": normalized_calendar_id,
            "summary": calendar_metadata.get("summary"),
            "timeZone": calendar_metadata.get("timeZone"),
            "service_account_email": service_account_email,
        }
    except HttpError as error:
        status_code = getattr(getattr(error, "resp", None), "status", None)
        message = _format_google_http_error(error)
        logger.warning(
            "Falha ao validar acesso ao Google Calendar '%s' com service account '%s': %s",
            normalized_calendar_id,
            service_account_email,
            message,
        )
        return {
            "ok": False,
            "calendar_id": normalized_calendar_id,
            "error": message,
            "http_status": status_code,
            "service_account_email": service_account_email,
        }
    except Exception as e:
        logger.exception(f"Erro inesperado ao validar Google Calendar '{normalized_calendar_id}': {e}")
        return {
            "ok": False,
            "calendar_id": normalized_calendar_id,
            "error": "Erro inesperado ao validar acesso ao Google Calendar.",
            "service_account_email": service_account_email,
        }

def create_google_event(
    calendar_id: str,
    summary: str,
    description: str,
    start_naive_iso: str, # Ex: "2025-04-18T16:30:00"
    end_naive_iso: str,   # Ex: "2025-04-18T17:00:00"
    timezone: str,         # Ex: "America/Sao_Paulo"
    service: Optional[Resource] = None,
    create_conference: bool = False,
    return_event: bool = False,
) -> Optional[Any]:
    """Cria um evento no Google Calendar usando datetime naive + timezone ID."""
    service = _resolve_calendar_service(service)
    if not service: return None

    event_body = {
        'summary': summary,
        'description': description,
        'start': {
            'dateTime': start_naive_iso, # Envia string naive
            'timeZone': timezone,       # Envia IANA Timezone ID
        },
        'end': {
            'dateTime': end_naive_iso,   # Envia string naive
            'timeZone': timezone,       # Envia IANA Timezone ID
        },
    }
    if create_conference:
        event_body["conferenceData"] = _conference_create_request()

    try:
        logger.info(f"Criando evento Google (naive) em '{calendar_id}': '{summary}' @ {start_naive_iso} [{timezone}]")
        request_kwargs = {"calendarId": calendar_id, "body": event_body}
        if create_conference:
            request_kwargs["conferenceDataVersion"] = 1
        event = service.events().insert(**request_kwargs).execute()
        if create_conference:
            event = _hydrate_conference_event(service, calendar_id, event) or event
        event_id = event.get('id')
        logger.info(f"Evento Google criado com sucesso. Event ID: {event_id}")
        return _event_return_value(event, return_event)
    except HttpError as error:
        logger.error(f"Erro API Google ao criar evento (naive): {error.status_code} - {error.reason}. Details: {error.content}")
        return None
    except Exception as e:
         logger.exception(f"Erro inesperado ao criar evento Google (naive): {e}")
         return None

def update_google_event(
    calendar_id: str,
    event_id: str,
    summary: str,
    description: str,
    start_naive_iso: str, # Ex: "2025-04-18T16:30:00"
    end_naive_iso: str,   # Ex: "2025-04-18T17:00:00"
    timezone: str,         # Ex: "America/Sao_Paulo"
    service: Optional[Resource] = None,
    create_conference: bool = False,
    return_event: bool = False,
) -> Optional[Any]:
    """Atualiza um evento no Google Calendar usando datetime naive + timezone ID."""
    service = _resolve_calendar_service(service)
    if not service: return None

    event_body = {
        'summary': summary,
        'description': description,
        'start': {'dateTime': start_naive_iso, 'timeZone': timezone},
        'end': {'dateTime': end_naive_iso, 'timeZone': timezone},
    }
    try:
        if create_conference:
            try:
                existing_event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
            except Exception:
                existing_event = None
            if not extract_google_meeting_link(existing_event):
                event_body["conferenceData"] = _conference_create_request()

        logger.info(f"Atualizando evento Google ID '{event_id}' em '{calendar_id}': '{summary}' @ {start_naive_iso} [{timezone}]")
        request_kwargs = {"calendarId": calendar_id, "eventId": event_id, "body": event_body}
        if create_conference:
            request_kwargs["conferenceDataVersion"] = 1
        event = service.events().patch(**request_kwargs).execute()
        if create_conference:
            event = _hydrate_conference_event(service, calendar_id, event) or event
        updated_event_id = event.get('id')
        logger.info(f"Evento Google atualizado com sucesso. Event ID: {updated_event_id}")
        return _event_return_value(event, return_event)
    except HttpError as error:
        logger.error(f"Erro API Google ao atualizar evento '{event_id}' (naive): {error.status_code}...")
        return None
    except Exception as e:
         logger.exception(f"Erro inesperado ao atualizar evento Google '{event_id}' (naive): {e}")
         return None

def delete_google_event(calendar_id: str, event_id: str, service: Optional[Resource] = None) -> bool:
    """
    Deleta um evento do Google Calendar.

    Retorna: True se sucesso ou se evento já não existia, False em caso de erro.
    """
    service = _resolve_calendar_service(service)
    if not service:
        logger.error("Não foi possível deletar evento Google: Serviço não disponível.")
        return False

    try:
        logger.info(f"Deletando evento Google Calendar ID '{event_id}' do calendário '{calendar_id}'")
        # Chama a API para deletar o evento
        # execute() retorna None em sucesso (HTTP 204)
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        logger.info(f"Evento Google Calendar '{event_id}' deletado com sucesso.")
        return True
    except HttpError as error:
        # Se o evento já não existe (404 ou 410), considera sucesso para nossa lógica
        if error.resp.status in [404, 410]:
            logger.warning(f"Evento Google Calendar '{event_id}' não encontrado ou já deletado (status {error.resp.status}). Considerado sucesso.")
            return True
        else:
            # Outros erros da API
            logger.error(f"Erro API Google ao deletar evento '{event_id}': {error.status_code} - {error.reason}. Detalhes: {error.content}")
            return False
    except Exception as e:
         logger.exception(f"Erro inesperado ao deletar evento Google Calendar '{event_id}': {e}")
         return False

def get_google_calendar_timezone(calendar_id: str, service: Optional[Resource] = None) -> Optional[str]:
    """
    Busca o timezone configurado para um Google Calendar específico.

    Args:
        calendar_id: O ID do Google Calendar.

    Returns:
        A string IANA do timezone (ex: 'America/Sao_Paulo') se sucesso, None caso contrário.
    """
    service = _resolve_calendar_service(service)
    if not service:
        logger.error("Não foi possível obter timezone do Google Calendar: Serviço não disponível.")
        return None

    try:
        logger.debug(f"Buscando metadados do Google Calendar ID: {calendar_id}")
        try:
            calendar_metadata = service.calendarList().get(calendarId=calendar_id).execute()
        except HttpError:
            calendar_metadata = service.calendars().get(calendarId=calendar_id).execute()
        timezone = calendar_metadata.get('timeZone')
        if timezone:
            logger.info(f"Timezone encontrado para Calendar ID '{calendar_id}': {timezone}")
            return timezone
        else:
            logger.warning(f"Campo 'timeZone' não encontrado nos metadados do Calendar ID '{calendar_id}'. Resposta: {calendar_metadata}")
            return None
    except HttpError as error:
        logger.error(f"Erro API Google ao buscar metadados do Calendar ID '{calendar_id}': {error.status_code} - {error.reason}. Detalhes: {error.content}")
        return None
    except Exception as e:
         logger.exception(f"Erro inesperado ao buscar timezone do Google Calendar ID '{calendar_id}': {e}")
         return None
