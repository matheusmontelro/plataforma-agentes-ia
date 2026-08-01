"""
Analytics Module - Análise de Mensagens e Métricas

Este módulo fornece ferramentas para análise de mensagens enviadas pela IA,
contabilização de tokens e estimativa de custos.
"""

from .message_analytics import MessageAnalytics, analyze_company_messages

__all__ = ['MessageAnalytics', 'analyze_company_messages']
