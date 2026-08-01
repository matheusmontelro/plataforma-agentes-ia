"""
Main entry point for Agents SDK
"""

import asyncio
import logging
import os
from typing import Optional
from sqlalchemy.orm import Session

from .manager import BusinessCompanyManager
from .config import is_company_enabled

logger = logging.getLogger(__name__)

async def handle_user_input(
    db: Session,
    company_id: int,
    contact_phone: str,
    user_input: str,
    msg_category: str = "",
    funnel_stage: str = "",
    funnel_status: str = ""
) -> Optional[str]:
    """
    Main entry point for Agents SDK processing

    Compatible with existing system signature

    Returns:
        - Agent response string if company is enabled
        - None if company should use legacy system
    """

    # Check if company is enabled
    if not is_company_enabled(company_id, db):
        logger.info(f"[AGENTS_SDK] Company {company_id} not enabled")
        return None

    try:
        logger.info(f"[AGENTS_SDK] Processing message for company {company_id}")

        # Create manager and process
        manager = BusinessCompanyManager(company_id=company_id, db=db)

        # Get conversation history
        conversation_history = manager.get_conversation_history(
            phone=contact_phone,
            limit=6  # Last 3 exchanges
        )

        # Process conversation
        result = await manager.process_conversation(
            phone=contact_phone,
            user_input=user_input,
            conversation_history=conversation_history
        )

        return result["response"]

    except Exception as e:
        logger.error(f"[AGENTS_SDK] Error processing message: {e}")
        return None

def handle_user_input_sync(
    db: Session,
    company_id: int,
    contact_phone: str,
    user_input: str,
    msg_category: str = "",
    funnel_stage: str = "",
    funnel_status: str = ""
) -> Optional[str]:
    """
    Synchronous wrapper for integration with Celery tasks
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        result = loop.run_until_complete(
            handle_user_input(
                db, company_id, contact_phone, user_input,
                msg_category, funnel_stage, funnel_status
            )
        )

        loop.close()
        return result

    except Exception as e:
        logger.error(f"[AGENTS_SDK_SYNC] Error: {e}")
        return None
