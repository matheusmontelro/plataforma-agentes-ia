"""
WhatsApp contact-card tools for frontend-created agents.

The agent can choose only from contact cards configured in AgentBuilder. The
destination is always the current WhatsApp conversation from runtime context.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Annotated, Any, Dict, List, Optional

from agents import RunContextWrapper, function_tool
from pydantic import Field

logger = logging.getLogger(__name__)


def create_whatsapp_contact_card_tools(
    *,
    company_id: int,
    contact_cards: Optional[List[Dict[str, Any]]] = None,
) -> List[Any]:
    """Create WhatsApp contact-card tools scoped to a workspace."""

    configured_cards = _normalize_contact_cards(contact_cards or [])

    @function_tool
    async def send_whatsapp_contact_card(
        context: RunContextWrapper,
        contact_key: Annotated[str, Field(description="Chave do card de contato configurado no AgentBuilder.")],
        reason: Annotated[str, Field(description="Motivo curto para enviar este card nesta conversa.")] = "",
    ) -> Dict[str, Any]:
        """
        Envia um card de contato WhatsApp para o lead da conversa atual.

        Use apenas quando o card configurado for relevante para o próximo passo.
        Não peça nem informe outro destinatário: o backend sempre envia para o
        chat WhatsApp atual.
        """

        from backend.db import get_db
        from backend.integrations.whatsapp_provider import send_contact_card

        runtime_context = getattr(context, "context", None)
        recipient_phone = _digits_only(getattr(runtime_context, "contact_phone", "") or "")
        selected_card = _select_contact_card(configured_cards, contact_key)

        if not configured_cards:
            return {
                "success": False,
                "error": "no_contact_cards_configured",
                "message_for_agent": "Nenhum card de contato foi configurado nesta tool.",
            }

        if selected_card is None:
            return {
                "success": False,
                "error": "contact_card_not_found",
                "available_contact_cards": _available_contact_card_payloads(configured_cards),
                "message_for_agent": "Escolha uma das chaves configuradas antes de enviar o card.",
            }

        if not recipient_phone:
            return {
                "success": False,
                "error": "conversation_phone_required",
                "message_for_agent": "Não foi possível identificar o WhatsApp da conversa atual.",
            }

        contact_payload = _contact_card_to_waha_payload(selected_card)
        db = next(get_db())
        try:
            result = send_contact_card(
                company_id=company_id,
                phone=recipient_phone,
                contacts=[contact_payload],
                db=db,
            )
            message_id = result.get("id") or result.get("messageId")
            sent_payload = {
                "contact_key": selected_card["key"],
                "contact_name": selected_card["full_name"],
                "contact_phone": selected_card["phone_number"],
                "message_id": message_id,
                "reason": reason,
            }
            if runtime_context is not None:
                setattr(runtime_context, "whatsapp_contact_card_sent", sent_payload)

            return {
                "success": True,
                **sent_payload,
                "message_for_agent": "Card de contato enviado. Responda de forma curta confirmando o envio quando fizer sentido.",
            }
        except Exception as exc:
            logger.exception("[WhatsAppContactCardTool] send_whatsapp_contact_card failed")
            return {
                "success": False,
                "error": "send_failed",
                "message_for_agent": "Não foi possível enviar o card de contato agora.",
                "details": str(exc),
            }
        finally:
            db.close()

    return [send_whatsapp_contact_card]


def _normalize_contact_cards(cards: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    used_keys: set[str] = set()

    for index, raw_card in enumerate(cards):
        if not isinstance(raw_card, dict):
            continue
        full_name = str(
            raw_card.get("full_name")
            or raw_card.get("fullName")
            or raw_card.get("name")
            or ""
        ).strip()
        phone_number = str(
            raw_card.get("phone_number")
            or raw_card.get("phoneNumber")
            or raw_card.get("phone")
            or ""
        ).strip()
        if not full_name or not phone_number:
            continue

        key = _slugify(raw_card.get("key") or raw_card.get("contact_key") or full_name)
        if not key:
            key = f"contato_{index + 1}"
        original_key = key
        suffix = 2
        while key in used_keys:
            key = f"{original_key}_{suffix}"
            suffix += 1
        used_keys.add(key)

        normalized.append(
            {
                "key": key,
                "full_name": full_name,
                "phone_number": phone_number,
                "organization": str(raw_card.get("organization") or "").strip(),
                "whatsapp_id": _digits_only(
                    raw_card.get("whatsapp_id")
                    or raw_card.get("whatsappId")
                    or raw_card.get("waid")
                    or phone_number
                ),
                "when_to_use": str(
                    raw_card.get("when_to_use")
                    or raw_card.get("whenToUse")
                    or raw_card.get("when")
                    or ""
                ).strip(),
                "vcard": str(raw_card.get("vcard") or "").strip(),
            }
        )

    return normalized


def _select_contact_card(cards: List[Dict[str, str]], contact_key: str) -> Optional[Dict[str, str]]:
    if len(cards) == 1 and not str(contact_key or "").strip():
        return cards[0]
    normalized_key = _slugify(contact_key)
    for card in cards:
        if card["key"] == normalized_key:
            return card
    return None


def _available_contact_card_payloads(cards: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return [
        {
            "key": card["key"],
            "full_name": card["full_name"],
            "phone_number": card["phone_number"],
            "when_to_use": card.get("when_to_use", ""),
        }
        for card in cards
    ]


def _contact_card_to_waha_payload(card: Dict[str, str]) -> Dict[str, str]:
    phone_number = _format_display_phone(card["phone_number"])
    whatsapp_id = card.get("whatsapp_id") or _digits_only(phone_number)
    vcard = card.get("vcard") or _build_vcard(
        full_name=card["full_name"],
        organization=card.get("organization", ""),
        phone_number=phone_number,
        whatsapp_id=whatsapp_id,
    )

    payload = {
        "fullName": card["full_name"],
        "phoneNumber": phone_number,
        "vcard": vcard,
    }
    if card.get("organization"):
        payload["organization"] = card["organization"]
    if whatsapp_id:
        payload["whatsappId"] = whatsapp_id
    return payload


def _build_vcard(
    *,
    full_name: str,
    organization: str,
    phone_number: str,
    whatsapp_id: str,
) -> str:
    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"FN:{_escape_vcard_text(full_name)}",
    ]
    if organization:
        lines.append(f"ORG:{_escape_vcard_text(organization)};")
    tel_meta = ";type=CELL;type=VOICE"
    if whatsapp_id:
        tel_meta += f";waid={whatsapp_id}"
    lines.extend(
        [
            f"TEL{tel_meta}:{phone_number}",
            "END:VCARD",
        ]
    )
    return "\n".join(lines)


def _escape_vcard_text(value: str) -> str:
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .strip()
    )


def _format_display_phone(value: str) -> str:
    phone = str(value or "").strip()
    if phone.startswith("+"):
        return phone
    digits = _digits_only(phone)
    return f"+{digits}" if digits else phone


def _digits_only(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _slugify(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")
