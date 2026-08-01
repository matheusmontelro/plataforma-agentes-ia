"""
Serviço para integração de leads com campos customizados.

Este módulo contém a lógica de negócio para:
- Criar leads com campos customizados
- Atualizar leads com campos customizados
- Buscar leads com campos customizados
- Processar valores customizados em operações de lead
"""

import logging
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime
from pydantic import BaseModel

from backend.models import Contact, Lead, LeadCustomField, LeadCustomValue
from backend.services.lead_custom_fields_service import LeadCustomFieldsService


# Schemas locais para evitar import circular
class LeadCustomValueCreate(BaseModel):
    custom_field_id: int
    value: Any

class LeadCustomValueResponse(BaseModel):
    id: int
    custom_field_id: int
    value: Any
    field_name: str
    field_key: str
    field_type: str
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class LeadCreateWithCustom(BaseModel):
    client_id: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    created_at: Optional[str] = None
    data_entrada: Optional[datetime] = None
    source_id: Optional[str] = None
    thumbnail_url: Optional[str] = None
    sender_lid: Optional[str] = None
    follow_up_sequence_id: Optional[int] = None
    custom_values: Optional[List[LeadCustomValueCreate]] = []

class LeadUpdateWithCustom(BaseModel):
    client_id: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    created_at: Optional[str] = None
    data_entrada: Optional[datetime] = None
    source_id: Optional[str] = None
    thumbnail_url: Optional[str] = None
    sender_lid: Optional[str] = None
    follow_up_sequence_id: Optional[int] = None
    custom_values: Optional[List[LeadCustomValueCreate]] = []

class LeadWithCustomFieldsResponse(BaseModel):
    id: int
    client_id: Optional[int] = None
    company_id: Optional[int] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    created_at: Optional[datetime] = None
    data_entrada: Optional[datetime] = None
    source_id: Optional[str] = None
    thumbnail_url: Optional[str] = None
    sender_lid: Optional[str] = None
    follow_up_sequence_id: Optional[int] = None
    current_stage_id: Optional[int] = None
    pipeline_id: Optional[int] = None
    pipeline_entered_at: Optional[datetime] = None
    last_stage_move_at: Optional[datetime] = None
    custom_values: List[LeadCustomValueResponse] = []

    class Config:
        orm_mode = True

logger = logging.getLogger("saas_business.leads_with_custom_fields_service")


class LeadsWithCustomFieldsService:
    """Serviço para gerenciamento de leads com campos customizados."""

    @staticmethod
    def create_lead_with_custom_fields(
        lead_data: LeadCreateWithCustom,
        client_id: int,
        company_id: int,
        db: Session
    ) -> LeadWithCustomFieldsResponse:
        """
        Cria um novo lead com campos customizados.

        Args:
            lead_data: Dados do lead com campos customizados
            client_id: ID do client
            company_id: ID da empresa
            db: Sessão do banco

        Returns:
            LeadWithCustomFieldsResponse: Lead criado com campos customizados
        """
        try:
            # Validar campos customizados se fornecidos
            if lead_data.custom_values:
                # Montar dicionário de valores para validação
                custom_values_dict = {}
                for custom_value in lead_data.custom_values:
                    field = db.query(LeadCustomField).filter(
                        LeadCustomField.id == custom_value.custom_field_id
                    ).first()
                    if field:
                        custom_values_dict[field.field_key] = custom_value.value

                # Validar campos obrigatórios e valores
                is_valid, errors = LeadCustomFieldsService.validate_required_fields(
                    company_id, custom_values_dict, db
                )

                if not is_valid:
                    raise ValueError(f"Validação de campos customizados falhou: {'; '.join(errors)}")

            thumbnail_url = lead_data.thumbnail_url
            if not thumbnail_url and lead_data.phone:
                thumbnail_url = LeadsWithCustomFieldsService._get_contact_photo(
                    company_id, lead_data.phone, db
                )

            # Criar lead básico
            new_lead = Lead(
                client_id=str(client_id),
                company_id=company_id,
                name=lead_data.name,
                phone=lead_data.phone,
                source_id=lead_data.source_id,
                thumbnail_url=thumbnail_url,
                sender_lid=lead_data.sender_lid,
                follow_up_sequence_id=lead_data.follow_up_sequence_id
            )

            # Adicionar data_entrada se fornecida
            if lead_data.data_entrada:
                new_lead.data_entrada = lead_data.data_entrada

            db.add(new_lead)
            db.flush()  # Obter ID do lead sem commit

            # Criar valores customizados
            if lead_data.custom_values:
                LeadCustomFieldsService.create_lead_custom_values(
                    new_lead.id, lead_data.custom_values, db
                )

            db.commit()
            db.refresh(new_lead)

            # Carregar valores customizados para resposta
            custom_values = LeadCustomFieldsService.get_lead_custom_values(new_lead.id, db)

            # Construir resposta
            return LeadsWithCustomFieldsService._build_lead_response(new_lead, custom_values)

        except Exception as e:
            db.rollback()
            logger.error(f"Erro ao criar lead com campos customizados: {str(e)}")
            raise e

    @staticmethod
    def update_lead_with_custom_fields(
        lead_id: int,
        lead_data: LeadUpdateWithCustom,
        company_id: int,
        db: Session
    ) -> LeadWithCustomFieldsResponse:
        """
        Atualiza um lead existente com campos customizados.

        Args:
            lead_id: ID do lead
            lead_data: Dados atualizados do lead com campos customizados
            company_id: ID da empresa
            db: Sessão do banco

        Returns:
            LeadWithCustomFieldsResponse: Lead atualizado com campos customizados
        """
        try:
            # Buscar lead existente
            lead = db.query(Lead).filter(
                and_(
                    Lead.id == lead_id,
                    Lead.company_id == company_id
                )
            ).first()

            if not lead:
                raise ValueError("Lead não encontrado")

            # Validar campos customizados se fornecidos
            if lead_data.custom_values:
                # Montar dicionário de valores para validação
                custom_values_dict = {}
                for custom_value in lead_data.custom_values:
                    field = db.query(LeadCustomField).filter(
                        LeadCustomField.id == custom_value.custom_field_id
                    ).first()
                    if field:
                        custom_values_dict[field.field_key] = custom_value.value

                # Validar campos obrigatórios e valores
                is_valid, errors = LeadCustomFieldsService.validate_required_fields(
                    company_id, custom_values_dict, db
                )

                if not is_valid:
                    raise ValueError(f"Validação de campos customizados falhou: {'; '.join(errors)}")

            # Atualizar dados básicos do lead se fornecidos
            if lead_data.name is not None:
                lead.name = lead_data.name
            if lead_data.phone is not None:
                lead.phone = lead_data.phone
            if lead_data.source_id is not None:
                lead.source_id = lead_data.source_id
            if lead_data.thumbnail_url is not None:
                lead.thumbnail_url = lead_data.thumbnail_url
            if lead_data.sender_lid is not None:
                lead.sender_lid = lead_data.sender_lid
            if lead_data.follow_up_sequence_id is not None:
                lead.follow_up_sequence_id = lead_data.follow_up_sequence_id
            if lead_data.data_entrada is not None:
                lead.data_entrada = lead_data.data_entrada

            # Atualizar campos customizados se fornecidos
            if lead_data.custom_values:
                LeadCustomFieldsService.create_lead_custom_values(
                    lead_id, lead_data.custom_values, db
                )

            db.commit()
            db.refresh(lead)

            # Carregar valores customizados para resposta
            custom_values = LeadCustomFieldsService.get_lead_custom_values(lead.id, db)

            # Construir resposta
            return LeadsWithCustomFieldsService._build_lead_response(
                lead,
                custom_values,
                LeadsWithCustomFieldsService._resolve_thumbnail_url(lead, db)
            )

        except Exception as e:
            db.rollback()
            logger.error(f"Erro ao atualizar lead com campos customizados: {str(e)}")
            raise e

    @staticmethod
    def get_lead_with_custom_fields(
        lead_id: int,
        company_id: int,
        db: Session
    ) -> Optional[LeadWithCustomFieldsResponse]:
        """
        Busca um lead com todos os seus campos customizados.

        Args:
            lead_id: ID do lead
            company_id: ID da empresa
            db: Sessão do banco

        Returns:
            Optional[LeadWithCustomFieldsResponse]: Lead com campos customizados ou None
        """
        try:
            # Buscar lead
            lead = db.query(Lead).filter(
                and_(
                    Lead.id == lead_id,
                    Lead.company_id == company_id
                )
            ).first()

            if not lead:
                return None

            # Carregar valores customizados
            custom_values = LeadCustomFieldsService.get_lead_custom_values(lead.id, db)

            # Construir resposta
            return LeadsWithCustomFieldsService._build_lead_response(
                lead,
                custom_values,
                LeadsWithCustomFieldsService._resolve_thumbnail_url(lead, db)
            )

        except Exception as e:
            logger.error(f"Erro ao buscar lead com campos customizados: {str(e)}")
            return None

    @staticmethod
    def list_leads_with_custom_fields(
        client_id: int,
        company_id: int,
        db: Session,
        pipeline_id: Optional[int] = None,
        stage_id: Optional[int] = None
    ) -> List[LeadWithCustomFieldsResponse]:
        """
        Lista leads de uma empresa com campos customizados.

        Args:
            client_id: ID do client
            company_id: ID da empresa
            db: Sessão do banco
            pipeline_id: Filtro opcional por pipeline_id
            stage_id: Filtro opcional por stage_id

        Returns:
            List[LeadWithCustomFieldsResponse]: Lista de leads com campos customizados
        """
        try:
            # Buscar leads
            query = db.query(Lead).filter(
                and_(
                    Lead.company_id == company_id,
                    Lead.client_id == str(client_id)
                )
            )

            # Aplicar filtros
            if pipeline_id:
                query = query.filter(Lead.pipeline_id == pipeline_id)
            if stage_id:
                query = query.filter(Lead.current_stage_id == stage_id)

            leads = query.all()

            # Para cada lead, carregar campos customizados e construir resposta
            leads_with_custom = []
            for lead in leads:
                custom_values = LeadCustomFieldsService.get_lead_custom_values(lead.id, db)
                lead_response = LeadsWithCustomFieldsService._build_lead_response(
                    lead,
                    custom_values,
                    LeadsWithCustomFieldsService._resolve_thumbnail_url(lead, db)
                )
                leads_with_custom.append(lead_response)

            return leads_with_custom

        except Exception as e:
            logger.error(f"Erro ao listar leads com campos customizados: {str(e)}")
            return []

    @staticmethod
    def validate_lead_custom_fields(
        company_id: int,
        validation_request: Dict[str, Any],
        db: Session
    ) -> Dict[str, Any]:
        """
        Valida valores de campos customizados sem criar o lead.

        Args:
            company_id: ID da empresa
            validation_request: Dicionário com field_key -> value
            db: Sessão do banco

        Returns:
            Dict[str, Any]: Resultado da validação com detalhes
        """
        try:
            is_valid, errors = LeadCustomFieldsService.validate_required_fields(
                company_id, validation_request, db
            )

            # Buscar todos os campos da empresa para mostrar informações adicionais
            all_fields = LeadCustomFieldsService.get_company_custom_fields(company_id, True, db)

            field_info = {}
            for field in all_fields:
                field_info[field.field_key] = {
                    'id': field.id,
                    'name': field.field_name,
                    'type': field.field_type,
                    'required': field.is_required,
                    'provided': field.field_key in validation_request,
                    'value': validation_request.get(field.field_key)
                }

            return {
                'is_valid': is_valid,
                'errors': errors,
                'field_info': field_info
            }

        except Exception as e:
            logger.error(f"Erro ao validar campos customizados: {str(e)}")
            return {
                'is_valid': False,
                'errors': [f"Erro na validação: {str(e)}"],
                'field_info': {}
            }

    @staticmethod
    def _build_lead_response(
        lead: Lead,
        custom_values: List[LeadCustomValue],
        thumbnail_url: Optional[str] = None
    ) -> LeadWithCustomFieldsResponse:
        """
        Constrói uma resposta de LeadWithCustomFieldsResponse a partir dos objetos do banco.

        Args:
            lead: Objeto Lead do banco
            custom_values: Lista de LeadCustomValue do banco

        Returns:
            LeadWithCustomFieldsResponse: Resposta formatada
        """
        # Converter valores customizados para o formato de resposta
        custom_value_responses = []
        for custom_value in custom_values:
            response = LeadCustomValueResponse(
                id=custom_value.id,
                custom_field_id=custom_value.custom_field_id,
                value=custom_value.value,
                field_name=custom_value.field_name or "",
                field_key=custom_value.field_key or "",
                field_type=custom_value.field_type or "",
                created_at=custom_value.created_at,
                updated_at=custom_value.updated_at
            )
            custom_value_responses.append(response)

        return LeadWithCustomFieldsResponse(
            id=lead.id,
            client_id=int(lead.client_id) if lead.client_id and lead.client_id.isdigit() else None,
            company_id=lead.company_id,
            name=lead.name,
            phone=lead.phone,
            created_at=lead.created_at,
            data_entrada=lead.data_entrada,
            source_id=lead.source_id,
            thumbnail_url=thumbnail_url if thumbnail_url is not None else lead.thumbnail_url,
            sender_lid=lead.sender_lid,
            follow_up_sequence_id=lead.follow_up_sequence_id,
            current_stage_id=lead.current_stage_id,
            pipeline_id=lead.pipeline_id,
            pipeline_entered_at=lead.pipeline_entered_at,
            last_stage_move_at=lead.last_stage_move_at,
            custom_values=custom_value_responses
        )

    @staticmethod
    def _resolve_thumbnail_url(lead: Lead, db: Session) -> Optional[str]:
        if lead.thumbnail_url:
            return lead.thumbnail_url
        if not lead.phone:
            return None
        return LeadsWithCustomFieldsService._get_contact_photo(lead.company_id, lead.phone, db)

    @staticmethod
    def _get_contact_photo(company_id: int, phone: str, db: Session) -> Optional[str]:
        contact_photo = db.query(Contact.photo).filter(
            Contact.company_id == company_id,
            Contact.phone == phone,
            Contact.photo.isnot(None)
        ).order_by(Contact.id.desc()).first()
        return contact_photo[0] if contact_photo else None
