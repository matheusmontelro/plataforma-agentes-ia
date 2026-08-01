"""
Integration module for gradual migration from existing system to Agents SDK
"""

import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from ..config import is_company_enabled

logger = logging.getLogger(__name__)

def process_with_agents_sdk_if_enabled_sync(
    db: Session,
    company_id: int,
    contact_phone: str,
    user_input: str,
    msg_category: str = "",
    funnel_stage: str = "",
    funnel_status: str = ""
) -> Optional[Dict[str, Any]]:
    """
    Synchronous version for integration with existing Celery tasks
    Returns dict with response and audio data for Z-API integration
    """
    import asyncio

    try:
        logger.info(f"[AGENTS_SDK_SYNC] Starting process for company {company_id}, phone {contact_phone}")

        # Run async function in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Use manager directly to get full response with audio
        from backend.agents_sdk.manager import BusinessCompanyManager
        from backend.agents_sdk.config import is_company_enabled

        # Check if company is enabled
        logger.info(f"[AGENTS_SDK_SYNC] Checking if company {company_id} is enabled...")
        enabled = is_company_enabled(company_id, db)
        logger.info(f"[AGENTS_SDK_SYNC] Company {company_id} enabled: {enabled}")

        if not enabled:
            logger.info(f"[AGENTS_SDK_SYNC] Company {company_id} not enabled - returning None")
            loop.close()
            return None

        from backend.services.ai_credit_guard import ai_credit_block_result_from_balance

        credit_block = ai_credit_block_result_from_balance(
            db=db,
            company_id=company_id,
            source="agents_sdk_sync",
        )
        if credit_block:
            loop.close()
            return credit_block

        # Create manager and process
        logger.info(f"[AGENTS_SDK_SYNC] Creating BusinessCompanyManager for company {company_id}")
        manager = BusinessCompanyManager(company_id=company_id, db=db)
        logger.info(f"[AGENTS_SDK_SYNC] Manager created successfully")

        # Get conversation history
        logger.info(f"[AGENTS_SDK_SYNC] Getting conversation history...")
        conversation_history = manager.get_conversation_history(
            phone=contact_phone,
            limit=6
        )
        logger.info(f"[AGENTS_SDK_SYNC] Got {len(conversation_history)} history items")

        # Process conversation (returns dict with audio)
        logger.info(f"[AGENTS_SDK_SYNC] Processing conversation...")
        result = loop.run_until_complete(
            manager.process_conversation(
                phone=contact_phone,
                user_input=user_input,
                conversation_history=conversation_history
            )
        )

        logger.info(f"[AGENTS_SDK_SYNC] Processing completed. Result type: {type(result)}")
        if isinstance(result, dict):
            logger.info(f"[AGENTS_SDK_SYNC] Result keys: {list(result.keys())}")
            logger.info(f"[AGENTS_SDK_SYNC] Response length: {len(result.get('response', ''))}")
            logger.info(f"[AGENTS_SDK_SYNC] Should send audio: {result.get('should_send_audio', False)}")

        loop.close()
        return result  # Returns dict with response, audio, should_send_audio, metadata

    except Exception as e:
        logger.error(f"[AGENTS_SDK_SYNC] Error: {e}")
        import traceback
        logger.error(f"[AGENTS_SDK_SYNC] Full traceback: {traceback.format_exc()}")
        return None

# This function is now just an alias to the main function
async def process_with_agents_sdk_if_enabled_async(
    db: Session,
    company_id: int,
    contact_phone: str,
    user_input: str,
    msg_category: str = "",
    funnel_stage: str = "",
    funnel_status: str = ""
) -> Optional[str]:
    """Async alias - delegates to main.handle_user_input"""
    from backend.agents_sdk.main import handle_user_input_sync
    return handle_user_input_sync(
        db, company_id, contact_phone, user_input,
        msg_category, funnel_stage, funnel_status
    )

# Configuration functions - using existing agent_configurations table
# No additional config functions needed, is_company_enabled is sufficient
