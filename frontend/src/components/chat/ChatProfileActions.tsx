import React from 'react';
import {
  CheckCircle2,
  StickyNote,
} from 'lucide-react';
import {
  agentivePanelClass,
  agentivePillClass,
  agentiveSecondaryButtonClass,
} from '../AgentiveUI.tsx';

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

interface ChatProfileActionsProps {
  isDark: boolean;
  onOpenNotes: () => void;
  onOpenTasks: () => void;
  pendingTasksCount?: number;
}

export default function ChatProfileActions({
  isDark,
  onOpenNotes,
  onOpenTasks,
  pendingTasksCount = 0,
}: ChatProfileActionsProps) {
  const mutedClass = isDark ? 'text-white/55' : 'text-brand/55';

  return (
    <section className={agentivePanelClass(isDark, 'overflow-hidden p-4')}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold">Ações do perfil</p>
          <p className={cx('mt-1 text-xs', mutedClass)}>Tarefas e anotações deste contato.</p>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
        <button type="button" onClick={onOpenTasks} className={cx(agentiveSecondaryButtonClass(isDark, 'relative justify-center'), 'min-w-0')}>
          <span className="flex min-w-0 items-center justify-center gap-2">
            <CheckCircle2 className="h-4 w-4" />
            Tarefas
          </span>
          {pendingTasksCount > 0 && (
            <span className={agentivePillClass(isDark, true, 'absolute right-3 px-2 py-0.5')}>
              {pendingTasksCount > 9 ? '9+' : pendingTasksCount}
            </span>
          )}
        </button>

        <button type="button" onClick={onOpenNotes} className={agentiveSecondaryButtonClass(isDark, 'justify-center')}>
          <StickyNote className="h-4 w-4" />
          Anotacoes
        </button>
      </div>
    </section>
  );
}
