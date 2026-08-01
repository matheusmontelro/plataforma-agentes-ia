"""Entrypoint preguiçoso para o runtime opcional do Agents SDK.

Manter este módulo sem imports eager permite que Alembic e outros comandos de
infraestrutura carreguem somente os modelos SQLAlchemy em uma instalação
limpa, antes das dependências de IA serem inicializadas.
"""

__all__ = [
    "tracer",
    "CompanySlot",
    "AgentExecution",
    "CompanyEmbedding",
    "AgentConfigCompiler",
    "AgentCreationConfig",
    "AgentRuntimeRegistry",
    "compile_agent_preview",
]


def __getattr__(name: str):
    if name == "tracer":
        from .tracing import tracer

        return tracer
    if name in {"CompanySlot", "AgentExecution", "CompanyEmbedding"}:
        from .database import AgentExecution, CompanyEmbedding, CompanySlot

        return {
            "CompanySlot": CompanySlot,
            "AgentExecution": AgentExecution,
            "CompanyEmbedding": CompanyEmbedding,
        }[name]
    if name in {
        "AgentConfigCompiler",
        "AgentCreationConfig",
        "AgentRuntimeRegistry",
        "compile_agent_preview",
    }:
        from .agent_builder import (
            AgentConfigCompiler,
            AgentCreationConfig,
            AgentRuntimeRegistry,
            compile_agent_preview,
        )

        return {
            "AgentConfigCompiler": AgentConfigCompiler,
            "AgentCreationConfig": AgentCreationConfig,
            "AgentRuntimeRegistry": AgentRuntimeRegistry,
            "compile_agent_preview": compile_agent_preview,
        }[name]
    raise AttributeError(name)
