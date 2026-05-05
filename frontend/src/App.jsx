import React, { useState } from 'react';
import Login from './components/Login.jsx';
import Analyze from './components/Analyze.jsx';
import AuditView from './components/AuditView.jsx';

export default function App() {
  // POC: token in memory.  Production: httpOnly cookie set by gateway.
  const [session, setSession] = useState(null);
  const [view, setView] = useState('analyze');

  if (!session) {
    return <Login onLogin={setSession} />;
  }

  // Routing per role:
  //   - auditor / it_admin → can see Audit view by default
  //   - others → analyze view
  const effectiveView = view;

  if (effectiveView === 'audit') {
    return <AuditView
      session={session}
      onSwitchView={setView}
      onLogout={() => setSession(null)}
    />;
  }

  return <Analyze
    session={session}
    onSwitchView={setView}
    onLogout={() => setSession(null)}
  />;
}
