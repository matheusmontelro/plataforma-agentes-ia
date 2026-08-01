# backend/routes/invoices_routes.py
"""
API REST para gestão de Faturas.
CRUD + ações: mark-paid, void, send.
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
from backend.models.revenue_models import Invoice, InvoiceLineItem, Payment, Contract, Plan
from backend.services.customer_revenue_service import is_recurring_contract

logger = logging.getLogger("agentive.invoices")

router = APIRouter(
    prefix="/clients/{client_id}/companies/{company_id}/invoices",
    tags=["Invoices - Faturas"]
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

class InvoiceLineItemCreate(BaseModel):
    """Schema para criar item de fatura."""
    description: str = Field(..., min_length=1, max_length=500)
    quantity: int = Field(default=1, ge=1)
    unit_price: Decimal = Field(..., ge=0)
    discount_amount: Decimal = Field(default=0, ge=0)
    type: str = Field(default="one_time")  # subscription, one_time, refund
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    plan_id: Optional[int] = None
    contract_item_id: Optional[int] = None


class InvoiceCreate(BaseModel):
    """Schema para criar fatura."""
    contract_id: Optional[int] = None
    contact_id: Optional[int] = None
    customer_id: Optional[int] = None
    due_date: Optional[date] = None
    payment_method: Optional[str] = None
    notes: Optional[str] = None
    line_items: List[InvoiceLineItemCreate] = Field(default_factory=list)

    class Config:
        json_schema_extra = {
            "example": {
                "contract_id": 123,
                "due_date": "2026-02-15",
                "payment_method": "boleto",
                "line_items": [
                    {
                        "description": "Parcela 1/12 - Tratamento Ortodôntico",
                        "quantity": 1,
                        "unit_price": 500.00
                    }
                ]
            }
        }


class InvoiceUpdate(BaseModel):
    """Schema para atualizar fatura."""
    due_date: Optional[date] = None
    payment_method: Optional[str] = None
    notes: Optional[str] = None


class InvoiceLineItemResponse(BaseModel):
    """Schema de resposta de item de fatura."""
    id: int
    invoice_id: int
    description: str
    quantity: int
    unit_price: Decimal
    discount_amount: Decimal
    total: Decimal
    type: str
    period_start: Optional[date]
    period_end: Optional[date]
    plan_id: Optional[int]
    contract_item_id: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


class InvoiceResponse(BaseModel):
    """Schema de resposta de fatura."""
    id: int
    company_id: int
    contract_id: Optional[int]
    contact_id: Optional[int]
    customer_id: Optional[int]
    invoice_number: str
    external_id: Optional[str]
    recurrence_key: Optional[str]
    status: str
    issue_date: date
    due_date: Optional[date]
    paid_at: Optional[datetime]
    subtotal: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    total: Decimal
    amount_paid: Decimal
    amount_due: Decimal
    currency: str
    payment_method: Optional[str]
    notes: Optional[str]
    customer_name: Optional[str] = None
    installment_number: Optional[int] = None
    installments: Optional[int] = None
    line_items: List[InvoiceLineItemResponse]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InvoiceListResponse(BaseModel):
    """Schema simplificado para listagem."""
    id: int
    company_id: int
    contract_id: Optional[int]
    contact_id: Optional[int]
    customer_id: Optional[int]
    invoice_number: str
    external_id: Optional[str] = None
    recurrence_key: Optional[str]
    status: str
    issue_date: date
    due_date: Optional[date]
    total: Decimal
    amount_paid: Decimal
    amount_due: Decimal
    currency: str
    payment_method: Optional[str]
    customer_name: Optional[str] = None
    installment_number: Optional[int] = None
    installments: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class MarkPaidRequest(BaseModel):
    """Schema para marcar fatura como paga."""
    payment_method: Optional[str] = None
    payment_date: Optional[datetime] = None
    notes: Optional[str] = None


# -----------------------------------------------------------------------------
# Funções auxiliares
# -----------------------------------------------------------------------------

def generate_invoice_number(db: Session, company_id: int) -> str:
    """Gera número de fatura único para a empresa."""
    year = datetime.now().year

    count = db.query(func.count(Invoice.id)).filter(
        Invoice.company_id == company_id,
        func.extract('year', Invoice.created_at) == year
    ).scalar() or 0

    return f"INV-{year}-{str(count + 1).zfill(6)}"


def calculate_line_item_total(item: InvoiceLineItemCreate) -> Decimal:
    """Calcula total de um item de fatura."""
    return (Decimal(str(item.quantity)) * item.unit_price) - item.discount_amount


def invoice_installment_info(invoice: Invoice) -> tuple[Optional[int], Optional[int]]:
    extra = invoice.extra_data if isinstance(invoice.extra_data, dict) else {}
    try:
        installment_number = int(extra.get("installment_number") or 1)
    except (TypeError, ValueError):
        installment_number = 1
    try:
        installments = int(extra.get("installments") or 1)
    except (TypeError, ValueError):
        installments = 1
    return installment_number, installments


def invoice_customer_name(invoice: Invoice) -> Optional[str]:
    if invoice.customer and invoice.customer.nome:
        return invoice.customer.nome
    if invoice.contact and invoice.contact.name:
        return invoice.contact.name
    return None


def validate_invoice_line_item_plans(db: Session, company_id: int, line_items: List[InvoiceLineItemCreate]) -> None:
    plan_ids = sorted({item.plan_id for item in line_items if item.plan_id})
    if not plan_ids:
        return

    rows = db.query(Plan.id).filter(
        Plan.company_id == company_id,
        Plan.id.in_(plan_ids),
    ).all()
    found_ids = set()
    for row in rows:
        try:
            found_ids.add(int(row[0]))
        except (TypeError, IndexError):
            found_ids.add(int(row))
    missing_ids = [plan_id for plan_id in plan_ids if plan_id not in found_ids]
    if missing_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produto/plano não encontrado para esta empresa")


def invoice_list_response(invoice: Invoice) -> InvoiceListResponse:
    installment_number, installments = invoice_installment_info(invoice)
    return InvoiceListResponse(
        id=invoice.id,
        company_id=invoice.company_id,
        contract_id=invoice.contract_id,
        contact_id=invoice.contact_id,
        customer_id=invoice.customer_id,
        invoice_number=invoice.invoice_number,
        external_id=invoice.external_id,
        recurrence_key=invoice.recurrence_key,
        status=invoice.status,
        issue_date=invoice.issue_date,
        due_date=invoice.due_date,
        total=invoice.total,
        amount_paid=invoice.amount_paid,
        amount_due=invoice.amount_due,
        currency=invoice.currency,
        payment_method=invoice.payment_method,
        customer_name=invoice_customer_name(invoice),
        installment_number=installment_number,
        installments=installments,
        created_at=invoice.created_at,
    )


# -----------------------------------------------------------------------------
# Rotas CRUD
# -----------------------------------------------------------------------------

@router.get("/", response_model=List[InvoiceListResponse])
async def listar_faturas(
    client_id: int,
    company_id: int,
    status_filter: Optional[str] = Query(None, alias="status", description="Filtrar por status"),
    contract_id: Optional[int] = Query(None, description="Filtrar por contrato"),
    contact_id: Optional[int] = Query(None, description="Filtrar por contato"),
    customer_id: Optional[int] = Query(None, description="Filtrar por cliente"),
    due_date_from: Optional[date] = Query(None, description="Vencimento desde"),
    due_date_to: Optional[date] = Query(None, description="Vencimento até"),
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """Lista todas as faturas de uma empresa."""
    logger.info(f"[listar_faturas] company_id={company_id}")

    try:
        query = db.query(Invoice).options(
            joinedload(Invoice.customer),
            joinedload(Invoice.contact),
        ).filter(Invoice.company_id == company_id)

        if status_filter:
            query = query.filter(Invoice.status == status_filter)
        if contract_id:
            query = query.filter(Invoice.contract_id == contract_id)
        if contact_id:
            query = query.filter(Invoice.contact_id == contact_id)
        if customer_id:
            query = query.filter(Invoice.customer_id == customer_id)
        if due_date_from:
            query = query.filter(Invoice.due_date >= due_date_from)
        if due_date_to:
            query = query.filter(Invoice.due_date <= due_date_to)

        faturas = query.order_by(Invoice.created_at.desc()).all()
        logger.info(f"[listar_faturas] Retornando {len(faturas)} faturas")
        return [invoice_list_response(fatura) for fatura in faturas]

    except Exception as e:
        logger.exception("[listar_faturas] Erro ao listar faturas")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def obter_fatura(
    client_id: int,
    company_id: int,
    invoice_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """Obtém uma fatura específica com seus itens."""
    logger.info(f"[obter_fatura] company_id={company_id}, invoice_id={invoice_id}")

    try:
        fatura = db.query(Invoice).options(
            joinedload(Invoice.line_items),
            joinedload(Invoice.customer),
            joinedload(Invoice.contact),
        ).filter(
            Invoice.id == invoice_id,
            Invoice.company_id == company_id
        ).first()

        if not fatura:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fatura não encontrada"
            )

        installment_number, installments = invoice_installment_info(fatura)
        response = InvoiceResponse(
            id=fatura.id,
            company_id=fatura.company_id,
            contract_id=fatura.contract_id,
            contact_id=fatura.contact_id,
            customer_id=fatura.customer_id,
            invoice_number=fatura.invoice_number,
            external_id=fatura.external_id,
            recurrence_key=fatura.recurrence_key,
            status=fatura.status,
            issue_date=fatura.issue_date,
            due_date=fatura.due_date,
            paid_at=fatura.paid_at,
            subtotal=fatura.subtotal,
            discount_amount=fatura.discount_amount,
            tax_amount=fatura.tax_amount,
            total=fatura.total,
            amount_paid=fatura.amount_paid,
            amount_due=fatura.amount_due,
            currency=fatura.currency,
            payment_method=fatura.payment_method,
            notes=fatura.notes,
            customer_name=invoice_customer_name(fatura),
            installment_number=installment_number,
            installments=installments,
            line_items=[InvoiceLineItemResponse.model_validate(item) for item in fatura.line_items],
            created_at=fatura.created_at,
            updated_at=fatura.updated_at
        )

        return response

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        logger.exception("[obter_fatura] Erro ao obter fatura")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )


@router.post("/", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
async def criar_fatura(
    client_id: int,
    company_id: int,
    payload: InvoiceCreate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """Cria uma nova fatura."""
    logger.info(f"[criar_fatura] company_id={company_id}")

    if not payload.line_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A fatura deve ter pelo menos um item"
        )
    validate_invoice_line_item_plans(db, company_id, payload.line_items)

    # Calcular totais
    subtotal = sum(calculate_line_item_total(item) for item in payload.line_items)
    total_discount = sum(item.discount_amount for item in payload.line_items)

    contract = None
    contact_id = payload.contact_id
    customer_id = payload.customer_id

    if payload.contract_id:
        contract = db.query(Contract).filter(
            Contract.id == payload.contract_id,
            Contract.company_id == company_id
        ).first()
        if not contract:
            raise HTTPException(status_code=404, detail="Contrato não encontrado")
        contact_id = contact_id or contract.contact_id
        customer_id = customer_id or contract.customer_id

    if customer_id:
        customer = db.query(Customer).filter(
            Customer.id == customer_id,
            Customer.company_id == company_id
        ).first()
        if not customer:
            raise HTTPException(status_code=404, detail="Cliente não encontrado")
        contact_id = contact_id or customer.contact_id
    else:
        customer = None

    try:
        nova_fatura = Invoice(
            company_id=company_id,
            contract_id=payload.contract_id,
            contact_id=contact_id,
            customer_id=customer_id,
            invoice_number=generate_invoice_number(db, company_id),
            status="open",
            issue_date=date.today(),
            due_date=payload.due_date,
            subtotal=subtotal + total_discount,  # Subtotal antes dos descontos
            discount_amount=total_discount,
            tax_amount=Decimal('0'),
            total=subtotal,
            amount_paid=Decimal('0'),
            payment_method=payload.payment_method,
            notes=payload.notes
        )

        db.add(nova_fatura)
        db.flush()

        # Criar itens da fatura
        for item_data in payload.line_items:
            item = InvoiceLineItem(
                invoice_id=nova_fatura.id,
                description=item_data.description,
                quantity=item_data.quantity,
                unit_price=item_data.unit_price,
                discount_amount=item_data.discount_amount,
                total=calculate_line_item_total(item_data),
                type=item_data.type,
                period_start=item_data.period_start,
                period_end=item_data.period_end,
                plan_id=item_data.plan_id,
                contract_item_id=item_data.contract_item_id
            )
            db.add(item)

        db.commit()
        db.refresh(nova_fatura)

        logger.info(f"[criar_fatura] Fatura criada: {nova_fatura.invoice_number}")
        return await obter_fatura(client_id, company_id, nova_fatura.id, db, _)

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("[criar_fatura] Erro ao criar fatura")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao criar fatura: {str(e)}"
        )


@router.put("/{invoice_id}", response_model=InvoiceResponse)
async def atualizar_fatura(
    client_id: int,
    company_id: int,
    invoice_id: int,
    payload: InvoiceUpdate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """Atualiza uma fatura (apenas campos editáveis)."""
    fatura = db.query(Invoice).options(joinedload(Invoice.line_items)).filter(
        Invoice.id == invoice_id,
        Invoice.company_id == company_id
    ).first()

    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    if fatura.status in ["paid", "void", "refunded"]:
        raise HTTPException(
            status_code=400,
            detail=f"Não é possível editar fatura com status '{fatura.status}'"
        )
    try:
        update_data = payload.model_dump(exclude_unset=True)
        for campo, valor in update_data.items():
            setattr(fatura, campo, valor)
        db.commit()
        return await obter_fatura(client_id, company_id, invoice_id, db, _)

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def excluir_fatura(
    client_id: int,
    company_id: int,
    invoice_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """Exclui uma fatura sem histórico financeiro."""
    fatura = db.query(Invoice).options(joinedload(Invoice.line_items)).filter(
        Invoice.id == invoice_id,
        Invoice.company_id == company_id
    ).first()

    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    if fatura.status not in ["draft", "open", "overdue"]:
        raise HTTPException(
            status_code=400,
            detail="Apenas faturas em rascunho, abertas ou vencidas podem ser excluídas"
        )

    if fatura.amount_paid and fatura.amount_paid > 0:
        raise HTTPException(status_code=400, detail="Fatura com pagamento registrado não pode ser excluída")

    payment_count = db.query(func.count(Payment.id)).filter(
        Payment.company_id == company_id,
        Payment.invoice_id == invoice_id
    ).scalar() or 0
    if payment_count:
        raise HTTPException(status_code=400, detail="Fatura com pagamento vinculado não pode ser excluída")

    try:
        db.delete(fatura)
        db.commit()
        return None
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("[excluir_fatura] Erro")
        raise HTTPException(status_code=400, detail=str(e))


# -----------------------------------------------------------------------------
# Ações especiais
# -----------------------------------------------------------------------------

@router.post("/{invoice_id}/mark-paid", response_model=InvoiceResponse)
async def marcar_fatura_paga(
    client_id: int,
    company_id: int,
    invoice_id: int,
    payload: MarkPaidRequest,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Marca uma fatura como paga.

    Cria automaticamente um registro de pagamento e atualiza o contrato.
    """
    logger.info(f"[marcar_fatura_paga] invoice_id={invoice_id}")

    fatura = db.query(Invoice).filter(
        Invoice.id == invoice_id,
        Invoice.company_id == company_id
    ).first()

    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    if fatura.status == "paid":
        raise HTTPException(status_code=400, detail="Fatura já está paga")

    if fatura.status in ["void", "refunded"]:
        raise HTTPException(status_code=400, detail=f"Fatura com status '{fatura.status}' não pode ser marcada como paga")

    try:
        amount_to_pay = fatura.total - fatura.amount_paid

        # Atualizar fatura
        fatura.status = "paid"
        fatura.paid_at = payload.payment_date or func.now()
        fatura.amount_paid = fatura.total
        if payload.payment_method:
            fatura.payment_method = payload.payment_method

        # Criar registro de pagamento
        payment = Payment(
            company_id=company_id,
            invoice_id=invoice_id,
            contract_id=fatura.contract_id,
            contact_id=fatura.contact_id,
            customer_id=fatura.customer_id,
            type="payment",
            status="succeeded",
            amount=amount_to_pay,
            payment_method=payload.payment_method or fatura.payment_method,
            payment_date=payload.payment_date or func.now(),
            gateway="manual",
            notes=payload.notes
        )
        db.add(payment)

        # Atualizar total_paid no contrato (se houver)
        if fatura.contract_id:
            contrato = db.query(Contract).options(joinedload(Contract.items)).filter(Contract.id == fatura.contract_id).first()
            if contrato:
                contrato.total_paid = contrato.total_paid + amount_to_pay

                # Contratos recorrentes continuam ativos após cada ciclo pago.
                if contrato.total_paid >= contrato.total_value and not is_recurring_contract(contrato):
                    contrato.status = "completed"

        db.commit()

        logger.info(f"[marcar_fatura_paga] Fatura {invoice_id} marcada como paga")
        return await obter_fatura(client_id, company_id, invoice_id, db, _)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("[marcar_fatura_paga] Erro")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{invoice_id}/void", response_model=InvoiceResponse)
async def cancelar_fatura(
    client_id: int,
    company_id: int,
    invoice_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """Cancela/anula uma fatura."""
    fatura = db.query(Invoice).filter(
        Invoice.id == invoice_id,
        Invoice.company_id == company_id
    ).first()

    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    if fatura.status == "paid":
        raise HTTPException(
            status_code=400,
            detail="Fatura já paga não pode ser anulada. Use estorno."
        )

    if fatura.status == "void":
        raise HTTPException(status_code=400, detail="Fatura já está anulada")

    try:
        fatura.status = "void"
        db.commit()

        return await obter_fatura(client_id, company_id, invoice_id, db, _)

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
