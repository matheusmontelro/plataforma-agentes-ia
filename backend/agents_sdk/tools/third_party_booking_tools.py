"""
Third Party Booking Tools - Tools for handling appointments for family members
"""

from agents import function_tool, RunContextWrapper
from typing import Annotated, Optional
from pydantic import Field
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

@function_tool
def collect_third_party_info(
    context: RunContextWrapper,
    data_type: Annotated[str, Field(description="Tipo de dado: nome, telefone ou status_cliente")],
    data_value: Annotated[Optional[str], Field(description="Valor coletado do usuário")] = None
) -> str:
    """
    Coleta incremental de dados para agendamento de terceiros.
    Guia o fluxo de coleta de nome, telefone e status de cliente.
    """

    from ..context.booking_context import BookingContext

    ctx: BookingContext = context.context

    # Update collection stage
    if data_type == "nome" and data_value:
        ctx.customer_name = data_value
        ctx.collection_stage = "collecting_phone"

        # Validate name (needs at least 2 words)
        if len(data_value.split()) < 2:
            return f"Por favor, forneça o nome completo da sua {ctx.relationship} (nome e sobrenome)."

        logger.info(f"[ThirdParty-CollectInfo] Collected customer_name: {data_value}")
        return f"Ótimo! Agora preciso de um telefone de contato para {data_value}."

    elif data_type == "telefone" and data_value:
        ctx.customer_phone = data_value
        ctx.collection_stage = "checking_customer_status"
        logger.info(f"[ThirdParty-CollectInfo] Collected customer_phone: {data_value}")
        return f"Perfeito! Antes de prosseguir, {ctx.customer_name} já é cliente da empresa ou será a primeira vez?"

    elif data_type == "status_cliente" and data_value:
        # Check if user said they are existing customer or first time
        data_lower = data_value.lower()
        if any(word in data_lower for word in ["já", "sim", "cliente", "retorno", "volta"]):
            ctx.is_existing_customer = True
            ctx.collection_stage = "needs_customer_support"
            # Signal that we need to handoff to customer support agent
            return "HANDOFF_TO_CUSTOMER_SUPPORT"
        else:
            ctx.is_existing_customer = False
            ctx.collection_stage = "confirming"
            return f"Que bom receber {ctx.customer_name} como novo cliente! Vou confirmar o agendamento da avaliação..."

    # Initial collection
    elif ctx.collection_stage == "initial":
        ctx.collection_stage = "collecting_name"
        return f"Perfeito! Vamos agendar para sua {ctx.relationship}. Qual o nome completo dela(e)?"

    return "Por favor, forneça as informações solicitadas."


@function_tool
def process_third_party_appointment(
    context: RunContextWrapper,
    customer_name: Annotated[str, Field(description="Nome completo do cliente")],
    customer_phone: Annotated[str, Field(description="Telefone do cliente")],
    appointment_date: Annotated[Optional[str], Field(description="Data do agendamento (formato: DD/MM/YYYY)")] = None,
    appointment_time: Annotated[Optional[str], Field(description="Horário do agendamento (formato: HH:MM)")] = None
) -> str:
    """
    Processa e confirma agendamento para terceiro (familiar).
    Cria lead e agenda consulta para o cliente.
    """

    from ..context.booking_context import BookingContext

    ctx: BookingContext = context.context

    try:
        # Validate name - must have at least first and last name
        if len(customer_name.split()) < 2:
            relationship_text = f"o {customer_name}" if ctx.relationship in ["filho", "pai", "irmão"] else f"a {customer_name}"
            return f"{relationship_text.capitalize()} não tem pelo menos um sobrenome pra confirmarmos o agendamento? Pode confirmar o nome completo pra mim, preciso dessa informação."

        # Clean phone number - Remove all non-digits
        customer_phone_clean = re.sub(r'\D', '', customer_phone)
        logger.info(f"[ThirdPartyBooking] Phone input: '{customer_phone}' -> cleaned: '{customer_phone_clean}'")

        # Always ensure phone starts with Brazil code 55
        if not customer_phone_clean.startswith('55'):
            customer_phone_clean = '55' + customer_phone_clean
            logger.info(f"[ThirdPartyBooking] Added country code 55 -> '{customer_phone_clean}'")

        # Validate final phone format: 55 + 2-digit DDD + 8 or 9 digits = 12 or 13 total
        if len(customer_phone_clean) < 12 or len(customer_phone_clean) > 13:
            logger.warning(f"[ThirdPartyBooking] Invalid phone length: {len(customer_phone_clean)} digits")
            return "Por favor, forneça um telefone válido com DDD (exemplo: 21998765432 ou 11987654321)."

        logger.info(f"[ThirdPartyBooking] Final phone number: '{customer_phone_clean}' ({len(customer_phone_clean)} digits)")

        # Import database dependencies
        from backend.db import get_db
        from backend.models import Lead, Contact, Client
        from sqlalchemy import text

        db = next(get_db())

        # First, get the client_id for this company
        client = db.query(Client).filter_by(
            company_id=ctx.company_id
        ).first()

        if not client:
            logger.error(f"[ThirdPartyBooking] Client not found for company_id {ctx.company_id}")
            return "Erro ao processar agendamento. Entre em contato com a empresa."

        client_id = client.id

        # Check if lead exists or create new one
        existing_lead = db.query(Lead).filter_by(
            phone=customer_phone_clean,
            company_id=ctx.company_id
        ).first()

        if not existing_lead:
            # Create new lead for the third party
            new_lead = Lead(
                name=customer_name,
                phone=customer_phone_clean,
                company_id=ctx.company_id,
                client_id=client_id,  # Adding client_id for consistency
                source_id="Indicação",
            )
            db.add(new_lead)
            db.flush()  # Flush to get the ID without committing yet
            logger.info(f"[ThirdPartyBooking] ✅ Created new lead: name='{customer_name}', phone='{customer_phone_clean}', company_id={ctx.company_id}")
        else:
            logger.info(f"[ThirdPartyBooking] Lead already exists: id={existing_lead.id}, phone='{existing_lead.phone}'")

        # Check if contact exists or create new one
        existing_contact = db.query(Contact).filter_by(
            phone=customer_phone_clean,
            company_id=ctx.company_id
        ).first()

        if not existing_contact:
            # Create new contact for the third party to enable WhatsApp communication
            new_contact = Contact(
                client_id=client_id,
                company_id=ctx.company_id,
                phone=customer_phone_clean,
                name=customer_name,
                human_mode=False  # Default to AI mode for new contacts
            )
            db.add(new_contact)
            db.flush()  # Flush to ensure contact is created
            logger.info(f"[ThirdPartyBooking] ✅ Created new contact: name='{customer_name}', phone='{customer_phone_clean}', company_id={ctx.company_id}")
        else:
            logger.info(f"[ThirdPartyBooking] Contact already exists: id={existing_contact.id}, phone='{existing_contact.phone}'")

        # Commit both lead and contact together
        db.commit()

        # Process appointment using existing logic
        from backend.prompt.db_integration.agendamento_logic import processar_json_do_llm

        # Use provided date/time if available, otherwise try context
        final_date = appointment_date or ctx.selected_date
        final_time = appointment_time or ctx.selected_time

        # Build LLM JSON for appointment
        logger.critical(f"[ThirdPartyBooking] Context data: selected_date={ctx.selected_date}, selected_time={ctx.selected_time}, relationship={ctx.relationship}")
        logger.critical(f"[ThirdPartyBooking] Parameters: appointment_date={appointment_date}, appointment_time={appointment_time}")
        logger.critical(f"[ThirdPartyBooking] Final values: final_date={final_date}, final_time={final_time}")

        # Validate that we have date and time
        if not final_date or not final_time:
            return (f"Ainda preciso saber quando você quer agendar para {customer_name}. "
                   f"Qual dia e horário você prefere?")

        llm_json = {
            "agendamento_confirmado": True,
            "appointment_date": final_date,
            "appointment_time": final_time,
            "customer_name": customer_name,
            "phone": customer_phone_clean,
            "treatment_type": ctx.treatment_type or "Consulta de Avaliação",
            "is_third_party": True,
            "requester_phone": ctx.requester_phone,
            "relationship": ctx.relationship
        }

        logger.critical(f"[ThirdPartyBooking] llm_json being sent: {llm_json}")

        # Get API key for company
        api_key = None
        try:
            result = db.execute(text("""
                SELECT c.api_key
                FROM clients c
                JOIN client_companies cc ON cc.client_id = c.id
                WHERE cc.company_id = :company_id
                LIMIT 1
            """), {"company_id": ctx.company_id}).fetchone()

            if result:
                api_key = result.api_key
        except Exception as e:
            logger.error(f"[ThirdPartyBooking] Error fetching API key: {e}")

        # Process the appointment
        result = processar_json_do_llm(
            db=db,
            company_id=ctx.company_id,
            phone=customer_phone_clean,
            llm_json=llm_json,
            api_key=api_key
        )

        # ATUALIZAR: Campo interesse no agendamento e nome no contact para TERCEIROS
        # Como agendamento_logic.py não preenche o campo interesse, fazemos aqui
        if result and not result.startswith("Erro") and not result.startswith("Ocorreu"):
            try:
                # 1. Atualizar campo interesse no agendamento recém-criado
                treatment = ctx.treatment_type or "Consulta de Avaliação"
                if treatment and treatment != "Consulta de Avaliação":
                    db.execute(text("""
                        UPDATE agendamentos
                        SET interesse = :treatment
                        WHERE phone = :phone
                        AND company_id = :company_id
                        AND status = 'SCHEDULED'
                        ORDER BY id DESC
                        LIMIT 1
                    """), {"treatment": treatment, "phone": customer_phone_clean, "company_id": ctx.company_id})
                    logger.info(f"[ThirdParty-POST] ✅ Updated interesse='{treatment}' for {customer_phone_clean}")

                # 2. Garantir que contact tenha nome completo (não apenas telefone)
                db.execute(text("""
                    UPDATE contacts
                    SET name = :name
                    WHERE phone = :phone
                    AND company_id = :company_id
                    AND (name IS NULL OR name = '' OR name = :phone)
                """), {"name": customer_name, "phone": customer_phone_clean, "company_id": ctx.company_id})

                db.commit()
                logger.info(f"[ThirdParty-POST] ✅ Contact and appointment data enriched for {customer_phone_clean}")

            except Exception as update_error:
                logger.error(f"[ThirdParty-POST] Error updating appointment/contact data: {update_error}")
                db.rollback()

        # Generate protocol number
        protocol = datetime.now().strftime("%Y%m%d%H%M")

        # Build confirmation message
        relationship_text = f"sua {ctx.relationship}" if ctx.relationship else "o cliente"

        confirmation_message = f"""✅ Agendamento confirmado para {relationship_text}!

👤 **Cliente**: {customer_name}
📅 **Data**: {ctx.selected_date} às {ctx.selected_time}
📱 **Telefone**: {customer_phone}
🔢 **Protocolo**: {protocol}

Enviamos a confirmação por WhatsApp para o número cadastrado.
Caso precise reagendar ou cancelar, é só me avisar!"""

        logger.info(f"[ThirdPartyBooking] Successfully booked for {customer_name} "
                   f"(relationship: {ctx.relationship}) via requester {ctx.requester_phone}")

        # Mark completion
        ctx.collection_stage = "completed"

        # Clear third-party booking state from contact_context (if accessible)
        # This will allow new third-party bookings to start fresh
        # Note: We don't have direct access to contact_context here, but it will be
        # cleared naturally when user starts a different conversation topic

        return confirmation_message

    except Exception as e:
        logger.error(f"[ThirdPartyBooking] Error processing appointment: {e}")
        return ("Houve um erro ao processar o agendamento. "
               "Por favor, entre em contato pelo telefone da empresa.")

    finally:
        try:
            db.close()
        except:
            pass