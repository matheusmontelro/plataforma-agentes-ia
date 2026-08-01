import React from 'react';
import type { FunnelMetricsResponse } from '../../../../services/api';
import type { DashboardStageRow } from '../types';
import { clampPercent, formatNumber } from '../utils/format';

interface MonoTableProps {
  stageRows: DashboardStageRow[];
  stats: FunnelMetricsResponse;
}

export const MonoTable: React.FC<MonoTableProps> = ({ stageRows, stats }) => (
  <div className="mono-table">
    <div className="mono-table-head">
      <span>Etapa</span>
      <span className="mono-row-value">Total</span>
      <span className="mono-row-muted">Conv.</span>
    </div>

    <div className="mono-table-row" style={{ ['--row-color' as string]: 'var(--mono-ink)' }}>
      <div>
        <div className="mono-row-title">
          <span className="mono-row-dot" />
          <span className="mono-row-name">Leads</span>
        </div>
        <div className="mono-bar-track">
          <div className="mono-bar-fill" style={{ width: '100%' }} />
        </div>
        <div className="mono-row-note">Entrada do funil</div>
      </div>
      <span className="mono-row-value mono-num">{formatNumber(stats.totalLeads)}</span>
      <span className="mono-row-muted mono-num">100%</span>
    </div>

    {stageRows.map((stage) => (
      <div className="mono-table-row" key={stage.id} style={{ ['--row-color' as string]: stage.color }}>
        <div>
          <div className="mono-row-title">
            <span className="mono-row-dot" />
            <span className="mono-row-name">{stage.name}</span>
          </div>
          <div className="mono-bar-track">
            <div
              className="mono-bar-fill"
              style={{ width: `${clampPercent(stage.percentage)}%` }}
            />
          </div>
          <div className="mono-row-note">Base: {stage.percentageBaseLabel}</div>
        </div>
        <span className="mono-row-value mono-num">{formatNumber(stage.count)}</span>
        <span className="mono-row-muted mono-num">{stage.percentage.toFixed(1)}%</span>
      </div>
    ))}
  </div>
);
