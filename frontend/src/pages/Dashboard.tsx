import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../contexts/ThemeContext.tsx';
import CommandDashboard, {
  CommandDashboardError,
  CommandDashboardLoading,
  type DashboardStageRow,
} from '../components/dashboard/CommandDashboard/CommandDashboard';
import MonoDashboard from '../components/dashboard/Mono/MonoDashboard';
import { MonoError as MonoDashboardError, MonoLoading as MonoDashboardLoading } from '../components/dashboard/Mono/States/MonoStates';
import ModernDashboard, {
  ModernDashboardError,
  ModernDashboardLoading,
} from '../components/dashboard/ModernDashboard/ModernDashboard';
import {
  getCompanyInfo,
  getDailyFunnel,
  getFunnelBySource,
  getFunnelMetrics,
  getProjections,
  getTimeBetweenStages,
  getTimeline,
  type DailyFunnelItem,
  type FunnelBySourceItem,
  type FunnelMetricsResponse,
  type ProjectionsResponse,
  type TimeBetweenStagesResponse,
  type TimelineEvent,
} from '../services/api';
import {
  crmApi,
  pipelineApi,
  type Lead,
  type LeadPipelineHistory,
  type PipelineStage,
} from '../services/crmApi.ts';
import { branding } from '../config/branding.ts';

function getStartOfCurrentMonth(): Date {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), 1);
}

function getEndOfCurrentMonth(): Date {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth() + 1, 0);
}

function formatDateToYYYYMMDD(date: Date): string {
  return date.toISOString().split('T')[0];
}

function formatDisplayDate(isoDate: string): string {
  const [year, month, day] = isoDate.split('-');
  if (!year || !month || !day) return isoDate;
  return `${day}/${month}/${year}`;
}

const REPORT_ACCENTS = ['#2563eb', '#0f766e', '#7c3aed', '#b45309', '#db2777', '#0891b2', '#16a34a'];

function getStageAccentColor(stage?: PipelineStage, index = 0): string {
  const fallback = REPORT_ACCENTS[index % REPORT_ACCENTS.length];
  if (!stage?.color) return fallback;

  if (stage.color.startsWith('#')) return stage.color;
  if (stage.color.includes('blue')) return '#2563eb';
  if (stage.color.includes('green')) return '#16a34a';
  if (stage.color.includes('yellow')) return '#ca8a04';
  if (stage.color.includes('red')) return '#dc2626';
  if (stage.color.includes('purple')) return '#7c3aed';
  if (stage.color.includes('pink')) return '#db2777';
  if (stage.color.includes('indigo')) return '#4f46e5';
  if (stage.color.includes('orange')) return '#ea580c';
  if (stage.color.includes('cyan')) return '#0891b2';
  if (stage.color.includes('teal')) return '#0f766e';
  return fallback;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

const DASHBOARD_VARIANT_KEY = 'agentive.dashboard.variant';
type DashboardVariant = 'modern' | 'mono' | 'command';

// Feature flag: 'modern' é o default; 'mono' e 'command' permanecem como rollback.
const readDashboardVariant = (): DashboardVariant => {
  if (typeof window === 'undefined') return 'modern';
  const stored = window.localStorage?.getItem(DASHBOARD_VARIANT_KEY);
  if (stored === 'mono' || stored === 'command') return stored;
  return 'modern';
};

const normalizeLeadName = (value?: string | null) => (value || '').trim().toLocaleLowerCase('pt-BR');

const resolveStoredLeadGender = (lead?: Lead): 'female' | 'male' | 'neutral' => {
  const genderField = lead?.custom_values?.find((field) => {
    const key = `${field.field_key || ''} ${field.field_name || ''}`
      .toLocaleLowerCase('pt-BR')
      .replace(/[_-]+/g, ' ');
    return /(^|\s)(g[eê]nero|genero|sexo|gender)(\s|$)/.test(key);
  });
  const value = String(genderField?.value || '').trim().toLocaleLowerCase('pt-BR');
  if (['female', 'feminino', 'feminina', 'mulher', 'f'].includes(value)) return 'female';
  if (['male', 'masculino', 'masculina', 'homem', 'm'].includes(value)) return 'male';
  return 'neutral';
};

const isWahaProfilePicture = (value?: string | null) => Boolean(
  value && value.includes('/media/profile-pictures/')
);

const enrichTimelineWithLeadAvatars = (events: TimelineEvent[], leads: Lead[]): TimelineEvent[] => {
  const byId = new Map(leads.map((lead) => [lead.id, lead]));
  const byUniqueName = new Map<string, Lead | null>();

  leads.forEach((lead) => {
    const key = normalizeLeadName(lead.name);
    if (!key) return;
    byUniqueName.set(key, byUniqueName.has(key) ? null : lead);
  });

  return events.map((event) => {
    const isLeadEvent = event.event_type.toLocaleLowerCase('pt-BR').includes('lead');
    const directLead = isLeadEvent ? byId.get(event.entity_id) : undefined;
    const namedLead = byUniqueName.get(normalizeLeadName(event.descricao)) || undefined;
    const lead = directLead || namedLead;
    const avatarUrl = isWahaProfilePicture(lead?.thumbnail_url) ? lead?.thumbnail_url : undefined;

    return {
      ...event,
      avatar_gender: resolveStoredLeadGender(lead),
      avatar_url: avatarUrl,
    };
  });
};

const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const { isDark } = useTheme();

  const [stats, setStats] = useState<FunnelMetricsResponse | null>(null);
  const [funnelBySource, setFunnelBySource] = useState<FunnelBySourceItem[]>([]);
  const [timelineEvents, setTimelineEvents] = useState<TimelineEvent[]>([]);
  const [projectionsData, setProjectionsData] = useState<ProjectionsResponse | null>(null);
  const [timeStagesData, setTimeStagesData] = useState<TimeBetweenStagesResponse | null>(null);
  const [dailyFunnelData, setDailyFunnelData] = useState<DailyFunnelItem[]>([]);

  const [stages, setStages] = useState<PipelineStage[]>([]);
  const [stageMetrics, setStageMetrics] = useState<Record<number, number>>({});
  const [stageReachMetrics, setStageReachMetrics] = useState<Record<number, number>>({});

  const [companyName, setCompanyName] = useState('Empresa');
  const [companyLogo, setCompanyLogo] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [shareError, setShareError] = useState<string | null>(null);
  const [showFilters, setShowFilters] = useState(false);
  const [dateRange, setDateRange] = useState({
    endDate: formatDateToYYYYMMDD(getEndOfCurrentMonth()),
    startDate: formatDateToYYYYMMDD(getStartOfCurrentMonth()),
  });
  const [mediaFilters, setMediaFilters] = useState({
    fonte: '',
  });

  useEffect(() => {
    const fetchCompanyInfo = async () => {
      try {
        const info = await getCompanyInfo();
        setCompanyName(info.name_company || info.name || 'Empresa');
        setCompanyLogo(info.logo_url || null);
      } catch (companyError) {
        console.error('Erro ao obter informações da empresa:', companyError);
        setCompanyName('Empresa');
        setCompanyLogo(null);
      }
    };

    fetchCompanyInfo();
  }, []);

  useEffect(() => {
    fetchAllMetrics();
  }, [dateRange, mediaFilters, navigate]);

  async function fetchAllMetrics() {
    setLoading(true);
    setError('');
    setShareError(null);

    try {
      const companyIdStr = localStorage.getItem('company_id') || localStorage.getItem('clinic_id');
      const companyId = Number(companyIdStr);
      if (!Number.isInteger(companyId) || companyId <= 0) {
        throw new Error('Selecione uma empresa válida antes de carregar o dashboard.');
      }

      const apiParams = {
        companyId,
        endDate: dateRange.endDate,
        startDate: dateRange.startDate,
        ...(mediaFilters.fonte && { fonte: mediaFilters.fonte }),
      };

      let pipelineStages: PipelineStage[] = [];
      try {
        const pipelines = await pipelineApi.getPipelines();
        if (pipelines && pipelines.length > 0) {
          const mainPipeline = pipelines[0];
          pipelineStages = mainPipeline.stages || [];
          setStages(pipelineStages);
        } else {
          setStages([]);
        }
      } catch (pipelineError) {
        console.error('Erro ao buscar pipelines:', pipelineError);
        setStages([]);
      }

      let leads: Lead[] = [];
      let leadHistory: LeadPipelineHistory[] = [];

      try {
        leads = await crmApi.getLeads();
      } catch (leadsError) {
        console.error('Erro ao buscar dados do CRM:', leadsError);
      }

      try {
        leadHistory = await crmApi.getLeadHistory(dateRange.startDate, dateRange.endDate);
      } catch (historyError) {
        console.error('Erro ao buscar histórico do CRM:', historyError);
      }

      const metricsByStage: Record<number, number> = {};
      const reachedLeadIdsByStage: Record<number, Set<number>> = {};
      const stageIds = new Set<number>();
      const stageById = new Map<number, PipelineStage>();
      const stageOrderById = new Map<number, number>();

      pipelineStages.forEach((stage, index) => {
        metricsByStage[stage.id] = 0;
        reachedLeadIdsByStage[stage.id] = new Set<number>();
        stageIds.add(stage.id);
        stageById.set(stage.id, stage);
        stageOrderById.set(stage.id, stage.order ?? index);
      });

      const startDateObj = new Date(dateRange.startDate);
      const endDateObj = new Date(dateRange.endDate);
      endDateObj.setHours(23, 59, 59, 999);

      const isDateWithinSelectedRange = (dateValue?: string | null) => {
        if (!dateValue) return false;

        const parsedDate = new Date(dateValue);
        return !Number.isNaN(parsedDate.getTime()) && parsedDate >= startDateObj && parsedDate <= endDateObj;
      };

      const matchesSourceFilter = (lead: Lead) => !mediaFilters.fonte || lead.source_id === mediaFilters.fonte;
      const getLeadEntryDate = (lead: Lead) => lead.data_entrada || null;
      const getLeadStageDate = (lead: Lead) =>
        lead.last_stage_move_at || lead.pipeline_entered_at || lead.created_at || lead.data_entrada || null;

      const leadsById = new Map<number, Lead>();
      const scopedLeadIds = new Set<number>();

      leads.forEach((lead) => {
        leadsById.set(lead.id, lead);

        if (matchesSourceFilter(lead) && isDateWithinSelectedRange(getLeadEntryDate(lead))) {
          scopedLeadIds.add(lead.id);
        }
      });

      leads.forEach((lead) => {
        const currentStageId = lead.current_stage_id;
        if (!currentStageId || !stageIds.has(currentStageId)) return;
        if (!matchesSourceFilter(lead)) return;

        const stageDateStr = getLeadStageDate(lead);
        if (!stageDateStr) return;

        if (isDateWithinSelectedRange(stageDateStr)) {
          metricsByStage[currentStageId]++;
        }
      });

      const historyByLeadId = new Map<number, LeadPipelineHistory[]>();

      leadHistory.forEach((historyItem) => {
        if (!isDateWithinSelectedRange(historyItem.moved_at)) return;

        const lead = leadsById.get(historyItem.lead_id);
        if (lead && !matchesSourceFilter(lead)) return;
        if (!scopedLeadIds.has(historyItem.lead_id)) return;

        const leadEvents = historyByLeadId.get(historyItem.lead_id) || [];
        leadEvents.push(historyItem);
        historyByLeadId.set(historyItem.lead_id, leadEvents);
      });

      const getStageOrder = (stageId: number) => stageOrderById.get(stageId) ?? Number.MAX_SAFE_INTEGER;

      const addStageToPath = (path: number[], stageId?: number | null) => {
        if (!stageId || !stageIds.has(stageId) || path.includes(stageId)) return;
        path.push(stageId);
      };

      const applyEffectiveStage = (path: number[], stageId?: number | null) => {
        if (!stageId || !stageIds.has(stageId)) return path;

        const stage = stageById.get(stageId);
        if (!stage) return path;

        if (stage.is_lost_stage || stage.is_converted_stage) {
          const nextPath = path.filter((existingStageId) => {
            const existingStage = stageById.get(existingStageId);
            return !existingStage?.is_lost_stage;
          });
          addStageToPath(nextPath, stageId);
          return nextPath;
        }

        const targetOrder = getStageOrder(stageId);
        const nextPath = path.filter((existingStageId) => {
          const existingStage = stageById.get(existingStageId);
          if (!existingStage || existingStage.is_lost_stage || existingStage.is_converted_stage) return false;
          return getStageOrder(existingStageId) <= targetOrder;
        });
        addStageToPath(nextPath, stageId);
        return nextPath;
      };

      scopedLeadIds.forEach((leadId) => {
        const lead = leadsById.get(leadId);
        if (!lead) return;

        let effectivePath: number[] = [];
        const leadEvents = (historyByLeadId.get(leadId) || []).sort((first, second) => {
          const firstTime = new Date(first.moved_at).getTime();
          const secondTime = new Date(second.moved_at).getTime();
          return firstTime - secondTime;
        });

        leadEvents.forEach((historyItem) => {
          addStageToPath(effectivePath, historyItem.from_stage_id);
          effectivePath = applyEffectiveStage(effectivePath, historyItem.to_stage_id);
        });

        const currentStageDate = getLeadStageDate(lead);
        if (isDateWithinSelectedRange(currentStageDate)) {
          effectivePath = applyEffectiveStage(effectivePath, lead.current_stage_id);
        }

        effectivePath.forEach((stageId) => {
          reachedLeadIdsByStage[stageId].add(leadId);
        });
      });

      const reachMetricsByStage: Record<number, number> = {};
      pipelineStages.forEach((stage) => {
        reachMetricsByStage[stage.id] = reachedLeadIdsByStage[stage.id].size;
      });

      setStageMetrics(metricsByStage);
      setStageReachMetrics(reachMetricsByStage);

      const [funnelData, timelineData, projections, timeBetween, funnelMain, dailyData] = await Promise.all([
        getFunnelBySource(companyId, dateRange.startDate, dateRange.endDate, mediaFilters.fonte || undefined),
        getTimeline(companyId, dateRange.startDate, dateRange.endDate, 10),
        getProjections(companyId),
        getTimeBetweenStages(companyId, dateRange.startDate, dateRange.endDate),
        getFunnelMetrics(apiParams),
        getDailyFunnel(companyId, dateRange.startDate, dateRange.endDate, mediaFilters.fonte || undefined),
      ]);

      setFunnelBySource(funnelData);
      setTimelineEvents(enrichTimelineWithLeadAvatars(timelineData, leads));
      setProjectionsData(projections);
      setTimeStagesData(timeBetween);
      setStats(funnelMain);
      setDailyFunnelData(dailyData);
      setLoading(false);
    } catch (metricsError: any) {
      console.error('Erro ao obter métricas:', metricsError);
      setError('Não foi possível carregar as métricas. Verifique sua conexão ou tente novamente mais tarde.');
      setLoading(false);
      if (metricsError.response?.status === 401) {
        localStorage.removeItem('token');
        navigate('/');
      }
    }
  }

  const handleDateChange = (newStartDate: string, newEndDate: string) => {
    setDateRange({
      endDate: newEndDate,
      startDate: newStartDate,
    });
  };

  const handleRefresh = () => {
    fetchAllMetrics();
  };

  const handleSourceChange = (fonte: string) => {
    setMediaFilters({ fonte });
  };

  const generateShareImage = async () => {
    if (!stats) return;

    try {
      setShareError(null);

      const shareElement = document.createElement('div');
      shareElement.style.position = 'fixed';
      shareElement.style.top = '-9999px';
      shareElement.style.left = '-9999px';
      shareElement.style.width = '540px';
      shareElement.style.height = '960px';
      shareElement.style.fontFamily = 'Inter, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif';

      const safeCompanyName = escapeHtml(companyName);
      const safeAppName = escapeHtml(branding.appName);
      const safeLogo = companyLogo ? escapeHtml(companyLogo) : '';
      const safePeriod = escapeHtml(`${formatDisplayDate(dateRange.startDate)} - ${formatDisplayDate(dateRange.endDate)}`);
      const conversionRate = stats.totalLeads > 0 ? (stats.totalVendas / stats.totalLeads) * 100 : 0;

      shareElement.innerHTML = `
        <div style="width:540px;height:960px;background:#f7f7f7;color:#020323;padding:34px;box-sizing:border-box;">
          <div style="height:100%;border:1px solid rgba(2,3,35,.1);border-radius:10px;background:#fff;overflow:hidden;box-shadow:0 10px 30px rgba(2,3,35,.08);">
            <div style="padding:28px;border-bottom:1px solid rgba(2,3,35,.1);background:#020323;color:#fff;">
              <div style="display:flex;align-items:center;gap:14px;margin-bottom:38px;">
                ${safeLogo ? `<img src="${safeLogo}" style="width:46px;height:46px;border-radius:8px;object-fit:cover;background:#fff;" />` : `<div style="width:46px;height:46px;border-radius:8px;background:#fff;color:#020323;display:grid;place-items:center;font-weight:700;">AI</div>`}
                <div>
                  <div style="font-size:15px;font-weight:700;line-height:1.2;">${safeCompanyName}</div>
                  <div style="font-size:11px;color:rgba(255,255,255,.62);margin-top:4px;">Criado com ${safeAppName}</div>
                </div>
              </div>
              <div style="font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:rgba(255,255,255,.55);font-weight:700;">Performance do período</div>
              <div style="font-size:44px;font-weight:500;line-height:1.05;margin-top:10px;">${stats.valorFaturado.toLocaleString('pt-BR', { currency: 'BRL', maximumFractionDigits: 0, style: 'currency' })}</div>
              <div style="font-size:13px;color:rgba(255,255,255,.68);margin-top:12px;">${safePeriod}</div>
            </div>
            <div style="padding:26px;display:grid;gap:16px;">
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
                <div style="border:1px solid rgba(2,3,35,.1);border-radius:8px;padding:18px;">
                  <div style="font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:rgba(2,3,35,.48);font-weight:700;">Leads</div>
                  <div style="font-size:32px;font-weight:500;margin-top:10px;">${stats.totalLeads.toLocaleString('pt-BR')}</div>
                </div>
                <div style="border:1px solid rgba(2,3,35,.1);border-radius:8px;padding:18px;">
                  <div style="font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:rgba(2,3,35,.48);font-weight:700;">Vendas</div>
                  <div style="font-size:32px;font-weight:500;margin-top:10px;">${stats.totalVendas.toLocaleString('pt-BR')}</div>
                </div>
              </div>
              <div style="border:1px solid rgba(2,3,35,.1);border-radius:8px;padding:18px;">
                <div style="font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:rgba(2,3,35,.48);font-weight:700;">Conversão</div>
                <div style="font-size:34px;font-weight:500;margin-top:10px;color:#0f766e;">${conversionRate.toFixed(1)}%</div>
                <div style="height:8px;border-radius:999px;background:rgba(2,3,35,.08);overflow:hidden;margin-top:16px;">
                  <div style="height:100%;width:${Math.min(conversionRate, 100)}%;background:#0f766e;border-radius:999px;"></div>
                </div>
              </div>
              <div style="display:grid;gap:10px;margin-top:6px;">
                ${stageRowsForShare(stats, stages, stageMetrics, stageReachMetrics).slice(0, 5).map((stage) => `
                  <div style="display:flex;justify-content:space-between;gap:14px;border-bottom:1px solid rgba(2,3,35,.08);padding-bottom:10px;">
                    <span style="font-size:13px;color:rgba(2,3,35,.68);">${escapeHtml(stage.name)}</span>
                    <strong style="font-size:13px;">${stage.count.toLocaleString('pt-BR')}</strong>
                  </div>
                `).join('')}
              </div>
            </div>
          </div>
        </div>
      `;

      document.body.appendChild(shareElement);

      // Aguarda as fontes (Lexend/Inter) com timeout — não trava o botão se a rede falhar.
      await Promise.race([
        typeof document !== 'undefined' && document.fonts ? document.fonts.ready : Promise.resolve(),
        new Promise((resolve) => setTimeout(resolve, 2500)),
      ]);

      const html2canvas = (await import('html2canvas')).default;
      const canvas = await html2canvas(shareElement, {
        backgroundColor: null,
        logging: false,
        scale: 2,
        useCORS: true,
      } as any);

      document.body.removeChild(shareElement);

      canvas.toBlob(async (blob) => {
        if (!blob) return;

        const file = new File([blob], `relatorio-performance-${Date.now()}.png`, { type: 'image/png' });

        if (navigator.share && navigator.canShare?.({ files: [file] })) {
          try {
            await navigator.share({
              files: [file],
              text: `Performance ${companyName} - ${formatDisplayDate(dateRange.startDate)} a ${formatDisplayDate(dateRange.endDate)}`,
              title: 'Relatório de performance',
            });
            return;
          } catch (shareException: any) {
            if (shareException?.name === 'AbortError') return;
            console.error('Erro ao compartilhar:', shareException);
          }
        }

        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `relatorio-performance-${Date.now()}.png`;
        anchor.click();
        URL.revokeObjectURL(url);
      }, 'image/png');
    } catch (shareException) {
      console.error('Erro ao gerar imagem:', shareException);
      setShareError('Não foi possível gerar a imagem para compartilhamento. Tente novamente em instantes.');
    }
  };

  const stageRows = useMemo<DashboardStageRow[]>(() => {
    if (!stats) return [];

    return stages.map((stage, index) => {
      const count = stageMetrics[stage.id] || 0;
      const reachedCount = stageReachMetrics[stage.id] || 0;
      const percentageBaseStageId = stage.percentage_base_stage_id ?? null;
      const percentageBaseCount = percentageBaseStageId ? (stageReachMetrics[percentageBaseStageId] || 0) : stats.totalLeads;
      const percentage = percentageBaseCount > 0 ? (reachedCount / percentageBaseCount) * 100 : 0;
      const percentageBaseLabel = percentageBaseStageId
        ? stages.find((baseStage) => baseStage.id === percentageBaseStageId)?.name || 'Leads'
        : 'Leads';

      return {
        ...stage,
        color: getStageAccentColor(stage, index),
        count,
        percentage,
        percentageBaseCount,
        percentageBaseLabel,
        reachedCount,
      };
    });
  }, [stageMetrics, stageReachMetrics, stages, stats]);

  const dashboardVariant = readDashboardVariant();

  if (loading) {
    return dashboardVariant === 'modern' ? (
      <ModernDashboardLoading isDark={isDark} />
    ) : dashboardVariant === 'mono' ? (
      <MonoDashboardLoading isDark={isDark} />
    ) : (
      <CommandDashboardLoading isDark={isDark} />
    );
  }

  if (error || !stats) {
    return dashboardVariant === 'modern' ? (
      <ModernDashboardError
        error={error || 'Não foi possível carregar as métricas.'}
        isDark={isDark}
        onRefresh={handleRefresh}
      />
    ) : dashboardVariant === 'mono' ? (
      <MonoDashboardError
        error={error || 'Não foi possível carregar as métricas.'}
        isDark={isDark}
        onRefresh={handleRefresh}
      />
    ) : (
      <CommandDashboardError
        error={error || 'Não foi possível carregar as métricas.'}
        isDark={isDark}
        onRefresh={handleRefresh}
      />
    );
  }

  const periodLabel = `${formatDisplayDate(dateRange.startDate)} - ${formatDisplayDate(dateRange.endDate)}`;
  const selectedSourceLabel = mediaFilters.fonte
    ? mediaFilters.fonte.charAt(0).toUpperCase() + mediaFilters.fonte.slice(1)
    : 'Todas as origens';
  const conversionRate = stats.totalLeads > 0 ? (stats.totalVendas / stats.totalLeads) * 100 : 0;
  const totalCurrentStageLeads = stageRows.reduce((sum, stage) => sum + stage.count, 0);
  const revenueProjectionPercent = projectionsData?.faturadoProjection
    ? Math.min((projectionsData.faturadoSoFar / projectionsData.faturadoProjection) * 100, 100)
    : 0;
  const averageTimeToSale = timeStagesData?.leadToVenda
    ? `${timeStagesData.leadToVenda.toFixed(1)} dias`
    : 'Sem dados';

  if (dashboardVariant === 'modern') {
    return (
      <ModernDashboard
        averageTimeToSale={averageTimeToSale}
        companyName={companyName}
        conversionRate={conversionRate}
        dailyFunnelData={dailyFunnelData}
        dateRange={dateRange}
        funnelBySource={funnelBySource}
        isDark={isDark}
        mediaSource={mediaFilters.fonte}
        onDateChange={handleDateChange}
        onRefresh={handleRefresh}
        onShare={generateShareImage}
        onSourceChange={handleSourceChange}
        onToggleFilters={() => setShowFilters((current) => !current)}
        periodLabel={periodLabel}
        projectionsData={projectionsData}
        revenueProjectionPercent={revenueProjectionPercent}
        selectedSourceLabel={selectedSourceLabel}
        shareError={shareError}
        showFilters={showFilters}
        stageRows={stageRows}
        stages={stages}
        stats={stats}
        timelineEvents={timelineEvents}
        totalCurrentStageLeads={totalCurrentStageLeads}
      />
    );
  }

  if (dashboardVariant === 'mono') {
    return (
      <MonoDashboard
        averageTimeToSale={averageTimeToSale}
        companyName={companyName}
        conversionRate={conversionRate}
        dailyFunnelData={dailyFunnelData}
        dateRange={dateRange}
        funnelBySource={funnelBySource}
        isDark={isDark}
        mediaSource={mediaFilters.fonte}
        onDateChange={handleDateChange}
        onRefresh={handleRefresh}
        onShare={generateShareImage}
        onSourceChange={handleSourceChange}
        onToggleFilters={() => setShowFilters((current) => !current)}
        periodLabel={periodLabel}
        projectionsData={projectionsData}
        revenueProjectionPercent={revenueProjectionPercent}
        selectedSourceLabel={selectedSourceLabel}
        shareError={shareError}
        showFilters={showFilters}
        stageRows={stageRows}
        stages={stages}
        stats={stats}
        timelineEvents={timelineEvents}
        totalCurrentStageLeads={totalCurrentStageLeads}
      />
    );
  }

  return (
    <CommandDashboard
      averageTimeToSale={averageTimeToSale}
      companyName={companyName}
      conversionRate={conversionRate}
      dailyFunnelData={dailyFunnelData}
      dateRange={dateRange}
      funnelBySource={funnelBySource}
      isDark={isDark}
      mediaSource={mediaFilters.fonte}
      onDateChange={handleDateChange}
      onRefresh={handleRefresh}
      onShare={generateShareImage}
      onSourceChange={handleSourceChange}
      onToggleFilters={() => setShowFilters((current) => !current)}
      periodLabel={periodLabel}
      projectionsData={projectionsData}
      revenueProjectionPercent={revenueProjectionPercent}
      selectedSourceLabel={selectedSourceLabel}
      shareError={shareError}
      showFilters={showFilters}
      stageRows={stageRows}
      stages={stages}
      stats={stats}
      timelineEvents={timelineEvents}
      totalCurrentStageLeads={totalCurrentStageLeads}
    />
  );
};

function stageRowsForShare(
  stats: FunnelMetricsResponse,
  stages: PipelineStage[],
  stageMetrics: Record<number, number>,
  stageReachMetrics: Record<number, number>,
) {
  return stages.map((stage, index) => {
    const count = stageMetrics[stage.id] || 0;
    const reachedCount = stageReachMetrics[stage.id] || 0;
    const percentageBaseStageId = stage.percentage_base_stage_id ?? null;
    const percentageBaseCount = percentageBaseStageId ? (stageReachMetrics[percentageBaseStageId] || 0) : stats.totalLeads;
    const percentage = percentageBaseCount > 0 ? (reachedCount / percentageBaseCount) * 100 : 0;

    return {
      color: getStageAccentColor(stage, index),
      count,
      name: stage.name,
      percentage,
    };
  });
}

export default Dashboard;
