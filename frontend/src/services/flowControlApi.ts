import api from './api.ts';

const API_BASE = '/api/flow-control';

export interface FlowStatus {
  flow_type: string;
  is_paused: boolean;
  paused_at?: string;
  paused_by?: number;
  pause_reason?: string;
  resumed_at?: string;
  resumed_by?: number;
}

export interface FlowControlUpdate {
  flow_type: string;
  is_paused: boolean;
  pause_reason?: string;
}

export interface FlowControlStats {
  flows: Array<{
    type: string;
    paused: number;
    total: number;
    active: number;
  }>;
  companies_with_paused_flows: number;
  cache_stats: any;
}

export const flowControlApi = {
  /**
   * Obtém o status de todos os fluxos de uma empresa
   */
  async getStatus(companyId: number): Promise<Record<string, FlowStatus>> {
    const response = await api.get(`${API_BASE}/status/${companyId}`);
    return response.data;
  },

  /**
   * Pausa ou retoma um fluxo específico
   */
  async toggleFlow(companyId: number, data: FlowControlUpdate): Promise<any> {
    const response = await api.post(`${API_BASE}/toggle/${companyId}`, data);
    return response.data;
  },

  /**
   * Obtém o histórico de pausas/retomadas
   */
  async getHistory(companyId: number, flowType?: string): Promise<any> {
    const params = flowType ? { flow_type: flowType } : {};
    const response = await api.get(`${API_BASE}/history/${companyId}`, { params });
    return response.data;
  },

  /**
   * Obtém estatísticas gerais do sistema (apenas admins)
   */
  async getStats(): Promise<FlowControlStats> {
    const response = await api.get(`${API_BASE}/stats`);
    return response.data;
  },
};
