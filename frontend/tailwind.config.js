import animate from 'tailwindcss-animate';

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{js,jsx,ts,tsx}',
  ],
  // Existing POC components build class names dynamically (e.g. `bg-${tone}-50`)
  // for deadline urgency and rejection-type chips. Safelist ONLY the shades
  // that actually appear via dynamic interpolation (grep `bg-${`). Static
  // class names (e.g. `bg-navy-900` in AppShell) are picked up by the JIT
  // scanner without help, so adding them here only inflates the CSS bundle.
  //
  // Dynamic call sites (grep `bg-\${`):
  //   • Analyze.jsx ResultSummaryBar: tone ∈ {rose, amber, emerald} → 100/700
  //   • DraftsPane.jsx tab chips: typeColor ∈ {rose, orange, amber, purple, slate}
  //     → 100/800  (orange = §103 obviousness, the most common rejection type)
  // Keep the regex tight; relaxing it later is cheap, shipping a +200 kB
  // CSS bundle to attorneys on 4G is not.
  safelist: [
    {
      pattern: /(bg|text)-(rose|orange|amber|emerald|purple|slate)-(100|700|800)/,
    },
  ],
  theme: {
    container: {
      center: true,
      padding: '2rem',
      screens: {
        '2xl': '1400px',
      },
    },
    extend: {
      fontFamily: {
        // Latin first, Noto Sans TC second so mixed zh/en strings render
        // with matching x-heights instead of system-font drift. The previous
        // CSS-fallback chain still wins inside `body {}` until components
        // opt into `font-sans` explicitly.
        sans: [
          'Inter',
          'Noto Sans TC',
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'Roboto',
          'sans-serif',
        ],
        mono: [
          'JetBrains Mono',
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'Consolas',
          'monospace',
        ],
      },
      colors: {
        // CHUNK-1 brand palette — conservative law firm, NOT modern startup.
        // Navy replaces indigo as the dominant brand color. Confidential-case
        // tint uses purple-700 (mapped via existing palette below).
        navy: {
          50: '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
        },
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      keyframes: {
        'accordion-down': {
          from: { height: '0' },
          to: { height: 'var(--radix-accordion-content-height)' },
        },
        'accordion-up': {
          from: { height: 'var(--radix-accordion-content-height)' },
          to: { height: '0' },
        },
      },
      animation: {
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up': 'accordion-up 0.2s ease-out',
      },
    },
  },
  plugins: [animate],
};
