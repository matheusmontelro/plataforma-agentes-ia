"""
Conversation tracing utilities for OpenAI Agents SDK
Note: Tracing is automatic in OpenAI Agents SDK - this just provides naming conventions
"""

import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class ConversationTracer:
    """
    Manages conversation naming conventions for OpenAI automatic tracing
    """

    def __init__(self):
        self.conversation_groups: Dict[str, str] = {}  # phone -> group_id mapping
        logger.info("✅ ConversationTracer initialized (tracing is automatic)")

    def setup_tracing(self):
        """No setup needed - tracing is automatic in OpenAI Agents SDK"""
        logger.info("✅ Tracing is automatic - no setup required")

    def get_workflow_name(self, phone: str, company_id: int) -> str:
        """
        Generate workflow name: phone_companyId
        Example: 5500900000001_company42
        """
        return f"{phone}_company{company_id}"

    def get_conversation_group(self, phone: str, company_id: int) -> str:
        """
        Generate conversation group for multiple traces
        Example: conv_5500900000001_company42
        """
        return f"conv_{phone}_company{company_id}"

    def get_trace_context(
        self,
        phone: str,
        company_id: int,
        user_input: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Get trace context for Runner.run()

        Returns context dict ready to be used in Runner.run()
        """
        workflow_name = self.get_workflow_name(phone, company_id)
        conversation_group = self.get_conversation_group(phone, company_id)

        # Store group mapping
        self.conversation_groups[phone] = conversation_group

        trace_metadata = {
            "phone": phone,
            "company_id": company_id,
            "conversation_group": conversation_group,
            "workflow_name": workflow_name,
            "input_preview": user_input[:100] if user_input else "",
            **(metadata or {})
        }

        return {
            "trace_name": workflow_name,
            "metadata": trace_metadata
        }

# Global tracer instance
tracer = ConversationTracer()
