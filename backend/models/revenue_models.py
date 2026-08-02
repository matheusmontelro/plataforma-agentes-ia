# backend/models/revenue_models.py
"""
Modelos para Sistema de Gestão de Receita
Inspirado no modelo de dados do ChartMogul

Entidades:
- Plan: Planos de serviço/tratamento
- Contract: Contratos fechados com clientes
- ContractItem: Itens dentro de um contrato
- Invoice: Faturas geradas
- InvoiceLineItem: Itens dentro de uma fatura
- Payment: Pagamentos/transações
"""

from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Boolean, Numeric, Date, DateTime,
    ForeignKey, TIMESTAMP, func, UniqueConstraint, CheckConstraint, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from backend.db import Base


# ================================================================
# PLAN - Planos de Serviço/Tratamento
# ================================================================

class Plan(Base):
    """
    Representa um plano de serviço ou tratamento oferecido pela empresa.
    Similar ao conceito de 'Plan' do ChartMogul.
    """
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    # Identificação
    name = Column(String(255), nullable=False)
    code = Column(String(50), nullable=True)  # Código interno (ex: "ORTO-001")
    description = Column(Text, nullable=True)

    # Preço e cobrança
    price = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="BRL", nullable=False)

    # Intervalo de cobrança: once (único), monthly, quarterly, yearly
    billing_interval = Column(String(20), default="once", nullable=False)
    billing_interval_count = Column(Integer, default=1, nullable=False)  # Ex: 3 para trimestral

    # Período de teste (opcional)
    trial_period_days = Column(Integer, default=0, nullable=False)

    # Recursos associados ao plano. Mantido como lista vazia por padrão para
    # compatibilidade com schemas antigos que exigem NOT NULL em produção.
    features = Column(JSONB, default=list, server_default='[]', nullable=False)

    # Status e categoria
    is_active = Column(Boolean, default=True, nullable=False)
    category = Column(String(50), nullable=True)  # tratamento, procedimento, manutenção

    # Auditoria
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relacionamentos
    company = relationship("Company", foreign_keys=[company_id])
    creator = relationship("User", foreign_keys=[created_by])
    contract_items = relationship("ContractItem", back_populates="plan")
    invoice_line_items = relationship("InvoiceLineItem", back_populates="plan")

    __table_args__ = (
        UniqueConstraint('company_id', 'code', name='uq_plan_company_code'),
        CheckConstraint(
            "billing_interval IN ('once', 'monthly', 'quarterly', 'yearly')",
            name='chk_plan_billing_interval'
        ),
        CheckConstraint('price >= 0', name='chk_plan_price_positive'),
        CheckConstraint('billing_interval_count >= 1', name='chk_plan_interval_count'),
        Index('idx_plans_company', 'company_id'),
        Index('idx_plans_company_active', 'company_id', 'is_active'),
        Index('idx_plans_category', 'category'),
    )


# ================================================================
# CONTRACT - Contratos fechados com clientes
# ================================================================

class Contract(Base):
    """
    Representa um contrato fechado quando o lead move para 'Ganhou'.
    Similar ao conceito de 'Subscription' do ChartMogul, mas adaptado para vendas únicas também.
    """
    __tablename__ = "contracts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    # Vínculos
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="SET NULL"), nullable=True)
    contact_id = Column(BigInteger, ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    customer_id = Column(BigInteger, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    external_id = Column(String(100), nullable=True)  # ID externo (integrações)

    # Status: active, paused, canceled, completed
    status = Column(String(20), default="active", nullable=False)

    # Datas
    start_date = Column(Date, nullable=False, server_default=func.current_date())
    end_date = Column(Date, nullable=True)  # Data de término prevista
    billing_anchor_date = Column(Date, nullable=True)
    next_invoice_date = Column(Date, nullable=True)
    canceled_at = Column(TIMESTAMP(timezone=True), nullable=True)
    cancellation_reason = Column(Text, nullable=True)

    # Valores
    total_value = Column(Numeric(12, 2), nullable=False, default=0)
    total_paid = Column(Numeric(12, 2), nullable=False, default=0)
    currency = Column(String(3), default="BRL", nullable=False)

    # Condições de pagamento
    payment_method = Column(String(50), nullable=True)  # pix, credit_card, boleto, etc
    installments = Column(Integer, default=1, nullable=False)  # Número de parcelas

    # Observações
    notes = Column(Text, nullable=True)
    extra_data = Column(JSONB, server_default='{}', nullable=False)

    # Auditoria
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relacionamentos
    company = relationship("Company", foreign_keys=[company_id])
    lead = relationship("Lead", foreign_keys=[lead_id])
    contact = relationship("Contact", foreign_keys=[contact_id])
    customer = relationship("Customer", foreign_keys=[customer_id])
    creator = relationship("User", foreign_keys=[created_by])
    items = relationship("ContractItem", back_populates="contract", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="contract", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="contract")

    @property
    def remaining_value(self):
        """Valor restante a ser pago"""
        return self.total_value - self.total_paid

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'paused', 'canceled', 'completed')",
            name='chk_contract_status'
        ),
        CheckConstraint('total_value >= 0', name='chk_contract_total_value'),
        CheckConstraint('total_paid >= 0', name='chk_contract_total_paid'),
        CheckConstraint('installments >= 1', name='chk_contract_installments'),
        Index('idx_contracts_company', 'company_id'),
        Index('idx_contracts_company_status', 'company_id', 'status'),
        Index('idx_contracts_lead', 'lead_id'),
        Index('idx_contracts_contact', 'contact_id'),
        Index('idx_contracts_customer', 'customer_id'),
        Index('idx_contracts_next_invoice_date', 'next_invoice_date'),
        Index('idx_contracts_created_at', 'created_at'),
    )


# ================================================================
# CONTRACT_ITEM - Itens do contrato
# ================================================================

class ContractItem(Base):
    """
    Itens/serviços incluídos em um contrato.
    """
    __tablename__ = "contract_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(Integer, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id", ondelete="SET NULL"), nullable=True)

    # Descrição do item
    description = Column(String(500), nullable=False)

    # Valores
    quantity = Column(Integer, default=1, nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)
    discount_percent = Column(Numeric(5, 2), default=0, nullable=False)
    discount_amount = Column(Numeric(12, 2), default=0, nullable=False)
    total_price = Column(Numeric(12, 2), nullable=False)

    # Tipo de cobrança (herdado do plano se houver)
    billing_interval = Column(String(20), default="once", nullable=False)

    # Controle de sessões (para tratamentos com múltiplas sessões)
    sessions_total = Column(Integer, nullable=True)
    sessions_used = Column(Integer, default=0, nullable=True)

    # Auditoria
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relacionamentos
    contract = relationship("Contract", back_populates="items")
    plan = relationship("Plan", back_populates="contract_items")

    __table_args__ = (
        CheckConstraint('quantity >= 1', name='chk_contract_item_quantity'),
        CheckConstraint('unit_price >= 0', name='chk_contract_item_unit_price'),
        CheckConstraint('discount_percent >= 0 AND discount_percent <= 100', name='chk_contract_item_discount_percent'),
        CheckConstraint('discount_amount >= 0', name='chk_contract_item_discount_amount'),
        CheckConstraint('total_price >= 0', name='chk_contract_item_total_price'),
        Index('idx_contract_items_contract', 'contract_id'),
        Index('idx_contract_items_plan', 'plan_id'),
    )


# ================================================================
# INVOICE - Faturas
# ================================================================

class Invoice(Base):
    """
    Faturas geradas para cobrança.
    Similar ao conceito de 'Invoice' do ChartMogul.
    """
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    # Vínculos
    contract_id = Column(Integer, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=True)
    contact_id = Column(BigInteger, ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    customer_id = Column(BigInteger, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)

    # Identificação
    invoice_number = Column(String(50), nullable=False)
    external_id = Column(String(100), nullable=True)  # ID no gateway
    recurrence_key = Column(String(120), nullable=True)

    # Status: draft, open, paid, overdue, void, refunded
    status = Column(String(20), default="draft", nullable=False)

    # Datas
    issue_date = Column(Date, nullable=False, server_default=func.current_date())
    due_date = Column(Date, nullable=True)
    paid_at = Column(TIMESTAMP(timezone=True), nullable=True)

    # Valores
    subtotal = Column(Numeric(12, 2), nullable=False, default=0)
    discount_amount = Column(Numeric(12, 2), nullable=False, default=0)
    tax_amount = Column(Numeric(12, 2), nullable=False, default=0)
    total = Column(Numeric(12, 2), nullable=False, default=0)
    amount_paid = Column(Numeric(12, 2), nullable=False, default=0)
    currency = Column(String(3), default="BRL", nullable=False)

    # Pagamento
    payment_method = Column(String(50), nullable=True)

    # Observações
    notes = Column(Text, nullable=True)
    extra_data = Column(JSONB, server_default='{}', nullable=False)

    # Auditoria
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relacionamentos
    company = relationship("Company", foreign_keys=[company_id])
    contract = relationship("Contract", back_populates="invoices")
    contact = relationship("Contact", foreign_keys=[contact_id])
    customer = relationship("Customer", foreign_keys=[customer_id])
    line_items = relationship("InvoiceLineItem", back_populates="invoice", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="invoice")

    @property
    def amount_due(self):
        """Valor em aberto"""
        return max((self.total or 0) - (self.amount_paid or 0), 0)

    __table_args__ = (
        UniqueConstraint('company_id', 'invoice_number', name='uq_invoice_company_number'),
        UniqueConstraint('company_id', 'contract_id', 'recurrence_key', name='uq_invoice_company_contract_recurrence'),
        CheckConstraint(
            "status IN ('draft', 'open', 'paid', 'overdue', 'void', 'refunded')",
            name='chk_invoice_status'
        ),
        CheckConstraint('subtotal >= 0', name='chk_invoice_subtotal'),
        CheckConstraint('total >= 0', name='chk_invoice_total'),
        CheckConstraint('amount_paid >= 0', name='chk_invoice_amount_paid'),
        Index('idx_invoices_company', 'company_id'),
        Index('idx_invoices_company_status', 'company_id', 'status'),
        Index('idx_invoices_contract', 'contract_id'),
        Index('idx_invoices_customer', 'customer_id'),
        Index('idx_invoices_due_date', 'due_date'),
        Index('idx_invoices_issue_date', 'issue_date'),
        Index('idx_invoices_recurrence_key', 'recurrence_key'),
    )


# ================================================================
# INVOICE_LINE_ITEM - Itens da fatura
# ================================================================

class InvoiceLineItem(Base):
    """
    Itens dentro de uma fatura.
    Similar ao conceito de 'Line Items' do ChartMogul.
    """
    __tablename__ = "invoice_line_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)

    # Vínculos opcionais
    contract_item_id = Column(Integer, ForeignKey("contract_items.id", ondelete="SET NULL"), nullable=True)
    plan_id = Column(Integer, ForeignKey("plans.id", ondelete="SET NULL"), nullable=True)

    # Descrição
    description = Column(String(500), nullable=False)

    # Valores
    quantity = Column(Integer, default=1, nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)
    discount_amount = Column(Numeric(12, 2), default=0, nullable=False)
    total = Column(Numeric(12, 2), nullable=False)

    # Tipo: subscription, one_time, refund
    type = Column(String(20), default="one_time", nullable=False)

    # Período (para recorrentes)
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)

    # Auditoria
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relacionamentos
    invoice = relationship("Invoice", back_populates="line_items")
    contract_item = relationship("ContractItem", foreign_keys=[contract_item_id])
    plan = relationship("Plan", back_populates="invoice_line_items")

    __table_args__ = (
        CheckConstraint('quantity >= 1', name='chk_invoice_line_item_quantity'),
        CheckConstraint('unit_price >= 0', name='chk_invoice_line_item_unit_price'),
        CheckConstraint(
            "type IN ('subscription', 'one_time', 'refund')",
            name='chk_invoice_line_item_type'
        ),
        Index('idx_invoice_line_items_invoice', 'invoice_id'),
    )


# ================================================================
# PAYMENT - Pagamentos/Transações
# ================================================================

class Payment(Base):
    """
    Registro de pagamentos e transações.
    Similar ao conceito de 'Transactions' do ChartMogul.
    """
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    # Vínculos
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True)
    contract_id = Column(Integer, ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True)
    contact_id = Column(BigInteger, ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    customer_id = Column(BigInteger, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)

    # Identificação externa
    external_id = Column(String(100), nullable=True)  # ID no gateway

    # Tipo: payment, refund
    type = Column(String(20), default="payment", nullable=False)

    # Status: pending, succeeded, failed, canceled
    status = Column(String(20), default="pending", nullable=False)

    # Valores
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="BRL", nullable=False)

    # Método de pagamento: pix, credit_card, debit_card, boleto, cash, transfer
    payment_method = Column(String(50), nullable=True)

    # Data do pagamento
    payment_date = Column(TIMESTAMP(timezone=True), nullable=True)

    # Gateway usado
    gateway = Column(String(50), nullable=True)  # provedor externo ou manual
    gateway_response = Column(JSONB, server_default='{}', nullable=False)

    # Comprovante
    receipt_url = Column(Text, nullable=True)

    # Observações
    notes = Column(Text, nullable=True)

    # Auditoria
    processed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relacionamentos
    company = relationship("Company", foreign_keys=[company_id])
    invoice = relationship("Invoice", back_populates="payments")
    contract = relationship("Contract", back_populates="payments")
    contact = relationship("Contact", foreign_keys=[contact_id])
    customer = relationship("Customer", foreign_keys=[customer_id])
    processor = relationship("User", foreign_keys=[processed_by])

    __table_args__ = (
        CheckConstraint("type IN ('payment', 'refund')", name='chk_payment_type'),
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'canceled')",
            name='chk_payment_status'
        ),
        CheckConstraint('amount >= 0', name='chk_payment_amount'),
        Index('idx_payments_company', 'company_id'),
        Index('idx_payments_company_status', 'company_id', 'status'),
        Index('idx_payments_invoice', 'invoice_id'),
        Index('idx_payments_contract', 'contract_id'),
        Index('idx_payments_customer', 'customer_id'),
        Index('idx_payments_date', 'payment_date'),
        Index('idx_payments_created_at', 'created_at'),
    )
