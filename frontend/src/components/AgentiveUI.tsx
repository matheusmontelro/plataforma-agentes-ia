import React from 'react';
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Info,
  type LucideIcon,
  X,
} from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext.tsx';

type FeedbackVariant = 'error' | 'success' | 'warning' | 'info';
type ConfirmVariant = 'danger' | 'warning' | 'info';
type ToneVariant = 'neutral' | 'primary' | 'success' | 'warning' | 'danger';

const joinClasses = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

export const agentivePageClass = (isDark: boolean, className = '') =>
  joinClasses('min-h-screen w-full pb-24', isDark ? 'bg-brand text-white' : 'bg-brand-canvas text-brand', className);

export const agentivePanelClass = (isDark: boolean, className = '') =>
  joinClasses(
    'rounded-2xl border shadow-flat-md',
    isDark ? 'border-white/10 bg-white/[0.06]' : 'border-brand/10 bg-white',
    className
  );

export const agentiveInputClass = (isDark: boolean, className = '') =>
  joinClasses(
    'w-full rounded-xl border px-3 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20 disabled:opacity-50',
    isDark
      ? 'border-white/10 bg-white/[0.06] text-white placeholder:text-white/35'
      : 'border-brand/10 bg-white text-brand placeholder:text-brand/35',
    className
  );

export const agentiveTextareaClass = (isDark: boolean, className = '') =>
  agentiveInputClass(isDark, joinClasses('min-h-24 resize-y', className));

export const agentiveLabelClass = (isDark: boolean, className = '') =>
  joinClasses('mb-1.5 block text-sm font-medium', isDark ? 'text-white/75' : 'text-brand/70', className);

export const agentiveSecondaryButtonClass = (isDark: boolean, className = '') =>
  joinClasses(
    'inline-flex items-center justify-center gap-2 rounded-xl border px-3 py-2 text-sm font-medium transition-colors disabled:opacity-50',
    isDark
      ? 'border-white/10 bg-white/[0.06] text-white/75 hover:bg-white/10 hover:text-white'
      : 'border-brand/10 bg-white text-brand/70 hover:bg-brand-canvas hover:text-brand',
    className
  );

export const agentivePrimaryButtonClass = (className = '') =>
  joinClasses(
    'inline-flex items-center justify-center gap-2 rounded-xl bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand/90 disabled:opacity-50',
    className
  );

export const agentiveIconButtonClass = (isDark: boolean, variant: ToneVariant = 'neutral', className = '') => {
  const variants: Record<ToneVariant, string> = {
    neutral: isDark
      ? 'text-white/55 hover:bg-white/10 hover:text-white'
      : 'text-brand/45 hover:bg-brand-canvas hover:text-brand',
    primary: isDark
      ? 'text-white/75 hover:bg-white/10 hover:text-white'
      : 'text-brand hover:bg-brand-canvas',
    success: isDark
      ? 'text-emerald-300 hover:bg-emerald-400/10'
      : 'text-emerald-700 hover:bg-emerald-50',
    warning: isDark
      ? 'text-amber-300 hover:bg-amber-400/10'
      : 'text-amber-700 hover:bg-amber-50',
    danger: isDark
      ? 'text-red-300 hover:bg-red-400/10'
      : 'text-red-600 hover:bg-red-50',
  };

  return joinClasses('inline-flex min-h-9 min-w-9 items-center justify-center rounded-xl p-2 transition-colors disabled:opacity-50', variants[variant], className);
};

export const agentivePillClass = (isDark: boolean, active = false, className = '') =>
  joinClasses(
    'inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
    active
      ? isDark
        ? 'border-white/15 bg-white/10 text-white'
        : 'border-brand/15 bg-brand text-white'
      : isDark
        ? 'border-white/10 bg-white/[0.06] text-white/65 hover:bg-white/10'
        : 'border-brand/10 bg-white text-brand/60 hover:bg-brand-canvas hover:text-brand',
    className
  );

const feedbackMeta: Record<FeedbackVariant, { icon: LucideIcon; classes: string; darkClasses: string }> = {
  error: {
    icon: AlertCircle,
    classes: 'border-red-200 bg-red-50 text-red-700',
    darkClasses: 'border-red-700/50 bg-red-900/20 text-red-300',
  },
  success: {
    icon: CheckCircle2,
    classes: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    darkClasses: 'border-emerald-700/50 bg-emerald-900/20 text-emerald-300',
  },
  warning: {
    icon: AlertTriangle,
    classes: 'border-amber-200 bg-amber-50 text-amber-800',
    darkClasses: 'border-amber-700/50 bg-amber-900/20 text-amber-300',
  },
  info: {
    icon: Info,
    classes: 'border-brand/10 bg-brand-canvas text-brand',
    darkClasses: 'border-white/10 bg-white/[0.06] text-white/80',
  },
};

const confirmMeta: Record<ConfirmVariant, { icon: LucideIcon; accent: string; darkAccent: string; button: string }> = {
  danger: {
    icon: AlertTriangle,
    accent: 'bg-red-50 text-red-600 ring-red-100',
    darkAccent: 'bg-red-900/20 text-red-300 ring-red-700/40',
    button: 'bg-red-600 text-white hover:bg-red-700',
  },
  warning: {
    icon: AlertTriangle,
    accent: 'bg-amber-50 text-amber-700 ring-amber-100',
    darkAccent: 'bg-amber-900/20 text-amber-300 ring-amber-700/40',
    button: 'bg-amber-500 text-white hover:bg-amber-600',
  },
  info: {
    icon: Info,
    accent: 'bg-brand-canvas text-brand ring-brand/10',
    darkAccent: 'bg-white/[0.06] text-white ring-white/10',
    button: 'bg-brand text-white hover:bg-brand/90',
  },
};

interface AgentiveAlertProps {
  children?: React.ReactNode;
  className?: string;
  onClose?: () => void;
  title?: string;
  variant?: FeedbackVariant;
}

export const AgentiveAlert: React.FC<AgentiveAlertProps> = ({
  children,
  className = '',
  onClose,
  title,
  variant = 'info',
}) => {
  const { isDark } = useTheme();
  const meta = feedbackMeta[variant];
  const Icon = meta.icon;

  return (
    <div
      className={`flex items-start gap-3 rounded-2xl border p-4 text-sm shadow-flat ${
        isDark ? meta.darkClasses : meta.classes
      } ${className}`}
      role={variant === 'error' ? 'alert' : 'status'}
    >
      <Icon className="mt-0.5 h-5 w-5 shrink-0" />
      <div className="min-w-0 flex-1">
        {title && <p className="font-semibold leading-snug">{title}</p>}
        {children && <div className={title ? 'mt-1 leading-relaxed' : 'leading-relaxed'}>{children}</div>}
      </div>
      {onClose && (
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg p-1 opacity-70 transition hover:bg-current/10 hover:opacity-100"
          aria-label="Fechar aviso"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
};

interface AgentiveConfirmModalProps {
  appearance?: 'default' | 'modern';
  cancelText?: string;
  children?: React.ReactNode;
  confirmText?: string;
  isLoading?: boolean;
  isOpen: boolean;
  message?: React.ReactNode;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  variant?: ConfirmVariant;
}

export const AgentiveConfirmModal: React.FC<AgentiveConfirmModalProps> = ({
  appearance = 'default',
  cancelText = 'Cancelar',
  children,
  confirmText = 'Confirmar',
  isLoading = false,
  isOpen,
  message,
  onClose,
  onConfirm,
  title,
  variant = 'danger',
}) => {
  const { isDark } = useTheme();
  const meta = confirmMeta[variant];
  const Icon = meta.icon;
  const isModern = appearance === 'modern';

  if (!isOpen) return null;

  return (
    <div className={joinClasses('fixed inset-0 z-[9999] flex items-center justify-center p-4', isModern && 'crm-work-modal', isModern && isDark && 'crm-work-modal--dark')}>
      <div className={isModern ? 'fixed inset-0 crm-modern-modal-root' : 'fixed inset-0 bg-brand/55 backdrop-blur-sm'} onClick={isLoading ? undefined : onClose} />
      <div
        className={`${isModern ? 'crm-modern-modal crm-confirm-modal' : ''} relative z-[10000] w-full max-w-md overflow-hidden rounded-2xl border p-5 shadow-[0_24px_70px_rgba(2,3,35,0.28)] ${
          isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand'
        }`}
      >
        <div className={joinClasses('flex items-start justify-between gap-4', isModern && 'crm-confirm-modal__header')}>
          <div className="flex items-start gap-3">
            <div
              className={`${isModern ? 'crm-confirm-modal__icon' : ''} grid h-11 w-11 shrink-0 place-items-center rounded-xl ring-1 ${
                isDark ? meta.darkAccent : meta.accent
              }`}
            >
              <Icon className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-base font-semibold leading-tight">{title}</h3>
              {message && (
                <div className={`mt-1.5 text-sm leading-relaxed ${isDark ? 'text-white/65' : 'text-brand/60'}`}>
                  {message}
                </div>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isLoading}
            className={`${isModern ? 'crm-modern-icon-control' : ''} rounded-xl p-2 transition ${
              isDark ? 'text-white/45 hover:bg-white/10 hover:text-white' : 'text-brand/45 hover:bg-brand-canvas hover:text-brand'
            } disabled:opacity-40`}
            aria-label="Fechar modal"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {children && (
          <div className={`${isModern ? 'crm-confirm-modal__content' : ''} mt-5 rounded-2xl border p-4 text-sm ${isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas'}`}>
            {children}
          </div>
        )}

        <div className={joinClasses('mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end', isModern && 'crm-confirm-modal__footer')}>
          <button
            type="button"
            onClick={onClose}
            disabled={isLoading}
            className={`${isModern ? 'crm-modern-control' : ''} rounded-xl border px-4 py-2.5 text-sm font-medium transition ${
              isDark
                ? 'border-white/10 bg-white/[0.04] text-white/80 hover:bg-white/10'
                : 'border-brand/10 bg-white text-brand/70 hover:bg-brand-canvas hover:text-brand'
            } disabled:opacity-50`}
          >
            {cancelText}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isLoading}
            className={`${isModern ? `crm-modern-control crm-confirm-modal__confirm crm-confirm-modal__confirm--${variant}` : ''} rounded-xl px-4 py-2.5 text-sm font-semibold transition disabled:opacity-60 ${meta.button}`}
          >
            {isLoading ? 'Processando...' : confirmText}
          </button>
        </div>
      </div>
    </div>
  );
};

interface AgentivePageHeaderProps {
  actions?: React.ReactNode;
  badges?: React.ReactNode;
  className?: string;
  description: string;
  icon: LucideIcon;
  title: string;
}

export const AgentivePageHeader: React.FC<AgentivePageHeaderProps> = ({
  actions,
  badges,
  className = '',
  description,
  icon: Icon,
  title,
}) => {
  const { isDark } = useTheme();

  return (
    <header
      className={`rounded-2xl border p-4 shadow-flat-md ${
        isDark ? 'border-white/10 bg-white/[0.06] text-white' : 'border-brand/10 bg-white text-brand'
      } ${className}`}
    >
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <div className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
            <Icon className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-lg font-semibold leading-tight md:text-xl">{title}</h1>
              {badges}
            </div>
            <p className={`mt-1 text-sm leading-snug ${isDark ? 'text-white/55' : 'text-brand/55'}`}>{description}</p>
          </div>
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
};

interface AgentiveEmptyStateProps {
  action?: React.ReactNode;
  className?: string;
  description?: string;
  icon: LucideIcon;
  title: string;
}

export const AgentiveEmptyState: React.FC<AgentiveEmptyStateProps> = ({
  action,
  className = '',
  description,
  icon: Icon,
  title,
}) => {
  const { isDark } = useTheme();

  return (
    <div
      className={joinClasses(
        'rounded-2xl border border-dashed px-6 py-12 text-center',
        isDark ? 'border-white/10 bg-white/[0.04] text-white' : 'border-brand/15 bg-brand-canvas text-brand',
        className
      )}
    >
      <div className={joinClasses('mx-auto mb-4 grid h-14 w-14 place-items-center rounded-2xl', isDark ? 'bg-white/10 text-white' : 'bg-white text-brand')}>
        <Icon className="h-7 w-7" />
      </div>
      <h3 className="text-base font-semibold">{title}</h3>
      {description && <p className={joinClasses('mx-auto mt-1 max-w-md text-sm', isDark ? 'text-white/55' : 'text-brand/55')}>{description}</p>}
      {action && <div className="mt-5 flex justify-center">{action}</div>}
    </div>
  );
};

interface AgentiveStatCardProps {
  icon: LucideIcon;
  label: string;
  value: React.ReactNode;
  helper?: React.ReactNode;
  className?: string;
}

export const AgentiveStatCard: React.FC<AgentiveStatCardProps> = ({
  icon: Icon,
  label,
  value,
  helper,
  className = '',
}) => {
  const { isDark } = useTheme();

  return (
    <div className={agentivePanelClass(isDark, joinClasses('p-4 shadow-flat', className))}>
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className={joinClasses('text-sm font-medium', isDark ? 'text-white/55' : 'text-brand/55')}>{label}</span>
        <Icon className={joinClasses('h-4 w-4', isDark ? 'text-white/55' : 'text-brand/60')} />
      </div>
      <div className="text-2xl font-semibold leading-none">{value}</div>
      {helper && <div className={joinClasses('mt-1 text-xs', isDark ? 'text-white/45' : 'text-brand/45')}>{helper}</div>}
    </div>
  );
};
