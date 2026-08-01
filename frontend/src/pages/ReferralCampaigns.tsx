import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  Target,
  ChevronDown,
  ChevronRight,
  Save,
  Trash2,
  Edit2,
  CheckCircle,
  AlertCircle,
  Gift,
  UserPlus,
  HelpCircle,
  CheckCircle2
} from 'lucide-react';

import {
  getReferralCampaigns,
  createReferralCampaign,
  updateReferralCampaign,
  deleteReferralCampaign,
  type ReferralCampaign,
  type ReferralCampaignCreate
} from '../services/referralCampaignApi';

import ConfirmDeleteModal from '../components/ConfirmDeleteModal.tsx';

// Helper components seguindo padrão do PromptConfig
const Field: React.FC<{ label: string; children: React.ReactNode; hint?: string; required?: boolean }> = ({
  label,
  children,
  hint,
  required
}) => {
  const { isDark } = useTheme();
  return (
    <label className="block text-sm">
      <span className={`mb-1 block font-medium ${
        isDark ? 'text-gray-300' : 'text-gray-700'
      }`}>
        {label} {required && <span className="text-red-500">*</span>}
      </span>
      {children}
      {hint && <span className={`mt-1 block text-[11px] ${
        isDark ? 'text-gray-400' : 'text-gray-500'
      }`}>{hint}</span>}
    </label>
  );
};

const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>((props, ref) => {
  const { isDark } = useTheme();
  return (
    <input
      ref={ref}
      {...props}
      className={`w-full rounded-xl border px-3 py-2 text-sm outline-none transition-all focus:ring-2 focus:ring-brand ${
        isDark
          ? 'border-gray-600 bg-gray-700 text-gray-200 placeholder:text-gray-400 focus:border-brand'
          : 'border-gray-300 bg-white text-gray-800 placeholder:text-gray-400 focus:border-brand'
      } ${props.className ?? ""}`}
    />
  );
});

const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>((props, ref) => {
  const { isDark } = useTheme();
  return (
    <textarea
      ref={ref}
      {...props}
      className={`w-full rounded-xl border px-3 py-2 text-sm outline-none transition-all focus:ring-2 focus:ring-brand ${
        isDark
          ? 'border-gray-600 bg-gray-700 text-gray-200 placeholder:text-gray-400 focus:border-brand'
          : 'border-gray-300 bg-white text-gray-800 placeholder:text-gray-400 focus:border-brand'
      } ${props.className ?? ""}`}
    />
  );
});

// Helper function to calculate completeness
function calculateCompleteness(campaign: ReferralCampaignCreate): number {
  const essentialFields = [
    campaign.campaign_name,
    campaign.referrer_campaign_description,
    campaign.referee_campaign_description
  ];

  const filledFields = essentialFields.filter(field =>
    field && field.toString().trim().length > 0
  ).length;

  return Math.round((filledFields / essentialFields.length) * 100);
}

const ReferralCampaigns: React.FC = () => {
  const { isDark } = useTheme();
  const [campaign, setCampaign] = useState<ReferralCampaign | null>(null);
  const [loading, setLoading] = useState(true);
  const [isEditing, setIsEditing] = useState(false);
  const [saveStatus, setSaveStatus] = useState<null | 'saving' | 'success' | 'error'>(null);
  const [expandedSections, setExpandedSections] = useState(['referrer', 'referee']);
  const [showDeleteModal, setShowDeleteModal] = useState(false);

  // Get company ID from localStorage
  const companyId = parseInt((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')) || '0');

  // Refs para inputs de texto (evita perda de foco)
  const campaignNameRef = useRef<HTMLInputElement>(null);
  const referrerDescRef = useRef<HTMLTextAreaElement>(null);
  const referrerInstrRef = useRef<HTMLTextAreaElement>(null);
  const refereeDescRef = useRef<HTMLTextAreaElement>(null);
  const refereeInstrRef = useRef<HTMLTextAreaElement>(null);
  const delayMinutesRef = useRef<HTMLInputElement>(null);
  const maxReferralsRef = useRef<HTMLInputElement>(null);
  const refereeDelayRef = useRef<HTMLInputElement>(null);

  // Form state
  const [formData, setFormData] = useState<ReferralCampaignCreate>({
    company_id: companyId,
    campaign_name: '',
    active: true,
    referrer_campaign_description: '',
    referrer_campaign_instructions: '',
    referee_campaign_description: '',
    referee_campaign_instructions: '',
    delay_minutes: 5,
    max_referrals_per_request: 3,
    contact_referees_immediately: true,
    referee_delay_minutes: 10
  });

  // Calculate completeness percentage
  const completenessPercentage = useMemo(() =>
    calculateCompleteness(formData),
    [formData]
  );

  // Sincronizar valores dos refs com formData
  useEffect(() => {
    if (campaignNameRef.current) campaignNameRef.current.value = formData.campaign_name;
    if (referrerDescRef.current) referrerDescRef.current.value = formData.referrer_campaign_description;
    if (referrerInstrRef.current) referrerInstrRef.current.value = formData.referrer_campaign_instructions;
    if (refereeDescRef.current) refereeDescRef.current.value = formData.referee_campaign_description;
    if (refereeInstrRef.current) refereeInstrRef.current.value = formData.referee_campaign_instructions;
    if (delayMinutesRef.current) delayMinutesRef.current.value = formData.delay_minutes.toString();
    if (maxReferralsRef.current) maxReferralsRef.current.value = formData.max_referrals_per_request.toString();
    if (refereeDelayRef.current) refereeDelayRef.current.value = formData.referee_delay_minutes.toString();
  }, [formData]);

  // Toggle section expansion with scroll preservation
  const toggleSection = useCallback((sectionId: string, event?: React.MouseEvent) => {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }

    // Save current scroll position
    const currentScrollY = window.scrollY;

    setExpandedSections(prev =>
      prev.includes(sectionId)
        ? prev.filter(id => id !== sectionId)
        : [...prev, sectionId]
    );

    // Maintain scroll position after update
    requestAnimationFrame(() => {
      window.scrollTo(0, currentScrollY);
    });
  }, []);

  // Load campaign on mount
  useEffect(() => {
    if (companyId) {
      loadCampaign();
    } else {
      setLoading(false);
    }
  }, [companyId]);

  const loadCampaign = async () => {
    if (!companyId) return;

    setLoading(true);
    try {
      const campaigns = await getReferralCampaigns(companyId);
      if (campaigns.length > 0) {
        const activeCampaign = campaigns.find(c => c.active) || campaigns[0];
        setCampaign(activeCampaign);
        setFormData({
          company_id: companyId,
          campaign_name: activeCampaign.campaign_name,
          active: activeCampaign.active,
          referrer_campaign_description: activeCampaign.referrer_campaign_description,
          referrer_campaign_instructions: activeCampaign.referrer_campaign_instructions || '',
          referee_campaign_description: activeCampaign.referee_campaign_description,
          referee_campaign_instructions: activeCampaign.referee_campaign_instructions || '',
          delay_minutes: activeCampaign.delay_minutes,
          max_referrals_per_request: activeCampaign.max_referrals_per_request,
          contact_referees_immediately: activeCampaign.contact_referees_immediately,
          referee_delay_minutes: activeCampaign.referee_delay_minutes
        });
      }
    } catch (error) {
      console.error('Erro ao carregar campanha:', error);
    } finally {
      setLoading(false);
    }
  };

  // Handler apenas para checkbox (que permanece controlado)
  const handleCheckboxChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, checked } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: checked
    }));
  };

  // Handlers para onBlur de cada campo
  const handleCampaignNameBlur = () => {
    if (campaignNameRef.current) {
      setFormData(prev => ({ ...prev, campaign_name: campaignNameRef.current!.value }));
    }
  };

  const handleReferrerDescBlur = () => {
    if (referrerDescRef.current) {
      setFormData(prev => ({ ...prev, referrer_campaign_description: referrerDescRef.current!.value }));
    }
  };

  const handleReferrerInstrBlur = () => {
    if (referrerInstrRef.current) {
      setFormData(prev => ({ ...prev, referrer_campaign_instructions: referrerInstrRef.current!.value }));
    }
  };

  const handleRefereeDescBlur = () => {
    if (refereeDescRef.current) {
      setFormData(prev => ({ ...prev, referee_campaign_description: refereeDescRef.current!.value }));
    }
  };

  const handleRefereeInstrBlur = () => {
    if (refereeInstrRef.current) {
      setFormData(prev => ({ ...prev, referee_campaign_instructions: refereeInstrRef.current!.value }));
    }
  };

  const handleDelayMinutesBlur = () => {
    if (delayMinutesRef.current) {
      setFormData(prev => ({ ...prev, delay_minutes: parseInt(delayMinutesRef.current!.value) || 5 }));
    }
  };

  const handleMaxReferralsBlur = () => {
    if (maxReferralsRef.current) {
      setFormData(prev => ({ ...prev, max_referrals_per_request: parseInt(maxReferralsRef.current!.value) || 3 }));
    }
  };

  const handleRefereeDelayBlur = () => {
    if (refereeDelayRef.current) {
      setFormData(prev => ({ ...prev, referee_delay_minutes: parseInt(refereeDelayRef.current!.value) || 10 }));
    }
  };

  const handleSave = async () => {
    // Capturar valores atuais de todos os refs antes de salvar
    const currentFormData = {
      ...formData,
      campaign_name: campaignNameRef.current?.value || formData.campaign_name,
      referrer_campaign_description: referrerDescRef.current?.value || formData.referrer_campaign_description,
      referrer_campaign_instructions: referrerInstrRef.current?.value || formData.referrer_campaign_instructions,
      referee_campaign_description: refereeDescRef.current?.value || formData.referee_campaign_description,
      referee_campaign_instructions: refereeInstrRef.current?.value || formData.referee_campaign_instructions,
      delay_minutes: parseInt(delayMinutesRef.current?.value || '') || formData.delay_minutes,
      max_referrals_per_request: parseInt(maxReferralsRef.current?.value || '') || formData.max_referrals_per_request,
      referee_delay_minutes: parseInt(refereeDelayRef.current?.value || '') || formData.referee_delay_minutes
    };

    setSaveStatus('saving');
    try {
      if (campaign) {
        await updateReferralCampaign(campaign.id!, currentFormData);
      } else {
        await createReferralCampaign(currentFormData);
      }
      setSaveStatus('success');
      setIsEditing(false);
      loadCampaign();
      setTimeout(() => setSaveStatus(null), 2000);
    } catch (error) {
      console.error('Erro ao salvar campanha:', error);
      setSaveStatus('error');
      setTimeout(() => setSaveStatus(null), 3000);
    }
  };

  const handleDelete = async () => {
    if (!campaign) return;

    try {
      await deleteReferralCampaign(campaign.id!);
      setCampaign(null);
      setIsEditing(false);
      setFormData({
        company_id: companyId,
        campaign_name: '',
        active: true,
        referrer_campaign_description: '',
        referrer_campaign_instructions: '',
        referee_campaign_description: '',
        referee_campaign_instructions: '',
        delay_minutes: 5,
        max_referrals_per_request: 3,
        contact_referees_immediately: true,
        referee_delay_minutes: 10
      });
      setShowDeleteModal(false);
    } catch (error) {
      console.error('Erro ao excluir campanha:', error);
    }
  };

  // Section container component com padrão do PromptConfig
  const SectionContainer: React.FC<{
    id: string;
    title: string;
    icon: React.ElementType;
    children: React.ReactNode
  }> = React.memo(({ id, title, icon: Icon, children }) => {
    const isExpanded = expandedSections.includes(id);

    return (
      <div className={`mb-4 rounded-2xl shadow-xl border overflow-hidden transition-all duration-200 ${
        isDark
          ? 'bg-gray-800 border-gray-600'
          : 'bg-white border-gray-200'
      }`}>
        <button
          type="button"
          onClick={(e) => toggleSection(id, e)}
          className={`w-full flex items-center justify-between p-4 text-left transition-colors ${
            isDark
              ? 'hover:bg-gray-700/40'
              : 'hover:bg-gray-50'
          }`}
        >
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-xl transition-colors ${
              isExpanded
                ? 'bg-brand/20 text-brand'
                : isDark
                  ? 'bg-gray-700 text-gray-400'
                  : 'bg-gray-100 text-gray-600'
            }`}>
              <Icon className="h-5 w-5" />
            </div>
            <span className={`font-semibold ${
              isDark ? 'text-gray-200' : 'text-gray-800'
            }`}>{title}</span>
          </div>
          {isExpanded ?
            <ChevronDown className={`h-5 w-5 ${
              isDark ? 'text-gray-400' : 'text-gray-400'
            }`} /> :
            <ChevronRight className={`h-5 w-5 ${
              isDark ? 'text-gray-400' : 'text-gray-400'
            }`} />
          }
        </button>

        {isExpanded && (
          <div className={`p-4 border-t ${
            isDark
              ? 'border-gray-600 bg-gray-800/50'
              : 'border-gray-200 bg-gray-50/50'
          }`}>
            {children}
          </div>
        )}
      </div>
    );
  });

  if (loading) {
    return (
      <div className={`min-h-screen flex items-center justify-center ${
        isDark ? 'bg-brand' : 'bg-gradient-to-b from-gray-50 to-white'
      }`}>
        <div className="text-center">
          <div className="w-12 h-12 border-4 border-brand/30 border-t-brand rounded-full animate-spin mx-auto"></div>
          <p className={`mt-4 ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
            Carregando campanha de indicação...
          </p>
        </div>
      </div>
    );
  }

  if (!companyId) {
    return (
      <div className={`min-h-screen flex items-center justify-center ${
        isDark ? 'bg-brand' : 'bg-gradient-to-b from-gray-50 to-white'
      }`}>
        <div className={`text-center p-8 rounded-2xl border ${
          isDark ? 'bg-gray-800 border-gray-600' : 'bg-white border-gray-200'
        }`}>
          <AlertCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
          <p className={`${isDark ? 'text-gray-300' : 'text-gray-600'}`}>
            Nenhuma empresa selecionada. Por favor, selecione uma empresa primeiro.
          </p>
        </div>
      </div>
    );
  }

  // Status color for the header
  const statusColor = campaign?.active
    ? "bg-brand/10 text-brand"
    : campaign
      ? isDark ? "bg-gray-700 text-gray-300" : "bg-gray-100 text-gray-600"
      : "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400";

  return (
    <div className={`min-h-screen w-full ${
      isDark
        ? 'bg-brand text-gray-200'
        : 'bg-gradient-to-b from-gray-50 to-white text-gray-800'
    }`}>
      {/* Header */}
      <header className={`sticky top-0 z-20 border-b px-4 py-3 shadow-sm backdrop-blur ${
        isDark
          ? 'border-gray-700 bg-brand/90'
          : 'border-gray-200 bg-white/90'
      }`}>
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3">
          <div>
            <h1 className={`text-lg font-semibold tracking-tight ${
              isDark ? 'text-white' : 'text-gray-800'
            }`}>Campanha de Indicação</h1>
            <p className={`text-xs ${
              isDark ? 'text-gray-400' : 'text-gray-500'
            }`}>Configure como funciona o programa de indicações da empresa</p>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className={`rounded-full px-3 py-1 ${statusColor}`}>
              {campaign?.active ? 'Ativa' : campaign ? 'Inativa' : 'Sem Campanha'}
            </span>
            <div className="flex items-center gap-2">
              {campaign && !isEditing ? (
                <>
                  <button
                    onClick={() => {
                      const currentScrollY = window.scrollY;
                      setIsEditing(true);
                      requestAnimationFrame(() => window.scrollTo(0, currentScrollY));
                    }}
                    className={`rounded-xl border px-3 py-2 transition-colors ${
                      isDark
                        ? 'border-gray-600 bg-gray-700 text-gray-200 hover:bg-gray-600'
                        : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    <Edit2 className="mr-1 inline h-4 w-4"/>Editar
                  </button>
                  <button
                    onClick={() => setShowDeleteModal(true)}
                    className="rounded-xl bg-red-500 px-3 py-2 text-white hover:bg-red-600 transition-colors"
                  >
                    <Trash2 className="mr-1 inline h-4 w-4"/>Excluir
                  </button>
                </>
              ) : (
                <button
                  onClick={handleSave}
                  disabled={saveStatus === 'saving'}
                  className="rounded-xl bg-brand px-3 py-2 text-white hover:bg-brand/90 transition-colors disabled:opacity-50"
                >
                  {saveStatus === 'saving' ? (
                    <>Salvando...</>
                  ) : saveStatus === 'success' ? (
                    <><CheckCircle className="mr-1 inline h-4 w-4"/>Salvo!</>
                  ) : (
                    <><Save className="mr-1 inline h-4 w-4"/>Salvar</>
                  )}
                </button>
              )}
            </div>
          </div>
        </div>
        {/* Progress bar */}
        {isEditing || !campaign ? (
          <div className="mx-auto mt-2 max-w-6xl">
            <div className={`relative h-2 w-full overflow-hidden rounded-full ${
              isDark ? 'bg-gray-700' : 'bg-gray-100'
            }`}>
              <div
                className="absolute left-0 top-0 h-2 rounded-full bg-brand transition-all duration-300"
                style={{ width: `${completenessPercentage}%` }}
              />
            </div>
            <p className={`mt-1 text-right text-[11px] ${
              isDark ? 'text-gray-400' : 'text-gray-500'
            }`}>Progresso: {completenessPercentage}%</p>
          </div>
        ) : null}
      </header>

      <div className="mx-auto max-w-6xl p-4">
        {/* View mode - show existing campaign */}
        {campaign && !isEditing ? (
          <div className="space-y-4">
            {/* Success banner */}
            <div className={`rounded-2xl border p-4 ${
              isDark
                ? 'border-brand/30 bg-brand/10'
                : 'border-brand/20 bg-brand/5'
            }`}>
              <div className="flex gap-3">
                <CheckCircle2 className="w-5 h-5 text-brand flex-shrink-0 mt-0.5" />
                <div>
                  <h4 className="font-medium text-brand mb-1">Campanha configurada</h4>
                  <p className={`text-sm ${
                    isDark ? 'text-brand/90' : 'text-brand/80'
                  }`}>
                    Sua campanha de indicação está {campaign.active ? 'ativa' : 'inativa'}.
                    Você pode editar os detalhes a qualquer momento.
                  </p>
                </div>
              </div>
            </div>

            {/* Campaign cards grid */}
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {/* Basic info card */}
              <div className={`col-span-full rounded-2xl border p-4 shadow-xl ${
                isDark
                  ? 'border-gray-600 bg-gray-800'
                  : 'border-gray-200 bg-white'
              }`}>
                <h3 className={`text-lg font-semibold mb-2 ${
                  isDark ? 'text-gray-200' : 'text-gray-800'
                }`}>{campaign.campaign_name}</h3>
                <span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs ${
                  campaign.active
                    ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                    : 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400'
                }`}>
                  <div className={`h-2 w-2 rounded-full ${
                    campaign.active ? 'bg-green-500' : 'bg-gray-400'
                  }`} />
                  {campaign.active ? 'Campanha Ativa' : 'Campanha Inativa'}
                </span>
              </div>

              {/* Referrer card */}
              <div className={`rounded-2xl border p-4 shadow-xl ${
                isDark
                  ? 'border-gray-600 bg-gray-800'
                  : 'border-gray-200 bg-white'
              }`}>
                <div className="mb-3 flex items-center justify-between">
                  <h3 className={`text-sm font-semibold flex items-center gap-2 ${
                    isDark ? 'text-gray-200' : 'text-gray-800'
                  }`}>
                    <Gift className="h-4 w-4 text-brand" />
                    Para quem Indica
                  </h3>
                  <button
                    onClick={() => {
                      const currentScrollY = window.scrollY;
                      setExpandedSections(['referrer']);
                      setIsEditing(true);
                      requestAnimationFrame(() => window.scrollTo(0, currentScrollY));
                    }}
                    className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                      isDark
                        ? 'border-gray-600 text-gray-300 hover:bg-gray-700'
                        : 'border-gray-200 text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    Editar
                  </button>
                </div>
                <ul className={`text-sm space-y-1 ${
                  isDark ? 'text-gray-300' : 'text-gray-700'
                }`}>
                  <li className="line-clamp-2"><strong>Descrição:</strong> {campaign.referrer_campaign_description || '—'}</li>
                  {campaign.referrer_campaign_instructions && (
                    <li className="line-clamp-2"><strong>Instruções:</strong> {campaign.referrer_campaign_instructions}</li>
                  )}
                  <li><strong>Delay:</strong> {campaign.delay_minutes} minutos</li>
                  <li><strong>Máx. indicações:</strong> {campaign.max_referrals_per_request}</li>
                </ul>
              </div>

              {/* Referee card */}
              <div className={`rounded-2xl border p-4 shadow-xl ${
                isDark
                  ? 'border-gray-600 bg-gray-800'
                  : 'border-gray-200 bg-white'
              }`}>
                <div className="mb-3 flex items-center justify-between">
                  <h3 className={`text-sm font-semibold flex items-center gap-2 ${
                    isDark ? 'text-gray-200' : 'text-gray-800'
                  }`}>
                    <UserPlus className="h-4 w-4 text-brand" />
                    Para quem é Indicado
                  </h3>
                  <button
                    onClick={() => {
                      const currentScrollY = window.scrollY;
                      setExpandedSections(['referee']);
                      setIsEditing(true);
                      requestAnimationFrame(() => window.scrollTo(0, currentScrollY));
                    }}
                    className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                      isDark
                        ? 'border-gray-600 text-gray-300 hover:bg-gray-700'
                        : 'border-gray-200 text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    Editar
                  </button>
                </div>
                <ul className={`text-sm space-y-1 ${
                  isDark ? 'text-gray-300' : 'text-gray-700'
                }`}>
                  <li className="line-clamp-2"><strong>Descrição:</strong> {campaign.referee_campaign_description || '—'}</li>
                  {campaign.referee_campaign_instructions && (
                    <li className="line-clamp-2"><strong>Instruções:</strong> {campaign.referee_campaign_instructions}</li>
                  )}
                  <li><strong>Contato imediato:</strong> {campaign.contact_referees_immediately ? 'Sim' : 'Não'}</li>
                  {campaign.contact_referees_immediately && (
                    <li><strong>Delay:</strong> {campaign.referee_delay_minutes} minutos</li>
                  )}
                </ul>
              </div>
            </div>
          </div>
        ) : (
          /* Edit/Create mode - show form */
          <>
            {/* Basic Info */}
            <SectionContainer id="basic" title="Informações Básicas" icon={Target}>
              <Field label="Nome da Campanha" required hint="Ex: Programa de Indicação Premium">
                <Input
                  ref={campaignNameRef}
                  type="text"
                  name="campaign_name"
                  defaultValue={formData.campaign_name}
                  onBlur={handleCampaignNameBlur}
                  required
                  placeholder="Digite o nome da campanha"
                />
              </Field>
            </SectionContainer>

            {/* Referrer Section */}
            <SectionContainer id="referrer" title="Configurações para quem Indica" icon={Gift}>
              <div className="space-y-4">
                <Field label="Descrição da campanha" required hint="Texto que será usado para oferecer a campanha ao cliente">
                  <Textarea
                    ref={referrerDescRef}
                    name="referrer_campaign_description"
                    defaultValue={formData.referrer_campaign_description}
                    onBlur={handleReferrerDescBlur}
                    required
                    rows={3}
                    placeholder="Ex: Indique amigos e ganhe 20% de desconto na próxima consulta!"
                  />
                </Field>

                <Field label="Instruções para o agente" hint="Orientações específicas para o agente ao solicitar indicações">
                  <Textarea
                    ref={referrerInstrRef}
                    name="referrer_campaign_instructions"
                    defaultValue={formData.referrer_campaign_instructions}
                    onBlur={handleReferrerInstrBlur}
                    rows={2}
                    placeholder="Ex: Seja educado e ofereça apenas após confirmação do agendamento"
                  />
                </Field>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <Field label="Máximo de indicações por vez" hint="Quantas pessoas podem ser indicadas de uma vez">
                    <Input
                      ref={maxReferralsRef}
                      type="number"
                      name="max_referrals_per_request"
                      defaultValue={formData.max_referrals_per_request}
                      onBlur={handleMaxReferralsBlur}
                      min="1"
                      max="10"
                    />
                  </Field>

                  <Field label="Delay antes de solicitar (minutos)" hint="Tempo de espera antes de oferecer a campanha">
                    <Input
                      ref={delayMinutesRef}
                      type="number"
                      name="delay_minutes"
                      defaultValue={formData.delay_minutes}
                      onBlur={handleDelayMinutesBlur}
                      min="0"
                    />
                  </Field>
                </div>
              </div>
            </SectionContainer>

            {/* Referee Section */}
            <SectionContainer id="referee" title="Configurações para quem é Indicado" icon={UserPlus}>
              <div className="space-y-4">
                <Field label="Descrição da campanha" required hint="Texto que será enviado para o indicado">
                  <Textarea
                    ref={refereeDescRef}
                    name="referee_campaign_description"
                    defaultValue={formData.referee_campaign_description}
                    onBlur={handleRefereeDescBlur}
                    required
                    rows={3}
                    placeholder="Ex: Você foi indicado e ganhou 20% de desconto na primeira consulta!"
                  />
                </Field>

                <Field label="Instruções para o agente" hint="Orientações específicas para o agente ao contatar indicados">
                  <Textarea
                    ref={refereeInstrRef}
                    name="referee_campaign_instructions"
                    defaultValue={formData.referee_campaign_instructions}
                    onBlur={handleRefereeInstrBlur}
                    rows={2}
                    placeholder="Ex: Mencione o nome de quem indicou e seja cordial"
                  />
                </Field>

                <div className="space-y-4">
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      name="contact_referees_immediately"
                      checked={formData.contact_referees_immediately}
                      onChange={handleCheckboxChange}
                      className="rounded border-gray-300 text-brand focus:ring-brand"
                    />
                    <span className={`text-sm font-medium ${
                      isDark ? 'text-gray-300' : 'text-gray-700'
                    }`}>
                      Contatar indicados imediatamente
                    </span>
                  </label>

                  {formData.contact_referees_immediately && (
                    <Field label="Delay antes de contatar (minutos)" hint="Tempo de espera antes de contatar o indicado">
                      <Input
                        ref={refereeDelayRef}
                        type="number"
                        name="referee_delay_minutes"
                        defaultValue={formData.referee_delay_minutes}
                        onBlur={handleRefereeDelayBlur}
                        min="0"
                        className="md:w-1/2"
                      />
                    </Field>
                  )}
                </div>
              </div>
            </SectionContainer>

            {/* Help tip */}
            <div className={`rounded-2xl border p-4 ${
              isDark
                ? 'border-brand/30 bg-brand/10'
                : 'border-brand/20 bg-brand/5'
            }`}>
              <div className="flex gap-3">
                <HelpCircle className="w-5 h-5 text-brand flex-shrink-0 mt-0.5" />
                <div>
                  <h4 className="font-medium text-brand mb-1">Dica de configuração</h4>
                  <p className={`text-sm ${
                    isDark ? 'text-brand/90' : 'text-brand/80'
                  }`}>
                    {!campaign
                      ? "Ao criar esta campanha, ela será ativada automaticamente para a empresa."
                      : "Configure tempos de delay adequados para não ser invasivo com os clientes."
                    }
                  </p>
                </div>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Delete confirmation modal */}
      <ConfirmDeleteModal
        isOpen={showDeleteModal}
        onClose={() => setShowDeleteModal(false)}
        onConfirm={handleDelete}
        title="Excluir campanha de indicação"
        message="Tem certeza que deseja excluir esta campanha? Esta ação não pode ser desfeita e você precisará criar uma nova campanha."
        confirmText="Sim, excluir"
        cancelText="Cancelar"
      />
    </div>
  );
};

export default ReferralCampaigns;