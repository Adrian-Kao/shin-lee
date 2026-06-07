import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { UploadCloud } from 'lucide-react';
import { api } from '../api/client.js';

// Day 2: drag-drop PDF / DOCX upload for the Analyze view.
// State machine:
//   idle → file-selected → uploading → server-extracting → success
//                                                       ↘ error → (retry) → uploading
//   At any point user can click "換一個" to reset to idle.
//
// Wires `api.uploadOA(...)` which returns { promise, abort } so we support real cancel.

const MAX_BYTES = 30 * 1024 * 1024; // 30MB hard ceiling per spec
const ALLOWED_EXT = ['.pdf', '.docx'];
const ALLOWED_MIME = [
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
];

function isAllowed(file) {
  const lower = (file.name || '').toLowerCase();
  const extOk = ALLOWED_EXT.some((ext) => lower.endsWith(ext));
  const mimeOk = !file.type || ALLOWED_MIME.includes(file.type); // some browsers omit MIME for .docx
  return extOk && mimeOk;
}

function isPdf(file) {
  return (file?.name || '').toLowerCase().endsWith('.pdf');
}

function fmtSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export default function OAUpload({ caseId, token, onExtractSuccess, onError }) {
  const { t } = useTranslation();
  const [status, setStatus] = useState('idle'); // idle | file-selected | uploading | server-extracting | success | error
  const [file, setFile] = useState(null);
  const [blobUrl, setBlobUrl] = useState(null);
  const [progress, setProgress] = useState(0); // 0..1 (network upload phase)
  const [errorMsg, setErrorMsg] = useState(null);
  const [extractResult, setExtractResult] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef(null);
  const abortRef = useRef(null);

  // Revoke blob URLs to avoid leaks (file replaced OR component unmounted).
  useEffect(() => {
    return () => {
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [blobUrl]);

  const handleFileChosen = useCallback(
    (f) => {
      if (!f) return;
      if (!isAllowed(f)) {
        setErrorMsg(t('upload.invalid_type'));
        setStatus('error');
        if (onError) onError(new Error(t('upload.invalid_type')));
        return;
      }
      if (f.size > MAX_BYTES) {
        setErrorMsg(t('upload.too_large'));
        setStatus('error');
        if (onError) onError(new Error(t('upload.too_large')));
        return;
      }
      // Replace any existing blobUrl
      if (blobUrl) URL.revokeObjectURL(blobUrl);
      setBlobUrl(isPdf(f) ? URL.createObjectURL(f) : null);
      setFile(f);
      setErrorMsg(null);
      setProgress(0);
      setExtractResult(null);
      setStatus('file-selected');
    },
    [blobUrl, onError, t]
  );

  const reset = useCallback(() => {
    if (abortRef.current) {
      try {
        abortRef.current();
      } catch {
        /* abort can throw if xhr already done */
      }
      abortRef.current = null;
    }
    if (blobUrl) URL.revokeObjectURL(blobUrl);
    setBlobUrl(null);
    setFile(null);
    setProgress(0);
    setErrorMsg(null);
    setExtractResult(null);
    setStatus('idle');
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, [blobUrl]);

  const startUpload = useCallback(() => {
    if (!file || !caseId || !token) return;
    setStatus('uploading');
    setProgress(0);
    setErrorMsg(null);

    const { promise, abort } = api.uploadOA(caseId, token, file, (p) => {
      setProgress(p);
      // When network finishes (p === 1), server still has work to do (parse / OCR).
      if (p >= 1) setStatus((s) => (s === 'uploading' ? 'server-extracting' : s));
    });
    abortRef.current = abort;

    promise
      .then((data) => {
        abortRef.current = null;
        setExtractResult(data);
        setStatus('success');
      })
      .catch((err) => {
        abortRef.current = null;
        // Don't surface as error if the user explicitly cancelled.
        if (err && err.message === 'Upload cancelled') {
          setStatus('file-selected');
          setProgress(0);
          return;
        }
        setErrorMsg(err?.message || 'Upload failed');
        setStatus('error');
        if (onError) onError(err);
      });
  }, [file, caseId, token, onError]);

  const cancelUpload = useCallback(() => {
    if (abortRef.current) {
      try {
        abortRef.current();
      } catch {
        /* already finished */
      }
    }
  }, []);

  const acceptResult = useCallback(() => {
    if (!extractResult || !file) return;
    onExtractSuccess({
      ...extractResult,
      fileName: file.name,
      fileSize: file.size,
    });
  }, [extractResult, file, onExtractSuccess]);

  // ---- DnD handlers (zone only renders in idle / error states) ----
  const onDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(true);
  };
  const onDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
  };
  const onDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
    const f = e.dataTransfer?.files?.[0];
    if (f) handleFileChosen(f);
  };

  // ---- Render ----
  const showDropZone = status === 'idle' || status === 'error';

  return (
    <div className="space-y-3">
      {showDropZone ? (
        <DropZone
          dragOver={dragOver}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          onBrowseClick={() => fileInputRef.current?.click()}
          t={t}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <PreviewPane file={file} blobUrl={blobUrl} t={t} />
          <StatusPane
            status={status}
            file={file}
            progress={progress}
            errorMsg={errorMsg}
            extractResult={extractResult}
            onUpload={startUpload}
            onCancel={cancelUpload}
            onChange={reset}
            onRetry={startUpload}
            onAccept={acceptResult}
            t={t}
          />
        </div>
      )}

      {status === 'error' && errorMsg && (
        <div className="rounded border border-rose-200 bg-rose-50 p-2 text-xs text-rose-700">
          {errorMsg}
        </div>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        className="hidden"
        onChange={(e) => handleFileChosen(e.target.files?.[0])}
      />
    </div>
  );
}

/**
 * Q8 figure-element table — reference numeral → description, surfaced after a
 * successful upload. Defensive: absent / empty / non-object → render nothing.
 * Numerals are sorted numerically so "10, 20, 200" reads in figure order.
 */
function ElementTable({ table, t }) {
  if (!table || typeof table !== 'object') return null;
  const rows = Object.entries(table).filter(([, desc]) => desc != null && desc !== '');
  if (rows.length === 0) return null;
  rows.sort((a, b) => {
    const na = Number(a[0]);
    const nb = Number(b[0]);
    if (Number.isNaN(na) || Number.isNaN(nb)) return String(a[0]).localeCompare(String(b[0]));
    return na - nb;
  });
  return (
    <div className="rounded border border-slate-200 bg-white p-2" data-testid="element-table">
      <div className="mb-1 text-xs font-semibold text-slate-600">
        {t('upload.element_table_title')}
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-slate-400">
            <th className="w-16 font-normal">{t('upload.element_table_numeral')}</th>
            <th className="font-normal">{t('upload.element_table_desc')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([numeral, desc]) => (
            <tr key={numeral} className="border-t border-slate-100">
              <td className="py-1 pr-2 font-mono text-slate-700">{numeral}</td>
              <td className="py-1 text-slate-700">{String(desc)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DropZone({ dragOver, onDragOver, onDragLeave, onDrop, onBrowseClick, t }) {
  // Three border-color states: idle (slate), dragging-over (indigo + bg).
  const base =
    'h-48 border-2 border-dashed rounded-lg flex flex-col items-center justify-center transition-colors cursor-pointer select-none';
  const tone = dragOver
    ? 'border-indigo-400 bg-indigo-50 text-indigo-700'
    : 'border-slate-300 text-slate-500 hover:border-slate-400';
  return (
    <div
      className={`${base} ${tone}`}
      onDragOver={onDragOver}
      onDragEnter={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      onClick={onBrowseClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onBrowseClick();
      }}
    >
      <UploadCloud
        className="mx-auto mb-2 h-10 w-10 text-slate-400"
        strokeWidth={1.5}
        aria-hidden="true"
      />
      <div className="text-sm">
        {t('upload.drop_zone')}{' '}
        <span className="text-navy-700 underline">{t('upload.browse')}</span>
      </div>
      <div className="mt-2 text-xs text-slate-400">PDF / DOCX · ≤ 30MB</div>
    </div>
  );
}

function PreviewPane({ file, blobUrl, t }) {
  if (!file) return null;
  if (blobUrl) {
    return (
      <embed
        type="application/pdf"
        src={blobUrl}
        className="h-96 w-full rounded border"
        title={file.name}
      />
    );
  }
  return (
    <div className="flex h-96 w-full flex-col items-center justify-center rounded border bg-slate-50 px-6 text-center">
      <div className="mb-2 text-4xl">📄</div>
      <div className="text-sm text-slate-600">{t('upload.docx_no_preview')}</div>
      <div className="mt-2 break-all font-mono text-xs text-slate-400">{file.name}</div>
    </div>
  );
}

function StatusPane({
  status,
  file,
  progress,
  errorMsg,
  extractResult,
  onUpload,
  onCancel,
  onChange,
  onRetry,
  onAccept,
  t,
}) {
  return (
    <div className="space-y-3 rounded border bg-white p-4">
      <div>
        <div className="text-xs uppercase tracking-wider text-slate-500">
          {t('upload.file_selected')}
        </div>
        <div className="mt-0.5 break-all font-mono text-sm">{file?.name}</div>
        <div className="text-xs text-slate-500">{file ? fmtSize(file.size) : ''}</div>
      </div>

      {status === 'file-selected' && (
        <div className="flex gap-2">
          <button
            onClick={onUpload}
            className="flex-1 rounded bg-indigo-600 px-3 py-2 text-sm text-white hover:bg-indigo-700"
          >
            {t('upload.upload_button')}
          </button>
          <button
            onClick={onChange}
            className="rounded bg-slate-200 px-3 py-2 text-sm hover:bg-slate-300"
          >
            {t('upload.change_file')}
          </button>
        </div>
      )}

      {status === 'uploading' && (
        <div>
          <div className="mb-1 text-xs text-slate-500">
            {t('upload.uploading')} {Math.round(progress * 100)}%
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-200">
            <div
              className="h-full bg-indigo-500 transition-[width] duration-150"
              style={{ width: `${Math.round(progress * 100)}%` }}
            />
          </div>
          <button
            onClick={onCancel}
            className="mt-3 rounded bg-slate-200 px-3 py-1.5 text-sm hover:bg-slate-300"
          >
            {t('upload.cancel_button')}
          </button>
        </div>
      )}

      {status === 'server-extracting' && (
        <div className="flex items-start gap-2">
          <span className="animate-pulse text-xl">⏳</span>
          <div className="text-sm text-slate-700">{t('upload.extracting')}</div>
        </div>
      )}

      {status === 'success' && extractResult && (
        <div className="space-y-2">
          <div className="rounded border border-emerald-200 bg-emerald-50 p-2 text-sm text-emerald-700">
            <div>
              {t('upload.success', {
                pages: extractResult.page_count ?? 0,
                chars: (extractResult.char_count ?? 0).toLocaleString(),
              })}
            </div>
            {extractResult.ocr_pages_used > 0 && (
              <div className="mt-1 text-xs text-amber-700">
                {t('upload.ocr_used', {
                  count: extractResult.ocr_pages_used,
                  cost: Number(extractResult.cost_meta?.estimated_cost_usd ?? 0).toFixed(2),
                })}
              </div>
            )}
          </div>
          <ElementTable table={extractResult.element_table} t={t} />
          <div className="flex gap-2">
            <button
              onClick={onAccept}
              className="flex-1 rounded bg-indigo-600 px-3 py-2 text-sm text-white hover:bg-indigo-700"
            >
              {t('upload.use_this_text')}
            </button>
            <button
              onClick={onChange}
              className="rounded bg-slate-200 px-3 py-2 text-sm hover:bg-slate-300"
            >
              {t('upload.change_file')}
            </button>
          </div>
        </div>
      )}

      {status === 'error' && (
        <div className="space-y-2">
          {errorMsg && (
            <div className="rounded border border-rose-200 bg-rose-50 p-2 text-xs text-rose-700">
              {errorMsg}
            </div>
          )}
          <div className="flex gap-2">
            <button
              onClick={onRetry}
              className="flex-1 rounded bg-indigo-600 px-3 py-2 text-sm text-white hover:bg-indigo-700"
              disabled={!file}
            >
              {t('upload.retry_button')}
            </button>
            <button
              onClick={onChange}
              className="rounded bg-slate-200 px-3 py-2 text-sm hover:bg-slate-300"
            >
              {t('upload.change_file')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
