"""
Flow Agent Runner Service

This service executes the Agent SDK using the company's saved AgentConfiguration.
It is called by the FlowBuilder's AgentResponseNode to generate AI responses.
"""

import logging
from typing import Dict, Any, Optional
from openai import OpenAI
from sqlalchemy.orm import Session

from backend.models import AgentConfiguration
from backend.services.ai_credit_guard import ai_credit_block_result_from_balance
from backend.services.ai_provider_service import (
    get_company_openai_api_key,
    safe_ai_provider_runtime_error,
)

logger = logging.getLogger(__name__)


def run_agent_response(
    db: Session,
    company_id: int,
    agent_config_id: int,
    message: str,
    conversation_history: Optional[list] = None
) -> Dict[str, Any]:
    """
    Executes the Agent SDK with the company's saved prompt.

    Args:
        db: Database session
        company_id: Active company that owns the configuration
        agent_config_id: ID of the AgentConfiguration to use
        message: The incoming user message
        conversation_history: Optional list of previous messages for context

    Returns:
        Dict with 'success', 'response', and optional 'error' fields
    """
    try:
        # 1. Load the AgentConfiguration
        config = db.query(AgentConfiguration).filter_by(
            id=agent_config_id,
            company_id=int(company_id),
        ).first()

        if not config:
            logger.error(f"[FlowAgentRunner] AgentConfiguration {agent_config_id} not found")
            return {
                "success": False,
                "response": "",
                "error": f"Agent configuration {agent_config_id} not found"
            }

        credit_block = ai_credit_block_result_from_balance(
            db=db,
            company_id=int(config.company_id),
            source="flow_agent_response",
        )
        if credit_block:
            return credit_block

        # 2. Get the saved prompt
        system_prompt = config.generated_prompt

        if not system_prompt:
            logger.warning(f"[FlowAgentRunner] AgentConfiguration {agent_config_id} has no generated_prompt")
            # Fallback: try to generate from CRIAR data if available
            criar_data = config.conversation_flow.get('criar_data', {}) if config.conversation_flow else {}
            if criar_data:
                from backend.agents_sdk.prompts.generators.criar_generator import generate_criar_prompt
                system_prompt = generate_criar_prompt(criar_data)
                logger.info(f"[FlowAgentRunner] Generated fallback prompt from CRIAR data")
            else:
                return {
                    "success": False,
                    "response": "",
                    "error": "Agent has no configured prompt. Please generate one in the Agent Editor."
                }

        logger.info(f"[FlowAgentRunner] Using prompt of length {len(system_prompt)} for agent {agent_config_id}")

        # 3. Call OpenAI to generate response
        api_key = get_company_openai_api_key(db, int(config.company_id))
        client = OpenAI(api_key=api_key)

        # Build messages array
        messages = [{"role": "system", "content": system_prompt}]

        # Add conversation history if provided
        if conversation_history:
            for msg in conversation_history:
                messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", "")
                })

        # Add current message
        messages.append({"role": "user", "content": message})

        logger.info(f"[FlowAgentRunner] Calling OpenAI with {len(messages)} messages")

        # 4. Call OpenAI
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=1000
        )

        ai_response = response.choices[0].message.content.strip()

        logger.info(f"[FlowAgentRunner] Generated response of length {len(ai_response)}")

        return {
            "success": True,
            "response": ai_response,
            "tokens_used": response.usage.total_tokens if response.usage else 0
        }

    except Exception as exc:
        safe_error = safe_ai_provider_runtime_error(
            exc,
            fallback="Não foi possível executar o agente de IA",
        )
        logger.error(
            "[FlowAgentRunner] Error running agent: error_type=%s",
            type(exc).__name__,
        )
        return {
            "success": False,
            "response": "",
            "error": safe_error,
        }
