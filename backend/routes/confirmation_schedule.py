# backend/routes/confirmation_schedule.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel
import logging

# Configurar logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Dependências
from backend.db import get_db
from backend.auth import get_current_user
from backend.models import (
   Client,
   ConfirmationScheduleConfig,
   ConfirmationSequence,
)

router = APIRouter()

# ==============================
# Pydantic Schemas
# ==============================
class DailyRange(BaseModel):
    start: str  # Exemplo: "08:00"
    end: str    # Exemplo: "18:00"

class ScheduleData(BaseModel):
    monday: Optional[DailyRange] = None
    tuesday: Optional[DailyRange] = None
    wednesday: Optional[DailyRange] = None
    thursday: Optional[DailyRange] = None
    friday: Optional[DailyRange] = None
    saturday: Optional[DailyRange] = None
    sunday: Optional[DailyRange] = None

class ConfirmationScheduleCreate(BaseModel):
    schedule_data: ScheduleData

class ConfirmationScheduleUpdate(BaseModel):
    schedule_data: ScheduleData

# ==============================
# Rotas
# ==============================
@router.post("/confirmation-schedule/{company_id}", response_model=dict)
def create_confirmation_schedule(
   company_id: int,
   data: ConfirmationScheduleCreate,
   db: Session = Depends(get_db),
   current_user: Client = Depends(get_current_user),
):
   logger.info(f"Iniciando criação de schedule de confirmação para company_id: {company_id}")
   logger.debug(f"Dados recebidos: {data.schedule_data.dict()}")

   if current_user.company_id != company_id:
       logger.error(f"Acesso negado - user company_id: {current_user.company_id}, requested company_id: {company_id}")
       raise HTTPException(403, "Você não tem permissão para criar schedule para outra empresa.")

   try:
       # Verificar config existente
       existing_config = db.query(ConfirmationScheduleConfig).filter_by(company_id=company_id).first()
       if existing_config:
           logger.warning(f"Tentativa de criar config duplicada para company_id: {company_id}")
           raise HTTPException(400, "Já existe configuração de schedule de confirmação para esta empresa.")

       # Buscar sequence
       sequence = db.query(ConfirmationSequence).filter(
           ConfirmationSequence.company_id == company_id
       ).first()
       if not sequence:
           logger.error(f"ConfirmationSequence não encontrada para company_id: {company_id}")
           raise HTTPException(404, "Nenhuma ConfirmationSequence encontrada para esta empresa.")

       # Criar config
       new_schedule = ConfirmationScheduleConfig(
           company_id=company_id,
           confirmation_sequence_id=sequence.id,
           schedule_data=data.schedule_data.dict()
       )
       db.add(new_schedule)
       db.commit()
       db.refresh(new_schedule)

       logger.info(f"Schedule criado com sucesso. ID: {new_schedule.id}")
       return {
           "message": "Confirmation schedule criado com sucesso",
           "id": new_schedule.id,
           "company_id": company_id
       }
   except Exception as e:
       logger.error(f"Erro ao criar schedule: {str(e)}", exc_info=True)
       db.rollback()
       raise

@router.get("/confirmation-schedule/{company_id}", response_model=dict)
def get_confirmation_schedule(
   company_id: int,
   db: Session = Depends(get_db),
   current_user: Client = Depends(get_current_user),
):
   logger.info(f"Buscando schedule de confirmação para company_id: {company_id}")

   if current_user.company_id != company_id:
       logger.error(f"Acesso negado - user company_id: {current_user.company_id}, requested company_id: {company_id}")
       raise HTTPException(403, "Você não tem permissão para ver schedule de outra empresa.")

   config = db.query(ConfirmationScheduleConfig).filter_by(company_id=company_id).first()
   if not config:
       logger.warning(f"Schedule não encontrado para company_id: {company_id}")
       raise HTTPException(404, "Nenhuma configuração de confirmação encontrada para esta empresa.")

   response = {
       "id": config.id,
       "company_id": config.company_id,
       "confirmation_sequence_id": config.confirmation_sequence_id,
       "schedule_data": config.schedule_data
   }

   logger.info(f"Schedule encontrado para company_id: {company_id}")
   logger.debug(f"Dados retornados: {response}")
   return response

@router.put("/confirmation-schedule/{company_id}", response_model=dict)
def update_confirmation_schedule(
   company_id: int,
   data: ConfirmationScheduleUpdate,
   db: Session = Depends(get_db),
   current_user: Client = Depends(get_current_user),
):
   logger.info(f"Iniciando atualização de schedule para company_id: {company_id}")
   logger.debug(f"Dados recebidos: {data.schedule_data.dict()}")

   if current_user.company_id != company_id:
       logger.error(f"Acesso negado - user company_id: {current_user.company_id}, requested company_id: {company_id}")
       raise HTTPException(403, "Você não tem permissão para atualizar schedule de outra empresa.")

   try:
       config = db.query(ConfirmationScheduleConfig).filter_by(company_id=company_id).first()
       if not config:
           logger.warning(f"Schedule não encontrado para atualização - company_id: {company_id}")
           raise HTTPException(404, "Config de confirmação não encontrada para esta empresa.")

       old_data = config.schedule_data
       config.schedule_data = data.schedule_data.dict()
       db.commit()
       db.refresh(config)

       logger.info(f"Schedule atualizado com sucesso - ID: {config.id}")
       logger.debug(f"Dados antigos: {old_data}")
       logger.debug(f"Novos dados: {config.schedule_data}")

       return {
           "message": "Confirmation schedule atualizado com sucesso",
           "id": config.id,
           "company_id": company_id
       }
   except Exception as e:
       logger.error(f"Erro ao atualizar schedule: {str(e)}", exc_info=True)
       db.rollback()
       raise

@router.delete("/confirmation-schedule/{company_id}", response_model=dict)
def delete_confirmation_schedule(
   company_id: int,
   db: Session = Depends(get_db),
   current_user: Client = Depends(get_current_user),
):
   logger.info(f"Iniciando remoção de schedule para company_id: {company_id}")

   if current_user.company_id != company_id:
       logger.error(f"Acesso negado - user company_id: {current_user.company_id}, requested company_id: {company_id}")
       raise HTTPException(403, "Você não tem permissão para deletar schedule de outra empresa.")

   try:
       config = db.query(ConfirmationScheduleConfig).filter_by(company_id=company_id).first()
       if not config:
           logger.warning(f"Schedule não encontrado para exclusão - company_id: {company_id}")
           raise HTTPException(404, "Config de confirmação não encontrada para esta empresa.")

       config_id = config.id
       db.delete(config)
       db.commit()

       logger.info(f"Schedule {config_id} deletado com sucesso para company_id: {company_id}")
       return {
           "message": f"Configuração de schedule de confirmação para a empresa {company_id} deletada com sucesso."
       }
   except Exception as e:
       logger.error(f"Erro ao deletar schedule: {str(e)}", exc_info=True)
       db.rollback()
       raise