from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.models import Client, RefundAccessSuspension, User
from backend.services import registration_eligibility_service as service


class FakeQuery:
    def __init__(self, existing=None):
        self.existing = existing

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.existing


class FakeDB:
    def __init__(self, existing=None, existing_user=None, blocked_refund=None):
        self.existing = existing
        self.existing_user = existing_user
        self.blocked_refund = blocked_refund

    def query(self, model):
        if model is RefundAccessSuspension.id:
            return FakeQuery(self.blocked_refund)
        if model is Client:
            return FakeQuery(self.existing)
        if model is User:
            return FakeQuery(self.existing_user)
        raise AssertionError(f"Modelo inesperado no teste: {model}")


def test_registration_eligibility_allows_student_email(monkeypatch):
    monkeypatch.setattr(
        service,
        "verify_registration_purchase",
        lambda email: SimpleNamespace(allowed=True, product_id="course-1", sale_id="sale-1"),
    )

    result = service.ensure_registration_eligibility("student@example.com", FakeDB())

    assert result.allowed is True
    assert result.product_id == "course-1"
    assert result.sale_id == "sale-1"


def test_registration_eligibility_blocks_non_student_email(monkeypatch):
    monkeypatch.setattr(
        service,
        "verify_registration_purchase",
        lambda email: SimpleNamespace(allowed=False, product_id=None, sale_id=None),
    )

    with pytest.raises(HTTPException) as exc:
        service.ensure_registration_eligibility("visitor@example.com", FakeDB())

    assert exc.value.status_code == 403
    assert exc.value.detail == "Cadastro liberado apenas para alunos."


def test_registration_eligibility_rejects_existing_email(monkeypatch):
    monkeypatch.setattr(
        service,
        "verify_registration_purchase",
        lambda email: SimpleNamespace(allowed=True, product_id="course-1", sale_id="sale-1"),
    )

    with pytest.raises(HTTPException) as exc:
        service.ensure_registration_eligibility("student@example.com", FakeDB(existing=SimpleNamespace()))

    assert exc.value.status_code == 400
    assert exc.value.detail == "Email já cadastrado"


def test_registration_eligibility_casefolds_and_rejects_staff_identity(monkeypatch):
    observed = []
    monkeypatch.setattr(
        service,
        "verify_registration_purchase",
        lambda email: observed.append(email),
    )

    with pytest.raises(HTTPException) as exc:
        service.ensure_registration_eligibility(
            "  STAFF@Example.COM  ",
            FakeDB(existing_user=SimpleNamespace()),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Email já cadastrado"
    assert observed == []


def test_registration_eligibility_rejects_refund_tombstone(monkeypatch):
    monkeypatch.setattr(
        service,
        "verify_registration_purchase",
        lambda email: pytest.fail("Compra não deve ser consultada para identidade bloqueada"),
    )

    with pytest.raises(HTTPException) as exc:
        service.ensure_registration_eligibility(
            "student@example.com",
            FakeDB(blocked_refund=1),
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == service.REGISTRATION_STUDENT_ONLY_DETAIL
