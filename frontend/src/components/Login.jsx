import React, { useState } from 'react';
import { api } from '../api/client.js';

const DEMO_USERS = [
  { id: 'alice',      label: 'Alice (Attorney, tenant_a)',     desc: '可上傳 OA、看分析、簽核草稿' },
  { id: 'bob',        label: 'Bob (Paralegal, tenant_a)',     desc: '協助上傳；只能看 CASE-2025-001 / 002' },
  { id: 'carol',      label: 'Carol (IT Admin, tenant_b)',    desc: '看儀表板、配額；無法存取 case' },
  { id: 'audit_dave', label: 'Dave (Auditor, tenant_a)',      desc: '唯讀 audit log；可驗 chain' },
];

export default function Login({ onLogin }) {
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);

  async function handlePick(uid) {
    setBusy(uid); setErr(null);
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
    <div className="min-h-screen flex items-center justify-center px-6">
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-8 max-w-2xl w-full">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-lg bg-indigo-600 flex items-center justify-center text-white font-bold">PM</div>
          <h1 className="text-2xl font-semibold">PatentMind AI</h1>
          <span className="text-xs uppercase tracking-wider px-2 py-0.5 rounded bg-amber-100 text-amber-800">POC</span>
        </div>
        <p className="text-slate-600 mb-6 text-sm">
          挑一位 demo 使用者登入。POC 直接發 JWT；正式版（Q12）改接 OIDC / SAML / magic link 三選一。
        </p>

        <div className="grid grid-cols-1 gap-3">
          {DEMO_USERS.map((u) => (
            <button
              key={u.id}
              onClick={() => handlePick(u.id)}
              disabled={busy !== null}
              className="text-left border border-slate-200 hover:border-indigo-400 hover:bg-indigo-50 transition rounded-lg p-4 disabled:opacity-50"
            >
              <div className="flex justify-between items-start">
                <div>
                  <div className="font-semibold">{u.label}</div>
                  <div className="text-xs text-slate-500 mt-1">{u.desc}</div>
                </div>
                {busy === u.id && <span className="text-xs text-indigo-600">登入中…</span>}
              </div>
            </button>
          ))}
        </div>

        {err && <div className="mt-4 text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded p-3">{err}</div>}

        <div className="mt-8 text-xs text-slate-500 border-t pt-4">
          架構決策見 <code>docs/DECISIONS.md</code>。20 題 reasoning 見 <code>docs/QUESTIONS.md</code>。
        </div>
      </div>
    </div>
  );
}
