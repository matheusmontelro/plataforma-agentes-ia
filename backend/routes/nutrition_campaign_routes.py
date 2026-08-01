
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime
import json

from backend.db import SessionLocal
from backend.auth import get_current_user
from backend.models import Client, User
from backend.services.company_access_control import (
    CompanyOperationallyBlockedError,
    capture_company_job_epoch,
)
from typing import Union

# Pydantic Models
class NutritionCampaignSequenceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    target_contact_status: Optional[List[str]] = None
    target_contact_categories: Optional[List[str]] = None
    target_contact_tags: Optional[List[str]] = None
    message_delay_min: int = 30
    message_delay_max: int = 120
    contact_delay_min: int = 5
    contact_delay_max: int = 30
    contact_delay_unit: str = 'minutes'
    active: bool = True

class NutritionCampaignSequenceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    target_contact_status: Optional[List[str]] = None
    target_contact_categories: Optional[List[str]] = None
    target_contact_tags: Optional[List[str]] = None
    message_delay_min: Optional[int] = None
    message_delay_max: Optional[int] = None
    contact_delay_min: Optional[int] = None
    contact_delay_max: Optional[int] = None
    contact_delay_unit: Optional[str] = None
    active: Optional[bool] = None

class NutritionCampaignStepCreate(BaseModel):
    step_number: int
    send_after: int
    send_after_unit: str  # 'minutes', 'hours', 'days'
    random_delay_min: int = 0
    random_delay_max: int = 3600

class NutritionCampaignStepUpdate(BaseModel):
    send_after: Optional[int] = None
    send_after_unit: Optional[str] = None
    random_delay_min: Optional[int] = None
    random_delay_max: Optional[int] = None

class NutritionCampaignMessageCreate(BaseModel):
    type: str  # 'text', 'image', 'audio', 'video', 'nps'
    content: str

class NutritionCampaignMessageUpdate(BaseModel):
    type: Optional[str] = None
    content: Optional[str] = None

class NutritionCampaignScheduleConfigCreate(BaseModel):
    schedule_data: Dict[str, Any]

class CampaignLaunchRequest(BaseModel):
    sequence_id: Optional[int] = None  # Se None, lança todas as sequências ativas

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/sequences")
def get_nutrition_sequences(
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """Lista todas as sequências de campanha de nutrição da empresa."""
    try:
        sequences = db.execute(
            text("""
                SELECT id, name, description, active, target_contact_status,
                       target_contact_categories, target_contact_tags,
                       message_delay_min, message_delay_max,
                       contact_delay_min, contact_delay_max, contact_delay_unit,
                       created_at, updated_at
                FROM nutrition_campaign_sequences
                WHERE company_id = :company_id
                ORDER BY created_at DESC
            """),
            {"company_id": getattr(current_user, 'company_id', None)}
        ).fetchall()

        # Converter manualmente para lidar com arrays PostgreSQL
        sequences_list = []
        for seq in sequences:
            seq_dict = {
                "id": seq.id,
                "name": seq.name,
                "description": seq.description,
                "active": seq.active,
                "target_contact_status": seq.target_contact_status if seq.target_contact_status else [],
                "target_contact_categories": seq.target_contact_categories if seq.target_contact_categories else [],
                "target_contact_tags": seq.target_contact_tags if seq.target_contact_tags else [],
                "message_delay_min": seq.message_delay_min,
                "message_delay_max": seq.message_delay_max,
                "contact_delay_min": seq.contact_delay_min,
                "contact_delay_max": seq.contact_delay_max,
                "contact_delay_unit": seq.contact_delay_unit,
                "created_at": seq.created_at.isoformat() if seq.created_at else None,
                "updated_at": seq.updated_at.isoformat() if seq.updated_at else None
            }
            sequences_list.append(seq_dict)

        return {
            "success": True,
            "sequences": sequences_list
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao buscar sequências: {str(e)}")

@router.post("/sequences")
def create_nutrition_sequence(
    sequence: NutritionCampaignSequenceCreate,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """Cria uma nova sequência de campanha de nutrição."""
    try:
        # Verificar se já existe sequência com esse nome
        existing = db.execute(
            text("""
                SELECT id FROM nutrition_campaign_sequences
                WHERE company_id = :company_id AND name = :name
            """),
            {"company_id": getattr(current_user, 'company_id', None), "name": sequence.name}
        ).fetchone()

        if existing:
            raise HTTPException(status_code=400, detail="Já existe uma sequência com esse nome")

        # Inserir sequência
        result = db.execute(
            text("""
                INSERT INTO nutrition_campaign_sequences (
                    company_id, name, description, active,
                    target_contact_status, target_contact_categories, target_contact_tags,
                    message_delay_min, message_delay_max,
                    contact_delay_min, contact_delay_max, contact_delay_unit
                ) VALUES (
                    :company_id, :name, :description, :active,
                    :target_status, :target_categories, :target_tags,
                    :delay_min, :delay_max,
                    :contact_delay_min, :contact_delay_max, :contact_delay_unit
                ) RETURNING id
            """),
            {
                "company_id": getattr(current_user, 'company_id', None),
                "name": sequence.name,
                "description": sequence.description,
                "active": sequence.active,
                "target_status": sequence.target_contact_status,
                "target_categories": sequence.target_contact_categories,
                "target_tags": sequence.target_contact_tags,
                "delay_min": sequence.message_delay_min,
                "delay_max": sequence.message_delay_max,
                "contact_delay_min": sequence.contact_delay_min,
                "contact_delay_max": sequence.contact_delay_max,
                "contact_delay_unit": sequence.contact_delay_unit
            }
        )

        sequence_id = result.fetchone()[0]
        db.commit()

        return {
            "success": True,
            "message": "Sequência criada com sucesso",
            "sequence_id": sequence_id
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao criar sequência: {str(e)}")

@router.put("/sequences/{sequence_id}")
def update_nutrition_sequence(
    sequence_id: int,
    sequence: NutritionCampaignSequenceUpdate,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """Atualiza uma sequência de campanha de nutrição."""
    try:
        # Verificar se sequência existe e pertence à empresa
        existing = db.execute(
            text("""
                SELECT id FROM nutrition_campaign_sequences
                WHERE id = :seq_id AND company_id = :company_id
            """),
            {"seq_id": sequence_id, "company_id": getattr(current_user, 'company_id', None)}
        ).fetchone()

        if not existing:
            raise HTTPException(status_code=404, detail="Sequência não encontrada")

        # Montar UPDATE dinâmico
        update_fields = []
        update_params = {"seq_id": sequence_id}

        if sequence.name is not None:
            update_fields.append("name = :name")
            update_params["name"] = sequence.name

        if sequence.description is not None:
            update_fields.append("description = :description")
            update_params["description"] = sequence.description

        if sequence.target_contact_status is not None:
            update_fields.append("target_contact_status = :target_status")
            update_params["target_status"] = sequence.target_contact_status

        if sequence.target_contact_categories is not None:
            update_fields.append("target_contact_categories = :target_categories")
            update_params["target_categories"] = sequence.target_contact_categories

        if sequence.target_contact_tags is not None:
            update_fields.append("target_contact_tags = :target_tags")
            update_params["target_tags"] = sequence.target_contact_tags

        if sequence.message_delay_min is not None:
            update_fields.append("message_delay_min = :delay_min")
            update_params["delay_min"] = sequence.message_delay_min

        if sequence.message_delay_max is not None:
            update_fields.append("message_delay_max = :delay_max")
            update_params["delay_max"] = sequence.message_delay_max

        if sequence.active is not None:
            update_fields.append("active = :active")
            update_params["active"] = sequence.active

        if update_fields:
            update_fields.append("updated_at = NOW()")
            update_query = f"""
                UPDATE nutrition_campaign_sequences
                SET {', '.join(update_fields)}
                WHERE id = :seq_id
            """

            db.execute(text(update_query), update_params)
            db.commit()

        return {
            "success": True,
            "message": "Sequência atualizada com sucesso"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar sequência: {str(e)}")

@router.delete("/sequences/{sequence_id}")
def delete_nutrition_sequence(
    sequence_id: int,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """Remove uma sequência de campanha de nutrição."""
    try:
        # Verificar se sequência existe e pertence à empresa
        existing = db.execute(
            text("""
                SELECT id FROM nutrition_campaign_sequences
                WHERE id = :seq_id AND company_id = :company_id
            """),
            {"seq_id": sequence_id, "company_id": getattr(current_user, 'company_id', None)}
        ).fetchone()

        if not existing:
            raise HTTPException(status_code=404, detail="Sequência não encontrada")

        # Cancelar execuções pendentes
        db.execute(
            text("""
                UPDATE nutrition_campaign_executions
                SET status = 'CANCELED', error_message = 'Sequência removida'
                WHERE nutrition_campaign_sequence_id = :seq_id
                  AND status IN ('SCHEDULED', 'PROCESSING')
            """),
            {"seq_id": sequence_id}
        )

        # Remover sequência (CASCADE remove steps, messages, etc.)
        db.execute(
            text("DELETE FROM nutrition_campaign_sequences WHERE id = :seq_id"),
            {"seq_id": sequence_id}
        )

        db.commit()

        return {
            "success": True,
            "message": "Sequência removida com sucesso"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao remover sequência: {str(e)}")

@router.get("/sequences/{sequence_id}/steps")
def get_nutrition_steps(
    sequence_id: int,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """Lista os steps de uma sequência."""
    try:
        # Verificar se sequência pertence à empresa
        sequence_check = db.execute(
            text("""
                SELECT id FROM nutrition_campaign_sequences
                WHERE id = :seq_id AND company_id = :company_id
            """),
            {"seq_id": sequence_id, "company_id": getattr(current_user, 'company_id', None)}
        ).fetchone()

        if not sequence_check:
            raise HTTPException(status_code=404, detail="Sequência não encontrada")

        steps = db.execute(
            text("""
                SELECT id, step_number, send_after, send_after_unit,
                       random_delay_min, random_delay_max, created_at, updated_at
                FROM nutrition_campaign_steps
                WHERE nutrition_campaign_sequence_id = :seq_id
                ORDER BY step_number
            """),
            {"seq_id": sequence_id}
        ).fetchall()

        return {
            "success": True,
            "steps": [dict(step) for step in steps]
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao buscar steps: {str(e)}")

@router.post("/sequences/{sequence_id}/steps")
def create_nutrition_step(
    sequence_id: int,
    step: NutritionCampaignStepCreate,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """Cria um novo step na sequência."""
    try:
        # Verificar se sequência pertence à empresa
        sequence_check = db.execute(
            text("""
                SELECT id FROM nutrition_campaign_sequences
                WHERE id = :seq_id AND company_id = :company_id
            """),
            {"seq_id": sequence_id, "company_id": getattr(current_user, 'company_id', None)}
        ).fetchone()

        if not sequence_check:
            raise HTTPException(status_code=404, detail="Sequência não encontrada")

        # Verificar se step_number já existe
        existing_step = db.execute(
            text("""
                SELECT id FROM nutrition_campaign_steps
                WHERE nutrition_campaign_sequence_id = :seq_id AND step_number = :step_num
            """),
            {"seq_id": sequence_id, "step_num": step.step_number}
        ).fetchone()

        if existing_step:
            raise HTTPException(status_code=400, detail=f"Step {step.step_number} já existe")

        # Inserir step
        result = db.execute(
            text("""
                INSERT INTO nutrition_campaign_steps (
                    nutrition_campaign_sequence_id, step_number, send_after, send_after_unit,
                    random_delay_min, random_delay_max
                ) VALUES (
                    :seq_id, :step_num, :send_after, :send_unit,
                    :delay_min, :delay_max
                ) RETURNING id
            """),
            {
                "seq_id": sequence_id,
                "step_num": step.step_number,
                "send_after": step.send_after,
                "send_unit": step.send_after_unit,
                "delay_min": step.random_delay_min,
                "delay_max": step.random_delay_max
            }
        )

        step_id = result.fetchone()[0]
        db.commit()

        return {
            "success": True,
            "message": "Step criado com sucesso",
            "step_id": step_id
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao criar step: {str(e)}")

@router.get("/steps/{step_id}/messages")
def get_nutrition_messages(
    step_id: int,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """Lista as mensagens de um step."""
    try:
        # Verificar se step pertence à empresa
        step_check = db.execute(
            text("""
                SELECT ncs.id
                FROM nutrition_campaign_steps ncs
                JOIN nutrition_campaign_sequences seq ON seq.id = ncs.nutrition_campaign_sequence_id
                WHERE ncs.id = :step_id AND seq.company_id = :company_id
            """),
            {"step_id": step_id, "company_id": getattr(current_user, 'company_id', None)}
        ).fetchone()

        if not step_check:
            raise HTTPException(status_code=404, detail="Step não encontrado")

        messages = db.execute(
            text("""
                SELECT id, type, content, created_at, updated_at
                FROM nutrition_campaign_messages
                WHERE nutrition_campaign_step_id = :step_id
                ORDER BY id
            """),
            {"step_id": step_id}
        ).fetchall()

        return {
            "success": True,
            "messages": [dict(msg) for msg in messages]
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao buscar mensagens: {str(e)}")

@router.post("/steps/{step_id}/messages")
def create_nutrition_message(
    step_id: int,
    message: NutritionCampaignMessageCreate,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """Cria uma nova mensagem no step."""
    try:
        # Verificar se step pertence à empresa
        step_check = db.execute(
            text("""
                SELECT ncs.id
                FROM nutrition_campaign_steps ncs
                JOIN nutrition_campaign_sequences seq ON seq.id = ncs.nutrition_campaign_sequence_id
                WHERE ncs.id = :step_id AND seq.company_id = :company_id
            """),
            {"step_id": step_id, "company_id": getattr(current_user, 'company_id', None)}
        ).fetchone()

        if not step_check:
            raise HTTPException(status_code=404, detail="Step não encontrado")

        # Inserir mensagem
        result = db.execute(
            text("""
                INSERT INTO nutrition_campaign_messages (
                    nutrition_campaign_step_id, type, content
                ) VALUES (
                    :step_id, :type, :content
                ) RETURNING id
            """),
            {
                "step_id": step_id,
                "type": message.type,
                "content": message.content
            }
        )

        message_id = result.fetchone()[0]
        db.commit()

        return {
            "success": True,
            "message": "Mensagem criada com sucesso",
            "message_id": message_id
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao criar mensagem: {str(e)}")

@router.put("/messages/{message_id}")
def update_nutrition_message(
    message_id: int,
    message: NutritionCampaignMessageUpdate,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """Atualiza uma mensagem."""
    try:
        # Verificar se mensagem pertence à empresa
        message_check = db.execute(
            text("""
                SELECT ncm.id
                FROM nutrition_campaign_messages ncm
                JOIN nutrition_campaign_steps ncs ON ncs.id = ncm.nutrition_campaign_step_id
                JOIN nutrition_campaign_sequences seq ON seq.id = ncs.nutrition_campaign_sequence_id
                WHERE ncm.id = :msg_id AND seq.company_id = :company_id
            """),
            {"msg_id": message_id, "company_id": getattr(current_user, 'company_id', None)}
        ).fetchone()

        if not message_check:
            raise HTTPException(status_code=404, detail="Mensagem não encontrada")

        # Montar UPDATE dinâmico
        update_fields = []
        update_params = {"msg_id": message_id}

        if message.type is not None:
            update_fields.append("type = :type")
            update_params["type"] = message.type

        if message.content is not None:
            update_fields.append("content = :content")
            update_params["content"] = message.content

        if update_fields:
            update_fields.append("updated_at = NOW()")
            update_query = f"""
                UPDATE nutrition_campaign_messages
                SET {', '.join(update_fields)}
                WHERE id = :msg_id
            """

            db.execute(text(update_query), update_params)
            db.commit()

        return {
            "success": True,
            "message": "Mensagem atualizada com sucesso"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar mensagem: {str(e)}")

@router.delete("/messages/{message_id}")
def delete_nutrition_message(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """Remove uma mensagem."""
    try:
        # Verificar se mensagem pertence à empresa
        message_check = db.execute(
            text("""
                SELECT ncm.id
                FROM nutrition_campaign_messages ncm
                JOIN nutrition_campaign_steps ncs ON ncs.id = ncm.nutrition_campaign_step_id
                JOIN nutrition_campaign_sequences seq ON seq.id = ncs.nutrition_campaign_sequence_id
                WHERE ncm.id = :msg_id AND seq.company_id = :company_id
            """),
            {"msg_id": message_id, "company_id": getattr(current_user, 'company_id', None)}
        ).fetchone()

        if not message_check:
            raise HTTPException(status_code=404, detail="Mensagem não encontrada")

        db.execute(
            text("DELETE FROM nutrition_campaign_messages WHERE id = :msg_id"),
            {"msg_id": message_id}
        )

        db.commit()

        return {
            "success": True,
            "message": "Mensagem removida com sucesso"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao remover mensagem: {str(e)}")

@router.post("/sequences/{sequence_id}/schedule")
def create_nutrition_schedule_config(
    sequence_id: int,
    config: NutritionCampaignScheduleConfigCreate,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """Cria configuração de horários para uma sequência."""
    try:
        # Verificar se sequência pertence à empresa
        sequence_check = db.execute(
            text("""
                SELECT id FROM nutrition_campaign_sequences
                WHERE id = :seq_id AND company_id = :company_id
            """),
            {"seq_id": sequence_id, "company_id": getattr(current_user, 'company_id', None)}
        ).fetchone()

        if not sequence_check:
            raise HTTPException(status_code=404, detail="Sequência não encontrada")

        # Inserir ou atualizar configuração
        db.execute(
            text("""
                INSERT INTO nutrition_campaign_schedule_configs (
                    company_id, nutrition_campaign_sequence_id, schedule_data
                ) VALUES (
                    :company_id, :seq_id, :schedule_data
                ) ON CONFLICT (company_id, nutrition_campaign_sequence_id)
                DO UPDATE SET
                    schedule_data = EXCLUDED.schedule_data,
                    updated_at = NOW()
            """),
            {
                "company_id": getattr(current_user, 'company_id', None),
                "seq_id": sequence_id,
                "schedule_data": json.dumps(config.schedule_data)
            }
        )

        db.commit()

        return {
            "success": True,
            "message": "Configuração de horários salva com sucesso"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao salvar configuração: {str(e)}")

@router.post("/launch")
def launch_nutrition_campaign(
    request: CampaignLaunchRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """Lança campanha de nutrição para contatos elegíveis."""
    try:
        from backend.worker.tasks_nutrition_campaign import iniciar_nutrition_campaign_para_contatos

        company_id = int(getattr(current_user, "company_id", 0) or 0)
        operational_epoch = capture_company_job_epoch(db, company_id)
        db.commit()

        # Agendar task em background
        background_tasks.add_task(
            iniciar_nutrition_campaign_para_contatos.delay,
            company_id,
            request.sequence_id,
            operational_epoch,
        )

        return {
            "success": True,
            "message": "Campanha de nutrição iniciada com sucesso! Os disparos serão processados em background."
        }

    except CompanyOperationallyBlockedError as exc:
        db.rollback()
        raise HTTPException(
            status_code=423,
            detail=f"Acesso operacional bloqueado: {exc.status}",
        ) from exc
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao lançar campanha: {str(e)}")

@router.get("/executions")
def get_nutrition_executions(
    sequence_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """Lista execuções de campanhas de nutrição."""
    try:
        query = """
            SELECT nce.id, nce.contact_id, nce.step_number, nce.status,
                   nce.scheduled_for, nce.executed_at, nce.error_message,
                   nce.random_delay_applied, nce.targeting_criteria_matched,
                   c.name as contact_name, c.phone as contact_phone,
                   seq.name as sequence_name
            FROM nutrition_campaign_executions nce
            JOIN contacts c ON c.id = nce.contact_id
            JOIN nutrition_campaign_sequences seq ON seq.id = nce.nutrition_campaign_sequence_id
            WHERE nce.company_id = :company_id
        """

        params = {"company_id": getattr(current_user, 'company_id', None)}

        if sequence_id:
            query += " AND nce.nutrition_campaign_sequence_id = :seq_id"
            params["seq_id"] = sequence_id

        if status:
            query += " AND nce.status = :status"
            params["status"] = status

        query += " ORDER BY nce.created_at DESC LIMIT :limit"
        params["limit"] = limit

        executions = db.execute(text(query), params).fetchall()

        return {
            "success": True,
            "executions": [dict(exec) for exec in executions]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao buscar execuções: {str(e)}")

@router.get("/stats")
def get_nutrition_campaign_stats(
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """Estatísticas das campanhas de nutrição."""
    try:
        stats = db.execute(
            text("""
                SELECT
                    seq.name as sequence_name,
                    COUNT(nce.id) as total_executions,
                    COUNT(CASE WHEN nce.status = 'SUCCESS' THEN 1 END) as successful_executions,
                    COUNT(CASE WHEN nce.status = 'FAILED' THEN 1 END) as failed_executions,
                    COUNT(CASE WHEN nce.status = 'SCHEDULED' THEN 1 END) as scheduled_executions,
                    COUNT(CASE WHEN nce.status = 'PROCESSING' THEN 1 END) as processing_executions
                FROM nutrition_campaign_sequences seq
                LEFT JOIN nutrition_campaign_executions nce ON nce.nutrition_campaign_sequence_id = seq.id
                WHERE seq.company_id = :company_id
                GROUP BY seq.id, seq.name
                ORDER BY seq.name
            """),
            {"company_id": getattr(current_user, 'company_id', None)}
        ).fetchall()

        return {
            "success": True,
            "stats": [dict(stat) for stat in stats]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao buscar estatísticas: {str(e)}")

@router.get("/targeting/preview")
def preview_targeting_criteria(
    target_contact_status: Optional[List[str]] = None,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """Preview dos contatos que seriam atingidos pelos critérios de targeting."""
    try:
        company_id = getattr(current_user, 'company_id', None)
        if not company_id:
            raise HTTPException(status_code=400, detail="Company ID não encontrado")

        # Usar a mesma rota que o ContactsList usa, importando a função
        from backend.routes.webhook import get_contacts
        from fastapi import Request
        from urllib.parse import urlencode

        # Simular request para usar a função existente
        funnel_stages_param = ','.join(target_contact_status) if target_contact_status else None

        # Chamar a função existente diretamente
        try:
            response = get_contacts(
                user=current_user,
                db=db,
                q_client_id=getattr(current_user, 'id', None),
                q_company_id=company_id,
                limit=500,
                offset=0,
                search=None,
                unread_only=False,
                show_archived=False,
                archived_only=False,
                funnel_stages=funnel_stages_param,
                active_flows=None
            )

            # Extrair contatos da resposta
            contacts_data = response.get('contacts', [])

            # Converter para formato esperado pelo frontend
            contacts_list = []
            for contact in contacts_data:
                contacts_list.append({
                    "id": contact.get("id"),
                    "name": contact.get("name"),
                    "phone": contact.get("phone"),
                    "status": contact.get("funnel_stage", "contato"),
                    "categoria": "",
                    "tags": []
                })

            return {
                "success": True,
                "total_contacts": len(contacts_list),
                "contacts": contacts_list
            }

        except Exception as contacts_error:
            # Fallback: buscar todos os contatos e filtrar manualmente
            all_contacts_response = get_contacts(
                user=current_user,
                db=db,
                q_client_id=getattr(current_user, 'id', None),
                q_company_id=company_id,
                limit=500,
                offset=0,
                search=None,
                unread_only=False,
                show_archived=False,
                archived_only=False,
                funnel_stages=None,
                active_flows=None
            )

            all_contacts = all_contacts_response.get('contacts', [])

            # Filtrar por target_contact_status se especificado
            filtered_contacts = []
            for contact in all_contacts:
                if not target_contact_status or contact.get("funnel_stage") in target_contact_status:
                    filtered_contacts.append({
                        "id": contact.get("id"),
                        "name": contact.get("name"),
                        "phone": contact.get("phone"),
                        "status": contact.get("funnel_stage", "contato"),
                        "categoria": "",
                        "tags": []
                    })

            return {
                "success": True,
                "total_contacts": len(filtered_contacts),
                "contacts": filtered_contacts
            }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao buscar preview: {str(e)}")
