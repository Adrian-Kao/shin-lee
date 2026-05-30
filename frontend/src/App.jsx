import React, { useCallback, useState } from 'react';
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import Login from './components/Login.jsx';
import Analyze from './components/Analyze.jsx';
import AuditView from './components/AuditView.jsx';

/**
 * Slice B: router-based shell.
 *
 * Session lives in App state (same as the original POC — production switches
 * to httpOnly cookie set by gateway, see CLAUDE.md). Each existing view is
 * mounted under its own <Route> via a thin wrapper that adapts the old
 * `onSwitchView` setter API to react-router's `useNavigate`, so the child
 * components themselves don't need to know routing exists.
 */
export default function App() {
  const [session, setSession] = useState(null);

  const handleLogout = useCallback(() => setSession(null), []);

  if (!session) {
    // Login is the only public route. Anything else redirects here.
    return (
      <Routes>
        <Route path="/login" element={<LoginRoute onLogin={setSession} />} />
        <Route path="*" element={<LoginRoute onLogin={setSession} />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route path="/login" element={<Navigate to="/analyze" replace />} />
      <Route path="/analyze" element={<AnalyzeRoute session={session} onLogout={handleLogout} />} />
      <Route path="/audit" element={<AuditRoute session={session} onLogout={handleLogout} />} />
      <Route path="/cases" element={<CasesPlaceholder />} />
      <Route path="*" element={<Navigate to="/analyze" replace />} />
    </Routes>
  );
}

function LoginRoute({ onLogin }) {
  const navigate = useNavigate();
  // Login expects a single onLogin(session) callback; preserve that contract.
  return (
    <Login
      onLogin={(s) => {
        onLogin(s);
        navigate('/analyze', { replace: true });
      }}
    />
  );
}

/**
 * Adapter: existing Analyze/AuditView use onSwitchView('analyze' | 'audit').
 * We translate that into a navigate() call so child JSX stays untouched.
 */
function buildSwitchView(navigate) {
  return (view) => {
    if (view === 'analyze') navigate('/analyze');
    else if (view === 'audit') navigate('/audit');
    else if (view === 'cases') navigate('/cases');
    else navigate('/analyze');
  };
}

function AnalyzeRoute({ session, onLogout }) {
  const navigate = useNavigate();
  return <Analyze session={session} onLogout={onLogout} onSwitchView={buildSwitchView(navigate)} />;
}

function AuditRoute({ session, onLogout }) {
  const navigate = useNavigate();
  return (
    <AuditView session={session} onLogout={onLogout} onSwitchView={buildSwitchView(navigate)} />
  );
}

/**
 * Phase 4 will populate this with the case-management UI.
 * For slice B we only reserve the route so links don't 404.
 */
function CasesPlaceholder() {
  // Hooks are imported via the named imports above; this stays a local function.
  return <CasesPlaceholderInner />;
}

function CasesPlaceholderInner() {
  const navigate = useNavigate();
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const { t } = useTranslation();
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-6 py-12">
      <div className="w-full max-w-lg rounded-xl border border-slate-200 bg-white p-8 text-center shadow-sm md:p-12">
        <div className="mb-3 text-5xl" aria-hidden="true">
          🚧
        </div>
        <h1 className="mb-1 text-xl font-semibold text-slate-900">
          {t('placeholder.cases_title')}
        </h1>
        <p className="mb-6 text-sm text-slate-500">{t('placeholder.cases_subtitle')}</p>

        <ul className="mb-6 space-y-2 text-left text-sm text-slate-600">
          {[
            t('placeholder.cases_bullet_1'),
            t('placeholder.cases_bullet_2'),
            t('placeholder.cases_bullet_3'),
          ].map((bullet, i) => (
            <li key={i} className="flex items-start gap-2">
              <span className="mt-0.5 text-indigo-500" aria-hidden="true">
                •
              </span>
              <span>{bullet}</span>
            </li>
          ))}
        </ul>

        <button
          type="button"
          onClick={() => navigate('/analyze')}
          className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          {t('placeholder.back_to_analyze')}
        </button>
      </div>
    </div>
  );
}
