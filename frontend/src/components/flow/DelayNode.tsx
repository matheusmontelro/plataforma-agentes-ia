import React, { memo, useState, useEffect } from 'react';
import { Position } from 'reactflow';
import { Clock } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import {
    FlowNodeHandle,
    FlowNodeHeader,
    flowNodeLabelClass,
    flowNodeSelectClass,
    flowNodeShellClass,
} from './FlowNodeChrome.tsx';

export default memo(({ data, isConnectable, selected }: any) => {
    const { isDark } = useTheme();

    // -- Local State for Immediate UI Feedback --
    // Solves the "input stuck" or "reverting" issue by decoupling
    // value from the possibly slow or missing parent prop update.
    const [amount, setAmount] = useState(data.delayAmount || 1);
    const [unit, setUnit] = useState(data.delayUnit || 'minutes');

    // -- Sync Local State to Global Data --
    // Maintains persistence and compatibility with flow saving
    useEffect(() => {
        data.delayAmount = amount;
        data.delayUnit = unit;

        // If parent provided a persistent change handler, call it too
        if (data.onChange) {
            data.onChange({
                ...data,
                delayAmount: amount,
                delayUnit: unit
            });
        }
    }, [amount, unit, data]);

    return (
        <div className={flowNodeShellClass(isDark, Boolean(selected), 'amber', 'w-[240px] text-xs')}>
            <FlowNodeHeader icon={Clock} title="Aguardar" subtitle="Tempo" tone="amber" />

            <div className="p-3 space-y-3">
                <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-2 text-[10px] text-amber-700 dark:text-amber-300">
                    Máximo permitido: 5 minutos
                </div>

                <div className="flex gap-2">
                    <div className="flex-1">
                        <label className={flowNodeLabelClass(isDark)}>Quantidade</label>
                        <input
                            type="number"
                            className={`${flowNodeSelectClass(isDark)} px-2 py-1 text-xs`}
                            placeholder="1"
                            value={amount}
                            min={1}
                            max={unit === 'seconds' ? 300 : 5}
                            onMouseDown={(e) => e.stopPropagation()}
                            onChange={(e) => {
                                // Allow free typing/spinning, validate on blur
                                let val = parseInt(e.target.value);
                                if (isNaN(val)) val = 0;
                                setAmount(val);
                            }}
                            onBlur={() => {
                                // Clamp value on blur to ensure validity
                                const max = unit === 'seconds' ? 300 : 5;
                                let val = amount;
                                if (val > max) val = max;
                                if (val < 1) val = 1;
                                setAmount(val);
                            }}
                        />
                    </div>

                    <div className="w-24">
                        <label className={flowNodeLabelClass(isDark)}>Unidade</label>
                        <select
                            className={`${flowNodeSelectClass(isDark)} px-2 py-1 text-xs`}
                            value={unit}
                            onMouseDown={(e) => e.stopPropagation()}
                            onChange={(e) => {
                                const newUnit = e.target.value;
                                setUnit(newUnit);

                                // Re-validate amount against new unit limits
                                let max = newUnit === 'seconds' ? 300 : 5;
                                if (amount > max) {
                                    setAmount(max);
                                }
                            }}
                        >
                            <option value="seconds">Segundos</option>
                            <option value="minutes">Minutos</option>
                        </select>
                    </div>
                </div>
            </div>

            <FlowNodeHandle type="target" position={Position.Left} tone="amber" isConnectable={isConnectable} />
            <FlowNodeHandle type="source" position={Position.Right} tone="amber" isConnectable={isConnectable} />
        </div>
    );
});
