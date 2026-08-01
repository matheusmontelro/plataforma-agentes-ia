# backend/routes/crm_kanban.py

import logging

from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from typing import List, Optional, Union
from pydantic import BaseModel
from backend.db import get_db
from backend.auth import get_current_user, verify_client_or_bearer_api_key
from backend.models import User, Client
from backend.services.pipeline_service import PipelineService

router = APIRouter()
logger = logging.getLogger(__name__)

# --- Função para verificar API Key ---
async def verify_api_key(
    api_key: str = Header(..., alias="X-API-Key"),
    client_id: int = None,
    db: Session = Depends(get_db)
):
    """
    Verifica se a API key é válida para o client_id fornecido
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key não fornecida"
        )

    client = db.query(Client).filter(
        Client.id == client_id,
        Client.api_key == api_key
    ).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API Key inválida ou sem permissão para este client"
        )

    return client

# --- Pydantic Schemas ---

class PipelineStageBase(BaseModel):
    name: str
    description: Optional[str] = None
    color: Optional[str] = "#3B82F6"
    is_converted_stage: Optional[bool] = False
    is_lost_stage: Optional[bool] = False
    auto_advance_days: Optional[int] = None
    follow_up_sequence_id: Optional[int] = None
    percentage_base_stage_id: Optional[int] = None

class PipelineStageCreate(PipelineStageBase):
    order: int

class PipelineStageUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    is_converted_stage: Optional[bool] = None
    is_lost_stage: Optional[bool] = None
    auto_advance_days: Optional[int] = None
    follow_up_sequence_id: Optional[int] = None
    percentage_base_stage_id: Optional[int] = None
    order: Optional[int] = None

class PipelineStageResponse(PipelineStageBase):
    id: int
    pipeline_id: int
    order: int
    is_first_stage: bool

    class Config:
        orm_mode = True

class PipelineBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: Optional[bool] = True

class PipelineCreate(PipelineBase):
    stages: Optional[List[PipelineStageCreate]] = []

class PipelineUpdate(PipelineBase):
    pass

class PipelineResponse(PipelineBase):
    id: int
    company_id: int
    created_by_user_id: Optional[int]
    created_at: str
    updated_at: str
    stages: List[PipelineStageResponse]

    class Config:
        orm_mode = True

class LeadMove(BaseModel):
    stage_id: int
    notes: Optional[str] = None

class StageOrder(BaseModel):
    stage_id: int
    order: int

class PipelineStats(BaseModel):
    total_leads: int
    leads_with_pipeline: int
    pipeline_adoption_rate: float
    stage_statistics: List[dict]

# --- Enhanced Pipeline Endpoints ---

@router.get("/pipelines", response_model=List[PipelineResponse])
async def get_pipelines(
    company_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: Union[User, Client] = Depends(get_current_user)
):
    """Listar pipelines da empresa do usuário (via JWT Token)"""

    # Se company_id não fornecido, usar do usuário atual
    if not company_id:
        company_id = current_user.company_id

    logger.debug(
        "CRM pipeline lookup: user_id=%s user_company_id=%s requested_company_id=%s user_type=%s",
        current_user.id,
        current_user.company_id,
        company_id,
        type(current_user).__name__,
    )

    if not company_id:
        raise HTTPException(status_code=400, detail="Company_id não fornecido")

    # Verificar permissão (se company_id diferente do usuário)
    if current_user.company_id != company_id:
        logger.warning(
            "CRM pipeline permission mismatch: user_company_id=%s requested_company_id=%s",
            current_user.company_id,
            company_id,
        )
        # TODO: Implementar verificação de permissão admin
        pass

    from backend.models import Pipeline

    pipelines = db.query(Pipeline).filter(
        Pipeline.company_id == company_id
    ).all()

    result = []
    for pipeline in pipelines:
        stages_data = []
        for stage in sorted(pipeline.stages, key=lambda x: x.order):
            stages_data.append(PipelineStageResponse(
                id=stage.id,
                pipeline_id=stage.pipeline_id,
                name=stage.name,
                description=stage.description,
                color=stage.color,
                order=stage.order,
                is_first_stage=stage.is_first_stage,
                is_converted_stage=stage.is_converted_stage,
                is_lost_stage=stage.is_lost_stage,
                auto_advance_days=stage.auto_advance_days,
                follow_up_sequence_id=stage.follow_up_sequence_id,
                percentage_base_stage_id=stage.percentage_base_stage_id
            ))

        result.append(PipelineResponse(
            id=pipeline.id,
            company_id=pipeline.company_id,
            name=pipeline.name,
            description=pipeline.description,
            is_active=pipeline.is_active,
            created_by_user_id=pipeline.created_by_user_id,
            created_at=pipeline.created_at.isoformat() if pipeline.created_at else "",
            updated_at=pipeline.updated_at.isoformat() if pipeline.updated_at else "",
            stages=stages_data
        ))

    return result

# --- Pipeline Endpoints via API Key (para compatibilidade com frontend) ---

@router.get("/clients/{client_id}/companies/{company_id}/pipelines", response_model=List[PipelineResponse])
async def get_pipelines_api_key(
    client_id: int,
    company_id: int,
    db: Session = Depends(get_db),
    current_client: Client = Depends(verify_client_or_bearer_api_key)
):
    """Listar pipelines da empresa via API Key"""

    logger.debug(
        "CRM pipeline API key lookup: client_id=%s company_id=%s",
        client_id,
        company_id,
    )

    from backend.models import Pipeline

    pipelines = db.query(Pipeline).filter(
        Pipeline.company_id == company_id
    ).all()

    result = []
    for pipeline in pipelines:
        stages_data = []
        for stage in sorted(pipeline.stages, key=lambda x: x.order):
            stages_data.append(PipelineStageResponse(
                id=stage.id,
                pipeline_id=stage.pipeline_id,
                name=stage.name,
                description=stage.description,
                color=stage.color,
                order=stage.order,
                is_first_stage=stage.is_first_stage,
                is_converted_stage=stage.is_converted_stage,
                is_lost_stage=stage.is_lost_stage,
                auto_advance_days=stage.auto_advance_days,
                follow_up_sequence_id=stage.follow_up_sequence_id,
                percentage_base_stage_id=stage.percentage_base_stage_id
            ))

        result.append(PipelineResponse(
            id=pipeline.id,
            company_id=pipeline.company_id,
            name=pipeline.name,
            description=pipeline.description,
            is_active=pipeline.is_active,
            created_by_user_id=pipeline.created_by_user_id,
            created_at=pipeline.created_at.isoformat() if pipeline.created_at else "",
            updated_at=pipeline.updated_at.isoformat() if pipeline.updated_at else "",
            stages=stages_data
        ))

    return result

@router.post("/pipelines", response_model=PipelineResponse)
async def create_pipeline(
    pipeline_data: PipelineCreate,
    company_id: int,
    db: Session = Depends(get_db),
    current_user: Union[User, Client] = Depends(get_current_user)
):

    if not company_id:
        raise HTTPException(status_code=400, detail="Company_id não fornecido")

    # Verificar permissão (se company_id diferente do usuário)
    if current_user.company_id != company_id:
        logger.warning(
            "CRM pipeline permission mismatch: user_company_id=%s requested_company_id=%s",
            current_user.company_id,
            company_id,
        )
        # TODO: Implementar verificação de permissão admin
        pass

    from backend.models import Pipeline

    pipelines = db.query(Pipeline).filter(
        Pipeline.company_id == company_id
    ).all()

    result = []
    for pipeline in pipelines:
        stages_data = []
        for stage in sorted(pipeline.stages, key=lambda x: x.order):
            stages_data.append(PipelineStageResponse(
                id=stage.id,
                pipeline_id=stage.pipeline_id,
                name=stage.name,
                description=stage.description,
                color=stage.color,
                order=stage.order,
                is_first_stage=stage.is_first_stage,
                is_converted_stage=stage.is_converted_stage,
                is_lost_stage=stage.is_lost_stage,
                auto_advance_days=stage.auto_advance_days,
                follow_up_sequence_id=stage.follow_up_sequence_id,
                percentage_base_stage_id=stage.percentage_base_stage_id
            ))

        result.append(PipelineResponse(
            id=pipeline.id,
            company_id=pipeline.company_id,
            name=pipeline.name,
            description=pipeline.description,
            is_active=pipeline.is_active,
            created_by_user_id=pipeline.created_by_user_id,
            created_at=pipeline.created_at.isoformat() if pipeline.created_at else "",
            updated_at=pipeline.updated_at.isoformat() if pipeline.updated_at else "",
            stages=stages_data
        ))

    return result

@router.post("/pipelines", response_model=PipelineResponse)
async def create_pipeline(
    pipeline_data: PipelineCreate,
    company_id: int,
    db: Session = Depends(get_db),
    current_user: Union[User, Client] = Depends(get_current_user)
):
    """Criar novo pipeline para a empresa"""

    # Validar permissão
    if current_user.company_id != company_id:
        raise HTTPException(status_code=403, detail="Sem permissão para esta empresa")

    # Criar pipeline usando serviço
    from backend.models import Pipeline

    pipeline = Pipeline(
        company_id=company_id,
        name=pipeline_data.name,
        description=pipeline_data.description,
        created_by_user_id=current_user.id,
        is_active=True
    )

    db.add(pipeline)
    db.flush()

    # Criar etapa inicial obrigatória
    from backend.models import PipelineStage

    first_stage = PipelineStage(
        pipeline_id=pipeline.id,
        name="Novo Lead",
        description="Primeiro contato - configure mais etapas conforme necessário",
        color="#3B82F6",
        order=1,
        order_index=1,  # Manter sincronizado com order
        is_first_stage=True
    )

    db.add(first_stage)

    # Criar etapas adicionais se fornecidas
    for i, stage_data in enumerate(pipeline_data.stages or [], start=2):
        stage = PipelineStage(
            pipeline_id=pipeline.id,
            order=i,
            order_index=i,  # Manter sincronizado com order
            name=stage_data.name,
            description=stage_data.description,
            color=stage_data.color,
            is_converted_stage=stage_data.is_converted_stage,
            is_lost_stage=stage_data.is_lost_stage,
            auto_advance_days=stage_data.auto_advance_days
        )
        db.add(stage)

    db.commit()
    db.refresh(pipeline)

    # Retornar com formato de resposta
    stages_data = []
    for stage in sorted(pipeline.stages, key=lambda x: x.order):
        stages_data.append(PipelineStageResponse(
            id=stage.id,
            pipeline_id=stage.pipeline_id,
            name=stage.name,
            description=stage.description,
            color=stage.color,
            order=stage.order,
            is_first_stage=stage.is_first_stage,
            is_converted_stage=stage.is_converted_stage,
            is_lost_stage=stage.is_lost_stage,
            auto_advance_days=stage.auto_advance_days,
            follow_up_sequence_id=stage.follow_up_sequence_id,
            percentage_base_stage_id=stage.percentage_base_stage_id
        ))

    return PipelineResponse(
        id=pipeline.id,
        company_id=pipeline.company_id,
        name=pipeline.name,
        description=pipeline.description,
        is_active=pipeline.is_active,
        created_by_user_id=pipeline.created_by_user_id,
        created_at=pipeline.created_at.isoformat() if pipeline.created_at else "",
        updated_at=pipeline.updated_at.isoformat() if pipeline.updated_at else "",
        stages=stages_data
    )

@router.post("/pipelines/{pipeline_id}/stages", response_model=PipelineStageResponse)
async def add_stage_to_pipeline(
    pipeline_id: int,
    stage_data: PipelineStageCreate,
    db: Session = Depends(get_db),
    current_user: Union[User, Client] = Depends(get_current_user)
):
    """Adicionar nova etapa a um pipeline existente"""

    # Validar que pipeline pertence à empresa do usuário
    from backend.models import Pipeline

    pipeline = db.query(Pipeline).filter(
        Pipeline.id == pipeline_id
    ).first()

    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline não encontrado")

    if current_user.company_id != pipeline.company_id:
        raise HTTPException(status_code=403, detail="Sem permissão para este pipeline")

    try:
        stage = PipelineService.create_custom_stage(pipeline_id, stage_data.dict(), db)

        return PipelineStageResponse(
            id=stage.id,
            pipeline_id=stage.pipeline_id,
            name=stage.name,
            description=stage.description,
            color=stage.color,
            order=stage.order,
            is_first_stage=stage.is_first_stage,
            is_converted_stage=stage.is_converted_stage,
            is_lost_stage=stage.is_lost_stage,
            auto_advance_days=stage.auto_advance_days,
            follow_up_sequence_id=stage.follow_up_sequence_id,
            percentage_base_stage_id=stage.percentage_base_stage_id
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao criar etapa: {str(e)}"
        )

@router.put("/pipelines/stages/{stage_id}", response_model=PipelineStageResponse)
async def update_pipeline_stage(
    stage_id: int,
    stage_data: PipelineStageUpdate,
    db: Session = Depends(get_db),
    current_user: Union[User, Client] = Depends(get_current_user)
):
    """Atualizar dados de uma etapa do pipeline"""

    from backend.models import PipelineStage

    stage = db.query(PipelineStage).filter(PipelineStage.id == stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Etapa não encontrada")

    if current_user.company_id != stage.pipeline.company_id:
        raise HTTPException(status_code=403, detail="Sem permissão para esta etapa")

    payload = stage_data.dict(exclude_unset=True)

    if "name" in payload and not payload["name"].strip():
        raise HTTPException(status_code=400, detail="Nome da etapa não pode ficar vazio")

    if payload.get("is_converted_stage") is True and not stage.is_converted_stage:
        existing_converted = db.query(PipelineStage).filter(
            PipelineStage.pipeline_id == stage.pipeline_id,
            PipelineStage.is_converted_stage == True,
            PipelineStage.id != stage.id
        ).first()
        if existing_converted:
            raise HTTPException(status_code=400, detail="Já existe uma etapa de 'Convertido' neste pipeline")

    if payload.get("is_lost_stage") is True and not stage.is_lost_stage:
        existing_lost = db.query(PipelineStage).filter(
            PipelineStage.pipeline_id == stage.pipeline_id,
            PipelineStage.is_lost_stage == True,
            PipelineStage.id != stage.id
        ).first()
        if existing_lost:
            raise HTTPException(status_code=400, detail="Já existe uma etapa de 'Perdido' neste pipeline")

    if "percentage_base_stage_id" in payload:
        base_stage_id = payload["percentage_base_stage_id"]
        if base_stage_id is not None:
            if base_stage_id == stage.id:
                raise HTTPException(status_code=400, detail="A etapa não pode usar ela mesma como base percentual")
            if stage.is_first_stage:
                raise HTTPException(status_code=400, detail="A etapa inicial deve usar Leads como base percentual")
            base_stage = db.query(PipelineStage).filter(
                PipelineStage.id == base_stage_id,
                PipelineStage.pipeline_id == stage.pipeline_id
            ).first()
            if not base_stage:
                raise HTTPException(status_code=400, detail="Etapa base do percentual não pertence a este pipeline")

    allowed_fields = {
        "name",
        "description",
        "color",
        "is_converted_stage",
        "is_lost_stage",
        "auto_advance_days",
        "follow_up_sequence_id",
        "percentage_base_stage_id",
        "order",
    }

    for field, value in payload.items():
        if field in allowed_fields:
            setattr(stage, field, value)
            if field == "order":
                stage.order_index = value

    db.commit()
    db.refresh(stage)

    return PipelineStageResponse(
        id=stage.id,
        pipeline_id=stage.pipeline_id,
        name=stage.name,
        description=stage.description,
        color=stage.color,
        order=stage.order,
        is_first_stage=stage.is_first_stage,
        is_converted_stage=stage.is_converted_stage,
        is_lost_stage=stage.is_lost_stage,
        auto_advance_days=stage.auto_advance_days,
        follow_up_sequence_id=stage.follow_up_sequence_id,
        percentage_base_stage_id=stage.percentage_base_stage_id
    )

@router.put("/pipelines/{pipeline_id}/stages/reorder")
async def reorder_pipeline_stages(
    pipeline_id: int,
    stage_orders: List[StageOrder],
    db: Session = Depends(get_db),
    current_user: Union[User, Client] = Depends(get_current_user)
):
    """Reordenar etapas de um pipeline"""

    # Validar permissão
    from backend.models import Pipeline

    pipeline = db.query(Pipeline).filter(Pipeline.id == pipeline_id).first()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline não encontrado")

    if current_user.company_id != pipeline.company_id:
        raise HTTPException(status_code=403, detail="Sem permissão para este pipeline")

    success = PipelineService.update_stage_order(
        [so.dict() for so in stage_orders],
        db
    )

    if success:
        return {"message": "Ordem das etapas atualizada com sucesso"}
    else:
        raise HTTPException(
            status_code=500,
            detail="Erro ao atualizar ordem das etapas"
        )

# --- Kanban Data Endpoints ---

@router.get("/pipelines/kanban/{company_id}")
async def get_pipeline_kanban_data(
    company_id: int,
    pipeline_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: Union[User, Client] = Depends(get_current_user)
):
    """Retorna dados formatados para visualização Kanban"""

    # Validar permissão
    if current_user.company_id != company_id:
        raise HTTPException(status_code=403, detail="Sem permissão para esta empresa")

    kanban_data = PipelineService.get_pipeline_kanban_data(
        company_id=company_id,
        pipeline_id=pipeline_id,
        db=db
    )

    return kanban_data

# --- Lead Movement Endpoints ---

@router.put("/pipelines/leads/{lead_id}/move")
async def move_lead_to_stage(
    lead_id: int,
    move_data: LeadMove,
    db: Session = Depends(get_db),
    current_user: Union[User, Client] = Depends(get_current_user)
):
    """Mover lead para nova etapa com histórico"""

    # Validar que lead pertence à empresa do usuário
    from backend.models import Lead

    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead não encontrado")

    if current_user.company_id != lead.company_id:
        raise HTTPException(status_code=403, detail="Sem permissão para este lead")

    try:
        # Verificar se current_user é User (para histórico) ou Client (sem usuário específico)
        user_id = current_user.id if hasattr(current_user, 'email') and 'users' in str(type(current_user)) else None

        history = PipelineService.move_lead_to_stage(
            lead_id=lead_id,
            new_stage_id=move_data.stage_id,
            user_id=user_id,
            notes=move_data.notes,
            db=db
        )

        return {
            "message": "Lead movido com sucesso",
            "lead_id": lead_id,
            "new_stage_id": move_data.stage_id,
            "history_id": history.id,
            "moved_at": history.moved_at.isoformat() if history.moved_at else None
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao mover lead: {str(e)}"
        )

@router.get("/pipelines/leads/{lead_id}/history")
async def get_lead_pipeline_history(
    lead_id: int,
    db: Session = Depends(get_db),
    current_user: Union[User, Client] = Depends(get_current_user)
):
    """Retornar histórico completo de movimentação do lead"""

    # Validar permissão
    from backend.models import Lead

    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead não encontrado")

    if current_user.company_id != lead.company_id:
        raise HTTPException(status_code=403, detail="Sem permissão para este lead")

    history = PipelineService.get_lead_pipeline_history(lead_id, db)

    return {
        "lead_id": lead_id,
        "pipeline_history": history
    }

# --- Analytics Endpoints ---

@router.get("/pipelines/statistics/{company_id}", response_model=PipelineStats)
async def get_pipeline_statistics(
    company_id: int,
    pipeline_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: Union[User, Client] = Depends(get_current_user)
):
    """Retornar estatísticas do pipeline para analytics"""

    # Validar permissão
    if current_user.company_id != company_id:
        raise HTTPException(status_code=403, detail="Sem permissão para esta empresa")

    stats = PipelineService.get_pipeline_statistics(
        company_id=company_id,
        pipeline_id=pipeline_id,
        db=db
    )

    return PipelineStats(**stats)

# --- Pipeline Management Endpoints ---

@router.put("/pipelines/{pipeline_id}")
async def update_pipeline(
    pipeline_id: int,
    pipeline_data: PipelineUpdate,
    db: Session = Depends(get_db),
    current_user: Union[User, Client] = Depends(get_current_user)
):
    """Atualizar dados do pipeline"""

    from backend.models import Pipeline

    pipeline = db.query(Pipeline).filter(Pipeline.id == pipeline_id).first()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline não encontrado")

    if current_user.company_id != pipeline.company_id:
        raise HTTPException(status_code=403, detail="Sem permissão para este pipeline")

    # Atualizar campos
    if pipeline_data.name:
        pipeline.name = pipeline_data.name
    if pipeline_data.description is not None:
        pipeline.description = pipeline_data.description
    if pipeline_data.is_active is not None:
        pipeline.is_active = pipeline_data.is_active

    db.commit()
    db.refresh(pipeline)

    return {"message": "Pipeline atualizado com sucesso"}

@router.delete("/pipelines/{pipeline_id}")
async def delete_pipeline(
    pipeline_id: int,
    db: Session = Depends(get_db),
    current_user: Union[User, Client] = Depends(get_current_user)
):
    """Excluir pipeline (validação de segurança)"""

    from backend.models import Pipeline, Lead

    pipeline = db.query(Pipeline).filter(Pipeline.id == pipeline_id).first()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline não encontrado")

    if current_user.company_id != pipeline.company_id:
        raise HTTPException(status_code=403, detail="Sem permissão para este pipeline")

    # Verificar se há leads ativos no pipeline
    leads_count = db.query(Lead).filter(Lead.pipeline_id == pipeline_id).count()
    if leads_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Não é possível excluir pipeline com {leads_count} leads ativos. Mova os leads para outro pipeline primeiro."
        )

    db.delete(pipeline)
    db.commit()

    return {"message": "Pipeline excluído com sucesso"}

@router.delete("/pipelines/stages/{stage_id}")
async def delete_pipeline_stage(
    stage_id: int,
    db: Session = Depends(get_db),
    current_user: Union[User, Client] = Depends(get_current_user)
):
    """Excluir etapa do pipeline (validação de segurança)"""

    from backend.models import PipelineStage, Lead

    stage = db.query(PipelineStage).filter(PipelineStage.id == stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Etapa não encontrada")

    # Validar permissão através do pipeline
    if current_user.company_id != stage.pipeline.company_id:
        raise HTTPException(status_code=403, detail="Sem permissão para esta etapa")

    # Impedir exclusão de etapa inicial
    if stage.is_first_stage:
        raise HTTPException(
            status_code=400,
            detail="Não é possível excluir a etapa inicial 'Novo Lead'"
        )

    # Verificar se há leads na etapa
    leads_count = db.query(Lead).filter(Lead.current_stage_id == stage_id).count()
    if leads_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Não é possível excluir etapa com {leads_count} leads. Mova os leads para outra etapa primeiro."
        )

    db.delete(stage)
    db.commit()

    return {"message": "Etapa excluída com sucesso"}
