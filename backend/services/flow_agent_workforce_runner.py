"""
Run AgentWorkforce definitions from FlowBuilder.

This is the bridge between the visual workforce created in /agents and the
FlowBuilder runtime. Workforces are executed with the OpenAI Agents SDK so
handoffs, tool calls, guardrails, and model calls show up in structured traces.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import re
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, time as datetime_time
from decimal import Decimal
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agents import (
    Agent,
    FileSearchTool,
    InputGuardrailTripwireTriggered,
    OutputGuardrailTripwireTriggered,
    Runner,
    WebSearchTool,
)
from openai.types.responses.web_search_tool import Filters as WebSearchFilters
from sqlalchemy.orm import Session

from backend.agents_sdk.agent_builder import (
    AgentConfigCompiler,
    AgentCreationConfig,
    AgentRuntimeRegistry,
    DEFAULT_PROMPT_SAFETY_BLOCK_MESSAGE,
)
from backend.agents_sdk.voice import AudioRequest, AudioResponse, AudioService
from backend.agents_sdk.voice.triggers import AudioTriggers
from backend.agents_sdk.database import AgentExecution
from backend.models import AgentWorkforce, Message
from backend.prompt.media.image_analysis import (
    analyze_image_with_google_vision,
    analyze_image_with_openai,
    build_openai_image_input_part,
)
from backend.services.ai_usage_service import (
    extract_openai_usage,
    safe_record_openai_text_usage,
    safe_record_tts_usage,
)
from backend.services.ai_credit_guard import (
    ai_credit_block_result_from_balance,
    get_ai_credit_balance,
)
from backend.services.ai_provider_service import (
    build_company_openai_run_config,
    get_company_openai_api_key,
    openai_run_trace,
    safe_ai_provider_runtime_error,
)

logger = logging.getLogger(__name__)

MAX_AGENT_RESPONSE_DELAY_SECONDS = 60
DEFAULT_AGENT_RESPONSE_DELAY_SECONDS = 15
DEFAULT_WORKFORCE_SCHEDULE_TIMEZONE = "America/Sao_Paulo"
WORKFORCE_SCHEDULE_MODE_ALWAYS_ON = "always_on"
WORKFORCE_SCHEDULE_MODE_CUSTOM = "custom"
WORKFORCE_SCHEDULE_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
WORKFORCE_SCHEDULE_DAY_ALIASES = {
    "segunda": "monday",
    "segunda-feira": "monday",
    "terca": "tuesday",
    "terça": "tuesday",
    "terça-feira": "tuesday",
    "quarta": "wednesday",
    "quarta-feira": "wednesday",
    "quinta": "thursday",
    "quinta-feira": "thursday",
    "sexta": "friday",
    "sexta-feira": "friday",
    "sabado": "saturday",
    "sábado": "saturday",
    "domingo": "sunday",
}
WORKFORCE_SCHEDULE_PERIODS = ("morning", "afternoon", "night", "dawn")
AUTO_AUDIO_TAIL_MIN_CHARS = 180
AUDIO_GENERATION_FAILURE_FALLBACK_PREFIX = (
    "No momento não consegui te responder em áudio, mas respondendo sua pergunta:"
)
AUDIO_LINK_BLOCKED_ERROR = "Audio blocked because text contains link"
AUDIO_HISTORY_TRANSCRIPT_LOOKBACK_SECONDS = 600
AUDIO_HISTORY_TRANSCRIPT_FORWARD_SECONDS = 30
AUDIO_HISTORY_TRANSCRIPT_MAX_CHARS = 2000
CALENDAR_FIND_TOOL_NAME = "find_available_lead_slots"
CALENDAR_MUTATION_TOOL_NAMES = {
    "create_lead_appointment",
    "reschedule_lead_appointment",
    "cancel_lead_appointment",
}
CALENDAR_TOOL_NAMES = {CALENDAR_FIND_TOOL_NAME, *CALENDAR_MUTATION_TOOL_NAMES}
CALENDAR_LOOKUP_FAILURE_MARKERS = (
    "agenda esta instavel",
    "agenda instavel",
    "assim que normalizar",
    "estou com uma instabilidade",
    "instabilidade para consultar",
    "nao consegui consultar",
    "nao foi possivel consultar",
    "tentei puxar os horarios",
)
AGENT_CONFIG_AUDIO_RULE_PATTERNS = (
    "audio a ser enviado",
    "conteudo do audio",
    "deve enviar audio",
    "deve enviar um audio",
    "deve mandar audio",
    "envia o audio",
    "envia um audio",
    "enviar o audio",
    "envie o audio",
    "envie um audio",
    "mande o audio",
    "mande um audio",
    "mandar o audio",
    "responda em audio",
    "responder em audio",
    "tem que enviar audio",
    "tem que enviar um audio",
    "tem que mandar audio",
)
AGENT_CONFIG_AUDIO_NEGATION_PATTERNS = (
    "apenas texto",
    "nao enviar audio",
    "nao envie audio",
    "nunca enviar audio",
    "nunca envie audio",
    "sem audio",
    "somente texto",
)
AGENT_CONFIG_AUDIO_RESPONSE_MARKERS = (
    "[audio enviado]",
    "[audio enviada]",
    "audio enviado",
    "audio enviada",
    "audio enviado pela empresa",
    "audio enviada pela empresa",
    "aqui esta o audio",
    "aqui vai o audio",
    "segue o audio",
    "vou enviar audio",
    "vou enviar o audio",
    "vou mandar audio",
    "vou mandar o audio",
    "vou te enviar audio",
    "vou te enviar o audio",
    "vou te enviar um audio",
    "vou te mandar audio",
    "vou te mandar o audio",
    "vou te mandar um audio",
    "enviar audio agora",
    "enviar o audio agora",
    "enviar um audio agora",
    "mandar audio agora",
    "mandar o audio agora",
    "mandar um audio agora",
)
AGENT_RESPONSE_AUDIO_PROMISE_PATTERNS = (
    "explicar em audio",
    "explico em audio",
    "explico por audio",
    "te explicar em audio",
    "te explicar por audio",
    "te explico em audio",
    "te explico por audio",
    "vou explicar em audio",
    "vou explicar por audio",
    "vou te explicar em audio",
    "vou te explicar por audio",
)
AGENT_RESPONSE_AUDIO_OFFER_PATTERNS = (
    "posso enviar audio",
    "posso enviar o audio",
    "posso enviar um audio",
    "posso mandar audio",
    "posso mandar o audio",
    "posso mandar um audio",
    "posso te enviar audio",
    "posso te enviar o audio",
    "posso te enviar um audio",
    "posso te mandar audio",
    "posso te mandar o audio",
    "posso te mandar um audio",
    "quer que eu envie audio",
    "quer que eu envie o audio",
    "quer que eu envie um audio",
    "quer que eu mande audio",
    "quer que eu mande o audio",
    "quer que eu mande um audio",
    "quer que eu te envie audio",
    "quer que eu te envie o audio",
    "quer que eu te envie um audio",
    "quer que eu te mande audio",
    "quer que eu te mande o audio",
    "quer que eu te mande um audio",
)
AGENT_RESPONSE_AUDIO_NEGATION_PATTERNS = (
    "nao enviar audio",
    "nao enviar o audio",
    "nao enviar um audio",
    "nao mande audio",
    "nao mandar audio",
    "nao posso enviar audio",
    "nao posso mandar audio",
    "nao vou enviar audio",
    "nao vou mandar audio",
    "sem audio",
)
TEXT_DELIVERY_PATTERNS = (
    "apenas em texto",
    "apenas texto",
    "em texto",
    "explicar por texto",
    "explico por texto",
    "por mensagem",
    "por texto",
    "responder em texto",
    "responder por texto",
    "respondo em texto",
    "respondo por texto",
    "somente em texto",
    "somente texto",
    "te explicar por texto",
    "te explico por texto",
    "texto mesmo",
    "via mensagem",
    "via texto",
    "vou explicar por texto",
    "vou responder em texto",
    "vou responder por texto",
    "vou te explicar por texto",
)
USER_DELIVERY_ACCEPTANCE_PATTERNS = (
    "beleza",
    "claro",
    "manda",
    "manda sim",
    "ok",
    "okay",
    "pode",
    "pode mandar",
    "pode sim",
    "quero",
    "quero sim",
    "sim",
    "ta bom",
    "tudo bem",
)
AGENT_CONFIG_AUDIO_ALWAYS_PATTERNS = (
    "responda sempre em audio",
    "responder sempre em audio",
    "sempre enviar audio",
    "sempre mande audio",
    "somente audio",
    "so audio",
)
LONG_DASH_PATTERN = re.compile(r"[ \t]*[\u2013\u2014][ \t]*")
MARKDOWN_LINK_PATTERN = re.compile(
    r"(?<!!)\[([^\]\n]+)\]\(((?:https?://|www\.)[^)\s]+)\)",
    flags=re.IGNORECASE,
)
AUDIO_BLOCKED_LINK_PATTERN = re.compile(r"(?:https?://|www\.)\S+", flags=re.IGNORECASE)
AUDIO_CAPABILITY_REFUSAL_PATTERNS = (
    "nao consigo enviar audio",
    "nao consigo mandar audio",
    "nao consigo gravar audio",
    "nao posso enviar audio",
    "nao posso mandar audio",
    "nao tenho capacidade de enviar audio",
    "nao tenho como enviar audio",
    "sou apenas um assistente de texto",
    "sou uma ia de texto",
    "apenas por texto",
    "somente por texto",
    "i cannot send audio",
    "i can't send audio",
    "i am unable to send audio",
)
FALSE_CUSTOMER_FILE_REFERENCE_PATTERNS = (
    (
        r"\b(?:arquivo|arquivos|documento|documentos|anexo|anexos|pdf|pdfs)"
        r"\s+que\s+(?:voce|vc|voces)\s+"
        r"(?:enviou|mandou|anexou|compartilhou|encaminhou|subiu)"
    ),
    (
        r"\b(?:arquivo|arquivos|documento|documentos|anexo|anexos|pdf|pdfs)"
        r"\s+(?:enviado|enviados|mandado|mandados|anexado|anexados|"
        r"compartilhado|compartilhados|encaminhado|encaminhados)"
        r"\s+(?:por|pel[ao])\s+(?:voce|vc|voces)"
    ),
    (
        r"\b(?:seu|seus|sua|suas)\s+"
        r"(?:arquivo|arquivos|documento|documentos|anexo|anexos|pdf|pdfs)"
        r"\s+(?:enviado|enviados|mandado|mandados|anexado|anexados|"
        r"compartilhado|compartilhados)"
    ),
)
CUSTOMER_FILE_MESSAGE_TYPES = (
    "file",
    "document",
    "documento",
    "attachment",
    "anexo",
)
CUSTOMER_FILE_PAYLOAD_KEYS = (
    "file",
    "files",
    "document",
    "documents",
    "attachment",
    "attachments",
)
GREETING_ONLY_MESSAGES = (
    "bom dia",
    "boa noite",
    "boa tarde",
    "ei",
    "hello",
    "hey",
    "hi",
    "ola",
    "oi",
    "opa",
)


@dataclass(frozen=True)
class AgentAudioDeliveryPlan:
    request_text: str
    trigger_type: str
    delivery_mode: str
    text_intro: Optional[str] = None
    split_parts: List[str] = field(default_factory=list)


@dataclass
class AgentWorkforceRunContext:
    company_id: int
    workforce_id: int
    workforce_name: str
    root_agent_key: str
    flow_id: Optional[int] = None
    node_id: Optional[str] = None
    channel: str = "whatsapp"
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    current_stage: Optional[str] = None
    conversation_step: Optional[str] = None
    latest_user_message: str = ""
    organization_data: Dict[str, Any] = field(default_factory=dict)
    structured_context: Any = None
    human_handoff_task: Optional[Dict[str, Any]] = None
    suppress_whatsapp_send: bool = False
    audio_delivery_request: Optional[Dict[str, Any]] = None
    audio_delivery_tool_calls: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class CompiledWorkforce:
    agents_by_key: Dict[str, Agent[Any]]
    configs_by_key: Dict[str, AgentCreationConfig]
    root_agent: Agent[Any]
    root_agent_key: str
    warnings: List[str]


def _default_workforce_schedule_days() -> Dict[str, Any]:
    days: Dict[str, Any] = {}
    for day in WORKFORCE_SCHEDULE_WEEKDAYS:
        weekday = day not in {"saturday", "sunday"}
        days[day] = {
            "enabled": weekday,
            "periods": {
                "morning": {"enabled": weekday, "start": "08:00", "end": "12:00"},
                "afternoon": {"enabled": weekday, "start": "13:00", "end": "18:00"},
                "night": {"enabled": False, "start": "18:00", "end": "23:59"},
                "dawn": {"enabled": False, "start": "00:00", "end": "06:00"},
            },
        }
    return days


def _normalize_schedule_day_key(day_key: Any) -> str:
    key = str(day_key or "").strip().lower()
    if key in WORKFORCE_SCHEDULE_WEEKDAYS:
        return key
    return WORKFORCE_SCHEDULE_DAY_ALIASES.get(key, "")


def _normalize_schedule_time(value: Any, fallback: str) -> str:
    raw = str(value or fallback).strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}", raw):
        return fallback
    hour_str, minute_str = raw.split(":", 1)
    hour = int(hour_str)
    minute = int(minute_str)
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return fallback
    return f"{hour:02d}:{minute:02d}"


def _parse_schedule_time(value: str) -> Optional[datetime_time]:
    try:
        hour_str, minute_str = value.split(":", 1)
        return datetime_time(hour=int(hour_str), minute=int(minute_str))
    except Exception:
        return None


def _period_config_from_day(day_config: Dict[str, Any], period_key: str) -> Dict[str, Any]:
    nested_periods = day_config.get("periods")
    if isinstance(nested_periods, dict) and isinstance(nested_periods.get(period_key), dict):
        return nested_periods[period_key]
    direct_period = day_config.get(period_key)
    return direct_period if isinstance(direct_period, dict) else {}


def _normalize_workforce_schedule(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize the global AgentWorkforce service schedule.

    Missing settings intentionally mean 24h service so existing active teams
    keep responding after the legacy ai_response_windows gate is removed.
    """

    settings = settings if isinstance(settings, dict) else {}
    agent_context = settings.get("agent_context") if isinstance(settings.get("agent_context"), dict) else {}
    raw_schedule = agent_context.get("schedule")
    if not isinstance(raw_schedule, dict):
        raw_schedule = settings.get("schedule") if isinstance(settings.get("schedule"), dict) else {}

    defaults = {
        "mode": WORKFORCE_SCHEDULE_MODE_ALWAYS_ON,
        "timezone": DEFAULT_WORKFORCE_SCHEDULE_TIMEZONE,
        "days": _default_workforce_schedule_days(),
    }

    mode = raw_schedule.get("mode")
    if mode not in {WORKFORCE_SCHEDULE_MODE_ALWAYS_ON, WORKFORCE_SCHEDULE_MODE_CUSTOM}:
        mode = WORKFORCE_SCHEDULE_MODE_ALWAYS_ON

    timezone_name = str(raw_schedule.get("timezone") or defaults["timezone"]).strip()
    if not timezone_name:
        timezone_name = defaults["timezone"]

    raw_days = raw_schedule.get("days") if isinstance(raw_schedule.get("days"), dict) else {}
    normalized_days: Dict[str, Any] = {}
    for day_key in WORKFORCE_SCHEDULE_WEEKDAYS:
        default_day = defaults["days"][day_key]
        source_day = raw_days.get(day_key)
        if not isinstance(source_day, dict):
            for raw_key, raw_value in raw_days.items():
                if _normalize_schedule_day_key(raw_key) == day_key and isinstance(raw_value, dict):
                    source_day = raw_value
                    break
        if not isinstance(source_day, dict):
            source_day = {}

        periods: Dict[str, Any] = {}
        for period_key in WORKFORCE_SCHEDULE_PERIODS:
            default_period = default_day["periods"][period_key]
            source_period = _period_config_from_day(source_day, period_key)
            periods[period_key] = {
                "enabled": bool(source_period.get("enabled", default_period["enabled"])),
                "start": _normalize_schedule_time(source_period.get("start"), default_period["start"]),
                "end": _normalize_schedule_time(source_period.get("end"), default_period["end"]),
            }

        normalized_days[day_key] = {
            "enabled": bool(source_day.get("enabled", default_day["enabled"])),
            "periods": periods,
        }

    return {
        "mode": mode,
        "timezone": timezone_name,
        "days": normalized_days,
    }


def _is_workforce_schedule_open(
    schedule: Dict[str, Any],
    now: Optional[datetime] = None,
) -> bool:
    if schedule.get("mode") != WORKFORCE_SCHEDULE_MODE_CUSTOM:
        return True

    timezone_name = schedule.get("timezone") or DEFAULT_WORKFORCE_SCHEDULE_TIMEZONE
    try:
        local_tz = ZoneInfo(str(timezone_name))
    except ZoneInfoNotFoundError:
        logger.warning(
            "[AgentWorkforce] Invalid schedule timezone '%s'; using %s",
            timezone_name,
            DEFAULT_WORKFORCE_SCHEDULE_TIMEZONE,
        )
        local_tz = ZoneInfo(DEFAULT_WORKFORCE_SCHEDULE_TIMEZONE)

    local_now = now or datetime.now(local_tz)
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=local_tz)
    else:
        local_now = local_now.astimezone(local_tz)

    day_key = WORKFORCE_SCHEDULE_WEEKDAYS[local_now.weekday()]
    day_config = (schedule.get("days") or {}).get(day_key) or {}
    if not day_config.get("enabled", False):
        return False

    current_time = local_now.time().replace(second=0, microsecond=0)
    for period in (day_config.get("periods") or {}).values():
        if not isinstance(period, dict) or not period.get("enabled"):
            continue
        start = _parse_schedule_time(str(period.get("start") or ""))
        end = _parse_schedule_time(str(period.get("end") or ""))
        if not start or not end:
            continue
        if start < end and start <= current_time < end:
            return True
        if start >= end and (current_time >= start or current_time < end):
            return True

    return False


def run_agent_workforce_response(
    db: Session,
    workforce_id: int,
    company_id: int,
    message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    runtime_variables: Optional[Dict[str, Any]] = None,
    allow_inactive: bool = False,
    flow_id: Optional[int] = None,
    node_id: Optional[str] = None,
    provider_message_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a saved AgentWorkforce with the OpenAI Agents SDK."""

    credit_block = ai_credit_block_result_from_balance(
        db=db,
        company_id=company_id,
        source="agent_workforce",
    )
    if credit_block:
        credit_block.update({
            "workforce_id": workforce_id,
            "tokens_used": 0,
            "should_send_audio": False,
        })
        return credit_block

    workforce = (
        db.query(AgentWorkforce)
        .filter(
            AgentWorkforce.id == workforce_id,
            AgentWorkforce.company_id == company_id,
        )
        .first()
    )

    if not workforce:
        return {
            "success": False,
            "response": "",
            "error": f"Agent workforce {workforce_id} not found",
        }

    if workforce.status != "active" and not allow_inactive:
        return {
            "success": False,
            "response": "",
            "error": f"Agent workforce is {workforce.status}; only active workforces can execute",
            "workforce_id": workforce.id,
            "workforce_name": workforce.name,
            "workforce_status": workforce.status,
        }

    schedule = _normalize_workforce_schedule(workforce.settings or {})
    if not _is_workforce_schedule_open(schedule):
        logger.info(
            "[AgentWorkforce] Workforce %s blocked by custom schedule timezone=%s",
            workforce.id,
            schedule.get("timezone"),
        )
        return {
            "success": False,
            "response": "",
            "error": "Agent workforce outside configured schedule",
            "workforce_id": workforce.id,
            "workforce_name": workforce.name,
            "workforce_status": workforce.status,
            "blocked_by_schedule": True,
            "schedule_mode": schedule.get("mode"),
            "schedule_timezone": schedule.get("timezone"),
        }

    agent_configs = workforce.agent_configs or {}
    root_agent_key = workforce.root_agent_key or next(iter(agent_configs.keys()), None)

    if not root_agent_key or root_agent_key not in agent_configs:
        return {
            "success": False,
            "response": "",
            "error": "Agent workforce has no root agent configured",
            "workforce_id": workforce.id,
            "workforce_name": workforce.name,
        }

    try:
        run_config = build_company_openai_run_config(
            db,
            company_id,
            tracing_disabled=True,
            model_override=None,
        )
        runtime_variables_for_run = runtime_variables or {}
        configured_response_delay_seconds = _response_delay_seconds(workforce.settings or {})
        response_delay_seconds = (
            0
            if _response_delay_already_waited(runtime_variables_for_run)
            else configured_response_delay_seconds
        )
        runtime_context = _build_runtime_context(
            runtime_variables_for_run,
            message,
            company_id=company_id,
            workforce=workforce,
            root_agent_key=root_agent_key,
            flow_id=flow_id,
            node_id=node_id,
        )
        history_source = "provided"
        if conversation_history is None:
            conversation_history = _load_recent_conversation_history(
                db=db,
                company_id=company_id,
                contact_phone=runtime_context.contact_phone,
                current_message=message,
            )
            history_source = "database" if conversation_history else "none"
        else:
            conversation_history = _normalize_conversation_history(conversation_history)
        debounced_messages = _debounced_message_texts(runtime_variables_for_run)
        if debounced_messages:
            conversation_history = _drop_debounced_messages_from_history(
                conversation_history,
                debounced_messages,
            )

        compiled = _compile_workforce_agents(
            agent_configs,
            root_agent_key,
            company_id=company_id,
            workforce_settings=workforce.settings or {},
            latest_user_message=message,
        )
        root_config = compiled.configs_by_key[root_agent_key]
        input_guardrail = _evaluate_custom_guardrails(root_config, "input", message)
        trace_context = _build_trace_context(
            workforce=workforce,
            company_id=company_id,
            root_agent_key=root_agent_key,
            runtime_context=runtime_context,
            flow_id=flow_id,
            node_id=node_id,
            provider_message_id=provider_message_id,
        )

        if input_guardrail and input_guardrail["action"] == "block":
            response, punctuation_sanitized = _sanitize_agent_response_punctuation(
                input_guardrail["message"]
            )
            _log_agent_execution(
                db=db,
                company_id=company_id,
                phone=runtime_context.contact_phone,
                workflow_name=trace_context["workflow_name"],
                trace_id=trace_context["trace_id"],
                conversation_group=trace_context["group_id"],
                user_input=message,
                agent_response=response,
                execution_time_ms=0,
                tokens_used=0,
                tools_called=[],
                status="success",
                metadata={
                    **trace_context["metadata"],
                    "execution_mode": "guardrail_block",
                    "guardrail": input_guardrail,
                    "response_delay_seconds": response_delay_seconds,
                    "configured_response_delay_seconds": configured_response_delay_seconds,
                    "conversation_history_source": history_source,
                    "conversation_history_count": len(conversation_history),
                    "debounced_message_count": len(debounced_messages),
                    "response_punctuation_sanitized": punctuation_sanitized,
                },
            )
            return _success_payload(
                workforce=workforce,
                root_agent_key=root_agent_key,
                root_agent_name=root_config.agent.name,
                response=response,
                tokens_used=0,
                metadata={
                    "execution_mode": "guardrail_block",
                    "guardrail": input_guardrail,
                    "response_delay_seconds": response_delay_seconds,
                    "configured_response_delay_seconds": configured_response_delay_seconds,
                    "trace": trace_context,
                    "conversation_history_source": history_source,
                    "conversation_history_count": len(conversation_history),
                    "debounced_message_count": len(debounced_messages),
                },
            )

        image_payloads = _runtime_image_payloads(runtime_variables_for_run)
        image_input_parts = _runtime_image_input_parts(runtime_variables_for_run)
        runner_message = (
            _image_text_fallback_message(
                message,
                runtime_variables_for_run,
                db=db,
                company_id=company_id,
            )
            if image_payloads and not image_input_parts
            else message
        )
        runner_input = _build_runner_input(
            runner_message,
            conversation_history,
            image_input_parts=image_input_parts,
        )
        started_at = time.perf_counter()
        multimodal_fallback_error = ""
        multimodal_fallback_used = False
        try:
            result = _run_coroutine_sync(
                lambda: _run_agent_sdk(
                    agent=compiled.root_agent,
                    runner_input=runner_input,
                    runtime_context=runtime_context,
                    max_turns=root_config.runtime.max_turns,
                    trace_context=trace_context,
                    run_config=run_config,
                )
            )
        except (InputGuardrailTripwireTriggered, OutputGuardrailTripwireTriggered) as guardrail_error:
            execution_time_ms = int((time.perf_counter() - started_at) * 1000)
            return _handle_sdk_guardrail_tripwire(
                db=db,
                workforce=workforce,
                root_agent_key=root_agent_key,
                root_config=root_config,
                runtime_context=runtime_context,
                trace_context=trace_context,
                message=message,
                guardrail_error=guardrail_error,
                execution_time_ms=execution_time_ms,
                response_delay_seconds=response_delay_seconds,
                configured_response_delay_seconds=configured_response_delay_seconds,
                history_source=history_source,
                conversation_history=conversation_history,
                debounced_messages=debounced_messages,
            )
        except Exception as multimodal_error:
            if not image_input_parts:
                raise
            if not _should_retry_image_input_as_text(multimodal_error):
                raise

            multimodal_fallback_error = str(multimodal_error)
            multimodal_fallback_used = True
            logger.warning(
                "[AgentWorkforceRunner] Multimodal image input failed; retrying text fallback: %s",
                multimodal_error,
            )
            runner_message = _image_text_fallback_message(
                message,
                runtime_variables_for_run,
                db=db,
                company_id=company_id,
            )
            runner_input = _build_runner_input(runner_message, conversation_history)
            try:
                result = _run_coroutine_sync(
                    lambda: _run_agent_sdk(
                        agent=compiled.root_agent,
                        runner_input=runner_input,
                        runtime_context=runtime_context,
                        max_turns=root_config.runtime.max_turns,
                        trace_context=trace_context,
                        run_config=run_config,
                    )
                )
            except (InputGuardrailTripwireTriggered, OutputGuardrailTripwireTriggered) as guardrail_error:
                execution_time_ms = int((time.perf_counter() - started_at) * 1000)
                return _handle_sdk_guardrail_tripwire(
                    db=db,
                    workforce=workforce,
                    root_agent_key=root_agent_key,
                    root_config=root_config,
                    runtime_context=runtime_context,
                    trace_context=trace_context,
                    message=message,
                    guardrail_error=guardrail_error,
                    execution_time_ms=execution_time_ms,
                    response_delay_seconds=response_delay_seconds,
                    configured_response_delay_seconds=configured_response_delay_seconds,
                    history_source=history_source,
                    conversation_history=conversation_history,
                    debounced_messages=debounced_messages,
                    extra_metadata={
                        "multimodal_fallback_used": multimodal_fallback_used,
                        "multimodal_fallback_error": multimodal_fallback_error,
                    },
                )
        execution_time_ms = int((time.perf_counter() - started_at) * 1000)
        response_text = str(result.final_output or "").strip()
        usage = getattr(result.context_wrapper, "usage", None)
        openai_usage = extract_openai_usage(usage)
        tokens_used = int(openai_usage.get("total_tokens") or 0)

        last_agent = result.last_agent
        last_agent_key = _find_agent_key(compiled.agents_by_key, last_agent) or root_agent_key
        last_config = compiled.configs_by_key.get(last_agent_key, root_config)
        execution_mode = "agent_handoff" if last_agent_key != root_agent_key else "root_agent"
        handoff_target = f"agent:{last_agent_key}" if last_agent_key != root_agent_key else None
        result_context = getattr(getattr(result, "context_wrapper", None), "context", runtime_context)
        human_task = getattr(result_context, "human_handoff_task", None)
        suppress_whatsapp_send = bool(getattr(result_context, "suppress_whatsapp_send", False))

        calendar_tool_events = _calendar_tool_events(result)
        calendar_tool_results = _calendar_tool_result_summaries(calendar_tool_events)
        calendar_response_repaired = False
        calendar_response_repair_reason = None
        if not suppress_whatsapp_send:
            (
                response_text,
                calendar_response_repaired,
                calendar_response_repair_reason,
            ) = _enforce_calendar_availability_response(
                response_text=response_text,
                calendar_tool_events=calendar_tool_events,
            )

        output_guardrail = _evaluate_custom_guardrails(last_config, "output", response_text)
        if output_guardrail:
            if output_guardrail["action"] == "block":
                response_text = output_guardrail["message"]
                execution_mode = "guardrail_block"
            elif output_guardrail["action"] == "redact":
                response_text = _redact_by_guardrail(response_text, output_guardrail)

        response_text, audio_refusal_sanitized = _sanitize_audio_refusal_response(
            config=last_config,
            response_text=response_text,
            user_message=message,
        )
        (
            response_text,
            false_file_reference_sanitized,
        ) = _sanitize_false_customer_file_reference(
            response_text=response_text,
            user_message=message,
            runtime_variables=runtime_variables_for_run,
        )
        (
            response_text,
            whatsapp_markdown_links_sanitized,
        ) = _sanitize_whatsapp_markdown_links(
            response_text,
            channel=last_config.channel.type,
        )
        response_text, punctuation_sanitized = _sanitize_agent_response_punctuation(
            response_text
        )
        if suppress_whatsapp_send:
            response_text = ""
            execution_mode = "human_handoff_silent"

        tools_called = _summarize_run_items(result)
        audio_delivery_request = _audio_delivery_request_from_context(result_context)
        audio_delivery_tool_calls = _audio_delivery_tool_calls_from_context(result_context)
        execution_metadata = {
            **trace_context["metadata"],
            "execution_mode": execution_mode,
            "last_agent_key": last_agent_key,
            "last_agent_name": last_config.agent.name,
            "handoffs_configured": [
                handoff.model_dump() for handoff in root_config.handoffs
            ],
            "human_handoff_targets": root_config.metadata.get(
                "human_handoff_targets", []
            ),
            "human_task": human_task,
            "suppress_whatsapp_send": suppress_whatsapp_send,
            "output_guardrail": output_guardrail,
            "compiler_warnings": compiled.warnings,
            "last_response_id": getattr(result, "last_response_id", None),
            "response_delay_seconds": response_delay_seconds,
            "configured_response_delay_seconds": configured_response_delay_seconds,
            "conversation_history_source": history_source,
            "conversation_history_count": len(conversation_history),
            "debounced_message_count": len(debounced_messages),
            "audio_refusal_sanitized": audio_refusal_sanitized,
            "false_customer_file_reference_sanitized": false_file_reference_sanitized,
            "whatsapp_markdown_links_sanitized": whatsapp_markdown_links_sanitized,
            "response_punctuation_sanitized": punctuation_sanitized,
            "calendar_response_repaired": calendar_response_repaired,
            "calendar_response_repair_reason": calendar_response_repair_reason,
            "calendar_tool_results": calendar_tool_results,
            "openai_usage": openai_usage,
            "audio_delivery_request": audio_delivery_request,
            "audio_delivery_tool_calls": audio_delivery_tool_calls,
            "multimodal_image_input": bool(image_input_parts),
            "multimodal_image_count": len(image_input_parts),
            "multimodal_fallback_used": multimodal_fallback_used,
            "multimodal_fallback_error": multimodal_fallback_error,
        }

        audio_plan: Optional[AgentAudioDeliveryPlan] = None
        audio_response: Optional[AudioResponse] = None
        audio_fallback_text_used = False
        if not suppress_whatsapp_send:
            audio_plan = _build_agent_audio_delivery_plan(
                config=last_config,
                response_text=response_text,
                user_message=message,
                contact_name=runtime_context.contact_name,
                conversation_history=conversation_history,
                audio_delivery_request=audio_delivery_request,
            )
            audio_response = _generate_configured_agent_audio(
                db=db,
                company_id=company_id,
                config=last_config,
                response_text=response_text,
                user_message=message,
                audio_plan=audio_plan,
            )
            response_text, audio_fallback_text_used = _apply_requested_audio_failure_text_fallback(
                response_text=response_text,
                audio_response=audio_response,
                audio_plan=audio_plan,
            )
        execution_metadata["audio"] = _audio_response_metadata(audio_response, audio_plan)
        execution_metadata["audio"]["fallback_text_used"] = audio_fallback_text_used

        agent_execution_id = _log_agent_execution(
            db=db,
            company_id=company_id,
            phone=runtime_context.contact_phone,
            workflow_name=trace_context["workflow_name"],
            trace_id=trace_context["trace_id"],
            conversation_group=trace_context["group_id"],
            user_input=message,
            agent_response=response_text,
            execution_time_ms=execution_time_ms,
            tokens_used=tokens_used,
            tools_called=tools_called,
            status="success",
            metadata=execution_metadata,
        )

        safe_record_openai_text_usage(
            db=db,
            company_id=company_id,
            usage=usage,
            model=last_config.runtime.model,
            agent_execution_id=agent_execution_id,
            agent_key=last_config.agent.key,
            agent_name=last_config.agent.name,
            phone=runtime_context.contact_phone,
            conversation_group=trace_context["group_id"],
            trace_id=trace_context["trace_id"],
            provider_response_id=getattr(result, "last_response_id", None),
            usage_metadata={
                "workflow_name": trace_context["workflow_name"],
                "execution_mode": execution_mode,
                "flow_id": flow_id,
                "node_id": node_id,
            },
        )
        _record_audio_usage_event(
            db=db,
            company_id=company_id,
            audio_response=audio_response,
            audio_plan=audio_plan,
            agent_execution_id=agent_execution_id,
            agent_key=last_config.agent.key,
            agent_name=last_config.agent.name,
            phone=runtime_context.contact_phone,
            conversation_group=trace_context["group_id"],
            trace_id=trace_context["trace_id"],
            flow_id=flow_id,
            node_id=node_id,
        )

        return {
            "success": True,
            "response": response_text,
            "tokens_used": tokens_used,
            "workforce_id": workforce.id,
            "workforce_name": workforce.name,
            "root_agent_key": root_agent_key,
            "root_agent_name": root_config.agent.name,
            "handoff_target": handoff_target,
            "last_agent_key": last_agent_key,
            "last_agent_name": last_config.agent.name,
            **_audio_payload_fields(audio_response, audio_plan),
            "metadata": {
                **execution_metadata,
                "trace": trace_context,
            },
        }
    except Exception as exc:
        safe_error = safe_ai_provider_runtime_error(
            exc,
            fallback="Não foi possível executar a equipe de agentes de IA",
        )
        logger.error(
            "[AgentWorkforceRunner] Failed to execute workforce=%s root=%s error_type=%s",
            workforce_id,
            root_agent_key,
            type(exc).__name__,
        )
        try:
            trace_context = locals().get("trace_context")
            runtime_context = locals().get("runtime_context")
            _log_agent_execution(
                db=db,
                company_id=company_id,
                phone=getattr(runtime_context, "contact_phone", None),
                workflow_name=(trace_context or {}).get("workflow_name")
                or f"agent_workforce.{workforce_id}",
                trace_id=(trace_context or {}).get("trace_id"),
                conversation_group=(trace_context or {}).get("group_id"),
                user_input=message,
                agent_response="",
                execution_time_ms=0,
                tokens_used=0,
                tools_called=[],
                status="error",
                error_message=safe_error,
                metadata={
                    "workforce_id": workforce.id,
                    "workforce_name": workforce.name,
                    "root_agent_key": root_agent_key,
                    "flow_id": flow_id,
                    "node_id": node_id,
                },
            )
        except Exception:
            logger.exception("[AgentWorkforceRunner] Failed to persist error execution")

        return {
            "success": False,
            "response": "",
            "error": safe_error,
            "workforce_id": workforce.id,
            "workforce_name": workforce.name,
            "root_agent_key": root_agent_key,
        }


def _success_payload(
    workforce: AgentWorkforce,
    root_agent_key: str,
    root_agent_name: str,
    response: str,
    tokens_used: int,
    metadata: Dict[str, Any],
    audio_response: Optional[AudioResponse] = None,
) -> Dict[str, Any]:
    return {
        "success": True,
        "response": response,
        "tokens_used": tokens_used,
        "workforce_id": workforce.id,
        "workforce_name": workforce.name,
        "root_agent_key": root_agent_key,
        "root_agent_name": root_agent_name,
        **_audio_payload_fields(audio_response),
        "metadata": metadata,
    }


def _handle_sdk_guardrail_tripwire(
    *,
    db: Session,
    workforce: AgentWorkforce,
    root_agent_key: str,
    root_config: AgentCreationConfig,
    runtime_context: "AgentWorkforceRunContext",
    trace_context: Dict[str, Any],
    message: str,
    guardrail_error: InputGuardrailTripwireTriggered | OutputGuardrailTripwireTriggered,
    execution_time_ms: int,
    response_delay_seconds: int,
    configured_response_delay_seconds: int,
    history_source: str,
    conversation_history: List[Dict[str, str]],
    debounced_messages: List[str],
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    guardrail = _sdk_guardrail_info(guardrail_error)
    response, punctuation_sanitized = _sanitize_agent_response_punctuation(
        str(guardrail.get("message") or DEFAULT_PROMPT_SAFETY_BLOCK_MESSAGE)
    )
    metadata = {
        **trace_context["metadata"],
        "execution_mode": "guardrail_block",
        "guardrail": guardrail,
        "guardrail_source": "agents_sdk",
        "guardrail_exception": guardrail_error.__class__.__name__,
        "response_delay_seconds": response_delay_seconds,
        "configured_response_delay_seconds": configured_response_delay_seconds,
        "conversation_history_source": history_source,
        "conversation_history_count": len(conversation_history),
        "debounced_message_count": len(debounced_messages),
        "response_punctuation_sanitized": punctuation_sanitized,
        **(extra_metadata or {}),
    }
    _log_agent_execution(
        db=db,
        company_id=workforce.company_id,
        phone=runtime_context.contact_phone,
        workflow_name=trace_context["workflow_name"],
        trace_id=trace_context["trace_id"],
        conversation_group=trace_context["group_id"],
        user_input=message,
        agent_response=response,
        execution_time_ms=execution_time_ms,
        tokens_used=0,
        tools_called=[],
        status="success",
        metadata=metadata,
    )
    return _success_payload(
        workforce=workforce,
        root_agent_key=root_agent_key,
        root_agent_name=root_config.agent.name,
        response=response,
        tokens_used=0,
        metadata={
            **metadata,
            "trace": trace_context,
        },
    )


def _sdk_guardrail_info(
    guardrail_error: InputGuardrailTripwireTriggered | OutputGuardrailTripwireTriggered,
) -> Dict[str, Any]:
    guardrail_result = getattr(guardrail_error, "guardrail_result", None)
    guardrail_output = getattr(guardrail_result, "output", None)
    output_info = getattr(guardrail_output, "output_info", None)
    if isinstance(output_info, dict):
        return output_info
    return {
        "key": "agents_sdk_guardrail",
        "name": "Agents SDK guardrail",
        "stage": "input"
        if isinstance(guardrail_error, InputGuardrailTripwireTriggered)
        else "output",
        "action": "block",
        "triggered": True,
        "category": "guardrail_tripwire",
        "message": DEFAULT_PROMPT_SAFETY_BLOCK_MESSAGE,
    }


def _voice_override_from_agent_config(
    config: AgentCreationConfig,
) -> Optional[Dict[str, Any]]:
    channel = getattr(config, "channel", None)
    if not channel or not getattr(channel, "allow_audio", False):
        return None

    voice = getattr(channel, "voice", None)
    voice_id = str(getattr(voice, "voice_id", "") or "").strip()
    provider = str(getattr(voice, "provider", "") or "").strip().lower()
    if not voice or not voice_id or provider != "elevenlabs":
        return None

    return voice.model_dump()


def _agent_audio_trigger_type(user_message: str) -> str:
    """Legacy helper: runtime audio intent should come from the agent tool."""

    trigger_result = AudioTriggers().detect_trigger(user_message or "")
    if trigger_result.should_send_audio and trigger_result.trigger_name:
        return trigger_result.trigger_name
    return "channel_audio_enabled"


def _audio_delivery_request_from_context(context: Any) -> Optional[Dict[str, Any]]:
    request = getattr(context, "audio_delivery_request", None)
    return _normalize_audio_delivery_request(request)


def _normalize_audio_delivery_request(request: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(request, dict):
        return None
    trigger_type = str(request.get("trigger_type") or "").strip()
    if trigger_type != "audio_requested":
        return None
    return {
        "trigger_type": trigger_type,
        "delivery_mode": str(request.get("delivery_mode") or "llm_requested_full").strip(),
        "spoken_text": str(request.get("spoken_text") or "").strip(),
        "reason": str(request.get("reason") or "").strip(),
        "source": str(request.get("source") or "agent_tool").strip(),
    }


def _audio_delivery_tool_calls_from_context(context: Any) -> List[Dict[str, Any]]:
    calls = getattr(context, "audio_delivery_tool_calls", None)
    if not isinstance(calls, list):
        return []
    return [
        call
        for call in (_normalize_audio_delivery_request(item) for item in calls)
        if call
    ]


def _normalize_audio_refusal_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text.lower()).strip()


def _contains_audio_capability_refusal(text: str) -> bool:
    normalized = _normalize_audio_refusal_text(text)
    return any(pattern in normalized for pattern in AUDIO_CAPABILITY_REFUSAL_PATTERNS)


def _normalized_delivery_text(text: str) -> str:
    normalized = _normalize_audio_refusal_text(text)
    normalized = re.sub(r"[^a-z0-9\s]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _contains_any_delivery_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    normalized = _normalized_delivery_text(text)
    return any(pattern in normalized for pattern in patterns)


def _response_promises_audio_delivery(text: str) -> bool:
    normalized = _normalized_delivery_text(text)
    if not normalized:
        return False
    if any(pattern in normalized for pattern in AGENT_RESPONSE_AUDIO_NEGATION_PATTERNS):
        return False
    return any(
        pattern in normalized
        for pattern in (*AGENT_CONFIG_AUDIO_RESPONSE_MARKERS, *AGENT_RESPONSE_AUDIO_PROMISE_PATTERNS)
    )


def _response_offers_audio_delivery(text: str) -> bool:
    normalized = _normalized_delivery_text(text)
    if not normalized:
        return False
    if any(pattern in normalized for pattern in AGENT_RESPONSE_AUDIO_NEGATION_PATTERNS):
        return False
    return any(pattern in normalized for pattern in AGENT_RESPONSE_AUDIO_OFFER_PATTERNS)


def _prefers_text_delivery(text: str) -> bool:
    return _contains_any_delivery_pattern(text, TEXT_DELIVERY_PATTERNS)


def _user_accepts_delivery_offer(user_message: str) -> bool:
    normalized = _normalized_delivery_text(user_message)
    if not normalized:
        return False
    return any(
        normalized == pattern or normalized.startswith(f"{pattern} ")
        for pattern in USER_DELIVERY_ACCEPTANCE_PATTERNS
    )


def _latest_assistant_history_message(
    conversation_history: Optional[List[Dict[str, str]]],
) -> str:
    for item in reversed(_normalize_conversation_history(conversation_history or [])):
        if item.get("role") == "assistant":
            return str(item.get("content") or "").strip()
    return ""


def _accepted_prior_audio_offer(
    conversation_history: Optional[List[Dict[str, str]]],
    user_message: str,
) -> bool:
    if not _user_accepts_delivery_offer(user_message):
        return False
    return _response_offers_audio_delivery(_latest_assistant_history_message(conversation_history))


def _accepted_prior_text_offer(
    conversation_history: Optional[List[Dict[str, str]]],
    user_message: str,
) -> bool:
    if not _user_accepts_delivery_offer(user_message):
        return False
    return _prefers_text_delivery(_latest_assistant_history_message(conversation_history))


def _sanitize_agent_response_punctuation(response_text: str) -> tuple[str, bool]:
    text = str(response_text or "").strip()
    if not text or not LONG_DASH_PATTERN.search(text):
        return text, False

    def _replacement(match: re.Match[str]) -> str:
        start, end = match.span()
        previous_char = text[start - 1] if start > 0 else ""
        next_char = text[end] if end < len(text) else ""
        if previous_char.isdigit() and next_char.isdigit():
            return "-"
        if not previous_char or not previous_char.strip():
            return ""
        if not next_char or not next_char.strip():
            return ""
        if previous_char in "([{/" or next_char in ")]},.;:!?/":
            return " "
        return ", "

    cleaned = LONG_DASH_PATTERN.sub(_replacement, text)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r",\s*([.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"(^|\n)\s*,\s*", r"\1", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip(), True


def _sanitize_whatsapp_markdown_links(
    response_text: str,
    *,
    channel: Optional[str],
) -> tuple[str, bool]:
    text = str(response_text or "").strip()
    if (
        not text
        or str(channel or "").strip().lower() != "whatsapp"
        or not MARKDOWN_LINK_PATTERN.search(text)
    ):
        return text, False

    def _replacement(match: re.Match[str]) -> str:
        label = re.sub(r"\s+", " ", match.group(1)).strip()
        url = match.group(2).strip()
        if not label:
            return url
        if _normalized_markdown_url(label) == _normalized_markdown_url(url):
            return url
        if label.endswith(":"):
            return f"{label} {url}"
        return f"{label}: {url}"

    cleaned = MARKDOWN_LINK_PATTERN.sub(_replacement, text)
    return cleaned.strip(), cleaned != text


def _normalized_markdown_url(value: str) -> str:
    normalized = str(value or "").strip().rstrip("/").lower()
    if normalized.startswith("https://"):
        normalized = normalized[len("https://"):]
    elif normalized.startswith("http://"):
        normalized = normalized[len("http://"):]
    return normalized.rstrip("/")


def _sanitize_false_customer_file_reference(
    *,
    response_text: str,
    user_message: str,
    runtime_variables: Optional[Dict[str, Any]] = None,
) -> tuple[str, bool]:
    text = str(response_text or "").strip()
    if not text or not _response_claims_customer_sent_file(text):
        return text, False
    if _current_input_has_customer_file_context(user_message, runtime_variables):
        return text, False

    sanitized = _false_customer_file_reference_fallback(user_message)
    logger.warning(
        "[AgentWorkforceRunner] Replaced unsupported customer file reference"
    )
    return sanitized, True


def _response_claims_customer_sent_file(response_text: str) -> bool:
    normalized = _normalized_delivery_text(response_text)
    return any(
        re.search(pattern, normalized)
        for pattern in FALSE_CUSTOMER_FILE_REFERENCE_PATTERNS
    )


def _current_input_has_customer_file_context(
    user_message: str,
    runtime_variables: Optional[Dict[str, Any]],
) -> bool:
    if _user_message_references_own_file(user_message):
        return True

    variables = _dict_or_empty(runtime_variables)
    trigger = _dict_or_empty(variables.get("trigger"))
    for payload in (variables, trigger):
        if _payload_has_file_attachment(payload):
            return True
    return False


def _user_message_references_own_file(user_message: str) -> bool:
    normalized = _normalized_delivery_text(user_message)
    if not normalized:
        return False

    negative_patterns = (
        "nao enviei arquivo",
        "nao enviei anexo",
        "nao enviei documento",
        "nao mandei arquivo",
        "nao mandei anexo",
        "nao mandei documento",
        "sem arquivo",
        "sem anexo",
        "sem documento",
    )
    if any(pattern in normalized for pattern in negative_patterns):
        return False

    return any(
        re.search(pattern, normalized)
        for pattern in (
            (
                r"\b(?:arquivo|arquivos|documento|documentos|anexo|anexos|"
                r"pdf|pdfs)\s+que\s+(?:eu\s+)?"
                r"(?:enviei|mandei|anexei|compartilhei|encaminhei)"
            ),
            (
                r"\b(?:enviei|mandei|anexei|compartilhei|encaminhei)\s+"
                r"(?:um|uma|o|a|os|as|meu|meus|minha|minhas)?\s*"
                r"(?:arquivo|arquivos|documento|documentos|anexo|anexos|pdf|pdfs)"
            ),
            r"\b(?:meu|meus|minha|minhas)\s+(?:arquivo|arquivos|documento|documentos|anexo|anexos|pdf|pdfs)\b",
            r"\b(?:arquivo|documento|anexo)\s+recebido\b",
        )
    )


def _payload_has_file_attachment(payload: Dict[str, Any]) -> bool:
    if not payload:
        return False

    raw_values = [
        payload.get("type"),
        payload.get("message_type"),
        payload.get("messageType"),
        payload.get("mime_type"),
        payload.get("mimetype"),
        payload.get("content_type"),
        payload.get("contentType"),
    ]
    normalized_values = " ".join(
        _normalized_delivery_text(str(value or ""))
        for value in raw_values
        if str(value or "").strip()
    )
    normalized_value_parts = normalized_values.split()
    if any(
        message_type in normalized_value_parts
        for message_type in CUSTOMER_FILE_MESSAGE_TYPES
    ):
        return True
    if (
        "application pdf" in normalized_values
        or "application msword" in normalized_values
    ):
        return True
    if "officedocument" in normalized_values:
        return True

    for key in CUSTOMER_FILE_PAYLOAD_KEYS:
        value = payload.get(key)
        if isinstance(value, dict) and value:
            return True
        if isinstance(value, list) and any(item for item in value):
            return True
        if isinstance(value, str) and value.strip():
            return True
    return False


def _false_customer_file_reference_fallback(user_message: str) -> str:
    normalized = _normalized_delivery_text(user_message)
    if normalized in GREETING_ONLY_MESSAGES or len(normalized) <= 4:
        return "Olá, tudo bem? Como posso te ajudar?"
    return "Você poderia me informar o que precisa para eu te ajudar melhor?"


def _agent_config_audio_rule_sources(config: AgentCreationConfig) -> List[str]:
    prompt = getattr(config, "prompt_techniques", None)
    if not prompt:
        return []

    sources: List[str] = []
    instructions = getattr(prompt, "instructions", None) or []
    conversation_rules = getattr(prompt, "conversation_rules", None) or []
    for value in [*instructions, *conversation_rules]:
        text = str(value or "").strip()
        if text:
            sources.append(text)
    return sources


def _is_agent_config_audio_rule(text: str) -> bool:
    normalized = _normalize_audio_refusal_text(text)
    if not normalized:
        return False
    if any(pattern in normalized for pattern in AGENT_CONFIG_AUDIO_NEGATION_PATTERNS):
        return False
    return any(pattern in normalized for pattern in AGENT_CONFIG_AUDIO_RULE_PATTERNS)


def _agent_config_audio_response_matches(response_text: str, rules: List[str]) -> bool:
    if _response_promises_audio_delivery(response_text):
        return True

    for rule in rules:
        normalized_rule = _normalized_delivery_text(rule)
        if any(pattern in normalized_rule for pattern in AGENT_CONFIG_AUDIO_ALWAYS_PATTERNS):
            return True
    return False


def _extract_quoted_audio_text(text: str) -> Optional[str]:
    raw_text = str(text or "").strip()
    for quote in ('"', "'"):
        if raw_text.startswith(quote):
            closing_quote_index = raw_text.rfind(quote)
            if closing_quote_index > 0:
                quoted = re.sub(r"\s+", " ", raw_text[1:closing_quote_index]).strip()
                if quoted:
                    return quoted

    for pattern in (r'"([^"]+)"', r"'([^']+)'"):
        match = re.search(pattern, text, flags=re.DOTALL)
        if match:
            quoted = re.sub(r"\s+", " ", match.group(1)).strip()
            if quoted:
                return quoted
    return None


def _extract_agent_config_audio_content(rules: List[str]) -> Optional[str]:
    for rule in rules:
        match = re.search(
            r"conte[uú]do\s+do\s+[áa]udio(?:\s+a\s+ser\s+enviado)?\s*:\s*(.+)",
            rule,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            continue

        content = _extract_quoted_audio_text(match.group(1))
        if content:
            return content

        line = re.split(r"[\r\n]", match.group(1).strip(), maxsplit=1)[0].strip()
        line = line.strip(" \"'")
        if line:
            return line
    return None


def _strip_agent_audio_placeholder(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(
        r"^\s*\[(?:áudio|audio)\s+enviad[ao](?:\s+pela\s+empresa)?\]\s*:?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^\s*(?:áudio|audio)\s+enviad[ao](?:\s+pela\s+empresa)?\s*:?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()


def _is_agent_audio_placeholder_only(text: str) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned:
        return False
    return not _strip_agent_audio_placeholder(cleaned)


def _apply_agent_audio_template_values(
    text: str,
    *,
    contact_name: Optional[str] = None,
) -> str:
    rendered = str(text or "").strip()
    name = str(contact_name or "").strip()
    if name:
        rendered = re.sub(r"\[(?:nome|name)\]", name, rendered, flags=re.IGNORECASE)
        rendered = re.sub(r"\{\{\s*(?:nome|name)\s*\}\}", name, rendered, flags=re.IGNORECASE)
        rendered = re.sub(r"\{\s*(?:nome|name)\s*\}", name, rendered, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", rendered).strip()


def _agent_config_audio_delivery_plan(
    *,
    config: AgentCreationConfig,
    response_text: str,
    contact_name: Optional[str] = None,
    force_match: bool = False,
) -> Optional[AgentAudioDeliveryPlan]:
    rules = [
        source
        for source in _agent_config_audio_rule_sources(config)
        if _is_agent_config_audio_rule(source)
    ]
    if not rules or (not force_match and not _agent_config_audio_response_matches(response_text, rules)):
        return None

    request_text = (
        _extract_agent_config_audio_content(rules)
        or _strip_agent_audio_placeholder(response_text)
    )
    request_text = _apply_agent_audio_template_values(
        request_text,
        contact_name=contact_name,
    )
    if not request_text:
        return None

    return AgentAudioDeliveryPlan(
        request_text=request_text,
        trigger_type="channel_audio_enabled",
        delivery_mode="agent_config_full",
    )


def _contains_link_for_audio(*texts: Optional[str]) -> bool:
    return any(
        bool(AUDIO_BLOCKED_LINK_PATTERN.search(str(text or "")))
        for text in texts
    )


def _audio_refusal_fallback_text(user_message: str) -> str:
    normalized_message = _normalize_audio_refusal_text(user_message)
    if "audio" in normalized_message and "como funciona" in normalized_message:
        return (
            "Funciona assim: eu preparo a resposta normalmente, o sistema transforma "
            "essa resposta na voz configurada da agente e envia o resultado como "
            "audio no WhatsApp. Voce pode continuar perguntando por aqui e eu "
            "respondo com o conteudo em audio quando essa opcao estiver habilitada."
        )

    return (
        "Claro. Vou responder normalmente para que o sistema envie em audio. "
        "Para te ajudar com precisao, me diga qual ponto voce quer que eu explique."
    )


def _sanitize_audio_refusal_response(
    *,
    config: AgentCreationConfig,
    response_text: str,
    user_message: str,
) -> tuple[str, bool]:
    text = str(response_text or "").strip()
    if not text or not _voice_override_from_agent_config(config):
        return text, False
    if not _contains_audio_capability_refusal(text):
        return text, False

    kept_sentences: List[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        cleaned_sentence = sentence.strip()
        if cleaned_sentence and not _contains_audio_capability_refusal(cleaned_sentence):
            kept_sentences.append(cleaned_sentence)

    cleaned = " ".join(kept_sentences).strip()
    cleaned = re.sub(
        r"\b(por|em|via)\s+texto\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    if len(_normalize_audio_refusal_text(cleaned)) >= 60 and not _contains_audio_capability_refusal(cleaned):
        sanitized = cleaned
    else:
        sanitized = _audio_refusal_fallback_text(user_message)

    logger.warning(
        "[AgentWorkforceRunner] Replaced audio capability refusal for agent=%s",
        config.agent.key,
    )
    return sanitized, True


def _build_agent_audio_delivery_plan(
    *,
    config: AgentCreationConfig,
    response_text: str,
    user_message: str,
    contact_name: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    audio_delivery_request: Optional[Dict[str, Any]] = None,
) -> Optional[AgentAudioDeliveryPlan]:
    if not _voice_override_from_agent_config(config):
        return None

    normalized_response = str(response_text or "").strip()
    if not normalized_response:
        return None

    if _prefers_text_delivery(user_message) or _prefers_text_delivery(normalized_response):
        return None

    accepted_prior_text_offer = _accepted_prior_text_offer(conversation_history, user_message)
    if accepted_prior_text_offer:
        return None

    accepted_prior_audio_offer = _accepted_prior_audio_offer(conversation_history, user_message)
    placeholder_only_response = _is_agent_audio_placeholder_only(normalized_response)

    semantic_audio_plan = _semantic_agent_audio_delivery_plan(
        audio_delivery_request=audio_delivery_request,
        response_text=normalized_response,
        contact_name=contact_name,
    )
    if semantic_audio_plan:
        return semantic_audio_plan

    config_audio_plan = _agent_config_audio_delivery_plan(
        config=config,
        response_text=normalized_response,
        contact_name=contact_name,
        force_match=accepted_prior_audio_offer or placeholder_only_response,
    )
    if config_audio_plan:
        return config_audio_plan
    if placeholder_only_response:
        logger.warning(
            "[AgentWorkforceRunner] Skipping audio generation because response only contains audio placeholder"
        )
        return None

    if _response_promises_audio_delivery(normalized_response) or accepted_prior_audio_offer:
        return AgentAudioDeliveryPlan(
            request_text=normalized_response,
            trigger_type="channel_audio_enabled",
            delivery_mode=(
                "accepted_audio_offer_full"
                if accepted_prior_audio_offer
                else "agent_audio_promise_full"
            ),
        )

    if _response_offers_audio_delivery(normalized_response):
        return None

    try:
        from backend.services.flow_node_handlers import split_humanized_whatsapp_response

        split_parts = split_humanized_whatsapp_response(normalized_response)
    except Exception as exc:
        logger.warning(
            "[AgentWorkforceRunner] Could not evaluate response split for audio policy: %s",
            exc,
        )
        return None

    if len(split_parts) < 2:
        return None

    audio_text = " ".join(part.strip() for part in split_parts[1:] if part and part.strip()).strip()
    if len(audio_text) <= AUTO_AUDIO_TAIL_MIN_CHARS:
        return None

    return AgentAudioDeliveryPlan(
        request_text=audio_text,
        trigger_type="channel_audio_enabled",
        delivery_mode="text_then_audio_tail",
        text_intro=split_parts[0],
        split_parts=split_parts,
    )


def _semantic_agent_audio_delivery_plan(
    *,
    audio_delivery_request: Optional[Dict[str, Any]],
    response_text: str,
    contact_name: Optional[str] = None,
) -> Optional[AgentAudioDeliveryPlan]:
    request = audio_delivery_request if isinstance(audio_delivery_request, dict) else None
    if not request or request.get("trigger_type") != "audio_requested":
        return None

    request_text = str(request.get("spoken_text") or "").strip()
    if not request_text:
        request_text = _strip_agent_audio_placeholder(response_text)
    request_text = _apply_agent_audio_template_values(
        request_text,
        contact_name=contact_name,
    )
    if not request_text:
        logger.warning(
            "[AgentWorkforceRunner] Skipping semantic audio generation because no spoken text was available"
        )
        return None

    return AgentAudioDeliveryPlan(
        request_text=request_text,
        trigger_type="audio_requested",
        delivery_mode=str(request.get("delivery_mode") or "llm_requested_full").strip()
        or "llm_requested_full",
    )


def _generate_configured_agent_audio(
    *,
    db: Session,
    company_id: int,
    config: AgentCreationConfig,
    response_text: str,
    user_message: str,
    audio_plan: Optional[AgentAudioDeliveryPlan] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> Optional[AudioResponse]:
    voice_override = _voice_override_from_agent_config(config)
    audio_plan = audio_plan or _build_agent_audio_delivery_plan(
        config=config,
        response_text=response_text,
        user_message=user_message,
        conversation_history=conversation_history,
    )
    request_text = str(audio_plan.request_text if audio_plan else "").strip()[:4096]
    if not voice_override or not request_text or not audio_plan:
        return None

    if _contains_link_for_audio(response_text, request_text):
        audio_response = AudioResponse(
            should_send_audio=False,
            text_processed=request_text,
            error=AUDIO_LINK_BLOCKED_ERROR,
        )
        _hydrate_audio_response_provider_fields(audio_response, voice_override)
        logger.info(
            "[AgentWorkforceRunner] Audio blocked because response/request text contains link for company=%s agent=%s",
            company_id,
            config.agent.key,
        )
        return audio_response

    voice_provider = str(voice_override.get("provider") or "openai").strip().lower()
    if voice_provider == "elevenlabs" and get_ai_credit_balance(db, company_id) <= 0:
        logger.warning(
            "[AgentWorkforceRunner] Legacy ElevenLabs allowance exhausted for company=%s agent=%s",
            company_id,
            config.agent.key,
        )
        return AudioResponse(
            should_send_audio=False,
            text_processed=request_text,
            provider_used="elevenlabs",
            model_used=voice_override.get("model_id") or voice_override.get("model"),
            error="Legacy ElevenLabs allowance exhausted",
        )

    try:
        audio_service = AudioService(
            db=db,
            company_id=company_id,
            voice_config_override=voice_override,
        )
        audio_request = AudioRequest(
            text=request_text,
            user_message=user_message or "",
            company_id=company_id,
            trigger_type=audio_plan.trigger_type,
        )
        audio_response = _run_coroutine_sync(
            lambda: audio_service.process_audio_request(audio_request)
        )
        _hydrate_audio_response_provider_fields(audio_response, voice_override)
        if audio_response.should_send_audio:
            logger.info(
                "[AgentWorkforceRunner] Audio generated for company=%s agent=%s trigger=%s provider=%s",
                company_id,
                config.agent.key,
                audio_response.trigger_detected,
                audio_response.provider_used,
            )
        elif audio_response.error:
            logger.warning(
                "[AgentWorkforceRunner] Audio not generated for company=%s agent=%s: %s",
                company_id,
                config.agent.key,
                audio_response.error,
            )
        return audio_response
    except Exception as exc:
        logger.exception(
            "[AgentWorkforceRunner] Failed to generate configured audio for company=%s agent=%s",
            company_id,
            config.agent.key,
        )
        return AudioResponse(
            should_send_audio=False,
            text_processed=request_text,
            provider_used=voice_override.get("provider"),
            model_used=voice_override.get("model_id") or voice_override.get("model"),
            error=str(exc),
        )


def _hydrate_audio_response_provider_fields(
    audio_response: AudioResponse,
    voice_override: Dict[str, Any],
) -> None:
    provider = str(voice_override.get("provider") or "openai").strip().lower()
    if provider not in {"openai", "elevenlabs"}:
        provider = "openai"

    if not audio_response.provider_used:
        audio_response.provider_used = provider
    if not audio_response.model_used:
        audio_response.model_used = (
            voice_override.get("model_id")
            or voice_override.get("elevenlabs_model_id")
            or voice_override.get("model")
        )
    if not audio_response.voice_used:
        audio_response.voice_used = voice_override.get("voice_id") or voice_override.get("default_voice")


def _audio_response_metadata(
    audio_response: Optional[AudioResponse],
    audio_plan: Optional[AgentAudioDeliveryPlan] = None,
) -> Dict[str, Any]:
    if not audio_response:
        return {
            "should_send_audio": False,
            "delivery_mode": audio_plan.delivery_mode if audio_plan else None,
            "audio_text_intro": audio_plan.text_intro if audio_plan else None,
        }

    return {
        "should_send_audio": bool(audio_response.should_send_audio),
        "trigger": audio_response.trigger_detected,
        "delivery_mode": audio_plan.delivery_mode if audio_plan else None,
        "audio_text_intro": audio_plan.text_intro if audio_plan else None,
        "audio_text": audio_plan.request_text if audio_plan else None,
        "audio_text_chars": len(audio_plan.request_text) if audio_plan else None,
        "split_parts": audio_plan.split_parts if audio_plan else [],
        "voice_used": audio_response.voice_used,
        "provider": audio_response.provider_used,
        "model": audio_response.model_used,
        "speed": audio_response.speed_used,
        "characters_used": audio_response.characters_used,
        "provider_usage_units": audio_response.provider_usage_units,
        "provider_request_id": audio_response.provider_request_id,
        "provider_metadata": audio_response.provider_metadata,
        "generation_time_ms": audio_response.generation_time_ms,
        "error": audio_response.error,
    }


def _apply_requested_audio_failure_text_fallback(
    *,
    response_text: str,
    audio_response: Optional[AudioResponse],
    audio_plan: Optional[AgentAudioDeliveryPlan],
) -> tuple[str, bool]:
    text = str(response_text or "").strip()
    if not text or not audio_response or not audio_plan:
        return text, False
    if audio_response.should_send_audio:
        return text, False
    if audio_plan.trigger_type != "audio_requested" or audio_plan.delivery_mode not in {
        "requested_full",
        "llm_requested_full",
    }:
        return text, False
    if _normalize_audio_refusal_text(text).startswith(
        _normalize_audio_refusal_text(AUDIO_GENERATION_FAILURE_FALLBACK_PREFIX)
    ):
        return text, False

    return f"{AUDIO_GENERATION_FAILURE_FALLBACK_PREFIX} {text}", True


def _audio_payload_fields(
    audio_response: Optional[AudioResponse],
    audio_plan: Optional[AgentAudioDeliveryPlan] = None,
) -> Dict[str, Any]:
    if not audio_response:
        return {
            "audio": None,
            "should_send_audio": False,
            "audio_trigger": None,
            "audio_delivery_mode": audio_plan.delivery_mode if audio_plan else None,
            "audio_text_intro": audio_plan.text_intro if audio_plan else None,
            "audio_text": audio_plan.request_text if audio_plan else None,
            "audio_split_parts": audio_plan.split_parts if audio_plan else [],
            "voice_used": None,
            "voice_provider": None,
            "voice_model": None,
            "audio_error": None,
        }

    return {
        "audio": (
            audio_response.audio_data
            if audio_response.should_send_audio
            else None
        ),
        "should_send_audio": bool(audio_response.should_send_audio),
        "audio_trigger": audio_response.trigger_detected,
        "audio_delivery_mode": audio_plan.delivery_mode if audio_plan else None,
        "audio_text_intro": audio_plan.text_intro if audio_plan else None,
        "audio_text": audio_plan.request_text if audio_plan else None,
        "audio_split_parts": audio_plan.split_parts if audio_plan else [],
        "voice_used": audio_response.voice_used,
        "voice_provider": audio_response.provider_used,
        "voice_model": audio_response.model_used,
        "audio_error": audio_response.error,
    }


def _record_audio_usage_event(
    *,
    db: Session,
    company_id: int,
    audio_response: Optional[AudioResponse],
    audio_plan: Optional[AgentAudioDeliveryPlan],
    agent_execution_id: Optional[int],
    agent_key: Optional[str],
    agent_name: Optional[str],
    phone: Optional[str],
    conversation_group: Optional[str],
    trace_id: Optional[str],
    flow_id: Optional[int],
    node_id: Optional[str],
) -> None:
    if not audio_plan or not audio_response:
        return
    if not audio_response.should_send_audio and audio_response.error == AUDIO_LINK_BLOCKED_ERROR:
        return

    status = "success" if audio_response.should_send_audio else "failed"
    provider_units = None
    if audio_response.provider_usage_units is not None:
        provider_units = Decimal(str(audio_response.provider_usage_units))

    safe_record_tts_usage(
        db=db,
        company_id=company_id,
        provider=audio_response.provider_used or "openai",
        model=audio_response.model_used,
        text_characters=audio_response.characters_used or len(audio_plan.request_text),
        status=status,
        provider_usage_units=provider_units,
        agent_execution_id=agent_execution_id,
        agent_key=agent_key,
        agent_name=agent_name,
        phone=phone,
        conversation_group=conversation_group,
        trace_id=trace_id,
        provider_request_id=audio_response.provider_request_id,
        usage_metadata={
            "trigger": audio_response.trigger_detected,
            "delivery_mode": audio_plan.delivery_mode,
            "voice_used": audio_response.voice_used,
            "speed": audio_response.speed_used,
            "generation_time_ms": audio_response.generation_time_ms,
            "provider_metadata": audio_response.provider_metadata or {},
            "flow_id": flow_id,
            "node_id": node_id,
        },
        error_message=audio_response.error,
    )


def _response_delay_seconds(workforce_settings: Dict[str, Any]) -> int:
    agent_context = (
        workforce_settings.get("agent_context")
        if isinstance(workforce_settings.get("agent_context"), dict)
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


def _response_delay_already_waited(variables: Dict[str, Any]) -> bool:
    trigger = variables.get("trigger") if isinstance(variables.get("trigger"), dict) else {}
    return bool(
        trigger.get("response_delay_already_waited")
        or variables.get("response_delay_already_waited")
    )


def _debounced_message_texts(variables: Dict[str, Any]) -> List[str]:
    trigger = variables.get("trigger") if isinstance(variables.get("trigger"), dict) else {}
    raw_messages = trigger.get("debounced_messages") or variables.get("debounced_messages")
    if not isinstance(raw_messages, list):
        return []
    return [
        str(message or "").strip()
        for message in raw_messages
        if str(message or "").strip()
    ]


def _drop_debounced_messages_from_history(
    conversation_history: List[Dict[str, str]],
    debounced_messages: List[str],
) -> List[Dict[str, str]]:
    """Avoid duplicating the just-buffered user messages in model input."""

    if not conversation_history or not debounced_messages:
        return conversation_history

    trimmed = list(conversation_history)
    pending = list(reversed([message.strip() for message in debounced_messages if message.strip()]))
    while pending and trimmed:
        last = trimmed[-1]
        if last.get("role") != "user":
            break
        if str(last.get("content") or "").strip() != pending[0]:
            break
        trimmed.pop()
        pending.pop(0)
    return trimmed


def _build_runtime_context(
    variables: Dict[str, Any],
    message: str,
    *,
    company_id: int,
    workforce: AgentWorkforce,
    root_agent_key: str,
    flow_id: Optional[int],
    node_id: Optional[str],
) -> AgentWorkforceRunContext:
    trigger = variables.get("trigger") if isinstance(variables.get("trigger"), dict) else {}
    return AgentWorkforceRunContext(
        company_id=company_id,
        workforce_id=workforce.id,
        workforce_name=workforce.name,
        root_agent_key=root_agent_key,
        flow_id=flow_id,
        node_id=node_id,
        channel=trigger.get("channel") or variables.get("channel") or "whatsapp",
        contact_name=trigger.get("name") or variables.get("name"),
        contact_phone=trigger.get("phone")
        or variables.get("phone")
        or variables.get("whatsapp"),
        current_stage=variables.get("current_stage"),
        conversation_step=variables.get("conversation_step"),
        latest_user_message=message,
        organization_data=variables.get("organization_data")
        if isinstance(variables.get("organization_data"), dict)
        else {},
    )


def _compile_workforce_agents(
    agent_configs: Dict[str, Any],
    root_agent_key: str,
    company_id: Optional[int] = None,
    workforce_settings: Optional[Dict[str, Any]] = None,
    latest_user_message: str = "",
) -> CompiledWorkforce:
    configs_by_key: Dict[str, AgentCreationConfig] = {}
    agents_by_key: Dict[str, Agent[Any]] = {}
    warnings: List[str] = []
    prepared_configs, registry, settings_warnings = _prepare_workforce_agent_configs(
        agent_configs=agent_configs,
        company_id=company_id,
        workforce_settings=workforce_settings or {},
        latest_user_message=latest_user_message,
    )
    warnings.extend(settings_warnings)
    compiler = AgentConfigCompiler(registry=registry, strict_references=False)

    for key, raw_config in prepared_configs.items():
        config = AgentCreationConfig.model_validate(raw_config)
        configs_by_key[key] = config
        build_result = compiler.create_agent(config)
        agents_by_key[key] = build_result.agent
        if build_result.unresolved_tools:
            warnings.append(
                f"{key}: unresolved tool ids: {', '.join(build_result.unresolved_tools)}"
            )
        if build_result.unresolved_guardrails:
            warnings.append(
                f"{key}: unresolved guardrail ids: {', '.join(build_result.unresolved_guardrails)}"
            )

    for key, config in configs_by_key.items():
        resolved_handoffs: List[Agent[Any]] = []
        for rule in config.handoffs:
            target_agent = agents_by_key.get(rule.target_agent)
            if target_agent is None:
                warnings.append(
                    f"{key}: unresolved handoff target {rule.target_agent}"
                )
                continue
            resolved_handoffs.append(target_agent)
        agents_by_key[key].handoffs = resolved_handoffs

    return CompiledWorkforce(
        agents_by_key=agents_by_key,
        configs_by_key=configs_by_key,
        root_agent=agents_by_key[root_agent_key],
        root_agent_key=root_agent_key,
        warnings=warnings,
    )


def _prepare_workforce_agent_configs(
    *,
    agent_configs: Dict[str, Any],
    company_id: Optional[int],
    workforce_settings: Dict[str, Any],
    latest_user_message: str,
) -> tuple[Dict[str, Any], AgentRuntimeRegistry, List[str]]:
    agent_context = (
        workforce_settings.get("agent_context")
        if isinstance(workforce_settings.get("agent_context"), dict)
        else {}
    )
    global_context = (
        agent_context.get("global_context")
        if isinstance(agent_context.get("global_context"), dict)
        else {}
    )
    global_few_shots = (
        agent_context.get("global_few_shots")
        if isinstance(agent_context.get("global_few_shots"), dict)
        else {}
    )
    knowledge = (
        agent_context.get("knowledge")
        if isinstance(agent_context.get("knowledge"), dict)
        else {}
    )
    performance = (
        agent_context.get("performance")
        if isinstance(agent_context.get("performance"), dict)
        else {}
    )

    warnings: List[str] = []
    registry = AgentRuntimeRegistry()
    from backend.agents_sdk.tools.audio_delivery_tools import create_audio_delivery_tools

    registry.register_tool_factory(
        "audio.request_response",
        lambda _tool: create_audio_delivery_tools(),
    )
    prepared: Dict[str, Any] = {}

    if company_id:
        from backend.agents_sdk.tools.calendar_scheduling_tools import (
            create_calendar_scheduling_tools,
        )
        from backend.agents_sdk.tools.human_handoff_tools import (
            create_human_handoff_tools,
        )
        from backend.agents_sdk.tools.crm_pipeline_tools import (
            create_crm_pipeline_tools,
        )
        from backend.agents_sdk.tools.whatsapp_contact_tools import (
            create_whatsapp_contact_card_tools,
        )
        from backend.agents_sdk.tools.whatsapp_scheduled_followup_tools import (
            create_whatsapp_scheduled_followup_tools,
        )

        def _calendar_scheduling_factory(tool_config: Any) -> List[Any]:
            settings = getattr(tool_config, "settings", None)
            if not isinstance(settings, dict):
                settings = {}
            agenda_id = _optional_positive_int(
                settings.get("agenda_id") or settings.get("agendaId")
            )
            raw_allowed_actions = settings.get("allowed_actions") or settings.get(
                "allowedActions"
            )
            allowed_actions = (
                [str(action) for action in raw_allowed_actions]
                if isinstance(raw_allowed_actions, list)
                else None
            )
            require_confirmation = (
                settings.get(
                    "require_confirmation",
                    settings.get("requireConfirmation", True),
                )
                is not False
            )
            max_suggestions = _safe_int(
                settings.get("max_suggestions") or settings.get("maxSuggestions"),
                default=3,
                minimum=1,
                maximum=6,
            )
            create_google_meet = bool(
                settings.get("create_google_meet") or settings.get("createGoogleMeet")
            )
            return create_calendar_scheduling_tools(
                company_id=int(company_id),
                configured_agenda_id=agenda_id,
                require_confirmation=require_confirmation,
                allowed_actions=allowed_actions,
                max_suggestions=max_suggestions,
                create_google_meet=create_google_meet,
            )

        registry.register_tool_factory(
            "calendar.scheduling",
            _calendar_scheduling_factory,
        )

        def _human_handoff_factory(tool_config: Any) -> List[Any]:
            settings = getattr(tool_config, "settings", None)
            if not isinstance(settings, dict):
                settings = {}
            targets = settings.get("targets") or settings.get("human_handoff_targets")
            if not isinstance(targets, list):
                targets = []
            return create_human_handoff_tools(
                company_id=int(company_id),
                targets=targets,
            )

        registry.register_tool_factory(
            "human_handoff.create_task",
            _human_handoff_factory,
        )

        def _crm_pipeline_factory(tool_config: Any) -> List[Any]:
            settings = getattr(tool_config, "settings", None)
            if not isinstance(settings, dict):
                settings = {}
            pipeline_id = _optional_positive_int(
                settings.get("pipeline_id") or settings.get("pipelineId")
            )
            stage_rules = settings.get("stage_rules") or settings.get("stageRules")
            if not isinstance(stage_rules, list):
                stage_rules = []
            return create_crm_pipeline_tools(
                company_id=int(company_id),
                configured_pipeline_id=pipeline_id,
                stage_rules=stage_rules,
            )

        registry.register_tool_factory(
            "crm.pipeline_stage",
            _crm_pipeline_factory,
        )

        registry.register_tool_factory(
            "crm.dynamic_followup",
            lambda _tool: [],
        )

        def _whatsapp_contact_card_factory(tool_config: Any) -> List[Any]:
            settings = getattr(tool_config, "settings", None)
            if not isinstance(settings, dict):
                settings = {}
            contact_cards = settings.get("contact_cards") or settings.get("contacts")
            if not isinstance(contact_cards, list):
                contact_cards = []
            return create_whatsapp_contact_card_tools(
                company_id=int(company_id),
                contact_cards=contact_cards,
            )

        registry.register_tool_factory(
            "whatsapp.send_contact_card",
            _whatsapp_contact_card_factory,
        )

        def _whatsapp_scheduled_followup_factory(tool_config: Any) -> List[Any]:
            settings = getattr(tool_config, "settings", None)
            if not isinstance(settings, dict):
                settings = {}
            return create_whatsapp_scheduled_followup_tools(
                company_id=int(company_id),
                default_replace_existing_pending=_safe_bool(
                    settings.get(
                        "replace_existing_pending",
                        settings.get("replaceExistingPending", True),
                    ),
                    default=True,
                ),
            )

        registry.register_tool_factory(
            "whatsapp.schedule_followup_message",
            _whatsapp_scheduled_followup_factory,
        )

    selected_examples = _select_relevant_global_examples(
        examples=global_few_shots.get("examples")
        if isinstance(global_few_shots.get("examples"), list)
        else [],
        message=latest_user_message,
        max_examples=_safe_int(
            performance.get("max_global_few_shots")
            or global_few_shots.get("max_examples"),
            default=3,
            minimum=0,
            maximum=8,
        ),
        enabled=global_few_shots.get("enabled", True) is not False
        and performance.get("retrieval_mode", "keyword") != "off",
    )

    file_search = (
        knowledge.get("file_search")
        if isinstance(knowledge.get("file_search"), dict)
        else {}
    )
    vector_store_id = str(file_search.get("vector_store_id") or "").strip()
    file_search_enabled = bool(vector_store_id) and file_search.get("enabled", True) is not False
    if file_search_enabled:
        max_results = _safe_int(
            file_search.get("max_num_results"),
            default=4,
            minimum=1,
            maximum=20,
        )
        registry.register_tool(
            "knowledge.file_search",
            FileSearchTool(
                vector_store_ids=[vector_store_id],
                max_num_results=max_results,
            ),
        )

    web_search = (
        knowledge.get("web_search")
        if isinstance(knowledge.get("web_search"), dict)
        else {}
    )
    web_search_enabled = bool(web_search.get("enabled"))
    if web_search_enabled:
        allowed_domains = _parse_allowed_domains(web_search.get("allowed_domains"))
        registry.register_tool(
            "knowledge.web_search",
            WebSearchTool(
                filters=WebSearchFilters(allowed_domains=allowed_domains)
                if allowed_domains
                else None,
                search_context_size=_normalize_web_context_size(
                    web_search.get("search_context_size")
                ),
            ),
        )

    for key, raw_config in agent_configs.items():
        prepared_config = copy.deepcopy(raw_config or {})
        _hydrate_tool_settings_from_metadata(prepared_config)
        _hydrate_human_handoff_settings_from_metadata(prepared_config)
        model = str(((prepared_config.get("model") or {}).get("model")) or "")
        _inject_global_context(prepared_config, global_context, performance)
        _inject_global_few_shots(prepared_config, selected_examples)

        if _raw_agent_config_has_audio_voice(prepared_config):
            _ensure_tool_selection(
                prepared_config,
                "audio.request_response",
                "Quando o usuario pedir, aceitar ou demonstrar preferencia por receber a resposta em audio.",
            )

        if file_search_enabled:
            _ensure_tool_selection(
                prepared_config,
                "knowledge.file_search",
                "Consultar documentos e links indexados quando a resposta depender de fatos da empresa.",
            )

        if web_search_enabled:
            if model.startswith("gpt-5"):
                _ensure_tool_selection(
                    prepared_config,
                    "knowledge.web_search",
                    "Pesquisar na web somente quando a resposta depender de informação externa ou atual.",
                )
            else:
                warnings.append(
                    f"{key}: web_search skipped for model {model or 'unknown'}; use a GPT-5 model for live web search"
                )

        prepared[key] = prepared_config

    if selected_examples:
        warnings.append(f"global_few_shots: selected {len(selected_examples)} relevant examples")
    if file_search_enabled:
        warnings.append(f"knowledge.file_search: enabled vector_store={vector_store_id}")
    if web_search_enabled:
        warnings.append("knowledge.web_search: enabled")

    return prepared, registry, warnings


def _raw_agent_config_has_audio_voice(config: Dict[str, Any]) -> bool:
    channel = config.get("channel") if isinstance(config.get("channel"), dict) else {}
    if channel.get("allow_audio") is not True:
        return False
    voice = channel.get("voice") if isinstance(channel.get("voice"), dict) else {}
    return bool(str(voice.get("voice_id") or "").strip())


def _inject_global_context(
    config: Dict[str, Any],
    global_context: Dict[str, Any],
    performance: Dict[str, Any],
) -> None:
    if not global_context or global_context.get("enabled", True) is False:
        return
    if performance.get("include_global_context", True) is False:
        return

    labels = [
        ("company_profile", "Sobre a empresa"),
        ("products_services", "Produtos e servicos"),
        ("brand_voice", "Tom da marca"),
        ("target_audience", "Publico alvo"),
        ("commercial_policy", "Politicas comerciais"),
        ("faq", "FAQ operacional"),
    ]
    lines = []
    for key, label in labels:
        value = str(global_context.get(key) or "").strip()
        if value:
            lines.append(f"## {label}\n{value}")

    if not lines:
        return

    prompt = _prompt_config(config)
    custom_sections = prompt.setdefault("custom_sections", {})
    if isinstance(custom_sections, dict):
        custom_sections["Contexto global da equipe"] = "\n\n".join(lines)


def _inject_global_few_shots(
    config: Dict[str, Any],
    selected_examples: List[Dict[str, Any]],
) -> None:
    if not selected_examples:
        return

    prompt = _prompt_config(config)
    few_shots = prompt.setdefault("few_shots", [])
    if not isinstance(few_shots, list):
        few_shots = []
        prompt["few_shots"] = few_shots

    formatted = []
    for example in selected_examples:
        user = str(example.get("user") or "").strip()
        assistant = str(example.get("assistant") or "").strip()
        if not user or not assistant:
            continue
        title = str(example.get("title") or "").strip()
        tags = str(example.get("tags") or "").strip()
        context_parts = [
            str(example.get("context") or "").strip(),
            f"Tags: {tags}" if tags else "",
            f"Exemplo global: {title}" if title else "Exemplo global da equipe",
        ]
        formatted.append(
            {
                "user": user,
                "assistant": assistant,
                "context": " | ".join(part for part in context_parts if part),
            }
        )

    prompt["few_shots"] = formatted + few_shots


def _ensure_tool_selection(config: Dict[str, Any], tool_id: str, when: str) -> None:
    tools = config.setdefault("tools", [])
    if not isinstance(tools, list):
        tools = []
        config["tools"] = tools
    if not any(isinstance(tool, dict) and tool.get("id") == tool_id for tool in tools):
        tools.append(
            {
                "id": tool_id,
                "enabled": True,
                "requires_approval": False,
                "notes": "Ferramenta global da equipe.",
            }
        )

    prompt = _prompt_config(config)
    policies = prompt.setdefault("tool_policy", [])
    if not isinstance(policies, list):
        policies = []
        prompt["tool_policy"] = policies
    if not any(isinstance(policy, dict) and policy.get("tool") == tool_id for policy in policies):
        policies.append(
            {
                "tool": tool_id,
                "when": when,
                "requires": [],
                "side_effect": False,
                "retry_safety": "consultar apenas quando precisar de contexto adicional",
            }
        )


def _prompt_config(config: Dict[str, Any]) -> Dict[str, Any]:
    prompt = config.setdefault("prompt_techniques", {})
    if not isinstance(prompt, dict):
        prompt = {}
        config["prompt_techniques"] = prompt
    return prompt


def _select_relevant_global_examples(
    *,
    examples: List[Dict[str, Any]],
    message: str,
    max_examples: int,
    enabled: bool,
) -> List[Dict[str, Any]]:
    if not enabled or max_examples <= 0:
        return []

    query_tokens = _tokenize_for_retrieval(message)
    scored: List[tuple[int, int, Dict[str, Any]]] = []
    for index, raw_example in enumerate(examples):
        if not isinstance(raw_example, dict) or raw_example.get("enabled", True) is False:
            continue
        user = str(raw_example.get("user") or "").strip()
        assistant = str(raw_example.get("assistant") or "").strip()
        if not user or not assistant:
            continue

        haystack = " ".join(
            str(raw_example.get(field) or "")
            for field in ("title", "tags", "context", "user", "assistant")
        )
        tokens = _tokenize_for_retrieval(haystack)
        score = len(query_tokens & tokens)
        if score == 0 and query_tokens:
            continue
        scored.append((score, -index, raw_example))

    scored.sort(reverse=True)
    if not scored and not query_tokens:
        return [example for example in examples if isinstance(example, dict)][:max_examples]
    return [example for _, _, example in scored[:max_examples]]


def _tokenize_for_retrieval(text: str) -> set[str]:
    stopwords = {
        "a",
        "as",
        "o",
        "os",
        "e",
        "de",
        "do",
        "da",
        "dos",
        "das",
        "em",
        "para",
        "por",
        "com",
        "que",
        "um",
        "uma",
        "oi",
        "ola",
        "olá",
        "bom",
        "boa",
        "dia",
        "tarde",
        "noite",
    }
    return {
        token
        for token in re.findall(r"[\wÀ-ÿ]{3,}", text.lower())
        if token not in stopwords
    }


def _safe_int(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _safe_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "sim", "on"}:
        return True
    if normalized in {"0", "false", "no", "nao", "não", "off"}:
        return False
    return default


def _optional_positive_int(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _hydrate_tool_settings_from_metadata(config: Dict[str, Any]) -> None:
    if not isinstance(config, dict):
        return
    metadata = config.get("metadata")
    if not isinstance(metadata, dict):
        return
    tool_settings = metadata.get("tool_settings")
    if not isinstance(tool_settings, dict):
        return
    tools = config.get("tools")
    if not isinstance(tools, list):
        return

    for tool in tools:
        if not isinstance(tool, dict):
            continue
        tool_id = str(tool.get("id") or "").strip()
        settings = tool_settings.get(tool_id)
        if tool_id and isinstance(settings, dict) and "settings" not in tool:
            tool["settings"] = settings


def _hydrate_human_handoff_settings_from_metadata(config: Dict[str, Any]) -> None:
    if not isinstance(config, dict):
        return
    metadata = config.get("metadata")
    if not isinstance(metadata, dict):
        return
    targets = metadata.get("human_handoff_targets")
    if not isinstance(targets, list):
        return
    tools = config.get("tools")
    if not isinstance(tools, list):
        return

    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if str(tool.get("id") or "").strip() != "human_handoff.create_task":
            continue
        settings = tool.setdefault("settings", {})
        if isinstance(settings, dict) and "targets" not in settings:
            settings["targets"] = targets


def _normalize_web_context_size(value: Any) -> str:
    if value in {"low", "medium", "high"}:
        return str(value)
    return "low"


def _parse_allowed_domains(value: Any) -> List[str]:
    if isinstance(value, list):
        raw_domains = value
    else:
        raw_domains = re.split(r"[,;\n]", str(value or ""))
    domains = []
    for item in raw_domains:
        domain = str(item).strip().lower()
        domain = re.sub(r"^https?://", "", domain).split("/")[0]
        if domain and domain not in domains:
            domains.append(domain)
    return domains[:100]


def _evaluate_custom_guardrails(
    config: AgentCreationConfig,
    stage: str,
    text: str,
) -> Optional[Dict[str, Any]]:
    for guardrail in config.custom_guardrails:
        if not guardrail.enabled or guardrail.stage != stage:
            continue
        triggered = False
        if guardrail.check_type == "regex":
            try:
                triggered = bool(re.search(guardrail.condition, text, flags=re.IGNORECASE))
            except re.error:
                logger.warning("[AgentWorkforceRunner] Invalid guardrail regex: %s", guardrail.key)
        elif guardrail.check_type == "keyword_filter":
            keywords = [
                item.strip().lower()
                for item in re.split(r"[,;\n]", guardrail.condition)
                if item.strip()
            ]
            lowered = text.lower()
            triggered = any(keyword in lowered for keyword in keywords)

        if triggered:
            return {
                "key": guardrail.key,
                "name": guardrail.name,
                "stage": guardrail.stage,
                "target_tool_id": guardrail.target_tool_id,
                "action": guardrail.action,
                "message": guardrail.message
                or "Não consigo continuar com segurança por aqui.",
                "condition": guardrail.condition,
                "check_type": guardrail.check_type,
            }
    return None


def _redact_by_guardrail(text: str, guardrail: Dict[str, Any]) -> str:
    if guardrail.get("check_type") != "regex":
        return text
    try:
        return re.sub(guardrail["condition"], "[redigido]", text, flags=re.IGNORECASE)
    except re.error:
        return text


def _dict_or_empty(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _runtime_image_payloads(runtime_variables: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    variables = _dict_or_empty(runtime_variables)
    trigger = _dict_or_empty(variables.get("trigger"))
    payloads: List[Dict[str, str]] = []
    seen_sources: set[str] = set()

    def add_payload(raw_payload: Any) -> None:
        payload = _dict_or_empty(raw_payload)
        source = str(
            payload.get("imageUrl")
            or payload.get("image_url")
            or payload.get("mediaUrl")
            or payload.get("media_url")
            or payload.get("url")
            or ""
        ).strip()
        if not source or source in seen_sources:
            return
        seen_sources.add(source)
        payloads.append(
            {
                "image_url": source,
                "caption": str(payload.get("caption") or "").strip(),
                "mimetype": str(payload.get("mimetype") or payload.get("mime_type") or "").strip(),
            }
        )

    for source_payload in (
        trigger.get("images"),
        variables.get("images"),
        trigger.get("debounced_images"),
        variables.get("debounced_images"),
    ):
        if isinstance(source_payload, list):
            for item in source_payload:
                add_payload(item)

    for source_payload in (
        trigger.get("image"),
        variables.get("image"),
    ):
        add_payload(source_payload)

    trigger_type = str(trigger.get("type") or variables.get("type") or "").strip().lower()
    mimetype = str(trigger.get("mimetype") or variables.get("mimetype") or "").strip().lower()
    if trigger_type == "image" or mimetype.startswith("image/"):
        add_payload(
            {
                "imageUrl": trigger.get("mediaUrl")
                or trigger.get("imageUrl")
                or variables.get("mediaUrl")
                or variables.get("imageUrl"),
                "caption": trigger.get("caption") or variables.get("caption"),
                "mimetype": trigger.get("mimetype") or variables.get("mimetype"),
            }
        )

    return payloads


def _runtime_image_input_parts(runtime_variables: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    image_detail = os.getenv("OPENAI_AGENT_IMAGE_DETAIL") or "auto"
    parts: List[Dict[str, str]] = []
    for payload in _runtime_image_payloads(runtime_variables):
        source = payload.get("image_url", "")
        try:
            parts.append(build_openai_image_input_part(source, detail=image_detail))
        except Exception as exc:
            logger.warning(
                "[AgentWorkforceRunner] Failed to build OpenAI image input part: %s",
                exc,
            )
    return parts


def _image_text_fallback_message(
    message: str,
    runtime_variables: Optional[Dict[str, Any]],
    *,
    db: Session,
    company_id: int,
) -> str:
    payloads = _runtime_image_payloads(runtime_variables)
    if not payloads:
        return message

    payload = payloads[0]
    image_source = payload.get("image_url", "")
    caption = payload.get("caption", "")
    fallback_text = ""
    if image_source:
        api_key = get_company_openai_api_key(db, company_id)
        fallback_text = analyze_image_with_openai(
            image_source,
            api_key=api_key,
            caption=caption,
        )
        if not fallback_text:
            fallback_text = analyze_image_with_google_vision(image_source)

    message_text = str(message or "").strip()
    if fallback_text and message_text:
        return f"{message_text}\n\n{fallback_text}"
    if fallback_text:
        return fallback_text
    return message_text or "[Imagem recebida - Não foi possível analisar a imagem]"


def _should_retry_image_input_as_text(exc: Exception) -> bool:
    message = str(exc).lower()
    retry_markers = (
        "image",
        "input_image",
        "content",
        "data url",
        "unsupported",
        "invalid",
        "badrequest",
        "bad request",
    )
    return any(marker in message for marker in retry_markers)


def _build_runner_input(
    message: str,
    conversation_history: List[Dict[str, str]],
    *,
    image_input_parts: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for item in _normalize_conversation_history(conversation_history):
        items.append(item)

    if image_input_parts:
        text = str(message or "").strip() or "Imagem recebida via WhatsApp."
        items.append(
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": text},
                    *image_input_parts,
                ],
            }
        )
    else:
        items.append({"role": "user", "content": message})
    return items


def _normalize_conversation_history(
    conversation_history: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for item in conversation_history or []:
        if not isinstance(item, dict):
            continue
        role = item.get("role", "user")
        if role not in {"user", "assistant", "system", "developer"}:
            role = "user"
        content = str(item.get("content", "") or "").strip()
        if content:
            items.append({"role": role, "content": content})
    return items


def _load_recent_conversation_history(
    *,
    db: Session,
    company_id: int,
    contact_phone: Optional[str],
    current_message: str,
    limit: int = 24,
) -> List[Dict[str, str]]:
    if not contact_phone:
        return []

    phone_candidates = _phone_candidates(contact_phone)
    if not phone_candidates:
        return []

    try:
        recent_messages = (
            db.query(Message)
            .filter(
                Message.company_id == company_id,
                Message.contact_phone.in_(phone_candidates),
            )
            .order_by(Message.timestamp.desc(), Message.id.desc())
            .limit(max(limit, 1) + 3)
            .all()
        )
    except Exception:
        logger.exception(
            "[AgentWorkforceRunner] Failed to load conversation history for company=%s phone=%s",
            company_id,
            contact_phone,
        )
        return []

    ordered = list(reversed(recent_messages))
    current = str(current_message or "").strip()
    if ordered and not ordered[-1].from_me and str(ordered[-1].content or "").strip() == current:
        ordered = ordered[:-1]

    history_rows = ordered[-limit:]
    audio_transcripts = _load_generated_audio_history_transcripts(
        db=db,
        company_id=company_id,
        phone_candidates=phone_candidates,
        messages=history_rows,
    )

    history: List[Dict[str, str]] = []
    for row in history_rows:
        content = _message_content_for_agent_history(row, audio_transcripts=audio_transcripts)
        if not content:
            continue
        history.append(
            {
                "role": "assistant" if row.from_me else "user",
                "content": content,
            }
        )
    return history


def _load_generated_audio_history_transcripts(
    *,
    db: Session,
    company_id: int,
    phone_candidates: List[str],
    messages: List[Message],
) -> Dict[int, str]:
    audio_messages = [
        row
        for row in messages
        if getattr(row, "from_me", False) and _history_message_type(row) == "audio"
    ]
    if not audio_messages or not phone_candidates:
        return {}

    audio_times = [
        timestamp
        for timestamp in (
            _history_datetime_utc_naive(getattr(row, "timestamp", None))
            for row in audio_messages
        )
        if timestamp is not None
    ]
    if not audio_times:
        return {}

    start_at = min(audio_times) - timedelta(seconds=AUDIO_HISTORY_TRANSCRIPT_LOOKBACK_SECONDS)
    end_at = max(audio_times) + timedelta(seconds=AUDIO_HISTORY_TRANSCRIPT_FORWARD_SECONDS)

    try:
        executions = (
            db.query(AgentExecution)
            .filter(
                AgentExecution.company_id == company_id,
                AgentExecution.phone.in_(phone_candidates),
                AgentExecution.created_at >= start_at,
                AgentExecution.created_at <= end_at,
            )
            .order_by(AgentExecution.created_at.asc(), AgentExecution.id.asc())
            .all()
        )
    except Exception:
        logger.exception(
            "[AgentWorkforceRunner] Failed to load generated audio context for company=%s phones=%s",
            company_id,
            phone_candidates,
        )
        return {}

    return _match_audio_history_transcripts(audio_messages, executions)


def _match_audio_history_transcripts(
    audio_messages: List[Any],
    executions: List[Any],
) -> Dict[int, str]:
    execution_candidates: List[tuple[datetime, Any, str]] = []
    for execution in executions:
        created_at = _history_datetime_utc_naive(getattr(execution, "created_at", None))
        text = _generated_audio_text_from_execution(execution)
        if created_at is None or not text:
            continue
        execution_candidates.append((created_at, execution, text))

    if not execution_candidates:
        return {}

    used_execution_ids: set[Any] = set()
    transcripts: Dict[int, str] = {}
    sorted_messages = sorted(
        audio_messages,
        key=lambda row: _history_datetime_utc_naive(getattr(row, "timestamp", None))
        or datetime.min,
    )
    for row in sorted_messages:
        row_id = getattr(row, "id", None)
        audio_time = _history_datetime_utc_naive(getattr(row, "timestamp", None))
        if row_id is None or audio_time is None:
            continue

        nearest: Optional[tuple[float, Any, str]] = None
        for execution_time, execution, text in execution_candidates:
            execution_id = getattr(execution, "id", None)
            if execution_id is not None and execution_id in used_execution_ids:
                continue
            delta_seconds = (audio_time - execution_time).total_seconds()
            if (
                delta_seconds < -AUDIO_HISTORY_TRANSCRIPT_FORWARD_SECONDS
                or delta_seconds > AUDIO_HISTORY_TRANSCRIPT_LOOKBACK_SECONDS
            ):
                continue
            distance = abs(delta_seconds)
            if nearest is None or distance < nearest[0]:
                nearest = (distance, execution, text)

        if nearest is None:
            continue
        _, execution, text = nearest
        transcripts[int(row_id)] = text
        execution_id = getattr(execution, "id", None)
        if execution_id is not None:
            used_execution_ids.add(execution_id)

    return transcripts


def _generated_audio_text_from_execution(execution: Any) -> str:
    metadata = getattr(execution, "execution_metadata", None)
    audio_metadata = metadata.get("audio") if isinstance(metadata, dict) else None
    if isinstance(audio_metadata, dict) and "should_send_audio" in audio_metadata:
        if not bool(audio_metadata.get("should_send_audio")):
            return ""

    text = _audio_history_text_from_execution_metadata(metadata)
    if text:
        return text
    if not (
        isinstance(metadata, dict)
        and (
            isinstance(metadata.get("audio_delivery_request"), dict)
            or isinstance(audio_metadata, dict)
        )
    ):
        return ""
    return _normalize_audio_history_text(getattr(execution, "agent_response", ""))


def _audio_history_text_from_execution_metadata(metadata: Any) -> str:
    if not isinstance(metadata, dict):
        return ""

    audio_metadata = metadata.get("audio")
    if isinstance(audio_metadata, dict) and "should_send_audio" in audio_metadata:
        if not bool(audio_metadata.get("should_send_audio")):
            return ""

    delivery_request = metadata.get("audio_delivery_request")
    if isinstance(delivery_request, dict):
        request_text = _normalize_audio_history_text(delivery_request.get("spoken_text"))
        if request_text:
            return request_text

    if isinstance(audio_metadata, dict):
        for key in ("audio_text", "spoken_text", "request_text", "text_processed"):
            audio_text = _normalize_audio_history_text(audio_metadata.get(key))
            if audio_text:
                return audio_text

        split_parts = audio_metadata.get("split_parts")
        if isinstance(split_parts, list):
            parts = [
                str(part or "").strip()
                for part in split_parts
                if str(part or "").strip()
            ]
            if str(audio_metadata.get("delivery_mode") or "").strip() == "text_then_audio_tail":
                parts = parts[1:] if len(parts) > 1 else parts
            split_text = _normalize_audio_history_text(" ".join(parts))
            if split_text:
                return split_text

    for key in ("audio_text", "spoken_text", "request_text"):
        text = _normalize_audio_history_text(metadata.get(key))
        if text:
            return text

    return ""


def _history_datetime_utc_naive(value: Any) -> Optional[datetime]:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _normalize_audio_history_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= AUDIO_HISTORY_TRANSCRIPT_MAX_CHARS:
        return text
    return f"{text[:AUDIO_HISTORY_TRANSCRIPT_MAX_CHARS - 3].rstrip()}..."


def _history_message_type(row: Any) -> str:
    return str(getattr(row, "message_type", "") or "text").strip().lower()


def _message_content_for_agent_history(
    row: Message,
    audio_transcripts: Optional[Dict[int, str]] = None,
) -> str:
    message_type = _history_message_type(row)
    content = str(getattr(row, "content", "") or "").strip()

    if message_type == "text":
        return content

    label = {
        "image": "Imagem",
        "audio": "Audio",
        "video": "Video",
        "file": "Arquivo",
        "contact": "Contato",
        "sticker": "Sticker",
    }.get(message_type, "Mensagem")
    direction = "enviada pela empresa" if getattr(row, "from_me", False) else "recebida do cliente"

    if message_type == "audio" and getattr(row, "from_me", False):
        transcript = (audio_transcripts or {}).get(getattr(row, "id", None))
        if transcript:
            return f"[{label} {direction}: {transcript}]"
    if message_type == "contact" and content:
        return f"[{label} {direction}: {content}]"
    return f"[{label} {direction}]"


def _phone_candidates(phone: str) -> List[str]:
    raw = str(phone or "").strip()
    digits = re.sub(r"\D+", "", raw)
    candidates: List[str] = []
    for value in (raw, digits):
        if value and value not in candidates:
            candidates.append(value)
    if digits.startswith("55") and len(digits) > 11:
        local = digits[2:]
        if local not in candidates:
            candidates.append(local)
    elif len(digits) in {10, 11}:
        brazil = f"55{digits}"
        if brazil not in candidates:
            candidates.append(brazil)
    return candidates


def _build_trace_context(
    *,
    workforce: AgentWorkforce,
    company_id: int,
    root_agent_key: str,
    runtime_context: AgentWorkforceRunContext,
    flow_id: Optional[int],
    node_id: Optional[str],
    provider_message_id: Optional[str],
) -> Dict[str, Any]:
    phone = runtime_context.contact_phone or "unknown"
    safe_workforce_name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", workforce.name).strip("_")
    workflow_name = f"agent_workforce.{company_id}.{workforce.id}.{safe_workforce_name or 'workforce'}"
    group_id = f"conv_{phone}_company{company_id}"
    trace_id = f"trace_aw_{company_id}_{workforce.id}_{uuid.uuid4().hex[:16]}"
    metadata = _string_trace_metadata({
        "source": "flow_builder_agent_workforce",
        "company_id": company_id,
        "flow_id": flow_id,
        "node_id": node_id,
        "workforce_id": workforce.id,
        "workforce_name": workforce.name,
        "root_agent_key": root_agent_key,
        "contact_phone": phone,
        "channel": runtime_context.channel,
        "provider_message_id": provider_message_id,
    })
    return {
        "workflow_name": workflow_name,
        "group_id": group_id,
        "trace_id": trace_id,
        "metadata": metadata,
    }


def _string_trace_metadata(metadata: Dict[str, Any]) -> Dict[str, str]:
    return {
        key: "" if value is None else str(value)
        for key, value in metadata.items()
    }


async def _run_agent_sdk(
    *,
    agent: Agent[Any],
    runner_input: List[Dict[str, Any]],
    runtime_context: AgentWorkforceRunContext,
    max_turns: int,
    trace_context: Dict[str, Any],
    run_config: Any,
) -> Any:
    with openai_run_trace(
        run_config,
        workflow_name=trace_context["workflow_name"],
        group_id=trace_context["group_id"],
        trace_id=trace_context["trace_id"],
        metadata=trace_context["metadata"],
    ):
        return await Runner.run(
            agent,
            runner_input,
            context=runtime_context,
            max_turns=max_turns,
            run_config=run_config,
        )


def _run_coroutine_sync(coro_factory: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(lambda: asyncio.run(coro_factory()))
        return future.result()


def _find_agent_key(agents_by_key: Dict[str, Agent[Any]], agent: Agent[Any]) -> Optional[str]:
    for key, candidate in agents_by_key.items():
        if candidate is agent:
            return key
    for key, candidate in agents_by_key.items():
        if candidate.name == agent.name:
            return key
    return None


def _raw_run_item_value(raw_item: Any, key: str) -> Any:
    if isinstance(raw_item, dict):
        return raw_item.get(key)
    return getattr(raw_item, key, None)


def _run_item_tool_name(item: Any) -> Optional[str]:
    raw_item = getattr(item, "raw_item", None)
    value = (
        getattr(item, "tool_name", None)
        or _raw_run_item_value(raw_item, "name")
        or _raw_run_item_value(raw_item, "tool_name")
    )
    return str(value) if value else None


def _decode_calendar_tool_output(item: Any) -> Optional[Dict[str, Any]]:
    value = getattr(item, "output", None)
    if value is None:
        value = _raw_run_item_value(getattr(item, "raw_item", None), "output")

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        value = model_dump()

    for _ in range(2):
        if not isinstance(value, str):
            break
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return None

    return value if isinstance(value, dict) else None


def _calendar_tool_events(result: Any) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    events_by_call_id: Dict[str, Dict[str, Any]] = {}

    for item in getattr(result, "new_items", []) or []:
        item_type = str(
            getattr(item, "type", None) or item.__class__.__name__
        ).lower()
        raw_item = getattr(item, "raw_item", None)
        call_id_value = _raw_run_item_value(raw_item, "call_id")
        call_id = str(call_id_value) if call_id_value else None

        if item_type == "tool_call_item":
            tool_name = _run_item_tool_name(item)
            if tool_name not in CALENDAR_TOOL_NAMES:
                continue
            event = {
                "tool_name": tool_name,
                "result": None,
            }
            events.append(event)
            if call_id:
                events_by_call_id[call_id] = event
            continue

        if item_type != "tool_call_output_item" or not call_id:
            continue
        event = events_by_call_id.get(call_id)
        if event is not None:
            event["result"] = _decode_calendar_tool_output(item)

    return events


def _safe_calendar_error_code(value: Any) -> Optional[str]:
    if not value:
        return None
    normalized = str(value).strip()
    if re.fullmatch(r"[a-z][a-z0-9_.:-]{0,79}", normalized):
        return normalized
    return "unclassified_error"


def _calendar_tool_result_summaries(
    calendar_tool_events: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    summaries: List[Dict[str, Any]] = []
    for event in calendar_tool_events:
        result = event.get("result")
        payload = result if isinstance(result, dict) else {}
        slots = payload.get("slots")
        next_slots = payload.get("next_available_slots")
        summaries.append(
            {
                "tool_name": event.get("tool_name"),
                "success": payload.get("success")
                if isinstance(payload.get("success"), bool)
                else None,
                "error": _safe_calendar_error_code(payload.get("error")),
                "slot_count": len(slots) if isinstance(slots, list) else 0,
                "next_slot_count": len(next_slots)
                if isinstance(next_slots, list)
                else 0,
            }
        )
    return summaries


def _calendar_slot_displays(value: Any, *, limit: int) -> List[str]:
    if not isinstance(value, list):
        return []

    displays: List[str] = []
    for slot in value:
        if not isinstance(slot, dict):
            continue
        display = str(slot.get("display") or "").strip()
        if not display or len(display) > 100 or display in displays:
            continue
        displays.append(display)
        if len(displays) >= limit:
            break
    return displays


def _calendar_suggestion_limit(payload: Dict[str, Any]) -> int:
    try:
        parsed = int(payload.get("max_suggestions") or 3)
    except (TypeError, ValueError):
        parsed = 3
    return max(1, min(parsed, 6))


def _claims_calendar_lookup_failure(response_text: str) -> bool:
    normalized = _normalize_audio_refusal_text(response_text)
    return any(marker in normalized for marker in CALENDAR_LOOKUP_FAILURE_MARKERS)


def _format_calendar_options_response(
    displays: List[str],
    *,
    requested_range_has_slots: bool,
) -> str:
    heading = (
        "Encontrei estes horários disponíveis:"
        if requested_range_has_slots
        else (
            "Não encontrei horários no período solicitado. "
            "As próximas opções disponíveis são:"
        )
    )
    options = "\n".join(
        f"{index}. {display}" for index, display in enumerate(displays, start=1)
    )
    return f"{heading}\n{options}\nQual opção você prefere?"


def _enforce_calendar_availability_response(
    *,
    response_text: str,
    calendar_tool_events: List[Dict[str, Any]],
) -> tuple[str, bool, Optional[str]]:
    if not calendar_tool_events:
        return response_text, False, None

    latest_event = calendar_tool_events[-1]
    if latest_event.get("tool_name") != CALENDAR_FIND_TOOL_NAME:
        return response_text, False, None

    payload = latest_event.get("result")
    if not isinstance(payload, dict) or payload.get("success") is not True:
        return response_text, False, None

    limit = _calendar_suggestion_limit(payload)
    slots = _calendar_slot_displays(payload.get("slots"), limit=limit)
    next_slots = _calendar_slot_displays(
        payload.get("next_available_slots"),
        limit=limit,
    )
    selected_displays = slots or next_slots
    response_casefold = response_text.casefold()
    contains_returned_slot = any(
        display.casefold() in response_casefold for display in selected_displays
    )
    claims_lookup_failure = _claims_calendar_lookup_failure(response_text)

    if selected_displays and contains_returned_slot and not claims_lookup_failure:
        return response_text, False, None

    if selected_displays:
        return (
            _format_calendar_options_response(
                selected_displays,
                requested_range_has_slots=bool(slots),
            ),
            True,
            (
                "successful_lookup_reported_as_failure"
                if claims_lookup_failure
                else "successful_lookup_slots_missing_from_response"
            ),
        )

    if claims_lookup_failure:
        return (
            (
                "Não encontrei horários disponíveis nesse período. "
                "Quer que eu consulte outra data ou período?"
            ),
            True,
            "successful_empty_lookup_reported_as_failure",
        )

    return response_text, False, None


def _summarize_run_items(result: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for item in getattr(result, "new_items", []) or []:
        raw_item = getattr(item, "raw_item", None)
        item_type = getattr(item, "type", None) or item.__class__.__name__
        tool_name = _run_item_tool_name(item)
        if tool_name or "tool" in str(item_type).lower() or "handoff" in str(item_type).lower():
            items.append(
                {
                    "type": str(item_type),
                    "tool_name": tool_name,
                    "agent": getattr(getattr(item, "agent", None), "name", None),
                }
            )
    return items


def _log_agent_execution(
    *,
    db: Session,
    company_id: int,
    phone: Optional[str],
    workflow_name: str,
    trace_id: Optional[str],
    conversation_group: Optional[str],
    user_input: str,
    agent_response: str,
    execution_time_ms: int,
    tokens_used: int,
    tools_called: List[Dict[str, Any]],
    status: str,
    metadata: Dict[str, Any],
    error_message: Optional[str] = None,
) -> Optional[int]:
    try:
        execution = AgentExecution(
            company_id=company_id,
            phone=phone or "unknown",
            conversation_group=conversation_group,
            workflow_name=workflow_name,
            trace_id=trace_id,
            user_input=user_input,
            agent_response=agent_response,
            execution_time_ms=execution_time_ms,
            tokens_used=tokens_used,
            tools_called=tools_called,
            execution_metadata=metadata,
            status=status,
            error_message=error_message,
        )
        db.add(execution)
        db.commit()
        return int(execution.id) if execution.id is not None else None
    except Exception:
        db.rollback()
        logger.exception("[AgentWorkforceRunner] Failed to persist agent execution")
        return None
