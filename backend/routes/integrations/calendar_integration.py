# backend/routes/integrations/calendar_integration.py
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from backend.auth import ALGORITHM, SECRET_KEY, ensure_user_can_access_company, get_current_user
from backend.db import get_db
from backend.models import Agenda, CalendarIntegration
from backend.routes.integrations.google_calendar_service import (
    GOOGLE_OAUTH_SCOPES,
    build_google_oauth_service,
)
from backend.runtime_settings import PUBLIC_APP_URL, PUBLIC_BASE_URL


def require_calendar_company_access(
    company_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    ensure_user_can_access_company(user, company_id, db)
    return user


router = APIRouter()


class GoogleCalendarConfig(BaseModel):
    google_calendar_id: Optional[str] = None


class GoogleCalendarCreatePayload(BaseModel):
    summary: str
    time_zone: Optional[str] = None


class GoogleCalendarLinkPayload(BaseModel):
    google_calendar_id: str


class ClinicorpConfig(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    code_link: Optional[str] = None
    subscriber_id: Optional[str] = None


def _clean_url(raw_value: Optional[str]) -> str:
    return (raw_value or "").strip().rstrip("/")


def _public_app_origin() -> str:
    configured = _clean_url(os.getenv("GOOGLE_OAUTH_FRONTEND_REDIRECT_ORIGIN"))
    if configured:
        return configured

    frontend_url = _clean_url(os.getenv("FRONTEND_URL"))
    if frontend_url and "localhost" not in frontend_url and "127.0.0.1" not in frontend_url:
        return frontend_url

    return PUBLIC_APP_URL


def _oauth_redirect_uri() -> str:
    configured = _clean_url(os.getenv("GOOGLE_OAUTH_REDIRECT_URI"))
    if configured:
        return configured

    return f"{PUBLIC_BASE_URL}/api/integrations/calendar/google/oauth/callback"


def _oauth_client_config() -> dict:
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    redirect_uri = _oauth_redirect_uri()

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=503,
            detail="OAuth do Google não configurado. Defina GOOGLE_OAUTH_CLIENT_ID e GOOGLE_OAUTH_CLIENT_SECRET no backend.",
        )

    if redirect_uri.startswith("http://"):
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }


def _new_oauth_flow() -> Flow:
    return Flow.from_client_config(
        _oauth_client_config(),
        scopes=GOOGLE_OAUTH_SCOPES,
        redirect_uri=_oauth_redirect_uri(),
    )


def _make_state(company_id: int, user_id: Optional[int]) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "company_id": company_id,
        "user_id": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
        "type": "google_calendar_oauth",
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _read_state(state: str) -> dict:
    try:
        payload = jwt.decode(state, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=400, detail="Estado OAuth inválido ou expirado.")

    if payload.get("type") != "google_calendar_oauth" or not payload.get("company_id"):
        raise HTTPException(status_code=400, detail="Estado OAuth inválido.")
    return payload


def _get_google_integration(db: Session, company_id: int) -> Optional[CalendarIntegration]:
    return db.query(CalendarIntegration).filter(
        CalendarIntegration.provider == "google",
        CalendarIntegration.company_id == company_id,
    ).first()


def _get_google_integration_or_404(db: Session, company_id: int) -> CalendarIntegration:
    integration = _get_google_integration(db, company_id)
    if not integration or not integration.google_oauth_token:
        raise HTTPException(status_code=404, detail="Google Agenda ainda não conectado para esta empresa.")
    return integration


def _get_company_agenda_or_404(db: Session, company_id: int, agenda_id: int) -> Agenda:
    agenda = db.query(Agenda).filter(
        Agenda.id == agenda_id,
        Agenda.company_id == company_id,
    ).first()
    if not agenda:
        raise HTTPException(status_code=404, detail="Agenda local não encontrada para esta empresa.")
    return agenda


def _calendar_to_response(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "summary": item.get("summary"),
        "description": item.get("description"),
        "primary": bool(item.get("primary")),
        "access_role": item.get("accessRole"),
        "background_color": item.get("backgroundColor"),
        "time_zone": item.get("timeZone"),
    }


def _list_writable_calendars(service) -> list[dict]:
    result = service.calendarList().list(
        minAccessRole="writer",
        showHidden=True,
    ).execute()
    return [
        _calendar_to_response(item)
        for item in result.get("items", [])
        if item.get("accessRole") == "owner"
    ]


def _apply_google_calendar_to_agenda(db: Session, agenda: Agenda, calendar_item: dict) -> dict:
    agenda.google_calendar_id = calendar_item.get("id")
    agenda.google_calendar_summary = calendar_item.get("summary")
    agenda.google_calendar_time_zone = calendar_item.get("timeZone")
    db.add(agenda)
    db.commit()
    db.refresh(agenda)
    return _calendar_to_response(calendar_item)


def _select_calendar(db: Session, integration: CalendarIntegration, calendar_id: str) -> dict:
    normalized_calendar_id = (calendar_id or "").strip()
    if not normalized_calendar_id:
        raise HTTPException(status_code=400, detail="Informe uma agenda para conectar.")

    service = build_google_oauth_service(integration, db)
    if not service:
        raise HTTPException(status_code=401, detail="Google Agenda precisa ser reconectado.")

    try:
        calendar_list_entry = service.calendarList().get(calendarId=normalized_calendar_id).execute()
    except Exception:
        raise HTTPException(status_code=400, detail="Agenda não encontrada na conta Google conectada.")

    access_role = calendar_list_entry.get("accessRole")
    if access_role != "owner":
        raise HTTPException(status_code=403, detail="Escolha uma agenda que pertença à conta Google conectada.")

    integration.google_calendar_id = calendar_list_entry.get("id") or normalized_calendar_id
    integration.google_calendar_summary = calendar_list_entry.get("summary")
    db.add(integration)
    db.commit()

    return _calendar_to_response(calendar_list_entry)


def _link_calendar_to_agenda(
    db: Session,
    integration: CalendarIntegration,
    agenda: Agenda,
    calendar_id: str,
) -> dict:
    normalized_calendar_id = (calendar_id or "").strip()
    if not normalized_calendar_id:
        raise HTTPException(status_code=400, detail="Informe uma agenda Google para vincular.")

    service = build_google_oauth_service(integration, db)
    if not service:
        raise HTTPException(status_code=401, detail="Google Agenda precisa ser reconectado.")

    try:
        calendar_list_entry = service.calendarList().get(calendarId=normalized_calendar_id).execute()
    except Exception:
        raise HTTPException(status_code=400, detail="Agenda não encontrada na conta Google conectada.")

    access_role = calendar_list_entry.get("accessRole")
    if access_role != "owner":
        raise HTTPException(status_code=403, detail="Escolha uma agenda que pertença à conta Google conectada.")

    return _apply_google_calendar_to_agenda(db, agenda, calendar_list_entry)


def _oauth_success_redirect(query: str = "google_oauth=success") -> str:
    return f"{_public_app_origin()}/prompt/agenda?{query}"


@router.get("/google/{company_id}")
def get_google_calendar_config(
    company_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    config = _get_google_integration(db, company_id)
    oauth_configured = bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID") and os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"))

    if not config:
        return {
            "google_calendar_id": None,
            "google_calendar_summary": None,
            "google_account_email": None,
            "google_oauth_connected": False,
            "oauth_configured": oauth_configured,
            "oauth_redirect_uri": _oauth_redirect_uri(),
            "message": "Nenhuma integração Google para essa empresa.",
        }

    return {
        "google_calendar_id": config.google_calendar_id,
        "google_calendar_summary": config.google_calendar_summary,
        "google_account_email": config.google_account_email,
        "google_oauth_connected": bool(config.google_oauth_token),
        "oauth_configured": oauth_configured,
        "oauth_redirect_uri": _oauth_redirect_uri(),
    }


@router.get("/google/{company_id}/oauth/start")
def start_google_calendar_oauth(
    company_id: int,
    user=Depends(require_calendar_company_access),
):
    flow = _new_oauth_flow()
    state = _make_state(company_id, getattr(user, "id", None))
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return {"authorization_url": authorization_url}


@router.get("/google/oauth/callback")
def google_calendar_oauth_callback(
    state: str,
    code: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if error:
        return RedirectResponse(_oauth_success_redirect(f"google_oauth=error&reason={error}"))

    if not code:
        raise HTTPException(status_code=400, detail="Código OAuth ausente.")

    payload = _read_state(state)
    company_id = int(payload["company_id"])

    flow = _new_oauth_flow()
    try:
        flow.fetch_token(code=code)
    except Exception:
        return RedirectResponse(_oauth_success_redirect("google_oauth=error&reason=token"))

    credentials = flow.credentials
    service = build_google_oauth_service(
        type("TemporaryIntegration", (), {"google_oauth_token": json.loads(credentials.to_json())})()
    )
    if not service:
        return RedirectResponse(_oauth_success_redirect("google_oauth=error&reason=service"))

    calendars = _list_writable_calendars(service)
    primary_calendar = next((item for item in calendars if item.get("primary")), None)
    config = _get_google_integration(db, company_id)
    if not config:
        config = CalendarIntegration(provider="google", company_id=company_id)
        db.add(config)

    config.google_oauth_token = json.loads(credentials.to_json())
    config.google_oauth_scopes = " ".join(credentials.scopes or GOOGLE_OAUTH_SCOPES)
    config.google_account_email = primary_calendar.get("id") if primary_calendar else None

    db.commit()
    return RedirectResponse(_oauth_success_redirect())


@router.get("/google/{company_id}/calendars")
def list_google_calendars(
    company_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    integration = _get_google_integration_or_404(db, company_id)
    service = build_google_oauth_service(integration, db)
    if not service:
        raise HTTPException(status_code=401, detail="Google Agenda precisa ser reconectado.")
    return {"calendars": _list_writable_calendars(service)}


@router.post("/google/{company_id}/calendar/select")
def select_google_calendar(
    company_id: int,
    data: GoogleCalendarConfig,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    integration = _get_google_integration_or_404(db, company_id)
    calendar = _select_calendar(db, integration, data.google_calendar_id or "")
    return {"status": "success", "message": "Agenda Google selecionada.", "calendar": calendar}


@router.post("/google/{company_id}/agendas/{agenda_id}/link")
def link_google_calendar_to_agenda(
    company_id: int,
    agenda_id: int,
    data: GoogleCalendarLinkPayload,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    integration = _get_google_integration_or_404(db, company_id)
    agenda = _get_company_agenda_or_404(db, company_id, agenda_id)
    calendar = _link_calendar_to_agenda(db, integration, agenda, data.google_calendar_id)
    return {
        "status": "success",
        "message": "Agenda local vinculada ao Google Agenda.",
        "calendar": calendar,
        "agenda_id": agenda.id,
    }


@router.delete("/google/{company_id}/agendas/{agenda_id}/link")
def unlink_google_calendar_from_agenda(
    company_id: int,
    agenda_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    _get_google_integration_or_404(db, company_id)
    agenda = _get_company_agenda_or_404(db, company_id, agenda_id)
    agenda.google_calendar_id = None
    agenda.google_calendar_summary = None
    agenda.google_calendar_time_zone = None
    db.add(agenda)
    db.commit()
    return {
        "status": "success",
        "message": "Agenda Google desvinculada da agenda local.",
        "agenda_id": agenda.id,
    }


@router.post("/google/{company_id}/agendas/{agenda_id}/calendars")
def create_google_calendar_for_agenda(
    company_id: int,
    agenda_id: int,
    data: GoogleCalendarCreatePayload,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    integration = _get_google_integration_or_404(db, company_id)
    agenda = _get_company_agenda_or_404(db, company_id, agenda_id)
    service = build_google_oauth_service(integration, db)
    if not service:
        raise HTTPException(status_code=401, detail="Google Agenda precisa ser reconectado.")

    summary = (data.summary or "").strip()
    if not summary:
        raise HTTPException(status_code=400, detail="Informe um nome para a nova agenda.")

    body = {"summary": summary}
    if data.time_zone:
        body["timeZone"] = data.time_zone

    try:
        created = service.calendars().insert(body=body).execute()
    except Exception:
        raise HTTPException(status_code=400, detail="Não foi possível criar a agenda na conta Google conectada.")

    calendar = _apply_google_calendar_to_agenda(db, agenda, created)
    return {
        "status": "success",
        "message": "Agenda Google criada e vinculada à agenda local.",
        "calendar": calendar,
        "agenda_id": agenda.id,
    }


@router.post("/google/{company_id}/calendars")
def create_google_calendar(
    company_id: int,
    data: GoogleCalendarCreatePayload,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    integration = _get_google_integration_or_404(db, company_id)
    service = build_google_oauth_service(integration, db)
    if not service:
        raise HTTPException(status_code=401, detail="Google Agenda precisa ser reconectado.")

    summary = (data.summary or "").strip()
    if not summary:
        raise HTTPException(status_code=400, detail="Informe um nome para a nova agenda.")

    body = {"summary": summary}
    if data.time_zone:
        body["timeZone"] = data.time_zone

    try:
        created = service.calendars().insert(body=body).execute()
    except Exception:
        raise HTTPException(status_code=400, detail="Não foi possível criar a agenda na conta Google conectada.")

    integration.google_calendar_id = created.get("id")
    integration.google_calendar_summary = created.get("summary")
    db.add(integration)
    db.commit()

    return {
        "status": "success",
        "message": "Agenda Google criada e selecionada.",
        "calendar": _calendar_to_response(created),
    }


@router.post("/google/{company_id}")
def create_google_calendar_config(
    company_id: int,
    data: GoogleCalendarConfig,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    integration = _get_google_integration_or_404(db, company_id)
    calendar = _select_calendar(db, integration, data.google_calendar_id or "")
    return {"status": "success", "message": "Agenda Google selecionada.", "calendar": calendar}


@router.put("/google/{company_id}")
def update_google_calendar_config(
    company_id: int,
    data: GoogleCalendarConfig,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    integration = _get_google_integration_or_404(db, company_id)
    calendar = _select_calendar(db, integration, data.google_calendar_id or "")
    return {"status": "success", "message": "Agenda Google selecionada.", "calendar": calendar}


@router.delete("/google/{company_id}")
def delete_google_calendar_config(
    company_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    config = _get_google_integration(db, company_id)
    if not config:
        raise HTTPException(status_code=404, detail="Integração Google não encontrada para essa empresa.")

    db.query(Agenda).filter(Agenda.company_id == company_id).update({
        Agenda.google_calendar_id: None,
        Agenda.google_calendar_summary: None,
        Agenda.google_calendar_time_zone: None,
    }, synchronize_session=False)
    db.delete(config)
    db.commit()
    return {"status": "success", "message": "Integração Google removida com sucesso."}


@router.get("/clinicorp/{company_id}")
def get_clinicorp_config(
    company_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    config = db.query(CalendarIntegration).options(
        joinedload(CalendarIntegration.clinicorp_details)
    ).filter(
        CalendarIntegration.provider == "clinicorp",
        CalendarIntegration.company_id == company_id
    ).first()

    if not config:
        return {
            "username": None,
            "password": None,
            "code_link": None,
            "subscriber_id": None,
            "business_id": None,
            "dentist_person_id": None,
            "message": "Nenhuma integração Clinicorp para essa empresa."
        }

    details = config.clinicorp_details
    return {
        "username": config.clinicorp_username,
        "code_link": config.clinicorp_code_link,
        "subscriber_id": config.clinicorp_subscriber_id,
        "business_id": details.business_id if details else None,
        "dentist_person_id": details.dentist_person_id if details else None,
    }


@router.post("/clinicorp/{company_id}")
def create_clinicorp_config(
    company_id: int,
    data: ClinicorpConfig,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    config = db.query(CalendarIntegration).filter_by(
        provider="clinicorp",
        company_id=company_id
    ).first()

    if config:
        config.clinicorp_username = data.username
        config.clinicorp_password = data.password
        config.clinicorp_code_link = data.code_link
        config.clinicorp_subscriber_id = data.subscriber_id
    else:
        config = CalendarIntegration(
            provider="clinicorp",
            company_id=company_id,
            clinicorp_username=data.username,
            clinicorp_password=data.password,
            clinicorp_code_link=data.code_link,
            clinicorp_subscriber_id=data.subscriber_id
        )
        db.add(config)

    db.commit()
    return {"status": "success", "message": "Integração Clinicorp (POST) criada ou sobrescrita."}


@router.put("/clinicorp/{company_id}")
def update_clinicorp_config(
    company_id: int,
    data: ClinicorpConfig,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    config = db.query(CalendarIntegration).filter_by(
        provider="clinicorp",
        company_id=company_id
    ).first()

    if not config:
        config = CalendarIntegration(
            provider="clinicorp",
            company_id=company_id,
            clinicorp_username=data.username,
            clinicorp_password=data.password,
            clinicorp_code_link=data.code_link,
            clinicorp_subscriber_id=data.subscriber_id
        )
        db.add(config)
    else:
        config.clinicorp_username = data.username
        config.clinicorp_password = data.password
        config.clinicorp_code_link = data.code_link
        config.clinicorp_subscriber_id = data.subscriber_id

    db.commit()
    return {"status": "success", "message": "Integração Clinicorp (PUT) atualizada ou criada."}


@router.delete("/clinicorp/{company_id}")
def delete_clinicorp_config(
    company_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_calendar_company_access),
):
    config = db.query(CalendarIntegration).filter_by(
        provider="clinicorp",
        company_id=company_id
    ).first()

    if not config:
        raise HTTPException(status_code=404, detail="Integração Clinicorp não encontrada para essa empresa.")

    db.delete(config)
    db.commit()
    return {"status": "success", "message": "Integração Clinicorp removida com sucesso."}
