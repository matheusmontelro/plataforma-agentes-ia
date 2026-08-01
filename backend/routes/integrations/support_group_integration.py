# backend/routes/integrations/support_group_integration.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from backend.db import get_db
from backend.auth import get_current_user, ensure_user_can_access_company
from backend.models import SupportGroupIntegration

def require_support_group_company_access(
    company_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    ensure_user_can_access_company(user, company_id, db)
    return user


router = APIRouter(dependencies=[Depends(require_support_group_company_access)])

class SupportGroupConfig(BaseModel):
    webhook_scheduling: Optional[str] = None
    webhook_cancellation: Optional[str] = None

@router.get("/{company_id}")
def get_support_group_config(company_id: int, db: Session = Depends(get_db)):
    """
    Retorna a configuração do grupo de suporte para a empresa 'company_id'.
    """
    config = db.query(SupportGroupIntegration).filter_by(company_id=company_id).first()
    if not config:
        return {
            "webhook_scheduling": None,
            "webhook_cancellation": None,
            "message": "Nenhuma integração de grupo de suporte encontrada para esta empresa."
        }
    return {
        "webhook_scheduling": config.webhook_scheduling,
        "webhook_cancellation": config.webhook_cancellation,
    }

@router.post("/{company_id}")
def create_support_group_config(company_id: int, data: SupportGroupConfig, db: Session = Depends(get_db)):
    """
    Cria (ou sobrescreve) uma nova integração do grupo de suporte para a empresa especificada.
    """
    config = db.query(SupportGroupIntegration).filter_by(company_id=company_id).first()
    if config:
        config.webhook_scheduling = data.webhook_scheduling
        config.webhook_cancellation = data.webhook_cancellation
    else:
        config = SupportGroupIntegration(
            company_id=company_id,
            webhook_scheduling=data.webhook_scheduling,
            webhook_cancellation=data.webhook_cancellation
        )
        db.add(config)
    db.commit()
    return {"status": "success", "message": "Integração de grupo de suporte (POST) criada ou sobrescrita."}

@router.put("/{company_id}")
def update_support_group_config(company_id: int, data: SupportGroupConfig, db: Session = Depends(get_db)):
    """
    Atualiza (ou cria) a integração do grupo de suporte para a empresa 'company_id'.
    """
    config = db.query(SupportGroupIntegration).filter_by(company_id=company_id).first()
    if not config:
        # Se não existir, cria (ou retorne 404 se quiser comportamento diferente)
        config = SupportGroupIntegration(
            company_id=company_id,
            webhook_scheduling=data.webhook_scheduling,
            webhook_cancellation=data.webhook_cancellation
        )
        db.add(config)
    else:
        config.webhook_scheduling = data.webhook_scheduling
        config.webhook_cancellation = data.webhook_cancellation
    db.commit()
    return {"status": "success", "message": "Integração de grupo de suporte (PUT) atualizada ou criada."}

@router.delete("/{company_id}")
def delete_support_group_config(company_id: int, db: Session = Depends(get_db)):
    """
    Remove a integração do grupo de suporte para a empresa 'company_id'.
    """
    config = db.query(SupportGroupIntegration).filter_by(company_id=company_id).first()
    if not config:
        raise HTTPException(
            status_code=404,
            detail="Integração de grupo de suporte não encontrada para esta empresa."
        )
    db.delete(config)
    db.commit()
    return {"status": "success", "message": "Integração de grupo de suporte removida com sucesso."}
