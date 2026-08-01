import React, { useMemo, useState } from 'react';
import {
  Activity,
  AlertCircle,
  ArrowUpRight,
  BarChart3,
  CalendarRange,
  ChevronDown,
  Clock,
  DollarSign,
  Filter,
  LineChart as LineChartIcon,
  PieChart,
  RefreshCw,
  Share2,
  Target,
  Table2,
  Users,
} from 'lucide-react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type {
  DailyFunnelItem,
  FunnelBySourceItem,
  FunnelMetricsResponse,
  ProjectionsResponse,
  TimelineEvent,
} from '../../../services/api';
import type { PipelineStage } from '../../../services/crmApi';
import BrowserDateTime from '../../BrowserDateTime';
import './CommandDashboard.css';

export interface DashboardStageRow extends PipelineStage {
  color: string;
  count: number;
  percentage: number;
  percentageBaseCount: number;
  percentageBaseLabel: string;
  reachedCount: number;
}

export interface DashboardDateRange {
  endDate: string;
  startDate: string;
}

interface CommandDashboardProps {
  averageTimeToSale: string;
  companyName: string;
  conversionRate: number;
  dailyFunnelData: DailyFunnelItem[];
  dateRange: DashboardDateRange;
  errorMessage?: string;
  funnelBySource: FunnelBySourceItem[];
  isDark: boolean;
  mediaSource: string;
  onDateChange: (startDate: string, endDate: string) => void;
  onRefresh: () => void;
  onShare: () => void;
  onSourceChange: (source: string) => void;
  onToggleFilters: () => void;
  periodLabel: string;
  projectionsData: ProjectionsResponse | null;
  revenueProjectionPercent: number;
  selectedSourceLabel: string;
  shareError?: string | null;
  showFilters: boolean;
  stageRows: DashboardStageRow[];
  stages: PipelineStage[];
  stats: FunnelMetricsResponse;
  timelineEvents: TimelineEvent[];
  totalCurrentStageLeads: number;
}

const SOURCE_OPTIONS = [
  { label: 'Todas as origens', value: '' },
  { label: 'Instagram', value: 'instagram' },
  { label: 'Facebook', value: 'facebook' },
  { label: 'Google', value: 'google' },
  { label: 'TikTok', value: 'tiktok' },
  { label: 'Indicação', value: 'indicacao' },
];

const CHART_COLORS = ['#2563eb', '#0f766e', '#7c3aed', '#b45309', '#db2777', '#0891b2'];

const formatDisplayDate = (isoDate: string) => {
  const [year, month, day] = isoDate.split('-');
  if (!year || !month || !day) return isoDate;
  return `${day}/${month}/${year}`;
};

const formatDateToYYYYMMDD = (date: Date) => date.toISOString().split('T')[0];

const formatNumber = (value: number) => new Intl.NumberFormat('pt-BR').format(value);

const formatCompactNumber = (value: number) =>
  new Intl.NumberFormat('pt-BR', {
    maximumFractionDigits: 1,
    notation: Math.abs(value) >= 10000 ? 'compact' : 'standard',
  }).format(value);

const formatCurrency = (value: number) =>
  value.toLocaleString('pt-BR', {
    currency: 'BRL',
    maximumFractionDigits: 0,
    style: 'currency',
  });

const clampPercent = (value: number) => Math.max(0, Math.min(value, 100));

const getDailyValue = (item: DailyFunnelItem, key: string) => {
  const value = item[key];
  return typeof value === 'number' ? value : 0;
};

const getEventLabel = (eventType: string) => {
  const type = eventType.toLowerCase();
  if (type.includes('lead')) return 'Novo lead';
  if (type.includes('agendamento')) return 'Agendamento';
  if (type.includes('venda')) return 'Venda realizada';
  if (type.includes('comparecimento')) return 'Comparecimento';
  return eventType;
};

const getEventIcon = (eventType: string) => {
  const type = eventType.toLowerCase();
  if (type.includes('lead')) return Users;
  if (type.includes('agendamento')) return CalendarRange;
  if (type.includes('venda')) return DollarSign;
  if (type.includes('comparecimento')) return Target;
  return Activity;
};

const getStartOfCurrentMonth = () => {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), 1);
};

const getEndOfCurrentMonth = () => {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth() + 1, 0);
};

interface DateRangePickerProps {
  endDate: string;
  onDateChange: (startDate: string, endDate: string) => void;
  startDate: string;
}

const DateRangePicker: React.FC<DateRangePickerProps> = ({ endDate, onDateChange, startDate }) => {
  const [isOpen, setIsOpen] = useState(false);

  const ranges = [
    {
      label: 'Hoje',
      getDates: () => {
        const today = new Date();
        return {
          end: formatDateToYYYYMMDD(today),
          start: formatDateToYYYYMMDD(today),
        };
      },
    },
    {
      label: 'Semana',
      getDates: () => {
        const now = new Date();
        const start = new Date(now);
        start.setDate(now.getDate() - now.getDay());
        const end = new Date(now);
        end.setDate(now.getDate() + (6 - now.getDay()));
        return {
          end: formatDateToYYYYMMDD(end),
          start: formatDateToYYYYMMDD(start),
        };
      },
    },
    {
      label: 'Mês',
      getDates: () => ({
        end: formatDateToYYYYMMDD(getEndOfCurrentMonth()),
        start: formatDateToYYYYMMDD(getStartOfCurrentMonth()),
      }),
    },
  ];

  const handlePreset = (range: (typeof ranges)[number]) => {
    const dates = range.getDates();
    onDateChange(dates.start, dates.end);
    setIsOpen(false);
  };

  return (
    <div className="command-date-picker">
      <button
        aria-expanded={isOpen}
        className="command-date-trigger"
        onClick={() => setIsOpen((current) => !current)}
        type="button"
      >
        <CalendarRange />
        <span className="command-date-label">{formatDisplayDate(startDate)} - {formatDisplayDate(endDate)}</span>
        <ChevronDown />
      </button>

      {isOpen && (
        <div className="command-date-menu" role="dialog" aria-label="Selecionar período">
          <p className="command-eyebrow">Períodos rápidos</p>
          <div className="command-date-presets">
            {ranges.map((range) => (
              <button
                className="command-button command-button--ghost"
                key={range.label}
                onClick={() => handlePreset(range)}
                type="button"
              >
                {range.label}
              </button>
            ))}
          </div>

          <div className="command-date-custom">
            <label className="command-field">
              <span className="command-label">Início</span>
              <input
                className="command-date-input"
                onChange={(event) => onDateChange(event.target.value, endDate)}
                type="date"
                value={startDate}
              />
            </label>
            <label className="command-field">
              <span className="command-label">Fim</span>
              <input
                className="command-date-input"
                onChange={(event) => onDateChange(startDate, event.target.value)}
                type="date"
                value={endDate}
              />
            </label>
          </div>
        </div>
      )}
    </div>
  );
};

interface IconButtonProps {
  children: React.ReactNode;
  label: string;
  onClick: () => void;
}

const IconButton: React.FC<IconButtonProps> = ({ children, label, onClick }) => (
  <button
    aria-label={label}
    className="command-icon-button"
    data-tooltip={label}
    onClick={onClick}
    title={label}
    type="button"
  >
    {children}
  </button>
);

interface PanelProps {
  action?: React.ReactNode;
  children: React.ReactNode;
  description?: string;
  icon?: React.ReactNode;
  title: string;
}

const Panel: React.FC<PanelProps> = ({ action, children, description, icon, title }) => (
  <section className="command-panel">
    <header className="command-panel-header">
      <div>
        <h2 className="command-panel-title">
          {icon}
          <span>{title}</span>
        </h2>
        {description && <p className="command-panel-kicker">{description}</p>}
      </div>
      {action}
    </header>
    <div className="command-panel-body">{children}</div>
  </section>
);

interface KpiCardProps {
  color: string;
  description?: string;
  icon: React.ReactNode;
  percentage?: number;
  title: string;
  value: string;
}

const KpiCard: React.FC<KpiCardProps> = ({ color, description, icon, percentage, title, value }) => (
  <article className="command-kpi-card" style={{ '--kpi-accent': color } as React.CSSProperties}>
    <div className="command-kpi-top">
      <div className="command-kpi-text">
        <span className="command-kpi-label">{title}</span>
        <div className="command-kpi-value">{value}</div>
      </div>
      <div className="command-kpi-icon">{icon}</div>
    </div>
    <div className="command-kpi-footer">
      {percentage !== undefined && <span className="command-kpi-chip">{percentage.toFixed(1)}%</span>}
      {description && <span>{description}</span>}
    </div>
  </article>
);

interface FunnelTableProps {
  stageRows: DashboardStageRow[];
  stats: FunnelMetricsResponse;
}

const FunnelTable: React.FC<FunnelTableProps> = ({ stageRows, stats }) => (
  <div className="command-table">
    <div className="command-table-head">
      <span>Etapa</span>
      <span className="command-row-value">Total</span>
      <span className="command-row-muted">Conv.</span>
    </div>
    <div
      className="command-table-row"
      style={{ '--row-color': '#2563eb' } as React.CSSProperties}
    >
      <div>
        <div className="command-row-title">
          <span className="command-row-dot" />
          <span className="command-row-name">Leads</span>
        </div>
        <div className="command-progress-note">Entrada do funil</div>
      </div>
      <span className="command-row-value">{formatNumber(stats.totalLeads)}</span>
      <span className="command-row-muted">100%</span>
    </div>
    {stageRows.map((stage) => (
      <div
        className="command-table-row"
        key={stage.id}
        style={{ '--row-color': stage.color } as React.CSSProperties}
      >
        <div>
          <div className="command-row-title">
            <span className="command-row-dot" />
            <span className="command-row-name">{stage.name}</span>
          </div>
          <div className="command-progress">
            <div
              className="command-progress-fill"
              style={{ width: `${clampPercent(stage.percentage)}%` }}
            />
          </div>
          <div className="command-progress-note">Base: {stage.percentageBaseLabel}</div>
        </div>
        <span className="command-row-value">{formatNumber(stage.count)}</span>
        <span className="command-row-muted">{stage.percentage.toFixed(1)}%</span>
      </div>
    ))}
  </div>
);

interface TimeSeriesPanelProps {
  dailyFunnelData: DailyFunnelItem[];
  isDark: boolean;
  stages: PipelineStage[];
}

const TimeSeriesPanel: React.FC<TimeSeriesPanelProps> = ({ dailyFunnelData, isDark, stages }) => {
  const chartData = useMemo(
    () =>
      dailyFunnelData.map((item) => {
        const [year, month, day] = item.date.split('-');
        const date = new Date(Number(year), Number(month) - 1, Number(day));
        return {
          ...item,
          displayDate: date.toLocaleDateString('pt-BR', {
            day: '2-digit',
            month: '2-digit',
          }),
        };
      }),
    [dailyFunnelData],
  );

  const tooltipStyle: React.CSSProperties = {
    backgroundColor: isDark ? '#08092f' : '#ffffff',
    border: `1px solid ${isDark ? 'rgba(255,255,255,0.14)' : 'rgba(2,3,35,0.12)'}`,
    borderRadius: 12,
    boxShadow: '0 18px 52px rgba(2,3,35,0.16)',
    color: isDark ? '#f7f7f7' : '#020323',
    fontSize: 12,
  };

  return (
    <Panel
      action={<span className="command-badge"><LineChartIcon /> Linha diária</span>}
      description="Movimento de entrada e avanço no funil durante o período."
      icon={<BarChart3 />}
      title="Evolução diária"
    >
      {chartData.length === 0 ? (
        <div className="command-empty">Sem dados diários para o período selecionado.</div>
      ) : (
        <>
          <div className="command-chart">
            <ResponsiveContainer height="100%" width="100%">
              <LineChart data={chartData} margin={{ bottom: 0, left: 0, right: 10, top: 8 }}>
                <CartesianGrid
                  stroke={isDark ? 'rgba(255,255,255,0.10)' : 'rgba(2,3,35,0.10)'}
                  strokeDasharray="3 3"
                  vertical={false}
                />
                <XAxis
                  axisLine={false}
                  dataKey="displayDate"
                  tick={{ fill: isDark ? 'rgba(247,247,247,0.50)' : 'rgba(2,3,35,0.48)', fontSize: 12 }}
                  tickLine={false}
                />
                <YAxis
                  axisLine={false}
                  tick={{ fill: isDark ? 'rgba(247,247,247,0.50)' : 'rgba(2,3,35,0.48)', fontSize: 12 }}
                  tickLine={false}
                  width={34}
                />
                <RechartsTooltip contentStyle={tooltipStyle} />
                <Line
                  dataKey="leads"
                  dot={false}
                  name="Leads"
                  stroke={isDark ? '#f7f7f7' : '#020323'}
                  strokeWidth={2.5}
                  type="monotone"
                />
                {stages.map((stage, index) => (
                  <Line
                    dataKey={(item: DailyFunnelItem) => getDailyValue(item, stage.name)}
                    dot={false}
                    key={stage.id}
                    name={stage.name}
                    stroke={stage.color || CHART_COLORS[index % CHART_COLORS.length]}
                    strokeWidth={2}
                    type="monotone"
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="command-chart-footer">
            <div className="command-compact-stat">
              <span>Intervalo</span>
              <strong>Diário</strong>
            </div>
            <div className="command-compact-stat">
              <span>Pontos</span>
              <strong>{formatNumber(chartData.length)}</strong>
            </div>
            <div className="command-compact-stat">
              <span>Séries</span>
              <strong>{formatNumber(stages.length + 1)}</strong>
            </div>
          </div>
        </>
      )}
    </Panel>
  );
};

interface SourcesPanelProps {
  sources: FunnelBySourceItem[];
}

const SourcesPanel: React.FC<SourcesPanelProps> = ({ sources }) => {
  const total = sources.reduce((sum, item) => sum + item.totalLeads, 0);
  const mappedSources = sources.map((source, index) => ({
    ...source,
    color: CHART_COLORS[index % CHART_COLORS.length],
    percentage: total ? Math.round((source.totalLeads / total) * 100) : 0,
  }));

  return (
    <Panel
      description="Canais que trouxeram leads no período."
      icon={<Table2 />}
      title="Origem dos leads"
    >
      {sources.length === 0 ? (
        <div className="command-empty">Sem origem de lead registrada neste período.</div>
      ) : (
        <>
          <div className="command-source-summary">
            <div className="command-compact-stat">
              <span>Fontes</span>
              <strong>{formatNumber(sources.length)}</strong>
            </div>
            <div className="command-compact-stat">
              <span>Leads atribuídos</span>
              <strong>{formatNumber(total)}</strong>
            </div>
          </div>
          <div className="command-source-list">
            {mappedSources.map((source, index) => (
              <div
                className="command-source-item"
                key={`${source.fonte || 'N/A'}-${index}`}
                style={{ '--row-color': source.color } as React.CSSProperties}
              >
                <div className="command-source-line">
                  <div className="command-source-name">
                    <span className="command-row-dot" />
                    <span>{source.fonte || 'N/A'}</span>
                  </div>
                  <span className="command-source-count">
                    {formatNumber(source.totalLeads)} · {source.percentage}%
                  </span>
                </div>
                <div className="command-progress">
                  <div className="command-progress-fill" style={{ width: `${source.percentage}%` }} />
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </Panel>
  );
};

interface ForecastPanelProps {
  projectionsData: ProjectionsResponse | null;
  revenueProjectionPercent: number;
}

const ForecastPanel: React.FC<ForecastPanelProps> = ({ projectionsData, revenueProjectionPercent }) => {
  if (!projectionsData) {
    return (
      <Panel description="Ritmo atual comparado à projeção." icon={<ArrowUpRight />} title="Projeções do mês">
        <div className="command-empty">Carregando projeções...</div>
      </Panel>
    );
  }

  const rows = Object.entries(projectionsData.stages || {}).map(([stageName, data], index) => ({
    color: CHART_COLORS[index % CHART_COLORS.length],
    name: stageName,
    percentage: data.projection > 0 ? clampPercent((data.soFar / data.projection) * 100) : 0,
    projection: data.projection,
    soFar: data.soFar,
  }));

  return (
    <Panel description="Ritmo atual comparado à projeção." icon={<ArrowUpRight />} title="Projeções do mês">
      <div className="command-forecast-list">
        {rows.map((row) => (
          <div
            className="command-forecast-row"
            key={row.name}
            style={{ '--row-color': row.color } as React.CSSProperties}
          >
            <div className="command-forecast-line">
              <span className="command-forecast-name">{row.name}</span>
              <span className="command-forecast-values">
                Atual {formatNumber(row.soFar)} / Proj. {formatNumber(row.projection)}
              </span>
            </div>
            <div className="command-progress">
              <div className="command-progress-fill" style={{ width: `${row.percentage}%` }} />
            </div>
          </div>
        ))}

        <div
          className="command-forecast-row"
          style={{ '--row-color': '#0f766e' } as React.CSSProperties}
        >
          <div className="command-forecast-line">
            <span className="command-forecast-name">Faturamento</span>
            <span className="command-forecast-values">
              Atual {formatCurrency(projectionsData.faturadoSoFar)} / Proj. {formatCurrency(projectionsData.faturadoProjection)}
            </span>
          </div>
          <div className="command-progress">
            <div className="command-progress-fill" style={{ width: `${revenueProjectionPercent}%` }} />
          </div>
        </div>
      </div>
    </Panel>
  );
};

interface TimelinePanelProps {
  events: TimelineEvent[];
}

const TimelinePanel: React.FC<TimelinePanelProps> = ({ events }) => (
  <Panel description="Sinais recentes para investigação rápida." icon={<Clock />} title="Atividades recentes">
    {events.length === 0 ? (
      <div className="command-empty">Nenhum evento recente encontrado.</div>
    ) : (
      <div className="command-timeline">
        {events.slice(0, 6).map((event) => {
          const EventIcon = getEventIcon(event.event_type);
          return (
            <article className="command-timeline-item" key={`${event.entity_id}-${event.event_date}`}>
              <div className="command-timeline-icon">
                <EventIcon />
              </div>
              <div className="command-timeline-content">
                <div className="command-timeline-heading">
                  <span className="command-timeline-title">{getEventLabel(event.event_type)}</span>
                  <BrowserDateTime
                    className="command-timeline-time"
                    value={event.event_date}
                    variant="dateTime"
                  />
                </div>
                <p className="command-timeline-description">{event.descricao || 'Sem descrição'}</p>
              </div>
            </article>
          );
        })}
      </div>
    )}
  </Panel>
);

export const CommandDashboardLoading: React.FC<{ isDark: boolean }> = ({ isDark }) => (
  <div className={`command-dashboard ${isDark ? 'command-dashboard--dark' : ''}`}>
    <div className="command-loading-page">
      <div className="command-loading-box">
        <div className="command-spinner" />
        <p>Carregando métricas...</p>
      </div>
    </div>
  </div>
);

interface CommandDashboardErrorProps {
  error: string;
  isDark: boolean;
  onRefresh: () => void;
}

export const CommandDashboardError: React.FC<CommandDashboardErrorProps> = ({ error, isDark, onRefresh }) => (
  <div className={`command-dashboard ${isDark ? 'command-dashboard--dark' : ''}`}>
    <div className="command-error-page">
      <div className="command-error-box">
        <AlertCircle />
        <h1 className="command-title">Erro ao carregar dados</h1>
        <p className="command-description">{error}</p>
        <button className="command-button command-button--primary" onClick={onRefresh} type="button">
          <RefreshCw />
          Tentar novamente
        </button>
      </div>
    </div>
  </div>
);

const CommandDashboard: React.FC<CommandDashboardProps> = ({
  averageTimeToSale,
  companyName,
  conversionRate,
  dailyFunnelData,
  dateRange,
  errorMessage,
  funnelBySource,
  isDark,
  mediaSource,
  onDateChange,
  onRefresh,
  onShare,
  onSourceChange,
  onToggleFilters,
  periodLabel,
  projectionsData,
  revenueProjectionPercent,
  selectedSourceLabel,
  shareError,
  showFilters,
  stageRows,
  stages,
  stats,
  timelineEvents,
  totalCurrentStageLeads,
}) => {
  const topStages = stageRows.slice(0, 5);

  return (
    <main className={`command-dashboard ${isDark ? 'command-dashboard--dark' : ''}`}>
      <div className="command-dashboard-shell">
        <header className="command-toolbar">
          <div>
            <p className="command-eyebrow">Dashboard comercial</p>
            <div className="command-title-row">
              <h1 className="command-title">Visão geral</h1>
              <span className="command-badge">
                <span className="command-badge-dot" />
                {selectedSourceLabel}
              </span>
            </div>
            <p className="command-description">
              Performance de {companyName || 'Empresa'} em {periodLabel}. Receita, avanço do funil e canais em uma leitura operacional.
            </p>
          </div>

          <div className="command-toolbar-actions">
            <DateRangePicker
              endDate={dateRange.endDate}
              onDateChange={onDateChange}
              startDate={dateRange.startDate}
            />
            <IconButton label={showFilters ? 'Ocultar filtros' : 'Mostrar filtros'} onClick={onToggleFilters}>
              <Filter />
            </IconButton>
            <IconButton label="Compartilhar relatório" onClick={onShare}>
              <Share2 />
            </IconButton>
            <IconButton label="Atualizar métricas" onClick={onRefresh}>
              <RefreshCw />
            </IconButton>
          </div>
        </header>

        {(shareError || errorMessage) && (
          <div className="command-alert" role="alert">
            <AlertCircle />
            <span>{shareError || errorMessage}</span>
          </div>
        )}

        {showFilters && (
          <section className="command-filter-bar" aria-label="Filtros do dashboard">
            <label className="command-field">
              <span className="command-label">Origem do lead</span>
              <select
                className="command-select"
                onChange={(event) => onSourceChange(event.target.value)}
                value={mediaSource}
              >
                {SOURCE_OPTIONS.map((option) => (
                  <option key={option.value || 'all'} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </section>
        )}

        <section className="command-performance">
          <div className="command-performance-main">
            <div className="command-performance-meta">
              <span className="command-badge">{periodLabel}</span>
              <span className="command-badge">{formatNumber(stats.totalVendas)} vendas</span>
            </div>
            <p className="command-revenue">{formatCurrency(stats.valorFaturado)}</p>
            <p className="command-revenue-subtitle">
              Faturamento no período filtrado, com conversão de {conversionRate.toFixed(1)}% sobre os leads captados.
            </p>

            <div className="command-performance-stats">
              <div className="command-mini-stat">
                <span>Conversão</span>
                <strong>{conversionRate.toFixed(1)}%</strong>
              </div>
              <div className="command-mini-stat">
                <span>Tempo até venda</span>
                <strong>{averageTimeToSale}</strong>
              </div>
              <div className="command-mini-stat">
                <span>Ticket médio</span>
                <strong>{formatCurrency(stats.ticketMedio || 0)}</strong>
              </div>
            </div>
          </div>

          <aside className="command-funnel-snapshot">
            <div className="command-snapshot-header">
              <div>
                <h2>Funil em tempo real</h2>
                <p>{formatNumber(stats.totalLeads)} leads captados, {formatNumber(totalCurrentStageLeads)} em etapa atual.</p>
              </div>
              <div className="command-snapshot-icon">
                <PieChart />
              </div>
            </div>
            {stageRows.length === 0 ? (
              <div className="command-empty">Pipeline ainda não retornou etapas para este período.</div>
            ) : (
              <div className="command-source-list">
                {topStages.map((stage) => (
                  <div
                    className="command-source-item"
                    key={stage.id}
                    style={{ '--row-color': stage.color } as React.CSSProperties}
                  >
                    <div className="command-source-line">
                      <div className="command-source-name">
                        <span className="command-row-dot" />
                        <span>{stage.name}</span>
                      </div>
                      <span className="command-source-count">{formatNumber(stage.count)}</span>
                    </div>
                    <div className="command-progress">
                      <div
                        className="command-progress-fill"
                        style={{ width: `${clampPercent(stage.percentage)}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </aside>
        </section>

        <section className="command-kpi-grid" aria-label="Indicadores principais">
          <KpiCard
            color="#2563eb"
            description="Entrada do funil"
            icon={<Users />}
            title="Leads"
            value={formatCompactNumber(stats.totalLeads)}
          />
          {stageRows.map((stage) => (
            <KpiCard
              color={stage.color}
              description={`sobre ${stage.percentageBaseLabel}`}
              icon={<Target />}
              key={stage.id}
              percentage={stage.percentage}
              title={stage.name}
              value={formatCompactNumber(stage.count)}
            />
          ))}
          <KpiCard
            color="#0f766e"
            description={`${formatNumber(stats.totalVendas)} vendas`}
            icon={<DollarSign />}
            title="Faturamento"
            value={formatCurrency(stats.valorFaturado)}
          />
        </section>

        <section className="command-main-grid">
          <div className="command-stack">
            <TimeSeriesPanel dailyFunnelData={dailyFunnelData} isDark={isDark} stages={stages} />
            <Panel
              description="Leitura compacta de volume atual e conversão por etapa."
              icon={<BarChart3 />}
              title="Resumo do funil"
            >
              <FunnelTable stageRows={stageRows} stats={stats} />
            </Panel>
          </div>

          <aside className="command-stack">
            <SourcesPanel sources={funnelBySource} />
            <ForecastPanel projectionsData={projectionsData} revenueProjectionPercent={revenueProjectionPercent} />
            <TimelinePanel events={timelineEvents} />
          </aside>
        </section>
      </div>
    </main>
  );
};

export default CommandDashboard;
