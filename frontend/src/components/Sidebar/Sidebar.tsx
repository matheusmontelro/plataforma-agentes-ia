import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronDown, ChevronRight, PanelLeftClose, PanelLeftOpen, Target, type LucideIcon } from 'lucide-react';
import NotificationTray from '../NotificationTray/NotificationTray';
import WorkspaceAccountNav from '../WorkspaceAccountNav/WorkspaceAccountNav';
import type { MenuItem, SubItem } from '../../services/permissionService';
import type { ModuleKey } from '../../config/sidebarNavigation';
import type { UserCompany } from '../../services/api';
import { branding } from '../../config/branding.ts';
import styles from './Sidebar.module.css';

interface ModuleItemProps {
  label: string;
  isActive: boolean;
  isExpanded: boolean;
  onClick: () => void;
}

const ModuleSectionToggle: React.FC<ModuleItemProps> = ({ label, isActive, isExpanded, onClick }) => {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={isExpanded}
      className={`${styles.navSectionTitle} ${styles.sectionToggle} ${isActive ? styles.sectionToggleActive : ''}`}
    >
      <span>{label}</span>
      <ChevronDown className={`${styles.sectionChevron} ${isExpanded ? '' : styles.sectionChevronCollapsed}`} />
    </button>
  );
};

interface SidebarMenuItemProps {
  icon: LucideIcon | React.FC<any>;
  label: string;
  isActive: boolean;
  path: string;
  hasSubItems?: boolean;
  isSubmenuOpen?: boolean;
  onToggle?: () => void;
}

const SidebarMenuItem: React.FC<SidebarMenuItemProps> = ({
  icon: Icon,
  label,
  isActive,
  path,
  hasSubItems,
  isSubmenuOpen,
  onToggle,
}) => {
  if (hasSubItems) {
    return (
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={isSubmenuOpen}
        className={`${styles.navItem} ${isActive ? styles.navItemActive : ''}`}
      >
        <div className={styles.navItemContent}>
          <Icon className={styles.navIcon} />
          <span className={styles.navItemLabel}>{label}</span>
          <ChevronRight className={`${styles.navChevron} ${isSubmenuOpen ? styles.navChevronOpen : ''}`} />
        </div>
      </button>
    );
  }

  return (
    <Link
      to={path}
      className={`${styles.navItem} ${isActive ? styles.navItemActive : ''}`}
      aria-current={isActive ? 'page' : undefined}
    >
      <Icon className={styles.navIcon} />
      <span className={styles.navItemLabel}>{label}</span>
    </Link>
  );
};

interface SidebarSubItemProps {
  label: string;
  path: string;
  isActive: boolean;
  icon?: LucideIcon | React.FC<any>;
}

const SidebarSubItem: React.FC<SidebarSubItemProps> = ({
  label,
  path,
  isActive,
  icon: Icon,
}) => {
  return (
    <Link
      to={path}
      aria-current={isActive ? 'page' : undefined}
      className={`${styles.navSubitem} ${isActive ? styles.navSubitemActive : ''}`}
    >
      {Icon ? <Icon className={styles.navSubitemIcon} /> : <span className={styles.navSubitemDot} />}
      <span className={styles.navSubitemLabel}>{label}</span>
    </Link>
  );
};

interface SidebarProps {
  isCollapsed: boolean;
  navigationModule: ModuleKey;
  onToggleCollapse: () => void;
  setActiveModule: (module: ModuleKey) => void;
  isManagedCustomerWorkspace: boolean;
  isDark: boolean;
  moduleMenus: Record<ModuleKey, MenuItem[]>;
  openSubmenu: string | null;
  setOpenSubmenu: (path: string | null) => void;
  isMenuEntryActive: (entry: MenuItem | SubItem, peerPaths: string[]) => boolean;
  isDrawerPathActive: (path: string, peerPaths?: string[]) => boolean;
  websocketMessage: any;
  companyId: string | null;
  companyLogoUrl: string | null;
  userCompanies: UserCompany[];
  setShowLogoutModal: (show: boolean) => void;
  handleSelectCompany: (id: number) => void;
  toggleTheme: () => void;
  userEmail: string;
  workspaceInitials: string;
  workspaceName: string;
  railItems: {
    icon: LucideIcon | React.FC<any>;
    label: string;
    moduleKey: ModuleKey;
    hidden?: boolean;
  }[];
}

const Sidebar: React.FC<SidebarProps> = ({
  isCollapsed,
  navigationModule,
  onToggleCollapse,
  setActiveModule,
  isDark,
  moduleMenus,
  openSubmenu,
  setOpenSubmenu,
  isMenuEntryActive,
  isDrawerPathActive,
  websocketMessage,
  companyId,
  companyLogoUrl,
  userCompanies,
  setShowLogoutModal,
  handleSelectCompany,
  toggleTheme,
  userEmail,
  workspaceInitials,
  workspaceName,
  railItems,
}) => {
  const [expandedModules, setExpandedModules] = useState<Set<ModuleKey>>(
    () => new Set(railItems.map((item) => item.moduleKey)),
  );
  const [isActivityExpanded, setIsActivityExpanded] = useState(true);
  const visibleRailItems = railItems.filter((item) => !item.hidden);

  useEffect(() => {
    setExpandedModules((current) => {
      if (current.has(navigationModule)) return current;
      const next = new Set(current);
      next.add(navigationModule);
      return next;
    });
  }, [navigationModule]);

  const fullLogoSrc = isDark
    ? branding.assets.logoDark
    : branding.assets.logoLight;
  const faviconSrc = isDark
    ? branding.assets.iconWhite
    : branding.assets.icon;

  const toggleModule = (moduleKey: ModuleKey) => {
    setActiveModule(moduleKey);
    setExpandedModules((current) => {
      const next = new Set(current);
      if (next.has(moduleKey)) {
        next.delete(moduleKey);
      } else {
        next.add(moduleKey);
      }
      return next;
    });
  };

  return (
    <aside className={`${styles.sidebar} ${isCollapsed ? styles.sidebarCollapsed : ''}`} aria-label="Navegação principal">
      <div className={styles.sidebarHeader}>
        <Link to="/dashboard" className={styles.logoContainer} aria-label="Voltar para o dashboard">
          {isCollapsed ? (
            <img
              alt={branding.appName}
              className={styles.logoFavicon}
              src={faviconSrc}
            />
          ) : (
            <span className={styles.logoExpanded}>
              <img
                alt={branding.appName}
                className={styles.logoFull}
                src={fullLogoSrc}
              />
            </span>
          )}
        </Link>
        <button
          type="button"
          aria-label={isCollapsed ? 'Expandir sidebar' : 'Minimizar sidebar'}
          className={styles.collapseBtn}
          onClick={onToggleCollapse}
        >
          {isCollapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
        </button>
      </div>

      <div className={styles.sidebarNavContainer}>
        {isCollapsed ? (
          <nav className={styles.collapsedNav} aria-label="Módulos compactos">
            {visibleRailItems.map((item) => {
              const Icon = item.icon;
              const menuItems = moduleMenus[item.moduleKey] || [];
              const peerPaths = menuItems.map((menuItem) => menuItem.path);
              const hasActiveChild = menuItems.some((menuItem) => isMenuEntryActive(menuItem, peerPaths));
              const isModuleActive = navigationModule === item.moduleKey || hasActiveChild;

              return (
                <button
                  type="button"
                  aria-label={item.label}
                  className={`${styles.collapsedNavItem} ${isModuleActive ? styles.collapsedNavItemActive : ''}`}
                  key={item.moduleKey}
                  onClick={() => {
                    setActiveModule(item.moduleKey);
                    onToggleCollapse();
                  }}
                  title={item.label}
                >
                  <Icon className={styles.navIcon} />
                </button>
              );
            })}
          </nav>
        ) : (
          <section className={styles.navSection}>
            <nav className={styles.navList} aria-label="Módulos">
              {visibleRailItems.map((item) => {
                const menuItems = moduleMenus[item.moduleKey] || [];
                const peerPaths = menuItems.map((menuItem) => menuItem.path);
                const isExpanded = expandedModules.has(item.moduleKey);
                const hasActiveChild = menuItems.some((menuItem) => isMenuEntryActive(menuItem, peerPaths));
                const isModuleActive = navigationModule === item.moduleKey || hasActiveChild;

                return (
                  <div className={styles.moduleGroup} key={item.moduleKey}>
                    <ModuleSectionToggle
                      label={item.label}
                      isActive={isModuleActive}
                      isExpanded={isExpanded}
                      onClick={() => toggleModule(item.moduleKey)}
                    />
                    {isExpanded && menuItems.length > 0 && (
                      <div className={styles.moduleMenu}>
                        {menuItems.map((menuItem) => {
                          const hasSubItems = !!menuItem.subItems && menuItem.subItems.length > 0;
                          const isOpen = openSubmenu === menuItem.path;
                          const isActive = hasSubItems
                            ? isMenuEntryActive(menuItem, peerPaths)
                            : isDrawerPathActive(menuItem.path, peerPaths);

                          return (
                            <div className={styles.navGroup} key={menuItem.path}>
                              <SidebarMenuItem
                                icon={menuItem.icon || Target}
                                label={menuItem.label}
                                isActive={isActive}
                                path={menuItem.path}
                                hasSubItems={hasSubItems}
                                isSubmenuOpen={isOpen}
                                onToggle={hasSubItems ? () => {
                                  setActiveModule(item.moduleKey);
                                  setOpenSubmenu(isOpen ? null : menuItem.path);
                                } : undefined}
                              />
                              {hasSubItems && isOpen && (
                                <div className={styles.navSublist}>
                                  {menuItem.subItems?.map((subItem) => (
                                    <SidebarSubItem
                                      key={subItem.path}
                                      label={subItem.label}
                                      path={subItem.path}
                                      isActive={isMenuEntryActive(subItem, menuItem.subItems?.map((peer) => peer.path) || [])}
                                      icon={subItem.icon}
                                    />
                                  ))}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </nav>
          </section>
        )}
      </div>

      {!isCollapsed && <div className={styles.sidebarFooter}>
        <section className={styles.footerSection}>
          <ModuleSectionToggle
            label="Atividade"
            isActive={false}
            isExpanded={isActivityExpanded}
            onClick={() => setIsActivityExpanded((current) => !current)}
          />
          {isActivityExpanded && (
            <NotificationTray isCollapsed={false} websocketMessage={websocketMessage} />
          )}
        </section>

        <div className={styles.userProfile}>
          <WorkspaceAccountNav
            activeCompanyId={companyId}
            companyLogoUrl={companyLogoUrl}
            companies={userCompanies}
            isDark={isDark}
            onLogout={() => setShowLogoutModal(true)}
            onSelectCompany={handleSelectCompany}
            onThemeToggle={toggleTheme}
            userEmail={userEmail}
            workspaceInitials={workspaceInitials}
            workspaceName={workspaceName}
          />
        </div>
      </div>}
    </aside>
  );
};

export default Sidebar;
