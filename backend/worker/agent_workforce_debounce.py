import json
import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import redis
from celery import current_app

from backend.worker.celery_app import app

logger = logging.getLogger(__name__)

redis_client = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

DEBOUNCE_KEY_PREFIX = "agent_workforce_debounce"
MAX_RESPONSE_DELAY_SECONDS = 60
BUFFER_TTL_GRACE_SECONDS = 300


def schedule_debounced_whatsapp_flow(
    *,
    company_id: int,
    operational_epoch: int,
    phone: str,
    message_text: str,
    message_data: Dict[str, Any],
    flow_id: int,
    workforce_id: int,
    delay_seconds: int,
) -> bool:
    """Buffer WhatsApp messages and schedule one FlowBuilder execution."""

    delay_seconds = _normalize_delay_seconds(delay_seconds)
    if delay_seconds <= 0:
        return False

    clean_phone = _normalize_phone(phone)
    if not clean_phone or not message_text:
        return False

    debounce_key = _debounce_key(
        company_id,
        clean_phone,
        flow_id,
        workforce_id,
        operational_epoch,
    )
    buffer_key = f"{DEBOUNCE_KEY_PREFIX}:buffer:{debounce_key}"
    task_key = f"{DEBOUNCE_KEY_PREFIX}:task:{debounce_key}"
    nonce_key = f"{DEBOUNCE_KEY_PREFIX}:nonce:{debounce_key}"
    ttl_seconds = delay_seconds + BUFFER_TTL_GRACE_SECONDS
    nonce = uuid.uuid4().hex

    db = None
    scheduled = False
    try:
        from backend.db import SessionLocal
        from backend.services.company_access_control import capture_company_job_epoch

        db = SessionLocal()
        capture_company_job_epoch(
            db,
            company_id,
            expected_epoch=operational_epoch,
        )
        payload = {
            "message_text": str(message_text).strip(),
            "message_data": message_data,
            "operational_epoch": int(operational_epoch),
            "queued_at": datetime.utcnow().isoformat(),
        }
        pipe = redis_client.pipeline()
        pipe.rpush(buffer_key, json.dumps(payload, ensure_ascii=False))
        pipe.expire(buffer_key, ttl_seconds)
        pipe.set(nonce_key, nonce, ex=ttl_seconds)
        pipe.execute()

        old_task_id = redis_client.get(task_key)
        if old_task_id:
            try:
                current_app.control.revoke(old_task_id, terminate=False)
                logger.info(
                    "[AgentWorkforceDebounce] Task anterior revogada company=%s phone=%s task_id=%s",
                    company_id,
                    clean_phone,
                    old_task_id,
                )
            except Exception as exc:
                logger.warning(
                    "[AgentWorkforceDebounce] Falha ao revogar task anterior company=%s phone=%s: %s",
                    company_id,
                    clean_phone,
                    exc,
                )

        eta = datetime.utcnow() + timedelta(seconds=delay_seconds)
        result = process_debounced_whatsapp_flow.apply_async(
            args=[
                company_id,
                clean_phone,
                flow_id,
                workforce_id,
                nonce,
                int(operational_epoch),
            ],
            eta=eta,
            queue="waha_messages_queue",
        )
        redis_client.set(task_key, result.id, ex=ttl_seconds)
        logger.info(
            "[AgentWorkforceDebounce] Execucao agendada company=%s phone=%s flow=%s workforce=%s delay=%ss task_id=%s",
            company_id,
            clean_phone,
            flow_id,
            workforce_id,
            delay_seconds,
            result.id,
        )
        scheduled = True
    except Exception as exc:
        logger.exception(
            "[AgentWorkforceDebounce] Falha ao agendar debounce company=%s phone=%s: %s",
            company_id,
            clean_phone,
            exc,
        )
    finally:
        if db is not None:
            db.rollback()
            db.close()

    if scheduled:
        _start_typing_indicator(company_id=company_id, phone=clean_phone)
        return True
    _stop_typing_indicator(company_id=company_id, phone=clean_phone)
    return False


@app.task(bind=True, ignore_result=True)
def process_debounced_whatsapp_flow(
    self,
    company_id: int,
    phone: str,
    flow_id: int,
    workforce_id: int,
    nonce: str,
    operational_epoch: Optional[int] = None,
) -> None:
    """Run the active WhatsApp flow once with the buffered messages."""

    clean_phone = _normalize_phone(phone)
    debounce_key = _debounce_key(
        company_id,
        clean_phone,
        flow_id,
        workforce_id,
        operational_epoch,
    )
    buffer_key = f"{DEBOUNCE_KEY_PREFIX}:buffer:{debounce_key}"
    task_key = f"{DEBOUNCE_KEY_PREFIX}:task:{debounce_key}"
    nonce_key = f"{DEBOUNCE_KEY_PREFIX}:nonce:{debounce_key}"

    from backend.db import SessionLocal
    from backend.services.company_access_control import (
        get_company_operational_epoch,
        validate_company_job_epoch,
    )

    gate_db = SessionLocal()
    effective_epoch = operational_epoch
    try:
        epoch_is_valid = validate_company_job_epoch(
            gate_db,
            company_id,
            operational_epoch,
        )
        if epoch_is_valid and effective_epoch is None:
            effective_epoch = get_company_operational_epoch(gate_db, company_id)
    except Exception:
        epoch_is_valid = False
        logger.exception(
            "[AgentWorkforceDebounce] Falha ao validar epoch company=%s",
            company_id,
        )
    finally:
        gate_db.close()
    if not epoch_is_valid:
        _clear_keys(buffer_key, task_key, nonce_key)
        _stop_typing_indicator(company_id=company_id, phone=clean_phone)
        logger.info(
            "[AgentWorkforceDebounce] Epoch obsoleto descartado company=%s epoch=%s",
            company_id,
            operational_epoch,
        )
        return
    if effective_epoch is None:
        _clear_keys(buffer_key, task_key, nonce_key)
        _stop_typing_indicator(company_id=company_id, phone=clean_phone)
        return

    current_nonce = redis_client.get(nonce_key)
    if current_nonce != nonce:
        logger.info(
            "[AgentWorkforceDebounce] Task obsoleta ignorada company=%s phone=%s flow=%s workforce=%s",
            company_id,
            clean_phone,
            flow_id,
            workforce_id,
        )
        return

    raw_items = redis_client.lrange(buffer_key, 0, -1)
    if not raw_items:
        logger.info(
            "[AgentWorkforceDebounce] Nenhuma mensagem no buffer company=%s phone=%s",
            company_id,
            clean_phone,
        )
        _clear_keys(buffer_key, task_key, nonce_key)
        _stop_typing_indicator(company_id=company_id, phone=clean_phone)
        return

    entries = [_parse_buffer_item(raw_item) for raw_item in raw_items]
    entries = [entry for entry in entries if entry]
    if not entries:
        _clear_keys(buffer_key, task_key, nonce_key)
        _stop_typing_indicator(company_id=company_id, phone=clean_phone)
        return

    _clear_keys(buffer_key, task_key, nonce_key)

    from backend.services.flow_executor_waha import execute_flow_message

    db = SessionLocal()
    try:
        if _contact_in_human_mode(db=db, company_id=company_id, phone=clean_phone):
            logger.info(
                "[AgentWorkforceDebounce] Contato em modo humano; fluxo ignorado company=%s phone=%s",
                company_id,
                clean_phone,
            )
            return

        messages = [
            str(entry.get("message_text") or "").strip()
            for entry in entries
            if str(entry.get("message_text") or "").strip()
        ]
        if not messages:
            return

        latest_message_data = dict(entries[-1].get("message_data") or {})
        debounced_images = _image_payloads_from_entries(entries)
        combined_body = "\n".join(messages).strip()
        flow_message_data = {
            **latest_message_data,
            "phone": clean_phone,
            "body": combined_body,
            "type": "image" if debounced_images else "text",
            "debounced_messages": messages,
            "debounced_message_count": len(messages),
            "response_delay_already_waited": True,
            "_operational_epoch": int(effective_epoch),
        }
        if debounced_images:
            flow_message_data["debounced_images"] = debounced_images
            flow_message_data["images"] = debounced_images
            flow_message_data["image"] = debounced_images[-1]
            flow_message_data["mediaUrl"] = debounced_images[-1]["imageUrl"]
            flow_message_data["caption"] = debounced_images[-1].get("caption", "")
            flow_message_data["mimetype"] = debounced_images[-1].get("mimetype", "")

        logger.info(
            "[AgentWorkforceDebounce] Executando fluxo agrupado company=%s phone=%s flow=%s workforce=%s messages=%s",
            company_id,
            clean_phone,
            flow_id,
            workforce_id,
            len(messages),
        )
        execute_flow_message(db, company_id, flow_message_data)
    except Exception as exc:
        logger.exception(
            "[AgentWorkforceDebounce] Erro ao executar fluxo agrupado company=%s phone=%s: %s",
            company_id,
            clean_phone,
            exc,
        )
        raise self.retry(exc=exc, countdown=30, max_retries=2)
    finally:
        _stop_typing_indicator(company_id=company_id, phone=clean_phone)
        db.close()


def _normalize_delay_seconds(value: Any) -> int:
    try:
        parsed = int(round(float(value or 0)))
    except (TypeError, ValueError):
        parsed = 0
    return max(0, min(MAX_RESPONSE_DELAY_SECONDS, parsed))


def _normalize_phone(phone: Any) -> str:
    return re.sub(r"\D+", "", str(phone or ""))


def _debounce_key(
    company_id: int,
    phone: str,
    flow_id: int,
    workforce_id: int,
    operational_epoch: Optional[int] = None,
) -> str:
    if operational_epoch is None:
        return (
            f"{int(company_id)}:{int(flow_id)}:"
            f"{int(workforce_id)}:{_normalize_phone(phone)}"
        )
    epoch_part = str(int(operational_epoch))
    return (
        f"{int(company_id)}:{epoch_part}:{int(flow_id)}:"
        f"{int(workforce_id)}:{_normalize_phone(phone)}"
    )


def _parse_buffer_item(raw_item: str) -> Optional[Dict[str, Any]]:
    try:
        item = json.loads(raw_item)
    except (TypeError, json.JSONDecodeError):
        return None
    return item if isinstance(item, dict) else None


def _image_payload_from_message_data(message_data: Dict[str, Any]) -> Optional[Dict[str, str]]:
    if not isinstance(message_data, dict):
        return None

    image_data = message_data.get("image") if isinstance(message_data.get("image"), dict) else {}
    source = str(
        image_data.get("imageUrl")
        or image_data.get("image_url")
        or message_data.get("mediaUrl")
        or message_data.get("imageUrl")
        or ""
    ).strip()
    message_type = str(message_data.get("type") or "").strip().lower()
    mimetype = str(
        image_data.get("mimetype")
        or message_data.get("mimetype")
        or message_data.get("mime_type")
        or ""
    ).strip()
    if not source or (message_type != "image" and not mimetype.lower().startswith("image/")):
        return None

    return {
        "imageUrl": source,
        "caption": str(image_data.get("caption") or message_data.get("caption") or "").strip(),
        "mimetype": mimetype,
    }


def _image_payloads_from_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    payloads: List[Dict[str, str]] = []
    seen_sources: set[str] = set()
    for entry in entries:
        message_data = entry.get("message_data") if isinstance(entry, dict) else None
        payload = _image_payload_from_message_data(message_data or {})
        if not payload:
            continue
        source = payload["imageUrl"]
        if source in seen_sources:
            continue
        seen_sources.add(source)
        payloads.append(payload)
    return payloads


def _clear_keys(*keys: str) -> None:
    try:
        redis_client.delete(*keys)
    except Exception:
        logger.exception("[AgentWorkforceDebounce] Falha ao limpar chaves Redis")


def _contact_in_human_mode(*, db: Any, company_id: int, phone: str) -> bool:
    from backend.models import Contact

    candidates = _phone_candidates(phone)
    if not candidates:
        return False

    contact = (
        db.query(Contact)
        .filter(Contact.company_id == company_id, Contact.phone.in_(candidates))
        .first()
    )
    return bool(contact and contact.human_mode)


def _phone_candidates(phone: str) -> List[str]:
    digits = _normalize_phone(phone)
    candidates = [digits] if digits else []
    if digits.startswith("55") and len(digits) > 11:
        candidates.append(digits[2:])
    elif len(digits) in {10, 11}:
        candidates.append(f"55{digits}")
    return list(dict.fromkeys(candidates))


def _start_typing_indicator(*, company_id: int, phone: str) -> None:
    _set_typing_indicator(company_id=company_id, phone=phone, active=True)


def _stop_typing_indicator(*, company_id: int, phone: str) -> None:
    _set_typing_indicator(company_id=company_id, phone=phone, active=False)


def _set_typing_indicator(*, company_id: int, phone: str, active: bool) -> None:
    try:
        from backend.db import SessionLocal
        from backend.integrations.waha_sdk import get_client as get_waha_client
        from backend.integrations.whatsapp_provider import (
            WhatsAppConfig,
            _locked_company_remote_operation,
        )

        db = SessionLocal()
        try:
            with _locked_company_remote_operation(company_id, db) as locked_db:
                config = WhatsAppConfig.from_company(company_id, locked_db)
                if not config or not config.is_waha():
                    return
                client = get_waha_client(
                    base_url=config.config["base_url"],
                    **{"api" + "_key": config.config["api_key"]},
                )
                if active:
                    client.start_typing(session=config.config["session_name"], phone=phone)
                else:
                    client.stop_typing(session=config.config["session_name"], phone=phone)
        finally:
            db.close()
    except Exception as exc:
        action = "iniciar" if active else "parar"
        logger.warning(
            "[AgentWorkforceDebounce] Nao foi possivel %s digitacao company=%s phone=%s: %s",
            action,
            company_id,
            phone,
            exc,
        )
