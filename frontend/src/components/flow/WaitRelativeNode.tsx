import React, { memo, useState } from 'react';
import { Handle, Position, NodeProps, useReactFlow } from 'reactflow';
import { Timer, Trash2 } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import { NodeContextMenu } from './NodeContextMenu.tsx';
import { useFlowConfirm } from './FlowConfirmContext.tsx';

const unitOptions = [
    { value: 'minutes', label: 'Minutos' },
    { value: 'hours', label: 'Horas' },
    { value: 'days', label: 'Dias' },
];

const anchorOptions = [
    { value: 'appointment_start', label: 'Agendamento do gatilho' },
    { value: 'crm_stage_entered_at', label: 'Entrada no CRM' },
    { value: 'anchor_at', label: 'Data do evento gatilho' },
];

const WaitRelativeNode = ({ data, id, selected }: NodeProps) => {
    const { isDark } = useTheme();
    const { deleteElements } = useReactFlow();
    const { confirm } = useFlowConfirm();
    const [amount, setAmount] = useState(data.offsetAmount || 24);
    const [unit, setUnit] = useState(data.offsetUnit || 'hours');
    const [direction, setDirection] = useState(data.offsetDirection || 'before');
    const [anchorType, setAnchorType] = useState(data.anchorType || 'appointment_start');
    const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null);

    const updateData = (updates: Record<string, unknown>) => {
        Object.assign(data, updates);
        data.onDataChange?.(id, updates);
    };

    const handleAmountChange = (value: string) => {
        const parsed = Math.max(1, Number.parseInt(value || '1', 10) || 1);
        setAmount(parsed);
        updateData({ offsetAmount: parsed, label: 'Aguardar por data' });
    };

    const handleUnitChange = (value: string) => {
        setUnit(value);
        updateData({ offsetUnit: value, label: 'Aguardar por data' });
    };

    const handleDirectionChange = (value: string) => {
        setDirection(value);
        updateData({ offsetDirection: value, label: 'Aguardar por data' });
    };

    const handleAnchorChange = (value: string) => {
        setAnchorType(value);
        updateData({ anchorType: value, label: 'Aguardar por data' });
    };

    const handleContextMenu = (event: React.MouseEvent) => {
        event.preventDefault();
        event.stopPropagation();
        setMenuPosition({ x: event.clientX, y: event.clientY });
    };

    const handleDelete = async () => {
        const confirmed = await confirm({
            confirmText: 'Excluir espera',
            message: 'Este node e suas conexões serão removidos do fluxo.',
            title: 'Excluir espera por data?',
            variant: 'danger',
        });

        if (confirmed) {
            deleteElements({ nodes: [{ id }] });
        }
    };

    const selectedAnchorLabel = anchorOptions.find((option) => option.value === anchorType)?.label || 'Referência';
    const unitLabelMap: Record<string, { singular: string; plural: string }> = {
        days: { singular: 'dia', plural: 'dias' },
        hours: { singular: 'hora', plural: 'horas' },
        minutes: { singular: 'minuto', plural: 'minutos' },
    };
    const selectedUnitLabel = amount === 1
        ? unitLabelMap[unit]?.singular || 'hora'
        : unitLabelMap[unit]?.plural || 'horas';
    const directionLabel = direction === 'before' ? 'antes de' : 'depois de';

    return (
        <div
            onContextMenu={handleContextMenu}
            className={`rounded-lg border-l-4 border-amber-500 bg-white text-xs shadow-lg dark:bg-gray-800 ${selected ? 'ring-2 ring-amber-300' : ''}`}
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
                <Timer size={13} className="text-amber-500" />
                Aguardar por data
            </div>

            <div className="w-[260px] space-y-3 p-3">
                <div className="grid grid-cols-[1fr_104px] gap-2">
                    <div>
                        <label className="mb-1 block text-[10px] text-gray-500">Quantidade</label>
                        <input
                            type="number"
                            min={1}
                            className="nodrag w-full rounded border border-gray-200 bg-white px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700"
                            value={amount}
                            onMouseDown={(event) => event.stopPropagation()}
                            onChange={(event) => handleAmountChange(event.target.value)}
                        />
                    </div>
                    <div>
                        <label className="mb-1 block text-[10px] text-gray-500">Unidade</label>
                        <select
                            className="nodrag w-full rounded border border-gray-200 bg-white px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700"
                            value={unit}
                            onMouseDown={(event) => event.stopPropagation()}
                            onChange={(event) => handleUnitChange(event.target.value)}
                        >
                            {unitOptions.map((option) => (
                                <option key={option.value} value={option.value}>
                                    {option.label}
                                </option>
                            ))}
                        </select>
                    </div>
                </div>

                <div>
                    <label className="mb-1 block text-[10px] text-gray-500">Quando</label>
                    <select
                        className="nodrag w-full rounded border border-gray-200 bg-white px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700"
                        value={direction}
                        onMouseDown={(event) => event.stopPropagation()}
                        onChange={(event) => handleDirectionChange(event.target.value)}
                    >
                        <option value="before">Antes da referência</option>
                        <option value="after">Depois da referência</option>
                    </select>
                </div>

                <div>
                    <label className="mb-1 block text-[10px] text-gray-500">Referência de data</label>
                    <select
                        className="nodrag w-full rounded border border-gray-200 bg-white px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700"
                        value={anchorType}
                        onMouseDown={(event) => event.stopPropagation()}
                        onChange={(event) => handleAnchorChange(event.target.value)}
                    >
                        {anchorOptions.map((option) => (
                            <option key={option.value} value={option.value}>
                                {option.label}
                            </option>
                        ))}
                    </select>
                </div>

                <div className={`rounded p-2 text-[10px] ${isDark ? 'bg-amber-900/20 text-amber-200' : 'bg-amber-50 text-amber-700'}`}>
                    {amount} {selectedUnitLabel} {directionLabel} {selectedAnchorLabel.toLowerCase()}.
                </div>
            </div>

            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
        </div>
    );
};

export default memo(WaitRelativeNode);
