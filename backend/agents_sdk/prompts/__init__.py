"""
Prompts Package
Exports legacy artifacts for backward compatibility and new registry.
"""

from .legacy_domain import CompanyContext, _build_prompt_variables, business_company_instructions
from .registry import PromptRegistry

__all__ = [
    'CompanyContext',
    '_build_prompt_variables',
    'business_company_instructions',
    'PromptRegistry',
]
