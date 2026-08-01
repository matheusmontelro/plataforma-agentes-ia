from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Importe a sessão do banco
from backend.db import get_db
from backend.auth import get_current_user, ensure_user_can_access_company
from backend.models import (
    ConfirmationSequence,
    ConfirmationStep,
    ConfirmationMessage
)

# =============== NOVOS Schemas p/ UPDATE ===================
from typing import Optional

class MessageUpdate(BaseModel):
    id: Optional[int] = None
    type: str
    content: str

class StepUpdate(BaseModel):
    id: Optional[int] = None
    step_number: int
    send_after: int
    send_after_unit: str  # "minutes", "hours", "days"
    messages: List[MessageUpdate]

class ConfirmationSequenceUpdate(BaseModel):
    client_id: str
    company_id: int
    name: str
    description: str
    steps: List[StepUpdate]

# =============== Schemas originais p/ CREATE ===============
class MessageCreate(BaseModel):
    type: str
    content: str

class StepCreate(BaseModel):
    step_number: int
    send_after: int
    send_after_unit: str
    messages: List[MessageCreate]

class ConfirmationSequenceCreate(BaseModel):
    client_id: str
    company_id: int
    name: str
    description: str
    steps: List[StepCreate]

# -----------------------------------------------------------
router = APIRouter()

# =================== POST (igual) ==========================
@router.post("/confirmations/{company_id}", response_model=dict)
def create_confirmation_sequence(
    company_id: int,
    data: ConfirmationSequenceCreate,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    logger.info(f"Iniciando criação de sequência de confirmação para company_id: {company_id}")
    logger.debug(f"Dados recebidos: {data.dict()}")

    if data.company_id != company_id:
        logger.error(f"Mismatch de company_id: rota={company_id}, payload={data.company_id}")
        raise HTTPException(status_code=400, detail="company_id mismatch")
    ensure_user_can_access_company(user, company_id, db)

    existing_seq = db.query(ConfirmationSequence).filter(
        ConfirmationSequence.company_id == company_id
    ).first()
    if existing_seq:
        logger.warning(f"Tentativa de criar sequência duplicada p/ company_id: {company_id}")
        raise HTTPException(status_code=400, detail="Já existe uma sequência de confirmação para esta empresa.")

    try:
        # Cria a sequência
        seq = ConfirmationSequence(
            client_id=data.client_id,
            company_id=company_id,
            name=data.name,
            description=data.description
        )
        db.add(seq)
        db.commit()
        db.refresh(seq)
        logger.info(f"Sequência principal criada com ID: {seq.id}")

        # Cria steps e messages
        for step_data in data.steps:
            step = ConfirmationStep(
                confirmation_sequence_id=seq.id,
                step_number=step_data.step_number,
                send_after=step_data.send_after,
                send_after_unit=step_data.send_after_unit
            )
            db.add(step)
            db.commit()
            db.refresh(step)
            logger.info(f"Step {step.step_number} criado com ID: {step.id}")

            for msg_data in step_data.messages:
                msg = ConfirmationMessage(
                    confirmation_step_id=step.id,
                    type=msg_data.type,
                    content=msg_data.content
                )
                db.add(msg)
                logger.debug(f"Mensagem tipo {msg_data.type} adicionada ao step {step.id}")
            db.commit()

        logger.info(f"Sequência completa criada com sucesso p/ company_id: {company_id}")
        return {
            "message": "Confirmation sequence created successfully",
            "sequence_id": seq.id
        }
    except Exception as e:
        logger.error(f"Erro ao criar sequência: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# =================== GET (igual) ===========================
@router.get("/confirmations/{company_id}", response_model=dict)
def get_confirmation_sequence(
    company_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    logger.info(f"Buscando sequência de confirmação para company_id: {company_id}")
    ensure_user_can_access_company(user, company_id, db)

    seq = db.query(ConfirmationSequence).filter(
        ConfirmationSequence.company_id == company_id
    ).first()
    if not seq:
        logger.warning(f"Sequência não encontrada p/ company_id: {company_id}")
        raise HTTPException(status_code=404, detail="Confirmation sequence not found for this company")

    response = {
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
    logger.info(f"Sequência encontrada com {len(seq.steps)} steps")
    logger.debug(f"Dados retornados: {response}")
    return response

# =================== PUT (ajustado p/ upsert) ==============
@router.put("/confirmations/{company_id}", response_model=dict)
def update_confirmation_sequence(
    company_id: int,
    data: ConfirmationSequenceUpdate,  # <--- USAMOS O NOVO SCHEMA
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    logger.info(f"Iniciando atualização de sequência para company_id: {company_id}")
    logger.debug(f"Dados recebidos: {data.dict()}")

    if data.company_id != company_id:
        logger.error(f"Mismatch de company_id: rota={company_id}, payload={data.company_id}")
        raise HTTPException(status_code=400, detail="company_id mismatch")
    ensure_user_can_access_company(user, company_id, db)

    try:
        seq = db.query(ConfirmationSequence).filter(
            ConfirmationSequence.company_id == company_id
        ).first()
        if not seq:
            logger.warning(f"Tentativa de atualizar sequência inexistente: {company_id}")
            raise HTTPException(status_code=404, detail="Confirmation sequence not found")

        # Atualiza campos básicos
        seq.client_id = data.client_id
        seq.name = data.name
        seq.description = data.description
        db.commit()
        db.refresh(seq)

        # Carrega steps existentes no banco
        existing_steps = db.query(ConfirmationStep).filter(
            ConfirmationStep.confirmation_sequence_id == seq.id
        ).all()

        # Dicionário p/ acesso rápido
        existing_steps_dict = { s.id: s for s in existing_steps }

        # Guardar quais steps permanecem (para excluir os que não vierem no payload)
        updated_step_ids = []

        # Percorrer os steps do payload
        for step_data in data.steps:
            # Verificar se no payload veio um ID (step_data.id)
            if step_data.id:
                # Tentar achar esse step no banco
                step_obj = existing_steps_dict.get(step_data.id)
                if step_obj:
                    # -> Step existente: atualizar campos
                    step_obj.step_number = step_data.step_number
                    step_obj.send_after = step_data.send_after
                    step_obj.send_after_unit = step_data.send_after_unit
                    db.commit()
                    db.refresh(step_obj)
                else:
                    # -> ID não encontrado no banco -> cria step novo
                    step_obj = ConfirmationStep(
                        confirmation_sequence_id=seq.id,
                        step_number=step_data.step_number,
                        send_after=step_data.send_after,
                        send_after_unit=step_data.send_after_unit
                    )
                    db.add(step_obj)
                    db.commit()
                    db.refresh(step_obj)
            else:
                # Step sem ID -> cria novo
                step_obj = ConfirmationStep(
                    confirmation_sequence_id=seq.id,
                    step_number=step_data.step_number,
                    send_after=step_data.send_after,
                    send_after_unit=step_data.send_after_unit
                )
                db.add(step_obj)
                db.commit()
                db.refresh(step_obj)

            updated_step_ids.append(step_obj.id)

            # Atualizar mensagens dentro desse step
            old_msgs = db.query(ConfirmationMessage).filter(
                ConfirmationMessage.confirmation_step_id == step_obj.id
            ).all()
            old_msgs_dict = { m.id: m for m in old_msgs }
            updated_msg_ids = []

            for msg_data in step_data.messages:
                if hasattr(msg_data, 'id') and msg_data.id is not None:
                    # Tentar achar a msg no banco
                    existing_msg = old_msgs_dict.get(msg_data.id)
                    if existing_msg:
                        # Atualiza
                        existing_msg.type = msg_data.type
                        existing_msg.content = msg_data.content
                        db.commit()
                        db.refresh(existing_msg)
                        updated_msg_ids.append(existing_msg.id)
                    else:
                        # Cria nova
                        new_msg = ConfirmationMessage(
                            confirmation_step_id=step_obj.id,
                            type=msg_data.type,
                            content=msg_data.content
                        )
                        db.add(new_msg)
                        db.commit()
                        db.refresh(new_msg)
                        updated_msg_ids.append(new_msg.id)
                else:
                    # Mensagem sem ID -> nova
                    new_msg = ConfirmationMessage(
                        confirmation_step_id=step_obj.id,
                        type=msg_data.type,
                        content=msg_data.content
                    )
                    db.add(new_msg)
                    db.commit()
                    db.refresh(new_msg)
                    updated_msg_ids.append(new_msg.id)

            # Excluir mensagens que não estão mais no payload
            for old_id, old_obj in old_msgs_dict.items():
                if old_id not in updated_msg_ids:
                    db.delete(old_obj)
                    db.commit()

        # Excluir steps que não apareceram no novo payload
        for s_id, s_obj in existing_steps_dict.items():
            if s_id not in updated_step_ids:
                db.delete(s_obj)
                db.commit()

        logger.info(f"Atualização completa realizada com sucesso p/ company_id: {company_id}")
        return {
            "message": "Confirmation sequence updated successfully",
            "sequence_id": seq.id
        }
    except Exception as e:
        logger.error(f"Erro ao atualizar sequência: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# =================== DELETE (igual) =========================
@router.delete("/confirmations/{company_id}", response_model=dict)
def delete_confirmation_sequence(
    company_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    logger.info(f"Iniciando remoção de sequência para company_id: {company_id}")
    ensure_user_can_access_company(user, company_id, db)

    seq = db.query(ConfirmationSequence).filter(
        ConfirmationSequence.company_id == company_id
    ).first()
    if not seq:
        logger.warning(f"Tentativa de deletar sequência inexistente: {company_id}")
        raise HTTPException(status_code=404, detail="Confirmation sequence not found")

    try:
        sequence_id = seq.id
        db.delete(seq)
        db.commit()
        logger.info(f"Sequência {sequence_id} deletada com sucesso para company_id: {company_id}")
        return {
            "message": f"Confirmation sequence for company {company_id} deleted successfully"
        }
    except Exception as e:
        logger.error(f"Erro ao deletar sequência: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
