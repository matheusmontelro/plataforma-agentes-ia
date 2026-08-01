import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  Calendar,
  ExternalLink,
  Link2,
  Loader2,
  RefreshCw,
  Trash2,
} from 'lucide-react';
import { toast } from 'react-toastify';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  deleteGoogleCalendarIntegration,
  getGoogleCalendarIntegration,
  GoogleCalendarIntegration,
  startGoogleCalendarOAuth,
} from '../services/api';
import { calendarApi, Agenda } from '../services/calendar_api.ts';
import {
  AgentiveAlert,
  AgentiveConfirmModal,
  AgentiveEmptyState,
  agentiveIconButtonClass,
  agentivePageClass,
  agentivePanelClass,
  agentivePillClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';

interface AgendaIntegrationProps {
  embedded?: boolean;
}

const AgendaIntegration: React.FC<AgendaIntegrationProps> = ({ embedded = false }) => {
  const { isDark } = useTheme();
  const [integration, setIntegration] = useState<GoogleCalendarIntegration | null>(null);
  const [agendas, setAgendas] = useState<Agenda[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showDisconnectConfirm, setShowDisconnectConfirm] = useState(false);

  const isConnected = Boolean(integration?.google_oauth_connected);
  const linkedAgendas = useMemo(
    () => agendas.filter((agenda) => Boolean(agenda.google_calendar_id)),
    [agendas]
  );

  const mutedClass = isDark ? 'text-white/55' : 'text-brand/55';
  const borderClass = isDark ? 'border-white/10' : 'border-brand/10';
  const headClass = isDark ? 'bg-white/[0.04] text-white/45' : 'bg-brand-canvas text-brand/45';
  const pageClass = embedded
    ? ''
    : agentivePageClass(isDark, 'px-4 pb-28 pt-4 sm:px-6 lg:px-8 xl:px-10');
  const contentClass = embedded ? 'w-full space-y-5' : 'mx-auto max-w-screen-2xl space-y-5';

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [integrationData, localAgendas] = await Promise.all([
        getGoogleCalendarIntegration(),
        calendarApi.listAgendas(),
      ]);
      setIntegration(integrationData);
      setAgendas(localAgendas);
    } catch (error: any) {
      toast.error(error.message || 'Erro ao carregar integração Google Agenda.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const oauthStatus = params.get('google_oauth');

    const clearOauthStatus = () => {
      params.delete('google_oauth');
      const remainingParams = params.toString();
      window.history.replaceState(
        {},
        '',
        `${window.location.pathname}${remainingParams ? `?${remainingParams}` : ''}`
      );
    };

    if (oauthStatus === 'success') {
      toast.success('Google Agenda conectado com sucesso.');
      clearOauthStatus();
    } else if (oauthStatus === 'error') {
      toast.error('Não foi possível concluir a conexão com o Google.');
      clearOauthStatus();
    }

    loadData();
  }, [loadData]);

  const handleConnectGoogle = async () => {
    setSaving(true);
    try {
      const { authorization_url } = await startGoogleCalendarOAuth();
      window.location.href = authorization_url;
    } catch (error: any) {
      toast.error(error.message || 'Erro ao iniciar conexão com Google.');
      setSaving(false);
    }
  };

  const handleDisconnect = async () => {
    setSaving(true);
    try {
      await deleteGoogleCalendarIntegration();
      toast.success('Google Agenda desconectado.');
      setShowDisconnectConfirm(false);
      await loadData();
    } catch (error: any) {
      toast.error(error.message || 'Erro ao desconectar Google Agenda.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className={pageClass}>
        <div className={agentivePanelClass(isDark, `${embedded ? 'w-full' : 'mx-auto max-w-screen-2xl'} p-8`)}>
          <div className="flex items-center justify-center gap-3">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span className="text-sm font-medium">Carregando integração</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={pageClass}>
      <div className={contentClass}>
        {!embedded && (
          <div className={`border-b pb-6 ${borderClass}`}>
            <h1 className="text-3xl font-semibold">Integração Google Agenda</h1>
            <p className={`mt-2 ${mutedClass}`}>
              Conecte a conta Google e acompanhe quais agendas locais estão vinculadas a calendários Google.
            </p>
          </div>
        )}

        {!integration?.oauth_configured && (
          <AgentiveAlert variant="warning" title="OAuth do Google ainda não está configurado no backend.">
            A conexão com Google Agenda precisa das credenciais OAuth do projeto Google.
          </AgentiveAlert>
        )}

        <section className={agentivePanelClass(isDark, 'min-w-0 overflow-hidden')}>
          <div className={`border-b p-4 sm:p-5 ${borderClass}`}>
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="flex min-w-0 items-start gap-3">
                <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border ${isDark ? 'border-white/10 bg-white' : 'border-brand/10 bg-brand-canvas'}`}>
                  <Calendar className="h-6 w-6" aria-hidden="true" />
                </div>
                <div className="min-w-0">
                  <div className={`mb-1 text-[10px] font-bold uppercase tracking-[0.16em] ${isDark ? 'text-white/35' : 'text-brand/35'}`}>
                    Conector
                  </div>
                  <h2 className="truncate text-xl font-semibold">Google Agenda</h2>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <span className={agentivePillClass(isDark, isConnected)}>
                      {isConnected ? 'Conectado' : 'Não conectado'}
                    </span>
                    {integration?.google_account_email && (
                      <span className={agentivePillClass(isDark)}>
                        {integration.google_account_email}
                      </span>
                    )}
                  </div>
                </div>
              </div>

              <div className="flex flex-col gap-2 sm:flex-row">
                <button
                  type="button"
                  onClick={loadData}
                  disabled={loading || saving}
                  className={agentiveSecondaryButtonClass(isDark)}
                >
                  {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  Atualizar
                </button>
                {!isConnected ? (
                  <button
                    type="button"
                    onClick={handleConnectGoogle}
                    disabled={saving || !integration?.oauth_configured}
                    className={agentivePrimaryButtonClass('px-4')}
                  >
                    {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <ExternalLink className="h-4 w-4" />}
                    Conectar Google
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => setShowDisconnectConfirm(true)}
                    disabled={saving}
                    className={agentiveIconButtonClass(isDark, 'danger')}
                    title="Desconectar Google Agenda"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </div>
            </div>
          </div>

          <div className="p-3 sm:p-4">
            {!isConnected ? (
              <AgentiveEmptyState
                icon={AlertCircle}
                title="Google Agenda não conectado"
                description="Autorize a conta Google para vincular calendários às agendas locais."
                action={(
                  <button
                    type="button"
                    onClick={handleConnectGoogle}
                    disabled={saving || !integration?.oauth_configured}
                    className={agentivePrimaryButtonClass('px-4')}
                  >
                    <ExternalLink className="h-4 w-4" />
                    Conectar Google
                  </button>
                )}
              />
            ) : linkedAgendas.length === 0 ? (
              <AgentiveEmptyState
                icon={Link2}
                title="Nenhuma agenda local vinculada"
                description="Use a aba Agendas e horários para vincular cada agenda local a uma agenda Google existente ou nova."
              />
            ) : (
              <div className={`overflow-hidden rounded-2xl border ${borderClass}`}>
                <div className="overflow-x-auto">
                  <table className="min-w-[780px] w-full border-collapse text-sm">
                    <thead className={headClass}>
                      <tr className="text-left text-[10px] font-bold uppercase tracking-[0.16em]">
                        <th className="px-4 py-3">Agenda local</th>
                        <th className="px-4 py-3">Google Agenda</th>
                        <th className="px-4 py-3">Fuso Google</th>
                        <th className="px-4 py-3">Status</th>
                      </tr>
                    </thead>
                    <tbody className={`divide-y ${isDark ? 'divide-white/10' : 'divide-brand/10'}`}>
                      {linkedAgendas.map((agenda) => (
                        <tr key={agenda.id} className={isDark ? 'hover:bg-white/[0.06]' : 'hover:bg-brand-canvas'}>
                          <td className="px-4 py-3">
                            <div className="flex min-w-0 items-center gap-3">
                              <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ${agenda.active ? 'bg-emerald-500/10 text-emerald-600' : isDark ? 'bg-white/10 text-white/70' : 'bg-brand-canvas text-brand/70'}`}>
                                <Calendar className="h-4 w-4" />
                              </span>
                              <div className="min-w-0">
                                <p className="truncate font-semibold">{agenda.name}</p>
                                <p className={`mt-0.5 text-xs ${mutedClass}`}>Agenda #{agenda.id}</p>
                              </div>
                            </div>
                          </td>
                          <td className="px-4 py-3">
                            <p className="max-w-[360px] truncate font-medium">
                              {agenda.google_calendar_summary || agenda.google_calendar_id}
                            </p>
                            <p className={`mt-0.5 max-w-[360px] truncate text-xs ${mutedClass}`}>
                              {agenda.google_calendar_id}
                            </p>
                          </td>
                          <td className={`px-4 py-3 ${mutedClass}`}>
                            {agenda.google_calendar_time_zone || '-'}
                          </td>
                          <td className="px-4 py-3">
                            <span className={agentivePillClass(isDark, true)}>Vinculada</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </section>

        <AgentiveConfirmModal
          cancelText="Manter conexão"
          confirmText="Desconectar"
          isLoading={saving}
          isOpen={showDisconnectConfirm}
          message="A empresa deixará de criar eventos e consultar bloqueios pelo Google Agenda. Os vínculos locais serão removidos, mas eventos já existentes no Google não serão apagados."
          onClose={() => setShowDisconnectConfirm(false)}
          onConfirm={handleDisconnect}
          title="Desconectar Google Agenda?"
          variant="danger"
        />
      </div>
    </div>
  );
};

export default AgendaIntegration;
