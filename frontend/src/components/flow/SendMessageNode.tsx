import React, { memo, useEffect, useState } from 'react';
import { Position, NodeProps, useReactFlow } from 'reactflow';
import { MessageSquare, Trash2, Play, Check, AlertCircle, Loader2, Image, Video, Mic, Type, Plus, X } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import { NodeContextMenu } from './NodeContextMenu.tsx';
import { VariableInput } from './VariableInput.tsx';
import { useFlowVariables } from '../../contexts/FlowVariablesContext.tsx';
import { interpolateVariables } from '../../utils/variableUtils.ts';
import { useFlowConfirm } from './FlowConfirmContext.tsx';
import {
    FlowNodeHandle,
    FlowNodeHeader,
    flowNodeLabelClass,
    flowNodePanelClass,
    flowNodeShellClass,
} from './FlowNodeChrome.tsx';
import {
    sendWhatsAppTextMultiProvider,
    sendWhatsAppImageMultiProvider,
    sendWhatsAppVideoMultiProvider,
    sendWhatsAppAudioMultiProvider,
    uploadFile,
    API_URL
} from '../../services/api';

// Interface interna para itens de mensagem
interface MessageItem {
    id: string;
    type: 'text' | 'image' | 'video' | 'audio';
    content: string;
    caption?: string;
}

const createMessageItemId = () => {
    const randomUUID = globalThis.crypto?.randomUUID;
    if (typeof randomUUID === 'function') {
        return randomUUID.call(globalThis.crypto);
    }

    return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
};

const SendMessageNode = ({ data, id, selected }: NodeProps) => {
    const { isDark } = useTheme();
    const { deleteElements } = useReactFlow();
    const { executionData, setNodeExecutionData } = useFlowVariables();
    const { confirm, notice } = useFlowConfirm();

    // -- State Initialization with Migration Logic --
    // Se data.messages existir, usa. Caso contrário, migra o formato antigo se houver conteúdo.
    const [phone, setPhone] = useState(data.phone || '');
    const [messages, setMessages] = useState<MessageItem[]>(() => {
        if (data.messages && Array.isArray(data.messages)) {
            return data.messages;
        }
        // Migration: se tem dados antigos, cria um item
        if (data.content || data.messageType) {
            return [{
                id: createMessageItemId(),
                type: data.messageType || 'text',
                content: data.content || '',
                caption: data.caption || ''
            }];
        }
        // Default: um item de texto vazio
        return [{
            id: createMessageItemId(),
            type: 'text',
            content: '',
            caption: ''
        }];
    });

    // Execution State
    const [executing, setExecuting] = useState(false);
    const [executionResult, setExecutionResult] = useState<{ success: boolean, message?: string } | null>(null);
    const [uploadingId, setUploadingId] = useState<string | null>(null); // Track which item is uploading

    // Context Menu State
    const [menuPosition, setMenuPosition] = useState<{ x: number, y: number } | null>(null);

    // Sync State to Data (Persistence)
    useEffect(() => {
        data.phone = phone;
    }, [phone, data]);

    useEffect(() => {
        data.messages = messages;
        // Limpa campos legados para evitar confusão futura (opcional, mantendo compatibilidade reversa se necessário)
        // data.content = messages[0]?.content;
        // data.messageType = messages[0]?.type;
    }, [messages, data]);


    // Chain Execution Trigger
    const lastRunRef = React.useRef<number>(data.triggerRunOnce || 0);
    useEffect(() => {
        if (data.triggerRunOnce && data.triggerRunOnce !== lastRunRef.current && executing !== true) {
            console.log("External trigger received for SendMessageNode:", id);
            lastRunRef.current = data.triggerRunOnce;
            handleRunOnce(true);
        }
    }, [data.triggerRunOnce, executing]);

    // -- Handlers for Messages --

    const handleAddMessage = () => {
        setMessages(prev => [
            ...prev,
            { id: createMessageItemId(), type: 'text', content: '' }
        ]);
    };

    const handleRemoveMessage = (itemId: string) => {
        if (messages.length <= 1) {
            // Se for o único, apenas limpa
            setMessages(prev => prev.map(m => m.id === itemId ? { ...m, content: '', caption: '' } : m));
            return;
        }
        setMessages(prev => prev.filter(m => m.id !== itemId));
    };

    const updateMessage = (itemId: string, updates: Partial<MessageItem>) => {
        setMessages(prev => prev.map(m => m.id === itemId ? { ...m, ...updates } : m));
    };

    const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>, itemId: string) => {
        const file = e.target.files?.[0];
        if (!file) return;

        setUploadingId(itemId);
        try {
            console.log("Uploading file:", file.name);
            const response = await uploadFile(file);
            console.log("Upload success:", response);
            // Salva o path relativo retornado
            updateMessage(itemId, { content: response.path });
        } catch (error) {
            console.error("Upload error:", error);
            await notice({
                title: 'Upload não concluído',
                message: 'Nao foi possivel enviar o arquivo para esta mensagem.',
            });
        } finally {
            setUploadingId(null);
            e.target.value = '';
        }
    };

    // -- Execution Logic --

    const handleRunOnce = async (executeChain = false) => {
        if (!phone) {
            await notice({
                title: 'Telefone ausente',
                message: 'Preencha o telefone do destinatário antes de testar o envio.',
            });
            return;
        }

        // Valida se tem conteúdo
        const hasContent = messages.some(m => m.content && m.content.trim() !== '');
        if (!hasContent) {
            await notice({
                title: 'Conteúdo ausente',
                message: 'Adicione pelo menos uma mensagem com conteúdo antes de testar.',
            });
            return;
        }

        setExecuting(true);
        setExecutionResult(null);

        try {
            const finalPhone = interpolateVariables(phone, executionData).replace(/\D/g, '');

            // Sequentially send messages
            for (let i = 0; i < messages.length; i++) {
                const msg = messages[i];
                if (!msg.content) continue;

                const finalContent = interpolateVariables(msg.content, executionData, { nameMode: 'first_name_for_messages' });
                const finalCaption = msg.caption
                    ? interpolateVariables(msg.caption, executionData, { nameMode: 'first_name_for_messages' })
                    : undefined;

                console.log(`[SendMessageNode] Sending item ${i + 1}/${messages.length} (${msg.type}) to ${finalPhone}`);

                // Pequeno delay entre mensagens para garantir ordem (opcional, mas recomendado para WhatsApp)
                if (i > 0) await new Promise(r => setTimeout(r, 500));

                if (msg.type === 'text') {
                    await sendWhatsAppTextMultiProvider({
                        phone: finalPhone,
                        message: finalContent
                    });
                } else if (msg.type === 'image') {
                    await sendWhatsAppImageMultiProvider({
                        phone: finalPhone,
                        image: finalContent,
                        caption: finalCaption
                    });
                } else if (msg.type === 'video') {
                    await sendWhatsAppVideoMultiProvider({
                        phone: finalPhone,
                        video: finalContent,
                        caption: finalCaption
                    });
                } else if (msg.type === 'audio') {
                    await sendWhatsAppAudioMultiProvider({
                        phone: finalPhone,
                        audio: finalContent
                    });
                }
            }

            setNodeExecutionData(id, { success: true, count: messages.length }, executeChain);
            setExecutionResult({ success: true, message: `${messages.length} mensage(ns) enviada(s)!` });

        } catch (error: any) {
            console.error("SendMessage Error", error);
            let errorMessage = "Erro ao enviar mensagem";
            if (error.response?.data?.detail) {
                errorMessage = error.response.data.detail;
            } else if (error.message) {
                errorMessage = error.message;
            }
            setExecutionResult({ success: false, message: errorMessage });
        } finally {
            setExecuting(false);
        }
    };

    // -- Helper Render --
    const getIcon = (type: string) => {
        switch (type) {
            case 'image': return <Image className="w-3 h-3" />;
            case 'video': return <Video className="w-3 h-3" />;
            case 'audio': return <Mic className="w-3 h-3" />;
            default: return <Type className="w-3 h-3" />;
        }
    };

    const getPreviewUrl = (content: string) => {
        try {
            if (content.startsWith('http') || content.startsWith('data:')) return content;
            const parts = content.split('/');
            // Expect relative path: client_X/company_Y/type/filename
            if (parts.length >= 4) {
                const clientId = parts[0].split('_')[1];
                const companyId = parts[1].split('_')[1];
                const fileName = parts[3];
                return `${API_URL}/api/arquivos/files/view/${companyId}/${clientId}/${fileName}`;
            }
            return content;
        } catch (e) { return content; }
    };

    // -- Main Render --
    return (
        <div
            onContextMenu={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setMenuPosition({ x: e.clientX, y: e.clientY });
            }}
            className={flowNodeShellClass(isDark, selected, 'purple')}
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
                                    confirmText: 'Excluir node',
                                    message: 'Este node e suas conexões serão removidos do fluxo.',
                                    title: 'Excluir mensagem WhatsApp?',
                                    variant: 'danger',
                                });
                                if (confirmed) deleteElements({ nodes: [{ id }] });
                            },
                            danger: true
                        },
                        { label: 'Testar Envio', icon: <Play className="w-3 h-3" />, onClick: () => handleRunOnce(false) }
                    ]}
                />
            )}

            <FlowNodeHeader
                icon={MessageSquare}
                title="Msg WhatsApp"
                subtitle="Ação"
                tone="purple"
                meta={<span className="rounded-full border border-white/15 bg-white/10 px-2 py-0.5 text-[10px] font-semibold text-white/75">{messages.length}</span>}
            />

            {/* Status */}
            {executing && (
                <div className="px-4 py-2 bg-yellow-500/10 text-yellow-500 text-xs flex items-center gap-2 animate-pulse border-b border-yellow-500/20">
                    <Loader2 className="w-3 h-3 animate-spin" /> Enviando sequência...
                </div>
            )}
            {executionResult && !executing && (
                <div className={`px-4 py-2 text-xs flex items-center gap-2 border-b ${executionResult.success ? 'bg-green-500/10 text-green-500 border-green-500/20' : 'bg-red-500/10 text-red-500 border-red-500/20'}`}>
                    {executionResult.success ? <Check className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
                    <span className="truncate">{executionResult.message}</span>
                </div>
            )}

            {/* Content */}
            <div
                className="p-4 space-y-4 max-h-[600px] overflow-y-auto custom-scrollbar nowheel"
                onWheel={(e) => e.stopPropagation()}
            >
                {/* Global Phone Input */}
                <VariableInput
                    label="Telefone do Destinatário"
                    value={phone}
                    onChange={(val) => setPhone(val)}
                    placeholder="{{trigger.phone}} ou 5511999..."
                />

                <div className="space-y-3">
                    <label className={flowNodeLabelClass(isDark)}>
                        Mensagens
                    </label>

                    {messages.map((msg, index) => (
                        <div key={msg.id} className={`${flowNodePanelClass(isDark)} relative group`}>
                            {/* Remove Button */}
                            <button
                                onClick={() => handleRemoveMessage(msg.id)}
                                className="absolute top-2 right-2 p-1 text-gray-400 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-all"
                                title="Remover mensagem"
                            >
                                <X className="w-3 h-3" />
                            </button>

                            {/* Type Selector */}
                            <div className="flex items-center gap-2 mb-3">
                                <div className={`rounded-lg border p-1.5 ${isDark ? 'border-white/10 bg-black/20' : 'border-brand/10 bg-white'}`}>
                                    {getIcon(msg.type)}
                                </div>
                                <select
                                    value={msg.type}
                                    onChange={(e) => updateMessage(msg.id, { type: e.target.value as any, content: '', caption: '' })}
                                    className={`flex-1 border-none bg-transparent text-xs font-medium outline-none ${isDark ? 'text-white' : 'text-brand'}`}
                                >
                                    <option value="text">Texto</option>
                                    <option value="image">Imagem</option>
                                    <option value="video">Vídeo</option>
                                    <option value="audio">Áudio</option>
                                </select>
                                <span className="text-[10px] text-gray-400 font-mono">#{index + 1}</span>
                            </div>

                            {/* Content Input */}
                            {msg.type === 'text' ? (
                                <VariableInput
                                    label=""
                                    value={msg.content}
                                    onChange={(val) => updateMessage(msg.id, { content: val })}
                                    placeholder="Digite a mensagem..."
                                    isTextArea={true}
                                />
                            ) : (
                                <div className="space-y-2">
                                    {msg.content ? (
                                        <div className={`rounded-lg overflow-hidden border ${isDark ? 'border-gray-600 bg-black/20' : 'border-gray-300 bg-gray-100'}`}>
                                            {/* Preview */}
                                            {msg.type === 'image' && (
                                                <div className="aspect-video relative">
                                                    <img src={getPreviewUrl(msg.content)} alt="preview" className="w-full h-full object-cover" />
                                                </div>
                                            )}
                                            {msg.type === 'video' && (
                                                <div className="aspect-video relative bg-black">
                                                    <video src={getPreviewUrl(msg.content)} controls className="w-full h-full" />
                                                </div>
                                            )}
                                            {msg.type === 'audio' && (
                                                <div className="p-3 flex justify-center">
                                                    <audio src={getPreviewUrl(msg.content)} controls className="w-full" />
                                                </div>
                                            )}

                                            <div className="p-2 flex items-center justify-between gap-2 border-t border-gray-600/20">
                                                <p className="text-[10px] truncate max-w-[150px] opacity-70">
                                                    {msg.content.split('/').pop()}
                                                </p>
                                                <button onClick={() => updateMessage(msg.id, { content: '' })} className="text-xs text-red-400 hover:text-red-500">Trocar</button>
                                            </div>
                                        </div>
                                    ) : (
                                        <div className="flex gap-2">
                                            <input
                                                type="file"
                                                id={`file-upload-${msg.id}`}
                                                className="hidden"
                                                accept={msg.type === 'image' ? "image/*" : msg.type === 'video' ? "video/*" : "audio/*"}
                                                onChange={(e) => handleFileUpload(e, msg.id)}
                                            />
                                            <button
                                                onClick={() => document.getElementById(`file-upload-${msg.id}`)?.click()}
                                                disabled={uploadingId === msg.id}
                                                className={`w-full py-6 rounded-lg border-2 border-dashed flex flex-col items-center justify-center gap-2 transition-colors ${isDark ? 'border-gray-600 hover:border-purple-500/50 hover:bg-gray-700/50' : 'border-gray-300 hover:border-purple-500/50 hover:bg-gray-50'
                                                    }`}
                                            >
                                                {uploadingId === msg.id ? (
                                                    <Loader2 className="w-4 h-4 animate-spin text-purple-500" />
                                                ) : (
                                                    <>
                                                        {getIcon(msg.type)}
                                                        <span className="text-[10px] opacity-70">Upload {msg.type}</span>
                                                    </>
                                                )}
                                            </button>
                                        </div>
                                    )}

                                    {/* Caption for Media */}
                                    {(msg.type === 'image' || msg.type === 'video') && (
                                        <VariableInput
                                            label="Legenda"
                                            value={msg.caption || ''}
                                            onChange={(val) => updateMessage(msg.id, { caption: val })}
                                            placeholder="Legenda da mídia..."
                                        />
                                    )}
                                </div>
                            )}
                        </div>
                    ))}

                    <button
                        onClick={handleAddMessage}
                        className={`w-full py-2 flex items-center justify-center gap-2 text-xs font-medium rounded-lg border border-dashed transition-all ${isDark
                            ? 'border-gray-600 text-gray-400 hover:text-purple-400 hover:border-purple-500/50 hover:bg-purple-500/10'
                            : 'border-gray-300 text-gray-500 hover:text-purple-600 hover:border-purple-500/50 hover:bg-purple-50'
                            }`}
                    >
                        <Plus className="w-3 h-3" />
                        Adicionar Mensagem
                    </button>
                </div>
            </div>

            <FlowNodeHandle type="target" position={Position.Left} tone="purple" />
            <FlowNodeHandle type="source" position={Position.Right} tone="purple" />
        </div>
    );
};

export default memo(SendMessageNode);
