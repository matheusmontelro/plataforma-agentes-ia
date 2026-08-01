from types import SimpleNamespace

import pytest

from backend.services import brevo_email_service as service


@pytest.fixture(autouse=True)
def _public_app_url(monkeypatch):
    monkeypatch.setenv("BREVO_PUBLIC_APP_URL", "https://app.example.com")


class FakeResponse:
    status_code = 201

    def json(self):
        return {"messageId": "msg-1"}


def test_send_master_welcome_email_posts_brevo_template_payload(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "brevo-key")
    monkeypatch.setenv("BREVO_SENDER_EMAIL", "contato@example.com")
    monkeypatch.setenv("BREVO_SENDER_NAME", "Empresa Exemplo")
    monkeypatch.setenv("BREVO_WELCOME_TEMPLATE_ID", "101")
    monkeypatch.setenv("BREVO_CONTACT_LIST_ID", "9")

    calls = []

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr(service.requests, "post", fake_post)

    result = service.send_master_welcome_email(
        SimpleNamespace(email="owner@example.com", billing_profile={"full_name": "Owner Name"}),
        company_name="Acme",
    )

    assert result.sent is True
    assert calls[0]["url"].endswith("/contacts")
    assert calls[0]["json"]["listIds"] == [9]
    assert calls[1]["url"].endswith("/smtp/email")
    assert calls[1]["headers"]["api-key"] == "brevo-key"
    assert calls[1]["json"]["sender"] == {"email": "contato@example.com", "name": "Empresa Exemplo"}
    assert calls[1]["json"]["to"] == [{"email": "owner@example.com", "name": "Owner Name"}]
    assert calls[1]["json"]["templateId"] == 101
    assert calls[1]["json"]["params"]["login_url"] == "https://app.example.com/login"


def test_send_template_email_skips_without_required_config(monkeypatch):
    monkeypatch.delenv("BREVO_API_KEY", raising=False)
    monkeypatch.delenv("BREVO_SENDER_EMAIL", raising=False)

    result = service.send_brevo_template_email(
        to_email="owner@example.com",
        to_name="Owner",
        template_id=101,
        params={},
    )

    assert result.sent is False
    assert result.skipped is True
    assert result.reason == "brevo_not_configured"


def test_send_managed_workspace_welcome_email_posts_template_payload(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "brevo-key")
    monkeypatch.setenv("BREVO_SENDER_EMAIL", "contato@example.com")
    monkeypatch.setenv("BREVO_SENDER_NAME", "Empresa Exemplo")
    monkeypatch.setenv("BREVO_MANAGED_WORKSPACE_WELCOME_TEMPLATE_ID", "303")

    calls = []

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr(service.requests, "post", fake_post)

    result = service.send_managed_workspace_welcome_email(
        SimpleNamespace(email="cliente@example.com", billing_profile={"full_name": "Cliente Final"}),
        workspace_name="Workspace Cliente",
        owner_company_name="Aluno SaaS",
        owner_email="aluno@example.com",
        trial_days=7,
        trial_credits=1000,
        password_setup_url="https://app.example.com/reset-password?token=test",
        password_setup_expires_minutes=60,
    )

    assert result.sent is True
    assert calls[0]["url"].endswith("/contacts")
    assert calls[1]["url"].endswith("/smtp/email")
    assert calls[1]["json"]["templateId"] == 303
    assert calls[1]["json"]["params"]["workspace_name"] == "Workspace Cliente"
    assert calls[1]["json"]["params"]["owner_company_name"] == "Aluno SaaS"
    assert calls[1]["json"]["params"]["password_setup_expires_minutes"] == 60


def test_send_ai_credit_purchase_email_uses_purchase_template(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "brevo-key")
    monkeypatch.setenv("BREVO_SENDER_EMAIL", "contato@example.com")
    monkeypatch.setenv("BREVO_SENDER_NAME", "Empresa Exemplo")
    monkeypatch.setenv("BREVO_AI_CREDIT_PURCHASE_TEMPLATE_ID", "205")

    calls = []

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr(service.requests, "post", fake_post)

    result = service.send_ai_credit_purchase_email(
        to_email="owner@example.com",
        to_name="Owner Name",
        company_name="Acme",
        package_name="Essencial",
        credits="50000",
        price="R$ 97,00",
        balance_after="75000",
        order_id="aic-1-essential-test",
    )

    assert result.sent is True
    assert calls[0]["url"].endswith("/smtp/email")
    assert calls[0]["json"]["templateId"] == 205
    assert calls[0]["json"]["params"] == {
        "email": "owner@example.com",
        "name": "Owner Name",
        "company_name": "Acme",
        "package_name": "Essencial",
        "credits": "50000",
        "price": "R$ 97,00",
        "balance_after": "75000",
        "order_id": "aic-1-essential-test",
        "credits_url": "https://app.example.com/company/ai-credits",
    }
