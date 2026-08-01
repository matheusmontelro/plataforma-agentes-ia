import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  Calendar,
  CalendarClock,
  CalendarPlus,
  Check,
  CheckCircle2,
  Clock,
  ExternalLink,
  FileText,
  Globe,
  Loader2,
  Mail,
  MapPin,
  MessageSquare,
  Pencil,
  Phone,
  RefreshCw,
  Settings,
  User,
  UserX,
  X,
} from 'lucide-react';
import { crmApi, LeadCustomField } from '../services/crmApi';
import {
  AgendamentoResponse,
  atualizarAgendamento,
  listarAgendamentos,
  marcarNoShowAgendamento,
} from '../services/api';
import { calendarApi, type Agenda } from '../services/calendar_api.ts';
import AppointmentBookingModal from './AppointmentBookingModal.tsx';
import ManageAttributesModal from './ManageAttributesModal';
import ChatProfileWorkModal, { type ChatProfileWorkMode } from './chat/ChatProfileWorkModal.tsx';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AgentiveAlert,
  AgentiveConfirmModal,
} from './AgentiveUI.tsx';
import './crm/LeadInspector/LeadInspector.css';
import {
  CrmModernEmptyState,
  crmModernBadgeClass,
  crmModernIconButtonClass,
  crmModernInputClass,
  crmModernPanelClass,
  crmModernPrimaryButtonClass,
  crmModernSecondaryButtonClass,
} from './crm/CRMModern/CRMModernUI.tsx';

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

interface CustomValue {
  field_key: string;
  field_name: string;
  value: any;
}

export interface LeadProfileProps {
  activeTab?: LeadProfileTab;
  contextActions?: React.ReactNode;
  contextPanel?: React.ReactNode;
  isOpen: boolean;
  onActiveTabChange?: (tab: LeadProfileTab) => void;
  onClose: () => void;
  onLeadUpdate?: () => void;
  onPendingTasksChange?: (pendingCount: number) => void;
  lead: {
    id: number;
    name: string;
    phone: string;
    email?: string;
    thumbnailUrl?: string;
    columnId: string;
    stageName?: string;
    date: Date | string;
    sourceId?: string;
    custom_values?: CustomValue[];
    address?: string;
    website?: string;
  };
}

export type LeadProfileTab = 'overview' | 'activity' | 'attributes' | ChatProfileWorkMode;

const getInitials = (name?: string) => {
  const parts = (name || '').trim().split(/\s+/).filter(Boolean);
  return (parts.slice(0, 2).map(part => part[0]).join('') || 'LD').toUpperCase();
};

const LeadProfileAvatar: React.FC<{ isDark: boolean; name?: string; thumbnailUrl?: string }> = ({
  isDark,
  name,
  thumbnailUrl,
}) => {
  const [imageFailed, setImageFailed] = useState(false);

  useEffect(() => {
    setImageFailed(false);
  }, [thumbnailUrl]);

  const canShowImage = Boolean(thumbnailUrl && !imageFailed);

  return (
    <span className="crm-lead-inspector__avatar">
      {canShowImage ? (
        <img
          src={thumbnailUrl}
          alt={name || 'Lead'}
          className="h-full w-full object-cover"
          onError={() => setImageFailed(true)}
        />
      ) : (
        getInitials(name)
      )}
    </span>
  );
};

const formatDate = (date: Date | string) => {
  const parsed = date instanceof Date ? date : new Date(date);
  if (Number.isNaN(parsed.getTime())) return 'Sem data';
  return parsed.toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
};

const getCountryFromPhone = (phone?: string) => {
  const digits = (phone || '').replace(/\D/g, '');
  if (digits.startsWith('55')) return 'Brasil';
  if (digits.startsWith('1')) return 'Estados Unidos';
  if (digits.startsWith('54')) return 'Argentina';
  return 'Não identificado';
};

const normalizePhone = (phone?: string | null) => (phone || '').replace(/\D/g, '');

const normalizeExternalHref = (value?: string | null) => {
  const trimmed = (value || '').trim();
  if (!trimmed) return '#';
  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
};

const resolveNumericStorageValue = (...keys: string[]) => {
  for (const key of keys) {
    const rawValue = localStorage.getItem(key) || sessionStorage.getItem(key);
    const parsed = Number(rawValue);
    if (Number.isFinite(parsed) && parsed > 0) return parsed;
  }
  return null;
};

const toDateTimeLocalValue = (value?: string | null) => {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';

  const offsetDate = new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60000);
  return offsetDate.toISOString().slice(0, 16);
};

const sortAppointments = (appointments: AgendamentoResponse[]) => {
  const now = Date.now();
  return [...appointments].sort((a, b) => {
    const aTime = a.consulta_data ? new Date(a.consulta_data).getTime() : 0;
    const bTime = b.consulta_data ? new Date(b.consulta_data).getTime() : 0;
    const aFuture = aTime >= now;
    const bFuture = bTime >= now;

    if (aFuture !== bFuture) return aFuture ? -1 : 1;
    if (aFuture && bFuture) return aTime - bTime;
    return bTime - aTime;
  });
};

const appointmentStatusLabel = (status?: string | null) => {
  const normalized = (status || 'SCHEDULED').toUpperCase();
  const labels: Record<string, string> = {
    CANCELED: 'Cancelado',
    CANCELLED: 'Cancelado',
    CANCELADO: 'Cancelado',
    CONFIRMED: 'Confirmado',
    NO_SHOW: 'Falta',
    SCHEDULED: 'Agendado',
  };

  return labels[normalized] || normalized;
};

const appointmentStatusClass = (isDark: boolean, status?: string | null) => {
  void isDark;
  const normalized = (status || 'SCHEDULED').toUpperCase();

  if (normalized === 'NO_SHOW') {
    return 'crm-appointment-status crm-appointment-status--danger';
  }
  if (normalized === 'CONFIRMED') {
    return 'crm-appointment-status crm-appointment-status--success';
  }
  if (['CANCELED', 'CANCELLED', 'CANCELADO'].includes(normalized)) {
    return 'crm-appointment-status';
  }

  return 'crm-appointment-status crm-appointment-status--active';
};

export default function LeadProfile({
  activeTab: controlledActiveTab,
  contextActions,
  contextPanel,
  isOpen,
  onActiveTabChange,
  onClose,
  onLeadUpdate,
  onPendingTasksChange,
  lead,
}: LeadProfileProps) {
  const { isDark } = useTheme();
  const [internalActiveTab, setInternalActiveTab] = useState<LeadProfileTab>('overview');
  const [customFields, setCustomFields] = useState<LeadCustomField[]>([]);
  const [customValues, setCustomValues] = useState<CustomValue[]>(lead.custom_values || []);
  const [showManageAttributes, setShowManageAttributes] = useState(false);
  const [editingFieldId, setEditingFieldId] = useState<number | null>(null);
  const [editingValue, setEditingValue] = useState('');
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [appointments, setAppointments] = useState<AgendamentoResponse[]>([]);
  const [appointmentsLoading, setAppointmentsLoading] = useState(false);
  const [appointmentsError, setAppointmentsError] = useState<string | null>(null);
  const [agendas, setAgendas] = useState<Agenda[]>([]);
  const [agendasLoading, setAgendasLoading] = useState(false);
  const [appointmentActionId, setAppointmentActionId] = useState<number | null>(null);
  const [showBookingModal, setShowBookingModal] = useState(false);
  const [noShowTarget, setNoShowTarget] = useState<AgendamentoResponse | null>(null);
  const [noShowObservation, setNoShowObservation] = useState('');
  const [rescheduleTarget, setRescheduleTarget] = useState<AgendamentoResponse | null>(null);
  const [rescheduleDate, setRescheduleDate] = useState('');
  const [rescheduleAgendaId, setRescheduleAgendaId] = useState('');

  const mutedTextClass = 'crm-modern-muted';
  const softSurfaceClass = 'crm-modern-subtle';
  const activeTab = controlledActiveTab || internalActiveTab;

  const changeActiveTab = useCallback((tab: LeadProfileTab) => {
    setInternalActiveTab(tab);
    onActiveTabChange?.(tab);
  }, [onActiveTabChange]);

  const fetchFields = useCallback(async () => {
    try {
      const fields = await crmApi.getCustomFields();
      setCustomFields(fields.sort((a, b) => a.display_order - b.display_order));
    } catch (error) {
      console.error('Erro ao carregar atributos do lead:', error);
      setFeedback({ type: 'error', message: 'Não foi possível carregar os atributos personalizados.' });
    }
  }, []);

  const fetchAppointments = useCallback(async () => {
    setAppointmentsLoading(true);
    setAppointmentsError(null);

    try {
      const items = await listarAgendamentos();
      const leadPhone = normalizePhone(lead.phone);
      const filtered = items.filter((appointment) => {
        if (Number(appointment.lead_id) === Number(lead.id)) return true;

        const appointmentPhone = normalizePhone(appointment.phone);
        return Boolean(leadPhone && appointmentPhone && leadPhone === appointmentPhone);
      });

      setAppointments(sortAppointments(filtered));
    } catch (error) {
      console.error('Erro ao carregar agendamentos do lead:', error);
      setAppointments([]);
      setAppointmentsError('Não foi possível carregar os agendamentos deste lead.');
    } finally {
      setAppointmentsLoading(false);
    }
  }, [lead.id, lead.phone]);

  const fetchAgendas = useCallback(async () => {
    setAgendasLoading(true);
    try {
      const items = await calendarApi.listAgendas();
      setAgendas(items);
    } catch (error) {
      console.error('Erro ao carregar agendas no perfil do lead:', error);
      setAgendas([]);
    } finally {
      setAgendasLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      fetchFields();
      fetchAppointments();
      fetchAgendas();
      setCustomValues(lead.custom_values || []);
      if (!controlledActiveTab) {
        setInternalActiveTab('overview');
      }
      setFeedback(null);
      setAppointmentsError(null);
      setShowBookingModal(false);
      setNoShowTarget(null);
      setRescheduleTarget(null);
    }
  }, [controlledActiveTab, fetchAgendas, fetchAppointments, fetchFields, isOpen, lead.custom_values, lead.id]);

  useEffect(() => {
    if (!isOpen) return undefined;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [isOpen]);

  const getCustomValue = useCallback(
    (fieldKey: string) => customValues.find(value => value.field_key === fieldKey)?.value,
    [customValues]
  );

  const handleSaveCustomValue = useCallback(async (field: LeadCustomField) => {
    try {
      await crmApi.updateLeadCustomValues(lead.id, [
        { custom_field_id: field.id, value: editingValue },
      ]);

      setCustomValues(prev => {
        const exists = prev.some(value => value.field_key === field.field_key);
        if (exists) {
          return prev.map(value => value.field_key === field.field_key ? { ...value, value: editingValue } : value);
        }
        return [...prev, { field_key: field.field_key, field_name: field.field_name, value: editingValue }];
      });
      setEditingFieldId(null);
      setEditingValue('');
      setFeedback({ type: 'success', message: 'Atributo atualizado.' });
      onLeadUpdate?.();
    } catch (error) {
      console.error('Erro ao salvar atributo do lead:', error);
      setFeedback({ type: 'error', message: 'Erro ao salvar atributo. Tente novamente.' });
    }
  }, [editingValue, lead.id, onLeadUpdate]);

  const startEditing = (fieldId: number, currentValue: any) => {
    setEditingFieldId(fieldId);
    setEditingValue(currentValue !== null && currentValue !== undefined ? String(currentValue) : '');
  };

  const openNoShowModal = (appointment: AgendamentoResponse) => {
    setNoShowTarget(appointment);
    setNoShowObservation('');
  };

  const openRescheduleModal = (appointment: AgendamentoResponse) => {
    setRescheduleTarget(appointment);
    setRescheduleDate(toDateTimeLocalValue(appointment.consulta_data));
    setRescheduleAgendaId(appointment.agenda_id ? String(appointment.agenda_id) : '');
  };

  const handleConfirmNoShow = useCallback(async () => {
    if (!noShowTarget) return;

    const clientId = resolveNumericStorageValue('client_id');
    const companyId = resolveNumericStorageValue('company_id', 'clinic_id');
    if (!clientId || !companyId) {
      setFeedback({ type: 'error', message: 'Sessão incompleta para atualizar o agendamento.' });
      return;
    }

    setAppointmentActionId(noShowTarget.id);
    try {
      await marcarNoShowAgendamento(clientId, companyId, noShowTarget.id, {
        observacao: noShowObservation.trim() || 'Marcado como falta pelo CRM.',
      });
      setNoShowTarget(null);
      setNoShowObservation('');
      setFeedback({ type: 'success', message: 'Agendamento marcado como falta.' });
      await fetchAppointments();
      onLeadUpdate?.();
    } catch (error) {
      console.error('Erro ao marcar falta no agendamento:', error);
      setFeedback({ type: 'error', message: 'Não foi possível marcar este agendamento como falta.' });
    } finally {
      setAppointmentActionId(null);
    }
  }, [fetchAppointments, noShowObservation, noShowTarget, onLeadUpdate]);

  const handleConfirmReschedule = useCallback(async () => {
    if (!rescheduleTarget) return;

    if (!rescheduleDate) {
      setFeedback({ type: 'error', message: 'Informe a nova data e hora do agendamento.' });
      return;
    }

    const clientId = resolveNumericStorageValue('client_id');
    const companyId = resolveNumericStorageValue('company_id', 'clinic_id');
    if (!clientId || !companyId) {
      setFeedback({ type: 'error', message: 'Sessão incompleta para reagendar.' });
      return;
    }

    setAppointmentActionId(rescheduleTarget.id);
    try {
      await atualizarAgendamento(
        clientId,
        companyId,
        rescheduleTarget.id,
        {
          agenda_id: rescheduleAgendaId ? Number(rescheduleAgendaId) : undefined,
          consulta_data: rescheduleDate,
        },
        ''
      );
      setRescheduleTarget(null);
      setRescheduleDate('');
      setRescheduleAgendaId('');
      setFeedback({ type: 'success', message: 'Agendamento reagendado.' });
      await fetchAppointments();
      onLeadUpdate?.();
    } catch (error) {
      console.error('Erro ao reagendar:', error);
      setFeedback({ type: 'error', message: 'Não foi possível reagendar este agendamento.' });
    } finally {
      setAppointmentActionId(null);
    }
  }, [fetchAppointments, onLeadUpdate, rescheduleAgendaId, rescheduleDate, rescheduleTarget]);

  const handleAppointmentCreated = useCallback(async () => {
    setShowBookingModal(false);
    setFeedback({ type: 'success', message: 'Agendamento criado.' });
    await fetchAppointments();
    onLeadUpdate?.();
  }, [fetchAppointments, onLeadUpdate]);

  const profileEvents = useMemo(() => {
    const events = [
      {
        id: 'created',
        icon: User,
        title: 'Lead criado',
        description: `Registro entrou no CRM em ${formatDate(lead.date)}.`,
      },
    ];

    if (lead.sourceId) {
      events.push({
        id: 'source',
        icon: Globe,
        title: 'Origem registrada',
        description: `Lead atribuído à mídia ${lead.sourceId}.`,
      });
    }

    if (customValues.length > 0) {
      events.push({
        id: 'attributes',
        icon: FileText,
        title: 'Atributos disponíveis',
        description: `${customValues.length} campo(s) personalizado(s) vinculados ao perfil.`,
      });
    }

    return events;
  }, [customValues.length, lead.date, lead.sourceId]);

  if (!isOpen) return null;

  const company = getCustomValue('company') || getCustomValue('empresa') || '-';
  const createdAt = formatDate(lead.date);

  return (
    <div className={cx('crm-lead-inspector-root fixed inset-0 z-[90] flex justify-end', isDark && 'crm-lead-inspector-root--dark')}>
      <div className="crm-lead-inspector__backdrop" onClick={onClose} />

      <section className="crm-lead-inspector" role="dialog" aria-modal="true" aria-label={`Perfil de ${lead.name || 'lead'}`}>
        <header className="crm-lead-inspector__header">
          <div className="crm-lead-inspector__header-row">
            <div className="crm-lead-inspector__identity">
              <LeadProfileAvatar isDark={isDark} name={lead.name} thumbnailUrl={lead.thumbnailUrl} />
              <div className="min-w-0">
                <p className="crm-lead-inspector__eyebrow">Perfil do lead</p>
                <h2 className="crm-lead-inspector__name">{lead.name || 'Lead sem nome'}</h2>
                <div className="crm-lead-inspector__subline">
                  <span>Lead #{lead.id}</span>
                </div>
              </div>
            </div>

            <div className="crm-lead-inspector__actions">
              {contextActions}
              {lead.phone && (
                <a
                  href={`tel:${lead.phone}`}
                  className={cx(crmModernIconButtonClass(isDark, 'success', 'crm-action-icon'), 'crm-lead-inspector__action')}
                  aria-label="Ligar para o lead"
                  title="Ligar"
                >
                  <Phone className="h-4 w-4" />
                </a>
              )}
              {lead.email && (
                <a
                  href={`mailto:${lead.email}`}
                  className={cx(crmModernIconButtonClass(isDark, 'primary', 'crm-action-icon'), 'crm-lead-inspector__action crm-lead-inspector__action--optional')}
                  aria-label="Enviar email para o lead"
                  title="Email"
                >
                  <Mail className="h-4 w-4" />
                </a>
              )}
              <button
                type="button"
                onClick={() => setShowManageAttributes(true)}
                className={cx(crmModernIconButtonClass(isDark, 'neutral', 'crm-action-icon'), 'crm-lead-inspector__action crm-lead-inspector__action--optional')}
                aria-label="Gerenciar atributos"
                title="Atributos"
              >
                <Settings className="h-4 w-4" />
              </button>
              <button type="button" onClick={onClose} className={cx(crmModernIconButtonClass(isDark, 'neutral', 'crm-action-icon'), 'crm-lead-inspector__action')} aria-label="Fechar perfil" title="Fechar">
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div className="crm-lead-inspector__meta">
            <span className={crmModernBadgeClass(isDark, true)}>
              <CheckCircle2 className="h-3 w-3" />
              {lead.stageName || lead.columnId || 'Sem etapa'}
            </span>
            <span className={crmModernBadgeClass(isDark)}>
              <Phone className="h-3 w-3" />
              {lead.phone || 'Sem telefone'}
            </span>
            {lead.sourceId && (
              <span className={crmModernBadgeClass(isDark)}>
                <Globe className="h-3 w-3" />
                {lead.sourceId}
              </span>
            )}
            <span className={crmModernBadgeClass(isDark)}>
              <Calendar className="h-3 w-3" />
              {createdAt}
            </span>
          </div>
        </header>

        <div className="crm-lead-inspector__tabs" role="tablist" aria-label="Seções do perfil">
          {[
            { id: 'overview' as const, label: 'Resumo' },
            { id: 'activity' as const, label: 'Atividade' },
            { id: 'attributes' as const, label: 'Campos' },
            { id: 'notes' as const, label: 'Anotações' },
            { id: 'tasks' as const, label: 'Tarefas' },
          ].map(tab => (
            <button
              key={tab.id}
              type="button"
              onClick={() => changeActiveTab(tab.id)}
              className={cx(
                'crm-lead-inspector__tab',
                activeTab === tab.id && 'crm-lead-inspector__tab--active'
              )}
              role="tab"
              aria-selected={activeTab === tab.id}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="crm-lead-inspector__body custom-scrollbar">
          <div className="crm-lead-inspector__content">
            <main className="min-w-0 space-y-3">
              {feedback && (
                <AgentiveAlert
                  className="crm-modern-alert"
                  title={feedback.type === 'success' ? 'Atualizado' : 'Erro'}
                  variant={feedback.type}
                  onClose={() => setFeedback(null)}
                >
                  {feedback.message}
                </AgentiveAlert>
              )}

              {activeTab === 'overview' && (
                <div className="crm-lead-inspector__overview">
                  <InfoCard title="Resumo operacional" icon={CheckCircle2} isDark={isDark}>
                    <div className="crm-lead-inspector__metrics">
                      <Metric label="Origem" value={lead.sourceId || 'Sistema'} isDark={isDark} />
                      <Metric label="Campos" value={customFields.length.toString()} isDark={isDark} />
                      <Metric label="Telefone" value={lead.phone || '-'} isDark={isDark} />
                      <Metric label="Agendamentos" value={appointments.length.toString()} isDark={isDark} />
                    </div>
                  </InfoCard>

                  <div className="crm-lead-inspector__overview-grid">
                    <InfoCard title="Dados comerciais" icon={User} isDark={isDark}>
                      <DetailRow label="Status" value={lead.stageName || lead.columnId || '-'} isDark={isDark} />
                      <DetailRow label="Empresa" value={company} isDark={isDark} />
                      <DetailRow label="Localização" value={getCountryFromPhone(lead.phone)} isDark={isDark} />
                      <DetailRow label="Site" value={lead.website || '-'} isDark={isDark} />
                      <DetailRow label="Criado em" value={createdAt} isDark={isDark} />
                    </InfoCard>

                    <InfoCard title="Contato" icon={Phone} isDark={isDark}>
                      <DetailRow label="Nome" value={lead.name || '-'} isDark={isDark} />
                      <DetailRow label="Telefone" value={lead.phone || '-'} isDark={isDark} isMono />
                      <DetailRow label="Email" value={lead.email || '-'} isDark={isDark} />
                      <DetailRow label="Endereço" value={lead.address || '-'} isDark={isDark} />
                    </InfoCard>
                  </div>

                  <InfoCard title="Próximo contato" icon={MessageSquare} isDark={isDark}>
                    <div className={cx('crm-lead-inspector__next-contact text-sm', softSurfaceClass)}>
                      <p className="font-semibold">Sem tarefa aberta</p>
                      <p className={cx('mt-1 text-xs leading-relaxed', mutedTextClass)}>
                        Use a aba de tarefas para registrar o próximo passo deste lead.
                      </p>
                    </div>
                  </InfoCard>

                  {contextPanel && <div className="crm-lead-inspector__context-panel">{contextPanel}</div>}

                  <LeadAppointmentsCard
                    actionId={appointmentActionId}
                    agendas={agendas}
                    appointments={appointments}
                    error={appointmentsError}
                    isDark={isDark}
                    loading={appointmentsLoading}
                    onCreate={() => setShowBookingModal(true)}
                    onNoShow={openNoShowModal}
                    onRefresh={fetchAppointments}
                    onReschedule={openRescheduleModal}
                  />
                </div>
              )}

              {activeTab === 'activity' && (
                <InfoCard title="Linha do tempo" icon={Calendar} isDark={isDark}>
                  <div className="space-y-4">
                    {profileEvents.map(event => (
                      <TimelineEvent
                        key={event.id}
                        icon={event.icon}
                        title={event.title}
                        description={event.description}
                        isDark={isDark}
                      />
                    ))}
                  </div>
                </InfoCard>
              )}

              {activeTab === 'attributes' && (
                <InfoCard
                  title="Atributos personalizados"
                  icon={FileText}
                  isDark={isDark}
                  action={(
                    <button type="button" onClick={() => setShowManageAttributes(true)} className={crmModernSecondaryButtonClass(isDark, 'px-2.5 py-1.5 text-xs')}>
                      <Settings className="h-3.5 w-3.5" />
                      Gerenciar
                    </button>
                  )}
                >
                  {customFields.length > 0 ? (
                    <div className="crm-lead-inspector__attributes">
                      {customFields.map(field => {
                        const value = getCustomValue(field.field_key);
                        const isEditing = editingFieldId === field.id;

                        return (
                          <div key={field.id} className="crm-lead-inspector__attribute">
                            <span className={cx('text-xs font-semibold', mutedTextClass)}>{field.field_name}</span>
                            {isEditing ? (
                              <div className="flex min-w-0 items-center gap-2">
                                <input
                                  type={field.field_type === 'number' ? 'number' : 'text'}
                                  className={crmModernInputClass(isDark, 'min-w-0 flex-1')}
                                  value={editingValue}
                                  onChange={(event) => setEditingValue(event.target.value)}
                                  onKeyDown={(event) => {
                                    if (event.key === 'Enter') handleSaveCustomValue(field);
                                    if (event.key === 'Escape') setEditingFieldId(null);
                                  }}
                                  autoFocus
                                />
                                <button type="button" onClick={() => handleSaveCustomValue(field)} className={crmModernIconButtonClass(isDark, 'success', 'crm-action-icon')} aria-label="Salvar atributo" title="Salvar atributo">
                                  <Check className="h-4 w-4" />
                                </button>
                                <button type="button" onClick={() => setEditingFieldId(null)} className={crmModernIconButtonClass(isDark, 'neutral', 'crm-action-icon')} aria-label="Cancelar edição" title="Cancelar edição">
                                  <X className="h-4 w-4" />
                                </button>
                              </div>
                            ) : (
                              <button
                                type="button"
                                onClick={() => startEditing(field.id, value)}
                                className="crm-lead-inspector__attribute-value"
                              >
                                <span className={cx('min-w-0 truncate', value ? '' : 'italic')}>
                                  {value !== undefined && value !== null && value !== '' ? String(value) : '-'}
                                </span>
                                <Pencil className="h-3.5 w-3.5 shrink-0" />
                              </button>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <CrmModernEmptyState
                      icon={AlertCircle}
                      title="Nenhum atributo definido"
                      description="Crie atributos personalizados para enriquecer o perfil comercial do lead."
                      action={(
                        <button type="button" onClick={() => setShowManageAttributes(true)} className={crmModernPrimaryButtonClass()}>
                          Gerenciar atributos
                        </button>
                      )}
                    />
                  )}
                </InfoCard>
              )}

              {(activeTab === 'notes' || activeTab === 'tasks') && (
                <ChatProfileWorkModal
                  className="min-w-0"
                  contactId={lead.phone}
                  contactName={lead.name}
                  contactPhone={lead.phone}
                  embedded
                  isOpen={isOpen}
                  mode={activeTab}
                  onModeChange={changeActiveTab}
                  onPendingTasksChange={onPendingTasksChange}
                />
              )}
            </main>
          </div>
        </div>
      </section>

      <AgentiveConfirmModal
        appearance="modern"
        confirmText="Marcar falta"
        isLoading={appointmentActionId === noShowTarget?.id}
        isOpen={Boolean(noShowTarget)}
        message="O status do agendamento será atualizado e os fluxos ligados a falta poderão ser disparados."
        onClose={() => {
          if (appointmentActionId) return;
          setNoShowTarget(null);
          setNoShowObservation('');
        }}
        onConfirm={handleConfirmNoShow}
        title="Marcar falta?"
        variant="danger"
      >
        <div className="space-y-3">
          <DetailRow
            isDark={isDark}
            label="Data"
            value={noShowTarget?.consulta_data_display || (noShowTarget?.consulta_data ? formatDate(noShowTarget.consulta_data) : '-')}
          />
          <div>
            <label className={cx('mb-1.5 block text-xs font-semibold', mutedTextClass)}>Observação</label>
            <textarea
              className={crmModernInputClass(isDark, 'min-h-24 resize-y')}
              value={noShowObservation}
              onChange={(event) => setNoShowObservation(event.target.value)}
              placeholder="Opcional"
            />
          </div>
        </div>
      </AgentiveConfirmModal>

      <AgentiveConfirmModal
        appearance="modern"
        confirmText="Salvar reagendamento"
        isLoading={appointmentActionId === rescheduleTarget?.id}
        isOpen={Boolean(rescheduleTarget)}
        message="A confirmação e os eventos do FlowBuilder serão recalculados pela agenda ao salvar."
        onClose={() => {
          if (appointmentActionId) return;
          setRescheduleTarget(null);
          setRescheduleDate('');
          setRescheduleAgendaId('');
        }}
        onConfirm={handleConfirmReschedule}
        title="Reagendar"
        variant="warning"
      >
        <div className="space-y-3">
          <div>
            <label className={cx('mb-1.5 block text-xs font-semibold', mutedTextClass)}>Nova data e hora</label>
            <input
              type="datetime-local"
              className={crmModernInputClass(isDark)}
              value={rescheduleDate}
              onChange={(event) => setRescheduleDate(event.target.value)}
            />
          </div>

          <div>
            <label className={cx('mb-1.5 block text-xs font-semibold', mutedTextClass)}>Agenda</label>
            <select
              className={crmModernInputClass(isDark)}
              disabled={agendasLoading}
              value={rescheduleAgendaId}
              onChange={(event) => setRescheduleAgendaId(event.target.value)}
            >
              <option value="">{agendasLoading ? 'Carregando agendas...' : 'Manter sem agenda definida'}</option>
              {agendas.map((agenda) => (
                <option key={agenda.id} value={agenda.id}>
                  {agenda.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </AgentiveConfirmModal>

      <AppointmentBookingModal
        agendas={agendas}
        defaultAgendaId={agendas[0]?.id ?? null}
        isOpen={showBookingModal}
        lockedLead={{
          leadId: lead.id,
          name: lead.name,
          phone: lead.phone,
          sourceId: lead.sourceId,
        }}
        onClose={() => setShowBookingModal(false)}
        onCreated={handleAppointmentCreated}
        title="Agendar lead"
        visualVariant="crm-modern"
      />

      <ManageAttributesModal
        isOpen={showManageAttributes}
        onClose={() => setShowManageAttributes(false)}
        onAttributesChanged={fetchFields}
      />
    </div>
  );
}

function LeadAppointmentsCard({
  actionId,
  agendas,
  appointments,
  error,
  isDark,
  loading,
  onCreate,
  onNoShow,
  onRefresh,
  onReschedule,
}: {
  actionId: number | null;
  agendas: Agenda[];
  appointments: AgendamentoResponse[];
  error: string | null;
  isDark: boolean;
  loading: boolean;
  onCreate: () => void;
  onNoShow: (appointment: AgendamentoResponse) => void;
  onRefresh: () => void;
  onReschedule: (appointment: AgendamentoResponse) => void;
}) {
  const mutedTextClass = 'crm-modern-muted';
  const agendaById = new Map(agendas.map((agenda) => [Number(agenda.id), agenda.name]));

  return (
    <InfoCard
      title="Agendamentos"
      icon={CalendarClock}
      isDark={isDark}
      action={(
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onCreate}
            className={crmModernSecondaryButtonClass(isDark, 'px-2.5 py-1.5 text-xs')}
          >
            <CalendarPlus className="h-3.5 w-3.5" />
            Agendar
          </button>
          <button
            type="button"
            onClick={onRefresh}
            className={crmModernIconButtonClass(isDark, 'primary', 'crm-action-icon')}
            aria-label="Atualizar agendamentos"
            title="Atualizar agendamentos"
            disabled={loading}
          >
            <RefreshCw className={cx('h-4 w-4', loading && 'animate-spin')} />
          </button>
        </div>
      )}
    >
      {loading ? (
        <div className="crm-appointments-loading">
          <Loader2 className="h-4 w-4 animate-spin" />
          Carregando agendamentos
        </div>
      ) : error ? (
        <AgentiveAlert className="crm-modern-alert" title="Erro" variant="error">
          {error}
        </AgentiveAlert>
      ) : appointments.length === 0 ? (
        <CrmModernEmptyState
          icon={CalendarClock}
          title="Nenhum agendamento"
          description="Este lead ainda não tem agendamentos vinculados."
          action={(
            <button type="button" onClick={onCreate} className={crmModernPrimaryButtonClass()}>
              <CalendarPlus className="h-4 w-4" />
              Agendar lead
            </button>
          )}
        />
      ) : (
        <div className="crm-appointments-list">
          {appointments.map((appointment) => {
            const normalizedStatus = (appointment.status || 'SCHEDULED').toUpperCase();
            const isNoShow = normalizedStatus === 'NO_SHOW';
            const isCanceled = ['CANCELED', 'CANCELLED', 'CANCELADO'].includes(normalizedStatus);
            const agendaName = appointment.agenda_id ? agendaById.get(Number(appointment.agenda_id)) : null;
            const dateLabel = appointment.consulta_data_display || (appointment.consulta_data ? formatDate(appointment.consulta_data) : 'Sem data');
            const isActionLoading = actionId === appointment.id;

            return (
              <article
                key={appointment.id}
                className="crm-lead-inspector__appointment"
              >
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="truncate text-sm font-semibold">{dateLabel}</p>
                      <span className={appointmentStatusClass(isDark, appointment.status)}>
                        {appointmentStatusLabel(appointment.status)}
                      </span>
                    </div>
                    <div className={cx('mt-2 flex flex-wrap items-center gap-2 text-xs', mutedTextClass)}>
                      <span className={crmModernBadgeClass(isDark)}>
                        <Clock className="h-3 w-3" />
                        {agendaName || 'Agenda padrão'}
                      </span>
                      {appointment.interesse && (
                        <span className={crmModernBadgeClass(isDark)}>{appointment.interesse}</span>
                      )}
                      {appointment.endereco && (
                        <span className={crmModernBadgeClass(isDark, false, 'max-w-full')}>
                          <MapPin className="h-3 w-3" />
                          <span className="truncate">{appointment.endereco}</span>
                        </span>
                      )}
                      {appointment.local_link && (
                        <a
                          href={normalizeExternalHref(appointment.local_link)}
                          target="_blank"
                          rel="noreferrer"
                          className={crmModernBadgeClass(isDark)}
                        >
                          <ExternalLink className="h-3 w-3" />
                          Abrir local
                        </a>
                      )}
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2 sm:justify-end">
                    <button
                      type="button"
                      onClick={() => onReschedule(appointment)}
                      className={crmModernSecondaryButtonClass(isDark, 'px-2.5 py-1.5 text-xs')}
                      disabled={isActionLoading || isCanceled}
                    >
                      <RefreshCw className="h-3.5 w-3.5" />
                      Reagendar
                    </button>
                    <button
                      type="button"
                      onClick={() => onNoShow(appointment)}
                      className={crmModernSecondaryButtonClass(isDark, 'px-2.5 py-1.5 text-xs')}
                      disabled={isActionLoading || isNoShow || isCanceled}
                    >
                      <UserX className="h-3.5 w-3.5" />
                      Falta
                    </button>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </InfoCard>
  );
}

function InfoCard({
  action,
  children,
  icon: Icon,
  isDark,
  title,
}: {
  action?: React.ReactNode;
  children: React.ReactNode;
  icon: React.ComponentType<{ className?: string }>;
  isDark: boolean;
  title: string;
}) {
  return (
    <section className={cx(crmModernPanelClass(isDark, 'overflow-hidden p-4'), 'crm-lead-inspector__section')}>
      <div className="crm-lead-inspector__section-header flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="crm-lead-inspector__section-header-icon">
            <Icon className="h-4 w-4" />
          </span>
          <h3 className="truncate text-sm font-semibold">{title}</h3>
        </div>
        {action}
      </div>
      <div className="crm-lead-inspector__section-body">{children}</div>
    </section>
  );
}

function DetailRow({
  isDark,
  isMono = false,
  label,
  value,
}: {
  isDark: boolean;
  isMono?: boolean;
  label: string;
  value: React.ReactNode;
}) {
  void isDark;
  return (
    <div className="crm-lead-inspector__detail">
      <span>{label}</span>
      <span className={cx(isMono && 'font-mono')} title={typeof value === 'string' ? value : undefined}>
        {value}
      </span>
    </div>
  );
}

function Metric({ isDark, label, value }: { isDark: boolean; label: string; value: string }) {
  void isDark;
  return (
    <div className="crm-lead-inspector__metric">
      <p>{label}</p>
      <p className="mt-2 truncate text-sm font-semibold">{value}</p>
    </div>
  );
}

function TimelineEvent({
  description,
  icon: Icon,
  isDark,
  title,
}: {
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  isDark: boolean;
  title: string;
}) {
  void isDark;
  return (
    <div className="crm-lead-inspector__timeline flex gap-3">
      <span className="crm-lead-inspector__timeline-icon">
        <Icon className="h-4 w-4" />
      </span>
      <div className="min-w-0 pt-0.5">
        <p className="text-sm font-semibold">{title}</p>
        <p className="crm-modern-muted mt-1 text-sm leading-relaxed">{description}</p>
      </div>
    </div>
  );
}
