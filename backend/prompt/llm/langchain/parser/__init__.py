"""
Parser inteligente com LangChain
================================

Sistema modular de parsing que resolve o problema de extração incorreta
quando usuário responde apenas "sim" ou outras confirmações simples.
"""

from .smart_parser import SmartParser
from .models import ExtractedData

__all__ = ["SmartParser", "ExtractedData"]