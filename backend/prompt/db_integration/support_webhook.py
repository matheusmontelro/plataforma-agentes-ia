from sqlalchemy.orm import Session
from sqlalchemy.sql import text
import logging
import requests
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

def get_webhook_url(db: Session, company_id: int, webhook_type: str) -> Optional[str]:
    """
    Obtém a URL do webhook baseado no tipo (scheduling, cancellation, etc)
    do banco de dados support_group_integrations.

    Args:
        db (Session): Sessão do SQLAlchemy
        company_id (int): ID da empresa
        webhook_type (str): Tipo do webhook (ex: 'webhook_scheduling', 'webhook_cancellation')

    Returns:
        Optional[str]: URL do webhook ou None se não encontrado
    """
    try:
        row = db.execute(
            text(f"""
                SELECT {webhook_type}
                FROM support_group_integrations
                WHERE company_id = :cid
                LIMIT 1
            """),
            {"cid": company_id}
        ).fetchone()

        if not row:
            logger.warning(
                f"[Webhook] Não há registro em support_group_integrations para "
                f"company_id={company_id}."
            )
            return None

        return row[0]  # Retorna o valor da coluna webhook_type

    except Exception as e:
        logger.error(f"[Webhook] Erro ao buscar {webhook_type}: {e}")
        return None

def send_to_webhook(
    db: Session,
    company_id: int,
    phone: str,
    payload_data: Dict[str, Any],
    api_key: str,
    webhook_type: str
) -> bool:
    """
    Envia dados para o webhook especificado.

    Args:
        db (Session): Sessão do SQLAlchemy
        company_id (int): ID da empresa
        phone (str): Telefone do lead
        payload_data (Dict[str, Any]): Dados a serem enviados
        api_key (str): Chave da API para autenticação
        webhook_type (str): Tipo do webhook (ex: 'webhook_scheduling', 'webhook_cancellation')

    Returns:
        bool: True se o envio foi bem sucedido, False caso contrário
    """
    # 1. Obtém a URL do webhook
    webhook_url = get_webhook_url(db, company_id, webhook_type)
    if not webhook_url:
        return False

    # 2. Busca informações do lead
    lead_row = db.execute(text("""
        SELECT id AS lead_id,
               client_id AS client_id_db
        FROM leads
        WHERE phone = :p
          AND company_id = :cid
        LIMIT 1
    """), {"p": phone, "cid": company_id}).fetchone()

    if not lead_row:
        logger.warning(f"[Webhook] Nenhum lead encontrado para phone={phone}, company_id={company_id}.")
        lead_id = None
        client_id_db = None
    else:
        lead_row = lead_row._mapping
        lead_id = lead_row['lead_id']
        client_id_db = lead_row['client_id_db']

    # 3. Monta o payload completo
    full_payload = {
        "company_id": company_id,
        "client_id": client_id_db,
        "lead_id": lead_id,
        "api_key": api_key,
        **payload_data  # Inclui os dados específicos do payload
    }

    # 4. Configura os headers
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
    }

    # 5. Envia a requisição
    try:
        resp = requests.post(webhook_url, json=full_payload, headers=headers, timeout=60)
        success = resp.status_code in (200, 201, 202)

        log_msg = (
            f"[Webhook] Dados enviados para {webhook_type} ({webhook_url}). "
            f"Status code: {resp.status_code}"
        )
        if success:
            logger.info(log_msg)
        else:
            logger.error(f"{log_msg}. Response: {resp.text}")

        return success

    except requests.RequestException as e:
        logger.error(f"[Webhook] Erro ao enviar dados para {webhook_type}: {e}")
        return False
