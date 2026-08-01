// Referral Campaigns API functions

import api from './api.ts';

export interface ReferralCampaign {
  id?: number;
  company_id: number;
  campaign_name: string;
  active: boolean;
  referrer_campaign_description: string;
  referrer_campaign_instructions?: string;
  referee_campaign_description: string;
  referee_campaign_instructions?: string;
  delay_minutes: number;
  max_referrals_per_request: number;
  contact_referees_immediately: boolean;
  referee_delay_minutes: number;
  created_at?: string;
  updated_at?: string;
  created_by?: number;
  company?: {
    id: number;
    name: string;
  };
}

export interface ReferralCampaignCreate {
  company_id: number;
  campaign_name: string;
  active?: boolean;
  referrer_campaign_description: string;
  referrer_campaign_instructions?: string;
  referee_campaign_description: string;
  referee_campaign_instructions?: string;
  delay_minutes?: number;
  max_referrals_per_request?: number;
  contact_referees_immediately?: boolean;
  referee_delay_minutes?: number;
}

export interface ReferralCampaignUpdate {
  campaign_name?: string;
  active?: boolean;
  referrer_campaign_description?: string;
  referrer_campaign_instructions?: string;
  referee_campaign_description?: string;
  referee_campaign_instructions?: string;
  delay_minutes?: number;
  max_referrals_per_request?: number;
  contact_referees_immediately?: boolean;
  referee_delay_minutes?: number;
}

// Listar campanhas de indicação
export async function getReferralCampaigns(
  companyId?: number,
  active?: boolean
): Promise<ReferralCampaign[]> {
  try {
    const params = new URLSearchParams();
    if (companyId) params.append('company_id', companyId.toString());
    if (active !== undefined) params.append('active', active.toString());

    console.log('[getReferralCampaigns] Fetching campaigns with params:', params.toString());
    const response = await api.get(`/api/referral-campaigns?${params.toString()}`);
    console.log('[getReferralCampaigns] Response:', response.data);
    return response.data;
  } catch (error) {
    console.error('[getReferralCampaigns] Erro:', error);
    if (error.response) {
      console.error('[getReferralCampaigns] Response error:', error.response.data);
      console.error('[getReferralCampaigns] Status:', error.response.status);
    }
    throw error;
  }
}

// Buscar campanha específica
export async function getReferralCampaign(campaignId: number): Promise<ReferralCampaign> {
  try {
    const response = await api.get(`/api/referral-campaigns/${campaignId}`);
    return response.data;
  } catch (error) {
    console.error('[getReferralCampaign] Erro:', error);
    throw error;
  }
}

// Criar nova campanha
export async function createReferralCampaign(
  campaign: ReferralCampaignCreate
): Promise<ReferralCampaign> {
  try {
    console.log('[createReferralCampaign] Creating campaign:', campaign);
    const response = await api.post('/api/referral-campaigns', campaign);
    console.log('[createReferralCampaign] Response:', response.data);
    return response.data;
  } catch (error) {
    console.error('[createReferralCampaign] Erro:', error);
    if (error.response) {
      console.error('[createReferralCampaign] Response error:', error.response.data);
      console.error('[createReferralCampaign] Status:', error.response.status);
    }
    throw error;
  }
}

// Atualizar campanha
export async function updateReferralCampaign(
  campaignId: number,
  campaign: ReferralCampaignUpdate
): Promise<ReferralCampaign> {
  try {
    console.log('[updateReferralCampaign] Updating campaign:', campaignId, campaign);
    const response = await api.put(`/api/referral-campaigns/${campaignId}`, campaign);
    console.log('[updateReferralCampaign] Response:', response.data);
    return response.data;
  } catch (error) {
    console.error('[updateReferralCampaign] Erro:', error);
    if (error.response) {
      console.error('[updateReferralCampaign] Response error:', error.response.data);
      console.error('[updateReferralCampaign] Status:', error.response.status);
    }
    throw error;
  }
}

// Deletar campanha
export async function deleteReferralCampaign(campaignId: number): Promise<void> {
  try {
    await api.delete(`/api/referral-campaigns/${campaignId}`);
  } catch (error) {
    console.error('[deleteReferralCampaign] Erro:', error);
    throw error;
  }
}

// Alternar status ativo/inativo
export async function toggleReferralCampaignStatus(
  campaignId: number
): Promise<{ message: string; campaign: ReferralCampaign }> {
  try {
    const response = await api.post(`/api/referral-campaigns/${campaignId}/toggle`);
    return response.data;
  } catch (error) {
    console.error('[toggleReferralCampaignStatus] Erro:', error);
    throw error;
  }
}

// Export default object with all functions
const referralCampaignApi = {
  getReferralCampaigns,
  getReferralCampaign,
  createReferralCampaign,
  updateReferralCampaign,
  deleteReferralCampaign,
  toggleReferralCampaignStatus
};

export default referralCampaignApi;
