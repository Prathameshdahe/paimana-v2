/// <reference types="vite/client" />

// ── Global Window Augmentation ─────────────────────────────────────────────
// Exposes mock data to browser DevTools for debugging.
// Only populated in development mode via src/mocks/index.ts.
import type { Project } from './contracts/project'

declare global {
  // this file is a module (it imports), so env typings must live in `declare global`
  interface ImportMetaEnv {
    readonly VITE_API_BASE?: string
  }

  interface Window {
    __PAIMANA_MOCKS__?: {
      projects: Project[]
    }
  }
}
