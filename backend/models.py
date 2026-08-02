# backend/models.py

from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Boolean, Numeric, Enum, Float, Date, Time, DateTime,
    ForeignKey, TIMESTAMP, func, UniqueConstraint, CheckConstraint, Index, JSON, text, ARRAY
)
from sqlalchemy.orm import relationship, backref
from backend.db import Base
from sqlalchemy.dialects.postgresql import UUID, JSONB
import uuid
import enum
from pydantic import BaseModel
from typing import Dict, Optional
from datetime import date, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_AGENDA_TIMEZONE = "America/Sao_Paulo"


def _safe_zoneinfo(timezone_name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name or DEFAULT_AGENDA_TIMEZONE)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_AGENDA_TIMEZONE)


def _initial_client_ownership_company_id(context):
    """Anchor ownership to the workspace selected when the Client is created."""
    return context.get_current_parameters().get("company_id")


class Company(Base):
    __tablename__ = "companies"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)  # já existia
    cnpj = Column(String(14), nullable=False, unique=True)
    # Novas colunas adicionadas via ALTER TABLE no banco:
    name_company = Column(String(255), nullable=True)  # campo para nome customizável da empresa
    logo_url = Column(Text, nullable=True)            # campo para URL do logo

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Campo do Mirror Webhook
    mirror_webhook_url = Column(Text, nullable=True)  # <--- AQUI

    # Campos de Business Type (Plataforma Universal)
    business_type_id = Column(Integer, ForeignKey("business_types.id"), server_default='1', nullable=False)
    settings = Column(JSON, server_default='{}', nullable=False)

    # Z-API Integration
    zapi_instance_id = Column(String(255), nullable=True)
    zapi_token = Column(String(255), nullable=True)

    # WAHA Integration
    waha_session_name = Column(String(255), nullable=True)
    waha_enabled = Column(Boolean, server_default='false', nullable=False)
    operational_status = Column(String(30), server_default="active", nullable=False)
    operational_epoch = Column(
        BigInteger,
        server_default="0",
        default=0,
        nullable=False,
    )

    # Relacionamentos
    # clients = relationship("Client", back_populates="company")
    business_type = relationship("BusinessType", back_populates="companies")
    agent_configurations = relationship("AgentConfiguration", back_populates="company")
    agent_workforces = relationship("AgentWorkforce", back_populates="company", cascade="all, delete-orphan")
    calendar_integrations = relationship("CalendarIntegration", back_populates="company")
    support_group_integrations = relationship("SupportGroupIntegration", back_populates="company")
    telegram_integrations = relationship("TelegramIntegration", back_populates="company", cascade="all, delete-orphan")
    clients_association = relationship("ClientCompany", back_populates="company")
    users = relationship("User", back_populates="company")
    pipelines = relationship("Pipeline", back_populates="company", cascade="all, delete-orphan")

class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password = Column(String)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    # `company_id` is mutable UI context. This column is the immutable root used
    # by offboarding and must never be changed by workspace selection.
    ownership_company_id = Column(
        BigInteger,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        default=_initial_client_ownership_company_id,
        index=True,
    )
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    mirror_webhook_url = Column(Text, nullable=True)
    api_key = Column(String(64), unique=True, index=True, nullable=True)  # Nova coluna
    billing_profile = Column(JSONB, nullable=False, server_default="{}")
    is_active = Column(Boolean, nullable=False, server_default='true')
    auth_token_version = Column(Integer, nullable=False, server_default="0")

    # Relacionamentos permanecem os mesmos
    messages = relationship("Message", back_populates="client")
    contacts = relationship("Contact", back_populates="client")
    companies = relationship("ClientCompany", back_populates="client")
    users = relationship("User", back_populates="client")
    user_sessions = relationship("UserSession")

class ClientCompany(Base):
    __tablename__ = 'client_companies'

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        UniqueConstraint('client_id', 'company_id', name='uq_client_company'),
    )

    # Relacionamentos
    client = relationship("Client", back_populates="companies")
    company = relationship("Company", back_populates="clients_association")  # Podemos criar algo como 'clients_association' no model Company


class CustomerManagedCompany(Base):
    __tablename__ = "customer_managed_companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    customer_id = Column(BigInteger, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    managed_company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    created_by_client_id = Column(Integer, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    trial_days = Column(Integer, server_default="0", nullable=False)
    trial_started_at = Column(TIMESTAMP(timezone=True), nullable=True)
    trial_ends_at = Column(TIMESTAMP(timezone=True), nullable=True)
    lifecycle_status = Column(String(20), server_default="active", nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    owner_company = relationship("Company", foreign_keys=[owner_company_id])
    managed_company = relationship("Company", foreign_keys=[managed_company_id])
    customer = relationship("Customer", foreign_keys=[customer_id])
    created_by_client = relationship("Client", foreign_keys=[created_by_client_id])

    __table_args__ = (
        UniqueConstraint("owner_company_id", "customer_id", "managed_company_id", name="uq_customer_managed_company"),
        UniqueConstraint("owner_company_id", "managed_company_id", name="uq_owner_managed_company"),
        CheckConstraint("trial_days IN (0, 3, 7, 14, 30)", name="chk_customer_managed_company_trial_days"),
        CheckConstraint("lifecycle_status IN ('active', 'trialing', 'expired', 'archived')", name="chk_customer_managed_company_lifecycle"),
        Index("idx_customer_managed_companies_owner", "owner_company_id"),
        Index("idx_customer_managed_companies_customer", "customer_id"),
        Index("idx_customer_managed_companies_managed", "managed_company_id"),
        Index("idx_customer_managed_companies_lifecycle", "lifecycle_status"),
        Index("idx_customer_managed_companies_trial_ends", "trial_ends_at"),
    )

class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String)
    phone = Column(String)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Se você quiser registrar outra data de entrada diferente do created_at
    data_entrada = Column(DateTime, server_default=func.now(), nullable=True)

    source_id = Column(String(255), nullable=True)
    thumbnail_url = Column(Text, nullable=True)
    sender_lid = Column(String(255), nullable=True)

    follow_up_sequence_id = Column(Integer, ForeignKey("follow_up_sequences.id", ondelete="SET NULL"))

    # relationships
    client = relationship("Client", foreign_keys=[client_id])
    company = relationship("Company", foreign_keys=[company_id])
    follow_up_sequence = relationship("FollowUpSequence", foreign_keys=[follow_up_sequence_id], lazy="joined")

    # Kanban Relationships - Enhanced for Custom Pipelines
    pipeline_id = Column(Integer, ForeignKey("pipelines.id", ondelete="SET NULL"), nullable=True)
    current_stage_id = Column(Integer, ForeignKey("pipeline_stages.id", ondelete="SET NULL"), nullable=True)
    pipeline_entered_at = Column(DateTime, server_default=func.now(), nullable=True)
    last_stage_move_at = Column(DateTime, server_default=func.now(), nullable=True)

    # Relacionamentos
    pipeline = relationship("Pipeline", foreign_keys=[pipeline_id])
    current_stage = relationship("PipelineStage", foreign_keys=[current_stage_id])
    stage = relationship("PipelineStage", foreign_keys=[current_stage_id])  # Mantido para compatibilidade
    pipeline_history = relationship("LeadPipelineHistory", back_populates="lead", order_by="LeadPipelineHistory.moved_at.desc()")

    # Deal value for Meta CAPI
    deal_value = Column(Numeric(12, 2), nullable=True, comment="Valor do negócio quando lead é convertido")

    # Relacionamentos com campos customizados
    custom_values = relationship("LeadCustomValue", back_populates="lead", cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    contact_phone = Column(String(20), nullable=False, index=True)
    message_type = Column(String(10), nullable=False)  # text, image, audio, video
    content = Column(Text, nullable=False)
    sender_phone = Column(String(20), nullable=False)
    sender_name = Column(String(255))
    from_me = Column(Boolean, nullable=False)
    timestamp = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    photo = Column(Text, nullable=True)
    zapi_message_id = Column(String(255), nullable=True, index=True)
    delivery_status = Column(String(20), nullable=True)
    delivery_ack = Column(Integer, nullable=True)
    delivery_status_updated_at = Column(TIMESTAMP(timezone=True), nullable=True)
    reply_to = Column(JSONB, nullable=True)
    reactions = Column(JSONB, server_default=text("'[]'::jsonb"), nullable=False)

    client = relationship("Client", back_populates="messages")
    company = relationship("Company", foreign_keys=[company_id])

class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    phone = Column(String(20), nullable=False)
    name = Column(String(255))
    photo = Column(Text)

    # Nova coluna para indicar se o contato está em modo humano (True) ou modo IA (False)
    human_mode = Column(Boolean, default=False, nullable=False)

    client = relationship("Client", back_populates="contacts")
    company = relationship("Company", foreign_keys=[company_id])

    # Relationship to tags via junction table
    contact_tags = relationship("ContactTag", back_populates="contact", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('client_id', 'phone', name='uq_contact_client_phone'),
    )


# ============ TAG SYSTEM ============

class TagCategory(Base):
    """User-created categories to organize tags"""
    __tablename__ = "tag_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(50), nullable=False)
    color = Column(String(7), default="#6B7280")  # Hex color, default gray
    display_order = Column(Integer, default=0)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company", foreign_keys=[company_id])
    tags = relationship("Tag", back_populates="category", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('company_id', 'name', name='uq_tag_category_company_name'),
        Index('idx_tag_categories_company', 'company_id'),
    )


class Tag(Base):
    """Tags that can be assigned to contacts"""
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    category_id = Column(BigInteger, ForeignKey("tag_categories.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(50), nullable=False)
    color = Column(String(7), default="#49A5D9")  # Hex color, default brand blue
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company", foreign_keys=[company_id])
    category = relationship("TagCategory", back_populates="tags")
    contact_tags = relationship("ContactTag", back_populates="tag", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('company_id', 'name', name='uq_tag_company_name'),
        Index('idx_tags_company', 'company_id'),
        Index('idx_tags_category', 'category_id'),
    )


class ContactTag(Base):
    """Junction table for many-to-many relationship between contacts and tags"""
    __tablename__ = "contact_tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contact_id = Column(BigInteger, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False)
    tag_id = Column(BigInteger, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    contact = relationship("Contact", back_populates="contact_tags")
    tag = relationship("Tag", back_populates="contact_tags")

    __table_args__ = (
        UniqueConstraint('contact_id', 'tag_id', name='uq_contact_tag'),
        Index('idx_contact_tags_contact', 'contact_id'),
        Index('idx_contact_tags_tag', 'tag_id'),
    )


class AgentConfiguration(Base):
    __tablename__ = 'agent_configurations'
    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey('companies.id', ondelete="CASCADE"), nullable=False)
    assistant_identity = Column(JSON)
    assistant_tone_and_voice = Column(JSON)
    company_info = Column(JSON)
    team_and_specialties = Column(JSON)
    scheduling_config = Column(JSON)
    financial_config = Column(JSON)
    conversation_flow = Column(JSON)
    generated_prompt = Column(Text, nullable=True)  # Stores the AI-generated or manually edited prompt
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    company = relationship("Company", back_populates="agent_configurations")

    # --- Generic Aliases for Universal Platform ---
    @property
    def organization_info(self):
        """Generic alias for company_info"""
        return self.company_info

    @organization_info.setter
    def organization_info(self, value):
        self.company_info = value

    @property
    def team_and_resources(self):
        """Generic alias for team_and_specialties"""
        return self.team_and_specialties

    @team_and_resources.setter
    def team_and_resources(self, value):
        self.team_and_specialties = value


class AgentWorkforce(Base):
    __tablename__ = "agent_workforces"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(30), server_default="draft", nullable=False)
    channel = Column(String(50), server_default="whatsapp", nullable=False)
    root_agent_key = Column(String(120), nullable=True)

    nodes = Column(JSON, server_default="[]", nullable=False)
    edges = Column(JSON, server_default="[]", nullable=False)
    viewport = Column(JSON, server_default='{"x": 0, "y": 0, "zoom": 1}', nullable=False)
    agent_configs = Column(JSON, server_default="{}", nullable=False)
    settings = Column(JSON, server_default="{}", nullable=False)

    version = Column(Integer, server_default="1", nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company", back_populates="agent_workforces")

    __table_args__ = (
        Index("idx_agent_workforces_company", "company_id"),
        Index("idx_agent_workforces_status", "company_id", "status"),
    )


class AgentDynamicFollowupEnrollment(Base):
    __tablename__ = "agent_dynamic_followup_enrollments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    workforce_id = Column(Integer, ForeignKey("agent_workforces.id", ondelete="CASCADE"), nullable=False)
    agent_key = Column(String(120), nullable=False)
    lead_id = Column(BigInteger, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    contact_id = Column(BigInteger, ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    pipeline_id = Column(Integer, ForeignKey("pipelines.id", ondelete="SET NULL"), nullable=True)
    start_stage_id = Column(Integer, ForeignKey("pipeline_stages.id", ondelete="SET NULL"), nullable=True)

    target_stage_ids = Column(JSON, server_default="[]", nullable=False)
    status = Column(String(20), server_default="active", nullable=False)
    next_step_number = Column(Integer, server_default="1", nullable=False)
    anchor_at = Column(TIMESTAMP(timezone=True), nullable=True)
    started_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    last_sent_at = Column(TIMESTAMP(timezone=True), nullable=True)
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    cancel_reason = Column(Text, nullable=True)
    last_error = Column(Text, nullable=True)
    config_snapshot = Column(JSON, server_default="{}", nullable=False)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    company = relationship("Company")
    workforce = relationship("AgentWorkforce")
    lead = relationship("Lead")
    contact = relationship("Contact")
    executions = relationship(
        "AgentDynamicFollowupExecution",
        back_populates="enrollment",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            status.in_(["active", "completed", "cancelled", "failed"]),
            name="chk_agent_dynamic_followup_enrollment_status",
        ),
        Index(
            "idx_agent_dynamic_followup_active",
            "company_id",
            "lead_id",
            "workforce_id",
            "agent_key",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("idx_agent_dynamic_followup_lead", "company_id", "lead_id", "status"),
        Index("idx_agent_dynamic_followup_workforce", "workforce_id", "status"),
    )


class AgentDynamicFollowupExecution(Base):
    __tablename__ = "agent_dynamic_followup_executions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    enrollment_id = Column(
        Integer,
        ForeignKey("agent_dynamic_followup_enrollments.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    workforce_id = Column(Integer, ForeignKey("agent_workforces.id", ondelete="CASCADE"), nullable=False)
    lead_id = Column(BigInteger, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    agent_key = Column(String(120), nullable=False)
    step_number = Column(Integer, nullable=False)
    channel = Column(String(30), server_default="whatsapp", nullable=False)
    objective = Column(Text, nullable=True)
    mini_prompt = Column(Text, nullable=False)

    status = Column(String(20), server_default="SCHEDULED", nullable=False)
    scheduled_for = Column(TIMESTAMP(timezone=True), nullable=False)
    executed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    generated_message = Column(Text, nullable=True)
    prompt_payload = Column(JSON, server_default="{}", nullable=False)
    openai_usage = Column(JSON, nullable=True)
    provider_response = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    enrollment = relationship("AgentDynamicFollowupEnrollment", back_populates="executions")
    company = relationship("Company")
    workforce = relationship("AgentWorkforce")
    lead = relationship("Lead")

    __table_args__ = (
        UniqueConstraint("enrollment_id", "step_number", name="uq_agent_dynamic_followup_execution_step"),
        CheckConstraint(
            status.in_(["SCHEDULED", "PROCESSING", "SUCCESS", "FAILED", "CANCELED", "SKIPPED"]),
            name="chk_agent_dynamic_followup_execution_status",
        ),
        Index("idx_agent_dynamic_followup_exec_due", "status", "scheduled_for"),
        Index("idx_agent_dynamic_followup_exec_lead", "company_id", "lead_id"),
        Index("idx_agent_dynamic_followup_exec_enrollment", "enrollment_id", "status"),
    )


class NPSResponse(Base):
    __tablename__ = "nps_responses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    lead_id = Column(BigInteger, ForeignKey("leads.id", ondelete="CASCADE"), nullable=True)
    contact_phone = Column(String(20), nullable=False, index=True)
    contact_name = Column(String(255), nullable=True)

    # Dados da enquete
    poll_message_id = Column(String(255), nullable=False)  # ID da mensagem da enquete no Z-API
    question = Column(Text, nullable=False)  # Pergunta enviada

    # Resposta
    score = Column(Integer, nullable=True)  # Nota de 0-10
    response_message_id = Column(String(255), nullable=True)  # ID da resposta no Z-API
    response_text = Column(Text, nullable=True)  # Texto completo da resposta

    # Status
    status = Column(String(20), default="sent", nullable=False)  # sent, answered, expired

    # Timestamps
    sent_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    answered_at = Column(TIMESTAMP(timezone=True), nullable=True)

    # Metadados
    campaign_name = Column(String(255), nullable=True)  # Para organizar campanhas
    context = Column(JSON, nullable=True)  # Dados adicionais (ex: pós-atendimento, pós-agendamento)

    # Relacionamentos
    company = relationship("Company", foreign_keys=[company_id])
    lead = relationship("Lead", foreign_keys=[lead_id])

    __table_args__ = (
        UniqueConstraint('poll_message_id', name='uq_nps_poll_message'),
        Index('idx_nps_company_date', 'company_id', 'sent_at'),
        Index('idx_nps_score', 'score'),
    )

class CalendarIntegration(Base):
    __tablename__ = "calendar_integrations"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    provider = Column(String(50), index=True)  # "google" ou "clinicorp"

    # Campos específicos para cada provider
    google_calendar_id = Column(String(255), nullable=True)
    google_calendar_summary = Column(String(255), nullable=True)
    google_account_email = Column(String(255), nullable=True)
    google_oauth_token = Column(JSON, nullable=True)
    google_oauth_scopes = Column(Text, nullable=True)
    clinicorp_username = Column(String(255), nullable=True)
    clinicorp_password = Column(String(255), nullable=True)
    clinicorp_code_link = Column(String(255), nullable=True)
    clinicorp_subscriber_id = Column(String(255), nullable=True)

    # (opcional) caso você queira estabelecer relação com Company
    company = relationship("Company", back_populates="calendar_integrations")

    clinicorp_details = relationship(
        "ClinicorpDetails",
        back_populates="calendar_integration",
        uselist=False, # Indica relacionamento 1-para-1
        cascade="all, delete-orphan" # Garante que ao deletar CalendarIntegration, ClinicorpDetails seja deletado pelo ORM
    )

class SupportGroupIntegration(Base):
    __tablename__ = "support_group_integrations"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    webhook_scheduling = Column(String(255), nullable=True)
    webhook_cancellation = Column(String(255), nullable=True)

    company = relationship("Company", back_populates="support_group_integrations")


class TelegramIntegration(Base):
    __tablename__ = "telegram_integrations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    bot_token_encrypted = Column(Text, nullable=False)
    bot_username = Column(String(255), nullable=True)
    bot_name = Column(String(255), nullable=True)
    default_chat_id = Column(String(255), nullable=True)
    default_chat_title = Column(String(255), nullable=True)
    status = Column(String(40), server_default="connected", nullable=False)
    last_error = Column(Text, nullable=True)
    last_validated_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    company = relationship("Company", back_populates="telegram_integrations")

    __table_args__ = (
        UniqueConstraint("company_id", name="uq_telegram_integrations_company"),
        Index("idx_telegram_integrations_company", "company_id"),
        Index("idx_telegram_integrations_status", "status"),
    )



class Agenda(Base):
    __tablename__ = "agendas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    slot_duration = Column(Integer, default=30, nullable=False) # Duration in minutes
    active = Column(Boolean, default=True)
    timezone = Column(String(50), default="America/Sao_Paulo", nullable=False) # Nova coluna
    safety_margin_minutes = Column(Integer, default=180, nullable=False) # Margem de segurança em minutos
    google_calendar_id = Column(String(255), nullable=True)
    google_calendar_summary = Column(String(255), nullable=True)
    google_calendar_time_zone = Column(String(80), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    company = relationship("Company", backref=backref("agendas", cascade="all, delete-orphan"))
    schedules = relationship("AgendaSchedule", back_populates="agenda", cascade="all, delete-orphan")

class AgendaSchedule(Base):
    __tablename__ = "agenda_schedules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agenda_id = Column(BigInteger, ForeignKey("agendas.id", ondelete="CASCADE"), nullable=False, index=True)
    day_of_week = Column(Integer, nullable=False) # 0=Monday, 6=Sunday

    # Morning Shift
    morning_start = Column(Time, nullable=True)
    morning_end = Column(Time, nullable=True)

    # Afternoon Shift
    afternoon_start = Column(Time, nullable=True)
    afternoon_end = Column(Time, nullable=True)

    # Night Shift
    night_start = Column(Time, nullable=True)
    night_end = Column(Time, nullable=True)

    agenda = relationship("Agenda", back_populates="schedules")

    __table_args__ = (
        UniqueConstraint('agenda_id', 'day_of_week', name='uq_agenda_day'),
    )

class Agendamento(Base):
    __tablename__ = "agendamentos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    lead_id = Column(BigInteger, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)

    # Aqui definimos o 'CURRENT_TIMESTAMP AT TIME ZONE "America/Sao_Paulo"'
    agendamento_realizado_em = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    nome = Column(String(255), nullable=True)
    phone = Column(String(20), nullable=True)
    consulta_data = Column(TIMESTAMP(timezone=True), nullable=True)
    midia = Column(Text, nullable=True)
    interesse = Column(Text, nullable=True)
    endereco = Column(Text, nullable=True)
    local_link = Column(Text, nullable=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    agenda_id = Column(BigInteger, ForeignKey("agendas.id", ondelete="SET NULL"), nullable=True) # Nova coluna
    customer_id = Column(String(255), nullable=True)
    id_agendamento = Column(String(255), nullable=True)
    event_id = Column(String(255), nullable=True)
    google_calendar_id = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, server_default='SCHEDULED')

    # --- NOVAS COLUNAS DE STATUS DE SYNC ---
    clinicorp_sync_status = Column(
        String(30), # Aumentado para VARCHAR(30) para nomes mais longos se necessário
        nullable=True,
        index=True,
        comment="Status da sincronização com Clinicorp (e.g., PENDING, SYNCED, FAILED, CANCELLED, CANCEL_FAILED)"
    )
    google_sync_status = Column(
        String(30), # Aumentado para VARCHAR(30)
        nullable=True,
        index=True,
        comment="Status da sincronização com Google Calendar"
    )
    # --------------------------------------

    __table_args__ = (
        UniqueConstraint('client_id', 'lead_id', 'consulta_data', name='agendamento_lead_client_uniq'),
    )

    client = relationship("Client", foreign_keys=[client_id])
    lead = relationship("Lead", foreign_keys=[lead_id])
    company = relationship("Company", foreign_keys=[company_id])
    agenda = relationship("Agenda", foreign_keys=[agenda_id])

    @property
    def consulta_timezone(self) -> str:
        agenda_timezone = getattr(getattr(self, "agenda", None), "timezone", None)
        return agenda_timezone or DEFAULT_AGENDA_TIMEZONE

    @property
    def consulta_data_local(self) -> Optional[str]:
        if not self.consulta_data:
            return None

        value = self.consulta_data
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        return value.astimezone(_safe_zoneinfo(self.consulta_timezone)).strftime("%Y-%m-%dT%H:%M:%S")

    @property
    def consulta_data_display(self) -> Optional[str]:
        if not self.consulta_data:
            return None

        value = self.consulta_data
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        return value.astimezone(_safe_zoneinfo(self.consulta_timezone)).strftime("%d/%m/%Y às %H:%M")

class FileType(str, enum.Enum):
    image = "image"    # minúsculo
    video = "video"    # minúsculo
    audio = "audio"    # minúsculo

class MediaFile(Base):
    __tablename__ = "media_files"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    file_name = Column(String(255), nullable=False)
    original_name = Column(String(255), nullable=False)
    file_type = Column(Enum(FileType), nullable=False)
    mime_type = Column(String(127), nullable=False)
    file_size = Column(BigInteger, nullable=False)

    file_path = Column(Text, nullable=False)
    relative_path = Column(Text, nullable=False)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relacionamentos
    client = relationship("Client", foreign_keys=[client_id])
    company = relationship("Company", foreign_keys=[company_id])

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "(file_type = 'image' AND file_size <= 15728640) OR "
            "(file_type IN ('video', 'audio') AND file_size <= 15728640)",
            name="valid_file_size"
        ),
        CheckConstraint(
            "(file_type = 'image' AND mime_type IN ('image/jpeg', 'image/jpg', 'image/png', 'image/webp')) OR "
            "(file_type = 'video' AND mime_type = 'video/mp4') OR "
            "(file_type = 'audio' AND mime_type = 'audio/mpeg')",
            name="check_mime_type"
        ),
    )

class FollowUpSequence(Base):
    __tablename__ = "follow_up_sequences"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String, nullable=False)  # ou Integer, conforme sua tabela 'clients'
    company_id = Column(BigInteger, ForeignKey("companies.id"), nullable=False)
    name = Column(String)
    description = Column(Text)

    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now())

    # relationships
    steps = relationship("FollowUpStep", back_populates="sequence", cascade="all, delete-orphan")

class FollowUpStep(Base):
    __tablename__ = "follow_up_steps"

    id = Column(Integer, primary_key=True, index=True)
    follow_up_sequence_id = Column(Integer, ForeignKey("follow_up_sequences.id", ondelete="CASCADE"), nullable=False)
    step_number = Column(Integer, nullable=False)
    send_after = Column(Integer, nullable=False)
    send_after_unit = Column(String(20), nullable=False)

    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now())

    # relationships
    sequence = relationship("FollowUpSequence", back_populates="steps")
    messages = relationship("FollowUpMessage", back_populates="step", cascade="all, delete-orphan")

class FollowUpMessage(Base):
    __tablename__ = "follow_up_messages"

    id = Column(Integer, primary_key=True, index=True)
    follow_up_step_id = Column(Integer, ForeignKey("follow_up_steps.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(20), nullable=False)    # "text", "image", "audio", "video"
    content = Column(Text, nullable=False)

    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now())

    step = relationship("FollowUpStep", back_populates="messages")

class FollowUpScheduleConfig(Base):
    __tablename__ = "follow_up_schedule_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(
        BigInteger,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False
    )
    follow_up_sequence_id = Column(
        Integer,
        ForeignKey("follow_up_sequences.id", ondelete="CASCADE"),
        nullable=False
    )
    schedule_data = Column(JSON, nullable=False, default={})

    created_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now()
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    # Relacionamentos (opcionais)
    # Dependendo da sua necessidade, você pode criar relacionamentos:
    # company = relationship("Company", back_populates="...")
    # sequence = relationship("FollowUpSequence", back_populates="...")

# --------------------------------------------------------------
# Tabelas de CONFIRMAÇÃO DE CONSULTA
# --------------------------------------------------------------

class ConfirmationSequence(Base):
    __tablename__ = "confirmation_sequences"
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String, nullable=False)
    # Retirar ondelete="CASCADE" se não quiser apagar a sequence ao remover a Company
    company_id = Column(BigInteger, ForeignKey("companies.id"), nullable=False)
    name = Column(String)
    description = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now())

    # Se você não quiser que Steps sejam todos removidos ao apagar a Sequence, remova "delete-orphan"
    steps = relationship("ConfirmationStep", back_populates="sequence")
    # Se quiser manter a exclusão, basta deixar cascade="all, delete-orphan".


class ConfirmationStep(Base):
    __tablename__ = "confirmation_steps"
    id = Column(Integer, primary_key=True, index=True)
    # Retire ondelete="CASCADE" se não quiser remover Steps ao apagar a Sequence
    confirmation_sequence_id = Column(Integer, ForeignKey("confirmation_sequences.id"), nullable=False)
    step_number = Column(Integer, nullable=False)
    send_after = Column(Integer, nullable=False)
    send_after_unit = Column(String(20), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now())

    sequence = relationship("ConfirmationSequence", back_populates="steps")
    messages = relationship("ConfirmationMessage", back_populates="step")
    # Se quiser manter a deleção de messages quando remover Step, use cascade="all, delete-orphan".


class ConfirmationMessage(Base):
    __tablename__ = "confirmation_messages"
    id = Column(Integer, primary_key=True, index=True)
    # Retire ondelete="CASCADE" se não quiser remover msgs ao apagar Step
    confirmation_step_id = Column(Integer, ForeignKey("confirmation_steps.id"), nullable=False)
    type = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now())

    step = relationship("ConfirmationStep", back_populates="messages")


class ConfirmationScheduleConfig(Base):
    __tablename__ = "confirmation_schedule_configs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id"), nullable=False)
    confirmation_sequence_id = Column(Integer, ForeignKey("confirmation_sequences.id"), nullable=False)
    schedule_data = Column(JSON, nullable=False, default={})
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

class Comparecimento(Base):
    __tablename__ = "comparecimentos"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(BigInteger, ForeignKey("clients.id"), nullable=False)
    lead_id = Column(BigInteger, ForeignKey("leads.id"), nullable=False)
    agendamento_id = Column(BigInteger, ForeignKey("agendamentos.id"), nullable=False)
    compareceu_em = Column(DateTime(timezone=True), nullable=False)

    nome = Column(String(255))
    phone = Column(String(20))
    midia = Column(Text)
    interesse = Column(Text)
    tratamento_orcado = Column(Text)
    valor_orcamento = Column(Numeric(10,2))
    company_id = Column(BigInteger, ForeignKey("companies.id"))

    # relationships
    client = relationship("Client", foreign_keys=[client_id])
    lead = relationship("Lead", foreign_keys=[lead_id])
    agendamento = relationship("Agendamento", foreign_keys=[agendamento_id])
    company = relationship("Company", foreign_keys=[company_id])

class Venda(Base):
    __tablename__ = "vendas"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(BigInteger, ForeignKey("clients.id"), nullable=False)
    lead_id = Column(BigInteger, ForeignKey("leads.id"), nullable=False)
    comparecimento_id = Column(BigInteger, ForeignKey("comparecimentos.id"), nullable=False)
    venda_data = Column(DateTime(timezone=True), nullable=False)

    nome = Column(String(255))
    phone = Column(String(20))
    tratamento_fechado = Column(Text)
    valor_faturado = Column(Numeric(10,2))
    valor_pago = Column(Numeric(10,2))
    company_id = Column(BigInteger, ForeignKey("companies.id"))

    # relationships
    client = relationship("Client", foreign_keys=[client_id])
    lead = relationship("Lead", foreign_keys=[lead_id])
    comparecimento = relationship("Comparecimento", foreign_keys=[comparecimento_id])
    company = relationship("Company", foreign_keys=[company_id])

class NoShowFollowUpSequence(Base):
    __tablename__ = "noshow_follow_up_sequences"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    name = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)

    created_at = Column(TIMESTAMP(timezone=False), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=False), server_default=func.now(), onupdate=func.now())

    # Relacionamentos
    steps = relationship("NoShowFollowUpStep", back_populates="sequence", cascade="all, delete-orphan")
    # Exemplo de relacionamento com schedule config (se quiser mapear do lado de Sequence):
    # schedule_configs = relationship("NoShowFollowUpScheduleConfig", back_populates="sequence")

class NoShowFollowUpStep(Base):
    __tablename__ = "noshow_follow_up_steps"

    id = Column(Integer, primary_key=True, index=True)
    noshow_follow_up_sequence_id = Column(
        Integer,
        ForeignKey("noshow_follow_up_sequences.id", ondelete="CASCADE"),
        nullable=False
    )
    step_number = Column(Integer, nullable=False)
    send_after = Column(Integer, nullable=False)
    send_after_unit = Column(String(20), nullable=False)  # "minutes", "hours", "days"

    created_at = Column(TIMESTAMP(timezone=False), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=False), server_default=func.now(), onupdate=func.now())

    # Relacionamentos
    sequence = relationship("NoShowFollowUpSequence", back_populates="steps")
    messages = relationship("NoShowFollowUpMessage", back_populates="step", cascade="all, delete-orphan")

class NoShowFollowUpMessage(Base):
    __tablename__ = "noshow_follow_up_messages"

    id = Column(Integer, primary_key=True, index=True)
    noshow_follow_up_step_id = Column(
        Integer,
        ForeignKey("noshow_follow_up_steps.id", ondelete="CASCADE"),
        nullable=False
    )
    type = Column(String(20), nullable=False)    # "text", "image", "audio", "video", etc.
    content = Column(Text, nullable=False)

    created_at = Column(TIMESTAMP(timezone=False), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=False), server_default=func.now(), onupdate=func.now())

    # Relacionamentos
    step = relationship("NoShowFollowUpStep", back_populates="messages")

class NoShowFollowUpScheduleConfig(Base):
    __tablename__ = "noshow_follow_up_schedule_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(
        BigInteger,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False
    )
    noshow_follow_up_sequence_id = Column(
        Integer,
        ForeignKey("noshow_follow_up_sequences.id", ondelete="CASCADE"),
        nullable=False
    )
    schedule_data = Column(JSON, nullable=False, default={})

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relacionamentos (opcionais)
    # sequence = relationship("NoShowFollowUpSequence", back_populates="schedule_configs")

class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    code = Column(String(20), nullable=False)  # Código gerado a partir do nome da equipe
    description = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relacionamentos
    company = relationship("Company")
    users = relationship("User", back_populates="team")
    permissions = relationship("TeamPermission", back_populates="team", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('company_id', 'code', name='uq_teams_company_code'),
    )

class TeamPermission(Base):
    __tablename__ = "team_permissions"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    resource = Column(String(50), nullable=False)
    permission = Column(String(20), nullable=False)
    filter_criteria = Column(JSON)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relacionamentos
    team = relationship("Team", back_populates="permissions")

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, server_default='staff')  # 'admin', 'manager', 'staff'
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default='true')
    auth_token_version = Column(Integer, nullable=False, server_default="0")
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relacionamentos
    client = relationship("Client", back_populates="users")
    company = relationship("Company", back_populates="users")
    team = relationship("Team", back_populates="users")

    __table_args__ = (
        Index('idx_users_client_company', 'client_id', 'company_id'),
        Index('idx_users_email', 'email'),
        Index('idx_users_team', 'team_id'),
    )

class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    token = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)

    # Relacionamentos
    user = relationship(
        "User",
        backref=backref("sessions", passive_deletes=True)
    )
    client = relationship("Client", overlaps="user_sessions")

    __table_args__ = (
        Index('idx_user_sessions_user', 'user_id'),
        Index('idx_user_sessions_token', 'token'),
    )

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    email = Column(String(255), nullable=False)
    token_hash = Column(String(64), unique=True, nullable=False)
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    used_at = Column(TIMESTAMP(timezone=True), nullable=True)
    requested_ip = Column(String(64), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("client_id IS NOT NULL OR user_id IS NOT NULL", name="ck_password_reset_tokens_owner"),
        Index('idx_password_reset_tokens_email', 'email'),
        Index('idx_password_reset_tokens_client', 'client_id'),
        Index('idx_password_reset_tokens_user', 'user_id'),
        Index('idx_password_reset_tokens_expires', 'expires_at'),
        Index('idx_password_reset_tokens_active', 'token_hash', 'used_at'),
    )


class NoShowEvent(Base):
    __tablename__ = "noshow_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    lead_id = Column(BigInteger, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    agendamento_id = Column(BigInteger, ForeignKey("agendamentos.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        UniqueConstraint("agendamento_id", name="uq_noshow_agendamento"),
    )

    # Colunas adicionadas
    nome = Column(String(255), nullable=True)
    phone = Column(String(20), nullable=True)
    data_agendada = Column(TIMESTAMP(timezone=True), nullable=True)

    # Data/hora em que foi marcado
    marcado_em = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    # Campo de observação ou comentário
    observacao = Column(Text, nullable=True)

    # Relacionamentos (opcionais, se quiser acessar via ORM)
    client = relationship("Client", foreign_keys=[client_id])
    company = relationship("Company", foreign_keys=[company_id])
    lead = relationship("Lead", foreign_keys=[lead_id])
    agendamento = relationship("Agendamento", foreign_keys=[agendamento_id])

class AdCampaignMedia(Base):
    __tablename__ = "ad_campaign_media"

    id = Column(Integer, primary_key=True)
    company_id = Column(BigInteger, ForeignKey("companies.id"), nullable=False)
    #lead_id = Column(BigInteger, ForeignKey("leads.id"))  # <-- REMOVER ISTO!
    source_id = Column(String(255), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_path = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

class AIResponseWindows(Base):
    __tablename__ = "ai_response_windows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    timezone = Column(String(100), nullable=False, server_default="America/Sao_Paulo")
    time_windows = Column(JSON, nullable=False, server_default='{}')

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relacionamento (opcional)
    company = relationship("Company", foreign_keys=[company_id])

class PeriodTimeConfig(BaseModel):
    enabled: bool
    start: str  # "08:00"
    end: str    # "12:00"

class DayTimeConfig(BaseModel):
    morning: PeriodTimeConfig
    afternoon: PeriodTimeConfig
    night: PeriodTimeConfig
    dawn: PeriodTimeConfig

class AIResponseWindowsCreate(BaseModel):
    company_id: int
    timezone: str
    # Ex.: { "segunda": DayTimeConfig(...), "terca": DayTimeConfig(...), ... }
    time_windows: Dict[str, DayTimeConfig]

class AIResponseWindowsUpdate(BaseModel):
    timezone: str = None
    time_windows: Dict[str, DayTimeConfig] = None

class AdCampaignInvestmentPayload(BaseModel):
    company_id: int
    source_id: str
    investment: float
    reference_month: date  # 'YYYY-MM-DD'

class ConversationState(Base):
    __tablename__ = 'conversation_state'

    phone = Column(String, primary_key=True)
    company_id = Column(BigInteger, primary_key=True)
    state_data = Column(JSON, nullable=False)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

class ClinicorpDetails(Base):
    __tablename__ = "clinicorp_details"

    id = Column(Integer, primary_key=True, index=True)
    calendar_integration_id = Column(
        Integer,
        ForeignKey("calendar_integrations.id", ondelete='CASCADE'), # Adicionado ondelete
        nullable=False,
        # unique=True # Adicionar se for estritamente 1-para-1
    )

    business_id = Column(BigInteger, nullable=True)
    dentist_person_id = Column(BigInteger, nullable=True)

    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relacionamento com a tabela calendar_integrations (se quiser, para navegar)
    calendar_integration = relationship("CalendarIntegration", back_populates="clinicorp_details")

# ================================================================
# MODELS PARA FOLLOW-UP PÓS-CONSULTA
# ================================================================

class PosConsultaSequence(Base):
    __tablename__ = "pos_consulta_sequences"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('company_id', name='uq_pos_consulta_sequence_company'),
    )

    # Relacionamentos
    company = relationship("Company")
    steps = relationship("PosConsultaStep", back_populates="sequence", cascade="all, delete-orphan")
    schedule_configs = relationship("PosConsultaScheduleConfig", back_populates="sequence", cascade="all, delete-orphan")

class PosConsultaStep(Base):
    __tablename__ = "pos_consulta_steps"

    id = Column(Integer, primary_key=True, index=True)
    pos_consulta_sequence_id = Column(Integer, ForeignKey("pos_consulta_sequences.id", ondelete="CASCADE"), nullable=False)
    step_number = Column(Integer, nullable=False)
    send_after = Column(Integer, nullable=False)
    send_after_unit = Column(String(20), nullable=False)  # 'minutes', 'hours', 'days'
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint('pos_consulta_sequence_id', 'step_number', name='uq_pos_consulta_step_number'),
        CheckConstraint(send_after_unit.in_(['minutes', 'hours', 'days']), name='chk_pos_consulta_step_unit'),
    )

    # Relacionamentos
    sequence = relationship("PosConsultaSequence", back_populates="steps")
    messages = relationship("PosConsultaMessage", back_populates="step", cascade="all, delete-orphan")

# ================================================================
# MODELS PARA KANBAN CRM
# ================================================================

class Pipeline(Base):
    __tablename__ = "pipelines"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)  # ex: "Funil de Vendas", "Recepção"
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relacionamentos
    company = relationship("Company", back_populates="pipelines")
    creator = relationship("User", foreign_keys=[created_by_user_id])
    stages = relationship("PipelineStage", back_populates="pipeline", cascade="all, delete-orphan", order_by="PipelineStage.order")

    __table_args__ = (Index("idx_company_pipeline", "company_id"),)

class PipelineStage(Base):
    __tablename__ = "pipeline_stages"

    id = Column(Integer, primary_key=True, index=True)
    pipeline_id = Column(Integer, ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)  # ex: "Qualificado", "Proposta", "Agendado"
    description = Column(Text, nullable=True)
    color = Column(String(7), default="#3B82F6")  # Hex color para UI
    order_index = Column(Integer, nullable=False)  # Ordem original (mantida para compatibilidade)
    order = Column(Integer, nullable=False)  # Ordem no Kanban (mudado de order_index)
    is_first_stage = Column(Boolean, default=False)  # Apenas "Novo Lead"
    is_converted_stage = Column(Boolean, default=False)  # Usuario define
    is_lost_stage = Column(Boolean, default=False)  # Usuario define
    auto_advance_days = Column(Integer, nullable=True)  # Dias para avanço automático (opcional)
    percentage_base_stage_id = Column(Integer, ForeignKey("pipeline_stages.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relacionamentos
    pipeline = relationship("Pipeline", back_populates="stages")
    leads = relationship("Lead", back_populates="current_stage", foreign_keys="Lead.current_stage_id")

    __table_args__ = (Index("idx_pipeline_stage", "pipeline_id", "order"),)

    # Nova coluna para vincular sequência de follow-up ao estágio
    follow_up_sequence_id = Column(Integer, ForeignKey("follow_up_sequences.id", ondelete="SET NULL"), nullable=True)

    # Relacionamento
    follow_up_sequence = relationship("FollowUpSequence", foreign_keys=[follow_up_sequence_id])
    percentage_base_stage = relationship("PipelineStage", remote_side=[id], foreign_keys=[percentage_base_stage_id])

class LeadPipelineHistory(Base):
    __tablename__ = "lead_pipeline_history"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    from_stage_id = Column(Integer, ForeignKey("pipeline_stages.id", ondelete="SET NULL"), nullable=True)
    to_stage_id = Column(Integer, ForeignKey("pipeline_stages.id", ondelete="CASCADE"), nullable=False)
    moved_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    moved_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    notes = Column(Text, nullable=True)
    time_in_previous_stage = Column(Integer, nullable=True)  # Tempo em segundos na etapa anterior

    # Relacionamentos
    lead = relationship("Lead", back_populates="pipeline_history")
    company = relationship("Company", foreign_keys=[company_id])
    from_stage = relationship("PipelineStage", foreign_keys=[from_stage_id])
    to_stage = relationship("PipelineStage", foreign_keys=[to_stage_id])
    moved_by = relationship("User", foreign_keys=[moved_by_user_id])

    __table_args__ = (Index("idx_lead_history", "lead_id", "moved_at"),)

class PosConsultaMessage(Base):
    __tablename__ = "pos_consulta_messages"

    id = Column(Integer, primary_key=True, index=True)
    pos_consulta_step_id = Column(Integer, ForeignKey("pos_consulta_steps.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(20), nullable=False)  # 'text', 'image', 'audio', 'video'
    content = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(type.in_(['text', 'image', 'audio', 'video']), name='chk_pos_consulta_message_type'),
    )

    # Relacionamentos
    step = relationship("PosConsultaStep", back_populates="messages")

class PosConsultaExecution(Base):
    __tablename__ = "pos_consulta_executions"

    id = Column(Integer, primary_key=True, index=True)
    comparecimento_id = Column(BigInteger, ForeignKey("comparecimentos.id", ondelete="CASCADE"), nullable=False)
    lead_id = Column(BigInteger, nullable=False)
    company_id = Column(BigInteger, nullable=False)
    pos_consulta_sequence_id = Column(Integer, nullable=False)
    pos_consulta_step_id = Column(Integer, nullable=True)
    step_number = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False)  # 'SCHEDULED', 'PROCESSING', 'SUCCESS', 'FAILED', 'CANCELED'
    scheduled_for = Column(TIMESTAMP(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('comparecimento_id', 'pos_consulta_sequence_id', 'pos_consulta_step_id',
                        name='uq_pos_consulta_execution'),
        CheckConstraint(status.in_(['SCHEDULED', 'PROCESSING', 'SUCCESS', 'FAILED', 'CANCELED']),
                       name='chk_pos_consulta_execution_status'),
        Index('idx_pos_consulta_exec_status', 'status', 'scheduled_for'),
        Index('idx_pos_consulta_exec_lead', 'lead_id'),
        Index('idx_pos_consulta_exec_company', 'company_id'),
    )

    # Relacionamentos
    comparecimento = relationship("Comparecimento")

class PosConsultaScheduleConfig(Base):
    __tablename__ = "pos_consulta_schedule_configs"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    pos_consulta_sequence_id = Column(Integer, ForeignKey("pos_consulta_sequences.id", ondelete="CASCADE"), nullable=False)
    schedule_data = Column(JSON, nullable=False, default={})
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('company_id', 'pos_consulta_sequence_id', name='uq_pos_consulta_schedule_config'),
    )

    # Relacionamentos
    company = relationship("Company")
    sequence = relationship("PosConsultaSequence", back_populates="schedule_configs")


# Contact Tasks Models
class ContactTask(Base):
    __tablename__ = "contact_tasks"

    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(BigInteger, ForeignKey("contacts.id"), nullable=False)
    company_id = Column(BigInteger, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Task type and details
    task_type = Column(String(50), nullable=False)  # 'message', 'call', 'email', 'custom', 'scheduled_message'
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Campos para mensagem agendada (quando task_type = 'scheduled_message')
    message_content = Column(Text, nullable=True)  # Conteúdo da mensagem
    message_type = Column(String(20), nullable=True)  # 'text', 'image', 'audio', 'video'
    message_file_path = Column(Text, nullable=True)  # Path do arquivo de mídia (se aplicável)

    # Scheduling
    scheduled_for = Column(TIMESTAMP(timezone=True), nullable=False)
    reminder_minutes = Column(Integer, nullable=False, default=15)

    # Status and execution
    status = Column(String(20), nullable=False, default='pending')  # pending, in_progress, completed, canceled
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    completed_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Flow integration
    flow_type = Column(String(50), nullable=True)
    flow_execution_id = Column(Integer, nullable=True)

    # Priority and tags
    priority = Column(String(10), nullable=False, default='medium')  # low, medium, high, urgent
    tags = Column(ARRAY(Text), nullable=True)

    # Metadata
    task_metadata = Column(JSON, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    contact = relationship("Contact", backref="tasks")
    creator = relationship("User", foreign_keys=[created_by], backref="created_tasks")
    assignee = relationship("User", foreign_keys=[assigned_to], backref="assigned_tasks")
    completer = relationship("User", foreign_keys=[completed_by], backref="completed_tasks")
    comments = relationship("ContactTaskComment", back_populates="task", cascade="all, delete-orphan")


class ContactTaskComment(Base):
    __tablename__ = "contact_task_comments"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(BigInteger, ForeignKey("contact_tasks.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    comment = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    task = relationship("ContactTask", back_populates="comments")
    user = relationship("User", backref="task_comments")


class ContactNote(Base):
    __tablename__ = "contact_notes"

    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(BigInteger, ForeignKey("contacts.id"), nullable=False)
    company_id = Column(BigInteger, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    content = Column(Text, nullable=False)
    note_metadata = Column(JSON, nullable=True)  # Para armazenar info do Client quando created_by é NULL
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    contact = relationship("Contact")
    creator = relationship("User", backref="contact_notes")


# Scheduled Message Executions Model
class ScheduledMessageExecution(Base):
    __tablename__ = "scheduled_message_executions"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(BigInteger, ForeignKey("contact_tasks.id", ondelete="CASCADE"), nullable=False)
    contact_id = Column(BigInteger, nullable=False)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    # Informações da mensagem
    message_type = Column(String(20), nullable=False)  # 'text', 'image', 'audio', 'video'
    message_content = Column(Text, nullable=False)
    message_file_path = Column(Text, nullable=True)

    # Controle de execução
    status = Column(String(20), nullable=False, default='SCHEDULED')  # SCHEDULED, PROCESSING, SUCCESS, FAILED, CANCELED
    scheduled_for = Column(TIMESTAMP(timezone=True), nullable=False)
    executed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)

    # Auditoria
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relacionamentos
    task = relationship("ContactTask", backref="scheduled_executions")
    company = relationship("Company")

class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contact_id = Column(BigInteger, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    # Dados do cliente
    nome = Column(String(255), nullable=False)
    telefone = Column(String(20), nullable=False)
    email = Column(String(255), nullable=True)
    data_nascimento = Column(DateTime, nullable=True)
    cpf = Column(String(14), nullable=True)
    # Status e categoria
    status = Column(String(20), nullable=False, default='ativo')  # ativo, inativo, bloqueado
    categoria = Column(String(30), nullable=False, default='cliente')  # cliente, lead_qualificado, prospect, ex_cliente

    # Dados de relacionamento
    primeira_consulta = Column(DateTime, nullable=True)
    ultima_consulta = Column(DateTime, nullable=True)
    total_consultas = Column(Integer, default=0)
    valor_total_tratamentos = Column(Numeric(12,2), default=0)

    # Controle de criação/conversão
    convertido_de_lead_id = Column(BigInteger, ForeignKey("leads.id", ondelete="SET NULL"), nullable=True)
    convertido_em = Column(TIMESTAMP(timezone=True), server_default=func.now())
    criado_por = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Metadados
    observacoes = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)
    dados_adicionais = Column(JSON, default={})

    # Auditoria
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relacionamentos
    contact = relationship("Contact", foreign_keys=[contact_id])
    company = relationship("Company", foreign_keys=[company_id])
    lead_origem = relationship("Lead", foreign_keys=[convertido_de_lead_id])
    usuario_criador = relationship("User", foreign_keys=[criado_por])

    # Constraints
    __table_args__ = (
        UniqueConstraint('contact_id', 'company_id', name='uq_cliente_contact_company'),
        UniqueConstraint('telefone', 'company_id', name='uq_cliente_telefone_company'),
        CheckConstraint(status.in_(['ativo', 'inativo', 'bloqueado']), name='chk_cliente_status'),
        CheckConstraint(categoria.in_(['cliente', 'lead_qualificado', 'prospect', 'ex_cliente']), name='chk_cliente_categoria'),
        Index('idx_clientes_company_id', 'company_id'),
        Index('idx_clientes_contact_id', 'contact_id'),
        Index('idx_clientes_telefone', 'telefone'),
        Index('idx_clientes_status', 'status'),
        Index('idx_clientes_categoria', 'categoria'),
        Index('idx_clientes_primeira_consulta', 'primeira_consulta'),
        Index('idx_clientes_ultima_consulta', 'ultima_consulta'),
    )

# ================================================================
# MODELS PARA CAMPANHAS DE NUTRIÇÃO
# ================================================================

class NutritionCampaignSequence(Base):
    __tablename__ = "nutrition_campaign_sequences"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    active = Column(Boolean, default=True)

    # Critérios de targeting para contatos
    target_contact_status = Column(JSON, nullable=True)  # ['ativo', 'inativo']
    target_contact_categories = Column(JSON, nullable=True)  # ['lead_qualificado', 'prospect']
    target_contact_tags = Column(JSON, nullable=True)  # tags específicas

    # Configurações de timing aleatório
    message_delay_min = Column(Integer, default=30, nullable=False)  # min 30s entre mensagens do mesmo step
    message_delay_max = Column(Integer, default=120, nullable=False)  # max 120s entre mensagens do mesmo step

    # Delay entre contatos (MAIS IMPORTANTE para anti-spam)
    contact_delay_min = Column(Integer, default=5, nullable=False)  # min 5min entre contatos
    contact_delay_max = Column(Integer, default=30, nullable=False)  # max 30min entre contatos
    contact_delay_unit = Column(String(20), default='minutes', nullable=False)  # 'minutes', 'hours', 'days'

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('company_id', 'name', name='uq_nutrition_sequence_company_name'),
        CheckConstraint('message_delay_min > 0 AND message_delay_max >= message_delay_min',
                       name='chk_nutrition_message_delays'),
        CheckConstraint('contact_delay_min > 0 AND contact_delay_max >= contact_delay_min',
                       name='chk_nutrition_contact_delays'),
        CheckConstraint(contact_delay_unit.in_(['minutes', 'hours', 'days']),
                       name='chk_nutrition_contact_delay_unit'),
    )

    # Relacionamentos
    company = relationship("Company")
    steps = relationship("NutritionCampaignStep", back_populates="sequence", cascade="all, delete-orphan")
    schedule_configs = relationship("NutritionCampaignScheduleConfig", back_populates="sequence", cascade="all, delete-orphan")

class NutritionCampaignStep(Base):
    __tablename__ = "nutrition_campaign_steps"

    id = Column(Integer, primary_key=True, index=True)
    nutrition_campaign_sequence_id = Column(Integer, ForeignKey("nutrition_campaign_sequences.id", ondelete="CASCADE"), nullable=False)
    step_number = Column(Integer, nullable=False)
    send_after = Column(Integer, nullable=False)
    send_after_unit = Column(String(20), nullable=False)  # 'minutes', 'hours', 'days'

    # Timing aleatório para o step (range em segundos para somar ao send_after)
    random_delay_min = Column(Integer, default=0, nullable=False)  # delay mínimo adicional
    random_delay_max = Column(Integer, default=3600, nullable=False)  # delay máximo adicional (1h)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('nutrition_campaign_sequence_id', 'step_number', name='uq_nutrition_step_number'),
        CheckConstraint(send_after_unit.in_(['minutes', 'hours', 'days']), name='chk_nutrition_step_unit'),
        CheckConstraint('random_delay_min >= 0 AND random_delay_max >= random_delay_min',
                       name='chk_nutrition_random_delays'),
    )

    # Relacionamentos
    sequence = relationship("NutritionCampaignSequence", back_populates="steps")
    messages = relationship("NutritionCampaignMessage", back_populates="step", cascade="all, delete-orphan")

class NutritionCampaignMessage(Base):
    __tablename__ = "nutrition_campaign_messages"

    id = Column(Integer, primary_key=True, index=True)
    nutrition_campaign_step_id = Column(Integer, ForeignKey("nutrition_campaign_steps.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(20), nullable=False)  # 'text', 'image', 'audio', 'video', 'nps'
    content = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(type.in_(['text', 'image', 'audio', 'video', 'nps']), name='chk_nutrition_message_type'),
    )

    # Relacionamentos
    step = relationship("NutritionCampaignStep", back_populates="messages")

class NutritionCampaignExecution(Base):
    __tablename__ = "nutrition_campaign_executions"

    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(BigInteger, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(BigInteger, nullable=False)
    nutrition_campaign_sequence_id = Column(Integer, nullable=False)
    nutrition_campaign_step_id = Column(Integer, nullable=True)
    step_number = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False)  # 'SCHEDULED', 'PROCESSING', 'SUCCESS', 'FAILED', 'CANCELED'
    scheduled_for = Column(TIMESTAMP(timezone=True), nullable=True)
    executed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)

    # Metadados da execução
    random_delay_applied = Column(Integer, nullable=True)  # delay aleatório aplicado (segundos)
    targeting_criteria_matched = Column(JSON, nullable=True)  # critérios que levaram ao disparo

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('contact_id', 'nutrition_campaign_sequence_id', 'nutrition_campaign_step_id',
                        name='uq_nutrition_execution'),
        CheckConstraint(status.in_(['SCHEDULED', 'PROCESSING', 'SUCCESS', 'FAILED', 'CANCELED']),
                       name='chk_nutrition_execution_status'),
        Index('idx_nutrition_exec_status', 'status', 'scheduled_for'),
        Index('idx_nutrition_exec_contact', 'contact_id'),
        Index('idx_nutrition_exec_company', 'company_id'),
    )

    # Relacionamentos
    contact = relationship("Contact")

class NutritionCampaignScheduleConfig(Base):
    __tablename__ = "nutrition_campaign_schedule_configs"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    nutrition_campaign_sequence_id = Column(Integer, ForeignKey("nutrition_campaign_sequences.id", ondelete="CASCADE"), nullable=False)
    schedule_data = Column(JSON, nullable=False, default={})
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('company_id', 'nutrition_campaign_sequence_id', name='uq_nutrition_schedule_config'),
    )

    # Relacionamentos
    company = relationship("Company")
    sequence = relationship("NutritionCampaignSequence", back_populates="schedule_configs")


# ================================================================
# REFERRAL CAMPAIGNS - Sistema de Campanhas de Indicação
# ================================================================

class ReferralCampaign(Base):
    __tablename__ = "referral_campaigns"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    # Configurações gerais
    campaign_name = Column(String(255), nullable=False)
    active = Column(Boolean, default=True, nullable=False)

    # CAMPANHA PARA INDICADOR (quem indica)
    referrer_campaign_description = Column(Text, nullable=False)
    referrer_campaign_instructions = Column(Text, nullable=True)

    # CAMPANHA PARA INDICADO (quem foi indicado)
    referee_campaign_description = Column(Text, nullable=False)
    referee_campaign_instructions = Column(Text, nullable=True)

    # Configurações de timing
    delay_minutes = Column(Integer, default=5, nullable=False)
    max_referrals_per_request = Column(Integer, default=5, nullable=False)

    # Configurações para indicados
    contact_referees_immediately = Column(Boolean, default=True, nullable=False)
    referee_delay_minutes = Column(Integer, default=10, nullable=False)

    # Auditoria
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Relacionamentos
    company = relationship("Company", foreign_keys=[company_id])
    creator = relationship("User", foreign_keys=[created_by])

    # Constraints
    __table_args__ = (
        UniqueConstraint('company_id', name='uq_referral_campaign_company'),
        CheckConstraint('delay_minutes >= 1 AND delay_minutes <= 60', name='chk_delay_minutes'),
        CheckConstraint('max_referrals_per_request >= 1 AND max_referrals_per_request <= 10', name='chk_max_referrals'),
        CheckConstraint('referee_delay_minutes >= 1 AND referee_delay_minutes <= 1440', name='chk_referee_delay'),
        Index('idx_referral_campaigns_company', 'company_id'),
        Index('idx_referral_campaigns_active', 'active'),
    )

# ================================================================
# BUSINESS TYPES - Sistema de Tipos de Negócio (Plataforma Universal)
# ================================================================

class BusinessType(Base):
    """
    Define os tipos de negócio suportados pela plataforma.
    Cada tipo possui configurações padrão de funil, dashboard e terminologia.
    """
    __tablename__ = "business_types"

    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    default_config = Column(JSON, server_default="{}", nullable=False)
    icon = Column(String(50), nullable=True)
    enabled = Column(Boolean, server_default="true", nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relacionamentos
    companies = relationship("Company", back_populates="business_type")

    __table_args__ = (
        Index("idx_business_types_code", "code"),
        Index("idx_business_types_enabled", "enabled"),
    )

# ================================================================
# LEAD CUSTOM FIELDS - Sistema de Campos Customizados para Leads
# ================================================================

class LeadCustomField(Base):
    """
    Define campos customizados para leads por empresa.
    Cada empresa pode configurar seus próprios campos para coletar informações específicas dos leads.
    """
    __tablename__ = "lead_custom_fields"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    # Configuração do campo
    field_name = Column(String(100), nullable=False)  # Nome exibido (ex: "CPF", "Data de Nascimento")
    field_key = Column(String(100), nullable=False)   # Chave única (ex: "cpf", "data_nascimento")
    field_type = Column(String(20), nullable=False)   # text, number, email, date, select, textarea

    # Configurações adicionais
    is_required = Column(Boolean, default=False)
    default_value = Column(JSON, nullable=True)      # Valor padrão ou opções para select
    validation_rules = Column(JSON, nullable=True)   # Regras de validação
    display_order = Column(Integer, default=0)       # Ordem de exibição
    is_active = Column(Boolean, default=True)        # Campo está ativo

    # Auditoria
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relacionamentos
    company = relationship("Company", foreign_keys=[company_id])
    custom_values = relationship("LeadCustomValue", back_populates="custom_field", cascade="all, delete-orphan")

    # Constraints
    __table_args__ = (
        UniqueConstraint('company_id', 'field_key', name='uq_lead_custom_field_company_key'),
        CheckConstraint('field_type IN (\'text\', \'number\', \'email\', \'date\', \'select\', \'textarea\')', name='chk_lead_custom_field_type'),
        CheckConstraint('length(trim(field_name)) > 0', name='chk_lead_custom_field_name_not_empty'),
        CheckConstraint('length(trim(field_key)) > 0', name='chk_lead_custom_field_key_not_empty'),
        CheckConstraint('display_order >= 0', name='chk_lead_custom_field_order_positive'),
        Index('idx_lead_custom_field_company', 'company_id'),
        Index('idx_lead_custom_field_company_active', 'company_id', 'is_active'),
        Index('idx_lead_custom_field_company_order', 'company_id', 'display_order'),
    )

    def __repr__(self):
        return f"<LeadCustomField(id={self.id}, company_id={self.company_id}, field_name='{self.field_name}', field_key='{self.field_key}')>"

class LeadCustomValue(Base):
    """
    Armazena valores de campos customizados para cada lead.
    Permite flexibilidade total nos tipos de dados através de JSONB.
    """
    __tablename__ = "lead_custom_values"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    custom_field_id = Column(Integer, ForeignKey("lead_custom_fields.id", ondelete="CASCADE"), nullable=False)

    # Valor do campo (JSON para flexibilidade de tipos)
    value = Column(JSON, nullable=True)

    # Auditoria
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relacionamentos
    lead = relationship("Lead", back_populates="custom_values")
    custom_field = relationship("LeadCustomField", back_populates="custom_values")

    # Constraints
    __table_args__ = (
        UniqueConstraint('lead_id', 'custom_field_id', name='uq_lead_custom_value_lead_field'),
        Index('idx_lead_custom_value_lead', 'lead_id'),
        Index('idx_lead_custom_value_field', 'custom_field_id'),
    )

    def __repr__(self):
        return f"<LeadCustomValue(id={self.id}, lead_id={self.lead_id}, custom_field_id={self.custom_field_id}, value={self.value})>"

    @property
    def field_key(self) -> str:
        """Retorna a chave do campo customizado para fácil acesso"""
        return self.custom_field.field_key if self.custom_field else None

    @property
    def field_name(self) -> str:
        """Retorna o nome do campo customizado para exibição"""
        return self.custom_field.field_name if self.custom_field else None

    @property
    def field_type(self) -> str:
        """Retorna o tipo do campo customizado"""
        return self.custom_field.field_type if self.custom_field else None

class WebhookTrigger(Base):
    __tablename__ = "webhook_triggers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    uuid = Column(String(36), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    method = Column(String(10), default="POST", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relacionamentos
    company = relationship("Company", backref="webhook_triggers")
    events = relationship("WebhookEvent", back_populates="webhook_trigger", passive_deletes=True)

    __table_args__ = (
        Index('idx_webhook_triggers_company', 'company_id'),
    )


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    webhook_trigger_id = Column(BigInteger, ForeignKey("webhook_triggers.id", ondelete="SET NULL"), nullable=True)
    webhook_uuid = Column(String(36), nullable=True)
    webhook_name = Column(String(255), nullable=True)
    method = Column(String(10), nullable=False, default="POST")
    status = Column(String(30), nullable=False, default="received")
    status_code = Column(Integer, nullable=False, default=200)
    source_ip = Column(String(100), nullable=True)
    user_agent = Column(Text, nullable=True)
    content_type = Column(String(255), nullable=True)
    payload_preview = Column(JSONB, nullable=True)
    payload_size = Column(Integer, nullable=True)
    received_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    company = relationship("Company", backref="webhook_events")
    webhook_trigger = relationship("WebhookTrigger", back_populates="events")

    __table_args__ = (
        Index('idx_webhook_events_company_received', 'company_id', 'received_at'),
        Index('idx_webhook_events_trigger_received', 'webhook_trigger_id', 'received_at'),
    )


class Flow(Base):
    __tablename__ = "flows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=False, nullable=False)

    # Armazena estado do React Flow (Lista de Nodes e Edges)
    nodes = Column(JSON, server_default='[]', nullable=False)
    edges = Column(JSON, server_default='[]', nullable=False)
    viewport = Column(JSON, server_default='{"x": 0, "y": 0, "zoom": 1}', nullable=False)

    # Opcional: Link direto com um Webhook Trigger
    trigger_webhook_id = Column(BigInteger, ForeignKey("webhook_triggers.id", ondelete="SET NULL"), nullable=True)

    # Tipo de trigger: 'webhook' (genérico), 'whatsapp' (WAHA messages)
    trigger_type = Column(String(50), default='webhook', nullable=False)
    trigger_config = Column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relacionamentos
    company = relationship("Company", backref="flows")
    trigger_webhook = relationship("WebhookTrigger", backref="flows")
    enrollments = relationship("FlowEnrollment", back_populates="flow", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_flows_company', 'company_id'),
    )


class FlowEnrollment(Base):
    __tablename__ = "flow_enrollments"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    flow_id = Column(Integer, ForeignKey("flows.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    lead_id = Column(BigInteger, ForeignKey("leads.id", ondelete="SET NULL"), nullable=True)
    appointment_id = Column(BigInteger, ForeignKey("agendamentos.id", ondelete="SET NULL"), nullable=True)
    pipeline_id = Column(Integer, ForeignKey("pipelines.id", ondelete="SET NULL"), nullable=True)
    stage_id = Column(Integer, ForeignKey("pipeline_stages.id", ondelete="SET NULL"), nullable=True)
    trigger_type = Column(String(50), nullable=False)
    anchor_at = Column(TIMESTAMP(timezone=True), nullable=True)
    trigger_payload = Column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    status = Column(String(30), server_default='active', nullable=False)
    cancel_reason = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    flow = relationship("Flow", back_populates="enrollments")
    executions = relationship("FlowStepExecution", back_populates="enrollment", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_flow_enrollments_flow_status", "flow_id", "status"),
        Index("idx_flow_enrollments_appointment", "company_id", "appointment_id", "status"),
        Index("idx_flow_enrollments_lead_stage", "company_id", "lead_id", "stage_id", "status"),
    )


class FlowStepExecution(Base):
    __tablename__ = "flow_step_executions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    enrollment_id = Column(BigInteger, ForeignKey("flow_enrollments.id", ondelete="CASCADE"), nullable=False)
    flow_id = Column(Integer, ForeignKey("flows.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(String(255), nullable=False)
    task_id = Column(String(255), nullable=True)
    scheduled_for = Column(TIMESTAMP(timezone=True), nullable=True)
    sent_at = Column(TIMESTAMP(timezone=True), nullable=True)
    status = Column(String(30), server_default='scheduled', nullable=False)
    dedupe_key = Column(String(500), nullable=False, unique=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    enrollment = relationship("FlowEnrollment", back_populates="executions")
    flow = relationship("Flow")

    __table_args__ = (
        Index("idx_flow_step_executions_enrollment", "enrollment_id", "status"),
        Index("idx_flow_step_executions_scheduled", "company_id", "scheduled_for", "status"),
    )


class MediaSource(Base):
    __tablename__ = "media_sources"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company", foreign_keys=[company_id])


# ================================================================
# WHATSAPP MARKETING CAMPAIGNS
# ================================================================

class WhatsAppCampaign(Base):
    """
    Campanhas de marketing via WhatsApp usando WAHA.
    """
    __tablename__ = "whatsapp_campaigns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)

    # Message Content (MVP = text only)
    message_text = Column(Text, nullable=False)

    # Targeting
    target_tags = Column(ARRAY(Integer), nullable=True)  # Array of tag IDs
    excluded_tags = Column(ARRAY(Integer), nullable=True)  # Array of tag IDs to exclude

    # Status & Counters
    status = Column(String(50), default='DRAFT', nullable=False)  # DRAFT, PROCESSING, PAUSED, COMPLETED, CANCELED, FAILED
    processed_contacts = Column(Integer, default=0)
    total_contacts = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)

    # Time Window (horário permitido para envio)
    daily_start_time = Column(Time, nullable=True)  # Ex: 08:00
    daily_end_time = Column(Time, nullable=True)    # Ex: 21:00
    allowed_days = Column(ARRAY(Integer), nullable=True)  # 0=Monday, 6=Sunday

    # Rate Limiting (MINUTOS para evitar bloqueio WhatsApp)
    interval_min = Column(Integer, default=1, nullable=False)   # Mínimo 1 minuto
    interval_max = Column(Integer, default=5, nullable=False)   # Máximo 5 minutos (default)
    # Constraint: 1 <= interval_min <= interval_max <= 240

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Relationships
    company = relationship("Company", foreign_keys=[company_id])
    creator = relationship("User", foreign_keys=[created_by])
    executions = relationship("WhatsAppCampaignExecution", back_populates="campaign", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_whatsapp_campaigns_company', 'company_id'),
        Index('idx_whatsapp_campaigns_status', 'status'),
        CheckConstraint('interval_min >= 1 AND interval_min <= interval_max AND interval_max <= 240',
                       name='chk_whatsapp_campaign_interval'),
    )


class WhatsAppCampaignExecution(Base):
    """
    Registro de execução individual de mensagem em uma campanha de WhatsApp.
    """
    __tablename__ = "whatsapp_campaign_executions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(BigInteger, ForeignKey("whatsapp_campaigns.id", ondelete="CASCADE"), nullable=False)
    contact_id = Column(BigInteger, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False)

    # Status
    status = Column(String(50), default='PENDING', nullable=False)  # PENDING, SCHEDULED, SENT, FAILED, SKIPPED

    # WAHA Message ID (returned from API)
    waha_message_id = Column(String(255), nullable=True)

    # Timing
    scheduled_for = Column(TIMESTAMP(timezone=True), nullable=True)
    sent_at = Column(TIMESTAMP(timezone=True), nullable=True)
    replied_at = Column(TIMESTAMP(timezone=True), nullable=True)  # Quando o contato respondeu

    error_message = Column(Text, nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    campaign = relationship("WhatsAppCampaign", back_populates="executions")
    contact = relationship("Contact")

    __table_args__ = (
        Index('idx_whatsapp_campaign_exec_campaign', 'campaign_id'),
        Index('idx_whatsapp_campaign_exec_contact', 'contact_id'),
        Index('idx_whatsapp_campaign_exec_status', 'status'),
        UniqueConstraint('campaign_id', 'contact_id', name='uq_whatsapp_campaign_contact'),
    )
