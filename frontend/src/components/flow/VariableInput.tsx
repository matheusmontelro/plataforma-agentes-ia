import React, { useState, useRef, useEffect } from 'react';
import { Braces, ChevronDown, X } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import { useFlowVariables } from '../../contexts/FlowVariablesContext.tsx';

interface VariableInputProps {
    value: string;
    onChange: (value: string) => void;
    placeholder?: string;
    className?: string;
    label?: string;
    list?: string;
    disableVariables?: boolean;
    isTextArea?: boolean;
}

export const VariableInput: React.FC<VariableInputProps> = ({
    value,
    onChange,
    placeholder,
    className,
    label,
    list,
    disableVariables = false,
    isTextArea = false
}) => {
    const { isDark } = useTheme();
    const { getAvailableVariables } = useFlowVariables();
    const [showVariables, setShowVariables] = useState(false);
    const containerRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLElement>(null);

    const variables = getAvailableVariables();

    // Close dropdown on click outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                setShowVariables(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
        };
    }, []);

    const handleVariableSelect = (variableValue: string) => {
        // Insert variable at cursor position or append
        const input = inputRef.current as HTMLInputElement | HTMLTextAreaElement;

        if (input) {
            const start = input.selectionStart || 0;
            const end = input.selectionEnd || 0;
            const newValue = value.slice(0, start) + variableValue + value.slice(end);
            onChange(newValue);

            // Restore focus and move cursor
            setTimeout(() => {
                input.focus();
                const newPos = start + variableValue.length;
                input.setSelectionRange(newPos, newPos);
            }, 0);
        } else {
            onChange(value + variableValue);
        }
        setShowVariables(false);
    };

    return (
        <div className="relative" ref={containerRef}>
            {label && (
                <div className="flex justify-between items-center mb-1">
                    <label className={`block text-xs font-medium ${isDark ? 'text-white/60' : 'text-brand/60'}`}>
                        {label}
                    </label>
                    {/* Optional: Indicator if variables are available */}
                    {!disableVariables && variables.length > 0 && (
                        <span className="text-[10px] text-blue-500 font-medium opacity-80">
                            {variables.length} var(s)
                        </span>
                    )}
                </div>
            )}

            <div className="relative flex items-center">
                {isTextArea ? (
                    <textarea
                        ref={inputRef as any}
                        value={value}
                        onChange={(e) => onChange(e.target.value)}
                        onMouseDown={(e) => e.stopPropagation()} // Important for React Flow
                        placeholder={placeholder}
                        rows={3}
                        className={`w-full px-3 py-2 pr-8 text-xs rounded-xl border outline-none focus:ring-2 focus:ring-brand/20 transition-all resize-none ${isDark
                            ? 'bg-white/[0.06] border-white/10 text-white placeholder:text-white/35'
                            : 'bg-white border-brand/10 text-brand placeholder:text-brand/35'
                            } ${className || ''}`}
                    />
                ) : (
                    <input
                        ref={inputRef as any}
                        type="text"
                        value={value}
                        onChange={(e) => onChange(e.target.value)}
                        onMouseDown={(e) => e.stopPropagation()} // Important for React Flow
                        placeholder={placeholder}
                        list={list} // Keep support for datalist if passed
                        className={`w-full px-3 py-2 pr-8 text-xs rounded-xl border outline-none focus:ring-2 focus:ring-brand/20 transition-all ${isDark
                            ? 'bg-white/[0.06] border-white/10 text-white placeholder:text-white/35'
                            : 'bg-white border-brand/10 text-brand placeholder:text-brand/35'
                            } ${className || ''}`}
                    />
                )}

                {/* Trigger Button */}
                {!disableVariables && (
                    <button
                        onClick={() => setShowVariables(!showVariables)}
                        className={`absolute right-1 top-1 p-1.5 rounded-md transition-colors ${isDark
                            ? 'text-white/45 hover:bg-white/10 hover:text-white'
                            : 'text-brand/40 hover:bg-brand-canvas hover:text-brand'
                            } ${showVariables ? 'bg-brand/10 text-brand dark:bg-white/10 dark:text-white' : ''}`}
                        title="Inserir Variável"
                    >
                        <Braces className="w-3.5 h-3.5" />
                    </button>
                )}
            </div>

            {/* Variables Dropdown */}
            {showVariables && (
                <div className={`absolute left-0 right-0 top-full mt-1 z-50 max-h-[200px] overflow-y-auto rounded-2xl border shadow-[0_18px_45px_rgba(2,3,35,0.16)] custom-scrollbar animation-fade-in ${isDark ? 'bg-brand border-white/10' : 'bg-white border-brand/10'
                    }`}>
                    {variables.length === 0 ? (
                        <div className="p-3 text-center text-xs text-gray-500">
                            Nenhuma variável detectada.<br />
                            Execute o "Run Once" no trigger primeiro.
                        </div>
                    ) : (
                        <div className="p-1">
                            <div className={`px-2 py-1 text-[10px] font-bold uppercase tracking-wider ${isDark ? 'bg-white/[0.04] text-white/40' : 'bg-brand-canvas text-brand/40'}`}>
                                Variáveis Disponíveis
                            </div>
                            {variables.map((v, idx) => (
                                <button
                                    key={idx}
                                    onClick={() => handleVariableSelect(v.value)}
                                    className={`w-full text-left px-3 py-2 text-xs flex justify-between items-center group transition-colors ${isDark
                                        ? 'hover:bg-white/10 text-white/70'
                                        : 'hover:bg-brand-canvas text-brand/70'
                                        }`}
                                >
                                    <span className="font-mono text-blue-500">{v.label}</span>
                                    <span className={`text-[10px] opacity-0 group-hover:opacity-100 ${isDark ? 'text-gray-500' : 'text-gray-400'}`}>
                                        {v.value}
                                    </span>
                                </button>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};
