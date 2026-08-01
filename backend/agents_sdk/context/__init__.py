"""
Context Management

New platform code should prefer generic conversation/contact context. The
company/customer classes remain exported for backward compatibility with the
existing business adapter.
"""

from .organization_data_service import CompanyDataService
from .conversation_context import (
    ClientContext,
    ContactContext,
    ContactLifecycle,
    ConversationChannel,
    ConversationContext,
    LeadContext,
)
from .contact_context import CustomerContext, CustomerContextManager

__all__ = [
    "CompanyDataService",
    "ConversationChannel",
    "ContactLifecycle",
    "ConversationContext",
    "ContactContext",
    "LeadContext",
    "ClientContext",
    "CustomerContext",
    "CustomerContextManager",
]
