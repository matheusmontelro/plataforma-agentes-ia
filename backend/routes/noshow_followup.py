# backend/routes/noshow_followup.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional

from backend.db import get_db
from backend.models import (
    NoShowFollowUpSequence,
    NoShowFollowUpStep,
    NoShowFollowUpMessage
)

# ----------------------------------------------------------------
# Schemas para criação (POST) - sem "id" nos steps/messages
# ----------------------------------------------------------------
class NoShowMessageCreate(BaseModel):
    type: str                 # "text", "image", "audio", "video", etc.
    content: str

class NoShowStepCreate(BaseModel):
    step_number: int
    send_after: int
    send_after_unit: str      # "minutes", "hours", "days"
    messages: List[NoShowMessageCreate]

class NoShowFollowUpSequenceCreate(BaseModel):
    company_id: int
    name: str
    description: str
    steps: List[NoShowStepCreate]


# ----------------------------------------------------------------
# Schemas para UPDATE (PUT) - com "id" opcional
# ----------------------------------------------------------------
class NoShowMessageUpdate(BaseModel):
    id: Optional[int] = None  # se vier, atualizamos o registro
    type: str
    content: str

class NoShowStepUpdate(BaseModel):
    id: Optional[int] = None  # se vier, atualizamos o registro
    step_number: int
    send_after: int
    send_after_unit: str      # "minutes", "hours", "days"
    messages: List[NoShowMessageUpdate]

class NoShowFollowUpSequenceUpdate(BaseModel):
    company_id: int
    name: str
    description: str
    steps: List[NoShowStepUpdate]


# ----------------------------------------------------------------
# Router
# ----------------------------------------------------------------
router = APIRouter()


# ----------------------------------------------------------------
# POST: Cria nova sequência de no-show
# ----------------------------------------------------------------
@router.post("/noshow-followups/{company_id}", response_model=dict)
def create_noshow_followup_sequence(
    company_id: int,
    data: NoShowFollowUpSequenceCreate,
    db: Session = Depends(get_db),
):
    """
    Cria uma nova sequência de no-show para a empresa {company_id}.
    Não aceita 'id' nos steps/messages, tudo é novo.
    """
    if data.company_id != company_id:
        raise HTTPException(status_code=400, detail="company_id mismatch")

    # Verifica se já existe uma sequência para a empresa
    existing_seq = db.query(NoShowFollowUpSequence).filter(
        NoShowFollowUpSequence.company_id == company_id
    ).first()
    if existing_seq:
        raise HTTPException(status_code=400, detail="Já existe uma sequência de no-show para esta empresa.")

    # Cria sequência
    seq = NoShowFollowUpSequence(
        company_id=company_id,
        name=data.name,
        description=data.description
    )
    db.add(seq)
    db.commit()
    db.refresh(seq)

    # Cria steps e messages
    for step_data in data.steps:
        step = NoShowFollowUpStep(
            noshow_follow_up_sequence_id=seq.id,
            step_number=step_data.step_number,
            send_after=step_data.send_after,
            send_after_unit=step_data.send_after_unit
        )
        db.add(step)
        db.commit()
        db.refresh(step)

        for msg_data in step_data.messages:
            msg = NoShowFollowUpMessage(
                noshow_follow_up_step_id=step.id,
                type=msg_data.type,
                content=msg_data.content
            )
            db.add(msg)
        db.commit()

    return {
        "message": "No-show follow-up sequence criada com sucesso",
        "sequence_id": seq.id
    }


# ----------------------------------------------------------------
# GET: Retorna a sequência de no-show pelo company_id
# ----------------------------------------------------------------
@router.get("/noshow-followups/{company_id}", response_model=dict)
def get_noshow_followup_sequence(
    company_id: int,
    db: Session = Depends(get_db),
):
    """
    Retorna a sequência completa de no-show para company_id.
    Supondo que só exista UMA sequência de no-show por empresa.
    """
    seq = db.query(NoShowFollowUpSequence).filter(
        NoShowFollowUpSequence.company_id == company_id
    ).first()

    if not seq:
        raise HTTPException(status_code=404, detail="Nenhuma sequência de no-show encontrada para esta empresa.")

    return {
        "id": seq.id,
        "company_id": seq.company_id,
        "name": seq.name,
        "description": seq.description,
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
            for step in seq.steps
        ]
    }


# ----------------------------------------------------------------
# PUT: Atualiza a sequência de no-show (Upsert em steps/messages)
# ----------------------------------------------------------------
@router.put("/noshow-followups/{company_id}", response_model=dict)
def update_noshow_followup_sequence(
    company_id: int,
    data: NoShowFollowUpSequenceUpdate,
    db: Session = Depends(get_db),
):
    """
    Atualiza a sequência de no-show da empresa {company_id},
    mantendo os mesmos IDs de steps/mensagens se eles continuarem existindo.
    """
    if data.company_id != company_id:
        raise HTTPException(status_code=400, detail="company_id mismatch")

    # Verifica existência da sequência
    seq = db.query(NoShowFollowUpSequence).filter(
        NoShowFollowUpSequence.company_id == company_id
    ).first()

    if not seq:
        raise HTTPException(status_code=404, detail="Nenhuma sequência de no-show encontrada para esta empresa.")

    # Atualiza campos básicos
    seq.name = data.name
    seq.description = data.description
    db.commit()

    # ----------------------------------------------------------------
    # Upsert Steps
    # ----------------------------------------------------------------

    # 1) Obter steps existentes no banco
    existing_steps = db.query(NoShowFollowUpStep).filter(
        NoShowFollowUpStep.noshow_follow_up_sequence_id == seq.id
    ).all()

    # Transforma em dicionário {step_id: step_obj}
    existing_steps_dict = {step.id: step for step in existing_steps}

    # Vamos guardar os IDs de steps que aparecem no payload
    payload_step_ids = []

    # 2) Iterar steps do payload
    for step_data in data.steps:
        step_id = step_data.id

        # Se vier um ID, tentamos achar no banco
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
                upsert_noshow_messages(
                    db=db,
                    step=existing_step,
                    messages_data=step_data.messages
                )
            else:
                # ID veio no payload mas não existe no banco -> cria step novo
                new_step = NoShowFollowUpStep(
                    noshow_follow_up_sequence_id=seq.id,
                    step_number=step_data.step_number,
                    send_after=step_data.send_after,
                    send_after_unit=step_data.send_after_unit
                )
                db.add(new_step)
                db.commit()
                db.refresh(new_step)

                payload_step_ids.append(new_step.id)

                # Cria mensagens para esse step
                upsert_noshow_messages(
                    db=db,
                    step=new_step,
                    messages_data=step_data.messages
                )
        else:
            # Step novo (sem ID)
            new_step = NoShowFollowUpStep(
                noshow_follow_up_sequence_id=seq.id,
                step_number=step_data.step_number,
                send_after=step_data.send_after,
                send_after_unit=step_data.send_after_unit
            )
            db.add(new_step)
            db.commit()
            db.refresh(new_step)

            payload_step_ids.append(new_step.id)

            # Cria mensagens
            upsert_noshow_messages(
                db=db,
                step=new_step,
                messages_data=step_data.messages
            )

    # 3) Deletar steps que não estão no payload
    for old_step in existing_steps:
        if old_step.id not in payload_step_ids:
            db.delete(old_step)
    db.commit()

    db.refresh(seq)
    return {
        "message": "No-show follow-up sequence atualizada com sucesso",
        "sequence_id": seq.id
    }


def upsert_noshow_messages(db: Session, step: NoShowFollowUpStep, messages_data: List[NoShowMessageUpdate]):
    """
    Faz upsert de mensagens para um step específico.
    - Cria ou atualiza cada message
    - Deleta as mensagens que não aparecem mais no payload
    """
    # Mensagens atuais do banco
    existing_msgs = db.query(NoShowFollowUpMessage).filter(
        NoShowFollowUpMessage.noshow_follow_up_step_id == step.id
    ).all()

    existing_msgs_dict = {msg.id: msg for msg in existing_msgs}
    payload_msg_ids = []

    for msg_data in messages_data:
        msg_id = msg_data.id
        if msg_id is not None:
            # Tentar encontrar no banco
            old_msg = existing_msgs_dict.get(msg_id)
            if old_msg:
                # Atualiza
                old_msg.type = msg_data.type
                old_msg.content = msg_data.content
                db.commit()
                payload_msg_ids.append(msg_id)
            else:
                # ID veio mas não existe: cria
                new_msg = NoShowFollowUpMessage(
                    noshow_follow_up_step_id=step.id,
                    type=msg_data.type,
                    content=msg_data.content
                )
                db.add(new_msg)
                db.commit()
                db.refresh(new_msg)
                payload_msg_ids.append(new_msg.id)
        else:
            # Mensagem nova
            new_msg = NoShowFollowUpMessage(
                noshow_follow_up_step_id=step.id,
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
# DELETE: Remove a sequência de no-show
# ----------------------------------------------------------------
@router.delete("/noshow-followups/{company_id}", response_model=dict)
def delete_noshow_followup_sequence(
    company_id: int,
    db: Session = Depends(get_db),
):
    """
    Remove a sequência de no-show da empresa {company_id}.
    """
    seq = db.query(NoShowFollowUpSequence).filter(
        NoShowFollowUpSequence.company_id == company_id
    ).first()

    if not seq:
        raise HTTPException(status_code=404, detail="Nenhuma sequência de no-show encontrada.")

    db.delete(seq)
    db.commit()

    return {"message": f"No-show follow-up sequence da empresa {company_id} excluída com sucesso."}
