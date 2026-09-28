import type { Config } from 'tailwindcss'
import typography from '@tailwindcss/typography'

/**
 * Tailwind config — token-based, zero hardcoded hex values.
 * All colors reference CSS custom properties defined in src/styles/globals.css.
 */
const config: Config = {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        surface: {
          base:     'hsl(var(--color-surface-base) / <alpha-value>)',
          panel:    'hsl(var(--color-surface-panel) / <alpha-value>)',
          input:    'hsl(var(--color-surface-input) / <alpha-value>)',
          elevated: 'hsl(var(--color-surface-elevated) / <alpha-value>)',
        },
        border: {
          subtle:  'hsl(var(--color-border-subtle) / <alpha-value>)',
          default: 'hsl(var(--color-border-default) / <alpha-value>)',
          strong:  'hsl(var(--color-border-strong) / <alpha-value>)',
        },
        accent:   'hsl(var(--color-accent) / <alpha-value>)',
        critical: 'hsl(var(--color-critical) / <alpha-value>)',
        warning:  'hsl(var(--color-warning) / <alpha-value>)',
        stable:   'hsl(var(--color-stable) / <alpha-value>)',
        watch:    'hsl(var(--color-watch) / <alpha-value>)',
        fg: {
          base:    'hsl(var(--color-fg-base) / <alpha-value>)',
          muted:   'hsl(var(--color-fg-muted) / <alpha-value>)',
          dimmed:  'hsl(var(--color-fg-dimmed) / <alpha-value>)',
          inverse: 'hsl(var(--color-fg-inverse) / <alpha-value>)',
        },
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', '"Fira Code"', 'Consolas', 'monospace'],
      },
      // one type scale on a 16px root: 12px is the floor (xs), body is sm/base
      fontSize: {
        xs: ['0.75rem', { lineHeight: '1.125rem' }],
        sm: ['0.875rem', { lineHeight: '1.375rem' }],
        base: ['1rem', { lineHeight: '1.5rem' }],
      },
      spacing: {
        '18': '4.5rem',
        '22': '5.5rem',
      },
      // Sharp corners everywhere: every named radius is 0, so `rounded-*` classes are harmless no-ops and a new
      // panel or control needs no radius class at all. `full` keeps Tailwind's 9999px and is for true circles ONLY:
      // status and tier dots, gauge rings, avatars and initials, the chat launcher, the online dot, loading and
      // typing dots, the slider thumb, radio dots. Pills, chips, badges, tabs, bars, search fields, tooltips and
      // chat bubbles are square. Recharts and SVG shapes have no rx/ry or radius either.
      borderRadius: {
        DEFAULT: '0',
        sm: '0',
        md: '0',
        lg: '0',
        xl: '0',
        '2xl': '0',
        '3xl': '0',
      },
      boxShadow: {
        card: '0 1px 2px hsl(220 25% 15% / 0.04), 0 1px 3px hsl(220 25% 15% / 0.05)',
        pop: '0 8px 24px hsl(220 25% 15% / 0.12)',
      },
      keyframes: {
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'none' },
        },
      },
      animation: {
        // page on route change, cards on mount; off under prefers-reduced-motion (globals.css). Fill 'backwards', not
        // 'both': a filling animation keeps a stacking context and would trap fixed drawers under the top bar
        'page-in': 'fade-up 280ms cubic-bezier(0.22, 1, 0.36, 1) backwards',
        'card-in': 'fade-up 220ms cubic-bezier(0.22, 1, 0.36, 1) backwards',
      },
      ringColor: {
        accent: 'hsl(var(--color-accent) / <alpha-value>)',
      },
    },
  },
  plugins: [typography],
}

export default config
