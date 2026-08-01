import React, { useState, useEffect } from 'react';
import {
  Calendar,
  Clock,
  Phone,
  Mail,
  MessageSquare,
  CheckCircle,
  XCircle,
  AlertCircle,
  Plus,
  ArrowLeft,
  Filter,
  ChevronRight,
  Trash2,
  Edit2
} from 'lucide-react';
import { format, formatDistanceToNow, isPast, isToday, isTomorrow, parseISO } from 'date-fns';
import { ptBR } from 'date-fns/locale';
import api from '../services/api.ts';
import { AgentiveConfirmModal } from './AgentiveUI.tsx';

interface TaskPanelMobileProps {
  contactId: string;
  contactName: string;
  contactPhone: string;
  companyId: number;
  onClose: () => void;
}

interface Task {
  id: number;
  contact_id: number;
  contact_name: string;
  contact_phone: string;
  task_type: 'message' | 'call' | 'email' | 'custom';
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
  task_type: 'message' | 'call' | 'email' | 'custom';
  title: string;
  description: string;
  scheduled_for: string;
  reminder_minutes: number;
  priority: 'low' | 'medium' | 'high' | 'urgent';
  assigned_to?: number;
  tags: string[];
}

const TaskPanelMobile: React.FC<TaskPanelMobileProps> = ({
  contactId,
  contactName,
  contactPhone,
  companyId,
  onClose
}) => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [currentView, setCurrentView] = useState<'list' | 'form' | 'detail'>('list');
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [editingTask, setEditingTask] = useState<Task | null>(null);
  const [filter, setFilter] = useState<'all' | 'pending' | 'completed'>('all');
  const [taskToDelete, setTaskToDelete] = useState<number | null>(null);

  const userTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;

  const [formData, setFormData] = useState<TaskFormData>({
    task_type: 'message',
    title: '',
    description: '',
    scheduled_for: format(new Date(), "yyyy-MM-dd'T'HH:mm"),
    reminder_minutes: 15,
    priority: 'medium',
    tags: []
  });

  useEffect(() => {
    fetchTasks();
  }, [contactId]);

  const fetchTasks = async () => {
    try {
      setLoading(true);
      const response = await api.get(`/api/contacts/${contactId}/tasks`);
      setTasks(response.data);
    } catch (error) {
      console.error('Error fetching tasks:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    try {
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
      setCurrentView('list');
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
      if (selectedTask?.id === taskToDelete) {
        setSelectedTask(null);
        setCurrentView('list');
      }
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
      tags: []
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
        return 'text-red-600 bg-red-50';
      case 'high':
        return 'text-orange-600 bg-orange-50';
      case 'medium':
        return 'text-yellow-600 bg-yellow-50';
      case 'low':
        return 'text-gray-600 bg-gray-50';
      default:
        return 'text-gray-600 bg-gray-50';
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
    const date = parseISO(dateString);

    if (isPast(date) && !isToday(date)) {
      return {
        text: `Atrasada há ${formatDistanceToNow(date, { locale: ptBR })}`,
        class: 'text-red-600'
      };
    } else if (isToday(date)) {
      return {
        text: `Hoje às ${format(date, 'HH:mm')}`,
        class: 'text-blue-600'
      };
    } else if (isTomorrow(date)) {
      return {
        text: `Amanhã às ${format(date, 'HH:mm')}`,
        class: 'text-green-600'
      };
    } else {
      return {
        text: format(date, "dd 'de' MMMM 'às' HH:mm", { locale: ptBR }),
        class: 'text-gray-600'
      };
    }
  };

  const filteredTasks = tasks.filter(task => {
    if (filter === 'all') return true;
    if (filter === 'pending') return task.status === 'pending' || task.status === 'in_progress';
    if (filter === 'completed') return task.status === 'completed';
    return true;
  });

  // View: Lista de tarefas
  const renderTaskList = () => (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="bg-white border-b px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={onClose} className="p-1 -ml-1">
            <ArrowLeft className="h-5 w-5" />
          </button>
          <div>
            <h2 className="font-semibold">Tarefas</h2>
            <p className="text-xs text-gray-600">{contactName}</p>
          </div>
        </div>
        <button
          onClick={() => {
            resetForm();
            setEditingTask(null);
            setCurrentView('form');
          }}
          className="p-2 bg-blue-600 text-white rounded-lg"
        >
          <Plus className="h-5 w-5" />
        </button>
      </div>

      {/* Filtros */}
      <div className="bg-white border-b px-4 py-2 flex gap-2">
        <button
          onClick={() => setFilter('all')}
          className={`flex-1 py-1.5 text-sm rounded-lg ${
            filter === 'all' ? 'bg-gray-800 text-white' : 'bg-gray-100'
          }`}
        >
          Todas ({tasks.length})
        </button>
        <button
          onClick={() => setFilter('pending')}
          className={`flex-1 py-1.5 text-sm rounded-lg ${
            filter === 'pending' ? 'bg-gray-800 text-white' : 'bg-gray-100'
          }`}
        >
          Pendentes ({tasks.filter(t => t.status === 'pending' || t.status === 'in_progress').length})
        </button>
        <button
          onClick={() => setFilter('completed')}
          className={`flex-1 py-1.5 text-sm rounded-lg ${
            filter === 'completed' ? 'bg-gray-800 text-white' : 'bg-gray-100'
          }`}
        >
          Concluídas ({tasks.filter(t => t.status === 'completed').length})
        </button>
      </div>

      {/* Lista */}
      <div className="flex-1 overflow-y-auto bg-gray-50">
        {loading ? (
          <div className="flex items-center justify-center h-32">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900"></div>
          </div>
        ) : filteredTasks.length === 0 ? (
          <div className="text-center py-12">
            <Calendar className="h-12 w-12 mx-auto mb-2 text-gray-300" />
            <p className="text-gray-500">Nenhuma tarefa encontrada</p>
          </div>
        ) : (
          <div className="space-y-2 p-4">
            {filteredTasks.map(task => {
              const dateFormat = formatTaskDate(task.scheduled_for);

              return (
                <button
                  key={task.id}
                  onClick={() => {
                    setSelectedTask(task);
                    setCurrentView('detail');
                  }}
                  className={`w-full bg-white rounded-lg p-4 text-left ${
                    task.status === 'completed' ? 'opacity-75' : ''
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <div className="mt-1">{getStatusIcon(task.status)}</div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        {getTaskIcon(task.task_type)}
                        <h3 className={`font-medium text-sm ${
                          task.status === 'completed' ? 'line-through text-gray-500' : ''
                        }`}>
                          {task.title}
                        </h3>
                      </div>
                      <p className={`text-xs ${dateFormat.class}`}>
                        {dateFormat.text}
                      </p>
                      <div className="flex items-center gap-2 mt-2">
                        <span className={`text-xs px-2 py-0.5 rounded-full ${getPriorityColor(task.priority)}`}>
                          {task.priority === 'urgent' ? 'Urgente' :
                           task.priority === 'high' ? 'Alta' :
                           task.priority === 'medium' ? 'Média' : 'Baixa'}
                        </span>
                        {task.tags && task.tags.map(tag => (
                          <span key={tag} className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">
                            #{tag}
                          </span>
                        ))}
                      </div>
                    </div>
                    <ChevronRight className="h-4 w-4 text-gray-400 flex-shrink-0" />
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );

  // View: Formulário
  const renderTaskForm = () => (
    <div className="flex flex-col h-full bg-white">
      {/* Header */}
      <div className="border-b px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={() => {
              setCurrentView('list');
              setEditingTask(null);
              resetForm();
            }}
            className="p-1 -ml-1"
          >
            <ArrowLeft className="h-5 w-5" />
          </button>
          <h2 className="font-semibold">
            {editingTask ? 'Editar Tarefa' : 'Nova Tarefa'}
          </h2>
        </div>
        <button
          onClick={handleSubmit}
          className="px-4 py-1.5 bg-blue-600 text-white rounded-lg text-sm font-medium"
        >
          {editingTask ? 'Salvar' : 'Criar'}
        </button>
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto">
        <div className="p-4 space-y-4">
          {/* Tipo */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Tipo de Tarefa
            </label>
            <div className="grid grid-cols-4 gap-2">
              {[
                { value: 'message', icon: MessageSquare, label: 'Msg' },
                { value: 'call', icon: Phone, label: 'Ligar' },
                { value: 'email', icon: Mail, label: 'Email' },
                { value: 'custom', icon: Calendar, label: 'Outra' }
              ].map(({ value, icon: Icon, label }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setFormData({ ...formData, task_type: value as any })}
                  className={`p-3 rounded-lg border text-xs ${
                    formData.task_type === value
                      ? 'border-blue-500 bg-blue-50 text-blue-600'
                      : 'border-gray-200'
                  }`}
                >
                  <Icon className="h-4 w-4 mx-auto mb-1" />
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Título */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Título
            </label>
            <input
              type="text"
              value={formData.title}
              onChange={(e) => setFormData({ ...formData, title: e.target.value })}
              className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Ex: Ligar para agendar retorno"
              required
            />
          </div>

          {/* Descrição */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Descrição
            </label>
            <textarea
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              rows={3}
              placeholder="Detalhes da tarefa..."
            />
          </div>

          {/* Data e Hora */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Data e Hora
            </label>
            <input
              type="datetime-local"
              value={formData.scheduled_for}
              onChange={(e) => setFormData({ ...formData, scheduled_for: e.target.value })}
              className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              required
            />
          </div>

          {/* Prioridade */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Prioridade
            </label>
            <select
              value={formData.priority}
              onChange={(e) => setFormData({ ...formData, priority: e.target.value as any })}
              className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="low">Baixa</option>
              <option value="medium">Média</option>
              <option value="high">Alta</option>
              <option value="urgent">Urgente</option>
            </select>
          </div>

          {/* Lembrete */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Lembrete
            </label>
            <select
              value={formData.reminder_minutes}
              onChange={(e) => setFormData({ ...formData, reminder_minutes: parseInt(e.target.value) })}
              className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="0">Sem lembrete</option>
              <option value="15">15 minutos antes</option>
              <option value="30">30 minutos antes</option>
              <option value="60">1 hora antes</option>
              <option value="1440">1 dia antes</option>
            </select>
          </div>

          {/* Tags */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Tags
            </label>
            <input
              type="text"
              value={formData.tags.join(', ')}
              onChange={(e) => setFormData({
                ...formData,
                tags: e.target.value.split(',').map(t => t.trim()).filter(t => t)
              })}
              placeholder="Ex: orçamento, retorno"
              className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>
      </form>
    </div>
  );

  // View: Detalhes da tarefa
  const renderTaskDetail = () => {
    if (!selectedTask) return null;

    const dateFormat = formatTaskDate(selectedTask.scheduled_for);

    return (
      <div className="flex flex-col h-full bg-white">
        {/* Header */}
        <div className="border-b px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => {
                setCurrentView('list');
                setSelectedTask(null);
              }}
              className="p-1 -ml-1"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
            <h2 className="font-semibold">Detalhes da Tarefa</h2>
          </div>
          {selectedTask.status !== 'completed' && (
            <button
              onClick={() => handleComplete(selectedTask.id)}
              className="p-2 text-green-600"
            >
              <CheckCircle className="h-5 w-5" />
            </button>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">
          <div className="space-y-4">
            {/* Status e Tipo */}
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                {getStatusIcon(selectedTask.status)}
                <span className="text-sm text-gray-600">
                  {selectedTask.status === 'completed' ? 'Concluída' :
                   selectedTask.status === 'pending' ? 'Pendente' :
                   selectedTask.status === 'in_progress' ? 'Em progresso' : 'Cancelada'}
                </span>
              </div>
              <div className="flex items-center gap-2">
                {getTaskIcon(selectedTask.task_type)}
                <span className="text-sm text-gray-600">
                  {selectedTask.task_type === 'message' ? 'Mensagem' :
                   selectedTask.task_type === 'call' ? 'Ligação' :
                   selectedTask.task_type === 'email' ? 'Email' : 'Customizada'}
                </span>
              </div>
            </div>

            {/* Título */}
            <div>
              <h3 className={`text-lg font-medium ${
                selectedTask.status === 'completed' ? 'line-through text-gray-500' : ''
              }`}>
                {selectedTask.title}
              </h3>
            </div>

            {/* Data e Prioridade */}
            <div className="space-y-2">
              <p className={`text-sm ${dateFormat.class}`}>
                <Clock className="h-4 w-4 inline mr-1" />
                {dateFormat.text}
              </p>
              <div className="flex items-center gap-2">
                <span className={`text-xs px-2 py-1 rounded-full ${getPriorityColor(selectedTask.priority)}`}>
                  {selectedTask.priority === 'urgent' ? 'Urgente' :
                   selectedTask.priority === 'high' ? 'Alta' :
                   selectedTask.priority === 'medium' ? 'Média' : 'Baixa'}
                </span>
                {selectedTask.reminder_minutes > 0 && (
                  <span className="text-xs bg-gray-100 text-gray-600 px-2 py-1 rounded">
                    Lembrete {selectedTask.reminder_minutes < 60
                      ? `${selectedTask.reminder_minutes} min`
                      : selectedTask.reminder_minutes === 1440
                        ? '1 dia'
                        : `${selectedTask.reminder_minutes / 60}h`} antes
                  </span>
                )}
              </div>
            </div>

            {/* Descrição */}
            {selectedTask.description && (
              <div>
                <h4 className="text-sm font-medium text-gray-700 mb-1">Descrição</h4>
                <p className="text-sm text-gray-600 bg-gray-50 p-3 rounded-lg">
                  {selectedTask.description}
                </p>
              </div>
            )}

            {/* Tags */}
            {selectedTask.tags && selectedTask.tags.length > 0 && (
              <div>
                <h4 className="text-sm font-medium text-gray-700 mb-1">Tags</h4>
                <div className="flex flex-wrap gap-1">
                  {selectedTask.tags.map(tag => (
                    <span key={tag} className="text-xs bg-gray-100 text-gray-600 px-2 py-1 rounded">
                      #{tag}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Informações */}
            <div className="border-t pt-4 space-y-3">
              <div>
                <span className="text-xs text-gray-500">Criada por</span>
                <p className="text-sm">{selectedTask.created_by.name}</p>
                <p className="text-xs text-gray-500">
                  {format(parseISO(selectedTask.created_at), "dd/MM/yyyy 'às' HH:mm")}
                </p>
              </div>

              {selectedTask.assigned_to && (
                <div>
                  <span className="text-xs text-gray-500">Atribuída a</span>
                  <p className="text-sm">{selectedTask.assigned_to.name}</p>
                </div>
              )}

              {selectedTask.completed_at && selectedTask.completed_by && (
                <div>
                  <span className="text-xs text-gray-500">Concluída por</span>
                  <p className="text-sm">{selectedTask.completed_by.name}</p>
                  <p className="text-xs text-gray-500">
                    {format(parseISO(selectedTask.completed_at), "dd/MM/yyyy 'às' HH:mm")}
                  </p>
                </div>
              )}
            </div>

            {/* Ações */}
            <div className="flex gap-2 pt-4">
              <button
                onClick={() => {
                  setEditingTask(selectedTask);
                  setFormData({
                    task_type: selectedTask.task_type,
                    title: selectedTask.title,
                    description: selectedTask.description || '',
                    scheduled_for: format(parseISO(selectedTask.scheduled_for), "yyyy-MM-dd'T'HH:mm"),
                    reminder_minutes: selectedTask.reminder_minutes,
                    priority: selectedTask.priority,
                    assigned_to: selectedTask.assigned_to?.id,
                    tags: selectedTask.tags || []
                  });
                  setCurrentView('form');
                }}
                className="flex-1 py-2 border border-gray-300 rounded-lg flex items-center justify-center gap-2"
              >
                <Edit2 className="h-4 w-4" />
                <span>Editar</span>
              </button>
              <button
                onClick={() => handleDelete(selectedTask.id)}
                className="flex-1 py-2 border border-red-300 text-red-600 rounded-lg flex items-center justify-center gap-2"
              >
                <Trash2 className="h-4 w-4" />
                <span>Excluir</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="fixed inset-0 bg-white z-50">
      {currentView === 'list' && renderTaskList()}
      {currentView === 'form' && renderTaskForm()}
      {currentView === 'detail' && renderTaskDetail()}
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

export default TaskPanelMobile;
