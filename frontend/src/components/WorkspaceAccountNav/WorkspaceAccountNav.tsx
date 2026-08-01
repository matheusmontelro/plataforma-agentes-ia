import React from 'react';
import { useNavigate } from 'react-router-dom';
import { KeyRound, MoreVertical, Check, Sun, Moon, LogOut } from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu';
import {
  Avatar,
  AvatarFallback,
  AvatarImage,
} from '../ui/avatar';
import type { UserCompany } from '../../services/api';
import styles from './WorkspaceAccountNav.module.css';

interface WorkspaceAccountNavProps {
  companyLogoUrl: string | null;
  companies: UserCompany[];
  isDark: boolean;
  onLogout: () => void;
  onSelectCompany: (id: number) => void;
  onThemeToggle: () => void;
  userEmail: string;
  workspaceInitials: string;
  workspaceName: string;
  activeCompanyId: string | null;
}

export const getInitials = (name: string) => {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const initials = parts.slice(0, 2).map(part => part[0]).join('');
  return (initials || 'A').toUpperCase();
};

const WorkspaceAccountNav: React.FC<WorkspaceAccountNavProps> = ({
  companyLogoUrl,
  companies,
  isDark,
  onLogout,
  onSelectCompany,
  onThemeToggle,
  userEmail,
  workspaceInitials,
  workspaceName,
  activeCompanyId,
}) => {
  const hasCompanies = companies.length > 0;
  const navigate = useNavigate();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button type="button" className={styles.triggerButton}>
          <Avatar className={styles.avatar}>
            <AvatarImage src={companyLogoUrl || undefined} alt={workspaceName} />
            <AvatarFallback className={styles.avatarFallback}>
              {workspaceInitials}
            </AvatarFallback>
          </Avatar>
          <div className={styles.userInfo}>
            <p className={styles.userName}>
              {workspaceName}
            </p>
            <p className={styles.userEmail}>
              {userEmail}
            </p>
          </div>
          <MoreVertical className={styles.moreIcon} />
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent
        align="start"
        side="top"
        sideOffset={10}
        className={styles.dropdownContent}
      >
        <div className={styles.dropdownHeader}>
          Trocar empresa
        </div>

        <DropdownMenuGroup className={styles.companiesGroup}>
          {hasCompanies ? companies.map((company) => {
            const isActiveCompany = company.company_id.toString() === activeCompanyId;
            const companyName = company.name_company || `Empresa ${company.company_id}`;
            const companyLogo = company.logo_url?.trim() || (isActiveCompany ? companyLogoUrl : null);

            return (
              <DropdownMenuItem
                key={company.company_id}
                onClick={() => onSelectCompany(company.company_id)}
                className={`${styles.companyItem} ${isActiveCompany ? styles.companyItemActive : styles.companyItemInactive}`}
              >
                <Avatar className={`${styles.companyAvatar} ${isActiveCompany ? styles.companyAvatarActive : styles.companyAvatarInactive}`}>
                  <AvatarImage src={companyLogo || undefined} alt={companyName} />
                  <AvatarFallback className={`${styles.companyAvatarFallback} ${isActiveCompany ? styles.fallbackActive : styles.fallbackInactive}`}>
                    {getInitials(companyName)}
                  </AvatarFallback>
                </Avatar>
                <span className={styles.companyInfo}>
                  <span className={styles.companyName}>{companyName}</span>
                </span>
                {isActiveCompany && <Check className={styles.activeCheck} />}
              </DropdownMenuItem>
            );
          }) : (
            <div className={styles.noCompanies}>
              Nenhuma empresa disponível
            </div>
          )}
        </DropdownMenuGroup>

        <DropdownMenuSeparator className={styles.separator} />

        <DropdownMenuItem
          onClick={() => navigate('/company/ai-provider')}
          className={styles.menuItem}
        >
          <span className={styles.menuItemIconWrapper}>
            <KeyRound className="h-4 w-4" />
          </span>
          <span className={styles.menuItemText}>Provedor de IA</span>
        </DropdownMenuItem>

        <DropdownMenuItem
          onClick={onThemeToggle}
          className={styles.menuItem}
        >
          <span className={styles.menuItemIconWrapper}>
            {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </span>
          <span className={styles.menuItemText}>Alternar tema</span>
        </DropdownMenuItem>

        <DropdownMenuItem
          onClick={onLogout}
          className={`${styles.menuItem} ${styles.menuItemLogout}`}
        >
          <span className={`${styles.menuItemIconWrapper} ${styles.iconLogout}`}>
            <LogOut className="h-4 w-4" />
          </span>
          <span className={styles.menuItemText}>Sair</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

export default WorkspaceAccountNav;
