import api from './api.ts';

export interface Flow {
    id: number;
    name: string;
    description?: string;
    is_active: boolean;
    nodes: any[];
    edges: any[];
    viewport: any;
    trigger_webhook_id?: number | null;
    trigger_type?: string; // 'webhook', 'whatsapp', 'appointment', or 'crm_stage'
    trigger_config?: Record<string, any>;
    created_at: string;
    updated_at: string;
}

export interface FlowCreate {
    name: string;
    description?: string;
    is_active?: boolean;
    nodes?: any[];
    edges?: any[];
    viewport?: any;
    trigger_webhook_id?: number | null;
    trigger_type?: string;
    trigger_config?: Record<string, any>;
}

export interface FlowUpdate {
    name?: string;
    description?: string;
    is_active?: boolean;
    nodes?: any[];
    edges?: any[];
    viewport?: any;
    trigger_webhook_id?: number | null;
    trigger_type?: string; // 'webhook', 'whatsapp', 'appointment', or 'crm_stage'
    trigger_config?: Record<string, any>;
}

export const getFlows = async (): Promise<Flow[]> => {
    // Backend route is registered as "/api/flows/" (trailing slash).
    // Calling "/api/flows" triggers a 307 redirect that can resolve to absolute localhost.
    const response = await api.get('/api/flows/');
    return response.data;
};

export const getFlow = async (id: number): Promise<Flow> => {
    const response = await api.get(`/api/flows/${id}`);
    return response.data;
};

export const createFlow = async (data: FlowCreate): Promise<Flow> => {
    const response = await api.post('/api/flows/', data);
    return response.data;
};

export const updateFlow = async (id: number, data: FlowUpdate): Promise<Flow> => {
    const response = await api.put(`/api/flows/${id}`, data);
    return response.data;
};

export const deleteFlow = async (id: number): Promise<void> => {
    await api.delete(`/api/flows/${id}`);
};
