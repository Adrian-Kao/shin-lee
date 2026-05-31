import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client.js';
import { toast } from '../lib/toast.jsx';
import InputPane from './analyze/InputPane.jsx';
import DraftsPane from './analyze/DraftsPane.jsx';
import ReferencesPane from './analyze/ReferencesPane.jsx';

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

/**
 * Three-pane analyze workspace (UX_RESEARCH §4.4, §5 #1 must-have).
 *
 * Desktop (≥ xl / 1280px): InputPane (30%) | DraftsPane (40%) | ReferencesPane (30%).
 * Each pane scrolls independently. Active rejection is lifted to this parent
 * so the tab strip in DraftsPane and the filter in ReferencesPane stay in sync.
 *
 * Tablet / mobile (< xl): single column, top tab strip swaps which pane renders.
 */
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
  const [showUpload, setShowUpload] = useState(true);
  const [loadedMeta, setLoadedMeta] = useState(null);
  const [uploadWarnings, setUploadWarnings] = useState([]);
  // Shared cross-pane state: which rejection is currently focused.
  const [activeRejectionId, setActiveRejectionId] = useState(null);
  // < xl: which pane is visible. Desktop ignores this.
  const [mobileTab, setMobileTab] = useState('input'); // 'input' | 'drafts' | 'refs'

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

  // When a new result arrives, default the active rejection to the first one.
  useEffect(() => {
    if (!result) {
      setActiveRejectionId(null);
      return;
    }
    const first = result.oa?.rejections?.[0]?.rejection_id;
    if (first) setActiveRejectionId(first);
  }, [result]);

  // When a new result arrives on mobile, surface the drafts tab so the
  // attorney sees the output without an extra tap.
  useEffect(() => {
    if (result) setMobileTab('drafts');
  }, [result]);

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

  // Build {[GROUNDED_REF_N]: hit} for citation hover (Q14).
  // Preserved here (not lifted into DraftsPane) so the lookup is computed once
  // per result and re-used if drafts re-render across tab switches.
  const citationLookup = useMemo(() => {
    if (!result) return {};
    const out = {};
    (result.related_prior_art || []).slice(0, 20).forEach((h, i) => {
      out[`[GROUNDED_REF_${i + 1}]`] = h;
    });
    return out;
  }, [result]);

  const inputPaneProps = {
    caseId,
    setCaseId,
    targetPatent,
    setTargetPatent,
    oaText,
    setOaText,
    showUpload,
    setShowUpload,
    loadedMeta,
    uploadWarnings,
    onExtractSuccess: handleExtractSuccess,
    session,
    onPreviewRedaction: previewRedaction,
    onAnalyze: runAnalyze,
    running,
    error,
    setError,
    onLogout,
    redactPreview,
    quota,
  };

  const draftsPaneProps = {
    result,
    running,
    activeRejectionId,
    setActiveRejectionId,
    citationLookup,
  };

  const referencesPaneProps = {
    result,
    activeRejectionId,
  };

  return (
    <div className="flex min-h-screen flex-col bg-slate-50">
      <Header session={session} onLogout={onLogout} onSwitchView={onSwitchView} />

      {result && <ResultSummaryBar result={result} />}

      {/* Mobile / tablet (< xl): single column, top tab strip swaps panes. */}
      <main className="flex flex-1 flex-col xl:hidden">
        <MobileTabBar
          activeTab={mobileTab}
          setActiveTab={setMobileTab}
          hasResult={!!result || running}
        />
        <div className="flex flex-1">
          {mobileTab === 'input' && (
            <div className="w-full">
              <InputPane {...inputPaneProps} />
            </div>
          )}
          {mobileTab === 'drafts' && (
            <div className="w-full">
              <DraftsPane {...draftsPaneProps} />
            </div>
          )}
          {mobileTab === 'refs' && (
            <div className="w-full">
              <ReferencesPane {...referencesPaneProps} />
            </div>
          )}
        </div>
      </main>

      {/* Desktop (≥ xl): three-pane side-by-side. Each pane scrolls independently. */}
      <main className="hidden flex-1 xl:grid xl:grid-cols-[3fr_4fr_3fr]">
        <div className="min-h-0 border-r bg-white">
          <InputPane {...inputPaneProps} />
        </div>
        <div className="min-h-0 border-r bg-white">
          <DraftsPane {...draftsPaneProps} />
        </div>
        <div className="min-h-0 bg-white">
          <ReferencesPane {...referencesPaneProps} />
        </div>
      </main>
    </div>
  );
}

function Header({ session, onLogout, onSwitchView }) {
  return (
    <header className="border-b bg-white">
      <div className="mx-auto flex max-w-[1920px] items-center gap-4 px-6 py-3">
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

/**
 * Slim band under the header that surfaces the cross-cutting "result metadata"
 * (policy chips + deadline). Visible above all three panes so the context is
 * not duplicated inside each pane.
 */
function ResultSummaryBar({ result }) {
  const policyChips = useMemo(
    () => [
      ['authz_passed', true],
      ['rate_limit_passed', true],
      ['quota_passed', true],
      ['cache_hit', result.cost_meta.cache_hit],
      ['circuit_open', false],
    ],
    [result]
  );

  const dr = result.deadline_summary.days_remaining;
  const tone = dr < 14 ? 'rose' : dr < 30 ? 'amber' : 'emerald';

  return (
    <div className="border-b bg-white">
      <div className="mx-auto flex max-w-[1920px] flex-wrap items-center gap-4 px-6 py-2 text-xs">
        <div className="flex flex-wrap gap-1.5">
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
        <div className={`ml-auto flex items-center gap-2 text-${tone}-700`}>
          <span className="text-xs uppercase tracking-wider text-slate-500">期日 (Q17)</span>
          <span className="font-mono">
            {new Date(result.deadline_summary.statutory_deadline).toLocaleDateString('zh-TW')}
          </span>
          <span className={`rounded bg-${tone}-100 px-2 py-0.5 font-semibold text-${tone}-700`}>
            {dr} 天
          </span>
        </div>
      </div>
    </div>
  );
}

function MobileTabBar({ activeTab, setActiveTab, hasResult }) {
  const tabs = [
    { id: 'input', label: '輸入 / Input' },
    { id: 'drafts', label: '草稿 / Drafts', disabled: !hasResult },
    { id: 'refs', label: '引證 / Refs', disabled: !hasResult },
  ];
  return (
    <div className="sticky top-0 z-10 flex border-b bg-white/95 backdrop-blur">
      {tabs.map((tab) => {
        const isActive = activeTab === tab.id;
        return (
          <button
            key={tab.id}
            onClick={() => !tab.disabled && setActiveTab(tab.id)}
            disabled={tab.disabled}
            className={`flex-1 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors ${
              isActive
                ? 'border-indigo-600 text-indigo-700'
                : tab.disabled
                  ? 'cursor-not-allowed border-transparent text-slate-300'
                  : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
