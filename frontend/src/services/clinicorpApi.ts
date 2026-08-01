
import  api  from './api.ts'; // Importa a instância axios configurada de api.ts
import { AxiosError } from 'axios'; // Para checagem de tipo de erro se necessário

// --- Interfaces ---

/**
 * Interface para dados básicos da integração retornados por GET /calendar/clinicorp/{id}
 * Contém principalmente as credenciais, sem os detalhes (business/dentist IDs).
 */
// Em src/services/clinicorpApi.ts
export interface ClinicorpIntegrationData {
  username: string | null;
  password?: string | null;
  code_link: string | null;
  subscriber_id: string | null;
  business_id?: number | null;       // <-- ADICIONAR/VERIFICAR
  dentist_person_id?: number | null; // <-- ADICIONAR/VERIFICAR
  message?: string;
}

/**
 * Interface para o payload ao salvar/atualizar as credenciais via PUT /calendar/clinicorp/{id}
 */
export interface ClinicorpIntegrationPayload {
  username?: string;
  password?: string; // Enviado apenas se o usuário digitar uma nova senha
  code_link?: string;
  subscriber_id?: string;
}

/**
 * Interface para um item na lista de Empresas (Businesses) retornada pelo backend.
 */
export interface ClinicorpBusinessItem {
  id: number;
  Name: string; // Campo 'Name' retornado pela API Clinicorp
}

/**
 * Interface para um item na lista de Usuários/Profissionais retornada pelo backend.
 */
export interface ClinicorpUserItem {
  id: number;
  name: string; // <-- Alterado de FullName para name
}

/**
 * Interface para a resposta da rota GET /selectable_details.
 */
export interface SelectableDetailsResponse {
  businesses: ClinicorpBusinessItem[];
  users: ClinicorpUserItem[];
  message?: string | null; // Mensagens de aviso (ex: falha parcial na busca)
}

/**
 * Interface para o payload da rota POST /save_selected_details.
 */
export interface SelectedDetailsPayload {
  business_id: number;
  dentist_person_id: number;
}

/**
 * Interface para uma resposta genérica de sucesso.
 */
export interface SuccessResponse {
  message: string;
}

// --- Helper de Erro (Simplificado) ---
// Você pode usar um handler de erro mais sofisticado ou o global do api.ts
const handleClinicorpApiError = (error: unknown, defaultMessage: string): never => {
    console.error('[ClinicorpAPI Error]', defaultMessage, error);
     if (error instanceof AxiosError && error.response?.data?.detail) {
         // Erro específico retornado pelo FastAPI/Backend
         throw new Error(error.response.data.detail);
     }
     if (error instanceof AxiosError && error.response?.data?.message) {
         // Erro com campo 'message' (ex: vindo da rota de save)
         throw new Error(error.response.data.message);
     }
     // Fallback para erro genérico
    throw new Error(defaultMessage || 'Erro na operação com a API Clinicorp.');
};


// --- Funções API ---

/**
 * Busca a configuração BÁSICA (credenciais) da integração Clinicorp.
 * GET /api/integrations/calendar/clinicorp/{companyId}
 * (Assume que companyId é lido do localStorage internamente pela função ou passado)
 */
export async function getClinicorpIntegration(): Promise<ClinicorpIntegrationData | null> {
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) {
      console.error("[getClinicorpIntegration] company_id não encontrado no localStorage.");
      throw new Error("ID da empresa não encontrado para buscar integração.");
  }

  try {
    const resp = await api.get<ClinicorpIntegrationData>(
        `/api/integrations/calendar/clinicorp/${companyId}`,
        { // Permite tratar 404 como "não encontrado" sem lançar erro
            validateStatus: (status) => (status >= 200 && status < 300) || status === 404,
        }
    );
    if (resp.status === 404) {
        return null; // Indica que não há integração configurada
    }
    // Retorna os dados básicos (username, subscriber_id, etc.)
    return resp.data;
  } catch (error) {
    // Trata outros erros (500, rede, etc.)
    handleClinicorpApiError(error, 'Erro ao obter configuração da integração Clinicorp');
    throw error; // Re-lança para o componente tratar
  }
}

/**
 * Salva (Cria ou Atualiza via PUT) as credenciais da integração Clinicorp.
 * PUT /api/integrations/calendar/clinicorp/{companyId}
 */
export async function saveClinicorpIntegration(payload: ClinicorpIntegrationPayload): Promise<string> {
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) {
      console.error("[saveClinicorpIntegration] company_id não encontrado no localStorage.");
      throw new Error("ID da empresa não encontrado para salvar integração.");
  }

  try {
    // A rota PUT no backend lida com criação ou atualização
    const resp = await api.put<{ message: string }>(`/api/integrations/calendar/clinicorp/${companyId}`, payload);
    // Retorna a mensagem de sucesso do backend
    return resp.data.message || 'Credenciais Clinicorp salvas com sucesso!';
  } catch (error) {
    handleClinicorpApiError(error, 'Erro ao salvar credenciais da integração Clinicorp');
    throw error;
  }
}

/**
 * Deleta a configuração da integração Clinicorp (credenciais e detalhes via cascade).
 * DELETE /api/integrations/calendar/clinicorp/{companyId}
 */
export async function deleteClinicorpIntegration(): Promise<string> {
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) {
      console.error("[deleteClinicorpIntegration] company_id não encontrado no localStorage.");
      throw new Error("ID da empresa não encontrado para deletar integração.");
  }

  try {
    const resp = await api.delete<{ message: string }>(`/api/integrations/calendar/clinicorp/${companyId}`);
    return resp.data.message || 'Integração Clinicorp removida com sucesso!';
  } catch (error) {
    handleClinicorpApiError(error, 'Erro ao deletar integração Clinicorp');
    throw error;
  }
}

/**
 * Busca as listas de Empresas (Businesses) e Usuários (Persons) selecionáveis do Clinicorp.
 * Chamada após salvar as credenciais.
 * GET /api/integrations/clinicorp/{company_id}/selectable_details
 */
export async function getSelectableClinicorpDetails(companyId: number): Promise<SelectableDetailsResponse> {
  if (!companyId) {
    throw new Error("Company ID é necessário para buscar detalhes selecionáveis.");
  }
  try {
    console.log(`[getSelectableClinicorpDetails] Buscando detalhes para companyId: ${companyId}`);
    const resp = await api.get<SelectableDetailsResponse>(
      `/api/integrations/clinicorp/${companyId}/selectable_details`
    );
    console.log('[getSelectableClinicorpDetails] Resposta do backend:', resp.data);
    // Retorna o objeto { businesses: [...], users: [...], message?: "..." }
    return resp.data;
  } catch (error) {
    console.error('[getSelectableClinicorpDetails] Erro ao buscar detalhes selecionáveis:', error);
    handleClinicorpApiError(error, 'Erro ao buscar opções de empresas e profissionais do Clinicorp.');
    throw error;
  }
}

/**
 * Salva os IDs de Business e Dentist Person selecionados pelo usuário no backend.
 * POST /api/integrations/clinicorp/{company_id}/save_selected_details
 */
export async function saveSelectedClinicorpDetails(
    companyId: number,
    payload: SelectedDetailsPayload // { business_id: number, dentist_person_id: number }
): Promise<SuccessResponse> {
  if (!companyId) {
    throw new Error("Company ID é necessário para salvar detalhes selecionados.");
  }
  if (!payload || payload.business_id == null || payload.dentist_person_id == null) {
      // Verifica se os IDs são válidos (não null/undefined)
      throw new Error("É necessário fornecer o ID da empresa e do profissional selecionados.");
  }

  try {
    console.log(`[saveSelectedClinicorpDetails] Salvando IDs para companyId: ${companyId}`, payload);
    const resp = await api.post<SuccessResponse>(
      `/api/integrations/clinicorp/${companyId}/save_selected_details`,
      payload // Envia os IDs selecionados no corpo
    );
    console.log('[saveSelectedClinicorpDetails] Resposta do backend:', resp.data);
    return resp.data; // Retorna { message: "..." }
  } catch (error) {
    console.error('[saveSelectedClinicorpDetails] Erro ao salvar detalhes selecionados:', error);
    handleClinicorpApiError(error, 'Erro ao salvar detalhes selecionados da integração Clinicorp.');
    throw error;
  }
}
