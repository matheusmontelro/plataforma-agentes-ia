"""
Simple configuration for Agents SDK
Uses existing agent_configurations table
"""

import logging
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

def is_company_enabled(company_id: int, db: Optional[Session] = None) -> bool:
    """
    Check whether a company has an Agents SDK configuration.

    Public installations must not depend on tenant IDs copied from another
    environment.  The persisted ``agent_configurations`` row is the source of
    truth: creating that configuration enables the SDK for the workspace.
    """
    if not db:
        return False

    try:
        result = db.execute(text("""
            SELECT 1 FROM agent_configurations WHERE company_id = :company_id LIMIT 1
        """), {"company_id": company_id}).fetchone()

        return result is not None

    except Exception as e:
        logger.error(f"Error checking agent config for company {company_id}: {e}")
        return False

def is_customer_identification_enabled(company_id: int, db: Optional[Session] = None) -> bool:
    """
    Check if customer identification feature is enabled for company

    Args:
        company_id: ID of the company
        db: Database session

    Returns:
        bool: True if customer identification is enabled
    """
    # Customer identification follows the same persisted configuration.
    return is_company_enabled(company_id, db)

def get_customer_identification_config(company_id: int, db: Session) -> dict:
    """
    Get customer identification configuration for company

    Args:
        company_id: ID of the company
        db: Database session

    Returns:
        dict: Configuration for customer identification
    """
    if not is_customer_identification_enabled(company_id, db):
        return {
            'enabled': False,
            'confidence_threshold': 0.0,
            'redirect_configs': {}
        }

    try:
        # Get redirect configurations from agent_configurations
        result = db.execute(text("""
            SELECT conversation_flow
            FROM agent_configurations
            WHERE company_id = :company_id
            LIMIT 1
        """), {"company_id": company_id}).fetchone()

        redirect_configs = {}
        if result and result.conversation_flow:
            conversation_flow = result.conversation_flow
            redirect_configs = {
                'financial': conversation_flow.get('financial_redirect', {}),
                'maintenance': conversation_flow.get('maintenance_redirect', {}),
                'general': conversation_flow.get('regular_redirect', {}),
                'active_customers': conversation_flow.get('active_customers_redirect', {})
            }

        return {
            'enabled': True,
            'confidence_threshold': 0.7,  # Minimum confidence for customer identification
            'redirect_configs': redirect_configs,
            'llm_model': 'gpt-4o-mini',  # Model for customer analysis
            'max_analysis_tokens': 300
        }

    except Exception as e:
        logger.error(f"Error loading customer identification config for company {company_id}: {e}")
        return {
            'enabled': False,
            'confidence_threshold': 0.0,
            'redirect_configs': {}
        }
