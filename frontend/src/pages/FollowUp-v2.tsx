import React, { useEffect, useMemo, useState } from 'react';
import {
  uploadFile,
  getFileUrl,
  getSingleFollowUpSequence,
  createFollowUpSequence,
  updateFollowUpSequence,
  deleteFile,
  getFollowUpScheduleConfig,
  createFollowUpScheduleConfig,
  updateFollowUpScheduleConfig,
  deleteFollowUpScheduleConfig
} from '../services/api';
import { pipelineApi, type PipelineStage } from '../services/crmApi.ts';
import {
  AlertCircle,
  Calendar,
  Check,
  ChevronDown,
  Edit2,
  File,
  Image,
  Layers,
  ListChecks,
  Loader2,
  MessageCircle,
  Music,
  Plus,
  Save,
  Send,
  Smartphone,
  Timer,
  Trash2,
  Type,
  Video,
  X,
  Zap,
  type LucideIcon,
} from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AgentiveAlert,
  AgentiveConfirmModal,
  AgentiveEmptyState,
  AgentivePageHeader,
  agentiveIconButtonClass,
  agentiveInputClass,
  agentivePageClass,
  agentivePanelClass,
  agentiveSecondaryButtonClass,
  agentiveTextareaClass,
} from '../components/AgentiveUI.tsx';
import WhatsAppIcon from '../components/icons/WhatsAppIcon.tsx';
import { branding } from '../config/branding.ts';

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

interface MensagemAPI {
  id?: number;
  type: string;
  content: string;
}

interface PassoAPI {
  id?: number;
  step_number: number;
  send_after: number;
  send_after_unit: string;
  messages: MensagemAPI[];
}

interface ScheduleDay {
  enabled: boolean;
  start: string;
  end: string;
}

interface ScheduleData {
  [key: string]: ScheduleDay;
}

type FollowUpTab = 'sequence' | 'schedule';
type SavedStatus = 'saving' | 'saved' | 'error' | null;

interface MessageDeleteTarget {
  stepNumber: number;
  index: number;
  message: MensagemLocal;
}

interface StepDeleteTarget {
  step: PassoLocal;
}

const MAX_PASSOS = 10;
const MAX_MENSAGENS_POR_PASSO = 3;

const LIMITE_ARQUIVOS = {
  image: 2 * 1024 * 1024,
  audio: 5 * 1024 * 1024,
  video: 5 * 1024 * 1024,
};

const daysOfWeek = [
  { label: 'Segunda', short: 'Seg', key: 'monday' },
  { label: 'Terca', short: 'Ter', key: 'tuesday' },
  { label: 'Quarta', short: 'Qua', key: 'wednesday' },
  { label: 'Quinta', short: 'Qui', key: 'thursday' },
  { label: 'Sexta', short: 'Sex', key: 'friday' },
  { label: 'Sabado', short: 'Sab', key: 'saturday' },
  { label: 'Domingo', short: 'Dom', key: 'sunday' },
];

const timeUnits: Array<{ value: PassoLocal['send_after_unit']; label: string }> = [
  { value: 'minutes', label: 'Minutos' },
  { value: 'hours', label: 'Horas' },
  { value: 'days', label: 'Dias' }
];

const messageTypes: Array<{ value: MensagemLocal['type']; label: string; icon: LucideIcon }> = [
  { value: 'text', label: 'Texto', icon: Type },
  { value: 'image', label: 'Imagem', icon: Image },
  { value: 'audio', label: 'Audio', icon: Music },
  { value: 'video', label: 'Video', icon: Video }
];

const weekHours = Array.from({ length: 12 }, (_, index) => index + 8);

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

const createDefaultSchedule = (): ScheduleData => ({
  monday: { enabled: false, start: '08:00', end: '18:00' },
  tuesday: { enabled: false, start: '08:00', end: '18:00' },
  wednesday: { enabled: false, start: '08:00', end: '18:00' },
  thursday: { enabled: false, start: '08:00', end: '18:00' },
  friday: { enabled: false, start: '08:00', end: '18:00' },
  saturday: { enabled: false, start: '08:00', end: '14:00' },
  sunday: { enabled: false, start: '00:00', end: '00:00' },
});

function mergeScheduleData(
  serverData: Record<string, any> | null | undefined,
  baseData: ScheduleData
): ScheduleData {
  const merged: ScheduleData = { ...baseData };

  if (!serverData) return merged;

  for (const dayKey in merged) {
    const fromServer = serverData[dayKey];

    if (fromServer === null) {
      merged[dayKey] = {
        enabled: false,
        start: merged[dayKey].start,
        end: merged[dayKey].end,
      };
    } else if (typeof fromServer === 'object') {
      merged[dayKey] = {
        enabled: fromServer.enabled ?? true,
        start: fromServer.start ?? merged[dayKey].start,
        end: fromServer.end ?? merged[dayKey].end,
      };
    }
  }

  return merged;
}

function isFile(value: any): boolean {
  return (
    typeof value === 'object' &&
    value !== null &&
    'name' in value &&
    'size' in value &&
    'type' in value
  );
}

const getMessageTypeMeta = (type: string) =>
  messageTypes.find(item => item.value === type) || { value: 'text', label: 'Arquivo', icon: File };

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

const formatDelay = (step: PassoLocal) => `Apos ${step.send_after} ${unidadeTempoTexto(step.send_after_unit)}`;

const getFileName = (content: string | File | any) => {
  if (isFile(content)) return content.name;
  if (typeof content === 'string') return content.split('/').pop() || content;
  return '';
};

const getStoredFileUrl = (content: string | File | any) => {
  if (typeof content !== 'string' || !content) return '';
  const companyId = Number((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')));
  const clientId = Number(localStorage.getItem('client_id'));
  const fileName = content.split('/').pop() || '';
  return fileName ? getFileUrl(companyId, clientId, fileName) : '';
};

const getScheduleEnabledCount = (schedule: ScheduleData) =>
  daysOfWeek.filter(day => schedule[day.key]?.enabled).length;

const getStageName = (stage?: PipelineStage | null) => stage?.name || 'Etapa do funil';

const isStageConfigured = (stage: PipelineStage, selectedStageId: number | null, currentSequenceId: number | null) =>
  Boolean(stage.follow_up_sequence_id || (stage.id === selectedStageId && currentSequenceId));

const renumberSteps = (steps: PassoLocal[]) =>
  steps.map((step, index) => ({
    ...step,
    step_number: index + 1,
  }));

const PreviewArquivo = ({ tipo, conteudo }: { tipo: string; conteudo: string | File | any }) => {
  const { isDark } = useTheme();

  if (isFile(conteudo)) {
    return (
      <div className={cx(
        'my-2 rounded-xl border p-3 text-sm',
        isDark ? 'border-amber-400/30 bg-amber-400/10 text-amber-200' : 'border-amber-200 bg-amber-50 text-amber-800'
      )}>
        <div className="flex items-center gap-2">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span className="min-w-0 truncate">{getFileName(conteudo)} pendente de upload</span>
        </div>
      </div>
    );
  }

  if (typeof conteudo !== 'string' || !conteudo) {
    return (
      <div className={cx(
        'my-2 rounded-xl border p-3 text-sm',
        isDark ? 'border-red-400/30 bg-red-400/10 text-red-200' : 'border-red-200 bg-red-50 text-red-700'
      )}>
        <div className="flex items-center gap-2">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>Arquivo nao selecionado</span>
        </div>
      </div>
    );
  }

  const url = getStoredFileUrl(conteudo);

  if (tipo === 'image') {
    return (
      <div className="mt-2 overflow-hidden rounded-xl border border-brand/10">
        <img
          src={url}
          alt="Preview"
          className="max-h-48 w-full object-cover"
        />
      </div>
    );
  }

  if (tipo === 'audio') {
    return (
      <div className={cx('mt-2 rounded-xl border p-3', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas')}>
        <audio controls className="w-full">
          <source src={url} type="audio/mpeg" />
          Seu navegador nao suporta o elemento de audio.
        </audio>
      </div>
    );
  }

  if (tipo === 'video') {
    return (
      <div className="mt-2 overflow-hidden rounded-xl border border-brand/10">
        <video controls className="max-h-48 w-full">
          <source src={url} type="video/mp4" />
          Seu navegador nao suporta o elemento de video.
        </video>
      </div>
    );
  }

  return null;
};

const MessagePreview = ({ message }: { message: MensagemLocal }) => {
  const { isDark } = useTheme();

  if (message.type === 'text') {
    const text = typeof message.content === 'string' ? message.content : '';

    return (
      <p className={cx(
        'whitespace-pre-wrap rounded-xl border p-3 text-sm leading-relaxed',
        isDark ? 'border-white/10 bg-white/[0.04] text-white/75' : 'border-brand/10 bg-brand-canvas text-brand/70'
      )}>
        {text || 'Mensagem de texto vazia'}
      </p>
    );
  }

  return <PreviewArquivo tipo={message.type} conteudo={message.content} />;
};

const TimelineIndicator = ({
  activeStepNumber,
  isDark,
  onAddStep,
  onEditStep,
  passos,
}: {
  activeStepNumber?: number;
  isDark: boolean;
  onAddStep: () => void;
  onEditStep: (stepNumber: number) => void;
  passos: PassoLocal[];
}) => {
  return (
    <div className="relative space-y-3">
      <div className={cx('absolute bottom-8 left-5 top-6 w-px', isDark ? 'bg-white/10' : 'bg-brand/10')} />

      {passos.map((step) => {
        const isActive = activeStepNumber === step.step_number;

        return (
          <button
            key={step.step_number}
            type="button"
            onClick={() => onEditStep(step.step_number)}
            className={cx(
              'relative flex w-full items-center gap-3 rounded-2xl border p-3 text-left transition-all',
              isActive
                ? isDark
                  ? 'border-white/20 bg-white/10 text-white'
                  : 'border-brand bg-brand text-white shadow-flat-md'
                : isDark
                  ? 'border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/[0.08]'
                  : 'border-brand/10 bg-white text-brand hover:bg-brand-canvas'
            )}
          >
            <span className={cx(
              'z-10 grid h-10 w-10 shrink-0 place-items-center rounded-xl text-sm font-semibold',
              isActive
                ? isDark ? 'bg-white text-brand' : 'bg-white text-brand'
                : isDark ? 'bg-brand text-white' : 'bg-brand text-white'
            )}>
              {step.step_number}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold">Passo {step.step_number}</span>
              <span className={cx(
                'mt-0.5 flex flex-wrap items-center gap-2 text-xs',
                isActive ? isDark ? 'text-white/65' : 'text-white/70' : isDark ? 'text-white/45' : 'text-brand/45'
              )}>
                <span className="inline-flex items-center gap-1">
                  <Timer className="h-3.5 w-3.5" />
                  {formatDelay(step)}
                </span>
                <span className="inline-flex items-center gap-1">
                  <MessageCircle className="h-3.5 w-3.5" />
                  {step.messages.length} {step.messages.length === 1 ? 'mensagem' : 'mensagens'}
                </span>
              </span>
            </span>
            <Edit2 className={cx('h-4 w-4 shrink-0', isActive ? 'opacity-80' : 'opacity-45')} />
          </button>
        );
      })}

      {passos.length < MAX_PASSOS && (
        <button
          type="button"
          onClick={onAddStep}
          className={cx(
            'relative flex w-full items-center gap-3 rounded-2xl border border-dashed p-3 text-left text-sm font-semibold transition-colors',
            isDark ? 'border-white/15 text-white/60 hover:bg-white/[0.06] hover:text-white' : 'border-brand/15 text-brand/55 hover:bg-brand-canvas hover:text-brand'
          )}
        >
          <span className={cx('z-10 grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-dashed', isDark ? 'border-white/20 bg-brand' : 'border-brand/20 bg-white')}>
            <Plus className="h-4 w-4" />
          </span>
          Adicionar passo
        </button>
      )}
    </div>
  );
};

const WhatsAppMessageBubble = ({ message }: { message: MensagemLocal }) => {
  const meta = getMessageTypeMeta(message.type);
  const Icon = meta.icon;

  if (message.type === 'text') {
    const text = typeof message.content === 'string' ? message.content : '';

    return (
      <div className="ml-auto max-w-[84%] rounded-2xl rounded-tr-sm bg-[#dcf8c6] px-3 py-2 text-sm leading-relaxed text-[#1f2c34] shadow-sm">
        <p className="whitespace-pre-wrap">{text || 'Mensagem de texto vazia'}</p>
        <div className="mt-1 flex justify-end gap-1 text-[10px] text-[#667781]">
          <span>09:41</span>
          <Check className="h-3 w-3" />
        </div>
      </div>
    );
  }

  if (message.type === 'image' && typeof message.content === 'string' && message.content) {
    return (
      <div className="ml-auto max-w-[84%] overflow-hidden rounded-2xl rounded-tr-sm bg-[#dcf8c6] p-1.5 shadow-sm">
        <img src={getStoredFileUrl(message.content)} alt="Preview WhatsApp" className="max-h-44 w-full rounded-xl object-cover" />
        <div className="mt-1 flex justify-end gap-1 px-1 text-[10px] text-[#667781]">
          <span>09:41</span>
          <Check className="h-3 w-3" />
        </div>
      </div>
    );
  }

  return (
    <div className="ml-auto max-w-[84%] rounded-2xl rounded-tr-sm bg-[#dcf8c6] px-3 py-2 text-sm text-[#1f2c34] shadow-sm">
      <div className="flex items-center gap-2">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-white/65 text-[#075e54]">
          <Icon className="h-4 w-4" />
        </span>
        <span className="min-w-0">
          <span className="block font-semibold">{meta.label}</span>
          <span className="block truncate text-xs text-[#667781]">
            {getFileName(message.content) || 'Arquivo pendente'}
          </span>
        </span>
      </div>
      <div className="mt-1 flex justify-end gap-1 text-[10px] text-[#667781]">
        <span>09:41</span>
        <Check className="h-3 w-3" />
      </div>
    </div>
  );
};

const WhatsAppPreview = ({
  editandoPasso,
  isDark,
  passos,
  selectedStageName,
}: {
  editandoPasso: PassoLocal | null;
  isDark: boolean;
  passos: PassoLocal[];
  selectedStageName: string;
}) => {
  const previewSteps = editandoPasso ? [editandoPasso] : passos;
  const hasMessages = previewSteps.some(step => step.messages.length > 0);

  return (
    <aside className={agentivePanelClass(isDark, 'overflow-hidden p-0 xl:sticky xl:top-4')}>
      <div className={cx('border-b p-4', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas')}>
        <div className="flex items-center gap-3">
          <div className={cx('grid h-10 w-10 place-items-center rounded-xl', isDark ? 'bg-white/10 text-white' : 'bg-brand text-white')}>
            <Smartphone className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold">Preview WhatsApp</h2>
            <p className={cx('truncate text-xs', isDark ? 'text-white/50' : 'text-brand/50')}>{selectedStageName}</p>
          </div>
        </div>
      </div>

      <div className="p-4">
        <div className="mx-auto max-w-[360px] overflow-hidden rounded-[28px] border border-brand/20 bg-brand p-2 shadow-[0_18px_44px_rgba(2,3,35,0.2)]">
          <div className="overflow-hidden rounded-[22px] bg-[#efeae2]">
            <div className="flex items-center gap-3 bg-[#075e54] px-3 py-3 text-white">
              <div className="grid h-9 w-9 place-items-center rounded-full bg-white/15">
                <WhatsAppIcon className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{branding.appName} Follow-up</p>
                <p className="text-[11px] text-white/70">online</p>
              </div>
              <Send className="h-4 w-4 text-white/70" />
            </div>

            <div className="min-h-[420px] max-h-[560px] space-y-3 overflow-y-auto px-3 py-4">
              <div className="mx-auto w-fit max-w-[88%] rounded-xl bg-white/75 px-3 py-2 text-center text-[11px] leading-relaxed text-[#54656f] shadow-sm">
                Hoje
              </div>

              {!hasMessages ? (
                <div className="mt-20 text-center text-sm text-[#667781]">
                  <MessageCircle className="mx-auto mb-2 h-8 w-8 opacity-40" />
                  Nenhuma mensagem nesta etapa
                </div>
              ) : (
                previewSteps.map(step => (
                  <React.Fragment key={`preview-${step.step_number}`}>
                    <div className="mx-auto w-fit rounded-full bg-white/75 px-3 py-1 text-[11px] font-medium text-[#54656f] shadow-sm">
                      Passo {step.step_number} - {formatDelay(step)}
                    </div>
                    {[...step.messages]
                      .sort((a, b) => (a.id ?? 0) - (b.id ?? 0))
                      .map((message, index) => (
                        <WhatsAppMessageBubble key={`${step.step_number}-${index}-${message.id || 'new'}`} message={message} />
                      ))}
                  </React.Fragment>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
};

const FollowUp: React.FC = () => {
  const { isDark } = useTheme();
  const [passos, setPassos] = useState<PassoLocal[]>([]);
  const [editandoPasso, setEditandoPasso] = useState<PassoLocal | null>(null);

  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [activeTab, setActiveTab] = useState<FollowUpTab>('sequence');
  const [savedStatus, setSavedStatus] = useState<SavedStatus>(null);

  const [stages, setStages] = useState<PipelineStage[]>([]);
  const [selectedStageId, setSelectedStageId] = useState<number | null>(null);
  const [currentSequenceId, setCurrentSequenceId] = useState<number | null>(null);

  const [scheduleExists, setScheduleExists] = useState(false);
  const [scheduleEditMode, setScheduleEditMode] = useState(false);
  const [showDeleteScheduleModal, setShowDeleteScheduleModal] = useState(false);
  const [messageDeleteTarget, setMessageDeleteTarget] = useState<MessageDeleteTarget | null>(null);
  const [stepDeleteTarget, setStepDeleteTarget] = useState<StepDeleteTarget | null>(null);

  const [schedule, setSchedule] = useState<ScheduleData>(() => createDefaultSchedule());

  const selectedStage = useMemo(
    () => stages.find(stage => stage.id === selectedStageId) || null,
    [selectedStageId, stages]
  );

  const totalMessages = useMemo(
    () => passos.reduce((total, step) => total + step.messages.length, 0),
    [passos]
  );

  const configuredStages = useMemo(
    () => stages.filter(stage => isStageConfigured(stage, selectedStageId, currentSequenceId)).length,
    [currentSequenceId, selectedStageId, stages]
  );

  const enabledScheduleDays = useMemo(() => getScheduleEnabledCount(schedule), [schedule]);

  useEffect(() => {
    const companyIdStr = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
    if (!companyIdStr) return;
    const companyIdNum = Number(companyIdStr);
    if (!companyIdNum) return;

    carregarStages();
    carregarScheduleConfig(companyIdNum);
  }, []);

  useEffect(() => {
    if (!selectedStageId) return;

    const stage = stages.find(s => s.id === selectedStageId);
    setEditandoPasso(null);

    if (stage && stage.follow_up_sequence_id) {
      carregarSequenciaEspecifica(stage.follow_up_sequence_id);
    } else {
      setPassos([]);
      setCurrentSequenceId(null);
    }
  }, [selectedStageId, stages]);

  useEffect(() => {
    if (erro || sucesso) {
      const timer = setTimeout(() => {
        setErro(null);
        setSucesso(null);
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [erro, sucesso]);

  const carregarStages = async () => {
    try {
      const pipelines = await pipelineApi.getPipelines();
      if (pipelines.length > 0) {
        const stagesData = await pipelineApi.getStages(pipelines[0].id);
        setStages(stagesData);
        if (stagesData.length > 0 && !selectedStageId) {
          setSelectedStageId(stagesData[0].id);
        }
      }
    } catch (error) {
      console.error('Erro ao carregar stages', error);
      setErro('Erro ao carregar etapas do funil');
    }
  };

  const carregarSequenciaEspecifica = async (sequenceId: number) => {
    try {
      setCarregando(true);
      const seq = await getSingleFollowUpSequence(sequenceId);
      if (seq) {
        setCurrentSequenceId(seq.id);
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
        passosConvertidos.sort((a, b) => a.step_number - b.step_number);
        setPassos(passosConvertidos);
      }
    } catch (error) {
      console.error('Erro ao carregar sequência', error);
      setErro('Erro ao carregar sequência do estágio');
    } finally {
      setCarregando(false);
    }
  };

  const carregarScheduleConfig = async (companyId: number) => {
    try {
      const resp = await getFollowUpScheduleConfig(companyId);
      if (resp) {
        setSchedule(mergeScheduleData(resp.schedule_data, createDefaultSchedule()));
        setScheduleExists(true);
        setScheduleEditMode(false);
      }
    } catch (error) {
      console.log('Nenhuma config de horarios encontrada ou erro:', error);
      setScheduleExists(false);
    }
  };

  const handleSaveScheduleConfig = async () => {
    try {
      setSavedStatus('saving');
      const companyIdStr = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
      if (!companyIdStr) throw new Error('company_id nao encontrado');
      const companyIdNum = Number(companyIdStr);

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
        await createFollowUpScheduleConfig(companyIdNum, schedulePayload);
        setScheduleExists(true);
      } else {
        await updateFollowUpScheduleConfig(companyIdNum, schedulePayload);
      }

      setScheduleEditMode(false);
      setSavedStatus('saved');
      setTimeout(() => setSavedStatus(null), 2000);
    } catch (error) {
      console.error('Erro ao salvar config de horarios:', error);
      setSavedStatus('error');
    }
  };

  const handleDeleteScheduleConfig = async () => {
    try {
      setCarregando(true);
      const companyIdStr = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
      if (!companyIdStr) throw new Error('company_id nao encontrado');
      const companyIdNum = Number(companyIdStr);

      await deleteFollowUpScheduleConfig(companyIdNum);
      setScheduleExists(false);
      setScheduleEditMode(false);
      setSchedule(createDefaultSchedule());
      setShowDeleteScheduleModal(false);
      setSucesso('Configuracao de horarios excluida com sucesso.');
    } catch (error) {
      console.error('Erro ao deletar config de horarios:', error);
      setErro('Falha ao excluir configuracao de horarios');
    } finally {
      setCarregando(false);
    }
  };

  const salvarConfig = async () => {
    try {
      setSavedStatus('saving');

      const companyIdStr = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
      const clientIdStr = localStorage.getItem('client_id');
      if (!companyIdStr || !clientIdStr) {
        throw new Error('ID da empresa ou cliente nao encontrado');
      }

      const companyIdNum = Number(companyIdStr);

      const passosAPI: PassoAPI[] = await Promise.all(
        passos.map(async (passoLocal) => {
          const messagesSorted = passoLocal.messages
            .slice()
            .sort((a, b) => (a.id ?? 0) - (b.id ?? 0));

          const messagesAPI = await Promise.all(
            messagesSorted.map(async (msgLocal) => {
              if (msgLocal.type !== 'text' && isFile(msgLocal.content)) {
                const file = msgLocal.content as File;
                const limiteArquivo = LIMITE_ARQUIVOS[msgLocal.type];
                if (file.size > limiteArquivo) {
                  throw new Error(
                    `Arquivo muito grande. Max p/ ${msgLocal.type}: ${limiteArquivo / (1024 * 1024)}MB`
                  );
                }
                const resultadoUpload = await uploadFile(file);
                return {
                  id: msgLocal.id,
                  type: msgLocal.type,
                  content: resultadoUpload.path,
                } as MensagemAPI;
              } else if (typeof msgLocal.content === 'string') {
                return {
                  id: msgLocal.id,
                  type: msgLocal.type,
                  content: msgLocal.content,
                } as MensagemAPI;
              }

              throw new Error('Tipo de conteudo inesperado.');
            })
          );

          return {
            id: passoLocal.id,
            step_number: passoLocal.step_number,
            send_after: passoLocal.send_after,
            send_after_unit: passoLocal.send_after_unit,
            messages: messagesAPI,
          } as PassoAPI;
        })
      );

      const payload = {
        company_id: companyIdNum,
        client_id: clientIdStr,
        name: `Sequencia - Stage ${selectedStageId}`,
        description: 'Sequencia configurada via FollowUp-v2',
        steps: passosAPI,
        linked_stage_id: selectedStageId || undefined
      };

      if (currentSequenceId) {
        await updateFollowUpSequence(currentSequenceId, payload);
      } else {
        const newSeq = await createFollowUpSequence(companyIdNum, payload);
        setCurrentSequenceId(newSeq.sequence_id);
        setStages(prev => prev.map(s => s.id === selectedStageId ? { ...s, follow_up_sequence_id: newSeq.sequence_id } : s));
      }

      setSavedStatus('saved');
      setTimeout(() => setSavedStatus(null), 2000);
      setEditandoPasso(null);
    } catch (err) {
      setErro('Falha ao salvar configuracao');
      setSavedStatus('error');
      console.error(err);
    }
  };

  const adicionarPasso = () => {
    if (passos.length >= MAX_PASSOS) {
      setErro(`Numero maximo de passos (${MAX_PASSOS}) atingido`);
      return;
    }
    const novoPasso: PassoLocal = {
      step_number: passos.length + 1,
      send_after: 1,
      send_after_unit: 'days',
      messages: [],
    };
    setPassos([...passos, novoPasso]);
    setEditandoPasso(novoPasso);
  };

  const editarPasso = (numeroPasso: number) => {
    const passo = passos.find(p => p.step_number === numeroPasso);
    if (passo) {
      setEditandoPasso({
        ...passo,
        messages: [...passo.messages].sort((a, b) => (a.id ?? 0) - (b.id ?? 0))
      });
    }
  };

  const atualizarPasso = (passoAtualizado: PassoLocal) => {
    setPassos((prev) =>
      prev.map((p) => (p.step_number === passoAtualizado.step_number ? passoAtualizado : p))
    );
    setEditandoPasso(passoAtualizado);
  };

  const adicionarMensagem = (numeroPasso: number) => {
    const passoAlvo = passos.find((p) => p.step_number === numeroPasso);
    if (!passoAlvo) return;
    if (passoAlvo.messages.length >= MAX_MENSAGENS_POR_PASSO) {
      setErro(`Numero maximo de mensagens por passo (${MAX_MENSAGENS_POR_PASSO}) atingido`);
      return;
    }

    const mensagensOrdenadas = [...passoAlvo.messages].sort((a, b) => (a.id ?? 0) - (b.id ?? 0));
    const novoPassoComMensagem: PassoLocal = {
      ...passoAlvo,
      messages: [...mensagensOrdenadas, { type: 'text', content: '' }],
    };

    setPassos((prev) =>
      prev.map((p) => (p.step_number === numeroPasso ? novoPassoComMensagem : p))
    );

    setEditandoPasso(novoPassoComMensagem);
  };

  const excluirPasso = (passoParaExcluir: PassoLocal) => {
    setPassos((prev) => renumberSteps(
      prev.filter((passo) => passo.step_number !== passoParaExcluir.step_number)
    ));

    setEditandoPasso((prev) => {
      if (!prev) return prev;
      if (prev.step_number === passoParaExcluir.step_number) return null;
      if (prev.step_number > passoParaExcluir.step_number) {
        return {
          ...prev,
          step_number: prev.step_number - 1,
        };
      }
      return prev;
    });

    setStepDeleteTarget(null);
  };

  const deletarMensagem = async (numeroPasso: number, indiceMensagem: number) => {
    try {
      const passoIndex = passos.findIndex((p) => p.step_number === numeroPasso);
      if (passoIndex === -1) return;
      const passo = passos[passoIndex];

      const mensagensOrdenadas = [...passo.messages].sort((a, b) => (a.id ?? 0) - (b.id ?? 0));
      const mensagem = mensagensOrdenadas[indiceMensagem];

      if (mensagem && mensagem.type !== 'text' && typeof mensagem.content === 'string') {
        const fileName = mensagem.content.split('/').pop();
        if (fileName) {
          try {
            await deleteFile(fileName);
          } catch (error) {
            console.warn(`Nao foi possivel deletar arquivo ${fileName}:`, error);
          }
        }
      }

      const mensagensAtualizadas = [...mensagensOrdenadas];
      mensagensAtualizadas.splice(indiceMensagem, 1);

      const passoAtualizado = { ...passo, messages: mensagensAtualizadas };

      setPassos((prev) =>
        prev.map((p) => (p.step_number === numeroPasso ? passoAtualizado : p))
      );

      setEditandoPasso(passoAtualizado);
      setMessageDeleteTarget(null);
    } catch (err) {
      setErro('Falha ao remover mensagem');
      console.error(err);
    }
  };

  const alterarMensagem = (
    numeroPasso: number,
    indiceMensagem: number,
    messageType: MensagemLocal['type'],
    conteudo: string | File | any
  ) => {
    const passoIndex = passos.findIndex((p) => p.step_number === numeroPasso);
    if (passoIndex === -1) return;

    const passo = passos[passoIndex];
    const mensagensOrdenadas = [...passo.messages].sort((a, b) => (a.id ?? 0) - (b.id ?? 0));
    const oldMsg = mensagensOrdenadas[indiceMensagem];

    mensagensOrdenadas[indiceMensagem] = {
      id: oldMsg?.id,
      type: messageType,
      content: conteudo,
    };

    const passoAtualizado = { ...passo, messages: mensagensOrdenadas };

    setPassos((prev) =>
      prev.map((p) => (p.step_number === numeroPasso ? passoAtualizado : p))
    );

    setEditandoPasso(passoAtualizado);
  };

  const handleStageSelect = (stageId: number | null) => {
    setSelectedStageId(stageId);
    setActiveTab('sequence');
  };

  const renderSavedStatus = () => {
    if (!savedStatus) return null;

    const meta = {
      saving: { variant: 'info' as const, title: 'Salvando alteracoes', message: 'Aguarde enquanto a configuracao e atualizada.' },
      saved: { variant: 'success' as const, title: 'Alteracoes salvas', message: 'A sequencia foi atualizada com sucesso.' },
      error: { variant: 'error' as const, title: 'Erro ao salvar', message: 'Revise os dados e tente novamente.' },
    }[savedStatus];

    return (
      <AgentiveAlert variant={meta.variant} title={meta.title}>
        <div className="flex items-center gap-2">
          {savedStatus === 'saving' && <Loader2 className="h-4 w-4 animate-spin" />}
          <span>{meta.message}</span>
        </div>
      </AgentiveAlert>
    );
  };

  const renderTabs = () => (
    <div className={cx('grid w-full grid-cols-2 gap-1 rounded-2xl border p-1.5', isDark ? 'border-white/10 bg-black/15' : 'border-brand/10 bg-brand-canvas')}>
      {[
        { id: 'sequence' as const, label: 'Mensagens', description: 'Cadencia por etapa', icon: MessageCircle },
        { id: 'schedule' as const, label: 'Horarios', description: 'Janelas de envio', icon: Calendar },
      ].map(tab => {
        const Icon = tab.icon;
        const isActive = activeTab === tab.id;

        return (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            className={cx(
              'group flex min-w-0 items-center gap-2 rounded-xl border px-3 py-2 text-left transition-all',
              isActive
                ? isDark
                  ? 'border-white bg-white text-brand shadow-[0_10px_24px_rgba(255,255,255,0.08)]'
                  : 'border-brand bg-brand text-white shadow-[0_10px_24px_rgba(2,3,35,0.12)]'
                : isDark
                  ? 'border-transparent text-white/55 hover:border-white/10 hover:bg-white/[0.06] hover:text-white'
                  : 'border-transparent text-brand/55 hover:border-brand/10 hover:bg-white hover:text-brand'
            )}
          >
            <span className={cx(
              'grid h-8 w-8 shrink-0 place-items-center rounded-lg transition-colors',
              isActive
                ? isDark ? 'bg-brand text-white' : 'bg-white text-brand'
                : isDark ? 'bg-white/10 text-white/55 group-hover:text-white' : 'bg-white text-brand/50 group-hover:text-brand'
            )}>
              <Icon className="h-4 w-4" />
            </span>
            <span className="min-w-0">
              <span className="block truncate text-sm font-semibold">{tab.label}</span>
              <span className={cx('hidden truncate text-[10px] leading-tight sm:block', isActive ? isDark ? 'text-brand/55' : 'text-white/60' : isDark ? 'text-white/35' : 'text-brand/35')}>
                {tab.description}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );

  const renderStageSelector = () => (
    <>
      <div className="xl:hidden">
        <label className={cx('mb-1.5 block text-xs font-semibold uppercase tracking-[0.12em]', isDark ? 'text-white/45' : 'text-brand/45')}>
          Etapa do funil
        </label>
        <div className="relative">
          <select
            value={selectedStageId || ''}
            onChange={(event) => handleStageSelect(event.target.value ? Number(event.target.value) : null)}
            className={cx(agentiveInputClass(isDark), 'appearance-none pr-10 font-semibold')}
          >
            <option value="" disabled>Selecione uma etapa</option>
            {stages.map(stage => (
              <option key={stage.id} value={stage.id}>
                {stage.name}
              </option>
            ))}
          </select>
          <ChevronDown className={cx('pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2', isDark ? 'text-white/45' : 'text-brand/45')} />
        </div>
      </div>

      <aside className={agentivePanelClass(isDark, 'hidden p-3 xl:block')}>
        <div className="mb-3 flex items-center justify-between gap-3 px-1">
          <div>
            <p className={cx('text-[10px] font-bold uppercase tracking-[0.16em]', isDark ? 'text-white/35' : 'text-brand/35')}>
              Funil
            </p>
            <h2 className="mt-1 text-base font-semibold">Etapas</h2>
          </div>
          <span className={cx('rounded-full px-2.5 py-1 text-xs font-semibold', isDark ? 'bg-white/10 text-white/65' : 'bg-brand-canvas text-brand/65')}>
            {configuredStages}/{stages.length}
          </span>
        </div>

        <div className="max-h-[calc(100vh-260px)] space-y-2 overflow-y-auto pr-1">
          {stages.length === 0 ? (
            <div className={cx('rounded-2xl border border-dashed p-5 text-center text-sm', isDark ? 'border-white/10 text-white/45' : 'border-brand/15 text-brand/45')}>
              Nenhuma etapa encontrada
            </div>
          ) : stages.map(stage => {
            const isSelected = stage.id === selectedStageId;
            const configured = isStageConfigured(stage, selectedStageId, currentSequenceId);

            return (
              <button
                key={stage.id}
                type="button"
                onClick={() => handleStageSelect(stage.id)}
                className={cx(
                  'w-full rounded-2xl border p-3 text-left transition-all',
                  isSelected
                    ? isDark
                      ? 'border-white bg-white text-brand shadow-flat-md'
                      : 'border-brand bg-brand text-white shadow-flat-md'
                    : isDark
                      ? 'border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/[0.08]'
                      : 'border-brand/10 bg-white text-brand hover:bg-brand-canvas'
                )}
              >
                <div className="flex items-start gap-3">
                  <span
                    className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full ring-4 ring-current/10"
                    style={{ backgroundColor: stage.color || '#020323' }}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">{stage.name}</span>
                    <span className={cx('mt-1 flex items-center gap-1 text-xs', isSelected ? isDark ? 'text-brand/55' : 'text-white/65' : isDark ? 'text-white/40' : 'text-brand/45')}>
                      {configured ? (
                        <>
                          <Check className="h-3.5 w-3.5" />
                          Sequencia configurada
                        </>
                      ) : (
                        <>
                          <Plus className="h-3.5 w-3.5" />
                          Sem sequencia
                        </>
                      )}
                    </span>
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </aside>
    </>
  );

  const renderSequenceOverview = () => (
    <div className="space-y-4">
      <div className={agentivePanelClass(isDark, 'p-4 sm:p-5')}>
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className={cx('text-[10px] font-bold uppercase tracking-[0.16em]', isDark ? 'text-white/35' : 'text-brand/35')}>
              Etapa selecionada
            </p>
            <h2 className="mt-1 text-xl font-semibold">{getStageName(selectedStage)}</h2>
            <p className={cx('mt-1 text-sm', isDark ? 'text-white/55' : 'text-brand/55')}>
              {currentSequenceId ? `Sequencia vinculada #${currentSequenceId}` : 'Crie uma sequencia para esta etapa do funil.'}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={adicionarPasso}
              disabled={passos.length >= MAX_PASSOS || carregando}
              className={agentiveSecondaryButtonClass(isDark)}
            >
              <Plus className="h-4 w-4" />
              Novo passo
            </button>
            <button
              type="button"
              onClick={salvarConfig}
              disabled={passos.length === 0 || carregando}
              className={cx(
                'inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition-colors disabled:opacity-50',
                isDark ? 'bg-white text-brand hover:bg-white/90' : 'bg-brand text-white hover:bg-brand/90'
              )}
            >
              {savedStatus === 'saving' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              Salvar
            </button>
          </div>
        </div>

        {carregando ? (
          <div className={cx('flex min-h-56 items-center justify-center rounded-2xl border', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas')}>
            <Loader2 className="h-7 w-7 animate-spin opacity-60" />
          </div>
        ) : passos.length > 0 ? (
          <TimelineIndicator
            activeStepNumber={editandoPasso?.step_number}
            isDark={isDark}
            passos={passos}
            onEditStep={editarPasso}
            onAddStep={adicionarPasso}
          />
        ) : (
          <AgentiveEmptyState
            icon={MessageCircle}
            title="Nenhum passo configurado"
            description="Esta etapa ainda nao tem cadencia de follow-up."
            action={(
              <button
                type="button"
                onClick={adicionarPasso}
                className={cx(
                  'inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition-colors',
                  isDark ? 'bg-white text-brand hover:bg-white/90' : 'bg-brand text-white hover:bg-brand/90'
                )}
              >
                <Plus className="h-4 w-4" />
                Adicionar primeiro passo
              </button>
            )}
          />
        )}
      </div>

      {passos.length > 0 && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {passos.map((passo) => {
            const messagesSorted = passo.messages
              .slice()
              .sort((a, b) => (a.id ?? 0) - (b.id ?? 0));

            return (
              <article key={passo.step_number} className={agentivePanelClass(isDark, 'overflow-hidden p-0 transition hover:-translate-y-0.5 hover:shadow-flat-lg')}>
                <div className={cx('flex items-center justify-between gap-3 border-b p-4', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas')}>
                  <div className="flex min-w-0 items-center gap-3">
                    <span className={cx('grid h-10 w-10 shrink-0 place-items-center rounded-xl text-sm font-semibold', isDark ? 'bg-white text-brand' : 'bg-brand text-white')}>
                      {passo.step_number}
                    </span>
                    <div className="min-w-0">
                      <h3 className="truncate font-semibold">Passo {passo.step_number}</h3>
                      <p className={cx('mt-0.5 text-xs', isDark ? 'text-white/45' : 'text-brand/45')}>
                        {formatDelay(passo)}
                      </p>
                    </div>
                  </div>

                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      type="button"
                      className={agentiveIconButtonClass(isDark, 'primary')}
                      onClick={() => editarPasso(passo.step_number)}
                      aria-label={`Editar passo ${passo.step_number}`}
                    >
                      <Edit2 className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      className={agentiveIconButtonClass(isDark, 'danger')}
                      onClick={() => setStepDeleteTarget({ step: passo })}
                      aria-label={`Excluir passo ${passo.step_number}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>

                <div className="space-y-4 p-4">
                  {messagesSorted.length > 0 ? (
                    messagesSorted.map((message, msgIndex) => {
                      const meta = getMessageTypeMeta(message.type);
                      const Icon = meta.icon;

                      return (
                        <div key={`${passo.step_number}-${msgIndex}-${message.id || 'new'}`}>
                          <div className="mb-2 flex items-center gap-2">
                            <span className={cx('grid h-7 w-7 place-items-center rounded-lg', isDark ? 'bg-white/10 text-white/65' : 'bg-brand-canvas text-brand/60')}>
                              <Icon className="h-3.5 w-3.5" />
                            </span>
                            <span className={cx('text-sm font-medium', isDark ? 'text-white/60' : 'text-brand/60')}>
                              Mensagem {msgIndex + 1} - {meta.label}
                            </span>
                          </div>
                          <MessagePreview message={message} />
                        </div>
                      );
                    })
                  ) : (
                    <div className={cx('rounded-2xl border border-dashed p-6 text-center text-sm', isDark ? 'border-white/10 text-white/45' : 'border-brand/15 text-brand/45')}>
                      Nenhuma mensagem definida
                    </div>
                  )}

                  {messagesSorted.length < MAX_MENSAGENS_POR_PASSO && (
                    <button
                      type="button"
                      onClick={() => adicionarMensagem(passo.step_number)}
                      className={cx(
                        'inline-flex w-full items-center justify-center gap-2 rounded-xl border border-dashed px-3 py-2 text-sm font-semibold transition-colors',
                        isDark ? 'border-white/15 text-white/60 hover:bg-white/[0.06] hover:text-white' : 'border-brand/15 text-brand/55 hover:bg-brand-canvas hover:text-brand'
                      )}
                    >
                      <Plus className="h-4 w-4" />
                      Adicionar mensagem
                    </button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );

  const renderStepEditor = () => {
    if (!editandoPasso) return renderSequenceOverview();

    return (
      <div className={agentivePanelClass(isDark, 'overflow-hidden p-0')}>
        <div className={cx('flex items-center justify-between gap-3 border-b p-4 sm:p-5', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas')}>
          <div className="flex min-w-0 items-center gap-3">
            <span className={cx('grid h-11 w-11 shrink-0 place-items-center rounded-xl text-base font-semibold', isDark ? 'bg-white text-brand' : 'bg-brand text-white')}>
              {editandoPasso.step_number}
            </span>
            <div className="min-w-0">
              <p className={cx('text-[10px] font-bold uppercase tracking-[0.16em]', isDark ? 'text-white/35' : 'text-brand/35')}>
                Editor de passo
              </p>
              <h2 className="truncate text-lg font-semibold">Passo {editandoPasso.step_number}</h2>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              className={agentiveIconButtonClass(isDark, 'danger')}
              onClick={() => setStepDeleteTarget({ step: editandoPasso })}
              aria-label={`Excluir passo ${editandoPasso.step_number}`}
            >
              <Trash2 className="h-4 w-4" />
            </button>
            <button
              type="button"
              className={agentiveIconButtonClass(isDark)}
              onClick={() => setEditandoPasso(null)}
              aria-label="Fechar editor"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="space-y-6 p-4 sm:p-5">
          <div className="grid gap-4 sm:grid-cols-[120px_minmax(0,180px)_1fr]">
            <div>
              <label className={cx('mb-1.5 block text-xs font-semibold uppercase tracking-[0.08em]', isDark ? 'text-white/45' : 'text-brand/45')}>
                Intervalo
              </label>
              <input
                type="number"
                min="1"
                value={editandoPasso.send_after}
                onChange={(e) => atualizarPasso({
                  ...editandoPasso,
                  send_after: parseInt(e.target.value || '1', 10),
                })}
                className={agentiveInputClass(isDark)}
              />
            </div>

            <div>
              <label className={cx('mb-1.5 block text-xs font-semibold uppercase tracking-[0.08em]', isDark ? 'text-white/45' : 'text-brand/45')}>
                Unidade
              </label>
              <select
                value={editandoPasso.send_after_unit}
                onChange={(e) => atualizarPasso({
                  ...editandoPasso,
                  send_after_unit: e.target.value as PassoLocal['send_after_unit'],
                })}
                className={agentiveInputClass(isDark)}
              >
                {timeUnits.map(unit => (
                  <option key={unit.value} value={unit.value}>{unit.label}</option>
                ))}
              </select>
            </div>

            <div className={cx('rounded-2xl border p-3', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas')}>
              <div className="flex items-center gap-2">
                <Timer className={cx('h-4 w-4', isDark ? 'text-white/50' : 'text-brand/50')} />
                <span className="text-sm font-semibold">{formatDelay(editandoPasso)}</span>
              </div>
              <p className={cx('mt-1 text-xs', isDark ? 'text-white/45' : 'text-brand/45')}>
                Este passo sera disparado dentro da janela de horarios configurada.
              </p>
            </div>
          </div>

          <div>
            <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="text-base font-semibold">Mensagens</h3>
                <p className={cx('text-sm', isDark ? 'text-white/50' : 'text-brand/50')}>
                  {editandoPasso.messages.length}/{MAX_MENSAGENS_POR_PASSO} mensagens neste passo
                </p>
              </div>
              {editandoPasso.messages.length < MAX_MENSAGENS_POR_PASSO && (
                <button
                  type="button"
                  onClick={() => adicionarMensagem(editandoPasso.step_number)}
                  className={agentiveSecondaryButtonClass(isDark)}
                >
                  <Plus className="h-4 w-4" />
                  Adicionar mensagem
                </button>
              )}
            </div>

            {editandoPasso.messages.length > 0 ? (
              <div className="space-y-4">
                {[...editandoPasso.messages]
                  .sort((a, b) => (a.id ?? 0) - (b.id ?? 0))
                  .map((message, index) => {
                    const meta = getMessageTypeMeta(message.type);
                    const Icon = meta.icon;

                    return (
                      <div key={`${editandoPasso.step_number}-${index}-${message.id || 'new'}`} className={cx('rounded-2xl border p-4', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas')}>
                        <div className="mb-3 flex items-center justify-between gap-3">
                          <div className="flex min-w-0 items-center gap-2">
                            <span className={cx('grid h-8 w-8 shrink-0 place-items-center rounded-lg', isDark ? 'bg-white/10 text-white/65' : 'bg-white text-brand')}>
                              <Icon className="h-4 w-4" />
                            </span>
                            <select
                              value={message.type}
                              onChange={(e) => alterarMensagem(
                                editandoPasso.step_number,
                                index,
                                e.target.value as MensagemLocal['type'],
                                message.type === 'text' && e.target.value !== 'text' ? '' : message.content
                              )}
                              className={cx(agentiveInputClass(isDark), 'h-10 max-w-[180px] py-1.5 text-sm font-semibold')}
                            >
                              {messageTypes.map(type => (
                                <option key={type.value} value={type.value}>{type.label}</option>
                              ))}
                            </select>
                          </div>

                          <button
                            type="button"
                            className={agentiveIconButtonClass(isDark, 'danger')}
                            onClick={() => setMessageDeleteTarget({ stepNumber: editandoPasso.step_number, index, message })}
                            aria-label={`Remover mensagem ${index + 1}`}
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>

                        {message.type === 'text' ? (
                          <div>
                            <textarea
                              value={typeof message.content === 'string' ? message.content : ''}
                              onChange={(e) => alterarMensagem(
                                editandoPasso.step_number,
                                index,
                                'text',
                                e.target.value
                              )}
                              rows={4}
                              className={agentiveTextareaClass(isDark)}
                              placeholder="Digite a mensagem para o lead"
                            />
                            <p className={cx('mt-2 text-xs', isDark ? 'text-white/40' : 'text-brand/40')}>
                              Variaveis: <code className={cx('rounded px-1', isDark ? 'bg-white/10 text-white/70' : 'bg-white text-brand/70')}>{'{first_name}'}</code> ou <code className={cx('rounded px-1', isDark ? 'bg-white/10 text-white/70' : 'bg-white text-brand/70')}>{'{nome}'}</code>
                            </p>
                          </div>
                        ) : (
                          <div className="space-y-3">
                            {typeof message.content === 'string' && message.content && (
                              <div>
                                <p className={cx('mb-2 text-xs font-medium', isDark ? 'text-white/45' : 'text-brand/45')}>
                                  Arquivo atual: {getFileName(message.content)}
                                </p>
                                <PreviewArquivo tipo={message.type} conteudo={message.content} />
                              </div>
                            )}

                            <div className={cx('rounded-2xl border border-dashed p-5 text-center', isDark ? 'border-white/15 bg-white/[0.03]' : 'border-brand/15 bg-white')}>
                              <File className={cx('mx-auto mb-2 h-8 w-8', isDark ? 'text-white/45' : 'text-brand/45')} />
                              <p className={cx('mb-2 text-sm', isDark ? 'text-white/60' : 'text-brand/60')}>
                                {isFile(message.content) ? getFileName(message.content) : `${meta.label} ate ${LIMITE_ARQUIVOS[message.type] / (1024 * 1024)}MB`}
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
                                className={cx(
                                  'inline-flex cursor-pointer items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm font-semibold transition-colors',
                                  isDark ? 'bg-white text-brand hover:bg-white/90' : 'bg-brand text-white hover:bg-brand/90'
                                )}
                              >
                                <File className="h-4 w-4" />
                                {isFile(message.content) ? 'Alterar arquivo' : 'Selecionar arquivo'}
                              </label>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
              </div>
            ) : (
              <AgentiveEmptyState
                icon={MessageCircle}
                title="Nenhuma mensagem neste passo"
                description="Adicione texto ou midia para compor a cadencia."
                action={(
                  <button
                    type="button"
                    onClick={() => adicionarMensagem(editandoPasso.step_number)}
                    className={cx(
                      'inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition-colors',
                      isDark ? 'bg-white text-brand hover:bg-white/90' : 'bg-brand text-white hover:bg-brand/90'
                    )}
                  >
                    <Plus className="h-4 w-4" />
                    Adicionar primeira mensagem
                  </button>
                )}
              />
            )}
          </div>

          <div className={cx('flex flex-col-reverse gap-2 border-t pt-4 sm:flex-row sm:justify-end', isDark ? 'border-white/10' : 'border-brand/10')}>
            <button
              type="button"
              className={cx(
                'inline-flex items-center justify-center gap-2 rounded-xl border px-4 py-2 text-sm font-semibold transition-colors',
                isDark ? 'border-red-400/30 text-red-200 hover:bg-red-400/10' : 'border-red-200 text-red-700 hover:bg-red-50'
              )}
              onClick={() => setStepDeleteTarget({ step: editandoPasso })}
            >
              <Trash2 className="h-4 w-4" />
              Excluir passo
            </button>
            <button
              type="button"
              className={agentiveSecondaryButtonClass(isDark)}
              onClick={() => setEditandoPasso(null)}
            >
              Cancelar
            </button>
            <button
              type="button"
              className={cx(
                'inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition-colors disabled:opacity-50',
                isDark ? 'bg-white text-brand hover:bg-white/90' : 'bg-brand text-white hover:bg-brand/90'
              )}
              onClick={salvarConfig}
              disabled={savedStatus === 'saving'}
            >
              {savedStatus === 'saving' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              Salvar alteracoes
            </button>
          </div>
        </div>
      </div>
    );
  };

  const renderSchedule = () => (
    <div className={agentivePanelClass(isDark, 'p-4 sm:p-5')}>
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className={cx('text-[10px] font-bold uppercase tracking-[0.16em]', isDark ? 'text-white/35' : 'text-brand/35')}>
            Janelas de envio
          </p>
          <h2 className="mt-1 text-xl font-semibold">Horarios do follow-up</h2>
          <p className={cx('mt-1 text-sm', isDark ? 'text-white/55' : 'text-brand/55')}>
            {enabledScheduleDays} {enabledScheduleDays === 1 ? 'dia ativo' : 'dias ativos'} para disparos automaticos.
          </p>
        </div>

        {scheduleExists && !scheduleEditMode ? (
          <button
            type="button"
            className={agentiveSecondaryButtonClass(isDark)}
            onClick={() => setScheduleEditMode(true)}
          >
            <Edit2 className="h-4 w-4" />
            Editar horarios
          </button>
        ) : (
          <button
            type="button"
            className={cx(
              'inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition-colors',
              isDark ? 'bg-white text-brand hover:bg-white/90' : 'bg-brand text-white hover:bg-brand/90'
            )}
            onClick={handleSaveScheduleConfig}
          >
            <Save className="h-4 w-4" />
            Salvar horarios
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
        {daysOfWeek.map(day => {
          const dayData = schedule[day.key] || { enabled: false, start: '09:00', end: '17:00' };
          const canEdit = scheduleEditMode || !scheduleExists;

          return (
            <div
              key={day.key}
              className={cx(
                'rounded-2xl border p-4 transition-colors',
                dayData.enabled
                  ? isDark ? 'border-white/15 bg-white/[0.08]' : 'border-brand/10 bg-brand-canvas'
                  : isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-white'
              )}
            >
              <div className="mb-3 flex items-center justify-between gap-3">
                <span className="text-sm font-semibold">{day.label}</span>
                {canEdit ? (
                  <label className="relative inline-flex cursor-pointer items-center">
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
                      className="peer sr-only"
                    />
                    <span className={cx(
                      "h-5 w-9 rounded-full transition-colors after:absolute after:left-[2px] after:top-[2px] after:h-4 after:w-4 after:rounded-full after:bg-white after:transition-all after:content-[''] peer-checked:after:translate-x-full",
                      dayData.enabled ? 'bg-brand' : isDark ? 'bg-white/20' : 'bg-brand/15'
                    )} />
                  </label>
                ) : (
                  <span className={cx('h-2.5 w-2.5 rounded-full', dayData.enabled ? 'bg-emerald-500' : isDark ? 'bg-white/20' : 'bg-brand/15')} />
                )}
              </div>

              {dayData.enabled ? (
                <div className="space-y-2">
                  {(['start', 'end'] as const).map((field) => (
                    <div key={field}>
                      <label className={cx('mb-1 block text-[10px] font-bold uppercase tracking-[0.12em]', isDark ? 'text-white/35' : 'text-brand/35')}>
                        {field === 'start' ? 'Inicio' : 'Fim'}
                      </label>
                      {canEdit ? (
                        <input
                          type="time"
                          value={dayData[field]}
                          onChange={(e) => {
                            setSchedule((prev) => ({
                              ...prev,
                              [day.key]: { ...prev[day.key], [field]: e.target.value },
                            }));
                          }}
                          className={agentiveInputClass(isDark, 'py-1.5 text-xs')}
                        />
                      ) : (
                        <div className={cx('rounded-xl border px-3 py-2 text-sm font-semibold', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-white')}>
                          {dayData[field]}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className={cx('rounded-xl border border-dashed px-3 py-6 text-center text-sm', isDark ? 'border-white/10 text-white/35' : 'border-brand/15 text-brand/40')}>
                  Inativo
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className={cx('mt-6 overflow-hidden rounded-2xl border', isDark ? 'border-white/10' : 'border-brand/10')}>
        <div className={cx('flex items-center gap-2 border-b px-4 py-3', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas')}>
          <ListChecks className={cx('h-4 w-4', isDark ? 'text-white/55' : 'text-brand/55')} />
          <h3 className="text-sm font-semibold">Visualizacao semanal</h3>
        </div>

        <div className="overflow-x-auto p-4">
          <div className="min-w-[760px]">
            <div className="grid grid-cols-[56px_repeat(7,minmax(0,1fr))] gap-1">
              <div />
              {daysOfWeek.map(day => (
                <div key={day.key} className={cx('pb-2 text-center text-xs font-semibold', isDark ? 'text-white/45' : 'text-brand/45')}>
                  {day.short}
                </div>
              ))}

              <div className="space-y-0 pt-1">
                {weekHours.map(hour => (
                  <div key={hour} className={cx('h-8 pr-2 text-right text-[10px]', isDark ? 'text-white/35' : 'text-brand/35')}>
                    {String(hour).padStart(2, '0')}:00
                  </div>
                ))}
              </div>

              {daysOfWeek.map(day => {
                const dayData = schedule[day.key] || { enabled: false, start: '09:00', end: '17:00' };
                const [startHour] = dayData.start.split(':').map(Number);
                const [endHour] = dayData.end.split(':').map(Number);
                const startOffset = Math.max(0, startHour - 8) * 32;
                const duration = Math.max(24, Math.min(384 - startOffset, (endHour - startHour) * 32));

                return (
                  <div key={day.key} className={cx('relative h-96 overflow-hidden rounded-xl border', isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-white')}>
                    {weekHours.map(hour => (
                      <div key={hour} className={cx('h-8 border-b', isDark ? 'border-white/5' : 'border-brand/5')} />
                    ))}
                    {dayData.enabled && (
                      <div
                        className={cx('absolute left-1 right-1 rounded-xl border px-2 py-1 text-xs font-semibold', isDark ? 'border-white/10 bg-white/15 text-white' : 'border-brand/10 bg-brand text-white')}
                        style={{ top: `${startOffset}px`, height: `${duration}px` }}
                      >
                        {dayData.start} - {dayData.end}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      <div className={cx('mt-6 flex flex-col-reverse gap-2 border-t pt-4 sm:flex-row sm:justify-end', isDark ? 'border-white/10' : 'border-brand/10')}>
        {scheduleExists && (
          scheduleEditMode ? (
            <button
              type="button"
              className={agentiveSecondaryButtonClass(isDark)}
              onClick={() => setScheduleEditMode(false)}
            >
              Cancelar
            </button>
          ) : (
            <button
              type="button"
              className={cx(
                'inline-flex items-center justify-center gap-2 rounded-xl border px-4 py-2 text-sm font-semibold transition-colors',
                isDark ? 'border-red-400/30 text-red-200 hover:bg-red-400/10' : 'border-red-200 text-red-700 hover:bg-red-50'
              )}
              onClick={() => setShowDeleteScheduleModal(true)}
            >
              <Trash2 className="h-4 w-4" />
              Excluir configuracao
            </button>
          )
        )}
      </div>
    </div>
  );

  return (
    <div className={agentivePageClass(isDark, 'px-4 pb-28 pt-4 sm:px-6 lg:px-8 xl:px-10')}>
      <div className="mx-auto max-w-screen-2xl space-y-5">
        <AgentivePageHeader
          icon={Zap}
          title="Follow-up"
          description="Configure cadencias por etapa do funil com preview da mensagem enviada no WhatsApp."
          badges={(
            <>
              <span className={cx('inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset', isDark ? 'bg-white/10 text-white/70 ring-white/10' : 'bg-brand-canvas text-brand/70 ring-brand/10')}>
                <Layers className="h-3.5 w-3.5" />
                {getStageName(selectedStage)}
              </span>
              <span className={cx('inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset', isDark ? 'bg-white/10 text-white/70 ring-white/10' : 'bg-brand-canvas text-brand/70 ring-brand/10')}>
                <MessageCircle className="h-3.5 w-3.5" />
                {passos.length} passos / {totalMessages} mensagens
              </span>
            </>
          )}
          actions={(
            <button
              type="button"
              onClick={salvarConfig}
              disabled={passos.length === 0 || savedStatus === 'saving'}
              className={cx(
                'inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition-colors disabled:opacity-50',
                isDark ? 'bg-white text-brand hover:bg-white/90' : 'bg-brand text-white hover:bg-brand/90'
              )}
            >
              {savedStatus === 'saving' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              Salvar
            </button>
          )}
        />

        {erro && (
          <AgentiveAlert variant="error" title="A acao nao foi concluida" onClose={() => setErro(null)}>
            {erro}
          </AgentiveAlert>
        )}
        {sucesso && (
          <AgentiveAlert variant="success" title="Tudo certo" onClose={() => setSucesso(null)}>
            {sucesso}
          </AgentiveAlert>
        )}
        {renderSavedStatus()}

        <div className="space-y-4">
          <div className={cx(
            'grid gap-4',
            activeTab === 'schedule'
              ? 'xl:grid-cols-[300px_minmax(0,1fr)]'
              : 'xl:grid-cols-[300px_minmax(0,1fr)_380px]'
          )}>
            {renderStageSelector()}

            <main className="min-w-0 space-y-4">
              {renderTabs()}
              {activeTab === 'sequence' ? renderStepEditor() : renderSchedule()}
            </main>

            {activeTab === 'sequence' && (
              <WhatsAppPreview
                editandoPasso={editandoPasso}
                isDark={isDark}
                passos={passos}
                selectedStageName={getStageName(selectedStage)}
              />
            )}
          </div>
        </div>
      </div>

      <AgentiveConfirmModal
        isOpen={Boolean(stepDeleteTarget)}
        onClose={() => setStepDeleteTarget(null)}
        onConfirm={() => {
          if (stepDeleteTarget) {
            excluirPasso(stepDeleteTarget.step);
          }
        }}
        title="Excluir passo?"
        message="Este passo sera removido da sequencia. Depois de salvar, o backend remove o passo que saiu do payload."
        confirmText="Excluir passo"
        variant="danger"
      >
        <span className={cx('text-sm', isDark ? 'text-white/65' : 'text-brand/65')}>
          Passo selecionado: <strong>{stepDeleteTarget?.step.step_number}</strong>
          {stepDeleteTarget && (
            <span> com <strong>{stepDeleteTarget.step.messages.length}</strong> {stepDeleteTarget.step.messages.length === 1 ? 'mensagem' : 'mensagens'}</span>
          )}
        </span>
      </AgentiveConfirmModal>

      <AgentiveConfirmModal
        isOpen={Boolean(messageDeleteTarget)}
        onClose={() => setMessageDeleteTarget(null)}
        onConfirm={() => {
          if (messageDeleteTarget) {
            deletarMensagem(messageDeleteTarget.stepNumber, messageDeleteTarget.index);
          }
        }}
        title="Remover mensagem?"
        message="A mensagem sera retirada deste passo. Se ela tiver midia salva, o arquivo tambem sera removido."
        confirmText="Remover mensagem"
        variant="danger"
      >
        <span className={cx('text-sm', isDark ? 'text-white/65' : 'text-brand/65')}>
          Tipo: <strong>{messageDeleteTarget ? getMessageTypeMeta(messageDeleteTarget.message.type).label : ''}</strong>
        </span>
      </AgentiveConfirmModal>

      <AgentiveConfirmModal
        isOpen={showDeleteScheduleModal}
        onClose={() => setShowDeleteScheduleModal(false)}
        onConfirm={handleDeleteScheduleConfig}
        isLoading={carregando}
        title="Excluir configuracao de horarios?"
        message="Os disparos de follow-up deixam de respeitar estas janelas ate que uma nova configuracao seja salva."
        confirmText="Excluir horarios"
        variant="danger"
      >
        <span className={cx('text-sm', isDark ? 'text-white/65' : 'text-brand/65')}>
          Dias ativos agora: <strong>{enabledScheduleDays}</strong>
        </span>
      </AgentiveConfirmModal>
    </div>
  );
};

export default FollowUp;
