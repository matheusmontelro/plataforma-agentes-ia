import React from 'react';

interface TooltipPayloadItem {
  color?: string;
  dataKey?: number | string;
  name?: string;
  value?: number | string;
}

interface MonoTooltipProps {
  active?: boolean;
  label?: string;
  payload?: TooltipPayloadItem[];
}

const formatValue = (value?: number | string) => {
  if (typeof value === 'number') return new Intl.NumberFormat('pt-BR').format(value);
  return value ?? '';
};

/** Tooltip HTML (recharts renderiza HTML, então var(--mono-*) funciona). Borda esquerda da série ativa. */
export const MonoTooltip: React.FC<MonoTooltipProps> = ({ active, label, payload }) => {
  if (!active || !payload || payload.length === 0) return null;
  const activeColor = payload[0]?.color || 'var(--mono-ink)';

  return (
    <div
      style={{
        maxWidth: 220,
        minWidth: 150,
        background: 'var(--mono-surface)',
        border: '1px solid var(--mono-hairline)',
        borderLeft: `2px solid ${activeColor}`,
        borderRadius: 'var(--mono-r-md)',
        boxShadow: 'var(--mono-shadow-pop)',
        padding: '8px 10px',
        color: 'var(--mono-ink)',
        fontSize: 12,
      }}
    >
      <div
        style={{
          marginBottom: 4,
          color: 'var(--mono-ink-muted)',
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
        }}
      >
        {label}
      </div>
      {payload.map((item, index) => (
        <div key={index} style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 2 }}>
          <span style={{ width: 8, height: 8, borderRadius: 999, background: item.color }} />
          <span style={{ color: 'var(--mono-ink-soft)' }}>{item.name}</span>
          <span className="mono-num" style={{ fontWeight: 600, marginLeft: 'auto' }}>
            {formatValue(item.value)}
          </span>
        </div>
      ))}
    </div>
  );
};
