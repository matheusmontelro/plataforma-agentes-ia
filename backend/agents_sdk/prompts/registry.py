"""
Prompt Registry
Routing logic for determining which instruction set to use.
"""
import logging
from .legacy_domain import business_company_instructions
from .templates.generic import get_generic_instructions

logger = logging.getLogger(__name__)

class PromptRegistry:
    @staticmethod
    def get_instructions(run_context, agent) -> str:
        """
        Determines which instructions to load based on context.
        """
        try:
            context = getattr(run_context, "context", None)
            organization_type = getattr(context, "organization_type", None)
            data = (
                getattr(context, "organization_data", None)
                or getattr(context, "company_data", None)
                or {}
            )

            configured_type = (
                organization_type
                or data.get("organization_type")
                or data.get("business_type")
                or data.get("domain")
            )

            business_types = {"business", "company", "serviÃ§os", "de serviÃ§os"}
            if configured_type and str(configured_type).lower() not in business_types:
                return get_generic_instructions(run_context, agent)

            if data.get("organization_info") and not data.get("company_info"):
                return get_generic_instructions(run_context, agent)

            return business_company_instructions(run_context, agent)

        except Exception as e:
            logger.error(f"Error in PromptRegistry: {e}")
            # Fallback
            return business_company_instructions(run_context, agent)

    @staticmethod
    def get_generic_instructions(run_context, agent) -> str:
        return get_generic_instructions(run_context, agent)
