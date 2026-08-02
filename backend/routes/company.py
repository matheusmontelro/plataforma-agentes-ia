from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from backend.db import get_db
from backend.auth import (
    ensure_managed_workspace_access,
    ensure_user_can_access_company,
    get_current_user,
    get_managed_workspace_trial_state,
    hash_password,
    refresh_managed_workspace_lifecycle,
)
from backend.models import AICreditWallet, Company, ClientCompany, Client, Customer, CustomerManagedCompany, User
from backend.services.ai_usage_service import (
    grant_managed_workspace_trial_ai_credits,
    managed_workspace_trial_credits_for_days,
)
from backend.services.password_reset_service import create_password_setup_token_for_account
from backend.services.company_access_control import (
    AccountEmailCollisionError,
    CompanyOperationallyBlockedError,
    IdentityOperationBusyError,
    IdentityOperationReservation,
    account_identity_operation_lock,
    account_identity_operation_reservation,
    ensure_company_operational,
    lock_and_resolve_account_email_identity,
    lock_entities_for_mutation,
    normalize_account_email,
)
from backend.services.transactional_email_service import send_password_setup_email
from contextlib import ExitStack, contextmanager
import os
import logging
import secrets
from pathlib import Path
from typing import Iterator, List, Optional
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

router = APIRouter()

COMPANY_LOGO_DIR = os.getenv(
    "COMPANY_LOGO_DIR",
    str(Path(__file__).resolve().parents[1] / "static" / "logos"),
)
COMPANY_LOGO_PUBLIC_PREFIX = os.getenv(
    "COMPANY_LOGO_PUBLIC_PREFIX",
    f"{os.getenv('PUBLIC_BASE_URL', 'http://127.0.0.1:8002').rstrip('/')}/media/logos",
)
ALLOWED_LOGO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
WORKSPACE_OWNER_EMAIL_CONFLICT_MESSAGE = "Use um e-mail diferente do seu para o cliente final."


def require_internal_admin(user = Depends(get_current_user)):
    if is_internal_admin(user):
        return user

    raise HTTPException(status_code=403, detail="Acesso restrito a administradores internos")


def internal_admin_emails() -> set[str]:
    return {
        normalize_account_email(email)
        for email in os.getenv("ADMIN_EMAILS", "").split(",")
        if email.strip()
    }


def is_internal_admin(user) -> bool:
    admin_emails = internal_admin_emails()
    email = normalize_account_email(getattr(user, "email", ""))
    if not admin_emails or email not in admin_emails:
        return False

    if isinstance(user, Client):
        return True

    if isinstance(user, User) and user.role == "admin" and admin_emails and normalize_account_email(user.email) in admin_emails:
        return True

    return False


def actor_client_id(user) -> Optional[int]:
    if isinstance(user, Client):
        return int(user.id)
    value = getattr(user, "client_id", None)
    return int(value) if value is not None else None


def ensure_client_company_link(db: Session, *, client_id: int, company_id: int) -> ClientCompany:
    link = db.query(ClientCompany).filter_by(client_id=client_id, company_id=company_id).first()
    if link:
        return link

    link = ClientCompany(client_id=client_id, company_id=company_id)
    db.add(link)
    return link


def normalize_workspace_email(value: str) -> str:
    email = normalize_account_email(value)
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Cadastre um e-mail válido para criar o workspace do cliente.")
    return email


def normalize_optional_workspace_email(value: Optional[str]) -> str:
    return normalize_account_email(value or "")


def clean_workspace_document(value: str) -> str:
    document = "".join(char for char in str(value or "") if char.isdigit())
    if len(document) not in {11, 14}:
        raise HTTPException(status_code=400, detail="Informe um CPF ou CNPJ válido para o workspace.")
    return document


def managed_workspace_client_profile(
    *,
    customer: Customer,
    email: str,
    document: str,
) -> dict:
    profile = {
        "full_name": customer.nome,
        "email": email,
        "document": document,
        "phone": customer.telefone,
    }
    extra = customer.dados_adicionais if isinstance(customer.dados_adicionais, dict) else {}
    billing_profile = extra.get("billing_profile") if isinstance(extra, dict) else None
    if isinstance(billing_profile, dict):
        mobile_phone = billing_profile.get("mobile_phone")
        if mobile_phone:
            profile["mobile_phone"] = mobile_phone
    return {key: value for key, value in profile.items() if value}


def rollback_if_available(db: Session) -> None:
    rollback = getattr(db, "rollback", None)
    if callable(rollback):
        rollback()


def identity_operation_busy_http(
    exc: IdentityOperationBusyError,
) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="Operação temporariamente indisponível. Tente novamente.",
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


@contextmanager
def managed_workspace_account_identity_locks(
    db: Session,
    emails: List[str],
    *,
    reservation: IdentityOperationReservation,
) -> Iterator[None]:
    normalized_emails = sorted(
        {
            normalized
            for email in emails
            if (normalized := normalize_account_email(email))
        }
    )
    with ExitStack() as stack:
        for email in normalized_emails:
            stack.enter_context(
                account_identity_operation_lock(
                    db,
                    email,
                    reservation=reservation,
                )
            )
        yield


def revalidate_managed_workspace_password_setup(
    db: Session,
    *,
    owner_company_id: int,
    managed_company_id: int,
    customer_id: int,
    managed_link_id: int,
    recipient_client_id: int,
    recipient_email: str,
    owner_client_ids: List[int],
) -> tuple[Client, Company, Company, CustomerManagedCompany] | None:
    lock_entities_for_mutation(
        db,
        company_ids=[int(owner_company_id), int(managed_company_id)],
        client_ids=[
            int(recipient_client_id),
            *(int(value) for value in owner_client_ids),
        ],
    )
    expire_all = getattr(db, "expire_all", None)
    if callable(expire_all):
        expire_all()

    owner_company = (
        db.query(Company)
        .filter_by(id=int(owner_company_id))
        .with_for_update()
        .first()
    )
    managed_company = (
        db.query(Company)
        .filter_by(id=int(managed_company_id))
        .with_for_update()
        .first()
    )
    recipient_client = (
        db.query(Client)
        .filter_by(
            id=int(recipient_client_id),
            email=normalize_account_email(recipient_email),
        )
        .with_for_update()
        .first()
    )
    owner_id_set = {int(value) for value in owner_client_ids}
    owner_clients = [
        owner_client
        for owner_client in (
            db.query(Client)
            .filter(Client.id.in_(sorted(owner_id_set)))
            .order_by(Client.id)
            .with_for_update()
            .all()
        )
        if int(owner_client.id) in owner_id_set
    ]
    managed_link = (
        db.query(CustomerManagedCompany)
        .filter_by(
            id=int(managed_link_id),
            owner_company_id=int(owner_company_id),
            managed_company_id=int(managed_company_id),
            customer_id=int(customer_id),
        )
        .with_for_update()
        .first()
    )
    if (
        not owner_company
        or owner_company.operational_status != "active"
        or not managed_company
        or managed_company.operational_status != "active"
        or not recipient_client
        or not bool(recipient_client.is_active)
        or len(owner_clients) != len(owner_id_set)
        or any(not bool(owner_client.is_active) for owner_client in owner_clients)
        or not managed_link
        or managed_link.lifecycle_status not in {"active", "trialing"}
    ):
        return None

    ensure_company_operational(db, int(owner_company_id))
    ensure_company_operational(db, int(managed_company_id))
    return recipient_client, owner_company, managed_company, managed_link


def run_managed_workspace_password_setup_after_commit(
    db: Session,
    *,
    reservation: IdentityOperationReservation,
    owner_company_id: int,
    managed_company_id: int,
    customer_id: int,
    managed_link_id: int,
    recipient_client_id: int,
    recipient_email: str,
    owner_client_ids: List[int],
    owner_client_emails: List[str],
    client_created: bool,
) -> dict:
    result = {
        "password_setup_email_sent": False,
        "password_setup_email_skipped": not client_created,
        "password_setup_email_reason": "existing_account" if not client_created else None,
        "password_setup_url": None,
    }
    if not client_created:
        return result

    fallback_setup_url = None
    try:
        rollback_if_available(db)
        with managed_workspace_account_identity_locks(
            db,
            [recipient_email, *owner_client_emails],
            reservation=reservation,
        ):
            state = revalidate_managed_workspace_password_setup(
                db,
                owner_company_id=owner_company_id,
                managed_company_id=managed_company_id,
                customer_id=customer_id,
                managed_link_id=managed_link_id,
                recipient_client_id=recipient_client_id,
                recipient_email=recipient_email,
                owner_client_ids=owner_client_ids,
            )
            if state is None:
                rollback_if_available(db)
                result["password_setup_email_skipped"] = True
                result["password_setup_email_reason"] = "account_unavailable"
                logger.info(
                    "[companies-admin] Definição de senha suprimida porque a conta "
                    "não está disponível client_id=%s",
                    recipient_client_id,
                )
                return result

            recipient_client, _owner_company, managed_company, managed_link = state
            min_setup_ttl_minutes = (
                int(managed_link.trial_days) * 24 * 60
                if managed_link.trial_days
                else None
            )
            setup_token = create_password_setup_token_for_account(
                db,
                account=recipient_client,
                min_ttl_minutes=min_setup_ttl_minutes,
                _identity_lock_held=True,
            )

            state = revalidate_managed_workspace_password_setup(
                db,
                owner_company_id=owner_company_id,
                managed_company_id=managed_company_id,
                customer_id=customer_id,
                managed_link_id=managed_link_id,
                recipient_client_id=recipient_client_id,
                recipient_email=recipient_email,
                owner_client_ids=owner_client_ids,
            )
            if state is None:
                rollback_if_available(db)
                result["password_setup_email_skipped"] = True
                result["password_setup_email_reason"] = "account_unavailable"
                return result

            recipient_client, _owner_company, managed_company, _managed_link = state
            fallback_setup_url = setup_token.reset_url
            billing_profile = dict(recipient_client.billing_profile or {})
            recipient_name = billing_profile.get("full_name")
            recipient_address = str(recipient_client.email)
            workspace_name = str(
                managed_company.name_company or managed_company.name
            )
            rollback_if_available(db)

            email_result = send_password_setup_email(
                to_email=recipient_address,
                to_name=recipient_name,
                workspace_name=workspace_name,
                setup_url=setup_token.reset_url,
                expires_minutes=setup_token.expires_minutes,
            )
            result["password_setup_email_sent"] = bool(email_result.sent)
            result["password_setup_email_skipped"] = bool(email_result.skipped)
            result["password_setup_email_reason"] = email_result.reason
            if not email_result.sent:
                result["password_setup_url"] = fallback_setup_url
    except IdentityOperationBusyError:
        rollback_if_available(db)
        result["password_setup_email_skipped"] = True
        result["password_setup_email_reason"] = "identity_busy"
        logger.info(
            "[companies-admin] Definição de senha suprimida por contenção "
            "de identidade client_id=%s",
            recipient_client_id,
        )
    except Exception as exc:
        rollback_if_available(db)
        result["password_setup_email_skipped"] = True
        result["password_setup_email_reason"] = "delivery_precondition_failed"
        result["password_setup_url"] = fallback_setup_url
        logger.warning(
            "[companies-admin] Definição de senha suprimida por falha de "
            "revalidação client_id=%s erro=%s",
            recipient_client_id,
            exc.__class__.__name__,
        )
    return result

# Endpoint para obter as informações da empresa atual do usuário logado
@router.get("/company")
def get_company_info(db: Session = Depends(get_db), user = Depends(get_current_user)):
    company_id = user.company_id
    logger.info(f"Buscando informações da empresa para company_id={company_id}, usuário={user.email}")
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        logger.warning(f"Empresa não encontrada para company_id={company_id}")
        raise HTTPException(status_code=404, detail="Empresa não encontrada")

    logger.info(f"Empresa encontrada: ID={company.id}, name_company={company.name_company}, logo_url={company.logo_url}")
    return {
        "company": {
            "name_company": company.name_company,
            "logo_url": company.logo_url,
            "whatsapp_config": {
                "waha_enabled": company.waha_enabled,
                "waha_session_name": company.waha_session_name,
                "zapi_instance_id": company.zapi_instance_id
            }
        }
    }

# Endpoint para atualizar informações da empresa (nome e logo)
@router.put("/company")
async def update_company_info(
    name_company: str = Form(...),
    logo: UploadFile = File(None),
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    company_id = user.company_id
    logger.info(f"Atualizando informações da empresa para company_id={company_id}, usuário={user.email}. Novo nome_company={name_company}")
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        logger.warning(f"Tentativa de atualização de empresa não encontrada: company_id={company_id}")
        raise HTTPException(status_code=404, detail="Empresa não encontrada")

    company.name_company = name_company

    if logo is not None:
        contents = await logo.read()

        filename_ext = os.path.splitext(logo.filename or "")[1].lower()
        if filename_ext not in ALLOWED_LOGO_EXTENSIONS:
            filename_ext = ".png"

        filename = f"company_{company_id}_logo{filename_ext}"
        logo_path = os.path.join(COMPANY_LOGO_DIR, filename)
        logger.info(f"Recebido arquivo de logo para company_id={company_id}, salvando em {logo_path}")

        os.makedirs(COMPANY_LOGO_DIR, exist_ok=True)
        with open(logo_path, "wb") as f:
            f.write(contents)
        company.logo_url = f"{COMPANY_LOGO_PUBLIC_PREFIX.rstrip('/')}/{filename}"
        logger.info(f"Logo da empresa atualizada: {company.logo_url}")

    db.commit()
    db.refresh(company)
    logger.info(f"Configurações da empresa atualizadas com sucesso para company_id={company_id}")
    return {
        "message": "Configurações da empresa atualizadas com sucesso",
        "name_company": company.name_company,
        "logo_url": company.logo_url,
        "logoUrl": company.logo_url,
    }

@router.delete("/company")
def delete_company_name_and_logo(
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    Remove (ou zera) o name_company e o logo_url da empresa do usuário.
    """
    company_id = user.company_id
    logger.info(f"[DELETE Company] Removendo name_company e logo_url para company_id={company_id}, user={user.email}")

    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        logger.warning(f"[DELETE Company] Empresa não encontrada para company_id={company_id}")
        raise HTTPException(status_code=404, detail="Empresa não encontrada")

    # Zera o campo de nome e a logo
    company.name_company = None
    company.logo_url = None

    db.commit()
    db.refresh(company)
    logger.info("[DELETE Company] Valor de name_company e logo_url removido/zerado.")

    return {"message": "Nome da empresa e logo removidos com sucesso."}

@router.get("/company/mirror-webhook")
async def get_mirror_webhook_url(
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    Retorna o mirror_webhook_url da empresa do usuário autenticado.
    """
    company_id = user.company_id
    logger.info(f"[GET MirrorWebhook] Consultando company_id={company_id}, user={user.email}")

    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        logger.warning(f"[GET MirrorWebhook] Empresa não encontrada para company_id={company_id}")
        raise HTTPException(status_code=404, detail="Empresa não encontrada")

    logger.info(f"[GET MirrorWebhook] Valor atual do mirror_webhook_url={company.mirror_webhook_url}")
    return {
        "company_id": company_id,
        "mirror_webhook_url": company.mirror_webhook_url
    }

@router.post("/company/mirror-webhook")
async def create_mirror_webhook_url(
    mirror_webhook_url: str = Form(...),
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    Cria (ou sobrescreve) a URL de mirror_webhook_url para a empresa do usuário.
    """
    company_id = user.company_id
    logger.info(f"[POST MirrorWebhook] Definindo mirror_webhook_url para company_id={company_id}, user={user.email}")
    logger.info(f"[POST MirrorWebhook] Novo valor = {mirror_webhook_url}")

    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        logger.warning(f"[POST MirrorWebhook] Empresa não encontrada para company_id={company_id}")
        raise HTTPException(status_code=404, detail="Empresa não encontrada")

    company.mirror_webhook_url = mirror_webhook_url
    db.commit()
    db.refresh(company)

    logger.info(f"[POST MirrorWebhook] URL de mirror_webhook atualizada com sucesso: {company.mirror_webhook_url}")
    return {
        "message": "Mirror webhook URL criada/atualizada com sucesso",
        "mirror_webhook_url": company.mirror_webhook_url
    }

@router.put("/company/mirror-webhook")
async def update_mirror_webhook_url(
    mirror_webhook_url: str = Form(...),
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    Atualiza a URL de mirror_webhook_url para a empresa do usuário (semântica PUT).
    Se não existir, pode criar ou retornar 404 — escolha a sua regra de negócio.
    """
    company_id = user.company_id
    logger.info(f"[PUT MirrorWebhook] Atualizando mirror_webhook_url para company_id={company_id}, user={user.email}")
    logger.info(f"[PUT MirrorWebhook] Novo valor = {mirror_webhook_url}")

    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        logger.warning(f"[PUT MirrorWebhook] Empresa não encontrada para company_id={company_id}")
        raise HTTPException(status_code=404, detail="Empresa não encontrada")

    # Dependendo da regra de negócio, se não existir você pode criar:
    # if not company.mirror_webhook_url:
    #     # "Criando" o valor se antes era nulo/vazio
    #     logger.info("[PUT MirrorWebhook] Valor inexistente, criando nova config.")
    # else:
    #     logger.info("[PUT MirrorWebhook] Substituindo valor anterior.")

    company.mirror_webhook_url = mirror_webhook_url
    db.commit()
    db.refresh(company)

    logger.info(f"[PUT MirrorWebhook] mirror_webhook_url atualizado para {company.mirror_webhook_url}")
    return {
        "message": "Mirror webhook URL atualizada com sucesso (PUT)",
        "mirror_webhook_url": company.mirror_webhook_url
    }

@router.delete("/company/mirror-webhook")
async def delete_mirror_webhook_url(
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    Remove (ou zera) a URL de mirror_webhook_url da empresa do usuário.
    """
    company_id = user.company_id
    logger.info(f"[DELETE MirrorWebhook] Removendo mirror_webhook_url para company_id={company_id}, user={user.email}")

    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        logger.warning(f"[DELETE MirrorWebhook] Empresa não encontrada para company_id={company_id}")
        raise HTTPException(status_code=404, detail="Empresa não encontrada")

    # zera ou remove
    company.mirror_webhook_url = None
    db.commit()
    db.refresh(company)

    logger.info("[DELETE MirrorWebhook] Valor de mirror_webhook_url removido/zerado.")
    return {"message": "Mirror webhook URL removido com sucesso."}

@router.post("/companies-admin", summary="Cria nova empresa e a vincula a um email existente")
def create_new_company_admin(
    client_email: str = Form(...),
    company_name: str = Form(...),
    company_cnpj: str = Form(...),
    customer_id: Optional[int] = Form(None),
    trial_days: int = Form(0),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    normalized_client_email = normalize_workspace_email(client_email)
    try:
        with account_identity_operation_reservation(
            db,
            f"create-managed-workspace:{normalized_client_email}",
        ) as reservation:
            return _create_new_company_admin_with_identity_reservation(
                client_email=client_email,
                company_name=company_name,
                company_cnpj=company_cnpj,
                customer_id=customer_id,
                trial_days=trial_days,
                db=db,
                current_user=current_user,
                normalized_client_email=normalized_client_email,
                reservation=reservation,
            )
    except IdentityOperationBusyError as exc:
        rollback_if_available(db)
        raise identity_operation_busy_http(exc) from exc


def _create_new_company_admin_with_identity_reservation(
    *,
    client_email: str,
    company_name: str,
    company_cnpj: str,
    customer_id: Optional[int],
    trial_days: int,
    db: Session,
    current_user,
    normalized_client_email: str,
    reservation: IdentityOperationReservation,
):
    """
    Cria uma nova empresa e a vincula ao usuário (Client) cujo e-mail for informado.
    Sem customer_id, exige allowlist interna. Com customer_id, permite que o
    aluno dono do cliente crie o workspace vinculado e, se necessário, cria o
    usuário master do cliente final automaticamente.
    """
    current_is_internal_admin = is_internal_admin(current_user)
    if customer_id is None and not current_is_internal_admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores internos")

    company_document = clean_workspace_document(company_cnpj)
    try:
        email_identity = lock_and_resolve_account_email_identity(
            db,
            normalized_client_email,
        )
    except AccountEmailCollisionError as exc:
        raise HTTPException(
            status_code=409,
            detail="Email já está em uso por mais de uma identidade",
        ) from exc
    if email_identity.user:
        raise HTTPException(
            status_code=409,
            detail="Email já está em uso por um usuário interno",
        )
    logger.info(f"[companies-admin] Usuario {current_user.email} criando empresa para {normalized_client_email}")

    if trial_days not in {0, 3, 7, 14, 30}:
        raise HTTPException(status_code=400, detail="Período de teste inválido. Use 0, 3, 7, 14 ou 30 dias.")

    client = email_identity.client
    if not client and customer_id is None:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum usuário encontrado com e-mail={normalized_client_email}"
        )

    linked_customer = None
    owner_company = None
    owner_client_ids: List[int] = []
    owner_client_emails: List[str] = []
    owner_company_id: Optional[int] = None
    if customer_id is not None:
        linked_customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not linked_customer:
            raise HTTPException(status_code=404, detail="Cliente para vínculo não encontrado")
        owner_company_id = int(linked_customer.company_id)

    # Adquire entidades na ordem global company -> client e cobre tanto o
    # workspace responsável quanto uma conta existente do cliente final.
    scope_company_ids = {
        *([owner_company_id] if owner_company_id is not None else []),
        *(
            [int(client.ownership_company_id)]
            if client is not None and client.ownership_company_id is not None
            else []
        ),
    }
    if scope_company_ids:
        lock_entities_for_mutation(
            db,
            company_ids=scope_company_ids,
        )

    discovered_owner_clients: List[Client] = []
    if owner_company_id is not None:
        discovered_owner_clients = (
            db.query(Client)
            .filter_by(ownership_company_id=owner_company_id)
            .order_by(Client.id)
            .all()
        )

    scope_client_ids = {
        *(int(owner_client.id) for owner_client in discovered_owner_clients),
        *([int(client.id)] if client is not None else []),
    }
    if scope_client_ids:
        lock_entities_for_mutation(
            db,
            client_ids=scope_client_ids,
        )

    if client is not None:
        locked_client = (
            db.query(Client)
            .filter_by(id=int(client.id))
            .with_for_update()
            .first()
        )
        if (
            not locked_client
            or not bool(locked_client.is_active)
            or normalize_account_email(locked_client.email) != normalized_client_email
        ):
            raise HTTPException(
                status_code=423,
                detail="O usuário do workspace está suspenso",
            )
        try:
            ensure_company_operational(db, int(locked_client.ownership_company_id))
        except CompanyOperationallyBlockedError as exc:
            raise HTTPException(
                status_code=423,
                detail="O usuário do workspace está suspenso",
            ) from exc
        client = locked_client

    if owner_company_id is not None:
        owner_company = (
            db.query(Company)
            .filter(Company.id == owner_company_id)
            .with_for_update()
            .first()
        )
        owner_clients = (
            db.query(Client)
            .filter_by(ownership_company_id=owner_company_id)
            .order_by(Client.id)
            .with_for_update()
            .all()
        )
        if {
            int(owner_client.id)
            for owner_client in owner_clients
        } != {
            int(owner_client.id)
            for owner_client in discovered_owner_clients
        }:
            raise HTTPException(
                status_code=409,
                detail="Os usuários responsáveis mudaram durante a criação; tente novamente.",
            )
        if (
            not owner_company
            or owner_company.operational_status != "active"
            or not owner_clients
            or any(not bool(owner_client.is_active) for owner_client in owner_clients)
        ):
            raise HTTPException(
                status_code=423,
                detail="O workspace responsável está suspenso",
            )
        owner_client_ids = [int(owner_client.id) for owner_client in owner_clients]
        owner_client_emails = [
            str(owner_client.email)
            for owner_client in owner_clients
            if normalize_account_email(owner_client.email)
        ]

        if not current_is_internal_admin:
            if not isinstance(current_user, Client):
                raise HTTPException(
                    status_code=403,
                    detail="Apenas o usuário master do workspace pode liberar workspace para clientes"
                )
            ensure_user_can_access_company(current_user, linked_customer.company_id, db)
        customer_email = normalize_workspace_email(linked_customer.email or "")
        if normalized_client_email != customer_email:
            raise HTTPException(
                status_code=400,
                detail="O e-mail do workspace deve ser o e-mail cadastrado no cliente selecionado.",
            )

        current_user_email = normalize_optional_workspace_email(getattr(current_user, "email", None))
        if current_user_email and normalized_client_email == current_user_email:
            raise HTTPException(status_code=400, detail=WORKSPACE_OWNER_EMAIL_CONFLICT_MESSAGE)

    # 1) Verificar se email do cliente já existe. No fluxo com customer_id,
    # criamos o usuário final automaticamente quando ele ainda não existe.
    # 2) Verificar se CPF/CNPJ já existe
    existing_company = db.query(Company).filter_by(cnpj=company_document).first()
    if existing_company:
        raise HTTPException(
            status_code=400,
            detail=f"CPF/CNPJ {company_document} já cadastrado em outra empresa."
        )

    managed_link = None
    trial_wallet = None
    trial_credits_granted = 0.0
    password_setup_email_sent = False
    password_setup_email_skipped = False
    password_setup_email_reason = None
    password_setup_url = None
    managed_response = None
    trial_wallet_balance = 0.0

    # 3) Criar a nova Company
    new_company = Company(
        name=company_name,
        cnpj=company_document,
        operational_status="active",
    )
    db.add(new_company)
    db.flush()
    db.refresh(new_company)

    client_created = False
    if client is None and linked_customer is not None:
        initial_secret_hash = hash_password(secrets.token_urlsafe(32))
        client = Client(
            email=normalized_client_email,
            company_id=new_company.id,
            ownership_company_id=new_company.id,
            is_active=True,
            billing_profile=managed_workspace_client_profile(
                customer=linked_customer,
                email=normalized_client_email,
                document=company_document,
            ),
        )
        setattr(client, "password", initial_secret_hash)
        db.add(client)
        db.flush()
        db.refresh(client)
        client_created = True

    # 4) Criar associações na tabela client_companies
    ensure_client_company_link(db, client_id=client.id, company_id=new_company.id)
    creator_client_id = actor_client_id(current_user)
    if linked_customer is not None and creator_client_id is not None:
        ensure_client_company_link(db, client_id=creator_client_id, company_id=new_company.id)

    # O vínculo de ownership faz parte da mesma transação da Company, Client e
    # associações para que o workspace nunca fique ativo sem responsável.
    if linked_customer is not None:
        trial_started_at = datetime.now(timezone.utc) if trial_days else None
        trial_ends_at = trial_started_at + timedelta(days=trial_days) if trial_started_at else None
        managed_link = CustomerManagedCompany(
            owner_company_id=linked_customer.company_id,
            customer_id=linked_customer.id,
            managed_company_id=new_company.id,
            created_by_client_id=creator_client_id,
            trial_days=trial_days,
            trial_started_at=trial_started_at,
            trial_ends_at=trial_ends_at,
            lifecycle_status="trialing" if trial_days else "active",
        )
        db.add(managed_link)
        db.flush()
        grant_amount = managed_workspace_trial_credits_for_days(managed_link.trial_days)
        if grant_amount > 0:
            trial_wallet, _ = grant_managed_workspace_trial_ai_credits(
                db=db,
                company_id=new_company.id,
                owner_company_id=managed_link.owner_company_id,
                customer_id=managed_link.customer_id,
                managed_link_id=managed_link.id,
                trial_days=managed_link.trial_days,
            )
            trial_credits_granted = float(grant_amount)
            trial_wallet_balance = (
                float(trial_wallet.balance_credits)
                if trial_wallet is not None
                else 0.0
            )
        managed_response = {
            "owner_company_id": int(managed_link.owner_company_id),
            "managed_company_id": int(managed_link.managed_company_id),
            "customer_id": int(managed_link.customer_id),
            "managed_link_id": int(managed_link.id),
            "trial_days": int(managed_link.trial_days or 0),
            "trial_ends_at": managed_link.trial_ends_at,
            "lifecycle_status": str(managed_link.lifecycle_status),
        }

    new_company_id = int(new_company.id)
    recipient_client_id = int(client.id)
    db.commit()

    # 5) Criar pipeline padrão para a nova empresa
    from backend.services.pipeline_service import PipelineService
    try:
        PipelineService.create_minimal_pipeline_for_company(new_company_id, db)
    except Exception as exc:
        rollback_if_available(db)
        logger.warning(
            "[companies-admin] Falha ao criar pipeline company_id=%s erro=%s",
            new_company_id,
            exc.__class__.__name__,
        )

    if managed_response is not None:
        email_flags = run_managed_workspace_password_setup_after_commit(
            db,
            reservation=reservation,
            owner_company_id=managed_response["owner_company_id"],
            managed_company_id=managed_response["managed_company_id"],
            customer_id=managed_response["customer_id"],
            managed_link_id=managed_response["managed_link_id"],
            recipient_client_id=recipient_client_id,
            recipient_email=normalized_client_email,
            owner_client_ids=owner_client_ids,
            owner_client_emails=owner_client_emails,
            client_created=client_created,
        )
        password_setup_email_sent = email_flags[
            "password_setup_email_sent"
        ]
        password_setup_email_skipped = email_flags[
            "password_setup_email_skipped"
        ]
        password_setup_email_reason = email_flags[
            "password_setup_email_reason"
        ]
        password_setup_url = email_flags["password_setup_url"]

    response = {
        "company_id": new_company_id,
        "message": f"Empresa '{company_name}' criada com sucesso e associada ao usuário {normalized_client_email}.",
        "client_id": recipient_client_id,
        "client_created": client_created,
    }
    if managed_response is not None:
        response["managed_customer_id"] = managed_response["customer_id"]
        response["managed_link_id"] = managed_response["managed_link_id"]
        response["trial_days"] = managed_response["trial_days"]
        response["trial_ends_at"] = (
            managed_response["trial_ends_at"].isoformat()
            if managed_response["trial_ends_at"]
            else None
        )
        response["lifecycle_status"] = managed_response["lifecycle_status"]
        response["trial_credits_granted"] = trial_credits_granted
        response["ai_credit_balance"] = trial_wallet_balance
        response["password_setup_email_sent"] = password_setup_email_sent
        response["password_setup_email_skipped"] = password_setup_email_skipped
        response["password_setup_email_reason"] = password_setup_email_reason
        if password_setup_url:
            response["password_setup_url"] = password_setup_url
    return response

@router.get("/client-companies", summary="Lista todas as empresas vinculadas ao usuário logado")
def list_user_companies(
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
) -> List[dict]:
    """
    Retorna a lista de empresas, incluindo logo e saldo de créditos de IA.
    """
    user_associations = db.query(ClientCompany).filter_by(client_id=user.id).all()
    if not user_associations:
        return []

    company_ids = [assoc.company_id for assoc in user_associations]
    companies = db.query(Company).filter(Company.id.in_(company_ids)).all()
    wallets = db.query(AICreditWallet).filter(AICreditWallet.company_id.in_(company_ids)).all()
    managed_links = db.query(CustomerManagedCompany).filter(
        CustomerManagedCompany.managed_company_id.in_(company_ids)
    ).all()
    companies_by_id = {company.id: company for company in companies}
    wallets_by_company_id = {wallet.company_id: wallet for wallet in wallets}
    managed_links_by_company_id = {link.managed_company_id: link for link in managed_links}

    companies_data = []
    lifecycle_changed = False
    for assoc in user_associations:
        company = companies_by_id.get(assoc.company_id)
        if company:
            wallet = wallets_by_company_id.get(company.id)
            managed_link = managed_links_by_company_id.get(company.id)
            trial_state = None
            if managed_link:
                trial_state = get_managed_workspace_trial_state(managed_link)
                lifecycle_changed = refresh_managed_workspace_lifecycle(db, managed_link) or lifecycle_changed
            item = {
                "company_id": company.id,
                "name_company": company.name_company or company.name,  # Exibe name_company se existir
                "logo_url": company.logo_url,
                "ai_credit_balance": float(wallet.balance_credits) if wallet else 0.0,
                "ai_credit_status": wallet.status if wallet else "active",
            }
            if managed_link and trial_state:
                item.update({
                    "managed_link_id": managed_link.id,
                    "managed_customer_id": managed_link.customer_id,
                    "lifecycle_status": trial_state["lifecycle_status"],
                    "trial_days": managed_link.trial_days or 0,
                    "trial_started_at": managed_link.trial_started_at.isoformat() if managed_link.trial_started_at else None,
                    "trial_ends_at": managed_link.trial_ends_at.isoformat() if managed_link.trial_ends_at else None,
                    "trial_days_remaining": trial_state["trial_days_remaining"],
                    "trial_progress_percent": trial_state["trial_progress_percent"],
                    "is_trial_expired": trial_state["is_trial_expired"],
                })
            companies_data.append(item)
    if lifecycle_changed:
        db.commit()
    return companies_data


@router.delete("/client-companies/{company_id}", summary="Remove vínculo com uma empresa específica")
def remove_user_company(
    company_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    Remove a associação (vínculo) do usuário atual com a empresa {company_id}.
    Não deleta a empresa em si, apenas o vínculo.
    """
    if int(company_id) == int(user.ownership_company_id):
        raise HTTPException(
            status_code=409,
            detail="A empresa principal da conta não pode ser desvinculada.",
        )

    lock_entities_for_mutation(
        db,
        company_ids=[int(user.ownership_company_id), int(company_id)],
        client_ids=[int(user.id)],
    )
    actor = (
        db.query(Client)
        .filter(Client.id == int(user.id))
        .with_for_update()
        .first()
    )
    if not actor or not actor.is_active:
        raise HTTPException(status_code=423, detail="Acesso suspenso")
    try:
        ensure_company_operational(db, int(user.ownership_company_id))
        ensure_company_operational(db, int(company_id))
    except CompanyOperationallyBlockedError as exc:
        raise HTTPException(status_code=423, detail="Acesso suspenso") from exc

    association = (
        db.query(ClientCompany)
        .filter_by(client_id=int(user.id), company_id=int(company_id))
        .with_for_update()
        .first()
    )
    if not association:
        raise HTTPException(status_code=404, detail="Vínculo não encontrado ou já removido.")

    db.delete(association)
    db.commit()
    return {"message": f"Vínculo com a empresa ID={company_id} removido com sucesso."}


@router.put("/client-companies/{company_id}/select", summary="Define qual empresa o usuário está usando no momento")
def select_active_company(
    company_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    Atualiza user.company_id para a empresa selecionada, sem precisar
    renovar o token. Assim que o front recebe a resposta, ele pode
    refazer o GET /api/company (ou usar a info retornada) para exibir
    o logo atual da nova empresa.
    """
    logger.info(f"[selectActiveCompany] Usuário {user.email} solicitou selecionar company_id={company_id}.")

    # Verifica se existe associação do user com a company_id
    association = db.query(ClientCompany).filter_by(client_id=user.id, company_id=company_id).first()
    if not association:
        logger.warning(
            f"[selectActiveCompany] Associação não encontrada: user_id={user.id}, company_id={company_id}. "
            "Retornando 404."
        )
        raise HTTPException(
            status_code=404,
            detail="Vínculo não encontrado. Impossível selecionar esta empresa."
        )

    ensure_managed_workspace_access(db, company_id)

    # Atualiza o user.company_id
    old_company_id = user.company_id
    user.company_id = company_id
    db.commit()

    logger.info(f"[selectActiveCompany] user.company_id alterado de {old_company_id} para {company_id} com sucesso.")

    # Opcionalmente, buscar a nova empresa para retornar logo_url e name_company
    new_company = db.query(Company).filter(Company.id == company_id).first()
    if not new_company:
        logger.warning(f"[selectActiveCompany] A empresa {company_id} não foi encontrada (inconsistência?).")
        raise HTTPException(status_code=404, detail="Empresa não encontrada após troca de contexto.")

    logger.info(f"[selectActiveCompany] Retornando logo_url={new_company.logo_url} e name_company={new_company.name_company}.")

    return {
        "message": f"Empresa ID={company_id} definida como ativa para o usuário {user.email}.",
        "company_logo_url": new_company.logo_url or "",
        "name_company": new_company.name_company or new_company.name or ""
    }
