"""
Serviços para gestão de campos customizados de leads.

Este módulo contém a lógica de negócio para:
- Validação de campos customizados
- Geração de chaves únicas
- Validação de valores conforme regras
- Integração com models SQLAlchemy
"""

import re
import logging
from datetime import datetime, date
from typing import Dict, Any, List, Tuple, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_

from backend.models import LeadCustomField, LeadCustomValue, Lead
from pydantic import BaseModel


# Schema local para evitar import circular
class LeadCustomFieldCreate(BaseModel):
    field_name: str
    field_key: str
    field_type: str
    is_required: bool = False
    default_value: Any = None
    validation_rules: Dict[str, Any] = None
    display_order: int = 0
    is_active: bool = True


class LeadCustomValueCreate(BaseModel):
    custom_field_id: int
    value: Any


class LeadCustomFieldsValidationRequest(BaseModel):
    values: Dict[str, Any]  # field_key -> value

logger = logging.getLogger("saas_business.lead_custom_fields_service")


class LeadCustomFieldsService:
    """Serviço para gerenciamento de campos customizados de leads."""

    @staticmethod
    def generate_field_key(company_id: int, field_name: str, db: Session) -> str:
        """
        Gera uma chave única (field_key) a partir do nome do campo.
        Remove caracteres especiais, espaços e garante unicidade por empresa.
        """
        # Converter para minúsculas e remover caracteres especiais
        base_key = re.sub(r'[^a-zA-Z0-9_]', '_', field_name.lower())
        # Substituir múltiplos underscores por um único
        base_key = re.sub(r'_+', '_', base_key)
        # Remover underscores do início e fim
        base_key = base_key.strip('_')

        # Garantir que comece com letra
        if base_key and base_key[0].isdigit():
            base_key = f"field_{base_key}"

        if not base_key:
            base_key = "field"

        # Verificar unicidade na empresa
        original_key = base_key
        counter = 1

        while db.query(LeadCustomField).filter(
            and_(
                LeadCustomField.company_id == company_id,
                LeadCustomField.field_key == base_key
            )
        ).first():
            base_key = f"{original_key}_{counter}"
            counter += 1

        return base_key

    @staticmethod
    def validate_field_value(field: LeadCustomField, value: Any) -> Tuple[bool, str]:
        """
        Valida um valor conforme o tipo e regras do campo customizado.

        Returns:
            Tuple[bool, str]: (is_valid, error_message)
        """
        if value is None or value == "":
            if field.is_required:
                return False, f"O campo '{field.field_name}' é obrigatório"
            return True, ""

        # Validar conforme o tipo
        field_type = field.field_type.lower()

        try:
            if field_type == 'text':
                if not isinstance(value, str):
                    return False, f"O campo '{field.field_name}' deve ser um texto"

                # Aplicar regras de validação específicas
                if field.validation_rules:
                    rules = field.validation_rules
                    if 'min_length' in rules and len(value) < rules['min_length']:
                        return False, f"O campo '{field.field_name}' deve ter no mínimo {rules['min_length']} caracteres"
                    if 'max_length' in rules and len(value) > rules['max_length']:
                        return False, f"O campo '{field.field_name}' deve ter no máximo {rules['max_length']} caracteres"
                    if 'pattern' in rules:
                        pattern = rules['pattern']
                        if not re.match(pattern, value):
                            return False, f"O campo '{field.field_name}' possui formato inválido"

            elif field_type == 'number':
                try:
                    num_value = float(str(value).replace(',', '.'))
                except (ValueError, TypeError):
                    return False, f"O campo '{field.field_name}' deve ser um número"

                # Aplicar regras de validação específicas
                if field.validation_rules:
                    rules = field.validation_rules
                    if 'min_value' in rules and num_value < rules['min_value']:
                        return False, f"O campo '{field.field_name}' deve ser maior ou igual a {rules['min_value']}"
                    if 'max_value' in rules and num_value > rules['max_value']:
                        return False, f"O campo '{field.field_name}' deve ser menor ou igual a {rules['max_value']}"

            elif field_type == 'email':
                if not isinstance(value, str):
                    return False, f"O campo '{field.field_name}' deve ser um email válido"

                email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                if not re.match(email_pattern, value):
                    return False, f"O campo '{field.field_name}' deve ser um email válido"

            elif field_type == 'date':
                if isinstance(value, str):
                    # Tentar converter string para data
                    try:
                        # Suportar formatos comuns
                        for date_format in ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y']:
                            try:
                                datetime.strptime(value, date_format)
                                break
                            except ValueError:
                                continue
                        else:
                            return False, f"O campo '{field.field_name}' deve estar em formato de data válido"
                    except ValueError:
                        return False, f"O campo '{field.field_name}' deve estar em formato de data válido"
                elif not isinstance(value, (date, datetime)):
                    return False, f"O campo '{field.field_name}' deve ser uma data válida"

            elif field_type == 'select':
                # Para select, verificar se o valor está nas opções
                if field.default_value and isinstance(field.default_value, list):
                    if value not in field.default_value:
                        return False, f"O campo '{field.field_name}' deve ter um dos valores permitidos: {', '.join(map(str, field.default_value))}"

            elif field_type == 'textarea':
                if not isinstance(value, str):
                    return False, f"O campo '{field.field_name}' deve ser um texto"

                # Aplicar regras de validação específicas
                if field.validation_rules:
                    rules = field.validation_rules
                    if 'min_length' in rules and len(value) < rules['min_length']:
                        return False, f"O campo '{field.field_name}' deve ter no mínimo {rules['min_length']} caracteres"
                    if 'max_length' in rules and len(value) > rules['max_length']:
                        return False, f"O campo '{field.field_name}' deve ter no máximo {rules['max_length']} caracteres"

        except Exception as e:
            logger.error(f"Erro ao validar campo '{field.field_name}': {str(e)}")
            return False, f"Erro ao validar o campo '{field.field_name}'"

        return True, ""

    @staticmethod
    def validate_required_fields(company_id: int, values: Dict[str, Any], db: Session) -> Tuple[bool, List[str]]:
        """
        Valida se todos os campos obrigatórios estão presentes e válidos.

        Args:
            company_id: ID da empresa
            values: Dicionário com field_key -> value
            db: Sessão do banco

        Returns:
            Tuple[bool, List[str]]: (is_valid, error_messages)
        """
        try:
            # Buscar campos obrigatórios da empresa
            required_fields = db.query(LeadCustomField).filter(
                and_(
                    LeadCustomField.company_id == company_id,
                    LeadCustomField.is_required == True,
                    LeadCustomField.is_active == True
                )
            ).all()

            errors = []

            for field in required_fields:
                field_value = values.get(field.field_key)

                # Validar se o campo está presente
                if field_value is None or field_value == "":
                    errors.append(f"O campo '{field.field_name}' é obrigatório")
                    continue

                # Validar o valor do campo
                is_valid, error_msg = LeadCustomFieldsService.validate_field_value(field, field_value)
                if not is_valid:
                    errors.append(error_msg)

            # Validar campos fornecidos que não são obrigatórios
            for field_key, field_value in values.items():
                if field_value is None or field_value == "":
                    continue  # Pular valores vazios para campos opcionais

                field = db.query(LeadCustomField).filter(
                    and_(
                        LeadCustomField.company_id == company_id,
                        LeadCustomField.field_key == field_key,
                        LeadCustomField.is_active == True
                    )
                ).first()

                if field:
                    is_valid, error_msg = LeadCustomFieldsService.validate_field_value(field, field_value)
                    if not is_valid:
                        errors.append(error_msg)

            return len(errors) == 0, errors

        except Exception as e:
            logger.error(f"Erro ao validar campos obrigatórios: {str(e)}")
            return False, [f"Erro ao validar campos: {str(e)}"]

    @staticmethod
    def create_lead_custom_values(lead_id: int, custom_values: List[LeadCustomValueCreate], db: Session) -> List[LeadCustomValue]:
        """
        Cria valores customizados para um lead.

        Args:
            lead_id: ID do lead
            custom_values: Lista de valores a serem criados
            db: Sessão do banco

        Returns:
            List[LeadCustomValue]: Lista de valores criados
        """
        created_values = []

        try:
            for custom_value_data in custom_values:
                # Verificar se o campo customizado existe
                field = db.query(LeadCustomField).filter(
                    LeadCustomField.id == custom_value_data.custom_field_id
                ).first()

                if not field:
                    logger.warning(f"Campo customizado {custom_value_data.custom_field_id} não encontrado")
                    continue

                # Validar o valor
                is_valid, error_msg = LeadCustomFieldsService.validate_field_value(
                    field, custom_value_data.value
                )

                if not is_valid:
                    logger.warning(f"Valor inválido para campo {field.field_name}: {error_msg}")
                    continue

                # Verificar se já existe um valor para este campo neste lead
                existing_value = db.query(LeadCustomValue).filter(
                    and_(
                        LeadCustomValue.lead_id == lead_id,
                        LeadCustomValue.custom_field_id == custom_value_data.custom_field_id
                    )
                ).first()

                if existing_value:
                    # Atualizar valor existente
                    existing_value.value = custom_value_data.value
                    created_values.append(existing_value)
                else:
                    # Criar novo valor
                    new_value = LeadCustomValue(
                        lead_id=lead_id,
                        custom_field_id=custom_value_data.custom_field_id,
                        value=custom_value_data.value
                    )
                    db.add(new_value)
                    created_values.append(new_value)

            db.commit()

            # Carregar relacionamentos para retorno
            for value in created_values:
                db.refresh(value)

            return created_values

        except Exception as e:
            db.rollback()
            logger.error(f"Erro ao criar valores customizados: {str(e)}")
            raise e

    @staticmethod
    def get_lead_custom_values(lead_id: int, db: Session) -> List[LeadCustomValue]:
        """
        Busca todos os valores customizados de um lead com informações dos campos.
        """
        try:
            return db.query(LeadCustomValue).filter(
                LeadCustomValue.lead_id == lead_id
            ).all()
        except Exception as e:
            logger.error(f"Erro ao buscar valores customizados do lead {lead_id}: {str(e)}")
            return []

    @staticmethod
    def get_company_custom_fields(company_id: int, active_only: bool = True, db: Session = None) -> List[LeadCustomField]:
        """
        Busca campos customizados de uma empresa.

        Args:
            company_id: ID da empresa
            active_only: Se True, retorna apenas campos ativos
            db: Sessão do banco

        Returns:
            List[LeadCustomField]: Lista de campos customizados ordenados por display_order
        """
        try:
            query = db.query(LeadCustomField).filter(
                LeadCustomField.company_id == company_id
            )

            if active_only:
                query = query.filter(LeadCustomField.is_active == True)

            return query.order_by(LeadCustomField.display_order).all()

        except Exception as e:
            logger.error(f"Erro ao buscar campos customizados da empresa {company_id}: {str(e)}")
            return []

    @staticmethod
    def reorder_custom_fields(company_id: int, field_orders: List[Dict[str, int]], db: Session) -> bool:
        """
        Reordena os campos customizados de uma empresa.

        Args:
            company_id: ID da empresa
            field_orders: Lista de dicionários com field_id e display_order
            db: Sessão do banco

        Returns:
            bool: True se successful, False caso contrário
        """
        try:
            for field_order in field_orders:
                field_id = field_order.get('field_id')
                display_order = field_order.get('display_order')

                if field_id is None or display_order is None:
                    continue

                # Verificar se o campo pertence à empresa
                field = db.query(LeadCustomField).filter(
                    and_(
                        LeadCustomField.id == field_id,
                        LeadCustomField.company_id == company_id
                    )
                ).first()

                if field:
                    field.display_order = display_order

            db.commit()
            return True

        except Exception as e:
            db.rollback()
            logger.error(f"Erro ao reordenar campos customizados: {str(e)}")
            return False