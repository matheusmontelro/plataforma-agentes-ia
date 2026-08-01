import React, { memo, useCallback, useEffect, useMemo, useState } from 'react';
import { NodeProps, Position, useReactFlow } from 'reactflow';
import { AlertCircle, Check, Database, Filter, Loader2, Play, Plus, Tag, Trash2 } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import { getTags, type Tag as ContactTag } from '../../services/tagsApi.ts';
import { listarLeadCustomFields, type LeadCustomField } from '../../services/api.ts';
import { useFlowVariables } from '../../contexts/FlowVariablesContext.tsx';
import { useFlowConfirm } from './FlowConfirmContext.tsx';
import { NodeContextMenu } from './NodeContextMenu.tsx';
import {
    FlowNodeHandle,
    FlowNodeHeader,
    flowNodeLabelClass,
    flowNodePanelClass,
    flowNodeSelectClass,
    flowNodeShellClass,
} from './FlowNodeChrome.tsx';

type ConditionSource = 'tag' | 'custom_field';
type ConditionMatchMode = 'all' | 'any';
type ActionOnMatch = 'advance' | 'stop';

interface FilterCondition {
    customFieldId: string;
    fieldKey: string;
    fieldName: string;
    id: string;
    operator: string;
    source: ConditionSource;
    tagId: string;
    tagName: string;
    value: string;
}

const getCompanyId = () => Number.parseInt(
    (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'))
    || (sessionStorage.getItem('company_id') || sessionStorage.getItem('clinic_id'))
    || '0',
    10
);

const getClientId = () => Number.parseInt(
    localStorage.getItem('client_id')
    || sessionStorage.getItem('client_id')
    || '0',
    10
);

const createConditionId = () => `condition-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

const createDefaultCondition = (): FilterCondition => ({
    customFieldId: '',
    fieldKey: '',
    fieldName: '',
    id: createConditionId(),
    operator: 'has_tag',
    source: 'tag',
    tagId: '',
    tagName: '',
    value: '',
});

const normalizeSource = (source: unknown): ConditionSource =>
    String(source || 'tag').toLowerCase().includes('field') ? 'custom_field' : 'tag';

const normalizeMatchMode = (value: unknown): ConditionMatchMode =>
    String(value || 'all').toLowerCase() === 'any' ? 'any' : 'all';

const normalizeActionOnMatch = (value: unknown): ActionOnMatch =>
    String(value || 'advance').toLowerCase() === 'stop' ? 'stop' : 'advance';

const normalizeCondition = (condition: any): FilterCondition => {
    const source = normalizeSource(condition?.source || condition?.type || condition?.fieldType);

    return {
        customFieldId: String(condition?.customFieldId || condition?.custom_field_id || condition?.fieldId || ''),
        fieldKey: condition?.fieldKey || condition?.field_key || '',
        fieldName: condition?.fieldName || condition?.field_name || '',
        id: condition?.id || createConditionId(),
        operator: condition?.operator || (source === 'tag' ? 'has_tag' : 'equals'),
        source,
        tagId: String(condition?.tagId || condition?.tag_id || ''),
        tagName: condition?.tagName || condition?.tag_name || '',
        value: String(condition?.expectedValue ?? condition?.value ?? ''),
    };
};

const getInitialConditions = (data: any): FilterCondition[] => {
    if (Array.isArray(data.conditions) && data.conditions.length > 0) {
        return data.conditions.map(normalizeCondition);
    }

    if (data.tagId || data.tag_id) {
        return [
            normalizeCondition({
                source: 'tag',
                operator: data.filterMode || 'has_tag',
                tagId: data.tagId || data.tag_id,
                tagName: data.tagName || data.tag_name,
            }),
        ];
    }

    return [createDefaultCondition()];
};

const tagOperatorOptions = [
    { label: 'tem a tag', value: 'has_tag' },
    { label: 'não tem a tag', value: 'not_has_tag' },
];

const fieldOperatorOptions = [
    { label: 'é igual a', requiresValue: true, value: 'equals' },
    { label: 'é diferente de', requiresValue: true, value: 'not_equals' },
    { label: 'contém', requiresValue: true, value: 'contains' },
    { label: 'não contém', requiresValue: true, value: 'not_contains' },
    { label: 'está vazio', requiresValue: false, value: 'is_empty' },
    { label: 'está preenchido', requiresValue: false, value: 'is_not_empty' },
    { label: 'maior que', requiresValue: true, value: 'greater_than' },
    { label: 'menor que', requiresValue: true, value: 'less_than' },
    { label: 'maior ou igual a', requiresValue: true, value: 'greater_or_equal' },
    { label: 'menor ou igual a', requiresValue: true, value: 'less_or_equal' },
];

const fieldOperatorsWithoutValue = new Set(
    fieldOperatorOptions.filter((option) => !option.requiresValue).map((option) => option.value)
);

const toPayloadCondition = (condition: FilterCondition) => {
    if (condition.source === 'tag') {
        return {
            id: condition.id,
            source: 'tag',
            operator: condition.operator || 'has_tag',
            tagId: condition.tagId ? Number(condition.tagId) : '',
            tagName: condition.tagName || '',
        };
    }

    return {
        id: condition.id,
        source: 'custom_field',
        operator: condition.operator || 'equals',
        customFieldId: condition.customFieldId ? Number(condition.customFieldId) : '',
        fieldKey: condition.fieldKey || '',
        fieldName: condition.fieldName || '',
        value: condition.value || '',
    };
};

const cx = (...classes: Array<string | false | null | undefined>) => classes.filter(Boolean).join(' ');

const TagFilterNode = ({ data, id, selected, isConnectable }: NodeProps) => {
    const { isDark } = useTheme();
    const { deleteElements, setNodes } = useReactFlow();
    const { setNodeExecutionData, setIsFlowRunning } = useFlowVariables();
    const { confirm, notice } = useFlowConfirm();

    const [tags, setTags] = useState<ContactTag[]>([]);
    const [customFields, setCustomFields] = useState<LeadCustomField[]>([]);
    const [conditions, setConditions] = useState<FilterCondition[]>(() => getInitialConditions(data));
    const [conditionMatch, setConditionMatch] = useState<ConditionMatchMode>(
        normalizeMatchMode(data.conditionMatch || data.matchMode)
    );
    const [actionOnMatch, setActionOnMatch] = useState<ActionOnMatch>(
        normalizeActionOnMatch(data.actionOnMatch || data.matchAction)
    );
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [executionResult, setExecutionResult] = useState<{ success: boolean; message: string } | null>(null);
    const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null);

    const inputClass = cx(
        'nodrag w-full rounded-xl border px-3 py-2 text-sm outline-none transition focus:ring-2 focus:ring-brand/20',
        isDark ? 'border-white/10 bg-white/[0.06] text-white placeholder:text-white/30' : 'border-brand/10 bg-brand-canvas text-brand placeholder:text-brand/35'
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
        const loadFilterOptions = async () => {
            const companyId = getCompanyId();
            const clientId = getClientId();
            if (!companyId) {
                setLoadError('Empresa ativa não encontrada.');
                setLoading(false);
                return;
            }

            try {
                setLoading(true);
                setLoadError(null);
                const [tagData, fieldData] = await Promise.all([
                    getTags(companyId),
                    clientId ? listarLeadCustomFields(clientId, companyId, true, '') : Promise.resolve([]),
                ]);
                setTags(Array.isArray(tagData) ? tagData : []);
                setCustomFields(Array.isArray(fieldData) ? fieldData.sort((a, b) => a.display_order - b.display_order) : []);
            } catch (error: any) {
                setLoadError(error?.response?.data?.detail || 'Erro ao carregar opções do filtro.');
            } finally {
                setLoading(false);
            }
        };

        loadFilterOptions();
    }, []);

    const persistedConditions = useMemo(
        () => conditions.map(toPayloadCondition),
        [conditions]
    );

    useEffect(() => {
        const firstTagCondition = conditions.find((condition) => condition.source === 'tag');
        const legacyTagId = firstTagCondition?.tagId ? Number(firstTagCondition.tagId) : '';
        const nextPayload = {
            actionOnMatch,
            conditionMatch,
            conditions: persistedConditions,
            filterMode: firstTagCondition?.operator || 'has_tag',
            tagId: legacyTagId,
            tagName: firstTagCondition?.tagName || '',
        };

        const hasChanged =
            JSON.stringify(data.conditions || []) !== JSON.stringify(persistedConditions) ||
            data.conditionMatch !== conditionMatch ||
            data.actionOnMatch !== actionOnMatch ||
            data.tagId !== legacyTagId ||
            data.filterMode !== nextPayload.filterMode ||
            data.tagName !== nextPayload.tagName;

        if (hasChanged) {
            updateNodeData(nextPayload);
        }
    }, [
        actionOnMatch,
        conditionMatch,
        conditions,
        data.actionOnMatch,
        data.conditionMatch,
        data.conditions,
        data.filterMode,
        data.tagId,
        data.tagName,
        persistedConditions,
        updateNodeData,
    ]);

    const updateCondition = (conditionId: string, updates: Partial<FilterCondition>) => {
        setConditions((current) =>
            current.map((condition) =>
                condition.id === conditionId
                    ? { ...condition, ...updates }
                    : condition
            )
        );
    };

    const removeCondition = async (conditionId: string) => {
        if (conditions.length === 1) {
            await notice({
                title: 'Condição obrigatória',
                message: 'Mantenha pelo menos uma condição no filtro.',
            });
            return;
        }
        setConditions((current) => current.filter((condition) => condition.id !== conditionId));
    };

    const addCondition = () => {
        setConditions((current) => [...current, createDefaultCondition()]);
    };

    const getIncompleteCondition = () => conditions.find((condition) => {
        if (condition.source === 'tag') {
            return !condition.tagId;
        }

        if (!condition.customFieldId) {
            return true;
        }

        return !fieldOperatorsWithoutValue.has(condition.operator) && !condition.value.trim();
    });

    const handleRunOnce = async (executeChain = false) => {
        const incompleteCondition = getIncompleteCondition();
        if (incompleteCondition) {
            await notice({
                title: 'Filtro incompleto',
                message: 'Revise as condições antes de simular este filtro.',
            });
            if (executeChain) setIsFlowRunning(false);
            return;
        }

        const stopBranch = actionOnMatch === 'stop';
        const result = {
            success: true,
            matched: true,
            condition_met: true,
            stop_branch: stopBranch,
            simulated: true,
            match_mode: conditionMatch,
            action_on_match: actionOnMatch,
            conditions: persistedConditions,
        };

        setExecutionResult({
            success: !stopBranch,
            message: stopBranch ? 'Filtro simulado como bloqueado.' : 'Filtro simulado como aprovado.',
        });

        setNodeExecutionData(id, result, executeChain && !stopBranch, true);
        if (executeChain && stopBranch) {
            setIsFlowRunning(false);
        }
    };

    const lastRunRef = React.useRef<number>(data.triggerRunOnce || 0);
    useEffect(() => {
        if (data.triggerRunOnce && data.triggerRunOnce !== lastRunRef.current) {
            lastRunRef.current = data.triggerRunOnce;
            handleRunOnce(true);
        }
    }, [data.triggerRunOnce, actionOnMatch, conditionMatch, persistedConditions]);

    return (
        <div
            onContextMenu={(event) => {
                event.preventDefault();
                event.stopPropagation();
                setMenuPosition({ x: event.clientX, y: event.clientY });
            }}
            className={flowNodeShellClass(isDark, Boolean(selected), 'indigo', 'min-w-[360px] max-w-[360px]')}
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
                                    message: 'Este filtro e suas conexões serão removidos do fluxo.',
                                    title: 'Excluir filtro condicional?',
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

            <FlowNodeHeader icon={Filter} title="Filtro condicional" subtitle="Filtro" tone="indigo" />

            {executionResult && (
                <div className={`flex items-center gap-2 border-b px-4 py-2 text-xs ${
                    executionResult.success
                        ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-500'
                        : 'border-amber-500/20 bg-amber-500/10 text-amber-600'
                }`}>
                    {executionResult.success ? <Check className="h-3 w-3" /> : <AlertCircle className="h-3 w-3" />}
                    <span className="truncate">{executionResult.message}</span>
                </div>
            )}

            <div className="space-y-4 p-4">
                {loading ? (
                    <div className={`flex items-center gap-2 rounded-xl border p-3 text-xs ${isDark ? 'border-white/10 bg-white/[0.04] text-white/60' : 'border-brand/10 bg-brand-canvas text-brand/60'}`}>
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Carregando opções...
                    </div>
                ) : loadError ? (
                    <div className={flowNodePanelClass(isDark, 'amber')}>
                        <div className="flex items-start gap-2 text-xs">
                            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                            <span>{loadError}</span>
                        </div>
                    </div>
                ) : null}

                <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-2">
                        <label className={flowNodeLabelClass(isDark)}>Combinação</label>
                        <select
                            value={conditionMatch}
                            onMouseDown={(event) => event.stopPropagation()}
                            onChange={(event) => setConditionMatch(event.target.value as ConditionMatchMode)}
                            className={flowNodeSelectClass(isDark)}
                        >
                            <option value="all">Todas</option>
                            <option value="any">Qualquer</option>
                        </select>
                    </div>

                    <div className="space-y-2">
                        <label className={flowNodeLabelClass(isDark)}>Ao bater</label>
                        <select
                            value={actionOnMatch}
                            onMouseDown={(event) => event.stopPropagation()}
                            onChange={(event) => setActionOnMatch(event.target.value as ActionOnMatch)}
                            className={flowNodeSelectClass(isDark)}
                        >
                            <option value="advance">Avançar</option>
                            <option value="stop">Não avançar</option>
                        </select>
                    </div>
                </div>

                <div className="space-y-3">
                    {conditions.map((condition, index) => {
                        const selectedTag = tags.find((tag) => String(tag.id) === String(condition.tagId));
                        const selectedField = customFields.find((field) => String(field.id) === String(condition.customFieldId));
                        const fieldOperator = fieldOperatorOptions.find((option) => option.value === condition.operator) || fieldOperatorOptions[0];
                        const operators = condition.source === 'tag' ? tagOperatorOptions : fieldOperatorOptions;

                        return (
                            <div key={condition.id} className={flowNodePanelClass(isDark)}>
                                <div className="mb-3 flex items-center justify-between gap-3">
                                    <div className="flex items-center gap-2">
                                        <span className={`grid h-7 w-7 place-items-center rounded-lg ${condition.source === 'tag' ? 'bg-emerald-500/10 text-emerald-600' : 'bg-sky-500/10 text-sky-600'}`}>
                                            {condition.source === 'tag' ? <Tag className="h-3.5 w-3.5" /> : <Database className="h-3.5 w-3.5" />}
                                        </span>
                                        <span className="text-xs font-semibold">Condição {index + 1}</span>
                                    </div>
                                    <button
                                        type="button"
                                        onMouseDown={(event) => event.stopPropagation()}
                                        onClick={() => removeCondition(condition.id)}
                                        className={`nodrag grid h-7 w-7 place-items-center rounded-lg transition ${
                                            conditions.length === 1
                                                ? isDark ? 'text-white/25' : 'text-brand/25'
                                                : 'text-red-500 hover:bg-red-500/10'
                                        }`}
                                        aria-label="Remover condição"
                                        title="Remover condição"
                                    >
                                        <Trash2 className="h-3.5 w-3.5" />
                                    </button>
                                </div>

                                <div className="space-y-3">
                                    <div className="grid grid-cols-[1fr_1.1fr] gap-2">
                                        <div className="space-y-2">
                                            <label className={flowNodeLabelClass(isDark)}>Origem</label>
                                            <select
                                                value={condition.source}
                                                onMouseDown={(event) => event.stopPropagation()}
                                                onChange={(event) => {
                                                    const source = event.target.value as ConditionSource;
                                                    updateCondition(condition.id, {
                                                        customFieldId: '',
                                                        fieldKey: '',
                                                        fieldName: '',
                                                        operator: source === 'tag' ? 'has_tag' : 'equals',
                                                        source,
                                                        tagId: '',
                                                        tagName: '',
                                                        value: '',
                                                    });
                                                }}
                                                className={flowNodeSelectClass(isDark)}
                                            >
                                                <option value="tag">Tag</option>
                                                <option value="custom_field">Campo</option>
                                            </select>
                                        </div>

                                        <div className="space-y-2">
                                            <label className={flowNodeLabelClass(isDark)}>Condição</label>
                                            <select
                                                value={condition.operator}
                                                onMouseDown={(event) => event.stopPropagation()}
                                                onChange={(event) => updateCondition(condition.id, { operator: event.target.value })}
                                                className={flowNodeSelectClass(isDark)}
                                            >
                                                {operators.map((option) => (
                                                    <option key={option.value} value={option.value}>
                                                        {option.label}
                                                    </option>
                                                ))}
                                            </select>
                                        </div>
                                    </div>

                                    {condition.source === 'tag' ? (
                                        <div className="space-y-2">
                                            <label className={flowNodeLabelClass(isDark)}>Tag</label>
                                            <select
                                                value={condition.tagId}
                                                onMouseDown={(event) => event.stopPropagation()}
                                                onChange={(event) => {
                                                    const nextTag = tags.find((tag) => String(tag.id) === event.target.value);
                                                    updateCondition(condition.id, {
                                                        tagId: event.target.value,
                                                        tagName: nextTag?.name || '',
                                                    });
                                                }}
                                                className={flowNodeSelectClass(isDark)}
                                            >
                                                <option value="">Selecione uma tag</option>
                                                {tags.map((tag) => (
                                                    <option key={tag.id} value={tag.id}>
                                                        {tag.name}{tag.category_name ? ` · ${tag.category_name}` : ''}
                                                    </option>
                                                ))}
                                            </select>
                                        </div>
                                    ) : (
                                        <div className="space-y-3">
                                            <div className="space-y-2">
                                                <label className={flowNodeLabelClass(isDark)}>Campo</label>
                                                <select
                                                    value={condition.customFieldId}
                                                    onMouseDown={(event) => event.stopPropagation()}
                                                    onChange={(event) => {
                                                        const nextField = customFields.find((field) => String(field.id) === event.target.value);
                                                        updateCondition(condition.id, {
                                                            customFieldId: event.target.value,
                                                            fieldKey: nextField?.field_key || '',
                                                            fieldName: nextField?.field_name || '',
                                                        });
                                                    }}
                                                    className={flowNodeSelectClass(isDark)}
                                                >
                                                    <option value="">Selecione um campo</option>
                                                    {customFields.map((field) => (
                                                        <option key={field.id} value={field.id}>
                                                            {field.field_name}
                                                        </option>
                                                    ))}
                                                </select>
                                            </div>

                                            {!fieldOperatorsWithoutValue.has(fieldOperator.value) && (
                                                <div className="space-y-2">
                                                    <label className={flowNodeLabelClass(isDark)}>Valor</label>
                                                    <input
                                                        value={condition.value}
                                                        onMouseDown={(event) => event.stopPropagation()}
                                                        onChange={(event) => updateCondition(condition.id, { value: event.target.value })}
                                                        className={inputClass}
                                                        placeholder="Valor ou {{variável}}"
                                                    />
                                                </div>
                                            )}
                                        </div>
                                    )}

                                    {(selectedTag || selectedField) && (
                                        <div className={`rounded-xl border px-3 py-2 text-xs ${isDark ? 'border-white/10 bg-white/[0.04] text-white/55' : 'border-brand/10 bg-white text-brand/55'}`}>
                                            {selectedTag ? (
                                                <div className="flex items-center gap-2">
                                                    <span
                                                        className="h-2.5 w-2.5 shrink-0 rounded-full border border-white/40"
                                                        style={{ backgroundColor: selectedTag.color || '#020323' }}
                                                    />
                                                    <span className="truncate">{selectedTag.name}</span>
                                                </div>
                                            ) : (
                                                <span className="truncate">
                                                    {selectedField?.field_name} · {selectedField?.field_type}
                                                </span>
                                            )}
                                        </div>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>

                <button
                    type="button"
                    onMouseDown={(event) => event.stopPropagation()}
                    onClick={addCondition}
                    className={`nodrag flex min-h-10 w-full items-center justify-center gap-2 rounded-xl border text-sm font-semibold transition ${
                        isDark
                            ? 'border-white/10 bg-white/[0.04] text-white hover:bg-white/[0.08]'
                            : 'border-brand/10 bg-brand-canvas text-brand hover:bg-brand/5'
                    }`}
                >
                    <Plus className="h-4 w-4" />
                    Adicionar condição
                </button>
            </div>

            <FlowNodeHandle type="target" position={Position.Left} tone="indigo" isConnectable={isConnectable} />
            <FlowNodeHandle type="source" position={Position.Right} tone="indigo" isConnectable={isConnectable} />
        </div>
    );
};

export default memo(TagFilterNode);
