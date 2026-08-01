"""
Customer Conversion Service - Handles lead to customer conversion operations
Integrates with existing APIs and database operations
"""

import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.models import Contact, Lead, Customer
from backend.prompt.db_integration.agent_config import get_agent_config_dict

logger = logging.getLogger(__name__)

class CustomerConversionService:
    """Service for converting leads to customers with proper cleanup"""

    def __init__(self, db: Session):
        self.db = db

    def get_redirect_configuration(self, company_id: int) -> Dict[str, Dict[str, Any]]:
        """
        Get redirect configurations from agent_configurations table

        Args:
            company_id: ID of the company

        Returns:
            Dict with redirect configurations by type
        """
        try:
            # Get agent configuration using existing utility
            agent_config = get_agent_config_dict(self.db, company_id)

            conversation_flow = agent_config.get('conversation_flow', {})

            # Extract redirect configurations
            redirects = {
                'financial': conversation_flow.get('financial_redirect', {}),
                'maintenance': conversation_flow.get('maintenance_redirect', {}),
                'general': conversation_flow.get('regular_redirect', {}),
                'active_customers': conversation_flow.get('active_customers_redirect', {})
            }

            logger.info(f"[REDIRECT_CONFIG] Loaded configurations for company {company_id}")
            return redirects

        except Exception as e:
            logger.error(f"[REDIRECT_CONFIG] Error loading for company {company_id}: {e}")

            # Return default configurations
            return {
                'financial': {'type': 'whatsapp', 'number': '5500000000017'},
                'maintenance': {'type': 'fixo', 'number': '00000000000'},
                'general': {'type': 'whatsapp', 'number': '5500000000018'},
                'active_customers': {'type': 'whatsapp', 'number': '5500000000018'}
            }

    def format_redirect_contact(self, redirect_config: Dict[str, Any]) -> str:
        """
        Format redirect configuration to user-friendly contact string

        Args:
            redirect_config: Configuration with type and number

        Returns:
            Formatted contact string
        """
        if not redirect_config or not isinstance(redirect_config, dict):
            return 'Atendimento disponível'

        redirect_type = redirect_config.get('type', '')
        number = redirect_config.get('number', '')

        if not number:
            return 'Atendimento disponível'

        if redirect_type == 'whatsapp':
            # Format WhatsApp number nicely
            if number.startswith('55'):
                formatted = f"({number[2:4]}) {number[4:9]}-{number[9:]}"
                return f"WhatsApp: {formatted}"
            else:
                return f"WhatsApp: {number}"
        elif redirect_type == 'fixo':
            # Format landline number
            if len(number) >= 10:
                if number.startswith('55'):
                    formatted = f"({number[2:4]}) {number[4:8]}-{number[8:]}"
                else:
                    formatted = f"({number[:2]}) {number[2:6]}-{number[6:]}"
                return f"Telefone: {formatted}"
            else:
                return f"Telefone: {number}"
        else:
            return number

    def convert_lead_to_customer_safely(
        self,
        phone: str,
        company_id: int,
        user_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Safely convert lead to customer with proper error handling

        Args:
            phone: Customer phone number
            company_id: Company ID
            user_name: Optional user name from conversation

        Returns:
            Dict with conversion results
        """
        try:
            # 1. Find contact
            contact = self.db.query(Contact).filter(
                Contact.phone == phone,
                Contact.company_id == company_id
            ).first()

            if not contact:
                logger.error(f"[CONVERT] Contact not found: {phone} @ company {company_id}")
                return {
                    'success': False,
                    'error': 'contact_not_found',
                    'message': 'Contato não encontrado no sistema'
                }

            # 2. Check if already a customer
            existing_customer = self.db.query(Customer).filter(
                Customer.contact_id == contact.id
            ).first()

            if existing_customer:
                logger.info(f"[CONVERT] Already a customer: {phone}")
                return {
                    'success': True,
                    'contact_converted': False,
                    'already_customer': True,
                    'customer_id': existing_customer.id
                }

            # 3. Create customer record
            customer_name = user_name or contact.name or "Nome não informado"

            new_customer = Customer(
                contact_id=contact.id,
                company_id=company_id,
                nome=customer_name,
                telefone=phone,
                categoria='cliente',
                status='ativo'
            )

            # 4. Find and link to lead if exists
            lead = self.db.query(Lead).filter(
                Lead.phone == phone,
                Lead.company_id == company_id
            ).first()

            if lead:
                new_customer.convertido_de_lead_id = lead.id

            self.db.add(new_customer)
            self.db.flush()

            logger.info(f"[CONVERT] ✅ Customer created: ID {new_customer.id} from contact {contact.id}")

            return {
                'success': True,
                'contact_converted': True,
                'already_customer': False,
                'customer_id': new_customer.id,
                'linked_to_lead': bool(lead)
            }

        except Exception as e:
            logger.error(f"[CONVERT] Error creating customer: {e}")
            self.db.rollback()

            return {
                'success': False,
                'error': 'conversion_failed',
                'message': f'Erro ao converter para cliente: {str(e)}'
            }

    def delete_lead_safely(self, phone: str, company_id: int) -> Dict[str, Any]:
        """
        Safely delete lead and related data with proper cleanup

        Args:
            phone: Lead phone number
            company_id: Company ID

        Returns:
            Dict with deletion results
        """
        try:
            # Find lead
            lead = self.db.query(Lead).filter(
                Lead.phone == phone,
                Lead.company_id == company_id
            ).first()

            if not lead:
                logger.info(f"[DELETE_LEAD] No lead found for {phone}")
                return {
                    'success': True,
                    'lead_deleted': False,
                    'message': 'Nenhum lead encontrado para exclusão'
                }

            # Delete related data following existing pattern
            try:
                # 1. Delete agendamentos (if any)
                agendamentos_result = self.db.execute(text("""
                    DELETE FROM agendamentos
                    WHERE lead_id = :lead_id
                """), {"lead_id": lead.id})

                agendamentos_deleted = agendamentos_result.rowcount

                # 2. Delete the lead itself
                self.db.delete(lead)

                logger.info(f"[DELETE_LEAD] ✅ Deleted lead {lead.id}, {agendamentos_deleted} agendamentos")

                return {
                    'success': True,
                    'lead_deleted': True,
                    'lead_id': lead.id,
                    'agendamentos_deleted': agendamentos_deleted
                }

            except Exception as e:
                logger.error(f"[DELETE_LEAD] Error in deletion process: {e}")
                raise e

        except Exception as e:
            logger.error(f"[DELETE_LEAD] Failed to delete lead: {e}")
            self.db.rollback()

            return {
                'success': False,
                'error': 'deletion_failed',
                'message': f'Erro ao excluir lead: {str(e)}'
            }

    def complete_lead_to_customer_conversion(
        self,
        phone: str,
        company_id: int,
        redirect_type: str = 'general',
        user_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Complete lead to customer conversion process

        Args:
            phone: Customer phone
            company_id: Company ID
            redirect_type: Type of redirect needed
            user_name: Optional user name

        Returns:
            Complete conversion result
        """
        try:
            # 1. Convert to customer
            conversion_result = self.convert_lead_to_customer_safely(phone, company_id, user_name)

            if not conversion_result['success']:
                return conversion_result

            # 2. Delete lead (if conversion was successful)
            deletion_result = self.delete_lead_safely(phone, company_id)

            # 3. Get redirect configuration
            redirects = self.get_redirect_configuration(company_id)
            redirect_config = redirects.get(redirect_type, redirects['general'])
            redirect_contact = self.format_redirect_contact(redirect_config)

            # 4. Commit all changes
            self.db.commit()

            # 5. Return complete result
            return {
                'success': True,
                'conversion': conversion_result,
                'deletion': deletion_result,
                'redirect': {
                    'type': redirect_type,
                    'config': redirect_config,
                    'contact': redirect_contact
                }
            }

        except Exception as e:
            logger.error(f"[FULL_CONVERSION] Complete process failed: {e}")
            self.db.rollback()

            return {
                'success': False,
                'error': 'complete_process_failed',
                'message': f'Erro no processo completo: {str(e)}'
            }