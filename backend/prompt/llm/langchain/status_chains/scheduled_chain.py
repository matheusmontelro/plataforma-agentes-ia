"""
Scheduled Customer Chain - For Customers with Active Appointments
==============================================================

Specialized chain for customers with SCHEDULED or NO_SHOW status.
Handles: reagendamento, cancelamento, confirmação, dúvidas sobre consulta.
Restrictions: Cannot schedule new appointments (customer already has one).
"""

import logging
from typing import Dict, Any, List
from datetime import datetime

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from .base_chain import BaseCustomerChain
from ..customer_routing.models import (
    CustomerStatusResult,
    ActionType,
    CustomerStatus
)

logger = logging.getLogger(__name__)


class ScheduledCustomerChain(BaseCustomerChain):
    """
    Chain for customers with scheduled appointments or no-shows.

    Capabilities:
    - Reschedule existing appointments
    - Cancel appointments
    - Confirm appointment details
    - Answer questions about appointments
    - Provide preparation instructions

    Restrictions:
    - Cannot schedule new appointments
    - Focus on existing appointment management
    """

    def _create_prompt_template(self) -> ChatPromptTemplate:
        """Create prompt template for scheduled customers"""

        return ChatPromptTemplate.from_messages([
            ("system", """Você é {assistant_name}, assistente especializada em gestão de consultas da {company_name}.

CONTEXTO DO CLIENTE:
Status: {customer_status_description}
Última consulta: {last_appointment}
Especialidades da empresa: {company_specialties}

AÇÕES PERMITIDAS PARA ESTE CLIENTE:
{allowed_actions_list}

AÇÕES ESTRITAMENTE PROIBIDAS:
{restrictions_list}

DIRETRIZES ESPECÍFICAS:

1. REAGENDAMENTO:
   - Seja proativa em oferecer reagendamento se o cliente demonstrar necessidade
   - Explique o processo: "Posso verificar novos horários disponíveis para você"
   - Use frases como: "Vamos encontrar um horário que funcione melhor"
   - {reagendamento_context}

2. CANCELAMENTO:
   - Seja empática: "Entendo que imprevistos acontecem"
   - Confirme antes de processar: "Você gostaria de cancelar sua consulta em [data/hora]?"
   - Ofereça reagendamento como alternativa antes de cancelar definitivamente
   - {cancelamento_context}

3. CONFIRMAÇÃO DE CONSULTA:
   - Forneça detalhes completos: data, hora, profissional, endereço
   - Inclua instruções de preparação se relevante
   - Confirme dados de contato
   - {confirmacao_context}

4. DÚVIDAS SOBRE CONSULTA:
   - Esclareça localização, estacionamento, documentos necessários
   - Explique procedimentos que serão realizados
   - Informe sobre tempo estimado da consulta
   - {duvidas_context}

ABORDAGEM:
- Seja empática e compreensiva com mudanças de agenda
- Priorize resolver a situação da consulta existente
- Mantenha tom profissional mas acolhedor
- Sempre confirme detalhes importantes
- Se não puder resolver algo, encaminhe para recepção

IMPORTANTE: Este cliente JÁ possui consulta marcada. NÃO ofereça agendamento de nova consulta.

Horário atual: {current_datetime}"""),

            MessagesPlaceholder(variable_name="conversation_history"),

            ("human", "{user_input}")
        ])

    def _get_allowed_actions(self) -> List[ActionType]:
        """Get actions allowed for scheduled customers"""
        return [
            ActionType.RESCHEDULE,
            ActionType.CANCEL,
            ActionType.CONFIRM,
            ActionType.CLARIFY
        ]

    def _get_status_specific_context(self, customer_status: CustomerStatusResult) -> Dict[str, Any]:
        """Get context specific to scheduled customers"""

        # Different contexts based on specific status
        if customer_status.status == CustomerStatus.NO_SHOW:
            status_message = "cliente que faltou à consulta anterior"
            reagendamento_context = "Ofereça reagendamento com prioridade, demonstrando que entendemos que imprevistos acontecem"
            cancelamento_context = "Se o cliente quiser cancelar definitivamente, seja empática e deixe a porta aberta para futuro contato"
        else:  # SCHEDULED
            status_message = "cliente com consulta agendada"
            reagendamento_context = "Verifique motivo do reagendamento e ofereça alternativas próximas à data original"
            cancelamento_context = "Tente entender o motivo e ofereça reagendamento antes de cancelar"

        # Get appointment details if available
        appointment_details = ""
        if hasattr(self, 'scheduling_service') and self.scheduling_service:
            try:
                # Could add method to get appointment details by phone
                appointment_details = "Consulte os detalhes específicos do agendamento"
            except Exception as e:
                logger.warning(f"[ScheduledChain] Could not get appointment details: {e}")

        return {
            "status_message": status_message,
            "reagendamento_context": reagendamento_context,
            "cancelamento_context": cancelamento_context,
            "confirmacao_context": "Forneça todos os detalhes da consulta agendada e confirme se o cliente tem alguma dúvida",
            "duvidas_context": "Esclareça qualquer aspecto relacionado à consulta agendada",
            "appointment_details": appointment_details,

            # Additional context for no-show vs scheduled
            "is_no_show": customer_status.status == CustomerStatus.NO_SHOW,
            "show_empathy": customer_status.status == CustomerStatus.NO_SHOW,

            # Timing context
            "days_until_appointment": self._calculate_days_until_appointment(customer_status),
            "is_urgent": self._is_appointment_urgent(customer_status)
        }

    def _calculate_days_until_appointment(self, customer_status: CustomerStatusResult) -> int:
        """Calculate days until appointment"""
        if not customer_status.last_appointment:
            return 0

        if customer_status.status == CustomerStatus.NO_SHOW:
            return 0  # Past appointment

        # For scheduled appointments
        days = (customer_status.last_appointment - datetime.now()).days
        return max(0, days)

    def _is_appointment_urgent(self, customer_status: CustomerStatusResult) -> bool:
        """Check if appointment is within 24 hours"""
        if not customer_status.last_appointment or customer_status.status == CustomerStatus.NO_SHOW:
            return False

        hours_until = (customer_status.last_appointment - datetime.now()).total_seconds() / 3600
        return 0 < hours_until < 24

    def _filter_restricted_content(self, response: str, allowed_actions) -> str:
        """Enhanced filtering for scheduled customers"""
        response = super()._filter_restricted_content(response, allowed_actions)

        # Specific filters for scheduled customers
        scheduling_phrases = [
            "agendar nova consulta",
            "marcar outra consulta",
            "primeira consulta",
            "quando você gostaria de agendar"
        ]

        for phrase in scheduling_phrases:
            if phrase in response.lower():
                response += "\n\n⚠️ Observação: Você já possui uma consulta em nosso sistema. Para novos agendamentos após resolver sua consulta atual, entre em contato conosco."
                break

        return response

    def get_reschedule_options(self) -> List[str]:
        """Get available rescheduling options"""
        if not self.scheduling_service:
            return ["Entre em contato com nossa recepção para verificar disponibilidade"]

        try:
            # Get next available slots
            slots = self.scheduling_service.get_next_available_slots()
            # Return first 5 options formatted for user
            return [f"{slot}" for slot in slots[:5]]
        except Exception as e:
            logger.error(f"[ScheduledChain] Error getting reschedule options: {e}")
            return ["Entre em contato com nossa recepção para verificar disponibilidade"]

    def format_appointment_confirmation(self, customer_status: CustomerStatusResult) -> str:
        """Format appointment confirmation details"""
        if not customer_status.last_appointment:
            return "Consulte nossa recepção para detalhes da consulta"

        date_str = customer_status.last_appointment.strftime("%d/%m/%Y")
        time_str = customer_status.last_appointment.strftime("%H:%M")

        return f"""
Detalhes da sua consulta:
📅 Data: {date_str}
🕒 Horário: {time_str}
📍 Local: {self.agent_config.get('company_info', {}).get('address', 'Consulte endereço na confirmação')}
👩‍⚕️ Profissional: {self.agent_config.get('company_info', {}).get('dentist_name', 'Será informado')}

Orientações:
• Chegue 15 minutos antes do horário
• Traga documento de identidade
• Em caso de imprevisto, entre em contato conosco

Precisa de alguma informação adicional?
""".strip()

    def handle_no_show_empathy(self) -> str:
        """Generate empathetic response for no-show customers"""
        return """
Entendo que imprevistos podem acontecer e que às vezes não conseguimos comparecer aos compromissos.
Não se preocupe, estamos aqui para ajudar você a remarcar sua consulta quando for conveniente.

Gostaria de reagendar para uma nova data? Posso verificar nossa disponibilidade para você.
""".strip()