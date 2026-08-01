# backend/routes/followup_schedule.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from backend.db import get_db
from backend.models import (
    FollowUpScheduleConfig,
    FollowUpSequence,
    Client
)
from backend.auth import get_current_user

router = APIRouter()

# ==============================
# Pydantic Schemas
# ==============================
class DailyRange(BaseModel):
    start: str
    end: str

class ScheduleData(BaseModel):
    monday: Optional[DailyRange] = None
    tuesday: Optional[DailyRange] = None
    wednesday: Optional[DailyRange] = None
    thursday: Optional[DailyRange] = None
    friday: Optional[DailyRange] = None
    saturday: Optional[DailyRange] = None
    sunday: Optional[DailyRange] = None

class FollowUpScheduleCreate(BaseModel):
    schedule_data: ScheduleData

class FollowUpScheduleUpdate(BaseModel):
    schedule_data: ScheduleData

# ==============================
# Rotas
# ==============================
@router.post("/followup-schedule/{company_id}", response_model=dict)
def create_followup_schedule(
    company_id: int,
    data: FollowUpScheduleCreate,
    db: Session = Depends(get_db),
    current_user: Client = Depends(get_current_user),
):
    """
    Cria uma nova configuração de horários/dias (schedule) para a empresa {company_id}
    sem receber follow_up_sequence_id do frontend, e sim buscando no banco.
    """

    # 1) Verificar se user logado bate com a empresa
    if current_user.company_id != company_id:
        raise HTTPException(
            status_code=403,
            detail="Você não tem permissão para criar schedule para outra empresa."
        )

    # 2) Verificar se já existe config para essa empresa
    existing_config = db.query(FollowUpScheduleConfig).filter_by(company_id=company_id).first()
    if existing_config:
        raise HTTPException(400, "Já existe configuração de schedule para esta empresa.")

    # 3) Buscar a FollowUpSequence para esta empresa
    sequence = db.query(FollowUpSequence).filter(FollowUpSequence.company_id == company_id).first()
    if not sequence:
        raise HTTPException(404, "Nenhuma FollowUpSequence encontrada para esta empresa.")

    # 4) Criar e salvar
    new_schedule = FollowUpScheduleConfig(
        company_id=company_id,
        follow_up_sequence_id=sequence.id,  # obtido automaticamente
        schedule_data=data.schedule_data.dict()
    )
    db.add(new_schedule)
    db.commit()
    db.refresh(new_schedule)

    return {
        "message": "Follow-up schedule criado com sucesso",
        "id": new_schedule.id,
        "company_id": company_id
    }


@router.get("/followup-schedule/{company_id}", response_model=dict)
def get_followup_schedule(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: Client = Depends(get_current_user),
):
    # ...
    if current_user.company_id != company_id:
        raise HTTPException(403, "Você não tem permissão para ver schedule de outra empresa.")

    config = db.query(FollowUpScheduleConfig).filter_by(company_id=company_id).first()
    if not config:
        raise HTTPException(404, "Nenhuma configuração encontrada para esta empresa.")

    return {
        "id": config.id,
        "company_id": config.company_id,
        "follow_up_sequence_id": config.follow_up_sequence_id,  # se existir no model
        "schedule_data": config.schedule_data
    }


@router.put("/followup-schedule/{company_id}", response_model=dict)
def update_followup_schedule(
    company_id: int,
    data: FollowUpScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: Client = Depends(get_current_user),
):
    # ...
    if current_user.company_id != company_id:
        raise HTTPException(403, "Você não tem permissão para atualizar schedule de outra empresa.")

    config = db.query(FollowUpScheduleConfig).filter_by(company_id=company_id).first()
    if not config:
        raise HTTPException(404, "Config não encontrada para esta empresa.")

    config.schedule_data = data.schedule_data.dict()
    db.commit()
    db.refresh(config)

    return {
        "message": "Follow-up schedule atualizado com sucesso",
        "id": config.id,
        "company_id": company_id
    }


@router.delete("/followup-schedule/{company_id}", response_model=dict)
def delete_followup_schedule(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: Client = Depends(get_current_user),
):
    # ...
    if current_user.company_id != company_id:
        raise HTTPException(403, "Você não tem permissão para deletar schedule de outra empresa.")

    config = db.query(FollowUpScheduleConfig).filter_by(company_id=company_id).first()
    if not config:
        raise HTTPException(404, "Config não encontrada para esta empresa.")

    db.delete(config)
    db.commit()

    return {
        "message": f"Configuração de schedule para a empresa {company_id} deletada com sucesso."
    }
