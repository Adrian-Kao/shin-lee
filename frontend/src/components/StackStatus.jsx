import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

/**
 * Delivery polish — integration "stack status" strip for the AppShell footer.
 *
 * Shows one chip per infrastructure tier the demo runs on:
 *
 *   Gateway     — authoritative check via the same-origin `/api/v1/health`
 *                 (vite proxies to the thin gateway / digiRunner, so this is
 *                 the only probe that can read a JSON body).
 *   AI Engine   — reachability probe to :8011 (FastAPI, no CORS headers).
 *   digiRunner  — reachability probe to :18080 (TPIsoftware API gateway).
 *   Dify        — reachability probe to :8088 (LLMOps platform).
 *
 * The three external probes use `mode: 'no-cors'`: the browser can't read the
 * response, but a resolved fetch means SOMETHING answered on that port (up),
 * while a rejected fetch means connection refused / timeout (unknown). CORS
 * never throws in no-cors mode, so a running-but-CORS-less service still
 * registers green. Failures degrade to a neutral gray "not detected" chip —
 * never an error state, per the demo's "subtle and professional" requirement.
 *
 * Probe targets are overridable at build time (VITE_*_PROBE_URL) so a docker /
 * remote topology can point the chips elsewhere without code changes.
 */

const PROBE_TIMEOUT_MS = 2500;
const POLL_INTERVAL_MS = 30_000;

const ENV = typeof import.meta !== 'undefined' && import.meta.env ? import.meta.env : {};

const STACK_SERVICES = [
  { id: 'gateway', label: 'Gateway', kind: 'gateway' },
  {
    id: 'ai-engine',
    label: 'AI Engine',
    url: ENV.VITE_AI_ENGINE_PROBE_URL || 'http://127.0.0.1:8011/v1/health',
  },
  {
    id: 'digirunner',
    label: 'digiRunner',
    url: ENV.VITE_DIGIRUNNER_PROBE_URL || 'http://localhost:18080/',
  },
  {
    id: 'dify',
    label: 'Dify',
    url: ENV.VITE_DIFY_PROBE_URL || 'http://localhost:8088/',
  },
];

function withTimeout(run) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  return run(controller.signal).finally(() => clearTimeout(timer));
}

async function probeGateway(signal) {
  const res = await fetch('/api/v1/health', { signal, cache: 'no-store' });
  if (!res.ok) return 'unknown';
  const data = await res.json().catch(() => null);
  return data && data.ok ? 'up' : 'unknown';
}

async function probeOpaque(url, signal) {
  // Opaque response — any HTTP answer (any status, any origin) means the
  // service is listening. Only network-level failure rejects.
  await fetch(url, { mode: 'no-cors', signal, cache: 'no-store' });
  return 'up';
}

async function probeService(service) {
  try {
    return await withTimeout((signal) =>
      service.kind === 'gateway' ? probeGateway(signal) : probeOpaque(service.url, signal)
    );
  } catch {
    return 'unknown';
  }
}

export default function StackStatus() {
  const { t } = useTranslation();
  const [statuses, setStatuses] = useState(() =>
    Object.fromEntries(STACK_SERVICES.map((s) => [s.id, 'checking']))
  );
  const aliveRef = useRef(true);

  const runProbes = useCallback(() => {
    STACK_SERVICES.forEach((service) => {
      probeService(service).then((status) => {
        if (!aliveRef.current) return;
        setStatuses((prev) => (prev[service.id] === status ? prev : { ...prev, [service.id]: status }));
      });
    });
  }, []);

  useEffect(() => {
    aliveRef.current = true;
    runProbes();
    const id = setInterval(runProbes, POLL_INTERVAL_MS);
    return () => {
      aliveRef.current = false;
      clearInterval(id);
    };
  }, [runProbes]);

  return (
    <div
      data-testid="stack-status"
      className="flex flex-wrap items-center gap-x-3 gap-y-1"
      role="status"
      aria-label={t('shell.stack.title')}
    >
      <span className="text-2xs font-medium uppercase tracking-wider text-slate-400 dark:text-slate-500">
        {t('shell.stack.title')}
      </span>
      {STACK_SERVICES.map((service) => (
        <StatusChip
          key={service.id}
          id={service.id}
          label={service.label}
          status={statuses[service.id]}
          t={t}
        />
      ))}
    </div>
  );
}

const DOT_CLASS = {
  up: 'bg-emerald-500',
  unknown: 'bg-slate-300 dark:bg-slate-600',
  checking: 'animate-pulse bg-slate-300 dark:bg-slate-600',
};

function StatusChip({ id, label, status, t }) {
  const statusText = t(`shell.stack.${status}`, { defaultValue: status });
  return (
    <span
      data-testid={`stack-status-${id}`}
      data-status={status}
      title={`${label} — ${statusText}`}
      className="inline-flex items-center gap-1.5 text-2xs text-slate-500 dark:text-slate-400"
    >
      <span
        aria-hidden="true"
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT_CLASS[status] || DOT_CLASS.unknown}`}
      />
      <span>{label}</span>
      <span className="sr-only">{statusText}</span>
    </span>
  );
}
