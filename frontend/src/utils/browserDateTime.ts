export type BrowserDateTimeInput = Date | string | number | null | undefined;
export type BrowserDateTimeVariant = 'time' | 'date' | 'dateTime' | 'relative';

const DEFAULT_LOCALE = 'pt-BR';
const DEFAULT_TIME_ZONE = 'UTC';

export const isValidTimeZone = (value?: string | null): value is string => {
  if (!value) return false;
  try {
    new Intl.DateTimeFormat(DEFAULT_LOCALE, { timeZone: value }).format();
    return true;
  } catch {
    return false;
  }
};

export const getBrowserTimeZone = (): string => {
  if (typeof Intl === 'undefined') return DEFAULT_TIME_ZONE;
  const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return isValidTimeZone(detected) ? detected : DEFAULT_TIME_ZONE;
};

export const resolveBrowserTimeZone = (value?: string | null): string =>
  isValidTimeZone(value) ? value : getBrowserTimeZone();

export const parseBrowserDateTime = (value: BrowserDateTimeInput): Date | null => {
  if (value === null || value === undefined || value === '') return null;
  const parsed = value instanceof Date ? new Date(value.getTime()) : new Date(value);
  return Number.isFinite(parsed.getTime()) ? parsed : null;
};

const formatRelativeDateTime = (date: Date, locale: string, relativeTo: Date): string => {
  const diffMs = date.getTime() - relativeTo.getTime();
  const absoluteMs = Math.abs(diffMs);
  const units: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ['year', 365 * 24 * 60 * 60 * 1000],
    ['month', 30 * 24 * 60 * 60 * 1000],
    ['week', 7 * 24 * 60 * 60 * 1000],
    ['day', 24 * 60 * 60 * 1000],
    ['hour', 60 * 60 * 1000],
    ['minute', 60 * 1000],
    ['second', 1000],
  ];
  const [unit, unitMs] = units.find(([, threshold]) => absoluteMs >= threshold) || units[units.length - 1];
  const amount = Math.round(diffMs / unitMs);

  return new Intl.RelativeTimeFormat(locale, {
    numeric: 'auto',
    style: 'long',
  }).format(amount, unit);
};

interface FormatBrowserDateTimeOptions {
  locale?: string;
  relativeTo?: Date;
  timeZone?: string;
  variant?: BrowserDateTimeVariant;
}

export const formatBrowserDateTime = (
  value: BrowserDateTimeInput,
  options: FormatBrowserDateTimeOptions = {},
): string | null => {
  const date = parseBrowserDateTime(value);
  if (!date) return null;

  const locale = options.locale || DEFAULT_LOCALE;
  const variant = options.variant || 'dateTime';
  if (variant === 'relative') {
    return formatRelativeDateTime(date, locale, options.relativeTo || new Date());
  }

  const timeZone = resolveBrowserTimeZone(options.timeZone);
  const formatOptions: Intl.DateTimeFormatOptions = variant === 'time'
    ? { hour: '2-digit', minute: '2-digit', timeZone }
    : variant === 'date'
      ? { day: '2-digit', month: '2-digit', year: 'numeric', timeZone }
      : {
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          month: '2-digit',
          timeZone,
          year: 'numeric',
        };

  return new Intl.DateTimeFormat(locale, formatOptions).format(date);
};

export const formatBrowserDateTimeTitle = (
  value: BrowserDateTimeInput,
  locale = DEFAULT_LOCALE,
  timeZone?: string,
): string | null => {
  const date = parseBrowserDateTime(value);
  if (!date) return null;
  const resolvedTimeZone = resolveBrowserTimeZone(timeZone);
  const formatted = new Intl.DateTimeFormat(locale, {
    dateStyle: 'full',
    timeStyle: 'medium',
    timeZone: resolvedTimeZone,
  }).format(date);
  return `${formatted} (${resolvedTimeZone})`;
};
