import React, { memo, useEffect, useState } from 'react';
import { Position, NodeProps, useReactFlow } from 'reactflow';
import { Bot, Trash2, Play, Check, AlertCircle, Loader2, ChevronDown } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import { NodeContextMenu } from './NodeContextMenu.tsx';
import { VariableInput } from './VariableInput.tsx';
import { useFlowVariables } from '../../contexts/FlowVariablesContext.tsx';
import { interpolateVariables } from '../../utils/variableUtils.ts';
import api, { listAgentConfigs } from '../../services/api.ts';
import { useFlowConfirm } from './FlowConfirmContext.tsx';
import {
    FlowNodeHandle,
    FlowNodeHeader,
    flowNodeLabelClass,
    flowNodePanelClass,
    flowNodeSelectClass,
    flowNodeShellClass,
} from './FlowNodeChrome.tsx';

interface AgentSummary {
    id: number;
    name: string;
    role: string;
}

const AgentResponseNode = ({ data, id, selected }: NodeProps) => {
    const { isDark } = useTheme();
    const { deleteElements } = useReactFlow();
    const { executionData, setNodeExecutionData } = useFlowVariables();
    const { confirm, notice } = useFlowConfirm();

    // State
    const [selectedAgentId, setSelectedAgentId] = useState<number | null>(data.agentId || null);
    const [agents, setAgents] = useState<AgentSummary[]>([]);
    const [inputMessage, setInputMessage] = useState(data.inputMessage || '{{trigger.body}}');
    const [loading, setLoading] = useState(true);

    // Execution State
    const [executing, setExecuting] = useState(false);
    const [executionResult, setExecutionResult] = useState<{ success: boolean, message?: string, response?: string } | null>(null);

    // Context Menu State
    const [menuPosition, setMenuPosition] = useState<{ x: number, y: number } | null>(null);

    // Load agents on mount
    useEffect(() => {
        const loadAgents = async () => {
            try {
                const data = await listAgentConfigs();
                setAgents(data || []);
            } catch (err) {
                console.error('Failed to load agents', err);
            } finally {
                setLoading(false);
            }
        };
        loadAgents();
    }, []);

    // Sync state to data (persistence)
    useEffect(() => {
        data.agentId = selectedAgentId;
    }, [selectedAgentId, data]);

    useEffect(() => {
        data.inputMessage = inputMessage;
    }, [inputMessage, data]);

    // Chain Execution Trigger
    const lastRunRef = React.useRef<number>(data.triggerRunOnce || 0);
    useEffect(() => {
        if (data.triggerRunOnce && data.triggerRunOnce !== lastRunRef.current && executing !== true) {
            console.log("External trigger received for AgentResponseNode:", id);
            lastRunRef.current = data.triggerRunOnce;
            handleRunOnce(true);
        }
    }, [data.triggerRunOnce, executing]);

    // Execution Logic
    const handleRunOnce = async (executeChain = false) => {
        if (!selectedAgentId) {
            await notice({
                title: 'Agente ausente',
                message: 'Selecione um agente antes de testar este node.',
            });
            return;
        }

        if (!inputMessage) {
            await notice({
                title: 'Mensagem ausente',
                message: 'Configure a mensagem de entrada antes de executar o agente.',
            });
            return;
        }

        setExecuting(true);
        setExecutionResult(null);

        try {
            const finalMessage = interpolateVariables(inputMessage, executionData);
            console.log(`[AgentResponseNode] Calling agent ${selectedAgentId} with message:`, finalMessage);

            const { data: result } = await api.post('/api/flows/run-agent', {
                agent_config_id: selectedAgentId,
                message: finalMessage
            });

            if (!result.success) {
                throw new Error(result.error || result.detail || 'Agent execution failed');
            }

            console.log(`[AgentResponseNode] Agent response:`, result.response);

            // Signal node completion for chain execution (no variable output for action nodes)
            setNodeExecutionData(id, {
                success: true,
                response: result.response,
                tokens_used: result.tokens_used
            }, executeChain);

            setExecutionResult({
                success: true,
                message: 'Resposta gerada!',
                response: result.response
            });

        } catch (error: any) {
            console.error("AgentResponse Error", error);
            setExecutionResult({
                success: false,
                message: error.message || 'Erro ao executar agente'
            });
        } finally {
            setExecuting(false);
        }
    };

    const selectedAgent = agents.find(a => a.id === selectedAgentId);

    return (
        <div
            onContextMenu={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setMenuPosition({ x: e.clientX, y: e.clientY });
            }}
            className={flowNodeShellClass(isDark, selected, 'emerald')}
        >
            {/* Context Menu */}
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
                                    title: 'Excluir agente IA?',
                                    variant: 'danger',
                                });
                                if (confirmed) deleteElements({ nodes: [{ id }] });
                            },
                            danger: true
                        },
                        { label: 'Testar Agente', icon: <Play className="w-3 h-3" />, onClick: () => handleRunOnce(false) }
                    ]}
                />
            )}

            <FlowNodeHeader icon={Bot} title="Agente IA" subtitle="IA" tone="emerald" />

            {/* Status */}
            {executing && (
                <div className="px-4 py-2 bg-yellow-500/10 text-yellow-500 text-xs flex items-center gap-2 animate-pulse border-b border-yellow-500/20">
                    <Loader2 className="w-3 h-3 animate-spin" /> Processando com IA...
                </div>
            )}
            {executionResult && !executing && (
                <div className={`px-4 py-2 text-xs flex items-center gap-2 border-b ${executionResult.success ? 'bg-green-500/10 text-green-500 border-green-500/20' : 'bg-red-500/10 text-red-500 border-red-500/20'}`}>
                    {executionResult.success ? <Check className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
                    <span className="truncate">{executionResult.message}</span>
                </div>
            )}

            {/* Content */}
            <div
                className="p-4 space-y-4 max-h-[400px] overflow-y-auto custom-scrollbar nowheel"
                onWheel={(e) => e.stopPropagation()}
            >
                {/* Agent Selector */}
                <div className="space-y-1">
                    <label className={flowNodeLabelClass(isDark)}>
                        Agente
                    </label>
                    <div className="relative">
                        <select
                            value={selectedAgentId || ''}
                            onChange={(e) => setSelectedAgentId(e.target.value ? parseInt(e.target.value) : null)}
                            disabled={loading}
                            className={flowNodeSelectClass(isDark)}
                        >
                            <option value="">{loading ? 'Carregando...' : 'Selecione um agente'}</option>
                            {agents.map(agent => (
                                <option key={agent.id} value={agent.id}>
                                    {agent.name} - {agent.role}
                                </option>
                            ))}
                        </select>
                        <ChevronDown className="w-4 h-4 absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none opacity-50" />
                    </div>
                </div>

                {/* Selected Agent Info */}
                {selectedAgent && (
                    <div className={flowNodePanelClass(isDark, 'emerald')}>
                        <p className={`text-xs font-medium ${isDark ? 'text-emerald-400' : 'text-emerald-700'}`}>
                            {selectedAgent.name}
                        </p>
                        <p className={`text-[10px] ${isDark ? 'text-emerald-500/70' : 'text-emerald-600/70'}`}>
                            {selectedAgent.role}
                        </p>
                    </div>
                )}

                {/* Input Message */}
                <VariableInput
                    label="Mensagem de Entrada"
                    value={inputMessage}
                    onChange={(val) => setInputMessage(val)}
                    placeholder="{{trigger.body}} ou texto fixo..."
                />

                {/* Output Preview */}
                {executionResult?.response && (
                    <div className="space-y-1">
                        <label className={flowNodeLabelClass(isDark)}>
                            Resposta do Agente
                        </label>
                        <div className={`max-h-[150px] overflow-y-auto rounded-xl border p-3 text-xs ${isDark ? 'border-white/10 bg-black/20' : 'border-brand/10 bg-brand-canvas'}`}>
                            {executionResult.response}
                        </div>
                    </div>
                )}
            </div>

            <FlowNodeHandle type="target" position={Position.Left} tone="emerald" />
            <FlowNodeHandle type="source" position={Position.Right} tone="emerald" />
        </div>
    );
};

export default memo(AgentResponseNode);
