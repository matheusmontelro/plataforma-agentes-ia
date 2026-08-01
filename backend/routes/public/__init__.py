"""
Rotas públicas da API
Estas rotas não requerem autenticação JWT, mas usam API Key para segurança
"""

from .company_setup import router as company_setup_router

__all__ = ["company_setup_router"]