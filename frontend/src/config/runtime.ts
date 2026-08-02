const DEFAULT_DEV_PROXY_TARGET = 'http://127.0.0.1:8002';

export const BACKEND_PROXY_ROUTES = [
  '/api',
  '/auth',
  '/webhook',
  '/media-sources',
  '/health',
  '/ws',
  '/media',
  '/agents-sdk',
] as const;

function cleanUrl(rawValue?: string): string {
  return (rawValue || '').trim().replace(/^['"]|['"]$/g, '').replace(/\/+$/, '');
}

function readBoolean(rawValue?: string): boolean {
  return ['1', 'true', 'yes', 'on'].includes((rawValue || '').trim().toLowerCase());
}

function getBrowserOrigin(): string {
  if (typeof window === 'undefined') return '';
  return cleanUrl(window.location.origin);
}

function getBrowserHostname(): string {
  if (typeof window === 'undefined') return '';
  return window.location.hostname;
}

export function pointsToLocalhost(rawUrl: string): boolean {
  const normalized = cleanUrl(rawUrl);
  if (!normalized) return false;

  try {
    const parsed = new URL(normalized);
    return parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1';
  } catch {
    return /(localhost|127\.0\.0\.1)/i.test(normalized);
  }
}

const configuredApiUrl = cleanUrl(import.meta.env.VITE_API_URL);
const forceAbsoluteApi = readBoolean(import.meta.env.VITE_FORCE_ABSOLUTE_API)
  || readBoolean(import.meta.env.VITE_DEV_FORCE_ABSOLUTE_API);
const browserOrigin = getBrowserOrigin();
const browserHostname = getBrowserHostname();

function resolveApiBaseUrl(): string {
  if (forceAbsoluteApi && configuredApiUrl) {
    return configuredApiUrl;
  }

  return browserOrigin;
}

export const runtimeConfig = Object.freeze({
  mode: import.meta.env.MODE || (import.meta.env.DEV ? 'development' : 'production'),
  isDev: import.meta.env.DEV === true,
  isProd: import.meta.env.PROD === true,
  isLocalhost: browserHostname === 'localhost' || browserHostname === '127.0.0.1',
  apiBaseUrl: resolveApiBaseUrl(),
  apiMode: forceAbsoluteApi && configuredApiUrl ? 'absolute-env' : 'same-origin',
  configuredApiUrl,
  forceAbsoluteApi,
  devProxyTarget: cleanUrl(import.meta.env.VITE_DEV_PROXY_TARGET) || DEFAULT_DEV_PROXY_TARGET,
  publicAppOrigin: cleanUrl(import.meta.env.VITE_PUBLIC_APP_ORIGIN) || browserOrigin,
  backendProxyRoutes: BACKEND_PROXY_ROUTES,
});

export function getBackendWebSocketBaseUrl(apiBaseUrl = runtimeConfig.apiBaseUrl): string {
  const baseUrl = cleanUrl(apiBaseUrl);

  if (baseUrl) {
    if (baseUrl.startsWith('https://')) return baseUrl.replace(/^https:\/\//, 'wss://');
    if (baseUrl.startsWith('http://')) return baseUrl.replace(/^http:\/\//, 'ws://');
  }

  if (typeof window === 'undefined') return '';

  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${protocol}://${window.location.host}`;
}

export function toPublicAppUrl(path = ''): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return runtimeConfig.publicAppOrigin
    ? `${runtimeConfig.publicAppOrigin}${normalizedPath}`
    : normalizedPath;
}
