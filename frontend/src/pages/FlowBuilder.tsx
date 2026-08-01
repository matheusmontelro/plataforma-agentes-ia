import React, { useState, useEffect, useCallback, useRef } from 'react';
import ReactFlow, {
    ReactFlowProvider,
    addEdge,
    useNodesState,
    useEdgesState,
    Controls,
    Background,
    MiniMap,
    Connection,
    Edge,
    Node,
    BackgroundVariant,
    Panel,
    Position // Import Position
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useParams, useNavigate } from 'react-router-dom';
import {
    Save,
    ArrowLeft,
    ChevronLeft,
    ChevronRight,
    Edit2,
    Play,
    Square,
    Loader2,
    GitMerge,
    Split,
} from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
    getFlow,
    updateFlow,
    type Flow,
    type FlowUpdate
} from '../services/flowBuilderApi';

import WebhookNode from '../components/flow/WebhookNode.tsx';
import CreateLeadNode from '../components/flow/CreateLeadNode.tsx'; // Import
import SendMessageNode from '../components/flow/SendMessageNode.tsx'; // Import SendMessageNode
import SendTelegramNode from '../components/flow/SendTelegramNode.tsx'; // Import SendTelegramNode
import AgentResponseNode from '../components/flow/AgentResponseNode.tsx'; // Import AgentResponseNode
import AgentWorkforceNode from '../components/flow/AgentWorkforceNode.tsx';
import WhatsAppTriggerNode from '../components/flow/WhatsAppTriggerNode.tsx'; // Import WhatsAppTriggerNode
import DelayNode from '../components/flow/DelayNode.tsx'; // Import DelayNode
import AppointmentTriggerNode from '../components/flow/AppointmentTriggerNode.tsx';
import CrmStageTriggerNode from '../components/flow/CrmStageTriggerNode.tsx';
import WaitRelativeNode from '../components/flow/WaitRelativeNode.tsx';
import AddTagNode from '../components/flow/AddTagNode.tsx';
import TagFilterNode from '../components/flow/TagFilterNode.tsx';
import MoveCrmStageNode from '../components/flow/MoveCrmStageNode.tsx';
import HumanHandoffNode from '../components/flow/HumanHandoffNode.tsx';
import FlowRenameModal from '../components/flow/FlowRenameModal.tsx';
import { FlowVariablesProvider, useFlowVariables } from '../contexts/FlowVariablesContext.tsx';
import { FlowControls } from '../components/flow/FlowControls.tsx';
import CustomDeleteEdge from '../components/flow/CustomDeleteEdge.tsx'; // Import CustomDeleteEdge
import {
    FlowNodeLibrary,
    getFlowNodeColor,
    getFlowNodeDefinition,
} from '../components/flow/FlowBuilderCatalog.tsx';
import { FlowConfirmProvider, useFlowConfirm } from '../components/flow/FlowConfirmContext.tsx';
import {
    agentiveIconButtonClass,
    agentivePillClass,
    agentivePrimaryButtonClass,
    agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';
import dagre from 'dagre';

const dagreGraph = new dagre.graphlib.Graph();
dagreGraph.setDefaultEdgeLabel(() => ({}));

const nodeWidth = 172;
const nodeHeight = 36;
const FLOW_LIBRARY_PANEL_WIDTH = 280;
const FLOW_INSPECTOR_PANEL_WIDTH = 320;
const FLOW_PANEL_RAIL_WIDTH = 56;

const TRIGGER_NODE_TYPES = ['webhookTrigger', 'webhookNode', 'whatsappTrigger', 'appointmentTrigger', 'crmStageTrigger'] as const;
type TriggerNodeType = (typeof TRIGGER_NODE_TYPES)[number];
type FlowTriggerType = 'webhook' | 'whatsapp' | 'appointment' | 'crm_stage';

const isTriggerNodeType = (nodeType?: string): nodeType is TriggerNodeType => {
    return TRIGGER_NODE_TYPES.includes(nodeType as TriggerNodeType);
};

const getTriggerNodes = (nodeList: Node[]) => {
    return nodeList.filter(node => isTriggerNodeType(node.type));
};

const parseOptionalNumber = (value: unknown) => {
    if (value === undefined || value === null || String(value).trim() === '') return null;
    const parsed = Number.parseInt(String(value), 10);
    return Number.isNaN(parsed) ? null : parsed;
};

const normalizeFlowTriggerType = (value?: string): FlowTriggerType => {
    if (value === 'whatsapp' || value === 'appointment' || value === 'crm_stage') return value;
    return 'webhook';
};

const inferTriggerMetadata = (triggerNodes: Node[], currentFlow?: Flow | null) => {
    const fallbackType = normalizeFlowTriggerType(currentFlow?.trigger_type);
    const fallbackWebhookId = currentFlow?.trigger_webhook_id ?? null;
    const fallbackConfig = currentFlow?.trigger_config || {};

    if (triggerNodes.length !== 1) {
        return {
            triggerType: fallbackType,
            triggerWebhookId: fallbackType === 'webhook' ? fallbackWebhookId : null,
            triggerConfig: fallbackConfig,
        };
    }

    const triggerNode = triggerNodes[0];
    const nodeData = triggerNode.data || {};

    if (triggerNode.type === 'whatsappTrigger') {
        return {
            triggerType: 'whatsapp' as const,
            triggerWebhookId: null,
            triggerConfig: {},
        };
    }

    if (triggerNode.type === 'appointmentTrigger') {
        const eventType = String(nodeData.eventType || 'appointment_scheduled');
        const events = eventType === 'appointment_scheduled'
            ? ['appointment_created', 'appointment_rescheduled']
            : [eventType];
        const status = String(nodeData.status || nodeData.statusFilter || '').trim();
        const agendaId = parseOptionalNumber(nodeData.agendaId);

        return {
            triggerType: 'appointment' as const,
            triggerWebhookId: null,
            triggerConfig: {
                events,
                ...(status ? { status } : {}),
                ...(agendaId ? { agenda_id: agendaId } : {}),
            },
        };
    }

    if (triggerNode.type === 'crmStageTrigger') {
        const eventType = String(nodeData.eventType || nodeData.event || 'crm_stage_entered');
        const pipelineId = parseOptionalNumber(nodeData.pipelineId);
        const stageId = parseOptionalNumber(nodeData.stageId);

        return {
            triggerType: 'crm_stage' as const,
            triggerWebhookId: null,
            triggerConfig: {
                event: eventType === 'lead_created' ? 'lead_created' : 'crm_stage_entered',
                ...(pipelineId ? { pipeline_id: pipelineId } : {}),
                ...(eventType !== 'lead_created' && stageId ? { stage_id: stageId } : {}),
            },
        };
    }

    return {
        triggerType: 'webhook' as const,
        triggerWebhookId: parseOptionalNumber(nodeData.webhookId),
        triggerConfig: {
            ...(nodeData.webhookMapping || nodeData.webhook_mapping
                ? { webhook_mapping: nodeData.webhookMapping || nodeData.webhook_mapping }
                : {}),
        },
    };
};

const RUNTIME_NODE_DATA_KEYS = new Set(['onDataChange', 'triggerRunOnce']);

const sanitizeNodesForPersistence = (nodeList: Node[]) =>
    nodeList.map((node) => {
        const cleanData = Object.fromEntries(
            Object.entries(node.data || {}).filter(([key, value]) =>
                !RUNTIME_NODE_DATA_KEYS.has(key) && typeof value !== 'function'
            )
        );

        return {
            ...node,
            data: cleanData
        };
    });

const hasPathToNodeType = (sourceId: string, targetType: string, nodeList: Node[], edgeList: Edge[]) => {
    const queue = [sourceId];
    const visited = new Set<string>();

    while (queue.length > 0) {
        const currentId = queue.shift();
        if (!currentId || visited.has(currentId)) continue;
        visited.add(currentId);

        const nextIds = edgeList
            .filter(edge => edge.source === currentId)
            .map(edge => edge.target);

        for (const nextId of nextIds) {
            const nextNode = nodeList.find(node => node.id === nextId);
            if (!nextNode) continue;
            if (nextNode.type === targetType) return true;
            queue.push(nextId);
        }
    }

    return false;
};

interface ActivationValidationResult {
    confirmText?: string;
    message: string;
    requiresConfirmation?: boolean;
    title: string;
}

const getActivationValidationIssue = (nodeList: Node[], edgeList: Edge[], triggerType: string): ActivationValidationResult | null => {
    if (triggerType !== 'whatsapp') return null;

    const workforceNodes = nodeList.filter(node => node.type === 'agentWorkforce');
    const missingWorkforce = workforceNodes.find(node => !node.data?.workforceId);

    if (missingWorkforce) {
        return {
            title: 'Equipe IA incompleta',
            message: 'Selecione uma equipe no node "Equipe de agentes" antes de ativar este fluxo de WhatsApp.',
        };
    }

    const workforceWithoutSend = workforceNodes.find(node =>
        !hasPathToNodeType(node.id, 'sendMessage', nodeList, edgeList)
        && !hasPathToNodeType(node.id, 'humanHandoff', nodeList, edgeList)
    );

    if (workforceWithoutSend) return {
        confirmText: 'Ativar mesmo assim',
        message: 'A equipe de agentes vai gerar uma resposta, mas nao ha um node "Msg WhatsApp" ou "Atribuir humano" conectado depois dela.',
        requiresConfirmation: true,
        title: 'Fluxo sem envio conectado',
    };

    return null;
};


const nodeTypes = {
    webhookTrigger: WebhookNode,
    webhookNode: WebhookNode, // Legacy support for previous saves
    createLead: CreateLeadNode,
    sendMessage: SendMessageNode, // Register new node
    sendTelegramMessage: SendTelegramNode,
    agentResponse: AgentResponseNode, // AI Agent node
    agentWorkforce: AgentWorkforceNode,
    whatsappTrigger: WhatsAppTriggerNode, // WhatsApp message trigger
    appointmentTrigger: AppointmentTriggerNode,
    crmStageTrigger: CrmStageTriggerNode,
    delay: DelayNode, // Sleep/Delay node
    sleep: DelayNode, // Alias
    waitRelative: WaitRelativeNode,
    addTag: AddTagNode,
    tagFilter: TagFilterNode,
    moveCrmStage: MoveCrmStageNode,
    humanHandoff: HumanHandoffNode,
};

const edgeTypes = {
    custom: CustomDeleteEdge,
    deletable: CustomDeleteEdge,
};

const FlowTrafficDots: React.FC<{ isDark: boolean }> = ({ isDark }) => (
    <div className="flex items-center gap-1.5" aria-hidden="true">
        <span className={`h-1.5 w-1.5 rounded-full ${isDark ? 'bg-white/35' : 'bg-brand/25'}`} />
        <span className={`h-1.5 w-1.5 rounded-full ${isDark ? 'bg-white/35' : 'bg-brand/25'}`} />
        <span className={`h-1.5 w-1.5 rounded-full ${isDark ? 'bg-white/35' : 'bg-brand/25'}`} />
    </div>
);

const FlowInspector: React.FC<{
    edges: Edge[];
    flow: Flow | null;
    isCollapsed: boolean;
    isDirty: boolean;
    nodes: Node[];
    onToggleCollapsed: () => void;
    selectedEdgeId: string | null;
    selectedNode: Node | null;
}> = ({ edges, flow, isCollapsed, isDirty, nodes, onToggleCollapsed, selectedEdgeId, selectedNode }) => {
    const { isDark } = useTheme();
    const definition = getFlowNodeDefinition(selectedNode?.type);
    const Icon = definition?.icon || GitMerge;
    const triggerNode = getTriggerNodes(nodes)[0];
    const triggerDefinition = getFlowNodeDefinition(triggerNode?.type);
    const selectedEdge = edges.find((edge) => edge.id === selectedEdgeId) || null;

    if (isCollapsed) {
        return (
            <aside className={`hidden min-h-0 w-14 flex-col items-center overflow-hidden rounded-2xl border p-2 shadow-[0_18px_45px_rgba(2,3,35,0.10)] xl:flex ${isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand'}`}>
                <button
                    type="button"
                    onClick={onToggleCollapsed}
                    className={agentiveIconButtonClass(isDark, 'primary', 'min-h-10 min-w-10')}
                    aria-label="Expandir inspector"
                    title="Expandir inspector"
                >
                    <ChevronLeft className="h-4 w-4" />
                </button>

                <div className={`my-2 h-px w-full ${isDark ? 'bg-white/10' : 'bg-brand/10'}`} />

                <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
                    <Icon className="h-4 w-4" />
                </div>

                <div className={`mt-3 [writing-mode:vertical-rl] rotate-180 text-[10px] font-bold uppercase tracking-[0.18em] ${isDark ? 'text-white/40' : 'text-brand/40'}`}>
                    Inspector
                </div>
            </aside>
        );
    }

    return (
        <aside className={`hidden min-h-0 w-full flex-col overflow-hidden rounded-2xl border shadow-[0_18px_45px_rgba(2,3,35,0.10)] xl:flex ${isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand'}`}>
            <div className={`border-b p-4 ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
                <div className="mb-2 flex items-center justify-between gap-3">
                    <FlowTrafficDots isDark={isDark} />
                    <button
                        type="button"
                        onClick={onToggleCollapsed}
                        className={agentiveIconButtonClass(isDark)}
                        aria-label="Minimizar inspector"
                        title="Minimizar inspector"
                    >
                        <ChevronRight className="h-4 w-4" />
                    </button>
                </div>
                <p className={`text-[10px] font-bold uppercase tracking-[0.16em] ${isDark ? 'text-white/35' : 'text-brand/35'}`}>
                    Inspector
                </p>
                <h2 className="mt-1 truncate text-base font-semibold">
                    {selectedNode ? definition?.label || selectedNode.type : selectedEdge ? 'Conexão' : 'Visão do fluxo'}
                </h2>
                <p className={`mt-1 text-xs leading-snug ${isDark ? 'text-white/50' : 'text-brand/50'}`}>
                    {selectedNode ? definition?.category || 'Node customizado' : selectedEdge ? `${selectedEdge.source} -> ${selectedEdge.target}` : flow?.name || 'Automação'}
                </p>
            </div>

            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
                <section className={`rounded-2xl border p-3 ${isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas'}`}>
                    <div className="flex items-center gap-3">
                        <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
                            <Icon className="h-5 w-5" />
                        </span>
                        <div className="min-w-0">
                            <p className="truncate text-sm font-semibold">{selectedNode ? definition?.label || 'Node' : 'Resumo'}</p>
                            <p className={`text-xs ${isDark ? 'text-white/45' : 'text-brand/45'}`}>
                                {isDirty ? 'Alterações pendentes' : 'Sincronizado'}
                            </p>
                        </div>
                    </div>
                    {definition?.description && (
                        <p className={`mt-3 text-xs leading-relaxed ${isDark ? 'text-white/55' : 'text-brand/55'}`}>
                            {definition.description}
                        </p>
                    )}
                </section>

                <section className={`rounded-2xl border p-3 ${isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-white'}`}>
                    <p className={`text-[10px] font-bold uppercase tracking-[0.16em] ${isDark ? 'text-white/35' : 'text-brand/35'}`}>
                        Estrutura
                    </p>
                    <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                        <div className={`rounded-xl border px-3 py-2 ${isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas'}`}>
                            <span className="block text-base font-semibold">{nodes.length}</span>
                            <span className={isDark ? 'text-white/45' : 'text-brand/45'}>nodes</span>
                        </div>
                        <div className={`rounded-xl border px-3 py-2 ${isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas'}`}>
                            <span className="block text-base font-semibold">{edges.length}</span>
                            <span className={isDark ? 'text-white/45' : 'text-brand/45'}>conexões</span>
                        </div>
                    </div>
                </section>

                <section className={`rounded-2xl border p-3 ${isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-white'}`}>
                    <p className={`text-[10px] font-bold uppercase tracking-[0.16em] ${isDark ? 'text-white/35' : 'text-brand/35'}`}>
                        Gatilho
                    </p>
                    <div className="mt-3 flex items-center gap-2">
                        <span className={agentivePillClass(isDark, Boolean(triggerNode))}>
                            {triggerDefinition?.label || 'Nao definido'}
                        </span>
                    </div>
                    <p className={`mt-2 text-xs leading-relaxed ${isDark ? 'text-white/50' : 'text-brand/50'}`}>
                        {triggerDefinition?.output || 'Adicione um gatilho pela biblioteca para iniciar o fluxo.'}
                    </p>
                </section>

                {selectedNode && (
                    <section className={`rounded-2xl border p-3 ${isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-white'}`}>
                        <p className={`text-[10px] font-bold uppercase tracking-[0.16em] ${isDark ? 'text-white/35' : 'text-brand/35'}`}>
                            Saída esperada
                        </p>
                        <code className={`mt-3 block whitespace-pre-wrap rounded-xl border p-3 text-xs ${isDark ? 'border-white/10 bg-black/20 text-white/70' : 'border-brand/10 bg-brand-canvas text-brand/70'}`}>
                            {definition?.output || 'Variáveis disponíveis após executar o node.'}
                        </code>
                    </section>
                )}
            </div>
        </aside>
    );
};

const FlowBuilderCanvas: React.FC = () => {
    const { flowId } = useParams<{ flowId: string }>();
    const navigate = useNavigate();
    const { isDark } = useTheme();
    const { confirm, notice } = useFlowConfirm();

    // React Flow State
    const [nodes, setNodes, onNodesChange] = useNodesState([]);
    const [edges, setEdges, onEdgesChange] = useEdgesState([]);
    const reactFlowWrapper = useRef<HTMLDivElement>(null);
    const [reactFlowInstance, setReactFlowInstance] = useState<any>(null);
    const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
    const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);

    // Chain Execution State
    const { lastExecutedNodeId, isFlowRunning, setIsFlowRunning } = useFlowVariables();

    // App State
    const [flow, setFlow] = useState<Flow | null>(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [isDirty, setIsDirty] = useState(false);
    const [isRenameOpen, setIsRenameOpen] = useState(false);
    const [renaming, setRenaming] = useState(false);
    const [isLibraryPanelOpen, setIsLibraryPanelOpen] = useState(true);
    const [isInspectorPanelOpen, setIsInspectorPanelOpen] = useState(true);
    const selectedNode = nodes.find((node) => node.id === selectedNodeId) || null;

    const handleNodeDataChange = useCallback((nodeId: string, updates: Record<string, unknown>) => {
        setNodes((nds) =>
            nds.map((node) =>
                node.id === nodeId
                    ? { ...node, data: { ...node.data, ...updates } }
                    : node
            )
        );
        setIsDirty(true);
    }, [setNodes]);

    const attachRuntimeNodeData = useCallback((nodeList: Node[]) =>
        nodeList.map((node) => ({
            ...node,
            data: {
                ...node.data,
                onDataChange: handleNodeDataChange
            }
        })), [handleNodeDataChange]);

    // Effect to trigger next node when previous one finishes
    useEffect(() => {
        if (!lastExecutedNodeId || !isFlowRunning) return;

        // Find edges starting from this node
        const outgoingEdges = edges.filter(edge => edge.source === lastExecutedNodeId);

        if (outgoingEdges.length > 0) {
            console.log(`Flow Chain: Node ${lastExecutedNodeId} finished. Triggering ${outgoingEdges.length} next nodes.`);

            // Trigger next nodes
            setNodes((nds) =>
                nds.map((node) => {
                    // Check if this node is a target of any outgoing edge
                    if (outgoingEdges.some(edge => edge.target === node.id)) {
                        console.log(`-> Triggering node ${node.id} (${node.type})`);
                        return {
                            ...node,
                            data: {
                                ...node.data,
                                triggerRunOnce: Date.now() // Trigger execution!
                            }
                        };
                    }
                    return node;
                })
            );
        } else {
            console.log(`Flow Chain: Node ${lastExecutedNodeId} finished. End of branch.`);
            setIsFlowRunning(false);
        }

    }, [lastExecutedNodeId, edges, isFlowRunning, setIsFlowRunning, setNodes]); // Dependency on the context value changing


    useEffect(() => {
        if (flowId) {
            loadFlow(parseInt(flowId));
        }
    }, [flowId]); // loadFlow is stable if defined outside or wrapped in callback, but here it's defined inside. Needs useCallback or just ignore rule. Let's ignore rule to prevent infinite loop if loadFlow isn't memoized.
    // Actually, loadFlow is defined inside the component and depends on state setters.
    // Moving it inside useEffect or wrapping in useCallback is best practice.
    // For now, disabling exhaustive-deps for this line is safest to avoid refactor risk.
    // eslint-disable-next-line react-hooks/exhaustive-deps

    const loadFlow = async (id: number) => {
        try {
            setLoading(true);
            const data = await getFlow(id);
            setFlow(data);

            // Restore nodes and edges
            if (data.nodes) setNodes(attachRuntimeNodeData(data.nodes as Node[]));
            if (data.edges) {
                // Ensure all edges use the custom type for deletion support
                const migratedEdges = data.edges.map(edge => ({
                    ...edge,
                    type: 'custom'
                }));
                setEdges(migratedEdges);
            }

            // Restore viewport (needs instance)
            if (data.viewport && reactFlowInstance) {
                reactFlowInstance.setViewport(data.viewport);
            }
        } catch (error) {
            console.error("Error loading flow", error);
            await notice({
                title: 'Erro ao carregar fluxo',
                message: 'Nao foi possivel abrir esta automação. Tente novamente em alguns instantes.',
                variant: 'info',
            });
            navigate('/flows');
        } finally {
            setLoading(false);
        }
    };

    const onConnect = useCallback((params: Connection) => {
        setEdges((eds) => addEdge(params, eds));
        setIsDirty(true);
    }, [setEdges]);

    const handleActivationIssue = useCallback(async (issue: ActivationValidationResult | null) => {
        if (!issue) return true;

        if (issue.requiresConfirmation) {
            return confirm({
                cancelText: 'Revisar fluxo',
                confirmText: issue.confirmText || 'Continuar',
                message: issue.message,
                title: issue.title,
                variant: 'warning',
            });
        }

        await notice({
            title: issue.title,
            message: issue.message,
            variant: 'info',
        });

        return false;
    }, [confirm, notice]);

    const onSave = async () => {
        if (!flow || !reactFlowInstance) return;

        try {
            setSaving(true);
            const flowObject = reactFlowInstance.toObject();
            const persistedNodes = sanitizeNodesForPersistence((flowObject.nodes || []) as Node[]);
            const persistedEdges = (flowObject.edges || []) as Edge[];
            const triggerNodes = getTriggerNodes(persistedNodes || []);

            if (triggerNodes.length > 1) {
                await notice({
                    title: 'Múltiplos gatilhos',
                    message: 'Este fluxo possui mais de um gatilho. Mantenha apenas um node inicial para salvar com segurança.',
                    variant: 'info',
                });
                return;
            }

            const {
                triggerType,
                triggerWebhookId,
                triggerConfig,
            } = inferTriggerMetadata(triggerNodes, flow);

            console.log(
                `[FlowBuilder] Auto-detected: type=${triggerType}, webhook_id=${triggerWebhookId}, trigger_count=${triggerNodes.length}`
            );

            if (flow.is_active && !(await handleActivationIssue(getActivationValidationIssue(persistedNodes, persistedEdges, triggerType)))) {
                return;
            }

            await updateFlow(flow.id, {
                nodes: persistedNodes,
                edges: persistedEdges,
                viewport: flowObject.viewport,
                is_active: flow.is_active, // Mantém estado atual
                trigger_type: triggerType,
                trigger_webhook_id: triggerWebhookId,
                trigger_config: triggerConfig,
            });

            setIsDirty(false);
        } catch (error) {
            console.error("Error saving flow", error);
            await notice({
                title: 'Erro ao salvar',
                message: 'Nao foi possivel salvar o fluxo agora. Verifique a conexão e tente novamente.',
                variant: 'info',
            });
        } finally {
            setSaving(false);
        }
    };

    const onAutoAlign = useCallback(() => {
        dagreGraph.setGraph({ rankdir: 'LR' });

        nodes.forEach((node) => {
            // Use measured dimensions if available (React Flow v11+), otherwise fallback
            // @ts-ignore
            const width = node.measured?.width || node.width || nodeWidth;
            // @ts-ignore
            const height = node.measured?.height || node.height || nodeHeight;

            dagreGraph.setNode(node.id, { width, height });
        });

        edges.forEach((edge) => {
            dagreGraph.setEdge(edge.source, edge.target);
        });

        dagre.layout(dagreGraph);

        const layoutedNodes = nodes.map((node) => {
            const nodeWithPosition = dagreGraph.node(node.id);
            node.targetPosition = Position.Left;
            node.sourcePosition = Position.Right;

            // @ts-ignore
            const width = node.measured?.width || node.width || nodeWidth;
            // @ts-ignore
            const height = node.measured?.height || node.height || nodeHeight;

            // We are shifting the dagre node position (anchor=center center) to the top left
            // so it matches the React Flow node anchor point (top left).
            node.position = {
                x: nodeWithPosition.x - width / 2,
                y: nodeWithPosition.y - height / 2,
            };

            return node;
        });

        setNodes([...layoutedNodes]);
        setIsDirty(true);
    }, [nodes, edges, setNodes]);

    const onToggleActive = async (active: boolean) => {
        if (!flow) return;

        const flowObject = reactFlowInstance?.toObject();
        let updatePayload: FlowUpdate = { is_active: active };

        if (flowObject) {
            const persistedNodes = sanitizeNodesForPersistence((flowObject.nodes || []) as Node[]);
            const persistedEdges = (flowObject.edges || []) as Edge[];
            const triggerNodes = getTriggerNodes(persistedNodes || []);

            if (triggerNodes.length > 1) {
                await notice({
                    title: 'Múltiplos gatilhos',
                    message: 'Este fluxo possui mais de um gatilho. Remova os extras antes de alterar o status.',
                    variant: 'info',
                });
                return;
            }

            const {
                triggerType,
                triggerWebhookId,
                triggerConfig,
            } = inferTriggerMetadata(triggerNodes, flow);

            if (active && !(await handleActivationIssue(getActivationValidationIssue(persistedNodes, persistedEdges, triggerType)))) {
                return;
            }

            updatePayload = {
                nodes: persistedNodes,
                edges: persistedEdges,
                viewport: flowObject.viewport,
                is_active: active,
                trigger_type: triggerType,
                trigger_webhook_id: triggerWebhookId,
                trigger_config: triggerConfig,
            };
        }

        // Optimistic update
        setFlow(prev => prev ? { ...prev, is_active: active } : null);
        setIsDirty(true); // Mark as dirty effectively

        // Note: For now we just update local state, save will persist it.
        // Or should we persist immediately? Make.com usually persists active state immediately.
        // Let's persist immediately for better UX.
        try {
            await updateFlow(flow.id, updatePayload);
            setIsDirty(false); // Saved
        } catch (e) {
            console.error("Failed to toggle active", e);
            await notice({
                title: 'Erro ao alterar status',
                message: 'Nao foi possivel atualizar o status da automação. O estado anterior foi restaurado.',
                variant: 'info',
            });
            setFlow(prev => prev ? { ...prev, is_active: !active } : null); // Revert
        }
    };

    const handleRenameFlow = async (name: string) => {
        if (!flow) return;

        try {
            setRenaming(true);
            const updatedFlow = await updateFlow(flow.id, { name });
            setFlow((currentFlow) => currentFlow
                ? { ...currentFlow, name: updatedFlow.name, updated_at: updatedFlow.updated_at }
                : updatedFlow
            );
            setIsRenameOpen(false);
        } catch (error) {
            console.error('Failed to rename flow', error);
            await notice({
                title: 'Erro ao editar nome',
                message: 'Nao foi possivel salvar o novo nome da automação. Tente novamente.',
                variant: 'info',
            });
        } finally {
            setRenaming(false);
        }
    };

    const onGlobalRunOnce = () => {
        const triggerNodes = getTriggerNodes(nodes);

        if (triggerNodes.length === 0) {
            void notice({
                title: 'Gatilho ausente',
                message: 'Adicione um gatilho de WhatsApp, Webhook, Agenda ou CRM pela biblioteca antes de testar o fluxo.',
                variant: 'info',
            });
            setIsFlowRunning(false);
            return;
        }

        if (triggerNodes.length > 1) {
            void notice({
                title: 'Múltiplos gatilhos',
                message: 'Este fluxo possui mais de um gatilho. Mantenha apenas um node inicial para testar.',
                variant: 'info',
            });
            setIsFlowRunning(false);
            return;
        }

        setIsFlowRunning(true);

        const triggerNode = triggerNodes[0];

        setNodes((nds) =>
            nds.map((node) => {
                if (node.id === triggerNode.id) {
                    return {
                        ...node,
                        data: {
                            ...node.data,
                            triggerRunOnce: Date.now()
                        }
                    };
                }
                return node;
            })
        );
    };

    const onStopRunOnce = useCallback(() => {
        setIsFlowRunning(false);
        setNodes((currentNodes) =>
            currentNodes.map((node) =>
                node.data?.triggerRunOnce
                    ? {
                        ...node,
                        data: {
                            ...node.data,
                            triggerRunOnce: undefined,
                        },
                    }
                    : node
            )
        );
    }, [setIsFlowRunning, setNodes]);

    // Add Node Helper
    const addNode = (type: string, label: string) => {
        if (isTriggerNodeType(type)) {
            const existingTriggerNodes = getTriggerNodes(nodes);
            if (existingTriggerNodes.length > 0) {
                void notice({
                    title: 'Gatilho já definido',
                    message: 'Cada automação pode ter apenas um gatilho. Remova o gatilho atual antes de adicionar outro.',
                    variant: 'info',
                });
                return;
            }
        }

        const id = `${type}_${Date.now()}`;

        let initialData: Record<string, unknown> = { label: label };

        if (type === 'agentWorkforce') {
            initialData = {
                ...initialData,
                workforceId: null,
                inputMessage: '{{trigger.body}}'
            };
        }

        if (type === 'appointmentTrigger') {
            initialData = {
                ...initialData,
                eventType: 'appointment_scheduled',
                status: '',
                agendaId: '',
            };
        }

        if (type === 'crmStageTrigger') {
            initialData = {
                ...initialData,
                pipelineId: '',
                stageId: '',
            };
        }

        if (type === 'waitRelative') {
            initialData = {
                ...initialData,
                offsetAmount: 24,
                offsetUnit: 'hours',
                offsetDirection: 'before',
                anchorType: 'appointment_start',
            };
        }

        if (type === 'addTag') {
            initialData = {
                ...initialData,
                tagId: '',
                tagName: '',
            };
        }

        if (type === 'tagFilter') {
            initialData = {
                ...initialData,
                tagId: '',
                tagName: '',
                filterMode: 'has_tag',
                conditionMatch: 'all',
                actionOnMatch: 'advance',
                conditions: [
                    {
                        id: `condition-${Date.now()}`,
                        source: 'tag',
                        operator: 'has_tag',
                        tagId: '',
                        tagName: '',
                    },
                ],
            };
        }

        if (type === 'moveCrmStage') {
            initialData = {
                ...initialData,
                pipelineId: '',
                stageId: '',
                stageName: '',
                leadId: '',
                leadPhone: '{{lead.phone}}',
                notes: 'Movido pelo FlowBuilder.',
            };
        }

        if (type === 'humanHandoff') {
            initialData = {
                ...initialData,
                assignedUserId: '',
                assignedUserName: '',
                priority: 'high',
                leadPhone: '{{lead.phone}}',
                title: 'Atender lead',
                reason: 'Solicitou atendimento humano.',
                summary: '',
                pauseBot: true,
                silent: true,
                stopFlow: true,
            };
        }

        const newNode: Node = {
            id,
            type: type,
            position: nodes.length > 0
                ? {
                    x: Math.max(...nodes.map((node) => node.position.x)) + 360,
                    y: nodes[nodes.length - 1].position.y,
                }
                : { x: 120, y: 160 },
            data: {
                ...initialData,
                onDataChange: handleNodeDataChange
            },
        };
        setNodes((nds) => nds.concat(newNode));
        setIsDirty(true);
    };

    if (loading) {
        return (
            <div className={`flex h-screen w-full items-center justify-center ${isDark ? 'bg-brand text-white' : 'bg-brand-canvas text-brand'}`}>
                <div className={`flex items-center gap-3 rounded-2xl border px-5 py-4 shadow-flat-md ${isDark ? 'border-white/10 bg-white/[0.06]' : 'border-brand/10 bg-white'}`}>
                    <Loader2 className="h-5 w-5 animate-spin" />
                    <span className="text-sm font-medium">Carregando editor</span>
                </div>
            </div>
        );
    }



    const libraryColumnWidth = isLibraryPanelOpen ? `${FLOW_LIBRARY_PANEL_WIDTH}px` : `${FLOW_PANEL_RAIL_WIDTH}px`;
    const inspectorColumnWidth = isInspectorPanelOpen ? `${FLOW_INSPECTOR_PANEL_WIDTH}px` : `${FLOW_PANEL_RAIL_WIDTH}px`;

    return (
        <div className={`min-h-screen p-3 pb-[calc(7rem+env(safe-area-inset-bottom))] sm:p-4 sm:pb-4 ${isDark ? 'bg-brand text-white' : 'bg-brand-canvas text-brand'}`}>
            <section className={`flex min-h-[calc(100vh-1.5rem-7rem)] flex-col overflow-hidden rounded-[24px] border shadow-[0_22px_55px_rgba(2,3,35,0.12)] sm:h-[calc(100vh-2rem)] sm:min-h-0 ${
                isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand'
            }`}>
                <header className={`z-20 border-b px-4 py-3 ${isDark ? 'border-white/10 bg-brand' : 'border-brand/10 bg-white'}`}>
                    <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
                        <div className="flex min-w-0 items-center gap-3">
                        <button
                            type="button"
                            onClick={() => navigate('/flows')}
                            className={agentiveIconButtonClass(isDark)}
                            aria-label="Voltar para automações"
                        >
                            <ArrowLeft className="h-5 w-5" />
                        </button>
                            <div className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
                                <GitMerge className="h-5 w-5" />
                            </div>
                            <div className="min-w-0">
                                <div className="mb-1 flex items-center gap-2">
                                    <FlowTrafficDots isDark={isDark} />
                                    <span className={`text-[10px] font-bold uppercase tracking-[0.18em] ${isDark ? 'text-white/35' : 'text-brand/35'}`}>
                                        Flow Builder
                                    </span>
                                </div>
                                <div className="flex flex-wrap items-center gap-2">
                                    <div className="flex min-w-0 items-center gap-1">
                                        <h1 className="truncate text-lg font-semibold leading-tight">{flow?.name || 'Automação'}</h1>
                                        <button
                                            type="button"
                                            onClick={() => setIsRenameOpen(true)}
                                            disabled={!flow}
                                            className={agentiveIconButtonClass(isDark, 'primary', 'min-h-8 min-w-8 p-1.5')}
                                            aria-label="Editar nome do fluxo"
                                            title="Editar nome"
                                        >
                                            <Edit2 className="h-4 w-4" />
                                        </button>
                                    </div>
                                    <span className={agentivePillClass(isDark, flow?.is_active || false)}>
                                        {flow?.is_active ? 'Ativo' : 'Rascunho'}
                                    </span>
                                    <span className={agentivePillClass(isDark, isDirty)}>
                                        {isDirty ? 'Alterado' : 'Salvo'}
                                    </span>
                                </div>
                                <p className={`mt-1 text-xs ${isDark ? 'text-white/50' : 'text-brand/50'}`}>
                                    {nodes.length} nodes, {edges.length} conexões
                                </p>
                            </div>
                        </div>

                        <div className="flex flex-wrap items-center gap-2">
                            <button
                                type="button"
                                onClick={isFlowRunning ? onStopRunOnce : onGlobalRunOnce}
                                className={isFlowRunning ? 'inline-flex min-h-10 items-center gap-2 rounded-xl bg-red-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-700' : agentiveSecondaryButtonClass(isDark, 'min-h-10')}
                            >
                                {isFlowRunning ? <Square className="h-4 w-4 fill-current" /> : <Play className="h-4 w-4 fill-current" />}
                                {isFlowRunning ? 'Pausar' : 'Testar'}
                            </button>
                            <button
                                type="button"
                                onClick={onSave}
                                disabled={saving}
                                className={agentivePrimaryButtonClass('min-h-10 px-4')}
                            >
                                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                                {saving ? 'Salvando' : 'Salvar'}
                            </button>
                        </div>
                    </div>
                </header>

                <div
                    className={`grid min-h-0 flex-1 grid-cols-1 gap-3 p-3 lg:grid-cols-[var(--flow-builder-library-width)_minmax(0,1fr)] xl:grid-cols-[var(--flow-builder-library-width)_minmax(0,1fr)_var(--flow-builder-inspector-width)] ${isDark ? 'bg-white/[0.025]' : 'bg-brand-canvas'}`}
                    style={{
                        '--flow-builder-library-width': libraryColumnWidth,
                        '--flow-builder-inspector-width': inspectorColumnWidth,
                    } as React.CSSProperties}
                >
                    <FlowNodeLibrary
                        isCollapsed={!isLibraryPanelOpen}
                        nodes={nodes}
                        onAddNode={addNode}
                        onToggleCollapsed={() => setIsLibraryPanelOpen((current) => !current)}
                    />

                    <main
                        className={`relative min-h-[560px] min-w-0 overflow-hidden rounded-2xl border shadow-[0_18px_45px_rgba(2,3,35,0.08)] ${isDark ? 'border-white/10 bg-brand' : 'border-brand/10 bg-white'}`}
                        ref={reactFlowWrapper}
                    >
                    <ReactFlow
                        nodes={nodes}
                        edges={edges}
                        onNodesChange={onNodesChange}
                        onEdgesChange={onEdgesChange}
                        onConnect={onConnect}
                        nodeTypes={nodeTypes}
                        edgeTypes={edgeTypes}
                        defaultEdgeOptions={{ type: 'custom' }}
                        onInit={setReactFlowInstance}
                        onSelectionChange={(selection) => {
                            setSelectedNodeId(selection.nodes[0]?.id || null);
                            setSelectedEdgeId(selection.edges[0]?.id || null);
                        }}
                        fitView
                        attributionPosition="bottom-right"
                        minZoom={0.1}
                        maxZoom={2}
                        className={isDark ? 'bg-brand' : 'bg-brand-canvas'}
                    >
                        <Background color={isDark ? 'rgba(255,255,255,0.16)' : 'rgba(2,3,35,0.18)'} gap={22} size={1} variant={BackgroundVariant.Dots} />
                        <Controls className={`!rounded-2xl !border !shadow-flat-md ${isDark ? '!border-white/10 !bg-brand !text-white' : '!border-brand/10 !bg-white !text-brand'}`} />
                        <MiniMap
                            nodeColor={(node) => getFlowNodeColor(node.type)}
                            className={`!rounded-2xl !border !shadow-flat-md ${isDark ? '!border-white/10 !bg-brand' : '!border-brand/10 !bg-white'}`}
                        />
                        <FlowControls
                            onRunOnce={onGlobalRunOnce}
                            onStop={onStopRunOnce}
                            isRunning={isFlowRunning}
                            onSave={onSave}
                            onAutoAlign={onAutoAlign}
                            onToggleActive={onToggleActive}
                            isActive={flow?.is_active || false}
                            isSaving={saving}
                            isDirty={isDirty}
                        />

                        <Panel position="top-right" className="m-3">
                            <div className={`flex items-center gap-2 rounded-2xl border px-3 py-2 text-xs shadow-flat-md ${isDark ? 'border-white/10 bg-brand/90 text-white/60' : 'border-brand/10 bg-white/95 text-brand/55'}`}>
                                <Split className="h-3.5 w-3.5" />
                                Flow Builder v0.3
                            </div>
                        </Panel>
                    </ReactFlow>
                </main>

                    <FlowInspector
                        edges={edges}
                        flow={flow}
                        isCollapsed={!isInspectorPanelOpen}
                        isDirty={isDirty}
                        nodes={nodes}
                        onToggleCollapsed={() => setIsInspectorPanelOpen((current) => !current)}
                        selectedEdgeId={selectedEdgeId}
                        selectedNode={selectedNode}
                    />
                </div>
            </section>

            <FlowRenameModal
                initialName={flow?.name || ''}
                isDark={isDark}
                isOpen={isRenameOpen}
                isSaving={renaming}
                onClose={() => setIsRenameOpen(false)}
                onSubmit={handleRenameFlow}
            />
        </div>
    );

};

export default function FlowBuilder() {
    return (
        <ReactFlowProvider>
            <FlowVariablesProvider>
                <FlowConfirmProvider>
                    <FlowBuilderCanvas />
                </FlowConfirmProvider>
            </FlowVariablesProvider>
        </ReactFlowProvider>
    );
}
