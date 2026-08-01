const cleanText = (value: string | undefined, fallback: string): string => {
  const normalized = (value || '').trim();
  return normalized || fallback;
};

export const branding = Object.freeze({
  appName: cleanText(import.meta.env.VITE_APP_NAME, 'SUA_EMPRESA'),
  appDescription: cleanText(
    import.meta.env.VITE_APP_DESCRIPTION,
    'Plataforma de atendimento, CRM e automacoes com IA',
  ),
  supportName: cleanText(import.meta.env.VITE_SUPPORT_NAME, 'Equipe de suporte'),
  supportEmail: cleanText(import.meta.env.VITE_SUPPORT_EMAIL, 'suporte@seu-dominio.com'),
  assets: Object.freeze({
    logoLight: '/branding/logo-light.svg',
    logoDark: '/branding/logo-dark.svg',
    icon: '/branding/icon.svg',
    iconWhite: '/branding/icon-white.svg',
  }),
});

export const applyBrandingToDocument = (): void => {
  if (typeof document === 'undefined') return;

  document.title = `${branding.appName} - ${branding.appDescription}`;

  const description = document.querySelector<HTMLMetaElement>('meta[name="description"]');
  if (description) description.content = `${branding.appName} - ${branding.appDescription}`;

  document.querySelectorAll<HTMLLinkElement>('link[rel="icon"], link[rel="apple-touch-icon"]').forEach((link) => {
    link.href = branding.assets.icon;
  });
};
