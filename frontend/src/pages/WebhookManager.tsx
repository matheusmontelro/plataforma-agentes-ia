import React, { useEffect, useMemo, useState } from 'react';
import {
    Activity,
    Check,
    Clock3,
    Code2,
    Copy,
    Database,
    Edit2,
    Inbox,
    ListFilter,
    Plus,
    RefreshCw,
    Search,
    ShieldCheck,
    Trash2,
    Webhook
} from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
    createWebhook,
    deleteWebhook,
    getWebhookEvents,
    getWebhooks,
    getWebhookUrl,
    updateWebhook,
    type WebhookEvent,
    type WebhookTrigger
} from '../services/webhookBuilderApi';
import ConfirmDeleteModal from '../components/ConfirmDeleteModal';
import {
    AgentiveAlert,
    AgentiveEmptyState,
    AgentivePageHeader,
    AgentiveStatCard,
    agentiveIconButtonClass,
    agentiveInputClass,
    agentiveLabelClass,
    agentivePageClass,
    agentivePanelClass,
    agentivePillClass,
    agentivePrimaryButtonClass,
    agentiveSecondaryButtonClass,
    agentiveTextareaClass,
} from '../components/AgentiveUI';

type StatusFilter = 'all' | 'active' | 'inactive';

const dateFormatter = new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
});

const fullDateFormatter = new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
});

const formatDate = (value?: string | null) => {
    if (!value) return 'Sem eventos';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Data inválida';
    return dateFormatter.format(date);
};

const formatDateTime = (value?: string | null) => {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '-';
    return fullDateFormatter.format(date);
};

const formatRelativeTime = (value?: string | null) => {
    if (!value) return 'Sem eventos';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Data inválida';

    const diffMinutes = Math.max(0, Math.round((Date.now() - date.getTime()) / 60000));
    if (diffMinutes < 1) return 'agora';
    if (diffMinutes < 60) return `${diffMinutes} min`;

    const diffHours = Math.round(diffMinutes / 60);
    if (diffHours < 24) return `${diffHours} h`;

    const diffDays = Math.round(diffHours / 24);
    return `${diffDays} d`;
};

const truncateMiddle = (value: string, start = 34, end = 18) => {
    if (value.length <= start + end + 3) return value;
    return `${value.slice(0, start)}...${value.slice(-end)}`;
};

const formatPayloadPreview = (payload: unknown) => {
    if (payload === null || payload === undefined || payload === '') return 'Sem payload';

    if (typeof payload === 'string') {
        return payload.length > 260 ? `${payload.slice(0, 260)}...` : payload;
    }

    try {
        const serialized = JSON.stringify(payload, null, 2);
        return serialized.length > 360 ? `${serialized.slice(0, 360)}...` : serialized;
    } catch {
        const fallback = String(payload);
        return fallback.length > 260 ? `${fallback.slice(0, 260)}...` : fallback;
    }
};

const eventStatusLabel = (status: string, statusCode: number) => {
    if (status === 'received' && statusCode >= 200 && statusCode < 300) return 'Recebido';
    if (status === 'inactive') return 'Inativo';
    return status || `${statusCode}`;
};

const copyTextToClipboard = async (text: string) => {
    if (navigator.clipboard?.writeText && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return;
    }

    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.setAttribute('readonly', '');
    textArea.style.position = 'fixed';
    textArea.style.left = '-9999px';
    textArea.style.top = '0';
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();

    try {
        const copied = document.execCommand('copy');
        if (!copied) {
            throw new Error('Fallback clipboard copy failed');
        }
    } finally {
        document.body.removeChild(textArea);
    }
};

const WebhookManager: React.FC = () => {
    const { isDark } = useTheme();
    const [webhooks, setWebhooks] = useState<WebhookTrigger[]>([]);
    const [events, setEvents] = useState<WebhookEvent[]>([]);
    const [loading, setLoading] = useState(true);
    const [eventsLoading, setEventsLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [editingWebhook, setEditingWebhook] = useState<WebhookTrigger | null>(null);
    const [webhookToDelete, setWebhookToDelete] = useState<WebhookTrigger | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [query, setQuery] = useState('');
    const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
    const [selectedWebhookId, setSelectedWebhookId] = useState('all');
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [copiedId, setCopiedId] = useState<number | null>(null);

    const mutedClass = isDark ? 'text-white/55' : 'text-brand/55';
    const subtleClass = isDark ? 'text-white/40' : 'text-brand/40';
    const borderClass = isDark ? 'border-white/10' : 'border-brand/10';
    const tableHeaderClass = isDark ? 'bg-white/[0.04] text-white/45' : 'bg-brand-canvas text-brand/45';
    const rowClass = isDark ? 'border-white/10 hover:bg-white/[0.04]' : 'border-brand/10 hover:bg-brand-canvas/70';

    const fetchWebhooks = async () => {
        try {
            setLoading(true);
            setError(null);
            const data = await getWebhooks();
            setWebhooks(data);
        } catch (error) {
            console.error('Failed to fetch webhooks', error);
            setError('Não foi possível carregar os webhooks.');
        } finally {
            setLoading(false);
        }
    };

    const fetchEvents = async (webhookId = selectedWebhookId) => {
        try {
            setEventsLoading(true);
            const parsedWebhookId = webhookId === 'all' ? undefined : Number(webhookId);
            const data = await getWebhookEvents({ limit: 80, webhook_id: parsedWebhookId });
            setEvents(data);
        } catch (error) {
            console.error('Failed to fetch webhook events', error);
            setError('Não foi possível carregar os eventos recebidos.');
        } finally {
            setEventsLoading(false);
        }
    };

    useEffect(() => {
        fetchWebhooks();
    }, []);

    useEffect(() => {
        fetchEvents(selectedWebhookId);
    }, [selectedWebhookId]);

    const latestEventByWebhook = useMemo(() => {
        const result = new Map<number, WebhookEvent>();
        events.forEach(event => {
            if (!event.webhook_id) return;
            if (!result.has(event.webhook_id)) {
                result.set(event.webhook_id, event);
            }
        });
        return result;
    }, [events]);

    const filteredWebhooks = useMemo(() => {
        const normalizedQuery = query.trim().toLowerCase();

        return webhooks.filter(hook => {
            const matchesStatus =
                statusFilter === 'all' ||
                (statusFilter === 'active' && hook.is_active) ||
                (statusFilter === 'inactive' && !hook.is_active);

            const matchesQuery =
                !normalizedQuery ||
                hook.name.toLowerCase().includes(normalizedQuery) ||
                hook.uuid.toLowerCase().includes(normalizedQuery) ||
                (hook.description || '').toLowerCase().includes(normalizedQuery);

            return matchesStatus && matchesQuery;
        });
    }, [query, statusFilter, webhooks]);

    const activeCount = webhooks.filter(hook => hook.is_active).length;
    const totalEvents = webhooks.reduce((sum, hook) => sum + (hook.event_count || 0), 0);
    const eventsLast24h = events.filter(event => {
        const receivedAt = new Date(event.received_at).getTime();
        return !Number.isNaN(receivedAt) && Date.now() - receivedAt <= 24 * 60 * 60 * 1000;
    }).length;
    const latestEvent = events[0];

    const handleRefresh = async () => {
        await Promise.all([fetchWebhooks(), fetchEvents()]);
    };

    const handleOpenModal = (webhook?: WebhookTrigger) => {
        if (webhook) {
            setEditingWebhook(webhook);
            setName(webhook.name);
            setDescription(webhook.description || '');
        } else {
            setEditingWebhook(null);
            setName('');
            setDescription('');
        }
        setIsModalOpen(true);
    };

    const handleCloseModal = () => {
        if (saving) return;
        setIsModalOpen(false);
        setEditingWebhook(null);
        setName('');
        setDescription('');
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        const trimmedName = name.trim();
        if (!trimmedName) return;

        try {
            setSaving(true);
            if (editingWebhook) {
                await updateWebhook(editingWebhook.id, { name: trimmedName, description: description.trim() });
            } else {
                await createWebhook({ name: trimmedName, description: description.trim() });
            }
            setIsModalOpen(false);
            setEditingWebhook(null);
            setName('');
            setDescription('');
            await fetchWebhooks();
        } catch (error) {
            console.error('Failed to save webhook', error);
            setError('Erro ao salvar webhook.');
        } finally {
            setSaving(false);
        }
    };

    const handleDelete = (id: number) => {
        const webhook = webhooks.find(item => item.id === id);
        if (webhook) setWebhookToDelete(webhook);
    };

    const confirmDelete = async () => {
        if (!webhookToDelete) return;
        try {
            await deleteWebhook(webhookToDelete.id);
            if (selectedWebhookId === String(webhookToDelete.id)) {
                setSelectedWebhookId('all');
            }
            setWebhookToDelete(null);
            await Promise.all([fetchWebhooks(), fetchEvents('all')]);
        } catch (error) {
            console.error('Failed to delete webhook', error);
            setError('Erro ao excluir webhook.');
        }
    };

    const handleCopyUrl = async (uuid: string, id: number) => {
        const url = getWebhookUrl(uuid);
        try {
            await copyTextToClipboard(url);
            setCopiedId(id);
            setTimeout(() => setCopiedId(null), 2000);
        } catch (error) {
            console.error('Failed to copy webhook URL', error);
            setError('Não foi possível copiar a URL.');
        }
    };

    return (
        <div className={agentivePageClass(isDark, 'p-4 sm:p-6')}>
            <div className="mx-auto max-w-screen-2xl space-y-5">
                <AgentivePageHeader
                    icon={Webhook}
                    title="Webhooks"
                    description="Entrada de eventos externos para automações, integrações e fluxos ativos."
                    badges={(
                        <span className={agentivePillClass(isDark, true)}>
                            Conexões
                        </span>
                    )}
                    actions={(
                        <>
                            <button
                                type="button"
                                onClick={handleRefresh}
                                className={agentiveSecondaryButtonClass(isDark, 'px-3')}
                                disabled={loading || eventsLoading}
                            >
                                <RefreshCw className={`w-4 h-4 ${loading || eventsLoading ? 'animate-spin' : ''}`} />
                                Atualizar
                            </button>
                            <button
                                type="button"
                                onClick={() => handleOpenModal()}
                                className={agentivePrimaryButtonClass('px-4')}
                            >
                                <Plus className="w-4 h-4" />
                                Novo webhook
                            </button>
                        </>
                    )}
                />

                {error && (
                    <AgentiveAlert variant="error" title="Ação não concluída" onClose={() => setError(null)}>
                        {error}
                    </AgentiveAlert>
                )}

                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    <AgentiveStatCard
                        icon={Webhook}
                        label="Webhooks"
                        value={webhooks.length}
                        helper={`${activeCount} ativos`}
                    />
                    <AgentiveStatCard
                        icon={ShieldCheck}
                        label="Operação"
                        value={webhooks.length ? `${Math.round((activeCount / webhooks.length) * 100)}%` : '0%'}
                        helper="endpoints ativos"
                    />
                    <AgentiveStatCard
                        icon={Database}
                        label="Eventos"
                        value={totalEvents}
                        helper={`${eventsLast24h} nas últimas 24h`}
                    />
                    <AgentiveStatCard
                        icon={Clock3}
                        label="Último evento"
                        value={formatRelativeTime(latestEvent?.received_at)}
                        helper={latestEvent?.webhook_name || 'Sem recebimentos'}
                    />
                </div>

                <section className={agentivePanelClass(isDark, 'overflow-hidden')}>
                    <div className={`border-b ${borderClass} p-4 sm:p-5`}>
                        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
                            <div>
                                <div className={`mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] ${subtleClass}`}>
                                    Gerenciamento
                                </div>
                                <h2 className="text-lg font-semibold">Endpoints configurados</h2>
                                <p className={`mt-1 text-sm ${mutedClass}`}>
                                    {filteredWebhooks.length} de {webhooks.length} webhooks exibidos.
                                </p>
                            </div>

                            <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
                                <div className={`relative min-w-0 lg:w-72`}>
                                    <Search className={`pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${subtleClass}`} />
                                    <input
                                        type="search"
                                        value={query}
                                        onChange={(event) => setQuery(event.target.value)}
                                        placeholder="Buscar webhook"
                                        className={agentiveInputClass(isDark, 'pl-9')}
                                    />
                                </div>

                                <div className={`flex items-center gap-1 rounded-2xl border p-1 ${isDark ? 'border-white/10 bg-black/15' : 'border-brand/10 bg-brand-canvas'}`}>
                                    <ListFilter className={`ml-2 h-4 w-4 ${subtleClass}`} />
                                    {[
                                        { id: 'all', label: 'Todos' },
                                        { id: 'active', label: 'Ativos' },
                                        { id: 'inactive', label: 'Inativos' },
                                    ].map(item => (
                                        <button
                                            key={item.id}
                                            type="button"
                                            onClick={() => setStatusFilter(item.id as StatusFilter)}
                                            className={agentivePillClass(isDark, statusFilter === item.id, 'border-transparent')}
                                        >
                                            {item.label}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </div>

                    {loading ? (
                        <div className="flex justify-center p-12">
                            <div className="h-11 w-11 animate-spin rounded-full border-b-2 border-brand" />
                        </div>
                    ) : webhooks.length === 0 ? (
                        <div className="p-4 sm:p-5">
                            <AgentiveEmptyState
                                icon={Inbox}
                                title="Nenhum webhook criado"
                                description="Crie um endpoint para receber eventos de formulários, anúncios, ERPs ou ferramentas externas."
                                action={(
                                    <button onClick={() => handleOpenModal()} className={agentivePrimaryButtonClass('px-5 py-3')}>
                                        <Plus className="h-4 w-4" />
                                        Criar webhook
                                    </button>
                                )}
                            />
                        </div>
                    ) : filteredWebhooks.length === 0 ? (
                        <div className="p-4 sm:p-5">
                            <AgentiveEmptyState
                                icon={Search}
                                title="Nenhum resultado encontrado"
                                description="Ajuste a busca ou o filtro de status para ver outros webhooks."
                            />
                        </div>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full min-w-[1080px] table-fixed">
                                <thead className={tableHeaderClass}>
                                    <tr>
                                        <th className="w-[27%] px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.08em]">Webhook</th>
                                        <th className="w-[28%] px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.08em]">URL</th>
                                        <th className="w-[10%] px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.08em]">Status</th>
                                        <th className="w-[13%] px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.08em]">Eventos</th>
                                        <th className="w-[13%] px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.08em]">Criado em</th>
                                        <th className="w-[9%] px-4 py-3 text-right text-xs font-semibold uppercase tracking-[0.08em]">Ações</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {filteredWebhooks.map(hook => {
                                        const url = getWebhookUrl(hook.uuid);
                                        const latestForHook = latestEventByWebhook.get(hook.id);
                                        const latestReceivedAt = latestForHook?.received_at || hook.last_event_at;

                                        return (
                                            <tr key={hook.id} className={`border-t transition-colors ${rowClass}`}>
                                                <td className="px-4 py-4 align-top">
                                                    <div className="flex min-w-0 items-start gap-3">
                                                        <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${hook.is_active ? 'bg-emerald-500/10 text-emerald-500' : isDark ? 'bg-white/10 text-white/45' : 'bg-brand-canvas text-brand/45'}`}>
                                                            <Activity className="h-5 w-5" />
                                                        </div>
                                                        <div className="min-w-0">
                                                            <div className="truncate text-sm font-semibold">{hook.name}</div>
                                                            <div className={`mt-1 line-clamp-2 text-xs leading-relaxed ${mutedClass}`}>
                                                                {hook.description || 'Sem descrição'}
                                                            </div>
                                                            <div className={`mt-2 font-mono text-[11px] ${subtleClass}`}>{hook.uuid.slice(0, 8)}...</div>
                                                        </div>
                                                    </div>
                                                </td>
                                                <td className="px-4 py-4 align-top">
                                                    <div className={`flex items-center gap-2 rounded-xl border px-3 py-2 ${isDark ? 'border-white/10 bg-brand text-white/65' : 'border-brand/10 bg-brand-canvas text-brand/60'}`}>
                                                        <Code2 className="h-4 w-4 shrink-0" />
                                                        <span className="truncate font-mono text-xs">{truncateMiddle(url)}</span>
                                                        <button
                                                            type="button"
                                                            onClick={() => handleCopyUrl(hook.uuid, hook.id)}
                                                            className={copiedId === hook.id ? agentiveIconButtonClass(isDark, 'success', 'ml-auto shrink-0 min-h-8 min-w-8 p-1.5') : agentiveIconButtonClass(isDark, 'neutral', 'ml-auto shrink-0 min-h-8 min-w-8 p-1.5')}
                                                            title="Copiar URL"
                                                        >
                                                            {copiedId === hook.id ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                                                        </button>
                                                    </div>
                                                </td>
                                                <td className="px-4 py-4 align-top">
                                                    <div className="space-y-2">
                                                        <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${hook.is_active ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200' : 'bg-red-50 text-red-700 ring-1 ring-red-200'}`}>
                                                            {hook.is_active ? 'Ativo' : 'Inativo'}
                                                        </span>
                                                        <div className={`font-mono text-xs ${mutedClass}`}>{hook.method}</div>
                                                    </div>
                                                </td>
                                                <td className="px-4 py-4 align-top">
                                                    <div className="text-sm font-semibold">{hook.event_count || 0}</div>
                                                    <div className={`mt-1 text-xs ${mutedClass}`}>{formatDate(latestReceivedAt)}</div>
                                                </td>
                                                <td className="px-4 py-4 align-top">
                                                    <div className="text-sm">{formatDateTime(hook.created_at)}</div>
                                                    <div className={`mt-1 text-xs ${mutedClass}`}>Atualizado {formatRelativeTime(hook.updated_at)}</div>
                                                </td>
                                                <td className="px-4 py-4 align-top">
                                                    <div className="flex justify-end gap-1">
                                                        <button
                                                            type="button"
                                                            onClick={() => handleOpenModal(hook)}
                                                            className={agentiveIconButtonClass(isDark)}
                                                            title="Editar"
                                                        >
                                                            <Edit2 className="h-4 w-4" />
                                                        </button>
                                                        <button
                                                            type="button"
                                                            onClick={() => handleDelete(hook.id)}
                                                            className={agentiveIconButtonClass(isDark, 'danger')}
                                                            title="Excluir"
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
                    )}
                </section>

                <section className={agentivePanelClass(isDark, 'overflow-hidden')}>
                    <div className={`flex flex-col gap-4 border-b ${borderClass} p-4 sm:p-5 lg:flex-row lg:items-end lg:justify-between`}>
                        <div>
                            <div className={`mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] ${subtleClass}`}>
                                Monitoramento
                            </div>
                            <h2 className="text-lg font-semibold">Eventos recebidos</h2>
                            <p className={`mt-1 text-sm ${mutedClass}`}>
                                Últimos eventos gravados para auditoria de integrações.
                            </p>
                        </div>

                        <select
                            value={selectedWebhookId}
                            onChange={(event) => setSelectedWebhookId(event.target.value)}
                            className={agentiveInputClass(isDark, 'lg:w-80')}
                        >
                            <option value="all">Todos os webhooks</option>
                            {webhooks.map(hook => (
                                <option key={hook.id} value={hook.id}>{hook.name}</option>
                            ))}
                        </select>
                    </div>

                    {eventsLoading ? (
                        <div className="flex justify-center p-10">
                            <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-brand" />
                        </div>
                    ) : events.length === 0 ? (
                        <div className="p-4 sm:p-5">
                            <AgentiveEmptyState
                                icon={Database}
                                title="Nenhum evento recebido"
                                description="Quando um endpoint receber uma requisição, ela aparecerá aqui com payload redigido."
                            />
                        </div>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full min-w-[980px] table-fixed">
                                <thead className={tableHeaderClass}>
                                    <tr>
                                        <th className="w-[16%] px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.08em]">Horário</th>
                                        <th className="w-[20%] px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.08em]">Webhook</th>
                                        <th className="w-[12%] px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.08em]">Status</th>
                                        <th className="w-[17%] px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.08em]">Origem</th>
                                        <th className="w-[35%] px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.08em]">Payload</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {events.map(event => (
                                        <tr key={event.id} className={`border-t transition-colors ${rowClass}`}>
                                            <td className="px-4 py-4 align-top">
                                                <div className="text-sm font-semibold">{formatDateTime(event.received_at)}</div>
                                                <div className={`mt-1 text-xs ${mutedClass}`}>{formatRelativeTime(event.received_at)}</div>
                                            </td>
                                            <td className="px-4 py-4 align-top">
                                                <div className="truncate text-sm font-semibold">{event.webhook_name || 'Webhook removido'}</div>
                                                <div className={`mt-1 truncate font-mono text-[11px] ${subtleClass}`}>{event.webhook_uuid || '-'}</div>
                                            </td>
                                            <td className="px-4 py-4 align-top">
                                                <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${event.status === 'received' ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200' : 'bg-amber-50 text-amber-700 ring-1 ring-amber-200'}`}>
                                                    {eventStatusLabel(event.status, event.status_code)}
                                                </span>
                                                <div className={`mt-1 font-mono text-xs ${mutedClass}`}>{event.method} {event.status_code}</div>
                                            </td>
                                            <td className="px-4 py-4 align-top">
                                                <div className="truncate text-sm">{event.source_ip || 'Origem não informada'}</div>
                                                <div className={`mt-1 truncate text-xs ${mutedClass}`}>{event.content_type || 'Sem content-type'}</div>
                                            </td>
                                            <td className="px-4 py-4 align-top">
                                                <pre className={`max-h-32 overflow-hidden whitespace-pre-wrap break-words rounded-xl border p-3 font-mono text-[11px] leading-relaxed ${isDark ? 'border-white/10 bg-brand text-white/65' : 'border-brand/10 bg-brand-canvas text-brand/65'}`}>
                                                    {formatPayloadPreview(event.payload_preview)}
                                                </pre>
                                                {event.payload_size !== null && event.payload_size !== undefined && (
                                                    <div className={`mt-1 text-[11px] ${subtleClass}`}>{event.payload_size} bytes</div>
                                                )}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </section>
            </div>

            {isModalOpen && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand/60 p-4 backdrop-blur-sm">
                    <div className={agentivePanelClass(isDark, 'w-full max-w-md p-6 shadow-[0_24px_70px_rgba(2,3,35,0.28)]')}>
                        <div className="mb-5 flex items-start gap-3">
                            <div className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
                                <Webhook className="h-5 w-5" />
                            </div>
                            <div>
                                <h2 className="text-xl font-semibold">
                                    {editingWebhook ? 'Editar webhook' : 'Novo webhook'}
                                </h2>
                                <p className={`mt-1 text-sm ${mutedClass}`}>
                                    {editingWebhook ? 'Atualize nome e descrição do endpoint.' : 'Crie um endpoint para receber eventos externos.'}
                                </p>
                            </div>
                        </div>

                        <form onSubmit={handleSubmit} className="space-y-4">
                            <div>
                                <label className={agentiveLabelClass(isDark)}>Nome</label>
                                <input
                                    type="text"
                                    required
                                    value={name}
                                    onChange={(e) => setName(e.target.value)}
                                    placeholder="Ex: Lead Ads Meta"
                                    className={agentiveInputClass(isDark, 'px-4')}
                                />
                            </div>

                            <div>
                                <label className={agentiveLabelClass(isDark)}>Descrição</label>
                                <textarea
                                    value={description}
                                    onChange={(e) => setDescription(e.target.value)}
                                    placeholder="Origem ou finalidade do webhook"
                                    rows={3}
                                    className={agentiveTextareaClass(isDark, 'px-4')}
                                />
                            </div>

                            <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row">
                                <button
                                    type="button"
                                    onClick={handleCloseModal}
                                    className={agentiveSecondaryButtonClass(isDark, 'flex-1')}
                                    disabled={saving}
                                >
                                    Cancelar
                                </button>
                                <button
                                    type="submit"
                                    className={agentivePrimaryButtonClass('flex-1')}
                                    disabled={saving || !name.trim()}
                                >
                                    {saving ? 'Salvando...' : editingWebhook ? 'Salvar' : 'Criar'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            <ConfirmDeleteModal
                isOpen={Boolean(webhookToDelete)}
                onClose={() => setWebhookToDelete(null)}
                onConfirm={confirmDelete}
                title="Excluir webhook?"
                message="O endpoint deixará de receber eventos externos imediatamente."
                confirmText="Excluir webhook"
            >
                <span className={isDark ? 'text-white/80' : 'text-brand/70'}>
                    Webhook selecionado: <strong>{webhookToDelete?.name}</strong>
                </span>
            </ConfirmDeleteModal>
        </div>
    );
};

export default WebhookManager;
