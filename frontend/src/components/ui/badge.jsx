import * as React from 'react';

import { cn } from '../../lib/utils';

/**
 * Status badge / chip — the single source of truth for tone→class mapping.
 *
 * Before this component each call site (AppShell TrustChip, ClaimTree rows,
 * InputPane quota) hard-coded its own `bg-x-50 text-x-800 ring-x-200` strings,
 * and a few interpolated `bg-${tone}-100` (invisible to the Tailwind JIT
 * scanner). STATUS_TONE centralises the conservative law-firm palette and
 * keeps every class string static so JIT picks them all up at build time.
 *
 * Tones (semantic, not raw colour names):
 *   success      → emerald   (clean / verified)
 *   warning      → amber     (cascade risk / quota high)
 *   error        → rose      (rejected / failed)
 *   info         → sky       (neutral informational)
 *   brand        → navy      (primary brand accent, e.g. redaction-on)
 *   confidential → purple    (confidential-case routing)
 *   neutral      → slate     (default fallback)
 *
 * `variant`:
 *   soft    (default) — tinted background + ring, dark text (the chip look)
 *   solid             — saturated background, white text (the loud tag look)
 *   outline           — transparent background, coloured ring + text
 */
const STATUS_TONE = {
  success: {
    soft: 'bg-emerald-50 text-emerald-800 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:ring-emerald-800',
    solid: 'bg-emerald-600 text-white ring-emerald-700',
    outline: 'bg-transparent text-emerald-700 ring-emerald-300 dark:text-emerald-300 dark:ring-emerald-800',
  },
  warning: {
    soft: 'bg-amber-50 text-amber-800 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:ring-amber-800',
    solid: 'bg-amber-500 text-white ring-amber-600',
    outline: 'bg-transparent text-amber-700 ring-amber-300 dark:text-amber-300 dark:ring-amber-800',
  },
  error: {
    soft: 'bg-rose-50 text-rose-700 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:ring-rose-800',
    solid: 'bg-rose-600 text-white ring-rose-700',
    outline: 'bg-transparent text-rose-700 ring-rose-300 dark:text-rose-300 dark:ring-rose-800',
  },
  info: {
    soft: 'bg-sky-50 text-sky-800 ring-sky-200 dark:bg-sky-950/40 dark:text-sky-300 dark:ring-sky-800',
    solid: 'bg-sky-600 text-white ring-sky-700',
    outline: 'bg-transparent text-sky-700 ring-sky-300 dark:text-sky-300 dark:ring-sky-800',
  },
  brand: {
    soft: 'bg-navy-50 text-navy-900 ring-navy-200 dark:bg-navy-900/40 dark:text-navy-200 dark:ring-navy-800',
    solid: 'bg-navy-700 text-white ring-navy-800',
    outline: 'bg-transparent text-navy-700 ring-navy-300 dark:text-navy-200 dark:ring-navy-800',
  },
  confidential: {
    soft: 'bg-purple-50 text-purple-800 ring-purple-200 dark:bg-purple-950/40 dark:text-purple-300 dark:ring-purple-800',
    solid: 'bg-purple-600 text-white ring-purple-700',
    outline: 'bg-transparent text-purple-700 ring-purple-300 dark:text-purple-300 dark:ring-purple-800',
  },
  neutral: {
    soft: 'bg-slate-100 text-slate-700 ring-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700',
    solid: 'bg-slate-600 text-white ring-slate-700',
    outline: 'bg-transparent text-slate-600 ring-slate-300 dark:text-slate-300 dark:ring-slate-600',
  },
};

/**
 * @param {object}  props
 * @param {keyof typeof STATUS_TONE} [props.tone='neutral']
 * @param {'soft'|'solid'|'outline'} [props.variant='soft']
 * @param {React.ReactNode} [props.children]
 * @param {string} [props.className]
 */
const Badge = React.forwardRef(
  ({ className, tone = 'neutral', variant = 'soft', ...props }, ref) => {
    const toneMap = STATUS_TONE[tone] || STATUS_TONE.neutral;
    const toneClasses = toneMap[variant] || toneMap.soft;
    return (
      <span
        ref={ref}
        className={cn(
          'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1',
          toneClasses,
          className
        )}
        {...props}
      />
    );
  }
);
Badge.displayName = 'Badge';

export { Badge, STATUS_TONE };
export default Badge;
