# backend/routes/plans_routes.py
"""
API REST para gestão de Planos de Serviço.
CRUD completo + listagem filtrada.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status, Header, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import List, Optional
from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import datetime

from backend.db import get_db
from backend.auth import verify_client_or_bearer_api_key
from backend.models import Client
from backend.models.revenue_models import Plan

logger = logging.getLogger("agentive.plans")

router = APIRouter(
    prefix="/clients/{client_id}/companies/{company_id}/plans",
    tags=["Plans - Planos de Serviço"]
)


# -----------------------------------------------------------------------------
# Autenticação via API Key
# -----------------------------------------------------------------------------
async def verify_api_key(
    api_key: str = Header(..., alias="X-API-Key"),
    client_id: int = None,
    db: Session = Depends(get_db)
):
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
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key inválida"
        )

    return client


# -----------------------------------------------------------------------------
# Schemas Pydantic
# -----------------------------------------------------------------------------

class PlanCreate(BaseModel):
    """Schema para criação de plano."""
    name: str = Field(..., min_length=1, max_length=255)
    code: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = None
    price: Decimal = Field(..., ge=0)
    currency: str = Field(default="BRL", max_length=3)
    billing_interval: str = Field(default="once")  # once, monthly, quarterly, yearly
    billing_interval_count: int = Field(default=1, ge=1)
    trial_period_days: int = Field(default=0, ge=0)
    features: List[str] = Field(default_factory=list)
    is_active: bool = Field(default=True)
    category: Optional[str] = Field(None, max_length=50)

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Tratamento Ortodôntico Completo",
                "code": "ORTO-001",
                "description": "Tratamento ortodôntico com aparelho fixo por 24 meses",
                "price": 6000.00,
                "billing_interval": "once",
                "category": "tratamento"
            }
        }


class PlanUpdate(BaseModel):
    """Schema para atualização de plano."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    code: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = None
    price: Optional[Decimal] = Field(None, ge=0)
    currency: Optional[str] = Field(None, max_length=3)
    billing_interval: Optional[str] = None
    billing_interval_count: Optional[int] = Field(None, ge=1)
    trial_period_days: Optional[int] = Field(None, ge=0)
    features: Optional[List[str]] = None
    is_active: Optional[bool] = None
    category: Optional[str] = Field(None, max_length=50)


class PlanResponse(BaseModel):
    """Schema de resposta de plano."""
    id: int
    company_id: int
    name: str
    code: Optional[str]
    description: Optional[str]
    price: Decimal
    currency: str
    billing_interval: str
    billing_interval_count: int
    trial_period_days: int
    features: List[str]
    is_active: bool
    category: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# -----------------------------------------------------------------------------
# Rotas CRUD
# -----------------------------------------------------------------------------

@router.get("/", response_model=List[PlanResponse])
async def listar_planos(
    client_id: int,
    company_id: int,
    is_active: Optional[bool] = Query(None, description="Filtrar por status ativo"),
    category: Optional[str] = Query(None, description="Filtrar por categoria"),
    billing_interval: Optional[str] = Query(None, description="Filtrar por intervalo de cobrança"),
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Lista todos os planos de uma empresa.

    Filtros opcionais:
    - is_active: true/false
    - category: tratamento, procedimento, manutenção
    - billing_interval: once, monthly, quarterly, yearly
    """
    logger.info(f"[listar_planos] company_id={company_id}")

    try:
        query = db.query(Plan).filter(Plan.company_id == company_id)

        if is_active is not None:
            query = query.filter(Plan.is_active == is_active)
        if category:
            query = query.filter(Plan.category == category)
        if billing_interval:
            query = query.filter(Plan.billing_interval == billing_interval)

        planos = query.order_by(Plan.name).all()
        logger.info(f"[listar_planos] Retornando {len(planos)} planos")
        return planos

    except Exception as e:
        logger.exception("[listar_planos] Erro ao listar planos")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )


@router.get("/{plan_id}", response_model=PlanResponse)
async def obter_plano(
    client_id: int,
    company_id: int,
    plan_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """Obtém um plano específico pelo ID."""
    logger.info(f"[obter_plano] company_id={company_id}, plan_id={plan_id}")

    try:
        plano = db.query(Plan).filter(
            Plan.id == plan_id,
            Plan.company_id == company_id
        ).first()

        if not plano:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Plano não encontrado"
            )

        return plano

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[obter_plano] Erro ao obter plano")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )


@router.post("/", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
async def criar_plano(
    client_id: int,
    company_id: int,
    payload: PlanCreate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """Cria um novo plano de serviço."""
    logger.info(f"[criar_plano] company_id={company_id}, payload={payload.model_dump()}")

    # Validar billing_interval
    valid_intervals = ['once', 'monthly', 'quarterly', 'yearly']
    if payload.billing_interval not in valid_intervals:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"billing_interval inválido. Use: {', '.join(valid_intervals)}"
        )

    # Verificar se código já existe (se fornecido)
    if payload.code:
        existing = db.query(Plan).filter(
            Plan.company_id == company_id,
            Plan.code == payload.code
        ).first()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Já existe um plano com o código '{payload.code}'"
            )

    try:
        novo_plano = Plan(
            company_id=company_id,
            name=payload.name,
            code=payload.code,
            description=payload.description,
            price=payload.price,
            currency=payload.currency,
            billing_interval=payload.billing_interval,
            billing_interval_count=payload.billing_interval_count,
            trial_period_days=payload.trial_period_days,
            features=payload.features or [],
            is_active=payload.is_active,
            category=payload.category
        )

        db.add(novo_plano)
        db.commit()
        db.refresh(novo_plano)

        logger.info(f"[criar_plano] Plano criado com ID {novo_plano.id}")
        return novo_plano

    except Exception as e:
        db.rollback()
        logger.exception("[criar_plano] Erro ao criar plano")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao criar plano: {str(e)}"
        )


@router.put("/{plan_id}", response_model=PlanResponse)
async def atualizar_plano(
    client_id: int,
    company_id: int,
    plan_id: int,
    payload: PlanUpdate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """Atualiza um plano existente."""
    logger.info(f"[atualizar_plano] company_id={company_id}, plan_id={plan_id}")

    plano = db.query(Plan).filter(
        Plan.id == plan_id,
        Plan.company_id == company_id
    ).first()

    if not plano:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plano não encontrado"
        )

    # Validar billing_interval se fornecido
    if payload.billing_interval:
        valid_intervals = ['once', 'monthly', 'quarterly', 'yearly']
        if payload.billing_interval not in valid_intervals:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"billing_interval inválido. Use: {', '.join(valid_intervals)}"
            )

    # Verificar código duplicado se alterado
    if payload.code and payload.code != plano.code:
        existing = db.query(Plan).filter(
            Plan.company_id == company_id,
            Plan.code == payload.code,
            Plan.id != plan_id
        ).first()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Já existe um plano com o código '{payload.code}'"
            )

    try:
        update_data = payload.model_dump(exclude_unset=True)
        for campo, valor in update_data.items():
            setattr(plano, campo, valor)

        db.commit()
        db.refresh(plano)

        logger.info(f"[atualizar_plano] Plano {plan_id} atualizado")
        return plano

    except Exception as e:
        db.rollback()
        logger.exception("[atualizar_plano] Erro ao atualizar plano")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao atualizar plano: {str(e)}"
        )


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deletar_plano(
    client_id: int,
    company_id: int,
    plan_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Deleta um plano.

    Nota: Planos vinculados a contratos não podem ser deletados.
    """
    logger.info(f"[deletar_plano] company_id={company_id}, plan_id={plan_id}")

    plano = db.query(Plan).filter(
        Plan.id == plan_id,
        Plan.company_id == company_id
    ).first()

    if not plano:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plano não encontrado"
        )

    # Verificar se há itens de contrato vinculados
    from backend.models.revenue_models import ContractItem
    has_contracts = db.query(ContractItem).filter(
        ContractItem.plan_id == plan_id
    ).first()

    if has_contracts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não é possível deletar este plano pois existem contratos vinculados. Desative-o em vez de deletar."
        )

    try:
        db.delete(plano)
        db.commit()
        logger.info(f"[deletar_plano] Plano {plan_id} deletado")
        return None

    except Exception as e:
        db.rollback()
        logger.exception("[deletar_plano] Erro ao deletar plano")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao deletar plano: {str(e)}"
        )
