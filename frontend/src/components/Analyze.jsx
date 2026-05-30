import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client.js';
import DraftEditor from './DraftEditor.jsx';
import OAUpload from './OAUpload.jsx';
import ErrorBanner from './ErrorBanner.jsx';
import EmptyState from './EmptyState.jsx';
import { SkeletonText } from './Skeleton.jsx';
import { toast } from '../lib/toast.jsx';

const SAMPLE_OA = `UNITED STATES PATENT AND TRADEMARK OFFICE
Office Action

Application No.: 17/123,456
Applicant: NCCU Apex Patent Law Firm (file ref: APEX-2025-0314, client: CL-EVCO12)
Examiner: J. Smith
Mailing Date: 2025-04-15

Claims 1-3 are rejected under 35 U.S.C. § 103 as being obvious over US7654321
in view of US6543210. The combination of microchannels with non-uniform
cross-section and copper construction yields predictable results.

Claims 4-5 are rejected under 35 U.S.C. § 102 as anticipated by US7654321.

Attorney contact: alice.chen@apex-ip.com (mobile: 0912-345-678)
`;

const SECURITY_BADGE = {
  rate_limit_passed: { ok: '✓ RPM', no: '✗ RPM' },
  quota_passed: { ok: '✓ Quota', no: '✗ Quota' },
  authz_passed: { ok: '✓ Authz', no: '✗ Authz' },
  cache_hit: { ok: '⚡ Cache', no: '🆕 Fresh' },
  circuit_open: { ok: '⚠ Breaker', no: '✓ Breaker OK' },
};

export default function Analyze({ session, onLogout, onSwitchView }) {
  const { t } = useTranslation();
  const [oaText, setOaText] = useState(SAMPLE_OA);
  const [caseId, setCaseId] = useState('CASE-2025-001');
  const [targetPatent, setTargetPatent] = useState('US17123456');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [redactPreview, setRedactPreview] = useState(null);
  const [quota, setQuota] = useState(null);
  // Day 2 upload UI state (additive — does not change the analyze POST contract)
  const [showUpload, setShowUpload] = useState(true);
  const [loadedMeta, setLoadedMeta] = useState(null); // {fileName, page_count} after extraction
  const [uploadWarnings, setUploadWarnings] = useState([]);

  const handleExtractSuccess = (payload) => {
    setOaText(payload.extracted_text || '');
    setLoadedMeta({ fileName: payload.fileName, pages: payload.page_count });
    setUploadWarnings(Array.isArray(payload.warnings) ? payload.warnings : []);
    toast.success(t('upload.toast_success', { pages: payload.page_count ?? 0 }));
  };

  useEffect(() => {
    api
      .quota(session.token, caseId)
      .then(setQuota)
      .catch(() => {});
  }, [session.token, caseId, result]);

  async function previewRedaction() {
    try {
      const r = await api.redactionPreview(session.token, oaText, caseId);
      setRedactPreview(r);
    } catch (e) {
      setError(e);
    }
  }

  async function runAnalyze() {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const r = await api.analyze(session.token, {
        oa_text: oaText,
        case_id: caseId,
        target_patent_no: targetPatent,
      });
      setResult(r);
    } catch (e) {
      setError(e);
    } finally {
      setRunning(false);
    }
  }

  // Build {[GROUNDED_REF_N]: hit} for citation hover (Q14)
  const citationLookup = useMemo(() => {
    if (!result) return {};
    const out = {};
    (result.related_prior_art || []).slice(0, 20).forEach((h, i) => {
      out[`[GROUNDED_REF_${i + 1}]`] = h;
    });
    return out;
  }, [result]);

  return (
    <div className="flex min-h-screen flex-col">
      <Header session={session} onLogout={onLogout} onSwitchView={onSwitchView} />

      <main className="mx-auto grid w-full max-w-7xl flex-1 grid-cols-1 gap-6 px-6 py-6 lg:grid-cols-3">
        {/* Left: input */}
        <section className="space-y-4 lg:col-span-1">
          <div className="rounded-lg border bg-white p-4">
            <h2 className="mb-3 font-semibold">輸入 OA</h2>
            <label className="mb-1 block text-xs text-slate-500">Case ID</label>
            <input
              value={caseId}
              onChange={(e) => setCaseId(e.target.value)}
              className="mb-3 w-full rounded border px-2 py-1.5 text-sm"
            />
            <label className="mb-1 block text-xs text-slate-500">Target patent (本案)</label>
            <input
              value={targetPatent}
              onChange={(e) => setTargetPatent(e.target.value)}
              className="mb-3 w-full rounded border px-2 py-1.5 text-sm"
            />
            {showUpload && (
              <div className="mb-3">
                <OAUpload
                  caseId={caseId}
                  token={session.token}
                  onExtractSuccess={handleExtractSuccess}
                  onError={(err) => setError(err?.message || String(err))}
                />
                <button
                  type="button"
                  onClick={() => setShowUpload(false)}
                  className="mt-2 text-xs text-indigo-600 hover:underline"
                >
                  {t('upload.switch_to_paste')}
                </button>
              </div>
            )}
            {!showUpload && (
              <button
                type="button"
                onClick={() => setShowUpload(true)}
                className="mb-2 text-xs text-indigo-600 hover:underline"
              >
                {t('upload.switch_to_upload')}
              </button>
            )}

            {loadedMeta && (
              <div className="mb-2 inline-block rounded border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs text-emerald-800">
                {t('upload.loaded_chip', {
                  filename: loadedMeta.fileName,
                  pages: loadedMeta.pages ?? 0,
                })}
              </div>
            )}
            {uploadWarnings.length > 0 && (
              <div className="mb-2 space-y-1">
                {uploadWarnings.map((w, i) => (
                  <div
                    key={i}
                    className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-800"
                  >
                    ⚠ {w}
                  </div>
                ))}
              </div>
            )}

            <label className="mb-1 block text-xs text-slate-500">OA 全文</label>
            <textarea
              value={oaText}
              onChange={(e) => setOaText(e.target.value)}
              rows={14}
              className="w-full rounded border px-2 py-1.5 font-mono text-xs"
            />
            <div className="mt-3 flex gap-2">
              <button
                onClick={previewRedaction}
                className="flex-1 rounded bg-slate-200 px-3 py-2 text-sm hover:bg-slate-300"
              >
                預覽 redaction
              </button>
              <button
                onClick={runAnalyze}
                disabled={running}
                className="flex-1 rounded bg-indigo-600 px-3 py-2 text-sm text-white hover:bg-indigo-700 disabled:bg-slate-400"
              >
                {running ? '分析中…' : '分析 OA'}
              </button>
            </div>
            {error && (
              <div className="mt-3">
                <ErrorBanner
                  error={error}
                  onRetry={runAnalyze}
                  onDismiss={() => setError(null)}
                  onLogin={onLogout}
                />
              </div>
            )}
          </div>

          {redactPreview && (
            <div className="rounded-lg border bg-white p-4">
              <h3 className="mb-2 text-sm font-semibold">
                Redaction 預覽 <span className="text-xs text-slate-500">(Q10)</span>
              </h3>
              <div className="mb-2 whitespace-pre-wrap rounded border border-amber-200 bg-amber-50 p-2 font-mono text-xs">
                {redactPreview.redacted}
              </div>
              <div className="text-xs">
                <span className="text-slate-500">觸發規則：</span>
                {redactPreview.rules_triggered.map((r) => (
                  <span
                    key={r}
                    className="mr-1 inline-block rounded bg-slate-100 px-1.5 py-0.5 font-mono"
                  >
                    {r}
                  </span>
                ))}
              </div>
            </div>
          )}

          {!quota && (
            <div className="rounded-lg border bg-white p-4">
              <h3 className="mb-2 text-sm font-semibold">
                配額 <span className="text-xs text-slate-500">(Q18)</span>
              </h3>
              <SkeletonText lines={3} />
            </div>
          )}

          {quota && (
            <div className="rounded-lg border bg-white p-4">
              <h3 className="mb-2 text-sm font-semibold">
                配額 <span className="text-xs text-slate-500">(Q18)</span>
              </h3>
              <Bar
                label="今日 token (你)"
                used={quota.user_daily_used}
                total={quota.user_daily_limit}
              />
              <Bar
                label="本月 token (tenant)"
                used={quota.tenant_monthly_used}
                total={quota.tenant_monthly_cap}
              />
              <div className="mt-2 text-xs text-slate-500">
                Cost breaker: ${quota.circuit_breaker.current_usd} / $
                {quota.circuit_breaker.threshold_usd}
                {quota.circuit_breaker.tripped && (
                  <span className="ml-2 font-semibold text-rose-600">TRIPPED</span>
                )}
              </div>
            </div>
          )}
        </section>

        {/* Right: result */}
        <section className="space-y-4 lg:col-span-2">
          {!result && !running && (
            <EmptyState
              icon="📄"
              title={t('empty.no_result_title')}
              description={t('empty.no_result_desc')}
              hint={t('empty.no_result_hint')}
            />
          )}

          {running && <RunningPanel />}

          {result && <ResultView result={result} citationLookup={citationLookup} />}
        </section>
      </main>
    </div>
  );
}

function Header({ session, onLogout, onSwitchView }) {
  return (
    <header className="border-b bg-white">
      <div className="mx-auto flex max-w-7xl items-center gap-4 px-6 py-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded bg-indigo-600 text-sm font-bold text-white">
            PM
          </div>
          <span className="font-semibold">PatentMind AI</span>
          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs uppercase tracking-wider text-amber-800">
            POC
          </span>
        </div>
        <nav className="ml-6 flex gap-1">
          <button
            onClick={() => onSwitchView('analyze')}
            className="rounded bg-indigo-50 px-3 py-1.5 text-sm font-medium text-indigo-700"
          >
            分析
          </button>
          <button
            onClick={() => onSwitchView('audit')}
            className="rounded px-3 py-1.5 text-sm hover:bg-slate-100"
          >
            Audit
          </button>
        </nav>
        <div className="ml-auto flex items-center gap-3 text-sm">
          <div className="text-right">
            <div className="font-medium">{session.display_name}</div>
            <div className="text-xs text-slate-500">
              {session.tenant_id} · {session.role}
            </div>
          </div>
          <button onClick={onLogout} className="rounded bg-slate-200 px-2 py-1 text-xs">
            登出
          </button>
        </div>
      </div>
    </header>
  );
}

function ResultView({ result, citationLookup }) {
  const policyChips = useMemo(() => {
    // Build from cost meta + audit-style decisions
    return [
      ['authz_passed', true],
      ['rate_limit_passed', true],
      ['quota_passed', true],
      ['cache_hit', result.cost_meta.cache_hit],
      ['circuit_open', false],
    ];
  }, [result]);

  return (
    <>
      <div className="rounded-lg border bg-white p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="font-semibold">
            分析結果{' '}
            <span className="text-xs font-normal text-slate-500">
              request: {result.request_id.slice(0, 8)}…
            </span>
          </h2>
          <div className="text-xs text-slate-500">
            model: <span className="font-mono">{result.cost_meta.model}</span> · tokens:{' '}
            {result.cost_meta.prompt_tokens}+{result.cost_meta.completion_tokens} · ~$
            {result.cost_meta.estimated_cost_usd.toFixed(4)}
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
          {policyChips.map(([k, v]) => {
            const def = SECURITY_BADGE[k];
            const pos = k === 'cache_hit' || k === 'circuit_open' ? !v : v;
            const label = pos ? def.ok : def.no;
            return (
              <span
                key={k}
                className={`rounded px-2 py-0.5 font-mono ${
                  k === 'cache_hit'
                    ? 'bg-amber-100 text-amber-800'
                    : pos
                      ? 'bg-emerald-100 text-emerald-800'
                      : 'bg-rose-100 text-rose-800'
                }`}
              >
                {label}
              </span>
            );
          })}
        </div>
      </div>

      <DeadlineCard deadline={result.deadline_summary} oa={result.oa} />

      {result.oa.rejections.map((rej) => {
        const draft = result.drafts.find((d) => d.rejection_id === rej.rejection_id);
        const hits = result.related_prior_art.filter((h) =>
          rej.cited_prior_art.includes(h.patent_no)
        );
        return (
          <RejectionBlock
            key={rej.rejection_id}
            rejection={rej}
            draft={draft}
            hits={hits}
            citationLookup={citationLookup}
          />
        );
      })}
    </>
  );
}

function Bar({ label, used, total }) {
  const pct = total ? Math.min(100, (used / total) * 100) : 0;
  const isHigh = pct > 80;
  return (
    <div className="mb-2">
      <div className="flex justify-between text-xs text-slate-600">
        <span>{label}</span>
        <span>
          {used.toLocaleString()} / {total.toLocaleString()}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-200">
        <div
          className={`h-full ${isHigh ? 'bg-rose-500' : 'bg-indigo-500'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function DeadlineCard({ deadline, oa }) {
  const dr = deadline.days_remaining;
  const tone = dr < 14 ? 'rose' : dr < 30 ? 'amber' : 'emerald';
  return (
    <div className={`bg-${tone}-50 border border-${tone}-300 rounded-lg p-4`}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-xs uppercase tracking-wider text-slate-500">法定期日 (Q17)</div>
          <div className="mt-0.5 text-2xl font-semibold">
            {new Date(deadline.statutory_deadline).toLocaleDateString('zh-TW')}
          </div>
          <div className="mt-1 text-sm text-slate-600">
            內部建議完成日{' '}
            {new Date(deadline.recommended_internal_deadline).toLocaleDateString('zh-TW')}
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs text-slate-500">剩餘</div>
          <div className={`text-3xl font-bold text-${tone}-700`}>{dr}</div>
          <div className="text-xs text-slate-500">天</div>
        </div>
      </div>
      {deadline.warnings && deadline.warnings.length > 0 && (
        <div className="mt-3 space-y-1 text-xs text-slate-700">
          {deadline.warnings.map((w, i) => (
            <div key={i}>• {w}</div>
          ))}
        </div>
      )}
      <div className="mt-2 text-xs text-slate-500">
        calendar version: <span className="font-mono">{deadline.holiday_calendar_version}</span>
      </div>
    </div>
  );
}

function RejectionBlock({ rejection, draft, hits, citationLookup }) {
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

      <div>
        <div className="mb-1 text-xs uppercase tracking-wider text-slate-500">引證案</div>
        <div className="flex flex-wrap gap-1">
          {rejection.cited_prior_art.map((p) => (
            <span key={p} className="rounded bg-slate-100 px-2 py-0.5 font-mono text-xs">
              {p}
            </span>
          ))}
        </div>
      </div>

      {hits.length > 0 && (
        <div>
          <div className="mb-1 text-xs uppercase tracking-wider text-slate-500">
            RAG retrieval (Q6, Q7, Q14 grounding)
          </div>
          <div className="space-y-1">
            {hits.slice(0, 3).map((h, i) => (
              <details key={i} className="rounded border border-slate-200 p-2 text-xs">
                <summary className="cursor-pointer">
                  <span className="font-mono">{h.patent_no}</span>
                  <span className="text-slate-500">
                    {' '}
                    · {h.section} · score {h.score.toFixed(3)}
                  </span>
                </summary>
                <div className="mt-2 whitespace-pre-wrap text-slate-600">{h.text}</div>
              </details>
            ))}
          </div>
        </div>
      )}

      {draft && (
        <div className="border-t pt-4">
          <div className="mb-1 text-xs uppercase tracking-wider text-slate-500">答辯策略</div>
          <p className="mb-3 text-sm text-slate-700">{draft.strategy}</p>

          <div className="mb-2 text-xs uppercase tracking-wider text-slate-500">
            草稿（律師逐句簽核 — Q16）
          </div>
          <DraftEditor initialDraft={draft.draft_text} citationLookup={citationLookup} />
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
// We don't have per-step server events in the MVP, so we estimate stage from elapsed seconds.
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
  const [tick, setTick] = useState(0);
  const startRef = React.useRef(Date.now());

  useEffect(() => {
    startRef.current = Date.now();
    const id = setInterval(() => setTick((t) => t + 1), 500);
    return () => clearInterval(id);
  }, []);

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
