import React, { useState, useEffect } from 'react';
import {
  // Funções específicas de No-Show
  createNoShowFollowUpSequence,
  getNoShowFollowUpSequence,
  updateNoShowFollowUpSequence,

  createNoShowScheduleConfig,
  getNoShowScheduleConfig,
  updateNoShowScheduleConfig,
  deleteNoShowScheduleConfig,

  // Reuso das mesmas funções de upload e preview
  uploadFile,
  getFileUrl,
  deleteFile,
} from '../services/api';

import {
  Trash2,
  Edit2,
  Plus,
  Play,
  Calendar,
  Clock,
  MessageCircle,
  Check,
  X,
  Image,
  Video,
  Music,
  Type,
  ChevronDown,
  ChevronUp,
  File,
  Settings,
  AlertCircle,
  Save
} from 'lucide-react';

// ----------------------------------------------------------------
// Tipos compatíveis com upsert (id? em steps e messages)
// ----------------------------------------------------------------
interface MensagemLocal {
  id?: number;  // ID opcional
  type: 'text' | 'image' | 'audio' | 'video';
  content: string | File;
}

interface PassoLocal {
  id?: number;  // ID opcional
  step_number: number;
  send_after: number;
  send_after_unit: 'days' | 'hours' | 'minutes';
  messages: MensagemLocal[];
}

// ----------------------------------------------------------------
// Tipos para Schedule
// ----------------------------------------------------------------
interface ScheduleDay {
  enabled: boolean;
  start: string;
  end: string;
}

interface ScheduleData {
  [key: string]: ScheduleDay;
}

// ----------------------------------------------------------------
// Constantes e arrays
// ----------------------------------------------------------------
const MAX_PASSOS = 10;
const MAX_MENSAGENS_POR_PASSO = 3;
const MIN_SEND_AFTER = 0;

const LIMITE_ARQUIVOS = {
  image: 2 * 1024 * 1024,
  audio: 15 * 1024 * 1024,
  video: 15 * 1024 * 1024,
};

const daysOfWeek = [
  { label: 'Segunda', key: 'monday' },
  { label: 'Terça', key: 'tuesday' },
  { label: 'Quarta', key: 'wednesday' },
  { label: 'Quinta', key: 'thursday' },
  { label: 'Sexta', key: 'friday' },
  { label: 'Sábado', key: 'saturday' },
  { label: 'Domingo', key: 'sunday' },
];

const timeUnits = [
  { value: 'minutes', label: 'Minutos' },
  { value: 'hours', label: 'Horas' },
  { value: 'days', label: 'Dias' }
];

const messageTypes = [
  { value: 'text', label: 'Texto', icon: Type },
  { value: 'image', label: 'Imagem', icon: Image },
  { value: 'audio', label: 'Áudio', icon: Music },
  { value: 'video', label: 'Vídeo', icon: Video }
];

// -------------------------------------------------------------
// Função para verificar se é um arquivo
// -------------------------------------------------------------
function isFile(value: any): boolean {
  return (
    typeof value === 'object' &&
    value !== null &&
    'name' in value &&
    'size' in value &&
    'type' in value
  );
}

// -------------------------------------------------------------
// Componente de preview de arquivo
// -------------------------------------------------------------
const PreviewArquivo = ({ tipo, conteudo }: { tipo: string; conteudo: string | File | any }) => {
  if (isFile(conteudo)) {
    return (
      <div className="bg-amber-50 border-l-4 border-amber-400 p-3 rounded-md my-2">
        <p className="text-sm text-amber-700 flex items-center">
          <AlertCircle className="w-4 h-4 mr-2" />
          Arquivo pendente de upload. Será enviado ao salvar as configurações.
        </p>
      </div>
    );
  }

  if (typeof conteudo !== 'string') {
    return (
      <div className="bg-red-50 border-l-4 border-red-400 p-3 rounded-md my-2">
        <p className="text-sm text-red-700 flex items-center">
          <AlertCircle className="w-4 h-4 mr-2" />
          Formato de arquivo inválido
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
        <img
          src={url}
          alt="Preview"
          className="w-full max-h-48 object-cover rounded-lg"
        />
      </div>
    );
  }
  if (tipo === 'audio') {
    return (
      <div className="bg-slate-50 p-3 rounded-lg mt-2">
        <audio controls className="w-full">
          <source src={url} type="audio/mpeg" />
          Seu navegador não suporta o elemento de áudio.
        </audio>
      </div>
    );
  }
  if (tipo === 'video') {
    return (
      <div className="mt-2 rounded-lg overflow-hidden">
        <video controls className="w-full max-h-48 rounded-lg">
          <source src={url} type="video/mp4" />
          Seu navegador não suporta o elemento de vídeo.
        </video>
      </div>
    );
  }
  return null;
};

// Componente para visualizar uma mensagem no modo de leitura
const MessagePreview = ({ message }: { message: MensagemLocal }) => {
  const { type, content } = message;

  if (type === 'text' && typeof content === 'string') {
    return <p className="text-slate-700 bg-slate-50 p-3 rounded-lg">{content}</p>;
  }

  return <PreviewArquivo tipo={type} conteudo={content} />;
};

// Timeline indicator component
const TimelineIndicator = ({ passos, onEditStep, onAddStep }: {
  passos: PassoLocal[],
  onEditStep: (stepNumber: number) => void,
  onAddStep: () => void
}) => {
  return (
    <div className="relative mt-8 mb-6">
      <div className="absolute top-0 bottom-0 left-8 w-0.5 bg-slate-200"></div>
      {passos.map((step) => {
        const unidadeTexto = step.send_after_unit === 'days' ? 'dias' :
                        step.send_after_unit === 'hours' ? 'horas' : 'minutos';

        return (
          <div key={step.step_number} className="relative flex items-center mb-12">
            <div className="absolute left-8 transform -translate-x-1/2 h-6 w-6 rounded-full bg-slate-800 flex items-center justify-center text-white text-xs font-bold z-10">
              {step.step_number}
            </div>
            <div className="ml-12 flex-1">
              <div className="text-sm text-slate-500 mb-1">
                Após {step.send_after} {unidadeTexto} do no-show
              </div>
              <div className="text-slate-700 font-semibold flex items-center gap-2">
                <MessageCircle className="w-4 h-4" />
                {step.messages.length} {step.messages.length === 1 ? 'mensagem' : 'mensagens'}
              </div>
              <button
                onClick={() => onEditStep(step.step_number)}
                className="mt-2 text-slate-600 text-sm hover:text-slate-900 flex items-center"
              >
                <Edit2 className="w-3 h-3 mr-1" />
                Editar passo
              </button>
            </div>
          </div>
        );
      })}

      {/* Add step button at the end of timeline */}
      {passos.length < MAX_PASSOS && (
        <div className="relative flex items-center">
          <div className="absolute left-8 transform -translate-x-1/2 h-6 w-6 rounded-full border-2 border-dashed border-slate-400 flex items-center justify-center text-slate-500 z-10">
            <Plus className="w-3 h-3" />
          </div>
          <button
            onClick={onAddStep}
            className="ml-12 text-slate-600 font-medium flex items-center gap-2 hover:text-slate-900"
          >
            <Plus className="w-4 h-4" />
            Adicionar Passo
          </button>
        </div>
      )}
    </div>
  );
};

// -------------------------------------------------------------
// Componente principal de NoShowFollowUp
// -------------------------------------------------------------
const NoShowFollowUp: React.FC = () => {
  const [passos, setPassos] = useState<PassoLocal[]>([]);
  const [editandoPasso, setEditandoPasso] = useState<PassoLocal | null>(null);

  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [hasSequence, setHasSequence] = useState(false);
  const [activeTab, setActiveTab] = useState('sequence'); // 'sequence' ou 'schedule'
  const [savedStatus, setSavedStatus] = useState<string | null>(null); // null, 'saving', 'saved', 'error'

  // schedule
  const [scheduleExists, setScheduleExists] = useState(false);
  const [scheduleEditMode, setScheduleEditMode] = useState(false);

  const [schedule, setSchedule] = useState<ScheduleData>({
    monday: { enabled: false, start: '08:00', end: '18:00' },
    tuesday: { enabled: false, start: '08:00', end: '18:00' },
    wednesday: { enabled: false, start: '08:00', end: '18:00' },
    thursday: { enabled: false, start: '08:00', end: '18:00' },
    friday: { enabled: false, start: '08:00', end: '18:00' },
    saturday: { enabled: false, start: '08:00', end: '18:00' },
    sunday: { enabled: false, start: '08:00', end: '18:00' },
  });

  // Ao montar, carrega configuração e schedule
  useEffect(() => {
    const companyIdStr = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
    if (!companyIdStr) return;
    const companyIdNum = Number(companyIdStr);
    if (!companyIdNum) return;

    carregarConfigExistente(companyIdNum);
    handleLoadScheduleConfig(companyIdNum);
  }, []);

  // Limpa mensagens de erro/sucesso após tempo
  useEffect(() => {
    if (erro || sucesso) {
      const timer = setTimeout(() => {
        setErro(null);
        setSucesso(null);
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [erro, sucesso]);

  // -----------------------------------------------------------
  // Carrega config de NoShow
  // -----------------------------------------------------------
  const carregarConfigExistente = async (companyId: number) => {
    try {
      setCarregando(true);
      const seq = await getNoShowFollowUpSequence(companyId);

      if (!seq) {
        setHasSequence(false);
        setPassos([]);
      } else {
        setHasSequence(true);

        // Converter steps e guardar ID de step e mensagens
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

        // Ordenamos os passos pelo step_number ascendente
        passosConvertidos.sort((a, b) => a.step_number - b.step_number);

        // Ordenamos as mensagens pelo id dentro de cada passo
        passosConvertidos.forEach(passo => {
          // Ordenar somente se as mensagens tiverem id
          if (passo.messages.length > 0 && passo.messages[0].id) {
            passo.messages.sort((a, b) => {
              // Verificar se os ids existem antes de comparar
              if (a.id && b.id) {
                return a.id - b.id;
              }
              return 0;
            });
          }
        });

        setPassos(passosConvertidos);
      }
    } catch (error: any) {
      setErro('Erro ao carregar configuração existente');
      console.error(error);
    } finally {
      setCarregando(false);
    }
  };

  // -----------------------------------------------------------
  // Carrega config de horários
  // -----------------------------------------------------------
  const handleLoadScheduleConfig = async (companyId: number) => {
    try {
      const resp = await getNoShowScheduleConfig(companyId);
      if (resp) {
        // Criar uma nova versão de schedule com os dados da API
        const scheduleData: ScheduleData = {};

        // Inicializar com valores padrão
        const defaultSchedule = {
          monday: { enabled: false, start: '08:00', end: '18:00' },
          tuesday: { enabled: false, start: '08:00', end: '18:00' },
          wednesday: { enabled: false, start: '08:00', end: '18:00' },
          thursday: { enabled: false, start: '08:00', end: '18:00' },
          friday: { enabled: false, start: '08:00', end: '18:00' },
          saturday: { enabled: false, start: '08:00', end: '14:00' },
          sunday: { enabled: false, start: '00:00', end: '00:00' },
        };

        // Mesclar com dados recebidos
        for (const day in resp.schedule_data) {
          const dayData = resp.schedule_data[day];

          if (dayData === null) {
            // Se o dia é null, marcar como desabilitado
            scheduleData[day] = {
              enabled: false,
              start: defaultSchedule[day]?.start || '08:00',
              end: defaultSchedule[day]?.end || '18:00'
            };
          } else {
            // Se o dia tem dados, marcar como habilitado
            scheduleData[day] = {
              enabled: true,
              start: dayData.start || defaultSchedule[day]?.start || '08:00',
              end: dayData.end || defaultSchedule[day]?.end || '18:00'
            };
          }
        }

        // Garantir que todos os dias da semana estejam no objeto
        for (const day of daysOfWeek) {
          if (!scheduleData[day.key]) {
            scheduleData[day.key] = defaultSchedule[day.key];
          }
        }

        setSchedule(scheduleData);
        setScheduleExists(true);
        setScheduleEditMode(false);
      }
    } catch (error) {
      console.log('Nenhuma config de horários encontrada ou erro:', error);
      setScheduleExists(false);
    }
  };

  // -----------------------------------------------------------
  // Salvar config de horários
  // -----------------------------------------------------------
  const handleSaveScheduleConfig = async () => {
    try {
      setSavedStatus('saving');
      const companyIdStr = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
      if (!companyIdStr) throw new Error('company_id não encontrado');
      const companyIdNum = Number(companyIdStr);

      // Filtrar apenas dias enabled
      const filteredSchedule: ScheduleData = {};
      for (const dayKey in schedule) {
        const dayData = schedule[dayKey];
        if (dayData.enabled) {
          filteredSchedule[dayKey] = {
            enabled: true,
            start: dayData.start,
            end: dayData.end,
          };
        }
      }

      const schedulePayload = { schedule_data: filteredSchedule };

      if (!scheduleExists) {
        await createNoShowScheduleConfig(companyIdNum, schedulePayload);
        setScheduleExists(true);
      } else {
        await updateNoShowScheduleConfig(companyIdNum, schedulePayload);
      }

      setScheduleEditMode(false);
      setSavedStatus('saved');
      setTimeout(() => setSavedStatus(null), 2000);
    } catch (error) {
      console.error('Erro ao salvar config de horários:', error);
      setSavedStatus('error');
    }
  };

  // -----------------------------------------------------------
  // Deletar config de horários
  // -----------------------------------------------------------
  const handleDeleteScheduleConfig = async () => {
    try {
      setCarregando(true);
      const companyIdStr = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
      if (!companyIdStr) throw new Error('company_id não encontrado');
      const companyIdNum = Number(companyIdStr);

      await deleteNoShowScheduleConfig(companyIdNum);
      setScheduleExists(false);
      setScheduleEditMode(false);

      // Reset local
      setSchedule({
        monday: { enabled: false, start: '08:00', end: '18:00' },
        tuesday: { enabled: false, start: '08:00', end: '18:00' },
        wednesday: { enabled: false, start: '08:00', end: '18:00' },
        thursday: { enabled: false, start: '08:00', end: '18:00' },
        friday: { enabled: false, start: '08:00', end: '18:00' },
        saturday: { enabled: false, start: '08:00', end: '14:00' },
        sunday: { enabled: false, start: '00:00', end: '00:00' },
      });

      setSucesso('Config de horários deletada com sucesso!');
    } catch (error) {
      console.error('Erro ao deletar config de horários:', error);
      setErro('Falha ao deletar config de horários');
    } finally {
      setCarregando(false);
    }
  };

  // -----------------------------------------------------------
  // Salvar config (faz upload dos arquivos e manda pro backend)
  // -----------------------------------------------------------
  const salvarConfig = async () => {
    try {
      setSavedStatus('saving');

      const companyIdStr = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
      if (!companyIdStr) {
        throw new Error('ID da empresa não encontrado');
      }

      const companyIdNum = Number(companyIdStr);

      // 1) Transformar PassoLocal[] em API[] (fazendo upload se houver File)
      const passosAPI = await Promise.all(
        passos.map(async (passoLocal) => {
          const messagesAPI = await Promise.all(
            passoLocal.messages.map(async (msgLocal) => {
              // Verificamos se é um arquivo
              if (msgLocal.type !== 'text' && isFile(msgLocal.content)) {
                // upload
                const file = msgLocal.content as File;
                const limiteArquivo = LIMITE_ARQUIVOS[msgLocal.type];
                if (file.size > limiteArquivo) {
                  throw new Error(
                    `Arquivo muito grande. Máx p/ ${msgLocal.type}: ${limiteArquivo / (1024 * 1024)}MB`
                  );
                }
                const resultadoUpload = await uploadFile(file);
                return {
                  id: msgLocal.id,
                  type: msgLocal.type,
                  content: resultadoUpload.path,
                };
              } else if (typeof msgLocal.content === 'string') {
                return {
                  id: msgLocal.id,
                  type: msgLocal.type,
                  content: msgLocal.content,
                };
              } else {
                throw new Error('Tipo de conteúdo inesperado.');
              }
            })
          );

          return {
            id: passoLocal.id,
            step_number: passoLocal.step_number,
            send_after: passoLocal.send_after,
            send_after_unit: passoLocal.send_after_unit,
            messages: messagesAPI,
          };
        })
      );

      // 2) Montamos o payload final
      const payload = {
        company_id: companyIdNum,
        name: 'Sequência de No-Show',
        description: 'Mensagens automáticas para clientes que não compareceram',
        steps: passosAPI,
      };

      // 3) create ou update
      if (hasSequence) {
        await updateNoShowFollowUpSequence(companyIdNum, payload);
        setSavedStatus('saved');
      } else {
        await createNoShowFollowUpSequence(companyIdNum, payload);
        setHasSequence(true);
        setSavedStatus('saved');
      }

      setTimeout(() => setSavedStatus(null), 2000);

      // 4) Recarrega do GET para atualizar e ordenar local
      await carregarConfigExistente(companyIdNum);
      setEditandoPasso(null);
    } catch (err) {
      setErro('Falha ao salvar configuração');
      setSavedStatus('error');
      console.error(err);
    }
  };

  // -----------------------------------------------------------
  // Adicionar passo / editar passo / adicionar mensagens
  // -----------------------------------------------------------
  const adicionarPasso = () => {
    if (passos.length >= MAX_PASSOS) {
      setErro(`Número máximo de passos (${MAX_PASSOS}) atingido`);
      return;
    }
    const novoPasso: PassoLocal = {
      step_number: passos.length + 1,
      send_after: 0,
      send_after_unit: 'days',
      messages: [],
    };
    setPassos([...passos, novoPasso]);
    setEditandoPasso(novoPasso);
  };

  const editarPasso = (numeroPasso: number) => {
    const passo = passos.find(p => p.step_number === numeroPasso);
    if (passo) {
      setEditandoPasso(passo);
    }
  };

  const atualizarPasso = (passoAtualizado: PassoLocal) => {
    setPassos((prev) =>
      prev.map((p) => (p.step_number === passoAtualizado.step_number ? passoAtualizado : p))
    );
    setEditandoPasso(passoAtualizado);
  };

  const fecharEdicaoPasso = () => {
    setEditandoPasso(null);
  };

  const adicionarMensagem = (numeroPasso: number) => {
    const passoAlvo = passos.find((p) => p.step_number === numeroPasso);
    if (!passoAlvo) return;
    if (passoAlvo.messages.length >= MAX_MENSAGENS_POR_PASSO) {
      setErro(`Número máximo de mensagens por passo (${MAX_MENSAGENS_POR_PASSO}) atingido`);
      return;
    }

    const novaMensagem: MensagemLocal = { type: 'text', content: '' };

    const novoPassoComMensagem: PassoLocal = {
      ...passoAlvo,
      messages: [...passoAlvo.messages, novaMensagem],
    };

    setPassos((prev) =>
      prev.map((p) => (p.step_number === numeroPasso ? novoPassoComMensagem : p))
    );

    setEditandoPasso(novoPassoComMensagem);
  };

  const deletarMensagem = async (numeroPasso: number, indiceMensagem: number) => {
    try {
      const passoIndex = passos.findIndex((p) => p.step_number === numeroPasso);
      if (passoIndex === -1) return;
      const passo = passos[passoIndex];
      const mensagem = passo.messages[indiceMensagem];

      // Se houver ID e content for string (arquivo salvo), podemos deletar do servidor
      if (mensagem && mensagem.type !== 'text' && typeof mensagem.content === 'string') {
        const fileName = mensagem.content.split('/').pop();
        if (fileName) {
          try {
            await deleteFile(fileName);
          } catch (error) {
            console.warn(`Não foi possível deletar arquivo ${fileName}:`, error);
          }
        }
      }

      // Remover a mensagem
      const mensagensAtualizadas = [...passo.messages];
      mensagensAtualizadas.splice(indiceMensagem, 1);

      const passoAtualizado = { ...passo, messages: mensagensAtualizadas };

      setPassos((prev) =>
        prev.map((p) => (p.step_number === numeroPasso ? passoAtualizado : p))
      );

      setEditandoPasso(passoAtualizado);
    } catch (err) {
      setErro('Falha ao deletar mensagem');
      console.error(err);
    }
  };

  const alterarMensagem = async (
    numeroPasso: number,
    indiceMensagem: number,
    messageType: 'text' | 'image' | 'audio' | 'video',
    conteudo: string | File | any
  ) => {
    const passoIndex = passos.findIndex((p) => p.step_number === numeroPasso);
    if (passoIndex === -1) return;

    const passo = passos[passoIndex];
    const oldMsg = passo.messages[indiceMensagem];

    const updatedMsg: MensagemLocal = {
      id: oldMsg?.id,
      type: messageType,
      content: conteudo,
    };

    const mensagensAtualizadas = [...passo.messages];
    mensagensAtualizadas[indiceMensagem] = updatedMsg;

    const passoAtualizado = { ...passo, messages: mensagensAtualizadas };

    setPassos((prev) =>
      prev.map((p) => (p.step_number === numeroPasso ? passoAtualizado : p))
    );

    setEditandoPasso(passoAtualizado);
  };

  const unidadeTempoTexto = (unidade: string) => {
    switch (unidade) {
      case 'days':
        return 'dias';
      case 'hours':
        return 'horas';
      case 'minutes':
        return 'minutos';
      default:
        return unidade;
    }
  };

  const renderIconForMessageType = (type: string) => {
    switch(type) {
      case 'text':
        return <Type className="w-4 h-4 text-slate-500" />;
      case 'image':
        return <Image className="w-4 h-4 text-slate-500" />;
      case 'audio':
        return <Music className="w-4 h-4 text-slate-500" />;
      case 'video':
        return <Video className="w-4 h-4 text-slate-500" />;
      default:
        return <File className="w-4 h-4 text-slate-500" />;
    }
  };

  // Render loading state
  if (carregando && passos.length === 0) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-slate-700 border-t-transparent"></div>
      </div>
    );
  }

  // -----------------------------------------------------------
  // Render
  // -----------------------------------------------------------
  return (
    <div className="bg-white min-h-screen">
      <div className="max-w-6xl mx-auto p-6">
        {/* Header com logo e título */}
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold text-slate-800">Sequência de No-Show</h1>

          <div className="flex space-x-1 bg-white p-1 rounded-lg shadow-sm">
            <button
              onClick={() => setActiveTab('sequence')}
              className={`px-4 py-2 rounded-md text-sm font-medium flex items-center gap-2 ${
                activeTab === 'sequence'
                  ? 'bg-slate-800 text-white'
                  : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              <MessageCircle className="w-4 h-4" />
              Mensagens
            </button>
            <button
              onClick={() => setActiveTab('schedule')}
              className={`px-4 py-2 rounded-md text-sm font-medium flex items-center gap-2 ${
                activeTab === 'schedule'
                  ? 'bg-slate-800 text-white'
                  : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              <Calendar className="w-4 h-4" />
              Horários
            </button>
          </div>
        </div>

        {/* Alertas */}
        {erro && (
          <div className="fixed bottom-6 right-6 py-2 px-4 bg-red-100 text-red-700 rounded-md shadow-lg flex items-center max-w-md">
            <AlertCircle className="w-5 h-5 mr-2" />
            {erro}
          </div>
        )}
        {sucesso && (
          <div className="fixed bottom-6 right-6 py-2 px-4 bg-green-100 text-green-700 rounded-md shadow-lg flex items-center max-w-md">
            <Check className="w-5 h-5 mr-2" />
            {sucesso}
          </div>
        )}

        {/* Save status indicator */}
        {savedStatus && (
          <div className={`fixed bottom-6 right-6 py-2 px-4 rounded-md shadow-lg flex items-center gap-2 ${
            savedStatus === 'saving' ? 'bg-blue-100 text-blue-700' :
            savedStatus === 'saved' ? 'bg-green-100 text-green-700' :
            'bg-red-100 text-red-700'
          }`}>
            {savedStatus === 'saving' ?
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-2 border-blue-500 border-t-transparent"></div>
                <span>Salvando...</span>
              </> :
             savedStatus === 'saved' ?
              <>
                <Check className="w-4 h-4" />
                <span>Salvo com sucesso!</span>
              </> :
              <>
                <AlertCircle className="w-4 h-4" />
                <span>Erro ao salvar</span>
              </>
            }
          </div>
        )}

        {/* Sequence tab */}
        {activeTab === 'sequence' && (
          <div className="mb-8">
            {/* Visão de Overview (quando não está editando um passo) */}
            {!editandoPasso ? (
              <>
                <div className="bg-white rounded-2xl shadow-sm p-6 mb-8">
                  <div className="flex items-center justify-between mb-6">
                    <h2 className="text-xl font-semibold text-slate-800">Visão geral da sequência</h2>
                    <button
                      className="bg-slate-100 text-slate-700 hover:bg-slate-200 rounded-md px-4 py-2 text-sm font-medium flex items-center gap-2"
                      onClick={salvarConfig}
                      disabled={passos.length === 0 || carregando}
                    >
                      <Save className="w-4 h-4" />
                      Salvar alterações
                    </button>
                  </div>

                  {/* Timeline visualization */}
                  {passos.length > 0 ? (
                    <TimelineIndicator
                      passos={passos}
                      onEditStep={editarPasso}
                      onAddStep={adicionarPasso}
                    />
                  ) : (
                    <div className="bg-slate-50 border-2 border-dashed border-slate-200 rounded-lg p-8 text-center">
                      <MessageCircle className="w-12 h-12 text-slate-300 mx-auto mb-4" />
                      <p className="text-slate-500 mb-4">
                        Nenhum passo configurado. Crie sua sequência de no-show.
                      </p>
                      <button
                        onClick={adicionarPasso}
                        className="px-4 py-2 bg-slate-800 text-white rounded-md hover:bg-slate-700"
                      >
                        <Plus className="w-4 h-4 inline mr-2" />
                        Adicionar primeiro passo
                      </button>
                    </div>
                  )}
                </div>

                {/* Passos em cards */}
                {passos.length > 0 && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {passos.map((passo) => (
                      <div key={passo.step_number} className="bg-white rounded-2xl shadow-sm overflow-hidden transition-all hover:shadow-md">
                        <div className="bg-slate-100 px-6 py-4 flex justify-between items-center">
                          <div className="flex items-center gap-3">
                            <div className="h-8 w-8 rounded-full bg-slate-800 flex items-center justify-center text-white font-bold">
                              {passo.step_number}
                            </div>
                            <div>
                              <h3 className="font-semibold text-slate-800">Passo {passo.step_number}</h3>
                              <p className="text-xs text-slate-500">
                                Após {passo.send_after} {unidadeTempoTexto(passo.send_after_unit)} do no-show
                                {passo.id && <span className="ml-2">(ID: {passo.id})</span>}
                              </p>
                            </div>
                          </div>

                          <button
                            className="text-slate-600 hover:text-slate-800"
                            onClick={() => editarPasso(passo.step_number)}
                          >
                            <Edit2 className="w-5 h-5" />
                          </button>
                        </div>

                        <div className="p-6">
                          {passo.messages.length > 0 ? (
                            passo.messages.map((message, msgIndex) => (
                              <div key={msgIndex} className="mb-4 last:mb-0">
                                <div className="flex items-center gap-2 mb-2">
                                  {renderIconForMessageType(message.type)}
                                  <span className="text-sm text-slate-500">
                                    Mensagem {msgIndex + 1} • {
                                      message.type === 'text' ? 'Texto' :
                                      message.type === 'image' ? 'Imagem' :
                                      message.type === 'audio' ? 'Áudio' : 'Vídeo'
                                    }
                                    {message.id && <span className="ml-1">(ID: {message.id})</span>}
                                  </span>
                                </div>

                                <MessagePreview message={message} />
                              </div>
                            ))
                          ) : (
                            <div className="text-center py-4 text-slate-500">
                              <MessageCircle className="w-8 h-8 mx-auto mb-2 text-slate-300" />
                              <p>Nenhuma mensagem definida</p>
                            </div>
                          )}

                          {passo.messages.length < MAX_MENSAGENS_POR_PASSO && (
                            <button
                              onClick={() => adicionarMensagem(passo.step_number)}
                              className="w-full mt-4 py-2 border border-dashed border-slate-300 rounded-md text-slate-500 hover:bg-slate-50"
                            >
                              <Plus className="w-4 h-4 inline mr-1" />
                              Adicionar mensagem
                            </button>
                          )}
                        </div>
                      </div>
                    ))}

                    {/* Add new step card (if limit not reached) */}
                    {passos.length < MAX_PASSOS && (
                      <div className="bg-slate-50 rounded-2xl border-2 border-dashed border-slate-200 flex items-center justify-center h-64">
                        <button
                          onClick={adicionarPasso}
                          className="text-slate-600 hover:text-slate-800 font-medium flex flex-col items-center gap-2"
                        >
                          <div className="h-12 w-12 rounded-full border-2 border-current flex items-center justify-center">
                            <Plus className="w-6 h-6" />
                          </div>
                          <span>Adicionar Novo Passo</span>
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </>
            ) : (
              /* Formulário de edição de passo */
              <div className="bg-white rounded-2xl shadow-sm overflow-hidden">
                <div className="bg-slate-100 px-6 py-4 flex justify-between items-center">
                  <div className="flex items-center gap-3">
                    <div className="h-8 w-8 rounded-full bg-slate-800 flex items-center justify-center text-white font-bold">
                      {editandoPasso.step_number}
                    </div>
                    <h3 className="font-semibold text-slate-800">
                      Editar Passo {editandoPasso.step_number}
                      {editandoPasso.id && <span className="text-xs text-slate-500 ml-2">(ID: {editandoPasso.id})</span>}
                    </h3>
                  </div>

                  <button
                    className="text-slate-500 hover:text-slate-700"
                    onClick={fecharEdicaoPasso}
                  >
                    <X className="w-5 h-5" />
                  </button>
                </div>

                <div className="p-6">
                  {/* Timing configuration */}
                  <div className="mb-6">
                    <label className="block text-sm font-medium text-slate-700 mb-2">
                      Tempo após o no-show
                    </label>
                    <div className="flex gap-3">
                      <div className="w-24">
                        <input
                          type="number"
                          min={MIN_SEND_AFTER}
                          value={editandoPasso.send_after}
                          onChange={(e) => atualizarPasso({
                            ...editandoPasso,
                            send_after: parseInt(e.target.value || '0', 10),
                          })}
                          className="w-full rounded-md border-slate-300 shadow-sm focus:border-slate-500 focus:ring focus:ring-slate-200 focus:ring-opacity-50"
                        />
                      </div>
                      <div className="w-32">
                        <select
                          value={editandoPasso.send_after_unit}
                          onChange={(e) => atualizarPasso({
                            ...editandoPasso,
                            send_after_unit: e.target.value as 'days' | 'hours' | 'minutes',
                          })}
                          className="w-full rounded-md border-slate-300 shadow-sm focus:border-slate-500 focus:ring focus:ring-slate-200 focus:ring-opacity-50"
                        >
                          {timeUnits.map(unit => (
                            <option key={unit.value} value={unit.value}>{unit.label}</option>
                          ))}
                        </select>
                      </div>
                    </div>
                  </div>

                  {/* Messages */}
                  <div className="mb-6">
                    <div className="flex justify-between items-center mb-4">
                      <h4 className="font-medium text-slate-700">Mensagens</h4>
                      {editandoPasso.messages.length < MAX_MENSAGENS_POR_PASSO && (
                        <button
                          onClick={() => adicionarMensagem(editandoPasso.step_number)}
                          className="text-sm text-slate-600 hover:text-slate-800 flex items-center gap-1"
                        >
                          <Plus className="w-4 h-4" />
                          Adicionar Mensagem
                        </button>
                      )}
                    </div>

                    {/* Mensagens existentes */}
                    {editandoPasso.messages.length > 0 ? (
                      editandoPasso.messages.map((message, index) => (
                        <div key={index} className="bg-slate-50 rounded-lg p-4 mb-4">
                          <div className="flex justify-between items-center mb-3">
                            <div className="flex items-center gap-2">
                              <span className="bg-slate-200 text-slate-600 rounded-full w-6 h-6 flex items-center justify-center text-xs font-medium">
                                {index + 1}
                              </span>
                              <select
                                value={message.type}
                                onChange={(e) => alterarMensagem(
                                  editandoPasso.step_number,
                                  index,
                                  e.target.value as 'text' | 'image' | 'audio' | 'video',
                                  message.type === 'text' && e.target.value !== 'text' ? '' : message.content
                                )}
                                className="text-sm border-0 bg-transparent focus:ring-0 text-slate-700 font-medium"
                              >
                                {messageTypes.map(type => (
                                  <option key={type.value} value={type.value}>{type.label}</option>
                                ))}
                              </select>
                            </div>
                            <button
                              className="text-red-500 hover:text-red-700"
                              onClick={() => deletarMensagem(editandoPasso.step_number, index)}
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>

                          {message.type === 'text' ? (
                            <textarea
                              value={typeof message.content === 'string' ? message.content : ''}
                              onChange={(e) => alterarMensagem(
                                editandoPasso.step_number,
                                index,
                                'text',
                                e.target.value
                              )}
                              rows={3}
                              className="w-full rounded-md border-slate-300 shadow-sm focus:border-slate-500 focus:ring focus:ring-slate-200 focus:ring-opacity-50"
                              placeholder="Digite sua mensagem aqui..."
                            />
                          ) : (
                            <div className="mt-2">
                              {/* Arquivo já enviado */}
                              {typeof message.content === 'string' && message.content && (
                                <div className="mb-2">
                                  <p className="text-sm text-slate-600 mb-1">
                                    Arquivo atual: {message.content.split('/').pop()}
                                  </p>
                                  <PreviewArquivo tipo={message.type} conteudo={message.content} />
                                </div>
                              )}

                              {/* Upload de arquivo */}
                              <div className="border-2 border-dashed border-slate-300 rounded-lg p-4 flex flex-col items-center justify-center text-center">
                                {isFile(message.content) ? (
                                  <>
                                    <File className="w-8 h-8 text-slate-500 mb-2" />
                                    <p className="text-sm text-slate-600 mb-2">{(message.content as File).name}</p>
                                  </>
                                ) : (
                                  <File className="w-8 h-8 text-slate-400 mb-2" />
                                )}

                                <p className="text-sm text-slate-500 mb-2">
                                  {message.type === 'image' && `Máx ${LIMITE_ARQUIVOS.image / (1024 * 1024)}MB (imagens)`}
                                  {message.type === 'audio' && `Máx ${LIMITE_ARQUIVOS.audio / (1024 * 1024)}MB (áudios)`}
                                  {message.type === 'video' && `Máx ${LIMITE_ARQUIVOS.video / (1024 * 1024)}MB (vídeos)`}
                                </p>

                                <input
                                  type="file"
                                  id={`file-${editandoPasso.step_number}-${index}`}
                                  className="hidden"
                                  accept={
                                    message.type === 'image' ? 'image/*' :
                                    message.type === 'audio' ? 'audio/*' : 'video/*'
                                  }
                                  onChange={(e) => {
                                    if (e.target.files?.[0]) {
                                      alterarMensagem(
                                        editandoPasso.step_number,
                                        index,
                                        message.type,
                                        e.target.files[0]
                                      );
                                    }
                                  }}
                                />
                                <label
                                  htmlFor={`file-${editandoPasso.step_number}-${index}`}
                                  className="text-xs bg-slate-200 hover:bg-slate-300 text-slate-700 py-1 px-3 rounded cursor-pointer"
                                >
                                  {isFile(message.content) ? 'Alterar arquivo' : 'Selecionar arquivo'}
                                </label>
                              </div>
                            </div>
                          )}
                        </div>
                      ))
                    ) : (
                      <div className="text-center p-8 border-2 border-dashed border-slate-200 rounded-lg">
                        <MessageCircle className="w-12 h-12 text-slate-300 mx-auto mb-3" />
                        <p className="text-slate-500 mb-4">
                          Nenhuma mensagem adicionada para este passo
                        </p>
                        <button
                          onClick={() => adicionarMensagem(editandoPasso.step_number)}
                          className="px-4 py-2 bg-slate-800 text-white rounded-md hover:bg-slate-700"
                        >
                          <Plus className="w-4 h-4 inline mr-2" />
                          Adicionar primeira mensagem
                        </button>
                      </div>
                    )}
                  </div>

                  {/* Action buttons */}
                  <div className="flex justify-end gap-3 pt-4 border-t">
                    <button
                      className="px-4 py-2 border border-slate-300 rounded-md text-slate-700 hover:bg-slate-50"
                      onClick={fecharEdicaoPasso}
                    >
                      Cancelar
                    </button>
                    <button
                      className="px-4 py-2 bg-slate-800 text-white rounded-md hover:bg-slate-700 flex items-center gap-2"
                      onClick={salvarConfig}
                    >
                      <Save className="w-4 h-4" />
                      Salvar alterações
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Schedule tab */}
        {activeTab === 'schedule' && (
          <div className="bg-white rounded-2xl shadow-sm p-6">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-semibold text-slate-800">Configuração de horários</h2>

              {scheduleExists && !scheduleEditMode ? (
                <div className="space-x-2">
                  <button
                    className="bg-slate-100 text-slate-700 hover:bg-slate-200 rounded-md px-4 py-2 text-sm font-medium flex items-center gap-2"
                    onClick={() => setScheduleEditMode(true)}
                  >
                    <Edit2 className="w-4 h-4" />
                    Editar horários
                  </button>
                </div>
              ) : (
                <button
                  className="bg-slate-100 text-slate-700 hover:bg-slate-200 rounded-md px-4 py-2 text-sm font-medium flex items-center gap-2"
                  onClick={handleSaveScheduleConfig}
                >
                  <Save className="w-4 h-4" />
                  Salvar horários
                </button>
              )}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-7 gap-4 mb-8">
              {daysOfWeek.map(day => {
                const dayData = schedule[day.key] || { enabled: false, start: '09:00', end: '17:00' };

                return (
                  <div
                    key={day.key}
                    className={`rounded-lg p-4 ${
                      dayData.enabled
                        ? 'bg-slate-100 border border-slate-200'
                        : 'bg-slate-50 border border-slate-100'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-3">
                      <span className="font-medium text-slate-700">{day.label}</span>
                      {(scheduleEditMode || !scheduleExists) ? (
                        <label className="relative inline-flex items-center cursor-pointer">
                          <input
                            type="checkbox"
                            checked={dayData.enabled}
                            onChange={(e) => {
                              const checked = e.target.checked;
                              setSchedule((prev) => ({
                                ...prev,
                                [day.key]: { ...prev[day.key], enabled: checked },
                              }));
                            }}
                            className="sr-only peer"
                          />
                          <div className={`w-9 h-5 bg-slate-200 rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all ${
                            dayData.enabled ? 'peer-checked:bg-slate-600' : ''
                          }`}></div>
                        </label>
                      ) : (
                        <div className={`w-3 h-3 rounded-full ${dayData.enabled ? 'bg-green-500' : 'bg-slate-300'}`}></div>
                      )}
                    </div>

                    {dayData.enabled ? (
                      <div className="text-center space-y-2">
                        <div className="flex items-center gap-2">
                          <Clock className="w-4 h-4 text-slate-500" />
                          {(scheduleEditMode || !scheduleExists) ? (
                            <input
                              type="time"
                              value={dayData.start}
                              onChange={(e) => {
                                setSchedule((prev) => ({
                                  ...prev,
                                  [day.key]: { ...prev[day.key], start: e.target.value },
                                }));
                              }}
                              className="border-slate-200 rounded focus:ring-slate-500 focus:border-slate-500 text-sm p-1"
                            />
                          ) : (
                            <span className="text-slate-700">{dayData.start}</span>
                          )}
                        </div>
                        <div className="text-xs text-slate-500">até</div>
                        <div className="flex items-center gap-2">
                          <Clock className="w-4 h-4 text-slate-500" />
                          {(scheduleEditMode || !scheduleExists) ? (
                            <input
                              type="time"
                              value={dayData.end}
                              onChange={(e) => {
                                setSchedule((prev) => ({
                                  ...prev,
                                  [day.key]: { ...prev[day.key], end: e.target.value },
                                }));
                              }}
                              className="border-slate-200 rounded focus:ring-slate-500 focus:border-slate-500 text-sm p-1"
                            />
                          ) : (
                            <span className="text-slate-700">{dayData.end}</span>
                          )}
                        </div>
                      </div>
                    ) : (
                      <div className="text-center pt-2 pb-1">
                        <span className="text-sm text-slate-400">Desativado</span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Schedule visualization */}
            <div className="border rounded-lg overflow-hidden mt-8">
              <div className="bg-slate-50 px-4 py-3 border-b flex items-center">
                <h3 className="font-medium text-slate-700">Visualização da semana</h3>
              </div>

              <div className="p-6">
                <div className="flex">
                  {/* Time indicators */}
                  <div className="w-16 pr-2 pt-6">
                    {Array.from({ length: 12 }).map((_, i) => (
                      <div key={i} className="h-8 text-xs text-slate-500 text-right">
                        {(i + 8) % 12 === 0 ? '12' : (i + 8) % 12}:00 {i + 8 < 12 ? 'AM' : 'PM'}
                      </div>
                    ))}
                  </div>

                  {/* Day columns */}
                  <div className="flex-1 grid grid-cols-7 gap-1">
                    {daysOfWeek.map(day => {
                      const dayData = schedule[day.key] || { enabled: false, start: '09:00', end: '17:00' };
                      let startHour = 0;
                      let endHour = 0;

                      if (dayData.enabled) {
                        const [startH] = dayData.start.split(':').map(Number);
                        const [endH] = dayData.end.split(':').map(Number);
                        startHour = startH;
                        endHour = endH;
                      }

                      // Calculate position
                      const startOffset = Math.max(0, startHour - 8) * 8;
                      const duration = Math.max(0, endHour - startHour) * 8;

                      return (
                        <div key={day.key} className="relative">
                          <div className="h-6 text-xs font-medium text-center border-b pb-1">
                            {day.label}
                          </div>

                          {/* Time blocks */}
                          <div className="h-96 relative border-l">
                            {Array.from({ length: 12 }).map((_, i) => (
                              <div key={i} className="h-8 border-b border-slate-100"></div>
                            ))}

                            {dayData.enabled && (
                              <div
                                className="absolute left-0 right-0 bg-slate-100 border-l-4 border-slate-600 rounded-r-md px-2"
                                style={{ top: `${startOffset}px`, height: `${duration}px` }}
                              >
                                <div className="text-xs text-slate-700 font-medium h-full flex items-center">
                                  <span>{dayData.start} - {dayData.end}</span>
                                </div>
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>

            {/* Botões de ação para configuração de horários */}
            <div className="flex justify-end mt-6 gap-3">
              {scheduleExists && (
                <>
                  {scheduleEditMode ? (
                    <button
                      className="px-4 py-2 border border-slate-300 rounded-md text-slate-700 hover:bg-slate-50"
                      onClick={() => setScheduleEditMode(false)}
                    >
                      Cancelar
                    </button>
                  ) : (
                    <button
                      className="px-4 py-2 border border-red-300 text-red-700 rounded-md hover:bg-red-50"
                      onClick={handleDeleteScheduleConfig}
                    >
                      <Trash2 className="w-4 h-4 inline mr-1" />
                      Excluir configuração
                    </button>
                  )}
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default NoShowFollowUp;