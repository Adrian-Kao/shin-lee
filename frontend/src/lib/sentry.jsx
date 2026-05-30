// Sentry browser init. Env-gated via VITE_SENTRY_DSN — when unset, no-op
// (zero runtime cost beyond the bundled SDK, which is ~50 KB gzipped).
//
// Call initSentry() once at the top of main.jsx before createRoot().
// Wrap <App /> in <SentryErrorBoundary> for surface-level UI crashes.

import * as Sentry from '@sentry/react';

let _enabled = false;

export function initSentry() {
  const dsn = import.meta.env.VITE_SENTRY_DSN;
  if (!dsn) return false;

  Sentry.init({
    dsn,
    environment: import.meta.env.VITE_SENTRY_ENVIRONMENT || import.meta.env.MODE || 'dev',
    release: import.meta.env.VITE_SENTRY_RELEASE || undefined,
    integrations: [Sentry.browserTracingIntegration()],
    tracesSampleRate: Number(import.meta.env.VITE_SENTRY_TRACES_SAMPLE_RATE ?? 0.1),
    // Don't send PII by default — OA text might be confidential.
    sendDefaultPii: false,
  });

  _enabled = true;
  return true;
}

export function sentryEnabled() {
  return _enabled;
}

// Re-export ErrorBoundary so callers don't import from @sentry/react directly.
// Falls back to a pass-through fragment when Sentry is not initialised.
export function SentryErrorBoundary({ children, fallback }) {
  if (!_enabled) return children;
  return <Sentry.ErrorBoundary fallback={fallback}>{children}</Sentry.ErrorBoundary>;
}
