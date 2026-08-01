import React, { useState, useEffect } from 'react';
import {
  Pause,
  Play,
  RefreshCw,
  Clock,
  Zap,
  MessageSquare,
  CheckCircle2,
  HeartHandshake,
  ShoppingBag,
  Shield,
  Activity
} from 'lucide-react';
import { flowControlApi, FlowStatus } from '../services/flowControlApi.ts';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AgentiveAlert,
  AgentiveConfirmModal,
  AgentivePageHeader,
  agentiveInputClass,
  agentivePageClass,
  agentivePanelClass,
  agentiveSecondaryButtonClass,
} from './AgentiveUI.tsx';

const FLOW_TYPES = [
  {
    key: 'follow_up',
    label: 'Follow-up',
    description: 'Mensagens automatizadas para converter leads em agendamentos',
    icon: Zap,
  },
  {
    key: 'noshow',
    label: 'No-Show',
    description: 'Mensagens para clientes que faltaram à consulta',
    icon: MessageSquare,
  },
  {
    key: 'confirmation',
    label: 'Confirmação',
    description: 'Confirmação automática de consultas agendadas',
    icon: CheckCircle2,
  },
  {
    key: 'pos_consulta',
    label: 'Pós-Consulta',
    description: 'Follow-up após o atendimento para fidelização',
    icon: HeartHandshake,
  },
  {
    key: 'pos_venda',
    label: 'Pós-Venda',
    description: 'Acompanhamento após fechamento de tratamento',
    icon: ShoppingBag,
  }
];

export const FlowControlPanel: React.FC = () => {
  const { isDark } = useTheme();
  const [flowStates, setFlowStates] = useState<Record<string, FlowStatus>>({});
  const [loading, setLoading] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedFlow, setSelectedFlow] = useState<string | null>(null);
  const [showPauseModal, setShowPauseModal] = useState(false);
  const [pauseReason, setPauseReason] = useState('');

  const companyId = Number((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')));

  useEffect(() => {
    loadFlowStates();
    const interval = setInterval(loadFlowStates, 30000);
    return () => clearInterval(interval);
  }, []);

  const loadFlowStates = async () => {
    try {
      setError(null);
      const states = await flowControlApi.getStatus(companyId);
      setFlowStates(states);
    } catch (error: any) {
      console.error('Erro ao carregar estados:', error);
      setError(error.response?.data?.detail || 'Erro ao carregar status dos fluxos');
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    await loadFlowStates();
    setTimeout(() => setRefreshing(false), 500);
  };

  const handleToggle = async (flowType: string) => {
    const currentState = flowStates[flowType];
    const isPaused = currentState?.is_paused || false;

    if (!isPaused) {
      setSelectedFlow(flowType);
      setShowPauseModal(true);
      return;
    }

    confirmToggle(flowType, null);
  };

  const confirmToggle = async (flowType: string, reason: string | null) => {
    setLoading(flowType);
    setError(null);
    setShowPauseModal(false);
    setPauseReason('');

    try {
      const currentState = flowStates[flowType];
      const isPaused = currentState?.is_paused || false;

      await flowControlApi.toggleFlow(companyId, {
        flow_type: flowType,
        is_paused: !isPaused,
        pause_reason: reason || undefined
      });

      await loadFlowStates();
    } catch (error: any) {
      console.error('Erro ao alternar estado:', error);
      setError(
        error.response?.data?.detail ||
        `Erro ao ${flowStates[flowType]?.is_paused ? 'retomar' : 'pausar'} fluxo`
      );
    } finally {
      setLoading(null);
    }
  };

  const formatDateTime = (dateStr?: string) => {
    if (!dateStr) return '';
    return new Date(dateStr).toLocaleString('pt-BR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const getActiveFlowsCount = () => {
    return Object.values(flowStates).filter(state => !state.is_paused).length;
  };

  const getPausedFlowsCount = () => {
    return Object.values(flowStates).filter(state => state.is_paused).length;
  };

  return (
    <div className={agentivePageClass(isDark, 'p-4 sm:p-6')}>
      <div className="mx-auto mb-6 max-w-7xl">
        <AgentivePageHeader
          icon={Activity}
          title="Controle de fluxos"
          description="Gerencie pausas, retomadas e saúde dos envios automáticos."
          badges={(
            <>
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-100">
                <Activity className="w-3 h-3 text-emerald-500" />
                {getActiveFlowsCount()} Ativos
              </span>
              {getPausedFlowsCount() > 0 && (
                <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2.5 py-1 text-xs font-medium text-red-700 ring-1 ring-inset ring-red-100">
                  <Pause className="w-3 h-3 text-red-500" />
                  {getPausedFlowsCount()} Pausados
                </span>
              )}
            </>
          )}
          actions={(
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className={agentiveSecondaryButtonClass(isDark)}
              title="Atualizar status"
            >
              <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
              Atualizar
            </button>
          )}
        />

        {/* Erro Global */}
        {error && (
          <AgentiveAlert className="mt-4" variant="error" title="Erro ao carregar status">
            {error}
          </AgentiveAlert>
        )}
      </div>

      {/* Cards dos Fluxos */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 max-w-7xl mx-auto mb-8">
        {FLOW_TYPES.map(flow => {
          const state = flowStates[flow.key];
          const isPaused = state?.is_paused || false;
          const Icon = flow.icon;

          return (
            <div
              key={flow.key}
              className={agentivePanelClass(isDark, `relative p-5 transition hover:-translate-y-0.5 hover:shadow-flat-lg ${loading === flow.key ? 'animate-pulse' : ''}`)}
            >
              <div className="flex items-start gap-4">
                {/* Ícone padronizado */}
                <div className={`grid place-items-center rounded-xl w-10 h-10 ${
                  isPaused
                    ? isDark
                      ? 'bg-red-900/30 text-red-400'
                      : 'bg-red-50 text-red-600'
                    : isDark
                      ? 'bg-white/10 text-white/70'
                      : 'bg-brand-canvas text-brand'
                }`}>
                  <Icon className="w-5 h-5" />
                </div>

                {/* Conteúdo */}
                <div className="flex-1">
                  <h3 className="font-semibold">{flow.label}</h3>
                  <p className={`text-sm ${isDark ? 'text-white/55' : 'text-brand/55'}`}>{flow.description}</p>

                  {/* Status info */}
                  {isPaused && state?.paused_at && (
                    <div className={`mt-3 flex items-center gap-2 p-3 rounded-lg border ${
                      isDark
                        ? 'border-red-700/50 bg-red-900/20 text-red-300'
                        : 'border-red-200 bg-red-50 text-red-700'
                    }`}>
                      <Clock className="w-4 h-4" />
                      <div className="text-xs">
                        <p className="font-medium">
                          Pausado em {formatDateTime(state.paused_at)}
                        </p>
                        {state.pause_reason && (
                          <p className="mt-0.5 opacity-80">
                            Motivo: {state.pause_reason}
                          </p>
                        )}
                      </div>
                    </div>
                  )}

                  {!isPaused && state?.resumed_at && (
                    <div className={`mt-3 flex items-center gap-2 p-3 rounded-lg border ${
                      isDark
                        ? 'border-green-700/50 bg-green-900/20 text-green-300'
                        : 'border-green-200 bg-green-50 text-green-700'
                    }`}>
                      <Play className="w-4 h-4" />
                      <p className="text-xs font-medium">
                        Retomado em {formatDateTime(state.resumed_at)}
                      </p>
                    </div>
                  )}
                </div>

                {/* Botão de Ação */}
                <button
                  onClick={() => handleToggle(flow.key)}
                  disabled={loading === flow.key}
                  className={`
                    px-4 py-2 rounded-xl text-sm font-medium flex items-center gap-2 transition
                    ${loading === flow.key ? 'opacity-50 cursor-not-allowed' : ''}
                    ${isPaused
                      ? 'bg-green-600 text-white hover:bg-green-700'
                      : 'bg-red-600 text-white hover:bg-red-700'
                    }
                  `}
                >
                  {loading === flow.key ? (
                    <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
                  ) : isPaused ? (
                    <>
                      <Play className="w-4 h-4" />
                      Retomar
                    </>
                  ) : (
                    <>
                      <Pause className="w-4 h-4" />
                      Pausar
                    </>
                  )}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Card de Informações */}
      <div className="max-w-7xl mx-auto">
        <div className={agentivePanelClass(isDark, 'p-6')}>
          <div className="flex items-start gap-4">
            <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${
              isDark ? 'bg-white/10 text-white/70' : 'bg-brand-canvas text-brand'
            }`}>
              <Shield className="w-5 h-5" />
            </div>
            <div className="flex-1">
              <h3 className="mb-3 text-lg font-semibold">
                Como Funciona o Controle de Fluxos
              </h3>
              <div className="grid md:grid-cols-2 gap-4 text-sm">
                <div className="space-y-3">
                  <p className={`flex items-start gap-2 ${isDark ? 'text-white/70' : 'text-brand/65'}`}>
                    <span className="w-2 h-2 bg-brand rounded-full mt-2 flex-shrink-0"></span>
                    <span>Pausar interrompe imediatamente o envio de novas mensagens</span>
                  </p>
                  <p className={`flex items-start gap-2 ${isDark ? 'text-white/70' : 'text-brand/65'}`}>
                    <span className="w-2 h-2 bg-brand rounded-full mt-2 flex-shrink-0"></span>
                    <span>Mensagens pausadas são verificadas diariamente às 8h</span>
                  </p>
                  <p className={`flex items-start gap-2 ${isDark ? 'text-white/70' : 'text-brand/65'}`}>
                    <span className="w-2 h-2 bg-brand rounded-full mt-2 flex-shrink-0"></span>
                    <span>O timing original das mensagens é preservado</span>
                  </p>
                </div>
                <div className="space-y-3">
                  <p className={`flex items-start gap-2 ${isDark ? 'text-white/70' : 'text-brand/65'}`}>
                    <span className="w-2 h-2 bg-brand rounded-full mt-2 flex-shrink-0"></span>
                    <span>Ao retomar, o fluxo continua de onde parou</span>
                  </p>
                  <p className={`flex items-start gap-2 ${isDark ? 'text-white/70' : 'text-brand/65'}`}>
                    <span className="w-2 h-2 bg-brand rounded-full mt-2 flex-shrink-0"></span>
                    <span>Todas as ações são registradas para auditoria</span>
                  </p>
                  <p className={`flex items-start gap-2 ${isDark ? 'text-white/70' : 'text-brand/65'}`}>
                    <span className="w-2 h-2 bg-brand rounded-full mt-2 flex-shrink-0"></span>
                    <span>Sistema monitora a saúde dos fluxos 24/7</span>
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <AgentiveConfirmModal
        isOpen={showPauseModal}
        onClose={() => {
          setShowPauseModal(false);
          setPauseReason('');
        }}
        onConfirm={() => {
          if (selectedFlow) {
            confirmToggle(selectedFlow, pauseReason || null);
          }
        }}
        title="Pausar fluxo?"
        message="Novas mensagens deste fluxo deixam de ser enviadas até que ele seja retomado."
        confirmText="Confirmar pausa"
      >
        <label className={`mb-2 block text-xs font-semibold uppercase ${isDark ? 'text-white/45' : 'text-brand/45'}`}>
          Motivo opcional
        </label>
        <textarea
          value={pauseReason}
          onChange={(e) => setPauseReason(e.target.value)}
          placeholder="Ex: Manutenção programada, ajuste de mensagens..."
          className={agentiveInputClass(isDark, 'resize-none px-4 py-3')}
          rows={3}
        />
      </AgentiveConfirmModal>
    </div>
  );
};
