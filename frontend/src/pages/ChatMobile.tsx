// ChatMobile.tsx - Versão otimizada para dispositivos móveis
import React, { useEffect, useState } from 'react';
import {
  Search, Send, ArrowLeft, Mic, ImageIcon, VideoIcon,
  User as UserIcon, Cpu as CpuIcon, Calendar, Target,
  CheckCircle2, XCircle, DollarSign, Menu, MoreVertical,
  MessageSquare,
  PanelRightOpen,
} from 'lucide-react';
import api, {
  getContacts,
  markContactAsRead,
  takeOverContact,
  releaseContactToBot,
  sendWhatsAppText,
  sendWhatsAppAudio,
  sendWhatsAppImage,
  sendWhatsAppVideo,
  sendNPS,
  getCompanyInfo,
  unifiedWebSocketManager,
  OptimizedMessage
} from '../services/api';
import { formatChatTimestamp } from '../utils/date.ts';
import { getContactLastMessagePreview, normalizeContactLastMessage } from '../utils/contactLastMessagePreview.ts';
import { getContactInitials, resolveContactProfilePhoto } from '../utils/contactAvatar.ts';
import { useOptimizedMessages } from '../hooks/useOptimizedMessages.tsx';
import { VirtualizedMessageList } from '../components/VirtualizedMessageList.tsx';
import { OptimizedMessageInput } from '../components/OptimizedMessageInput.tsx';
import LeadProfile, { type LeadProfileTab } from '../components/LeadProfile.tsx';
import { crmApi, Lead as CrmLead } from '../services/crmApi.ts';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AgentiveEmptyState,
  agentiveIconButtonClass,
  agentiveInputClass,
  agentivePillClass,
} from '../components/AgentiveUI.tsx';
import ChatContactProfile from '../components/chat/ChatContactProfile.tsx';
import ChatProfileActions from '../components/chat/ChatProfileActions.tsx';

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

const ContactAvatar: React.FC<{
  contact?: { name?: string; phone?: string; photo?: string } | null;
  isDark: boolean;
  sizeClassName?: string;
}> = ({ contact, isDark, sizeClassName = 'h-12 w-12' }) => {
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

// Interface simplificada para mobile
interface Contact {
  id?: number;
  phone: string;
  name: string;
  photo: string;
  lastMessage?: string;
  timestamp?: string;
  timestampNumber: number;
  unreadCount: number;
  human_mode?: boolean;
  funnel_stage?: 'lead' | 'agendado' | 'compareceu' | 'faltou' | 'venda';
  funnel_status?: {
    lead_id?: number;
    agendamento_id?: number;
    comparecimento_id?: number;
    venda_id?: number;
    no_show_id?: number;
  };
  lead_id?: number;
  customer_id?: number;
  thumbnail_url?: string;
  source_id?: string;
  // Campos de tarefas
  pending_tasks_count?: number;
  next_task?: {
    id: number;
    title: string;
    scheduled_for: string;
    priority: 'low' | 'medium' | 'high' | 'urgent';
  };
}

const ChatMobile: React.FC = () => {
  const { isDark } = useTheme();
  // Estados - declarados primeiro
  const [contacts, setContacts] = useState<Map<string, Contact>>(new Map());
  const [selectedContact, setSelectedContact] = useState<Contact | null>(null);
  const [newMessage, setNewMessage] = useState('');
  const [companyInfo, setCompanyInfo] = useState<{name: string; logo_url: string | null}>({
    name: 'Empresa',
    logo_url: null
  });
  const [searchTerm, setSearchTerm] = useState('');
  const [showSearch, setShowSearch] = useState(false);
  const [showUnreadOnly, setShowUnreadOnly] = useState(false);
  const [currentView, setCurrentView] = useState<'list' | 'chat'>('list');
  const [showContactProfile, setShowContactProfile] = useState(false);
  const [profileActiveTab, setProfileActiveTab] = useState<LeadProfileTab>('overview');
  const [profileLead, setProfileLead] = useState<CrmLead | null>(null);
  const [isProfileLeadLoading, setIsProfileLeadLoading] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [isConvertingLead, setIsConvertingLead] = useState(false);

  // Aplicar reset de CSS para mobile ao montar
  React.useEffect(() => {
    // Salvar overflow original
    const originalOverflow = document.body.style.overflow;
    const originalPosition = document.body.style.position;

    // Prevenir scroll no body
    document.body.style.overflow = 'hidden';
    document.body.style.position = 'fixed';
    document.body.style.width = '100%';

    // Cleanup ao desmontar
    return () => {
      document.body.style.overflow = originalOverflow;
      document.body.style.position = originalPosition;
      document.body.style.width = '';
    };
  }, []);

  // Controlar visibilidade da navbar baseado na view
  React.useEffect(() => {
    const navbar = document.querySelector<HTMLElement>('[data-agentive-mobile-nav="true"]');
    if (navbar) {
      if (currentView === 'chat') {
        navbar.classList.add('hidden');
      } else {
        navbar.classList.remove('hidden');
      }
    }

    return () => {
      // Garantir que a navbar volte a aparecer quando sair do componente
      const navbar = document.querySelector<HTMLElement>('[data-agentive-mobile-nav="true"]');
      if (navbar) {
        navbar.classList.remove('hidden');
      }
    };
  }, [currentView]);

  // Refs removidos - não utilizados na versão simplificada

  // Funções auxiliares
  const normalizePhone = (phone: string): string => {
    if (!phone) return '';
    return phone.replace(/\D/g, '');
  };

  // Hook de mensagens
  const {
    messages,
    isLoading,
    hasMore,
    loadMoreMessages,
    sendMessage
  } = useOptimizedMessages(
    selectedContact ? normalizePhone(selectedContact.phone) : null,
    { pageSize: 30 }
  );

  const resolveContactLeadId = (contact?: Contact | null) => {
    if (!contact) return undefined;
    return contact.lead_id || contact.funnel_status?.lead_id;
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
      console.error('Erro ao converter contato em lead pelo chat mobile:', error);
      setProfileError(error?.response?.data?.detail || 'Erro ao converter contato em lead.');
    } finally {
      setIsConvertingLead(false);
    }
  };

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
  useEffect(() => {
    async function loadContacts() {
      try {
        const contactList = await getContacts();
        const cMap = new Map<string, Contact>();
        contactList.contacts.forEach((c) => {
          const normalizedPhone = normalizePhone(c.phone);
          cMap.set(normalizedPhone, {
            ...c,
            phone: normalizedPhone,
            lastMessage: normalizeContactLastMessage(c.lastMessage),
            unreadCount: c.unreadCount ?? 0
          });
        });
        setContacts(cMap);
      } catch (error) {
        console.error('Erro ao carregar contatos:', error);
      }
    }
    loadContacts();
  }, []);

  // WebSocket connection - COPIADO DO CHAT.TSX QUE FUNCIONA
  useEffect(() => {
    console.log('🔌 ChatMobile: Conectando WebSocket (lógica do Chat.tsx)...');
    unifiedWebSocketManager.connect();

    // Polling para atualizar contatos (mesmo que Chat.tsx)
    const contactsPolling = setInterval(async () => {
      try {
        const updatedContacts = await getContacts();
        const cMap = new Map<string, Contact>();

        updatedContacts.contacts.forEach((c) => {
          const normalizedPhone = normalizePhone(c.phone);
          cMap.set(normalizedPhone, {
            ...c,
            phone: normalizedPhone,
            lastMessage: normalizeContactLastMessage(c.lastMessage),
            unreadCount: c.unreadCount ?? 0
          });
        });

        setContacts(cMap);
      } catch (error) {
        console.error('Erro ao atualizar contatos:', error);
      }
    }, 15000);

    return () => {
      clearInterval(contactsPolling);
    };
  }, []);

  // Handler para contato selecionado - COPIADO DO CHAT.TSX
  useEffect(() => {
    if (!selectedContact) return;

    const normalizedPhone = normalizePhone(selectedContact.phone);
    console.log('📡 [ChatMobile] Inscrevendo no contato selecionado:', normalizedPhone);

    // Inscrever no tópico específico do contato selecionado
    unifiedWebSocketManager.subscribe(normalizedPhone);

    // Registrar handler para mensagens específicas deste contato
    const unsubscribeContact = unifiedWebSocketManager.onMessage(normalizedPhone, (data) => {
      console.log('📱 [ChatMobile] Mensagem WebSocket para contato selecionado:', {
        phone: data.phone,
        type: data.type,
        fromMe: data.fromMe
      });

      // O useOptimizedMessages automaticamente processa as mensagens
      // Aqui só atualizamos o estado do contato se necessário
      if (data.type === 'contact_mode_changed') {
        setSelectedContact(prev => prev ? {
          ...prev,
          human_mode: data.human_mode === true
        } : null);
      }
    });

    // Limpar quando mudar de contato ou desmontar
    return () => {
      unsubscribeContact();
      unifiedWebSocketManager.unsubscribe(normalizedPhone);
    };
  }, [selectedContact]);

  const handleToggleAtendimento = async () => {
    if (!selectedContact) return;

    try {
      const newHumanMode = !selectedContact.human_mode;

      if (selectedContact.human_mode) {
        await releaseContactToBot(selectedContact.phone);
      } else {
        await takeOverContact(selectedContact.phone);
      }

      setSelectedContact({
        ...selectedContact,
        human_mode: newHumanMode
      });

      setContacts(prev => {
        const newMap = new Map(prev);
        const contact = newMap.get(selectedContact.phone);
        if (contact) {
          newMap.set(selectedContact.phone, {
            ...contact,
            human_mode: newHumanMode
          });
        }
        return newMap;
      });
    } catch (error) {
      console.error('Erro ao alternar modo:', error);
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

  // Selecionar contato
  const selectContact = async (contact: Contact) => {
    const normalizedPhone = normalizePhone(contact.phone);

    try {
      await markContactAsRead(normalizedPhone);
    } catch (err) {
      console.error('Erro ao marcar contato como lido:', err);
    }

    setContacts((prev) => {
      const newMap = new Map(prev);
      if (prev.has(normalizedPhone)) {
        const updatedContact = {
          ...prev.get(normalizedPhone)!,
          unreadCount: 0
        };
        newMap.set(normalizedPhone, updatedContact);
      }
      return newMap;
    });

    setSelectedContact({ ...contact, unreadCount: 0 });
    setCurrentView('chat');

  };

  // Enviar mensagem
  const handleSendMessage = async () => {
    if (!newMessage.trim() || !selectedContact) return;

    try {
      const localMessageId = `local_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
      sendMessage(newMessage, 'text', localMessageId);
      await sendWhatsAppText({
        phone: selectedContact.phone,
        message: newMessage,
        localMessageId: localMessageId
      });
      setNewMessage('');
    } catch (error) {
      console.error('Erro ao enviar mensagem:', error);
    }
  };

  // Enviar áudio
  const handleAudioRecorded = async (audioBlob: Blob, recordedDuration: number) => {
    if (!selectedContact) return;

    try {
      const tempUrl = URL.createObjectURL(audioBlob);
      const reader = new FileReader();

      reader.onload = async (e) => {
        if (!e.target?.result) return;
        const base64Content = e.target.result.toString();
        const localMessageId = `local_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;

        sendMessage({
          url: tempUrl,
          mimeType: audioBlob.type,
          duration: recordedDuration
        }, 'audio', localMessageId);

        await sendWhatsAppAudio({
          phone: selectedContact.phone,
          audio: base64Content,
          localMessageId: localMessageId
        });
      };

      reader.readAsDataURL(audioBlob);
    } catch (err) {
      console.error('Erro ao processar áudio:', err);
    }
  };

  // Enviar NPS
  const handleSendNPS = async () => {
    if (!selectedContact) return;

    try {
      const question = 'Em uma escala de 1 a 5, como você avalia nosso atendimento?';

      // Enviar direto para o backend (que irá salvar na tabela messages)
      const response = await sendNPS({
        phone: selectedContact.phone,
        question,
        campaign_name: 'manual_chat'
      });

      // Adicionar mensagem NPS localmente para aparecer imediatamente
      if (response && typeof response === 'object' && 'nps_id' in response) {
        const npsMessageContent = {
          nps_data: {
            question: question,
            nps_id: response.nps_id,
            message_id: response.message_id,
            status: 'sent',
            campaign_name: 'manual_chat'
          }
        };
        sendMessage(npsMessageContent, 'nps', `local_nps_${Date.now()}`);
      }

      console.log('NPS enviado com sucesso para:', selectedContact.phone);
    } catch (error) {
      console.error('Erro ao enviar NPS:', error);
    }
  };

  // Filtrar contatos
  const filteredContacts = Array.from(contacts.values())
    .filter(c => c.timestampNumber && c.timestampNumber > 0)
    .filter(c => !showUnreadOnly || c.unreadCount > 0)
    .filter(c => {
      if (!searchTerm) return true;
      const search = searchTerm.toLowerCase();
      return c.name?.toLowerCase().includes(search) ||
             c.phone?.toLowerCase().includes(search);
    })
    .sort((a, b) => (b.timestampNumber || 0) - (a.timestampNumber || 0));

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

  // Renderizar lista de contatos
  const renderContactList = () => (
    <div className={cx('flex h-full flex-col overflow-hidden pb-[calc(7.25rem+env(safe-area-inset-bottom))]', isDark ? 'bg-brand text-white' : 'bg-brand-canvas text-brand')}>
      {/* Header da lista */}
      <div className={cx('flex items-center justify-between border-b px-4 py-3', isDark ? 'border-white/10 bg-white/[0.06]' : 'border-brand/10 bg-white')}>
        <h1 className="text-lg font-semibold">Chat ao vivo</h1>
        <button
          onClick={() => setShowSearch(!showSearch)}
          className={agentiveIconButtonClass(isDark)}
        >
          <Search className="w-5 h-5" />
        </button>
      </div>

      {/* Barra de busca */}
      {showSearch && (
        <div className={cx('border-b px-4 py-2', isDark ? 'border-white/10 bg-white/[0.06]' : 'border-brand/10 bg-white')}>
          <input
            type="text"
            placeholder="Buscar..."
            className={agentiveInputClass(isDark)}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            autoFocus
          />
        </div>
      )}

      {/* Filtros */}
      <div className={cx('grid grid-cols-2 gap-1 border-b px-4 py-2', isDark ? 'border-white/10 bg-white/[0.06]' : 'border-brand/10 bg-white')}>
        <button
          onClick={() => setShowUnreadOnly(false)}
          className={cx('rounded-xl px-3 py-2 text-sm font-semibold', !showUnreadOnly ? isDark ? 'bg-white text-brand' : 'bg-brand text-white' : isDark ? 'text-white/55' : 'text-brand/55')}
        >
          Todas
        </button>
        <button
          onClick={() => setShowUnreadOnly(true)}
          className={cx('rounded-xl px-3 py-2 text-sm font-semibold', showUnreadOnly ? isDark ? 'bg-white text-brand' : 'bg-brand text-white' : isDark ? 'text-white/55' : 'text-brand/55')}
        >
          Não lidas
        </button>
      </div>

      {/* Lista de contatos */}
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto overflow-x-hidden p-3">
        {filteredContacts.map((contact) => (
          <button
            key={contact.phone}
            onClick={() => selectContact(contact)}
            className={cx('flex w-full items-center gap-3 overflow-hidden rounded-2xl border p-3 text-left transition-colors', isDark ? 'border-white/10 bg-white/[0.05] hover:bg-white/[0.09]' : 'border-brand/10 bg-white hover:bg-brand-canvas')}
          >
            {/* Avatar */}
            <div className="relative flex-shrink-0">
              <ContactAvatar contact={contact} isDark={isDark} />
              {/* Indicador bot/humano */}
              <div className={cx('absolute -bottom-1 -right-1 h-5 w-5 rounded-full border-2', isDark ? 'border-brand' : 'border-white')}>
                {contact.human_mode ? (
                  <div className="w-full h-full bg-red-500 rounded-full flex items-center justify-center">
                    <UserIcon className="w-3 h-3 text-white" />
                  </div>
                ) : (
                  <div className="flex h-full w-full items-center justify-center rounded-full bg-brand">
                    <CpuIcon className="w-3 h-3 text-white" />
                  </div>
                )}
              </div>
            </div>

            {/* Conteúdo */}
            <div className="flex-1 min-w-0 text-left overflow-hidden">
              <div className="flex items-center justify-between gap-2">
                <p className="font-medium text-sm truncate flex-1">{contact.name}</p>
                <span className={cx('flex-shrink-0 text-xs', isDark ? 'text-white/45' : 'text-brand/45')}>
                  {formatChatTimestamp(contact.timestampNumber)}
                </span>
              </div>
              <p className={cx('mt-0.5 flex items-center overflow-hidden truncate text-xs', isDark ? 'text-white/50' : 'text-brand/50')}>
                {renderContactLastMessagePreview(contact.lastMessage) || 'Clique para conversar'}
              </p>
            </div>

            {/* Badges */}
            <div className="flex items-center gap-1 flex-shrink-0">
              {/* Badge de tarefas pendentes */}
              {contact.pending_tasks_count && contact.pending_tasks_count > 0 && (
                <div
                  className={`w-5 h-5 rounded-full text-white flex items-center justify-center text-[10px] font-bold ${
                    contact.next_task?.priority === 'urgent' ? 'bg-red-500' :
                    contact.next_task?.priority === 'high' ? 'bg-orange-500' :
                    'bg-brand'
                  }`}
                  title={`${contact.pending_tasks_count} tarefa(s) - ${contact.next_task?.title || ''}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    setSelectedContact(contact);
                    setProfileActiveTab('tasks');
                    setShowContactProfile(true);
                    loadLeadForContact(contact);
                  }}
                >
                  <CheckCircle2 className="w-3 h-3" />
                </div>
              )}

              {/* Badge não lidas */}
              {contact.unreadCount > 0 && (
                <div className="min-w-[20px] w-5 h-5 bg-green-500 rounded-full flex items-center justify-center">
                  <span className="text-[10px] text-white font-bold">
                    {contact.unreadCount > 9 ? '9+' : contact.unreadCount}
                  </span>
                </div>
              )}
            </div>
          </button>
        ))}
        {filteredContacts.length === 0 && (
          <AgentiveEmptyState
            icon={MessageSquare}
            title="Nenhuma conversa"
            description="Ajuste a busca ou veja todas as conversas."
          />
        )}
      </div>
    </div>
  );

  // Renderizar chat
  const renderChat = () => (
    <div className={cx('flex h-full flex-col overflow-hidden', isDark ? 'bg-brand text-white' : 'bg-brand-canvas text-brand')}>
      {/* Header do chat */}
      <div className={cx('flex items-center gap-3 border-b px-4 py-3', isDark ? 'border-white/10 bg-white/[0.06]' : 'border-brand/10 bg-white')}>
        <button
          onClick={() => setCurrentView('list')}
          className={agentiveIconButtonClass(isDark, 'neutral', '-ml-2')}
        >
          <ArrowLeft className="w-5 h-5" />
        </button>

        <button type="button" onClick={handleOpenContactProfile} className="flex min-w-0 flex-1 items-center gap-3 text-left">
          <ContactAvatar contact={selectedContact} isDark={isDark} sizeClassName="h-10 w-10" />
          <div className="flex-1 min-w-0">
            <p className="font-medium text-sm truncate">{selectedContact?.name}</p>
            <div className="mt-1 flex items-center gap-2">
              <span className={cx('truncate text-xs', isDark ? 'text-white/55' : 'text-brand/55')}>{selectedContact?.phone}</span>
            </div>
          </div>
        </button>

        <button type="button" onClick={handleOpenContactProfile} className={agentiveIconButtonClass(isDark, 'primary')} title="Abrir perfil">
          <PanelRightOpen className="h-5 w-5" />
        </button>
      </div>

      {/* Container com scroll que comporta mensagens */}
      <div className="flex-1 overflow-y-auto pb-[calc(5.75rem+env(safe-area-inset-bottom))]">
        <VirtualizedMessageList
          messages={messages}
          isLoading={isLoading}
          hasMore={hasMore}
          onLoadMore={loadMoreMessages}
        />
      </div>

      {/* Input de mensagem - fixo no bottom */}
      <div className={cx('fixed inset-x-0 bottom-0 z-50 border-t pb-[env(safe-area-inset-bottom)]', isDark ? 'border-white/10 bg-brand' : 'border-brand/10 bg-white')}>
        <OptimizedMessageInput
          onSendText={handleSendMessage}
          onSendAudio={handleAudioRecorded}
          onSendNPS={handleSendNPS}
          onSendImage={async (file) => {
            if (!selectedContact) return;

            const reader = new FileReader();
            reader.onload = async (e) => {
              if (!e.target?.result) return;
              const base64Content = e.target.result.toString();
              const localMessageId = `local_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;

              sendMessage({
                url: URL.createObjectURL(file),
                mimeType: file.type
              }, 'image', localMessageId);

              await sendWhatsAppImage({
                phone: selectedContact.phone,
                image: base64Content,
                localMessageId: localMessageId
              });
            };
            reader.readAsDataURL(file);
          }}
          onSendVideo={async (file) => {
            if (!selectedContact) return;

            const reader = new FileReader();
            reader.onload = async (e) => {
              if (!e.target?.result) return;
              const base64Content = e.target.result.toString();
              const localMessageId = `local_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;

              sendMessage({
                url: URL.createObjectURL(file),
                mimeType: file.type
              }, 'video', localMessageId);

              await sendWhatsAppVideo({
                phone: selectedContact.phone,
                video: base64Content,
                localMessageId: localMessageId
              });
            };
            reader.readAsDataURL(file);
          }}
          disabled={!selectedContact}
          placeholder="Digite.."
          value={newMessage}
          onChange={setNewMessage}
          extraControl={composerModeButton}
          extraControlLabel={selectedContact?.human_mode ? 'Devolver para IA' : 'Assumir atendimento'}
          actionsMode="menu"
        />
      </div>
    </div>
  );


  return (
    <div className="fixed inset-0 overflow-hidden">
      {currentView === 'list' ? renderContactList() : renderChat()}

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
  );
};

export default ChatMobile;
