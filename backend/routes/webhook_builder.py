from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from backend.db import get_db
from backend.auth import get_current_user
from backend.models import WebhookTrigger, WebhookEvent, Client, User
from pydantic import BaseModel, ConfigDict
from typing import Any, Dict, Optional, List, Union
import uuid
import logging
from datetime import datetime
import os
import json
from fastapi.responses import PlainTextResponse, JSONResponse
import requests

router = APIRouter()
logger = logging.getLogger(__name__)

SENSITIVE_PAYLOAD_KEYS = {
    "authorization",
    "access_token",
    "refresh_token",
    "token",
    "secret",
    "client_secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "cookie",
    "set-cookie",
}
MAX_PAYLOAD_DEPTH = 5
MAX_PAYLOAD_KEYS = 60
MAX_PAYLOAD_LIST_ITEMS = 25
MAX_PAYLOAD_STRING_LENGTH = 600

# Pydantic Schemas
class WebhookTriggerCreate(BaseModel):
    name: str
    description: Optional[str] = None
    method: Optional[str] = "POST"

class WebhookTriggerUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    method: Optional[str] = None
    is_active: Optional[bool] = None

class WebhookTriggerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int # Added company_id
    name: str
    uuid: str
    description: Optional[str]
    method: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    event_count: int = 0
    last_event_at: Optional[datetime] = None

class WebhookEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    webhook_id: Optional[int] = None
    webhook_name: Optional[str] = None
    webhook_uuid: Optional[str] = None
    method: str
    status: str
    status_code: int
    source_ip: Optional[str] = None
    content_type: Optional[str] = None
    payload_preview: Optional[Any] = None
    payload_size: Optional[int] = None
    received_at: datetime


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").strip()
    return normalized in SENSITIVE_PAYLOAD_KEYS or any(
        marker in normalized for marker in ("password", "passwd", "secret", "token")
    )


def _truncate_string(value: str, limit: int = MAX_PAYLOAD_STRING_LENGTH) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}... [truncado]"


def _sanitize_payload(value: Any, depth: int = 0) -> Any:
    if depth >= MAX_PAYLOAD_DEPTH:
        return "[conteudo profundo truncado]"

    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_PAYLOAD_KEYS:
                sanitized["__truncated_keys__"] = len(value) - MAX_PAYLOAD_KEYS
                break

            key_text = str(key)
            if _is_sensitive_key(key_text):
                sanitized[key_text] = "[redigido]"
            else:
                sanitized[key_text] = _sanitize_payload(item, depth + 1)
        return sanitized

    if isinstance(value, list):
        preview = [_sanitize_payload(item, depth + 1) for item in value[:MAX_PAYLOAD_LIST_ITEMS]]
        if len(value) > MAX_PAYLOAD_LIST_ITEMS:
            preview.append({"__truncated_items__": len(value) - MAX_PAYLOAD_LIST_ITEMS})
        return preview

    if isinstance(value, str):
        return _truncate_string(value)

    if value is None or isinstance(value, (bool, int, float)):
        return value

    return _truncate_string(str(value))


def _payload_size(payload: Any) -> int:
    try:
        return len(json.dumps(payload, ensure_ascii=False, default=str))
    except Exception:
        return len(str(payload))


def _request_source_ip(request: Request) -> Optional[str]:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()[:100]
    if request.client and request.client.host:
        return request.client.host[:100]
    return None


def _record_webhook_event(
    db: Session,
    trigger: WebhookTrigger,
    request: Request,
    payload: Any,
    status: str,
    status_code: int,
) -> Optional[WebhookEvent]:
    event = WebhookEvent(
        company_id=trigger.company_id,
        webhook_trigger_id=trigger.id,
        webhook_uuid=trigger.uuid,
        webhook_name=trigger.name,
        method=request.method,
        status=status,
        status_code=status_code,
        source_ip=_request_source_ip(request),
        user_agent=_truncate_string(request.headers.get("user-agent", ""), 1000) or None,
        content_type=_truncate_string(request.headers.get("content-type", ""), 255) or None,
        payload_preview=_sanitize_payload(payload),
        payload_size=_payload_size(payload),
    )

    try:
        db.add(event)
        db.commit()
        db.refresh(event)
        return event
    except Exception:
        db.rollback()
        logger.exception("Failed to record webhook event for trigger_id=%s", trigger.id)
        return None

# CRUD Routes

@router.post("/api/webhooks", response_model=WebhookTriggerResponse)
def create_webhook(
    webhook: WebhookTriggerCreate,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    # Determine company_id
    company_id = current_user.company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    new_webhook = WebhookTrigger(
        company_id=company_id,
        name=webhook.name,
        uuid=str(uuid.uuid4()),
        description=webhook.description,
        method=webhook.method,
        is_active=True
    )
    db.add(new_webhook)
    db.commit()
    db.refresh(new_webhook)
    logger.info(f"Webhook created: {new_webhook.uuid} by user {current_user.id}")
    return new_webhook

@router.get("/api/webhooks", response_model=List[WebhookTriggerResponse])
def list_webhooks(
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    company_id = current_user.company_id
    triggers = db.query(WebhookTrigger).filter(WebhookTrigger.company_id == company_id).all()
    trigger_ids = [trigger.id for trigger in triggers]

    if trigger_ids:
        event_rows = db.query(
            WebhookEvent.webhook_trigger_id,
            func.count(WebhookEvent.id),
            func.max(WebhookEvent.received_at),
        ).filter(
            WebhookEvent.company_id == company_id,
            WebhookEvent.webhook_trigger_id.in_(trigger_ids),
        ).group_by(WebhookEvent.webhook_trigger_id).all()
        event_stats = {
            row[0]: {
                "event_count": row[1],
                "last_event_at": row[2],
            }
            for row in event_rows
        }

        for trigger in triggers:
            stats = event_stats.get(trigger.id, {})
            trigger.event_count = int(stats.get("event_count") or 0)
            trigger.last_event_at = stats.get("last_event_at")

    return triggers


@router.get("/api/webhooks/events", response_model=List[WebhookEventResponse])
def list_webhook_events(
    webhook_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    company_id = current_user.company_id
    query = db.query(WebhookEvent).filter(WebhookEvent.company_id == company_id)

    if webhook_id is not None:
        owned_trigger = db.query(WebhookTrigger.id).filter(
            WebhookTrigger.id == webhook_id,
            WebhookTrigger.company_id == company_id,
        ).first()
        if not owned_trigger:
            raise HTTPException(status_code=404, detail="Webhook not found")
        query = query.filter(WebhookEvent.webhook_trigger_id == webhook_id)

    events = query.order_by(WebhookEvent.received_at.desc()).limit(limit).all()
    for event in events:
        event.webhook_id = event.webhook_trigger_id
    return events

@router.put("/api/webhooks/{webhook_id}", response_model=WebhookTriggerResponse)
def update_webhook(
    webhook_id: int,
    webhook_update: WebhookTriggerUpdate,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    company_id = current_user.company_id
    trigger = db.query(WebhookTrigger).filter(
        WebhookTrigger.id == webhook_id,
        WebhookTrigger.company_id == company_id
    ).first()

    if not trigger:
        raise HTTPException(status_code=404, detail="Webhook not found")

    if webhook_update.name is not None:
        trigger.name = webhook_update.name
    if webhook_update.description is not None:
        trigger.description = webhook_update.description
    if webhook_update.method is not None:
        trigger.method = webhook_update.method
    if webhook_update.is_active is not None:
        trigger.is_active = webhook_update.is_active

    db.commit()
    db.refresh(trigger)
    return trigger

@router.delete("/api/webhooks/{webhook_id}")
def delete_webhook(
    webhook_id: int,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    company_id = current_user.company_id
    trigger = db.query(WebhookTrigger).filter(
        WebhookTrigger.id == webhook_id,
        WebhookTrigger.company_id == company_id
    ).first()

    if not trigger:
        raise HTTPException(status_code=404, detail="Webhook not found")

    db.delete(trigger)
    db.commit()
    return {"message": "Webhook deleted successfully"}

# Public Trigger Endpoint
from backend.ws_manager import manager # Import manager

# CORS headers for public webhook endpoints
WEBHOOK_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With",
    "Access-Control-Max-Age": "86400",  # 24 hours cache for preflight
}


def _get_facebook_verify_token() -> Optional[str]:
    """Return configured verify token for Facebook Webhooks validation."""
    return (
        os.getenv("FACEBOOK_WEBHOOK_VERIFY_TOKEN")
        or os.getenv("FB_WEBHOOK_VERIFY_TOKEN")
        or os.getenv("META_WEBHOOK_VERIFY_TOKEN")
    )


def _extract_first_value(field_data: list, field_names: List[str]) -> str:
    """Get first matching field value from Meta lead field_data payload."""
    if not isinstance(field_data, list):
        return ""

    wanted = {name.lower() for name in field_names}
    for item in field_data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").lower().strip()
        if name not in wanted:
            continue
        values = item.get("values") or []
        if isinstance(values, list) and values:
            return str(values[0] or "").strip()
        if values is not None:
            return str(values).strip()
    return ""


def _get_facebook_user_token() -> Optional[str]:
    """
    User-level token used to derive a Page token and query lead details.
    NOTE: This token must be maintained by ops. If expired, webhook still works,
    but only with basic leadgen metadata.
    """
    return (
        os.getenv("PAGE_ACCESS_TOKEN")
        or os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
        or os.getenv("FB_PAGE_ACCESS_TOKEN")
        or os.getenv("META_PAGE_ACCESS_TOKEN")
    )


def _get_page_access_token(page_id: str, user_token: str) -> Optional[str]:
    try:
        resp = requests.get(
            f"https://graph.facebook.com/v25.0/{page_id}",
            params={"fields": "access_token", "access_token": user_token},
            timeout=8
        )
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            logger.warning(
                "Graph page token lookup failed page_id=%s error=%s",
                page_id,
                data.get("error")
            )
            return None

        page_token = data.get("access_token")
        if not page_token:
            logger.warning("Graph page token lookup returned no access_token for page_id=%s", page_id)
            return None

        return page_token
    except Exception as e:
        logger.warning("Failed to fetch page access token for page_id=%s: %s", page_id, e)
        return None


def _fetch_facebook_lead_raw(leadgen_id: str, access_token: str) -> tuple[Optional[dict], Optional[dict]]:
    """Query Graph lead endpoint and return (data, error)."""
    try:
        resp = requests.get(
            f"https://graph.facebook.com/v25.0/{leadgen_id}",
            params={
                # page_id is not a valid field on this edge for all app modes/versions.
                # Keep canonical page_id from webhook payload fallback argument.
                "fields": "id,created_time,ad_id,form_id,field_data",
                "access_token": access_token
            },
            timeout=8
        )
        data = resp.json()
    except Exception as e:
        logger.warning("Failed to fetch Facebook lead raw leadgen_id=%s: %s", leadgen_id, e)
        return None, {"message": str(e), "type": "request_exception"}

    if isinstance(data, dict) and data.get("error"):
        return None, data.get("error")

    if not isinstance(data, dict):
        return None, {"message": "Unexpected Graph response format", "type": "invalid_response"}

    return data, None


def _fetch_facebook_lead_details(leadgen_id: str, page_id: str) -> dict:
    """
    Try to enrich leadgen webhook event with field_data (name/phone/email).
    Fallback returns minimal metadata when Graph lookup fails.
    """
    base = {
        "source": "facebook_leadgen",
        "leadgen_id": leadgen_id,
        "page_id": page_id,
        "form_id": "",
        "created_time": "",
        "name": "",
        "phone": "",
        "email": "",
        "field_data": [],
    }

    configured_token = _get_facebook_user_token()
    if not configured_token:
        logger.warning("No Facebook token configured; leadgen_id=%s will remain without field_data", leadgen_id)
        return base

    # Try configured token directly first (works when env already contains a Page Access Token).
    data, error = _fetch_facebook_lead_raw(leadgen_id, configured_token)

    # Fallback: if configured token is user/system token, derive page token and retry.
    if data is None:
        page_token = _get_page_access_token(page_id, configured_token)
        if page_token and page_token != configured_token:
            data, error = _fetch_facebook_lead_raw(leadgen_id, page_token)

    if data is None:
        logger.warning(
            "Graph lead lookup failed leadgen_id=%s page_id=%s error=%s",
            leadgen_id,
            page_id,
            error
        )
        return base

    try:
        field_data = data.get("field_data") or []
        enriched = {
            **base,
            "leadgen_id": str(data.get("id") or leadgen_id),
            "page_id": str(data.get("page_id") or page_id),
            "form_id": str(data.get("form_id") or ""),
            "created_time": str(data.get("created_time") or ""),
            "field_data": field_data,
        }

        # Canonical extraction for Flow Builder variables.
        full_name = _extract_first_value(field_data, ["full_name", "name", "nome", "nome_completo"])
        first_name = _extract_first_value(field_data, ["first_name"])
        last_name = _extract_first_value(field_data, ["last_name"])
        if not full_name and (first_name or last_name):
            full_name = f"{first_name} {last_name}".strip()

        enriched["name"] = full_name
        enriched["phone"] = _extract_first_value(
            field_data,
            [
                "phone_number",
                "phone",
                "whatsapp",
                "whatsapp_number",
                "numero_do_whatsapp",
                "número_do_whatsapp",
                "telefone",
                "telefone_principal",
                "celular",
            ],
        )
        enriched["email"] = _extract_first_value(field_data, ["email"])
        return enriched
    except Exception as e:
        logger.warning("Failed to fetch Facebook lead details leadgen_id=%s: %s", leadgen_id, e)
        return base


def _normalize_facebook_leadgen_payload(payload: dict) -> Optional[dict]:
    """
    Convert Meta webhook payload shape:
      {object:'page', entry:[{changes:[{field:'leadgen', value:{...}}]}]}
    into a Flow-friendly payload with canonical fields and `body`.
    """
    if not isinstance(payload, dict):
        return None
    if payload.get("object") != "page":
        return None

    entries = payload.get("entry")
    if not isinstance(entries, list) or not entries:
        return None

    for entry in entries:
        changes = entry.get("changes") if isinstance(entry, dict) else None
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict):
                continue
            if str(change.get("field") or "").strip().lower() != "leadgen":
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue

            leadgen_id = str(value.get("leadgen_id") or "").strip()
            page_id = str(value.get("page_id") or entry.get("id") or "").strip()
            if not leadgen_id or not page_id:
                continue

            lead_details = _fetch_facebook_lead_details(leadgen_id, page_id)
            normalized = {
                "source": "facebook_leadgen",
                "leadgen_id": lead_details.get("leadgen_id") or leadgen_id,
                "page_id": lead_details.get("page_id") or page_id,
                "form_id": lead_details.get("form_id") or str(value.get("form_id") or ""),
                "created_time": lead_details.get("created_time") or str(value.get("created_time") or ""),
                "name": lead_details.get("name") or "",
                "phone": lead_details.get("phone") or "",
                "email": lead_details.get("email") or "",
                "field_data": lead_details.get("field_data") or [],
                "raw": payload,
            }
            # Backward-compatible body namespace used by existing webhook flows.
            normalized["body"] = {
                "source": normalized["source"],
                "leadgen_id": normalized["leadgen_id"],
                "page_id": normalized["page_id"],
                "form_id": normalized["form_id"],
                "created_time": normalized["created_time"],
                "name": normalized["name"],
                "phone": normalized["phone"],
                "email": normalized["email"],
                "field_data": normalized["field_data"],
            }
            return normalized

    return None


@router.get("/webhook/trigger/{webhook_uuid}")
async def verify_webhook_for_meta(
    webhook_uuid: str,
    request: Request,
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    db: Session = Depends(get_db),
):
    """
    Facebook/Meta webhook verification handshake.
    Meta sends GET with hub.mode, hub.verify_token and hub.challenge.
    """
    trigger = db.query(WebhookTrigger).filter(WebhookTrigger.uuid == webhook_uuid).first()
    if not trigger:
        raise HTTPException(status_code=404, detail="Webhook not found")

    expected_verify_token = _get_facebook_verify_token()
    if not expected_verify_token:
        logger.error(
            "Facebook webhook verification requested for %s, but verify token env var is not set",
            webhook_uuid,
        )
        raise HTTPException(
            status_code=500,
            detail="Facebook webhook verify token not configured on server",
        )

    if hub_mode == "subscribe" and hub_verify_token == expected_verify_token and hub_challenge:
        logger.info("Facebook webhook verified for trigger %s", webhook_uuid)
        return PlainTextResponse(content=hub_challenge, status_code=200)

    logger.warning(
        "Invalid Facebook webhook verification attempt for %s from %s",
        webhook_uuid,
        request.client.host if request.client else "unknown",
    )
    raise HTTPException(status_code=403, detail="Webhook verification failed")

@router.options("/webhook/trigger/{webhook_uuid}")
async def webhook_trigger_options(webhook_uuid: str):
    """Handle CORS preflight requests for webhook triggers"""
    return JSONResponse(
        content={"status": "ok"},
        headers=WEBHOOK_CORS_HEADERS
    )

@router.post("/webhook/trigger/{webhook_uuid}")
async def trigger_webhook(
    webhook_uuid: str,
    request: Request,
    db: Session = Depends(get_db)
):
    trigger = db.query(WebhookTrigger).filter(WebhookTrigger.uuid == webhook_uuid).first()

    if not trigger:
        return JSONResponse(
            status_code=404,
            content={"detail": "Webhook not found"},
            headers=WEBHOOK_CORS_HEADERS
        )

    from backend.services.company_access_control import is_company_operational
    if not is_company_operational(db, int(trigger.company_id)):
        return JSONResponse(
            status_code=423,
            content={"detail": "Company access suspended"},
            headers=WEBHOOK_CORS_HEADERS,
        )

    # Read and normalize payload before any processing so valid trigger attempts
    # can be audited without storing raw secrets.
    try:
        payload = await request.json()
    except:
        body = await request.body()
        payload = body.decode('utf-8') if body else ""

    # Normalize Facebook Lead Ads webhook payload into Flow-friendly shape.
    if isinstance(payload, dict):
        normalized_fb_payload = _normalize_facebook_leadgen_payload(payload)
        if normalized_fb_payload:
            payload = normalized_fb_payload

    if not trigger.is_active:
        _record_webhook_event(db, trigger, request, payload, status="inactive", status_code=400)
        return JSONResponse(
            status_code=400,
            content={"detail": "Webhook is inactive"},
            headers=WEBHOOK_CORS_HEADERS
        )

    recorded_event = _record_webhook_event(db, trigger, request, payload, status="received", status_code=200)
    logger.info(
        "Webhook trigger received: trigger_id=%s company_id=%s event_id=%s payload_size=%s",
        trigger.id,
        trigger.company_id,
        recorded_event.id if recorded_event else None,
        recorded_event.payload_size if recorded_event else _payload_size(payload),
    )

    # Broadcast to Flow Builder (Run Once listeners)
    # We use a special 'phone' identifier to target the specific listener
    try:
        if trigger.company_id:
            await manager.publish_message(trigger.company_id, {
                "phone": f"webhook_listener_{trigger.id}",
                "type": "webhook_event",
                "payload": payload,
                "webhook_uuid": trigger.uuid,
                "timestamp": datetime.now().isoformat()
            })
    except Exception as e:
        logger.error(f"Failed to broadcast webhook event: {e}")

    # Trigger Flow Execution (Backend)
    try:
        from backend.models import Flow
        from backend.services.company_access_control import capture_company_job_epoch
        from backend.worker.tasks_flow import execute_flow_task

        # Find active flow associated with this webhook
        flow = db.query(Flow).filter(
            Flow.trigger_webhook_id == trigger.id,
            Flow.is_active == True,
            Flow.trigger_type == 'webhook'
        ).first()

        if flow:
            logger.info(f"Triggering execution for Flow {flow.id} (Webhook {trigger.uuid})")

            operational_epoch = capture_company_job_epoch(db, trigger.company_id)
            task_payload = (
                dict(payload)
                if isinstance(payload, dict)
                else {"payload": payload}
            )
            task_payload["_operational_epoch"] = operational_epoch

            # Queue execution task via Celery
            execute_flow_task.apply_async(
                args=[flow.id, task_payload, trigger.company_id],
                kwargs={
                    "trigger_type": "webhook",
                    "webhook_uuid": trigger.uuid
                },
                queue='flow_execution_queue'
            )
            db.commit()
        else:
            logger.debug(f"No active flow found for Webhook {trigger.uuid}")

    except Exception as e:
        logger.error(f"Failed to trigger flow execution: {e}")

    return JSONResponse(
        content={"status": "received", "webhook": trigger.name},
        headers=WEBHOOK_CORS_HEADERS
    )
