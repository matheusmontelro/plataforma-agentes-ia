import React from 'react';
import type { ProjectionsResponse } from '../../../../services/api';
import { MonoEmpty } from '../States/MonoStates';
import { clampPercent, formatCurrency, formatNumber } from '../utils/format';

const PALETTE = ['rgba(2,3,35,0.55)', '#0f766e', 'rgba(2,3,35,0.30)', 'rgba(2,3,35,0.18)', 'rgba(2,3,35,0.12)', '#6b7280'];

interface MonoForecastProps {
  projectionsData: ProjectionsResponse | null;
  revenueProjectionPercent: number;
}

export const MonoForecast: React.FC<MonoForecastProps> = ({ projectionsData, revenueProjectionPercent }) => {
  if (!projectionsData) {
    return <MonoEmpty>Sem projeção disponível para este período.</MonoEmpty>;
  }

  const rows = Object.entries(projectionsData.stages || {}).map(([name, data], index) => ({
    color: PALETTE[index % PALETTE.length],
    name,
    percentage: data.projection > 0 ? clampPercent((data.soFar / data.projection) * 100) : 0,
    projection: data.projection,
    soFar: data.soFar,
  }));

  const fatPct = clampPercent(revenueProjectionPercent);

  const Row: React.FC<{ color: string; name: string; pct: number; soFar: string; projection: string; ahead?: boolean }> = ({
    color,
    name,
    pct,
    soFar,
    projection,
    ahead,
  }) => (
    <div className="mono-forecast-row" style={{ ['--row-color' as string]: color }}>
      <div className="mono-forecast-line">
        <span className="mono-forecast-name">{name}</span>
        <span className="mono-forecast-values mono-num">
          {soFar} / {projection}
          {ahead && <span className="mono-chip" style={{ marginLeft: 8 }}>Acima da meta</span>}
        </span>
      </div>
      <div className="mono-dual-track">
        <div className="mono-dual-projection" style={{ width: '100%' }} />
        <div className="mono-dual-sofar" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );

  return (
    <div className="mono-forecast-list">
      {rows.map((row) => (
        <Row
          ahead={row.projection > 0 && row.soFar > row.projection}
          color={row.color}
          key={row.name}
          name={row.name}
          pct={row.percentage}
          projection={formatNumber(row.projection)}
          soFar={formatNumber(row.soFar)}
        />
      ))}
      <Row
        ahead={revenueProjectionPercent >= 100}
        color="#0f766e"
        name="Faturamento"
        pct={fatPct}
        projection={formatCurrency(projectionsData.faturadoProjection)}
        soFar={formatCurrency(projectionsData.faturadoSoFar)}
      />
    </div>
  );
};
