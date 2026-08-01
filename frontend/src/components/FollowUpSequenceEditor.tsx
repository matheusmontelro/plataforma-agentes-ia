import React, { useState, useEffect } from 'react';
import {
    uploadFile,
    getFileUrl,
    createFollowUpSequence,
    getSingleFollowUpSequence,
    updateFollowUpSequence,
    deleteFile,
    FollowUpSequenceCreate,
    FollowUpSequenceUpdate,
    FollowUpStepUpdate,
    FollowUpMessageUpdate
} from '../services/api';
import {
    Trash2,
    Edit2,
    Plus,
    MessageCircle,
    Check,
    Image as ImageIcon,
    Video,
    Music,
    Type,
    AlertCircle,
    Save,
    X
} from 'lucide-react';

// ---------------------------
// Tipos internos do Componente
// ---------------------------
interface MensagemLocal {
    id?: number;
    type: 'text' | 'image' | 'audio' | 'video';
    content: string | File | any;
}

interface PassoLocal {
    id?: number;
    step_number: number;
    send_after: number;
    send_after_unit: 'days' | 'hours' | 'minutes';
    messages: MensagemLocal[];
}

interface FollowUpSequenceEditorProps {
    companyId: number;
    sequenceId?: number | null; // Se null, é criação
    linkedStageId?: number;     // Para vincular automaticamente na criação
    onSave?: (newSequenceId: number) => void;
    onCancel?: () => void;
}

const MAX_PASSOS = 10;
const MAX_MENSAGENS_POR_PASSO = 3;

const LIMITE_ARQUIVOS: Record<string, number> = {
    image: 2 * 1024 * 1024,   // 2MB
    audio: 5 * 1024 * 1024,  // 5MB
    video: 5 * 1024 * 1024,  // 5MB
};

// Função auxiliar para verificar se é arquivo
function isFile(value: any): boolean {
    return (
        typeof value === 'object' &&
        value !== null &&
        'name' in value &&
        'size' in value &&
        'type' in value
    );
}

// Preview simples de arquivo
const PreviewArquivo = ({ tipo, conteudo }: { tipo: string; conteudo: string | File | any }) => {
    if (isFile(conteudo)) {
        return (
            <div className="bg-amber-50 border-l-4 border-amber-400 p-3 rounded-md my-2">
                <p className="text-sm text-amber-700 flex items-center">
                    <AlertCircle className="w-4 h-4 mr-2" />
                    Arquivo pendente de upload. Será enviado ao salvar.
                </p>
            </div>
        );
    }

    if (typeof conteudo !== 'string') {
        return (
            <div className="bg-red-50 border-l-4 border-red-400 p-3 rounded-md my-2">
                <p className="text-sm text-red-700 flex items-center">
                    <AlertCircle className="w-4 h-4 mr-2" />
                    Formato inválido
                </p>
            </div>
        );
    }

    const companyId = Number((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')));
    const clientId = Number(localStorage.getItem('client_id'));
    const fileName = conteudo.split('/').pop() || '';
    const url = getFileUrl(companyId, clientId, fileName);

    if (tipo === 'image') {
        return (
            <div className="mt-2 rounded-lg overflow-hidden">
                <img src={url} alt="Preview" className="w-full max-h-48 object-cover rounded-lg" />
            </div>
        );
    }
    if (tipo === 'audio') {
        return (
            <div className="bg-slate-50 p-3 rounded-lg mt-2">
                <audio controls className="w-full">
                    <source src={url} type="audio/mpeg" />
                </audio>
            </div>
        );
    }
    if (tipo === 'video') {
        return (
            <div className="mt-2 rounded-lg overflow-hidden">
                <video controls className="w-full max-h-48 rounded-lg">
                    <source src={url} type="video/mp4" />
                </video>
            </div>
        );
    }
    return null;
};

export default function FollowUpSequenceEditor({
    companyId,
    sequenceId,
    linkedStageId,
    onSave,
    onCancel
}: FollowUpSequenceEditorProps) {
    const [passos, setPassos] = useState<PassoLocal[]>([]);
    const [editandoPasso, setEditandoPasso] = useState<PassoLocal | null>(null);
    const [nomeSequencia, setNomeSequencia] = useState('Nova Sequência');

    const [erro, setErro] = useState<string | null>(null);
    const [sucesso, setSucesso] = useState<string | null>(null);
    const [carregando, setCarregando] = useState(false);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (sequenceId) {
            carregarSequencia(sequenceId);
        } else {
            // Reset para criação
            setPassos([]);
            setNomeSequencia('Nova Sequência');
        }
    }, [sequenceId]);

    const carregarSequencia = async (id: number) => {
        try {
            setCarregando(true);
            const seq = await getSingleFollowUpSequence(id);
            if (seq) {
                setNomeSequencia(seq.name);
                const passosConvertidos: PassoLocal[] = seq.steps.map((step: any) => ({
                    id: step.id,
                    step_number: step.step_number,
                    send_after: step.send_after,
                    send_after_unit: step.send_after_unit as 'days' | 'hours' | 'minutes',
                    messages: step.messages.map((msg: any) => ({
                        id: msg.id,
                        type: msg.type as 'text' | 'image' | 'audio' | 'video',
                        content: msg.content,
                    })),
                }));
                passosConvertidos.sort((a, b) => (a.id ?? 0) - (b.id ?? 0));
                setPassos(passosConvertidos);
            }
        } catch (error) {
            console.error(error);
            setErro('Erro ao carregar sequência.');
        } finally {
            setCarregando(false);
        }
    };

    const salvarConfig = async () => {
        try {
            setSaving(true);
            const clientIdStr = localStorage.getItem('client_id');
            if (!clientIdStr) throw new Error('Client ID não encontrado');

            // 1. Upload de arquivos e conversão para API
            const passosAPI = await Promise.all(
                passos.map(async (passoLocal) => {
                    const messagesSorted = passoLocal.messages.slice().sort((a, b) => (a.id ?? 0) - (b.id ?? 0));

                    const messagesAPI = await Promise.all(
                        messagesSorted.map(async (msgLocal) => {
                            if (msgLocal.type !== 'text' && isFile(msgLocal.content)) {
                                const file = msgLocal.content as File;
                                const limite = LIMITE_ARQUIVOS[msgLocal.type];
                                if (file.size > limite) {
                                    throw new Error(`Arquivo muito grande para ${msgLocal.type}`);
                                }
                                const uploadRes = await uploadFile(file);
                                return {
                                    id: msgLocal.id,
                                    type: msgLocal.type,
                                    content: uploadRes.path
                                } as FollowUpMessageUpdate;
                            } else {
                                return {
                                    id: msgLocal.id,
                                    type: msgLocal.type,
                                    content: msgLocal.content
                                } as FollowUpMessageUpdate;
                            }
                        })
                    );

                    return {
                        id: passoLocal.id,
                        step_number: passoLocal.step_number,
                        send_after: passoLocal.send_after,
                        send_after_unit: passoLocal.send_after_unit,
                        messages: messagesAPI
                    } as FollowUpStepUpdate;
                })
            );

            // 2. Payload
            const payloadBase = {
                company_id: companyId,
                client_id: clientIdStr,
                name: nomeSequencia,
                description: 'Sequência configurada via Kanban',
                steps: passosAPI
            };

            let newId = sequenceId;

            if (sequenceId) {
                // Update
                await updateFollowUpSequence(sequenceId, payloadBase);
                setSucesso('Sequência atualizada!');
            } else {
                // Create
                const createPayload: FollowUpSequenceCreate = {
                    ...payloadBase,
                    linked_stage_id: linkedStageId // Passa o stage ID para vincular
                };
                const res = await createFollowUpSequence(companyId, createPayload);
                newId = res.sequence_id;
                setSucesso('Sequência criada!');
            }

            if (onSave && newId) {
                onSave(newId);
            }
        } catch (err: any) {
            console.error(err);
            setErro(err.message || 'Erro ao salvar sequência');
        } finally {
            setSaving(false);
        }
    };

    // --- Manipulação de Passos ---
    const adicionarPasso = () => {
        if (passos.length >= MAX_PASSOS) return;
        const novo: PassoLocal = {
            step_number: passos.length + 1,
            send_after: 1,
            send_after_unit: 'days',
            messages: []
        };
        setPassos([...passos, novo]);
        setEditandoPasso(novo);
    };

    const editarPasso = (stepNumber: number) => {
        const p = passos.find(x => x.step_number === stepNumber);
        if (p) setEditandoPasso({ ...p });
    };

    const atualizarPassoLocal = (atualizado: PassoLocal) => {
        setPassos(prev => prev.map(p => p.step_number === atualizado.step_number ? atualizado : p));
        setEditandoPasso(atualizado);
    };

    // --- Manipulação de Mensagens ---
    const adicionarMensagem = () => {
        if (!editandoPasso) return;
        if (editandoPasso.messages.length >= MAX_MENSAGENS_POR_PASSO) return;

        const novaMsg: MensagemLocal = { type: 'text', content: '' };
        const novoPasso = {
            ...editandoPasso,
            messages: [...editandoPasso.messages, novaMsg]
        };
        atualizarPassoLocal(novoPasso);
    };

    const removerMensagem = (idx: number) => {
        if (!editandoPasso) return;
        const novasMsgs = [...editandoPasso.messages];
        novasMsgs.splice(idx, 1);
        atualizarPassoLocal({ ...editandoPasso, messages: novasMsgs });
    };

    const alterarMensagem = (idx: number, campo: 'type' | 'content', valor: any) => {
        if (!editandoPasso) return;
        const novasMsgs = [...editandoPasso.messages];
        novasMsgs[idx] = { ...novasMsgs[idx], [campo]: valor };
        // Se mudou tipo, limpa conteúdo se for incompatível (opcional, mas bom pra UX)
        if (campo === 'type') novasMsgs[idx].content = '';
        atualizarPassoLocal({ ...editandoPasso, messages: novasMsgs });
    };

    if (carregando) return <div className="p-8 text-center">Carregando sequência...</div>;

    return (
        <div className="bg-white rounded-lg p-6 max-w-4xl w-full mx-auto">
            <div className="flex justify-between items-center mb-6">
                <div className="flex-1">
                    <label className="block text-sm font-medium text-gray-700 mb-1">Nome da Sequência</label>
                    <input
                        type="text"
                        value={nomeSequencia}
                        onChange={(e) => setNomeSequencia(e.target.value)}
                        className="text-xl font-bold text-slate-800 border-b border-gray-300 focus:border-blue-500 outline-none w-full"
                    />
                </div>
                <button onClick={onCancel} className="text-gray-500 hover:text-gray-700 ml-4">
                    <X className="w-6 h-6" />
                </button>
            </div>

            {erro && (
                <div className="bg-red-50 text-red-700 p-3 rounded mb-4 flex items-center">
                    <AlertCircle className="w-5 h-5 mr-2" /> {erro}
                </div>
            )}
            {sucesso && (
                <div className="bg-green-50 text-green-700 p-3 rounded mb-4 flex items-center">
                    <Check className="w-5 h-5 mr-2" /> {sucesso}
                </div>
            )}

            <div className="flex gap-6">
                {/* Timeline (Esquerda) */}
                <div className="w-1/3 border-r pr-6">
                    <div className="space-y-4">
                        {passos.map((p, idx) => (
                            <div
                                key={idx}
                                onClick={() => editarPasso(p.step_number)}
                                className={`p-3 rounded-lg cursor-pointer border transition-colors ${editandoPasso?.step_number === p.step_number
                                        ? 'bg-blue-50 border-blue-500'
                                        : 'bg-white border-gray-200 hover:border-blue-300'
                                    }`}
                            >
                                <div className="flex justify-between items-center mb-1">
                                    <span className="font-bold text-slate-700">Passo {p.step_number}</span>
                                    <span className="text-xs text-slate-500 bg-slate-100 px-2 py-1 rounded">
                                        {p.send_after} {p.send_after_unit}
                                    </span>
                                </div>
                                <div className="text-sm text-slate-500 flex items-center">
                                    <MessageCircle className="w-3 h-3 mr-1" />
                                    {p.messages.length} mensagens
                                </div>
                            </div>
                        ))}

                        {passos.length < MAX_PASSOS && (
                            <button
                                onClick={adicionarPasso}
                                className="w-full py-2 border-2 border-dashed border-slate-300 rounded-lg text-slate-500 hover:border-blue-500 hover:text-blue-500 transition-colors flex items-center justify-center gap-2"
                            >
                                <Plus className="w-4 h-4" /> Adicionar Passo
                            </button>
                        )}
                    </div>
                </div>

                {/* Editor (Direita) */}
                <div className="w-2/3">
                    {editandoPasso ? (
                        <div className="bg-slate-50 p-4 rounded-lg border border-slate-200">
                            <h3 className="font-bold text-lg mb-4 flex items-center gap-2">
                                <Edit2 className="w-4 h-4" /> Editando Passo {editandoPasso.step_number}
                            </h3>

                            {/* Config de Tempo */}
                            <div className="flex gap-4 mb-6 bg-white p-3 rounded border border-gray-200">
                                <div className="flex-1">
                                    <label className="block text-xs font-medium text-gray-500 mb-1">Enviar após</label>
                                    <input
                                        type="number"
                                        min="1"
                                        value={editandoPasso.send_after}
                                        onChange={(e) => atualizarPassoLocal({ ...editandoPasso, send_after: parseInt(e.target.value) || 1 })}
                                        className="w-full p-2 border rounded"
                                    />
                                </div>
                                <div className="flex-1">
                                    <label className="block text-xs font-medium text-gray-500 mb-1">Unidade</label>
                                    <select
                                        value={editandoPasso.send_after_unit}
                                        onChange={(e) => atualizarPassoLocal({ ...editandoPasso, send_after_unit: e.target.value as any })}
                                        className="w-full p-2 border rounded"
                                    >
                                        <option value="minutes">Minutos</option>
                                        <option value="hours">Horas</option>
                                        <option value="days">Dias</option>
                                    </select>
                                </div>
                            </div>

                            {/* Mensagens */}
                            <div className="space-y-4">
                                {editandoPasso.messages.map((msg, idx) => (
                                    <div key={idx} className="bg-white p-3 rounded border border-gray-200 relative group">
                                        <button
                                            onClick={() => removerMensagem(idx)}
                                            className="absolute top-2 right-2 text-gray-400 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
                                        >
                                            <Trash2 className="w-4 h-4" />
                                        </button>

                                        <div className="mb-2">
                                            <div className="flex gap-2 text-sm mb-2">
                                                {[
                                                    { id: 'text', icon: Type, label: 'Texto' },
                                                    { id: 'image', icon: ImageIcon, label: 'Imagem' },
                                                    { id: 'audio', icon: Music, label: 'Áudio' },
                                                    { id: 'video', icon: Video, label: 'Vídeo' }
                                                ].map(type => (
                                                    <button
                                                        key={type.id}
                                                        onClick={() => alterarMensagem(idx, 'type', type.id)}
                                                        className={`p-1 px-2 rounded flex items-center gap-1 ${msg.type === type.id ? 'bg-blue-100 text-blue-700' : 'text-gray-500 hover:bg-gray-100'
                                                            }`}
                                                    >
                                                        <type.icon className="w-3 h-3" /> {type.label}
                                                    </button>
                                                ))}
                                            </div>
                                        </div>

                                        {msg.type === 'text' ? (
                                            <textarea
                                                value={msg.content as string}
                                                onChange={(e) => alterarMensagem(idx, 'content', e.target.value)}
                                                placeholder="Digite a mensagem..."
                                                className="w-full p-2 border rounded h-24 text-sm"
                                            />
                                        ) : (
                                            <div>
                                                <input
                                                    type="file"
                                                    accept={`${msg.type}/*`}
                                                    onChange={(e) => {
                                                        if (e.target.files?.[0]) {
                                                            alterarMensagem(idx, 'content', e.target.files[0]);
                                                        }
                                                    }}
                                                    className="block w-full text-sm text-slate-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
                                                />
                                                {msg.content && <PreviewArquivo tipo={msg.type} conteudo={msg.content} />}
                                            </div>
                                        )}
                                    </div>
                                ))}

                                {editandoPasso.messages.length < MAX_MENSAGENS_POR_PASSO && (
                                    <button
                                        onClick={adicionarMensagem}
                                        className="w-full py-2 border border-dashed border-gray-300 rounded text-gray-500 hover:bg-gray-50 text-sm"
                                    >
                                        + Adicionar Mensagem
                                    </button>
                                )}
                            </div>

                        </div>
                    ) : (
                        <div className="h-full flex flex-col items-center justify-center text-slate-400 border-2 border-dashed border-slate-200 rounded-lg bg-slate-50 min-h-[300px]">
                            <Edit2 className="w-12 h-12 mb-2 opacity-50" />
                            <p>Selecione um passo para editar</p>
                        </div>
                    )}
                </div>
            </div>

            <div className="mt-8 flex justify-end gap-3 pt-4 border-t">
                <button
                    onClick={onCancel}
                    className="px-4 py-2 text-slate-600 hover:bg-slate-100 rounded-lg font-medium"
                >
                    Cancelar
                </button>
                <button
                    onClick={salvarConfig}
                    disabled={saving}
                    className="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium flex items-center gap-2 disabled:opacity-50"
                >
                    {saving ? 'Salvando...' : (
                        <>
                            <Save className="w-4 h-4" /> Salvar Sequência
                        </>
                    )}
                </button>
            </div>
        </div>
    );
}
