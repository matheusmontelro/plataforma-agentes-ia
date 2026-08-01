import os
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/agentive-flow-executor-vars-test.db")

from backend.services.flow_executor import FlowExecutor  # noqa: E402
from backend.services.flow_node_handlers import WebhookTriggerHandler  # noqa: E402


def test_webhook_payload_without_body_exposes_body_alias():
    payload = {
        "event": "registration.created",
        "client": {
            "phone": "5500000000004",
            "full_name": "Lead Teste",
        },
    }

    executor = FlowExecutor(
        flow_id=10,
        company_id=3,
        trigger_data=payload,
        trigger_type="webhook",
    )
    executor._init_trigger_variables()

    assert "body" not in payload
    assert executor.variables["trigger"]["client"]["phone"] == "5500000000004"
    assert executor.variables["trigger"]["body"]["client"]["phone"] == "5500000000004"
    assert executor.variables["body"]["client"]["phone"] == "5500000000004"
    assert executor.variables["lead"]["phone"] == "5500000000004"
    assert executor.variables["phone"] == "5500000000004"
    assert executor.variables["lead"]["name"] == "Lead Teste"
    assert executor.variables["name"] == "Lead Teste"
    assert executor.variables["event_type"] == "registration.created"
    assert executor.variables["company"]["id"] == 3


def test_webhook_payload_with_existing_body_keeps_existing_body():
    payload = {
        "client": {"phone": "top-level-phone"},
        "body": {"client": {"phone": "body-phone"}},
    }

    executor = FlowExecutor(
        flow_id=10,
        company_id=3,
        trigger_data=payload,
        trigger_type="webhook",
    )
    executor._init_trigger_variables()

    assert executor.variables["trigger"]["client"]["phone"] == "top-level-phone"
    assert executor.variables["trigger"]["body"]["client"]["phone"] == "body-phone"


def test_webhook_mapping_config_overrides_autodetection():
    payload = {
        "client": {"phone": "client-phone"},
        "contact": {"phone": "contact-phone", "full_name": "Contato"},
        "event": "registration.created",
        "event_data": {"type": "legacy.event"},
    }

    executor = FlowExecutor(
        flow_id=10,
        company_id=3,
        trigger_data=payload,
        trigger_type="webhook",
    )
    executor.flow = SimpleNamespace(
        trigger_config={
            "webhook_mapping": {
                "lead_phone_path": "contact.phone",
                "lead_name_path": "contact.full_name",
                "event_type_path": "event",
            }
        }
    )
    executor._init_trigger_variables()

    assert executor.variables["lead"]["phone"] == "contact-phone"
    assert executor.variables["phone"] == "contact-phone"
    assert executor.variables["lead"]["name"] == "Contato"
    assert executor.variables["event_type"] == "registration.created"
    assert executor.variables["event_data"]["type"] == "registration.created"


def test_node_handlers_resolve_standard_event_type_alias():
    variables = {
        "event": "registration.created",
        "event_data": {"type": "registration.created"},
    }

    resolved = WebhookTriggerHandler().resolve_variables("{{event.type}}", variables)

    assert resolved == "registration.created"


def test_whatsapp_trigger_exposes_standard_lead_phone_alias():
    payload = {
        "phone": "5500000000007",
        "name": "Ana",
        "body": "Oi",
    }

    executor = FlowExecutor(
        flow_id=8,
        company_id=7,
        trigger_data=payload,
        trigger_type="whatsapp",
    )
    executor._init_trigger_variables()

    assert executor.variables["lead"]["phone"] == "5500000000007"
    assert executor.variables["lead"]["name"] == "Ana"
    assert executor.variables["phone"] == "5500000000007"
    assert executor.variables["company"]["id"] == 7
