# Memory Models for Agents SDK
from sqlalchemy import (
    Column, BigInteger, String, Text, Boolean,
    ForeignKey, TIMESTAMP, func, UniqueConstraint, Index
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from backend.db import Base


class AgentsSDKRun(Base):
    """Armazena informações sobre cada execução do agent"""
    __tablename__ = "agents_sdk_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    contact_phone = Column(String(20), nullable=False)
    run_id = Column(String(255), nullable=False, unique=True)
    thread_id = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False)  # 'running', 'completed', 'failed'
    started_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    run_metadata = Column("metadata", JSONB, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relacionamentos
    company = relationship("Company", foreign_keys=[company_id])
    messages = relationship("AgentsSDKMessage", back_populates="run", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_agents_runs_company_phone', 'company_id', 'contact_phone'),
        Index('idx_agents_runs_thread', 'thread_id'),
        Index('idx_agents_runs_status', 'status'),
    )


class AgentsSDKMessage(Base):
    """Armazena mensagens de cada run"""
    __tablename__ = "agents_sdk_messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(String(255), ForeignKey("agents_sdk_runs.run_id", ondelete="CASCADE"), nullable=False)
    message_type = Column(String(20), nullable=False)  # 'user', 'assistant', 'tool', 'system'
    content = Column(Text, nullable=False)
    role = Column(String(20), nullable=False)
    tool_calls = Column(JSONB, nullable=True)
    tool_outputs = Column(JSONB, nullable=True)
    message_metadata = Column("metadata", JSONB, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relacionamentos
    run = relationship("AgentsSDKRun", back_populates="messages")

    __table_args__ = (
        Index('idx_agents_messages_run', 'run_id'),
        Index('idx_agents_messages_type', 'message_type'),
    )


class AgentsSDKMemory(Base):
    """Armazena memória de longo prazo do cliente"""
    __tablename__ = "agents_sdk_memory"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    contact_phone = Column(String(20), nullable=False)
    memory_key = Column(String(255), nullable=False)
    memory_value = Column(JSONB, nullable=False)
    memory_type = Column(String(50), nullable=False)  # 'preference', 'context', 'history', 'fact'
    expires_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relacionamentos
    company = relationship("Company", foreign_keys=[company_id])

    __table_args__ = (
        UniqueConstraint('company_id', 'contact_phone', 'memory_key', name='uq_agents_memory_key'),
        Index('idx_agents_memory_lookup', 'company_id', 'contact_phone'),
        Index('idx_agents_memory_type', 'memory_type'),
        Index('idx_agents_memory_expires', 'expires_at'),
    )
