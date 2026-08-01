# backend/routes/nps_routes.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, date

from backend.db import get_db
from backend.auth import get_current_user
from backend.models import NPSResponse, Lead, Contact
from backend.integrations.whatsapp_provider import send_nps_poll
import logging
import json

logger = logging.getLogger(__name__)
router = APIRouter()


def _extract_whatsapp_message_id(result: Dict[str, Any]) -> Optional[str]:
    if not isinstance(result, dict):
        return None
    key = result.get("key") if isinstance(result.get("key"), dict) else {}
    return result.get("messageId") or result.get("id") or key.get("id")

@router.post("/send")
async def send_nps_survey(
    phone: str,
    question: str = "Em uma escala de 1 a 5, como você avalia nosso atendimento?",
    campaign_name: str = "satisfacao_geral",
    context: Optional[Dict[str, Any]] = None,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Envia pesquisa NPS para um contato
    """
    try:
        # Determinar client_id baseado no tipo de usuário
        if hasattr(user, 'client_id'):
            # É um User normal
            client_id = user.client_id
        else:
            # É um Client (master), então o client_id é o próprio id do user
            client_id = user.id

        logger.info(f"[NPS] Iniciando envio para {phone}, user.company_id: {user.company_id}, client_id determinado: {client_id}")

        # Buscar informações do contato
        contact = db.execute(text("""
            SELECT name FROM contacts
            WHERE phone = :phone AND company_id = :company_id
            ORDER BY id DESC LIMIT 1
        """), {"phone": phone, "company_id": user.company_id}).fetchone()

        # Buscar lead se existir
        lead = db.execute(text("""
            SELECT id FROM leads
            WHERE phone = :phone AND company_id = :company_id
            ORDER BY id DESC LIMIT 1
        """), {"phone": phone, "company_id": user.company_id}).fetchone()

        nps_data = {
            "phone": phone,
            "question": question,
            "campaign_name": campaign_name,
            "context": context,
        }

        logger.info(f"[NPS] Enviando enquete via WAHA para {phone}")
        result = send_nps_poll(
            company_id=user.company_id,
            data=nps_data,
            db=db,
        )
        message_id = _extract_whatsapp_message_id(result)
        logger.info("[NPS] Resposta WAHA recebida: message_id_present=%s", bool(message_id))

        # Salvar no banco de dados
        logger.info(f"[NPS] Salvando no banco nps_responses...")
        nps_response = NPSResponse(
            company_id=user.company_id,
            lead_id=lead.id if lead else None,
            contact_phone=phone,
            contact_name=contact.name if contact else None,
            poll_message_id=message_id,
            question=question,
            campaign_name=campaign_name,
            context=context,
            status="sent"
        )

        db.add(nps_response)
        db.commit()
        db.refresh(nps_response)
        logger.info(f"[NPS] Registro salvo na nps_responses, ID: {nps_response.id}")

        # Também salvar na tabela messages para aparecer no chat
        logger.info(f"[NPS] Salvando na tabela messages...")
        from datetime import datetime
        import json

        message_content = {
            "nps_data": {
                "question": question,
                "nps_id": nps_response.id,
                "message_id": message_id,
                "status": "sent",
                "campaign_name": campaign_name
            }
        }

        try:
            db.execute(text("""
                INSERT INTO messages (
                    company_id, contact_phone, sender_phone, message_type, content, from_me,
                    timestamp, client_id
                ) VALUES (
                    :company_id, :contact_phone, :sender_phone, 'nps', :content, true,
                    :timestamp, :client_id
                )
            """), {
                "company_id": user.company_id,
                "contact_phone": phone,
                "sender_phone": "me",
                "content": json.dumps(message_content),
                "timestamp": datetime.utcnow(),
                "client_id": client_id
            })

            db.commit()
            logger.info(f"[NPS] Mensagem salva na tabela messages com sucesso")

        except Exception as msg_error:
            logger.error(f"[NPS] Erro ao salvar na tabela messages: {str(msg_error)}")
            # Não falhar completamente se só der erro na tabela messages
            db.rollback()
            # Re-commit do nps_response que já funcionou
            db.add(nps_response)
            db.commit()

        logger.info(f"NPS enviado para {phone} - Empresa {user.company_id}")

        return {
            "success": True,
            "message_id": message_id,
            "nps_id": nps_response.id,
            "sent_to": phone
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao enviar NPS: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao enviar pesquisa: {str(e)}")

@router.get("/responses")
async def get_nps_responses(
    campaign_name: Optional[str] = None,
    status: Optional[str] = None,
    days_back: int = 30,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Busca respostas NPS da empresa
    """
    try:
        # Query base
        query = """
            SELECT
                id, contact_phone, contact_name, question, score,
                response_text, status, campaign_name, sent_at, answered_at,
                context
            FROM nps_responses
            WHERE company_id = :company_id
            AND sent_at >= :date_from
        """
        params = {
            "company_id": user.company_id,
            "date_from": datetime.now() - timedelta(days=days_back)
        }

        # Filtros opcionais
        if campaign_name:
            query += " AND campaign_name = :campaign_name"
            params["campaign_name"] = campaign_name

        if status:
            query += " AND status = :status"
            params["status"] = status

        query += " ORDER BY sent_at DESC"

        responses = db.execute(text(query), params).fetchall()

        # Calcular estatísticas
        stats = db.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN score IS NOT NULL THEN 1 END) as answered,
                AVG(CASE WHEN score IS NOT NULL THEN score END) as avg_score,
                COUNT(CASE WHEN score >= 9 THEN 1 END) as promoters,
                COUNT(CASE WHEN score <= 6 THEN 1 END) as detractors
            FROM nps_responses
            WHERE company_id = :company_id
            AND sent_at >= :date_from
        """), params).fetchone()

        # Calcular NPS (Promoters % - Detractors %)
        nps_score = None
        if stats.answered > 0:
            promoters_pct = (stats.promoters / stats.answered) * 100
            detractors_pct = (stats.detractors / stats.answered) * 100
            nps_score = promoters_pct - detractors_pct

        return {
            "responses": [dict(r._mapping) for r in responses],
            "statistics": {
                "total_sent": stats.total,
                "total_answered": stats.answered,
                "response_rate": (stats.answered / stats.total * 100) if stats.total > 0 else 0,
                "average_score": float(stats.avg_score) if stats.avg_score else None,
                "nps_score": round(nps_score, 1) if nps_score is not None else None,
                "promoters": stats.promoters,
                "detractors": stats.detractors,
                "passives": stats.answered - stats.promoters - stats.detractors
            }
        }

    except Exception as e:
        logger.error(f"Erro ao buscar respostas NPS: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao buscar respostas: {str(e)}")

@router.post("/bulk-send")
async def send_bulk_nps(
    campaign_name: str,
    question: str = "Em uma escala de 1 a 5, como você avalia nosso atendimento?",
    filter_lead_status: Optional[str] = None,
    days_back: int = 7,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Envia NPS em massa para leads/contatos
    """
    try:
        # Query para buscar contatos elegíveis
        query = """
            SELECT DISTINCT c.phone, c.name
            FROM contacts c
            LEFT JOIN leads l ON l.phone = c.phone AND l.company_id = c.company_id
            WHERE c.company_id = :company_id
            AND c.phone NOT IN (
                SELECT contact_phone FROM nps_responses
                WHERE company_id = :company_id
                AND campaign_name = :campaign_name
                AND sent_at >= :date_from
            )
        """
        params = {
            "company_id": user.company_id,
            "campaign_name": campaign_name,
            "date_from": datetime.now() - timedelta(days=days_back)
        }

        if filter_lead_status:
            query += " AND l.status = :lead_status"
            params["lead_status"] = filter_lead_status

        contacts = db.execute(text(query), params).fetchall()

        sent_count = 0
        errors = []

        for contact in contacts:
            try:
                # Usar a rota de envio individual
                await send_nps_survey(
                    phone=contact.phone,
                    question=question,
                    campaign_name=campaign_name,
                    context={"bulk_send": True, "lead_status": filter_lead_status},
                    user=user,
                    db=db
                )
                sent_count += 1

            except Exception as e:
                errors.append(f"{contact.phone}: {str(e)}")
                logger.error(f"Erro ao enviar NPS para {contact.phone}: {str(e)}")

        return {
            "success": True,
            "sent_count": sent_count,
            "total_contacts": len(contacts),
            "errors": errors[:10]  # Limitar erros mostrados
        }

    except Exception as e:
        logger.error(f"Erro no envio em massa: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro no envio em massa: {str(e)}")

@router.get("/dashboard/metrics")
async def get_nps_dashboard_metrics(
    start_date: Optional[str] = None,  # YYYY-MM-DD
    end_date: Optional[str] = None,
    campaign_name: Optional[str] = None,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retorna métricas NPS otimizadas para o Dashboard
    """
    try:
        # Datas padrão: últimos 30 dias
        if not end_date:
            end_date = datetime.now().date()
        else:
            end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

        if not start_date:
            start_date = end_date - timedelta(days=30)
        else:
            start_date = datetime.strptime(start_date, "%Y-%m-%d").date()

        # Query principal com cálculo correto para escala 1-5
        metrics_query = """
            SELECT
                COUNT(*) as total_sent,
                COUNT(CASE WHEN score IS NOT NULL THEN 1 END) as total_answered,
                AVG(CASE WHEN score IS NOT NULL THEN score END) as avg_score,

                -- Escala 1-5: Promoters (4-5), Passives (3), Detractors (1-2)
                COUNT(CASE WHEN score >= 4 THEN 1 END) as promoters,
                COUNT(CASE WHEN score = 3 THEN 1 END) as passives,
                COUNT(CASE WHEN score <= 2 THEN 1 END) as detractors,

                -- Distribuição por score
                COUNT(CASE WHEN score = 1 THEN 1 END) as score_1,
                COUNT(CASE WHEN score = 2 THEN 1 END) as score_2,
                COUNT(CASE WHEN score = 3 THEN 1 END) as score_3,
                COUNT(CASE WHEN score = 4 THEN 1 END) as score_4,
                COUNT(CASE WHEN score = 5 THEN 1 END) as score_5

            FROM nps_responses
            WHERE company_id = :company_id
            AND sent_at >= :start_date
            AND sent_at <= :end_date
        """

        params = {
            "company_id": user.company_id,
            "start_date": start_date,
            "end_date": end_date + timedelta(days=1)  # Incluir o dia final completo
        }

        if campaign_name:
            metrics_query += " AND campaign_name = :campaign_name"
            params["campaign_name"] = campaign_name

        result = db.execute(text(metrics_query), params).fetchone()

        # Calcular NPS Score (escala 1-5)
        nps_score = 0
        if result.total_answered > 0:
            promoters_pct = (result.promoters / result.total_answered) * 100
            detractors_pct = (result.detractors / result.total_answered) * 100
            nps_score = promoters_pct - detractors_pct

        # Query para evolução diária
        daily_query = """
            SELECT
                DATE(sent_at) as date,
                COUNT(*) as sent,
                COUNT(CASE WHEN score IS NOT NULL THEN 1 END) as answered,
                AVG(CASE WHEN score IS NOT NULL THEN score END) as avg_score
            FROM nps_responses
            WHERE company_id = :company_id
            AND sent_at >= :start_date
            AND sent_at <= :end_date
        """

        if campaign_name:
            daily_query += " AND campaign_name = :campaign_name"

        daily_query += " GROUP BY DATE(sent_at) ORDER BY date"

        daily_results = db.execute(text(daily_query), params).fetchall()

        # Query para campanhas
        campaigns_query = """
            SELECT
                campaign_name,
                COUNT(*) as total,
                COUNT(CASE WHEN score IS NOT NULL THEN 1 END) as answered,
                AVG(CASE WHEN score IS NOT NULL THEN score END) as avg_score
            FROM nps_responses
            WHERE company_id = :company_id
            AND sent_at >= :start_date
            AND sent_at <= :end_date
            GROUP BY campaign_name
            ORDER BY total DESC
        """

        campaigns = db.execute(text(campaigns_query), {
            "company_id": user.company_id,
            "start_date": start_date,
            "end_date": end_date + timedelta(days=1)
        }).fetchall()

        return {
            "period": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            },
            "metrics": {
                "total_sent": result.total_sent,
                "total_answered": result.total_answered,
                "response_rate": round((result.total_answered / result.total_sent * 100), 1) if result.total_sent > 0 else 0,
                "average_score": round(float(result.avg_score), 2) if result.avg_score else 0,
                "nps_score": round(nps_score, 1),
                "distribution": {
                    "promoters": result.promoters,
                    "passives": result.passives,
                    "detractors": result.detractors
                }
            },
            "score_distribution": {
                "1": result.score_1,
                "2": result.score_2,
                "3": result.score_3,
                "4": result.score_4,
                "5": result.score_5
            },
            "daily_evolution": [
                {
                    "date": row.date.isoformat(),
                    "sent": row.sent,
                    "answered": row.answered,
                    "avg_score": round(float(row.avg_score), 2) if row.avg_score else 0,
                    "response_rate": round((row.answered / row.sent * 100), 1) if row.sent > 0 else 0
                }
                for row in daily_results
            ],
            "campaigns": [
                {
                    "name": row.campaign_name or "Sem campanha",
                    "total": row.total,
                    "answered": row.answered,
                    "response_rate": round((row.answered / row.total * 100), 1) if row.total > 0 else 0,
                    "avg_score": round(float(row.avg_score), 2) if row.avg_score else 0
                }
                for row in campaigns
            ]
        }

    except Exception as e:
        logger.error(f"Erro ao buscar métricas dashboard NPS: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao buscar métricas: {str(e)}")

def send_nps_internal(phone: str, question: str, campaign_name: str, context: str, company_id: int, db: Session):
    """
    Função interna para envio de NPS que pode ser chamada por tasks Celery
    """
    try:
        logger.info(f"[NPS-Internal] Iniciando envio para {phone}, company_id: {company_id}")

        # Buscar informações do contato
        contact = db.execute(text("""
            SELECT name FROM contacts
            WHERE phone = :phone AND company_id = :company_id
            ORDER BY id DESC LIMIT 1
        """), {"phone": phone, "company_id": company_id}).fetchone()

        # Buscar lead se existir
        lead = db.execute(text("""
            SELECT id FROM leads
            WHERE phone = :phone AND company_id = :company_id
            ORDER BY id DESC LIMIT 1
        """), {"phone": phone, "company_id": company_id}).fetchone()

        nps_data = {
            "phone": phone,
            "question": question,
            "campaign_name": campaign_name,
            "context": {"source": context},
        }

        logger.info(f"[NPS-Internal] Enviando enquete via WAHA para {phone}")
        result = send_nps_poll(
            company_id=company_id,
            data=nps_data,
            db=db,
        )
        message_id = _extract_whatsapp_message_id(result)
        logger.info("[NPS-Internal] Resposta WAHA recebida: message_id_present=%s", bool(message_id))

        # Salvar no banco de dados
        logger.info(f"[NPS-Internal] Salvando no banco nps_responses...")
        nps_response = NPSResponse(
            company_id=company_id,
            lead_id=lead.id if lead else None,
            contact_phone=phone,
            contact_name=contact.name if contact else None,
            poll_message_id=message_id,
            question=question,
            campaign_name=campaign_name,
            context={"source": context},
            status="sent"
        )

        db.add(nps_response)
        db.commit()
        db.refresh(nps_response)
        logger.info(f"[NPS-Internal] Registro salvo na nps_responses, ID: {nps_response.id}")

        # Também salvar na tabela messages para aparecer no chat
        logger.info(f"[NPS-Internal] Salvando na tabela messages...")
        message_content = {
            "nps_data": {
                "question": question,
                "nps_id": nps_response.id,
                "message_id": message_id,
                "status": "sent",
                "campaign_name": campaign_name
            }
        }

        try:
            # Obter client_id do lead
            client_id_result = db.execute(
                text("SELECT client_id FROM leads WHERE id = :lead_id"),
                {"lead_id": lead.id if lead else None}
            ).fetchone()

            parsed_client_id = None
            if client_id_result and client_id_result.client_id is not None:
                if str(client_id_result.client_id).isdigit():
                    parsed_client_id = int(client_id_result.client_id)

            db.execute(text("""
                INSERT INTO messages (
                    company_id, contact_phone, sender_phone, message_type, content, from_me,
                    timestamp, client_id
                ) VALUES (
                    :company_id, :contact_phone, :sender_phone, 'nps', :content, true,
                    :timestamp, :client_id
                )
            """), {
                "company_id": company_id,
                "contact_phone": phone,
                "sender_phone": "me",
                "content": json.dumps(message_content),
                "timestamp": datetime.utcnow(),
                "client_id": parsed_client_id
            })

            db.commit()
            logger.info(f"[NPS-Internal] Mensagem salva na tabela messages com sucesso")

        except Exception as msg_error:
            logger.error(f"[NPS-Internal] Erro ao salvar na tabela messages: {str(msg_error)}")
            # Não falhar completamente se só der erro na tabela messages
            db.rollback()
            # Re-commit do nps_response que já funcionou
            db.add(nps_response)
            db.commit()

        logger.info(f"NPS enviado para {phone} - Empresa {company_id}")

        return {
            "success": True,
            "message_id": message_id,
            "nps_id": nps_response.id,
            "sent_to": phone
        }

    except Exception as e:
        logger.error(f"Erro ao enviar NPS interno: {str(e)}")
        raise Exception(f"Erro ao enviar pesquisa: {str(e)}")
