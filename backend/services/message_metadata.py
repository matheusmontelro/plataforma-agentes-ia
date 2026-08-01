import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


DeliveryStatus = Optional[str]


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _as_list(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _body_preview(value: Any, limit: int = 160) -> str:
    body = str(value or "").strip()
    if len(body) <= limit:
        return body
    return f"{body[:max(0, limit - 3)]}..."


def _clean_chat_id(value: Any) -> str:
    text_value = str(value or "").strip()
    return (
        text_value
        .replace("@c.us", "")
        .replace("@s.whatsapp.net", "")
        .replace("@g.us", "")
        .replace("@lid", "")
    )


def _escape_sql_like(value: str) -> str:
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def _waha_stanza_id(provider_message_id: Any) -> str:
    value = str(provider_message_id or "").strip()
    if not value.startswith(("true_", "false_")) or "_" not in value:
        return ""

    suffix = value.rsplit("_", 1)[-1].strip()
    if not suffix or "@" in suffix:
        return ""
    return suffix


def _find_message_by_waha_stanza_id(
    db: Session,
    company_id: int,
    provider_message_id: str,
) -> Optional[Any]:
    stanza_id = _waha_stanza_id(provider_message_id)
    if not stanza_id:
        return None

    rows = db.execute(text("""
        SELECT id, zapi_message_id
        FROM messages
        WHERE company_id = :company_id
          AND from_me = true
          AND zapi_message_id IS NOT NULL
          AND zapi_message_id != :provider_message_id
          AND zapi_message_id LIKE :stanza_pattern ESCAPE '!'
        ORDER BY id DESC
        LIMIT 2
    """), {
        "company_id": company_id,
        "provider_message_id": provider_message_id,
        "stanza_pattern": f"%!_{_escape_sql_like(stanza_id)}",
    }).fetchall()

    if len(rows) == 1:
        row = rows[0]
        logger.info(
            "[MessageMetadata] ACK WAHA casado por stanza_id: ack_id=%s local_message_id=%s local_provider_id=%s",
            provider_message_id,
            getattr(row, "id", None),
            getattr(row, "zapi_message_id", None),
        )
        return row

    if len(rows) > 1:
        logger.warning(
            "[MessageMetadata] ACK WAHA ambiguo por stanza_id: company_id=%s ack_id=%s candidates=%s",
            company_id,
            provider_message_id,
            len(rows),
        )
    return None


def map_waha_ack_to_delivery_status(ack: Any, ack_name: Any = None) -> DeliveryStatus:
    ack_name_text = str(ack_name or "").strip().upper()
    if ack_name_text:
        return {
            "FAILED": "failed",
            "ERROR": "failed",
            "PENDING": "sending",
            "SERVER": "sent",
            "DEVICE": "delivered",
            "READ": "read",
            "PLAYED": "played",
        }.get(ack_name_text)

    try:
        ack_int = int(ack)
    except (TypeError, ValueError):
        return None

    if ack_int < 0:
        return "failed"
    return {
        0: "sending",
        1: "sent",
        2: "delivered",
        3: "read",
        4: "played",
        5: "played",
    }.get(ack_int, "played" if ack_int > 4 else None)


def extract_waha_reply_to(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    reply_to = payload.get("replyTo")
    if isinstance(reply_to, dict):
        media = _as_dict(reply_to.get("media"))
        metadata = {
            "id": reply_to.get("id"),
            "participant": reply_to.get("participant"),
            "body": _body_preview(reply_to.get("body")),
            "type": "media" if reply_to.get("hasMedia") else "text",
            "hasMedia": bool(reply_to.get("hasMedia")),
        }
        if media:
            metadata["media"] = {
                "mimetype": media.get("mimetype"),
                "filename": media.get("filename"),
                "url": media.get("url"),
            }
        return {key: value for key, value in metadata.items() if value not in (None, "")}

    message_data = _as_dict(_as_dict(payload.get("_data")).get("Message"))
    extended_text = _as_dict(message_data.get("extendedTextMessage"))
    context_info = _as_dict(extended_text.get("contextInfo"))
    quoted = _as_dict(context_info.get("quotedMessage"))

    if not context_info or not quoted:
        return None

    body = (
        quoted.get("conversation")
        or _as_dict(quoted.get("extendedTextMessage")).get("text")
        or _as_dict(quoted.get("imageMessage")).get("caption")
        or _as_dict(quoted.get("videoMessage")).get("caption")
        or ""
    )
    quoted_type = "text"
    if quoted.get("imageMessage"):
        quoted_type = "image"
    elif quoted.get("videoMessage"):
        quoted_type = "video"
    elif quoted.get("audioMessage"):
        quoted_type = "audio"
    elif quoted.get("documentMessage"):
        quoted_type = "file"

    metadata = {
        "id": context_info.get("stanzaId"),
        "participant": context_info.get("participant"),
        "body": _body_preview(body),
        "type": quoted_type,
        "hasMedia": quoted_type != "text",
    }
    return {key: value for key, value in metadata.items() if value not in (None, "")}


def normalize_reply_request(reply_to: Any) -> Optional[Dict[str, Any]]:
    reply = _as_dict(reply_to)
    if not reply:
        return None

    metadata = {
        "id": reply.get("id") or reply.get("messageId") or reply.get("providerMessageId"),
        "providerMessageId": reply.get("providerMessageId") or reply.get("messageId"),
        "participant": reply.get("participant"),
        "body": _body_preview(reply.get("body") or reply.get("content")),
        "type": reply.get("type") or "text",
        "senderName": reply.get("senderName") or reply.get("sender"),
    }
    return {key: value for key, value in metadata.items() if value not in (None, "")}


def resolve_waha_reply_to_id(
    db: Session,
    company_id: int,
    contact_phone: str,
    reply_to: Any,
) -> Optional[str]:
    reply = normalize_reply_request(reply_to)
    if not reply:
        return None

    candidate = str(reply.get("providerMessageId") or reply.get("id") or "").strip()
    if not candidate:
        return None

    if candidate.startswith(("true_", "false_")):
        return candidate

    row = None
    if candidate.isdigit():
        row = db.execute(text("""
            SELECT zapi_message_id
            FROM messages
            WHERE company_id = :company_id
              AND contact_phone = :contact_phone
              AND id = :message_id
            LIMIT 1
        """), {
            "company_id": company_id,
            "contact_phone": contact_phone,
            "message_id": int(candidate),
        }).fetchone()

    if not row:
        row = db.execute(text("""
            SELECT zapi_message_id
            FROM messages
            WHERE company_id = :company_id
              AND contact_phone = :contact_phone
              AND zapi_message_id = :message_id
            LIMIT 1
        """), {
            "company_id": company_id,
            "contact_phone": contact_phone,
            "message_id": candidate,
        }).fetchone()

    provider_message_id = getattr(row, "zapi_message_id", None) if row else None
    return str(provider_message_id) if provider_message_id else None


def message_metadata_for_response(message: Any) -> Dict[str, Any]:
    return {
        "providerMessageId": getattr(message, "zapi_message_id", None),
        "status": getattr(message, "delivery_status", None),
        "deliveryAck": getattr(message, "delivery_ack", None),
        "replyTo": getattr(message, "reply_to", None),
        "reactions": _as_list(getattr(message, "reactions", None)),
    }


def publish_metadata_update(company_id: int, payload: Dict[str, Any]) -> None:
    try:
        from backend.integrations.broadcast_redis import publish_to_redis

        publish_to_redis(company_id, payload)
    except Exception as exc:
        logger.warning("[MessageMetadata] Falha ao publicar update no Redis: %s", exc)


def update_message_delivery_status(
    db: Session,
    company_id: int,
    provider_message_id: str,
    status: str,
    ack: Any = None,
    ack_name: Any = None,
    local_message_id: Optional[str] = None,
    publish: bool = True,
) -> Optional[Dict[str, Any]]:
    if not provider_message_id or not status:
        return None

    ack_value = int(ack) if str(ack).lstrip("-").isdigit() else None
    row = db.execute(text("""
        UPDATE messages
        SET delivery_status = :status,
            delivery_ack = :ack,
            delivery_status_updated_at = NOW()
        WHERE company_id = :company_id
          AND zapi_message_id = :provider_message_id
        RETURNING id, contact_phone, zapi_message_id, delivery_status, delivery_ack
    """), {
        "company_id": company_id,
        "provider_message_id": provider_message_id,
        "status": status,
        "ack": ack_value,
    }).fetchone()

    if not row:
        fallback = _find_message_by_waha_stanza_id(db, company_id, provider_message_id)
        if fallback:
            row = db.execute(text("""
                UPDATE messages
                SET delivery_status = :status,
                    delivery_ack = :ack,
                    delivery_status_updated_at = NOW()
                WHERE id = :message_db_id
                RETURNING id, contact_phone, zapi_message_id, delivery_status, delivery_ack
            """), {
                "message_db_id": fallback.id,
                "status": status,
                "ack": ack_value,
            }).fetchone()
    db.commit()

    if not row:
        logger.info("[MessageMetadata] ACK sem mensagem local correspondente: company_id=%s message_id=%s", company_id, provider_message_id)
        return None

    payload = {
        "type": "message_status_update",
        "phone": row.contact_phone,
        "dbMessageId": str(row.id),
        "messageId": row.zapi_message_id,
        "providerMessageId": row.zapi_message_id,
        "localMessageId": local_message_id,
        "status": row.delivery_status,
        "ack": row.delivery_ack,
        "ackName": ack_name,
        "fromMe": True,
        "provider": "waha",
    }
    if publish:
        publish_metadata_update(company_id, payload)
    return payload


def update_message_reactions(
    db: Session,
    company_id: int,
    provider_message_id: str,
    reaction: str,
    actor_id: Optional[str],
    from_me: bool = False,
    reaction_message_id: Optional[str] = None,
    timestamp: Any = None,
    publish: bool = True,
) -> Optional[Dict[str, Any]]:
    if not provider_message_id:
        return None

    row = db.execute(text("""
        SELECT id, contact_phone, zapi_message_id, reactions
        FROM messages
        WHERE company_id = :company_id
          AND zapi_message_id = :provider_message_id
        LIMIT 1
    """), {
        "company_id": company_id,
        "provider_message_id": provider_message_id,
    }).fetchone()

    if not row:
        logger.info("[MessageMetadata] Reacao sem mensagem local correspondente: company_id=%s message_id=%s", company_id, provider_message_id)
        return None

    actor = str(actor_id or ("me" if from_me else "unknown"))
    reactions = [
        item for item in _as_list(row.reactions)
        if str(item.get("actorId") or item.get("participant") or "") != actor
    ]

    emoji = str(reaction or "")
    if emoji:
        reactions.append({
            "emoji": emoji,
            "actorId": actor,
            "actorPhone": _clean_chat_id(actor),
            "fromMe": bool(from_me),
            "messageId": reaction_message_id,
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        })

    db.execute(text("""
        UPDATE messages
        SET reactions = CAST(:reactions AS JSONB)
        WHERE id = :id
    """), {
        "id": row.id,
        "reactions": json.dumps(reactions),
    })
    db.commit()

    payload = {
        "type": "message_reaction_update",
        "phone": row.contact_phone,
        "dbMessageId": str(row.id),
        "messageId": row.zapi_message_id,
        "providerMessageId": row.zapi_message_id,
        "reactions": reactions,
        "fromMe": bool(from_me),
        "provider": "waha",
    }
    if publish:
        publish_metadata_update(company_id, payload)
    return payload
