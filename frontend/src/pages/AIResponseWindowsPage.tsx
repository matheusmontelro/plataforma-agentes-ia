// src/pages/AIResponseWindowsPage.tsx

import React, { useEffect, useState } from 'react';
import { useTheme } from '../contexts/ThemeContext.tsx';
import ConfirmDeleteModal from '../components/ConfirmDeleteModal.tsx';
import {
  getAIWindow,
  createAIWindow,
  updateAIWindow,
  deleteAIWindow,
  AIResponseWindowsData,
  DayTimeConfig,
} from '../services/api';

import {
  Loader,
  Trash2,
  Save,
  CheckCircle,
  Edit2,
  AlertCircle,
  Clock,
  Calendar,
  ChevronDown,
  ChevronUp,
  Sun,
  Sunrise,
  Sunset,
  Moon,
  HelpCircle
} from 'lucide-react';

/**
 * Estrutura local para manipular os dados no formulário.
 * "id" é opcional enquanto não existir config no banco.
 */
interface LocalAIWindowData extends Omit<AIResponseWindowsData, 'id'> {
  id?: number | null;
}

/**
 * Modelo base para cada período do dia.
 */
const defaultPeriod = {
  enabled: false,
  start: '06:00',
  end: '12:00',
};

/**
 * Gera uma estrutura default para cada dia da semana (monday..sunday),
 * cada um contendo { morning, afternoon, night, dawn }.
 */
function getDefaultTimeWindows(): Record<string, DayTimeConfig> {
  const days = [
    'monday', 'tuesday', 'wednesday',
    'thursday', 'friday', 'saturday', 'sunday'
  ];

  const defaultDayTimeConfig: DayTimeConfig = {
    dawn:      { ...defaultPeriod, start: '00:00', end: '06:00' },
    morning:   { ...defaultPeriod },
    afternoon: { ...defaultPeriod, start: '12:00', end: '18:00' },
    night:     { ...defaultPeriod, start: '18:00', end: '00:00' },
  };

  const result: Record<string, DayTimeConfig> = {};
  for (const day of days) {
    // Clona para evitar referências compartilhadas entre dias
    result[day] = JSON.parse(JSON.stringify(defaultDayTimeConfig));
  }
  return result;
}

/**
 * Função que faz merge (unifica) o objeto time_windows que veio do backend
 * com o objeto default. Assim, se faltar algum dia/período, ele será preenchido.
 */
function unifyTimeWindows(
  fromBackend?: Record<string, DayTimeConfig>
): Record<string, DayTimeConfig> {
  const def = getDefaultTimeWindows();
  if (!fromBackend) return def;

  for (const day of Object.keys(def)) {
    if (!fromBackend[day]) {
      // Se não existe esse dia no backend, adiciona
      fromBackend[day] = def[day];
    } else {
      // Se existe o dia, verifica cada período
      for (const period of ['morning','afternoon','night','dawn'] as const) {
        if (!fromBackend[day][period]) {
          fromBackend[day][period] = def[day][period];
        }
      }
    }
  }
  return fromBackend;
}

// Array ordenado dos dias da semana
const orderedDays = [
  'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'
];

// Traduções dos dias da semana
const dayTranslations: Record<string, string> = {
  monday:    'Segunda-feira',
  tuesday:   'Terça-feira',
  wednesday: 'Quarta-feira',
  thursday:  'Quinta-feira',
  friday:    'Sexta-feira',
  saturday:  'Sábado',
  sunday:    'Domingo'
};

// Traduções dos períodos
const periodTranslations: Record<string, string> = {
  morning:   'Manhã',
  afternoon: 'Tarde',
  night:     'Noite',
  dawn:      'Madrugada'
};

// Descrições para cada período
const periodDescriptions: Record<string, string> = {
  morning:   'Início da manhã até meio-dia',
  afternoon: 'Meio-dia até o final da tarde',
  night:     'Final da tarde até a noite',
  dawn:      'Noite até o início da manhã'
};

// Ícone para cada período
const PeriodIcon: React.FC<{ period: string; className?: string; enabled?: boolean }> = ({
  period,
  className = "w-5 h-5",
  enabled = true
}) => {
  const baseColor = enabled ? "text-brand" : "text-gray-400";

  switch (period) {
    case 'morning':
      return <Sunrise className={`${className} ${baseColor}`} />;
    case 'afternoon':
      return <Sun className={`${className} ${baseColor}`} />;
    case 'night':
      return <Sunset className={`${className} ${baseColor}`} />;
    case 'dawn':
      return <Moon className={`${className} ${baseColor}`} />;
    default:
      return <Clock className={`${className} ${baseColor}`} />;
  }
};

// Props do componente de card de dia
interface DayCardProps {
  day: string;
  config: DayTimeConfig;
  onTogglePeriod: (day: string, period: keyof DayTimeConfig) => void;
  onUpdateTime: (day: string, period: keyof DayTimeConfig, field: 'start' | 'end', value: string) => void;
  expanded: boolean;
  onToggleExpand: () => void;
  onApplyToWeekdays: () => void;
  onApplyToWeekend: () => void;
  isDark?: boolean;
}

/**
 * Componente que renderiza o card de um dia específico,
 * com toggle de habilitar e inputs de horário para cada período.
 */
const DayCard: React.FC<DayCardProps> = ({
  day,
  config,
  onTogglePeriod,
  onUpdateTime,
  expanded,
  onToggleExpand,
  onApplyToWeekdays,
  onApplyToWeekend,
  isDark = false
}) => {
  // Verifica se algum período do dia está habilitado
  const hasEnabledPeriods = Object.values(config).some(period => period.enabled);
  // Conta quantos períodos estão habilitados
  const enabledPeriodsCount = Object.values(config)
    .filter(period => period.enabled).length;

  return (
    <div className={`rounded-2xl border overflow-hidden transition-all duration-200 shadow-xl ${
      isDark
        ? 'border-gray-700 bg-gray-800'
        : 'border-slate-200 bg-white'
    }`}>
      {/* Cabeçalho do card (dia + status + botões) */}
      <div
        className={`p-4 flex items-center justify-between cursor-pointer transition-colors ${
          isDark
            ? 'bg-gray-800 hover:bg-gray-700'
            : 'bg-white hover:bg-slate-50'
        }`}
        onClick={onToggleExpand}
      >
        <div className="flex items-center gap-3">
          {/* Indicador de status */}
          <div className={`w-3 h-3 rounded-full ${hasEnabledPeriods ? 'bg-brand' : isDark ? 'bg-gray-600' : 'bg-slate-300'}`}></div>
          <span className={`font-medium ${
            isDark ? 'text-gray-200' : 'text-slate-800'
          }`}>
            {dayTranslations[day] || day}
          </span>

          {/* Se há períodos ativos, exibe a tag com o total */}
          {hasEnabledPeriods && (
            <span className={`text-xs px-2 py-1 rounded-full font-medium ${
              isDark
                ? 'bg-brand/20 text-brand'
                : 'bg-brand/10 text-brand'
            }`}>
              {enabledPeriodsCount} {enabledPeriodsCount === 1 ? 'período ativo' : 'períodos ativos'}
            </span>
          )}
        </div>
        <div>
          {expanded ? (
            <ChevronUp className={`w-5 h-5 ${
              isDark ? 'text-gray-400' : 'text-slate-500'
            }`} />
          ) : (
            <ChevronDown className={`w-5 h-5 ${
              isDark ? 'text-gray-400' : 'text-slate-500'
            }`} />
          )}
        </div>
      </div>

      {/* Conteúdo expandido */}
      {expanded && (
        <div className="px-4 pb-4">
          {/* Botões de aplicar configuração */}
          <div className="flex justify-end gap-2 mb-4 mt-2">
            <button
              onClick={(e) => {
                e.stopPropagation();
                onApplyToWeekdays();
              }}
              className={`text-xs px-2 py-1.5 rounded-xl transition-colors flex items-center gap-1 ${
                isDark
                  ? 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                  : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
              }`}
            >
              Aplicar aos dias úteis
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onApplyToWeekend();
              }}
              className={`text-xs px-2 py-1.5 rounded-xl transition-colors flex items-center gap-1 ${
                isDark
                  ? 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                  : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
              }`}
            >
              Aplicar ao fim de semana
            </button>
          </div>

          <div className="space-y-4">
            {(['morning','afternoon','night','dawn'] as const).map((period) => {
              const periodCfg = config[period];
              return (
                <div
                  key={period}
                  className={`p-4 rounded-xl transition-all duration-200 border ${
                    periodCfg.enabled
                      ? isDark
                        ? 'bg-brand/10 border-brand/20'
                        : 'bg-brand/5 border-brand/20'
                      : isDark
                        ? 'bg-gray-700 border-gray-600'
                        : 'bg-white border-slate-200'
                  }`}
                >
                  {/* Cabeçalho do período (nome + toggle) */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className={`p-1.5 rounded-full ${
                        periodCfg.enabled
                          ? isDark
                            ? 'bg-brand/20'
                            : 'bg-brand/10'
                          : isDark
                            ? 'bg-gray-600'
                            : 'bg-slate-100'
                      }`}>
                        <PeriodIcon period={period} enabled={periodCfg.enabled} />
                      </div>
                      <div>
                        <span className={`font-medium ${
                          isDark ? 'text-gray-200' : 'text-slate-800'
                        }`}>
                          {periodTranslations[period] || period}
                        </span>
                        <p className={`text-xs mt-0.5 ${
                          isDark ? 'text-gray-400' : 'text-slate-500'
                        }`}>
                          {periodDescriptions[period]}
                        </p>
                      </div>
                    </div>

                    {/* Switch toggle habilita/desabilita período */}
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input
                        type="checkbox"
                        checked={periodCfg.enabled}
                        onChange={() => onTogglePeriod(day, period)}
                        className="sr-only peer"
                      />
                      <div className={`w-11 h-6 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border after:rounded-full after:h-5 after:w-5 after:transition-all ${
                        isDark
                          ? 'bg-gray-600 after:border-gray-500 peer-checked:bg-brand'
                          : 'bg-slate-200 after:border-slate-300 peer-checked:bg-brand'
                      }`}></div>
                    </label>
                  </div>

                  {/* Inputs de horário */}
                  <div className={`grid grid-cols-2 gap-4 mt-4 transition-all duration-300 ${
                    periodCfg.enabled ? 'opacity-100' : 'opacity-50'
                  }`}>
                    <div>
                      <label className={`block text-xs mb-1 font-medium ${
                        isDark ? 'text-gray-400' : 'text-slate-500'
                      }`}>Início</label>
                      <input
                        type="time"
                        disabled={!periodCfg.enabled}
                        className={`w-full border rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/50 focus:border-brand transition-all ${
                          isDark
                            ? 'border-gray-600 bg-gray-700 text-gray-200 disabled:bg-gray-800'
                            : 'border-slate-300 bg-white text-slate-800 disabled:bg-slate-100'
                        }`}
                        value={periodCfg.start}
                        onChange={(e) => onUpdateTime(day, period, 'start', e.target.value)}
                      />
                    </div>
                    <div>
                      <label className={`block text-xs mb-1 font-medium ${
                        isDark ? 'text-gray-400' : 'text-slate-500'
                      }`}>Fim</label>
                      <input
                        type="time"
                        disabled={!periodCfg.enabled}
                        className={`w-full border rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/50 focus:border-brand transition-all ${
                          isDark
                            ? 'border-gray-600 bg-gray-700 text-gray-200 disabled:bg-gray-800'
                            : 'border-slate-300 bg-white text-slate-800 disabled:bg-slate-100'
                        }`}
                        value={periodCfg.end}
                        onChange={(e) => onUpdateTime(day, period, 'end', e.target.value)}
                      />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

const AIResponseWindowsPage: React.FC = () => {
  const { isDark } = useTheme();

  // Estado de loading e erro
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modo de edição
  const [isEditing, setIsEditing] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);

  // Dados locais do form
  const [windowData, setWindowData] = useState<LocalAIWindowData | null>(null);

  // Status de salvamento
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'success' | 'error'>('idle');

  // Estado de expansão dos cards de dia
  const [expandedDays, setExpandedDays] = useState<Record<string, boolean>>({});


  const orderedPeriods = ['dawn', 'morning', 'afternoon', 'night'];

  useEffect(() => {
    (async () => {
      try {
        // Lê company_id do localStorage
        const rawCompanyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
        if (!rawCompanyId) {
          throw new Error('Company ID não encontrado no localStorage.');
        }
        const companyId = parseInt(rawCompanyId, 10);
        if (Number.isNaN(companyId)) {
          throw new Error(`Valor inválido de company_id: ${rawCompanyId}`);
        }

        // Faz a chamada para buscar a config de IA
        const data = await getAIWindow(companyId);

        // Se não vier nada ou se data.id for null, não há registro no banco
        if (!data || data.id == null) {
          // Cria estrutura default
          const baseTimeWindows = getDefaultTimeWindows();
          setWindowData({
            id: null,
            company_id: companyId,
            timezone: 'America/Sao_Paulo',
            time_windows: baseTimeWindows,
          });
          setIsEditing(true);

          // Inicializa o estado de expansão (expande apenas "monday", por exemplo)
          const initialExpandState: Record<string, boolean> = {};
          orderedDays.forEach((day) => {
            initialExpandState[day] = (day === 'monday');
          });
          setExpandedDays(initialExpandState);
        } else {
          // Já existe config no banco. Faz merge com defaults
          const mergedWindows = unifyTimeWindows(data.time_windows);

          setWindowData({
            id: data.id,
            company_id: data.company_id,
            timezone: data.timezone,
            time_windows: mergedWindows,
          });

          // Inicia todos fechados, se preferir
          const initialExpandState: Record<string, boolean> = {};
          orderedDays.forEach((day) => {
            initialExpandState[day] = false;
          });
          setExpandedDays(initialExpandState);
        }
      } catch (err: any) {
        console.error('[AIWindowsPage] Erro ao obter config IA:', err);
        setError(err.message || 'Erro ao obter configuração da IA');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // Salvar
  const handleSave = async () => {
    if (!windowData) return;
    setSaveStatus('saving');

    try {
      // Se já existe ID => update
      if (windowData.id) {
        await updateAIWindow(windowData.id, {
          timezone: windowData.timezone,
          time_windows: windowData.time_windows,
        });
      } else {
        // Cria config nova
        const resp = await createAIWindow({
          company_id: windowData.company_id,
          timezone: windowData.timezone,
          time_windows: windowData.time_windows,
        });
        // resp => { id, message }
        setWindowData(prev => prev ? { ...prev, id: resp.id } : null);
      }
      setSaveStatus('success');
      setIsEditing(false);
    } catch (err: any) {
      console.error('[AIWindowsPage] Erro ao salvar config IA:', err);
      setSaveStatus('error');
    } finally {
      // Reseta status depois de um tempo
      setTimeout(() => setSaveStatus('idle'), 2000);
    }
  };

  // Excluir
  const handleDelete = async () => {
    if (!windowData || !windowData.id) {
      alert('Nenhuma config existente para deletar.');
      return;
    }

    try {
      await deleteAIWindow(windowData.id);
      // Reseta estado local para "sem config"
      const baseTimeWindows = getDefaultTimeWindows();
      setWindowData({
        id: null,
        company_id: windowData.company_id,
        timezone: 'America/Sao_Paulo',
        time_windows: baseTimeWindows,
      });
      setIsEditing(true);
      setShowDeleteModal(false);
    } catch (err: any) {
      console.error('[AIWindowsPage] Erro ao deletar config IA:', err);
      alert('Erro ao deletar configuração IA.');
    }
  };

  // Toggle habilitado/inabilitado
  const handleTogglePeriod = (day: string, period: keyof DayTimeConfig) => {
    if (!windowData) return;
    const clone = { ...windowData };
    const dayConfig = clone.time_windows[day];
    if (!dayConfig) return;

    // Inverte o enabled
    dayConfig[period].enabled = !dayConfig[period].enabled;
    setWindowData(clone);
  };

  // Atualiza horário de início/fim
  const handleUpdateTime = (
    day: string,
    period: keyof DayTimeConfig,
    field: 'start' | 'end',
    value: string
  ) => {
    if (!windowData) return;
    const clone = { ...windowData };
    const dayConfig = clone.time_windows[day];
    if (!dayConfig) return;

    dayConfig[period][field] = value;
    setWindowData(clone);
  };

  // Toggle de expansão do dia
  const toggleDayExpand = (day: string) => {
    setExpandedDays(prev => ({
      ...prev,
      [day]: !prev[day]
    }));
  };

  // Aplicar configuração aos dias úteis
  const applyToWeekdays = (fromDay: string) => {
    if (!windowData) return;

    const weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'];
    const sourceConfig = windowData.time_windows[fromDay];

    if (!sourceConfig) return;

    const clone = { ...windowData };
    for (const day of weekdays) {
      if (day !== fromDay) {
        clone.time_windows[day] = JSON.parse(JSON.stringify(sourceConfig));
      }
    }

    setWindowData(clone);
  };

  // Aplicar configuração ao fim de semana
  const applyToWeekend = (fromDay: string) => {
    if (!windowData) return;

    const weekend = ['saturday', 'sunday'];
    const sourceConfig = windowData.time_windows[fromDay];

    if (!sourceConfig) return;

    const clone = { ...windowData };
    for (const day of weekend) {
      if (day !== fromDay) {
        clone.time_windows[day] = JSON.parse(JSON.stringify(sourceConfig));
      }
    }

    setWindowData(clone);
  };

  if (loading) {
    return (
      <div className={`min-h-screen flex items-center justify-center ${
        isDark ? 'bg-brand' : 'bg-gradient-to-b from-slate-50 to-white'
      }`}>
        <div className="flex flex-col items-center space-y-4">
          <div className="w-12 h-12 border-4 border-brand/30 border-t-brand rounded-full animate-spin"></div>
          <span className={`font-medium ${
            isDark ? 'text-gray-300' : 'text-slate-600'
          }`}>Carregando configurações da IA...</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`min-h-screen w-full ${
      isDark
        ? 'bg-brand text-gray-200'
        : 'bg-gradient-to-b from-slate-50 to-white text-slate-800'
    }`}>
      {/* Header */}
      <header className={`sticky top-0 z-20 border-b px-4 py-3 shadow-sm backdrop-blur ${
        isDark
          ? 'border-gray-700 bg-brand/90'
          : 'border-slate-200 bg-white/90'
      }`}>
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3">
          <div>
            <h1 className={`text-2xl font-bold tracking-tight ${
              isDark ? 'text-white' : 'text-slate-800'
            }`}>Janelas de Resposta IA</h1>
            <p className={`text-sm ${
              isDark ? 'text-gray-400' : 'text-slate-500'
            }`}>Defina quando o bot deve responder automaticamente aos clientes.</p>
          </div>

          <div className="flex items-center gap-3">
            <span className={`rounded-full px-4 py-2 text-sm font-medium ${
              windowData?.id
                ? "bg-brand/10 text-brand"
                : isDark ? "bg-gray-700 text-gray-300" : "bg-gray-100 text-slate-600"
            }`}>
              {windowData?.id ? "Ativo" : "Rascunho"}
            </span>

            <div className="flex gap-2">
              {windowData?.id && !isEditing ? (
                <>
                  <button
                    onClick={() => setIsEditing(true)}
                    className={`rounded-xl border px-3 py-2 transition-colors ${
                      isDark
                        ? 'border-gray-600 bg-gray-700 text-gray-200 hover:bg-gray-600'
                        : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
                    }`}
                  >
                    <Edit2 className="w-4 h-4 mr-1 inline" />
                    Editar
                  </button>
                  <button
                    onClick={() => setShowDeleteModal(true)}
                    className="rounded-xl bg-red-500 px-3 py-2 text-white hover:bg-red-600 transition-colors"
                  >
                    <Trash2 className="w-4 h-4 mr-1 inline" />
                    Excluir
                  </button>
                </>
              ) : (
                <button
                  onClick={handleSave}
                  disabled={!windowData || saveStatus === 'saving'}
                  className={`px-3 py-2 rounded-xl transition-colors ${
                    (!windowData || saveStatus === 'saving')
                      ? 'bg-brand/70 text-white cursor-not-allowed'
                      : 'bg-brand text-white hover:bg-brand/90'
                  }`}
                >
                  {saveStatus === 'saving' ? (
                    <>
                      <Loader className="w-4 h-4 animate-spin mr-1 inline" />
                      Salvando...
                    </>
                  ) : (
                    <>
                      <Save className="w-4 h-4 mr-1 inline" />
                      Salvar
                    </>
                  )}
                </button>
              )}
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl p-4">
        {/* Status Messages */}
        {saveStatus === 'success' && (
          <div className={`mb-4 flex items-center gap-2 px-4 py-3 rounded-xl border ${
            isDark ? 'bg-green-900/20 text-green-400 border-green-700' : 'bg-green-50 text-green-700 border-green-200'
          }`}>
            <CheckCircle className="w-5 h-5" />
            <span>Configuração salva com sucesso.</span>
          </div>
        )}

        {saveStatus === 'error' && (
          <div className={`mb-4 flex items-center gap-2 px-4 py-3 rounded-xl border ${
            isDark ? 'bg-red-900/20 text-red-400 border-red-700' : 'bg-red-50 text-red-700 border-red-200'
          }`}>
            <AlertCircle className="w-5 h-5" />
            <span>Erro ao salvar a configuração. Verifique os logs.</span>
          </div>
        )}

        {error && (
          <div className={`mb-4 px-4 py-3 rounded-xl border ${
            isDark ? 'bg-red-900/20 text-red-400 border-red-700' : 'bg-red-50 text-red-700 border-red-200'
          }`}>
            <div className="flex items-center gap-2">
              <AlertCircle className="w-5 h-5" />
              <strong>Erro:</strong> {error}
            </div>
          </div>
        )}

        {/* Warning if no config and not editing */}
        {!windowData?.id && !isEditing && (
          <div className={`mb-4 p-4 rounded-xl border ${
            isDark ? 'bg-yellow-900/20 text-yellow-400 border-yellow-700' : 'bg-yellow-50 text-yellow-800 border-yellow-200'
          }`}>
            <p>
              Não há configuração existente. Clique em <strong>Salvar</strong> para criar uma nova.
            </p>
          </div>
        )}

        {/* Formulário de edição (caso esteja em edição ou não exista config) */}
        {windowData && (isEditing || !windowData.id) && (
          <div className="space-y-6">
            {/* Seleção de Fuso Horário */}
            <div className={`rounded-2xl shadow-xl p-6 border ${
              isDark ? 'border-gray-700 bg-gray-800' : 'border-slate-200 bg-white'
            }`}>
              <div className="flex items-center gap-2 mb-4">
                <Clock className="w-5 h-5 text-brand" />
                <h2 className={`text-lg font-medium ${
                  isDark ? 'text-white' : 'text-slate-800'
                }`}>Fuso Horário</h2>
              </div>
              <div className="max-w-md">
                <p className={`text-sm mb-3 ${
                  isDark ? 'text-gray-300' : 'text-slate-600'
                }`}>
                  Todos os horários configurados serão baseados neste fuso horário
                </p>
                <select
                  className={`w-full border rounded-xl p-2.5 focus:ring-2 focus:ring-brand/50 focus:border-brand transition-all ${
                    isDark
                      ? 'border-gray-600 bg-gray-700 text-gray-200'
                      : 'border-slate-300 bg-white text-slate-800'
                  }`}
                  value={windowData.timezone}
                  onChange={(e) => {
                    setWindowData((prev) => prev ? { ...prev, timezone: e.target.value } : null);
                  }}
                >
                  <option value="America/Sao_Paulo">America/Sao_Paulo (GMT-3)</option>
                  <option value="America/Manaus">America/Manaus (GMT-4)</option>
                  <option value="America/Rio_Branco">America/Rio_Branco (GMT-5)</option>
                  <option value="America/Recife">America/Recife (GMT-3)</option>
                </select>
              </div>
            </div>

            {/* Programação Semanal */}
            <div className={`rounded-2xl shadow-xl p-6 border ${
              isDark ? 'border-gray-700 bg-gray-800' : 'border-slate-200 bg-white'
            }`}>
              <div className="flex items-center gap-2 mb-4">
                <Calendar className="w-5 h-5 text-brand" />
                <h2 className={`text-lg font-medium ${
                  isDark ? 'text-white' : 'text-slate-800'
                }`}>Programação Semanal</h2>
              </div>

              <div className={`p-4 rounded-xl border mb-6 flex gap-3 ${
                isDark
                  ? 'bg-brand/10 border-brand/20'
                  : 'bg-brand/5 border-brand/20'
              }`}>
                <HelpCircle className="w-5 h-5 text-brand flex-shrink-0 mt-0.5" />
                <p className={`text-sm ${
                  isDark ? 'text-brand/90' : 'text-brand'
                }`}>
                  Configure os períodos em que a IA deve responder para cada dia da semana.
                  Ative os períodos desejados e defina o horário de início e fim.
                </p>
              </div>

              {/* Visualização em lista */}
              <div className="space-y-3">
                {orderedDays.map((day) => (
                  <DayCard
                    key={day}
                    day={day}
                    config={windowData.time_windows[day]}
                    onTogglePeriod={handleTogglePeriod}
                    onUpdateTime={handleUpdateTime}
                    expanded={expandedDays[day] || false}
                    onToggleExpand={() => toggleDayExpand(day)}
                    onApplyToWeekdays={() => applyToWeekdays(day)}
                    onApplyToWeekend={() => applyToWeekend(day)}
                    isDark={isDark}
                  />
                ))}
              </div>
            </div>
            </div>
          )}

          {/* Visualização (modo não-edição) */}
          {windowData?.id && !isEditing && (
            <div className="space-y-6">
              {/* Fuso Horário */}
              <div className={`rounded-2xl shadow-xl p-6 border ${
                isDark ? 'border-gray-700 bg-gray-800' : 'border-slate-200 bg-white'
              }`}>
                <div className="flex items-center gap-2 mb-4">
                  <Clock className="w-5 h-5 text-brand" />
                  <h2 className={`text-lg font-medium ${
                    isDark ? 'text-white' : 'text-slate-800'
                  }`}>Fuso Horário</h2>
                </div>
                <div className={`p-3 rounded-xl border ${
                  isDark ? 'bg-gray-700 border-gray-600 text-gray-200' : 'bg-slate-50 border-slate-200 text-slate-700'
                }`}>
                  <p>{windowData.timezone}</p>
                </div>
              </div>

              {/* Períodos Configurados (apenas leitura) */}
              <div className={`rounded-2xl shadow-xl p-6 border ${
                isDark ? 'border-gray-700 bg-gray-800' : 'border-slate-200 bg-white'
              }`}>
                <div className="flex items-center gap-2 mb-6">
                  <Calendar className="w-5 h-5 text-brand" />
                  <h2 className={`text-lg font-medium ${
                    isDark ? 'text-white' : 'text-slate-800'
                  }`}>Períodos de Disponibilidade</h2>
                </div>

                <div className="grid md:grid-cols-2 gap-4">
                  {orderedDays.map((day) => {
                    const config = windowData.time_windows[day];
                    // Filtra apenas os períodos habilitados
                    const enabledPeriods = Object.entries(config)
                    .filter(([_, periodCfg]) => periodCfg.enabled)
                    .map(([period, periodCfg]) => ({ period, ...periodCfg }))
                    .sort((a, b) => {
                      return orderedPeriods.indexOf(a.period) - orderedPeriods.indexOf(b.period);
                    });

                    const hasEnabledPeriods = enabledPeriods.length > 0;

                    return (
                      <div key={day} className={`p-4 rounded-xl border ${hasEnabledPeriods ? isDark ? 'border-brand/20 bg-brand/10' : 'border-brand/20 bg-brand/5' : isDark ? 'border-gray-700 bg-gray-700' : 'border-slate-200 bg-slate-50'}`}>
                        <div className="flex items-center gap-2 mb-3">
                          <div className={`w-3 h-3 rounded-full ${hasEnabledPeriods ? 'bg-brand' : isDark ? 'bg-gray-600' : 'bg-slate-300'}`}></div>
                          <h3 className={`font-medium ${
                            isDark ? 'text-gray-200' : 'text-slate-800'
                          }`}>
                            {dayTranslations[day] || day}
                          </h3>
                          {hasEnabledPeriods && (
                            <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${
                              isDark
                                ? 'bg-gray-800 text-brand border-brand/30'
                                : 'bg-white text-brand border-brand/30'
                            }`}>
                              {enabledPeriods.length} {enabledPeriods.length === 1 ? 'período' : 'períodos'}
                            </span>
                          )}
                        </div>

                        {hasEnabledPeriods ? (
                          <div className="space-y-2 mt-3">
                            {enabledPeriods.map(({ period, start, end }) => (
                              <div key={period} className={`flex items-center gap-3 text-sm p-2 rounded-xl border ${
                                isDark
                                  ? 'bg-gray-800 border-brand/20'
                                  : 'bg-white border-brand/20'
                              }`}>
                                <PeriodIcon period={period} className="w-4 h-4" />
                                <span className={`font-medium ${
                                  isDark ? 'text-gray-300' : 'text-slate-700'
                                }`}>
                                  {periodTranslations[period] || period}
                                </span>
                                <span className="text-brand font-medium ml-auto">
                                  {start} — {end}
                                </span>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className={`text-sm italic mt-2 ${
                            isDark ? 'text-gray-400' : 'text-slate-500'
                          }`}>
                            Sem períodos ativos
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Se nenhum período está habilitado em todos os dias */}
                {Object.values(windowData.time_windows).every(dayConfig =>
                  Object.values(dayConfig).every(periodCfg => !periodCfg.enabled)
                ) && (
                  <div className={`p-4 border rounded-xl mt-6 flex gap-3 ${
                    isDark
                      ? 'bg-brand/10 border-brand/20'
                      : 'bg-brand/5 border-brand/20'
                  }`}>
                    <HelpCircle className="w-5 h-5 text-brand flex-shrink-0 mt-0.5" />
                    <p className={`${
                      isDark ? 'text-brand/90' : 'text-brand'
                    }`}>
                      Não há períodos de resposta configurados. Clique em <strong>Editar</strong> para adicionar períodos.
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}
      </main>

      {/* Modal de confirmação de exclusão */}
      <ConfirmDeleteModal
        isOpen={showDeleteModal}
        onClose={() => setShowDeleteModal(false)}
        onConfirm={handleDelete}
        title="Excluir configuração de janelas de resposta IA"
        message="Tem certeza que deseja excluir toda a configuração de janelas de resposta da IA? Esta ação não pode ser desfeita e você precisará configurar tudo novamente."
        confirmText="Sim, excluir"
        cancelText="Cancelar"
      />
    </div>
  );
  };

  export default AIResponseWindowsPage;