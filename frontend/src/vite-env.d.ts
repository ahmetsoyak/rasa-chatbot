/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_RASA_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
