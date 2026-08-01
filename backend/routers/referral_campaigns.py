"""
Referral Campaigns Router - CRUD operations for referral campaigns
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Union
from pydantic import BaseModel
from datetime import datetime
import logging

from backend.db import get_db
from backend.models import ReferralCampaign, User, Company, Client
from backend.auth import get_current_user

logger = logging.getLogger(__name__)


router = APIRouter()


# Pydantic models for request/response
class ReferralCampaignCreate(BaseModel):
    company_id: int
    campaign_name: str
    active: bool = True
    referrer_campaign_description: str
    referrer_campaign_instructions: Optional[str] = None
    referee_campaign_description: str
    referee_campaign_instructions: Optional[str] = None
    delay_minutes: int = 5
    max_referrals_per_request: int = 3
    contact_referees_immediately: bool = True
    referee_delay_minutes: int = 10


class ReferralCampaignUpdate(BaseModel):
    campaign_name: Optional[str] = None
    active: Optional[bool] = None
    referrer_campaign_description: Optional[str] = None
    referrer_campaign_instructions: Optional[str] = None
    referee_campaign_description: Optional[str] = None
    referee_campaign_instructions: Optional[str] = None
    delay_minutes: Optional[int] = None
    max_referrals_per_request: Optional[int] = None
    contact_referees_immediately: Optional[bool] = None
    referee_delay_minutes: Optional[int] = None


class ReferralCampaignResponse(BaseModel):
    id: int
    company_id: int
    campaign_name: str
    active: bool
    referrer_campaign_description: str
    referrer_campaign_instructions: Optional[str]
    referee_campaign_description: str
    referee_campaign_instructions: Optional[str]
    delay_minutes: int
    max_referrals_per_request: int
    contact_referees_immediately: bool
    referee_delay_minutes: int
    created_at: Optional[str]
    updated_at: Optional[str]
    created_by: Optional[int]
    company: Optional[dict]

    class Config:
        from_attributes = True


def campaign_to_response(campaign: ReferralCampaign) -> ReferralCampaignResponse:
    """Convert ReferralCampaign model to ReferralCampaignResponse"""
    # Preparar dados da empresa
    company_data = None
    if campaign.company:
        company_data = {
            "id": campaign.company.id,
            "name": campaign.company.name_company or campaign.company.name
        }

    return ReferralCampaignResponse(
        id=campaign.id,
        company_id=campaign.company_id,
        campaign_name=campaign.campaign_name,
        active=campaign.active,
        referrer_campaign_description=campaign.referrer_campaign_description,
        referrer_campaign_instructions=campaign.referrer_campaign_instructions,
        referee_campaign_description=campaign.referee_campaign_description,
        referee_campaign_instructions=campaign.referee_campaign_instructions,
        delay_minutes=campaign.delay_minutes,
        max_referrals_per_request=campaign.max_referrals_per_request,
        contact_referees_immediately=campaign.contact_referees_immediately,
        referee_delay_minutes=campaign.referee_delay_minutes,
        created_at=campaign.created_at.isoformat() if campaign.created_at else None,
        updated_at=campaign.updated_at.isoformat() if campaign.updated_at else None,
        created_by=campaign.created_by,
        company=company_data
    )


@router.get("/referral-campaigns", response_model=List[ReferralCampaignResponse])
async def list_referral_campaigns(
    company_id: Optional[int] = Query(None, description="Filter by company ID"),
    active: Optional[bool] = Query(None, description="Filter by active status"),
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """
    List all referral campaigns with optional filters
    """
    logger.info(f"[REFERRAL_CAMPAIGNS] GET /referral-campaigns - user: {current_user.email}, company_id: {company_id}, active: {active}")
    try:
        query = db.query(ReferralCampaign)

        # Apply filters
        if company_id:
            # Check user permission for company
            if isinstance(current_user, Client):
                # Client (master) has access to all their companies
                # You may want to add validation here if needed
                pass
            else:
                # User needs to have access to the company
                user_companies = [uc.company_id for uc in current_user.user_companies]
                if company_id not in user_companies and current_user.account_type != "admin":
                    raise HTTPException(status_code=403, detail="No permission for this company")
            query = query.filter(ReferralCampaign.company_id == company_id)
        else:
            # Filter by user's companies if not admin
            if isinstance(current_user, Client):
                # Client sees all campaigns from all their companies
                # You may want to filter by client's companies here
                pass
            elif current_user.account_type != "admin":
                user_companies = [uc.company_id for uc in current_user.user_companies]
                query = query.filter(ReferralCampaign.company_id.in_(user_companies))

        if active is not None:
            query = query.filter(ReferralCampaign.active == active)

        campaigns = query.order_by(ReferralCampaign.created_at.desc()).all()
        logger.info(f"[REFERRAL_CAMPAIGNS] Found {len(campaigns)} campaigns")

        result = [campaign_to_response(campaign) for campaign in campaigns]
        logger.info(f"[REFERRAL_CAMPAIGNS] Returning {len(result)} campaigns")
        return result

    except Exception as e:
        logger.error(f"[REFERRAL_CAMPAIGNS] Error listing campaigns: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/referral-campaigns/{campaign_id}", response_model=ReferralCampaignResponse)
async def get_referral_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """
    Get a specific referral campaign by ID
    """
    logger.info(f"[REFERRAL_CAMPAIGNS] GET /referral-campaigns/{campaign_id} - user: {current_user.email}")
    campaign = db.query(ReferralCampaign).filter(ReferralCampaign.id == campaign_id).first()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Check permission
    if isinstance(current_user, Client):
        # Client has access to all their companies
        pass
    else:
        user_companies = [uc.company_id for uc in current_user.user_companies]
        if campaign.company_id not in user_companies and current_user.account_type != "admin":
            raise HTTPException(status_code=403, detail="No permission for this campaign")

    return campaign_to_response(campaign)


@router.post("/referral-campaigns", response_model=ReferralCampaignResponse)
async def create_referral_campaign(
    campaign: ReferralCampaignCreate,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """
    Create a new referral campaign
    """
    logger.info(f"[REFERRAL_CAMPAIGNS] POST /referral-campaigns - user: {current_user.email}, campaign_name: {campaign.campaign_name}, company_id: {campaign.company_id}")
    try:
        # Check permission for company
        if isinstance(current_user, Client):
            # Client has access to all their companies
            pass
        else:
            user_companies = [uc.company_id for uc in current_user.user_companies]
            if campaign.company_id not in user_companies and current_user.account_type != "admin":
                raise HTTPException(status_code=403, detail="No permission for this company")

        # Check if company exists
        company = db.query(Company).filter(Company.id == campaign.company_id).first()
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")

        # Check if there's already an active campaign for this company
        existing_active = db.query(ReferralCampaign).filter(
            ReferralCampaign.company_id == campaign.company_id,
            ReferralCampaign.active == True
        ).first()

        if existing_active and campaign.active:
            # Deactivate existing campaign
            existing_active.active = False
            db.commit()

        # Create new campaign
        new_campaign = ReferralCampaign(
            **campaign.dict(),
            created_by=current_user.id
        )

        db.add(new_campaign)
        db.commit()
        db.refresh(new_campaign)

        return campaign_to_response(new_campaign)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/referral-campaigns/{campaign_id}", response_model=ReferralCampaignResponse)
async def update_referral_campaign(
    campaign_id: int,
    campaign_update: ReferralCampaignUpdate,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """
    Update a referral campaign
    """
    logger.info(f"[REFERRAL_CAMPAIGNS] PUT /referral-campaigns/{campaign_id} - user: {current_user.email}")
    try:
        campaign = db.query(ReferralCampaign).filter(ReferralCampaign.id == campaign_id).first()

        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")

        # Check permission
        if isinstance(current_user, Client):
            # Client has access to all their companies
            pass
        else:
            user_companies = [uc.company_id for uc in current_user.user_companies]
            if campaign.company_id not in user_companies and current_user.account_type != "admin":
                raise HTTPException(status_code=403, detail="No permission for this campaign")

        # If activating this campaign, deactivate others for the same company
        if campaign_update.active == True and not campaign.active:
            db.query(ReferralCampaign).filter(
                ReferralCampaign.company_id == campaign.company_id,
                ReferralCampaign.id != campaign_id
            ).update({"active": False})

        # Update campaign
        update_data = campaign_update.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(campaign, key, value)
        campaign.updated_at = datetime.now()

        db.commit()
        db.refresh(campaign)

        return campaign_to_response(campaign)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/referral-campaigns/{campaign_id}")
async def delete_referral_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """
    Delete a referral campaign
    """
    logger.info(f"[REFERRAL_CAMPAIGNS] DELETE /referral-campaigns/{campaign_id} - user: {current_user.email}")
    try:
        campaign = db.query(ReferralCampaign).filter(ReferralCampaign.id == campaign_id).first()

        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")

        # Check permission
        if isinstance(current_user, Client):
            # Client has access to all their companies
            pass
        else:
            user_companies = [uc.company_id for uc in current_user.user_companies]
            if campaign.company_id not in user_companies and current_user.account_type != "admin":
                raise HTTPException(status_code=403, detail="No permission for this campaign")

        db.delete(campaign)
        db.commit()

        return {"message": "Campaign deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/referral-campaigns/{campaign_id}/toggle")
async def toggle_campaign_status(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    logger.info(f"[REFERRAL_CAMPAIGNS] POST /referral-campaigns/{campaign_id}/toggle - user: {current_user.email}")
    """
    Toggle campaign active status (convenience endpoint)
    """
    try:
        campaign = db.query(ReferralCampaign).filter(ReferralCampaign.id == campaign_id).first()

        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")

        # Check permission
        if isinstance(current_user, Client):
            # Client has access to all their companies
            pass
        else:
            user_companies = [uc.company_id for uc in current_user.user_companies]
            if campaign.company_id not in user_companies and current_user.account_type != "admin":
                raise HTTPException(status_code=403, detail="No permission for this campaign")

        # If activating, deactivate others
        if not campaign.active:
            db.query(ReferralCampaign).filter(
                ReferralCampaign.company_id == campaign.company_id,
                ReferralCampaign.id != campaign_id
            ).update({"active": False})

        # Toggle status
        campaign.active = not campaign.active
        db.commit()
        db.refresh(campaign)

        return {
            "message": f"Campaign {'activated' if campaign.active else 'deactivated'} successfully",
            "campaign": {
                "id": campaign.id,
                "company_id": campaign.company_id,
                "campaign_name": campaign.campaign_name,
                "active": campaign.active,
                "referrer_campaign_description": campaign.referrer_campaign_description,
                "referrer_campaign_instructions": campaign.referrer_campaign_instructions,
                "referee_campaign_description": campaign.referee_campaign_description,
                "referee_campaign_instructions": campaign.referee_campaign_instructions,
                "delay_minutes": campaign.delay_minutes,
                "max_referrals_per_request": campaign.max_referrals_per_request,
                "contact_referees_immediately": campaign.contact_referees_immediately,
                "referee_delay_minutes": campaign.referee_delay_minutes,
                "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
                "updated_at": campaign.updated_at.isoformat() if campaign.updated_at else None,
                "created_by": campaign.created_by
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))