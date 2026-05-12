import React, { useEffect, useState } from 'react';
import { api } from '../api/client.js';

/**
 * Q13: append-only audit log + tamper-evident hash chain.
 *
 * The auditor (Dave) sees every API call against tenant_a, with:
 *   - mask rules triggered (proves Q10 redaction happened before going to LLM)
 *   - policy decisions (proves Q12/Q18 gates fired)
 *   - hash-chain verify button (proves no tampering since insert)
 */
export default function AuditView({ session, onSwitchView, onLogout }) {
  const [rows, setRows] = useState([]);
  const [verify, setVerify] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    try {
      const r = await api.auditRecent(session.token);
      setRows(r);
    } catch (e) {
      setError(`${e.status} ${e.message}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); }, []);

  async function runVerify() {
    try {
      const r = await api.auditVerify(session.token);
      setVerify(r);
    } catch (e) {
      setError(`${e.status} ${e.message}`);
    }
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-white border-b">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center gap-4">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded bg-indigo-600 flex items-center justify-center text-white font-bold text-sm">PM</div>
            <span className="font-semibold">PatentMind AI</span>
            <span className="text-xs uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">POC</span>
          </div>
          <nav className="ml-6 flex gap-1">
            <button onClick={() => onSwitchView('analyze')} className="px-3 py-1.5 rounded text-sm hover:bg-slate-100">分析</button>
            <button onClick={() => onSwitchView('audit')} className="px-3 py-1.5 rounded text-sm bg-indigo-50 text-indigo-700 font-medium">Audit</button>
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <div className="text-right">
              <div className="font-medium">{session.display_name}</div>
              <div className="text-xs text-slate-500">{session.tenant_id} · {session.role}</div>
            </div>
            <button onClick={onLogout} className="text-xs px-2 py-1 bg-slate-200 rounded">登出</button>
          </div>
        </div>
      </header>

      <main className="flex-1 max-w-7xl w-full mx-auto px-6 py-6 space-y-4">
        <div className="bg-white border rounded-lg p-4">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <h2 className="font-semibold">Audit Log <span className="text-xs font-normal text-slate-500">(Q13)</span></h2>
              <p className="text-xs text-slate-500">Append-only SQLite + UPDATE/DELETE trigger 阻擋。 Production 加 S3 Object Lock 每小時封存。</p>
            </div>
            <div className="flex gap-2">
              <button onClick={refresh} className="text-sm px-3 py-1.5 bg-slate-200 rounded hover:bg-slate-300">重新整理</button>
              <button onClick={runVerify} className="text-sm px-3 py-1.5 bg-indigo-600 text-white rounded hover:bg-indigo-700">
                驗證 hash chain
              </button>
            </div>
          </div>

          {verify && (
            <div className={`mt-3 text-sm rounded p-2 ${
              verify.broken.length === 0 ? 'bg-emerald-50 border border-emerald-200 text-emerald-800'
                                          : 'bg-rose-50 border border-rose-200 text-rose-800'
            }`}>
              {verify.broken.length === 0
                ? `✓ ${verify.verified} 列全部通過 hash 驗證，無 tampering 痕跡。`
                : `✗ 發現 ${verify.broken.length} 列被竄改（${verify.broken.join(', ')}）`}
            </div>
          )}
          {error && <div className="mt-3 text-sm bg-rose-50 border border-rose-200 text-rose-800 rounded p-2">{error}</div>}
        </div>

        <div className="bg-white border rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead className="bg-slate-100 text-slate-600 uppercase tracking-wider">
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
                {loading && <tr><td colSpan={9} className="px-3 py-6 text-center text-slate-500">載入中…</td></tr>}
                {!loading && rows.length === 0 && (
                  <tr><td colSpan={9} className="px-3 py-6 text-center text-slate-500">沒有資料 — 先去「分析」頁跑一次 OA 分析。</td></tr>
                )}
                {rows.map((r) => (
                  <tr key={r.audit_id} className="border-t hover:bg-slate-50">
                    <td className="px-3 py-2 font-mono text-slate-500">{r.timestamp_utc.slice(0, 19)}</td>
                    <td className="px-3 py-2">{r.user_id}</td>
                    <td className="px-3 py-2 font-mono">{r.case_id || '—'}</td>
                    <td className="px-3 py-2 font-mono">{r.endpoint}</td>
                    <td className="px-3 py-2 font-mono">{r.model_used || '—'}</td>
                    <td className="px-3 py-2 text-right font-mono">{(r.prompt_tokens || 0) + (r.completion_tokens || 0)}</td>
                    <td className="px-3 py-2 text-right font-mono">{r.latency_ms}</td>
                    <td className="px-3 py-2">
                      {(r.masked_field_rules || []).length === 0 ? (
                        <span className="text-slate-400">—</span>
                      ) : (
                        <div className="flex flex-wrap gap-1">
                          {r.masked_field_rules.map((m, i) =>
                            <span key={i} className="px-1.5 py-0.5 bg-amber-100 rounded font-mono text-[10px]">{m}</span>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1">
                        {Object.entries(r.policy_decisions || {}).map(([k, v]) => (
                          <span key={k} className={`px-1.5 py-0.5 rounded font-mono text-[10px] ${
                            (k === 'cache_hit' || k === 'circuit_open')
                              ? (v ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-600')
                              : (v ? 'bg-emerald-100 text-emerald-800' : 'bg-rose-100 text-rose-800')
                          }`}>
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
      </main>
    </div>
  );
}
