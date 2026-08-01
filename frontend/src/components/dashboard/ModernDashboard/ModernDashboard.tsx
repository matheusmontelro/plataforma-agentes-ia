import React, { useId, useMemo, useRef, useState, useEffect } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  CalendarRange,
  ChevronDown,
  RefreshCw,
  Share2,
} from 'lucide-react';
import type { TimelineEvent } from '../../../services/api';
import type { MonoDashboardProps } from '../Mono/types';
import BrowserDateTime from '../../BrowserDateTime';
import {
  clampPercent,
  formatCompactNumber,
  formatCurrency,
  formatNumber,
  formatPercent,
} from '../Mono/utils/format';
import { resolveContactProfilePhoto } from '../../../utils/contactAvatar';
import './ModernDashboard.css';

type ModernDashboardProps = MonoDashboardProps;
type ChartMetric = 'leads' | 'sales' | 'conversion';

const SOURCE_OPTIONS = [
  { label: 'Todas as origens', value: '' },
  { label: 'Instagram', value: 'instagram' },
  { label: 'Facebook', value: 'facebook' },
  { label: 'Google', value: 'google' },
  { label: 'TikTok', value: 'tiktok' },
  { label: 'Indicação', value: 'indicacao' },
];

const chartMetricLabel: Record<ChartMetric, string> = {
  leads: 'Leads',
  sales: 'Vendas',
  conversion: 'Conversão',
};

const eventLabel = (type: string) => {
  const normalized = (type || '').toLowerCase();
  if (normalized.includes('lead')) return 'Novo lead cadastrado';
  if (normalized.includes('agendamento')) return 'Agendamento criado';
  if (normalized.includes('comparecimento')) return 'Comparecimento registrado';
  if (normalized.includes('no_show')) return 'Ausência registrada';
  if (normalized.includes('venda')) return 'Venda realizada';
  return type || 'Atividade registrada';
};

const eventAvatarLabel = (event: TimelineEvent) => {
  if (event.avatar_gender === 'female') return 'Contato com gênero feminino registrado';
  if (event.avatar_gender === 'male') return 'Contato com gênero masculino registrado';
  return 'Contato sem foto';
};

const EventAvatar: React.FC<{ event: TimelineEvent }> = ({ event }) => {
  const [failed, setFailed] = useState(false);
  const avatarUrl = resolveContactProfilePhoto({ photo: event.avatar_url });
  const canShowPhoto = Boolean(avatarUrl && !failed);
  const fallback = event.avatar_gender === 'female' ? '👩' : event.avatar_gender === 'male' ? '👨' : '👤';

  return (
    <span className="modern-activity-avatar">
      {canShowPhoto ? (
        <img
          alt={`Foto de ${event.descricao || 'contato'}`}
          onError={() => setFailed(true)}
          src={avatarUrl}
        />
      ) : (
        <span aria-label={eventAvatarLabel(event)} role="img">{fallback}</span>
      )}
    </span>
  );
};

interface DateRangeControlProps {
  endDate: string;
  onDateChange: (startDate: string, endDate: string) => void;
  startDate: string;
}

const formatShortDate = (value: string) => {
  const [year, month, day] = value.split('-');
  return year && month && day ? `${day}/${month}` : value;
};

const DateRangeControl: React.FC<DateRangeControlProps> = ({ endDate, onDateChange, startDate }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  return (
    <div className="modern-date" ref={ref}>
      <button
        aria-expanded={open}
        aria-haspopup="dialog"
        className="modern-control modern-date-trigger"
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <CalendarRange />
        <span>{formatShortDate(startDate)} — {formatShortDate(endDate)}</span>
        <ChevronDown />
      </button>

      {open && (
        <div aria-label="Selecionar período" className="modern-date-popover" role="dialog">
          <label>
            <span>Início</span>
            <input onChange={(event) => onDateChange(event.target.value, endDate)} type="date" value={startDate} />
          </label>
          <label>
            <span>Fim</span>
            <input onChange={(event) => onDateChange(startDate, event.target.value)} type="date" value={endDate} />
          </label>
        </div>
      )}
    </div>
  );
};

const MiniSparkline: React.FC<{ data: number[] }> = ({ data }) => {
  const gradientId = `modern-spark-${useId().replace(/:/g, '')}`;
  const values = data.map((value, index) => ({ index, value }));
  if (values.length < 2) return <span className="modern-kpi-signal" aria-hidden="true" />;

  return (
    <div aria-hidden="true" className="modern-sparkline">
      <ResponsiveContainer height="100%" width="100%">
        <AreaChart data={values} margin={{ bottom: 1, left: 1, right: 1, top: 1 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="var(--modern-signal)" stopOpacity={0.22} />
              <stop offset="100%" stopColor="var(--modern-signal)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area
            dataKey="value"
            dot={false}
            fill={`url(#${gradientId})`}
            isAnimationActive={false}
            stroke="var(--modern-signal)"
            strokeWidth={1.8}
            type="monotone"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
};

interface KpiCardProps {
  data?: number[];
  detail: string;
  label: string;
  value: string;
}

const KpiCard: React.FC<KpiCardProps> = ({ data = [], detail, label, value }) => (
  <article className={`modern-kpi-card ${data.length < 2 ? 'modern-kpi-card--static' : ''}`}>
    <div className="modern-kpi-copy">
      <span className="modern-kpi-label">{label}</span>
      <strong className="modern-kpi-value modern-num">{value}</strong>
      <span className="modern-kpi-detail">{detail}</span>
    </div>
    <MiniSparkline data={data} />
  </article>
);

interface PerformanceChartProps {
  dailyFunnelData: ModernDashboardProps['dailyFunnelData'];
  isDark: boolean;
  leadsStageName?: string;
  metric: ChartMetric;
  salesStageName?: string;
}

const getDailyLeads = (
  item: ModernDashboardProps['dailyFunnelData'][number],
  leadsStageName?: string,
) => {
  if (typeof item.leads === 'number') return item.leads;

  const normalizedStageName = leadsStageName?.trim().toLocaleLowerCase('pt-BR');
  const stageKey = Object.keys(item).find((key) => (
    key !== 'date' && key.trim().toLocaleLowerCase('pt-BR') === normalizedStageName
  ));
  const stageValue = stageKey ? item[stageKey] : undefined;
  if (typeof stageValue === 'number') return stageValue;

  const firstNumericValue = Object.entries(item).find(([key, value]) => (
    key !== 'date' && typeof value === 'number'
  ));
  return typeof firstNumericValue?.[1] === 'number' ? firstNumericValue[1] : 0;
};

const parseLocalDate = (value: string) => {
  const [year, month, day] = value.split('-').map(Number);
  if (!year || !month || !day) return null;
  const date = new Date(year, month - 1, day);
  return Number.isNaN(date.getTime()) ? null : date;
};

const formatLocalDate = (date: Date) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

const completeDailySeries = (
  dailyFunnelData: ModernDashboardProps['dailyFunnelData'],
  startDateValue: string,
  endDateValue: string,
  stageNames: string[],
  leadsStageName?: string,
) => {
  if (dailyFunnelData.length === 0) return dailyFunnelData;

  const startDate = parseLocalDate(startDateValue);
  const selectedEndDate = parseLocalDate(endDateValue);
  if (!startDate || !selectedEndDate) return dailyFunnelData;

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const endDate = selectedEndDate > today ? today : selectedEndDate;
  if (endDate < startDate) return dailyFunnelData;

  const dataByDate = new Map(dailyFunnelData.map((item) => [item.date, item]));
  const emptyStages = Object.fromEntries(stageNames.map((name) => [name, 0]));
  const completed: ModernDashboardProps['dailyFunnelData'] = [];

  for (const cursor = new Date(startDate); cursor <= endDate; cursor.setDate(cursor.getDate() + 1)) {
    const date = formatLocalDate(cursor);
    const current = dataByDate.get(date);
    completed.push(current
      ? { ...current, leads: getDailyLeads(current, leadsStageName) }
      : { ...emptyStages, date, leads: 0 });
  }

  return completed;
};

const PerformanceChart: React.FC<PerformanceChartProps> = ({
  dailyFunnelData,
  isDark,
  leadsStageName,
  metric,
  salesStageName,
}) => {
  const chartData = useMemo(() => dailyFunnelData.map((item) => {
    const [year, month, day] = item.date.split('-');
    const leads = getDailyLeads(item, leadsStageName);
    const salesValue = salesStageName && typeof item[salesStageName] === 'number' ? item[salesStageName] as number : 0;
    const value = metric === 'leads'
      ? leads
      : metric === 'sales'
        ? salesValue
        : leads > 0 ? (salesValue / leads) * 100 : 0;

    return {
      date: `${day}/${month}`,
      fullDate: `${day}/${month}/${year}`,
      value,
    };
  }), [dailyFunnelData, leadsStageName, metric, salesStageName]);

  const gradientId = `modern-chart-${useId().replace(/:/g, '')}`;
  const palette = isDark
    ? { axis: 'rgba(247,247,247,.56)', grid: 'rgba(255,255,255,.08)', signal: '#2dd4bf', tooltip: '#08091f', border: 'rgba(255,255,255,.14)' }
    : { axis: 'rgba(2,3,35,.56)', grid: 'rgba(2,3,35,.07)', signal: '#0f766e', tooltip: '#ffffff', border: 'rgba(2,3,35,.12)' };

  if (chartData.length === 0) {
    return <div className="modern-empty">Nenhuma movimentação no período selecionado.</div>;
  }

  return (
    <div className="modern-chart" role="img" aria-label={`Evolução diária de ${chartMetricLabel[metric]}`}>
      <ResponsiveContainer height="100%" width="100%">
        <AreaChart data={chartData} margin={{ bottom: 0, left: 0, right: 8, top: 14 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor={palette.signal} stopOpacity={0.26} />
              <stop offset="72%" stopColor={palette.signal} stopOpacity={0.07} />
              <stop offset="100%" stopColor={palette.signal} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={palette.grid} strokeDasharray="3 3" vertical={false} />
          <XAxis axisLine={false} dataKey="date" tick={{ fill: palette.axis, fontSize: 11 }} tickLine={false} />
          <YAxis
            axisLine={false}
            tick={{ fill: palette.axis, fontSize: 11 }}
            tickFormatter={(value) => metric === 'conversion' ? `${value.toFixed(0)}%` : formatCompactNumber(value)}
            tickLine={false}
            width={42}
          />
          <Tooltip
            contentStyle={{
              background: palette.tooltip,
              border: `1px solid ${palette.border}`,
              borderRadius: 8,
              boxShadow: '0 8px 24px rgba(2,3,35,.10)',
              color: isDark ? '#f7f7f7' : '#020323',
              fontSize: 12,
            }}
            formatter={(value: number) => [metric === 'conversion' ? formatPercent(value) : formatNumber(value), chartMetricLabel[metric]]}
            labelFormatter={(_, payload) => payload?.[0]?.payload?.fullDate || ''}
            cursor={{ stroke: palette.grid, strokeWidth: 1 }}
          />
          <Area
            dataKey="value"
            dot={chartData.length === 1 ? { fill: palette.signal, r: 4, strokeWidth: 0 } : false}
            fill={`url(#${gradientId})`}
            isAnimationActive={false}
            name={chartMetricLabel[metric]}
            stroke={palette.signal}
            strokeWidth={2.25}
            type="monotone"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
};

const ModernDashboard: React.FC<ModernDashboardProps> = ({
  averageTimeToSale,
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
  projectionsData,
  revenueProjectionPercent,
  shareError,
  sourceOptions,
  stageRows,
  stages,
  stats,
  timelineEvents,
}) => {
  const [chartMetric, setChartMetric] = useState<ChartMetric>('leads');
  const leadsStage = stages[0];
  const salesStage = stages.find((stage) => stage.is_converted_stage)
    || stages.find((stage) => /(venda|ganho|convert)/i.test(stage.name));
  const completeFunnelData = useMemo(() => completeDailySeries(
    dailyFunnelData,
    dateRange.startDate,
    dateRange.endDate,
    stages.map((stage) => stage.name),
    leadsStage?.name,
  ), [dailyFunnelData, dateRange.endDate, dateRange.startDate, leadsStage?.name, stages]);
  const leadsTrend = completeFunnelData.map((item) => getDailyLeads(item, leadsStage?.name));
  const salesTrend = completeFunnelData.map((item) => salesStage ? Number(item[salesStage.name]) || 0 : 0);
  const conversionTrend = completeFunnelData.map((item, index) => leadsTrend[index] > 0 ? (salesTrend[index] / leadsTrend[index]) * 100 : 0);
  const totalSources = funnelBySource.reduce((sum, item) => sum + item.totalLeads, 0);
  const resolvedSourceOptions = sourceOptions || SOURCE_OPTIONS;
  const projectionRows = projectionsData
    ? [
        ...Object.entries(projectionsData.stages || {}).slice(0, 4).map(([name, value]) => ({
          name,
          projection: value.projection,
          realized: value.soFar,
          type: 'number' as const,
        })),
        {
          name: 'Faturamento',
          projection: projectionsData.faturadoProjection,
          realized: projectionsData.faturadoSoFar,
          type: 'currency' as const,
        },
      ]
    : [];

  return (
    <main className={`modern-dashboard ${isDark ? 'modern-dashboard--dark' : ''}`}>
      <div className="modern-shell">
        {(shareError || errorMessage) && (
          <div className="modern-alert" role="alert">{shareError || errorMessage}</div>
        )}

        <section aria-label="Indicadores principais" className="modern-kpi-grid">
          <KpiCard
            detail={`${Math.round(revenueProjectionPercent)}% da projeção mensal`}
            label="Faturamento"
            value={formatCurrency(stats.valorFaturado)}
          />
          <KpiCard data={conversionTrend} detail="Leads → vendas" label="Conversão" value={formatPercent(conversionRate)} />
          <KpiCard data={leadsTrend} detail="No período selecionado" label="Leads" value={formatNumber(stats.totalLeads)} />
          <KpiCard data={salesTrend} detail="Convertidas no período" label="Vendas" value={formatNumber(stats.totalVendas)} />
        </section>

        <section className="modern-primary-grid">
          <article className="modern-panel modern-performance-panel">
            <div className="modern-panel-head modern-performance-head">
              <div>
                <h2>Performance</h2>
                <div aria-label="Métrica do gráfico" className="modern-tabs" role="tablist">
                  {(Object.keys(chartMetricLabel) as ChartMetric[]).map((metric) => (
                    <button
                      aria-selected={chartMetric === metric}
                      className={chartMetric === metric ? 'is-active' : ''}
                      key={metric}
                      onClick={() => setChartMetric(metric)}
                      role="tab"
                      type="button"
                    >
                      {chartMetricLabel[metric]}
                    </button>
                  ))}
                </div>
              </div>

              <div className="modern-panel-controls">
                <DateRangeControl
                  endDate={dateRange.endDate}
                  onDateChange={onDateChange}
                  startDate={dateRange.startDate}
                />
                <select
                  aria-label="Filtrar por origem"
                  className="modern-control modern-select"
                  onChange={(event) => onSourceChange(event.target.value)}
                  value={mediaSource}
                >
                  {resolvedSourceOptions.map((option) => <option key={option.value || 'all'} value={option.value}>{option.label}</option>)}
                </select>
                <button aria-label="Atualizar métricas" className="modern-control modern-icon-control" onClick={onRefresh} title="Atualizar métricas" type="button">
                  <RefreshCw />
                </button>
                <button aria-label="Compartilhar relatório" className="modern-control modern-icon-control" onClick={onShare} title="Compartilhar relatório" type="button">
                  <Share2 />
                </button>
              </div>
            </div>
            <div className="modern-panel-body modern-chart-body">
              <PerformanceChart
                dailyFunnelData={completeFunnelData}
                isDark={isDark}
                leadsStageName={leadsStage?.name}
                metric={chartMetric}
                salesStageName={salesStage?.name}
              />
            </div>
          </article>

          <article className="modern-panel">
            <div className="modern-panel-head">
              <div>
                <h2>Funil de conversão</h2>
                <p>Volume atual e avanço por etapa.</p>
              </div>
            </div>
            <div className="modern-panel-body modern-funnel">
              <div className="modern-funnel-row">
                <div className="modern-funnel-meta"><span>Leads</span><strong>{formatNumber(stats.totalLeads)} · 100%</strong></div>
                <div className="modern-progress"><span style={{ width: '100%' }} /></div>
              </div>
              {stageRows.slice(0, 6).map((stage) => (
                <div className="modern-funnel-row" key={stage.id}>
                  <div className="modern-funnel-meta">
                    <span>{stage.name}</span>
                    <strong>{formatNumber(stage.count)} · {formatPercent(stage.percentage)}</strong>
                  </div>
                  <div className="modern-progress"><span style={{ width: `${clampPercent(stage.percentage)}%` }} /></div>
                </div>
              ))}
              {stageRows.length === 0 && <div className="modern-empty">Pipeline sem etapas no período.</div>}
            </div>
          </article>
        </section>

        <section className="modern-secondary-grid">
          <article className="modern-panel">
            <div className="modern-panel-head"><div><h2>Origem dos leads</h2><p>Distribuição da captação.</p></div></div>
            <div className="modern-table-wrap">
              <table className="modern-table">
                <thead><tr><th>Origem</th><th>Leads</th><th>%</th></tr></thead>
                <tbody>
                  {funnelBySource.slice(0, 6).map((source) => {
                    const percentage = totalSources > 0 ? (source.totalLeads / totalSources) * 100 : 0;
                    return <tr key={source.fonte}><td>{source.fonte || 'Não informada'}</td><td className="modern-num">{formatNumber(source.totalLeads)}</td><td className="modern-num">{formatPercent(percentage, 0)}</td></tr>;
                  })}
                  {funnelBySource.length === 0 && <tr><td colSpan={3}>Sem origens registradas.</td></tr>}
                </tbody>
              </table>
            </div>
          </article>

          <article className="modern-panel">
            <div className="modern-panel-head"><div><h2>Projeção mensal</h2><p>Realizado comparado ao ritmo projetado.</p></div></div>
            <div className="modern-table-wrap">
              <table className="modern-table modern-projection-table">
                <thead><tr><th>Métrica</th><th>Realizado</th><th>Projeção</th><th>%</th></tr></thead>
                <tbody>
                  {projectionRows.map((row) => {
                    const percentage = row.projection > 0 ? (row.realized / row.projection) * 100 : 0;
                    const renderValue = (value: number) => row.type === 'currency' ? formatCurrency(value) : formatNumber(value);
                    return <tr key={row.name}><td>{row.name}</td><td className="modern-num">{renderValue(row.realized)}</td><td className="modern-num">{renderValue(row.projection)}</td><td className={`modern-num ${percentage >= 100 ? 'modern-positive' : ''}`}>{formatPercent(percentage, 0)}</td></tr>;
                  })}
                  {projectionRows.length === 0 && <tr><td colSpan={4}>Sem projeção disponível.</td></tr>}
                </tbody>
              </table>
            </div>
          </article>

          <article className="modern-panel">
            <div className="modern-panel-head"><div><h2>Atividades recentes</h2><p>Últimos sinais da operação.</p></div></div>
            <div className="modern-activity-list">
              {timelineEvents.slice(0, 6).map((event, index) => (
                <article className="modern-activity-row" key={`${event.event_type}-${event.entity_id}-${index}`}>
                  <EventAvatar event={event} />
                  <div className="modern-activity-copy">
                    <strong>{eventLabel(event.event_type)}</strong>
                    <span>{event.descricao || 'Sem descrição'}</span>
                  </div>
                  <BrowserDateTime className="modern-num" value={event.event_date} variant="dateTime" />
                </article>
              ))}
              {timelineEvents.length === 0 && <div className="modern-empty">Sem atividades recentes.</div>}
            </div>
          </article>
        </section>

        <article className="modern-panel modern-pipeline-panel">
          <div className="modern-panel-head">
            <div><h2>Etapas do pipeline</h2><p>Conversão calculada sobre a base configurada em cada etapa.</p></div>
            <span className="modern-average">Tempo até venda: <strong>{averageTimeToSale}</strong></span>
          </div>
          <div className="modern-table-wrap">
            <table className="modern-table modern-pipeline-table">
              <thead><tr><th>Etapa</th><th>Em etapa</th><th>Alcançaram</th><th>Conversão</th><th>Base</th></tr></thead>
              <tbody>
                <tr><td>Leads</td><td className="modern-num">{formatNumber(stats.totalLeads)}</td><td className="modern-num">{formatNumber(stats.totalLeads)}</td><td className="modern-num">100%</td><td>Entrada do funil</td></tr>
                {stageRows.map((stage) => (
                  <tr key={stage.id}><td>{stage.name}</td><td className="modern-num">{formatNumber(stage.count)}</td><td className="modern-num">{formatNumber(stage.reachedCount)}</td><td className="modern-num">{formatPercent(stage.percentage)}</td><td>{stage.percentageBaseLabel}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      </div>
    </main>
  );
};

export const ModernDashboardLoading: React.FC<{ isDark: boolean }> = ({ isDark }) => (
  <main className={`modern-dashboard ${isDark ? 'modern-dashboard--dark' : ''}`}>
    <div className="modern-shell" aria-label="Carregando métricas">
      <div className="modern-kpi-grid">
        {[0, 1, 2, 3].map((item) => <div className="modern-skeleton modern-skeleton-kpi" key={item} />)}
      </div>
      <div className="modern-primary-grid">
        <div className="modern-skeleton modern-skeleton-chart" />
        <div className="modern-skeleton modern-skeleton-chart" />
      </div>
      <div className="modern-secondary-grid">
        {[0, 1, 2].map((item) => <div className="modern-skeleton modern-skeleton-panel" key={item} />)}
      </div>
    </div>
  </main>
);

export const ModernDashboardError: React.FC<{ error: string; isDark: boolean; onRefresh: () => void }> = ({ error, isDark, onRefresh }) => (
  <main className={`modern-dashboard ${isDark ? 'modern-dashboard--dark' : ''}`}>
    <div className="modern-error">
      <strong>Não foi possível carregar o dashboard</strong>
      <p>{error}</p>
      <button className="modern-control" onClick={onRefresh} type="button"><RefreshCw /> Tentar novamente</button>
    </div>
  </main>
);

export default ModernDashboard;
