import React, { memo, useEffect, useRef, useState } from 'react';
import { Handle, Position, NodeProps, useReactFlow } from 'reactflow';
import { GitBranch, Trash2 } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import { pipelineApi, type Pipeline, type PipelineStage } from '../../services/crmApi.ts';
import { useFlowVariables } from '../../contexts/FlowVariablesContext.tsx';
import { NodeContextMenu } from './NodeContextMenu.tsx';
import { useFlowConfirm } from './FlowConfirmContext.tsx';

type CrmTriggerEvent = 'lead_created' | 'crm_stage_entered';

const normalizeCrmEvent = (value: unknown): CrmTriggerEvent => {
    return value === 'lead_created' ? 'lead_created' : 'crm_stage_entered';
};

const CrmStageTriggerNode = ({ data, id, selected }: NodeProps) => {
    const { isDark } = useTheme();
    const { deleteElements } = useReactFlow();
    const { setNodeExecutionData } = useFlowVariables();
    const { confirm } = useFlowConfirm();
    const [pipelines, setPipelines] = useState<Pipeline[]>([]);
    const [stages, setStages] = useState<PipelineStage[]>([]);
    const [eventType, setEventType] = useState<CrmTriggerEvent>(
        normalizeCrmEvent(data.eventType || data.event || data.crmEventType)
    );
    const [pipelineId, setPipelineId] = useState(data.pipelineId || '');
    const [stageId, setStageId] = useState(data.stageId || '');
    const [loadingPipelines, setLoadingPipelines] = useState(false);
    const [loadingStages, setLoadingStages] = useState(false);
    const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null);
    const lastRunRef = useRef<number>(Number(data.triggerRunOnce) || 0);

    useEffect(() => {
        let mounted = true;

        const loadPipelines = async () => {
            setLoadingPipelines(true);
            try {
                const items = await pipelineApi.getPipelines();
                if (!mounted) return;
                setPipelines(items);

                if (pipelineId) {
                    const selected = items.find((pipeline) => String(pipeline.id) === String(pipelineId));
                    setStages(selected?.stages || []);
                }
            } catch (error) {
                console.error('Erro ao carregar funis para o gatilho CRM', error);
            } finally {
                if (mounted) setLoadingPipelines(false);
            }
        };

        loadPipelines();

        return () => {
            mounted = false;
        };
    }, []);

    useEffect(() => {
        const runToken = Number(data.triggerRunOnce) || 0;
        if (!runToken || runToken === lastRunRef.current) return;

        lastRunRef.current = runToken;
        const selectedPipeline = pipelines.find((pipeline) => String(pipeline.id) === String(pipelineId));
        const selectedStage = stages.find((stage) => String(stage.id) === String(stageId));
        const enteredAt = new Date().toISOString();

        const lead = {
            id: 123,
            name: 'Cliente Exemplo',
            phone: '5500000000007',
            pipeline_id: pipelineId ? Number(pipelineId) : selectedPipeline?.id || null,
            current_stage_id: eventType === 'crm_stage_entered'
                ? (stageId ? Number(stageId) : selectedStage?.id || null)
                : null,
            created_at: enteredAt,
            data_entrada: enteredAt,
        };

        const sample = eventType === 'lead_created' ? {
            event: 'lead_created',
            anchor_at: enteredAt,
            phone: lead.phone,
            name: lead.name,
            lead_id: lead.id,
            lead,
            crm: {
                event: 'lead_created',
                event_label: 'Lead criado',
            },
            crm_stage: {
                lead_id: lead.id,
                pipeline_id: lead.pipeline_id,
                stage_id: null,
                stage_name: 'Novo Lead',
                entered_at: enteredAt,
            },
        } : {
            event: 'crm_stage_entered',
            anchor_at: enteredAt,
            phone: lead.phone,
            name: lead.name,
            lead_id: lead.id,
            lead,
            crm: {
                event: 'crm_stage_entered',
                event_label: 'Entrada em etapa',
            },
            crm_stage: {
                lead_id: lead.id,
                pipeline_id: lead.pipeline_id,
                stage_id: lead.current_stage_id,
                stage_name: selectedStage?.name || 'Etapa exemplo',
                entered_at: enteredAt
            }
        };

        setNodeExecutionData(id, sample, true, true);
    }, [data.triggerRunOnce, eventType, id, pipelineId, pipelines, setNodeExecutionData, stageId, stages]);

    const updateData = (updates: Record<string, unknown>) => {
        Object.assign(data, updates);
        data.onDataChange?.(id, updates);
    };

    const handleEventTypeChange = (value: CrmTriggerEvent) => {
        setEventType(value);
        const updates: Record<string, unknown> = {
            eventType: value,
            event: value,
            label: value === 'lead_created' ? 'Lead criado no CRM' : 'Entrada em etapa CRM',
        };

        if (value === 'lead_created') {
            updates.stageId = '';
            setStageId('');
        }

        updateData(updates);
    };

    const handlePipelineChange = async (value: string) => {
        setPipelineId(value);
        setStageId('');
        updateData({
            pipelineId: value,
            stageId: '',
            label: eventType === 'lead_created' ? 'Lead criado no CRM' : 'Entrada em etapa CRM',
        });

        if (!value) {
            setStages([]);
            return;
        }

        setLoadingStages(true);
        try {
            const loadedStages = await pipelineApi.getStages(Number(value));
            setStages(loadedStages);
        } catch (error) {
            console.error('Erro ao carregar etapas para o gatilho CRM', error);
            setStages([]);
        } finally {
            setLoadingStages(false);
        }
    };

    const handleStageChange = (value: string) => {
        setStageId(value);
        updateData({ stageId: value, label: 'Entrada em etapa CRM' });
    };

    const handleContextMenu = (event: React.MouseEvent) => {
        event.preventDefault();
        event.stopPropagation();
        setMenuPosition({ x: event.clientX, y: event.clientY });
    };

    const handleDelete = async () => {
        const confirmed = await confirm({
            confirmText: 'Excluir gatilho',
            message: 'Este gatilho e suas conexões serão removidos do fluxo.',
            title: 'Excluir gatilho de CRM?',
            variant: 'danger',
        });

        if (confirmed) {
            deleteElements({ nodes: [{ id }] });
        }
    };

    return (
        <div
            onContextMenu={handleContextMenu}
            className={`rounded-lg border-l-4 border-indigo-500 bg-white text-xs shadow-lg dark:bg-gray-800 ${selected ? 'ring-2 ring-indigo-300' : ''}`}
        >
            {menuPosition && (
                <NodeContextMenu
                    x={menuPosition.x}
                    y={menuPosition.y}
                    onClose={() => setMenuPosition(null)}
                    actions={[
                        { label: 'Excluir', icon: <Trash2 className="h-3 w-3" />, onClick: handleDelete, danger: true },
                    ]}
                />
            )}

            <div className="flex items-center gap-2 border-b border-gray-100 p-2 font-medium dark:border-gray-700">
                <GitBranch size={13} className="text-indigo-500" />
                Evento CRM
            </div>

            <div className="w-[250px] space-y-3 p-3">
                <div>
                    <label className="mb-1 block text-[10px] text-gray-500">Evento</label>
                    <select
                        className="nodrag w-full rounded border border-gray-200 bg-white px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700"
                        value={eventType}
                        onMouseDown={(event) => event.stopPropagation()}
                        onChange={(event) => handleEventTypeChange(event.target.value as CrmTriggerEvent)}
                    >
                        <option value="lead_created">Lead criado/adicionado</option>
                        <option value="crm_stage_entered">Entrou em etapa</option>
                    </select>
                </div>

                <div>
                    <label className="mb-1 block text-[10px] text-gray-500">Funil</label>
                    <select
                        className="nodrag w-full rounded border border-gray-200 bg-white px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700"
                        value={pipelineId}
                        onMouseDown={(event) => event.stopPropagation()}
                        onChange={(event) => handlePipelineChange(event.target.value)}
                    >
                        <option value="">{loadingPipelines ? 'Carregando funis...' : 'Qualquer funil'}</option>
                        {pipelines.map((pipeline) => (
                            <option key={pipeline.id} value={pipeline.id}>
                                {pipeline.name}
                            </option>
                        ))}
                    </select>
                </div>

                <div>
                    <label className="mb-1 block text-[10px] text-gray-500">Etapa</label>
                    <select
                        className="nodrag w-full rounded border border-gray-200 bg-white px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700"
                        value={stageId}
                        disabled={eventType === 'lead_created' || !pipelineId || loadingStages}
                        onMouseDown={(event) => event.stopPropagation()}
                        onChange={(event) => handleStageChange(event.target.value)}
                    >
                        <option value="">
                            {eventType === 'lead_created'
                                ? 'Nao usado neste evento'
                                : loadingStages ? 'Carregando etapas...' : 'Qualquer etapa'}
                        </option>
                        {stages.map((stage) => (
                            <option key={stage.id} value={stage.id}>
                                {stage.name}
                            </option>
                        ))}
                    </select>
                </div>

                <div className={`rounded p-2 text-[10px] ${isDark ? 'bg-indigo-900/20 text-indigo-200' : 'bg-indigo-50 text-indigo-700'}`}>
                    Variáveis: {'{{trigger.lead.id}}'}, {'{{phone}}'}, {'{{name}}'}
                </div>
            </div>

            <Handle type="source" position={Position.Right} />
        </div>
    );
};

export default memo(CrmStageTriggerNode);
