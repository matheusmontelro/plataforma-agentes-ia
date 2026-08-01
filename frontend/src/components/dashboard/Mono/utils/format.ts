// Mono — formatação centralizada (locale pt-BR).
// Lexend/Inter tabular-nums é aplicado via classe .mono-num no CSS.

const safe = (value: number) => (Number.isFinite(value) ? value : 0);

const currencyFormatter = new Intl.NumberFormat('pt-BR', {
  currency: 'BRL',
  maximumFractionDigits: 0,
  style: 'currency',
});

const numberFormatter = new Intl.NumberFormat('pt-BR');

export const formatCurrency = (value: number) => currencyFormatter.format(safe(value));

export const formatNumber = (value: number) => numberFormatter.format(safe(value));

export const formatCompactNumber = (value: number) =>
  new Intl.NumberFormat('pt-BR', {
    maximumFractionDigits: 1,
    notation: Math.abs(safe(value)) >= 10000 ? 'compact' : 'standard',
  }).format(safe(value));

export const formatPercent = (value: number, digits = 1) => `${safe(value).toFixed(digits)}%`;

export const clampPercent = (value: number) => Math.max(0, Math.min(value, 100));

export const formatDisplayDate = (isoDate: string) => {
  const [year, month, day] = (isoDate || '').split('-');
  if (!year || !month || !day) return isoDate;
  return `${day}/${month}/${year}`;
};

export const formatDateToYYYYMMDD = (date: Date) => date.toISOString().split('T')[0];

/** O indicador LIVE só é válido se o timestamp existir e for mais recente que 5 minutos. */
export const isLiveRecent = (liveTimestamp?: string): boolean => {
  if (!liveTimestamp) return false;
  const parsed = new Date(liveTimestamp).getTime();
  if (!Number.isFinite(parsed)) return false;
  return Date.now() - parsed < 5 * 60 * 1000;
};
