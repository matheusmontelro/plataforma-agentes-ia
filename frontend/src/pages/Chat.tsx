// ChatPage5.tsx - Versão otimizada e atualizada
import React, { useEffect, useState, useRef, useMemo } from 'react';
import { useLocation } from 'react-router-dom';
import {
  Search, Send, MoreVertical, Mic,
  ImageIcon, Video as VideoIcon,
  File as FileIcon,
  User as UserIcon,
  Cpu as CpuIcon,
  Target,
  PlusCircle,
  Calendar,
  CheckCircle2,
  XCircle,
  DollarSign,
  Settings2,
  ToggleLeft,
  ToggleRight,
  MessageSquare,
  HeartHandshake,
  ShoppingBag,
  Activity,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock,
  Check,
  CheckCheck,
  Loader2,
  AlertCircle,
  Headphones,
  PanelRightOpen,
  UserPlus,
  X,
} from 'lucide-react';
import { useIsMobile } from '../hooks/useIsMobile.ts';
import ChatMobile from './ChatMobile.tsx';
import api, {
  getContacts,
  getContactsNoHistory,
  markContactAsRead,
  takeOverContact,
  releaseContactToBot,
  sendWhatsAppText,
  sendWhatsAppReaction,
  sendWhatsAppAudio,
  sendWhatsAppAudioDirect,
  sendWhatsAppImage,
  sendWhatsAppVideo,
  SendImageParams,
  SendAudioParams,
  SendVideoParams,
  getCompanyInfo,
  unifiedWebSocketManager,
  OptimizedMessage,
  type MessageDeliveryStatus,
  MessageReplyPreview,
  getChatWebSocketUrl,
  getPipelines,
  PipelineResponse,
  PipelineStage
} from '../services/api';
import StatusTag from '../components/StatusTag.tsx';
import { formatChatTimestamp } from '../utils/date.ts';
import { getContactLastMessagePreview, normalizeContactLastMessage } from '../utils/contactLastMessagePreview.ts';
import { getContactInitials, resolveContactProfilePhoto } from '../utils/contactAvatar.ts';
import AudioRecorder from '../components/AudioRecorder.tsx';
import { ConnectionStatusIndicator } from '../components/ConnectionStatusIndicator.tsx';
import { VirtualizedMessageList } from '../components/VirtualizedMessageList.tsx';
import { OptimizedMessageContent } from '../components/OptimizedMessageContent.tsx';
import { OptimizedMessageInput } from '../components/OptimizedMessageInput.tsx';
import { useOptimizedMessages } from '../hooks/useOptimizedMessages.tsx';
import { DateSeparator } from '../components/DateSeparator.tsx';
import { groupMessagesByDay, MessageGroup } from '../utils/messageGrouping.ts';
import AudioWaveform from '../components/AudioWaveform.tsx';
import { ContactFilters } from '../components/ContactFilters.tsx';
import { archiveContact, unarchiveContact } from '../services/api.ts';
import { Archive, ArchiveRestore, StickyNote } from 'lucide-react';
import LeadProfile, { type LeadProfileTab } from '../components/LeadProfile.tsx';
import { crmApi, Lead as CrmLead } from '../services/crmApi.ts';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AgentiveAlert,
  AgentiveEmptyState,
  agentiveIconButtonClass,
  agentiveInputClass,
  agentivePanelClass,
  agentivePillClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';
import ChatContactProfile from '../components/chat/ChatContactProfile.tsx';
import ChatProfileActions from '../components/chat/ChatProfileActions.tsx';

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

type ChatAvatarContact = {
  name?: string | null;
  phone?: string | null;
  photo?: string | null;
};

const ContactAvatar: React.FC<{
  contact?: ChatAvatarContact | null;
  isDark: boolean;
  sizeClassName?: string;
}> = ({ contact, isDark, sizeClassName = 'h-11 w-11' }) => {
  const avatarUrl = resolveContactProfilePhoto(contact);
  const [imageFailed, setImageFailed] = useState(false);

  useEffect(() => {
    setImageFailed(false);
  }, [avatarUrl]);

  const label = contact?.name || contact?.phone || 'Contato';
  const canShowImage = Boolean(avatarUrl && !imageFailed);

  return (
    <div className={cx('flex flex-shrink-0 items-center justify-center overflow-hidden rounded-xl', sizeClassName, isDark ? 'bg-white/10 text-white' : 'bg-brand/10 text-brand')}>
      {canShowImage ? (
        <img
          src={avatarUrl}
          alt={label}
          className="h-full w-full object-cover"
          onError={() => setImageFailed(true)}
        />
      ) : (
        <span className="text-sm font-semibold">
          {getContactInitials(label)}
        </span>
      )}
    </div>
  );
};

const renderContactLastMessagePreview = (lastMessage?: string) => {
  const preview = getContactLastMessagePreview(lastMessage);
  if (!preview.label) return null;

  if (preview.type === 'audio') {
    return (
      <>
        <Mic className="mr-1 h-3 w-3 flex-shrink-0" />
        <span className="truncate">{preview.label}</span>
      </>
    );
  }

  if (preview.type === 'video') {
    return (
      <>
        <VideoIcon className="mr-1 h-3 w-3 flex-shrink-0" />
        <span className="truncate">{preview.label}</span>
      </>
    );
  }

  if (preview.type === 'image') {
    return (
      <>
        <ImageIcon className="mr-1 h-3 w-3 flex-shrink-0" />
        <span className="truncate">{preview.label}</span>
      </>
    );
  }

  return <span className="truncate">{preview.label}</span>;
};

const getContactLastMessageStatusMeta = (status?: MessageDeliveryStatus) => {
  const resolvedStatus = status || 'sent';

  if (resolvedStatus === 'sending') return { label: 'Enviando', Icon: Clock, tone: 'muted' as const };
  if (resolvedStatus === 'failed') return { label: 'Falhou', Icon: XCircle, tone: 'danger' as const };
  if (resolvedStatus === 'sent') return { label: 'Enviado', Icon: Check, tone: 'muted' as const };
  if (resolvedStatus === 'delivered') return { label: 'Entregue', Icon: CheckCheck, tone: 'muted' as const };
  if (resolvedStatus === 'played') return { label: 'Reproduzido', Icon: CheckCheck, tone: 'read' as const };
  return { label: 'Lido', Icon: CheckCheck, tone: 'read' as const };
};

// Interfaces de dados existentes
interface FlowProgress {
  current_step: number;
  total_steps: number;
  status: 'SCHEDULED' | 'PROCESSING' | 'SUCCESS' | 'FAILED' | 'CANCELED';
  next_scheduled?: string;
}

interface Contact {
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



  source_id?: string;
  thumbnail_url?: string;
  sender_lid?: string;
  lead_id?: number;
  customer_id?: number;
  // Novos campos do funil
  funnel_stage?: string;
  funnel_status?: {
    lead_id?: number;
    agendamento_id?: number;
    comparecimento_id?: number;
    venda_id?: number;
    no_show_id?: number;
  };
  // Campos de tarefas
  pending_tasks_count?: number;
  next_task?: {
    id: number;
    title: string;
    scheduled_for: string;
    priority: 'low' | 'medium' | 'high' | 'urgent';
    task_type: 'message' | 'call' | 'email' | 'custom';
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

const ChatPage5: React.FC = () => {
  // Hook para detectar se é mobile - DEVE vir antes de qualquer condicional
  const isMobile = useIsMobile(768);
  const location = useLocation();
  const { isDark } = useTheme();

  // Estados - TODOS os hooks devem ser declarados antes de qualquer return condicional
  const [contacts, setContacts] = useState<Map<string, Contact>>(new Map());
  const [selectedContact, setSelectedContact] = useState<Contact | null>(null);
  const [hasMoreContacts, setHasMoreContacts] = useState(true);
  const [isLoadingMoreContacts, setIsLoadingMoreContacts] = useState(false);
  const [currentOffset, setCurrentOffset] = useState(0);
  const [isThrottled, setIsThrottled] = useState(false);
  const [newMessage, setNewMessage] = useState('');
  const [replyingTo, setReplyingTo] = useState<OptimizedMessage | null>(null);
  const [companyInfo, setCompanyInfo] = useState<{ name: string; logo_url: string | null }>({
    name: 'Empresa',
    logo_url: null
  });
  const [skipHistory, setSkipHistory] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [showNewChatModal, setShowNewChatModal] = useState(false);
  const [modalSearchTerm, setModalSearchTerm] = useState('');
  const [isRecording, setIsRecording] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [isContactsLoading, setIsContactsLoading] = useState(true);
  const [showUnreadOnly, setShowUnreadOnly] = useState<boolean>(false);
  // Estado para controlar a navegação mobile (lista ou chat)
  const [showMobileChat, setShowMobileChat] = useState(false);
  const [showFlowTimeline, setShowFlowTimeline] = useState(false);
  const [showContactProfile, setShowContactProfile] = useState(false);
  const [profileActiveTab, setProfileActiveTab] = useState<LeadProfileTab>('overview');
  const [profileLead, setProfileLead] = useState<CrmLead | null>(null);
  const [isProfileLeadLoading, setIsProfileLeadLoading] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);

  const renderContactLastMessageStatus = (contact: Contact) => {
    if (!contact.lastMessageFromMe) return null;

    const { label, Icon, tone } = getContactLastMessageStatusMeta(contact.lastMessageStatus);
    const toneClass = tone === 'read'
      ? (isDark ? 'text-sky-300' : 'text-sky-600')
      : tone === 'danger'
        ? (isDark ? 'text-red-300' : 'text-red-600')
        : isDark
          ? 'text-white/40'
          : 'text-brand/40';

    return (
      <span
        className={cx('mr-1 inline-flex h-3.5 w-3.5 flex-shrink-0 items-center justify-center', toneClass)}
        title={`Status da última mensagem: ${label}`}
        aria-label={`Status da última mensagem: ${label}`}
      >
        <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      </span>
    );
  };

  const updateContactLastOwnMessagePreview = (
    phone: string,
    lastMessage: string,
    status: MessageDeliveryStatus = 'sending'
  ) => {
    setContacts((prev) => {
      const newContacts = new Map(prev);
      const existing = newContacts.get(phone);
      if (!existing) return newContacts;

      newContacts.set(phone, {
        ...existing,
        lastMessage,
        lastMessageFromMe: true,
        lastMessageStatus: status,
        timestamp: new Date().toLocaleTimeString(),
        timestampNumber: Date.now(),
      });

      return newContacts;
    });
  };
  const [isConvertingLead, setIsConvertingLead] = useState(false);

  // Detectar se usuário é da equipe SUPORTE
  const [isSupportTeam, setIsSupportTeam] = useState(false);



  // Estados para filtros e arquivamento
  const [contactFilters, setContactFilters] = useState<ContactFilters>({
    funnelStages: [],
    activeFlows: []
  });
  const [showArchivedSection, setShowArchivedSection] = useState(false);
  const [isArchiving, setIsArchiving] = useState(false);

  // Estado para Pipelines
  const [pipelines, setPipelines] = useState<PipelineResponse[]>([]);

  // Carregar pipelines ao montar
  useEffect(() => {
    async function loadPipelines() {
      try {
        const companyId = parseInt((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')) || '0');
        if (companyId) {
          const data = await getPipelines(companyId);
          setPipelines(data);
        }
      } catch (error) {
        console.error('Erro ao carregar pipelines:', error);
      }
    }
    loadPipelines();
  }, []);

  // Ref para rastrear mensagens já processadas e evitar duplicação
  const processedWebSocketMessages = useRef<Set<string>>(new Set());
  const getTotalUnreadCount = (): number => {
    let total = 0;
    contacts.forEach((contact) => {
      total += contact.unreadCount || 0;
    });
    return total;
  };



  // Hook otimizado para gerenciar mensagens com cache e paginação
  const {
    messages,
    isLoading,
    hasMore,
    loadMoreMessages,
    sendMessage
  } = useOptimizedMessages(
    selectedContact?.phone || null,
    { pageSize: 50 }
  );

  useEffect(() => {
    setReplyingTo(null);
  }, [selectedContact?.phone]);

  const resolveContactLeadId = (contact?: Contact | null) => {
    if (!contact) return undefined;
    return contact.lead_id || contact.funnel_status?.lead_id;
  };

  const buildReplyPreview = (message: OptimizedMessage): MessageReplyPreview => {
    const content = message.content;
    let body = '';

    if (typeof content === 'string') {
      body = content;
    } else if (content?.caption) {
      body = content.caption;
    } else if (message.type === 'image') {
      body = 'Imagem';
    } else if (message.type === 'video') {
      body = 'Vídeo';
    } else if (message.type === 'audio') {
      body = 'Áudio';
    } else {
      body = 'Mensagem';
    }

    return {
      id: message.id,
      providerMessageId: message.providerMessageId,
      type: message.type,
      body,
      senderName: message.fromMe ? 'Você' : message.sender.name,
    };
  };

  const handleReactToMessage = async (message: OptimizedMessage, reaction: string) => {
    if (!selectedContact) return;
    const messageId = message.providerMessageId || message.id;
    try {
      await sendWhatsAppReaction({
        phone: selectedContact.phone,
        messageId,
        reaction,
      });
    } catch (error) {
      console.error('[handleReactToMessage] -> Erro ao reagir:', error);
    }
  };

  const mapLeadToProfile = (lead: CrmLead, contact: Contact) => ({
    id: lead.id,
    name: lead.name || contact.name || contact.phone,
    phone: lead.phone || contact.phone,
    thumbnailUrl: resolveContactProfilePhoto(contact) || undefined,
    columnId: lead.current_stage_id ? String(lead.current_stage_id) : (contact.funnel_stage || 'lead'),
    date: lead.created_at || lead.data_entrada || new Date().toISOString(),
    sourceId: lead.source_id || contact.source_id,
    custom_values: lead.custom_values || [],
  });

  const loadLeadForContact = async (contact: Contact, overrideLeadId?: number) => {
    const leadId = overrideLeadId || resolveContactLeadId(contact);

    if (!leadId) {
      setProfileLead(null);
      setIsProfileLeadLoading(false);
      return;
    }

    setIsProfileLeadLoading(true);
    setProfileError(null);

    try {
      const lead = await crmApi.getLead(leadId);
      setProfileLead(lead);
    } catch (error) {
      console.error('Erro ao carregar lead do contato:', error);
      setProfileLead(null);
      setProfileError('Nao foi possivel carregar o lead vinculado a esta conversa.');
    } finally {
      setIsProfileLeadLoading(false);
    }
  };

  const handleOpenContactProfile = () => {
    if (!selectedContact) return;
    setProfileActiveTab('overview');
    setShowContactProfile(true);
    loadLeadForContact(selectedContact);
  };

  const handleCloseContactProfile = () => {
    setShowContactProfile(false);
    setProfileActiveTab('overview');
  };

  const openProfileTab = (tab: LeadProfileTab) => {
    if (!selectedContact) return;
    setProfileActiveTab(tab);
    setShowContactProfile(true);
    loadLeadForContact(selectedContact);
  };

  const updatePendingTasksCount = (pendingCount: number) => {
    if (!selectedContact) return;

    const phone = selectedContact.phone;
    setSelectedContact(prev => prev && prev.phone === phone ? { ...prev, pending_tasks_count: pendingCount } : prev);
    setContacts(prev => {
      const next = new Map(prev);
      const current = next.get(phone);
      if (current) {
        next.set(phone, { ...current, pending_tasks_count: pendingCount });
      }
      return next;
    });
  };

  const handleConvertSelectedContactToLead = async () => {
    if (!selectedContact) return;

    if (!selectedContact.id) {
      setProfileError('Este contato ainda nao retornou um ID valido para conversao.');
      return;
    }

    setIsConvertingLead(true);
    setProfileError(null);

    try {
      const response = await api.post(`/webhook/contacts/${selectedContact.id}/convert-to-lead`, {
        source_id: selectedContact.source_id || 'Chat',
      });
      const leadId = response.data?.lead_id;
      const updatedContact: Contact = {
        ...selectedContact,
        lead_id: leadId,
        funnel_stage: selectedContact.funnel_stage || 'lead',
        thumbnail_url: selectedContact.thumbnail_url || selectedContact.photo,
      };

      setSelectedContact(updatedContact);
      setContacts(prev => {
        const newMap = new Map(prev);
        const existing = newMap.get(updatedContact.phone);
        newMap.set(updatedContact.phone, { ...existing, ...updatedContact });
        return newMap;
      });

      if (leadId) {
        await loadLeadForContact(updatedContact, leadId);
      }
    } catch (error: any) {
      console.error('Erro ao converter contato em lead pelo chat:', error);
      setProfileError(error?.response?.data?.detail || 'Erro ao converter contato em lead.');
    } finally {
      setIsConvertingLead(false);
    }
  };

  useEffect(() => {
    if (!selectedContact) {
      setShowContactProfile(false);
      setProfileLead(null);
      setProfileError(null);
      return;
    }

    if (showContactProfile) {
      loadLeadForContact(selectedContact);
    }
  }, [showContactProfile, selectedContact?.phone, selectedContact?.lead_id, selectedContact?.funnel_status?.lead_id]);

  // Estados para modal de contatos sem histórico
  const [modalContacts, setModalContacts] = useState<Contact[]>([]);
  const [isLoadingModalContacts, setIsLoadingModalContacts] = useState(false);
  const [modalOffset, setModalOffset] = useState(0);
  const [hasMoreModalContacts, setHasMoreModalContacts] = useState(true);

  // Função para carregar contatos sem histórico no modal
  const loadModalContacts = async (offset = 0, limit = 20, append = false, search = '') => {
    console.log('📥 loadModalContacts chamada:', {
      offset,
      limit,
      append,
      search,
      modalSearchTerm
    });

    setIsLoadingModalContacts(true);

    try {
      // Use o parâmetro search se fornecido, senão use o estado atual
      const searchTerm = search !== undefined ? search : modalSearchTerm;

      const response = await getContactsNoHistory({
        limit,
        offset,
        search: searchTerm
      });

      // Processar lastMessage dos contatos do modal também
      const processedContacts = response.contacts.map(c => {
        return {
          ...c,
          photo: resolveContactProfilePhoto(c),
          lastMessage: normalizeContactLastMessage(c.lastMessage)
        };
      });

      console.log('📋 Resposta da API de contatos sem histórico:', {
        contactsCount: processedContacts.length,
        total: response.total,
        hasMore: response.has_more,
        searchUsed: searchTerm
      });

      if (append) {
        setModalContacts(prev => [...prev, ...processedContacts]);
      } else {
        setModalContacts(processedContacts);
      }

      setHasMoreModalContacts(response.has_more);
      setModalOffset(append ? offset + response.contacts.length : response.contacts.length);

      console.log('✅ Contatos do modal atualizados:', {
        total: response.contacts.length,
        hasMore: response.has_more,
        currentOffset: append ? offset + response.contacts.length : response.contacts.length,
        append
      });
    } catch (error) {
      console.error('❌ Erro ao carregar contatos do modal:', error);
    } finally {
      setIsLoadingModalContacts(false);
    }
  };

  // Carregar contatos do modal quando o modal abrir (executa UMA vez)
  useEffect(() => {
    if (showNewChatModal) {
      console.log('🔥 Abrindo modal - carregando contatos iniciais');
      // Reset estados do modal
      setModalContacts([]);
      setModalOffset(0);
      setModalSearchTerm('');
      setHasMoreModalContacts(true);
      // Carregar contatos iniciais sem busca
      setTimeout(() => {
        loadModalContacts(0, 20, false, '');
      }, 100); // Pequeno delay para garantir que os estados foram atualizados
    }
  }, [showNewChatModal]);

  // Recarregar contatos do modal quando o termo de busca mudar (com debounce)
  useEffect(() => {
    // Só executa se o modal estiver aberto E se não for o primeiro carregamento (modalSearchTerm não é vazio)
    if (showNewChatModal && modalSearchTerm !== '') {
      console.log('🔍 Termo de busca mudou no modal:', modalSearchTerm);
      const timeoutId = setTimeout(() => {
        setModalOffset(0);
        setHasMoreModalContacts(true);
        loadModalContacts(0, 20, false, modalSearchTerm);
      }, 300); // Debounce de 300ms

      return () => clearTimeout(timeoutId);
    } else if (showNewChatModal && modalSearchTerm === '' && modalContacts.length > 0) {
      // Se o campo de busca foi limpo, recarregar todos os contatos
      console.log('🔍 Campo de busca limpo - recarregando todos os contatos');
      setModalOffset(0);
      setHasMoreModalContacts(true);
      loadModalContacts(0, 20, false, '');
    }
  }, [modalSearchTerm]);

  const contactsRef = useRef<Map<string, Contact>>(new Map());
  const selectedContactRef = useRef<Contact | null>(null);

  // Função para arquivar/desarquivar contato
  const handleArchiveToggle = async (contact: Contact, isArchived: boolean) => {
    if (!contact || isArchiving) return;

    const companyId = parseInt((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')) || '0');
    if (!companyId) {
      console.error('Company ID não encontrado');
      return;
    }

    setIsArchiving(true);
    console.log(`🗂️ CHECKPOINT: ${isArchived ? 'Desarquivando' : 'Arquivando'} contato ${contact.phone}`);

    try {
      if (isArchived) {
        await unarchiveContact(contact.phone, companyId);
      } else {
        await archiveContact(contact.phone, companyId, 'Arquivado via chat');
      }

      // Recarregar contatos para refletir mudanças
      console.log('✅ CHECKPOINT: Operação concluída, recarregando contatos...');
      await loadContacts(0, 50, false);

      // Se o contato arquivado era o selecionado, desselecionar
      if (!isArchived && selectedContact?.phone === contact.phone) {
        setSelectedContact(null);
      }
    } catch (error) {
      console.error('❌ Erro ao alterar status de arquivo:', error);
      setProfileError('Erro ao ' + (isArchived ? 'desarquivar' : 'arquivar') + ' contato.');
    } finally {
      setIsArchiving(false);
    }
  };

  useEffect(() => {
    contactsRef.current = contacts;
  }, [contacts]);

  useEffect(() => {
    selectedContactRef.current = selectedContact;
  }, [selectedContact]);

  // Detectar equipe SUPORTE e aplicar filtro automático
  useEffect(() => {
    // Verificar se o usuário é da equipe SUPORTE
    const userStr = localStorage.getItem('user');
    if (userStr) {
      try {
        const user = JSON.parse(userStr);
        if (user.team?.code === 'SUPORTE') {
          setIsSupportTeam(true);
          // Aplicar filtro automático para mostrar apenas clientes
          setContactFilters({
            funnelStages: ['cliente'],
            activeFlows: []
          });
        }
      } catch (error) {
        console.error('Erro ao verificar equipe do usuário:', error);
      }
    }
  }, []);

  // Carrega informações da empresa
  useEffect(() => {
    async function loadCompanyInfo() {
      try {
        const info = await getCompanyInfo();
        setCompanyInfo({
          name: info.name_company || 'Empresa',
          logo_url: info.logo_url
        });
      } catch (error) {
        console.error('Erro ao carregar informações da empresa:', error);
      }
    }

    loadCompanyInfo();
  }, []);


  // Carrega contatos
  // Carrega contatos com paginação
  const loadContacts = async (offset = 0, limit = 50, append = false) => {
    if (offset === 0) {
      setIsContactsLoading(true);
      setCurrentOffset(0);
    }
    if (offset > 0) setIsLoadingMoreContacts(true);

    console.log('🔍 CHECKPOINT: Carregando contatos com filtros:', {
      ...contactFilters,
      search: searchTerm,
      unread_only: showUnreadOnly,
      offset,
      limit
    });

    try {
      // Preparar parâmetros com lógica correta para arquivados
      const params: any = {
        limit,
        offset,

        search: searchTerm,
        unread_only: showUnreadOnly,
        funnel_stages: contactFilters.funnelStages,
        active_flows: contactFilters.activeFlows,
        history_only: true // Mostrar apenas contatos com histórico
      };

      // Lógica correta para arquivados (igual ao ContactsList)
      if (showArchivedSection) {
        params.archived_only = true;
      } else {
        params.show_archived = false;
      }

      const response = await getContacts(params);

      const cMap = append ? new Map(contacts) : new Map<string, Contact>();

      // IMPORTANTE: Normalizar os telefones ao criar o Map inicial
      response.contacts.forEach((c) => {
        const normalizedPhone = normalizePhone(c.phone);

        const processedLastMessage = normalizeContactLastMessage(c.lastMessage);

        // Debug: verificar primeiro contato com flow_progress
        if (c.flow_progress && !(window as any)._flowDebugShown) {
          console.log('📱 Primeiro contato com flow_progress:', c);
          (window as any)._flowDebugShown = true;
        }

        const contactToSave = {
          ...c,
          phone: normalizedPhone,    // Mantém o telefone normalizado
          photo: resolveContactProfilePhoto(c),
          lastMessage: processedLastMessage, // Usa o lastMessage processado
          unreadCount: c.unreadCount ?? 0
        };

        cMap.set(normalizedPhone, contactToSave);
      });

      setContacts(cMap);
      setHasMoreContacts(response.has_more);

      // Atualizar offset apenas se for append
      if (append) {
        setCurrentOffset(offset + response.contacts.length);
      } else {
        setCurrentOffset(response.contacts.length);
      }

      // Imprimir as chaves do Map para debug
      console.log('Contatos carregados:', {
        total: cMap.size,
        hasMore: response.has_more,
        currentOffset: append ? offset + response.contacts.length : response.contacts.length,
        responseCount: response.contacts.length,
        append
      });
    } catch (error) {
      console.error('Erro ao carregar contatos:', error);
    } finally {
      setIsContactsLoading(false);
      setIsLoadingMoreContacts(false);
    }
  };

  useEffect(() => {
    loadContacts();
  }, []);

  // Lidar com navegação via state (quando vier de notificações)
  useEffect(() => {
    if (location.state?.selectedPhone && contacts.size > 0) {
      const rawPhone = location.state.selectedPhone;
      const contactInfo = location.state.selectedContact;

      // Normalizar o telefone para garantir consistência
      const normalizedPhone = normalizePhone(rawPhone);

      // Procurar o contato na lista existente
      const existingContact = contacts.get(normalizedPhone);

      if (existingContact) {
        // Se o contato já existe, selecioná-lo
        setSelectedContact(existingContact);
        console.log('[TaskNotification] Contato encontrado e selecionado:', normalizedPhone);
      } else {
        // Se não existe, criar um contato temporário e selecioná-lo
        const tempContact: Contact = {
          phone: normalizedPhone,
          name: contactInfo?.name || normalizedPhone,
          photo: '',
          timestampNumber: Date.now(),
          unreadCount: 0,
          human_mode: false
        };
        setSelectedContact(tempContact);
        console.log('[TaskNotification] Contato temporário criado:', normalizedPhone);

        // Recarregar a lista de contatos para incluir este contato
        loadContacts(0, 50, false);
      }

      // Limpar o state para evitar reprocessamento
      window.history.replaceState({}, document.title);
    }
  }, [location.state?.selectedPhone, contacts.size]);

  // Recarregar contatos quando filtros mudarem - com debounce separado para cada tipo
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      setCurrentOffset(0);
      setHasMoreContacts(true);
      loadContacts(0, 50, false);
    }, 300); // Debounce de 300ms

    return () => clearTimeout(timeoutId);
  }, [searchTerm, showUnreadOnly]);

  // Recarregar contatos quando filtros de funil mudarem - sem debounce para resposta imediata
  useEffect(() => {
    setCurrentOffset(0);
    setHasMoreContacts(true);
    loadContacts(0, 50, false);
  }, [contactFilters.funnelStages, contactFilters.activeFlows]);

  // Recarregar contatos quando mudar entre arquivados e não arquivados
  useEffect(() => {
    setCurrentOffset(0);
    setHasMoreContacts(true);
    loadContacts(0, 50, false);
  }, [showArchivedSection]);

  // Criar ref para acessar valores atuais dos filtros no polling
  const filtersRef = useRef({ contactFilters, searchTerm, showUnreadOnly, showArchivedSection });
  useEffect(() => {
    filtersRef.current = { contactFilters, searchTerm, showUnreadOnly, showArchivedSection };
  }, [contactFilters, searchTerm, showUnreadOnly, showArchivedSection]);

  // Conectar ao WebSocket unificado quando o componente montar - CORRIGIDO
  useEffect(() => {
    // CORREÇÃO: Não se conectar automaticamente ao modo global
    // Conectar apenas ao WebSocket base sem inscrição global
    unifiedWebSocketManager.connect();

    // Polling otimizado - apenas busca atualizações
    const contactsPolling = setInterval(async () => {
      try {
        // Buscar apenas os primeiros 20 contatos mais recentes para atualizações
        // IMPORTANTE: Usar os filtros atuais através da ref
        const currentFilters = filtersRef.current;

        // Preparar parâmetros com lógica correta para arquivados
        const params: any = {
          limit: 20,
          offset: 0,

          funnel_stages: currentFilters.contactFilters.funnelStages,
          unread_only: currentFilters.showUnreadOnly,

          active_flows: currentFilters.contactFilters.activeFlows,
          history_only: true
        };

        // Lógica correta para arquivados (igual ao ContactsList)
        if (currentFilters.showArchivedSection) {
          params.archived_only = true;
        } else {
          params.show_archived = false;
        }

        const response = await getContacts(params);

        const cMap = new Map(contactsRef.current);
        let hasChanges = false;

        response.contacts.forEach((c) => {
          const normalizedPhone = normalizePhone(c.phone);
          const existing = cMap.get(normalizedPhone);
          const existingPhoto = resolveContactProfilePhoto(existing);
          const incomingPhoto = resolveContactProfilePhoto(c);

          if (!existing ||
            existing.timestampNumber !== (c.last_message_at ? new Date(c.last_message_at).getTime() : 0) ||
            existing.unreadCount !== (c.unreadCount ?? 0) ||
            existing.lastMessageFromMe !== c.lastMessageFromMe ||
            existing.lastMessageStatus !== c.lastMessageStatus ||
            (incomingPhoto && incomingPhoto !== existingPhoto)) {
            cMap.set(normalizedPhone, {
              ...c,
              phone: normalizedPhone,
              photo: incomingPhoto || existingPhoto,
              name: c.name || normalizedPhone,
              unreadCount: c.unreadCount ?? 0,
              timestampNumber: c.last_message_at ? new Date(c.last_message_at).getTime() : 0,
              lastMessage: normalizeContactLastMessage(c.lastMessage),
              lastMessageFromMe: c.lastMessageFromMe === true,
              lastMessageStatus: c.lastMessageStatus,
              human_mode: c.human_mode || false,
              funnel_stage: c.funnel_stage,
              funnel_status: c.funnel_status
            });
            if (incomingPhoto && selectedContactRef.current?.phone === normalizedPhone) {
              setSelectedContact(prev => prev ? { ...prev, photo: incomingPhoto } : prev);
            }
            hasChanges = true;
          }
        });

        if (hasChanges) {
          setContacts(cMap);
        }
      } catch (error) {
        console.error('Erro ao atualizar contatos via polling:', error);
      }
    }, 30000); // Aumentar para 30 segundos

    // Limpar quando o componente desmontar
    return () => {
      clearInterval(contactsPolling);
    };
  }, []);

  // CORREÇÃO: Inscrever-se apenas no contato selecionado
  useEffect(() => {
    if (!selectedContact) return;

    // Inscrever no tópico específico do contato selecionado
    unifiedWebSocketManager.subscribe(selectedContact.phone);

    // Registrar handler para mensagens específicas deste contato
    const unsubscribeContact = unifiedWebSocketManager.onMessage(selectedContact.phone, (data) => {
      handleWebSocketMessage(data);
    });

    // Limpar quando mudar de contato ou desmontar
    return () => {
      unsubscribeContact();
      unifiedWebSocketManager.unsubscribe(selectedContact.phone);
    };
  }, [selectedContact]);

  // REMOVIDO: useEffect redundante para mensagens unificadas globais
  // A atualização da lista de contatos agora é feita via polling
  // e mensagens específicas são recebidas via WebSocket do contato selecionado

  // REMOVIDO: useEffect duplicado - já implementado acima

  /**
   * Normaliza um número de telefone para usar como chave no Map.
   * Remove espaços, traços e garante consistência.
   */
  const normalizePhone = (phone: string): string => {
    if (!phone) return '';

    // Remove todos os caracteres não numéricos
    // Isso garante consistência entre '55 1234-5678' e '551234-5678' por exemplo
    let normalized = phone.replace(/\D/g, '');

    // Se quiser manter o formato com país, você pode adicionar lógica aqui
    // Por exemplo, garantir que comece com '55' para Brasil

    return normalized;
  };

  // 2. Agora, vamos modificar o handleWebSocketMessage para usar a função de normalização

  const handleWebSocketMessage = (data: any) => {
    if (data.type === 'connection_established') return;

    const rawPhoneFromMsg = data.phone;
    if (!rawPhoneFromMsg) return;

    // Normalizar o telefone
    const phoneFromMsg = normalizePhone(rawPhoneFromMsg);

    // NOVO: Verificar duplicação usando messageId ou momment + phone
    const messageKey = `${data.messageId || data.momment || Date.now()}_${phoneFromMsg}`;
    if (processedWebSocketMessages.current.has(messageKey)) {
      console.log('🚫 Mensagem duplicada ignorada:', messageKey);
      return;
    }
    processedWebSocketMessages.current.add(messageKey);

    // Limpar mensagem do Set após 5 minutos para evitar vazamento de memória
    setTimeout(() => {
      processedWebSocketMessages.current.delete(messageKey);
    }, 5 * 60 * 1000);

    // IMPORTANTE: Se a mensagem é para o contato atualmente selecionado,
    // apenas atualizamos a lista de contatos mas NÃO processamos a mensagem aqui.
    // O useOptimizedMessages vai processar e adicionar ao chat.
    const isForSelectedContact = selectedContact && phoneFromMsg === selectedContact.phone;

    if (isForSelectedContact) {
      console.log('📌 Mensagem para contato selecionado detectada. Deixando useOptimizedMessages processar:', phoneFromMsg);
    } else {
      console.log('🔔 Processando mensagem WebSocket para outro contato:', {
        phoneOriginal: rawPhoneFromMsg,
        phoneNormalizado: phoneFromMsg,
        type: data.type,
        content: typeof data.content === 'string' ? data.content.substring(0, 20) : data.content,
        messageKey: messageKey
      });
    }

    if (data.type === 'message_status_update') {
      setContacts((prev) => {
        const newMap = new Map(prev);
        const existing = newMap.get(phoneFromMsg);
        if (existing && existing.lastMessageFromMe) {
          newMap.set(phoneFromMsg, {
            ...existing,
            lastMessageStatus: data.status || existing.lastMessageStatus || 'sent',
          });
        }
        return newMap;
      });
      return;
    }

    // NOVO: Tratamento inteligente de mensagens próprias
    if (data.fromMe === true) {
      // Se for mensagem manual do celular (fromApi=false), sempre processar
      if (data.fromApi === false) {
        console.log('📱 Mensagem manual do operador recebida:', phoneFromMsg);
        // Continua o processamento normal
      } else {
        // Se fromApi=true, pode ser do chat frontend OU do LLM
        // Verificar se temos localMessageId na mensagem
        const hasLocalMessageId = data.localMessageId && data.localMessageId.startsWith('local_');

        if (hasLocalMessageId) {
          // Mensagem enviada pelo chat frontend - ignorar para evitar duplicação
          console.log('💬 Ignorando notificação de mensagem própria enviada pelo chat:', phoneFromMsg);

          // Apenas atualiza o status/timestamp do contato
          setContacts((prev) => {
            const newMap = new Map(prev);
            const existing = newMap.get(phoneFromMsg);
            if (existing) {
              newMap.set(phoneFromMsg, {
                ...existing,
                lastMessageStatus: data.status || existing.lastMessageStatus || 'sent',
                timestampNumber: Date.now(),
              });
            }
            return newMap;
          });

          return;
        } else {
          // Mensagem sem localMessageId = provavelmente do LLM ou outra integração
          console.log('🤖 Mensagem de sistema/LLM recebida:', phoneFromMsg);
          // Continua o processamento normal
        }
      }
    }

    // Processar atualizações NPS
    if (data.type === 'nps_update') {
      console.log('🎯 [Chat] Recebeu nps_update via WebSocket:', data);
      // A atualização será processada pelo useOptimizedMessages se for o contato selecionado
      return;
    }

    // Ignora eventos de mudança de modo
    if (data.type === 'contact_mode_changed') {
      setContacts((prev) => {
        const newMap = new Map(prev);
        const existing = newMap.get(phoneFromMsg);
        if (existing) {
          const updated = {
            ...existing,
            human_mode: data.human_mode === true
          };
          newMap.set(phoneFromMsg, updated);
        }
        return newMap;
      });
      return;
    }

    // Timestamp atual para a mensagem
    const currentTimestamp = Date.now();

    // Determina o formato da última mensagem
    let lastMessage = '';
    let detectedType = data.type || 'text';

    console.log('📩 Processando mensagem para lista de contatos:', {
      content: data.content,
      type: data.type,
      fromPhone: phoneFromMsg
    });

    const preview = getContactLastMessagePreview(data.content);
    lastMessage = preview.label || (detectedType === 'text' ? '' : `[${detectedType.toUpperCase()}]`);
    if (preview.type !== 'text') {
      detectedType = preview.type;
    } else if (['audio', 'video', 'image', 'nps'].includes(detectedType)) {
      lastMessage = normalizeContactLastMessage(detectedType);
    }

    // Acesso direto ao Map atual através do ref
    const currentContacts = contactsRef.current;
    console.log('🔍 Estado atual de contatos:', {
      totalContacts: currentContacts.size,
      hasContact: currentContacts.has(phoneFromMsg),
      detectedType: detectedType
    });

    // IMPORTANTE: Apenas incrementar contador de não lidas se a mensagem não for do usuário
    const isFromUser = data.fromMe === true;
    const isFromLLM = data.senderName === 'LLM';

    // IMPORTANTE: Verificar se o contato está selecionado atualmente
    const isContactSelected = selectedContact?.phone === phoneFromMsg;
    const incomingMessagePhoto = resolveContactProfilePhoto({ photo: data.photo });

    if (incomingMessagePhoto && isContactSelected) {
      setSelectedContact(prev => prev ? { ...prev, photo: incomingMessagePhoto } : prev);
    }

    // Atualiza o Map de contatos
    setContacts((prev) => {
      // Clone o Map para não modificar o original
      const newMap = new Map(prev);
      const existing = newMap.get(phoneFromMsg);

      if (!existing) {
        console.log('➕ Criando novo contato:', phoneFromMsg);

        // Se não for do usuário, não for do LLM e não estiver selecionado => unread = 1
        const unreadCount = (!isFromUser && !isFromLLM && !isContactSelected) ? 1 : 0;

        const newContact: Contact = {
          phone: phoneFromMsg,
          name: data.senderName || phoneFromMsg,
          photo: incomingMessagePhoto,
          lastMessage: lastMessage,
          lastMessageFromMe: isFromUser,
          lastMessageStatus: isFromUser ? (data.status || 'sent') : undefined,
          timestamp: new Date(currentTimestamp).toLocaleTimeString(),
          timestampNumber: currentTimestamp,
          unreadCount,
          human_mode: false,
        };
        newMap.set(phoneFromMsg, newContact);
      } else {
        console.log('🔄 Atualizando contato existente:', phoneFromMsg);

        // Só incrementa se:
        // 1) mensagem não é do usuário (isFromUser=false)
        // 2) não é do LLM
        // 3) contato não está selecionado
        const shouldIncrementUnread = (!isFromUser && !isFromLLM && !isContactSelected);

        const updatedContact: Contact = {
          ...existing,
          phone: phoneFromMsg, // garantir telefone correto
          photo: incomingMessagePhoto || resolveContactProfilePhoto(existing),
          lastMessage: lastMessage,
          lastMessageFromMe: isFromUser,
          lastMessageStatus: isFromUser ? (data.status || 'sent') : undefined,
          timestamp: new Date(currentTimestamp).toLocaleTimeString(),
          timestampNumber: currentTimestamp,
          unreadCount: shouldIncrementUnread
            ? (existing.unreadCount || 0) + 1
            : (existing.unreadCount || 0),
        };
        console.log('✅ Atualizando contato com lastMessage:', {
          phone: phoneFromMsg,
          lastMessage: lastMessage,
          previousMessage: existing.lastMessage,
          type: detectedType
        });

        // Se for do LLM, zera contador (caso queira sobrescrever mesmo se já tinha valor)
        if (isFromLLM) {
          updatedContact.unreadCount = 0;
        }

        newMap.set(phoneFromMsg, updatedContact);
      }

      console.log('✅ Contato atualizado no setter. Total contatos:', newMap.size);
      return newMap;
    });

    // Verificação após a atualização do estado
    setTimeout(() => {
      // Use contactsRef para acessar o valor mais recente de contacts
      const currentContact = contactsRef.current.get(phoneFromMsg);

      console.log('Verificação pós-atualização:', {
        phone: phoneFromMsg,
        encontrado: !!currentContact,
        timestampNumber: currentContact?.timestampNumber,
        lastMessage: currentContact?.lastMessage,
        detectedType: detectedType,
        unreadCount: currentContact?.unreadCount
      });

      // Se o contato não for encontrado, vamos procurar em todas as chaves
      if (!currentContact) {
        console.warn('Contato não encontrado após atualização. Verificando todas as chaves...');
        const allKeys = Array.from(contactsRef.current.keys());
        console.log('Todas as chaves:', allKeys);

        // Tenta encontrar chaves similares
        const similarKeys = allKeys.filter(key =>
          key.includes(phoneFromMsg.substring(phoneFromMsg.length - 8)) ||
          phoneFromMsg.includes(key.substring(key.length - 8))
        );

        if (similarKeys.length > 0) {
          console.log('Encontradas chaves similares:', similarKeys);
          similarKeys.forEach(key => {
            console.log(`Contato com chave similar ${key}:`, contactsRef.current.get(key));
          });
        }
      }
    }, 100);

    // IMPORTANTE: Se a mensagem é para o contato selecionado,
    // paramos aqui para evitar processamento duplo
    if (isForSelectedContact) {
      console.log('⏹️ Parando processamento aqui. useOptimizedMessages cuidará desta mensagem.');
      return;
    }
  };

  // Função auxiliar para depuração que pode ser chamada após receber uma mensagem
  const debugContactState = (phoneNumber: string) => {
    const contact = contacts.get(phoneNumber);
    console.log('DEBUG CONTATO:', {
      phone: phoneNumber,
      encontrado: !!contact,
      dados: contact ? {
        name: contact.name,
        timestampNumber: contact.timestampNumber,
        lastMessage: contact.lastMessage
      } : 'não encontrado'
    });

    // Verifica se este contato aparece na lista filtrada
    const naListaFiltrada = filteredAndSortedContacts.some(c => c.phone === phoneNumber);
    console.log(`Contato ${phoneNumber} está na lista filtrada? ${naListaFiltrada}`);

    if (!naListaFiltrada && contact && contact.timestampNumber) {
      console.warn('ALERTA: Contato tem timestampNumber mas não está na lista filtrada!');
    }
  };

  // Função para enviar mensagem de texto
  const handleSendMessage = async () => {
    if (!newMessage.trim() || !selectedContact) return;

    try {
      // Gerar ID único para a mensagem
      const localMessageId = `local_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
      const replyPreview = replyingTo ? buildReplyPreview(replyingTo) : undefined;

      // Enviar mensagem usando o hook (também atualizará o estado local)
      sendMessage(newMessage, 'text', localMessageId, { replyTo: replyPreview });
      updateContactLastOwnMessagePreview(selectedContact.phone, newMessage, 'sending');

      // Enviar para o WhatsApp com o ID local
      await sendWhatsAppText({
        phone: selectedContact.phone,
        message: newMessage,
        localMessageId: localMessageId,
        replyTo: replyPreview
      });
      updateContactLastOwnMessagePreview(selectedContact.phone, newMessage, 'sent');

      // Limpar campo de texto
      setNewMessage('');
      setReplyingTo(null);
    } catch (error) {
      console.error('[handleSendMessage] -> Erro ao enviar texto:', error);
      updateContactLastOwnMessagePreview(selectedContact.phone, newMessage, 'failed');
    }
  };

  // Função para enviar mensagem de áudio
  const handleAudioRecorded = async (audioBlob: Blob, recordedDuration: number) => {
    if (!selectedContact) return;

    try {
      console.log("[AUDIO] 🚀 Usando fluxo WAHA otimizado (FormData direto)");
      console.log("[AUDIO] Áudio gravado com", recordedDuration, "segundos");
      console.log("[AUDIO] Tamanho do blob:", audioBlob.size, "bytes");
      console.log("[AUDIO] Tipo MIME:", audioBlob.type);

      // Gerar ID único para o áudio
      const localMessageId = `local_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
      console.log("[AUDIO] ID da mensagem local:", localMessageId);

      // Fluxo otimizado WAHA: não converter para base64
      const localMessageContent = {
        url: URL.createObjectURL(audioBlob),  // URL temporária para UI
        mimeType: audioBlob.type,
        duration: recordedDuration
      };

      console.log("[AUDIO] Conteúdo da mensagem local WAHA:", {
        mimeType: localMessageContent.mimeType,
        duration: localMessageContent.duration,
        urlType: 'blob'
      });

      // Enviar mensagem local para UI imediatamente
      sendMessage(localMessageContent, 'audio', localMessageId);
      updateContactLastOwnMessagePreview(selectedContact.phone, 'Áudio', 'sending');

      // Enviar via WAHA direto (FormData, sem base64) - sem verificação desnecessária
      try {
        console.log("[AUDIO] Enviando via WAHA Direct (FormData)...");
        const result = await sendWhatsAppAudioDirect({
          phone: selectedContact.phone,
          audioBlob: audioBlob,
          convert: true
        });
        console.log("[AUDIO] ✅ Áudio enviado via WAHA Direct:", result);
        updateContactLastOwnMessagePreview(selectedContact.phone, 'Áudio', 'sent');
      } catch (wahaError) {
        console.error("[AUDIO] ❌ Erro ao enviar via WAHA Direct:", wahaError);
        // Fallback para fluxo tradicional
        console.log("[AUDIO] Fazendo fallback para fluxo tradicional...");

        // Converter Blob para base64 para fallback
        const reader = new FileReader();
        reader.onload = async (e) => {
          if (!e.target?.result) return;
          const base64Content = e.target.result.toString();
          console.log("[AUDIO] Base64 gerado para fallback, tamanho:", base64Content.length);

          const fallbackContent = {
            url: base64Content,
            mimeType: audioBlob.type,
            duration: recordedDuration
          };

          try {
            const payload: SendAudioParams = {
              phone: selectedContact.phone,
              audio: base64Content,
              localMessageId: localMessageId
            };
            await sendWhatsAppAudio(payload);
            updateContactLastOwnMessagePreview(selectedContact.phone, 'Áudio', 'sent');
          } catch (fallbackErr) {
            console.error('[AUDIO] Erro no fallback:', fallbackErr);
            updateContactLastOwnMessagePreview(selectedContact.phone, 'Áudio', 'failed');
          }
        };
        reader.readAsDataURL(audioBlob);
      }
    } catch (err) {
      console.error('Erro ao processar áudio gravado:', err);
      updateContactLastOwnMessagePreview(selectedContact.phone, 'Áudio', 'failed');
    }
  };

  // Função para lidar com seleção de arquivos
  const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    if (!event.target.files || event.target.files.length === 0 || !selectedContact) {
      return;
    }

    const file = event.target.files[0];
    event.target.value = ''; // reset

    // Ignorar arquivos de áudio - usamos apenas o gravador de áudio
    if (file.type.startsWith('audio/')) {
      console.log('Arquivos de áudio devem ser enviados usando o gravador de áudio.');
      return;
    }

    let fileType: 'image' | 'video';
    if (file.type.startsWith('image/')) {
      fileType = 'image';
    } else if (file.type.startsWith('video/')) {
      fileType = 'video';
    } else {
      console.error('Tipo de arquivo não suportado:', file.type);
      return;
    }

    const reader = new FileReader();
    reader.onload = async (e) => {
      if (!e.target?.result) return;
      const base64Content = e.target.result.toString();

      try {
        console.log(`[${fileType.toUpperCase()}] Arquivo selecionado:`, file.name);
        console.log(`[${fileType.toUpperCase()}] Tamanho:`, file.size, "bytes");
        console.log(`[${fileType.toUpperCase()}] Tipo MIME:`, file.type);
        console.log(`[${fileType.toUpperCase()}] Base64 gerado, tamanho:`, base64Content.length, "caracteres");
        console.log(`[${fileType.toUpperCase()}] Primeiros 100 chars:`, base64Content.substring(0, 100));

        // Gerar ID único para a mídia
        const localMessageId = `local_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
        console.log(`[${fileType.toUpperCase()}] ID da mensagem local:`, localMessageId);

        // Usar base64 diretamente em vez de blob URL
        const messageContent = {
          url: base64Content,  // Base64 direto, persiste no banco
          mimeType: file.type
        };
        console.log(`[${fileType.toUpperCase()}] Enviando mensagem para o hook sendMessage...`);
        sendMessage(messageContent, fileType, localMessageId);
        const filePreview = `[${fileType.toUpperCase()}]`;
        updateContactLastOwnMessagePreview(selectedContact.phone, filePreview, 'sending');

        // Enviar para o WhatsApp com base no tipo
        if (fileType === 'image') {
          await sendWhatsAppImage({
            phone: selectedContact.phone,
            image: base64Content,
            localMessageId: localMessageId
          });
        } else {
          await sendWhatsAppVideo({
            phone: selectedContact.phone,
            video: base64Content,
            localMessageId: localMessageId
          });
        }
        updateContactLastOwnMessagePreview(selectedContact.phone, filePreview, 'sent');
      } catch (err) {
        console.error(`[handleFileChange] -> Erro ao enviar ${fileType}:`, err);
        updateContactLastOwnMessagePreview(selectedContact.phone, `[${fileType.toUpperCase()}]`, 'failed');
      }
    };

    reader.readAsDataURL(file);
  };

  // Função para alternar modo humano/bot
  const handleToggleAtendimento = async () => {
    if (!selectedContact) return;

    try {
      const userType = localStorage.getItem('user_type');
      const clientId = userType === 'user' ?
        localStorage.getItem('master_client_id') :
        localStorage.getItem('client_id');
      const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));

      if (!clientId || !companyId) {
        console.error('IDs não encontrados');
        return;
      }

      if (!selectedContact.human_mode) {
        // Modo IA -> Humano
        await takeOverContact(selectedContact.phone);
        setSkipHistory(true);
        setSelectedContact({ ...selectedContact, human_mode: true });
        setContacts((prev) => {
          const newMap = new Map(prev);
          const c = newMap.get(selectedContact.phone);
          if (c) {
            c.human_mode = true;
            newMap.set(selectedContact.phone, c);
          }
          return newMap;
        });
      } else {
        // Modo Humano -> IA
        await releaseContactToBot(selectedContact.phone);
        setSelectedContact({ ...selectedContact, human_mode: false });
        setContacts((prev) => {
          const newMap = new Map(prev);
          const c = newMap.get(selectedContact.phone);
          if (c) {
            c.human_mode = false;
            newMap.set(selectedContact.phone, c);
          }
          return newMap;
        });
      }
    } catch (err) {
      console.error('Erro ao alternar modo de atendimento:', err);
    }
  };

  const selectContactFromList = async (contact: Contact) => {
    // Normalizar o telefone antes de selecionar o contato
    const normalizedPhone = normalizePhone(contact.phone);

    console.log('🔍 Contato selecionado:', contact);
    console.log('📊 Flow Progress:', contact.flow_progress);
    console.log('📋 Tipo do contact:', typeof contact, 'É array?', Array.isArray(contact));
    console.log('🗂️ Chaves do contact:', Object.keys(contact));

    // Verificar se o contato existe no Map com o telefone normalizado
    const existingContact = contacts.get(normalizedPhone);
    console.log('📱 Contato existente no Map:', existingContact);

    // Definir skipHistory como falso (padrão ao selecionar da lista)
    setSkipHistory(false);

    // Marca como lido no BACKEND
    try {
      await markContactAsRead(normalizedPhone);
    } catch (err) {
      console.error('Erro ao marcar contato como lido no backend:', err);
    }

    // IMPORTANTE: Resetar contador de mensagens não lidas para este contato
    setContacts((prev) => {
      const newMap = new Map(prev);
      if (prev.has(normalizedPhone)) {
        const updatedContact = {
          ...prev.get(normalizedPhone)!,
          unreadCount: 0, // Resetar contador ao selecionar o contato
        };
        newMap.set(normalizedPhone, updatedContact);
      }
      return newMap;
    });

    if (existingContact) {
      console.log(`Selecionando contato existente: ${normalizedPhone}`);
      // Mesclar dados do contact (que tem flow_progress) com existingContact
      setSelectedContact({
        ...existingContact,
        ...contact, // Isso garante que flow_progress seja incluído
        phone: normalizedPhone,
        unreadCount: 0
      });
    } else {
      console.log(`Selecionando contato novo: ${normalizedPhone}`);
      setSelectedContact({
        ...contact,
        phone: normalizedPhone,
        unreadCount: 0,
      });
    }

  };

  // Função para iniciar/parar gravação de áudio
  const toggleAudioRecording = () => {
    setIsRecording(!isRecording);
  };

  // Função para selecionar um novo contato do modal
  async function handleSelectNewContact(contact: Contact) {
    // Marca o timestampNumber para aparecer na sidebar
    const updated = { ...contact, timestampNumber: Date.now() };

    // Atualiza o Map de contatos
    setContacts((prev) => {
      const newMap = new Map(prev);
      newMap.set(updated.phone, updated);
      return newMap;
    });

    // Seleciona o contato
    setSelectedContact(updated);

    // Fecha o modal e limpa os dados do modal
    setShowNewChatModal(false);
    setModalContacts([]);
    setModalSearchTerm('');
    setModalOffset(0);
    setHasMoreModalContacts(true);
  }

  // Lista ordenada de contatos (backend já fez a filtragem)
  const filteredAndSortedContacts = useMemo(() => {
    console.log('🔍 Preparando lista de contatos', {
      contactsSize: contacts.size,
      searchTerm: searchTerm,
      showUnreadOnly: showUnreadOnly
    });

    // Converter Map para array - backend já filtrou e ordenou
    let contactArray = Array.from(contacts.values());

    // Filtrar apenas contatos com histórico (local)
    const withHistory = contactArray.filter((contact) => {
      return (contact.timestampNumber && contact.timestampNumber > 0) ||  // timestamp válido
        (contact.unreadCount && contact.unreadCount > 0) ||           // tem mensagens não lidas
        (contact.name && contact.name !== contact.phone);            // tem nome diferente do telefone
    });

    // Backend já aplicou filtros de busca e unread_only
    // Aqui só ordenamos localmente por timestamp como fallback
    withHistory.sort((a, b) => {
      const timeA = a.timestampNumber || 0;
      const timeB = b.timestampNumber || 0;
      return timeB - timeA;
    });

    console.log('📋 Lista final de contatos:', withHistory.length);
    return withHistory;
  }, [contacts]);


  useEffect(() => {
    // Log de estatísticas
    console.log('📊 Estado de contatos:', {
      total: contacts.size,
      filteredTotal: filteredAndSortedContacts.length,
      selecionado: selectedContact?.phone
    });

    console.log('📊 Contatos atualizados:', {
      total: contacts.size,
      filteredTotal: filteredAndSortedContacts.length
    });

    // Verificação de consistência
    const interval = setInterval(() => {
      if (contacts.size > 0 && filteredAndSortedContacts.length === 0) {
        console.warn('⚠️ Inconsistência detectada: contatos existem, mas lista filtrada está vazia!');

        // Forçar recálculo do estado
        setContacts(prevContacts => {
          // Cria um novo Map com cópias dos valores para forçar atualização
          const newContacts = new Map();
          prevContacts.forEach((contact, phone) => {
            newContacts.set(phone, { ...contact });
          });
          return newContacts;
        });
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [contacts, filteredAndSortedContacts, selectedContact]);

  // Controlar navegação mobile e carregar status dos fluxos
  useEffect(() => {
    if (selectedContact) {
      setShowMobileChat(true);
    }
  }, [selectedContact]);

  // Função para voltar à lista no mobile
  const handleBackToList = () => {
    setShowMobileChat(false);
    setSelectedContact(null);
  };

  // Funções helper para o progresso dos fluxos
  const hasActiveFlows = (flowProgress: any) => {
    if (!flowProgress) return false;
    return Object.values(flowProgress).some((flow: any) =>
      flow && flow.status !== 'CANCELED'
    );
  };

  const getStatusLabel = (status: string) => {
    const labels = {
      'SUCCESS': 'Enviado',
      'SCHEDULED': 'Agendado',
      'PROCESSING': 'Enviando...',
      'FAILED': 'Erro'
    };
    return labels[status as keyof typeof labels] || status;
  };

  const formatNextExecution = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = date.getTime() - now.getTime();
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
    const diffDays = Math.floor(diffHours / 24);

    if (diffDays > 0) {
      return `${date.toLocaleDateString('pt-BR')} às ${date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}`;
    } else if (diffHours > 0) {
      return `em ${diffHours}h - ${date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}`;
    } else {
      const diffMinutes = Math.floor(diffMs / (1000 * 60));
      return `em ${diffMinutes} min`;
    }
  };

  const renderActiveFlows = (flowProgress: any) => {
    const flowConfigs = {
      follow_up: {
        label: 'Follow-up',
        icon: MessageSquare,
      },
      confirmation: {
        label: 'Confirmação',
        icon: Calendar,
      },
      noshow: {
        label: 'No-show',
        icon: XCircle,
      },
      pos_consulta: {
        label: 'Pós-consulta',
        icon: HeartHandshake,
      },
      pos_venda: {
        label: 'Pós-venda',
        icon: ShoppingBag,
      }
    };

    return Object.entries(flowProgress).map(([flowType, progress]) => {
      if (!progress || (progress as FlowProgress).status === 'CANCELED') return null;

      const config = flowConfigs[flowType as keyof typeof flowConfigs];
      if (!config) return null;

      const Icon = config.icon;
      const typedProgress = progress as FlowProgress;
      const progressPercent = (typedProgress.current_step / typedProgress.total_steps) * 100;

      return (
        <div key={flowType} className={cx('rounded-2xl border p-3', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-white')}>
          <div className="flex items-start gap-3">
            {/* Ícone do Fluxo */}
            <div className={cx('grid h-9 w-9 shrink-0 place-items-center rounded-xl', isDark ? 'bg-white/10 text-white/75' : 'bg-brand-canvas text-brand/75')}>
              <Icon className="h-4 w-4" />
            </div>

            {/* Informações do Fluxo */}
            <div className="flex-1">
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-sm font-semibold">
                  {config.label}
                </h4>
                <span className={cx('text-xs', isDark ? 'text-white/45' : 'text-brand/45')}>
                  Etapa {typedProgress.current_step} de {typedProgress.total_steps}
                </span>
              </div>

              {/* Barra de Progresso */}
              <div className={cx('mb-2 h-2 w-full overflow-hidden rounded-full', isDark ? 'bg-white/10' : 'bg-brand/10')}>
                <div
                  className="h-full bg-brand transition-all duration-500"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>

              {/* Detalhes de Tempo */}
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-4">
                  {/* Status Atual */}
                  <span className={`flex items-center gap-1 ${typedProgress.status === 'SUCCESS' ? 'text-green-600' :
                    typedProgress.status === 'PROCESSING' ? 'text-yellow-600' :
                      typedProgress.status === 'SCHEDULED' ? 'text-blue-600' :
                        'text-red-600'
                    }`}>
                    {typedProgress.status === 'SUCCESS' && <CheckCircle2 className="w-3 h-3" />}
                    {typedProgress.status === 'PROCESSING' && <Loader2 className="w-3 h-3 animate-spin" />}
                    {typedProgress.status === 'SCHEDULED' && <Clock className="w-3 h-3" />}
                    {typedProgress.status === 'FAILED' && <AlertCircle className="w-3 h-3" />}
                    {getStatusLabel(typedProgress.status)}
                  </span>

                  {/* Próxima Execução */}
                  {typedProgress.next_scheduled && typedProgress.status === 'SCHEDULED' && (
                    <span className={cx('flex items-center gap-1', isDark ? 'text-white/55' : 'text-brand/55')}>
                      <Calendar className="w-3 h-3" />
                      Próxima: {formatNextExecution(typedProgress.next_scheduled)}
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      );
    });
  };

  const profileActions = selectedContact ? (
    <ChatProfileActions
      isDark={isDark}
      onOpenNotes={() => openProfileTab('notes')}
      onOpenTasks={() => openProfileTab('tasks')}
      pendingTasksCount={selectedContact.pending_tasks_count}
    />
  ) : null;

  const profileLeadForDrawer = selectedContact && profileLead
    ? mapLeadToProfile(profileLead, selectedContact)
    : null;

  const composerModeButton = selectedContact ? (
    <button
      type="button"
      onClick={handleToggleAtendimento}
      className={cx(
        'inline-flex min-h-8 min-w-8 shrink-0 items-center justify-center rounded-xl border p-1.5 transition-colors',
        selectedContact.human_mode
          ? 'border-red-500 bg-red-500 text-white hover:bg-red-600'
          : isDark
            ? 'border-white bg-white text-brand hover:bg-white/90'
            : 'border-brand bg-brand text-white hover:bg-brand/90'
      )}
      title={selectedContact.human_mode ? 'Devolver atendimento para IA' : 'Assumir atendimento'}
      aria-label={selectedContact.human_mode ? 'Devolver atendimento para IA' : 'Assumir atendimento'}
    >
      {selectedContact.human_mode ? <UserIcon className="h-4 w-4" /> : <CpuIcon className="h-4 w-4" />}
    </button>
  ) : null;

  // Se for mobile, renderiza o componente otimizado
  if (isMobile) {
    return <ChatMobile />;
  }

  // Renderização para desktop
  return (
    <div className={cx('flex h-screen flex-col overflow-hidden lg:h-[calc(100vh-4rem)]', isDark ? 'bg-brand text-white' : 'bg-brand-canvas text-brand')}>
      <div className="flex min-h-0 flex-1 gap-3 p-3 lg:p-4">
        {/* Sidebar - Sempre visível no desktop, condicional no mobile */}
        <aside className={cx(`
          w-full lg:w-[360px] flex-shrink-0 flex flex-col overflow-hidden rounded-2xl border shadow-flat-md
          lg:flex
          ${showMobileChat ? 'hidden' : 'flex'}`,
          isDark ? 'border-white/10 bg-white/[0.06]' : 'border-brand/10 bg-white'
        )}>
          {/* Título, botão de novo chat e campo de busca */}
          <div className={cx('flex-shrink-0 border-b p-4', isDark ? 'border-white/10' : 'border-brand/10')}>
            <div className="mb-4 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="truncate text-lg font-semibold">Chat ao vivo</h2>
                <div className="mt-1 flex items-center gap-2">
                  <ConnectionStatusIndicator />
                </div>
              </div>

              {/* Botão de novo chat */}
              <button
                onClick={() => setShowNewChatModal(true)}
                className={agentivePrimaryButtonClass('min-h-10 min-w-10 rounded-xl p-2.5')}
                title="Iniciar novo chat"
              >
                <PlusCircle className="h-4 w-4" />
              </button>
            </div>

            {/* Barra de busca */}
            <div className="relative mb-3">
              <input
                type="text"
                placeholder="Buscar contato..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className={agentiveInputClass(isDark, 'pl-10')}
              />
              <Search className={cx('absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2', isDark ? 'text-white/35' : 'text-brand/35')} />
            </div>

            {/* Barra de filtros */}
            <div className={cx('grid grid-cols-2 rounded-2xl border p-1', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas')}>
              <button
                onClick={() => setShowUnreadOnly(false)}
                className={cx(
                  'rounded-xl px-3 py-2 text-xs font-semibold transition-all',
                  !showUnreadOnly
                    ? isDark ? 'bg-white text-brand shadow-flat' : 'bg-brand text-white shadow-flat'
                    : isDark ? 'text-white/55 hover:text-white' : 'text-brand/55 hover:text-brand'
                )}
              >
                Todas
              </button>
              <button
                onClick={() => setShowUnreadOnly(true)}
                className={cx(
                  'rounded-xl px-3 py-2 text-xs font-semibold transition-all',
                  showUnreadOnly
                    ? isDark ? 'bg-white text-brand shadow-flat' : 'bg-brand text-white shadow-flat'
                    : isDark ? 'text-white/55 hover:text-white' : 'text-brand/55 hover:text-brand'
                )}
              >
                Não lidas
                {/* Badge com contador de não lidas */}
                {getTotalUnreadCount() > 0 && (
                  <span className="ml-1 inline-flex min-h-4 min-w-4 items-center justify-center rounded-full bg-emerald-500 px-1 text-[10px] font-bold text-white">
                    {getTotalUnreadCount() > 99 ? '99+' : getTotalUnreadCount()}
                  </span>
                )}
              </button>
            </div>
          </div>

          {/* Componente de filtros avançados - Ocultar para equipe SUPORTE */}
          {!showArchivedSection && !isSupportTeam && (
            <ContactFilters
              onFiltersChange={setContactFilters}
              currentFilters={contactFilters}
              pipelines={pipelines}
            />
          )}

          {/* Mensagem informativa para equipe SUPORTE */}
          {isSupportTeam && !showArchivedSection && (
            <div className={cx('mx-4 mb-3 rounded-2xl border p-3', isDark ? 'border-white/10 bg-white/[0.05]' : 'border-brand/10 bg-brand-canvas')}>
              <div className="flex items-center gap-2">
                <Headphones className={cx('h-4 w-4', isDark ? 'text-white/65' : 'text-brand/65')} />
                <span className={cx('text-sm font-medium', isDark ? 'text-white/75' : 'text-brand/75')}>
                  Modo Suporte: Visualizando apenas clientes
                </span>
              </div>
            </div>
          )}

          {/* Lista de contatos */}
          <div
            className="flex-1 overflow-y-auto min-h-0"
            onScroll={(e) => {
              const { scrollTop, scrollHeight, clientHeight } = e.currentTarget;
              // Detectar quando está perto do final (últimos 200px)
              const nearBottom = scrollHeight - scrollTop - clientHeight < 200;

              if (nearBottom && hasMoreContacts && !isLoadingMoreContacts && !isThrottled) {
                console.log('🔄 Carregando mais contatos...', {
                  currentOffset,
                  hasMore: hasMoreContacts,
                  isLoading: isLoadingMoreContacts,
                  scrollInfo: {
                    scrollTop,
                    scrollHeight,
                    clientHeight,
                    remaining: scrollHeight - scrollTop - clientHeight
                  }
                });

                // Throttle para evitar múltiplas chamadas
                setIsThrottled(true);
                setTimeout(() => setIsThrottled(false), 1000);

                loadContacts(currentOffset, 50, true);
              }
            }}
          >
            <div className="space-y-2 p-3">
              {/* Atalho para conversas arquivadas */}
              {!showArchivedSection && (
                <button
                  onClick={() => {
                    setShowArchivedSection(true);
                    setSelectedContact(null);
                    setSearchTerm('');
                    setContactFilters({ funnelStages: [], activeFlows: [] });
                  }}
                  className={cx(
                    'mb-1 flex w-full items-center justify-between rounded-xl px-2.5 py-2 text-left transition-colors',
                    isDark ? 'text-white/60 hover:bg-white/[0.06] hover:text-white' : 'text-brand/55 hover:bg-brand-canvas hover:text-brand'
                  )}
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <span className={cx('grid h-7 w-7 shrink-0 place-items-center rounded-lg', isDark ? 'bg-white/[0.06]' : 'bg-brand/5')}>
                      <Archive className="h-3.5 w-3.5" />
                    </span>
                    <span className="truncate text-xs font-semibold">Arquivadas</span>
                  </div>
                  <ChevronRight className="h-3.5 w-3.5 shrink-0 opacity-45" />
                </button>
              )}

              {/* Botão voltar quando estiver vendo arquivados */}
              {showArchivedSection && (
                <button
                  onClick={() => {
                    setShowArchivedSection(false);
                    setSelectedContact(null);
                  }}
                  className={cx(
                    'mb-1 flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left transition-colors',
                    isDark ? 'text-white/70 hover:bg-white/[0.06] hover:text-white' : 'text-brand/70 hover:bg-brand-canvas hover:text-brand'
                  )}
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                  <span className="truncate text-xs font-semibold">Conversas arquivadas</span>
                </button>
              )}

              {isContactsLoading ? (
                // Estado de carregamento com esqueletos de contato
                <div className="space-y-2 p-1">
                  {/* Renderiza múltiplos esqueletos para dar a impressão de uma lista sendo carregada */}
                  {Array(8).fill(0).map((_, index) => (
                    <div key={index} className={cx('mb-1 flex w-full items-start gap-3 rounded-2xl border p-3 animate-pulse', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas')}>
                      {/* Avatar esqueleto */}
                      <div className="relative flex-shrink-0">
                        <div className={cx('h-12 w-12 rounded-xl', isDark ? 'bg-white/10' : 'bg-brand/10')}></div>
                      </div>

                      {/* Conteúdo do contato esqueleto */}
                      <div className="flex-1 min-w-0 flex flex-col space-y-2">
                        {/* Nome esqueleto */}
                        <div className={cx('h-4 w-1/2 rounded', isDark ? 'bg-white/10' : 'bg-brand/10')}></div>

                        {/* Mensagem esqueleto */}
                        <div className={cx('h-3 w-3/4 rounded', isDark ? 'bg-white/10' : 'bg-brand/10')}></div>
                      </div>

                      {/* Timestamp esqueleto */}
                      <div className={cx('h-3 w-10 rounded', isDark ? 'bg-white/10' : 'bg-brand/10')}></div>
                    </div>
                  ))}
                </div>
              ) : filteredAndSortedContacts.length === 0 ? (
                // Lista vazia (após carregamento)
                <AgentiveEmptyState
                  icon={MessageSquare}
                  title="Nenhuma conversa encontrada"
                  description="Ajuste a busca ou os filtros para encontrar conversas ativas."
                />
              ) : (
                // Lista de contatos (após carregamento com resultados)
                filteredAndSortedContacts.map((contact) => {
                  // Formata o horário da última mensagem
                  const displayedTimestamp = formatChatTimestamp(contact.timestampNumber);

                  return (
                    <div
                      key={contact.phone}
                      className={cx(`
                        relative group
                        w-full rounded-2xl border p-2.5
                        flex items-start gap-3
                        transition-colors duration-150 overflow-hidden
                        ${selectedContact?.phone === contact.phone
                          ? isDark ? 'border-white/20 bg-white/12' : 'border-brand/20 bg-brand-canvas'
                          : contact.unreadCount > 0
                            ? isDark ? 'border-emerald-400/25 bg-emerald-400/10 hover:bg-emerald-400/15' : 'border-emerald-200 bg-emerald-50 hover:bg-emerald-100'
                            : isDark ? 'border-white/10 bg-white/[0.035] hover:bg-white/[0.07]' : 'border-brand/10 bg-white hover:bg-brand-canvas'}
                      `)}
                    >
                      {/* Botão oculto de arquivar/desarquivar que aparece no hover */}
                      <div className="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity z-10">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleArchiveToggle(contact, showArchivedSection);
                          }}
                          className={agentiveIconButtonClass(isDark, 'neutral', 'bg-white shadow-flat dark:bg-white/10')}
                          title={showArchivedSection ? "Desarquivar" : "Arquivar"}
                          disabled={isArchiving}
                        >
                          {showArchivedSection ? (
                            <ArchiveRestore className="h-4 w-4" />
                          ) : (
                            <Archive className="h-4 w-4" />
                          )}
                        </button>
                      </div>

                      <button
                        onClick={() => selectContactFromList(contact)}
                        className="w-full flex items-start gap-2 lg:gap-3 text-left"
                      >
                        <div className="relative flex-shrink-0">
                          <ContactAvatar contact={contact} isDark={isDark} />

                          {/* Indicador humano/bot */}
                          <div className="absolute -bottom-1 -right-1">
                            {contact.human_mode ? (
                              <div className={cx('flex h-5 w-5 items-center justify-center rounded-full border-2 shadow-flat', isDark ? 'border-brand bg-red-500' : 'border-white bg-red-500')}>
                                <UserIcon className="h-3 w-3 text-white" />
                              </div>
                            ) : (
                              <div className={cx('flex h-5 w-5 items-center justify-center rounded-full border-2 shadow-flat', isDark ? 'border-brand bg-brand' : 'border-white bg-brand')}>
                                <CpuIcon className="h-3 w-3 text-white" />
                              </div>
                            )}
                          </div>
                        </div>

                        {/* Nome, timestamp e última mensagem */}
                        <div className="flex-1 min-w-0 flex flex-col text-left overflow-hidden">
                          {/* Linha de cima (nome + horário) */}
                          <div className="flex items-center justify-between min-w-0">
                            <p className={cx('mr-1 min-w-0 flex-1 truncate text-sm', contact.unreadCount > 0 ? 'font-bold' : 'font-semibold', isDark ? 'text-white' : 'text-brand')}>
                              {contact.name}
                            </p>

                            <div className="flex items-center gap-1 flex-shrink-0">
                              {contact.unreadCount > 0 && (
                                <div className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-emerald-500 text-[10px] font-bold text-white">
                                  {contact.unreadCount > 99 ? '99+' : contact.unreadCount}
                                </div>
                              )}

                              {/* Task indicator badge */}
                              {contact.pending_tasks_count && contact.pending_tasks_count > 0 && (
                                <div
                                  className={`flex h-5 w-5 flex-shrink-0 cursor-pointer items-center justify-center rounded-full text-xs font-bold text-white ${contact.next_task?.priority === 'urgent' ? 'bg-red-500' :
                                    contact.next_task?.priority === 'high' ? 'bg-orange-500' :
                                      contact.next_task?.priority === 'medium' ? 'bg-yellow-500' :
                                        'bg-brand'
                                    }`}
                                  title={`${contact.pending_tasks_count} tarefa(s) pendente(s)${contact.next_task ? ` - Próxima: ${contact.next_task.title}` : ''}`}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setSelectedContact(contact);
                                    setProfileActiveTab('tasks');
                                    setShowContactProfile(true);
                                    loadLeadForContact(contact);
                                  }}
                                >
                                  <CheckCircle2 className="h-3 w-3" />
                                </div>
                              )}

                              {contact.timestampNumber !== 0 && (
                                <span className={cx('hidden flex-shrink-0 text-xs md:inline', contact.unreadCount > 0 ? 'font-semibold text-emerald-600' : isDark ? 'text-white/45' : 'text-brand/45')}>
                                  {displayedTimestamp}
                                </span>
                              )}
                            </div>
                          </div>

                          {contact.lastMessage && (
                            <p
                              className={cx('mt-1 flex items-center overflow-hidden truncate text-xs', contact.unreadCount > 0 ? isDark ? 'font-medium text-white/75' : 'font-medium text-brand/75' : isDark ? 'text-white/50' : 'text-brand/50')}
                            >
                              {renderContactLastMessageStatus(contact)}
                              {renderContactLastMessagePreview(contact.lastMessage)}
                            </p>
                          )}

                          {/* NOVO: Linha inferior - Status do funil de vendas */}
                          <div className="flex justify-between items-center mt-1.5 min-w-0 overflow-hidden">
                            {/* Status do Funil - usando o componente StatusTag */}
                            {contact.funnel_stage && (
                              <StatusTag status={contact.funnel_stage} pipelines={pipelines} className="flex-shrink-0" />
                            )}

                            {/* Fonte/origem do lead (se disponível) */}
                            {contact.source_id && (
                              <div className={cx('flex items-center truncate text-xs', isDark ? 'text-white/35' : 'text-brand/35')}>
                                <Target className="w-3 h-3 mr-1 flex-shrink-0" />
                                <span className="truncate">{contact.source_id}</span>
                              </div>
                            )}
                          </div>
                        </div>
                      </button>
                    </div>
                  );
                })
              )}

              {/* Indicador de carregamento para mais contatos */}
              {isLoadingMoreContacts && (
                <div className="flex justify-center py-4">
                  <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500"></div>
                </div>
              )}
            </div>
          </div>
        </aside>

        {/* Main Chat Area */}
        <main className={cx(`
          w-full lg:flex-1 flex flex-col min-w-0 overflow-hidden rounded-2xl border shadow-flat-md
          lg:flex
          ${showMobileChat ? 'flex' : 'hidden'}`,
          isDark ? 'border-white/10 bg-white/[0.06]' : 'border-brand/10 bg-white'
        )}>
          {selectedContact ? (
            <>
              {/* Chat Header */}
              <div className={cx('flex-shrink-0 border-b p-4', isDark ? 'border-white/10 bg-white/[0.045]' : 'border-brand/10 bg-white')}>
                <div className="flex items-center justify-between gap-3">
                  {/* Botão voltar para mobile */}
                  <button
                    onClick={handleBackToList}
                    className={agentiveIconButtonClass(isDark, 'neutral', '-ml-2 lg:hidden')}
                  >
                    <ChevronLeft className="h-5 w-5" />
                  </button>

                  <button
                    type="button"
                    onClick={handleOpenContactProfile}
                    className="flex min-w-0 flex-1 items-center gap-3 rounded-2xl text-left transition"
                  >
                    <ContactAvatar contact={selectedContact} isDark={isDark} />
                    <div className="min-w-0 flex-1">
                      <h2 className="truncate text-sm font-semibold lg:text-base">
                        {selectedContact.name}
                      </h2>
                      <div className="mt-1 flex min-w-0 flex-wrap items-center gap-2">
                        <span className={cx('hidden truncate text-xs sm:inline', isDark ? 'text-white/55' : 'text-brand/55')}>
                          {selectedContact.phone}
                        </span>
                      </div>
                    </div>
                  </button>

                  <button type="button" onClick={handleOpenContactProfile} className={agentiveSecondaryButtonClass(isDark, 'shrink-0')}>
                    <PanelRightOpen className="h-4 w-4" />
                    Perfil
                  </button>
                </div>

                {/* NOVO: Barra de Fluxos Ativos */}
                {(() => {
                  console.log('Debug flow header:', {
                    selectedContact: selectedContact?.name,
                    flowProgress: selectedContact?.flow_progress,
                    hasActive: selectedContact?.flow_progress ? hasActiveFlows(selectedContact.flow_progress) : false
                  });
                  return null;
                })()}
                {selectedContact.flow_progress && hasActiveFlows(selectedContact.flow_progress) && (
                  <div className="mt-3">
                    {/* Título com toggle */}
                    <button
                      onClick={() => setShowFlowTimeline(!showFlowTimeline)}
                      className={cx('flex w-full items-center gap-2 rounded-2xl border px-3 py-2 text-sm transition-colors', isDark ? 'border-white/10 bg-white/[0.04] text-white/65 hover:text-white' : 'border-brand/10 bg-brand-canvas text-brand/65 hover:text-brand')}
                    >
                      <Activity className="w-4 h-4" />
                      <span className="font-medium">Fluxos Automatizados Ativos</span>
                      <ChevronDown className={`w-4 h-4 ml-auto transition-transform ${showFlowTimeline ? 'rotate-180' : ''}`} />
                    </button>

                    {/* Timeline de Fluxos Expandida */}
                    {showFlowTimeline && (
                      <div className="space-y-3 mt-3">
                        {renderActiveFlows(selectedContact.flow_progress)}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Messages Area - Versão otimizada com virtualização */}
              {selectedContact ? (
                <div className={cx('min-h-0 flex-1 overflow-y-auto', isDark ? 'bg-brand/60' : 'bg-brand-canvas')}>
                  {isLoading ? (
                    // Estado de carregamento das mensagens com esqueletos
                    <div className="space-y-8 p-2 lg:p-4">
                      {/* Data separator skeleton */}
                      <div className="flex justify-center my-4">
                        <div className={cx('h-5 w-24 animate-pulse rounded-full', isDark ? 'bg-white/10' : 'bg-brand/10')}></div>
                      </div>

                      {/* Mensagens recebidas (esquerda) */}
                      <div className="space-y-4">
                        {/* Primeira mensagem recebida */}
                        <div className="flex items-start animate-pulse">
                          <div className={cx('mr-2 h-8 w-8 rounded-xl', isDark ? 'bg-white/10' : 'bg-brand/10')}></div>
                          <div className="max-w-[70%]">
                            <div className={cx('h-16 w-48 rounded-2xl p-3', isDark ? 'bg-white/10' : 'bg-brand/10')}></div>
                            <div className={cx('float-right mt-1 h-3 w-12 rounded', isDark ? 'bg-white/10' : 'bg-brand/10')}></div>
                          </div>
                        </div>

                        {/* Segunda mensagem recebida */}
                        <div className="flex items-start animate-pulse">
                          <div className={cx('mr-2 h-8 w-8 rounded-xl', isDark ? 'bg-white/10' : 'bg-brand/10')}></div>
                          <div className="max-w-[70%]">
                            <div className={cx('h-12 w-64 rounded-2xl p-3', isDark ? 'bg-white/10' : 'bg-brand/10')}></div>
                            <div className={cx('float-right mt-1 h-3 w-12 rounded', isDark ? 'bg-white/10' : 'bg-brand/10')}></div>
                          </div>
                        </div>
                      </div>

                      {/* Mensagens enviadas (direita) */}
                      <div className="space-y-4">
                        {/* Primeira mensagem enviada */}
                        <div className="flex items-start justify-end animate-pulse">
                          <div className="max-w-[70%]">
                            <div className={cx('h-10 w-40 rounded-2xl p-3', isDark ? 'bg-white/15' : 'bg-brand/20')}></div>
                            <div className={cx('float-right mt-1 h-3 w-12 rounded', isDark ? 'bg-white/10' : 'bg-brand/10')}></div>
                          </div>
                          <div className={cx('ml-2 h-8 w-8 rounded-xl', isDark ? 'bg-white/10' : 'bg-brand/10')}></div>
                        </div>

                        {/* Segunda mensagem enviada */}
                        <div className="flex items-start justify-end animate-pulse">
                          <div className="max-w-[70%]">
                            <div className={cx('h-20 w-56 rounded-2xl p-3', isDark ? 'bg-white/15' : 'bg-brand/20')}></div>
                            <div className={cx('float-right mt-1 h-3 w-12 rounded', isDark ? 'bg-white/10' : 'bg-brand/10')}></div>
                          </div>
                          <div className={cx('ml-2 h-8 w-8 rounded-xl', isDark ? 'bg-white/10' : 'bg-brand/10')}></div>
                        </div>
                      </div>
                    </div>
                  ) : (
                    // Componente VirtualizedMessageList quando as mensagens estão carregadas
                    <VirtualizedMessageList
                      messages={messages}
                      isLoading={isLoading}
                      hasMore={hasMore}
                      onLoadMore={loadMoreMessages}
                      onReply={setReplyingTo}
                      onReact={handleReactToMessage}
                    />
                  )}
                </div>
              ) : (
                // Estado quando nenhum contato está selecionado
                <div className="flex flex-1 items-center justify-center p-6">
                  <AgentiveEmptyState
                    icon={MessageSquare}
                    title="Selecione uma conversa"
                    description="Escolha um contato da lista para abrir o histórico e o perfil comercial."
                  />
                </div>
              )}

              {/* Input Area - Componente otimizado com botão de modo humano */}
              <div className="flex-shrink-0 relative w-full">
                {replyingTo && (
                  <div className={cx('mx-3 mb-2 flex items-center justify-between rounded-xl border px-3 py-2 text-sm shadow-flat', isDark ? 'border-white/10 bg-white/[0.06] text-white' : 'border-brand/10 bg-white text-brand')}>
                    <div className="min-w-0">
                      <div className={cx('text-xs font-semibold', isDark ? 'text-white/60' : 'text-brand/55')}>
                        Respondendo {replyingTo.fromMe ? 'você' : replyingTo.sender.name}
                      </div>
                      <div className="truncate text-xs">
                        {buildReplyPreview(replyingTo).body || 'Mensagem'}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setReplyingTo(null)}
                      className={agentiveIconButtonClass(isDark, 'neutral', 'min-h-8 min-w-8')}
                      title="Cancelar resposta"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                )}
                <OptimizedMessageInput
                  onSendText={handleSendMessage}
                  onSendImage={(file) => {
                    if (fileInputRef.current) {
                      fileInputRef.current.files = ((): FileList => {
                        const dataTransfer = new DataTransfer();
                        dataTransfer.items.add(file);
                        return dataTransfer.files;
                      })();
                      handleFileChange({ target: fileInputRef.current } as any);
                    }
                  }}
                  onSendVideo={(file) => {
                    if (fileInputRef.current) {
                      fileInputRef.current.files = ((): FileList => {
                        const dataTransfer = new DataTransfer();
                        dataTransfer.items.add(file);
                        return dataTransfer.files;
                      })();
                      handleFileChange({ target: fileInputRef.current } as any);
                    }
                  }}
                  onSendAudio={handleAudioRecorded}
                  onStartRecording={() => setIsRecording(true)}
                  disabled={!selectedContact}
                  placeholder="Digite sua mensagem..."
                  value={newMessage}
                  onChange={(value) => setNewMessage(value)}
                  extraControl={composerModeButton}
                />

                {/* INPUT FILE INVISÍVEL - mantido para compatibilidade */}
                <input
                  ref={fileInputRef}
                  type="file"
                  style={{ display: 'none' }}
                  onChange={handleFileChange}
                  accept="image/*,video/*"
                />
              </div>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center p-4">
              <AgentiveEmptyState
                icon={MessageSquare}
                title="Selecione uma conversa"
                description="As mensagens e o perfil do contato aparecem aqui."
              />
            </div>
          )}
        </main>

        {/* Modal de contatos */}
        {showNewChatModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand/55 p-4 backdrop-blur-sm animate-in fade-in duration-200">
            <div
              className={cx('relative mx-auto w-full max-w-md overflow-hidden rounded-2xl border shadow-[0_24px_70px_rgba(2,3,35,0.28)] transition-all duration-300 ease-in-out animate-in slide-in-from-bottom-4', isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand')}
              onClick={(e) => e.stopPropagation()}
            >
              {/* Cabeçalho do modal */}
              <div className={cx('flex items-center justify-between border-b p-4', isDark ? 'border-white/10' : 'border-brand/10')}>
                <div>
                  <h3 className="text-base font-semibold">Iniciar conversa</h3>
                  <p className={cx('mt-1 text-xs', isDark ? 'text-white/55' : 'text-brand/55')}>Busque contatos sem histórico recente.</p>
                </div>
                <button
                  onClick={() => setShowNewChatModal(false)}
                  className={agentiveIconButtonClass(isDark)}
                  aria-label="Fechar modal"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              {/* Conteúdo do modal */}
              <div className="p-4 max-h-[70vh] overflow-y-auto">
                {/* Campo de pesquisa funcional */}
                <div className="relative mb-4">
                  <Search className={cx('absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2', isDark ? 'text-white/35' : 'text-brand/35')} />
                  <input
                    type="text"
                    placeholder="Buscar contatos..."
                    className={agentiveInputClass(isDark, 'pl-10')}
                    value={modalSearchTerm}
                    onChange={(e) => setModalSearchTerm(e.target.value)}
                  />
                </div>

                <div
                  className="space-y-2 max-h-80 overflow-y-auto"
                  onScroll={(e) => {
                    const { scrollTop, scrollHeight, clientHeight } = e.currentTarget;
                    const nearBottom = scrollHeight - scrollTop - clientHeight < 50;

                    if (nearBottom && hasMoreModalContacts && !isLoadingModalContacts) {
                      console.log('🔄 Carregando mais contatos do modal...', modalOffset);
                      loadModalContacts(modalOffset, 20, true);
                    }
                  }}
                >
                  {isLoadingModalContacts && modalContacts.length === 0 ? (
                    // Estado de carregamento inicial
                    <div className="space-y-2">
                      {Array(5).fill(0).map((_, index) => (
                        <div key={index} className={cx('flex w-full items-center gap-3 rounded-2xl border p-3 animate-pulse', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas')}>
                          <div className={cx('h-10 w-10 rounded-xl', isDark ? 'bg-white/10' : 'bg-brand/10')}></div>
                          <div className="flex-1">
                            <div className={cx('mb-1 h-4 w-1/2 rounded', isDark ? 'bg-white/10' : 'bg-brand/10')}></div>
                            <div className={cx('h-3 w-3/4 rounded', isDark ? 'bg-white/10' : 'bg-brand/10')}></div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : modalContacts.length === 0 && !isLoadingModalContacts ? (
                    <AgentiveEmptyState
                      icon={MessageSquare}
                      title="Nenhum contato encontrado"
                      description="A busca nao retornou contatos sem historico."
                    />
                  ) : (
                    modalContacts.map((contact) => (
                      <button
                        key={contact.phone}
                        onClick={() => handleSelectNewContact(contact)}
                        className={cx('flex w-full items-center gap-3 rounded-2xl border p-3 text-left transition-colors duration-150', isDark ? 'border-white/10 bg-white/[0.035] hover:bg-white/[0.08]' : 'border-brand/10 bg-white hover:bg-brand-canvas')}
                      >
                        <ContactAvatar contact={contact} isDark={isDark} sizeClassName="h-10 w-10" />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-semibold">{contact.name}</p>
                          <p className={cx('truncate text-xs', isDark ? 'text-white/55' : 'text-brand/55')}>{contact.phone}</p>
                        </div>
                      </button>
                    ))
                  )}

                  {/* Indicador de carregamento para mais contatos */}
                  {isLoadingModalContacts && modalContacts.length > 0 && (
                    <div className="flex justify-center py-4">
                      <Loader2 className={cx('h-4 w-4 animate-spin', isDark ? 'text-white/55' : 'text-brand/55')} />
                    </div>
                  )}
                </div>
              </div>

              {/* Rodapé do modal */}
              <div className={cx('flex justify-end border-t p-4', isDark ? 'border-white/10' : 'border-brand/10')}>
                <button
                  onClick={() => setShowNewChatModal(false)}
                  className={agentiveSecondaryButtonClass(isDark)}
                >
                  Cancelar
                </button>
              </div>
            </div>
          </div>
        )}

        {showContactProfile && selectedContact && profileLeadForDrawer && (
          <LeadProfile
            activeTab={profileActiveTab}
            isOpen={showContactProfile}
            onActiveTabChange={setProfileActiveTab}
            onClose={handleCloseContactProfile}
            onLeadUpdate={() => loadLeadForContact(selectedContact)}
            onPendingTasksChange={updatePendingTasksCount}
            lead={profileLeadForDrawer}
          />
        )}

        {showContactProfile && selectedContact && !profileLeadForDrawer && (
          <ChatContactProfile
            contact={selectedContact}
            actions={profileActions}
            error={profileError}
            isConverting={isConvertingLead}
            isLeadLoading={isProfileLeadLoading}
            onClose={handleCloseContactProfile}
            onConvertToLead={handleConvertSelectedContactToLead}
          />
        )}

      </div>
    </div>
  );
};

export default ChatPage5;
