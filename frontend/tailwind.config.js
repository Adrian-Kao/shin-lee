import animate from 'tailwindcss-animate';

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{js,jsx,ts,tsx}',
  ],
  // Day 12E — safelist removed. The deadline-urgency (Analyze.jsx
  // DEADLINE_TONE) and rejection-type (DraftsPane.jsx REJECTION_TYPE_CHIP)
  // chips no longer build class names via `bg-${tone}` interpolation; every
  // tone variant — including the new dark: shades — is now a literal string in
  // a static map, so the Tailwind JIT scanner picks them all up directly. With
  // no dynamic call sites left (grep `bg-\${` / `text-\${` finds only comments),
  // a safelist would only risk silently shipping unused utility classes. If a
  // future feature reintroduces interpolated colour classes, re-add a TIGHT
  // pattern here rather than a broad one — a loose safelist was the Day 9C
  // +130 kB CSS bundle leak.
  theme: {
    container: {
      center: true,
      padding: '2rem',
      screens: {
        '2xl': '1400px',
      },
    },
    extend: {
      // Named micro type-scale tokens — replace ad-hoc `text-[9/10/11px]`
      // magic numbers with a small, consistent scale below Tailwind's
      // `text-xs` (12px). Sizes match the previous arbitrary values so the
      // swap is visually neutral. Dense legal UI (case IDs, chips, audit
      // tables) lives in this band; keeping it named is the whole point.
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }], // 11px
        '3xs': ['0.625rem', { lineHeight: '0.875rem' }], // 10px
      },
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
