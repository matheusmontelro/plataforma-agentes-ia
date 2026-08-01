import React from 'react';

interface MonoSparkProps {
  color?: string;
  data: number[];
  height?: number;
}

/** Mini sparkline SVG. Retorna null se não houver série suficiente (estado válido). */
export const MonoSpark: React.FC<MonoSparkProps> = ({ color = 'var(--mono-ink)', data, height = 24 }) => {
  if (!data || data.length < 2) return null;

  const max = Math.max(...data, 0);
  const min = Math.min(...data, 0);
  const range = max - min || 1;
  const width = 100;

  const points = data
    .map((value, index) => {
      const x = (index / (data.length - 1)) * width;
      const y = height - ((value - min) / range) * (height - 4) - 2;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(' ');

  return (
    <svg
      className="mono-kpi-spark"
      preserveAspectRatio="none"
      role="img"
      style={{ color }}
      viewBox={`0 0 ${width} ${height}`}
    >
      <polyline
        fill="none"
        points={points}
        stroke="currentColor"
        strokeWidth={1.5}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
};
