"""Shared helpers for local customer revenue and billing workflows."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any, Iterable, Optional

from dateutil.relativedelta import relativedelta
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models import Contact, Customer, Lead
from backend.models.revenue_models import (
    Contract,
    ContractItem,
    Invoice,
    InvoiceLineItem,
    Payment,
)


RECURRING_INTERVALS = {
    "weekly",
    "biweekly",
    "monthly",
    "bimonthly",
    "quarterly",
    "semiannually",
    "yearly",
}
MONEY_PLACES = Decimal("0.01")


def to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    return Decimal(str(value))


def money_quantize(value: Decimal) -> Decimal:
    return Decimal(value or 0).quantize(MONEY_PLACES)


def split_money_amount(total: Decimal, parts: int) -> list[Decimal]:
    count = max(int(parts or 1), 1)
    amount = money_quantize(Decimal(total or 0))
    base = (amount / Decimal(count)).quantize(MONEY_PLACES, rounding=ROUND_DOWN)
    amounts = [base for _ in range(count)]
    remainder_cents = int(((amount - (base * count)) * 100).to_integral_value())
    for index in range(max(remainder_cents, 0)):
        amounts[index] = money_quantize(amounts[index] + MONEY_PLACES)
    return amounts


def calculate_item_total(item: Any) -> Decimal:
    quantity = Decimal(str(getattr(item, "quantity", 1) or 1))
    unit_price = to_decimal(getattr(item, "unit_price", 0))
    discount_percent = to_decimal(getattr(item, "discount_percent", 0))
    discount_amount = to_decimal(getattr(item, "discount_amount", 0))

    subtotal = quantity * unit_price
    if discount_percent:
        subtotal = subtotal * (Decimal("1") - discount_percent / Decimal("100"))
    if discount_amount:
        subtotal -= discount_amount

    return max(subtotal, Decimal("0"))


def add_billing_interval(start: date, interval: str, interval_count: int = 1) -> date:
    count = max(interval_count if interval_count is not None else 1, 0)
    if interval == "weekly":
        return start + relativedelta(weeks=count)
    if interval == "biweekly":
        return start + relativedelta(weeks=2 * count)
    if interval == "monthly":
        return start + relativedelta(months=count)
    if interval == "bimonthly":
        return start + relativedelta(months=2 * count)
    if interval == "quarterly":
        return start + relativedelta(months=3 * count)
    if interval == "semiannually":
        return start + relativedelta(months=6 * count)
    if interval == "yearly":
        return start + relativedelta(years=count)
    return start


def get_contract_billing_interval(contract: Contract) -> str:
    for item in contract.items or []:
        if item.billing_interval in RECURRING_INTERVALS:
            return item.billing_interval
    return "once"


def is_recurring_contract(contract: Contract) -> bool:
    return get_contract_billing_interval(contract) != "once"


def monthly_recurring_amount(contract: Contract) -> Decimal:
    total = Decimal("0")
    for item in contract.items or []:
        if item.billing_interval == "weekly":
            total += item.total_price * Decimal("52") / Decimal("12")
        elif item.billing_interval == "biweekly":
            total += item.total_price * Decimal("26") / Decimal("12")
        elif item.billing_interval == "monthly":
            total += item.total_price
        elif item.billing_interval == "bimonthly":
            total += item.total_price / Decimal("2")
        elif item.billing_interval == "quarterly":
            total += item.total_price / Decimal("3")
        elif item.billing_interval == "semiannually":
            total += item.total_price / Decimal("6")
        elif item.billing_interval == "yearly":
            total += item.total_price / Decimal("12")
    return total.quantize(MONEY_PLACES)


def generate_invoice_number(db: Session, company_id: int) -> str:
    year = datetime.now(timezone.utc).year
    count = db.query(func.count(Invoice.id)).filter(
        Invoice.company_id == company_id,
        func.extract("year", Invoice.created_at) == year,
    ).scalar() or 0
    return f"INV-{year}-{str(count + 1).zfill(6)}"


def ensure_customer_from_contact(
    db: Session,
    *,
    contact: Contact,
    lead: Optional[Lead] = None,
    created_by: Optional[int] = None,
) -> Customer:
    customer = db.query(Customer).filter(
        Customer.company_id == contact.company_id,
        Customer.contact_id == contact.id,
    ).first()

    if not customer:
        customer = db.query(Customer).filter(
            Customer.company_id == contact.company_id,
            Customer.telefone == contact.phone,
        ).first()

    if customer:
        if customer.status != "ativo":
            customer.status = "ativo"
        if customer.categoria != "cliente":
            customer.categoria = "cliente"
        if lead and not customer.convertido_de_lead_id:
            customer.convertido_de_lead_id = lead.id
        return customer

    customer = Customer(
        contact_id=contact.id,
        company_id=contact.company_id,
        nome=contact.name or (lead.name if lead else None) or "Nome não informado",
        telefone=contact.phone,
        convertido_de_lead_id=lead.id if lead else None,
        convertido_em=datetime.now(timezone.utc),
        criado_por=created_by,
        categoria="cliente",
        status="ativo",
    )
    db.add(customer)
    db.flush()
    return customer


def ensure_customer_from_lead(
    db: Session,
    *,
    lead: Lead,
    created_by: Optional[int] = None,
) -> Customer:
    if not lead.phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lead precisa ter telefone para virar cliente",
        )

    contact = db.query(Contact).filter(
        Contact.company_id == lead.company_id,
        Contact.phone == lead.phone,
    ).first()

    if not contact:
        contact = Contact(
            client_id=lead.client_id,
            company_id=lead.company_id,
            phone=lead.phone,
            name=lead.name or "Nome não informado",
            photo=lead.thumbnail_url,
        )
        db.add(contact)
        db.flush()

    return ensure_customer_from_contact(
        db,
        contact=contact,
        lead=lead,
        created_by=created_by,
    )


def create_invoice_for_contract_period(
    db: Session,
    *,
    contract: Contract,
    contract_items: Optional[Iterable[ContractItem]] = None,
    issue_date: Optional[date] = None,
    due_date: Optional[date] = None,
    recurrence_key: Optional[str] = None,
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    notes: Optional[str] = None,
    installment_number: Optional[int] = None,
    installment_count: int = 1,
) -> Invoice:
    if recurrence_key:
        existing = db.query(Invoice).filter(
            Invoice.company_id == contract.company_id,
            Invoice.contract_id == contract.id,
            Invoice.recurrence_key == recurrence_key,
        ).first()
        if existing:
            return existing

    items = list(contract_items or contract.items or [])
    installments = max(int(installment_count or 1), 1)
    is_installment = installments > 1
    if is_installment and (
        not installment_number
        or installment_number < 1
        or installment_number > installments
    ):
        raise HTTPException(status_code=400, detail="Parcela inválida para a fatura")

    line_amounts: list[tuple[ContractItem, Decimal]] = []
    for item in items:
        if is_installment:
            amount = split_money_amount(item.total_price, installments)[installment_number - 1]
        else:
            amount = money_quantize(item.total_price)
        line_amounts.append((item, amount))

    subtotal = money_quantize(
        sum((amount for _, amount in line_amounts), Decimal("0"))
    )
    extra_data = {
        "source": "customer_management",
        "period_start": period_start.isoformat() if period_start else None,
        "period_end": period_end.isoformat() if period_end else None,
    }
    if is_installment:
        extra_data.update(
            {
                "installment_number": installment_number,
                "installments": installments,
                "installment_amount": str(subtotal),
                "contract_total": str(
                    money_quantize(
                        sum((item.total_price for item in items), Decimal("0"))
                    )
                ),
            }
        )

    invoice = Invoice(
        company_id=contract.company_id,
        contract_id=contract.id,
        contact_id=contract.contact_id,
        customer_id=contract.customer_id,
        invoice_number=generate_invoice_number(db, contract.company_id),
        recurrence_key=recurrence_key,
        status="open",
        issue_date=issue_date or date.today(),
        due_date=due_date,
        subtotal=subtotal,
        discount_amount=Decimal("0"),
        tax_amount=Decimal("0"),
        total=subtotal,
        amount_paid=Decimal("0"),
        currency=contract.currency,
        payment_method=contract.payment_method,
        notes=notes,
        extra_data=extra_data,
    )
    db.add(invoice)
    db.flush()

    for item, line_total in line_amounts:
        line_type = (
            "subscription"
            if item.billing_interval in RECURRING_INTERVALS
            else "one_time"
        )
        description = item.description
        if is_installment:
            description = f"{description} - parcela {installment_number}/{installments}"
        line = InvoiceLineItem(
            invoice_id=invoice.id,
            contract_item_id=item.id,
            plan_id=item.plan_id,
            description=description,
            quantity=1 if is_installment else item.quantity,
            unit_price=line_total if is_installment else item.unit_price,
            discount_amount=Decimal("0") if is_installment else item.discount_amount,
            total=line_total,
            type=line_type,
            period_start=period_start if line_type == "subscription" else None,
            period_end=period_end if line_type == "subscription" else None,
        )
        db.add(line)

    return invoice


def register_manual_payment(
    db: Session,
    *,
    invoice: Invoice,
    amount: Decimal,
    payment_method: Optional[str],
    payment_date: Optional[datetime] = None,
    notes: Optional[str] = None,
) -> Payment:
    payment = Payment(
        company_id=invoice.company_id,
        invoice_id=invoice.id,
        contract_id=invoice.contract_id,
        contact_id=invoice.contact_id,
        customer_id=invoice.customer_id,
        type="payment",
        status="succeeded",
        amount=amount,
        currency=invoice.currency,
        payment_method=payment_method or invoice.payment_method,
        payment_date=payment_date or datetime.now(timezone.utc),
        gateway="manual",
        notes=notes,
    )
    db.add(payment)

    invoice.amount_paid = invoice.amount_paid + amount
    if invoice.amount_paid >= invoice.total:
        invoice.status = "paid"
        invoice.paid_at = payment.payment_date

    if invoice.contract_id:
        contract = db.query(Contract).filter(Contract.id == invoice.contract_id).first()
        if contract:
            contract.total_paid = contract.total_paid + amount
            if (
                contract.total_paid >= contract.total_value
                and not is_recurring_contract(contract)
            ):
                contract.status = "completed"

    return payment


def advance_contract_next_invoice_date(
    contract: Contract,
    current_period_start: date,
) -> tuple[date, date]:
    interval = get_contract_billing_interval(contract)
    next_period_start = add_billing_interval(current_period_start, interval)
    period_end = next_period_start - timedelta(days=1)
    contract.next_invoice_date = next_period_start
    return next_period_start, period_end
