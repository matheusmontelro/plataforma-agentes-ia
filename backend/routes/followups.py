# backend/routes/followups.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from backend.db import get_db
from backend.auth import get_current_user, ensure_user_can_access_company
from backend.models import FollowUpSequence, FollowUpStep, FollowUpMessage
from pydantic import BaseModel

# ------------------------------------------------------------------
# Pydantic Schemas
# ------------------------------------------------------------------

class MessageCreate(BaseModel):
    type: str
    content: str

class StepCreate(BaseModel):
    step_number: int
    send_after: int
    send_after_unit: str
    messages: List[MessageCreate]

class FollowUpSequenceCreate(BaseModel):
    client_id: str  # ou int, a depender da sua base
    company_id: int
    name: str
    description: str
    steps: List[StepCreate]
    linked_stage_id: Optional[int] = None  # Novo campo opcional

# ---------------
# NOVOS SCHEMAS
# ---------------
class FollowUpMessageUpdate(BaseModel):
    """Schema para criar/atualizar mensagens; 'id' é opcional."""
    id: Optional[int] = None
    type: str
    content: str

class FollowUpStepUpdate(BaseModel):
    """Schema para criar/atualizar steps; 'id' é opcional."""
    id: Optional[int] = None
    step_number: int
    send_after: int
    send_after_unit: str
    messages: List[FollowUpMessageUpdate]

class FollowUpSequenceUpdate(BaseModel):
    """Schema para criar/atualizar a sequência completa."""
    client_id: str
    company_id: int
    name: str
    description: str
    steps: List[FollowUpStepUpdate]
    linked_stage_id: Optional[int] = None

# ------------------------------------------------------------------
# Router
# ------------------------------------------------------------------

router = APIRouter()

@router.post("/followups/{company_id}", response_model=dict)
def create_followup_sequence(
    company_id: int,
    data: FollowUpSequenceCreate,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    Cria uma nova sequência de follow-up para a empresa {company_id}.
    """

    # Verifica se o company_id do body (data.company_id) bate com o que veio na rota
    if data.company_id != company_id:
        raise HTTPException(status_code=400, detail="company_id mismatch")
    ensure_user_can_access_company(user, company_id, db)

    # (Opcional) Se quiser impedir mais de uma sequência por empresa, verifique se já existe:
    # existing_seq = db.query(FollowUpSequence).filter(FollowUpSequence.company_id == company_id).first()
    # if existing_seq:
    #     raise HTTPException(status_code=400, detail="Já existe uma sequência para esta empresa.")

    seq = FollowUpSequence(
        client_id=data.client_id,
        company_id=company_id,        # ou data.company_id (já verificado)
        name=data.name,
        description=data.description
    )
    db.add(seq)
    db.commit()
    db.refresh(seq)

    # Cria steps e messages
    for step_data in data.steps:
        step = FollowUpStep(
            follow_up_sequence_id=seq.id,
            step_number=step_data.step_number,
            send_after=step_data.send_after,
            send_after_unit=step_data.send_after_unit
        )
        db.add(step)
        db.commit()
        db.refresh(step)

        for msg_data in step_data.messages:
            msg = FollowUpMessage(
                follow_up_step_id=step.id,
                type=msg_data.type,
                content=msg_data.content
            )
            db.add(msg)
        db.commit()

    # Se veio linked_stage_id, faz o vínculo
    if data.linked_stage_id:
        from backend.models import PipelineStage
        stage = db.query(PipelineStage).filter(PipelineStage.id == data.linked_stage_id).first()
        if stage and stage.pipeline.company_id == company_id:
            stage.follow_up_sequence_id = seq.id
            db.commit()

    return {
        "message": "Follow-up sequence created successfully",
        "sequence_id": seq.id
    }

@router.get("/followups/{company_id}", response_model=List[dict])
def get_followup_sequences(
    company_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    Retorna TODAS as sequências da empresa.
    """
    ensure_user_can_access_company(user, company_id, db)
    seqs = db.query(FollowUpSequence).filter(FollowUpSequence.company_id == company_id).all()

    result = []
    for seq in seqs:
        result.append({
            "id": seq.id,
            "client_id": seq.client_id,
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
        })
    return result

@router.get("/followups/sequence/{sequence_id}", response_model=dict)
def get_single_followup_sequence(
    sequence_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    Retorna UMA sequência específica pelo ID.
    """
    seq = db.query(FollowUpSequence).filter(FollowUpSequence.id == sequence_id).first()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence not found")
    ensure_user_can_access_company(user, seq.company_id, db)

    return {
        "id": seq.id,
        "client_id": seq.client_id,
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

@router.put("/followups/{sequence_id}", response_model=dict)
def update_followup_sequence(
    sequence_id: int,
    data: FollowUpSequenceUpdate,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    Atualiza a sequência de follow-up de forma "upsert", ou seja:
    - Mantendo o 'id' de steps e messages já existentes (atualiza os campos).
    - Criando novos registros somente se não houver 'id' no payload.
    - Excluindo no banco apenas aquilo que sumir do payload.
    Isso evita perder referências na tabela follow_up_executions.
    """
    # 2) Localiza a sequência no banco pelo ID
    seq = db.query(FollowUpSequence).filter(
        FollowUpSequence.id == sequence_id
    ).first()

    if not seq:
        raise HTTPException(status_code=404, detail="Sequence not found")
    ensure_user_can_access_company(user, seq.company_id, db)

    # Verifica se pertence à empresa correta (segurança)
    # Verifica se pertence à empresa correta (segurança)
    # A verificação é feita abaixo comparando com data.company_id

    if seq.company_id != data.company_id:
         raise HTTPException(status_code=403, detail="Sequence does not belong to this company")

    # 3) Atualiza campos básicos da sequência
    seq.client_id = data.client_id
    seq.name = data.name
    seq.description = data.description
    db.commit()
    db.refresh(seq)

    # 4) Carrega steps existentes e cria um dicionário para acesso rápido
    existing_steps = db.query(FollowUpStep).filter(
        FollowUpStep.follow_up_sequence_id == seq.id
    ).all()
    steps_map = {s.id: s for s in existing_steps}

    # Lista de IDs que ainda existem no payload (para excluir o resto)
    updated_step_ids = []

    # 5) Itera pelos steps vindos no payload
    for step_data in data.steps:
        if step_data.id:
            # Se veio 'id' no payload, tenta achar no dicionário
            step_obj = steps_map.get(step_data.id)
            if step_obj:
                # Step existente: atualiza
                step_obj.step_number = step_data.step_number
                step_obj.send_after = step_data.send_after
                step_obj.send_after_unit = step_data.send_after_unit
                db.commit()
                db.refresh(step_obj)
            else:
                # Step não existe no banco: cria novo
                step_obj = FollowUpStep(
                    follow_up_sequence_id=seq.id,
                    step_number=step_data.step_number,
                    send_after=step_data.send_after,
                    send_after_unit=step_data.send_after_unit
                )
                db.add(step_obj)
                db.commit()
                db.refresh(step_obj)
        else:
            # Step sem 'id' => criar novo
            step_obj = FollowUpStep(
                follow_up_sequence_id=seq.id,
                step_number=step_data.step_number,
                send_after=step_data.send_after,
                send_after_unit=step_data.send_after_unit
            )
            db.add(step_obj)
            db.commit()
            db.refresh(step_obj)

        updated_step_ids.append(step_obj.id)

        # --- UPSERT DE MESSAGES ---
        existing_msgs = db.query(FollowUpMessage).filter(
            FollowUpMessage.follow_up_step_id == step_obj.id
        ).all()
        msgs_map = {m.id: m for m in existing_msgs}

        updated_msg_ids = []

        for msg_data in step_data.messages:
            if msg_data.id:
                # Mensagem existente?
                msg_obj = msgs_map.get(msg_data.id)
                if msg_obj:
                    # Atualiza
                    msg_obj.type = msg_data.type
                    msg_obj.content = msg_data.content
                    db.commit()
                    db.refresh(msg_obj)
                    updated_msg_ids.append(msg_obj.id)
                else:
                    # Não existe => criar
                    new_msg = FollowUpMessage(
                        follow_up_step_id=step_obj.id,
                        type=msg_data.type,
                        content=msg_data.content
                    )
                    db.add(new_msg)
                    db.commit()
                    db.refresh(new_msg)
                    updated_msg_ids.append(new_msg.id)
            else:
                # Criar nova mensagem
                new_msg = FollowUpMessage(
                    follow_up_step_id=step_obj.id,
                    type=msg_data.type,
                    content=msg_data.content
                )
                db.add(new_msg)
                db.commit()
                db.refresh(new_msg)
                updated_msg_ids.append(new_msg.id)

        # Excluir as mensagens que não vieram no payload
        for old_msg_id, old_msg_obj in msgs_map.items():
            if old_msg_id not in updated_msg_ids:
                db.delete(old_msg_obj)
                db.commit()

    # 6) Excluir steps que desapareceram do payload
    for old_step_id, old_step_obj in steps_map.items():
        if old_step_id not in updated_step_ids:
            db.delete(old_step_obj)
            db.commit()

    db.refresh(seq)
    return {
        "message": "Follow-up sequence updated successfully (upsert)",
        "sequence_id": seq.id
    }

@router.delete("/followups/{company_id}", response_model=dict)
def delete_followup_sequence(
    company_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    Remove a sequência de follow-up desta empresa (se existir).
    """
    ensure_user_can_access_company(user, company_id, db)
    seq = db.query(FollowUpSequence).filter(FollowUpSequence.company_id == company_id).first()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence not found for this company")

    db.delete(seq)
    db.commit()

    return {"message": f"Follow-up sequence for company {company_id} deleted successfully"}
