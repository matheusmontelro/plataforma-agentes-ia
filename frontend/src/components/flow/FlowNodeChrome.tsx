import React from 'react';
import { Handle, Position } from 'reactflow';
import { type LucideIcon } from 'lucide-react';

type FlowNodeTone = 'green' | 'pink' | 'blue' | 'emerald' | 'indigo' | 'purple' | 'sky' | 'amber';

const toneClassMap: Record<FlowNodeTone, {
    accent: string;
    handle: string;
    icon: string;
    ring: string;
    soft: string;
}> = {
    green: {
        accent: 'bg-emerald-500',
        handle: '!bg-emerald-500',
        icon: 'bg-emerald-500/15 text-emerald-300',
        ring: 'ring-emerald-500/45',
        soft: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-600',
    },
    pink: {
        accent: 'bg-pink-500',
        handle: '!bg-pink-500',
        icon: 'bg-pink-500/15 text-pink-300',
        ring: 'ring-pink-500/45',
        soft: 'border-pink-500/20 bg-pink-500/10 text-pink-600',
    },
    blue: {
        accent: 'bg-blue-500',
        handle: '!bg-blue-500',
        icon: 'bg-blue-500/15 text-blue-300',
        ring: 'ring-blue-500/45',
        soft: 'border-blue-500/20 bg-blue-500/10 text-blue-600',
    },
    emerald: {
        accent: 'bg-emerald-500',
        handle: '!bg-emerald-500',
        icon: 'bg-emerald-500/15 text-emerald-300',
        ring: 'ring-emerald-500/45',
        soft: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-600',
    },
    indigo: {
        accent: 'bg-indigo-500',
        handle: '!bg-indigo-500',
        icon: 'bg-indigo-500/15 text-indigo-300',
        ring: 'ring-indigo-500/45',
        soft: 'border-indigo-500/20 bg-indigo-500/10 text-indigo-600',
    },
    purple: {
        accent: 'bg-purple-500',
        handle: '!bg-purple-500',
        icon: 'bg-purple-500/15 text-purple-300',
        ring: 'ring-purple-500/45',
        soft: 'border-purple-500/20 bg-purple-500/10 text-purple-600',
    },
    sky: {
        accent: 'bg-sky-500',
        handle: '!bg-sky-500',
        icon: 'bg-sky-500/15 text-sky-300',
        ring: 'ring-sky-500/45',
        soft: 'border-sky-500/20 bg-sky-500/10 text-sky-600',
    },
    amber: {
        accent: 'bg-amber-500',
        handle: '!bg-amber-500',
        icon: 'bg-amber-500/15 text-amber-300',
        ring: 'ring-amber-500/45',
        soft: 'border-amber-500/20 bg-amber-500/10 text-amber-700',
    },
};

export const flowNodeShellClass = (
    isDark: boolean,
    selected: boolean,
    tone: FlowNodeTone,
    className = 'min-w-[320px] max-w-[320px]'
) => {
    const toneClasses = toneClassMap[tone];

    return [
        'relative overflow-hidden rounded-[20px] border shadow-[0_18px_45px_rgba(2,3,35,0.16)] transition-all duration-200',
        className,
        isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand',
        selected ? `ring-2 ${toneClasses.ring}` : 'hover:shadow-[0_22px_55px_rgba(2,3,35,0.2)]',
    ].join(' ');
};

export const FlowNodeHeader: React.FC<{
    icon: LucideIcon;
    meta?: React.ReactNode;
    subtitle: string;
    title: string;
    tone: FlowNodeTone;
}> = ({ icon: Icon, meta, subtitle, title, tone }) => {
    const toneClasses = toneClassMap[tone];

    return (
        <div className="relative overflow-hidden border-b border-white/10 bg-brand px-4 py-3 text-white">
            <div className={`absolute inset-y-0 left-0 w-1 ${toneClasses.accent}`} />
            <div className="flex items-center gap-3">
                <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ${toneClasses.icon}`}>
                    <Icon className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                    <h3 className="truncate text-sm font-semibold leading-tight">{title}</h3>
                    <p className="mt-0.5 text-[10px] font-bold uppercase tracking-[0.16em] text-white/45">
                        {subtitle}
                    </p>
                </div>
                {meta}
            </div>
        </div>
    );
};

export const flowNodeLabelClass = (isDark: boolean) =>
    `block text-[10px] font-bold uppercase tracking-[0.16em] ${isDark ? 'text-white/45' : 'text-brand/45'}`;

export const flowNodeSelectClass = (isDark: boolean) =>
    `nodrag w-full appearance-none rounded-xl border px-3 py-2 pr-8 text-sm outline-none transition focus:ring-2 focus:ring-brand/20 ${
        isDark
            ? 'border-white/10 bg-white/[0.06] text-white'
            : 'border-brand/10 bg-brand-canvas text-brand'
    }`;

export const flowNodePanelClass = (isDark: boolean, tone?: FlowNodeTone) => {
    if (tone) {
        return `rounded-xl border p-3 ${toneClassMap[tone].soft}`;
    }

    return `rounded-xl border p-3 ${isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas'}`;
};

export const FlowNodeHandle: React.FC<{
    isConnectable?: boolean;
    position: Position;
    tone: FlowNodeTone;
    type: 'source' | 'target';
}> = ({ isConnectable, position, tone, type }) => (
    <Handle
        type={type}
        position={position}
        isConnectable={isConnectable}
        className={`!h-3.5 !w-3.5 ${toneClassMap[tone].handle} !border-2 !border-white dark:!border-brand`}
    />
);
