import React, { useState, useEffect } from 'react';
import {
  X,
  Calendar,
  Clock,
  Phone,
  Mail,
  MessageSquare,
  CheckCircle,
  AlertCircle,
  Search,
  Filter,
  User,
  ChevronDown,
  SortAsc,
  SortDesc
} from 'lucide-react';
import { format, formatDistanceToNow, isToday, isTomorrow, parseISO } from 'date-fns';
import { ptBR } from 'date-fns/locale';
import api from '../services/api.ts';
import styles from './AllTasksModal.module.css';

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
  created_by?: {
    id: number;
    name: string;
  };
  assigned_to?: {
    id: number;
    name: string;
  };
}

interface AllTasksModalProps {
  isOpen: boolean;
  onClose: () => void;
  onTaskClick?: (task: Task) => void;
}

const AllTasksModal: React.FC<AllTasksModalProps> = ({ isOpen, onClose, onTaskClick }) => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [priorityFilter, setPriorityFilter] = useState<string>('all');
  const [sortBy, setSortBy] = useState<'date' | 'priority'>('date');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');
  const [showFilters, setShowFilters] = useState(false);
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const PAGE_SIZE = 50;

  useEffect(() => {
    if (isOpen) {
      // Reset pagination when opening modal
      setPage(0);
      setTasks([]);
      setHasMore(true);
      loadAllTasks(0, true);
    }
  }, [isOpen]);

  // Reset pagination when filters change
  useEffect(() => {
    if (isOpen) {
      setPage(0);
      setTasks([]);
      setHasMore(true);
      loadAllTasks(0, true);
    }
  }, [statusFilter, priorityFilter, searchTerm]);

  const loadAllTasks = async (pageNumber: number = 0, isNewSearch: boolean = false) => {
    if (!hasMore && !isNewSearch) return;

    try {
      if (pageNumber === 0) {
        setLoading(true);
      } else {
        setLoadingMore(true);
      }

      // Build query parameters
      const params = new URLSearchParams();
      params.append('limit', PAGE_SIZE.toString());
      params.append('offset', (pageNumber * PAGE_SIZE).toString());

      // Handle overdue filter specially
      if (statusFilter === 'overdue') {
        params.append('overdue', 'true');
      } else if (statusFilter === 'pending') {
        // For pending, we want non-overdue pending tasks
        params.append('status', 'pending');
        params.append('overdue', 'false');
      } else if (statusFilter !== 'all') {
        params.append('status', statusFilter);
      }

      if (priorityFilter !== 'all') params.append('priority', priorityFilter);
      if (searchTerm) params.append('search', searchTerm);

      const response = await api.get(`/api/tasks/all?${params.toString()}`);
      const newTasks = response.data;

      if (isNewSearch) {
        setTasks(newTasks);
      } else {
        setTasks(prev => [...prev, ...newTasks]);
      }

      // Check if there are more tasks to load
      setHasMore(newTasks.length === PAGE_SIZE);
      setPage(pageNumber);

    } catch (error) {
      console.error('Erro ao carregar tarefas:', error);
      setHasMore(false);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  };

  const handleLoadMore = () => {
    if (!loadingMore && hasMore) {
      loadAllTasks(page + 1);
    }
  };

  // Handle scroll for infinite loading
  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const element = e.currentTarget;
    const threshold = 100; // Load more when within 100px of bottom

    if (element.scrollHeight - element.scrollTop - element.clientHeight < threshold) {
      handleLoadMore();
    }
  };

  const getTaskTypeIcon = (type: string) => {
    switch (type) {
      case 'message':
        return <MessageSquare className={styles.taskIcon} />;
      case 'call':
        return <Phone className={styles.taskIcon} />;
      case 'email':
        return <Mail className={styles.taskIcon} />;
      default:
        return <Calendar className={styles.taskIcon} />;
    }
  };

  const isTaskOverdue = (task: Task) => {
    // Check if task is overdue considering current time
    const now = new Date();
    const scheduledTime = new Date(task.scheduled_for);
    return scheduledTime < now && (task.status === 'pending' || task.status === 'in_progress');
  };


  const formatTaskDate = (dateStr: string, task: Task) => {
    const date = parseISO(dateStr);
    const isOverdueTask = isTaskOverdue(task);

    if (isOverdueTask) {
      return {
        text: `Atrasada há ${formatDistanceToNow(date, { locale: ptBR })}`,
        tone: 'danger' as const,
      };
    }

    if (isToday(date)) {
      return {
        text: `Hoje às ${format(date, 'HH:mm')}`,
        tone: 'accent' as const,
      };
    }

    if (isTomorrow(date)) {
      return {
        text: `Amanhã às ${format(date, 'HH:mm')}`,
        tone: 'default' as const,
      };
    }

    return {
      text: format(date, "dd 'de' MMMM 'às' HH:mm", { locale: ptBR }),
      tone: 'default' as const,
    };
  };

  const getPriorityLabel = (priority: Task['priority']) => {
    switch (priority) {
      case 'urgent': return 'Urgente';
      case 'high': return 'Alta';
      case 'medium': return 'Média';
      default: return 'Baixa';
    }
  };

  const getStatusLabel = (status: Task['status']) => {
    switch (status) {
      case 'pending': return 'Pendente';
      case 'in_progress': return 'Em progresso';
      case 'completed': return 'Concluída';
      default: return 'Cancelada';
    }
  };

  const getPriorityClass = (priority: Task['priority']) => {
    switch (priority) {
      case 'urgent': return styles.priorityUrgent;
      case 'high': return styles.priorityHigh;
      case 'medium': return styles.priorityMedium;
      default: return styles.priorityLow;
    }
  };

  const getStatusClass = (status: Task['status']) => {
    switch (status) {
      case 'completed': return styles.statusCompleted;
      case 'in_progress': return styles.statusProgress;
      case 'pending': return styles.statusPending;
      default: return styles.statusCanceled;
    }
  };

  // Apenas ordenar tarefas (filtros já aplicados no backend)
  const filteredAndSortedTasks = [...tasks].sort((a, b) => {
    if (sortBy === 'date') {
      const dateA = new Date(a.scheduled_for).getTime();
      const dateB = new Date(b.scheduled_for).getTime();
      return sortOrder === 'asc' ? dateA - dateB : dateB - dateA;
    } else {
      // Ordenar por prioridade
      const priorityOrder = { urgent: 0, high: 1, medium: 2, low: 3 };
      const orderA = priorityOrder[a.priority] || 4;
      const orderB = priorityOrder[b.priority] || 4;
      return sortOrder === 'asc' ? orderA - orderB : orderB - orderA;
    }
  });

  if (!isOpen) return null;

  return (
    <div className={styles.overlay}>
      <div className={styles.modal}>
        <div className={styles.header}>
          <div className={styles.headerText}>
            <p className={styles.eyebrow}>Histórico</p>
            <h2 className={styles.title}>Todas as tarefas</h2>
          </div>
          <button
            aria-label="Fechar histórico de tarefas"
            onClick={onClose}
            className={styles.iconButton}
            type="button"
          >
            <X className={styles.icon} />
          </button>
        </div>

        <div className={styles.toolbar}>
          <div className={styles.searchRow}>
            <div className={styles.searchBox}>
              <Search className={styles.searchIcon} />
              <input
                type="text"
                placeholder="Buscar tarefas..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className={styles.searchInput}
              />
            </div>
            <button
              onClick={() => setShowFilters(!showFilters)}
              className={`${styles.filterButton} ${showFilters ? styles.filterButtonActive : ''}`}
              type="button"
            >
              <Filter className={styles.controlIcon} />
              <span>Filtros</span>
              <ChevronDown className={`${styles.controlIcon} ${showFilters ? styles.chevronOpen : ''}`} />
            </button>
          </div>

          {showFilters && (
            <div className={styles.filtersGrid}>
              <label className={styles.field}>
                <span className={styles.fieldLabel}>Status</span>
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  className={styles.select}
                >
                  <option value="all">Todos</option>
                  <option value="pending">Pendente</option>
                  <option value="in_progress">Em progresso</option>
                  <option value="completed">Concluída</option>
                  <option value="overdue">Em atraso</option>
                  <option value="canceled">Cancelada</option>
                </select>
              </label>

              <label className={styles.field}>
                <span className={styles.fieldLabel}>Prioridade</span>
                <select
                  value={priorityFilter}
                  onChange={(e) => setPriorityFilter(e.target.value)}
                  className={styles.select}
                >
                  <option value="all">Todas</option>
                  <option value="urgent">Urgente</option>
                  <option value="high">Alta</option>
                  <option value="medium">Média</option>
                  <option value="low">Baixa</option>
                </select>
              </label>

              <label className={styles.field}>
                <span className={styles.fieldLabel}>Ordenar por</span>
                <div className={styles.sortControls}>
                  <select
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value as 'date' | 'priority')}
                    className={styles.select}
                  >
                    <option value="date">Data</option>
                    <option value="priority">Prioridade</option>
                  </select>
                  <button
                    onClick={() => setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')}
                    className={styles.sortButton}
                    type="button"
                    aria-label="Alternar ordem"
                  >
                    {sortOrder === 'asc' ? <SortAsc className={styles.controlIcon} /> : <SortDesc className={styles.controlIcon} />}
                  </button>
                </div>
              </label>
            </div>
          )}
        </div>

        <div className={styles.content} onScroll={handleScroll}>
          {loading ? (
            <div className={styles.loadingState}>
              <div className={styles.spinner} />
              <span>Carregando tarefas...</span>
            </div>
          ) : filteredAndSortedTasks.length === 0 ? (
            <div className={styles.emptyState}>
              <AlertCircle className={styles.emptyIcon} />
              <p>Nenhuma tarefa encontrada</p>
            </div>
          ) : (
            <div className={styles.taskList}>
              {filteredAndSortedTasks.map((task) => {
                const dateInfo = formatTaskDate(task.scheduled_for, task);
                const isOverdue = isTaskOverdue(task);

                return (
                  <div
                    key={task.id}
                    className={`${styles.taskCard} ${isOverdue ? styles.taskCardOverdue : ''}`}
                    onClick={() => onTaskClick?.(task)}
                  >
                    <div className={styles.taskIconBox}>
                      {getTaskTypeIcon(task.task_type)}
                    </div>

                    <div className={styles.taskBody}>
                      <div className={styles.taskHeader}>
                        <h3 className={styles.taskTitle}>{task.title}</h3>
                        <div className={styles.badgeGroup}>
                          <span className={`${styles.badge} ${getPriorityClass(task.priority)}`}>
                            {getPriorityLabel(task.priority)}
                          </span>
                          <span className={`${styles.badge} ${getStatusClass(task.status)}`}>
                            {getStatusLabel(task.status)}
                          </span>
                        </div>
                      </div>

                      {task.description && (
                        <p className={styles.taskDescription}>{task.description}</p>
                      )}

                      <div className={styles.taskMeta}>
                        <span className={styles.metaItem}>
                          <User className={styles.metaIcon} />
                          {task.contact_name}
                        </span>

                        <span className={`${styles.metaItem} ${dateInfo.tone === 'danger' ? styles.metaDanger : dateInfo.tone === 'accent' ? styles.metaAccent : ''}`}>
                          <Clock className={styles.metaIcon} />
                          {dateInfo.text}
                        </span>

                        {task.assigned_to && (
                          <span className={styles.metaItem}>
                            <CheckCircle className={styles.metaIcon} />
                            Atribuída a {task.assigned_to.name}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}

              {loadingMore && (
                <div className={styles.inlineLoading}>
                  <div className={styles.smallSpinner} />
                  <span>Carregando mais tarefas...</span>
                </div>
              )}

              {!hasMore && tasks.length > 0 && (
                <div className={styles.endState}>
                  Todas as tarefas foram carregadas
                </div>
              )}
            </div>
          )}
        </div>

        <div className={styles.footer}>
          <div className={styles.footerSummary}>
            <span>
              {filteredAndSortedTasks.length} {filteredAndSortedTasks.length === 1 ? 'tarefa' : 'tarefas'} carregadas
              {hasMore && ' de uma lista maior'}
              {searchTerm || statusFilter !== 'all' || priorityFilter !== 'all' ? ' - filtradas' : ''}
            </span>
            <div className={styles.footerStats}>
              <span className={styles.footerStat}>
                <span className={`${styles.statusDot} ${styles.dotDanger}`} />
                {tasks.filter(t => isTaskOverdue(t)).length} atrasadas
              </span>
              <span className={styles.footerStat}>
                <span className={`${styles.statusDot} ${styles.dotBrand}`} />
                {tasks.filter(t => t.status === 'pending').length} pendentes
              </span>
              <span className={styles.footerStat}>
                <span className={`${styles.statusDot} ${styles.dotSuccess}`} />
                {tasks.filter(t => t.status === 'completed').length} concluídas
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AllTasksModal;
