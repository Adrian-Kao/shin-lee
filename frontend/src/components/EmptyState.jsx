// Presentational empty-state placeholder. Callers pass localized strings.

export default function EmptyState({
  icon = '📄',
  title,
  description,
  hint,
  action,
  className = '',
}) {
  return (
    <div
      className={`rounded-lg border border-slate-200 bg-white p-8 text-center md:p-12 ${className}`}
    >
      <div className="mb-3 select-none text-4xl md:text-5xl" aria-hidden="true">
        {icon}
      </div>
      {title && <h2 className="mb-1 text-base font-semibold text-slate-700 md:text-lg">{title}</h2>}
      {description && <p className="mx-auto max-w-md text-sm text-slate-500">{description}</p>}
      {hint && <p className="mx-auto mt-2 max-w-md text-xs text-slate-400">{hint}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}
