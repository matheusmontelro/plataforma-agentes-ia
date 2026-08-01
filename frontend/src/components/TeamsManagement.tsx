import React, { useEffect, useMemo, useState } from 'react';
import {
  Check,
  Loader2,
  Plus,
  Save,
  Search,
  Shield,
  Trash2,
  UserMinus,
  UserPlus,
  Users,
  X,
} from 'lucide-react';
import {
  assignUserToTeam,
  ContactPermissionConfig,
  createTeam,
  deleteTeam,
  getPipelines,
  getTeamUsers,
  getTeams,
  listUsers,
  PipelineResponse,
  removeUserFromTeam,
  SidebarPermission,
  Team,
  TeamCreate,
  updateTeam,
  User,
} from '../services/api';
import { useTheme } from '../contexts/ThemeContext.tsx';
import { getSidebarPermissionGroups } from '../config/sidebarNavigation.ts';
import {
  AgentiveConfirmModal,
  AgentiveEmptyState,
  agentiveInputClass,
  agentiveLabelClass,
  agentivePanelClass,
  agentivePillClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from './AgentiveUI.tsx';

interface TeamsManagementProps {
  onTeamsChanged?: () => Promise<void> | void;
}

interface TeamFormState {
  name: string;
  description: string;
  sidebar_permissions: SidebarPermission[];
  contact_permissions: ContactPermissionConfig;
}

const emptyContactPermissions: ContactPermissionConfig = {
  include_outside_crm: false,
  pipeline_stage_ids: [],
};

const emptyForm: TeamFormState = {
  name: '',
  description: '',
  sidebar_permissions: ['crm', 'chat'],
  contact_permissions: emptyContactPermissions,
};

const toFormState = (team?: Team | null): TeamFormState => {
  if (!team) {
    return {
      ...emptyForm,
      sidebar_permissions: [...emptyForm.sidebar_permissions],
      contact_permissions: { ...emptyContactPermissions },
    };
  }

  return {
    name: team.name,
    description: team.description || '',
    sidebar_permissions: team.sidebar_permissions || [],
    contact_permissions: {
      include_outside_crm: Boolean(team.contact_permissions?.include_outside_crm),
      pipeline_stage_ids: team.contact_permissions?.pipeline_stage_ids || [],
    },
  };
};

const toggleValue = <T,>(items: T[], value: T): T[] => {
  return items.includes(value) ? items.filter(item => item !== value) : [...items, value];
};

const getInitials = (name: string) => {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return (parts.slice(0, 2).map(part => part[0]).join('') || 'U').toUpperCase();
};

const TeamsManagement: React.FC<TeamsManagementProps> = ({ onTeamsChanged }) => {
  const { isDark } = useTheme();
  const [teams, setTeams] = useState<Team[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [teamUsers, setTeamUsers] = useState<User[]>([]);
  const [pipelines, setPipelines] = useState<PipelineResponse[]>([]);
  const [selectedTeam, setSelectedTeam] = useState<Team | null>(null);
  const [form, setForm] = useState<TeamFormState>(emptyForm);
  const [mode, setMode] = useState<'create' | 'edit'>('create');
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [loadingUsers, setLoadingUsers] = useState<Record<number, boolean>>({});
  const [teamToDelete, setTeamToDelete] = useState<Team | null>(null);
  const [teamSearch, setTeamSearch] = useState('');
  const [userSearch, setUserSearch] = useState('');
  const [error, setError] = useState<string | null>(null);

  const companyId = Number((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')));

  const stages = useMemo(() => {
    return pipelines.flatMap(pipeline =>
      pipeline.stages.map(stage => ({
        id: stage.id,
        name: stage.name,
        pipelineName: pipeline.name,
        color: stage.color || '#3B82F6',
      }))
    );
  }, [pipelines]);

  const selectedTeamUserIds = useMemo(() => new Set(teamUsers.map(user => user.id)), [teamUsers]);
  const sidebarPermissionGroups = useMemo(() => getSidebarPermissionGroups(), []);

  const filteredTeams = useMemo(() => {
    const normalizedSearch = teamSearch.trim().toLowerCase();
    if (!normalizedSearch) return teams;

    return teams.filter(team =>
      team.name.toLowerCase().includes(normalizedSearch) ||
      (team.description || '').toLowerCase().includes(normalizedSearch)
    );
  }, [teamSearch, teams]);

  const filteredUsers = useMemo(() => {
    const normalizedSearch = userSearch.trim().toLowerCase();
    if (!normalizedSearch) return users;

    return users.filter(user =>
      user.name.toLowerCase().includes(normalizedSearch) ||
      user.email.toLowerCase().includes(normalizedSearch)
    );
  }, [userSearch, users]);

  useEffect(() => {
    fetchInitialData();
  }, []);

  useEffect(() => {
    setForm(toFormState(selectedTeam));
    setMode(selectedTeam ? 'edit' : 'create');

    if (selectedTeam) {
      fetchTeamUsers(selectedTeam.id);
    } else {
      setTeamUsers([]);
    }
  }, [selectedTeam]);

  const notifyParent = async () => {
    if (onTeamsChanged) await onTeamsChanged();
  };

  const fetchInitialData = async () => {
    setIsLoading(true);
    setError(null);

    try {
      const [teamsData, usersData, pipelinesData] = await Promise.all([
        getTeams(),
        listUsers(companyId),
        getPipelines(companyId),
      ]);
      setTeams(teamsData);
      setUsers(usersData);
      setPipelines(pipelinesData);
      setSelectedTeam(teamsData[0] || null);
    } catch (fetchError) {
      console.error('Erro ao carregar equipes:', fetchError);
      setError('Não foi possível carregar equipes e permissões.');
    } finally {
      setIsLoading(false);
    }
  };

  const fetchTeamUsers = async (teamId: number) => {
    try {
      const response = await getTeamUsers(teamId);
      setTeamUsers(response);
    } catch (fetchError) {
      console.error('Erro ao carregar usuários da equipe:', fetchError);
      setError('Não foi possível carregar os membros da equipe.');
    }
  };

  const refreshTeams = async (nextSelectedTeamId?: number) => {
    const teamsData = await getTeams();
    setTeams(teamsData);
    const nextSelected = teamsData.find(team => team.id === nextSelectedTeamId) || teamsData[0] || null;
    setSelectedTeam(nextSelected);
    if (nextSelected) await fetchTeamUsers(nextSelected.id);
    await notifyParent();
  };

  const resetToCreate = () => {
    setSelectedTeam(null);
    setMode('create');
    setForm(toFormState(null));
    setError(null);
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    if (!form.name.trim()) return;

    setIsSaving(true);
    setError(null);

    const payload: TeamCreate = {
      name: form.name.trim(),
      description: form.description.trim() || undefined,
      sidebar_permissions: form.sidebar_permissions,
      contact_permissions: {
        include_outside_crm: form.contact_permissions.include_outside_crm,
        pipeline_stage_ids: form.contact_permissions.pipeline_stage_ids,
      },
    };

    try {
      const savedTeam = mode === 'edit' && selectedTeam
        ? await updateTeam(selectedTeam.id, payload)
        : await createTeam(payload);
      await refreshTeams(savedTeam.id);
    } catch (submitError) {
      console.error('Erro ao salvar equipe:', submitError);
      setError('Não foi possível salvar a equipe.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDeleteTeam = async () => {
    if (!teamToDelete) return;

    setIsSaving(true);
    setError(null);

    try {
      await deleteTeam(teamToDelete.id);
      setTeamToDelete(null);
      await refreshTeams();
      const usersData = await listUsers(companyId);
      setUsers(usersData);
    } catch (deleteError) {
      console.error('Erro ao excluir equipe:', deleteError);
      setError('Não foi possível excluir a equipe.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleToggleUser = async (user: User, isInTeam: boolean) => {
    if (!selectedTeam) return;

    setLoadingUsers(prev => ({ ...prev, [user.id]: true }));
    setError(null);

    try {
      if (isInTeam) {
        await removeUserFromTeam(selectedTeam.id, user.id);
      } else {
        await assignUserToTeam(selectedTeam.id, user.id);
      }

      await fetchTeamUsers(selectedTeam.id);
      const [teamsData, usersData] = await Promise.all([getTeams(), listUsers(companyId)]);
      setTeams(teamsData);
      setUsers(usersData);
      await notifyParent();
    } catch (toggleError) {
      console.error('Erro ao atualizar usuário na equipe:', toggleError);
      setError('Não foi possível atualizar o membro da equipe.');
    } finally {
      setLoadingUsers(prev => ({ ...prev, [user.id]: false }));
    }
  };

  if (isLoading) {
    return (
      <div className={agentivePanelClass(isDark, 'flex min-h-[360px] items-center justify-center p-8')}>
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-10 w-10 animate-spin text-brand" />
          <p className={`text-sm font-medium ${isDark ? 'text-white/70' : 'text-brand/60'}`}>Carregando equipes...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[340px_minmax(0,1fr)]">
      <aside className={agentivePanelClass(isDark, 'overflow-hidden')}>
        <div className={`border-b p-4 ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">Equipes</h2>
              <p className={`text-sm ${isDark ? 'text-white/55' : 'text-brand/55'}`}>{teams.length} cadastradas</p>
            </div>
            <button
              type="button"
              onClick={resetToCreate}
              className={agentivePrimaryButtonClass('px-3')}
            >
              <Plus className="h-4 w-4" />
              Nova
            </button>
          </div>
          <div className="relative mt-4">
            <Search className={`absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${isDark ? 'text-white/40' : 'text-brand/40'}`} />
            <input
              value={teamSearch}
              onChange={event => setTeamSearch(event.target.value)}
              placeholder="Buscar equipe"
              className={agentiveInputClass(isDark, 'pl-9')}
            />
          </div>
        </div>

        <div className="max-h-[680px] space-y-2 overflow-y-auto p-3">
          {filteredTeams.length === 0 ? (
            <AgentiveEmptyState
              icon={Shield}
              title={teams.length === 0 ? 'Nenhuma equipe' : 'Nenhum resultado'}
              description={teams.length === 0 ? 'Crie uma equipe para separar acessos e carteiras de contato.' : 'Revise a busca para encontrar outra equipe.'}
              className="px-4 py-8"
            />
          ) : (
            filteredTeams.map(team => {
              const isSelected = selectedTeam?.id === team.id;

              return (
                <button
                  key={team.id}
                  type="button"
                  onClick={() => setSelectedTeam(team)}
                  className={`w-full rounded-2xl border p-4 text-left transition ${
                    isSelected
                      ? isDark
                        ? 'border-white bg-white text-brand shadow-[0_16px_32px_rgba(255,255,255,0.08)]'
                        : 'border-brand bg-brand text-white shadow-[0_16px_32px_rgba(2,3,35,0.12)]'
                      : isDark
                        ? 'border-white/10 bg-white/[0.04] text-white/75 hover:bg-white/10 hover:text-white'
                        : 'border-brand/10 bg-white text-brand/75 hover:bg-brand-canvas hover:text-brand'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${
                      isSelected
                        ? isDark ? 'bg-brand text-white' : 'bg-white text-brand'
                        : isDark ? 'bg-white/10 text-white/60' : 'bg-brand-canvas text-brand/60'
                    }`}>
                      <Shield className="h-4 w-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-semibold">{team.name}</p>
                      <p className={`mt-1 line-clamp-2 text-xs ${isSelected ? (isDark ? 'text-brand/55' : 'text-white/60') : isDark ? 'text-white/50' : 'text-brand/50'}`}>
                        {team.description || 'Sem descrição'}
                      </p>
                      <div className="mt-3 flex flex-wrap gap-1.5">
                        <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${isSelected ? (isDark ? 'bg-brand/10 text-brand' : 'bg-white/15 text-white') : isDark ? 'bg-white/10 text-white/55' : 'bg-brand-canvas text-brand/55'}`}>
                          {team.user_count || 0} usuários
                        </span>
                        <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${isSelected ? (isDark ? 'bg-brand/10 text-brand' : 'bg-white/15 text-white') : isDark ? 'bg-white/10 text-white/55' : 'bg-brand-canvas text-brand/55'}`}>
                          {team.sidebar_permissions?.length || 0} menus
                        </span>
                      </div>
                    </div>
                  </div>
                </button>
              );
            })
          )}
        </div>
      </aside>

      <section className="min-w-0 space-y-5">
        {error && (
          <div className={`rounded-2xl border px-4 py-3 text-sm ${isDark ? 'border-red-700/40 bg-red-900/20 text-red-200' : 'border-red-200 bg-red-50 text-red-700'}`}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className={agentivePanelClass(isDark, 'overflow-hidden')}>
          <div className={`flex flex-col gap-3 border-b p-5 sm:flex-row sm:items-center sm:justify-between ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
            <div>
              <div className={`mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] ${isDark ? 'text-white/40' : 'text-brand/40'}`}>
                {mode === 'edit' ? 'Equipe selecionada' : 'Nova equipe'}
              </div>
              <h2 className="text-xl font-semibold">{mode === 'edit' && selectedTeam ? selectedTeam.name : 'Criar equipe'}</h2>
              <p className={`text-sm ${isDark ? 'text-white/55' : 'text-brand/55'}`}>
                Menus, contatos e membros vinculados.
              </p>
            </div>
            {mode === 'edit' && selectedTeam && (
              <button
                type="button"
                onClick={() => setTeamToDelete(selectedTeam)}
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700 transition hover:bg-red-100"
              >
                <Trash2 className="h-4 w-4" />
                Excluir
              </button>
            )}
          </div>

          <div className={`grid gap-4 border-b p-5 md:grid-cols-2 ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
            <label className="block">
              <span className={agentiveLabelClass(isDark)}>Nome da equipe</span>
              <input
                value={form.name}
                onChange={event => setForm(prev => ({ ...prev, name: event.target.value }))}
                required
                placeholder="Ex: Comercial"
                className={agentiveInputClass(isDark)}
              />
            </label>

            <label className="block">
              <span className={agentiveLabelClass(isDark)}>Descrição</span>
              <input
                value={form.description}
                onChange={event => setForm(prev => ({ ...prev, description: event.target.value }))}
                placeholder="Ex: SDRs e atendimento inicial"
                className={agentiveInputClass(isDark)}
              />
            </label>
          </div>

          <div className={`grid gap-6 border-b p-5 2xl:grid-cols-[minmax(0,1fr)_420px] ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
            <div>
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold">Menus liberados</h3>
                <span className={agentivePillClass(isDark, false)}>
                  {form.sidebar_permissions.length}/{sidebarPermissionGroups.length}
                </span>
              </div>
              <div className="space-y-3">
                {sidebarPermissionGroups.map(group => {
                  const permissionKey = group.key as SidebarPermission;
                  const checked = form.sidebar_permissions.includes(permissionKey);
                  const Icon = group.icon;

                  return (
                    <div
                      key={group.key}
                      className={`rounded-2xl border p-3 transition ${
                        checked
                          ? isDark
                            ? 'border-white/25 bg-white/[0.08] text-white'
                            : 'border-brand/20 bg-white text-brand shadow-[0_14px_35px_rgba(2,3,35,0.08)]'
                          : isDark
                            ? 'border-white/10 bg-white/[0.03] text-white/75 hover:bg-white/[0.06]'
                            : 'border-brand/10 bg-brand-canvas text-brand/70 hover:bg-white'
                      }`}
                    >
                      <label className="flex cursor-pointer items-start gap-3">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => setForm(prev => ({
                            ...prev,
                            sidebar_permissions: toggleValue(prev.sidebar_permissions, permissionKey),
                          }))}
                          className="sr-only"
                        />
                        <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl border ${
                          checked
                            ? isDark
                              ? 'border-white bg-white text-brand'
                              : 'border-brand bg-brand text-white'
                            : isDark
                              ? 'border-white/10 bg-white/10 text-white/55'
                              : 'border-brand/10 bg-white text-brand/55'
                        }`}>
                          <Icon className="h-4 w-4" />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className={`block truncate text-sm font-semibold ${checked ? (isDark ? 'text-white' : 'text-brand') : ''}`}>
                            {group.label}
                          </span>
                          <span className={`mt-1 block truncate text-xs ${isDark ? 'text-white/45' : 'text-brand/45'}`}>
                            {group.moduleLabels.join(' • ')}
                          </span>
                        </span>
                        <span className={`shrink-0 rounded-full px-2 py-1 text-[11px] font-semibold ${
                          checked
                            ? isDark
                              ? 'bg-white text-brand'
                              : 'bg-brand text-white'
                            : isDark
                              ? 'bg-white/10 text-white/55'
                              : 'bg-white text-brand/55'
                        }`}>
                          {group.items.length} itens
                        </span>
                        {checked && <Check className={`mt-2 h-4 w-4 shrink-0 ${isDark ? 'text-white' : 'text-brand'}`} />}
                      </label>

                      <div className={`mt-3 rounded-xl border p-2 ${isDark ? 'border-white/10 bg-brand/30' : 'border-brand/10 bg-white/80'}`}>
                        <div className="grid gap-1.5 sm:grid-cols-2">
                          {group.items.map((item, itemIndex) => {
                            const ItemIcon = item.icon;

                            return (
                              <div
                                key={`${group.key}-${item.path}-${item.label}-${itemIndex}`}
                                className={`flex min-w-0 items-center gap-2 rounded-lg px-2 py-1.5 text-xs ${isDark ? 'text-white/58' : 'text-brand/58'}`}
                              >
                                <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${isDark ? 'bg-white/10 text-white/55' : 'bg-brand-canvas text-brand/55'}`}>
                                  {item.type === 'menu' ? 'Menu' : 'Submenu'}
                                </span>
                                {ItemIcon && <ItemIcon className="h-3.5 w-3.5 shrink-0" />}
                                <span className="min-w-0 flex-1 truncate">
                                  {item.parentLabel ? `${item.parentLabel} / ${item.label}` : item.label}
                                </span>
                                {(item.isNew || item.isBeta) && (
                                  <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${isDark ? 'bg-white/10 text-white/55' : 'bg-brand-canvas text-brand/55'}`}>
                                    {item.isNew ? 'Novo' : 'Beta'}
                                  </span>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div>
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold">Contatos visíveis</h3>
                <span className={agentivePillClass(isDark, false)}>
                  {form.contact_permissions.pipeline_stage_ids.length} etapas
                </span>
              </div>

              <div className="space-y-2">
                <label className={`flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-3 text-sm transition ${
                  form.contact_permissions.include_outside_crm
                    ? isDark ? 'border-white bg-white text-brand' : 'border-brand bg-brand text-white'
                    : isDark ? 'border-white/10 text-white/65 hover:bg-white/[0.06]' : 'border-brand/10 text-brand/65 hover:bg-brand-canvas'
                }`}>
                  <input
                    type="checkbox"
                    checked={form.contact_permissions.include_outside_crm}
                    onChange={() => setForm(prev => ({
                      ...prev,
                      contact_permissions: {
                        ...prev.contact_permissions,
                        include_outside_crm: !prev.contact_permissions.include_outside_crm,
                      },
                    }))}
                    className="sr-only"
                  />
                  <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${form.contact_permissions.include_outside_crm ? (isDark ? 'bg-brand text-white' : 'bg-white text-brand') : isDark ? 'bg-white/10 text-white/50' : 'bg-white text-brand/50'}`}>
                    <Users className="h-4 w-4" />
                  </span>
                  <span className="flex-1 font-medium">Contatos fora do CRM</span>
                  {form.contact_permissions.include_outside_crm && <Check className="h-4 w-4" />}
                </label>

                <div className={`max-h-72 overflow-y-auto rounded-xl border p-2 ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
                  {stages.length === 0 ? (
                    <p className={`px-2 py-3 text-sm ${isDark ? 'text-white/45' : 'text-brand/45'}`}>Nenhuma etapa de CRM encontrada.</p>
                  ) : (
                    stages.map(stage => {
                      const checked = form.contact_permissions.pipeline_stage_ids.includes(stage.id);

                      return (
                        <label
                          key={stage.id}
                          className={`flex cursor-pointer items-center gap-3 rounded-xl px-2 py-2 text-sm transition ${
                            checked
                              ? isDark ? 'bg-white text-brand' : 'bg-brand text-white'
                              : isDark ? 'text-white/65 hover:bg-white/[0.06]' : 'text-brand/65 hover:bg-brand-canvas'
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => setForm(prev => ({
                              ...prev,
                              contact_permissions: {
                                ...prev.contact_permissions,
                                pipeline_stage_ids: toggleValue(prev.contact_permissions.pipeline_stage_ids, stage.id),
                              },
                            }))}
                            className="sr-only"
                          />
                          <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: stage.color }} />
                          <span className="min-w-0 flex-1 truncate">{stage.name}</span>
                          <span className={`hidden text-xs sm:inline ${checked ? (isDark ? 'text-brand/55' : 'text-white/60') : isDark ? 'text-white/35' : 'text-brand/35'}`}>
                            {stage.pipelineName}
                          </span>
                        </label>
                      );
                    })
                  )}
                </div>
              </div>
            </div>
          </div>

          <div className="flex flex-col-reverse gap-2 p-5 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={resetToCreate}
              className={agentiveSecondaryButtonClass(isDark)}
            >
              <X className="h-4 w-4" />
              Limpar
            </button>
            <button
              type="submit"
              disabled={isSaving || !form.name.trim()}
              className={agentivePrimaryButtonClass()}
            >
              {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              Salvar equipe
            </button>
          </div>
        </form>

        <section className={agentivePanelClass(isDark, 'overflow-hidden')}>
          <div className={`flex flex-col gap-3 border-b p-5 lg:flex-row lg:items-center lg:justify-between ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
            <div>
              <h3 className="text-lg font-semibold">Membros</h3>
              <p className={`text-sm ${isDark ? 'text-white/55' : 'text-brand/55'}`}>
                {selectedTeam ? `${teamUsers.length} vinculados em ${selectedTeam.name}` : 'Salve ou selecione uma equipe'}
              </p>
            </div>
            <div className="relative lg:w-80">
              <Search className={`absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${isDark ? 'text-white/40' : 'text-brand/40'}`} />
              <input
                value={userSearch}
                onChange={event => setUserSearch(event.target.value)}
                placeholder="Buscar usuário"
                className={agentiveInputClass(isDark, 'pl-9')}
                disabled={!selectedTeam}
              />
            </div>
          </div>

          {!selectedTeam ? (
            <div className="p-4">
              <AgentiveEmptyState
                icon={Users}
                title="Nenhuma equipe selecionada"
                description="Selecione uma equipe existente ou salve uma nova para gerenciar membros."
              />
            </div>
          ) : filteredUsers.length === 0 ? (
            <div className="p-4">
              <AgentiveEmptyState
                icon={Users}
                title={users.length === 0 ? 'Nenhum usuário criado' : 'Nenhum usuário encontrado'}
                description={users.length === 0 ? 'Crie usuários na aba de acessos para atribuir membros.' : 'Revise a busca para encontrar outro usuário.'}
              />
            </div>
          ) : (
            <div className={`divide-y ${isDark ? 'divide-white/10' : 'divide-brand/10'}`}>
              {filteredUsers.map(user => {
                const isInTeam = selectedTeamUserIds.has(user.id);

                return (
                  <div
                    key={user.id}
                    className={`flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between ${isDark ? 'text-white/70' : 'text-brand/70'}`}
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl text-sm font-semibold ${isDark ? 'bg-white/10 text-white' : 'bg-brand-canvas text-brand'}`}>
                        {getInitials(user.name)}
                      </div>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold">{user.name}</p>
                        <p className={`truncate text-xs ${isDark ? 'text-white/45' : 'text-brand/45'}`}>{user.email}</p>
                      </div>
                    </div>

                    <button
                      type="button"
                      onClick={() => handleToggleUser(user, isInTeam)}
                      disabled={loadingUsers[user.id]}
                      className={`inline-flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm font-medium transition disabled:opacity-50 ${
                        isInTeam
                          ? 'border border-red-200 bg-red-50 text-red-700 hover:bg-red-100'
                          : 'border border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
                      }`}
                    >
                      {loadingUsers[user.id] ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : isInTeam ? (
                        <UserMinus className="h-4 w-4" />
                      ) : (
                        <UserPlus className="h-4 w-4" />
                      )}
                      {isInTeam ? 'Remover' : 'Adicionar'}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </section>

      <AgentiveConfirmModal
        isOpen={Boolean(teamToDelete)}
        title="Excluir equipe"
        confirmText="Excluir"
        isLoading={isSaving}
        onClose={() => {
          if (!isSaving) setTeamToDelete(null);
        }}
        onConfirm={handleDeleteTeam}
        variant="danger"
        message={(
          <>
            Os usuários de <strong>{teamToDelete?.name}</strong> ficarão sem equipe atribuída. As permissões desse grupo serão removidas.
          </>
        )}
      />
    </div>
  );
};

export default TeamsManagement;
