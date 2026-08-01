import React, { memo, useEffect, useState } from 'react';
import { Position, NodeProps, useReactFlow } from 'reactflow';
import { UserPlus, ChevronDown, Loader2, Trash2, Sliders } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import { pipelineApi } from '../../services/crmApi.ts';
import { NodeContextMenu } from './NodeContextMenu.tsx';
import { VariableInput } from './VariableInput.tsx'; // Import VariableInput
import {
    listarLeadCustomFields,
    type LeadCustomField
} from '../../services/api';
import { crmApi } from '../../services/crmApi.ts'; // Import crmApi
import { useFlowVariables } from '../../contexts/FlowVariablesContext.tsx';
import { interpolateVariables } from '../../utils/variableUtils.ts';
import { Play, Check, AlertCircle } from 'lucide-react';
import { useFlowConfirm } from './FlowConfirmContext.tsx';
import {
    FlowNodeHandle,
    FlowNodeHeader,
    flowNodeLabelClass,
    flowNodeSelectClass,
    flowNodeShellClass,
} from './FlowNodeChrome.tsx';

interface Pipeline {
    id: number;
    name: string;
}

interface Stage {
    id: number;
    name: string;
    pipeline_id: number;
}

const CreateLeadNode = ({ data, id, selected }: NodeProps) => {
    const { isDark } = useTheme();
    const { deleteElements } = useReactFlow();
    const { confirm, notice } = useFlowConfirm();

    // State
    const [pipelines, setPipelines] = useState<Pipeline[]>([]);
    const [stages, setStages] = useState<Stage[]>([]);
    const [customFields, setCustomFields] = useState<LeadCustomField[]>([]);

    const [loadingPipelines, setLoadingPipelines] = useState(false);
    const [loadingStages, setLoadingStages] = useState(false);
    const [loadingFields, setLoadingFields] = useState(false);

    // Execution State
    const { executionData, setNodeExecutionData } = useFlowVariables();
    const [executing, setExecuting] = useState(false);
    const [executionResult, setExecutionResult] = useState<{ success: boolean, message?: string } | null>(null);

    // Form State (stored in data)
    const [name, setName] = useState(data.name || '');
    const [phone, setPhone] = useState(data.phone || '');
    const [sourceId, setSourceId] = useState(data.sourceId || '');
    const [dataEntrada, setDataEntrada] = useState(data.dataEntrada || '');

    const [selectedPipelineId, setSelectedPipelineId] = useState<string>(data.pipelineId || '');
    const [selectedStageId, setSelectedStageId] = useState<string>(data.stageId || '');

    // Custom Values (map field_key -> value)
    const [customValues, setCustomValues] = useState<Record<string, string>>(data.customValues || {});

    // Context Menu State
    const [menuPosition, setMenuPosition] = useState<{ x: number, y: number } | null>(null);


    // Listen for external trigger (Chain Execution)
    // Track last processed trigger timestamp to avoid loops. Init with current to ignore mount trigger.
    const lastRunRef = React.useRef<number>(data.triggerRunOnce || 0);


    // Listen for external trigger (Chain Execution)
    useEffect(() => {
        if (data.triggerRunOnce && data.triggerRunOnce !== lastRunRef.current && executing !== true) {
            console.log("External trigger received for CreateLeadNode:", id);
            lastRunRef.current = data.triggerRunOnce; // Mark as processed
            handleRunOnce(true);
        }
    }, [data.triggerRunOnce, executing]);



    // Initial Data Fetch
    useEffect(() => {
        const loadData = async () => {
            setLoadingPipelines(true);
            setLoadingFields(true);
            try {
                // Fetch Pipelines
                const pipes = await pipelineApi.getPipelines();
                setPipelines(pipes);

                // Fetch Custom Fields
                const clientId = parseInt(localStorage.getItem('client_id') || sessionStorage.getItem('client_id') || '0', 10);
                const companyId = parseInt((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')) || (sessionStorage.getItem('company_id') || sessionStorage.getItem('clinic_id')) || '0', 10);
                const apiKey = '';

                if (!clientId || !companyId) {
                    throw new Error('Sessão incompleta para carregar campos customizados (client_id/company_id).');
                }

                const fields = await listarLeadCustomFields(clientId, companyId, true, apiKey);
                const sortedFields = fields.sort((a, b) => a.display_order - b.display_order);
                setCustomFields(sortedFields);

                // If existing pipeline, load stages
                if (data.pipelineId) {
                    loadStages(data.pipelineId);
                }
            } catch (error) {
                console.error("Failed to load node data", error);
            } finally {
                setLoadingPipelines(false);
                setLoadingFields(false);
            }
        };
        loadData();
    }, []);

    const loadStages = async (pipelineId: number | string) => {
        setLoadingStages(true);
        try {
            const fetchedStages = await pipelineApi.getStages(Number(pipelineId));

            // Inject "Novo Lead" stage (ID 0) as the first option
            const virtualStage: Stage = { id: 0, name: 'Novo Lead', pipeline_id: Number(pipelineId) };
            const allStages = [virtualStage, ...fetchedStages];

            console.log("Fetched Stages + Virtual for Pipeline", pipelineId, allStages);
            setStages(allStages);
        } catch (error) {
            console.error("Failed to load stages", error);
            setStages([]);
        } finally {
            setLoadingStages(false);
        }
    };

    // Effect to auto-select first stage if none selected (Fix for Default Stage issue)
    useEffect(() => {
        if (stages.length > 0 && !selectedStageId) {
            // If there's a "Novo Lead" or similar, prefer it, otherwise pick first
            const defaultStage = stages.find(s => s.name.includes("Novo") || s.name.includes("New")) || stages[0];
            if (defaultStage) {
                setSelectedStageId(defaultStage.id.toString());
                data.stageId = defaultStage.id.toString();
            }
        }
    }, [stages, selectedStageId]);

    // Handlers
    const handlePipelineChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
        const val = e.target.value;
        setSelectedPipelineId(val);
        data.pipelineId = val;
        setSelectedStageId('');
        data.stageId = '';
        if (val) loadStages(val);
    };

    const handleStageChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
        const val = e.target.value;
        setSelectedStageId(val);
        data.stageId = val;
    };

    const handleNameChange = (val: string) => {
        setName(val);
        data.name = val;
    };

    const handlePhoneChange = (val: string) => {
        setPhone(val);
        data.phone = val;
    };

    const handleSourceChange = (val: string) => {
        setSourceId(val);
        data.sourceId = val;
    };

    const handleDataEntradaChange = (val: string) => {
        setDataEntrada(val);
        data.dataEntrada = val;
    };

    // Custom Field Handler
    const handleCustomFieldChange = (fieldKey: string, value: string) => {
        const newValues = { ...customValues, [fieldKey]: value };
        setCustomValues(newValues);
        data.customValues = newValues;
    };

    const handleContextMenu = (e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setMenuPosition({ x: e.clientX, y: e.clientY });
    };



    const handleRunOnce = async (executeChain = false) => {
        console.log("Run Once Inputs:", { name, selectedPipelineId, selectedStageId });


        // Validate required fields (Note: "0" is truthy string, so it passes)
        if (!name || !selectedPipelineId || selectedStageId === '') {
            console.error("Validation failed:", { name, selectedPipelineId, selectedStageId });
            await notice({
                title: 'Campos obrigatórios',
                message: `Revise: nome ${name ? 'OK' : 'vazio'}, pipeline ${selectedPipelineId ? 'OK' : 'vazio'}, etapa ${selectedStageId !== '' ? 'OK' : 'vazia'}.`,
            });
            return;
        }

        setExecuting(true);
        setExecutionResult(null);

        try {
            // Interpolate variables
            const rawPhone = interpolateVariables(phone, executionData);
            const sanitizedPhone = rawPhone.replace(/\D/g, ''); // Remove all non-digits

            const leadData: any = {
                company_id: parseInt((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')) || '0'),
                name: interpolateVariables(name, executionData),
                phone: sanitizedPhone,

                pipeline_id: parseInt(selectedPipelineId),
                current_stage_id: parseInt(selectedStageId) > 0 ? parseInt(selectedStageId) : undefined, // Ensure valid stage ID
                source_id: sourceId ? interpolateVariables(sourceId, executionData) : undefined,

                data_entrada: dataEntrada ? interpolateVariables(dataEntrada, executionData) : undefined,
                custom_values: []
            };

            // Interpolate and format custom values
            // Backend expects: custom_values: [{ custom_field_id: 1, value: "..." }, ...]
            const formattedCustomValues = Object.entries(customValues).map(([key, val]) => {
                // Find field definition to get ID
                const fieldDef = customFields.find(f => f.field_key === key);
                if (!fieldDef) return null;

                return {
                    custom_field_id: fieldDef.id,
                    value: interpolateVariables(val, executionData)
                };
            }).filter(Boolean);

            leadData.custom_values = formattedCustomValues;

            // Custom Fields Resolution
            // We need to map customValues keys (field_key) to backend format if needed.
            // Usually crmApi.createLead expects `custom_fields` object or similar depending on implementation.
            // Checking crmApi.createLead type: passed 'Lead' partial.
            // The Lead interface doesn't explicitly show 'custom_fields' property in the snippet I saw earlier,
            // checking models.py would be ideal but for now let's assume standard REST API behavior or check api service.
            // However, looking at previous artifacts/context, Lead usually has custom fields.
            // Let's assume we pass them mixed in or separate.
            // Wait, looking at CreateLeadNode custom values state: `customValues` is Record<string, string>.
            // I should verify how custom fields are sent to Create Lead API.
            // In the absence of strict type defs for custom fields in `Lead` interface in `crmApi.ts` snippet,
            // I'll assume they are passed as regular properties or under a `custom_fields` key.
            // Let's try passing them at root level for now as Python typically handles kwargs or specific keys.
            // Actually, safest bet is to check how standard Lead Form does it.
            // But for this task, I'll interpolate them and pass them.



            console.log("Creating Lead with Data:", leadData);

            const result = await crmApi.createLead(leadData);

            setNodeExecutionData(id, result, executeChain); // Signal node completion; only trigger nodes publish variables
            setExecutionResult({ success: true, message: `Lead criado: ID ${result.id}` });

            // setNodeExecutionData(id, result); // Removed redundant call


        } catch (error: any) {
            console.error("Run Once Error", error);

            // Extract detailed error message from backend
            let errorMessage = "Erro ao criar lead";
            if (error.response?.data?.detail) {
                errorMessage = error.response.data.detail;
            } else if (error.message) {
                errorMessage = error.message;
            }

            setExecutionResult({ success: false, message: errorMessage });
        } finally {
            setExecuting(false);
        }
    };

    const handleDelete = async () => {
        const confirmed = await confirm({
            confirmText: 'Excluir node',
            message: 'Este node e suas conexões serão removidos do fluxo.',
            title: 'Excluir ação de CRM?',
            variant: 'danger',
        });
        if (confirmed) {
            deleteElements({ nodes: [{ id }] });
        }
    };

    const renderCustomFieldInput = (field: LeadCustomField) => {
        const value = customValues[field.field_key] || '';
        return (
            <div key={field.id} className="mb-2">
                <VariableInput
                    label={`${field.field_name} ${field.is_required ? '*' : ''}`}
                    value={value}
                    onChange={(val) => handleCustomFieldChange(field.field_key, val)}
                    placeholder={field.field_type === 'date' ? 'YYYY-MM-DD ou {{var}}' : 'Valor ou {{var}}'}
                    list={field.field_type === 'select' ? `options-${field.id}` : undefined}
                />
            </div>
        );
    };

    return (
        <div
            onContextMenu={handleContextMenu}
            className={flowNodeShellClass(isDark, selected, 'blue')}>

            {/* Context Menu */}
            {menuPosition && (
                <NodeContextMenu
                    x={menuPosition.x}
                    y={menuPosition.y}
                    onClose={() => setMenuPosition(null)}
                    actions={[
                        { label: 'Excluir', icon: <Trash2 className="w-3 h-3" />, onClick: handleDelete, danger: true },

                        { label: 'Run Once (Testar Node)', icon: <Play className="w-3 h-3" />, onClick: () => handleRunOnce(false) }
                    ]}

                />
            )}

            <FlowNodeHeader icon={UserPlus} title="Criar Lead CRM" subtitle="CRM" tone="blue" />

            {/* Execution Result Status */}
            {executing && (
                <div className="px-4 py-2 bg-yellow-500/10 text-yellow-500 text-xs flex items-center gap-2 animate-pulse border-b border-yellow-500/20">
                    <Loader2 className="w-3 h-3 animate-spin" /> Executando...
                </div>
            )}
            {executionResult && !executing && (
                <div className={`px-4 py-2 text-xs flex items-center gap-2 border-b ${executionResult.success ? 'bg-green-500/10 text-green-500 border-green-500/20' : 'bg-red-500/10 text-red-500 border-red-500/20'}`}>
                    {executionResult.success ? <Check className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
                    <span className="truncate">{executionResult.message}</span>
                </div>
            )}

            {/* Body */}
            <div
                className="p-4 space-y-4 max-h-[400px] overflow-y-auto custom-scrollbar nowheel"
                onWheel={(e) => e.stopPropagation()}
            >

                {/* Standard Inputs */}
                <div className="space-y-3">
                    <VariableInput
                        label="Nome do Lead"
                        value={name}
                        onChange={handleNameChange}
                        placeholder="{{trigger.name}} ou Nome Fixo"
                    />

                    <VariableInput
                        label="Telefone"
                        value={phone}
                        onChange={handlePhoneChange}
                        placeholder="{{trigger.phone}} ou 5511999..."
                    />

                    <div className="grid grid-cols-2 gap-2">
                        <VariableInput
                            label="Mídia (Source)"
                            value={sourceId}
                            onChange={handleSourceChange}
                            placeholder="Selecione ou {{var}}"
                            list="source-options"
                        />
                        <datalist id="source-options">
                            <option value="Facebook" />
                            <option value="Instagram" />
                            <option value="Google" />
                            <option value="Indicação" />
                            <option value="Site" />
                            <option value="Orgânico" />
                        </datalist>

                        <VariableInput
                            label="Data Entrada"
                            value={dataEntrada}
                            onChange={handleDataEntradaChange}
                            placeholder="{{now}} ou YYYY-MM-DDTHH:mm"
                            list="date-options"
                        />
                        <datalist id="date-options">
                            <option value="{{now}}">Data/Hora Atual (América/SP)</option>
                        </datalist>
                    </div>
                </div>

                <div className={`my-2 h-px ${isDark ? 'bg-white/10' : 'bg-brand/10'}`} />

                {/* Pipeline Configuration */}
                <div className="space-y-3">
                    <div>
                        <label className={flowNodeLabelClass(isDark)}>
                            Pipeline
                        </label>
                        {loadingPipelines ? (
                            <div className="flex items-center gap-2 text-xs text-gray-500 py-2">
                                <Loader2 className="w-3 h-3 animate-spin" /> Carregando...
                            </div>
                        ) : (
                            <div className="relative">
                                <select
                                    value={selectedPipelineId}
                                    onChange={handlePipelineChange}
                                    onMouseDown={(e) => e.stopPropagation()}
                                    className={flowNodeSelectClass(isDark)}
                                >
                                    <option value="">Selecione Pipeline...</option>
                                    {pipelines.map(pipe => (
                                        <option key={pipe.id} value={pipe.id}>{pipe.name}</option>
                                    ))}
                                </select>
                                <ChevronDown className={`absolute right-3 top-1/2 -translate-y-1/2 w-3 h-3 pointer-events-none ${isDark ? 'text-gray-400' : 'text-gray-500'}`} />
                            </div>
                        )}
                    </div>

                    <div>
                        <label className={flowNodeLabelClass(isDark)}>
                            Etapa (Stage)
                        </label>
                        {loadingStages ? (
                            <div className="flex items-center gap-2 text-xs text-gray-500 py-2">
                                <Loader2 className="w-3 h-3 animate-spin" /> Carregando...
                            </div>
                        ) : (
                            <div className="relative">
                                <select
                                    value={selectedStageId}
                                    onChange={handleStageChange}
                                    disabled={!selectedPipelineId}
                                    onMouseDown={(e) => e.stopPropagation()}
                                    className={`${flowNodeSelectClass(isDark)} disabled:opacity-50`}
                                >
                                    {/* Add Default Option */}
                                    <option value="">Selecione a Etapa...</option>
                                    {stages.length === 0 && <option disabled>Nenhuma etapa encontrada</option>}
                                    {stages.map(stage => (
                                        <option key={stage.id} value={stage.id}>{stage.name} (ID: {stage.id})</option>
                                    ))}
                                </select>
                                <ChevronDown className={`absolute right-3 top-1/2 -translate-y-1/2 w-3 h-3 pointer-events-none ${isDark ? 'text-gray-400' : 'text-gray-500'}`} />
                            </div>
                        )}
                    </div>
                </div>

                {/* Custom Fields Section */}
                {customFields.length > 0 && (
                    <>
                        <div className={`my-2 h-px ${isDark ? 'bg-white/10' : 'bg-brand/10'}`} />

                        <div className="space-y-3">
                            <div className="flex items-center gap-2 mb-2">
                                <Sliders className="w-3 h-3 text-blue-500" />
                                <h4 className={flowNodeLabelClass(isDark)}>
                                    Atributos Personalizados
                                </h4>
                            </div>

                            {loadingFields ? (
                                <div className="flex items-center gap-2 text-xs text-gray-500 py-2">
                                    <Loader2 className="w-3 h-3 animate-spin" /> Carregando campos...
                                </div>
                            ) : (
                                customFields.map(renderCustomFieldInput)
                            )}
                        </div>
                    </>
                )}

            </div>

            {/* Handle Input */}
            <FlowNodeHandle type="target" position={Position.Left} tone="blue" />
            {/* Handle Output */}
            <FlowNodeHandle type="source" position={Position.Right} tone="blue" />
        </div>
    );
};

export default memo(CreateLeadNode);
