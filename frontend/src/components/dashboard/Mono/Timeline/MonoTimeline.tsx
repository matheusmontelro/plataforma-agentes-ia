import React from 'react';
import type { TimelineEvent } from '../../../../services/api';
import BrowserDateTime from '../../../BrowserDateTime';
import { MonoEmpty } from '../States/MonoStates';

interface MonoTimelineProps {
  events: TimelineEvent[];
}

const labelFor = (type: string) => {
  const value = (type || '').toLowerCase();
  if (value.includes('lead')) return 'Novo lead';
  if (value.includes('agendamento')) return 'Agendamento';
  if (value.includes('venda')) return 'Venda realizada';
  if (value.includes('comparecimento')) return 'Comparecimento';
  return type || 'Atividade';
};

const isSignalEvent = (type: string) => (type || '').toLowerCase().includes('venda');

export const MonoTimeline: React.FC<MonoTimelineProps> = ({ events }) => {
  if (events.length === 0) {
    return <MonoEmpty>Sem atividades recentes.</MonoEmpty>;
  }

  const shown = events.slice(0, 8);

  return (
    <div className="mono-timeline">
      {shown.map((event, index) => (
        <article className="mono-tl-item" key={`${event.entity_id}-${event.event_date}-${index}`}>
          <BrowserDateTime className="mono-tl-time mono-num" value={event.event_date} variant="dateTime" />
          <span className="mono-tl-rail">
            <span
              className={`mono-tl-dot ${isSignalEvent(event.event_type) ? 'mono-tl-dot--signal' : ''}`}
            />
          </span>
          <div>
            <div className="mono-tl-title">{labelFor(event.event_type)}</div>
            <p className="mono-tl-desc">{event.descricao || 'Sem descrição'}</p>
          </div>
        </article>
      ))}
    </div>
  );
};
