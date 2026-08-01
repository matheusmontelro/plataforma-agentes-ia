"""
Adapter for integrating LangChain with burst_processor.py

This adapter connects the burst processor with the new modular
conversation flow architecture.
"""

import logging
from typing import Optional
from sqlalchemy.orm import Session

from ..chains.conversation_chain import ConversationFlowChain
from backend.prompt.db_integration.agent_config import get_agent_config_dict
from backend.prompt.scheduling.scheduling_service import SchedulingService

logger = logging.getLogger(__name__)


def handle_user_input_v2(
    db: Session,
    company_id: int,
    contact_phone: str,
    user_input: str,
    msg_category: str = "",
    funnel_stage: str = "",
    funnel_status: str = ""
) -> str:
    """
    Handle user input using the modular LangChain conversation flow.

    Args:
        db: Database session
        company_id: Company ID (should be 2)
        contact_phone: User's phone number
        user_input: User's message
        msg_category: Message category from classifier
        funnel_stage: Current funnel stage
        funnel_status: Current funnel status

    Returns:
        Assistant's response string
    """
    logger.info(f"[LangChain V2] Processing message for company_id={company_id}, phone={contact_phone}")

    try:
        # Get company configuration
        company_config = get_agent_config_dict(db, company_id)
        if not company_config:
            logger.error(f"[LangChain V2] No configuration found for company_id={company_id}")
            return "Desculpe, não foi possível carregar as configurações da empresa."

        # Get available appointment slots
        scheduling = SchedulingService(db, company_id)
        available_slots = scheduling.get_next_available_slots()

        logger.info(f"[LangChain V2] Found {len(available_slots)} available slots")

        # Initialize conversation chain with company config
        chain = ConversationFlowChain(company_config=company_config)

        # Process the message
        result = chain.process(
            user_input=user_input,
            contact_phone=contact_phone,
            company_id=company_id,
            db_session=db,
            available_slots=available_slots,
            msg_category=msg_category,
            funnel_stage=funnel_stage,
            funnel_status=funnel_status
        )

        # Extract response
        response = result.get("response", "Desculpe, não consegui processar sua mensagem.")

        # Log collected data for debugging
        collected_data = result.get("collected_data", {})
        current_step = result.get("current_step", 0)

        logger.info(f"[LangChain V2] Current step: {current_step}")
        logger.info(f"[LangChain V2] Collected data: {collected_data}")
        logger.info(f"[LangChain V2] Response preview: {response[:100]}...")

        # Handle special cases based on state
        state = result.get("state", {})

        # If appointment was confirmed (step 6), trigger appointment creation
        if current_step == 6 and all([
            state.get("tratamento"),
            state.get("nome"),
            state.get("data"),
            state.get("horario")
        ]):
            logger.info("[LangChain V2] Appointment data complete, ready for creation")
            # The actual appointment creation is handled by the burst processor

        # If cancellation was requested
        if state.get("cancelamento"):
            logger.info("[LangChain V2] Cancellation requested")
            # Cancellation logic is handled elsewhere

        # If rescheduling was requested
        if state.get("reagendamento"):
            logger.info("[LangChain V2] Rescheduling requested")
            # Rescheduling logic is handled elsewhere

        return response

    except Exception as e:
        logger.error(f"[LangChain V2] Error processing message: {e}", exc_info=True)

        # Try to provide a helpful error message
        if "agent_config" in str(e):
            return "Desculpe, houve um erro ao carregar as configurações. Por favor, tente novamente."
        elif "scheduling" in str(e):
            return "Desculpe, houve um erro ao buscar horários disponíveis. Por favor, tente novamente."
        else:
            return "Desculpe, houve um erro ao processar sua mensagem. Por favor, tente novamente em alguns instantes."


# Alias for compatibility
process_llm_v2_message = handle_user_input_v2