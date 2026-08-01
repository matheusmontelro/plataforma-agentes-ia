import React, { useEffect, useState } from 'react';
import {
  formatBrowserDateTime,
  formatBrowserDateTimeTitle,
  parseBrowserDateTime,
  type BrowserDateTimeInput,
  type BrowserDateTimeVariant,
} from '../utils/browserDateTime.ts';

export interface BrowserDateTimeProps
  extends Omit<React.TimeHTMLAttributes<HTMLTimeElement>, 'children' | 'dateTime'> {
  fallback?: React.ReactNode;
  locale?: string;
  relativeTo?: Date;
  timeZone?: string;
  value: BrowserDateTimeInput;
  variant?: BrowserDateTimeVariant;
}

const BrowserDateTime: React.FC<BrowserDateTimeProps> = ({
  fallback = '—',
  locale = 'pt-BR',
  relativeTo,
  timeZone,
  title,
  value,
  variant = 'dateTime',
  ...timeProps
}) => {
  const [relativeNow, setRelativeNow] = useState(() => relativeTo || new Date());

  useEffect(() => {
    if (variant !== 'relative' || relativeTo) return undefined;
    const intervalId = window.setInterval(() => setRelativeNow(new Date()), 60_000);
    return () => window.clearInterval(intervalId);
  }, [relativeTo, variant]);

  const parsed = parseBrowserDateTime(value);
  const label = formatBrowserDateTime(value, {
    locale,
    relativeTo: relativeTo || relativeNow,
    timeZone,
    variant,
  });

  if (!parsed || !label) {
    return <time {...timeProps} title={title}>{fallback}</time>;
  }

  return (
    <time
      {...timeProps}
      dateTime={parsed.toISOString()}
      suppressHydrationWarning
      title={title || formatBrowserDateTimeTitle(parsed, locale, timeZone) || undefined}
    >
      {label}
    </time>
  );
};

export default BrowserDateTime;
