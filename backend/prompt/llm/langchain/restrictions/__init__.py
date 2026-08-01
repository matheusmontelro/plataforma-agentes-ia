"""
Action Restriction and Validation System
=======================================

This module implements comprehensive action validation and response filtering
based on customer status, ensuring that conversations stay within appropriate
boundaries for each type of customer interaction.

Components:
- action_validator.py: Validates actions against customer status
- response_filter.py: Filters LLM responses for compliance
- restriction_models.py: Pydantic models for restrictions
"""

from .action_validator import ActionValidator, ValidationResult, ValidationStrategy

__all__ = [
    "ActionValidator",
    "ValidationResult",
    "ValidationStrategy"
]