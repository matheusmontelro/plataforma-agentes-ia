"""
Campaign Reply Tracker

Utility to track when contacts reply to WhatsApp campaign messages.
"""

import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

logger = logging.getLogger(__name__)


def check_and_mark_campaign_reply(db: Session, company_id: int, phone: str) -> bool:
    """
    Check if the phone number has a pending/sent campaign execution in the last 7 days.
    If yes, mark it as replied.

    Args:
        db: Database session
        company_id: Company ID
        phone: Phone number of the contact (clean format, e.g., "5500000000004")

    Returns:
        True if a campaign reply was marked, False otherwise
    """
    try:
        from backend.models import WhatsAppCampaignExecution, Contact

        # Clean phone number (remove any formatting)
        clean_phone = phone.replace("+", "").replace("-", "").replace(" ", "").replace("@c.us", "")

        # Find contact by phone
        contact = db.query(Contact).filter(
            Contact.company_id == company_id,
            Contact.phone == clean_phone
        ).first()

        if not contact:
            # Try partial match (some systems store with/without country code differently)
            contact = db.query(Contact).filter(
                Contact.company_id == company_id,
                Contact.phone.contains(clean_phone[-11:])  # Last 11 digits (Brazil format)
            ).first()

        if not contact:
            return False

        # Check for campaign executions in the last 7 days that haven't been replied yet
        seven_days_ago = datetime.utcnow() - timedelta(days=7)

        execution = db.query(WhatsAppCampaignExecution).filter(
            WhatsAppCampaignExecution.contact_id == contact.id,
            WhatsAppCampaignExecution.status == 'SENT',
            WhatsAppCampaignExecution.sent_at >= seven_days_ago,
            WhatsAppCampaignExecution.replied_at.is_(None)
        ).order_by(
            WhatsAppCampaignExecution.sent_at.desc()
        ).first()

        if execution:
            execution.replied_at = func.now()
            execution.status = 'REPLIED'  # Update status to REPLIED
            db.commit()

            logger.info(
                f"[CampaignReplyTracker] ✅ Marked reply for campaign execution "
                f"(execution_id={execution.id}, campaign_id={execution.campaign_id}, "
                f"contact={contact.name}, phone={clean_phone})"
            )
            return True

        return False

    except Exception as e:
        logger.error(f"[CampaignReplyTracker] Error checking campaign reply: {e}")
        return False
