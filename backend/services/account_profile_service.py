"""Helpers for the master account profile."""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from backend.models import Client, User


PROFILE_KEYS = (
    "full_name",
    "email",
    "cellphone",
    "document",
    "postal_code",
    "street",
    "number",
    "neighborhood",
    "complement",
    "state",
    "profile_picture_url",
)

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def only_digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def clean_text(value: Any, *, max_length: int = 255) -> str:
    return " ".join(str(value or "").strip().split())[:max_length]


def is_valid_cpf(value: Any) -> bool:
    digits = only_digits(value)
    if len(digits) != 11 or digits == digits[0] * 11:
        return False

    numbers = [int(char) for char in digits]
    first_sum = sum(numbers[index] * (10 - index) for index in range(9))
    first_digit = 0 if first_sum % 11 < 2 else 11 - (first_sum % 11)
    second_sum = sum(numbers[index] * (11 - index) for index in range(10))
    second_digit = 0 if second_sum % 11 < 2 else 11 - (second_sum % 11)
    return numbers[9] == first_digit and numbers[10] == second_digit


def is_valid_cnpj(value: Any) -> bool:
    digits = only_digits(value)
    if len(digits) != 14 or digits == digits[0] * 14:
        return False

    numbers = [int(char) for char in digits]
    first_weights = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    second_weights = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    first_sum = sum(numbers[index] * first_weights[index] for index in range(12))
    first_digit = 0 if first_sum % 11 < 2 else 11 - (first_sum % 11)
    second_sum = sum(numbers[index] * second_weights[index] for index in range(13))
    second_digit = 0 if second_sum % 11 < 2 else 11 - (second_sum % 11)
    return numbers[12] == first_digit and numbers[13] == second_digit


def clean_optional_email(value: Any, *, fallback_email: Optional[str] = None) -> str:
    email = clean_text(value or fallback_email, max_length=255).lower()
    if email and not EMAIL_RE.match(email):
        raise ValueError("Email inválido")
    return email


def normalize_account_billing_profile(
    payload: Optional[Mapping[str, Any]],
    *,
    fallback_email: Optional[str] = None,
    require_core: bool = False,
    validate_document: bool = True,
) -> dict[str, str]:
    data = payload or {}
    full_name = clean_text(data.get("full_name") or data.get("name"), max_length=120)
    email = clean_optional_email(data.get("email"), fallback_email=fallback_email)
    cellphone = only_digits(data.get("cellphone") or data.get("phone"))[:13]
    document = only_digits(data.get("document") or data.get("cpf_cnpj") or data.get("cnpj"))[:14]
    postal_code = only_digits(data.get("postal_code") or data.get("cep"))[:8]
    state = clean_text(data.get("state") or data.get("uf"), max_length=2).upper()
    profile_picture_url = clean_text(data.get("profile_picture_url"), max_length=500)

    if require_core and not full_name:
        raise ValueError("Nome completo do responsável é obrigatório")
    if require_core and not cellphone:
        raise ValueError("Celular do responsável é obrigatório")

    if cellphone and not 10 <= len(cellphone) <= 13:
        raise ValueError("Celular deve ter entre 10 e 13 dígitos")
    if document and len(document) not in {11, 14}:
        raise ValueError("Documento deve ser CPF ou CNPJ com 11 ou 14 dígitos")
    if validate_document and len(document) == 11 and not is_valid_cpf(document):
        raise ValueError("CPF inválido")
    if validate_document and len(document) == 14 and not is_valid_cnpj(document):
        raise ValueError("CNPJ inválido")
    if postal_code and len(postal_code) != 8:
        raise ValueError("CEP deve ter 8 dígitos")
    if state and (len(state) != 2 or not state.isalpha()):
        raise ValueError("UF deve ter 2 letras")

    return {
        "full_name": full_name,
        "email": email,
        "cellphone": cellphone,
        "document": document,
        "postal_code": postal_code,
        "street": clean_text(data.get("street"), max_length=120),
        "number": clean_text(data.get("number"), max_length=30),
        "neighborhood": clean_text(data.get("neighborhood"), max_length=80),
        "complement": clean_text(data.get("complement"), max_length=120),
        "state": state,
        "profile_picture_url": profile_picture_url,
    }


def fill_account_billing_profile_defaults(profile: Optional[Mapping[str, Any]], *, fallback_email: str) -> dict[str, str]:
    normalized = normalize_account_billing_profile(profile, fallback_email=fallback_email, validate_document=False)
    return {key: normalized.get(key, "") for key in PROFILE_KEYS}


def is_account_billing_profile_complete(profile: Optional[Mapping[str, Any]]) -> bool:
    try:
        normalized = normalize_account_billing_profile(profile)
    except ValueError:
        return False
    return all(normalized.get(key) for key in ("full_name", "email", "cellphone", "document"))


def get_master_client_for_user(db: Any, user: Any) -> Optional[Client]:
    if isinstance(user, Client):
        return user
    if isinstance(user, User):
        return db.query(Client).filter(Client.id == user.client_id).first()
    client_id = getattr(user, "client_id", None)
    if client_id:
        return db.query(Client).filter(Client.id == client_id).first()
    return None
