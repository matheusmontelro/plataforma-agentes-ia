/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_APP_DESCRIPTION?: string;
  readonly VITE_APP_NAME?: string;
  readonly VITE_DEV_FORCE_ABSOLUTE_API?: string;
  readonly VITE_DEV_PROXY_TARGET?: string;
  readonly VITE_FORCE_ABSOLUTE_API?: string;
  readonly VITE_PUBLIC_APP_ORIGIN?: string;
  readonly VITE_SUPPORT_EMAIL?: string;
  readonly VITE_SUPPORT_NAME?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
