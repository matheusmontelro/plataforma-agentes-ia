"""
WhatsApp Campaign Celery Tasks

Tasks for processing WhatsApp marketing campaigns asynchronously.
"""

import logging
import random
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError

from .celery_app import app
from backend.db import SessionLocal
from backend.models import (
    WhatsAppCampaign, WhatsAppCampaignExecution,
    Contact, ContactTag, Company
)
from backend.integrations.waha_utils import send_text_to_waha, check_number_exists
from backend.services.company_access_control import (
    CompanyOperationallyBlockedError,
    enqueue_company_job_if_active,
    fence_company_job_mutation,
)
from backend.services.ai_provider_service import (
    AIProviderCredentialError,
    get_company_openai_api_key,
)

logger = logging.getLogger(__name__)


def humanize_message(
    original_message: str,
    contact_name: str = None,
    *,
    db=None,
    company_id: int | None = None,
) -> str:
    """
    Usa LLM para fazer pequenas variações na mensagem sem mudar o contexto.
    Isso evita que o WhatsApp detecte mensagens idênticas como spam/bot.

    Args:
        original_message: Mensagem original da campanha
        contact_name: Nome do contato (opcional, para personalização)

    Returns:
        Mensagem com pequenas variações (ou original se falhar)
    """
    try:
        from openai import OpenAI

        if db is None or not company_id:
            logger.warning(
                "[humanize_message] Company context missing, using original message"
            )
            return original_message
        try:
            api_key = get_company_openai_api_key(db, company_id)
        except AIProviderCredentialError:
            logger.warning(
                "[humanize_message] Company OpenAI key unavailable, using original message company_id=%s",
                company_id,
            )
            return original_message

        client = OpenAI(api_key=api_key)

        # Construir prompt
        personalization = f"O nome do destinatário é {contact_name}. " if contact_name else ""

        prompt = f"""Você é um assistente que ajuda a humanizar mensagens de marketing.

Sua tarefa é fazer PEQUENAS variações na mensagem abaixo, mantendo exatamente o mesmo significado e contexto.

Regras:
1. NÃO mude o significado ou intenção da mensagem
2. NÃO adicione informações novas
3. NÃO remova informações importantes
4. Faça apenas pequenas mudanças como:
   - Trocar sinônimos simples
   - Mudar levemente a ordem de algumas frases
   - Variar emojis similares (ex: 👋 por 🙋 ou 😊)
   - Pequenas variações de pontuação
5. Mantenha o mesmo tom (formal/informal)
6. A mensagem resultante deve ter tamanho similar à original
{personalization}

Mensagem original:
{original_message}

Retorne APENAS a mensagem variada, sem explicações."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Modelo rápido e barato
            messages=[
                {"role": "system", "content": "Você faz pequenas variações em mensagens para parecerem mais humanas."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500,
            temperature=0.7  # Criatividade moderada
        )

        varied_message = response.choices[0].message.content.strip()

        # Validação básica: se a resposta for muito diferente em tamanho, usar original
        original_len = len(original_message)
        varied_len = len(varied_message)

        if varied_len < original_len * 0.5 or varied_len > original_len * 2:
            logger.warning(f"[humanize_message] Varied message length ({varied_len}) too different from original ({original_len}), using original")
            return original_message

        logger.info(f"[humanize_message] Message humanized successfully")
        return varied_message

    except Exception as e:
        logger.error(
            "[humanize_message] Error humanizing message: %s",
            type(e).__name__,
        )
        return original_message


def replace_message_variables(message: str, contact_name: str) -> str:
    """
    Substitui variáveis na mensagem pelo valor real do contato.
    Suporta:
    - {{nome}}: Nome completo
    - {{primeiro_nome}}: Primeiro nome apenas
    """
    if not message or not contact_name:
        return message

    # Replace {{nome}} -> Full Name
    message = message.replace("{{nome}}", contact_name)

    # Replace {{primeiro_nome}} -> First Name
    first_name = contact_name.split()[0] if contact_name else ""
    message = message.replace("{{primeiro_nome}}", first_name)

    return message



@app.task
def process_whatsapp_campaign(campaign_id: int):
    """
    Orchestrate the WhatsApp campaign.
    1. Fetch targets based on tags.
    2. Create PENDING executions.
    3. Queue individual messages with rate-limited delays (in minutes) to avoid WhatsApp blocking.
    """
    logger.info(f"[WhatsAppCampaign] Starting campaign processing: {campaign_id}")
    db = SessionLocal()
    try:
        campaign = db.query(WhatsAppCampaign).get(campaign_id)
        if not campaign:
            logger.error(f"[WhatsAppCampaign] Campaign {campaign_id} not found.")
            return
        from backend.services.company_access_control import is_company_operational
        if not is_company_operational(db, int(campaign.company_id)):
            campaign.status = "CANCELED"
            db.commit()
            return

        # Check if campaign was paused/canceled before we started
        if campaign.status not in ('PROCESSING',):
            logger.info(f"[WhatsAppCampaign] Campaign {campaign_id} status is {campaign.status}. Aborting.")
            return

        # 1. Fetch Contacts
        target_tags = campaign.target_tags or []
        excluded_tags = campaign.excluded_tags or []

        if not target_tags:
            logger.warning(f"[WhatsAppCampaign] No target tags defined for campaign {campaign_id}.")
            campaign.status = 'FAILED'
            campaign.total_contacts = 0
            db.commit()
            return

        # Query contacts that have ANY of the target tags
        query = db.query(Contact).join(ContactTag).filter(
            Contact.company_id == campaign.company_id,
            ContactTag.tag_id.in_(target_tags)
        )

        if excluded_tags:
            # Exclude contacts that have ANY of the excluded tags
            exclude_query = db.query(Contact.id).join(ContactTag).filter(
                ContactTag.tag_id.in_(excluded_tags)
            )
            query = query.filter(Contact.id.notin_(exclude_query))

        # Use distinct to avoid duplicates if contact has multiple target tags
        contacts = query.distinct().all()

        total = len(contacts)
        campaign.total_contacts = total
        db.commit()

        logger.info(f"[WhatsAppCampaign] Found {total} contacts for campaign {campaign_id}")

        if total == 0:
            campaign.status = 'COMPLETED'
            db.commit()
            logger.info(f"[WhatsAppCampaign] Campaign {campaign_id} completed (0 contacts).")
            return

        # 2. Create Executions & Queue

        # Rate Limiting Config (in MINUTES, convert to seconds)
        min_delay_seconds = (campaign.interval_min or 1) * 60
        max_delay_seconds = (campaign.interval_max or 5) * 60

        # Start scheduling from NOW + 5 seconds
        virtual_now_utc = datetime.utcnow() + timedelta(seconds=5)

        daily_start = campaign.daily_start_time
        daily_end = campaign.daily_end_time
        allowed_days = campaign.allowed_days

        queued_count = 0

        for contact in contacts:
            # Check if execution already exists (resume capability)
            exists = db.query(WhatsAppCampaignExecution).filter(
                WhatsAppCampaignExecution.campaign_id == campaign_id,
                WhatsAppCampaignExecution.contact_id == contact.id
            ).first()

            if exists:
                continue

            # Time Window & Allowed Days Check
            if daily_start and daily_end:
                while True:
                    # Convert Virtual Now UTC to Brazil Time (approx UTC-3)
                    brazil_time = virtual_now_utc - timedelta(hours=3)
                    current_day = brazil_time.weekday()  # 0=Monday
                    current_time_of_day = brazil_time.time()

                    # 1. Check Day
                    day_ok = (not allowed_days) or (current_day in allowed_days)

                    # 2. Check Time
                    if daily_start <= daily_end:
                        # Normal window: 08:00 to 21:00
                        in_time_window = daily_start <= current_time_of_day <= daily_end
                    else:
                        # Overnight window: 22:00 to 05:00
                        in_time_window = current_time_of_day >= daily_start or current_time_of_day <= daily_end

                    if day_ok and in_time_window:
                        break

                    # Calculate next jump
                    if not day_ok:
                        # If day is not allowed, jump to next allowed day
                        next_date = brazil_time.date() + timedelta(days=1)
                        if allowed_days:
                            for _ in range(30):  # Safety break
                                if next_date.weekday() in allowed_days:
                                    break
                                next_date += timedelta(days=1)

                        target_brazil = datetime.combine(next_date, daily_start)
                    else:
                        # Day is OK, but Time is OUT
                        if current_time_of_day < daily_start:
                            # Too early today, move forward to start time
                            target_brazil = datetime.combine(brazil_time.date(), daily_start)
                        else:
                            # Too late today, move to tomorrow
                            target_brazil = datetime.combine(brazil_time.date() + timedelta(days=1), daily_start)

                    diff_seconds = (target_brazil - brazil_time).total_seconds()
                    virtual_now_utc += timedelta(seconds=diff_seconds + 1)

            # Create Execution
            try:
                fence_company_job_mutation(db, int(campaign.company_id))
            except CompanyOperationallyBlockedError:
                campaign.status = "CANCELED"
                db.commit()
                return
            execution = WhatsAppCampaignExecution(
                campaign_id=campaign_id,
                contact_id=contact.id,
                status='PENDING',
                scheduled_for=virtual_now_utc
            )
            db.add(execution)

            try:
                # COMMIT IMMEDIATELY to reserve this spot and prevent race conditions
                db.commit()
                db.refresh(execution)
            except IntegrityError:
                # Race condition caught: another worker already inserted this execution
                logger.warning(f"[WhatsAppCampaign] Execution already exists for campaign {campaign_id} and contact {contact.id}. Skipping duplicate.")
                db.rollback()
                continue
            except Exception as e:
                logger.error(f"[WhatsAppCampaign] Error creating execution: {e}")
                db.rollback()
                continue

            # Queue only while the committed execution remains pending under
            # the company operational-access fence.
            try:
                enqueued, _ = enqueue_company_job_if_active(
                    db,
                    int(campaign.company_id),
                    is_still_pending=lambda: bool(
                        db.query(WhatsAppCampaignExecution.id)
                        .filter(
                            WhatsAppCampaignExecution.id == execution.id,
                            WhatsAppCampaignExecution.status == "PENDING",
                        )
                        .first()
                        and db.query(WhatsAppCampaign.id)
                        .filter(
                            WhatsAppCampaign.id == campaign.id,
                            WhatsAppCampaign.status == "PROCESSING",
                        )
                        .first()
                    ),
                    enqueue=lambda: send_single_message_task.apply_async(
                        args=[execution.id],
                        eta=virtual_now_utc,
                    ),
                )
            except CompanyOperationallyBlockedError:
                enqueued = False
            if not enqueued:
                logger.info(
                    "[WhatsAppCampaign] Execution cancelled before enqueue execution_id=%s",
                    execution.id,
                )
                return

            queued_count += 1

            # Increment delay randomly between min and max (in seconds)
            step = random.uniform(min_delay_seconds, max_delay_seconds)
            virtual_now_utc += timedelta(seconds=step)

        # Final update not really needed for executions, but maybe for campaign status if we changed it at start
        # (We already updated total_contacts at start)

        total_duration_seconds = (virtual_now_utc - datetime.utcnow()).total_seconds()
        total_minutes = total_duration_seconds / 60
        logger.info(f"[WhatsAppCampaign] Queued {queued_count} messages. Campaign will end approx in {total_minutes:.1f} minutes.")

    except Exception as e:
        logger.error(f"[WhatsAppCampaign] Error processing campaign {campaign_id}: {e}", exc_info=True)
        try:
            if 'campaign' in locals() and campaign:
                campaign.status = 'FAILED'
                db.commit()
        except:
            pass
    finally:
        db.close()


@app.task(bind=True, max_retries=3)
def send_single_message_task(self, execution_id: int):
    """
    Send a single WhatsApp message for a campaign execution.
    Uses waha_utils.send_text_to_waha()
    """
    logger.info(f"[WhatsAppCampaign] Executing task for execution_id: {execution_id}")
    db = SessionLocal()
    try:
        # === ATOMIC CLAIM: Prevent race condition ===
        # Use atomic UPDATE to claim this execution. Only ONE worker can succeed.
        # This prevents multiple workers from processing the same execution simultaneously.
        from sqlalchemy import update

        result = db.execute(
            update(WhatsAppCampaignExecution)
            .where(WhatsAppCampaignExecution.id == execution_id)
            .where(WhatsAppCampaignExecution.status == 'PENDING')
            .values(status='PROCESSING')
        )
        db.commit()

        if result.rowcount == 0:
            # Another worker already claimed this execution
            logger.info(f"[WhatsAppCampaign] Execution {execution_id} already claimed by another worker. Skipping.")
            return

        logger.info(f"[WhatsAppCampaign] Successfully claimed execution {execution_id}")

        # Now load the full execution object with relationships
        execution = db.query(WhatsAppCampaignExecution).options(
            joinedload(WhatsAppCampaignExecution.campaign),
            joinedload(WhatsAppCampaignExecution.contact)
        ).get(execution_id)

        if not execution:
            logger.error(f"[WhatsAppCampaign] Execution {execution_id} not found after claim.")
            return

        campaign = execution.campaign
        contact = execution.contact
        from backend.services.company_access_control import is_company_operational
        if not is_company_operational(db, int(campaign.company_id)):
            execution.status = "SKIPPED"
            execution.error_message = "company_access_suspended"
            db.commit()
            return

        # Refresh campaign to check current status
        db.refresh(campaign)

        # Check if campaign was paused/canceled
        if campaign.status in ('PAUSED', 'CANCELED'):
            logger.info(f"[WhatsAppCampaign] Campaign {campaign.id} is {campaign.status}. Skipping message for {contact.phone}")
            execution.status = 'SKIPPED'
            execution.error_message = f'Campaign {campaign.status}'
            db.commit()
            return

        # Get company's WAHA session
        company = db.query(Company).filter(Company.id == campaign.company_id).first()
        if not company or not company.waha_session_name:
            logger.error(f"[WhatsAppCampaign] Company {campaign.company_id} has no WAHA session configured.")
            execution.status = 'FAILED'
            execution.error_message = 'Company has no WAHA session'
            campaign.failed_count = (campaign.failed_count or 0) + 1
            campaign.processed_contacts = (campaign.processed_contacts or 0) + 1
            db.commit()
            return

        # Prepare phone number
        phone = contact.phone
        if phone.startswith('+'):
            phone = phone[1:]  # Remove leading +

        # Send message via WAHA
        try:
            logger.info(f"[WhatsAppCampaign] Sending message to {phone} via WAHA session {company.waha_session_name}")

            # Humanize message to avoid bot detection
            contact_name = contact.name if contact else None

            # First, replace strict variables
            personalized_message = replace_message_variables(campaign.message_text, contact_name)

            # Then humanize (LLM will see the name already inserted)
            humanized_message = humanize_message(
                personalized_message,
                contact_name,
                db=db,
                company_id=campaign.company_id,
            )
            logger.info(f"[WhatsAppCampaign] Original: {campaign.message_text[:50]}... | Personalized: {personalized_message[:50]}... | Humanized: {humanized_message[:50]}...")

            result = send_text_to_waha(
                waha_session_name=company.waha_session_name,
                phone=phone,
                message=humanized_message,
                company_id=campaign.company_id
            )

            # Extract message ID from response
            waha_message_id = result.get('id') if result else None

            # Update execution
            execution.status = 'SENT'
            execution.waha_message_id = waha_message_id
            execution.sent_at = func.now()

            # Update campaign counters
            campaign.processed_contacts = (campaign.processed_contacts or 0) + 1
            campaign.success_count = (campaign.success_count or 0) + 1

            db.commit()
            logger.info(f"[WhatsAppCampaign] Execution {execution_id} successful. Message ID: {waha_message_id}")

            # Check for completion
            if campaign.total_contacts > 0 and campaign.processed_contacts >= campaign.total_contacts:
                campaign.status = 'COMPLETED'
                logger.info(f"[WhatsAppCampaign] Campaign {campaign.id} COMPLETED (All {campaign.total_contacts} contacts processed)")
                db.commit()

        except Exception as send_err:
            logger.error(f"[WhatsAppCampaign] Failed to send message for execution {execution_id}: {send_err}")
            execution.status = 'FAILED'
            execution.error_message = str(send_err)[:500]  # Truncate error message
            campaign.failed_count = (campaign.failed_count or 0) + 1
            campaign.processed_contacts = (campaign.processed_contacts or 0) + 1

            # Check for completion even on failure
            if campaign.total_contacts > 0 and campaign.processed_contacts >= campaign.total_contacts:
                campaign.status = 'COMPLETED'
                logger.info(f"[WhatsAppCampaign] Campaign {campaign.id} COMPLETED (All {campaign.total_contacts} contacts processed)")

            db.commit()

            # Retry on transient errors (optional)
            # self.retry(exc=send_err, countdown=60)

            # --- FALLBACK FOR "NO LID FOUND" ---
            # Automatically fix number if WAHA rejects it due to formatting (e.g. extra 9)
            error_msg = str(send_err)
            if "no LID found" in error_msg or "number is not registered" in error_msg:
                logger.warning(f"[WhatsAppCampaign] Attempting to fix number for {phone} using check-exists fallback...")

                try:
                    corrected_chat_id = check_number_exists(company.waha_session_name, phone)

                    if corrected_chat_id and corrected_chat_id != f"{phone}@c.us":
                        logger.info(f"[WhatsAppCampaign] Number corrected! Original: {phone}, New: {corrected_chat_id}")

                        # Strip suffix for consistency if needed, but send_text handles @c.us
                        new_phone = corrected_chat_id

                        logger.info(f"[WhatsAppCampaign] Retrying send with corrected number {new_phone}")

                        # Retrying send
                        result = send_text_to_waha(
                            waha_session_name=company.waha_session_name,
                            phone=new_phone,
                            message=humanized_message,
                            company_id=campaign.company_id
                        )

                        # Success on retry!
                        waha_message_id = result.get('id') if result else None

                        # --- AUTO-UPDATE CONTACT IN DB ---
                        try:
                            clean_new_phone = new_phone.split('@')[0]
                            if clean_new_phone != phone:
                                # Check uniqueness
                                from backend.models import Contact
                                existing = db.query(Contact).filter(
                                    Contact.company_id == campaign.company_id,
                                    Contact.phone == clean_new_phone
                                ).first()

                                if not existing:
                                    logger.info(f"[WhatsAppCampaign] Auto-updating contact {contact.id} phone: {phone} -> {clean_new_phone}")
                                    contact.phone = clean_new_phone
                                    db.add(contact)
                                    db.commit()
                                    # Update local variable for logging/consistency
                                    phone = clean_new_phone
                                else:
                                    logger.warning(f"[WhatsAppCampaign] Contact update skipped: Phone {clean_new_phone} already exists (ID: {existing.id})")
                        except Exception as db_err:
                            logger.error(f"[WhatsAppCampaign] Failed to auto-update contact phone: {db_err}")
                            # Don't rollback the main transaction if possible, or just log.
                            # Since we committed above for campaign status, this might be a new transaction state.
                            # Just log and continue, the message was sent.


                        execution.status = 'SENT'
                        execution.waha_message_id = waha_message_id
                        execution.sent_at = func.now()
                        execution.error_message = f"Fixed: {phone} -> {corrected_chat_id}"

                        # Fix stats (decrement failed, increment success)
                        # NOTE: We partially committed failure above, need to revert the failure count increment ideally
                        # But simpler is to just adjust here or accept double counting logic if not careful.
                        # Actually, failure was NOT committed yet if we caught exception?
                        # Ah, code commits failure inside except block.
                        # Wait, the code structure is inside `try...except Exception as send_err`

                        # Let's adjust counts back
                        campaign.failed_count = max(0, (campaign.failed_count or 1) - 1)
                        # success count already incremented? No, it was skipped.
                        campaign.success_count = (campaign.success_count or 0) + 1

                        # processed contacts is fine (already incremented)

                        db.commit()
                        logger.info(f"[WhatsAppCampaign] Retry successful for {execution_id} with corrected number.")

                except Exception as fallback_err:
                    logger.error(f"[WhatsAppCampaign] Fallback failed for {execution_id}: {fallback_err}")
            # -----------------------------------

    except Exception as e:
        logger.error(f"[WhatsAppCampaign] Error in send_single_message_task {execution_id}: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()
