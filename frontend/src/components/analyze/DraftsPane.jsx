import React from 'react';
import { useTranslation } from 'react-i18next';
import { ShieldCheck, ShieldAlert, AlertTriangle, Loader2, CheckCircle2, Circle, FileText } from 'lucide-react';
import DraftEditor from '../DraftEditor.jsx';
import EmptyState from '../EmptyState.jsx';

/**
 * Center pane — drafts per rejection.
 *
 * Tab strip when there are 2+ rejections; otherwise renders the single
 * rejection's draft directly (UX_RESEARCH §4.4: "active rejection drives all
 * three panes" — clicking a tab updates shared state, ReferencesPane reacts).
 */
export default function DraftsPane({
  result,
  running,
  activeRejectionId,
  setActiveRejectionId,
  citationLookup,
  caseId,
  session,
}) {
  const { t } = useTranslation();

  if (running) {
    return (
      <div className="flex h-full flex-col">
        <PaneHeader title={t('analyze.pane_drafts', { defaultValue: '草稿 / Drafts' })} />
        <div className="flex-1 overflow-y-auto p-4">
          <RunningPanel />
        </div>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="flex h-full flex-col">
        <PaneHeader title={t('analyze.pane_drafts', { defaultValue: '草稿 / Drafts' })} />
        <div className="flex-1 overflow-y-auto p-4">
          <EmptyState
            icon={<FileText className="mx-auto h-10 w-10 text-slate-400 dark:text-slate-500" strokeWidth={1.5} aria-hidden="true" />}
            title={t('empty.no_result_title')}
            description={t('empty.no_result_desc')}
            hint={t('empty.no_result_hint')}
          />
        </div>
      </div>
    );
  }

  const rejections = result.oa.rejections || [];
  const activeRejection =
    rejections.find((r) => r.rejection_id === activeRejectionId) || rejections[0];
  const activeDraft = activeRejection
    ? result.drafts.find((d) => d.rejection_id === activeRejection.rejection_id)
    : null;
  const multi = rejections.length > 1;

  return (
    <div className="flex h-full flex-col">
      <PaneHeader title={t('analyze.pane_drafts', { defaultValue: '草稿 / Drafts' })}>
        <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          request: {result.request_id.slice(0, 8)}… · model:{' '}
          <span className="font-mono">{result.cost_meta.model}</span> · tokens{' '}
          {result.cost_meta.prompt_tokens}+{result.cost_meta.completion_tokens}
        </div>
        {multi && (
          <RejectionTabs
            rejections={rejections}
            activeRejectionId={activeRejection?.rejection_id}
            setActiveRejectionId={setActiveRejectionId}
          />
        )}
      </PaneHeader>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {activeRejection && (
          <RejectionDetail
            rejection={activeRejection}
            draft={activeDraft}
            citationLookup={citationLookup}
            caseId={caseId}
            session={session}
          />
        )}
      </div>
    </div>
  );
}

function PaneHeader({ title, children }) {
  return (
    <div className="sticky top-0 z-10 border-b dark:border-slate-700 bg-white/90 dark:bg-slate-900/90 px-4 py-2 backdrop-blur">
      <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">{title}</h2>
      {children}
    </div>
  );
}

function RejectionTabs({ rejections, activeRejectionId, setActiveRejectionId }) {
  return (
    <div className="-mb-2 mt-2 flex flex-wrap gap-1 overflow-x-auto">
      {rejections.map((r) => {
        const isActive = r.rejection_id === activeRejectionId;
        return (
          <button
            key={r.rejection_id}
            onClick={() => setActiveRejectionId(r.rejection_id)}
            className={`whitespace-nowrap border-b-2 px-2 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-500 ${
              isActive
                ? 'border-navy-600 text-navy-700 dark:text-navy-200'
                : 'border-transparent text-slate-500 dark:text-slate-400 hover:border-slate-300 dark:hover:border-slate-600 hover:text-slate-700 dark:hover:text-slate-200'
            }`}
          >
            <span className="font-mono">{shortType(r.rejection_type)}</span>
            <span className="ml-1 text-slate-400 dark:text-slate-500">claims {r.affected_claims.join(',')}</span>
          </button>
        );
      })}
    </div>
  );
}

// Compact label for the tab strip. e.g. 103_obviousness → §103
function shortType(t) {
  const m = /^(\d+)_/.exec(t || '');
  if (!m) return t || '';
  return `§${m[1]}`;
}

function RejectionDetail({ rejection, draft, citationLookup, caseId, session }) {
  const { t } = useTranslation();
  // Export (Q16 sign-off) is an ATTORNEY act — the backend 403s a paralegal.
  // Only surface the sign-off gate to attorneys so the UI matches the policy.
  const canExport = session?.role === 'attorney';
  const typeColor =
    {
      '102_novelty': 'rose',
      '103_obviousness': 'orange',
      '112_indefiniteness': 'amber',
      '101_subject_matter': 'purple',
    }[rejection.rejection_type] || 'slate';

  return (
    <div className="space-y-4 rounded-lg border dark:border-slate-700 bg-white dark:bg-slate-900 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <span
            className={`rounded px-2 py-0.5 text-xs bg-${typeColor}-100 text-${typeColor}-800 mr-2 font-mono`}
          >
            {rejection.rejection_type}
          </span>
          <span className="text-sm font-medium">Claims {rejection.affected_claims.join(', ')}</span>
        </div>
        <div className="text-xs text-slate-500 dark:text-slate-400">
          confidence: {(rejection.confidence * 100).toFixed(0)}%
        </div>
      </div>

      <div className="rounded border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 p-3 text-sm text-slate-700 dark:text-slate-200">
        <div className="mb-1 text-xs uppercase tracking-wider text-slate-500 dark:text-slate-400">
          {t('analyze.drafts.examiner_argument')}
        </div>
        {rejection.examiner_argument}
      </div>

      {draft && (
        <div className="border-t dark:border-slate-700 pt-4">
          {/* ★3 防幻覺面板：把後端 verifier 的把關結果畫成看得見的牆 */}
          <VerificationBanner draft={draft} />
          <div className="mb-1 text-xs uppercase tracking-wider text-slate-500 dark:text-slate-400">
            {t('analyze.drafts.strategy')}
          </div>
          <p className="mb-3 text-sm text-slate-700 dark:text-slate-200">{draft.strategy}</p>

          <div className="mb-2 text-xs uppercase tracking-wider text-slate-500 dark:text-slate-400">
            {t('analyze.drafts.signoff_label')}
          </div>
          <DraftEditor
            initialDraft={draft.draft_text}
            citationLookup={citationLookup}
            caseId={caseId}
            rejectionId={rejection.rejection_id}
            token={session?.token}
            canExport={canExport}
            role={session?.role}
          />
          <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-500 dark:text-slate-400">
            <span>grounded citations: {draft.grounded_citations.length}</span>
            <span>verifier confidence: {(draft.confidence * 100).toFixed(0)}%</span>
            <span className="ml-auto">
              requires attorney review: {draft.requires_attorney_review ? 'true' : 'false'}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * ★3 防幻覺 / Citation verification 狀態列。
 *
 * 消費後端（orchestrator）透傳的 verifier 明細：
 *   - draft.grounded_citations  — 驗證通過、保留的引用
 *   - draft.invalid_citations   — 驗證器移除的引用原文清單
 *   - draft.verifier_confidence — 驗證器獨立信心（≠ 折低後的 confidence）
 *   - draft.verifier_model      — 執行把關的模型
 * 舊後端未帶這些欄位時，退回用 draft_text 內 [CITATION_REMOVED] 計數推導；
 * 皆缺時回傳中性提示而非 crash（graceful degrade）。
 */
function VerificationBanner({ draft }) {
  const invalidCitations = Array.isArray(draft?.invalid_citations)
    ? draft.invalid_citations
    : null;
  const removedCount =
    invalidCitations != null
      ? invalidCitations.length
      : countOccurrences(draft?.draft_text || '', '[CITATION_REMOVED]');
  const groundedCount = Array.isArray(draft?.grounded_citations)
    ? draft.grounded_citations.length
    : null;
  const confidence = Number.isFinite(draft?.verifier_confidence)
    ? draft.verifier_confidence
    : Number.isFinite(draft?.confidence)
      ? draft.confidence
      : null;
  const verifierModel = draft?.verifier_model || null;

  let tone;
  let Icon;
  let title;
  if (removedCount > 0) {
    tone = 'rose';
    Icon = ShieldAlert;
    title = `${removedCount} 個引用未通過驗證、已移除 / ${removedCount} citation(s) removed`;
  } else if (groundedCount && groundedCount > 0) {
    tone = 'emerald';
    Icon = ShieldCheck;
    title = `${groundedCount} 個引用全部驗證通過 / All ${groundedCount} citation(s) verified`;
  } else {
    tone = 'slate';
    Icon = AlertTriangle;
    title = '引用驗證資訊不足 / No citation verification data';
  }

  const toneCls = {
    rose: 'border-rose-300 dark:border-rose-800 bg-rose-50 dark:bg-rose-950/40 text-rose-800 dark:text-rose-300',
    emerald: 'border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300',
    slate: 'border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-800/50 text-slate-600 dark:text-slate-300',
  }[tone];

  return (
    <div
      className={`mb-3 rounded-md border px-3 py-2 text-xs ${toneCls}`}
      data-testid="verification-banner"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
        <span className="font-semibold uppercase tracking-wider">
          幻覺防禦 / Citation verification
        </span>
        <span className="font-medium">{title}</span>
        <span className="ml-auto flex items-center gap-2 font-mono">
          {groundedCount != null && <span>grounded {groundedCount}</span>}
          {removedCount > 0 && <span className="text-rose-700 dark:text-rose-300">removed {removedCount}</span>}
          {confidence != null && <span>conf {(confidence * 100).toFixed(0)}%</span>}
        </span>
      </div>
      {invalidCitations != null && invalidCitations.length > 0 && (
        <div className="mt-1 break-words font-mono text-2xs text-rose-700 dark:text-rose-300">
          已移除 / removed: {invalidCitations.join('、')}
        </div>
      )}
      {verifierModel && (
        <div className="mt-1 text-2xs text-slate-500 dark:text-slate-400">
          由 {verifierModel} 把關 / verified by {verifierModel}
        </div>
      )}
    </div>
  );
}

function countOccurrences(haystack, needle) {
  if (!haystack || !needle) return 0;
  let count = 0;
  let idx = haystack.indexOf(needle);
  while (idx !== -1) {
    count += 1;
    idx = haystack.indexOf(needle, idx + needle.length);
  }
  return count;
}

// Approximate stage timings observed on CPU llama3.1:8b for a typical 1-rejection OA.
// Mirrors the original Analyze.jsx STAGES so we keep visual parity during loading.
const STAGES = [
  { name: 'redact', key: 'analyze.stages.redact', untilSec: 1 },
  { name: 'parse', key: 'analyze.stages.parse', untilSec: 60 },
  { name: 'retrieve', key: 'analyze.stages.retrieve', untilSec: 65 },
  { name: 'draft', key: 'analyze.stages.draft', untilSec: 200 },
  { name: 'verify', key: 'analyze.stages.verify', untilSec: 290 },
  { name: 'deadline', key: 'analyze.stages.deadline', untilSec: 295 },
  { name: 'unmask', key: 'analyze.stages.unmask', untilSec: Infinity },
];

function fmtElapsed(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

function RunningPanel() {
  const { t } = useTranslation();
  const [tick, setTick] = React.useState(0);
  const startRef = React.useRef(Date.now());

  React.useEffect(() => {
    startRef.current = Date.now();
    const id = setInterval(() => setTick((t) => t + 1), 500);
    return () => clearInterval(id);
  }, []);

  // tick is referenced to keep the linter happy and to force re-render.
  void tick;

  const elapsedMs = Date.now() - startRef.current;
  const elapsedSec = elapsedMs / 1000;
  const currentIdx = STAGES.findIndex((s) => elapsedSec < s.untilSec);
  const safeIdx = currentIdx === -1 ? STAGES.length - 1 : currentIdx;

  return (
    <div className="rounded-lg border dark:border-slate-700 bg-white dark:bg-slate-900 p-8">
      <div className="mb-4 flex items-baseline justify-between">
        <div className="flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin text-navy-600 dark:text-navy-300" strokeWidth={1.75} aria-hidden="true" />
          <span className="font-semibold text-slate-700 dark:text-slate-200">{t('analyze.drafts.analyzing')}</span>
        </div>
        <div className="font-mono text-2xl tabular-nums text-navy-700 dark:text-navy-200">
          {fmtElapsed(elapsedMs)}
        </div>
      </div>

      <div className="space-y-2">
        {STAGES.map((stage, i) => {
          const done = i < safeIdx;
          const active = i === safeIdx;
          return (
            <div key={stage.name} className="flex items-center gap-3 text-sm">
              <span
                className={`inline-flex w-5 justify-center ${
                  done ? 'text-emerald-600 dark:text-emerald-400' : active ? 'text-navy-600 dark:text-navy-300' : 'text-slate-300 dark:text-slate-600'
                }`}
              >
                {done ? (
                  <CheckCircle2 className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
                ) : active ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.75} aria-hidden="true" />
                ) : (
                  <Circle className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
                )}
              </span>
              <span
                className={
                  done
                    ? 'text-slate-500 dark:text-slate-400 line-through decoration-emerald-300/60'
                    : active
                      ? 'font-medium text-slate-800 dark:text-slate-200'
                      : 'text-slate-400 dark:text-slate-500'
                }
              >
                {t(stage.key)}
              </span>
              {active && (
                <span className="ml-auto animate-pulse text-xs text-navy-500 dark:text-navy-300">running…</span>
              )}
            </div>
          );
        })}
      </div>

      <p className="mt-5 text-xs leading-relaxed text-slate-400 dark:text-slate-500">
        {t('analyze.drafts.running_note')}
      </p>
    </div>
  );
}
