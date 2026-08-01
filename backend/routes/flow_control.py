"""
API REST para controle de fluxos automatizados
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime
import logging

from backend.db import get_db
from backend.auth import get_current_user
from backend.models import User, Client
from backend.worker.flow_control import clear_cache, clear_contact_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/flow-control", tags=["flow-control"])

class FlowControlUpdate(BaseModel):
    flow_type: str
    is_paused: bool
    pause_reason: Optional[str] = None

class FlowStatus(BaseModel):
    flow_type: str
    is_paused: bool
    paused_at: Optional[datetime]
    paused_by: Optional[int]
    pause_reason: Optional[str]
    resumed_at: Optional[datetime]
    resumed_by: Optional[int]

class ContactFlowControlUpdate(BaseModel):
    contact_identifier: str
    identifier_type: str = "phone"  # phone ou lead_id
    flow_type: str
    is_paused: bool
    pause_reason: Optional[str] = None
    expire_at: Optional[datetime] = None

class ContactFlowStatus(BaseModel):
    flow_type: str
    is_paused: bool
    pause_reason: Optional[str]
    paused_at: Optional[datetime]
    expire_at: Optional[datetime]

@router.get("/status/{company_id}", response_model=Dict[str, FlowStatus])
async def get_flow_status(
    company_id: int,
    flow_type: Optional[str] = Query(None, description="Filtrar por tipo de fluxo"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retorna status dos fluxos da empresa

    Tipos de fluxo disponíveis:
    - follow_up: Mensagens automatizadas para converter leads
    - noshow: Mensagens para clientes que faltaram
    - confirmation: Confirmação de consultas agendadas
    - pos_consulta: Follow-up após atendimento
    - pos_venda: Acompanhamento após venda
    """

    # Verificar permissão
    # Client (master) tem acesso a todas as empresas associadas
    if isinstance(current_user, Client):
        # Para Client, verificar se tem acesso à empresa
        # Por ora, assumir que tem acesso (pode adicionar verificação de client_companies se necessário)
        pass
    else:
        # Para User, verificar se é admin ou se é da mesma empresa
        is_admin = getattr(current_user, 'is_admin', False)
        if not is_admin and current_user.company_id != company_id:
            raise HTTPException(status_code=403, detail="Sem permissão para visualizar esta empresa")

    query = """
        SELECT
            flow_type,
            is_paused,
            paused_at,
            paused_by,
            pause_reason,
            resumed_at,
            resumed_by
        FROM flow_control_states
        WHERE company_id = :company_id
    """
    params = {"company_id": company_id}

    if flow_type:
        query += " AND flow_type = :flow_type"
        params["flow_type"] = flow_type

    flows = db.execute(text(query), params).fetchall()

    # Incluir todos os tipos de fluxo, mesmo sem registro
    all_flow_types = ['follow_up', 'noshow', 'confirmation', 'pos_consulta', 'pos_venda']
    result = {}

    for ft in all_flow_types:
        flow_data = next((f for f in flows if f.flow_type == ft), None)

        if flow_data:
            result[ft] = FlowStatus(
                flow_type=ft,
                is_paused=flow_data.is_paused,
                paused_at=flow_data.paused_at,
                paused_by=flow_data.paused_by,
                pause_reason=flow_data.pause_reason,
                resumed_at=flow_data.resumed_at,
                resumed_by=flow_data.resumed_by
            )
        else:
            # Se não existe registro, assumir que não está pausado
            result[ft] = FlowStatus(
                flow_type=ft,
                is_paused=False,
                paused_at=None,
                paused_by=None,
                pause_reason=None,
                resumed_at=None,
                resumed_by=None
            )

    return result

@router.post("/toggle/{company_id}")
async def toggle_flow_control(
    company_id: int,
    data: FlowControlUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Pausa ou retoma um fluxo específico

    Body esperado:
    {
        "flow_type": "follow_up",  // ou noshow, confirmation, pos_consulta, pos_venda
        "is_paused": true,         // true para pausar, false para retomar
        "pause_reason": "Feriado"  // opcional
    }
    """

    # Verificar permissão
    # Client (master) tem acesso a todas as empresas associadas
    if isinstance(current_user, Client):
        # Para Client, verificar se tem acesso à empresa
        # Por ora, assumir que tem acesso (pode adicionar verificação de client_companies se necessário)
        pass
    else:
        # Para User, verificar se é admin ou se é da mesma empresa
        is_admin = getattr(current_user, 'is_admin', False)
        if not is_admin and current_user.company_id != company_id:
            raise HTTPException(status_code=403, detail="Sem permissão para modificar esta empresa")

    # Validar flow_type
    valid_types = ['follow_up', 'noshow', 'confirmation', 'pos_consulta', 'pos_venda']
    if data.flow_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Tipo de fluxo inválido. Válidos: {valid_types}")

    try:
        # Determinar user_id (só para User, não Client)
        user_id = None
        if isinstance(current_user, User):
            user_id = current_user.id

        # Upsert do estado
        db.execute(
            text("""
                INSERT INTO flow_control_states (
                    company_id, flow_type, is_paused,
                    paused_at, paused_by, resumed_at, resumed_by, pause_reason
                ) VALUES (
                    :company_id, :flow_type, :is_paused,
                    CASE WHEN :is_paused THEN NOW() ELSE NULL END,
                    CASE WHEN :is_paused THEN CAST(:user_id AS INTEGER) ELSE CAST(NULL AS INTEGER) END,
                    CASE WHEN NOT :is_paused THEN NOW() ELSE NULL END,
                    CASE WHEN NOT :is_paused THEN CAST(:user_id AS INTEGER) ELSE CAST(NULL AS INTEGER) END,
                    :pause_reason
                )
                ON CONFLICT (company_id, flow_type)
                DO UPDATE SET
                    is_paused = EXCLUDED.is_paused,
                    paused_at = CASE
                        WHEN EXCLUDED.is_paused AND NOT flow_control_states.is_paused
                        THEN EXCLUDED.paused_at
                        ELSE flow_control_states.paused_at
                    END,
                    paused_by = CASE
                        WHEN EXCLUDED.is_paused AND NOT flow_control_states.is_paused
                        THEN EXCLUDED.paused_by
                        ELSE flow_control_states.paused_by
                    END,
                    resumed_at = CASE
                        WHEN NOT EXCLUDED.is_paused AND flow_control_states.is_paused
                        THEN EXCLUDED.resumed_at
                        ELSE flow_control_states.resumed_at
                    END,
                    resumed_by = CASE
                        WHEN NOT EXCLUDED.is_paused AND flow_control_states.is_paused
                        THEN EXCLUDED.resumed_by
                        ELSE flow_control_states.resumed_by
                    END,
                    pause_reason = EXCLUDED.pause_reason,
                    updated_at = NOW()
            """),
            {
                "company_id": company_id,
                "flow_type": data.flow_type,
                "is_paused": data.is_paused,
                "user_id": user_id,
                "pause_reason": data.pause_reason
            }
        )
        db.commit()

        # Limpar cache
        clear_cache(company_id, data.flow_type)

        # Log da ação
        action = "pausado" if data.is_paused else "retomado"
        user_info = f"user_id={user_id}" if user_id else f"client={current_user.email}"
        logger.info(
            f"[FlowControl] Fluxo {data.flow_type} {action} para company_id={company_id} "
            f"por {user_info}"
        )

        # Buscar o registro atualizado para retornar
        updated_flow = db.execute(
            text("""
                SELECT flow_type, is_paused, paused_at, paused_by,
                       pause_reason, resumed_at, resumed_by
                FROM flow_control_states
                WHERE company_id = :company_id AND flow_type = :flow_type
            """),
            {"company_id": company_id, "flow_type": data.flow_type}
        ).fetchone()

        return {
            "success": True,
            "message": f"Fluxo {data.flow_type} {action} com sucesso",
            "flow": FlowStatus(
                flow_type=updated_flow.flow_type,
                is_paused=updated_flow.is_paused,
                paused_at=updated_flow.paused_at,
                paused_by=updated_flow.paused_by,
                pause_reason=updated_flow.pause_reason,
                resumed_at=updated_flow.resumed_at,
                resumed_by=updated_flow.resumed_by
            )
        }

    except Exception as e:
        logger.error(f"[FlowControl] Erro ao alterar estado: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Erro ao alterar estado do fluxo")

@router.get("/history/{company_id}")
async def get_flow_history(
    company_id: int,
    flow_type: Optional[str] = Query(None, description="Filtrar por tipo de fluxo"),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retorna histórico de pausas/retomadas

    Por enquanto, retorna apenas o estado atual.
    Futuramente, pode ser implementada uma tabela de histórico
    para auditoria completa.
    """

    # Verificar permissão
    # Client (master) tem acesso a todas as empresas associadas
    if isinstance(current_user, Client):
        # Para Client, verificar se tem acesso à empresa
        # Por ora, assumir que tem acesso (pode adicionar verificação de client_companies se necessário)
        pass
    else:
        # Para User, verificar se é admin ou se é da mesma empresa
        is_admin = getattr(current_user, 'is_admin', False)
        if not is_admin and current_user.company_id != company_id:
            raise HTTPException(status_code=403, detail="Sem permissão")

    # Por enquanto, retorna o estado atual
    # No futuro, implementar tabela de histórico
    return await get_flow_status(company_id, flow_type, current_user, db)

@router.get("/stats")
async def get_flow_control_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retorna estatísticas gerais do sistema de controle de fluxos
    (apenas para admins)
    """

    # Apenas administradores do sistema ou Client (master) podem ver stats gerais
    if isinstance(current_user, Client):
        # Client pode ver stats
        pass
    else:
        is_admin = getattr(current_user, 'is_admin', False)
        if not is_admin:
            raise HTTPException(status_code=403, detail="Apenas administradores")

    # Contar quantos fluxos estão pausados por tipo
    stats = db.execute(
        text("""
            SELECT
                flow_type,
                COUNT(*) FILTER (WHERE is_paused = true) as paused_count,
                COUNT(*) as total_count
            FROM flow_control_states
            GROUP BY flow_type
            ORDER BY flow_type
        """)
    ).fetchall()

    # Total de empresas com algum fluxo pausado
    companies_with_paused = db.execute(
        text("""
            SELECT COUNT(DISTINCT company_id) as count
            FROM flow_control_states
            WHERE is_paused = true
        """)
    ).scalar()

    return {
        "flows": [
            {
                "type": stat.flow_type,
                "paused": stat.paused_count,
                "total": stat.total_count,
                "active": stat.total_count - stat.paused_count
            }
            for stat in stats
        ],
        "companies_with_paused_flows": companies_with_paused or 0,
        "cache_stats": None  # Pode adicionar get_cache_stats() aqui se quiser
    }

# Endpoints para controle individual de contatos

@router.get("/contact/{company_id}/{contact_identifier}")
async def get_contact_flow_status(
    company_id: int,
    contact_identifier: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retorna status dos fluxos para um contato específico
    """
    # Verificar permissão
    if isinstance(current_user, Client):
        pass
    else:
        is_admin = getattr(current_user, 'is_admin', False)
        if not is_admin and current_user.company_id != company_id:
            raise HTTPException(status_code=403, detail="Sem permissão")

    # Buscar pausas ativas do contato
    flows = db.execute(
        text("""
            SELECT flow_type, is_paused, pause_reason,
                   paused_at, expire_at, paused_by
            FROM contact_flow_control
            WHERE company_id = :company_id
              AND contact_identifier = :contact_identifier
              AND is_paused = true
              AND (expire_at IS NULL OR expire_at > NOW())
            ORDER BY flow_type
        """),
        {"company_id": company_id, "contact_identifier": contact_identifier}
    ).fetchall()

    # Incluir todos os tipos de fluxo
    all_flow_types = ['follow_up', 'noshow', 'confirmation', 'pos_consulta', 'pos_venda']
    result = {
        "contact": contact_identifier,
        "flows": {}
    }

    # Criar dict com fluxos pausados
    paused_flows = {f.flow_type: f for f in flows}

    # Verificar se tem pausa global "all"
    has_global_pause = any(f.flow_type == 'all' for f in flows)
    global_pause = next((f for f in flows if f.flow_type == 'all'), None) if has_global_pause else None

    for ft in all_flow_types:
        if ft in paused_flows:
            # Fluxo específico pausado
            f = paused_flows[ft]
            result["flows"][ft] = ContactFlowStatus(
                flow_type=ft,
                is_paused=True,
                pause_reason=f.pause_reason,
                paused_at=f.paused_at,
                expire_at=f.expire_at
            )
        elif has_global_pause:
            # Pausa global afeta este fluxo
            result["flows"][ft] = ContactFlowStatus(
                flow_type=ft,
                is_paused=True,
                pause_reason=global_pause.pause_reason,
                paused_at=global_pause.paused_at,
                expire_at=global_pause.expire_at
            )
        else:
            # Fluxo não pausado
            result["flows"][ft] = ContactFlowStatus(
                flow_type=ft,
                is_paused=False,
                pause_reason=None,
                paused_at=None,
                expire_at=None
            )

    return result

@router.post("/contact/{company_id}/toggle")
async def toggle_contact_flow(
    company_id: int,
    data: ContactFlowControlUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Pausa ou retoma um fluxo para um contato específico

    Body esperado:
    {
        "contact_identifier": "+5500000000007",
        "identifier_type": "phone",
        "flow_type": "follow_up",
        "is_paused": true,
        "pause_reason": "Cliente solicitou parar",
        "expire_at": "2025-08-01T00:00:00Z"  // opcional
    }
    """
    # Verificar permissão
    if isinstance(current_user, Client):
        pass
    else:
        is_admin = getattr(current_user, 'is_admin', False)
        if not is_admin and current_user.company_id != company_id:
            raise HTTPException(status_code=403, detail="Sem permissão")

    # Validar flow_type
    valid_types = ['follow_up', 'noshow', 'confirmation', 'pos_consulta', 'pos_venda', 'all']
    if data.flow_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Tipo de fluxo inválido. Válidos: {valid_types}")

    try:
        # Determinar user_id
        user_id = None
        if isinstance(current_user, User):
            user_id = current_user.id

        if data.is_paused:
            # Pausar fluxo
            db.execute(
                text("""
                    INSERT INTO contact_flow_control (
                        company_id, contact_identifier, identifier_type,
                        flow_type, is_paused, pause_reason, paused_at,
                        paused_by, expire_at
                    ) VALUES (
                        :company_id, :contact_identifier, :identifier_type,
                        :flow_type, true, :reason, NOW(), :user_id, :expire_at
                    )
                    ON CONFLICT (company_id, contact_identifier, flow_type)
                    DO UPDATE SET
                        is_paused = true,
                        pause_reason = EXCLUDED.pause_reason,
                        paused_at = NOW(),
                        paused_by = EXCLUDED.paused_by,
                        expire_at = EXCLUDED.expire_at,
                        resumed_at = NULL,
                        resumed_by = NULL,
                        updated_at = NOW()
                    RETURNING id
                """),
                {
                    "company_id": company_id,
                    "contact_identifier": data.contact_identifier,
                    "identifier_type": data.identifier_type,
                    "flow_type": data.flow_type,
                    "reason": data.pause_reason or "Pausado via interface",
                    "user_id": user_id,
                    "expire_at": data.expire_at
                }
            )

            # Registrar no histórico
            db.execute(
                text("""
                    INSERT INTO contact_flow_control_history (
                        contact_flow_control_id, action, reason, performed_by
                    )
                    SELECT id, 'paused', :reason, :user_id
                    FROM contact_flow_control
                    WHERE company_id = :company_id
                      AND contact_identifier = :contact_identifier
                      AND flow_type = :flow_type
                    ORDER BY id DESC
                    LIMIT 1
                """),
                {
                    "company_id": company_id,
                    "contact_identifier": data.contact_identifier,
                    "flow_type": data.flow_type,
                    "reason": data.pause_reason or "Pausado via interface",
                    "user_id": user_id
                }
            )

            action = "pausado"
        else:
            # Retomar fluxo
            result = db.execute(
                text("""
                    UPDATE contact_flow_control
                    SET is_paused = false,
                        resumed_at = NOW(),
                        resumed_by = :user_id,
                        updated_at = NOW()
                    WHERE company_id = :company_id
                      AND contact_identifier = :contact_identifier
                      AND flow_type = :flow_type
                      AND is_paused = true
                    RETURNING id
                """),
                {
                    "company_id": company_id,
                    "contact_identifier": data.contact_identifier,
                    "flow_type": data.flow_type,
                    "user_id": user_id
                }
            )

            if result.rowcount > 0:
                # Registrar no histórico
                db.execute(
                    text("""
                        INSERT INTO contact_flow_control_history (
                            contact_flow_control_id, action, reason, performed_by
                        )
                        SELECT id, 'resumed', 'Retomado via interface', :user_id
                        FROM contact_flow_control
                        WHERE company_id = :company_id
                          AND contact_identifier = :contact_identifier
                          AND flow_type = :flow_type
                        ORDER BY id DESC
                        LIMIT 1
                    """),
                    {
                        "company_id": company_id,
                        "contact_identifier": data.contact_identifier,
                        "flow_type": data.flow_type,
                        "user_id": user_id
                    }
                )

            action = "retomado"

        db.commit()

        # Limpar cache
        clear_contact_cache(company_id, data.contact_identifier, data.flow_type)

        # Log
        user_info = f"user_id={user_id}" if user_id else f"client={current_user.email}"
        logger.info(
            f"[FlowControl] Fluxo individual {data.flow_type} {action} para "
            f"contato {data.contact_identifier} na company_id={company_id} por {user_info}"
        )

        return {
            "success": True,
            "message": f"Fluxo {data.flow_type} {action} com sucesso para {data.contact_identifier}",
            "contact": data.contact_identifier,
            "flow_type": data.flow_type,
            "is_paused": data.is_paused
        }

    except Exception as e:
        logger.error(f"[FlowControl] Erro ao alterar controle individual: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Erro ao alterar controle do fluxo")

@router.get("/contact/{company_id}/history/{contact_identifier}")
async def get_contact_flow_history(
    company_id: int,
    contact_identifier: str,
    limit: int = Query(50, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retorna histórico de controle de fluxo do contato
    """
    # Verificar permissão
    if isinstance(current_user, Client):
        pass
    else:
        is_admin = getattr(current_user, 'is_admin', False)
        if not is_admin and current_user.company_id != company_id:
            raise HTTPException(status_code=403, detail="Sem permissão")

    history = db.execute(
        text("""
            SELECT
                h.action,
                h.reason,
                h.performed_at,
                h.metadata,
                u.name as performed_by_name,
                cfc.flow_type
            FROM contact_flow_control_history h
            JOIN contact_flow_control cfc ON cfc.id = h.contact_flow_control_id
            LEFT JOIN users u ON u.id = h.performed_by
            WHERE cfc.company_id = :company_id
              AND cfc.contact_identifier = :contact_identifier
            ORDER BY h.performed_at DESC
            LIMIT :limit
        """),
        {
            "company_id": company_id,
            "contact_identifier": contact_identifier,
            "limit": limit
        }
    ).fetchall()

    return {
        "contact": contact_identifier,
        "history": [
            {
                "action": h.action,
                "flow_type": h.flow_type,
                "reason": h.reason,
                "performed_at": h.performed_at,
                "performed_by": h.performed_by_name,
                "metadata": h.metadata
            }
            for h in history
        ]
    }