import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { DragDropContext, Droppable, Draggable, type DragStart, type DropResult } from '@hello-pangea/dnd';
import {
  Search,
  Plus,
  Download,
  Calendar,
  GripVertical,
  Trash2,
  Settings,
  X,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  Phone,
  MessageCircle,
  Pencil,
  LayoutGrid,
  List,
  Megaphone,
  Eye,
  Users,
  UserPlus,
  Link2,
  Loader2,
} from 'lucide-react';
import { crmApi, pipelineApi, Lead as BackendLead, Column } from '../services/crmApi.ts';
import api, { criarLead, LeadCreate } from '../services/api.ts';
import LeadProfile from '../components/LeadProfile.tsx';
import TaskPreview from '../components/TaskPreview.tsx';
import GlobalDateFilter, {
  type GlobalDateFilterValue,
  type GlobalDatePreset,
  type GlobalDateRange,
} from '../components/filters/GlobalDateFilter/index.ts';
import { getMediaSources, MediaSource } from '../services/mediaApi.ts';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AgentiveAlert,
  AgentiveConfirmModal,
} from '../components/AgentiveUI.tsx';
import '../components/crm/CRMWorkspace/CRMWorkspace.css';
import { sortLeadsByEntryRecency } from '../components/crm/CRMWorkspace/leadOrdering.ts';
import {
  CrmModernEmptyState,
  crmModernBadgeClass,
  crmModernIconButtonClass,
  crmModernInputClass,
  crmModernLabelClass,
  crmModernPanelClass,
  crmModernPrimaryButtonClass,
  crmModernSecondaryButtonClass,
} from '../components/crm/CRMModern/CRMModernUI.tsx';

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

const legacyStageColorMap: Record<string, string> = {
  amber: '#d97706',
  blue: '#2563eb',
  cyan: '#0891b2',
  emerald: '#059669',
  gray: '#4b5563',
  green: '#16a34a',
  indigo: '#4f46e5',
  lime: '#65a30d',
  neutral: '#525252',
  orange: '#ea580c',
  pink: '#db2777',
  purple: '#9333ea',
  red: '#dc2626',
  rose: '#e11d48',
  sky: '#0284c7',
  slate: '#475569',
  stone: '#57534e',
  teal: '#0d9488',
  yellow: '#ca8a04',
  zinc: '#52525b',
};

const normalizeStageColor = (color?: string) => {
  const value = color?.trim();
  if (!value) return '#020323';
  if (/^#[0-9a-f]{6}$/i.test(value)) return value;
  if (/^#[0-9a-f]{3}$/i.test(value)) {
    const [, r, g, b] = value;
    return `#${r}${r}${g}${g}${b}${b}`;
  }

  const lowered = value.toLowerCase();
  return Object.entries(legacyStageColorMap).find(([name]) => lowered.includes(name))?.[1] || '#020323';
};

const getStageDotStyle = (color?: string): React.CSSProperties => ({
  backgroundColor: normalizeStageColor(color),
});

const getStageColumnStyle = (color?: string): React.CSSProperties => ({
  borderTopColor: normalizeStageColor(color),
});

const getStageChipStyle = (color?: string): React.CSSProperties => {
  const stageColor = normalizeStageColor(color);
  return {
    backgroundColor: `${stageColor}12`,
    borderColor: `${stageColor}28`,
    color: stageColor,
  };
};

const getInitials = (name?: string) => {
  const parts = (name || '').trim().split(/\s+/).filter(Boolean);
  return (parts.slice(0, 2).map(part => part[0]).join('') || 'LD').toUpperCase();
};

// --- Tipos ---
interface ContactSearchResult {
  id: number;
  phone: string;
  name?: string;
  photo?: string;
  lead_id?: number;
  customer_id?: number;
  last_message_at?: string;
}

interface ContactsSearchResponse {
  contacts: ContactSearchResult[];
  total: number;
  has_more: boolean;
}

// Interface interna para Lead no frontend
interface Lead {
  id: number;
  name: string;
  phone: string;
  date: Date | string;
  tag: string;
  columnId: string;
  thumbnailUrl?: string;
  sourceId?: string;
  pipelineId?: number;
  currentStageId?: number;
  data_entrada?: string;
  isMoving?: boolean;
  nextTask?: {
    title: string;
    scheduled_for: string;
    task_type: 'message' | 'call' | 'email';
  };
  avatarColor?: string;
  lastActivity?: string;
  custom_values?: {
    field_key: string;
    value: any;
    field_name: string;
  }[];
  consulta_data?: string; // Data do agendamento (ISO string)
  consulta_data_display?: string;
  consulta_timezone?: string;
}

// Dados dos países com regras de validação
const countries = [
  {
    code: 'BR',
    name: 'Brasil',
    flag: '🇧🇷',
    ddi: '55',
    mask: '(XX) XXXXX-XXXX',
    phoneLength: { min: 10, max: 11 }, // DDD + 8 ou 9 dígitos
    validateDigits: (digits: string) => {
      const phoneDigits = digits.slice(2); // Remove DDD
      return phoneDigits.length === 8 || phoneDigits.length === 9;
    }
  },
  {
    code: 'US',
    name: 'Estados Unidos',
    flag: '🇺🇸',
    ddi: '1',
    mask: '(XXX) XXX-XXXX',
    phoneLength: { min: 10, max: 10 }, // 10 dígitos fixo
    validateDigits: (digits: string) => digits.length === 10
  },
  {
    code: 'AR',
    name: 'Argentina',
    flag: '🇦🇷',
    ddi: '54',
    mask: '(XX) XXXX-XXXX',
    phoneLength: { min: 10, max: 10 }, // DDD + 8 dígitos
    validateDigits: (digits: string) => digits.length === 10
  }
];

const normalizePhoneDigits = (value?: string) => (value || '').replace(/\D/g, '');

const inferCountryFromPhone = (phone: string) => {
  const digits = normalizePhoneDigits(phone);
  return countries.find(country => digits.startsWith(country.ddi)) || countries[0];
};

const isNewLead = (createdAt: string): boolean => {
  if (!createdAt) return false;
  const leadDate = new Date(createdAt);
  const hoursDiff = (Date.now() - leadDate.getTime()) / (1000 * 60 * 60);
  return hoursDiff <= 24;
};

// Função de formatação de telefone com validação de limite
function maskPhoneByCountry(input: string, country: any): string {
  let digits = input.replace(/\D/g, '');

  // Remove o DDI se o usuário digitar
  if (digits.startsWith(country.ddi)) {
    digits = digits.slice(country.ddi.length);
  }

  // Limitar dígitos baseado no país
  let maxDigits;
  if (country.code === 'BR') {
    maxDigits = 2 + country.phoneLength.max; // DDD + máximo de dígitos do telefone
  } else {
    maxDigits = country.phoneLength.max; // Total de dígitos sem DDD
  }
  digits = digits.slice(0, maxDigits);

  let formatted = digits;

  // Aplicar máscara baseada no país
  if (country.code === 'BR') { // Brasil
    const ddd = digits.slice(0, 2);
    const rest = digits.slice(2);
    formatted = '';
    if (ddd) formatted += `(${ddd}`;
    if (rest.length > 0) formatted += `) `;

    // Lógica para 8 ou 9 dígitos
    if (rest.length <= 4) {
      formatted += rest;
    } else if (rest.length === 5) {
      formatted += `${rest.slice(0, 4)}-${rest.slice(4)}`;
    } else {
      const part1 = rest.slice(0, 5);
      const part2 = rest.slice(5, 9);
      formatted += `${part1}-${part2}`;
    }
  } else if (country.code === 'US') { // EUA
    const area = digits.slice(0, 3);
    const prefix = digits.slice(3, 6);
    const line = digits.slice(6, 10);
    formatted = '';
    if (area) formatted += `(${area}`;
    if (prefix.length > 0) formatted += `) ${prefix}`;
    if (line.length > 0) formatted += `-${line}`;
  } else { // Argentina e outros
    const ddd = digits.slice(0, 2);
    const rest = digits.slice(2);
    formatted = '';
    if (ddd) formatted += `(${ddd})`;
    if (rest.length > 0) formatted += ` ${rest.slice(0, 4)}-${rest.slice(4, 8)}`;
  }

  return formatted;
}

// Função para limpar telefone
function getRawPhone(masked: string): string {
  return masked.replace(/\D/g, '');
}

// Função para montar telefone completo com DDI
function buildFullPhone(countryDDI: string, phone: string): string {
  const rawPhone = getRawPhone(phone);
  return countryDDI + rawPhone;
}

// Mapear backend lead para frontend lead
const mapBackendLeadToFrontend = (backendLead: BackendLead): Lead => {
  const tag = isNewLead(backendLead.created_at || '') ? 'NOVO' : '';
  const operationalDate = backendLead.data_entrada || backendLead.created_at || '';

  // Se não tiver current_stage_id, é um novo lead
  // Se tiver, mantém no estágio atual
  const columnId = backendLead.current_stage_id
    ? backendLead.current_stage_id.toString()
    : 'novo_lead';

  return {
    id: backendLead.id,
    name: backendLead.name || 'Sem Nome',
    phone: backendLead.phone || '',
    date: operationalDate,
    tag,
    columnId: columnId,
    thumbnailUrl: backendLead.thumbnail_url,
    sourceId: backendLead.source_id,
    pipelineId: backendLead.pipeline_id,
    currentStageId: backendLead.current_stage_id,
    data_entrada: backendLead.data_entrada,
    custom_values: backendLead.custom_values
  };
};

export default function CRMv4() {
  const navigate = useNavigate();
  const { isDark } = useTheme();

  // --- Estados ---
  const [columns, setColumns] = useState<Column[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [isEditingPipeline, setIsEditingPipeline] = useState(false);
  const [newColumnName, setNewColumnName] = useState('');
  const [newColumnColor, setNewColumnColor] = useState('#020323');
  const [newColumnPercentageBaseStageId, setNewColumnPercentageBaseStageId] = useState('');
  const [editingStageColumnId, setEditingStageColumnId] = useState<string | null>(null);
  const [editStageName, setEditStageName] = useState('');
  const [editStageColor, setEditStageColor] = useState('#020323');
  const [editStagePercentageBaseStageId, setEditStagePercentageBaseStageId] = useState('');
  const [stageDeleteColumn, setStageDeleteColumn] = useState<Column | null>(null);
  const [minimizedColumns, setMinimizedColumns] = useState<Set<string>>(() => {
    const saved = localStorage.getItem('crm_minimized_columns');
    return saved ? new Set(JSON.parse(saved)) : new Set();
  });
  const [searchTerm, setSearchTerm] = useState('');
  const [viewMode, setViewMode] = useState<'board' | 'list'>(() => {
    const saved = localStorage.getItem('crm_view_mode');
    if (saved === 'list' || saved === 'board') return saved;
    return typeof window !== 'undefined' && window.matchMedia('(max-width: 639px)').matches ? 'list' : 'board';
  });
  const [showNewLeadModal, setShowNewLeadModal] = useState(false);
  const [mediaOptions, setMediaOptions] = useState<MediaSource[]>([]);
  const [contactSearchTerm, setContactSearchTerm] = useState('');
  const [contactSearchResults, setContactSearchResults] = useState<ContactSearchResult[]>([]);
  const [contactSearchLoading, setContactSearchLoading] = useState(false);
  const [contactSearchError, setContactSearchError] = useState<string | null>(null);
  const [selectedContact, setSelectedContact] = useState<ContactSearchResult | null>(null);

  // Estados para modais de edição e exclusão
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [selectedProfileLead, setSelectedProfileLead] = useState<Lead | null>(null);
  const [showProfileModal, setShowProfileModal] = useState(false);
  const [actionLoading, setActionLoading] = useState<number | null>(null);

  // Estado para edição de lead completo (mesma estrutura que newLead)
  const [editLeadData, setEditLeadData] = useState({
    name: '',
    phone: '',
    source_id: '',
    data_entrada: '',
    selectedCountry: countries[0]
  });

  const [newLead, setNewLead] = useState({
    name: '',
    phone: '',
    source_id: '',
    data_entrada: '',
    selectedCountry: countries[0] // Brasil como padrão
  });
  const [editingLeadId, setEditingLeadId] = useState<number | null>(null);
  const [draggedLeadId, setDraggedLeadId] = useState<number | null>(null);
  const [isDateEditable, setIsDateEditable] = useState(false);



  // Estados de filtro de data
  const [dateRange, setDateRange] = useState<GlobalDateRange>({ startDate: null, endDate: null });
  const [dateFilterType, setDateFilterType] = useState<GlobalDatePreset>('all');

  // Estados de loading e erro
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // Fetch Media Sources
  useEffect(() => {
    const fetchMedia = async () => {
      try {
        const sources = await getMediaSources();
        setMediaOptions(sources);
        // Set default source if available and not set
        if (sources.length > 0) {
          setNewLead(prev => ({ ...prev, source_id: sources[0].name }));
        }
      } catch (e) {
        console.error("Failed to fetch media sources", e);
      }
    };
    fetchMedia();
  }, []);

  useEffect(() => {
    localStorage.setItem('crm_view_mode', viewMode);
  }, [viewMode]);

  const getDefaultLeadSource = () => mediaOptions.find(media => media.active)?.name || 'Facebook';

  const resetContactSearch = () => {
    setContactSearchTerm('');
    setContactSearchResults([]);
    setContactSearchError(null);
    setContactSearchLoading(false);
    setSelectedContact(null);
  };

  const openNewLeadModal = () => {
    const now = new Date();
    const localIsoString = new Date(now.getTime() - (now.getTimezoneOffset() * 60000)).toISOString().slice(0, 16);

    resetContactSearch();
    setNewLead({
      name: '',
      phone: '',
      source_id: getDefaultLeadSource(),
      data_entrada: localIsoString,
      selectedCountry: countries[0]
    });
    setIsDateEditable(false);
    setShowNewLeadModal(true);
  };

  const closeNewLeadModal = () => {
    setShowNewLeadModal(false);
    setEditingLeadId(null);
    setIsDateEditable(false);
    resetContactSearch();
    setNewLead({
      name: '',
      phone: '',
      source_id: getDefaultLeadSource(),
      data_entrada: '',
      selectedCountry: countries[0]
    });
  };

  useEffect(() => {
    if (!showNewLeadModal || editingLeadId) {
      setContactSearchResults([]);
      setContactSearchLoading(false);
      return;
    }

    const term = contactSearchTerm.trim();
    if (term.length < 2) {
      setContactSearchResults([]);
      setContactSearchError(null);
      setContactSearchLoading(false);
      return;
    }

    let cancelled = false;
    const timeout = window.setTimeout(async () => {
      try {
        setContactSearchLoading(true);
        setContactSearchError(null);

        const companyId = localStorage.getItem('company_id') || localStorage.getItem('clinic_id') || sessionStorage.getItem('company_id') || sessionStorage.getItem('clinic_id');
        if (!companyId) {
          throw new Error('ID da empresa não encontrado');
        }

        const params = new URLSearchParams({
          company_id: companyId,
          limit: '8',
          offset: '0',
          unread_only: 'false',
          show_archived: 'false',
          search: term,
        });

        const response = await api.get<ContactsSearchResponse>(`/webhook/contacts?${params}`);
        if (cancelled) return;

        const existingLeadPhones = new Set(leads.map(lead => normalizePhoneDigits(lead.phone)));
        const availableContacts = (response.data.contacts || []).filter(contact => (
          !contact.lead_id && !existingLeadPhones.has(normalizePhoneDigits(contact.phone))
        ));

        setContactSearchResults(availableContacts);
      } catch (err: any) {
        if (!cancelled) {
          const message = typeof err === 'string'
            ? err
            : err.response?.data?.detail || err.message || 'Erro ao buscar contatos';
          setContactSearchError(message);
          setContactSearchResults([]);
        }
      } finally {
        if (!cancelled) {
          setContactSearchLoading(false);
        }
      }
    }, 280);

    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [contactSearchTerm, editingLeadId, leads, showNewLeadModal]);

  // Estados para movimentação de leads
  const [notification, setNotification] = useState<{ type: 'success' | 'error', message: string } | null>(null);

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

  // Colunas padrão do sistema
  const COLUNAS_PADRAO: Column[] = [
    {
      id: 'novo_lead',
      title: 'Novo Lead',
      color: '#020323',
      stageId: 0,
      pipelineId: 0,
      order: 1
    }
  ];

  // Colunas que não podem ser removidas
  const COLUNAS_PROTEGIDAS = ['novo_lead'];

  // Carregar dados iniciais - executar apenas uma vez na montagem
  useEffect(() => {
    const loadInitialData = async () => {
      try {
        setLoading(true);
        setError(null);

        // 1. Carregar Leads da tabela leads
        const backendLeads = await crmApi.getLeads();

        // 2. Carregar tasks para os leads (em batch)
        const phones = [...new Set(backendLeads.map(lead => lead.phone).filter((phone): phone is string => Boolean(phone)))];
        let tasksMap: Record<string, any> = {};

        try {
          const tasks = await crmApi.getNextTasksBatch(phones);
          tasksMap = tasks.reduce((acc, task) => {
            acc[task.phone] = task;
            return acc;
          }, {});
        } catch (taskError) {
          console.warn('⚠️ Erro ao carregar tasks (continuando sem tasks):', taskError);
        }

        // 2.5. Carregar agendamentos para mostrar consulta_data nos cards
        let agendamentosMap: Record<string, {
          consulta_data: string;
          consulta_data_display?: string;
          consulta_timezone?: string;
        }> = {};
        try {
          const { clientId, companyId } = getAuthIds();
          if (clientId && companyId) {
            const response = await api.get(`/api/agenda/clients/${clientId}/companies/${companyId}/agendamentos`);
            const agendamentos = response.data || [];
            // Mapear phone -> consulta_data mais próxima (futura)
            const now = new Date();
            agendamentos.forEach((ag: any) => {
              if (ag.phone && ag.consulta_data) {
                const agDate = new Date(ag.consulta_data);
                // Normalizar telefone (últimos 10-11 dígitos)
                const normalizedPhone = ag.phone.replace(/\D/g, '').slice(-11);
                // Se ainda não tem ou se a data é mais próxima (e futura), usar esta
                if (!agendamentosMap[normalizedPhone] || (agDate > now && agDate < new Date(agendamentosMap[normalizedPhone].consulta_data))) {
                  agendamentosMap[normalizedPhone] = {
                    consulta_data: ag.consulta_data,
                    consulta_data_display: ag.consulta_data_display,
                    consulta_timezone: ag.consulta_timezone
                  };
                }
              }
            });
            console.log(`✅ Agendamentos carregados: ${Object.keys(agendamentosMap).length} mapeados`);
          }
        } catch (agError) {
          console.warn('⚠️ Erro ao carregar agendamentos (continuando sem):', agError);
        }

        // 3. Mapear leads para frontend incluindo nextTask e consulta_data
        const frontendLeads = backendLeads.map(mapBackendLeadToFrontend).map(lead => {
          const normalizedLeadPhone = lead.phone.replace(/\D/g, '').slice(-11);
          const agendamento = agendamentosMap[normalizedLeadPhone];
          return {
            ...lead,
            nextTask: tasksMap[lead.phone] || undefined,
            consulta_data: agendamento?.consulta_data,
            consulta_data_display: agendamento?.consulta_data_display,
            consulta_timezone: agendamento?.consulta_timezone
          };
        });

        setLeads(frontendLeads);

        // 4. Criar colunas: padrão + estágios reais do banco
        let allColumns = [...COLUNAS_PADRAO];

        try {
          // Tentar buscar estágios do pipeline do banco
          let pipelineId = 1;
          try {
            const pipelines = await pipelineApi.getPipelines();
            if (pipelines && pipelines.length > 0) {
              pipelineId = pipelines[0].id;

              // Buscar estágios do pipeline
              const stages = await pipelineApi.getStages(pipelineId);
              if (stages && stages.length > 0) {
                // Filtrar estágios que não são colunas padrão
                const customStages = stages
                  .filter(stage => !COLUNAS_PADRAO.some(col => col.id === stage.id.toString()))
                  .map(stage => ({
                    id: stage.id.toString(),
                    title: stage.name,
                    color: stage.color || 'border-yellow-500',
                    order: stage.order,
                    stageId: stage.id,
                    percentageBaseStageId: stage.percentage_base_stage_id ?? null
                  }))
                  .sort((a, b) => a.order - b.order);

                // Encontrar posição de inserção (depois de "Novo Lead")
                const novoLeadIndex = allColumns.findIndex(col => col.id === 'novo_lead');
                const insertIndex = novoLeadIndex + 1;

                // Inserir estágios personalizados entre "Novo Lead" e "Ganhou/Perdido"
                allColumns = [
                  ...allColumns.slice(0, insertIndex),
                  ...customStages,
                  ...allColumns.slice(insertIndex)
                ];
              }
            }
          } catch (pipelineError) {
            console.warn('Falha ao buscar estágios do pipeline, usando apenas colunas padrão:', pipelineError);
          }
        } catch (error) {
          console.warn('Erro ao carregar estágios personalizados:', error);
        }

        setColumns(allColumns);

        console.log(`✅ Dados carregados: ${frontendLeads.length} leads, colunas padrão + personalizadas`);
      } catch (err) {
        console.error('❌ Erro ao carregar dados iniciais:', err);
        setError('Falha ao carregar dados do CRM. Tente recarregar a página.');

        // Fallback: colunas padrão
        setColumns(COLUNAS_PADRAO);
      } finally {
        setLoading(false);
      }
    };

    loadInitialData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Executar apenas na montagem inicial

  // --- Filtro global de data ---
  const handleDateFilterChange = ({ preset, range }: GlobalDateFilterValue) => {
    setDateRange(range);
    setDateFilterType(preset);
  };

  // Função para formatar telefone enquanto digita (com validação)
  const handlePhoneChange = (value: string) => {
    const masked = maskPhoneByCountry(value, newLead.selectedCountry);
    setNewLead(prev => ({ ...prev, phone: masked }));
  };

  const handleEditPhoneChange = (value: string) => {
    const masked = maskPhoneByCountry(value, editLeadData.selectedCountry);
    setEditLeadData(prev => ({ ...prev, phone: masked }));
  };

  const handleSelectContact = (contact: ContactSearchResult) => {
    const country = inferCountryFromPhone(contact.phone);
    setSelectedContact(contact);
    setContactSearchTerm(contact.name || contact.phone);
    setContactSearchResults([]);
    setNewLead(prev => ({
      ...prev,
      name: contact.name || 'Contato sem nome',
      phone: maskPhoneByCountry(contact.phone, country),
      selectedCountry: country,
    }));
  };

  const handleClearSelectedContact = () => {
    setSelectedContact(null);
    setContactSearchTerm('');
    setContactSearchResults([]);
    setNewLead(prev => ({
      ...prev,
      name: '',
      phone: '',
      selectedCountry: countries[0],
    }));
  };

  const isPhoneCompleteFor = (phone: string, country: typeof countries[number]) => {
    const rawPhone = getRawPhone(phone);
    return country.validateDigits(rawPhone);
  };

  // Função para validar se o telefone está completo
  const isPhoneComplete = () => {
    return isPhoneCompleteFor(newLead.phone, newLead.selectedCountry);
  };

  const isEditPhoneComplete = () => {
    return isPhoneCompleteFor(editLeadData.phone, editLeadData.selectedCountry);
  };

  // Função para validar data (limitar ano a 4 dígitos)
  const validateDateTime = (dateTime: string) => {
    if (!dateTime) return true; // Campo opcional

    try {
      const date = new Date(dateTime);
      const currentYear = new Date().getFullYear();
      const year = date.getFullYear();

      // Validar se o ano tem 4 dígitos e não é excessivamente no futuro
      return year >= 1900 && year <= currentYear + 10;
    } catch {
      return false;
    }
  };

  // Função para formatar data/hora com validação
  const handleDateTimeChange = (value: string) => {
    if (!value || validateDateTime(value)) {
      setNewLead(prev => ({ ...prev, data_entrada: value }));
    } else {
      // Se inválido, limpa o campo
      setNewLead(prev => ({ ...prev, data_entrada: '' }));
      showNotification('error', 'Data inválida. Use uma data válida.');
    }
  };

  // Função para mudar país selecionado
  const handleCountryChange = (countryCode: string) => {
    const country = countries.find(c => c.code === countryCode);
    if (country) {
      setNewLead(prev => ({
        ...prev,
        selectedCountry: country,
        phone: '' // Limpa telefone ao mudar país
      }));
    }
  };

  // --- Funções de notificação e tratamento de erro ---
  const showNotification = (type: 'success' | 'error', message: string) => {
    setNotification({ type, message });
    setTimeout(() => setNotification(null), 3000);
  };

  const handleMoveError = (error: any) => {
    if (error.response?.status === 403) {
      showNotification('error', 'Sem permissão para mover este lead');
    } else if (error.response?.status === 404) {
      showNotification('error', 'Lead ou estágio não encontrado');
    } else if (error.response?.status === 400) {
      showNotification('error', 'Movimentação inválida: ' + (error.response?.data?.detail || ''));
    } else if (error.code === 'NETWORK_ERROR' || error.message?.includes('Network Error')) {
      showNotification('error', 'Falha de conexão. Verifique sua internet');
    } else {
      showNotification('error', 'Erro inesperado. Tente novamente');
    }
  };



  // Retry automático para falhas de rede
  const retryMove = async (leadId: number, stageId: number, userId: number, notes: string, retryCount = 0): Promise<any> => {
    const maxRetries = 3;

    try {
      return await pipelineApi.moveLeadToStage(leadId, stageId, userId, notes);
    } catch (error: any) {
      if (retryCount < maxRetries && (error.code === 'NETWORK_ERROR' || error.message?.includes('Network Error'))) {
        await new Promise(resolve => setTimeout(resolve, 1000 * (retryCount + 1)));
        return retryMove(leadId, stageId, userId, notes, retryCount + 1);
      }
      throw error;
    }
  };

  // --- Funções do Pipeline ---
  const getPercentageBaseOptions = (currentColumn?: Column) => {
    return columns.filter((column) => {
      const stageId = column.stageId || parseInt(column.id, 10);
      if (!stageId || isNaN(stageId)) return false;
      if (currentColumn?.stageId && stageId === currentColumn.stageId) return false;
      if (currentColumn?.order && column.order >= currentColumn.order) return false;
      return true;
    });
  };

  const getPercentageBaseLabel = (stageId?: number | null) => {
    if (!stageId) return 'Leads';
    return columns.find(column => column.stageId === stageId)?.title || 'Leads';
  };

  const addColumn = async () => {
    if (!newColumnName.trim()) return;

    try {
      // Obter IDs do localStorage
      const { clientId, companyId } = getAuthIds();
      if (!clientId || !companyId) {
        throw new Error('IDs de cliente ou empresa não encontrados');
      }

      // Primeiro, buscar ou criar um pipeline para esta empresa
      let pipelineId = 1; // Default
      try {
        const pipelines = await pipelineApi.getPipelines();
        if (pipelines && pipelines.length > 0) {
          pipelineId = pipelines[0].id;
        } else {
          console.warn('Nenhum pipeline encontrado, usando ID padrão');
        }
      } catch (e) {
        console.warn('Falha ao carregar pipelines, usando ID padrão', e);
      }

      // Criar nova etapa no backend
      const newStage = await pipelineApi.createStage(pipelineId, {
        name: newColumnName.trim(),
        pipeline_id: pipelineId,
        color: newColumnColor,
        order: columns.length + 1,
        is_active: true,
        percentage_base_stage_id: newColumnPercentageBaseStageId ? parseInt(newColumnPercentageBaseStageId, 10) : null
      });

      // Encontrar colunas convertidas ou perdidas para inserir antes delas
      const convertedLostIndex = columns.findIndex(col =>
        col.title?.toLowerCase().includes('ganhou') ||
        col.title?.toLowerCase().includes('perdido')
      );

      let finalColumns = [...columns];
      const newCol: Column = {
        id: newStage.id.toString(),
        title: newStage.name,
        color: newStage.color,
        order: newStage.order,
        stageId: newStage.id,
        percentageBaseStageId: newStage.percentage_base_stage_id ?? null
      };

      // Inserir a nova coluna antes de "Ganhou" ou "Perdido"
      if (convertedLostIndex !== -1) {
        finalColumns.splice(convertedLostIndex, 0, newCol);
      } else {
        finalColumns.push(newCol);
      }

      setColumns(finalColumns);

      // Persistir a nova ordem no backend imediatamente
      // Backend cria sempre no final, então precisamos reordenar explicitamente
      const stageOrders = finalColumns
        .map((col, index) => {
          const sId = col.stageId || parseInt(col.id);
          // Ignorar colunas sem ID numérico válido (ex: colunas locais como 'novo_lead' string)
          if (!sId || isNaN(sId)) return null;

          return {
            stage_id: sId,
            order: index + 1
          };
        })
        .filter((item): item is { stage_id: number; order: number } => item !== null);

      await pipelineApi.reorderStages(pipelineId, stageOrders);

      showNotification('success', `Etapa "${newColumnName.trim()}" criada`);
      setNewColumnName('');
      setNewColumnColor('#020323');
      setNewColumnPercentageBaseStageId('');
      console.log(`✅ Nova etapa "${newColumnName.trim()}" salva e reordenada`);
    } catch (error) {
      console.error('Erro ao criar etapa:', error);
      showNotification('error', 'Erro ao criar etapa. Tente novamente.');
    }
  };

  const startEditStage = (column: Column) => {
    setEditingStageColumnId(column.id);
    setEditStageName(column.title);
    setEditStageColor(normalizeStageColor(column.color));
    setEditStagePercentageBaseStageId(column.percentageBaseStageId ? column.percentageBaseStageId.toString() : '');
  };

  const cancelEditStage = () => {
    setEditingStageColumnId(null);
    setEditStageName('');
    setEditStageColor('#020323');
    setEditStagePercentageBaseStageId('');
  };

  const saveEditStage = async () => {
    const column = columns.find(col => col.id === editingStageColumnId);
    if (!column?.stageId || !editStageName.trim()) return;

    try {
      const updatedStage = await pipelineApi.updateStage(column.stageId, {
        name: editStageName.trim(),
        color: editStageColor,
        percentage_base_stage_id: editStagePercentageBaseStageId ? parseInt(editStagePercentageBaseStageId, 10) : null
      });

      setColumns(prev => prev.map(col => col.id === column.id ? {
        ...col,
        title: updatedStage.name,
        color: updatedStage.color,
        percentageBaseStageId: updatedStage.percentage_base_stage_id ?? null
      } : col));

      showNotification('success', 'Etapa atualizada');
      cancelEditStage();
    } catch (error) {
      console.error('Erro ao atualizar etapa:', error);
      showNotification('error', 'Erro ao atualizar etapa. Tente novamente.');
    }
  };

  const toggleMinimizeColumn = (colId: string) => {
    setMinimizedColumns(prev => {
      const newSet = new Set(prev);
      if (newSet.has(colId)) {
        newSet.delete(colId);
      } else {
        newSet.add(colId);
      }
      localStorage.setItem('crm_minimized_columns', JSON.stringify(Array.from(newSet)));
      return newSet;
    });
  };

  const requestRemoveColumn = (colId: string) => {
    if (columns.length <= 1) {
      showNotification('error', 'Você deve manter pelo menos uma etapa no pipeline.');
      return;
    }

    if (COLUNAS_PROTEGIDAS.includes(colId)) {
      const columnName = columns.find(c => c.id === colId)?.title;
      showNotification('error', `A etapa "${columnName}" não pode ser removida.`);
      return;
    }

    const columnToRemove = columns.find(c => c.id === colId);
    if (columnToRemove) setStageDeleteColumn(columnToRemove);
  };

  const confirmRemoveColumn = async () => {
    if (!stageDeleteColumn) return;
    const colId = stageDeleteColumn.id;
    try {
      // Encontrar a coluna para remover
      const columnToRemove = columns.find(c => c.id === colId);
      if (columnToRemove?.stageId && columnToRemove.stageId !== 0) {
        // Remover do backend apenas se for uma etapa real do banco
        try {
          await pipelineApi.deleteStage(0, columnToRemove.stageId);
          console.log(`✅ Etapa ${columnToRemove.title} removida do banco`);
        } catch (backendError) {
          console.warn('Falha ao remover etapa do banco, removendo apenas localmente:', backendError);
        }
      }

      // Mover leads para "Novo Lead"
      const fallbackColumn = 'novo_lead';
      setLeads(leads.map(lead => lead.columnId === colId ? { ...lead, columnId: fallbackColumn } : lead));

      // Remover coluna do estado local
      setColumns(columns.filter(c => c.id !== colId));
      setStageDeleteColumn(null);
      showNotification('success', 'Etapa removida');
      console.log(`✅ Coluna removida: ${colId}`);
    } catch (error) {
      console.error('Erro ao remover etapa:', error);
      showNotification('error', 'Erro ao remover etapa. Tente novamente.');
    }
  };



  const handleSaveLead = async () => {
    if (!selectedContact && (!newLead.name.trim() || !newLead.phone.trim())) {
      showNotification('error', 'Preencha nome e telefone');
      return;
    }

    if (selectedContact && !newLead.phone.trim()) {
      showNotification('error', 'O contato selecionado não possui telefone válido');
      return;
    }

    // Validar se o telefone está completo
    if (!selectedContact && !isPhoneComplete()) {
      const countryName = newLead.selectedCountry.name;
      const expectedLength = newLead.selectedCountry.code === 'BR'
        ? 'DDD + 8 ou 9 dígitos'
        : `${newLead.selectedCountry.phoneLength.max} dígitos`;
      showNotification('error', `Telefone incompleto para ${countryName}. Formato esperado: ${expectedLength}.`);
      return;
    }

    // Validar data se fornecida
    if (newLead.data_entrada && !validateDateTime(newLead.data_entrada)) {
      showNotification('error', 'Data de entrada inválida. Verifique o ano e tente novamente.');
      return;
    }

    try {
      // Obter dados do localStorage (padrão CRM_v3.tsx)
      const clientId = parseInt(localStorage.getItem('client_id') || sessionStorage.getItem('client_id') || '0', 10);
      const companyId = parseInt((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')) || (sessionStorage.getItem('company_id') || sessionStorage.getItem('clinic_id')) || '0', 10);
      const apiKey = '';
      const userType = localStorage.getItem('user_type') || sessionStorage.getItem('user_type');

      if (!clientId || !companyId) {
        throw new Error('Informações de autenticação inválidas');
      }

      // Lógica para effectiveClientId (como no CRM_v3.tsx)
      const effectiveClientId = (userType === 'user')
        ? parseInt(localStorage.getItem('master_client_id') || sessionStorage.getItem('master_client_id') || '0', 10)
        : clientId;

      setActionLoading(-1);

      if (!editingLeadId && selectedContact) {
        const response = await api.post(`/webhook/contacts/${selectedContact.id}/convert-to-lead`, {
          source_id: newLead.source_id || 'manual_conversion',
        });
        const convertedLeadId = Number(response.data?.lead_id);

        if (!convertedLeadId) {
          throw new Error('Contato convertido, mas o ID do lead não foi retornado');
        }

        if (newLead.data_entrada) {
          await crmApi.updateLead(convertedLeadId, {
            data_entrada: newLead.data_entrada.replace('T', ' ') + ':00',
          });
        }

        const convertedLead = await crmApi.getLead(convertedLeadId);
        const mappedLead = mapBackendLeadToFrontend(convertedLead);
        const leadWithColumn = {
          ...mappedLead,
          columnId: mappedLead.columnId || 'novo_lead',
        };

        setLeads(prev => {
          const exists = prev.some(lead => lead.id === leadWithColumn.id);
          return exists
            ? prev.map(lead => lead.id === leadWithColumn.id ? leadWithColumn : lead)
            : [...prev, leadWithColumn];
        });

        showNotification('success', 'Contato vinculado ao CRM como lead');
        closeNewLeadModal();
        return;
      }

      // Tratar telefone com DDI do país selecionado
      const finalPhone = buildFullPhone(newLead.selectedCountry.ddi, newLead.phone);

      // Preparar payload (exatamente como CRM_v3.tsx)
      const payload: LeadCreate = {
        client_id: String(effectiveClientId),
        name: newLead.name,
        phone: finalPhone,
        source_id: newLead.source_id
      };

      // Adicionar data_entrada se fornecida (igual ao CRM_v3.tsx)
      if (newLead.data_entrada) {
        payload.data_entrada = newLead.data_entrada.replace('T', ' ') + ':00';
      }

      if (editingLeadId) {
        // Atualizar Lead Existente
        const updatePayload: Partial<BackendLead> = {
          name: newLead.name,
          phone: finalPhone,
          source_id: newLead.source_id
        };

        if (newLead.data_entrada) {
          updatePayload.data_entrada = newLead.data_entrada.replace('T', ' ') + ':00';
        }

        const updated = await crmApi.updateLead(editingLeadId, updatePayload);

        // Mapear resposta para frontend
        const backendLead = {
          id: updated.id,
          client_id: updated.client_id,
          company_id: updated.company_id,
          name: updated.name,
          phone: updated.phone,
          created_at: updated.created_at,
          data_entrada: updated.data_entrada,
          source_id: updated.source_id,
          thumbnail_url: updated.thumbnail_url,
          sender_lid: updated.sender_lid,
          follow_up_sequence_id: updated.follow_up_sequence_id,
          current_stage_id: updated.current_stage_id,
          pipeline_id: updated.pipeline_id
        };
        const mappedLead = mapBackendLeadToFrontend(backendLead);

        setLeads(leads.map(l => l.id === editingLeadId ? mappedLead : l));
        showNotification('success', 'Lead atualizado com sucesso');
      } else {
        // Criar Novo Lead
        // Usar criarLead do api.ts (exatamente como CRM_v3.tsx)
        const novo = await criarLead(effectiveClientId, companyId, payload, apiKey);
        // Converter ApiLead para BackendLead compatível
        const backendLead = {
          id: novo.id,
          client_id: novo.client_id ? parseInt(novo.client_id.toString(), 10) : undefined,
          company_id: novo.company_id,
          name: novo.name,
          phone: novo.phone,
          created_at: novo.created_at,
          data_entrada: novo.data_entrada,
          source_id: novo.source_id,
          thumbnail_url: novo.thumbnail_url,
          sender_lid: novo.sender_lid,
          follow_up_sequence_id: novo.follow_up_sequence_id
        };
        const mappedLead = mapBackendLeadToFrontend(backendLead);

        // Adicionar novo lead à coluna "Novo Lead"
        const newLeadWithColumn = {
          ...mappedLead,
          columnId: 'novo_lead' // Garante que novos leads vão para a coluna "Novo Lead"
        };
        setLeads([...leads, newLeadWithColumn]);
        showNotification('success', 'Lead criado com sucesso');
      }

      closeNewLeadModal();

      // Recarregar dados para atualizar colunas se necessário
      // handleRefresh(); // Comentado para não sobrecarregar - já adicionamos o lead localmente
    } catch (error: any) {
      console.error('Erro ao salvar lead:', error);
      const errorMessage = error.response?.data?.detail || error.message || 'Erro ao salvar lead. Tente novamente.';
      showNotification('error', errorMessage);
    } finally {
      setActionLoading(null);
    }
  };

  const deleteLead = async (leadId: number) => {
    try {
      await crmApi.deleteLead(leadId);
      setLeads(leads.filter(l => l.id !== leadId));
    } catch (error) {
      console.error('Erro ao deletar lead:', error);
      throw error;
    }
  };

  // Funções para edição e exclusão de leads
  const handleDeleteLead = (lead: Lead) => {
    setSelectedLead(lead);
    setShowDeleteModal(true);
  };

  const confirmDeleteLead = async () => {
    if (!selectedLead) return;

    try {
      setActionLoading(selectedLead.id);
      await deleteLead(selectedLead.id);
      setShowDeleteModal(false);
      setSelectedLead(null);
      showNotification('success', 'Lead excluído com sucesso');
    } catch (error: any) {
      console.error('Erro ao excluir lead:', error);
      showNotification('error', 'Erro ao excluir lead. Tente novamente.');
    } finally {
      setActionLoading(null);
    }
  };

  const handleEditLead = (lead: Lead) => {
    setSelectedLead(lead);
    resetContactSearch();

    // Formatar telefone baseado no país (assumindo Brasil se não tiver info)
    const maskedPhone = maskPhoneByCountry(lead.phone, countries[0]);

    // Popular todos os campos do modal de edição
    setEditLeadData({
      name: lead.name || '',
      phone: maskedPhone,
      source_id: lead.sourceId || '',
      data_entrada: lead.data_entrada ? lead.data_entrada.replace(' ', 'T').slice(0, 16) : '',
      selectedCountry: countries[0] // Brasil como padrão
    });

    setShowEditModal(true);
  };

  const confirmEditLead = async () => {
    if (!selectedLead || !editLeadData.name.trim() || !editLeadData.phone.trim()) {
      showNotification('error', 'Preencha nome e telefone');
      return;
    }

    if (!isEditPhoneComplete()) {
      showNotification('error', `Telefone incompleto para ${editLeadData.selectedCountry.name}.`);
      return;
    }

    try {
      setActionLoading(selectedLead.id);

      // Preparar payload com todos os campos
      const updatePayload: Partial<BackendLead> = {
        name: editLeadData.name.trim(),
        phone: getRawPhone(editLeadData.phone), // Enviar telefone sem formatação
        source_id: editLeadData.source_id,
        data_entrada: editLeadData.data_entrada
      };

      const updated = await crmApi.updateLead(selectedLead.id, updatePayload);

      // Mapear resposta para frontend
      const backendLead = {
        id: updated.id,
        client_id: updated.client_id,
        company_id: updated.company_id,
        name: updated.name,
        phone: updated.phone,
        created_at: updated.created_at,
        data_entrada: updated.data_entrada,
        source_id: updated.source_id,
        thumbnail_url: updated.thumbnail_url,
        sender_lid: updated.sender_lid,
        follow_up_sequence_id: updated.follow_up_sequence_id,
        current_stage_id: updated.current_stage_id,
        pipeline_id: updated.pipeline_id
      };
      const mappedLead = mapBackendLeadToFrontend(backendLead);

      setLeads(leads.map(l => l.id === selectedLead.id ? mappedLead : l));
      setShowEditModal(false);
      setSelectedLead(null);
      setEditLeadData({
        name: '',
        phone: '',
        source_id: 'Facebook',
        data_entrada: '',
        selectedCountry: countries[0]
      });
      showNotification('success', 'Lead atualizado com sucesso');
    } catch (error: any) {
      console.error('Erro ao editar lead:', error);
      showNotification('error', 'Erro ao editar lead. Tente novamente.');
    } finally {
      setActionLoading(null);
    }
  };

  const handleOpenChat = (lead: Lead) => {
    navigate('/chat', {
      state: {
        selectedPhone: lead.phone,
        selectedContact: {
          name: lead.name || 'Lead sem nome',
          phone: lead.phone,
          photo: lead.thumbnailUrl
        }
      }
    });
  };

  const handleOpenProfile = (lead: Lead) => {
    setSelectedProfileLead(lead);
    setShowProfileModal(true);
  };

  const exportToCSV = () => {
    const filteredData = leads.filter(lead => {
      const matchesSearch = lead.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        lead.phone.includes(searchTerm);

      const leadDate = lead.date instanceof Date ? lead.date : new Date(lead.date);
      let matchesDate = true;

      if (dateRange.startDate && leadDate < dateRange.startDate) {
        matchesDate = false;
      }
      if (dateRange.endDate && leadDate > dateRange.endDate) {
        matchesDate = false;
      }

      return matchesSearch && matchesDate;
    });

    const headers = ['ID', 'Nome', 'Telefone', 'Data', 'Tag', 'Coluna'];
    const csvContent = [
      headers.join(','),
      ...filteredData.map(lead => [
        lead.id,
        `"${lead.name}"`,
        lead.phone,
        lead.date instanceof Date ? lead.date.toLocaleString('pt-BR') : lead.date,
        lead.tag,
        columns.find(c => c.id === lead.columnId)?.title || ''
      ].join(','))
    ].join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', `leads_${new Date().toISOString().split('T')[0]}.csv`);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // --- Funções de Drag & Drop ---
  const handleDragStart = (start: DragStart) => {
    const cardId = Number(start.draggableId);
    setDraggedLeadId(Number.isNaN(cardId) ? null : cardId);
  };

  const handleDragEnd = async (result: DropResult) => {
    const destColId = result.destination?.droppableId;
    const sourceColId = result.source.droppableId;
    const cardId = Number(result.draggableId);

    if (!destColId || !cardId || Number.isNaN(cardId) || sourceColId === destColId) {
      setDraggedLeadId(null);
      return;
    }

    try {
      // Loading state no lead específico
      setLeads(prev => prev.map(lead =>
        lead.id === cardId ? { ...lead, isMoving: true } : lead
      ));

      // 1. Validar se é coluna especial (baseado no título em vez do ID fixo)
      const destColumn = columns.find(col => col.id === destColId);
      const isSpecialColumn = destColumn && (
        destColId === 'novo_lead' ||
        destColumn.title?.toLowerCase().includes('ganhou') ||
        destColumn.title?.toLowerCase().includes('perdido')
      );

      if (isSpecialColumn) {
        // Movimentação com persistência para colunas especiais (Ganhou/Perdido)
        let targetStageId = 0;

        // Para "Novo Lead", manter stageId = 0
        if (destColId === 'novo_lead') {
          setLeads(prev => prev.map(lead =>
            lead.id === cardId ? {
              ...lead,
              columnId: destColId,
              currentStageId: 0,
              isMoving: false
            } : lead
          ));

          showNotification('success', 'Lead movido para Novo Lead');
          console.log(`✅ Lead ${cardId} movido para Novo Lead`);
          return;
        }

        // Para "Ganhou" ou "Perdido", pegar o stageId real da coluna
        if (destColumn.stageId) {
          targetStageId = destColumn.stageId;

          try {
            // Chamar API para persistir no banco
            const userId = parseInt(localStorage.getItem('user_id') || sessionStorage.getItem('user_id') || '0', 10);
            const columnType = destColumn.title?.toLowerCase().includes('ganhou') ? 'Ganhou' :
              destColumn.title?.toLowerCase().includes('perdido') ? 'Perdido' : 'Especial';



            // Para outras colunas especiais (Perdido), mover direto
            await retryMove(
              cardId,
              targetStageId,
              userId || 0,
              `Movido para ${columnType} via drag & drop`
            );

            // Atualizar estado local apenas após sucesso
            setLeads(prev => prev.map(lead =>
              lead.id === cardId ? {
                ...lead,
                columnId: destColId,
                currentStageId: targetStageId,
                isMoving: false
              } : lead
            ));

            showNotification('success', `Lead movido para ${columnType}`);
            console.log(`✅ Lead ${cardId} persistido em ${columnType} (stageId: ${targetStageId})`);
            if (columnType === 'Ganhou') {
              navigate(`/customers?leadId=${cardId}&action=sale`);
            }

          } catch (error) {
            // Reverter estado em caso de erro
            setLeads(prev => prev.map(lead =>
              lead.id === cardId ? { ...lead, isMoving: false } : lead
            ));

            console.error('❌ Erro ao mover para coluna especial:', error);
            showNotification('error', 'Erro ao mover lead. Tente novamente.');
          }
        } else {
          // Fallback se não tiver stageId (não deveria acontecer)
          setLeads(prev => prev.map(lead =>
            lead.id === cardId ? {
              ...lead,
              columnId: destColId,
              currentStageId: 0,
              isMoving: false
            } : lead
          ));

          const columnType = destColumn.title?.toLowerCase().includes('ganhou') ? 'Ganhou' :
            destColumn.title?.toLowerCase().includes('perdido') ? 'Perdido' : 'Especial';

          showNotification('success', `Lead movido para ${columnType}`);
          console.log(`⚠️ Lead ${cardId} movido para ${columnType} sem stageId válido`);
        }
      } else {
        // 2. Movimentação com persistência para colunas de pipeline
        const userId = parseInt(localStorage.getItem('user_id') || sessionStorage.getItem('user_id') || '0', 10);

        // Validar se estágio é válido
        const targetStageId = parseInt(destColId);
        if (isNaN(targetStageId)) {
          throw new Error('ID de estágio inválido');
        }

        // Chamar API com retry automático (enviar userId apenas se for válido)
        await retryMove(
          cardId,
          targetStageId,
          userId || 0,
          'Movido via drag & drop'
        );

        // Atualizar estado local apenas após sucesso
        setLeads(prev => prev.map(lead =>
          lead.id === cardId ? {
            ...lead,
            columnId: destColId,
            currentStageId: targetStageId,
            isMoving: false
          } : lead
        ));

        showNotification('success', 'Lead movido com sucesso');
        console.log(`✅ Lead ${cardId} persistido no estágio ${destColId}`);
      }
    } catch (error) {
      console.error(`❌ Falha ao mover lead ${cardId}:`, error);

      // Remover loading state
      setLeads(prev => prev.map(lead =>
        lead.id === cardId ? { ...lead, isMoving: false } : lead
      ));

      // Tratamento específico de erro
      handleMoveError(error);
    } finally {
      setDraggedLeadId(null);
    }
  };

  // --- Filtros ---
  const filteredLeads = leads.filter(lead => {
    const matchesSearch = lead.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      lead.phone.includes(searchTerm);

    const leadDate = lead.date instanceof Date ? lead.date : new Date(lead.date);
    let matchesDate = true;

    if (dateRange.startDate && leadDate < dateRange.startDate) {
      matchesDate = false;
    }
    if (dateRange.endDate && leadDate > dateRange.endDate) {
      matchesDate = false;
    }

    return matchesSearch && matchesDate;
  });

  // Função de refresh manual - recarrega leads e recria colunas
  const handleRefresh = () => {
    setRefreshing(true);

    const reloadData = async () => {
      try {
        setLoading(true);

        // 1. Carregar Leads da tabela leads
        const backendLeads = await crmApi.getLeads();
        const frontendLeads = backendLeads.map(mapBackendLeadToFrontend);
        setLeads(frontendLeads);

        // 2. Criar colunas: padrão + estágios reais do banco
        let allColumns = [...COLUNAS_PADRAO];

        try {
          // Tentar buscar estágios do pipeline do banco
          let pipelineId = 1;
          try {
            const pipelines = await pipelineApi.getPipelines();
            if (pipelines && pipelines.length > 0) {
              pipelineId = pipelines[0].id;

              // Buscar estágios do pipeline
              const stages = await pipelineApi.getStages(pipelineId);
              if (stages && stages.length > 0) {
                // Filtrar estágios que não são colunas padrão
                const customStages = stages
                  .filter(stage => !COLUNAS_PADRAO.some(col => col.id === stage.id.toString()))
                  .map(stage => ({
                    id: stage.id.toString(),
                    title: stage.name,
                    color: stage.color || 'border-yellow-500',
                    order: stage.order,
                    stageId: stage.id,
                    percentageBaseStageId: stage.percentage_base_stage_id ?? null
                  }))
                  .sort((a, b) => a.order - b.order);

                // Encontrar posição de inserção (depois de "Novo Lead")
                const novoLeadIndex = allColumns.findIndex(col => col.id === 'novo_lead');
                const insertIndex = novoLeadIndex + 1;

                // Inserir estágios personalizados entre "Novo Lead" e "Ganhou/Perdido"
                allColumns = [
                  ...allColumns.slice(0, insertIndex),
                  ...customStages,
                  ...allColumns.slice(insertIndex)
                ];
              }
            }
          } catch (pipelineError) {
            console.warn('Falha ao buscar estágios do pipeline, usando apenas colunas padrão:', pipelineError);
          }
        } catch (error) {
          console.warn('Erro ao carregar estágios personalizados:', error);
        }

        setColumns(allColumns);

        console.log(`✅ Dados recarregados: ${frontendLeads.length} leads, colunas padrão + personalizadas`);
      } catch (err) {
        console.error('❌ Erro ao recarregar dados:', err);
        setError('Falha ao atualizar dados do CRM.');
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    };

    reloadData();
  };

  const firstTerminalIndex = columns.findIndex(column => (
    column.title?.toLowerCase().includes('ganhou') ||
    column.title?.toLowerCase().includes('perdido')
  ));
  const editingStageColumn = columns.find(column => column.id === editingStageColumnId);
  const editStageBaseOptions = getPercentageBaseOptions(editingStageColumn);
  const mutedTextClass = 'crm-modern-muted';
  const softSurfaceClass = 'crm-modern-subtle';
  return (
    <div className={cx(
      'crm-workspace flex h-[100dvh] min-h-0 flex-col overflow-hidden sm:h-screen',
      isDark && 'crm-workspace--dark'
    )}>
      <style>{`
        .custom-scrollbar::-webkit-scrollbar { width: 6px; height: 8px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background-color: ${isDark ? 'rgba(255,255,255,0.22)' : 'rgba(2,3,35,0.18)'};
          border-radius: 20px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background-color: ${isDark ? 'rgba(255,255,255,0.36)' : 'rgba(2,3,35,0.32)'};
        }
      `}</style>

      {notification && (
        <div className="fixed right-4 top-4 z-[90] w-[min(420px,calc(100vw-2rem))]">
          <AgentiveAlert
            className="crm-modern-alert"
            title={notification.type === 'success' ? 'Operação concluída' : 'Atenção'}
            variant={notification.type === 'success' ? 'success' : 'error'}
            onClose={() => setNotification(null)}
          >
            {notification.message}
          </AgentiveAlert>
        </div>
      )}

      <section className="crm-toolbar">
        <div className="crm-toolbar__main">
          <div className={cx('crm-toolbar__search flex w-full items-center gap-2', crmModernInputClass(isDark))}>
            <Search className={cx('h-4 w-4 shrink-0', isDark ? 'text-white/40' : 'text-brand/40')} />
            <input
              aria-label="Buscar lead ou telefone"
              type="text"
              placeholder="Buscar lead ou telefone"
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-inherit"
            />
            {searchTerm && (
              <button
                type="button"
                onClick={() => setSearchTerm('')}
                className={crmModernIconButtonClass(isDark, 'neutral', 'min-h-7 min-w-7 p-1')}
                aria-label="Limpar busca"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          <div className="crm-toolbar__date">
            <GlobalDateFilter
              onChange={handleDateFilterChange}
              value={{ preset: dateFilterType, range: dateRange }}
            />
          </div>

          <div aria-label="Visualização do CRM" className="crm-toolbar__views" role="group">
              {[
                { value: 'board' as const, label: 'Board', icon: LayoutGrid },
                { value: 'list' as const, label: 'Lista', icon: List },
              ].map(option => {
                const Icon = option.icon;
                const active = viewMode === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    className={cx(
                      'crm-toolbar__view',
                      active && 'crm-toolbar__view--active'
                    )}
                    aria-pressed={active}
                    onClick={() => setViewMode(option.value)}
                  >
                    <Icon className="h-4 w-4" />
                    <span>{option.label}</span>
                  </button>
                );
              })}
          </div>

          <div className="crm-toolbar__actions custom-scrollbar">
            <button type="button" onClick={handleRefresh} disabled={loading || refreshing} className={crmModernSecondaryButtonClass(isDark)}>
              <RefreshCw className={cx('h-4 w-4', refreshing && 'animate-spin')} />
              <span className="crm-toolbar__secondary-label">Atualizar</span>
            </button>
            <button type="button" onClick={exportToCSV} disabled={loading || filteredLeads.length === 0} className={crmModernSecondaryButtonClass(isDark)}>
              <Download className="h-4 w-4" />
              <span className="crm-toolbar__secondary-label">Exportar</span>
            </button>
            <button
              type="button"
              className={isEditingPipeline ? crmModernPrimaryButtonClass() : crmModernSecondaryButtonClass(isDark)}
              onClick={() => {
                if (!isEditingPipeline) {
                  setNewColumnName('');
                  setNewColumnColor('#020323');
                  setNewColumnPercentageBaseStageId('');
                }
                setIsEditingPipeline(current => !current);
              }}
            >
              <Settings className="h-4 w-4" />
              {isEditingPipeline ? 'Concluir' : 'Pipeline'}
            </button>
            <button
              type="button"
              className={crmModernPrimaryButtonClass()}
              onClick={openNewLeadModal}
              disabled={loading}
            >
              <Plus className="h-4 w-4" />
              Novo lead
            </button>
          </div>
        </div>
      </section>

      {error && (
        <div className="mt-3 shrink-0">
          <AgentiveAlert className="crm-modern-alert" title="Não foi possível carregar o CRM" variant="error">
            <div className="space-y-3">
              <p>{error}</p>
              <button type="button" onClick={handleRefresh} className={crmModernPrimaryButtonClass()}>
                Tentar novamente
              </button>
            </div>
          </AgentiveAlert>
        </div>
      )}

      {loading && !error && (
        <div className="crm-modern-panel crm-loading-row mt-3 flex shrink-0 items-center gap-3">
          <Loader2 className={cx('h-5 w-5 animate-spin', isDark ? 'text-white/60' : 'text-brand/60')} />
          <span className={mutedTextClass}>Carregando leads e etapas do pipeline...</span>
        </div>
      )}

      {editingStageColumn && (
        <div className={cx('crm-work-modal fixed inset-0 z-[80] flex items-center justify-center p-3 sm:p-4', isDark && 'crm-work-modal--dark')}>
          <div className="crm-modern-modal-root fixed inset-0" onClick={cancelEditStage} />
          <div className="crm-modern-modal crm-pipeline-stage-modal relative z-[81] w-full overflow-hidden" role="dialog" aria-modal="true" aria-labelledby="crm-pipeline-stage-title">
            <div className="crm-modern-modal__header crm-pipeline-stage-modal__header flex items-start justify-between gap-4">
              <div className="flex min-w-0 items-center gap-3">
                <span className="crm-pipeline-stage-modal__icon" aria-hidden="true">
                  <Settings className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <p className="crm-pipeline-stage-modal__eyebrow">Pipeline</p>
                  <h2 id="crm-pipeline-stage-title" className="truncate text-base font-semibold leading-tight">Editar etapa</h2>
                  <p className={cx('mt-1 text-xs', mutedTextClass)}>{editingStageColumn.title}</p>
                </div>
              </div>
              <button type="button" onClick={cancelEditStage} className={crmModernIconButtonClass(isDark)} aria-label="Fechar edição da etapa">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="crm-modern-modal__body crm-pipeline-stage-modal__body space-y-4">
              <div>
                <label className={crmModernLabelClass(isDark)}>Nome da etapa</label>
                <input
                  type="text"
                  value={editStageName}
                  onChange={(event) => setEditStageName(event.target.value)}
                  className={crmModernInputClass(isDark)}
                  autoFocus
                />
              </div>

              <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                <div>
                  <label className={crmModernLabelClass(isDark)}>Cor</label>
                  <label className={cx('crm-pipeline-stage-modal__color-control', softSurfaceClass)}>
                    <input
                      type="color"
                      value={editStageColor}
                      onChange={(event) => setEditStageColor(event.target.value)}
                      aria-label="Escolher cor da etapa"
                    />
                    <span className="crm-pipeline-stage-modal__color-preview" style={{ backgroundColor: editStageColor }} />
                    <span className={cx('font-mono text-xs uppercase', mutedTextClass)}>{editStageColor}</span>
                  </label>
                </div>

                <div>
                  <label className={crmModernLabelClass(isDark)}>% comparado com</label>
                  <select
                    value={editStagePercentageBaseStageId}
                    onChange={(event) => setEditStagePercentageBaseStageId(event.target.value)}
                    className={crmModernInputClass(isDark)}
                  >
                    <option value="">Leads</option>
                    {editStageBaseOptions.map(option => (
                      <option key={option.id} value={option.stageId}>
                        {option.title}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <p className={cx('text-xs leading-relaxed', mutedTextClass)}>
                A referência escolhida determina a conversão exibida no dashboard.
              </p>
            </div>

            <div className="crm-modern-modal__footer flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={cancelEditStage} className={crmModernSecondaryButtonClass(isDark)}>
                Cancelar
              </button>
              <button type="button" onClick={saveEditStage} className={crmModernPrimaryButtonClass()}>
                Salvar etapa
              </button>
            </div>
          </div>
        </div>
      )}

      <AgentiveConfirmModal
        appearance="modern"
        cancelText="Cancelar"
        confirmText="Remover etapa"
        isOpen={Boolean(stageDeleteColumn)}
        message="Os leads desta etapa serão movidos para Novo Lead. Esta ação altera a organização do pipeline."
        onClose={() => setStageDeleteColumn(null)}
        onConfirm={confirmRemoveColumn}
        title={`Remover ${stageDeleteColumn?.title || 'etapa'}?`}
        variant="warning"
      />

      <div className="relative mt-3 min-h-0 flex-1">
        {viewMode === 'board' ? (
        <div className={cx(
          'crm-board-shell absolute inset-0 overflow-x-auto overflow-y-hidden p-3 custom-scrollbar sm:p-4'
        )}>
          <DragDropContext onDragEnd={handleDragEnd} onDragStart={handleDragStart}>
          <div className="crm-board-grid flex h-full min-w-max gap-4">
            {columns.map((column, index) => {
              const showAddStageBefore = isEditingPipeline && index === firstTerminalIndex;
              const columnLeads = sortLeadsByEntryRecency(
                filteredLeads.filter(lead => lead.columnId === column.id),
              );

              return (
                <React.Fragment key={column.id}>
                  {showAddStageBefore && (
                    <div className="crm-pipeline-add-stage flex w-[calc(100vw-3.5rem)] max-w-72 shrink-0 flex-col sm:w-[288px] sm:max-w-none">
                      <div className="crm-add-stage">
                        <div className="crm-add-stage__header">
                          <div>
                            <p className="crm-add-stage__eyebrow">Pipeline</p>
                            <h3>Nova etapa</h3>
                          </div>
                          <span className="crm-add-stage__icon" aria-hidden="true"><Plus className="h-4 w-4" /></span>
                        </div>
                        <p className={cx('crm-add-stage__description', mutedTextClass)}>Insira antes das etapas finais.</p>
                        <input
                          type="text"
                          value={newColumnName}
                          onChange={(event) => setNewColumnName(event.target.value)}
                          placeholder="Nome da etapa"
                          className={crmModernInputClass(isDark)}
                          onKeyDown={(event) => event.key === 'Enter' && addColumn()}
                          autoFocus
                        />
                        <div className="crm-add-stage__grid">
                          <label>
                            <span className={crmModernLabelClass(isDark)}>Cor</span>
                            <span className={cx('crm-add-stage__color-control', softSurfaceClass)}>
                              <input
                                type="color"
                                value={newColumnColor}
                                onChange={(event) => setNewColumnColor(event.target.value)}
                                aria-label="Escolher cor da nova etapa"
                              />
                              <i style={{ backgroundColor: newColumnColor }} />
                              <b>{newColumnColor}</b>
                            </span>
                          </label>
                          <label>
                            <span className={crmModernLabelClass(isDark)}>% sobre</span>
                            <select
                              value={newColumnPercentageBaseStageId}
                              onChange={(event) => setNewColumnPercentageBaseStageId(event.target.value)}
                              className={crmModernInputClass(isDark)}
                            >
                              <option value="">Leads</option>
                              {getPercentageBaseOptions().map(option => (
                                <option key={option.id} value={option.stageId}>
                                  {option.title}
                                </option>
                              ))}
                            </select>
                          </label>
                        </div>
                        <button type="button" onClick={addColumn} disabled={!newColumnName.trim()} className={crmModernPrimaryButtonClass('w-full')}>
                          <Plus className="h-4 w-4" />
                          Adicionar etapa
                        </button>
                      </div>
                    </div>
                  )}
                  <div
                    className={cx(
                      'crm-kanban-column',
                      minimizedColumns.has(column.id) && 'crm-kanban-column--minimized',
                      minimizedColumns.has(column.id) ? 'w-[68px]' : 'w-[calc(100vw-3.5rem)] max-w-72 sm:w-[320px] sm:max-w-none',
                      'relative flex h-full shrink-0 flex-col overflow-hidden transition-all duration-300'
                    )}
                    style={getStageColumnStyle(column.color)}
                  >
                    {minimizedColumns.has(column.id) ? (
                      <div
                        className={cx('flex h-full w-full cursor-pointer flex-col items-center py-4 transition-colors', isDark ? 'hover:bg-white/[0.06]' : 'hover:bg-white')}
                        onClick={() => toggleMinimizeColumn(column.id)}
                        title="Clique para expandir"
                      >
                        <div className="crm-kanban-column__count mb-6">
                          {columnLeads.length}
                        </div>
                        <div className="flex flex-1 items-center justify-center">
                          <h3
                            className={cx('select-none whitespace-nowrap text-sm font-semibold uppercase', isDark ? 'text-white/55' : 'text-brand/55')}
                            style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}
                          >
                            {column.title}
                          </h3>
                        </div>
                        <div className="mt-6 h-3 w-3 rounded-full" style={getStageDotStyle(column.color)} />
                        <div className={cx('mt-4', isDark ? 'text-white/40' : 'text-brand/40')}>
                          <ChevronRight className="h-4 w-4" />
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="crm-kanban-column__header flex items-center justify-between gap-3 border-b">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={getStageDotStyle(column.color)} />
                              <h3 className="truncate text-sm font-semibold">{column.title}</h3>
                              <span className="crm-kanban-column__stage-count" style={getStageChipStyle(column.color)}>
                                {columnLeads.length}
                              </span>
                            </div>
                            {isEditingPipeline && (
                              <p className={cx('mt-1 truncate text-[11px]', mutedTextClass)}>
                                % sobre {getPercentageBaseLabel(column.percentageBaseStageId)}
                              </p>
                            )}
                          </div>
                          <div className="flex items-center gap-1">
                            {isEditingPipeline && !COLUNAS_PROTEGIDAS.includes(column.id) && (
                              <>
                                <button
                                  type="button"
                                  onClick={() => startEditStage(column)}
                                  className={crmModernIconButtonClass(isDark, 'primary', 'min-h-8 min-w-8 p-1.5')}
                                  title="Editar etapa"
                                >
                                  <Pencil className="h-3.5 w-3.5" />
                                </button>
                                <button
                                  type="button"
                                  onClick={() => requestRemoveColumn(column.id)}
                                  className={crmModernIconButtonClass(isDark, 'danger', 'min-h-8 min-w-8 p-1.5')}
                                  title="Remover etapa"
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </button>
                              </>
                            )}
                            <button
                              type="button"
                              onClick={() => toggleMinimizeColumn(column.id)}
                              className={crmModernIconButtonClass(isDark, 'neutral', 'min-h-8 min-w-8 p-1.5')}
                              title="Minimizar coluna"
                            >
                              <ChevronLeft className="h-4 w-4" />
                            </button>
                          </div>
                        </div>

                        <Droppable droppableId={column.id}>
                          {(provided, snapshot) => (
                            <div
                              ref={provided.innerRef}
                              {...provided.droppableProps}
                              className={cx(
                                'crm-kanban-column__list flex-1 space-y-3 overflow-y-auto custom-scrollbar transition-colors',
                                draggedLeadId && 'crm-kanban-column__list--drag-active',
                                snapshot.isDraggingOver && 'crm-kanban-column__list--drag-over'
                              )}
                            >
                              {columnLeads.map((lead, leadIndex) => (
                                <Draggable
                                  key={lead.id}
                                  draggableId={String(lead.id)}
                                  index={leadIndex}
                                  isDragDisabled={Boolean(lead.isMoving)}
                                >
                                  {(dragProvided, dragSnapshot) => (
                                    <div
                                      ref={dragProvided.innerRef}
                                      {...dragProvided.draggableProps}
                                      {...dragProvided.dragHandleProps}
                                      style={dragProvided.draggableProps.style}
                                    >
                                      <LeadCard
                                        data={lead}
                                        isDragging={dragSnapshot.isDragging || draggedLeadId === lead.id}
                                        onDelete={(id: number) => handleDeleteLead(leads.find(l => l.id === id)!)}
                                        onEdit={(id: number) => handleEditLead(leads.find(l => l.id === id)!)}
                                        onChat={handleOpenChat}
                                        onOpenProfile={handleOpenProfile}
                                      />
                                    </div>
                                  )}
                                </Draggable>
                              ))}

                              {provided.placeholder}

                            </div>
                          )}
                        </Droppable>
                      </>
                    )}
                  </div>
                </React.Fragment>
              );
            })
            }
          </div>
          </DragDropContext>
        </div>
        ) : (
          <LeadListView
            className="absolute inset-0"
            columns={columns}
            isDark={isDark}
            leads={filteredLeads}
            onChat={handleOpenChat}
            onDelete={handleDeleteLead}
            onEdit={handleEditLead}
            onOpenProfile={handleOpenProfile}
          />
        )}
      </div>

      {showNewLeadModal && (
        <div className={cx('crm-work-modal crm-lead-form-modal-root fixed inset-0 z-[80] flex items-center justify-center p-3 sm:p-4', isDark && 'crm-work-modal--dark')}>
          <div className="crm-modern-modal-root fixed inset-0" onClick={closeNewLeadModal} />
          <div className="crm-modern-modal crm-lead-form-modal relative z-[81] w-full overflow-hidden" role="dialog" aria-modal="true" aria-labelledby="crm-new-lead-title">
            <div className="crm-modern-modal__header crm-lead-form-modal__header">
              <div className="crm-lead-form-modal__heading">
                <span className="crm-lead-form-modal__icon" aria-hidden="true"><UserPlus className="h-4 w-4" /></span>
                <div>
                  <p className="crm-lead-form-modal__eyebrow">CRM</p>
                  <h3 id="crm-new-lead-title" className="crm-lead-form-modal__title">{editingLeadId ? 'Editar lead' : 'Novo lead'}</h3>
                  <p className="crm-lead-form-modal__subtitle">Dados principais para entrada no pipeline.</p>
                </div>
              </div>
              <button
                type="button"
                onClick={closeNewLeadModal}
                className={crmModernIconButtonClass(isDark)}
                aria-label="Fechar modal"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="crm-modern-modal__body crm-lead-form-modal__body custom-scrollbar max-h-[calc(100dvh-11rem)] overflow-y-auto sm:max-h-[calc(100vh-13rem)]">
              {!editingLeadId && (
                <div className={cx('crm-lead-form-modal__section crm-contact-linker p-3', softSurfaceClass)}>
                  <div className="flex items-start gap-3">
                    <span className={cx('grid h-10 w-10 shrink-0 place-items-center rounded-xl', isDark ? 'bg-white/10 text-white/80' : 'bg-white text-brand')}>
                      <UserPlus className="h-4 w-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold">Buscar contato existente</p>
                      <p className={cx('mt-1 text-xs leading-relaxed', mutedTextClass)}>
                        Vincule um contato da base ao CRM sem recriar telefone ou conversa.
                      </p>
                    </div>
                  </div>

                  {selectedContact ? (
                    <div className="crm-selected-contact mt-3 p-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex min-w-0 items-center gap-3">
                          <ContactAvatar contact={selectedContact} isDark={isDark} />
                          <div className="min-w-0">
                            <p className={cx('truncate text-sm font-semibold', isDark ? 'text-white' : 'text-brand')}>{selectedContact.name || 'Contato sem nome'}</p>
                            <p className={cx('mt-0.5 truncate font-mono text-xs', isDark ? 'text-white/55' : 'text-brand/55')}>{selectedContact.phone}</p>
                          </div>
                        </div>
                        <button type="button" onClick={handleClearSelectedContact} className={crmModernSecondaryButtonClass(isDark, 'shrink-0 px-3 py-2 text-xs')}>
                          Remover
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className={cx('mt-3 flex min-h-11 items-center gap-2', crmModernInputClass(isDark))}>
                        <Search className={cx('h-4 w-4 shrink-0', isDark ? 'text-white/40' : 'text-brand/40')} />
                        <input
                          type="text"
                          value={contactSearchTerm}
                          onChange={(event) => setContactSearchTerm(event.target.value)}
                          className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-inherit"
                          placeholder="Buscar por nome ou telefone"
                        />
                        {contactSearchLoading && <Loader2 className={cx('h-4 w-4 shrink-0 animate-spin', isDark ? 'text-white/45' : 'text-brand/45')} />}
                      </div>

                      {contactSearchError && (
                        <p className="mt-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
                          {contactSearchError}
                        </p>
                      )}

                      {contactSearchTerm.trim().length >= 2 && !contactSearchLoading && !contactSearchError && contactSearchResults.length === 0 && (
                        <p className={cx('mt-2 rounded-xl border px-3 py-2 text-xs', isDark ? 'border-white/10 bg-white/[0.04] text-white/50' : 'border-brand/10 bg-white text-brand/50')}>
                          Nenhum contato livre encontrado para essa busca.
                        </p>
                      )}

                      {contactSearchResults.length > 0 && (
                        <div className="mt-2 space-y-2">
                          {contactSearchResults.map(contact => (
                            <button
                              key={contact.id}
                              type="button"
                              className="crm-contact-result"
                              onClick={() => handleSelectContact(contact)}
                            >
                              <div className="flex min-w-0 items-center gap-3">
                                <ContactAvatar contact={contact} isDark={isDark} />
                                <div className="min-w-0">
                                  <p className="truncate text-sm font-semibold">{contact.name || 'Contato sem nome'}</p>
                                  <p className={cx('mt-0.5 truncate font-mono text-xs', mutedTextClass)}>{contact.phone}</p>
                                </div>
                              </div>
                              <span className={crmModernBadgeClass(isDark, true)}>
                                <Link2 className="h-3 w-3" />
                                Vincular
                              </span>
                            </button>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}

              <div className="crm-lead-form-modal__section">
                <p className="crm-lead-form-modal__section-heading">Dados do lead</p>
              <div className="crm-lead-form-modal__field">
                <label className={crmModernLabelClass(isDark)}>Nome *</label>
                <input
                  type="text"
                  value={newLead.name}
                  onChange={(e) => setNewLead({ ...newLead, name: e.target.value })}
                  className={crmModernInputClass(isDark, 'p-3')}
                  placeholder="Digite o nome do lead"
                  disabled={Boolean(selectedContact)}
                />
              </div>

              <div className="crm-lead-form-modal__field">
                <label className={crmModernLabelClass(isDark)}>Telefone *</label>
                <div className={cx('crm-phone-field', softSurfaceClass)}>
                  <CountryDialSelector
                    disabled={Boolean(selectedContact)}
                    isDark={isDark}
                    onSelect={handleCountryChange}
                    selectedCountry={newLead.selectedCountry}
                  />
                  <div className="relative min-w-0 flex-1">
                    <input
                      type="text"
                      value={newLead.phone}
                      onChange={(e) => handlePhoneChange(e.target.value)}
                      className={crmModernInputClass(isDark, cx('p-3 pr-8', newLead.phone && !isPhoneComplete() && (isDark ? 'border-amber-400/50' : 'border-amber-300')))}
                      placeholder={newLead.selectedCountry.code === 'BR' ? 'DDD + número' : 'Phone number'}
                      maxLength={newLead.selectedCountry.code === 'BR' ? 15 : 14}
                      disabled={Boolean(selectedContact)}
                    />
                    {newLead.phone && (
                      <span className={cx('absolute right-3 top-1/2 h-2 w-2 -translate-y-1/2 rounded-full', isPhoneComplete() ? 'bg-emerald-500' : 'bg-amber-500')} />
                    )}
                  </div>
                </div>
                <div className="mt-1 flex justify-between gap-3 text-xs">
                  <p className={mutedTextClass}>
                    {newLead.selectedCountry.code === 'BR' ? '(21) 98888-7777 ou (21) 8888-7777' :
                      newLead.selectedCountry.code === 'US' ? '(555) 123-4567' : '(11) 1234-5678'}
                  </p>
                  {newLead.phone && !isPhoneComplete() && (
                    <p className="font-medium text-amber-600">
                      {newLead.selectedCountry.code === 'BR'
                        ? `${getRawPhone(newLead.phone).length}/11`
                        : `${getRawPhone(newLead.phone).length}/${newLead.selectedCountry.phoneLength.max}`}
                    </p>
                  )}
                </div>
              </div>

              <div className="crm-lead-form-modal__grid crm-lead-form-modal__grid--two">
              <div className="crm-lead-form-modal__field">
                <label className={crmModernLabelClass(isDark)}>Mídia</label>
                <select
                  value={newLead.source_id}
                  onChange={(e) => setNewLead({ ...newLead, source_id: e.target.value })}
                  className={crmModernInputClass(isDark, 'p-3')}
                >
                  <option value="">Selecione...</option>
                  {mediaOptions.filter(m => m.active).map(option => (
                    <option key={option.id} value={option.name}>{option.name}</option>
                  ))}
                </select>
              </div>

              <div className="crm-lead-form-modal__field">
                <label className={crmModernLabelClass(isDark)}>Data de entrada</label>
                <div className="relative">
                  <input
                    type="datetime-local"
                    value={newLead.data_entrada}
                    onChange={(e) => handleDateTimeChange(e.target.value)}
                    max={`${new Date().getFullYear() + 10}-12-31T23:59`}
                    min="1900-01-01T00:00"
                    disabled={!isDateEditable}
                    className={crmModernInputClass(isDark, cx('p-3 pr-11', newLead.data_entrada && !validateDateTime(newLead.data_entrada) && 'border-red-400/60'))}
                  />
                  <button
                    type="button"
                    onClick={() => setIsDateEditable(!isDateEditable)}
                    className={crmModernIconButtonClass(isDark, 'neutral', 'absolute right-1.5 top-1/2 min-h-8 min-w-8 -translate-y-1/2 p-1.5')}
                    title={isDateEditable ? 'Bloquear data' : 'Editar data'}
                    aria-label={isDateEditable ? 'Bloquear data' : 'Editar data'}
                  >
                    <Settings className="h-3.5 w-3.5" />
                  </button>
                </div>
                {newLead.data_entrada && !validateDateTime(newLead.data_entrada) && (
                  <p className="mt-1 text-xs text-red-600">Data inválida. Use um ano real com 4 dígitos.</p>
                )}
              </div>
              </div>
              </div>
            </div>

            <div className="crm-modern-modal__footer flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={closeNewLeadModal}
                className={crmModernSecondaryButtonClass(isDark)}
              >
                Cancelar
              </button>
              <button type="button" onClick={handleSaveLead} disabled={actionLoading === -1} className={crmModernPrimaryButtonClass()}>
                {actionLoading === -1 ? 'Salvando...' : selectedContact ? 'Vincular lead' : editingLeadId ? 'Salvar' : 'Criar lead'}
              </button>
            </div>
          </div>
        </div>
      )}

      <AgentiveConfirmModal
        appearance="modern"
        cancelText="Cancelar"
        confirmText="Excluir lead"
        isLoading={actionLoading === selectedLead?.id}
        isOpen={showDeleteModal && Boolean(selectedLead)}
        message="Esta ação remove o lead e vínculos operacionais relacionados de forma permanente."
        onClose={() => {
          setShowDeleteModal(false);
          setSelectedLead(null);
        }}
        onConfirm={confirmDeleteLead}
        title="Excluir lead?"
        variant="danger"
      >
        <div className={isDark ? 'text-white/75' : 'text-brand/70'}>
          <p className="font-semibold">{selectedLead?.name}</p>
          <p className="mt-0.5 font-mono text-xs opacity-75">{selectedLead?.phone}</p>
          <ul className="mt-3 list-inside list-disc space-y-1 text-xs">
            <li>Dados do lead</li>
            <li>Histórico de interações</li>
            <li>Tarefas relacionadas</li>
          </ul>
        </div>
      </AgentiveConfirmModal>

      {showEditModal && selectedLead && (
        <div className={cx('crm-work-modal crm-lead-form-modal-root fixed inset-0 z-[80] flex items-center justify-center p-3 sm:p-4', isDark && 'crm-work-modal--dark')}>
          <div className="crm-modern-modal-root fixed inset-0" onClick={() => setShowEditModal(false)} />
          <div className="crm-modern-modal crm-lead-form-modal crm-lead-form-modal--edit relative z-[81] w-full overflow-hidden" role="dialog" aria-modal="true" aria-labelledby="crm-edit-lead-title">
            <div className="crm-modern-modal__header crm-lead-form-modal__header">
              <div className="crm-lead-form-modal__heading">
                <span className="crm-lead-form-modal__icon" aria-hidden="true"><Pencil className="h-4 w-4" /></span>
                <div>
                  <p className="crm-lead-form-modal__eyebrow">CRM</p>
                  <h3 id="crm-edit-lead-title" className="crm-lead-form-modal__title">Editar lead</h3>
                  <p className="crm-lead-form-modal__subtitle">Atualize dados sem alterar o histórico do pipeline.</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => {
                  setShowEditModal(false);
                  setSelectedLead(null);
                  setEditLeadData({ name: '', phone: '', source_id: 'Facebook', data_entrada: '', selectedCountry: countries[0] });
                }}
                className={crmModernIconButtonClass(isDark)}
                aria-label="Fechar modal"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="crm-modern-modal__body crm-lead-form-modal__body custom-scrollbar max-h-[calc(100dvh-11rem)] overflow-y-auto sm:max-h-[calc(100vh-13rem)]">
              <div className="crm-lead-form-modal__section">
                <p className="crm-lead-form-modal__section-heading">Dados do lead</p>
              <div className="crm-lead-form-modal__field">
                <label className={crmModernLabelClass(isDark)}>Nome *</label>
                <input
                  type="text"
                  value={editLeadData.name}
                  onChange={(e) => setEditLeadData({ ...editLeadData, name: e.target.value })}
                  className={crmModernInputClass(isDark, 'p-3')}
                  placeholder="Digite o nome do lead"
                />
              </div>

              <div className="crm-lead-form-modal__field">
                <label className={crmModernLabelClass(isDark)}>Telefone *</label>
                <div className={cx('crm-phone-field', softSurfaceClass)}>
                  <CountryDialSelector
                    isDark={isDark}
                    onSelect={(countryCode) => {
                      const country = countries.find(c => c.code === countryCode);
                      if (country) {
                        const maskedPhone = maskPhoneByCountry(editLeadData.phone, country);
                        setEditLeadData({ ...editLeadData, selectedCountry: country, phone: maskedPhone });
                      }
                    }}
                    selectedCountry={editLeadData.selectedCountry}
                  />
                  <div className="relative min-w-0 flex-1">
                    <input
                      type="text"
                      value={editLeadData.phone}
                      onChange={(e) => handleEditPhoneChange(e.target.value)}
                      className={crmModernInputClass(isDark, cx('p-3 pr-8', editLeadData.phone && !isEditPhoneComplete() && (isDark ? 'border-amber-400/50' : 'border-amber-300')))}
                      placeholder={editLeadData.selectedCountry.code === 'BR' ? 'DDD + número' : 'Phone number'}
                      maxLength={editLeadData.selectedCountry.code === 'BR' ? 15 : 14}
                    />
                    {editLeadData.phone && (
                      <span className={cx('absolute right-3 top-1/2 h-2 w-2 -translate-y-1/2 rounded-full', isEditPhoneComplete() ? 'bg-emerald-500' : 'bg-amber-500')} />
                    )}
                  </div>
                </div>
                <div className="mt-1 flex justify-between gap-3 text-xs">
                  <p className={mutedTextClass}>
                    Formato: {editLeadData.selectedCountry.code === 'BR' ? '(21) 98888-7777 ou (21) 8888-7777' :
                      editLeadData.selectedCountry.code === 'US' ? '(555) 123-4567' : '(11) 1234-5678'}
                  </p>
                  {editLeadData.phone && !isEditPhoneComplete() && (
                    <p className="font-medium text-amber-600">
                      {editLeadData.selectedCountry.code === 'BR'
                        ? `${getRawPhone(editLeadData.phone).length}/11`
                        : `${getRawPhone(editLeadData.phone).length}/${editLeadData.selectedCountry.phoneLength.max}`}
                    </p>
                  )}
                </div>
              </div>

              <div className="crm-lead-form-modal__grid crm-lead-form-modal__grid--two">
              <div className="crm-lead-form-modal__field">
                <label className={crmModernLabelClass(isDark)}>Mídia</label>
                <select
                  value={editLeadData.source_id}
                  onChange={(e) => setEditLeadData({ ...editLeadData, source_id: e.target.value })}
                  className={crmModernInputClass(isDark, 'p-3')}
                >
                  <option value="">Selecione...</option>
                  {mediaOptions.filter(m => m.active).map(option => (
                    <option key={option.id} value={option.name}>{option.name}</option>
                  ))}
                </select>
              </div>

              <div className="crm-lead-form-modal__field">
                <label className={crmModernLabelClass(isDark)}>Data de entrada</label>
                <div className="relative">
                  <input
                    type="datetime-local"
                    value={editLeadData.data_entrada}
                    onChange={(e) => setEditLeadData({ ...editLeadData, data_entrada: e.target.value })}
                    max={`${new Date().getFullYear() + 10}-12-31T23:59`}
                    min="1900-01-01T00:00"
                    className={crmModernInputClass(isDark, cx('p-3', editLeadData.data_entrada && !validateDateTime(editLeadData.data_entrada) && 'border-red-400/60'))}
                  />
                </div>
              </div>
              </div>
              </div>
            </div>

            <div className="crm-modern-modal__footer flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                <button
                  type="button"
                  onClick={() => {
                    setShowEditModal(false);
                    setSelectedLead(null);
                    setEditLeadData({ name: '', phone: '', source_id: '', data_entrada: '', selectedCountry: countries[0] });
                  }}
                  className={crmModernSecondaryButtonClass(isDark)}
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  onClick={confirmEditLead}
                  disabled={actionLoading === selectedLead?.id || !editLeadData.name.trim() || !editLeadData.phone.trim() || !isEditPhoneComplete()}
                  className={crmModernPrimaryButtonClass()}
                >
                  {actionLoading === selectedLead?.id ? 'Salvando...' : 'Salvar lead'}
                </button>
              </div>
            </div>
          </div>
      )}

      {selectedProfileLead && (
        <LeadProfile
          contextActions={(
            <button
              type="button"
              onClick={() => handleOpenChat(selectedProfileLead)}
              className={cx(crmModernIconButtonClass(isDark, 'primary', 'crm-action-icon'), 'crm-lead-inspector__action')}
              aria-label="Abrir conversa"
              title="Abrir conversa"
            >
              <MessageCircle className="h-4 w-4" />
            </button>
          )}
          isOpen={showProfileModal}
          onClose={() => {
            setShowProfileModal(false);
            setSelectedProfileLead(null);
          }}
          lead={{
            ...selectedProfileLead,
            stageName: columns.find(column => column.id === selectedProfileLead.columnId)?.title,
          }}
        />
      )}
    </div>
  );
}

interface CountryDialSelectorProps {
  disabled?: boolean;
  isDark: boolean;
  onSelect: (countryCode: string) => void;
  selectedCountry: typeof countries[number];
}

function CountryDialSelector({ disabled = false, isDark, onSelect, selectedCountry }: CountryDialSelectorProps) {
  return (
    <div className="mb-2 flex flex-wrap gap-1">
      {countries.map(country => {
        const active = selectedCountry.code === country.code;
        return (
          <button
            key={country.code}
            type="button"
            disabled={disabled}
            onClick={() => onSelect(country.code)}
            className={cx(
              'crm-country-dial',
              active && 'crm-country-dial--active'
            )}
          >
            <span>{country.flag}</span>
            <span>+{country.ddi}</span>
          </button>
        );
      })}
    </div>
  );
}

function ContactAvatar({ contact, isDark: _isDark }: { contact: ContactSearchResult; isDark: boolean }) {
  return (
    <div className="crm-contact-avatar">
      {contact.photo ? (
        <img src={contact.photo} alt={contact.name || 'Contato'} className="h-full w-full object-cover" />
      ) : (
        getInitials(contact.name || 'CT')
      )}
    </div>
  );
}

function LeadAvatar({
  className = '',
  lead,
  isDark: _isDark,
  size = 'md',
}: {
  className?: string;
  lead: Pick<Lead, 'name' | 'thumbnailUrl'>;
  isDark: boolean;
  size?: 'sm' | 'md';
}) {
  const [imageFailed, setImageFailed] = useState(false);
  const sizeClass = size === 'sm' ? 'crm-lead-avatar--sm' : 'crm-lead-avatar--md';
  const canShowImage = Boolean(lead.thumbnailUrl && !imageFailed);

  return (
    <div className={cx(
      'crm-lead-avatar',
      sizeClass,
      className
    )}>
      {canShowImage ? (
        <img
          src={lead.thumbnailUrl}
          alt={lead.name || 'Lead'}
          className="h-full w-full object-cover"
          onError={() => setImageFailed(true)}
        />
      ) : (
        getInitials(lead.name)
      )}
    </div>
  );
}

interface LeadListViewProps {
  className?: string;
  columns: Column[];
  isDark: boolean;
  leads: Lead[];
  onChat: (lead: Lead) => void;
  onDelete: (lead: Lead) => void;
  onEdit: (lead: Lead) => void;
  onOpenProfile: (lead: Lead) => void;
}

function LeadListView({ className = '', columns, isDark, leads, onChat, onDelete, onEdit, onOpenProfile }: LeadListViewProps) {
  const mutedTextClass = isDark ? 'text-white/55' : 'text-brand/55';
  const rowBorderClass = isDark ? 'border-white/10' : 'border-brand/10';
  const sortedLeads = sortLeadsByEntryRecency(leads);

  const getStage = (lead: Lead) => columns.find(column => column.id === lead.columnId);
  const formatLeadDate = (lead: Lead) => {
    const date = lead.date instanceof Date ? lead.date : new Date(lead.date);
    if (Number.isNaN(date.getTime())) return '-';
    return date.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  };
  const getAgendaLabel = (lead: Lead) => {
    if (lead.consulta_data_display) return lead.consulta_data_display;
    if (lead.consulta_data) {
      const date = new Date(lead.consulta_data);
      if (!Number.isNaN(date.getTime())) {
        return date.toLocaleString('pt-BR', {
          day: '2-digit',
          month: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          timeZone: lead.consulta_timezone || 'America/Sao_Paulo',
        });
      }
    }
    return lead.nextTask?.title || 'Sem agenda';
  };

  if (sortedLeads.length === 0) {
    return (
      <div className={cx('crm-lead-list', className)}>
        <CrmModernEmptyState
          icon={Users}
          title="Nenhum lead encontrado"
          description="Ajuste a busca ou o periodo para ver leads nesta lista."
          className="h-full min-h-[320px] px-4 py-10"
        />
      </div>
    );
  }

  return (
    <div className={cx('crm-lead-list overflow-hidden', className)}>
      <div className="hidden h-full overflow-auto custom-scrollbar lg:block">
        <table className="min-w-[980px] w-full border-separate border-spacing-0 text-left text-sm">
          <thead className={cx('sticky top-0 z-10', isDark ? 'bg-brand text-white/55' : 'bg-white text-brand/55')}>
            <tr>
              {['Lead', 'Etapa', 'Origem', 'Entrada', 'Agenda', 'Acoes'].map(label => (
                <th key={label} className={cx('border-b px-4 py-3 text-xs font-semibold', rowBorderClass)}>
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedLeads.map(lead => {
              const stage = getStage(lead);
              return (
                <tr key={lead.id} className="crm-lead-list__row transition-colors">
                  <td className={cx('border-b px-4 py-3', rowBorderClass)}>
                    <div className="flex min-w-0 items-center gap-3">
                      <LeadAvatar lead={lead} isDark={isDark} />
                      <div className="min-w-0">
                        <p className="truncate font-semibold">{lead.name || 'Sem nome'}</p>
                        <p className={cx('mt-0.5 truncate font-mono text-xs', mutedTextClass)}>{lead.phone || 'Sem telefone'}</p>
                      </div>
                    </div>
                  </td>
                  <td className={cx('border-b px-4 py-3', rowBorderClass)}>
                    {stage ? (
                      <span className="crm-stage-label max-w-[180px]" style={getStageChipStyle(stage.color)}>
                        <span className="h-2 w-2 shrink-0 rounded-full" style={getStageDotStyle(stage.color)} />
                        <span className="truncate">{stage.title}</span>
                      </span>
                    ) : (
                      <span className={crmModernBadgeClass(isDark)}>Sem etapa</span>
                    )}
                  </td>
                  <td className={cx('border-b px-4 py-3', rowBorderClass)}>
                    <span className={cx('truncate', mutedTextClass)}>{lead.sourceId || '-'}</span>
                  </td>
                  <td className={cx('border-b px-4 py-3', rowBorderClass)}>
                    <span className={mutedTextClass}>{formatLeadDate(lead)}</span>
                  </td>
                  <td className={cx('border-b px-4 py-3', rowBorderClass)}>
                    <span className={cx('line-clamp-1', lead.consulta_data || lead.nextTask ? '' : mutedTextClass)}>
                      {getAgendaLabel(lead)}
                    </span>
                  </td>
                  <td className={cx('border-b px-4 py-3', rowBorderClass)}>
                    <div className="crm-lead-actions ml-auto">
                      <button type="button" title="Perfil" aria-label="Abrir perfil" className={crmModernIconButtonClass(isDark, 'primary', 'crm-action-icon')} onClick={() => onOpenProfile(lead)}>
                        <Eye className="h-3.5 w-3.5" />
                      </button>
                      <button type="button" title="Chat" aria-label="Abrir chat" className={crmModernIconButtonClass(isDark, 'success', 'crm-action-icon')} onClick={() => onChat(lead)}>
                        <MessageCircle className="h-3.5 w-3.5" />
                      </button>
                      <button type="button" title="Editar" aria-label="Editar lead" className={crmModernIconButtonClass(isDark, 'neutral', 'crm-action-icon')} onClick={() => onEdit(lead)}>
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button type="button" title="Excluir" aria-label="Excluir lead" className={crmModernIconButtonClass(isDark, 'danger', 'crm-action-icon')} onClick={() => onDelete(lead)}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="h-full space-y-3 overflow-y-auto p-3 custom-scrollbar lg:hidden">
        {sortedLeads.map(lead => {
          const stage = getStage(lead);
          return (
            <article key={lead.id} className="crm-lead-card">
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3">
                  <LeadAvatar lead={lead} isDark={isDark} />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold">{lead.name || 'Sem nome'}</p>
                    <p className={cx('mt-0.5 truncate font-mono text-xs', mutedTextClass)}>{lead.phone || 'Sem telefone'}</p>
                  </div>
                </div>
                <button type="button" title="Abrir perfil" className={crmModernIconButtonClass(isDark, 'primary', 'crm-action-icon')} onClick={() => onOpenProfile(lead)} aria-label="Abrir perfil">
                  <Eye className="h-3.5 w-3.5" />
                </button>
              </div>

              <div className="mt-3 flex flex-wrap gap-1.5">
                {stage && (
                  <span className="crm-stage-label max-w-full" style={getStageChipStyle(stage.color)}>
                    <span className="h-2 w-2 shrink-0 rounded-full" style={getStageDotStyle(stage.color)} />
                    <span className="truncate">{stage.title}</span>
                  </span>
                )}
                {lead.sourceId && <span className={crmModernBadgeClass(isDark)}>{lead.sourceId}</span>}
                <span className={crmModernBadgeClass(isDark)}>{formatLeadDate(lead)}</span>
              </div>

              <p className={cx('mt-3 line-clamp-2 text-xs', mutedTextClass)}>{getAgendaLabel(lead)}</p>

              <div className={cx('mt-3 flex justify-end border-t pt-2', rowBorderClass)}>
                <div className="crm-lead-actions">
                  <button type="button" title="Abrir chat" className={crmModernIconButtonClass(isDark, 'success', 'crm-action-icon')} onClick={() => onChat(lead)} aria-label="Abrir chat">
                    <MessageCircle className="h-3.5 w-3.5" />
                  </button>
                  <button type="button" title="Editar lead" className={crmModernIconButtonClass(isDark, 'neutral', 'crm-action-icon')} onClick={() => onEdit(lead)} aria-label="Editar lead">
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                  <button type="button" title="Excluir lead" className={crmModernIconButtonClass(isDark, 'danger', 'crm-action-icon')} onClick={() => onDelete(lead)} aria-label="Excluir lead">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

// Componente LeadCard simples
function LeadCard({
  data,
  isDragging,
  onDelete,

  onEdit,
  onChat,
  onOpenProfile
}: {
  data: Lead,
  isDragging: boolean,
  onDelete: (id: number) => void,
  onEdit: (id: number) => void,
  onChat: (data: Lead) => void,
  onOpenProfile: (data: Lead) => void
}) {
  const { isDark } = useTheme();
  const [showMenu, setShowMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const createdAt = data.date instanceof Date ? data.date : new Date(data.date);
  const createdAtLabel = Number.isNaN(createdAt.getTime())
    ? 'Sem data'
    : createdAt.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: '2-digit' });

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node) &&
        buttonRef.current && !buttonRef.current.contains(event.target as Node)) {
        setShowMenu(false);
      }
    }
    function handleEscapeKey(event: KeyboardEvent) {
      if (event.key === 'Escape' && showMenu) {
        setShowMenu(false);
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEscapeKey);

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscapeKey);
    };
  }, [showMenu]);

  return (
    <div
      className={cx(
        'crm-lead-card group relative flex cursor-grab flex-col transition-all active:cursor-grabbing',
        isDragging ? 'crm-lead-card--dragging' : 'opacity-100'
      )}
    >
      {data.isMoving && (
        <div className="crm-lead-card__moving absolute inset-0 z-10 flex items-center justify-center backdrop-blur-sm">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      )}

      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <LeadAvatar className="crm-lead-card__avatar" lead={data} isDark={isDark} />
          <div className="crm-lead-card__identity min-w-0">
            <h4 className="truncate text-sm font-semibold leading-tight">{data.name || 'Sem nome'}</h4>
            <div className={cx('crm-lead-card__meta mt-1 flex items-center gap-1.5 text-[10px] font-medium', isDark ? 'text-white/40' : 'text-brand/40')}>
              <span>#{data.id}</span>
              <span>•</span>
              <span>{createdAtLabel}</span>
            </div>
          </div>
        </div>
        <GripVertical className={cx('h-4 w-4 shrink-0 opacity-0 transition-opacity group-hover:opacity-100', isDark ? 'text-white/35' : 'text-brand/35')} />
      </div>

      <div className="crm-lead-card__details">
        <div className="crm-lead-card__detail">
          <Phone className="h-3 w-3" />
          <span className="truncate">{data.phone || 'Sem telefone'}</span>
        </div>
        {data.sourceId && (
          <div className="crm-lead-card__detail">
            <Megaphone className="h-3 w-3" />
            <span className="truncate">{data.sourceId}</span>
          </div>
        )}
        {data.consulta_data && (
          <div className="crm-lead-card__detail crm-lead-card__detail--appointment">
            <Calendar className="h-3 w-3" />
            <span className="truncate">
              {data.consulta_data_display || new Date(data.consulta_data).toLocaleString('pt-BR', {
                day: '2-digit',
                month: '2-digit',
                year: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                timeZone: data.consulta_timezone || 'America/Sao_Paulo'
              })}
            </span>
          </div>
        )}
      </div>

      {data.custom_values && data.custom_values.some(cv => cv.field_key.startsWith('utm_') && cv.value) && (
        <div className="crm-lead-card__utm-list">
          {data.custom_values
            .filter(cv => cv.field_key.startsWith('utm_') && cv.value)
            .slice(0, 3)
            .map(cv => (
              <div key={cv.field_key} className="crm-lead-card__utm" title={`${cv.field_name}: ${cv.value}`}>
                <span className="font-semibold">{cv.field_key.replace('utm_', '')}:</span> {cv.value}
              </div>
            ))}
        </div>
      )}

      {data.nextTask && <TaskPreview task={data.nextTask} />}

      <div className={cx('crm-lead-card__footer mt-auto flex items-center justify-between gap-2 border-t pt-2', isDark ? 'border-white/10' : 'border-brand/10')}>
        <span className={cx('min-w-0 truncate text-[10px] font-medium', isDark ? 'text-white/35' : 'text-brand/35')}>
          {data.lastActivity || 'Sem atividade recente'}
        </span>
        <div className="crm-lead-actions shrink-0">
          <button type="button" title="Abrir chat" aria-label="Abrir chat" className={crmModernIconButtonClass(isDark, 'success', 'crm-action-icon')} onClick={() => onChat(data)}>
            <MessageCircle className="h-3.5 w-3.5" />
          </button>
          <button type="button" title="Ver perfil" aria-label="Ver perfil" className={crmModernIconButtonClass(isDark, 'primary', 'crm-action-icon')} onClick={() => onOpenProfile(data)}>
            <Eye className="h-3.5 w-3.5" />
          </button>
          <button type="button" title="Editar lead" aria-label="Editar lead" className={crmModernIconButtonClass(isDark, 'neutral', 'crm-action-icon')} onClick={() => onEdit(data.id)}>
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button type="button" title="Excluir lead" aria-label="Excluir lead" className={crmModernIconButtonClass(isDark, 'danger', 'crm-action-icon')} onClick={() => onDelete(data.id)}>
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
