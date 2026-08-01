import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Select, Tooltip } from 'flowbite-react';
import { CalendarRange, ChevronDown, Check } from 'lucide-react';
import type { DashboardDateRange } from '../types';
import { formatDateToYYYYMMDD, formatDisplayDate } from '../utils/format';

/* ---------------- Button ---------------- */
type ButtonVariant = 'default' | 'primary' | 'ghost';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

const variantClass: Record<ButtonVariant, string> = {
  default: '',
  primary: ' mono-btn--primary',
  ghost: ' mono-btn--ghost',
};

const variantColor: Record<ButtonVariant, string> = {
  default: 'monoDefault',
  primary: 'monoPrimary',
  ghost: 'monoGhost',
};

const joinClasses = (...classes: Array<string | undefined | false>) => classes.filter(Boolean).join(' ');

export const MonoButton: React.FC<ButtonProps> = ({
  children,
  className,
  variant = 'default',
  ...rest
}) => (
  <Button
    className={joinClasses('mono-btn', variantClass[variant].trim(), className)}
    color={variantColor[variant]}
    size="mono"
    type="button"
    {...rest}
  >
    {children}
  </Button>
);

/* ---------------- IconButton ---------------- */
interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
}

export const MonoIconButton: React.FC<IconButtonProps> = ({ children, className, label, ...rest }) => (
  <Tooltip arrow={false} content={label} placement="top" style="auto">
    <Button
      aria-label={label}
      className={joinClasses('mono-icon-btn', className)}
      color="monoIcon"
      size="monoIcon"
      type="button"
      {...rest}
    >
      {children}
    </Button>
  </Tooltip>
);

interface MonoSelectProps extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, 'color'> {}

export const MonoSelect = React.forwardRef<HTMLSelectElement, MonoSelectProps>(
  ({ children, ...rest }, ref) => (
    <Select color="mono" ref={ref} sizing="mono" {...rest}>
      {children}
    </Select>
  ),
);
MonoSelect.displayName = 'MonoSelect';

/* ---------------- Segmented (radiogroup) ---------------- */
interface SegmentOption {
  label: string;
  value: string;
}

interface SegmentedProps {
  'aria-label': string;
  disabled?: boolean;
  onChange: (value: string) => void;
  options: SegmentOption[];
  value: string;
}

export const MonoSegmented: React.FC<SegmentedProps> = ({
  'aria-label': ariaLabel,
  disabled,
  onChange,
  options,
  value,
}) => {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);

  const focusByIndex = useCallback((index: number) => {
    const next = options[(index + options.length) % options.length];
    if (next) onChange(next.value);
    requestAnimationFrame(() => {
      const idx = options.findIndex((option) => option.value === next?.value);
      refs.current[idx]?.focus();
    });
  }, [onChange, options]);

  const onKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
      event.preventDefault();
      focusByIndex(index + 1);
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
      event.preventDefault();
      focusByIndex(index - 1);
    }
  };

  return (
    <div aria-label={ariaLabel} className="mono-segmented" role="radiogroup">
      {options.map((option, index) => {
        const checked = option.value === value;
        return (
          <button
            aria-checked={checked}
            className="mono-seg-item"
            disabled={disabled}
            key={option.value || 'all'}
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => onKeyDown(event, index)}
            ref={(element) => {
              refs.current[index] = element;
            }}
            role="radio"
            tabIndex={checked ? 0 : -1}
            type="button"
          >
            {checked && <Check style={{ width: 12, height: 12 }} />}
            {option.label}
          </button>
        );
      })}
    </div>
  );
};

/* ---------------- DateRange ---------------- */
interface DateRangeProps {
  dateRange: DashboardDateRange;
  disabled?: boolean;
  onDateChange: (startDate: string, endDate: string) => void;
}

const getStartOfCurrentMonth = () => {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), 1);
};

const getEndOfCurrentMonth = () => {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth() + 1, 0);
};

const buildPreset = (preset: 'today' | 'week' | 'month') => {
  if (preset === 'today') {
    const today = new Date();
    return { end: formatDateToYYYYMMDD(today), start: formatDateToYYYYMMDD(today) };
  }
  if (preset === 'week') {
    const now = new Date();
    const start = new Date(now);
    start.setDate(now.getDate() - now.getDay());
    const end = new Date(now);
    end.setDate(now.getDate() + (6 - now.getDay()));
    return { end: formatDateToYYYYMMDD(end), start: formatDateToYYYYMMDD(start) };
  }
  return {
    end: formatDateToYYYYMMDD(getEndOfCurrentMonth()),
    start: formatDateToYYYYMMDD(getStartOfCurrentMonth()),
  };
};

export const MonoDateRange: React.FC<DateRangeProps> = ({ dateRange, disabled, onDateChange }) => {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsOpen(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [isOpen]);

  const triggerId = React.useId();

  return (
    <div className="mono-date-picker" ref={containerRef}>
      <Button
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        className="mono-date-trigger"
        color="monoDate"
        disabled={disabled}
        id={triggerId}
        onClick={() => setIsOpen((current) => !current)}
        size="mono"
        type="button"
      >
        <CalendarRange />
        <span className="mono-date-label">
          {formatDisplayDate(dateRange.startDate)} — {formatDisplayDate(dateRange.endDate)}
        </span>
        <ChevronDown />
      </Button>

      {isOpen && (
        <div aria-labelledby={triggerId} className="mono-date-menu" role="dialog">
          <p className="mono-eyebrow">Períodos rápidos</p>
          <div className="mono-date-presets">
            {(['today', 'week', 'month'] as const).map((preset) => (
              <button
                className="mono-btn mono-btn--ghost"
                key={preset}
                onClick={() => {
                  const dates = buildPreset(preset);
                  onDateChange(dates.start, dates.end);
                  setIsOpen(false);
                }}
                type="button"
              >
                {preset === 'today' ? 'Hoje' : preset === 'week' ? 'Semana' : 'Mês'}
              </button>
            ))}
          </div>

          <div className="mono-date-custom">
            <label className="mono-field">
              <span className="mono-label">Início</span>
              <input
                className="mono-date-input"
                onChange={(event) => onDateChange(event.target.value, dateRange.endDate)}
                type="date"
                value={dateRange.startDate}
              />
            </label>
            <label className="mono-field">
              <span className="mono-label">Fim</span>
              <input
                className="mono-date-input"
                onChange={(event) => onDateChange(dateRange.startDate, event.target.value)}
                type="date"
                value={dateRange.endDate}
              />
            </label>
          </div>
        </div>
      )}
    </div>
  );
};
