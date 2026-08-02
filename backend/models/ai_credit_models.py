"""Models for internal AI credit tracking and usage ledger."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from backend.db import Base


class AICreditWallet(Base):
    """Credit balance per company for internal AI usage accounting."""

    __tablename__ = "ai_credit_wallets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    balance_credits = Column(Numeric(18, 6), nullable=False, server_default="0")
    total_granted_credits = Column(Numeric(18, 6), nullable=False, server_default="0")
    total_used_credits = Column(Numeric(18, 6), nullable=False, server_default="0")
    currency = Column(String(20), nullable=False, server_default="internal_credit")
    status = Column(String(20), nullable=False, server_default="active")
    wallet_metadata = Column(JSONB, nullable=False, server_default="{}")
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company", foreign_keys=[company_id])

    __table_args__ = (
        UniqueConstraint("company_id", name="uq_ai_credit_wallet_company"),
        CheckConstraint("status IN ('active', 'suspended')", name="chk_ai_credit_wallet_status"),
        Index("idx_ai_credit_wallets_company", "company_id"),
    )


class AIUsageEvent(Base):
    """Immutable-ish event describing AI provider usage for text or audio."""

    __tablename__ = "ai_usage_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    # AgentExecution lives in the Agents SDK metadata, so declaring an ORM
    # ForeignKey here makes SQLAlchemy fail to resolve the table at flush time.
    # The database migration keeps the real FK constraint; the ORM stores the id.
    agent_execution_id = Column(BigInteger, nullable=True)
    agent_key = Column(String(100), nullable=True)
    agent_name = Column(String(255), nullable=True)
    phone = Column(String(30), nullable=True)
    conversation_group = Column(String(100), nullable=True)
    trace_id = Column(String(255), nullable=True)

    provider = Column(String(50), nullable=False)
    operation = Column(String(50), nullable=False)
    model = Column(String(120), nullable=True)
    status = Column(String(20), nullable=False, server_default="success")

    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    cached_tokens = Column(Integer, nullable=True)
    reasoning_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    text_characters = Column(Integer, nullable=True)
    provider_usage_units = Column(Numeric(18, 6), nullable=True)
    estimated_cost_usd = Column(Numeric(18, 8), nullable=True)
    estimated_cost_brl = Column(Numeric(18, 8), nullable=True)
    revenue_brl = Column(Numeric(18, 8), nullable=True)
    gross_profit_brl = Column(Numeric(18, 8), nullable=True)
    margin_percent = Column(Numeric(9, 4), nullable=True)
    internal_credits_charged = Column(Numeric(18, 6), nullable=False, server_default="0")

    provider_request_id = Column(String(255), nullable=True)
    provider_response_id = Column(String(255), nullable=True)
    pricing_snapshot = Column(JSONB, nullable=False, server_default="{}")
    usage_metadata = Column(JSONB, nullable=False, server_default="{}")
    error_message = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    company = relationship("Company", foreign_keys=[company_id])

    __table_args__ = (
        CheckConstraint("provider IN ('openai', 'elevenlabs')", name="chk_ai_usage_provider"),
        CheckConstraint("operation IN ('llm_response', 'tts')", name="chk_ai_usage_operation"),
        CheckConstraint("status IN ('success', 'failed', 'skipped')", name="chk_ai_usage_status"),
        Index("idx_ai_usage_events_company_created", "company_id", "created_at"),
        Index("idx_ai_usage_events_provider_operation", "provider", "operation"),
        Index("idx_ai_usage_events_agent_execution", "agent_execution_id"),
    )


class AICreditTransaction(Base):
    """Ledger entry that changes or records the internal credit balance."""

    __tablename__ = "ai_credit_transactions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    wallet_id = Column(BigInteger, ForeignKey("ai_credit_wallets.id", ondelete="CASCADE"), nullable=False)
    usage_event_id = Column(BigInteger, ForeignKey("ai_usage_events.id", ondelete="SET NULL"), nullable=True)
    transaction_type = Column(String(30), nullable=False)
    amount_credits = Column(Numeric(18, 6), nullable=False)
    balance_after = Column(Numeric(18, 6), nullable=False)
    description = Column(String(255), nullable=True)
    transaction_metadata = Column(JSONB, nullable=False, server_default="{}")
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    company = relationship("Company", foreign_keys=[company_id])
    wallet = relationship("AICreditWallet", foreign_keys=[wallet_id])
    usage_event = relationship("AIUsageEvent", foreign_keys=[usage_event_id])

    __table_args__ = (
        CheckConstraint(
            "transaction_type IN ('debit', 'credit', 'refund', 'adjustment')",
            name="chk_ai_credit_transaction_type",
        ),
        Index("idx_ai_credit_transactions_company_created", "company_id", "created_at"),
        Index("idx_ai_credit_transactions_wallet", "wallet_id"),
        Index("idx_ai_credit_transactions_usage_event", "usage_event_id"),
    )
