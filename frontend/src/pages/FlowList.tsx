import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import {
    Activity,
    Edit2,
    GitMerge,
    Loader2,
    Plus,
    Search,
    Trash2,
    X,
} from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
    createFlow,
    deleteFlow,
    getFlows,
    updateFlow,
    type Flow,
} from '../services/flowBuilderApi';
import FlowRenameModal from '../components/flow/FlowRenameModal.tsx';
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

type StatusFilter = 'all' | 'active' | 'draft';

const statusOptions: Array<{ id: StatusFilter; label: string }> = [
    { id: 'all', label: 'Todos' },
    { id: 'active', label: 'Ativos' },
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

const getTriggerLabel = (flow: Flow) => {
    if (flow.trigger_type === 'appointment') return 'Agenda';
    if (flow.trigger_type === 'crm_stage') return 'CRM';
    if (flow.trigger_type === 'whatsapp') return 'WhatsApp';
    if (flow.trigger_type === 'webhook') return 'Webhook';

    const triggerNode = (flow.nodes || []).find((node: any) =>
        ['appointmentTrigger', 'crmStageTrigger', 'whatsappTrigger', 'webhookTrigger', 'webhookNode'].includes(node?.type)
    );

    if (triggerNode?.type === 'appointmentTrigger') return 'Agenda';
    if (triggerNode?.type === 'crmStageTrigger') return 'CRM';
    if (triggerNode?.type === 'whatsappTrigger') return 'WhatsApp';
    if (triggerNode?.type === 'webhookTrigger' || triggerNode?.type === 'webhookNode') return 'Webhook';
    return 'Sem gatilho';
};

const FlowList: React.FC = () => {
    const { isDark } = useTheme();
    const navigate = useNavigate();
    const [flows, setFlows] = useState<Flow[]>([]);
    const [loading, setLoading] = useState(true);
    const [searchTerm, setSearchTerm] = useState('');
    const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
    const [fetchError, setFetchError] = useState('');
    const [isCreateOpen, setIsCreateOpen] = useState(false);
    const [newFlowName, setNewFlowName] = useState('');
    const [creating, setCreating] = useState(false);
    const [flowToDelete, setFlowToDelete] = useState<Flow | null>(null);
    const [deleting, setDeleting] = useState(false);
    const [flowToRename, setFlowToRename] = useState<Flow | null>(null);
    const [renaming, setRenaming] = useState(false);

    const fetchFlows = useCallback(async () => {
        try {
            setLoading(true);
            setFetchError('');
            const data = await getFlows();
            setFlows(data);
        } catch (error) {
            console.error('Failed to fetch flows', error);
            if (axios.isAxiosError(error) && error.code === 'ERR_NETWORK') {
                setFetchError('Nao foi possivel carregar os fluxos pelo proxy de desenvolvimento. Confira se a chamada usa /api/flows/ no mesmo dominio do frontend.');
            } else {
                setFetchError('Nao foi possivel carregar os fluxos.');
            }
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchFlows();
    }, [fetchFlows]);

    const filteredFlows = useMemo(() => {
        const normalizedSearch = searchTerm.trim().toLowerCase();

        return flows.filter((flow) => {
            const matchesSearch = !normalizedSearch || flow.name.toLowerCase().includes(normalizedSearch);
            const matchesStatus =
                statusFilter === 'all'
                || (statusFilter === 'active' && flow.is_active)
                || (statusFilter === 'draft' && !flow.is_active);

            return matchesSearch && matchesStatus;
        });
    }, [flows, searchTerm, statusFilter]);

    const openCreateModal = (name = '') => {
        setNewFlowName(name);
        setIsCreateOpen(true);
    };

    const handleCreateFlow = async (event?: React.FormEvent) => {
        event?.preventDefault();
        const name = newFlowName.trim();
        if (!name) {
            setFetchError('Informe um nome para criar o fluxo.');
            return;
        }

        try {
            setCreating(true);
            setFetchError('');
            const newFlow = await createFlow({
                name,
                description: '',
                is_active: false,
                nodes: [],
                edges: [],
                viewport: { x: 0, y: 0, zoom: 1 },
            });
            setIsCreateOpen(false);
            navigate(`/flows/editor/${newFlow.id}`);
        } catch (error) {
            console.error('Failed to create flow', error);
            setFetchError('Nao foi possivel criar o fluxo.');
        } finally {
            setCreating(false);
        }
    };

    const confirmDeleteFlow = async () => {
        if (!flowToDelete) return;

        try {
            setDeleting(true);
            setFetchError('');
            await deleteFlow(flowToDelete.id);
            setFlowToDelete(null);
            await fetchFlows();
        } catch (error) {
            console.error('Failed to delete flow', error);
            setFetchError('Nao foi possivel excluir o fluxo.');
        } finally {
            setDeleting(false);
        }
    };

    const confirmRenameFlow = async (name: string) => {
        if (!flowToRename) return;

        try {
            setRenaming(true);
            setFetchError('');
            const updatedFlow = await updateFlow(flowToRename.id, { name });
            setFlows((currentFlows) =>
                currentFlows.map((flow) => (
                    flow.id === updatedFlow.id
                        ? { ...flow, name: updatedFlow.name, updated_at: updatedFlow.updated_at }
                        : flow
                ))
            );
            setFlowToRename(null);
        } catch (error) {
            console.error('Failed to rename flow', error);
            setFetchError('Nao foi possivel editar o nome do fluxo.');
        } finally {
            setRenaming(false);
        }
    };

    return (
        <div className={agentivePageClass(isDark, 'px-4 pb-28 pt-4 sm:px-6 lg:px-8 xl:px-10')}>
            <div className="mx-auto max-w-screen-2xl space-y-5">
                <AgentivePageHeader
                    icon={GitMerge}
                    title="Automações"
                    description="Modele fluxos visuais com gatilhos de WhatsApp, Webhook, Agenda e CRM conectados a acoes de atendimento e IA."
                    badges={<span className={agentivePillClass(isDark, true)}>Flow Builder</span>}
                    actions={(
                        <>
                            <button
                                type="button"
                                onClick={() => fetchFlows()}
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
                                Novo fluxo
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
                                    <h2 className="mt-1 text-lg font-semibold">Fluxos configurados</h2>
                                    <p className={`mt-1 text-sm ${isDark ? 'text-white/55' : 'text-brand/55'}`}>
                                        {filteredFlows.length} de {flows.length} fluxos exibidos.
                                    </p>
                                </div>

                                <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
                                    <div className="relative min-w-0 lg:w-72">
                                        <Search className={`pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${isDark ? 'text-white/35' : 'text-brand/35'}`} />
                                        <input
                                            type="search"
                                            value={searchTerm}
                                            onChange={(event) => setSearchTerm(event.target.value)}
                                            placeholder="Buscar automação"
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
                                    <span className="text-sm font-medium">Carregando automações</span>
                                </div>
                            ) : flows.length === 0 ? (
                                <AgentiveEmptyState
                                    icon={GitMerge}
                                    title="Nenhuma automação criada"
                                    description="Crie seu primeiro fluxo visual conectando um gatilho a modulos de CRM, IA e mensagens."
                                    action={(
                                        <button type="button" onClick={() => openCreateModal()} className={agentivePrimaryButtonClass('px-4')}>
                                            <Plus className="h-4 w-4" />
                                            Criar fluxo
                                        </button>
                                    )}
                                />
                            ) : filteredFlows.length === 0 ? (
                                <AgentiveEmptyState
                                    icon={Search}
                                    title="Nenhum fluxo encontrado"
                                    description="Ajuste a busca ou o filtro de status para encontrar outra automação."
                                />
                            ) : (
                                <div className={`overflow-hidden rounded-2xl border ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
                                    <div className="overflow-x-auto">
                                        <table className="min-w-[780px] w-full border-collapse text-sm">
                                            <thead className={isDark ? 'bg-white/[0.04] text-white/45' : 'bg-brand-canvas text-brand/45'}>
                                                <tr className="text-left text-[10px] font-bold uppercase tracking-[0.16em]">
                                                    <th className="px-4 py-3">Fluxo</th>
                                                    <th className="px-4 py-3">Status</th>
                                                    <th className="px-4 py-3">Gatilho</th>
                                                    <th className="px-4 py-3">Nodes</th>
                                                    <th className="px-4 py-3">Última edição</th>
                                                    <th className="px-4 py-3 text-right">Ações</th>
                                                </tr>
                                            </thead>
                                            <tbody className={`divide-y ${isDark ? 'divide-white/10' : 'divide-brand/10'}`}>
                                                {filteredFlows.map((flow) => {
                                                    const triggerLabel = getTriggerLabel(flow);
                                                    const nodeCount = flow.nodes?.length || 0;

                                                    return (
                                                        <tr
                                                            key={flow.id}
                                                            onClick={() => navigate(`/flows/editor/${flow.id}`)}
                                                            className={`group cursor-pointer transition ${
                                                                isDark ? 'hover:bg-white/[0.06]' : 'hover:bg-brand-canvas'
                                                            }`}
                                                        >
                                                            <td className="px-4 py-3">
                                                                <div className="flex min-w-0 items-center gap-3">
                                                                    <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ${flow.is_active ? 'bg-emerald-500/10 text-emerald-600' : isDark ? 'bg-white/10 text-white/70' : 'bg-brand-canvas text-brand/70'}`}>
                                                                        <GitMerge className="h-4 w-4" />
                                                                    </span>
                                                                    <div className="min-w-0">
                                                                        <p className="truncate font-semibold">{flow.name}</p>
                                                                        <p className={`mt-0.5 text-xs ${isDark ? 'text-white/45' : 'text-brand/45'}`}>
                                                                            ID #{flow.id}
                                                                        </p>
                                                                    </div>
                                                                </div>
                                                            </td>
                                                            <td className="px-4 py-3">
                                                                <span className={agentivePillClass(isDark, flow.is_active)}>
                                                                    {flow.is_active ? 'Ativo' : 'Rascunho'}
                                                                </span>
                                                            </td>
                                                            <td className="px-4 py-3">
                                                                <span className={agentivePillClass(isDark)}>
                                                                    {triggerLabel}
                                                                </span>
                                                            </td>
                                                            <td className={`px-4 py-3 font-medium ${isDark ? 'text-white/65' : 'text-brand/65'}`}>
                                                                {nodeCount}
                                                            </td>
                                                            <td className={`px-4 py-3 ${isDark ? 'text-white/55' : 'text-brand/55'}`}>
                                                                {formatDate(flow.updated_at)}
                                                            </td>
                                                            <td className="px-4 py-3">
                                                                <div className="flex items-center justify-end gap-2">
                                                                    <button
                                                                        type="button"
                                                                        onClick={(event) => {
                                                                            event.stopPropagation();
                                                                            setFlowToRename(flow);
                                                                        }}
                                                                        className={agentiveIconButtonClass(isDark, 'primary')}
                                                                        title="Editar nome"
                                                                        aria-label={`Editar nome de ${flow.name}`}
                                                                    >
                                                                        <Edit2 className="h-4 w-4" />
                                                                    </button>
                                                                    <button
                                                                        type="button"
                                                                        onClick={(event) => {
                                                                            event.stopPropagation();
                                                                            setFlowToDelete(flow);
                                                                        }}
                                                                        className={agentiveIconButtonClass(isDark, 'danger')}
                                                                        title="Excluir fluxo"
                                                                        aria-label={`Excluir ${flow.name}`}
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
                        onSubmit={handleCreateFlow}
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
                                    <h3 className="text-base font-semibold leading-tight">Novo fluxo</h3>
                                    <p className={`mt-1.5 text-sm leading-relaxed ${isDark ? 'text-white/60' : 'text-brand/60'}`}>
                                        Nomeie a automação. O desenho dos nodes acontece no editor visual.
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
                                Nome da automação
                            </label>
                            <input
                                autoFocus
                                value={newFlowName}
                                onChange={(event) => setNewFlowName(event.target.value)}
                                placeholder="Ex: Qualificar leads do WhatsApp"
                                className={agentiveInputClass(isDark)}
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
                confirmText="Excluir fluxo"
                isLoading={deleting}
                isOpen={Boolean(flowToDelete)}
                message={(
                    <>
                        Esta ação remove <strong>{flowToDelete?.name}</strong> e suas conexões salvas. Essa alteração não pode ser desfeita.
                    </>
                )}
                onClose={() => setFlowToDelete(null)}
                onConfirm={confirmDeleteFlow}
                title="Excluir automação?"
                variant="danger"
            />

            <FlowRenameModal
                initialName={flowToRename?.name || ''}
                isDark={isDark}
                isOpen={Boolean(flowToRename)}
                isSaving={renaming}
                onClose={() => setFlowToRename(null)}
                onSubmit={confirmRenameFlow}
            />
        </div>
    );
};

export default FlowList;
