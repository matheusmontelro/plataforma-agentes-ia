import React, { memo, useCallback, useEffect, useMemo, useState } from 'react';
import { NodeProps, Position, useReactFlow } from 'reactflow';
import { AlertCircle, Check, ChevronDown, GitBranch, Play, Trash2 } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import { pipelineApi, type Pipeline, type PipelineStage } from '../../services/crmApi.ts';
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

const MoveCrmStageNode = ({ data, id, selected, isConnectable }: NodeProps) => {
    const { isDark } = useTheme();
    const { deleteElements, setNodes } = useReactFlow();
    const { executionData, setIsFlowRunning, setNodeExecutionData } = useFlowVariables();
    const { confirm, notice } = useFlowConfirm();

    const [pipelines, setPipelines] = useState<Pipeline[]>([]);
    const [stages, setStages] = useState<PipelineStage[]>([]);
    const [pipelineId, setPipelineId] = useState(data.pipelineId ? String(data.pipelineId) : '');
    const [stageId, setStageId] = useState(data.stageId ? String(data.stageId) : '');
    const [leadId, setLeadId] = useState(data.leadId ? String(data.leadId) : '');
    const [leadPhone, setLeadPhone] = useState(
        data.leadPhone !== undefined ? String(data.leadPhone) : '{{lead.phone}}'
    );
    const [notes, setNotes] = useState(String(data.notes || 'Movido pelo FlowBuilder.'));
    const [loadingPipelines, setLoadingPipelines] = useState(true);
    const [loadingStages, setLoadingStages] = useState(false);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [executionResult, setExecutionResult] = useState<{ success: boolean; message: string } | null>(null);
    const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null);

    const selectedPipeline = useMemo(
        () => pipelines.find((pipeline) => String(pipeline.id) === pipelineId) || null,
        [pipelineId, pipelines]
    );

    const selectedStage = useMemo(
        () => stages.find((stage) => String(stage.id) === stageId) || null,
        [stageId, stages]
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

        const loadPipelines = async () => {
            try {
                setLoadingPipelines(true);
                setLoadError(null);
                const items = await pipelineApi.getPipelines();
                if (!mounted) return;

                setPipelines(items);
                if (pipelineId) {
                    const currentPipeline = items.find((pipeline) => String(pipeline.id) === pipelineId);
                    setStages(currentPipeline?.stages || []);
                }
            } catch (error: any) {
                if (mounted) setLoadError(error?.message || 'Erro ao carregar funis.');
            } finally {
                if (mounted) setLoadingPipelines(false);
            }
        };

        loadPipelines();

        return () => {
            mounted = false;
        };
    }, []);

    const handlePipelineChange = async (value: string) => {
        setPipelineId(value);
        setStageId('');
        updateNodeData({ pipelineId: value, stageId: '' });

        if (!value) {
            setStages([]);
            return;
        }

        setLoadingStages(true);
        try {
            const loadedStages = await pipelineApi.getStages(Number(value));
            setStages(loadedStages);
        } catch (error: any) {
            setLoadError(error?.message || 'Erro ao carregar etapas.');
            setStages([]);
        } finally {
            setLoadingStages(false);
        }
    };

    const handleStageChange = (value: string) => {
        setStageId(value);
        const stage = stages.find((item) => String(item.id) === value);
        updateNodeData({
            stageId: value,
            stageName: stage?.name || '',
        });
    };

    const handleNotesChange = (value: string) => {
        setNotes(value);
        updateNodeData({ notes: value });
    };

    const handleLeadIdChange = (value: string) => {
        setLeadId(value);
        updateNodeData({ leadId: value });
    };

    const handleLeadPhoneChange = (value: string) => {
        setLeadPhone(value);
        updateNodeData({ leadPhone: value });
    };

    const handleRunOnce = async (executeChain = false) => {
        if (!pipelineId || !stageId) {
            await notice({
                title: 'Destino incompleto',
                message: 'Selecione o funil e a etapa de destino antes de simular este node.',
            });
            if (executeChain) setIsFlowRunning(false);
            return;
        }

        const output = {
            success: true,
            simulated: true,
            changed: true,
            pipeline_id: Number(pipelineId),
            pipeline_name: selectedPipeline?.name || '',
            stage_id: Number(stageId),
            stage_name: selectedStage?.name || '',
            lead_id: leadId ? interpolateVariables(leadId, executionData) : '',
            lead_phone: interpolateVariables(leadPhone, executionData),
            notes: interpolateVariables(notes, executionData),
        };

        setExecutionResult({
            success: true,
            message: selectedStage ? `Lead iria para "${selectedStage.name}".` : 'Movimento simulado.',
        });
        setNodeExecutionData(id, output, executeChain, true);
    };

    const lastRunRef = React.useRef<number>(data.triggerRunOnce || 0);
    useEffect(() => {
        if (data.triggerRunOnce && data.triggerRunOnce !== lastRunRef.current) {
            lastRunRef.current = data.triggerRunOnce;
            handleRunOnce(true);
        }
    }, [data.triggerRunOnce, pipelineId, stageId, selectedPipeline, selectedStage, leadId, leadPhone, notes]);

    return (
        <div
            onContextMenu={(event) => {
                event.preventDefault();
                event.stopPropagation();
                setMenuPosition({ x: event.clientX, y: event.clientY });
            }}
            className={flowNodeShellClass(isDark, Boolean(selected), 'blue', 'min-w-[340px] max-w-[340px]')}
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
                                    title: 'Excluir avanço de CRM?',
                                    variant: 'danger',
                                });
                                if (confirmed) deleteElements({ nodes: [{ id }] });
                            },
                            danger: true,
                        },
                        {
                            label: 'Simular passagem',
                            icon: <Play className="h-3 w-3" />,
                            onClick: () => handleRunOnce(false),
                        },
                    ]}
                />
            )}

            <FlowNodeHeader icon={GitBranch} title="Avançar etapa CRM" subtitle="CRM" tone="blue" />

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

            <div className="max-h-[430px] space-y-4 overflow-y-auto p-4 custom-scrollbar nowheel" onWheel={(event) => event.stopPropagation()}>
                {loadError && (
                    <div className={flowNodePanelClass(isDark, 'amber')}>
                        <div className="flex items-start gap-2 text-xs">
                            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                            <span>{loadError}</span>
                        </div>
                    </div>
                )}

                <div className="grid grid-cols-1 gap-3">
                    <VariableInput
                        label="ID do lead"
                        value={leadId}
                        onChange={handleLeadIdChange}
                        placeholder="{{trigger.lead_id}}"
                    />

                    <VariableInput
                        label="Telefone do lead"
                        value={leadPhone}
                        onChange={handleLeadPhoneChange}
                        placeholder="{{lead.phone}}"
                    />
                </div>

                <div className="space-y-2">
                    <label className={flowNodeLabelClass(isDark)}>Funil</label>
                    <div className="relative">
                        <select
                            value={pipelineId}
                            disabled={loadingPipelines}
                            onMouseDown={(event) => event.stopPropagation()}
                            onChange={(event) => handlePipelineChange(event.target.value)}
                            className={flowNodeSelectClass(isDark)}
                        >
                            <option value="">{loadingPipelines ? 'Carregando funis...' : 'Selecione um funil'}</option>
                            {pipelines.map((pipeline) => (
                                <option key={pipeline.id} value={pipeline.id}>
                                    {pipeline.name}
                                </option>
                            ))}
                        </select>
                        <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 opacity-50" />
                    </div>
                </div>

                <div className="space-y-2">
                    <label className={flowNodeLabelClass(isDark)}>Etapa de destino</label>
                    <div className="relative">
                        <select
                            value={stageId}
                            disabled={!pipelineId || loadingStages}
                            onMouseDown={(event) => event.stopPropagation()}
                            onChange={(event) => handleStageChange(event.target.value)}
                            className={flowNodeSelectClass(isDark)}
                        >
                            <option value="">{loadingStages ? 'Carregando etapas...' : 'Selecione uma etapa'}</option>
                            {stages.map((stage) => (
                                <option key={stage.id} value={stage.id}>
                                    {stage.name}
                                </option>
                            ))}
                        </select>
                        <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 opacity-50" />
                    </div>
                </div>

                <VariableInput
                    label="Motivo / observação"
                    value={notes}
                    onChange={handleNotesChange}
                    placeholder="Movido pelo FlowBuilder"
                    isTextArea
                />

                {selectedStage && (
                    <div className={flowNodePanelClass(isDark, 'blue')}>
                        <p className="truncate text-xs font-semibold">{selectedPipeline?.name || 'Funil selecionado'}</p>
                        <p className="mt-1 truncate text-[11px] opacity-80">Destino: {selectedStage.name}</p>
                    </div>
                )}
            </div>

            <FlowNodeHandle type="target" position={Position.Left} tone="blue" isConnectable={isConnectable} />
            <FlowNodeHandle type="source" position={Position.Right} tone="blue" isConnectable={isConnectable} />
        </div>
    );
};

export default memo(MoveCrmStageNode);
