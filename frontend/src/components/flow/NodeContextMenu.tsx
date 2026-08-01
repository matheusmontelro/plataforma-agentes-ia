import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTheme } from '../../contexts/ThemeContext.tsx';

interface Action {
    label: string;
    icon?: React.ReactNode;
    onClick: () => void | Promise<void>;
    danger?: boolean;
}

interface NodeContextMenuProps {
    x: number;
    y: number;
    onClose: () => void;
    actions: Action[];
}

export const NodeContextMenu: React.FC<NodeContextMenuProps> = ({ x, y, onClose, actions }) => {
    const { isDark } = useTheme();
    const menuRef = useRef<HTMLDivElement>(null);
    const [position, setPosition] = useState({ left: x, top: y });

    useLayoutEffect(() => {
        const menu = menuRef.current;
        if (!menu) {
            setPosition({ left: x, top: y });
            return;
        }

        const padding = 8;
        const rect = menu.getBoundingClientRect();
        const maxLeft = Math.max(padding, window.innerWidth - rect.width - padding);
        const maxTop = Math.max(padding, window.innerHeight - rect.height - padding);

        setPosition({
            left: Math.min(Math.max(padding, x), maxLeft),
            top: Math.min(Math.max(padding, y), maxTop),
        });
    }, [actions.length, x, y]);

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
                onClose();
            }
        };
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                onClose();
            }
        };

        document.addEventListener('mousedown', handleClickOutside);
        document.addEventListener('keydown', handleKeyDown);
        window.addEventListener('resize', onClose);
        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
            document.removeEventListener('keydown', handleKeyDown);
            window.removeEventListener('resize', onClose);
        };
    }, [onClose]);

    if (typeof document === 'undefined') return null;

    return createPortal(
        <div
            ref={menuRef}
            onContextMenu={(event) => event.preventDefault()}
            onMouseDown={(event) => event.stopPropagation()}
            style={{ top: position.top, left: position.left, position: 'fixed', zIndex: 2147483647 }}
            className={`min-w-[176px] overflow-hidden rounded-2xl border p-1 shadow-[0_18px_45px_rgba(2,3,35,0.16)] animation-fade-in ${isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand'
                }`}
        >
            <div className="flex flex-col gap-1">
                {actions.map((action, index) => (
                    <button
                        key={index}
                        onClick={(e) => {
                            e.stopPropagation();
                            action.onClick();
                            onClose();
                        }}
                        className={`flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-left text-xs font-medium transition-colors ${action.danger
                                ? (isDark ? 'text-red-300 hover:bg-red-500/10' : 'text-red-600 hover:bg-red-50')
                                : (isDark ? 'text-white/75 hover:bg-white/10 hover:text-white' : 'text-brand/70 hover:bg-brand-canvas hover:text-brand')
                            }`}
                    >
                        {action.icon && <span className="w-4 h-4">{action.icon}</span>}
                        {action.label}
                    </button>
                ))}
            </div>
        </div>,
        document.body
    );
};
