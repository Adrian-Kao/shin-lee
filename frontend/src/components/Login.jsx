import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, ChevronRight, Mail, LogIn } from 'lucide-react';

import { api } from '../api/client.js';

// Role label + tenant stay as a stable technical identifier (the demo's
// identity matrix); the human-readable capability blurb is localised via
// `descKey`. Person names are kept verbatim — e2e tests match them by name.
const DEMO_USERS = [
  {
    id: 'alice',
    initial: 'A',
    name: 'Alice',
    role: 'Attorney · tenant_a',
    descKey: 'login.user_alice',
  },
  {
    id: 'bob',
    initial: 'B',
    name: 'Bob',
    role: 'Paralegal · tenant_a',
    descKey: 'login.user_bob',
  },
  {
    id: 'carol',
    initial: 'C',
    name: 'Carol',
    role: 'IT Admin · tenant_b',
    descKey: 'login.user_carol',
  },
  {
    id: 'audit_dave',
    initial: 'D',
    name: 'Dave',
    role: 'Auditor · tenant_a',
    descKey: 'login.user_dave',
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
      // HTTP errors carry a human-readable gateway `detail`; anything without
      // a status is a network failure ("Failed to fetch") — show the
      // localized message instead of the raw browser string.
      setErr(e?.status ? e.message : t('errors.network'));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900 dark:bg-slate-800/50 dark:text-slate-100">
      {/* Agency header bar — solid navy with an amber accent rule underneath,
          the visual signature of an official government portal. */}
      <header className="border-b-4 border-amber-400 bg-navy-900 text-white">
        <div className="mx-auto flex h-16 max-w-5xl items-center gap-3 px-6">
          <div className="flex h-9 w-9 items-center justify-center rounded bg-white/10 text-sm font-bold ring-1 ring-white/20">
            PM
          </div>
          <div className="leading-tight">
            <div className="text-base font-semibold tracking-tight">{t('app_title')}</div>
            <div className="text-xs text-navy-200">{t('login.subtitle')}</div>
          </div>
        </div>
      </header>

      <main className="flex flex-1 justify-center px-6 py-10">
        <div className="w-full max-w-2xl">
          <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">{t('landing.tagline')}</h1>
          <div className="mt-4 h-px w-full bg-slate-200 dark:bg-slate-700" />

          <h2 className="mb-1 mt-6 text-base font-semibold text-slate-900 dark:text-slate-100">
            {t('landing.pick_user')}
          </h2>
          <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">{t('landing.poc_note')}</p>

          <div className="divide-y divide-slate-200 overflow-hidden rounded-md border border-slate-200 bg-white dark:divide-slate-700 dark:border-slate-700 dark:bg-slate-900">
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
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-navy-500 dark:focus-visible:ring-navy-400',
                    disabled
                      ? 'cursor-wait opacity-60'
                      : 'cursor-pointer hover:bg-navy-50 dark:hover:bg-navy-900/40',
                  ].join(' ')}
                >
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-navy-900 text-sm font-bold text-white">
                    {u.initial}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-slate-900 dark:text-slate-100">{u.name}</span>
                      <span className="truncate text-xs text-slate-500 dark:text-slate-400">{u.role}</span>
                    </div>
                    <div className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{t(u.descKey)}</div>
                  </div>
                  {isBusy ? (
                    <Loader2
                      className="h-5 w-5 shrink-0 animate-spin text-navy-700 dark:text-navy-200"
                      aria-hidden="true"
                    />
                  ) : (
                    <ChevronRight
                      className="h-4 w-4 shrink-0 text-slate-300 dark:text-slate-600"
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
              className="mt-4 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300"
            >
              {err}
            </div>
          )}

          <MagicLink onLogin={onLogin} disabled={busy !== null} />
        </div>
      </main>

      <footer className="border-t border-slate-200 bg-white py-3 text-center text-xs text-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-500">
        {t('landing.footer')}
      </footer>
    </div>
  );
}

/**
 * Q12 magic-link sign-in. Secondary path: request a link for a user_id, the
 * demo returns the token directly (clearly labelled DEMO — production emails
 * it), then "sign in with this link" consumes the token and yields the SAME
 * logged-in state as password login.
 */
function MagicLink({ onLogin, disabled }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [userId, setUserId] = useState('');
  const [phase, setPhase] = useState('idle'); // idle | requesting | sent | consuming
  const [token, setToken] = useState(null);
  const [error, setError] = useState(null);

  async function requestLink(e) {
    e.preventDefault();
    if (!userId.trim()) return;
    setPhase('requesting');
    setError(null);
    setToken(null);
    try {
      const r = await api.magicRequest(userId.trim());
      // magic_token is the DEMO-ONLY escape hatch; null for unknown users
      // (the message is identical either way — enumeration-safe).
      setToken(r.magic_token || null);
      setPhase('sent');
    } catch (e2) {
      setError(e2?.status ? e2.message : t('errors.network'));
      setPhase('idle');
    }
  }

  async function consume() {
    if (!token) return;
    setPhase('consuming');
    setError(null);
    try {
      const session = await api.magicConsume(token);
      onLogin(session);
    } catch {
      setError(t('magic.consume_failed'));
      setPhase('sent');
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={disabled}
        className="mt-6 inline-flex items-center gap-2 rounded-md text-sm text-navy-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-500 focus-visible:ring-offset-2 disabled:opacity-50 dark:text-navy-200 dark:focus-visible:ring-navy-400 dark:focus-visible:ring-offset-slate-800"
      >
        <Mail className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
        {t('magic.link_cta')}
      </button>
    );
  }

  return (
    <div className="mt-6 rounded-md border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
        <Mail className="h-4 w-4 text-navy-700 dark:text-navy-200" strokeWidth={1.75} aria-hidden="true" />
        {t('magic.link_cta')}
      </div>

      <form onSubmit={requestLink} className="space-y-2">
        <label className="block text-xs text-slate-500 dark:text-slate-400">{t('magic.user_label')}</label>
        <div className="flex gap-2">
          <input
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            placeholder={t('magic.user_placeholder')}
            className="flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm transition-colors focus-visible:border-navy-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:focus-visible:border-navy-400 dark:focus-visible:ring-navy-400"
          />
          <button
            type="submit"
            disabled={!userId.trim() || phase === 'requesting' || phase === 'consuming'}
            className="rounded-md bg-navy-900 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-navy-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-500 focus-visible:ring-offset-2 disabled:bg-slate-300 dark:focus-visible:ring-navy-400 dark:focus-visible:ring-offset-slate-900 dark:disabled:bg-slate-700"
          >
            {phase === 'requesting' ? t('magic.requesting') : t('magic.request')}
          </button>
        </div>
      </form>

      {phase === 'sent' && (
        <div className="mt-3 space-y-2">
          <div className="text-xs text-slate-500 dark:text-slate-400">{t('magic.sent')}</div>
          {token && (
            <div className="rounded-md border border-amber-300 bg-amber-50 p-2 dark:border-amber-800 dark:bg-amber-950/40">
              <div className="mb-1 text-2xs font-semibold uppercase tracking-wider text-amber-700 dark:text-amber-300">
                {t('magic.demo_label')}
              </div>
              <div
                className="mb-2 break-all font-mono text-3xs text-slate-600 dark:text-slate-300"
                data-testid="magic-token"
              >
                {token}
              </div>
              <button
                type="button"
                onClick={consume}
                disabled={phase === 'consuming'}
                className="inline-flex items-center gap-1.5 rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-emerald-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2 disabled:opacity-60 dark:focus-visible:ring-emerald-400 dark:focus-visible:ring-offset-amber-950"
              >
                {phase === 'consuming' ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <LogIn className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
                )}
                {phase === 'consuming'
                  ? t('magic.consuming')
                  : t('magic.sign_in_with_link')}
              </button>
            </div>
          )}
        </div>
      )}

      {error && (
        <div role="alert" className="mt-3 text-sm text-rose-700 dark:text-rose-300">
          {error}
        </div>
      )}

      <button
        type="button"
        onClick={() => {
          setOpen(false);
          setPhase('idle');
          setToken(null);
          setError(null);
        }}
        className="mt-3 rounded text-xs text-slate-500 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-500 focus-visible:ring-offset-2 dark:text-slate-400 dark:focus-visible:ring-navy-400 dark:focus-visible:ring-offset-slate-900"
      >
        {t('magic.back')}
      </button>
    </div>
  );
}
