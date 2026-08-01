import React, { memo, useEffect, useMemo, useState, useRef } from 'react';
import { Position, NodeProps, useReactFlow } from 'reactflow';
import { Webhook, ChevronDown, Loader2, AlertCircle, Play, X, Copy, Check, Trash2, SlidersHorizontal } from 'lucide-react';
import { getWebhookUrl, getWebhooks, type WebhookTrigger } from '../../services/webhookBuilderApi.ts';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import { API_URL } from '../../services/api.ts';
import { NodeContextMenu } from './NodeContextMenu.tsx';
import { useFlowVariables } from '../../contexts/FlowVariablesContext.tsx';
import { useFlowConfirm } from './FlowConfirmContext.tsx';
import {
    buildWebhookExecutionContext,
    detectWebhookStandardMapping,
    getWebhookPayloadPathOptions,
    WEBHOOK_STANDARD_MAPPING_FIELDS,
    type WebhookStandardMapping,
} from '../../utils/variableUtils.ts';
import {
    FlowNodeHandle,
    FlowNodeHeader,
    flowNodeLabelClass,
    flowNodePanelClass,
    flowNodeSelectClass,
    flowNodeShellClass,
} from './FlowNodeChrome.tsx';

const resolveCompanyId = (currentWebhook: WebhookTrigger | undefined): number | null => {
    const fromWebhook = Number(currentWebhook?.company_id);
    if (Number.isFinite(fromWebhook) && fromWebhook > 0) {
        return fromWebhook;
    }

    const fromStorage = Number((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')));
    if (Number.isFinite(fromStorage) && fromStorage > 0) {
        return fromStorage;
    }

    return null;
};

const copyTextToClipboard = async (text: string) => {
    if (navigator.clipboard?.writeText && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return;
    }

    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.setAttribute('readonly', '');
    textArea.style.position = 'fixed';
    textArea.style.left = '-9999px';
    textArea.style.top = '0';
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();

    try {
        const copied = document.execCommand('copy');
        if (!copied) {
            throw new Error('Fallback clipboard copy failed');
        }
    } finally {
        document.body.removeChild(textArea);
    }
};

const mergeDetectedMapping = (
    current: WebhookStandardMapping,
    detected: WebhookStandardMapping
): WebhookStandardMapping => ({
    ...detected,
    ...Object.fromEntries(
        Object.entries(current || {}).filter(([, value]) => typeof value === 'string' && value.trim())
    ),
});

const WebhookNode = ({ data, id, selected }: NodeProps) => {
    const { isDark } = useTheme();
    const { deleteElements, setNodes } = useReactFlow();
    const { setNodeExecutionData, isFlowRunning, setIsFlowRunning } = useFlowVariables();
    const { confirm, notice } = useFlowConfirm();

    const [webhooks, setWebhooks] = useState<WebhookTrigger[]>([]);
    const [loading, setLoading] = useState(false);
    const [selectedWebhookId, setSelectedWebhookId] = useState<string>(data.webhookId || '');
    const [webhookMapping, setWebhookMapping] = useState<WebhookStandardMapping>(
        data.webhookMapping || data.webhook_mapping || {}
    );

    // Context Menu State
    const [menuPosition, setMenuPosition] = useState<{ x: number, y: number } | null>(null);

    // Run Once State
    const [isListening, setIsListening] = useState(false);
    const keepAliveIntervalRef = useRef<number | null>(null);
    const userInitiatedCloseRef = useRef(false);

    // Sync Global Stop -> Local Stop
    useEffect(() => {
        if (!isFlowRunning && isListening) {
            // Global stop triggered
            clearKeepAlive();
            if (wsRef.current) {
                userInitiatedCloseRef.current = true;
                wsRef.current.close();
                wsRef.current = null;
            }
            setIsListening(false);
        }
    }, [isFlowRunning, isListening]);
    const [receivedData, setReceivedData] = useState<any>(null);
    const wsRef = useRef<WebSocket | null>(null);
    const shouldTriggerChainRef = useRef<boolean>(true); // Track intent
    const lastRunRef = useRef<number>(Number(data.triggerRunOnce) || 0);

    const [copySuccess, setCopySuccess] = useState(false);
    const pathOptions = useMemo(() => (
        receivedData ? getWebhookPayloadPathOptions(receivedData) : []
    ), [receivedData]);

    const updateNodeData = (updates: Record<string, unknown>) => {
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
    };

    const clearKeepAlive = () => {
        if (keepAliveIntervalRef.current !== null) {
            window.clearInterval(keepAliveIntervalRef.current);
            keepAliveIntervalRef.current = null;
        }
    };

    const startKeepAlive = (ws: WebSocket) => {
        clearKeepAlive();
        keepAliveIntervalRef.current = window.setInterval(() => {
            try {
                if (ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'ping', source: 'flow_builder_run_once' }));
                }
            } catch (e) {
                console.warn('Run Once keepalive failed', e);
            }
        }, 15000);
    };

    useEffect(() => {
        const fetchHooks = async () => {
            setLoading(true);
            try {
                const hooks = await getWebhooks();
                setWebhooks(hooks);
            } catch (error) {
                console.error("Erro ao buscar webhooks", error);
            } finally {
                setLoading(false);
            }
        };
        fetchHooks();
    }, []);

    // Cleanup WS on unmount
    useEffect(() => {
        return () => {
            clearKeepAlive();
            if (wsRef.current) {
                userInitiatedCloseRef.current = true;
                wsRef.current.close();
            }
        };
    }, []);

    // Effect to handle external run once trigger (from global button)
    useEffect(() => {
        const nextRunToken = Number(data.triggerRunOnce) || 0;
        if (nextRunToken > 0 && nextRunToken !== lastRunRef.current && !isListening) {
            lastRunRef.current = nextRunToken;
            handleRunOnce(true);
        }
    }, [data.triggerRunOnce, isListening]);

    const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
        const newVal = e.target.value;
        setSelectedWebhookId(newVal);
        updateNodeData({
            webhookId: newVal,
            label: webhooks.find(w => w.id.toString() === newVal)?.name || 'Webhook Trigger',
        });
    };

    const currentWebhook = webhooks.find(w => w.id.toString() === selectedWebhookId);

    // Base WS URL construction
    const getWsUrl = (baseUrl: string) => {
        const cleanUrl = baseUrl.replace(/\/$/, '');
        if (cleanUrl.startsWith('https://')) {
            return cleanUrl.replace('https://', 'wss://');
        }
        return cleanUrl.replace('http://', 'ws://');
    };

    const handleRunOnce = (executeChain = false) => {
        shouldTriggerChainRef.current = executeChain;

        if (!selectedWebhookId) {
            void notice({
                title: 'Webhook ausente',
                message: 'Selecione um webhook antes de executar este gatilho.',
            });
            return;
        }

        // Cleanup existing connection if any
        if (wsRef.current) {
            userInitiatedCloseRef.current = true;
            wsRef.current.close();
        }
        clearKeepAlive();

        setIsListening(true);
        setIsFlowRunning(true);
        setReceivedData(null);

        // Connect WS using API_URL from env
        const wsBase = getWsUrl(API_URL);
        const companyId = resolveCompanyId(currentWebhook);
        if (!companyId) {
            void notice({
                title: 'Empresa não identificada',
                message: 'Nao foi possivel determinar a empresa para escutar este webhook no teste.',
            });
            setIsListening(false);
            setIsFlowRunning(false);
            return;
        }

        const phone = `webhook_listener_${selectedWebhookId}`;

        // Encode parameters properly
        const wsUrl = `${wsBase}/ws/chat?company_id=${encodeURIComponent(companyId.toString())}&phone=${encodeURIComponent(phone)}`;

        console.log("Connecting to WS:", wsUrl);

        try {
            const ws = new WebSocket(wsUrl);
            wsRef.current = ws;
            userInitiatedCloseRef.current = false;
            let connectionOpened = false;

            ws.onopen = () => {
                connectionOpened = true;
                console.log("Listening for webhook events... Connected!");
                startKeepAlive(ws);
            };

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    console.log("Run Once: Received event", data);
                    if ((data.type === 'message' || data.type === 'webhook_event') && data.payload) {
                        setReceivedData(data.payload);
                        setIsListening(false);
                        setIsFlowRunning(false);

                        clearKeepAlive();
                        ws.close();

                        const safePayload = data.payload;
                        const nextMapping = mergeDetectedMapping(
                            webhookMapping,
                            detectWebhookStandardMapping(safePayload)
                        );
                        setWebhookMapping(nextMapping);
                        updateNodeData({ webhookMapping: nextMapping });

                        const executionContext = buildWebhookExecutionContext(safePayload, nextMapping);

                        setNodeExecutionData(id, executionContext, shouldTriggerChainRef.current, true);
                    }
                } catch (e) {
                    console.error("Error parsing WS message", e);
                }
            };

            ws.onerror = (e) => {
                console.error("WS Error", e);
                // Do not immediately reset state on error if it's transient,
                // but for handshake failure it will close anyway.
                // Let onclose handle the state reset.
            };

            ws.onclose = (event) => {
                console.log(`WS Closed: code=${event.code}, reason=${event.reason}`);
                clearKeepAlive();
                if (!connectionOpened && !userInitiatedCloseRef.current) {
                    void notice({
                        title: 'Listener indisponível',
                        message: 'Falha ao conectar no listener do teste. Reabra o fluxo e tente novamente.',
                    });
                }
                if (isListening) {
                    setIsListening(false);
                    setIsFlowRunning(false);
                }
                userInitiatedCloseRef.current = false;
            };
        } catch (err) {
            console.error("Failed to create WebSocket", err);
            setIsListening(false);
            setIsFlowRunning(false);
        }
    };

    const handleMappingChange = (field: keyof WebhookStandardMapping, path: string) => {
        const nextMapping: WebhookStandardMapping = { ...webhookMapping, [field]: path };
        setWebhookMapping(nextMapping);
        updateNodeData({ webhookMapping: nextMapping });

        if (receivedData) {
            setNodeExecutionData(
                id,
                buildWebhookExecutionContext(receivedData, nextMapping),
                false,
                true
            );
        }
    };

    const handleCancel = () => {
        clearKeepAlive();
        if (wsRef.current) {
            userInitiatedCloseRef.current = true;
            wsRef.current.close();
        }
        setIsListening(false);
        setIsFlowRunning(false);
    };

    const handleCopyUrl = async () => {
        if (!currentWebhook) return;
        const url = getWebhookUrl(currentWebhook.uuid);
        try {
            await copyTextToClipboard(url);
            setCopySuccess(true);
            setTimeout(() => setCopySuccess(false), 2000);
        } catch (error) {
            console.error("Failed to copy webhook URL", error);
        }
    };

    const handleContextMenu = (e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setMenuPosition({ x: e.clientX, y: e.clientY });
    };

    const handleDelete = async () => {
        const confirmed = await confirm({
            confirmText: 'Excluir gatilho',
            message: 'Este gatilho e suas conexões serão removidos do fluxo.',
            title: 'Excluir webhook?',
            variant: 'danger',
        });
        if (confirmed) {
            deleteElements({ nodes: [{ id }] });
        }
    };

    const renderContent = () => {
        if (receivedData) {
            return (
                <div className="space-y-3 p-4">
                    <div className={flowNodePanelClass(isDark, 'emerald')}>
                        <div className="mb-3 flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2 text-xs font-semibold">
                                <SlidersHorizontal className="h-3.5 w-3.5" />
                                <span>Campos padrão</span>
                            </div>
                            <button
                                onClick={(e) => { e.stopPropagation(); setReceivedData(null); }}
                                className="rounded-md p-1 opacity-70 transition hover:bg-white/10 hover:opacity-100"
                            >
                                <X className="w-3 h-3" />
                            </button>
                        </div>
                        <div className="grid grid-cols-1 gap-2">
                            {WEBHOOK_STANDARD_MAPPING_FIELDS.map((field) => (
                                <div key={field.key} className="space-y-1">
                                    <div className="flex items-center justify-between gap-2">
                                        <label className={flowNodeLabelClass(isDark)}>{field.label}</label>
                                        <span className="font-mono text-[10px] opacity-60">{field.variable}</span>
                                    </div>
                                    <div className="relative">
                                        <select
                                            value={webhookMapping[field.key] || ''}
                                            onChange={(event) => handleMappingChange(field.key, event.target.value)}
                                            onMouseDown={(event) => event.stopPropagation()}
                                            className={flowNodeSelectClass(isDark)}
                                        >
                                            <option value="">Automático</option>
                                            {pathOptions.map((path) => (
                                                <option key={`${field.key}-${path}`} value={path}>
                                                    {path}
                                                </option>
                                            ))}
                                        </select>
                                        <ChevronDown className={`pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 ${isDark ? 'text-white/45' : 'text-brand/45'}`} />
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    <div
                        className="nowheel relative max-h-[180px] overflow-auto rounded-xl border border-emerald-500/20 bg-brand p-3 font-mono text-xs text-emerald-300"
                        onWheel={(e) => e.stopPropagation()}
                    >
                        <div className="mb-2 flex items-center justify-between border-b border-green-800 pb-1">
                            <span className="font-bold">Payload recebido</span>
                        </div>
                        <pre>{JSON.stringify(receivedData, null, 2)}</pre>
                    </div>
                </div>
            );
        }

        if (isListening) {
            return (
                <div className={`flex flex-col items-center gap-3 rounded-xl border-2 border-dashed p-4 ${isDark ? 'border-pink-500/50 bg-pink-500/10' : 'border-pink-300 bg-pink-50'}`}>
                    <div className="flex items-center gap-2 text-sm font-bold text-pink-500">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Aguardando evento...
                    </div>
                    <div className="text-[10px] text-center opacity-75">
                        Envie um POST para o webhook para testar.
                    </div>

                    <div className="flex gap-2">
                        <button
                            onClick={(e) => { e.stopPropagation(); handleCopyUrl(); }}
                            className={`text-[10px] px-2 py-1 rounded border flex items-center gap-1 hover:bg-white/10`}
                        >
                            {copySuccess ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                            Copiar URL
                        </button>
                        <button
                            onClick={(e) => { e.stopPropagation(); handleCancel(); }}
                            className="text-[10px] underline decoration-pink-500 underline-offset-2 hover:opacity-80"
                        >
                            Cancelar
                        </button>
                    </div>
                </div>
            );
        }

        return (
            <div className="p-4">
                <label className={flowNodeLabelClass(isDark)}>
                    Selecione o Gatilho
                </label>

                {loading ? (
                    <div className="flex items-center gap-2 text-xs text-gray-500 py-2">
                        <Loader2 className="w-3 h-3 animate-spin" /> Carregando webhooks...
                    </div>
                ) : webhooks.length === 0 ? (
                    <div className={`flex items-center gap-2 rounded-xl border p-2 text-xs ${isDark ? 'bg-red-500/10 border-red-500/20 text-red-400' : 'bg-red-50 border-red-100 text-red-600'}`}>
                        <AlertCircle className="w-3 h-3" />
                        Sem webhooks criados
                    </div>
                ) : (
                    <div className="relative">
                        <select
                            value={selectedWebhookId}
                            onChange={handleChange}
                            onClick={(e) => e.stopPropagation()}
                            onMouseDown={(e) => e.stopPropagation()} // Prevent node drag start
                            className={flowNodeSelectClass(isDark)}
                        >
                            <option value="">Selecione...</option>
                            {webhooks.map(hook => (
                                <option key={hook.id} value={hook.id}>
                                    {hook.name} {hook.is_active ? '' : '(Inativo)'}
                                </option>
                            ))}
                        </select>
                        <ChevronDown className={`absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 pointer-events-none ${isDark ? 'text-gray-400' : 'text-gray-500'}`} />
                    </div>
                )}
            </div>
        );
    };

    return (
        <div
            onContextMenu={handleContextMenu}
            className={flowNodeShellClass(isDark, selected, 'pink', 'min-w-[360px] max-w-[360px]')}
        >

            {/* Context Menu */}
            {menuPosition && (
                <NodeContextMenu
                    x={menuPosition.x}
                    y={menuPosition.y}
                    onClose={() => setMenuPosition(null)}
                    actions={[
                        { label: 'Run Once (Testar Node)', icon: <Play className="w-3 h-3" />, onClick: () => handleRunOnce(false) },

                        { label: 'Excluir', icon: <Trash2 className="w-3 h-3" />, onClick: handleDelete, danger: true }
                    ]}
                />
            )}

            <FlowNodeHeader
                icon={Webhook}
                title="Webhook"
                subtitle="Gatilho"
                tone="pink"
                meta={selectedWebhookId ? <span className={`h-2.5 w-2.5 rounded-full ${isListening ? 'bg-yellow-400 animate-pulse' : 'bg-emerald-400'}`} /> : null}
            />

            {/* Body */}
            {renderContent()}

            {/* Handle Output */}
            <FlowNodeHandle type="source" position={Position.Right} tone="pink" />
        </div>
    );
};

export default memo(WebhookNode);
