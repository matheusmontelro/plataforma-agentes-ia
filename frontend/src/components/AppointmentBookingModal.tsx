import React, { useEffect, useMemo, useState } from 'react';
import { format } from 'date-fns';
import { CalendarPlus, Check, Link2, Loader2, MapPin, Phone, Search, User, X } from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AgendamentoResponse,
  Contact,
  convertContactToLead,
  criarAgendamento,
  getContacts,
} from '../services/api.ts';
import { type Agenda } from '../services/calendar_api.ts';
import {
  AgentiveAlert,
  agentiveInputClass,
  agentivePillClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from './AgentiveUI.tsx';
import {
  crmModernBadgeClass,
  crmModernIconButtonClass,
  crmModernInputClass,
  crmModernPrimaryButtonClass,
  crmModernSecondaryButtonClass,
} from './crm/CRMModern/CRMModernUI.tsx';
import './AppointmentBookingModal.css';

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

export interface AppointmentBookingLead {
  leadId: number;
  name?: string;
  phone?: string;
  sourceId?: string;
}

interface AppointmentBookingModalProps {
  agendas: Agenda[];
  defaultAgendaId?: number | null;
  defaultDate?: Date | string | null;
  isOpen: boolean;
  lockedLead?: AppointmentBookingLead;
  onClose: () => void;
  onCreated: (appointment: AgendamentoResponse) => void | Promise<void>;
  title?: string;
  visualVariant?: 'default' | 'crm-modern';
}

const resolveNumericStorageValue = (...keys: string[]) => {
  for (const key of keys) {
    const rawValue = localStorage.getItem(key) || sessionStorage.getItem(key);
    const parsed = Number(rawValue);
    if (Number.isFinite(parsed) && parsed > 0) return parsed;
  }
  return null;
};

const toDateTimeLocalValue = (value?: Date | string | null) => {
  if (!value) return '';
  const parsed = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';

  const offsetDate = new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60000);
  return offsetDate.toISOString().slice(0, 16);
};

const toAppointmentDatePayload = (value: string) => {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  return format(parsed, 'dd/MM/yyyy HH:mm');
};

const normalizeContact = (contact: Contact): Contact => ({
  ...contact,
  name: contact.name || contact.phone,
});

const getInitials = (name?: string) => {
  const parts = (name || '').trim().split(/\s+/).filter(Boolean);
  return (parts.slice(0, 2).map((part) => part[0]).join('') || 'CT').toUpperCase();
};

const getContactPhotoUrl = (contact: Contact) => contact.thumbnail_url || contact.photo || '';

function ContactAvatar({ contact, isDark, isModern = false }: { contact: Contact; isDark: boolean; isModern?: boolean }) {
  const [imageFailed, setImageFailed] = useState(false);
  const photoUrl = getContactPhotoUrl(contact);

  return (
    <span
      className={cx(
        isModern && 'crm-booking-avatar',
        !isModern && 'grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-xl text-xs font-semibold',
        isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'
      )}
    >
      {photoUrl && !imageFailed ? (
        <img
          src={photoUrl}
          alt={contact.name || 'Contato'}
          className="h-full w-full object-cover"
          onError={() => setImageFailed(true)}
        />
      ) : (
        getInitials(contact.name || contact.phone)
      )}
    </span>
  );
}

export default function AppointmentBookingModal({
  agendas,
  defaultAgendaId,
  defaultDate,
  isOpen,
  lockedLead,
  onClose,
  onCreated,
  title = 'Novo agendamento',
  visualVariant = 'default',
}: AppointmentBookingModalProps) {
  const { isDark } = useTheme();
  const isModern = visualVariant === 'crm-modern';
  const inputClass = isModern ? crmModernInputClass : agentiveInputClass;
  const badgeClass = isModern ? crmModernBadgeClass : agentivePillClass;
  const primaryButtonClass = isModern ? crmModernPrimaryButtonClass : agentivePrimaryButtonClass;
  const secondaryButtonClass = isModern ? crmModernSecondaryButtonClass : agentiveSecondaryButtonClass;
  const [agendaId, setAgendaId] = useState('');
  const [dateTime, setDateTime] = useState('');
  const [interest, setInterest] = useState('');
  const [address, setAddress] = useState('');
  const [locationLink, setLocationLink] = useState('');
  const [query, setQuery] = useState('');
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [selectedContact, setSelectedContact] = useState<Contact | null>(null);
  const [searching, setSearching] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedAgenda = useMemo(
    () => agendas.find((agenda) => String(agenda.id) === String(agendaId)) || null,
    [agendaId, agendas]
  );

  useEffect(() => {
    if (!isOpen) return;

    setAgendaId(defaultAgendaId ? String(defaultAgendaId) : '');
    setDateTime(toDateTimeLocalValue(defaultDate));
    setInterest('');
    setAddress('');
    setLocationLink('');
    setQuery('');
    setContacts([]);
    setSelectedContact(null);
    setError(null);
    setSubmitting(false);
    setSearching(false);
  }, [defaultAgendaId, defaultDate, isOpen, lockedLead?.leadId]);

  useEffect(() => {
    if (!isOpen || lockedLead) return;

    const trimmed = query.trim();
    if (trimmed.length < 3) {
      setContacts([]);
      setSearching(false);
      return;
    }

    let canceled = false;
    setSearching(true);
    const timeout = window.setTimeout(async () => {
      try {
        const response = await getContacts({ limit: 8, search: trimmed, show_archived: true });
        if (!canceled) {
          setContacts(response.contacts.map(normalizeContact));
        }
      } catch (searchError) {
        console.error('Erro ao buscar contatos para agendamento:', searchError);
        if (!canceled) {
          setContacts([]);
          setError('Não foi possível buscar contatos agora.');
        }
      } finally {
        if (!canceled) setSearching(false);
      }
    }, 300);

    return () => {
      canceled = true;
      window.clearTimeout(timeout);
    };
  }, [isOpen, lockedLead, query]);

  const selectedName = lockedLead?.name || selectedContact?.name || '';
  const selectedPhone = lockedLead?.phone || selectedContact?.phone || '';
  const canSubmit = Boolean(dateTime && (lockedLead || selectedContact) && !submitting);

  const handleCreate = async () => {
    if (!canSubmit) return;

    const clientId = resolveNumericStorageValue('client_id');
    const companyId = resolveNumericStorageValue('company_id', 'clinic_id');
    if (!clientId || !companyId) {
      setError('Sessão incompleta para criar o agendamento.');
      return;
    }

    setSubmitting(true);
    setError(null);

    try {
      let leadId = lockedLead?.leadId || selectedContact?.lead_id || null;

      if (!leadId && selectedContact?.id) {
        const conversion = await convertContactToLead(selectedContact.id, selectedContact.source_id || 'Manual');
        leadId = conversion.lead_id;
      }

      if (!leadId) {
        throw new Error('Contato sem lead vinculado para agendamento.');
      }

      const appointment = await criarAgendamento(
        clientId,
        companyId,
        {
          agenda_id: agendaId ? Number(agendaId) : undefined,
          consulta_data: toAppointmentDatePayload(dateTime),
          endereco: address.trim() || undefined,
          interesse: interest.trim() || undefined,
          lead_id: leadId,
          local_link: locationLink.trim() || undefined,
          midia: lockedLead?.sourceId || selectedContact?.source_id || 'Manual',
          nome: selectedName,
          phone: selectedPhone,
        },
        ''
      );

      await onCreated(appointment);
      onClose();
    } catch (createError: any) {
      console.error('Erro ao criar agendamento:', createError);
      setError(createError?.response?.data?.detail || createError?.message || 'Não foi possível criar o agendamento.');
    } finally {
      setSubmitting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className={cx('fixed inset-0 z-[10010] flex items-center justify-center p-4', isModern && 'crm-work-modal', isModern && isDark && 'crm-work-modal--dark')}>
      <div
        className={cx('fixed inset-0 bg-brand/55 backdrop-blur-sm', isModern && 'crm-modern-modal-root')}
        onClick={submitting ? undefined : onClose}
      />
      <section
        className={cx(
          'relative z-[10020] flex max-h-[92vh] w-full max-w-2xl flex-col overflow-hidden border',
          isModern ? 'crm-modern-modal' : 'rounded-2xl shadow-[0_24px_80px_rgba(2,3,35,0.28)]',
          !isModern && (isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand')
        )}
      >
        <header className={cx('shrink-0 border-b', isModern ? 'crm-modern-modal__header' : 'p-5', !isModern && (isDark ? 'border-white/10 bg-white/[0.035]' : 'border-brand/10 bg-white'))}>
          <div className="flex items-start justify-between gap-4">
            <div className="flex min-w-0 items-start gap-3">
              <span className={cx('crm-booking-header-icon grid shrink-0 place-items-center', !isModern && 'h-11 w-11 rounded-xl', isDark ? 'bg-white/10 text-white' : 'bg-brand text-white')}>
                <CalendarPlus className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <h2 className="text-base font-semibold leading-tight">{title}</h2>
                <p className={cx('mt-1 text-sm leading-relaxed', isDark ? 'text-white/55' : 'text-brand/55')}>
                  {selectedAgenda?.name || 'Agenda'}{dateTime ? ` · ${format(new Date(dateTime), "dd/MM/yyyy 'às' HH:mm")}` : ''}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className={isModern
                ? crmModernIconButtonClass(isDark)
                : cx('rounded-xl p-2 transition disabled:opacity-40', isDark ? 'text-white/45 hover:bg-white/10 hover:text-white' : 'text-brand/45 hover:bg-brand-canvas hover:text-brand')}
              aria-label="Fechar modal"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </header>

        <div className={cx('min-h-0 flex-1 space-y-4 overflow-y-auto custom-scrollbar', isModern ? 'crm-modern-modal__body' : 'p-5')}>
          {error && (
            <AgentiveAlert className={isModern ? 'crm-modern-alert' : undefined} title="Erro" variant="error" onClose={() => setError(null)}>
              {error}
            </AgentiveAlert>
          )}

          {lockedLead ? (
            <div className={cx(isModern ? 'crm-booking-selection' : 'rounded-2xl border p-4', !isModern && (isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas'))}>
              <p className={cx('text-[10px] font-semibold uppercase tracking-[0.14em]', isDark ? 'text-white/35' : 'text-brand/40')}>Lead</p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold">{lockedLead.name || 'Lead sem nome'}</span>
                {lockedLead.phone && (
                  <span className={badgeClass(isDark)}>
                    <Phone className="h-3 w-3" />
                    {lockedLead.phone}
                  </span>
                )}
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <div>
                <label className={cx('mb-1.5 block text-xs font-semibold', isDark ? 'text-white/55' : 'text-brand/55')}>
                  Buscar contato
                </label>
                <div className="relative">
                  <Search className={cx('absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2', isDark ? 'text-white/35' : 'text-brand/35')} />
                  <input
                    className={inputClass(isDark, 'pl-9')}
                    value={query}
                    onChange={(event) => {
                      setQuery(event.target.value);
                      setSelectedContact(null);
                    }}
                    placeholder="Telefone ou nome"
                    autoFocus
                  />
                </div>
              </div>

              <div className={cx(isModern ? 'crm-booking-contact-list' : 'min-h-[144px] rounded-2xl border p-2', !isModern && (isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-brand-canvas'))}>
                {searching ? (
                  <div className={cx('flex items-center gap-2 p-3 text-sm', isDark ? 'text-white/55' : 'text-brand/55')}>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Buscando contatos
                  </div>
                ) : contacts.length > 0 ? (
                  <div className="space-y-2">
                    {contacts.map((contact) => {
                      const active = selectedContact?.id === contact.id;
                      return (
                        <button
                          key={`${contact.id || contact.phone}-${contact.phone}`}
                          type="button"
                          onClick={() => setSelectedContact(contact)}
                          className={cx(
                            'flex w-full items-center justify-between gap-3 text-left transition',
                            isModern ? 'crm-booking-contact' : 'rounded-xl border p-3',
                            isModern && active && 'crm-booking-contact--active',
                            !isModern && active
                              ? isDark ? 'border-white/20 bg-white/12' : 'border-brand/20 bg-white'
                              : !isModern && (isDark ? 'border-white/10 bg-white/[0.04] hover:bg-white/10' : 'border-brand/10 bg-white hover:bg-brand-canvas')
                          )}
                        >
                          <span className="flex min-w-0 items-center gap-3">
                            <ContactAvatar contact={contact} isDark={isDark} isModern={isModern} />
                            <span className="min-w-0">
                              <span className="block truncate text-sm font-semibold">{contact.name || 'Contato sem nome'}</span>
                              <span className={cx('mt-1 block truncate font-mono text-xs', isDark ? 'text-white/45' : 'text-brand/45')}>{contact.phone}</span>
                            </span>
                          </span>
                          <span className="flex shrink-0 items-center gap-2">
                            <span className={badgeClass(isDark, Boolean(contact.lead_id), 'px-2 py-0.5 text-[11px]')}>
                              {contact.lead_id ? 'Lead' : 'Converter'}
                            </span>
                            {active && <Check className="h-4 w-4" />}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <div className={cx('p-3 text-sm leading-relaxed', isDark ? 'text-white/55' : 'text-brand/55')}>
                    {query.trim().length >= 3 ? 'Nenhum contato encontrado.' : 'Digite pelo menos 3 caracteres.'}
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className={cx('mb-1.5 block text-xs font-semibold', isDark ? 'text-white/55' : 'text-brand/55')}>
                Agenda
              </label>
              <select
                className={inputClass(isDark)}
                value={agendaId}
                onChange={(event) => setAgendaId(event.target.value)}
              >
                <option value="">Sem agenda definida</option>
                {agendas.map((agenda) => (
                  <option key={agenda.id} value={agenda.id}>
                    {agenda.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className={cx('mb-1.5 block text-xs font-semibold', isDark ? 'text-white/55' : 'text-brand/55')}>
                Data e hora
              </label>
              <input
                type="datetime-local"
                className={inputClass(isDark)}
                value={dateTime}
                onChange={(event) => setDateTime(event.target.value)}
              />
            </div>
          </div>

          <div>
            <label className={cx('mb-1.5 block text-xs font-semibold', isDark ? 'text-white/55' : 'text-brand/55')}>
              Interesse
            </label>
            <input
              className={inputClass(isDark)}
              value={interest}
              onChange={(event) => setInterest(event.target.value)}
              placeholder="Opcional"
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className={cx('mb-1.5 block text-xs font-semibold', isDark ? 'text-white/55' : 'text-brand/55')}>
                Endereço
              </label>
              <div className="relative">
                <MapPin className={cx('absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2', isDark ? 'text-white/35' : 'text-brand/35')} />
                <input
                  className={inputClass(isDark, 'pl-9')}
                  value={address}
                  onChange={(event) => setAddress(event.target.value)}
                  placeholder="Preencher endereço"
                />
              </div>
            </div>

            <div>
              <label className={cx('mb-1.5 block text-xs font-semibold', isDark ? 'text-white/55' : 'text-brand/55')}>
                Link do local
              </label>
              <div className="relative">
                <Link2 className={cx('absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2', isDark ? 'text-white/35' : 'text-brand/35')} />
                <input
                  className={inputClass(isDark, 'pl-9')}
                  value={locationLink}
                  onChange={(event) => setLocationLink(event.target.value)}
                  placeholder="Meet, Zoom ou Maps"
                />
              </div>
            </div>
          </div>

          {(selectedContact || lockedLead) && (
            <div className={cx(isModern ? 'crm-booking-selection' : 'rounded-2xl border p-3 text-sm', !isModern && (isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas'))}>
              <div className="flex min-w-0 items-center gap-3">
                {selectedContact ? (
                  <ContactAvatar contact={selectedContact} isDark={isDark} isModern={isModern} />
                ) : (
                  <span className={cx('grid shrink-0 place-items-center', isModern ? 'crm-booking-avatar' : 'h-10 w-10 rounded-xl', isDark ? 'bg-white/10 text-white' : 'bg-brand text-white')}>
                    <User className="h-4 w-4" />
                  </span>
                )}
                <div className="min-w-0">
                  <p className="truncate font-semibold">{selectedName || 'Contato selecionado'}</p>
                  {selectedPhone && <p className={cx('mt-1 truncate font-mono text-xs', isDark ? 'text-white/45' : 'text-brand/45')}>{selectedPhone}</p>}
                </div>
              </div>
            </div>
          )}
        </div>

        <footer className={cx('shrink-0 border-t', isModern ? 'crm-modern-modal__footer' : 'p-5', !isModern && (isDark ? 'border-white/10 bg-white/[0.025]' : 'border-brand/10 bg-white'))}>
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className={secondaryButtonClass(isDark)}
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={handleCreate}
              disabled={!canSubmit}
              className={primaryButtonClass()}
            >
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <CalendarPlus className="h-4 w-4" />}
              {submitting ? 'Agendando...' : 'Agendar'}
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}
