import React, { memo, useCallback, useEffect, useMemo, useState } from 'react';
import { NodeProps, Position, useReactFlow } from 'reactflow';
import { AlertCircle, Bot, Check, ChevronDown, Loader2, MessageSquare, Network, Play, Trash2 } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import { NodeContextMenu } from './NodeContextMenu.tsx';
import { VariableInput } from './VariableInput.tsx';
import { useFlowVariables } from '../../contexts/FlowVariablesContext.tsx';
import { interpolateVariables } from '../../utils/variableUtils.ts';
import { useFlowConfirm } from './FlowConfirmContext.tsx';
import {
    FlowNodeHandle,
    FlowNodeHeader,
    flowNodeLabelClass,
    flowNodePanelClass,
    flowNodeSelectClass,
    flowNodeShellClass,
} from './FlowNodeChrome.tsx';
import {
    AgentWorkforce,
    getAgentWorkforces,
    runAgentWorkforce
} from '../../services/agentWorkforceApi.ts';

const getRootAgentName = (workforce?: AgentWorkforce | null) => {
    if (!workforce?.root_agent_key) return 'Raiz não definida';
    const rootConfig = workforce.agent_configs?.[workforce.root_agent_key];
    return rootConfig?.agent?.name || workforce.root_agent_key;
};

const getAgentCount = (workforce: AgentWorkforce) =>
    (workforce.nodes || []).filter((node: any) => node?.data?.kind !== 'human').length;

const AgentWorkforceNode = ({ data, id, selected }: NodeProps) => {
    const { isDark } = useTheme();
    const { deleteElements, setNodes } = useReactFlow();
    const { executionData, setNodeExecutionData } = useFlowVariables();
    const { confirm, notice } = useFlowConfirm();

    const [workforces, setWorkforces] = useState<AgentWorkforce[]>([]);
    const [selectedWorkforceId, setSelectedWorkforceId] = useState<number | null>(data.workforceId || null);
    const [inputMessage, setInputMessage] = useState(data.inputMessage || '{{trigger.body}}');
    const [loading, setLoading] = useState(true);
    const [executing, setExecuting] = useState(false);
    const [executionResult, setExecutionResult] = useState<{
        success: boolean;
        message?: string;
        response?: string;
    } | null>(null);
    const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null);

    const selectedWorkforce = useMemo(
        () => workforces.find((workforce) => workforce.id === selectedWorkforceId) || null,
        [selectedWorkforceId, workforces]
    );

    useEffect(() => {
        const loadWorkforces = async () => {
            try {
                const data = await getAgentWorkforces();
                setWorkforces(data || []);
            } catch (error) {
                console.error('Failed to load agent workforces', error);
            } finally {
                setLoading(false);
            }
        };
        loadWorkforces();
    }, []);

    const updateNodeData = useCallback((updates: Record<string, unknown>) => {
        if (data.onDataChange) {
            data.onDataChange(id, updates);
            return;
        }

        setNodes((nodes) =>
            nodes.map((node) =>
                node.id === id
                    ? { ...node, data: { ...node.data, ...updates } }
                    : node
            )
        );
    }, [data, id, setNodes]);

    useEffect(() => {
        if (data.workforceId !== selectedWorkforceId) {
            updateNodeData({ workforceId: selectedWorkforceId });
        }
    }, [data.workforceId, selectedWorkforceId, updateNodeData]);

    useEffect(() => {
        if (data.inputMessage !== inputMessage) {
            updateNodeData({ inputMessage });
        }
    }, [data.inputMessage, inputMessage, updateNodeData]);

    const lastRunRef = React.useRef<number>(data.triggerRunOnce || 0);
    useEffect(() => {
        if (data.triggerRunOnce && data.triggerRunOnce !== lastRunRef.current && executing !== true) {
            lastRunRef.current = data.triggerRunOnce;
            handleRunOnce(true);
        }
    }, [data.triggerRunOnce, executing]);

    const handleRunOnce = async (executeChain = false) => {
        if (!selectedWorkforceId) {
            await notice({
                title: 'Equipe ausente',
                message: 'Selecione uma equipe de agentes antes de testar este node.',
            });
            return;
        }

        if (!inputMessage) {
            await notice({
                title: 'Mensagem ausente',
                message: 'Configure a mensagem de entrada antes de executar a equipe.',
            });
            return;
        }

        setExecuting(true);
        setExecutionResult(null);

        try {
            const finalMessage = interpolateVariables(inputMessage, executionData);
            const result = await runAgentWorkforce(selectedWorkforceId, finalMessage, [], true);

            if (!result.success) {
                throw new Error(result.error || 'Falha ao executar equipe de agentes');
            }

            const output = {
                success: true,
                response: result.response,
                tokens_used: result.tokens_used,
                workforce_id: result.workforce_id || selectedWorkforceId,
                workforce_name: result.workforce_name || selectedWorkforce?.name,
                root_agent_key: result.root_agent_key || selectedWorkforce?.root_agent_key,
                root_agent_name: result.root_agent_name || getRootAgentName(selectedWorkforce)
            };

            setNodeExecutionData(id, output, executeChain, true);
            setExecutionResult({
                success: true,
                message: 'Resposta gerada.',
                response: result.response
            });
        } catch (error: any) {
            console.error('AgentWorkforceNode Error', error);
            setExecutionResult({
                success: false,
                message: error.message || 'Erro ao executar equipe de agentes'
            });
        } finally {
            setExecuting(false);
        }
    };

    return (
        <div
            onContextMenu={(event) => {
                event.preventDefault();
                event.stopPropagation();
                setMenuPosition({ x: event.clientX, y: event.clientY });
            }}
            className={flowNodeShellClass(isDark, selected, 'indigo', 'min-w-[340px] max-w-[340px]')}
        >
            {menuPosition && (
                <NodeContextMenu
                    x={menuPosition.x}
                    y={menuPosition.y}
                    onClose={() => setMenuPosition(null)}
                    actions={[
                        {
                            label: 'Excluir Nó',
                            icon: <Trash2 className="w-3 h-3" />,
                            onClick: async () => {
                                const confirmed = await confirm({
                                    confirmText: 'Excluir node',
                                    message: 'Este node e suas conexões serão removidos do fluxo.',
                                    title: 'Excluir equipe de agentes?',
                                    variant: 'danger',
                                });
                                if (confirmed) deleteElements({ nodes: [{ id }] });
                            },
                            danger: true
                        },
                        { label: 'Testar Equipe', icon: <Play className="w-3 h-3" />, onClick: () => handleRunOnce(false) }
                    ]}
                />
            )}

            <FlowNodeHeader icon={Network} title="Equipe de agentes" subtitle="Multiagente" tone="indigo" />

            {executing && (
                <div className="px-4 py-2 bg-yellow-500/10 text-yellow-500 text-xs flex items-center gap-2 animate-pulse border-b border-yellow-500/20">
                    <Loader2 className="w-3 h-3 animate-spin" /> Processando equipe...
                </div>
            )}
            {executionResult && !executing && (
                <div className={`px-4 py-2 text-xs flex items-center gap-2 border-b ${executionResult.success ? 'bg-green-500/10 text-green-500 border-green-500/20' : 'bg-red-500/10 text-red-500 border-red-500/20'}`}>
                    {executionResult.success ? <Check className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
                    <span className="truncate">{executionResult.message}</span>
                </div>
            )}

            <div className="p-4 space-y-4 max-h-[430px] overflow-y-auto custom-scrollbar nowheel" onWheel={(event) => event.stopPropagation()}>
                <div className="space-y-1">
                    <label className={flowNodeLabelClass(isDark)}>
                        Equipe
                    </label>
                    <div className="relative">
                        <select
                            value={selectedWorkforceId || ''}
                            onChange={(event) => setSelectedWorkforceId(event.target.value ? Number(event.target.value) : null)}
                            disabled={loading}
                            className={flowNodeSelectClass(isDark)}
                        >
                            <option value="">{loading ? 'Carregando...' : 'Selecione uma equipe'}</option>
                            {workforces.map((workforce) => (
                                <option key={workforce.id} value={workforce.id}>
                                    {workforce.name}
                                </option>
                            ))}
                        </select>
                        <ChevronDown className="w-4 h-4 absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none opacity-50" />
                    </div>
                </div>

                {selectedWorkforce && (
                    <div className={flowNodePanelClass(isDark, 'indigo')}>
                        <div className="flex items-center gap-2">
                            <Bot className={`w-3.5 h-3.5 ${isDark ? 'text-indigo-300' : 'text-indigo-600'}`} />
                            <p className={`text-xs font-semibold ${isDark ? 'text-indigo-300' : 'text-indigo-700'}`}>
                                Primeiro agente: {getRootAgentName(selectedWorkforce)}
                            </p>
                        </div>
                        <p className={`mt-1 text-[10px] ${isDark ? 'text-indigo-400/80' : 'text-indigo-600/80'}`}>
                            {getAgentCount(selectedWorkforce)} agentes IA. Saída: {'{{agent_workforce.response}}'}
                        </p>
                    </div>
                )}

                <VariableInput
                    label="Mensagem de entrada"
                    value={inputMessage}
                    onChange={(value) => setInputMessage(value)}
                    placeholder="{{trigger.body}}"
                />

                <div className={flowNodePanelClass(isDark, 'indigo')}>
                    <div className="flex items-center gap-2 font-semibold">
                        <MessageSquare className="w-3.5 h-3.5" />
                        <span>Saída para o nó Msg WhatsApp</span>
                    </div>
                    <code className={`mt-1 block rounded px-2 py-1 font-mono text-[11px] ${isDark ? 'bg-gray-950/50 text-indigo-100' : 'bg-white text-indigo-700'}`}>
                        {'{{agent_workforce.response}}'}
                    </code>
                </div>

                {executionResult?.response && (
                    <div className="space-y-1">
                        <label className={flowNodeLabelClass(isDark)}>
                            Resposta da equipe
                        </label>
                        <div className={`max-h-[150px] overflow-y-auto rounded-xl border p-3 text-xs ${isDark ? 'border-white/10 bg-black/20' : 'border-brand/10 bg-brand-canvas'}`}>
                            {executionResult.response}
                        </div>
                    </div>
                )}
            </div>

            <FlowNodeHandle type="target" position={Position.Left} tone="indigo" />
            <FlowNodeHandle type="source" position={Position.Right} tone="indigo" />
        </div>
    );
};

export default memo(AgentWorkforceNode);
