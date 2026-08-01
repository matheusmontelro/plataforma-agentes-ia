# backend/routes/pos_venda_followup_routes.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from backend.db import get_db
from sqlalchemy import text
import json

# ----------------------------------------------------------------
# Schemas para criação (POST) - sem "id" nos steps/messages
# ----------------------------------------------------------------
class PosVendaMessageCreate(BaseModel):
    type: str                 # "text", "image", "audio", "video", "nps"
    content: str

class PosVendaStepCreate(BaseModel):
    step_number: int
    send_after: int
    send_after_unit: str      # "minutes", "hours", "days"
    messages: List[PosVendaMessageCreate]

class PosVendaSequenceCreate(BaseModel):
    company_id: int
    name: str
    description: str
    steps: List[PosVendaStepCreate]

# ----------------------------------------------------------------
# Schemas para UPDATE (PUT) - com "id" opcional
# ----------------------------------------------------------------
class PosVendaMessageUpdate(BaseModel):
    id: Optional[int] = None
    type: str
    content: str

class PosVendaStepUpdate(BaseModel):
    id: Optional[int] = None
    step_number: int
    send_after: int
    send_after_unit: str
    messages: List[PosVendaMessageUpdate]

class PosVendaSequenceUpdate(BaseModel):
    company_id: int
    name: str
    description: str
    steps: List[PosVendaStepUpdate]

# ----------------------------------------------------------------
# Schemas para Schedule
# ----------------------------------------------------------------
class PosVendaScheduleConfigData(BaseModel):
    schedule_data: dict

# ----------------------------------------------------------------
# Router
# ----------------------------------------------------------------
router = APIRouter()

# ----------------------------------------------------------------
# POST: Cria nova sequência pós-venda
# ----------------------------------------------------------------
@router.post("/pos-venda-followups/{company_id}", response_model=dict)
def create_pos_venda_sequence(
    company_id: int,
    data: PosVendaSequenceCreate,
    db: Session = Depends(get_db),
):
    """
    Cria uma nova sequência de follow-up pós-venda para a empresa.
    """
    if data.company_id != company_id:
        raise HTTPException(status_code=400, detail="company_id mismatch")

    # Verifica se já existe uma sequência para a empresa
    existing_seq = db.execute(
        text("SELECT id FROM pos_venda_sequences WHERE company_id = :company_id"),
        {"company_id": company_id}
    ).fetchone()

    if existing_seq:
        raise HTTPException(status_code=400, detail="Já existe uma sequência pós-venda para esta empresa.")

    # Cria sequência
    result = db.execute(
        text("""
            INSERT INTO pos_venda_sequences (company_id, name, description)
            VALUES (:company_id, :name, :description)
            RETURNING id
        """),
        {
            "company_id": company_id,
            "name": data.name,
            "description": data.description
        }
    )
    seq_id = result.fetchone().id
    db.commit()

    # Cria steps e messages
    for step_data in data.steps:
        step_result = db.execute(
            text("""
                INSERT INTO pos_venda_steps
                (pos_venda_sequence_id, step_number, send_after, send_after_unit)
                VALUES (:seq_id, :step_number, :send_after, :send_after_unit)
                RETURNING id
            """),
            {
                "seq_id": seq_id,
                "step_number": step_data.step_number,
                "send_after": step_data.send_after,
                "send_after_unit": step_data.send_after_unit
            }
        )
        step_id = step_result.fetchone().id
        db.commit()

        for msg_data in step_data.messages:
            db.execute(
                text("""
                    INSERT INTO pos_venda_messages
                    (pos_venda_step_id, type, content)
                    VALUES (:step_id, :type, :content)
                """),
                {
                    "step_id": step_id,
                    "type": msg_data.type,
                    "content": msg_data.content
                }
            )
        db.commit()

    return {
        "message": "Sequência pós-venda criada com sucesso",
        "sequence_id": seq_id
    }

# ----------------------------------------------------------------
# GET: Retorna a sequência pós-venda pelo company_id
# ----------------------------------------------------------------
@router.get("/pos-venda-followups/{company_id}", response_model=dict)
def get_pos_venda_sequence(
    company_id: int,
    db: Session = Depends(get_db),
):
    """
    Retorna a sequência completa de follow-up pós-venda para company_id.
    """
    seq = db.execute(
        text("SELECT id, company_id, name, description, active FROM pos_venda_sequences WHERE company_id = :company_id"),
        {"company_id": company_id}
    ).fetchone()

    if not seq:
        raise HTTPException(status_code=404, detail="Nenhuma sequência pós-venda encontrada para esta empresa.")

    # Buscar steps
    steps = db.execute(
        text("""
            SELECT id, step_number, send_after, send_after_unit
            FROM pos_venda_steps
            WHERE pos_venda_sequence_id = :seq_id
            ORDER BY step_number
        """),
        {"seq_id": seq.id}
    ).fetchall()

    steps_data = []
    for step in steps:
        # Buscar messages do step
        messages = db.execute(
            text("""
                SELECT id, type, content
                FROM pos_venda_messages
                WHERE pos_venda_step_id = :step_id
                ORDER BY id
            """),
            {"step_id": step.id}
        ).fetchall()

        steps_data.append({
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
                for msg in messages
            ]
        })

    return {
        "id": seq.id,
        "company_id": seq.company_id,
        "name": seq.name,
        "description": seq.description,
        "active": seq.active,
        "steps": steps_data
    }

# ----------------------------------------------------------------
# PUT: Atualiza a sequência pós-venda (Upsert em steps/messages)
# ----------------------------------------------------------------
@router.put("/pos-venda-followups/{company_id}", response_model=dict)
def update_pos_venda_sequence(
    company_id: int,
    data: PosVendaSequenceUpdate,
    db: Session = Depends(get_db),
):
    """
    Atualiza a sequência de follow-up pós-venda da empresa,
    mantendo os mesmos IDs de steps/mensagens se eles continuarem existindo.
    """
    if data.company_id != company_id:
        raise HTTPException(status_code=400, detail="company_id mismatch")

    # Verifica existência da sequência
    seq = db.execute(
        text("SELECT id FROM pos_venda_sequences WHERE company_id = :company_id"),
        {"company_id": company_id}
    ).fetchone()

    if not seq:
        raise HTTPException(status_code=404, detail="Nenhuma sequência pós-venda encontrada para esta empresa.")

    # Atualiza campos básicos
    db.execute(
        text("""
            UPDATE pos_venda_sequences
            SET name = :name, description = :description, updated_at = NOW()
            WHERE id = :seq_id
        """),
        {
            "seq_id": seq.id,
            "name": data.name,
            "description": data.description
        }
    )
    db.commit()

    # Buscar steps existentes
    existing_steps = db.execute(
        text("SELECT id, step_number FROM pos_venda_steps WHERE pos_venda_sequence_id = :seq_id"),
        {"seq_id": seq.id}
    ).fetchall()

    existing_steps_dict = {step.id: step for step in existing_steps}
    payload_step_ids = []

    for step_data in data.steps:
        step_id = step_data.id

        if step_id is not None and step_id in existing_steps_dict:
            # Atualiza step existente
            db.execute(
                text("""
                    UPDATE pos_venda_steps
                    SET step_number = :step_number, send_after = :send_after,
                        send_after_unit = :send_after_unit, updated_at = NOW()
                    WHERE id = :step_id
                """),
                {
                    "step_id": step_id,
                    "step_number": step_data.step_number,
                    "send_after": step_data.send_after,
                    "send_after_unit": step_data.send_after_unit
                }
            )
            db.commit()
            payload_step_ids.append(step_id)

            # Upsert de mensagens
            upsert_pos_venda_messages(db=db, step_id=step_id, messages_data=step_data.messages)
        else:
            # Cria step novo
            new_step_result = db.execute(
                text("""
                    INSERT INTO pos_venda_steps
                    (pos_venda_sequence_id, step_number, send_after, send_after_unit)
                    VALUES (:seq_id, :step_number, :send_after, :send_after_unit)
                    RETURNING id
                """),
                {
                    "seq_id": seq.id,
                    "step_number": step_data.step_number,
                    "send_after": step_data.send_after,
                    "send_after_unit": step_data.send_after_unit
                }
            )
            new_step_id = new_step_result.fetchone().id
            db.commit()
            payload_step_ids.append(new_step_id)

            upsert_pos_venda_messages(db=db, step_id=new_step_id, messages_data=step_data.messages)

    # Deletar steps que não estão no payload
    for old_step in existing_steps:
        if old_step.id not in payload_step_ids:
            # Deletar mensagens do step primeiro
            db.execute(
                text("DELETE FROM pos_venda_messages WHERE pos_venda_step_id = :step_id"),
                {"step_id": old_step.id}
            )
            # Deletar o step
            db.execute(
                text("DELETE FROM pos_venda_steps WHERE id = :step_id"),
                {"step_id": old_step.id}
            )
    db.commit()

    return {
        "message": "Sequência pós-venda atualizada com sucesso",
        "sequence_id": seq.id
    }

def upsert_pos_venda_messages(db: Session, step_id: int, messages_data: List[PosVendaMessageUpdate]):
    """
    Faz upsert de mensagens para um step específico.
    """
    # Buscar mensagens existentes
    existing_msgs = db.execute(
        text("SELECT id, type, content FROM pos_venda_messages WHERE pos_venda_step_id = :step_id"),
        {"step_id": step_id}
    ).fetchall()

    existing_msgs_dict = {msg.id: msg for msg in existing_msgs}
    payload_msg_ids = []

    for msg_data in messages_data:
        msg_id = msg_data.id
        if msg_id is not None and msg_id in existing_msgs_dict:
            # Atualiza mensagem existente
            db.execute(
                text("""
                    UPDATE pos_venda_messages
                    SET type = :type, content = :content, updated_at = NOW()
                    WHERE id = :msg_id
                """),
                {
                    "msg_id": msg_id,
                    "type": msg_data.type,
                    "content": msg_data.content
                }
            )
            db.commit()
            payload_msg_ids.append(msg_id)
        else:
            # Cria mensagem nova
            new_msg_result = db.execute(
                text("""
                    INSERT INTO pos_venda_messages
                    (pos_venda_step_id, type, content)
                    VALUES (:step_id, :type, :content)
                    RETURNING id
                """),
                {
                    "step_id": step_id,
                    "type": msg_data.type,
                    "content": msg_data.content
                }
            )
            new_msg_id = new_msg_result.fetchone().id
            db.commit()
            payload_msg_ids.append(new_msg_id)

    # Deletar mensagens que não foram enviadas
    for old_msg in existing_msgs:
        if old_msg.id not in payload_msg_ids:
            db.execute(
                text("DELETE FROM pos_venda_messages WHERE id = :msg_id"),
                {"msg_id": old_msg.id}
            )
    db.commit()

# ----------------------------------------------------------------
# DELETE: Remove a sequência pós-venda
# ----------------------------------------------------------------
@router.delete("/pos-venda-followups/{company_id}", response_model=dict)
def delete_pos_venda_sequence(
    company_id: int,
    db: Session = Depends(get_db),
):
    """
    Remove a sequência de follow-up pós-venda da empresa.
    """
    seq = db.execute(
        text("SELECT id FROM pos_venda_sequences WHERE company_id = :company_id"),
        {"company_id": company_id}
    ).fetchone()

    if not seq:
        raise HTTPException(status_code=404, detail="Nenhuma sequência pós-venda encontrada.")

    # Deletar em cascata (messages -> steps -> sequence)
    db.execute(
        text("""
            DELETE FROM pos_venda_messages
            WHERE pos_venda_step_id IN (
                SELECT id FROM pos_venda_steps WHERE pos_venda_sequence_id = :seq_id
            )
        """),
        {"seq_id": seq.id}
    )

    db.execute(
        text("DELETE FROM pos_venda_steps WHERE pos_venda_sequence_id = :seq_id"),
        {"seq_id": seq.id}
    )

    db.execute(
        text("DELETE FROM pos_venda_sequences WHERE id = :seq_id"),
        {"seq_id": seq.id}
    )

    db.commit()

    return {"message": f"Sequência pós-venda da empresa {company_id} excluída com sucesso."}

# ----------------------------------------------------------------
# Schedule Configuration Routes
# ----------------------------------------------------------------

@router.post("/pos-venda-followups/{company_id}/schedule", response_model=dict)
def create_pos_venda_schedule_config(
    company_id: int,
    data: PosVendaScheduleConfigData,
    db: Session = Depends(get_db),
):
    """Cria configuração de horários para sequência pós-venda."""

    # Verificar se existe sequência
    seq = db.execute(
        text("SELECT id FROM pos_venda_sequences WHERE company_id = :company_id"),
        {"company_id": company_id}
    ).fetchone()

    if not seq:
        raise HTTPException(status_code=404, detail="Sequência pós-venda não encontrada.")

    # Verificar se já existe config
    existing_config = db.execute(
        text("""
            SELECT id FROM pos_venda_schedule_configs
            WHERE company_id = :company_id AND pos_venda_sequence_id = :seq_id
        """),
        {"company_id": company_id, "seq_id": seq.id}
    ).fetchone()

    if existing_config:
        raise HTTPException(status_code=400, detail="Configuração de horários já existe.")

    config_result = db.execute(
        text("""
            INSERT INTO pos_venda_schedule_configs
            (company_id, pos_venda_sequence_id, schedule_data)
            VALUES (:company_id, :seq_id, CAST(:schedule_data AS jsonb))
            RETURNING id
        """),
        {
            "company_id": company_id,
            "seq_id": seq.id,
            "schedule_data": json.dumps(data.schedule_data)
        }
    )
    config_id = config_result.fetchone().id
    db.commit()

    return {
        "message": "Configuração de horários criada com sucesso",
        "config_id": config_id
    }

@router.get("/pos-venda-followups/{company_id}/schedule", response_model=dict)
def get_pos_venda_schedule_config(
    company_id: int,
    db: Session = Depends(get_db),
):
    """Obtém configuração de horários para sequência pós-venda."""

    # Verificar se existe sequência
    seq = db.execute(
        text("SELECT id FROM pos_venda_sequences WHERE company_id = :company_id"),
        {"company_id": company_id}
    ).fetchone()

    if not seq:
        raise HTTPException(status_code=404, detail="Sequência pós-venda não encontrada.")

    config = db.execute(
        text("""
            SELECT id, company_id, pos_venda_sequence_id, schedule_data
            FROM pos_venda_schedule_configs
            WHERE company_id = :company_id AND pos_venda_sequence_id = :seq_id
        """),
        {"company_id": company_id, "seq_id": seq.id}
    ).fetchone()

    if not config:
        raise HTTPException(status_code=404, detail="Configuração de horários não encontrada.")

    return {
        "id": config.id,
        "company_id": config.company_id,
        "pos_venda_sequence_id": config.pos_venda_sequence_id,
        "schedule_data": config.schedule_data
    }

@router.put("/pos-venda-followups/{company_id}/schedule", response_model=dict)
def update_pos_venda_schedule_config(
    company_id: int,
    data: PosVendaScheduleConfigData,
    db: Session = Depends(get_db),
):
    """Atualiza configuração de horários para sequência pós-venda."""

    # Verificar se existe sequência
    seq = db.execute(
        text("SELECT id FROM pos_venda_sequences WHERE company_id = :company_id"),
        {"company_id": company_id}
    ).fetchone()

    if not seq:
        raise HTTPException(status_code=404, detail="Sequência pós-venda não encontrada.")

    config = db.execute(
        text("""
            SELECT id FROM pos_venda_schedule_configs
            WHERE company_id = :company_id AND pos_venda_sequence_id = :seq_id
        """),
        {"company_id": company_id, "seq_id": seq.id}
    ).fetchone()

    if not config:
        raise HTTPException(status_code=404, detail="Configuração de horários não encontrada.")

    db.execute(
        text("""
            UPDATE pos_venda_schedule_configs
            SET schedule_data = CAST(:schedule_data AS jsonb), updated_at = NOW()
            WHERE id = :config_id
        """),
        {
            "config_id": config.id,
            "schedule_data": json.dumps(data.schedule_data)
        }
    )
    db.commit()

    return {
        "message": "Configuração de horários atualizada com sucesso",
        "config_id": config.id
    }

@router.delete("/pos-venda-followups/{company_id}/schedule", response_model=dict)
def delete_pos_venda_schedule_config(
    company_id: int,
    db: Session = Depends(get_db),
):
    """Remove configuração de horários para sequência pós-venda."""

    config = db.execute(
        text("SELECT id FROM pos_venda_schedule_configs WHERE company_id = :company_id"),
        {"company_id": company_id}
    ).fetchone()

    if not config:
        raise HTTPException(status_code=404, detail="Configuração de horários não encontrada.")

    db.execute(
        text("DELETE FROM pos_venda_schedule_configs WHERE id = :config_id"),
        {"config_id": config.id}
    )
    db.commit()

    return {"message": "Configuração de horários removida com sucesso."}