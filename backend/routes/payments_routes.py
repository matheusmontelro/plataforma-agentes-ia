# backend/routes/payments_routes.py
"""
API REST para gestão de Pagamentos/Transações.
CRUD + estorno.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status, Header, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import List, Optional
from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import datetime, date

from backend.db import get_db
from backend.auth import verify_client_or_bearer_api_key
from backend.models import Client, Customer
from backend.models.revenue_models import Payment, Invoice, Contract
from backend.services.customer_revenue_service import is_recurring_contract

logger = logging.getLogger("agentive.payments")

router = APIRouter(
    prefix="/clients/{client_id}/companies/{company_id}/payments",
    tags=["Payments - Pagamentos"]
)


# -----------------------------------------------------------------------------
# Autenticação via API Key
# -----------------------------------------------------------------------------
async def verify_api_key(
    api_key: str = Header(..., alias="X-API-Key"),
    client_id: int = None,
    db: Session = Depends(get_db)
):
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key não fornecida"
        )

    client = db.query(Client).filter(
        Client.id == client_id,
        Client.api_key == api_key
    ).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key inválida"
        )

    return client


# -----------------------------------------------------------------------------
# Schemas Pydantic
# -----------------------------------------------------------------------------

class PaymentCreate(BaseModel):
    """Schema para criar pagamento."""
    invoice_id: Optional[int] = None
    contract_id: Optional[int] = None
    contact_id: Optional[int] = None
    customer_id: Optional[int] = None
    amount: Decimal = Field(..., gt=0)
    payment_method: str = Field(..., description="pix, credit_card, debit_card, boleto, cash, transfer")
    payment_date: Optional[datetime] = None
    notes: Optional[str] = None
    external_id: Optional[str] = None
    gateway: Optional[str] = Field(default="manual")
    receipt_url: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "contract_id": 123,
                "amount": 500.00,
                "payment_method": "pix",
                "notes": "Pagamento parcela 1/12"
            }
        }


class PaymentResponse(BaseModel):
    """Schema de resposta de pagamento."""
    id: int
    company_id: int
    invoice_id: Optional[int]
    contract_id: Optional[int]
    contact_id: Optional[int]
    customer_id: Optional[int]
    external_id: Optional[str]
    type: str
    status: str
    amount: Decimal
    currency: str
    payment_method: Optional[str]
    payment_date: Optional[datetime]
    gateway: Optional[str]
    receipt_url: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RefundRequest(BaseModel):
    """Schema para estorno."""
    amount: Optional[Decimal] = Field(None, gt=0, description="Valor do estorno (parcial ou total)")
    reason: Optional[str] = None


# -----------------------------------------------------------------------------
# Rotas CRUD
# -----------------------------------------------------------------------------

@router.get("/", response_model=List[PaymentResponse])
async def listar_pagamentos(
    client_id: int,
    company_id: int,
    status_filter: Optional[str] = Query(None, alias="status", description="Filtrar por status"),
    type_filter: Optional[str] = Query(None, alias="type", description="payment ou refund"),
    contract_id: Optional[int] = Query(None, description="Filtrar por contrato"),
    invoice_id: Optional[int] = Query(None, description="Filtrar por fatura"),
    customer_id: Optional[int] = Query(None, description="Filtrar por cliente"),
    payment_method: Optional[str] = Query(None, description="Filtrar por método"),
    date_from: Optional[date] = Query(None, description="Data desde"),
    date_to: Optional[date] = Query(None, description="Data até"),
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """Lista todos os pagamentos de uma empresa."""
    logger.info(f"[listar_pagamentos] company_id={company_id}")

    try:
        query = db.query(Payment).filter(Payment.company_id == company_id)

        if status_filter:
            query = query.filter(Payment.status == status_filter)
        if type_filter:
            query = query.filter(Payment.type == type_filter)
        if contract_id:
            query = query.filter(Payment.contract_id == contract_id)
        if invoice_id:
            query = query.filter(Payment.invoice_id == invoice_id)
        if customer_id:
            query = query.filter(Payment.customer_id == customer_id)
        if payment_method:
            query = query.filter(Payment.payment_method == payment_method)
        if date_from:
            query = query.filter(func.date(Payment.payment_date) >= date_from)
        if date_to:
            query = query.filter(func.date(Payment.payment_date) <= date_to)

        pagamentos = query.order_by(Payment.created_at.desc()).all()
        logger.info(f"[listar_pagamentos] Retornando {len(pagamentos)} pagamentos")
        return pagamentos

    except Exception as e:
        logger.exception("[listar_pagamentos] Erro ao listar pagamentos")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )


@router.get("/{payment_id}", response_model=PaymentResponse)
async def obter_pagamento(
    client_id: int,
    company_id: int,
    payment_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """Obtém um pagamento específico."""
    pagamento = db.query(Payment).filter(
        Payment.id == payment_id,
        Payment.company_id == company_id
    ).first()

    if not pagamento:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pagamento não encontrado"
        )

    return pagamento


@router.post("/", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def criar_pagamento(
    client_id: int,
    company_id: int,
    payload: PaymentCreate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Cria um novo registro de pagamento.

    Atualiza automaticamente:
    - amount_paid na fatura (se vinculado)
    - total_paid no contrato (se vinculado)
    """
    logger.info(f"[criar_pagamento] company_id={company_id}, amount={payload.amount}")

    # Validar método de pagamento
    valid_methods = ['pix', 'credit_card', 'debit_card', 'boleto', 'cash', 'transfer', 'other']
    if payload.payment_method not in valid_methods:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Método de pagamento inválido. Use: {', '.join(valid_methods)}"
        )

    customer_id = payload.customer_id
    contact_id = payload.contact_id

    # Verificar fatura se fornecida
    if payload.invoice_id:
        invoice = db.query(Invoice).filter(
            Invoice.id == payload.invoice_id,
            Invoice.company_id == company_id
        ).first()

        if not invoice:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fatura não encontrada"
            )

        if invoice.status in ["void", "refunded"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Não é possível registrar pagamento em fatura com status '{invoice.status}'"
            )
        customer_id = customer_id or invoice.customer_id
        contact_id = contact_id or invoice.contact_id

    # Verificar contrato se fornecido
    if payload.contract_id:
        contract = db.query(Contract).options(joinedload(Contract.items)).filter(
            Contract.id == payload.contract_id,
            Contract.company_id == company_id
        ).first()

        if not contract:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contrato não encontrado"
            )

        if contract.status == "canceled":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Não é possível registrar pagamento em contrato cancelado"
            )
        customer_id = customer_id or contract.customer_id
        contact_id = contact_id or contract.contact_id

    if customer_id:
        customer = db.query(Customer).filter(
            Customer.id == customer_id,
            Customer.company_id == company_id
        ).first()
        if not customer:
            raise HTTPException(status_code=404, detail="Cliente não encontrado")
        contact_id = contact_id or customer.contact_id

    try:
        novo_pagamento = Payment(
            company_id=company_id,
            invoice_id=payload.invoice_id,
            contract_id=payload.contract_id,
            contact_id=contact_id,
            customer_id=customer_id,
            external_id=payload.external_id,
            type="payment",
            status="succeeded",
            amount=payload.amount,
            currency="BRL",
            payment_method=payload.payment_method,
            payment_date=payload.payment_date or func.now(),
            gateway=payload.gateway or "manual",
            receipt_url=payload.receipt_url,
            notes=payload.notes
        )

        db.add(novo_pagamento)

        # Atualizar fatura
        if payload.invoice_id:
            invoice.amount_paid = invoice.amount_paid + payload.amount
            if invoice.amount_paid >= invoice.total:
                invoice.status = "paid"
                invoice.paid_at = payload.payment_date or func.now()

        # Atualizar contrato
        if payload.contract_id:
            contract.total_paid = contract.total_paid + payload.amount
            if contract.total_paid >= contract.total_value and not is_recurring_contract(contract):
                contract.status = "completed"

        db.commit()
        db.refresh(novo_pagamento)

        logger.info(f"[criar_pagamento] Pagamento criado ID {novo_pagamento.id}")
        return novo_pagamento

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("[criar_pagamento] Erro ao criar pagamento")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao criar pagamento: {str(e)}"
        )


# -----------------------------------------------------------------------------
# Estorno
# -----------------------------------------------------------------------------

@router.post("/{payment_id}/refund", response_model=PaymentResponse)
async def estornar_pagamento(
    client_id: int,
    company_id: int,
    payment_id: int,
    payload: RefundRequest,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Cria um estorno para um pagamento.

    Pode ser estorno total ou parcial.
    Atualiza automaticamente fatura e contrato.
    """
    logger.info(f"[estornar_pagamento] payment_id={payment_id}")

    # Buscar pagamento original
    pagamento_original = db.query(Payment).filter(
        Payment.id == payment_id,
        Payment.company_id == company_id
    ).first()

    if not pagamento_original:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pagamento não encontrado"
        )

    if pagamento_original.type == "refund":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não é possível estornar um estorno"
        )

    if pagamento_original.status != "succeeded":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Apenas pagamentos confirmados podem ser estornados"
        )

    linked_invoice = None
    if pagamento_original.invoice_id:
        linked_invoice = db.query(Invoice).filter(
            Invoice.id == pagamento_original.invoice_id,
            Invoice.company_id == company_id,
        ).first()
    linked_contract = None
    if pagamento_original.contract_id:
        linked_contract = db.query(Contract).filter(
            Contract.id == pagamento_original.contract_id,
            Contract.company_id == company_id,
        ).first()
    # Calcular valor do estorno
    refund_amount = payload.amount if payload.amount else pagamento_original.amount

    # Verificar se já houve estornos anteriores
    total_refunded = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.company_id == company_id,
        Payment.type == "refund",
        Payment.notes.contains(f"Ref. Payment #{payment_id}")  # Rastrear por nota
    ).scalar()

    available_for_refund = pagamento_original.amount - Decimal(str(total_refunded))

    if refund_amount > available_for_refund:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Valor de estorno ({refund_amount}) excede o disponível ({available_for_refund})"
        )

    try:
        # Criar registro de estorno
        refund = Payment(
            company_id=company_id,
            invoice_id=pagamento_original.invoice_id,
            contract_id=pagamento_original.contract_id,
            contact_id=pagamento_original.contact_id,
            customer_id=pagamento_original.customer_id,
            type="refund",
            status="succeeded",
            amount=refund_amount,
            currency="BRL",
            payment_method=pagamento_original.payment_method,
            payment_date=func.now(),
            gateway=pagamento_original.gateway,
            notes=f"Estorno ref. Payment #{payment_id}. {payload.reason or ''}"
        )

        db.add(refund)

        # Atualizar fatura
        if linked_invoice:
            linked_invoice.amount_paid = linked_invoice.amount_paid - refund_amount
            if linked_invoice.amount_paid < linked_invoice.total:
                linked_invoice.status = "open"  # Reabrir fatura
            if linked_invoice.amount_paid <= 0:
                linked_invoice.status = "refunded"

        # Atualizar contrato
        if linked_contract:
            linked_contract.total_paid = linked_contract.total_paid - refund_amount
            if linked_contract.status == "completed":
                linked_contract.status = "active"  # Reativar contrato

        db.commit()
        db.refresh(refund)

        logger.info(f"[estornar_pagamento] Estorno criado ID {refund.id}")
        return refund

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("[estornar_pagamento] Erro ao estornar")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao estornar: {str(e)}"
        )


# -----------------------------------------------------------------------------
# Sumário
# -----------------------------------------------------------------------------

class PaymentSummary(BaseModel):
    """Sumário de pagamentos."""
    total_received: Decimal
    total_refunded: Decimal
    net_received: Decimal
    payment_count: int
    refund_count: int
    by_method: dict


@router.get("/summary/totals", response_model=PaymentSummary)
async def resumo_pagamentos(
    client_id: int,
    company_id: int,
    date_from: Optional[date] = Query(None, description="Data desde"),
    date_to: Optional[date] = Query(None, description="Data até"),
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Retorna resumo dos pagamentos da empresa.
    """
    try:
        # Query base
        query = db.query(Payment).filter(
            Payment.company_id == company_id,
            Payment.status == "succeeded"
        )

        if date_from:
            query = query.filter(func.date(Payment.payment_date) >= date_from)
        if date_to:
            query = query.filter(func.date(Payment.payment_date) <= date_to)

        payments = query.all()

        # Calcular totais
        total_received = Decimal('0')
        total_refunded = Decimal('0')
        payment_count = 0
        refund_count = 0
        by_method = {}

        for p in payments:
            if p.type == "payment":
                total_received += p.amount
                payment_count += 1
                method = p.payment_method or "other"
                by_method[method] = by_method.get(method, Decimal('0')) + p.amount
            elif p.type == "refund":
                total_refunded += p.amount
                refund_count += 1

        return PaymentSummary(
            total_received=total_received,
            total_refunded=total_refunded,
            net_received=total_received - total_refunded,
            payment_count=payment_count,
            refund_count=refund_count,
            by_method={k: float(v) for k, v in by_method.items()}
        )

    except Exception as e:
        logger.exception("[resumo_pagamentos] Erro")
        raise HTTPException(status_code=500, detail=str(e))
