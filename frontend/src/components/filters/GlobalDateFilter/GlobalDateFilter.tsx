import React, { useEffect, useId, useRef, useState } from 'react';
import { CalendarRange, Check, ChevronDown, RotateCcw } from 'lucide-react';
import { useTheme } from '../../../contexts/ThemeContext.tsx';
import {
  createCustomGlobalDateRange,
  createEmptyGlobalDateRange,
  formatGlobalDateFilterLabel,
  GLOBAL_DATE_PRESET_LABELS,
  GLOBAL_DATE_QUICK_PRESETS,
  type GlobalDateFilterValue,
  type GlobalDatePreset,
  resolveGlobalDatePreset,
  toGlobalDateInputValue,
} from './dateRange.ts';
import './GlobalDateFilter.css';

const cx = (...classes: Array<string | false | null | undefined>) => classes.filter(Boolean).join(' ');

export interface GlobalDateFilterProps {
  align?: 'start' | 'end';
  className?: string;
  disabled?: boolean;
  onChange: (value: GlobalDateFilterValue) => void;
  value: GlobalDateFilterValue;
}

const GlobalDateFilter: React.FC<GlobalDateFilterProps> = ({
  align = 'end',
  className = '',
  disabled = false,
  onChange,
  value,
}) => {
  const { isDark } = useTheme();
  const [isOpen, setIsOpen] = useState(false);
  const [draftStart, setDraftStart] = useState('');
  const [draftEnd, setDraftEnd] = useState('');
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerId = useId();
  const hasActiveFilter = value.preset !== 'all' || Boolean(value.range.startDate || value.range.endDate);

  useEffect(() => {
    if (!isOpen) return;
    setDraftStart(toGlobalDateInputValue(value.range.startDate));
    setDraftEnd(toGlobalDateInputValue(value.range.endDate));
    setError(null);
  }, [isOpen, value.range.endDate, value.range.startDate]);

  useEffect(() => {
    if (!isOpen) return;

    const handlePointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setIsOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsOpen(false);
    };

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen]);

  const selectPreset = (preset: GlobalDatePreset) => {
    onChange({ preset, range: resolveGlobalDatePreset(preset) });
    setIsOpen(false);
  };

  const clearFilter = () => {
    onChange({ preset: 'all', range: createEmptyGlobalDateRange() });
    setIsOpen(false);
  };

  const applyCustomRange = () => {
    if (!draftStart || !draftEnd) {
      setError('Informe as datas de início e fim.');
      return;
    }

    const range = createCustomGlobalDateRange(draftStart, draftEnd);
    if (!range) {
      setError('A data final deve ser igual ou posterior à inicial.');
      return;
    }

    onChange({ preset: 'custom', range });
    setIsOpen(false);
  };

  return (
    <div
      className={cx('global-date-filter', isDark && 'global-date-filter--dark', className)}
      ref={rootRef}
    >
      <button
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        className="global-date-filter__trigger"
        data-active={hasActiveFilter ? 'true' : 'false'}
        disabled={disabled}
        id={triggerId}
        onClick={() => setIsOpen((current) => !current)}
        type="button"
      >
        <CalendarRange aria-hidden="true" />
        <span>{formatGlobalDateFilterLabel(value)}</span>
        <ChevronDown aria-hidden="true" className={cx(isOpen && 'is-open')} />
      </button>

      {isOpen && (
        <div
          aria-labelledby={triggerId}
          className={cx('global-date-filter__popover', `global-date-filter__popover--${align}`)}
          role="dialog"
        >
          <div className="global-date-filter__header">
            <div>
              <strong>Filtrar por período</strong>
              <span>Use um atalho ou defina as datas.</span>
            </div>
            {hasActiveFilter && (
              <button className="global-date-filter__clear" onClick={clearFilter} type="button">
                <RotateCcw aria-hidden="true" />
                Limpar
              </button>
            )}
          </div>

          <div className="global-date-filter__presets" aria-label="Períodos rápidos">
            {GLOBAL_DATE_QUICK_PRESETS.map((preset) => {
              const active = value.preset === preset;
              return (
                <button
                  aria-pressed={active}
                  className={cx('global-date-filter__preset', active && 'is-active')}
                  key={preset}
                  onClick={() => selectPreset(preset)}
                  type="button"
                >
                  <span>{GLOBAL_DATE_PRESET_LABELS[preset]}</span>
                  {active && <Check aria-hidden="true" />}
                </button>
              );
            })}
          </div>

          <div className="global-date-filter__custom">
            <p>Intervalo personalizado</p>
            <div className="global-date-filter__fields">
              <label>
                <span>Início</span>
                <input
                  onChange={(event) => {
                    setDraftStart(event.target.value);
                    setError(null);
                  }}
                  type="date"
                  value={draftStart}
                />
              </label>
              <label>
                <span>Fim</span>
                <input
                  onChange={(event) => {
                    setDraftEnd(event.target.value);
                    setError(null);
                  }}
                  type="date"
                  value={draftEnd}
                />
              </label>
            </div>
            {error && <div className="global-date-filter__error" role="alert">{error}</div>}
            <div className="global-date-filter__footer">
              <button onClick={applyCustomRange} type="button">Aplicar período</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default GlobalDateFilter;
