import api from './api.ts';

export interface AgentWorkforce {
    id: number;
    company_id: number;
    name: string;
    description?: string | null;
    status: 'draft' | 'active' | 'paused' | string;
    channel: 'whatsapp' | 'webchat' | 'voice' | 'email' | 'instagram' | 'other' | string;
    root_agent_key?: string | null;
    nodes: any[];
    edges: any[];
    viewport: any;
    agent_configs: Record<string, any>;
    settings: Record<string, any>;
    version: number;
    created_at: string;
    updated_at: string;
}

export interface AgentWorkforcePayload {
    name: string;
    description?: string | null;
    status?: string;
    channel?: string;
    root_agent_key?: string | null;
    nodes?: any[];
    edges?: any[];
    viewport?: any;
    agent_configs?: Record<string, any>;
    settings?: Record<string, any>;
}

export interface AgentConfigPreview {
    instructions: string;
    agent_definition: Record<string, any>;
    warnings: string[];
}

export interface AgentVoiceOption {
    provider: 'elevenlabs';
    voice_id: string;
    name: string;
    category?: string | null;
    labels?: Record<string, any>;
    preview_url?: string | null;
}

export interface AgentVoiceOptionsResponse {
    provider: 'elevenlabs';
    voices: AgentVoiceOption[];
    default_voice_id?: string | null;
    model_id: string;
    output_format: string;
    error?: string | null;
}

export interface AgentWorkforceExecutionResult {
    success: boolean;
    response: string;
    error?: string | null;
    tokens_used?: number | null;
    workforce_id?: number;
    workforce_name?: string;
    root_agent_key?: string | null;
    root_agent_name?: string | null;
    handoff_target?: string | null;
    metadata?: Record<string, any>;
}

export const getAgentWorkforces = async (): Promise<AgentWorkforce[]> => {
    const response = await api.get('/api/agent-workforces');
    return response.data;
};

export const createAgentWorkforce = async (data: AgentWorkforcePayload): Promise<AgentWorkforce> => {
    const response = await api.post('/api/agent-workforces', data);
    return response.data;
};

export const updateAgentWorkforce = async (
    id: number,
    data: Partial<AgentWorkforcePayload>
): Promise<AgentWorkforce> => {
    const response = await api.put(`/api/agent-workforces/${id}`, data);
    return response.data;
};

export const deleteAgentWorkforce = async (id: number): Promise<void> => {
    await api.delete(`/api/agent-workforces/${id}`);
};

export const previewAgentConfig = async (data: Record<string, any>): Promise<AgentConfigPreview> => {
    const response = await api.post('/agents-sdk/agent-config/preview', data);
    return response.data;
};

export const listAgentVoiceOptions = async (): Promise<AgentVoiceOptionsResponse> => {
    const response = await api.get('/agents-sdk/voice/voices');
    return response.data;
};

export const runAgentWorkforce = async (
    workforceId: number,
    message: string,
    conversationHistory: Array<Record<string, string>> = [],
    allowInactive = false
): Promise<AgentWorkforceExecutionResult> => {
    const response = await api.post('/api/flows/run-agent-workforce', {
        workforce_id: workforceId,
        message,
        conversation_history: conversationHistory,
        allow_inactive: allowInactive
    });
    return response.data;
};

export const uploadAgentWorkforceKnowledgeFile = async (
    workforceId: number,
    file: File
): Promise<AgentWorkforce> => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await api.post(`/api/agent-workforces/${workforceId}/knowledge/files`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
    });
    return response.data;
};

export const refreshAgentWorkforceKnowledge = async (
    workforceId: number
): Promise<AgentWorkforce> => {
    const response = await api.post(`/api/agent-workforces/${workforceId}/knowledge/refresh`);
    return response.data;
};

export const deleteAgentWorkforceKnowledgeFile = async (
    workforceId: number,
    fileId: string
): Promise<AgentWorkforce> => {
    const response = await api.delete(`/api/agent-workforces/${workforceId}/knowledge/files/${encodeURIComponent(fileId)}`);
    return response.data;
};

export const ingestAgentWorkforceKnowledgeLink = async (
    workforceId: number,
    url: string,
    title?: string
): Promise<AgentWorkforce> => {
    const response = await api.post(`/api/agent-workforces/${workforceId}/knowledge/links`, {
        url,
        title
    });
    return response.data;
};
