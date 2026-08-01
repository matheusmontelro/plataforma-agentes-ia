"""
Flow Execution Service for WAHA Integration

This service handles the execution of FlowBuilder flows when triggered
by incoming WhatsApp messages via WAHA.
"""

import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from backend.models import AgentWorkforce, Flow
from backend.services.flow_agent_workforce_runner import run_agent_workforce_response

logger = logging.getLogger(__name__)

MAX_AGENT_RESPONSE_DELAY_SECONDS = 60
DEFAULT_AGENT_RESPONSE_DELAY_SECONDS = 15


def _response_delay_seconds_from_settings(settings: Dict[str, Any]) -> int:
    agent_context = (
        settings.get("agent_context")
        if isinstance(settings.get("agent_context"), dict)
        else {}
    )
    performance = (
        agent_context.get("performance")
        if isinstance(agent_context.get("performance"), dict)
        else {}
    )
    raw_value = performance.get("response_delay_seconds")
    if raw_value is None or raw_value == "":
        raw_value = DEFAULT_AGENT_RESPONSE_DELAY_SECONDS
    try:
        value = int(round(float(raw_value)))
    except (TypeError, ValueError):
        value = 0
    return max(0, min(MAX_AGENT_RESPONSE_DELAY_SECONDS, value))


def find_active_whatsapp_flow(db: Session, company_id: int) -> Optional[Flow]:
    """
    Finds an active flow with trigger_type='whatsapp' for the given company.

    Args:
        db: Database session
        company_id: ID of the company

    Returns:
        Flow object if found, None otherwise
    """
    flow = db.query(Flow).filter(
        Flow.company_id == company_id,
        Flow.is_active == True,
        Flow.trigger_type == 'whatsapp'
    ).first()

    if flow:
        logger.info(f"[FlowExecutor] Found active WhatsApp flow: {flow.id} - {flow.name}")
    else:
        logger.debug(f"[FlowExecutor] No active WhatsApp flow found for company {company_id}")

    return flow


def get_active_whatsapp_agent_workforce_context(
    db: Session,
    company_id: int,
) -> Optional[Dict[str, Any]]:
    """Return the AgentWorkforce attached to the active WhatsApp flow, if any."""

    flow = find_active_whatsapp_flow(db, company_id)
    if not flow:
        return None

    agent_workforce_node = None
    for node in flow.nodes or []:
        if node.get("type") == "agentWorkforce":
            agent_workforce_node = node
            break

    if not agent_workforce_node:
        return None

    node_data = agent_workforce_node.get("data") or {}
    try:
        workforce_id = int(node_data.get("workforceId") or 0)
    except (TypeError, ValueError):
        workforce_id = 0

    if workforce_id <= 0:
        return None

    workforce = (
        db.query(AgentWorkforce)
        .filter(
            AgentWorkforce.id == workforce_id,
            AgentWorkforce.company_id == company_id,
        )
        .first()
    )
    if not workforce:
        return None

    return {
        "flow_id": flow.id,
        "flow_name": flow.name,
        "workforce_id": workforce.id,
        "workforce_name": workforce.name,
        "node_id": agent_workforce_node.get("id"),
        "response_delay_seconds": _response_delay_seconds_from_settings(
            workforce.settings or {}
        ),
    }


def execute_whatsapp_flow(
    db: Session,
    flow: Flow,
    trigger_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Executes a WhatsApp-triggered flow with the given trigger data.

    Args:
        db: Database session
        flow: The Flow object to execute
        trigger_data: Data from the incoming WhatsApp message containing:
            - phone: Sender's phone number
            - name: Sender's name
            - body: Message text
            - type: Message type (text, image, audio, video)
            - mediaUrl: URL for media (if applicable)
            - timestamp: Message timestamp

    Returns:
        Dict with execution results including the agent's response
    """
    logger.info(f"[FlowExecutor] Executing flow {flow.id} with trigger data")

    nodes = flow.nodes or []

    # Build execution context from trigger
    context = {
        "trigger": trigger_data
    }

    # Find nodes by type
    whatsapp_trigger_node = None
    agent_workforce_node = None

    for node in nodes:
        node_type = node.get('type', '')
        if node_type == 'whatsappTrigger':
            whatsapp_trigger_node = node
        elif node_type == 'agentWorkforce':
            agent_workforce_node = node

    if not whatsapp_trigger_node:
        logger.warning(f"[FlowExecutor] Flow {flow.id} has no whatsappTrigger node")
        return {"success": False, "error": "Flow has no WhatsApp trigger node"}

    if not agent_workforce_node:
        logger.warning(f"[FlowExecutor] Flow {flow.id} has no AgentWorkforce node")
        return {
            "success": False,
            "error": "WhatsApp flows must use an AgentWorkforce node",
            "context": context,
        }

    node_data = agent_workforce_node.get('data', {})
    workforce_id = node_data.get('workforceId')
    if not workforce_id:
        logger.warning(f"[FlowExecutor] AgentWorkforce node has no workforceId configured")
        return {
            "success": False,
            "error": "AgentWorkforce node has no workforceId configured",
            "context": context,
        }

    message_template = node_data.get('inputMessage') or '{{trigger.body}}'
    message = trigger_data.get('body', '')
    if message_template and message_template != '{{trigger.body}}':
        message = message_template.replace('{{trigger.body}}', trigger_data.get('body', ''))
        message = message.replace('{{trigger.name}}', trigger_data.get('name', ''))
        message = message.replace('{{trigger.phone}}', trigger_data.get('phone', ''))

    if not message and trigger_data.get('type') == 'audio':
        message = "[Mensagem de áudio recebida]"

    logger.info(f"[FlowExecutor] Executing workforce {workforce_id} with message: {message[:100]}...")

    workforce_result = run_agent_workforce_response(
        db=db,
        workforce_id=int(workforce_id),
        company_id=flow.company_id,
        message=message,
        runtime_variables=context,
        flow_id=flow.id,
        node_id=agent_workforce_node.get('id'),
        provider_message_id=trigger_data.get('messageId') or trigger_data.get('id'),
    )

    if workforce_result.get('success'):
        context['agent_workforce'] = {
            'response': workforce_result.get('response', ''),
            'tokens_used': workforce_result.get('tokens_used', 0),
            'workforce_id': workforce_result.get('workforce_id'),
            'workforce_name': workforce_result.get('workforce_name'),
            'root_agent_key': workforce_result.get('root_agent_key'),
            'root_agent_name': workforce_result.get('root_agent_name'),
            'handoff_target': workforce_result.get('handoff_target'),
            'last_agent_key': workforce_result.get('last_agent_key'),
            'last_agent_name': workforce_result.get('last_agent_name'),
            'audio': workforce_result.get('audio'),
            'should_send_audio': bool(workforce_result.get('should_send_audio')),
            'audio_trigger': workforce_result.get('audio_trigger'),
            'audio_delivery_mode': workforce_result.get('audio_delivery_mode'),
            'audio_text_intro': workforce_result.get('audio_text_intro'),
            'audio_text': workforce_result.get('audio_text'),
            'audio_split_parts': workforce_result.get('audio_split_parts', []),
            'voice_used': workforce_result.get('voice_used'),
            'voice_provider': workforce_result.get('voice_provider'),
            'voice_model': workforce_result.get('voice_model'),
            'audio_error': workforce_result.get('audio_error'),
            'metadata': workforce_result.get('metadata', {}),
        }
        context['agent'] = {
            'response': workforce_result.get('response', ''),
            'tokens_used': workforce_result.get('tokens_used', 0)
        }
        logger.info(f"[FlowExecutor] Workforce response generated: {len(workforce_result.get('response', ''))} chars")
    else:
        logger.error(f"[FlowExecutor] Workforce execution failed: {workforce_result.get('error')}")
        from backend.services.ai_credit_guard import is_ai_credit_block_result

        return {
            "success": False,
            "error": workforce_result.get('error'),
            "context": context,
            "blocked_by_ai_credits": is_ai_credit_block_result(workforce_result),
            "blocked_by_schedule": bool(workforce_result.get("blocked_by_schedule")),
            "workforce_status": workforce_result.get("workforce_status"),
        }

    return {
        "success": True,
        "context": context,
        "flow_id": flow.id,
        "flow_name": flow.name
    }


def execute_flow_message(
    db: Session,
    company_id: int,
    message_data: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Execute an active WhatsApp flow and let explicit action nodes decide outputs.

    This is the production path for WAHA messages. Agent nodes only populate
    variables such as {{agent_workforce.response}}; WhatsApp delivery must happen
    through a connected sendMessage node.
    """
    flow = find_active_whatsapp_flow(db, company_id)
    if not flow:
        return None

    trigger_data = {
        "phone": message_data.get('phone', ''),
        "name": message_data.get('name', ''),
        "body": message_data.get('body', message_data.get('text', '')),
        "type": message_data.get('type', 'text'),
        "mediaUrl": message_data.get('mediaUrl', ''),
        "timestamp": message_data.get('timestamp', ''),
        "messageId": message_data.get('messageId') or message_data.get('id'),
    }
    for key in (
        "caption",
        "mimetype",
        "image",
        "images",
        "debounced_images",
        "debounced_messages",
        "debounced_message_count",
        "response_delay_already_waited",
        "_operational_epoch",
    ):
        if key in message_data:
            trigger_data[key] = message_data[key]

    from backend.services.flow_executor import FlowExecutor

    executor = FlowExecutor(
        flow_id=flow.id,
        company_id=company_id,
        trigger_data=trigger_data,
        trigger_type='whatsapp',
    )
    result = executor.execute()
    result["flow_id"] = flow.id
    result["flow_name"] = flow.name
    return result
