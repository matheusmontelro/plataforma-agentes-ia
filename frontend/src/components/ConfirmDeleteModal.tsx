import React from 'react';
import { AgentiveConfirmModal } from './AgentiveUI.tsx';

interface ConfirmDeleteModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title?: string;
  message?: React.ReactNode;
  confirmText?: string;
  cancelText?: string;
  children?: React.ReactNode;
  isLoading?: boolean;
  variant?: 'danger' | 'warning' | 'info';
}

const ConfirmDeleteModal: React.FC<ConfirmDeleteModalProps> = ({
  isOpen,
  onClose,
  onConfirm,
  title = "Confirmar exclusão",
  message = "Esta ação não pode ser desfeita. Tem certeza que deseja continuar?",
  confirmText = "Excluir",
  cancelText = "Cancelar",
  children,
  isLoading,
  variant = 'danger',
}) => {
  const handleConfirm = () => {
    onConfirm();
    onClose();
  };

  return (
    <AgentiveConfirmModal
      cancelText={cancelText}
      confirmText={confirmText}
      isLoading={isLoading}
      isOpen={isOpen}
      message={message}
      onClose={onClose}
      onConfirm={handleConfirm}
      title={title}
      variant={variant}
    >
      {children}
    </AgentiveConfirmModal>
  );
};

export default ConfirmDeleteModal;
