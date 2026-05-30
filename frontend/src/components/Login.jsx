import React, { useState } from 'react';
import { api } from '../api/client.js';

const DEMO_USERS = [
  { id: 'alice', label: 'Alice (Attorney, tenant_a)', desc: '可上傳 OA、看分析、簽核草稿' },
  { id: 'bob', label: 'Bob (Paralegal, tenant_a)', desc: '協助上傳；只能看 CASE-2025-001 / 002' },
  { id: 'carol', label: 'Carol (IT Admin, tenant_b)', desc: '看儀表板、配額；無法存取 case' },
  { id: 'audit_dave', label: 'Dave (Auditor, tenant_a)', desc: '唯讀 audit log；可驗 chain' },
];

export default function Login({ onLogin }) {
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);

  async function handlePick(uid) {
    setBusy(uid);
    setErr(null);
    try {
      const r = await api.login(uid);
      onLogin(r);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="w-full max-w-2xl rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="mb-2 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-600 font-bold text-white">
            PM
          </div>
          <h1 className="text-2xl font-semibold">PatentMind AI</h1>
          <span className="rounded bg-amber-100 px-2 py-0.5 text-xs uppercase tracking-wider text-amber-800">
            POC
          </span>
        </div>
        <p className="mb-6 text-sm text-slate-600">
          挑一位 demo 使用者登入。POC 直接發 JWT；正式版（Q12）改接 OIDC / SAML / magic link
          三選一。
        </p>

        <div className="grid grid-cols-1 gap-3">
          {DEMO_USERS.map((u) => (
            <button
              key={u.id}
              onClick={() => handlePick(u.id)}
              disabled={busy !== null}
              className="rounded-lg border border-slate-200 p-4 text-left transition hover:border-indigo-400 hover:bg-indigo-50 disabled:opacity-50"
            >
              <div className="flex items-start justify-between">
                <div>
                  <div className="font-semibold">{u.label}</div>
                  <div className="mt-1 text-xs text-slate-500">{u.desc}</div>
                </div>
                {busy === u.id && <span className="text-xs text-indigo-600">登入中…</span>}
              </div>
            </button>
          ))}
        </div>

        {err && (
          <div className="mt-4 rounded border border-rose-200 bg-rose-50 p-3 text-sm text-rose-600">
            {err}
          </div>
        )}

        <div className="mt-8 border-t pt-4 text-xs text-slate-500">
          架構決策見 <code>docs/DECISIONS.md</code>。20 題 reasoning 見{' '}
          <code>docs/QUESTIONS.md</code>。
        </div>
      </div>
    </div>
  );
}
