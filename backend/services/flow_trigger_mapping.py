"""Standard field mapping for FlowBuilder webhook triggers."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


WEBHOOK_MAPPING_CONFIG_KEY = "webhook_mapping"

MAPPING_KEY_ALIASES = {
    "lead_phone_path": ("lead_phone_path", "leadPhonePath", "phone_path", "phonePath"),
    "lead_name_path": ("lead_name_path", "leadNamePath", "name_path", "namePath"),
    "lead_email_path": ("lead_email_path", "leadEmailPath", "email_path", "emailPath"),
    "lead_id_path": ("lead_id_path", "leadIdPath"),
    "event_type_path": ("event_type_path", "eventTypePath"),
    "company_id_path": ("company_id_path", "companyIdPath"),
}

DEFAULT_PATHS = {
    "lead_phone_path": (
        "lead.phone",
        "lead.whatsapp",
        "client.phone",
        "client.whatsapp",
        "contact.phone",
        "contact.whatsapp",
        "body.lead.phone",
        "body.lead.whatsapp",
        "body.client.phone",
        "body.client.whatsapp",
        "body.contact.phone",
        "body.contact.whatsapp",
        "phone",
        "whatsapp",
        "telefone",
        "celular",
        "body.phone",
        "body.whatsapp",
        "body.telefone",
        "body.celular",
    ),
    "lead_name_path": (
        "lead.name",
        "lead.full_name",
        "client.name",
        "client.full_name",
        "contact.name",
        "contact.full_name",
        "body.lead.name",
        "body.lead.full_name",
        "body.client.name",
        "body.client.full_name",
        "body.contact.name",
        "body.contact.full_name",
        "name",
        "nome",
        "full_name",
        "nome_completo",
        "body.name",
        "body.nome",
        "body.full_name",
        "body.nome_completo",
    ),
    "lead_email_path": (
        "lead.email",
        "client.email",
        "contact.email",
        "body.lead.email",
        "body.client.email",
        "body.contact.email",
        "email",
        "e_mail",
        "body.email",
        "body.e_mail",
    ),
    "lead_id_path": (
        "lead.id",
        "lead.lead_id",
        "lead_id",
        "leadId",
        "body.lead.id",
        "body.lead.lead_id",
        "body.lead_id",
        "body.leadId",
    ),
    "event_type_path": (
        "event.type",
        "event_type",
        "eventType",
        "event",
        "type",
        "body.event.type",
        "body.event_type",
        "body.eventType",
        "body.event",
        "body.type",
    ),
    "company_id_path": (
        "company.id",
        "company_id",
        "companyId",
        "body.company.id",
        "body.company_id",
        "body.companyId",
    ),
}


def is_present_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (dict, list, tuple, set)):
        return len(value) > 0
    return True


def resolve_payload_path(payload: Any, path: str) -> Any:
    current = payload
    for part in str(path or "").split("."):
        if not part:
            return None
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
            continue
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
            continue
        return None
    return current


def _scalar_or_none(value: Any) -> Optional[Any]:
    if not is_present_value(value):
        return None
    if isinstance(value, (dict, list, tuple, set)):
        return None
    return value


def _get_configured_mapping(trigger_config: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not isinstance(trigger_config, dict):
        return {}

    raw_mapping = trigger_config.get(WEBHOOK_MAPPING_CONFIG_KEY) or trigger_config.get("webhookMapping")
    if not isinstance(raw_mapping, dict):
        raw_mapping = trigger_config

    out: Dict[str, str] = {}
    for canonical_key, aliases in MAPPING_KEY_ALIASES.items():
        for alias in aliases:
            value = raw_mapping.get(alias)
            if isinstance(value, str) and value.strip():
                out[canonical_key] = value.strip()
                break
    return out


def _resolve_first_path(
    payload: Dict[str, Any],
    configured_path: Optional[str],
    default_paths: Iterable[str],
) -> Optional[Any]:
    paths = []
    if configured_path:
        paths.append(configured_path)
    paths.extend(default_paths)

    seen = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        value = _scalar_or_none(resolve_payload_path(payload, path))
        if value is not None:
            return value
    return None


def resolve_standard_webhook_fields(
    trigger_payload: Dict[str, Any],
    trigger_config: Optional[Dict[str, Any]] = None,
    company_id: Optional[int] = None,
) -> Dict[str, Dict[str, Any]]:
    """Resolve standard aliases like lead.phone from a webhook payload."""

    mapping = _get_configured_mapping(trigger_config)

    lead: Dict[str, Any] = {}
    lead_phone = _resolve_first_path(
        trigger_payload,
        mapping.get("lead_phone_path"),
        DEFAULT_PATHS["lead_phone_path"],
    )
    if lead_phone is not None:
        lead["phone"] = lead_phone

    lead_name = _resolve_first_path(
        trigger_payload,
        mapping.get("lead_name_path"),
        DEFAULT_PATHS["lead_name_path"],
    )
    if lead_name is not None:
        lead["name"] = lead_name

    lead_email = _resolve_first_path(
        trigger_payload,
        mapping.get("lead_email_path"),
        DEFAULT_PATHS["lead_email_path"],
    )
    if lead_email is not None:
        lead["email"] = lead_email

    lead_id = _resolve_first_path(
        trigger_payload,
        mapping.get("lead_id_path"),
        DEFAULT_PATHS["lead_id_path"],
    )
    if lead_id is not None:
        lead["id"] = lead_id

    event: Dict[str, Any] = {}
    event_type = _resolve_first_path(
        trigger_payload,
        mapping.get("event_type_path"),
        DEFAULT_PATHS["event_type_path"],
    )
    if event_type is not None:
        event["type"] = event_type

    company: Dict[str, Any] = {}
    configured_company_id = _resolve_first_path(
        trigger_payload,
        mapping.get("company_id_path"),
        DEFAULT_PATHS["company_id_path"],
    )
    if configured_company_id is not None:
        company["id"] = configured_company_id
    elif company_id is not None:
        company["id"] = company_id

    return {
        "lead": lead,
        "event": event,
        "company": company,
    }


def merge_standard_fields_into_trigger(
    trigger_payload: Dict[str, Any],
    standard_fields: Dict[str, Dict[str, Any]],
) -> None:
    """Expose standard field groups on the trigger without dropping raw payload values."""

    for group_key in ("lead", "company"):
        resolved_group = standard_fields.get(group_key) or {}
        existing_group = (
            trigger_payload.get(group_key)
            if isinstance(trigger_payload.get(group_key), dict)
            else {}
        )
        merged_group = {**existing_group, **resolved_group}
        if merged_group:
            trigger_payload[group_key] = merged_group

    event_group = standard_fields.get("event") or {}
    if event_group:
        existing_event = trigger_payload.get("event")
        if isinstance(existing_event, dict):
            trigger_payload["event"] = {**existing_event, **event_group}
        trigger_payload["event_data"] = {
            **(
                trigger_payload.get("event_data")
                if isinstance(trigger_payload.get("event_data"), dict)
                else {}
            ),
            **event_group,
        }
