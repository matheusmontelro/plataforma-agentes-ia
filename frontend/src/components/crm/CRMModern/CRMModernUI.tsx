import React from 'react';
import type { LucideIcon } from 'lucide-react';
import './CRMModernUI.css';

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

export type CrmModernTone = 'neutral' | 'primary' | 'success' | 'warning' | 'danger';

export const crmModernPanelClass = (_isDark: boolean, className = '') =>
  cx('crm-modern-panel', className);

export const crmModernInputClass = (_isDark: boolean, className = '') =>
  cx('crm-modern-input', className);

export const crmModernLabelClass = (_isDark: boolean, className = '') =>
  cx('crm-modern-label', className);

export const crmModernSecondaryButtonClass = (_isDark: boolean, className = '') =>
  cx('crm-modern-control', className);

export const crmModernPrimaryButtonClass = (className = '') =>
  cx('crm-modern-control crm-modern-control--primary', className);

export const crmModernIconButtonClass = (
  _isDark: boolean,
  tone: CrmModernTone = 'neutral',
  className = '',
) => cx('crm-modern-icon-control', `crm-modern-icon-control--${tone}`, className);

export const crmModernBadgeClass = (_isDark: boolean, active = false, className = '') =>
  cx('crm-modern-badge', active && 'crm-modern-badge--active', className);

interface CrmModernEmptyStateProps {
  action?: React.ReactNode;
  className?: string;
  description?: string;
  icon: LucideIcon;
  title: string;
}

export const CrmModernEmptyState: React.FC<CrmModernEmptyStateProps> = ({
  action,
  className = '',
  description,
  icon: Icon,
  title,
}) => (
  <div className={cx('crm-modern-empty', className)}>
    <span className="crm-modern-empty__icon" aria-hidden="true">
      <Icon />
    </span>
    <div className="crm-modern-empty__copy">
      <strong>{title}</strong>
      {description && <span>{description}</span>}
    </div>
    {action && <div className="crm-modern-empty__action">{action}</div>}
  </div>
);

export default CrmModernEmptyState;
