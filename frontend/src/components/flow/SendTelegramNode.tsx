import React, { memo, useEffect, useState } from 'react';
import { Position, NodeProps, useReactFlow } from 'reactflow';
import { Send, Trash2, Play, Check, AlertCircle, Loader2, ExternalLink, RefreshCw } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import { NodeContextMenu } from './NodeContextMenu.tsx';
import { VariableInput } from './VariableInput.tsx';
import { useFlowVariables } from '../../contexts/FlowVariablesContext.tsx';
import { interpolateVariables } from '../../utils/variableUtils.ts';
import api, { getTelegramIntegration, type TelegramIntegration } from '../../services/api.ts';
import { useFlowConfirm } from './FlowConfirmContext.tsx';
import {
    FlowNodeHandle,
    FlowNodeHeader,
    flowNodeLabelClass,
    flowNodeSelectClass,
    flowNodeShellClass,
} from './FlowNodeChrome.tsx';

const DEFAULT_MESSAGE_TEMPLATE = `🚀 <b>Novo Lead Capturado!</b>

👤 <b>Nome:</b> {{name}}
📧 <b>Email:</b> {{email}}
📱 <b>WhatsApp:</b> {{phone}}

🔗 <i>Origem: {{source}}</i>`;

const SendTelegramNode = ({ data, id, selected }: NodeProps) => {
    const { isDark } = useTheme();
    const { deleteElements } = useReactFlow();
    const { executionData, setNodeExecutionData } = useFlowVariables();
    const { confirm, notice } = useFlowConfirm();

    const [chatId, setChatId] = useState(data.chatId || '');
    const [message, setMessage] = useState(data.message || DEFAULT_MESSAGE_TEMPLATE);
    const [parseMode, setParseMode] = useState(data.parseMode || 'HTML');
    const [disablePreview, setDisablePreview] = useState(
        data.disableWebPagePreview !== undefined ? Boolean(data.disableWebPagePreview) : true
    );
    const [telegramIntegration, setTelegramIntegration] = useState<TelegramIntegration | null>(null);
    const [loadingIntegration, setLoadingIntegration] = useState(true);

    const [executing, setExecuting] = useState(false);
    const [executionResult, setExecutionResult] = useState<{ success: boolean; message?: string } | null>(null);
    const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null);

    useEffect(() => {
        data.chatId = chatId;
    }, [chatId, data]);

    useEffect(() => {
        data.message = message;
    }, [message, data]);

    useEffect(() => {
        data.parseMode = parseMode;
    }, [parseMode, data]);

    useEffect(() => {
        data.disableWebPagePreview = disablePreview;
    }, [disablePreview, data]);

    const loadTelegramIntegration = async () => {
        setLoadingIntegration(true);
        try {
            const integration = await getTelegramIntegration();
            setTelegramIntegration(integration);
        } catch (error) {
            console.error('Failed to load Telegram integration', error);
            setTelegramIntegration(null);
        } finally {
            setLoadingIntegration(false);
        }
    };

    useEffect(() => {
        loadTelegramIntegration();
    }, []);

    const lastRunRef = React.useRef<number>(data.triggerRunOnce || 0);
    useEffect(() => {
        if (data.triggerRunOnce && data.triggerRunOnce !== lastRunRef.current && executing !== true) {
            lastRunRef.current = data.triggerRunOnce;
            handleRunOnce(true);
        }
    }, [data.triggerRunOnce, executing]);

    const handleRunOnce = async (executeChain = false) => {
        if (!message || !message.trim()) {
            await notice({
                title: 'Mensagem ausente',
                message: 'Preencha a mensagem do Telegram antes de testar este node.',
            });
            return;
        }

        if (!telegramIntegration?.configured) {
            await notice({
                title: 'Telegram não configurado',
                message: 'Configure a integração Telegram da empresa antes de testar este node.',
            });
            return;
        }

        setExecuting(true);
        setExecutionResult(null);

        try {
            const finalMessage = interpolateVariables(message, executionData);
            const finalChatId = chatId ? interpolateVariables(chatId, executionData).trim() : '';
            const finalParseMode = parseMode === 'none' ? null : parseMode;

            const { data: result } = await api.post('/api/flows/run-telegram', {
                message: finalMessage,
                chat_id: finalChatId || undefined,
                parse_mode: finalParseMode,
                disable_web_page_preview: disablePreview,
            });

            if (!result.success) {
                throw new Error(result.detail || result.error || 'Erro ao enviar mensagem no Telegram');
            }

            setNodeExecutionData(id, {
                success: true,
                telegram_message_id: result.message_id,
                telegram_chat_id: result.chat_id,
                message: finalMessage,
            }, executeChain);

            setExecutionResult({
                success: true,
                message: `Mensagem enviada (chat ${result.chat_id})`,
            });
        } catch (error: any) {
            setExecutionResult({
                success: false,
                message: error?.message || 'Falha ao enviar no Telegram',
            });
        } finally {
            setExecuting(false);
        }
    };

    return (
        <div
            onContextMenu={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setMenuPosition({ x: e.clientX, y: e.clientY });
            }}
            className={flowNodeShellClass(isDark, selected, 'sky')}
        >
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
                                    confirmText: 'Excluir node',
                                    message: 'Este node e suas conexões serão removidos do fluxo.',
                                    title: 'Excluir mensagem Telegram?',
                                    variant: 'danger',
                                });
                                if (confirmed) deleteElements({ nodes: [{ id }] });
                            },
                            danger: true
                        },
                        { label: 'Testar Telegram', icon: <Play className="w-3 h-3" />, onClick: () => handleRunOnce(false) }
                    ]}
                />
            )}

            <FlowNodeHeader icon={Send} title="Msg Telegram" subtitle="Notificação" tone="sky" />

            {executing && (
                <div className="px-4 py-2 bg-yellow-500/10 text-yellow-500 text-xs flex items-center gap-2 animate-pulse border-b border-yellow-500/20">
                    <Loader2 className="w-3 h-3 animate-spin" /> Enviando no Telegram...
                </div>
            )}
            {executionResult && !executing && (
                <div className={`px-4 py-2 text-xs flex items-center gap-2 border-b ${executionResult.success ? 'bg-green-500/10 text-green-500 border-green-500/20' : 'bg-red-500/10 text-red-500 border-red-500/20'}`}>
                    {executionResult.success ? <Check className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
                    <span className="truncate">{executionResult.message}</span>
                </div>
            )}

            <div
                className="p-4 space-y-4 max-h-[420px] overflow-y-auto custom-scrollbar nowheel"
                onWheel={(e) => e.stopPropagation()}
            >
                {loadingIntegration ? (
                    <div className={`flex items-center gap-2 rounded-xl border p-3 text-xs ${isDark ? 'border-white/10 bg-white/[0.04] text-white/60' : 'border-brand/10 bg-brand-canvas text-brand/60'}`}>
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Verificando integração...
                    </div>
                ) : telegramIntegration?.configured ? (
                    <div className={`rounded-xl border p-3 text-xs ${isDark ? 'border-emerald-400/20 bg-emerald-400/10 text-emerald-100' : 'border-emerald-200 bg-emerald-50 text-emerald-800'}`}>
                        <div className="flex items-center justify-between gap-2">
                            <span className="font-semibold">
                                Telegram configurado
                            </span>
                            <button
                                type="button"
                                onClick={loadTelegramIntegration}
                                className="nodrag rounded-lg p-1 transition hover:bg-current/10"
                                aria-label="Atualizar status Telegram"
                            >
                                <RefreshCw className="h-3.5 w-3.5" />
                            </button>
                        </div>
                        <p className="mt-1 truncate opacity-80">
                            {telegramIntegration.bot_username ? `@${telegramIntegration.bot_username}` : telegramIntegration.bot_name || 'Bot validado'}
                            {telegramIntegration.default_chat_title || telegramIntegration.default_chat_id
                                ? ` · ${telegramIntegration.default_chat_title || telegramIntegration.default_chat_id}`
                                : ''}
                        </p>
                    </div>
                ) : (
                    <div className={`rounded-xl border p-3 text-xs ${isDark ? 'border-amber-400/25 bg-amber-400/10 text-amber-100' : 'border-amber-200 bg-amber-50 text-amber-800'}`}>
                        <div className="flex items-start gap-2">
                            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                            <div className="min-w-0 flex-1">
                                <p className="font-semibold">Telegram precisa ser configurado</p>
                                <p className="mt-1 leading-snug opacity-80">Este node usa a integração da empresa ativa.</p>
                                <a
                                    href="/integrations/telegram"
                                    target="_blank"
                                    rel="noreferrer"
                                    className="nodrag mt-2 inline-flex items-center gap-1 rounded-lg bg-brand px-2.5 py-1.5 font-semibold text-white"
                                >
                                    Configurar
                                    <ExternalLink className="h-3.5 w-3.5" />
                                </a>
                            </div>
                        </div>
                    </div>
                )}

                <VariableInput
                    label="Chat ID (Opcional)"
                    value={chatId}
                    onChange={setChatId}
                    placeholder="Ex: -1001234567890 (se vazio usa o padrão da empresa)"
                    disableVariables={false}
                />

                <div className="space-y-1">
                    <label className={flowNodeLabelClass(isDark)}>
                        Parse Mode
                    </label>
                    <select
                        value={parseMode}
                        onChange={(e) => setParseMode(e.target.value)}
                        className={flowNodeSelectClass(isDark)}
                    >
                        <option value="HTML">HTML</option>
                        <option value="MarkdownV2">MarkdownV2</option>
                        <option value="Markdown">Markdown</option>
                        <option value="none">Sem parse</option>
                    </select>
                </div>

                <label className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-xs ${isDark ? 'border-white/10 bg-white/[0.04] text-white/65' : 'border-brand/10 bg-brand-canvas text-brand/65'}`}>
                    <input
                        type="checkbox"
                        checked={disablePreview}
                        onChange={(e) => setDisablePreview(e.target.checked)}
                        className="rounded"
                    />
                    Desabilitar preview de link
                </label>

                <VariableInput
                    label="Mensagem"
                    value={message}
                    onChange={setMessage}
                    isTextArea
                    placeholder="Digite a mensagem com variáveis..."
                />
            </div>

            <FlowNodeHandle type="target" position={Position.Left} tone="sky" />
            <FlowNodeHandle type="source" position={Position.Right} tone="sky" />
        </div>
    );
};

export default memo(SendTelegramNode);
