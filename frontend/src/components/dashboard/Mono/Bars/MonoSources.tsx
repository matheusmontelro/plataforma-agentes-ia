import React from 'react';
import type { FunnelBySourceItem } from '../../../../services/api';
import { MonoEmpty } from '../States/MonoStates';
import { formatNumber } from '../utils/format';

const PALETTE = ['#020323', 'rgba(2,3,35,0.55)', '#0f766e', 'rgba(2,3,35,0.30)', 'rgba(2,3,35,0.18)', '#6b7280'];

interface MonoSourcesProps {
  sources: FunnelBySourceItem[];
}

export const MonoSources: React.FC<MonoSourcesProps> = ({ sources }) => {
  if (sources.length === 0) {
    return <MonoEmpty>Sem origem de lead registrada neste período.</MonoEmpty>;
  }

  const total = sources.reduce((sum, item) => sum + item.totalLeads, 0);

  return (
    <div className="mono-bar-list">
        {sources.map((source, index) => {
          const percentage = total ? (source.totalLeads / total) * 100 : 0;
          const color = PALETTE[index % PALETTE.length];
          return (
            <div key={`${source.fonte || 'N/A'}-${index}`} style={{ ['--row-color' as string]: color }}>
              <div className="mono-source-line">
                <div className="mono-source-name">
                  <span className="mono-row-dot" />
                  <span>{source.fonte || 'N/A'}</span>
                </div>
                <span className="mono-source-count mono-num">
                  {formatNumber(source.totalLeads)} · {percentage.toFixed(0)}%
                </span>
              </div>
              <div className="mono-bar-track">
                <div className="mono-bar-fill" style={{ width: `${Math.max(percentage, 0)}%` }} />
              </div>
            </div>
          );
        })}
      </div>
  );
};
