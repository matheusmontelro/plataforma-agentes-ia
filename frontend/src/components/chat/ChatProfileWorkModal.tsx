import React, { useEffect, useMemo, useState } from 'react';
import {
  Calendar,
  CheckCircle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Edit2,
  Loader2,
  Mail,
  MessageSquare,
  Phone,
  Plus,
  StickyNote,
  Tag,
  Trash2,
  User,
  X,
} from 'lucide-react';
import { format, formatDistanceToNow, isPast, isToday, isTomorrow, parseISO } from 'date-fns';
import { ptBR } from 'date-fns/locale';
import api from '../../services/api.ts';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import {
  AgentiveAlert,
  AgentiveConfirmModal,
} from '../AgentiveUI.tsx';
import {
  CrmModernEmptyState,
  crmModernBadgeClass,
  crmModernIconButtonClass,
  crmModernInputClass,
  crmModernPanelClass,
  crmModernPrimaryButtonClass,
  crmModernSecondaryButtonClass,
} from '../crm/CRMModern/CRMModernUI.tsx';
import './ChatProfileWorkModal.css';

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

export type ChatProfileWorkMode = 'tasks' | 'notes';

type TaskType = 'message' | 'call' | 'email';
type TaskPriority = 'low' | 'medium' | 'high' | 'urgent';
type TaskStatus = 'pending' | 'in_progress' | 'completed' | 'canceled';
type TaskFilter = 'all' | 'pending' | 'completed';

interface ProfileTask {
  id: number;
  contact_id: number;
  contact_name: string;
  contact_phone: string;
  task_type: TaskType | 'scheduled_message';
  title: string;
  description?: string;
  scheduled_for: string;
  reminder_minutes: number;
  status: TaskStatus;
  priority: TaskPriority;
  tags?: string[];
  created_at: string;
  updated_at: string;
  created_by?: {
    id: number;
    name: string;
    email: string;
    type?: string;
  };
  assigned_to?: {
    id: number;
    name: string;
    email: string;
  };
  completed_at?: string;
  completed_by?: {
    id: number;
    name: string;
    email: string;
  };
  comments_count?: number;
}

interface ProfileNote {
  id: number;
  contact_id: number;
  contact_name: string;
  contact_phone: string;
  content: string;
  created_at: string;
  updated_at: string;
  created_by?: {
    id: number;
    name: string;
    email: string;
    type?: string;
  };
}

interface TaskFormData {
  task_type: TaskType;
  title: string;
  description: string;
  scheduled_for: string;
  reminder_minutes: number;
  priority: TaskPriority;
  tags: string[];
}

interface NoteFormData {
  content: string;
}

interface ChatProfileWorkModalProps {
  className?: string;
  contactId: string;
  contactName: string;
  contactPhone: string;
  embedded?: boolean;
  isOpen: boolean;
  mode: ChatProfileWorkMode;
  onClose?: () => void;
  onModeChange: (mode: ChatProfileWorkMode) => void;
  onPendingTasksChange?: (pendingCount: number) => void;
}

const defaultTaskForm = (): TaskFormData => ({
  task_type: 'message',
  title: '',
  description: '',
  scheduled_for: format(new Date(), "yyyy-MM-dd'T'HH:mm"),
  reminder_minutes: 15,
  priority: 'medium',
  tags: [],
});

const defaultNoteForm = (): NoteFormData => ({
  content: '',
});

const parseDate = (value: string) => {
  const parsed = parseISO(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

const formatDateTime = (value: string) => {
  const parsed = parseDate(value);
  if (!parsed) return 'Data não registrada';
  return format(parsed, "dd/MM/yyyy 'às' HH:mm", { locale: ptBR });
};

const formatRelativeDate = (value: string) => {
  const parsed = parseDate(value);
  if (!parsed) return 'sem data';
  return formatDistanceToNow(parsed, { locale: ptBR, addSuffix: true });
};

const toDateTimeInput = (value: string) => {
  const parsed = parseDate(value);
  if (!parsed) return format(new Date(), "yyyy-MM-dd'T'HH:mm");
  return format(parsed, "yyyy-MM-dd'T'HH:mm");
};

const isPendingTask = (task: ProfileTask) => task.status === 'pending' || task.status === 'in_progress';

const priorityLabel: Record<TaskPriority, string> = {
  low: 'Baixa',
  medium: 'Média',
  high: 'Alta',
  urgent: 'Urgente',
};

const statusLabel: Record<TaskStatus, string> = {
  pending: 'Pendente',
  in_progress: 'Em progresso',
  completed: 'Concluída',
  canceled: 'Cancelada',
};

const taskTypeOptions: Array<{ id: TaskType; label: string; icon: typeof MessageSquare }> = [
  { id: 'message', label: 'Mensagem', icon: MessageSquare },
  { id: 'call', label: 'Ligação', icon: Phone },
  { id: 'email', label: 'Email', icon: Mail },
];

const getTaskIcon = (type: string) => {
  switch (type) {
    case 'call':
      return Phone;
    case 'email':
      return Mail;
    default:
      return MessageSquare;
  }
};

const getPriorityClass = (isDark: boolean, priority: TaskPriority) => {
  void isDark;
  return `crm-profile-priority crm-profile-priority--${priority}`;
};

const formatTaskSchedule = (value: string) => {
  const parsed = parseDate(value);
  if (!parsed) return { text: 'Sem data', overdue: false };

  if (isPast(parsed) && !isToday(parsed)) {
    return { text: `Atrasada ha ${formatDistanceToNow(parsed, { locale: ptBR })}`, overdue: true };
  }
  if (isToday(parsed)) {
    return { text: `Hoje as ${format(parsed, 'HH:mm')}`, overdue: false };
  }
  if (isTomorrow(parsed)) {
    return { text: `Amanha as ${format(parsed, 'HH:mm')}`, overdue: false };
  }
  return { text: format(parsed, "dd/MM 'as' HH:mm", { locale: ptBR }), overdue: false };
};

export default function ChatProfileWorkModal({
  className,
  contactId,
  contactName,
  contactPhone,
  embedded = false,
  isOpen,
  mode,
  onClose,
  onModeChange,
  onPendingTasksChange,
}: ChatProfileWorkModalProps) {
  const { isDark } = useTheme();
  const [tasks, setTasks] = useState<ProfileTask[]>([]);
  const [notes, setNotes] = useState<ProfileNote[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [notesLoading, setNotesLoading] = useState(false);
  const [taskFilter, setTaskFilter] = useState<TaskFilter>('all');
  const [expandedTasks, setExpandedTasks] = useState<Set<number>>(new Set());
  const [expandedNotes, setExpandedNotes] = useState<Set<number>>(new Set());
  const [taskFormOpen, setTaskFormOpen] = useState(false);
  const [noteFormOpen, setNoteFormOpen] = useState(false);
  const [editingTask, setEditingTask] = useState<ProfileTask | null>(null);
  const [editingNote, setEditingNote] = useState<ProfileNote | null>(null);
  const [taskForm, setTaskForm] = useState<TaskFormData>(() => defaultTaskForm());
  const [noteForm, setNoteForm] = useState<NoteFormData>(() => defaultNoteForm());
  const [taskToDelete, setTaskToDelete] = useState<ProfileTask | null>(null);
  const [noteToDelete, setNoteToDelete] = useState<ProfileNote | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const mutedClass = 'crm-modern-muted';
  const pendingTasks = tasks.filter(isPendingTask);

  const fetchTasks = async () => {
    setTasksLoading(true);
    try {
      const response = await api.get(`/api/contacts/${contactId}/tasks`);
      const items = Array.isArray(response.data) ? response.data : [];
      setTasks(items);
      onPendingTasksChange?.(items.filter(isPendingTask).length);
    } catch (error) {
      console.error('Erro ao carregar tarefas do perfil:', error);
      setTasks([]);
      setFeedback({ type: 'error', message: 'Não foi possível carregar as tarefas deste contato.' });
    } finally {
      setTasksLoading(false);
    }
  };

  const fetchNotes = async () => {
    setNotesLoading(true);
    try {
      const response = await api.get(`/api/contacts/${contactId}/notes`);
      setNotes(Array.isArray(response.data) ? response.data : []);
    } catch (error) {
      console.error('Erro ao carregar anotacoes do perfil:', error);
      setNotes([]);
      setFeedback({ type: 'error', message: 'Não foi possível carregar as anotações deste contato.' });
    } finally {
      setNotesLoading(false);
    }
  };

  useEffect(() => {
    if (!isOpen) return;
    setFeedback(null);
    setTaskFormOpen(false);
    setNoteFormOpen(false);
    setEditingTask(null);
    setEditingNote(null);
    setTaskForm(defaultTaskForm());
    setNoteForm(defaultNoteForm());
    fetchTasks();
    fetchNotes();
  }, [isOpen, contactId]);

  const filteredTasks = useMemo(() => {
    if (taskFilter === 'pending') return tasks.filter(isPendingTask);
    if (taskFilter === 'completed') return tasks.filter(task => task.status === 'completed');
    return tasks;
  }, [taskFilter, tasks]);

  const openNewTask = () => {
    setEditingTask(null);
    setTaskForm(defaultTaskForm());
    setTaskFormOpen(true);
    onModeChange('tasks');
  };

  const openEditTask = (task: ProfileTask) => {
    setEditingTask(task);
    setTaskForm({
      task_type: task.task_type === 'call' || task.task_type === 'email' ? task.task_type : 'message',
      title: task.title,
      description: task.description || '',
      scheduled_for: toDateTimeInput(task.scheduled_for),
      reminder_minutes: task.reminder_minutes,
      priority: task.priority,
      tags: task.tags || [],
    });
    setTaskFormOpen(true);
    onModeChange('tasks');
  };

  const openNewNote = () => {
    setEditingNote(null);
    setNoteForm(defaultNoteForm());
    setNoteFormOpen(true);
    onModeChange('notes');
  };

  const openEditNote = (note: ProfileNote) => {
    setEditingNote(note);
    setNoteForm({ content: note.content });
    setNoteFormOpen(true);
    onModeChange('notes');
  };

  const resetTaskForm = () => {
    setTaskFormOpen(false);
    setEditingTask(null);
    setTaskForm(defaultTaskForm());
  };

  const resetNoteForm = () => {
    setNoteFormOpen(false);
    setEditingNote(null);
    setNoteForm(defaultNoteForm());
  };

  const handleTaskSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!taskForm.title.trim()) {
      setFeedback({ type: 'error', message: 'Informe o titulo da tarefa.' });
      return;
    }

    setActionLoading(true);
    try {
      const payload = {
        task_type: taskForm.task_type,
        title: taskForm.title.trim(),
        description: taskForm.description.trim() || undefined,
        scheduled_for: taskForm.scheduled_for,
        reminder_minutes: taskForm.reminder_minutes,
        priority: taskForm.priority,
        tags: taskForm.tags,
      };
      const config = { headers: { 'X-Timezone': Intl.DateTimeFormat().resolvedOptions().timeZone } };

      if (editingTask) {
        await api.put(`/api/tasks/${editingTask.id}`, payload, config);
        setFeedback({ type: 'success', message: 'Tarefa atualizada no perfil.' });
      } else {
        await api.post(`/api/contacts/${contactId}/tasks`, payload, config);
        setFeedback({ type: 'success', message: 'Tarefa adicionada ao perfil.' });
      }

      resetTaskForm();
      await fetchTasks();
    } catch (error) {
      console.error('Erro ao salvar tarefa do perfil:', error);
      setFeedback({ type: 'error', message: 'Não foi possível salvar a tarefa.' });
    } finally {
      setActionLoading(false);
    }
  };

  const handleNoteSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!noteForm.content.trim()) {
      setFeedback({ type: 'error', message: 'Escreva a anotação antes de salvar.' });
      return;
    }

    setActionLoading(true);
    try {
      const payload = { content: noteForm.content.trim() };

      if (editingNote) {
        await api.put(`/api/notes/${editingNote.id}`, payload);
        setFeedback({ type: 'success', message: 'Anotação atualizada no perfil.' });
      } else {
        await api.post(`/api/contacts/${contactId}/notes`, payload);
        setFeedback({ type: 'success', message: 'Anotação adicionada ao perfil.' });
      }

      resetNoteForm();
      await fetchNotes();
    } catch (error) {
      console.error('Erro ao salvar anotacao do perfil:', error);
      setFeedback({ type: 'error', message: 'Não foi possível salvar a anotação.' });
    } finally {
      setActionLoading(false);
    }
  };

  const handleCompleteTask = async (task: ProfileTask) => {
    setActionLoading(true);
    try {
      await api.post(`/api/tasks/${task.id}/complete`);
      setFeedback({ type: 'success', message: 'Tarefa concluida no perfil.' });
      await fetchTasks();
    } catch (error) {
      console.error('Erro ao concluir tarefa do perfil:', error);
      setFeedback({ type: 'error', message: 'Não foi possível concluir a tarefa.' });
    } finally {
      setActionLoading(false);
    }
  };

  const confirmDeleteTask = async () => {
    if (!taskToDelete) return;
    setActionLoading(true);
    try {
      await api.delete(`/api/tasks/${taskToDelete.id}`);
      setFeedback({ type: 'success', message: 'Tarefa removida do perfil.' });
      setTaskToDelete(null);
      await fetchTasks();
    } catch (error) {
      console.error('Erro ao remover tarefa do perfil:', error);
      setFeedback({ type: 'error', message: 'Não foi possível remover a tarefa.' });
    } finally {
      setActionLoading(false);
    }
  };

  const confirmDeleteNote = async () => {
    if (!noteToDelete) return;
    setActionLoading(true);
    try {
      await api.delete(`/api/notes/${noteToDelete.id}`);
      setFeedback({ type: 'success', message: 'Anotação removida do perfil.' });
      setNoteToDelete(null);
      await fetchNotes();
    } catch (error) {
      console.error('Erro ao remover anotacao do perfil:', error);
      setFeedback({ type: 'error', message: 'Não foi possível remover a anotação.' });
    } finally {
      setActionLoading(false);
    }
  };

  const completedTasksCount = tasks.filter(task => task.status === 'completed').length;
  const EmbeddedModeIcon = mode === 'tasks' ? CheckCircle2 : StickyNote;
  const embeddedComposerOpen = mode === 'tasks' ? taskFormOpen : noteFormOpen;

  if (!isOpen) return null;

  return (
    <div className={embedded ? cx('crm-profile-work', className) : cx('crm-work-modal fixed inset-0 z-[120] flex items-center justify-center p-2 sm:p-5', isDark && 'crm-work-modal--dark')}>
      {!embedded && <div className="crm-modern-modal-root absolute inset-0" onClick={onClose} />}

      <section className={cx(
        embedded
          ? cx('crm-profile-work__surface', embeddedComposerOpen && 'is-composing')
          : 'crm-modern-modal relative z-10 flex h-full w-full max-w-5xl flex-col overflow-hidden sm:h-auto sm:max-h-[92vh]'
      )}>
        {embedded && !embeddedComposerOpen && (
          <header className="crm-profile-work__embedded-header">
            <div className="crm-profile-work__embedded-heading">
              <span className="crm-profile-work__embedded-icon" aria-hidden="true">
                <EmbeddedModeIcon className="h-4 w-4" />
              </span>
              <div className="min-w-0">
                <p className="crm-profile-work__eyebrow">Operação do lead</p>
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <h2 className="text-sm font-semibold">{mode === 'tasks' ? 'Tarefas' : 'Anotações'}</h2>
                  <span className={crmModernBadgeClass(isDark, false, 'tabular-nums')}>
                    {mode === 'tasks' ? `${pendingTasks.length} pendentes` : `${notes.length} registros`}
                  </span>
                </div>
                <p className={cx('mt-1 text-xs leading-relaxed', mutedClass)}>
                  {mode === 'tasks'
                    ? 'Organize os próximos contatos e acompanhe o que já foi concluído.'
                    : 'Registre contexto e decisões importantes do atendimento.'}
                </p>
              </div>
            </div>

            {!embeddedComposerOpen && (
              <button
                type="button"
                onClick={mode === 'tasks' ? openNewTask : openNewNote}
                className={crmModernPrimaryButtonClass('crm-profile-work__primary-action shrink-0')}
              >
                <Plus className="h-4 w-4" />
                {mode === 'tasks' ? 'Nova tarefa' : 'Nova anotação'}
              </button>
            )}
          </header>
        )}

        {!embedded && <header className="crm-modern-modal__header shrink-0">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-sm font-semibold">Centro operacional do perfil</p>
              <p className={cx('mt-1 truncate text-xs', mutedClass)}>
                {contactName || 'Contato sem nome'} • {contactPhone}
              </p>
            </div>
            <button type="button" onClick={onClose} className={crmModernIconButtonClass(isDark, 'neutral', 'crm-action-icon')} aria-label="Fechar tarefas e anotações" title="Fechar">
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="crm-profile-work__tabs mt-4 grid grid-cols-2">
            <button
              type="button"
              onClick={() => onModeChange('tasks')}
              className={cx('crm-profile-work__tab', mode === 'tasks' && 'is-active')}
            >
              <CheckCircle2 className="h-4 w-4" />
              Tarefas
              {pendingTasks.length > 0 && <span className={crmModernBadgeClass(isDark, mode === 'tasks', 'px-2 py-0.5')}>{pendingTasks.length}</span>}
            </button>
            <button
              type="button"
              onClick={() => onModeChange('notes')}
              className={cx('crm-profile-work__tab', mode === 'notes' && 'is-active')}
            >
              <StickyNote className="h-4 w-4" />
              Anotações
              {notes.length > 0 && <span className={crmModernBadgeClass(isDark, mode === 'notes', 'px-2 py-0.5')}>{notes.length}</span>}
            </button>
          </div>
        </header>}

        <div className={embedded ? 'crm-profile-work__body' : 'crm-modern-modal__body min-h-0 flex-1 overflow-y-auto custom-scrollbar'}>
          {feedback && (
            <AgentiveAlert title={feedback.type === 'success' ? 'Atualizado' : 'Erro'} variant={feedback.type} onClose={() => setFeedback(null)} className="crm-modern-alert mb-4">
              {feedback.message}
            </AgentiveAlert>
          )}

          {mode === 'tasks' ? (
            <div className="crm-profile-work__view">
              {(tasks.length > 0 || !embedded) && (
                <div className="crm-profile-work__toolbar">
                  <div className="crm-profile-work__filters" role="group" aria-label="Filtrar tarefas">
                    {[
                      { id: 'all' as const, label: `Todas (${tasks.length})` },
                      { id: 'pending' as const, label: `Pendentes (${pendingTasks.length})` },
                      { id: 'completed' as const, label: `Concluídas (${completedTasksCount})` },
                    ].map(item => (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => setTaskFilter(item.id)}
                        className={cx('crm-profile-work__filter', taskFilter === item.id && 'is-active')}
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>

                  {!embedded && (
                    <button type="button" onClick={openNewTask} className={crmModernPrimaryButtonClass('shrink-0')}>
                      <Plus className="h-4 w-4" />
                      Nova tarefa
                    </button>
                  )}
                </div>
              )}

              {taskFormOpen && (
                <TaskForm
                  actionLoading={actionLoading}
                  form={taskForm}
                  isDark={isDark}
                  isEditing={Boolean(editingTask)}
                  onCancel={resetTaskForm}
                  onChange={setTaskForm}
                  onSubmit={handleTaskSubmit}
                />
              )}

              {tasksLoading ? (
                <LoadingState isDark={isDark} label="Carregando tarefas" />
              ) : filteredTasks.length === 0 ? (
                embedded && tasks.length === 0 ? null : (
                  <CrmModernEmptyState
                    icon={Calendar}
                    title="Nenhuma tarefa neste filtro"
                    description="Crie a próxima atividade deste contato sem sair do perfil CRM."
                    action={!embedded ? (
                      <button type="button" onClick={openNewTask} className={crmModernPrimaryButtonClass()}>
                        <Plus className="h-4 w-4" />
                        Nova tarefa
                      </button>
                    ) : undefined}
                  />
                )
              ) : (
                <div className="crm-profile-work__list">
                  {filteredTasks.map(task => (
                    <TaskCard
                      expanded={expandedTasks.has(task.id)}
                      isDark={isDark}
                      key={task.id}
                      onComplete={() => handleCompleteTask(task)}
                      onDelete={() => setTaskToDelete(task)}
                      onEdit={() => openEditTask(task)}
                      onToggleExpanded={() => {
                        setExpandedTasks(prev => {
                          const next = new Set(prev);
                          if (next.has(task.id)) next.delete(task.id);
                          else next.add(task.id);
                          return next;
                        });
                      }}
                      task={task}
                    />
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="crm-profile-work__view">
              {!embedded && (
                <div className="crm-profile-work__toolbar">
                  <div>
                    <p className="text-sm font-semibold">Anotações do atendimento</p>
                    <p className={cx('mt-1 text-xs', mutedClass)}>Registros ficam vinculados ao contato e visíveis no painel.</p>
                  </div>
                  <button type="button" onClick={openNewNote} className={crmModernPrimaryButtonClass('shrink-0')}>
                    <Plus className="h-4 w-4" />
                    Nova anotação
                  </button>
                </div>
              )}

              {noteFormOpen && (
                <NoteForm
                  actionLoading={actionLoading}
                  form={noteForm}
                  isDark={isDark}
                  isEditing={Boolean(editingNote)}
                  onCancel={resetNoteForm}
                  onChange={setNoteForm}
                  onSubmit={handleNoteSubmit}
                />
              )}

              {notesLoading ? (
                <LoadingState isDark={isDark} label="Carregando anotações" />
              ) : notes.length === 0 ? (
                embedded ? null : (
                  <CrmModernEmptyState
                    icon={StickyNote}
                    title="Nenhuma anotação"
                    description="Registre contexto, combinados ou observações sem sair do perfil CRM."
                    action={(
                      <button type="button" onClick={openNewNote} className={crmModernPrimaryButtonClass()}>
                        <Plus className="h-4 w-4" />
                        Nova anotação
                      </button>
                    )}
                  />
                )
              ) : (
                <div className="crm-profile-work__list">
                  {notes.map(note => (
                    <NoteCard
                      expanded={expandedNotes.has(note.id)}
                      isDark={isDark}
                      key={note.id}
                      note={note}
                      onDelete={() => setNoteToDelete(note)}
                      onEdit={() => openEditNote(note)}
                      onToggleExpanded={() => {
                        setExpandedNotes(prev => {
                          const next = new Set(prev);
                          if (next.has(note.id)) next.delete(note.id);
                          else next.add(note.id);
                          return next;
                        });
                      }}
                    />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      <AgentiveConfirmModal
        appearance="modern"
        cancelText="Cancelar"
        confirmText="Excluir tarefa"
        isLoading={actionLoading}
        isOpen={Boolean(taskToDelete)}
        message="Esta tarefa será removida do histórico operacional do contato."
        onClose={() => {
          if (!actionLoading) setTaskToDelete(null);
        }}
        onConfirm={confirmDeleteTask}
        title="Excluir tarefa?"
        variant="danger"
      />

      <AgentiveConfirmModal
        appearance="modern"
        cancelText="Cancelar"
        confirmText="Excluir anotação"
        isLoading={actionLoading}
        isOpen={Boolean(noteToDelete)}
        message="Esta anotação será removida do histórico do contato."
        onClose={() => {
          if (!actionLoading) setNoteToDelete(null);
        }}
        onConfirm={confirmDeleteNote}
        title="Excluir anotação?"
        variant="danger"
      />
    </div>
  );
}

function LoadingState({ isDark, label }: { isDark: boolean; label: string }) {
  void isDark;
  return (
    <div className="crm-profile-work__loading">
      <div className="flex items-center gap-2 text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {label}
      </div>
    </div>
  );
}

interface TaskFormProps {
  actionLoading: boolean;
  form: TaskFormData;
  isDark: boolean;
  isEditing: boolean;
  onCancel: () => void;
  onChange: React.Dispatch<React.SetStateAction<TaskFormData>>;
  onSubmit: (event: React.FormEvent) => void;
}

function TaskForm({ actionLoading, form, isDark, isEditing, onCancel, onChange, onSubmit }: TaskFormProps) {
  const mutedClass = 'crm-modern-muted';

  return (
    <form onSubmit={onSubmit} className={crmModernPanelClass(isDark, 'crm-profile-form')}>
      <div className="crm-profile-form__header">
        <div className="crm-profile-form__heading">
          <span className="crm-profile-form__icon" aria-hidden="true">
            <Calendar className="h-4 w-4" />
          </span>
          <div>
            <p className="text-sm font-semibold">{isEditing ? 'Editar tarefa' : 'Nova tarefa'}</p>
            <p className={cx('mt-1 text-xs', mutedClass)}>Defina o próximo passo e quando ele deve acontecer.</p>
          </div>
        </div>
        <button type="button" onClick={onCancel} className={crmModernIconButtonClass(isDark, 'neutral', 'crm-action-icon')} aria-label="Fechar formulário de tarefa" title="Fechar">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="crm-profile-form__body">
        <div>
          <label className={cx('mb-2 block text-xs font-semibold', mutedClass)}>Tipo</label>
          <div className="grid gap-2 sm:grid-cols-3">
            {taskTypeOptions.map(option => {
              const Icon = option.icon;
              const selected = form.task_type === option.id;
              return (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => onChange(prev => ({ ...prev, task_type: option.id }))}
                  className={cx('crm-profile-type', selected && 'is-active')}
                >
                  <Icon className="h-4 w-4" />
                  {option.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <label className={cx('mb-1.5 block text-xs font-semibold', mutedClass)}>Título</label>
            <input
              className={crmModernInputClass(isDark)}
              onChange={event => onChange(prev => ({ ...prev, title: event.target.value }))}
              placeholder="Ex: Retornar proposta"
              required
              value={form.title}
            />
          </div>
          <div>
            <label className={cx('mb-1.5 block text-xs font-semibold', mutedClass)}>Data e hora</label>
            <input
              className={crmModernInputClass(isDark)}
              onChange={event => onChange(prev => ({ ...prev, scheduled_for: event.target.value }))}
              required
              type="datetime-local"
              value={form.scheduled_for}
            />
          </div>
        </div>

        <div>
          <label className={cx('mb-1.5 block text-xs font-semibold', mutedClass)}>Descrição</label>
          <textarea
            className={crmModernInputClass(isDark, 'min-h-20 resize-y')}
            onChange={event => onChange(prev => ({ ...prev, description: event.target.value }))}
            placeholder="Contexto da atividade"
            value={form.description}
          />
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          <div>
            <label className={cx('mb-1.5 block text-xs font-semibold', mutedClass)}>Prioridade</label>
            <select className={crmModernInputClass(isDark)} value={form.priority} onChange={event => onChange(prev => ({ ...prev, priority: event.target.value as TaskPriority }))}>
              <option value="low">Baixa</option>
              <option value="medium">Média</option>
              <option value="high">Alta</option>
              <option value="urgent">Urgente</option>
            </select>
          </div>
          <div>
            <label className={cx('mb-1.5 block text-xs font-semibold', mutedClass)}>Lembrete</label>
            <select className={crmModernInputClass(isDark)} value={form.reminder_minutes} onChange={event => onChange(prev => ({ ...prev, reminder_minutes: Number(event.target.value) }))}>
              <option value={0}>Sem lembrete</option>
              <option value={15}>15 minutos antes</option>
              <option value={30}>30 minutos antes</option>
              <option value={60}>1 hora antes</option>
              <option value={1440}>1 dia antes</option>
            </select>
          </div>
          <div>
            <label className={cx('mb-1.5 block text-xs font-semibold', mutedClass)}>Tags</label>
            <input
              className={crmModernInputClass(isDark)}
              onChange={event => onChange(prev => ({ ...prev, tags: event.target.value.split(',').map(tag => tag.trim()).filter(Boolean) }))}
              placeholder="retorno, proposta"
              value={form.tags.join(', ')}
            />
          </div>
        </div>

      </div>

      <div className="crm-profile-form__footer">
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" onClick={onCancel} className={crmModernSecondaryButtonClass(isDark)} disabled={actionLoading}>
            Cancelar
          </button>
          <button type="submit" className={crmModernPrimaryButtonClass()} disabled={actionLoading}>
            {actionLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
            {isEditing ? 'Salvar tarefa' : 'Criar tarefa'}
          </button>
        </div>
      </div>
    </form>
  );
}

interface NoteFormProps {
  actionLoading: boolean;
  form: NoteFormData;
  isDark: boolean;
  isEditing: boolean;
  onCancel: () => void;
  onChange: React.Dispatch<React.SetStateAction<NoteFormData>>;
  onSubmit: (event: React.FormEvent) => void;
}

function NoteForm({ actionLoading, form, isDark, isEditing, onCancel, onChange, onSubmit }: NoteFormProps) {
  const mutedClass = 'crm-modern-muted';

  return (
    <form onSubmit={onSubmit} className={crmModernPanelClass(isDark, 'crm-profile-form')}>
      <div className="crm-profile-form__header">
        <div className="crm-profile-form__heading">
          <span className="crm-profile-form__icon" aria-hidden="true">
            <StickyNote className="h-4 w-4" />
          </span>
          <div>
            <p className="text-sm font-semibold">{isEditing ? 'Editar anotação' : 'Nova anotação'}</p>
            <p className={cx('mt-1 text-xs', mutedClass)}>Registre um contexto útil para os próximos atendimentos.</p>
          </div>
        </div>
        <button type="button" onClick={onCancel} className={crmModernIconButtonClass(isDark, 'neutral', 'crm-action-icon')} aria-label="Fechar formulário de anotação" title="Fechar">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="crm-profile-form__body">
        <label className={cx('mb-1.5 block text-xs font-semibold', mutedClass)}>Anotação</label>
        <textarea
          className={crmModernInputClass(isDark, 'min-h-36 resize-y')}
          onChange={event => onChange({ content: event.target.value })}
          placeholder="Registre o contexto do atendimento"
          required
          value={form.content}
        />
        <div className={cx('mt-1.5 text-right text-[10px] tabular-nums', mutedClass)}>{form.content.length} caracteres</div>
      </div>

      <div className="crm-profile-form__footer">
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" onClick={onCancel} className={crmModernSecondaryButtonClass(isDark)} disabled={actionLoading}>
            Cancelar
          </button>
          <button type="submit" className={crmModernPrimaryButtonClass()} disabled={actionLoading || !form.content.trim()}>
            {actionLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
            {isEditing ? 'Salvar anotação' : 'Criar anotação'}
          </button>
        </div>
      </div>
    </form>
  );
}

interface TaskCardProps {
  expanded: boolean;
  isDark: boolean;
  onComplete: () => void;
  onDelete: () => void;
  onEdit: () => void;
  onToggleExpanded: () => void;
  task: ProfileTask;
}

function TaskCard({ expanded, isDark, onComplete, onDelete, onEdit, onToggleExpanded, task }: TaskCardProps) {
  const Icon = getTaskIcon(task.task_type);
  const schedule = formatTaskSchedule(task.scheduled_for);
  const mutedClass = 'crm-modern-muted';

  return (
    <article className="crm-profile-item">
      <div className="flex items-start gap-3">
        <span className={cx('crm-profile-item__icon', schedule.overdue && task.status !== 'completed' && 'is-overdue')}>
          {task.status === 'completed' ? <CheckCircle className="h-4 w-4 text-emerald-600" /> : <Icon className="h-4 w-4" />}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <h3 className={cx('truncate text-sm font-semibold', task.status === 'completed' && 'line-through opacity-60')}>{task.title}</h3>
              <div className={cx('mt-1 flex flex-wrap items-center gap-2 text-xs', mutedClass)}>
                <span className={cx(schedule.overdue && task.status !== 'completed' && 'font-semibold text-red-600')}>{schedule.text}</span>
                <span className={crmModernBadgeClass(isDark, false, 'px-2 py-0.5')}>{statusLabel[task.status]}</span>
                <span className={getPriorityClass(isDark, task.priority)}>
                  {priorityLabel[task.priority]}
                </span>
              </div>
            </div>

            <div className="crm-profile-item__actions">
              {task.status !== 'completed' && (
                <button type="button" onClick={onComplete} className={crmModernIconButtonClass(isDark, 'success', 'crm-action-icon')} title="Concluir tarefa" aria-label={`Concluir ${task.title}`}>
                  <CheckCircle className="h-4 w-4" />
                </button>
              )}
              <button type="button" onClick={onEdit} className={crmModernIconButtonClass(isDark, 'primary', 'crm-action-icon')} title="Editar tarefa" aria-label={`Editar ${task.title}`}>
                <Edit2 className="h-4 w-4" />
              </button>
              <button type="button" onClick={onDelete} className={crmModernIconButtonClass(isDark, 'danger', 'crm-action-icon')} title="Excluir tarefa" aria-label={`Excluir ${task.title}`}>
                <Trash2 className="h-4 w-4" />
              </button>
              <button type="button" onClick={onToggleExpanded} className={crmModernIconButtonClass(isDark, 'neutral', 'crm-action-icon')} title={expanded ? 'Mostrar menos' : 'Mostrar mais'} aria-label={expanded ? `Recolher ${task.title}` : `Expandir ${task.title}`}>
                {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
              </button>
            </div>
          </div>

          {task.tags && task.tags.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {task.tags.map(tag => (
                <span key={tag} className={crmModernBadgeClass(isDark, false, 'px-2 py-0.5')}>
                  <Tag className="h-3 w-3" />
                  {tag}
                </span>
              ))}
            </div>
          )}

          {expanded && (
            <div className="crm-profile-item__details">
              <div>
                <p className={cx('mb-1 text-xs font-semibold', mutedClass)}>Descrição</p>
                <p className={cx('leading-relaxed text-[var(--crm-modern-ink-soft)]', task.description ? '' : 'italic')}>
                  {task.description || 'Sem descrição'}
                </p>
              </div>
              <div>
                <p className={cx('mb-1 text-xs font-semibold', mutedClass)}>Histórico</p>
                <p className="flex items-center gap-1 text-sm text-[var(--crm-modern-ink-soft)]">
                  <User className="h-3.5 w-3.5" />
                  {task.created_by?.name || 'Sistema'}
                </p>
                <p className={cx('mt-1 text-xs', mutedClass)}>{formatDateTime(task.created_at)}</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </article>
  );
}

interface NoteCardProps {
  expanded: boolean;
  isDark: boolean;
  note: ProfileNote;
  onDelete: () => void;
  onEdit: () => void;
  onToggleExpanded: () => void;
}

function NoteCard({ expanded, isDark, note, onDelete, onEdit, onToggleExpanded }: NoteCardProps) {
  const mutedClass = 'crm-modern-muted';
  const canExpand = note.content.length > 180 || note.updated_at !== note.created_at;

  return (
    <article className="crm-profile-item">
      <div className="flex items-start gap-3">
        <span className="crm-profile-item__icon">
          <StickyNote className="h-4 w-4" />
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <p className={cx('crm-profile-item__content whitespace-pre-wrap', !expanded && note.content.length > 180 && 'line-clamp-3')}>
                {note.content}
              </p>
              <div className={cx('mt-3 flex flex-wrap items-center gap-2 text-xs', mutedClass)}>
                <span className="flex items-center gap-1">
                  <User className="h-3 w-3" />
                  {note.created_by?.name || 'Sistema'}
                </span>
                <span>•</span>
                <span title={formatDateTime(note.created_at)}>{formatRelativeDate(note.created_at)}</span>
                {note.updated_at !== note.created_at && <span className="italic">editada</span>}
              </div>
            </div>

            <div className="crm-profile-item__actions">
              <button type="button" onClick={onEdit} className={crmModernIconButtonClass(isDark, 'primary', 'crm-action-icon')} title="Editar anotação" aria-label="Editar anotação">
                <Edit2 className="h-4 w-4" />
              </button>
              <button type="button" onClick={onDelete} className={crmModernIconButtonClass(isDark, 'danger', 'crm-action-icon')} title="Excluir anotação" aria-label="Excluir anotação">
                <Trash2 className="h-4 w-4" />
              </button>
              {canExpand && (
                <button type="button" onClick={onToggleExpanded} className={crmModernIconButtonClass(isDark, 'neutral', 'crm-action-icon')} title={expanded ? 'Mostrar menos' : 'Mostrar mais'} aria-label={expanded ? 'Recolher anotação' : 'Expandir anotação'}>
                  {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                </button>
              )}
            </div>
          </div>

          {expanded && note.updated_at !== note.created_at && (
            <div className="crm-profile-item__edited">
              Última edição: {formatDateTime(note.updated_at)}
            </div>
          )}
        </div>
      </div>
    </article>
  );
}
