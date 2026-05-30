import React, { useCallback, useState } from 'react';
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom';

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
  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="max-w-md rounded-xl border border-slate-200 bg-white p-8 text-center shadow-sm">
        <div className="mb-3 text-4xl">🗂️</div>
        <h1 className="mb-1 text-lg font-semibold">Cases</h1>
        <p className="text-sm text-slate-500">Coming soon (Phase 4).</p>
      </div>
    </div>
  );
}
