import React from 'react';
import { formatPercent } from '../utils/format';

interface MonoKpiProps {
  description?: string;
  icon?: React.ReactNode;
  percentage?: number;
  title: string;
  value: string;
}

export const MonoKpi: React.FC<MonoKpiProps> = ({ description, icon, percentage, title, value }) => (
  <article className="mono-kpi">
    <div className="mono-kpi-top">
      <div>
        <span className="mono-kpi-label">{title}</span>
        <div className="mono-kpi-value mono-num">{value}</div>
      </div>
      {icon && <span style={{ color: 'var(--mono-ink-faint)', display: 'inline-flex' }}>{icon}</span>}
    </div>
    {(percentage !== undefined || description) && (
      <div className="mono-kpi-footer">
        {percentage !== undefined && (
          <span className="mono-chip mono-chip--ink mono-num">{formatPercent(percentage)}</span>
        )}
        {description && <span>{description}</span>}
      </div>
    )}
  </article>
);
