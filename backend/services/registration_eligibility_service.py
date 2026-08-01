"""Public registration eligibility rules."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Dict

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models import Client, Company, User
from backend.services.company_access_control import (
    RefundIdentityOperationBusyError,
    is_account_refund_blocked,
    is_email_refund_blocked,
    lock_refund_entities_for_mutation,
    lock_refund_identity_for_creation,
    normalize_account_email,
    refund_identity_operation_lock,
)
from backend.services.brevo_email_service import send_master_welcome_email
from backend.services.eduzz_checkout_service import EduzzAPIError, EduzzConfigurationError
from backend.services.eduzz_registration_service import EduzzRegistrationVerification, verify_registration_purchase
from backend.services.pipeline_service import PipelineService

logger = logging.getLogger("saas_business")

REGISTRATION_STUDENT_ONLY_DETAIL = "Cadastro liberado apenas para alunos."


def ensure_registration_eligibility(email: str, db: Session) -> EduzzRegistrationVerification:
    normalized_email = normalize_account_email(email)
    lock_refund_identity_for_creation(db, normalized_email)
    if is_email_refund_blocked(db, normalized_email):
        logger.warning("Cadastro bloqueado por suspensão de reembolso pendente/confirmada")
        raise HTTPException(status_code=403, detail=REGISTRATION_STUDENT_ONLY_DETAIL)

    existing_client = db.query(Client).filter(func.lower(Client.email) == normalized_email).first()
    existing_user = db.query(User).filter(func.lower(User.email) == normalized_email).first()
    if existing_client or existing_user:
        logger.warning("Email já cadastrado")
        raise HTTPException(status_code=400, detail="Email já cadastrado")

    try:
        registration_purchase = verify_registration_purchase(email)
    except EduzzConfigurationError as exc:
        logger.error("Validação de compra para cadastro indisponível: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Cadastro temporariamente indisponível. Tente novamente em instantes.",
        ) from exc
    except EduzzAPIError as exc:
        logger.error(
            "Erro ao validar compra para cadastro: status=%s",
            exc.status_code,
        )
        raise HTTPException(
            status_code=503,
            detail="Não foi possível validar sua compra agora. Tente novamente em instantes.",
        ) from exc

    if not registration_purchase.allowed:
        logger.warning("Cadastro bloqueado: compra do produto principal não encontrada para o email informado")
        raise HTTPException(
            status_code=403,
            detail=REGISTRATION_STUDENT_ONLY_DETAIL,
        )

    return registration_purchase


def _revalidate_registered_account(
    db: Session,
    *,
    client_id: int,
    company_id: int,
    email: str,
) -> tuple[Client, Company] | None:
    lock_refund_entities_for_mutation(
        db,
        company_ids=[int(company_id)],
        client_ids=[int(client_id)],
    )
    db.expire_all()
    client = (
        db.query(Client)
        .filter(
            Client.id == int(client_id),
            Client.email == email,
            Client.ownership_company_id == int(company_id),
            Client.is_active.is_(True),
        )
        .first()
    )
    company = (
        db.query(Company)
        .filter(
            Company.id == int(company_id),
            Company.operational_status == "active",
        )
        .first()
    )
    if (
        not client
        or not company
        or is_account_refund_blocked(db, client)
    ):
        db.rollback()
        return None
    return client, company


def run_registration_post_commit_effects(
    db: Session,
    *,
    client_id: int,
    company_id: int,
    email: str,
    company_name: str,
    billing_profile: Dict[str, Any],
) -> Dict[str, Any]:
    """Run welcome effects only while the new account still wins the refund race."""
    normalized_email = normalize_account_email(email)
    result: Dict[str, Any] = {
        "pipeline_created": False,
        "welcome_email_sent": False,
        "skipped": None,
    }
    try:
        with refund_identity_operation_lock(db, normalized_email):
            account = _revalidate_registered_account(
                db,
                client_id=client_id,
                company_id=company_id,
                email=normalized_email,
            )
            if account is None:
                result["skipped"] = "refund_blocked"
                return result

            try:
                PipelineService.create_minimal_pipeline_for_company(
                    int(company_id),
                    db,
                )
                result["pipeline_created"] = True
            except Exception as exc:
                db.rollback()
                logger.error(
                    "Erro ao criar pipeline pós-cadastro company_id=%s erro=%s",
                    company_id,
                    exc.__class__.__name__,
                )

            account = _revalidate_registered_account(
                db,
                client_id=client_id,
                company_id=company_id,
                email=normalized_email,
            )
            if account is None:
                result["skipped"] = "refund_blocked"
                return result

            # The identity lock remains held while Brevo runs, but the DB
            # transaction/entity locks can be released before network I/O.
            db.rollback()
            welcome_client = SimpleNamespace(
                id=int(client_id),
                email=normalized_email,
                billing_profile=billing_profile,
            )
            try:
                email_result = send_master_welcome_email(
                    welcome_client,
                    company_name=company_name,
                )
                result["welcome_email_sent"] = bool(email_result.sent)
                if email_result.sent:
                    logger.info(
                        "Email de boas-vindas enviado para novo cliente ID=%s",
                        client_id,
                    )
                elif email_result.skipped:
                    logger.info(
                        "Email de boas-vindas ignorado para novo cliente "
                        "ID=%s motivo=%s",
                        client_id,
                        email_result.reason,
                    )
                else:
                    logger.warning(
                        "Email de boas-vindas não enviado para novo cliente "
                        "ID=%s motivo=%s",
                        client_id,
                        email_result.reason,
                    )
            except Exception as exc:
                logger.warning(
                    "Falha inesperada no envio de boas-vindas para cliente "
                    "ID=%s erro=%s",
                    client_id,
                    exc.__class__.__name__,
                )
    except RefundIdentityOperationBusyError:
        db.rollback()
        result["skipped"] = "refund_lock_busy"
        logger.info(
            "Efeitos pós-cadastro ignorados por contenção de reembolso "
            "client_id=%s",
            client_id,
        )
    except Exception as exc:
        db.rollback()
        result["skipped"] = "revalidation_failed"
        logger.warning(
            "Efeitos pós-cadastro ignorados por falha na revalidação "
            "client_id=%s erro=%s",
            client_id,
            exc.__class__.__name__,
        )
    return result
