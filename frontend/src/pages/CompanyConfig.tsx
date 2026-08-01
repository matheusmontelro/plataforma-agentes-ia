import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  Building2,
  Camera,
  Check,
  ChevronDown,
  Circle,
  Eye,
  EyeOff,
  Key,
  Loader2,
  MoreVertical,
  Pencil,
  Plus,
  Search,
  Shield,
  Trash2,
  UserCheck,
  Users,
  X,
} from 'lucide-react';
import api, {
  changeUserPassword,
  createUser,
  deleteUser,
  getCompanyInfo,
  getTeams,
  listUsers,
  Team,
  updateUser,
  User,
  UserCreate,
  UserUpdate,
} from '../services/api';
import TeamsManagement from '../components/TeamsManagement.tsx';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AgentiveAlert,
  AgentiveConfirmModal,
  AgentiveEmptyState,
  agentiveIconButtonClass,
  agentiveInputClass,
  agentiveLabelClass,
  agentivePageClass,
  agentivePanelClass,
  agentivePillClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';

type CompanyTab = 'overview' | 'users' | 'teams';
type UserDialogMode = 'create' | 'edit' | 'password';

interface UserFormData {
  name: string;
  email: string;
  role: string;
  team_id?: number;
  password: string;
  confirmPassword: string;
}

interface DialogProps {
  children: React.ReactNode;
  description?: string;
  footer: React.ReactNode;
  icon: React.ComponentType<{ className?: string }>;
  onClose: () => void;
  open: boolean;
  title: string;
}

interface InputFieldProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label: string;
  suffix?: React.ReactNode;
}

interface SelectFieldProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  children: React.ReactNode;
}

interface DropdownMenuProps {
  trigger: React.ReactNode;
  children: React.ReactNode;
}

interface DropdownItemProps {
  children: React.ReactNode;
  destructive?: boolean;
  icon: React.ReactNode;
  onClick: () => void;
}

const emptyUserForm: UserFormData = {
  name: '',
  email: '',
  role: 'staff',
  password: '',
  confirmPassword: '',
};

const tabs: Array<{
  id: CompanyTab;
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
}> = [
  { id: 'overview', label: 'Visão geral', description: 'Empresa', icon: Building2 },
  { id: 'users', label: 'Usuários', description: 'Acessos', icon: Users },
  { id: 'teams', label: 'Equipes', description: 'Permissões', icon: Shield },
];

const getInitials = (name: string) => {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return (parts.slice(0, 2).map(part => part[0]).join('') || 'A').toUpperCase();
};

const getRoleLabel = (role: string) => {
  const labels: Record<string, string> = {
    admin: 'Administrador',
    manager: 'Gestor',
    master: 'Master',
    staff: 'Funcionário',
  };

  return labels[role] || role;
};

const getErrorMessage = (error: unknown, fallback: string) => {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
};

const Dialog: React.FC<DialogProps> = ({
  children,
  description,
  footer,
  icon: Icon,
  onClose,
  open,
  title,
}) => {
  const { isDark } = useTheme();

  if (!open || typeof document === 'undefined') return null;

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="Fechar modal"
        className="fixed inset-0 cursor-default bg-brand/55 backdrop-blur-sm"
        onClick={onClose}
      />
      <div
        className={`relative z-[10000] flex max-h-[92vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border shadow-[0_24px_70px_rgba(2,3,35,0.28)] ${
          isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand'
        }`}
      >
        <div className={`flex items-start justify-between gap-4 border-b p-5 ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
          <div className="flex min-w-0 items-start gap-3">
            <div className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
              <Icon className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h2 className="text-lg font-semibold leading-tight">{title}</h2>
              {description && (
                <p className={`mt-1 text-sm ${isDark ? 'text-white/55' : 'text-brand/55'}`}>
                  {description}
                </p>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className={agentiveIconButtonClass(isDark)}
            aria-label="Fechar"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="overflow-y-auto p-5">{children}</div>
        <div className={`flex flex-col-reverse gap-2 border-t p-5 sm:flex-row sm:justify-end ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
          {footer}
        </div>
      </div>
    </div>,
    document.body
  );
};

const InputField: React.FC<InputFieldProps> = ({ label, className = '', suffix, ...props }) => {
  const { isDark } = useTheme();

  return (
    <label className="block">
      <span className={agentiveLabelClass(isDark)}>{label}</span>
      <div className="relative">
        <input
          className={agentiveInputClass(isDark, suffix ? `pr-12 ${className}` : className)}
          {...props}
        />
        {suffix}
      </div>
    </label>
  );
};

const SelectField: React.FC<SelectFieldProps> = ({ label, children, className = '', ...props }) => {
  const { isDark } = useTheme();

  return (
    <label className="block">
      <span className={agentiveLabelClass(isDark)}>{label}</span>
      <div className="relative">
        <select
          className={agentiveInputClass(isDark, `appearance-none pr-10 ${className}`)}
          {...props}
        >
          {children}
        </select>
        <ChevronDown className={`pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 ${isDark ? 'text-white/45' : 'text-brand/45'}`} />
      </div>
    </label>
  );
};

const DropdownMenu: React.FC<DropdownMenuProps> = ({ trigger, children }) => {
  const { isDark } = useTheme();
  const [isOpen, setIsOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const triggerRef = useRef<HTMLDivElement>(null);

  const handleToggle = () => {
    if (!isOpen && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setPosition({
        top: rect.bottom + 8,
        left: Math.max(12, rect.right - 224),
      });
    }
    setIsOpen(prev => !prev);
  };

  return (
    <>
      <div ref={triggerRef} className="inline-flex">
        <div onClick={handleToggle}>{trigger}</div>
      </div>
      {isOpen && typeof document !== 'undefined' && createPortal(
        <>
          <button
            type="button"
            aria-label="Fechar menu"
            className="fixed inset-0 z-[9997] cursor-default"
            onClick={() => setIsOpen(false)}
          />
          <div
            className={`fixed z-[9998] w-56 rounded-2xl border p-1.5 shadow-[0_22px_55px_rgba(2,3,35,0.18)] ${
              isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand'
            }`}
            style={{ top: `${position.top}px`, left: `${position.left}px` }}
            role="menu"
            onClick={() => setIsOpen(false)}
          >
            {children}
          </div>
        </>,
        document.body
      )}
    </>
  );
};

const DropdownItem: React.FC<DropdownItemProps> = ({
  children,
  destructive,
  icon,
  onClick,
}) => {
  const { isDark } = useTheme();

  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm font-medium transition-colors ${
        destructive
          ? 'text-red-500 hover:bg-red-500/10'
          : isDark
            ? 'text-white/70 hover:bg-white/10 hover:text-white'
            : 'text-brand/70 hover:bg-brand-canvas hover:text-brand'
      }`}
    >
      <span className="grid h-7 w-7 place-items-center rounded-lg bg-current/10">{icon}</span>
      <span>{children}</span>
    </button>
  );
};

const CompanyConfig: React.FC = () => {
  const { isDark } = useTheme();

  const [currentTab, setCurrentTab] = useState<CompanyTab>('users');
  const [nameCompany, setNameCompany] = useState('');
  const [logoUrl, setLogoUrl] = useState<string | null>(null);
  const [companyLogo, setCompanyLogo] = useState<File | null>(null);
  const [logoPreviewUrl, setLogoPreviewUrl] = useState<string | null>(null);
  const [isCompanyEditing, setIsCompanyEditing] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isSavingCompany, setIsSavingCompany] = useState(false);
  const [originalName, setOriginalName] = useState('');
  const [originalLogoUrl, setOriginalLogoUrl] = useState<string | null>(null);

  const [users, setUsers] = useState<User[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [teamFilter, setTeamFilter] = useState('all');
  const [showUserDialog, setShowUserDialog] = useState(false);
  const [dialogMode, setDialogMode] = useState<UserDialogMode>('create');
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [userToDelete, setUserToDelete] = useState<User | null>(null);
  const [isSavingUser, setIsSavingUser] = useState(false);
  const [isDeletingUser, setIsDeletingUser] = useState(false);
  const [userForm, setUserForm] = useState<UserFormData>(emptyUserForm);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const storedCompanyId = Number(localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  const companyId = Number.isInteger(storedCompanyId) && storedCompanyId > 0 ? storedCompanyId : null;

  useEffect(() => {
    fetchInitialData();
  }, []);

  useEffect(() => {
    if (!companyLogo) {
      setLogoPreviewUrl(null);
      return;
    }

    const previewUrl = URL.createObjectURL(companyLogo);
    setLogoPreviewUrl(previewUrl);

    return () => URL.revokeObjectURL(previewUrl);
  }, [companyLogo]);

  const currentLogoSrc = logoPreviewUrl || logoUrl;
  const workspaceName = nameCompany.trim() || 'Minha Empresa';
  const workspaceInitials = getInitials(workspaceName);

  const activeUsers = useMemo(() => users.filter(user => user.is_active), [users]);
  const unassignedUsers = useMemo(() => users.filter(user => !user.team_id && !user.team), [users]);
  const teamsWithPermissions = useMemo(() => {
    return teams.filter(team =>
      (team.sidebar_permissions?.length || 0) > 0 ||
      Boolean(team.contact_permissions?.include_outside_crm) ||
      (team.contact_permissions?.pipeline_stage_ids?.length || 0) > 0
    );
  }, [teams]);

  const filteredUsers = useMemo(() => {
    const normalizedSearch = searchTerm.trim().toLowerCase();

    return users.filter(user => {
      const teamName = user.team?.name || teams.find(team => team.id === user.team_id)?.name || '';
      const matchesSearch = !normalizedSearch ||
        user.name.toLowerCase().includes(normalizedSearch) ||
        user.email.toLowerCase().includes(normalizedSearch) ||
        teamName.toLowerCase().includes(normalizedSearch);
      const matchesTeam =
        teamFilter === 'all' ||
        (teamFilter === 'unassigned' && !user.team_id && !user.team) ||
        user.team_id?.toString() === teamFilter ||
        user.team?.id.toString() === teamFilter;

      return matchesSearch && matchesTeam;
    });
  }, [searchTerm, teamFilter, teams, users]);

  const completionItems = [
    Boolean(nameCompany.trim()),
    Boolean(currentLogoSrc),
    users.length > 0,
    teams.length > 0,
  ];
  const completionScore = completionItems.filter(Boolean).length;

  async function fetchInitialData() {
    setIsLoading(true);
    setError(null);

    try {
      await Promise.all([fetchCompanyData(), refreshOrganizationData()]);
    } catch (fetchError) {
      setError(getErrorMessage(fetchError, 'Não foi possível carregar a configuração da empresa.'));
    } finally {
      setIsLoading(false);
    }
  }

  async function fetchCompanyData() {
    const info = await getCompanyInfo();
    const companyName = info.name_company || info.name || '';
    const companyLogoUrl = info.logo_url || null;

    setNameCompany(companyName);
    setLogoUrl(companyLogoUrl);
    setOriginalName(companyName);
    setOriginalLogoUrl(companyLogoUrl);
    setIsCompanyEditing(!companyName && !companyLogoUrl);
  }

  async function refreshOrganizationData() {
    if (!companyId) {
      throw new Error('Selecione uma empresa válida antes de carregar usuários.');
    }

    const [usersData, teamsData] = await Promise.all([
      listUsers(companyId),
      getTeams(),
    ]);
    setUsers(usersData);
    setTeams(teamsData);
  }

  const handleCompanySave = async () => {
    if (!nameCompany.trim()) return;

    setIsSavingCompany(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append('name_company', nameCompany.trim());
      if (companyLogo) formData.append('logo', companyLogo);

      const response = await api.put('/api/company', formData);
      const nextLogoUrl = response.data.logoUrl || response.data.logo_url || logoUrl;

      setLogoUrl(nextLogoUrl);
      setOriginalName(nameCompany.trim());
      setOriginalLogoUrl(nextLogoUrl);
      setCompanyLogo(null);
      setIsCompanyEditing(false);
      setSuccessMessage('Empresa atualizada com sucesso.');
    } catch (saveError) {
      setError(getErrorMessage(saveError, 'Não foi possível atualizar a empresa.'));
    } finally {
      setIsSavingCompany(false);
    }
  };

  const handleCancelCompanyEdit = () => {
    setNameCompany(originalName);
    setLogoUrl(originalLogoUrl);
    setCompanyLogo(null);
    setIsCompanyEditing(false);
  };

  const resetUserForm = () => {
    setUserForm(emptyUserForm);
    setSelectedUser(null);
    setShowPassword(false);
    setShowConfirmPassword(false);
  };

  const openCreateUserDialog = () => {
    resetUserForm();
    setDialogMode('create');
    setShowUserDialog(true);
  };

  const openEditUserDialog = (user: User) => {
    setSelectedUser(user);
    setUserForm({
      name: user.name,
      email: user.email,
      role: user.role,
      team_id: user.team_id,
      password: '',
      confirmPassword: '',
    });
    setDialogMode('edit');
    setShowUserDialog(true);
  };

  const openPasswordDialog = (user: User) => {
    setSelectedUser(user);
    setUserForm({
      ...emptyUserForm,
      name: user.name,
      email: user.email,
      role: user.role,
      team_id: user.team_id,
    });
    setDialogMode('password');
    setShowUserDialog(true);
  };

  const closeUserDialog = () => {
    setShowUserDialog(false);
    resetUserForm();
  };

  const handleUserSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    if (dialogMode === 'create' && !companyId) {
      setError('Selecione uma empresa válida antes de criar um usuário.');
      return;
    }

    if ((dialogMode === 'create' || dialogMode === 'password') && userForm.password !== userForm.confirmPassword) {
      setError('As senhas não conferem.');
      return;
    }

    setIsSavingUser(true);
    setError(null);

    try {
      if (dialogMode === 'create') {
        const payload: UserCreate = {
          name: userForm.name.trim(),
          email: userForm.email.trim(),
          password: userForm.password,
          confirm_password: userForm.confirmPassword,
          role: userForm.role,
          company_id: companyId,
          team_id: userForm.team_id,
        };
        await createUser(payload);
        setSuccessMessage('Usuário criado com sucesso.');
      }

      if (dialogMode === 'edit' && selectedUser) {
        const payload: UserUpdate = {
          name: userForm.name.trim(),
          email: userForm.email.trim(),
          role: userForm.role,
          team_id: userForm.team_id,
        };
        await updateUser(selectedUser.id, payload);
        setSuccessMessage('Usuário atualizado com sucesso.');
      }

      if (dialogMode === 'password' && selectedUser) {
        await changeUserPassword(selectedUser.id, userForm.password, userForm.confirmPassword);
        setSuccessMessage('Senha atualizada com sucesso.');
      }

      await refreshOrganizationData();
      closeUserDialog();
    } catch (submitError) {
      setError(getErrorMessage(submitError, 'Não foi possível salvar o usuário.'));
    } finally {
      setIsSavingUser(false);
    }
  };

  const confirmDeleteUser = async () => {
    if (!userToDelete) return;

    setIsDeletingUser(true);
    setError(null);

    try {
      await deleteUser(userToDelete.id);
      await refreshOrganizationData();
      setUserToDelete(null);
      setSuccessMessage('Usuário excluído com sucesso.');
    } catch (deleteError) {
      setError(getErrorMessage(deleteError, 'Não foi possível excluir o usuário.'));
    } finally {
      setIsDeletingUser(false);
    }
  };

  const getTeamName = (user: User) => {
    return user.team?.name || teams.find(team => team.id === user.team_id)?.name || null;
  };

  const userDialogTitle =
    dialogMode === 'create'
      ? 'Novo usuário'
      : dialogMode === 'edit'
        ? 'Editar usuário'
        : 'Alterar senha';

  const userDialogDescription =
    dialogMode === 'create'
      ? 'Defina acesso, equipe e credenciais iniciais.'
      : dialogMode === 'edit'
        ? 'Atualize dados de acesso e vínculo de equipe.'
        : selectedUser?.name || 'Atualize a credencial do usuário.';

  if (isLoading) {
    return (
      <div className={`flex min-h-screen items-center justify-center ${isDark ? 'bg-brand text-white' : 'bg-brand-canvas text-brand'}`}>
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-10 w-10 animate-spin" />
          <p className={`text-sm font-medium ${isDark ? 'text-white/60' : 'text-brand/60'}`}>
            Carregando configurações...
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className={agentivePageClass(isDark, 'px-4 pb-28 pt-4 sm:px-6 lg:px-8 xl:px-10')}>
      <div className="mx-auto max-w-screen-2xl space-y-5">
        <header className={agentivePanelClass(isDark, 'overflow-hidden')}>
          <div className="grid gap-5 p-5 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-end">
            <div className="flex min-w-0 flex-col gap-4 sm:flex-row sm:items-center">
              <div className="relative h-16 w-16 shrink-0">
                {currentLogoSrc ? (
                  <img
                    src={currentLogoSrc}
                    alt={workspaceName}
                    className="h-16 w-16 rounded-2xl object-cover ring-1 ring-brand/10"
                  />
                ) : (
                  <div className="grid h-16 w-16 place-items-center rounded-2xl bg-brand text-xl font-semibold text-white">
                    {workspaceInitials}
                  </div>
                )}
                {isCompanyEditing && (
                  <label className="absolute inset-0 grid cursor-pointer place-items-center rounded-2xl bg-brand/60 text-white opacity-0 transition hover:opacity-100">
                    <Camera className="h-5 w-5" />
                    <input
                      type="file"
                      className="hidden"
                      accept="image/*"
                      onChange={event => setCompanyLogo(event.target.files?.[0] || null)}
                    />
                  </label>
                )}
              </div>

              <div className="min-w-0 flex-1">
                <div className={`mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] ${isDark ? 'text-white/40' : 'text-brand/40'}`}>
                  Configurações
                </div>
                {isCompanyEditing ? (
                  <input
                    type="text"
                    value={nameCompany}
                    onChange={event => setNameCompany(event.target.value)}
                    className={agentiveInputClass(isDark, 'max-w-xl px-3 py-2 text-xl font-semibold sm:text-2xl')}
                    placeholder="Nome da empresa"
                  />
                ) : (
                  <h1 className="truncate text-2xl font-semibold tracking-tight sm:text-3xl">{workspaceName}</h1>
                )}
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
                    <Circle className="h-2.5 w-2.5 fill-emerald-500 text-emerald-500" />
                    Sistema ativo
                  </span>
                  <span className={agentivePillClass(isDark)}>
                    {users.length} usuários
                  </span>
                  <span className={agentivePillClass(isDark)}>
                    {teams.length} equipes
                  </span>
                </div>
              </div>
            </div>

            <div className="flex flex-col gap-2 sm:flex-row xl:justify-end">
              {isCompanyEditing ? (
                <>
                  <button
                    type="button"
                    onClick={handleCancelCompanyEdit}
                    disabled={isSavingCompany}
                    className={agentiveSecondaryButtonClass(isDark)}
                  >
                    <X className="h-4 w-4" />
                    Cancelar
                  </button>
                  <button
                    type="button"
                    onClick={handleCompanySave}
                    disabled={isSavingCompany || !nameCompany.trim()}
                    className={agentivePrimaryButtonClass()}
                  >
                    {isSavingCompany ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                    Salvar empresa
                  </button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => setIsCompanyEditing(true)}
                    className={agentiveSecondaryButtonClass(isDark)}
                  >
                    <Pencil className="h-4 w-4" />
                    Editar empresa
                  </button>
                  <button
                    type="button"
                    onClick={openCreateUserDialog}
                    className={agentivePrimaryButtonClass()}
                  >
                    <Plus className="h-4 w-4" />
                    Novo usuário
                  </button>
                </>
              )}
            </div>
          </div>

          <div className={`grid gap-3 border-t p-4 sm:grid-cols-2 xl:grid-cols-4 ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
            {[
              { label: 'Usuários ativos', value: activeUsers.length, icon: UserCheck },
              { label: 'Equipes criadas', value: teams.length, icon: Shield },
              { label: 'Sem equipe', value: unassignedUsers.length, icon: Users },
              { label: 'Setup da conta', value: `${completionScore}/4`, icon: Building2 },
            ].map(item => {
              const Icon = item.icon;
              return (
                <div
                  key={item.label}
                  className={`rounded-2xl border px-4 py-3 ${isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas'}`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className={`text-sm font-medium ${isDark ? 'text-white/55' : 'text-brand/55'}`}>{item.label}</span>
                    <Icon className={`h-4 w-4 ${isDark ? 'text-white/45' : 'text-brand/45'}`} />
                  </div>
                  <div className="mt-2 text-2xl font-semibold leading-none">{item.value}</div>
                </div>
              );
            })}
          </div>
        </header>

        {error && (
          <AgentiveAlert variant="error" title="Não foi possível concluir a ação" onClose={() => setError(null)}>
            {error}
          </AgentiveAlert>
        )}

        {successMessage && (
          <AgentiveAlert variant="success" title="Atualização concluída" onClose={() => setSuccessMessage(null)}>
            {successMessage}
          </AgentiveAlert>
        )}

        <div className={`grid gap-1 rounded-2xl border p-1.5 lg:w-[680px] ${isDark ? 'border-white/10 bg-black/15' : 'border-brand/10 bg-white'}`} style={{ gridTemplateColumns: `repeat(${tabs.length}, minmax(0, 1fr))` }}>
          {tabs.map(tab => {
            const Icon = tab.icon;
            const isActive = currentTab === tab.id;

            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setCurrentTab(tab.id)}
                className={`group flex min-w-0 items-center gap-2 rounded-xl border px-2 py-2 text-left transition-all duration-200 sm:px-3 ${
                  isActive
                    ? isDark
                      ? 'border-white bg-white text-brand shadow-[0_10px_24px_rgba(255,255,255,0.08)]'
                      : 'border-brand bg-brand text-white shadow-[0_10px_24px_rgba(2,3,35,0.12)]'
                    : isDark
                      ? 'border-transparent text-white/55 hover:border-white/10 hover:bg-white/[0.06] hover:text-white'
                      : 'border-transparent text-brand/55 hover:border-brand/10 hover:bg-brand-canvas hover:text-brand'
                }`}
              >
                <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors ${
                  isActive
                    ? isDark
                      ? 'bg-brand text-white'
                      : 'bg-white text-brand'
                    : isDark
                      ? 'bg-white/10 text-white/55 group-hover:text-white'
                      : 'bg-brand-canvas text-brand/50 group-hover:text-brand'
                }`}>
                  <Icon className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-xs font-semibold sm:text-sm">{tab.label}</span>
                  <span className={`hidden truncate text-[10px] leading-tight sm:block ${
                    isActive
                      ? isDark ? 'text-brand/55' : 'text-white/60'
                      : isDark ? 'text-white/35' : 'text-brand/35'
                  }`}>
                    {tab.description}
                  </span>
                </span>
              </button>
            );
          })}
        </div>

        {currentTab === 'overview' && (
          <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
            <div className={agentivePanelClass(isDark, 'p-5')}>
              <div className="mb-5 flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold">Perfil da empresa</h2>
                  <p className={`text-sm ${isDark ? 'text-white/55' : 'text-brand/55'}`}>Identidade usada no workspace e nas áreas administrativas.</p>
                </div>
                <Building2 className={`h-5 w-5 ${isDark ? 'text-white/45' : 'text-brand/45'}`} />
              </div>

              <div className={`grid gap-4 rounded-2xl border p-4 sm:grid-cols-2 ${isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas'}`}>
                <div>
                  <p className={`text-xs font-semibold uppercase tracking-[0.12em] ${isDark ? 'text-white/40' : 'text-brand/40'}`}>Nome</p>
                  <p className="mt-1 text-sm font-semibold">{workspaceName}</p>
                </div>
                <div>
                  <p className={`text-xs font-semibold uppercase tracking-[0.12em] ${isDark ? 'text-white/40' : 'text-brand/40'}`}>Logo</p>
                  <p className="mt-1 text-sm font-semibold">{currentLogoSrc ? 'Configurado' : 'Pendente'}</p>
                </div>
                <div>
                  <p className={`text-xs font-semibold uppercase tracking-[0.12em] ${isDark ? 'text-white/40' : 'text-brand/40'}`}>Usuários</p>
                  <p className="mt-1 text-sm font-semibold">{users.length}</p>
                </div>
                <div>
                  <p className={`text-xs font-semibold uppercase tracking-[0.12em] ${isDark ? 'text-white/40' : 'text-brand/40'}`}>Equipes</p>
                  <p className="mt-1 text-sm font-semibold">{teams.length}</p>
                </div>
              </div>
            </div>

            <div className={agentivePanelClass(isDark, 'p-5')}>
              <h2 className="text-lg font-semibold">Distribuição</h2>
              <div className="mt-5 space-y-4">
                <div>
                  <div className="mb-2 flex justify-between text-sm">
                    <span className={isDark ? 'text-white/55' : 'text-brand/55'}>Usuários em equipes</span>
                    <span className="font-semibold">{users.length - unassignedUsers.length}/{users.length}</span>
                  </div>
                  <div className={`h-2 overflow-hidden rounded-full ${isDark ? 'bg-white/10' : 'bg-brand/10'}`}>
                    <div
                      className={`h-full rounded-full ${isDark ? 'bg-white' : 'bg-brand'}`}
                      style={{ width: users.length ? `${((users.length - unassignedUsers.length) / users.length) * 100}%` : '0%' }}
                    />
                  </div>
                </div>
                <div>
                  <div className="mb-2 flex justify-between text-sm">
                    <span className={isDark ? 'text-white/55' : 'text-brand/55'}>Equipes com permissões</span>
                    <span className="font-semibold">{teamsWithPermissions.length}/{teams.length}</span>
                  </div>
                  <div className={`h-2 overflow-hidden rounded-full ${isDark ? 'bg-white/10' : 'bg-brand/10'}`}>
                    <div
                      className="h-full rounded-full bg-emerald-500"
                      style={{ width: teams.length ? `${(teamsWithPermissions.length / teams.length) * 100}%` : '0%' }}
                    />
                  </div>
                </div>
              </div>
            </div>
          </section>
        )}

        {currentTab === 'users' && (
          <section className={agentivePanelClass(isDark, 'overflow-hidden')}>
            <div className={`flex flex-col gap-3 border-b p-4 lg:flex-row lg:items-center lg:justify-between ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
              <div>
                <h2 className="text-lg font-semibold">Usuários</h2>
                <p className={`text-sm ${isDark ? 'text-white/55' : 'text-brand/55'}`}>Acessos, equipes e credenciais.</p>
              </div>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <div className="relative sm:w-72">
                  <Search className={`absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${isDark ? 'text-white/40' : 'text-brand/40'}`} />
                  <input
                    value={searchTerm}
                    onChange={event => setSearchTerm(event.target.value)}
                    placeholder="Buscar por nome, email ou equipe"
                    className={agentiveInputClass(isDark, 'pl-9')}
                  />
                </div>
                <div className="relative sm:w-48">
                  <select
                    value={teamFilter}
                    onChange={event => setTeamFilter(event.target.value)}
                    className={agentiveInputClass(isDark, 'appearance-none pr-9')}
                    aria-label="Filtrar por equipe"
                  >
                    <option value="all">Todas as equipes</option>
                    <option value="unassigned">Sem equipe</option>
                    {teams.map(team => (
                      <option key={team.id} value={team.id.toString()}>{team.name}</option>
                    ))}
                  </select>
                  <ChevronDown className={`pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 ${isDark ? 'text-white/45' : 'text-brand/45'}`} />
                </div>
                <button
                  type="button"
                  onClick={openCreateUserDialog}
                  className={agentivePrimaryButtonClass('sm:whitespace-nowrap')}
                >
                  <Plus className="h-4 w-4" />
                  Novo usuário
                </button>
              </div>
            </div>

            {filteredUsers.length === 0 ? (
              <div className="p-4">
                <AgentiveEmptyState
                  icon={Users}
                  title={users.length === 0 ? 'Nenhum usuário cadastrado' : 'Nenhum usuário encontrado'}
                  description={users.length === 0 ? 'Crie o primeiro acesso para organizar responsabilidades e permissões.' : 'Ajuste os filtros para ver outros usuários.'}
                  action={users.length === 0 ? (
                    <button type="button" onClick={openCreateUserDialog} className={agentiveSecondaryButtonClass(isDark)}>
                      <Plus className="h-4 w-4" />
                      Criar usuário
                    </button>
                  ) : undefined}
                />
              </div>
            ) : (
              <>
                <div className="hidden overflow-x-auto md:block">
                  <table className="min-w-full">
                    <thead className={isDark ? 'bg-white/[0.04]' : 'bg-brand-canvas'}>
                      <tr className={`text-left text-xs font-semibold uppercase tracking-[0.08em] ${isDark ? 'text-white/45' : 'text-brand/45'}`}>
                        <th className="px-5 py-3">Usuário</th>
                        <th className="px-5 py-3">Equipe</th>
                        <th className="px-5 py-3">Função</th>
                        <th className="px-5 py-3">Status</th>
                        <th className="px-5 py-3 text-right">Ações</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredUsers.map(user => {
                        const teamName = getTeamName(user);

                        return (
                          <tr
                            key={user.id}
                            className={`border-t text-sm transition-colors ${isDark ? 'border-white/10 text-white/70 hover:bg-white/[0.04]' : 'border-brand/10 text-brand/70 hover:bg-brand-canvas'}`}
                          >
                            <td className="px-5 py-4">
                              <div className="flex min-w-0 items-center gap-3">
                                <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl text-sm font-semibold ${isDark ? 'bg-white/10 text-white' : 'bg-brand-canvas text-brand'}`}>
                                  {getInitials(user.name)}
                                </div>
                                <div className="min-w-0">
                                  <p className="truncate font-semibold">{user.name}</p>
                                  <p className={`truncate text-xs ${isDark ? 'text-white/45' : 'text-brand/45'}`}>{user.email}</p>
                                </div>
                              </div>
                            </td>
                            <td className="px-5 py-4">
                              {teamName ? (
                                <span className={agentivePillClass(isDark)}>{teamName}</span>
                              ) : (
                                <span className={`text-xs italic ${isDark ? 'text-white/35' : 'text-brand/35'}`}>Sem equipe</span>
                              )}
                            </td>
                            <td className="px-5 py-4">
                              <span className={agentivePillClass(isDark, false)}>{getRoleLabel(user.role)}</span>
                            </td>
                            <td className="px-5 py-4">
                              <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
                                user.is_active
                                  ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100'
                                  : 'bg-amber-50 text-amber-700 ring-1 ring-amber-100'
                              }`}>
                                <Circle className={`h-2 w-2 ${user.is_active ? 'fill-emerald-500 text-emerald-500' : 'fill-amber-500 text-amber-500'}`} />
                                {user.is_active ? 'Ativo' : 'Inativo'}
                              </span>
                            </td>
                            <td className="px-5 py-4 text-right">
                              <DropdownMenu
                                trigger={(
                                  <button
                                    type="button"
                                    className={agentiveIconButtonClass(isDark)}
                                    aria-label={`Gerenciar ${user.name}`}
                                    title="Gerenciar"
                                  >
                                    <MoreVertical className="h-4 w-4" />
                                  </button>
                                )}
                              >
                                <DropdownItem icon={<Pencil className="h-4 w-4" />} onClick={() => openEditUserDialog(user)}>
                                  Editar
                                </DropdownItem>
                                <DropdownItem icon={<Key className="h-4 w-4" />} onClick={() => openPasswordDialog(user)}>
                                  Alterar senha
                                </DropdownItem>
                                <DropdownItem icon={<Trash2 className="h-4 w-4" />} destructive onClick={() => setUserToDelete(user)}>
                                  Excluir
                                </DropdownItem>
                              </DropdownMenu>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                <div className={`divide-y md:hidden ${isDark ? 'divide-white/10' : 'divide-brand/10'}`}>
                  {filteredUsers.map(user => {
                    const teamName = getTeamName(user);

                    return (
                      <div key={user.id} className="p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex min-w-0 items-center gap-3">
                            <div className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl text-sm font-semibold ${isDark ? 'bg-white/10 text-white' : 'bg-brand-canvas text-brand'}`}>
                              {getInitials(user.name)}
                            </div>
                            <div className="min-w-0">
                              <p className="truncate text-sm font-semibold">{user.name}</p>
                              <p className={`truncate text-xs ${isDark ? 'text-white/45' : 'text-brand/45'}`}>{user.email}</p>
                            </div>
                          </div>
                          <DropdownMenu
                            trigger={(
                              <button
                                type="button"
                                className={agentiveIconButtonClass(isDark)}
                                aria-label={`Gerenciar ${user.name}`}
                                title="Gerenciar"
                              >
                                <MoreVertical className="h-4 w-4" />
                              </button>
                            )}
                          >
                            <DropdownItem icon={<Pencil className="h-4 w-4" />} onClick={() => openEditUserDialog(user)}>
                              Editar
                            </DropdownItem>
                            <DropdownItem icon={<Key className="h-4 w-4" />} onClick={() => openPasswordDialog(user)}>
                              Alterar senha
                            </DropdownItem>
                            <DropdownItem icon={<Trash2 className="h-4 w-4" />} destructive onClick={() => setUserToDelete(user)}>
                              Excluir
                            </DropdownItem>
                          </DropdownMenu>
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          <span className={agentivePillClass(isDark, false)}>{getRoleLabel(user.role)}</span>
                          <span className={agentivePillClass(isDark, false)}>{teamName || 'Sem equipe'}</span>
                          <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
                            user.is_active
                              ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100'
                              : 'bg-amber-50 text-amber-700 ring-1 ring-amber-100'
                          }`}>
                            <Circle className={`h-2 w-2 ${user.is_active ? 'fill-emerald-500 text-emerald-500' : 'fill-amber-500 text-amber-500'}`} />
                            {user.is_active ? 'Ativo' : 'Inativo'}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </section>
        )}

        {currentTab === 'teams' && (
          <TeamsManagement onTeamsChanged={refreshOrganizationData} />
        )}
      </div>

      <Dialog
        open={showUserDialog}
        title={userDialogTitle}
        description={userDialogDescription}
        icon={dialogMode === 'password' ? Key : Users}
        onClose={closeUserDialog}
        footer={(
          <>
            <button
              type="button"
              onClick={closeUserDialog}
              disabled={isSavingUser}
              className={agentiveSecondaryButtonClass(isDark)}
            >
              Cancelar
            </button>
            <button
              type="submit"
              form="company-user-form"
              disabled={
                isSavingUser ||
                ((dialogMode === 'create' || dialogMode === 'password') && userForm.password !== userForm.confirmPassword)
              }
              className={agentivePrimaryButtonClass()}
            >
              {isSavingUser ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              {dialogMode === 'create' ? 'Criar usuário' : dialogMode === 'edit' ? 'Salvar alterações' : 'Alterar senha'}
            </button>
          </>
        )}
      >
        <form id="company-user-form" onSubmit={handleUserSubmit} className="space-y-5">
          {dialogMode !== 'password' && (
            <div className="grid gap-4 sm:grid-cols-2">
              <InputField
                label="Nome"
                value={userForm.name}
                onChange={event => setUserForm(prev => ({ ...prev, name: event.target.value }))}
                required
              />
              <InputField
                label="Email"
                type="email"
                value={userForm.email}
                onChange={event => setUserForm(prev => ({ ...prev, email: event.target.value }))}
                required
              />
              <SelectField
                label="Função"
                value={userForm.role}
                onChange={event => setUserForm(prev => ({ ...prev, role: event.target.value }))}
                required
              >
                <option value="staff">Funcionário</option>
              </SelectField>
              <SelectField
                label="Equipe"
                value={userForm.team_id?.toString() || ''}
                onChange={event => setUserForm(prev => ({
                  ...prev,
                  team_id: event.target.value ? Number(event.target.value) : undefined,
                }))}
              >
                <option value="">Sem equipe</option>
                {teams.map(team => (
                  <option key={team.id} value={team.id.toString()}>{team.name}</option>
                ))}
              </SelectField>
            </div>
          )}

          {(dialogMode === 'create' || dialogMode === 'password') && (
            <div className="grid gap-4 sm:grid-cols-2">
              <InputField
                label="Senha"
                type={showPassword ? 'text' : 'password'}
                value={userForm.password}
                onChange={event => setUserForm(prev => ({ ...prev, password: event.target.value }))}
                required
                suffix={(
                  <button
                    type="button"
                    onClick={() => setShowPassword(prev => !prev)}
                    className={`absolute right-3 top-1/2 -translate-y-1/2 ${isDark ? 'text-white/45 hover:text-white' : 'text-brand/45 hover:text-brand'}`}
                    aria-label={showPassword ? 'Ocultar senha' : 'Mostrar senha'}
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                )}
              />
              <InputField
                label="Confirmar senha"
                type={showConfirmPassword ? 'text' : 'password'}
                value={userForm.confirmPassword}
                onChange={event => setUserForm(prev => ({ ...prev, confirmPassword: event.target.value }))}
                required
                suffix={(
                  <button
                    type="button"
                    onClick={() => setShowConfirmPassword(prev => !prev)}
                    className={`absolute right-3 top-1/2 -translate-y-1/2 ${isDark ? 'text-white/45 hover:text-white' : 'text-brand/45 hover:text-brand'}`}
                    aria-label={showConfirmPassword ? 'Ocultar confirmação' : 'Mostrar confirmação'}
                  >
                    {showConfirmPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                )}
              />
              {userForm.password !== userForm.confirmPassword && userForm.confirmPassword && (
                <p className="sm:col-span-2 text-xs font-medium text-red-500">As senhas não conferem.</p>
              )}
            </div>
          )}
        </form>
      </Dialog>

      <AgentiveConfirmModal
        isOpen={Boolean(userToDelete)}
        title="Excluir usuário"
        confirmText="Excluir"
        isLoading={isDeletingUser}
        onClose={() => {
          if (!isDeletingUser) setUserToDelete(null);
        }}
        onConfirm={confirmDeleteUser}
        variant="danger"
        message={(
          <>
            O acesso de <strong>{userToDelete?.name}</strong> será removido. Contatos, CRM e históricos serão preservados.
          </>
        )}
      />
    </div>
  );
};

export default CompanyConfig;
