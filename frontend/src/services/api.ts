
import axios, { AxiosError, AxiosResponse } from 'axios';
import { formatChatTimestamp } from '../utils/date.ts';
import { getBrowserTimeZone } from '../utils/browserDateTime.ts';
import { getBackendWebSocketBaseUrl, pointsToLocalhost, runtimeConfig } from '../config/runtime.ts';

declare var process: {
  env: {
    [key: string]: string | undefined;
  };
};

// Reuse one refresh request so concurrent 401 responses settle together.
let refreshPromise: Promise<void> | null = null;

// --- MULTI-AGENT API METHODS ---

export async function listAgentConfigs(): Promise<any[]> {
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) throw new Error("Company ID not found");
  const resp = await api.get(`/agent-configs/list/${companyId}`);
  return resp.data;
}

export async function getAgentConfigById(configId: number): Promise<any> {
  const resp = await api.get(`/agent-config/detail/${configId}`);
  return resp.data;
}

export async function deleteAgentConfigById(configId: number): Promise<void> {
  await api.delete(`/agent-config/detail/${configId}`);
}

export async function previewAgentPrompt(payload: any, useAi: boolean = false): Promise<string> {
  const resp = await api.post(`/agent-config/preview-prompt?use_ai=${useAi}`, payload);
  return resp.data.prompt;
}

// -------------------------------


const isDev = runtimeConfig.isDev;
const isLocal = runtimeConfig.isLocalhost;
const forceAbsoluteApiInDev = runtimeConfig.forceAbsoluteApi;
const devProxyTarget = runtimeConfig.devProxyTarget;

export const API_URL = runtimeConfig.apiBaseUrl;

if (isDev && typeof window !== 'undefined') {
  console.info(`[DEV API] mode=${runtimeConfig.apiMode}, API_URL='${API_URL}', proxyTarget=${devProxyTarget}`);
}

// Função auxiliar para determinar MIME type baseado na extensão
function getMimeType(filename: string): string {
  const ext = filename.toLowerCase().split('.').pop() || '';
  const mimeTypes: { [key: string]: string } = {
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'png': 'image/png',
    'gif': 'image/gif',
    'webp': 'image/webp',
    'mp4': 'video/mp4',
    'mov': 'video/quicktime',
    'avi': 'video/x-msvideo',
    'mkv': 'video/x-matroska',
    'webm': 'video/webm',
    'mp3': 'audio/mpeg',
    'wav': 'audio/wav',
    'oga': 'audio/ogg',
    'ogg': 'audio/ogg',
    'opus': 'audio/opus',
    'mpga': 'audio/mpeg'
  };
  return mimeTypes[ext] || 'application/octet-stream';
}

function getResponseHeader(headers: any, name: string, fallback: string): string {
  const value = headers?.[name];
  return typeof value === 'string' ? value : fallback;
}

const api = axios.create({
  baseURL: API_URL,
  headers: {
    Accept: 'application/json',
  },
  withCredentials: true,
  timeout: 240000,
});

axios.defaults.withCredentials = true;

function getCookieValue(name: string): string | null {
  if (typeof document === 'undefined') return null;

  const cookie = document.cookie
    .split('; ')
    .find(row => row.startsWith(`${encodeURIComponent(name)}=`));

  return cookie ? decodeURIComponent(cookie.split('=').slice(1).join('=')) : null;
}

function attachCsrfHeader(config: any) {
  const method = (config.method || 'get').toLowerCase();
  if (['post', 'put', 'patch', 'delete'].includes(method)) {
    const csrfToken = getCookieValue('csrf_token');
    if (csrfToken) {
      config.headers = config.headers || {};
      config.headers['X-CSRF-Token'] = csrfToken;
    }
  }
  return config;
}

axios.interceptors.request.use(attachCsrfHeader);

function legacyApiKeyHeaders(apiKey?: string | null) {
  return apiKey ? { 'X-API-Key': apiKey } : {};
}

const AUTH_STORAGE_KEYS = [
  'token',
  'refresh_token',
  'api_key',
  'user_type',
  'user_team',
  'user_team_data',
  'sidebar_permissions',
  'contact_permissions',
  'user_id',
  'client_id',
  'master_client_id',
  'company_id',
  'user_email',
  'company_whatsapp_config',
  'taskNotifications',
  'taskUnreadCount',
] as const;

const AUTH_CACHE_KEY_PREFIXES = [
  'chat_messages_',
] as const;

function clearAuthStorageArea(storage: Storage) {
  AUTH_STORAGE_KEYS.forEach(key => storage.removeItem(key));
  storage.removeItem('chat_lru_list');
  storage.removeItem('chat_messages_lru_list');

  const cacheKeys: string[] = [];
  for (let i = 0; i < storage.length; i += 1) {
    const key = storage.key(i);
    if (key && AUTH_CACHE_KEY_PREFIXES.some(prefix => key.startsWith(prefix))) {
      cacheKeys.push(key);
    }
  }

  cacheKeys.forEach(key => storage.removeItem(key));
}

export function clearAuthStorage() {
  if (typeof window === 'undefined') return;

  clearAuthStorageArea(window.localStorage);
  clearAuthStorageArea(window.sessionStorage);
}

if (typeof window !== 'undefined') {
  window.localStorage.removeItem('token');
  window.localStorage.removeItem('refresh_token');
  window.localStorage.removeItem('api_key');
  window.localStorage.removeItem('company_whatsapp_config');
  window.sessionStorage.removeItem('token');
  window.sessionStorage.removeItem('refresh_token');
  window.sessionStorage.removeItem('api_key');
  window.sessionStorage.removeItem('company_whatsapp_config');
}

interface PasswordResetResponse {
  message: string;
}

export interface AgendamentoCreate {
  lead_id: number;
  nome?: string;
  phone?: string;
  consulta_data?: string;  // se o backend espera string "DD/MM/YYYY HH:mm"
  midia?: string;
  interesse?: string;
  endereco?: string;
  local_link?: string;
  agenda_id?: number;
  customer_id?: string;
  id_agendamento?: string;
  event_id?: string;
  status?: string;         // se desejar permitir já definir status
}

export type MessageDeliveryStatus = 'sending' | 'sent' | 'delivered' | 'read' | 'played' | 'failed';

export interface MessageReplyPreview {
  id?: string;
  providerMessageId?: string;
  participant?: string;
  body?: string;
  content?: string;
  type?: string;
  senderName?: string;
  hasMedia?: boolean;
}

export interface MessageReaction {
  emoji: string;
  actorId?: string;
  actorPhone?: string;
  fromMe?: boolean;
  messageId?: string;
  timestamp?: string | number;
}

export interface ContactMessageData {
  displayName?: string;
  fullName?: string;
  name?: string;
  organization?: string;
  phone?: string;
  phoneNumber?: string;
  whatsappId?: string;
  phones?: string[];
  vcard?: string;
}

export interface OptimizedMessageObjectContent extends ContactMessageData {
  url?: string;
  mediaPath?: string;
  needsLoading?: boolean;
  duration?: number;
  caption?: string;
  mimeType?: string;
  thumbnailUrl?: string;
  nps_data?: NPSMessageData;
}

// Interface para mensagens recebidas e enviadas
export interface OptimizedMessage {
  id: string;
  type: 'text' | 'audio' | 'video' | 'image' | 'nps' | 'contact';
  content: string | OptimizedMessageObjectContent;
  sender: {
    phone: string;
    name: string;
    photo: string;
  };
  timestamp: string;
  timestampNumber: number;
  fromMe: boolean;
  sequenceNumber?: number;
  status?: MessageDeliveryStatus;
  providerMessageId?: string;
  deliveryAck?: number;
  replyTo?: MessageReplyPreview | null;
  reactions?: MessageReaction[];
}

export interface NPSMessageData {
  question: string;
  nps_id?: number;
  message_id?: string;
  score?: number;
  status: 'sent' | 'answered';
  answered_at?: string;
  campaign_name?: string;
}

// Interfaces para NPS Dashboard
export interface NPSDashboardMetrics {
  period: {
    start_date: string;
    end_date: string;
  };
  metrics: {
    total_sent: number;
    total_answered: number;
    response_rate: number;
    average_score: number;
    nps_score: number;
    distribution: {
      promoters: number;
      passives: number;
      detractors: number;
    };
  };
  score_distribution: {
    "1": number;
    "2": number;
    "3": number;
    "4": number;
    "5": number;
  };
  daily_evolution: Array<{
    date: string;
    sent: number;
    answered: number;
    avg_score: number;
    response_rate: number;
  }>;
  campaigns: Array<{
    name: string;
    total: number;
    answered: number;
    response_rate: number;
    avg_score: number;
  }>;
}

// Interface para paginação de mensagens
export interface MessagePagination {
  totalCount: number;
  hasMore: boolean;
  nextId?: string;
  nextTimestamp?: number;
}

// Resposta da API de mensagens paginadas
export interface PagedMessagesResponse {
  messages: OptimizedMessage[];
  pagination: MessagePagination;
}

// interfaces para UPDATE (com 'id?' opcional)
export interface FollowUpMessageUpdate {
  id?: number;        // <-- opcional
  type: string;
  content: string;
}

export interface FollowUpStepUpdate {
  id?: number;        // <-- opcional
  step_number: number;
  send_after: number;
  send_after_unit: string;
  messages: FollowUpMessageUpdate[];
}

export interface FollowUpSequenceUpdate {
  client_id: string;  // ou number, se for assim no seu backend
  company_id: number;
  name: string;
  description: string;
  steps: FollowUpStepUpdate[];
  linked_stage_id?: number; // Novo campo opcional
}

export interface FollowUpSequenceCreate {
  client_id: string;
  company_id: number;
  name: string;
  description: string;
  steps: FollowUpStepCreate[];
  linked_stage_id?: number;
}

// PeriodTimeConfig: define se está habilitado, e qual o intervalo de tempo
export interface PeriodTimeConfig {
  enabled: boolean;
  start: string;  // ex.: "08:00"
  end: string;    // ex.: "12:00"
}

// Para cada dia, temos 4 períodos (morning, afternoon, night, dawn)
export interface DayTimeConfig {
  morning: {
    enabled: boolean;
    start: string;
    end: string;
  };
  afternoon: {
    enabled: boolean;
    start: string;
    end: string;
  };
  night: {
    enabled: boolean;
    start: string;
    end: string;
  };
  dawn: {
    enabled: boolean;
    start: string;
    end: string;
  };
}

export interface AIResponseWindowsCreate {
  company_id: number;
  timezone: string;
  time_windows: Record<string, DayTimeConfig>;
}

export interface AIResponseWindowsUpdate {
  timezone?: string;
  time_windows?: Record<string, DayTimeConfig>;
}

export interface AIResponseWindowsData {
  id: number;
  company_id: number;
  timezone: string;
  time_windows: {
    [day: string]: {
      morning: { enabled: boolean; start: string; end: string };
      afternoon: { enabled: boolean; start: string; end: string };
      night: { enabled: boolean; start: string; end: string };
      dawn: { enabled: boolean; start: string; end: string };
    }
  }
}

/**
 * Interface que define o payload enviado ao marcar um no-show.
 * Aqui, apenas 'observacao', pois 'nome', 'phone', 'data_agendada'
 * serão preenchidos no backend a partir do Agendamento.
 */
export interface NoShowCreatePayload {
  observacao?: string;
}

/**
 * Interface representando um registro de NoShowEvent retornado pelo backend.
 * Se no backend temos (nome, phone, data_agendada, observacao, etc.),
 * listamos todos aqui:
 */
export interface NoShowEvent {
  id: number;
  client_id: number;
  company_id: number;
  lead_id: number;
  agendamento_id: number;
  nome?: string;                // snapshot do agendamento
  phone?: string;               // snapshot do agendamento
  data_agendada?: string;       // ex.: "2025-02-18T10:00:00Z"
  marcado_em: string;           // data/hora em que foi marcado no-show
  observacao?: string;          // campo texto
}

export interface User {
  id: number;
  email: string;
  name: string;
  role: string;
  company_id: number;
  client_id: number;
  team_id?: number;
  team?: {
    id: number;
    name: string;
    code: string;
  };
  is_active: boolean;
  created_at: string;
}

export type SidebarPermission =
  | 'dashboard'
  | 'crm'
  | 'chat'
  | 'whatsapp'
  | 'follow-up'
  | 'prompt'
  | 'company';

export interface ContactPermissionConfig {
  include_outside_crm: boolean;
  pipeline_stage_ids: number[];
}

export interface TeamPermissionPayload {
  sidebar_permissions: SidebarPermission[];
  contact_permissions: ContactPermissionConfig;
  team?: {
    id: number;
    name: string;
    code: string;
  } | null;
}

export interface UserCreate {
  email: string;
  password: string;
  confirm_password: string; // Agora existe
  name: string;
  role: string;
  company_id: number;
  team_id?: number;
}

export interface UserUpdate {
  email?: string;
  name?: string;
  role?: string;
  company_id?: number;
  team_id?: number;
  is_active?: boolean;
}

// Interfaces para equipes
export interface Team {
  id: number;
  company_id: number;
  name: string;
  code: string;
  description?: string;
  created_at: string;
  updated_at: string;
  user_count?: number;
  sidebar_permissions: SidebarPermission[];
  contact_permissions: ContactPermissionConfig;
  permissions?: TeamPermission[];
}

export interface TeamPermission {
  id: number;
  resource: string;
  permission: string;
  filter_criteria?: any;
}

export interface TeamCreate {
  name: string;
  description?: string;
  sidebar_permissions: SidebarPermission[];
  contact_permissions: ContactPermissionConfig;
}

export type TeamUpdate = Partial<TeamCreate>;

interface FlowProgress {
  current_step: number;
  total_steps: number;
  status: 'SCHEDULED' | 'PROCESSING' | 'SUCCESS' | 'FAILED' | 'CANCELED';
  next_scheduled?: string;
}

export interface Contact {
  id?: number;
  phone: string;
  name: string;
  photo: string;
  lastMessage?: string;
  lastMessageFromMe?: boolean;
  lastMessageStatus?: MessageDeliveryStatus;
  timestamp?: string;
  timestampNumber: number;
  unreadCount: number;
  human_mode?: boolean;
  last_message_at?: Date | string;
  source_id?: string;
  thumbnail_url?: string;
  sender_lid?: string;
  lead_id?: number;
  customer_id?: number;
  // Novos campos do funil
  funnel_stage?: 'lead' | 'agendado' | 'compareceu' | 'faltou' | 'venda';
  funnel_status?: {
    agendamento_id?: number;
    comparecimento_id?: number;
    venda_id?: number;
    no_show_id?: number;
  };
  // Progresso dos fluxos
  flow_progress?: {
    follow_up?: FlowProgress;
    confirmation?: FlowProgress;
    noshow?: FlowProgress;
    pos_consulta?: FlowProgress;
    pos_venda?: FlowProgress;
  };
}

export interface LeadCreate {
  client_id?: string;
  name?: string;
  phone?: string;
  created_at?: string;
  data_entrada?: string; // "2025-01-18 10:00:00", por exemplo
  source_id?: string;
  thumbnail_url?: string;
  sender_lid?: string;
  follow_up_sequence_id?: number;
}

export interface LeadUpdate {
  client_id?: string;
  name?: string;
  phone?: string;
  created_at?: string;
  data_entrada?: string;
  source_id?: string;
  thumbnail_url?: string;
  sender_lid?: string;
  follow_up_sequence_id?: number;
}

// Interface para o retorno de Leads (já existe em seu arquivo, mas fica aqui p/ referência):
export interface Lead {
  id: number;
  client_id?: string;
  name?: string;
  phone?: string;
  created_at?: string;
  company_id?: number;
  data_entrada?: string;
  source_id?: string;
  thumbnail_url?: string;
  sender_lid?: string;
  follow_up_sequence_id?: number;
}

// 1) Defina as interfaces de retorno:

/**
 * Resposta de /metrics/funnel_by_source
 * Exemplo de item retornado:
 * {
 *   fonte: "Meta Ads",
 *   totalLeads: 42
 * }
 */
export interface FunnelBySourceItem {
  fonte: string;       // "Meta Ads", "Orgânico", ou o valor de source_id
  totalLeads: number;
}

/**
 * Resposta de /metrics/timeline
 * Exemplo de item:
 * {
 *   entity_id: 123,
 *   event_date: "2025-03-01T10:00:00Z",
 *   event_type: "novo_lead",
 *   descricao: "João da Silva"
 * }
 */
export interface TimelineEvent {
  entity_id: number;
  event_date: string;
  event_type: string;   // "novo_lead", "agendamento", "comparecimento", etc.
  descricao: string;    // alguma descrição, ex.: nome do lead/cliente
  avatar_url?: string;
  avatar_gender?: 'female' | 'male' | 'neutral';
}

/**
 * Resposta de /metrics/projections
 * Exemplo:
 * {
 *   mes: "2025-03",
 *   diasNoMes: 31,
 *   diaAtual: 2,
 *   leadsSoFar: 20,
 *   leadsProjection: 310,
 *   agendamentosSoFar: 10,
 *   agendamentosProjection: 155,
 *   comparecimentosSoFar: 5,
 *   comparecimentosProjection: 77,
 *   vendasSoFar: 2,
 *   vendasProjection: 31,
 *   faturadoSoFar: 1500,
 *   faturadoProjection: 23250.5
 * }
 */
export interface ProjectionsResponse {
  mes: string;
  diasNoMes: number;
  diaAtual: number;

  stages: {
    [key: string]: {
      soFar: number;
      projection: number;
    };
  };

  faturadoSoFar: number;
  faturadoProjection: number;
}

/**
 * Interface que o backend retorna em /api/metrics/time_between_stages
 */
export interface TimeBetweenStagesResponse {
  leadToAgendamento: number;
  leadToComparecimento: number;
  leadToVenda: number;
}

// Representa o que o endpoint /api/metrics/funnels retorna
export interface FunnelMetricsResponse {
  totalLeads: number;
  totalAgendamentos: number;
  percentAgendamentos: number;
  totalComparecimentos: number;
  percentComparecimentos: number;
  totalVendas: number;
  percentVendas: number;
  valorFaturado: number;
  valorPago: number;          // <-- novo campo
  valorOrcado: number;
  ticketMedio: number;
  boasPraticas: string[];     // array de mensagens de "boas práticas"
}

// Parâmetros de filtro para o funil
export interface FunnelMetricsParams {
  companyId?: number;
  startDate?: string; // 'YYYY-MM-DD'
  endDate?: string;   // 'YYYY-MM-DD'
  fonte?: string;     // Filtro por fonte de mídia
}

// Defina a interface para o Agendamento (ajuste conforme a estrutura real)
export interface AgendamentoResponse {
  id: number;
  client_id: number;
  company_id?: number;
  lead_id: number;
  agendamento_realizado_em: string; // ou Date, dependendo de como você manipula datas
  nome?: string;
  phone?: string;
  consulta_data?: string; // ou Date
  consulta_timezone?: string;
  consulta_data_local?: string;
  consulta_data_display?: string;
  midia?: string;
  interesse?: string;
  endereco?: string;
  local_link?: string;
  agenda_id?: number;
  customer_id?: string;
  id_agendamento?: string;
  event_id?: string;
  status?: string;

  // Novos campos para os status de sincronização
  google_sync_status?: string; // SYNCED, FAILED, CANCELLED, CANCEL_FAILED, NOT_APPLICABLE
  clinicorp_sync_status?: string; // SYNCED, FAILED, CANCELLED, CANCEL_FAILED, NOT_APPLICABLE
}

// Constantes para os estados de sincronização do Google Calendar
export const GOOGLE_SYNC_STATUS = {
  SYNCED: "SYNCED",
  FAILED: "FAILED",
  CANCELLED: "CANCELLED",
  CANCEL_FAILED: "CANCEL_FAILED",
  NOT_APPLICABLE: "NOT_APPLICABLE"
};

// Constantes para os estados de sincronização do Clinicorp
export const CLINICORP_SYNC_STATUS = {
  SYNCED: "SYNCED",
  FAILED: "FAILED",
  CANCELLED: "CANCELLED",
  CANCEL_FAILED: "CANCEL_FAILED",
  NOT_APPLICABLE: "NOT_APPLICABLE"
};

// Se precisar de um tipo para o payload de update:
export interface AgendamentoUpdate {
  lead_id?: number;
  nome?: string;
  phone?: string;
  consulta_data?: string; // se o backend espera string "DD/MM/YYYY HH:mm"
  midia?: string;
  interesse?: string;
  endereco?: string;
  local_link?: string;
  agenda_id?: number;
  customer_id?: string;
  id_agendamento?: string;
  event_id?: string;
  status?: string;
}

export interface Lead {
  id: number;
  client_id?: string;
  name?: string;
  phone?: string;
  created_at?: string;
  company_id?: number;
  data_entrada?: string;       // ou Date, se preferir converter
  source_id?: string;
  thumbnail_url?: string;
  sender_lid?: string;
  follow_up_sequence_id?: number;
}

// Interface completa para leitura (retorno da API)
export interface Comparecimento {
  id: number;
  // Estes campos vêm do banco, mas não podem ser alterados via formulário
  client_id: number;
  company_id?: number;
  lead_id: number;

  agendamento_id: number;
  compareceu_em: string; // ou Date
  nome?: string;
  phone?: string;
  midia?: string;
  interesse?: string;
  tratamento_orcado?: string;
  valor_orcamento?: number;
}

// Interface de criação
// Note que NÃO incluímos client_id, company_id e NÃO *fazemos update* de lead_id
// pois em geral eles são determinados pela URL ou outro fluxo de negócio.
export interface ComparecimentoCreate {
  // se lead_id for realmente necessário durante a criação,
  // mantenha-o — caso ele também não seja editável pelo usuário
  // mas sim determinável pela rota/URL, então retire daqui
  lead_id: number;
  compareceu_em: string; // ou Date
  agendamento_id: number;
  nome?: string;
  phone?: string;
  midia?: string;
  interesse?: string;
  tratamento_orcado?: string;
  valor_orcamento?: number;
}

// Interface de atualização
// Note que aqui NÃO incluímos client_id, company_id e lead_id
// pois não queremos permitir que sejam alterados
export interface ComparecimentoUpdate {
  agendamento_id?: number;
  nome?: string;
  phone?: string;
  midia?: string;
  interesse?: string;
  tratamento_orcado?: string;
  valor_orcamento?: number;
}

/**
 * Interface de Venda, de acordo com seu backend (vendas_routes.py)
 */
export interface Venda {
  id: number;
  client_id: number;
  company_id?: number;
  lead_id: number;
  comparecimento_id: number;
  venda_data: string; // ou Date, se preferir converter no front
  nome?: string;
  phone?: string;
  tratamento_fechado?: string;
  valor_faturado?: number;
  valor_pago?: number;
}

/**
 * Interface para criar uma nova venda (POST)
 */
export interface VendaCreate {
  lead_id: number;
  comparecimento_id: number;
  nome?: string;
  phone?: string;
  tratamento_fechado?: string;
  valor_faturado?: number;
  valor_pago?: number;
  venda_data?: string;  // <== agora podemos enviar a data/hora, caso o backend aceite
}

/**
 * Interface para atualizar uma venda (PUT)
 */
export interface VendaUpdate {
  lead_id?: number;
  comparecimento_id?: number;
  nome?: string;
  phone?: string;
  tratamento_fechado?: string;
  valor_faturado?: number;
  valor_pago?: number;
  venda_data?: string;  // <== idem, se a rota de atualização permitir alterar a data
}

// [NO-SHOW FOLLOW-UP] Interfaces

export interface NoShowMessageUpdate {
  id?: number;        // ID opcional
  type: string;
  content: string;
}

export interface NoShowStepUpdate {
  id?: number;        // ID opcional
  step_number: number;
  send_after: number;
  send_after_unit: string; // "minutes", "hours", "days"
  messages: NoShowMessageUpdate[];
}

// Mensagem de No-Show
export interface NoShowMessageCreate {
  type: string;    // "text" | "image" | "audio" | "video", etc.
  content: string; // texto ou caminho/URL do arquivo
}

// Passo (Step) do No-Show
export interface NoShowStepCreate {
  step_number: number;
  send_after: number;        // 1, 2, 3 ...
  send_after_unit: string;   // "minutes" | "hours" | "days"
  messages: NoShowMessageCreate[];
}

// Criação de uma sequência de No-Show
export interface NoShowFollowUpSequenceCreate {
  company_id: number;
  name: string;
  description: string;
  steps: NoShowStepCreate[];
}

export interface NoShowFollowUpSequenceUpdate {
  company_id: number;
  name: string;
  description: string;
  steps: NoShowStepUpdate[];
}

// Resposta do backend no PUT
export interface NoShowFollowUpSequenceResponse {
  message: string;
  sequence_id: number;
}

// Detalhes de uma sequência de No-Show (retorno do GET)
export interface NoShowFollowUpSequenceDetail {
  id: number;
  company_id: number;
  name: string;
  description: string;
  steps: Array<{
    id: number;
    step_number: number;
    send_after: number;
    send_after_unit: string;
    messages: Array<{
      id: number;
      type: string;
      content: string;
    }>;
  }>;
}

// =========== SCHEDULE CONFIG ===========

export interface DailyRangeNoShow {
  enabled: boolean;
  start: string;
  end: string;
}

export interface NoShowScheduleData {
  [key: string]: DailyRangeNoShow;
}

// Criação de config
export interface NoShowScheduleCreate {
  schedule_data: NoShowScheduleData;
}

// Atualização de config
export interface NoShowScheduleUpdate {
  schedule_data: NoShowScheduleData;
}

// Retorno do GET
export interface NoShowScheduleConfig {
  id: number;
  company_id: number;
  noshow_follow_up_sequence_id: number;
  schedule_data: NoShowScheduleData;
}

interface RefreshResponse {
  refreshed: boolean;
  token_type: string;
}

interface ApiError {
  detail: string;
}

interface MirrorWebhookResponse {
  mirror_webhook_url: string | null;
}

// Models para o TS (exemplo)
// Ajuste conforme o que seu backend espera/retorna

export interface ConfirmationMessageCreate {
  type: string;
  content: string;
}

export interface ConfirmationStepCreate {
  step_number: number;
  send_after: number;
  send_after_unit: string; // "minutes", "hours", "days"
  messages: ConfirmationMessageCreate[];
}

export interface ConfirmationSequenceCreate {
  client_id: string; // ou number, se for o caso
  company_id: number;
  name: string;
  description: string;
  steps: ConfirmationStepCreate[];
}

export interface ConfirmationSequenceResponse {
  message: string;
  sequence_id: number;
}

export interface ConfirmationSequenceDetail {
  id: number;
  client_id: string; // ou number
  company_id: number;
  name: string;
  description: string;
  steps: Array<{
    id: number;
    step_number: number;
    send_after: number;
    send_after_unit: string;
    messages: Array<{
      id: number;
      type: string;
      content: string;
    }>;
  }>;
}

// Para UPDATE (PUT):
export interface ConfirmationMessageUpdate {
  id?: number;        // <--- agora é opcional
  type: string;
  content: string;
}

export interface ConfirmationStepUpdate {
  id?: number;        // <--- opcional
  step_number: number;
  send_after: number;
  send_after_unit: string; // "minutes", "hours", "days"
  messages: ConfirmationMessageUpdate[];
}

export interface ConfirmationSequenceUpdate {
  client_id: string | number;  // depende do backend
  company_id: number;
  name: string;
  description: string;
  steps: ConfirmationStepUpdate[];
}

export interface DailyRange {
  start: string; // ex: "08:00"
  end: string;   // ex: "18:00"
}

export interface ConfirmationScheduleData {
  [key: string]: {
    enabled: boolean;
    start: string;
    end: string;
  };
}

export interface ConfirmationScheduleCreate {
  schedule_data: ConfirmationScheduleData;
}

export interface ConfirmationScheduleUpdate {
  schedule_data: ConfirmationScheduleData;
}

export interface ConfirmationScheduleConfig {
  id: number;
  company_id: number;
  confirmation_sequence_id: number;
  schedule_data: ConfirmationScheduleData;
}

export interface ScheduleDayItem {
  enabled: boolean;
  start: string;
  end: string;
}

export interface ScheduleData {
  [day: string]: ScheduleDayItem;
  // "monday" | "tuesday" | ... se quiser algo mais restrito
}

// Payload para criar uma nova configuração
export interface FollowUpScheduleCreate {
  //follow_up_sequence_id: number; // se necessário
  schedule_data: ScheduleData;
}

// Payload para atualizar configuração existente
export interface FollowUpScheduleUpdate {
  schedule_data: ScheduleData;
}

// Resposta ao obter a configuração
export interface FollowUpScheduleConfig {
  id: number;
  company_id: number;
  follow_up_sequence_id: number;
  schedule_data: ScheduleData;
}

// Tipos base
export interface FollowUpMessageCreate {
  type: string;      // "text" | "image" | "audio" | "video"
  content: string;   // texto ou path do arquivo
}

export interface FollowUpStepCreate {
  step_number: number;
  send_after: number;
  send_after_unit: string; // "days" | "hours" | "minutes"
  messages: FollowUpMessageCreate[];
}

// Interface FollowUpSequenceCreate removida (duplicada). Ver início do arquivo.

// Resposta do backend (simplificada)
export interface FollowUpSequenceResponse {
  sequence_id: number;
  message: string;
}

export interface MessageCreate {
  type: string;
  content: string;
}

export interface StepCreate {
  step_number: number;
  send_after: number;
  send_after_unit: string;
  messages: MessageCreate[];
}

export interface GetFollowUpSequenceDetail {
  id: number;
  client_id: string;
  company_id: number;
  name: string;
  description: string;
  steps: Array<{
    id: number;
    step_number: number;
    send_after: number;
    send_after_unit: string;
    messages: Array<{
      id: number;
      type: string;
      content: string;
    }>;
  }>;
}

export interface Company {
  id: number | string;
  name: string;         // "Razão Social" original?
  cnpj?: string;        // se você quiser deixá-lo opcional
  name_company?: string; // alias para nome customizável
  logo_url?: string;
  mirror_webhook_url?: string;

  // se quiser, inclua mais propriedades que já existem no seu backend
  created_at?: string;
  updated_at?: string;
}

export interface MediaFile {
  id: string;
  file_name: string;
  file_type: string;
  mime_type: string;
  file_size: number;
  relative_path: string;
  created_at: string;
  metadata?: Record<string, any>; // se tiver metadados adicionais
}

export interface SendTextParams {
  phone: string;
  message: string;
  localMessageId?: string;
  replyTo?: MessageReplyPreview;
}

interface LoginResponse {
  token_type: string;
  company_id?: number;
  client_id?: number;
}

export interface SendImageParams {
  phone: string;
  image: string;        // URL ou base64
  caption?: string;
  localMessageId?: string;
  viewOnce?: boolean;
  messageId?: string;
  delayMessage?: number;
}

export interface SendAudioParams {
  phone: string;
  audio: string;        // URL ou base64
  viewOnce?: boolean;
  localMessageId?: string;
  delayMessage?: number;
  delayTyping?: number;
}

export interface SendVideoParams {
  phone: string;
  video: string;        // URL ou base64
  caption?: string;
  localMessageId?: string;
  viewOnce?: boolean;
  messageId?: string;
  delayMessage?: number;
  delayTyping?: number;
  asyncUpload?: boolean;
}

// Tipos de Provider WhatsApp
export type WhatsAppProvider = 'zapi' | 'waha' | 'evolution' | 'wppconnect';

export interface WhatsAppProviderInfo {
  provider: WhatsAppProvider;
  config: any;
  session_name?: string;
}

export interface MessageConfig {
  type: 'text' | 'image' | 'audio' | 'video';
  content: string;
}

export interface FollowUpConfig {
  sendAfter: number;        // em dias, horas ou minutos
  sendAfterUnit: 'days' | 'hours' | 'minutes';
  waitBetween: number;
  waitBetweenUnit: 'days' | 'hours' | 'minutes';
  messages: MessageConfig[]; // limita a 3 msgs/dia, 5 dias total
}

function getAccessToken(): string | null {
  return null;
}

function getRefreshToken(): string | null {
  return null;
}

function setTokens(_accessToken?: string, _refreshToken?: string) {
  // Tokens são mantidos exclusivamente em cookies HttpOnly emitidos pelo backend.
}

async function refreshAccessToken(): Promise<void> {
  try {
    await api.post<RefreshResponse>('/auth/refresh');
  } catch (error) {
    console.error('Falha ao atualizar sessão.');
    if (axios.isAxiosError(error)) {
      const status = error.response?.status;
      // Se for erro de autenticação ou token inválido
      if (status === 401 || status === 422) {
        clearAuthStorage();

        // Verificar se estamos na página de login (raiz)
        if (window.location.pathname !== '/') {
          // Só redireciona se NÃO estivermos na página de login
          window.location.href = '/';
        }
        // Se já estivermos na página de login, não redirecionamos,
        // apenas deixamos a promessa ser rejeitada com o erro para ser tratado no componente Login
      }
    }
    throw error;
  }
}

function getOrStartTokenRefresh(): Promise<void> {
  if (!refreshPromise) {
    refreshPromise = refreshAccessToken().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

// Função helper para tratar erros
const handleApiError = (error: unknown, defaultMessage: string): never => {
  if (axios.isAxiosError(error)) {
    const axiosError = error as AxiosError<ApiError>;
    console.error('Detalhes do erro:', {
      status: axiosError.response?.status,
      statusText: axiosError.response?.statusText,
      data: axiosError.response?.data,
      url: axiosError.config?.url,
      method: axiosError.config?.method,
      headers: axiosError.response?.headers,
    });

    if (axiosError.response?.data?.detail) {
      throw new Error(axiosError.response.data.detail);
    }
  }
  console.error('Erro não esperado:', error);
  throw new Error(defaultMessage);
};

export async function requestPasswordReset(email: string): Promise<string> {
  try {
    const response = await api.post<PasswordResetResponse>(
      '/auth/password-reset/request',
      { email },
      { headers: { 'Content-Type': 'application/json' } },
    );
    return response.data.message;
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const message = error.response?.data?.detail || 'Não foi possível solicitar a redefinição agora.';
      throw new Error(message);
    }
    throw error;
  }
}

export async function confirmPasswordReset(
  token: string,
  newPassword: string,
  confirmPassword: string,
): Promise<string> {
  try {
    const response = await api.post<PasswordResetResponse>(
      '/auth/password-reset/confirm',
      {
        token,
        new_password: newPassword,
        confirm_password: confirmPassword,
      },
      { headers: { 'Content-Type': 'application/json' } },
    );
    return response.data.message;
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const message = error.response?.data?.detail || 'Não foi possível redefinir a senha agora.';
      throw new Error(message);
    }
    throw error;
  }
}

export async function login(
  email: string,
  password: string
): Promise<{
  tokenType: string;
  companyId?: number;
  clientId?: number;
  userType?: string;
  userId?: number;
  userTeam?: string;
  team?: TeamPermissionPayload['team'];
  sidebarPermissions?: SidebarPermission[];
  contactPermissions?: ContactPermissionConfig;
  businessType?: string;
  settings?: Record<string, any>;
}> {
  const formData = new URLSearchParams();
  formData.append('username', email);
  formData.append('password', password);

  try {
    const resp = await api.post('/auth/login', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });

    return {
      tokenType: resp.data.token_type,
      companyId: resp.data.company_id,
      clientId: resp.data.client_id,
      userType: resp.data.user_type,
      userId: resp.data.user_id,
      userTeam: resp.data.user_team,
      team: resp.data.team,
      sidebarPermissions: resp.data.sidebar_permissions || [],
      contactPermissions: resp.data.contact_permissions,
      businessType: resp.data.business_type,
      settings: resp.data.settings,
    };
  } catch (error) {
    // Capturar e traduzir o erro aqui, antes que o interceptor o pegue
    if (axios.isAxiosError(error)) {
      // Se tiver uma mensagem de erro do backend, use-a
      if (error.response?.data?.detail) {
        throw new Error(error.response.data.detail);
      } else if (error.response?.status === 401) {
        throw new Error('Credenciais inválidas. Verifique seu email e senha.');
      }
    }
    // Se não for um erro específico conhecido, repasse o erro original
    throw error;
  }
}

// Interceptor de request para adicionar access_token
api.interceptors.request.use(
  (config) => {
    // In local browser sessions, always prefer Vite proxy for localhost targets.
    // This prevents direct browser calls to localhost:8002 (which fail when backend is remote).
    if (isLocal && !(isDev && forceAbsoluteApiInDev)) {
      if (typeof config.url === 'string') {
        const rewrittenUrl = config.url.replace(/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?/i, '');

        if (rewrittenUrl !== config.url) {
          config.url = rewrittenUrl.startsWith('/') ? rewrittenUrl : `/${rewrittenUrl}`;
          config.baseURL = '';
        }
      }

      if (typeof config.baseURL === 'string' && pointsToLocalhost(config.baseURL)) {
        config.baseURL = '';
      }
    }

    return attachCsrfHeader(config);
  },
  (error) => {
    console.error('Erro no interceptor de requisição.');
    return Promise.reject(error);
  }
);

// Interceptor de resposta para tentar usar refresh_token se receber 401
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    // Auth endpoints must never recursively enter the refresh interceptor.
    if (
      originalRequest.url?.includes('/auth/login')
      || originalRequest.url?.includes('/auth/refresh')
    ) {
      return Promise.reject(error);
    }

    // Evitar loop infinito
    if (originalRequest._retry) {
      return Promise.reject(error);
    }

    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;

      try {
        await getOrStartTokenRefresh();
        return api(originalRequest);
      } catch (refreshError) {
        // 401/422 are handled by refreshAccessToken. Transient failures such
        // as 503 keep the current browser session and can be retried safely.
        return Promise.reject(refreshError);
      }
    }

    return Promise.reject(error);
  }
);

/**
 * Retorna a URL do WebSocket para o chat, lendo token e company_id do localStorage.
 *
 * Se 'phone' não for passado, usaremos "__global__" como phone,
 * permitindo que o backend (e seu manager) tratem como conexão global
 * para receber mensagens de contatos novos ou gerais.
 */
export function getChatWebSocketUrl(phone?: string): string {
  // 1) Lê o company_id do localStorage
  const rawCompanyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!rawCompanyId) {
    throw new Error('company_id ausente no localStorage. Não é possível prosseguir.');
  }

  const companyId = parseInt(rawCompanyId, 10);
  if (!companyId) {
    throw new Error(`company_id inválido (${rawCompanyId}).`);
  }

  // 2) Se nenhum phone foi passado, adotamos um valor “global”
  const finalPhone = phone && phone.trim() !== '' ? phone.trim() : '__global__';

  // 3) Usa a mesma origem do frontend; Vite/Nginx resolvem /ws para o backend.
  const wsBaseUrl = getBackendWebSocketBaseUrl(API_URL);

  // 4) Monta a URL final com query params. O cookie HttpOnly é enviado no handshake.
  return (
    `${wsBaseUrl}/ws/chat` +
    `?company_id=${encodeURIComponent(String(companyId))}` +
    `&phone=${encodeURIComponent(finalPhone)}`
  );
}

// Exemplo adaptado para getMessageHistory()
export async function getMessageHistory(contact_phone: string): Promise<OptimizedMessage[]> {
  try {
    const resp = await api.get(`/webhook/history?contact_phone=${encodeURIComponent(contact_phone)}`);
    // resp.data.messages => array de mensagens, cada uma com type, content, etc.

    // Precisamos transformar as mensagens
    const processed = await Promise.all(resp.data.messages.map(async (m: any) => {
      const messageDate = new Date(m.timestamp);

      let finalContent: string | { url: string; mimeType?: string } = m.content;

      // Se for mídia (imagem, vídeo, áudio) E o backend não trouxer a URL completa,
      // chamamos algo como getMessageMedia() ou fetchFileBlob() para converter path -> BlobURL
      if (m.type === 'image' || m.type === 'video' || m.type === 'audio') {
        // Exemplo: se seu backend exige GET /media/messages/{clientId}/{companyId}/{arquivo}
        // e você tem a função getMessageMedia(content, fromMe)
        try {
          const blobUrl = await getMessageMedia(m.content, m.fromMe);
          finalContent = { url: blobUrl };
        } catch (err) {
          console.error('Erro ao obter mídia do histórico:', err);
        }
      }

      // Para mensagens NPS, processar o conteúdo específico
      if (m.type === 'nps') {
        try {
          if (typeof m.content === 'string') {
            const npsContent = JSON.parse(m.content);
            finalContent = npsContent;
          } else {
            finalContent = m.content;
          }
        } catch (err) {
          console.error('Erro ao processar conteúdo NPS:', err);
          finalContent = m.content;
        }
      }

      return {
        id: m.id.toString(),
        type: m.type,
        content: finalContent,
        sender: {
          phone: m.sender.phone,
          name: m.sender.name,
          photo: m.sender.photo || '',
        },
        timestamp: messageDate.toLocaleTimeString(),
        timestampNumber: messageDate.getTime(),
        fromMe: m.fromMe,
        status: m.status || (m.fromMe ? 'sent' : undefined),
        providerMessageId: m.providerMessageId || m.messageId || undefined,
        deliveryAck: m.deliveryAck ?? undefined,
        replyTo: m.replyTo || null,
        reactions: Array.isArray(m.reactions) ? m.reactions : [],
      };
    }));

    return processed;
  } catch (error) {
    console.error('Erro ao obter histórico de mensagens:', error);
    throw error;
  }
}

export interface ContactsFilters {
  limit?: number;
  offset?: number;
  search?: string;
  unread_only?: boolean;
  show_archived?: boolean;
  archived_only?: boolean;
  funnel_stages?: string[];
  active_flows?: string[];
  history_only?: boolean;
}

export interface PagedContactsResponse {
  contacts: Contact[];
  total: number;
  has_more: boolean;
}



export async function getContacts(filters: ContactsFilters = {}): Promise<PagedContactsResponse> {
  try {
    const rawOwnClientId = localStorage.getItem('client_id');
    const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));

    // Para usuários staff (user), sempre usar o próprio client_id
    // O backend já trata as permissões corretamente
    let finalClientId = rawOwnClientId;

    // Construir query parameters com paginação
    const params = new URLSearchParams({
      client_id: finalClientId || '',
      company_id: companyId || '',
      limit: (filters.limit || 50).toString(),
      offset: (filters.offset || 0).toString()
    });

    if (filters.search) {
      params.append('search', filters.search);
    }
    if (filters.unread_only) {
      params.append('unread_only', 'true');
    }
    if (filters.show_archived) {
      params.append('show_archived', 'true');
    }
    if (filters.archived_only) {
      params.append('archived_only', 'true');
    }
    if (filters.funnel_stages && filters.funnel_stages.length > 0) {
      params.append('funnel_stages', filters.funnel_stages.join(','));
    }
    if (filters.active_flows && filters.active_flows.length > 0) {
      params.append('active_flows', filters.active_flows.join(','));
    }
    if (filters.history_only) {
      params.append('history_only', 'true');
    }

    // Fazemos a requisição GET com paginação
    const resp = await api.get(`/webhook/contacts?${params.toString()}`);
    // resp.data: { contacts: [...] }

    console.log("Dados brutos da API (contacts):", resp.data.contacts);

    // Debug flow_progress
    if (resp.data.contacts && resp.data.contacts.length > 0) {
      const contactsWithFlow = resp.data.contacts.filter((c: any) => c.flow_progress);
      console.log(`📊 ${contactsWithFlow.length}/${resp.data.contacts.length} contatos com flow_progress`);
      if (contactsWithFlow.length > 0) {
        console.log('Exemplo de flow_progress:', contactsWithFlow[0].flow_progress);
      }
    }

    // Mapeamos cada contato retornado
    const contacts = resp.data.contacts.map((c: any) => {
      const lastMessageAt = c.last_message_at ? new Date(c.last_message_at) : null;
      // Se não existir "last_message_at", definimos um "valor" antigo, para ficar no fim da lista
      const timestampNumber = lastMessageAt ? lastMessageAt.getTime() : 0;

      return {
        id: c.id,
        phone: c.phone,
        name: c.name,
        photo: c.photo || '',
        // Agora preenchemos 'lastMessage' com o campo vindo do backend
        lastMessage: c.last_message || '',
        lastMessageFromMe: c.last_message_from_me === true,
        lastMessageStatus: c.last_message_status || undefined,

        // NEW: se a API já retorna unread_count na consulta, incluímos aqui
        unreadCount: c.unread_count ?? 0,

        timestamp: lastMessageAt ? formatChatTimestamp(timestampNumber) : '',
        timestampNumber,
        human_mode: c.human_mode ?? false,
        last_message_at: c.last_message_at,
        source_id: c.source_id,
        thumbnail_url: c.thumbnail_url,
        sender_lid: c.sender_lid,
        lead_id: c.lead_id,
        customer_id: c.customer_id,

        // Novos campos do funil
        funnel_stage: c.funnel_stage || 'lead',
        funnel_status: c.funnel_status || {},

        // Progresso dos fluxos
        flow_progress: c.flow_progress || null
      };
    });

    return {
      contacts,
      total: resp.data.total || contacts.length,
      has_more: resp.data.has_more || false
    };
  } catch (error) {
    console.error('Erro ao obter contatos:', error);
    throw error;
  }
}

export interface ConvertContactToLeadResponse {
  success?: boolean;
  message: string;
  lead_id: number;
}

export async function convertContactToLead(
  contactId: number,
  sourceId = 'Manual'
): Promise<ConvertContactToLeadResponse> {
  const response = await api.post<ConvertContactToLeadResponse>(
    `/webhook/contacts/${contactId}/convert-to-lead`,
    { source_id: sourceId }
  );
  return response.data;
}

// Função de compatibilidade para não quebrar código existente
export async function getContactsLegacy(): Promise<Contact[]> {
  const response = await getContacts({ limit: 1000 }); // Carregar mais para compatibilidade
  return response.contacts;
}

// Funções de arquivamento
export async function archiveContact(phone: string, companyId: number, reason?: string): Promise<any> {
  try {
    console.log(`🗂️ CHECKPOINT: Arquivando contato ${phone} na empresa ${companyId}`);

    const response = await api.put(`/webhook/contacts/${phone}/archive`, {
      reason
    }, {
      params: { company_id: companyId }
    });

    console.log('✅ CHECKPOINT: Contato arquivado com sucesso:', response.data);
    return response.data;
  } catch (error) {
    console.error('❌ Erro ao arquivar contato:', error);
    throw error;
  }
}

export async function unarchiveContact(phone: string, companyId: number): Promise<any> {
  try {
    console.log(`📂 CHECKPOINT: Desarquivando contato ${phone} na empresa ${companyId}`);

    const response = await api.put(`/webhook/contacts/${phone}/unarchive`, {}, {
      params: { company_id: companyId }
    });

    console.log('✅ CHECKPOINT: Contato desarquivado com sucesso:', response.data);
    return response.data;
  } catch (error) {
    console.error('❌ Erro ao desarquivar contato:', error);
    throw error;
  }
}

export async function getContactAuditLog(companyId: number, filters?: {
  contact_id?: number;
  action_type?: string;
  limit?: number;
  offset?: number;
}): Promise<any> {
  try {
    const params = new URLSearchParams({
      company_id: companyId.toString()
    });

    if (filters) {
      if (filters.contact_id) params.append('contact_id', filters.contact_id.toString());
      if (filters.action_type) params.append('action_type', filters.action_type);
      if (filters.limit) params.append('limit', filters.limit.toString());
      if (filters.offset) params.append('offset', filters.offset.toString());
    }

    const response = await api.get(`/webhook/contacts/audit-log?${params.toString()}`);
    return response.data;
  } catch (error) {
    console.error('❌ Erro ao buscar logs de auditoria:', error);
    throw error;
  }
}

export async function getContactsNoHistory(filters: ContactsFilters = {}): Promise<PagedContactsResponse> {
  try {
    const rawOwnClientId = localStorage.getItem('client_id');
    const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));

    // Para usuários staff (user), sempre usar o próprio client_id
    // O backend já trata as permissões corretamente
    let finalClientId = rawOwnClientId;

    // Construir query parameters com paginação para contatos sem histórico
    const params = new URLSearchParams({
      client_id: finalClientId || '',
      company_id: companyId || '',
      limit: (filters.limit || 50).toString(),
      offset: (filters.offset || 0).toString()
    });

    if (filters.search) {
      params.append('search', filters.search);
    }

    // Fazemos a requisição GET para o endpoint específico de contatos sem histórico
    const resp = await api.get(`/webhook/contacts/no-history?${params.toString()}`);

    console.log("Dados brutos da API (contacts no-history):", resp.data.contacts);

    // Mapeamos cada contato retornado
    const contacts = resp.data.contacts.map((c: any) => {
      return {
        id: c.id,
        phone: c.phone,
        name: c.name,
        photo: c.photo || '',
        lastMessage: c.last_message || '',
        lastMessageFromMe: c.last_message_from_me === true,
        lastMessageStatus: c.last_message_status || undefined,
        unreadCount: c.unread_count ?? 0,
        timestamp: '',
        timestampNumber: 0, // Contatos sem histórico têm timestamp 0
        human_mode: c.human_mode ?? false,
        last_message_at: c.last_message_at,
        source_id: c.source_id,
        thumbnail_url: c.thumbnail_url,
        sender_lid: c.sender_lid,
        lead_id: c.lead_id,
        customer_id: c.customer_id,
        funnel_stage: c.funnel_stage || 'lead',
        funnel_status: c.funnel_status || {}
      };
    });

    return {
      contacts,
      total: resp.data.total || contacts.length,
      has_more: resp.data.has_more || false
    };
  } catch (error) {
    console.error('Erro ao obter contatos sem histórico:', error);
    throw error;
  }
}

/**
 * Marca o contato como lido no backend (unread_count = 0).
 */
export async function markContactAsRead(phone: string): Promise<void> {
  try {
    // Descobrir se é 'user' ou 'master'
    const rawOwnClientId = localStorage.getItem('client_id');
    const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));

    if (!companyId) {
      throw new Error("Company ID não encontrado no localStorage");
    }

    // Para usuários staff (user), sempre usar o próprio client_id
    // O backend já trata as permissões corretamente
    let finalClientId = rawOwnClientId;

    // Montar a URL
    // Ex: PUT /webhook/contacts/5500000000002/read?client_id=6&company_id=1
    const url = `/webhook/contacts/${phone}/read?client_id=${finalClientId}&company_id=${companyId}`;
    await api.put(url);
    console.log(`[markContactAsRead] Contato ${phone} marcado como lido no backend.`);
  } catch (error) {
    console.error('[markContactAsRead] Erro ao marcar como lido:', error);
    throw error;
  }
}

/**
 * Converte um contato para cliente
 */
export async function convertContactToCustomer(contactId: number): Promise<void> {
  try {
    await api.post(`/webhook/contacts/${contactId}/convert-to-customer`);
    console.log(`[convertContactToCustomer] Contato ${contactId} convertido para cliente.`);
  } catch (error) {
    console.error('[convertContactToCustomer] Erro ao converter para cliente:', error);
    throw error;
  }
}

// Contact Tasks API
export interface TaskCreate {
  contact_id: number;
  task_type: 'message' | 'call' | 'email' | 'custom';
  title: string;
  description?: string;
  scheduled_for: string;
  reminder_minutes?: number;
  assigned_to?: number;
  priority?: 'low' | 'medium' | 'high' | 'urgent';
  tags?: string[];
  metadata?: any;
}

export interface TaskUpdate {
  task_type?: 'message' | 'call' | 'email' | 'custom';
  title?: string;
  description?: string;
  scheduled_for?: string;
  reminder_minutes?: number;
  assigned_to?: number;
  status?: 'pending' | 'in_progress' | 'completed' | 'canceled';
  priority?: 'low' | 'medium' | 'high' | 'urgent';
  tags?: string[];
  metadata?: any;
}

export interface Task {
  id: number;
  contact_id: number;
  contact_name: string;
  contact_phone: string;
  task_type: 'message' | 'call' | 'email' | 'custom';
  title: string;
  description?: string;
  scheduled_for: string;
  reminder_minutes: number;
  status: 'pending' | 'in_progress' | 'completed' | 'canceled';
  priority: 'low' | 'medium' | 'high' | 'urgent';
  tags?: string[];
  metadata?: any;
  created_at: string;
  updated_at: string;
  created_by: {
    id: number;
    name: string;
    email: string;
  };
  assigned_to?: {
    id: number;
    name: string;
    email: string;
  };
  completed_at?: string;
  completed_by?: {
    id: number;
    name: string;
    email: string;
  };
  comments_count: number;
}

// Get tasks for a contact
export async function getContactTasks(
  contactId: number,
  filters?: {
    status?: string;
    priority?: string;
    task_type?: string;
    assigned_to_me?: boolean;
  }
): Promise<Task[]> {
  try {
    const params = new URLSearchParams();
    if (filters?.status) params.append('status', filters.status);
    if (filters?.priority) params.append('priority', filters.priority);
    if (filters?.task_type) params.append('task_type', filters.task_type);
    if (filters?.assigned_to_me) params.append('assigned_to_me', 'true');

    const response = await api.get(`/api/contacts/${contactId}/tasks?${params.toString()}`);
    return response.data;
  } catch (error) {
    console.error('Error fetching contact tasks:', error);
    handleApiError(error, 'Erro ao buscar tarefas do contato');
    return [];
  }
}

// Create a new task
export async function createTask(contactId: number, taskData: TaskCreate): Promise<Task> {
  try {
    const response = await api.post(`/api/contacts/${contactId}/tasks`, taskData);
    return response.data;
  } catch (error) {
    console.error('Error creating task:', error);
    handleApiError(error, 'Erro ao criar tarefa');
    throw error;
  }
}

// Update a task
export async function updateTask(taskId: number, taskData: TaskUpdate): Promise<Task> {
  try {
    const response = await api.put(`/api/tasks/${taskId}`, taskData);
    return response.data;
  } catch (error) {
    console.error('Error updating task:', error);
    handleApiError(error, 'Erro ao atualizar tarefa');
    throw error;
  }
}

// Complete a task
export async function completeTask(taskId: number): Promise<Task> {
  try {
    const response = await api.post(`/api/tasks/${taskId}/complete`);
    return response.data;
  } catch (error) {
    console.error('Error completing task:', error);
    handleApiError(error, 'Erro ao concluir tarefa');
    throw error;
  }
}

// Delete a task
export async function deleteTask(taskId: number): Promise<void> {
  try {
    await api.delete(`/api/tasks/${taskId}`);
  } catch (error) {
    console.error('Error deleting task:', error);
    handleApiError(error, 'Erro ao excluir tarefa');
    throw error;
  }
}

// Get upcoming tasks
export async function getUpcomingTasks(params?: {
  limit?: number;
  include_overdue?: boolean;
  assigned_to_me?: boolean;
}): Promise<Task[]> {
  try {
    const queryParams = new URLSearchParams();
    if (params?.limit) queryParams.append('limit', params.limit.toString());
    if (params?.include_overdue !== undefined) queryParams.append('include_overdue', params.include_overdue.toString());
    if (params?.assigned_to_me) queryParams.append('assigned_to_me', 'true');

    const response = await api.get(`/api/tasks/upcoming?${queryParams.toString()}`);
    return response.data;
  } catch (error) {
    console.error('Error fetching upcoming tasks:', error);
    handleApiError(error, 'Erro ao buscar próximas tarefas');
    return [];
  }
}

// Notes API Functions
export interface Note {
  id: number;
  contact_id: number;
  contact_name: string;
  contact_phone: string;
  content: string;
  created_at: string;
  updated_at: string;
  created_by: {
    id: number;
    name: string;
    email: string;
    type: string;
  };
}

export interface NoteCreate {
  content: string;
}

export interface NoteUpdate {
  content: string;
}

// Get notes for a contact
export async function getContactNotes(contactPhone: string): Promise<Note[]> {
  try {
    const response = await api.get(`/api/contacts/${contactPhone}/notes`);
    return response.data;
  } catch (error) {
    console.error('Error fetching notes:', error);
    handleApiError(error, 'Erro ao buscar anotações');
    return [];
  }
}

// Create a new note
export async function createNote(contactPhone: string, noteData: NoteCreate): Promise<Note> {
  try {
    const response = await api.post(`/api/contacts/${contactPhone}/notes`, noteData);
    return response.data;
  } catch (error) {
    console.error('Error creating note:', error);
    handleApiError(error, 'Erro ao criar anotação');
    throw error;
  }
}

// Update a note
export async function updateNote(noteId: number, noteData: NoteUpdate): Promise<Note> {
  try {
    const response = await api.put(`/api/notes/${noteId}`, noteData);
    return response.data;
  } catch (error) {
    console.error('Error updating note:', error);
    handleApiError(error, 'Erro ao atualizar anotação');
    throw error;
  }
}

// Delete a note
export async function deleteNote(noteId: number): Promise<void> {
  try {
    await api.delete(`/api/notes/${noteId}`);
  } catch (error) {
    console.error('Error deleting note:', error);
    handleApiError(error, 'Erro ao excluir anotação');
    throw error;
  }
}

// Get all user notes
export async function getAllUserNotes(params?: {
  limit?: number;
  offset?: number;
}): Promise<Note[]> {
  try {
    const queryParams = new URLSearchParams();
    if (params?.limit) queryParams.append('limit', params.limit.toString());
    if (params?.offset) queryParams.append('offset', params.offset.toString());

    const response = await api.get(`/api/notes/all?${queryParams.toString()}`);
    return response.data;
  } catch (error) {
    console.error('Error fetching user notes:', error);
    handleApiError(error, 'Erro ao buscar anotações do usuário');
    return [];
  }
}

// Add comment to task
export async function addTaskComment(taskId: number, comment: string): Promise<any> {
  try {
    const response = await api.post(`/api/tasks/${taskId}/comments`, { comment });
    return response.data;
  } catch (error) {
    console.error('Error adding task comment:', error);
    handleApiError(error, 'Erro ao adicionar comentário');
    throw error;
  }
}

// Get task comments
export async function getTaskComments(taskId: number): Promise<any[]> {
  try {
    const response = await api.get(`/api/tasks/${taskId}/comments`);
    return response.data;
  } catch (error) {
    console.error('Error fetching task comments:', error);
    handleApiError(error, 'Erro ao buscar comentários');
    return [];
  }
}

// Get task statistics
export async function getTaskStatistics(): Promise<any> {
  try {
    const response = await api.get('/api/tasks/statistics');
    return response.data;
  } catch (error) {
    console.error('Error fetching task statistics:', error);
    handleApiError(error, 'Erro ao buscar estatísticas de tarefas');
    return null;
  }
}

export interface TaskNotification {
  type: string;
  message: string;
  count: number;
  tasks: Task[];
}

export async function getPendingNotifications(): Promise<TaskNotification | null> {
  try {
    // Get browser timezone
    const userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;

    const response = await api.get('/api/notifications/pending', {
      headers: {
        'x-timezone': userTimezone
      }
    });
    return response.data;
  } catch (error) {
    console.error('Error fetching pending notifications:', error);
    handleApiError(error, 'Erro ao buscar notificações pendentes');
    return null;
  }
}

export interface AICreditWalletSummary {
  balance_credits: number;
  total_granted_credits: number;
  total_used_credits: number;
  currency: string;
  status: string;
  updated_at?: string | null;
}

export interface AICreditUsageSummary {
  period_days: number;
  today_credits: number;
  period_credits: number;
  month_credits: number;
  text_credits: number;
  audio_credits: number;
  success_events: number;
  failed_events: number;
  last_event_at?: string | null;
}

export interface AICreditSummaryResponse {
  wallet: AICreditWalletSummary;
  usage: AICreditUsageSummary;
}

export interface AICreditUsagePoint {
  date: string;
  text_credits: number;
  audio_credits: number;
  total_credits: number;
}

export interface AICreditUsageResponse {
  period_days: number;
  series: AICreditUsagePoint[];
}

export interface AICreditTransactionUsage {
  operation?: string | null;
  status?: string | null;
  model?: string | null;
  agent_name?: string | null;
  phone_masked?: string | null;
}

export interface AICreditTransactionItem {
  id: number;
  transaction_type: 'debit' | 'credit' | 'refund' | 'adjustment';
  amount_credits: number;
  balance_after: number;
  description?: string | null;
  created_at: string;
  usage?: AICreditTransactionUsage | null;
}

export interface AICreditTransactionsResponse {
  total: number;
  limit: number;
  offset: number;
  items: AICreditTransactionItem[];
}

export async function getAICreditSummary(periodDays = 30): Promise<AICreditSummaryResponse> {
  try {
    const response = await api.get('/api/ai-credits/summary', {
      params: { period_days: periodDays },
    });
    return response.data;
  } catch (error) {
    handleApiError(error, 'Erro ao carregar resumo de créditos de IA');
  }
}

export async function getAICreditUsage(periodDays = 30): Promise<AICreditUsageResponse> {
  try {
    const response = await api.get('/api/ai-credits/usage', {
      params: { period_days: periodDays },
    });
    return response.data;
  } catch (error) {
    handleApiError(error, 'Erro ao carregar consumo de créditos de IA');
  }
}

export async function getAICreditTransactions(params?: {
  limit?: number;
  offset?: number;
  transaction_type?: AICreditTransactionItem['transaction_type'];
}): Promise<AICreditTransactionsResponse> {
  try {
    const response = await api.get('/api/ai-credits/transactions', {
      params,
    });
    return response.data;
  } catch (error) {
    handleApiError(error, 'Erro ao carregar extrato de créditos de IA');
  }
}

export default api;

export async function saveAgentConfig(payload: any): Promise<string> {
  try {
    console.log('Enviando payload de AgentConfig:', payload);    const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
    if (!companyId) {
      console.error('company_id não encontrado no localStorage. Não é possível salvar config.');
      throw new Error('Não foi possível determinar a empresa para salvar as configurações.');
    }

    // Inclua company_id no payload
    payload.company_id = Number(companyId);

    console.log('Payload final com company_id:', payload);

    const headers: HeadersInit = { 'Content-Type': 'application/json' };

    const resp = await api.post('/agent-config', payload, { headers });
    console.log('Resposta AgentConfig:', resp.data);
    return resp.data.message || 'Configurações salvas com sucesso!';
  } catch (error) {
    console.error('Erro ao salvar AgentConfig:', error);
    if (axios.isAxiosError(error)) {
      const message = error.response?.data?.detail || 'Erro ao salvar configurações do agente.';
      throw new Error(message);
    }
    throw error;
  }
}

export interface CompanyInfo {
  id: number;
  name: string;
  name_company: string | null;
  logo_url: string | null;
  plan?: {
    id: number;
    name: string;
    price: number;
    features: any;
  } | null;
}

export interface AccountBillingProfile {
  full_name: string;
  email: string;
  cellphone: string;
  document: string;
  postal_code: string;
  street: string;
  number: string;
  neighborhood: string;
  complement: string;
  state: string;
  profile_picture_url: string;
}

export interface AccountProfile {
  id: number;
  email: string;
  billing_profile: AccountBillingProfile;
  profile_complete: boolean;
}

export type AccountBillingProfileUpdate = Partial<AccountBillingProfile>;

export interface CompanyWhatsAppConfig {
  zapi_instance_id?: string;
  waha_enabled?: boolean;
  waha_session_name?: string;
  evolution_instance_id?: string;
  wppconnect_session_name?: string;
}

export interface ExtendedCompanyInfo extends CompanyInfo {
  whatsapp_config?: CompanyWhatsAppConfig;
}

export async function getCompanyInfo(): Promise<CompanyInfo> {
  try {
    const resp = await api.get('/api/company');
    console.log('Dados retornados da empresa:', resp.data);
    const data = resp.data.company;
    const finalName = ''; // Opcional caso não venha do backend
    const finalNameCompany = typeof data.name_company === 'string' ? data.name_company : null;
    const finalLogo = typeof data.logo_url === 'string' ? data.logo_url : null;

    return {
      id: data.id,
      name: finalName,
      name_company: finalNameCompany,
      logo_url: finalLogo,
      plan: data.plan, // ✅ Incluindo plano na resposta
    };
  } catch (error) {
    handleApiError(error, 'Erro ao obter informações da empresa');
    // Aqui, para satisfazer o TS que requer um retorno, precisamos lançar ou retornar algo.
    throw new Error('Unreachable');
  }
}

export async function getAccountProfile(): Promise<AccountProfile> {
  try {
    const resp = await api.get<AccountProfile>('/api/account/profile');
    return resp.data;
  } catch (error) {
    handleApiError(error, 'Erro ao obter perfil da conta');
    throw new Error('Unreachable');
  }
}

export async function updateAccountProfile(profile: AccountBillingProfileUpdate): Promise<AccountProfile> {
  try {
    const resp = await api.put<AccountProfile>('/api/account/profile', profile);
    return resp.data;
  } catch (error) {
    handleApiError(error, 'Erro ao atualizar perfil da conta');
    throw new Error('Unreachable');
  }
}

export async function uploadAccountProfilePhoto(photo: File): Promise<AccountProfile> {
  try {
    const formData = new FormData();
    formData.append('photo', photo);
    const resp = await api.post<AccountProfile>('/api/account/profile/photo', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return resp.data;
  } catch (error) {
    handleApiError(error, 'Erro ao atualizar foto do perfil');
    throw new Error('Unreachable');
  }
}

export async function getExtendedCompanyInfo(): Promise<ExtendedCompanyInfo> {
  try {
    const resp = await api.get('/api/company/extended');
    console.log('[ExtendedCompanyInfo] Dados completos da empresa:', resp.data);

    // O backend retorna os dados diretamente, não aninhados em 'company'
    const data = resp.data;

    console.log('[ExtendedCompanyInfo] whatsapp_config:', data.whatsapp_config);
    console.log('[ExtendedCompanyInfo] waha_enabled:', data.whatsapp_config?.waha_enabled);
    console.log('[ExtendedCompanyInfo] waha_session_name:', data.whatsapp_config?.waha_session_name);

    const finalName = ''; // Opcional caso não venha do backend
    const finalNameCompany = typeof data.name_company === 'string' ? data.name_company : null;
    const finalLogo = typeof data.logo_url === 'string' ? data.logo_url : null;

    const result = {
      id: data.id,  // 🔥 INCLUIR O ID DA EMPRESA
      name: finalName,
      name_company: finalNameCompany,
      logo_url: finalLogo,
      whatsapp_config: data.whatsapp_config || {}
    };

    console.log('[ExtendedCompanyInfo] Retornando:', result);
    return result;
  } catch (error) {
    handleApiError(error, 'Erro ao obter informações completas da empresa');
    throw new Error('Unreachable');
  }
}

export async function updateCompanyInfo(name_company: string, file?: File): Promise<string> {
  try {
    const formData = new FormData();
    formData.append('name_company', name_company);
    if (file) {
      formData.append('logo', file);
    }

    console.log('Enviando atualização da empresa:', { name_company, file });
    const resp = await api.put('/api/company', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    console.log('Resposta atualização empresa:', resp.data);
    return resp.data.message || 'Configurações da empresa atualizadas com sucesso!';
  } catch (error) {
    console.error('Erro ao atualizar empresa:', error);
    handleApiError(error, 'Erro ao atualizar configurações da empresa');
    throw new Error('Unreachable');
  }
}

/**
 * Deleta (reseta) as informações da empresa (name_company, logo_url).
 * DELETE /api/company
 */
export async function deleteCompanyInfo(): Promise<string> {

  try {
    const resp = await api.delete('/api/company');
    // A resposta deve conter algo como { message: "...sucesso..." }
    return resp.data.message || 'Nome e logo da empresa removidos com sucesso!';
  } catch (error) {
    console.error('Erro ao remover as informações da empresa:', error);
    handleApiError(error, 'Erro ao remover as informações da empresa');
    throw new Error('Unreachable');
  }
}

// Função para obter configurações do agente
// Função para obter configurações do agente
export async function getAgentConfig(): Promise<any> {
  console.log('%c[AgentConfig] Iniciando getAgentConfig...', 'color: #2e86c1; font-weight: bold;');

  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  console.log('%c[AgentConfig] companyId obtido do localStorage:', 'color: #2e86c1;', companyId);

  if (!companyId) {
    console.error('%c[AgentConfig] company_id não encontrado no localStorage ao tentar obter config do agente.', 'color: red;');
    throw new Error('Não foi possível determinar a empresa para obter as configurações.');
  }

  try {
    console.log(`%c[AgentConfig] Realizando GET em /agent-config/${companyId}`, 'color: #2e86c1;');
    const resp = await api.get(`/agent-config/${companyId}`);

    console.log('%c[AgentConfig] Resposta getAgentConfig:', 'color: #2e86c1;', resp.data);
    return resp.data;
  } catch (error) {
    console.error('%c[AgentConfig] Erro ao obter AgentConfig:', 'color: red;', error);
    handleApiError(error, 'Erro ao obter configurações do agente');
    throw new Error('Unreachable');
  }
}

// Função para deletar configurações do agente
export async function deleteAgentConfig(): Promise<string> {
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) {
    console.error('company_id não encontrado no localStorage ao tentar deletar config do agente.');
    throw new Error('Não foi possível determinar a empresa para deletar as configurações.');
  }

  try {
    const resp = await api.delete(`/agent-config/${companyId}`);
    console.log('Resposta deleteAgentConfig:', resp.data);
    return resp.data.message || 'Configurações removidas com sucesso!';
  } catch (error) {
    console.error('Erro ao deletar AgentConfig:', error);
    handleApiError(error, 'Erro ao deletar configurações do agente');
    throw new Error('Unreachable');
  }
}

// Função para atualizar configurações do agente
export async function updateAgentConfig(payload: any): Promise<string> {  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) {
    console.error('company_id não encontrado no localStorage. Não é possível atualizar config.');
    throw new Error('Não foi possível determinar a empresa para atualizar as configurações.');
  }

  payload.company_id = Number(companyId);

  console.log('Enviando payload de updateAgentConfig:', payload);

  const headers: HeadersInit = { 'Content-Type': 'application/json' };

  try {
    const resp = await api.put(`/agent-config/${companyId}`, payload, { headers });
    console.log('Resposta updateAgentConfig:', resp.data);
    return resp.data.message || 'Configurações atualizadas com sucesso!';
  } catch (error) {
    console.error('Erro ao atualizar AgentConfig:', error);
    if (axios.isAxiosError(error)) {
      const message = error.response?.data?.detail || 'Erro ao atualizar configurações do agente.';
      throw new Error(message);
    }
    throw error;
  }
}

/**
 * GOOGLE CALENDAR ENDPOINTS
 */
export interface GoogleCalendarIntegration {
  google_calendar_id: string | null;
  google_calendar_summary?: string | null;
  google_account_email?: string | null;
  google_oauth_connected?: boolean;
  oauth_configured?: boolean;
  oauth_redirect_uri?: string;
  message?: string;
}

export interface GoogleCalendarOption {
  id: string;
  summary?: string;
  description?: string;
  primary?: boolean;
  access_role?: string;
  background_color?: string;
  time_zone?: string;
}

export async function getGoogleCalendarIntegration(): Promise<GoogleCalendarIntegration> {
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) throw new Error("company_id não encontrado.");

  try {
    const resp = await api.get(`/api/integrations/calendar/google/${companyId}`);
    return resp.data;  // { google_calendar_id: "..." }
  } catch (error) {
    console.error("Erro ao obter google calendar integration:", error);
    handleApiError(error, 'Erro ao obter integração Google Calendar');
    throw new Error('Unreachable');
  }
}

export async function startGoogleCalendarOAuth(): Promise<{ authorization_url: string }> {
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) throw new Error("company_id não encontrado.");

  try {
    const resp = await api.get(`/api/integrations/calendar/google/${companyId}/oauth/start`);
    return resp.data;
  } catch (error) {
    console.error("Erro ao iniciar OAuth Google Calendar:", error);
    handleApiError(error, 'Erro ao iniciar conexão com Google Agenda');
    throw new Error('Unreachable');
  }
}

export async function listGoogleCalendars(): Promise<GoogleCalendarOption[]> {
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) throw new Error("company_id não encontrado.");

  try {
    const resp = await api.get(`/api/integrations/calendar/google/${companyId}/calendars`);
    return resp.data.calendars || [];
  } catch (error) {
    console.error("Erro ao listar agendas Google:", error);
    handleApiError(error, 'Erro ao listar agendas Google');
    throw new Error('Unreachable');
  }
}

export async function selectGoogleCalendar(calendarId: string): Promise<string> {
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) throw new Error("company_id não encontrado.");

  try {
    const resp = await api.post(`/api/integrations/calendar/google/${companyId}/calendar/select`, {
      google_calendar_id: calendarId,
    });
    return resp.data.message || 'Agenda Google selecionada com sucesso!';
  } catch (error) {
    console.error("Erro ao selecionar agenda Google:", error);
    handleApiError(error, 'Erro ao selecionar agenda Google');
    throw new Error('Unreachable');
  }
}

export async function createGoogleCalendar(summary: string): Promise<string> {
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) throw new Error("company_id não encontrado.");

  try {
    const resp = await api.post(`/api/integrations/calendar/google/${companyId}/calendars`, {
      summary,
    });
    return resp.data.message || 'Agenda Google criada com sucesso!';
  } catch (error) {
    console.error("Erro ao criar agenda Google:", error);
    handleApiError(error, 'Erro ao criar agenda Google');
    throw new Error('Unreachable');
  }
}

export async function linkGoogleCalendarToAgenda(agendaId: number, calendarId: string): Promise<string> {
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) throw new Error("company_id não encontrado.");

  try {
    const resp = await api.post(`/api/integrations/calendar/google/${companyId}/agendas/${agendaId}/link`, {
      google_calendar_id: calendarId,
    });
    return resp.data.message || 'Agenda vinculada ao Google Agenda com sucesso!';
  } catch (error) {
    console.error("Erro ao vincular agenda Google:", error);
    handleApiError(error, 'Erro ao vincular agenda Google');
    throw new Error('Unreachable');
  }
}

export async function createGoogleCalendarForAgenda(agendaId: number, summary: string): Promise<string> {
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) throw new Error("company_id não encontrado.");

  try {
    const resp = await api.post(`/api/integrations/calendar/google/${companyId}/agendas/${agendaId}/calendars`, {
      summary,
    });
    return resp.data.message || 'Agenda Google criada e vinculada com sucesso!';
  } catch (error) {
    console.error("Erro ao criar agenda Google vinculada:", error);
    handleApiError(error, 'Erro ao criar agenda Google vinculada');
    throw new Error('Unreachable');
  }
}

export async function unlinkGoogleCalendarFromAgenda(agendaId: number): Promise<string> {
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) throw new Error("company_id não encontrado.");

  try {
    const resp = await api.delete(`/api/integrations/calendar/google/${companyId}/agendas/${agendaId}/link`);
    return resp.data.message || 'Agenda Google desvinculada com sucesso!';
  } catch (error) {
    console.error("Erro ao desvincular agenda Google:", error);
    handleApiError(error, 'Erro ao desvincular agenda Google');
    throw new Error('Unreachable');
  }
}

export async function updateGoogleCalendarIntegration(google_calendar_id: string): Promise<string> {
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) throw new Error("company_id não encontrado.");

  const payload = { google_calendar_id };  // "Ex: { google_calendar_id: '...' }"
  const headers: HeadersInit = { 'Content-Type': 'application/json' };

  try {
    const resp = await api.put(`/api/integrations/calendar/google/${companyId}`, payload, { headers });
    return resp.data.message || 'Integração Google Calendar atualizada com sucesso!';
  } catch (error) {
    console.error("Erro ao atualizar google calendar integration:", error);
    handleApiError(error, 'Erro ao atualizar Google Calendar');
    throw new Error('Unreachable');
  }
}

export async function deleteGoogleCalendarIntegration(): Promise<string> {
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) throw new Error("company_id não encontrado.");
  const headers: HeadersInit = { 'Content-Type': 'application/json' };

  try {
    const resp = await api.delete(`/api/integrations/calendar/google/${companyId}`, { headers });
    return resp.data.message || 'Integração Google Calendar removida com sucesso!';
  } catch (error) {
    console.error("Erro ao deletar google calendar integration:", error);
    handleApiError(error, 'Erro ao deletar Google Calendar');
    throw new Error('Unreachable');
  }
}


/**
 * CLINICORP ENDPOINTS
 */
export async function getClinicorpIntegration(): Promise<{
  username: string | null;
  password: string | null;
  code_link: string | null;
  subscriber_id: string | null;
}> {
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) throw new Error("company_id não encontrado.");

  try {
    const resp = await api.get(`/api/integrations/calendar/clinicorp/${companyId}`);
    return resp.data; // {username, password, code_link, subscriber_id}
  } catch (error) {
    console.error("Erro ao obter clinicorp integration:", error);
    handleApiError(error, 'Erro ao obter integração Clinicorp');
    throw new Error('Unreachable');
  }
}

export async function updateClinicorpIntegration(payload: {
  username?: string;
  password?: string;
  code_link?: string;
  subscriber_id?: string;
}): Promise<string> {
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) throw new Error("company_id não encontrado.");
  const headers: HeadersInit = { 'Content-Type': 'application/json' };

  try {
    const resp = await api.put(`/api/integrations/calendar/clinicorp/${companyId}`, payload, { headers });
    return resp.data.message || 'Integração Clinicorp atualizada com sucesso!';
  } catch (error) {
    console.error("Erro ao atualizar clinicorp integration:", error);
    handleApiError(error, 'Erro ao atualizar integração Clinicorp');
    throw new Error('Unreachable');
  }
}

export async function deleteClinicorpIntegration(): Promise<string> {
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) throw new Error("company_id não encontrado.");
  const headers: HeadersInit = { 'Content-Type': 'application/json' };

  try {
    const resp = await api.delete(`/api/integrations/calendar/clinicorp/${companyId}`, { headers });
    return resp.data.message || 'Integração Clinicorp removida com sucesso!';
  } catch (error) {
    console.error("Erro ao deletar clinicorp integration:", error);
    handleApiError(error, 'Erro ao deletar integração Clinicorp');
    throw new Error('Unreachable');
  }
}

/** ========================================================================
 *  INTEGRAÇÕES DE GRUPO DE SUPORTE
 *  Rota no backend: /api/integrations/support-group/{company_id}
 * ========================================================================*/

export async function getSupportGroupIntegration(): Promise<any> {
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) {
    throw new Error('company_id não encontrado.');
  }
  try {
    const resp = await api.get(`/api/integrations/support-group/${companyId}`);
    return resp.data;
  } catch (error) {
    console.error('Erro ao obter support group integration:', error);
    handleApiError(error, 'Erro ao obter integração do grupo de suporte');
    throw new Error('Unreachable');
  }
}

export async function updateSupportGroupIntegration(payload: any): Promise<string> {
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) {
    throw new Error('company_id não encontrado.');
  }

  payload.company_id = Number(companyId);
  const headers: HeadersInit = { 'Content-Type': 'application/json' };

  try {
    const resp = await api.put(`/api/integrations/support-group/${companyId}`, payload, {
      headers,
    });
    return resp.data.message || 'Integração do grupo de suporte atualizada com sucesso!';
  } catch (error) {
    console.error('Erro ao atualizar suporte group integration:', error);
    handleApiError(error, 'Erro ao atualizar integração do grupo de suporte');
    throw new Error('Unreachable');
  }
}

// Função para deletar integrações de grupo de suporte
export async function deleteSupportGroupIntegration(): Promise<string> {
  console.log("Iniciando deleteSupportGroupIntegration");
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) {
    throw new Error("company_id não encontrado.");
  }
  const headers: HeadersInit = { 'Content-Type': 'application/json' };

  try {
    console.log(`Enviando DELETE para /api/integrations/support-group/${companyId} com headers:`, headers);
    const resp = await api.delete(`/api/integrations/support-group/${companyId}`, { headers });
    console.log("Resposta deleteSupportGroupIntegration:", resp.data);
    return resp.data.message || 'Integração do grupo de suporte deletada com sucesso!';
  } catch (error) {
    console.error("Erro ao deletar suporte group integration:", error);

    if (axios.isAxiosError(error)) {
      const message = error.response?.data?.detail || 'Erro ao deletar integração do grupo de suporte.';
      console.error("Detalhes do erro Axios:", error.response?.data);
      throw new Error(message);
    }
    throw error;
  }
}

/** ========================================================================
 *  INTEGRAÇÃO TELEGRAM
 *  Rota no backend: /api/integrations/telegram/{company_id}
 * ========================================================================*/

export interface TelegramIntegration {
  configured: boolean;
  bot_name?: string | null;
  bot_username?: string | null;
  default_chat_id?: string | null;
  default_chat_title?: string | null;
  last_error?: string | null;
  last_validated_at?: string | null;
  status: string;
}

export interface TelegramIntegrationPayload {
  bot_token?: string;
  default_chat_id?: string;
  default_chat_title?: string;
}

const getActiveCompanyId = (): string => {
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  if (!companyId) {
    throw new Error('company_id não encontrado.');
  }
  return companyId;
};

export async function getTelegramIntegration(): Promise<TelegramIntegration> {
  const companyId = getActiveCompanyId();
  try {
    const resp = await api.get<TelegramIntegration>(`/api/integrations/telegram/${companyId}`);
    return resp.data;
  } catch (error) {
    console.error('Erro ao obter integração Telegram:', error);
    handleApiError(error, 'Erro ao obter integração Telegram');
    throw new Error('Unreachable');
  }
}

export async function updateTelegramIntegration(payload: TelegramIntegrationPayload): Promise<TelegramIntegration> {
  const companyId = getActiveCompanyId();
  try {
    const resp = await api.put<TelegramIntegration>(`/api/integrations/telegram/${companyId}`, payload, {
      headers: { 'Content-Type': 'application/json' },
    });
    return resp.data;
  } catch (error) {
    console.error('Erro ao atualizar integração Telegram:', error);
    handleApiError(error, 'Erro ao atualizar integração Telegram');
    throw new Error('Unreachable');
  }
}

export async function testTelegramIntegration(payload: { chat_id?: string; message?: string }) {
  const companyId = getActiveCompanyId();
  try {
    const resp = await api.post(`/api/integrations/telegram/${companyId}/test-message`, payload, {
      headers: { 'Content-Type': 'application/json' },
    });
    return resp.data;
  } catch (error) {
    console.error('Erro ao testar integração Telegram:', error);
    handleApiError(error, 'Erro ao testar integração Telegram');
    throw new Error('Unreachable');
  }
}

export async function deleteTelegramIntegration(): Promise<string> {
  const companyId = getActiveCompanyId();
  try {
    const resp = await api.delete(`/api/integrations/telegram/${companyId}`, {
      headers: { 'Content-Type': 'application/json' },
    });
    return resp.data.message || 'Integração Telegram removida com sucesso!';
  } catch (error) {
    console.error('Erro ao remover integração Telegram:', error);
    handleApiError(error, 'Erro ao remover integração Telegram');
    throw new Error('Unreachable');
  }
}

// ========================
// MIRROR WEBHOOK ENDPOINTS
// ========================

/**
 * Obtém a URL atual do mirror_webhook.
 * GET /api/company/mirror-webhook
 */
export async function getMirrorWebhookUrl(): Promise<MirrorWebhookResponse> {
  try {
    const resp = await api.get('/api/company/mirror-webhook');
    // resp.data deve ser { mirror_webhook_url: "..."} ou { mirror_webhook_url: null }
    return resp.data;
  } catch (error) {
    console.error("Erro ao obter Mirror Webhook URL:", error);
    handleApiError(error, 'Erro ao obter o Mirror Webhook URL');
    throw error;
  }
}

/**
 * Cria (POST) uma nova mirror_webhook_url via FormData.
 * POST /api/company/mirror-webhook
 */
export async function createMirrorWebhookUrl(newUrl: string): Promise<string> {

  // Montamos formData com o campo mirror_webhook_url
  const formData = new FormData();
  formData.append('mirror_webhook_url', newUrl);

  try {
    // Enviamos com multipart/form-data
    const resp = await api.post('/api/company/mirror-webhook', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return resp.data.message || 'Mirror Webhook criado com sucesso!';
  } catch (error) {
    console.error('Erro ao criar Mirror Webhook URL:', error);
    handleApiError(error, 'Erro ao criar Mirror Webhook URL');
    throw new Error('Unreachable');
  }
}

/**
 * Atualiza (PUT) a mirror_webhook_url existente via FormData.
 * PUT /api/company/mirror-webhook
 */
export async function updateMirrorWebhookUrl(newUrl: string): Promise<string> {

  // Montamos formData com o campo mirror_webhook_url
  const formData = new FormData();
  formData.append('mirror_webhook_url', newUrl);

  try {
    // Enviamos com multipart/form-data
    const resp = await api.put('/api/company/mirror-webhook', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return resp.data.message || 'Mirror Webhook atualizado com sucesso!';
  } catch (error) {
    console.error('Erro ao atualizar Mirror Webhook URL:', error);
    handleApiError(error, 'Erro ao atualizar Mirror Webhook URL');
    throw new Error('Unreachable');
  }
}

/**
 * Deleta (DELETE) a mirror_webhook_url.
 * DELETE /api/company/mirror-webhook
 */
export async function deleteMirrorWebhookUrl(): Promise<string> {

  try {
    const resp = await api.delete('/api/company/mirror-webhook');
    return resp.data.message || 'Mirror Webhook deletado com sucesso!';
  } catch (error) {
    console.error('Erro ao deletar Mirror Webhook URL:', error);
    handleApiError(error, 'Erro ao deletar Mirror Webhook URL');
    throw new Error('Unreachable');
  }
}

/**
 * Cria uma nova empresa e a associa ao usuário cujo e-mail é passado.
 * Endpoint: POST /api/companies-admin
 * Usa a sessão autenticada do usuário atual.
 */
export async function createNewCompanyAdmin(
  clientEmail: string,
  companyName: string,
  companyCnpj: string,
  customerId?: number | null,
  trialDays: number = 0
): Promise<{
  company_id: number;
  client_id?: number;
  client_created?: boolean;
  message: string;
  managed_customer_id?: number;
  managed_link_id?: number;
  trial_days?: number;
  trial_ends_at?: string | null;
  lifecycle_status?: string;
  trial_credits_granted?: number;
  ai_credit_balance?: number;
  password_setup_email_sent?: boolean;
  password_setup_email_skipped?: boolean;
  password_setup_email_reason?: string;
  password_setup_url?: string | null;
}> {
  const formData = new FormData();
  formData.append('client_email', clientEmail);
  formData.append('company_name', companyName);
  formData.append('company_cnpj', companyCnpj);
  if (customerId) {
    formData.append('customer_id', String(customerId));
  }
  formData.append('trial_days', String(trialDays || 0));

  try {
    // Não setamos "Content-Type" pois o axios detecta como multipart/form-data
    const resp = await api.post('/api/companies-admin', formData);
    console.log('Resposta createNewCompanyAdmin:', resp.data);
    return resp.data;
  } catch (error) {
    console.error('Erro ao criar nova empresa (admin):', error);
    // Caso use o handleApiError, pode chamar assim:
    // handleApiError(error, 'Erro ao criar nova empresa (admin)');
    throw error;
  }
}


/**
 * Lista todas as empresas vinculadas ao usuário logado (GET /api/client-companies).
 */
export interface UserCompany {
  company_id: number;
  name_company?: string | null;
  logo_url?: string | null;
  ai_credit_balance?: number | null;
  ai_credit_status?: string | null;
  managed_link_id?: number;
  managed_customer_id?: number;
  lifecycle_status?: string;
  trial_days?: number;
  trial_started_at?: string | null;
  trial_ends_at?: string | null;
  trial_days_remaining?: number | null;
  trial_progress_percent?: number | null;
  is_trial_expired?: boolean;
}

export async function getUserCompanies(): Promise<UserCompany[]> {
  try {
    const resp = await api.get('/api/client-companies');
    return resp.data; // array de empresas
  } catch (error) {
    console.error("Erro ao obter lista de empresas do usuário:", error);
    throw error;
  }
}

/**
 * Define qual empresa (company_id) o usuário está usando no momento.
 * PUT /api/client-companies/{company_id}/select
 */
export async function selectActiveCompany(companyId: number) {
  const resp = await api.put(`/api/client-companies/${companyId}/select`);
  return resp.data; // { message, company_logo_url, name_company }
}

/**
 * Remove vínculo com uma empresa específica do usuário logado.
 * DELETE /api/client-companies/{company_id}
 */
export async function removeUserCompany(companyId: number): Promise<string> {
  console.log('[API] removeUserCompany -> Removendo vínculo com empresa:', companyId);

  try {
    const resp = await api.delete(`/client-companies/${companyId}`);
    console.log('[API] removeUserCompany -> Resposta do servidor:', resp.data);

    return resp.data.message || 'Vínculo com a empresa removido com sucesso.';
  } catch (error) {
    console.error('[API] removeUserCompany -> Erro ao remover vínculo:', error);
    handleApiError(error, 'Erro ao remover vínculo com a empresa');
    throw new Error('Unreachable');
  }
}

/**
 * Faz upload de um arquivo (imagem, áudio, vídeo) para o backend,
 * usando `client_id` e `company_id` do localStorage.
 */
// api.ts
export async function uploadFile(file: File): Promise<{ id: string; path: string }> {
  try {
    const clientId = Number(localStorage.getItem('client_id'));
    const companyId = Number((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')));

    if (!clientId || !companyId) {
      throw new Error('Faltando client_id ou company_id no localStorage.');
    }

    const formData = new FormData();
    formData.append('file', file);

    // Log para debug
    console.log('Enviando arquivo:', {
      name: file.name,
      type: file.type,
      size: file.size
    });

    const resp = await api.post<{ id: string; path: string }>(
      `/api/arquivos/upload/${clientId}/${companyId}`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        timeout: 30000, // Aumenta para 30 segundos
        maxContentLength: Infinity,
        maxBodyLength: Infinity
      }
    );

    return resp.data;
  } catch (error: any) {
    console.error('[uploadFile] Erro ao fazer upload:', error);
    if (error.code === 'ECONNABORTED') {
      throw new Error('O upload está demorando muito. Tente um arquivo menor ou verifique sua conexão.');
    }
    throw error;
  }
}

/**
 * Lista os arquivos do client_id e company_id, obtidos do localStorage.
 */
export async function listFiles(): Promise<MediaFile[]> {
  try {
    const clientId = Number(localStorage.getItem('client_id'));
    const companyId = Number((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')));

    if (!clientId || !companyId) {
      throw new Error('Faltando client_id ou company_id no localStorage.');
    }

    const resp = await api.get<MediaFile[]>(
      `/api/arquivos/files/${clientId}/${companyId}`
    );
    return resp.data;
  } catch (error) {
    console.error('[listFiles] Erro ao listar arquivos:', error);
    handleApiError(error, 'Erro ao listar arquivos');
    throw new Error('Unreachable');
  }
}

/**
 * Deleta um arquivo específico pelo seu ID.
 * O endpoint /api/arquivos/files/{file_id} não depende de client_id/company_id,
 * pois só precisa do file_id na rota.
 */
export async function deleteFile(fileId: string): Promise<string> {
  try {
    const resp = await api.delete<{ message: string }>(
      `/api/arquivos/files/${fileId}`
    );
    return resp.data.message || 'Arquivo deletado com sucesso!';
  } catch (error) {
    console.error('[deleteFile] Erro ao deletar arquivo:', error);
    handleApiError(error, 'Erro ao deletar arquivo');
    throw new Error('Unreachable');
  }
}

/**
 * Retorna a URL final para GET /api/arquivos/files/view/{company_id}/{client_id}/{file_name},
 * usando o file_name completo (ex.: "c24465ac-...7007.jpg").
 */
export function getFileUrl(
  companyId: number,
  clientId: number,
  fileName: string
): string {
  return `/api/arquivos/files/view/${companyId}/${clientId}/${fileName}`;
}

/**
 * Faz um GET para buscar o arquivo como Blob, usando o fileName completo.
 */
export async function fetchFileBlob(
  companyId: number,
  clientId: number,
  fileName: string
): Promise<Blob> {
  try {
    const response = await api.get(
      `/api/arquivos/files/view/${companyId}/${clientId}/${fileName}`,
      {
        responseType: 'blob',
      }
    );
    return response.data;
  } catch (error) {
    console.error('[fetchFileBlob] Erro ao buscar arquivo:', error);
    handleApiError(error, 'Erro ao buscar arquivo');
    throw error;
  }
}

/**
 * Envia texto via WhatsApp (Z-API)
 * POST /webhook/send-text
 */
export async function sendWhatsAppText({ phone, message, localMessageId, replyTo }: SendTextParams): Promise<any> {
  try {
    // 1) Descobrir se é 'master' ou 'user'
    const userType = localStorage.getItem("user_type");
    const rawMasterClientId = localStorage.getItem("master_client_id");
    const rawOwnClientId = localStorage.getItem("client_id");
    const companyId = localStorage.getItem("company_id");

    // 2) Se for 'user', usar master_client_id. Se for 'master', usar client_id
    // Para usuários staff (user), sempre usar o próprio client_id
    // O backend já trata as permissões corretamente
    let finalClientId = rawOwnClientId;

    // 3) Montar URL com query param
    const url = `/webhook/send-text?client_id=${finalClientId}&company_id=${companyId}`;

    // 4) Fazer POST com body (incluindo localMessageId se fornecido)
    const body: any = { phone, message };
    if (localMessageId) {
      body.localMessageId = localMessageId;
    }
    if (replyTo) {
      body.replyTo = replyTo;
    }

    const resp = await api.post(url, body, {
      headers: { 'Content-Type': 'application/json' },
    });
    return resp.data; // { message: "...", zapi_response: ... }
  } catch (error) {
    console.error('[sendWhatsAppText] Erro ao enviar texto:', error);
    handleApiError(error, 'Erro ao enviar mensagem de texto via WhatsApp');
    throw new Error('Unreachable');
  }
}

export async function sendWhatsAppReaction({
  phone,
  messageId,
  reaction,
}: {
  phone: string;
  messageId: string;
  reaction: string;
}): Promise<any> {
  try {
    const finalClientId = localStorage.getItem("client_id");
    const companyId = localStorage.getItem("company_id");
    const url = `/webhook/reaction?client_id=${finalClientId}&company_id=${companyId}`;
    const resp = await api.put(url, { phone, messageId, reaction }, {
      headers: { 'Content-Type': 'application/json' },
    });
    return resp.data;
  } catch (error) {
    console.error('[sendWhatsAppReaction] Erro ao atualizar reação:', error);
    handleApiError(error, 'Erro ao atualizar reação no WhatsApp');
    throw new Error('Unreachable');
  }
}

/**
 * Envia imagem via WhatsApp (Z-API)
 * POST /webhook/send-image
 */
export async function sendWhatsAppImage(params: SendImageParams): Promise<any> {
  try {
    // 1) Lógica para pegar client_id
    const userType = localStorage.getItem("user_type");
    const rawMasterClientId = localStorage.getItem("master_client_id");
    const rawOwnClientId = localStorage.getItem("client_id");
    const companyId = localStorage.getItem("company_id");

    // Para usuários staff (user), sempre usar o próprio client_id
    // O backend já trata as permissões corretamente
    let finalClientId = rawOwnClientId;

    // 2) Query string
    const url = `/webhook/send-image?client_id=${finalClientId}&company_id=${companyId}`;

    // 3) POST no endpoint, enviando 'params' no body
    const resp = await api.post(url, params, {
      headers: { 'Content-Type': 'application/json' },
    });
    return resp.data;
  } catch (error) {
    console.error('[sendWhatsAppImage] Erro ao enviar imagem:', error);
    handleApiError(error, 'Erro ao enviar imagem via WhatsApp');
    throw new Error('Unreachable');
  }
}

/**
 * Envia áudio via WhatsApp (Z-API)
 * POST /webhook/send-audio
 */
export async function sendWhatsAppAudio(params: SendAudioParams): Promise<any> {
  try {
    // Obter parâmetros necessários
    const userType = localStorage.getItem("user_type");
    const rawMasterClientId = localStorage.getItem("master_client_id");
    const rawOwnClientId = localStorage.getItem("client_id");
    const companyId = localStorage.getItem("company_id");

    // Para usuários staff (user), sempre usar o próprio client_id
    // O backend já trata as permissões corretamente
    let finalClientId = rawOwnClientId;

    const url = `/webhook/send-audio?client_id=${finalClientId}&company_id=${companyId}`;

    // Enviar o áudio sem muitas manipulações
    const resp = await api.post(url, params, {
      headers: { 'Content-Type': 'application/json' },
    });
    return resp.data;
  } catch (error) {
    console.error('[sendWhatsAppAudio] Erro ao enviar áudio:', error);
    throw error;
  }
}


/**
 * Envia vídeo via WhatsApp (Z-API)
 * POST /webhook/send-video
 */
export async function sendWhatsAppVideo(params: SendVideoParams): Promise<any> {
  try {
    const userType = localStorage.getItem("user_type");
    const rawMasterClientId = localStorage.getItem("master_client_id");
    const rawOwnClientId = localStorage.getItem("client_id");
    const companyId = localStorage.getItem("company_id");

    // Para usuários staff (user), sempre usar o próprio client_id
    // O backend já trata as permissões corretamente
    let finalClientId = rawOwnClientId;

    const url = `/webhook/send-video?client_id=${finalClientId}&company_id=${companyId}`;

    const resp = await api.post(url, params, {
      headers: { 'Content-Type': 'application/json' },
    });
    return resp.data;
  } catch (error) {
    console.error('[sendWhatsAppVideo] Erro ao enviar vídeo:', error);
    handleApiError(error, 'Erro ao enviar vídeo via WhatsApp');
    throw new Error('Unreachable');
  }
}

// [GERENCIAR FOLLOW-UP]

/**
 * Cria uma nova sequência de follow-up para uma empresa específica.
 * Endpoint: POST /api/followups/{company_id}
 */
// Função createFollowUpSequence removida (duplicada). Ver final do arquivo.

/**
 * Obtém a sequência de follow-up (caso exista) para uma empresa específica.
 * Endpoint: GET /api/followups/{company_id}
 */
// Funções de follow-up removidas (duplicadas). Ver final do arquivo.

/**
 * Cria a configuração de follow-up schedule para a empresa {companyId}.
 * Endpoint: POST /followup-schedule/{company_id}
 */
export async function createFollowUpScheduleConfig(
  companyId: number,
  payload: FollowUpScheduleCreate
): Promise<{ message: string; id: number; company_id: number }> {
  try {
    // Exemplo de chamada:
    // POST /followup-schedule/123
    // body: { follow_up_sequence_id, schedule_data: { days_of_week, times } }

    const resp = await api.post<{ message: string; id: number; company_id: number }>(
      `/api/followup-schedule/${companyId}`,
      payload
    );
    return resp.data;
  } catch (error) {
    console.error('[createFollowUpScheduleConfig] Erro:', error);
    // Se você tiver a handleApiError:
    // handleApiError(error, 'Erro ao criar configuração de horários');
    throw error;
  }
}

/**
 * Obtém a configuração de follow-up schedule da empresa {companyId}.
 * Endpoint: GET /followup-schedule/{company_id}
 */
export async function getFollowUpScheduleConfig(
  companyId: number
): Promise<FollowUpScheduleConfig> {
  try {
    const resp = await api.get<FollowUpScheduleConfig>(
      `/api/followup-schedule/${companyId}`
    );
    return resp.data;
  } catch (error: any) {
    if (error.response && error.response.status === 404) {
      return null as any; // Retorna null se não existir config
    }
    console.error('[getFollowUpScheduleConfig] Erro:', error);
    throw error;
  }
}

/**
 * Atualiza a configuração de follow-up schedule para a empresa {companyId}.
 * Endpoint: PUT /followup-schedule/{company_id}
 */
export async function updateFollowUpScheduleConfig(
  companyId: number,
  payload: FollowUpScheduleUpdate
): Promise<{ message: string; id: number; company_id: number }> {
  try {
    // PUT /followup-schedule/123
    // body: { schedule_data: { days_of_week, times } }

    const resp = await api.put<{ message: string; id: number; company_id: number }>(
      `/api/followup-schedule/${companyId}`,
      payload
    );
    return resp.data;
  } catch (error) {
    console.error('[updateFollowUpScheduleConfig] Erro:', error);
    // handleApiError(error, 'Erro ao atualizar configuração de horários');
    throw error;
  }
}

/**
 * Deleta a configuração de follow-up schedule para a empresa {companyId}.
 * Endpoint: DELETE /followup-schedule/{company_id}
 */
export async function deleteFollowUpScheduleConfig(
  companyId: number
): Promise<{ message: string }> {
  try {
    const resp = await api.delete<{ message: string }>(
      `/api/followup-schedule/${companyId}`
    );
    return resp.data;
  } catch (error) {
    console.error('[deleteFollowUpScheduleConfig] Erro:', error);
    // handleApiError(error, 'Erro ao deletar configuração de horários');
    throw error;
  }
}

/**
 * Cria uma nova sequência de confirmação para uma empresa específica.
 * Endpoint: POST /api/confirmations/{company_id}
 */
export async function createConfirmationSequence(
  companyId: number,
  payload: ConfirmationSequenceCreate
): Promise<ConfirmationSequenceResponse> {
  try {
    const resp = await api.post<ConfirmationSequenceResponse>(
      `/api/confirmations/${companyId}`,
      payload
    );
    return resp.data; // { message: '...', sequence_id: 123 }
  } catch (error) {
    console.error('Erro ao criar ConfirmationSequence:', error);
    throw new Error('Não foi possível criar a sequência de confirmação.');
  }
}

/**
 * Obtém a sequência de confirmação (caso exista) para uma empresa específica.
 * Endpoint: GET /api/confirmations/{company_id}
 */
export async function getConfirmationSequence(
  companyId: number
): Promise<ConfirmationSequenceDetail | null> {
  try {
    const resp = await api.get<ConfirmationSequenceDetail>(
      `/api/confirmations/${companyId}`,
      {
        validateStatus: (status) => {
          // Aceita 200 (OK) e 404 (não encontrado)
          return (status >= 200 && status < 300) || status === 404;
        },
      }
    );

    if (resp.status === 404) {
      return null;
    }

    return resp.data;
  } catch (error) {
    console.error('Erro ao obter ConfirmationSequence:', error);
    throw new Error('Não foi possível obter a sequência de confirmação.');
  }
}

/**
 * Atualiza completamente a sequência de confirmação para a empresa específica,
 * sobrescrevendo steps e messages conforme o payload.
 * Endpoint: PUT /api/confirmations/{company_id}
 */
export async function updateConfirmationSequence(
  companyId: number,
  payload: ConfirmationSequenceUpdate
): Promise<ConfirmationSequenceResponse> {
  try {
    const resp = await api.put<ConfirmationSequenceResponse>(
      `/api/confirmations/${companyId}`,
      payload
    );
    return resp.data;
  } catch (error) {
    console.error('Erro ao atualizar ConfirmationSequence:', error);
    throw new Error('Não foi possível atualizar a sequência de confirmação.');
  }
}

/**
 * Deleta a sequência de confirmação (se existir) para a empresa específica.
 * Endpoint: DELETE /api/confirmations/{company_id}
 */
export async function deleteConfirmationSequence(
  companyId: number
): Promise<{ message: string }> {
  try {
    const resp = await api.delete<{ message: string }>(
      `/api/confirmations/${companyId}`
    );
    return resp.data; // { message: 'Confirmation sequence ... deleted successfully' }
  } catch (error) {
    console.error('Erro ao deletar ConfirmationSequence:', error);
    throw new Error('Não foi possível deletar a sequência de confirmação.');
  }
}

/**
 * Cria a configuração de CONFIRMAÇÃO schedule para a empresa {companyId}.
 * Endpoint: POST /api/confirmation-schedule/{company_id}
 */
export async function createConfirmationScheduleConfig(
  companyId: number,
  payload: ConfirmationScheduleCreate
): Promise<{ message: string; id: number; company_id: number }> {
  try {
    const resp = await api.post<{ message: string; id: number; company_id: number }>(
      `/api/confirmation-schedule/${companyId}`,
      payload
    );
    return resp.data;
  } catch (error) {
    console.error('[createConfirmationScheduleConfig] Erro:', error);
    throw error;
  }
}

/**
 * Obtém a configuração de CONFIRMAÇÃO schedule da empresa {companyId}.
 * Endpoint: GET /api/confirmation-schedule/{company_id}
 */
export async function getConfirmationScheduleConfig(
  companyId: number
): Promise<ConfirmationScheduleConfig | null> {
  console.log('[getConfirmationScheduleConfig] Iniciando chamada com companyId:', companyId);

  try {
    const resp = await api.get<ConfirmationScheduleConfig>(
      `/api/confirmation-schedule/${companyId}`,
      {
        validateStatus: (status) => {
          // Aceita 200 e 404
          return (status >= 200 && status < 300) || status === 404;
        },
      }
    );

    console.log('[getConfirmationScheduleConfig] Status da resposta:', resp.status);
    console.log('[getConfirmationScheduleConfig] Dados recebidos:', resp.data);

    if (resp.status === 404) {
      console.warn('[getConfirmationScheduleConfig] Recebemos 404, retornando null');
      return null;
    }

    console.log('[getConfirmationScheduleConfig] Retornando schedule config:', resp.data);
    return resp.data;

  } catch (error) {
    console.error('[getConfirmationScheduleConfig] Erro ao obter config:', error);
    throw error;
  }
}


/**
 * Atualiza a configuração de CONFIRMAÇÃO schedule para a empresa {companyId}.
 * Endpoint: PUT /api/confirmation-schedule/{company_id}
 */
export async function updateConfirmationScheduleConfig(
  companyId: number,
  payload: ConfirmationScheduleUpdate
): Promise<{ message: string; id: number; company_id: number }> {
  try {
    const resp = await api.put<{ message: string; id: number; company_id: number }>(
      `/api/confirmation-schedule/${companyId}`,
      payload
    );
    return resp.data;
  } catch (error) {
    console.error('[updateConfirmationScheduleConfig] Erro:', error);
    throw error;
  }
}

/**
 * Deleta a configuração de CONFIRMAÇÃO schedule para a empresa {companyId}.
 * Endpoint: DELETE /api/confirmation-schedule/{company_id}
 */
export async function deleteConfirmationScheduleConfig(
  companyId: number
): Promise<{ message: string }> {
  try {
    const resp = await api.delete<{ message: string }>(
      `/api/confirmation-schedule/${companyId}`
    );
    return resp.data;
  } catch (error) {
    console.error('[deleteConfirmationScheduleConfig] Erro:', error);
    throw error;
  }
}

/**
 * 1) Obtém a lista de agendamentos completos
 */
export async function listarAgendamentos(): Promise<AgendamentoResponse[]> {
  const clientId = localStorage.getItem('client_id');
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  const apiKey = '';

  if (!clientId || !companyId) {
    throw new Error('Informações de autenticação não encontradas');
  }

  try {
    const response = await api.get(
      `/api/agenda/clients/${clientId}/companies/${companyId}/agendamentos`,
      {
        headers: legacyApiKeyHeaders(apiKey)
      }
    );

    return response.data;
  } catch (error) {
    // Adicione mais detalhes ao log de erro
    console.error('Erro ao listar agendamentos:', {
      error,
      status: (error as any).response?.status,
      data: (error as any).response?.data
    });
    throw error;
  }
}

/**
 * 2) Atualiza um agendamento específico (por ID)
 */
export async function atualizarAgendamento(
  clientId: number,
  companyId: number,
  agendamentoId: number,
  data: AgendamentoUpdate,
  apiKey: string
): Promise<AgendamentoResponse> {
  const response: AxiosResponse<AgendamentoResponse> = await api.put(
    `/api/agenda/clients/${clientId}/companies/${companyId}/agendamentos/${agendamentoId}`,
    data,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
  return response.data;
}

/**
 *  Deleta um agendamento específico (DELETE)
 *  DELETE /api/agenda/clients/{clientId}/companies/{companyId}/agendamentos/{agendamentoId}
 */
export async function deletarAgendamento(
  clientId: number,
  companyId: number,
  agendamentoId: number,
  apiKey: string
): Promise<void> {
  await api.delete(
    `/api/agenda/clients/${clientId}/companies/${companyId}/agendamentos/${agendamentoId}`,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
}

/**
 * 1) Lista todos os leads de um determinado client/company.
 */
export async function listarLeads(
  clientId: number,
  companyId: number,
  apiKey: string
): Promise<Lead[]> {
  // Ex: GET /api/agenda/clients/{clientId}/companies/{companyId}/leads
  const response: AxiosResponse<Lead[]> = await api.get(
    `/api/agenda/clients/${clientId}/companies/${companyId}/leads`,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
  return response.data;
}

/**
 * 2) Obtém um lead específico pelo ID.
 */
export async function obterLead(
  clientId: number,
  companyId: number,
  leadId: number,
  apiKey: string
): Promise<Lead> {
  // Ex: GET /api/agenda/clients/{clientId}/companies/{companyId}/leads/{leadId}
  const response: AxiosResponse<Lead> = await api.get(
    `/api/agenda/clients/${clientId}/companies/${companyId}/leads/${leadId}`,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
  return response.data;
}

/**
 * Lista todos os comparecimentos (GET).
 */
export async function listarComparecimentos(
  clientId: number,
  companyId: number,
  apiKey: string
): Promise<Comparecimento[]> {
  // GET /api/agenda/clients/{clientId}/companies/{companyId}/comparecimentos
  const response: AxiosResponse<Comparecimento[]> = await api.get(
    `/api/agenda/clients/${clientId}/companies/${companyId}/comparecimentos`,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
  return response.data;
}

/**
 * Obtém um comparecimento específico (GET).
 */
export async function obterComparecimento(
  clientId: number,
  companyId: number,
  comparecimentoId: number,
  apiKey: string
): Promise<Comparecimento> {
  // GET /api/agenda/clients/{clientId}/companies/{companyId}/comparecimentos/{comparecimentoId}
  const response: AxiosResponse<Comparecimento> = await api.get(
    `/api/agenda/clients/${clientId}/companies/${companyId}/comparecimentos/${comparecimentoId}`,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
  return response.data;
}

/**
 * Cria um novo comparecimento (POST).
 */
export async function criarComparecimento(
  clientId: number,
  companyId: number,
  data: ComparecimentoCreate,
  apiKey: string
): Promise<Comparecimento> {
  // POST /api/agenda/clients/{clientId}/companies/{companyId}/comparecimentos
  const response: AxiosResponse<Comparecimento> = await api.post(
    `/api/agenda/clients/${clientId}/companies/${companyId}/comparecimentos`,
    data,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
  return response.data;
}

/**
 * Atualiza um comparecimento específico (PUT).
 */
export async function atualizarComparecimento(
  clientId: number,
  companyId: number,
  comparecimentoId: number,
  data: ComparecimentoUpdate,
  apiKey: string
): Promise<Comparecimento> {
  // PUT /api/agenda/clients/{clientId}/companies/{companyId}/comparecimentos/{comparecimentoId}
  const response: AxiosResponse<Comparecimento> = await api.put(
    `/api/agenda/clients/${clientId}/companies/${companyId}/comparecimentos/${comparecimentoId}`,
    data,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
  return response.data;
}

/**
 * Deleta um comparecimento específico (DELETE).
 */
export async function deletarComparecimento(
  clientId: number,
  companyId: number,
  comparecimentoId: number,
  apiKey: string
): Promise<void> {
  // DELETE /api/agenda/clients/{clientId}/companies/{companyId}/comparecimentos/{comparecimentoId}
  await api.delete(
    `/api/agenda/clients/${clientId}/companies/${companyId}/comparecimentos/${comparecimentoId}`,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
}

/**
 * 1) Lista todas as vendas (GET)
 * GET /api/agenda/clients/{clientId}/companies/{companyId}/vendas
 */
export async function listarVendas(
  clientId: number,
  companyId: number,
  apiKey: string
): Promise<Venda[]> {
  const response: AxiosResponse<Venda[]> = await api.get(
    `/api/agenda/clients/${clientId}/companies/${companyId}/vendas`,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
  return response.data;
}

/**
 * 2) Obtém uma venda específica (GET)
 * GET /api/agenda/clients/{clientId}/companies/{companyId}/vendas/{vendaId}
 */
export async function obterVenda(
  clientId: number,
  companyId: number,
  vendaId: number,
  apiKey: string
): Promise<Venda> {
  const response: AxiosResponse<Venda> = await api.get(
    `/api/agenda/clients/${clientId}/companies/${companyId}/vendas/${vendaId}`,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
  return response.data;
}

/**
 * 3) Cria uma nova venda (POST)
 * POST /api/agenda/clients/{clientId}/companies/{companyId}/vendas
 */
export async function criarVenda(
  clientId: number,
  companyId: number,
  data: VendaCreate,
  apiKey: string
): Promise<Venda> {
  const response: AxiosResponse<Venda> = await api.post(
    `/api/agenda/clients/${clientId}/companies/${companyId}/vendas`,
    data,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
  return response.data;
}

/**
 * 4) Atualiza uma venda específica (PUT)
 * PUT /api/agenda/clients/{clientId}/companies/{companyId}/vendas/{vendaId}
 */
export async function atualizarVenda(
  clientId: number,
  companyId: number,
  vendaId: number,
  data: VendaUpdate,
  apiKey: string
): Promise<Venda> {
  const response: AxiosResponse<Venda> = await api.put(
    `/api/agenda/clients/${clientId}/companies/${companyId}/vendas/${vendaId}`,
    data,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
  return response.data;
}

/**
 * 5) Deleta uma venda específica (DELETE)
 * DELETE /api/agenda/clients/{clientId}/companies/{companyId}/vendas/{vendaId}
 */
export async function deletarVenda(
  clientId: number,
  companyId: number,
  vendaId: number,
  apiKey: string
): Promise<void> {
  await api.delete(
    `/api/agenda/clients/${clientId}/companies/${companyId}/vendas/${vendaId}`,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
}

// ==============================
// [NO-SHOW FOLLOW-UP] SEQUÊNCIAS
// ==============================

/**
 * Cria uma nova sequência de no-show para uma empresa específica.
 * Endpoint: POST /api/noshow-followups/{company_id}
 */
export async function createNoShowFollowUpSequence(
  companyId: number,
  payload: NoShowFollowUpSequenceCreate
): Promise<NoShowFollowUpSequenceResponse> {
  try {
    const resp = await api.post<NoShowFollowUpSequenceResponse>(
      `/api/noshow-followups/${companyId}`,
      payload
    );
    return resp.data; // { message, sequence_id }
  } catch (error) {
    console.error('[createNoShowFollowUpSequence] Erro:', error);
    throw new Error('Não foi possível criar a sequência de no-show.');
  }
}

/**
 * Obtém a sequência de no-show (caso exista) para uma empresa específica.
 * Endpoint: GET /api/noshow-followups/{company_id}
 */
export async function getNoShowFollowUpSequence(
  companyId: number
): Promise<NoShowFollowUpSequenceDetail | null> {
  try {
    const resp = await api.get<NoShowFollowUpSequenceDetail>(
      `/api/noshow-followups/${companyId}`,
      {
        validateStatus: (status) => {
          // Aceita 200 e 404
          return (status >= 200 && status < 300) || status === 404;
        },
      }
    );

    if (resp.status === 404) {
      return null;
    }

    return resp.data;
  } catch (error) {
    console.error('[getNoShowFollowUpSequence] Erro:', error);
    throw new Error('Não foi possível obter a sequência de no-show.');
  }
}

/**
 * Atualiza completamente a sequência de no-show para a empresa específica.
 * Endpoint: PUT /api/noshow-followups/{company_id}
 */
export async function updateNoShowFollowUpSequence(
  companyId: number,
  payload: NoShowFollowUpSequenceUpdate
): Promise<NoShowFollowUpSequenceResponse> {
  try {
    const resp = await api.put<NoShowFollowUpSequenceResponse>(
      `/api/noshow-followups/${companyId}`,
      payload
    );
    return resp.data; // { message, sequence_id }
  } catch (error) {
    console.error('[updateNoShowFollowUpSequence] Erro:', error);
    throw new Error('Não foi possível atualizar a sequência de no-show.');
  }
}

/**
 * Deleta a sequência de no-show (se existir) para a empresa específica.
 * Endpoint: DELETE /api/noshow-followups/{company_id}
 */
export async function deleteNoShowFollowUpSequence(
  companyId: number
): Promise<{ message: string }> {
  try {
    const resp = await api.delete<{ message: string }>(
      `/api/noshow-followups/${companyId}`
    );
    return resp.data; // { message: 'No-show follow-up sequence excluída...' }
  } catch (error) {
    console.error('[deleteNoShowFollowUpSequence] Erro:', error);
    throw new Error('Não foi possível deletar a sequência de no-show.');
  }
}

// ==============================
// [NO-SHOW FOLLOW-UP] SCHEDULE
// ==============================

/**
 * Cria uma nova configuração de no-show schedule para a empresa {companyId}.
 * Endpoint: POST /api/noshow-schedule/{company_id}
 */
export async function createNoShowScheduleConfig(
  companyId: number,
  payload: NoShowScheduleCreate
): Promise<{ message: string; id: number; company_id: number }> {
  try {
    const resp = await api.post<{ message: string; id: number; company_id: number }>(
      `/api/noshow-schedule/${companyId}`,
      payload
    );
    return resp.data;
  } catch (error) {
    console.error('[createNoShowScheduleConfig] Erro:', error);
    throw new Error('Não foi possível criar a configuração de no-show schedule.');
  }
}

/**
 * Obtém a configuração de no-show schedule da empresa {companyId}.
 * Endpoint: GET /api/noshow-schedule/{company_id}
 */
export async function getNoShowScheduleConfig(
  companyId: number
): Promise<NoShowScheduleConfig | null> {
  try {
    const resp = await api.get<NoShowScheduleConfig>(
      `/api/noshow-schedule/${companyId}`,
      {
        validateStatus: (status) => {
          return (status >= 200 && status < 300) || status === 404;
        },
      }
    );
    if (resp.status === 404) {
      return null; // caso não exista config
    }
    return resp.data;
  } catch (error) {
    console.error('[getNoShowScheduleConfig] Erro:', error);
    throw new Error('Não foi possível obter a configuração de no-show schedule.');
  }
}

/**
 * Atualiza a configuração de no-show schedule para a empresa {companyId}.
 * Endpoint: PUT /api/noshow-schedule/{company_id}
 */
export async function updateNoShowScheduleConfig(
  companyId: number,
  payload: NoShowScheduleUpdate
): Promise<{ message: string; id: number; company_id: number }> {
  try {
    const resp = await api.put<{ message: string; id: number; company_id: number }>(
      `/api/noshow-schedule/${companyId}`,
      payload
    );
    return resp.data;
  } catch (error) {
    console.error('[updateNoShowScheduleConfig] Erro:', error);
    throw new Error('Não foi possível atualizar a configuração de no-show schedule.');
  }
}

/**
 * Deleta a configuração de no-show schedule para a empresa {companyId}.
 * Endpoint: DELETE /api/noshow-schedule/{company_id}
 */
export async function deleteNoShowScheduleConfig(
  companyId: number
): Promise<{ message: string }> {
  try {
    const resp = await api.delete<{ message: string }>(
      `/api/noshow-schedule/${companyId}`
    );
    return resp.data;
  } catch (error) {
    console.error('[deleteNoShowScheduleConfig] Erro:', error);
    throw new Error('Não foi possível deletar a configuração de no-show schedule.');
  }
}

/**
 * Marcar um agendamento como NO_SHOW enviando o payload { observacao: "..." }.
 * PUT /api/agenda/clients/{clientId}/companies/{companyId}/agendamentos/{agendamentoId}/noshow
 */
export async function marcarNoShowAgendamento(
  clientId: number,
  companyId: number,
  agendamentoId: number,
  payload: NoShowCreatePayload
): Promise<string> {
  try {
    // body JSON contendo { observacao: "..." }
    const resp = await api.put(
      `/api/agenda/clients/${clientId}/companies/${companyId}/agendamentos/${agendamentoId}/noshow`,
      payload
    );
    // Se o backend retorna { message: "...", task_id, noshow_id }, pegamos message
    return resp.data.message || 'Agendamento marcado como no-show com sucesso!';
  } catch (error) {
    console.error('[marcarNoShowAgendamento] Erro ao marcar no-show:', error);
    throw error;
  }
}

/**
 * Lista todos os no-shows de um determinado clientId e companyId.
 * GET /api/agenda/clients/{clientId}/companies/{companyId}/noshow-events
 */
export async function listarNoShows(
  clientId: number,
  companyId: number,
  apiKey: string
): Promise<NoShowEvent[]> {
  try {
    const resp = await api.get<NoShowEvent[]>(
      `/api/agenda/clients/${clientId}/companies/${companyId}/noshow-events`,
      {
        headers: legacyApiKeyHeaders(apiKey)
      }
    );
    return resp.data; // array de NoShowEvent
  } catch (error) {
    console.error('[listarNoShows] Erro:', error);
    throw error;
  }
}

/**
 * Obtém um no-show específico pelo ID.
 * GET /api/agenda/clients/{clientId}/companies/{companyId}/noshow-events/{noShowId}
 */
export async function obterNoShowEvent(
  clientId: number,
  companyId: number,
  noShowId: number,
  apiKey: string
): Promise<NoShowEvent> {
  try {
    const resp = await api.get<NoShowEvent>(
      `/api/agenda/clients/${clientId}/companies/${companyId}/noshow-events/${noShowId}`,
      {
        headers: legacyApiKeyHeaders(apiKey)
      }
    );
    return resp.data;
  } catch (error) {
    console.error('[obterNoShowEvent] Erro:', error);
    throw error;
  }
}

/**
 * Se quisermos atualizar apenas a observação do no-show:
 * PUT /api/agenda/clients/{clientId}/companies/{companyId}/noshow-events/{noShowId}
 */
export interface NoShowUpdatePayload {
  observacao?: string;
  // Se quiser permitir editar nome, phone, data_agendada,
  // adicione aqui: nome?: string, phone?: string, data_agendada?: string ...
}

export async function atualizarNoShowEvent(
  clientId: number,
  companyId: number,
  noShowId: number,
  data: NoShowUpdatePayload,
  apiKey: string
): Promise<NoShowEvent> {
  try {
    const resp = await api.put<NoShowEvent>(
      `/api/agenda/clients/${clientId}/companies/${companyId}/noshow-events/${noShowId}`,
      data,
      {
        headers: legacyApiKeyHeaders(apiKey)
      }
    );
    return resp.data; // objeto NoShowEvent atualizado
  } catch (error) {
    console.error('[atualizarNoShowEvent] Erro:', error);
    throw error;
  }
}

/**
 * Deleta um registro de no-show específico.
 * DELETE /api/agenda/clients/{clientId}/companies/{companyId}/noshow-events/{noShowId}
 */
export async function deletarNoShowEvent(
  clientId: number,
  companyId: number,
  noShowId: number,
  apiKey: string
): Promise<void> {
  try {
    await api.delete(
      `/api/agenda/clients/${clientId}/companies/${companyId}/noshow-events/${noShowId}`,
      {
        headers: legacyApiKeyHeaders(apiKey)
      }
    );
  } catch (error) {
    console.error('[deletarNoShowEvent] Erro:', error);
    throw error;
  }
}

export async function getMessageMedia(content: string, fromMe: boolean): Promise<string> {
  try {
    // 🆕 PARA VÍDEOS WAHA: CONVERTER PARA PROXY DO BACKEND
    if (content.includes('/api/files/') && !content.includes('/api/waha/')) {
      console.log('[getMessageMedia] 🎥 URL WAHA detectada, convertendo para proxy:', content.substring(0, 100) + '...');

      // Converter para URL do proxy backend - detecta qualquer host com /api/files/
      // Formato: localhost:3000/api/files/sessao-exemplo/arquivo.jpeg -> /api/waha/media/sessao-exemplo/arquivo.jpeg
      // Formato: https://api.seu-dominio.com/api/files/sessao-exemplo/arquivo.jpeg -> /api/waha/media/sessao-exemplo/arquivo.jpeg
      const match = content.match(/\/api\/files\/(.+)$/);
      if (match) {
        const wahaPath = match[1];
        const proxyUrl = `/api/waha/media/${wahaPath}`;
        console.log('[getMessageMedia] ✅ URL convertida para proxy:', proxyUrl);
        return `${API_URL}${proxyUrl}`;
      }

      // Fallback se não conseguir converter
      console.warn('[getMessageMedia] ⚠️ Não foi possível converter URL WAHA, usando original');
      return content;
    }

    // Para conteúdo já em base64, converter para Blob e criar URL
    if (content.startsWith('data:')) {
      // Identificar se é um áudio ou vídeo em base64
      const isAudio = content.includes('audio/');
      const isVideo = content.includes('video/');

      if (isAudio) {
        // Extrair o MIME type completo, mantendo parâmetros como "codecs=opus"
        const mimePartMatch = content.match(/data:(audio\/[^;]+)(;[^,]*)?/);
        const mimeType = mimePartMatch ? mimePartMatch[1] : 'audio/ogg';
        const mimeParams = mimePartMatch && mimePartMatch[2] ? mimePartMatch[2] : '';

        // Extrair a parte base64
        const base64Content = content.split(',')[1];

        // Converter base64 para Blob
        const binary = atob(base64Content);
        const array = new Uint8Array(binary.length);

        for (let i = 0; i < binary.length; i++) {
          array[i] = binary.charCodeAt(i);
        }

        // Criar Blob com o MIME type correto
        const blob = new Blob([array], { type: mimeType });

        // Criar uma URL para este blob
        const blobUrl = URL.createObjectURL(blob);

        // Criar um elemento de Audio para pré-carregar os metadados
        const audio = new Audio();
        audio.src = blobUrl;

        // Retornar uma Promise que resolve com a URL quando os metadados estiverem carregados
        return new Promise((resolve) => {
          audio.onloadedmetadata = () => {
            console.log(`Áudio carregado com duração: ${audio.duration}s`);
            resolve(blobUrl);
          };

          // Se falhar ao carregar metadados, ainda assim retornar a URL do blob
          audio.onerror = () => {
            console.warn('Erro ao carregar metadados do áudio, usando URL sem duração');
            resolve(blobUrl);
          };

          // Se demorar muito, continuar mesmo sem metadados
          setTimeout(() => {
            if (audio.duration === 0) {
              console.warn('Timeout ao carregar metadados do áudio, usando URL sem duração');
              resolve(blobUrl);
            }
          }, 2000);
        });
      } else if (isVideo) {
        // Extrair o MIME type completo para vídeos
        const mimePartMatch = content.match(/data:(video\/[^;]+)(;[^,]*)?/);
        const mimeType = mimePartMatch ? mimePartMatch[1] : 'video/mp4';

        // Extrair a parte base64
        const base64Content = content.split(',')[1];

        // Converter base64 para Blob
        const binary = atob(base64Content);
        const array = new Uint8Array(binary.length);

        for (let i = 0; i < binary.length; i++) {
          array[i] = binary.charCodeAt(i);
        }

        // Criar Blob com o MIME type correto
        const blob = new Blob([array], { type: mimeType });

        // Criar uma URL para este blob
        const blobUrl = URL.createObjectURL(blob);

        // Criar um elemento de Video para pré-carregar os metadados
        const video = document.createElement('video');
        video.src = blobUrl;

        // Retornar uma Promise que resolve com a URL quando os metadados estiverem carregados
        return new Promise((resolve) => {
          video.onloadedmetadata = () => {
            console.log(`Vídeo carregado com duração: ${video.duration}s e dimensões: ${video.videoWidth}x${video.videoHeight}`);
            resolve(blobUrl);
          };

          // Se falhar ao carregar metadados, ainda assim retornar a URL do blob
          video.onerror = () => {
            console.warn('Erro ao carregar metadados do vídeo, usando URL sem duração');
            resolve(blobUrl);
          };

          // Se demorar muito, continuar mesmo sem metadados
          setTimeout(() => {
            if (video.duration === 0 || video.videoWidth === 0) {
              console.warn('Timeout ao carregar metadados do vídeo, usando URL sem duração');
              resolve(blobUrl);
            }
          }, 2000);
        });
      }

      // Para outros tipos de mídia em base64, retornar como está
      return content;
    }

    // 🆕 TRATAMENTO PARA URLs WAHA DIRETAS
    // Se o content for uma URL WAHA direta (ex: /api/waha/media/company_68/arquivo.mp4)
    if (content.startsWith('/api/waha/media/')) {
      console.log(`[Media Fix] URL WAHA direta detectada: ${content}`);

      try {
        const wahaResp = await api.get(content, {
          responseType: 'blob'
        });

        const blob = new Blob([wahaResp.data], {
          type: getResponseHeader(wahaResp.headers, 'content-type', getMimeType(content))
        });
        console.log(`[Media Fix] ✅ Sucesso com URL WAHA direta`);
        return URL.createObjectURL(blob);
      } catch (error) {
        console.error(`[Media Fix] ❌ Erro com URL WAHA direta: ${error}`);
        throw new Error(`Falha ao carregar mídia WAHA: ${error}`);
      }
    }

    // Se o content for uma URL HTTP completa (incluindo WAHA externo)
    if (content.startsWith('http')) {
      console.log(`[Media Fix] URL HTTP detectada: ${content.substring(0, 100)}...`);

      try {
        // Tentar buscar via proxy do backend para melhor tratamento de CORS/autenticação
        const proxyResp = await api.get('/media/whatsapp/proxy', {
          params: { url: content },
          responseType: 'blob'
        });

        const blob = new Blob([proxyResp.data], {
          type: getResponseHeader(proxyResp.headers, 'content-type', getMimeType(content))
        });
        console.log(`[Media Fix] ✅ Sucesso via proxy HTTP`);
        return URL.createObjectURL(blob);
      } catch (proxyError) {
        console.log(`[Media Fix] Proxy falhou, tentando busca direta: ${proxyError}`);

        // Fallback: tentar busca direta
        try {
          const directResp = await fetch(content);
          if (!directResp.ok) {
            throw new Error(`HTTP ${directResp.status}: ${directResp.statusText}`);
          }

          const blob = await directResp.blob();
          console.log(`[Media Fix] ✅ Sucesso via busca direta`);
          return URL.createObjectURL(blob);
        } catch (directError) {
          console.error(`[Media Fix] ❌ Falha em todas as tentativas HTTP: ${directError}`);
          throw new Error(`Falha ao carregar mídia HTTP: ${directError}`);
        }
      }
    }

    // Resto do código existente...
    // Obtém client_id e company_id do localStorage
    const clientId = localStorage.getItem('client_id');
    const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
    if (!clientId || !companyId) {
      throw new Error('client_id ou company_id não encontrados');
    }

    // Para imagens no formato "client_X/company_Y/..."
    const clientCompanyPattern = /^client_(\d+)\/company_(\d+)\/(.+)$/;
    const match = content.match(clientCompanyPattern);

    if (match) {
      // Extrair os componentes do caminho corretamente
      const [_, pathClientId, pathCompanyId, actualPath] = match;

      // PRIMEIRA TENTATIVA: Endpoint WAHA para arquivos recentes
      try {
        console.log(`[Media Fix] Tentando endpoint WAHA: /api/waha/media/company_${pathCompanyId}/${actualPath}`);
        const wahaResp = await api.get(`/api/waha/media/company_${pathCompanyId}/${actualPath}`, {
          responseType: 'blob'
        });

        const blob = new Blob([wahaResp.data], {
          type: getResponseHeader(wahaResp.headers, 'content-type', getMimeType(actualPath))
        });
        console.log(`[Media Fix] ✅ Sucesso com endpoint WAHA`);
        return URL.createObjectURL(blob);
      } catch (wahaError) {
        console.log(`[Media Fix] WAHA falhou, tentando endpoint tradicional: ${wahaError}`);
      }

      // SEGUNDA TENTATIVA: Endpoint tradicional para arquivos locais
      try {
        console.log(`[Media Fix] Tentando endpoint tradicional: /media/messages/${pathClientId}/${pathCompanyId}/${actualPath}`);
        const resp = await api.get(`/media/messages/${pathClientId}/${pathCompanyId}/${actualPath}`, {
          responseType: 'blob'
        });

        const blob = new Blob([resp.data], {
          type: getResponseHeader(resp.headers, 'content-type', getMimeType(actualPath))
        });
        console.log(`[Media Fix] ✅ Sucesso com endpoint tradicional`);
        return URL.createObjectURL(blob);
      } catch (innerError) {
        console.error(`[Media Fix] ❌ Erro em todos os endpoints: ${innerError}`);

        // NOVA ALTERNATIVA: converter para base64
        try {
          // Obter a URL direta do arquivo
          const fileUrl = `${API_URL}/media/messages/${pathClientId}/${pathCompanyId}/${actualPath}`;
          console.log(`[Media Fix] Tentando acessar diretamente: ${fileUrl}`);

          // Tentar converter para base64
          const response = await fetch(fileUrl);
          if (response.ok) {
            const blob = await response.blob();
            return URL.createObjectURL(blob);
          } else {
            throw new Error(`Falha ao buscar imagem: ${response.status}`);
          }
        } catch (fetchError) {
          console.error(`Erro na tentativa direta: ${fetchError}`);
          // Última alternativa: tentar acessar diretamente com caminho completo
          return `${API_URL}/${content}`;
        }
      }
    }

    // Para outros formatos de caminho (sem prefixo client/company)
    try {
      const resp = await api.get(`/media/messages/${clientId}/${companyId}/${content}`, {
        responseType: 'blob'
      });

      const blob = new Blob([resp.data], {
        type: getResponseHeader(resp.headers, 'content-type', 'application/octet-stream')
      });
      return URL.createObjectURL(blob);
    } catch (error) {
      console.error(`Erro ao acessar mídia regular: ${error}`);
      // Tentar acessar a URL direta como último recurso
      return `${API_URL}/${content}`;
    }
  } catch (error) {
    console.error(`Erro geral ao obter mídia da mensagem: ${error}`);
    // Adicionar logs para depuração
    console.error(`Tentando acessar: ${content}`);

    // Retornar placeholder como último recurso
    return '/assets/image-placeholder.png';
  }
}

/**
 * Consulta as métricas de funil (Leads, Agendamentos, Comparecimentos, Vendas, etc.)
 * Endpoint: GET /api/metrics/funnels?company_id=...&start_date=...&end_date=...
 */
export async function getFunnelMetrics(params: FunnelMetricsParams): Promise<FunnelMetricsResponse> {
  try {
    // Montamos a query string
    const queryString = new URLSearchParams();

    if (params.companyId) {
      queryString.append('company_id', params.companyId.toString());
    }
    if (params.startDate) {
      queryString.append('start_date', params.startDate);
    }
    if (params.endDate) {
      queryString.append('end_date', params.endDate);
    }
    if (params.fonte) {
      queryString.append('fonte', params.fonte);
    }

    // Exemplo de URL final: /api/metrics/funnels?company_id=1&start_date=2025-01-01&end_date=2025-01-31
    const url = `/api/metrics/funnels?${queryString.toString()}`;
    console.log('[getFunnelMetrics] Chamando GET em:', url);

    // Fazemos a chamada usando nosso axios 'api'
    const resp = await api.get<FunnelMetricsResponse>(url);

    console.log('[getFunnelMetrics] Resposta:', resp.data);
    return resp.data;
  } catch (error) {
    console.error('[getFunnelMetrics] Erro ao obter métricas do funil:', error);
    throw error;
  }
}

// ============= INSERIR AQUI (1) - LOGO APÓS AS IMPORTAÇÕES =============

export async function takeOverContact(contactId: string): Promise<string> {
  const rawOwnClientId = localStorage.getItem('client_id');
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));

  if (!companyId) {
    throw new Error("Empresa não identificada");
  }

  // Para usuários staff (user), sempre usar o próprio client_id
  // O backend já trata as permissões corretamente
  let finalClientId = rawOwnClientId;

  // Em vez de mandar body, transformamos tudo em query params:
  const finalUrl = `/api/atendimento/take_over/${contactId}?client_id=${finalClientId}&company_id=${companyId}`;

  try {
    const resp = await api.post(finalUrl);
    return resp.data.message || "Atendimento puxado para modo humano com sucesso.";
  } catch (error) {
    handleApiError(error, "Erro ao puxar atendimento para modo humano");
    throw new Error("Unreachable");
  }
}

export async function releaseContactToBot(contactId: string): Promise<string> {
  try {
    const rawOwnClientId = localStorage.getItem('client_id');
    const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));

    if (!companyId) {
      throw new Error("Empresa não identificada");
    }

    // Para usuários staff (user), sempre usar o próprio client_id
    // O backend já trata as permissões corretamente
    let finalClientId = rawOwnClientId;

    // Monta a URL com os query params
    const finalUrl = `/api/atendimento/release_to_bot/${contactId}?client_id=${finalClientId}&company_id=${companyId}`;

    const resp = await api.post(finalUrl);
    return resp.data.message || "Atendimento devolvido para a IA com sucesso.";
  } catch (error) {
    handleApiError(error, "Erro ao devolver atendimento para a IA");
    throw new Error("Unreachable");
  }
}


// --------------------
//    Funções de API
// --------------------

export async function listUsers(companyId?: number): Promise<User[]> {
  try {
    const params = companyId ? { company_id: companyId } : {};
    const response = await api.get('/api/users/', { params });
    return response.data;
  } catch (error) {
    console.error('Erro ao listar usuários:', error);
    handleApiError(error, 'Erro ao obter lista de usuários');
    throw new Error('Unreachable');
  }
}

export async function createUser(userData: UserCreate): Promise<User> {
  try {
    const response = await api.post('/api/users/', userData);
    return response.data;
  } catch (error) {
    console.error('Erro ao criar usuário:', error);
    handleApiError(error, 'Erro ao criar novo usuário');
    throw new Error('Unreachable');
  }
}

export async function updateUser(userId: number, userData: UserUpdate): Promise<User> {
  try {
    const response = await api.patch(`/api/users/${userId}`, userData);
    return response.data;
  } catch (error) {
    console.error('Erro ao atualizar usuário:', error);
    handleApiError(error, 'Erro ao atualizar usuário');
    throw new Error('Unreachable');
  }
}

export async function deleteUser(userId: number): Promise<void> {
  try {
    await api.delete(`/api/users/${userId}`);
  } catch (error) {
    console.error('Erro ao deletar usuário:', error);
    handleApiError(error, 'Erro ao remover usuário');
    throw new Error('Unreachable');
  }
}

export async function changeUserPassword(
  userId: number,
  newPassword: string,
  confirmPassword: string
): Promise<User> {
  try {
    const response = await api.post(`/api/users/${userId}/change-password`, {
      new_password: newPassword,
      confirm_password: confirmPassword,
    });
    return response.data;
  } catch (error) {
    console.error('Erro ao alterar senha:', error);
    handleApiError(error, 'Erro ao alterar senha do usuário');
    throw new Error('Unreachable');
  }
}

// --------------------
//  Funções de Equipes
// --------------------

export async function getTeams(): Promise<Team[]> {
  try {
    const response = await api.get('/api/teams/');
    return response.data;
  } catch (error) {
    console.error('Erro ao listar equipes:', error);
    handleApiError(error, 'Erro ao obter lista de equipes');
    throw new Error('Unreachable');
  }
}

export async function getTeam(teamId: number): Promise<Team> {
  try {
    const response = await api.get(`/api/teams/${teamId}`);
    return response.data;
  } catch (error) {
    console.error('Erro ao obter equipe:', error);
    handleApiError(error, 'Erro ao obter dados da equipe');
    throw new Error('Unreachable');
  }
}

export async function createTeam(teamData: TeamCreate): Promise<Team> {
  try {
    const response = await api.post('/api/teams/', teamData);
    return response.data;
  } catch (error) {
    console.error('Erro ao criar equipe:', error);
    handleApiError(error, 'Erro ao criar equipe');
    throw new Error('Unreachable');
  }
}

export async function updateTeam(teamId: number, teamData: TeamUpdate): Promise<Team> {
  try {
    const response = await api.put(`/api/teams/${teamId}`, teamData);
    return response.data;
  } catch (error) {
    console.error('Erro ao atualizar equipe:', error);
    handleApiError(error, 'Erro ao atualizar equipe');
    throw new Error('Unreachable');
  }
}

export async function deleteTeam(teamId: number): Promise<void> {
  try {
    await api.delete(`/api/teams/${teamId}`);
  } catch (error) {
    console.error('Erro ao excluir equipe:', error);
    handleApiError(error, 'Erro ao excluir equipe');
    throw new Error('Unreachable');
  }
}

export async function getCurrentTeamPermissions(): Promise<TeamPermissionPayload> {
  try {
    const response = await api.get('/api/teams/current/permissions');
    return response.data;
  } catch (error) {
    console.error('Erro ao carregar permissões atuais:', error);
    handleApiError(error, 'Erro ao carregar permissões atuais');
    throw new Error('Unreachable');
  }
}

export async function getTeamUsers(teamId: number): Promise<User[]> {
  try {
    const response = await api.get(`/api/teams/${teamId}/users`);
    return response.data;
  } catch (error) {
    console.error('Erro ao listar usuários da equipe:', error);
    handleApiError(error, 'Erro ao obter usuários da equipe');
    throw new Error('Unreachable');
  }
}

export async function assignUserToTeam(teamId: number, userId: number): Promise<void> {
  try {
    await api.post(`/api/teams/${teamId}/users`, { user_id: userId });
  } catch (error) {
    console.error('Erro ao atribuir usuário à equipe:', error);
    handleApiError(error, 'Erro ao atribuir usuário à equipe');
    throw new Error('Unreachable');
  }
}

export async function removeUserFromTeam(teamId: number, userId: number): Promise<void> {
  try {
    await api.delete(`/api/teams/${teamId}/users/${userId}`);
  } catch (error) {
    console.error('Erro ao remover usuário da equipe:', error);
    handleApiError(error, 'Erro ao remover usuário da equipe');
    throw new Error('Unreachable');
  }
}

// ----------------------------------------------------------------
// Criação de Lead (POST)
// ----------------------------------------------------------------
export async function criarLead(
  clientId: number,
  companyId: number,
  data: LeadCreate,
  apiKey: string
): Promise<Lead> {
  try {
    // POST /api/agenda/clients/{clientId}/companies/{companyId}/leads
    const response = await api.post<Lead>(
      `/api/agenda/clients/${clientId}/companies/${companyId}/leads`,
      data,
      {
        headers: legacyApiKeyHeaders(apiKey),
      }
    );
    return response.data;
  } catch (error) {
    console.error('[criarLead] Erro ao criar lead:', error);
    throw error;
  }
}

// ----------------------------------------------------------------
// Atualização de Lead (PUT)
// ----------------------------------------------------------------
export async function atualizarLead(
  clientId: number,
  companyId: number,
  leadId: number,
  data: LeadUpdate,
  apiKey: string
): Promise<Lead> {
  try {
    // PUT /api/agenda/clients/{clientId}/companies/{companyId}/leads/{leadId}
    const response = await api.put<Lead>(
      `/api/agenda/clients/${clientId}/companies/${companyId}/leads/${leadId}`,
      data,
      {
        headers: legacyApiKeyHeaders(apiKey),
      }
    );
    return response.data;
  } catch (error) {
    console.error('[atualizarLead] Erro ao atualizar lead:', error);
    throw error;
  }
}

// ----------------------------------------------------------------
// Exclusão de Lead (DELETE)
// ----------------------------------------------------------------
export async function deletarLead(
  clientId: number,
  companyId: number,
  leadId: number,
  apiKey: string
): Promise<void> {
  try {
    // DELETE /api/agenda/clients/{clientId}/companies/{companyId}/leads/{leadId}
    await api.delete(
      `/api/agenda/clients/${clientId}/companies/${companyId}/leads/${leadId}`,
      {
        headers: legacyApiKeyHeaders(apiKey),
      }
    );
  } catch (error) {
    console.error('[deletarLead] Erro ao deletar lead:', error);
    throw error;
  }
}

export function downloadRowsAsCsv(rows: Record<string, unknown>[], fileName: string) {
  if (!rows.length) {
    return;
  }

  const headers = Object.keys(rows[0]);
  const escapeCsvValue = (value: unknown) => {
    const raw = value === null || value === undefined ? '' : String(value);
    const safeValue = /^[=+\-@]/.test(raw) ? `'${raw}` : raw;
    return `"${safeValue.replace(/"/g, '""')}"`;
  };

  const csvContent = [
    headers.map(escapeCsvValue).join(','),
    ...rows.map(row => headers.map(header => escapeCsvValue(row[header])).join(','))
  ].join('\n');

  const blob = new Blob(['\uFEFF', csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', fileName);

  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

// Função para buscar todos os dados do funil respeitando filtros
export async function exportLeadsToExcel(
  leads: Lead[],
  startDate?: string,
  endDate?: string
) {
  try {
    const clientId = localStorage.getItem('client_id');
    const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
    const apiKey = '';

    if (!clientId || !companyId) {
      throw new Error('Informações de autenticação não encontradas');
    }

    // Buscar dados complementares
    const [agendamentos, comparecimentos, vendas, noShows] = await Promise.all([
      listarAgendamentos(),
      listarComparecimentos(Number(clientId), Number(companyId), apiKey),
      listarVendas(Number(clientId), Number(companyId), apiKey),
      listarNoShows(Number(clientId), Number(companyId), apiKey)
    ]);

    // Criar um Set com os IDs dos leads para busca eficiente
    const leadIds = new Set(leads.map(l => l.id));

    // Filtrar atividades por período para encontrar leads adicionais
    const filterByDateRange = (items: any[], dateField: string) => {
      if (!startDate || !endDate) return items;
      return items.filter(item => {
        const itemDate = new Date(item[dateField]);
        const start = new Date(startDate);
        const end = new Date(endDate + 'T23:59:59');
        return itemDate >= start && itemDate <= end;
      });
    };

    // Buscar atividades do período
    const vendasPeriodo = filterByDateRange(vendas, 'venda_data');
    const agendamentosPeriodo = filterByDateRange(agendamentos, 'consulta_data');
    const comparecimentosPeriodo = filterByDateRange(comparecimentos, 'compareceu_em');

    // Adicionar lead_ids de atividades do período (leads antigos que tiveram atividade)
    vendasPeriodo.forEach(v => v.lead_id && leadIds.add(v.lead_id));
    agendamentosPeriodo.forEach(a => a.lead_id && leadIds.add(a.lead_id));
    comparecimentosPeriodo.forEach(c => c.lead_id && leadIds.add(c.lead_id));

    // Buscar dados relacionados aos leads expandidos
    const relevantAgendamentos = agendamentos.filter(a => leadIds.has(a.lead_id));
    const relevantComparecimentos = comparecimentos.filter(c => leadIds.has(c.lead_id));
    const relevantVendas = vendas.filter(v => leadIds.has(v.lead_id));
    const relevantNoShows = noShows.filter(n => {
      const agendamento = agendamentos.find(a => a.id === n.agendamento_id);
      return agendamento && leadIds.has(agendamento.lead_id);
    });

    // Buscar leads adicionais que foram identificados pelas atividades do período
    const originalLeadIds = new Set(leads.map(l => l.id));
    const additionalLeadIds = Array.from(leadIds).filter(id => !originalLeadIds.has(id));

    let additionalLeads: Lead[] = [];
    if (additionalLeadIds.length > 0) {
      console.log(`[Export] Buscando ${additionalLeadIds.length} leads adicionais com atividades no período`);
      // Buscar os leads adicionais
      const allLeadsData = await listarLeads(Number(clientId), Number(companyId), apiKey);
      additionalLeads = allLeadsData.filter(lead => additionalLeadIds.includes(lead.id));
    }

    // Combinar leads originais + leads adicionais
    const allLeadsToExport = [...leads, ...additionalLeads];
    console.log(`[Export] Total leads: ${leads.length} originais + ${additionalLeads.length} adicionais = ${allLeadsToExport.length}`);

    // Preparar dados para exportação
    const exportData = allLeadsToExport.map(lead => {
      // Buscar TODOS os dados relacionados ao lead
      const leadAgendamentos = relevantAgendamentos.filter(a => a.lead_id === lead.id);
      const leadComparecimentos = relevantComparecimentos.filter(c => c.lead_id === lead.id);
      const leadVendas = relevantVendas.filter(v => v.lead_id === lead.id);

      // Pegar o agendamento mais recente
      const agendamento = leadAgendamentos.sort((a, b) => {
        const dateA = new Date(a.consulta_data || 0).getTime();
        const dateB = new Date(b.consulta_data || 0).getTime();
        return dateB - dateA;
      })[0];

      // Verificar se teve no-show
      const hasNoShow = agendamento && relevantNoShows.some(n => n.agendamento_id === agendamento.id);

      // Pegar o comparecimento mais recente
      const comparecimento = leadComparecimentos.sort((a, b) => {
        const dateA = new Date(a.compareceu_em || 0).getTime();
        const dateB = new Date(b.compareceu_em || 0).getTime();
        return dateB - dateA;
      })[0];

      // Pegar a venda mais recente
      const venda = leadVendas.sort((a, b) => {
        const dateA = new Date(a.venda_data || 0).getTime();
        const dateB = new Date(b.venda_data || 0).getTime();
        return dateB - dateA;
      })[0];

      // Determinar status do funil
      let statusFunil = 'Lead';
      if (venda) {
        statusFunil = 'Vendido';
      } else if (comparecimento) {
        statusFunil = 'Compareceu';
      } else if (hasNoShow) {
        statusFunil = 'Faltou';
      } else if (agendamento) {
        statusFunil = 'Agendado';
      }

      // Formatar datas
      const formatDate = (dateStr: string | undefined) => {
        if (!dateStr) return '';
        try {
          const date = new Date(dateStr);
          if (isNaN(date.getTime())) return '';
          const day = String(date.getDate()).padStart(2, '0');
          const month = String(date.getMonth() + 1).padStart(2, '0');
          const year = date.getFullYear();
          const hours = String(date.getHours()).padStart(2, '0');
          const minutes = String(date.getMinutes()).padStart(2, '0');
          return `${day}/${month}/${year} ${hours}:${minutes}`;
        } catch {
          return '';
        }
      };

      // Formatar valores monetários
      const formatCurrency = (value: number | undefined) => {
        if (value === undefined || value === null) return '';
        return `R$ ${value.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
      };

      // Mapear source_id para nome da mídia
      const getMediaName = (sourceId: string | undefined) => {
        if (!sourceId) return '';
        // Mapear os valores comuns
        const mediaMap: { [key: string]: string } = {
          'facebook': 'Facebook',
          'instagram': 'Instagram',
          'google': 'Google Ads',
          'whatsapp': 'WhatsApp',
          'site': 'Site',
          'indicacao': 'Indicação',
          'meta': 'Meta Ads',
          'google_ads': 'Google Ads',
          'organico': 'Orgânico',
          'outros': 'Outros'
        };
        return mediaMap[sourceId.toLowerCase()] || sourceId;
      };

      return {
        'ID Lead': lead.id,
        'Nome': lead.name || '',
        'Telefone': lead.phone || '',
        'Mídia': getMediaName(lead.source_id),
        'Data Entrada': formatDate(lead.data_entrada),
        'Status Funil': statusFunil,
        'Agendado': agendamento ? 'Sim' : 'Não',
        'Data Agendamento': agendamento ? (agendamento.consulta_data_display || formatDate(agendamento.consulta_data)) : '',
        'Faltou': hasNoShow ? 'Sim' : 'Não',
        'Compareceu': comparecimento ? 'Sim' : 'Não',
        'Data Comparecimento': comparecimento ? formatDate(comparecimento.compareceu_em) : '',
        'Valor Orçado': comparecimento ? formatCurrency(comparecimento.valor_orcamento) : '',
        'Vendido': venda ? 'Sim' : 'Não',
        'Data Venda': venda ? formatDate(venda.venda_data) : '',
        'Valor Faturado': venda ? formatCurrency(venda.valor_faturado) : '',
        'Valor Pago': venda ? formatCurrency(venda.valor_pago) : ''
      };
    });

    // Gerar nome do arquivo com data e período
    const today = new Date();
    const dateStr = `${today.getFullYear()}${String(today.getMonth() + 1).padStart(2, '0')}${String(today.getDate()).padStart(2, '0')}`;
    const periodStr = startDate && endDate ? `_${startDate.replace(/-/g, '')}_${endDate.replace(/-/g, '')}` : '';
    const fileName = `relatorio_crm_${dateStr}${periodStr}.csv`;

    // Exportar arquivo
    downloadRowsAsCsv(exportData, fileName);

    return true;
  } catch (error) {
    console.error('Erro ao exportar relatório CRM:', error);
    throw error;
  }
}

// Manter função CSV original para compatibilidade
export function exportLeadsAsCsv(leads: Lead[]) {
  downloadRowsAsCsv(
    leads.map((lead) => ({
      'ID': lead.id ?? '',
      'Nome': lead.name ?? '',
      'Telefone': lead.phone ?? '',
      'Mídia': lead.source_id ?? '',
      'Data de Entrada': lead.data_entrada ?? ''
    })),
    'leads_export.csv'
  );
}

/**
 * Cria um novo agendamento para o clientId/companyId informado.
 * POST /api/agenda/clients/{clientId}/companies/{companyId}/agendamentos
 */
export async function criarAgendamento(
  clientId: number,
  companyId: number,
  data: AgendamentoCreate,
  apiKey: string
): Promise<AgendamentoResponse> {
  try {
    const response = await api.post<AgendamentoResponse>(
      `/api/agenda/clients/${clientId}/companies/${companyId}/agendamentos`,
      data,
      {
        headers: legacyApiKeyHeaders(apiKey),
      }
    );
    return response.data;
  } catch (error) {
    console.error('[criarAgendamento] Erro ao criar agendamento:', error);
    throw error;
  }
}

// Interface para dados diários do funil
export interface DailyFunnelItem {
  date: string;
  leads: number;
  [key: string]: number | string;
}

/**
 * Chama GET /api/metrics/daily_funnel?company_id=...&start_date=...&end_date=...&fonte=...
 */
export async function getDailyFunnel(
  companyId?: number,
  startDate?: string,
  endDate?: string,
  fonte?: string
): Promise<DailyFunnelItem[]> {
  const qs = new URLSearchParams();
  if (companyId) qs.append("company_id", companyId.toString());
  if (startDate) qs.append("start_date", startDate);
  if (endDate) qs.append("end_date", endDate);
  if (fonte) qs.append("fonte", fonte);

  const url = `/api/metrics/daily_funnel?${qs.toString()}`;

  try {
    const resp = await api.get<DailyFunnelItem[]>(url);
    return resp.data;
  } catch (error) {
    console.error("[getDailyFunnel] Erro ao obter dados:", error);
    throw error;
  }
}

/**
 * Chama GET /api/metrics/funnel_by_source?company_id=...&start_date=...&end_date=...
 */
export async function getFunnelBySource(
  companyId?: number,
  startDate?: string,
  endDate?: string,
  fonte?: string
): Promise<FunnelBySourceItem[]> {
  // Monta a query string
  const qs = new URLSearchParams();
  if (companyId) qs.append("company_id", companyId.toString());
  if (startDate) qs.append("start_date", startDate);
  if (endDate) qs.append("end_date", endDate);
  if (fonte) qs.append("fonte", fonte);

  // Ex: /api/metrics/funnel_by_source?company_id=10&start_date=2025-01-01&end_date=2025-01-31
  const url = `/api/metrics/funnel_by_source?${qs.toString()}`;

  try {
    const resp = await api.get<FunnelBySourceItem[]>(url);
    return resp.data;
  } catch (error) {
    console.error("[getFunnelBySource] Erro ao obter dados:", error);
    throw error;
  }
}

/**
 * Chama GET /api/metrics/timeline com o timezone IANA detectado no navegador.
 */
export async function getTimeline(
  companyId?: number,
  startDate?: string,
  endDate?: string,
  limit = 20,
  timezone = getBrowserTimeZone(),
): Promise<TimelineEvent[]> {
  // Monta query string
  const qs = new URLSearchParams();
  if (companyId) qs.append("company_id", companyId.toString());
  if (startDate) qs.append("start_date", startDate);
  if (endDate) qs.append("end_date", endDate);
  if (limit) qs.append("limit", limit.toString());
  if (timezone) qs.append("timezone", timezone);

  const url = `/api/metrics/timeline?${qs.toString()}`;

  try {
    const resp = await api.get<TimelineEvent[]>(url);
    return resp.data;
  } catch (error) {
    console.error("[getTimeline] Erro ao obter timeline:", error);
    throw error;
  }
}

/**
 * Chama GET /api/metrics/projections?company_id=...
 * (no nosso backend, definimos que é opcional, mas você pode mudar)
 */
export async function getProjections(
  companyId?: number
): Promise<ProjectionsResponse> {
  // Monta query string se quiser
  const qs = new URLSearchParams();
  if (companyId) qs.append("company_id", companyId.toString());

  const url = `/api/metrics/projections?${qs.toString()}`;

  try {
    const resp = await api.get<ProjectionsResponse>(url);
    return resp.data;
  } catch (error) {
    console.error("[getProjections] Erro ao obter projeções:", error);
    throw error;
  }
}

/**
 * Chama GET /api/metrics/time_between_stages?company_id=...
 */
export async function getTimeBetweenStages(
  companyId?: number,
  startDate?: string,
  endDate?: string
): Promise<TimeBetweenStagesResponse> {
  const qs = new URLSearchParams();

  if (companyId) {
    qs.append("company_id", companyId.toString());
  }
  if (startDate) {
    qs.append("start_date", startDate);
  }
  if (endDate) {
    qs.append("end_date", endDate);
  }

  const url = `/api/metrics/time_between_stages?${qs.toString()}`;

  try {
    const resp = await api.get<TimeBetweenStagesResponse>(url);
    return resp.data;
  } catch (error) {
    console.error("[getTimeBetweenStages] Erro ao obter tempos médios:", error);
    throw error;
  }
}

/**
 * Cria uma nova configuração de IA para horários de resposta.
 * POST /api/ai-windows
 * Precisamos enviar {company_id, timezone, time_windows} no body.
 * Também podemos passar company_id/client_id via query param se o backend quiser.
 */
export async function createAIWindow(
  payload: AIResponseWindowsCreate
): Promise<{ id: number; message: string }> {
  // 1) Lê do localStorage
  const rawOwnClientId = localStorage.getItem('client_id');
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));

  if (!companyId) {
    throw new Error("Company ID não encontrado no localStorage.");
  }

  // Se seu backend precisa de client_id, definimos:
  // Para usuários staff (user), sempre usar o próprio client_id
  // O backend já trata as permissões corretamente
  let finalClientId = rawOwnClientId;

  // 2) Forçamos no body a usar o company_id do localStorage
  payload.company_id = Number(companyId);

  try {
    // 3) Chamamos a rota /api/ai-windows (POST).
    //    Caso o backend exija client_id e company_id via query param,
    //    podemos adicionar `params: { client_id: finalClientId, company_id }`.
    const resp = await api.post('/api/ai-windows', payload, {
      params: {
        client_id: finalClientId,
        company_id: companyId,
      },
    });
    return resp.data as { id: number; message: string };
  } catch (error) {
    console.error('[createAIWindow] Erro ao criar config IA:', error);
    handleApiError(error, 'Erro ao criar configuração de IA');
    throw new Error('Unreachable');
  }
}

/**
 * Busca a configuração de janelas de resposta pelo company_id (via localStorage).
 * GET /api/ai-windows/{company_id}
 */
export async function getAIWindow(companyId: number): Promise<AIResponseWindowsData | null> {
  // 1) Lê localStorage
  const rawOwnClientId = localStorage.getItem('client_id');
  //const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));

  if (!companyId) {
    throw new Error("Company ID não encontrado no localStorage.");
  }

  // Para usuários staff (user), sempre usar o próprio client_id
  // O backend já trata as permissões corretamente
  let finalClientId = rawOwnClientId;

  try {
    // 2) Fazemos GET /api/ai-windows/{companyId},
    //    e passamos { client_id, company_id } como query param se necessário.
    const resp = await api.get(`/api/ai-windows/${companyId}`, {
      params: {
        client_id: finalClientId,
        company_id: companyId,
      },
      validateStatus: (status) => {
        // se 404 => retorna null
        return (status >= 200 && status < 300) || status === 404;
      },
    });

    if (resp.status === 404) {
      return null; // sem config
    }

    return resp.data as AIResponseWindowsData;
  } catch (error) {
    console.error('[getAIWindow] Erro ao obter config IA:', error);
    handleApiError(error, 'Erro ao obter configuração de IA');
    throw new Error('Unreachable');
  }
}

/**
 * Atualiza a configuração de janelas de resposta, baseado em ID (que você pegou do GET).
 * PUT /api/ai-windows/{id}
 * O payload deve conter { timezone, time_windows? } e possivelmente company_id no body.
 */
export async function updateAIWindow(
  id: number,
  payload: AIResponseWindowsUpdate
): Promise<{ message: string }> {
  const rawOwnClientId = localStorage.getItem('client_id');
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));

  if (!companyId) {
    throw new Error("Company ID não encontrado no localStorage.");
  }

  // Para usuários staff (user), sempre usar o próprio client_id
  // O backend já trata as permissões corretamente
  let finalClientId = rawOwnClientId;

  // Se o backend quiser company_id no body:
  // (depende do seu design)
  // (ex.: payload["company_id"] = Number(companyId);)

  try {
    const resp = await api.put(`/api/ai-windows/${id}`, payload, {
      params: {
        client_id: finalClientId,
        company_id: companyId,
      },
    });
    return resp.data as { message: string };
  } catch (error) {
    console.error('[updateAIWindow] Erro ao atualizar config IA:', error);
    handleApiError(error, 'Erro ao atualizar configuração de IA');
    throw new Error('Unreachable');
  }
}

// api.ts (trecho simplificado)

// IMPORTS e variáveis de contexto omitidos...

/**
 * Deleta a configuração de horários de IA, identificada pelo ID.
 * DELETE /api/ai-windows/{id}
 */
export async function deleteAIWindow(id: number): Promise<{ message: string }> {
  // 1) Obter dados do localStorage (para contexto de client_id, company_id, etc. - se for preciso)
  const rawOwnClientId = localStorage.getItem('client_id');
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));

  if (!companyId) {
    throw new Error('Company ID não encontrado no localStorage.');
  }

  // Caso precise decidir qual client_id usar:
  // Para usuários staff (user), sempre usar o próprio client_id
  // O backend já trata as permissões corretamente
  let finalClientId = rawOwnClientId;

  // 2) Chamar endpoint DELETE /api/ai-windows/{id}, passando query params se necessários
  try {
    const resp = await api.delete(`/api/ai-windows/${id}`, {
      params: {
        client_id: finalClientId,
        company_id: companyId
      }
    });
    // O backend retorna { message: "Configuração deletada com sucesso." }
    return resp.data as { message: string };
  } catch (error) {
    console.error('[deleteAIWindow] Erro ao deletar config IA:', error);
    handleApiError(error, 'Erro ao deletar configuração de IA');
    throw new Error('Unreachable');
  }
}

function getDefaultTimeWindows() {
  const days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
  const defaultPeriod = {
    enabled: false,
    start: "08:00",
    end: "12:00",
  };
  const defaultDay = {
    morning: { ...defaultPeriod },
    afternoon: { ...defaultPeriod, start: "13:00", end: "18:00" },
    night: { ...defaultPeriod, start: "18:00", end: "22:00" },
    dawn: { ...defaultPeriod, start: "22:00", end: "06:00" },
  };

  const result: Record<string, typeof defaultDay> = {};
  for (const day of days) {
    // Clona para evitar referências compartilhadas
    result[day] = JSON.parse(JSON.stringify(defaultDay));
  }

  return result;
}

function unifyTimeWindows(
  fromBackend?: Record<string, any>
): Record<string, any> {
  const def = getDefaultTimeWindows();
  if (!fromBackend) return def;

  // Percorre cada dia do default
  for (const day of Object.keys(def)) {
    // Se não existe day no backend, adiciona
    if (!fromBackend[day]) {
      fromBackend[day] = def[day];
    } else {
      // Verifica cada período
      for (const period of ["morning", "afternoon", "night", "dawn"]) {
        if (!fromBackend[day][period as keyof typeof def[typeof day]]) {
          fromBackend[day][period] = def[day][period as keyof typeof def[typeof day]];
        }
      }
    }
  }
  return fromBackend;
}

/**
 * Obtém mensagens paginadas de um contato específico.
 * Suporta paginação por ID ou timestamp.
 */
// Correção para getPagedMessages em api.ts
export async function getPagedMessages(
  contact_phone: string,
  limit: number = 30,
  before_id?: string,
  before_timestamp?: number
): Promise<PagedMessagesResponse> {
  try {
    // Obter company_id do localStorage para garantir o contexto correto
    const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
    console.log('[DEBUG-API] getPagedMessages called for phone:', contact_phone);
    console.log('[DEBUG-API] company_id from localStorage:', companyId);

    // Construir a query string
    let url = `/api/chat-optimized/messages/paged?contact_phone=${encodeURIComponent(contact_phone)}&limit=${limit}`;

    if (companyId) {
      url += `&company_id=${companyId}`;
    }

    console.log('[DEBUG-API] Requesting URL:', url);

    if (before_id) {
      url += `&before_id=${encodeURIComponent(before_id)}`;
    } else if (before_timestamp) {
      url += `&before_timestamp=${before_timestamp}`;
    }

    console.log('[DEBUG-API] Chamando endpoint:', url);
    const resp = await api.get(url);

    // Verificar estrutura da resposta e logar para debug
    console.log('[DEBUG-API] Resposta RAW:', resp);
    console.log('[DEBUG-API] Resposta DATA:', resp.data);

    // Debug detalhado de mensagens de mídia
    if (resp.data && resp.data.messages) {
      const mediaMessages = resp.data.messages.filter((m: any) =>
        m.type === 'audio' || m.type === 'image' || m.type === 'video'
      );
      console.log(`[DEBUG-API] Total: ${resp.data.messages.length}, Mídia: ${mediaMessages.length}`);
    }

    // Verificar se a resposta tem a estrutura esperada
    if (!resp.data || !resp.data.messages) {
      console.error('[DEBUG-API] Resposta inválida ou vazia:', resp.data);
      // Retornar uma resposta padrão vazia para evitar erros
      return {
        messages: [],
        pagination: {
          totalCount: 0,
          hasMore: false,
          nextId: null,      // Ensure strict typing matches
          nextTimestamp: null // Ensure strict typing matches
        }
      };
    }

    // Processar as mensagens para o formato esperado pelo frontend
    const processedMessages = resp.data.messages.map((m: any) => {
      const messageDate = new Date(m.timestamp);
      const content = m.type === 'contact' && m.contact ? m.contact : m.content;
      return {
        id: m.id.toString(),
        type: m.type,
        content,
        sender: {
          phone: m.sender.phone,
          name: m.sender.name,
          photo: m.sender.photo || '',
        },
        timestamp: messageDate.toLocaleTimeString(),
        timestampNumber: m.timestampNumber || messageDate.getTime(),
        fromMe: m.fromMe,
        sequenceNumber: m.sequenceNumber,
        status: m.status || (m.fromMe ? 'sent' : undefined),
        providerMessageId: m.providerMessageId || m.messageId || undefined,
        deliveryAck: m.deliveryAck ?? undefined,
        replyTo: m.replyTo || null,
        reactions: Array.isArray(m.reactions) ? m.reactions : []
      } as OptimizedMessage;
    }).filter(m => {
      // Filtra mensagens inválidas ou desconhecidas que podem quebrar o layout
      if (m.type === 'unknown' || (!m.content && m.type !== 'image' && m.type !== 'video' && m.type !== 'audio' && m.type !== 'nps' && m.type !== 'contact')) {
        return false;
      }
      return true;
    });

    return {
      messages: processedMessages,
      pagination: resp.data.pagination || { totalCount: processedMessages.length, hasMore: false }
    };
  } catch (error) {
    console.error('Erro ao obter mensagens paginadas:', error);
    // Retornamos um objeto vazio mas válido em caso de erro
    return {
      messages: [],
      pagination: {
        totalCount: 0,
        hasMore: false
      }
    };
  }
}

/**
 * Classe WebSocketManager que gerencia uma única conexão WebSocket
 * com subscrição a múltiplos tópicos (contatos).
 */
export class UnifiedWebSocketManager {
  private ws: WebSocket | null = null;
  private isConnecting: boolean = false;
  private topics: Set<string> = new Set();
  private messageHandlers: Map<string, ((message: any) => void)[]> = new Map();
  private connectionStatusHandlers: ((connected: boolean) => void)[] = [];
  private reconnectTimer: any = null;
  private reconnectAttempts: number = 0;

  /**
   * Obtém a URL do WebSocket unificado.
   */
  private getWebSocketUrl(): string {
    const rawCompanyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
    if (!rawCompanyId) {
      throw new Error('company_id ausente no localStorage. Não é possível prosseguir.');
    }

    const companyId = parseInt(rawCompanyId, 10);
    if (!companyId) {
      throw new Error(`company_id inválido (${rawCompanyId}).`);
    }

    // Junta os tópicos em uma string separada por vírgula
    const topicsStr = Array.from(this.topics).join(',');

    // Decide se será wss:// ou ws:// com base em API_URL ou window.location
    let protocol = 'ws';
    let domain = '';

    if (API_URL === '' || API_URL.startsWith('/')) {
      // Se for URL relativa ou vazia (proxy mode), usa o host atual (ex: localhost:3004)
      // Se window.location.protocol for https:, usa wss:
      protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
      domain = window.location.host + (API_URL || ''); // ex: localhost:3004
    } else {
      // Se for absoluta (http://...)
      protocol = API_URL.startsWith('https') ? 'wss' : 'ws';
      domain = API_URL.replace(/^https?:\/\//, '');
    }

    // Remover barra final do domain, se houver, pra não duplicar
    if (domain.endsWith('/')) {
      domain = domain.slice(0, -1);
    }

    // Monta a URL final com query params
    const wsUrl = (
      `${protocol}://${domain}/api/chat-optimized/ws/unified` +
      `?company_id=${encodeURIComponent(String(companyId))}` +
      `&topics=${encodeURIComponent(topicsStr)}`
    );
    console.log('[DEBUG-WS] Connecting to:', wsUrl);
    return wsUrl;
  }

  // Adicione este método na classe UnifiedWebSocketManager
  public broadcastMessage(message: any): void {
    if (message) {
      console.log('[DEBUG-WS] Broadcast message:', message);
      if (message.phone) {
        // Cria um evento personalizado com os dados da mensagem
        const updateEvent = new CustomEvent('unified-message-received', {
          detail: message
        });
        window.dispatchEvent(updateEvent);
      }
    }
  }


  /**
   * Conecta ao WebSocket, se ainda não estiver conectado.
   */
  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN || this.isConnecting) {
      return;
    }

    this.isConnecting = true;

    try {
      const wsUrl = this.getWebSocketUrl();
      console.log('[UnifiedWS] Conectando em:', wsUrl);

      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        console.log('[UnifiedWS] Conexão estabelecida');
        this.isConnecting = false;
        this.reconnectAttempts = 0;
        this.notifyConnectionStatus(true);
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          console.log('[UnifiedWS] Mensagem recebida:', data);

          // Se for mensagem de conexão estabelecida, ignoramos
          if (data.type === 'connection_established') {
            return;
          }

          // Processar a mensagem recebida
          this.processMessage(data);
        } catch (error) {
          console.error('[UnifiedWS] Erro ao processar mensagem:', error);
        }
      };

      this.ws.onclose = (event) => {
        console.warn('[UnifiedWS] Conexão fechada:', event.code, event.reason);
        this.isConnecting = false;
        this.ws = null;
        this.notifyConnectionStatus(false);

        // Tentar reconectar com backoff exponencial
        this.scheduleReconnect();
      };

      this.ws.onerror = (error) => {
        console.error('[UnifiedWS] Erro na conexão:', error);
        this.isConnecting = false;
      };
    } catch (error) {
      console.error('[UnifiedWS] Erro ao iniciar conexão:', error);
      this.isConnecting = false;
      this.scheduleReconnect();
    }
  }

  /**
   * Agenda uma tentativa de reconexão com backoff exponencial.
   */
  private scheduleReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }

    // Backoff exponencial: 1s, 2s, 4s, 8s, 16s, max 30s
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
    console.log(`[UnifiedWS] Tentando reconectar em ${delay / 1000}s...`);

    this.reconnectTimer = setTimeout(() => {
      this.reconnectAttempts++;
      this.connect();
    }, delay);
  }

  /**
   * Inscreve-se em um novo tópico (contato).
   */
  subscribe(topic: string): void {
    if (this.topics.has(topic)) {
      return;
    }

    this.topics.add(topic);

    // Se já estiver conectado, envia comando de subscribe
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        type: 'subscribe',
        topics: [topic]
      }));
    } else {
      // Se não está conectado, tenta conectar com o novo tópico
      this.connect();
    }
  }

  /**
   * Cancela a inscrição em um tópico (contato).
   */
  unsubscribe(topic: string): void {
    if (!this.topics.has(topic)) {
      return;
    }

    this.topics.delete(topic);

    // Se estiver conectado, envia comando de unsubscribe
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        type: 'unsubscribe',
        topics: [topic]
      }));
    }
  }

  /**
   * Fecha a conexão de forma limpa.
   */
  disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    if (this.ws) {
      try {
        this.ws.close(1000, 'Desconexão solicitada pelo cliente');
      } catch (error) {
        console.error('[UnifiedWS] Erro ao fechar conexão:', error);
      }

      this.ws = null;
    }

    this.isConnecting = false;
    this.notifyConnectionStatus(false);
  }

  // Adicione este método após o método broadcastMessage na classe UnifiedWebSocketManager
  public notifyGlobalListeners(data: any): void {
    // Notifica os handlers do tópico '*' (handlers globais)
    const globalHandlers = this.messageHandlers.get('*');
    if (globalHandlers) {
      globalHandlers.forEach(handler => {
        try {
          handler(data);
        } catch (error) {
          console.error('[UnifiedWS] Erro no handler global:', error);
        }
      });
    }

    // Dispara um evento customizado para qualquer componente escutando
    // MODIFIED: Dispatch event for ALL messages, not just those with phone, to allow system events
    const updateEvent = new CustomEvent('unified-message-received', {
      detail: data
    });
    window.dispatchEvent(updateEvent);
  }


  private processMessage(data: any): void {
    // Pegamos o tópico da mensagem (phone do contato)
    const topic = data.phone || '__global__';

    // Notificamos os handlers específicos do tópico
    const topicHandlers = this.messageHandlers.get(topic);
    if (topicHandlers) {
      topicHandlers.forEach(handler => {
        try {
          handler(data);
        } catch (error) {
          console.error(`[UnifiedWS] Erro no handler do tópico ${topic}:`, error);
        }
      });
    }

    // Sempre notificar os handlers globais e disparar evento window,
    // independente do tópico específico
    this.notifyGlobalListeners(data);
  }

  /**
   * Registra um handler para mensagens de um tópico específico.
   * Use '*' para receber todas as mensagens.
   */
  onMessage(topic: string, handler: (message: any) => void): () => void {
    if (!this.messageHandlers.has(topic)) {
      this.messageHandlers.set(topic, []);
    }

    this.messageHandlers.get(topic)!.push(handler);

    // Retorna uma função para remover este handler
    return () => {
      const handlers = this.messageHandlers.get(topic);
      if (handlers) {
        const index = handlers.indexOf(handler);
        if (index !== -1) {
          handlers.splice(index, 1);
        }
      }
    };
  }

  /**
   * Registra um handler para notificações de status de conexão.
   */
  onConnectionStatus(handler: (connected: boolean) => void): () => void {
    this.connectionStatusHandlers.push(handler);

    // Notifica imediatamente o status atual
    if (this.ws?.readyState === WebSocket.OPEN) {
      handler(true);
    } else {
      handler(false);
    }

    // Retorna uma função para remover este handler
    return () => {
      const index = this.connectionStatusHandlers.indexOf(handler);
      if (index !== -1) {
        this.connectionStatusHandlers.splice(index, 1);
      }
    };
  }

  /**
   * Notifica os handlers de status de conexão.
   */
  private notifyConnectionStatus(connected: boolean): void {
    this.connectionStatusHandlers.forEach(handler => {
      try {
        handler(connected);
      } catch (error) {
        console.error('[UnifiedWS] Erro no handler de status de conexão:', error);
      }
    });
  }

  /**
   * Verifica se está conectado.
   */
  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}

// Criar uma instância singleton do gerenciador
export const unifiedWebSocketManager = new UnifiedWebSocketManager();

/**
 * Hook para gerenciar o cache de mensagens para cada contato.
 * Implementa uma estratégia de LRU (Least Recently Used).
 */
export class MessageCacheManager {
  private static readonly CACHE_PREFIX = 'chat_messages_';
  private static readonly MAX_CACHE_AGE_MS = 30 * 60 * 1000; // 30 minutos
  private static readonly MAX_CACHE_ENTRIES = 20; // Máximo de conversas em cache

  /**
   * Salva mensagens no cache para um contato específico.
   */
  saveMessages(contactPhone: string, messages: OptimizedMessage[]): void {
    console.log(`[MessageCache] saveMessages chamado para ${contactPhone} com ${messages.length} mensagens`);

    // Verificar mensagens de mídia
    const mediaMessages = messages.filter(m => m.type === 'audio' || m.type === 'image' || m.type === 'video');
    console.log(`[MessageCache] Total de mensagens de mídia: ${mediaMessages.length}`);
    mediaMessages.forEach(m => {
      console.log(`[MessageCache] Salvando ${m.type} - ID: ${m.id}, content type:`, typeof m.content);
      if (typeof m.content === 'object' && m.content.url) {
        console.log(`[MessageCache] URL tem ${m.content.url.length} caracteres, começa com:`, m.content.url.substring(0, 30));
      }
    });

    try {
      const cacheKey = `${MessageCacheManager.CACHE_PREFIX}${contactPhone}`;

      // NOVA LÓGICA: Limitar o número de mensagens por contato para evitar exceder a quota
      const MAX_MESSAGES_PER_CONTACT = 200; // Ajuste este valor conforme necessário
      let messagesToSave = messages;

      if (messages.length > MAX_MESSAGES_PER_CONTACT) {
        // Se tivermos muitas mensagens, manter apenas as mais recentes
        messagesToSave = messages.slice(-MAX_MESSAGES_PER_CONTACT);
        console.log(`[MessageCache] Limitando a ${MAX_MESSAGES_PER_CONTACT} mensagens para o contato ${contactPhone}`);
      }

      // Tenta salvar com o conjunto limitado de mensagens
      try {
        localStorage.setItem(cacheKey, JSON.stringify(messagesToSave));
      } catch (storageError) {
        // Se ainda falhar, tente com ainda menos mensagens
        if (messagesToSave.length > 50) {
          console.warn(`[MessageCache] Falha com ${messagesToSave.length} mensagens, tentando com 50 mensagens`);
          messagesToSave = messages.slice(-50);
          localStorage.setItem(cacheKey, JSON.stringify(messagesToSave));
        } else {
          // Se mesmo com 50 mensagens falhar, não salve nada no cache
          console.error(`[MessageCache] Não foi possível salvar mesmo com apenas 50 mensagens, desativando cache para ${contactPhone}`);
          // Não lance erro, apenas retorne sem salvar
          return;
        }
      }

      // Salva timestamp para controle de TTL
      localStorage.setItem(`${cacheKey}_timestamp`, Date.now().toString());

      // Atualiza a lista LRU
      this.updateLRUList(contactPhone);

      // Limpa entradas antigas se necessário
      this.cleanupCache();
    } catch (error) {
      console.error('[MessageCache] Erro ao salvar mensagens:', error);
      // Não lance erro, apenas log
    }
  }

  /**
   * Obtém mensagens do cache para um contato específico.
   * Retorna null se não houver cache ou se estiver expirado.
   */
  getMessages(contactPhone: string): OptimizedMessage[] | null {
    console.log(`[MessageCache] getMessages chamado para ${contactPhone}`);
    try {
      const cacheKey = `${MessageCacheManager.CACHE_PREFIX}${contactPhone}`;
      const cachedData = localStorage.getItem(cacheKey);
      const timestampStr = localStorage.getItem(`${cacheKey}_timestamp`);

      if (!cachedData || !timestampStr) {
        console.log(`[MessageCache] Nenhum cache encontrado para ${contactPhone}`);
        return null;
      }
      console.log(`[MessageCache] Cache encontrado, tamanho: ${cachedData.length} caracteres`);

      // Verificar TTL
      const timestamp = parseInt(timestampStr, 10);
      const age = Date.now() - timestamp;

      if (age > MessageCacheManager.MAX_CACHE_AGE_MS) {
        // Cache expirou
        this.removeFromCache(contactPhone);
        return null;
      }

      // Atualiza a lista LRU (o contato foi acessado)
      this.updateLRUList(contactPhone);

      const parsedMessages = JSON.parse(cachedData);
      console.log(`[MessageCache] Recuperadas ${parsedMessages.length} mensagens do cache`);

      // 🔥 FIX CRÍTICO: Validar que todas as mensagens pertencem ao contato correto
      const validatedMessages = parsedMessages.filter((m: any) => {
        // Validar que a mensagem tem sender.phone e que corresponde ao contactPhone
        if (m.sender && m.sender.phone && m.sender.phone !== contactPhone) {
          console.warn(`[MessageCache] ⚠️ Mensagem de contato errado detectada e removida:`, {
            expectedPhone: contactPhone,
            messagePhone: m.sender.phone,
            messageId: m.id,
            type: m.type
          });
          return false;
        }
        return true;
      });

      if (validatedMessages.length !== parsedMessages.length) {
        console.warn(`[MessageCache] 🧹 Removidas ${parsedMessages.length - validatedMessages.length} mensagens de contatos errados`);
        // Salvar o cache limpo
        this.saveMessages(contactPhone, validatedMessages);
      }

      // Verificar mensagens de mídia
      const mediaMessages = validatedMessages.filter((m: any) => m.type === 'audio' || m.type === 'image' || m.type === 'video');
      console.log(`[MessageCache] Mensagens de mídia no cache: ${mediaMessages.length}`);
      mediaMessages.forEach((m: any) => {
        console.log(`[MessageCache] ${m.type} recuperado - ID: ${m.id}, tem URL:`,
          !!(m.content && typeof m.content === 'object' && m.content.url));
        if (m.content && typeof m.content === 'object' && m.content.url) {
          console.log(`[MessageCache] URL tem ${m.content.url.length} chars, começa com:`, m.content.url.substring(0, 30));
        }
      });

      return validatedMessages;
    } catch (error) {
      console.error('[MessageCache] Erro ao recuperar mensagens:', error);
      return null;
    }
  }

  /**
   * 🔥 FIX CRÍTICO: Limpa todos os caches de mensagens corrompidos
   * Método utilitário para resolver problemas de mistura de contatos
   */
  clearAllCorruptedCaches(): void {
    console.log('[MessageCache] 🧹 Limpando todos os caches de mensagens corrompidos...');

    try {
      const keysToRemove: string[] = [];

      // Encontrar todas as chaves de cache de mensagens
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key && key.startsWith(MessageCacheManager.CACHE_PREFIX)) {
          keysToRemove.push(key);
          // Remover também o timestamp correspondente
          const timestampKey = `${key}_timestamp`;
          keysToRemove.push(timestampKey);
        }
      }

      // Remover todas as chaves encontradas
      keysToRemove.forEach(key => {
        localStorage.removeItem(key);
      });

      console.log(`[MessageCache] ✅ Removidas ${keysToRemove.length / 2} conversas do cache`);

      // Limpar também a lista LRU se existir
      localStorage.removeItem('chat_messages_lru_list');

      console.log('[MessageCache] 🎉 Todos os caches de mensagens foram limpos com sucesso!');

    } catch (error) {
      console.error('[MessageCache] Erro ao limpar caches:', error);
    }
  }

  /**
   * Atualiza uma mensagem específica no cache ou adiciona se não existir.
   */
  updateMessage(contactPhone: string, message: OptimizedMessage): void {
    try {
      const messages = this.getMessages(contactPhone) || [];

      // Procura a mensagem pelo ID
      const index = messages.findIndex((m: OptimizedMessage) => m.id === message.id);

      if (index >= 0) {
        // Atualiza a mensagem existente
        messages[index] = message;
      } else {
        // Adiciona a nova mensagem
        messages.push(message);

        // Ordena as mensagens por timestampNumber ou sequenceNumber
        messages.sort((a: OptimizedMessage, b: OptimizedMessage) => {
          // Prefere sequenceNumber se disponível
          if (a.sequenceNumber !== undefined && b.sequenceNumber !== undefined) {
            return a.sequenceNumber - b.sequenceNumber;
          }

          // Fallback para timestampNumber
          return (a.timestampNumber || 0) - (b.timestampNumber || 0);
        });
      }

      // Salva de volta no cache
      this.saveMessages(contactPhone, messages);
    } catch (error) {
      console.error('[MessageCache] Erro ao atualizar mensagem:', error);
    }
  }

  /**
   * Remove um contato do cache.
   */
  removeFromCache(contactPhone: string): void {
    try {
      const cacheKey = `${MessageCacheManager.CACHE_PREFIX}${contactPhone}`;
      localStorage.removeItem(cacheKey);
      localStorage.removeItem(`${cacheKey}_timestamp`);

      // Remove da lista LRU
      const lruList = this.getLRUList();
      const updatedList = lruList.filter(phone => phone !== contactPhone);
      this.saveLRUList(updatedList);
    } catch (error) {
      console.error('[MessageCache] Erro ao remover do cache:', error);
    }
  }

  /**
   * Limpa todo o cache de mensagens.
   */
  clearAllCache(): void {
    try {
      // Obtém a lista de contatos em cache
      const lruList = this.getLRUList();

      // Remove cada entrada
      lruList.forEach(contactPhone => {
        this.removeFromCache(contactPhone);
      });

      // Limpa a lista LRU
      this.saveLRUList([]);
    } catch (error) {
      console.error('[MessageCache] Erro ao limpar cache:', error);
    }
  }

  /**
   * Obtém a lista LRU de contatos em cache.
   */
  private getLRUList(): string[] {
    try {
      const lruData = localStorage.getItem('chat_lru_list');
      return lruData ? JSON.parse(lruData) : [];
    } catch (error) {
      console.error('[MessageCache] Erro ao obter lista LRU:', error);
      return [];
    }
  }

  /**
   * Salva a lista LRU.
   */
  private saveLRUList(list: string[]): void {
    try {
      localStorage.setItem('chat_lru_list', JSON.stringify(list));
    } catch (error) {
      console.error('[MessageCache] Erro ao salvar lista LRU:', error);
    }
  }

  /**
   * Atualiza a lista LRU quando um contato é acessado.
   */
  private updateLRUList(contactPhone: string): void {
    try {
      const lruList = this.getLRUList();

      // Remove o contato da lista (se existir)
      const updatedList = lruList.filter(phone => phone !== contactPhone);

      // Adiciona o contato no início (mais recentemente usado)
      updatedList.unshift(contactPhone);

      // Salva a lista atualizada
      this.saveLRUList(updatedList);
    } catch (error) {
      console.error('[MessageCache] Erro ao atualizar lista LRU:', error);
    }
  }

  /**
   * Limpa as entradas mais antigas do cache, se exceder o máximo.
   */
  private cleanupCache(): void {
    try {
      const lruList = this.getLRUList();

      // Se não exceder o máximo, não faz nada
      if (lruList.length <= MessageCacheManager.MAX_CACHE_ENTRIES) {
        return;
      }

      // Remove as entradas mais antigas
      const toRemove = lruList.slice(MessageCacheManager.MAX_CACHE_ENTRIES);
      toRemove.forEach(contactPhone => {
        this.removeFromCache(contactPhone);
      });

      // Atualiza a lista LRU
      this.saveLRUList(lruList.slice(0, MessageCacheManager.MAX_CACHE_ENTRIES));
    } catch (error) {
      console.error('[MessageCache] Erro ao limpar cache antigo:', error);
    }
  }
}

// Criar uma instância singleton do gerenciador de cache
export const messageCacheManager = new MessageCacheManager();

export async function prepareAudioForZAPI(audioBlob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    try {
      console.log(`Preparando áudio para Z-API: ${audioBlob.size} bytes, tipo: ${audioBlob.type}`);

      // Verifica se o formato é compatível com WhatsApp (ogg, opus, mp3, etc.)
      const isCompatibleFormat = audioBlob.type.includes('audio/ogg') ||
        audioBlob.type.includes('audio/opus') ||
        audioBlob.type.includes('audio/mp3') ||
        audioBlob.type.includes('audio/mpeg');

      console.log(`Formato compatível com WhatsApp? ${isCompatibleFormat ? 'Sim' : 'Não'}`);

      const reader = new FileReader();

      reader.onloadend = () => {
        if (!reader.result) {
          reject(new Error('Falha ao converter áudio para base64'));
          return;
        }

        // Obter o resultado como string
        const base64Data = reader.result.toString();

        // Se o resultado já tiver um prefixo data:, verificar e corrigir se necessário
        if (base64Data.startsWith('data:')) {
          // Extrair partes do data URL
          const [prefix, data] = base64Data.split(',');

          // Determinar se precisamos mudar o tipo MIME para audio/ogg
          if (!prefix.includes('audio/ogg') && !prefix.includes('audio/mpeg')) {
            // Z-API prefere audio/ogg para áudios
            console.log('Corrigindo prefixo MIME para audio/ogg');
            resolve(`data:audio/ogg;base64,${data}`);
          } else {
            // O prefixo já é audio/ogg ou audio/mpeg, manter o original
            console.log('Prefixo MIME já está correto:', prefix);
            resolve(base64Data);
          }
        } else {
          // Não tem prefixo, adicionar prefix audio/ogg
          console.log('Adicionando prefixo audio/ogg ao base64');
          resolve(`data:audio/ogg;base64,${base64Data}`);
        }
      };

      reader.onerror = (error) => {
        console.error('Erro ao ler arquivo de áudio:', error);
        reject(new Error('Falha ao ler o arquivo de áudio'));
      };

      // Iniciar a leitura como data URL (base64)
      reader.readAsDataURL(audioBlob);
    } catch (error) {
      console.error('Erro ao preparar áudio para Z-API:', error);
      reject(error);
    }
  });
}

// ===============================
// INTERFACES E FUNÇÕES PÓS-CONSULTA
// ===============================

// Interfaces para mensagens pós-consulta
export interface PosConsultaMessageUpdate {
  id?: number;
  type: 'text' | 'image' | 'audio' | 'video' | 'nps';
  content: string;
}

export interface PosConsultaStepUpdate {
  id?: number;
  step_number: number;
  send_after: number;
  send_after_unit: 'days' | 'hours' | 'minutes';
  messages: PosConsultaMessageUpdate[];
}

export interface PosConsultaMessageCreate {
  type: 'text' | 'image' | 'audio' | 'video' | 'nps';
  content: string;
}

export interface PosConsultaStepCreate {
  step_number: number;
  send_after: number;
  send_after_unit: 'days' | 'hours' | 'minutes';
  messages: PosConsultaMessageCreate[];
}

export interface PosConsultaFollowUpSequenceCreate {
  company_id: number;
  name: string;
  description?: string;
  steps: PosConsultaStepCreate[];
}

export interface PosConsultaFollowUpSequenceUpdate {
  company_id: number;
  name: string;
  description?: string;
  steps: PosConsultaStepUpdate[];
}

export interface PosConsultaFollowUpSequenceResponse {
  id: number;
  name: string;
  description?: string;
  active: boolean;
}

export interface PosConsultaFollowUpSequenceDetail {
  id: number;
  company_id: number;
  name: string;
  description?: string;
  active: boolean;
  steps: Array<{
    id: number;
    step_number: number;
    send_after: number;
    send_after_unit: 'days' | 'hours' | 'minutes';
    messages: Array<{
      id: number;
      type: 'text' | 'image' | 'audio' | 'video' | 'nps';
      content: string;
    }>;
  }>;
}

// Interfaces para configuração de horários pós-consulta
export interface DailyRangePosConsulta {
  enabled: boolean;
  start: string; // formato "HH:mm"
  end: string;   // formato "HH:mm"
}

export interface PosConsultaScheduleData {
  [key: string]: DailyRangePosConsulta;
}

export interface PosConsultaScheduleCreate {
  schedule_data: PosConsultaScheduleData;
}

export interface PosConsultaScheduleUpdate {
  schedule_data: PosConsultaScheduleData;
}

export interface PosConsultaScheduleConfig {
  id: number;
  company_id: number;
  pos_consulta_sequence_id: number;
  schedule_data: PosConsultaScheduleData;
}

// ===============================
// FUNÇÕES NPS
// ===============================

export interface SendNPSParams {
  phone: string;
  question?: string;
  campaign_name?: string;
}

export const sendNPS = async (params: SendNPSParams): Promise<any> => {
  try {
    const { phone, question, campaign_name } = params;

    // Usar query parameters conforme esperado pelo backend
    const searchParams = new URLSearchParams({
      phone,
      question: question || 'Em uma escala de 1 a 5, como você avalia nosso atendimento?',
      campaign_name: campaign_name || 'manual_chat'
    });

    console.log('Enviando NPS para:', phone);
    const response = await api.post(`/api/nps/send?${searchParams.toString()}`);

    console.log('NPS enviado com sucesso:', response.data);
    return response.data;
  } catch (error) {
    console.error('Erro ao enviar NPS:', error);
    throw error;
  }
};

// Interface para parâmetros de ligação
export interface SendCallParams {
  phone: string;
  callDuration?: number;
}

// Função para fazer ligação via WhatsApp
export const sendCall = async (params: SendCallParams): Promise<any> => {
  try {
    const { phone, callDuration = 10 } = params;

    // Usar query parameters conforme esperado pelo backend
    const searchParams = new URLSearchParams({
      phone,
      callDuration: callDuration.toString()
    });

    console.log('Fazendo ligação para:', phone, 'duração:', callDuration + 's');
    const response = await api.post(`/api/call/send?${searchParams.toString()}`);

    console.log('Ligação enviada com sucesso:', response.data);
    return response.data;
  } catch (error) {
    console.error('Erro ao fazer ligação:', error);
    throw error;
  }
};

// Função para buscar métricas NPS para o Dashboard
export const getNPSDashboardMetrics = async (
  startDate?: string,
  endDate?: string,
  campaignName?: string
): Promise<NPSDashboardMetrics> => {
  try {
    const params = new URLSearchParams();
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    if (campaignName) params.append('campaign_name', campaignName);

    const response = await api.get(`/api/nps/dashboard/metrics?${params.toString()}`);
    return response.data;
  } catch (error) {
    console.error('Erro ao buscar métricas NPS:', error);
    throw error;
  }
};

// ===============================
// FUNÇÕES CRUD PÓS-CONSULTA
// ===============================

/**
 * Cria uma nova sequência de follow-up pós-consulta
 */
export async function createPosConsultaFollowUpSequence(
  companyId: number,
  payload: PosConsultaFollowUpSequenceCreate
): Promise<PosConsultaFollowUpSequenceResponse> {
  try {
    const resp = await api.post<PosConsultaFollowUpSequenceResponse>(
      `/api/pos-consulta-followups/${companyId}`,
      payload
    );
    console.log('[createPosConsultaFollowUpSequence] Sucesso:', resp.data);
    return resp.data;
  } catch (error) {
    console.error('[createPosConsultaFollowUpSequence] Erro:', error);
    throw error;
  }
}

/**
 * Busca a sequência de follow-up pós-consulta
 */
export async function getPosConsultaFollowUpSequence(
  companyId: number
): Promise<PosConsultaFollowUpSequenceDetail | null> {
  try {
    const resp = await api.get<PosConsultaFollowUpSequenceDetail>(
      `/api/pos-consulta-followups/${companyId}`,
      {
        validateStatus: (status) => {
          // Se 404, não tem sequência criada ainda
          return (status >= 200 && status < 300) || status === 404;
        },
      }
    );

    if (resp.status === 404) {
      console.log('[getPosConsultaFollowUpSequence] Nenhuma sequência encontrada.');
      return null;
    }

    console.log('[getPosConsultaFollowUpSequence] Sequência obtida:', resp.data);
    return resp.data;
  } catch (error) {
    console.error('[getPosConsultaFollowUpSequence] Erro:', error);
    throw error;
  }
}

/**
 * Atualiza uma sequência de follow-up pós-consulta
 */
export async function updatePosConsultaFollowUpSequence(
  companyId: number,
  payload: PosConsultaFollowUpSequenceUpdate
): Promise<PosConsultaFollowUpSequenceResponse> {
  try {
    const resp = await api.put<PosConsultaFollowUpSequenceResponse>(
      `/api/pos-consulta-followups/${companyId}`,
      payload
    );
    console.log('[updatePosConsultaFollowUpSequence] Sucesso:', resp.data);
    return resp.data;
  } catch (error) {
    console.error('[updatePosConsultaFollowUpSequence] Erro:', error);
    throw error;
  }
}

/**
 * Deleta uma sequência de follow-up pós-consulta
 */
export async function deletePosConsultaFollowUpSequence(
  companyId: number
): Promise<void> {
  try {
    await api.delete(`/api/pos-consulta-followups/${companyId}`);
    console.log('[deletePosConsultaFollowUpSequence] Sequência deletada com sucesso.');
  } catch (error) {
    console.error('[deletePosConsultaFollowUpSequence] Erro:', error);
    throw error;
  }
}

// ===============================
// FUNÇÕES PARA CONFIGURAÇÃO DE HORÁRIOS PÓS-CONSULTA
// ===============================

/**
 * Cria uma nova configuração de horários para pós-consulta
 */
export async function createPosConsultaScheduleConfig(
  companyId: number,
  payload: PosConsultaScheduleCreate
): Promise<{ message: string }> {
  try {
    const resp = await api.post(`/api/pos-consulta-followups/${companyId}/schedule`, payload);
    console.log('[createPosConsultaScheduleConfig] Sucesso:', resp.data);
    return resp.data;
  } catch (error) {
    console.error('[createPosConsultaScheduleConfig] Erro:', error);
    throw error;
  }
}

/**
 * Busca a configuração de horários para pós-consulta
 */
export async function getPosConsultaScheduleConfig(
  companyId: number
): Promise<PosConsultaScheduleConfig | null> {
  try {
    const resp = await api.get<PosConsultaScheduleConfig>(
      `/api/pos-consulta-followups/${companyId}/schedule`,
      {
        validateStatus: (status) => {
          return (status >= 200 && status < 300) || status === 404;
        },
      }
    );

    if (resp.status === 404) {
      return null;
    }

    return resp.data;
  } catch (error) {
    console.error('[getPosConsultaScheduleConfig] Erro:', error);
    throw error;
  }
}

/**
 * Atualiza a configuração de horários para pós-consulta
 */
export async function updatePosConsultaScheduleConfig(
  companyId: number,
  payload: PosConsultaScheduleUpdate
): Promise<{ message: string }> {
  try {
    const resp = await api.put(`/api/pos-consulta-followups/${companyId}/schedule`, payload);
    console.log('[updatePosConsultaScheduleConfig] Sucesso:', resp.data);
    return resp.data;
  } catch (error) {
    console.error('[updatePosConsultaScheduleConfig] Erro:', error);
    throw error;
  }
}

/**
 * Deleta a configuração de horários para pós-consulta
 */
export async function deletePosConsultaScheduleConfig(
  companyId: number
): Promise<{ message: string }> {
  try {
    const resp = await api.delete(`/api/pos-consulta-followups/${companyId}/schedule`);
    console.log('[deletePosConsultaScheduleConfig] Sucesso:', resp.data);
    return resp.data;
  } catch (error) {
    console.error('[deletePosConsultaScheduleConfig] Erro:', error);
    throw error;
  }
}

// ===============================
// INTERFACES PÓS-VENDA
// ===============================

export interface PosVendaMessageCreate {
  type: 'text' | 'image' | 'audio' | 'video' | 'nps';
  content: string;
}

export interface PosVendaStepCreate {
  step_number: number;
  send_after: number;
  send_after_unit: 'days' | 'hours' | 'minutes';
  messages: PosVendaMessageCreate[];
}

export interface PosVendaMessageUpdate {
  id?: number;
  type: 'text' | 'image' | 'audio' | 'video' | 'nps';
  content: string;
}

export interface PosVendaStepUpdate {
  id?: number;
  step_number: number;
  send_after: number;
  send_after_unit: 'days' | 'hours' | 'minutes';
  messages: PosVendaMessageUpdate[];
}

export interface PosVendaFollowUpSequenceCreate {
  company_id: number;
  name: string;
  description: string;
  steps: PosVendaStepCreate[];
}

export interface PosVendaFollowUpSequenceUpdate {
  company_id: number;
  name: string;
  description: string;
  steps: PosVendaStepUpdate[];
}

export interface PosVendaFollowUpSequenceResponse {
  message: string;
  sequence_id: number;
}

export interface PosVendaFollowUpSequenceDetail {
  id: number;
  company_id: number;
  name: string;
  description: string;
  active: boolean;
  steps: Array<{
    id: number;
    step_number: number;
    send_after: number;
    send_after_unit: 'days' | 'hours' | 'minutes';
    messages: Array<{
      id: number;
      type: 'text' | 'image' | 'audio' | 'video' | 'nps';
      content: string;
    }>;
  }>;
}

// Interfaces para configuração de horários pós-venda
export interface DailyRangePosVenda {
  enabled: boolean;
  start: string; // formato "HH:mm"
  end: string;   // formato "HH:mm"
}

export interface PosVendaScheduleData {
  [key: string]: DailyRangePosVenda;
}

export interface PosVendaScheduleCreate {
  schedule_data: PosVendaScheduleData;
}

export interface PosVendaScheduleUpdate {
  schedule_data: PosVendaScheduleData;
}

export interface PosVendaScheduleConfig {
  id: number;
  company_id: number;
  pos_venda_sequence_id: number;
  schedule_data: PosVendaScheduleData;
}

// ===============================
// FUNÇÕES CRUD PÓS-VENDA
// ===============================

/**
 * Cria uma nova sequência de follow-up pós-venda
 */
export async function createPosVendaFollowUpSequence(
  companyId: number,
  payload: PosVendaFollowUpSequenceCreate
): Promise<PosVendaFollowUpSequenceResponse> {
  try {
    const resp = await api.post<PosVendaFollowUpSequenceResponse>(
      `/api/pos-venda-followups/${companyId}`,
      payload
    );
    console.log('[createPosVendaFollowUpSequence] Sucesso:', resp.data);
    return resp.data;
  } catch (error) {
    console.error('[createPosVendaFollowUpSequence] Erro:', error);
    throw error;
  }
}

/**
 * Busca a sequência de follow-up pós-venda
 */
export async function getPosVendaFollowUpSequence(
  companyId: number
): Promise<PosVendaFollowUpSequenceDetail | null> {
  try {
    const resp = await api.get<PosVendaFollowUpSequenceDetail>(
      `/api/pos-venda-followups/${companyId}`,
      {
        validateStatus: (status) => {
          // Se 404, não tem sequência criada ainda
          return (status >= 200 && status < 300) || status === 404;
        },
      }
    );

    if (resp.status === 404) {
      console.log('[getPosVendaFollowUpSequence] Nenhuma sequência encontrada.');
      return null;
    }

    console.log('[getPosVendaFollowUpSequence] Sequência obtida:', resp.data);
    return resp.data;
  } catch (error) {
    console.error('[getPosVendaFollowUpSequence] Erro:', error);
    throw error;
  }
}

/**
 * Atualiza uma sequência de follow-up pós-venda
 */
export async function updatePosVendaFollowUpSequence(
  companyId: number,
  payload: PosVendaFollowUpSequenceUpdate
): Promise<PosVendaFollowUpSequenceResponse> {
  try {
    const resp = await api.put<PosVendaFollowUpSequenceResponse>(
      `/api/pos-venda-followups/${companyId}`,
      payload
    );
    console.log('[updatePosVendaFollowUpSequence] Sucesso:', resp.data);
    return resp.data;
  } catch (error) {
    console.error('[updatePosVendaFollowUpSequence] Erro:', error);
    throw error;
  }
}

/**
 * Deleta uma sequência de follow-up pós-venda
 */
export async function deletePosVendaFollowUpSequence(
  companyId: number
): Promise<{ message: string }> {
  try {
    const resp = await api.delete<{ message: string }>(
      `/api/pos-venda-followups/${companyId}`
    );
    console.log('[deletePosVendaFollowUpSequence] Sequência deletada com sucesso.');
    return resp.data;
  } catch (error) {
    console.error('[deletePosVendaFollowUpSequence] Erro:', error);
    throw error;
  }
}

// ===============================
// FUNÇÕES PARA CONFIGURAÇÃO DE HORÁRIOS PÓS-VENDA
// ===============================

/**
 * Cria uma nova configuração de horários para pós-venda
 */
export async function createPosVendaScheduleConfig(
  companyId: number,
  payload: PosVendaScheduleCreate
): Promise<{ message: string; config_id: number }> {
  try {
    const resp = await api.post(`/api/pos-venda-followups/${companyId}/schedule`, payload);
    console.log('[createPosVendaScheduleConfig] Sucesso:', resp.data);
    return resp.data;
  } catch (error) {
    console.error('[createPosVendaScheduleConfig] Erro:', error);
    throw error;
  }
}

/**
 * Busca a configuração de horários para pós-venda
 */
export async function getPosVendaScheduleConfig(
  companyId: number
): Promise<PosVendaScheduleConfig | null> {
  try {
    const resp = await api.get<PosVendaScheduleConfig>(
      `/api/pos-venda-followups/${companyId}/schedule`,
      {
        validateStatus: (status) => {
          return (status >= 200 && status < 300) || status === 404;
        },
      }
    );

    if (resp.status === 404) {
      return null;
    }

    return resp.data;
  } catch (error) {
    console.error('[getPosVendaScheduleConfig] Erro:', error);
    throw error;
  }
}

/**
 * Atualiza a configuração de horários para pós-venda
 */
export async function updatePosVendaScheduleConfig(
  companyId: number,
  payload: PosVendaScheduleUpdate
): Promise<{ message: string; config_id: number }> {
  try {
    const resp = await api.put(`/api/pos-venda-followups/${companyId}/schedule`, payload);
    console.log('[updatePosVendaScheduleConfig] Sucesso:', resp.data);
    return resp.data;
  } catch (error) {
    console.error('[updatePosVendaScheduleConfig] Erro:', error);
    throw error;
  }
}

/**
 * Deleta a configuração de horários para pós-venda
 */
export async function deletePosVendaScheduleConfig(
  companyId: number
): Promise<{ message: string }> {
  try {
    const resp = await api.delete(`/api/pos-venda-followups/${companyId}/schedule`);
    console.log('[deletePosVendaScheduleConfig] Sucesso:', resp.data);
    return resp.data;
  } catch (error) {
    console.error('[deletePosVendaScheduleConfig] Erro:', error);
    throw error;
  }
}

// ================================================================
// NUTRITION CAMPAIGN API FUNCTIONS
// ================================================================

export interface NutritionCampaignSequence {
  id?: number;
  name: string;
  description?: string;
  active: boolean;
  target_contact_status?: string[];
  target_contact_categories?: string[];
  target_contact_tags?: string[];
  message_delay_min: number;
  message_delay_max: number;
  created_at?: string;
  updated_at?: string;
  steps?: NutritionCampaignStep[];
}

export interface NutritionCampaignStep {
  id?: number;
  step_number: number;
  send_after: number;
  send_after_unit: 'minutes' | 'hours' | 'days';
  random_delay_min: number;
  random_delay_max: number;
  created_at?: string;
  updated_at?: string;
  messages?: NutritionCampaignMessage[];
}

export interface NutritionCampaignMessage {
  id?: number;
  type: 'text' | 'image' | 'audio' | 'video' | 'nps';
  content: string;
  created_at?: string;
  updated_at?: string;
}

/**
 * Lista todas as sequências de campanha de nutrição
 */
export async function getNutritionCampaignSequences(): Promise<{
  success: boolean;
  sequences: NutritionCampaignSequence[];
}> {
  try {
    const resp = await api.get('/api/nutrition-campaigns/sequences');
    return resp.data;
  } catch (error) {
    console.error('[getNutritionCampaignSequences] Erro:', error);
    throw error;
  }
}

/**
 * Cria uma nova sequência de campanha de nutrição
 */
export async function createNutritionCampaignSequence(
  sequence: Omit<NutritionCampaignSequence, 'id' | 'created_at' | 'updated_at'>
): Promise<{ success: boolean; message: string; sequence_id: number }> {
  try {
    const resp = await api.post('/api/nutrition-campaigns/sequences', sequence);
    return resp.data;
  } catch (error) {
    console.error('[createNutritionCampaignSequence] Erro:', error);
    throw error;
  }
}

/**
 * Lança uma campanha de nutrição
 */
export async function launchNutritionCampaign(
  sequenceId?: number
): Promise<{ success: boolean; message: string }> {
  try {
    const resp = await api.post('/api/nutrition-campaigns/launch', {
      sequence_id: sequenceId
    });
    return resp.data;
  } catch (error) {
    console.error('[launchNutritionCampaign] Erro:', error);
    throw error;
  }
}

/**
 * Obtém estatísticas das campanhas de nutrição
 */
export async function getNutritionCampaignStats(): Promise<{
  success: boolean;
  stats: Array<{
    sequence_name: string;
    total_executions: number;
    successful_executions: number;
    failed_executions: number;
    scheduled_executions: number;
    processing_executions: number;
  }>;
}> {
  try {
    const resp = await api.get('/api/nutrition-campaigns/stats');
    return resp.data;
  } catch (error) {
    console.error('[getNutritionCampaignStats] Erro:', error);
    throw error;
  }
}

/**
 * Obtém preview dos contatos que serão atingidos pelos critérios de targeting
 */
export async function getNutritionTargetingPreview(criteria: {
  target_contact_status?: string[];
  target_contact_categories?: string[];
  target_contact_tags?: string[];
}): Promise<{
  success: boolean;
  total_contacts: number;
  contacts: Array<{
    id: number;
    name: string;
    phone: string;
    status: string;
    categoria: string;
    tags: string[];
  }>;
}> {
  try {
    const params = new URLSearchParams();

    if (criteria.target_contact_status) {
      criteria.target_contact_status.forEach(status =>
        params.append('target_contact_status', status)
      );
    }

    if (criteria.target_contact_categories) {
      criteria.target_contact_categories.forEach(category =>
        params.append('target_contact_categories', category)
      );
    }

    if (criteria.target_contact_tags) {
      criteria.target_contact_tags.forEach(tag =>
        params.append('target_contact_tags', tag)
      );
    }

    const resp = await api.get(`/api/nutrition-campaigns/targeting/preview?${params}`);
    return resp.data;
  } catch (error) {
    console.error('[getNutritionTargetingPreview] Erro:', error);
    throw error;
  }
}



/**
 * Salva configuração de horários para uma sequência de campanha de nutrição
 */
export async function saveNutritionCampaignScheduleConfig(
  sequenceId: number,
  scheduleData: any
): Promise<{ success: boolean; message: string }> {
  try {
    const resp = await api.post(`/api/nutrition-campaigns/sequences/${sequenceId}/schedule`, {
      schedule_data: scheduleData
    });
    return resp.data;
  } catch (error) {
    console.error('[saveNutritionCampaignScheduleConfig] Erro:', error);
    throw error;
  }
}

// ==========================================
// EVOLUTION API - Gestão de Instâncias
// ==========================================

/**
 * Conecta uma empresa ao Evolution API
 * Cria uma nova instância e salva no banco
 */
export async function connectEvolution(instanceName: string, phoneNumber?: string): Promise<{ message: string; instance_name: string }> {
  const payload: { instance_name: string; phone_number?: string } = {
    instance_name: instanceName,
  };

  if (phoneNumber) {
    payload.phone_number = phoneNumber;
  }

  const response = await api.post('/webhook/evolution/connect', payload);
  return response.data;
}

/**
 * Obtém a configuração Evolution da empresa logada
 */
export async function getEvolutionConfig(): Promise<{
  instance_id: string;
  api_url: string;
}> {
  const response = await api.get('/webhook/evolution/config');
  return response.data;
}

/**
 * Interface para dados de conexão Evolution (QR Code ou Pairing Code)
 */
export interface EvolutionConnectionData {
  mode: 'qr' | 'pairing';
  qrcode?: string;          // Se mode=qr
  pairingCode?: string;     // Se mode=pairing
  cached?: boolean;
  fresh?: boolean;
  age_seconds?: number;
  fallback?: boolean;       // Se true, Evolution retornou modo diferente do solicitado
}

/**
 * Obtém conexão Evolution (QR Code ou Pairing Code)
 * @param forceRefresh - Se true, força busca de novo código ignorando cache
 * @param mode - 'qr' para QR Code, 'pairing' para Pairing Code
 * @param phoneNumber - Número de telefone com código do país (ex: 5500000000003) - usado para pairing code
 */
export async function getEvolutionConnection(
  forceRefresh: boolean = false,
  mode: 'qr' | 'pairing' = 'qr',
  phoneNumber?: string
): Promise<EvolutionConnectionData> {
  const params: any = { force_refresh: forceRefresh, mode };

  if (mode === 'pairing' && phoneNumber) {
    params.phone_number = phoneNumber;
  }

  const response = await api.get('/webhook/evolution/qrcode', { params });
  return response.data;
}

/**
 * Obtém o QR Code para conectar o WhatsApp
 * @param forceRefresh - Se true, força busca de novo QR code ignorando cache
 * @deprecated Use getEvolutionConnection() com mode='qr' para mais flexibilidade
 */
export async function getEvolutionQRCode(forceRefresh: boolean = false): Promise<{ qrcode: string }> {
  const data = await getEvolutionConnection(forceRefresh, 'qr');
  return { qrcode: data.qrcode || '' };
}

/**
 * Obtém o status da conexão Evolution
 */
export async function getEvolutionStatus(): Promise<{
  connected: boolean;
  state: string;
}> {
  const response = await api.get('/webhook/evolution/status');
  return response.data;
}

/**
 * Obtém dados do device conectado (WhatsApp)
 */
export async function getEvolutionDevice(): Promise<{
  id: string;
  name: string;
  phone: string;
  imgUrl: string;
  isBusiness: boolean;
  device: {
    sessionName: string;
    device_model: string;
  };
}> {
  const response = await api.get('/webhook/evolution/device');
  return response.data;
}

/**
 * Desconecta a instância Evolution (logout do WhatsApp)
 */
export async function disconnectEvolution(): Promise<{ message: string }> {
  const response = await api.post('/webhook/evolution/disconnect');
  return response.data;
}

/**
 * Reseta completamente a configuração Evolution da empresa
 */
export async function resetEvolution(): Promise<{ message: string }> {
  const response = await api.post('/webhook/evolution/reset');
  return response.data;
}

// ==========================================
// WPPCONNECT - Gestão de Sessões
// ==========================================

/**
 * Conecta uma empresa ao WPPConnect
 * Cria uma nova sessão e salva no banco
 */
export async function connectWPPConnect(sessionName: string): Promise<{
  message: string;
  session_name: string;
  status: string;
}> {
  const payload = {
    session_name: sessionName,
  };

  const response = await api.post('/webhook/wppconnect/connect', payload);
  return response.data;
}

/**
 * Obtém a configuração WPPConnect da empresa logada
 */
export async function getWPPConnectConfig(): Promise<{
  session_name: string;
  secret_key: string;
  base_url: string;
}> {
  const response = await api.get('/webhook/wppconnect/config');
  return response.data;
}

/**
 * Obtém o QR Code para conectar o WhatsApp via WPPConnect
 */
export async function getWPPConnectQRCode(): Promise<{
  qrcode: string;
  session_name: string;
}> {
  const response = await api.get('/webhook/wppconnect/qrcode');
  return response.data;
}

/**
 * Obtém o status da conexão WPPConnect
 */
export async function getWPPConnectStatus(): Promise<{
  connected: boolean;
  status: string;
  session: string;
}> {
  const response = await api.get('/webhook/wppconnect/status');
  return response.data;
}

/**
 * Obtém dados do device conectado (WhatsApp) via WPPConnect
 */
export async function getWPPConnectDevice(): Promise<{
  id: string;
  name: string;
  phone?: string;
  profilePicUrl?: string;
  status: string;
  connected: boolean;
  isBusiness?: boolean;
  device: {
    sessionName: string;
    device_model: string;
    pushname?: string;
    phone?: string;
    wid?: string;
    platform?: string;
  };
}> {
  const response = await api.get('/webhook/wppconnect/device');
  return response.data;
}

/**
 * Desconecta a sessão WPPConnect (logout do WhatsApp)
 */
export async function disconnectWPPConnect(): Promise<{ message: string }> {
  const response = await api.post('/webhook/wppconnect/disconnect');
  return response.data;
}

/**
 * Reseta completamente a configuração WPPConnect da empresa
 */
export async function resetWPPConnect(): Promise<{ message: string }> {
  const response = await api.post('/webhook/wppconnect/reset');
  return response.data;
}

// ==========================================
// WAHA FUNCTIONS (WhatsApp HTTP API)
// ==========================================

/**
 * Verifica o status detalhado da sessão WAHA
 */
export async function getWahaSessionStatus(): Promise<{
  name: string;
  status: string;
  connected: boolean;
  needsQR: boolean;
  needsStart: boolean;
  failed?: boolean;
  message?: string | null;
  me?: {
    id: string;
    pushName: string;
  };
}> {
  const response = await api.get('/webhook/whatsapp/waha/session-status');
  return response.data;
}

/**
 * Inicia uma sessão WAHA (se estiver STOPPED)
 */
export async function startWahaSession(): Promise<{
  message: string;
  sessionStatus: string;
  nextStep: string;
}> {
  const response = await api.post('/webhook/whatsapp/waha/start-session');
  return response.data;
}

/**
 * Solicita um código de pareamento para conectar o WAHA pelo número do telefone.
 */
export async function requestWahaPairingCode(phoneNumber: string): Promise<{
  message: string;
  sessionName: string;
  phoneNumber: string;
  pairingCode: string;
}> {
  const response = await api.post('/webhook/whatsapp/waha/request-code', {
    phone_number: phoneNumber,
  });
  return response.data;
}

/**
 * Para/desconecta uma sessão WAHA (útil para resetar estado FAILED)
 */
export async function stopWahaSession(): Promise<{
  message: string;
}> {
  const response = await api.get('/webhook/whatsapp/disconnect');
  return response.data;
}

export async function connectWaha(): Promise<{
  message: string;
  session_name: string;
  session_status: string;
}> {
  const response = await api.post('/webhook/whatsapp/connect-waha');
  return response.data;
}

/**
 * Busca e salva a configuração do WhatsApp da empresa
 */
export async function fetchCompanyWhatsAppConfig(companyId: number): Promise<any> {
  try {
    console.log('[fetchCompanyWhatsAppConfig] Buscando configuração para empresa (via token):', companyId);
    // Usa endpoint que retorna dados da empresa do usuário logado
    const response = await api.get(`/api/company`);
    const data = response.data;

    if (data && data.company && data.company.whatsapp_config) {
      console.log('[fetchCompanyWhatsAppConfig] Configuração encontrada e salva:', data.company.whatsapp_config);
      localStorage.setItem('company_whatsapp_config', JSON.stringify(data.company.whatsapp_config));
      return data.company.whatsapp_config;
    }
    return null;
  } catch (error) {
    console.error('[fetchCompanyWhatsAppConfig] Erro ao buscar configuração:', error);
    return null;
  }
}

// ============= FUNÇÕES MULTI-PROVIDER =============

/**
 * Detecta qual provider WhatsApp está configurado para a empresa
 */
export function detectWhatsAppProvider(config?: any): WhatsAppProviderInfo | null {
  console.log('[WhatsAppProvider] Iniciando detecção do provider');
  console.log('[WhatsAppProvider] Config recebida:', config);

  // Se não for passada config, usar do localStorage
  if (!config) {
    const storedConfig = localStorage.getItem('company_whatsapp_config');
    if (storedConfig) {
      config = JSON.parse(storedConfig);
    }
  }

  console.log('[WhatsAppProvider] Config final usada:', config);

  if (!config) {
    console.warn('[WhatsAppProvider] Nenhuma configuração encontrada');
    return null;
  }

  // A configuração pode estar direta ou aninhada em whatsapp_config
  const whatsappConfig = config.whatsapp_config || config;

  console.log('[WhatsAppProvider] WhatsApp config extraída:', whatsappConfig);

  // Log detalhado das configurações Waha
  console.log('[WhatsAppProvider] Verificando configurações Waha:');
  console.log('  - waha_enabled:', whatsappConfig.waha_enabled);
  console.log('  - waha_session_name:', whatsappConfig.waha_session_name);
  console.log('  - waha_enabled type:', typeof whatsappConfig.waha_enabled);
  console.log('  - waha_session_name type:', typeof whatsappConfig.waha_session_name);

  // Prioridade: WAHA > Evolution > WPPConnect > Z-API
  if (whatsappConfig.waha_enabled && whatsappConfig.waha_session_name) {
    console.log('[WhatsAppProvider] Detectado WAHA (WhatsApp HTTP API)');
    return {
      provider: 'waha',
      config: {
        session_name: whatsappConfig.waha_session_name,
      }
    };
  }

  console.log('[WhatsAppProvider] Waha não configurado, verificando Evolution...');
  if (whatsappConfig.evolution_instance_id) {
    console.log('[WhatsAppProvider] Detectado Evolution API');
    return {
      provider: 'evolution',
      config: {
        instance_id: whatsappConfig.evolution_instance_id
      }
    };
  }

  console.log('[WhatsAppProvider] Evolution não configurado, verificando WPPConnect...');
  if (whatsappConfig.wppconnect_session_name) {
    console.log('[WhatsAppProvider] Detectado WPPConnect');
    return {
      provider: 'wppconnect',
      config: {
        session_name: whatsappConfig.wppconnect_session_name,
        base_url: whatsappConfig.wppconnect_base_url || 'http://localhost:21465'
      }
    };
  }

  console.log('[WhatsAppProvider] WPPConnect não configurado, verificando Z-API...');
  if (whatsappConfig.zapi_instance_id) {
    console.log('[WhatsAppProvider] Detectado Z-API (legado)');
    return {
      provider: 'zapi',
      config: {
        instance_id: whatsappConfig.zapi_instance_id
      }
    };
  }

  console.warn('[WhatsAppProvider] Nenhum provider configurado');
  console.warn('[WhatsAppProvider] Resumo da configuração:', {
    waha_enabled: whatsappConfig.waha_enabled,
    waha_session_name: whatsappConfig.waha_session_name,
    evolution_instance_id: whatsappConfig.evolution_instance_id,
    wppconnect_session_name: whatsappConfig.wppconnect_session_name,
    zapi_instance_id: whatsappConfig.zapi_instance_id,
  });

  return null;
}

/**
 * Envia mensagem de texto usando o provider detectado automaticamente
 */
export async function sendWhatsAppTextMultiProvider({ phone, message, localMessageId, replyTo }: SendTextParams): Promise<any> {
  let providerInfo = detectWhatsAppProvider();

  if (!providerInfo) {
    // Tenta buscar do backend se não tiver no localStorage
    const companyId = parseInt((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')) || '0');
    if (companyId) {
      await fetchCompanyWhatsAppConfig(companyId);
      providerInfo = detectWhatsAppProvider();
    }
  }

  if (!providerInfo) {
    throw new Error('Nenhum provider WhatsApp configurado');
  }

  console.log(`[WhatsAppMulti] Enviando texto via ${providerInfo.provider}`);

  if (providerInfo.provider === 'zapi') {
    // Usa função existente para Z-API
    return await sendWhatsAppText({ phone, message, localMessageId, replyTo });
  }

  // Para outros providers, usa endpoint unificado do backend
  const companyId = localStorage.getItem("company_id");
  let finalClientId = localStorage.getItem("client_id");
  const url = `/webhook/send-text?client_id=${finalClientId}&company_id=${companyId}`;

  const body: any = { phone, message, provider: providerInfo.provider };
  if (localMessageId) {
    body.localMessageId = localMessageId;
  }
  if (replyTo) {
    body.replyTo = replyTo;
  }

  const resp = await api.post(url, body, {
    headers: { 'Content-Type': 'application/json' },
  });

  return resp.data;
}

/**
 * Envia imagem usando o provider detectado automaticamente
 */
export async function sendWhatsAppImageMultiProvider(params: SendImageParams): Promise<any> {
  let providerInfo = detectWhatsAppProvider();

  if (!providerInfo) {
    const companyId = parseInt((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')) || '0');
    if (companyId) {
      await fetchCompanyWhatsAppConfig(companyId);
      providerInfo = detectWhatsAppProvider();
    }
  }

  if (!providerInfo) {
    throw new Error('Nenhum provider WhatsApp configurado');
  }

  console.log(`[WhatsAppMulti] Enviando imagem via ${providerInfo.provider}`);

  if (providerInfo.provider === 'zapi') {
    // Usa função existente para Z-API
    return await sendWhatsAppImage(params);
  }

  // Para outros providers, usa endpoint unificado do backend
  const companyId = localStorage.getItem("company_id");
  let finalClientId = localStorage.getItem("client_id");
  const url = `/webhook/send-image?client_id=${finalClientId}&company_id=${companyId}`;

  const body = { ...params, provider: providerInfo.provider };

  const resp = await api.post(url, body, {
    headers: { 'Content-Type': 'application/json' },
  });

  return resp.data;
}

/**
 * Envia vídeo usando o provider detectado automaticamente
 */
export async function sendWhatsAppVideoMultiProvider(params: SendVideoParams): Promise<any> {
  let providerInfo = detectWhatsAppProvider();

  if (!providerInfo) {
    const companyId = parseInt((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')) || '0');
    if (companyId) {
      await fetchCompanyWhatsAppConfig(companyId);
      providerInfo = detectWhatsAppProvider();
    }
  }

  if (!providerInfo) {
    throw new Error('Nenhum provider WhatsApp configurado');
  }

  console.log(`[WhatsAppMulti] Enviando vídeo via ${providerInfo.provider}`);

  // Para provider "zapi", precisaríamos chamar a func específica se existisse ou usar endpoint genérico?
  // Como o webhook/send-video do backend já trata Z-API (base64) e WAHA (URL), podemos usar o endpoint unificado para TODOS
  // MAS, se tivermos função específica legada, podemos manter.
  // Por consistência com as outras func MultiProvider, vamos priorizar o backend unificado se possível, ou ramificar.

  // Como não temos sendWhatsAppVideo "legacy" frontend function facilmente visível (talvez tenha),
  // vamos usar direto o backend que já trata tudo.

  if (providerInfo.provider === 'zapi') {
    // Usa função existente para Z-API
    return await sendWhatsAppVideo(params);
  }

  // Para outros providers, usa endpoint unificado do backend
  const companyId = localStorage.getItem("company_id");
  let finalClientId = localStorage.getItem("client_id");

  const url = `/webhook/send-video?client_id=${finalClientId}&company_id=${companyId}`;

  const body = {
    phone: params.phone,
    video: params.video, // Backend espera "video" (pode ser URL p/ WAHA/WPP ou base64 p/ Z-API - backend converte se precisar)
    caption: params.caption,
    provider: providerInfo.provider
  };

  const resp = await api.post(url, body, {
    headers: { 'Content-Type': 'application/json' },
  });

  return resp.data;
}

/**
 * Envia áudio usando o provider detectado automaticamente
 */
export async function sendWhatsAppAudioMultiProvider(params: SendAudioParams): Promise<any> {
  let providerInfo = detectWhatsAppProvider();

  if (!providerInfo) {
    const companyId = parseInt((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')) || '0');
    if (companyId) {
      await fetchCompanyWhatsAppConfig(companyId);
      providerInfo = detectWhatsAppProvider();
    }
  }

  if (!providerInfo) {
    throw new Error('Nenhum provider WhatsApp configurado');
  }

  console.log(`[WhatsAppMulti] Enviando áudio via ${providerInfo.provider}`);

  if (providerInfo.provider === 'zapi') {
    // Usa função existente para Z-API
    return await sendWhatsAppAudio(params);
  }

  // Para outros providers, usa endpoint unificado do backend
  const companyId = localStorage.getItem("company_id");
  let finalClientId = localStorage.getItem("client_id");
  const url = `/webhook/send-audio?client_id=${finalClientId}&company_id=${companyId}`;

  const body = { ...params, provider: providerInfo.provider };

  const resp = await api.post(url, body, {
    headers: { 'Content-Type': 'application/json' },
  });

  return resp.data;
}



// Função Multi-Provider para enviar NPS
export async function sendNPSMultiProvider(params: {
  phone: string;
  question: string;
  campaign_name?: string;
  provider?: WhatsAppProvider;
}) {
  // Obter configuração da empresa
  const companyInfo = await getCompanyInfo();
  const extendedCompanyInfo = await getExtendedCompanyInfo();

  console.log('[NPSMulti] extendedCompanyInfo completo:', extendedCompanyInfo);
  console.log('[NPSMulti] extendedCompanyInfo.id:', extendedCompanyInfo?.id);

  if (!extendedCompanyInfo || !extendedCompanyInfo.whatsapp_config) {
    throw new Error('Configuração do WhatsApp não encontrada para esta empresa');
  }

  const whatsappConfig = extendedCompanyInfo.whatsapp_config;
  const providerInfo = detectWhatsAppProvider(extendedCompanyInfo);

  // Usar provider passado como parâmetro ou detectar automaticamente
  const selectedProvider = params.provider || providerInfo?.provider;

  // Obter ownClientId baseado no provider
  let rawOwnClientId = '';
  switch (selectedProvider) {
    case 'zapi':
      rawOwnClientId = whatsappConfig.zapi_instance_id || '';
      break;
    case 'waha':
      rawOwnClientId = whatsappConfig.waha_session_name || '';
      break;
    case 'evolution':
      rawOwnClientId = whatsappConfig.evolution_instance_id || '';
      break;
    case 'wppconnect':
      rawOwnClientId = whatsappConfig.wppconnect_session_name || '';
      break;
    default:
      throw new Error(`Provider WhatsApp não suportado: ${selectedProvider}`);
  }

  if (!rawOwnClientId) {
    throw new Error(`ID do WhatsApp não configurado para provider ${selectedProvider}`);
  }

  // Sanitizar ID para uso na URL
  let finalClientId = rawOwnClientId;

  // Usar endpoint unificado multi-provider para NPS
  // O endpoint espera phone como query parameter, não no body
  const url = `/api/nps/send?company_id=${extendedCompanyInfo.id}&phone=${params.phone}`;

  console.log(`[NPSMulti] Enviando NPS via ${selectedProvider} para ${params.phone} usando endpoint unificado`);
  console.log(`[NPSMulti] company_id: ${extendedCompanyInfo.id}`);

  const body = {
    question: params.question,
    campaign_name: params.campaign_name || 'manual_chat',
    context: { provider: selectedProvider }  // Enviar provider no context
  };

  console.log('[NPSMulti] Body enviado:', body);
  console.log('[NPSMulti] URL completa:', url);

  const resp = await api.post(url, body, {
    headers: { 'Content-Type': 'application/json' },
  });

  return resp.data;
}

// Função Multi-Provider para enviar chamada
export async function sendCallMultiProvider(params: {
  phone: string;
  callDuration: number;
  provider?: WhatsAppProvider;
}) {
  // Obter configuração da empresa
  const companyInfo = await getCompanyInfo();
  const extendedCompanyInfo = await getExtendedCompanyInfo();

  if (!extendedCompanyInfo || !extendedCompanyInfo.whatsapp_config) {
    throw new Error('Configuração do WhatsApp não encontrada para esta empresa');
  }

  const whatsappConfig = extendedCompanyInfo.whatsapp_config;
  const providerInfo = detectWhatsAppProvider(extendedCompanyInfo);

  // Usar provider passado como parâmetro ou detectar automaticamente
  const selectedProvider = params.provider || providerInfo?.provider;

  // Obter ownClientId baseado no provider
  let rawOwnClientId = '';
  switch (selectedProvider) {
    case 'zapi':
      rawOwnClientId = whatsappConfig.zapi_instance_id || '';
      break;
    case 'waha':
      rawOwnClientId = whatsappConfig.waha_session_name || '';
      break;
    case 'evolution':
      rawOwnClientId = whatsappConfig.evolution_instance_id || '';
      break;
    case 'wppconnect':
      rawOwnClientId = whatsappConfig.wppconnect_session_name || '';
      break;
    default:
      throw new Error(`Provider WhatsApp não suportado: ${selectedProvider}`);
  }

  if (!rawOwnClientId) {
    throw new Error(`ID do WhatsApp não configurado para provider ${selectedProvider}`);
  }

  // Sanitizar ID para uso na URL
  let finalClientId = rawOwnClientId;

  // Rotas específicas por provider
  let url = '';
  switch (selectedProvider) {
    case 'zapi':
      url = `/api/z-api/send-call?client_id=${finalClientId}&company_id=${companyInfo.id}`;
      break;
    case 'waha':
      url = `/api/waha/send-call?session=${finalClientId}&company_id=${companyInfo.id}`;
      break;
    case 'evolution':
      url = `/api/evolution/send-call?instance=${finalClientId}&company_id=${companyInfo.id}`;
      break;
    case 'wppconnect':
      url = `/api/wppconnect/send-call?session=${finalClientId}&company_id=${companyInfo.id}`;
      break;
  }

  const body = {
    phone: params.phone,
    callDuration: params.callDuration,
    provider: selectedProvider
  };

  const resp = await api.post(url, body, {
    headers: { 'Content-Type': 'application/json' },
  });

  return resp.data;
}

// ================================================================
// 🎯 NOVA FUNCIONALIDADE: Áudio Direto WAHA (Otimizado)
// ================================================================

/**
 * Interface para envio direto de áudio via WAHA
 * Formato otimizado compatível com agents_sdk
 */
export interface WahaDirectAudioParams {
  phone: string;
  audioBlob: Blob;        // Blob direto, sem base64!
  session?: string;       // Backend descobre da empresa logada se não fornecido
  companyId?: number;
  convert?: boolean;
}

/**
 * Envia áudio diretamente via WAHA com formato otimizado
 *
 * 🔥 NOVO: Performance ~60% melhor que fluxo atual
 * - Envia Blob como multipart/form-data (sem base64)
 * - Formato compatível com agents_sdk
 * - Menor processamento no frontend
 *
 * @param params Parâmetros para envio do áudio
 * @returns Promise com resposta do WAHA
 *
 * @example
 * const blob = new Blob([audioData], { type: 'audio/webm' });
 * await sendWhatsAppAudioDirect({
 *   phone: "5500000000004",
 *   audioBlob: blob,
 *   session: "default",
 *   companyId: 68
 * });
 */
export async function sendWhatsAppAudioDirect(params: WahaDirectAudioParams): Promise<any> {
  console.log("[WAHA Direct Audio] 🚀 Enviando áudio via WAHA (formato otimizado)");
  console.log("[WAHA Direct Audio] 📊 Parâmetros:", {
    phone: params.phone,
    session: params.session,
    audioSize: params.audioBlob.size,
    audioType: params.audioBlob.type,
    companyId: params.companyId
  });

  try {
    // Validar parâmetros
    if (!params.phone || !params.audioBlob) {
      throw new Error("Parâmetros obrigatórios ausentes: phone, audioBlob");
    }

    // Criar FormData para envio multipart (sem base64!)
    const formData = new FormData();
    formData.append('phone', params.phone);

    // Adicionar session apenas se fornecida (backend descobre automaticamente)
    if (params.session) {
      formData.append('session', params.session);
    }

    formData.append('audio', params.audioBlob, `voice.${params.audioBlob.type.split('/')[1] || 'webm'}`);
    formData.append('convert', String(params.convert ?? true));

    // Adicionar company_id se fornecido
    if (params.companyId) {
      formData.append('company_id', String(params.companyId));
    }

    console.log("[WAHA Direct Audio] 📤 Enviando requisição multipart...");
    console.log("[WAHA Direct Audio] 📦 FormData keys:", Array.from(formData.keys()));

    // Enviar para novo endpoint WAHA
    const response = await api.post('/api/waha/send-voice', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      timeout: 60000, // 60 segundos para upload de áudio
    });

    console.log("[WAHA Direct Audio] ✅ Resposta WAHA:", response.data);
    return response.data;

  } catch (error: any) {
    console.error("[WAHA Direct Audio] ❌ Erro ao enviar áudio:", error);

    // Melhor tratamento de erro
    if (error.response) {
      console.error("[WAHA Direct Audio] Status:", error.response.status);
      console.error("[WAHA Direct Audio] Data:", error.response.data);
      throw new Error(`WAHA Error ${error.response.status}: ${error.response.data?.detail || 'Erro desconhecido'}`);
    }

    throw error;
  }
}

/**
 * Verifica se o provider WAHA está disponível e configurado
 * @returns Boolean indicando se WAHA pode ser usado
 */
export function isWahaAvailable(): boolean {
  const providerInfo = detectWhatsAppProvider();
  return providerInfo?.provider === 'waha' && !!providerInfo?.session_name;
}

/**
 * Obtém informações da sessão WAHA atual
 * @returns Informações da sessão ou null se não disponível
 */
export function getWahaSessionInfo(): { session: string; companyId?: number } | null {
  const providerInfo = detectWhatsAppProvider();

  if (providerInfo?.provider === 'waha' && providerInfo?.session_name) {
    const companyId = parseInt((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')) || '0');
    return {
      session: providerInfo?.session_name || '',
      companyId: companyId > 0 ? companyId : undefined
    };
  }

  return null;
}

// ================================================================
// LEAD CUSTOM FIELDS - CAMPOS CUSTOMIZADOS DE LEADS
// ================================================================

// Tipos de campos customizados suportados
export type CustomFieldType = 'text' | 'number' | 'email' | 'date' | 'select' | 'textarea';

// Regras de validação para campos customizados
export interface CustomFieldValidationRules {
  min_length?: number;        // Para text/textarea
  max_length?: number;        // Para text/textarea
  min_value?: number;         // Para number
  max_value?: number;         // Para number
  pattern?: string;           // Regex para text
  options?: string[];         // Para select
}

// Interface para criação de campo customizado
export interface LeadCustomFieldCreate {
  field_name: string;
  field_key?: string;         // Opcional, será gerado automaticamente
  field_type: CustomFieldType;
  is_required?: boolean;
  default_value?: any;        // Para select: array de opções; para outros: valor padrão
  validation_rules?: CustomFieldValidationRules;
  display_order?: number;
  is_active?: boolean;
}

// Interface para atualização de campo customizado
export interface LeadCustomFieldUpdate {
  field_name?: string;
  field_type?: CustomFieldType;
  is_required?: boolean;
  default_value?: any;
  validation_rules?: CustomFieldValidationRules;
  display_order?: number;
  is_active?: boolean;
}

// Interface de resposta para campo customizado
export interface LeadCustomField {
  id: number;
  company_id: number;
  field_name: string;
  field_key: string;
  field_type: CustomFieldType;
  is_required: boolean;
  default_value?: any;
  validation_rules?: CustomFieldValidationRules;
  display_order: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// Interface para criação/atualização de valor customizado
export interface LeadCustomValueCreate {
  custom_field_id: number;
  value: any;
}

// Interface de resposta para valor customizado
export interface LeadCustomValue {
  id: number;
  lead_id: number;
  custom_field_id: number;
  value: any;
  field_name?: string;
  field_key?: string;
  field_type?: string;
  created_at: string;
  updated_at: string;
}

// Interface para lead com campos customizados
export interface LeadWithCustomFields {
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
  custom_values: LeadCustomValue[];
}

// Interface para reordenação de campos
export interface FieldOrderRequest {
  field_id: number;
  display_order: number;
}

// Interface para validação de campos
export interface LeadCustomFieldsValidationRequest {
  values: Record<string, any>;  // field_key -> value
}

// Interface para resposta de validação
export interface LeadCustomFieldsValidationResponse {
  is_valid: boolean;
  errors: string[];
  field_info: Record<string, {
    id: number;
    name: string;
    type: string;
    required: boolean;
    provided: boolean;
    value: any;
  }>;
}

/**
 * Lista todos os campos customizados de uma empresa
 */
export async function listarLeadCustomFields(
  clientId: number,
  companyId: number,
  activeOnly: boolean = true,
  apiKey: string
): Promise<LeadCustomField[]> {
  const response: AxiosResponse<LeadCustomField[]> = await api.get(
    `/api/agenda/clients/${clientId}/companies/${companyId}/lead-custom-fields/`,
    {
      params: { active_only: activeOnly },
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
  return response.data;
}

/**
 * Cria um novo campo customizado
 */
export async function criarLeadCustomField(
  clientId: number,
  companyId: number,
  fieldData: LeadCustomFieldCreate,
  apiKey: string
): Promise<LeadCustomField> {
  const response: AxiosResponse<LeadCustomField> = await api.post(
    `/api/agenda/clients/${clientId}/companies/${companyId}/lead-custom-fields/`,
    fieldData,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
  return response.data;
}

/**
 * Atualiza um campo customizado existente
 */
export async function atualizarLeadCustomField(
  clientId: number,
  companyId: number,
  fieldId: number,
  fieldData: LeadCustomFieldUpdate,
  apiKey: string
): Promise<LeadCustomField> {
  const response: AxiosResponse<LeadCustomField> = await api.put(
    `/api/agenda/clients/${clientId}/companies/${companyId}/lead-custom-fields/${fieldId}`,
    fieldData,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
  return response.data;
}

/**
 * Remove (desativa) um campo customizado
 */
export async function deletarLeadCustomField(
  clientId: number,
  companyId: number,
  fieldId: number,
  apiKey: string
): Promise<void> {
  await api.delete(
    `/api/agenda/clients/${clientId}/companies/${companyId}/lead-custom-fields/${fieldId}`,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
}

/**
 * Reordena campos customizados
 */
export async function reordenarLeadCustomFields(
  clientId: number,
  companyId: number,
  fieldOrders: FieldOrderRequest[],
  apiKey: string
): Promise<{ message: string }> {
  const response: AxiosResponse<{ message: string }> = await api.put(
    `/api/agenda/clients/${clientId}/companies/${companyId}/lead-custom-fields/reorder`,
    fieldOrders,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
  return response.data;
}

/**
 * Valida valores de campos customizados sem criar o lead
 */
export async function validarLeadCustomFields(
  clientId: number,
  companyId: number,
  validationRequest: LeadCustomFieldsValidationRequest,
  apiKey: string
): Promise<LeadCustomFieldsValidationResponse> {
  const response: AxiosResponse<LeadCustomFieldsValidationResponse> = await api.post(
    `/api/agenda/clients/${clientId}/companies/${companyId}/lead-custom-fields/validate`,
    validationRequest,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
  return response.data;
}

/**
 * Cria um novo lead com campos customizados
 */
export async function criarLeadWithCustomFields(
  clientId: number,
  companyId: number,
  leadData: any, // LeadCreate com custom_values
  apiKey: string
): Promise<LeadWithCustomFields> {
  const response: AxiosResponse<LeadWithCustomFields> = await api.post(
    `/api/clients/${clientId}/companies/${companyId}/leads/with-custom-fields`,
    leadData,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
  return response.data;
}

/**
 * Atualiza um lead existente com campos customizados
 */
export async function atualizarLeadWithCustomFields(
  clientId: number,
  companyId: number,
  leadId: number,
  leadData: any, // LeadUpdate com custom_values
  apiKey: string
): Promise<LeadWithCustomFields> {
  const response: AxiosResponse<LeadWithCustomFields> = await api.put(
    `/api/clients/${clientId}/companies/${companyId}/leads/${leadId}/with-custom-fields`,
    leadData,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
  return response.data;
}

/**
 * Busca um lead com campos customizados
 */
export async function obterLeadWithCustomFields(
  clientId: number,
  companyId: number,
  leadId: number,
  apiKey: string
): Promise<LeadWithCustomFields> {
  const response: AxiosResponse<LeadWithCustomFields> = await api.get(
    `/api/clients/${clientId}/companies/${companyId}/leads/${leadId}/with-custom-fields`,
    {
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
  return response.data;
}

/**
 * Lista leads de uma empresa com campos customizados
 */
export async function listarLeadsWithCustomFields(
  clientId: number,
  companyId: number,
  apiKey: string,
  pipelineId?: number,
  stageId?: number
): Promise<LeadWithCustomFields[]> {
  const params: any = {};
  if (pipelineId) params.pipeline_id = pipelineId;
  if (stageId) params.stage_id = stageId;

  const response: AxiosResponse<LeadWithCustomFields[]> = await api.get(
    `/api/clients/${clientId}/companies/${companyId}/leads/with-custom-fields`,
    {
      params,
      headers: legacyApiKeyHeaders(apiKey),
    }
  );
  return response.data;
}

// --- Follow Up Sequences (Múltiplas) ---

export const getFollowUpSequences = async (companyId: number) => {
  const response = await api.get(`/api/followups/${companyId}`);
  return response.data;
};

export const getSingleFollowUpSequence = async (sequenceId: number) => {
  const response = await api.get(`/api/followups/sequence/${sequenceId}`);
  return response.data;
};

// Mantido para compatibilidade (pega a primeira ou única)
export const getFollowUpSequence = async (companyId: number) => {
  try {
    const seqs = await getFollowUpSequences(companyId);
    return seqs && seqs.length > 0 ? seqs[0] : null;
  } catch (error) {
    // Se der 404 ou vazio
    return null;
  }
};

export const createFollowUpSequence = async (companyId: number, data: FollowUpSequenceCreate) => {
  const response = await api.post(`/api/followups/${companyId}`, data);
  return response.data;
};

export const updateFollowUpSequence = async (sequenceId: number, data: FollowUpSequenceUpdate) => {
  // Agora a rota é PUT /followups/{sequenceId}
  const response = await api.put(`/api/followups/${sequenceId}`, data);
  return response.data;
};

export const deleteFollowUpSequence = async (companyId: number) => {
  const response = await api.delete(`/api/followups/${companyId}`);
  return response.data;
};

export interface PipelineStage {
  id: number;
  pipeline_id: number;
  name: string;
  description?: string;
  color?: string;
  order: number;
  is_first_stage: boolean;
  is_converted_stage?: boolean;
  is_lost_stage?: boolean;
  auto_advance_days?: number;
}

export interface PipelineResponse {
  id: number;
  company_id: number;
  name: string;
  description?: string;
  is_active?: boolean;
  created_by_user_id?: number;
  created_at: string;
  updated_at: string;
  stages: PipelineStage[];
}

export async function getPipelines(companyId: number): Promise<PipelineResponse[]> {
  const response = await api.get('/api/pipelines', {
    params: { company_id: companyId }
  });
  return response.data;
}

/**
 * Get next tasks for multiple leads in batch
 * POST /api/leads/next-tasks-batch
 */
export async function getLeadsNextTasksBatch(phones: string[]): Promise<any[]> {
  try {
    const response = await api.post('/api/leads/next-tasks-batch', { phones });
    return response.data;
  } catch (error) {
    console.error('Error fetching leads next tasks:', error);
    return [];
  }
}
