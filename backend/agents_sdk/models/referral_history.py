"""
Referral History Model - Track referrals to avoid repeated requests
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from backend.db import Base

class ReferralHistory(Base):
    """
    Model to track referral history per lead
    Prevents asking for referrals repeatedly
    """
    __tablename__ = 'referral_history'

    id = Column(Integer, primary_key=True)
    lead_phone = Column(String(20), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    campaign_id = Column(Integer, ForeignKey('referral_campaigns.id', ondelete='SET NULL'), nullable=True)
    referrals_count = Column(Integer, default=0)
    referral_names = Column(Text)  # JSON array of names
    last_referral_date = Column(DateTime, index=True)
    created_at = Column(DateTime, default=func.now(), index=True)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('lead_phone', 'company_id', 'campaign_id',
                        name='unique_lead_company_campaign'),
    )

    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'lead_phone': self.lead_phone,
            'company_id': self.company_id,
            'campaign_id': self.campaign_id,
            'referrals_count': self.referrals_count,
            'referral_names': self.referral_names,
            'last_referral_date': self.last_referral_date.isoformat() if self.last_referral_date else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }