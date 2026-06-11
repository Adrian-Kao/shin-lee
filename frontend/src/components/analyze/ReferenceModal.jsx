import React, { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import { Button } from '../ui/button.jsx';

/**
 * Minimal modal for displaying a single RAG retrieval hit's full text.
 *
 * Uses the native <dialog> element to get accessibility (Esc-to-close, focus
 * trap, backdrop click) without pulling in radix-ui. Falls back to a plain
 * fixed overlay if showModal() isn't available (very old browsers).
 */
export default function ReferenceModal({ hit, onClose }) {
  const { t } = useTranslation();
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
      className="w-full max-w-2xl rounded-lg border border-slate-200 bg-white p-0 shadow-2xl backdrop:bg-slate-900/40 dark:border-slate-700 dark:bg-slate-900"
    >
      <div className="flex items-baseline justify-between gap-3 border-b px-5 py-3 dark:border-slate-700">
        <div className="min-w-0">
          <div className="truncate font-mono text-sm font-semibold text-slate-800 dark:text-slate-200">
            {hit.patent_no}
          </div>
          <div className="text-xs text-slate-500 dark:text-slate-400">
            {hit.section} · {t('analyze.refs.score')} {hit.score.toFixed(3)}
          </div>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onClose}
          className="h-8 w-8 shrink-0"
          aria-label={t('signoff.close')}
        >
          <X className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
        </Button>
      </div>
      <div className="max-h-[60vh] overflow-y-auto px-5 py-4">
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700 dark:text-slate-200">
          {hit.text}
        </p>
      </div>
    </dialog>
  );
}
