"""
Customer Routing Module for LangChain-based Status Detection
==========================================================

This module implements a professional customer status routing system that:
1. Detects customer status from database (scheduled, attended, purchased, etc.)
2. Routes conversations to appropriate specialized chains
3. Enforces action restrictions based on customer status
4. Provides type-safe interfaces for all components

Components:
- models.py: Pydantic models for type safety
- status_detector.py: Database-driven status detection
- routing_chain.py: Main routing chain orchestrator
- customer_status_service.py: Database service layer
"""

from .models import (
    CustomerStatus,
    CustomerStatusResult,
    StatusDetectionContext,
    RoutingResult
)

__all__ = [
    "CustomerStatus",
    "CustomerStatusResult",
    "StatusDetectionContext",
    "RoutingResult"
]