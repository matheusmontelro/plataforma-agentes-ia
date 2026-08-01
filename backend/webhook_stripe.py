# backend/routes/webhook_stripe.py

import os
import json
import stripe
import logging
import secrets  # para gerar senha
import string
from secrets import token_hex
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from datetime import datetime
from dotenv import load_dotenv

from backend.db import get_db
from backend.models import User, Client, Company, ClientCompany
from backend.auth import hash_password

router = APIRouter()
logger = logging.getLogger(__name__)

load_dotenv()

STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")

stripe.api_key = STRIPE_SECRET_KEY


def gerar_senha_aleatoria(tamanho: int = 12) -> str:
    """
    Gera uma senha forte e aleatória com letras maiúsculas, minúsculas, dígitos e símbolos.
    """
    caracteres = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    senha = "".join(secrets.choice(caracteres) for _ in range(tamanho))
    return senha


@router.post("/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Endpoint para receber eventos da Stripe (checkout.session.completed)
    e processar a criação de um novo usuário (Client) + empresa correspondente.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    # 1) Validar a assinatura do webhook para garantir que vem da Stripe
    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Falha ao verificar assinatura da Stripe: {str(e)}")
        raise HTTPException(status_code=400, detail="Signature verification failed.")

    # Log do evento completo (opcional)
    logger.info(f"Evento completo do Stripe: {json.dumps(event, indent=2, default=str)}")

    # 2) Identificar o tipo do evento
    event_type = event["type"]
    data_object = event["data"]["object"]

    logger.info(f"Recebendo evento Stripe type={event_type}")

    if event_type == "checkout.session.completed":
        # 3) Obter e-mail do cliente e status de pagamento
        session_id = data_object["id"]
        customer_email = (
            data_object.get("customer_details", {}).get("email")
            or data_object.get("customer_email")
        )
        payment_status = data_object.get("payment_status")

        # 4) Extrair campos customizados (cnpj, razaosocial) de custom_fields
        custom_fields = data_object.get("custom_fields", [])
        cnpj_value = None
        razao_social_value = None

        for field in custom_fields:
            key = field.get("key")
            val = field.get("text", {}).get("value")  # valor digitado
            if key == "cnpj":
                cnpj_value = val
            elif key == "razaosocial":
                razao_social_value = val

        logger.info(
            f"Campos customizados da Sessão: cnpj={cnpj_value}, "
            f"razao_social={razao_social_value}"
        )

        # 5) Se pagamento estiver 'paid', cria o Client + Company
        if payment_status == "paid":
            logger.info(f"Pagamento confirmado. Criando usuário para {customer_email}.")
            if not customer_email or not razao_social_value or not cnpj_value:
                logger.warning(
                    "Provisionamento Stripe ignorado por dados cadastrais incompletos "
                    "session_id=%s",
                    session_id,
                )
                return {"status": "ignored", "reason": "missing_registration_data"}

            from backend.services.company_access_control import (
                AccountEmailCollisionError,
                is_email_refund_blocked,
                lock_and_resolve_account_email_identity,
            )
            try:
                email_identity = lock_and_resolve_account_email_identity(
                    db,
                    str(customer_email),
                )
            except AccountEmailCollisionError:
                logger.error(
                    "Provisionamento Stripe rejeitado por colisão de identidade "
                    "session_id=%s",
                    session_id,
                )
                return {"status": "ignored", "reason": "email_identity_collision"}
            normalized_customer_email = email_identity.normalized_email
            if is_email_refund_blocked(db, normalized_customer_email):
                logger.warning("Provisionamento Stripe ignorado por suspensão de acesso")
                return {"status": "ignored", "reason": "access_suspended"}

            # Verificar se já existe o e-mail
            existing_client = email_identity.client
            if email_identity.user:
                logger.warning(
                    "Provisionamento Stripe ignorado: email pertence a usuário interno"
                )
                return {"status": "ignored", "reason": "email_in_use_by_user"}
            if existing_client:
                logger.info("Já existe um Client com esse e-mail. Ignorando criação.")
            else:
                # 5a) Gerar senha aleatória
                senha_aleatoria = gerar_senha_aleatoria()
                logger.info("[STRIPE] Credencial inicial gerada")

                # 5b) Gerar uma API key se quiser
                api_key_gerado = token_hex(32)
                logger.info("[STRIPE] API key gerada")

                try:
                    # Company, Client e associação são persistidos em uma única
                    # transação protegida pelo lock da identidade. Um reembolso
                    # concorrente verá o escopo inteiro ou aguardará o commit.
                    new_company = Company(
                        name=razao_social_value,
                        cnpj=cnpj_value,
                    )
                    db.add(new_company)
                    db.flush()

                    new_client = Client(
                        email=normalized_customer_email,
                        password=hash_password(senha_aleatoria),
                        company_id=new_company.id,
                        ownership_company_id=new_company.id,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                        api_key=api_key_gerado,
                    )
                    db.add(new_client)
                    db.flush()

                    db.add(
                        ClientCompany(
                            client_id=new_client.id,
                            company_id=new_company.id,
                        )
                    )
                    db.flush()
                    db.commit()
                    db.refresh(new_company)
                    db.refresh(new_client)
                    logger.info(
                        "Provisionamento Stripe concluído company_id=%s client_id=%s",
                        new_company.id,
                        new_client.id,
                    )
                except Exception as exc:
                    db.rollback()
                    logger.exception(
                        "Falha no provisionamento atômico Stripe session_id=%s erro=%s",
                        session_id,
                        exc.__class__.__name__,
                    )
                    raise HTTPException(
                        status_code=500,
                        detail="Falha ao provisionar acesso",
                    ) from exc

    else:
        logger.info(f"Evento sem tratamento específico: {event_type}")

    return {"status": "success", "event_received": True}
