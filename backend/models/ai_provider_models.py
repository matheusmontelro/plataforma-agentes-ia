"""Encrypted AI provider credentials scoped to a company."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from backend.db import Base


class AIProviderCredential(Base):
    """An encrypted provider credential owned by one workspace."""

    __tablename__ = "ai_provider_credentials"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(
        BigInteger,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider = Column(String(30), nullable=False, server_default="openai")
    api_key_encrypted = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, server_default="valid")
    available_models = Column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    last_validated_at = Column(TIMESTAMP(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    company = relationship("Company", foreign_keys=[company_id])

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "provider",
            name="uq_ai_provider_credentials_company_provider",
        ),
        CheckConstraint(
            "provider = 'openai'",
            name="chk_ai_provider_credentials_provider",
        ),
        CheckConstraint(
            "status IN ('valid', 'invalid', 'error')",
            name="chk_ai_provider_credentials_status",
        ),
        Index("idx_ai_provider_credentials_company", "company_id"),
    )
