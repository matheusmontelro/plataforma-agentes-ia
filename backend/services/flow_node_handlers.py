"""
Flow Node Handlers

Individual handlers for each node type in the FlowBuilder.
Each handler executes a specific action and returns results.
"""

import logging
import re
from abc import ABC, abstractmethod
from math import ceil
from typing import Dict, Any, List, Optional, Type
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta, timezone

from backend.services.telegram_service import (
    TelegramConfigurationError,
    decrypt_bot_token,
    get_company_telegram_integration,
    send_telegram_text,
)

logger = logging.getLogger(__name__)

MAX_AGENT_RESPONSE_DELAY_SECONDS = 60

AGENT_RESPONSE_VARIABLES = {
    "agent_workforce.response",
    "agentWorkforce.response",
    "agent.response",
    "agent_response",
}

FIRST_NAME_KEYS = ("first_name", "primeiro_nome")
FULL_NAME_KEYS = ("full_name", "nome_completo", "name", "nome")
CONTACT_NAME_CONTAINER_KEYS = (
    "lead",
    "contact",
    "client",
    "customer",
    "body",
    "fields",
    "field_data_values",
)
ROOT_CONTACT_PAYLOAD_KEYS = ("trigger", *CONTACT_NAME_CONTAINER_KEYS)
TRIGGER_NODE_OUTPUT_PREFIXES = ("webhookTrigger_", "whatsappTrigger_", "webhookNode_")


def _is_agent_response_template(content: str) -> bool:
    if not isinstance(content, str) or "{{" not in content:
        return False

    for match in re.finditer(r"\{\{([^}]+)\}\}", content):
        if match.group(1).strip() in AGENT_RESPONSE_VARIABLES:
            return True
    return False


def _clean_contact_name(value: Any) -> str:
    text_value = str(value or "").strip()
    if not text_value:
        return ""

    has_letter = any(character.isalpha() for character in text_value)
    digits = ''.join(filter(str.isdigit, text_value))
    if not has_letter and len(digits) >= 8:
        return ""

    return text_value


def _first_name_from_value(value: Any) -> str:
    contact_name = _clean_contact_name(value)
    if not contact_name:
        return ""
    return contact_name.split()[0]


def _dict_or_empty(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _collect_contact_name_payloads(payload: Dict[str, Any], max_depth: int = 3) -> List[Dict[str, Any]]:
    payloads = [payload]
    if max_depth <= 0:
        return payloads

    for key in CONTACT_NAME_CONTAINER_KEYS:
        nested_payload = payload.get(key)
        if isinstance(nested_payload, dict):
            payloads.extend(_collect_contact_name_payloads(nested_payload, max_depth - 1))

    return payloads


def _is_trigger_node_output(key: str, value: Any) -> bool:
    if not isinstance(value, dict):
        return False

    node_key = key.split(".", 1)[1] if key.startswith("nodes.") else key
    if node_key.startswith(TRIGGER_NODE_OUTPUT_PREFIXES):
        return True

    return value.get("type") in {"trigger", "webhook_trigger", "whatsapp_trigger"} and isinstance(value.get("body"), dict)


def _contact_name_payloads(variables: Dict[str, Any]) -> List[Dict[str, Any]]:
    payloads: List[Dict[str, Any]] = [variables]

    for key in ROOT_CONTACT_PAYLOAD_KEYS:
        payload = variables.get(key)
        if isinstance(payload, dict):
            payloads.extend(_collect_contact_name_payloads(payload))

    for key, value in variables.items():
        if _is_trigger_node_output(key, value):
            payloads.extend(_collect_contact_name_payloads(value))

    deduped_payloads: List[Dict[str, Any]] = []
    seen_payloads = set()
    for payload in payloads:
        payload_id = id(payload)
        if payload_id in seen_payloads:
            continue
        seen_payloads.add(payload_id)
        deduped_payloads.append(payload)

    return deduped_payloads


def _copy_message_name_payload(
    payload: Any,
    first_name: str,
    full_name: str,
    max_depth: int = 3,
) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None

    copied_payload = dict(payload)
    copied_payload["name"] = first_name
    copied_payload["nome"] = first_name
    copied_payload["first_name"] = first_name
    copied_payload["primeiro_nome"] = first_name
    copied_payload["full_name"] = full_name
    copied_payload["nome_completo"] = full_name

    if max_depth <= 0:
        return copied_payload

    for key in CONTACT_NAME_CONTAINER_KEYS:
        nested_payload = copied_payload.get(key)
        if isinstance(nested_payload, dict):
            copied_payload[key] = _copy_message_name_payload(
                nested_payload,
                first_name,
                full_name,
                max_depth - 1,
            )

    return copied_payload


def _has_name_like_value(variables: Dict[str, Any]) -> bool:
    for payload in _contact_name_payloads(variables):
        for key in (*FIRST_NAME_KEYS, *FULL_NAME_KEYS):
            raw_value = payload.get(key)
            if raw_value is not None and str(raw_value).strip():
                return True
    return False


def _resolve_contact_full_name(variables: Dict[str, Any]) -> str:
    for payload in _contact_name_payloads(variables):
        for key in FULL_NAME_KEYS:
            contact_name = _clean_contact_name(payload.get(key))
            if contact_name:
                return contact_name
    return ""


def _resolve_contact_first_name(variables: Dict[str, Any]) -> str:
    for payload in _contact_name_payloads(variables):
        for key in FIRST_NAME_KEYS:
            first_name = _first_name_from_value(payload.get(key))
            if first_name:
                return first_name

    return _first_name_from_value(_resolve_contact_full_name(variables))


def _agent_response_delay_seconds(variables: Dict[str, Any]) -> int:
    for key in ("agent_workforce", "agentWorkforce"):
        payload = variables.get(key)
        if not isinstance(payload, dict):
            continue
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        value = metadata.get("response_delay_seconds", payload.get("response_delay_seconds"))
        try:
            parsed = int(round(float(value or 0)))
        except (TypeError, ValueError):
            parsed = 0
        return max(0, min(MAX_AGENT_RESPONSE_DELAY_SECONDS, parsed))
    return 0


def _agent_response_audio_payload(variables: Dict[str, Any]) -> Optional[bytes]:
    payload = _agent_response_audio_context(variables)
    if not payload:
        return None

    audio = payload.get("audio")
    if isinstance(audio, bytes):
        return audio
    if isinstance(audio, bytearray):
        return bytes(audio)
    if isinstance(audio, memoryview):
        return audio.tobytes()
    return None


def _agent_response_audio_context(variables: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for key in ("agent_workforce", "agentWorkforce"):
        payload = variables.get(key)
        if not isinstance(payload, dict) or not payload.get("should_send_audio"):
            continue
        return payload
    return None


def _agent_response_audio_text_intro(variables: Dict[str, Any]) -> Optional[str]:
    payload = _agent_response_audio_context(variables)
    if not payload:
        return None
    intro = _normalize_message_text(str(payload.get("audio_text_intro") or ""))
    return intro or None


def _agent_response_audio_text(variables: Dict[str, Any]) -> Optional[str]:
    payload = _agent_response_audio_context(variables)
    if not payload:
        return None
    text = _normalize_message_text(str(payload.get("audio_text") or ""))
    return text or None


def _agent_response_audio_delivery_mode(variables: Dict[str, Any]) -> Optional[str]:
    payload = _agent_response_audio_context(variables)
    if not payload:
        return None
    mode = str(payload.get("audio_delivery_mode") or "").strip()
    return mode or None


def _clear_agent_response_audio_payload(variables: Dict[str, Any]) -> None:
    for key in ("agent_workforce", "agentWorkforce"):
        payload = variables.get(key)
        if isinstance(payload, dict):
            payload["audio"] = None
            payload["audio_consumed"] = True


def split_humanized_whatsapp_response(
    text: str,
    *,
    max_messages: int = 3,
    short_threshold: int = 180,
) -> List[str]:
    """Split an agent response into a few WhatsApp-sized messages."""

    normalized = _normalize_message_text(text)
    if not normalized:
        return []

    max_messages = max(1, min(max_messages, 3))
    if len(normalized) <= short_threshold or max_messages == 1:
        return [normalized]

    units = _split_message_units(normalized)
    if len(units) <= 1:
        return _split_words_evenly(normalized, _target_message_count(normalized, units, short_threshold, max_messages))

    target_count = _target_message_count(normalized, units, short_threshold, max_messages)
    return _pack_message_units(units, target_count)


def _normalize_message_text(text: str) -> str:
    text = str(text or "").strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text)


def _split_message_units(text: str) -> List[str]:
    units: List[str] = []
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]

    for paragraph in paragraphs:
        lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
        has_list = any(re.match(r"^([-*•]|\d+[.)])\s+", line) for line in lines)
        if has_list:
            units.append("\n".join(lines))
            continue

        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+(?=\S)", paragraph)
            if sentence.strip()
        ]
        units.extend(sentences or [paragraph])

    return units


def _target_message_count(
    text: str,
    units: List[str],
    short_threshold: int,
    max_messages: int,
) -> int:
    if len(text) <= short_threshold:
        return 1

    target_count = 2 if len(text) <= 360 else 3
    if len(units) >= 4:
        target_count = max(target_count, 3)
    if units and units[-1].endswith("?") and len(units) >= 3 and len(text) > 240:
        target_count = max(target_count, 3)

    return min(max_messages, target_count, len(units) if units else max_messages)


def _pack_message_units(units: List[str], target_count: int) -> List[str]:
    if target_count <= 1 or len(units) <= 1:
        return [" ".join(units).strip()]

    tail: List[str] = []
    head = units
    if units[-1].endswith("?") and target_count >= 2:
        head = units[:-1]
        tail = [units[-1]]
        target_count -= 1

    chunks = _pack_units_evenly(head, target_count) if head else []
    chunks.extend(tail)
    return [chunk for chunk in chunks if chunk]


def _pack_units_evenly(units: List[str], target_count: int) -> List[str]:
    if not units:
        return []
    if target_count <= 1 or len(units) <= 1:
        return [_join_units(units)]

    total_length = sum(len(unit) for unit in units) + max(len(units) - 1, 0)
    target_length = max(1, ceil(total_length / target_count))
    chunks: List[str] = []
    current: List[str] = []

    for index, unit in enumerate(units):
        remaining_units = len(units) - index
        remaining_chunks = target_count - len(chunks)
        current_length = len(_join_units(current)) if current else 0
        next_length = current_length + (1 if current else 0) + len(unit)

        if (
            current
            and next_length > target_length
            and remaining_chunks > 1
            and remaining_units >= remaining_chunks
        ):
            chunks.append(_join_units(current))
            current = [unit]
        else:
            current.append(unit)

    if current:
        chunks.append(_join_units(current))

    while len(chunks) > target_count:
        extra = chunks.pop()
        chunks[-1] = _join_units([chunks[-1], extra])

    return chunks


def _split_words_evenly(text: str, target_count: int) -> List[str]:
    words = text.split()
    if not words or target_count <= 1:
        return [text]

    words_per_chunk = max(1, ceil(len(words) / target_count))
    chunks = [
        " ".join(words[index:index + words_per_chunk]).strip()
        for index in range(0, len(words), words_per_chunk)
    ]

    while len(chunks) > target_count:
        extra = chunks.pop()
        chunks[-1] = _join_units([chunks[-1], extra])

    return [chunk for chunk in chunks if chunk]


def _join_units(units: List[str]) -> str:
    return " ".join(unit.strip() for unit in units if unit and unit.strip()).strip()


class BaseNodeHandler(ABC):
    """Base class for all node handlers"""

    @abstractmethod
    def execute(
        self,
        db: Session,
        node_data: Dict[str, Any],
        variables: Dict[str, Any],
        company_id: int,
        flow_id: int
    ) -> Dict[str, Any]:
        """
        Execute the node action.

        Args:
            db: Database session
            node_data: The node's data configuration
            variables: Current flow variables
            company_id: ID of the company
            flow_id: ID of the flow

        Returns:
            Dict with:
            - success: bool
            - (optional) result data
            - (optional) stop_flow: bool - if True, stops flow execution
            - (optional) delay_execution: bool - if True, node handles its own continuation
        """
        pass

    def resolve_variables(self, text: str, variables: Dict[str, Any]) -> str:
        """Resolve variable placeholders in text"""
        if not text:
            return text

        def replace_var(match):
            var_path = match.group(1).strip()
            if var_path == "event.type":
                event_data = variables.get("event_data")
                if isinstance(event_data, dict) and event_data.get("type") is not None:
                    return str(event_data.get("type"))
                event_value = variables.get("event")
                if isinstance(event_value, dict) and event_value.get("type") is not None:
                    return str(event_value.get("type"))
                if event_value is not None:
                    return str(event_value)

            parts = var_path.split('.')
            value = variables

            for part in parts:
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    return match.group(0)

            return str(value) if value is not None else ''

        pattern = r'\{\{([^}]+)\}\}'
        return re.sub(pattern, replace_var, text)

    def _parse_positive_int(self, value: Any) -> Optional[int]:
        try:
            if value is None or str(value).strip() == "":
                return None
            parsed = int(value)
            return parsed if parsed > 0 else None
        except (TypeError, ValueError):
            return None

    def _phone_candidates(self, value: Any) -> List[str]:
        clean_phone = ''.join(filter(str.isdigit, str(value or "")))
        if not clean_phone:
            return []

        candidates = {clean_phone}
        if len(clean_phone) in (10, 11):
            candidates.add(f"55{clean_phone}")
        if clean_phone.startswith("55") and len(clean_phone) in (12, 13):
            candidates.add(clean_phone[2:])

        return list(candidates)

    def _resolve_node_config_value(
        self,
        node_data: Dict[str, Any],
        variables: Dict[str, Any],
        *keys: str,
    ) -> str:
        for key in keys:
            raw_value = node_data.get(key)
            if raw_value is None:
                continue

            raw_text = str(raw_value).strip()
            if not raw_text:
                continue

            resolved = self.resolve_variables(raw_text, variables).strip()
            if "{{" in resolved and "}}" in resolved:
                continue
            if resolved:
                return resolved

        return ""

    def _resolve_flow_contact(
        self,
        db: Session,
        variables: Dict[str, Any],
        company_id: int,
        explicit_phone: Optional[Any] = None,
    ) -> Optional[Any]:
        """Resolve the contact currently moving through the flow."""
        from backend.models import Contact, Lead

        trigger = variables.get("trigger", {}) if isinstance(variables.get("trigger"), dict) else {}
        flow_enrollment = (
            variables.get("flow_enrollment", {})
            if isinstance(variables.get("flow_enrollment"), dict)
            else {}
        )
        trigger_contact = trigger.get("contact", {}) if isinstance(trigger.get("contact"), dict) else {}
        trigger_body = trigger.get("body", {}) if isinstance(trigger.get("body"), dict) else {}

        contact_id_candidates = [
            variables.get("contact_id"),
            variables.get("contactId"),
            trigger.get("contact_id"),
            trigger.get("contactId"),
            trigger_contact.get("id"),
            trigger_body.get("contact_id"),
            trigger_body.get("contactId"),
        ]

        for raw_contact_id in contact_id_candidates:
            contact_id = self._parse_positive_int(raw_contact_id)
            if not contact_id:
                continue

            contact = db.query(Contact).filter(
                Contact.id == contact_id,
                Contact.company_id == company_id,
            ).first()
            if contact:
                return contact

        phone_values: List[Any] = [
            explicit_phone,
            variables.get("phone"),
            variables.get("whatsapp"),
            trigger.get("phone"),
            trigger.get("whatsapp"),
            trigger_contact.get("phone"),
            trigger_body.get("phone"),
            trigger_body.get("whatsapp"),
        ]

        lead_id = self._parse_positive_int(
            variables.get("lead_id")
            or trigger.get("lead_id")
            or flow_enrollment.get("lead_id")
        )
        if lead_id:
            lead = db.query(Lead).filter(
                Lead.id == lead_id,
                Lead.company_id == company_id,
            ).first()
            if lead and lead.phone:
                phone_values.append(lead.phone)

        phone_candidates: List[str] = []
        for raw_phone in phone_values:
            phone_candidates.extend(self._phone_candidates(raw_phone))

        unique_phone_candidates = list(dict.fromkeys(phone_candidates))
        if not unique_phone_candidates:
            return None

        return db.query(Contact).filter(
            Contact.company_id == company_id,
            Contact.phone.in_(unique_phone_candidates),
        ).order_by(Contact.id.desc()).first()

    def _resolve_flow_lead(
        self,
        db: Session,
        variables: Dict[str, Any],
        company_id: int,
        explicit_lead_id: Optional[Any] = None,
        explicit_phone: Optional[Any] = None,
    ) -> Optional[Any]:
        """Resolve the CRM lead currently moving through the flow."""
        from backend.models import Lead

        trigger = variables.get("trigger", {}) if isinstance(variables.get("trigger"), dict) else {}
        flow_enrollment = (
            variables.get("flow_enrollment", {})
            if isinstance(variables.get("flow_enrollment"), dict)
            else {}
        )
        crm_stage = trigger.get("crm_stage", {}) if isinstance(trigger.get("crm_stage"), dict) else {}
        trigger_body = trigger.get("body", {}) if isinstance(trigger.get("body"), dict) else {}

        lead_id_candidates = [
            explicit_lead_id,
            variables.get("lead_id"),
            variables.get("leadId"),
            variables.get("body.lead_id"),
            trigger.get("lead_id"),
            trigger.get("leadId"),
            trigger_body.get("lead_id"),
            trigger_body.get("leadId"),
            crm_stage.get("lead_id"),
            flow_enrollment.get("lead_id"),
        ]

        for value in variables.values():
            if not isinstance(value, dict):
                continue
            lead_id_candidates.extend([
                value.get("lead_id"),
                value.get("leadId"),
            ])

        for raw_lead_id in lead_id_candidates:
            lead_id = self._parse_positive_int(raw_lead_id)
            if not lead_id:
                continue

            lead = db.query(Lead).filter(
                Lead.id == lead_id,
                Lead.company_id == company_id,
            ).first()
            if lead:
                return lead

        phone_values: List[Any] = [
            explicit_phone,
            variables.get("phone"),
            variables.get("whatsapp"),
            trigger.get("phone"),
            trigger.get("whatsapp"),
            trigger_body.get("phone"),
            trigger_body.get("whatsapp"),
        ]
        contact = self._resolve_flow_contact(
            db,
            variables,
            company_id,
            explicit_phone=explicit_phone,
        )
        if contact and contact.phone:
            phone_values.append(contact.phone)

        phone_candidates: List[str] = []
        for raw_phone in phone_values:
            phone_candidates.extend(self._phone_candidates(raw_phone))

        unique_phone_candidates = list(dict.fromkeys(phone_candidates))
        if not unique_phone_candidates:
            return None

        return db.query(Lead).filter(
            Lead.company_id == company_id,
            Lead.phone.in_(unique_phone_candidates),
        ).order_by(Lead.id.desc()).first()

    def _resolve_client_id(self, db: Session, company_id: int) -> Optional[int]:
        from backend.models import Client, ClientCompany

        association = db.query(ClientCompany).filter(
            ClientCompany.company_id == company_id,
        ).order_by(ClientCompany.id.asc()).first()
        if association:
            return int(association.client_id)

        client = db.query(Client).filter(Client.company_id == company_id).first()
        return int(client.id) if client else None

    def _resolve_phone(
        self,
        variables: Dict[str, Any],
        *,
        lead: Optional[Any],
        contact: Optional[Any],
        explicit_phone: Optional[Any] = None,
    ) -> str:
        trigger = variables.get("trigger", {}) if isinstance(variables.get("trigger"), dict) else {}
        trigger_body = trigger.get("body", {}) if isinstance(trigger.get("body"), dict) else {}
        phone = (
            explicit_phone
            or variables.get("phone")
            or variables.get("whatsapp")
            or trigger.get("phone")
            or trigger.get("whatsapp")
            or trigger_body.get("phone")
            or trigger_body.get("whatsapp")
            or getattr(contact, "phone", None)
            or getattr(lead, "phone", None)
            or ""
        )
        digits = "".join(filter(str.isdigit, str(phone or "")))
        if len(digits) in (10, 11):
            return f"55{digits}"
        return digits

    def _resolve_name(
        self,
        variables: Dict[str, Any],
        *,
        lead: Optional[Any],
        contact: Optional[Any],
    ) -> str:
        trigger = variables.get("trigger", {}) if isinstance(variables.get("trigger"), dict) else {}
        trigger_body = trigger.get("body", {}) if isinstance(trigger.get("body"), dict) else {}
        return str(
            variables.get("name")
            or trigger.get("name")
            or trigger_body.get("name")
            or getattr(contact, "name", None)
            or getattr(lead, "name", None)
            or ""
        ).strip()


class WebhookTriggerHandler(BaseNodeHandler):
    """Handler for webhook trigger nodes - basically a no-op since trigger already happened"""

    def execute(
        self,
        db: Session,
        node_data: Dict[str, Any],
        variables: Dict[str, Any],
        company_id: int,
        flow_id: int
    ) -> Dict[str, Any]:
        logger.debug("[WebhookTriggerHandler] Trigger node executed (pass-through)")

        # Pass the full trigger data to be accessible via node output
        trigger_data = variables.get('trigger', {})

        return {
            "success": True,
            "type": "trigger",
            "body": trigger_data
        }


class WhatsAppTriggerHandler(BaseNodeHandler):
    """Handler for WhatsApp message trigger nodes"""

    def execute(
        self,
        db: Session,
        node_data: Dict[str, Any],
        variables: Dict[str, Any],
        company_id: int,
        flow_id: int
    ) -> Dict[str, Any]:
        logger.debug("[WhatsAppTriggerHandler] WhatsApp trigger node executed (pass-through)")
        return {"success": True, "type": "whatsapp_trigger"}


class AppointmentTriggerHandler(BaseNodeHandler):
    """Handler for appointment business triggers."""

    def execute(
        self,
        db: Session,
        node_data: Dict[str, Any],
        variables: Dict[str, Any],
        company_id: int,
        flow_id: int
    ) -> Dict[str, Any]:
        trigger_data = variables.get("trigger", {}) or {}
        return {
            "success": True,
            "type": "appointment_trigger",
            "appointment": trigger_data.get("appointment", {}),
            "event": trigger_data.get("event"),
        }


class CrmStageTriggerHandler(BaseNodeHandler):
    """Handler for CRM stage business triggers."""

    def execute(
        self,
        db: Session,
        node_data: Dict[str, Any],
        variables: Dict[str, Any],
        company_id: int,
        flow_id: int
    ) -> Dict[str, Any]:
        trigger_data = variables.get("trigger", {}) or {}
        return {
            "success": True,
            "type": "crm_trigger",
            "crm_stage": trigger_data.get("crm_stage", {}),
            "crm": trigger_data.get("crm", {}),
            "lead": trigger_data.get("lead", {}),
            "event": trigger_data.get("event"),
        }


class SendMessageHandler(BaseNodeHandler):
    """Handler for sending WhatsApp messages"""

    def _message_delivery_variables(self, variables: Dict[str, Any]) -> Dict[str, Any]:
        full_name = _resolve_contact_full_name(variables)
        first_name = _resolve_contact_first_name(variables)
        full_name = full_name or first_name

        if not (full_name or first_name or _has_name_like_value(variables)):
            return variables

        delivery_variables: Dict[str, Any] = dict(variables)
        delivery_variables["name"] = first_name
        delivery_variables["nome"] = first_name
        delivery_variables["first_name"] = first_name
        delivery_variables["primeiro_nome"] = first_name
        delivery_variables["full_name"] = full_name
        delivery_variables["nome_completo"] = full_name

        for key in ROOT_CONTACT_PAYLOAD_KEYS:
            copied_payload = _copy_message_name_payload(variables.get(key), first_name, full_name)
            if copied_payload is not None:
                delivery_variables[key] = copied_payload

        for key, value in variables.items():
            if _is_trigger_node_output(key, value):
                copied_payload = _copy_message_name_payload(value, first_name, full_name)
                if copied_payload is not None:
                    delivery_variables[key] = copied_payload

        return delivery_variables

    def execute(
        self,
        db: Session,
        node_data: Dict[str, Any],
        variables: Dict[str, Any],
        company_id: int,
        flow_id: int
    ) -> Dict[str, Any]:
        from backend.integrations.whatsapp_provider import send_text as provider_send_text

        # Get message configuration
        messages = node_data.get('messages', [])

        # Get phone from variables (support both "phone" and "whatsapp" payload styles)
        trigger = variables.get('trigger', {}) or {}
        phone = (
            variables.get('phone')
            or variables.get('whatsapp')
            or trigger.get('phone')
            or trigger.get('whatsapp')
        )

        # Normalize phone number (ensure BR country code)
        if phone:
            # Remove non-digits
            clean_phone = ''.join(filter(str.isdigit, str(phone)))

            # If valid BR length (10 or 11 digits), prepend 55
            # e.g. 21999999999 -> 5500000000002
            if len(clean_phone) in [10, 11]:
                phone = '55' + clean_phone
            else:
                phone = clean_phone

        if not phone:
            logger.error("[SendMessageHandler] No phone number available in variables")
            return {
                "success": False,
                "error": "No phone number available"
            }

        message_variables = self._message_delivery_variables(variables)
        results = []

        for msg in messages:
            msg_type = msg.get('type', 'text')
            content = msg.get('content', '')
            should_split_agent_response = msg_type == 'text' and _is_agent_response_template(content)
            agent_response_delay_seconds = (
                _agent_response_delay_seconds(variables)
                if should_split_agent_response
                else 0
            )

            # Resolve variables in content
            resolved_content = self.resolve_variables(content, message_variables)

            logger.info(f"[SendMessageHandler] Sending {msg_type} to {phone}: {resolved_content[:50]}...")

            try:
                if msg_type == 'text':
                    if should_split_agent_response and _is_agent_response_template(resolved_content):
                        logger.error(
                            "[SendMessageHandler] Agent response template was not resolved; skipping send: %s",
                            content,
                        )
                        results.append({
                            "type": "text",
                            "success": False,
                            "error": "Agent response variable was not resolved",
                            "unresolved_template": content,
                        })
                        continue

                    audio_fallback_error = None
                    text_delivery_content = resolved_content
                    audio_intro_already_sent = False
                    if should_split_agent_response:
                        audio_bytes = _agent_response_audio_payload(variables)
                        if audio_bytes:
                            from backend.integrations.whatsapp_provider import send_audio

                            audio_intro = _agent_response_audio_text_intro(variables)
                            audio_text = _agent_response_audio_text(variables)
                            audio_delivery_mode = _agent_response_audio_delivery_mode(variables)
                            try:
                                if audio_intro:
                                    intro_result = provider_send_text(
                                        company_id=company_id,
                                        phone=phone,
                                        message=audio_intro,
                                        db=db,
                                        human_mode=True,
                                        response_delay_seconds=agent_response_delay_seconds,
                                    )
                                    audio_intro_already_sent = True
                                    results.append({
                                        "type": "text",
                                        "success": True,
                                        "result": intro_result,
                                        "part_index": 1,
                                        "parts_total": 2,
                                        "response_delay_seconds": agent_response_delay_seconds,
                                        "split_from_agent_response": True,
                                        "audio_intro": True,
                                    })

                                audio_result = send_audio(
                                    company_id=company_id,
                                    phone=phone,
                                    audio_bytes=audio_bytes,
                                    db=db
                                )
                                _clear_agent_response_audio_payload(variables)
                                results.append({
                                    "type": "audio",
                                    "success": True,
                                    "result": audio_result,
                                    "sent_from_agent_response": True,
                                    "audio_delivery_mode": audio_delivery_mode,
                                    "text_intro_sent": audio_intro_already_sent,
                                    "part_index": 2 if audio_intro_already_sent else 1,
                                    "parts_total": 2 if audio_intro_already_sent else 1,
                                })
                                continue
                            except Exception as audio_exc:
                                audio_fallback_error = str(audio_exc)
                                if audio_intro_already_sent and audio_text:
                                    text_delivery_content = audio_text
                                _clear_agent_response_audio_payload(variables)
                                logger.exception(
                                    "[SendMessageHandler] Error sending agent audio delivery; falling back to text: %s",
                                    audio_exc,
                                )

                    message_parts = (
                        split_humanized_whatsapp_response(text_delivery_content)
                        if should_split_agent_response
                        else [_normalize_message_text(text_delivery_content)]
                    )

                    for part_index, message_part in enumerate(message_parts, start=1):
                        if not message_part:
                            continue

                        response_delay_seconds = (
                            agent_response_delay_seconds
                            if part_index == 1 and not audio_intro_already_sent
                            else 0
                        )
                        displayed_part_index = part_index + (1 if audio_intro_already_sent else 0)
                        displayed_parts_total = len(message_parts) + (1 if audio_intro_already_sent else 0)
                        result = provider_send_text(
                            company_id=company_id,
                            phone=phone,
                            message=message_part,
                            db=db,
                            human_mode=True,  # Mark as sent by flow, not AI
                            response_delay_seconds=response_delay_seconds
                        )
                        text_result = {
                            "type": "text",
                            "success": True,
                            "result": result,
                            "part_index": displayed_part_index,
                            "parts_total": displayed_parts_total,
                            "response_delay_seconds": response_delay_seconds,
                            "split_from_agent_response": should_split_agent_response,
                        }
                        if audio_fallback_error:
                            text_result["audio_fallback_error"] = audio_fallback_error
                        results.append(text_result)

                elif msg_type == 'image':
                    from backend.integrations.whatsapp_provider import send_image
                    image_url = msg.get('url', '')
                    caption = msg.get('caption', '')
                    resolved_caption = self.resolve_variables(caption, message_variables)

                    result = send_image(
                        company_id=company_id,
                        phone=phone,
                        image_url=image_url,
                        caption=resolved_caption,
                        db=db
                    )
                    results.append({
                        "type": "image",
                        "success": True,
                        "result": result
                    })

                elif msg_type == 'audio':
                    from backend.integrations.whatsapp_provider import send_audio
                    audio_url = msg.get('url', '')

                    result = send_audio(
                        company_id=company_id,
                        phone=phone,
                        audio_url=audio_url,
                        db=db
                    )
                    results.append({
                        "type": "audio",
                        "success": True,
                        "result": result
                    })

                elif msg_type == 'video':
                    from backend.integrations.whatsapp_provider import send_video
                    video_url = msg.get('url', '')
                    caption = msg.get('caption', '')
                    resolved_caption = self.resolve_variables(caption, message_variables)

                    result = send_video(
                        company_id=company_id,
                        phone=phone,
                        video_url=video_url,
                        caption=resolved_caption,
                        db=db
                    )
                    results.append({
                        "type": "video",
                        "success": True,
                        "result": result
                    })
                else:
                    logger.warning(f"[SendMessageHandler] Unknown message type: {msg_type}")

            except Exception as e:
                logger.exception(f"[SendMessageHandler] Error sending {msg_type}: {e}")
                results.append({
                    "type": msg_type,
                    "success": False,
                    "error": str(e)
                })

        all_success = all(r.get('success', False) for r in results)

        return {
            "success": all_success,
            "messages_sent": len([r for r in results if r.get('success')]),
            "results": results
        }


class SendTelegramMessageHandler(BaseNodeHandler):
    """Handler for sending Telegram messages"""

    _ALLOWED_PARSE_MODES = {"HTML", "Markdown", "MarkdownV2"}

    def execute(
        self,
        db: Session,
        node_data: Dict[str, Any],
        variables: Dict[str, Any],
        company_id: int,
        flow_id: int
    ) -> Dict[str, Any]:
        # Keep signature parity with other handlers even if `flow_id` is unused.
        _ = flow_id

        raw_message = str(node_data.get("message") or node_data.get("content") or "").strip()
        if not raw_message:
            return {"success": False, "error": "Telegram message is required"}

        resolved_message = self.resolve_variables(raw_message, variables)
        if not resolved_message.strip():
            return {"success": False, "error": "Telegram message resolved to empty content"}

        raw_chat_id = str(node_data.get("chatId") or node_data.get("chat_id") or "").strip()
        resolved_chat_id = self.resolve_variables(raw_chat_id, variables).strip() if raw_chat_id else ""

        integration = get_company_telegram_integration(db, int(company_id))
        if not integration:
            return {
                "success": False,
                "error": "Telegram nao configurado para esta empresa. Configure em Conexoes > Integracoes."
            }

        chat_id = resolved_chat_id or (integration.default_chat_id or "").strip()
        if not chat_id:
            return {
                "success": False,
                "error": "Telegram chat_id nao configurado no node nem na integracao da empresa"
            }

        try:
            bot_token = decrypt_bot_token(integration.bot_token_encrypted)
        except TelegramConfigurationError as exc:
            return {
                "success": False,
                "error": str(exc)
            }

        parse_mode_raw = str(node_data.get("parseMode") or node_data.get("parse_mode") or "HTML").strip()
        if not parse_mode_raw or parse_mode_raw.lower() == "none":
            parse_mode = None
        elif parse_mode_raw in self._ALLOWED_PARSE_MODES:
            parse_mode = parse_mode_raw
        else:
            logger.warning(
                "[SendTelegramMessageHandler] Invalid parse mode '%s'; sending without parse_mode",
                parse_mode_raw
            )
            parse_mode = None

        disable_preview = bool(
            node_data.get("disableWebPagePreview")
            if node_data.get("disableWebPagePreview") is not None
            else node_data.get("disable_web_page_preview", True)
        )

        try:
            result = send_telegram_text(
                bot_token=bot_token,
                chat_id=str(chat_id),
                message=resolved_message,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_preview,
            )
            logger.info(
                "[SendTelegramMessageHandler] Telegram sent chat_id=%s message_id=%s",
                result.get("chat", {}).get("id", chat_id),
                result.get("message_id"),
            )
            return {
                "success": True,
                "chat_id": str(result.get("chat", {}).get("id", chat_id)),
                "message_id": result.get("message_id"),
                "text": resolved_message,
            }
        except Exception as e:
            logger.exception("[SendTelegramMessageHandler] Error sending Telegram message: %s", e)
            return {"success": False, "error": str(e)}


class CreateLeadHandler(BaseNodeHandler):
    """Handler for creating/updating leads in CRM"""

    def _canonicalize_phone_for_waha(self, db: Session, company_id: int, phone: str) -> str:
        """
        Resolve canonical phone using WAHA check_number_status when WAHA is enabled.

        WAHA may return a corrected chatId for BR numbers (old/new 8/9-digit formats).
        We persist that canonical phone so CRM/contact records match the real WhatsApp chat.
        """
        clean_phone = ''.join(filter(str.isdigit, str(phone or "")))
        if not clean_phone or not clean_phone.startswith("55"):
            return clean_phone

        try:
            company_row = db.execute(
                text(
                    """
                    SELECT waha_enabled, waha_session_name
                    FROM companies
                    WHERE id = :company_id
                    LIMIT 1
                    """
                ),
                {"company_id": company_id},
            ).fetchone()

            if not company_row or not company_row.waha_enabled or not company_row.waha_session_name:
                return clean_phone

            from backend.config import WAHA_API_KEY, WAHA_BASE_URL
            if not WAHA_API_KEY:
                return clean_phone

            from backend.integrations.waha_sdk import get_client as get_waha_client

            client = get_waha_client(
                base_url=WAHA_BASE_URL,
                api_key=WAHA_API_KEY,
            )
            status = client.check_number_status(
                session=company_row.waha_session_name,
                phone=clean_phone,
            )

            chat_id = str((status or {}).get("chatId") or "").strip()
            if not chat_id:
                return clean_phone

            canonical_phone = ''.join(filter(str.isdigit, chat_id.split("@")[0]))
            if not canonical_phone:
                return clean_phone

            if canonical_phone != clean_phone:
                logger.info(
                    "[CreateLeadHandler] WAHA canonicalized phone %s -> %s (chatId=%s)",
                    clean_phone,
                    canonical_phone,
                    chat_id,
                )

            return canonical_phone

        except Exception as e:
            logger.warning(
                "[CreateLeadHandler] WAHA canonicalization failed for %s: %s",
                clean_phone,
                e,
            )
            return clean_phone

    def execute(
        self,
        db: Session,
        node_data: Dict[str, Any],
        variables: Dict[str, Any],
        company_id: int,
        flow_id: int
    ) -> Dict[str, Any]:

        # Get field mappings from node configuration
        field_mappings = node_data.get('fieldMappings', {})

        # Build lead data from mappings
        lead_data = {}

        for field_name, var_path in field_mappings.items():
            if var_path:
                # Resolve the variable path
                value = self._get_nested_value(variables, var_path)
                if value is not None:
                    lead_data[field_name] = value

        # --- NEW: Support the customValues format and templates ---
        # Some flows use a direct customValues dict with mustache templates
        node_custom_values = node_data.get('customValues', {})
        for field_name, value_template in node_custom_values.items():
            if isinstance(value_template, str) and '{{' in value_template:
                resolved_val = self.resolve_variables(value_template, variables)
                if resolved_val and resolved_val != value_template:
                    lead_data[field_name] = resolved_val
            elif value_template is not None:
                lead_data[field_name] = value_template

        # Also resolve top-level name/phone fields if they are templates
        for field in ['name', 'phone', 'email']:
            field_val = node_data.get(field)
            if isinstance(field_val, str) and '{{' in field_val:
                resolved_val = self.resolve_variables(field_val, variables)
                if resolved_val and resolved_val != field_val:
                    lead_data[field] = resolved_val

        # Ensure we have required fields
        trigger = variables.get('trigger', {}) or {}
        phone = (
            lead_data.get('phone')
            or variables.get('phone')
            or variables.get('whatsapp')
            or trigger.get('phone')
            or trigger.get('whatsapp')
        )
        name = lead_data.get('name') or variables.get('name') or variables.get('trigger', {}).get('name', '')
        email = lead_data.get('email') or variables.get('email') or variables.get('trigger', {}).get('email', '')

        if not phone:
            logger.error("[CreateLeadHandler] No phone number for lead creation")
            return {
                "success": False,
                "error": "Phone number is required for lead creation"
            }

        # Normalize phone number (ensure BR country code)
        # e.g. 21999999999 -> 5500000000002
        clean_phone = ''.join(filter(str.isdigit, str(phone)))
        if len(clean_phone) in [10, 11]:
            phone = '55' + clean_phone
        else:
            phone = clean_phone

        # Canonicalize with WAHA when available to avoid phone/chatId mismatches.
        phone = self._canonicalize_phone_for_waha(db, company_id, phone)
        lead_data['phone'] = phone

        # Persist normalized phone in flow variables for delayed/resumed nodes.
        variables['phone'] = phone
        variables['whatsapp'] = phone

        logger.info(f"[CreateLeadHandler] Creating/updating lead: phone={phone}, name={name}")

        try:
            configured_pipeline_id = self._parse_positive_int(
                node_data.get('pipelineId') or node_data.get('pipeline_id')
            )
            configured_stage_id = self._parse_positive_int(
                node_data.get('stageId') or node_data.get('stage_id')
            )

            if configured_stage_id:
                stage_row = db.execute(text("""
                    SELECT ps.id, ps.pipeline_id
                    FROM pipeline_stages ps
                    JOIN pipelines p ON p.id = ps.pipeline_id
                    WHERE ps.id = :stage_id
                      AND p.company_id = :company_id
                    LIMIT 1
                """), {
                    "stage_id": configured_stage_id,
                    "company_id": company_id,
                }).fetchone()

                if stage_row:
                    configured_stage_id = int(stage_row.id)
                    configured_pipeline_id = int(stage_row.pipeline_id)
                else:
                    logger.warning(
                        "[CreateLeadHandler] Ignoring invalid stage_id=%s for company_id=%s",
                        configured_stage_id,
                        company_id,
                    )
                    configured_stage_id = None

            if configured_pipeline_id and not configured_stage_id:
                pipeline_row = db.execute(text("""
                    SELECT id
                    FROM pipelines
                    WHERE id = :pipeline_id
                      AND company_id = :company_id
                    LIMIT 1
                """), {
                    "pipeline_id": configured_pipeline_id,
                    "company_id": company_id,
                }).fetchone()
                if not pipeline_row:
                    logger.warning(
                        "[CreateLeadHandler] Ignoring invalid pipeline_id=%s for company_id=%s",
                        configured_pipeline_id,
                        company_id,
                    )
                    configured_pipeline_id = None
                else:
                    from backend.services.pipeline_service import PipelineService

                    fallback_stage = PipelineService.get_initial_stage_for_pipeline(
                        int(configured_pipeline_id),
                        db,
                    )
                    if fallback_stage:
                        configured_stage_id = int(fallback_stage.id)
                        logger.info(
                            "[CreateLeadHandler] Using initial stage fallback stage_id=%s for pipeline_id=%s",
                            configured_stage_id,
                            configured_pipeline_id,
                        )

            # Get client_id for the company first
            company_data = db.execute(text("""
                SELECT cc.client_id FROM client_companies cc
                WHERE cc.company_id = :company_id
                LIMIT 1
            """), {"company_id": company_id}).fetchone()

            client_id = company_data.client_id if company_data else None

            if not client_id:
                logger.error(f"[CreateLeadHandler] No client_id found for company {company_id}")
                return {
                    "success": False,
                    "error": "No client association found for company"
                }

            # Ensures Contact Exists before creating Lead
            contact_name = name or phone
            try:
                db.execute(text("""
                    INSERT INTO contacts (client_id, company_id, phone, name, last_message_at, human_mode, unread_count, archived)
                    VALUES (:client_id, :company_id, :phone, :name, NOW(), false, 0, false)
                    ON CONFLICT (client_id, company_id, phone) DO UPDATE
                    SET name = COALESCE(NULLIF(EXCLUDED.name, ''), contacts.name),
                        last_message_at = NOW()
                """), {
                    "client_id": client_id,
                    "company_id": company_id,
                    "phone": phone,
                    "name": contact_name
                })
            except Exception as e_contact:
                logger.warning(f"[CreateLeadHandler] Warning creating contact: {e_contact}")

            # Check if lead already exists
            existing_lead = db.execute(text("""
                SELECT id, name FROM leads
                WHERE phone = :phone AND company_id = :company_id
                LIMIT 1
            """), {"phone": phone, "company_id": company_id}).fetchone()

            if existing_lead:
                # Update existing lead
                db.execute(text("""
                    UPDATE leads SET
                        name = COALESCE(NULLIF(:name, ''), name)
                    WHERE id = :lead_id
                """), {
                    "name": name,
                    "lead_id": existing_lead.id
                })
                db.commit()

                # --- NEW: Save custom fields/UTMs during update ---
                try:
                    from backend.services.lead_custom_fields_service import LeadCustomFieldsService, LeadCustomValueCreate

                    standard_fields = ['name', 'phone', 'email']
                    custom_data = {k: v for k, v in lead_data.items() if k not in standard_fields}

                    if custom_data:
                        logger.info(f"[CreateLeadHandler] updating custom fields for existing lead {existing_lead.id}: {list(custom_data.keys())}")

                        company_fields = LeadCustomFieldsService.get_company_custom_fields(company_id, True, db)
                        field_key_to_id = {f.field_key: f.id for f in company_fields}

                        custom_values_to_create = []
                        for key, val in custom_data.items():
                            if key in field_key_to_id:
                                custom_values_to_create.append(LeadCustomValueCreate(
                                    custom_field_id=field_key_to_id[key],
                                    value=str(val) if val is not None else ""
                                ))

                        if custom_values_to_create:
                            LeadCustomFieldsService.create_lead_custom_values(existing_lead.id, custom_values_to_create, db)
                            logger.info(f"[CreateLeadHandler] Updated {len(custom_values_to_create)} custom values for lead {existing_lead.id}")
                except Exception as e_custom:
                    logger.error(f"[CreateLeadHandler] Error updating custom fields: {e_custom}")

                logger.info(f"[CreateLeadHandler] Updated existing lead: {existing_lead.id}")

                return {
                    "success": True,
                    "action": "updated",
                    "lead_id": existing_lead.id
                }
            else:
                # Create new lead
                result = db.execute(text("""
                    INSERT INTO leads (
                        client_id, company_id, name, phone, created_at, data_entrada,
                        pipeline_id, current_stage_id
                    )
                    VALUES (
                        :client_id, :company_id, :name, :phone, TO_CHAR(NOW(), 'YYYY-MM-DD HH24:MI:SS'), NOW(),
                        :pipeline_id, :current_stage_id
                    )
                    RETURNING id
                """), {
                    "client_id": str(client_id),
                    "company_id": company_id,
                    "name": name or phone,
                    "phone": phone,
                    "pipeline_id": configured_pipeline_id,
                    "current_stage_id": configured_stage_id,
                })

                new_lead_id = result.fetchone().id
                db.commit()

                # --- NEW: Save custom fields/UTMs ---
                try:
                    from backend.services.lead_custom_fields_service import LeadCustomFieldsService, LeadCustomValueCreate

                    # Identify fields that are NOT standard lead columns
                    standard_fields = ['name', 'phone', 'email'] # email is handled as custom usually if not in table
                    custom_data = {k: v for k, v in lead_data.items() if k not in standard_fields}

                    if custom_data:
                        logger.info(f"[CreateLeadHandler] saving custom fields for lead {new_lead_id}: {list(custom_data.keys())}")

                        # Get valid custom fields for this company
                        company_fields = LeadCustomFieldsService.get_company_custom_fields(company_id, True, db)
                        field_key_to_id = {f.field_key: f.id for f in company_fields}

                        custom_values_to_create = []
                        for key, val in custom_data.items():
                            if key in field_key_to_id:
                                custom_values_to_create.append(LeadCustomValueCreate(
                                    custom_field_id=field_key_to_id[key],
                                    value=str(val) if val is not None else ""
                                ))

                        if custom_values_to_create:
                            LeadCustomFieldsService.create_lead_custom_values(new_lead_id, custom_values_to_create, db)
                            logger.info(f"[CreateLeadHandler] Saved {len(custom_values_to_create)} custom values for lead {new_lead_id}")
                except Exception as e_custom:
                    logger.error(f"[CreateLeadHandler] Error saving custom fields: {e_custom}")

                logger.info(f"[CreateLeadHandler] Created new lead: {new_lead_id}")

                try:
                    from backend.models import Lead
                    from backend.services.flow_event_service import trigger_crm_lead_created

                    new_lead = db.query(Lead).filter(
                        Lead.id == new_lead_id,
                        Lead.company_id == company_id,
                    ).first()
                    if new_lead:
                        started_flows = trigger_crm_lead_created(
                            db,
                            lead=new_lead,
                            created_at=new_lead.created_at,
                            exclude_flow_id=flow_id,
                        )
                        if started_flows:
                            logger.info(
                                "[CreateLeadHandler] Started %s lead_created flow(s) for lead_id=%s",
                                started_flows,
                                new_lead_id,
                            )
                except Exception as flow_event_err:
                    logger.error(
                        "[CreateLeadHandler] Error starting lead_created flows for lead_id=%s: %s",
                        new_lead_id,
                        flow_event_err,
                    )

                return {
                    "success": True,
                    "action": "created",
                    "lead_id": new_lead_id,
                    "pipeline_id": configured_pipeline_id,
                    "current_stage_id": configured_stage_id,
                }

        except Exception as e:
            db.rollback()
            logger.exception(f"[CreateLeadHandler] Error creating/updating lead: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _get_nested_value(self, data: Dict, path: str) -> Any:
        """Get value from nested dict using dot notation path"""
        parts = path.split('.')
        value = data

        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return None

        return value


class AgentResponseHandler(BaseNodeHandler):
    """Handler for AI agent response generation"""

    def execute(
        self,
        db: Session,
        node_data: Dict[str, Any],
        variables: Dict[str, Any],
        company_id: int,
        flow_id: int
    ) -> Dict[str, Any]:
        from backend.services.flow_agent_runner import run_agent_response

        agent_id = node_data.get('agentId')

        if not agent_id:
            logger.error("[AgentResponseHandler] No agent ID configured")
            return {
                "success": False,
                "error": "No agent ID configured in node"
            }

        # Get message from variables
        message = (
            variables.get('message') or
            variables.get('body') or
            variables.get('trigger', {}).get('body') or
            variables.get('trigger', {}).get('message', '')
        )

        if not message:
            logger.warning("[AgentResponseHandler] No message available for agent")
            message = "Olá"  # Default message

        logger.info(f"[AgentResponseHandler] Running agent {agent_id} with message: {message[:50]}...")

        try:
            result = run_agent_response(
                db=db,
                company_id=company_id,
                agent_config_id=agent_id,
                message=message
            )

            if result.get('success'):
                response = result.get('response', '')

                # Store response in variables for next nodes
                variables['agent_response'] = response
                variables['agent_tokens'] = result.get('tokens_used', 0)

                logger.info(f"[AgentResponseHandler] Agent response generated: {len(response)} chars")

                return {
                    "success": True,
                    "response": response,
                    "tokens_used": result.get('tokens_used', 0)
                }
            else:
                from backend.services.ai_credit_guard import is_ai_credit_block_result

                if is_ai_credit_block_result(result):
                    return {
                        **result,
                        "stop_flow": True,
                    }
                return {
                    "success": False,
                    "error": result.get('error', 'Agent execution failed')
                }

        except Exception as e:
            logger.exception(f"[AgentResponseHandler] Error running agent: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class AgentWorkforceHandler(BaseNodeHandler):
    """Handler for multi-agent workforce response generation"""

    def execute(
        self,
        db: Session,
        node_data: Dict[str, Any],
        variables: Dict[str, Any],
        company_id: int,
        flow_id: int
    ) -> Dict[str, Any]:
        from backend.services.flow_agent_workforce_runner import run_agent_workforce_response

        workforce_id = node_data.get("workforceId")
        if not workforce_id:
            logger.error("[AgentWorkforceHandler] No workforce ID configured")
            return {
                "success": False,
                "error": "No agent workforce configured in node"
            }

        message_template = (
            node_data.get("inputMessage")
            or "{{trigger.body}}"
        )
        message = self.resolve_variables(str(message_template), variables)
        if not message or message == "{{trigger.body}}":
            message = (
                variables.get("message")
                or variables.get("body")
                or variables.get("trigger", {}).get("body")
                or variables.get("trigger", {}).get("message", "")
            )

        if not message:
            message = "Olá"

        logger.info(
            "[AgentWorkforceHandler] Running workforce %s with message: %s...",
            workforce_id,
            str(message)[:50],
        )

        try:
            result = run_agent_workforce_response(
                db=db,
                workforce_id=int(workforce_id),
                company_id=company_id,
                message=str(message),
                runtime_variables=variables,
                flow_id=flow_id,
                node_id=node_data.get("id"),
                provider_message_id=variables.get("messageId")
                or variables.get("trigger", {}).get("messageId")
                or variables.get("trigger", {}).get("id"),
            )

            if not result.get("success"):
                from backend.services.ai_credit_guard import is_ai_credit_block_result

                if is_ai_credit_block_result(result):
                    return {
                        **result,
                        "stop_flow": True,
                    }
                if result.get("blocked_by_schedule") or result.get("workforce_status") not in (None, "active"):
                    return {
                        **result,
                        "stop_flow": True,
                    }
                return {
                    "success": False,
                    "error": result.get("error", "Agent workforce execution failed")
                }

            response = result.get("response", "")
            variables["agent_response"] = response
            result_metadata = result.get("metadata", {}) if isinstance(result.get("metadata"), dict) else {}
            suppress_whatsapp_send = bool(result_metadata.get("suppress_whatsapp_send"))
            agent_workforce_payload = {
                "response": response,
                "workforce_id": result.get("workforce_id"),
                "workforce_name": result.get("workforce_name"),
                "root_agent_key": result.get("root_agent_key"),
                "root_agent_name": result.get("root_agent_name"),
                "handoff_target": result.get("handoff_target"),
                "last_agent_key": result.get("last_agent_key"),
                "last_agent_name": result.get("last_agent_name"),
                "tokens_used": result.get("tokens_used", 0),
                "audio": result.get("audio"),
                "should_send_audio": bool(result.get("should_send_audio")),
                "audio_trigger": result.get("audio_trigger"),
                "audio_delivery_mode": result.get("audio_delivery_mode"),
                "audio_text_intro": result.get("audio_text_intro"),
                "audio_text": result.get("audio_text"),
                "audio_split_parts": result.get("audio_split_parts", []),
                "voice_used": result.get("voice_used"),
                "voice_provider": result.get("voice_provider"),
                "voice_model": result.get("voice_model"),
                "audio_error": result.get("audio_error"),
                "suppress_whatsapp_send": suppress_whatsapp_send,
                "metadata": result_metadata,
            }
            variables["agent_workforce"] = agent_workforce_payload
            variables["agentWorkforce"] = agent_workforce_payload

            payload = {
                "success": True,
                "response": response,
                "tokens_used": result.get("tokens_used", 0),
                "workforce_id": result.get("workforce_id"),
                "workforce_name": result.get("workforce_name"),
                "root_agent_key": result.get("root_agent_key"),
                "root_agent_name": result.get("root_agent_name"),
                "handoff_target": result.get("handoff_target"),
                "should_send_audio": bool(result.get("should_send_audio")),
                "audio_trigger": result.get("audio_trigger"),
                "audio_delivery_mode": result.get("audio_delivery_mode"),
                "audio_text_intro": result.get("audio_text_intro"),
                "audio_text": result.get("audio_text"),
                "audio_split_parts": result.get("audio_split_parts", []),
                "voice_used": result.get("voice_used"),
                "voice_provider": result.get("voice_provider"),
                "voice_model": result.get("voice_model"),
                "audio_error": result.get("audio_error"),
                "suppress_whatsapp_send": suppress_whatsapp_send,
                "metadata": result.get("metadata", {}),
            }
            if suppress_whatsapp_send:
                payload["stop_flow"] = True
            return payload
        except Exception as e:
            logger.exception("[AgentWorkforceHandler] Error running workforce: %s", e)
            return {
                "success": False,
                "error": str(e)
            }


class DelayHandler(BaseNodeHandler):
    """Handler for delay nodes - schedules continuation after delay"""

    def execute(
        self,
        db: Session,
        node_data: Dict[str, Any],
        variables: Dict[str, Any],
        company_id: int,
        flow_id: int
    ) -> Dict[str, Any]:
        from datetime import timedelta, timezone

        delay_amount = int(node_data.get('delayAmount', 1))
        delay_unit = node_data.get('delayUnit', 'minutes')

        # Calculate delay in seconds for normalization
        total_seconds = 0
        if delay_unit == 'seconds':
            total_seconds = delay_amount
        elif delay_unit == 'minutes':
            total_seconds = delay_amount * 60
        elif delay_unit == 'hours':
            total_seconds = delay_amount * 3600
        elif delay_unit == 'days':
            total_seconds = delay_amount * 86400
        else:
            total_seconds = delay_amount * 60  # default to minutes

        # Enforce MAX limit of 5 minutes (300 seconds)
        MAX_DELAY_SECONDS = 300
        if total_seconds > MAX_DELAY_SECONDS:
            logger.warning(f"[DelayHandler] Requested delay {total_seconds}s exceeds limit. Capping at {MAX_DELAY_SECONDS}s.")
            total_seconds = MAX_DELAY_SECONDS
            delay_amount = 5
            delay_unit = 'minutes'

        delay = timedelta(seconds=total_seconds)
        # Use timezone-aware UTC to prevent Celery from assuming local time (Sao Paulo)
        eta = datetime.now(timezone.utc) + delay

        logger.info(f"[DelayHandler] Scheduling continuation for {eta} ({total_seconds}s)")

        return {
            "success": True,
            "delay_execution": True,
            "delay_seconds": total_seconds,
            "scheduled_for": eta.isoformat()
        }


class WaitRelativeHandler(BaseNodeHandler):
    """Schedule continuation relative to a business event anchor."""

    def execute(
        self,
        db: Session,
        node_data: Dict[str, Any],
        variables: Dict[str, Any],
        company_id: int,
        flow_id: int
    ) -> Dict[str, Any]:
        amount = int(node_data.get("offsetAmount") or node_data.get("delayAmount") or 1)
        unit = str(node_data.get("offsetUnit") or node_data.get("delayUnit") or "hours")
        direction = str(node_data.get("offsetDirection") or "before")
        anchor_type = str(node_data.get("anchorType") or "anchor_at")

        anchor_raw = self._resolve_anchor(anchor_type, variables)
        if not anchor_raw:
            return {
                "success": False,
                "error": f"Anchor not available for {anchor_type}",
            }

        anchor_at = self._parse_datetime(anchor_raw)
        if not anchor_at:
            return {
                "success": False,
                "error": f"Invalid anchor datetime: {anchor_raw}",
            }

        delta = self._delta(amount, unit)
        scheduled_for = anchor_at - delta if direction == "before" else anchor_at + delta
        now = datetime.now(timezone.utc)
        if scheduled_for <= now:
            logger.info(
                "[WaitRelativeHandler] Target time %s already passed; continuing immediately",
                scheduled_for.isoformat(),
            )
            return {
                "success": True,
                "delay_execution": False,
                "scheduled_for": now.isoformat(),
                "anchor_at": anchor_at.isoformat(),
            }

        logger.info(
            "[WaitRelativeHandler] Scheduling continuation for %s relative to %s",
            scheduled_for.isoformat(),
            anchor_at.isoformat(),
        )
        return {
            "success": True,
            "delay_execution": True,
            "scheduled_for": scheduled_for.isoformat(),
            "anchor_at": anchor_at.isoformat(),
            "offset_amount": amount,
            "offset_unit": unit,
            "offset_direction": direction,
        }

    def _resolve_anchor(self, anchor_type: str, variables: Dict[str, Any]) -> Optional[Any]:
        trigger = variables.get("trigger", {}) or {}
        appointment = trigger.get("appointment", {}) if isinstance(trigger.get("appointment"), dict) else {}
        crm_stage = trigger.get("crm_stage", {}) if isinstance(trigger.get("crm_stage"), dict) else {}

        if anchor_type in {"appointment_start", "appointment.starts_at"}:
            return appointment.get("starts_at") or appointment.get("consulta_data") or trigger.get("anchor_at")
        if anchor_type in {"crm_stage_entered_at", "crm_stage.entered_at"}:
            return crm_stage.get("entered_at") or trigger.get("anchor_at")
        return variables.get("anchor_at") or trigger.get("anchor_at")

    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _delta(self, amount: int, unit: str) -> timedelta:
        if unit == "minutes":
            return timedelta(minutes=amount)
        if unit == "days":
            return timedelta(days=amount)
        return timedelta(hours=amount)


class AddTagHandler(BaseNodeHandler):
    """Add an existing company tag to the current flow contact."""

    def execute(
        self,
        db: Session,
        node_data: Dict[str, Any],
        variables: Dict[str, Any],
        company_id: int,
        flow_id: int
    ) -> Dict[str, Any]:
        from backend.models import Contact, ContactTag, Tag

        tag_id = self._parse_positive_int(node_data.get("tagId") or node_data.get("tag_id"))
        if not tag_id:
            result = {
                "success": False,
                "stop_branch": True,
                "error": "Tag is required",
            }
            variables["add_tag"] = result
            return result

        tag = db.query(Tag).filter(
            Tag.id == tag_id,
            Tag.company_id == company_id,
        ).first()
        if not tag:
            result = {
                "success": False,
                "stop_branch": True,
                "error": "Tag not found for company",
                "tag_id": tag_id,
            }
            variables["add_tag"] = result
            return result

        contact = self._resolve_flow_contact(db, variables, company_id)
        if not contact:
            lead = self._resolve_flow_lead(db, variables, company_id)
            resolved_phone = self._resolve_phone(variables, lead=lead, contact=None)
            resolved_name = self._resolve_name(variables, lead=lead, contact=None)

            if not resolved_phone:
                result = {
                    "success": False,
                    "stop_branch": False,
                    "action": "skipped",
                    "error": "Contact not found for flow",
                    "tag_id": tag.id,
                    "tag_name": tag.name,
                }
                variables["add_tag"] = result
                return result

            client_id = self._resolve_client_id(db, company_id)
            if not client_id:
                result = {
                    "success": False,
                    "stop_branch": False,
                    "action": "skipped",
                    "error": "Client association not found for company",
                    "tag_id": tag.id,
                    "tag_name": tag.name,
                    "lead_phone": resolved_phone,
                }
                variables["add_tag"] = result
                return result

            contact = Contact(
                client_id=client_id,
                company_id=company_id,
                phone=resolved_phone,
                name=resolved_name or None,
                human_mode=False,
            )
            try:
                db.add(contact)
                db.flush()
                variables["contact_id"] = contact.id
            except IntegrityError:
                db.rollback()
                contact = self._resolve_flow_contact(
                    db,
                    variables,
                    company_id,
                    explicit_phone=resolved_phone,
                )
            except Exception as e:
                db.rollback()
                logger.exception("[AddTagHandler] Error creating contact for tag %s: %s", tag.id, e)
                result = {
                    "success": False,
                    "stop_branch": False,
                    "action": "skipped",
                    "error": str(e),
                    "tag_id": tag.id,
                    "tag_name": tag.name,
                    "lead_phone": resolved_phone,
                }
                variables["add_tag"] = result
                return result

            if not contact:
                result = {
                    "success": False,
                    "stop_branch": False,
                    "action": "skipped",
                    "error": "Contact not found for flow",
                    "tag_id": tag.id,
                    "tag_name": tag.name,
                    "lead_phone": resolved_phone,
                }
                variables["add_tag"] = result
                return result

        existing = db.query(ContactTag).filter(
            ContactTag.contact_id == contact.id,
            ContactTag.tag_id == tag.id,
        ).first()
        if existing:
            result = {
                "success": True,
                "action": "already_exists",
                "contact_id": contact.id,
                "tag_id": tag.id,
                "tag_name": tag.name,
            }
            variables["add_tag"] = result
            return result

        try:
            db.add(ContactTag(contact_id=contact.id, tag_id=tag.id))
            db.commit()
        except IntegrityError:
            db.rollback()
            result = {
                "success": True,
                "action": "already_exists",
                "contact_id": contact.id,
                "tag_id": tag.id,
                "tag_name": tag.name,
            }
            variables["add_tag"] = result
            return result
        except Exception as e:
            db.rollback()
            logger.exception("[AddTagHandler] Error adding tag %s to contact %s: %s", tag.id, contact.id, e)
            result = {
                "success": False,
                "stop_branch": True,
                "error": str(e),
                "contact_id": contact.id,
                "tag_id": tag.id,
                "tag_name": tag.name,
            }
            variables["add_tag"] = result
            return result

        result = {
            "success": True,
            "action": "added",
            "contact_id": contact.id,
            "tag_id": tag.id,
            "tag_name": tag.name,
        }
        variables["add_tag"] = result
        return result


class MoveCrmStageHandler(BaseNodeHandler):
    """Move the current flow lead to a selected CRM stage."""

    def execute(
        self,
        db: Session,
        node_data: Dict[str, Any],
        variables: Dict[str, Any],
        company_id: int,
        flow_id: int
    ) -> Dict[str, Any]:
        from fastapi import HTTPException
        from backend.models import Pipeline, PipelineStage
        from backend.services.pipeline_service import PipelineService

        _ = flow_id

        stage_id = self._parse_positive_int(node_data.get("stageId") or node_data.get("stage_id"))
        pipeline_id = self._parse_positive_int(node_data.get("pipelineId") or node_data.get("pipeline_id"))
        lead_id_value = self._resolve_node_config_value(
            node_data,
            variables,
            "leadId",
            "lead_id",
        )
        lead_phone_value = self._resolve_node_config_value(
            node_data,
            variables,
            "leadPhone",
            "lead_phone",
            "phone",
        )
        if not stage_id:
            result = {
                "success": False,
                "stop_branch": True,
                "error": "Stage is required",
            }
            variables["move_crm_stage"] = result
            return result

        stage = db.query(PipelineStage).join(Pipeline).filter(
            PipelineStage.id == stage_id,
            Pipeline.company_id == company_id,
        ).first()
        if not stage:
            result = {
                "success": False,
                "stop_branch": True,
                "error": "Stage not found for company",
                "stage_id": stage_id,
            }
            variables["move_crm_stage"] = result
            return result

        if pipeline_id and stage.pipeline_id != pipeline_id:
            result = {
                "success": False,
                "stop_branch": True,
                "error": "Stage does not belong to selected pipeline",
                "pipeline_id": pipeline_id,
                "stage_id": stage.id,
            }
            variables["move_crm_stage"] = result
            return result

        lead = self._resolve_flow_lead(
            db,
            variables,
            company_id,
            explicit_lead_id=lead_id_value,
            explicit_phone=lead_phone_value,
        )
        if not lead:
            result = {
                "success": False,
                "stop_branch": True,
                "error": "Lead not found for flow",
                "lead_phone": lead_phone_value,
                "lead_id": lead_id_value,
                "stage_id": stage.id,
                "stage_name": stage.name,
            }
            variables["move_crm_stage"] = result
            return result

        if lead.current_stage_id == stage.id:
            result = {
                "success": True,
                "changed": False,
                "lead_id": lead.id,
                "pipeline_id": stage.pipeline_id,
                "stage_id": stage.id,
                "stage_name": stage.name,
                "lead_phone": lead_phone_value or lead.phone,
                "message": "Lead already in selected stage",
            }
            variables["move_crm_stage"] = result
            return result

        notes_template = str(
            node_data.get("notes")
            or node_data.get("reason")
            or "Movido pelo FlowBuilder."
        )
        notes = self.resolve_variables(notes_template, variables)

        try:
            history = PipelineService.move_lead_to_stage(
                lead_id=lead.id,
                new_stage_id=stage.id,
                user_id=None,
                notes=notes,
                db=db,
            )
            db.refresh(lead)
        except HTTPException as exc:
            result = {
                "success": False,
                "stop_branch": True,
                "error": "pipeline_service_error",
                "detail": str(exc.detail),
                "lead_id": lead.id,
                "stage_id": stage.id,
                "stage_name": stage.name,
            }
            variables["move_crm_stage"] = result
            return result
        except Exception as exc:
            db.rollback()
            logger.exception("[MoveCrmStageHandler] Error moving lead %s to stage %s", lead.id, stage.id)
            result = {
                "success": False,
                "stop_branch": True,
                "error": str(exc),
                "lead_id": lead.id,
                "stage_id": stage.id,
                "stage_name": stage.name,
            }
            variables["move_crm_stage"] = result
            return result

        result = {
            "success": True,
            "changed": True,
            "lead_id": lead.id,
            "history_id": history.id,
            "from_stage_id": history.from_stage_id,
            "to_stage_id": history.to_stage_id,
            "pipeline_id": stage.pipeline_id,
            "stage_id": stage.id,
            "stage_name": stage.name,
            "lead_phone": lead_phone_value or lead.phone,
            "notes": notes,
            "moved_at": history.moved_at.isoformat() if history.moved_at else None,
        }
        variables["move_crm_stage"] = result
        return result


class HumanHandoffHandler(BaseNodeHandler):
    """Assign the current contact to a human task without messaging the lead."""

    VALID_PRIORITIES = {"low", "medium", "high", "urgent"}

    def execute(
        self,
        db: Session,
        node_data: Dict[str, Any],
        variables: Dict[str, Any],
        company_id: int,
        flow_id: int
    ) -> Dict[str, Any]:
        from backend.models import Contact, ContactTask, User

        assigned_to = self._parse_positive_int(
            node_data.get("assignedUserId")
            or node_data.get("assigned_user_id")
            or node_data.get("assignedTo")
        )
        if assigned_to:
            user = db.query(User).filter(
                User.id == assigned_to,
                User.company_id == company_id,
                User.is_active == True,
            ).first()
            if not user:
                result = {
                    "success": False,
                    "stop_branch": True,
                    "error": "Assigned user not found for company",
                    "assigned_to": assigned_to,
                }
                variables["human_handoff"] = result
                return result

        lead_phone_value = self._resolve_node_config_value(
            node_data,
            variables,
            "leadPhone",
            "lead_phone",
            "phone",
        )
        contact = self._resolve_flow_contact(
            db,
            variables,
            company_id,
            explicit_phone=lead_phone_value,
        )
        lead = self._resolve_flow_lead(
            db,
            variables,
            company_id,
            explicit_phone=lead_phone_value,
        )
        resolved_phone = self._resolve_phone(
            variables,
            lead=lead,
            contact=contact,
            explicit_phone=lead_phone_value,
        )
        resolved_name = self._resolve_name(variables, lead=lead, contact=contact)

        if not contact and resolved_phone:
            client_id = self._resolve_client_id(db, company_id)
            if not client_id:
                result = {
                    "success": False,
                    "stop_branch": True,
                    "error": "Client association not found for company",
                }
                variables["human_handoff"] = result
                return result

            contact = Contact(
                client_id=client_id,
                company_id=company_id,
                phone=resolved_phone,
                name=resolved_name or None,
                human_mode=False,
            )
            try:
                db.add(contact)
                db.flush()
            except Exception as exc:
                db.rollback()
                logger.exception("[HumanHandoffHandler] Error creating contact for handoff")
                result = {
                    "success": False,
                    "stop_branch": True,
                    "error": str(exc),
                    "phone": resolved_phone,
                }
                variables["human_handoff"] = result
                return result

        if not contact:
            result = {
                "success": False,
                "stop_branch": True,
                "error": "Contact not found for flow",
            }
            variables["human_handoff"] = result
            return result

        if resolved_name and not contact.name:
            contact.name = resolved_name

        pause_bot = node_data.get("pauseBot")
        if pause_bot is None:
            pause_bot = node_data.get("pause_bot")
        pause_bot = pause_bot is not False
        if pause_bot:
            contact.human_mode = True

        priority = self._normalize_priority(node_data.get("priority"))
        title_template = str(node_data.get("title") or "Atender lead")
        reason_template = str(node_data.get("reason") or "Solicitado pelo fluxo.")
        summary_template = str(node_data.get("summary") or "")

        title = self.resolve_variables(title_template, variables).strip() or "Atender lead"
        reason = self.resolve_variables(reason_template, variables).strip()
        summary = self.resolve_variables(summary_template, variables).strip()

        task = ContactTask(
            contact_id=contact.id,
            company_id=company_id,
            assigned_to=assigned_to,
            task_type="message",
            title=title,
            description=self._build_description(
                reason=reason,
                summary=summary,
                lead_name=resolved_name or contact.name or "",
                lead_phone=resolved_phone or contact.phone or "",
            ),
            scheduled_for=datetime.now(timezone.utc),
            reminder_minutes=0,
            priority=priority,
            tags=[
                "agentive_handoff",
                "flowbuilder_handoff",
                f"flow:{flow_id}",
            ],
            task_metadata={
                "source": "flow_builder_human_handoff",
                "flow_id": flow_id,
                "node_label": node_data.get("label"),
                "reason": reason,
                "summary": summary,
                "pause_bot": pause_bot,
                "silent": True,
                "stop_flow": node_data.get("stopFlow", True) is not False,
                "lead_id": lead.id if lead else None,
            },
        )

        try:
            db.add(task)
            db.commit()
            db.refresh(task)
        except Exception as exc:
            db.rollback()
            logger.exception("[HumanHandoffHandler] Error creating handoff task for contact %s", contact.id)
            result = {
                "success": False,
                "stop_branch": True,
                "error": str(exc),
                "contact_id": contact.id,
            }
            variables["human_handoff"] = result
            return result

        result = {
            "success": True,
            "task_id": task.id,
            "contact_id": contact.id,
            "lead_phone": resolved_phone or contact.phone,
            "assigned_to": assigned_to,
            "priority": priority,
            "bot_paused": pause_bot,
            "silent": True,
            "suppress_whatsapp_send": True,
            "stop_flow": node_data.get("stopFlow", True) is not False,
        }
        variables["human_handoff"] = result
        return result

    def _normalize_priority(self, priority: Any) -> str:
        value = str(priority or "medium").strip().lower()
        return value if value in self.VALID_PRIORITIES else "medium"

    def _resolve_client_id(self, db: Session, company_id: int) -> Optional[int]:
        from backend.models import Client, ClientCompany

        association = db.query(ClientCompany).filter(
            ClientCompany.company_id == company_id,
        ).order_by(ClientCompany.id.asc()).first()
        if association:
            return int(association.client_id)

        client = db.query(Client).filter(Client.company_id == company_id).first()
        return int(client.id) if client else None

    def _resolve_phone(
        self,
        variables: Dict[str, Any],
        *,
        lead: Optional[Any],
        contact: Optional[Any],
        explicit_phone: Optional[Any] = None,
    ) -> str:
        trigger = variables.get("trigger", {}) if isinstance(variables.get("trigger"), dict) else {}
        trigger_body = trigger.get("body", {}) if isinstance(trigger.get("body"), dict) else {}
        phone = (
            explicit_phone
            or variables.get("phone")
            or variables.get("whatsapp")
            or trigger.get("phone")
            or trigger.get("whatsapp")
            or trigger_body.get("phone")
            or trigger_body.get("whatsapp")
            or getattr(contact, "phone", None)
            or getattr(lead, "phone", None)
            or ""
        )
        digits = "".join(filter(str.isdigit, str(phone or "")))
        if len(digits) in (10, 11):
            return f"55{digits}"
        return digits

    def _resolve_name(
        self,
        variables: Dict[str, Any],
        *,
        lead: Optional[Any],
        contact: Optional[Any],
    ) -> str:
        trigger = variables.get("trigger", {}) if isinstance(variables.get("trigger"), dict) else {}
        trigger_body = trigger.get("body", {}) if isinstance(trigger.get("body"), dict) else {}
        return str(
            variables.get("name")
            or trigger.get("name")
            or trigger_body.get("name")
            or getattr(contact, "name", None)
            or getattr(lead, "name", None)
            or ""
        ).strip()

    def _build_description(
        self,
        *,
        reason: str,
        summary: str,
        lead_name: str,
        lead_phone: str,
    ) -> str:
        parts = [
            f"Motivo: {reason.strip()}" if reason.strip() else "",
            f"Resumo: {summary.strip()}" if summary.strip() else "",
            f"Lead: {lead_name.strip()}" if lead_name.strip() else "",
            f"Telefone: {lead_phone}" if lead_phone else "",
        ]
        return "\n".join(part for part in parts if part)


class TagFilterHandler(BaseNodeHandler):
    """Gate a branch with tag and lead custom-field conditions."""

    TAG_OPERATORS = {
        "has_tag": "has_tag",
        "has": "has_tag",
        "contains_tag": "has_tag",
        "not_has_tag": "not_has_tag",
        "does_not_have_tag": "not_has_tag",
        "lacks_tag": "not_has_tag",
        "without_tag": "not_has_tag",
    }

    FIELD_OPERATORS = {
        "equals": "equals",
        "eq": "equals",
        "not_equals": "not_equals",
        "ne": "not_equals",
        "contains": "contains",
        "not_contains": "not_contains",
        "is_empty": "is_empty",
        "empty": "is_empty",
        "is_not_empty": "is_not_empty",
        "not_empty": "is_not_empty",
        "has_value": "is_not_empty",
        "greater_than": "greater_than",
        "gt": "greater_than",
        "less_than": "less_than",
        "lt": "less_than",
        "greater_or_equal": "greater_or_equal",
        "greater_than_or_equal": "greater_or_equal",
        "gte": "greater_or_equal",
        "less_or_equal": "less_or_equal",
        "less_than_or_equal": "less_or_equal",
        "lte": "less_or_equal",
    }

    def execute(
        self,
        db: Session,
        node_data: Dict[str, Any],
        variables: Dict[str, Any],
        company_id: int,
        flow_id: int
    ) -> Dict[str, Any]:
        _ = flow_id

        conditions = self._build_conditions(node_data)
        if not conditions:
            result = {
                "success": False,
                "condition_met": False,
                "matched": False,
                "stop_branch": True,
                "error": "At least one filter condition is required",
            }
            self._store_result(variables, result)
            return result

        match_mode = self._normalize_match_mode(
            node_data.get("conditionMatch")
            or node_data.get("matchMode")
            or node_data.get("conditionsMode")
        )
        action_on_match = self._normalize_action(
            node_data.get("actionOnMatch")
            or node_data.get("matchAction")
            or node_data.get("passBehavior")
        )

        condition_results = []
        for condition in conditions:
            condition_result = self._evaluate_condition(db, condition, variables, company_id)
            condition_results.append(condition_result)
            if not condition_result.get("success", False):
                result = {
                    "success": False,
                    "condition_met": False,
                    "matched": False,
                    "stop_branch": True,
                    "match_mode": match_mode,
                    "action_on_match": action_on_match,
                    "conditions": condition_results,
                    "error": condition_result.get("error") or "Invalid filter condition",
                }
                self._copy_legacy_tag_metadata(result, condition_results)
                self._store_result(variables, result)
                return result

        matched_values = [bool(item.get("matched")) for item in condition_results]
        condition_met = all(matched_values) if match_mode == "all" else any(matched_values)
        should_advance = condition_met if action_on_match == "advance" else not condition_met

        result = {
            "success": True,
            "condition_met": condition_met,
            "matched": condition_met,
            "stop_branch": not should_advance,
            "match_mode": match_mode,
            "action_on_match": action_on_match,
            "conditions": condition_results,
        }
        self._copy_legacy_tag_metadata(result, condition_results)
        self._store_result(variables, result)
        return result

    def _build_conditions(self, node_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        raw_conditions = node_data.get("conditions")
        if isinstance(raw_conditions, list):
            conditions = [condition for condition in raw_conditions if isinstance(condition, dict)]
            if conditions:
                return conditions

        tag_id = self._parse_positive_int(node_data.get("tagId") or node_data.get("tag_id"))
        if tag_id:
            return [{
                "source": "tag",
                "operator": node_data.get("filterMode") or "has_tag",
                "tagId": tag_id,
                "tagName": node_data.get("tagName") or node_data.get("tag_name"),
            }]

        return []

    def _normalize_match_mode(self, value: Any) -> str:
        normalized = str(value or "all").strip().lower()
        if normalized in {"any", "or", "qualquer"}:
            return "any"
        return "all"

    def _normalize_action(self, value: Any) -> str:
        normalized = str(value or "advance").strip().lower()
        if normalized in {"stop", "block", "halt", "nao_avancar", "não_avançar", "do_not_advance"}:
            return "stop"
        return "advance"

    def _evaluate_condition(
        self,
        db: Session,
        condition: Dict[str, Any],
        variables: Dict[str, Any],
        company_id: int,
    ) -> Dict[str, Any]:
        source = str(
            condition.get("source")
            or condition.get("type")
            or condition.get("fieldType")
            or "tag"
        ).strip().lower()

        if source in {"tag", "tags"}:
            return self._evaluate_tag_condition(db, condition, variables, company_id)
        if source in {"custom_field", "customfield", "field", "lead_field", "leadcustomfield"}:
            return self._evaluate_custom_field_condition(db, condition, variables, company_id)

        return {
            "success": False,
            "matched": False,
            "source": source,
            "error": "Unsupported filter condition source",
        }

    def _evaluate_tag_condition(
        self,
        db: Session,
        condition: Dict[str, Any],
        variables: Dict[str, Any],
        company_id: int,
    ) -> Dict[str, Any]:
        from backend.models import ContactTag, Tag

        tag_id = self._parse_positive_int(condition.get("tagId") or condition.get("tag_id"))
        operator = self.TAG_OPERATORS.get(str(condition.get("operator") or "has_tag").strip().lower(), "has_tag")
        if not tag_id:
            result = {
                "success": False,
                "condition_met": False,
                "matched": False,
                "source": "tag",
                "operator": operator,
                "error": "Tag is required",
            }
            return result

        tag = db.query(Tag).filter(
            Tag.id == tag_id,
            Tag.company_id == company_id,
        ).first()
        if not tag:
            return {
                "success": False,
                "condition_met": False,
                "matched": False,
                "source": "tag",
                "operator": operator,
                "error": "Tag not found for company",
                "tag_id": tag_id,
            }

        contact = self._resolve_flow_contact(db, variables, company_id)
        if not contact:
            return {
                "success": True,
                "condition_met": False,
                "matched": False,
                "source": "tag",
                "operator": operator,
                "reason": "contact_not_found",
                "tag_id": tag.id,
                "tag_name": tag.name,
            }

        has_tag = db.query(ContactTag.id).filter(
            ContactTag.contact_id == contact.id,
            ContactTag.tag_id == tag.id,
        ).first() is not None
        matched = has_tag if operator == "has_tag" else not has_tag

        return {
            "success": True,
            "condition_met": matched,
            "matched": matched,
            "source": "tag",
            "operator": operator,
            "actual": has_tag,
            "contact_id": contact.id,
            "tag_id": tag.id,
            "tag_name": tag.name,
        }

    def _evaluate_custom_field_condition(
        self,
        db: Session,
        condition: Dict[str, Any],
        variables: Dict[str, Any],
        company_id: int,
    ) -> Dict[str, Any]:
        from backend.models import LeadCustomField, LeadCustomValue

        field_id = self._parse_positive_int(
            condition.get("customFieldId")
            or condition.get("custom_field_id")
            or condition.get("fieldId")
            or condition.get("field_id")
        )
        field_key = str(
            condition.get("fieldKey")
            or condition.get("field_key")
            or ""
        ).strip()
        operator = self.FIELD_OPERATORS.get(str(condition.get("operator") or "equals").strip().lower(), "equals")
        expected = self._resolve_expected_value(condition, variables)

        if field_id:
            field = db.query(LeadCustomField).filter(
                LeadCustomField.id == field_id,
                LeadCustomField.company_id == company_id,
                LeadCustomField.is_active == True,
            ).first()
        elif field_key:
            field = db.query(LeadCustomField).filter(
                LeadCustomField.field_key == field_key,
                LeadCustomField.company_id == company_id,
                LeadCustomField.is_active == True,
            ).first()
        else:
            field = None

        if not field:
            return {
                "success": False,
                "condition_met": False,
                "matched": False,
                "source": "custom_field",
                "operator": operator,
                "custom_field_id": field_id,
                "field_key": field_key,
                "error": "Custom field not found for company",
            }

        lead = self._resolve_flow_lead(db, variables, company_id)
        if not lead:
            return {
                "success": True,
                "condition_met": False,
                "matched": False,
                "source": "custom_field",
                "operator": operator,
                "reason": "lead_not_found",
                "custom_field_id": field.id,
                "field_key": field.field_key,
                "field_name": field.field_name,
                "expected": expected,
            }

        value_row = db.query(LeadCustomValue).filter(
            LeadCustomValue.lead_id == lead.id,
            LeadCustomValue.custom_field_id == field.id,
        ).first()
        actual = value_row.value if value_row else None
        matched = self._evaluate_value(actual, operator, expected)

        return {
            "success": True,
            "condition_met": matched,
            "matched": matched,
            "source": "custom_field",
            "operator": operator,
            "actual": actual,
            "expected": expected,
            "lead_id": lead.id,
            "custom_field_id": field.id,
            "field_key": field.field_key,
            "field_name": field.field_name,
            "field_type": field.field_type,
        }

    def _resolve_expected_value(self, condition: Dict[str, Any], variables: Dict[str, Any]) -> Any:
        expected = condition.get("expectedValue") if "expectedValue" in condition else condition.get("value")
        if isinstance(expected, str):
            return self.resolve_variables(expected, variables).strip()
        return expected

    def _evaluate_value(self, actual: Any, operator: str, expected: Any) -> bool:
        if operator == "is_empty":
            return self._is_empty_value(actual)
        if operator == "is_not_empty":
            return not self._is_empty_value(actual)

        actual_values = self._flatten_values(actual)
        actual_texts = [self._normalize_text(value) for value in actual_values]
        expected_text = self._normalize_text(expected)

        if operator == "equals":
            return any(text == expected_text for text in actual_texts)
        if operator == "not_equals":
            return all(text != expected_text for text in actual_texts)
        if operator == "contains":
            return expected_text in self._normalize_text(actual)
        if operator == "not_contains":
            return expected_text not in self._normalize_text(actual)

        actual_number = self._parse_number(actual)
        expected_number = self._parse_number(expected)
        if actual_number is None or expected_number is None:
            return False

        if operator == "greater_than":
            return actual_number > expected_number
        if operator == "less_than":
            return actual_number < expected_number
        if operator == "greater_or_equal":
            return actual_number >= expected_number
        if operator == "less_or_equal":
            return actual_number <= expected_number

        return False

    def _is_empty_value(self, value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip() == ""
        if isinstance(value, (list, tuple, set, dict)):
            return len(value) == 0
        return False

    def _flatten_values(self, value: Any) -> List[Any]:
        if isinstance(value, (list, tuple, set)):
            return list(value)
        return [value]

    def _normalize_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, tuple, set)):
            return " ".join(self._normalize_text(item) for item in value).strip()
        if isinstance(value, dict):
            return " ".join(
                self._normalize_text(item)
                for item in value.values()
            ).strip()
        return str(value).strip().casefold()

    def _parse_number(self, value: Any) -> Optional[float]:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        text_value = self._normalize_text(value)
        if not text_value:
            return None

        cleaned = re.sub(r"[^0-9,.\-]", "", text_value)
        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")

        try:
            return float(cleaned)
        except (TypeError, ValueError):
            return None

    def _copy_legacy_tag_metadata(
        self,
        result: Dict[str, Any],
        condition_results: List[Dict[str, Any]],
    ) -> None:
        for condition_result in condition_results:
            if condition_result.get("source") != "tag":
                continue
            for key in ("contact_id", "tag_id", "tag_name"):
                if key in condition_result:
                    result[key] = condition_result[key]
            return

    def _store_result(self, variables: Dict[str, Any], result: Dict[str, Any]) -> None:
        variables["tag_filter"] = result
        variables["lead_filter"] = result


class ConditionHandler(BaseNodeHandler):
    """Handler for condition/branch nodes"""

    def execute(
        self,
        db: Session,
        node_data: Dict[str, Any],
        variables: Dict[str, Any],
        company_id: int,
        flow_id: int
    ) -> Dict[str, Any]:

        conditions = node_data.get('conditions', [])

        for condition in conditions:
            field = condition.get('field', '')
            operator = condition.get('operator', 'equals')
            value = condition.get('value', '')

            # Get actual value from variables
            actual_value = self._get_nested_value(variables, field)

            # Evaluate condition
            result = self._evaluate_condition(actual_value, operator, value)

            if result:
                return {
                    "success": True,
                    "condition_met": True,
                    "matched_condition": condition
                }

        return {
            "success": True,
            "condition_met": False
        }

    def _get_nested_value(self, data: Dict, path: str) -> Any:
        """Get value from nested dict using dot notation path"""
        parts = path.split('.')
        value = data

        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return None

        return value

    def _evaluate_condition(self, actual: Any, operator: str, expected: Any) -> bool:
        """Evaluate a condition"""
        if actual is None:
            return False

        actual_str = str(actual).lower()
        expected_str = str(expected).lower()

        if operator == 'equals':
            return actual_str == expected_str
        elif operator == 'not_equals':
            return actual_str != expected_str
        elif operator == 'contains':
            return expected_str in actual_str
        elif operator == 'not_contains':
            return expected_str not in actual_str
        elif operator == 'starts_with':
            return actual_str.startswith(expected_str)
        elif operator == 'ends_with':
            return actual_str.endswith(expected_str)
        elif operator == 'is_empty':
            return not actual or actual_str == ''
        elif operator == 'is_not_empty':
            return actual and actual_str != ''
        else:
            return False


# =====================================
# Handler Registry
# =====================================

NODE_HANDLERS: Dict[str, Type[BaseNodeHandler]] = {
    'webhookTrigger': WebhookTriggerHandler,
    'webhookNode': WebhookTriggerHandler,  # Legacy support
    'whatsappTrigger': WhatsAppTriggerHandler,
    'appointmentTrigger': AppointmentTriggerHandler,
    'crmStageTrigger': CrmStageTriggerHandler,
    'sendMessage': SendMessageHandler,
    'sendTelegramMessage': SendTelegramMessageHandler,
    'createLead': CreateLeadHandler,
    'agentResponse': AgentResponseHandler,
    'agentWorkforce': AgentWorkforceHandler,
    'delay': DelayHandler,
    'waitRelative': WaitRelativeHandler,
    'addTag': AddTagHandler,
    'moveCrmStage': MoveCrmStageHandler,
    'humanHandoff': HumanHandoffHandler,
    'tagFilter': TagFilterHandler,
    'condition': ConditionHandler,
}


def get_node_handler(node_type: str) -> Optional[BaseNodeHandler]:
    """
    Get a handler instance for the given node type.

    Args:
        node_type: The type of node

    Returns:
        Handler instance or None if not found
    """
    handler_class = NODE_HANDLERS.get(node_type)

    if handler_class:
        return handler_class()

    return None
