import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FileSearch, Quote, Calendar, ShieldCheck, Loader2 } from 'lucide-react';

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

const VALUE_BULLETS = [
  { Icon: FileSearch, key: 'landing.value_classify' },
  { Icon: Quote, key: 'landing.value_grounded' },
  { Icon: Calendar, key: 'landing.value_deadline' },
  { Icon: ShieldCheck, key: 'landing.value_compliance' },
];

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
    <div className="grid min-h-screen grid-cols-1 lg:grid-cols-2">
      {/* Hero / brand */}
      <section className="relative flex flex-col justify-center bg-gradient-to-br from-indigo-700 via-indigo-800 to-slate-900 px-8 py-12 text-white lg:px-16">
        <div className="max-w-xl">
          <div className="mb-8 flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-white/10 text-lg font-bold text-white ring-1 ring-white/20 backdrop-blur">
              PM
            </div>
            <h1 className="text-2xl font-semibold tracking-tight">{t('app_title')}</h1>
            <span className="rounded bg-amber-400 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-amber-900">
              POC
            </span>
          </div>

          <h2 className="mb-8 text-2xl font-semibold leading-snug text-indigo-50 lg:text-3xl">
            {t('landing.tagline')}
          </h2>

          <ul className="hidden space-y-4 lg:block">
            {VALUE_BULLETS.map(({ Icon, key }) => (
              <li key={key} className="flex items-start gap-3 text-indigo-100">
                <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/10 ring-1 ring-white/15">
                  <Icon className="h-5 w-5" aria-hidden="true" />
                </span>
                <span className="text-[15px] leading-6">{t(key)}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="absolute bottom-6 left-8 text-xs text-indigo-200/70 lg:left-16">
          {t('landing.footer')}
        </div>
      </section>

      {/* Login card */}
      <section className="flex items-center justify-center bg-white px-6 py-12">
        <div className="w-full max-w-md">
          <h2 className="mb-1 text-xl font-semibold text-slate-900">{t('landing.pick_user')}</h2>
          <p className="mb-6 text-sm text-slate-500">{t('landing.poc_note')}</p>

          <div className="grid grid-cols-1 gap-3">
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
                    'group rounded-lg border border-slate-200 p-4 text-left',
                    'transition-all duration-150 ease-out',
                    'hover:scale-[1.02] hover:border-indigo-400 hover:shadow-md',
                    'focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2',
                    disabled
                      ? 'cursor-wait opacity-60 hover:scale-100 hover:shadow-none'
                      : 'cursor-pointer',
                  ].join(' ')}
                >
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-indigo-600 font-bold text-white">
                      {u.initial}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-slate-900">{u.name}</span>
                        <span className="truncate text-xs text-slate-500">{u.role}</span>
                      </div>
                      <div className="mt-0.5 text-xs text-slate-500">{u.desc}</div>
                    </div>
                    {isBusy && (
                      <Loader2
                        className="h-5 w-5 shrink-0 animate-spin text-indigo-600"
                        aria-hidden="true"
                      />
                    )}
                  </div>
                </button>
              );
            })}
          </div>

          {err && (
            <div
              role="alert"
              className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700"
            >
              {err}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
