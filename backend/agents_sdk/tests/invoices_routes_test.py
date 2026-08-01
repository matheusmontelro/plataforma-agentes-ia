import asyncio
import os
from datetime import date, datetime, timezone
from decimal import Decimal


os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/invoices-routes-test.db")
os.environ.setdefault("ENVIRONMENT", "development")

from backend.models import Client
from backend.models.revenue_models import Invoice, InvoiceLineItem, Payment
from backend.routes import invoices_routes as routes


class _Query:
    def __init__(self, value=None, scalar_value=0):
        self.value = value
        self.scalar_value = scalar_value

    def options(self, *_args, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.value

    def all(self):
        return []

    def scalar(self):
        return self.scalar_value


class _DB:
    def __init__(self, invoice=None):
        self.invoice = invoice
        self.added = []
        self.commits = 0

    def query(self, model):
        if model is Invoice:
            return _Query(self.invoice)
        return _Query(scalar_value=0)

    def add(self, value):
        if isinstance(value, Invoice) and value.id is None:
            value.id = 101
        if isinstance(value, InvoiceLineItem) and value.id is None:
            value.id = 201
        self.added.append(value)

    def flush(self):
        return None

    def commit(self):
        self.commits += 1

    def refresh(self, _value):
        return None

    def rollback(self):
        return None


def _invoice(**overrides):
    values = {
        "id": 7,
        "company_id": 11,
        "invoice_number": "INV-2026-000001",
        "status": "open",
        "issue_date": date(2026, 8, 1),
        "subtotal": Decimal("120.00"),
        "discount_amount": Decimal("0"),
        "tax_amount": Decimal("0"),
        "total": Decimal("120.00"),
        "amount_paid": Decimal("0"),
        "currency": "BRL",
        "extra_data": {},
    }
    values.update(overrides)
    invoice = Invoice(**values)
    invoice.created_at = overrides.get("created_at") or datetime.now(timezone.utc)
    invoice.updated_at = overrides.get("updated_at") or datetime.now(timezone.utc)
    return invoice


def test_invoice_payload_is_provider_neutral():
    assert "installments" not in routes.InvoiceCreate.model_fields
    assert "terms" not in routes.InvoiceCreate.model_fields


def test_invoice_list_response_keeps_generic_external_id():
    invoice = _invoice(external_id="external-payment-42")

    response = routes.invoice_list_response(invoice)

    assert response.external_id == "external-payment-42"
    assert response.installments == 1


def test_create_invoice_stays_local_and_open(monkeypatch):
    db = _DB()
    payload = routes.InvoiceCreate(
        due_date=date(2026, 8, 10),
        payment_method="pix",
        line_items=[
            routes.InvoiceLineItemCreate(
                description="Mensalidade",
                quantity=1,
                unit_price=Decimal("120.00"),
            )
        ],
    )

    async def _return_created(*_args, **_kwargs):
        return next(value for value in db.added if isinstance(value, Invoice))

    monkeypatch.setattr(routes, "obter_fatura", _return_created)

    created = asyncio.run(
        routes.criar_fatura(
            client_id=3,
            company_id=11,
            payload=payload,
            db=db,
            _=Client(id=3),
        )
    )

    assert created.status == "open"
    assert created.external_id is None
    assert db.commits == 1


def test_mark_paid_creates_manual_payment(monkeypatch):
    invoice = _invoice()
    db = _DB(invoice=invoice)

    async def _return_paid(*_args, **_kwargs):
        return invoice

    monkeypatch.setattr(routes, "obter_fatura", _return_paid)

    result = asyncio.run(
        routes.marcar_fatura_paga(
            client_id=3,
            company_id=11,
            invoice_id=invoice.id,
            payload=routes.MarkPaidRequest(payment_method="pix"),
            db=db,
            _=Client(id=3),
        )
    )

    payments = [value for value in db.added if isinstance(value, Payment)]
    assert result.status == "paid"
    assert len(payments) == 1
    assert payments[0].gateway == "manual"
    assert payments[0].amount == Decimal("120.00")
