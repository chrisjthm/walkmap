/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_MAP_STYLE_URL?: string;
  readonly VITE_E2E?: string;
  readonly VITE_E2E_MOCK_MAP?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
