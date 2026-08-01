import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell, BellRing, Clock, AlertCircle, History, Phone, Mail, MessageSquare, Calendar } from 'lucide-react';
import AllTasksModal from '../AllTasksModal';
import styles from './NotificationTray.module.css';

export interface TaskReminder {
  type: string;
  task: {
    id: number;
    title: string;
    task_type: string;
    priority: string;
    scheduled_for: string;
    contact: {
      id: number;
      name: string;
      phone: string;
    };
  };
  minutes_until: number;
  is_overdue: boolean;
  company_id?: number;
}

export type TrayNotification = TaskReminder;

export const isTaskReminderNotification = (notification: unknown): notification is TaskReminder => {
  if (!notification || typeof notification !== 'object') return false;
  const candidate = notification as Partial<TaskReminder>;
  return Boolean(candidate.task && typeof candidate.task.id === 'number');
};

interface NotificationTrayProps {
  isCollapsed: boolean;
  websocketMessage: any;
}

const NotificationTray: React.FC<NotificationTrayProps> = ({ isCollapsed, websocketMessage }) => {
  const navigate = useNavigate();
  const [notifications, setNotifications] = useState<TrayNotification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [showAllTasksModal, setShowAllTasksModal] = useState(false);
  const [lastProcessedMessage, setLastProcessedMessage] = useState<string | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const trayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (trayRef.current && !trayRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [trayRef]);

  useEffect(() => {
    const savedNotifications = localStorage.getItem('taskNotifications');
    const savedUnreadCount = localStorage.getItem('taskUnreadCount');
    if (savedNotifications) {
      try {
        const parsed = JSON.parse(savedNotifications);
        setNotifications(Array.isArray(parsed) ? parsed.filter(isTaskReminderNotification) : []);
      } catch (e) {
        console.error('Erro ao carregar notificações:', e);
      }
    }
    if (savedUnreadCount) setUnreadCount(parseInt(savedUnreadCount, 10));
  }, []);

  useEffect(() => {
    localStorage.setItem('taskNotifications', JSON.stringify(notifications));
    localStorage.setItem('taskUnreadCount', unreadCount.toString());
  }, [notifications, unreadCount]);

  useEffect(() => {
    if (websocketMessage?.type === 'task_reminder' || websocketMessage?.type === 'overdue_tasks') {
      const messageId = `${websocketMessage.type}_${websocketMessage.count}_${JSON.stringify(websocketMessage.tasks?.map((t: any) => t.id) || [])}`;
      if (lastProcessedMessage === messageId) return;

      setLastProcessedMessage(messageId);

      if (websocketMessage?.type === 'task_reminder') {
        const newNotification = websocketMessage as TaskReminder;
        const currentCompanyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
        if (newNotification.company_id && currentCompanyId && newNotification.company_id.toString() !== currentCompanyId) return;

        setNotifications(prev => {
          const exists = prev.some(n => isTaskReminderNotification(n) && n.task.id === newNotification.task.id);
          if (exists) {
            return prev.map(n => (
              isTaskReminderNotification(n) && n.task.id === newNotification.task.id ? newNotification : n
            ));
          }
          return [newNotification, ...prev].slice(0, 10);
        });
        setUnreadCount(prev => prev + 1);
      } else if (websocketMessage?.type === 'overdue_tasks') {
        const { tasks } = websocketMessage;
        if (tasks && tasks.length > 0) {
          const newNotifications = tasks.map((task: any) => {
            const scheduledTime = new Date(task.scheduled_for);
            const now = new Date();
            const minutesOverdue = Math.floor((now.getTime() - scheduledTime.getTime()) / (1000 * 60));
            return {
              type: 'overdue_task',
              task: {
                id: task.id,
                title: task.title,
                task_type: task.task_type,
                priority: task.priority,
                scheduled_for: task.scheduled_for,
                contact: {
                  id: task.contact_id,
                  name: task.contact_name,
                  phone: task.contact_phone,
                }
              },
              minutes_until: -minutesOverdue,
              is_overdue: true,
              message: websocketMessage.message
            };
          });
          setNotifications(prev => {
            const filtered = prev.filter(n => !n.is_overdue);
            return [...newNotifications, ...filtered].slice(0, 10);
          });
          setUnreadCount(prev => {
            const existingOverdueIds = notifications
              .filter((n): n is TaskReminder => isTaskReminderNotification(n) && n.is_overdue)
              .map(n => n.task.id);
            const newOverdueIds = newNotifications.map((n: any) => n.task.id);
            const reallyNewCount = newOverdueIds.filter((id: number) => !existingOverdueIds.includes(id)).length;
            return prev + reallyNewCount;
          });
        }
      }
    }
  }, [websocketMessage, notifications, lastProcessedMessage]);

  const clearNotifications = () => {
    setNotifications([]);
    setUnreadCount(0);
    localStorage.removeItem('taskNotifications');
    localStorage.removeItem('taskUnreadCount');
  };

  const getTaskTypeIcon = (type: string) => {
    switch (type) {
      case 'message': return <MessageSquare className={styles.taskTypeIcon} />;
      case 'call': return <Phone className={styles.taskTypeIcon} />;
      case 'email': return <Mail className={styles.taskTypeIcon} />;
      default: return <Calendar className={styles.taskTypeIcon} />;
    }
  };

  const formatTimeUntil = (minutes: number, isOverdue: boolean) => {
    const absMinutes = Math.abs(minutes);
    if (isOverdue) return `Atrasada há ${absMinutes < 60 ? `${absMinutes} min` : `${Math.floor(absMinutes / 60)}h`}`;
    if (minutes <= 0) return 'Agora';
    return `Em ${minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)}h`}`;
  };

  return (
    <>
      <div ref={trayRef} className={styles.container}>
        <div className={`${styles.panel} ${isOpen ? styles.panelOpen : styles.panelClosed}`}>
          <div className={styles.header}>
            <div className={styles.headerTitleContainer}>
              <span className={styles.headerIconWrapper}>
                <BellRing className={styles.headerIcon} />
              </span>
              <div className={styles.headerTextWrapper}>
                <p className={styles.headerTitle}>
                  Notificações
                </p>
                <p className={styles.headerSubtitle}>
                  {notifications.length > 0 ? `${notifications.length} pendente${notifications.length > 1 ? 's' : ''}` : 'Tudo em dia'}
                </p>
              </div>
            </div>
            {notifications.length > 0 && (
              <button onClick={clearNotifications} className={styles.clearButton}>
                Limpar
              </button>
            )}
          </div>

          <div className={styles.listContainer}>
            {notifications.length === 0 ? (
              <div className={styles.emptyState}>
                <span className={styles.emptyStateIconWrapper}>
                  <Bell className={styles.emptyStateIcon} />
                </span>
                <p className={styles.emptyStateTitle}>Tudo limpo</p>
                <p className={styles.emptyStateSubtitle}>Nenhuma notificação por enquanto.</p>
              </div>
            ) : (
              notifications.map((n, i) => (
                  <div
                    key={`${n.task.id}-${i}`}
                    className={`${styles.notificationItem} ${n.is_overdue ? styles.notificationItemOverdue : styles.notificationItemTask}`}
                    onClick={() => {
                      navigate('/chat', { state: { selectedPhone: n.task.contact.phone, selectedContact: n.task.contact } });
                      setIsOpen(false);
                    }}
                  >
                    <div className={styles.notificationItemHeader}>
                      <span className={`${styles.notificationItemTitle} ${n.is_overdue ? styles.textOverdue : ''}`}>
                        {n.task.title}
                      </span>
                      <span className={styles.taskTypeIconWrapper}>
                        {getTaskTypeIcon(n.task.task_type)}
                      </span>
                    </div>
                    <p className={styles.notificationItemSubtitle}>{n.task.contact.name}</p>

                    <div className={`${styles.notificationItemTime} ${n.is_overdue ? styles.textOverdue : ''}`}>
                      {n.is_overdue ? <AlertCircle className={styles.timeIcon} /> : <Clock className={styles.timeIcon} />}
                      {formatTimeUntil(n.minutes_until, n.is_overdue)}
                    </div>
                  </div>
              ))
            )}
          </div>

          <div className={styles.footer}>
            <button
              onClick={() => { setShowAllTasksModal(true); setIsOpen(false); }}
              className={styles.footerButton}
            >
              <span className={styles.footerButtonIconWrapper}>
                <History className={styles.footerButtonIcon} />
              </span>
              <span className={styles.footerButtonText}>Ver histórico completo</span>
            </button>
          </div>
        </div>

        <button
          className={`${styles.triggerButton} ${isOpen || unreadCount > 0 ? styles.triggerButtonActive : styles.triggerButtonInactive}`}
          onClick={() => {
            setIsOpen(!isOpen);
            if (!isOpen) setUnreadCount(0);
          }}
        >
          <div className={styles.triggerIconContainer}>
            <BellRing className={styles.triggerIcon} />
            {unreadCount > 0 && <span className={styles.triggerBadgePulse} />}
          </div>
          <span className={styles.triggerText}>Notificações</span>
          {unreadCount > 0 && (
            <span className={styles.triggerBadge}>
              {unreadCount}
            </span>
          )}
        </button>
      </div>

      <AllTasksModal
        isOpen={showAllTasksModal}
        onClose={() => setShowAllTasksModal(false)}
        onTaskClick={(task) => {
          navigate('/chat', {
            state: {
              selectedPhone: task.contact_phone,
              selectedContact: {
                id: task.contact_id,
                name: task.contact_name,
                phone: task.contact_phone
              }
            }
          });
          setShowAllTasksModal(false);
        }}
      />
    </>
  );
};

export default NotificationTray;
