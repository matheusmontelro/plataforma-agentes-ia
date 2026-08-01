import React from 'react';

interface PanelProps {
  action?: React.ReactNode;
  children: React.ReactNode;
  description?: string;
  icon?: React.ReactNode;
  title: string;
}

export const MonoPanel: React.FC<PanelProps> = ({ action, children, description, icon, title }) => (
  <section className="mono-panel">
    <header className="mono-panel-head">
      <div>
        <h2 className="mono-panel-title">
          {icon}
          <span>{title}</span>
        </h2>
        {description && <p className="mono-panel-kicker">{description}</p>}
      </div>
      {action && <div className="mono-panel-action">{action}</div>}
    </header>
    <div className="mono-panel-body">{children}</div>
  </section>
);
