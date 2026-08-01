import api from './api.ts';

export const FALLBACK_AI_MODELS = [
  'gpt-5.6-sol',
  'gpt-5.6-terra',
  'gpt-5.6-luna',
  'gpt-5.5',
  'gpt-5.5-pro',
  'gpt-5.4-mini',
  'gpt-5.4-nano',
  'gpt-5.4',
  'gpt-5.4-pro',
  'gpt-4o-mini',
] as const;

export interface AIProviderConfig {
  configured: boolean;
  status: string;
  last_validated_at?: string | null;
  last_error?: string | null;
  models: string[];
}

export interface AIProviderUpdatePayload {
  api_key: string;
}

export const getAIProvider = async (): Promise<AIProviderConfig> => {
  const response = await api.get<AIProviderConfig>('/api/ai-provider');
  return response.data;
};

export const updateAIProvider = async (
  payload: AIProviderUpdatePayload,
): Promise<AIProviderConfig> => {
  const response = await api.put<AIProviderConfig>('/api/ai-provider', payload);
  return response.data;
};

export const validateAIProvider = async (): Promise<AIProviderConfig> => {
  const response = await api.post<AIProviderConfig>('/api/ai-provider/validate');
  return response.data;
};

export const deleteAIProvider = async (): Promise<void> => {
  await api.delete('/api/ai-provider');
};
