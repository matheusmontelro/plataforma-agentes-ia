import React, { memo, useCallback, useEffect, useMemo, useState } from 'react';
import { NodeProps, Position, useReactFlow } from 'reactflow';
import { AlertCircle, Check, ChevronDown, Headphones, Play, Trash2, UserCheck } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import { listUsers, type User } from '../../services/api.ts';
import { useFlowVariables } from '../../contexts/FlowVariablesContext.tsx';
import { interpolateVariables } from '../../utils/variableUtils.ts';
import { NodeContextMenu } from './NodeContextMenu.tsx';
import { VariableInput } from './VariableInput.tsx';
import { useFlowConfirm } from './FlowConfirmContext.tsx';
import {
    FlowNodeHandle,
    FlowNodeHeader,
    flowNodeLabelClass,
    flowNodePanelClass,
    flowNodeSelectClass,
    flowNodeShellClass,
} from './FlowNodeChrome.tsx';

const getCompanyId = () => Number.parseInt(
    (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'))
    || (sessionStorage.getItem('company_id') || sessionStorage.getItem('clinic_id'))
    || '0',
    10
);

const priorityLabels: Record<string, string> = {
    low: 'Baixa',
    medium: 'Média',
    high: 'Alta',
    urgent: 'Urgente',
};

const HumanHandoffNode = ({ data, id, selected, isConnectable }: NodeProps) => {
    const { isDark } = useTheme();
    const { deleteElements, setNodes } = useReactFlow();
    const { executionData, setIsFlowRunning, setNodeExecutionData } = useFlowVariables();
    const { confirm, notice } = useFlowConfirm();

    const [users, setUsers] = useState<User[]>([]);
    const [assignedUserId, setAssignedUserId] = useState(data.assignedUserId ? String(data.assignedUserId) : '');
    const [priority, setPriority] = useState(String(data.priority || 'high'));
    const [title, setTitle] = useState(String(data.title || 'Atender lead'));
    const [reason, setReason] = useState(String(data.reason || 'Solicitado pelo fluxo.'));
    const [summary, setSummary] = useState(String(data.summary || ''));
    const [leadPhone, setLeadPhone] = useState(
        data.leadPhone !== undefined ? String(data.leadPhone) : '{{lead.phone}}'
    );
    const [pauseBot, setPauseBot] = useState(data.pauseBot !== false);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [executionResult, setExecutionResult] = useState<{ success: boolean; message: string } | null>(null);
    const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null);

    const selectedUser = useMemo(
        () => users.find((user) => String(user.id) === assignedUserId) || null,
        [assignedUserId, users]
    );

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
        let mounted = true;

        const loadUsers = async () => {
            const companyId = getCompanyId();
            if (!companyId) {
                setLoadError('Empresa ativa não encontrada.');
                setLoading(false);
                return;
            }

            try {
                setLoading(true);
                setLoadError(null);
                const userData = await listUsers(companyId);
                if (!mounted) return;
                setUsers((userData || []).filter((user) => user.is_active !== false));
            } catch (error: any) {
                if (mounted) setLoadError(error?.message || 'Erro ao carregar usuários.');
            } finally {
                if (mounted) setLoading(false);
            }
        };

        loadUsers();

        return () => {
            mounted = false;
        };
    }, []);

    const handleAssignedUserChange = (value: string) => {
        setAssignedUserId(value);
        const user = users.find((item) => String(item.id) === value);
        updateNodeData({
            assignedUserId: value,
            assignedUserName: user?.name || '',
        });
    };

    const handlePriorityChange = (value: string) => {
        setPriority(value);
        updateNodeData({ priority: value });
    };

    const handleTitleChange = (value: string) => {
        setTitle(value);
        updateNodeData({ title: value });
    };

    const handleReasonChange = (value: string) => {
        setReason(value);
        updateNodeData({ reason: value });
    };

    const handleSummaryChange = (value: string) => {
        setSummary(value);
        updateNodeData({ summary: value });
    };

    const handleLeadPhoneChange = (value: string) => {
        setLeadPhone(value);
        updateNodeData({ leadPhone: value });
    };

    const handlePauseBotChange = (value: boolean) => {
        setPauseBot(value);
        updateNodeData({ pauseBot: value, stopFlow: true, silent: true });
    };

    const handleRunOnce = async (executeChain = false) => {
        if (!title.trim()) {
            await notice({
                title: 'Título ausente',
                message: 'Informe o título da tarefa antes de simular este node.',
            });
            if (executeChain) setIsFlowRunning(false);
            return;
        }

        const output = {
            success: true,
            simulated: true,
            silent: true,
            stop_flow: true,
            assigned_to: assignedUserId ? Number(assignedUserId) : null,
            assigned_to_name: selectedUser?.name || '',
            priority,
            lead_phone: interpolateVariables(leadPhone, executionData),
            title: interpolateVariables(title, executionData),
            reason: interpolateVariables(reason, executionData),
            summary: interpolateVariables(summary, executionData),
            bot_paused: pauseBot,
        };

        setExecutionResult({
            success: true,
            message: selectedUser ? `Tarefa para ${selectedUser.name}.` : 'Tarefa sem responsável fixo.',
        });
        setNodeExecutionData(id, output, false, true);
        if (executeChain) setIsFlowRunning(false);
    };

    const lastRunRef = React.useRef<number>(data.triggerRunOnce || 0);
    useEffect(() => {
        if (data.triggerRunOnce && data.triggerRunOnce !== lastRunRef.current) {
            lastRunRef.current = data.triggerRunOnce;
            handleRunOnce(true);
        }
    }, [data.triggerRunOnce, assignedUserId, selectedUser, priority, leadPhone, title, reason, summary, pauseBot]);

    return (
        <div
            onContextMenu={(event) => {
                event.preventDefault();
                event.stopPropagation();
                setMenuPosition({ x: event.clientX, y: event.clientY });
            }}
            className={flowNodeShellClass(isDark, Boolean(selected), 'purple', 'min-w-[340px] max-w-[340px]')}
        >
            {menuPosition && (
                <NodeContextMenu
                    x={menuPosition.x}
                    y={menuPosition.y}
                    onClose={() => setMenuPosition(null)}
                    actions={[
                        {
                            label: 'Excluir node',
                            icon: <Trash2 className="h-3 w-3" />,
                            onClick: async () => {
                                const confirmed = await confirm({
                                    confirmText: 'Excluir node',
                                    message: 'Este node e suas conexões serão removidos do fluxo.',
                                    title: 'Excluir handoff humano?',
                                    variant: 'danger',
                                });
                                if (confirmed) deleteElements({ nodes: [{ id }] });
                            },
                            danger: true,
                        },
                        {
                            label: 'Simular handoff',
                            icon: <Play className="h-3 w-3" />,
                            onClick: () => handleRunOnce(false),
                        },
                    ]}
                />
            )}

            <FlowNodeHeader
                icon={Headphones}
                title="Atribuir humano"
                subtitle="Handoff silencioso"
                tone="purple"
                meta={(
                    <span className="rounded-full border border-purple-300/25 bg-purple-300/10 px-2 py-1 text-[10px] font-semibold text-purple-100">
                        Silencioso
                    </span>
                )}
            />

            {executionResult && (
                <div className={`flex items-center gap-2 border-b px-4 py-2 text-xs ${
                    executionResult.success
                        ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-500'
                        : 'border-red-500/20 bg-red-500/10 text-red-500'
                }`}>
                    {executionResult.success ? <Check className="h-3 w-3" /> : <AlertCircle className="h-3 w-3" />}
                    <span className="truncate">{executionResult.message}</span>
                </div>
            )}

            <div className="max-h-[460px] space-y-4 overflow-y-auto p-4 custom-scrollbar nowheel" onWheel={(event) => event.stopPropagation()}>
                {loadError && (
                    <div className={flowNodePanelClass(isDark, 'amber')}>
                        <div className="flex items-start gap-2 text-xs">
                            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                            <span>{loadError}</span>
                        </div>
                    </div>
                )}

                <VariableInput
                    label="Telefone do lead"
                    value={leadPhone}
                    onChange={handleLeadPhoneChange}
                    placeholder="{{lead.phone}}"
                />

                <div className="space-y-2">
                    <label className={flowNodeLabelClass(isDark)}>Responsável</label>
                    <div className="relative">
                        <select
                            value={assignedUserId}
                            disabled={loading}
                            onMouseDown={(event) => event.stopPropagation()}
                            onChange={(event) => handleAssignedUserChange(event.target.value)}
                            className={flowNodeSelectClass(isDark)}
                        >
                            <option value="">{loading ? 'Carregando usuários...' : 'Sem responsável fixo'}</option>
                            {users.map((user) => (
                                <option key={user.id} value={user.id}>
                                    {user.name || user.email}
                                </option>
                            ))}
                        </select>
                        <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 opacity-50" />
                    </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-2">
                        <label className={flowNodeLabelClass(isDark)}>Prioridade</label>
                        <div className="relative">
                            <select
                                value={priority}
                                onMouseDown={(event) => event.stopPropagation()}
                                onChange={(event) => handlePriorityChange(event.target.value)}
                                className={flowNodeSelectClass(isDark)}
                            >
                                {Object.entries(priorityLabels).map(([value, label]) => (
                                    <option key={value} value={value}>
                                        {label}
                                    </option>
                                ))}
                            </select>
                            <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 opacity-50" />
                        </div>
                    </div>

                    <label className={`flex min-h-[64px] cursor-pointer items-center gap-3 rounded-xl border px-3 py-2 text-xs font-semibold transition ${
                        isDark ? 'border-white/10 bg-white/[0.04] text-white/70' : 'border-brand/10 bg-brand-canvas text-brand/70'
                    }`}>
                        <input
                            type="checkbox"
                            checked={pauseBot}
                            onMouseDown={(event) => event.stopPropagation()}
                            onChange={(event) => handlePauseBotChange(event.target.checked)}
                            className="h-4 w-4 rounded border-brand/20 text-brand focus:ring-brand/20"
                        />
                        <span>Pausar IA</span>
                    </label>
                </div>

                <VariableInput
                    label="Título da task"
                    value={title}
                    onChange={handleTitleChange}
                    placeholder="Atender lead"
                />

                <VariableInput
                    label="Motivo"
                    value={reason}
                    onChange={handleReasonChange}
                    placeholder="Solicitou atendimento humano"
                    isTextArea
                />

                <VariableInput
                    label="Resumo"
                    value={summary}
                    onChange={handleSummaryChange}
                    placeholder="Resumo para o atendimento"
                    isTextArea
                />

                <div className={flowNodePanelClass(isDark, 'purple')}>
                    <div className="flex items-center gap-2">
                        <UserCheck className="h-3.5 w-3.5" />
                        <span className="truncate text-xs font-semibold">
                            {selectedUser?.name || 'Sem responsável fixo'}
                        </span>
                    </div>
                    <p className="mt-1 text-[11px] opacity-80">
                        Saída: {'{{human_handoff.task_id}}'}
                    </p>
                </div>
            </div>

            <FlowNodeHandle type="target" position={Position.Left} tone="purple" isConnectable={isConnectable} />
            <FlowNodeHandle type="source" position={Position.Right} tone="purple" isConnectable={isConnectable} />
        </div>
    );
};

export default memo(HumanHandoffNode);
