import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import {
    Activity,
    Bot,
    GitBranch,
    Loader2,
    Network,
    Plus,
    Search,
    Trash2,
    X,
} from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
    createAgentWorkforce,
    deleteAgentWorkforce,
    getAgentWorkforces,
    type AgentWorkforce,
} from '../services/agentWorkforceApi.ts';
import {
    AgentiveAlert,
    AgentiveConfirmModal,
    AgentiveEmptyState,
    AgentivePageHeader,
    agentiveIconButtonClass,
    agentiveInputClass,
    agentivePageClass,
    agentivePanelClass,
    agentivePillClass,
    agentivePrimaryButtonClass,
    agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';

type StatusFilter = 'all' | 'active' | 'paused' | 'draft';

const statusOptions: Array<{ id: StatusFilter; label: string }> = [
    { id: 'all', label: 'Todos' },
    { id: 'active', label: 'Ativas' },
    { id: 'paused', label: 'Pausadas' },
    { id: 'draft', label: 'Rascunhos' },
];

const formatDate = (value?: string) => {
    if (!value) return 'Sem edicao';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Data invalida';

    return new Intl.DateTimeFormat('pt-BR', {
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
    }).format(date);
};

const statusLabel: Record<string, string> = {
    active: 'Ativa',
    paused: 'Pausada',
    draft: 'Rascunho',
};

const channelLabel: Record<string, string> = {
    whatsapp: 'WhatsApp',
    webchat: 'Webchat',
    voice: 'Voz',
    email: 'E-mail',
    instagram: 'Instagram',
};

const getStatusLabel = (status?: string) => statusLabel[status || 'draft'] || status || 'Rascunho';

const getChannelLabel = (channel?: string) => channelLabel[channel || 'whatsapp'] || channel || 'WhatsApp';

const getAgentCount = (workforce: AgentWorkforce) =>
    (workforce.nodes || []).filter((node: any) => node?.data?.kind !== 'human').length;

const getHumanQueueCount = (workforce: AgentWorkforce) =>
    (workforce.nodes || []).filter((node: any) => node?.data?.kind === 'human').length;

const AgentsPage: React.FC = () => {
    const { isDark } = useTheme();
    const navigate = useNavigate();
    const [workforces, setWorkforces] = useState<AgentWorkforce[]>([]);
    const [loading, setLoading] = useState(true);
    const [searchTerm, setSearchTerm] = useState('');
    const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
    const [fetchError, setFetchError] = useState('');
    const [isCreateOpen, setIsCreateOpen] = useState(false);
    const [newWorkforceName, setNewWorkforceName] = useState('');
    const [newWorkforceDescription, setNewWorkforceDescription] = useState('');
    const [creating, setCreating] = useState(false);
    const [workforceToDelete, setWorkforceToDelete] = useState<AgentWorkforce | null>(null);
    const [deleting, setDeleting] = useState(false);

    const fetchWorkforces = useCallback(async () => {
        try {
            setLoading(true);
            setFetchError('');
            const data = await getAgentWorkforces();
            setWorkforces(data);
        } catch (error) {
            console.error('Failed to fetch agent workforces', error);
            if (axios.isAxiosError(error) && error.code === 'ERR_NETWORK') {
                setFetchError('Nao foi possivel carregar as equipes pelo proxy de desenvolvimento. Confira se a chamada usa /api/agent-workforces no mesmo dominio do frontend.');
            } else {
                setFetchError('Nao foi possivel carregar as equipes de agentes.');
            }
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchWorkforces();
    }, [fetchWorkforces]);

    const filteredWorkforces = useMemo(() => {
        const normalizedSearch = searchTerm.trim().toLowerCase();

        return workforces.filter((workforce) => {
            const matchesSearch = !normalizedSearch
                || workforce.name.toLowerCase().includes(normalizedSearch)
                || (workforce.description || '').toLowerCase().includes(normalizedSearch);
            const matchesStatus =
                statusFilter === 'all'
                || (statusFilter === 'active' && workforce.status === 'active')
                || (statusFilter === 'paused' && workforce.status === 'paused')
                || (statusFilter === 'draft' && workforce.status !== 'active' && workforce.status !== 'paused');

            return matchesSearch && matchesStatus;
        });
    }, [workforces, searchTerm, statusFilter]);

    const openCreateModal = (name = '') => {
        setNewWorkforceName(name);
        setNewWorkforceDescription('');
        setIsCreateOpen(true);
    };

    const handleCreateWorkforce = async (event?: React.FormEvent) => {
        event?.preventDefault();
        const name = newWorkforceName.trim();
        if (!name) {
            setFetchError('Informe um nome para criar a equipe.');
            return;
        }

        try {
            setCreating(true);
            setFetchError('');
            const newWorkforce = await createAgentWorkforce({
                name,
                description: newWorkforceDescription.trim(),
                status: 'draft',
                channel: 'whatsapp',
                root_agent_key: null,
                nodes: [],
                edges: [],
                viewport: { x: 0, y: 0, zoom: 1 },
                agent_configs: {},
                settings: {},
            });
            setIsCreateOpen(false);
            navigate(`/agents/editor/${newWorkforce.id}`);
        } catch (error) {
            console.error('Failed to create agent workforce', error);
            setFetchError('Nao foi possivel criar a equipe de agentes.');
        } finally {
            setCreating(false);
        }
    };

    const confirmDeleteWorkforce = async () => {
        if (!workforceToDelete) return;

        try {
            setDeleting(true);
            setFetchError('');
            await deleteAgentWorkforce(workforceToDelete.id);
            setWorkforceToDelete(null);
            await fetchWorkforces();
        } catch (error) {
            console.error('Failed to delete agent workforce', error);
            setFetchError('Nao foi possivel excluir a equipe de agentes.');
        } finally {
            setDeleting(false);
        }
    };

    return (
        <div className={agentivePageClass(isDark, 'px-4 pb-28 pt-4 sm:px-6 lg:px-8 xl:px-10')}>
            <div className="mx-auto max-w-screen-2xl space-y-5">
                <AgentivePageHeader
                    icon={Network}
                    title="Agentes"
                    description="Gerencie equipes multiagente e abra o Agent Builder para modelar especialistas, filas humanas, handoffs e ferramentas."
                    badges={<span className={agentivePillClass(isDark, true)}>Agent Builder</span>}
                    actions={(
                        <>
                            <button
                                type="button"
                                onClick={() => fetchWorkforces()}
                                className={agentiveSecondaryButtonClass(isDark)}
                                disabled={loading}
                            >
                                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Activity className="h-4 w-4" />}
                                Atualizar
                            </button>
                            <button
                                type="button"
                                onClick={() => openCreateModal()}
                                className={agentivePrimaryButtonClass('min-h-10 px-4')}
                            >
                                <Plus className="h-4 w-4" />
                                Nova equipe
                            </button>
                        </>
                    )}
                />

                {fetchError && (
                    <AgentiveAlert variant="error" title="Ação não concluída" onClose={() => setFetchError('')}>
                        {fetchError}
                    </AgentiveAlert>
                )}

                <section className={agentivePanelClass(isDark, 'min-w-0 overflow-hidden')}>
                        <div className={`border-b p-4 sm:p-5 ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
                            <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
                                <div>
                                    <p className={`text-[10px] font-bold uppercase tracking-[0.16em] ${isDark ? 'text-white/35' : 'text-brand/35'}`}>Gerenciamento</p>
                                    <h2 className="mt-1 text-lg font-semibold">Equipes configuradas</h2>
                                    <p className={`mt-1 text-sm ${isDark ? 'text-white/55' : 'text-brand/55'}`}>
                                        {filteredWorkforces.length} de {workforces.length} equipes exibidas.
                                    </p>
                                </div>

                                <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
                                    <div className="relative min-w-0 lg:w-72">
                                        <Search className={`pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${isDark ? 'text-white/35' : 'text-brand/35'}`} />
                                        <input
                                            type="search"
                                            value={searchTerm}
                                            onChange={(event) => setSearchTerm(event.target.value)}
                                            placeholder="Buscar equipe"
                                            className={agentiveInputClass(isDark, 'pl-9')}
                                        />
                                    </div>

                                    <div className={`flex items-center gap-1 rounded-2xl border p-1 ${isDark ? 'border-white/10 bg-black/15' : 'border-brand/10 bg-brand-canvas'}`}>
                                        {statusOptions.map((option) => (
                                            <button
                                                key={option.id}
                                                type="button"
                                                onClick={() => setStatusFilter(option.id)}
                                                className={agentivePillClass(isDark, statusFilter === option.id, 'border-transparent')}
                                            >
                                                {option.label}
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div className="p-3 sm:p-4">
                            {loading ? (
                                <div className={`flex items-center justify-center gap-3 rounded-2xl border p-12 ${isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas'}`}>
                                    <Loader2 className="h-5 w-5 animate-spin" />
                                    <span className="text-sm font-medium">Carregando equipes</span>
                                </div>
                            ) : workforces.length === 0 ? (
                                <AgentiveEmptyState
                                    icon={Network}
                                    title="Nenhuma equipe criada"
                                    description="Crie uma equipe multiagente e abra o Agent Builder para desenhar agentes, handoffs e filas humanas."
                                    action={(
                                        <button type="button" onClick={() => openCreateModal()} className={agentivePrimaryButtonClass('px-4')}>
                                            <Plus className="h-4 w-4" />
                                            Criar equipe
                                        </button>
                                    )}
                                />
                            ) : filteredWorkforces.length === 0 ? (
                                <AgentiveEmptyState
                                    icon={Search}
                                    title="Nenhuma equipe encontrada"
                                    description="Ajuste a busca ou o filtro de status para encontrar outra equipe."
                                />
                            ) : (
                                <div className={`overflow-hidden rounded-2xl border ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
                                    <div className="overflow-x-auto">
                                        <table className="min-w-[780px] w-full border-collapse text-sm">
                                            <thead className={isDark ? 'bg-white/[0.04] text-white/45' : 'bg-brand-canvas text-brand/45'}>
                                                <tr className="text-left text-[10px] font-bold uppercase tracking-[0.16em]">
                                                    <th className="px-4 py-3">Equipe</th>
                                                    <th className="px-4 py-3">Status</th>
                                                    <th className="px-4 py-3">Canal</th>
                                                    <th className="px-4 py-3">Agentes</th>
                                                    <th className="px-4 py-3">Conexões</th>
                                                    <th className="px-4 py-3">Última edição</th>
                                                    <th className="px-4 py-3 text-right">Ações</th>
                                                </tr>
                                            </thead>
                                            <tbody className={`divide-y ${isDark ? 'divide-white/10' : 'divide-brand/10'}`}>
                                                {filteredWorkforces.map((workforce) => {
                                                    const agentCount = getAgentCount(workforce);
                                                    const humanQueueCount = getHumanQueueCount(workforce);
                                                    const isActive = workforce.status === 'active';

                                                    return (
                                                        <tr
                                                            key={workforce.id}
                                                            onClick={() => navigate(`/agents/editor/${workforce.id}`)}
                                                            className={`group cursor-pointer transition ${
                                                                isDark ? 'hover:bg-white/[0.06]' : 'hover:bg-brand-canvas'
                                                            }`}
                                                        >
                                                            <td className="px-4 py-3">
                                                                <div className="flex min-w-0 items-center gap-3">
                                                                    <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ${isActive ? 'bg-emerald-500/10 text-emerald-600' : isDark ? 'bg-white/10 text-white/70' : 'bg-brand-canvas text-brand/70'}`}>
                                                                        <Network className="h-4 w-4" />
                                                                    </span>
                                                                    <div className="min-w-0">
                                                                        <p className="truncate font-semibold">{workforce.name}</p>
                                                                        <p className={`mt-0.5 text-xs ${isDark ? 'text-white/45' : 'text-brand/45'}`}>
                                                                            {workforce.description || `ID #${workforce.id}`}
                                                                        </p>
                                                                    </div>
                                                                </div>
                                                            </td>
                                                            <td className="px-4 py-3">
                                                                <span className={agentivePillClass(isDark, isActive)}>
                                                                    {getStatusLabel(workforce.status)}
                                                                </span>
                                                            </td>
                                                            <td className="px-4 py-3">
                                                                <span className={agentivePillClass(isDark)}>
                                                                    {getChannelLabel(workforce.channel)}
                                                                </span>
                                                            </td>
                                                            <td className={`px-4 py-3 font-medium ${isDark ? 'text-white/65' : 'text-brand/65'}`}>
                                                                <span className="inline-flex items-center gap-2">
                                                                    <Bot className="h-4 w-4 opacity-60" />
                                                                    {agentCount}
                                                                </span>
                                                            </td>
                                                            <td className={`px-4 py-3 font-medium ${isDark ? 'text-white/65' : 'text-brand/65'}`}>
                                                                <span className="inline-flex items-center gap-2">
                                                                    <GitBranch className="h-4 w-4 opacity-60" />
                                                                    {workforce.edges?.length || 0}
                                                                    {humanQueueCount > 0 && (
                                                                        <span className={`text-xs font-normal ${isDark ? 'text-white/40' : 'text-brand/40'}`}>
                                                                            {humanQueueCount} fila
                                                                        </span>
                                                                    )}
                                                                </span>
                                                            </td>
                                                            <td className={`px-4 py-3 ${isDark ? 'text-white/55' : 'text-brand/55'}`}>
                                                                {formatDate(workforce.updated_at)}
                                                            </td>
                                                            <td className="px-4 py-3">
                                                                <div className="flex items-center justify-end gap-2">
                                                                    <button
                                                                        type="button"
                                                                        onClick={(event) => {
                                                                            event.stopPropagation();
                                                                            setWorkforceToDelete(workforce);
                                                                        }}
                                                                        className={agentiveIconButtonClass(isDark, 'danger')}
                                                                        title="Excluir equipe"
                                                                    >
                                                                        <Trash2 className="h-4 w-4" />
                                                                    </button>
                                                                </div>
                                                            </td>
                                                        </tr>
                                                    );
                                                })}
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                            )}
                        </div>
                    </section>
            </div>

            {isCreateOpen && (
                <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4">
                    <div className="fixed inset-0 bg-brand/55 backdrop-blur-sm" onClick={creating ? undefined : () => setIsCreateOpen(false)} />
                    <form
                        onSubmit={handleCreateWorkforce}
                        className={`relative z-[10000] w-full max-w-lg overflow-hidden rounded-2xl border p-5 shadow-[0_24px_70px_rgba(2,3,35,0.28)] ${
                            isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand'
                        }`}
                    >
                        <div className="flex items-start justify-between gap-4">
                            <div className="flex items-start gap-3">
                                <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
                                    <Plus className="h-5 w-5" />
                                </span>
                                <div>
                                    <h3 className="text-base font-semibold leading-tight">Nova equipe</h3>
                                    <p className={`mt-1.5 text-sm leading-relaxed ${isDark ? 'text-white/60' : 'text-brand/60'}`}>
                                        Nomeie a equipe. O desenho dos agentes acontece no Agent Builder.
                                    </p>
                                </div>
                            </div>
                            <button
                                type="button"
                                onClick={() => setIsCreateOpen(false)}
                                disabled={creating}
                                className={agentiveIconButtonClass(isDark)}
                                aria-label="Fechar modal"
                            >
                                <X className="h-4 w-4" />
                            </button>
                        </div>

                        <div className="mt-5">
                            <label className={`mb-1.5 block text-sm font-medium ${isDark ? 'text-white/75' : 'text-brand/70'}`}>
                                Nome da equipe
                            </label>
                            <input
                                autoFocus
                                value={newWorkforceName}
                                onChange={(event) => setNewWorkforceName(event.target.value)}
                                placeholder="Ex: Atendimento comercial"
                                className={agentiveInputClass(isDark)}
                            />
                        </div>

                        <div className="mt-4">
                            <label className={`mb-1.5 block text-sm font-medium ${isDark ? 'text-white/75' : 'text-brand/70'}`}>
                                Descrição
                            </label>
                            <textarea
                                value={newWorkforceDescription}
                                onChange={(event) => setNewWorkforceDescription(event.target.value)}
                                placeholder="Ex: qualificar leads, agendar e transferir exceções para humanos."
                                className={agentiveInputClass(isDark, 'min-h-24 resize-y')}
                            />
                        </div>

                        <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                            <button
                                type="button"
                                onClick={() => setIsCreateOpen(false)}
                                disabled={creating}
                                className={agentiveSecondaryButtonClass(isDark)}
                            >
                                Cancelar
                            </button>
                            <button type="submit" disabled={creating} className={agentivePrimaryButtonClass('px-4')}>
                                {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                                {creating ? 'Criando' : 'Criar e abrir'}
                            </button>
                        </div>
                    </form>
                </div>
            )}

            <AgentiveConfirmModal
                cancelText="Cancelar"
                confirmText="Excluir equipe"
                isLoading={deleting}
                isOpen={Boolean(workforceToDelete)}
                message={(
                    <>
                        Esta ação remove <strong>{workforceToDelete?.name}</strong>, agentes, handoffs e configurações salvas. Essa alteração não pode ser desfeita.
                    </>
                )}
                onClose={() => setWorkforceToDelete(null)}
                onConfirm={confirmDeleteWorkforce}
                title="Excluir equipe?"
                variant="danger"
            />
        </div>
    );
};

export default AgentsPage;
