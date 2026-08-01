"""
WhatsApp Campaign Routes - REST API for WhatsApp Marketing Campaigns

Endpoints:
- POST   /api/whatsapp-campaigns/estimate     - Estimate contacts based on tags
- POST   /api/whatsapp-campaigns              - Create new campaign
- GET    /api/whatsapp-campaigns              - List campaigns for company
- GET    /api/whatsapp-campaigns/{id}         - Get campaign details
- POST   /api/whatsapp-campaigns/{id}/start   - Start DRAFT campaign
- POST   /api/whatsapp-campaigns/{id}/pause   - Pause PROCESSING campaign
- DELETE /api/whatsapp-campaigns/{id}         - Delete campaign
- GET    /api/whatsapp-campaigns/{id}/executions - List executions with contact details
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel, Field
from datetime import datetime, time

from backend.db import get_db
from backend.auth import get_current_user
from backend.models import (
    Client, Company, Contact, ContactTag,
    WhatsAppCampaign, WhatsAppCampaignExecution, User
)
from backend.worker.tasks_whatsapp_campaign import process_whatsapp_campaign
from backend.services.company_access_control import (
    CompanyOperationallyBlockedError,
    enqueue_company_job_if_active,
    fence_company_job_mutation,
)

router = APIRouter(prefix="/api/whatsapp-campaigns", tags=["WhatsApp Campaigns"])


# --- Pydantic Models ---

class CampaignCreate(BaseModel):
    name: str
    message_text: str
    tag_ids: List[int]
    exclude_tag_ids: Optional[List[int]] = []
    interval_min: Optional[int] = Field(default=1, ge=1, le=240)
    interval_max: Optional[int] = Field(default=5, ge=1, le=240)
    start_immediately: Optional[bool] = False
    daily_start_time: Optional[str] = "08:00"
    daily_end_time: Optional[str] = "21:00"
    allowed_days: Optional[List[int]] = None  # 0=Monday, 6=Sunday


class CampaignResponse(BaseModel):
    id: int
    name: str
    message_text: str
    status: str
    total_contacts: int
    processed_contacts: int
    success_count: int = 0
    failed_count: int = 0
    interval_min: int
    interval_max: int
    created_at: datetime
    daily_start_time: Optional[time]
    daily_end_time: Optional[time]
    allowed_days: Optional[List[int]]

    class Config:
        from_attributes = True


class EstimateRequest(BaseModel):
    tag_ids: List[int]
    exclude_tag_ids: Optional[List[int]] = []


class ExecutionContactResponse(BaseModel):
    id: int
    contact_id: int
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    status: str
    scheduled_for: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    replied_at: Optional[datetime] = None
    error_message: Optional[str] = None
    waha_message_id: Optional[str] = None

    class Config:
        from_attributes = True


class CampaignAnalyticsResponse(BaseModel):
    campaign_id: int
    campaign_name: str
    status: str
    total_contacts: int
    sent_count: int
    replied_count: int
    reply_rate: float  # Percentual de respostas
    contacts_who_replied: List[dict]  # Lista com nome, telefone, replied_at


# --- Helper Functions ---

def get_company_id_from_user(user: Client, db: Session) -> int:
    """Get company_id from user's client_companies association."""
    from backend.models import ClientCompany

    # Helper to check if user is Client or User
    if hasattr(user, 'company_id') and user.company_id:
        return user.company_id

    client_company = db.query(ClientCompany).filter(
        ClientCompany.client_id == user.id
    ).first()
    if not client_company:
        raise HTTPException(status_code=403, detail="User not associated with any company")
    return client_company.company_id


# --- Endpoints ---

@router.post("/estimate")
def estimate_contacts(
    data: EstimateRequest,
    user: Client = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Estimate number of contacts based on tags."""
    company_id = get_company_id_from_user(user, db)

    if not data.tag_ids:
        return {"count": 0}

    # Query contacts that have ANY of the target tags
    query = db.query(func.count(func.distinct(Contact.id))).join(ContactTag).filter(
        Contact.company_id == company_id,
        ContactTag.tag_id.in_(data.tag_ids)
    )

    if data.exclude_tag_ids:
        # Exclude contacts that have ANY of the excluded tags
        exclude_query = db.query(Contact.id).join(ContactTag).filter(
            ContactTag.tag_id.in_(data.exclude_tag_ids)
        )
        query = query.filter(Contact.id.notin_(exclude_query))

    count = query.scalar() or 0
    return {"count": count}


@router.post("", response_model=CampaignResponse)
def create_campaign(
    campaign_data: CampaignCreate,
    user: Client = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new WhatsApp Marketing Campaign.
    Optionally start it immediately.
    """
    company_id = get_company_id_from_user(user, db)

    # Validate interval
    if campaign_data.interval_min > campaign_data.interval_max:
        raise HTTPException(
            status_code=400,
            detail="interval_min must be less than or equal to interval_max"
        )

    # Check if company has WAHA enabled
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company or not company.waha_session_name:
        raise HTTPException(
            status_code=400,
            detail="Company does not have WAHA configured. Please configure waha_session_name first."
        )

    # Parse time strings
    daily_start = None
    daily_end = None
    if campaign_data.daily_start_time:
        try:
            parts = campaign_data.daily_start_time.split(":")
            daily_start = time(int(parts[0]), int(parts[1]))
        except:
            pass
    if campaign_data.daily_end_time:
        try:
            parts = campaign_data.daily_end_time.split(":")
            daily_end = time(int(parts[0]), int(parts[1]))
        except:
            pass

    # Handle created_by (only if user is a standard User, not Client/Master)
    created_by_id = None
    if isinstance(user, User):
        created_by_id = user.id

    try:
        fence_company_job_mutation(db, company_id)
    except CompanyOperationallyBlockedError as exc:
        raise HTTPException(status_code=423, detail="Acesso da empresa suspenso") from exc

    # Create campaign
    campaign = WhatsAppCampaign(
        company_id=company_id,
        name=campaign_data.name,
        message_text=campaign_data.message_text,
        target_tags=campaign_data.tag_ids,
        excluded_tags=campaign_data.exclude_tag_ids or [],
        interval_min=campaign_data.interval_min,
        interval_max=campaign_data.interval_max,
        daily_start_time=daily_start,
        daily_end_time=daily_end,
        allowed_days=campaign_data.allowed_days,
        status='DRAFT',
        created_by=created_by_id
    )

    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    # Start immediately if requested
    if campaign_data.start_immediately:
        try:
            fence_company_job_mutation(db, company_id)
            campaign.status = 'PROCESSING'
            db.commit()
            enqueued, _ = enqueue_company_job_if_active(
                db,
                company_id,
                is_still_pending=lambda: (
                    db.query(WhatsAppCampaign.status)
                    .filter(WhatsAppCampaign.id == campaign.id)
                    .scalar()
                    == "PROCESSING"
                ),
                enqueue=lambda: process_whatsapp_campaign.delay(campaign.id),
            )
            if not enqueued:
                raise HTTPException(status_code=423, detail="Campanha cancelada por suspensão de acesso")
        except CompanyOperationallyBlockedError as exc:
            raise HTTPException(status_code=423, detail="Acesso da empresa suspenso") from exc

    return campaign


@router.get("", response_model=List[CampaignResponse])
def list_campaigns(
    skip: int = 0,
    limit: int = 20,
    user: Client = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List campaigns for the current company."""
    company_id = get_company_id_from_user(user, db)

    campaigns = db.query(WhatsAppCampaign).filter(
        WhatsAppCampaign.company_id == company_id
    ).order_by(WhatsAppCampaign.created_at.desc()).offset(skip).limit(limit).all()

    return campaigns


@router.get("/{campaign_id}", response_model=CampaignResponse)
def get_campaign(
    campaign_id: int,
    user: Client = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get specific campaign details."""
    company_id = get_company_id_from_user(user, db)

    campaign = db.query(WhatsAppCampaign).filter(
        WhatsAppCampaign.id == campaign_id,
        WhatsAppCampaign.company_id == company_id
    ).first()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    return campaign


@router.get("/{campaign_id}/analytics", response_model=CampaignAnalyticsResponse)
def get_campaign_analytics(
    campaign_id: int,
    user: Client = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get analytics for a campaign - shows who replied.
    """
    company_id = get_company_id_from_user(user, db)

    campaign = db.query(WhatsAppCampaign).filter(
        WhatsAppCampaign.id == campaign_id,
        WhatsAppCampaign.company_id == company_id
    ).first()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Count sent and replied
    sent_count = db.query(func.count(WhatsAppCampaignExecution.id)).filter(
        WhatsAppCampaignExecution.campaign_id == campaign_id,
        WhatsAppCampaignExecution.sent_at.isnot(None)
    ).scalar() or 0

    replied_count = db.query(func.count(WhatsAppCampaignExecution.id)).filter(
        WhatsAppCampaignExecution.campaign_id == campaign_id,
        WhatsAppCampaignExecution.replied_at.isnot(None)
    ).scalar() or 0

    # Get contacts who replied
    replied_executions = db.query(WhatsAppCampaignExecution).filter(
        WhatsAppCampaignExecution.campaign_id == campaign_id,
        WhatsAppCampaignExecution.replied_at.isnot(None)
    ).all()

    contacts_who_replied = []
    for exec in replied_executions:
        contact = db.query(Contact).filter(Contact.id == exec.contact_id).first()
        if contact:
            contacts_who_replied.append({
                "contact_id": contact.id,
                "name": contact.name,
                "phone": contact.phone,
                "replied_at": exec.replied_at.isoformat() if exec.replied_at else None
            })

    reply_rate = (replied_count / sent_count * 100) if sent_count > 0 else 0.0

    return CampaignAnalyticsResponse(
        campaign_id=campaign.id,
        campaign_name=campaign.name,
        status=campaign.status,
        total_contacts=campaign.total_contacts or 0,
        sent_count=sent_count,
        replied_count=replied_count,
        reply_rate=round(reply_rate, 2),
        contacts_who_replied=contacts_who_replied
    )


@router.post("/{campaign_id}/start")
def start_campaign(
    campaign_id: int,
    user: Client = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manually start a DRAFT or PAUSED campaign."""
    company_id = get_company_id_from_user(user, db)

    campaign = db.query(WhatsAppCampaign).filter(
        WhatsAppCampaign.id == campaign_id,
        WhatsAppCampaign.company_id == company_id
    ).first()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.status not in ('DRAFT', 'PAUSED'):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start campaign with status '{campaign.status}'. Must be DRAFT or PAUSED."
        )

    # Check WAHA session
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company or not company.waha_session_name:
        raise HTTPException(
            status_code=400,
            detail="Company does not have WAHA configured."
        )

    try:
        fence_company_job_mutation(db, company_id)
        campaign.status = 'PROCESSING'
        db.commit()
        enqueued, _ = enqueue_company_job_if_active(
            db,
            company_id,
            is_still_pending=lambda: (
                db.query(WhatsAppCampaign.status)
                .filter(WhatsAppCampaign.id == campaign_id)
                .scalar()
                == "PROCESSING"
            ),
            enqueue=lambda: process_whatsapp_campaign.delay(campaign_id),
        )
        if not enqueued:
            raise HTTPException(status_code=423, detail="Campanha cancelada por suspensão de acesso")
    except CompanyOperationallyBlockedError as exc:
        raise HTTPException(status_code=423, detail="Acesso da empresa suspenso") from exc

    return {"message": "Campaign started", "campaign_id": campaign_id}


@router.post("/{campaign_id}/pause")
def pause_campaign(
    campaign_id: int,
    user: Client = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Pause a running campaign."""
    company_id = get_company_id_from_user(user, db)

    campaign = db.query(WhatsAppCampaign).filter(
        WhatsAppCampaign.id == campaign_id,
        WhatsAppCampaign.company_id == company_id
    ).first()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.status != 'PROCESSING':
        raise HTTPException(
            status_code=400,
            detail=f"Cannot pause campaign with status '{campaign.status}'. Must be PROCESSING."
        )

    campaign.status = 'PAUSED'
    db.commit()

    return {"message": "Campaign paused", "campaign_id": campaign_id}


@router.delete("/{campaign_id}")
def delete_campaign(
    campaign_id: int,
    user: Client = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a campaign (only if not currently processing)."""
    company_id = get_company_id_from_user(user, db)

    campaign = db.query(WhatsAppCampaign).filter(
        WhatsAppCampaign.id == campaign_id,
        WhatsAppCampaign.company_id == company_id
    ).first()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.status == 'PROCESSING':
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a campaign that is currently processing. Pause it first."
        )

    db.delete(campaign)
    db.commit()

    return {"message": "Campaign deleted", "campaign_id": campaign_id}


@router.get("/{campaign_id}/executions", response_model=List[ExecutionContactResponse])
def list_campaign_executions(
    campaign_id: int,
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    user: Client = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all executions for a campaign with contact details."""
    company_id = get_company_id_from_user(user, db)

    # Verify campaign belongs to company
    campaign = db.query(WhatsAppCampaign).filter(
        WhatsAppCampaign.id == campaign_id,
        WhatsAppCampaign.company_id == company_id
    ).first()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Query executions with contact info
    query = db.query(WhatsAppCampaignExecution).filter(
        WhatsAppCampaignExecution.campaign_id == campaign_id
    )

    if status_filter:
        query = query.filter(WhatsAppCampaignExecution.status == status_filter)

    executions = query.order_by(
        WhatsAppCampaignExecution.scheduled_for.asc()
    ).offset(skip).limit(limit).all()

    # Build response with contact details
    result = []
    for exec in executions:
        contact = db.query(Contact).filter(Contact.id == exec.contact_id).first()
        result.append(ExecutionContactResponse(
            id=exec.id,
            contact_id=exec.contact_id,
            contact_name=contact.name if contact else None,
            contact_phone=contact.phone if contact else None,
            status=exec.status,
            scheduled_for=exec.scheduled_for,
            sent_at=exec.sent_at,
            replied_at=exec.replied_at,
            error_message=exec.error_message,
            waha_message_id=exec.waha_message_id
        ))

    return result
