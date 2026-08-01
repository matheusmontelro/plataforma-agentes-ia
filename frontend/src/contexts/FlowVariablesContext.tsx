import React, { createContext, useContext, useState, ReactNode } from 'react';
import { getVariablesFromExecutionData } from '../utils/variableUtils.ts';

interface FlowVariablesContextType {
    executionData: Record<string, any>;
    setNodeExecutionData: (
        nodeId: string,
        data: any,
        emitTrigger?: boolean,
        allowVariableOutput?: boolean
    ) => void;


    getAvailableVariables: () => { label: string; value: string; group: string }[];
    lastExecutedNodeId: string | null; // Track who just finished

    isFlowRunning: boolean;
    setIsFlowRunning: (running: boolean) => void;
}


const FlowVariablesContext = createContext<FlowVariablesContextType | undefined>(undefined);

export const FlowVariablesProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
    // executionData: { 'webhook': { body: {...}, headers: {...} } }
    const [executionData, setExecutionData] = useState<Record<string, any>>({});
    const [lastExecutedNodeId, setLastExecutedNodeId] = useState<string | null>(null);
    const [isFlowRunning, setIsFlowRunning] = useState(false);


    const setNodeExecutionData = (
        nodeId: string,
        data: any,
        emitTrigger: boolean = true,
        allowVariableOutput: boolean = false
    ) => {
        setExecutionData(prev => {
            if (allowVariableOutput) {
                const next = { ...prev };
                next[nodeId] = data;
                return next;
            } else if (nodeId in prev) {
                const next = { ...prev };
                // Ensure stale non-trigger outputs are not kept as variables.
                delete next[nodeId];
                return next;
            }

            return prev;
        });

        if (emitTrigger) {
            setLastExecutedNodeId(nodeId); // Signal completion
        }
    };

    const getAvailableVariables = () => {
        return getVariablesFromExecutionData(executionData);
    };

    return (
        <FlowVariablesContext.Provider value={{
            executionData,
            setNodeExecutionData,
            getAvailableVariables,
            lastExecutedNodeId,
            isFlowRunning,
            setIsFlowRunning
        }}>
            {children}
        </FlowVariablesContext.Provider>
    );
};

export const useFlowVariables = () => {
    const context = useContext(FlowVariablesContext);
    if (!context) {
        throw new Error('useFlowVariables must be used within a FlowVariablesProvider');
    }
    return context;
};
