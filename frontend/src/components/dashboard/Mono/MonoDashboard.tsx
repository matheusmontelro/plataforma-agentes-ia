import React, { useMemo } from 'react';
import { Alert, Badge, ThemeProvider } from 'flowbite-react';
import {
  BarChart3,
  Clock,
  DollarSign,
  Filter,
  LineChart as LineChartIcon,
  RefreshCw,
  Share2,
  Table2,
  Target,
  TrendingUp,
  Users,
} from 'lucide-react';
import './MonoDashboard.css';
import type { MonoDashboardProps, SourceOption } from './types';
import { formatCompactNumber, formatCurrency, formatPercent } from './utils/format';
import { MonoButton, MonoDateRange, MonoIconButton, MonoSelect } from './Controls/MonoControls';
import { MonoPanel } from './Panel/MonoPanel';
import { MonoRevenueHero } from './Hero/MonoRevenueHero';
import { MonoKpi } from './Kpi/MonoKpi';
import { MonoTable } from './Table/MonoTable';
import { MonoSources } from './Bars/MonoSources';
import { MonoForecast } from './Bars/MonoForecast';
import { MonoChart } from './Chart/MonoChart';
import { MonoTimeline } from './Timeline/MonoTimeline';
import { monoFlowbiteClearTheme, monoFlowbiteProps, monoFlowbiteTheme } from './flowbiteTheme';

const DEFAULT_SOURCE_OPTIONS: SourceOption[] = [
  { label: 'Todas as origens', value: '' },
  { label: 'Instagram', value: 'instagram' },
  { label: 'Facebook', value: 'facebook' },
  { label: 'Google', value: 'google' },
  { label: 'TikTok', value: 'tiktok' },
  { label: 'Indicação', value: 'indicacao' },
];

const MonoDashboard: React.FC<MonoDashboardProps> = ({
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
  shareError,
  showFilters,
  sourceOptions,
  stageRows,
  stages,
  stats,
  timelineEvents,
  totalCurrentStageLeads,
}) => {
  const leadsTrend = useMemo(() => dailyFunnelData.map((item) => item.leads), [dailyFunnelData]);
  const sourceOptionsResolved = sourceOptions ?? DEFAULT_SOURCE_OPTIONS;

  return (
    <ThemeProvider
      clearTheme={monoFlowbiteClearTheme}
      props={monoFlowbiteProps}
      root
      theme={monoFlowbiteTheme}
    >
      <main className={`mono-dashboard ${isDark ? 'mono-dashboard--dark' : ''}`}>
      <a className="mono-skip-link" href="#mono-content">
        Pular para o conteúdo
      </a>

      <div className="mono-shell" id="mono-content">
        <header className="mono-toolbar">
          <div className="mono-title-row">
            <h1 className="mono-title">Visão geral</h1>
            <span className="mono-toolbar-sub">
              {companyName || 'Empresa'} · {periodLabel}
            </span>
          </div>

          <div className="mono-toolbar-actions">
            <MonoDateRange dateRange={dateRange} onDateChange={onDateChange} />
            <MonoIconButton label={showFilters ? 'Ocultar filtros' : 'Mostrar filtros'} onClick={onToggleFilters}>
              <Filter />
            </MonoIconButton>
            <MonoIconButton label="Atualizar métricas" onClick={onRefresh}>
              <RefreshCw />
            </MonoIconButton>
            <MonoButton variant="primary" onClick={onShare}>
              <Share2 />
              <span>Compartilhar</span>
            </MonoButton>
          </div>
        </header>

        {(shareError || errorMessage) && (
          <Alert color="failure" icon={Share2}>
            <span>{shareError || errorMessage}</span>
          </Alert>
        )}

        {showFilters && (
          <section aria-label="Filtros do dashboard" className="mono-filter-bar">
            <label className="mono-field">
              <span className="mono-label">Origem do lead</span>
              <MonoSelect
                onChange={(event) => onSourceChange(event.target.value)}
                value={mediaSource}
              >
                {sourceOptionsResolved.map((option) => (
                  <option key={option.value || 'all'} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </MonoSelect>
            </label>
          </section>
        )}

        <MonoRevenueHero
          averageTimeToSale={averageTimeToSale}
          conversionRate={conversionRate}
          leadsTrend={leadsTrend}
          revenueProjectionPercent={revenueProjectionPercent}
          stageRows={stageRows}
          stats={stats}
          totalCurrentStageLeads={totalCurrentStageLeads}
        />

        <section aria-label="Indicadores principais" className="mono-kpi-grid">
          <MonoKpi
            description="Entrada do funil"
            icon={<Users size={16} />}
            title="Leads"
            value={formatCompactNumber(stats.totalLeads)}
          />
          <MonoKpi
            description="Convertidos no período"
            icon={<Target size={16} />}
            title="Vendas"
            value={formatCompactNumber(stats.totalVendas)}
          />
          <MonoKpi
            description="Leads → vendas"
            icon={<TrendingUp size={16} />}
            percentage={conversionRate}
            title="Conversão"
            value={formatPercent(conversionRate)}
          />
          <MonoKpi
            description="Receita realizada"
            icon={<DollarSign size={16} />}
            title="Faturamento"
            value={formatCurrency(stats.valorFaturado)}
          />
        </section>

        <section className="mono-main-grid">
          <div className="mono-stack">
            <MonoPanel
              action={<Badge icon={LineChartIcon}>Linha diária</Badge>}
              description="Movimento de entrada e avanço no funil durante o período."
              icon={<BarChart3 size={16} />}
              title="Evolução diária"
            >
              <MonoChart dailyFunnelData={dailyFunnelData} isDark={isDark} stages={stages} />
            </MonoPanel>

            <MonoPanel
              description="Leitura compacta de volume atual e conversão por etapa."
              icon={<Table2 size={16} />}
              title="Resumo do funil"
            >
              {stageRows.length === 0 ? (
                <p className="mono-row-note">Pipeline sem etapas para este período.</p>
              ) : (
                <MonoTable stageRows={stageRows} stats={stats} />
              )}
            </MonoPanel>
          </div>

          <aside className="mono-stack">
            <MonoPanel
              description="Canais que trouxeram leads no período."
              icon={<Table2 size={16} />}
              title="Origem dos leads"
            >
              <MonoSources sources={funnelBySource} />
            </MonoPanel>

            <MonoPanel
              description="Ritmo atual comparado à projeção do mês."
              icon={<TrendingUp size={16} />}
              title="Projeções"
            >
              <MonoForecast
                projectionsData={projectionsData}
                revenueProjectionPercent={revenueProjectionPercent}
              />
            </MonoPanel>

            <MonoPanel
              description="Sinais recentes para investigação rápida."
              icon={<Clock size={16} />}
              title="Atividades recentes"
            >
              <MonoTimeline events={timelineEvents} />
            </MonoPanel>
          </aside>
        </section>
      </div>
      </main>
    </ThemeProvider>
  );
};

export default MonoDashboard;
