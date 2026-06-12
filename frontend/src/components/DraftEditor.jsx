import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Pencil, X, Undo2, CheckCheck } from 'lucide-react';
import { api, ApiError } from '../api/client.js';
import { toast } from '../lib/toast.jsx';
import { Button } from './ui/button.jsx';

/**
 * Q16: 逐句律師標記 + 簽核匯出（責任界線）。
 *
 * 每行 (segment) 都帶 provenance：
 *   - source: 'ai_generated'  — AI 生成、律師原樣接受
 *             'attorney_edited' — AI 句被律師改寫（共同作者；改寫即回饋訊號）
 *             'attorney_added'  — 律師自行新增（全律師作者）
 *   - status: 'pending' | 'accepted' | 'excluded' — 三態決策。excluded 句仍
 *     隨 export payload 送出（accepted=false），讓後端 provenance 完整；但
 *     不會進最終文件。
 *
 * 匯出硬性閘門（Q16 決策）：每一句都必須「決定過」（接受或排除）+ 勾選
 * 「我已逐項確認」，Export 才 enable；後端在 attorney_signoff !== true 時
 * 回 409，前端把「需簽核」訊息攤開，不靜默吞掉。律師簽核時清楚知道自己
 * endorse 了哪些 AI 句、改寫/新增/排除了哪些。
 *
 * 鍵盤操作：行聚焦後 A 接受、E 改寫、X 排除、U 撤銷；編輯中 Ctrl+Enter
 * 儲存、Esc 取消。
 */
export default function DraftEditor({
  initialDraft,
  citationLookup,
  caseId,
  rejectionId,
  token,
  canExport = false,
  role,
  onCitationClick,
}) {
  const { t } = useTranslation();
  // Multi-person provenance: tag a human edit/add by the CURRENT user's role so
  // the responsibility chain (paralegal drafts → attorney signs) is visible per
  // sentence, not collapsed to "attorney". The attorney still owns the export
  // sign-off gate (canExport).
  const isParalegal = role === 'paralegal';
  const editedSource = isParalegal ? 'paralegal_edited' : 'attorney_edited';
  const addedSource = isParalegal ? 'paralegal_added' : 'attorney_added';
  const [lines, setLines] = useState(() => splitIntoLines(initialDraft));
  const [editingIdx, setEditingIdx] = useState(null);
  const [editValue, setEditValue] = useState('');
  const [reviewed, setReviewed] = useState(false);
  const [addingValue, setAddingValue] = useState('');
  const [exporting, setExporting] = useState(false);
  const [exportResult, setExportResult] = useState(null);
  const [showOriginalIdx, setShowOriginalIdx] = useState(null);

  useEffect(() => {
    setLines(splitIntoLines(initialDraft));
    setReviewed(false);
    setExportResult(null);
    setEditingIdx(null);
    setAddingValue('');
    setShowOriginalIdx(null);
  }, [initialDraft]);

  const acceptedCount = lines.filter((l) => l.status === 'accepted').length;
  const excludedCount = lines.filter((l) => l.status === 'excluded').length;
  const decidedCount = acceptedCount + excludedCount;
  const pendingCount = lines.length - decidedCount;

  function setStatus(i, status) {
    setLines((ls) =>
      ls.map((l, idx) => (idx === i ? { ...l, status, ts: new Date().toISOString() } : l))
    );
  }
  function acceptAllPending() {
    const ts = new Date().toISOString();
    setLines((ls) => (ls.map((l) => (l.status === 'pending' ? { ...l, status: 'accepted', ts } : l))));
  }
  function startEdit(i) {
    setEditingIdx(i);
    setEditValue(lines[i].text);
  }
  function commitEdit() {
    setLines((ls) =>
      ls.map((l, idx) =>
        idx === editingIdx
          ? {
              ...l,
              // Re-editing an *_added line keeps its "added" provenance; editing
              // any other line marks it edited BY THE CURRENT ROLE.
              source: l.source.endsWith('_added') ? l.source : editedSource,
              edited_from: l.edited_from ?? (l.source === 'ai_generated' ? l.text : undefined),
              text: editValue,
              status: 'accepted',
              ts: new Date().toISOString(),
            }
          : l
      )
    );
    setEditingIdx(null);
  }
  function addLine() {
    const text = addingValue.trim();
    if (!text) return;
    setLines((ls) => [
      ...ls,
      {
        segment_id: `seg-add-${ls.length}-${Date.now()}`,
        text,
        source: addedSource,
        status: 'accepted',
        ts: new Date().toISOString(),
      },
    ]);
    setAddingValue('');
  }

  // Keyboard shortcuts on a focused draft line. Skipped while a textarea is
  // open (edit mode handles its own keys).
  function lineKeyDown(e, i) {
    if (editingIdx !== null) return;
    const k = e.key.toLowerCase();
    const l = lines[i];
    if (k === 'a' && l.status !== 'accepted') {
      e.preventDefault();
      setStatus(i, 'accepted');
    } else if (k === 'x' && l.status !== 'excluded') {
      e.preventDefault();
      setStatus(i, 'excluded');
    } else if (k === 'e') {
      e.preventDefault();
      startEdit(i);
    } else if (k === 'u' && l.status !== 'pending') {
      e.preventDefault();
      setStatus(i, 'pending');
    }
  }

  async function doExport() {
    // Belt-and-braces: the button is disabled until `reviewed` + all lines
    // decided, but guard here too so a stale click never sends a half-reviewed
    // draft silently.
    if (!reviewed || !canExport || !token || !caseId || pendingCount > 0) return;
    const segments = lines.map((l) => ({
      segment_id: l.segment_id,
      text: l.text,
      source: l.source,
      accepted: l.status === 'accepted',
    }));
    setExporting(true);
    try {
      const res = await api.exportDraft(token, {
        case_id: caseId,
        rejection_id: rejectionId,
        segments,
        attorney_signoff: true,
      });
      setExportResult(res);
      toast.success(t('signoff.export_success'));
    } catch (e) {
      // 409 = sign-off gate (e.g. checkbox state got out of sync). Surface it,
      // never swallow it.
      if (e instanceof ApiError && e.status === 409) {
        toast.error(t('signoff.signoff_required'));
      } else {
        toast.error(`${t('signoff.export_failed')}: ${e.message}`);
      }
    } finally {
      setExporting(false);
    }
  }

  function downloadTxt() {
    if (!exportResult?.document) return;
    const blob = new Blob([exportResult.document], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${caseId || 'response'}${rejectionId ? '-' + rejectionId : ''}.txt`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  const progressPct = lines.length ? Math.round((decidedCount / lines.length) * 100) : 0;

  return (
    <div className="space-y-2">
      {/* Progress + legend strip. aria-live so screen readers hear progress. */}
      <div className="mb-2 space-y-1.5">
        <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
          <span className="ai-line px-1">{t('signoff.source_ai')}</span>
          <span className="attorney-line px-1">{t('signoff.source_edited')}</span>
          <span className="ml-auto tabular-nums" aria-live="polite">
            {t('signoff.decided_count', { decided: decidedCount, total: lines.length })}
            {acceptedCount > 0 && ` · ${t('signoff.accepted_count', { count: acceptedCount })}`}
            {excludedCount > 0 && ` · ${t('signoff.excluded_count', { count: excludedCount })}`}
          </span>
        </div>
        <div
          className="h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700"
          role="progressbar"
          aria-valuenow={decidedCount}
          aria-valuemin={0}
          aria-valuemax={lines.length}
        >
          <div
            className="h-full rounded-full bg-navy-500 transition-all dark:bg-navy-400"
            style={{ width: `${progressPct}%` }}
          />
        </div>
        <div className="flex items-center justify-between text-2xs text-slate-400 dark:text-slate-500">
          <span>{t('signoff.kbd_hint')}</span>
          {pendingCount > 1 && (
            <Button
              size="xs"
              variant="secondary"
              onClick={acceptAllPending}
              data-testid="signoff-accept-all"
              className="gap-1"
            >
              <CheckCheck className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
              {t('signoff.accept_all_rest', { count: pendingCount })}
            </Button>
          )}
        </div>
      </div>

      {lines.map((l, i) => (
        <div
          key={l.segment_id}
          data-testid="draft-line"
          tabIndex={0}
          onKeyDown={(e) => lineKeyDown(e, i)}
          aria-label={`${i + 1}. ${l.text}`}
          className={`group -mx-1 flex items-start gap-2 rounded px-1 py-0.5 transition-colors hover:bg-slate-50 focus-visible:bg-slate-50 dark:hover:bg-slate-800/60 dark:focus-visible:bg-slate-800/60 ${
            l.status === 'pending' ? 'border-l-2 border-amber-300 dark:border-amber-600' : 'border-l-2 border-transparent'
          }`}
        >
          <div className="w-6 pt-1.5 text-xs tabular-nums text-slate-400 dark:text-slate-500">
            {i + 1}.
          </div>
          {editingIdx === i ? (
            <div className="flex-1">
              <textarea
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) commitEdit();
                  if (e.key === 'Escape') setEditingIdx(null);
                }}
                autoFocus
                className="w-full rounded border border-emerald-300 p-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-300 dark:border-emerald-800"
                rows={3}
              />
              <div className="mt-1 flex items-center gap-2">
                <Button
                  size="xs"
                  onClick={commitEdit}
                  className="bg-emerald-600 text-white hover:bg-emerald-700 focus-visible:ring-emerald-500"
                >
                  {t('signoff.save')}
                </Button>
                <Button size="xs" variant="secondary" onClick={() => setEditingIdx(null)}>
                  {t('signoff.cancel')}
                </Button>
                <span className="text-2xs text-slate-400 dark:text-slate-500">
                  {t('signoff.edit_kbd_hint')}
                </span>
              </div>
            </div>
          ) : (
            <>
              <div className="min-w-0 flex-1">
                <div
                  className={`${l.source === 'ai_generated' ? 'ai-line' : 'attorney-line'} px-1 leading-7 ${
                    l.status === 'excluded'
                      ? 'text-slate-400 line-through decoration-rose-400/60 dark:text-slate-500'
                      : ''
                  }`}
                >
                  <CitationHighlighter
                    text={l.text}
                    citationLookup={citationLookup}
                    onCitationClick={onCitationClick}
                  />
                  {l.status === 'accepted' && (
                    <span className="ml-2 inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
                      <Check className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
                      {sourceLabel(l.source, t)}
                    </span>
                  )}
                  {l.status === 'excluded' && (
                    <span className="ml-2 inline-flex items-center gap-1 text-xs text-rose-500 dark:text-rose-400">
                      <X className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
                      {t('signoff.excluded')}
                    </span>
                  )}
                </div>
                {/* 改寫透明度：律師看得到自己把 AI 原句改成了什麼（edited_from）。 */}
                {l.edited_from && (
                  <div className="px-1">
                    <button
                      type="button"
                      onClick={() => setShowOriginalIdx(showOriginalIdx === i ? null : i)}
                      className="text-2xs text-slate-400 underline decoration-dotted underline-offset-2 hover:text-slate-600 dark:text-slate-500 dark:hover:text-slate-300"
                    >
                      {showOriginalIdx === i
                        ? t('signoff.hide_original')
                        : t('signoff.view_original')}
                    </button>
                    {showOriginalIdx === i && (
                      <div className="mt-0.5 rounded border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-500 line-through decoration-slate-400/60 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-400">
                        {l.edited_from}
                      </div>
                    )}
                  </div>
                )}
              </div>
              {/* Action cluster — always visible (touch + keyboard friendly),
                  subdued until hover/focus so the prose stays readable. */}
              <div className="flex shrink-0 gap-1 pt-0.5 opacity-60 transition group-hover:opacity-100 group-focus-within:opacity-100">
                {l.status !== 'accepted' && (
                  <IconAction
                    label={t('signoff.accept')}
                    testid="line-accept"
                    onClick={() => setStatus(i, 'accepted')}
                    className="text-emerald-700 hover:bg-emerald-50 dark:text-emerald-400 dark:hover:bg-emerald-900/30"
                  >
                    <Check className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
                  </IconAction>
                )}
                <IconAction
                  label={t('signoff.edit')}
                  testid="line-edit"
                  onClick={() => startEdit(i)}
                  className="text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  <Pencil className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
                </IconAction>
                {l.status !== 'excluded' && (
                  <IconAction
                    label={t('signoff.exclude')}
                    testid="line-exclude"
                    onClick={() => setStatus(i, 'excluded')}
                    className="text-rose-600 hover:bg-rose-50 dark:text-rose-400 dark:hover:bg-rose-900/30"
                  >
                    <X className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
                  </IconAction>
                )}
                {l.status !== 'pending' && (
                  <IconAction
                    label={t('signoff.undo')}
                    testid="line-undo"
                    onClick={() => setStatus(i, 'pending')}
                    className="text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
                  >
                    <Undo2 className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
                  </IconAction>
                )}
              </div>
            </>
          )}
        </div>
      ))}

      {/* Attorney-added line */}
      <div className="mt-2 flex items-start gap-2">
        <div className="w-6" />
        <div className="flex-1">
          <textarea
            value={addingValue}
            onChange={(e) => setAddingValue(e.target.value)}
            placeholder={t('signoff.new_line_placeholder')}
            className="w-full rounded border border-slate-200 p-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-300 dark:border-slate-700"
            rows={2}
          />
          <Button
            size="xs"
            variant="secondary"
            onClick={addLine}
            disabled={!addingValue.trim()}
            className="mt-1"
          >
            {t('signoff.add_line')}
          </Button>
        </div>
      </div>

      {/* Sign-off gate (Q16) */}
      {canExport && (
        <div className="mt-4 space-y-3 border-t pt-3 dark:border-slate-700">
          <label className="flex items-start gap-2 text-sm text-slate-700 dark:text-slate-200">
            <input
              type="checkbox"
              checked={reviewed}
              onChange={(e) => setReviewed(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-slate-300 dark:border-slate-600"
              data-testid="signoff-checkbox"
            />
            <span>{t('signoff.review_each')}</span>
          </label>

          <div className="flex items-center justify-between">
            <div className="text-xs text-slate-500 dark:text-slate-400" aria-live="polite">
              {pendingCount > 0
                ? t('signoff.undecided_hint', { count: pendingCount })
                : reviewed
                  ? null
                  : t('signoff.export_hint')}
            </div>
            <Button
              type="button"
              variant="primary"
              disabled={!reviewed || exporting || acceptedCount === 0 || pendingCount > 0}
              onClick={doExport}
              data-testid="signoff-export"
              className="disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {exporting ? t('signoff.exporting') : t('signoff.export')}
            </Button>
          </div>
          {acceptedCount === 0 && (
            <div className="text-xs text-amber-700 dark:text-amber-300">
              {t('signoff.no_accepted')}
            </div>
          )}
        </div>
      )}

      {exportResult && (
        <ExportResultPanel
          result={exportResult}
          onDownload={downloadTxt}
          onClose={() => setExportResult(null)}
          t={t}
        />
      )}
    </div>
  );
}

/** Small always-visible per-line action button (icon + text label). */
function IconAction({ label, onClick, testid, className = '', children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testid}
      aria-label={label}
      title={label}
      className={`inline-flex items-center gap-1 rounded px-1.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-500 ${className}`}
    >
      {children}
      <span className="hidden sm:inline">{label}</span>
    </button>
  );
}

function ExportResultPanel({ result, onDownload, onClose, t }) {
  const s = result.provenance_summary || {};
  return (
    <div
      className="mt-3 space-y-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-800 dark:bg-emerald-950/40"
      data-testid="export-result"
    >
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-emerald-800 dark:text-emerald-300">
          {t('signoff.result_title')}
        </h4>
        <Button
          type="button"
          variant="link"
          size="xs"
          onClick={onClose}
          className="text-slate-500 dark:text-slate-400"
        >
          {t('signoff.close')}
        </Button>
      </div>
      <div className="text-xs text-slate-600 dark:text-slate-300">
        {t('signoff.signed_off_by')}: <span className="font-medium">{result.signed_off_by}</span>
      </div>
      <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded border border-emerald-200 bg-white p-2 text-xs text-slate-800 dark:border-emerald-800 dark:bg-slate-900 dark:text-slate-200">
        {result.document}
      </pre>
      <div className="flex flex-wrap gap-2 text-xs text-slate-500 dark:text-slate-400">
        <span>
          {t('signoff.source_ai')}: {s.ai_generated ?? 0}
        </span>
        <span>
          {t('signoff.source_edited')}: {s.attorney_edited ?? 0}
        </span>
        <span>
          {t('signoff.source_added')}: {s.attorney_added ?? 0}
        </span>
        {(s.paralegal_edited ?? 0) > 0 && (
          <span>
            {t('signoff.source_paralegal_edited')}: {s.paralegal_edited}
          </span>
        )}
        {(s.paralegal_added ?? 0) > 0 && (
          <span>
            {t('signoff.source_paralegal_added')}: {s.paralegal_added}
          </span>
        )}
      </div>
      <div className="break-all font-mono text-3xs text-slate-400 dark:text-slate-500">
        {t('signoff.content_hash')}: {result.content_sha256}
      </div>
      <Button
        type="button"
        size="xs"
        onClick={onDownload}
        className="bg-emerald-600 text-white hover:bg-emerald-700"
      >
        {t('signoff.download')}
      </Button>
    </div>
  );
}

function sourceLabel(source, t) {
  if (source === 'attorney_added') return t('signoff.source_added');
  if (source === 'attorney_edited') return t('signoff.source_edited');
  if (source === 'paralegal_added') return t('signoff.source_paralegal_added');
  if (source === 'paralegal_edited') return t('signoff.source_paralegal_edited');
  return t('signoff.accepted');
}

function splitIntoLines(text) {
  if (!text) return [];
  return text
    .split(/(?<=[.。！？!?])\s+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s, i) => ({
      segment_id: `seg-${i}`,
      text: s,
      source: 'ai_generated',
      status: 'pending',
      ts: null,
    }));
}

/**
 * Q14: render [GROUNDED_REF_N] as a citation pill. Hover shows the source
 * excerpt; click fires onCitationClick → ReferencesPane scrolls to & highlights
 * the matching card (★2 跨窗格連動).
 */
function CitationHighlighter({ text, citationLookup, onCitationClick }) {
  const parts = useMemo(() => text.split(/(\[GROUNDED_REF_\d+\]|\[CITATION_REMOVED\])/g), [text]);
  return (
    <span>
      {parts.map((p, i) => {
        if (/^\[GROUNDED_REF_\d+\]$/.test(p)) {
          const hit = citationLookup?.[p];
          const clickable = hit && onCitationClick;
          const cls =
            'mx-0.5 inline-block rounded border border-navy-300 bg-navy-100 px-1.5 py-0.5 font-mono text-xs text-navy-800 dark:border-navy-700 dark:bg-navy-900/40 dark:text-navy-200';
          if (clickable) {
            return (
              <button
                key={i}
                type="button"
                onClick={() =>
                  onCitationClick({ patentNo: hit.patent_no, nonce: Date.now() })
                }
                title={`${hit.patent_no} / ${hit.section}\n\n${hit.text}`}
                className={`${cls} cursor-pointer transition-colors hover:bg-navy-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-500 dark:hover:bg-navy-800/60`}
              >
                {p}
              </button>
            );
          }
          return (
            <span key={i} title={hit ? `${hit.patent_no} / ${hit.section}\n\n${hit.text}` : p} className={`${cls} cursor-help`}>
              {p}
            </span>
          );
        }
        if (p === '[CITATION_REMOVED]') {
          return (
            <span
              key={i}
              className="mx-0.5 inline-block rounded border border-rose-300 bg-rose-100 px-1.5 py-0.5 font-mono text-xs text-rose-800 dark:border-rose-800 dark:bg-rose-900/40 dark:text-rose-300"
            >
              CITATION_REMOVED
            </span>
          );
        }
        return <span key={i}>{p}</span>;
      })}
    </span>
  );
}
