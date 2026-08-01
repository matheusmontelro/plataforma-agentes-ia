import api from './api';

export interface WhatsAppCampaign {
    id: number;
    name: string;
    message_text: string;
    status: 'DRAFT' | 'PROCESSING' | 'COMPLETED' | 'PAUSED' | 'FAILED' | 'CANCELED';
    total_contacts: number;
    processed_contacts: number;
    success_count: number;
    failed_count: number;
    interval_min: number;
    interval_max: number;
    created_at: string;
    daily_start_time?: string;
    daily_end_time?: string;
    allowed_days?: number[];
}

export interface WhatsAppCampaignCreate {
    name: string;
    message_text: string;
    tag_ids: number[];
    exclude_tag_ids?: number[];
    interval_min: number;
    interval_max: number;
    start_immediately?: boolean;
    daily_start_time?: string;
    daily_end_time?: string;
    allowed_days?: number[];
}

export interface WhatsAppCampaignExecution {
    id: number;
    contact_id: number;
    contact_name: string | null;
    contact_phone: string | null;
    status: 'PENDING' | 'SCHEDULED' | 'SENT' | 'FAILED' | 'SKIPPED';
    scheduled_for: string | null;
    sent_at: string | null;
    replied_at: string | null;
    error_message: string | null;
    waha_message_id: string | null;
}

export interface CampaignAnalytics {
    campaign_id: number;
    campaign_name: string;
    status: string;
    total_contacts: number;
    sent_count: number;
    replied_count: number;
    reply_rate: number;
    contacts_who_replied: {
        contact_id: number;
        name: string;
        phone: string;
        replied_at: string;
    }[];
}

export interface EstimateRequest {
    tag_ids: number[];
    exclude_tag_ids?: number[];
}

export const listWhatsAppCampaigns = async (): Promise<WhatsAppCampaign[]> => {
    const response = await api.get<WhatsAppCampaign[]>('/api/whatsapp-campaigns');
    return response.data;
};

export const getWhatsAppCampaign = async (id: number): Promise<WhatsAppCampaign> => {
    const response = await api.get<WhatsAppCampaign>(`/api/whatsapp-campaigns/${id}`);
    return response.data;
};

export const createWhatsAppCampaign = async (data: WhatsAppCampaignCreate): Promise<WhatsAppCampaign> => {
    const response = await api.post<WhatsAppCampaign>('/api/whatsapp-campaigns', data);
    return response.data;
};

export const startWhatsAppCampaign = async (id: number): Promise<void> => {
    await api.post(`/api/whatsapp-campaigns/${id}/start`);
};

export const pauseWhatsAppCampaign = async (id: number): Promise<void> => {
    await api.post(`/api/whatsapp-campaigns/${id}/pause`);
};

export const deleteWhatsAppCampaign = async (id: number): Promise<void> => {
    await api.delete(`/api/whatsapp-campaigns/${id}`);
};

export const getWhatsAppCampaignExecutions = async (
    id: number,
    status_filter?: string,
    skip: number = 0,
    limit: number = 100
): Promise<WhatsAppCampaignExecution[]> => {
    const params = { status_filter, skip, limit };
    const response = await api.get<WhatsAppCampaignExecution[]>(`/api/whatsapp-campaigns/${id}/executions`, { params });
    return response.data;
};

export const getWhatsAppCampaignAnalytics = async (id: number): Promise<CampaignAnalytics> => {
    const response = await api.get<CampaignAnalytics>(`/api/whatsapp-campaigns/${id}/analytics`);
    return response.data;
};

export const estimateWhatsAppCampaignContacts = async (data: EstimateRequest): Promise<{ count: number }> => {
    const response = await api.post<{ count: number }>('/api/whatsapp-campaigns/estimate', data);
    return response.data;
};
