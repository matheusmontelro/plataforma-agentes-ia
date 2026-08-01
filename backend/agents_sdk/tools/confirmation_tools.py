"""
Confirmation Tools - OpenAI Agents SDK compatible tools for appointment confirmation
Enhanced with structured context and detailed tracing

This module provides LLM-driven tools that wrap existing agendamento_logic.py
functionality in a modular, type-safe way following OpenAI SDK patterns.
"""

import logging
from typing import Annotated, Optional
from pydantic import Field
from sqlalchemy.orm import Session

# Importar decorator do OpenAI Agents SDK
from agents import function_tool, trace

# Import structured context
try:
    from ..context.contact_context import CustomerContext
except ImportError:
    # Fallback for backwards compatibility
    CustomerContext = None

logger = logging.getLogger(__name__)

def _ensure_lead_exists_for_scheduling(db, company_id: int, phone: str, customer_name: str, target_stage_id: Optional[int] = None, media_source: Optional[str] = None):
    """
    AJUSTE CIRÚRGICO: Ensure lead exists before calling agendamento_logic.py

    2 scenarios:
    1. Is customer (exists in clientes table) → create lead with source_id="Carteira de Clientes"
    2. Is only contact (not customer) → create lead with source_id=NULL
    """
    try:
        from sqlalchemy import text
        from backend.models import Lead, PipelineStage
        from datetime import datetime
        from pytz import timezone

        # 1. Check if lead already exists
        existing_lead = db.execute(text("""
            SELECT id FROM leads
            WHERE phone = :phone AND company_id = :company_id
            LIMIT 1
        """), {"phone": phone, "company_id": company_id}).fetchone()

        if existing_lead:
            logger.info(f"[ENSURE_LEAD] Lead already exists for {phone}")

            # FORCE STAGE UPDATE if target_stage_id is provided
            if target_stage_id:
                try:
                    # Verify stage exists and get pipeline_id
                    stage_info = db.execute(text("SELECT id, pipeline_id FROM pipeline_stages WHERE id = :sid"), {"sid": target_stage_id}).fetchone()
                    if stage_info:
                        db.execute(text("""
                            UPDATE leads
                            SET current_stage_id = :sid,
                                pipeline_id = :pid,
                                last_stage_move_at = NOW()
                            WHERE id = :lid
                        """), {
                            "sid": target_stage_id,
                            "pid": stage_info.pipeline_id,
                            "lid": existing_lead.id
                        })

                        # Track history
                        db.execute(text("""
                            INSERT INTO lead_pipeline_history (lead_id, company_id, from_stage_id, to_stage_id, moved_at)
                            VALUES (:lid, :cid, NULL, :sid, NOW())
                        """), {
                            "lid": existing_lead.id,
                            "cid": company_id,
                            "sid": target_stage_id
                        })
                        db.commit()
                        logger.info(f"[ENSURE_LEAD] ✅ Enforced target stage {target_stage_id} for existing lead {existing_lead.id}")
                except Exception as ef:
                    logger.error(f"[ENSURE_LEAD] Failed to enforce stage: {ef}")

            return

        # 2. Set source_id based on media_source
        source_id = media_source
        logger.info(f"[ENSURE_LEAD] Creating lead for {phone} with source_id='{source_id}'")

        # 4. Get client_id for the company
        client_info = db.execute(text("""
            SELECT id as client_id FROM clients WHERE company_id = :company_id LIMIT 1
        """), {"company_id": company_id}).fetchone()

        if not client_info:
            logger.error(f"[ENSURE_LEAD] Client not found for company_id={company_id}")
            return

        # --- NEW: Ensure CONTACT exists first ---
        # If contact doesn't exist, the subsequent UPDATE in execute_appointment_confirmation will fail silently.

        existing_contact = db.execute(text("""
            SELECT id FROM contacts
            WHERE phone = :phone AND company_id = :company_id
            LIMIT 1
        """), {"phone": phone, "company_id": company_id}).fetchone()

        if not existing_contact:
            try:
                # Use provided name or default
                c_name = customer_name if customer_name and customer_name.strip() else "Novo Contato"

                db.execute(text("""
                    INSERT INTO contacts (client_id, company_id, phone, name, human_mode)
                    VALUES (:client_id, :company_id, :phone, :name, :human_mode)
                """), {
                    "client_id": str(client_info.client_id),
                    "company_id": company_id,
                    "phone": phone,
                    "name": c_name,
                    "human_mode": False
                })
                # Commit immediately to ensure ID availability if needed
                db.commit()
                logger.info(f"[ENSURE_LEAD] ✅ Created missing Contact for {phone}")
            except Exception as ce:
                logger.error(f"[ENSURE_LEAD] Failed to create contact: {ce}")
                db.rollback()
        # ----------------------------------------

        # 5. Create lead with appropriate source_id
        sp_tz = timezone('America/Sao_Paulo')
        data_entrada = datetime.now(sp_tz).strftime("%Y-%m-%d %H:%M:%S")

        db.execute(text("""
            INSERT INTO leads
                (client_id, company_id, name, phone, source_id, created_at, data_entrada)
            VALUES (:client_id, :company_id, :name, :phone, :source_id, :created_at, :data_entrada)
        """), {
            "client_id": str(client_info.client_id),
            "company_id": company_id,
            "name": customer_name,
            "phone": phone,
            "source_id": source_id,
            "created_at": data_entrada,
            "data_entrada": data_entrada
        })

        # Apply target stage if provided and lead created
        if target_stage_id:
             try:
                # Get the created lead ID (or query it)
                # Since we didn't use RETURNING, query it back
                new_lead = db.execute(text("SELECT id FROM leads WHERE phone=:p AND company_id=:c ORDER BY id DESC LIMIT 1"), {"p": phone, "c": company_id}).fetchone()

                stage_info = db.execute(text("SELECT id, pipeline_id FROM pipeline_stages WHERE id = :sid"), {"sid": target_stage_id}).fetchone()

                if new_lead and stage_info:
                    db.execute(text("""
                        UPDATE leads
                        SET current_stage_id = :sid,
                            pipeline_id = :pid
                        WHERE id = :lid
                    """), {
                        "sid": target_stage_id,
                        "pid": stage_info.pipeline_id,
                        "lid": new_lead.id
                    })

                    # Track history for new lead
                    db.execute(text("""
                        INSERT INTO lead_pipeline_history (lead_id, company_id, from_stage_id, to_stage_id, moved_at)
                        VALUES (:lid, :cid, NULL, :sid, NOW())
                    """), {
                        "lid": new_lead.id,
                        "cid": company_id,
                        "sid": target_stage_id
                    })
                    logger.info(f"[ENSURE_LEAD] Applied target stage {target_stage_id} to new lead {new_lead.id}")
             except Exception as es:
                 logger.error(f"[ENSURE_LEAD] Error applying stage to new lead: {es}")


        db.commit()
        logger.info(f"[ENSURE_LEAD] ✅ Lead created for {phone} with source_id='{source_id}'")

    except Exception as e:
        logger.error(f"[ENSURE_LEAD] Error creating lead for {phone}: {e}")
        # Don't raise - let scheduling continue even if lead creation fails
        db.rollback()


def execute_appointment_confirmation(
    company_id: int,
    phone: str,
    customer_name: str,
    appointment_date: str,
    appointment_time: str,
    treatment_type: str = "Consulta de Avaliação",
    customer_type: str = "novo",
    agenda_id: Optional[int] = None,
    target_stage_id: Optional[int] = None,
    media_source: Optional[str] = None
) -> str:
    """
    Core implementation of appointment confirmation logic.
    Separated from tool wrapper to allow direct usage.
    """
    from typing import Optional
    # Enhanced tracing with structured context
    with trace("process_appointment_confirmation"):
        # Log tool entry with all parameters
        logger.critical(f"[TOOL_ENTRY] process_appointment_confirmation called with: company_id={company_id}, phone={phone}, customer_name={customer_name[:50]}, appointment_date={appointment_date}, appointment_time={appointment_time}, treatment_type={treatment_type}, customer_type={customer_type}, agenda_id={agenda_id}")

        logger.info(f"[ConfirmationTool] Processing confirmation for {phone} at company {company_id}")

        # Enhanced structured logging
        logger.info(
            f"[ENHANCED_TRACING] process_appointment_confirmation called",
            extra={
                "event": "tool_call",
                "tool": "process_appointment_confirmation",
                "company_id": company_id,
                "phone": phone,
                "appointment_date": appointment_date,
                "appointment_time": appointment_time,
                "treatment_type": treatment_type,
                "customer_type": customer_type,
                "agenda_id": agenda_id, # Log agenda_id
                "customer_name_length": len(customer_name)  # Privacy-safe
            }
        )

        try:
            # Import the wrapper service
            from ..services.appointment_service import AppointmentService
            from backend.db import get_db

            # Get database session
            db = next(get_db())

            # AJUSTE CIRÚRGICO: Ensure lead exists before scheduling
            _ensure_lead_exists_for_scheduling(db, company_id, phone, customer_name, target_stage_id, media_source)

            # --- AUTO-ASSIGN AGENDA IF MISSING ---
            if not agenda_id:
                try:
                    from backend.models import Agenda
                    # Find the first active agenda for this company (default logic)
                    active_agenda = db.query(Agenda).filter(
                        Agenda.company_id == company_id,
                        Agenda.active == True
                    ).first()

                    if active_agenda:
                        agenda_id = active_agenda.id
                        logger.info(f"[ConfirmationTool] Auto-assigned default Agenda ID: {agenda_id}")
                    else:
                        logger.warning(f"[ConfirmationTool] No active agenda found for company {company_id}")
                except Exception as agenda_err:
                    logger.error(f"[ConfirmationTool] Error finding default agenda: {agenda_err}")
            # -------------------------------------

            # Create service instance
            appointment_service = AppointmentService(db)

            # Process confirmation using existing business logic
            result = appointment_service.process_confirmation(
                company_id=company_id,
                phone=phone,
                customer_name=customer_name,
                appointment_date=appointment_date,
                appointment_time=appointment_time,
                treatment_type=treatment_type,
                customer_type=customer_type,
                agenda_id=agenda_id # Pass agenda_id
            )

            logger.info(f"[ConfirmationTool] Confirmation processed successfully for {phone}")

            # UPDATE CUSTOMER CONTEXT AFTER CONFIRMATION
            if result and not result.startswith("Erro") and not result.startswith("Ocorreu"):
                try:
                    # Update structured context to mark appointment as confirmed
                    if CustomerContext:
                        try:
                            # Get or create context from RunContext if available
                            import agents
                            context = agents.get_run_context()
                            if context and hasattr(context, 'structured_context'):
                                context.structured_context.appointment_confirmed = True
                                context.structured_context.appointment_protocol = result.split("Protocolo: ")[-1].split("\n")[0] if "Protocolo:" in result else "confirmed"
                                context.structured_context.selected_date = appointment_date
                                context.structured_context.selected_time = appointment_time
                                logger.info(f"[CONTEXT_UPDATE] ✅ Updated appointment_confirmed=True in structured context")
                        except Exception as ctx_error:
                            logger.warning(f"[CONTEXT_UPDATE] Could not update structured context: {ctx_error}")

                    # ATUALIZAR: Campo interesse no agendamento e nome no contact
                    # Como agendamento_logic.py não preenche o campo interesse, fazemos aqui
                    from sqlalchemy import text

                    # 1. Atualizar campo interesse no agendamento recém-criado
                    if treatment_type and treatment_type != "Consulta de Avaliação":
                        # Primeiro buscar o ID do agendamento mais recente
                        latest_appointment = db.execute(text("""
                            SELECT id FROM agendamentos
                            WHERE phone = :phone
                            AND company_id = :company_id
                            AND status = 'SCHEDULED'
                            ORDER BY id DESC
                            LIMIT 1
                        """), {"phone": phone, "company_id": company_id}).fetchone()

                        if latest_appointment:
                            db.execute(text("""
                                UPDATE agendamentos
                                SET interesse = :treatment
                                WHERE id = :appointment_id
                            """), {"treatment": treatment_type, "appointment_id": latest_appointment.id})
                            logger.info(f"[POST_APPOINTMENT] ✅ Updated interesse='{treatment_type}' for appointment ID {latest_appointment.id}")

                    # 2. Garantir que contact tenha nome completo (não apenas telefone)
                    db.execute(text("""
                        UPDATE contacts
                        SET name = :name
                        WHERE phone = :phone
                        AND company_id = :company_id
                        AND (name IS NULL OR name = '' OR name = :phone)
                    """), {"name": customer_name, "phone": phone, "company_id": company_id})
                    logger.info(f"[POST_APPOINTMENT] ✅ Updated contact name to '{customer_name}' for {phone}")

                    db.commit()
                    logger.info(f"[POST_APPOINTMENT] ✅ Contact and appointment data enriched for {phone}")

                except Exception as update_error:
                    logger.error(f"[POST_APPOINTMENT] Error updating appointment/contact data: {update_error}")
                    db.rollback()

            # Log success without span attributes
            logger.info(f"[SUCCESS] Appointment confirmed successfully for {phone}")

            # Enhanced success logging
            logger.info(
                f"[SUCCESS] Appointment confirmed successfully",
                extra={
                    "event": "appointment_confirmed",
                    "tool": "process_appointment_confirmation",
                    "company_id": company_id,
                    "phone": phone,
                    "appointment_date": appointment_date,
                    "appointment_time": appointment_time,
                    "treatment_type": treatment_type,
                    "customer_type": customer_type
                }
            )

            # NOVO: Agendar solicitação de indicações se empresa tem campanha ativa
            if result and not result.startswith("Erro") and not result.startswith("Ocorreu"):
                try:
                    from ..services.referral_service import ReferralService

                    # Verificar e agendar indicações
                    referral_service = ReferralService(db)
                    campaign = referral_service.get_active_campaign(company_id)

                    if campaign:
                        logger.info(f"[REFERRAL_HOOK] Agendando solicitação de indicações para {phone}")

                        # Executar agendamento (agora síncrono)
                        success = referral_service.schedule_referrer_request(
                            company_id=company_id,
                            phone=phone,
                            customer_name=customer_name,
                            campaign=campaign
                        )

                        if success:
                            logger.info(f"[REFERRAL_HOOK] ✅ Solicitação agendada para {campaign.delay_minutes} minutos")
                        else:
                            logger.warning(f"[REFERRAL_HOOK] ❌ Falha ao agendar solicitação")
                    else:
                        logger.info(f"[REFERRAL_HOOK] Empresa {company_id} não tem campanha ativa - pulando indicações")

                except Exception as referral_error:
                    # Não quebrar o fluxo principal por erro nas indicações
                    logger.error(f"[REFERRAL_HOOK] Erro ao processar indicações: {referral_error}")

            return result

        except Exception as e:
            # Log errors without span attributes
            logger.critical(f"[ERROR] Appointment confirmation failed: {str(e)} (type: {type(e).__name__})")

            logger.error(f"[ConfirmationTool] Error processing confirmation: {e}")

            # Enhanced error logging
            logger.error(
                f"[ERROR] Appointment confirmation failed",
                extra={
                    "event": "appointment_confirmation_failed",
                    "tool": "process_appointment_confirmation",
                    "company_id": company_id,
                    "phone": phone,
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )

            return (
                "Ocorreu um erro interno ao processar seu agendamento. "
                "Nossa equipe foi notificada e entrará em contato em breve."
            )
        finally:
            # Ensure database session is closed
            try:
                db.close()
            except:
                pass


@function_tool
def process_appointment_confirmation(
    company_id: Annotated[int, Field(description="ID da empresa onde será feito o agendamento")],
    phone: Annotated[str, Field(description="Telefone do cliente (formato: 5500000000009)")],
    customer_name: Annotated[str, Field(description="Nome completo do cliente")],
    appointment_date: Annotated[str, Field(description="Data do agendamento no formato DD/MM/YYYY")],
    appointment_time: Annotated[str, Field(description="Horário do agendamento no formato HH:MM")],
    treatment_type: Annotated[str, Field(description="Tipo de tratamento solicitado pelo cliente")] = "Consulta de Avaliação",
    customer_type: Annotated[str, Field(description="Tipo de cliente: 'novo' ou 'retorno'")] = "novo",
    agenda_id: Annotated[Optional[int], Field(description="ID opcional da agenda específica (se houver preferência)")] = None
) -> str:
    """
    Processa confirmação completa do agendamento integrando com sistema existente.

    Esta tool encapsula toda a lógica de agendamento_logic.py de forma modular:
    - Salva agendamento no banco de dados
    - Sincroniza com CRM (Clinicorp/Google Calendar/Webhook)
    - Gera mensagem de confirmação padrão
    - Agenda tasks de follow-up automáticas

    Args:
        company_id: ID numérico da empresa
        phone: Telefone no formato brasileiro completo
        customer_name: Nome completo com pelo menos 2 palavras
        appointment_date: Data no formato brasileiro DD/MM/YYYY
        appointment_time: Horário no formato 24h HH:MM
        treatment_type: Tipo de tratamento extraído da conversa (ex: "Limpeza", "Canal", etc.)
        customer_type: "novo" se é primeira vez na empresa, "retorno" se já é cliente
        agenda_id: ID específico da agenda (opcional)

    Returns:
        Mensagem de confirmação formatada para envio ao cliente
    """
    return execute_appointment_confirmation(
        company_id=company_id,
        phone=phone,
        customer_name=customer_name,
        appointment_date=appointment_date,
        appointment_time=appointment_time,
        treatment_type=treatment_type,
        customer_type=customer_type,
        agenda_id=agenda_id
    )

# Tool registration for OpenAI Agents SDK
# This will be imported and used by the business assistant agent
CONFIRMATION_TOOLS = [
    process_appointment_confirmation
]