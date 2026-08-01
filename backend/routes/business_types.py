"""
Rotas para gerenciamento de tipos de negócio (Business Types).

Permite criar, listar, atualizar e deletar tipos de negócio para
customização da plataforma (funis, dashboards, terminologia).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from backend.db import get_db
from backend.models import BusinessType, Company, Client, User
from backend.auth import get_current_user
from typing import Union

router = APIRouter(prefix="/api/business-types", tags=["Business Types"])


# ==================== SCHEMAS ====================

class BusinessTypeBase(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    default_config: dict = {}
    icon: Optional[str] = None
    enabled: bool = True


class BusinessTypeCreate(BusinessTypeBase):
    """Schema para criação de um novo tipo de negócio"""
    pass


class BusinessTypeUpdate(BaseModel):
    """Schema para atualização (todos os campos opcionais)"""
    code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    default_config: Optional[dict] = None
    icon: Optional[str] = None
    enabled: Optional[bool] = None


class BusinessTypeResponse(BusinessTypeBase):
    """Schema de resposta com todos os campos"""
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BusinessTypeWithStats(BusinessTypeResponse):
    """Business Type com estatísticas de uso"""
    companies_count: int


# ==================== ENDPOINTS ====================

@router.get("/", response_model=List[BusinessTypeWithStats])
async def list_business_types(
    enabled_only: bool = False,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """
    Lista todos os tipos de negócio disponíveis.

    - **enabled_only**: Se True, retorna apenas tipos habilitados
    """
    query = db.query(BusinessType)

    if enabled_only:
        query = query.filter(BusinessType.enabled == True)

    business_types = query.order_by(BusinessType.name).all()

    # Adicionar contagem de empresas usando cada tipo
    result = []
    for bt in business_types:
        count = db.query(Company).filter(Company.business_type_id == bt.id).count()
        bt_dict = {
            "id": bt.id,
            "code": bt.code,
            "name": bt.name,
            "description": bt.description,
            "default_config": bt.default_config,
            "icon": bt.icon,
            "enabled": bt.enabled,
            "created_at": bt.created_at,
            "updated_at": bt.updated_at,
            "companies_count": count
        }
        result.append(bt_dict)

    return result


@router.get("/{business_type_id}", response_model=BusinessTypeResponse)
async def get_business_type(
    business_type_id: int,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """
    Busca um tipo de negócio específico por ID.
    """
    business_type = db.query(BusinessType).filter(
        BusinessType.id == business_type_id
    ).first()

    if not business_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Business type com ID {business_type_id} não encontrado"
        )

    return business_type


@router.get("/by-code/{code}", response_model=BusinessTypeResponse)
async def get_business_type_by_code(
    code: str,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """
    Busca um tipo de negócio pelo código.
    """
    business_type = db.query(BusinessType).filter(
        BusinessType.code == code
    ).first()

    if not business_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Business type com código '{code}' não encontrado"
        )

    return business_type


@router.post("/", response_model=BusinessTypeResponse, status_code=status.HTTP_201_CREATED)
async def create_business_type(
    business_type_data: BusinessTypeCreate,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """
    Cria um novo tipo de negócio.

    **Exemplo de default_config**:
    ```json
    {
        "funnel_stages": ["leads", "appointments", "attendances", "sales"],
        "terminology": {
            "lead": "Cliente",
            "appointment": "Reunião",
            "attendance": "Atendimento",
            "sale": "Fechamento"
        },
        "dashboard_widgets": ["kpi_leads", "kpi_appointments", "funnel_chart"],
        "features": ["scheduling", "crm", "reports"]
    }
    ```
    """
    # Verificar se já existe um business type com esse código
    existing = db.query(BusinessType).filter(
        BusinessType.code == business_type_data.code
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Já existe um business type com o código '{business_type_data.code}'"
        )

    # Criar novo business type
    new_business_type = BusinessType(
        code=business_type_data.code,
        name=business_type_data.name,
        description=business_type_data.description,
        default_config=business_type_data.default_config,
        icon=business_type_data.icon,
        enabled=business_type_data.enabled
    )

    db.add(new_business_type)
    db.commit()
    db.refresh(new_business_type)

    return new_business_type


@router.put("/{business_type_id}", response_model=BusinessTypeResponse)
async def update_business_type(
    business_type_id: int,
    business_type_data: BusinessTypeUpdate,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """
    Atualiza um tipo de negócio existente.
    """
    business_type = db.query(BusinessType).filter(
        BusinessType.id == business_type_id
    ).first()

    if not business_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Business type com ID {business_type_id} não encontrado"
        )

    # Verificar se está tentando alterar o código para um que já existe
    if business_type_data.code and business_type_data.code != business_type.code:
        existing = db.query(BusinessType).filter(
            BusinessType.code == business_type_data.code
        ).first()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Já existe um business type com o código '{business_type_data.code}'"
            )

    # Atualizar campos fornecidos
    update_data = business_type_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(business_type, field, value)

    db.commit()
    db.refresh(business_type)

    return business_type


@router.delete("/{business_type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_business_type(
    business_type_id: int,
    force: bool = False,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """
    Deleta um tipo de negócio.

    - **force**: Se True, permite deletar mesmo com empresas associadas (elas ficarão órfãs!)

    **AVISO**: Por padrão, não é possível deletar um business type que tem empresas associadas.
    """
    business_type = db.query(BusinessType).filter(
        BusinessType.id == business_type_id
    ).first()

    if not business_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Business type com ID {business_type_id} não encontrado"
        )

    # Proteger o tipo padrão (business_company)
    if business_type.code == "business_company":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não é possível deletar o tipo padrão 'business_company'"
        )

    # Verificar se existem empresas usando este tipo
    companies_count = db.query(Company).filter(
        Company.business_type_id == business_type_id
    ).count()

    if companies_count > 0 and not force:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Não é possível deletar: existem {companies_count} empresa(s) usando este tipo. Use force=true para forçar."
        )

    db.delete(business_type)
    db.commit()

    return None


@router.patch("/{business_type_id}/toggle", response_model=BusinessTypeResponse)
async def toggle_business_type(
    business_type_id: int,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """
    Alterna o estado (habilitado/desabilitado) de um tipo de negócio.
    """
    business_type = db.query(BusinessType).filter(
        BusinessType.id == business_type_id
    ).first()

    if not business_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Business type com ID {business_type_id} não encontrado"
        )

    # Não permitir desabilitar o tipo padrão
    if business_type.code == "business_company" and business_type.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não é possível desabilitar o tipo padrão 'business_company'"
        )

    business_type.enabled = not business_type.enabled
    db.commit()
    db.refresh(business_type)

    return business_type
