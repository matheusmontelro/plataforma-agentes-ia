import React, { useState, useEffect } from 'react';
import {
  uploadFile,
  getFileUrl,
  deleteFile,
  getNutritionCampaignSequences,
  createNutritionCampaignSequence,
  launchNutritionCampaign,
  getNutritionCampaignStats,
  getNutritionTargetingPreview,
  saveNutritionCampaignScheduleConfig,
  type NutritionCampaignSequence,
  type NutritionCampaignStep,
  type NutritionCampaignMessage
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
  Save,
  Star,
  Target,
  Users,
  TrendingUp,
  Eye,
  Activity,
  Zap,
  Info,
  HelpCircle,
  Timer,
  Shuffle
} from 'lucide-react';

// ----------------------------------------------------------------
// Tipos para Campanhas de Nutrição - Usando os tipos da API
// ----------------------------------------------------------------
interface MensagemLocal {
  id?: number;
  type: 'text' | 'image' | 'audio' | 'video' | 'nps';
  content: string | File; // Local pode ter File, API sempre string
}

interface PassoLocal extends Omit<NutritionCampaignStep, 'messages'> {
  messages: MensagemLocal[];
}

interface SequenciaLocal extends Omit<NutritionCampaignSequence, 'steps' | 'description' | 'target_contact_status' | 'target_contact_categories' | 'target_contact_tags'> {
  description: string; // Forçar como string no local, mesmo que API seja opcional
  steps: PassoLocal[];
  target_funnel_stages: string[]; // Usar funnel_stage em vez de status
  contact_delay_min: number; // Delay mínimo entre contatos
  contact_delay_max: number; // Delay máximo entre contatos
  contact_delay_unit: 'minutes' | 'hours' | 'days'; // Unidade do delay entre contatos
}

interface ScheduleDay {
  enabled: boolean;
  start: string;
  end: string;
}

interface ScheduleData {
  [key: string]: ScheduleDay;
}

interface CampaignStats {
  sequence_name: string;
  total_executions: number;
  successful_executions: number;
  failed_executions: number;
  scheduled_executions: number;
  processing_executions: number;
}

interface TargetingPreview {
  total_contacts: number;
  contacts: Array<{
    id: number;
    name: string;
    phone: string;
    status: string;
    categoria: string;
    tags: string[];
  }>;
}

// ----------------------------------------------------------------
// Constantes
// ----------------------------------------------------------------
const MAX_PASSOS = 10;
const MAX_MENSAGENS_POR_PASSO = 5;
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

// Status reais do sistema baseados em funnel_stage (ContactsList.tsx)
const funnelStageOptions = [
  { value: 'contato', label: 'Contato', color: 'bg-gray-100 text-gray-700' },
  { value: 'lead', label: 'Lead', color: 'bg-blue-100 text-blue-700' },
  { value: 'agendado', label: 'Agendado', color: 'bg-yellow-100 text-yellow-700' },
  { value: 'cliente', label: 'Cliente', color: 'bg-purple-100 text-purple-700' },
  { value: 'compareceu', label: 'Compareceu', color: 'bg-green-100 text-green-700' },
  { value: 'faltou', label: 'Faltou', color: 'bg-red-100 text-red-700' },
  { value: 'venda', label: 'Venda', color: 'bg-emerald-100 text-emerald-700' },
];


// Usando as funções da API do services/api.ts

// ----------------------------------------------------------------
// Componente Principal
// ----------------------------------------------------------------
export default function NutritionCampaignConfig() {
  // Estados principais
  const [sequences, setSequences] = useState<SequenciaLocal[]>([]);
  const [currentSequence, setCurrentSequence] = useState<SequenciaLocal>({
    name: '',
    description: '',
    active: true,
    target_funnel_stages: [],
    message_delay_min: 30,
    message_delay_max: 120,
    contact_delay_min: 5,
    contact_delay_max: 30,
    contact_delay_unit: 'minutes',
    steps: []
  });

  // Estados de UI
  const [activeTab, setActiveTab] = useState<'sequences' | 'targeting' | 'schedule' | 'stats'>('sequences');
  const [isEditing, setIsEditing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [expandedStep, setExpandedStep] = useState<number | null>(null);

  // Estados para targeting
  const [targetingPreview, setTargetingPreview] = useState<TargetingPreview | null>(null);

  // Estados para schedule
  const [scheduleData, setScheduleData] = useState<ScheduleData>({
    monday: { enabled: true, start: '09:00', end: '18:00' },
    tuesday: { enabled: true, start: '09:00', end: '18:00' },
    wednesday: { enabled: true, start: '09:00', end: '18:00' },
    thursday: { enabled: true, start: '09:00', end: '18:00' },
    friday: { enabled: true, start: '09:00', end: '18:00' },
    saturday: { enabled: false, start: '09:00', end: '12:00' },
    sunday: { enabled: false, start: '09:00', end: '12:00' },
  });

  // Estados para estatísticas
  const [stats, setStats] = useState<CampaignStats[]>([]);

  // Estado para mostrar explicação do timing
  const [showTimingHelp, setShowTimingHelp] = useState(false);

  // ----------------------------------------------------------------
  // Effects
  // ----------------------------------------------------------------
  useEffect(() => {
    loadSequences();
    loadStats();
  }, []);

  // ----------------------------------------------------------------
  // Funções de carregamento
  // ----------------------------------------------------------------
  const loadSequences = async () => {
    try {
      const response = await getNutritionCampaignSequences();
      if (response.success) {
        // Converter de NutritionCampaignSequence[] para SequenciaLocal[]
        const sequences: SequenciaLocal[] = (response.sequences || []).map(seq => ({
          ...seq,
          description: seq.description || '', // Garantir que description seja string
          target_funnel_stages: (seq as any).target_contact_status || [], // Usar o campo correto da API
          contact_delay_min: (seq as any).contact_delay_min || 5,
          contact_delay_max: (seq as any).contact_delay_max || 30,
          contact_delay_unit: (seq as any).contact_delay_unit || 'minutes',
          steps: [] // Inicialmente vazio, carregado separadamente se necessário
        }));
        setSequences(sequences);
      }
    } catch (error) {
      console.error('Erro ao carregar sequências:', error);
    }
  };

  const loadStats = async () => {
    try {
      const response = await getNutritionCampaignStats();
      if (response.success) {
        setStats(response.stats || []);
      }
    } catch (error) {
      console.error('Erro ao carregar estatísticas:', error);
    }
  };

  // ----------------------------------------------------------------
  // Funções de targeting
  // ----------------------------------------------------------------
  const updateTargetingPreview = async () => {
    try {
      const criteria = {
        target_contact_status: currentSequence.target_funnel_stages.length > 0 ? currentSequence.target_funnel_stages : undefined,
      };

      const response = await getNutritionTargetingPreview(criteria);
      if (response.success) {
        setTargetingPreview({
          total_contacts: response.total_contacts,
          contacts: response.contacts
        });
      }
    } catch (error) {
      console.error('Erro ao carregar preview:', error);
    }
  };

  // ----------------------------------------------------------------
  // Componente de Explicação do Timing
  // ----------------------------------------------------------------
  const renderTimingExplanation = () => (
    <div className="bg-blue-50 border border-blue-200 rounded-lg p-6 mb-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center">
          <Info className="w-5 h-5 text-blue-600 mr-2" />
          <h4 className="text-lg font-medium text-blue-900">Como Funciona o Sistema Anti-Spam</h4>
        </div>
        <button
          onClick={() => setShowTimingHelp(!showTimingHelp)}
          className="text-blue-600 hover:text-blue-800"
        >
          {showTimingHelp ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
        </button>
      </div>

      {showTimingHelp && (
        <div className="space-y-6">
          {/* Nível 1 - MAIS IMPORTANTE - Entre Contatos */}
          <div className="bg-yellow-50 border-2 border-yellow-300 rounded-lg p-4">
            <div className="flex items-center mb-3">
              <Users className="w-5 h-5 text-yellow-600 mr-2" />
              <h5 className="font-medium text-yellow-900">1. DELAY ENTRE CONTATOS (MAIS IMPORTANTE!) 🎯</h5>
            </div>
            <p className="text-sm text-yellow-700 mb-3 font-medium">
              O delay mais crítico! Evita que o WhatsApp detecte como disparo em massa.
            </p>
            <div className="bg-yellow-100 rounded p-3 font-mono text-sm">
              <div className="text-yellow-800">👤 João (Contato 1): recebe agora 14h30</div>
              <div className="text-yellow-600 text-xs ml-4">⏱️ delay: {currentSequence.contact_delay_min}-{currentSequence.contact_delay_max} {currentSequence.contact_delay_unit}</div>
              <div className="text-yellow-800">👤 Maria (Contato 2): recebe 14h35-15h00</div>
              <div className="text-yellow-600 text-xs ml-4">⏱️ delay: {currentSequence.contact_delay_min}-{currentSequence.contact_delay_max} {currentSequence.contact_delay_unit}</div>
              <div className="text-yellow-800">👤 Carlos (Contato 3): recebe 14h40-15h30</div>
              <div className="text-red-600 text-xs mt-2">⚠️ Sem esse delay, WhatsApp bloqueia por spam!</div>
            </div>
          </div>

          {/* Nível 2 - Entre Mensagens */}
          <div className="bg-white rounded-lg p-4 border border-blue-100">
            <div className="flex items-center mb-3">
              <MessageCircle className="w-5 h-5 text-green-600 mr-2" />
              <h5 className="font-medium text-gray-900">2. Delay Entre Mensagens (Mesmo Step)</h5>
            </div>
            <p className="text-sm text-gray-600 mb-3">
              Simula digitação humana - aguarda entre cada mensagem do mesmo step.
            </p>
            <div className="bg-gray-50 rounded p-3 font-mono text-sm">
              <div className="text-green-600">📱 Mensagem 1: "Olá João!"</div>
              <div className="text-gray-500 text-xs ml-4">⏱️ aguarda {currentSequence.message_delay_min}-{currentSequence.message_delay_max}s</div>
              <div className="text-green-600">📷 Mensagem 2: [Imagem]</div>
              <div className="text-gray-500 text-xs ml-4">⏱️ aguarda {currentSequence.message_delay_min}-{currentSequence.message_delay_max}s</div>
              <div className="text-green-600">📝 Mensagem 3: "Tem dúvidas?"</div>
            </div>
          </div>

          {/* Nível 3 - Entre Steps */}
          <div className="bg-white rounded-lg p-4 border border-blue-100">
            <div className="flex items-center mb-3">
              <Calendar className="w-5 h-5 text-blue-600 mr-2" />
              <h5 className="font-medium text-gray-900">3. Enviar Após (Entre Steps)</h5>
            </div>
            <p className="text-sm text-gray-600 mb-3">
              Cadência da campanha - tempo base entre cada step da sequência.
            </p>
            <div className="bg-gray-50 rounded p-3 font-mono text-sm">
              <div className="text-blue-600">📋 Step 1: Boas-vindas (imediato)</div>
              <div className="text-gray-500 text-xs ml-4">⏱️ aguarda 2 dias</div>
              <div className="text-blue-600">📋 Step 2: Conteúdo educativo</div>
              <div className="text-gray-500 text-xs ml-4">⏱️ aguarda 5 dias</div>
              <div className="text-blue-600">📋 Step 3: Call-to-action</div>
            </div>
          </div>

          {/* Nível 4 - Delay Aleatório */}
          <div className="bg-white rounded-lg p-4 border border-blue-100">
            <div className="flex items-center mb-3">
              <Shuffle className="w-5 h-5 text-purple-600 mr-2" />
              <h5 className="font-medium text-gray-900">4. Delay Aleatório Adicional (Por Step)</h5>
            </div>
            <p className="text-sm text-gray-600 mb-3">
              Randomização para evitar que todos os contatos recebam no mesmo horário.
            </p>
            <div className="bg-gray-50 rounded p-3 font-mono text-sm">
              <div className="text-purple-600">👤 João: Step 2 em 2 dias + 45min aleatório = 2d 45min</div>
              <div className="text-purple-600">👤 Maria: Step 2 em 2 dias + 1h30 aleatório = 2d 1h30</div>
              <div className="text-purple-600">👤 Carlos: Step 2 em 2 dias + 20min aleatório = 2d 20min</div>
            </div>
          </div>

          {/* Timeline Visual */}
          <div className="bg-white rounded-lg p-4 border border-blue-100">
            <div className="flex items-center mb-3">
              <Timer className="w-5 h-5 text-orange-600 mr-2" />
              <h5 className="font-medium text-gray-900">Timeline Completa - Exemplo Prático</h5>
            </div>

            <div className="space-y-4">
              <div className="border-l-4 border-green-500 pl-4">
                <div className="font-medium text-green-700">🚀 Lançamento: Hoje 14h30</div>
                <div className="text-sm text-gray-600">100 contatos selecionados como "lead"</div>
              </div>

              <div className="border-l-4 border-yellow-500 pl-4">
                <div className="font-medium text-yellow-700">📋 Step 1: Distribuído ao longo de várias horas</div>
                <div className="text-sm text-yellow-600">• Contato 1: 14h30 | Contato 2: 14h{35 + currentSequence.contact_delay_min} | Contato 3: 14h{40 + currentSequence.contact_delay_min * 2}</div>
                <div className="text-xs text-yellow-500">• Delay entre contatos: {currentSequence.contact_delay_min}-{currentSequence.contact_delay_max} {currentSequence.contact_delay_unit}</div>
                <div className="text-xs text-gray-500">• Mensagens por contato: delay de {currentSequence.message_delay_min}-{currentSequence.message_delay_max}s entre cada</div>
              </div>

              <div className="border-l-4 border-blue-500 pl-4">
                <div className="font-medium text-blue-700">📋 Step 2: 2 dias após Step 1 (para cada contato)</div>
                <div className="text-sm text-blue-600">Cada contato recebe 2 dias após seu Step 1 individual + delay aleatório</div>
              </div>

              <div className="border-l-4 border-purple-500 pl-4">
                <div className="font-medium text-purple-700">📋 Step 3: 7 dias após Step 2 (para cada contato)</div>
                <div className="text-sm text-purple-600">Cadência individual mantida para cada contato</div>
              </div>
            </div>

            <div className="mt-4 bg-green-50 border border-green-200 rounded p-3">
              <div className="flex items-center">
                <Check className="w-4 h-4 text-green-600 mr-2" />
                <span className="text-sm font-medium text-green-800">
                  Resultado: WhatsApp detecta como conversas individuais naturais! 🎯
                </span>
              </div>
            </div>
          </div>

          {/* Dicas Importantes */}
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
            <div className="flex items-center mb-2">
              <AlertCircle className="w-5 h-5 text-yellow-600 mr-2" />
              <h5 className="font-medium text-yellow-900">Dicas Importantes</h5>
            </div>
            <ul className="text-sm text-yellow-800 space-y-1">
              <li>• <strong>Delays maiores</strong> = mais seguro contra spam, mas campanha mais lenta</li>
              <li>• <strong>Delays menores</strong> = campanha mais rápida, mas maior risco de detecção</li>
              <li>• <strong>Teste primeiro</strong> com poucos contatos antes de lançar em massa</li>
              <li>• <strong>Respeite horários comerciais</strong> para melhor engajamento</li>
            </ul>
          </div>
        </div>
      )}
    </div>
  );

  // ----------------------------------------------------------------
  // Funções de steps e mensagens
  // ----------------------------------------------------------------
  const addStep = () => {
    if (currentSequence.steps.length >= MAX_PASSOS) return;

    const newStep: PassoLocal = {
      step_number: currentSequence.steps.length + 1,
      send_after: 1,
      send_after_unit: 'days',
      random_delay_min: 0,
      random_delay_max: 3600,
      messages: []
    };

    setCurrentSequence(prev => ({
      ...prev,
      steps: [...prev.steps, newStep]
    }));
  };

  const updateStep = (stepIndex: number, field: keyof PassoLocal, value: any) => {
    setCurrentSequence(prev => ({
      ...prev,
      steps: prev.steps.map((step, index) =>
        index === stepIndex ? { ...step, [field]: value } : step
      )
    }));
  };

  const removeStep = (stepIndex: number) => {
    setCurrentSequence(prev => ({
      ...prev,
      steps: prev.steps.filter((_, index) => index !== stepIndex)
        .map((step, index) => ({ ...step, step_number: index + 1 }))
    }));
  };

  const addMessage = (stepIndex: number) => {
    const step = currentSequence.steps[stepIndex];
    if (step.messages.length >= MAX_MENSAGENS_POR_PASSO) return;

    const newMessage: MensagemLocal = {
      type: 'text',
      content: ''
    };

    updateStep(stepIndex, 'messages', [...step.messages, newMessage]);
  };

  const updateMessage = (stepIndex: number, messageIndex: number, field: keyof MensagemLocal, value: any) => {
    const step = currentSequence.steps[stepIndex];
    const updatedMessages = step.messages.map((msg, index) =>
      index === messageIndex ? { ...msg, [field]: value } : msg
    );
    updateStep(stepIndex, 'messages', updatedMessages);
  };

  const removeMessage = (stepIndex: number, messageIndex: number) => {
    const step = currentSequence.steps[stepIndex];
    const updatedMessages = step.messages.filter((_, index) => index !== messageIndex);
    updateStep(stepIndex, 'messages', updatedMessages);
  };

  // ----------------------------------------------------------------
  // Funções de salvar
  // ----------------------------------------------------------------
  const saveSequence = async () => {
    setLoading(true);
    try {
      // Converter SequenciaLocal para formato da API
      const sequenceForAPI = {
        name: currentSequence.name,
        description: currentSequence.description,
        active: currentSequence.active,
        target_contact_status: currentSequence.target_funnel_stages,
        message_delay_min: currentSequence.message_delay_min,
        message_delay_max: currentSequence.message_delay_max,
        contact_delay_min: currentSequence.contact_delay_min,
        contact_delay_max: currentSequence.contact_delay_max,
        contact_delay_unit: currentSequence.contact_delay_unit,
        // Não incluir steps por enquanto - implementar CRUD separado
      };

      let response;
      if (currentSequence.id) {
        // Função de update não implementada ainda - usar create por enquanto
        response = await createNutritionCampaignSequence(sequenceForAPI);
      } else {
        response = await createNutritionCampaignSequence(sequenceForAPI);
      }

      if (response.success) {
        await loadSequences();
        setIsEditing(false);
        alert('Sequência salva com sucesso!');
      } else {
        alert('Erro ao salvar sequência: ' + (response.message || 'Erro desconhecido'));
      }
    } catch (error) {
      console.error('Erro ao salvar:', error);
      alert('Erro ao salvar sequência');
    } finally {
      setLoading(false);
    }
  };

  const launchCampaign = async (sequenceId?: number) => {
    if (!window.confirm('Tem certeza que deseja lançar esta campanha? Os disparos serão iniciados imediatamente.')) {
      return;
    }

    setLoading(true);
    try {
      const response = await launchNutritionCampaign(sequenceId);
      if (response.success) {
        alert('Campanha lançada com sucesso!');
        loadStats();
      } else {
        alert('Erro ao lançar campanha: ' + (response.message || 'Erro desconhecido'));
      }
    } catch (error) {
      console.error('Erro ao lançar campanha:', error);
      alert('Erro ao lançar campanha');
    } finally {
      setLoading(false);
    }
  };

  // ----------------------------------------------------------------
  // Renderização - Tabs
  // ----------------------------------------------------------------
  const renderTabs = () => (
    <div className="flex justify-between items-center mb-6">
      <div className="flex space-x-1 bg-gray-100 p-1 rounded-lg">
        <button
          onClick={() => setActiveTab('sequences')}
          className={`flex items-center px-4 py-2 rounded-md transition-colors ${activeTab === 'sequences'
              ? 'bg-white text-blue-600 shadow-sm'
              : 'text-gray-600 hover:text-gray-900'
            }`}
        >
          <MessageCircle className="w-4 h-4 mr-2" />
          Sequências
        </button>
        <button
          onClick={() => setActiveTab('targeting')}
          className={`flex items-center px-4 py-2 rounded-md transition-colors ${activeTab === 'targeting'
              ? 'bg-white text-blue-600 shadow-sm'
              : 'text-gray-600 hover:text-gray-900'
            }`}
        >
          <Target className="w-4 h-4 mr-2" />
          Targeting
        </button>
        <button
          onClick={() => setActiveTab('schedule')}
          className={`flex items-center px-4 py-2 rounded-md transition-colors ${activeTab === 'schedule'
              ? 'bg-white text-blue-600 shadow-sm'
              : 'text-gray-600 hover:text-gray-900'
            }`}
        >
          <Calendar className="w-4 h-4 mr-2" />
          Horários
        </button>
        <button
          onClick={() => setActiveTab('stats')}
          className={`flex items-center px-4 py-2 rounded-md transition-colors ${activeTab === 'stats'
              ? 'bg-white text-blue-600 shadow-sm'
              : 'text-gray-600 hover:text-gray-900'
            }`}
        >
          <TrendingUp className="w-4 h-4 mr-2" />
          Estatísticas
        </button>
      </div>

      {/* Botão de Ajuda */}
      <button
        onClick={() => setShowTimingHelp(!showTimingHelp)}
        className={`flex items-center px-4 py-2 rounded-md transition-colors ${showTimingHelp
            ? 'bg-blue-100 text-blue-700 border border-blue-200'
            : 'text-gray-600 hover:text-blue-600 border border-gray-200'
          }`}
      >
        <HelpCircle className="w-4 h-4 mr-2" />
        Como Funciona o Anti-Spam
      </button>
    </div>
  );

  // ----------------------------------------------------------------
  // Renderização - Lista de Sequências
  // ----------------------------------------------------------------
  const renderSequencesList = () => (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="text-lg font-medium">Campanhas de Nutrição</h3>
        <button
          onClick={() => {
            setCurrentSequence({
              name: '',
              description: '',
              active: true,
              target_funnel_stages: [],
              message_delay_min: 30,
              message_delay_max: 120,
              contact_delay_min: 5,
              contact_delay_max: 30,
              contact_delay_unit: 'minutes',
              steps: []
            });
            setIsEditing(true);
          }}
          className="bg-green-600 text-white px-4 py-2 rounded-md hover:bg-green-700 flex items-center"
        >
          <Plus className="w-4 h-4 mr-2" />
          Nova Campanha
        </button>
      </div>

      {sequences.length === 0 ? (
        <div className="text-center py-12 bg-gray-50 rounded-lg">
          <Target className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">Nenhuma campanha criada</h3>
          <p className="text-gray-500 mb-4">Crie sua primeira campanha de nutrição para começar.</p>
        </div>
      ) : (
        <div className="grid gap-4">
          {sequences.map((sequence) => (
            <div key={sequence.id} className="bg-white p-6 rounded-lg border border-gray-200 hover:shadow-md transition-shadow">
              <div className="flex justify-between items-start">
                <div className="flex-1">
                  <div className="flex items-center space-x-3 mb-2">
                    <h4 className="text-lg font-semibold text-gray-900">{sequence.name}</h4>
                    <span className={`px-2 py-1 text-xs font-medium rounded-full ${sequence.active
                        ? 'bg-green-100 text-green-800'
                        : 'bg-gray-100 text-gray-800'
                      }`}>
                      {sequence.active ? 'Ativa' : 'Inativa'}
                    </span>
                  </div>

                  {sequence.description && (
                    <p className="text-gray-600 mb-3">{sequence.description}</p>
                  )}

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                    <div>
                      <span className="text-gray-500">Steps:</span>
                      <span className="ml-1 font-medium">{sequence.steps?.length || 0}</span>
                    </div>
                    <div>
                      <span className="text-gray-500">Delay entre msgs:</span>
                      <span className="ml-1 font-medium">{sequence.message_delay_min}-{sequence.message_delay_max}s</span>
                    </div>
                    <div>
                      <span className="text-gray-500">Funnel stages:</span>
                      <span className="ml-1 font-medium">{sequence.target_funnel_stages?.length || 0}</span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center space-x-2">
                  <button
                    onClick={() => launchCampaign(sequence.id)}
                    className="bg-blue-600 text-white px-3 py-1.5 rounded text-sm hover:bg-blue-700 flex items-center"
                  >
                    <Play className="w-4 h-4 mr-1" />
                    Lançar
                  </button>
                  <button
                    onClick={() => {
                      setCurrentSequence(sequence);
                      setIsEditing(true);
                    }}
                    className="text-gray-600 hover:text-blue-600 p-1"
                  >
                    <Edit2 className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => {
                      if (window.confirm('Tem certeza que deseja remover esta sequência?')) {
                        // Implementar remoção
                      }
                    }}
                    className="text-gray-600 hover:text-red-600 p-1"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  // ----------------------------------------------------------------
  // Renderização - Editor de Sequência
  // ----------------------------------------------------------------
  const renderSequenceEditor = () => (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h3 className="text-lg font-medium">
          {currentSequence.id ? 'Editar Campanha' : 'Nova Campanha'}
        </h3>
        <div className="flex space-x-2">
          <button
            onClick={() => setIsEditing(false)}
            className="bg-gray-600 text-white px-4 py-2 rounded-md hover:bg-gray-700"
          >
            Cancelar
          </button>
          <button
            onClick={saveSequence}
            disabled={loading}
            className="bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 disabled:opacity-50 flex items-center"
          >
            <Save className="w-4 h-4 mr-2" />
            {loading ? 'Salvando...' : 'Salvar'}
          </button>
        </div>
      </div>

      {/* Informações Básicas */}
      <div className="bg-white p-6 rounded-lg border border-gray-200">
        <h4 className="text-md font-medium mb-4">Informações Básicas</h4>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Nome da Campanha</label>
            <input
              type="text"
              value={currentSequence.name}
              onChange={(e) => setCurrentSequence(prev => ({ ...prev, name: e.target.value }))}
              className="w-full p-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder="Ex: Nutrição para Implantes"
            />
          </div>

          <div className="flex items-center">
            <label className="flex items-center">
              <input
                type="checkbox"
                checked={currentSequence.active}
                onChange={(e) => setCurrentSequence(prev => ({ ...prev, active: e.target.checked }))}
                className="mr-2"
              />
              <span className="text-sm font-medium text-gray-700">Campanha Ativa</span>
            </label>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Descrição</label>
          <textarea
            value={currentSequence.description}
            onChange={(e) => setCurrentSequence(prev => ({ ...prev, description: e.target.value }))}
            className="w-full p-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            rows={3}
            placeholder="Descreva o objetivo desta campanha..."
          />
        </div>

        {/* Configurações de Timing */}
        <div className="mt-4 space-y-6">
          {/* Delay Entre Contatos - MAIS IMPORTANTE */}
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center">
                <Users className="w-5 h-5 text-yellow-600 mr-2" />
                <h5 className="text-sm font-medium text-yellow-900">Delay Entre Contatos (CRÍTICO Anti-Spam)</h5>
              </div>
              <button
                onClick={() => setShowTimingHelp(!showTimingHelp)}
                className="text-yellow-600 hover:text-yellow-800 flex items-center text-xs"
              >
                <HelpCircle className="w-4 h-4 mr-1" />
                Mais importante!
              </button>
            </div>

            <div className="grid grid-cols-3 gap-4 mb-3">
              <div>
                <label className="block text-xs text-yellow-700 mb-1">Mínimo</label>
                <input
                  type="number"
                  value={currentSequence.contact_delay_min}
                  onChange={(e) => setCurrentSequence(prev => ({
                    ...prev,
                    contact_delay_min: Math.max(1, parseInt(e.target.value) || 1)
                  }))}
                  className="w-full p-2 border border-yellow-300 rounded-md focus:ring-2 focus:ring-yellow-500 focus:border-yellow-500"
                  min="1"
                />
              </div>
              <div>
                <label className="block text-xs text-yellow-700 mb-1">Máximo</label>
                <input
                  type="number"
                  value={currentSequence.contact_delay_max}
                  onChange={(e) => setCurrentSequence(prev => ({
                    ...prev,
                    contact_delay_max: Math.max(prev.contact_delay_min, parseInt(e.target.value) || prev.contact_delay_min)
                  }))}
                  className="w-full p-2 border border-yellow-300 rounded-md focus:ring-2 focus:ring-yellow-500 focus:border-yellow-500"
                  min={currentSequence.contact_delay_min}
                />
              </div>
              <div>
                <label className="block text-xs text-yellow-700 mb-1">Unidade</label>
                <select
                  value={currentSequence.contact_delay_unit}
                  onChange={(e) => setCurrentSequence(prev => ({
                    ...prev,
                    contact_delay_unit: e.target.value as 'minutes' | 'hours' | 'days'
                  }))}
                  className="w-full p-2 border border-yellow-300 rounded-md focus:ring-2 focus:ring-yellow-500 focus:border-yellow-500"
                >
                  <option value="minutes">Minutos</option>
                  <option value="hours">Horas</option>
                  <option value="days">Dias</option>
                </select>
              </div>
            </div>

            <div className="bg-yellow-100 border border-yellow-300 rounded p-3">
              <div className="flex items-center mb-2">
                <AlertCircle className="w-4 h-4 text-yellow-700 mr-2" />
                <span className="text-sm font-medium text-yellow-800">Exemplo com 100 contatos:</span>
              </div>
              <div className="text-xs text-yellow-700 font-mono">
                • Contato 1: agora<br />
                • Contato 2: +{currentSequence.contact_delay_min}-{currentSequence.contact_delay_max} {currentSequence.contact_delay_unit}<br />
                • Contato 3: +{currentSequence.contact_delay_min * 2}-{currentSequence.contact_delay_max * 2} {currentSequence.contact_delay_unit}<br />
                • Contato 100: +{Math.round(currentSequence.contact_delay_min * 99 / (currentSequence.contact_delay_unit === 'minutes' ? 60 : currentSequence.contact_delay_unit === 'hours' ? 1 : 1 / 24))} - {Math.round(currentSequence.contact_delay_max * 99 / (currentSequence.contact_delay_unit === 'minutes' ? 60 : currentSequence.contact_delay_unit === 'hours' ? 1 : 1 / 24))} {currentSequence.contact_delay_unit === 'minutes' ? 'horas' : currentSequence.contact_delay_unit === 'hours' ? 'horas' : 'dias'}
              </div>
            </div>
          </div>

          {/* Delay Entre Mensagens */}
          <div>
            <h5 className="text-sm font-medium text-gray-700 mb-2">Delay Entre Mensagens (Mesmo Step)</h5>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-gray-500 mb-1">Mínimo (segundos)</label>
                <input
                  type="number"
                  value={currentSequence.message_delay_min}
                  onChange={(e) => setCurrentSequence(prev => ({
                    ...prev,
                    message_delay_min: Math.max(1, parseInt(e.target.value) || 1)
                  }))}
                  className="w-full p-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  min="1"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Máximo (segundos)</label>
                <input
                  type="number"
                  value={currentSequence.message_delay_max}
                  onChange={(e) => setCurrentSequence(prev => ({
                    ...prev,
                    message_delay_max: Math.max(prev.message_delay_min, parseInt(e.target.value) || prev.message_delay_min)
                  }))}
                  className="w-full p-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  min={currentSequence.message_delay_min}
                />
              </div>
            </div>
            <p className="text-xs text-gray-500 mt-1">
              Simula digitação humana entre mensagens do mesmo step
            </p>
          </div>
        </div>
      </div>

      {/* Steps */}
      <div className="bg-white p-6 rounded-lg border border-gray-200">
        <div className="flex justify-between items-center mb-4">
          <h4 className="text-md font-medium">Steps da Campanha</h4>
          <button
            onClick={addStep}
            disabled={currentSequence.steps.length >= MAX_PASSOS}
            className="bg-green-600 text-white px-3 py-1.5 rounded text-sm hover:bg-green-700 disabled:opacity-50 flex items-center"
          >
            <Plus className="w-4 h-4 mr-1" />
            Adicionar Step
          </button>
        </div>

        {currentSequence.steps.length === 0 ? (
          <div className="text-center py-8 text-gray-500">
            <Clock className="w-8 h-8 text-gray-400 mx-auto mb-2" />
            <p>Nenhum step criado. Adicione o primeiro step para começar.</p>
          </div>
        ) : (
          <div className="space-y-4">
            {currentSequence.steps.map((step, stepIndex) => (
              <div key={stepIndex} className="border border-gray-200 rounded-lg">
                <div className="p-4 bg-gray-50 flex justify-between items-center cursor-pointer"
                  onClick={() => setExpandedStep(expandedStep === stepIndex ? null : stepIndex)}>
                  <div className="flex items-center space-x-3">
                    <span className="bg-blue-100 text-blue-800 px-2 py-1 rounded text-sm font-medium">
                      Step {step.step_number}
                    </span>
                    <span className="text-sm text-gray-600">
                      {step.send_after} {timeUnits.find(u => u.value === step.send_after_unit)?.label.toLowerCase()}
                      {step.messages.length > 0 && ` • ${step.messages.length} mensagem(ns)`}
                    </span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        removeStep(stepIndex);
                      }}
                      className="text-red-600 hover:text-red-800 p-1"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                    {expandedStep === stepIndex ?
                      <ChevronUp className="w-5 h-5 text-gray-400" /> :
                      <ChevronDown className="w-5 h-5 text-gray-400" />
                    }
                  </div>
                </div>

                {expandedStep === stepIndex && (
                  <div className="p-4 space-y-4">
                    {/* Configurações do Step */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Enviar após</label>
                        <input
                          type="number"
                          value={step.send_after}
                          onChange={(e) => updateStep(stepIndex, 'send_after', Math.max(MIN_SEND_AFTER, parseInt(e.target.value) || 0))}
                          className="w-full p-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                          min={MIN_SEND_AFTER}
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Unidade</label>
                        <select
                          value={step.send_after_unit}
                          onChange={(e) => updateStep(stepIndex, 'send_after_unit', e.target.value)}
                          className="w-full p-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                        >
                          {timeUnits.map(unit => (
                            <option key={unit.value} value={unit.value}>{unit.label}</option>
                          ))}
                        </select>
                      </div>
                    </div>

                    {/* Delay Aleatório do Step */}
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <label className="block text-sm font-medium text-gray-700">Delay Aleatório Adicional (segundos)</label>
                        <div className="text-xs text-blue-600 flex items-center">
                          <Shuffle className="w-3 h-3 mr-1" />
                          Evita horário sincronizado
                        </div>
                      </div>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-xs text-gray-500 mb-1">Mínimo</label>
                          <input
                            type="number"
                            value={step.random_delay_min}
                            onChange={(e) => updateStep(stepIndex, 'random_delay_min', Math.max(0, parseInt(e.target.value) || 0))}
                            className="w-full p-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                            min="0"
                          />
                        </div>
                        <div>
                          <label className="block text-xs text-gray-500 mb-1">Máximo</label>
                          <input
                            type="number"
                            value={step.random_delay_max}
                            onChange={(e) => updateStep(stepIndex, 'random_delay_max', Math.max(step.random_delay_min, parseInt(e.target.value) || step.random_delay_min))}
                            className="w-full p-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                            min={step.random_delay_min}
                          />
                        </div>
                      </div>
                      <div className="mt-2 bg-blue-50 border border-blue-100 rounded p-2">
                        <div className="text-xs text-blue-700 font-medium mb-1">⏱️ Timing Total do Step:</div>
                        <div className="text-xs text-blue-600">
                          • <strong>Base:</strong> {step.send_after} {timeUnits.find(u => u.value === step.send_after_unit)?.label.toLowerCase()}
                        </div>
                        <div className="text-xs text-blue-600">
                          • <strong>+ Aleatório:</strong> {Math.floor(step.random_delay_min / 60)}min - {Math.floor(step.random_delay_max / 60)}min
                        </div>
                        <div className="text-xs text-blue-600 font-medium mt-1">
                          = <strong>Total:</strong> {step.send_after} {timeUnits.find(u => u.value === step.send_after_unit)?.label.toLowerCase()} + {Math.floor(step.random_delay_min / 60)}-{Math.floor(step.random_delay_max / 60)}min variação
                        </div>
                      </div>
                    </div>

                    {/* Mensagens */}
                    <div>
                      <div className="flex justify-between items-center mb-3">
                        <h5 className="text-sm font-medium">Mensagens</h5>
                        <button
                          onClick={() => addMessage(stepIndex)}
                          disabled={step.messages.length >= MAX_MENSAGENS_POR_PASSO}
                          className="bg-blue-600 text-white px-2 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50"
                        >
                          <Plus className="w-3 h-3 mr-1 inline" />
                          Adicionar
                        </button>
                      </div>

                      {step.messages.length === 0 ? (
                        <p className="text-sm text-gray-500 text-center py-4">
                          Nenhuma mensagem adicionada
                        </p>
                      ) : (
                        <div className="space-y-3">
                          {step.messages.map((message, messageIndex) => (
                            <div key={messageIndex} className="border border-gray-200 rounded p-3">
                              <div className="flex justify-between items-center mb-2">
                                <select
                                  value={message.type}
                                  onChange={(e) => updateMessage(stepIndex, messageIndex, 'type', e.target.value)}
                                  className="text-sm border border-gray-300 rounded px-2 py-1"
                                >
                                  <option value="text">📝 Texto</option>
                                  <option value="image">🖼️ Imagem</option>
                                  <option value="audio">🎵 Áudio</option>
                                  <option value="video">🎥 Vídeo</option>
                                  <option value="nps">⭐ NPS</option>
                                </select>
                                <button
                                  onClick={() => removeMessage(stepIndex, messageIndex)}
                                  className="text-red-600 hover:text-red-800 p-1"
                                >
                                  <Trash2 className="w-4 h-4" />
                                </button>
                              </div>

                              {message.type === 'text' && (
                                <textarea
                                  value={typeof message.content === 'string' ? message.content : ''}
                                  onChange={(e) => updateMessage(stepIndex, messageIndex, 'content', e.target.value)}
                                  placeholder="Digite sua mensagem..."
                                  className="w-full p-2 border border-gray-300 rounded text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                                  rows={3}
                                />
                              )}

                              {message.type === 'nps' && (
                                <textarea
                                  value={typeof message.content === 'string' ? message.content : ''}
                                  onChange={(e) => updateMessage(stepIndex, messageIndex, 'content', e.target.value)}
                                  placeholder="Digite a pergunta do NPS (opcional - deixe vazio para usar padrão)"
                                  className="w-full p-2 border border-gray-300 rounded text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                                  rows={2}
                                />
                              )}

                              {['image', 'audio', 'video'].includes(message.type) && (
                                <div>
                                  <input
                                    type="file"
                                    accept={message.type === 'image' ? 'image/*' : message.type === 'audio' ? 'audio/*' : 'video/*'}
                                    onChange={(e) => {
                                      const file = e.target.files?.[0];
                                      if (file) {
                                        // Verificar tamanho
                                        const limite = LIMITE_ARQUIVOS[message.type as keyof typeof LIMITE_ARQUIVOS];
                                        if (file.size > limite) {
                                          alert(`Arquivo muito grande. Tamanho máximo: ${Math.round(limite / (1024 * 1024))}MB`);
                                          return;
                                        }
                                        updateMessage(stepIndex, messageIndex, 'content', file);
                                      }
                                    }}
                                    className="w-full text-sm"
                                  />
                                  {typeof message.content !== 'string' && message.content instanceof File && (
                                    <p className="text-xs text-gray-500 mt-1">
                                      Arquivo: {message.content.name} ({Math.round(message.content.size / 1024)}KB)
                                    </p>
                                  )}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );

  // ----------------------------------------------------------------
  // Renderização - Targeting
  // ----------------------------------------------------------------
  const renderTargeting = () => (
    <div className="space-y-6">
      <div className="bg-white p-6 rounded-lg border border-gray-200">
        <h3 className="text-lg font-medium mb-4">Critérios de Targeting</h3>

        {/* Funnel Stage (Status do Funil) */}
        <div className="mb-6">
          <label className="block text-sm font-medium text-gray-700 mb-2">Funnel Stage (Status do Funil)</label>
          <div className="flex flex-wrap gap-2">
            {funnelStageOptions.map((option) => (
              <label key={option.value} className="flex items-center">
                <input
                  type="checkbox"
                  checked={currentSequence.target_funnel_stages.includes(option.value)}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setCurrentSequence(prev => ({
                        ...prev,
                        target_funnel_stages: [...prev.target_funnel_stages, option.value]
                      }));
                    } else {
                      setCurrentSequence(prev => ({
                        ...prev,
                        target_funnel_stages: prev.target_funnel_stages.filter(s => s !== option.value)
                      }));
                    }
                  }}
                  className="mr-2"
                />
                <span className={`text-sm px-2 py-1 rounded ${option.color}`}>
                  {option.label}
                </span>
              </label>
            ))}
          </div>
        </div>


        {/* Preview */}
        <div className="mt-6">
          <div className="flex justify-between items-center mb-4">
            <button
              onClick={updateTargetingPreview}
              disabled={currentSequence.target_funnel_stages.length === 0}
              className="bg-green-600 text-white px-4 py-2 rounded-md hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed flex items-center"
            >
              <Eye className="w-4 h-4 mr-2" />
              Preview dos Contatos
            </button>

            {targetingPreview && (
              <div className="text-sm text-gray-600">
                <span className="font-medium text-lg">{targetingPreview.total_contacts}</span> contatos encontrados
              </div>
            )}
          </div>

          {currentSequence.target_funnel_stages.length === 0 && (
            <div className="bg-yellow-50 border border-yellow-200 rounded-md p-4 mb-4">
              <div className="flex">
                <AlertCircle className="w-5 h-5 text-yellow-400 mr-2" />
                <p className="text-sm text-yellow-700">
                  Selecione pelo menos um Funnel Stage para ver o preview dos contatos.
                </p>
              </div>
            </div>
          )}

          {targetingPreview && (
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <div className="bg-gray-50 px-4 py-3 border-b border-gray-200">
                <h4 className="text-sm font-medium text-gray-900">
                  Contatos que receberão a campanha ({targetingPreview.total_contacts})
                </h4>
              </div>

              {targetingPreview.total_contacts === 0 ? (
                <div className="p-6 text-center">
                  <Users className="w-12 h-12 text-gray-400 mx-auto mb-4" />
                  <p className="text-sm text-gray-500">Nenhum contato atende aos critérios definidos.</p>
                  <p className="text-xs text-gray-400 mt-1">Ajuste os critérios de targeting acima.</p>
                </div>
              ) : (
                <div className="max-h-60 overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 sticky top-0">
                      <tr>
                        <th className="px-4 py-3 text-left font-medium text-gray-600">Nome</th>
                        <th className="px-4 py-3 text-left font-medium text-gray-600">Telefone</th>
                        <th className="px-4 py-3 text-left font-medium text-gray-600">Funnel Stage</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-200">
                      {targetingPreview.contacts.slice(0, 20).map((contact) => {
                        const stageOption = funnelStageOptions.find(opt => opt.value === contact.status);
                        return (
                          <tr key={contact.id} className="hover:bg-gray-50">
                            <td className="px-4 py-3">{contact.name || 'Sem nome'}</td>
                            <td className="px-4 py-3 font-mono text-xs">{contact.phone}</td>
                            <td className="px-4 py-3">
                              {stageOption && (
                                <span className={`px-2 py-1 text-xs rounded ${stageOption.color}`}>
                                  {stageOption.label}
                                </span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {targetingPreview.contacts.length > 20 && (
                    <div className="bg-gray-50 px-4 py-3 text-center border-t border-gray-200">
                      <p className="text-xs text-gray-500">
                        ... e mais {targetingPreview.contacts.length - 20} contatos
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );

  // ----------------------------------------------------------------
  // Renderização - Schedule
  // ----------------------------------------------------------------
  const renderSchedule = () => (
    <div className="bg-white p-6 rounded-lg border border-gray-200">
      <h3 className="text-lg font-medium mb-4">Horários de Funcionamento</h3>
      <p className="text-sm text-gray-600 mb-6">
        Configure os horários em que as mensagens podem ser enviadas. Mensagens fora deste horário serão reagendadas.
      </p>

      <div className="space-y-4">
        {daysOfWeek.map((day) => (
          <div key={day.key} className="flex items-center space-x-4 p-4 bg-gray-50 rounded-lg">
            <div className="w-24">
              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={scheduleData[day.key]?.enabled || false}
                  onChange={(e) => setScheduleData(prev => ({
                    ...prev,
                    [day.key]: {
                      ...prev[day.key],
                      enabled: e.target.checked
                    }
                  }))}
                  className="mr-2"
                />
                <span className="text-sm font-medium">{day.label}</span>
              </label>
            </div>

            {scheduleData[day.key]?.enabled && (
              <>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Início</label>
                  <input
                    type="time"
                    value={scheduleData[day.key]?.start || '09:00'}
                    onChange={(e) => setScheduleData(prev => ({
                      ...prev,
                      [day.key]: {
                        ...prev[day.key],
                        start: e.target.value
                      }
                    }))}
                    className="p-1 border border-gray-300 rounded text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Fim</label>
                  <input
                    type="time"
                    value={scheduleData[day.key]?.end || '18:00'}
                    onChange={(e) => setScheduleData(prev => ({
                      ...prev,
                      [day.key]: {
                        ...prev[day.key],
                        end: e.target.value
                      }
                    }))}
                    className="p-1 border border-gray-300 rounded text-sm"
                  />
                </div>
              </>
            )}
          </div>
        ))}
      </div>

      <div className="mt-6">
        <button
          onClick={async () => {
            if (currentSequence.id) {
              try {
                await saveNutritionCampaignScheduleConfig(currentSequence.id, scheduleData);
                alert('Horários salvos com sucesso!');
              } catch (error) {
                alert('Erro ao salvar horários');
              }
            } else {
              alert('Salve a sequência primeiro antes de configurar os horários');
            }
          }}
          className="bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 flex items-center"
        >
          <Save className="w-4 h-4 mr-2" />
          Salvar Horários
        </button>
      </div>
    </div>
  );

  // ----------------------------------------------------------------
  // Renderização - Estatísticas
  // ----------------------------------------------------------------
  const renderStats = () => (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h3 className="text-lg font-medium">Estatísticas das Campanhas</h3>
        <button
          onClick={() => launchCampaign()}
          className="bg-green-600 text-white px-4 py-2 rounded-md hover:bg-green-700 flex items-center"
        >
          <Zap className="w-4 h-4 mr-2" />
          Lançar Todas as Campanhas
        </button>
      </div>

      {stats.length === 0 ? (
        <div className="text-center py-12 bg-gray-50 rounded-lg">
          <Activity className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">Nenhuma estatística disponível</h3>
          <p className="text-gray-500">Crie e lance campanhas para ver as estatísticas aqui.</p>
        </div>
      ) : (
        <div className="grid gap-6">
          {stats.map((stat, index) => {
            const totalExecutions = stat.total_executions || 0;
            const successRate = totalExecutions > 0 ?
              Math.round((stat.successful_executions / totalExecutions) * 100) : 0;

            return (
              <div key={index} className="bg-white p-6 rounded-lg border border-gray-200">
                <h4 className="text-lg font-semibold mb-4">{stat.sequence_name}</h4>

                <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-4">
                  <div className="text-center">
                    <div className="text-2xl font-bold text-gray-900">{totalExecutions}</div>
                    <div className="text-sm text-gray-500">Total</div>
                  </div>
                  <div className="text-center">
                    <div className="text-2xl font-bold text-green-600">{stat.successful_executions}</div>
                    <div className="text-sm text-gray-500">Sucesso</div>
                  </div>
                  <div className="text-center">
                    <div className="text-2xl font-bold text-red-600">{stat.failed_executions}</div>
                    <div className="text-sm text-gray-500">Falharam</div>
                  </div>
                  <div className="text-center">
                    <div className="text-2xl font-bold text-blue-600">{stat.scheduled_executions}</div>
                    <div className="text-sm text-gray-500">Agendadas</div>
                  </div>
                  <div className="text-center">
                    <div className="text-2xl font-bold text-yellow-600">{stat.processing_executions}</div>
                    <div className="text-sm text-gray-500">Processando</div>
                  </div>
                </div>

                <div className="mb-2">
                  <div className="flex justify-between text-sm mb-1">
                    <span>Taxa de Sucesso</span>
                    <span>{successRate}%</span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <div
                      className="bg-green-600 h-2 rounded-full"
                      style={{ width: `${successRate}%` }}
                    ></div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );

  // ----------------------------------------------------------------
  // Renderização Principal
  // ----------------------------------------------------------------
  return (
    <div className="min-h-screen bg-gray-100">
      <div className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900 flex items-center">
            <Target className="w-8 h-8 mr-3 text-green-600" />
            Campanhas de Nutrição
          </h1>
          <p className="mt-2 text-gray-600">
            Gerencie campanhas automatizadas para engajamento nutricional com timing inteligente anti-spam
          </p>
        </div>

        {renderTabs()}

        {/* Explicação do Sistema (sempre visível quando ativada) */}
        {showTimingHelp && !isEditing && renderTimingExplanation()}

        {!isEditing && activeTab === 'sequences' && renderSequencesList()}
        {isEditing && renderSequenceEditor()}
        {!isEditing && activeTab === 'targeting' && renderTargeting()}
        {!isEditing && activeTab === 'schedule' && renderSchedule()}
        {!isEditing && activeTab === 'stats' && renderStats()}
      </div>
    </div>
  );
}