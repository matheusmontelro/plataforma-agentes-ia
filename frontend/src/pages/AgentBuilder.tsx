import React, { memo, useCallback, useEffect, useMemo, useState } from 'react';
import ReactFlow, {
    Background,
    BackgroundVariant,
    Connection,
    ConnectionMode,
    Controls,
    Edge,
    MarkerType,
    MiniMap,
    Node,
    NodeProps,
    Panel,
    Position,
    ReactFlowInstance,
    addEdge,
    useEdgesState,
    useNodesState
} from 'reactflow';
import { useNavigate, useParams } from 'react-router-dom';
import 'reactflow/dist/style.css';
import {
    ArrowLeft,
    Bot,
    Brain,
    Briefcase,
    Building2,
    CalendarClock,
    Check,
    ChevronDown,
    ChevronLeft,
    ChevronRight,
    ClipboardCheck,
    ClipboardList,
    Database,
    DollarSign,
    FileText,
    Gem,
    GitBranch,
    Globe,
    Handshake,
    Headphones,
    Info,
    LifeBuoy,
    Loader2,
    Mail,
    Megaphone,
    MessageCircle,
    Network,
    Phone,
    Plus,
    RefreshCw,
    Save,
    Search,
    Shield,
    ShoppingCart,
    Sparkles,
    Settings,
    Store,
    Target,
    Trash2,
    UserCog,
    UserPlus,
    UserRoundCheck,
    Video,
    Volume2,
    Users,
    Wrench,
    X,
    type LucideIcon
} from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
    AgentVoiceOption,
    AgentWorkforce,
    createAgentWorkforce,
    deleteAgentWorkforceKnowledgeFile,
    getAgentWorkforces,
    listAgentVoiceOptions,
    previewAgentConfig,
    refreshAgentWorkforceKnowledge,
    uploadAgentWorkforceKnowledgeFile,
    updateAgentWorkforce
} from '../services/agentWorkforceApi.ts';
import { getTeams, listUsers } from '../services/api.ts';
import type { Team, User } from '../services/api.ts';
import { getAIProvider } from '../services/aiProviderApi.ts';
import { calendarApi, type Agenda } from '../services/calendar_api.ts';
import { pipelineApi, type Pipeline, type PipelineStage } from '../services/crmApi.ts';
import {
    AgentiveAlert,
    AgentiveConfirmModal,
    agentiveIconButtonClass,
    agentivePageClass,
    agentivePillClass,
    agentivePrimaryButtonClass,
    agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';
import {
    FlowNodeHandle,
    FlowNodeHeader,
    flowNodePanelClass,
    flowNodeShellClass,
} from '../components/flow/FlowNodeChrome.tsx';

type AgentKind = 'manager' | 'sales' | 'scheduler' | 'support' | 'human' | 'custom';
type AgentStatus = 'draft' | 'active' | 'paused';
type PromptFramework = 'agent_standard' | 'structured_instruction' | 'consultative_sales' | 'bant' | 'spin' | 'support_triage' | 'custom';
type QualificationType = 'none' | 'BANT' | 'SPIN' | 'MEDDIC' | 'custom';
type ReasoningEffort = 'none' | 'low' | 'medium' | 'high' | 'xhigh';
type GuardrailStage = 'input' | 'output' | 'tool';
type GuardrailCheckType = 'llm_classifier' | 'keyword_filter' | 'regex' | 'moderation' | 'pii_detection';
type GuardrailAction = 'block' | 'handoff' | 'redact' | 'warn';
type HumanAssignmentType = 'team' | 'user';
type HumanAssignmentStrategy = 'manual' | 'round_robin' | 'least_busy';
type ModelCatalogStatus = 'loading' | 'ready' | 'not_configured' | 'unavailable';
type HumanQueuePriority = 'low' | 'medium' | 'high' | 'urgent';
type InspectorTab = 'context' | 'knowledge' | 'examples' | 'schedule' | 'performance';
type WebSearchContextSize = 'low' | 'medium' | 'high';
type CalendarToolAction = 'find_slots' | 'create_appointment' | 'reschedule_appointment' | 'cancel_appointment';
type WorkforceScheduleMode = 'always_on' | 'custom';
type WorkforceScheduleDayKey = 'monday' | 'tuesday' | 'wednesday' | 'thursday' | 'friday' | 'saturday' | 'sunday';
type WorkforceSchedulePeriodKey = 'morning' | 'afternoon' | 'night' | 'dawn';
type DynamicFollowupTimeUnit = 'minutes' | 'hours' | 'days';

interface DynamicCrmFollowupDeliveryWindow {
    enabled: boolean;
    timezone: string;
    allowedWeekdays: number[];
    startTime: string;
    endTime: string;
}

interface CalendarSchedulingToolSettings {
    agendaId: number | null;
    allowedActions: CalendarToolAction[];
    requireConfirmation: boolean;
    maxSuggestions: number;
    createGoogleMeet: boolean;
    whenToUse: string;
}

interface CrmPipelineStageRule {
    stageId: number;
    stageName: string;
    advanceRule: string;
    recedeRule: string;
}

interface CrmPipelineToolSettings {
    pipelineId: number | null;
    stageRules: CrmPipelineStageRule[];
    whenToUse: string;
}

interface WhatsAppContactCardConfig {
    key: string;
    fullName: string;
    phoneNumber: string;
    organization: string;
    whatsappId: string;
    whenToUse: string;
}

interface WhatsAppContactCardToolSettings {
    contactCards: WhatsAppContactCardConfig[];
    whenToUse: string;
}

interface WhatsAppScheduledFollowupToolSettings {
    whenToUse: string;
    messageInstruction: string;
    replaceExistingPending: boolean;
}

interface DynamicCrmFollowupStep {
    stepNumber: number;
    sendAfter: number;
    sendAfterUnit: DynamicFollowupTimeUnit;
    channel: 'whatsapp';
    objective: string;
    miniPrompt: string;
}

interface DynamicCrmFollowupToolSettings {
    pipelineId: number | null;
    targetStageIds: number[];
    stopOnAppointmentCreated: boolean;
    timezone: string;
    deliveryWindow: DynamicCrmFollowupDeliveryWindow;
    steps: DynamicCrmFollowupStep[];
}

type AgentToolSettings = Record<string, CalendarSchedulingToolSettings | CrmPipelineToolSettings | WhatsAppContactCardToolSettings | WhatsAppScheduledFollowupToolSettings | DynamicCrmFollowupToolSettings | Record<string, any>>;

interface FewShotExampleData {
    user: string;
    assistant: string;
    context?: string;
}

interface GlobalFewShotExampleData extends FewShotExampleData {
    title?: string;
    tags?: string;
    enabled?: boolean;
}

interface WorkforceGlobalContextSettings {
    enabled: boolean;
    company_profile: string;
    products_services: string;
    brand_voice: string;
    target_audience: string;
    commercial_policy: string;
    faq: string;
}

interface WorkforceSchedulePeriodSettings {
    enabled: boolean;
    start: string;
    end: string;
}

interface WorkforceScheduleDaySettings {
    enabled: boolean;
    periods: Record<WorkforceSchedulePeriodKey, WorkforceSchedulePeriodSettings>;
}

interface WorkforceScheduleSettings {
    mode: WorkforceScheduleMode;
    timezone: string;
    days: Record<WorkforceScheduleDayKey, WorkforceScheduleDaySettings>;
}

interface WorkforceAgentContextSettings {
    global_context: WorkforceGlobalContextSettings;
    global_few_shots: {
        enabled: boolean;
        examples: GlobalFewShotExampleData[];
    };
    knowledge: {
        file_search: {
            enabled: boolean;
            vector_store_id: string;
            max_num_results: number;
            files: Array<Record<string, any>>;
            links: Array<Record<string, any>>;
        };
        web_search: {
            enabled: boolean;
            search_context_size: WebSearchContextSize;
            allowed_domains: string;
            external_web_access: boolean;
        };
    };
    performance: {
        include_global_context: boolean;
        retrieval_mode: 'keyword' | 'off';
        max_global_few_shots: number;
        response_delay_seconds: number;
        tool_search_enabled: boolean;
    };
    schedule: WorkforceScheduleSettings;
}

interface CustomGuardrailData {
    key: string;
    name: string;
    stage: GuardrailStage;
    targetToolId?: string;
    checkType: GuardrailCheckType;
    condition: string;
    action: GuardrailAction;
    message?: string;
    enabled: boolean;
}

interface HumanQueueConfig {
    assignmentType: HumanAssignmentType;
    teamId: number | null;
    userId: number | null;
    strategy: HumanAssignmentStrategy;
    priority: HumanQueuePriority;
    slaMinutes: number | null;
    transferMessage: string;
    silentTransfer: boolean;
    tags: string[];
}

interface HumanHandoffTarget {
    queue_key: string;
    queue_name: string;
    when: string;
    assignment: HumanQueueConfig;
}

interface AgentNodeData {
    key: string;
    name: string;
    role: string;
    kind: AgentKind;
    iconKey?: string;
    goal: string;
    description: string;
    promptContext: string;
    tone: string;
    audioEnabled: boolean;
    audioProvider: 'elevenlabs';
    audioVoiceId: string;
    audioVoiceLabel: string;
    audioModelId: string;
    audioOutputFormat: string;
    model: string;
    reasoningEffort?: ReasoningEffort;
    framework: PromptFramework;
    qualification: QualificationType;
    tools: string[];
    toolSettings?: AgentToolSettings;
    guardrails?: string[];
    customGuardrails: CustomGuardrailData[];
    instructions: string[];
    constraints: string[];
    conversationRules: string[];
    successCriteria?: string[];
    failureConditions: string[];
    fewShots: FewShotExampleData[];
    humanQueue?: HumanQueueConfig;
}

interface AgentEdgeData {
    mode: 'handoff' | 'supervision' | 'escalation';
    rule: string;
}

type AgentNode = Node<AgentNodeData>;
type AgentEdge = Edge<AgentEdgeData>;

const AGENT_META: Record<AgentKind, {
    label: string;
    role: string;
    icon: LucideIcon;
    goal: string;
}> = {
    custom: {
        label: 'Agente',
        role: '',
        icon: Bot,
        goal: ''
    },
    manager: {
        label: 'Coordenador',
        role: 'Orquestrador de atendimento',
        icon: Network,
        goal: 'Entender a intenção do contato, conduzir o fluxo principal e acionar especialistas quando necessário.'
    },
    sales: {
        label: 'SDR',
        role: 'Qualificador de leads',
        icon: UserRoundCheck,
        goal: 'Qualificar o lead, mapear necessidade, urgência e próximos passos comerciais.'
    },
    scheduler: {
        label: 'Agenda',
        role: 'Especialista de agendamento',
        icon: CalendarClock,
        goal: 'Encontrar horários disponíveis, confirmar dados essenciais e preparar a marcação.'
    },
    support: {
        label: 'Suporte',
        role: 'Especialista de suporte',
        icon: Headphones,
        goal: 'Resolver dúvidas operacionais, coletar contexto e escalar casos que exigem humano.'
    },
    human: {
        label: 'Humano',
        role: 'Fila de atendimento humano',
        icon: Users,
        goal: 'Receber conversas que precisam de decisão humana, negociação sensível ou exceção operacional.'
    }
};

const ICON_OPTIONS: Array<{
    key: string;
    label: string;
    icon: LucideIcon;
}> = [
    { key: 'bot', label: 'Bot', icon: Bot },
    { key: 'message', label: 'Conversa', icon: MessageCircle },
    { key: 'target', label: 'Meta', icon: Target },
    { key: 'briefcase', label: 'Negócio', icon: Briefcase },
    { key: 'store', label: 'Loja', icon: Store },
    { key: 'building', label: 'Empresa', icon: Building2 },
    { key: 'cart', label: 'Vendas', icon: ShoppingCart },
    { key: 'money', label: 'Financeiro', icon: DollarSign },
    { key: 'file', label: 'Documento', icon: FileText },
    { key: 'clipboard_check', label: 'Checklist', icon: ClipboardCheck },
    { key: 'handshake', label: 'Relacionamento', icon: Handshake },
    { key: 'calendar', label: 'Agenda', icon: CalendarClock },
    { key: 'megaphone', label: 'Campanha', icon: Megaphone },
    { key: 'phone', label: 'Contato', icon: Phone },
    { key: 'mail', label: 'E-mail', icon: Mail },
    { key: 'search', label: 'Pesquisa', icon: Search },
    { key: 'globe', label: 'Global', icon: Globe },
    { key: 'shield', label: 'Segurança', icon: Shield },
    { key: 'support', label: 'Suporte', icon: Headphones },
    { key: 'life_buoy', label: 'Ajuda', icon: LifeBuoy },
    { key: 'sparkles', label: 'IA', icon: Sparkles },
    { key: 'brain', label: 'Estratégia', icon: Brain },
    { key: 'gem', label: 'Especialista', icon: Gem },
    { key: 'wrench', label: 'Operação', icon: Wrench },
    { key: 'user_plus', label: 'Captação', icon: UserPlus },
    { key: 'user_cog', label: 'Gestão', icon: UserCog },
    { key: 'users', label: 'Humano', icon: Users }
];

const DEFAULT_AGENT_MODEL = 'gpt-5.4-mini';

const getModelGroupLabel = (model: string) => {
    if (model.startsWith('gpt-5.6')) return 'GPT-5.6';
    if (model.startsWith('gpt-5.5')) return 'GPT-5.5';
    if (model.startsWith('gpt-5.4')) return 'GPT-5.4';
    if (model.startsWith('gpt-4o')) return 'GPT-4o';
    return 'Outros';
};

const groupModelOptions = (models: readonly string[]) => {
    const groups = new Map<string, string[]>();
    models.forEach((model) => {
        const normalizedModel = String(model).trim();
        if (!normalizedModel) return;
        const label = getModelGroupLabel(normalizedModel);
        const currentModels = groups.get(label) || [];
        if (!currentModels.includes(normalizedModel)) {
            currentModels.push(normalizedModel);
        }
        groups.set(label, currentModels);
    });
    return Array.from(groups, ([label, groupedModels]) => ({ label, models: groupedModels }));
};

const DEFAULT_AUDIO_MODEL_ID = 'eleven_flash_v2_5';
const DEFAULT_AUDIO_OUTPUT_FORMAT = 'mp3_44100_128';
const VOICE_OPTIONS_UNAVAILABLE_MESSAGE = 'Vozes indisponíveis no momento.';

const AUDIO_MODEL_OPTIONS = [
    { value: 'eleven_flash_v2_5', label: 'Flash v2.5' },
    { value: 'eleven_multilingual_v2', label: 'Multilíngue v2' }
];

const REASONING_OPTIONS: Array<{ value: ReasoningEffort; label: string }> = [
    { value: 'none', label: 'Nenhum' },
    { value: 'low', label: 'Baixo' },
    { value: 'medium', label: 'Médio' },
    { value: 'high', label: 'Alto' },
    { value: 'xhigh', label: 'Máximo' }
];

const getReasoningOptions = (model: string) => {
    if (!model.startsWith('gpt-5')) {
        return REASONING_OPTIONS.filter((option) => option.value === 'none');
    }

    return model.endsWith('-pro')
        ? REASONING_OPTIONS.filter((option) => ['medium', 'high', 'xhigh'].includes(option.value))
        : REASONING_OPTIONS;
};

const getNormalizedReasoningEffort = (
    model: string,
    effort?: ReasoningEffort
): ReasoningEffort => {
    const availableReasoning = getReasoningOptions(model).map((option) => option.value);
    const currentReasoning = effort || 'low';
    return availableReasoning.includes(currentReasoning)
        ? currentReasoning
        : availableReasoning[0];
};

const TONE_PRESETS = [
    {
        id: 'consultivo',
        label: 'Consultivo',
        value: 'Use tom consultivo, claro e objetivo. Faça perguntas úteis, explique o próximo passo e evite pressão excessiva.'
    },
    {
        id: 'objetivo',
        label: 'Objetivo',
        value: 'Use respostas curtas, diretas e práticas. Evite explicações longas e avance para o próximo passo.'
    },
    {
        id: 'acolhedor',
        label: 'Acolhedor',
        value: 'Use tom calmo, empático e respeitoso. Valide a necessidade do contato antes de orientar.'
    },
    {
        id: 'profissional',
        label: 'Profissional',
        value: 'Use tom profissional, preciso e confiável. Seja educado, claro e mantenha formalidade leve.'
    },
    {
        id: 'persuasivo',
        label: 'Persuasivo',
        value: 'Use tom confiante e comercial. Conduza para a ação com naturalidade, sem parecer insistente.'
    },
    {
        id: 'especialista',
        label: 'Especialista',
        value: 'Use tom técnico, didático e preciso. Demonstre autoridade sem arrogância e simplifique conceitos quando necessário.'
    },
    {
        id: 'casual',
        label: 'Casual',
        value: 'Use tom natural, próximo e simples. Mantenha leveza sem perder clareza ou profissionalismo.'
    },
    {
        id: 'premium',
        label: 'Premium',
        value: 'Use tom elegante, discreto e personalizado. Transmita cuidado, exclusividade e atenção aos detalhes.'
    },
    {
        id: 'resolutivo',
        label: 'Resolutivo',
        value: 'Use tom firme, prático e focado em resolver. Confirme dados, reduza idas e vindas e indique o próximo passo.'
    },
    {
        id: 'neutro',
        label: 'Neutro',
        value: 'Use tom equilibrado, educado e claro. Evite personalidade forte e priorize entendimento.'
    }
];

const DEFAULT_TONE_PRESET_BY_KIND: Record<AgentKind, string> = {
    manager: 'profissional',
    sales: 'consultivo',
    scheduler: 'objetivo',
    support: 'acolhedor',
    human: 'acolhedor',
    custom: 'consultivo'
};

const getTonePresetValue = (tone?: string, kind: AgentKind = 'custom') => {
    if (tone && TONE_PRESETS.some((preset) => preset.value === tone)) {
        return tone;
    }

    const normalizedTone = (tone || '').toLowerCase();
    const matchedPreset = TONE_PRESETS.find(
        (preset) => normalizedTone.includes(preset.id) || normalizedTone.includes(preset.label.toLowerCase())
    );

    if (matchedPreset) {
        return matchedPreset.value;
    }

    return TONE_PRESETS.find((preset) => preset.id === DEFAULT_TONE_PRESET_BY_KIND[kind])?.value || TONE_PRESETS[0].value;
};

const normalizeAudioModelId = (modelId?: string) => (
    AUDIO_MODEL_OPTIONS.some((option) => option.value === modelId)
        ? String(modelId)
        : DEFAULT_AUDIO_MODEL_ID
);

const getVoiceLabel = (voice: AgentVoiceOption) => {
    const accent = typeof voice.labels?.accent === 'string' ? voice.labels.accent : '';
    const gender = typeof voice.labels?.gender === 'string' ? voice.labels.gender : '';
    return [voice.name, accent || gender].filter(Boolean).join(' · ');
};

const getPreferredVoiceOption = (
    voices: AgentVoiceOption[],
    currentVoiceId?: string,
    defaultVoiceId?: string
) => {
    const currentVoice = currentVoiceId
        ? voices.find((voice) => voice.voice_id === currentVoiceId)
        : null;
    const defaultVoice = defaultVoiceId
        ? voices.find((voice) => voice.voice_id === defaultVoiceId)
        : null;

    return currentVoice || defaultVoice || voices[0] || null;
};

const getAudioVoiceFromConfig = (config?: Record<string, any>): Partial<AgentNodeData> => {
    const channel = config?.channel;
    const voice = channel?.voice;
    if (!channel || typeof channel !== 'object') {
        return {};
    }

    return {
        audioEnabled: Boolean(channel.allow_audio),
        audioProvider: 'elevenlabs',
        audioVoiceId: typeof voice?.voice_id === 'string' ? voice.voice_id : '',
        audioVoiceLabel: typeof voice?.label === 'string' ? voice.label : '',
        audioModelId: normalizeAudioModelId(voice?.model_id),
        audioOutputFormat: typeof voice?.output_format === 'string' && voice.output_format
            ? voice.output_format
            : DEFAULT_AUDIO_OUTPUT_FORMAT
    };
};

const TOOL_OPTIONS = [
    { id: 'calendar.scheduling', label: 'Agendamento de lead' },
    { id: 'crm.pipeline_stage', label: 'Mover lead no CRM' },
    { id: 'crm.dynamic_followup', label: 'Follow-up dinâmico CRM' },
    { id: 'human_handoff.create_task', label: 'Transferir para humano' },
    { id: 'whatsapp.send_contact_card', label: 'Enviar card de contato' },
    { id: 'whatsapp.schedule_followup_message', label: 'Agendar mensagem automática' }
];

const ALLOWED_TOOL_IDS = TOOL_OPTIONS.map((tool) => tool.id);
const CALENDAR_TOOL_ID = 'calendar.scheduling';
const CRM_PIPELINE_TOOL_ID = 'crm.pipeline_stage';
const DYNAMIC_CRM_FOLLOWUP_TOOL_ID = 'crm.dynamic_followup';
const HUMAN_HANDOFF_TOOL_ID = 'human_handoff.create_task';
const WHATSAPP_CONTACT_CARD_TOOL_ID = 'whatsapp.send_contact_card';
const WHATSAPP_SCHEDULED_FOLLOWUP_TOOL_ID = 'whatsapp.schedule_followup_message';
const CALENDAR_TOOL_ACTION_OPTIONS: Array<{ value: CalendarToolAction; label: string; description: string }> = [
    {
        value: 'find_slots',
        label: 'Consultar horários',
        description: 'Mostra slots disponíveis da agenda escolhida.'
    },
    {
        value: 'create_appointment',
        label: 'Criar agendamento',
        description: 'Marca o horário depois da confirmação do lead.'
    },
    {
        value: 'reschedule_appointment',
        label: 'Reagendar',
        description: 'Move um agendamento futuro para outro horário disponível.'
    },
    {
        value: 'cancel_appointment',
        label: 'Cancelar/excluir',
        description: 'Cancela um agendamento futuro depois da confirmação do lead.'
    }
];

const DEFAULT_CALENDAR_TOOL_SETTINGS: CalendarSchedulingToolSettings = {
    agendaId: null,
    allowedActions: ['find_slots', 'create_appointment'],
    requireConfirmation: true,
    maxSuggestions: 3,
    createGoogleMeet: false,
    whenToUse: ''
};

const DEFAULT_CRM_PIPELINE_TOOL_SETTINGS: CrmPipelineToolSettings = {
    pipelineId: null,
    stageRules: [],
    whenToUse: ''
};

const createDefaultContactCard = (index = 0): WhatsAppContactCardConfig => ({
    key: `contato_${index + 1}`,
    fullName: '',
    phoneNumber: '',
    organization: '',
    whatsappId: '',
    whenToUse: ''
});

const DEFAULT_WHATSAPP_CONTACT_CARD_SETTINGS: WhatsAppContactCardToolSettings = {
    contactCards: [createDefaultContactCard()],
    whenToUse: ''
};

const DEFAULT_WHATSAPP_SCHEDULED_FOLLOWUP_SETTINGS: WhatsAppScheduledFollowupToolSettings = {
    whenToUse: '',
    messageInstruction: '',
    replaceExistingPending: true
};

const DYNAMIC_FOLLOWUP_TIME_UNIT_OPTIONS: Array<{ value: DynamicFollowupTimeUnit; label: string }> = [
    { value: 'minutes', label: 'min' },
    { value: 'hours', label: 'h' },
    { value: 'days', label: 'dias' }
];
const DYNAMIC_FOLLOWUP_DEFAULT_DELIVERY_WEEKDAYS = [0, 1, 2, 3, 4];
const DYNAMIC_FOLLOWUP_DEFAULT_START_TIME = '09:00';
const DYNAMIC_FOLLOWUP_DEFAULT_END_TIME = '18:00';

const createDefaultDynamicFollowupDeliveryWindow = (): DynamicCrmFollowupDeliveryWindow => ({
    enabled: false,
    timezone: 'America/Sao_Paulo',
    allowedWeekdays: [...DYNAMIC_FOLLOWUP_DEFAULT_DELIVERY_WEEKDAYS],
    startTime: DYNAMIC_FOLLOWUP_DEFAULT_START_TIME,
    endTime: DYNAMIC_FOLLOWUP_DEFAULT_END_TIME
});

const createDefaultDynamicCrmFollowupStep = (index = 0): DynamicCrmFollowupStep => ({
    stepNumber: index + 1,
    sendAfter: index === 0 ? 0 : 1,
    sendAfterUnit: index === 0 ? 'minutes' : 'days',
    channel: 'whatsapp',
    objective: index === 0 ? 'Responder no pico de intenção' : '',
    miniPrompt: ''
});

const DEFAULT_DYNAMIC_CRM_FOLLOWUP_SETTINGS: DynamicCrmFollowupToolSettings = {
    pipelineId: null,
    targetStageIds: [],
    stopOnAppointmentCreated: true,
    timezone: 'America/Sao_Paulo',
    deliveryWindow: createDefaultDynamicFollowupDeliveryWindow(),
    steps: [createDefaultDynamicCrmFollowupStep()]
};

const CALENDAR_SUGGESTION_OPTIONS = [2, 3, 4, 5];

const GUARDRAIL_STAGE_OPTIONS: Array<{ value: GuardrailStage; label: string }> = [
    { value: 'input', label: 'Antes do agente responder' },
    { value: 'output', label: 'Depois da resposta do agente' },
    { value: 'tool', label: 'Antes ou depois de usar ferramenta' }
];

const GUARDRAIL_CHECK_OPTIONS: Array<{ value: GuardrailCheckType; label: string }> = [
    { value: 'llm_classifier', label: 'IA avalia a condição' },
    { value: 'keyword_filter', label: 'Palavras proibidas/obrigatórias' },
    { value: 'regex', label: 'Padrão de texto' },
    { value: 'moderation', label: 'Conteúdo sensível/moderação' },
    { value: 'pii_detection', label: 'Dados pessoais/sensíveis' }
];

const GUARDRAIL_ACTION_OPTIONS: Array<{ value: GuardrailAction; label: string }> = [
    { value: 'block', label: 'Bloquear e responder' },
    { value: 'handoff', label: 'Transferir para humano' },
    { value: 'redact', label: 'Mascarar informação' },
    { value: 'warn', label: 'Registrar alerta' }
];

const HUMAN_ASSIGNMENT_OPTIONS: Array<{ value: HumanAssignmentType; label: string }> = [
    { value: 'team', label: 'Equipe' },
    { value: 'user', label: 'Usuário específico' }
];

const HUMAN_STRATEGY_OPTIONS: Array<{ value: HumanAssignmentStrategy; label: string }> = [
    { value: 'manual', label: 'Manual' },
    { value: 'round_robin', label: 'Rodízio' },
    { value: 'least_busy', label: 'Menor fila' }
];

const HUMAN_PRIORITY_OPTIONS: Array<{ value: HumanQueuePriority; label: string }> = [
    { value: 'low', label: 'Baixa' },
    { value: 'medium', label: 'Normal' },
    { value: 'high', label: 'Alta' },
    { value: 'urgent', label: 'Urgente' }
];

const HUMAN_SLA_PRESETS = [
    { label: '15 min', value: 15 },
    { label: '30 min', value: 30 },
    { label: '1 h', value: 60 },
    { label: '2 h', value: 120 }
];

const HUMAN_TAG_SUGGESTIONS = [
    'urgente',
    'comercial',
    'suporte',
    'financeiro',
    'fora do escopo',
    'decisão humana'
];

const MAX_AGENT_RESPONSE_DELAY_SECONDS = 60;
const INSPECTOR_DEFAULT_WIDTH = 380;
const DEFAULT_WORKFORCE_TIMEZONE = 'America/Sao_Paulo';
const WORKFORCE_WEEKDAYS: Array<{ key: WorkforceScheduleDayKey; label: string; short: string }> = [
    { key: 'monday', label: 'Segunda-feira', short: 'Seg' },
    { key: 'tuesday', label: 'Terça-feira', short: 'Ter' },
    { key: 'wednesday', label: 'Quarta-feira', short: 'Qua' },
    { key: 'thursday', label: 'Quinta-feira', short: 'Qui' },
    { key: 'friday', label: 'Sexta-feira', short: 'Sex' },
    { key: 'saturday', label: 'Sábado', short: 'Sáb' },
    { key: 'sunday', label: 'Domingo', short: 'Dom' }
];
const DYNAMIC_FOLLOWUP_WEEKDAYS = WORKFORCE_WEEKDAYS.map((day, index) => ({
    value: index,
    label: day.label,
    short: day.short
}));
const WORKFORCE_SCHEDULE_PERIODS: Array<{ key: WorkforceSchedulePeriodKey; label: string }> = [
    { key: 'morning', label: 'Manhã' },
    { key: 'afternoon', label: 'Tarde' },
    { key: 'night', label: 'Noite' },
    { key: 'dawn', label: 'Madrugada' }
];

const clampAgentResponseDelay = (value: any): number => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return 0;
    return Math.max(0, Math.min(MAX_AGENT_RESPONSE_DELAY_SECONDS, Math.round(parsed)));
};

const isValidScheduleTime = (value: any) => typeof value === 'string' && /^\d{2}:\d{2}$/.test(value);

const createDefaultSchedulePeriods = (enabled: boolean): Record<WorkforceSchedulePeriodKey, WorkforceSchedulePeriodSettings> => ({
    morning: { enabled, start: '08:00', end: '12:00' },
    afternoon: { enabled, start: '13:00', end: '18:00' },
    night: { enabled: false, start: '18:00', end: '23:59' },
    dawn: { enabled: false, start: '00:00', end: '06:00' }
});

const createDefaultWorkforceScheduleDays = (): Record<WorkforceScheduleDayKey, WorkforceScheduleDaySettings> =>
    WORKFORCE_WEEKDAYS.reduce((acc, day) => {
        const enabled = !['saturday', 'sunday'].includes(day.key);
        acc[day.key] = {
            enabled,
            periods: createDefaultSchedulePeriods(enabled)
        };
        return acc;
    }, {} as Record<WorkforceScheduleDayKey, WorkforceScheduleDaySettings>);

const createDefaultWorkforceScheduleSettings = (): WorkforceScheduleSettings => ({
    mode: 'always_on',
    timezone: DEFAULT_WORKFORCE_TIMEZONE,
    days: createDefaultWorkforceScheduleDays()
});

const normalizeSchedulePeriod = (
    value: any,
    fallback: WorkforceSchedulePeriodSettings
): WorkforceSchedulePeriodSettings => ({
    enabled: typeof value?.enabled === 'boolean' ? value.enabled : fallback.enabled,
    start: isValidScheduleTime(value?.start) ? value.start : fallback.start,
    end: isValidScheduleTime(value?.end) ? value.end : fallback.end
});

const normalizeWorkforceScheduleSettings = (value: any): WorkforceScheduleSettings => {
    const defaults = createDefaultWorkforceScheduleSettings();
    const source = value && typeof value === 'object' ? value : {};
    const sourceDays = source.days && typeof source.days === 'object' ? source.days : {};
    const days = WORKFORCE_WEEKDAYS.reduce((acc, day) => {
        const fallback = defaults.days[day.key];
        const sourceDay = sourceDays[day.key] && typeof sourceDays[day.key] === 'object' ? sourceDays[day.key] : {};
        const sourcePeriods = sourceDay.periods && typeof sourceDay.periods === 'object' ? sourceDay.periods : sourceDay;
        acc[day.key] = {
            enabled: typeof sourceDay.enabled === 'boolean' ? sourceDay.enabled : fallback.enabled,
            periods: WORKFORCE_SCHEDULE_PERIODS.reduce((periodAcc, period) => {
                periodAcc[period.key] = normalizeSchedulePeriod(sourcePeriods[period.key], fallback.periods[period.key]);
                return periodAcc;
            }, {} as Record<WorkforceSchedulePeriodKey, WorkforceSchedulePeriodSettings>)
        };
        return acc;
    }, {} as Record<WorkforceScheduleDayKey, WorkforceScheduleDaySettings>);

    return {
        mode: source.mode === 'custom' ? 'custom' : 'always_on',
        timezone: typeof source.timezone === 'string' && source.timezone.trim()
            ? source.timezone.trim()
            : defaults.timezone,
        days
    };
};

const createDefaultAgentContextSettings = (): WorkforceAgentContextSettings => ({
    global_context: {
        enabled: true,
        company_profile: '',
        products_services: '',
        brand_voice: '',
        target_audience: '',
        commercial_policy: '',
        faq: ''
    },
    global_few_shots: {
        enabled: true,
        examples: []
    },
    knowledge: {
        file_search: {
            enabled: false,
            vector_store_id: '',
            max_num_results: 4,
            files: [],
            links: []
        },
        web_search: {
            enabled: false,
            search_context_size: 'low',
            allowed_domains: '',
            external_web_access: true
        }
    },
    performance: {
        include_global_context: true,
        retrieval_mode: 'keyword',
        max_global_few_shots: 3,
        response_delay_seconds: 15,
        tool_search_enabled: false
    },
    schedule: createDefaultWorkforceScheduleSettings()
});

const normalizeAgentContextSettings = (settings?: Record<string, any>): WorkforceAgentContextSettings => {
    const defaults = createDefaultAgentContextSettings();
    const source = settings?.agent_context || {};
    const globalContext = source.global_context || {};
    const globalFewShots = source.global_few_shots || {};
    const knowledge = source.knowledge || {};
    const fileSearch = knowledge.file_search || {};
    const webSearch = knowledge.web_search || {};
    const performance = source.performance || {};
    const schedule = source.schedule || {};
    const hasFileSearchContent = (Array.isArray(fileSearch.files) && fileSearch.files.length > 0)
        || (Array.isArray(fileSearch.links) && fileSearch.links.length > 0);

    return {
        global_context: {
            ...defaults.global_context,
            ...globalContext,
            enabled: globalContext.enabled !== false
        },
        global_few_shots: {
            enabled: globalFewShots.enabled !== false,
            examples: Array.isArray(globalFewShots.examples)
                ? globalFewShots.examples.map((example: any) => ({
                    title: example.title || '',
                    tags: example.tags || '',
                    context: example.context || '',
                    user: example.user || '',
                    assistant: example.assistant || '',
                    enabled: example.enabled !== false
                }))
                : []
        },
        knowledge: {
            file_search: {
                ...defaults.knowledge.file_search,
                ...fileSearch,
                enabled: Boolean(fileSearch.enabled !== false && hasFileSearchContent),
                vector_store_id: fileSearch.vector_store_id || '',
                max_num_results: Number(fileSearch.max_num_results || defaults.knowledge.file_search.max_num_results),
                files: Array.isArray(fileSearch.files) ? fileSearch.files : [],
                links: Array.isArray(fileSearch.links) ? fileSearch.links : []
            },
            web_search: {
                ...defaults.knowledge.web_search,
                ...webSearch,
                enabled: Boolean(webSearch.enabled),
                search_context_size: ['low', 'medium', 'high'].includes(webSearch.search_context_size)
                    ? webSearch.search_context_size
                    : defaults.knowledge.web_search.search_context_size,
                allowed_domains: webSearch.allowed_domains || '',
                external_web_access: webSearch.external_web_access !== false
            }
        },
        performance: {
            ...defaults.performance,
            ...performance,
            include_global_context: performance.include_global_context !== false,
            retrieval_mode: performance.retrieval_mode === 'off' ? 'off' : 'keyword',
            max_global_few_shots: Number(performance.max_global_few_shots || defaults.performance.max_global_few_shots),
            response_delay_seconds: clampAgentResponseDelay(performance.response_delay_seconds),
            tool_search_enabled: Boolean(performance.tool_search_enabled)
        },
        schedule: normalizeWorkforceScheduleSettings(schedule)
    };
};

const KIND_MINIMAP_COLOR: Record<AgentKind, string> = {
    custom: '#8b5cf6',
    manager: '#818cf8',
    sales: '#34d399',
    scheduler: '#38bdf8',
    support: '#fbbf24',
    human: '#fb7185'
};

const AGENT_NODE_TONE: Record<AgentKind, 'green' | 'pink' | 'blue' | 'emerald' | 'indigo' | 'purple' | 'sky' | 'amber'> = {
    custom: 'purple',
    manager: 'indigo',
    sales: 'emerald',
    scheduler: 'sky',
    support: 'amber',
    human: 'pink',
};

const AgentBuilderTrafficDots: React.FC<{ isDark: boolean }> = ({ isDark }) => (
    <span className="flex items-center gap-1.5" aria-hidden="true">
        {['bg-red-400', 'bg-amber-400', 'bg-emerald-400'].map((color) => (
            <span
                key={color}
                className={`h-2 w-2 rounded-full ${color} ${isDark ? 'opacity-85' : 'opacity-75'}`}
            />
        ))}
    </span>
);

const cx = (...classes: Array<string | false | null | undefined>) => classes.filter(Boolean).join(' ');

const builderPanelClass = (isDark: boolean, className = '') =>
    cx(
        'rounded-2xl border p-3',
        isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas',
        className
    );

const builderSurfaceClass = (isDark: boolean, className = '') =>
    cx(
        'rounded-2xl border',
        isDark ? 'border-white/10 bg-white/[0.06]' : 'border-brand/10 bg-white',
        className
    );

const builderEmptyClass = (isDark: boolean, className = '') =>
    cx(
        'rounded-2xl border border-dashed px-3 py-4 text-sm',
        isDark ? 'border-white/10 bg-white/[0.03] text-white/50' : 'border-brand/10 bg-brand-canvas text-brand/50',
        className
    );

const builderMutedTextClass = (isDark: boolean, className = '') =>
    cx(isDark ? 'text-white/55' : 'text-brand/55', className);

const builderChevronClass = (isDark: boolean, className = '') =>
    cx('pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2', isDark ? 'text-white/40' : 'text-brand/40', className);

const builderInlineInputClass = (isDark: boolean, className = '') =>
    cx(
        'min-w-0 flex-1 border-0 bg-transparent text-sm outline-none',
        isDark ? 'text-white placeholder:text-white/35' : 'text-brand placeholder:text-brand/35',
        className
    );

const builderInputClass = (isDark: boolean, className = '') =>
    cx(
        'w-full rounded-xl border px-3 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20 disabled:opacity-50',
        isDark ? 'border-white/10 bg-white/[0.06] text-white placeholder:text-white/35' : 'border-brand/10 bg-white text-brand placeholder:text-brand/35',
        className
    );

const builderTextareaClass = (isDark: boolean, className = '') =>
    builderInputClass(isDark, cx('resize-none', className));

const builderSelectClass = (isDark: boolean, className = '') =>
    builderInputClass(isDark, cx('appearance-none pr-8', className));

const builderCheckboxClass = (isDark: boolean, className = '') =>
    cx(
        'mt-0.5 h-4 w-4 rounded border text-brand focus:ring-brand',
        isDark ? 'border-white/20 bg-white/10' : 'border-brand/20 bg-white',
        className
    );

const builderToggleCardClass = (isDark: boolean, active: boolean, className = '') =>
    cx(
        'flex items-start gap-3 rounded-2xl border p-3 text-sm transition',
        active
            ? isDark ? 'border-white/15 bg-white/[0.08] text-white' : 'border-brand/15 bg-white text-brand shadow-sm'
            : isDark ? 'border-white/10 bg-white/[0.03] text-white/65 hover:bg-white/[0.06]' : 'border-brand/10 bg-brand-canvas text-brand/65 hover:bg-white hover:text-brand',
        className
    );

const getIconOption = (iconKey?: string, kind?: AgentKind) => {
    if (iconKey) {
        const icon = ICON_OPTIONS.find((option) => option.key === iconKey);
        if (icon) return icon;
    }

    const meta = AGENT_META[kind || 'custom'] || AGENT_META.custom;
    return {
        key: kind || 'custom',
        label: meta.label,
        icon: meta.icon
    };
};

const getSelectableIconKey = (iconKey?: string, kind?: AgentKind) => {
    if (iconKey && ICON_OPTIONS.some((option) => option.key === iconKey)) {
        return iconKey;
    }
    return kind === 'human' ? 'users' : 'bot';
};

const makeAgentKey = (name: string, suffix?: string) => {
    const base = name
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '');
    return `${base || 'agent'}${suffix ? `_${suffix}` : ''}`;
};

const makeUniqueAgentKey = (name: string, nodes: AgentNode[], currentNodeId?: string) => {
    const base = makeAgentKey(name);
    const usedKeys = new Set(
        nodes
            .filter((node) => node.id !== currentNodeId)
            .map((node) => node.data.key)
            .filter(Boolean)
    );

    if (!usedKeys.has(base)) return base;

    let suffix = 2;
    let candidate = makeAgentKey(base, String(suffix));
    while (usedKeys.has(candidate)) {
        suffix += 1;
        candidate = makeAgentKey(base, String(suffix));
    }
    return candidate;
};

const createDefaultHumanQueueConfig = (): HumanQueueConfig => ({
    assignmentType: 'team',
    teamId: null,
    userId: null,
    strategy: 'manual',
    priority: 'medium',
    slaMinutes: null,
    transferMessage: 'Vou transferir para um atendente humano continuar.',
    silentTransfer: false,
    tags: []
});

const toNullableId = (value: unknown) => {
    if (value === null || value === undefined || value === '') return null;
    const numeric = Number(value);
    return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
};

const parseHumanTags = (value: string) =>
    value
        .split(',')
        .map((tag) => tag.trim())
        .filter(Boolean);

const normalizeHumanQueueConfig = (config?: Partial<HumanQueueConfig>): HumanQueueConfig => {
    const fallback = createDefaultHumanQueueConfig();
    const assignmentType: HumanAssignmentType = config?.assignmentType === 'user' ? 'user' : 'team';
    const strategy = HUMAN_STRATEGY_OPTIONS.some((option) => option.value === config?.strategy)
        ? config?.strategy as HumanAssignmentStrategy
        : fallback.strategy;
    const priority = HUMAN_PRIORITY_OPTIONS.some((option) => option.value === config?.priority)
        ? config?.priority as HumanQueuePriority
        : fallback.priority;
    const numericSla = Number(config?.slaMinutes);
    const slaMinutes = Number.isFinite(numericSla) && numericSla > 0 ? numericSla : null;

    return {
        assignmentType,
        teamId: assignmentType === 'team' ? toNullableId(config?.teamId) : null,
        userId: assignmentType === 'user' ? toNullableId(config?.userId) : null,
        strategy,
        priority,
        slaMinutes,
        transferMessage: typeof config?.transferMessage === 'string'
            ? config.transferMessage
            : fallback.transferMessage,
        silentTransfer: Boolean(config?.silentTransfer ?? (config as any)?.silent_transfer),
        tags: Array.isArray(config?.tags)
            ? config.tags.map((tag) => String(tag).trim()).filter(Boolean)
            : []
    };
};

const sanitizeHumanQueueConfig = (config?: Partial<HumanQueueConfig>): HumanQueueConfig => {
    const normalized = normalizeHumanQueueConfig(config);
    const fallback = createDefaultHumanQueueConfig();
    return {
        ...normalized,
        transferMessage: normalized.silentTransfer
            ? normalized.transferMessage.trim()
            : normalized.transferMessage.trim() || fallback.transferMessage,
        tags: normalized.tags.map((tag) => tag.trim()).filter(Boolean)
    };
};

const createAgentNode = (
    kind: AgentKind,
    index: number,
    position: { x: number; y: number },
    overrides: Partial<AgentNodeData> = {}
): AgentNode => {
    const meta = AGENT_META[kind] || AGENT_META.custom;
    const nodeName = overrides.name || meta.label;
    const key = overrides.key || makeAgentKey(nodeName, String(index + 1));
    const model = overrides.model || DEFAULT_AGENT_MODEL;
    const tools = kind === 'human' ? [] : sanitizeToolIds(overrides.tools);

    return {
        id: `${kind}-${Date.now()}-${index}`,
        type: 'agent',
        position,
        data: {
            key,
            name: nodeName,
            role: overrides.role ?? meta.role,
            kind,
            iconKey: overrides.iconKey || (kind === 'human' ? 'users' : 'bot'),
            goal: overrides.goal ?? meta.goal,
            description: overrides.description || '',
            promptContext: overrides.promptContext || '',
            tone: getTonePresetValue(overrides.tone, kind),
            audioEnabled: Boolean(overrides.audioEnabled),
            audioProvider: 'elevenlabs',
            audioVoiceId: overrides.audioVoiceId || '',
            audioVoiceLabel: overrides.audioVoiceLabel || '',
            audioModelId: normalizeAudioModelId(overrides.audioModelId),
            audioOutputFormat: overrides.audioOutputFormat || DEFAULT_AUDIO_OUTPUT_FORMAT,
            model,
            reasoningEffort: getNormalizedReasoningEffort(model, overrides.reasoningEffort),
            framework: overrides.framework || 'agent_standard',
            qualification: overrides.qualification || (kind === 'sales' ? 'BANT' : 'none'),
            tools,
            toolSettings: kind === 'human' ? {} : sanitizeToolSettings(overrides.toolSettings, tools),
            customGuardrails: kind === 'human' ? [] : sanitizeCustomGuardrails(overrides.customGuardrails, tools),
            instructions: overrides.instructions || [],
            constraints: overrides.constraints || [],
            conversationRules: overrides.conversationRules || [],
            failureConditions: overrides.failureConditions || [],
            fewShots: overrides.fewShots || [],
            humanQueue: kind === 'human' ? normalizeHumanQueueConfig(overrides.humanQueue) : overrides.humanQueue
        }
    };
};

const createEdge = (source: string, target: string, rule: string): AgentEdge => ({
    id: `edge-${source}-${target}-${Date.now()}`,
    source,
    target,
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed },
    data: {
        mode: 'handoff',
        rule
    },
    label: rule
});

const normalizeAgentNode = (node: AgentNode): AgentNode => {
    const isHumanQueue = node.data.kind === 'human';
    const model = String(node.data.model || '').trim() || DEFAULT_AGENT_MODEL;
    const reasoningEffort = getNormalizedReasoningEffort(model, node.data.reasoningEffort);
    const tools = isHumanQueue ? [] : sanitizeToolIds(node.data.tools);

    return {
        ...node,
        data: {
            ...node.data,
            model,
            reasoningEffort,
            tone: getTonePresetValue(node.data.tone, node.data.kind),
            audioEnabled: isHumanQueue ? false : Boolean(node.data.audioEnabled),
            audioProvider: 'elevenlabs',
            audioVoiceId: isHumanQueue ? '' : String(node.data.audioVoiceId || ''),
            audioVoiceLabel: isHumanQueue ? '' : String(node.data.audioVoiceLabel || ''),
            audioModelId: normalizeAudioModelId(node.data.audioModelId),
            audioOutputFormat: node.data.audioOutputFormat || DEFAULT_AUDIO_OUTPUT_FORMAT,
            tools,
            toolSettings: isHumanQueue ? {} : sanitizeToolSettings(node.data.toolSettings, tools),
            customGuardrails: isHumanQueue ? [] : sanitizeCustomGuardrails(node.data.customGuardrails, tools),
            humanQueue: isHumanQueue ? normalizeHumanQueueConfig(node.data.humanQueue) : node.data.humanQueue
        }
    };
};

const createDefaultTeam = () => {
    const human = createAgentNode('human', 0, { x: 80, y: 120 }, {
        name: 'Fila Humana',
        key: 'fila_humana',
        role: 'Fallback humano',
        iconKey: 'users',
        goal: 'Receber conversas que precisam de decisão humana, negociação sensível ou exceção operacional.',
        humanQueue: createDefaultHumanQueueConfig()
    });

    return {
        name: 'Nova equipe',
        description: 'Equipe com fallback humano padrão. Crie os agentes especialistas conforme a operação.',
        status: 'draft' as AgentStatus,
        nodes: [human],
        edges: [] as AgentEdge[]
    };
};

const AgentOrgNode = memo(({ data, selected, isConnectable }: NodeProps<AgentNodeData>) => {
    const { isDark } = useTheme();
    const iconOption = getIconOption(data.iconKey, data.kind);
    const Icon = iconOption.icon;
    const isHumanQueue = data.kind === 'human';
    const toolCount = isHumanQueue ? 0 : sanitizeToolIds(data.tools).length;
    const tone = AGENT_NODE_TONE[data.kind] || AGENT_NODE_TONE.custom;
    const subtitle = isHumanQueue ? 'Fila humana' : AGENT_META[data.kind]?.label || 'Agente';

    return (
        <div className={flowNodeShellClass(isDark, Boolean(selected), tone, 'w-[290px] min-w-[290px] max-w-[290px]')}>
            <FlowNodeHandle type="target" position={Position.Left} tone={tone} isConnectable={isConnectable} />
            <FlowNodeHeader
                icon={Icon}
                title={data.name}
                subtitle={subtitle}
                tone={tone}
                meta={(
                    <span className="rounded-full border border-white/10 bg-white/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.14em] text-white/65">
                        {isHumanQueue ? 'Handoff' : `${toolCount} tools`}
                    </span>
                )}
            />
            <div className="space-y-3 p-3">
                <div className={flowNodePanelClass(isDark)}>
                    <p className={`truncate text-xs font-semibold ${isDark ? 'text-white/80' : 'text-brand/75'}`}>{data.role}</p>
                    <p className={`mt-1 line-clamp-2 text-[11px] leading-4 ${isDark ? 'text-white/52' : 'text-brand/52'}`}>{data.goal}</p>
                </div>
                <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-[0.16em]">
                    <span className={isDark ? 'text-white/40' : 'text-brand/40'}>
                        {isHumanQueue ? 'fila humana' : 'prompt'}
                    </span>
                    <span className={isDark ? 'text-white/55' : 'text-brand/55'}>
                        {data.model || DEFAULT_AGENT_MODEL}
                    </span>
                </div>
            </div>
            {!isHumanQueue && (
                <FlowNodeHandle type="source" position={Position.Right} tone={tone} isConnectable={isConnectable} />
            )}
        </div>
    );
});

const nodeTypes = { agent: AgentOrgNode };

const sanitizeStringList = (values?: string[]) =>
    (values || [])
        .map((item) => item.trim())
        .filter(Boolean);

const sanitizeToolIds = (values?: string[]) =>
    (values || []).filter((toolId) => ALLOWED_TOOL_IDS.includes(toolId));

const sanitizeCalendarToolSettings = (settings?: any): CalendarSchedulingToolSettings => {
    const rawAllowedActions = Array.isArray(settings?.allowedActions)
        ? settings.allowedActions
        : Array.isArray(settings?.allowed_actions)
            ? settings.allowed_actions
            : DEFAULT_CALENDAR_TOOL_SETTINGS.allowedActions;
    const allowedActions = rawAllowedActions.filter((action: string) =>
        CALENDAR_TOOL_ACTION_OPTIONS.some((option) => option.value === action)
    ) as CalendarToolAction[];

    const rawMaxSuggestions = Number(settings?.maxSuggestions ?? settings?.max_suggestions ?? DEFAULT_CALENDAR_TOOL_SETTINGS.maxSuggestions);
    const maxSuggestions = Number.isFinite(rawMaxSuggestions)
        ? Math.min(6, Math.max(1, Math.round(rawMaxSuggestions)))
        : DEFAULT_CALENDAR_TOOL_SETTINGS.maxSuggestions;

    const createGoogleMeet = (settings?.createGoogleMeet ?? settings?.create_google_meet) === true;

    return {
        agendaId: toNullableId(settings?.agendaId ?? settings?.agenda_id),
        allowedActions: allowedActions.length ? allowedActions : DEFAULT_CALENDAR_TOOL_SETTINGS.allowedActions,
        requireConfirmation: (settings?.requireConfirmation ?? settings?.require_confirmation) !== false,
        maxSuggestions,
        createGoogleMeet: createGoogleMeet && allowedActions.includes('create_appointment'),
        whenToUse: String(settings?.whenToUse ?? settings?.when_to_use ?? '')
    };
};

const sanitizeCrmPipelineStageRules = (rules?: any[]): CrmPipelineStageRule[] => (
    Array.isArray(rules) ? rules : []
)
    .map((rule) => ({
        stageId: Number(rule?.stageId ?? rule?.stage_id ?? 0),
        stageName: String(rule?.stageName ?? rule?.stage_name ?? '').trim(),
        advanceRule: String(rule?.advanceRule ?? rule?.advance_rule ?? ''),
        recedeRule: String(rule?.recedeRule ?? rule?.recede_rule ?? '')
    }))
    .filter((rule) => Number.isFinite(rule.stageId) && rule.stageId > 0);

const sanitizeCrmPipelineToolSettings = (settings?: any): CrmPipelineToolSettings => ({
    pipelineId: toNullableId(settings?.pipelineId ?? settings?.pipeline_id),
    stageRules: sanitizeCrmPipelineStageRules(settings?.stageRules ?? settings?.stage_rules),
    whenToUse: String(settings?.whenToUse ?? settings?.when_to_use ?? '')
});

const sanitizeContactCardKey = (value: string, fallback: string) => {
    const key = makeAgentKey(value || fallback).replace(/^agent$/, fallback);
    return key || fallback;
};

const sanitizeWhatsAppContactCards = (cards?: any[]): WhatsAppContactCardConfig[] => {
    const source = Array.isArray(cards) ? cards : [];
    const normalized = source.map((card, index) => {
        const fullName = String(card?.fullName ?? card?.full_name ?? card?.name ?? '');
        const fallbackKey = fullName.trim() || `contato_${index + 1}`;
        return {
            key: sanitizeContactCardKey(String(card?.key ?? card?.contact_key ?? ''), makeAgentKey(fallbackKey)),
            fullName,
            phoneNumber: String(card?.phoneNumber ?? card?.phone_number ?? card?.phone ?? ''),
            organization: String(card?.organization ?? ''),
            whatsappId: String(card?.whatsappId ?? card?.whatsapp_id ?? card?.waid ?? ''),
            whenToUse: String(card?.whenToUse ?? card?.when_to_use ?? card?.when ?? '')
        };
    });

    return normalized.length ? normalized : [createDefaultContactCard()];
};

const sanitizeWhatsAppContactCardToolSettings = (settings?: any): WhatsAppContactCardToolSettings => ({
    contactCards: sanitizeWhatsAppContactCards(settings?.contactCards ?? settings?.contact_cards ?? settings?.contacts),
    whenToUse: String(settings?.whenToUse ?? settings?.when_to_use ?? '')
});

const normalizeBooleanSetting = (value: any, fallback: boolean) => {
    if (typeof value === 'boolean') return value;
    if (value === undefined || value === null) return fallback;
    const normalized = String(value).trim().toLowerCase();
    if (['1', 'true', 'yes', 'sim', 'on'].includes(normalized)) return true;
    if (['0', 'false', 'no', 'nao', 'não', 'off'].includes(normalized)) return false;
    return fallback;
};

const sanitizeWhatsAppScheduledFollowupToolSettings = (settings?: any): WhatsAppScheduledFollowupToolSettings => ({
    whenToUse: String(settings?.whenToUse ?? settings?.when_to_use ?? ''),
    messageInstruction: String(settings?.messageInstruction ?? settings?.message_instruction ?? ''),
    replaceExistingPending: normalizeBooleanSetting(
        settings?.replaceExistingPending ?? settings?.replace_existing_pending,
        true
    )
});

const normalizeDynamicFollowupUnit = (value: any): DynamicFollowupTimeUnit => {
    const normalized = String(value || '').trim();
    return DYNAMIC_FOLLOWUP_TIME_UNIT_OPTIONS.some((option) => option.value === normalized)
        ? normalized as DynamicFollowupTimeUnit
        : 'hours';
};

const sanitizeDynamicFollowupDelay = (value: any) => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return 0;
    return Math.max(0, Math.min(365 * 24 * 60, Math.round(parsed)));
};

const sanitizeDynamicCrmFollowupSteps = (steps?: any[]): DynamicCrmFollowupStep[] => {
    const source = Array.isArray(steps) ? steps : [];
    const normalized = source.map((step, index) => ({
        stepNumber: index + 1,
        sendAfter: sanitizeDynamicFollowupDelay(step?.sendAfter ?? step?.send_after),
        sendAfterUnit: normalizeDynamicFollowupUnit(step?.sendAfterUnit ?? step?.send_after_unit),
        channel: 'whatsapp' as const,
        objective: String(step?.objective ?? step?.objetivo ?? ''),
        miniPrompt: String(step?.miniPrompt ?? step?.mini_prompt ?? '')
    }));

    return normalized.length ? normalized : [createDefaultDynamicCrmFollowupStep()];
};

const normalizeDynamicFollowupWeekdays = (value: any): number[] => {
    const source = Array.isArray(value) ? value : [];
    const weekdays = source
        .map((weekday: any) => Number(weekday))
        .filter((weekday: number) => Number.isInteger(weekday) && weekday >= 0 && weekday <= 6);
    return weekdays.length ? Array.from(new Set(weekdays)) : [...DYNAMIC_FOLLOWUP_DEFAULT_DELIVERY_WEEKDAYS];
};

const sanitizeDynamicFollowupTime = (value: any, fallback: string) => (
    isValidScheduleTime(value) ? String(value) : fallback
);

const normalizeDynamicFollowupBoolean = (value: any) => {
    if (typeof value === 'boolean') return value;
    if (value === 1) return true;
    return typeof value === 'string' && ['true', '1', 'yes', 'sim', 'on'].includes(value.trim().toLowerCase());
};

const sanitizeDynamicFollowupDeliveryWindow = (
    value: any,
    fallbackTimezone = DEFAULT_WORKFORCE_TIMEZONE
): DynamicCrmFollowupDeliveryWindow => {
    const source = value && typeof value === 'object' ? value : {};
    let startTime = sanitizeDynamicFollowupTime(
        source.startTime ?? source.start_time,
        DYNAMIC_FOLLOWUP_DEFAULT_START_TIME
    );
    let endTime = sanitizeDynamicFollowupTime(
        source.endTime ?? source.end_time,
        DYNAMIC_FOLLOWUP_DEFAULT_END_TIME
    );
    if (startTime >= endTime) {
        startTime = DYNAMIC_FOLLOWUP_DEFAULT_START_TIME;
        endTime = DYNAMIC_FOLLOWUP_DEFAULT_END_TIME;
    }

    return {
        enabled: normalizeDynamicFollowupBoolean(source.enabled),
        timezone: String(source.timezone ?? source.business_timezone ?? source.businessTimezone ?? fallbackTimezone),
        allowedWeekdays: normalizeDynamicFollowupWeekdays(source.allowedWeekdays ?? source.allowed_weekdays),
        startTime,
        endTime
    };
};

const sanitizeDynamicCrmFollowupToolSettings = (settings?: any): DynamicCrmFollowupToolSettings => {
    const timezone = String(settings?.timezone ?? settings?.business_timezone ?? DEFAULT_WORKFORCE_TIMEZONE);
    return {
        pipelineId: toNullableId(settings?.pipelineId ?? settings?.pipeline_id),
        targetStageIds: Array.isArray(settings?.targetStageIds)
            ? settings.targetStageIds.map((stageId: any) => Number(stageId)).filter((stageId: number) => Number.isFinite(stageId) && stageId > 0)
            : Array.isArray(settings?.target_stage_ids)
                ? settings.target_stage_ids.map((stageId: any) => Number(stageId)).filter((stageId: number) => Number.isFinite(stageId) && stageId > 0)
                : [],
        stopOnAppointmentCreated: normalizeBooleanSetting(
            settings?.stopOnAppointmentCreated ?? settings?.stop_on_appointment_created,
            true
        ),
        timezone,
        deliveryWindow: sanitizeDynamicFollowupDeliveryWindow(settings?.deliveryWindow ?? settings?.delivery_window, timezone),
        steps: sanitizeDynamicCrmFollowupSteps(settings?.steps)
    };
};

const getGeneratedContactCardKey = (card: WhatsAppContactCardConfig, index: number) => (
    sanitizeContactCardKey(card.fullName.trim() || card.key, `contato_${index + 1}`)
);

const getWhatsAppContactCardUsageSummary = (settings: WhatsAppContactCardToolSettings) => (
    settings.contactCards
        .map((card) => card.whenToUse.trim())
        .filter(Boolean)
        .join(' | ')
);

const getCrmStageRule = (
    settings: CrmPipelineToolSettings,
    stage: PipelineStage
): CrmPipelineStageRule => {
    const existing = settings.stageRules.find((rule) => Number(rule.stageId) === Number(stage.id));
    return {
        stageId: stage.id,
        stageName: stage.name,
        advanceRule: existing?.advanceRule || '',
        recedeRule: existing?.recedeRule || ''
    };
};

const getCrmStageRulesForPipeline = (
    settings: CrmPipelineToolSettings,
    stages: PipelineStage[]
): CrmPipelineStageRule[] => stages.map((stage) => getCrmStageRule(settings, stage));

const sanitizeToolSettings = (
    settings?: AgentToolSettings,
    tools?: string[]
): AgentToolSettings => {
    const selectedTools = sanitizeToolIds(tools);
    const nextSettings: AgentToolSettings = {};

    if (selectedTools.includes(CALENDAR_TOOL_ID)) {
        nextSettings[CALENDAR_TOOL_ID] = sanitizeCalendarToolSettings(settings?.[CALENDAR_TOOL_ID]);
    }
    if (selectedTools.includes(CRM_PIPELINE_TOOL_ID)) {
        nextSettings[CRM_PIPELINE_TOOL_ID] = sanitizeCrmPipelineToolSettings(settings?.[CRM_PIPELINE_TOOL_ID]);
    }
    if (selectedTools.includes(DYNAMIC_CRM_FOLLOWUP_TOOL_ID)) {
        nextSettings[DYNAMIC_CRM_FOLLOWUP_TOOL_ID] = sanitizeDynamicCrmFollowupToolSettings(settings?.[DYNAMIC_CRM_FOLLOWUP_TOOL_ID]);
    }
    if (selectedTools.includes(WHATSAPP_CONTACT_CARD_TOOL_ID)) {
        nextSettings[WHATSAPP_CONTACT_CARD_TOOL_ID] = sanitizeWhatsAppContactCardToolSettings(settings?.[WHATSAPP_CONTACT_CARD_TOOL_ID]);
    }
    if (selectedTools.includes(WHATSAPP_SCHEDULED_FOLLOWUP_TOOL_ID)) {
        nextSettings[WHATSAPP_SCHEDULED_FOLLOWUP_TOOL_ID] = sanitizeWhatsAppScheduledFollowupToolSettings(settings?.[WHATSAPP_SCHEDULED_FOLLOWUP_TOOL_ID]);
    }

    return nextSettings;
};

const syncHumanHandoffToolWithHumanEdges = (
    nodes: AgentNode[],
    edges: AgentEdge[]
): AgentNode[] => {
    const humanNodeIds = new Set(
        nodes
            .filter((node) => node.data.kind === 'human')
            .map((node) => node.id)
    );
    if (humanNodeIds.size === 0) {
        return nodes;
    }

    const agentIdsWithHumanTarget = new Set(
        edges
            .filter((edge) => edge.source && edge.target && humanNodeIds.has(edge.target))
            .map((edge) => edge.source)
    );
    if (agentIdsWithHumanTarget.size === 0) {
        return nodes;
    }

    let changed = false;
    const nextNodes = nodes.map((node) => {
        if (node.data.kind === 'human' || !agentIdsWithHumanTarget.has(node.id)) {
            return node;
        }

        const tools = sanitizeToolIds(node.data.tools);
        if (tools.includes(HUMAN_HANDOFF_TOOL_ID)) {
            return node;
        }

        changed = true;
        const nextTools = [...tools, HUMAN_HANDOFF_TOOL_ID];
        return {
            ...node,
            data: {
                ...node.data,
                tools: nextTools,
                toolSettings: sanitizeToolSettings(node.data.toolSettings, nextTools)
            }
        };
    });

    return changed ? nextNodes : nodes;
};

const createEmptyGuardrail = (index: number): CustomGuardrailData => ({
    key: `guardrail_${Date.now()}_${index + 1}`,
    name: '',
    stage: 'input',
    targetToolId: '',
    checkType: 'llm_classifier',
    condition: '',
    action: 'block',
    message: '',
    enabled: true
});

const CONSTRAINT_TYPES = ['Nunca fazer', 'Somente com confirmação', 'Transferir para humano'];

const getConstraintParts = (value: string) => {
    const cleanValue = value || '';
    const match = CONSTRAINT_TYPES.find((type) => cleanValue.startsWith(`${type}:`));
    if (!match) {
        return { type: CONSTRAINT_TYPES[0], text: cleanValue };
    }

    return {
        type: match,
        text: cleanValue.slice(match.length + 1).trimStart()
    };
};

const buildConstraintValue = (type: string, text: string) => `${type}: ${text}`;

const getFewShotSummary = (example: FewShotExampleData) => {
    const summary = example.user || example.assistant || example.context || 'Sem conteúdo ainda';
    return summary.length > 78 ? `${summary.slice(0, 78)}...` : summary;
};

const sanitizeConstraints = (values?: string[]) =>
    (values || [])
        .map((item) => {
            const { type, text } = getConstraintParts(item);
            return text.trim() ? buildConstraintValue(type, text.trim()) : '';
        })
        .filter(Boolean);

const sanitizeCustomGuardrails = (values?: CustomGuardrailData[], selectedToolIds?: string[]) => {
    const availableToolIds = sanitizeToolIds(selectedToolIds);
    return (values || [])
        .map((guardrail, index) => {
            const fallbackKey = makeAgentKey(guardrail.name || 'guardrail', String(index + 1));
            const rawTargetToolId = String(guardrail.targetToolId || (guardrail as any).target_tool_id || '').trim();
            const targetToolId = guardrail.stage === 'tool' && availableToolIds.includes(rawTargetToolId)
                ? rawTargetToolId
                : '';
            return {
                ...guardrail,
                key: makeAgentKey(guardrail.key || fallbackKey),
                name: guardrail.name.trim(),
                targetToolId,
                checkType: guardrail.stage === 'tool' && !['regex', 'keyword_filter'].includes(guardrail.checkType)
                    ? 'keyword_filter'
                    : guardrail.checkType,
                condition: guardrail.condition.trim(),
                message: guardrail.message?.trim() || '',
                enabled: guardrail.enabled !== false
            };
        })
        .filter((guardrail) => (
            guardrail.name
            && guardrail.condition
            && (guardrail.stage !== 'tool' || guardrail.targetToolId)
        ));
};

const sanitizeAgentNode = (node: AgentNode): AgentNode => {
    const data = { ...node.data };
    delete data.successCriteria;
    delete data.guardrails;
    const isHumanQueue = data.kind === 'human';
    const tools = isHumanQueue ? [] : sanitizeToolIds(node.data.tools);
    const toolSettings = isHumanQueue ? {} : sanitizeToolSettings(node.data.toolSettings, tools);

    return {
        ...node,
        data: {
            ...data,
            tools,
            toolSettings,
            customGuardrails: isHumanQueue ? [] : sanitizeCustomGuardrails(node.data.customGuardrails, tools),
            instructions: isHumanQueue ? [] : sanitizeStringList(node.data.instructions),
            conversationRules: isHumanQueue ? [] : sanitizeStringList(node.data.conversationRules),
            constraints: isHumanQueue ? [] : sanitizeConstraints(node.data.constraints),
            failureConditions: isHumanQueue ? [] : sanitizeStringList(node.data.failureConditions),
            fewShots: isHumanQueue ? [] : node.data.fewShots,
            promptContext: isHumanQueue ? '' : node.data.promptContext,
            audioEnabled: isHumanQueue ? false : Boolean(node.data.audioEnabled),
            audioProvider: 'elevenlabs',
            audioVoiceId: isHumanQueue ? '' : String(node.data.audioVoiceId || '').trim(),
            audioVoiceLabel: isHumanQueue ? '' : String(node.data.audioVoiceLabel || '').trim(),
            audioModelId: isHumanQueue ? DEFAULT_AUDIO_MODEL_ID : normalizeAudioModelId(node.data.audioModelId),
            audioOutputFormat: isHumanQueue ? DEFAULT_AUDIO_OUTPUT_FORMAT : (node.data.audioOutputFormat || DEFAULT_AUDIO_OUTPUT_FORMAT),
            humanQueue: isHumanQueue ? sanitizeHumanQueueConfig(node.data.humanQueue) : undefined
        }
    };
};

const getApprovalRequirement = (toolId: string) => {
    return toolId === HUMAN_HANDOFF_TOOL_ID
        || toolId === CALENDAR_TOOL_ID
        || toolId === CRM_PIPELINE_TOOL_ID
        || toolId === DYNAMIC_CRM_FOLLOWUP_TOOL_ID
        || toolId === WHATSAPP_CONTACT_CARD_TOOL_ID
        || toolId === WHATSAPP_SCHEDULED_FOLLOWUP_TOOL_ID;
};

const getToolUsagePolicy = (
    toolId: string,
    humanHandoffTargets: HumanHandoffTarget[],
    toolSettings?: AgentToolSettings
) => {
    if (toolId === 'calendar.scheduling') {
        const settings = sanitizeCalendarToolSettings(toolSettings?.[CALENDAR_TOOL_ID]);
        const customPolicy = settings.whenToUse.trim();
        if (customPolicy) {
            return customPolicy;
        }
        const policies = [
            'quando o lead pedir horários ou disponibilidade',
            settings.allowedActions.includes('create_appointment')
                ? 'quando o lead quiser marcar um horário'
                : '',
            settings.createGoogleMeet
                ? 'quando o atendimento for online e a agenda selecionada tiver vínculo com Google Agenda, retornar o link da reunião gerado pela tool'
                : '',
            settings.allowedActions.includes('reschedule_appointment')
                ? 'quando o lead quiser remarcar ou trocar dia/horário'
                : '',
            settings.allowedActions.includes('cancel_appointment')
                ? 'quando o lead confirmar que deseja cancelar ou excluir um agendamento'
                : ''
        ].filter(Boolean);
        return `${policies.join('; ')}; sugerir no máximo ${settings.maxSuggestions} horários por resposta; sempre consultar disponibilidade antes de criar ou reagendar e só executar ações após confirmação explícita do lead`;
    }

    if (toolId === HUMAN_HANDOFF_TOOL_ID && humanHandoffTargets.length > 0) {
        return humanHandoffTargets.map((target) => `${target.queue_name}: ${target.when}`).join(' | ');
    }

    if (toolId === CRM_PIPELINE_TOOL_ID) {
        const settings = sanitizeCrmPipelineToolSettings(toolSettings?.[CRM_PIPELINE_TOOL_ID]);
        return settings.whenToUse.trim()
            || 'quando uma regra configurada de avanço ou recuo de etapa do CRM estiver claramente atendida pela conversa';
    }

    if (toolId === DYNAMIC_CRM_FOLLOWUP_TOOL_ID) {
        const settings = sanitizeDynamicCrmFollowupToolSettings(toolSettings?.[DYNAMIC_CRM_FOLLOWUP_TOOL_ID]);
        return settings.targetStageIds.length > 0
            ? 'automação em background: iniciar quando o lead entrar no pipeline configurado e continuar até atingir a etapa objetivo'
            : 'automação em background: configurar pipeline, etapa objetivo e mini-prompts antes de ativar em produção';
    }

    if (toolId === WHATSAPP_CONTACT_CARD_TOOL_ID) {
        const settings = sanitizeWhatsAppContactCardToolSettings(toolSettings?.[WHATSAPP_CONTACT_CARD_TOOL_ID]);
        return settings.whenToUse.trim()
            || getWhatsAppContactCardUsageSummary(settings)
            || 'quando o lead precisar receber um contato humano, comercial ou operacional configurado como card WhatsApp';
    }

    if (toolId === WHATSAPP_SCHEDULED_FOLLOWUP_TOOL_ID) {
        const settings = sanitizeWhatsAppScheduledFollowupToolSettings(toolSettings?.[WHATSAPP_SCHEDULED_FOLLOWUP_TOOL_ID]);
        return settings.whenToUse.trim()
            || 'quando o lead combinar receber uma mensagem futura no WhatsApp e informar uma data com horário exato';
    }

    return 'quando o agente não conseguir resolver com segurança ou uma condição de falha exigir atendimento humano';
};

const getToolNotes = (toolId: string, humanHandoffTargets: HumanHandoffTarget[], toolSettings?: AgentToolSettings) => {
    if (toolId === 'calendar.scheduling') {
        const settings = sanitizeCalendarToolSettings(toolSettings?.[CALENDAR_TOOL_ID]);
        return settings.createGoogleMeet
            ? 'Consultar horários, criar agendamentos e retornar link Google Meet quando a agenda vinculada permitir.'
            : 'Consultar horários e criar agendamentos para leads usando agendas configuradas no menu Agenda.';
    }

    if (toolId === HUMAN_HANDOFF_TOOL_ID && humanHandoffTargets.length > 0) {
        return 'Criar tarefa para a fila humana conectada no organograma.';
    }

    if (toolId === CRM_PIPELINE_TOOL_ID) {
        return 'Consultar etapas do CRM e mover o lead no pipeline com histórico quando as regras configuradas forem atendidas.';
    }

    if (toolId === DYNAMIC_CRM_FOLLOWUP_TOOL_ID) {
        const settings = sanitizeDynamicCrmFollowupToolSettings(toolSettings?.[DYNAMIC_CRM_FOLLOWUP_TOOL_ID]);
        const deliveryWindowNote = settings.deliveryWindow.enabled
            ? ` Janela de envio: ${settings.deliveryWindow.startTime}-${settings.deliveryWindow.endTime} (${settings.deliveryWindow.timezone}).`
            : '';
        return `${settings.steps.length} passo(s) dinâmico(s) por WhatsApp até o lead chegar na etapa objetivo do CRM.${deliveryWindowNote}`;
    }

    if (toolId === WHATSAPP_CONTACT_CARD_TOOL_ID) {
        return 'Enviar um card de contato WhatsApp configurado para a conversa atual do lead.';
    }

    if (toolId === WHATSAPP_SCHEDULED_FOLLOWUP_TOOL_ID) {
        const settings = sanitizeWhatsAppScheduledFollowupToolSettings(toolSettings?.[WHATSAPP_SCHEDULED_FOLLOWUP_TOOL_ID]);
        return settings.messageInstruction.trim()
            || 'Agendar uma mensagem futura de WhatsApp para a conversa atual, usando o fuso da agenda da empresa.';
    }

    return '';
};

const getToolRequiredInputs = (toolId: string, toolSettings?: AgentToolSettings) => {
    if (toolId === 'calendar.scheduling') {
        const settings = sanitizeCalendarToolSettings(toolSettings?.[CALENDAR_TOOL_ID]);
        const requiredInputs = ['agenda_id ou agenda_name quando houver mais de uma agenda'];
        if (settings.allowedActions.includes('create_appointment')) {
            requiredInputs.push('lead_name', 'lead_phone', 'selected_start_time', 'confirmed_by_lead');
        }
        if (settings.allowedActions.includes('reschedule_appointment')) {
            requiredInputs.push('appointment_id ou lead_phone', 'new_start_time', 'confirmed_by_lead');
        }
        if (settings.allowedActions.includes('cancel_appointment')) {
            requiredInputs.push('appointment_id ou lead_phone', 'confirmed_by_lead');
        }
        return Array.from(new Set(requiredInputs));
    }

    if (toolId === CRM_PIPELINE_TOOL_ID) {
        return ['lead_phone do contexto', 'action', 'reason baseado na regra configurada'];
    }

    if (toolId === DYNAMIC_CRM_FOLLOWUP_TOOL_ID) {
        return ['pipeline_id', 'target_stage_ids', 'steps com send_after e mini_prompt', 'delivery_window opcional'];
    }

    if (toolId === WHATSAPP_CONTACT_CARD_TOOL_ID) {
        return ['nome e telefone do contato', 'regra de quando enviar'];
    }

    if (toolId === WHATSAPP_SCHEDULED_FOLLOWUP_TOOL_ID) {
        return ['data e horário exatos combinados com o lead', 'mensagem futura gerada pelo agente', 'motivo contextual'];
    }

    return [];
};

const getToolSettingsForMetadata = (
    toolId: string,
    toolSettings?: AgentToolSettings
) => {
    if (toolId === CALENDAR_TOOL_ID) {
        const settings = sanitizeCalendarToolSettings(toolSettings?.[CALENDAR_TOOL_ID]);
        return {
            agenda_id: settings.agendaId,
            allowed_actions: settings.allowedActions,
            require_confirmation: settings.requireConfirmation,
            max_suggestions: settings.maxSuggestions,
            create_google_meet: settings.createGoogleMeet,
            when_to_use: settings.whenToUse.trim()
        };
    }

    if (toolId === CRM_PIPELINE_TOOL_ID) {
        const settings = sanitizeCrmPipelineToolSettings(toolSettings?.[CRM_PIPELINE_TOOL_ID]);
        return {
            pipeline_id: settings.pipelineId,
            when_to_use: settings.whenToUse.trim(),
            stage_rules: settings.stageRules.map((rule) => ({
                stage_id: rule.stageId,
                stage_name: rule.stageName,
                advance_rule: rule.advanceRule.trim(),
                recede_rule: rule.recedeRule.trim()
            }))
        };
    }

    if (toolId === DYNAMIC_CRM_FOLLOWUP_TOOL_ID) {
        const settings = sanitizeDynamicCrmFollowupToolSettings(toolSettings?.[DYNAMIC_CRM_FOLLOWUP_TOOL_ID]);
        return {
            pipeline_id: settings.pipelineId,
            target_stage_ids: Array.from(new Set(settings.targetStageIds)),
            stop_on_appointment_created: settings.stopOnAppointmentCreated,
            timezone: settings.timezone,
            delivery_window: {
                enabled: settings.deliveryWindow.enabled,
                timezone: settings.deliveryWindow.timezone || settings.timezone,
                allowed_weekdays: Array.from(new Set(settings.deliveryWindow.allowedWeekdays)),
                start_time: settings.deliveryWindow.startTime,
                end_time: settings.deliveryWindow.endTime
            },
            steps: settings.steps
                .map((step, index) => ({
                    step_number: index + 1,
                    send_after: step.sendAfter,
                    send_after_unit: step.sendAfterUnit,
                    channel: 'whatsapp',
                    objective: step.objective.trim(),
                    mini_prompt: step.miniPrompt.trim()
                }))
                .filter((step) => step.mini_prompt)
        };
    }

    if (toolId === WHATSAPP_CONTACT_CARD_TOOL_ID) {
        const settings = sanitizeWhatsAppContactCardToolSettings(toolSettings?.[WHATSAPP_CONTACT_CARD_TOOL_ID]);
        const contactCards = settings.contactCards
            .map((card, index) => ({
                key: getGeneratedContactCardKey(card, index),
                full_name: card.fullName.trim(),
                phone_number: card.phoneNumber.trim(),
                when_to_use: card.whenToUse.trim()
            }))
            .filter((card) => card.key && card.full_name && card.phone_number);

        return {
            when_to_use: settings.whenToUse.trim()
                || contactCards.map((card) => card.when_to_use).filter(Boolean).join(' | '),
            contact_cards: contactCards
        };
    }

    if (toolId === WHATSAPP_SCHEDULED_FOLLOWUP_TOOL_ID) {
        const settings = sanitizeWhatsAppScheduledFollowupToolSettings(toolSettings?.[WHATSAPP_SCHEDULED_FOLLOWUP_TOOL_ID]);
        return {
            when_to_use: settings.whenToUse.trim(),
            message_instruction: settings.messageInstruction.trim(),
            replace_existing_pending: settings.replaceExistingPending
        };
    }

    return {};
};

const buildToolSettingsMetadata = (
    tools: string[],
    toolSettings?: AgentToolSettings
) => tools.reduce<Record<string, any>>((acc, toolId) => {
    const settings = getToolSettingsForMetadata(toolId, toolSettings);
    if (Object.keys(settings).length > 0) {
        acc[toolId] = settings;
    }
    return acc;
}, {});

const getApiErrorMessage = (error: unknown, fallback: string) => {
    const detail = (error as any)?.response?.data?.detail;
    if (typeof detail === 'string') {
        return detail;
    }
    if (Array.isArray(detail)) {
        const messages = detail
            .map((item) => item?.msg || item?.detail)
            .filter(Boolean);
        if (messages.length > 0) {
            return messages.join(' ');
        }
    }
    return fallback;
};

const buildAgentConfig = (node: AgentNode, nodes: AgentNode[], edges: AgentEdge[]) => {
    const outgoing = edges.filter((edge) => edge.source === node.id);
    const selectedTools = sanitizeToolIds(node.data.tools);
    const canUseHumanHandoff = selectedTools.includes(HUMAN_HANDOFF_TOOL_ID);
    const humanHandoffTargets = canUseHumanHandoff ? outgoing
        .map((edge) => {
            const target = nodes.find((candidate) => candidate.id === edge.target);
            if (!target || target.data.kind !== 'human') return null;
            return {
                queue_key: target.data.key,
                queue_name: target.data.name,
                when: edge.data?.rule || String(edge.label || 'Quando precisar de atendimento humano.'),
                assignment: sanitizeHumanQueueConfig(target.data.humanQueue)
            };
        })
        .filter((target): target is HumanHandoffTarget => Boolean(target)) : [];
    const handoffs = outgoing
        .map((edge) => {
            const target = nodes.find((candidate) => candidate.id === edge.target);
            if (!target || target.data.kind === 'human') return null;
            return {
                target_agent: target.data.key,
                when: edge.data?.rule || String(edge.label || 'Quando o especialista for mais adequado.'),
                owns_final_response: true,
                description: `Transferir para ${target.data.name}.`
            };
        })
        .filter(Boolean);

    const qualificationFields = node.data.qualification === 'none'
        ? []
        : ['necessidade', 'urgencia', 'orcamento', 'autoridade'];
    const instructions = sanitizeStringList(node.data.instructions);
    const constraints = sanitizeConstraints(node.data.constraints);
    const conversationRules = sanitizeStringList(node.data.conversationRules);
    const failureConditions = sanitizeStringList(node.data.failureConditions);
    const fewShots = node.data.fewShots || [];
    const customGuardrails = sanitizeCustomGuardrails(node.data.customGuardrails, selectedTools);
    const audioEnabled = Boolean(node.data.audioEnabled && node.data.audioVoiceId);
    const audioVoice = audioEnabled
        ? {
            provider: 'elevenlabs',
            voice_id: node.data.audioVoiceId,
            label: node.data.audioVoiceLabel || node.data.audioVoiceId,
            model_id: normalizeAudioModelId(node.data.audioModelId),
            output_format: node.data.audioOutputFormat || DEFAULT_AUDIO_OUTPUT_FORMAT
        }
        : null;

    return {
        schema_version: '2026-05-01',
        agent: {
            key: node.data.key,
            name: node.data.name,
            role: node.data.role,
            organization_type: 'generic',
            language: 'pt-BR',
            tone: getTonePresetValue(node.data.tone, node.data.kind),
            description: node.data.description,
            handoff_description: node.data.goal
        },
        channel: {
            type: 'whatsapp',
            message_style: 'curto, natural e objetivo',
            max_response_sentences: 3,
            allow_audio: audioEnabled,
            voice: audioVoice,
            business_timezone: 'America/Sao_Paulo'
        },
        objective: {
            primary_goal: node.data.goal,
            user_outcome: 'Contato entende o próximo passo e a empresa recebe contexto acionável.',
            failure_conditions: failureConditions
        },
        prompt_techniques: {
            framework: 'agent_standard',
            context: node.data.promptContext || '',
            instructions,
            constraints,
            conversation_rules: conversationRules,
            variables: ['contact_name', 'contact_phone', 'current_stage', 'conversation_step'],
            qualification_method: {
                type: node.data.qualification,
                required_fields: qualificationFields,
                optional_fields: ['origem', 'preferencia_de_horario', 'observacoes'],
                disqualifiers: []
            },
            few_shots: fewShots.filter((example) => example.user.trim() && example.assistant.trim()),
            objection_handling: [],
            tool_policy: selectedTools.map((tool) => ({
                tool,
                when: getToolUsagePolicy(tool, humanHandoffTargets, node.data.toolSettings),
                requires: getToolRequiredInputs(tool, node.data.toolSettings),
                side_effect: getApprovalRequirement(tool),
                retry_safety: 'nao repetir se houver risco de duplicar uma acao'
            })),
            custom_sections: {}
        },
        model: {
            model: node.data.model,
            temperature: 0.4,
            max_turns: 10,
            reasoning_effort: getNormalizedReasoningEffort(node.data.model, node.data.reasoningEffort),
            verbosity: 'medium',
            tool_choice: 'auto',
            parallel_tool_calls: true
        },
        tools: selectedTools.map((tool) => ({
            id: tool,
            enabled: true,
            requires_approval: getApprovalRequirement(tool),
            notes: getToolNotes(tool, humanHandoffTargets, node.data.toolSettings),
            settings: getToolSettingsForMetadata(tool, node.data.toolSettings)
        })),
        handoffs,
        custom_guardrails: customGuardrails.map((guardrail) => ({
            key: guardrail.key,
            name: guardrail.name,
            stage: guardrail.stage,
            target_tool_id: guardrail.stage === 'tool' ? guardrail.targetToolId || null : null,
            check_type: guardrail.checkType,
            condition: guardrail.condition,
            action: guardrail.action,
            enabled: guardrail.enabled,
            message: guardrail.message || ''
        })),
        output: {
            mode: 'text',
            notes: 'Resposta final pronta para WhatsApp.'
        },
        metadata: {
            source: 'agents-ui-v1',
            node_id: node.id,
            kind: node.data.kind,
            custom_guardrail_count: customGuardrails.length,
            human_handoff_targets: humanHandoffTargets,
            audio_voice: audioVoice,
            tool_settings: buildToolSettingsMetadata(selectedTools, node.data.toolSettings)
        }
    };
};

const buildAgentConfigs = (nodes: AgentNode[], edges: AgentEdge[]) => {
    return nodes.reduce<Record<string, any>>((acc, node) => {
        if (node.data.kind === 'human') {
            return acc;
        }
        acc[node.data.key] = buildAgentConfig(node, nodes, edges);
        return acc;
    }, {});
};

const buildHumanQueues = (nodes: AgentNode[]) =>
    nodes
        .filter((node) => node.data.kind === 'human')
        .map((node) => ({
            key: node.data.key,
            name: node.data.name,
            description: node.data.goal,
            assignment: sanitizeHumanQueueConfig(node.data.humanQueue)
        }));

const buildWorkforceSettings = (
    nodes: AgentNode[],
    agentContext: WorkforceAgentContextSettings
) => ({
    orchestration: 'handoff',
    channel: 'whatsapp',
    source: 'agents-ui-v1',
    recommended_flow_builder_node: 'agentWorkforce',
    human_queues: buildHumanQueues(nodes),
    agent_context: {
        global_context: agentContext.global_context,
        global_few_shots: {
            enabled: agentContext.global_few_shots.enabled,
            examples: agentContext.global_few_shots.examples
                .map((example) => ({
                    title: (example.title || '').trim(),
                    tags: (example.tags || '').trim(),
                    context: (example.context || '').trim(),
                    user: (example.user || '').trim(),
                    assistant: (example.assistant || '').trim(),
                    enabled: example.enabled !== false
                }))
                .filter((example) => example.user && example.assistant)
        },
        knowledge: agentContext.knowledge,
        performance: agentContext.performance,
        schedule: agentContext.schedule
    }
});

const FieldLabel: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const { isDark } = useTheme();

    return (
        <label className={`text-[10px] font-bold uppercase tracking-[0.16em] ${isDark ? 'text-white/40' : 'text-brand/40'}`}>
            {children}
        </label>
    );
};

const HelpFieldLabel: React.FC<{ children: React.ReactNode; help: string }> = ({ children, help }) => {
    const { isDark } = useTheme();

    return (
        <div className="group relative flex min-w-0 flex-1 items-center gap-1.5">
            <FieldLabel>{children}</FieldLabel>
            <span className="inline-flex shrink-0">
                <Info className={`h-3.5 w-3.5 ${isDark ? 'text-white/35' : 'text-brand/35'}`} aria-label={`Ajuda: ${children}`} />
            </span>
            <span
                role="tooltip"
                className={`pointer-events-none absolute bottom-[calc(100%+8px)] left-0 right-0 z-[999] rounded-xl border px-3 py-2 text-left text-[11px] font-normal leading-4 opacity-0 shadow-[0_18px_45px_rgba(2,3,35,0.18)] transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 ${
                    isDark ? 'border-white/10 bg-brand text-white/65' : 'border-brand/10 bg-white text-brand/65'
                }`}
            >
                {help}
            </span>
        </div>
    );
};

const knowledgeStatusLabel = (status?: any): string => {
    const normalized = String(status || '').toLowerCase();
    if (normalized === 'completed') return 'indexado';
    if (normalized === 'in_progress' || normalized === 'processing') return 'processando';
    if (normalized === 'failed') return 'falhou';
    if (normalized === 'cancelled') return 'cancelado';
    if (normalized === 'missing') return 'removido';
    return 'processando';
};

const knowledgeStatusClass = (status?: any): string => {
    const normalized = String(status || '').toLowerCase();
    if (normalized === 'completed') return 'bg-emerald-50 text-emerald-700';
    if (normalized === 'failed' || normalized === 'cancelled' || normalized === 'missing') return 'bg-red-50 text-red-600';
    return 'bg-amber-50 text-amber-700';
};

const IconSelect: React.FC<{
    value?: string;
    kind?: AgentKind;
    onChange: (value: string) => void;
}> = ({ value, kind, onChange }) => {
    const { isDark } = useTheme();
    const selectedKey = getSelectableIconKey(value, kind);
    const selectedOption = ICON_OPTIONS.find((option) => option.key === selectedKey) || ICON_OPTIONS[0];
    const SelectedIcon = selectedOption.icon;

    return (
        <div className="mt-1 flex items-center gap-2">
            <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border ${isDark ? 'border-white/10 bg-white/[0.06] text-white/70' : 'border-brand/10 bg-brand-canvas text-brand/70'}`}>
                <SelectedIcon className="h-4 w-4" />
            </div>
            <div className="relative min-w-0 flex-1">
                <select
                    value={selectedKey}
                    onChange={(event) => onChange(event.target.value)}
                    className={`w-full appearance-none rounded-xl border px-3 py-2 pr-8 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20 ${
                        isDark ? 'border-white/10 bg-white/[0.06] text-white' : 'border-brand/10 bg-white text-brand'
                    }`}
                >
                    {ICON_OPTIONS.map((option) => (
                        <option key={option.key} value={option.key}>{option.label}</option>
                    ))}
                </select>
                <ChevronDown className={builderChevronClass(isDark, 'right-2.5')} />
            </div>
        </div>
    );
};

const HumanQueueInspector: React.FC<{
    node: AgentNode;
    users: User[];
    teams: Team[];
    inputClass: string;
    onNameChange: (value: string) => void;
    onNodeDataChange: (field: keyof AgentNodeData, value: any) => void;
    onHumanQueueChange: (patch: Partial<HumanQueueConfig>) => void;
}> = ({ node, users, teams, inputClass, onNameChange, onNodeDataChange, onHumanQueueChange }) => {
    const { isDark } = useTheme();
    const config = normalizeHumanQueueConfig(node.data.humanQueue);
    const [tagDraft, setTagDraft] = useState('');
    const selectedSla = config.slaMinutes ?? null;
    const availableTagSuggestions = HUMAN_TAG_SUGGESTIONS.filter(
        (suggestion) => !config.tags.some((tag) => tag.toLowerCase() === suggestion.toLowerCase())
    );

    const addTags = (rawTags: string[]) => {
        const seen = new Set(config.tags.map((tag) => tag.toLowerCase()));
        const nextTags = [...config.tags];

        rawTags.forEach((rawTag) => {
            const cleanTag = rawTag.trim();
            const tagKey = cleanTag.toLowerCase();
            if (!cleanTag || seen.has(tagKey)) return;
            seen.add(tagKey);
            nextTags.push(cleanTag);
        });

        if (nextTags.length !== config.tags.length) {
            onHumanQueueChange({ tags: nextTags });
        }
    };

    const commitTagDraft = () => {
        const nextTags = parseHumanTags(tagDraft);
        if (nextTags.length === 0) return;
        addTags(nextTags);
        setTagDraft('');
    };

    const handleTagInputChange = (value: string) => {
        if (value.includes(',')) {
            addTags(parseHumanTags(value));
            setTagDraft('');
            return;
        }
        setTagDraft(value);
    };

    const handleTagKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
        if (event.key === 'Enter' || event.key === ',') {
            event.preventDefault();
            commitTagDraft();
            return;
        }

        if (event.key === 'Backspace' && !tagDraft && config.tags.length > 0) {
            onHumanQueueChange({ tags: config.tags.slice(0, -1) });
        }
    };

    const removeTag = (tagToRemove: string) => {
        onHumanQueueChange({
            tags: config.tags.filter((tag) => tag !== tagToRemove)
        });
    };

    return (
        <div className="space-y-4">
            <div className={flowNodePanelClass(isDark, 'pink')}>
                <div className="flex items-center gap-2 text-sm font-semibold">
                    <Users className="h-4 w-4" />
                    Fila humana
                </div>
                <p className={`mt-1 text-xs leading-5 ${isDark ? 'text-white/60' : 'text-brand/60'}`}>
                    Destino operacional para transferir a conversa a pessoas cadastradas na configuração da empresa.
                </p>
            </div>

            <div>
                <FieldLabel>Nome</FieldLabel>
                <input
                    value={node.data.name}
                    onChange={(event) => onNameChange(event.target.value)}
                    className={builderInputClass(isDark, 'mt-1')}
                />
            </div>

            <div>
                <FieldLabel>Ícone</FieldLabel>
                <IconSelect
                    value={node.data.iconKey}
                    kind={node.data.kind}
                    onChange={(iconKey) => onNodeDataChange('iconKey', iconKey)}
                />
            </div>

            <div>
                <HelpFieldLabel help="Defina em quais situações esta fila deve receber conversas. A regra específica de cada transferência continua sendo configurada na conexão do organograma.">
                    Quando usar esta fila
                </HelpFieldLabel>
                <textarea
                    value={node.data.goal}
                    onChange={(event) => onNodeDataChange('goal', event.target.value)}
                    className={builderTextareaClass(isDark, 'mt-1 h-24')}
                    placeholder="Ex: negociações sensíveis, exceções, dúvidas fora do escopo ou pedidos que exigem decisão humana."
                />
            </div>

            <div className={builderPanelClass(isDark)}>
                <div className="mb-3 flex items-center gap-2">
                    <UserCog className={`h-4 w-4 ${isDark ? 'text-white/50' : 'text-brand/50'}`} />
                    <FieldLabel>Destino de atendimento</FieldLabel>
                </div>

                <div className="space-y-3">
                    <div>
                        <FieldLabel>Atribuir para</FieldLabel>
                        <div className="relative mt-1">
                            <select
                                value={config.assignmentType}
                                onChange={(event) => {
                                    const assignmentType = event.target.value as HumanAssignmentType;
                                    onHumanQueueChange({
                                        assignmentType,
                                        teamId: null,
                                        userId: null,
                                        strategy: assignmentType === 'user' ? 'manual' : config.strategy
                                    });
                                }}
                                className={builderSelectClass(isDark)}
                            >
                                {HUMAN_ASSIGNMENT_OPTIONS.map((option) => (
                                    <option key={option.value} value={option.value}>{option.label}</option>
                                ))}
                            </select>
                            <ChevronDown className={builderChevronClass(isDark)} />
                        </div>
                    </div>

                    {config.assignmentType === 'team' ? (
                        <div>
                            <FieldLabel>Equipe</FieldLabel>
                            <div className="relative mt-1">
                                <select
                                    value={config.teamId ?? ''}
                                    onChange={(event) => onHumanQueueChange({ teamId: event.target.value ? Number(event.target.value) : null })}
                                    className={builderSelectClass(isDark)}
                                >
                                    <option value="">Selecione uma equipe</option>
                                    {teams.map((team) => (
                                        <option key={team.id} value={team.id}>
                                            {team.name}{team.user_count ? ` (${team.user_count})` : ''}
                                        </option>
                                    ))}
                                </select>
                                <ChevronDown className={builderChevronClass(isDark)} />
                            </div>
                        </div>
                    ) : (
                        <div>
                            <FieldLabel>Usuário</FieldLabel>
                            <div className="relative mt-1">
                                <select
                                    value={config.userId ?? ''}
                                    onChange={(event) => onHumanQueueChange({ userId: event.target.value ? Number(event.target.value) : null })}
                                    className={builderSelectClass(isDark)}
                                >
                                    <option value="">Selecione um usuário</option>
                                    {users.map((user) => (
                                        <option key={user.id} value={user.id}>
                                            {user.name || user.email}
                                        </option>
                                    ))}
                                </select>
                                <ChevronDown className={builderChevronClass(isDark)} />
                            </div>
                        </div>
                    )}

                    {config.assignmentType === 'team' && (
                        <div>
                            <FieldLabel>Distribuição</FieldLabel>
                            <div className="relative mt-1">
                                <select
                                    value={config.strategy}
                                    onChange={(event) => onHumanQueueChange({ strategy: event.target.value as HumanAssignmentStrategy })}
                                    className={builderSelectClass(isDark)}
                                >
                                    {HUMAN_STRATEGY_OPTIONS.map((option) => (
                                        <option key={option.value} value={option.value}>{option.label}</option>
                                    ))}
                                </select>
                                <ChevronDown className={builderChevronClass(isDark)} />
                            </div>
                        </div>
                    )}

                    <div>
                        <FieldLabel>Prioridade</FieldLabel>
                        <div className="relative mt-1">
                            <select
                                value={config.priority}
                                onChange={(event) => onHumanQueueChange({ priority: event.target.value as HumanQueuePriority })}
                                className={builderSelectClass(isDark)}
                            >
                                {HUMAN_PRIORITY_OPTIONS.map((option) => (
                                    <option key={option.value} value={option.value}>{option.label}</option>
                                ))}
                            </select>
                            <ChevronDown className={builderChevronClass(isDark)} />
                        </div>
                    </div>

                    <div>
                        <div className="flex items-center justify-between gap-3">
                            <HelpFieldLabel help="Prazo esperado para alguém assumir a conversa depois que o handoff humano for criado. Use vazio quando não houver meta de atendimento.">
                                Prazo de resposta
                            </HelpFieldLabel>
                            {selectedSla && (
                                <button
                                    type="button"
                                    onClick={() => onHumanQueueChange({ slaMinutes: null })}
                                    className={`shrink-0 text-xs font-medium transition ${isDark ? 'text-white/40 hover:text-red-300' : 'text-brand/40 hover:text-red-600'}`}
                                >
                                    Limpar
                                </button>
                            )}
                        </div>

                        <div className="mt-2 grid grid-cols-4 gap-1.5">
                            {HUMAN_SLA_PRESETS.map((preset) => (
                                <button
                                    key={preset.value}
                                    type="button"
                                    onClick={() => onHumanQueueChange({ slaMinutes: preset.value })}
                                    className={`min-h-[34px] rounded-xl border px-2 text-xs font-semibold transition ${selectedSla === preset.value
                                        ? 'border-brand bg-brand text-white'
                                        : isDark ? 'border-white/10 bg-white/[0.04] text-white/60 hover:bg-white/10 hover:text-white' : 'border-brand/10 bg-white text-brand/60 hover:bg-brand-canvas hover:text-brand'
                                        }`}
                                >
                                    {preset.label}
                                </button>
                            ))}
                        </div>

                        <div className={`mt-2 flex items-center rounded-xl border transition focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/20 ${isDark ? 'border-white/10 bg-white/[0.06]' : 'border-brand/10 bg-white'}`}>
                            <input
                                type="number"
                                min={1}
                                value={config.slaMinutes ?? ''}
                                onChange={(event) => onHumanQueueChange({ slaMinutes: event.target.value ? Number(event.target.value) : null })}
                                className={builderInlineInputClass(isDark, 'px-3 py-2')}
                                placeholder="Outro prazo"
                            />
                            <span className={`shrink-0 border-l px-3 text-xs font-medium ${isDark ? 'border-white/10 text-white/40' : 'border-brand/10 text-brand/40'}`}>
                                min
                            </span>
                        </div>
                    </div>
                </div>
            </div>

            <label className={builderToggleCardClass(isDark, config.silentTransfer)}>
                <input
                    type="checkbox"
                    checked={config.silentTransfer}
                    onChange={(event) => onHumanQueueChange({ silentTransfer: event.target.checked })}
                    className={builderCheckboxClass(isDark, 'mt-1')}
                />
                <span className="min-w-0">
                    <span className="block font-semibold">Transferência silenciosa</span>
                    <span className={builderMutedTextClass(isDark, 'mt-1 block text-xs leading-5')}>
                        Cria a tarefa, pausa a IA e deixa a pessoa assumir sem aviso automático no WhatsApp.
                    </span>
                </span>
            </label>

            <div>
                <HelpFieldLabel help="Mensagem que o agente pode enviar antes de criar a tarefa para atendimento humano. Ela deve ser curta e natural para WhatsApp.">
                    Mensagem de transferência
                </HelpFieldLabel>
                <textarea
                    value={config.transferMessage}
                    onChange={(event) => onHumanQueueChange({ transferMessage: event.target.value })}
                    disabled={config.silentTransfer}
                    className={builderTextareaClass(isDark, `mt-1 h-20 ${config.silentTransfer ? 'opacity-60' : ''}`)}
                    placeholder="Ex: Vou transferir para um atendente humano continuar."
                />
            </div>

            <div>
                <HelpFieldLabel help="Use etiquetas para classificar tarefas humanas e facilitar filtros futuros no atendimento. Pressione Enter para adicionar.">
                    Etiquetas
                </HelpFieldLabel>
                <div className={`mt-1 rounded-xl border p-2 transition focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/20 ${isDark ? 'border-white/10 bg-white/[0.06]' : 'border-brand/10 bg-white'}`}>
                    <div className="flex min-h-[34px] flex-wrap items-center gap-1.5">
                        {config.tags.map((tag) => (
                            <span
                                key={tag}
                                className={agentivePillClass(isDark, false, 'max-w-full')}
                            >
                                <span className="truncate">{tag}</span>
                                <button
                                    type="button"
                                    onClick={() => removeTag(tag)}
                                    className={`rounded-full p-0.5 transition ${isDark ? 'text-white/40 hover:bg-white/10 hover:text-red-300' : 'text-brand/40 hover:bg-white hover:text-red-600'}`}
                                    title={`Remover ${tag}`}
                                >
                                    <X className="h-3 w-3" />
                                </button>
                            </span>
                        ))}
                        <input
                            value={tagDraft}
                            onChange={(event) => handleTagInputChange(event.target.value)}
                            onKeyDown={handleTagKeyDown}
                            onBlur={commitTagDraft}
                            className={builderInlineInputClass(isDark, 'min-h-[30px] min-w-[128px] px-1')}
                            placeholder={config.tags.length ? 'Adicionar etiqueta' : 'Ex: urgência'}
                        />
                    </div>
                </div>

                {availableTagSuggestions.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                        {availableTagSuggestions.slice(0, 4).map((tag) => (
                            <button
                                key={tag}
                                type="button"
                                onClick={() => addTags([tag])}
                                className={agentivePillClass(isDark, false)}
                            >
                                <Plus className="h-3 w-3" />
                                {tag}
                            </button>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
};

const PromptListField: React.FC<{
    label: string;
    help: string;
    values: string[];
    addLabel: string;
    placeholder: string;
    emptyText: string;
    onChange: (values: string[]) => void;
}> = ({ label, help, values, addLabel, placeholder, emptyText, onChange }) => {
    const { isDark } = useTheme();
    const items = values || [];

    const updateItem = (index: number, value: string) => {
        onChange(items.map((item, itemIndex) => (itemIndex === index ? value : item)));
    };

    const addItem = (afterIndex?: number) => {
        if (typeof afterIndex === 'number') {
            const nextItems = [...items];
            nextItems.splice(afterIndex + 1, 0, '');
            onChange(nextItems);
            return;
        }

        onChange([...items, '']);
    };

    const removeItem = (index: number) => {
        onChange(items.filter((_, itemIndex) => itemIndex !== index));
    };

    const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>, index: number) => {
        if (event.key === 'Enter') {
            event.preventDefault();
            addItem(index);
        }
    };

    return (
        <div className={builderPanelClass(isDark)}>
            <div className="flex items-center justify-between gap-3">
                <HelpFieldLabel help={help}>{label}</HelpFieldLabel>
                <button
                    type="button"
                    onClick={() => addItem()}
                    className={agentiveSecondaryButtonClass(isDark, 'shrink-0 px-2.5 py-1.5 text-xs')}
                >
                    <Plus className="h-3.5 w-3.5" />
                    {addLabel}
                </button>
            </div>

            <div className="mt-3 space-y-2">
                {items.length === 0 ? (
                    <div className={builderEmptyClass(isDark, 'py-3 text-xs')}>
                        {emptyText}
                    </div>
                ) : (
                    items.map((item, index) => (
                        <div key={`${label}-${index}`} className={builderSurfaceClass(isDark, 'flex items-center gap-2 px-2 py-2')}>
                            <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-lg text-[11px] font-semibold ${isDark ? 'bg-white/10 text-white/55' : 'bg-brand-canvas text-brand/55'}`}>
                                {index + 1}
                            </span>
                            <input
                                value={item}
                                onChange={(event) => updateItem(index, event.target.value)}
                                onKeyDown={(event) => handleKeyDown(event, index)}
                                className={builderInlineInputClass(isDark)}
                                placeholder={placeholder}
                            />
                            <button
                                type="button"
                                onClick={() => removeItem(index)}
                                className={agentiveIconButtonClass(isDark, 'danger', 'min-h-8 min-w-8 p-1.5')}
                                title="Remover item"
                            >
                                <Trash2 className="h-3.5 w-3.5" />
                            </button>
                        </div>
                    ))
                )}
            </div>
        </div>
    );
};

const ConstraintListField: React.FC<{
    values: string[];
    onChange: (values: string[]) => void;
}> = ({ values, onChange }) => {
    const { isDark } = useTheme();
    const items = values || [];

    const updateItem = (index: number, value: string) => {
        onChange(items.map((item, itemIndex) => (itemIndex === index ? value : item)));
    };

    const updateType = (index: number, type: string) => {
        const current = getConstraintParts(items[index] || '');
        updateItem(index, buildConstraintValue(type, current.text));
    };

    const updateText = (index: number, text: string) => {
        const current = getConstraintParts(items[index] || '');
        updateItem(index, buildConstraintValue(current.type, text));
    };

    const addItem = (afterIndex?: number) => {
        const nextValue = buildConstraintValue(CONSTRAINT_TYPES[0], '');
        if (typeof afterIndex === 'number') {
            const nextItems = [...items];
            nextItems.splice(afterIndex + 1, 0, nextValue);
            onChange(nextItems);
            return;
        }

        onChange([...items, nextValue]);
    };

    const removeItem = (index: number) => {
        onChange(items.filter((_, itemIndex) => itemIndex !== index));
    };

    const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>, index: number) => {
        if (event.key === 'Enter') {
            event.preventDefault();
            addItem(index);
        }
    };

    return (
        <div className={builderPanelClass(isDark)}>
            <div className="flex items-center justify-between gap-3">
                <HelpFieldLabel help="Liste o que este agente não pode fazer, prometer ou responder. Use para bloquear assuntos, promessas, decisões sensíveis e ações sem dados suficientes.">
                    Limites e restrições
                </HelpFieldLabel>
                <button
                    type="button"
                    onClick={() => addItem()}
                    className={agentiveSecondaryButtonClass(isDark, 'shrink-0 px-2.5 py-1.5 text-xs')}
                >
                    <Plus className="h-3.5 w-3.5" />
                    Restrição
                </button>
            </div>

            <div className="mt-3 space-y-2">
                {items.length === 0 ? (
                    <div className={builderEmptyClass(isDark, 'py-3 text-xs')}>
                        Nenhuma restrição adicionada.
                    </div>
                ) : (
                    items.map((item, index) => {
                        const parts = getConstraintParts(item);
                        return (
                            <div key={`constraint-${index}`} className={builderSurfaceClass(isDark, 'p-2')}>
                                <div className="flex items-center gap-2">
                                    <div className="relative min-w-0 flex-1">
                                        <select
                                            value={parts.type}
                                            onChange={(event) => updateType(index, event.target.value)}
                                            className={`w-full appearance-none rounded-xl border px-2.5 py-2 pr-7 text-xs font-semibold outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20 ${
                                                isDark ? 'border-white/10 bg-white/[0.06] text-white' : 'border-brand/10 bg-brand-canvas text-brand'
                                            }`}
                                        >
                                            {CONSTRAINT_TYPES.map((type) => (
                                                <option key={type} value={type}>{type}</option>
                                            ))}
                                        </select>
                                        <ChevronDown className={builderChevronClass(isDark, 'h-3.5 w-3.5')} />
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => removeItem(index)}
                                        className={agentiveIconButtonClass(isDark, 'danger')}
                                        title="Remover restrição"
                                    >
                                        <Trash2 className="h-3.5 w-3.5" />
                                    </button>
                                </div>
                                <input
                                    value={parts.text}
                                    onChange={(event) => updateText(index, event.target.value)}
                                    onKeyDown={(event) => handleKeyDown(event, index)}
                                    className={`mt-2 w-full rounded-xl border px-2.5 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20 ${
                                        isDark ? 'border-white/10 bg-white/[0.06] text-white placeholder:text-white/35' : 'border-brand/10 bg-white text-brand placeholder:text-brand/35'
                                    }`}
                                    placeholder="Ex: prometer preço, prazo ou disponibilidade sem ferramenta confiável"
                                />
                            </div>
                        );
                    })
                )}
            </div>
        </div>
    );
};

const CustomGuardrailListField: React.FC<{
    values: CustomGuardrailData[];
    availableTools: string[];
    onChange: (values: CustomGuardrailData[]) => void;
}> = ({ values, availableTools, onChange }) => {
    const { isDark } = useTheme();
    const items = values || [];
    const availableToolOptions = TOOL_OPTIONS.filter((tool) => availableTools.includes(tool.id));
    const firstAvailableToolId = availableToolOptions[0]?.id || '';

    const updateItem = (index: number, patch: Partial<CustomGuardrailData>) => {
        onChange(items.map((item, itemIndex) => (itemIndex === index ? { ...item, ...patch } : item)));
    };

    const updateStage = (index: number, guardrail: CustomGuardrailData, stage: GuardrailStage) => {
        updateItem(index, {
            stage,
            targetToolId: stage === 'tool' ? guardrail.targetToolId || firstAvailableToolId : '',
            checkType: stage === 'tool' && !['regex', 'keyword_filter'].includes(guardrail.checkType)
                ? 'keyword_filter'
                : guardrail.checkType
        });
    };

    const addItem = () => {
        onChange([...items, createEmptyGuardrail(items.length)]);
    };

    const removeItem = (index: number) => {
        onChange(items.filter((_, itemIndex) => itemIndex !== index));
    };

    return (
        <div className={builderPanelClass(isDark)}>
            <div className="flex items-center justify-between gap-3">
                <HelpFieldLabel help="Crie validações automáticas para bloquear, transferir, mascarar ou alertar quando uma condição acontecer. Não é instrução de prompt: o backend precisa executar essa checagem.">
                    Guardrails personalizados
                </HelpFieldLabel>
                <button
                    type="button"
                    onClick={addItem}
                    className={agentiveSecondaryButtonClass(isDark, 'shrink-0 px-2.5 py-1.5 text-xs')}
                >
                    <Plus className="h-3.5 w-3.5" />
                    Guardrail
                </button>
            </div>

            <div className="mt-3 space-y-3">
                {items.length === 0 ? (
                    <div className={builderEmptyClass(isDark, 'py-3 text-xs')}>
                        Nenhum guardrail personalizado.
                    </div>
                ) : (
                    items.map((guardrail, index) => (
                        <div key={guardrail.key || `custom-guardrail-${index}`} className={builderSurfaceClass(isDark, 'p-3')}>
                            {(() => {
                                const checkOptions = guardrail.stage === 'tool'
                                    ? GUARDRAIL_CHECK_OPTIONS.filter((option) => ['regex', 'keyword_filter'].includes(option.value))
                                    : GUARDRAIL_CHECK_OPTIONS;
                                return (
                                    <>
                            <div className="mb-3 flex items-start gap-2">
                                <input
                                    value={guardrail.name}
                                    onChange={(event) => updateItem(index, { name: event.target.value })}
                                    className={`min-w-0 flex-1 rounded-xl border px-2.5 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20 ${
                                        isDark ? 'border-white/10 bg-white/[0.06] text-white placeholder:text-white/35' : 'border-brand/10 bg-white text-brand placeholder:text-brand/35'
                                    }`}
                                    placeholder="Nome do guardrail"
                                />
                                <label className={`inline-flex h-9 shrink-0 items-center gap-1.5 rounded-xl border px-2 text-xs ${isDark ? 'border-white/10 text-white/65' : 'border-brand/10 text-brand/65'}`}>
                                    <input
                                        type="checkbox"
                                        checked={guardrail.enabled !== false}
                                        onChange={(event) => updateItem(index, { enabled: event.target.checked })}
                                        className="h-3.5 w-3.5"
                                    />
                                    Ativo
                                </label>
                                <button
                                    type="button"
                                    onClick={() => removeItem(index)}
                                    className={agentiveIconButtonClass(isDark, 'danger')}
                                    title="Remover guardrail"
                                >
                                    <Trash2 className="h-3.5 w-3.5" />
                                </button>
                            </div>

                            <div className="space-y-2">
                                <div>
                                    <FieldLabel>Quando validar</FieldLabel>
                                    <div className="relative mt-1">
                                        <select
                                            value={guardrail.stage}
                                            onChange={(event) => updateStage(index, guardrail, event.target.value as GuardrailStage)}
                                            className={`w-full appearance-none rounded-xl border px-2.5 py-2 pr-7 text-xs font-semibold outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20 ${
                                                isDark ? 'border-white/10 bg-white/[0.06] text-white' : 'border-brand/10 bg-brand-canvas text-brand'
                                            }`}
                                        >
                                            {GUARDRAIL_STAGE_OPTIONS.map((option) => (
                                                <option key={option.value} value={option.value}>{option.label}</option>
                                            ))}
                                        </select>
                                        <ChevronDown className={builderChevronClass(isDark, 'h-3.5 w-3.5')} />
                                    </div>
                                </div>

                                {guardrail.stage === 'tool' && (
                                    <div>
                                        <FieldLabel>Ferramenta alvo</FieldLabel>
                                        <div className="relative mt-1">
                                            <select
                                                value={guardrail.targetToolId || ''}
                                                onChange={(event) => updateItem(index, { targetToolId: event.target.value })}
                                                className={`w-full appearance-none rounded-xl border px-2.5 py-2 pr-7 text-xs font-semibold outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20 ${
                                                    isDark ? 'border-white/10 bg-white/[0.06] text-white' : 'border-brand/10 bg-brand-canvas text-brand'
                                                }`}
                                            >
                                                <option value="">Selecione uma ferramenta</option>
                                                {availableToolOptions.map((option) => (
                                                    <option key={option.id} value={option.id}>{option.label}</option>
                                                ))}
                                            </select>
                                            <ChevronDown className={builderChevronClass(isDark, 'h-3.5 w-3.5')} />
                                        </div>
                                    </div>
                                )}

                                <div>
                                    <FieldLabel>Como checar</FieldLabel>
                                    <div className="relative mt-1">
                                        <select
                                            value={guardrail.checkType}
                                            onChange={(event) => updateItem(index, { checkType: event.target.value as GuardrailCheckType })}
                                            className={`w-full appearance-none rounded-xl border px-2.5 py-2 pr-7 text-xs font-semibold outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20 ${
                                                isDark ? 'border-white/10 bg-white/[0.06] text-white' : 'border-brand/10 bg-brand-canvas text-brand'
                                            }`}
                                        >
                                            {checkOptions.map((option) => (
                                                <option key={option.value} value={option.value}>{option.label}</option>
                                            ))}
                                        </select>
                                        <ChevronDown className={builderChevronClass(isDark, 'h-3.5 w-3.5')} />
                                    </div>
                                </div>

                                <div>
                                    <FieldLabel>O que fazer</FieldLabel>
                                    <div className="relative mt-1">
                                        <select
                                            value={guardrail.action}
                                            onChange={(event) => updateItem(index, { action: event.target.value as GuardrailAction })}
                                            className={`w-full appearance-none rounded-xl border px-2.5 py-2 pr-7 text-xs font-semibold outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20 ${
                                                isDark ? 'border-white/10 bg-white/[0.06] text-white' : 'border-brand/10 bg-brand-canvas text-brand'
                                            }`}
                                        >
                                            {GUARDRAIL_ACTION_OPTIONS.map((option) => (
                                                <option key={option.value} value={option.value}>{option.label}</option>
                                            ))}
                                        </select>
                                        <ChevronDown className={builderChevronClass(isDark, 'h-3.5 w-3.5')} />
                                    </div>
                                </div>
                            </div>

                            <div className="mt-2">
                                <FieldLabel>Condição</FieldLabel>
                                <textarea
                                    value={guardrail.condition}
                                    onChange={(event) => updateItem(index, { condition: event.target.value })}
                                    className={`mt-1 h-20 w-full resize-none rounded-xl border px-2.5 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20 ${
                                        isDark ? 'border-white/10 bg-white/[0.06] text-white placeholder:text-white/35' : 'border-brand/10 bg-white text-brand placeholder:text-brand/35'
                                    }`}
                                    placeholder="Ex: se o contato pedir algo fora do escopo deste agente"
                                />
                            </div>

                            <div className="mt-2">
                                <FieldLabel>Resposta quando disparar</FieldLabel>
                                <input
                                    value={guardrail.message || ''}
                                    onChange={(event) => updateItem(index, { message: event.target.value })}
                                    className={`mt-1 w-full rounded-xl border px-2.5 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20 ${
                                        isDark ? 'border-white/10 bg-white/[0.06] text-white placeholder:text-white/35' : 'border-brand/10 bg-white text-brand placeholder:text-brand/35'
                                    }`}
                                    placeholder="Ex: Não consigo continuar com segurança por aqui. Vou transferir para um atendente humano."
                                />
                            </div>
                                    </>
                                );
                            })()}
                        </div>
                    ))
                )}
            </div>
        </div>
    );
};

const AgentBuilder: React.FC = () => {
    const { isDark } = useTheme();
    const navigate = useNavigate();
    const { workforceId } = useParams<{ workforceId: string }>();
    const parsedWorkforceId = Number(workforceId);
    const seed = useMemo(() => createDefaultTeam(), []);
    const [nodes, setNodes, onNodesChange] = useNodesState<AgentNodeData>(seed.nodes);
    const [edges, setEdges, onEdgesChange] = useEdgesState<AgentEdgeData>(seed.edges);
    const [workforces, setWorkforces] = useState<AgentWorkforce[]>([]);
    const [humanUsers, setHumanUsers] = useState<User[]>([]);
    const [humanTeams, setHumanTeams] = useState<Team[]>([]);
    const [calendarAgendas, setCalendarAgendas] = useState<Agenda[]>([]);
    const [loadingCalendarAgendas, setLoadingCalendarAgendas] = useState(false);
    const [crmPipelines, setCrmPipelines] = useState<Pipeline[]>([]);
    const [loadingCrmPipelines, setLoadingCrmPipelines] = useState(false);
    const [voiceOptions, setVoiceOptions] = useState<AgentVoiceOption[]>([]);
    const [defaultVoiceId, setDefaultVoiceId] = useState<string>('');
    const [defaultAudioModelId, setDefaultAudioModelId] = useState(DEFAULT_AUDIO_MODEL_ID);
    const [defaultAudioOutputFormat, setDefaultAudioOutputFormat] = useState(DEFAULT_AUDIO_OUTPUT_FORMAT);
    const [loadingVoiceOptions, setLoadingVoiceOptions] = useState(false);
    const [voiceOptionsError, setVoiceOptionsError] = useState('');
    const [modelOptions, setModelOptions] = useState<string[]>([]);
    const [modelCatalogStatus, setModelCatalogStatus] = useState<ModelCatalogStatus>('loading');
    const [modelCatalogMessage, setModelCatalogMessage] = useState('Carregando os modelos disponíveis para esta empresa.');
    const [selectedWorkforce, setSelectedWorkforce] = useState<AgentWorkforce | null>(null);
    const [name, setName] = useState(seed.name);
    const [description, setDescription] = useState(seed.description);
    const [status, setStatus] = useState<AgentStatus>(seed.status);
    const [agentContextSettings, setAgentContextSettings] = useState<WorkforceAgentContextSettings>(() => createDefaultAgentContextSettings());
    const [activeInspectorTab, setActiveInspectorTab] = useState<InspectorTab>('context');
    const [knowledgeUploading, setKnowledgeUploading] = useState(false);
    const [knowledgeRefreshing, setKnowledgeRefreshing] = useState(false);
    const [deletingKnowledgeFileId, setDeletingKnowledgeFileId] = useState<string | null>(null);
    const [knowledgeFileToDelete, setKnowledgeFileToDelete] = useState<string | null>(null);
    const [rootAgentKey, setRootAgentKey] = useState<string | null>(null);
    const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
    const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
    const [deleteSelectionRequest, setDeleteSelectionRequest] = useState<'node' | 'edge' | null>(null);
    const [reactFlowInstance, setReactFlowInstance] = useState<ReactFlowInstance | null>(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [previewing, setPreviewing] = useState(false);
    const [isDirty, setIsDirty] = useState(false);
    const [error, setError] = useState('');
    const [preview, setPreview] = useState('');
    const [showNewAgentModal, setShowNewAgentModal] = useState(false);
    const [configuringToolId, setConfiguringToolId] = useState<string | null>(null);
    const [isLibraryCollapsed, setIsLibraryCollapsed] = useState(false);
    const [isInspectorPanelOpen, setIsInspectorPanelOpen] = useState(true);
    const [isInspectorDrawerOpen, setIsInspectorDrawerOpen] = useState(false);
    const [expandedFewShots, setExpandedFewShots] = useState<Record<string, boolean>>({});
    const [newAgentName, setNewAgentName] = useState('');
    const [newAgentRole, setNewAgentRole] = useState('');
    const [newAgentGoal, setNewAgentGoal] = useState('');
    const [newAgentIconKey, setNewAgentIconKey] = useState('bot');

    const selectedNode = nodes.find((node) => node.id === selectedNodeId) || null;
    const selectedEdge = edges.find((edge) => edge.id === selectedEdgeId) || null;
    const humanNode = nodes.find((node) => node.data.kind === 'human') || null;
    const agentNodes = useMemo(
        () => nodes.filter((node) => node.data.kind !== 'human'),
        [nodes]
    );
    const modelGroups = useMemo(() => groupModelOptions(modelOptions), [modelOptions]);
    const hasReadyModelCatalog = modelCatalogStatus === 'ready' && modelOptions.length > 0;

    const panelClass = isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand';
    const inputClass = isDark
        ? 'border-white/10 bg-white/[0.06] text-white placeholder:text-white/35 focus:border-brand focus:ring-2 focus:ring-brand/20'
        : 'border-brand/10 bg-white text-brand placeholder:text-brand/35 focus:border-brand focus:ring-2 focus:ring-brand/20';

    const openInspectorPanel = () => {
        setIsInspectorPanelOpen(true);
        setIsInspectorDrawerOpen(true);
    };

    const minimizeInspectorPanel = () => {
        setIsInspectorDrawerOpen(false);
        setIsInspectorPanelOpen(false);
    };

    const loadWorkforces = useCallback(async () => {
        try {
            setLoading(true);
            setError('');
            const data = await getAgentWorkforces();
            setWorkforces(data);
            const requestedWorkforce = Number.isFinite(parsedWorkforceId)
                ? data.find((workforce) => workforce.id === parsedWorkforceId)
                : null;

            if (requestedWorkforce) {
                loadWorkforce(requestedWorkforce);
            } else if (Number.isFinite(parsedWorkforceId)) {
                setError('Equipe de agentes não encontrada.');
                applyDraft(createDefaultTeam());
            } else if (data.length > 0) {
                loadWorkforce(data[0]);
            }
        } catch (err) {
            console.error('Failed to load agent workforces', err);
            setError('Não foi possível carregar as equipes de agentes.');
        } finally {
            setLoading(false);
        }
    }, [parsedWorkforceId]);

    const loadHumanTargets = useCallback(async () => {
        try {
            const companyId = Number((localStorage.getItem('company_id') || localStorage.getItem('clinic_id'))) || undefined;
            const [usersData, teamsData] = await Promise.all([
                listUsers(companyId),
                getTeams()
            ]);
            setHumanUsers(usersData.filter((user) => user.is_active !== false));
            setHumanTeams(teamsData);
        } catch (err) {
            console.error('Failed to load human handoff targets', err);
        }
    }, []);

    const loadCalendarAgendas = useCallback(async () => {
        try {
            setLoadingCalendarAgendas(true);
            const agendas = await calendarApi.listAgendas();
            setCalendarAgendas(agendas.filter((agenda) => agenda.active !== false));
        } catch (err) {
            console.error('Failed to load calendar agendas', err);
            setCalendarAgendas([]);
        } finally {
            setLoadingCalendarAgendas(false);
        }
    }, []);

    const loadCrmPipelines = useCallback(async () => {
        try {
            setLoadingCrmPipelines(true);
            const pipelines = await pipelineApi.getPipelines();
            setCrmPipelines(pipelines.filter((pipeline) => pipeline.is_active !== false));
        } catch (err) {
            console.error('Failed to load CRM pipelines', err);
            setCrmPipelines([]);
        } finally {
            setLoadingCrmPipelines(false);
        }
    }, []);

    const loadVoiceOptions = useCallback(async () => {
        try {
            setLoadingVoiceOptions(true);
            setVoiceOptionsError('');
            const result = await listAgentVoiceOptions();
            setVoiceOptions(result.voices || []);
            setDefaultVoiceId(result.default_voice_id || result.voices?.[0]?.voice_id || '');
            setDefaultAudioModelId(result.model_id || DEFAULT_AUDIO_MODEL_ID);
            setDefaultAudioOutputFormat(result.output_format || DEFAULT_AUDIO_OUTPUT_FORMAT);
            if (result.error) {
                setVoiceOptionsError(VOICE_OPTIONS_UNAVAILABLE_MESSAGE);
            }
            return result;
        } catch (err) {
            console.error('Failed to load voice options', err);
            setVoiceOptions([]);
            setVoiceOptionsError(VOICE_OPTIONS_UNAVAILABLE_MESSAGE);
            return null;
        } finally {
            setLoadingVoiceOptions(false);
        }
    }, []);

    useEffect(() => {
        loadWorkforces();
    }, [loadWorkforces]);

    useEffect(() => {
        loadHumanTargets();
    }, [loadHumanTargets]);

    useEffect(() => {
        loadCalendarAgendas();
    }, [loadCalendarAgendas]);

    useEffect(() => {
        loadCrmPipelines();
    }, [loadCrmPipelines]);

    useEffect(() => {
        loadVoiceOptions();
    }, [loadVoiceOptions]);

    useEffect(() => {
        let isMounted = true;
        setModelCatalogStatus('loading');
        setModelCatalogMessage('Carregando os modelos disponíveis para esta empresa.');
        getAIProvider()
            .then((provider) => {
                if (!isMounted) return;
                const providerModels = (provider.models || [])
                    .map((model) => String(model).trim())
                    .filter(Boolean);
                if (providerModels.length > 0) {
                    setModelOptions(Array.from(new Set(providerModels)));
                    setModelCatalogStatus('ready');
                    setModelCatalogMessage('');
                    return;
                }
                setModelOptions([]);
                if (!provider.configured) {
                    setModelCatalogStatus('not_configured');
                    setModelCatalogMessage('Configure e valide a chave OpenAI da empresa para liberar os modelos.');
                    return;
                }
                setModelCatalogStatus('unavailable');
                setModelCatalogMessage(
                    provider.last_error
                    || 'A chave configurada não possui modelos disponíveis. Valide novamente o provedor de IA.'
                );
            })
            .catch((err) => {
                if (!isMounted) return;
                console.warn('Failed to load AI provider model catalog.', err);
                setModelOptions([]);
                setModelCatalogStatus('unavailable');
                setModelCatalogMessage(
                    getApiErrorMessage(err, 'Não foi possível carregar o catálogo de modelos desta empresa.')
                );
            });
        return () => {
            isMounted = false;
        };
    }, []);

    useEffect(() => {
        const fallbackVoice = getPreferredVoiceOption(voiceOptions, defaultVoiceId, defaultVoiceId);
        if (!fallbackVoice) return;
        const hasMissingAudioVoice = nodes.some((node) => (
            node.data.kind !== 'human'
            && node.data.audioEnabled
            && !String(node.data.audioVoiceId || '').trim()
        ));
        if (!hasMissingAudioVoice) return;

        setNodes((currentNodes) => {
            const nextNodes = currentNodes.map((node) => {
                if (
                    node.data.kind === 'human'
                    || !node.data.audioEnabled
                    || String(node.data.audioVoiceId || '').trim()
                ) {
                    return node;
                }

                return {
                    ...node,
                    data: {
                        ...node.data,
                        audioProvider: 'elevenlabs' as const,
                        audioVoiceId: fallbackVoice.voice_id,
                        audioVoiceLabel: getVoiceLabel(fallbackVoice),
                        audioModelId: normalizeAudioModelId(node.data.audioModelId || defaultAudioModelId),
                        audioOutputFormat: node.data.audioOutputFormat || defaultAudioOutputFormat
                    }
                };
            });

            return nextNodes;
        });

        setPreview('');
        setIsDirty(true);
    }, [defaultAudioModelId, defaultAudioOutputFormat, defaultVoiceId, nodes, setNodes, voiceOptions]);

    useEffect(() => {
        setConfiguringToolId(null);
    }, [selectedNodeId]);

    useEffect(() => {
        const availableAgentKeys = agentNodes.map((node) => node.data.key);
        if (availableAgentKeys.length === 0 && rootAgentKey !== null) {
            setRootAgentKey(null);
            return;
        }
        if (availableAgentKeys.length > 0 && (!rootAgentKey || !availableAgentKeys.includes(rootAgentKey))) {
            setRootAgentKey(availableAgentKeys[0]);
        }
    }, [agentNodes, rootAgentKey]);

    const applyDraft = (draft: ReturnType<typeof createDefaultTeam>) => {
        const firstAgent = draft.nodes.find((node) => node.data.kind !== 'human');
        setSelectedWorkforce(null);
        setName(draft.name);
        setDescription(draft.description);
        setStatus(draft.status);
        setAgentContextSettings(createDefaultAgentContextSettings());
        setRootAgentKey(firstAgent?.data.key || null);
        setNodes(draft.nodes);
        setEdges(draft.edges);
        setSelectedNodeId(null);
        setSelectedEdgeId(null);
        setActiveInspectorTab('context');
        setConfiguringToolId(null);
        setPreview('');
        setIsDirty(true);
        window.setTimeout(() => reactFlowInstance?.fitView({ padding: 0.2 }), 50);
    };

    const loadWorkforce = (workforce: AgentWorkforce) => {
        const fallback = createDefaultTeam();
        const loadedEdges = (workforce.edges || []) as AgentEdge[];
        const loadedNodes = syncHumanHandoffToolWithHumanEdges(((workforce.nodes?.length ? workforce.nodes : fallback.nodes) as AgentNode[])
            .map((node) => ({
                ...node,
                data: {
                    ...node.data,
                    ...getAudioVoiceFromConfig(workforce.agent_configs?.[node.data.key])
                }
            }))
            .map(normalizeAgentNode), loadedEdges);
        const firstAgent = loadedNodes.find((node) => node.data.kind !== 'human');
        const loadedRoot = loadedNodes.find(
            (node) => node.data.kind !== 'human' && node.data.key === workforce.root_agent_key
        );
        setSelectedWorkforce(workforce);
        setName(workforce.name);
        setDescription(workforce.description || '');
        setStatus((workforce.status as AgentStatus) || 'draft');
        setAgentContextSettings(normalizeAgentContextSettings(workforce.settings));
        setRootAgentKey(loadedRoot?.data.key || firstAgent?.data.key || null);
        setNodes(loadedNodes);
        setEdges(loadedEdges);
        setSelectedNodeId(null);
        setSelectedEdgeId(null);
        setActiveInspectorTab('context');
        setConfiguringToolId(null);
        setPreview('');
        setIsDirty(false);
        window.setTimeout(() => reactFlowInstance?.fitView({ padding: 0.2 }), 50);
    };

    const handleNodesChange = useCallback((changes: any[]) => {
        onNodesChange(changes);
        if (changes.some((change) => change.type !== 'select')) {
            setIsDirty(true);
        }
    }, [onNodesChange]);

    const handleEdgesChange = useCallback((changes: any[]) => {
        onEdgesChange(changes);
        if (changes.some((change) => change.type !== 'select')) {
            setIsDirty(true);
        }
    }, [onEdgesChange]);

    const onConnect = useCallback((connection: Connection) => {
        const sourceNode = nodes.find((node) => node.id === connection.source);
        const targetNode = nodes.find((node) => node.id === connection.target);
        if (!sourceNode || !targetNode) return;
        if (sourceNode.data.kind === 'human') {
            setError('Conexões devem partir de um agente IA.');
            return;
        }

        if (targetNode.data.kind === 'human') {
            setNodes((currentNodes) =>
                currentNodes.map((node) => {
                    if (node.id !== sourceNode.id) return node;
                    const tools = sanitizeToolIds(node.data.tools);
                    if (tools.includes(HUMAN_HANDOFF_TOOL_ID)) return node;
                    const nextTools = [...tools, HUMAN_HANDOFF_TOOL_ID];
                    return {
                        ...node,
                        data: {
                            ...node.data,
                            tools: nextTools,
                            toolSettings: sanitizeToolSettings(node.data.toolSettings, nextTools)
                        }
                    };
                })
            );
        }

        setEdges((currentEdges) => addEdge({
            ...connection,
            type: 'smoothstep',
            markerEnd: { type: MarkerType.ArrowClosed },
            label: 'Transferir quando fizer sentido',
            data: {
                mode: 'handoff',
                rule: 'Transferir quando o agente de destino tiver melhor contexto.'
            }
        }, currentEdges));
        setError('');
        setIsDirty(true);
    }, [nodes, setEdges, setNodes]);

    const updateNodeData = (field: keyof AgentNodeData, value: any) => {
        if (!selectedNode) return;
        setNodes((currentNodes) =>
            currentNodes.map((node) =>
                node.id === selectedNode.id
                    ? { ...node, data: { ...node.data, [field]: value } }
                    : node
            )
        );
        setPreview('');
        setIsDirty(true);
    };

    const updateNodeDataPatch = (patch: Partial<AgentNodeData>) => {
        if (!selectedNode) return;
        setNodes((currentNodes) =>
            currentNodes.map((node) =>
                node.id === selectedNode.id
                    ? { ...node, data: { ...node.data, ...patch } }
                    : node
            )
        );
        setPreview('');
        setIsDirty(true);
    };

    const handleAudioVoiceChange = (voiceId: string) => {
        const selectedVoice = voiceOptions.find((voice) => voice.voice_id === voiceId);
        updateNodeDataPatch({
            audioProvider: 'elevenlabs',
            audioVoiceId: voiceId,
            audioVoiceLabel: selectedVoice ? getVoiceLabel(selectedVoice) : voiceId
        });
    };

    const updateAgentContextSettings = (updater: (current: WorkforceAgentContextSettings) => WorkforceAgentContextSettings) => {
        setAgentContextSettings((current) => updater(current));
        setIsDirty(true);
    };

    const updateGlobalContextField = (
        field: keyof WorkforceGlobalContextSettings,
        value: string | boolean
    ) => {
        updateAgentContextSettings((current) => ({
            ...current,
            global_context: {
                ...current.global_context,
                [field]: value
            }
        }));
    };

    const updatePerformanceField = (
        field: keyof WorkforceAgentContextSettings['performance'],
        value: any
    ) => {
        updateAgentContextSettings((current) => ({
            ...current,
            performance: {
                ...current.performance,
                [field]: value
            }
        }));
    };

    const updateScheduleSettings = (updater: (current: WorkforceScheduleSettings) => WorkforceScheduleSettings) => {
        updateAgentContextSettings((current) => ({
            ...current,
            schedule: updater(current.schedule)
        }));
    };

    const updateScheduleMode = (mode: WorkforceScheduleMode) => {
        updateScheduleSettings((current) => ({
            ...current,
            mode
        }));
    };

    const updateScheduleTimezone = (timezone: string) => {
        updateScheduleSettings((current) => ({
            ...current,
            timezone
        }));
    };

    const updateScheduleDayEnabled = (day: WorkforceScheduleDayKey, enabled: boolean) => {
        updateScheduleSettings((current) => ({
            ...current,
            days: {
                ...current.days,
                [day]: {
                    ...current.days[day],
                    enabled
                }
            }
        }));
    };

    const updateSchedulePeriod = (
        day: WorkforceScheduleDayKey,
        period: WorkforceSchedulePeriodKey,
        patch: Partial<WorkforceSchedulePeriodSettings>
    ) => {
        updateScheduleSettings((current) => ({
            ...current,
            days: {
                ...current.days,
                [day]: {
                    ...current.days[day],
                    periods: {
                        ...current.days[day].periods,
                        [period]: {
                            ...current.days[day].periods[period],
                            ...patch
                        }
                    }
                }
            }
        }));
    };

    const updateGlobalFewShots = (examples: GlobalFewShotExampleData[]) => {
        updateAgentContextSettings((current) => ({
            ...current,
            global_few_shots: {
                ...current.global_few_shots,
                examples
            }
        }));
    };

    const addGlobalFewShot = () => {
        updateGlobalFewShots([
            ...agentContextSettings.global_few_shots.examples,
            { title: '', tags: '', context: '', user: '', assistant: '', enabled: true }
        ]);
    };

    const updateGlobalFewShot = (
        index: number,
        field: keyof GlobalFewShotExampleData,
        value: string | boolean
    ) => {
        updateGlobalFewShots(
            agentContextSettings.global_few_shots.examples.map((example, itemIndex) =>
                itemIndex === index ? { ...example, [field]: value } : example
            )
        );
    };

    const removeGlobalFewShot = (index: number) => {
        updateGlobalFewShots(
            agentContextSettings.global_few_shots.examples.filter((_, itemIndex) => itemIndex !== index)
        );
    };

    const applyUpdatedWorkforce = (updated: AgentWorkforce) => {
        setSelectedWorkforce(updated);
        setWorkforces((current) => current.map((item) => item.id === updated.id ? updated : item));
        setAgentContextSettings(normalizeAgentContextSettings(updated.settings));
    };

    const handleKnowledgeRefresh = async () => {
        if (!selectedWorkforce) return;
        const fileSearch = agentContextSettings.knowledge.file_search;
        if (fileSearch.files.length === 0 && fileSearch.links.length === 0) return;

        try {
            setKnowledgeRefreshing(true);
            const updated = await refreshAgentWorkforceKnowledge(selectedWorkforce.id);
            applyUpdatedWorkforce(updated);
        } catch (err) {
            console.error('Failed to refresh knowledge status', err);
            setError('Não foi possível atualizar o status dos documentos.');
        } finally {
            setKnowledgeRefreshing(false);
        }
    };

    const handleKnowledgeFileUpload = async (file?: File | null) => {
        if (!file) return;
        if (!selectedWorkforce) {
            setError('Salve a equipe antes de anexar documentos ao RAG.');
            return;
        }
        try {
            setKnowledgeUploading(true);
            setError('');
            const updated = await uploadAgentWorkforceKnowledgeFile(selectedWorkforce.id, file);
            applyUpdatedWorkforce(updated);
            setIsDirty(false);
        } catch (err) {
            console.error('Failed to upload knowledge file', err);
            setError('Não foi possível anexar o documento ao conhecimento da equipe.');
        } finally {
            setKnowledgeUploading(false);
        }
    };

    const handleKnowledgeFileDelete = async (fileId?: string) => {
        if (!selectedWorkforce || !fileId) return;
        setKnowledgeFileToDelete(fileId);
    };

    const confirmKnowledgeFileDelete = async () => {
        if (!selectedWorkforce || !knowledgeFileToDelete) return;

        try {
            setDeletingKnowledgeFileId(knowledgeFileToDelete);
            setError('');
            const updated = await deleteAgentWorkforceKnowledgeFile(selectedWorkforce.id, knowledgeFileToDelete);
            applyUpdatedWorkforce(updated);
            setIsDirty(false);
            setKnowledgeFileToDelete(null);
        } catch (err) {
            console.error('Failed to delete knowledge file', err);
            setError('Não foi possível excluir o documento da base RAG.');
        } finally {
            setDeletingKnowledgeFileId(null);
        }
    };

    useEffect(() => {
        if (activeInspectorTab !== 'knowledge' || !selectedWorkforce) return;
        const fileSearch = agentContextSettings.knowledge.file_search;
        if (fileSearch.files.length === 0 && fileSearch.links.length === 0) return;
        handleKnowledgeRefresh();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeInspectorTab, selectedWorkforce?.id]);

    const updateNodeName = (value: string) => {
        if (!selectedNode) return;
        const nextKey = makeUniqueAgentKey(value, nodes as AgentNode[], selectedNode.id);
        setNodes((currentNodes) =>
            currentNodes.map((node) =>
                node.id === selectedNode.id
                    ? {
                        ...node,
                        data: {
                            ...node.data,
                            name: value,
                            key: nextKey
                        }
                    }
                    : node
            )
        );
        if (selectedNode.data.key === rootAgentKey) {
            setRootAgentKey(nextKey);
        }
        setPreview('');
        setIsDirty(true);
    };

    const handleModelChange = (model: string) => {
        if (!selectedNode) return;
        const reasoningEffort = getNormalizedReasoningEffort(model, selectedNode.data.reasoningEffort);

        setNodes((currentNodes) =>
            currentNodes.map((node) =>
                node.id === selectedNode.id
                    ? { ...node, data: { ...node.data, model, reasoningEffort } }
                    : node
            )
        );
        setPreview('');
        setIsDirty(true);
    };

    const updateHumanQueueData = (patch: Partial<HumanQueueConfig>) => {
        if (!selectedNode || selectedNode.data.kind !== 'human') return;
        const currentConfig = normalizeHumanQueueConfig(selectedNode.data.humanQueue);
        updateNodeData('humanQueue', normalizeHumanQueueConfig({ ...currentConfig, ...patch }));
    };

    const updateFewShot = (index: number, field: keyof FewShotExampleData, value: string) => {
        if (!selectedNode) return;
        const nextFewShots = [...(selectedNode.data.fewShots || [])];
        nextFewShots[index] = {
            user: '',
            assistant: '',
            ...nextFewShots[index],
            [field]: value
        };
        updateNodeData('fewShots', nextFewShots);
    };

    const getFewShotKey = (index: number) => `${selectedNode?.id || 'agent'}-${index}`;

    const toggleFewShot = (index: number) => {
        const key = getFewShotKey(index);
        setExpandedFewShots((current) => ({ ...current, [key]: !current[key] }));
    };

    const addFewShot = () => {
        if (!selectedNode) return;
        const nextIndex = selectedNode.data.fewShots?.length || 0;
        updateNodeData('fewShots', [
            ...(selectedNode.data.fewShots || []),
            { user: '', assistant: '', context: '' }
        ]);
        setExpandedFewShots((current) => ({ ...current, [getFewShotKey(nextIndex)]: true }));
    };

    const removeFewShot = (index: number) => {
        if (!selectedNode) return;
        updateNodeData('fewShots', (selectedNode.data.fewShots || []).filter((_, itemIndex) => itemIndex !== index));
    };

    const updateEdgeData = (field: keyof AgentEdgeData, value: any) => {
        if (!selectedEdge) return;
        setEdges((currentEdges) =>
            currentEdges.map((edge) =>
                edge.id === selectedEdge.id
                    ? {
                        ...edge,
                        label: field === 'rule' ? value : edge.label,
                        data: { mode: 'handoff', rule: '', ...edge.data, [field]: value }
                    }
                    : edge
            )
        );
        setIsDirty(true);
    };

    const toggleToolValue = (value: string) => {
        if (!selectedNode) return;
        const selectedNodeIdForUpdate = selectedNode.id;
        const humanNodeIds = new Set(
            nodes
                .filter((node) => node.data.kind === 'human')
                .map((node) => node.id)
        );
        const isRemovingHumanHandoff = (
            value === HUMAN_HANDOFF_TOOL_ID
            && sanitizeToolIds(selectedNode.data.tools).includes(HUMAN_HANDOFF_TOOL_ID)
        );

        setNodes((currentNodes) =>
            currentNodes.map((node) => {
                if (node.id !== selectedNodeIdForUpdate) return node;
                const currentValues = sanitizeToolIds(node.data.tools);
                const isRemoving = currentValues.includes(value);
                const nextValues = currentValues.includes(value)
                    ? currentValues.filter((item) => item !== value)
                    : [...currentValues, value];
                const nextToolSettings = !isRemoving && value === CALENDAR_TOOL_ID
                    ? {
                        ...(node.data.toolSettings || {}),
                        [CALENDAR_TOOL_ID]: sanitizeCalendarToolSettings(node.data.toolSettings?.[CALENDAR_TOOL_ID])
                    }
                        : !isRemoving && value === CRM_PIPELINE_TOOL_ID
                            ? {
                                ...(node.data.toolSettings || {}),
                                [CRM_PIPELINE_TOOL_ID]: sanitizeCrmPipelineToolSettings(node.data.toolSettings?.[CRM_PIPELINE_TOOL_ID])
                            }
                            : !isRemoving && value === DYNAMIC_CRM_FOLLOWUP_TOOL_ID
                                ? {
                                    ...(node.data.toolSettings || {}),
                                    [DYNAMIC_CRM_FOLLOWUP_TOOL_ID]: sanitizeDynamicCrmFollowupToolSettings(node.data.toolSettings?.[DYNAMIC_CRM_FOLLOWUP_TOOL_ID])
                                }
                                : !isRemoving && value === WHATSAPP_CONTACT_CARD_TOOL_ID
                                    ? {
                                        ...(node.data.toolSettings || {}),
                                        [WHATSAPP_CONTACT_CARD_TOOL_ID]: sanitizeWhatsAppContactCardToolSettings(node.data.toolSettings?.[WHATSAPP_CONTACT_CARD_TOOL_ID])
                                    }
                                    : !isRemoving && value === WHATSAPP_SCHEDULED_FOLLOWUP_TOOL_ID
                                        ? {
                                            ...(node.data.toolSettings || {}),
                                            [WHATSAPP_SCHEDULED_FOLLOWUP_TOOL_ID]: sanitizeWhatsAppScheduledFollowupToolSettings(node.data.toolSettings?.[WHATSAPP_SCHEDULED_FOLLOWUP_TOOL_ID])
                                        }
                                        : node.data.toolSettings;

                return {
                    ...node,
                    data: {
                        ...node.data,
                        tools: nextValues,
                        toolSettings: sanitizeToolSettings(nextToolSettings, nextValues)
                    }
                };
            })
        );
        if (isRemovingHumanHandoff) {
            setEdges((currentEdges) =>
                currentEdges.filter((edge) => !(
                    edge.source === selectedNodeIdForUpdate
                    && edge.target
                    && humanNodeIds.has(edge.target)
                ))
            );
        }
        if (configuringToolId === value) {
            setConfiguringToolId(null);
        }
        setPreview('');
        setIsDirty(true);
    };

    const updateCalendarToolSettings = (patch: Partial<CalendarSchedulingToolSettings>) => {
        if (!selectedNode) return;
        const currentSettings = sanitizeToolSettings(selectedNode.data.toolSettings, selectedNode.data.tools);
        const calendarSettings = sanitizeCalendarToolSettings(currentSettings[CALENDAR_TOOL_ID]);
        updateNodeData('toolSettings', {
            ...currentSettings,
            [CALENDAR_TOOL_ID]: sanitizeCalendarToolSettings({
                ...calendarSettings,
                ...patch
            })
        });
    };

    const toggleCalendarToolAction = (action: CalendarToolAction, checked: boolean) => {
        const settings = sanitizeCalendarToolSettings(selectedNode?.data.toolSettings?.[CALENDAR_TOOL_ID]);
        const nextActions = checked
            ? Array.from(new Set([...settings.allowedActions, action]))
            : settings.allowedActions.filter((item) => item !== action);

        if (nextActions.length === 0) return;
        updateCalendarToolSettings({ allowedActions: nextActions });
    };

    const updateCrmPipelineToolSettings = (patch: Partial<CrmPipelineToolSettings>) => {
        if (!selectedNode) return;
        const currentSettings = sanitizeToolSettings(selectedNode.data.toolSettings, selectedNode.data.tools);
        const crmSettings = sanitizeCrmPipelineToolSettings(currentSettings[CRM_PIPELINE_TOOL_ID]);
        updateNodeData('toolSettings', {
            ...currentSettings,
            [CRM_PIPELINE_TOOL_ID]: sanitizeCrmPipelineToolSettings({
                ...crmSettings,
                ...patch
            })
        });
    };

    const updateDynamicCrmFollowupToolSettings = (patch: Partial<DynamicCrmFollowupToolSettings>) => {
        if (!selectedNode) return;
        const currentSettings = sanitizeToolSettings(selectedNode.data.toolSettings, selectedNode.data.tools);
        const dynamicSettings = sanitizeDynamicCrmFollowupToolSettings(currentSettings[DYNAMIC_CRM_FOLLOWUP_TOOL_ID]);
        updateNodeData('toolSettings', {
            ...currentSettings,
            [DYNAMIC_CRM_FOLLOWUP_TOOL_ID]: sanitizeDynamicCrmFollowupToolSettings({
                ...dynamicSettings,
                ...patch
            })
        });
    };

    const updateWhatsAppContactCardToolSettings = (patch: Partial<WhatsAppContactCardToolSettings>) => {
        if (!selectedNode) return;
        const currentSettings = sanitizeToolSettings(selectedNode.data.toolSettings, selectedNode.data.tools);
        const contactSettings = sanitizeWhatsAppContactCardToolSettings(currentSettings[WHATSAPP_CONTACT_CARD_TOOL_ID]);
        updateNodeData('toolSettings', {
            ...currentSettings,
            [WHATSAPP_CONTACT_CARD_TOOL_ID]: sanitizeWhatsAppContactCardToolSettings({
                ...contactSettings,
                ...patch
            })
        });
    };

    const updateWhatsAppScheduledFollowupToolSettings = (patch: Partial<WhatsAppScheduledFollowupToolSettings>) => {
        if (!selectedNode) return;
        const currentSettings = sanitizeToolSettings(selectedNode.data.toolSettings, selectedNode.data.tools);
        const followupSettings = sanitizeWhatsAppScheduledFollowupToolSettings(currentSettings[WHATSAPP_SCHEDULED_FOLLOWUP_TOOL_ID]);
        updateNodeData('toolSettings', {
            ...currentSettings,
            [WHATSAPP_SCHEDULED_FOLLOWUP_TOOL_ID]: sanitizeWhatsAppScheduledFollowupToolSettings({
                ...followupSettings,
                ...patch
            })
        });
    };

    const updateDynamicFollowupStep = (
        index: number,
        field: keyof DynamicCrmFollowupStep,
        value: string | number
    ) => {
        if (!selectedNode) return;
        const settings = sanitizeDynamicCrmFollowupToolSettings(selectedNode.data.toolSettings?.[DYNAMIC_CRM_FOLLOWUP_TOOL_ID]);
        const nextSteps = settings.steps.map((step, stepIndex) => {
            if (stepIndex !== index) return step;
            if (field === 'sendAfter') {
                return { ...step, sendAfter: sanitizeDynamicFollowupDelay(value) };
            }
            if (field === 'sendAfterUnit') {
                return { ...step, sendAfterUnit: normalizeDynamicFollowupUnit(value) };
            }
            if (field === 'channel') {
                return { ...step, channel: 'whatsapp' as const };
            }
            return { ...step, [field]: String(value) };
        });
        updateDynamicCrmFollowupToolSettings({ steps: nextSteps });
    };

    const addDynamicFollowupStep = () => {
        if (!selectedNode) return;
        const settings = sanitizeDynamicCrmFollowupToolSettings(selectedNode.data.toolSettings?.[DYNAMIC_CRM_FOLLOWUP_TOOL_ID]);
        updateDynamicCrmFollowupToolSettings({
            steps: [...settings.steps, createDefaultDynamicCrmFollowupStep(settings.steps.length)]
        });
    };

    const removeDynamicFollowupStep = (index: number) => {
        if (!selectedNode) return;
        const settings = sanitizeDynamicCrmFollowupToolSettings(selectedNode.data.toolSettings?.[DYNAMIC_CRM_FOLLOWUP_TOOL_ID]);
        const nextSteps = settings.steps
            .filter((_, stepIndex) => stepIndex !== index)
            .map((step, stepIndex) => ({ ...step, stepNumber: stepIndex + 1 }));
        updateDynamicCrmFollowupToolSettings({
            steps: nextSteps.length ? nextSteps : [createDefaultDynamicCrmFollowupStep()]
        });
    };

    const toggleDynamicFollowupTargetStage = (stageId: number, checked: boolean) => {
        if (!selectedNode) return;
        const settings = sanitizeDynamicCrmFollowupToolSettings(selectedNode.data.toolSettings?.[DYNAMIC_CRM_FOLLOWUP_TOOL_ID]);
        const nextStageIds = checked
            ? Array.from(new Set([...settings.targetStageIds, stageId]))
            : settings.targetStageIds.filter((id) => Number(id) !== Number(stageId));
        updateDynamicCrmFollowupToolSettings({
            pipelineId: settings.pipelineId ?? selectedDynamicFollowupPipeline?.id ?? null,
            targetStageIds: nextStageIds
        });
    };

    const updateDynamicFollowupDeliveryWindow = (patch: Partial<DynamicCrmFollowupDeliveryWindow>) => {
        if (!selectedNode) return;
        const settings = sanitizeDynamicCrmFollowupToolSettings(selectedNode.data.toolSettings?.[DYNAMIC_CRM_FOLLOWUP_TOOL_ID]);
        updateDynamicCrmFollowupToolSettings({
            deliveryWindow: sanitizeDynamicFollowupDeliveryWindow({
                ...settings.deliveryWindow,
                ...patch
            }, settings.timezone)
        });
    };

    const toggleDynamicFollowupDeliveryWeekday = (weekday: number, checked: boolean) => {
        if (!selectedNode) return;
        const settings = sanitizeDynamicCrmFollowupToolSettings(selectedNode.data.toolSettings?.[DYNAMIC_CRM_FOLLOWUP_TOOL_ID]);
        const currentWeekdays = settings.deliveryWindow.allowedWeekdays;
        const nextWeekdays = checked
            ? Array.from(new Set([...currentWeekdays, weekday])).sort((a, b) => a - b)
            : currentWeekdays.filter((item) => item !== weekday);
        if (!nextWeekdays.length) return;
        updateDynamicFollowupDeliveryWindow({ allowedWeekdays: nextWeekdays });
    };

    const updateWhatsAppContactCard = (
        index: number,
        field: keyof WhatsAppContactCardConfig,
        value: string
    ) => {
        if (!selectedNode) return;
        const settings = sanitizeWhatsAppContactCardToolSettings(selectedNode.data.toolSettings?.[WHATSAPP_CONTACT_CARD_TOOL_ID]);
        const nextCards = settings.contactCards.map((card, cardIndex) => (
            cardIndex === index
                ? {
                    ...card,
                    [field]: field === 'key'
                        ? sanitizeContactCardKey(value, `contato_${index + 1}`)
                        : value
                }
                : card
        ));
        updateWhatsAppContactCardToolSettings({ contactCards: nextCards });
    };

    const addWhatsAppContactCard = () => {
        if (!selectedNode) return;
        const settings = sanitizeWhatsAppContactCardToolSettings(selectedNode.data.toolSettings?.[WHATSAPP_CONTACT_CARD_TOOL_ID]);
        updateWhatsAppContactCardToolSettings({
            contactCards: [...settings.contactCards, createDefaultContactCard(settings.contactCards.length)]
        });
    };

    const removeWhatsAppContactCard = (index: number) => {
        if (!selectedNode) return;
        const settings = sanitizeWhatsAppContactCardToolSettings(selectedNode.data.toolSettings?.[WHATSAPP_CONTACT_CARD_TOOL_ID]);
        const nextCards = settings.contactCards.filter((_, cardIndex) => cardIndex !== index);
        updateWhatsAppContactCardToolSettings({
            contactCards: nextCards.length ? nextCards : [createDefaultContactCard()]
        });
    };

    const updateCrmStageRule = (
        stage: PipelineStage,
        field: 'advanceRule' | 'recedeRule',
        value: string
    ) => {
        if (!selectedNode) return;
        const settings = sanitizeCrmPipelineToolSettings(selectedNode.data.toolSettings?.[CRM_PIPELINE_TOOL_ID]);
        const nextRules = getCrmStageRulesForPipeline(settings, selectedCrmStages)
            .map((rule) => Number(rule.stageId) === Number(stage.id)
                ? { ...rule, stageName: stage.name, [field]: value }
                : rule
            );
        updateCrmPipelineToolSettings({ stageRules: nextRules });
    };

    const openNewAgentModal = () => {
        if (!hasReadyModelCatalog) {
            setError(modelCatalogMessage || 'Carregue um catálogo válido antes de criar um agente.');
            return;
        }
        setNewAgentName('');
        setNewAgentRole('');
        setNewAgentGoal('');
        setNewAgentIconKey('bot');
        setShowNewAgentModal(true);
    };

    const focusNode = (node: AgentNode) => {
        setSelectedNodeId(node.id);
        setSelectedEdgeId(null);
        if (typeof window !== 'undefined' && window.innerWidth < 1536) {
            setIsInspectorDrawerOpen(true);
        }
        reactFlowInstance?.setCenter(node.position.x + 130, node.position.y + 80, {
            zoom: Math.max(reactFlowInstance.getZoom(), 0.8),
            duration: 300
        });
    };

    const handleHumanShortcut = () => {
        if (humanNode) {
            focusNode(humanNode as AgentNode);
            return;
        }

        const nextIndex = nodes.length;
        const node = createAgentNode('human', nextIndex, {
            x: 80 + (nextIndex % 3) * 280,
            y: 80 + Math.floor(nextIndex / 3) * 190
        }, {
            name: 'Fila Humana',
            key: 'fila_humana',
            role: 'Fallback humano',
            iconKey: 'users',
            goal: 'Receber conversas que precisam de decisão humana, negociação sensível ou exceção operacional.',
            humanQueue: createDefaultHumanQueueConfig()
        });

        setNodes((currentNodes) => [...currentNodes, node]);
        focusNode(node);
        setError('');
        setIsDirty(true);
    };

    const handleCreateCustomAgent = () => {
        if (!hasReadyModelCatalog) {
            setError(modelCatalogMessage || 'Carregue um catálogo válido antes de criar um agente.');
            return;
        }
        const trimmedName = newAgentName.trim();
        if (!trimmedName) {
            setError('Informe um nome para o novo agente.');
            return;
        }

        const nextIndex = nodes.length;
        const node = createAgentNode('custom', nextIndex, {
            x: 80 + (nextIndex % 3) * 280,
            y: 80 + Math.floor(nextIndex / 3) * 190
        }, {
            name: trimmedName,
            key: makeAgentKey(trimmedName, String(nextIndex + 1)),
            role: newAgentRole.trim(),
            goal: newAgentGoal.trim(),
            iconKey: newAgentIconKey,
            model: modelOptions[0],
            framework: 'agent_standard',
            qualification: 'none',
            customGuardrails: [],
            instructions: [],
            constraints: [],
            conversationRules: [],
            failureConditions: [],
            fewShots: []
        });
        setNodes((currentNodes) => [...currentNodes, node]);
        if (!nodes.some((item) => item.data.kind !== 'human')) {
            setRootAgentKey(node.data.key);
        }
        setSelectedNodeId(node.id);
        setSelectedEdgeId(null);
        setShowNewAgentModal(false);
        setError('');
        setIsDirty(true);
    };

    const handleDeleteSelected = () => {
        if (selectedNode) {
            setDeleteSelectionRequest('node');
            return;
        }

        if (selectedEdge) {
            setDeleteSelectionRequest('edge');
        }
    };

    const confirmDeleteSelected = () => {
        if (selectedNode) {
            if (selectedNode.data.key === rootAgentKey) {
                const nextRoot = nodes.find(
                    (node) => node.id !== selectedNode.id && node.data.kind !== 'human'
                );
                setRootAgentKey(nextRoot?.data.key || null);
            }
            setNodes((currentNodes) => currentNodes.filter((node) => node.id !== selectedNode.id));
            setEdges((currentEdges) => currentEdges.filter((edge) => edge.source !== selectedNode.id && edge.target !== selectedNode.id));
            setSelectedNodeId(null);
            setConfiguringToolId(null);
            setIsDirty(true);
            setDeleteSelectionRequest(null);
            return;
        }

        if (selectedEdge) {
            setEdges((currentEdges) => currentEdges.filter((edge) => edge.id !== selectedEdge.id));
            setSelectedEdgeId(null);
            setConfiguringToolId(null);
            setIsDirty(true);
            setDeleteSelectionRequest(null);
        }
        setDeleteSelectionRequest(null);
    };

    const clearInspectorSelection = () => {
        setSelectedNodeId(null);
        setSelectedEdgeId(null);
        setConfiguringToolId(null);
        setNodes((currentNodes) => currentNodes.map((node) => ({ ...node, selected: false })));
        setEdges((currentEdges) => currentEdges.map((edge) => ({ ...edge, selected: false })));
    };

    const buildPayload = () => {
        const flowObject = reactFlowInstance?.toObject() || {
            nodes,
            edges,
            viewport: { x: 0, y: 0, zoom: 1 }
        };
        const cleanEdges = (flowObject.edges || edges) as AgentEdge[];
        const cleanNodes = syncHumanHandoffToolWithHumanEdges(
            (flowObject.nodes as AgentNode[]).map(sanitizeAgentNode),
            cleanEdges
        );
        const root = cleanNodes.find((node) => node.data.kind !== 'human' && node.data.key === rootAgentKey)
            || cleanNodes.find((node) => node.data.kind !== 'human');

        return {
            name: name.trim(),
            description: description.trim(),
            status,
            channel: 'whatsapp',
            root_agent_key: root?.data.key || null,
            nodes: cleanNodes,
            edges: cleanEdges,
            viewport: flowObject.viewport || { x: 0, y: 0, zoom: 1 },
            agent_configs: buildAgentConfigs(cleanNodes, cleanEdges),
            settings: buildWorkforceSettings(cleanNodes, agentContextSettings)
        };
    };

    const handleSave = async () => {
        if (!name.trim()) {
            setError('Informe um nome para a equipe.');
            return;
        }

        try {
            setSaving(true);
            setError('');
            const payload = buildPayload();
            const agentCount = (payload.nodes || []).filter((node: any) => node?.data?.kind !== 'human').length;
            if (agentCount === 0) {
                setError('Adicione pelo menos um agente IA antes de salvar a equipe.');
                return;
            }
            if (!hasReadyModelCatalog) {
                setError(modelCatalogMessage || 'Não foi possível confirmar os modelos disponíveis para esta empresa.');
                return;
            }
            const invalidModelAgent = (payload.nodes || []).find((node: any) => (
                node?.data?.kind !== 'human'
                && !modelOptions.includes(String(node?.data?.model || '').trim())
            ));
            if (invalidModelAgent) {
                setError(
                    `O modelo de "${invalidModelAgent.data?.name || 'agente'}" não está disponível para a chave desta empresa. Selecione outro modelo antes de salvar.`
                );
                return;
            }
            const invalidAgent = (payload.nodes || []).find((node: any) => {
                if (node?.data?.kind === 'human') return false;
                return (
                    String(node?.data?.name || '').trim().length < 2
                    || String(node?.data?.role || '').trim().length < 3
                    || String(node?.data?.goal || '').trim().length < 5
                );
            });
            if (invalidAgent) {
                setError(`Revise "${invalidAgent.data?.name || 'agente'}": nome, responsabilidade e objetivo precisam estar preenchidos.`);
                return;
            }
            const invalidAudioAgent = (payload.nodes || []).find((node: any) => {
                if (node?.data?.kind === 'human') return false;
                return Boolean(node?.data?.audioEnabled) && !String(node?.data?.audioVoiceId || '').trim();
            });
            if (invalidAudioAgent) {
                setError(`Revise "${invalidAudioAgent.data?.name || 'agente'}": selecione uma voz para ativar áudio.`);
                return;
            }
            if (!payload.root_agent_key || !payload.agent_configs?.[payload.root_agent_key]) {
                setError('Selecione um agente inicial válido para esta equipe.');
                return;
            }
            const saved = selectedWorkforce
                ? await updateAgentWorkforce(selectedWorkforce.id, payload)
                : await createAgentWorkforce(payload);

            setSelectedWorkforce(saved);
            setAgentContextSettings(normalizeAgentContextSettings(saved.settings));
            setRootAgentKey(saved.root_agent_key || payload.root_agent_key || null);
            setWorkforces((current) => {
                const exists = current.some((item) => item.id === saved.id);
                return exists
                    ? current.map((item) => item.id === saved.id ? saved : item)
                    : [saved, ...current];
            });
            setIsDirty(false);
        } catch (err) {
            console.error('Failed to save agent workforce', err);
            setError(getApiErrorMessage(err, 'Não foi possível salvar a equipe de agentes.'));
        } finally {
            setSaving(false);
        }
    };

    const handlePreview = async () => {
        if (!selectedNode) return;

        try {
            setPreviewing(true);
            setError('');
            const payload = buildAgentConfig(selectedNode as AgentNode, nodes as AgentNode[], edges as AgentEdge[]);
            const result = await previewAgentConfig(payload);
            setPreview(result.instructions);
        } catch (err) {
            console.error('Failed to preview agent config', err);
            setError('Não foi possível gerar a prévia do agente selecionado.');
        } finally {
            setPreviewing(false);
        }
    };

    const inspectorTabs: Array<{ id: InspectorTab; label: string; icon: React.ElementType }> = [
        { id: 'context', label: 'Contexto', icon: Building2 },
        { id: 'knowledge', label: 'Conhecimento', icon: FileText },
        { id: 'examples', label: 'Exemplos', icon: MessageCircle },
        { id: 'schedule', label: 'Horários', icon: CalendarClock },
        { id: 'performance', label: 'Custo', icon: DollarSign }
    ];

    const renderGlobalContextPanel = () => (
        <div className="space-y-3">
            <div className={flowNodePanelClass(isDark, 'blue')}>
                <div className="flex items-start gap-3">
                    <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-white text-brand shadow-sm'}`}>
                        <Building2 className="h-4 w-4" />
                    </span>
                    <div className="min-w-0">
                        <p className="text-sm font-semibold">Memória da empresa</p>
                        <p className={builderMutedTextClass(isDark, 'mt-1 text-xs leading-5')}>
                            Base estável usada por todos os agentes para manter identidade, oferta e políticas consistentes.
                        </p>
                    </div>
                </div>
            </div>

            <label className={builderToggleCardClass(isDark, agentContextSettings.global_context.enabled)}>
                <input
                    type="checkbox"
                    checked={agentContextSettings.global_context.enabled}
                    onChange={(event) => updateGlobalContextField('enabled', event.target.checked)}
                    className={builderCheckboxClass(isDark, 'mt-1')}
                />
                <span className="min-w-0">
                    <span className="block font-semibold">Usar contexto global da empresa</span>
                    <span className={builderMutedTextClass(isDark, 'mt-1 block text-xs leading-5')}>
                        Esse bloco entra como conhecimento persistente para todos os agentes da equipe.
                    </span>
                </span>
            </label>

            {([
                ['company_profile', 'Sobre a empresa', 'Resumo institucional, proposta de valor, localização e diferenciais.'],
                ['products_services', 'Produtos e serviços', 'Tratamentos, planos, serviços, preços públicos e condições conhecidas.'],
                ['brand_voice', 'Tom da marca', 'Como a empresa fala com clientes e quais palavras evitar ou priorizar.'],
                ['target_audience', 'Público-alvo', 'Perfil dos contatos, dores comuns e expectativas.'],
                ['commercial_policy', 'Políticas comerciais', 'Regras comerciais, desconto, orçamento, pagamento, garantia e agenda.'],
                ['faq', 'FAQ operacional', 'Perguntas frequentes e respostas oficiais curtas.']
            ] as Array<[keyof WorkforceGlobalContextSettings, string, string]>).map(([field, label, placeholder]) => (
                <div key={field} className={builderSurfaceClass(isDark, 'p-3')}>
                    <HelpFieldLabel help={placeholder}>{label}</HelpFieldLabel>
                    <textarea
                        value={String(agentContextSettings.global_context[field] || '')}
                        onChange={(event) => updateGlobalContextField(field, event.target.value)}
                        className={builderTextareaClass(isDark, 'mt-2 h-28')}
                        placeholder={placeholder}
                    />
                </div>
            ))}
        </div>
    );

    const renderKnowledgePanel = () => {
        const fileSearch = agentContextSettings.knowledge.file_search;
        const hasKnowledge = fileSearch.files.length > 0 || fileSearch.links.length > 0;

        return (
            <div className="space-y-3">
                <div className={flowNodePanelClass(isDark, 'emerald')}>
                    <div className="flex items-start gap-3">
                        <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-white text-emerald-700 shadow-sm'}`}>
                            <FileText className="h-4 w-4" />
                        </span>
                        <div className="min-w-0">
                            <p className="text-sm font-semibold">Conhecimento operacional</p>
                            <p className={builderMutedTextClass(isDark, 'mt-1 text-xs leading-5')}>
                                Documentos e links indexados entram como referência consultável sem poluir o prompt base.
                            </p>
                        </div>
                    </div>
                </div>

                <div className={builderPanelClass(isDark)}>
                    <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                            <div className="flex items-center gap-2">
                                <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-xl ${isDark ? 'bg-white/[0.07] text-white/60' : 'bg-white text-brand/60 ring-1 ring-brand/10'}`}>
                                    <Database className="h-3.5 w-3.5" />
                                </span>
                                <p className="text-sm font-semibold">Base RAG</p>
                            </div>
                            <p className={builderMutedTextClass(isDark, 'mt-2 text-xs leading-5')}>
                                Anexe PDFs da empresa. A indexação, vector store e busca por trechos ficam automáticas no backend.
                            </p>
                        </div>
                        <span className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-semibold uppercase ${hasKnowledge
                            ? 'bg-emerald-50 text-emerald-700'
                            : isDark ? 'bg-white/10 text-white/55' : 'bg-brand-canvas text-brand/55'
                            }`}>
                            {hasKnowledge ? 'ativo' : 'vazio'}
                        </span>
                    </div>

                    <label className={`mt-4 flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border border-dashed px-3 py-6 text-center text-sm transition ${
                        isDark ? 'border-white/10 bg-white/[0.03] text-white/65 hover:bg-white/[0.07]' : 'border-brand/10 bg-white text-brand/65 hover:bg-brand-canvas hover:text-brand'
                    }`}>
                        {knowledgeUploading ? <Loader2 className="h-5 w-5 animate-spin" /> : <FileText className="h-5 w-5" />}
                        <span className="font-medium">{knowledgeUploading ? 'Indexando PDF' : 'Anexar PDF'}</span>
                        <span className={`text-xs ${isDark ? 'text-white/45' : 'text-brand/45'}`}>O backend configura tudo depois do envio.</span>
                        <input
                            type="file"
                            accept="application/pdf,.pdf"
                            className="hidden"
                            disabled={knowledgeUploading}
                            onChange={(event) => {
                                const file = event.target.files?.[0];
                                event.currentTarget.value = '';
                                handleKnowledgeFileUpload(file);
                            }}
                        />
                    </label>

                    {!selectedWorkforce && (
                        <div className={`mt-3 rounded-2xl border px-3 py-2 text-xs ${isDark ? 'border-amber-300/20 bg-amber-300/10 text-amber-100' : 'border-amber-200 bg-amber-50 text-amber-700'}`}>
                            Salve a equipe uma vez antes de anexar o primeiro PDF.
                        </div>
                    )}

                    {(fileSearch.files.length > 0 || fileSearch.links.length > 0) && (
                        <div className="mt-4">
                            <div className="flex items-center justify-between gap-2">
                                <FieldLabel>Documentos indexados</FieldLabel>
                                <button
                                    type="button"
                                    onClick={handleKnowledgeRefresh}
                                    disabled={knowledgeRefreshing}
                                    className={agentiveSecondaryButtonClass(isDark, 'px-2 py-1 text-[11px] disabled:cursor-not-allowed')}
                                    title="Atualizar status dos documentos"
                                >
                                    <RefreshCw className={`h-3.5 w-3.5 ${knowledgeRefreshing ? 'animate-spin' : ''}`} />
                                    Atualizar
                                </button>
                            </div>
                            <div className={`mt-2 space-y-2 text-xs ${isDark ? 'text-white/55' : 'text-brand/55'}`}>
                                {fileSearch.files.slice(0, 8).map((item, index) => {
                                    const fileId = String(item.file_id || item.vector_store_file_id || '');
                                    const isDeleting = deletingKnowledgeFileId === fileId;
                                    return (
                                        <div key={`file-${fileId || index}`} className={builderSurfaceClass(isDark, 'flex items-center justify-between gap-2 px-2 py-2')}>
                                            <div className="flex min-w-0 items-center gap-2">
                                                <FileText className={`h-3.5 w-3.5 shrink-0 ${isDark ? 'text-white/35' : 'text-brand/35'}`} />
                                                <span className="truncate">{item.filename || 'Documento'}</span>
                                            </div>
                                            <div className="flex shrink-0 items-center gap-1.5">
                                                <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${knowledgeStatusClass(item.status)}`}>
                                                    {knowledgeStatusLabel(item.status)}
                                                </span>
                                                <button
                                                    type="button"
                                                    onClick={() => handleKnowledgeFileDelete(fileId)}
                                                    disabled={!fileId || isDeleting}
                                                    className={agentiveIconButtonClass(isDark, 'danger', 'min-h-8 min-w-8 p-1.5 disabled:cursor-not-allowed')}
                                                    title="Excluir documento"
                                                >
                                                    {isDeleting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                                                </button>
                                            </div>
                                        </div>
                                    );
                                })}
                                {fileSearch.links.slice(0, 8).map((item, index) => {
                                    const fileId = String(item.file_id || item.vector_store_file_id || '');
                                    const isDeleting = deletingKnowledgeFileId === fileId;
                                    return (
                                        <div key={`link-${item.url || fileId || index}`} className={builderSurfaceClass(isDark, 'flex items-center justify-between gap-2 px-2 py-2')}>
                                            <div className="flex min-w-0 items-center gap-2">
                                                <Globe className={`h-3.5 w-3.5 shrink-0 ${isDark ? 'text-white/35' : 'text-brand/35'}`} />
                                                <span className="truncate">{item.title || item.url}</span>
                                            </div>
                                            <div className="flex shrink-0 items-center gap-1.5">
                                                <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${knowledgeStatusClass(item.status)}`}>
                                                    {knowledgeStatusLabel(item.status)}
                                                </span>
                                                <button
                                                    type="button"
                                                    onClick={() => handleKnowledgeFileDelete(fileId)}
                                                    disabled={!fileId || isDeleting}
                                                    className={agentiveIconButtonClass(isDark, 'danger', 'min-h-8 min-w-8 p-1.5 disabled:cursor-not-allowed')}
                                                    title="Excluir link"
                                                >
                                                    {isDeleting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                                                </button>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        );
    };

    const renderGlobalExamplesPanel = () => (
        <div className="space-y-3">
            <div className={flowNodePanelClass(isDark, 'pink')}>
                <div className="flex items-start gap-3">
                    <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-white text-pink-700 shadow-sm'}`}>
                        <MessageCircle className="h-4 w-4" />
                    </span>
                    <div className="min-w-0">
                        <p className="text-sm font-semibold">Exemplos globais</p>
                        <p className={builderMutedTextClass(isDark, 'mt-1 text-xs leading-5')}>
                            Exemplos reutilizáveis ensinam padrões de resposta para toda a equipe.
                        </p>
                    </div>
                </div>
            </div>

            <label className={builderToggleCardClass(isDark, agentContextSettings.global_few_shots.enabled)}>
                <input
                    type="checkbox"
                    checked={agentContextSettings.global_few_shots.enabled}
                    onChange={(event) => updateAgentContextSettings((current) => ({
                        ...current,
                        global_few_shots: {
                            ...current.global_few_shots,
                            enabled: event.target.checked
                        }
                    }))}
                    className={builderCheckboxClass(isDark, 'mt-1')}
                />
                <span className="min-w-0">
                    <span className="block font-semibold">Recuperar exemplos globais</span>
                    <span className={builderMutedTextClass(isDark, 'mt-1 block text-xs leading-5')}>
                        Só os exemplos mais parecidos entram no prompt do turno.
                    </span>
                </span>
            </label>

            <div className="flex items-center justify-between">
                <FieldLabel>Few shots globais</FieldLabel>
                <button
                    type="button"
                    onClick={addGlobalFewShot}
                    className={agentiveSecondaryButtonClass(isDark, 'px-2.5 py-1.5 text-xs')}
                >
                    <Plus className="h-3.5 w-3.5" />
                    Exemplo
                </button>
            </div>

            {agentContextSettings.global_few_shots.examples.length === 0 ? (
                <div className={builderEmptyClass(isDark)}>
                    Nenhum exemplo global ainda.
                </div>
            ) : (
                <div className="space-y-3">
                    {agentContextSettings.global_few_shots.examples.map((example, index) => (
                        <div key={`global-few-shot-${index}`} className={builderPanelClass(isDark)}>
                            <div className="mb-2 flex items-center gap-2">
                                <input
                                    value={example.title || ''}
                                    onChange={(event) => updateGlobalFewShot(index, 'title', event.target.value)}
                                    className={builderInputClass(isDark, 'min-w-0 flex-1 text-xs')}
                                    placeholder="Título do exemplo"
                                />
                                <button
                                    type="button"
                                    onClick={() => removeGlobalFewShot(index)}
                                    className={agentiveIconButtonClass(isDark, 'danger')}
                                    title="Remover exemplo"
                                >
                                    <Trash2 className="h-3.5 w-3.5" />
                                </button>
                            </div>
                            <input
                                value={example.tags || ''}
                                onChange={(event) => updateGlobalFewShot(index, 'tags', event.target.value)}
                                className={builderInputClass(isDark, 'mb-2 text-xs')}
                                placeholder="Tags: preço, objeção, agendamento"
                            />
                            <textarea
                                value={example.context || ''}
                                onChange={(event) => updateGlobalFewShot(index, 'context', event.target.value)}
                                className={builderTextareaClass(isDark, 'mb-2 h-14 text-xs')}
                                placeholder="Contexto opcional"
                            />
                            <textarea
                                value={example.user}
                                onChange={(event) => updateGlobalFewShot(index, 'user', event.target.value)}
                                className={builderTextareaClass(isDark, 'mb-2 h-16 text-xs')}
                                placeholder="Mensagem real do contato"
                            />
                            <textarea
                                value={example.assistant}
                                onChange={(event) => updateGlobalFewShot(index, 'assistant', event.target.value)}
                                className={builderTextareaClass(isDark, 'h-16 text-xs')}
                                placeholder="Resposta ideal"
                            />
                        </div>
                    ))}
                </div>
            )}
        </div>
    );

    const renderSchedulePanel = () => {
        const schedule = agentContextSettings.schedule;

        return (
            <div className="space-y-4">
                <div className={flowNodePanelClass(isDark, 'sky')}>
                    <div className="flex items-start gap-3">
                        <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-white text-sky-700 shadow-sm'}`}>
                            <CalendarClock className="h-4 w-4" />
                        </div>
                        <div>
                            <p className="text-sm font-semibold">Horários de atendimento</p>
                            <p className={builderMutedTextClass(isDark, 'mt-1 text-xs leading-5')}>
                                Define quando a equipe ativa pode responder automaticamente no WhatsApp.
                            </p>
                        </div>
                    </div>
                </div>

                <div className={builderPanelClass(isDark)}>
                    <FieldLabel>Modo</FieldLabel>
                    <div className={`mt-2 grid grid-cols-2 gap-1 rounded-2xl border p-1 ${isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-white'}`}>
                        {[
                            { value: 'always_on' as WorkforceScheduleMode, label: '24h' },
                            { value: 'custom' as WorkforceScheduleMode, label: 'Personalizado' }
                        ].map((option) => {
                            const active = schedule.mode === option.value;
                            return (
                                <button
                                    key={option.value}
                                    type="button"
                                    onClick={() => updateScheduleMode(option.value)}
                                    className={`h-9 rounded-xl px-2 text-xs font-semibold transition ${active
                                        ? isDark ? 'bg-white/[0.12] text-white' : 'bg-brand text-white shadow-sm shadow-brand/15'
                                        : isDark ? 'text-white/50 hover:bg-white/10 hover:text-white' : 'text-brand/50 hover:bg-brand-canvas hover:text-brand'
                                        }`}
                                >
                                    {option.label}
                                </button>
                            );
                        })}
                    </div>
                </div>

                <div className={builderPanelClass(isDark)}>
                    <FieldLabel>Fuso horário</FieldLabel>
                    <div className="relative mt-2">
                        <select
                            value={schedule.timezone}
                            onChange={(event) => updateScheduleTimezone(event.target.value)}
                            className={builderSelectClass(isDark)}
                        >
                            <option value="America/Sao_Paulo">America/Sao_Paulo</option>
                            <option value="America/Manaus">America/Manaus</option>
                            <option value="America/Cuiaba">America/Cuiaba</option>
                            <option value="America/Rio_Branco">America/Rio_Branco</option>
                            <option value="UTC">UTC</option>
                        </select>
                        <ChevronDown className={builderChevronClass(isDark, 'right-3')} />
                    </div>
                </div>

                {schedule.mode === 'custom' && (
                    <div className="space-y-3">
                        {WORKFORCE_WEEKDAYS.map((day) => {
                            const daySchedule = schedule.days[day.key];
                            return (
                                <div key={day.key} className={builderPanelClass(isDark)}>
                                    <label className="flex items-start gap-3">
                                        <input
                                            type="checkbox"
                                            checked={daySchedule.enabled}
                                            onChange={(event) => updateScheduleDayEnabled(day.key, event.target.checked)}
                                            className={builderCheckboxClass(isDark, 'mt-1')}
                                        />
                                        <span className="min-w-0 flex-1">
                                            <span className="block text-sm font-semibold">{day.label}</span>
                                            <span className={builderMutedTextClass(isDark, 'mt-1 block text-xs')}>
                                                {daySchedule.enabled ? 'Atendimento liberado' : 'Sem atendimento automático'}
                                            </span>
                                        </span>
                                    </label>

                                    {daySchedule.enabled && (
                                        <div className="mt-3 space-y-2">
                                            {WORKFORCE_SCHEDULE_PERIODS.map((period) => {
                                                const periodSchedule = daySchedule.periods[period.key];
                                                return (
                                                    <div
                                                        key={`${day.key}-${period.key}`}
                                                        className={`rounded-2xl border p-2 ${isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-white'}`}
                                                    >
                                                        <label className="flex items-center gap-2">
                                                            <input
                                                                type="checkbox"
                                                                checked={periodSchedule.enabled}
                                                                onChange={(event) => updateSchedulePeriod(day.key, period.key, { enabled: event.target.checked })}
                                                                className={builderCheckboxClass(isDark)}
                                                            />
                                                            <span className="text-xs font-semibold">{period.label}</span>
                                                        </label>
                                                        {periodSchedule.enabled && (
                                                            <div className="mt-2 grid grid-cols-2 gap-2">
                                                                <input
                                                                    type="time"
                                                                    value={periodSchedule.start}
                                                                    onChange={(event) => updateSchedulePeriod(day.key, period.key, { start: event.target.value })}
                                                                    className={builderInputClass(isDark, 'text-xs')}
                                                                    aria-label={`${period.label} início ${day.label}`}
                                                                />
                                                                <input
                                                                    type="time"
                                                                    value={periodSchedule.end}
                                                                    onChange={(event) => updateSchedulePeriod(day.key, period.key, { end: event.target.value })}
                                                                    className={builderInputClass(isDark, 'text-xs')}
                                                                    aria-label={`${period.label} fim ${day.label}`}
                                                                />
                                                            </div>
                                                        )}
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        );
    };

    const renderPerformancePanel = () => (
        <div className="space-y-4">
            <div className={flowNodePanelClass(isDark, 'emerald')}>
                <div className="flex items-start gap-3">
                    <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-white text-emerald-700 shadow-sm'}`}>
                        <DollarSign className="h-4 w-4" />
                    </div>
                    <div>
                        <p className="text-sm font-semibold">Custo e qualidade</p>
                        <p className={`mt-1 text-xs leading-5 ${isDark ? 'text-white/60' : 'text-brand/60'}`}>
                            Controle quanto contexto entra em cada resposta. Mais contexto melhora precisão, mas aumenta custo e latência.
                        </p>
                    </div>
                </div>
            </div>

            <div className={builderPanelClass(isDark)}>
                <FieldLabel>Exemplos reais por resposta</FieldLabel>
                <input
                    type="number"
                    min={0}
                    max={8}
                    value={agentContextSettings.performance.max_global_few_shots}
                    onChange={(event) => updatePerformanceField('max_global_few_shots', Number(event.target.value || 0))}
                    className={builderInputClass(isDark, 'mt-2')}
                />
                <p className={builderMutedTextClass(isDark, 'mt-2 text-xs leading-5')}>
                    Quantos exemplos parecidos o agente pode consultar antes de responder. Use 1 a 3 para equilibrar custo e consistência.
                </p>
            </div>

            <div className={builderPanelClass(isDark)}>
                <FieldLabel>Tempo de resposta no WhatsApp</FieldLabel>
                <div className="mt-1 flex items-center gap-2">
                    <input
                        type="number"
                        min={0}
                        max={MAX_AGENT_RESPONSE_DELAY_SECONDS}
                        value={agentContextSettings.performance.response_delay_seconds}
                        onChange={(event) => updatePerformanceField('response_delay_seconds', clampAgentResponseDelay(event.target.value))}
                        className={builderInputClass(isDark)}
                    />
                    <span className={`shrink-0 rounded-xl border px-3 py-2 text-xs font-semibold ${isDark ? 'border-white/10 bg-white/[0.06] text-white/50' : 'border-brand/10 bg-white text-brand/50'}`}>
                        seg
                    </span>
                </div>
                <p className={builderMutedTextClass(isDark, 'mt-2 text-xs leading-5')}>
                    Aguarda antes de enviar a resposta automática. No WhatsApp, o contato vê o status de digitação durante esse tempo.
                </p>
            </div>

            <div className={builderPanelClass(isDark)}>
                <FieldLabel>Uso dos exemplos</FieldLabel>
                <div className="relative mt-2">
                    <select
                        value={agentContextSettings.performance.retrieval_mode}
                        onChange={(event) => updatePerformanceField('retrieval_mode', event.target.value)}
                        className={builderSelectClass(isDark)}
                    >
                        <option value="keyword">Automático por relevância</option>
                        <option value="off">Não usar exemplos globais</option>
                    </select>
                    <ChevronDown className={builderChevronClass(isDark, 'right-3')} />
                </div>
                <p className={builderMutedTextClass(isDark, 'mt-2 text-xs leading-5')}>
                    No automático, só os exemplos mais próximos da mensagem atual entram no prompt.
                </p>
            </div>

            <label className={builderToggleCardClass(isDark, agentContextSettings.performance.include_global_context)}>
                <input
                    type="checkbox"
                    checked={agentContextSettings.performance.include_global_context}
                    onChange={(event) => updatePerformanceField('include_global_context', event.target.checked)}
                    className={builderCheckboxClass(isDark, 'mt-1')}
                />
                <span className="min-w-0">
                    <span className="block font-semibold">Usar dados da empresa em todas as respostas</span>
                    <span className={builderMutedTextClass(isDark, 'mt-1 block text-xs leading-5')}>
                        Mantém sobre a empresa, serviços, tom de voz, público e políticas sempre disponíveis para todos os agentes.
                    </span>
                </span>
            </label>
        </div>
    );

    const hasInspectorSelection = Boolean(selectedNode || selectedEdge);
    const selectedToolIds = selectedNode ? sanitizeToolIds(selectedNode.data.tools) : [];
    const selectedCalendarSettings = selectedNode
        ? sanitizeCalendarToolSettings(selectedNode.data.toolSettings?.[CALENDAR_TOOL_ID])
        : DEFAULT_CALENDAR_TOOL_SETTINGS;
    const selectedCalendarAgenda = selectedCalendarSettings.agendaId
        ? calendarAgendas.find((agenda) => Number(agenda.id) === Number(selectedCalendarSettings.agendaId))
        : undefined;
    const googleLinkedAgendas = calendarAgendas.filter((agenda) => Boolean(agenda.google_calendar_id));
    const canCreateGoogleMeet = selectedCalendarAgenda
        ? Boolean(selectedCalendarAgenda.google_calendar_id)
        : googleLinkedAgendas.length > 0;
    const googleMeetStatusLabel = selectedCalendarAgenda
        ? selectedCalendarAgenda.google_calendar_id
            ? selectedCalendarAgenda.google_calendar_summary || selectedCalendarAgenda.google_calendar_id
            : 'Agenda selecionada sem vínculo Google'
        : googleLinkedAgendas.length > 0
            ? `${googleLinkedAgendas.length} agenda(s) vinculada(s)`
            : 'Nenhuma agenda vinculada ao Google';
    const selectedCrmSettings = selectedNode
        ? sanitizeCrmPipelineToolSettings(selectedNode.data.toolSettings?.[CRM_PIPELINE_TOOL_ID])
        : DEFAULT_CRM_PIPELINE_TOOL_SETTINGS;
    const selectedCrmPipeline = selectedCrmSettings.pipelineId
        ? crmPipelines.find((pipeline) => Number(pipeline.id) === Number(selectedCrmSettings.pipelineId)) || null
        : crmPipelines.find((pipeline) => pipeline.is_active !== false) || crmPipelines[0] || null;
    const selectedCrmStages = selectedCrmPipeline?.stages || [];
    const selectedCrmStageRules = getCrmStageRulesForPipeline(selectedCrmSettings, selectedCrmStages);
    const selectedDynamicCrmFollowupSettings = selectedNode
        ? sanitizeDynamicCrmFollowupToolSettings(selectedNode.data.toolSettings?.[DYNAMIC_CRM_FOLLOWUP_TOOL_ID])
        : DEFAULT_DYNAMIC_CRM_FOLLOWUP_SETTINGS;
    const selectedDynamicFollowupPipeline = selectedDynamicCrmFollowupSettings.pipelineId
        ? crmPipelines.find((pipeline) => Number(pipeline.id) === Number(selectedDynamicCrmFollowupSettings.pipelineId)) || null
        : crmPipelines.find((pipeline) => pipeline.is_active !== false) || crmPipelines[0] || null;
    const selectedDynamicFollowupStages = selectedDynamicFollowupPipeline?.stages || [];
    const selectedDynamicFollowupDeliveryWindow = selectedDynamicCrmFollowupSettings.deliveryWindow;
    const selectedDynamicFollowupWeekdaySummary = DYNAMIC_FOLLOWUP_WEEKDAYS
        .filter((day) => selectedDynamicFollowupDeliveryWindow.allowedWeekdays.includes(day.value))
        .map((day) => day.short)
        .join(', ');
    const selectedWhatsAppContactSettings = selectedNode
        ? sanitizeWhatsAppContactCardToolSettings(selectedNode.data.toolSettings?.[WHATSAPP_CONTACT_CARD_TOOL_ID])
        : DEFAULT_WHATSAPP_CONTACT_CARD_SETTINGS;
    const selectedWhatsAppScheduledFollowupSettings = selectedNode
        ? sanitizeWhatsAppScheduledFollowupToolSettings(selectedNode.data.toolSettings?.[WHATSAPP_SCHEDULED_FOLLOWUP_TOOL_ID])
        : DEFAULT_WHATSAPP_SCHEDULED_FOLLOWUP_SETTINGS;
    const inspectorTitle = selectedNode
        ? (selectedNode.data.kind === 'human' ? 'Fila humana' : 'Agente')
        : selectedEdge
            ? 'Conexão'
            : 'Configurações globais';
    const inspectorSubtitle = selectedNode
        ? selectedNode.data.name
        : selectedEdge
            ? 'Regra de handoff'
            : 'Contexto, RAG, exemplos e custo';
    const libraryWidth = isLibraryCollapsed ? '72px' : '280px';
    const inspectorColumnWidth = isInspectorPanelOpen ? `${INSPECTOR_DEFAULT_WIDTH}px` : '56px';

    return (
        <div className={agentivePageClass(isDark, 'p-3 pb-[calc(7rem+env(safe-area-inset-bottom))] sm:p-4 sm:pb-4')}>
            <section className={`flex min-h-[calc(100vh-1.5rem-7rem)] flex-col overflow-hidden rounded-[24px] border shadow-[0_22px_55px_rgba(2,3,35,0.12)] sm:h-[calc(100vh-2rem)] sm:min-h-0 ${panelClass}`}>
            <header className={`z-20 border-b px-4 py-3 ${isDark ? 'border-white/10 bg-brand' : 'border-brand/10 bg-white'}`}>
                <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
                    <div className="flex min-w-0 items-center gap-3">
                        <button
                            type="button"
                            onClick={() => navigate('/agents')}
                            className={agentiveIconButtonClass(isDark)}
                            aria-label="Voltar para equipes"
                        >
                            <ArrowLeft className="h-5 w-5" />
                        </button>
                        <div className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
                            <Network className="h-5 w-5" />
                        </div>
                        <div className="min-w-0">
                            <div className="mb-1 flex items-center gap-2">
                                <AgentBuilderTrafficDots isDark={isDark} />
                                <span className={`text-[10px] font-bold uppercase tracking-[0.18em] ${isDark ? 'text-white/35' : 'text-brand/35'}`}>
                                    Agent Builder
                                </span>
                            </div>
                            <div className="flex flex-wrap items-center gap-2">
                                <h1 className="truncate text-lg font-semibold leading-tight">{name || 'Equipe de agentes'}</h1>
                                <span className={agentivePillClass(isDark, status === 'active')}>
                                    {status === 'active' ? 'Ativa' : status === 'paused' ? 'Pausada' : 'Rascunho'}
                                </span>
                                <span className={agentivePillClass(isDark, isDirty)}>
                                    {isDirty ? 'Alterado' : 'Salvo'}
                                </span>
                            </div>
                            <p className={`mt-1 text-xs ${isDark ? 'text-white/50' : 'text-brand/50'}`}>
                                {agentNodes.length} agentes, {edges.length} conexões, canal WhatsApp
                            </p>
                        </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                        <button
                            type="button"
                            onClick={openInspectorPanel}
                            className={agentiveSecondaryButtonClass(isDark, 'min-h-10 2xl:hidden')}
                        >
                            <Settings className="h-4 w-4" />
                            Configurar
                        </button>
                        <button
                            type="button"
                            onClick={openNewAgentModal}
                            disabled={!hasReadyModelCatalog}
                            className={agentiveSecondaryButtonClass(isDark, 'min-h-10')}
                            title={hasReadyModelCatalog ? 'Criar novo agente' : modelCatalogMessage}
                        >
                            <Plus className="h-4 w-4" />
                            Novo agente
                        </button>
                        <button
                            type="button"
                            onClick={handleSave}
                            disabled={saving}
                            className={agentivePrimaryButtonClass('min-h-10 px-4')}
                        >
                            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                            {saving ? 'Salvando' : 'Salvar'}
                        </button>
                    </div>
                </div>
            </header>

            {error && (
                <AgentiveAlert variant="error" title="Ação não concluída" className="m-3" onClose={() => setError('')}>
                    {error}
                </AgentiveAlert>
            )}

            {!hasReadyModelCatalog && (
                <AgentiveAlert
                    variant={modelCatalogStatus === 'loading' ? 'info' : 'warning'}
                    title={modelCatalogStatus === 'loading' ? 'Carregando modelos' : 'Catálogo de modelos indisponível'}
                    className="m-3"
                >
                    <div className="flex flex-col items-start gap-2 sm:flex-row sm:items-center sm:justify-between">
                        <span>{modelCatalogMessage}</span>
                        {modelCatalogStatus !== 'loading' && (
                            <button
                                type="button"
                                onClick={() => navigate('/company/ai-provider')}
                                className={agentiveSecondaryButtonClass(isDark, 'shrink-0')}
                            >
                                Configurar provedor
                            </button>
                        )}
                    </div>
                </AgentiveAlert>
            )}

            <div
                className={cx(
                    'grid min-h-0 flex-1 grid-cols-1 gap-3 p-3 lg:grid-cols-[var(--agent-builder-library-width)_minmax(0,1fr)]',
                    '2xl:grid-cols-[var(--agent-builder-library-width)_minmax(0,1fr)_var(--agent-builder-inspector-width)]',
                    isDark ? 'bg-white/[0.025]' : 'bg-brand-canvas'
                )}
                style={{
                    '--agent-builder-inspector-width': inspectorColumnWidth,
                    '--agent-builder-library-width': libraryWidth,
                } as React.CSSProperties}
            >
                <aside className={`min-h-0 overflow-y-auto rounded-2xl border shadow-flat-md ${isLibraryCollapsed ? 'p-2' : 'p-3'} ${isDark ? 'border-white/10 bg-brand' : 'border-brand/10 bg-white'}`}>
                    {isLibraryCollapsed ? (
                        <div className="flex h-full flex-col items-center gap-2">
                            <button
                                type="button"
                                onClick={() => setIsLibraryCollapsed(false)}
                                className={agentiveIconButtonClass(isDark, 'neutral', 'h-10 w-10 p-0')}
                                title="Expandir painel"
                                aria-label="Expandir painel de equipe"
                            >
                                <ChevronRight className="h-4 w-4" />
                            </button>
                            <button
                                type="button"
                                onClick={openNewAgentModal}
                                className={agentiveIconButtonClass(isDark, 'neutral', 'h-10 w-10 p-0')}
                                title="Novo agente"
                                aria-label="Novo agente"
                            >
                                <Bot className="h-4 w-4" />
                            </button>
                            <button
                                type="button"
                                onClick={handleHumanShortcut}
                                className={agentiveIconButtonClass(isDark, 'neutral', 'h-10 w-10 p-0')}
                                title="Fila humana"
                                aria-label="Fila humana"
                            >
                                <Users className="h-4 w-4" />
                            </button>
                            <button
                                type="button"
                                onClick={openInspectorPanel}
                                className={agentiveIconButtonClass(isDark, 'neutral', 'h-10 w-10 p-0 2xl:hidden')}
                                title="Configurar"
                                aria-label="Abrir configurações"
                            >
                                <Settings className="h-4 w-4" />
                            </button>
                            <div className={cx(
                                'mt-auto grid w-full gap-2 rounded-xl border px-2 py-3 text-center text-[10px] font-semibold leading-none',
                                isDark ? 'border-white/10 bg-white/[0.04] text-white/55' : 'border-brand/10 bg-brand-canvas text-brand/55'
                            )}>
                                <span>{agentNodes.length}</span>
                                <span>{nodes.filter((node) => node.data.kind === 'human').length}</span>
                                <span>{edges.length}</span>
                            </div>
                        </div>
                    ) : (
                        <>
                                <div className="mb-3 flex items-center justify-between gap-3">
                                    <div className="min-w-0">
                                        <p className={`text-[10px] font-bold uppercase tracking-[0.16em] ${isDark ? 'text-white/35' : 'text-brand/35'}`}>Workspace</p>
                                        <p className={`truncate text-xs ${isDark ? 'text-white/50' : 'text-brand/50'}`}>Equipe e componentes</p>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => setIsLibraryCollapsed(true)}
                                        className={agentiveIconButtonClass(isDark, 'neutral', 'h-9 w-9 p-0')}
                                        title="Recolher painel"
                                        aria-label="Recolher painel de equipe"
                                    >
                                        <ChevronLeft className="h-4 w-4" />
                                    </button>
                                </div>
                                <div className={builderPanelClass(isDark, 'space-y-3')}>
                                    <div>
                                        <FieldLabel>Equipe</FieldLabel>
                                        <p className={builderMutedTextClass(isDark, 'mt-1 text-xs leading-5')}>
                                            Defina a identidade e a entrada principal desta equipe multiagente.
                                        </p>
                                    </div>
                                    <input
                                        value={name}
                                        onChange={(event) => {
                                            setName(event.target.value);
                                            setIsDirty(true);
                                        }}
                                        className={`w-full rounded-xl border px-3 py-2 text-sm outline-none ${inputClass}`}
                                        placeholder="Nova equipe"
                                    />
                                    <textarea
                                        value={description}
                                        onChange={(event) => {
                                            setDescription(event.target.value);
                                            setIsDirty(true);
                                        }}
                                        className={`h-20 w-full resize-none rounded-xl border px-3 py-2 text-sm outline-none ${inputClass}`}
                                        placeholder="Descreva a responsabilidade desta equipe"
                                    />
                                    <div className="grid grid-cols-2 gap-2">
                                        <select
                                            value={status}
                                            onChange={(event) => {
                                                setStatus(event.target.value as AgentStatus);
                                                setIsDirty(true);
                                            }}
                                            className={`rounded-xl border px-3 py-2 text-sm outline-none ${inputClass}`}
                                        >
                                            <option value="draft">Rascunho</option>
                                            <option value="active">Ativa</option>
                                            <option value="paused">Pausada</option>
                                        </select>
                                        <div className={`flex items-center justify-center rounded-xl border text-xs font-semibold ${isDark ? 'border-white/10 bg-white/[0.04] text-white/50' : 'border-brand/10 bg-white text-brand/50'}`}>
                                            {isDirty ? 'Alterado' : 'Sincronizado'}
                                        </div>
                                    </div>
                                    <div>
                                        <FieldLabel>Agente inicial</FieldLabel>
                                        <div className="relative mt-2">
                                            <select
                                                value={rootAgentKey || ''}
                                                onChange={(event) => {
                                                    setRootAgentKey(event.target.value || null);
                                                    setIsDirty(true);
                                                }}
                                                className={`w-full appearance-none rounded-xl border px-3 py-2 pr-8 text-sm outline-none ${inputClass}`}
                                            >
                                                <option value="">Selecione o primeiro agente</option>
                                                {agentNodes.map((node) => (
                                                    <option key={node.id} value={node.data.key}>
                                                        {node.data.name}
                                                    </option>
                                                ))}
                                            </select>
                                            <ChevronDown className={`pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 ${isDark ? 'text-white/45' : 'text-brand/45'}`} />
                                        </div>
                                    </div>
                                </div>

                                <div className="mt-3 space-y-3">
                                    <div>
                                        <p className={`text-[10px] font-bold uppercase tracking-[0.16em] ${isDark ? 'text-white/35' : 'text-brand/35'}`}>Componentes</p>
                                        <p className={`mt-1 text-xs ${isDark ? 'text-white/50' : 'text-brand/50'}`}>
                                            Adicione especialistas e filas humanas ao canvas.
                                        </p>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={openNewAgentModal}
                                        className={agentiveSecondaryButtonClass(isDark, 'w-full justify-start')}
                                    >
                                        <Bot className="h-4 w-4" />
                                        Agente IA
                                    </button>
                                    <button
                                        type="button"
                                        onClick={handleHumanShortcut}
                                        className={agentiveSecondaryButtonClass(isDark, 'w-full justify-start')}
                                    >
                                        <Users className="h-4 w-4" />
                                        Fila humana
                                    </button>
                                    <div className={flowNodePanelClass(isDark)}>
                                        <p className={`text-xs font-semibold ${isDark ? 'text-white/75' : 'text-brand/70'}`}>Resumo</p>
                                        <div className={`mt-2 grid grid-cols-3 gap-2 text-center text-xs ${isDark ? 'text-white/55' : 'text-brand/55'}`}>
                                            <span>{agentNodes.length}<br />agentes</span>
                                            <span>{nodes.filter((node) => node.data.kind === 'human').length}<br />filas</span>
                                            <span>{edges.length}<br />conexões</span>
                                        </div>
                                    </div>
                                </div>
                            </>
                        )}
                    </aside>

                <main className={`relative min-h-[560px] min-w-0 overflow-hidden rounded-2xl border shadow-[0_18px_45px_rgba(2,3,35,0.08)] ${isDark ? 'border-white/10 bg-brand' : 'border-brand/10 bg-white'}`}>
                    <ReactFlow
                        nodes={nodes}
                        edges={edges}
                        nodeTypes={nodeTypes}
                        onNodesChange={handleNodesChange}
                        onEdgesChange={handleEdgesChange}
                        onConnect={onConnect}
                        connectionMode={ConnectionMode.Strict}
                        connectionRadius={34}
                        onInit={setReactFlowInstance}
                        onSelectionChange={(selection) => {
                            const nextSelectedNodeId = selection.nodes[0]?.id || null;
                            const nextSelectedEdgeId = selection.edges[0]?.id || null;
                            setSelectedNodeId(nextSelectedNodeId);
                            setSelectedEdgeId(nextSelectedEdgeId);
                            if (
                                typeof window !== 'undefined'
                                && window.innerWidth < 1536
                                && (nextSelectedNodeId || nextSelectedEdgeId)
                            ) {
                                setIsInspectorDrawerOpen(true);
                            }
                        }}
                        fitView
                        proOptions={{ hideAttribution: true }}
                        className={isDark ? 'bg-brand' : 'bg-brand-canvas'}
                    >
                        <Background variant={BackgroundVariant.Dots} gap={22} size={1} color={isDark ? 'rgba(255,255,255,0.16)' : 'rgba(2,3,35,0.18)'} />
                        <Controls className={`!rounded-2xl !border !shadow-flat-md ${isDark ? '!border-white/10 !bg-brand !text-white' : '!border-brand/10 !bg-white !text-brand'}`} />
                        <MiniMap
                            nodeColor={(node) => KIND_MINIMAP_COLOR[(node.data as AgentNodeData).kind || 'custom']}
                            className={`!rounded-2xl !border !shadow-flat-md ${isDark ? '!border-white/10 !bg-brand' : '!border-brand/10 !bg-white'}`}
                        />

                        <Panel position="top-left" className="m-3">
                            <div className={`flex flex-wrap gap-2 rounded-2xl border p-2 shadow-flat-md backdrop-blur ${isDark ? 'border-white/10 bg-brand/90' : 'border-brand/10 bg-white/95'}`}>
                                <button
                                    onClick={openNewAgentModal}
                                    className="inline-flex items-center gap-2 rounded-xl bg-brand px-2.5 py-2 text-xs font-semibold text-white transition hover:bg-brand/90"
                                    title="Criar novo agente personalizado"
                                >
                                    <Plus className="h-4 w-4" />
                                    Novo agente
                                </button>
                                <button
                                    onClick={handleHumanShortcut}
                                    className={`inline-flex items-center gap-2 rounded-xl px-2.5 py-2 text-xs font-semibold transition ${humanNode
                                        ? selectedNodeId === humanNode.id
                                            ? 'bg-pink-500/10 text-pink-600'
                                            : 'text-pink-600 hover:bg-pink-500/10'
                                        : 'border border-dashed border-pink-400/40 text-pink-600 hover:bg-pink-500/10'
                                        }`}
                                    title={humanNode ? 'Selecionar fila humana' : 'Adicionar fila humana'}
                                >
                                    <Users className="h-4 w-4" />
                                    Humano
                                </button>
                                {nodes.filter((node) => node.data.kind !== 'human').map((node) => {
                                    const iconOption = getIconOption(node.data.iconKey, node.data.kind);
                                    const Icon = iconOption.icon;
                                    const isSelected = node.id === selectedNodeId;
                                    return (
                                        <button
                                            key={node.id}
                                            onClick={() => focusNode(node as AgentNode)}
                                            className={`inline-flex items-center gap-2 rounded-xl px-2.5 py-2 text-xs font-semibold transition ${isSelected
                                                ? isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'
                                                : isDark ? 'text-white/60 hover:bg-white/10 hover:text-white' : 'text-brand/60 hover:bg-brand-canvas hover:text-brand'
                                                }`}
                                            title={node.data.name}
                                        >
                                            <Icon className="h-4 w-4" />
                                            {node.data.name}
                                        </button>
                                    );
                                })}
                            </div>
                        </Panel>

                        <Panel position="bottom-left" className="m-3">
                            <div className={`flex items-center gap-3 rounded-2xl border px-3 py-2 text-xs shadow-flat-md ${isDark ? 'border-white/10 bg-brand/90 text-white/55' : 'border-brand/10 bg-white/95 text-brand/55'}`}>
                                <span>{nodes.filter((node) => node.data.kind !== 'human').length} agentes</span>
                                <span>{nodes.filter((node) => node.data.kind === 'human').length} filas humanas</span>
                                <span>{edges.length} conexões</span>
                                <span>Canal WhatsApp</span>
                            </div>
                        </Panel>
                    </ReactFlow>
                </main>

                {isInspectorDrawerOpen && (
                    <button
                        type="button"
                        onClick={() => setIsInspectorDrawerOpen(false)}
                        className="fixed inset-0 z-[60] bg-brand/45 backdrop-blur-sm 2xl:hidden"
                        aria-label="Fechar painel de configuração"
                    />
                )}

                <aside className={cx(
                    'min-h-0 flex-col overflow-hidden rounded-2xl border shadow-flat-md',
                    isInspectorDrawerOpen
                        ? 'fixed bottom-3 right-3 top-3 z-[70] flex w-[min(420px,calc(100vw-1.5rem))]'
                        : 'hidden',
                    '2xl:relative 2xl:bottom-auto 2xl:right-auto 2xl:top-auto 2xl:z-auto 2xl:flex 2xl:w-auto',
                    isDark ? 'border-white/10 bg-brand' : 'border-brand/10 bg-white'
                )}>
                    {!isInspectorPanelOpen ? (
                        <div className="flex h-full w-full flex-col items-center gap-2 p-2">
                            <button
                                type="button"
                                onClick={openInspectorPanel}
                                className={agentiveIconButtonClass(isDark, 'neutral', 'h-10 w-10 p-0')}
                                title="Expandir configurações"
                                aria-label="Expandir painel de configuração"
                            >
                                <ChevronLeft className="h-4 w-4" />
                            </button>
                            <button
                                type="button"
                                onClick={openInspectorPanel}
                                className={agentiveIconButtonClass(isDark, 'neutral', 'h-10 w-10 p-0')}
                                title={inspectorTitle}
                                aria-label="Abrir configurações"
                            >
                                <Settings className="h-4 w-4" />
                            </button>
                        </div>
                    ) : (
                        <>
                    <div className={`flex items-center justify-between border-b px-4 py-3 ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
                        <div className="min-w-0">
                            <p className="truncate text-sm font-semibold">{inspectorTitle}</p>
                            <p className={`truncate text-xs ${isDark ? 'text-white/50' : 'text-brand/50'}`}>{inspectorSubtitle}</p>
                        </div>
                        <div className="flex items-center gap-2">
                            {hasInspectorSelection && (
                                <button
                                    type="button"
                                    onClick={clearInspectorSelection}
                                    className={agentiveSecondaryButtonClass(isDark, 'px-2.5 py-2 text-xs')}
                                    title="Ver configurações globais"
                                >
                                    <Globe className="h-4 w-4" />
                                    Globais
                                </button>
                            )}
                            <button
                                onClick={handleDeleteSelected}
                                disabled={!selectedNode && !selectedEdge}
                                className={agentiveIconButtonClass(isDark, 'danger')}
                                title="Excluir seleção"
                            >
                                <Trash2 className="h-4 w-4" />
                            </button>
                            <button
                                type="button"
                                onClick={minimizeInspectorPanel}
                                className={agentiveIconButtonClass(isDark, 'neutral')}
                                title="Minimizar painel"
                                aria-label="Minimizar painel de configuração"
                            >
                                <ChevronRight className="h-4 w-4" />
                            </button>
                        </div>
                    </div>

                    {!hasInspectorSelection && (
                        <div className={`border-b px-3 py-2 ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
                            <div className={`grid grid-cols-5 gap-1 rounded-2xl border p-1 ${isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-brand-canvas'}`}>
                                {inspectorTabs.map((tab) => {
                                    const Icon = tab.icon;
                                    const isActive = activeInspectorTab === tab.id;
                                    return (
                                        <button
                                            key={tab.id}
                                            type="button"
                                            onClick={() => setActiveInspectorTab(tab.id)}
                                            className={`flex h-8 items-center justify-center rounded-xl transition ${isActive
                                                ? isDark ? 'bg-white/[0.12] text-white' : 'bg-brand text-white shadow-sm shadow-brand/15'
                                                : isDark ? 'text-white/45 hover:bg-white/10 hover:text-white' : 'text-brand/45 hover:bg-white hover:text-brand'
                                                }`}
                                            aria-label={tab.label}
                                            title={tab.label}
                                        >
                                            <Icon className="h-4 w-4" />
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    <div className="min-h-0 flex-1 overflow-y-auto p-4">
                        {!hasInspectorSelection && activeInspectorTab === 'context' ? (
                            renderGlobalContextPanel()
                        ) : !hasInspectorSelection && activeInspectorTab === 'knowledge' ? (
                            renderKnowledgePanel()
                        ) : !hasInspectorSelection && activeInspectorTab === 'examples' ? (
                            renderGlobalExamplesPanel()
                        ) : !hasInspectorSelection && activeInspectorTab === 'schedule' ? (
                            renderSchedulePanel()
                        ) : !hasInspectorSelection && activeInspectorTab === 'performance' ? (
                            renderPerformancePanel()
                        ) : selectedNode ? (
                            selectedNode.data.kind === 'human' ? (
                                <HumanQueueInspector
                                    node={selectedNode as AgentNode}
                                    users={humanUsers}
                                    teams={humanTeams}
                                    inputClass={inputClass}
                                    onNameChange={updateNodeName}
                                    onNodeDataChange={updateNodeData}
                                    onHumanQueueChange={updateHumanQueueData}
                                />
                            ) : (
                            <div className="space-y-4">
                                <div>
                                    <FieldLabel>Nome</FieldLabel>
                                    <input
                                        value={selectedNode.data.name}
                                        onChange={(event) => updateNodeName(event.target.value)}
                                        className={builderInputClass(isDark, 'mt-1')}
                                    />
                                </div>

                                <div>
                                    <HelpFieldLabel help="Defina a função prática deste agente dentro da equipe. Exemplo: qualificar leads, responder dúvidas ou transferir exceções.">
                                        Responsabilidade
                                    </HelpFieldLabel>
                                    <input
                                        value={selectedNode.data.role}
                                        onChange={(event) => updateNodeData('role', event.target.value)}
                                        className={builderInputClass(isDark, 'mt-1')}
                                    />
                                </div>

                                <div>
                                    <HelpFieldLabel help="Descreva como o agente deve se comportar no papel dele: estilo, postura, nível de detalhe e especialidade.">
                                        Persona / role prompting
                                    </HelpFieldLabel>
                                    <textarea
                                        value={selectedNode.data.description}
                                        onChange={(event) => updateNodeData('description', event.target.value)}
                                        className={builderTextareaClass(isDark, 'mt-1 h-20')}
                                        placeholder="Ex: Você é um especialista consultivo, claro e objetivo, responsável por..."
                                    />
                                </div>

                                <div>
                                    <FieldLabel>Ícone</FieldLabel>
                                    <IconSelect
                                        value={selectedNode.data.iconKey}
                                        kind={selectedNode.data.kind}
                                        onChange={(iconKey) => updateNodeData('iconKey', iconKey)}
                                    />
                                </div>

                                <div>
                                    <HelpFieldLabel help="Explique o resultado principal que este agente deve buscar na conversa. Isso orienta decisões e handoffs.">
                                        Objetivo
                                    </HelpFieldLabel>
                                    <textarea
                                        value={selectedNode.data.goal}
                                        onChange={(event) => updateNodeData('goal', event.target.value)}
                                        className={builderTextareaClass(isDark, 'mt-1 h-24')}
                                    />
                                </div>

                                <div className="grid grid-cols-2 gap-3">
                                    <div>
                                        <FieldLabel>Modelo</FieldLabel>
                                        <div className="relative mt-1">
                                            <select
                                                value={selectedNode.data.model}
                                                onChange={(event) => handleModelChange(event.target.value)}
                                                disabled={!hasReadyModelCatalog}
                                                className={builderSelectClass(isDark)}
                                            >
                                                {!modelOptions.includes(selectedNode.data.model) && selectedNode.data.model && (
                                                    <optgroup label={hasReadyModelCatalog ? 'Modelo salvo indisponível' : 'Modelo salvo'}>
                                                        <option value={selectedNode.data.model}>
                                                            {selectedNode.data.model}
                                                        </option>
                                                    </optgroup>
                                                )}
                                                {!selectedNode.data.model && modelOptions.length === 0 && (
                                                    <option value="">Nenhum modelo disponível</option>
                                                )}
                                                {modelGroups.map((group) => (
                                                    <optgroup key={group.label} label={group.label}>
                                                        {group.models.map((model) => (
                                                            <option key={model} value={model}>{model}</option>
                                                        ))}
                                                    </optgroup>
                                                ))}
                                            </select>
                                            <ChevronDown className={builderChevronClass(isDark)} />
                                        </div>
                                        {(!hasReadyModelCatalog || !modelOptions.includes(selectedNode.data.model)) && (
                                            <div className={`mt-2 rounded-lg border px-3 py-2 text-xs leading-relaxed ${
                                                isDark
                                                    ? 'border-amber-300/20 bg-amber-300/10 text-amber-100'
                                                    : 'border-amber-600/15 bg-amber-50 text-amber-800'
                                            }`}>
                                                <p>
                                                    {hasReadyModelCatalog
                                                        ? 'O modelo salvo não está disponível para a chave desta empresa. Selecione outro modelo antes de salvar.'
                                                        : modelCatalogMessage}
                                                </p>
                                                {modelCatalogStatus !== 'loading' && (
                                                    <button
                                                        type="button"
                                                        onClick={() => navigate('/company/ai-provider')}
                                                        className="mt-1 font-semibold underline underline-offset-2"
                                                    >
                                                        Abrir provedor de IA
                                                    </button>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                    <div>
                                        <FieldLabel>Raciocínio</FieldLabel>
                                        <div className="relative mt-1">
                                            <select
                                                value={getNormalizedReasoningEffort(
                                                    selectedNode.data.model,
                                                    selectedNode.data.reasoningEffort
                                                )}
                                                onChange={(event) => updateNodeData('reasoningEffort', event.target.value)}
                                                className={builderSelectClass(isDark)}
                                            >
                                                {getReasoningOptions(selectedNode.data.model).map((option) => (
                                                    <option key={option.value} value={option.value}>{option.label}</option>
                                                ))}
                                            </select>
                                            <ChevronDown className={builderChevronClass(isDark)} />
                                        </div>
                                    </div>
                                </div>

                                <div>
                                    <FieldLabel>Tom de voz</FieldLabel>
                                    <div className="mt-2 grid grid-cols-2 gap-2">
                                        {TONE_PRESETS.map((preset, presetIndex) => {
                                            const selectedTone = getTonePresetValue(selectedNode.data.tone, selectedNode.data.kind) === preset.value;
                                            const tooltipAlignment = presetIndex % 2 === 0 ? 'left-0' : 'right-0';

                                            return (
                                                <button
                                                    key={preset.id}
                                                    type="button"
                                                    onClick={() => updateNodeData('tone', preset.value)}
                                                    className={`group relative flex min-h-[38px] items-center justify-between gap-2 rounded-xl border px-3 py-2 text-left text-xs font-semibold transition hover:z-50 focus:z-50 ${
                                                        selectedTone
                                                            ? 'border-brand bg-brand text-white'
                                                            : isDark ? 'border-white/10 bg-white/[0.04] text-white/60 hover:bg-white/10 hover:text-white' : 'border-brand/10 bg-white text-brand/60 hover:bg-brand-canvas hover:text-brand'
                                                    }`}
                                                >
                                                    <span className="min-w-0 truncate">{preset.label}</span>
                                                    <span className="flex shrink-0 items-center">
                                                        <Info
                                                            className={`h-3.5 w-3.5 ${selectedTone ? 'text-white/75' : isDark ? 'text-white/35' : 'text-brand/35'}`}
                                                            aria-label={`Sobre o tom ${preset.label}`}
                                                        />
                                                    </span>
                                                    <span
                                                        role="tooltip"
                                                        className={`pointer-events-none absolute bottom-[calc(100%+10px)] ${tooltipAlignment} z-[999] w-[min(18rem,calc(100vw-3rem))] rounded-xl border px-3 py-2 text-left text-[11px] font-normal leading-4 opacity-0 shadow-[0_18px_45px_rgba(2,3,35,0.18)] transition-opacity group-hover:opacity-100 group-focus:opacity-100 ${
                                                            isDark ? 'border-white/10 bg-brand text-white/65' : 'border-brand/10 bg-white text-brand/65'
                                                        }`}
                                                    >
                                                        {preset.value}
                                                    </span>
                                                </button>
                                            );
                                        })}
                                    </div>
                                </div>

                                <div className={builderPanelClass(isDark)}>
                                    <div className="flex items-center justify-between gap-3">
                                        <div className="flex min-w-0 items-center gap-2">
                                            <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ring-1 ${isDark ? 'bg-white/10 text-white ring-white/10' : 'bg-white text-brand ring-brand/10 shadow-sm'}`}>
                                                <Volume2 className="h-4 w-4" />
                                            </span>
                                            <div className="min-w-0">
                                                <FieldLabel>Áudio</FieldLabel>
                                                {voiceOptionsError && (
                                                    <p className="mt-0.5 text-xs text-amber-600">{voiceOptionsError}</p>
                                                )}
                                            </div>
                                        </div>
                                        <button
                                            type="button"
                                            disabled
                                            className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition ${
                                                selectedNode.data.audioEnabled ? 'bg-brand' : isDark ? 'bg-white/20' : 'bg-brand/20'
                                            } disabled:cursor-not-allowed disabled:opacity-55`}
                                            aria-pressed={selectedNode.data.audioEnabled}
                                            aria-label={selectedNode.data.audioEnabled ? 'Áudio legado preservado' : 'Novas ativações de áudio indisponíveis'}
                                            title={selectedNode.data.audioEnabled ? 'Áudio legado preservado; a ativação não pode ser alterada' : 'Novas ativações de áudio ElevenLabs estão indisponíveis'}
                                        >
                                            <span
                                                className={`inline-block h-5 w-5 rounded-full bg-white shadow transition ${
                                                    selectedNode.data.audioEnabled ? 'translate-x-5' : 'translate-x-0.5'
                                                }`}
                                            />
                                        </button>
                                    </div>

                                    <p className={`mt-2 text-xs leading-relaxed ${isDark ? 'text-white/45' : 'text-brand/45'}`}>
                                        {selectedNode.data.audioEnabled
                                            ? 'Áudio legado preservado. A ativação não pode ser desligada ou reativada por esta tela.'
                                            : 'Novas ativações de voz estão indisponíveis. Configurações já salvas continuam preservadas.'}
                                    </p>

                                    {selectedNode.data.audioEnabled && (
                                        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                                            <div>
                                                <FieldLabel>Voz do áudio</FieldLabel>
                                                {voiceOptions.length > 0 ? (
                                                    <div className="relative mt-1">
                                                        <select
                                                            value={selectedNode.data.audioVoiceId || defaultVoiceId}
                                                            onChange={(event) => handleAudioVoiceChange(event.target.value)}
                                                            disabled={loadingVoiceOptions}
                                                            className={builderSelectClass(isDark)}
                                                        >
                                                            {voiceOptions.map((voice) => (
                                                                <option key={voice.voice_id} value={voice.voice_id}>
                                                                    {getVoiceLabel(voice)}
                                                                </option>
                                                            ))}
                                                        </select>
                                                        <ChevronDown className={builderChevronClass(isDark)} />
                                                    </div>
                                                ) : (
                                                    <div className="mt-1 flex items-center gap-2">
                                                        <input
                                                            value={selectedNode.data.audioVoiceId}
                                                            onChange={(event) => updateNodeDataPatch({
                                                                audioVoiceId: event.target.value,
                                                                audioVoiceLabel: event.target.value
                                                            })}
                                                            disabled={loadingVoiceOptions}
                                                            className={builderInputClass(isDark, 'min-w-0 flex-1')}
                                                            placeholder={loadingVoiceOptions ? 'Carregando vozes...' : 'ID da voz'}
                                                        />
                                                        <button
                                                            type="button"
                                                            onClick={() => void loadVoiceOptions()}
                                                            disabled={loadingVoiceOptions}
                                                            className={agentiveIconButtonClass(isDark, 'primary', 'h-10 w-10 shrink-0')}
                                                            aria-label="Recarregar vozes"
                                                            title="Recarregar vozes"
                                                        >
                                                            <RefreshCw className={`h-4 w-4 ${loadingVoiceOptions ? 'animate-spin' : ''}`} />
                                                        </button>
                                                    </div>
                                                )}
                                            </div>
                                            <div>
                                                <FieldLabel>Modelo</FieldLabel>
                                                <div className="relative mt-1">
                                                    <select
                                                        value={normalizeAudioModelId(selectedNode.data.audioModelId || defaultAudioModelId)}
                                                        onChange={(event) => updateNodeDataPatch({ audioModelId: event.target.value })}
                                                        className={builderSelectClass(isDark)}
                                                    >
                                                        {AUDIO_MODEL_OPTIONS.map((option) => (
                                                            <option key={option.value} value={option.value}>{option.label}</option>
                                                        ))}
                                                    </select>
                                                    <ChevronDown className={builderChevronClass(isDark)} />
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                </div>

                                <div>
                                    <HelpFieldLabel help="Use apenas informações específicas deste agente. Dados gerais da empresa, produtos, endereço e políticas devem ficar na configuração global da empresa.">
                                        Contexto do agente
                                    </HelpFieldLabel>
                                    <textarea
                                        value={selectedNode.data.promptContext}
                                        onChange={(event) => updateNodeData('promptContext', event.target.value)}
                                        className={builderTextareaClass(isDark, 'mt-1 h-24')}
                                        placeholder="Ex: quando este agente deve atuar, o que ele precisa considerar nesta função, ou algum detalhe específico do papel dele."
                                    />
                                </div>

                                <PromptListField
                                    label="Instruções"
                                    help="Escreva comandos diretos para este agente seguir. Exemplo: qual abordagem usar, como iniciar, como conduzir e o que priorizar."
                                    values={selectedNode.data.instructions || []}
                                    addLabel="Instrução"
                                    placeholder="Ex: cumprimente o contato de forma breve e avance para o próximo passo"
                                    emptyText="Nenhuma instrução adicionada."
                                    onChange={(values) => updateNodeData('instructions', values)}
                                />

                                <PromptListField
                                    label="Regras de conversa"
                                    help="Defina regras de comportamento durante a conversa. Exemplo: fazer uma pergunta por vez, confirmar dados antes de agir, ou transferir quando fugir do escopo."
                                    values={selectedNode.data.conversationRules || []}
                                    addLabel="Regra"
                                    placeholder="Ex: faça uma pergunta por vez quando precisar coletar dados"
                                    emptyText="Nenhuma regra adicionada."
                                    onChange={(values) => updateNodeData('conversationRules', values)}
                                />

                                <ConstraintListField
                                    values={selectedNode.data.constraints || []}
                                    onChange={(values) => updateNodeData('constraints', values)}
                                />

                                <PromptListField
                                    label="Condições de falha"
                                    help="Defina quando este agente deve parar, reconhecer que não consegue resolver ou transferir para outro agente/humano."
                                    values={selectedNode.data.failureConditions || []}
                                    addLabel="Condição"
                                    placeholder="Ex: o contato pediu algo fora do escopo deste agente"
                                    emptyText="Nenhuma condição de falha adicionada."
                                    onChange={(values) => updateNodeData('failureConditions', values)}
                                />

                                <CustomGuardrailListField
                                    values={selectedNode.data.customGuardrails || []}
                                    availableTools={selectedNode.data.tools || []}
                                    onChange={(values) => updateNodeData('customGuardrails', values)}
                                />

                                <div className={builderPanelClass(isDark)}>
                                    <div className="mb-3 flex items-center justify-between gap-3">
                                        <div>
                                            <FieldLabel>Few-shot examples</FieldLabel>
                                            <p className={builderMutedTextClass(isDark, 'mt-1 text-xs')}>Adicione exemplos só quando quiser ensinar um padrão específico de resposta.</p>
                                        </div>
                                        <button
                                            onClick={addFewShot}
                                            className={agentiveSecondaryButtonClass(isDark, 'px-2.5 py-1.5 text-xs')}
                                        >
                                            <Plus className="h-3.5 w-3.5" />
                                            Exemplo
                                        </button>
                                    </div>

                                    {(selectedNode.data.fewShots || []).length === 0 ? (
                                        <div className={builderEmptyClass(isDark, 'py-3 text-xs')}>
                                            Nenhum exemplo adicionado.
                                        </div>
                                    ) : (
                                        <div className="space-y-2">
                                            {selectedNode.data.fewShots.map((example, index) => {
                                                const fewShotKey = getFewShotKey(index);
                                                const isExpanded = expandedFewShots[fewShotKey] === true;

                                                return (
                                                    <div key={`few-shot-${index}`} className={builderSurfaceClass(isDark, 'overflow-hidden')}>
                                                        <div className="flex items-center gap-2 px-3 py-2">
                                                            <button
                                                                type="button"
                                                                onClick={() => toggleFewShot(index)}
                                                                className="flex min-w-0 flex-1 items-center gap-2 text-left"
                                                            >
                                                                <ChevronDown className={`h-4 w-4 shrink-0 transition ${isExpanded ? '' : '-rotate-90'} ${isDark ? 'text-white/40' : 'text-brand/40'}`} />
                                                                <div className="min-w-0">
                                                                    <p className="text-xs font-semibold">Exemplo {index + 1}</p>
                                                                    <p className={builderMutedTextClass(isDark, 'truncate text-[11px]')}>{getFewShotSummary(example)}</p>
                                                                </div>
                                                            </button>
                                                            <button
                                                                type="button"
                                                                onClick={() => removeFewShot(index)}
                                                                className={agentiveIconButtonClass(isDark, 'danger', 'min-h-8 min-w-8 p-1.5')}
                                                                title="Remover exemplo"
                                                            >
                                                                <Trash2 className="h-3.5 w-3.5" />
                                                            </button>
                                                        </div>

                                                        {isExpanded && (
                                                            <div className={`border-t p-3 ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
                                                                <textarea
                                                                    value={example.context || ''}
                                                                    onChange={(event) => updateFewShot(index, 'context', event.target.value)}
                                                                    className={builderTextareaClass(isDark, 'mb-2 h-16 text-xs')}
                                                                    placeholder="Contexto opcional do exemplo"
                                                                />
                                                                <textarea
                                                                    value={example.user}
                                                                    onChange={(event) => updateFewShot(index, 'user', event.target.value)}
                                                                    className={builderTextareaClass(isDark, 'mb-2 h-16 text-xs')}
                                                                    placeholder="Mensagem do usuário"
                                                                />
                                                                <textarea
                                                                    value={example.assistant}
                                                                    onChange={(event) => updateFewShot(index, 'assistant', event.target.value)}
                                                                    className={builderTextareaClass(isDark, 'h-16 text-xs')}
                                                                    placeholder="Resposta ideal do agente"
                                                                />
                                                            </div>
                                                        )}
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    )}
                                </div>

                                <div>
                                    <div className="mb-2 flex items-center gap-2">
                                        <ClipboardList className={`h-4 w-4 ${isDark ? 'text-white/50' : 'text-brand/50'}`} />
                                        <FieldLabel>Ferramentas</FieldLabel>
                                    </div>
                                    <div className="grid grid-cols-1 gap-2">
                                        {TOOL_OPTIONS.map((tool) => {
                                            const isSelected = selectedToolIds.includes(tool.id);
                                            const isConfigurable = tool.id === CALENDAR_TOOL_ID
                                                || tool.id === CRM_PIPELINE_TOOL_ID
                                                || tool.id === DYNAMIC_CRM_FOLLOWUP_TOOL_ID
                                                || tool.id === WHATSAPP_CONTACT_CARD_TOOL_ID
                                                || tool.id === WHATSAPP_SCHEDULED_FOLLOWUP_TOOL_ID;

                                            return (
                                                <div
                                                    key={tool.id}
                                                    className={`flex items-center gap-2 rounded-xl border p-1 transition ${isSelected
                                                        ? 'border-brand bg-brand text-white shadow-sm shadow-brand/15'
                                                        : isDark ? 'border-white/10 bg-white/[0.04] text-white/60 hover:bg-white/10 hover:text-white' : 'border-brand/10 bg-white text-brand/60 hover:bg-brand-canvas hover:text-brand'
                                                        }`}
                                                >
                                                    <button
                                                        type="button"
                                                        onClick={() => toggleToolValue(tool.id)}
                                                        className="flex min-h-9 min-w-0 flex-1 items-center justify-between gap-2 rounded-md px-2 text-left text-sm"
                                                    >
                                                        <span className="truncate">{tool.label}</span>
                                                        {isSelected && <Check className="h-4 w-4 shrink-0" />}
                                                    </button>
                                                    {isSelected && isConfigurable && (
                                                        <button
                                                            type="button"
                                                            onClick={() => setConfiguringToolId(tool.id)}
                                                            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white/10 text-white transition hover:bg-white/20"
                                                            title="Configurar ferramenta"
                                                        >
                                                            <Settings className="h-4 w-4" />
                                                        </button>
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>

                                <button
                                    onClick={handlePreview}
                                    disabled={previewing}
                                    className={agentiveSecondaryButtonClass(isDark, 'w-full')}
                                >
                                    {previewing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                                    Pré-visualizar prompt SDK
                                </button>

                                {preview && (
                                    <pre className={builderPanelClass(isDark, `max-h-72 overflow-auto text-[11px] leading-5 ${isDark ? 'text-white/70' : 'text-brand/70'}`)}>
                                        {preview}
                                    </pre>
                                )}
                            </div>
                            )
                        ) : selectedEdge ? (
                            <div className="space-y-4">
                                <div className={builderPanelClass(isDark)}>
                                    <div className="flex items-center gap-2 text-sm font-medium">
                                        <GitBranch className={`h-4 w-4 ${isDark ? 'text-white/55' : 'text-brand/55'}`} />
                                        Conexão entre agentes
                                    </div>
                                    <p className={builderMutedTextClass(isDark, 'mt-1 text-xs')}>Defina quando o handoff deve acontecer.</p>
                                </div>

                                <div>
                                    <FieldLabel>Tipo</FieldLabel>
                                    <select
                                        value={selectedEdge.data?.mode || 'handoff'}
                                        onChange={(event) => updateEdgeData('mode', event.target.value)}
                                        className={builderSelectClass(isDark, 'mt-1')}
                                    >
                                        <option value="handoff">Handoff</option>
                                        <option value="supervision">Supervisão</option>
                                        <option value="escalation">Escalonamento</option>
                                    </select>
                                </div>

                                <div>
                                    <FieldLabel>Regra</FieldLabel>
                                    <textarea
                                        value={selectedEdge.data?.rule || String(selectedEdge.label || '')}
                                        onChange={(event) => updateEdgeData('rule', event.target.value)}
                                        className={builderTextareaClass(isDark, 'mt-1 h-28')}
                                    />
                                </div>
                            </div>
                        ) : (
                            <div className={builderEmptyClass(isDark, 'flex h-full flex-col items-center justify-center px-6 text-center')}>
                                <MessageCircle className={`mb-3 h-8 w-8 ${isDark ? 'text-white/35' : 'text-brand/35'}`} />
                                <p className={`text-sm font-medium ${isDark ? 'text-white/70' : 'text-brand/70'}`}>Selecione um agente ou conexão</p>
                                <p className="mt-1 text-xs">O inspector mostra prompt, tools e regras de handoff.</p>
                            </div>
                        )}
                    </div>
                        </>
                    )}
                </aside>
            </div>
            </section>

            {configuringToolId === CALENDAR_TOOL_ID && selectedNode && selectedToolIds.includes(CALENDAR_TOOL_ID) && (
                <div className="fixed inset-0 z-[80] flex items-center justify-center bg-brand/60 px-3 py-4 backdrop-blur-sm">
                    <div className={`flex max-h-[calc(100vh-2rem)] w-full max-w-3xl flex-col overflow-hidden rounded-[24px] border shadow-[0_28px_90px_rgba(2,3,35,0.34)] ${isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand'}`}>
                        <div className={`flex items-start justify-between gap-4 border-b px-5 py-4 ${isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-brand-canvas'}`}>
                            <div className="flex min-w-0 items-start gap-3">
                                <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
                                    <CalendarClock className="h-5 w-5" />
                                </div>
                                <div className="min-w-0">
                                    <p className={`text-[10px] font-bold uppercase tracking-[0.16em] ${isDark ? 'text-white/40' : 'text-brand/40'}`}>Tool</p>
                                    <h2 className="text-lg font-semibold leading-tight">Agendamento de lead</h2>
                                    <p className={builderMutedTextClass(isDark, 'mt-1 text-sm leading-5')}>
                                        {selectedNode.data.name}
                                    </p>
                                </div>
                            </div>
                            <button
                                type="button"
                                onClick={() => setConfiguringToolId(null)}
                                className={agentiveIconButtonClass(isDark)}
                                title="Fechar"
                            >
                                <X className="h-4 w-4" />
                            </button>
                        </div>

                        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4 sm:p-5">
                            <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_220px]">
                                <div className={builderPanelClass(isDark)}>
                                    <div className="flex items-center gap-2">
                                        <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ${isDark ? 'bg-white/[0.07] text-white/60' : 'bg-white text-brand/60 ring-1 ring-brand/10'}`}>
                                            <CalendarClock className="h-4 w-4" />
                                        </span>
                                        <FieldLabel>Agenda vinculada</FieldLabel>
                                    </div>
                                    <div className="relative mt-3">
                                        <select
                                            value={selectedCalendarSettings.agendaId ?? ''}
                                            onChange={(event) => {
                                                const nextAgendaId = toNullableId(event.target.value);
                                                const nextAgenda = nextAgendaId
                                                    ? calendarAgendas.find((agenda) => Number(agenda.id) === Number(nextAgendaId))
                                                    : undefined;
                                                const nextCanCreateMeet = nextAgenda
                                                    ? Boolean(nextAgenda.google_calendar_id)
                                                    : googleLinkedAgendas.length > 0;
                                                updateCalendarToolSettings({
                                                    agendaId: nextAgendaId,
                                                    createGoogleMeet: nextCanCreateMeet ? selectedCalendarSettings.createGoogleMeet : false
                                                });
                                            }}
                                            disabled={loadingCalendarAgendas}
                                            className={builderSelectClass(isDark)}
                                        >
                                            <option value="">Escolher durante a conversa</option>
                                            {calendarAgendas.map((agenda) => (
                                                <option key={agenda.id} value={agenda.id}>
                                                    {agenda.name}
                                                </option>
                                            ))}
                                        </select>
                                        <ChevronDown className={builderChevronClass(isDark, 'right-3')} />
                                    </div>
                                    <p className={builderMutedTextClass(isDark, 'mt-2 text-[11px] leading-4')}>
                                        {loadingCalendarAgendas
                                            ? 'Carregando agendas...'
                                            : calendarAgendas.length === 0
                                                ? 'Nenhuma agenda ativa encontrada no menu Agenda.'
                                                : 'Use uma agenda fixa ou deixe o agente pedir a agenda quando houver mais de uma.'}
                                    </p>
                                </div>

                                <div className={builderPanelClass(isDark)}>
                                    <FieldLabel>Horários sugeridos</FieldLabel>
                                    <div className="mt-3 grid grid-cols-4 gap-1.5 lg:grid-cols-2">
                                        {CALENDAR_SUGGESTION_OPTIONS.map((option) => {
                                            const active = selectedCalendarSettings.maxSuggestions === option;

                                            return (
                                                <button
                                                    key={option}
                                                    type="button"
                                                    onClick={() => updateCalendarToolSettings({ maxSuggestions: option })}
                                                    className={`min-h-10 rounded-xl border px-3 text-sm font-semibold transition ${active
                                                        ? isDark ? 'border-white/15 bg-white/10 text-white' : 'border-brand bg-brand text-white shadow-sm shadow-brand/15'
                                                        : isDark ? 'border-white/10 bg-white/[0.04] text-white/60 hover:bg-white/10 hover:text-white' : 'border-brand/10 bg-white text-brand/60 hover:bg-brand-canvas hover:text-brand'
                                                        }`}
                                                >
                                                    {option}
                                                </button>
                                            );
                                        })}
                                    </div>
                                    <p className={builderMutedTextClass(isDark, 'mt-2 text-[11px] leading-4')}>
                                        Quantidade de opções por resposta.
                                    </p>
                                </div>
                            </div>

                            <div className={builderPanelClass(isDark)}>
                                <FieldLabel>Ações permitidas</FieldLabel>
                                <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                                    {CALENDAR_TOOL_ACTION_OPTIONS.map((action) => {
                                        const checked = selectedCalendarSettings.allowedActions.includes(action.value);
                                        const isLastChecked = checked && selectedCalendarSettings.allowedActions.length === 1;

                                        return (
                                            <label
                                                key={action.value}
                                                className={`flex min-h-[92px] items-start gap-3 rounded-2xl border p-3 text-sm transition ${checked
                                                    ? isDark ? 'border-white/15 bg-white/10 text-white' : 'border-brand bg-brand text-white shadow-sm shadow-brand/15'
                                                    : isDark ? 'border-white/10 bg-white/[0.03] text-white/65 hover:bg-white/[0.06]' : 'border-brand/10 bg-white text-brand/65 hover:bg-brand-canvas hover:text-brand'
                                                    }`}
                                            >
                                                <input
                                                    type="checkbox"
                                                    checked={checked}
                                                    disabled={isLastChecked}
                                                    onChange={(event) => toggleCalendarToolAction(action.value, event.target.checked)}
                                                    className={builderCheckboxClass(isDark, checked ? 'mt-0.5 border-white/40' : 'mt-0.5')}
                                                />
                                                <span className="min-w-0">
                                                    <span className="block font-semibold">{action.label}</span>
                                                    <span className={`mt-1 block text-xs leading-4 ${checked ? 'text-current opacity-70' : isDark ? 'text-white/45' : 'text-brand/45'}`}>
                                                        {action.description}
                                                    </span>
                                                </span>
                                            </label>
                                        );
                                    })}
                                </div>
                            </div>

                            {selectedCalendarSettings.allowedActions.some((action) => action !== 'find_slots') && (
                                <label className={builderToggleCardClass(isDark, selectedCalendarSettings.requireConfirmation)}>
                                    <input
                                        type="checkbox"
                                        checked={selectedCalendarSettings.requireConfirmation}
                                        onChange={(event) => updateCalendarToolSettings({ requireConfirmation: event.target.checked })}
                                        className={builderCheckboxClass(isDark, 'mt-1')}
                                    />
                                    <span className="min-w-0">
                                        <span className="block font-semibold">Exigir confirmação explícita do lead antes de executar ações</span>
                                        <span className={builderMutedTextClass(isDark, 'mt-1 block text-xs leading-5')}>
                                            Mantém consultas livres, mas bloqueia criar, reagendar ou cancelar sem confirmação clara.
                                        </span>
                                    </span>
                                </label>
                            )}

                            {selectedCalendarSettings.allowedActions.includes('create_appointment') && (
                                <label className={builderToggleCardClass(isDark, selectedCalendarSettings.createGoogleMeet && canCreateGoogleMeet, !canCreateGoogleMeet ? 'opacity-75' : '')}>
                                    <input
                                        type="checkbox"
                                        checked={selectedCalendarSettings.createGoogleMeet && canCreateGoogleMeet}
                                        disabled={!canCreateGoogleMeet}
                                        onChange={(event) => updateCalendarToolSettings({ createGoogleMeet: event.target.checked })}
                                        className={builderCheckboxClass(isDark, 'mt-1')}
                                    />
                                    <span className="min-w-0">
                                        <span className="flex items-center gap-2 font-semibold">
                                            <Video className="h-4 w-4" />
                                            Criar Google Meet e enviar link ao lead
                                        </span>
                                        <span className={builderMutedTextClass(isDark, 'mt-1 block text-xs leading-5')}>
                                            {canCreateGoogleMeet
                                                ? `Usa o Google Agenda vinculado: ${googleMeetStatusLabel}.`
                                                : `${googleMeetStatusLabel}. Vincule uma agenda no menu Agenda para habilitar.`}
                                        </span>
                                    </span>
                                </label>
                            )}

                            <div className={builderPanelClass(isDark)}>
                                <HelpFieldLabel help="Essa regra entra no prompt do agente e define em quais momentos ele deve chamar a tool de agendamento.">
                                    Quando usar
                                </HelpFieldLabel>
                                <textarea
                                    value={selectedCalendarSettings.whenToUse}
                                    onChange={(event) => updateCalendarToolSettings({ whenToUse: event.target.value })}
                                    className={builderTextareaClass(isDark, 'mt-2 h-28')}
                                    placeholder="Ex: use quando o lead pedir disponibilidade, escolher um horário, quiser remarcar ou cancelar."
                                />
                            </div>
                        </div>

                        <div className={`flex items-center justify-end gap-2 border-t px-5 py-4 ${isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-brand-canvas'}`}>
                            <button
                                type="button"
                                onClick={() => setConfiguringToolId(null)}
                                className={agentivePrimaryButtonClass('px-4')}
                            >
                                <Check className="h-4 w-4" />
                                Concluir
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {configuringToolId === CRM_PIPELINE_TOOL_ID && selectedNode && selectedToolIds.includes(CRM_PIPELINE_TOOL_ID) && (
                <div className="fixed inset-0 z-[80] flex items-center justify-center bg-brand/60 px-3 py-4 backdrop-blur-sm">
                    <div className={`flex max-h-[calc(100vh-2rem)] w-full max-w-4xl flex-col overflow-hidden rounded-[24px] border shadow-[0_28px_90px_rgba(2,3,35,0.34)] ${isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand'}`}>
                        <div className={`flex items-start justify-between gap-4 border-b px-5 py-4 ${isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-brand-canvas'}`}>
                            <div className="flex min-w-0 items-start gap-3">
                                <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
                                    <Target className="h-5 w-5" />
                                </div>
                                <div className="min-w-0">
                                    <p className={`text-[10px] font-bold uppercase tracking-[0.16em] ${isDark ? 'text-white/40' : 'text-brand/40'}`}>Tool</p>
                                    <h2 className="text-lg font-semibold leading-tight">Mover lead no CRM</h2>
                                    <p className={builderMutedTextClass(isDark, 'mt-1 text-sm leading-5')}>
                                        {selectedNode.data.name}
                                    </p>
                                </div>
                            </div>
                            <button
                                type="button"
                                onClick={() => setConfiguringToolId(null)}
                                className={agentiveIconButtonClass(isDark)}
                                title="Fechar"
                            >
                                <X className="h-4 w-4" />
                            </button>
                        </div>

                        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4 sm:p-5">
                            <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(260px,0.65fr)]">
                                <div className={builderPanelClass(isDark)}>
                                    <div className="flex items-center gap-2">
                                        <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ${isDark ? 'bg-white/[0.07] text-white/60' : 'bg-white text-brand/60 ring-1 ring-brand/10'}`}>
                                            <Target className="h-4 w-4" />
                                        </span>
                                        <FieldLabel>Pipeline</FieldLabel>
                                    </div>
                                    <div className="relative mt-3">
                                        <select
                                            value={selectedCrmSettings.pipelineId ?? selectedCrmPipeline?.id ?? ''}
                                            onChange={(event) => {
                                                const nextPipelineId = toNullableId(event.target.value);
                                                const nextPipeline = nextPipelineId
                                                    ? crmPipelines.find((pipeline) => Number(pipeline.id) === Number(nextPipelineId)) || null
                                                    : crmPipelines.find((pipeline) => pipeline.is_active !== false) || crmPipelines[0] || null;
                                                updateCrmPipelineToolSettings({
                                                    pipelineId: nextPipelineId,
                                                    stageRules: nextPipeline
                                                        ? getCrmStageRulesForPipeline(selectedCrmSettings, nextPipeline.stages || [])
                                                        : []
                                                });
                                            }}
                                            disabled={loadingCrmPipelines}
                                            className={builderSelectClass(isDark)}
                                        >
                                            <option value="" disabled hidden>
                                                Selecione um pipeline
                                            </option>
                                            {crmPipelines.map((pipeline) => (
                                                <option key={pipeline.id} value={pipeline.id}>
                                                    {pipeline.name}
                                                </option>
                                            ))}
                                        </select>
                                        <ChevronDown className={builderChevronClass(isDark, 'right-3')} />
                                    </div>
                                    <p className={builderMutedTextClass(isDark, 'mt-2 text-[11px] leading-4')}>
                                        {loadingCrmPipelines
                                            ? 'Carregando pipelines...'
                                            : selectedCrmPipeline
                                                ? `${selectedCrmStages.length} etapa(s) encontradas.`
                                                : 'Nenhum pipeline ativo encontrado no CRM.'}
                                    </p>
                                </div>

                                <div className={builderPanelClass(isDark)}>
                                    <HelpFieldLabel help="Essa regra entra no prompt do agente antes de ele usar a tool do CRM.">
                                        Quando usar
                                    </HelpFieldLabel>
                                    <textarea
                                        value={selectedCrmSettings.whenToUse}
                                        onChange={(event) => updateCrmPipelineToolSettings({ whenToUse: event.target.value })}
                                        className={builderTextareaClass(isDark, 'mt-2 h-28')}
                                        placeholder="Ex: use quando o lead confirmar interesse, desistir, pedir retorno ou revelar que não é o perfil certo."
                                    />
                                </div>
                            </div>

                            <div className={builderPanelClass(isDark)}>
                                <div className="flex items-center justify-between gap-3">
                                    <FieldLabel>Regras por etapa</FieldLabel>
                                    <span className={builderMutedTextClass(isDark, 'text-[11px]')}>
                                        {selectedCrmStageRules.length} etapa(s)
                                    </span>
                                </div>

                                {selectedCrmStageRules.length === 0 ? (
                                    <div className={builderEmptyClass(isDark, 'mt-3 px-4 py-6 text-center text-sm')}>
                                        Configure um pipeline no CRM para liberar regras de avanço e recuo.
                                    </div>
                                ) : (
                                    <div className="mt-3 space-y-3">
                                        {selectedCrmStages.map((stage) => {
                                            const rule = getCrmStageRule(selectedCrmSettings, stage);
                                            return (
                                                <div
                                                    key={stage.id}
                                                    className={`rounded-2xl border p-3 ${isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-white'}`}
                                                >
                                                    <div className="flex items-center gap-2">
                                                        <span
                                                            className="h-3 w-3 shrink-0 rounded-full"
                                                            style={{ backgroundColor: stage.color || '#3B82F6' }}
                                                        />
                                                        <p className="min-w-0 truncate text-sm font-semibold">{stage.name}</p>
                                                    </div>
                                                    <div className="mt-3 grid gap-3 md:grid-cols-2">
                                                        <div>
                                                            <FieldLabel>Por que avançar</FieldLabel>
                                                            <textarea
                                                                value={rule.advanceRule}
                                                                onChange={(event) => updateCrmStageRule(stage, 'advanceRule', event.target.value)}
                                                                className={builderTextareaClass(isDark, 'mt-1 h-24')}
                                                                placeholder="Ex: lead confirmou orçamento, urgência e quer seguir para proposta."
                                                            />
                                                        </div>
                                                        <div>
                                                            <FieldLabel>Por que recuar</FieldLabel>
                                                            <textarea
                                                                value={rule.recedeRule}
                                                                onChange={(event) => updateCrmStageRule(stage, 'recedeRule', event.target.value)}
                                                                className={builderTextareaClass(isDark, 'mt-1 h-24')}
                                                                placeholder="Ex: lead voltou a ter dúvida básica ou perdeu critério desta etapa."
                                                            />
                                                        </div>
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                )}
                            </div>
                        </div>

                        <div className={`flex items-center justify-end gap-2 border-t px-5 py-4 ${isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-brand-canvas'}`}>
                            <button
                                type="button"
                                onClick={() => setConfiguringToolId(null)}
                                className={agentivePrimaryButtonClass('px-4')}
                            >
                                <Check className="h-4 w-4" />
                                Concluir
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {configuringToolId === DYNAMIC_CRM_FOLLOWUP_TOOL_ID && selectedNode && selectedToolIds.includes(DYNAMIC_CRM_FOLLOWUP_TOOL_ID) && (
                <div className="fixed inset-0 z-[80] flex items-center justify-center bg-brand/60 px-3 py-4 backdrop-blur-sm">
                    <div className={`flex max-h-[calc(100vh-2rem)] w-full max-w-5xl flex-col overflow-hidden rounded-[24px] border shadow-[0_28px_90px_rgba(2,3,35,0.34)] ${isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand'}`}>
                        <div className={`flex items-start justify-between gap-4 border-b px-5 py-4 ${isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-brand-canvas'}`}>
                            <div className="flex min-w-0 items-start gap-3">
                                <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
                                    <MessageCircle className="h-5 w-5" />
                                </div>
                                <div className="min-w-0">
                                    <p className={`text-[10px] font-bold uppercase tracking-[0.16em] ${isDark ? 'text-white/40' : 'text-brand/40'}`}>Tool</p>
                                    <h2 className="text-lg font-semibold leading-tight">Follow-up dinâmico CRM</h2>
                                    <p className={builderMutedTextClass(isDark, 'mt-1 text-sm leading-5')}>
                                        {selectedNode.data.name}
                                    </p>
                                </div>
                            </div>
                            <button
                                type="button"
                                onClick={() => setConfiguringToolId(null)}
                                className={agentiveIconButtonClass(isDark)}
                                title="Fechar"
                            >
                                <X className="h-4 w-4" />
                            </button>
                        </div>

                        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4 sm:p-5">
                            <div className="grid gap-3 lg:grid-cols-[minmax(260px,0.45fr)_minmax(0,1fr)]">
                                <div className={builderPanelClass(isDark)}>
                                    <div className="flex items-center gap-2">
                                        <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ${isDark ? 'bg-white/[0.07] text-white/60' : 'bg-white text-brand/60 ring-1 ring-brand/10'}`}>
                                            <Target className="h-4 w-4" />
                                        </span>
                                        <FieldLabel>Pipeline</FieldLabel>
                                    </div>
                                    <div className="relative mt-3">
                                        <select
                                            value={selectedDynamicCrmFollowupSettings.pipelineId ?? selectedDynamicFollowupPipeline?.id ?? ''}
                                            onChange={(event) => {
                                                const nextPipelineId = toNullableId(event.target.value);
                                                updateDynamicCrmFollowupToolSettings({
                                                    pipelineId: nextPipelineId,
                                                    targetStageIds: []
                                                });
                                            }}
                                            disabled={loadingCrmPipelines}
                                            className={builderSelectClass(isDark)}
                                        >
                                            <option value="" disabled hidden>
                                                Selecione um pipeline
                                            </option>
                                            {crmPipelines.map((pipeline) => (
                                                <option key={pipeline.id} value={pipeline.id}>
                                                    {pipeline.name}
                                                </option>
                                            ))}
                                        </select>
                                        <ChevronDown className={builderChevronClass(isDark, 'right-3')} />
                                    </div>
                                    <p className={builderMutedTextClass(isDark, 'mt-2 text-[11px] leading-4')}>
                                        {loadingCrmPipelines
                                            ? 'Carregando pipelines...'
                                            : selectedDynamicFollowupPipeline
                                                ? `${selectedDynamicFollowupStages.length} etapa(s) encontradas.`
                                                : 'Nenhum pipeline ativo encontrado no CRM.'}
                                    </p>
                                </div>

                                <div className={builderPanelClass(isDark)}>
                                    <div className="flex items-center justify-between gap-3">
                                        <FieldLabel>Parar quando chegar em</FieldLabel>
                                        <span className={builderMutedTextClass(isDark, 'text-[11px]')}>
                                            {selectedDynamicCrmFollowupSettings.targetStageIds.length} selecionada(s)
                                        </span>
                                    </div>

                                    {selectedDynamicFollowupStages.length === 0 ? (
                                        <div className={builderEmptyClass(isDark, 'mt-3 px-4 py-6 text-center text-sm')}>
                                            Selecione um pipeline com etapas para definir o objetivo.
                                        </div>
                                    ) : (
                                        <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                                            {selectedDynamicFollowupStages.map((stage) => {
                                                const checked = selectedDynamicCrmFollowupSettings.targetStageIds.includes(Number(stage.id));
                                                return (
                                                    <label
                                                        key={stage.id}
                                                        className={builderToggleCardClass(isDark, checked, 'min-h-[72px]')}
                                                    >
                                                        <input
                                                            type="checkbox"
                                                            checked={checked}
                                                            onChange={(event) => toggleDynamicFollowupTargetStage(Number(stage.id), event.target.checked)}
                                                            className={builderCheckboxClass(isDark, 'mt-1')}
                                                        />
                                                        <span className="flex min-w-0 items-center gap-2">
                                                            <span
                                                                className="h-3 w-3 shrink-0 rounded-full"
                                                                style={{ backgroundColor: stage.color || '#3B82F6' }}
                                                            />
                                                            <span className="min-w-0 truncate text-sm font-semibold">{stage.name}</span>
                                                        </span>
                                                    </label>
                                                );
                                            })}
                                        </div>
                                    )}

                                    <label className={builderToggleCardClass(isDark, selectedDynamicCrmFollowupSettings.stopOnAppointmentCreated, 'mt-3')}>
                                        <input
                                            type="checkbox"
                                            checked={selectedDynamicCrmFollowupSettings.stopOnAppointmentCreated}
                                            onChange={(event) => updateDynamicCrmFollowupToolSettings({ stopOnAppointmentCreated: event.target.checked })}
                                            className={builderCheckboxClass(isDark, 'mt-1')}
                                        />
                                        <span className="min-w-0">
                                            <span className="block font-semibold">Parar quando houver agendamento</span>
                                            <span className={builderMutedTextClass(isDark, 'mt-1 block text-xs leading-5')}>
                                                Conclui o follow-up dinâmico quando o lead tiver um agendamento ativo.
                                            </span>
                                        </span>
                                    </label>
                                </div>
                            </div>

                            <div className={builderPanelClass(isDark, 'space-y-4')}>
                                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                                    <div className="flex min-w-0 items-start gap-3">
                                        <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${isDark ? 'bg-white/[0.07] text-white/60' : 'bg-white text-brand/60 ring-1 ring-brand/10'}`}>
                                            <CalendarClock className="h-4 w-4" />
                                        </span>
                                        <div className="min-w-0">
                                            <FieldLabel>Janela de envio</FieldLabel>
                                            <p className={builderMutedTextClass(isDark, 'mt-1 text-xs leading-5')}>
                                                {selectedDynamicFollowupDeliveryWindow.enabled
                                                    ? `${selectedDynamicFollowupDeliveryWindow.startTime}-${selectedDynamicFollowupDeliveryWindow.endTime} em ${selectedDynamicFollowupWeekdaySummary || 'dias selecionados'}`
                                                    : 'Sem restrição de horário'}
                                            </p>
                                        </div>
                                    </div>
                                    <label className={`inline-flex h-10 shrink-0 items-center gap-2 rounded-xl border px-3 text-sm font-semibold ${selectedDynamicFollowupDeliveryWindow.enabled
                                        ? isDark
                                            ? 'border-white/20 bg-white/10 text-white'
                                            : 'border-brand/20 bg-white text-brand'
                                        : isDark
                                            ? 'border-white/10 bg-white/[0.04] text-white/55'
                                            : 'border-brand/10 bg-white text-brand/55'
                                    }`}>
                                        <input
                                            type="checkbox"
                                            checked={selectedDynamicFollowupDeliveryWindow.enabled}
                                            onChange={(event) => updateDynamicFollowupDeliveryWindow({ enabled: event.target.checked })}
                                            className={builderCheckboxClass(isDark)}
                                        />
                                        Ativa
                                    </label>
                                </div>

                                {selectedDynamicFollowupDeliveryWindow.enabled && (
                                    <div className="grid gap-3">
                                        <div className="grid gap-3 md:grid-cols-[minmax(220px,1fr)_minmax(120px,0.45fr)_minmax(120px,0.45fr)]">
                                            <div>
                                                <FieldLabel>Fuso</FieldLabel>
                                                <input
                                                    value={selectedDynamicFollowupDeliveryWindow.timezone}
                                                    onChange={(event) => updateDynamicFollowupDeliveryWindow({ timezone: event.target.value })}
                                                    className={builderInputClass(isDark, 'mt-2')}
                                                    placeholder="America/Sao_Paulo"
                                                />
                                            </div>
                                            <div>
                                                <FieldLabel>Início</FieldLabel>
                                                <input
                                                    type="time"
                                                    value={selectedDynamicFollowupDeliveryWindow.startTime}
                                                    onChange={(event) => updateDynamicFollowupDeliveryWindow({ startTime: event.target.value })}
                                                    className={builderInputClass(isDark, 'mt-2')}
                                                />
                                            </div>
                                            <div>
                                                <FieldLabel>Fim</FieldLabel>
                                                <input
                                                    type="time"
                                                    value={selectedDynamicFollowupDeliveryWindow.endTime}
                                                    onChange={(event) => updateDynamicFollowupDeliveryWindow({ endTime: event.target.value })}
                                                    className={builderInputClass(isDark, 'mt-2')}
                                                />
                                            </div>
                                        </div>

                                        <div>
                                            <FieldLabel>Dias da semana</FieldLabel>
                                            <div className="mt-2 grid gap-2 sm:grid-cols-4 lg:grid-cols-7">
                                                {DYNAMIC_FOLLOWUP_WEEKDAYS.map((day) => {
                                                    const checked = selectedDynamicFollowupDeliveryWindow.allowedWeekdays.includes(day.value);
                                                    const disabled = checked && selectedDynamicFollowupDeliveryWindow.allowedWeekdays.length === 1;
                                                    return (
                                                        <label
                                                            key={`dynamic-followup-window-${day.value}`}
                                                            className={`flex min-h-[42px] items-center justify-center gap-2 rounded-xl border px-2 text-xs font-semibold transition ${checked
                                                                ? isDark
                                                                    ? 'border-white/20 bg-white/10 text-white'
                                                                    : 'border-brand/20 bg-white text-brand shadow-sm'
                                                                : isDark
                                                                    ? 'border-white/10 bg-white/[0.03] text-white/50 hover:bg-white/[0.06]'
                                                                    : 'border-brand/10 bg-white text-brand/50 hover:border-brand/20'
                                                            } ${disabled ? 'cursor-not-allowed opacity-70' : 'cursor-pointer'}`}
                                                        >
                                                            <input
                                                                type="checkbox"
                                                                checked={checked}
                                                                disabled={disabled}
                                                                onChange={(event) => toggleDynamicFollowupDeliveryWeekday(day.value, event.target.checked)}
                                                                className={builderCheckboxClass(isDark, 'h-3.5 w-3.5')}
                                                            />
                                                            {day.short}
                                                        </label>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>

                            <div className={builderPanelClass(isDark)}>
                                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                                    <div>
                                        <FieldLabel>Passos</FieldLabel>
                                        <p className={builderMutedTextClass(isDark, 'mt-1 text-xs leading-5')}>
                                            A primeira etapa conta da entrada no CRM. As próximas contam da mensagem anterior.
                                        </p>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={addDynamicFollowupStep}
                                        className={agentiveSecondaryButtonClass(isDark, 'shrink-0 px-3')}
                                    >
                                        <Plus className="h-4 w-4" />
                                        Adicionar
                                    </button>
                                </div>

                                <div className="mt-3 space-y-3">
                                    {selectedDynamicCrmFollowupSettings.steps.map((step, index) => (
                                        <div
                                            key={`dynamic-followup-step-${index}`}
                                            className={`rounded-2xl border p-3 sm:p-4 ${isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-white'}`}
                                        >
                                            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                                                <div className="flex min-w-0 items-center gap-3">
                                                    <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-sm font-bold ${isDark ? 'bg-white/[0.08] text-white/80' : 'bg-brand-canvas text-brand'}`}>
                                                        {index + 1}
                                                    </span>
                                                    <div className="min-w-0">
                                                        <p className="truncate text-sm font-semibold">Mensagem {index + 1}</p>
                                                        <p className={builderMutedTextClass(isDark, 'mt-0.5 text-[11px] leading-4')}>
                                                            {index === 0 ? 'Conta a partir da entrada no CRM' : 'Conta a partir da mensagem anterior'}
                                                        </p>
                                                    </div>
                                                </div>

                                                <div className="flex flex-wrap items-center gap-2">
                                                    <span className={`inline-flex h-9 items-center gap-2 rounded-xl border px-3 text-xs font-semibold ${isDark ? 'border-white/10 bg-white/[0.05] text-white/75' : 'border-brand/10 bg-brand-canvas text-brand/70'}`}>
                                                        <MessageCircle className="h-4 w-4" />
                                                        WhatsApp
                                                    </span>
                                                    <button
                                                        type="button"
                                                        onClick={() => removeDynamicFollowupStep(index)}
                                                        className={agentiveIconButtonClass(isDark, 'neutral', 'h-9 w-9')}
                                                        title="Remover passo"
                                                    >
                                                        <Trash2 className="h-4 w-4" />
                                                    </button>
                                                </div>
                                            </div>

                                            <div className="mt-4 grid gap-3 xl:grid-cols-[240px_minmax(220px,0.7fr)_minmax(320px,1fr)]">
                                                <div>
                                                    <div className="flex items-center gap-1.5">
                                                        <CalendarClock className={`h-3.5 w-3.5 ${isDark ? 'text-white/45' : 'text-brand/45'}`} />
                                                        <FieldLabel>Momento</FieldLabel>
                                                    </div>
                                                    <div className={`mt-2 flex min-w-0 items-center gap-2 rounded-xl border p-2 ${isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas'}`}>
                                                        <span className={builderMutedTextClass(isDark, 'shrink-0 text-xs')}>Após</span>
                                                        <input
                                                            type="number"
                                                            min={0}
                                                            value={step.sendAfter}
                                                            onChange={(event) => updateDynamicFollowupStep(index, 'sendAfter', event.target.value)}
                                                            className={builderInputClass(isDark, 'h-9 w-20 px-2 text-sm')}
                                                        />
                                                        <div className="relative min-w-[88px] flex-1">
                                                            <select
                                                                value={step.sendAfterUnit}
                                                                onChange={(event) => updateDynamicFollowupStep(index, 'sendAfterUnit', event.target.value)}
                                                                className={builderSelectClass(isDark, 'h-9 px-2 pr-7 text-xs')}
                                                            >
                                                                {DYNAMIC_FOLLOWUP_TIME_UNIT_OPTIONS.map((option) => (
                                                                    <option key={option.value} value={option.value}>
                                                                        {option.label}
                                                                    </option>
                                                                ))}
                                                            </select>
                                                            <ChevronDown className={builderChevronClass(isDark, 'right-2 h-3.5 w-3.5')} />
                                                        </div>
                                                    </div>
                                                </div>

                                                <div>
                                                    <FieldLabel>Objetivo</FieldLabel>
                                                    <input
                                                        value={step.objective}
                                                        onChange={(event) => updateDynamicFollowupStep(index, 'objective', event.target.value)}
                                                        className={builderInputClass(isDark, 'mt-2')}
                                                        placeholder="Ex: reconhecer cadastro"
                                                    />
                                                </div>

                                                <div>
                                                    <FieldLabel>Mini-prompt</FieldLabel>
                                                    <textarea
                                                        value={step.miniPrompt}
                                                        onChange={(event) => updateDynamicFollowupStep(index, 'miniPrompt', event.target.value)}
                                                        className={builderTextareaClass(isDark, 'mt-2 h-24')}
                                                        placeholder="Ex: Gere uma mensagem curta para um lead que acabou de se cadastrar. Use o primeiro nome se houver. Não explique demais."
                                                    />
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>

                        <div className={`flex items-center justify-end gap-2 border-t px-5 py-4 ${isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-brand-canvas'}`}>
                            <button
                                type="button"
                                onClick={() => setConfiguringToolId(null)}
                                className={agentivePrimaryButtonClass('px-4')}
                            >
                                <Check className="h-4 w-4" />
                                Concluir
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {configuringToolId === WHATSAPP_CONTACT_CARD_TOOL_ID && selectedNode && selectedToolIds.includes(WHATSAPP_CONTACT_CARD_TOOL_ID) && (
                <div className="fixed inset-0 z-[80] flex items-center justify-center bg-brand/60 px-3 py-4 backdrop-blur-sm">
                    <div className={`flex max-h-[calc(100vh-2rem)] w-full max-w-4xl flex-col overflow-hidden rounded-[24px] border shadow-[0_28px_90px_rgba(2,3,35,0.34)] ${isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand'}`}>
                        <div className={`flex items-start justify-between gap-4 border-b px-5 py-4 ${isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-brand-canvas'}`}>
                            <div className="flex min-w-0 items-start gap-3">
                                <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
                                    <Phone className="h-5 w-5" />
                                </div>
                                <div className="min-w-0">
                                    <p className={`text-[10px] font-bold uppercase tracking-[0.16em] ${isDark ? 'text-white/40' : 'text-brand/40'}`}>Tool</p>
                                    <h2 className="text-lg font-semibold leading-tight">Enviar card de contato</h2>
                                    <p className={builderMutedTextClass(isDark, 'mt-1 text-sm leading-5')}>
                                        {selectedNode.data.name}
                                    </p>
                                </div>
                            </div>
                            <button
                                type="button"
                                onClick={() => setConfiguringToolId(null)}
                                className={agentiveIconButtonClass(isDark)}
                                title="Fechar"
                            >
                                <X className="h-4 w-4" />
                            </button>
                        </div>

                        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4 sm:p-5">
                            <div className={builderPanelClass(isDark)}>
                                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                                    <div>
                                        <FieldLabel>Cards permitidos</FieldLabel>
                                        <p className={builderMutedTextClass(isDark, 'mt-1 text-xs leading-5')}>
                                            O agente só pode enviar cards configurados aqui e sempre para a conversa atual.
                                        </p>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={addWhatsAppContactCard}
                                        className={agentiveSecondaryButtonClass(isDark, 'shrink-0 px-3')}
                                    >
                                        <Plus className="h-4 w-4" />
                                        Adicionar
                                    </button>
                                </div>

                                <div className="mt-3 space-y-3">
                                    {selectedWhatsAppContactSettings.contactCards.map((card, index) => (
                                        <div
                                            key={`${card.key}-${index}`}
                                            className={`rounded-2xl border p-3 ${isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-white'}`}
                                        >
                                            <div className="flex items-center justify-between gap-3">
                                                <div className="flex min-w-0 items-center gap-2">
                                                    <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ${isDark ? 'bg-white/[0.07] text-white/60' : 'bg-brand-canvas text-brand/60'}`}>
                                                        <UserPlus className="h-4 w-4" />
                                                    </span>
                                                    <div className="min-w-0">
                                                        <p className="truncate text-sm font-semibold">
                                                            {card.fullName || `Contato ${index + 1}`}
                                                        </p>
                                                        <p className={builderMutedTextClass(isDark, 'truncate text-[11px]')}>
                                                            {card.phoneNumber || 'Telefone pendente'}
                                                        </p>
                                                    </div>
                                                </div>
                                                <button
                                                    type="button"
                                                    onClick={() => removeWhatsAppContactCard(index)}
                                                    className={agentiveIconButtonClass(isDark, 'neutral', 'h-9 w-9')}
                                                    title="Remover card"
                                                >
                                                    <Trash2 className="h-4 w-4" />
                                                </button>
                                            </div>

                                            <div className="mt-3 grid gap-3 md:grid-cols-2">
                                                <div>
                                                    <FieldLabel>Nome</FieldLabel>
                                                    <input
                                                        value={card.fullName}
                                                        onChange={(event) => updateWhatsAppContactCard(index, 'fullName', event.target.value)}
                                                        className={builderInputClass(isDark, 'mt-1')}
                                                        placeholder="Nome do responsável"
                                                    />
                                                </div>
                                                <div>
                                                    <FieldLabel>Telefone</FieldLabel>
                                                    <input
                                                        value={card.phoneNumber}
                                                        onChange={(event) => updateWhatsAppContactCard(index, 'phoneNumber', event.target.value)}
                                                        className={builderInputClass(isDark, 'mt-1')}
                                                        placeholder="+55 00 00000-0000"
                                                    />
                                                </div>
                                                <div className="md:col-span-2">
                                                    <FieldLabel>Quando enviar</FieldLabel>
                                                    <input
                                                        value={card.whenToUse}
                                                        onChange={(event) => updateWhatsAppContactCard(index, 'whenToUse', event.target.value)}
                                                        className={builderInputClass(isDark, 'mt-1')}
                                                        placeholder="Quando o lead pedir o contato comercial"
                                                    />
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>

                        <div className={`flex items-center justify-end gap-2 border-t px-5 py-4 ${isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-brand-canvas'}`}>
                            <button
                                type="button"
                                onClick={() => setConfiguringToolId(null)}
                                className={agentivePrimaryButtonClass('px-4')}
                            >
                                <Check className="h-4 w-4" />
                                Concluir
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {configuringToolId === WHATSAPP_SCHEDULED_FOLLOWUP_TOOL_ID && selectedNode && selectedToolIds.includes(WHATSAPP_SCHEDULED_FOLLOWUP_TOOL_ID) && (
                <div className="fixed inset-0 z-[80] flex items-center justify-center bg-brand/60 px-3 py-4 backdrop-blur-sm">
                    <div className={`flex max-h-[calc(100vh-2rem)] w-full max-w-3xl flex-col overflow-hidden rounded-[24px] border shadow-[0_28px_90px_rgba(2,3,35,0.34)] ${isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand'}`}>
                        <div className={`flex items-start justify-between gap-4 border-b px-5 py-4 ${isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-brand-canvas'}`}>
                            <div className="flex min-w-0 items-start gap-3">
                                <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
                                    <CalendarClock className="h-5 w-5" />
                                </div>
                                <div className="min-w-0">
                                    <p className={`text-[10px] font-bold uppercase tracking-[0.16em] ${isDark ? 'text-white/40' : 'text-brand/40'}`}>Tool</p>
                                    <h2 className="text-lg font-semibold leading-tight">Agendar mensagem automática</h2>
                                    <p className={builderMutedTextClass(isDark, 'mt-1 text-sm leading-5')}>
                                        {selectedNode.data.name}
                                    </p>
                                </div>
                            </div>
                            <button
                                type="button"
                                onClick={() => setConfiguringToolId(null)}
                                className={agentiveIconButtonClass(isDark)}
                                title="Fechar"
                            >
                                <X className="h-4 w-4" />
                            </button>
                        </div>

                        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4 sm:p-5">
                            <div className={builderPanelClass(isDark)}>
                                <HelpFieldLabel help="Essa regra entra no prompt deste agente e define os casos em que ele deve agendar uma mensagem futura.">
                                    Quando acionar
                                </HelpFieldLabel>
                                <textarea
                                    value={selectedWhatsAppScheduledFollowupSettings.whenToUse}
                                    onChange={(event) => updateWhatsAppScheduledFollowupToolSettings({ whenToUse: event.target.value })}
                                    className={builderTextareaClass(isDark, 'mt-2 h-28')}
                                    placeholder="Ex: quando o lead disser que vai testar amanhã na clínica e informar um horário exato."
                                />
                            </div>

                            <div className={builderPanelClass(isDark)}>
                                <HelpFieldLabel help="Essa orientação guia o texto que o agente colocará em message_content ao chamar a tool.">
                                    Como escrever a mensagem
                                </HelpFieldLabel>
                                <textarea
                                    value={selectedWhatsAppScheduledFollowupSettings.messageInstruction}
                                    onChange={(event) => updateWhatsAppScheduledFollowupToolSettings({ messageInstruction: event.target.value })}
                                    className={builderTextareaClass(isDark, 'mt-2 h-32')}
                                    placeholder="Ex: mensagem curta, natural, lembrando do link de teste e oferecendo ajuda em poucos minutos."
                                />
                            </div>

                            <label className={builderToggleCardClass(isDark, selectedWhatsAppScheduledFollowupSettings.replaceExistingPending)}>
                                <input
                                    type="checkbox"
                                    checked={selectedWhatsAppScheduledFollowupSettings.replaceExistingPending}
                                    onChange={(event) => updateWhatsAppScheduledFollowupToolSettings({ replaceExistingPending: event.target.checked })}
                                    className={builderCheckboxClass(isDark, 'mt-1')}
                                />
                                <span className="min-w-0">
                                    <span className="block font-semibold">Manter só a última mensagem automática</span>
                                    <span className={builderMutedTextClass(isDark, 'mt-1 block text-xs leading-5')}>
                                        Se o lead trocar o horário, cancela a mensagem pendente anterior deste lead e mantém apenas a nova.
                                    </span>
                                </span>
                            </label>
                        </div>

                        <div className={`flex items-center justify-end gap-2 border-t px-5 py-4 ${isDark ? 'border-white/10 bg-white/[0.03]' : 'border-brand/10 bg-brand-canvas'}`}>
                            <button
                                type="button"
                                onClick={() => setConfiguringToolId(null)}
                                className={agentivePrimaryButtonClass('px-4')}
                            >
                                <Check className="h-4 w-4" />
                                Concluir
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {showNewAgentModal && (
                <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4">
                    <div className="fixed inset-0 bg-brand/55 backdrop-blur-sm" onClick={() => setShowNewAgentModal(false)} />
                    <div className={`relative z-[10000] w-full max-w-lg overflow-hidden rounded-2xl border shadow-[0_24px_70px_rgba(2,3,35,0.28)] ${
                        isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand'
                    }`}>
                        <div className={`flex items-start justify-between gap-4 border-b px-5 py-4 ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
                            <div className="flex min-w-0 items-start gap-3">
                                <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
                                    <Bot className="h-5 w-5" />
                                </span>
                                <div className="min-w-0">
                                    <h2 className="text-base font-semibold leading-tight">Novo agente personalizado</h2>
                                    <p className={`mt-1.5 text-sm leading-relaxed ${isDark ? 'text-white/60' : 'text-brand/60'}`}>Defina identidade, responsabilidade e ícone antes de inserir no organograma.</p>
                                </div>
                            </div>
                            <button
                                type="button"
                                onClick={() => setShowNewAgentModal(false)}
                                className={agentiveIconButtonClass(isDark)}
                                title="Fechar"
                            >
                                <X className="h-4 w-4" />
                            </button>
                        </div>

                        <div className="space-y-4 px-5 py-5">
                            <div>
                                <FieldLabel>Nome do agente</FieldLabel>
                                <input
                                    value={newAgentName}
                                    onChange={(event) => setNewAgentName(event.target.value)}
                                    className={builderInputClass(isDark, 'mt-1')}
                                    placeholder="Ex: Especialista de retenção"
                                    autoFocus
                                />
                            </div>

                            <div>
                                <FieldLabel>Responsabilidade</FieldLabel>
                                <input
                                    value={newAgentRole}
                                    onChange={(event) => setNewAgentRole(event.target.value)}
                                    className={builderInputClass(isDark, 'mt-1')}
                                    placeholder="Ex: Recuperar oportunidades sem resposta"
                                />
                            </div>

                            <div>
                                <FieldLabel>Objetivo</FieldLabel>
                                <textarea
                                    value={newAgentGoal}
                                    onChange={(event) => setNewAgentGoal(event.target.value)}
                                    className={builderTextareaClass(isDark, 'mt-1 h-20')}
                                    placeholder="Descreva o que este agente deve resolver na conversa."
                                />
                            </div>

                            <div>
                                <FieldLabel>Ícone</FieldLabel>
                                <IconSelect
                                    value={newAgentIconKey}
                                    onChange={setNewAgentIconKey}
                                />
                            </div>
                        </div>

                        <div className={`flex items-center justify-end gap-2 border-t px-5 py-4 ${isDark ? 'border-white/10' : 'border-brand/10'}`}>
                            <button
                                type="button"
                                onClick={() => setShowNewAgentModal(false)}
                                className={agentiveSecondaryButtonClass(isDark)}
                            >
                                Cancelar
                            </button>
                            <button
                                type="button"
                                onClick={handleCreateCustomAgent}
                                disabled={!hasReadyModelCatalog}
                                className={agentivePrimaryButtonClass('px-4')}
                            >
                                <Plus className="h-4 w-4" />
                                Criar agente
                            </button>
                        </div>
                    </div>
                </div>
            )}

            <AgentiveConfirmModal
                cancelText="Cancelar"
                confirmText="Remover documento"
                isLoading={Boolean(deletingKnowledgeFileId)}
                isOpen={Boolean(knowledgeFileToDelete)}
                message="O arquivo será removido da base RAG desta equipe. O conteúdo deixa de ser usado nas respostas dos agentes."
                onClose={() => setKnowledgeFileToDelete(null)}
                onConfirm={confirmKnowledgeFileDelete}
                title="Remover documento?"
                variant="danger"
            />

            <AgentiveConfirmModal
                cancelText="Cancelar"
                confirmText={deleteSelectionRequest === 'edge' ? 'Excluir conexão' : 'Excluir agente'}
                isOpen={Boolean(deleteSelectionRequest)}
                message={
                    deleteSelectionRequest === 'edge'
                        ? 'A regra de handoff selecionada será removida do Agent Builder.'
                        : 'O agente selecionado e suas conexões serão removidos do Agent Builder.'
                }
                onClose={() => setDeleteSelectionRequest(null)}
                onConfirm={confirmDeleteSelected}
                title={deleteSelectionRequest === 'edge' ? 'Excluir conexão?' : 'Excluir agente?'}
                variant="danger"
            />
        </div>
    );
};

export default AgentBuilder;
