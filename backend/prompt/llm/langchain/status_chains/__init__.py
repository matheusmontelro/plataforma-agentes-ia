"""
Status-Specific Chain Implementations
====================================

Specialized LangChain implementations for different customer statuses:
- BaseCustomerChain: Common functionality and patterns
- ScheduledCustomerChain: For customers with scheduled appointments
- AttendedCustomerChain: For customers who attended consultations
- PurchasedCustomerChain: For customers who made purchases
- LeadCustomerChain: For new leads without history

Each chain enforces specific action restrictions and provides
context-appropriate responses based on customer status.
"""

from .base_chain import BaseCustomerChain
from .scheduled_chain import ScheduledCustomerChain
from .attended_chain import AttendedCustomerChain
from .purchased_chain import PurchasedCustomerChain
from .lead_chain import LeadCustomerChain

__all__ = [
    "BaseCustomerChain",
    "ScheduledCustomerChain",
    "AttendedCustomerChain",
    "PurchasedCustomerChain",
    "LeadCustomerChain"
]