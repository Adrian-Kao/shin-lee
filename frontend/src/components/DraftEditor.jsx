import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, ApiError } from '../api/client.js';
import { toast } from '../lib/toast.jsx';

/**
 * Q16: 逐句律師標記 + 簽核匯出（責任界線）。
 *
 * 每行 (segment) 都帶 provenance：
 *   - source: 'ai_generated'  — AI 生成、律師原樣接受
 *             'attorney_edited' — AI 句被律師改寫（共同作者；改寫即回饋訊號）
 *             'attorney_added'  — 律師自行新增（全律師作者）
 *   - accepted: 律師是否將此句納入最終文件（false = 排除）
 *
 * 匯出硬性閘門（Q16 決策）：除非「我已逐項確認」勾選，否則 Export 按鈕 disabled，
 * 且後端在 attorney_signoff !== true 時回 409，前端會把「需簽核」訊息攤開，
 * 不靜默吞掉。律師簽核時清楚知道自己 endorse 了哪些 AI 句、改寫/新增了哪些。
 */
export default function DraftEditor({
  initialDraft,
  citationLookup,
  caseId,
  rejectionId,
  token,
  canExport = false,
  role,
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

  useEffect(() => {
    setLines(splitIntoLines(initialDraft));
    setReviewed(false);
    setExportResult(null);
    setEditingIdx(null);
    setAddingValue('');
  }, [initialDraft]);

  const decidedCount = lines.filter((l) => l.accepted).length;
  const acceptedCount = decidedCount;

  function accept(i) {
    setLines((ls) =>
      ls.map((l, idx) =>
        idx === i ? { ...l, accepted: true, ts: new Date().toISOString() } : l
      )
    );
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
              accepted: true,
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
        accepted: true,
        ts: new Date().toISOString(),
      },
    ]);
    setAddingValue('');
  }

  async function doExport() {
    // Belt-and-braces: the button is disabled until `reviewed`, but guard
    // here too so a stale click never sends signoff=false silently.
    if (!reviewed || !canExport || !token || !caseId) return;
    const segments = lines.map((l) => ({
      segment_id: l.segment_id,
      text: l.text,
      source: l.source,
      accepted: l.accepted,
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

  return (
    <div className="space-y-2">
      <div className="mb-2 flex gap-3 text-xs text-slate-500 dark:text-slate-400">
        <span className="ai-line px-1">{t('signoff.source_ai')}</span>
        <span className="attorney-line px-1">{t('signoff.source_edited')}</span>
        <span className="ml-auto">
          {t('signoff.decided_count', { decided: decidedCount, total: lines.length })}
        </span>
      </div>

      {lines.map((l, i) => (
        <div key={l.segment_id} className="group flex items-start gap-2">
          <div className="w-6 pt-1.5 text-xs text-slate-400 dark:text-slate-500">{i + 1}.</div>
          {editingIdx === i ? (
            <div className="flex-1">
              <textarea
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                className="w-full rounded border border-emerald-300 dark:border-emerald-800 p-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-300"
                rows={3}
              />
              <div className="mt-1 flex gap-2">
                <button
                  onClick={commitEdit}
                  className="rounded bg-emerald-600 px-2 py-1 text-xs text-white"
                >
                  {t('signoff.save')}
                </button>
                <button
                  onClick={() => setEditingIdx(null)}
                  className="rounded bg-slate-200 dark:bg-slate-700 px-2 py-1 text-xs"
                >
                  {t('signoff.cancel')}
                </button>
              </div>
            </div>
          ) : (
            <>
              <div
                className={`flex-1 ${l.source === 'ai_generated' ? 'ai-line' : 'attorney-line'} ${l.accepted ? 'opacity-100' : 'opacity-90'} px-1 leading-7`}
              >
                <CitationHighlighter text={l.text} citationLookup={citationLookup} />
                {l.accepted && (
                  <span className="ml-2 text-xs text-emerald-600">✓ {sourceLabel(l.source, t)}</span>
                )}
              </div>
              <div className="flex gap-1 opacity-0 transition group-hover:opacity-100">
                {!l.accepted && (
                  <button
                    onClick={() => accept(i)}
                    className="rounded bg-indigo-600 px-2 py-1 text-xs text-white"
                  >
                    {t('signoff.accept')}
                  </button>
                )}
                <button
                  onClick={() => startEdit(i)}
                  className="rounded bg-slate-200 dark:bg-slate-700 px-2 py-1 text-xs"
                >
                  {t('signoff.edit')}
                </button>
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
            className="w-full rounded border border-slate-200 dark:border-slate-700 p-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-300"
            rows={2}
          />
          <button
            onClick={addLine}
            disabled={!addingValue.trim()}
            className="mt-1 rounded bg-slate-200 dark:bg-slate-700 px-2 py-1 text-xs hover:bg-slate-300 disabled:opacity-50"
          >
            {t('signoff.add_line')}
          </button>
        </div>
      </div>

      {/* Sign-off gate (Q16) */}
      {canExport && (
        <div className="mt-4 space-y-3 border-t dark:border-slate-700 pt-3">
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
            <div className="text-xs text-slate-500 dark:text-slate-400">
              {reviewed ? null : t('signoff.export_hint')}
            </div>
            <button
              type="button"
              disabled={!reviewed || exporting || acceptedCount === 0}
              onClick={doExport}
              data-testid="signoff-export"
              className="rounded-md bg-navy-900 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-navy-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {exporting ? t('signoff.exporting') : t('signoff.export')}
            </button>
          </div>
          {acceptedCount === 0 && (
            <div className="text-xs text-amber-700 dark:text-amber-300">{t('signoff.no_accepted')}</div>
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

function ExportResultPanel({ result, onDownload, onClose, t }) {
  const s = result.provenance_summary || {};
  return (
    <div
      className="mt-3 space-y-2 rounded-lg border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/40 p-3"
      data-testid="export-result"
    >
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-emerald-800 dark:text-emerald-300">{t('signoff.result_title')}</h4>
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-slate-500 dark:text-slate-400 hover:underline"
        >
          {t('signoff.close')}
        </button>
      </div>
      <div className="text-xs text-slate-600 dark:text-slate-300">
        {t('signoff.signed_off_by')}: <span className="font-medium">{result.signed_off_by}</span>
      </div>
      <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded border border-emerald-200 dark:border-emerald-800 bg-white dark:bg-slate-900 p-2 text-xs text-slate-800 dark:text-slate-200">
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
      <div className="break-all font-mono text-[10px] text-slate-400 dark:text-slate-500">
        {t('signoff.content_hash')}: {result.content_sha256}
      </div>
      <button
        type="button"
        onClick={onDownload}
        className="rounded bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700"
      >
        {t('signoff.download')}
      </button>
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
      accepted: false,
      ts: null,
    }));
}

/** Q14: render [GROUNDED_REF_N] as hover-able citation pill linking to source. */
function CitationHighlighter({ text, citationLookup }) {
  const parts = useMemo(
    () => text.split(/(\[GROUNDED_REF_\d+\]|\[CITATION_REMOVED\])/g),
    [text]
  );
  return (
    <span>
      {parts.map((p, i) => {
        if (/^\[GROUNDED_REF_\d+\]$/.test(p)) {
          const hit = citationLookup?.[p];
          return (
            <span
              key={i}
              title={hit ? `${hit.patent_no} / ${hit.section}\n\n${hit.text}` : p}
              className="mx-0.5 inline-block cursor-help rounded border border-indigo-300 dark:border-indigo-700 bg-indigo-100 dark:bg-indigo-900/40 px-1.5 py-0.5 font-mono text-xs text-indigo-800 dark:text-indigo-300"
            >
              {p}
            </span>
          );
        }
        if (p === '[CITATION_REMOVED]') {
          return (
            <span
              key={i}
              className="mx-0.5 inline-block rounded border border-rose-300 dark:border-rose-800 bg-rose-100 dark:bg-rose-900/40 px-1.5 py-0.5 font-mono text-xs text-rose-800 dark:text-rose-300"
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
