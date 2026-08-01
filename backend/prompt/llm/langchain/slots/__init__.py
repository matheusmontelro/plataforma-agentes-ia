"""
Sistema de Agendamento com LangChain
===================================

Este módulo implementa um sistema profissional de agendamento usando LangChain
com arquitetura modular, type safety e observabilidade completa.

Componentes principais:
- models.py: Modelos Pydantic para validação de dados
- chains.py: Chains LangChain para processamento
- agents.py: Agentes inteligentes para busca de slots
- memory.py: Gerenciamento otimizado de memória
- callbacks.py: Handlers para erro e observabilidade
- workflow.py: Orquestração com LangGraph
- utils.py: Funções auxiliares

Uso:
    from langchain.slots import SchedulingWorkflow

    workflow = SchedulingWorkflow(db, company_id)
    result = workflow.process_user_input(user_input, contact_phone)
"""

from .workflow import SchedulingWorkflow
from .models import SchedulingIntent, SlotSelection
from .chains import create_scheduling_chain

__all__ = [
    "SchedulingWorkflow",
    "SchedulingIntent",
    "SlotSelection",
    "create_scheduling_chain"
]