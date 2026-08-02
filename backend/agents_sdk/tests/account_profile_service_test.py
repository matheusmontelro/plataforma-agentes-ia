import pytest

from backend.services.account_profile_service import (
    is_account_billing_profile_complete,
    is_valid_cnpj,
    is_valid_cpf,
    normalize_account_billing_profile,
)


def test_normalize_account_billing_profile_accepts_cpf_or_cnpj():
    cpf_profile = normalize_account_billing_profile(
        {
            "full_name": "  Pessoa de Exemplo   Ferreira ",
            "email": "MASTER@EXAMPLE.COM",
            "cellphone": "(11) 98888-7777",
            "document": "123.456.789-09",
        },
        require_core=True,
    )
    cnpj_profile = normalize_account_billing_profile({"document": "12.345.678/0001-95"})

    assert cpf_profile["full_name"] == "Pessoa de Exemplo Ferreira"
    assert cpf_profile["email"] == "master@example.com"
    assert cpf_profile["cellphone"] == "11988887777"
    assert cpf_profile["document"] == "12345678909"
    assert cnpj_profile["document"] == "12345678000195"


def test_normalize_account_billing_profile_rejects_invalid_document():
    with pytest.raises(ValueError, match="Documento"):
        normalize_account_billing_profile({"document": "123"}, require_core=False)
    with pytest.raises(ValueError, match="CPF"):
        normalize_account_billing_profile({"document": "111.111.111-11"}, require_core=False)
    with pytest.raises(ValueError, match="CNPJ"):
        normalize_account_billing_profile({"document": "12.345.678/0001-09"}, require_core=False)


def test_document_validators_check_digits():
    assert is_valid_cpf("123.456.789-09") is True
    assert is_valid_cpf("123.456.789-00") is False
    assert is_valid_cnpj("12.345.678/0001-95") is True
    assert is_valid_cnpj("12.345.678/0001-09") is False


def test_normalize_account_billing_profile_preserves_profile_picture_url():
    profile = normalize_account_billing_profile(
        {
            "document": "123.456.789-09",
            "profile_picture_url": "/media/account-profiles/client_1_avatar.webp",
        },
        require_core=False,
    )

    assert profile["profile_picture_url"] == "/media/account-profiles/client_1_avatar.webp"


def test_account_billing_profile_completion_requires_core_fields():
    assert is_account_billing_profile_complete(
        {
            "full_name": "Cliente Exemplo",
            "email": "master@example.com",
            "cellphone": "11988887777",
            "document": "12345678909",
        }
    ) is True
    assert is_account_billing_profile_complete({"full_name": "Cliente Exemplo"}) is False
