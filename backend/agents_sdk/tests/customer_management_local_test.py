import os
from datetime import datetime, timezone


os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/customer-management-local-test.db")
os.environ.setdefault("ENVIRONMENT", "development")

from backend.models import Customer
from backend.routes import company as company_routes
from backend.routes import customer_management_routes as routes


def _customer():
    customer = Customer(
        id=31,
        contact_id=41,
        company_id=7,
        nome="Cliente Exemplo",
        telefone="27999999999",
        email="cliente@example.test",
        status="ativo",
        categoria="cliente",
        dados_adicionais={},
    )
    customer.created_at = datetime.now(timezone.utc)
    customer.updated_at = datetime.now(timezone.utc)
    return customer


def test_customer_profile_is_stored_under_neutral_billing_key():
    customer = _customer()

    routes._apply_billing_profile(
        customer,
        {
            "cpf_cnpj": "123.456.789-00",
            "mobile_phone": "27988888888",
            "postal_code": "29000-000",
            "city": "Vitória",
            "state": "ES",
        },
    )

    assert customer.cpf == "12345678900"
    assert customer.dados_adicionais == {
        "billing_profile": {
            "cpf_cnpj": "12345678900",
            "mobile_phone": "27988888888",
            "postal_code": "29000-000",
            "city": "Vitória",
            "state": "ES",
            "name": "Cliente Exemplo",
            "phone": "27999999999",
            "email": "cliente@example.test",
        }
    }


def test_workspace_profile_reuses_local_customer_contact_data():
    customer = _customer()
    customer.dados_adicionais = {
        "billing_profile": {"mobile_phone": "27988888888"}
    }

    profile = company_routes.managed_workspace_client_profile(
        customer=customer,
        email="cliente@example.test",
        document="12345678900",
    )

    assert profile["full_name"] == "Cliente Exemplo"
    assert profile["mobile_phone"] == "27988888888"
