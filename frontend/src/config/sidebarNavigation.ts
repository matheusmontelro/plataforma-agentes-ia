import {
  Brain,
  Building2,
  Calendar,
  ClipboardCheck,
  CreditCard,
  GitMerge,
  KeyRound,
  LayoutDashboard,
  Megaphone,
  MessageSquare,
  Package,
  Plug,
  Receipt,
  Share2,
  Users,
  UserRound,
  Webhook,
  type LucideIcon,
} from 'lucide-react';
import WhatsAppIcon from '../components/icons/WhatsAppIcon.tsx';
import type { MenuItem, Permission, SubItem } from '../services/permissionService.ts';

export type ModuleKey = 'dashboard' | 'operacional' | 'clientes' | 'inteligencia' | 'conexoes' | 'config';

export interface ModuleMeta {
  label: string;
  description: string;
}

export interface SidebarPermissionItem {
  depth: number;
  icon?: LucideIcon;
  isBeta?: boolean;
  isNew?: boolean;
  label: string;
  moduleKey: ModuleKey;
  moduleLabel: string;
  parentLabel?: string;
  path: string;
  type: 'menu' | 'submenu';
}

export interface SidebarPermissionGroup {
  icon: LucideIcon;
  items: SidebarPermissionItem[];
  key: Permission;
  label: string;
  moduleLabels: string[];
}

export const MODULE_META: Record<ModuleKey, ModuleMeta> = {
  dashboard: {
    label: 'Dashboard',
    description: 'Visão geral da operação',
  },
  operacional: {
    label: 'Operacional',
    description: 'Atendimento, CRM e campanhas',
  },
  clientes: {
    label: 'Clientes',
    description: 'Clientes, faturas e pagamentos',
  },
  inteligencia: {
    label: 'Inteligência',
    description: 'Agentes, automações e IA',
  },
  conexoes: {
    label: 'Conexões',
    description: 'Canais, integrações e webhooks',
  },
  config: {
    label: 'Configurações',
    description: 'Empresa, campos e regras',
  },
};

export const SIDEBAR_MODULE_MENUS: Record<ModuleKey, MenuItem[]> = {
  dashboard: [
    {
      path: '/dashboard',
      label: 'Visão Geral',
      icon: LayoutDashboard,
      permission: 'dashboard',
    },
  ],
  operacional: [
    {
      path: '/crm',
      label: 'CRM',
      icon: Users,
      permission: 'crm',
      subItems: [
        { path: '/crm', label: 'Board', permission: 'crm' },
        { path: '/contacts', label: 'Todos Contatos', permission: 'crm' },
        { path: '/tags', label: 'Filtros & Tags', permission: 'crm' },
      ],
    },
    {
      path: '/campaigns',
      label: 'Campanhas',
      icon: Megaphone,
      permission: 'company',
      subItems: [
        { path: '/campaigns/whatsapp', label: 'WhatsApp', icon: MessageSquare, permission: 'company', isNew: true },
      ],
    },
    { path: '/chat', label: 'Chat Ao Vivo', icon: MessageSquare, permission: 'chat' },
    { path: '/calendar-config', label: 'Agenda', icon: Calendar, permission: 'company' },
  ],
  clientes: [
    {
      path: '/customers',
      label: 'Gestão',
      icon: Users,
      subItems: [
        { path: '/customers', label: 'Carteira', icon: Users, permission: 'crm' },
        { path: '/customers/invoices', label: 'Faturas', icon: Receipt, permission: 'crm' },
        { path: '/customers/plans', label: 'Planos', icon: Package, permission: 'crm' },
        { path: '/customers/revenue', label: 'Receita & Churn', icon: CreditCard, permission: 'crm' },
      ],
    },
  ],
  inteligencia: [
    {
      path: '/agents',
      label: 'Agentes',
      icon: Brain,
      permission: 'prompt',
      isNew: true,
    },
    { path: '/flows', label: 'Automações', icon: GitMerge, permission: 'prompt', isNew: true },
  ],
  conexoes: [
    { path: '/whatsapp', label: 'WhatsApp', icon: WhatsAppIcon, permission: 'whatsapp' },
    {
      path: '/integrations',
      label: 'Integrações',
      icon: Plug,
      permission: 'company',
      isNew: true,
    },
    { path: '/webhooks', label: 'Webhooks', icon: Webhook, isBeta: true, permission: 'prompt' },
  ],
  config: [
    { path: '/account/profile', label: 'Perfil da conta', icon: UserRound, permission: 'company', isNew: true },
    { path: '/company', label: 'Minha Empresa', icon: Building2, permission: 'company' },
    { path: '/company/ai-provider', label: 'Provedor de IA', icon: KeyRound, permission: 'company' },
    { path: '/config/midias', label: 'Canais & Origens', icon: Share2, isNew: true, permission: 'company' },
    { path: '/company/custom-fields', label: 'Campos Personalizados', icon: ClipboardCheck, permission: 'company' },
  ],
};

const PERMISSION_META: Record<Permission, { icon: LucideIcon; label: string }> = {
  dashboard: { icon: LayoutDashboard, label: 'Dashboard' },
  crm: { icon: Users, label: 'CRM' },
  chat: { icon: MessageSquare, label: 'Chat ao vivo' },
  whatsapp: { icon: WhatsAppIcon, label: 'WhatsApp' },
  'follow-up': { icon: ClipboardCheck, label: 'Follow-up' },
  prompt: { icon: Brain, label: 'Agentes e automações' },
  company: { icon: Building2, label: 'Configurações e gestão' },
};

const collectSubItems = (
  subItems: SubItem[] | undefined,
  moduleKey: ModuleKey,
  parentLabel: string,
  depth: number,
  groups: Map<Permission, SidebarPermissionGroup>,
) => {
  subItems?.forEach((subItem) => {
    if (subItem.permission) {
      addPermissionItem(groups, subItem.permission, {
        depth,
        icon: subItem.icon,
        isBeta: subItem.isBeta,
        isNew: subItem.isNew,
        label: subItem.label,
        moduleKey,
        moduleLabel: MODULE_META[moduleKey].label,
        parentLabel,
        path: subItem.path,
        type: 'submenu',
      });
    }

    collectSubItems(subItem.subItems, moduleKey, subItem.label, depth + 1, groups);
  });
};

const addPermissionItem = (
  groups: Map<Permission, SidebarPermissionGroup>,
  permission: Permission,
  item: SidebarPermissionItem,
) => {
  const meta = PERMISSION_META[permission];
  const current = groups.get(permission) || {
    icon: meta.icon,
    items: [],
    key: permission,
    label: meta.label,
    moduleLabels: [],
  };

  const itemKey = `${item.type}:${item.moduleKey}:${item.parentLabel || ''}:${item.path}:${item.label}`;
  const alreadyAdded = current.items.some(existing =>
    `${existing.type}:${existing.moduleKey}:${existing.parentLabel || ''}:${existing.path}:${existing.label}` === itemKey
  );

  if (!alreadyAdded) {
    current.items.push(item);
  }

  if (!current.moduleLabels.includes(item.moduleLabel)) {
    current.moduleLabels.push(item.moduleLabel);
  }

  groups.set(permission, current);
};

export const getSidebarPermissionGroups = (): SidebarPermissionGroup[] => {
  const groups = new Map<Permission, SidebarPermissionGroup>();

  Object.entries(SIDEBAR_MODULE_MENUS).forEach(([moduleKey, menuItems]) => {
    const typedModuleKey = moduleKey as ModuleKey;

    menuItems.forEach((item) => {
      if (item.permission) {
        addPermissionItem(groups, item.permission, {
          depth: 0,
          icon: item.icon,
          isBeta: item.isBeta,
          isNew: item.isNew,
          label: item.label,
          moduleKey: typedModuleKey,
          moduleLabel: MODULE_META[typedModuleKey].label,
          path: item.path,
          type: 'menu',
        });
      }

      collectSubItems(item.subItems, typedModuleKey, item.label, 1, groups);
    });
  });

  return Array.from(groups.values());
};

export const resolveActiveModule = (pathname: string): ModuleKey => {
  if (pathname.startsWith('/dashboard')) return 'dashboard';
  if (
    pathname.startsWith('/crm') ||
    pathname.startsWith('/contacts') ||
    pathname.startsWith('/campaigns') ||
    pathname.startsWith('/chat') ||
    pathname.startsWith('/calendar') ||
    pathname.startsWith('/tags')
  ) {
    return 'operacional';
  }
  if (pathname.startsWith('/customers')) return 'clientes';
  if (pathname.startsWith('/prompt/support-group')) return 'conexoes';
  if (pathname.startsWith('/agents') || pathname.startsWith('/prompt') || pathname.startsWith('/flows')) return 'inteligencia';
  if (pathname.startsWith('/whatsapp') || pathname.startsWith('/integrations') || pathname.startsWith('/webhooks')) return 'conexoes';
  if (pathname.startsWith('/account') || pathname.startsWith('/company') || pathname.startsWith('/config')) return 'config';

  return 'dashboard';
};
