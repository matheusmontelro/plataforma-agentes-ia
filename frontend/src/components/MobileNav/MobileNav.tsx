import React from 'react';
import { Link } from 'react-router-dom';
import { LogOut, type LucideIcon } from 'lucide-react';
import styles from './MobileNav.module.css';

interface MobileNavItemProps {
  icon: LucideIcon | React.FC<any>;
  label: string;
  isActive: boolean;
  path: string;
  status?: string;
}

export const MobileNavItem: React.FC<MobileNavItemProps> = ({
  icon: Icon,
  label,
  isActive,
  path,
  status
}) => {
  return (
    <Link
      to={path}
      className={`${styles.navItem} ${isActive ? styles.navItemActive : styles.navItemInactive}`}
      aria-current={isActive ? 'page' : undefined}
    >
      <div className={styles.iconContainer}>
        <Icon className={styles.icon} />
        {status === 'connected' && (
          <div className={styles.statusBadge} />
        )}
      </div>
      <span className={styles.label}>
        {label}
      </span>
    </Link>
  );
};

interface MobileNavProps {
  menuItems: {
    path: string;
    icon: LucideIcon | React.FC<any>;
    label: string;
    isActive: boolean;
    status?: string;
  }[];
  onLogout: () => void;
}

const MobileNav: React.FC<MobileNavProps> = ({ menuItems, onLogout }) => {
  return (
    <nav className={styles.navContainer} data-agentive-mobile-nav="true">
      <div className={styles.glassContainer}>
        {menuItems.map((item) => (
          <MobileNavItem
            key={item.path}
            icon={item.icon}
            label={item.label}
            isActive={item.isActive}
            path={item.path}
            status={item.status}
          />
        ))}
        <button
          type="button"
          onClick={onLogout}
          className={styles.logoutButton}
          aria-label="Sair da conta"
        >
          <LogOut className={styles.icon} />
          <span className={styles.label}>Sair</span>
        </button>
      </div>
    </nav>
  );
};

export default MobileNav;
