"""Cria a primeira empresa e a conta administradora de uma instalação vazia."""

from __future__ import annotations

import argparse
import getpass
import os
import re
import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# O banco é configurado durante o import de ``backend.db``. Carregue o mesmo
# arquivo usado pelo backend antes de importar qualquer módulo da aplicação.
env_file = Path(os.getenv("ENV_FILE", ".env"))
if not env_file.is_absolute():
    env_file = BACKEND_DIR / env_file
load_dotenv(env_file, override=False)

from email_validator import EmailNotValidError, validate_email  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from backend.auth import hash_password  # noqa: E402
from backend.db import SessionLocal  # noqa: E402
from backend.models import BusinessType, Client, ClientCompany, Company  # noqa: E402
from backend.services.company_access_control import normalize_account_email  # noqa: E402


MIN_PASSWORD_LENGTH = 12
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class BootstrapError(RuntimeError):
    """Erro de entrada ou de estado que pode ser corrigido pelo operador."""


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cria a primeira empresa e o administrador master.",
    )
    parser.add_argument("--email", required=True, help="E-mail do administrador")
    parser.add_argument(
        "--company-name",
        required=True,
        help="Nome da primeira empresa",
    )
    parser.add_argument(
        "--document",
        required=True,
        help="CPF ou CNPJ da empresa, somente dígitos",
    )
    parser.add_argument(
        "--password-env",
        help="Nome da variável de ambiente que contém a senha",
    )
    return parser.parse_args(argv)


def _validated_email(raw_email: str) -> str:
    try:
        validated = validate_email(raw_email.strip(), check_deliverability=False)
    except EmailNotValidError as exc:
        raise BootstrapError(f"E-mail inválido: {exc}") from exc
    return normalize_account_email(validated.normalized)


def _validated_company_name(raw_name: str) -> str:
    company_name = raw_name.strip()
    if not company_name:
        raise BootstrapError("O nome da empresa não pode ficar vazio.")
    if len(company_name) > 255:
        raise BootstrapError("O nome da empresa deve ter no máximo 255 caracteres.")
    return company_name


def _validated_document(raw_document: str) -> str:
    document = raw_document.strip()
    if not document.isdigit() or len(document) not in {11, 14}:
        raise BootstrapError("O documento deve conter 11 ou 14 dígitos, sem pontuação.")
    return document


def _read_password(password_env: str | None) -> str:
    if password_env:
        if not ENV_NAME_PATTERN.fullmatch(password_env):
            raise BootstrapError("O nome informado em --password-env é inválido.")
        password = os.getenv(password_env)
        if password is None:
            raise BootstrapError(
                f"A variável de ambiente {password_env} não está definida."
            )
    else:
        password = getpass.getpass("Senha do administrador: ")
        confirmation = getpass.getpass("Confirme a senha: ")
        if password != confirmation:
            raise BootstrapError("As senhas informadas não coincidem.")

    if len(password) < MIN_PASSWORD_LENGTH:
        raise BootstrapError(
            f"A senha deve ter pelo menos {MIN_PASSWORD_LENGTH} caracteres."
        )
    return password


def bootstrap_admin(
    *,
    email: str,
    company_name: str,
    document: str,
    password: str,
) -> tuple[int, int]:
    """Insere a primeira empresa e seu cliente master em uma transação."""

    with SessionLocal() as db:
        try:
            with db.begin():
                existing_client = db.query(Client).filter(Client.email == email).first()
                if existing_client is not None:
                    raise BootstrapError(
                        "Já existe uma conta com esse e-mail; o banco não foi alterado."
                    )

                existing_company = db.query(Company).filter(Company.cnpj == document).first()
                if existing_company is not None:
                    raise BootstrapError(
                        "Já existe uma empresa com esse documento; o banco não foi alterado."
                    )

                business_type = db.get(BusinessType, 1)
                if business_type is None or not business_type.enabled:
                    raise BootstrapError(
                        "O tipo de negócio padrão não existe. Execute 'alembic upgrade head'."
                    )

                company = Company(
                    name=company_name,
                    name_company=company_name,
                    cnpj=document,
                    business_type_id=business_type.id,
                )
                db.add(company)
                db.flush()

                client = Client(
                    email=email,
                    password=hash_password(password),
                    company_id=company.id,
                    ownership_company_id=company.id,
                    api_key=secrets.token_hex(32),
                    billing_profile={},
                    is_active=True,
                )
                db.add(client)
                db.flush()

                db.add(ClientCompany(client_id=client.id, company_id=company.id))
                db.flush()

                return int(company.id), int(client.id)
        except IntegrityError as exc:
            raise BootstrapError(
                "Não foi possível criar a conta porque o e-mail ou documento já existe."
            ) from exc


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        email = _validated_email(args.email)
        company_name = _validated_company_name(args.company_name)
        document = _validated_document(args.document)
        password = _read_password(args.password_env)
        company_id, client_id = bootstrap_admin(
            email=email,
            company_name=company_name,
            document=document,
            password=password,
        )
    except (BootstrapError, EOFError, KeyboardInterrupt) as exc:
        message = str(exc).strip() or "Operação cancelada."
        print(f"Erro: {message}", file=sys.stderr)
        return 1

    print("Primeiro administrador criado com sucesso.")
    print(f"Empresa: {company_name} (ID {company_id})")
    print(f"Conta: {email} (ID {client_id})")
    print("A senha e a chave de API não foram exibidas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
