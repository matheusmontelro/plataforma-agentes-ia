import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  Calendar,
  Globe,
  Loader2,
  Phone,
  UserPlus,
  X,
} from 'lucide-react';
import {
  AgentiveAlert,
  AgentiveEmptyState,
  agentiveIconButtonClass,
  agentivePanelClass,
  agentivePillClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from '../AgentiveUI.tsx';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import { getContactInitials, resolveContactProfilePhoto } from '../../utils/contactAvatar.ts';

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

interface ChatContactProfileProps {
  actions?: React.ReactNode;
  contact: {
    id?: number;
    customer_id?: number;
    funnel_stage?: string;
    lead_id?: number;
    name?: string;
    phone: string;
    photo?: string;
    source_id?: string;
    thumbnail_url?: string;
    timestampNumber?: number;
  };
  error?: string | null;
  isConverting?: boolean;
  isLeadLoading?: boolean;
  onClose: () => void;
  onConvertToLead: () => void;
}

const formatDate = (timestamp?: number) => {
  if (!timestamp) return 'Sem historico recente';
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return 'Sem historico recente';
  return date.toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
};

export default function ChatContactProfile({
  actions,
  contact,
  error,
  isConverting = false,
  isLeadLoading = false,
  onClose,
  onConvertToLead,
}: ChatContactProfileProps) {
  const { isDark } = useTheme();
  const [imageFailed, setImageFailed] = useState(false);
  const avatarUrl = resolveContactProfilePhoto(contact);
  const canShowImage = Boolean(avatarUrl && !imageFailed);
  const mutedClass = isDark ? 'text-white/55' : 'text-brand/55';
  const softSurfaceClass = isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas';
  const hasLeadReference = Boolean(contact.lead_id);

  useEffect(() => {
    setImageFailed(false);
  }, [avatarUrl]);

  return (
    <div className="fixed inset-0 z-[90] flex justify-end p-0 sm:p-4">
      <div className="absolute inset-0 bg-brand/55 backdrop-blur-sm" onClick={onClose} />

      <section className={cx(
        'relative z-10 flex h-full w-full max-w-6xl flex-col overflow-hidden border shadow-[0_24px_80px_rgba(2,3,35,0.28)] sm:rounded-2xl',
        isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-brand-canvas text-brand'
      )}>
        <header className={cx('shrink-0 border-b p-4 sm:p-5', isDark ? 'border-white/10 bg-white/[0.035]' : 'border-brand/10 bg-white')}>
          <div className="flex items-start justify-between gap-4">
            <div className="flex min-w-0 items-start gap-3">
              <span className={cx('grid h-12 w-12 shrink-0 place-items-center overflow-hidden rounded-xl text-sm font-semibold shadow-flat', isDark ? 'bg-white text-brand' : 'bg-brand text-white')}>
                {canShowImage ? (
                  <img
                    src={avatarUrl}
                    alt={contact.name || contact.phone}
                    className="h-full w-full object-cover"
                    onError={() => setImageFailed(true)}
                  />
                ) : (
                  getContactInitials(contact.name || contact.phone)
                )}
              </span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="truncate text-xl font-semibold leading-tight">{contact.name || 'Contato sem nome'}</h2>
                  {contact.customer_id && <span className={agentivePillClass(isDark, true)}>Cliente</span>}
                  {!contact.customer_id && <span className={agentivePillClass(isDark)}>Contato</span>}
                </div>
                <div className={cx('mt-2 flex flex-wrap items-center gap-2 text-xs', mutedClass)}>
                  <span className={agentivePillClass(isDark)}>
                    <Phone className="h-3 w-3" />
                    {contact.phone}
                  </span>
                  {contact.source_id && (
                    <span className={agentivePillClass(isDark)}>
                      <Globe className="h-3 w-3" />
                      {contact.source_id}
                    </span>
                  )}
                  <span className={agentivePillClass(isDark)}>
                    <Calendar className="h-3 w-3" />
                    {formatDate(contact.timestampNumber)}
                  </span>
                </div>
              </div>
            </div>

            <button type="button" onClick={onClose} className={agentiveIconButtonClass(isDark)} aria-label="Fechar perfil">
              <X className="h-4 w-4" />
            </button>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-4 custom-scrollbar sm:p-5">
          <div className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
            <aside className="space-y-4">
              {actions}
            </aside>

            <main className="min-w-0 space-y-4">
              {error && (
                <AgentiveAlert title="Perfil do CRM" variant="error">
                  {error}
                </AgentiveAlert>
              )}

              <section className={agentivePanelClass(isDark, 'overflow-hidden p-4')}>
                <div className="mb-4 flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold">Dados comerciais</p>
                    <p className={cx('mt-1 text-xs', mutedClass)}>
                      Este contato ainda precisa de um lead vinculado para abrir o perfil completo do CRM.
                    </p>
                  </div>
                  {isLeadLoading && <Loader2 className={cx('h-4 w-4 animate-spin', mutedClass)} />}
                </div>

                {hasLeadReference ? (
                  <AgentiveAlert title="Carregando lead" variant="info">
                    O contato possui um lead vinculado. Estamos buscando os campos completos do CRM.
                  </AgentiveAlert>
                ) : (
                  <AgentiveEmptyState
                    icon={AlertCircle}
                    title="Contato sem lead no CRM"
                    description="Converta este contato para lead para usar atributos, historico comercial e funil dentro do perfil."
                    action={(
                      <button
                        type="button"
                        onClick={onConvertToLead}
                        disabled={isConverting || !contact.id}
                        className={agentivePrimaryButtonClass()}
                      >
                        {isConverting ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
                        Converter em lead
                      </button>
                    )}
                  />
                )}
              </section>

              <section className={agentivePanelClass(isDark, 'overflow-hidden p-4')}>
                <p className="text-sm font-semibold">Resumo do contato</p>
                <div className={cx('mt-4 divide-y overflow-hidden rounded-2xl border', isDark ? 'divide-white/10 border-white/10' : 'divide-brand/10 border-brand/10')}>
                  {[
                    ['Telefone', contact.phone],
                    ['Origem', contact.source_id || '-'],
                    ['Status', contact.funnel_stage || 'contato'],
                    ['Ultima atividade', formatDate(contact.timestampNumber)],
                  ].map(([label, value]) => (
                    <div key={label} className={cx('grid gap-1 p-3 sm:grid-cols-[140px_minmax(0,1fr)]', softSurfaceClass)}>
                      <span className={cx('text-xs font-semibold', mutedClass)}>{label}</span>
                      <span className="min-w-0 truncate text-sm">{value}</span>
                    </div>
                  ))}
                </div>
              </section>
            </main>
          </div>
        </div>

        <footer className={cx('shrink-0 border-t px-4 py-3 sm:px-5', isDark ? 'border-white/10 bg-white/[0.035]' : 'border-brand/10 bg-white')}>
          <button type="button" onClick={onClose} className={agentiveSecondaryButtonClass(isDark)}>
            Fechar perfil
          </button>
        </footer>
      </section>
    </div>
  );
}
