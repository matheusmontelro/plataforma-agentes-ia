import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { AgentiveConfirmModal } from '../AgentiveUI.tsx';

type FlowConfirmVariant = 'danger' | 'warning' | 'info';

interface FlowConfirmOptions {
    cancelText?: string;
    confirmText?: string;
    message: React.ReactNode;
    title: string;
    variant?: FlowConfirmVariant;
}

interface PendingConfirmation extends FlowConfirmOptions {
    resolve: (confirmed: boolean) => void;
}

interface FlowConfirmContextValue {
    confirm: (options: FlowConfirmOptions) => Promise<boolean>;
    notice: (options: FlowConfirmOptions) => Promise<void>;
}

const FlowConfirmContext = createContext<FlowConfirmContextValue | null>(null);

export const FlowConfirmProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [pending, setPending] = useState<PendingConfirmation | null>(null);

    const closePending = useCallback((confirmed: boolean) => {
        setPending((current) => {
            current?.resolve(confirmed);
            return null;
        });
    }, []);

    const confirm = useCallback((options: FlowConfirmOptions) => {
        return new Promise<boolean>((resolve) => {
            setPending({ ...options, resolve });
        });
    }, []);

    const notice = useCallback(async (options: FlowConfirmOptions) => {
        await confirm({
            cancelText: 'Fechar',
            confirmText: 'Entendi',
            variant: 'info',
            ...options,
        });
    }, [confirm]);

    const value = useMemo(() => ({ confirm, notice }), [confirm, notice]);

    return (
        <FlowConfirmContext.Provider value={value}>
            {children}
            <AgentiveConfirmModal
                cancelText={pending?.cancelText || 'Cancelar'}
                confirmText={pending?.confirmText || 'Confirmar'}
                isOpen={Boolean(pending)}
                message={pending?.message}
                onClose={() => closePending(false)}
                onConfirm={() => closePending(true)}
                title={pending?.title || ''}
                variant={pending?.variant || 'warning'}
            />
        </FlowConfirmContext.Provider>
    );
};

export const useFlowConfirm = (): FlowConfirmContextValue => {
    const context = useContext(FlowConfirmContext);

    if (!context) {
        return {
            confirm: async (_options: FlowConfirmOptions) => {
                console.warn('[FlowConfirm] Provider ausente.');
                return false;
            },
            notice: async (options: FlowConfirmOptions) => {
                console.warn('[FlowConfirm] Provider ausente:', options.title);
            },
        };
    }

    return context;
};
