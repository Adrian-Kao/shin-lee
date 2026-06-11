import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { UploadCloud, FileText, Loader2, Download } from 'lucide-react';
import { api } from '../api/client.js';
import { Button } from './ui/button.jsx';
import { Badge } from './ui/badge.jsx';
import { toast } from '../lib/toast.jsx';

// Backend joins per-page extracted text with this exact separator (see
// backend OA upload handler). We split on it to render per-page blocks.
const PAGE_BREAK = '\n\n--- page break ---\n\n';

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
        const msg = t('upload.invalid_type');
        toast.error(msg); // toast per spec; inline chip below for in-pane context
        setErrorMsg(msg);
        setStatus('error');
        if (onError) onError(new Error(msg));
        return;
      }
      if (f.size > MAX_BYTES) {
        const msg = t('upload.too_large');
        toast.error(msg);
        setErrorMsg(msg);
        setStatus('error');
        if (onError) onError(new Error(msg));
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
        // Localize the transport-level failure strings from client.js; keep
        // server-provided `detail` messages verbatim (already human-readable).
        const msg =
          err?.message === 'Network error during upload'
            ? t('errors.network')
            : err?.message || t('errors.request_failed');
        setErrorMsg(msg);
        setStatus('error');
        if (onError) onError(err);
      });
  }, [file, caseId, token, onError, t]);

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
        <div className="rounded border border-rose-200 bg-rose-50 p-2 text-xs text-rose-700 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300">
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
    <div
      className="rounded border border-slate-200 bg-white p-2 dark:border-slate-700 dark:bg-slate-900"
      data-testid="element-table"
    >
      <div className="mb-1 text-xs font-semibold text-slate-600 dark:text-slate-300">
        {t('upload.element_table_title')}
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-slate-400 dark:text-slate-500">
            <th className="w-16 font-normal">{t('upload.element_table_numeral')}</th>
            <th className="font-normal">{t('upload.element_table_desc')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([numeral, desc]) => (
            <tr key={numeral} className="border-t border-slate-100 dark:border-slate-800">
              <td className="py-1 pr-2 font-mono text-slate-700 dark:text-slate-200">{numeral}</td>
              <td className="py-1 text-slate-700 dark:text-slate-200">{String(desc)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DropZone({ dragOver, onDragOver, onDragLeave, onDrop, onBrowseClick, t }) {
  // Two border-color states: idle (slate), dragging-over (navy + bg).
  const base =
    'h-48 border-2 border-dashed rounded-lg flex flex-col items-center justify-center transition-colors cursor-pointer select-none';
  const tone = dragOver
    ? 'border-navy-400 bg-navy-50 text-navy-700 dark:bg-navy-950/40 dark:text-navy-300'
    : 'border-slate-300 text-slate-500 hover:border-slate-400 dark:border-slate-600 dark:text-slate-400';
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
        className="mx-auto mb-2 h-10 w-10 text-slate-400 dark:text-slate-500"
        strokeWidth={1.5}
        aria-hidden="true"
      />
      <div className="text-sm">
        {t('upload.drop_zone')}{' '}
        <span className="text-navy-700 underline dark:text-navy-200">{t('upload.browse')}</span>
      </div>
      <div className="mt-2 text-xs text-slate-400 dark:text-slate-500">PDF / DOCX · ≤ 30MB</div>
    </div>
  );
}

function PreviewPane({ file, blobUrl, t }) {
  if (!file) return null;
  if (blobUrl) {
    // Native browser PDF rendering — NO pdf.js dependency. <object> is the
    // primary renderer; an <iframe> is the first fallback (some browsers honour
    // one but not the other for blob: URLs), and a download link is the final
    // fallback for environments that render neither (e.g. some mobile webviews).
    return (
      <object
        type="application/pdf"
        data={blobUrl}
        className="h-96 w-full rounded border dark:border-slate-700"
        aria-label={file.name}
        data-testid="pdf-preview"
      >
        <iframe
          src={blobUrl}
          title={file.name}
          className="h-96 w-full rounded border dark:border-slate-700"
        />
        <div className="flex h-96 w-full flex-col items-center justify-center rounded border bg-slate-50 px-6 text-center dark:border-slate-700 dark:bg-slate-800/50">
          <FileText
            className="mb-2 h-10 w-10 text-slate-400 dark:text-slate-500"
            strokeWidth={1.5}
            aria-hidden="true"
          />
          <div className="text-sm text-slate-600 dark:text-slate-300">
            {t('upload.pdf_no_inline')}
          </div>
          <a
            href={blobUrl}
            download={file.name}
            className="mt-2 inline-flex items-center gap-1 rounded text-sm text-navy-700 underline hover:text-navy-800 dark:text-navy-200"
          >
            <Download className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
            {file.name}
          </a>
        </div>
      </object>
    );
  }
  return (
    <div className="flex h-96 w-full flex-col items-center justify-center rounded border bg-slate-50 px-6 text-center dark:border-slate-700 dark:bg-slate-800/50">
      <FileText
        className="mb-2 h-10 w-10 text-slate-400 dark:text-slate-500"
        strokeWidth={1.5}
        aria-hidden="true"
      />
      <div className="text-sm text-slate-600 dark:text-slate-300">
        {t('upload.docx_no_preview')}
      </div>
      <div className="mt-2 break-all font-mono text-xs text-slate-400 dark:text-slate-500">
        {file.name}
      </div>
    </div>
  );
}

/**
 * Extracted-text preview — shown after a successful upload. Splits the
 * page-joined `extracted_text` on the backend separator into per-page
 * scrollable blocks, and surfaces page/char counts, an OCR badge, and any
 * warnings. Defensive: missing/empty text → renders only the meta header.
 */
function ExtractedTextPreview({ result, t }) {
  const pages = useMemo(() => {
    const raw = typeof result?.extracted_text === 'string' ? result.extracted_text : '';
    if (!raw) return [];
    return raw.split(PAGE_BREAK);
  }, [result]);

  const pageCount = result?.page_count ?? pages.length;
  const charCount = result?.char_count ?? 0;
  const ocrPages = result?.ocr_pages_used ?? 0;
  const warnings = Array.isArray(result?.warnings) ? result.warnings : [];

  return (
    <div
      className="rounded border border-slate-200 bg-white p-2 dark:border-slate-700 dark:bg-slate-900"
      data-testid="extracted-text-preview"
    >
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <Badge tone="brand" variant="soft">
          {t('upload.preview_pages', { count: pageCount })}
        </Badge>
        <Badge tone="neutral" variant="soft">
          {t('upload.preview_chars', { count: (charCount || 0).toLocaleString() })}
        </Badge>
        {ocrPages > 0 && (
          <Badge tone="warning" variant="soft" data-testid="ocr-badge">
            {t('upload.preview_ocr', { count: ocrPages })}
          </Badge>
        )}
      </div>

      {warnings.length > 0 && (
        <div className="mb-2 space-y-1">
          {warnings.map((w, i) => (
            <div
              key={i}
              className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300"
            >
              {w}
            </div>
          ))}
        </div>
      )}

      {pages.length > 0 && (
        <div className="space-y-2" data-testid="extracted-text-pages">
          {pages.map((pageText, i) => (
            <div key={i} className="rounded border border-slate-100 dark:border-slate-800">
              <div className="border-b border-slate-100 bg-slate-50 px-2 py-1 text-3xs uppercase tracking-wider text-slate-400 dark:border-slate-800 dark:bg-slate-800/50 dark:text-slate-500">
                {t('upload.preview_page_n', { n: i + 1 })}
              </div>
              <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words px-2 py-1.5 font-mono text-xs text-slate-700 dark:text-slate-200">
                {pageText}
              </pre>
            </div>
          ))}
        </div>
      )}
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
    <div className="space-y-3 rounded border bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
      <div>
        <div className="text-xs uppercase tracking-wider text-slate-500 dark:text-slate-400">
          {t('upload.file_selected')}
        </div>
        <div className="mt-0.5 break-all font-mono text-sm">{file?.name}</div>
        <div className="text-xs text-slate-500 dark:text-slate-400">
          {file ? fmtSize(file.size) : ''}
        </div>
      </div>

      {status === 'file-selected' && (
        <div className="flex gap-2">
          <Button variant="primary" onClick={onUpload} className="flex-1">
            {t('upload.upload_button')}
          </Button>
          <Button variant="secondary" onClick={onChange}>
            {t('upload.change_file')}
          </Button>
        </div>
      )}

      {status === 'uploading' && (
        <div>
          <div className="mb-1 text-xs text-slate-500 dark:text-slate-400">
            {t('upload.uploading')} {Math.round(progress * 100)}%
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
            <div
              className="h-full bg-navy-500 transition-[width] duration-150"
              style={{ width: `${Math.round(progress * 100)}%` }}
            />
          </div>
          <Button
            variant="secondary"
            size="xs"
            onClick={onCancel}
            className="mt-3 px-3 py-1.5 text-sm"
          >
            {t('upload.cancel_button')}
          </Button>
        </div>
      )}

      {status === 'server-extracting' && (
        <div className="flex items-start gap-2">
          <Loader2
            className="h-5 w-5 shrink-0 animate-spin text-navy-600 dark:text-navy-300"
            strokeWidth={1.75}
            aria-hidden="true"
          />
          <div className="text-sm text-slate-700 dark:text-slate-200">{t('upload.extracting')}</div>
        </div>
      )}

      {status === 'success' && extractResult && (
        <div className="space-y-2">
          <div className="rounded border border-emerald-200 bg-emerald-50 p-2 text-sm text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300">
            <div>
              {t('upload.success', {
                pages: extractResult.page_count ?? 0,
                chars: (extractResult.char_count ?? 0).toLocaleString(),
              })}
            </div>
            {extractResult.ocr_pages_used > 0 && (
              <div className="mt-1 text-xs text-amber-700 dark:text-amber-300">
                {t('upload.ocr_used', {
                  count: extractResult.ocr_pages_used,
                  cost: Number(extractResult.cost_meta?.estimated_cost_usd ?? 0).toFixed(2),
                })}
              </div>
            )}
          </div>
          <ExtractedTextPreview result={extractResult} t={t} />
          <ElementTable table={extractResult.element_table} t={t} />
          <div className="flex gap-2">
            <Button variant="primary" onClick={onAccept} className="flex-1">
              {t('upload.use_this_text')}
            </Button>
            <Button variant="secondary" onClick={onChange}>
              {t('upload.change_file')}
            </Button>
          </div>
        </div>
      )}

      {status === 'error' && (
        <div className="space-y-2">
          {errorMsg && (
            <div className="rounded border border-rose-200 bg-rose-50 p-2 text-xs text-rose-700 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300">
              {errorMsg}
            </div>
          )}
          <div className="flex gap-2">
            <Button variant="primary" onClick={onRetry} disabled={!file} className="flex-1">
              {t('upload.retry_button')}
            </Button>
            <Button variant="secondary" onClick={onChange}>
              {t('upload.change_file')}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
