import React from 'react';
import { TrendingUp } from 'lucide-react';
import type { FunnelMetricsResponse } from '../../../../services/api';
import type { DashboardStageRow } from '../types';
import { clampPercent, formatCurrency, formatNumber, formatPercent } from '../utils/format';
import { MonoDelta } from '../Kpi/MonoDelta';
import { MonoSpark } from '../Kpi/MonoSpark';

interface HeroProps {
  averageTimeToSale: string;
  conversionRate: number;
  leadsTrend?: number[];
  revenueProjectionPercent: number;
  stageRows: DashboardStageRow[];
  stats: FunnelMetricsResponse;
  totalCurrentStageLeads: number;
}

const MonoStat: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="mono-stat">
    <span className="mono-stat-label">{label}</span>
    <span className="mono-stat-value mono-num">{value}</span>
  </div>
);

export const MonoRevenueHero: React.FC<HeroProps> = ({
  averageTimeToSale,
  conversionRate,
  leadsTrend,
  revenueProjectionPercent,
  stageRows,
  stats,
  totalCurrentStageLeads,
}) => {
  const ahead = revenueProjectionPercent >= 100;
  const topStages = stageRows.slice(0, 5);
  const maxCount = Math.max(...topStages.map((stage) => stage.count), 1);

  return (
    <section aria-label="Performance do período" className="mono-hero">
      <div className="mono-hero-main">
        <p className="mono-hero-kicker">Faturamento</p>
        <p className="mono-revenue mono-num">{formatCurrency(stats.valorFaturado)}</p>
        <p className="mono-revenue-sub">
          Receita realizada no período com conversão de {formatPercent(conversionRate)} sobre os leads
          captados.
        </p>

        <div style={{ marginTop: 12 }}>
          <MonoDelta
            direction={ahead ? 'up' : 'flat'}
            label={ahead ? 'acima do ritmo projetado' : 'ritmo do mês'}
            tone={ahead ? 'signal' : 'ink'}
            value={revenueProjectionPercent}
          />
        </div>

        <div className="mono-stat-strip">
          <MonoStat label="Tempo até venda" value={averageTimeToSale} />
          <MonoStat label="Ticket médio" value={formatCurrency(stats.ticketMedio || 0)} />
        </div>
      </div>

      <aside className="mono-hero-snapshot">
        <div className="mono-snapshot-head">
          <div>
            <h2>Funil em tempo real</h2>
            <p>
              {formatNumber(stats.totalLeads)} leads captados · {formatNumber(totalCurrentStageLeads)}{' '}
              em etapa atual
            </p>
          </div>
          <TrendingUp size={18} style={{ color: 'var(--mono-ink-faint)' }} />
        </div>

        {leadsTrend && leadsTrend.length > 1 && (
          <div style={{ marginBottom: 14 }}>
            <span className="mono-stat-label">Ritmo de leads</span>
            <MonoSpark data={leadsTrend} />
          </div>
        )}

        {topStages.length === 0 ? (
          <p className="mono-row-note">Pipeline sem etapas para este período.</p>
        ) : (
          <div className="mono-bar-list">
            {topStages.map((stage) => (
              <div key={stage.id} style={{ ['--row-color' as string]: stage.color }}>
                <div className="mono-source-line">
                  <div className="mono-source-name">
                    <span className="mono-row-dot" />
                    <span>{stage.name}</span>
                  </div>
                  <span className="mono-source-count mono-num">{formatNumber(stage.count)}</span>
                </div>
                <div className="mono-bar-track">
                  <div
                    className="mono-bar-fill"
                    style={{ width: `${clampPercent((stage.count / maxCount) * 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </aside>
    </section>
  );
};
