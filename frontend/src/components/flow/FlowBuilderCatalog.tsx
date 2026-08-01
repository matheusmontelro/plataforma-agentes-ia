import React, { useMemo, useState } from 'react';
import {
    CalendarClock,
    ChevronLeft,
    ChevronRight,
    Clock,
    Filter,
    GitBranch,
    Headphones,
    MessageCircle,
    MessageSquare,
    Network,
    Search,
    Send,
    Tag,
    Timer,
    UserPlus,
    Webhook,
    type LucideIcon,
} from 'lucide-react';
import { Node } from 'reactflow';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import { agentiveIconButtonClass } from '../AgentiveUI.tsx';

type NodeCategory = 'Gatilhos' | 'CRM' | 'Atendimento' | 'Filtros' | 'IA' | 'Mensagens' | 'Tempo';
type NodeTone = 'green' | 'pink' | 'blue' | 'emerald' | 'indigo' | 'purple' | 'sky' | 'amber';

export interface FlowNodeDefinition {
    category: NodeCategory;
    description: string;
    icon: LucideIcon;
    isTrigger?: boolean;
    label: string;
    output: string;
    tone: NodeTone;
    type: string;
}

const toneClasses: Record<NodeTone, { icon: string; soft: string; ring: string; minimap: string }> = {
    green: {
        icon: 'bg-emerald-500/10 text-emerald-600',
        soft: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20',
        ring: 'group-hover:border-emerald-500/35',
        minimap: '#22c55e',
    },
    pink: {
        icon: 'bg-pink-500/10 text-pink-600',
        soft: 'bg-pink-500/10 text-pink-600 border-pink-500/20',
        ring: 'group-hover:border-pink-500/35',
        minimap: '#ec4899',
    },
    blue: {
        icon: 'bg-blue-500/10 text-blue-600',
        soft: 'bg-blue-500/10 text-blue-600 border-blue-500/20',
        ring: 'group-hover:border-blue-500/35',
        minimap: '#3b82f6',
    },
    emerald: {
        icon: 'bg-emerald-500/10 text-emerald-600',
        soft: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20',
        ring: 'group-hover:border-emerald-500/35',
        minimap: '#10b981',
    },
    indigo: {
        icon: 'bg-indigo-500/10 text-indigo-600',
        soft: 'bg-indigo-500/10 text-indigo-600 border-indigo-500/20',
        ring: 'group-hover:border-indigo-500/35',
        minimap: '#6366f1',
    },
    purple: {
        icon: 'bg-purple-500/10 text-purple-600',
        soft: 'bg-purple-500/10 text-purple-600 border-purple-500/20',
        ring: 'group-hover:border-purple-500/35',
        minimap: '#a855f7',
    },
    sky: {
        icon: 'bg-sky-500/10 text-sky-600',
        soft: 'bg-sky-500/10 text-sky-600 border-sky-500/20',
        ring: 'group-hover:border-sky-500/35',
        minimap: '#0ea5e9',
    },
    amber: {
        icon: 'bg-amber-500/10 text-amber-700',
        soft: 'bg-amber-500/10 text-amber-700 border-amber-500/20',
        ring: 'group-hover:border-amber-500/35',
        minimap: '#f59e0b',
    },
};

export const FLOW_NODE_CATALOG: FlowNodeDefinition[] = [
    {
        category: 'Gatilhos',
        description: 'Inicia o fluxo quando uma mensagem real chega no WhatsApp.',
        icon: MessageCircle,
        isTrigger: true,
        label: 'Mensagem WhatsApp',
        output: '{{trigger.body}}, {{trigger.phone}}, {{trigger.name}}',
        tone: 'green',
        type: 'whatsappTrigger',
    },
    {
        category: 'Gatilhos',
        description: 'Recebe eventos externos por endpoint e gera variaveis do payload.',
        icon: Webhook,
        isTrigger: true,
        label: 'Webhook',
        output: '{{trigger.body}}',
        tone: 'pink',
        type: 'webhookTrigger',
    },
    {
        category: 'Gatilhos',
        description: 'Inicia o fluxo quando um agendamento é criado ou remarcado.',
        icon: CalendarClock,
        isTrigger: true,
        label: 'Agendamento',
        output: '{{trigger.appointment.starts_at}}, {{phone}}, {{name}}',
        tone: 'sky',
        type: 'appointmentTrigger',
    },
    {
        category: 'Gatilhos',
        description: 'Inicia o fluxo quando um lead e criado ou entra em uma etapa do CRM.',
        icon: GitBranch,
        isTrigger: true,
        label: 'Evento CRM',
        output: '{{trigger.lead.id}}, {{phone}}, {{name}}',
        tone: 'indigo',
        type: 'crmStageTrigger',
    },
    {
        category: 'CRM',
        description: 'Cria ou atualiza um lead no funil usando dados do gatilho.',
        icon: UserPlus,
        label: 'Criar lead',
        output: '{{create_lead.id}}',
        tone: 'blue',
        type: 'createLead',
    },
    {
        category: 'CRM',
        description: 'Adiciona uma tag existente ao contato que passou por este ponto.',
        icon: Tag,
        label: 'Adicionar tag',
        output: '{{add_tag.success}}, {{add_tag.tag_name}}',
        tone: 'emerald',
        type: 'addTag',
    },
    {
        category: 'CRM',
        description: 'Move o lead atual para uma etapa escolhida do funil.',
        icon: GitBranch,
        label: 'Avançar etapa CRM',
        output: '{{move_crm_stage.success}}, {{move_crm_stage.stage_name}}',
        tone: 'blue',
        type: 'moveCrmStage',
    },
    {
        category: 'Atendimento',
        description: 'Atribui o contato para atendimento humano sem enviar mensagem.',
        icon: Headphones,
        label: 'Atribuir humano',
        output: '{{human_handoff.task_id}}, {{human_handoff.bot_paused}}',
        tone: 'purple',
        type: 'humanHandoff',
    },
    {
        category: 'Filtros',
        description: 'Controla avanço por tags e campos personalizados do lead.',
        icon: Filter,
        label: 'Filtro condicional',
        output: '{{lead_filter.matched}}',
        tone: 'indigo',
        type: 'tagFilter',
    },
    {
        category: 'IA',
        description: 'Roda uma equipe multiagente configurada no menu Agentes.',
        icon: Network,
        label: 'Equipe de agentes',
        output: '{{agent_workforce.response}}',
        tone: 'indigo',
        type: 'agentWorkforce',
    },
    {
        category: 'Mensagens',
        description: 'Envia texto, imagem, video ou audio pelo WhatsApp.',
        icon: MessageSquare,
        label: 'Msg WhatsApp',
        output: '{{send_message.success}}',
        tone: 'green',
        type: 'sendMessage',
    },
    {
        category: 'Mensagens',
        description: 'Envia uma mensagem para Telegram quando o fluxo passar por aqui.',
        icon: Send,
        label: 'Msg Telegram',
        output: '{{send_telegram_message.success}}',
        tone: 'sky',
        type: 'sendTelegramMessage',
    },
    {
        category: 'Tempo',
        description: 'Pausa a execucao por um intervalo antes de continuar.',
        icon: Clock,
        label: 'Aguardar',
        output: '{{delay.completed}}',
        tone: 'amber',
        type: 'delay',
    },
    {
        category: 'Tempo',
        description: 'Agenda a continuação antes ou depois da data do evento de Agenda ou CRM.',
        icon: Timer,
        label: 'Antes/depois',
        output: '{{anchor_at}}',
        tone: 'amber',
        type: 'waitRelative',
    },
];

export const getFlowNodeDefinition = (type?: string) =>
    FLOW_NODE_CATALOG.find((item) => item.type === type || (type === 'webhookNode' && item.type === 'webhookTrigger'));

export const getFlowNodeColor = (type?: string) => {
    const definition = getFlowNodeDefinition(type);
    return definition ? toneClasses[definition.tone].minimap : '#4d506d';
};

interface FlowNodeLibraryProps {
    isCollapsed?: boolean;
    nodes: Node[];
    onAddNode: (type: string, label: string) => void;
    onToggleCollapsed?: () => void;
}

export const FlowNodeLibrary: React.FC<FlowNodeLibraryProps> = ({
    isCollapsed = false,
    nodes,
    onAddNode,
    onToggleCollapsed,
}) => {
    const { isDark } = useTheme();
    const [query, setQuery] = useState('');
    const hasTrigger = nodes.some((node) => getFlowNodeDefinition(node.type)?.isTrigger);
    const normalizedQuery = query.trim().toLowerCase();

    const filteredCatalog = useMemo(() => {
        if (!normalizedQuery) return FLOW_NODE_CATALOG;
        return FLOW_NODE_CATALOG.filter((item) =>
            `${item.label} ${item.category} ${item.description}`.toLowerCase().includes(normalizedQuery)
        );
    }, [normalizedQuery]);

    const groupedCatalog = useMemo(() => {
        return filteredCatalog.reduce<Record<NodeCategory, FlowNodeDefinition[]>>((acc, item) => {
            acc[item.category] = [...(acc[item.category] || []), item];
            return acc;
        }, {} as Record<NodeCategory, FlowNodeDefinition[]>);
    }, [filteredCatalog]);

    const railCatalogGroups = useMemo(() => {
        return FLOW_NODE_CATALOG.reduce<Record<NodeCategory, FlowNodeDefinition[]>>((acc, item) => {
            acc[item.category] = [...(acc[item.category] || []), item];
            return acc;
        }, {} as Record<NodeCategory, FlowNodeDefinition[]>);
    }, []);

    if (isCollapsed) {
        return (
            <aside className={`flex max-h-[360px] min-h-0 w-14 flex-col items-center overflow-hidden rounded-2xl border p-2 shadow-[0_18px_45px_rgba(2,3,35,0.10)] lg:max-h-none ${
                isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand'
            }`}>
                <button
                    type="button"
                    onClick={onToggleCollapsed}
                    className={agentiveIconButtonClass(isDark, 'primary', 'min-h-10 min-w-10')}
                    aria-label="Expandir biblioteca"
                    title="Expandir biblioteca"
                >
                    <ChevronRight className="h-4 w-4" />
                </button>

                <div className={`my-2 h-px w-full ${isDark ? 'bg-white/10' : 'bg-brand/10'}`} />

                <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
                    {Object.entries(railCatalogGroups).map(([category, items], categoryIndex) => (
                        <div key={category} className="flex flex-col items-center" role="group" aria-label={category}>
                            {categoryIndex > 0 && (
                                <div className={`my-2 h-px w-7 shrink-0 ${isDark ? 'bg-white/10' : 'bg-brand/10'}`} aria-hidden="true" />
                            )}
                            <div className="flex flex-col items-center gap-2">
                                {items.map((item) => {
                                    const Icon = item.icon;
                                    const tone = toneClasses[item.tone];
                                    const disabled = Boolean(item.isTrigger && hasTrigger);

                                    return (
                                        <button
                                            key={item.type}
                                            type="button"
                                            onClick={() => onAddNode(item.type, item.label)}
                                            disabled={disabled}
                                            className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl border transition disabled:cursor-not-allowed disabled:opacity-45 ${tone.icon} ${
                                                isDark ? 'border-white/10 hover:bg-white/10' : 'border-brand/10 hover:bg-brand-canvas'
                                            }`}
                                            aria-label={`Adicionar ${item.label}`}
                                            title={disabled ? 'Este fluxo ja tem um gatilho.' : `Adicionar ${item.label}`}
                                        >
                                            <Icon className="h-4 w-4" />
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    ))}
                </div>
            </aside>
        );
    }

    return (
        <aside className={`flex max-h-[360px] min-h-0 w-full flex-col overflow-hidden rounded-2xl border shadow-[0_18px_45px_rgba(2,3,35,0.10)] lg:max-h-none ${
            isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand'
        }`}>
            <div className={`border-b p-4 ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
                <div className="mb-4 flex items-center justify-between gap-3">
                    <div className="flex items-center gap-1.5" aria-hidden="true">
                        <span className={`h-1.5 w-1.5 rounded-full ${isDark ? 'bg-white/35' : 'bg-brand/25'}`} />
                        <span className={`h-1.5 w-1.5 rounded-full ${isDark ? 'bg-white/35' : 'bg-brand/25'}`} />
                        <span className={`h-1.5 w-1.5 rounded-full ${isDark ? 'bg-white/35' : 'bg-brand/25'}`} />
                    </div>
                    {onToggleCollapsed && (
                        <button
                            type="button"
                            onClick={onToggleCollapsed}
                            className={agentiveIconButtonClass(isDark)}
                            aria-label="Minimizar biblioteca"
                            title="Minimizar biblioteca"
                        >
                            <ChevronLeft className="h-4 w-4" />
                        </button>
                    )}
                </div>
                <div className="flex items-start gap-3">
                    <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
                        <GitBranch className="h-5 w-5" />
                    </div>
                    <div className="min-w-0">
                        <p className="text-sm font-semibold">Biblioteca</p>
                        <p className={`mt-1 text-xs leading-snug ${isDark ? 'text-white/50' : 'text-brand/50'}`}>
                            Escolha um gatilho e conecte modulos como no n8n/Make.
                        </p>
                    </div>
                </div>

                <div className="relative mt-4">
                    <Search className={`pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${isDark ? 'text-white/35' : 'text-brand/35'}`} />
                    <input
                        type="search"
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        placeholder="Buscar node"
                        className={`w-full rounded-xl border py-2 pl-9 pr-3 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20 ${
                            isDark
                                ? 'border-white/10 bg-white/[0.06] text-white placeholder:text-white/35'
                                : 'border-brand/10 bg-brand-canvas text-brand placeholder:text-brand/35'
                        }`}
                    />
                </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-3">
                {Object.entries(groupedCatalog).map(([category, items]) => (
                    <section key={category} className="mb-4 last:mb-0">
                        <div className={`mb-2 px-1 text-[10px] font-bold uppercase tracking-[0.16em] ${isDark ? 'text-white/35' : 'text-brand/35'}`}>
                            {category}
                        </div>
                        <div className="space-y-2">
                            {items.map((item) => {
                                const Icon = item.icon;
                                const tone = toneClasses[item.tone];
                                const disabled = Boolean(item.isTrigger && hasTrigger);

                                return (
                                    <button
                                        key={item.type}
                                        type="button"
                                        onClick={() => onAddNode(item.type, item.label)}
                                        disabled={disabled}
                                        className={`group w-full rounded-2xl border p-3 text-left transition ${tone.ring} ${
                                            disabled
                                                ? isDark
                                                    ? 'cursor-not-allowed border-white/5 bg-white/[0.03] opacity-50'
                                                    : 'cursor-not-allowed border-brand/5 bg-brand-canvas/50 opacity-60'
                                                : isDark
                                                    ? 'border-white/10 bg-white/[0.05] hover:bg-white/[0.08]'
                                                    : 'border-brand/10 bg-white hover:bg-brand-canvas'
                                        }`}
                                    >
                                        <div className="flex items-start gap-3">
                                            <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ${tone.icon}`}>
                                                <Icon className="h-4 w-4" />
                                            </span>
                                            <span className="min-w-0 flex-1">
                                                <span className="flex items-center gap-2">
                                                    <span className="truncate text-sm font-semibold">{item.label}</span>
                                                    {item.isTrigger && (
                                                        <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${tone.soft}`}>
                                                            Gatilho
                                                        </span>
                                                    )}
                                                </span>
                                                <span className={`mt-1 block text-xs leading-snug ${isDark ? 'text-white/50' : 'text-brand/50'}`}>
                                                    {disabled ? 'Este fluxo ja tem um gatilho.' : item.description}
                                                </span>
                                            </span>
                                        </div>
                                    </button>
                                );
                            })}
                        </div>
                    </section>
                ))}

                {filteredCatalog.length === 0 && (
                    <div className={`rounded-2xl border border-dashed p-4 text-center text-sm ${isDark ? 'border-white/10 text-white/50' : 'border-brand/15 text-brand/50'}`}>
                        Nenhum node encontrado.
                    </div>
                )}
            </div>
        </aside>
    );
};
