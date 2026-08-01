import { LucideIcon } from 'lucide-react';

// Tipos para permissões
export type UserRole = string;
export type UserType = 'user' | 'master';
export type Permission =
  | 'dashboard'
  | 'crm'
  | 'chat'
  | 'whatsapp'
  | 'follow-up'
  | 'prompt'
  | 'company';

// Interface para MenuItem (compatível com ProtectedLayout)
export interface MenuItem {
  path: string;
  icon: LucideIcon;
  label: string;
  badge?: string;
  status?: string;
  subItems?: SubItem[];
  permission?: Permission; // Nova propriedade para controle de acesso
  isNew?: boolean;
  isBeta?: boolean;
  isGroup?: boolean;
}

export interface SubItem {
  path: string;
  label: string;
  icon?: LucideIcon;
  isNew?: boolean;
  isBeta?: boolean;
  permission?: Permission; // Nova propriedade para controle de acesso
  subItems?: SubItem[]; // Suporte a n-níveis (L3)
}

export const USER_TYPE_PERMISSIONS: Record<UserType, Permission[]> = {
  user: [],
  master: ['dashboard', 'crm', 'chat', 'whatsapp', 'follow-up', 'prompt', 'company']
};

const parseStoredPermissions = (): Permission[] | null => {
  const raw = localStorage.getItem('sidebar_permissions');
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return null;
    const allowed = new Set<Permission>(['dashboard', 'crm', 'chat', 'whatsapp', 'follow-up', 'prompt', 'company']);
    return parsed
      .map((item) => item === 'clinic' ? 'company' : item)
      .filter((item): item is Permission => allowed.has(item));
  } catch (error) {
    console.error('Erro ao parsear sidebar_permissions:', error);
    return null;
  }
};

/**
 * Obtém o role do usuário a partir do localStorage
 */
export const getUserRole = (): UserRole | null => {
  // Primeiro verifica se é master
  const userType = localStorage.getItem('user_type');
  if (userType === 'master') {
    return 'MASTER';
  }

  const userTeamData = localStorage.getItem('user_team_data');
  if (userTeamData) {
    try {
      const team = JSON.parse(userTeamData);
      const label = String(team?.name || team?.code || '').trim();
      return label || null;
    } catch (error) {
      console.error('Erro ao parsear user_team_data:', error);
    }
  }

  const userTeam = localStorage.getItem('user_team');
  if (userTeam) {
    return userTeam;
  }

  return null;
};

/**
 * Obtém o tipo do usuário a partir do localStorage
 */
export const getUserType = (): UserType => {
  const userType = localStorage.getItem('user_type');
  return userType === 'master' ? 'master' : 'user';
};

/**
 * Verifica se o usuário tem uma permissão específica
 */
export const hasPermission = (permission: Permission): boolean => {
  const userType = getUserType();

  if (userType === 'master') {
    return USER_TYPE_PERMISSIONS.master.includes(permission);
  }

  const storedPermissions = parseStoredPermissions();
  if (storedPermissions) {
    return storedPermissions.includes(permission);
  }

  return USER_TYPE_PERMISSIONS[userType].includes(permission);
};

/**
 * Filtra os itens de menu baseado nas permissões do usuário
 */
export const filterMenusByPermissions = (menuItems: MenuItem[]): MenuItem[] => {
  return menuItems.map(item => {
    const nextItem: MenuItem = {
      ...item,
      subItems: item.subItems ? item.subItems.filter(subItem => {
        if (subItem.permission && !hasPermission(subItem.permission)) {
          return false;
        }
        return true;
      }).map(subItem => ({ ...subItem })) : undefined,
    };
    return nextItem;
  }).filter(item => {
    if (item.permission && !hasPermission(item.permission)) {
      return false;
    }

    if (item.isGroup) {
      return item.subItems && item.subItems.length > 0;
    }

    return true;
  });
};

/**
 * Obtém todas as permissões do usuário atual
 */
export const getUserPermissions = (): Permission[] => {
  const userType = getUserType();

  if (userType === 'master') {
    return USER_TYPE_PERMISSIONS.master;
  }

  const storedPermissions = parseStoredPermissions();
  if (storedPermissions) {
    return storedPermissions;
  }

  return USER_TYPE_PERMISSIONS[userType];
};

/**
 * Verifica se o usuário é master
 */
export const isUserMaster = (): boolean => {
  return getUserType() === 'master';
};

/**
 * Verifica se o usuário pode acessar configurações avançadas
 */
export const canAccessAdvancedSettings = (): boolean => {
  return hasPermission('prompt') || hasPermission('company');
};

/**
 * Debug: retorna informações do usuário atual (apenas para desenvolvimento)
 */
export const debugUserInfo = () => {
  return {
    userRole: getUserRole(),
    userType: getUserType(),
    permissions: getUserPermissions(),
    isRawData: {
      user_type: localStorage.getItem('user_type'),
      user_team: localStorage.getItem('user_team'),
      user_team_data: localStorage.getItem('user_team_data'),
      sidebar_permissions: localStorage.getItem('sidebar_permissions'),
      user_id: localStorage.getItem('user_id'),
    }
  };
};
