import React, { memo, useCallback, useEffect, useMemo, useState } from 'react';
import { NodeProps, Position, useReactFlow } from 'reactflow';
import { AlertCircle, Check, Loader2, Play, Tag, Trash2 } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import { getTags, type Tag as ContactTag } from '../../services/tagsApi.ts';
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

const getCompanyId = () => Number.parseInt(
    (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'))
    || (sessionStorage.getItem('company_id') || sessionStorage.getItem('clinic_id'))
    || '0',
    10
);

const AddTagNode = ({ data, id, selected, isConnectable }: NodeProps) => {
    const { isDark } = useTheme();
    const { deleteElements, setNodes } = useReactFlow();
    const { setNodeExecutionData, setIsFlowRunning } = useFlowVariables();
    const { confirm, notice } = useFlowConfirm();

    const [tags, setTags] = useState<ContactTag[]>([]);
    const [tagId, setTagId] = useState(data.tagId ? String(data.tagId) : '');
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [executionResult, setExecutionResult] = useState<{ success: boolean; message: string } | null>(null);
    const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null);

    const selectedTag = useMemo(
        () => tags.find((tag) => String(tag.id) === tagId) || null,
        [tagId, tags]
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
        const loadTags = async () => {
            const companyId = getCompanyId();
            if (!companyId) {
                setLoadError('Empresa ativa não encontrada.');
                setLoading(false);
                return;
            }

            try {
                setLoading(true);
                setLoadError(null);
                const tagData = await getTags(companyId);
                setTags(Array.isArray(tagData) ? tagData : []);
            } catch (error: any) {
                setLoadError(error?.response?.data?.detail || 'Erro ao carregar tags.');
            } finally {
                setLoading(false);
            }
        };

        loadTags();
    }, []);

    useEffect(() => {
        const nextTagId = tagId ? Number(tagId) : '';
        if (data.tagId !== nextTagId) {
            updateNodeData({
                tagId: nextTagId,
                tagName: selectedTag?.name || '',
            });
        }
    }, [data.tagId, selectedTag?.name, tagId, updateNodeData]);

    const handleRunOnce = async (executeChain = false) => {
        if (!tagId) {
            await notice({
                title: 'Tag ausente',
                message: 'Selecione uma tag antes de simular este node.',
            });
            if (executeChain) setIsFlowRunning(false);
            return;
        }

        setExecutionResult({
            success: true,
            message: selectedTag ? `Tag "${selectedTag.name}" marcada para aplicação.` : 'Tag marcada para aplicação.',
        });
        setNodeExecutionData(id, {
            success: true,
            simulated: true,
            tag_id: Number(tagId),
            tag_name: selectedTag?.name || '',
        }, executeChain, true);
    };

    const lastRunRef = React.useRef<number>(data.triggerRunOnce || 0);
    useEffect(() => {
        if (data.triggerRunOnce && data.triggerRunOnce !== lastRunRef.current) {
            lastRunRef.current = data.triggerRunOnce;
            handleRunOnce(true);
        }
    }, [data.triggerRunOnce, tagId, selectedTag]);

    return (
        <div
            onContextMenu={(event) => {
                event.preventDefault();
                event.stopPropagation();
                setMenuPosition({ x: event.clientX, y: event.clientY });
            }}
            className={flowNodeShellClass(isDark, Boolean(selected), 'emerald')}
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
                                    title: 'Excluir ação de tag?',
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

            <FlowNodeHeader icon={Tag} title="Adicionar tag" subtitle="CRM" tone="emerald" />

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

            <div className="space-y-4 p-4">
                {loading ? (
                    <div className={`flex items-center gap-2 rounded-xl border p-3 text-xs ${isDark ? 'border-white/10 bg-white/[0.04] text-white/60' : 'border-brand/10 bg-brand-canvas text-brand/60'}`}>
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Carregando tags...
                    </div>
                ) : loadError ? (
                    <div className={flowNodePanelClass(isDark, 'amber')}>
                        <div className="flex items-start gap-2 text-xs">
                            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                            <span>{loadError}</span>
                        </div>
                    </div>
                ) : (
                    <div className="space-y-2">
                        <label className={flowNodeLabelClass(isDark)}>Tag</label>
                        <select
                            value={tagId}
                            onMouseDown={(event) => event.stopPropagation()}
                            onChange={(event) => setTagId(event.target.value)}
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
                )}

                {selectedTag && (
                    <div className={`rounded-xl border p-3 ${isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas'}`}>
                        <div className="flex items-center gap-2">
                            <span
                                className="h-3 w-3 shrink-0 rounded-full border border-white/40"
                                style={{ backgroundColor: selectedTag.color || '#020323' }}
                            />
                            <div className="min-w-0">
                                <p className="truncate text-sm font-semibold">{selectedTag.name}</p>
                                <p className={`truncate text-xs ${isDark ? 'text-white/45' : 'text-brand/45'}`}>
                                    {selectedTag.category_name || 'Sem categoria'}
                                </p>
                            </div>
                        </div>
                    </div>
                )}
            </div>

            <FlowNodeHandle type="target" position={Position.Left} tone="emerald" isConnectable={isConnectable} />
            <FlowNodeHandle type="source" position={Position.Right} tone="emerald" isConnectable={isConnectable} />
        </div>
    );
};

export default memo(AddTagNode);
