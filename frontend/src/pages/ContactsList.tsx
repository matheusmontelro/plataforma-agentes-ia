import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  Check,
  Copy,
  Download,
  Edit2,
  Filter,
  Inbox,
  Loader2,
  MessageSquare,
  MoreVertical,
  Phone,
  Plus,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Trash2,
  Upload,
  UserPlus,
  Users,
  X,
  type LucideIcon,
} from 'lucide-react';
import api, { downloadRowsAsCsv, getPipelines, PipelineResponse } from '../services/api.ts';

import ContactsImport from '../components/ContactsImport.tsx';
import ConfirmDeleteModal from '../components/ConfirmDeleteModal.tsx';
import StatusTag from '../components/StatusTag.tsx';
import {
  AgentiveAlert,
  AgentiveEmptyState,
  agentiveIconButtonClass,
  agentiveInputClass,
  agentiveLabelClass,
  agentivePageClass,
  agentivePanelClass,
  agentivePillClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';
import { getMediaSources, MediaSource } from '../services/mediaApi.ts';
import { Tag, getTags, removeTagFromContact, updateContactTags } from '../services/tagsApi.ts';
import './ContactsList.css';

const cx = (...args: (string | false | null | undefined)[]) => args.filter(Boolean).join(' ');

type Query = { text?: string; status?: string; tag?: string; owner?: string };
type ActionMenuPosition = { left: number; top: number };
type StatusFilterOption = {
  color?: string;
  kind: 'contact' | 'crm-stage';
  label: string;
  pipelineName?: string;
  value: string;
};

const ACTION_MENU_WIDTH = 208;
const ACTION_MENU_ESTIMATED_HEIGHT = 230;
const ACTION_MENU_GAP = 8;
const ACTION_MENU_VIEWPORT_MARGIN = 12;

function parseQuery(q: string): Query {
  const parts = q.trim().split(/\s+/).filter(Boolean);
  const res: Query = {};
  const rest: string[] = [];

  for (const part of parts) {
    if (part.startsWith('status:')) res.status = part.slice(7);
    else if (part.startsWith('tag:')) res.tag = part.slice(4);
    else if (part.startsWith('dono:') || part.startsWith('owner:')) res.owner = part.split(':')[1];
    else rest.push(part);
  }

  if (rest.length) res.text = rest.join(' ');
  return res;
}

const contactStatusOption: StatusFilterOption = {
  kind: 'contact',
  label: 'Contato',
  value: 'contato',
};

const getContactStatusColors = (isDark: boolean) => (
  isDark
    ? 'border-white/10 bg-white/10 text-white/70'
    : 'border-brand/10 bg-brand-canvas text-brand/70'
);

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
  if (!value) return undefined;

  if (/^#[0-9a-f]{6}$/i.test(value)) return value;
  if (/^#[0-9a-f]{3}$/i.test(value)) {
    const [, r, g, b] = value;
    return `#${r}${r}${g}${g}${b}${b}`;
  }

  const lowered = value.toLowerCase();
  const match = Object.entries(legacyStageColorMap).find(([name]) => lowered.includes(name));
  return match?.[1];
};

const getStageChipStyle = (color?: string): React.CSSProperties | undefined => {
  const stageColor = normalizeStageColor(color);
  if (!stageColor) return undefined;

  return {
    backgroundColor: `${stageColor}16`,
    borderColor: `${stageColor}35`,
    color: stageColor,
  };
};

interface Contact {
  id: number;
  phone: string;
  name: string;
  photo?: string;
  unread_count: number;
  last_message_at?: string;
  last_message?: string;
  human_mode: boolean;
  funnel_stage?: string;
  active_flows?: string[];
  lead_id?: number;
  customer_id?: number;
  tags?: Tag[];
}

interface ContactsResponse {
  contacts: Contact[];
  total: number;
  has_more: boolean;
}

interface ModalShellProps {
  children: React.ReactNode;
  description?: string;
  isDark: boolean;
  onClose: () => void;
  title: string;
}

interface MetricTileProps {
  helper: string;
  icon: LucideIcon;
  isDark: boolean;
  label: string;
  value: React.ReactNode;
}

const getInitials = (name?: string) => {
  const parts = (name || '').trim().split(/\s+/).filter(Boolean);
  return (parts.slice(0, 2).map(part => part[0]).join('') || 'CT').toUpperCase();
};

const getContactKey = (contact: Contact) => contact.id?.toString() || contact.phone || contact.name;

const getActionMenuPosition = (triggerRect: DOMRect): ActionMenuPosition => {
  const maxLeft = window.innerWidth - ACTION_MENU_WIDTH - ACTION_MENU_VIEWPORT_MARGIN;
  const left = Math.max(
    ACTION_MENU_VIEWPORT_MARGIN,
    Math.min(triggerRect.right - ACTION_MENU_WIDTH, maxLeft)
  );

  const bottomTop = triggerRect.bottom + ACTION_MENU_GAP;
  const topTop = triggerRect.top - ACTION_MENU_ESTIMATED_HEIGHT - ACTION_MENU_GAP;
  const hasBottomSpace = bottomTop + ACTION_MENU_ESTIMATED_HEIGHT <= window.innerHeight - ACTION_MENU_VIEWPORT_MARGIN;
  const top = hasBottomSpace
    ? bottomTop
    : Math.max(ACTION_MENU_VIEWPORT_MARGIN, topTop);

  return { left, top };
};

const formatLastMessage = (message?: string) => {
  if (!message) return 'Sem mensagem recente';
  return message.length > 76 ? `${message.substring(0, 76)}...` : message;
};

const formatDate = (dateString?: string) => {
  if (!dateString) return 'Sem data';
  const date = new Date(dateString);
  const now = new Date();
  const diffInHours = (now.getTime() - date.getTime()) / (1000 * 60 * 60);

  if (diffInHours < 24) {
    return date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  }

  if (diffInHours < 168) {
    return date.toLocaleDateString('pt-BR', { weekday: 'short', hour: '2-digit', minute: '2-digit' });
  }

  return date.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
};

const ContactAvatar: React.FC<{ contact: Contact; isDark: boolean; size?: 'sm' | 'md' }> = ({
  contact,
  isDark,
  size = 'md',
}) => {
  const sizeClass = size === 'sm' ? 'h-9 w-9 rounded-xl text-xs' : 'h-11 w-11 rounded-2xl text-sm';

  return (
    <div
      className={cx(
        'grid shrink-0 place-items-center overflow-hidden border font-semibold',
        sizeClass,
        isDark ? 'border-white/10 bg-white/10 text-white' : 'border-brand/10 bg-brand-canvas text-brand'
      )}
    >
      {contact.photo ? (
        <img src={contact.photo} alt={contact.name || 'Contato'} className="h-full w-full object-cover" />
      ) : (
        getInitials(contact.name)
      )}
    </div>
  );
};

const MetricTile: React.FC<MetricTileProps> = ({ helper, icon: Icon, label, value }) => (
  <div className="contacts-metric">
    <span className="contacts-metric__icon" aria-hidden="true">
      <Icon />
    </span>
    <div className="contacts-metric__copy">
      <p>{label}</p>
      <span>{helper}</span>
    </div>
    <strong>{value}</strong>
  </div>
);

const ModalShell: React.FC<ModalShellProps> = ({ children, description, isDark, onClose, title }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand/60 p-4 backdrop-blur-sm">
    <div className={agentivePanelClass(isDark, 'relative max-h-[92vh] w-full max-w-lg overflow-y-auto p-5 shadow-[0_24px_70px_rgba(2,3,35,0.28)]')}>
      <div className="mb-5 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="text-lg font-semibold leading-tight">{title}</h3>
          {description && <p className={cx('mt-1 text-sm', isDark ? 'text-white/55' : 'text-brand/55')}>{description}</p>}
        </div>
        <button type="button" onClick={onClose} className={agentiveIconButtonClass(isDark)} aria-label="Fechar modal">
          <X className="h-4 w-4" />
        </button>
      </div>
      {children}
    </div>
  </div>
);

const ContactsList: React.FC = () => {
  const navigate = useNavigate();
  const { isDark } = useTheme();
  const filterDropdownRef = useRef<HTMLDivElement>(null);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [showArchived, setShowArchived] = useState(false);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [showImport, setShowImport] = useState(false);
  const [actionLoading, setActionLoading] = useState<number | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showLeadModal, setShowLeadModal] = useState(false);
  const [showCustomerModal, setShowCustomerModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [showNewContactModal, setShowNewContactModal] = useState(false);
  const [contactToConvert, setContactToConvert] = useState<Contact | null>(null);
  const [selectedSource, setSelectedSource] = useState('');
  const [editName, setEditName] = useState('');
  const [newContactName, setNewContactName] = useState('');
  const [newContactPhone, setNewContactPhone] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState<number | null>(null);
  const [dropdownPosition, setDropdownPosition] = useState<ActionMenuPosition | null>(null);
  const [pipelines, setPipelines] = useState<PipelineResponse[]>([]);
  const [allTags, setAllTags] = useState<Tag[]>([]);
  const [mediaOptions, setMediaOptions] = useState<MediaSource[]>([]);
  const [tagDropdownOpen, setTagDropdownOpen] = useState(false);
  const limit = 50;

  const tokens = useMemo(() => parseQuery(query), [query]);
  const totalPages = Math.ceil(total / limit);
  const rowPadding = 'py-3.5';
  const allVisibleSelected = contacts.length > 0 && contacts.every(contact => contact.id && selected.has(contact.id.toString()));
  const visibleUnreadCount = contacts.filter(contact => contact.unread_count > 0).length;
  const visibleHumanCount = contacts.filter(contact => contact.human_mode).length;
  const activeFilterCount = [tokens.status, tokens.tag, tokens.owner, unreadOnly, showArchived].filter(Boolean).length;
  const mutedTextClass = isDark ? 'text-white/55' : 'text-brand/55';
  const crmStageOptions = useMemo<StatusFilterOption[]>(() => (
    pipelines.flatMap(pipeline => (
      [...(pipeline.stages || [])]
        .sort((first, second) => first.order - second.order)
        .map(stage => ({
          color: stage.color,
          kind: 'crm-stage' as const,
          label: stage.name,
          pipelineName: pipeline.name,
          value: stage.id.toString(),
        }))
    ))
  ), [pipelines]);
  const statusFilterOptions = useMemo<StatusFilterOption[]>(
    () => [contactStatusOption, ...crmStageOptions],
    [crmStageOptions]
  );
  const activeStatusLabel = tokens.status
    ? statusFilterOptions.find(option => option.value === tokens.status)?.label || tokens.status
    : null;

  const fetchContacts = async () => {
    try {
      setLoading(true);
      setError(null);

      const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
      if (!companyId) {
        setError('ID da empresa não encontrado');
        return;
      }

      const offset = (currentPage - 1) * limit;
      const params = new URLSearchParams({
        company_id: companyId,
        limit: limit.toString(),
        offset: offset.toString(),
        unread_only: unreadOnly.toString(),
      });

      if (showArchived) {
        params.append('archived_only', 'true');
      } else {
        params.append('show_archived', 'false');
      }

      if (tokens.text?.trim()) {
        params.append('search', tokens.text.trim());
      }

      if (tokens.status?.trim()) {
        params.append('funnel_stages', tokens.status.trim());
      }

      const response = await api.get<ContactsResponse>(`/webhook/contacts?${params}`);
      setContacts(response.data.contacts || []);
      setTotal(response.data.total || 0);
    } catch (err: any) {
      const errorMessage = typeof err === 'string'
        ? err
        : err.response?.data?.detail || err.message || 'Erro ao carregar contatos';
      setError(errorMessage);
      console.error('Erro ao buscar contatos:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchContacts();
  }, [currentPage, showArchived, unreadOnly, tokens.status]);

  useEffect(() => {
    async function loadPipelines() {
      try {
        const companyId = parseInt((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')) || '0');
        if (companyId) {
          const data = await getPipelines(companyId);
          setPipelines(data);
        }
      } catch (loadError) {
        console.error('Erro ao carregar pipelines:', loadError);
      }
    }

    loadPipelines();
  }, []);

  useEffect(() => {
    async function fetchTags() {
      try {
        const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
        if (companyId) {
          const tags = await getTags(parseInt(companyId));
          setAllTags(tags);
        }
      } catch (loadError) {
        console.error('Erro ao buscar tags:', loadError);
      }
    }

    fetchTags();
  }, []);

  useEffect(() => {
    const fetchMedia = async () => {
      try {
        const sources = await getMediaSources();
        setMediaOptions(sources);
      } catch (loadError) {
        console.error('Failed to fetch media sources', loadError);
      }
    };

    fetchMedia();
  }, []);

  useEffect(() => {
    const delayedSearch = setTimeout(() => {
      if (currentPage === 1) {
        fetchContacts();
      } else {
        setCurrentPage(1);
      }
    }, 500);

    return () => clearTimeout(delayedSearch);
  }, [query]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as HTMLElement;

      if (filterDropdownRef.current && !filterDropdownRef.current.contains(target)) {
        setShowFilters(false);
      }

      if (dropdownOpen !== null) {
        const dropdownElement = target.closest('[data-dropdown]');
        if (!dropdownElement) {
          setDropdownOpen(null);
          setDropdownPosition(null);
        }
      }
    };

    if (showFilters || dropdownOpen !== null) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [showFilters, dropdownOpen]);

  useEffect(() => {
    if (dropdownOpen === null) return;

    const closeFloatingMenu = () => {
      setDropdownOpen(null);
      setDropdownPosition(null);
    };

    window.addEventListener('resize', closeFloatingMenu);
    window.addEventListener('scroll', closeFloatingMenu, true);

    return () => {
      window.removeEventListener('resize', closeFloatingMenu);
      window.removeEventListener('scroll', closeFloatingMenu, true);
    };
  }, [dropdownOpen]);

  const toggleSelectAll = () => {
    setSelected(prev => {
      const next = new Set(prev);

      if (allVisibleSelected) {
        contacts.forEach(contact => {
          if (contact.id) next.delete(contact.id.toString());
        });
      } else {
        contacts.forEach(contact => {
          if (contact.id) next.add(contact.id.toString());
        });
      }

      return next;
    });
  };

  const toggleContactSelection = (contact: Contact) => {
    if (!contact.id) return;

    setSelected(prev => {
      const next = new Set(prev);
      const id = contact.id.toString();
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const removeToken = (key: keyof Query) => {
    const parts = query.split(/\s+/).filter(Boolean).filter(part => {
      if (key === 'status' && part.startsWith('status:')) return false;
      if (key === 'tag' && part.startsWith('tag:')) return false;
      if (key === 'owner' && (part.startsWith('dono:') || part.startsWith('owner:'))) return false;
      return true;
    });
    setQuery(parts.join(' '));
  };

  const applyStatusFilter = (status: string) => {
    const cleanQuery = query.split(/\s+/).filter(part => !part.startsWith('status:')).join(' ');
    const newQuery = cleanQuery.trim() ? `${cleanQuery} status:${status}` : `status:${status}`;
    setQuery(newQuery);
    setCurrentPage(1);
    setShowFilters(false);
  };

  const resetFilters = () => {
    setQuery('');
    setUnreadOnly(false);
    setShowArchived(false);
    setCurrentPage(1);
  };

  const handleConvertToLead = async (contact: Contact) => {
    setContactToConvert(contact);
    setSelectedSource('');
    setShowLeadModal(true);
  };

  const confirmConvertToLead = async () => {
    if (!contactToConvert) return;

    try {
      setActionLoading(contactToConvert.id);
      await api.post(`/webhook/contacts/${contactToConvert.id}/convert-to-lead`, {
        source_id: selectedSource,
      });
      await fetchContacts();
      setShowLeadModal(false);
      setContactToConvert(null);
    } catch (err: any) {
      const errorMessage = typeof err === 'string'
        ? err
        : err.response?.data?.detail || err.message || 'Erro ao converter para lead';
      setError(errorMessage);
    } finally {
      setActionLoading(null);
    }
  };

  const handleConvertToCustomer = async (contact: Contact) => {
    setContactToConvert(contact);
    setShowCustomerModal(true);
  };

  const confirmConvertToCustomer = async () => {
    if (!contactToConvert) return;

    try {
      setActionLoading(contactToConvert.id);
      await api.post(`/webhook/contacts/${contactToConvert.id}/convert-to-customer`);
      await fetchContacts();
      setShowCustomerModal(false);
      setContactToConvert(null);
    } catch (err: any) {
      const errorMessage = typeof err === 'string'
        ? err
        : err.response?.data?.detail || err.message || 'Erro ao converter para cliente';
      setError(errorMessage);
    } finally {
      setActionLoading(null);
    }
  };

  const handleImportComplete = () => {
    fetchContacts();
  };

  const handleExportContacts = async () => {
    try {
      setLoading(true);
      setError(null);

      const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
      if (!companyId) {
        setError('ID da empresa não encontrado');
        return;
      }

      let allContacts: Contact[] = [];
      let offset = 0;
      const exportLimit = 500;
      let hasMore = true;

      while (hasMore) {
        const params = new URLSearchParams({
          company_id: companyId,
          limit: exportLimit.toString(),
          offset: offset.toString(),
          unread_only: unreadOnly.toString(),
        });

        if (showArchived) {
          params.append('archived_only', 'true');
        } else {
          params.append('show_archived', 'false');
        }

        if (tokens.text?.trim()) {
          params.append('search', tokens.text.trim());
        }

        if (tokens.status?.trim()) {
          params.append('funnel_stages', tokens.status.trim());
        }

        const response = await api.get<ContactsResponse>(`/webhook/contacts?${params}`);
        const pageContacts = response.data.contacts || [];
        allContacts = [...allContacts, ...pageContacts];
        hasMore = response.data.has_more && pageContacts.length === exportLimit;
        offset += exportLimit;

        if (offset > 10000) {
          console.warn('Limite de 10.000 contatos atingido para exportação');
          break;
        }
      }

      if (allContacts.length === 0) {
        setError('Nenhum contato encontrado para exportar');
        return;
      }

      const exportData = allContacts.map(contact => ({
        Nome: String(contact.name || 'Sem nome'),
        Telefone: String(contact.phone || ''),
        Status: String(contact.funnel_stage || 'contato'),
        'Mensagens não lidas': Number(contact.unread_count || 0),
        'Última mensagem': String(contact.last_message || '-').substring(0, 100),
        'Data última interação': contact.last_message_at
          ? new Date(contact.last_message_at).toLocaleString('pt-BR')
          : '-',
        'Modo humano': contact.human_mode ? 'Sim' : 'Não',
        'É Lead': contact.lead_id ? 'Sim' : 'Não',
        'É Cliente': contact.customer_id ? 'Sim' : 'Não',
      }));

      const now = new Date();
      const dateStr = now.toISOString().split('T')[0];
      downloadRowsAsCsv(exportData, `contatos_${dateStr}.csv`);
    } catch (err: any) {
      const errorMessage = typeof err === 'string'
        ? err
        : err.response?.data?.detail || err.message || 'Erro ao exportar contatos';
      setError(errorMessage);
      console.error('Erro ao exportar contatos:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleEditContact = (contact: Contact) => {
    setContactToConvert(contact);
    setEditName(contact.name || '');
    setTagDropdownOpen(false);
    setShowEditModal(true);
  };

  const confirmEditContact = async () => {
    if (!contactToConvert || !editName.trim()) return;

    try {
      setActionLoading(contactToConvert.id);
      await api.put(`/webhook/contacts/${contactToConvert.id}/edit`, {
        name: editName.trim(),
      });
      await fetchContacts();
      setShowEditModal(false);
      setContactToConvert(null);
      setEditName('');
    } catch (err: any) {
      const errorMessage = typeof err === 'string'
        ? err
        : err.response?.data?.detail || err.message || 'Erro ao editar contato';
      setError(errorMessage);
    } finally {
      setActionLoading(null);
    }
  };

  const handleDeleteContact = (contact: Contact) => {
    setContactToConvert(contact);
    setShowDeleteModal(true);
  };

  const confirmDeleteContact = async () => {
    if (!contactToConvert) return;

    try {
      setActionLoading(contactToConvert.id);
      await api.delete(`/webhook/contacts/${contactToConvert.id}/delete`);
      await fetchContacts();
      setShowDeleteModal(false);
      setContactToConvert(null);
    } catch (err: any) {
      const errorMessage = typeof err === 'string'
        ? err
        : err.response?.data?.detail || err.message || 'Erro ao excluir contato';
      setError(errorMessage);
    } finally {
      setActionLoading(null);
    }
  };

  const handleCopyPhone = async (phone: string) => {
    try {
      await navigator.clipboard.writeText(phone);
    } catch {
      const textArea = document.createElement('textarea');
      textArea.value = phone;
      document.body.appendChild(textArea);
      textArea.select();
      document.execCommand('copy');
      document.body.removeChild(textArea);
    }
  };

  const formatPhoneNumber = (value: string) => {
    const numbers = value.replace(/\D/g, '');
    if (!numbers) return '';

    const limitedNumbers = numbers.slice(0, 11);

    if (limitedNumbers.length <= 2) {
      return `(${limitedNumbers}`;
    }

    if (limitedNumbers.length <= 3) {
      return `(${limitedNumbers.slice(0, 2)}) ${limitedNumbers.slice(2)}`;
    }

    if (limitedNumbers.length <= 7) {
      return `(${limitedNumbers.slice(0, 2)}) ${limitedNumbers.slice(2)}`;
    }

    if (limitedNumbers.length <= 10) {
      return `(${limitedNumbers.slice(0, 2)}) ${limitedNumbers.slice(2, 6)}-${limitedNumbers.slice(6)}`;
    }

    return `(${limitedNumbers.slice(0, 2)}) ${limitedNumbers.slice(2, 7)}-${limitedNumbers.slice(7)}`;
  };

  const handlePhoneChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setNewContactPhone(formatPhoneNumber(event.target.value));
  };

  const handleCreateNewContact = async () => {
    if (!newContactName.trim() || !newContactPhone.trim()) {
      setError('Nome e telefone são obrigatórios');
      return;
    }

    try {
      setActionLoading(-1);

      const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
      if (!companyId) {
        setError('ID da empresa não encontrado');
        return;
      }

      const cleanPhone = newContactPhone.replace(/\D/g, '');

      await api.post('/webhook/contacts/create', {
        name: newContactName.trim(),
        phone: cleanPhone,
        company_id: parseInt(companyId),
      });

      await fetchContacts();
      setShowNewContactModal(false);
      setNewContactName('');
      setNewContactPhone('');
    } catch (err: any) {
      const errorMessage = typeof err === 'string'
        ? err
        : err.response?.data?.detail || err.message || 'Erro ao criar contato';
      setError(errorMessage);
    } finally {
      setActionLoading(null);
    }
  };

  const handleOpenChat = (contact: Contact) => {
    navigate('/chat', {
      state: {
        selectedPhone: contact.phone,
        selectedContact: {
          name: contact.name || 'Contato sem nome',
          phone: contact.phone,
          photo: contact.photo,
        },
      },
    });
  };

  const closeActionMenu = () => {
    setDropdownOpen(null);
    setDropdownPosition(null);
  };

  const toggleActionMenu = (contact: Contact, event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();

    if (dropdownOpen === contact.id) {
      closeActionMenu();
      return;
    }

    setDropdownPosition(getActionMenuPosition(event.currentTarget.getBoundingClientRect()));
    setDropdownOpen(contact.id);
  };

  const renderActionMenu = (contact: Contact) => {
    const isOpen = dropdownOpen === contact.id;
    const menu = isOpen && dropdownPosition && typeof document !== 'undefined' ? createPortal(
      <div
        className={agentivePanelClass(isDark, 'w-52 p-2 shadow-[0_22px_55px_rgba(2,3,35,0.18)]')}
        data-dropdown
        style={{
          left: dropdownPosition.left,
          position: 'fixed',
          top: dropdownPosition.top,
          zIndex: 10000,
        }}
      >
        {!contact.lead_id && (
          <button
            type="button"
            onClick={() => {
              closeActionMenu();
              handleConvertToLead(contact);
            }}
            className={cx('flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm transition-colors', isDark ? 'text-white/75 hover:bg-white/10' : 'text-brand/70 hover:bg-brand-canvas')}
            disabled={actionLoading === contact.id}
          >
            <UserPlus className="h-4 w-4" />
            Converter em lead
          </button>
        )}

        {!contact.customer_id && (
          <button
            type="button"
            onClick={() => {
              closeActionMenu();
              handleConvertToCustomer(contact);
            }}
            className={cx('flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm transition-colors', isDark ? 'text-white/75 hover:bg-white/10' : 'text-brand/70 hover:bg-brand-canvas')}
            disabled={actionLoading === contact.id}
          >
            <Users className="h-4 w-4" />
            Marcar cliente
          </button>
        )}

        {contact.lead_id && contact.customer_id && (
          <div className={cx('rounded-xl px-3 py-2 text-sm', isDark ? 'text-white/45' : 'text-brand/45')}>
            Lead e cliente vinculados
          </div>
        )}

        <div className={cx('my-2 h-px', isDark ? 'bg-white/10' : 'bg-brand/10')} />

        <button
          type="button"
          onClick={() => {
            closeActionMenu();
            handleEditContact(contact);
          }}
          className={cx('flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm transition-colors', isDark ? 'text-white/75 hover:bg-white/10' : 'text-brand/70 hover:bg-brand-canvas')}
        >
          <Edit2 className="h-4 w-4" />
          Editar contato
        </button>

        <button
          type="button"
          onClick={() => {
            closeActionMenu();
            handleDeleteContact(contact);
          }}
          className={cx('flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm transition-colors', isDark ? 'text-red-300 hover:bg-red-500/10' : 'text-red-700 hover:bg-red-50')}
        >
          <Trash2 className="h-4 w-4" />
          Excluir
        </button>
      </div>,
      document.body
    ) : null;

    return (
      <div className="relative" data-dropdown>
        <button
          type="button"
          className={agentiveIconButtonClass(isDark, 'neutral', 'min-h-9 min-w-9 p-2')}
          onClick={(event) => toggleActionMenu(contact, event)}
          aria-label="Abrir ações do contato"
        >
          <MoreVertical className="h-4 w-4" />
        </button>
        {menu}
      </div>
    );
  };

  const renderContactTags = (contact: Contact) => {
    if (!contact.tags?.length) return null;

    return (
      <div className="mt-2 flex flex-wrap gap-1.5">
        {contact.tags.slice(0, 3).map(tag => (
          <span
            key={tag.id}
            className="inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium"
            style={{ backgroundColor: `${tag.color}16`, borderColor: `${tag.color}35`, color: tag.color }}
          >
            {tag.name}
          </span>
        ))}
        {contact.tags.length > 3 && (
          <span className={agentivePillClass(isDark, false, 'px-2 py-0.5 text-[11px]')}>
            +{contact.tags.length - 3}
          </span>
        )}
      </div>
    );
  };

  return (
    <div className={cx(agentivePageClass(isDark), 'contacts-page', isDark && 'contacts-page--dark')}>
      <div className="contacts-shell">
        <section className="contacts-header">
          <div className="contacts-header__copy">
            <div className="contacts-header__eyebrow">
              <Users aria-hidden="true" />
              Relacionamento
            </div>
            <div className="contacts-header__title-row">
              <div>
                <h1>Contatos</h1>
                <p>Organize sua base, acompanhe conversas e avance relacionamentos.</p>
              </div>
              <span className="contacts-header__count">{total.toLocaleString('pt-BR')}</span>
            </div>
          </div>

          <div className="contacts-header__actions">
              <button type="button" onClick={() => setShowImport(!showImport)} className={agentiveSecondaryButtonClass(isDark, 'contacts-control')}>
                <Upload className="h-4 w-4" />
                <span className="hidden sm:inline">Importar</span>
              </button>
              <button type="button" onClick={handleExportContacts} disabled={loading} className={agentiveSecondaryButtonClass(isDark, 'contacts-control')}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                <span className="hidden sm:inline">{loading ? 'Exportando' : 'Exportar'}</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowNewContactModal(true);
                  setError(null);
                }}
                className={agentivePrimaryButtonClass('contacts-control contacts-control--primary')}
              >
                <UserPlus className="h-4 w-4" />
                Novo contato
              </button>
          </div>
        </section>

        {showImport && (
          <ContactsImport
            onImportComplete={handleImportComplete}
            onClose={() => setShowImport(false)}
          />
        )}

        <section className="contacts-metrics" aria-label="Resumo dos contatos">
          <MetricTile
            icon={Users}
            isDark={isDark}
            label="Total filtrado"
            value={total.toLocaleString('pt-BR')}
            helper={showArchived ? 'contatos arquivados' : 'contatos ativos'}
          />
          <MetricTile
            icon={Inbox}
            isDark={isDark}
            label="Não lidas"
            value={visibleUnreadCount}
            helper="na página atual"
          />
          <MetricTile
            icon={MessageSquare}
            isDark={isDark}
            label="Modo humano"
            value={visibleHumanCount}
            helper="conversas assumidas"
          />
          <MetricTile
            icon={Filter}
            isDark={isDark}
            label="Filtros"
            value={activeFilterCount}
            helper={activeFilterCount ? 'ativos agora' : 'sem filtros extras'}
          />
        </section>

        <section className="contacts-toolbar">
          <div className="contacts-toolbar__main">
            <div className="flex min-w-0 flex-col gap-2 md:flex-row md:items-center">
              <div className={cx('contacts-search', agentiveInputClass(isDark))}>
                <Search className={cx('h-4 w-4 shrink-0', isDark ? 'text-white/40' : 'text-brand/40')} />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-inherit"
                  placeholder="Buscar nome, telefone ou filtrar por status"
                />
                {query && (
                  <button
                    type="button"
                    onClick={() => setQuery('')}
                    className={agentiveIconButtonClass(isDark, 'neutral', 'min-h-7 min-w-7 p-1')}
                    aria-label="Limpar busca"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>

              <div className="relative shrink-0" ref={filterDropdownRef}>
                <button
                  type="button"
                  onClick={() => setShowFilters(!showFilters)}
                  className={agentiveSecondaryButtonClass(isDark, 'contacts-control contacts-filter-trigger')}
                >
                  <SlidersHorizontal className="h-4 w-4" />
                  Status
                  {activeStatusLabel && (
                    <span className={agentivePillClass(isDark, true, 'ml-1 max-w-28 px-2 py-0.5')}>
                      <span className="truncate">{activeStatusLabel}</span>
                    </span>
                  )}
                </button>

                {showFilters && (
                  <div className={cx(agentivePanelClass(isDark), 'contacts-filter-menu')}>
                    <div className={cx('px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]', isDark ? 'text-white/40' : 'text-brand/40')}>
                      Contato e etapas do CRM
                    </div>
                    <div className="mt-1 max-h-80 space-y-1 overflow-y-auto pr-1">
                      {statusFilterOptions.map(option => (
                        <button
                          key={option.value}
                          type="button"
                          onClick={() => applyStatusFilter(option.value)}
                          className={cx('flex w-full items-center justify-between gap-3 rounded-xl px-2.5 py-2 text-left text-sm transition-colors', isDark ? 'text-white/70 hover:bg-white/10' : 'text-brand/70 hover:bg-brand-canvas')}
                        >
                          <span className="min-w-0">
                            <span
                              className={cx(
                                'inline-flex max-w-full items-center rounded-full border px-2 py-0.5 text-xs font-semibold',
                                option.kind === 'contact'
                                  ? getContactStatusColors(isDark)
                                  : isDark
                                    ? 'border-white/10 bg-white/10 text-white/70'
                                    : 'border-brand/10 bg-brand-canvas text-brand/70'
                              )}
                              style={option.kind === 'crm-stage' ? getStageChipStyle(option.color) : undefined}
                            >
                              <span className="truncate">{option.label}</span>
                            </span>
                            {option.pipelineName && (
                              <span className={cx('mt-1 block truncate text-[11px]', isDark ? 'text-white/40' : 'text-brand/40')}>
                                {option.pipelineName}
                              </span>
                            )}
                          </span>
                          {tokens.status === option.value && <Check className="h-4 w-4" />}
                        </button>
                      ))}
                      {crmStageOptions.length === 0 && (
                        <div className={cx('rounded-xl px-2.5 py-2 text-xs', isDark ? 'text-white/45' : 'text-brand/45')}>
                          Nenhuma etapa do CRM carregada para esta empresa.
                        </div>
                      )}
                    </div>
                    {tokens.status && (
                      <>
                        <div className={cx('my-2 h-px', isDark ? 'bg-white/10' : 'bg-brand/10')} />
                        <button
                          type="button"
                          onClick={() => removeToken('status')}
                          className={cx('w-full rounded-xl px-2.5 py-2 text-left text-sm transition-colors', isDark ? 'text-white/55 hover:bg-white/10' : 'text-brand/55 hover:bg-brand-canvas')}
                        >
                          Limpar status
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 xl:justify-end">
              <div className="contacts-view-toggle">
                <button
                  type="button"
                  onClick={() => {
                    setShowArchived(false);
                    setCurrentPage(1);
                  }}
                  className={cx(
                    'contacts-view-toggle__item',
                    !showArchived
                      ? isDark ? 'bg-white text-brand shadow-flat' : 'bg-brand text-white shadow-flat'
                      : isDark ? 'text-white/55 hover:text-white' : 'text-brand/55 hover:text-brand'
                  )}
                >
                  Ativos
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowArchived(true);
                    setCurrentPage(1);
                  }}
                  className={cx(
                    'contacts-view-toggle__item',
                    showArchived
                      ? isDark ? 'bg-white text-brand shadow-flat' : 'bg-brand text-white shadow-flat'
                      : isDark ? 'text-white/55 hover:text-white' : 'text-brand/55 hover:text-brand'
                  )}
                >
                  Arquivados
                </button>
              </div>

              <button
                type="button"
                onClick={() => {
                  setUnreadOnly(!unreadOnly);
                  setCurrentPage(1);
                }}
                className={agentivePillClass(isDark, unreadOnly, 'contacts-control px-3')}
              >
                <Inbox className="h-3.5 w-3.5" />
                Não lidas
              </button>

              <button
                type="button"
                onClick={fetchContacts}
                className={agentiveIconButtonClass(isDark, 'neutral', 'contacts-refresh')}
                aria-label="Atualizar contatos"
              >
                <RefreshCw className={cx('h-4 w-4', loading && 'animate-spin')} />
              </button>
            </div>
          </div>

          {(tokens.status || tokens.tag || tokens.owner || activeFilterCount > 0) && (
            <div className="contacts-active-filters">
              {tokens.status && (
                <span className={agentivePillClass(isDark)}>
                  Status: {activeStatusLabel || tokens.status}
                  <button type="button" onClick={() => removeToken('status')} className={cx('ml-1 rounded p-0.5', isDark ? 'hover:bg-white/10' : 'hover:bg-brand/10')} aria-label="Remover filtro de status">
                    <X className="h-3 w-3" />
                  </button>
                </span>
              )}
              {tokens.tag && (
                <span className={agentivePillClass(isDark)}>
                  tag:{tokens.tag}
                  <button type="button" onClick={() => removeToken('tag')} className={cx('ml-1 rounded p-0.5', isDark ? 'hover:bg-white/10' : 'hover:bg-brand/10')} aria-label="Remover filtro de tag">
                    <X className="h-3 w-3" />
                  </button>
                </span>
              )}
              {tokens.owner && (
                <span className={agentivePillClass(isDark)}>
                  dono:{tokens.owner}
                  <button type="button" onClick={() => removeToken('owner')} className={cx('ml-1 rounded p-0.5', isDark ? 'hover:bg-white/10' : 'hover:bg-brand/10')} aria-label="Remover filtro de dono">
                    <X className="h-3 w-3" />
                  </button>
                </span>
              )}
              {unreadOnly && (
                <span className={agentivePillClass(isDark)}>
                  não lidas
                  <button type="button" onClick={() => setUnreadOnly(false)} className={cx('ml-1 rounded p-0.5', isDark ? 'hover:bg-white/10' : 'hover:bg-brand/10')} aria-label="Remover filtro de não lidas">
                    <X className="h-3 w-3" />
                  </button>
                </span>
              )}
              {showArchived && (
                <span className={agentivePillClass(isDark)}>
                  arquivados
                  <button type="button" onClick={() => setShowArchived(false)} className={cx('ml-1 rounded p-0.5', isDark ? 'hover:bg-white/10' : 'hover:bg-brand/10')} aria-label="Remover filtro de arquivados">
                    <X className="h-3 w-3" />
                  </button>
                </span>
              )}
              {activeFilterCount > 0 && (
                <button type="button" onClick={resetFilters} className={agentiveSecondaryButtonClass(isDark, 'px-2.5 py-1.5 text-xs')}>
                  Limpar filtros
                </button>
              )}
            </div>
          )}

          {selected.size > 0 && (
            <div className="contacts-selection-bar">
              <div>
                <strong className={isDark ? 'text-white' : 'text-brand'}>{selected.size}</strong> contato(s) selecionado(s)
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" onClick={handleExportContacts} className={agentiveSecondaryButtonClass(isDark, 'px-2.5 py-1.5 text-xs')}>
                  <Download className="h-3.5 w-3.5" />
                  Exportar filtro
                </button>
                <button type="button" onClick={() => setSelected(new Set())} className={agentiveSecondaryButtonClass(isDark, 'px-2.5 py-1.5 text-xs')}>
                  Limpar seleção
                </button>
              </div>
            </div>
          )}
        </section>

        <section className="contacts-results">
          {loading ? (
            <div className="contacts-state">
              <Loader2 className={cx('h-8 w-8 animate-spin', isDark ? 'text-white/60' : 'text-brand/60')} />
              <div>
                <p className="text-sm font-semibold">Carregando contatos</p>
                <p className={cx('mt-1 text-xs', mutedTextClass)}>Atualizando lista e filtros da empresa.</p>
              </div>
            </div>
          ) : error ? (
            <div className="contacts-state contacts-state--alert">
              <AgentiveAlert title="Não foi possível carregar contatos" variant="error">
                <div className="space-y-3">
                  <p>{typeof error === 'string' ? error : 'Erro ao carregar contatos'}</p>
                  <button type="button" onClick={fetchContacts} className="rounded-xl bg-brand px-3 py-2 text-sm font-semibold text-white transition-colors hover:bg-brand/90">
                    Tentar novamente
                  </button>
                </div>
              </AgentiveAlert>
            </div>
          ) : contacts.length === 0 ? (
            <div className="contacts-state contacts-state--empty">
              <AgentiveEmptyState
                icon={Users}
                title="Nenhum contato encontrado"
                description="Ajuste os filtros, importe uma planilha ou crie um contato manualmente para iniciar atendimento."
                action={(
                  <button
                    type="button"
                    onClick={() => setShowNewContactModal(true)}
                    className={agentivePrimaryButtonClass()}
                  >
                    <UserPlus className="h-4 w-4" />
                    Novo contato
                  </button>
                )}
              />
            </div>
          ) : (
            <>
              <div className="contacts-table-scroll">
                <table className="contacts-table">
                  <thead>
                    <tr>
                      <th className="w-10 px-4 py-3">
                        <input type="checkbox" checked={allVisibleSelected} onChange={toggleSelectAll} className="h-4 w-4 rounded border-brand/20 text-brand focus:ring-brand/20" />
                      </th>
                      <th className="min-w-[260px] px-3 py-3">Contato</th>
                      <th className="min-w-[320px] px-3 py-3">Última interação</th>
                      <th className="min-w-[150px] px-3 py-3">Status</th>
                      <th className="min-w-[150px] px-3 py-3">Tags</th>
                      <th className="w-24 px-3 py-3 text-center">Não lidas</th>
                      <th className="w-28 px-4 py-3 text-right">Ações</th>
                    </tr>
                  </thead>
                  <tbody className={cx('divide-y', isDark ? 'divide-white/10' : 'divide-brand/10')}>
                    {contacts.map(contact => {
                      const isSelected = contact.id ? selected.has(contact.id.toString()) : false;
                      const unread = contact.unread_count > 0;

                      return (
                        <tr
                          key={getContactKey(contact)}
                          className={cx('contacts-table__row', unread && 'contacts-table__row--unread', isSelected && 'contacts-table__row--selected')}
                        >
                          <td className={cx('px-4 align-top', rowPadding)}>
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={() => toggleContactSelection(contact)}
                              className="mt-3 h-4 w-4 rounded border-brand/20 text-brand focus:ring-brand/20"
                            />
                          </td>
                          <td className={cx('px-3 align-top', rowPadding)}>
                            <div className="flex min-w-0 items-start gap-3">
                              <ContactAvatar contact={contact} isDark={isDark} />
                              <div className="min-w-0 flex-1">
                                <div className="flex min-w-0 items-center gap-2">
                                  <p className={cx('truncate text-sm font-semibold', isDark ? 'text-white' : 'text-brand')}>
                                    {contact.name || 'Sem nome'}
                                  </p>
                                  {contact.human_mode && (
                                    <span className={agentivePillClass(isDark, false, 'px-2 py-0.5 text-[11px]')}>Humano</span>
                                  )}
                                </div>
                                <div className={cx('mt-1 flex items-center gap-2 text-xs', isDark ? 'text-white/50' : 'text-brand/50')}>
                                  <Phone className="h-3.5 w-3.5" />
                                  <span className="font-mono">{contact.phone}</span>
                                </div>
                                <div className="mt-2 flex items-center gap-1">
                                  <button type="button" onClick={() => handleCopyPhone(contact.phone)} className={agentiveIconButtonClass(isDark, 'neutral', 'min-h-7 min-w-7 p-1')} title="Copiar telefone">
                                    <Copy className="h-3.5 w-3.5" />
                                  </button>
                                  <button type="button" onClick={() => handleOpenChat(contact)} className={agentiveIconButtonClass(isDark, 'neutral', 'min-h-7 min-w-7 p-1')} title="Abrir chat">
                                    <MessageSquare className="h-3.5 w-3.5" />
                                  </button>
                                </div>
                              </div>
                            </div>
                          </td>
                          <td className={cx('px-3 align-top', rowPadding)}>
                            <p className={cx('line-clamp-2 max-w-xl text-sm', isDark ? 'text-white/75' : 'text-brand/75')}>
                              {formatLastMessage(contact.last_message)}
                            </p>
                            <p className={cx('mt-1 text-xs', isDark ? 'text-white/40' : 'text-brand/40')}>
                              {formatDate(contact.last_message_at)}
                            </p>
                          </td>
                          <td className={cx('px-3 align-top', rowPadding)}>
                            {contact.funnel_stage ? (
                              <StatusTag status={contact.funnel_stage} pipelines={pipelines} />
                            ) : (
                              <span className={agentivePillClass(isDark, false)}>Sem status</span>
                            )}
                          </td>
                          <td className={cx('px-3 align-top', rowPadding)}>
                            {contact.tags?.length ? (
                              <div className="flex max-w-[220px] flex-wrap gap-1.5">
                                {contact.tags.slice(0, 2).map(tag => (
                                  <span
                                    key={tag.id}
                                    className="inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium"
                                    style={{ backgroundColor: `${tag.color}16`, borderColor: `${tag.color}35`, color: tag.color }}
                                  >
                                    {tag.name}
                                  </span>
                                ))}
                                {contact.tags.length > 2 && (
                                  <span className={agentivePillClass(isDark, false, 'px-2 py-0.5 text-[11px]')}>+{contact.tags.length - 2}</span>
                                )}
                              </div>
                            ) : (
                              <span className={cx('text-xs', isDark ? 'text-white/35' : 'text-brand/35')}>Sem tags</span>
                            )}
                          </td>
                          <td className={cx('px-3 text-center align-top', rowPadding)}>
                            {unread ? (
                              <span className={cx('inline-flex min-w-7 justify-center rounded-full px-2 py-0.5 text-xs font-semibold', isDark ? 'bg-red-500/15 text-red-200' : 'bg-red-50 text-red-700')}>
                                {contact.unread_count}
                              </span>
                            ) : (
                              <span className={cx('text-xs', isDark ? 'text-white/35' : 'text-brand/35')}>0</span>
                            )}
                          </td>
                          <td className={cx('px-4 text-right align-top', rowPadding)}>
                            <div className="flex justify-end">{renderActionMenu(contact)}</div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="contacts-mobile-list">
                {contacts.map(contact => {
                  const isSelected = contact.id ? selected.has(contact.id.toString()) : false;
                  const unread = contact.unread_count > 0;

                  return (
                    <article key={getContactKey(contact)} className={cx('contacts-mobile-card', unread && 'contacts-mobile-card--unread', isSelected && 'contacts-mobile-card--selected')}>
                      <div className="flex items-start gap-3">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleContactSelection(contact)}
                          className="mt-3 h-4 w-4 rounded border-brand/20 text-brand focus:ring-brand/20"
                        />
                        <ContactAvatar contact={contact} isDark={isDark} size="sm" />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                              <p className={cx('truncate text-sm font-semibold', isDark ? 'text-white' : 'text-brand')}>{contact.name || 'Sem nome'}</p>
                              <p className={cx('mt-1 truncate font-mono text-xs', isDark ? 'text-white/50' : 'text-brand/50')}>{contact.phone}</p>
                            </div>
                            {unread && (
                              <span className={cx('shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold', isDark ? 'bg-red-500/15 text-red-200' : 'bg-red-50 text-red-700')}>
                                {contact.unread_count}
                              </span>
                            )}
                          </div>

                          <p className={cx('mt-3 line-clamp-2 text-sm', isDark ? 'text-white/70' : 'text-brand/70')}>
                            {formatLastMessage(contact.last_message)}
                          </p>
                          <p className={cx('mt-1 text-xs', isDark ? 'text-white/40' : 'text-brand/40')}>
                            {formatDate(contact.last_message_at)}
                          </p>

                          <div className="mt-3 flex flex-wrap items-center gap-2">
                            {contact.funnel_stage ? (
                              <StatusTag status={contact.funnel_stage} pipelines={pipelines} />
                            ) : (
                              <span className={agentivePillClass(isDark, false)}>Sem status</span>
                            )}
                            {contact.human_mode && <span className={agentivePillClass(isDark, false)}>Humano</span>}
                          </div>
                          {renderContactTags(contact)}

                          <div className="mt-3 flex items-center justify-between gap-2">
                            <div className="flex items-center gap-1">
                              <button type="button" onClick={() => handleCopyPhone(contact.phone)} className={agentiveIconButtonClass(isDark, 'neutral', 'min-h-9 min-w-9 p-2')} aria-label="Copiar telefone">
                                <Copy className="h-4 w-4" />
                              </button>
                              <button type="button" onClick={() => handleOpenChat(contact)} className={agentiveSecondaryButtonClass(isDark, 'min-h-9 px-3 py-2 text-xs')}>
                                <MessageSquare className="h-3.5 w-3.5" />
                                Chat
                              </button>
                            </div>
                            {renderActionMenu(contact)}
                          </div>
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            </>
          )}

          {!loading && !error && contacts.length > 0 && (
            <div className="contacts-pagination">
              <p className={cx('text-sm', mutedTextClass)}>
                Mostrando {contacts.length} de {total.toLocaleString('pt-BR')} contatos
              </p>
              {totalPages > 1 && (
                <div className="flex items-center gap-2">
                  <button type="button" onClick={() => setCurrentPage(currentPage - 1)} disabled={currentPage === 1} className={agentiveSecondaryButtonClass(isDark)}>
                    Anterior
                  </button>
                  <span className={cx('rounded-xl px-3 py-2 text-sm font-semibold', isDark ? 'bg-white/[0.04] text-white/65' : 'bg-brand-canvas text-brand/65')}>
                    {currentPage} de {totalPages}
                  </span>
                  <button type="button" onClick={() => setCurrentPage(currentPage + 1)} disabled={currentPage === totalPages} className={agentiveSecondaryButtonClass(isDark)}>
                    Próxima
                  </button>
                </div>
              )}
            </div>
          )}
        </section>
      </div>

      {showLeadModal && contactToConvert && (
        <ModalShell
          isDark={isDark}
          title="Converter em lead"
          description="Selecione a origem antes de mover este contato para o funil comercial."
          onClose={() => {
            setShowLeadModal(false);
            setContactToConvert(null);
          }}
        >
          <div className="space-y-4">
            <div className={cx('rounded-2xl border p-4', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas')}>
              <p className="font-semibold">{contactToConvert.name || 'Sem nome'}</p>
              <p className={cx('mt-1 font-mono text-xs', isDark ? 'text-white/45' : 'text-brand/45')}>{contactToConvert.phone}</p>
            </div>
            <div>
              <label className={agentiveLabelClass(isDark)}>Mídia de origem</label>
              <select value={selectedSource} onChange={(event) => setSelectedSource(event.target.value)} className={agentiveInputClass(isDark, 'p-3')}>
                <option value="">Selecione a origem</option>
                {mediaOptions.map(source => (
                  <option key={source.id} value={source.name}>{source.name}</option>
                ))}
              </select>
            </div>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={() => {
                  setShowLeadModal(false);
                  setContactToConvert(null);
                }}
                className={agentiveSecondaryButtonClass(isDark)}
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={confirmConvertToLead}
                disabled={actionLoading === contactToConvert.id}
                className={agentivePrimaryButtonClass()}
              >
                {actionLoading === contactToConvert.id ? 'Convertendo...' : 'Converter'}
              </button>
            </div>
          </div>
        </ModalShell>
      )}

      {showCustomerModal && contactToConvert && (
        <ModalShell
          isDark={isDark}
          title="Marcar como cliente"
          description="Confirme a mudanca de etapa para manter a base comercial atualizada."
          onClose={() => {
            setShowCustomerModal(false);
            setContactToConvert(null);
          }}
        >
          <div className="space-y-4">
            <div className={cx('rounded-2xl border p-4', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas')}>
              <div className="flex items-center gap-3">
                <span className={cx('grid h-10 w-10 place-items-center rounded-xl', isDark ? 'bg-white/10 text-white' : 'bg-white text-brand')}>
                  <Users className="h-5 w-5" />
                </span>
                <div className="min-w-0">
                  <p className="truncate font-semibold">{contactToConvert.name || 'Sem nome'}</p>
                  <p className={cx('mt-0.5 truncate font-mono text-xs', isDark ? 'text-white/45' : 'text-brand/45')}>{contactToConvert.phone}</p>
                </div>
              </div>
            </div>
            <p className={cx('text-sm leading-relaxed', isDark ? 'text-white/65' : 'text-brand/65')}>
              O contato será marcado como cliente e continuará disponível no histórico de atendimento.
            </p>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={() => {
                  setShowCustomerModal(false);
                  setContactToConvert(null);
                }}
                className={agentiveSecondaryButtonClass(isDark)}
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={confirmConvertToCustomer}
                disabled={actionLoading === contactToConvert.id}
                className={agentivePrimaryButtonClass()}
              >
                {actionLoading === contactToConvert.id ? 'Convertendo...' : 'Confirmar cliente'}
              </button>
            </div>
          </div>
        </ModalShell>
      )}

      {showEditModal && contactToConvert && (
        <ModalShell
          isDark={isDark}
          title="Editar contato"
          description="Atualize nome e tags sem alterar o histórico operacional."
          onClose={() => {
            setShowEditModal(false);
            setContactToConvert(null);
            setEditName('');
            setTagDropdownOpen(false);
          }}
        >
          <div className="space-y-4">
            <div>
              <label className={agentiveLabelClass(isDark)}>Nome do contato</label>
              <input
                type="text"
                value={editName}
                onChange={(event) => setEditName(event.target.value)}
                className={agentiveInputClass(isDark, 'p-3')}
                placeholder="Digite o nome do contato"
              />
              <p className={cx('mt-1 font-mono text-xs', isDark ? 'text-white/45' : 'text-brand/45')}>{contactToConvert.phone}</p>
            </div>

            <div>
              <label className={agentiveLabelClass(isDark)}>Tags</label>
              <div className="mb-2 flex flex-wrap gap-2">
                {contactToConvert.tags?.length ? (
                  contactToConvert.tags.map(tag => (
                    <span
                      key={tag.id}
                      className="inline-flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-medium"
                      style={{ backgroundColor: `${tag.color}16`, borderColor: `${tag.color}35`, color: tag.color }}
                    >
                      {tag.name}
                      <button
                        type="button"
                        onClick={async () => {
                          if (!contactToConvert) return;
                          try {
                            await removeTagFromContact(contactToConvert.id, tag.id);
                            const updatedTags = contactToConvert.tags?.filter(item => item.id !== tag.id) || [];
                            setContactToConvert({ ...contactToConvert, tags: updatedTags });
                            setContacts(prev => prev.map(contact => contact.id === contactToConvert.id ? { ...contact, tags: updatedTags } : contact));
                          } catch (removeError) {
                            console.error('Erro ao remover tag', removeError);
                          }
                        }}
                        className="rounded-full p-0.5 transition hover:bg-current/10"
                        aria-label={`Remover tag ${tag.name}`}
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  ))
                ) : (
                  <span className={cx('text-xs italic', isDark ? 'text-white/40' : 'text-brand/40')}>Sem tags</span>
                )}
              </div>

              <div className="relative">
                <button type="button" onClick={() => setTagDropdownOpen(!tagDropdownOpen)} className={agentiveSecondaryButtonClass(isDark, 'px-2.5 py-1.5 text-xs')}>
                  <Plus className="h-3.5 w-3.5" />
                  Adicionar tag
                </button>

                {tagDropdownOpen && (
                  <div className={agentivePanelClass(isDark, 'absolute left-0 top-full z-50 mt-2 max-h-56 w-56 overflow-y-auto p-1 shadow-[0_22px_55px_rgba(2,3,35,0.18)]')}>
                    {allTags.filter(tag => !contactToConvert.tags?.some(contactTag => contactTag.id === tag.id)).length > 0 ? (
                      allTags
                        .filter(tag => !contactToConvert.tags?.some(contactTag => contactTag.id === tag.id))
                        .map(tag => (
                          <button
                            key={tag.id}
                            type="button"
                            onClick={async () => {
                              if (!contactToConvert) return;
                              try {
                                const currentTagIds = contactToConvert.tags?.map(item => item.id) || [];
                                const newTagIds = [...currentTagIds, tag.id];
                                await updateContactTags(contactToConvert.id, newTagIds);

                                const updatedTags = [...(contactToConvert.tags || []), tag];
                                setContactToConvert({ ...contactToConvert, tags: updatedTags });
                                setContacts(prev => prev.map(contact => contact.id === contactToConvert.id ? { ...contact, tags: updatedTags } : contact));
                                setTagDropdownOpen(false);
                              } catch (addError) {
                                console.error('Erro ao adicionar tag', addError);
                              }
                            }}
                            className={cx('flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm transition-colors', isDark ? 'hover:bg-white/10' : 'hover:bg-brand-canvas')}
                          >
                            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: tag.color }} />
                            {tag.name}
                          </button>
                        ))
                    ) : (
                      <div className={cx('px-3 py-2 text-xs', isDark ? 'text-white/45' : 'text-brand/45')}>Nenhuma tag disponível</div>
                    )}
                  </div>
                )}
              </div>
            </div>

            <div className={cx('rounded-2xl border p-3 text-xs leading-relaxed', isDark ? 'border-white/10 bg-white/[0.04] text-white/65' : 'border-brand/10 bg-brand-canvas text-brand/65')}>
              O nome será atualizado nos registros relacionados, incluindo leads, clientes e agendamentos.
            </div>

            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={() => {
                  setShowEditModal(false);
                  setContactToConvert(null);
                  setEditName('');
                  setTagDropdownOpen(false);
                }}
                className={agentiveSecondaryButtonClass(isDark)}
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={confirmEditContact}
                disabled={actionLoading === contactToConvert.id || !editName.trim()}
                className={agentivePrimaryButtonClass()}
              >
                {actionLoading === contactToConvert.id ? 'Salvando...' : 'Salvar contato'}
              </button>
            </div>
          </div>
        </ModalShell>
      )}

      <ConfirmDeleteModal
        isOpen={showDeleteModal && Boolean(contactToConvert)}
        onClose={() => {
          setShowDeleteModal(false);
          setContactToConvert(null);
        }}
        onConfirm={confirmDeleteContact}
        isLoading={actionLoading === contactToConvert?.id}
        title="Excluir contato?"
        message="Esta ação remove o contato e dados operacionais vinculados de forma permanente."
        confirmText="Excluir contato"
      >
        <div className={isDark ? 'text-white/75' : 'text-brand/70'}>
          <p className="font-medium">{contactToConvert?.name}</p>
          <p className="mt-0.5 text-xs opacity-75">{contactToConvert?.phone}</p>
          <ul className="mt-3 list-inside list-disc space-y-1 text-xs">
            <li>Histórico de mensagens</li>
            <li>Dados de lead ou cliente vinculados</li>
            <li>Agendamentos, comparecimentos, vendas e no-show</li>
          </ul>
        </div>
      </ConfirmDeleteModal>

      {showNewContactModal && (
        <ModalShell
          isDark={isDark}
          title="Novo contato"
          description="Crie um registro manual para iniciar atendimento ou vincular ao funil."
          onClose={() => {
            setShowNewContactModal(false);
            setNewContactName('');
            setNewContactPhone('');
            setError(null);
          }}
        >
          <div className="space-y-4">
            <div>
              <label className={agentiveLabelClass(isDark)}>Nome do contato</label>
              <input
                type="text"
                value={newContactName}
                onChange={(event) => setNewContactName(event.target.value)}
                className={agentiveInputClass(isDark, 'p-3')}
                placeholder="Digite o nome do contato"
              />
            </div>
            <div>
              <label className={agentiveLabelClass(isDark)}>Telefone</label>
              <input
                type="tel"
                value={newContactPhone}
                onChange={handlePhoneChange}
                className={agentiveInputClass(isDark, 'p-3')}
                placeholder="Ex: (11) 99999-9999"
                maxLength={15}
              />
            </div>

            {error ? (
              <AgentiveAlert title="Não foi possível criar o contato" variant="error">
                <p>{error}</p>
              </AgentiveAlert>
            ) : (
              <div className={cx('rounded-2xl border p-3 text-xs leading-relaxed', isDark ? 'border-white/10 bg-white/[0.04] text-white/65' : 'border-brand/10 bg-brand-canvas text-brand/65')}>
                O contato ficará disponível no chat e poderá ser convertido em lead ou cliente depois.
              </div>
            )}

            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={() => {
                  setShowNewContactModal(false);
                  setNewContactName('');
                  setNewContactPhone('');
                  setError(null);
                }}
                className={agentiveSecondaryButtonClass(isDark)}
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={handleCreateNewContact}
                disabled={actionLoading === -1 || !newContactName.trim() || !newContactPhone.trim()}
                className={agentivePrimaryButtonClass()}
              >
                {actionLoading === -1 ? 'Criando...' : 'Criar contato'}
              </button>
            </div>
          </div>
        </ModalShell>
      )}
    </div>
  );
};

export default ContactsList;
