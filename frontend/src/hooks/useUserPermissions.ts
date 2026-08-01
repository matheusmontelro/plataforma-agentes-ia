import { useState, useEffect } from 'react';
import {
  hasPermission,
  getUserPermissions,
  getUserRole,
  getUserType,
  isUserMaster,
  canAccessAdvancedSettings,
  debugUserInfo,
  type Permission,
  type UserRole,
  type UserType
} from '../services/permissionService';

interface UserPermissions {
  // Permissões específicas
  canAccessDashboard: boolean;
  canAccessCRM: boolean;
  canAccessChat: boolean;
  canAccessWhatsApp: boolean;
  canAccessFollowUp: boolean;
  canAccessPromptConfig: boolean;
  canAccessCompanyConfig: boolean;

  // Informações do usuário
  userRole: UserRole | null;
  userType: UserType;
  isMaster: boolean;

  // Métodos utilitários
  hasPermission: (permission: Permission) => boolean;
  getAllPermissions: () => Permission[];
  canAccessAdvanced: boolean;

  // Debug (apenas desenvolvimento)
  debugInfo: () => any;
}

/**
 * Hook customizado para gerenciar permissões do usuário
 *
 * Este hook centraliza toda a lógica de permissões e fornece uma interface
 * simples para componentes verificarem se o usuário pode acessar determinadas funcionalidades.
 *
 * @returns UserPermissions object com todas as permissões e métodos utilitários
 */
export const useUserPermissions = (): UserPermissions => {
  const [permissions, setPermissions] = useState<UserPermissions>(() => {
    return calculatePermissions();
  });

  // Recalcula permissões quando localStorage muda (ex: troca de empresa/usuário)
  useEffect(() => {
    const handleStorageChange = () => {
      setPermissions(calculatePermissions());
    };

    // Escuta mudanças no localStorage
    window.addEventListener('storage', handleStorageChange);

    // Também escuta mudanças customizadas (para quando o código modifica localStorage)
    window.addEventListener('userPermissionsChanged', handleStorageChange);

    return () => {
      window.removeEventListener('storage', handleStorageChange);
      window.removeEventListener('userPermissionsChanged', handleStorageChange);
    };
  }, []);

  return permissions;
};

/**
 * Calcula todas as permissões baseadas no estado atual do localStorage
 */
function calculatePermissions(): UserPermissions {
  const userRole = getUserRole();
  const userType = getUserType();
  const isMaster = isUserMaster();

  return {
    // Permissões específicas para cada funcionalidade
    canAccessDashboard: hasPermission('dashboard'),
    canAccessCRM: hasPermission('crm'),
    canAccessChat: hasPermission('chat'),
    canAccessWhatsApp: hasPermission('whatsapp'),
    canAccessFollowUp: hasPermission('follow-up'),
    canAccessPromptConfig: hasPermission('prompt'),
    canAccessCompanyConfig: hasPermission('company'),

    // Informações do usuário
    userRole,
    userType,
    isMaster,

    // Métodos utilitários
    hasPermission: (permission: Permission) => hasPermission(permission),
    getAllPermissions: () => getUserPermissions(),
    canAccessAdvanced: canAccessAdvancedSettings(),

    // Debug
    debugInfo: () => debugUserInfo(),
  };
}

/**
 * Função utilitária para disparar atualização manual das permissões
 * Útil quando o código modifica o localStorage programaticamente
 */
export const refreshUserPermissions = (): void => {
  window.dispatchEvent(new CustomEvent('userPermissionsChanged'));
};

/**
 * Hook para verificar uma permissão específica de forma reativa
 *
 * @param permission - A permissão a ser verificada
 * @returns boolean indicando se o usuário tem a permissão
 */
export const usePermission = (permission: Permission): boolean => {
  const { hasPermission: checkPermission } = useUserPermissions();
  return checkPermission(permission);
};

/**
 * Hook para verificar múltiplas permissões
 *
 * @param permissions - Array de permissões a serem verificadas
 * @returns object com o resultado de cada permissão
 */
export const usePermissions = (permissions: Permission[]): Record<Permission, boolean> => {
  const { hasPermission: checkPermission } = useUserPermissions();

  return permissions.reduce((acc, permission) => {
    acc[permission] = checkPermission(permission);
    return acc;
  }, {} as Record<Permission, boolean>);
};

/**
 * Hook para verificar se o usuário tem pelo menos uma das permissões fornecidas
 *
 * @param permissions - Array de permissões (OR logic)
 * @returns boolean indicando se o usuário tem pelo menos uma permissão
 */
export const useHasAnyPermission = (permissions: Permission[]): boolean => {
  const { hasPermission: checkPermission } = useUserPermissions();
  return permissions.some(permission => checkPermission(permission));
};

/**
 * Hook para verificar se o usuário tem todas as permissões fornecidas
 *
 * @param permissions - Array de permissões (AND logic)
 * @returns boolean indicando se o usuário tem todas as permissões
 */
export const useHasAllPermissions = (permissions: Permission[]): boolean => {
  const { hasPermission: checkPermission } = useUserPermissions();
  return permissions.every(permission => checkPermission(permission));
};