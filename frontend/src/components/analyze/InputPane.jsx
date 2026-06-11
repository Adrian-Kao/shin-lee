import React from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, ClipboardPaste, Paperclip } from 'lucide-react';
import OAUpload from '../OAUpload.jsx';
import ErrorBanner from '../ErrorBanner.jsx';
import { SkeletonText } from '../Skeleton.jsx';
import ClaimTree from './ClaimTree.jsx';
import { Button } from '../ui/button.jsx';

/**
 * Left pane — OA input + redaction preview + quota / deadline summary.
 *
 * Pure presentational; all state and handlers are owned by the Analyze parent
 * (see UX_RESEARCH §4.4: three-pane layout with independent scroll per pane).
 *
 * Header is sticky so context never disappears during scroll on desktop.
 */
export default function InputPane({
  // form state
  caseId,
  setCaseId,
  targetPatent,
  setTargetPatent,
  oaText,
  setOaText,
  // upload state
  showUpload,
  setShowUpload,
  loadedMeta,
  uploadWarnings,
  onExtractSuccess,
  session,
  // actions
  onPreviewRedaction,
  previewing = false,
  onAnalyze,
  running,
  // status
  error,
  setError,
  onLogout,
  redactPreview,
  quota,
  // claim tree (UX_RESEARCH §5 #2)
  claimTree = [],
  rejections = [],
  activeRejectionId = null,
  setActiveRejectionId = null,
}) {
  const { t } = useTranslation();

  return (
    <div className="flex h-full flex-col">
      <PaneHeader title={t('analyze.pane_input', { defaultValue: '輸入 OA / Input' })} />

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        <div className="rounded-lg border bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
          <label
            htmlFor="analyze-case-id"
            className="mb-1 block text-xs text-slate-500 dark:text-slate-400"
          >
            {t('analyze.input.case_id')}
          </label>
          <input
            id="analyze-case-id"
            value={caseId}
            onChange={(e) => setCaseId(e.target.value)}
            className="mb-3 w-full rounded border px-2 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-500 dark:border-slate-700 dark:bg-slate-800"
          />
          <label
            htmlFor="analyze-target-patent"
            className="mb-1 block text-xs text-slate-500 dark:text-slate-400"
          >
            {t('analyze.input.target_patent')}
          </label>
          <input
            id="analyze-target-patent"
            value={targetPatent}
            onChange={(e) => setTargetPatent(e.target.value)}
            className="mb-3 w-full rounded border px-2 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-500 dark:border-slate-700 dark:bg-slate-800"
          />

          {showUpload && (
            <div className="mb-3">
              <OAUpload
                caseId={caseId}
                token={session.token}
                onExtractSuccess={onExtractSuccess}
                onError={(err) => setError(err?.message ? err : new Error(String(err)))}
              />
              <button
                type="button"
                onClick={() => setShowUpload(false)}
                className="mt-2 inline-flex items-center gap-1 rounded text-xs text-navy-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-500 dark:text-navy-200"
              >
                <ClipboardPaste className="h-3 w-3" strokeWidth={1.75} aria-hidden="true" />
                {t('upload.switch_to_paste')}
              </button>
            </div>
          )}
          {!showUpload && (
            <button
              type="button"
              onClick={() => setShowUpload(true)}
              className="mb-2 inline-flex items-center gap-1 rounded text-xs text-navy-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-500 dark:text-navy-200"
            >
              <Paperclip className="h-3 w-3" strokeWidth={1.75} aria-hidden="true" />
              {t('upload.switch_to_upload')}
            </button>
          )}

          {loadedMeta && (
            <div className="mb-2 inline-block rounded border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300">
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
                  className="flex items-start gap-1.5 rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300"
                >
                  <AlertTriangle
                    className="mt-0.5 h-3 w-3 shrink-0"
                    strokeWidth={1.75}
                    aria-hidden="true"
                  />
                  <span>{w}</span>
                </div>
              ))}
            </div>
          )}

          <label
            htmlFor="analyze-oa-text"
            className="mb-1 block text-xs text-slate-500 dark:text-slate-400"
          >
            {t('analyze.input.oa_full_text')}
          </label>
          <textarea
            id="analyze-oa-text"
            value={oaText}
            onChange={(e) => setOaText(e.target.value)}
            rows={12}
            className="w-full rounded border px-2 py-1.5 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-500 dark:border-slate-700 dark:bg-slate-800"
          />
          <div className="mt-3 flex gap-2">
            <Button
              variant="secondary"
              onClick={onPreviewRedaction}
              disabled={previewing}
              className="flex-1 disabled:cursor-wait"
            >
              {t('analyze.input.preview_redaction')}
            </Button>
            <Button
              variant="primary"
              onClick={onAnalyze}
              disabled={running}
              className="flex-1 disabled:cursor-wait"
            >
              {running ? t('analyze.input.analyzing') : t('analyze.input.analyze_oa')}
            </Button>
          </div>
          {error && (
            <div className="mt-3">
              <ErrorBanner
                error={error}
                onRetry={onAnalyze}
                onDismiss={() => setError(null)}
                onLogin={onLogout}
              />
            </div>
          )}
        </div>

        {/*
         * UX_RESEARCH §5 #2 — claim dependency tree.
         * Only renders once an analysis has produced a `claim_tree`; until
         * then this is a no-op (ClaimTree returns null on empty).
         * Mounted between the OA card and the redaction-preview card so
         * it sits naturally next to the "what claims got rejected" data
         * the attorney is reasoning about.
         */}
        {claimTree && claimTree.length > 0 && (
          <ClaimTree
            claimTree={claimTree}
            rejections={rejections}
            activeRejectionId={activeRejectionId}
            onClaimClick={(_claim_no, rejection_id) => {
              if (setActiveRejectionId && rejection_id) {
                setActiveRejectionId(rejection_id);
              }
            }}
          />
        )}

        {redactPreview && (
          <div className="rounded-lg border bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
            <h3 className="mb-2 text-sm font-semibold">
              {t('analyze.input.redaction_preview_title')}{' '}
              <span className="text-xs text-slate-500 dark:text-slate-400">(Q10)</span>
            </h3>
            <div className="mb-2 whitespace-pre-wrap rounded border border-amber-200 bg-amber-50 p-2 font-mono text-xs dark:border-amber-800 dark:bg-amber-950/40">
              {redactPreview.redacted}
            </div>
            <div className="text-xs">
              <span className="text-slate-500 dark:text-slate-400">
                {t('analyze.input.rules_triggered')}
              </span>
              {redactPreview.rules_triggered.map((r) => (
                <span
                  key={r}
                  className="mr-1 inline-block rounded bg-slate-100 px-1.5 py-0.5 font-mono dark:bg-slate-800"
                >
                  {r}
                </span>
              ))}
            </div>
          </div>
        )}

        {!quota && (
          <div className="rounded-lg border bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
            <h3 className="mb-2 text-sm font-semibold">
              {t('analyze.input.quota')}{' '}
              <span className="text-xs text-slate-500 dark:text-slate-400">(Q18)</span>
            </h3>
            <SkeletonText lines={3} />
          </div>
        )}

        {quota && (
          <div className="rounded-lg border bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
            <h3 className="mb-2 text-sm font-semibold">
              {t('analyze.input.quota')}{' '}
              <span className="text-xs text-slate-500 dark:text-slate-400">(Q18)</span>
            </h3>
            <Bar
              label={t('analyze.input.token_today')}
              used={quota.user_daily_used}
              total={quota.user_daily_limit}
            />
            <Bar
              label={t('analyze.input.token_month')}
              used={quota.tenant_monthly_used}
              total={quota.tenant_monthly_cap}
            />
            <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
              {t('analyze.input.cost_breaker')}: ${quota.circuit_breaker.current_usd} / $
              {quota.circuit_breaker.threshold_usd}
              {quota.circuit_breaker.tripped && (
                <span className="ml-2 font-semibold text-rose-600 dark:text-rose-300">
                  {t('analyze.input.cost_breaker_tripped')}
                </span>
              )}
            </div>
          </div>
        )}

        {quota?.budget && <BudgetPanel budget={quota.budget} t={t} />}
      </div>
    </div>
  );
}

function PaneHeader({ title, subtitle }) {
  return (
    <div className="sticky top-0 z-10 border-b bg-white/90 px-4 py-2 backdrop-blur dark:border-slate-700 dark:bg-slate-900/90">
      <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">{title}</h2>
      {subtitle && <p className="text-xs text-slate-500 dark:text-slate-400">{subtitle}</p>}
    </div>
  );
}

/**
 * Q18 budget dashboard — compact panel. Reads the `budget` block the quota
 * endpoint now returns (month-to-date spend, projected month-end, per-model
 * breakdown, and an on-track / will-exceed badge). Reuses the existing quota
 * fetch in Analyze.jsx — no extra request.
 */
function BudgetPanel({ budget, t }) {
  const forecast = budget.forecast || {};
  const perModel = Array.isArray(budget.per_model) ? budget.per_model : [];
  const status = budget.status || 'no_cap';

  const badge =
    status === 'will_exceed'
      ? {
          cls: 'bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300',
          label: t('budget.will_exceed'),
        }
      : status === 'on_track'
        ? {
            cls: 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-800 dark:text-emerald-300',
            label: t('budget.on_track'),
          }
        : {
            cls: 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300',
            label: t('budget.no_cap'),
          };

  const fmt = (n) => `$${Number(n ?? 0).toFixed(2)}`;
  const cap = forecast.tenant_monthly_cap_usd;

  return (
    <div className="rounded-lg border bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold">
          {t('budget.title')}{' '}
          <span className="text-xs text-slate-500 dark:text-slate-400">(Q18)</span>
        </h3>
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${badge.cls}`}>
          {badge.label}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="rounded border border-slate-100 bg-slate-50 p-2 dark:border-slate-700 dark:bg-slate-800/50">
          <div className="text-slate-500 dark:text-slate-400">{t('budget.month_to_date')}</div>
          <div className="font-mono text-sm text-slate-800 dark:text-slate-200">
            {fmt(forecast.month_to_date_usd)}
          </div>
        </div>
        <div className="rounded border border-slate-100 bg-slate-50 p-2 dark:border-slate-700 dark:bg-slate-800/50">
          <div className="text-slate-500 dark:text-slate-400">{t('budget.projected')}</div>
          <div className="font-mono text-sm text-slate-800 dark:text-slate-200">
            {fmt(forecast.projected_month_end_usd)}
            {cap != null && (
              <span className="ml-1 text-3xs text-slate-400 dark:text-slate-500">
                / {fmt(cap)} {t('budget.cap')}
              </span>
            )}
          </div>
        </div>
      </div>

      {perModel.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-xs uppercase tracking-wider text-slate-500 dark:text-slate-400">
            {t('budget.per_model')}
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-slate-400 dark:text-slate-500">
                <th className="font-normal">{t('budget.model')}</th>
                <th className="text-right font-normal">{t('budget.today')}</th>
                <th className="text-right font-normal">{t('budget.month_to_date')}</th>
              </tr>
            </thead>
            <tbody>
              {perModel.map((m) => (
                <tr key={m.model} className="border-t border-slate-100 dark:border-slate-700">
                  <td className="truncate py-1 pr-2 font-mono">{m.model}</td>
                  <td className="py-1 text-right font-mono text-slate-600 dark:text-slate-300">
                    {fmt(m.today_usd)}
                  </td>
                  <td className="py-1 text-right font-mono text-slate-800 dark:text-slate-200">
                    {fmt(m.month_to_date_usd)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Bar({ label, used, total }) {
  const pct = total ? Math.min(100, (used / total) * 100) : 0;
  const isHigh = pct > 80;
  return (
    <div className="mb-2">
      <div className="flex justify-between text-xs text-slate-600 dark:text-slate-300">
        <span>{label}</span>
        <span>
          {used.toLocaleString()} / {total.toLocaleString()}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
        <div
          className={`h-full ${isHigh ? 'bg-rose-500' : 'bg-navy-500'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
