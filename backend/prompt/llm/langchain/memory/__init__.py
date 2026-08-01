"""
Sistema de gerenciamento de contexto conversacional usando LangChain.

Este módulo fornece uma implementação profissional e extensível para detectar
e gerenciar mudanças de contexto em conversas, substituindo implementações
anteriores baseadas em regex e lógica hardcoded.

Componentes principais:
- ContextManager: Orquestrador principal
- ContextExtractionChain: Análise de contexto usando LLM
- InterventionDetector: Detecção rápida de intervenções
- InstructionGenerator: Geração dinâmica de instruções
- ContextAwareMemory: Memória com tracking de mudanças

Exemplo de uso:
    from backend.prompt.llm.langchain.memory import ContextManager

    manager = ContextManager(company_id=42)
    requires_context, instruction = manager.check_context(messages, user_input)
"""

from .models import (
    InterventionType,
    Entity,
    ContextAnalysis,
    ContextShift,
    InstructionTemplate
)

from .context_manager import (
    ContextManager,
    check_context_enhanced
)

from .extraction_chain import ContextExtractionChain
from .intervention_detector import InterventionDetector
from .instruction_generator import InstructionGenerator
from .context_aware_memory import (
    ContextAwareMemory,
    SimpleContextTracker
)

# Versão do módulo
__version__ = "1.0.0"

# Exportações principais
__all__ = [
    # Classes principais
    "ContextManager",
    "ContextExtractionChain",
    "InterventionDetector",
    "InstructionGenerator",
    "ContextAwareMemory",
    "SimpleContextTracker",

    # Modelos
    "InterventionType",
    "Entity",
    "ContextAnalysis",
    "ContextShift",
    "InstructionTemplate",

    # Funções utilitárias
    "check_context_enhanced",

    # Metadados
    "__version__"
]

# Configuração de logging para o módulo
import logging

logger = logging.getLogger(__name__)

# Função de conveniência para inicialização rápida
def create_context_manager(company_id: int, **kwargs) -> ContextManager:
    """
    Função de conveniência para criar ContextManager com configurações padrão.

    Args:
        company_id: ID da empresa
        **kwargs: Argumentos adicionais para ContextManager

    Returns:
        Instância configurada do ContextManager
    """
    return ContextManager(company_id=company_id, **kwargs)

# Função para validar dependências
def check_dependencies() -> bool:
    """
    Verifica se todas as dependências necessárias estão disponíveis.

    Returns:
        True se todas as dependências estão OK
    """
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import BaseMessage
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import PydanticOutputParser
        from pydantic import BaseModel

        logger.info("[ContextMemory] Todas as dependências verificadas com sucesso")
        return True

    except ImportError as e:
        logger.error(f"[ContextMemory] Dependência faltando: {e}")
        return False

# Validação automática na importação
if not check_dependencies():
    logger.warning("[ContextMemory] Algumas dependências podem estar faltando")

logger.info(f"[ContextMemory] Módulo inicializado - versão {__version__}")
