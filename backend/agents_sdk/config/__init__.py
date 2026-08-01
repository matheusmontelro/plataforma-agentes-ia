"""
Configuration module for Agents SDK
"""

from .model_config import get_model_config, DEFAULT_MODEL, MAX_TURNS, TEMPERATURE, ENABLE_TRACING

# Import from parent config.py file
import sys
from pathlib import Path
parent_dir = Path(__file__).parent.parent
config_file = parent_dir / 'config.py'

# Import functions from parent config.py
import importlib.util
spec = importlib.util.spec_from_file_location("parent_config", config_file)
parent_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent_config)

is_company_enabled = parent_config.is_company_enabled
is_customer_identification_enabled = parent_config.is_customer_identification_enabled
get_customer_identification_config = parent_config.get_customer_identification_config

__all__ = [
    'get_model_config',
    'DEFAULT_MODEL',
    'MAX_TURNS',
    'TEMPERATURE',
    'ENABLE_TRACING',
    'is_company_enabled',
    'is_customer_identification_enabled',
    'get_customer_identification_config'
]