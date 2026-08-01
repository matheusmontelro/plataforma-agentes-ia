"""
Company Information Tools - Function tools for company data retrieval
"""

import logging
from typing import Dict, Any
from pydantic import BaseModel

from agents import function_tool

logger = logging.getLogger(__name__)

class InfoRequest(BaseModel):
    """Request for company information"""
    info_type: str = "geral"  # geral, servicos, precos, equipe, contato

@function_tool
def get_company_information(request: InfoRequest) -> Dict[str, Any]:
    """
    Get company information (services, prices, team, location, etc.)

    Args:
        request: Type of information requested

    Returns:
        Dict with company information
    """
    try:
        # This will be injected by the manager with proper company context
        return {
            "tool_name": "get_company_information",
            "info_type": request.info_type,
            "requires_company_context": True
        }

    except Exception as e:
        logger.error(f"Error in get_company_information tool: {e}")
        return {
            "message": "Erro ao buscar informações da empresa",
            "error": str(e)
        }