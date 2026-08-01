# backend/routes/pos_consulta_followup_routes.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from backend.db import get_db
from backend.models import (
    PosConsultaSequence,
    PosConsultaStep,
    PosConsultaMessage,
    PosConsultaScheduleConfig
)

# ----------------------------------------------------------------
# Schemas para criação (POST) - sem "id" nos steps/messages
# ----------------------------------------------------------------
class PosConsultaMessageCreate(BaseModel):
    type: str                 # "text", "image", "audio", "video"
    content: str

class PosConsultaStepCreate(BaseModel):
    step_number: int
    send_after: int
    send_after_unit: str      # "minutes", "hours", "days"
    messages: List[PosConsultaMessageCreate]

class PosConsultaSequenceCreate(BaseModel):
    company_id: int
    name: str
    description: str
    steps: List[PosConsultaStepCreate]

# ----------------------------------------------------------------
# Schemas para UPDATE (PUT) - com "id" opcional
# ----------------------------------------------------------------
class PosConsultaMessageUpdate(BaseModel):
    id: Optional[int] = None
    type: str
    content: str

class PosConsultaStepUpdate(BaseModel):
    id: Optional[int] = None
    step_number: int
    send_after: int
    send_after_unit: str
    messages: List[PosConsultaMessageUpdate]

class PosConsultaSequenceUpdate(BaseModel):
    company_id: int
    name: str
    description: str
    steps: List[PosConsultaStepUpdate]

# ----------------------------------------------------------------
# Schemas para Schedule
# ----------------------------------------------------------------
class PosConsultaScheduleConfigData(BaseModel):
    schedule_data: dict

# ----------------------------------------------------------------
# Router
# ----------------------------------------------------------------
router = APIRouter()

# ----------------------------------------------------------------
# POST: Cria nova sequência pós-consulta
# ----------------------------------------------------------------
@router.post("/pos-consulta-followups/{company_id}", response_model=dict)
def create_pos_consulta_sequence(
    company_id: int,
    data: PosConsultaSequenceCreate,
    db: Session = Depends(get_db),
):
    """
    Cria uma nova sequência de follow-up pós-consulta para a empresa.
    """
    if data.company_id != company_id:
        raise HTTPException(status_code=400, detail="company_id mismatch")

    # Verifica se já existe uma sequência para a empresa
    existing_seq = db.query(PosConsultaSequence).filter(
        PosConsultaSequence.company_id == company_id
    ).first()
    if existing_seq:
        raise HTTPException(status_code=400, detail="Já existe uma sequência pós-consulta para esta empresa.")

    # Cria sequência
    seq = PosConsultaSequence(
        company_id=company_id,
        name=data.name,
        description=data.description
    )
    db.add(seq)
    db.commit()
    db.refresh(seq)

    # Cria steps e messages
    for step_data in data.steps:
        step = PosConsultaStep(
            pos_consulta_sequence_id=seq.id,
            step_number=step_data.step_number,
            send_after=step_data.send_after,
            send_after_unit=step_data.send_after_unit
        )
        db.add(step)
        db.commit()
        db.refresh(step)

        for msg_data in step_data.messages:
            msg = PosConsultaMessage(
                pos_consulta_step_id=step.id,
                type=msg_data.type,
                content=msg_data.content
            )
            db.add(msg)
        db.commit()

    return {
        "message": "Sequência pós-consulta criada com sucesso",
        "sequence_id": seq.id
    }

# ----------------------------------------------------------------
# GET: Retorna a sequência pós-consulta pelo company_id
# ----------------------------------------------------------------
@router.get("/pos-consulta-followups/{company_id}", response_model=dict)
def get_pos_consulta_sequence(
    company_id: int,
    db: Session = Depends(get_db),
):
    """
    Retorna a sequência completa de follow-up pós-consulta para company_id.
    """
    seq = db.query(PosConsultaSequence).filter(
        PosConsultaSequence.company_id == company_id
    ).first()

    if not seq:
        raise HTTPException(status_code=404, detail="Nenhuma sequência pós-consulta encontrada para esta empresa.")

    return {
        "id": seq.id,
        "company_id": seq.company_id,
        "name": seq.name,
        "description": seq.description,
        "active": seq.active,
        "steps": [
            {
                "id": step.id,
                "step_number": step.step_number,
                "send_after": step.send_after,
                "send_after_unit": step.send_after_unit,
                "messages": [
                    {
                        "id": msg.id,
                        "type": msg.type,
                        "content": msg.content
                    }
                    for msg in step.messages
                ]
            }
            for step in sorted(seq.steps, key=lambda x: x.step_number)
        ]
    }

# ----------------------------------------------------------------
# PUT: Atualiza a sequência pós-consulta (Upsert em steps/messages)
# ----------------------------------------------------------------
@router.put("/pos-consulta-followups/{company_id}", response_model=dict)
def update_pos_consulta_sequence(
    company_id: int,
    data: PosConsultaSequenceUpdate,
    db: Session = Depends(get_db),
):
    """
    Atualiza a sequência de follow-up pós-consulta da empresa,
    mantendo os mesmos IDs de steps/mensagens se eles continuarem existindo.
    """
    if data.company_id != company_id:
        raise HTTPException(status_code=400, detail="company_id mismatch")

    # Verifica existência da sequência
    seq = db.query(PosConsultaSequence).filter(
        PosConsultaSequence.company_id == company_id
    ).first()

    if not seq:
        raise HTTPException(status_code=404, detail="Nenhuma sequência pós-consulta encontrada para esta empresa.")

    # Atualiza campos básicos
    seq.name = data.name
    seq.description = data.description
    db.commit()

    # Upsert Steps
    existing_steps = db.query(PosConsultaStep).filter(
        PosConsultaStep.pos_consulta_sequence_id == seq.id
    ).all()

    existing_steps_dict = {step.id: step for step in existing_steps}
    payload_step_ids = []

    for step_data in data.steps:
        step_id = step_data.id

        if step_id is not None:
            existing_step = existing_steps_dict.get(step_id)
            if existing_step:
                # Atualiza esse step
                existing_step.step_number = step_data.step_number
                existing_step.send_after = step_data.send_after
                existing_step.send_after_unit = step_data.send_after_unit
                db.commit()

                payload_step_ids.append(step_id)

                # Upsert de mensagens
                upsert_pos_consulta_messages(
                    db=db,
                    step=existing_step,
                    messages_data=step_data.messages
                )
            else:
                # Cria step novo
                new_step = PosConsultaStep(
                    pos_consulta_sequence_id=seq.id,
                    step_number=step_data.step_number,
                    send_after=step_data.send_after,
                    send_after_unit=step_data.send_after_unit
                )
                db.add(new_step)
                db.commit()
                db.refresh(new_step)

                payload_step_ids.append(new_step.id)

                upsert_pos_consulta_messages(
                    db=db,
                    step=new_step,
                    messages_data=step_data.messages
                )
        else:
            # Step novo (sem ID)
            new_step = PosConsultaStep(
                pos_consulta_sequence_id=seq.id,
                step_number=step_data.step_number,
                send_after=step_data.send_after,
                send_after_unit=step_data.send_after_unit
            )
            db.add(new_step)
            db.commit()
            db.refresh(new_step)

            payload_step_ids.append(new_step.id)

            upsert_pos_consulta_messages(
                db=db,
                step=new_step,
                messages_data=step_data.messages
            )

    # Deletar steps que não estão no payload
    for old_step in existing_steps:
        if old_step.id not in payload_step_ids:
            db.delete(old_step)
    db.commit()

    db.refresh(seq)
    return {
        "message": "Sequência pós-consulta atualizada com sucesso",
        "sequence_id": seq.id
    }

def upsert_pos_consulta_messages(db: Session, step: PosConsultaStep, messages_data: List[PosConsultaMessageUpdate]):
    """
    Faz upsert de mensagens para um step específico.
    """
    existing_msgs = db.query(PosConsultaMessage).filter(
        PosConsultaMessage.pos_consulta_step_id == step.id
    ).all()

    existing_msgs_dict = {msg.id: msg for msg in existing_msgs}
    payload_msg_ids = []

    for msg_data in messages_data:
        msg_id = msg_data.id
        if msg_id is not None:
            old_msg = existing_msgs_dict.get(msg_id)
            if old_msg:
                # Atualiza
                old_msg.type = msg_data.type
                old_msg.content = msg_data.content
                db.commit()
                payload_msg_ids.append(msg_id)
            else:
                # Cria
                new_msg = PosConsultaMessage(
                    pos_consulta_step_id=step.id,
                    type=msg_data.type,
                    content=msg_data.content
                )
                db.add(new_msg)
                db.commit()
                db.refresh(new_msg)
                payload_msg_ids.append(new_msg.id)
        else:
            # Mensagem nova
            new_msg = PosConsultaMessage(
                pos_consulta_step_id=step.id,
                type=msg_data.type,
                content=msg_data.content
            )
            db.add(new_msg)
            db.commit()
            db.refresh(new_msg)
            payload_msg_ids.append(new_msg.id)

    # Deletar mensagens que não foram enviadas
    for old_msg in existing_msgs:
        if old_msg.id not in payload_msg_ids:
            db.delete(old_msg)
    db.commit()

# ----------------------------------------------------------------
# DELETE: Remove a sequência pós-consulta
# ----------------------------------------------------------------
@router.delete("/pos-consulta-followups/{company_id}", response_model=dict)
def delete_pos_consulta_sequence(
    company_id: int,
    db: Session = Depends(get_db),
):
    """
    Remove a sequência de follow-up pós-consulta da empresa.
    """
    seq = db.query(PosConsultaSequence).filter(
        PosConsultaSequence.company_id == company_id
    ).first()

    if not seq:
        raise HTTPException(status_code=404, detail="Nenhuma sequência pós-consulta encontrada.")

    db.delete(seq)
    db.commit()

    return {"message": f"Sequência pós-consulta da empresa {company_id} excluída com sucesso."}

# ----------------------------------------------------------------
# Schedule Configuration Routes
# ----------------------------------------------------------------

@router.post("/pos-consulta-followups/{company_id}/schedule", response_model=dict)
def create_pos_consulta_schedule_config(
    company_id: int,
    data: PosConsultaScheduleConfigData,
    db: Session = Depends(get_db),
):
    """Cria configuração de horários para sequência pós-consulta."""

    # Verificar se existe sequência
    seq = db.query(PosConsultaSequence).filter(
        PosConsultaSequence.company_id == company_id
    ).first()

    if not seq:
        raise HTTPException(status_code=404, detail="Sequência pós-consulta não encontrada.")

    # Verificar se já existe config
    existing_config = db.query(PosConsultaScheduleConfig).filter(
        PosConsultaScheduleConfig.company_id == company_id,
        PosConsultaScheduleConfig.pos_consulta_sequence_id == seq.id
    ).first()

    if existing_config:
        raise HTTPException(status_code=400, detail="Configuração de horários já existe.")

    config = PosConsultaScheduleConfig(
        company_id=company_id,
        pos_consulta_sequence_id=seq.id,
        schedule_data=data.schedule_data
    )
    db.add(config)
    db.commit()
    db.refresh(config)

    return {
        "message": "Configuração de horários criada com sucesso",
        "config_id": config.id
    }

@router.get("/pos-consulta-followups/{company_id}/schedule", response_model=dict)
def get_pos_consulta_schedule_config(
    company_id: int,
    db: Session = Depends(get_db),
):
    """Obtém configuração de horários para sequência pós-consulta."""

    # Verificar se existe sequência
    seq = db.query(PosConsultaSequence).filter(
        PosConsultaSequence.company_id == company_id
    ).first()

    if not seq:
        raise HTTPException(status_code=404, detail="Sequência pós-consulta não encontrada.")

    config = db.query(PosConsultaScheduleConfig).filter(
        PosConsultaScheduleConfig.company_id == company_id,
        PosConsultaScheduleConfig.pos_consulta_sequence_id == seq.id
    ).first()

    if not config:
        raise HTTPException(status_code=404, detail="Configuração de horários não encontrada.")

    return {
        "id": config.id,
        "company_id": config.company_id,
        "pos_consulta_sequence_id": config.pos_consulta_sequence_id,
        "schedule_data": config.schedule_data
    }

@router.put("/pos-consulta-followups/{company_id}/schedule", response_model=dict)
def update_pos_consulta_schedule_config(
    company_id: int,
    data: PosConsultaScheduleConfigData,
    db: Session = Depends(get_db),
):
    """Atualiza configuração de horários para sequência pós-consulta."""

    # Verificar se existe sequência
    seq = db.query(PosConsultaSequence).filter(
        PosConsultaSequence.company_id == company_id
    ).first()

    if not seq:
        raise HTTPException(status_code=404, detail="Sequência pós-consulta não encontrada.")

    config = db.query(PosConsultaScheduleConfig).filter(
        PosConsultaScheduleConfig.company_id == company_id,
        PosConsultaScheduleConfig.pos_consulta_sequence_id == seq.id
    ).first()

    if not config:
        raise HTTPException(status_code=404, detail="Configuração de horários não encontrada.")

    config.schedule_data = data.schedule_data
    db.commit()

    return {
        "message": "Configuração de horários atualizada com sucesso",
        "config_id": config.id
    }

@router.delete("/pos-consulta-followups/{company_id}/schedule", response_model=dict)
def delete_pos_consulta_schedule_config(
    company_id: int,
    db: Session = Depends(get_db),
):
    """Remove configuração de horários para sequência pós-consulta."""

    config = db.query(PosConsultaScheduleConfig).filter(
        PosConsultaScheduleConfig.company_id == company_id
    ).first()

    if not config:
        raise HTTPException(status_code=404, detail="Configuração de horários não encontrada.")

    db.delete(config)
    db.commit()

    return {"message": "Configuração de horários removida com sucesso."}