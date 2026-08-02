import os
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/company_routes_workspace_test.db")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-with-at-least-32-chars")

from backend.models import (
    Client,
    ClientCompany,
    Company,
    Customer,
    CustomerManagedCompany,
    User,
)
from backend.routes import company as company_routes


class FakeQuery:
    def __init__(self, items):
        self.items = list(items)

    def filter(self, *args, **kwargs):
        for expression in args:
            if str(expression).startswith("lower("):
                expected = getattr(getattr(expression, "right", None), "value", None)
                if expected is not None:
                    self.items = [
                        item
                        for item in self.items
                        if str(getattr(item, "email", "") or "").lower() == str(expected)
                    ]
        return self

    def filter_by(self, **kwargs):
        self.items = [
            item
            for item in self.items
            if all(getattr(item, key, None) == value for key, value in kwargs.items())
        ]
        return self

    def order_by(self, *args, **kwargs):
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self.items[0] if self.items else None

    def all(self):
        return list(self.items)

    def scalar(self):
        item = self.first()
        if isinstance(item, tuple):
            return item[0] if item else None
        return item


class FakeDB:
    def __init__(self, *, clients=None, companies=None, customers=None, accounts=None, client_companies=None):
        self.clients = list(clients or [])
        self.companies = list(companies or [])
        self.customers = list(customers or [])
        self.accounts = list(accounts or [])
        self.client_companies = list(client_companies or [])
        self.customer_managed_companies = []
        self.commits = 0
        self.commit_snapshots = []
        self.refreshed = []
        self.next_company_id = 900
        self.next_client_id = 950
        self.next_client_company_id = 1000
        self.next_managed_link_id = 1100

    def query(self, model):
        if model is Client:
            return FakeQuery(self.clients)
        if model is User:
            return FakeQuery([])
        if model is Company:
            return FakeQuery(self.companies)
        if model is Customer:
            return FakeQuery(self.customers)
        if model is ClientCompany:
            return FakeQuery(self.client_companies)
        if model is CustomerManagedCompany:
            return FakeQuery(self.customer_managed_companies)
        if model is Company.operational_status:
            return FakeQuery(
                [
                    getattr(company, "operational_status", None) or "active"
                    for company in self.companies
                ]
            )
        raise AssertionError(f"Modelo inesperado no teste: {model}")

    def execute(self, statement, params):
        pair = (int(params["client_id"]), int(params["company_id"]))
        allowed = any(
            int(link.client_id) == pair[0] and int(link.company_id) == pair[1]
            for link in self.client_companies
        )
        return SimpleNamespace(fetchone=lambda: (1,) if allowed else None)

    def add(self, obj):
        if isinstance(obj, Company):
            if obj.id is None:
                obj.id = self.next_company_id
                self.next_company_id += 1
            self.companies.append(obj)
            return
        if isinstance(obj, Client):
            if obj.id is None:
                obj.id = self.next_client_id
                self.next_client_id += 1
            self.clients.append(obj)
            return
        if isinstance(obj, ClientCompany):
            if obj.id is None:
                obj.id = self.next_client_company_id
                self.next_client_company_id += 1
            self.client_companies.append(obj)
            return
        if isinstance(obj, CustomerManagedCompany):
            if obj.id is None:
                obj.id = self.next_managed_link_id
                self.next_managed_link_id += 1
            self.customer_managed_companies.append(obj)
            return
        raise AssertionError(f"Objeto inesperado no teste: {obj}")

    def delete(self, obj):
        if isinstance(obj, ClientCompany):
            self.client_companies.remove(obj)
            return
        raise AssertionError(f"Objeto inesperado para exclusão no teste: {obj}")

    def commit(self):
        self.commits += 1
        self.commit_snapshots.append(
            {
                "companies": len(self.companies),
                "clients": len(self.clients),
                "client_companies": len(self.client_companies),
                "managed_links": len(self.customer_managed_companies),
            }
        )

    def flush(self):
        return None

    def refresh(self, obj):
        self.refreshed.append(obj)

    def rollback(self):
        return None


@pytest.fixture(autouse=True)
def stub_workspace_onboarding_integrations(monkeypatch):
    monkeypatch.setattr(
        company_routes,
        "create_password_setup_token_for_account",
        lambda *args, **kwargs: SimpleNamespace(reset_url="https://example.test/reset-password?token=test", expires_minutes=60),
    )
    monkeypatch.setattr(
        company_routes,
        "send_password_setup_email",
        lambda *args, **kwargs: SimpleNamespace(sent=True, skipped=False, reason=None),
    )


def _owner_fixture():
    owner_company = Company(
        id=10,
        name="Aluno SaaS",
        cnpj="11111111000191",
        operational_status="active",
    )
    owner_client = Client(
        id=1,
        email="aluno@example.com",
        company_id=owner_company.id,
        ownership_company_id=owner_company.id,
        is_active=True,
    )
    target_client = Client(
        id=2,
        email="cliente@example.com",
        company_id=20,
        ownership_company_id=20,
        is_active=True,
    )
    customer = Customer(
        id=55,
        contact_id=77,
        company_id=owner_company.id,
        nome="Cliente do aluno",
        telefone="27999999999",
        email="cliente@example.com",
    )
    account = SimpleNamespace(id=5)
    owner_access = ClientCompany(client_id=owner_client.id, company_id=owner_company.id)
    return owner_company, owner_client, target_client, customer, account, owner_access


def test_owner_client_can_create_workspace_linked_to_customer(monkeypatch):
    owner_company, owner_client, target_client, customer, account, owner_access = _owner_fixture()
    db = FakeDB(
        clients=[owner_client, target_client],
        companies=[owner_company],
        customers=[customer],
        accounts=[account],
        client_companies=[owner_access],
    )
    monkeypatch.setattr(company_routes, "managed_workspace_trial_credits_for_days", lambda days: Decimal("700"))
    monkeypatch.setattr(
        company_routes,
        "grant_managed_workspace_trial_ai_credits",
        lambda **kwargs: (SimpleNamespace(balance_credits=Decimal("700")), None),
    )

    response = company_routes.create_new_company_admin(
        client_email=target_client.email,
        company_name="Workspace Cliente",
        company_cnpj="12345678000199",
        customer_id=customer.id,
        trial_days=7,
        db=db,
        current_user=owner_client,
    )

    new_company_id = response["company_id"]
    assert response["managed_customer_id"] == customer.id
    assert response["trial_days"] == 7
    assert response["trial_credits_granted"] == 700.0
    assert any(
        int(link.client_id) == int(target_client.id) and int(link.company_id) == int(new_company_id)
        for link in db.client_companies
    )
    assert any(
        int(link.client_id) == int(owner_client.id) and int(link.company_id) == int(new_company_id)
        for link in db.client_companies
    )
    managed_link = db.customer_managed_companies[0]
    assert managed_link.owner_company_id == owner_company.id
    assert managed_link.customer_id == customer.id
    assert managed_link.managed_company_id == new_company_id
    assert managed_link.created_by_client_id == owner_client.id
    assert managed_link.lifecycle_status == "trialing"
    assert response["client_created"] is False
    assert response["password_setup_email_sent"] is False
    assert response["password_setup_email_skipped"] is True
    assert response["password_setup_email_reason"] == "existing_account"
    assert "password_setup_url" not in response
    assert db.commit_snapshots[0]["managed_links"] == 1


def test_workspace_creation_locks_owner_and_existing_target_in_global_order(monkeypatch):
    owner_company, owner_client, target_client, customer, account, owner_access = _owner_fixture()
    db = FakeDB(
        clients=[owner_client, target_client],
        companies=[owner_company],
        customers=[customer],
        accounts=[account],
        client_companies=[owner_access],
    )
    lock_calls = []
    monkeypatch.setattr(
        company_routes,
        "lock_entities_for_mutation",
        lambda _db, **kwargs: lock_calls.append(kwargs),
    )
    monkeypatch.setattr(
        company_routes,
        "managed_workspace_trial_credits_for_days",
        lambda _days: Decimal("0"),
    )

    company_routes.create_new_company_admin(
        client_email=target_client.email,
        company_name="Workspace com fence completo",
        company_cnpj="12345678000199",
        customer_id=customer.id,
        trial_days=0,
        db=db,
        current_user=owner_client,
    )

    assert len(lock_calls) >= 2
    assert set(lock_calls[0]["company_ids"]) == {
        owner_company.id,
        target_client.ownership_company_id,
    }
    assert "client_ids" not in lock_calls[0]
    assert set(lock_calls[1]["client_ids"]) == {
        owner_client.id,
        target_client.id,
    }
    assert "company_ids" not in lock_calls[1]


def test_owner_client_can_create_missing_customer_master_user(monkeypatch):
    owner_company, owner_client, _target_client, customer, account, owner_access = _owner_fixture()
    customer.email = "novo-cliente@example.com"
    customer.cpf = "12345678901"
    setup_token_kwargs = {}
    db = FakeDB(
        clients=[owner_client],
        companies=[owner_company],
        customers=[customer],
        accounts=[account],
        client_companies=[owner_access],
    )
    monkeypatch.setattr(company_routes, "managed_workspace_trial_credits_for_days", lambda days: Decimal("300"))
    monkeypatch.setattr(
        company_routes,
        "grant_managed_workspace_trial_ai_credits",
        lambda **kwargs: (SimpleNamespace(balance_credits=Decimal("300")), None),
    )

    def fake_create_password_setup_token(*args, **kwargs):
        setup_token_kwargs.update(kwargs)
        return SimpleNamespace(
            reset_url="https://example.test/reset-password?token=test",
            expires_minutes=kwargs.get("min_ttl_minutes"),
        )

    monkeypatch.setattr(
        company_routes,
        "create_password_setup_token_for_account",
        fake_create_password_setup_token,
    )

    response = company_routes.create_new_company_admin(
        client_email=customer.email,
        company_name="Workspace Novo Cliente",
        company_cnpj=customer.cpf,
        customer_id=customer.id,
        trial_days=3,
        db=db,
        current_user=owner_client,
    )

    created_client = next(client for client in db.clients if client.email == customer.email)
    assert created_client.company_id == response["company_id"]
    assert created_client.ownership_company_id == response["company_id"]
    assert created_client.password
    assert created_client.billing_profile["full_name"] == customer.nome
    assert created_client.billing_profile["document"] == customer.cpf
    assert response["client_created"] is True
    assert setup_token_kwargs["min_ttl_minutes"] == 3 * 24 * 60
    assert response["password_setup_email_sent"] is True
    assert response["password_setup_email_skipped"] is False
    assert response["password_setup_email_reason"] is None
    assert "password_setup_url" not in response
    assert any(
        int(link.client_id) == int(created_client.id) and int(link.company_id) == int(response["company_id"])
        for link in db.client_companies
    )
    assert any(
        int(link.client_id) == int(owner_client.id) and int(link.company_id) == int(response["company_id"])
        for link in db.client_companies
    )
    assert db.commit_snapshots[0]["managed_links"] == 1


def test_missing_smtp_returns_one_time_password_setup_url(monkeypatch):
    owner_company, owner_client, _target_client, customer, account, owner_access = _owner_fixture()
    customer.email = "novo-cliente@example.com"
    customer.cpf = "12345678901"
    db = FakeDB(
        clients=[owner_client],
        companies=[owner_company],
        customers=[customer],
        accounts=[account],
        client_companies=[owner_access],
    )
    monkeypatch.setattr(
        company_routes,
        "managed_workspace_trial_credits_for_days",
        lambda _days: Decimal("0"),
    )
    monkeypatch.setattr(
        company_routes,
        "send_password_setup_email",
        lambda **_kwargs: SimpleNamespace(
            sent=False,
            skipped=True,
            reason="smtp_not_configured",
        ),
    )

    response = company_routes.create_new_company_admin(
        client_email=customer.email,
        company_name="Workspace sem SMTP",
        company_cnpj=customer.cpf,
        customer_id=customer.id,
        trial_days=0,
        db=db,
        current_user=owner_client,
    )

    assert response["client_created"] is True
    assert response["password_setup_email_sent"] is False
    assert response["password_setup_email_skipped"] is True
    assert response["password_setup_email_reason"] == "smtp_not_configured"
    assert response["password_setup_url"] == (
        "https://example.test/reset-password?token=test"
    )


def test_managed_workspace_uses_immutable_owner_when_context_is_shared(monkeypatch):
    owner_company, owner_client, target_client, customer, account, owner_access = _owner_fixture()
    owner_client.company_id = 30
    db = FakeDB(
        clients=[owner_client, target_client],
        companies=[owner_company],
        customers=[customer],
        accounts=[account],
        client_companies=[owner_access],
    )
    monkeypatch.setattr(
        company_routes,
        "managed_workspace_trial_credits_for_days",
        lambda _days: Decimal("0"),
    )

    response = company_routes.create_new_company_admin(
        client_email=target_client.email,
        company_name="Workspace com contexto compartilhado",
        company_cnpj="12345678000199",
        customer_id=customer.id,
        trial_days=7,
        db=db,
        current_user=owner_client,
    )

    assert response["password_setup_email_reason"] == "existing_account"
    assert db.customer_managed_companies[0].owner_company_id == owner_company.id


def test_select_active_company_does_not_change_ownership_anchor():
    owner_company, owner_client, _target_client, _customer, _account, owner_access = _owner_fixture()
    owner_client.ownership_company_id = owner_company.id
    selected_company = Company(
        id=20,
        name="Contexto compartilhado",
        cnpj="22222222000191",
        operational_status="active",
    )
    selected_access = ClientCompany(client_id=owner_client.id, company_id=selected_company.id)
    db = FakeDB(
        clients=[owner_client],
        companies=[owner_company, selected_company],
        client_companies=[owner_access, selected_access],
    )

    company_routes.select_active_company(
        company_id=selected_company.id,
        db=db,
        user=owner_client,
    )

    assert owner_client.company_id == selected_company.id
    assert owner_client.ownership_company_id == owner_company.id


def test_remove_user_company_rejects_ownership_anchor():
    owner_company, owner_client, _target_client, _customer, _account, owner_access = _owner_fixture()
    owner_client.ownership_company_id = owner_company.id
    db = FakeDB(
        clients=[owner_client],
        companies=[owner_company],
        client_companies=[owner_access],
    )

    with pytest.raises(HTTPException) as exc:
        company_routes.remove_user_company(
            company_id=owner_company.id,
            db=db,
            user=owner_client,
        )

    assert exc.value.status_code == 409
    assert db.client_companies == [owner_access]


def test_remove_user_company_locks_scope_before_unlink(monkeypatch):
    owner_company, owner_client, _target_client, _customer, _account, owner_access = _owner_fixture()
    owner_client.ownership_company_id = owner_company.id
    selected_company = Company(
        id=20,
        name="Contexto exclusivo",
        cnpj="22222222000191",
        operational_status="active",
    )
    selected_access = ClientCompany(
        client_id=owner_client.id,
        company_id=selected_company.id,
    )
    db = FakeDB(
        clients=[owner_client],
        companies=[owner_company, selected_company],
        client_companies=[owner_access, selected_access],
    )
    events = []
    monkeypatch.setattr(
        company_routes,
        "lock_entities_for_mutation",
        lambda _db, **kwargs: events.append(("lock", kwargs)),
    )
    monkeypatch.setattr(
        company_routes,
        "ensure_company_operational",
        lambda _db, company_id: events.append(("operational", company_id)),
    )
    result = company_routes.remove_user_company(
        company_id=selected_company.id,
        db=db,
        user=owner_client,
    )

    assert result["message"].endswith("removido com sucesso.")
    assert db.client_companies == [owner_access]
    assert events == [
        (
            "lock",
            {
                "company_ids": [owner_company.id, selected_company.id],
                "client_ids": [owner_client.id],
            },
        ),
        ("operational", owner_company.id),
        ("operational", selected_company.id),
    ]


def test_owner_workspace_creation_requires_customer_email():
    owner_company, owner_client, _target_client, customer, account, owner_access = _owner_fixture()
    customer.email = None
    db = FakeDB(
        clients=[owner_client],
        companies=[owner_company],
        customers=[customer],
        accounts=[account],
        client_companies=[owner_access],
    )

    with pytest.raises(HTTPException) as exc:
        company_routes.create_new_company_admin(
            client_email="novo-cliente@example.com",
            company_name="Workspace Novo Cliente",
            company_cnpj="12345678901",
            customer_id=customer.id,
            trial_days=3,
            db=db,
            current_user=owner_client,
        )

    assert exc.value.status_code == 400
    assert "e-mail" in exc.value.detail


def test_owner_workspace_creation_blocks_same_email_as_owner():
    owner_company, owner_client, _target_client, customer, account, owner_access = _owner_fixture()
    customer.email = owner_client.email
    db = FakeDB(
        clients=[owner_client],
        companies=[owner_company],
        customers=[customer],
        accounts=[account],
        client_companies=[owner_access],
    )

    with pytest.raises(HTTPException) as exc:
        company_routes.create_new_company_admin(
            client_email=owner_client.email,
            company_name="Workspace Mesmo Email",
            company_cnpj="12345678901",
            customer_id=customer.id,
            trial_days=7,
            db=db,
            current_user=owner_client,
        )

    assert exc.value.status_code == 400
    assert "diferente do seu" in exc.value.detail
    assert db.companies == [owner_company]
    assert db.customer_managed_companies == []


def test_owner_workspace_creation_rechecks_operational_state_after_scope_lock():
    owner_company, owner_client, target_client, customer, account, owner_access = _owner_fixture()
    owner_company.operational_status = "blocked"
    db = FakeDB(
        clients=[owner_client, target_client],
        companies=[owner_company],
        customers=[customer],
        accounts=[account],
        client_companies=[owner_access],
    )

    with pytest.raises(HTTPException) as exc:
        company_routes.create_new_company_admin(
            client_email=target_client.email,
            company_name="Workspace durante bloqueio",
            company_cnpj="12345678000199",
            customer_id=customer.id,
            trial_days=7,
            db=db,
            current_user=owner_client,
        )

    assert exc.value.status_code == 423
    assert db.companies == [owner_company]
    assert db.customer_managed_companies == []
    assert db.commits == 0


def test_owner_workspace_creation_blocks_client_without_access_to_customer_company():
    owner_company, owner_client, target_client, customer, account, _owner_access = _owner_fixture()
    outsider = Client(id=3, email="outro@example.com", company_id=30)
    outsider_access = ClientCompany(client_id=outsider.id, company_id=outsider.company_id)
    db = FakeDB(
        clients=[owner_client, target_client, outsider],
        companies=[owner_company],
        customers=[customer],
        accounts=[account],
        client_companies=[outsider_access],
    )

    with pytest.raises(HTTPException) as exc:
        company_routes.create_new_company_admin(
            client_email=target_client.email,
            company_name="Workspace Cliente",
            company_cnpj="12345678000199",
            customer_id=customer.id,
            trial_days=7,
            db=db,
            current_user=outsider,
        )

    assert exc.value.status_code == 403
    assert db.companies == [owner_company]
    assert db.customer_managed_companies == []


def test_non_admin_without_customer_stays_restricted():
    owner_company, owner_client, target_client, _customer, _account, owner_access = _owner_fixture()
    db = FakeDB(
        clients=[owner_client, target_client],
        companies=[owner_company],
        client_companies=[owner_access],
    )

    with pytest.raises(HTTPException) as exc:
        company_routes.create_new_company_admin(
            client_email=target_client.email,
            company_name="Workspace sem cliente",
            company_cnpj="12345678000199",
            customer_id=None,
            trial_days=0,
            db=db,
            current_user=owner_client,
        )

    assert exc.value.status_code == 403
    assert "administradores internos" in exc.value.detail
