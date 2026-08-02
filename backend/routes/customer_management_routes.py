"""Customer management and revenue workflows."""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, joinedload

from backend.auth import (
    get_managed_workspace_trial_state,
    refresh_managed_workspace_lifecycle,
    verify_client_or_bearer_api_key,
)
from backend.db import get_db
from backend.models import AICreditWallet, Client, ClientCompany, Company, Contact, Customer, CustomerManagedCompany, Lead
from backend.models.revenue_models import Contract, ContractItem, Invoice, Payment, Plan
from backend.services.ai_usage_service import managed_workspace_trial_credits_for_days
from backend.services.customer_revenue_service import (
    RECURRING_INTERVALS,
    add_billing_interval,
    calculate_item_total,
    create_invoice_for_contract_period,
    ensure_customer_from_contact,
    ensure_customer_from_lead,
    get_contract_billing_interval,
    is_recurring_contract,
    monthly_recurring_amount,
    register_manual_payment,
)
from backend.services.company_access_control import (
    CompanyOperationalLockBusyError,
    CompanyOperationallyBlockedError,
    ensure_company_operational,
    lock_entities_for_mutation,
)


logger = logging.getLogger("agentive.customer_management")

router = APIRouter(
    prefix="/clients/{client_id}/companies/{company_id}/customers",
    tags=["Customer Management - Clientes"],
)


class CustomerBillingProfilePayload(BaseModel):
    cpf_cnpj: Optional[str] = Field(None, max_length=18)
    mobile_phone: Optional[str] = Field(None, max_length=20)
    postal_code: Optional[str] = Field(None, max_length=20)
    address: Optional[str] = Field(None, max_length=255)
    address_number: Optional[str] = Field(None, max_length=30)
    complement: Optional[str] = Field(None, max_length=120)
    province: Optional[str] = Field(None, max_length=120)
    city: Optional[str] = Field(None, max_length=120)
    state: Optional[str] = Field(None, max_length=2)


class CustomerCreate(CustomerBillingProfilePayload):
    contact_id: Optional[int] = None
    lead_id: Optional[int] = None
    name: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None


class CustomerUpdate(CustomerBillingProfilePayload):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    phone: Optional[str] = Field(None, min_length=1, max_length=20)
    email: Optional[str] = Field(None, max_length=255)
    status: Optional[str] = Field(None, pattern="^(ativo|inativo|bloqueado)$")
    categoria: Optional[str] = Field(None, pattern="^(cliente|lead_qualificado|prospect|ex_cliente)$")
    notes: Optional[str] = None


class CustomerResponse(BaseModel):
    id: int
    contact_id: int
    company_id: int
    nome: str
    telefone: str
    email: Optional[str]
    cpf_cnpj: Optional[str] = None
    mobile_phone: Optional[str] = None
    postal_code: Optional[str] = None
    address: Optional[str] = None
    address_number: Optional[str] = None
    complement: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    status: str
    categoria: str
    convertido_de_lead_id: Optional[int]
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CustomerListItem(CustomerResponse):
    mrr: Decimal
    total_paid: Decimal
    open_amount: Decimal
    overdue_amount: Decimal
    active_contracts: int
    open_invoices: int
    overdue_invoices: int
    next_invoice_date: Optional[date]
    last_payment_date: Optional[datetime]
    churned_at: Optional[datetime]


class ContractItemCreate(BaseModel):
    plan_id: Optional[int] = None
    description: str = Field(..., min_length=1, max_length=500)
    quantity: int = Field(default=1, ge=1)
    unit_price: Decimal = Field(..., ge=0)
    discount_percent: Decimal = Field(default=0, ge=0, le=100)
    discount_amount: Decimal = Field(default=0, ge=0)
    billing_interval: str = Field(default="once")
    sessions_total: Optional[int] = Field(None, ge=1)


class CustomerSaleCreate(BaseModel):
    lead_id: Optional[int] = None
    contact_id: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    payment_method: Optional[str] = None
    installments: int = Field(default=1, ge=1)
    notes: Optional[str] = None
    items: List[ContractItemCreate] = Field(default_factory=list)
    total_value: Optional[Decimal] = Field(None, ge=0)
    create_initial_invoice: bool = True
    initial_invoice_due_date: Optional[date] = None
    initial_payment_amount: Optional[Decimal] = Field(None, ge=0)
    initial_payment_method: Optional[str] = None
    initial_payment_date: Optional[datetime] = None
    initial_payment_installment: Optional[int] = Field(None, ge=1)


class GenerateRecurringInvoiceRequest(BaseModel):
    due_date: Optional[date] = None
    notes: Optional[str] = None


class CancelContractRequest(BaseModel):
    reason: Optional[str] = None


class ContractSummary(BaseModel):
    id: int
    customer_id: Optional[int]
    contact_id: Optional[int]
    lead_id: Optional[int]
    status: str
    start_date: date
    end_date: Optional[date]
    billing_anchor_date: Optional[date]
    next_invoice_date: Optional[date]
    canceled_at: Optional[datetime]
    cancellation_reason: Optional[str]
    total_value: Decimal
    total_paid: Decimal
    mrr: Decimal
    is_recurring: bool
    payment_method: Optional[str]
    notes: Optional[str]
    external_id: Optional[str] = None


class InvoiceSummary(BaseModel):
    id: int
    customer_id: Optional[int]
    contract_id: Optional[int]
    invoice_number: str
    recurrence_key: Optional[str]
    status: str
    issue_date: date
    due_date: Optional[date]
    paid_at: Optional[datetime]
    total: Decimal
    amount_paid: Decimal
    amount_due: Decimal
    payment_method: Optional[str]
    installment_number: Optional[int] = None
    installments: Optional[int] = None
    external_id: Optional[str] = None


class PaymentSummary(BaseModel):
    id: int
    customer_id: Optional[int]
    contract_id: Optional[int]
    invoice_id: Optional[int]
    type: str
    status: str
    amount: Decimal
    payment_method: Optional[str]
    payment_date: Optional[datetime]
    gateway: Optional[str]


class ManagedCompanyLinkCreate(BaseModel):
    managed_company_id: int


class CepLookupResponse(BaseModel):
    postal_code: str
    address: Optional[str] = None
    complement: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None


class ManagedCompanySummary(BaseModel):
    id: int
    owner_company_id: int
    customer_id: int
    managed_company_id: int
    name: str
    name_company: Optional[str]
    cnpj: Optional[str]
    logo_url: Optional[str]
    trial_days: int
    trial_started_at: Optional[datetime]
    trial_ends_at: Optional[datetime]
    lifecycle_status: str
    trial_days_remaining: Optional[int] = None
    trial_progress_percent: Optional[float] = None
    is_trial_expired: bool = False
    ai_credit_balance: Decimal = Decimal("0")
    trial_credits_granted: Decimal = Decimal("0")
    created_at: datetime


class CustomerDetail(CustomerListItem):
    contracts: List[ContractSummary]
    invoices: List[InvoiceSummary]
    payments: List[PaymentSummary]
    managed_companies: List[ManagedCompanySummary] = Field(default_factory=list)


class RevenueOverview(BaseModel):
    total_customers: int
    active_customers: int
    churned_customers: int
    mrr: Decimal
    open_amount: Decimal
    overdue_amount: Decimal
    paid_amount: Decimal
    open_invoices: int
    overdue_invoices: int


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _invoice_amount_due(invoice: Invoice) -> Decimal:
    return max((invoice.total or Decimal("0")) - (invoice.amount_paid or Decimal("0")), Decimal("0"))


def _invoice_installment_info(invoice: Invoice) -> tuple[int, int]:
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


BILLING_PROFILE_FIELDS = (
    "mobile_phone",
    "postal_code",
    "address",
    "address_number",
    "complement",
    "province",
    "city",
    "state",
)


def _clean_optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _clean_document(value: Any) -> Optional[str]:
    text = _clean_optional_string(value)
    if not text:
        return None
    digits = "".join(char for char in text if char.isdigit())
    return digits or None


def _digits(value: Any) -> str:
    return "".join(char for char in str(value or "") if char.isdigit())


def _fetch_cep_payload(cep: str) -> dict[str, Any]:
    url = f"https://viacep.com.br/ws/{cep}/json/"
    with urllib.request.urlopen(url, timeout=4) as response:
        return json.loads(response.read().decode("utf-8"))


def _billing_profile(customer: Customer) -> dict:
    extra = customer.dados_adicionais if isinstance(customer.dados_adicionais, dict) else {}
    profile = extra.get("billing_profile")
    return dict(profile) if isinstance(profile, dict) else {}


def _store_billing_profile(customer: Customer, profile: dict) -> None:
    extra = dict(customer.dados_adicionais or {}) if isinstance(customer.dados_adicionais, dict) else {}
    cleaned_profile = {
        key: value
        for key, value in profile.items()
        if value is not None and value != ""
    }
    extra["billing_profile"] = cleaned_profile
    customer.dados_adicionais = extra


def _apply_billing_profile(customer: Customer, update_data: dict) -> None:
    profile = _billing_profile(customer)

    if "cpf_cnpj" in update_data:
        customer.cpf = _clean_document(update_data.get("cpf_cnpj"))
        profile["cpf_cnpj"] = customer.cpf

    for field_name in BILLING_PROFILE_FIELDS:
        if field_name not in update_data:
            continue
        value = update_data.get(field_name)
        if isinstance(value, bool) or value is None:
            profile[field_name] = value
        else:
            profile[field_name] = _clean_optional_string(value)

    profile["name"] = customer.nome
    profile["phone"] = customer.telefone
    profile["email"] = customer.email

    _store_billing_profile(customer, profile)


def _customer_response(customer: Customer) -> CustomerResponse:
    profile = _billing_profile(customer)
    return CustomerResponse(
        id=customer.id,
        contact_id=customer.contact_id,
        company_id=customer.company_id,
        nome=customer.nome,
        telefone=customer.telefone,
        email=customer.email,
        cpf_cnpj=customer.cpf or profile.get("cpf_cnpj"),
        mobile_phone=profile.get("mobile_phone"),
        postal_code=profile.get("postal_code"),
        address=profile.get("address"),
        address_number=profile.get("address_number"),
        complement=profile.get("complement"),
        province=profile.get("province"),
        city=profile.get("city"),
        state=profile.get("state"),
        status=customer.status,
        categoria=customer.categoria,
        convertido_de_lead_id=customer.convertido_de_lead_id,
        notes=customer.observacoes,
        created_at=customer.created_at,
        updated_at=customer.updated_at,
    )


def _customer_metrics(db: Session, customer: Customer) -> dict:
    today = date.today()
    contracts = db.query(Contract).options(joinedload(Contract.items)).filter(
        Contract.company_id == customer.company_id,
        Contract.customer_id == customer.id,
    ).all()
    invoices = db.query(Invoice).filter(
        Invoice.company_id == customer.company_id,
        Invoice.customer_id == customer.id,
    ).all()
    payments = db.query(Payment).filter(
        Payment.company_id == customer.company_id,
        Payment.customer_id == customer.id,
        Payment.status == "succeeded",
    ).all()

    active_contracts = [contract for contract in contracts if contract.status in ("active", "paused")]
    open_invoices = [invoice for invoice in invoices if invoice.status in ("open", "overdue")]
    overdue_invoices = [
        invoice for invoice in open_invoices
        if invoice.status == "overdue" or (invoice.due_date and invoice.due_date < today)
    ]
    canceled_contracts = [contract for contract in contracts if contract.status == "canceled" and contract.canceled_at]

    payment_total = Decimal("0")
    refund_total = Decimal("0")
    last_payment_date = None
    for payment in payments:
        if payment.type == "refund":
            refund_total += payment.amount
        else:
            payment_total += payment.amount
            if payment.payment_date and (last_payment_date is None or payment.payment_date > last_payment_date):
                last_payment_date = payment.payment_date

    next_dates = [contract.next_invoice_date for contract in active_contracts if contract.next_invoice_date]

    return {
        "mrr": _money(sum((monthly_recurring_amount(contract) for contract in active_contracts), Decimal("0"))),
        "total_paid": _money(payment_total - refund_total),
        "open_amount": _money(sum((_invoice_amount_due(invoice) for invoice in open_invoices), Decimal("0"))),
        "overdue_amount": _money(sum((_invoice_amount_due(invoice) for invoice in overdue_invoices), Decimal("0"))),
        "active_contracts": len(active_contracts),
        "open_invoices": len(open_invoices),
        "overdue_invoices": len(overdue_invoices),
        "next_invoice_date": min(next_dates) if next_dates else None,
        "last_payment_date": last_payment_date,
        "churned_at": max((contract.canceled_at for contract in canceled_contracts), default=None),
    }


def _customer_list_item(db: Session, customer: Customer) -> CustomerListItem:
    return CustomerListItem(
        **_customer_response(customer).model_dump(),
        **_customer_metrics(db, customer),
    )


def _contract_summary(contract: Contract) -> ContractSummary:
    return ContractSummary(
        id=contract.id,
        customer_id=contract.customer_id,
        contact_id=contract.contact_id,
        lead_id=contract.lead_id,
        status=contract.status,
        start_date=contract.start_date,
        end_date=contract.end_date,
        billing_anchor_date=contract.billing_anchor_date,
        next_invoice_date=contract.next_invoice_date,
        canceled_at=contract.canceled_at,
        cancellation_reason=contract.cancellation_reason,
        total_value=contract.total_value,
        total_paid=contract.total_paid,
        mrr=monthly_recurring_amount(contract),
        is_recurring=is_recurring_contract(contract),
        payment_method=contract.payment_method,
        notes=contract.notes,
        external_id=contract.external_id,
    )


def _invoice_summary(invoice: Invoice) -> InvoiceSummary:
    installment_number, installments = _invoice_installment_info(invoice)
    return InvoiceSummary(
        id=invoice.id,
        customer_id=invoice.customer_id,
        contract_id=invoice.contract_id,
        invoice_number=invoice.invoice_number,
        recurrence_key=invoice.recurrence_key,
        status=invoice.status,
        issue_date=invoice.issue_date,
        due_date=invoice.due_date,
        paid_at=invoice.paid_at,
        total=invoice.total,
        amount_paid=invoice.amount_paid,
        amount_due=_invoice_amount_due(invoice),
        payment_method=invoice.payment_method,
        installment_number=installment_number,
        installments=installments,
        external_id=invoice.external_id,
    )


def _payment_summary(payment: Payment) -> PaymentSummary:
    return PaymentSummary(
        id=payment.id,
        customer_id=payment.customer_id,
        contract_id=payment.contract_id,
        invoice_id=payment.invoice_id,
        type=payment.type,
        status=payment.status,
        amount=payment.amount,
        payment_method=payment.payment_method,
        payment_date=payment.payment_date,
        gateway=payment.gateway,
    )


def _managed_company_wallets(
    db: Session,
    links: List[CustomerManagedCompany],
) -> dict[int, AICreditWallet]:
    company_ids = [link.managed_company_id for link in links]
    if not company_ids:
        return {}
    wallets = db.query(AICreditWallet).filter(AICreditWallet.company_id.in_(company_ids)).all()
    return {wallet.company_id: wallet for wallet in wallets}


def _managed_company_summary(
    link: CustomerManagedCompany,
    wallet: Optional[AICreditWallet] = None,
) -> ManagedCompanySummary:
    company = link.managed_company
    trial_state = get_managed_workspace_trial_state(link)
    return ManagedCompanySummary(
        id=link.id,
        owner_company_id=link.owner_company_id,
        customer_id=link.customer_id,
        managed_company_id=link.managed_company_id,
        name=company.name if company else "",
        name_company=company.name_company if company else None,
        cnpj=company.cnpj if company else None,
        logo_url=company.logo_url if company else None,
        trial_days=link.trial_days or 0,
        trial_started_at=link.trial_started_at,
        trial_ends_at=link.trial_ends_at,
        lifecycle_status=trial_state["lifecycle_status"],
        trial_days_remaining=trial_state["trial_days_remaining"],
        trial_progress_percent=trial_state["trial_progress_percent"],
        is_trial_expired=trial_state["is_trial_expired"],
        ai_credit_balance=Decimal(str(wallet.balance_credits or 0)) if wallet else Decimal("0"),
        trial_credits_granted=managed_workspace_trial_credits_for_days(link.trial_days),
        created_at=link.created_at,
    )


def _managed_company_summaries(
    db: Session,
    links: List[CustomerManagedCompany],
) -> List[ManagedCompanySummary]:
    wallets_by_company_id = _managed_company_wallets(db, links)
    lifecycle_changed = False
    summaries: List[ManagedCompanySummary] = []
    for link in links:
        lifecycle_changed = refresh_managed_workspace_lifecycle(db, link) or lifecycle_changed
        summaries.append(_managed_company_summary(link, wallets_by_company_id.get(link.managed_company_id)))
    if lifecycle_changed:
        db.commit()
    return summaries


def _build_contract_for_customer(
    db: Session,
    *,
    company_id: int,
    customer: Customer,
    payload: CustomerSaleCreate,
    lead_id: Optional[int] = None,
) -> Contract:
    if not payload.items and payload.total_value is None:
        raise HTTPException(status_code=400, detail="Informe pelo menos um item ou valor total")

    start_date = payload.start_date or date.today()
    contract_items: list[ContractItem] = []
    total_value = Decimal("0")

    for item_data in payload.items:
        if item_data.billing_interval not in {"once", *RECURRING_INTERVALS}:
            raise HTTPException(status_code=400, detail="Intervalo de cobrança inválido")
        if item_data.plan_id:
            plan = db.query(Plan).filter(Plan.id == item_data.plan_id, Plan.company_id == company_id).first()
            if not plan:
                raise HTTPException(status_code=404, detail="Produto/plano não encontrado")
        item_total = calculate_item_total(item_data)
        total_value += item_total
        contract_items.append(
            ContractItem(
                plan_id=item_data.plan_id,
                description=item_data.description,
                quantity=item_data.quantity,
                unit_price=item_data.unit_price,
                discount_percent=item_data.discount_percent,
                discount_amount=item_data.discount_amount,
                total_price=item_total,
                billing_interval=item_data.billing_interval,
                sessions_total=item_data.sessions_total,
                sessions_used=0,
            )
        )

    if not contract_items:
        total_value = payload.total_value or Decimal("0")
        contract_items.append(
            ContractItem(
                description="Contrato de serviço",
                quantity=1,
                unit_price=total_value,
                discount_percent=Decimal("0"),
                discount_amount=Decimal("0"),
                total_price=total_value,
                billing_interval="once",
                sessions_used=0,
            )
        )

    recurring = any(item.billing_interval in RECURRING_INTERVALS for item in contract_items)
    contract = Contract(
        company_id=company_id,
        lead_id=lead_id or payload.lead_id,
        contact_id=customer.contact_id,
        customer_id=customer.id,
        status="active",
        start_date=start_date,
        end_date=payload.end_date,
        billing_anchor_date=start_date if recurring else None,
        next_invoice_date=start_date if recurring else None,
        total_value=total_value,
        total_paid=Decimal("0"),
        currency="BRL",
        payment_method=payload.payment_method,
        installments=payload.installments,
        notes=payload.notes,
    )
    db.add(contract)
    db.flush()

    for item in contract_items:
        item.contract_id = contract.id
        db.add(item)
    db.flush()
    contract.items = contract_items

    if payload.create_initial_invoice:
        period_start = start_date if recurring else None
        period_end = None
        if recurring:
            interval = next(item.billing_interval for item in contract_items if item.billing_interval in RECURRING_INTERVALS)
            next_period_start = add_billing_interval(start_date, interval)
            period_end = next_period_start - timedelta(days=1)
            contract.next_invoice_date = next_period_start

        invoices: list[Invoice] = []
        installment_count = max(payload.installments or 1, 1)
        due_date = payload.initial_invoice_due_date or date.today()
        recurrence_base = (period_start or start_date).isoformat()
        if payload.initial_payment_installment and payload.initial_payment_installment > installment_count:
            raise HTTPException(status_code=400, detail="Parcela recebida maior que o número de parcelas")

        if installment_count > 1:
            for installment_number in range(1, installment_count + 1):
                invoices.append(create_invoice_for_contract_period(
                    db,
                    contract=contract,
                    contract_items=contract_items,
                    issue_date=date.today(),
                    due_date=add_billing_interval(due_date, "monthly", installment_number - 1),
                    recurrence_key=f"{contract.id}:{recurrence_base}:installment:{installment_number}",
                    period_start=period_start,
                    period_end=period_end,
                    notes=payload.notes,
                    installment_number=installment_number,
                    installment_count=installment_count,
                ))
        else:
            recurrence_key = f"{contract.id}:{recurrence_base}" if recurring else None
            invoices.append(create_invoice_for_contract_period(
                db,
                contract=contract,
                contract_items=contract_items,
                issue_date=date.today(),
                due_date=due_date,
                recurrence_key=recurrence_key,
                period_start=period_start,
                period_end=period_end,
                notes=payload.notes,
            ))

        if payload.initial_payment_amount and payload.initial_payment_amount > 0:
            payment_installment = payload.initial_payment_installment or 1
            invoice = invoices[payment_installment - 1]
            if payload.initial_payment_amount > invoice.total:
                detail = "Pagamento inicial maior que o total da parcela" if installment_count > 1 else "Pagamento inicial maior que o total da fatura"
                raise HTTPException(status_code=400, detail=detail)
            payment_notes = "Pagamento registrado na venda"
            if installment_count > 1:
                payment_notes = f"{payment_notes} - parcela {payment_installment}/{installment_count}"
            payment = register_manual_payment(
                db,
                invoice=invoice,
                amount=payload.initial_payment_amount,
                payment_method=payload.initial_payment_method or payload.payment_method,
                payment_date=payload.initial_payment_date,
                notes=payment_notes,
            )
            payment.gateway_response = {
                **(payment.gateway_response or {}),
                "source": "customer_sale",
                "installment_number": payment_installment if installment_count > 1 else payload.initial_payment_installment,
                "installments": installment_count,
            }

    customer.valor_total_tratamentos = (customer.valor_total_tratamentos or Decimal("0")) + total_value
    return contract


@router.get("/", response_model=List[CustomerListItem])
async def list_customers(
    client_id: int,
    company_id: int,
    search: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    category: Optional[str] = Query(None, alias="categoria"),
    limit: int = Query(default=80, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key),
):
    query = db.query(Customer).filter(Customer.company_id == company_id)

    if status_filter:
        query = query.filter(Customer.status == status_filter)
    if category:
        query = query.filter(Customer.categoria == category)
    if search:
        like = f"%{search.strip()}%"
        query = query.filter(
            (Customer.nome.ilike(like))
            | (Customer.telefone.ilike(like))
            | (Customer.email.ilike(like))
            | (Customer.cpf.ilike(like))
        )

    customers = query.order_by(Customer.updated_at.desc()).offset(offset).limit(limit).all()
    return [_customer_list_item(db, customer) for customer in customers]


@router.post("/", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(
    client_id: int,
    company_id: int,
    payload: CustomerCreate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key),
):
    update_data = payload.model_dump(exclude_unset=True)
    try:
        if payload.lead_id:
            lead = db.query(Lead).filter(Lead.id == payload.lead_id, Lead.company_id == company_id).first()
            if not lead:
                raise HTTPException(status_code=404, detail="Lead não encontrado")
            customer = ensure_customer_from_lead(db, lead=lead)
        elif payload.contact_id:
            contact = db.query(Contact).filter(Contact.id == payload.contact_id, Contact.company_id == company_id).first()
            if not contact:
                raise HTTPException(status_code=404, detail="Contato não encontrado")
            customer = ensure_customer_from_contact(db, contact=contact)
        else:
            phone = _clean_optional_string(payload.phone) or _clean_optional_string(payload.mobile_phone)
            if not phone:
                raise HTTPException(status_code=400, detail="Informe telefone ou contato existente")
            contact = db.query(Contact).filter(
                Contact.client_id == client_id,
                Contact.phone == phone,
            ).first()
            if not contact:
                contact = Contact(
                    client_id=client_id,
                    company_id=company_id,
                    phone=phone,
                    name=payload.name or "Nome não informado",
                )
                db.add(contact)
                db.flush()
            customer = ensure_customer_from_contact(db, contact=contact)

        if payload.name:
            customer.nome = payload.name.strip()
            if customer.contact:
                customer.contact.name = customer.nome
        if payload.phone:
            phone = payload.phone.strip()
            if phone and phone != customer.telefone:
                existing_customer = db.query(Customer.id).filter(
                    Customer.company_id == company_id,
                    Customer.telefone == phone,
                    Customer.id != customer.id,
                ).first()
                if existing_customer:
                    raise HTTPException(status_code=409, detail="Já existe outro cliente com este telefone")
                existing_contact = db.query(Contact.id).filter(
                    Contact.client_id == client_id,
                    Contact.phone == phone,
                    Contact.id != customer.contact_id,
                ).first()
                if existing_contact:
                    raise HTTPException(status_code=409, detail="Já existe outro contato com este telefone")
                customer.telefone = phone
                if customer.contact:
                    customer.contact.phone = phone
        if payload.email:
            customer.email = payload.email
        if payload.notes:
            customer.observacoes = payload.notes
        _apply_billing_profile(customer, update_data)
        db.flush()

        db.commit()
        db.refresh(customer)
        return _customer_response(customer)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("[create_customer] erro")
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/overview", response_model=RevenueOverview)
async def revenue_overview(
    client_id: int,
    company_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key),
):
    customers = db.query(Customer).filter(Customer.company_id == company_id).all()
    metrics = [_customer_metrics(db, customer) for customer in customers]
    return RevenueOverview(
        total_customers=len(customers),
        active_customers=sum(1 for customer in customers if customer.status == "ativo"),
        churned_customers=sum(1 for customer in customers if customer.categoria == "ex_cliente"),
        mrr=_money(sum((item["mrr"] for item in metrics), Decimal("0"))),
        open_amount=_money(sum((item["open_amount"] for item in metrics), Decimal("0"))),
        overdue_amount=_money(sum((item["overdue_amount"] for item in metrics), Decimal("0"))),
        paid_amount=_money(sum((item["total_paid"] for item in metrics), Decimal("0"))),
        open_invoices=sum(item["open_invoices"] for item in metrics),
        overdue_invoices=sum(item["overdue_invoices"] for item in metrics),
    )


@router.get("/address/cep/{postal_code}", response_model=CepLookupResponse)
async def lookup_cep(
    client_id: int,
    company_id: int,
    postal_code: str,
    _: Client = Depends(verify_client_or_bearer_api_key),
):
    cep = _digits(postal_code)
    if len(cep) != 8:
        raise HTTPException(status_code=400, detail="CEP deve ter 8 dígitos")

    try:
        payload = await asyncio.to_thread(_fetch_cep_payload, cep)
    except urllib.error.URLError as exc:
        logger.warning("[lookup_cep] falha ao consultar ViaCEP: %s", exc)
        raise HTTPException(status_code=503, detail="Serviço de CEP indisponível no momento")
    except Exception as exc:
        logger.warning("[lookup_cep] resposta inválida do ViaCEP: %s", exc)
        raise HTTPException(status_code=503, detail="Não foi possível consultar o CEP")

    if payload.get("erro"):
        raise HTTPException(status_code=404, detail="CEP não encontrado")

    return CepLookupResponse(
        postal_code=cep,
        address=payload.get("logradouro") or None,
        complement=payload.get("complemento") or None,
        province=payload.get("bairro") or None,
        city=payload.get("localidade") or None,
        state=payload.get("uf") or None,
    )


@router.get("/{customer_id}", response_model=CustomerDetail)
async def get_customer_detail(
    client_id: int,
    company_id: int,
    customer_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key),
):
    customer = db.query(Customer).filter(Customer.id == customer_id, Customer.company_id == company_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    contracts = db.query(Contract).options(joinedload(Contract.items)).filter(
        Contract.company_id == company_id,
        Contract.customer_id == customer_id,
    ).order_by(Contract.created_at.desc()).all()
    invoices = db.query(Invoice).filter(
        Invoice.company_id == company_id,
        Invoice.customer_id == customer_id,
    ).order_by(
        Invoice.due_date.asc().nullslast(),
        Invoice.created_at.asc(),
        Invoice.id.asc(),
    ).limit(80).all()
    payments = db.query(Payment).filter(
        Payment.company_id == company_id,
        Payment.customer_id == customer_id,
    ).order_by(Payment.created_at.desc()).limit(80).all()
    managed_links = db.query(CustomerManagedCompany).options(
        joinedload(CustomerManagedCompany.managed_company),
    ).filter(
        CustomerManagedCompany.owner_company_id == company_id,
        CustomerManagedCompany.customer_id == customer_id,
    ).order_by(CustomerManagedCompany.created_at.desc()).all()

    return CustomerDetail(
        **_customer_list_item(db, customer).model_dump(),
        contracts=[_contract_summary(contract) for contract in contracts],
        invoices=[_invoice_summary(invoice) for invoice in invoices],
        payments=[_payment_summary(payment) for payment in payments],
        managed_companies=_managed_company_summaries(db, managed_links),
    )


@router.put("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    client_id: int,
    company_id: int,
    customer_id: int,
    payload: CustomerUpdate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key),
):
    customer = db.query(Customer).options(joinedload(Customer.contact)).filter(
        Customer.id == customer_id,
        Customer.company_id == company_id,
    ).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        return customer

    try:
        if "name" in update_data and update_data["name"] is not None:
            name = update_data["name"].strip()
            if not name:
                raise HTTPException(status_code=400, detail="Nome do cliente é obrigatório")
            customer.nome = name
            if customer.contact:
                customer.contact.name = name

        if "phone" in update_data and update_data["phone"] is not None:
            phone = update_data["phone"].strip()
            if not phone:
                raise HTTPException(status_code=400, detail="Telefone do cliente é obrigatório")
            existing_customer = db.query(Customer.id).filter(
                Customer.company_id == company_id,
                Customer.telefone == phone,
                Customer.id != customer.id,
            ).first()
            if existing_customer:
                raise HTTPException(status_code=409, detail="Já existe outro cliente com este telefone")
            existing_contact = db.query(Contact.id).filter(
                Contact.client_id == client_id,
                Contact.phone == phone,
                Contact.id != customer.contact_id,
            ).first()
            if existing_contact:
                raise HTTPException(status_code=409, detail="Já existe outro contato com este telefone")
            customer.telefone = phone
            if customer.contact:
                customer.contact.phone = phone

        if "email" in update_data:
            email = update_data["email"]
            customer.email = email.strip() if email and email.strip() else None

        if "status" in update_data and update_data["status"]:
            customer.status = update_data["status"]

        if "categoria" in update_data and update_data["categoria"]:
            customer.categoria = update_data["categoria"]

        if "notes" in update_data:
            customer.observacoes = update_data["notes"]

        _apply_billing_profile(customer, update_data)
        db.flush()

        db.commit()
        db.refresh(customer)
        return _customer_response(customer)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("[update_customer] erro")
        raise HTTPException(status_code=400, detail=str(exc))


def _lock_customer_delete_scope(
    db: Session,
    *,
    client_id: int,
    company_id: int,
    customer_id: int,
) -> Customer:
    """Fence customer deletion against concurrent scope/link mutations."""
    lock_entities_for_mutation(
        db,
        company_ids=[company_id],
        client_ids=[client_id],
    )
    actor = (
        db.query(Client)
        .filter(Client.id == client_id)
        .with_for_update()
        .first()
    )
    if not actor or not actor.is_active:
        raise HTTPException(status_code=423, detail="Acesso suspenso")
    try:
        ensure_company_operational(db, company_id)
    except CompanyOperationallyBlockedError as exc:
        raise HTTPException(status_code=423, detail="Acesso suspenso") from exc

    customer = (
        db.query(Customer)
        .filter(
            Customer.id == customer_id,
            Customer.company_id == company_id,
        )
        .with_for_update()
        .first()
    )
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    managed_link = (
        db.query(CustomerManagedCompany.id)
        .filter(
            CustomerManagedCompany.owner_company_id == company_id,
            CustomerManagedCompany.customer_id == customer_id,
        )
        .with_for_update()
        .first()
    )
    if managed_link:
        raise HTTPException(status_code=400, detail="Cliente com workspace vinculado não pode ser excluído")
    return customer


def _load_deletable_customer_financial_records(
    db: Session,
    *,
    company_id: int,
    customer_id: int,
) -> tuple[List[Contract], List[Invoice]]:
    """Load and lock every financial row, rejecting immutable history."""
    contracts = (
        db.query(Contract)
        .filter(
            Contract.company_id == company_id,
            Contract.customer_id == customer_id,
        )
        .with_for_update()
        .all()
    )
    contract_ids = [contract.id for contract in contracts]

    invoice_query = db.query(Invoice).filter(Invoice.company_id == company_id)
    if contract_ids:
        invoice_query = invoice_query.filter(
            (Invoice.customer_id == customer_id)
            | (Invoice.contract_id.in_(contract_ids))
        )
    else:
        invoice_query = invoice_query.filter(Invoice.customer_id == customer_id)
    invoices = invoice_query.with_for_update().all()
    invoice_ids = [invoice.id for invoice in invoices]

    payment_filters = [Payment.customer_id == customer_id]
    if contract_ids:
        payment_filters.append(Payment.contract_id.in_(contract_ids))
    if invoice_ids:
        payment_filters.append(Payment.invoice_id.in_(invoice_ids))

    payment_count = db.query(func.count(Payment.id)).filter(
        Payment.company_id == company_id,
        or_(*payment_filters),
    ).scalar() or 0
    if payment_count:
        raise HTTPException(
            status_code=400,
            detail="Cliente com pagamento registrado não pode ser excluído",
        )

    blocked_invoice = next(
        (
            invoice
            for invoice in invoices
            if invoice.status not in {"draft", "open", "overdue"}
            or (invoice.amount_paid and invoice.amount_paid > 0)
        ),
        None,
    )
    if blocked_invoice:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cliente com fatura paga, estornada, anulada ou com "
                "histórico financeiro não pode ser excluído"
            ),
        )
    return contracts, invoices


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(
    client_id: int,
    company_id: int,
    customer_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key),
):
    try:
        customer = _lock_customer_delete_scope(
            db,
            client_id=client_id,
            company_id=company_id,
            customer_id=customer_id,
        )
        contracts, invoices = _load_deletable_customer_financial_records(
            db,
            company_id=company_id,
            customer_id=customer_id,
        )
        for invoice in invoices:
            db.delete(invoice)
        for contract in contracts:
            db.delete(contract)
        db.delete(customer)
        db.commit()
        return None
    except HTTPException:
        db.rollback()
        raise
    except (CompanyOperationalLockBusyError, OperationalError):
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("[delete_customer] erro")
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{customer_id}/managed-companies", response_model=List[ManagedCompanySummary])
async def list_customer_managed_companies(
    client_id: int,
    company_id: int,
    customer_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key),
):
    customer = db.query(Customer).filter(Customer.id == customer_id, Customer.company_id == company_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    links = db.query(CustomerManagedCompany).options(
        joinedload(CustomerManagedCompany.managed_company),
    ).filter(
        CustomerManagedCompany.owner_company_id == company_id,
        CustomerManagedCompany.customer_id == customer_id,
    ).order_by(CustomerManagedCompany.created_at.desc()).all()
    return _managed_company_summaries(db, links)


@router.post("/{customer_id}/managed-companies", response_model=ManagedCompanySummary, status_code=status.HTTP_201_CREATED)
async def link_customer_managed_company(
    client_id: int,
    company_id: int,
    customer_id: int,
    payload: ManagedCompanyLinkCreate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key),
):
    managed_company_id = int(payload.managed_company_id)
    lock_entities_for_mutation(
        db,
        company_ids=[company_id, managed_company_id],
        client_ids=[client_id],
    )
    actor = (
        db.query(Client)
        .filter(Client.id == client_id)
        .with_for_update()
        .first()
    )
    if not actor or not actor.is_active:
        raise HTTPException(status_code=423, detail="Acesso suspenso")
    managed_company = (
        db.query(Company)
        .filter(Company.id == managed_company_id)
        .with_for_update()
        .first()
    )
    if not managed_company:
        raise HTTPException(status_code=404, detail="Empresa gerenciada não encontrada")
    try:
        ensure_company_operational(db, company_id)
        ensure_company_operational(db, managed_company_id)
    except CompanyOperationallyBlockedError as exc:
        raise HTTPException(status_code=423, detail="Acesso suspenso") from exc

    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id, Customer.company_id == company_id)
        .with_for_update()
        .first()
    )
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    if managed_company_id == int(company_id):
        raise HTTPException(status_code=400, detail="A empresa gerenciada deve ser diferente da empresa atual")

    access = (
        db.query(ClientCompany)
        .filter(
            ClientCompany.client_id == client_id,
            ClientCompany.company_id == managed_company_id,
        )
        .with_for_update()
        .first()
    )
    if not access:
        raise HTTPException(status_code=403, detail="Este cliente não tem acesso à empresa gerenciada")

    existing_for_owner = (
        db.query(CustomerManagedCompany)
        .filter(
            CustomerManagedCompany.owner_company_id == company_id,
            CustomerManagedCompany.managed_company_id == managed_company_id,
        )
        .with_for_update()
        .first()
    )
    if existing_for_owner:
        if int(existing_for_owner.customer_id) == int(customer_id):
            return _managed_company_summaries(db, [existing_for_owner])[0]
        raise HTTPException(status_code=409, detail="Esta empresa já está vinculada a outro cliente")

    link = CustomerManagedCompany(
        owner_company_id=company_id,
        customer_id=customer_id,
        managed_company_id=managed_company_id,
        created_by_client_id=client_id,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    link.managed_company = managed_company
    return _managed_company_summaries(db, [link])[0]


@router.delete("/{customer_id}/managed-companies/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_customer_managed_company(
    client_id: int,
    company_id: int,
    customer_id: int,
    link_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key),
):
    discovered_link = db.query(CustomerManagedCompany).filter(
        CustomerManagedCompany.id == link_id,
        CustomerManagedCompany.owner_company_id == company_id,
        CustomerManagedCompany.customer_id == customer_id,
    ).first()
    if not discovered_link:
        raise HTTPException(status_code=404, detail="Vínculo não encontrado")

    managed_company_id = int(discovered_link.managed_company_id)
    lock_entities_for_mutation(
        db,
        company_ids=[company_id, managed_company_id],
        client_ids=[client_id],
    )
    actor = (
        db.query(Client)
        .filter(Client.id == client_id)
        .with_for_update()
        .first()
    )
    if not actor or not actor.is_active:
        raise HTTPException(status_code=423, detail="Acesso suspenso")
    try:
        ensure_company_operational(db, company_id)
        ensure_company_operational(db, managed_company_id)
    except CompanyOperationallyBlockedError as exc:
        raise HTTPException(status_code=423, detail="Acesso suspenso") from exc

    link = (
        db.query(CustomerManagedCompany)
        .filter(
            CustomerManagedCompany.id == link_id,
            CustomerManagedCompany.owner_company_id == company_id,
            CustomerManagedCompany.customer_id == customer_id,
            CustomerManagedCompany.managed_company_id == managed_company_id,
        )
        .with_for_update()
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Vínculo não encontrado")

    db.delete(link)
    db.commit()
    return None


@router.post("/{customer_id}/contracts", response_model=ContractSummary, status_code=status.HTTP_201_CREATED)
async def create_customer_contract(
    client_id: int,
    company_id: int,
    customer_id: int,
    payload: CustomerSaleCreate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key),
):
    customer = db.query(Customer).filter(
        Customer.id == customer_id,
        Customer.company_id == company_id,
    ).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    try:
        contract = _build_contract_for_customer(
            db,
            company_id=company_id,
            customer=customer,
            payload=payload,
        )
        db.commit()
        db.refresh(contract)
        return _contract_summary(contract)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("[create_customer_contract] erro")
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/sales/from-lead/{lead_id}", response_model=ContractSummary, status_code=status.HTTP_201_CREATED)
async def create_sale_from_lead(
    client_id: int,
    company_id: int,
    lead_id: int,
    payload: CustomerSaleCreate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key),
):
    lead = db.query(Lead).filter(
        Lead.id == lead_id,
        Lead.company_id == company_id,
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead não encontrado")

    existing_contract = db.query(Contract).filter(
        Contract.company_id == company_id,
        Contract.lead_id == lead_id,
        Contract.status.in_(["active", "paused", "completed"]),
    ).first()
    if existing_contract:
        raise HTTPException(
            status_code=409,
            detail=f"Lead já possui contrato ativo (ID: {existing_contract.id})",
        )

    try:
        customer = ensure_customer_from_lead(db, lead=lead)
        contract = _build_contract_for_customer(
            db,
            company_id=company_id,
            customer=customer,
            payload=payload,
            lead_id=lead.id,
        )
        lead.deal_value = contract.total_value
        db.commit()
        db.refresh(contract)
        return _contract_summary(contract)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("[create_sale_from_lead] erro")
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/sales/from-contact/{contact_id}", response_model=ContractSummary, status_code=status.HTTP_201_CREATED)
async def create_sale_from_contact(
    client_id: int,
    company_id: int,
    contact_id: int,
    payload: CustomerSaleCreate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key),
):
    contact = db.query(Contact).filter(
        Contact.id == contact_id,
        Contact.company_id == company_id,
    ).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")

    lead = db.query(Lead).filter(
        Lead.company_id == company_id,
        Lead.phone == contact.phone,
    ).order_by(Lead.created_at.desc()).first()

    try:
        customer = ensure_customer_from_contact(db, contact=contact, lead=lead)
        contract = _build_contract_for_customer(
            db,
            company_id=company_id,
            customer=customer,
            payload=payload,
            lead_id=lead.id if lead else payload.lead_id,
        )
        if lead:
            lead.deal_value = contract.total_value
        db.commit()
        db.refresh(contract)
        return _contract_summary(contract)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("[create_sale_from_contact] erro")
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/contracts/{contract_id}/generate-next-invoice", response_model=InvoiceSummary, status_code=status.HTTP_201_CREATED)
async def generate_next_invoice(
    client_id: int,
    company_id: int,
    contract_id: int,
    payload: GenerateRecurringInvoiceRequest,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key),
):
    contract = db.query(Contract).options(joinedload(Contract.items)).filter(
        Contract.id == contract_id,
        Contract.company_id == company_id,
    ).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contrato não encontrado")
    if contract.status not in ("active", "paused"):
        raise HTTPException(
            status_code=400,
            detail="Apenas contratos ativos ou pausados podem gerar faturas",
        )
    if not is_recurring_contract(contract):
        raise HTTPException(status_code=400, detail="Contrato não é recorrente")
    if not contract.customer_id:
        raise HTTPException(
            status_code=400,
            detail="Contrato precisa estar vinculado a um cliente para gerar cobrança",
        )

    customer = db.query(Customer).filter(
        Customer.id == contract.customer_id,
        Customer.company_id == company_id,
    ).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente do contrato não encontrado")

    period_start = (
        contract.next_invoice_date
        or contract.billing_anchor_date
        or contract.start_date
    )
    interval = get_contract_billing_interval(contract)
    next_period_start = add_billing_interval(period_start, interval)
    period_end = next_period_start - timedelta(days=1)
    recurrence_key = f"{contract.id}:{period_start.isoformat()}"

    try:
        invoice = create_invoice_for_contract_period(
            db,
            contract=contract,
            issue_date=date.today(),
            due_date=payload.due_date or period_start,
            recurrence_key=recurrence_key,
            period_start=period_start,
            period_end=period_end,
            notes=payload.notes,
        )
        contract.next_invoice_date = next_period_start
        db.commit()
        db.refresh(invoice)
        return _invoice_summary(invoice)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("[generate_next_invoice] erro")
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/contracts/{contract_id}/cancel", response_model=ContractSummary)
async def cancel_contract_as_churn(
    client_id: int,
    company_id: int,
    contract_id: int,
    payload: CancelContractRequest,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key),
):
    contract = db.query(Contract).options(joinedload(Contract.items)).filter(
        Contract.id == contract_id,
        Contract.company_id == company_id,
    ).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contrato não encontrado")
    if contract.status == "canceled":
        raise HTTPException(status_code=400, detail="Contrato já está cancelado")

    pending_invoices = db.query(Invoice).filter(
        Invoice.company_id == company_id,
        Invoice.contract_id == contract.id,
        Invoice.status.in_(["draft", "open", "overdue"]),
    ).all()
    for invoice in pending_invoices:
        invoice.status = "void"

    contract.status = "canceled"
    contract.canceled_at = datetime.now(timezone.utc)
    contract.cancellation_reason = payload.reason
    contract.next_invoice_date = None

    if contract.customer_id:
        active_count = db.query(func.count(Contract.id)).filter(
            Contract.company_id == company_id,
            Contract.customer_id == contract.customer_id,
            Contract.id != contract.id,
            Contract.status.in_(["active", "paused"]),
        ).scalar() or 0
        if active_count == 0:
            customer = db.query(Customer).filter(
                Customer.id == contract.customer_id,
            ).first()
            if customer:
                customer.categoria = "ex_cliente"
                customer.status = "inativo"

    db.commit()
    db.refresh(contract)
    return _contract_summary(contract)
