# backend/routes/contracts_routes.py
"""
API REST para gestão de Contratos.
CRUD completo + ações especiais + conversão de lead.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status, Header, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, func
from typing import List, Optional
from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import datetime, date
from enum import Enum

from backend.db import get_db
from backend.auth import verify_client_or_bearer_api_key
from backend.models import Client, Lead, Contact, Customer
from backend.models.revenue_models import Contract, ContractItem, Plan, Invoice, InvoiceLineItem, Payment
from backend.services.customer_revenue_service import RECURRING_INTERVALS, ensure_customer_from_lead

logger = logging.getLogger("agentive.contracts")

router = APIRouter(
    prefix="/clients/{client_id}/companies/{company_id}",
    tags=["Contracts - Contratos"]
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
# Enums
# -----------------------------------------------------------------------------

class ContractStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELED = "canceled"
    COMPLETED = "completed"


class PaymentMethodEnum(str, Enum):
    PIX = "pix"
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    BOLETO = "boleto"
    CASH = "cash"
    TRANSFER = "transfer"


# -----------------------------------------------------------------------------
# Schemas Pydantic
# -----------------------------------------------------------------------------

class ContractItemCreate(BaseModel):
    """Schema para item de contrato."""
    plan_id: Optional[int] = None
    description: str = Field(..., min_length=1, max_length=500)
    quantity: int = Field(default=1, ge=1)
    unit_price: Decimal = Field(..., ge=0)
    discount_percent: Optional[Decimal] = Field(default=0, ge=0, le=100)
    discount_amount: Optional[Decimal] = Field(default=0, ge=0)
    billing_interval: str = Field(default="once")
    sessions_total: Optional[int] = Field(None, ge=1)


class ContractCreate(BaseModel):
    """Schema para criação de contrato."""
    lead_id: Optional[int] = None
    contact_id: Optional[int] = None
    customer_id: Optional[int] = None
    external_id: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    payment_method: Optional[str] = None
    installments: int = Field(default=1, ge=1)
    notes: Optional[str] = None
    items: List[ContractItemCreate] = Field(default_factory=list)

    # Pagamento inicial (opcional)
    initial_payment_amount: Optional[Decimal] = Field(None, ge=0)
    initial_payment_method: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "lead_id": 123,
                "payment_method": "credit_card",
                "installments": 12,
                "items": [
                    {
                        "description": "Tratamento Ortodôntico",
                        "unit_price": 6000.00,
                        "discount_percent": 10
                    }
                ],
                "initial_payment_amount": 500.00,
                "initial_payment_method": "pix"
            }
        }


class ContractUpdate(BaseModel):
    """Schema para atualização de contrato."""
    external_id: Optional[str] = None
    end_date: Optional[date] = None
    payment_method: Optional[str] = None
    installments: Optional[int] = Field(None, ge=1)
    notes: Optional[str] = None


class ContractItemResponse(BaseModel):
    """Schema de resposta de item de contrato."""
    id: int
    contract_id: int
    plan_id: Optional[int]
    description: str
    quantity: int
    unit_price: Decimal
    discount_percent: Decimal
    discount_amount: Decimal
    total_price: Decimal
    billing_interval: str
    sessions_total: Optional[int]
    sessions_used: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


class ContractResponse(BaseModel):
    """Schema de resposta de contrato."""
    id: int
    company_id: int
    lead_id: Optional[int]
    contact_id: Optional[int]
    customer_id: Optional[int]
    external_id: Optional[str]
    status: str
    start_date: date
    end_date: Optional[date]
    billing_anchor_date: Optional[date]
    next_invoice_date: Optional[date]
    canceled_at: Optional[datetime]
    cancellation_reason: Optional[str]
    total_value: Decimal
    total_paid: Decimal
    remaining_value: Decimal
    currency: str
    payment_method: Optional[str]
    installments: int
    notes: Optional[str]
    items: List[ContractItemResponse]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @property
    def remaining_value(self) -> Decimal:
        return self.total_value - self.total_paid


class ContractListResponse(BaseModel):
    """Schema simplificado para listagem."""
    id: int
    company_id: int
    lead_id: Optional[int]
    contact_id: Optional[int]
    customer_id: Optional[int]
    status: str
    start_date: date
    next_invoice_date: Optional[date]
    total_value: Decimal
    total_paid: Decimal
    currency: str
    payment_method: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class CancelContractRequest(BaseModel):
    """Schema para cancelamento de contrato."""
    reason: Optional[str] = None


class LeadConvertRequest(BaseModel):
    """Schema para conversão de lead para contrato."""
    customer_id: Optional[int] = None
    total_value: Decimal = Field(..., ge=0, description="Valor total do contrato")
    payment_method: Optional[str] = None
    installments: int = Field(default=1, ge=1)
    notes: Optional[str] = None
    items: List[ContractItemCreate] = Field(default_factory=list)
    initial_payment_amount: Optional[Decimal] = Field(None, ge=0)
    initial_payment_method: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "total_value": 6000.00,
                "payment_method": "credit_card",
                "installments": 12,
                "items": [
                    {
                        "description": "Tratamento Ortodôntico Completo",
                        "unit_price": 6000.00
                    }
                ],
                "initial_payment_amount": 500.00,
                "initial_payment_method": "pix"
            }
        }


# -----------------------------------------------------------------------------
# Funções auxiliares
# -----------------------------------------------------------------------------

def calculate_item_total(item: ContractItemCreate) -> Decimal:
    """Calcula o total de um item considerando descontos."""
    subtotal = Decimal(str(item.quantity)) * item.unit_price

    # Aplica desconto percentual primeiro, depois desconto em valor
    if item.discount_percent:
        subtotal = subtotal * (1 - item.discount_percent / 100)
    if item.discount_amount:
        subtotal = subtotal - item.discount_amount

    return max(subtotal, Decimal('0'))


def generate_invoice_number(db: Session, company_id: int) -> str:
    """Gera número de fatura único para a empresa."""
    from datetime import datetime

    # Formato: INV-YYYY-NNNNNN
    year = datetime.now().year

    # Conta invoices do ano atual
    count = db.query(func.count(Invoice.id)).filter(
        Invoice.company_id == company_id,
        func.extract('year', Invoice.created_at) == year
    ).scalar() or 0

    return f"INV-{year}-{str(count + 1).zfill(6)}"


# -----------------------------------------------------------------------------
# Rotas de Contratos
# -----------------------------------------------------------------------------

@router.get("/contracts", response_model=List[ContractListResponse])
async def listar_contratos(
    client_id: int,
    company_id: int,
    status: Optional[str] = Query(None, description="Filtrar por status"),
    lead_id: Optional[int] = Query(None, description="Filtrar por lead"),
    contact_id: Optional[int] = Query(None, description="Filtrar por contato"),
    start_date_from: Optional[date] = Query(None, description="Data início desde"),
    start_date_to: Optional[date] = Query(None, description="Data início até"),
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Lista todos os contratos de uma empresa.
    """
    logger.info(f"[listar_contratos] company_id={company_id}")

    try:
        query = db.query(Contract).filter(Contract.company_id == company_id)

        if status:
            query = query.filter(Contract.status == status)
        if lead_id:
            query = query.filter(Contract.lead_id == lead_id)
        if contact_id:
            query = query.filter(Contract.contact_id == contact_id)
        if start_date_from:
            query = query.filter(Contract.start_date >= start_date_from)
        if start_date_to:
            query = query.filter(Contract.start_date <= start_date_to)

        contratos = query.order_by(Contract.created_at.desc()).all()
        logger.info(f"[listar_contratos] Retornando {len(contratos)} contratos")
        return contratos

    except Exception as e:
        logger.exception("[listar_contratos] Erro ao listar contratos")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )


@router.get("/contracts/{contract_id}", response_model=ContractResponse)
async def obter_contrato(
    client_id: int,
    company_id: int,
    contract_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """Obtém um contrato específico com seus itens."""
    logger.info(f"[obter_contrato] company_id={company_id}, contract_id={contract_id}")

    try:
        contrato = db.query(Contract).options(
            joinedload(Contract.items)
        ).filter(
            Contract.id == contract_id,
            Contract.company_id == company_id
        ).first()

        if not contrato:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contrato não encontrado"
            )

        # Calcular remaining_value dinamicamente
        response = ContractResponse(
            id=contrato.id,
            company_id=contrato.company_id,
            lead_id=contrato.lead_id,
            contact_id=contrato.contact_id,
            customer_id=contrato.customer_id,
            external_id=contrato.external_id,
            status=contrato.status,
            start_date=contrato.start_date,
            end_date=contrato.end_date,
            billing_anchor_date=contrato.billing_anchor_date,
            next_invoice_date=contrato.next_invoice_date,
            canceled_at=contrato.canceled_at,
            cancellation_reason=contrato.cancellation_reason,
            total_value=contrato.total_value,
            total_paid=contrato.total_paid,
            remaining_value=contrato.total_value - contrato.total_paid,
            currency=contrato.currency,
            payment_method=contrato.payment_method,
            installments=contrato.installments,
            notes=contrato.notes,
            items=[ContractItemResponse.model_validate(item) for item in contrato.items],
            created_at=contrato.created_at,
            updated_at=contrato.updated_at
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[obter_contrato] Erro ao obter contrato")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )


@router.post("/contracts", response_model=ContractResponse, status_code=status.HTTP_201_CREATED)
async def criar_contrato(
    client_id: int,
    company_id: int,
    payload: ContractCreate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Cria um novo contrato.

    Pode incluir itens e pagamento inicial.
    """
    logger.info(f"[criar_contrato] company_id={company_id}, payload={payload.model_dump()}")

    # Verificar lead se fornecido
    if payload.lead_id:
        lead = db.query(Lead).filter(
            Lead.id == payload.lead_id,
            Lead.company_id == company_id
        ).first()
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead não encontrado"
            )

    customer = None
    contact_id = payload.contact_id
    if payload.customer_id:
        customer = db.query(Customer).filter(
            Customer.id == payload.customer_id,
            Customer.company_id == company_id
        ).first()
        if not customer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cliente não encontrado"
            )
        contact_id = customer.contact_id

    try:
        # Calcular total dos itens
        total_value = Decimal('0')
        contract_items = []

        for item_data in payload.items:
            item_total = calculate_item_total(item_data)
            total_value += item_total

            contract_items.append(ContractItem(
                plan_id=item_data.plan_id,
                description=item_data.description,
                quantity=item_data.quantity,
                unit_price=item_data.unit_price,
                discount_percent=item_data.discount_percent or 0,
                discount_amount=item_data.discount_amount or 0,
                total_price=item_total,
                billing_interval=item_data.billing_interval,
                sessions_total=item_data.sessions_total,
                sessions_used=0
            ))

        contract_start = payload.start_date or date.today()
        recurring_contract = any(item.billing_interval in RECURRING_INTERVALS for item in contract_items)

        # Criar contrato
        novo_contrato = Contract(
            company_id=company_id,
            lead_id=payload.lead_id,
            contact_id=contact_id,
            customer_id=customer.id if customer else None,
            external_id=payload.external_id,
            status="active",
            start_date=contract_start,
            billing_anchor_date=contract_start if recurring_contract else None,
            next_invoice_date=contract_start if recurring_contract else None,
            end_date=payload.end_date,
            total_value=total_value,
            total_paid=Decimal('0'),
            currency="BRL",
            payment_method=payload.payment_method,
            installments=payload.installments,
            notes=payload.notes
        )

        db.add(novo_contrato)
        db.flush()  # Para obter o ID

        # Adicionar itens
        for item in contract_items:
            item.contract_id = novo_contrato.id
            db.add(item)

        # Processar pagamento inicial se fornecido
        if payload.initial_payment_amount and payload.initial_payment_amount > 0:
            # Criar fatura para o pagamento inicial
            invoice = Invoice(
                company_id=company_id,
                contract_id=novo_contrato.id,
                contact_id=contact_id,
                customer_id=novo_contrato.customer_id,
                invoice_number=generate_invoice_number(db, company_id),
                status="paid",
                issue_date=date.today(),
                due_date=date.today(),
                paid_at=func.now(),
                subtotal=payload.initial_payment_amount,
                total=payload.initial_payment_amount,
                amount_paid=payload.initial_payment_amount,
                payment_method=payload.initial_payment_method or payload.payment_method
            )
            db.add(invoice)
            db.flush()

            # Criar linha da fatura
            line_item = InvoiceLineItem(
                invoice_id=invoice.id,
                description="Pagamento inicial",
                quantity=1,
                unit_price=payload.initial_payment_amount,
                total=payload.initial_payment_amount,
                type="one_time"
            )
            db.add(line_item)

            # Criar registro de pagamento
            payment = Payment(
                company_id=company_id,
                invoice_id=invoice.id,
                contract_id=novo_contrato.id,
                contact_id=contact_id,
                customer_id=novo_contrato.customer_id,
                type="payment",
                status="succeeded",
                amount=payload.initial_payment_amount,
                payment_method=payload.initial_payment_method or payload.payment_method,
                payment_date=func.now(),
                gateway="manual"
            )
            db.add(payment)

            # Atualizar total pago no contrato
            novo_contrato.total_paid = payload.initial_payment_amount

        db.commit()
        db.refresh(novo_contrato)

        logger.info(f"[criar_contrato] Contrato criado com ID {novo_contrato.id}")

        # Buscar contrato com itens
        return await obter_contrato(client_id, company_id, novo_contrato.id, db, _)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("[criar_contrato] Erro ao criar contrato")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao criar contrato: {str(e)}"
        )


@router.put("/contracts/{contract_id}", response_model=ContractResponse)
async def atualizar_contrato(
    client_id: int,
    company_id: int,
    contract_id: int,
    payload: ContractUpdate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """Atualiza um contrato existente."""
    logger.info(f"[atualizar_contrato] company_id={company_id}, contract_id={contract_id}")

    contrato = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.company_id == company_id
    ).first()

    if not contrato:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contrato não encontrado"
        )
    if contrato.status == "canceled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não é possível editar um contrato cancelado"
        )

    try:
        update_data = payload.model_dump(exclude_unset=True)
        for campo, valor in update_data.items():
            setattr(contrato, campo, valor)

        db.commit()

        logger.info(f"[atualizar_contrato] Contrato {contract_id} atualizado")
        return await obter_contrato(client_id, company_id, contract_id, db, _)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("[atualizar_contrato] Erro ao atualizar contrato")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao atualizar contrato: {str(e)}"
        )


# -----------------------------------------------------------------------------
# Ações especiais
# -----------------------------------------------------------------------------

@router.post("/contracts/{contract_id}/cancel", response_model=ContractResponse)
async def cancelar_contrato(
    client_id: int,
    company_id: int,
    contract_id: int,
    payload: CancelContractRequest,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """Cancela um contrato."""
    logger.info(f"[cancelar_contrato] company_id={company_id}, contract_id={contract_id}")

    contrato = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.company_id == company_id
    ).first()

    if not contrato:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contrato não encontrado"
        )
    if contrato.status == "canceled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Contrato já está cancelado"
        )

    try:
        contrato.status = "canceled"
        contrato.canceled_at = func.now()
        contrato.cancellation_reason = payload.reason

        db.commit()

        logger.info(f"[cancelar_contrato] Contrato {contract_id} cancelado")
        return await obter_contrato(client_id, company_id, contract_id, db, _)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("[cancelar_contrato] Erro ao cancelar contrato")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao cancelar contrato: {str(e)}"
        )


@router.post("/contracts/{contract_id}/pause", response_model=ContractResponse)
async def pausar_contrato(
    client_id: int,
    company_id: int,
    contract_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """Pausa um contrato ativo."""
    contrato = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.company_id == company_id
    ).first()

    if not contrato:
        raise HTTPException(status_code=404, detail="Contrato não encontrado")
    if contrato.status != "active":
        raise HTTPException(
            status_code=400,
            detail="Apenas contratos ativos podem ser pausados"
        )

    contrato.status = "paused"
    db.commit()

    return await obter_contrato(client_id, company_id, contract_id, db, _)


@router.post("/contracts/{contract_id}/resume", response_model=ContractResponse)
async def retomar_contrato(
    client_id: int,
    company_id: int,
    contract_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """Retoma um contrato pausado."""
    contrato = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.company_id == company_id
    ).first()

    if not contrato:
        raise HTTPException(status_code=404, detail="Contrato não encontrado")
    if contrato.status != "paused":
        raise HTTPException(
            status_code=400,
            detail="Apenas contratos pausados podem ser retomados"
        )

    contrato.status = "active"
    db.commit()

    return await obter_contrato(client_id, company_id, contract_id, db, _)


# -----------------------------------------------------------------------------
# Conversão de Lead para Contrato
# -----------------------------------------------------------------------------

@router.post("/leads/{lead_id}/convert-to-contract", response_model=ContractResponse, status_code=status.HTTP_201_CREATED)
async def converter_lead_para_contrato(
    client_id: int,
    company_id: int,
    lead_id: int,
    payload: LeadConvertRequest,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Converte um lead para contrato.

    Este é o endpoint principal para registrar uma venda quando o lead
    move para a coluna "Ganhou" no CRM.

    Cria:
    - Contrato com os itens fornecidos
    - Fatura inicial (se houver pagamento)
    - Registro de pagamento (se houver pagamento)
    - Atualiza deal_value do lead
    """
    logger.info(f"[converter_lead_para_contrato] company_id={company_id}, lead_id={lead_id}")

    # Verificar lead
    lead = db.query(Lead).filter(
        Lead.id == lead_id,
        Lead.company_id == company_id
    ).first()

    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead não encontrado"
        )

    # Verificar se já existe contrato para este lead
    existing_contract = db.query(Contract).filter(
        Contract.lead_id == lead_id,
        Contract.status.in_(["active", "paused", "completed"])
    ).first()

    if existing_contract:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Lead já possui contrato ativo (ID: {existing_contract.id})"
        )

    try:
        if payload.customer_id:
            customer = db.query(Customer).filter(
                Customer.id == payload.customer_id,
                Customer.company_id == company_id
            ).first()
            if not customer:
                raise HTTPException(status_code=404, detail="Cliente não encontrado")
        else:
            customer = ensure_customer_from_lead(db, lead=lead)

        contact_id = customer.contact_id

        # Calcular total dos itens ou usar valor fornecido
        if payload.items:
            total_value = sum(calculate_item_total(item) for item in payload.items)
        else:
            total_value = payload.total_value

        recurring_contract = any(item.billing_interval in RECURRING_INTERVALS for item in payload.items)

        # Criar contrato
        novo_contrato = Contract(
            company_id=company_id,
            lead_id=lead_id,
            contact_id=contact_id,
            customer_id=customer.id,
            status="active",
            start_date=date.today(),
            billing_anchor_date=date.today() if recurring_contract else None,
            next_invoice_date=date.today() if recurring_contract else None,
            total_value=total_value,
            total_paid=Decimal('0'),
            currency="BRL",
            payment_method=payload.payment_method,
            installments=payload.installments,
            notes=payload.notes
        )

        db.add(novo_contrato)
        db.flush()

        # Criar itens do contrato
        if payload.items:
            for item_data in payload.items:
                item_total = calculate_item_total(item_data)
                item = ContractItem(
                    contract_id=novo_contrato.id,
                    plan_id=item_data.plan_id,
                    description=item_data.description,
                    quantity=item_data.quantity,
                    unit_price=item_data.unit_price,
                    discount_percent=item_data.discount_percent or 0,
                    discount_amount=item_data.discount_amount or 0,
                    total_price=item_total,
                    billing_interval=item_data.billing_interval,
                    sessions_total=item_data.sessions_total,
                    sessions_used=0
                )
                db.add(item)
        else:
            # Criar item genérico com o valor total
            item = ContractItem(
                contract_id=novo_contrato.id,
                description="Contrato de serviço",
                quantity=1,
                unit_price=total_value,
                discount_percent=0,
                discount_amount=0,
                total_price=total_value,
                billing_interval="once"
            )
            db.add(item)

        # Processar pagamento inicial
        if payload.initial_payment_amount and payload.initial_payment_amount > 0:
            invoice = Invoice(
                company_id=company_id,
                contract_id=novo_contrato.id,
                contact_id=contact_id,
                customer_id=customer.id,
                invoice_number=generate_invoice_number(db, company_id),
                status="paid",
                issue_date=date.today(),
                due_date=date.today(),
                paid_at=func.now(),
                subtotal=payload.initial_payment_amount,
                total=payload.initial_payment_amount,
                amount_paid=payload.initial_payment_amount,
                payment_method=payload.initial_payment_method or payload.payment_method
            )
            db.add(invoice)
            db.flush()

            line_item = InvoiceLineItem(
                invoice_id=invoice.id,
                description="Pagamento inicial - Conversão de lead",
                quantity=1,
                unit_price=payload.initial_payment_amount,
                total=payload.initial_payment_amount,
                type="one_time"
            )
            db.add(line_item)

            payment = Payment(
                company_id=company_id,
                invoice_id=invoice.id,
                contract_id=novo_contrato.id,
                contact_id=contact_id,
                customer_id=customer.id,
                type="payment",
                status="succeeded",
                amount=payload.initial_payment_amount,
                payment_method=payload.initial_payment_method or payload.payment_method,
                payment_date=func.now(),
                gateway="manual"
            )
            db.add(payment)

            novo_contrato.total_paid = payload.initial_payment_amount

        # Atualizar deal_value no lead
        lead.deal_value = total_value
        customer.valor_total_tratamentos = (customer.valor_total_tratamentos or Decimal("0")) + total_value

        db.commit()
        db.refresh(novo_contrato)

        logger.info(f"[converter_lead_para_contrato] Lead {lead_id} convertido para contrato {novo_contrato.id}")

        return await obter_contrato(client_id, company_id, novo_contrato.id, db, _)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("[converter_lead_para_contrato] Erro ao converter lead")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao converter lead: {str(e)}"
        )
