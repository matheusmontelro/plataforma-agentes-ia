"""
Appointment Service - Wrapper for existing agendamento_logic.py

This service provides a clean, modular interface to the existing appointment
confirmation logic while maintaining 100% compatibility with the current system.
"""

import logging
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
from typing import Optional

logger = logging.getLogger(__name__)


class AppointmentService:
    """
    Service wrapper that encapsulates agendamento_logic.py functionality
    in a modern, type-safe interface compatible with OpenAI Agents SDK.
    """

    def __init__(self, db: Session):
        self.db = db

    def process_confirmation(
        self,
        company_id: int,
        phone: str,
        customer_name: str,
        appointment_date: str,
        appointment_time: str,
        treatment_type: str = "Consulta de Avaliação",
        customer_type: str = "novo",
        agenda_id: Optional[int] = None
    ) -> str:
        """
        Processes complete appointment confirmation by wrapping existing logic.

        This method maintains 100% compatibility with the current system while
        providing a clean interface for the new modular architecture.

        Args:
            company_id: Company ID for the appointment
            phone: Customer phone number
            customer_name: Full customer name
            appointment_date: Date in DD/MM/YYYY format
            appointment_time: Time in HH:MM format
            treatment_type: Type of treatment extracted from conversation
            customer_type: "novo" or "retorno" based on customer history
            agenda_id: Optional ID of specific agenda to schedule in

        Returns:
            Formatted confirmation message ready to send to customer

        Raises:
            Exception: If appointment processing fails
        """

        logger.info(f"[AppointmentService] Processing confirmation for {phone} at company {company_id}")
        logger.debug(f"[AppointmentService] Treatment: {treatment_type}, Customer type: {customer_type}, Agenda: {agenda_id}")

        try:
            # Prepare data in the format expected by existing system
            llm_json = {
                "company_id": company_id,
                "phone": phone,
                "nome": customer_name,
                "data": appointment_date,
                "horario": appointment_time,
                "agendamento_confirmado": True,
                "cancelar_agendamento": False,
                "tratamento": treatment_type,  # From LLM analysis
                "cliente": customer_type,      # From LLM analysis
                "agenda_id": agenda_id         # New field
            }

            # Get API key for the company
            api_key = self._get_api_key(company_id)

            # Log the data being processed
            logger.debug(f"[AppointmentService] Confirmation data: {llm_json}")

            # Call existing system - 100% reuse of tested logic
            from backend.prompt.db_integration.agendamento_logic import processar_json_do_llm

            result = processar_json_do_llm(
                db=self.db,
                company_id=company_id,
                phone=phone,
                llm_json=llm_json,
                api_key=api_key
            )

            if result:
                logger.info(f"[AppointmentService] Confirmation processed successfully for {phone}")
                return result
            else:
                logger.warning(f"[AppointmentService] Empty result from processar_json_do_llm for {phone}")
                return self._get_fallback_message(customer_name, appointment_date, appointment_time)

        except Exception as e:
            logger.error(f"[AppointmentService] Error processing confirmation for {phone}: {e}")
            # Re-raise to let the tool handle the error appropriately
            raise

    def _get_api_key(self, company_id: int) -> Optional[str]:
        """
        Retrieves API key for the company from the database.

        Args:
            company_id: ID of the company

        Returns:
            API key string or None if not found
        """
        try:
            row = self.db.execute(text("""
                SELECT c.api_key
                FROM clients c
                JOIN client_companies cc ON cc.client_id = c.id
                WHERE cc.company_id = :cid
                LIMIT 1
            """), {"cid": company_id}).fetchone()

            if row and row.api_key:
                logger.debug(f"[AppointmentService] API key found for company {company_id}")
                return row.api_key
            else:
                logger.warning(f"[AppointmentService] No API key found for company {company_id}")
                return None

        except Exception as e:
            logger.error(f"[AppointmentService] Error fetching API key for company {company_id}: {e}")
            return None

    def _get_fallback_message(self, customer_name: str, appointment_date: str, appointment_time: str) -> str:
        """
        Generates a fallback confirmation message if the main system fails.

        Args:
            customer_name: Customer's full name
            appointment_date: Appointment date
            appointment_time: Appointment time

        Returns:
            Basic confirmation message
        """
        return f"""
Olá {customer_name}!

Seu agendamento foi confirmado:
📅 Data: {appointment_date}
🕐 Horário: {appointment_time}

Nossa equipe entrará em contato com mais detalhes em breve.

Obrigado por escolher nossos serviços!
""".strip()