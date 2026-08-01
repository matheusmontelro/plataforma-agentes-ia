import React from 'react';
import { format } from 'date-fns';
import { ptBR } from 'date-fns/locale';
import { Clock, Mail, MessageSquare, PhoneCall } from 'lucide-react';
import './crm/CRMModern/CRMModernUI.css';

interface TaskPreviewProps {
  task: {
    title: string;
    scheduled_for: string;
    task_type: 'message' | 'call' | 'email';
  };
}

const TaskPreview: React.FC<TaskPreviewProps> = ({ task }) => {
  const getTimeDisplay = () => {
    const taskDate = new Date(task.scheduled_for);
    const now = new Date();
    const diffInMinutes = (taskDate.getTime() - now.getTime()) / (1000 * 60);

    if (diffInMinutes < 60) {
      return `em ${Math.ceil(diffInMinutes)} min`;
    } else if (diffInMinutes < 24 * 60) {
      return `hoje ${format(taskDate, 'HH:mm', { locale: ptBR })}`;
    } else {
      return format(taskDate, "dd/MM HH:mm", { locale: ptBR });
    }
  };

  const getTaskIcon = () => {
    switch (task.task_type) {
      case 'message':
        return MessageSquare;
      case 'call':
        return PhoneCall;
      case 'email':
        return Mail;
      default:
        return MessageSquare;
    }
  };

  const Icon = getTaskIcon();

  return (
    <div className="crm-task-preview">
      <div className="crm-task-preview__main">
        <span className="crm-task-preview__icon">
          <Icon className="h-3.5 w-3.5" />
        </span>
        <span className="crm-task-preview__title">{task.title}</span>
      </div>
      <div className="crm-task-preview__time">
        <Clock className="h-3 w-3" />
        <span>{getTimeDisplay()}</span>
      </div>
    </div>
  );
};

export default TaskPreview;
