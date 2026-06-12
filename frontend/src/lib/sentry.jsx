// Sentry browser init — fully env-gated via VITE_SENTRY_DSN.
//
// To keep @sentry/react (~50 KB gzipped) OUT of the main bundle when no DSN is
// configured, the SDK is loaded with a dynamic import() that only runs inside
// initSentry() when a DSN is present. Vite emits @sentry as its own async chunk
// (see manualChunks in vite.config.js) which is never fetched in DSN-less
// builds. There is therefore no static `import * as Sentry` at module top.
//
// Call initSentry() once near the top of main.jsx (before/around createRoot).
// Wrap the tree in <SentryErrorBoundary> for surface-level UI crash capture;
// until the SDK resolves (or when no DSN is set) it is a transparent passthrough.

/* eslint-disable react-refresh/only-export-components */
import { Component, useEffect, useState } from 'react';

let _enabled = false;
let _Boundary = null; // resolved Sentry.ErrorBoundary component

// Subscribers re-render when the boundary becomes available so an already
// mounted <SentryErrorBoundary> upgrades from passthrough to real boundary.
const _subs = new Set();
function _notify() {
  for (const fn of _subs) fn();
}

/**
 * Initialise Sentry if a DSN is configured. Returns a Promise<boolean>
 * (true when Sentry was initialised). Safe to call once; subsequent calls
 * resolve immediately. Callers need not await — fire-and-forget is fine.
 */
export async function initSentry() {
  const dsn = import.meta.env.VITE_SENTRY_DSN;
  if (!dsn || _enabled) return _enabled;

  try {
    const Sentry = await import('@sentry/react');
    Sentry.init({
      dsn,
      environment: import.meta.env.VITE_SENTRY_ENVIRONMENT || import.meta.env.MODE || 'dev',
      release: import.meta.env.VITE_SENTRY_RELEASE || undefined,
      integrations: [Sentry.browserTracingIntegration()],
      tracesSampleRate: Number(import.meta.env.VITE_SENTRY_TRACES_SAMPLE_RATE ?? 0.1),
      // Don't send PII by default — OA text might be confidential.
      sendDefaultPii: false,
    });
    _Boundary = Sentry.ErrorBoundary;
    _enabled = true;
    _notify();
    return true;
  } catch {
    // SDK failed to load — stay in passthrough mode rather than crash boot.
    return false;
  }
}

export function sentryEnabled() {
  return _enabled;
}

// Plain React boundary used whenever the Sentry SDK is absent (no DSN, or the
// dynamic import failed). Before this existed, DSN-less builds had NO error
// boundary at all — any render error white-screened the whole SPA. Same
// `fallback` contract as Sentry.ErrorBoundary (element, or function receiving
// { error, resetError }).
class LocalErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error('UI crash caught by LocalErrorBoundary:', error, info?.componentStack);
  }

  render() {
    const { error } = this.state;
    if (error === null) return this.props.children;
    const { fallback } = this.props;
    if (typeof fallback === 'function') {
      return fallback({ error, resetError: () => this.setState({ error: null }) });
    }
    return fallback ?? null;
  }
}

// ErrorBoundary wrapper so callers don't import @sentry/react directly.
// Starts as a plain local boundary; upgrades to the real Sentry.ErrorBoundary
// (with event capture) once the SDK has loaded.
export function SentryErrorBoundary({ children, fallback }) {
  const [, force] = useState(0);
  useEffect(() => {
    if (_enabled && _Boundary) return undefined;
    const fn = () => force((n) => n + 1);
    _subs.add(fn);
    return () => _subs.delete(fn);
  }, []);

  if (_enabled && _Boundary) {
    const Boundary = _Boundary;
    return <Boundary fallback={fallback}>{children}</Boundary>;
  }
  return <LocalErrorBoundary fallback={fallback}>{children}</LocalErrorBoundary>;
}
