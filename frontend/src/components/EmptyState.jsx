import { FileText } from 'lucide-react';

/**
 * Presentational empty-state placeholder.
 *
 * Day 9C — `icon` now accepts either a React node (e.g. a lucide-react
 * <ScrollText /> element) or — for backwards compatibility — a string
 * which is rendered as text. New call sites should pass nodes; the
 * default is a lucide FileText.
 */
export default function EmptyState({ icon, title, description, hint, action, className = '' }) {
  const iconNode =
    icon === undefined ? (
      <FileText className="mx-auto h-10 w-10 text-slate-400 dark:text-slate-500" strokeWidth={1.5} aria-hidden="true" />
    ) : typeof icon === 'string' ? (
      <span className="select-none text-4xl md:text-5xl" aria-hidden="true">
        {icon}
      </span>
    ) : (
      icon
    );
  return (
    <div
      className={`rounded-lg border border-slate-200 bg-white p-8 text-center md:p-12 dark:border-slate-700 dark:bg-slate-900 ${className}`}
    >
      <div className="mb-3">{iconNode}</div>
      {title && <h2 className="mb-1 text-base font-semibold text-slate-700 md:text-lg dark:text-slate-200">{title}</h2>}
      {description && <p className="mx-auto max-w-md text-sm text-slate-500 dark:text-slate-400">{description}</p>}
      {hint && <p className="mx-auto mt-2 max-w-md text-xs text-slate-400 dark:text-slate-500">{hint}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}
