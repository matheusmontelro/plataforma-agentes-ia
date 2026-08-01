import api, { getLeadsNextTasksBatch } from './api.ts';

// Tipos de dados
export interface Lead {
  id: number;
  client_id?: number;
  company_id?: number;
  name?: string;
  phone?: string;
  created_at?: string;
  data_entrada?: string;
  source_id?: string;
  thumbnail_url?: string;
  sender_lid?: string;
  follow_up_sequence_id?: number;
  pipeline_id?: number;
  current_stage_id?: number;
  pipeline_entered_at?: string;
  last_stage_move_at?: string;
  custom_values?: LeadCustomValue[];
}

export interface LeadCustomValue {
  id: number;
  custom_field_id: number;
  value: any;
  field_name: string;
  field_key: string;
  field_type: string;
}

export interface LeadCustomField {
  id: number;
  company_id: number;
  field_name: string;
  field_key: string;
  field_type: string;
  is_required: boolean;
  default_value?: any;
  validation_rules?: any;
  display_order: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}


export interface LeadPipelineHistory {
  id: number;
  lead_id: number;
  company_id: number;
  from_stage_id?: number;
  to_stage_id: number;
  moved_by_user_id?: number;
  moved_at: string;
  notes?: string;
  time_in_previous_stage?: number;
}

export interface Pipeline {
  id: number;
  company_id: number;
  name: string;
  description?: string;
  is_active: boolean;
  stages?: PipelineStage[];
  created_by_user_id?: number;
  created_at?: string;
  updated_at?: string;
}

export interface PipelineStage {
  id: number;
  pipeline_id: number;
  name: string;
  description?: string;
  color: string;
  order: number;
  is_first_stage: boolean;
  is_converted_stage: boolean;
  is_lost_stage: boolean;
  is_active?: boolean;
  auto_advance_days?: number;
  follow_up_sequence_id?: number;
  percentage_base_stage_id?: number | null;
  created_at?: string;
  updated_at?: string;
}

export interface Column {
  id: string;
  title: string;
  color: string;
  stageId?: number;
  percentageBaseStageId?: number | null;
  pipelineId?: number;
  order: number;
}

// Função para obter IDs do localStorage (baseado no CRM_v3.tsx)
const getAuthIds = () => {
  const clientId = parseInt(localStorage.getItem('client_id') || sessionStorage.getItem('client_id') || '0', 10);
  const companyId = parseInt((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')) || (sessionStorage.getItem('company_id') || sessionStorage.getItem('clinic_id')) || '0', 10);
  const userType = localStorage.getItem('user_type') || sessionStorage.getItem('user_type');

  // Lógica para master_user (como no CRM_v3.tsx)
  const effectiveClientId = (userType === 'master_user')
    ? parseInt(localStorage.getItem('master_client_id') || sessionStorage.getItem('master_client_id') || '0', 10)
    : clientId;

  return { clientId: effectiveClientId, companyId, userType };
};

// API de Leads
export const crmApi = {
  // Listar todos os leads (usa IDs do localStorage)
  async getLeads(stageId?: number): Promise<Lead[]> {
    try {
      const { clientId, companyId } = getAuthIds();

      if (!clientId || !companyId) {
        throw new Error('Informações de autenticação não encontradas');
      }

      // Build URL com trailing slash obrigatório
      let url = `/api/agenda/clients/${clientId}/companies/${companyId}/leads/`;

      // Adicionar query parameters se necessário
      if (stageId) {
        url += `?stage_id=${stageId}`;
      }

      const response = await api.get(url);
      return response.data;
    } catch (error) {
      console.error('Erro ao buscar leads:', error);
      throw error;
    }
  },

  async getCustomFields(): Promise<LeadCustomField[]> {
    try {
      const { clientId, companyId } = getAuthIds();

      if (!clientId || !companyId) {
        throw new Error('Informações de autenticação não encontradas');
      }

      const response = await api.get(
        `/api/agenda/clients/${clientId}/companies/${companyId}/lead-custom-fields/`
      );
      return response.data;
    } catch (error) {
      console.error('Erro ao buscar campos customizados:', error);
      throw error;
    }
  },

  async createCustomField(fieldData: Partial<LeadCustomField>): Promise<LeadCustomField> {
    try {
      const { clientId, companyId } = getAuthIds();

      if (!clientId || !companyId) {
        throw new Error('Informações de autenticação não encontradas');
      }

      const response = await api.post(
        `/api/agenda/clients/${clientId}/companies/${companyId}/lead-custom-fields/`,
        fieldData
      );
      return response.data;
    } catch (error) {
      console.error('Erro ao criar campo customizado:', error);
      throw error;
    }
  },

  async updateCustomField(fieldId: number, fieldData: Partial<LeadCustomField>): Promise<LeadCustomField> {
    try {
      const { clientId, companyId } = getAuthIds();

      if (!clientId || !companyId) {
        throw new Error('Informações de autenticação não encontradas');
      }

      const response = await api.put(
        `/api/agenda/clients/${clientId}/companies/${companyId}/lead-custom-fields/${fieldId}`,
        fieldData
      );
      return response.data;
    } catch (error) {
      console.error('Erro ao atualizar campo customizado:', error);
      throw error;
    }
  },

  async deleteCustomField(fieldId: number): Promise<void> {
    try {
      const { clientId, companyId } = getAuthIds();

      if (!clientId || !companyId) {
        throw new Error('Informações de autenticação não encontradas');
      }

      await api.delete(
        `/api/agenda/clients/${clientId}/companies/${companyId}/lead-custom-fields/${fieldId}`
      );
    } catch (error) {
      console.error('Erro ao deletar campo customizado:', error);
      throw error;
    }
  },

  async updateLeadCustomValues(
    leadId: number,
    customValues: { custom_field_id: number; value: any }[]
  ): Promise<Lead> {
    try {
      const { clientId, companyId } = getAuthIds();

      if (!clientId || !companyId) {
        throw new Error('Informações de autenticação não encontradas');
      }

      const response = await api.put(
        `/api/agenda/clients/${clientId}/companies/${companyId}/leads/${leadId}`,
        { custom_values: customValues }
      );
      return response.data;
    } catch (error) {
      console.error('Erro ao atualizar valores customizados do lead:', error);
      throw error;
    }
  },



  async getLeadHistory(startDate?: string, endDate?: string): Promise<LeadPipelineHistory[]> {
    try {
      const { clientId, companyId } = getAuthIds();

      if (!clientId || !companyId) {
        throw new Error('Informações de autenticação não encontradas');
      }

      let url = `/api/agenda/clients/${clientId}/companies/${companyId}/leads/history`;
      const params = new URLSearchParams();
      if (startDate) params.append('start_date', startDate);
      if (endDate) params.append('end_date', endDate);

      if (params.toString()) {
        url += `?${params.toString()}`;
      }

      const response = await api.get(url);
      return response.data;
    } catch (error) {
      console.error('Erro ao buscar histórico de leads:', error);
      throw error;
    }
  },

  // Criar novo lead (usa IDs do localStorage)
  async createLead(leadData: Partial<Lead>): Promise<Lead> {
    try {
      const { clientId, companyId } = getAuthIds();

      const response = await api.post(
        `/api/agenda/clients/${clientId}/companies/${companyId}/leads/`,
        leadData
      );
      return response.data;
    } catch (error) {
      console.error('Erro ao criar lead:', error);
      throw error;
    }
  },

  // Obter lead específico (usa IDs do localStorage)
  async getLead(leadId: number): Promise<Lead> {
    try {
      const { clientId, companyId } = getAuthIds();

      const response = await api.get(
        `/api/agenda/clients/${clientId}/companies/${companyId}/leads/${leadId}`
      );
      return response.data;
    } catch (error) {
      console.error('Erro ao obter lead:', error);
      throw error;
    }
  },

  // Atualizar lead (usa IDs do localStorage)
  async updateLead(leadId: number, leadData: Partial<Lead>): Promise<Lead> {
    try {
      const { clientId, companyId } = getAuthIds();

      if (!clientId || !companyId) {
        throw new Error('Informações de autenticação não encontradas');
      }

      const response = await api.put(
        `/api/agenda/clients/${clientId}/companies/${companyId}/leads/${leadId}`,
        leadData
      );
      return response.data;
    } catch (error) {
      console.error('Erro ao atualizar lead:', error);
      throw error;
    }
  },

  // Deletar lead (usa IDs do localStorage)
  async deleteLead(leadId: number): Promise<void> {
    try {
      const { clientId, companyId } = getAuthIds();

      if (!clientId || !companyId) {
        throw new Error('Informações de autenticação não encontradas');
      }

      await api.delete(
        `/api/agenda/clients/${clientId}/companies/${companyId}/leads/${leadId}`
      );
    } catch (error) {
      console.error('Erro ao deletar lead:', error);
      throw error;
    }
  },

  // Obter próximas tasks para múltiplos leads
  async getNextTasksBatch(phones: string[]): Promise<any[]> {
    try {
      return await getLeadsNextTasksBatch(phones);

    } catch (error) {
      console.error('Erro ao buscar tasks em lote:', error);
      return [];
    }
  }
};

// Serviços de Pipeline (vamos criar conforme necessário)
export const pipelineApi = {
  // Obter todos os pipelines
  async getPipelines(): Promise<Pipeline[]> {
    try {
      const { clientId, companyId } = getAuthIds();

      if (!clientId || !companyId) {
        throw new Error('Informações de autenticação não encontradas para pipelines');
      }

      const response = await api.get(
        `/api/clients/${clientId}/companies/${companyId}/pipelines`
      );
      return response.data;
    } catch (error) {
      console.error('Erro ao buscar pipelines:', error);
      throw error;
    }
  },

  // Obter estágios de um pipeline
  async getStages(pipelineId: number): Promise<PipelineStage[]> {
    try {
      // O endpoint de pipelines já retorna os estágios
      const pipelines = await this.getPipelines();
      const pipeline = pipelines.find(p => p.id === pipelineId);
      return pipeline ? (pipeline.stages || []) : [];
    } catch (error) {
      console.error('Erro ao buscar estágios:', error);
      throw error;
    }
  },

  // Criar novo estágio
  async createStage(pipelineId: number, stageData: Partial<PipelineStage>): Promise<PipelineStage> {
    try {
      const response = await api.post(
        `/api/pipelines/${pipelineId}/stages`,
        stageData
      );
      return response.data;
    } catch (error) {
      console.error('Erro ao criar estágio:', error);
      throw error;
    }
  },

  // Atualizar estágio existente
  async updateStage(stageId: number, stageData: Partial<PipelineStage>): Promise<PipelineStage> {
    try {
      const response = await api.put(
        `/api/pipelines/stages/${stageId}`,
        stageData
      );
      return response.data;
    } catch (error) {
      console.error('Erro ao atualizar estágio:', error);
      throw error;
    }
  },

  // Excluir estágio
  async deleteStage(pipelineId: number, stageId: number): Promise<void> {
    try {
      await api.delete(
        `/api/pipelines/stages/${stageId}`
      );
    } catch (error) {
      console.error('Erro ao excluir estágio:', error);
      throw error;
    }
  },

  // Reordenar estágios
  async reorderStages(pipelineId: number, stageOrders: { stage_id: number; order: number }[]): Promise<void> {
    try {
      const { clientId, companyId } = getAuthIds();

      await api.put(
        `/api/pipelines/${pipelineId}/stages/reorder`,
        stageOrders
      );
    } catch (error) {
      console.error('Erro ao reordenar estágios:', error);
      throw error;
    }
  },

  // Mover lead para outra etapa
  async moveLeadToStage(
    leadId: number,
    newStageId: number,
    userId?: number,
    notes?: string
  ): Promise<any> {
    try {
      // Verificar se userId é válido (maior que 0)
      const payload: any = { stage_id: newStageId, notes };
      if (userId && userId > 0) {
        payload.moved_by_user_id = userId;
      }

      const response = await api.put(
        `/api/pipelines/leads/${leadId}/move`,
        payload
      );
      return response.data;
    } catch (error) {
      console.error('Erro ao mover lead:', error);
      throw error;
    }
  },

  // Atualizar valor do negócio (para Meta CAPI)
  async updateLeadDealValue(leadId: number, dealValue: number): Promise<Lead> {
    try {
      const { clientId, companyId } = getAuthIds();

      if (!clientId || !companyId) {
        throw new Error('Informações de autenticação não encontradas');
      }

      const response = await api.patch(
        `/api/clients/${clientId}/companies/${companyId}/leads/${leadId}/deal-value`,
        { deal_value: dealValue }
      );
      return response.data;
    } catch (error) {
      console.error('Erro ao atualizar valor do negócio:', error);
      throw error;
    }
  }
};

export default crmApi;
