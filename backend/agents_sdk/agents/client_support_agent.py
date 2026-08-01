"""
Customer Support Agent - Handles existing customer needs and redirections
Converts leads to customers and provides appropriate redirections
"""

import logging
from typing import Dict, Any
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from agents import Agent, function_tool, handoff, RunContextWrapper
import requests

from ..context.contact_context import CustomerContext
from backend.models import Contact, Lead, Customer

# Import OpenAI recommended prompt prefix
try:
    from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
except ImportError:
    RECOMMENDED_PROMPT_PREFIX = "# System context\nYou are part of a multi-agent system. Transfers between agents are handled seamlessly in the background; do not mention or draw attention to these transfers in your conversation with the user.\n"

logger = logging.getLogger(__name__)

class ConversionRequest(BaseModel):
    """Request for lead to customer conversion"""
    redirect_type: str  # 'financial', 'maintenance', 'general'
    user_need: str

class ConversionResult(BaseModel):
    """Result of conversion and redirection"""
    success: bool
    contact_converted: bool
    lead_deleted: bool
    redirect_message: str
    redirect_contact: str
    error_message: str = ""

@function_tool
def convert_lead_to_customer_and_redirect(
    context: RunContextWrapper[CustomerContext],
    request: ConversionRequest
) -> ConversionResult:
    """
    Converts lead to customer and provides appropriate redirection

    Args:
        context: Customer context with company and phone info
        request: Conversion request with redirect type and user need

    Returns:
        ConversionResult with operation status and redirect message
    """
    try:
        company_id = context.context.company_id
        phone = context.context.phone
        db = context.context.db

        logger.info(f"[CUSTOMER_CONVERT] Starting conversion for {phone} at company {company_id}")

        # 1. Find contact by phone and company
        contact = db.query(Contact).filter(
            Contact.phone == phone,
            Contact.company_id == company_id
        ).first()

        if not contact:
            logger.error(f"[CUSTOMER_CONVERT] Contact not found for {phone}")
            return ConversionResult(
                success=False,
                contact_converted=False,
                lead_deleted=False,
                redirect_message="",
                redirect_contact="",
                error_message="Contato não encontrado no sistema"
            )

        # 2. Check if already a customer
        existing_customer = db.query(Customer).filter(
            Customer.contact_id == contact.id
        ).first()

        contact_converted = False
        if not existing_customer:
            # Convert contact to customer
            try:
                new_customer = Customer(
                    contact_id=contact.id,
                    company_id=company_id,
                    nome=contact.name or "Nome não informado",
                    telefone=phone,
                    categoria='cliente',
                    status='ativo'
                )
                db.add(new_customer)
                db.flush()
                contact_converted = True
                logger.info(f"[CUSTOMER_CONVERT] Customer created with ID {new_customer.id}")
            except Exception as e:
                logger.error(f"[CUSTOMER_CONVERT] Error creating customer: {e}")
                return ConversionResult(
                    success=False,
                    contact_converted=False,
                    lead_deleted=False,
                    redirect_message="",
                    redirect_contact="",
                    error_message=f"Erro ao criar cliente: {str(e)}"
                )

        # 3. SMART LEAD DELETION - Only delete if it's a mistaken lead, not a converted one
        lead_deleted = False
        lead = db.query(Lead).filter(
            Lead.phone == phone,
            Lead.company_id == company_id
        ).first()

        if lead:
            # Check if this lead has appointment history (indicating it's a legitimate conversion)
            has_appointment_history = db.execute(text("""
                SELECT COUNT(*) as count
                FROM agendamentos
                WHERE lead_id = :lead_id
            """), {"lead_id": lead.id}).scalar()

            # Check if lead has sales/attendance history
            has_sales_history = db.execute(text("""
                SELECT COUNT(*) as count
                FROM vendas v
                JOIN comparecimentos comp ON v.comparecimento_id = comp.id
                JOIN agendamentos a ON comp.agendamento_id = a.id
                WHERE a.lead_id = :lead_id
            """), {"lead_id": lead.id}).scalar()

            # DECISION LOGIC:
            # - If lead has appointment/sales history = LEGITIMATE CUSTOMER (preserve lead)
            # - If lead has NO history = MISTAKEN LEAD (safe to delete)

            if has_appointment_history > 0 or has_sales_history > 0:
                # This is a legitimate customer who became customer through the platform
                # DO NOT DELETE - preserve the conversion history
                logger.info(f"[CUSTOMER_CONVERT] Lead {lead.id} has history (appointments={has_appointment_history}, sales={has_sales_history}) - PRESERVING for historical tracking")
                lead_deleted = False
            else:
                # This is a mistaken lead (someone who was already a customer but got marked as lead)
                # SAFE TO DELETE - no valuable history to lose
                try:
                    logger.info(f"[CUSTOMER_CONVERT] Lead {lead.id} has no history - SAFE TO DELETE as mistaken lead")

                    # Simple deletion since there's no history
                    db.delete(lead)
                    lead_deleted = True
                    logger.info(f"[CUSTOMER_CONVERT] ✅ Mistaken lead {lead.id} deleted safely")

                except Exception as e:
                    logger.error(f"[CUSTOMER_CONVERT] Error deleting mistaken lead: {e}")
                    # Continue anyway - conversion is more important than lead deletion

        # 4. Get redirect configuration from context
        redirect_config = _get_redirect_config(context.context, request.redirect_type)
        redirect_contact = _format_redirect(redirect_config)

        # 5. Generate redirect message
        redirect_message = _generate_redirect_message(request.redirect_type, request.user_need, redirect_contact, context.context)

        # 6. Commit changes
        db.commit()

        logger.info(f"[CUSTOMER_CONVERT] ✅ Success: contact_converted={contact_converted}, lead_deleted={lead_deleted}")

        return ConversionResult(
            success=True,
            contact_converted=contact_converted,
            lead_deleted=lead_deleted,
            redirect_message=redirect_message,
            redirect_contact=redirect_contact
        )

    except Exception as e:
        logger.error(f"[CUSTOMER_CONVERT] ❌ Unexpected error: {e}")
        if 'db' in locals():
            db.rollback()

        return ConversionResult(
            success=False,
            contact_converted=False,
            lead_deleted=False,
            redirect_message="",
            redirect_contact="",
            error_message=f"Erro interno: {str(e)}"
        )

def _get_redirect_config(context: CustomerContext, redirect_type: str) -> Dict[str, Any]:
    """Get redirect configuration from agent config"""
    try:
        # Get agent configuration from database
        from backend.prompt.db_integration.agent_config import get_agent_config_dict
        agent_config = get_agent_config_dict(context.db, context.company_id)

        conversation_flow = agent_config.get('conversation_flow', {})

        # Extract redirect configurations
        redirects = {
            'financial': conversation_flow.get('financial_redirect', {}),
            'maintenance': conversation_flow.get('maintenance_redirect', {}),
            'general': conversation_flow.get('regular_redirect', {})
        }

        # Get specific redirect config or fallback to defaults
        redirect_config = redirects.get(redirect_type)
        if redirect_config:
            return redirect_config

    except Exception as e:
        logger.warning(f"[REDIRECT_CONFIG] Error loading from database: {e}")

    # Fallback to default configurations
    default_redirects = {
        'financial': {'type': 'whatsapp', 'number': '5500000000017'},
        'maintenance': {'type': 'fixo', 'number': '00000000000'},
        'general': {'type': 'whatsapp', 'number': '5500000000018'}
    }
    return default_redirects.get(redirect_type, default_redirects['general'])

def _get_business_hours(context: CustomerContext) -> str:
    """Extract business hours from agent config scheduling_config"""
    try:
        from backend.models import AgentConfiguration

        # Query directly from database
        config = context.db.query(AgentConfiguration).filter(
            AgentConfiguration.company_id == context.company_id
        ).first()

        if not config or not config.scheduling_config:
            return "segunda a sexta, 8h30 às 18h"

        schedule_parts = []
        schedule = config.scheduling_config

        # Check weekdays (Monday to Friday)
        weekday_times = set()
        for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']:
            if day in schedule and schedule[day].get('open', False):
                day_config = schedule[day]
                if day_config.get('morningEnabled', False):
                    start = day_config.get('morningStart', '')
                    end = day_config.get('morningEnd', '')
                    if start and end:
                        weekday_times.add((start, end))
                if day_config.get('afternoonEnabled', False):
                    start = day_config.get('afternoonStart', '')
                    end = day_config.get('afternoonEnd', '')
                    if start and end:
                        weekday_times.add((start, end))

        # Build weekday schedule string
        if weekday_times:
            # Get earliest start and latest end
            all_starts = [t[0] for t in weekday_times]
            all_ends = [t[1] for t in weekday_times]
            earliest_start = min(all_starts)
            latest_end = max(all_ends)

            # Format hours (08:30 -> 8h30)
            start_formatted = earliest_start.replace(':', 'h')
            end_formatted = latest_end.replace(':', 'h')
            schedule_parts.append(f"segunda a sexta, {start_formatted} às {end_formatted}")

        # Check Saturday
        if 'saturday' in schedule and schedule['saturday'].get('open', False):
            saturday_config = schedule['saturday']
            saturday_times = []

            if saturday_config.get('morningEnabled', False):
                start = saturday_config.get('morningStart', '')
                end = saturday_config.get('morningEnd', '')
                if start and end:
                    start_formatted = start.replace(':', 'h')
                    end_formatted = end.replace(':', 'h')
                    saturday_times.append(f"{start_formatted} às {end_formatted}")

            if saturday_config.get('afternoonEnabled', False):
                start = saturday_config.get('afternoonStart', '')
                end = saturday_config.get('afternoonEnd', '')
                if start and end:
                    start_formatted = start.replace(':', 'h')
                    end_formatted = end.replace(':', 'h')
                    saturday_times.append(f"{start_formatted} às {end_formatted}")

            if saturday_times:
                schedule_parts.append(f"sábado, {' e '.join(saturday_times)}")

        # Check Sunday
        if 'sunday' in schedule and schedule['sunday'].get('open', False):
            sunday_config = schedule['sunday']
            sunday_times = []

            if sunday_config.get('morningEnabled', False):
                start = sunday_config.get('morningStart', '')
                end = sunday_config.get('morningEnd', '')
                if start and end:
                    start_formatted = start.replace(':', 'h')
                    end_formatted = end.replace(':', 'h')
                    sunday_times.append(f"{start_formatted} às {end_formatted}")

            if sunday_config.get('afternoonEnabled', False):
                start = sunday_config.get('afternoonStart', '')
                end = sunday_config.get('afternoonEnd', '')
                if start and end:
                    start_formatted = start.replace(':', 'h')
                    end_formatted = end.replace(':', 'h')
                    sunday_times.append(f"{start_formatted} às {end_formatted}")

            if sunday_times:
                schedule_parts.append(f"domingo, {' e '.join(sunday_times)}")

        if schedule_parts:
            return " e ".join(schedule_parts)
        else:
            return "segunda a sexta, 8h30 às 18h"

    except Exception as e:
        logger.warning(f"[BUSINESS_HOURS] Error extracting from config: {e}")
        return "segunda a sexta, 8h30 às 18h"

def _format_redirect(redirect_config: Dict[str, Any]) -> str:
    """Format redirect configuration to contact string"""
    redirect_type = redirect_config.get('type', '')
    number = redirect_config.get('number', '')

    if redirect_type == 'whatsapp' and number:
        return f"WhatsApp: {number}"
    elif redirect_type == 'fixo' and number:
        return f"Telefone: {number}"
    else:
        return number

def _generate_redirect_message(redirect_type: str, user_need: str, redirect_contact: str, context: CustomerContext = None) -> str:
    """Generate appropriate redirect message based on type"""

    # Get dynamic business hours
    business_hours = _get_business_hours(context) if context else "segunda a sexta, 8h às 18h"

    base_messages = {
        'financial': f"""Perfeito! Nossa equipe financeira pode te ajudar melhor com isso, pois meu foco aqui é agendar consultas de avaliação (você pode me chamar se no futuro tiver interesse). Então vou deixar aqui nosso contato pra você chamar nossa equipe financeira, eles já irão saber o seu histórico e podem te atender melhor com questões de pagamento e parcelamentos.

{redirect_contact} - {business_hours}

Se precisar agendar sua avaliação no futuro me chama aqui! 😊""",

        'maintenance': f"""Perfeito! Nossa equipe de atendimento pode te ajudar melhor com consultas de retorno, pois meu foco aqui é agendar consultas de avaliação (você pode me chamar se no futuro tiver interesse). Então vou deixar aqui nosso contato pra você chamar nossa equipe, eles já irão saber o seu histórico e podem agendar seu retorno.

{redirect_contact} - {business_hours}

Se precisar agendar sua avaliação no futuro me chama aqui! 😊""",

        'general': f"""Perfeito! Nossa equipe de suporte pode te ajudar melhor com isso, pois meu foco aqui é agendar consultas de avaliação (você pode me chamar se no futuro tiver interesse). Então vou deixar aqui nosso contato pra você chamar nossa equipe, eles já irão saber o seu histórico e podem te atender melhor.

{redirect_contact} - {business_hours}

Se precisar agendar sua avaliação no futuro me chama aqui! 😊"""
    }

    return base_messages.get(redirect_type, base_messages['general'])

# Customer Support Agent
client_support_agent = Agent[CustomerContext](
    name="Customer Support Agent",
    handoff_description="Handles existing customer needs, converts leads to customers, and provides specialized redirections",
    instructions=f"""{RECOMMENDED_PROMPT_PREFIX}

    You handle existing customers with non-scheduling needs and manage system conversions.

    🔴 CRITICAL: NEVER mention "transferir", "passar para", "encaminhar", "equipe responsável" or similar!
    🔴 CRITICAL: You CANNOT schedule appointments - redirect to proper support channel!

    # Your Role:
    - Convert leads to customers in the database
    - Provide appropriate redirections based on customer needs
    - Direct customers to correct support channels
    - Ensure proper system cleanup and organization
    - Maintain professional, helpful communication

    # Process Flow:

    1. **ANALYZE THE REQUEST**:
       - Customer asks about specific dentist (Dr./Dra.) → Redirect to support (maintenance)
       - Customer mentions treatment/scheduling → Redirect to support (maintenance)
       - Customer asks about financial/payment → Redirect to financial
       - Other questions → Redirect to general support

    2. **ALWAYS USE THE TOOL**: convert_lead_to_customer_and_redirect()
       For ALL requests, determine redirect type:
       - 'maintenance': For scheduling, dentists, treatments, appointments
       - 'financial': For payments, prices, insurance
       - 'general': For other questions

    3. **DELIVER MESSAGE NATURALLY**:
       - Use the redirect_message from tool
       - NEVER add words like "transferir" or "encaminhar"
       - Make it sound like you're helping directly

    4. **MONITOR FOR INTENT CHANGE**: After providing redirection, if customer says:
       - "Actually, I want to schedule an evaluation"
       - "Can you help me book an appointment?"
       - "I changed my mind, I want to schedule"
       - Any indication they want to schedule evaluation
       → HANDOFF back to main agent immediately for scheduling

    # When to HANDOFF back to coordinator_agent (main agent):
    - Customer wants to schedule NEW evaluation
    - Customer asks about company hours, location, treatments
    - Customer asks about prices or procedures
    - Customer asks ANY question outside your knowledge
    - User changes topic completely
    - User says they're NOT actually a customer

    5. **CLOSE GRACEFULLY**: End conversation professionally after providing redirection (unless intent changed)

    # Redirect Type Mapping:
    - Financial questions, payments, installments → 'financial'
    - Specific dentist, scheduling, appointments → 'maintenance'
    - Return visits, maintenance, follow-ups → 'maintenance'
    - General questions, other needs → 'general'

    # Examples of CORRECT handling:
    USER: "Quero saber os dias da Dra. Letícia"
    → Use tool with redirect_type='maintenance', user_need='saber dias da Dra. Letícia'

    USER: "Preciso colar o bracket"
    → Use tool with redirect_type='maintenance', user_need='colar bracket'

    USER: "Qual o valor do tratamento?"
    → Use tool with redirect_type='financial', user_need='saber valor do tratamento'

    # Critical Rules:
    - ALWAYS use the conversion tool - never skip this step
    - NEVER mention "transferir", "passar para", "encaminhar" in your responses
    - Use EXACTLY the redirect_message provided by the tool
    - Be warm and reassuring about the redirect process
    - Confirm that everything is organized in the system
    - WATCH for scheduling intent change and handoff accordingly
    - If customer expresses interest in scheduling evaluation after redirection → HANDOFF to main agent
    """,
    tools=[convert_lead_to_customer_and_redirect]
)
