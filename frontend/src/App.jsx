import React, { useCallback, useState } from 'react';
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Folder } from 'lucide-react';

import Login from './components/Login.jsx';
import Analyze from './components/Analyze.jsx';
import AuditView from './components/AuditView.jsx';
import AppShell from './components/AppShell.jsx';
import { Button } from './components/ui/button.jsx';

/**
 * Role-aware landing route. After login each role lands on the page it can
 * actually use, instead of everyone defaulting to /analyze:
 *   • auditor   → /audit   (read-only audit log is the auditor's home)
 *   • it_admin  → /analyze (no dedicated home in the POC; /cases is a
 *                           placeholder and /audit 403s for non-tenant_a, so
 *                           the gentler default is the analyze input form)
 *   • attorney
 *   • paralegal → /analyze (the core working surface)
 */
function landingPathForRole(role) {
  switch (role) {
    case 'auditor':
      return '/audit';
    default:
      return '/analyze';
  }
}

/**
 * Slice B + Day 9C: router-based shell with persistent chrome.
 *
 * Session lives in App state (same as the original POC — production switches
 * to httpOnly cookie set by gateway, see CLAUDE.md). After CHUNK-1 every
 * authenticated route is wrapped in <AppShell>, which owns the top bar,
 * trust band (CHUNK-8), and left nav rail. Each child page receives
 * `embedded` so its in-component header is suppressed; the three-pane
 * Analyze grid + AuditView's table layout are otherwise untouched.
 *
 * `trustContext` is the upward channel from the active route to the shell's
 * trust band — Analyze pushes the current case_id + redaction count so the
 * Routing chip + Redaction chip reflect the live analysis instead of static
 * defaults.
 */
export default function App() {
  const [session, setSession] = useState(null);
  // Lifted to App so it survives route changes; routes call setTrustContext.
  const [trustContext, setTrustContext] = useState({ caseId: '', maskedEntityCount: 0 });

  const handleLogout = useCallback(() => {
    setSession(null);
    setTrustContext({ caseId: '', maskedEntityCount: 0 });
  }, []);

  if (!session) {
    // Login is the only public route. Anything else redirects here.
    return (
      <Routes>
        <Route path="/login" element={<LoginRoute onLogin={setSession} />} />
        <Route path="*" element={<LoginRoute onLogin={setSession} />} />
      </Routes>
    );
  }

  const landingPath = landingPathForRole(session.role);

  return (
    <AppShell session={session} onLogout={handleLogout} trustContext={trustContext}>
      <Routes>
        <Route path="/login" element={<Navigate to={landingPath} replace />} />
        <Route
          path="/analyze"
          element={
            <AnalyzeRoute
              session={session}
              onLogout={handleLogout}
              onTrustChange={setTrustContext}
            />
          }
        />
        <Route path="/audit" element={<AuditRoute session={session} onLogout={handleLogout} />} />
        <Route path="/cases" element={<CasesPlaceholder />} />
        <Route path="*" element={<Navigate to={landingPath} replace />} />
      </Routes>
    </AppShell>
  );
}

function LoginRoute({ onLogin }) {
  const navigate = useNavigate();
  // Login expects a single onLogin(session) callback; preserve that contract.
  // Route to the role-appropriate landing page (auditor/it_admin → /audit).
  return (
    <Login
      onLogin={(s) => {
        onLogin(s);
        navigate(landingPathForRole(s?.role), { replace: true });
      }}
    />
  );
}

/**
 * Adapter: existing Analyze/AuditView use onSwitchView('analyze' | 'audit').
 * The shell owns top-level nav now, but legacy callers inside the components
 * (e.g. result-summary deep links) still rely on the contract.
 */
function buildSwitchView(navigate) {
  return (view) => {
    if (view === 'analyze') navigate('/analyze');
    else if (view === 'audit') navigate('/audit');
    else if (view === 'cases') navigate('/cases');
    else navigate('/analyze');
  };
}

function AnalyzeRoute({ session, onLogout, onTrustChange }) {
  const navigate = useNavigate();
  return (
    <Analyze
      session={session}
      onLogout={onLogout}
      onSwitchView={buildSwitchView(navigate)}
      embedded
      onTrustChange={onTrustChange}
    />
  );
}

function AuditRoute({ session, onLogout }) {
  const navigate = useNavigate();
  return (
    <AuditView
      session={session}
      onLogout={onLogout}
      onSwitchView={buildSwitchView(navigate)}
      embedded
    />
  );
}

/**
 * Phase 4 will populate this with the case-management UI.
 * For slice B we only reserve the route so links don't 404.
 */
function CasesPlaceholder() {
  return <CasesPlaceholderInner />;
}

function CasesPlaceholderInner() {
  const navigate = useNavigate();
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const { t } = useTranslation();
  return (
    <div className="flex min-h-[60vh] items-center justify-center px-6 py-12">
      <div className="w-full max-w-lg rounded-xl border border-slate-200 bg-white p-8 text-center shadow-sm dark:border-slate-700 dark:bg-slate-900 md:p-12">
        <Folder
          className="mx-auto mb-3 h-12 w-12 text-navy-700 dark:text-navy-200"
          strokeWidth={1.5}
          aria-hidden="true"
        />
        <h1 className="mb-1 text-xl font-semibold text-slate-900 dark:text-slate-100">
          {t('placeholder.cases_title')}
        </h1>
        <p className="mb-6 text-sm text-slate-500 dark:text-slate-400">
          {t('placeholder.cases_subtitle')}
        </p>

        <ul className="mb-6 space-y-2 text-left text-sm text-slate-600 dark:text-slate-300">
          {[
            t('placeholder.cases_bullet_1'),
            t('placeholder.cases_bullet_2'),
            t('placeholder.cases_bullet_3'),
          ].map((bullet, i) => (
            <li key={i} className="flex items-start gap-2">
              <span className="mt-0.5 text-navy-700 dark:text-navy-200" aria-hidden="true">
                •
              </span>
              <span>{bullet}</span>
            </li>
          ))}
        </ul>

        <Button type="button" variant="primary" onClick={() => navigate('/analyze')}>
          {t('placeholder.back_to_analyze')}
        </Button>
      </div>
    </div>
  );
}
