import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
    Plus,
    Edit2,
    Trash2,
    X,
    Check,
    Loader2,
    Megaphone,
    Search,
    RadioTower,
    CircleDot,
    PauseCircle,
    Power,
    RefreshCw,
    SlidersHorizontal,
    Hash,
} from 'lucide-react';
import {
    getMediaSources,
    createMediaSource,
    updateMediaSource,
    deleteMediaSource,
    MediaSource,
} from '../services/mediaApi.ts';
import ConfirmDeleteModal from '../components/ConfirmDeleteModal.tsx';
import {
    AgentiveAlert,
    AgentiveEmptyState,
    AgentivePageHeader,
    agentiveIconButtonClass,
    agentiveInputClass,
    agentivePageClass,
    agentivePanelClass,
    agentivePrimaryButtonClass,
    agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';

type MediaFilter = 'all' | 'active' | 'inactive';

const cx = (...classes: Array<string | false | null | undefined>) => classes.filter(Boolean).join(' ');

const filterOptions: Array<{ id: MediaFilter; label: string }> = [
    { id: 'all', label: 'Todos' },
    { id: 'active', label: 'Ativas' },
    { id: 'inactive', label: 'Inativas' },
];

const isSourceActive = (source: MediaSource) => source.active !== false;

const MediaManagement: React.FC = () => {
    const { isDark } = useTheme();
    const [mediaSources, setMediaSources] = useState<MediaSource[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const [editingSource, setEditingSource] = useState<MediaSource | null>(null);
    const [showNewSource, setShowNewSource] = useState(false);
    const [newSourceName, setNewSourceName] = useState('');
    const [searchTerm, setSearchTerm] = useState('');
    const [statusFilter, setStatusFilter] = useState<MediaFilter>('all');
    const [actionLoading, setActionLoading] = useState(false);
    const [updatingSourceId, setUpdatingSourceId] = useState<number | null>(null);
    const [sourceToDelete, setSourceToDelete] = useState<MediaSource | null>(null);

    const fetchData = useCallback(async () => {
        try {
            setLoading(true);
            setError(null);
            const data = await getMediaSources();
            setMediaSources(data);
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Erro ao carregar mídias');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchData();
    }, [fetchData]);

    const handleCreateSource = async () => {
        if (!newSourceName.trim()) return;
        try {
            setActionLoading(true);
            await createMediaSource({
                name: newSourceName.trim(),
                active: true,
            });
            setNewSourceName('');
            setShowNewSource(false);
            await fetchData();
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Erro ao criar mídia');
        } finally {
            setActionLoading(false);
        }
    };

    const handleUpdateSource = async (source: MediaSource) => {
        if (!source.name.trim()) {
            setError('Informe o nome da mídia antes de salvar.');
            return;
        }

        try {
            setUpdatingSourceId(source.id);
            await updateMediaSource(source.id, {
                name: source.name.trim(),
                active: isSourceActive(source),
            });
            setEditingSource(null);
            await fetchData();
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Erro ao atualizar mídia');
        } finally {
            setUpdatingSourceId(null);
        }
    };

    const handleToggleSource = async (source: MediaSource) => {
        try {
            setUpdatingSourceId(source.id);
            await updateMediaSource(source.id, {
                active: !isSourceActive(source),
            });
            await fetchData();
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Erro ao alterar status da mídia');
        } finally {
            setUpdatingSourceId(null);
        }
    };

    const handleDeleteSource = async (sourceId: number) => {
        const source = mediaSources.find(item => item.id === sourceId);
        if (source) setSourceToDelete(source);
    };

    const confirmDeleteSource = async () => {
        if (!sourceToDelete) return;
        try {
            setActionLoading(true);
            await deleteMediaSource(sourceToDelete.id);
            setSourceToDelete(null);
            await fetchData();
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Erro ao excluir mídia');
        } finally {
            setActionLoading(false);
        }
    };

    const metrics = useMemo(() => {
        const active = mediaSources.filter(isSourceActive).length;
        const inactive = mediaSources.length - active;

        return {
            total: mediaSources.length,
            active,
            inactive,
        };
    }, [mediaSources]);

    const filteredSources = useMemo(() => {
        const normalizedSearch = searchTerm.trim().toLowerCase();

        return mediaSources.filter(source => {
            const matchesSearch = !normalizedSearch || source.name.toLowerCase().includes(normalizedSearch);
            const matchesStatus =
                statusFilter === 'all'
                || (statusFilter === 'active' && isSourceActive(source))
                || (statusFilter === 'inactive' && !isSourceActive(source));

            return matchesSearch && matchesStatus;
        });
    }, [mediaSources, searchTerm, statusFilter]);

    const mutedTextClass = isDark ? 'text-white/55' : 'text-brand/55';
    const subtlePanelClass = isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas';

    if (loading) {
        return (
            <div className={agentivePageClass(isDark, 'flex items-center justify-center p-4')}>
                <div className={agentivePanelClass(isDark, 'flex items-center gap-3 p-4')}>
                    <Loader2 className={cx('h-5 w-5 animate-spin', isDark ? 'text-white' : 'text-brand')} />
                    <span className={cx('text-sm font-medium', mutedTextClass)}>Carregando canais e origens...</span>
                </div>
            </div>
        );
    }

    return (
        <div className={agentivePageClass(isDark, 'pb-[calc(8rem+env(safe-area-inset-bottom))] sm:pb-10')}>
            <div className="mx-auto w-full max-w-screen-xl space-y-5 p-4 sm:p-6 lg:p-8">
                <AgentivePageHeader
                    icon={RadioTower}
                    title="Canais & Origens"
                    description="Organize as fontes de aquisição usadas pelo CRM, filtros e relatórios comerciais."
                    badges={(
                        <span className={cx('rounded-full border px-2.5 py-1 text-xs font-semibold', isDark ? 'border-white/10 bg-white/[0.06] text-white/65' : 'border-brand/10 bg-brand-canvas text-brand/60')}>
                            Configurações
                        </span>
                    )}
                    actions={(
                        <button
                            type="button"
                            onClick={() => setShowNewSource(true)}
                            className={agentivePrimaryButtonClass('w-full sm:w-auto')}
                        >
                            <Plus className="h-4 w-4" />
                            Nova mídia
                        </button>
                    )}
                />

                {error && (
                    <AgentiveAlert variant="error" title="Não foi possível concluir a ação" onClose={() => setError(null)}>
                        {error}
                    </AgentiveAlert>
                )}

                <section className="grid gap-3 sm:grid-cols-3">
                    <div className={agentivePanelClass(isDark, 'p-4 shadow-flat')}>
                        <div className="flex items-center justify-between gap-3">
                            <div>
                                <p className={cx('text-xs font-semibold uppercase tracking-[0.14em]', mutedTextClass)}>Catálogo</p>
                                <p className="mt-2 text-3xl font-semibold leading-none">{metrics.total}</p>
                            </div>
                            <span className={cx('grid h-10 w-10 place-items-center rounded-xl', isDark ? 'bg-white/10 text-white' : 'bg-brand text-white')}>
                                <Megaphone className="h-5 w-5" />
                            </span>
                        </div>
                        <p className={cx('mt-2 text-xs', mutedTextClass)}>origens cadastradas</p>
                    </div>

                    <div className={agentivePanelClass(isDark, 'p-4 shadow-flat')}>
                        <div className="flex items-center justify-between gap-3">
                            <div>
                                <p className={cx('text-xs font-semibold uppercase tracking-[0.14em]', mutedTextClass)}>Ativas</p>
                                <p className="mt-2 text-3xl font-semibold leading-none">{metrics.active}</p>
                            </div>
                            <span className={cx('grid h-10 w-10 place-items-center rounded-xl', isDark ? 'bg-emerald-400/10 text-emerald-300' : 'bg-emerald-50 text-emerald-700')}>
                                <CircleDot className="h-5 w-5" />
                            </span>
                        </div>
                        <p className={cx('mt-2 text-xs', mutedTextClass)}>disponíveis em novos registros</p>
                    </div>

                    <div className={agentivePanelClass(isDark, 'p-4 shadow-flat')}>
                        <div className="flex items-center justify-between gap-3">
                            <div>
                                <p className={cx('text-xs font-semibold uppercase tracking-[0.14em]', mutedTextClass)}>Pausadas</p>
                                <p className="mt-2 text-3xl font-semibold leading-none">{metrics.inactive}</p>
                            </div>
                            <span className={cx('grid h-10 w-10 place-items-center rounded-xl', isDark ? 'bg-amber-400/10 text-amber-300' : 'bg-amber-50 text-amber-700')}>
                                <PauseCircle className="h-5 w-5" />
                            </span>
                        </div>
                        <p className={cx('mt-2 text-xs', mutedTextClass)}>mantidas para histórico</p>
                    </div>
                </section>

                <section className={agentivePanelClass(isDark, 'overflow-hidden')}>
                    <div className={cx('border-b p-4 sm:p-5', isDark ? 'border-white/10' : 'border-brand/10')}>
                        <div className="grid gap-4 lg:grid-cols-[minmax(260px,1fr)_auto] lg:items-end">
                            <div>
                                <div className={cx('mb-2 flex w-fit items-center gap-2 rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em]', subtlePanelClass, mutedTextClass)}>
                                    <SlidersHorizontal className="h-3.5 w-3.5" />
                                    Governança de origem
                                </div>
                                <h2 className="text-lg font-semibold sm:text-xl">Origens de tráfego</h2>
                                <p className={cx('mt-1 max-w-2xl text-sm', mutedTextClass)}>
                                    Use nomes consistentes para manter CRM, relatórios e automações alinhados.
                                </p>
                            </div>

                            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                                <div className={cx('relative min-w-0 sm:w-72')}>
                                    <Search className={cx('pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2', isDark ? 'text-white/35' : 'text-brand/35')} />
                                    <input
                                        type="search"
                                        value={searchTerm}
                                        onChange={event => setSearchTerm(event.target.value)}
                                        placeholder="Buscar mídia"
                                        className={agentiveInputClass(isDark, 'pl-9')}
                                    />
                                </div>

                                <button
                                    type="button"
                                    onClick={fetchData}
                                    className={agentiveSecondaryButtonClass(isDark, 'shrink-0')}
                                    disabled={actionLoading || updatingSourceId !== null}
                                >
                                    <RefreshCw className="h-4 w-4" />
                                    Atualizar
                                </button>
                            </div>
                        </div>

                        <div className={cx('mt-4 grid grid-cols-3 gap-1 rounded-2xl border p-1.5 sm:w-fit', isDark ? 'border-white/10 bg-black/15' : 'border-brand/10 bg-brand-canvas')}>
                            {filterOptions.map(option => {
                                const isActive = statusFilter === option.id;

                                return (
                                    <button
                                        key={option.id}
                                        type="button"
                                        onClick={() => setStatusFilter(option.id)}
                                        className={cx(
                                            'rounded-xl border px-3 py-2 text-xs font-semibold transition-all',
                                            isActive
                                                ? isDark
                                                    ? 'border-white bg-white text-brand shadow-[0_10px_24px_rgba(255,255,255,0.08)]'
                                                    : 'border-brand bg-brand text-white shadow-[0_10px_24px_rgba(2,3,35,0.12)]'
                                                : isDark
                                                    ? 'border-transparent text-white/55 hover:border-white/10 hover:bg-white/[0.06] hover:text-white'
                                                    : 'border-transparent text-brand/55 hover:border-brand/10 hover:bg-white hover:text-brand'
                                        )}
                                    >
                                        {option.label}
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    <div className="space-y-3 p-4 sm:p-5">
                        {showNewSource && (
                            <div className={cx('rounded-2xl border p-3 shadow-flat', subtlePanelClass)}>
                                <div className="flex flex-col gap-3 md:flex-row md:items-center">
                                    <span className={cx('grid h-11 w-11 shrink-0 place-items-center rounded-xl', isDark ? 'bg-white/10 text-white' : 'bg-white text-brand')}>
                                        <Plus className="h-5 w-5" />
                                    </span>
                                    <div className="min-w-0 flex-1">
                                        <label className={cx('mb-1.5 block text-xs font-semibold uppercase tracking-[0.1em]', mutedTextClass)}>
                                            Nova origem
                                        </label>
                                        <input
                                            type="text"
                                            value={newSourceName}
                                            onChange={event => setNewSourceName(event.target.value)}
                                            placeholder="Nome da mídia, ex: Facebook Ads"
                                            className={agentiveInputClass(isDark)}
                                            onKeyDown={event => event.key === 'Enter' && handleCreateSource()}
                                            autoFocus
                                        />
                                    </div>
                                    <div className="flex items-center gap-2 md:self-end">
                                        <button
                                            type="button"
                                            onClick={handleCreateSource}
                                            disabled={actionLoading || !newSourceName.trim()}
                                            className={agentivePrimaryButtonClass('flex-1 px-3 md:flex-none')}
                                        >
                                            {actionLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                                            Salvar
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => { setShowNewSource(false); setNewSourceName(''); }}
                                            className={agentiveSecondaryButtonClass(isDark, 'flex-1 px-3 md:flex-none')}
                                            disabled={actionLoading}
                                        >
                                            <X className="h-4 w-4" />
                                            Cancelar
                                        </button>
                                    </div>
                                </div>
                            </div>
                        )}

                        {mediaSources.length === 0 && !showNewSource ? (
                            <AgentiveEmptyState
                                icon={RadioTower}
                                title="Nenhuma mídia cadastrada"
                                description="Cadastre canais de aquisição para qualificar contatos e relatórios."
                                action={(
                                    <button
                                        type="button"
                                        onClick={() => setShowNewSource(true)}
                                        className={agentivePrimaryButtonClass()}
                                    >
                                        <Plus className="h-4 w-4" />
                                        Cadastrar primeira mídia
                                    </button>
                                )}
                            />
                        ) : filteredSources.length === 0 ? (
                            <AgentiveEmptyState
                                icon={Search}
                                title="Nenhum resultado encontrado"
                                description="Ajuste a busca ou o filtro para encontrar outras origens cadastradas."
                                action={(
                                    <button
                                        type="button"
                                        onClick={() => {
                                            setSearchTerm('');
                                            setStatusFilter('all');
                                        }}
                                        className={agentiveSecondaryButtonClass(isDark)}
                                    >
                                        <X className="h-4 w-4" />
                                        Limpar filtros
                                    </button>
                                )}
                            />
                        ) : (
                            <div className={cx('overflow-hidden rounded-2xl border shadow-flat', isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-white')}>
                                <div className="overflow-x-auto">
                                    <table className="min-w-[820px] w-full">
                                        <thead className={isDark ? 'bg-white/[0.04]' : 'bg-brand-canvas'}>
                                            <tr>
                                                <th className={cx('px-4 py-3 text-left text-[10px] font-bold uppercase tracking-[0.14em]', mutedTextClass)}>
                                                    Origem
                                                </th>
                                                <th className={cx('px-4 py-3 text-left text-[10px] font-bold uppercase tracking-[0.14em]', mutedTextClass)}>
                                                    Status
                                                </th>
                                                <th className={cx('px-4 py-3 text-left text-[10px] font-bold uppercase tracking-[0.14em]', mutedTextClass)}>
                                                    Tipo
                                                </th>
                                                <th className={cx('px-4 py-3 text-left text-[10px] font-bold uppercase tracking-[0.14em]', mutedTextClass)}>
                                                    ID
                                                </th>
                                                <th className={cx('px-4 py-3 text-right text-[10px] font-bold uppercase tracking-[0.14em]', mutedTextClass)}>
                                                    Ações
                                                </th>
                                            </tr>
                                        </thead>
                                        <tbody className={cx('divide-y', isDark ? 'divide-white/10' : 'divide-brand/10')}>
                                            {filteredSources.map(source => {
                                                const sourceActive = isSourceActive(source);
                                                const sourceInitial = source.name.trim().charAt(0).toUpperCase() || '#';
                                                const isUpdating = updatingSourceId === source.id;
                                                const isEditing = editingSource?.id === source.id;

                                                return (
                                                    <tr
                                                        key={source.id}
                                                        className={cx('transition-colors', isDark ? 'hover:bg-white/[0.05]' : 'hover:bg-brand-canvas/70')}
                                                    >
                                                        <td className="px-4 py-3">
                                                            <div className="flex min-w-0 items-center gap-3">
                                                                <span className={cx('grid h-10 w-10 shrink-0 place-items-center rounded-xl text-sm font-semibold', sourceActive ? (isDark ? 'bg-white text-brand' : 'bg-brand text-white') : (isDark ? 'bg-white/10 text-white/55' : 'bg-brand-canvas text-brand/55'))}>
                                                                    {sourceInitial}
                                                                </span>
                                                                <div className="min-w-0 flex-1">
                                                                    {isEditing ? (
                                                                        <input
                                                                            type="text"
                                                                            value={editingSource.name}
                                                                            onChange={event => setEditingSource({ ...editingSource, name: event.target.value })}
                                                                            className={agentiveInputClass(isDark, 'min-w-[240px] py-2')}
                                                                            onKeyDown={event => {
                                                                                if (event.key === 'Enter') handleUpdateSource(editingSource);
                                                                                if (event.key === 'Escape') setEditingSource(null);
                                                                            }}
                                                                            autoFocus
                                                                        />
                                                                    ) : (
                                                                        <>
                                                                            <p className="truncate text-sm font-semibold">{source.name}</p>
                                                                            <p className={cx('mt-0.5 text-xs', mutedTextClass)}>Origem de aquisição</p>
                                                                        </>
                                                                    )}
                                                                </div>
                                                            </div>
                                                        </td>
                                                        <td className="px-4 py-3">
                                                            <span className={cx('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1', sourceActive ? (isDark ? 'bg-emerald-400/10 text-emerald-300 ring-emerald-400/20' : 'bg-emerald-50 text-emerald-700 ring-emerald-200') : (isDark ? 'bg-amber-400/10 text-amber-300 ring-amber-400/20' : 'bg-amber-50 text-amber-700 ring-amber-200'))}>
                                                                {sourceActive ? <CircleDot className="h-3.5 w-3.5" /> : <PauseCircle className="h-3.5 w-3.5" />}
                                                                {sourceActive ? 'Ativa' : 'Pausada'}
                                                            </span>
                                                        </td>
                                                        <td className="px-4 py-3">
                                                            <span className={cx('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium', subtlePanelClass, mutedTextClass)}>
                                                                <RadioTower className="h-3.5 w-3.5" />
                                                                Aquisição
                                                            </span>
                                                        </td>
                                                        <td className="px-4 py-3">
                                                            <span className={cx('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium', subtlePanelClass, mutedTextClass)}>
                                                                <Hash className="h-3.5 w-3.5" />
                                                                {source.id}
                                                            </span>
                                                        </td>
                                                        <td className="px-4 py-3">
                                                            <div className="flex items-center justify-end gap-1.5">
                                                                <button
                                                                    type="button"
                                                                    onClick={() => handleToggleSource(source)}
                                                                    disabled={isUpdating || actionLoading || isEditing}
                                                                    className={cx(
                                                                        'inline-flex h-9 items-center justify-center gap-2 rounded-xl border px-3 text-xs font-semibold transition-colors disabled:opacity-50',
                                                                        sourceActive
                                                                            ? isDark
                                                                                ? 'border-amber-400/20 text-amber-300 hover:bg-amber-400/10'
                                                                                : 'border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100'
                                                                            : isDark
                                                                                ? 'border-emerald-400/20 text-emerald-300 hover:bg-emerald-400/10'
                                                                                : 'border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
                                                                    )}
                                                                >
                                                                    {isUpdating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Power className="h-4 w-4" />}
                                                                    {sourceActive ? 'Pausar' : 'Ativar'}
                                                                </button>

                                                                {isEditing ? (
                                                                    <>
                                                                        <button
                                                                            type="button"
                                                                            onClick={() => handleUpdateSource(editingSource)}
                                                                            disabled={isUpdating}
                                                                            className={agentiveIconButtonClass(isDark, 'success')}
                                                                            aria-label="Salvar mídia"
                                                                            title="Salvar mídia"
                                                                        >
                                                                            {isUpdating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                                                                        </button>
                                                                        <button
                                                                            type="button"
                                                                            onClick={() => setEditingSource(null)}
                                                                            disabled={isUpdating}
                                                                            className={agentiveIconButtonClass(isDark)}
                                                                            aria-label="Cancelar edição"
                                                                            title="Cancelar edição"
                                                                        >
                                                                            <X className="h-4 w-4" />
                                                                        </button>
                                                                    </>
                                                                ) : (
                                                                    <>
                                                                        <button
                                                                            type="button"
                                                                            onClick={() => setEditingSource(source)}
                                                                            className={agentiveIconButtonClass(isDark)}
                                                                            aria-label={`Editar ${source.name}`}
                                                                            title="Editar"
                                                                        >
                                                                            <Edit2 className="h-4 w-4" />
                                                                        </button>
                                                                        <button
                                                                            type="button"
                                                                            onClick={() => handleDeleteSource(source.id)}
                                                                            className={agentiveIconButtonClass(isDark, 'danger')}
                                                                            aria-label={`Excluir ${source.name}`}
                                                                            title="Excluir"
                                                                        >
                                                                            <Trash2 className="h-4 w-4" />
                                                                        </button>
                                                                    </>
                                                                )}
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
            <ConfirmDeleteModal
                isOpen={Boolean(sourceToDelete)}
                onClose={() => setSourceToDelete(null)}
                onConfirm={confirmDeleteSource}
                isLoading={actionLoading}
                title="Excluir mídia?"
                message="Leads existentes manterão o histórico, mas esta opção não poderá ser usada em novos registros."
                confirmText="Excluir mídia"
            >
                <span className={isDark ? 'text-white/80' : 'text-brand/70'}>
                    Mídia selecionada: <strong>{sourceToDelete?.name}</strong>
                </span>
            </ConfirmDeleteModal>
        </div>
    );
};

export default MediaManagement;
