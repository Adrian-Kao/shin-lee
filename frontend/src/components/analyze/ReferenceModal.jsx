import React, { useEffect, useRef } from 'react';

/**
 * Minimal modal for displaying a single RAG retrieval hit's full text.
 *
 * Uses the native <dialog> element to get accessibility (Esc-to-close, focus
 * trap, backdrop click) without pulling in radix-ui. Falls back to a plain
 * fixed overlay if showModal() isn't available (very old browsers).
 */
export default function ReferenceModal({ hit, onClose }) {
  const dialogRef = useRef(null);

  useEffect(() => {
    const d = dialogRef.current;
    if (!d) return undefined;
    if (typeof d.showModal === 'function') {
      try {
        d.showModal();
      } catch {
        /* already open */
      }
    }
    const onCancel = (e) => {
      e.preventDefault();
      onClose();
    };
    d.addEventListener('cancel', onCancel);
    return () => {
      d.removeEventListener('cancel', onCancel);
      if (typeof d.close === 'function' && d.open) d.close();
    };
  }, [onClose]);

  // Close on backdrop click (clicks landing on the <dialog> itself, not its content).
  const onBackdropClick = (e) => {
    if (e.target === dialogRef.current) onClose();
  };

  return (
    <dialog
      ref={dialogRef}
      onClick={onBackdropClick}
      className="w-full max-w-2xl rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-0 shadow-2xl backdrop:bg-slate-900/40"
    >
      <div className="flex items-baseline justify-between gap-3 border-b dark:border-slate-700 px-5 py-3">
        <div className="min-w-0">
          <div className="truncate font-mono text-sm font-semibold text-slate-800 dark:text-slate-200">
            {hit.patent_no}
          </div>
          <div className="text-xs text-slate-500 dark:text-slate-400">
            {hit.section} · score {hit.score.toFixed(3)}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded bg-slate-100 dark:bg-slate-800 px-2 py-1 text-xs text-slate-600 dark:text-slate-300 hover:bg-slate-200"
          aria-label="Close"
        >
          ✕
        </button>
      </div>
      <div className="max-h-[60vh] overflow-y-auto px-5 py-4">
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700 dark:text-slate-200">{hit.text}</p>
      </div>
    </dialog>
  );
}
