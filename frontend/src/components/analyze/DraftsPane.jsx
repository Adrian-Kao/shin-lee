import React from 'react';
import { useTranslation } from 'react-i18next';
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
            icon="📄"
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
        <div className="mt-1 text-xs text-slate-500">
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
    <div className="sticky top-0 z-10 border-b bg-white/90 px-4 py-2 backdrop-blur">
      <h2 className="text-sm font-semibold text-slate-700">{title}</h2>
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
            className={`whitespace-nowrap border-b-2 px-2 py-1.5 text-xs font-medium transition-colors ${
              isActive
                ? 'border-indigo-600 text-indigo-700'
                : 'border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-700'
            }`}
          >
            <span className="font-mono">{shortType(r.rejection_type)}</span>
            <span className="ml-1 text-slate-400">claims {r.affected_claims.join(',')}</span>
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
    <div className="space-y-4 rounded-lg border bg-white p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <span
            className={`rounded px-2 py-0.5 text-xs bg-${typeColor}-100 text-${typeColor}-800 mr-2 font-mono`}
          >
            {rejection.rejection_type}
          </span>
          <span className="text-sm font-medium">Claims {rejection.affected_claims.join(', ')}</span>
        </div>
        <div className="text-xs text-slate-500">
          confidence: {(rejection.confidence * 100).toFixed(0)}%
        </div>
      </div>

      <div className="rounded border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
        <div className="mb-1 text-xs uppercase tracking-wider text-slate-500">Examiner 論點</div>
        {rejection.examiner_argument}
      </div>

      {draft && (
        <div className="border-t pt-4">
          <div className="mb-1 text-xs uppercase tracking-wider text-slate-500">答辯策略</div>
          <p className="mb-3 text-sm text-slate-700">{draft.strategy}</p>

          <div className="mb-2 text-xs uppercase tracking-wider text-slate-500">
            草稿（律師逐句簽核 — Q16）
          </div>
          <DraftEditor
            initialDraft={draft.draft_text}
            citationLookup={citationLookup}
            caseId={caseId}
            rejectionId={rejection.rejection_id}
            token={session?.token}
            canExport={canExport}
          />
          <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-500">
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

// Approximate stage timings observed on CPU llama3.1:8b for a typical 1-rejection OA.
// Mirrors the original Analyze.jsx STAGES so we keep visual parity during loading.
const STAGES = [
  { name: 'redact', label: '遮罩 PII / 客戶識別碼 (Q10)', untilSec: 1 },
  { name: 'parse', label: '解析 OA 鑑別 rejection (parse_oa)', untilSec: 60 },
  { name: 'retrieve', label: '檢索先前技術 (RAG, Q6+Q7)', untilSec: 65 },
  { name: 'draft', label: '草擬答辯 (draft_response, grounded Q14)', untilSec: 200 },
  { name: 'verify', label: '驗證引證 (verify_citations, Q14)', untilSec: 290 },
  { name: 'deadline', label: '計算期日 (Q17)', untilSec: 295 },
  { name: 'unmask', label: '回填 PII，整理回應', untilSec: Infinity },
];

function fmtElapsed(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

function RunningPanel() {
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
    <div className="rounded-lg border bg-white p-8">
      <div className="mb-4 flex items-baseline justify-between">
        <div className="flex items-center gap-2">
          <span className="animate-pulse text-2xl">⏳</span>
          <span className="font-semibold text-slate-700">分析中…</span>
        </div>
        <div className="font-mono text-2xl tabular-nums text-indigo-700">
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
                  done ? 'text-emerald-600' : active ? 'text-indigo-600' : 'text-slate-300'
                }`}
              >
                {done ? '✓' : active ? '●' : '○'}
              </span>
              <span
                className={
                  done
                    ? 'text-slate-500 line-through decoration-emerald-300/60'
                    : active
                      ? 'font-medium text-slate-800'
                      : 'text-slate-400'
                }
              >
                {stage.label}
              </span>
              {active && (
                <span className="ml-auto animate-pulse text-xs text-indigo-500">running…</span>
              )}
            </div>
          );
        })}
      </div>

      <p className="mt-5 text-xs leading-relaxed text-slate-400">
        地端 llama3.1:8b 於 CPU 推論，單次分析約 5–7 分鐘。再次送出相同 OA + case 會命中 cache（&lt;
        1 秒）。
      </p>
    </div>
  );
}
