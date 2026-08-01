"""
Rotas API para gestão de campos customizados de leads.

Este módulo define os endpoints para:
- Criar, editar, deletar campos customizados
- Listar campos customizados por empresa
- Reordenar campos customizados
- Validar valores de campos customizados
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from typing import List, Dict, Any

from backend.db import get_db
from backend.auth import verify_client_or_bearer_api_key
from backend.models import LeadCustomField, Client
from backend.routes.leads_routes import (
    LeadCustomFieldUpdate, LeadCustomFieldResponse, FieldOrderRequest
)
from backend.services.lead_custom_fields_service import (
    LeadCustomFieldsService, LeadCustomFieldCreate, LeadCustomFieldsValidationRequest
)
from backend.services.leads_with_custom_fields_service import LeadsWithCustomFieldsService

logger = logging.getLogger("saas_business.lead_custom_fields_routes")

router = APIRouter(
    prefix="/clients/{client_id}/companies/{company_id}/lead-custom-fields",
    tags=["Lead Custom Fields"]
)


async def verify_api_key(
    api_key: str = Header(..., alias="X-API-Key"),
    client_id: int = None,
    db: Session = Depends(get_db)
):
    """Verifica se a API Key é válida para o client_id."""
    try:
        client = db.query(Client).filter(
            Client.api_key == api_key,
            Client.id == client_id
        ).first()

        if not client:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API Key inválida ou não autorizada"
            )
        return client
    except Exception as e:
        logger.error(f"Erro na verificação da API Key: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao autenticar"
        )


@router.get("/", response_model=List[LeadCustomFieldResponse])
async def get_custom_fields(
    client_id: int,
    company_id: int,
    active_only: bool = True,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Lista todos os campos customizados de uma empresa.

    Args:
        client_id: ID do cliente
        company_id: ID da empresa
        active_only: Se True, retorna apenas campos ativos

    Returns:
        List[LeadCustomFieldResponse]: Lista de campos customizados
    """
    logger.info(f"[get_custom_fields] client_id={client_id}, company_id={company_id}, active_only={active_only}")

    try:
        custom_fields = LeadCustomFieldsService.get_company_custom_fields(
            company_id, active_only, db
        )

        logger.info(f"[get_custom_fields] Retornando {len(custom_fields)} campos")
        return custom_fields

    except Exception as e:
        logger.exception("[get_custom_fields] Erro ao buscar campos customizados")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )


@router.post("/", response_model=LeadCustomFieldResponse, status_code=status.HTTP_201_CREATED)
async def create_custom_field(
    client_id: int,
    company_id: int,
    field_data: LeadCustomFieldCreate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Cria um novo campo customizado para a empresa.

    Args:
        client_id: ID do cliente
        company_id: ID da empresa
        field_data: Dados do campo a ser criado

    Returns:
        LeadCustomFieldResponse: Campo criado
    """
    logger.info(f"[create_custom_field] client_id={client_id}, company_id={company_id}, field_name={field_data.field_name}")

    try:
        # Gerar field_key único se não fornecido
        if not field_data.field_key:
            field_data.field_key = LeadCustomFieldsService.generate_field_key(
                company_id, field_data.field_name, db
            )
        else:
            # Verificar se a key já existe na empresa
            existing_field = db.query(LeadCustomField).filter(
                LeadCustomField.company_id == company_id,
                LeadCustomField.field_key == field_data.field_key
            ).first()

            if existing_field:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Já existe um campo com a chave '{field_data.field_key}' nesta empresa"
                )

        # Criar novo campo
        new_field = LeadCustomField(
            company_id=company_id,
            field_name=field_data.field_name,
            field_key=field_data.field_key,
            field_type=field_data.field_type,
            is_required=field_data.is_required,
            default_value=field_data.default_value,
            validation_rules=field_data.validation_rules,
            display_order=field_data.display_order,
            is_active=field_data.is_active
        )

        db.add(new_field)
        db.commit()
        db.refresh(new_field)

        logger.info(f"[create_custom_field] Campo criado com sucesso: id={new_field.id}")
        return new_field

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("[create_custom_field] Erro ao criar campo customizado")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )


@router.put("/{field_id}", response_model=LeadCustomFieldResponse)
async def update_custom_field(
    client_id: int,
    company_id: int,
    field_id: int,
    field_data: LeadCustomFieldUpdate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Atualiza um campo customizado existente.

    Args:
        client_id: ID do cliente
        company_id: ID da empresa
        field_id: ID do campo a ser atualizado
        field_data: Dados atualizados do campo

    Returns:
        LeadCustomFieldResponse: Campo atualizado
    """
    logger.info(f"[update_custom_field] client_id={client_id}, company_id={company_id}, field_id={field_id}")

    try:
        # Buscar campo existente
        field = db.query(LeadCustomField).filter(
            LeadCustomField.id == field_id,
            LeadCustomField.company_id == company_id
        ).first()

        if not field:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campo customizado não encontrado"
            )

        # Atualizar apenas os campos fornecidos
        if field_data.field_name is not None:
            field.field_name = field_data.field_name
        if field_data.field_type is not None:
            field.field_type = field_data.field_type
        if field_data.is_required is not None:
            field.is_required = field_data.is_required
        if field_data.default_value is not None:
            field.default_value = field_data.default_value
        if field_data.validation_rules is not None:
            field.validation_rules = field_data.validation_rules
        if field_data.display_order is not None:
            field.display_order = field_data.display_order
        if field_data.is_active is not None:
            field.is_active = field_data.is_active

        db.commit()
        db.refresh(field)

        logger.info(f"[update_custom_field] Campo atualizado com sucesso: id={field.id}")
        return field

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("[update_custom_field] Erro ao atualizar campo customizado")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )


@router.delete("/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_field(
    client_id: int,
    company_id: int,
    field_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Remove um campo customizado (soft delete - desativa).

    Args:
        client_id: ID do cliente
        company_id: ID da empresa
        field_id: ID do campo a ser removido
    """
    logger.info(f"[delete_custom_field] client_id={client_id}, company_id={company_id}, field_id={field_id}")

    try:
        # Buscar campo existente
        field = db.query(LeadCustomField).filter(
            LeadCustomField.id == field_id,
            LeadCustomField.company_id == company_id
        ).first()

        if not field:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campo customizado não encontrado"
            )

        # Soft delete - desativar campo
        field.is_active = False
        db.commit()

        logger.info(f"[delete_custom_field] Campo desativado com sucesso: id={field_id}")

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("[delete_custom_field] Erro ao desativar campo customizado")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )


@router.put("/reorder", status_code=status.HTTP_200_OK)
async def reorder_custom_fields(
    client_id: int,
    company_id: int,
    field_orders: List[FieldOrderRequest],
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Reordena os campos customizados de uma empresa.

    Args:
        client_id: ID do cliente
        company_id: ID da empresa
        field_orders: Lista com field_id e nova display_order

    Returns:
        Dict: Mensagem de sucesso
    """
    logger.info(f"[reorder_custom_fields] client_id={client_id}, company_id={company_id}, fields_count={len(field_orders)}")

    try:
        success = LeadCustomFieldsService.reorder_custom_fields(
            company_id, [field.dict() for field in field_orders], db
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Erro ao reordenar campos"
            )

        logger.info(f"[reorder_custom_fields] Campos reordenados com sucesso")
        return {"message": "Campos reordenados com sucesso"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("[reorder_custom_fields] Erro ao reordenar campos")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )


@router.post("/validate", status_code=status.HTTP_200_OK)
async def validate_custom_fields(
    client_id: int,
    company_id: int,
    validation_request: LeadCustomFieldsValidationRequest,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Valida valores de campos customizados sem criar o lead.

    Args:
        client_id: ID do cliente
        company_id: ID da empresa
        validation_request: Valores a serem validados (field_key -> value)

    Returns:
        Dict: Resultado da validação com detalhes
    """
    logger.info(f"[validate_custom_fields] client_id={client_id}, company_id={company_id}")

    try:
        result = LeadsWithCustomFieldsService.validate_lead_custom_fields(
            company_id, validation_request.values, db
        )

        logger.info(f"[validate_custom_fields] Validação concluída: is_valid={result['is_valid']}")
        return result

    except Exception as e:
        logger.exception("[validate_custom_fields] Erro na validação de campos")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )
