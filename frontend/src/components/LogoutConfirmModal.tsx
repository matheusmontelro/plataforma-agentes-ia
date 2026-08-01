import React from 'react';
import api, { clearAuthStorage } from '../services/api.ts';
import { AgentiveConfirmModal } from './AgentiveUI.tsx';
import { branding } from '../config/branding.ts';

interface LogoutConfirmModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

const LogoutConfirmModal: React.FC<LogoutConfirmModalProps> = ({
  isOpen,
  onClose,
  onConfirm
}) => {
  const handleLogout = async () => {
    try {
      await api.post('/auth/logout');
    } catch {
      // Mesmo se o servidor não responder, limpe o estado local.
    }
    clearAuthStorage();
    window.location.href = '/';
  };

  return (
    <AgentiveConfirmModal
      cancelText="Continuar aqui"
      confirmText="Sair"
      isOpen={isOpen}
      message="Você precisará fazer login novamente para acessar a conta e os dados desta empresa."
      onClose={onClose}
      onConfirm={async () => {
        onConfirm();
        await handleLogout();
      }}
      title={`Sair de ${branding.appName}?`}
      variant="warning"
    />
  );
};

export default LogoutConfirmModal;
