import React, { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { LogOut, RefreshCw, ScrollText, ShieldCheck, ShieldAlert, Loader2, Check, X } from 'lucide-react';
import { useAuditRecent, useAuditVerify } from '../api/queries.js';
import { Button } from './ui/button.jsx';
import { Badge } from './ui/badge.jsx';
import ErrorBanner from './ErrorBanner.jsx';
import EmptyState from './EmptyState.jsx';
import { SkeletonCard } from './Skeleton.jsx';

/**
 * Q13: append-only audit log + tamper-evident hash chain.
 *
 * The auditor (Dave) sees every API call against tenant_a, with:
 *   - mask rules triggered (proves Q10 redaction happened before going to LLM)
 *   - policy decisions (proves Q12/Q18 gates fired)
 *   - hash-chain verify button (proves no tampering since insert)
 *
 * Day 9C — embedded mode + CHUNK-8 hero metric block. When mounted inside
 * the AppShell (the default for authenticated routes after CHUNK-1) the
 * in-component <Header> is suppressed; the hero block above the audit table
 * surfaces the three numbers BigLaw procurement asks about first
 * (PRODUCT_STRATEGY §0 bullet 3): row count, mismatch count, last verified.
 */
export default function AuditView({ session, onSwitchView, onLogout, embedded = false }) {
  const { t } = useTranslation();

  // Auditor → global scope (cross-tenant chain); it_admin stays per-tenant
  // because their role description is per-tenant connectors / dashboards,
  // not cross-tenant compliance (matches audit_verify gate in main.py).
  const scope = session?.role === 'auditor' ? 'global' : 'tenant';

  // Server state via TanStack Query (P1③). Both queries fire on mount; the
  // verify query SHARES its key with AppShell's chain chip (['audit','verify',
  // scope]) so the two no longer issue duplicate verify requests.
  const recentQ = useAuditRecent(session.token);
  const verifyQ = useAuditVerify(session.token, scope, { poll: false });
  const [dismissed, setDismissed] = useState(false);

  const rows = recentQ.data ?? [];
  const loading = recentQ.isPending;
  const verify = verifyQ.data ?? null;
  const verifying = verifyQ.isFetching;
  const lastVerifiedAt = verifyQ.dataUpdatedAt ? new Date(verifyQ.dataUpdatedAt) : null;
  const error = dismissed ? null : recentQ.error || verifyQ.error || null;

  function refresh() {
    setDismissed(false);
    recentQ.refetch();
  }
  function runVerify() {
    setDismissed(false);
    verifyQ.refetch();
  }

  // Hero metrics derived from the latest verify response.
  const heroMetrics = useMemo(() => {
    const verified = verify?.verified ?? 0;
    const broken = Array.isArray(verify?.broken) ? verify.broken.length : 0;
    return {
      totalRows: verified + broken,
      mismatches: broken,
      lastVerified: lastVerifiedAt,
      allPass: broken === 0,
    };
  }, [verify, lastVerifiedAt]);

  return (
    <div className={`flex flex-col ${embedded ? 'min-h-0 flex-1' : 'min-h-screen'}`}>
      {!embedded && <LegacyHeader session={session} onSwitchView={onSwitchView} onLogout={onLogout} t={t} />}

      <div className="mx-auto w-full max-w-7xl flex-1 space-y-4 px-4 py-6 sm:px-6">
        {/* CHUNK-8 hero metric block — three big numbers in JetBrains Mono. */}
        <HeroMetrics metrics={heroMetrics} verifying={verifying} onVerify={runVerify} t={t} />

        <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-4 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="flex items-center gap-2 font-semibold text-slate-900 dark:text-slate-100">
                <ScrollText className="h-4 w-4 text-navy-700" strokeWidth={1.75} aria-hidden="true" />
                <span>Audit Log</span>
                <span className="text-xs font-normal text-slate-500 dark:text-slate-400">(Q13)</span>
              </h2>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                Append-only SQLite + UPDATE/DELETE trigger 阻擋。 Production 加 S3 Object Lock 每小時封存。
              </p>
            </div>
            <Button
              variant="outline"
              size="xs"
              onClick={refresh}
              className="gap-1.5"
            >
              <RefreshCw className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
              重新整理
            </Button>
          </div>

          {verify && (
            <div
              className={`mt-3 flex items-start gap-2 rounded-md p-2 text-sm ${
                heroMetrics.allPass
                  ? 'border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300'
                  : 'border border-rose-200 dark:border-rose-800 bg-rose-50 dark:bg-rose-950/40 text-rose-800 dark:text-rose-300'
              }`}
            >
              {heroMetrics.allPass ? (
                <ShieldCheck className="mt-0.5 h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
              ) : (
                <ShieldAlert className="mt-0.5 h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
              )}
              <span>
                {heroMetrics.allPass
                  ? t('audit.verify_passed', { rows: heroMetrics.totalRows })
                  : t('audit.verify_failed', {
                      count: heroMetrics.mismatches,
                      rows: brokenRowsLabel(verify.broken),
                    })}
              </span>
            </div>
          )}
          {error && (
            <div className="mt-3">
              <ErrorBanner
                error={error}
                onRetry={refresh}
                onDismiss={() => setDismissed(true)}
                onLogin={onLogout}
              />
            </div>
          )}
        </div>

        {loading && <SkeletonCard />}

        {!loading && rows.length === 0 && !error && (
          <EmptyState
            icon={
              <ScrollText
                className="mx-auto h-10 w-10 text-slate-400"
                strokeWidth={1.5}
                aria-hidden="true"
              />
            }
            title={t('empty.no_audit_title')}
            description={t('empty.no_audit_desc')}
          />
        )}

        {!loading && rows.length > 0 && (
          <div className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-sm">
            <div className="overflow-x-auto">
              <table className="min-w-full text-xs">
                <thead className="bg-slate-100 dark:bg-slate-800 uppercase tracking-wider text-slate-600 dark:text-slate-300">
                  <tr>
                    <th className="px-3 py-2 text-left">時間 (UTC)</th>
                    <th className="px-3 py-2 text-left">User</th>
                    <th className="px-3 py-2 text-left">Case</th>
                    <th className="px-3 py-2 text-left">Endpoint</th>
                    <th className="px-3 py-2 text-left">Model</th>
                    <th className="px-3 py-2 text-right">Tokens</th>
                    <th className="px-3 py-2 text-right">ms</th>
                    <th className="px-3 py-2 text-left">Mask 規則 (Q10)</th>
                    <th className="px-3 py-2 text-left">Policy (Q12/18)</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.audit_id} className="border-t border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800/50">
                      <td className="px-3 py-2 font-mono text-slate-500 dark:text-slate-400">
                        {r.timestamp_utc.slice(0, 19)}
                      </td>
                      <td className="px-3 py-2">{r.user_id}</td>
                      <td className="px-3 py-2 font-mono">{r.case_id || '—'}</td>
                      <td className="px-3 py-2 font-mono">{r.endpoint}</td>
                      <td className="px-3 py-2 font-mono">{r.model_used || '—'}</td>
                      <td className="px-3 py-2 text-right font-mono">
                        {(r.prompt_tokens || 0) + (r.completion_tokens || 0)}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">{r.latency_ms}</td>
                      <td className="px-3 py-2">
                        {(r.masked_field_rules || []).length === 0 ? (
                          <span className="text-slate-400 dark:text-slate-500">—</span>
                        ) : (
                          <div className="flex flex-wrap gap-1">
                            {r.masked_field_rules.map((m, i) => (
                              <Badge
                                key={i}
                                tone="warning"
                                className="px-1.5 py-0.5 font-mono text-3xs"
                              >
                                {m}
                              </Badge>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(r.policy_decisions || {}).map(([k, v]) => (
                            <span
                              key={k}
                              className={`rounded px-1.5 py-0.5 font-mono text-3xs ${
                                k === 'cache_hit' || k === 'circuit_open'
                                  ? v
                                    ? 'bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300'
                                    : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300'
                                  : v
                                    ? 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-800 dark:text-emerald-300'
                                    : 'bg-rose-100 dark:bg-rose-900/40 text-rose-800 dark:text-rose-300'
                              }`}
                            >
                              <span className="inline-flex items-center gap-0.5">
                                {k}=
                                {v ? (
                                  <Check className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
                                ) : (
                                  <X className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
                                )}
                              </span>
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  CHUNK-8 hero metric block                                                 */
/* -------------------------------------------------------------------------- */

function HeroMetrics({ metrics, verifying, onVerify, t }) {
  const numberFmt = (n) => (n ?? 0).toLocaleString();
  const lastVerifiedStr = metrics.lastVerified
    ? metrics.lastVerified.toISOString().replace('T', ' ').slice(0, 19) + ' UTC'
    : t('audit.hero.never_verified');

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-5 shadow-sm">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="grid flex-1 grid-cols-1 gap-6 sm:grid-cols-3">
          <HeroStat
            label={t('audit.hero.rows_label')}
            value={numberFmt(metrics.totalRows)}
            tone={metrics.allPass ? 'emerald' : 'rose'}
          />
          <HeroStat
            label={t('audit.hero.mismatches_label')}
            value={numberFmt(metrics.mismatches)}
            tone={metrics.allPass ? 'emerald' : 'rose'}
          />
          <HeroStat
            label={t('audit.hero.last_verified_label')}
            value={lastVerifiedStr}
            tone="slate"
            small
          />
        </div>
        <Button
          type="button"
          variant="primary"
          onClick={onVerify}
          disabled={verifying}
          data-testid="audit-verify-now"
          className="gap-2 disabled:cursor-wait disabled:opacity-70"
        >
          {verifying ? (
            <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.75} aria-hidden="true" />
          ) : (
            <ShieldCheck className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
          )}
          {verifying ? t('audit.verifying') : t('audit.verify_now')}
        </Button>
      </div>
    </div>
  );
}

function HeroStat({ label, value, tone, small }) {
  const toneClasses = {
    emerald: 'text-emerald-700 dark:text-emerald-300',
    rose: 'text-rose-700 dark:text-rose-300',
    slate: 'text-slate-700 dark:text-slate-200',
  };
  return (
    <div>
      <div className="text-2xs font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">{label}</div>
      <div
        className={`mt-1 font-mono font-semibold ${toneClasses[tone] || toneClasses.slate} ${
          small ? 'text-sm sm:text-base' : 'text-2xl sm:text-3xl'
        }`}
      >
        {value}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Legacy standalone header (only when `embedded=false`)                     */
/* -------------------------------------------------------------------------- */

function LegacyHeader({ session, onSwitchView, onLogout, t }) {
  return (
    <header className="border-b dark:border-slate-700 bg-white dark:bg-slate-900">
      <div className="mx-auto flex max-w-7xl items-center gap-4 px-6 py-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded bg-navy-900 text-sm font-bold text-white">
            PM
          </div>
          <span className="font-semibold">PatentMind AI</span>
        </div>
        <nav className="ml-6 flex gap-1">
          <button onClick={() => onSwitchView('analyze')} className="rounded px-3 py-1.5 text-sm hover:bg-slate-100 dark:hover:bg-slate-800">
            分析
          </button>
          <button onClick={() => onSwitchView('audit')} className="rounded bg-navy-50 dark:bg-navy-900/40 px-3 py-1.5 text-sm font-medium text-navy-700 dark:text-navy-200">
            Audit
          </button>
        </nav>
        <div className="ml-auto flex items-center gap-3 text-sm">
          <div className="text-right">
            <div className="font-medium">{session.display_name}</div>
            <div className="text-xs text-slate-500 dark:text-slate-400">
              {session.tenant_id} · {session.role}
            </div>
          </div>
          <button onClick={onLogout} className="inline-flex items-center gap-1 rounded bg-slate-200 dark:bg-slate-700 px-2 py-1 text-xs">
            <LogOut className="h-3 w-3" strokeWidth={1.75} aria-hidden="true" />
            {t('buttons.logout')}
          </button>
        </div>
      </div>
    </header>
  );
}

function brokenRowsLabel(broken) {
  if (!Array.isArray(broken)) return '';
  // verify_global_chain → list[tuple[tenant_id, audit_id]]; per-tenant → list[str]
  return broken
    .slice(0, 5)
    .map((b) => (Array.isArray(b) ? b[1] : b))
    .join(', ');
}
