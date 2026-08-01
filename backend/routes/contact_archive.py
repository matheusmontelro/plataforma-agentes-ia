# backend/routes/contact_archive.py
import logging
import json
from datetime import datetime
from typing import Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel

from ..db import get_db
from ..auth import get_current_user, User, Client, verify_company_access

logger = logging.getLogger(__name__)
router = APIRouter()

class ArchiveRequest(BaseModel):
    reason: Optional[str] = None

class AuditLogger:
    """Sistema de auditoria com checkpoints"""

    @staticmethod
    def log_action(
        db: Session,
        user_id: int,
        company_id: int,
        contact_id: int,
        action_type: str,
        details: dict = None,
        ip_address: str = None,
        user_agent: str = None
    ):
        """Registra ação na tabela de auditoria com checkpoint"""
        try:
            print(f"🔍 AUDIT CHECKPOINT: {action_type} - User: {user_id}, Contact: {contact_id}")

            query = text("""
                INSERT INTO contact_actions_audit
                (contact_id, company_id, user_id, action_type, action_details, ip_address, user_agent)
                VALUES (:contact_id, :company_id, :user_id, :action_type, :details, :ip_address, :user_agent)
                RETURNING id
            """)

            result = db.execute(query, {
                "contact_id": contact_id,
                "company_id": company_id,
                "user_id": user_id,
                "action_type": action_type,
                "details": json.dumps(details) if details else None,
                "ip_address": ip_address,
                "user_agent": user_agent
            })

            audit_id = result.scalar()
            db.commit()

            print(f"✅ AUDIT CHECKPOINT: Ação registrada com ID: {audit_id}")
            return audit_id

        except Exception as e:
            logger.error(f"Erro ao registrar auditoria: {e}")
            db.rollback()
            raise

@router.put("/contacts/{phone}/archive")
async def archive_contact(
    phone: str,
    request: Request,
    archive_data: ArchiveRequest,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db),
    company_id: int = Query(..., description="ID da empresa")
):
    """Arquiva um contato com rastreamento completo"""
    print(f"🚀 CHECKPOINT 1: Iniciando arquivamento - Phone: {phone}, Company: {company_id}")

    try:
        # Verificar acesso à empresa
        user_id = user.id if isinstance(user, Client) else user.id

        if isinstance(user, User):
            has_access = await verify_company_access(user_id, company_id, db)
            if not has_access:
                raise HTTPException(status_code=403, detail="Acesso negado à empresa")

        print(f"✅ CHECKPOINT 2: Acesso verificado para usuário {user_id}")

        # Buscar o contato
        contact_query = text("""
            SELECT id, phone, name, archived
            FROM contacts
            WHERE phone = :phone AND company_id = :company_id
            FOR UPDATE
        """)

        contact = db.execute(contact_query, {
            "phone": phone,
            "company_id": company_id
        }).fetchone()

        if not contact:
            raise HTTPException(status_code=404, detail="Contato não encontrado")

        if contact.archived:
            raise HTTPException(status_code=400, detail="Contato já está arquivado")

        print(f"✅ CHECKPOINT 3: Contato encontrado - ID: {contact.id}, Nome: {contact.name}")

        # Arquivar o contato
        update_query = text("""
            UPDATE contacts
            SET archived = true,
                archived_at = CURRENT_TIMESTAMP,
                archived_by = :user_id,
                archive_reason = :reason
            WHERE id = :contact_id
            RETURNING id, archived_at
        """)

        result = db.execute(update_query, {
            "contact_id": contact.id,
            "user_id": user_id,
            "reason": archive_data.reason
        }).fetchone()

        print(f"✅ CHECKPOINT 4: Contato arquivado em {result.archived_at}")

        # Registrar na auditoria
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("User-Agent")

        audit_id = AuditLogger.log_action(
            db=db,
            user_id=user_id,
            company_id=company_id,
            contact_id=contact.id,
            action_type="ARCHIVED",
            details={
                "phone": phone,
                "name": contact.name,
                "reason": archive_data.reason,
                "archived_at": result.archived_at.isoformat()
            },
            ip_address=ip_address,
            user_agent=user_agent
        )

        db.commit()

        print(f"✅ CHECKPOINT FINAL: Arquivamento concluído com sucesso!")

        return {
            "success": True,
            "message": "Contato arquivado com sucesso",
            "data": {
                "contact_id": contact.id,
                "phone": phone,
                "archived_at": result.archived_at.isoformat(),
                "audit_id": audit_id
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao arquivar contato: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao arquivar contato: {str(e)}")

@router.put("/contacts/{phone}/unarchive")
async def unarchive_contact(
    phone: str,
    request: Request,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db),
    company_id: int = Query(..., description="ID da empresa")
):
    """Desarquiva um contato com rastreamento completo"""
    print(f"🚀 CHECKPOINT 1: Iniciando desarquivamento - Phone: {phone}, Company: {company_id}")

    try:
        # Verificar acesso
        user_id = user.id if isinstance(user, Client) else user.id

        if isinstance(user, User):
            has_access = await verify_company_access(user_id, company_id, db)
            if not has_access:
                raise HTTPException(status_code=403, detail="Acesso negado à empresa")

        print(f"✅ CHECKPOINT 2: Acesso verificado para usuário {user_id}")

        # Buscar contato arquivado
        contact_query = text("""
            SELECT id, phone, name, archived, archived_at, archive_reason
            FROM contacts
            WHERE phone = :phone AND company_id = :company_id
            FOR UPDATE
        """)

        contact = db.execute(contact_query, {
            "phone": phone,
            "company_id": company_id
        }).fetchone()

        if not contact:
            raise HTTPException(status_code=404, detail="Contato não encontrado")

        if not contact.archived:
            raise HTTPException(status_code=400, detail="Contato não está arquivado")

        print(f"✅ CHECKPOINT 3: Contato arquivado encontrado - Arquivado em: {contact.archived_at}")

        # Desarquivar
        update_query = text("""
            UPDATE contacts
            SET archived = false,
                archived_at = NULL,
                archived_by = NULL,
                archive_reason = NULL
            WHERE id = :contact_id
            RETURNING id
        """)

        db.execute(update_query, {"contact_id": contact.id})

        print(f"✅ CHECKPOINT 4: Contato desarquivado com sucesso")

        # Registrar na auditoria
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("User-Agent")

        audit_id = AuditLogger.log_action(
            db=db,
            user_id=user_id,
            company_id=company_id,
            contact_id=contact.id,
            action_type="UNARCHIVED",
            details={
                "phone": phone,
                "name": contact.name,
                "previous_archived_at": contact.archived_at.isoformat() if contact.archived_at else None,
                "previous_reason": contact.archive_reason
            },
            ip_address=ip_address,
            user_agent=user_agent
        )

        db.commit()

        print(f"✅ CHECKPOINT FINAL: Desarquivamento concluído com sucesso!")

        return {
            "success": True,
            "message": "Contato desarquivado com sucesso",
            "data": {
                "contact_id": contact.id,
                "phone": phone,
                "audit_id": audit_id
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao desarquivar contato: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao desarquivar contato: {str(e)}")

@router.get("/contacts/audit-log")
async def get_audit_log(
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db),
    company_id: int = Query(...),
    contact_id: Optional[int] = Query(None),
    action_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """Obtém o log de auditoria de ações em contatos"""
    print(f"🔍 CHECKPOINT: Consultando logs de auditoria - Company: {company_id}")

    try:
        # Verificar acesso
        user_id = user.id if isinstance(user, Client) else user.id

        if isinstance(user, User):
            has_access = await verify_company_access(user_id, company_id, db)
            if not has_access:
                raise HTTPException(status_code=403, detail="Acesso negado")

        # Construir query
        query = """
            SELECT
                a.id,
                a.contact_id,
                a.action_type,
                a.action_details,
                a.created_at,
                a.ip_address,
                u.name as user_name,
                u.email as user_email,
                c.phone as contact_phone,
                c.name as contact_name
            FROM contact_actions_audit a
            JOIN users u ON a.user_id = u.id
            JOIN contacts c ON a.contact_id = c.id
            WHERE a.company_id = :company_id
        """

        params = {"company_id": company_id}

        if contact_id:
            query += " AND a.contact_id = :contact_id"
            params["contact_id"] = contact_id

        if action_type:
            query += " AND a.action_type = :action_type"
            params["action_type"] = action_type

        query += " ORDER BY a.created_at DESC LIMIT :limit OFFSET :offset"
        params["limit"] = limit
        params["offset"] = offset

        results = db.execute(text(query), params).fetchall()

        # Contar total
        count_query = """
            SELECT COUNT(*) FROM contact_actions_audit a
            WHERE a.company_id = :company_id
        """
        if contact_id:
            count_query += " AND a.contact_id = :contact_id"
        if action_type:
            count_query += " AND a.action_type = :action_type"

        total = db.execute(text(count_query), params).scalar()

        logs = []
        for r in results:
            logs.append({
                "id": r.id,
                "contact_id": r.contact_id,
                "contact_phone": r.contact_phone,
                "contact_name": r.contact_name,
                "action_type": r.action_type,
                "action_details": r.action_details,
                "user_name": r.user_name,
                "user_email": r.user_email,
                "created_at": r.created_at.isoformat(),
                "ip_address": r.ip_address
            })

        print(f"✅ CHECKPOINT: {len(logs)} logs encontrados de {total} total")

        return {
            "logs": logs,
            "total": total,
            "has_more": (offset + limit) < total
        }

    except Exception as e:
        logger.error(f"Erro ao buscar logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao buscar logs: {str(e)}")