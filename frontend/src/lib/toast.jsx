import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';

// Minimal toast system: no deps, no provider. Subscribers (one — ToastViewport)
// listen for items; toast.success/.error/.info push; auto-dismiss after `duration`.

const listeners = new Set();
let counter = 0;
let items = [];

function emit() {
  for (const fn of listeners) fn(items);
}

function push(item) {
  items = [...items, item];
  emit();
}

function drop(id) {
  items = items.filter((it) => it.id !== id);
  emit();
}

function show(kind, message, opts = {}) {
  const id = ++counter;
  const duration = opts.duration ?? 3000;
  push({ id, kind, message, createdAt: Date.now() });
  if (duration > 0) setTimeout(() => drop(id), duration);
  return id;
}

export const toast = {
  success: (msg, opts) => show('success', msg, opts),
  error: (msg, opts) => show('error', msg, opts),
  info: (msg, opts) => show('info', msg, opts),
  dismiss: (id) => drop(id),
};

const KIND_CLASSES = {
  success: 'bg-emerald-600 text-white border-emerald-700',
  error: 'bg-rose-600 text-white border-rose-700',
  info: 'bg-slate-800 text-white border-slate-900',
};

const KIND_ICON = { success: '✓', error: '✗', info: 'i' };

export function ToastViewport() {
  const [list, setList] = useState(items);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    const fn = (next) => setList(next);
    listeners.add(fn);
    setList([...items]);
    return () => listeners.delete(fn);
  }, []);

  if (!mounted || typeof document === 'undefined') return null;

  // a11y: errors interrupt (assertive), everything else is non-interrupting
  // (polite). Two separate live regions so screen readers route correctly.
  const assertive = list.filter((it) => it.kind === 'error');
  const polite = list.filter((it) => it.kind !== 'error');

  return createPortal(
    <div className="pointer-events-none fixed right-4 top-4 z-[1000] flex w-[calc(100%-2rem)] max-w-sm flex-col gap-2 sm:w-auto">
      <div aria-live="assertive" aria-atomic="false" className="flex flex-col gap-2">
        {assertive.map((it) => (
          <ToastItem key={it.id} item={it} onDismiss={() => drop(it.id)} />
        ))}
      </div>
      <div aria-live="polite" aria-atomic="false" className="flex flex-col gap-2">
        {polite.map((it) => (
          <ToastItem key={it.id} item={it} onDismiss={() => drop(it.id)} />
        ))}
      </div>
    </div>,
    document.body
  );
}

function ToastItem({ item, onDismiss }) {
  const { t } = useTranslation();
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const id = requestAnimationFrame(() => setShown(true));
    return () => cancelAnimationFrame(id);
  }, []);

  const klass = KIND_CLASSES[item.kind] || KIND_CLASSES.info;
  const icon = KIND_ICON[item.kind] || KIND_ICON.info;

  return (
    // No per-item role: the surrounding aria-live region (assertive/polite)
    // owns the announcement. A nested role=alert here would double-announce.
    <div
      className={`${klass} pointer-events-auto flex items-start gap-2 rounded-md border px-3 py-2 text-sm shadow-lg`}
      style={{
        opacity: shown ? 1 : 0,
        transform: shown ? 'translateX(0)' : 'translateX(0.5rem)',
        transition: 'opacity 200ms ease-out, transform 200ms ease-out',
      }}
    >
      <span aria-hidden="true" className="select-none font-bold leading-5">
        {icon}
      </span>
      <span className="flex-1 break-words leading-5">{item.message}</span>
      <button
        type="button"
        onClick={onDismiss}
        aria-label={t('errors.dismiss')}
        className="px-1 leading-5 opacity-80 hover:opacity-100"
      >
        ×
      </button>
    </div>
  );
}
