// Canonical shadcn import path. Actual implementation lives in formatters.ts
// (already used by every other src/components/ui/* file) — re-exported here
// so drop-in shadcn components that import "@/lib/utils" work unmodified.
export { cn } from './formatters'
