import React, { useMemo, useState } from 'react';
import {
  ChevronDown,
  SlidersHorizontal,
  X,
  Check
} from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  agentivePanelClass,
  agentivePillClass,
  agentiveSecondaryButtonClass,
} from './AgentiveUI.tsx';
import type { PipelineResponse } from '../services/api.ts';

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

interface ContactFiltersProps {
  onFiltersChange: (filters: ContactFilters) => void;
  currentFilters: ContactFilters;
  pipelines?: PipelineResponse[];
}

export interface ContactFilters {
  funnelStages: string[];
  activeFlows: string[];
}

type StatusFilterOption = {
  color?: string;
  kind: 'contact' | 'crm-stage';
  label: string;
  pipelineName?: string;
  value: string;
};

const contactStatusOption: StatusFilterOption = {
  kind: 'contact',
  label: 'Contato',
  value: 'contato',
};

const legacyStageColorMap: Record<string, string> = {
  amber: '#d97706',
  blue: '#2563eb',
  cyan: '#0891b2',
  emerald: '#059669',
  gray: '#4b5563',
  green: '#16a34a',
  indigo: '#4f46e5',
  lime: '#65a30d',
  neutral: '#525252',
  orange: '#ea580c',
  pink: '#db2777',
  purple: '#9333ea',
  red: '#dc2626',
  rose: '#e11d48',
  sky: '#0284c7',
  slate: '#475569',
  stone: '#57534e',
  teal: '#0d9488',
  yellow: '#ca8a04',
  zinc: '#52525b',
};

const normalizeStageColor = (color?: string) => {
  const value = color?.trim();
  if (!value) return undefined;

  if (/^#[0-9a-f]{6}$/i.test(value)) return value;
  if (/^#[0-9a-f]{3}$/i.test(value)) {
    const [, r, g, b] = value;
    return `#${r}${r}${g}${g}${b}${b}`;
  }

  const lowered = value.toLowerCase();
  const match = Object.entries(legacyStageColorMap).find(([name]) => lowered.includes(name));
  return match?.[1];
};

const getStageChipStyle = (color?: string): React.CSSProperties | undefined => {
  const stageColor = normalizeStageColor(color);
  if (!stageColor) return undefined;

  return {
    backgroundColor: `${stageColor}16`,
    borderColor: `${stageColor}35`,
    color: stageColor,
  };
};

const getContactStatusColors = (isDark: boolean) => (
  isDark
    ? 'border-white/10 bg-white/10 text-white/70'
    : 'border-brand/10 bg-brand-canvas text-brand/70'
);

export const ContactFilters: React.FC<ContactFiltersProps> = ({ onFiltersChange, currentFilters, pipelines = [] }) => {
  const { isDark } = useTheme();
  const [showFunnelDropdown, setShowFunnelDropdown] = useState(false);

  const crmStageOptions = useMemo<StatusFilterOption[]>(() => (
    pipelines.flatMap(pipeline => (
      [...(pipeline.stages || [])]
        .sort((first, second) => first.order - second.order)
        .map(stage => ({
          color: stage.color,
          kind: 'crm-stage' as const,
          label: stage.name,
          pipelineName: pipeline.name,
          value: stage.id.toString(),
        }))
    ))
  ), [pipelines]);

  const statusFilterOptions = useMemo<StatusFilterOption[]>(
    () => [contactStatusOption, ...crmStageOptions],
    [crmStageOptions]
  );

  const activeStatus = currentFilters.funnelStages[0];
  const activeStatusLabel = activeStatus
    ? statusFilterOptions.find(option => option.value === activeStatus)?.label || activeStatus
    : null;

  const handleStatusSelect = (stage: string) => {
    onFiltersChange({
      ...currentFilters,
      funnelStages: activeStatus === stage ? [] : [stage],
    });
    setShowFunnelDropdown(false);
  };

  const clearAllFilters = () => {
    onFiltersChange({
      funnelStages: [],
      activeFlows: []
    });
  };

  const hasActiveFilters = currentFilters.funnelStages.length > 0;

  return (
    <div className={cx('flex items-center gap-2 border-b p-3', isDark ? 'border-white/10' : 'border-brand/10')}>
      <div className="relative">
        <button
          type="button"
          onClick={() => setShowFunnelDropdown(!showFunnelDropdown)}
          className={agentiveSecondaryButtonClass(isDark, 'min-h-10')}
        >
          <SlidersHorizontal className="h-4 w-4" />
          <span>Status</span>
          {activeStatusLabel && (
            <span className={agentivePillClass(isDark, true, 'ml-1 max-w-28 px-2 py-0.5')}>
              <span className="truncate">{activeStatusLabel}</span>
            </span>
          )}
          <ChevronDown className="h-4 w-4" />
        </button>

        {showFunnelDropdown && (
          <div className={agentivePanelClass(isDark, 'absolute left-0 top-full z-50 mt-2 w-72 p-2 shadow-[0_22px_55px_rgba(2,3,35,0.18)]')}>
            <div className={cx('px-2 py-1 text-[10px] font-semibold uppercase', isDark ? 'text-white/40' : 'text-brand/40')}>
              Contato e etapas do CRM
            </div>
            <div className="mt-1 max-h-80 space-y-1 overflow-y-auto pr-1">
              {statusFilterOptions.map((option) => {
                const isSelected = activeStatus === option.value;

                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => handleStatusSelect(option.value)}
                    className={cx('flex w-full items-center justify-between gap-3 rounded-xl px-2.5 py-2 text-left text-sm transition-colors', isDark ? 'text-white/70 hover:bg-white/10' : 'text-brand/70 hover:bg-brand-canvas')}
                  >
                    <span className="min-w-0">
                      <span
                        className={cx(
                          'inline-flex max-w-full items-center rounded-full border px-2 py-0.5 text-xs font-semibold',
                          option.kind === 'contact'
                            ? getContactStatusColors(isDark)
                            : isDark
                              ? 'border-white/10 bg-white/10 text-white/70'
                              : 'border-brand/10 bg-brand-canvas text-brand/70'
                        )}
                        style={option.kind === 'crm-stage' ? getStageChipStyle(option.color) : undefined}
                      >
                        <span className="truncate">{option.label}</span>
                      </span>
                      {option.pipelineName && (
                        <span className={cx('mt-1 block truncate text-[11px]', isDark ? 'text-white/40' : 'text-brand/40')}>
                          {option.pipelineName}
                        </span>
                      )}
                    </span>
                    {isSelected && <Check className="h-4 w-4" />}
                  </button>
                );
              })}
              {crmStageOptions.length === 0 && (
                <div className={cx('rounded-xl px-2.5 py-2 text-xs', isDark ? 'text-white/45' : 'text-brand/45')}>
                  Nenhuma etapa do CRM carregada para esta empresa.
                </div>
              )}
            </div>
            {hasActiveFilters && (
              <>
                <div className={cx('my-2 h-px', isDark ? 'bg-white/10' : 'bg-brand/10')} />
                <button
                  type="button"
                  onClick={clearAllFilters}
                  className={cx('flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-sm transition-colors', isDark ? 'text-white/55 hover:bg-white/10' : 'text-brand/55 hover:bg-brand-canvas')}
                >
                  <X className="h-4 w-4" />
                  Limpar status
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {/* Fechar dropdowns ao clicar fora */}
      {showFunnelDropdown && (
        <div
          className="fixed inset-0 z-40"
          onClick={() => {
            setShowFunnelDropdown(false);
          }}
        />
      )}
    </div>
  );
};
