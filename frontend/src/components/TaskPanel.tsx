import React, { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import {
  Calendar,
  Clock,
  Phone,
  Mail,
  MessageSquare,
  CheckCircle,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Plus,
  Edit2,
  Trash2,
  User,
  Tag,
  ChevronDown,
  ChevronUp
} from 'lucide-react';
import { format, formatDistanceToNow, isPast, isToday, isTomorrow, parseISO } from 'date-fns';
import { ptBR } from 'date-fns/locale';
import api from '../services/api.ts';
import { AgentiveConfirmModal } from './AgentiveUI.tsx';

interface TaskPanelProps {
  contactId: string;  // Changed to string to accept phone number
  contactName: string;
  contactPhone: string;
  companyId: number;
  onClose?: () => void;
}

interface Task {
  id: number;
  contact_id: number;
  contact_name: string;
  contact_phone: string;
  task_type: 'message' | 'call' | 'email' | 'scheduled_message';
  title: string;
  description?: string;
  scheduled_for: string;
  reminder_minutes: number;
  status: 'pending' | 'in_progress' | 'completed' | 'canceled';
  priority: 'low' | 'medium' | 'high' | 'urgent';
  tags?: string[];
  metadata?: any;
  created_at: string;
  updated_at: string;
  created_by: {
    id: number;
    name: string;
    email: string;
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
  comments_count: number;
}

interface TaskFormData {
  task_type: 'message' | 'call' | 'email' | 'scheduled_message';
  title: string;
  description: string;
  scheduled_for: string;
  reminder_minutes: number;
  priority: 'low' | 'medium' | 'high' | 'urgent';
  assigned_to?: number;
  tags: string[];
  // Campos para mensagem agendada
  message_type?: 'text' | 'image' | 'audio' | 'video';
  message_content?: string;
  message_file?: File | null;
}

const TaskPanel: React.FC<TaskPanelProps> = ({
  contactId,
  contactName,
  contactPhone,
  companyId,
  onClose
}) => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingTask, setEditingTask] = useState<Task | null>(null);
  const [expandedTasks, setExpandedTasks] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState<'all' | 'pending' | 'completed'>('all');
  const [taskToDelete, setTaskToDelete] = useState<number | null>(null);

  // Get user timezone
  const userTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;

  const [formData, setFormData] = useState<TaskFormData>({
    task_type: 'message',
    title: '',
    description: '',
    scheduled_for: format(new Date(), "yyyy-MM-dd'T'HH:mm"),
    reminder_minutes: 15,
    priority: 'medium',
    tags: [],
    // Campos para mensagem agendada
    message_type: 'text',
    message_content: '',
    message_file: null
  });

  const fetchTasks = useCallback(async () => {
    try {
      setLoading(true);
      const response = await api.get(`/api/contacts/${contactId}/tasks`);
      setTasks(response.data);
    } catch (error) {
      console.error('Error fetching tasks:', error);
    } finally {
      setLoading(false);
    }
  }, [contactId]);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  // Handle escape key to close modal and prevent body scroll
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && showForm) {
        setShowForm(false);
        setEditingTask(null);
        resetForm();
      }
    };

    if (showForm) {
      document.addEventListener('keydown', handleEscape);
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = 'unset';
    }

    return () => {
      document.removeEventListener('keydown', handleEscape);
      document.body.style.overflow = 'unset';
    };
  }, [showForm]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    try {
      // Add timezone header
      const config = {
        headers: {
          'X-Timezone': userTimeZone
        }
      };

      if (editingTask) {
        await api.put(`/api/tasks/${editingTask.id}`, formData, config);
      } else {
        await api.post(`/api/contacts/${contactId}/tasks`, formData, config);
      }

      fetchTasks();
      setShowForm(false);
      setEditingTask(null);
      resetForm();
    } catch (error) {
      console.error('Error saving task:', error);
    }
  };

  const handleComplete = async (taskId: number) => {
    try {
      await api.post(`/api/tasks/${taskId}/complete`);
      fetchTasks();
    } catch (error) {
      console.error('Error completing task:', error);
    }
  };

  const handleDelete = async (taskId: number) => {
    setTaskToDelete(taskId);
  };

  const confirmDelete = async () => {
    if (!taskToDelete) return;

    try {
      await api.delete(`/api/tasks/${taskToDelete}`);
      fetchTasks();
    } catch (error) {
      console.error('Error deleting task:', error);
    } finally {
      setTaskToDelete(null);
    }
  };

  const resetForm = () => {
    setFormData({
      task_type: 'message',
      title: '',
      description: '',
      scheduled_for: format(new Date(), "yyyy-MM-dd'T'HH:mm"),
      reminder_minutes: 15,
      priority: 'medium',
      tags: [],
      // Campos para mensagem agendada
      message_type: 'text',
      message_content: '',
      message_file: null
    });
  };

  const getTaskIcon = (type: string) => {
    switch (type) {
      case 'message':
        return <MessageSquare className="h-4 w-4" />;
      case 'call':
        return <Phone className="h-4 w-4" />;
      case 'email':
        return <Mail className="h-4 w-4" />;
      default:
        return <Calendar className="h-4 w-4" />;
    }
  };

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case 'urgent':
        return 'text-red-700 bg-red-50 border-red-200 hover:bg-red-100 transition-colors';
      case 'high':
        return 'text-orange-700 bg-orange-50 border-orange-200 hover:bg-orange-100 transition-colors';
      case 'medium':
        return 'text-amber-700 bg-amber-50 border-amber-200 hover:bg-amber-100 transition-colors';
      case 'low':
        return 'text-slate-700 bg-slate-50 border-slate-200 hover:bg-slate-100 transition-colors';
      default:
        return 'text-slate-700 bg-slate-50 border-slate-200 hover:bg-slate-100 transition-colors';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="h-4 w-4 text-green-600" />;
      case 'canceled':
        return <XCircle className="h-4 w-4 text-red-600" />;
      case 'in_progress':
        return <AlertCircle className="h-4 w-4 text-yellow-600" />;
      default:
        return <Clock className="h-4 w-4 text-gray-400" />;
    }
  };

  const formatTaskDate = (dateString: string) => {
    // Simply parse the ISO string - the backend already handles timezone correctly
    const date = parseISO(dateString);
    const isOverdue = isPast(date) && !isToday(date);

    if (isOverdue) {
      return {
        text: `Atrasada há ${formatDistanceToNow(date, { locale: ptBR })}`,
        class: 'text-red-700 font-medium',
        isOverdue: true
      };
    } else if (isToday(date)) {
      return {
        text: `Hoje às ${format(date, 'HH:mm')}`,
        class: 'text-blue-700 font-medium',
        isOverdue: false
      };
    } else if (isTomorrow(date)) {
      return {
        text: `Amanhã às ${format(date, 'HH:mm')}`,
        class: 'text-emerald-700 font-medium',
        isOverdue: false
      };
    } else {
      return {
        text: format(date, "dd 'de' MMMM 'às' HH:mm", { locale: ptBR }),
        class: 'text-slate-600',
        isOverdue: false
      };
    }
  };

  const filteredTasks = tasks.filter(task => {
    if (filter === 'all') return true;
    if (filter === 'pending') return task.status === 'pending' || task.status === 'in_progress';
    if (filter === 'completed') return task.status === 'completed';
    return true;
  });

  return (
    <div className="bg-white rounded-2xl shadow-flat-lg border border-card-border p-4 sm:p-6 max-w-4xl mx-auto backdrop-blur-sm">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:justify-between sm:items-start gap-4 mb-6">
        <div className="flex-1">
          <h2 className="text-2xl font-bold text-slate-800 mb-1">Tarefas</h2>
          <p className="text-sm text-slate-600">
            {contactName} • {contactPhone}
          </p>
        </div>

        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-2 px-6 py-2.5 bg-primary-600 hover:bg-primary-700 text-white rounded-xl font-medium transition-all duration-200 hover:scale-[1.02] active:scale-[0.98] shadow-lg shadow-primary-600/20"
        >
          <Plus className="h-4 w-4" />
          Nova Tarefa
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 mb-6">
        <button
          onClick={() => setFilter('all')}
          className={`px-3 py-2 sm:px-4 rounded-lg text-xs sm:text-sm font-medium transition-all duration-200 min-h-[44px] ${filter === 'all'
              ? 'bg-slate-800 text-white shadow-sm'
              : 'bg-slate-100 text-slate-600 hover:bg-slate-200 hover:text-slate-800'
            }`}
        >
          Todas ({tasks.length})
        </button>
        <button
          onClick={() => setFilter('pending')}
          className={`px-3 py-2 sm:px-4 rounded-lg text-xs sm:text-sm font-medium transition-all duration-200 min-h-[44px] ${filter === 'pending'
              ? 'bg-slate-800 text-white shadow-sm'
              : 'bg-slate-100 text-slate-600 hover:bg-slate-200 hover:text-slate-800'
            }`}
        >
          Pendentes ({tasks.filter(t => t.status === 'pending' || t.status === 'in_progress').length})
        </button>
        <button
          onClick={() => setFilter('completed')}
          className={`px-3 py-2 sm:px-4 rounded-lg text-xs sm:text-sm font-medium transition-all duration-200 min-h-[44px] ${filter === 'completed'
              ? 'bg-slate-800 text-white shadow-sm'
              : 'bg-slate-100 text-slate-600 hover:bg-slate-200 hover:text-slate-800'
            }`}
        >
          Concluídas ({tasks.filter(t => t.status === 'completed').length})
        </button>
      </div>

      {/* Task List */}
      {loading ? (
        <div className="text-center py-12">
          <div className="relative w-8 h-8 mx-auto">
            <div className="absolute inset-0 rounded-full border-2 border-slate-200"></div>
            <div className="absolute inset-0 rounded-full border-2 border-primary-600 border-t-transparent animate-spin"></div>
          </div>
          <p className="text-sm text-slate-500 mt-3">Carregando tarefas...</p>
        </div>
      ) : filteredTasks.length === 0 ? (
        <div className="text-center py-12">
          <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-slate-100 flex items-center justify-center">
            <Calendar className="h-8 w-8 text-slate-400" />
          </div>
          <p className="text-slate-600 font-medium mb-1">Nenhuma tarefa encontrada</p>
          <p className="text-sm text-slate-500">Crie uma nova tarefa para começar</p>
        </div>
      ) : (
        <div className="space-y-3 sm:space-y-4">
          {filteredTasks.map(task => {
            const isExpanded = expandedTasks.has(task.id);
            const dateFormat = formatTaskDate(task.scheduled_for);

            return (
              <div
                key={task.id}
                className={`border rounded-xl p-3 sm:p-4 transition-all duration-200 hover:shadow-flat-md ${task.status === 'completed'
                    ? 'bg-slate-50 border-slate-200'
                    : 'bg-white border-slate-300 hover:border-slate-400 hover:bg-slate-50/30'
                  }`}
              >
                <div className="flex items-start gap-3">
                  {/* Status Icon */}
                  <div className={`mt-1 p-2 rounded-lg bg-white border shadow-sm transition-all duration-200 hover:scale-110 ${dateFormat.isOverdue && task.status !== 'completed'
                      ? 'border-red-200 bg-red-50 animate-pulse'
                      : 'border-slate-200'
                    }`}>
                    {getStatusIcon(task.status)}
                  </div>

                  {/* Main Content */}
                  <div className="flex-1">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex flex-col sm:flex-row sm:items-center gap-2 mb-2">
                          <div className="flex items-center gap-2">
                            <div className="p-1.5 rounded-lg bg-slate-100 text-slate-600 group-hover:bg-slate-200 transition-colors duration-200">
                              {getTaskIcon(task.task_type)}
                            </div>
                            <h3 className={`font-semibold text-sm sm:text-base ${task.status === 'completed' ? 'line-through text-slate-500' : 'text-slate-900'
                              }`}>
                              {task.title}
                            </h3>
                          </div>
                          <span className={`text-xs px-2.5 py-1 rounded-full font-medium border transition-all duration-200 hover:scale-105 self-start sm:self-auto ${getPriorityColor(task.priority)}`}>
                            {task.priority === 'urgent' ? 'Urgente' :
                              task.priority === 'high' ? 'Alta' :
                                task.priority === 'medium' ? 'Média' : 'Baixa'}
                          </span>
                        </div>

                        <div className="flex items-center gap-2 mb-3">
                          <p className={`text-sm ${dateFormat.class}`}>
                            {dateFormat.text}
                          </p>
                          {dateFormat.isOverdue && task.status !== 'completed' && (
                            <span className="px-2 py-1 bg-red-100 text-red-700 text-xs rounded-full font-medium animate-pulse">
                              Atrasada
                            </span>
                          )}
                        </div>

                        {task.assigned_to && (
                          <div className="flex items-center gap-2 text-sm text-slate-600 mb-3 p-2 bg-slate-50 rounded-lg">
                            <div className="w-6 h-6 rounded-full bg-primary-100 flex items-center justify-center">
                              <User className="h-3.5 w-3.5 text-primary-600" />
                            </div>
                            <span className="font-medium">Atribuída a {task.assigned_to.name}</span>
                          </div>
                        )}

                        {task.tags && task.tags.length > 0 && (
                          <div className="flex flex-wrap gap-1.5 mb-3">
                            {task.tags.map(tag => (
                              <span key={tag} className="text-xs bg-primary-50 text-primary-700 px-2.5 py-1 rounded-full font-medium border border-primary-100 hover:bg-primary-100 transition-colors duration-200">
                                #{tag}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>

                      {/* Actions */}
                      <div className="flex items-center gap-1 flex-wrap">
                        {task.status !== 'completed' && (
                          <button
                            onClick={() => handleComplete(task.id)}
                            className="p-2 rounded-lg hover:bg-green-50 text-green-600 hover:text-green-700 transition-all duration-200 hover:scale-110 min-h-[44px] min-w-[44px] flex items-center justify-center"
                            title="Marcar como concluída"
                          >
                            <CheckCircle className="h-4 w-4" />
                          </button>
                        )}

                        <button
                          onClick={() => {
                            setEditingTask(task);
                            setFormData({
                              task_type: task.task_type,
                              title: task.title,
                              description: task.description || '',
                              scheduled_for: format(parseISO(task.scheduled_for), "yyyy-MM-dd'T'HH:mm"),
                              reminder_minutes: task.reminder_minutes,
                              priority: task.priority,
                              assigned_to: task.assigned_to?.id,
                              tags: task.tags || []
                            });
                            setShowForm(true);
                          }}
                          className="p-2 rounded-lg hover:bg-slate-100 text-slate-600 hover:text-slate-700 transition-all duration-200 hover:scale-110 min-h-[44px] min-w-[44px] flex items-center justify-center"
                          title="Editar tarefa"
                        >
                          <Edit2 className="h-4 w-4" />
                        </button>

                        <button
                          onClick={() => handleDelete(task.id)}
                          className="p-2 rounded-lg hover:bg-red-50 text-red-600 hover:text-red-700 transition-all duration-200 hover:scale-110 min-h-[44px] min-w-[44px] flex items-center justify-center"
                          title="Excluir tarefa"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>

                        <button
                          onClick={() => {
                            if (isExpanded) {
                              setExpandedTasks(prev => {
                                const next = new Set(prev);
                                next.delete(task.id);
                                return next;
                              });
                            } else {
                              setExpandedTasks(prev => new Set(prev).add(task.id));
                            }
                          }}
                          className="p-2 rounded-lg hover:bg-slate-100 text-slate-600 hover:text-slate-700 transition-all duration-200 hover:scale-110 min-h-[44px] min-w-[44px] flex items-center justify-center"
                        >
                          {isExpanded ? (
                            <ChevronUp className="h-4 w-4" />
                          ) : (
                            <ChevronDown className="h-4 w-4" />
                          )}
                        </button>
                      </div>
                    </div>

                    {/* Expanded Content */}
                    {isExpanded && (
                      <div className="mt-4 pt-4 border-t border-slate-200 animate-in slide-in-from-top-1 fade-in duration-200">
                        {task.description && (
                          <div className="mb-4 p-3 bg-slate-50 rounded-lg">
                            <p className="text-sm text-slate-700 leading-relaxed">{task.description}</p>
                          </div>
                        )}

                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                          <div className="p-3 bg-slate-50 rounded-lg">
                            <div className="flex items-center gap-2 text-sm font-medium text-slate-700 mb-1">
                              <div className="w-4 h-4 rounded-full bg-primary-100 flex items-center justify-center">
                                <Plus className="h-2.5 w-2.5 text-primary-600" />
                              </div>
                              Criada por:
                            </div>
                            <p className="text-sm text-slate-900 font-medium">{task.created_by.name}</p>
                            <p className="text-xs text-slate-500">
                              {format(parseISO(task.created_at), "dd 'de' MMMM 'às' HH:mm", { locale: ptBR })}
                            </p>
                          </div>

                          {task.completed_at && task.completed_by && (
                            <div className="p-3 bg-green-50 rounded-lg">
                              <div className="flex items-center gap-2 text-sm font-medium text-green-700 mb-1">
                                <div className="w-4 h-4 rounded-full bg-green-100 flex items-center justify-center">
                                  <CheckCircle className="h-2.5 w-2.5 text-green-600" />
                                </div>
                                Concluída por:
                              </div>
                              <p className="text-sm text-slate-900 font-medium">{task.completed_by.name}</p>
                              <p className="text-xs text-slate-500">
                                {format(parseISO(task.completed_at), "dd 'de' MMMM 'às' HH:mm", { locale: ptBR })}
                              </p>
                            </div>
                          )}
                        </div>

                        {task.comments_count > 0 && (
                          <div className="mt-4 flex items-center gap-2 p-2 bg-primary-50 rounded-lg">
                            <MessageSquare className="h-4 w-4 text-primary-600" />
                            <span className="text-sm text-primary-700 font-medium">
                              {task.comments_count} comentário{task.comments_count > 1 ? 's' : ''}
                            </span>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Modal rendered outside the sidebar using React Portal */}
      {showForm && createPortal(
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center p-3 sm:p-4 sm:p-6"
          onClick={(e) => {
            if (e.target === e.currentTarget) {
              setShowForm(false);
              setEditingTask(null);
              resetForm();
            }
          }}
        >
          {/* Overlay com backdrop blur */}
          <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm transition-opacity" />

          {/* Modal Card */}
          <div className="relative w-full max-w-2xl bg-white rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh] animate-in fade-in zoom-in-95 duration-200 m-2 sm:m-0">
            {/* Header */}
            <div className="px-4 sm:px-6 py-4 border-b border-slate-100 flex items-center justify-between bg-white sticky top-0 z-10">
              <div className="flex-1 min-w-0">
                <h2 className="text-lg sm:text-xl font-bold text-slate-800 truncate">
                  {editingTask ? 'Editar Tarefa' : 'Nova Tarefa'}
                </h2>
                <p className="text-xs text-slate-500 mt-0.5 hidden sm:block">
                  {editingTask ? 'Atualize os detalhes da tarefa' : 'Defina os detalhes da atividade para o lead'}
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setShowForm(false);
                  setEditingTask(null);
                  resetForm();
                }}
                className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-full transition-all duration-200 hover:scale-110 min-h-[44px] min-w-[44px] flex items-center justify-center"
                title="Fechar"
              >
                <XCircle className="h-5 w-5" />
              </button>
            </div>

            {/* Scrollable Content */}
            <div className="overflow-y-auto p-4 sm:p-6 space-y-4 sm:space-y-6 custom-scrollbar">
              <form id="task-form" onSubmit={handleSubmit} className="space-y-4 sm:space-y-6">
                {/* Seção de Tipo de Tarefa - Compacta */}
                <section>
                  <label className="text-sm font-semibold text-slate-700 mb-3 block">Tipo de Tarefa</label>
                  <div className="flex flex-wrap gap-2.5">
                    {[
                      { id: 'message', label: 'Mensagem', icon: MessageSquare, color: 'text-blue-600 bg-blue-50 border-blue-200 ring-blue-500' },
                      { id: 'call', label: 'Ligação', icon: Phone, color: 'text-green-600 bg-green-50 border-green-200 ring-green-500' },
                      { id: 'email', label: 'Email', icon: Mail, color: 'text-orange-600 bg-orange-50 border-orange-200 ring-orange-500' },
                      { id: 'scheduled_message', label: 'Agendar Msg', icon: MessageSquare, color: 'text-indigo-600 bg-indigo-50 border-indigo-200 ring-indigo-500', special: true }
                    ].map((type) => {
                      const Icon = type.icon;
                      const isSelected = formData.task_type === type.id;

                      return (
                        <button
                          key={type.id}
                          type="button"
                          onClick={() => setFormData({ ...formData, task_type: type.id as any })}
                          className={`
                        group relative flex items-center gap-2 px-3.5 py-2 rounded-full border transition-all duration-200
                        ${isSelected
                              ? `${type.color} ring-1 shadow-sm font-medium pr-4`
                              : 'bg-white border-slate-200 text-slate-600 hover:border-slate-300 hover:bg-slate-50'
                            }
                        hover:scale-105 active:scale-[0.98]
                      `}
                        >
                          <Icon size={16} className={`${isSelected ? 'stroke-[2.5px]' : 'stroke-2 text-slate-400 group-hover:text-slate-500'}`} />
                          <span className="text-xs leading-none">{type.label}</span>

                          {/* Indicador sutil para itens especiais (Agendar Msg) */}
                          {type.special && !isSelected && (
                            <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-indigo-500 ring-2 ring-white"></span>
                          )}
                        </button>
                      );
                    })}
                  </div>

                  {/* Explicação condicional para Agendar Mensagem */}
                  {formData.task_type === 'scheduled_message' && (
                    <div className="mt-3 flex items-start gap-2 p-2.5 bg-indigo-50 border border-indigo-100 rounded-lg text-xs text-indigo-800 animate-in fade-in zoom-in-95 duration-200">
                      <MessageSquare size={14} className="mt-0.5 shrink-0" />
                      <p>O sistema enviará a mensagem automaticamente na data e hora agendada.</p>
                    </div>
                  )}
                </section>

                {/* Título */}
                <div className="space-y-1.5">
                  <label htmlFor="title" className="text-sm font-medium text-slate-700">Título</label>
                  <input
                    id="title"
                    type="text"
                    value={formData.title}
                    onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                    placeholder="Ex: Retorno sobre proposta..."
                    className="w-full px-4 py-3 border border-slate-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all placeholder:text-slate-400 hover:border-slate-400"
                    required
                  />
                </div>

                {/* Descrição */}
                <div className="space-y-1.5">
                  <label htmlFor="description" className="text-sm font-medium text-slate-700 flex justify-between">
                    Descrição
                    <span className="text-slate-400 font-normal text-xs">Opcional</span>
                  </label>
                  <textarea
                    id="description"
                    rows={3}
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    placeholder="Adicione detalhes ou contexto..."
                    className="w-full px-4 py-3 border border-slate-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all resize-none placeholder:text-slate-400 hover:border-slate-400"
                  />
                </div>

                {/* Grid Data, Hora e Prioridade */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-5">

                  {/* Data e Hora */}
                  <div className="space-y-1.5">
                    <label className="text-sm font-medium text-slate-700 flex items-center gap-1.5">
                      <Clock size={14} /> Data e Hora
                    </label>
                    <input
                      type="datetime-local"
                      value={formData.scheduled_for}
                      onChange={(e) => setFormData({ ...formData, scheduled_for: e.target.value })}
                      className="w-full px-4 py-3 border border-slate-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all text-slate-600 hover:border-slate-400"
                      required
                    />
                  </div>

                  {/* Prioridade */}
                  <div className="space-y-1.5">
                    <label className="text-sm font-medium text-slate-700 flex items-center gap-1.5">
                      <AlertCircle size={14} /> Prioridade
                    </label>
                    <div className="flex bg-slate-100 p-1 rounded-lg">
                      {[
                        { id: 'low', label: 'Baixa' },
                        { id: 'medium', label: 'Média' },
                        { id: 'high', label: 'Alta' },
                        { id: 'urgent', label: 'Urgente' }
                      ].map((p) => (
                        <button
                          key={p.id}
                          type="button"
                          onClick={() => setFormData({ ...formData, priority: p.id as any })}
                          className={`flex-1 text-xs font-medium py-1.5 rounded-md transition-all ${formData.priority === p.id
                              ? 'bg-white text-slate-800 shadow-sm ring-1 ring-black/5'
                              : 'text-slate-500 hover:text-slate-700'
                            }`}
                        >
                          {p.label}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Lembrete e Tags */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                  <div className="space-y-1.5">
                    <label className="text-sm font-medium text-slate-700">Lembrete</label>
                    <select
                      className="w-full px-4 py-3 border border-slate-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 bg-white text-sm text-slate-600 hover:border-slate-400"
                      value={formData.reminder_minutes}
                      onChange={(e) => setFormData({ ...formData, reminder_minutes: parseInt(e.target.value) })}
                    >
                      <option value="0">Sem lembrete</option>
                      <option value="15">15 minutos antes</option>
                      <option value="30">30 minutos antes</option>
                      <option value="60">1 hora antes</option>
                      <option value="1440">1 dia antes</option>
                    </select>
                  </div>

                  <div className="space-y-1.5">
                    <label className="text-sm font-medium text-slate-700 flex items-center gap-1.5">
                      <Tag size={14} /> Tags
                    </label>
                    <input
                      type="text"
                      value={formData.tags.join(', ')}
                      onChange={(e) => setFormData({
                        ...formData,
                        tags: e.target.value.split(',').map(t => t.trim()).filter(t => t)
                      })}
                      placeholder="Ex: quente, retorno..."
                      className="w-full px-4 py-3 border border-slate-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 text-sm hover:border-slate-400"
                    />
                  </div>
                </div>

                {/* Campos específicos para mensagem agendada */}
                {formData.task_type === 'scheduled_message' && (
                  <div className="p-4 border border-indigo-200 rounded-lg bg-indigo-50 space-y-4">
                    <h4 className="font-medium text-indigo-800 flex items-center gap-2">
                      <MessageSquare size={16} />
                      Configuração da Mensagem
                    </h4>

                    {/* Conteúdo da mensagem */}
                    <div className="space-y-2">
                      <label className="text-sm font-medium text-slate-700">Conteúdo da Mensagem</label>
                      <textarea
                        value={formData.message_content || ''}
                        onChange={(e) => setFormData({ ...formData, message_content: e.target.value })}
                        className="w-full px-4 py-3 border border-slate-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 resize-none placeholder:text-slate-400"
                        rows={3}
                        placeholder="Digite a mensagem que será enviada..."
                        required
                      />
                    </div>

                    {/* Preview da mensagem */}
                    {formData.message_content && (
                      <div className="p-3 bg-white rounded-lg border border-slate-200">
                        <p className="text-xs text-slate-500 mb-1 font-medium">Preview:</p>
                        <p className="text-sm text-slate-700 leading-relaxed">{formData.message_content}</p>
                      </div>
                    )}
                  </div>
                )}

              </form>
            </div>

            {/* Footer */}
            <div className="px-4 sm:px-6 py-4 bg-slate-50 border-t border-slate-100 flex items-center justify-between sticky bottom-0 gap-2">
              <button
                type="button"
                onClick={() => {
                  setShowForm(false);
                  setEditingTask(null);
                  resetForm();
                }}
                className="px-4 py-2.5 text-sm font-medium text-slate-600 hover:text-slate-800 hover:bg-slate-200/50 rounded-lg transition-colors min-h-[44px]"
              >
                Cancelar
              </button>
              <button
                type="submit"
                form="task-form"
                className="px-4 sm:px-6 py-2.5 bg-gradient-to-r from-primary-600 to-primary-700 hover:from-primary-700 hover:to-primary-800 text-white text-sm font-medium rounded-lg shadow-lg shadow-primary-500/20 hover:shadow-primary-500/30 transition-all duration-200 transform hover:-translate-y-0.5 active:scale-95 flex items-center gap-2 min-h-[44px]"
              >
                <CheckCircle2 size={16} />
                <span className="hidden sm:inline">
                  {formData.task_type === 'scheduled_message' ? 'Agendar' : (editingTask ? 'Salvar' : 'Criar Tarefa')}
                </span>
                <span className="sm:hidden">
                  {formData.task_type === 'scheduled_message' ? 'Agendar' : (editingTask ? 'Salvar' : 'Criar')}
                </span>
              </button>
            </div>
          </div>

          <style>{`
          .custom-scrollbar::-webkit-scrollbar {
            width: 6px;
          }
          .custom-scrollbar::-webkit-scrollbar-track {
            background: transparent;
          }
          .custom-scrollbar::-webkit-scrollbar-thumb {
            background-color: #cbd5e1;
            border-radius: 20px;
          }
        `}</style>
        </div>,
        document.body
      )}

      <AgentiveConfirmModal
        isOpen={taskToDelete !== null}
        title="Excluir tarefa?"
        message="Esta tarefa sera removida do historico operacional do contato."
        confirmText="Excluir tarefa"
        cancelText="Cancelar"
        variant="danger"
        onClose={() => setTaskToDelete(null)}
        onConfirm={confirmDelete}
      />
    </div>
  );
};

export default TaskPanel;
