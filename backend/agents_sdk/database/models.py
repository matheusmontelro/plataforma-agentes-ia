"""
Database models for Agents SDK
"""

from sqlalchemy import Column, BigInteger, String, Text, TIMESTAMP, Boolean, JSON, Date, Time, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import ForeignKey, UniqueConstraint, func

Base = declarative_base()

class CompanySlot(Base):
    """
    Table to replace Redis slots caching
    Temporal context stored in slot_metadata JSON for LLM understanding
    """
    __tablename__ = 'company_slots'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, nullable=False)
    slot_date = Column(Date, nullable=False)
    slot_time = Column(Time, nullable=False)
    service_type = Column(String(100))
    is_available = Column(Boolean, default=True)

    # Metadata with temporal context for LLM
    source = Column(String(50), default='system')  # 'google', 'clinicorp', 'manual'
    slot_metadata = Column(JSON)  # Contains temporal context + other data
    """
    slot_metadata JSON structure:
    {
        "weekday_name": "Segunda-feira",     # Nome do dia da semana
        "day_type": "hoje",                  # hoje, amanha, semana_que_vem, etc.
        "time_period": "tarde",              # manha, tarde, noite
        "relative_days": 0,                  # 0=hoje, 1=amanha, 2=depois_amanha
        "generated_at": "2025-09-05T16:33:02",
        "integration_data": {...}           # Dados específicos da integração
    }
    """

    # Timestamps
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    expires_at = Column(TIMESTAMP)  # TTL replacement

    # Constraints
    __table_args__ = (
        UniqueConstraint('company_id', 'slot_date', 'slot_time'),
    )

class AgentExecution(Base):
    """
    Log agent executions for monitoring and conversation grouping
    """
    __tablename__ = 'agent_executions'

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # Conversation identifiers
    company_id = Column(BigInteger, nullable=False)
    phone = Column(String(20), nullable=False)
    conversation_group = Column(String(100))  # For grouping multiple traces

    # Execution details
    workflow_name = Column(String(255))  # phone_companyId format
    trace_id = Column(String(255))

    # Input/Output
    user_input = Column(Text)
    agent_response = Column(Text)

    # Performance metrics
    execution_time_ms = Column(Integer)
    tokens_used = Column(Integer)

    # Tools and metadata
    tools_called = Column(JSON)
    execution_metadata = Column(JSON)  # Renamed from 'metadata' (reserved word)

    # Status
    status = Column(String(20), default='success')  # success, error, timeout
    error_message = Column(Text)

    # Timestamp
    created_at = Column(TIMESTAMP, server_default=func.now())

class CompanyEmbedding(Base):
    """
    Store processed embeddings from agent_config
    """
    __tablename__ = 'company_embeddings'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, nullable=False, unique=True)

    # Processed configuration
    instructions = Column(Text, nullable=False)  # Generated instructions
    config_hash = Column(String(64), nullable=False)  # Hash for cache invalidation

    # Structured data
    company_info = Column(JSON)
    services_info = Column(JSON)
    team_info = Column(JSON)
    financial_info = Column(JSON)
    conversation_patterns = Column(JSON)

    # Timestamps
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())