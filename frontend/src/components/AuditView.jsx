import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client.js';
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
 */
export default function AuditView({ session, onSwitchView, onLogout }) {
  const { t } = useTranslation();
  const [rows, setRows] = useState([]);
  const [verify, setVerify] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const r = await api.auditRecent(session.token);
      setRows(r);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function runVerify() {
    try {
      const r = await api.auditVerify(session.token);
      setVerify(r);
    } catch (e) {
      setError(e);
    }
  }

  return (
    <div className="flex min-h-screen flex-col">
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
              className="rounded px-3 py-1.5 text-sm hover:bg-slate-100"
            >
              分析
            </button>
            <button
              onClick={() => onSwitchView('audit')}
              className="rounded bg-indigo-50 px-3 py-1.5 text-sm font-medium text-indigo-700"
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

      <main className="mx-auto w-full max-w-7xl flex-1 space-y-4 px-6 py-6">
        <div className="rounded-lg border bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="font-semibold">
                Audit Log <span className="text-xs font-normal text-slate-500">(Q13)</span>
              </h2>
              <p className="text-xs text-slate-500">
                Append-only SQLite + UPDATE/DELETE trigger 阻擋。 Production 加 S3 Object Lock
                每小時封存。
              </p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={refresh}
                className="rounded bg-slate-200 px-3 py-1.5 text-sm hover:bg-slate-300"
              >
                重新整理
              </button>
              <button
                onClick={runVerify}
                className="rounded bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-700"
              >
                驗證 hash chain
              </button>
            </div>
          </div>

          {verify && (
            <div
              className={`mt-3 rounded p-2 text-sm ${
                verify.broken.length === 0
                  ? 'border border-emerald-200 bg-emerald-50 text-emerald-800'
                  : 'border border-rose-200 bg-rose-50 text-rose-800'
              }`}
            >
              {verify.broken.length === 0
                ? `✓ ${verify.verified} 列全部通過 hash 驗證，無 tampering 痕跡。`
                : `✗ 發現 ${verify.broken.length} 列被竄改（${verify.broken.join(', ')}）`}
            </div>
          )}
          {error && (
            <div className="mt-3">
              <ErrorBanner
                error={error}
                onRetry={refresh}
                onDismiss={() => setError(null)}
                onLogin={onLogout}
              />
            </div>
          )}
        </div>

        {loading && <SkeletonCard />}

        {!loading && rows.length === 0 && !error && (
          <EmptyState
            icon="📋"
            title={t('empty.no_audit_title')}
            description={t('empty.no_audit_desc')}
          />
        )}

        {!loading && rows.length > 0 && (
          <div className="overflow-hidden rounded-lg border bg-white">
            <div className="overflow-x-auto">
              <table className="min-w-full text-xs">
                <thead className="bg-slate-100 uppercase tracking-wider text-slate-600">
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
                    <tr key={r.audit_id} className="border-t hover:bg-slate-50">
                      <td className="px-3 py-2 font-mono text-slate-500">
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
                          <span className="text-slate-400">—</span>
                        ) : (
                          <div className="flex flex-wrap gap-1">
                            {r.masked_field_rules.map((m, i) => (
                              <span
                                key={i}
                                className="rounded bg-amber-100 px-1.5 py-0.5 font-mono text-[10px]"
                              >
                                {m}
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(r.policy_decisions || {}).map(([k, v]) => (
                            <span
                              key={k}
                              className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${
                                k === 'cache_hit' || k === 'circuit_open'
                                  ? v
                                    ? 'bg-amber-100 text-amber-800'
                                    : 'bg-slate-100 text-slate-600'
                                  : v
                                    ? 'bg-emerald-100 text-emerald-800'
                                    : 'bg-rose-100 text-rose-800'
                              }`}
                            >
                              {k}={v ? '✓' : '✗'}
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
      </main>
    </div>
  );
}
