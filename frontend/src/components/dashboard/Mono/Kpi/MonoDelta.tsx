import React from 'react';
import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react';

interface MonoDeltaProps {
  direction: 'up' | 'down' | 'flat';
  label?: string;
  tone?: 'signal' | 'danger' | 'ink';
  value?: number;
}

const toneClass = {
  signal: 'mono-delta--up',
  danger: 'mono-delta--down',
  ink: '',
} as const;

const icon = {
  up: ArrowUpRight,
  down: ArrowDownRight,
  flat: Minus,
} as const;

export const MonoDelta: React.FC<MonoDeltaProps> = ({ direction, label, tone = 'ink', value }) => {
  const Icon = icon[direction];
  return (
    <span className={`mono-delta ${toneClass[tone]}`}>
      <Icon />
      {value !== undefined && <span className="mono-num">{value.toFixed(1)}%</span>}
      {label && <span>{label}</span>}
    </span>
  );
};
