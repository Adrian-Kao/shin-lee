import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, ChevronRight } from 'lucide-react';

import { api } from '../api/client.js';

const DEMO_USERS = [
  {
    id: 'alice',
    initial: 'A',
    name: 'Alice',
    role: 'Attorney · tenant_a',
    desc: '可上傳 OA、看分析、簽核草稿',
  },
  {
    id: 'bob',
    initial: 'B',
    name: 'Bob',
    role: 'Paralegal · tenant_a',
    desc: '協助上傳；只能看 CASE-2025-001 / 002',
  },
  {
    id: 'carol',
    initial: 'C',
    name: 'Carol',
    role: 'IT Admin · tenant_b',
    desc: '看儀表板、配額；無法存取 case',
  },
  {
    id: 'audit_dave',
    initial: 'D',
    name: 'Dave',
    role: 'Auditor · tenant_a',
    desc: '唯讀 audit log；可驗 chain',
  },
];

/**
 * Official-portal login (per user direction: reference a patent-office site).
 *
 * Deliberately NOT a startup hero: solid agency header bar, white body,
 * no gradient / card shadows / marketing value bullets. Identity selection
 * is a plain bordered list. Conservative navy + amber accent palette.
 *
 * Contract preserved for e2e: a "PatentMind" brand string, one <button>
 * per identity whose accessible name contains the person's name, and the
 * error surfaced as <div role="alert">.
 */
export default function Login({ onLogin }) {
  const { t } = useTranslation();
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
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900">
      {/* Agency header bar — solid navy with an amber accent rule underneath,
          the visual signature of an official government portal. */}
      <header className="border-b-4 border-amber-400 bg-navy-900 text-white">
        <div className="mx-auto flex h-16 max-w-5xl items-center gap-3 px-6">
          <div className="flex h-9 w-9 items-center justify-center rounded bg-white/10 text-sm font-bold ring-1 ring-white/20">
            PM
          </div>
          <div className="leading-tight">
            <div className="text-base font-semibold tracking-tight">{t('app_title')}</div>
            <div className="text-[12px] text-navy-200">專利答辯協助系統</div>
          </div>
        </div>
      </header>

      <main className="flex flex-1 justify-center px-6 py-10">
        <div className="w-full max-w-2xl">
          <h1 className="text-lg font-semibold text-slate-900">{t('landing.tagline')}</h1>
          <div className="mt-4 h-px w-full bg-slate-200" />

          <h2 className="mb-1 mt-6 text-base font-semibold text-slate-900">
            {t('landing.pick_user')}
          </h2>
          <p className="mb-4 text-sm text-slate-500">{t('landing.poc_note')}</p>

          <div className="divide-y divide-slate-200 overflow-hidden rounded-md border border-slate-200 bg-white">
            {DEMO_USERS.map((u) => {
              const isBusy = busy === u.id;
              const disabled = busy !== null;
              return (
                <button
                  key={u.id}
                  type="button"
                  onClick={() => handlePick(u.id)}
                  disabled={disabled}
                  aria-busy={isBusy}
                  className={[
                    'flex w-full items-center gap-3 px-4 py-3 text-left transition-colors',
                    'focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-navy-700',
                    disabled ? 'cursor-wait opacity-60' : 'cursor-pointer hover:bg-navy-50',
                  ].join(' ')}
                >
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-navy-900 text-sm font-bold text-white">
                    {u.initial}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-slate-900">{u.name}</span>
                      <span className="truncate text-xs text-slate-500">{u.role}</span>
                    </div>
                    <div className="mt-0.5 text-xs text-slate-500">{u.desc}</div>
                  </div>
                  {isBusy ? (
                    <Loader2
                      className="h-5 w-5 shrink-0 animate-spin text-navy-700"
                      aria-hidden="true"
                    />
                  ) : (
                    <ChevronRight
                      className="h-4 w-4 shrink-0 text-slate-300"
                      aria-hidden="true"
                    />
                  )}
                </button>
              );
            })}
          </div>

          {err && (
            <div
              role="alert"
              className="mt-4 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700"
            >
              {err}
            </div>
          )}
        </div>
      </main>

      <footer className="border-t border-slate-200 bg-white py-3 text-center text-xs text-slate-400">
        {t('landing.footer')}
      </footer>
    </div>
  );
}
