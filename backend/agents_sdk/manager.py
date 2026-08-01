"""
Business Company Manager - Business logic and orchestration
Enhanced with structured context and detailed tracing
"""

import copy
import json
import logging
import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import bindparam, text

from agents import FunctionTool, Runner, function_tool, SQLiteSession
from backend.services.ai_provider_service import (
    build_company_openai_run_config,
    openai_run_trace,
    safe_ai_provider_runtime_error,
)
from backend.services.ai_usage_service import safe_record_tts_usage

from .agents.coordinator_agent import coordinator_agent
from .agents.contact_identification_agent import contact_identification_agent
from .agents.client_support_agent import client_support_agent
from .context import CompanyDataService, CustomerContext, CustomerContextManager
from .tools import SlotsService
from .services.database_scheduling_service import DatabaseSchedulingService
from .services.lead_conversion_service import CustomerConversionService
from .tracing import tracer
from .database import AgentExecution
from .prompts import CompanyContext
from .config.model_config import get_model_config
from .voice import AudioService, AudioRequest, AudioResponse

logger = logging.getLogger(__name__)


def _bind_tool_to_company(
    tool: FunctionTool,
    company_id: int,
) -> FunctionTool:
    """Hide and override company_id for tools invoked by an LLM."""

    schema = copy.deepcopy(tool.params_json_schema)
    properties = schema.get("properties")
    if not isinstance(properties, dict) or "company_id" not in properties:
        return tool

    properties.pop("company_id", None)
    required = schema.get("required")
    if isinstance(required, list):
        schema["required"] = [
            field for field in required if field != "company_id"
        ]

    async def invoke_with_active_company(context: Any, input_json: str) -> Any:
        payload = json.loads(input_json or "{}")
        if not isinstance(payload, dict):
            raise ValueError("Tool input must be a JSON object")
        payload["company_id"] = int(company_id)
        return await tool.on_invoke_tool(
            context,
            json.dumps(payload, ensure_ascii=False),
        )

    return FunctionTool(
        name=tool.name,
        description=tool.description,
        params_json_schema=schema,
        on_invoke_tool=invoke_with_active_company,
        strict_json_schema=tool.strict_json_schema,
        is_enabled=tool.is_enabled,
        tool_input_guardrails=tool.tool_input_guardrails,
        tool_output_guardrails=tool.tool_output_guardrails,
    )


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


def _agent_history_content(message_type: str, content: str, from_me: bool) -> str:
    normalized_type = str(message_type or "text").strip().lower()
    clean_content = str(content or "").strip()

    if normalized_type == "text":
        return clean_content

    label = {
        "image": "Imagem",
        "audio": "Audio",
        "video": "Video",
        "file": "Arquivo",
        "contact": "Contato",
        "sticker": "Sticker",
    }.get(normalized_type, "Mensagem")
    direction = "enviada pela empresa" if from_me else "recebida do cliente"

    if normalized_type == "contact" and clean_content:
        return f"[{label} {direction}: {clean_content}]"
    return f"[{label} {direction}]"


class AgentExecutionManager:
    """
    Main manager class that orchestrates agent operations for any organization.
    Formerly BusinessCompanyManager.
    """

    def __init__(self, company_id: int, db: Session):
        self.company_id = company_id
        self.db = db
        self.organization_data_service = CompanyDataService(db)
        self.slots_service = SlotsService(db)
        self.scheduling_service = DatabaseSchedulingService(db, company_id)  # Use real scheduling
        self.audio_service = AudioService(db, company_id)  # Audio service integration
        self.lead_conversion_service = CustomerConversionService(db)  # NEW: Customer conversion service
        self._company_data = None

        # NEW: Initialize structured context manager
        self.contact_context_manager = CustomerContextManager(db)

        # NEW: Initialize specialized agents
        self._setup_specialized_agents()

        logger.info(f"✅ Using standard SQLiteSession for conversation memory (company {company_id})")
        logger.info(f"✅ Using DatabaseSchedulingService for real integrations (company {company_id})")
        logger.info(f"✅ AudioService initialized for company {company_id}")
        logger.info(f"✅ CustomerContextManager initialized for structured context (company {company_id})")

    def _get_company_data(self) -> Dict[str, Any]:
        """Get processed company data for context"""
        if self._company_data is None:
            self._company_data = self.organization_data_service.get_company_data(self.company_id)
        return self._company_data

    def _get_session_id(self, phone: str) -> str:
        """Generate consistent session ID for SQLiteSession"""
        return f"{phone}_company{self.company_id}"

    def _get_session(self, phone: str) -> SQLiteSession:
        """Get or create SQLiteSession following OpenAI documentation"""
        session_id = self._get_session_id(phone)
        # Use file-based SQLiteSession as shown in documentation (line 134)
        session = SQLiteSession(session_id, "conversations.db")
        return session

    async def _safe_import_history(self, phone: str, session: SQLiteSession):
        """Safely import existing history following OpenAI documentation patterns"""
        try:
            phone_candidates = _phone_candidates(phone)
            if not phone_candidates:
                return

            # Import recent chat messages from database (last 50 records for context).
            # Non-text media is represented as a compact event marker so outside
            # WhatsApp Web/cell actions are still visible to the agent context.
            query = text("""
                SELECT from_me, content, message_type
                FROM messages
                WHERE company_id = :company_id
                    AND contact_phone IN :phone_candidates
                    AND message_type IN ('text', 'image', 'audio', 'video', 'file', 'contact', 'sticker')
                ORDER BY timestamp DESC
                LIMIT 50
            """).bindparams(bindparam("phone_candidates", expanding=True))
            result = self.db.execute(query, {
                "company_id": self.company_id,
                "phone_candidates": phone_candidates,
            }).fetchall()

            # Convert to OpenAI format exactly as documentation shows
            items_to_add = []
            for row in reversed(result):  # Reverse to get chronological order
                content = _agent_history_content(row.message_type, row.content, row.from_me)
                if not content:
                    continue

                # DEBUG: Log role assignment decision
                logger.debug(f"[IMPORT_DEBUG] Row: from_me={row.from_me}, content='{content[:50]}...'")

                # Clean role assignment following documentation pattern
                role = "assistant" if row.from_me else "user"

                logger.debug(f"[IMPORT_DEBUG] Assigned role={role} based on from_me={row.from_me}")

                # Validate item format matches TResponseInputItem protocol
                item = {"role": role, "content": content}
                items_to_add.append(item)

            # Import using official add_items method (documentation line 75)
            if items_to_add:
                # DEBUG: Log what we're about to import
                logger.critical(f"[SESSION_DEBUG] About to import {len(items_to_add[-20:])} messages from DB:")
                for idx, item in enumerate(items_to_add[-5:]):
                    logger.critical(f"  [{idx}] role={item['role']}, content='{item['content'][:50]}...'")

                await session.add_items(items_to_add[-20:])  # Import only last 20 for performance
                logger.info(f"✅ Imported {len(items_to_add[-20:])} recent messages following OpenAI documentation")

        except Exception as e:
            logger.error(f"[HISTORY_IMPORT] Error importing history for {phone}: {e}")
            # Continue without import - session starts fresh

    def _setup_specialized_agents(self):
        """Setup specialized agents with bidirectional handoffs"""
        try:
            from agents import handoff
            from .agents.third_party_booking_agent import third_party_booking_agent

            logger.info(f"🔧 Setting up specialized agents for company {self.company_id}")

            # Configure handoffs from main agent to specialized agents
            if not hasattr(coordinator_agent, 'handoffs'):
                coordinator_agent.handoffs = []

            # Add customer identification agent
            coordinator_agent.handoffs.extend([
                contact_identification_agent,
                handoff(
                    agent=client_support_agent,
                    on_handoff=self._on_customer_support_handoff
                ),
                handoff(
                    agent=third_party_booking_agent,
                    on_handoff=self._on_third_party_handoff
                )
            ])

            # Configure bidirectional handoffs - specialized agents can return to main
            if not hasattr(contact_identification_agent, 'handoffs'):
                contact_identification_agent.handoffs = []
            contact_identification_agent.handoffs.extend([coordinator_agent, client_support_agent])

            if not hasattr(client_support_agent, 'handoffs'):
                client_support_agent.handoffs = []
            client_support_agent.handoffs.append(coordinator_agent)

            # Third party agent can handoff to customer support or return to main
            if not hasattr(third_party_booking_agent, 'handoffs'):
                third_party_booking_agent.handoffs = []
            third_party_booking_agent.handoffs.extend([client_support_agent, coordinator_agent])

            logger.info("✅ Specialized agents configured with bidirectional handoffs")

        except Exception as e:
            logger.error(f"❌ Failed to setup specialized agents: {e}")
            # Continue without specialized agents - fallback to main agent only

    async def _detect_third_party_intent(
        self,
        user_input: str,
        phone: str,
        session,
        contact_context
    ) -> Optional[Dict[str, Any]]:
        """
        Detect third-party booking intent using LLM.
        Works from any conversation stage with pure LLM detection.
        """
        try:
            # Use LLM detection from any stage - let the LLM decide based on full context
            from .tools.third_party_detection import detect_third_party_booking_intent

            # Get conversation history
            history = []
            if hasattr(session, 'get_items'):
                items = await session.get_items()
                history = items[-6:] if len(items) > 6 else items

            # Build comprehensive context for LLM
            detection = detect_third_party_booking_intent(
                message=user_input,
                context={
                    'current_stage': contact_context.current_stage or 'initial',
                    'selected_appointment_date': getattr(contact_context, 'selected_date', None),
                    'selected_appointment_time': getattr(contact_context, 'selected_time', None),
                    'conversation_step': contact_context.conversation_step
                },
                conversation_history=history,
                db=self.db,
                company_id=self.company_id,
            )

            # Log detection result for debugging
            if detection:
                logger.info(f"[ThirdPartyDetection] LLM Result: "
                           f"intent={detection.get('intent')}, "
                           f"confidence={detection.get('confidence')}, "
                           f"relationship={detection.get('relationship')}")

            # Return detection if high confidence third-party booking
            # Require confidence >= 0.7 to avoid false positives
            if (detection and
                detection.get('intent') == 'third_party_booking' and
                detection.get('confidence', 0) >= 0.7):
                return detection

            return None

        except Exception as e:
            logger.error(f"[ThirdPartyDetection] Error: {e}")
            return None

    async def _on_third_party_handoff(self, context):
        """Hook executed when handing off to third party booking agent"""
        try:
            logger.info(f"🔄 Third party booking handoff initiated")
            # Context is already prepared by process_conversation
        except Exception as e:
            logger.warning(f"⚠️ Error in third party handoff hook: {e}")

    async def _on_customer_support_handoff(self, context):
        """Hook executed when handing off to customer support agent"""
        try:
            if hasattr(context, 'context') and hasattr(context.context, 'company_id'):
                context.context.db = self.db  # Ensure database access
                context.context.stage = "customer_support"
                context.context.last_interaction = "handoff_to_customer_support"
                logger.info(f"🔄 Customer support handoff configured for company {context.context.company_id}")
        except Exception as e:
            logger.warning(f"⚠️ Error in customer support handoff hook: {e}")

    async def process_conversation(
        self,
        phone: str,
        user_input: str,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Main conversation processing method

        Args:
            phone: User's phone number
            user_input: User's message
            conversation_history: Optional conversation context

        Returns:
            Dict with response and metadata
        """
        execution_start = datetime.now()

        from backend.services.ai_credit_guard import ai_credit_block_result_from_balance

        credit_block = ai_credit_block_result_from_balance(
            db=self.db,
            company_id=self.company_id,
            source="agents_sdk_manager",
        )
        if credit_block:
            return credit_block

        # DEBUG: Log para rastrear origem da chamada
        import traceback
        logger.critical(f"[SESSION_DEBUG] ===== NEW CALL TO process_conversation =====")
        logger.critical(f"[SESSION_DEBUG] Phone: {phone}")
        logger.critical(f"[SESSION_DEBUG] User input: '{user_input[:100]}...'")
        logger.critical(f"[SESSION_DEBUG] Timestamp: {execution_start}")
        logger.critical(f"[SESSION_DEBUG] Call stack (last 3 frames):")
        for frame in traceback.extract_stack()[-4:-1]:
            logger.critical(f"  -> {frame.filename}:{frame.lineno} in {frame.name}")

        try:
            # NEW: Get or create structured customer context
            contact_context = self.contact_context_manager.get_or_create_context(
                company_id=self.company_id,
                phone=phone
            )

            # Update with current interaction
            contact_context.last_interaction = user_input[:200]  # Store for context

            # Prepare context (EXISTING CODE - unchanged)
            company_data = self._get_company_data()
            company_context = CompanyContext(
                company_id=self.company_id,
                phone=phone,
                company_data=company_data,
                db=self.db
            )

            # NEW: Attach structured context to company context
            company_context.structured_context = contact_context

            # Check if we're in referral collection mode
            is_collecting_referrals = self._check_referral_collection_mode(phone)
            if is_collecting_referrals:
                logger.info(f"[REFERRAL_MODE] Modo de coleta de indicações ATIVO para {phone}")
                contact_context.set_collection_mode('referral', {'active': True})

            # NEW: Check if this is a referred lead (indicado)
            referral_context = self._check_referral_context(phone)
            if referral_context:
                logger.info(f"[REFERRAL_CONTEXT] Usuário é um INDICADO: {referral_context}")
                contact_context.collection_data['referral_context'] = referral_context

            # Enhanced logging with structured context
            logger.info(
                f"[ENHANCED_PROCESSING] Starting conversation processing",
                extra={
                    "event": "conversation_start",
                    "company_id": self.company_id,
                    "phone": phone,
                    "user_input_length": len(user_input),
                    "current_stage": contact_context.current_stage,
                    "conversation_step": contact_context.conversation_step,
                    "has_conversation_history": bool(conversation_history),
                    "is_collecting_referrals": is_collecting_referrals
                }
            )

            # Enhance input with conversation context
            if conversation_history:
                context_str = "Histórico da conversa:\n"
                for msg in conversation_history[-3:]:  # Last 3 messages
                    role = "Usuário" if msg.get("role") == "user" else "Assistente"
                    context_str += f"{role}: {msg.get('content', '')}\n"
                enhanced_input = f"{context_str}\nNova mensagem: {user_input}"
            else:
                enhanced_input = user_input

            # Get trace context
            trace_context = tracer.get_trace_context(
                phone=phone,
                company_id=self.company_id,
                user_input=user_input,
                metadata={
                    "conversation_length": len(conversation_history) if conversation_history else 0,
                    "timestamp": execution_start.isoformat()
                }
            )

            # Inject tool implementations with company context
            agent_with_context = self._inject_tool_implementations(coordinator_agent)

            logger.critical(f"[AGENT_TOOLS] Agent configured with {len(agent_with_context.tools)} tools: {[tool.name if hasattr(tool, 'name') else str(tool) for tool in agent_with_context.tools]}")

            # Configure tracing for this conversation
            workflow_name = tracer.get_workflow_name(phone, self.company_id)
            group_id = tracer.get_conversation_group(phone, self.company_id)

            # Generate consistent trace_id for this conversation
            trace_id = f"trace_{phone}_company{self.company_id}".replace("+", "")[:32]

            # Get or create SQLiteSession following OpenAI documentation pattern
            session = self._get_session(phone)

            # DEBUG: Log session state BEFORE any operations
            session_items_before = await session.get_items()
            logger.critical(f"[SESSION_DEBUG] BEFORE operations - Session has {len(session_items_before)} items")
            if session_items_before:
                for idx, item in enumerate(session_items_before[-3:]):
                    content_str = str(item.get('content', ''))[:100] if item.get('content') else 'None'
                    logger.critical(f"[SESSION_DEBUG]   Item[{idx}]: role={item.get('role')}, content='{content_str}...'")

            # Import history ONLY if session is empty (first time)
            session_items = await session.get_items()
            if not session_items:
                logger.critical(f"[HISTORY_IMPORT] New session for {phone} - importing existing history")
                await self._safe_import_history(phone, session)
                session_items = await session.get_items()
                logger.critical(f"[SESSION_DEBUG] AFTER import - Session now has {len(session_items)} items")

            logger.critical(f"[AGENT_SESSION] Session {phone} has {len(session_items)} items")
            if session_items:
                logger.critical(f"[AGENT_SESSION] Last 2 messages: {session_items[-2:] if len(session_items) >= 2 else session_items}")

                # DEBUG: Check for problematic patterns in session
                for idx, item in enumerate(session_items):
                    content = item.get('content', '')
                    role = item.get('role', '')
                    # Handle nested content structure from agent responses
                    if isinstance(content, list) and len(content) > 0:
                        if isinstance(content[0], dict) and 'text' in content[0]:
                            content = content[0]['text']
                    content_str = str(content)
                    if "Olá! Me chamo" in content_str or "Sou a consultora" in content_str:
                        logger.critical(f"[SESSION_DEBUG] ⚠️ ASSISTANT PATTERN FOUND at index {idx}: role={role}, content='{content_str[:100]}...'")

            # Get model configuration
            model_config = get_model_config()
            run_config = build_company_openai_run_config(
                self.db,
                self.company_id,
                tracing_disabled=True,
            )

            # Check if already in third-party booking flow using contact_context collection_state
            # This is the proper way: context persists across runs through contact_context_manager
            is_continuing_third_party = (
                contact_context.collection_state == "third_party_booking" and
                contact_context.collection_data.get('relationship')
            )

            # If already in third-party flow, restore detection from contact_context
            if is_continuing_third_party:
                logger.info(f"[ThirdParty] Continuing existing third-party flow for {contact_context.collection_data.get('relationship')}")
                third_party_detection = {
                    'intent': 'third_party_booking',
                    'confidence': 1.0,
                    'relationship': contact_context.collection_data.get('relationship'),
                    'reasoning': 'Continuing existing third-party booking flow'
                }
            else:
                # Check for third-party booking intent BEFORE main agent
                third_party_detection = await self._detect_third_party_intent(
                    user_input, phone, session, contact_context
                )

            # If third-party detected with VERY high confidence, prepare for silent handoff
            # Increased threshold to 0.85 to avoid false positives
            if third_party_detection and third_party_detection.get('confidence', 0) > 0.85:
                logger.info(f"[ThirdParty] Detected intent: {third_party_detection}")

                # Prepare BookingContext for third-party agent
                from .context.booking_context import BookingContext
                from .agents.third_party_booking_agent import third_party_booking_agent
                from .tools.third_party_booking_tools import (
                    collect_third_party_info,
                    process_third_party_appointment
                )

                # Restore customer_name and customer_phone from contact_context if continuing
                existing_customer_name = contact_context.collection_data.get('customer_name') if is_continuing_third_party else None
                existing_customer_phone = contact_context.collection_data.get('customer_phone') if is_continuing_third_party else None

                booking_context = BookingContext(
                    company_id=self.company_id,
                    company_data=self._get_company_data(),
                    db=self.db,  # Pass database connection for agent config access
                    requester_phone=phone,
                    requester_name=contact_context.customer_name,
                    selected_date=getattr(contact_context, 'selected_date', None),
                    selected_time=getattr(contact_context, 'selected_time', None),
                    treatment_type=contact_context.treatment_interest or "Consulta de Avaliação",
                    is_third_party=True,
                    relationship=third_party_detection.get('relationship'),
                    customer_name=existing_customer_name,  # Restore if continuing
                    customer_phone=existing_customer_phone,  # Restore if continuing
                    current_stage=contact_context.current_stage,
                    conversation_step=contact_context.conversation_step,
                    detection_confidence=third_party_detection.get('confidence'),
                    detection_reasoning=third_party_detection.get('reasoning')
                )

                # Mark contact_context as being in third-party booking flow
                if not is_continuing_third_party:
                    contact_context.set_collection_mode('third_party_booking', {
                        'relationship': third_party_detection.get('relationship'),
                        'started_at': datetime.now().isoformat()
                    })
                    logger.info(f"[ThirdParty] Started new third-party booking flow")

                # Always update collection_data with current booking context
                contact_context.collection_data['relationship'] = booking_context.relationship
                contact_context.collection_data['customer_name'] = booking_context.customer_name
                contact_context.collection_data['customer_phone'] = booking_context.customer_phone

                # Get scheduling tools from the service
                from .tools.scheduling_tools import create_scheduling_tools
                scheduling_tools = create_scheduling_tools(
                    slots_service=self.scheduling_service,
                    company_id=self.company_id
                )
                get_available_slots = scheduling_tools[0]  # First tool is get_available_slots

                # Inject tools into third-party agent
                # Include get_available_slots so agent can find dates/times before confirming
                third_party_booking_agent.tools = [
                    collect_third_party_info,
                    process_third_party_appointment,
                    get_available_slots  # Need this to parse user date/time requests
                ]

                # Use third-party agent directly (silent handoff)
                agent_to_use = third_party_booking_agent
                context_to_use = booking_context

                logger.info(f"[ThirdParty] Using specialized agent for {booking_context.relationship}")
                logger.critical(f"[THIRD_PARTY_AGENT_TOOLS] Agent configured with {len(agent_to_use.tools)} tools: {[tool.name if hasattr(tool, 'name') else str(tool) for tool in agent_to_use.tools]}")
            else:
                # Use main business assistant
                agent_to_use = agent_with_context
                context_to_use = company_context

            # Use trace context manager for proper workflow naming with persistent trace_id
            logger.critical(f"[AGENT_INPUT] About to call agent with: user_input='{user_input}', company_id={self.company_id}, phone={phone}")

            # DEBUG: Final session state before calling agent
            final_session_items = await session.get_items()
            logger.critical(f"[SESSION_DEBUG] RIGHT BEFORE Runner.run:")
            logger.critical(f"[SESSION_DEBUG]   Total items in session: {len(final_session_items)}")
            if final_session_items:
                last = final_session_items[-1]
                logger.critical(f"[SESSION_DEBUG]   Last item: role={last.get('role')}, content_preview='{str(last.get('content', ''))[:100]}...'")

            # CRITICAL FIX: Remove items with custom metadata fields that break OpenAI API
            # Look for system messages with _third_party_metadata or other custom fields
            items_to_remove = []
            for item in final_session_items:
                if isinstance(item, dict) and item.get('role') == 'system':
                    # Check if has custom fields
                    has_custom_fields = any(k.startswith('_') and k not in ['_id'] for k in item.keys())
                    if has_custom_fields:
                        items_to_remove.append(item)
                        logger.warning(f"[SESSION_CLEANUP] Removing system message with custom fields: {list(item.keys())}")

            # Remove problematic items from session
            for _ in items_to_remove:
                await session.pop_item()

            with openai_run_trace(
                run_config,
                workflow_name=workflow_name,
                group_id=group_id,
                trace_id=trace_id,
            ):
                # Run appropriate agent with SQLiteSession
                result = await Runner.run(
                    agent_to_use,
                    user_input,
                    context=context_to_use,
                    session=session,
                    max_turns=model_config['max_turns'],
                    run_config=run_config
                )

            logger.critical(f"[AGENT_OUTPUT] Agent returned: response_length={len(result.content) if hasattr(result, 'content') else 'N/A'}, result_type={type(result)}")

            # Update contact_context with any changes made by tools during this run
            if third_party_detection and third_party_detection.get('confidence', 0) > 0.85:
                contact_context.collection_data['customer_name'] = context_to_use.customer_name
                contact_context.collection_data['customer_phone'] = context_to_use.customer_phone
                logger.info(f"[ThirdParty] Updated contact_context with: name={context_to_use.customer_name}, phone={context_to_use.customer_phone}")

            # DEBUG: Check what was added to session by Runner
            session_after = await session.get_items()
            logger.critical(f"[SESSION_DEBUG] AFTER Runner.run:")
            logger.critical(f"[SESSION_DEBUG]   Total items now: {len(session_after)}")
            if len(session_after) > len(final_session_items):
                new_count = len(session_after) - len(final_session_items)
                logger.critical(f"[SESSION_DEBUG]   Runner added {new_count} new items")
                for new_item in session_after[-new_count:]:
                    logger.critical(f"[SESSION_DEBUG]     New: role={new_item.get('role')}, content_preview='{str(new_item.get('content', ''))[:100]}...'")

            execution_time = (datetime.now() - execution_start).total_seconds() * 1000
            response = result.final_output

            # Check if response is long enough for automatic audio (>300 tokens)
            should_force_audio = self._should_force_audio_by_length(response, result)

            # Process audio (automatic for long responses OR when explicitly requested)
            audio_response = await self._process_audio_request(response, user_input, result, should_force_audio)
            _record_generated_audio_usage(
                db=self.db,
                company_id=self.company_id,
                audio_response=audio_response,
                fallback_text=response,
                phone=phone,
                conversation_group=group_id,
                trace_id=trace_id,
                workflow_name=workflow_name,
            )

            # NEW: Save structured context after successful processing
            try:
                self.contact_context_manager.save_context(contact_context)

                logger.info(
                    f"[CONTEXT_SAVED] Customer context updated successfully",
                    extra={
                        "event": "context_saved",
                        "company_id": self.company_id,
                        "phone": phone,
                        "final_stage": contact_context.current_stage,
                        "conversation_step": contact_context.conversation_step,
                        "execution_time_ms": int(execution_time)
                    }
                )
            except Exception as context_error:
                # Don't fail the whole request if context saving fails
                logger.warning(f"Failed to save customer context: {context_error}")

            # Log execution
            self._log_execution(
                phone=phone,
                user_input=user_input,
                agent_response=response,
                execution_time_ms=int(execution_time),
                workflow_name=workflow_name,
                status="success"
            )

            return {
                "response": response,
                "audio": audio_response.audio_data if audio_response.should_send_audio else None,
                "should_send_audio": audio_response.should_send_audio,
                "metadata": {
                    "company_id": self.company_id,
                    "phone": phone,
                    "workflow_name": workflow_name,
                    "conversation_group": group_id,
                    "execution_time_ms": int(execution_time),
                    "timestamp": execution_start.isoformat(),
                    "audio_trigger": audio_response.trigger_detected,
                    "voice_used": audio_response.voice_used,
                    "voice_provider": audio_response.provider_used,
                    "voice_model": audio_response.model_used,
                    # NEW: Add structured context info to metadata
                    "contact_context": {
                        "current_stage": contact_context.current_stage,
                        "conversation_step": contact_context.conversation_step,
                        "has_pain_description": bool(contact_context.pain_description),
                        "has_treatment_interest": bool(contact_context.treatment_interest),
                        "has_customer_type": bool(contact_context.customer_type),
                        "has_name": bool(contact_context.customer_name),
                        "appointment_confirmed": contact_context.appointment_confirmed
                    }
                }
            }

        except Exception as e:
            execution_time = (datetime.now() - execution_start).total_seconds() * 1000
            safe_error = safe_ai_provider_runtime_error(
                e,
                fallback="Não foi possível executar a conversa com IA",
            )

            logger.error(
                "Error in conversation processing: error_type=%s",
                type(e).__name__,
            )

            # NEW: Enhanced error logging with context (if available)
            error_extra = {
                "event": "conversation_error",
                "company_id": self.company_id,
                "phone": phone,
                "error": safe_error,
                "error_type": type(e).__name__,
                "execution_time_ms": int(execution_time)
            }

            # Add context info if available
            try:
                if 'contact_context' in locals():
                    error_extra.update({
                        "current_stage": contact_context.current_stage,
                        "conversation_step": contact_context.conversation_step
                    })
            except:
                pass

            logger.error(f"[ERROR] Conversation processing failed", extra=error_extra)

            # Use consistent workflow naming even for errors
            error_workflow_name = tracer.get_workflow_name(phone, self.company_id)
            error_group_id = tracer.get_conversation_group(phone, self.company_id)

            # Log error
            self._log_execution(
                phone=phone,
                user_input=user_input,
                agent_response="",
                execution_time_ms=int(execution_time),
                workflow_name=error_workflow_name,
                status="error",
                error_message=safe_error
            )

            return {
                "response": "Desculpe, houve um erro interno. Por favor, tente novamente ou entre em contato diretamente com a empresa.",
                "metadata": {
                    "company_id": self.company_id,
                    "phone": phone,
                    "workflow_name": error_workflow_name,
                    "conversation_group": error_group_id,
                    "error": safe_error,
                    "execution_time_ms": int(execution_time),
                    "timestamp": execution_start.isoformat()
                }
            }

    def _inject_tool_implementations(self, agent):
        """
        Inject real tool implementations with company context
        Following openai-agents-python patterns with direct dependency injection
        """
        from .tools.scheduling_tools import create_scheduling_tools
        from .tools.confirmation_tools import process_appointment_confirmation
        from .tools.appointment_management_tools import APPOINTMENT_MANAGEMENT_TOOLS
        from .voice.tools import trigger_audio_response, check_audio_capability
        from .tools.referral_tools import REFERRAL_TOOLS
        from .tools.smart_referral_collector import SMART_REFERRAL_TOOLS

        # Create tools with context injection - use real scheduling service
        scheduling_tools = create_scheduling_tools(
            slots_service=self.scheduling_service,  # Use real scheduling with integrations
            company_id=self.company_id
        )

        # Add company information tool
        company_info_tool = self._create_real_get_company_information()

        tenant_bound_tools = [
            _bind_tool_to_company(tool, self.company_id)
            for tool in [
                process_appointment_confirmation,
                *APPOINTMENT_MANAGEMENT_TOOLS,
                *REFERRAL_TOOLS,
            ]
        ]

        # Combine all tools with minimal audio tools (only for explicit requests)
        audio_tools = [trigger_audio_response, check_audio_capability]
        # Combinar TODAS as tools no agent principal (sem handoffs)
        real_tools = (
            scheduling_tools +
            [company_info_tool] +
            tenant_bound_tools +
            audio_tools +
            SMART_REFERRAL_TOOLS  # Tool inteligente direto no agent principal
        )

        return agent.clone(tools=real_tools)


    def _create_real_get_company_information(self):
        """Create real implementation of get_company_information"""

        @function_tool
        def get_company_information_impl(info_type: str = "geral") -> Dict[str, Any]:
            try:
                company_data = self._get_company_data()

                if info_type.lower() in ["servicos", "serviços"]:
                    return {
                        "type": "serviços",
                        "specialties": company_data.get("services_info", {}).get("specialties", []),
                        "professionals": company_data.get("services_info", {}).get("professionals", [])
                    }
                elif info_type.lower() in ["precos", "preços"]:
                    return {
                        "type": "preços",
                        "services": company_data.get("financial_info", {}).get("services", []),
                        "payment_methods": company_data.get("financial_info", {}).get("payment_methods", [])
                    }
                elif info_type.lower() in ["contato", "endereco"]:
                    company_info = company_data.get("company_info", {})
                    return {
                        "type": "contato",
                        "name": company_info.get("name", ""),
                        "address": company_info.get("address", ""),
                        "phone": company_info.get("phone", "")
                    }
                else:  # geral
                    company_info = company_data.get("company_info", {})
                    return {
                        "type": "geral",
                        "company_name": company_info.get("name", ""),
                        "address": company_info.get("address", ""),
                        "phone": company_info.get("phone", ""),
                        "specialties": company_data.get("services_info", {}).get("specialties", [])
                    }

            except Exception as e:
                logger.error(f"Error getting company info: {e}")
                return {
                    "message": "Erro ao buscar informações da empresa"
                }

        return get_company_information_impl

    def _should_ask_for_referrals(self, phone: str) -> bool:
        """Check if we should ask for referrals based on intelligent rules"""
        try:
            from backend.models import Lead, ReferralCampaign
            from .models.referral_history import ReferralHistory
            import datetime

            # Get lead info
            lead = self.db.query(Lead).filter(
                Lead.phone == phone,
                Lead.company_id == self.company_id
            ).first()

            if not lead:
                return False

            # Check if there's an active campaign
            campaign = self.db.query(ReferralCampaign).filter(
                ReferralCampaign.company_id == self.company_id,
                ReferralCampaign.active == True
            ).first()

            if not campaign:
                logger.info(f"[ReferralCheck] No active campaign for company {self.company_id}")
                return False

            # Check referral history
            history = self.db.query(ReferralHistory).filter(
                ReferralHistory.lead_phone == phone,
                ReferralHistory.company_id == self.company_id,
                ReferralHistory.campaign_id == campaign.id
            ).first()

            # Rule 1: Never asked before for this campaign
            if not history:
                logger.info(f"[ReferralCheck] First time asking for lead {phone}")
                return True

            # Rule 2: Check time since last referral
            if history.last_referral_date:
                days_since_last = (datetime.datetime.now() - history.last_referral_date).days

                # Don't ask if less than 30 days
                if days_since_last < 30:
                    logger.info(f"[ReferralCheck] Too soon since last referral ({days_since_last} days)")
                    return False

                # Check if it's a rescheduling (less than 7 days since last interaction)
                # This prevents asking during reschedulings
                if days_since_last < 7:
                    logger.info(f"[ReferralCheck] Likely rescheduling, skipping referral request")
                    return False

            # Rule 3: Check referral count limits
            max_referrals_per_lead = getattr(campaign, 'max_referrals_per_lead', 5)
            if history.referrals_count >= max_referrals_per_lead:
                logger.info(f"[ReferralCheck] Lead reached max referrals ({history.referrals_count}/{max_referrals_per_lead})")
                return False

            # Rule 4: Check campaign daily limits
            today = datetime.datetime.now().date()
            today_referrals = self.db.execute(text("""
                SELECT COUNT(*) as count
                FROM referral_history
                WHERE company_id = :company_id
                AND campaign_id = :campaign_id
                AND DATE(last_referral_date) = :today
            """), {
                "company_id": self.company_id,
                "campaign_id": campaign.id,
                "today": today
            }).scalar()

            daily_limit = getattr(campaign, 'daily_limit', 50)
            if today_referrals >= daily_limit:
                logger.info(f"[ReferralCheck] Daily limit reached ({today_referrals}/{daily_limit})")
                return False

            logger.info(f"[ReferralCheck] All checks passed, can ask for referrals")
            return True

        except Exception as e:
            logger.error(f"[ReferralCheck] Error checking referral eligibility: {e}")
            return False

    def _check_referral_context(self, phone: str) -> Optional[Dict[str, Any]]:
        """Check if this user is a referred lead (indicado) and get context"""
        try:
            from backend.models import Lead, ReferralCampaign

            # Check if lead exists with source_id="Indicação"
            lead = self.db.query(Lead).filter(
                Lead.phone == phone,
                Lead.company_id == self.company_id,
                Lead.source_id == "Indicação"
            ).first()

            if lead:
                # Get active referral campaign
                campaign = self.db.query(ReferralCampaign).filter(
                    ReferralCampaign.company_id == self.company_id,
                    ReferralCampaign.active == True
                ).first()

                if campaign:
                    # Calculate time since lead creation
                    import datetime

                    # Convert created_at to datetime if it's a string
                    if isinstance(lead.created_at, str):
                        # Handle string format (ISO format)
                        created_at = datetime.datetime.fromisoformat(lead.created_at.replace('Z', '+00:00').replace(' ', 'T'))
                    else:
                        created_at = lead.created_at

                    # Ensure created_at is timezone-naive for comparison
                    if created_at.tzinfo is not None:
                        created_at = created_at.replace(tzinfo=None)

                    time_since_creation = datetime.datetime.utcnow() - created_at

                    # If lead was created recently (last 24 hours), it's likely a fresh referral
                    if time_since_creation.days < 1:
                        return {
                            "is_referee": True,
                            "campaign_name": campaign.name,
                            "campaign_description": campaign.referee_campaign_description,
                            "lead_name": lead.name,
                            "created_recently": True,
                            "hours_since_creation": time_since_creation.total_seconds() / 3600
                        }
                    else:
                        # Older referral but still valid
                        return {
                            "is_referee": True,
                            "campaign_name": campaign.name,
                            "campaign_description": campaign.referee_campaign_description,
                            "lead_name": lead.name,
                            "created_recently": False,
                            "days_since_creation": time_since_creation.days
                        }

            return None

        except Exception as e:
            logger.error(f"Error checking referral context: {e}")
            return None

    def _check_referral_collection_mode(self, phone: str) -> bool:
        """Check if we're in referral collection mode for this phone"""
        try:
            import redis
            r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
            key = f"referral_collection:{self.company_id}:{phone}"
            value = r.get(key)
            return value == "active"
        except Exception as e:
            logger.debug(f"[REFERRAL_MODE] Could not check collection mode: {e}")
            return False

    def _get_day_info(self, date_str: str) -> str:
        """Get day of week info"""
        try:
            date_obj = datetime.strptime(date_str, "%d/%m/%Y")
            days = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
            return days[date_obj.weekday()]
        except:
            return ""

    def get_conversation_history(self, phone: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get conversation history for phone number"""
        try:
            from sqlalchemy import text
            result = self.db.execute(text("""
                SELECT user_input, agent_response, created_at
                FROM agent_executions
                WHERE company_id = :company_id AND phone = :phone
                AND status = 'success'
                ORDER BY created_at DESC
                LIMIT :limit
            """), {
                "company_id": self.company_id,
                "phone": phone,
                "limit": limit
            }).fetchall()

            history = []
            for row in reversed(result):  # Chronological order
                if row.user_input:
                    history.append({
                        "role": "user",
                        "content": row.user_input,
                        "timestamp": row.created_at.isoformat()
                    })
                if row.agent_response:
                    history.append({
                        "role": "assistant",
                        "content": row.agent_response,
                        "timestamp": row.created_at.isoformat()
                    })

            return history

        except Exception as e:
            logger.error(f"Error getting conversation history: {e}")
            return []

    def _log_execution(
        self,
        phone: str,
        user_input: str,
        agent_response: str,
        execution_time_ms: int,
        workflow_name: str,
        status: str = "success",
        error_message: Optional[str] = None
    ):
        """Log execution for monitoring"""
        try:
            # Use a separate transaction for logging to avoid conflicts
            execution_log = AgentExecution(
                company_id=self.company_id,
                phone=phone,
                conversation_group=tracer.get_conversation_group(phone, self.company_id),
                workflow_name=workflow_name,
                user_input=user_input,
                agent_response=agent_response,
                execution_time_ms=execution_time_ms,
                status=status,
                error_message=error_message,
                execution_metadata={
                    "sdk_version": "openai-agents",
                    "manager_version": "v1"
                }
            )

            # Rollback any failed transaction first
            self.db.rollback()

            # Add and commit in fresh transaction
            self.db.add(execution_log)
            self.db.commit()

        except Exception as e:
            logger.error(f"Error logging execution: {e}")
            self.db.rollback()

    def _should_force_audio_by_length(self, response_text: str, result) -> bool:
        """
        Check if response is long enough to automatically generate audio
        NUNCA enviar confirmações de agendamento por áudio
        """
        try:
            # DETECTAR CONFIRMAÇÃO pelos 5 elementos essenciais
            response_lower = response_text.lower()

            # Verificar presença dos 5 elementos
            has_date = "data e horário" in response_lower
            has_address = "endereço" in response_lower
            has_maps = "google maps" in response_lower or "maps.app.goo.gl" in response_lower
            has_protocol = "protocolo" in response_lower
            has_dentist = "dentista responsável" in response_lower or "responsável técnico" in response_lower

            # Contar elementos presentes
            elements = [has_date, has_address, has_maps, has_protocol, has_dentist]
            elements_found = sum(elements)

            # Se tiver 4+ dos 5 elementos, É confirmação
            if elements_found >= 4:
                logger.info(f"[AUDIO_SKIP] Confirmation detected ({elements_found}/5 elements)")
                return False

            # MANTER LÓGICA EXISTENTE para outras mensagens
            char_count = len(response_text)
            estimated_tokens = char_count / 4

            if estimated_tokens > 139:
                logger.info(f"Auto-audio triggered by response length: ~{int(estimated_tokens)} tokens ({char_count} chars)")
                return True
            else:
                logger.info(f"Response too short for auto-audio: ~{int(estimated_tokens)} tokens ({char_count} chars)")
                return False

        except Exception as e:
            logger.error(f"Error checking response length for audio: {e}")
            return False

    async def _process_audio_request(self, response_text: str, user_input: str, agent_result=None, force_audio: bool = False) -> AudioResponse:
        """
        Process audio request using voice service
        Now supports: explicit requests, tool calls, AND automatic long responses

        Args:
            response_text: Agent's response text
            user_input: User's original message
            agent_result: Result from agent execution (for tool detection)
            force_audio: Force audio generation (for long responses)

        Returns:
            AudioResponse with audio data if generated
        """
        try:
            # Create audio request
            audio_request = AudioRequest(
                text=response_text,
                user_message=user_input,
                company_id=self.company_id,
                trigger_type="long_response" if force_audio else None
            )

            # Process through audio service (pass agent result for tool detection + force flag)
            audio_response = await self.audio_service.process_audio_request(
                audio_request,
                agent_result,
                force_audio=force_audio
            )

            if audio_response.should_send_audio:
                logger.info(f"Audio generated for company {self.company_id} - trigger: {audio_response.trigger_detected}")

            return audio_response

        except Exception as e:
            logger.error(f"Error processing audio request: {e}")
            # Return safe fallback response
            return AudioResponse(
                should_send_audio=False,
                text_processed=response_text,
                error=str(e)
            )
# Backward Compatibility Alias
BusinessCompanyManager = AgentExecutionManager


def _record_generated_audio_usage(
    *,
    db: Session,
    company_id: int,
    audio_response: AudioResponse,
    fallback_text: str,
    phone: Optional[str],
    conversation_group: Optional[str],
    trace_id: Optional[str],
    workflow_name: Optional[str],
) -> None:
    """Debit successful legacy ElevenLabs audio from every manager path."""
    if not audio_response.should_send_audio:
        return

    provider_units = (
        Decimal(str(audio_response.provider_usage_units))
        if audio_response.provider_usage_units is not None
        else None
    )
    safe_record_tts_usage(
        db=db,
        company_id=company_id,
        provider=audio_response.provider_used or "openai",
        model=audio_response.model_used,
        text_characters=audio_response.characters_used or len(fallback_text),
        status="success",
        provider_usage_units=provider_units,
        phone=phone,
        conversation_group=conversation_group,
        trace_id=trace_id,
        usage_metadata={
            "trigger": audio_response.trigger_detected,
            "voice_used": audio_response.voice_used,
            "speed": audio_response.speed_used,
            "generation_time_ms": audio_response.generation_time_ms,
            "provider_metadata": audio_response.provider_metadata or {},
            "workflow_name": workflow_name,
        },
        provider_request_id=audio_response.provider_request_id,
    )
