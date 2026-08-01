import React, { memo, useCallback, useEffect, useRef, useState } from 'react';
import { Handle, Position, NodeProps, useReactFlow } from 'reactflow';
import { MessageCircle, Trash2, Image, Video, Mic, FileText, Phone, User, Loader2, Check, X } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import { NodeContextMenu } from './NodeContextMenu.tsx';
import { API_URL } from '../../services/api.ts';
import { useFlowVariables } from '../../contexts/FlowVariablesContext.tsx';
import { useFlowConfirm } from './FlowConfirmContext.tsx';

const FLOW_BUILDER_WHATSAPP_TOPIC = '__flow_builder_whatsapp__';

const getWsUrl = (baseUrl: string) => {
    const cleanUrl = baseUrl.replace(/\/$/, '');
    if (cleanUrl.startsWith('https://')) {
        return cleanUrl.replace('https://', 'wss://');
    }
    return cleanUrl.replace('http://', 'ws://');
};

const normalizeExecutionContext = (payload: any) => {
    return {
        phone: payload?.phone || '',
        name: payload?.name || '',
        body: payload?.body || '',
        type: payload?.type || 'text',
        mediaUrl: payload?.mediaUrl || '',
        timestamp: payload?.timestamp || '',
        provider: payload?.provider || 'unknown',
        raw: payload?.raw || payload || {}
    };
};

/**
 * WhatsAppTriggerNode - Trigger node for incoming WhatsApp messages via WAHA
 *
 * This node represents the entry point for flows triggered by incoming messages.
 * It supports global "Run Once" by capturing a real incoming message as sample data.
 */
const WhatsAppTriggerNode = ({ data, id, selected }: NodeProps) => {
    const { isDark } = useTheme();
    const { deleteElements } = useReactFlow();
    const { setNodeExecutionData, isFlowRunning, setIsFlowRunning } = useFlowVariables();
    const { confirm, notice } = useFlowConfirm();

    // Context Menu State
    const [menuPosition, setMenuPosition] = useState<{ x: number, y: number } | null>(null);

    // Run Once/Listener State
    const [isListening, setIsListening] = useState(false);
    const [receivedData, setReceivedData] = useState<any>(null);
    const wsRef = useRef<WebSocket | null>(null);
    const keepAliveIntervalRef = useRef<number | null>(null);
    const lastRunRef = useRef<number>(data.triggerRunOnce || 0);

    const clearKeepAlive = useCallback(() => {
        if (keepAliveIntervalRef.current !== null) {
            window.clearInterval(keepAliveIntervalRef.current);
            keepAliveIntervalRef.current = null;
        }
    }, []);

    const startKeepAlive = useCallback((ws: WebSocket) => {
        clearKeepAlive();
        keepAliveIntervalRef.current = window.setInterval(() => {
            try {
                if (ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'ping', source: 'flow_builder_run_once' }));
                }
            } catch (error) {
                console.warn('[WhatsAppTriggerNode] Keepalive failed', error);
            }
        }, 15000);
    }, [clearKeepAlive]);

    const closeSocket = useCallback(() => {
        clearKeepAlive();
        if (wsRef.current) {
            wsRef.current.close();
            wsRef.current = null;
        }
    }, [clearKeepAlive]);

    const handleCancel = useCallback(() => {
        closeSocket();
        setIsListening(false);
        setIsFlowRunning(false);
    }, [closeSocket, setIsFlowRunning]);

    const handleRunOnce = useCallback(() => {
        if (isListening) return;

        const companyId = parseInt((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')) || '0', 10);
        if (!companyId) {
            void notice({
                title: 'Empresa não identificada',
                message: 'Nao foi possivel identificar a empresa para iniciar o teste do WhatsApp.',
            });
            setIsFlowRunning(false);
            return;
        }

        closeSocket();
        setReceivedData(null);
        setIsListening(true);
        setIsFlowRunning(true);

        const wsBase = API_URL
            ? getWsUrl(API_URL)
            : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`;
        const wsUrl = `${wsBase}/ws/chat?company_id=${encodeURIComponent(
            companyId.toString()
        )}&phone=${encodeURIComponent(FLOW_BUILDER_WHATSAPP_TOPIC)}`;

        console.log(`[WhatsAppTriggerNode] Starting Run Once listener: company=${companyId}`);

        try {
            const ws = new WebSocket(wsUrl);
            wsRef.current = ws;

            ws.onopen = () => {
                console.log('[WhatsAppTriggerNode] Listening for real WhatsApp messages...');
                startKeepAlive(ws);
            };

            ws.onmessage = (event) => {
                try {
                    const message = JSON.parse(event.data);
                    if (message.type !== 'whatsapp_trigger_event' || !message.payload) return;

                    const executionContext = normalizeExecutionContext(message.payload);
                    console.log('[WhatsAppTriggerNode] Event received, capturing sample data.');

                    setReceivedData(executionContext);
                    // Real WhatsApp messages are processed by the backend worker when
                    // the flow is active. Capturing only prevents the builder tab from
                    // sending a second production response during Run Once.
                    setNodeExecutionData(id, executionContext, false, true);
                    setIsListening(false);
                    setIsFlowRunning(false);
                    closeSocket();
                } catch (error) {
                    console.error('[WhatsAppTriggerNode] Failed to parse WS message', error);
                }
            };

            ws.onerror = (error) => {
                console.error('[WhatsAppTriggerNode] WS error', error);
            };

            ws.onclose = () => {
                clearKeepAlive();
                setIsListening(false);
            };
        } catch (error) {
            console.error('[WhatsAppTriggerNode] Failed to create WS connection', error);
            setIsListening(false);
            setIsFlowRunning(false);
        }
    }, [clearKeepAlive, closeSocket, id, isListening, setIsFlowRunning, setNodeExecutionData, startKeepAlive]);

    // Sync Global Stop -> Local Stop
    useEffect(() => {
        if (!isFlowRunning && isListening) {
            console.log('[WhatsAppTriggerNode] Global stop received. Closing listener.');
            closeSocket();
            setIsListening(false);
        }
    }, [closeSocket, isFlowRunning, isListening]);

    // Effect to handle external run once trigger (from global button)
    useEffect(() => {
        if (data.triggerRunOnce && data.triggerRunOnce !== lastRunRef.current && !isListening) {
            lastRunRef.current = data.triggerRunOnce;
            handleRunOnce();
        }
    }, [data.triggerRunOnce, handleRunOnce, isListening]);

    // Cleanup WS on unmount
    useEffect(() => {
        return () => {
            closeSocket();
        };
    }, [closeSocket]);

    const getTypeIcon = (type: string) => {
        switch (type) {
            case 'image': return <Image className="w-3 h-3" />;
            case 'video': return <Video className="w-3 h-3" />;
            case 'audio': return <Mic className="w-3 h-3" />;
            case 'document': return <FileText className="w-3 h-3" />;
            default: return <MessageCircle className="w-3 h-3" />;
        }
    };

    return (
        <div
            onContextMenu={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setMenuPosition({ x: e.clientX, y: e.clientY });
            }}
            className={`shadow-[0_14px_34px_rgba(2,3,35,0.12)] rounded-2xl border min-w-[300px] max-w-[300px] transition-all duration-200 relative ${isDark ? 'bg-brand border-white/10' : 'bg-white border-brand/10'
                } ${selected ? 'ring-2 ring-green-500/50' : ''}`}
        >
            {/* Context Menu */}
            {menuPosition && (
                <NodeContextMenu
                    x={menuPosition.x}
                    y={menuPosition.y}
                    onClose={() => setMenuPosition(null)}
                    actions={[
                        {
                            label: 'Excluir Nó',
                            icon: <Trash2 className="w-3 h-3" />,
                            onClick: async () => {
                                const confirmed = await confirm({
                                    confirmText: 'Excluir gatilho',
                                    message: 'Este gatilho e suas conexões serão removidos do fluxo.',
                                    title: 'Excluir gatilho WhatsApp?',
                                    variant: 'danger',
                                });
                                if (confirmed) deleteElements({ nodes: [{ id }] });
                            },
                            danger: true
                        }
                    ]}
                />
            )}

            {/* Header */}
            <div className={`px-4 py-3 border-b flex items-center gap-3 rounded-t-2xl ${isDark ? 'bg-white/[0.04] border-white/10' : 'bg-brand-canvas border-brand/10'}`}>
                <div className="p-2 bg-green-500/20 rounded-lg">
                    <MessageCircle className="w-4 h-4 text-green-500" />
                </div>
                <div className="flex-1">
                    <h3 className={`text-sm font-bold ${isDark ? 'text-white' : 'text-brand'}`}>Mensagem WhatsApp</h3>
                    <p className={`text-[10px] uppercase font-bold tracking-wide ${isDark ? 'text-white/40' : 'text-brand/40'}`}>Gatilho</p>
                </div>
            </div>

            {/* Content */}
            <div
                className="p-4 space-y-3"
                onWheel={(e) => e.stopPropagation()}
            >
                {/* Info Box */}
                <div className={`p-3 rounded-lg text-xs ${isDark ? 'bg-gray-700/50' : 'bg-gray-50'}`}>
                    <p className={`font-medium mb-2 ${isDark ? 'text-gray-300' : 'text-gray-700'}`}>
                        Este fluxo será acionado quando uma mensagem real do WhatsApp for recebida.
                    </p>
                    <p className={`text-[10px] ${isDark ? 'text-gray-500' : 'text-gray-400'}`}>
                        No Run Once, ele captura uma mensagem real como amostra; o envio ativo roda no backend.
                    </p>
                </div>

                {/* Available Variables */}
                <div className="space-y-2">
                    <label className={`block text-xs font-bold uppercase tracking-wider ${isDark ? 'text-gray-500' : 'text-gray-400'}`}>
                        Variáveis Disponíveis
                    </label>

                    <div className={`space-y-1.5 text-[11px] font-mono ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
                        <div className="flex items-center gap-2">
                            <Phone className="w-3 h-3" />
                            <code className={`px-1.5 py-0.5 rounded ${isDark ? 'bg-gray-700' : 'bg-gray-200'}`}>
                                {`{{trigger.phone}}`}
                            </code>
                            <span className="text-[10px] opacity-60">Telefone</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <User className="w-3 h-3" />
                            <code className={`px-1.5 py-0.5 rounded ${isDark ? 'bg-gray-700' : 'bg-gray-200'}`}>
                                {`{{trigger.name}}`}
                            </code>
                            <span className="text-[10px] opacity-60">Nome</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <MessageCircle className="w-3 h-3" />
                            <code className={`px-1.5 py-0.5 rounded ${isDark ? 'bg-gray-700' : 'bg-gray-200'}`}>
                                {`{{trigger.body}}`}
                            </code>
                            <span className="text-[10px] opacity-60">Mensagem</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <FileText className="w-3 h-3" />
                            <code className={`px-1.5 py-0.5 rounded ${isDark ? 'bg-gray-700' : 'bg-gray-200'}`}>
                                {`{{trigger.type}}`}
                            </code>
                            <span className="text-[10px] opacity-60">Tipo</span>
                        </div>
                    </div>
                </div>

                {receivedData && !isListening && (
                    <div className={`p-3 rounded-lg border text-xs ${isDark ? 'bg-emerald-900/20 border-emerald-800 text-emerald-300' : 'bg-emerald-50 border-emerald-200 text-emerald-700'}`}>
                        <div className="flex items-center justify-between gap-2 mb-2">
                            <div className="flex items-center gap-1.5">
                                <Check className="w-3 h-3" />
                                <span className="font-semibold">Evento recebido</span>
                            </div>
                            <button
                                onClick={(e) => { e.stopPropagation(); setReceivedData(null); }}
                                className="opacity-70 hover:opacity-100"
                                title="Limpar resultado"
                            >
                                <X className="w-3 h-3" />
                            </button>
                        </div>
                        <div className="space-y-1">
                            <div className="flex items-center gap-2">
                                <Phone className="w-3 h-3" />
                                <span className="truncate">{receivedData.phone || 'Sem telefone'}</span>
                            </div>
                            <div className="flex items-center gap-2">
                                {getTypeIcon(receivedData.type)}
                                <span className="truncate">{receivedData.type || 'text'}</span>
                            </div>
                            <div className="truncate opacity-80">{receivedData.body || '(sem texto)'}</div>
                        </div>
                    </div>
                )}

                {/* Status Indicator */}
                <div className={`flex items-center gap-2 px-3 py-2 rounded-lg ${isListening
                    ? (isDark ? 'bg-yellow-900/20 border border-yellow-800' : 'bg-yellow-50 border border-yellow-200')
                    : (isDark ? 'bg-green-900/20 border border-green-800' : 'bg-green-50 border border-green-200')
                    }`}
                >
                    {isListening ? (
                        <Loader2 className="w-3 h-3 text-yellow-500 animate-spin" />
                    ) : (
                        <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
                    )}
                    <span className={`text-xs font-medium ${isListening
                        ? (isDark ? 'text-yellow-400' : 'text-yellow-700')
                        : (isDark ? 'text-green-400' : 'text-green-700')
                        }`}
                    >
                        {isListening ? 'Aguardando mensagem real...' : 'Pronto para capturar amostra'}
                    </span>
                    {isListening && (
                        <button
                            onClick={(e) => { e.stopPropagation(); handleCancel(); }}
                            className="ml-auto text-[10px] underline opacity-80 hover:opacity-100"
                        >
                            Cancelar
                        </button>
                    )}
                </div>
            </div>

            {/* Only output handle - this is a trigger */}
            <Handle
                type="source"
                position={Position.Right}
                className="!w-3 !h-3 !bg-green-500 !border-2 !border-white dark:!border-gray-800"
            />
        </div>
    );
};

export default memo(WhatsAppTriggerNode);
