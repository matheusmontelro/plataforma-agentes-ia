import api from './api.ts';
import { toPublicAppUrl } from '../config/runtime.ts';

export interface WebhookTrigger {
    id: number;
    company_id: number;
    name: string;
    uuid: string;
    description?: string;
    method: string;
    is_active: boolean;
    created_at: string;
    updated_at: string;
    event_count?: number;
    last_event_at?: string | null;
}

export interface WebhookEvent {
    id: number;
    webhook_id?: number | null;
    webhook_name?: string | null;
    webhook_uuid?: string | null;
    method: string;
    status: string;
    status_code: number;
    source_ip?: string | null;
    content_type?: string | null;
    payload_preview?: unknown;
    payload_size?: number | null;
    received_at: string;
}

export interface WebhookTriggerCreate {
    name: string;
    description?: string;
    method?: string;
}

export interface WebhookTriggerUpdate {
    name?: string;
    description?: string;
    method?: string;
    is_active?: boolean;
}

export const getWebhooks = async (): Promise<WebhookTrigger[]> => {
    const response = await api.get('/api/webhooks');
    return response.data;
};

export const getWebhookEvents = async (params: { webhook_id?: number; limit?: number } = {}): Promise<WebhookEvent[]> => {
    const response = await api.get('/api/webhooks/events', { params });
    return response.data;
};

export const createWebhook = async (data: WebhookTriggerCreate): Promise<WebhookTrigger> => {
    const response = await api.post('/api/webhooks', data);
    return response.data;
};

export const updateWebhook = async (id: number, data: WebhookTriggerUpdate): Promise<WebhookTrigger> => {
    const response = await api.put(`/api/webhooks/${id}`, data);
    return response.data;
};

export const deleteWebhook = async (id: number): Promise<void> => {
    await api.delete(`/api/webhooks/${id}`);
};

export const getWebhookUrl = (uuid: string): string => {
    return toPublicAppUrl(`/webhook/trigger/${uuid}`);
};
