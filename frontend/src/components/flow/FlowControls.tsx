import React from 'react';
import { Loader2, Play, Save, Square, Wand2 } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import { agentiveIconButtonClass } from '../AgentiveUI.tsx';

interface FlowControlsProps {
    isActive: boolean;
    isDirty: boolean;
    isRunning?: boolean;
    isSaving: boolean;
    onAutoAlign: () => void;
    onRunOnce: () => void;
    onSave: () => void;
    onStop?: () => void;
    onToggleActive: (active: boolean) => void;
}

export const FlowControls: React.FC<FlowControlsProps> = ({
    isActive,
    isDirty,
    isRunning = false,
    isSaving,
    onAutoAlign,
    onRunOnce,
    onSave,
    onStop,
    onToggleActive,
}) => {
    const { isDark } = useTheme();

    return (
        <div
            className={`absolute bottom-5 left-1/2 z-50 flex max-w-[calc(100%-2rem)] -translate-x-1/2 flex-wrap items-center justify-center gap-2 rounded-2xl border p-2 shadow-[0_18px_45px_rgba(2,3,35,0.16)] backdrop-blur ${
                isDark ? 'border-white/10 bg-brand/90 text-white' : 'border-brand/10 bg-white/95 text-brand'
            }`}
        >
            {isRunning ? (
                <button
                    type="button"
                    onClick={onStop}
                    className="inline-flex min-h-10 items-center gap-2 rounded-xl bg-red-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-700"
                >
                    <Square className="h-4 w-4 fill-current" />
                    Parar teste
                </button>
            ) : (
                <button
                    type="button"
                    onClick={onRunOnce}
                    className="inline-flex min-h-10 items-center gap-2 rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand/90"
                >
                    <Play className="h-4 w-4 fill-current" />
                    Testar fluxo
                </button>
            )}

            <div className={`hidden h-8 w-px sm:block ${isDark ? 'bg-white/10' : 'bg-brand/10'}`} />

            <button
                type="button"
                onClick={() => onToggleActive(!isActive)}
                className={`inline-flex min-h-10 items-center gap-2 rounded-xl border px-3 py-2 text-sm font-medium transition ${
                    isActive
                        ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-600'
                        : isDark
                            ? 'border-white/10 bg-white/[0.06] text-white/70 hover:bg-white/10'
                            : 'border-brand/10 bg-brand-canvas text-brand/60 hover:bg-white hover:text-brand'
                }`}
                aria-pressed={isActive}
            >
                <span className={`relative inline-flex h-5 w-9 items-center rounded-full transition ${isActive ? 'bg-emerald-500' : isDark ? 'bg-white/25' : 'bg-brand/25'}`}>
                    <span className={`h-3.5 w-3.5 rounded-full bg-white transition ${isActive ? 'translate-x-[18px]' : 'translate-x-0.5'}`} />
                </span>
                {isActive ? 'Ativo' : 'Inativo'}
            </button>

            <div className={`hidden h-8 w-px sm:block ${isDark ? 'bg-white/10' : 'bg-brand/10'}`} />

            <button
                type="button"
                onClick={onSave}
                disabled={isSaving}
                title="Salvar fluxo"
                className={agentiveIconButtonClass(isDark, isDirty ? 'warning' : 'primary', 'relative')}
            >
                {isSaving ? <Loader2 className="h-5 w-5 animate-spin" /> : <Save className="h-5 w-5" />}
                {isDirty && <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-amber-500" />}
            </button>

            <button
                type="button"
                onClick={onAutoAlign}
                title="Auto-organizar nodes"
                className={agentiveIconButtonClass(isDark)}
            >
                <Wand2 className="h-5 w-5" />
            </button>
        </div>
    );
};
