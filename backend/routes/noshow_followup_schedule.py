# backend/routes/noshow_followup_schedule.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel

from backend.db import get_db
from backend.models import (
    NoShowFollowUpScheduleConfig,
    NoShowFollowUpSequence
)

router = APIRouter()

# ===========================================
# Pydantic Schemas
# ===========================================
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

class NoShowScheduleCreate(BaseModel):
    schedule_data: ScheduleData

class NoShowScheduleUpdate(BaseModel):
    schedule_data: ScheduleData


# ===========================================
# Rotas
# ===========================================
@router.post("/noshow-schedule/{company_id}", response_model=dict)
def create_noshow_schedule(
    company_id: int,
    data: NoShowScheduleCreate,
    db: Session = Depends(get_db),
):
    """
    Cria uma nova config de horários para no-show na empresa {company_id}.
    """
    # Verifica se já existe config
    existing_config = db.query(NoShowFollowUpScheduleConfig).filter_by(company_id=company_id).first()
    if existing_config:
        raise HTTPException(400, "Já existe configuração de no-show schedule para esta empresa.")

    # Busca a NoShowFollowUpSequence
    seq = db.query(NoShowFollowUpSequence).filter(
        NoShowFollowUpSequence.company_id == company_id
    ).first()

    if not seq:
        raise HTTPException(404, "Nenhuma sequência de no-show encontrada para esta empresa.")

    new_schedule = NoShowFollowUpScheduleConfig(
        company_id=company_id,
        noshow_follow_up_sequence_id=seq.id,
        schedule_data=data.schedule_data.dict()
    )
    db.add(new_schedule)
    db.commit()
    db.refresh(new_schedule)

    return {
        "message": "No-show schedule criado com sucesso",
        "id": new_schedule.id,
        "company_id": company_id
    }


@router.get("/noshow-schedule/{company_id}", response_model=dict)
def get_noshow_schedule(
    company_id: int,
    db: Session = Depends(get_db),
):
    """
    Obtém a config de no-show schedule da empresa {company_id}.
    """
    config = db.query(NoShowFollowUpScheduleConfig).filter_by(company_id=company_id).first()

    if not config:
        raise HTTPException(404, "Nenhuma configuração de no-show schedule encontrada para esta empresa.")

    return {
        "id": config.id,
        "company_id": config.company_id,
        "noshow_follow_up_sequence_id": config.noshow_follow_up_sequence_id,
        "schedule_data": config.schedule_data
    }


@router.put("/noshow-schedule/{company_id}", response_model=dict)
def update_noshow_schedule(
    company_id: int,
    data: NoShowScheduleUpdate,
    db: Session = Depends(get_db),
):
    """
    Atualiza a config de no-show schedule da empresa {company_id}.
    """
    config = db.query(NoShowFollowUpScheduleConfig).filter_by(company_id=company_id).first()

    if not config:
        raise HTTPException(404, "Config de no-show schedule não encontrada para esta empresa.")

    config.schedule_data = data.schedule_data.dict()
    db.commit()
    db.refresh(config)

    return {
        "message": "No-show schedule atualizado com sucesso",
        "id": config.id,
        "company_id": company_id
    }


@router.delete("/noshow-schedule/{company_id}", response_model=dict)
def delete_noshow_schedule(
    company_id: int,
    db: Session = Depends(get_db),
):
    """
    Deleta a config de no-show schedule da empresa {company_id}.
    """
    config = db.query(NoShowFollowUpScheduleConfig).filter_by(company_id=company_id).first()

    if not config:
        raise HTTPException(404, "Config de no-show schedule não encontrada para esta empresa.")

    db.delete(config)
    db.commit()

    return {
        "message": f"Config de no-show schedule para a empresa {company_id} deletada com sucesso."
    }
