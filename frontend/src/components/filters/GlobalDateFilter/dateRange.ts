export type GlobalDatePreset =
  | 'all'
  | 'today'
  | 'yesterday'
  | 'thisWeek'
  | 'lastWeek'
  | 'thisMonth'
  | 'lastMonth'
  | 'custom';

export interface GlobalDateRange {
  startDate: Date | null;
  endDate: Date | null;
}

export interface GlobalDateFilterValue {
  preset: GlobalDatePreset;
  range: GlobalDateRange;
}

export const GLOBAL_DATE_PRESET_LABELS: Record<GlobalDatePreset, string> = {
  all: 'Todas as datas',
  today: 'Hoje',
  yesterday: 'Ontem',
  thisWeek: 'Esta semana',
  lastWeek: 'Semana passada',
  thisMonth: 'Este mês',
  lastMonth: 'Mês passado',
  custom: 'Personalizado',
};

export const GLOBAL_DATE_QUICK_PRESETS: GlobalDatePreset[] = [
  'today',
  'yesterday',
  'thisWeek',
  'lastWeek',
  'thisMonth',
  'lastMonth',
];

const startOfLocalDay = (date: Date) => {
  const next = new Date(date);
  next.setHours(0, 0, 0, 0);
  return next;
};

const endOfLocalDay = (date: Date) => {
  const next = new Date(date);
  next.setHours(23, 59, 59, 999);
  return next;
};

const startOfMondayWeek = (date: Date) => {
  const next = startOfLocalDay(date);
  const offset = next.getDay() === 0 ? -6 : 1 - next.getDay();
  next.setDate(next.getDate() + offset);
  return next;
};

export const createEmptyGlobalDateRange = (): GlobalDateRange => ({
  startDate: null,
  endDate: null,
});

export const resolveGlobalDatePreset = (
  preset: GlobalDatePreset,
  referenceDate = new Date(),
): GlobalDateRange => {
  const today = startOfLocalDay(referenceDate);

  if (preset === 'today') {
    return { startDate: today, endDate: endOfLocalDay(today) };
  }

  if (preset === 'yesterday') {
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);
    return { startDate: startOfLocalDay(yesterday), endDate: endOfLocalDay(yesterday) };
  }

  if (preset === 'thisWeek' || preset === 'lastWeek') {
    const weekStart = startOfMondayWeek(today);
    if (preset === 'lastWeek') weekStart.setDate(weekStart.getDate() - 7);
    const weekEnd = new Date(weekStart);
    weekEnd.setDate(weekEnd.getDate() + 6);
    return { startDate: weekStart, endDate: endOfLocalDay(weekEnd) };
  }

  if (preset === 'thisMonth' || preset === 'lastMonth') {
    const monthOffset = preset === 'lastMonth' ? -1 : 0;
    const monthStart = new Date(today.getFullYear(), today.getMonth() + monthOffset, 1);
    const monthEnd = new Date(today.getFullYear(), today.getMonth() + monthOffset + 1, 0);
    return { startDate: startOfLocalDay(monthStart), endDate: endOfLocalDay(monthEnd) };
  }

  return createEmptyGlobalDateRange();
};

export const createCustomGlobalDateRange = (startValue: string, endValue: string): GlobalDateRange | null => {
  if (!startValue || !endValue) return null;
  const startDate = startOfLocalDay(new Date(`${startValue}T00:00:00`));
  const endDate = endOfLocalDay(new Date(`${endValue}T00:00:00`));
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime()) || endDate < startDate) return null;
  return { startDate, endDate };
};

export const toGlobalDateInputValue = (date: Date | null) => {
  if (!date || Number.isNaN(date.getTime())) return '';
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
};

const formatCompactDate = (date: Date) => date.toLocaleDateString('pt-BR', {
  day: '2-digit',
  month: '2-digit',
  year: '2-digit',
});

export const formatGlobalDateFilterLabel = ({ preset, range }: GlobalDateFilterValue) => {
  if (preset !== 'custom') return GLOBAL_DATE_PRESET_LABELS[preset];
  if (!range.startDate || !range.endDate) return GLOBAL_DATE_PRESET_LABELS.custom;
  return `${formatCompactDate(range.startDate)} – ${formatCompactDate(range.endDate)}`;
};
