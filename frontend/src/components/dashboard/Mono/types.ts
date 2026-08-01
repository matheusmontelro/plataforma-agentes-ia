import type {
  DailyFunnelItem,
  FunnelBySourceItem,
  FunnelMetricsResponse,
  ProjectionsResponse,
  TimelineEvent,
} from '../../../services/api';
import type { PipelineStage } from '../../../services/crmApi';

export interface DashboardDateRange {
  endDate: string;
  startDate: string;
}

export interface DashboardStageRow extends PipelineStage {
  color: string;
  count: number;
  percentage: number;
  percentageBaseCount: number;
  percentageBaseLabel: string;
  reachedCount: number;
}

export interface SourceOption {
  label: string;
  value: string;
}

export interface MonoDashboardProps {
  averageTimeToSale: string;
  companyName: string;
  conversionRate: number;
  dailyFunnelData: DailyFunnelItem[];
  dateRange: DashboardDateRange;
  errorMessage?: string;
  funnelBySource: FunnelBySourceItem[];
  isDark: boolean;
  mediaSource: string;
  onDateChange: (startDate: string, endDate: string) => void;
  onRefresh: () => void;
  onShare: () => void;
  onSourceChange: (source: string) => void;
  onToggleFilters: () => void;
  periodLabel: string;
  projectionsData: ProjectionsResponse | null;
  revenueProjectionPercent: number;
  selectedSourceLabel: string;
  shareError?: string | null;
  showFilters: boolean;
  sourceOptions?: SourceOption[];
  stageRows: DashboardStageRow[];
  stages: PipelineStage[];
  stats: FunnelMetricsResponse;
  timelineEvents: TimelineEvent[];
  totalCurrentStageLeads: number;
}
