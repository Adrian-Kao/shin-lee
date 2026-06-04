import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  ChevronLeft,
  ChevronRight,
  FileSearch,
  Folder,
  Lock,
  LogOut,
  ScrollText,
  Server,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Cloud,
} from 'lucide-react';

import { api } from '../api/client.js';

/**
 * Day 9C — CHUNK-1 + CHUNK-8 app shell.
 *
 * Single source of truth for the chrome around every authenticated page:
 *
 *   • Top bar (navy.900): brand left + chain-verify chip + user/role/logout right
 *   • Trust band: three persistent chips (Redaction, Mapping, Routing)
 *   • Left nav rail (collapsible): Analyze / Cases / Audit
 *
 * Children render inside <main>. The three-pane Analyze grid and AuditView's
 * own scrollable content are deliberately untouched — this shell only owns
 * the chrome, not the layout inside each route.
 *
 * Why a single shell instead of duplicating the header per-route:
 *   1. The trust band (CHUNK-8) MUST appear on every page (PRODUCT_STRATEGY
 *      §10 — "make trust visible" / CLAUDE.md invariants #3, #4, #6, #7).
 *      Mounting it once at shell level guarantees no route can ship without it.
 *   2. The chain-verify chip polls every 60s; mounting it inside a route
 *      would tear down the interval on navigation, defeating the polling.
 *
 * `trustContext` lets the active route inject runtime info (entity counts,
 * current case_id) without the shell having to import from those routes.
 */
export default function AppShell({ session, onLogout, children, trustContext }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [navCollapsed, setNavCollapsed] = useState(false);

  const isAuditor = session?.role === 'auditor';
  const isItAdmin = session?.role === 'it_admin';
  const auditScope = isAuditor ? 'global' : 'tenant';
  const canCallAudit = isAuditor || isItAdmin;

  const [auditState, setAuditState] = useState({
    status: 'idle',
    verified: 0,
    broken: 0,
    error: null,
  });

  // CHUNK-8 — poll chain verify so the chip reflects real state, not a
  // demo string. Only roles with audit access can hit the endpoint; for
  // attorney/paralegal we show an unverified-but-not-failed neutral chip.
  const refreshChain = useCallback(async () => {
    if (!session?.token || !canCallAudit) return;
    try {
      const r = await api.auditVerify(session.token, null, auditScope);
      // verify_global_chain returns broken as list[tuple]; verify_chain
      // returns broken as list[str]. Length is the right signal either way.
      const brokenCount = Array.isArray(r?.broken) ? r.broken.length : 0;
      setAuditState({
        status: brokenCount === 0 ? 'ok' : 'fail',
        verified: r?.verified ?? 0,
        broken: brokenCount,
        error: null,
      });
    } catch (e) {
      setAuditState((prev) => ({ ...prev, status: 'fail', error: e?.message || 'verify failed' }));
    }
  }, [session?.token, canCallAudit, auditScope]);

  useEffect(() => {
    refreshChain();
    if (!canCallAudit) return undefined;
    const id = setInterval(refreshChain, 60_000);
    return () => clearInterval(id);
  }, [refreshChain, canCallAudit]);

  const navItems = useMemo(
    () => [
      { id: 'analyze', to: '/analyze', label: t('nav.analyze'), Icon: FileSearch },
      { id: 'cases', to: '/cases', label: t('nav.cases'), Icon: Folder },
      { id: 'audit', to: '/audit', label: t('nav.audit'), Icon: ScrollText },
    ],
    [t]
  );

  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900">
      <TopBar
        session={session}
        onLogout={onLogout}
        auditState={auditState}
        canCallAudit={canCallAudit}
        onNavigateAudit={() => navigate('/audit')}
        t={t}
      />
      <TrustBand session={session} trustContext={trustContext} t={t} />
      <div className="flex flex-1">
        <NavRail
          items={navItems}
          collapsed={navCollapsed}
          setCollapsed={setNavCollapsed}
          activePath={location.pathname}
          onNavigate={navigate}
          t={t}
        />
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Top bar                                                                   */
/* -------------------------------------------------------------------------- */

function TopBar({ session, onLogout, auditState, canCallAudit, onNavigateAudit, t }) {
  const roleKey = `shell.role_badge.${session?.role || 'attorney'}`;
  return (
    <header className="bg-navy-900 text-white shadow-sm">
      <div className="mx-auto flex h-14 max-w-[1920px] items-center gap-4 px-4 sm:px-6">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-white/10 text-sm font-bold ring-1 ring-white/20 backdrop-blur">
            PM
          </div>
          <span className="text-base font-semibold tracking-tight">{t('app_title')}</span>
          <span className="rounded bg-amber-400/90 px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-amber-950">
            {t('app_tag_poc')}
          </span>
        </div>

        <div className="ml-auto flex items-center gap-3">
          <ChainChip
            state={auditState}
            canCallAudit={canCallAudit}
            onClick={onNavigateAudit}
            t={t}
          />
          {session && (
            <div className="hidden items-center gap-3 sm:flex">
              <div className="text-right text-xs leading-tight">
                <div className="font-medium text-white">{session.display_name}</div>
                <div className="text-[11px] text-navy-200">
                  <span className="font-mono">{session.tenant_id}</span>
                </div>
              </div>
              <span className="rounded-full bg-white/10 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wider text-navy-50 ring-1 ring-white/15">
                {t(roleKey, { defaultValue: session.role })}
              </span>
            </div>
          )}
          <button
            type="button"
            onClick={onLogout}
            className="inline-flex items-center gap-1.5 rounded-md bg-white/10 px-2.5 py-1.5 text-xs font-medium text-white ring-1 ring-white/15 transition-colors hover:bg-white/20"
            aria-label={t('buttons.logout')}
          >
            <LogOut className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
            <span className="hidden sm:inline">{t('buttons.logout')}</span>
          </button>
        </div>
      </div>
    </header>
  );
}

function ChainChip({ state, canCallAudit, onClick, t }) {
  const failed = state.status === 'fail';
  const Icon = failed ? ShieldAlert : ShieldCheck;
  // For non-audit roles we render a quieter neutral chip — the chain still
  // exists, they just can't poll it. Same icon, dimmer color.
  const tone = failed
    ? 'bg-rose-600/90 hover:bg-rose-600 text-white ring-rose-300/40'
    : canCallAudit
      ? 'bg-emerald-600/90 hover:bg-emerald-600 text-white ring-emerald-300/40'
      : 'bg-white/10 hover:bg-white/15 text-navy-50 ring-white/15';
  const label = failed
    ? t('shell.audit_chip.fail')
    : canCallAudit
      ? t('shell.audit_chip.ok')
      : t('shell.audit_chip.ok');
  const rowsText =
    canCallAudit && state.verified > 0
      ? t('shell.audit_chip.rows', { rows: state.verified.toLocaleString() })
      : null;
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid="trust-chain-chip"
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 transition-colors ${tone}`}
      title={failed ? t('shell.audit_chip.fail') : 'Audit chain (Q13)'}
    >
      <Icon className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
      <span>{label}</span>
      {rowsText && <span className="hidden font-mono text-[11px] opacity-80 sm:inline">·{' '}{rowsText}</span>}
    </button>
  );
}

/* -------------------------------------------------------------------------- */
/*  Trust band — CHUNK-8                                                      */
/* -------------------------------------------------------------------------- */

function TrustBand({ session, trustContext, t }) {
  const caseId = trustContext?.caseId || '';
  const isConfidential =
    typeof caseId === 'string' && caseId.toUpperCase().endsWith('-CONF');
  const maskedCount = trustContext?.maskedEntityCount ?? 0;

  return (
    <div className="border-b border-slate-200 bg-white">
      <div
        data-testid="trust-band"
        className="mx-auto flex max-w-[1920px] flex-wrap items-center gap-2 px-4 py-2 sm:px-6"
      >
        <TrustChip
          testId="trust-redaction"
          Icon={Shield}
          tone="navy"
          label={
            maskedCount > 0
              ? t('shell.trust.redaction_active', { count: maskedCount })
              : t('shell.trust.redaction_default')
          }
          title={t('shell.trust.redaction_tooltip')}
        />
        <TrustChip
          testId="trust-mapping"
          Icon={Server}
          tone="slate"
          label={t('shell.trust.mapping_default')}
          title={t('shell.trust.mapping_tooltip')}
        />
        <TrustChip
          testId="trust-routing"
          Icon={isConfidential ? Lock : Cloud}
          tone={isConfidential ? 'purple' : 'emerald'}
          label={
            isConfidential
              ? t('shell.trust.routing_confidential')
              : t('shell.trust.routing_auto')
          }
          title={
            isConfidential
              ? t('shell.trust.routing_tooltip_conf')
              : t('shell.trust.routing_tooltip_auto')
          }
        />
        {session?.tenant_id && (
          <div className="ml-auto flex items-center gap-1.5 font-mono text-[11px] text-slate-500">
            <span>tenant</span>
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-700">
              {session.tenant_id}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function TrustChip({ Icon, label, title, tone, testId }) {
  // Tone → tailwind classes. Kept explicit (not interpolated) so the JIT
  // scanner picks every class up at build time.
  const toneClasses = {
    navy: 'bg-navy-50 text-navy-900 ring-navy-200',
    slate: 'bg-slate-100 text-slate-700 ring-slate-200',
    emerald: 'bg-emerald-50 text-emerald-800 ring-emerald-200',
    purple: 'bg-purple-50 text-purple-800 ring-purple-200',
    amber: 'bg-amber-50 text-amber-800 ring-amber-200',
    rose: 'bg-rose-50 text-rose-700 ring-rose-200',
  };
  return (
    <span
      data-testid={testId}
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ${toneClasses[tone] || toneClasses.slate}`}
    >
      <Icon className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
      <span>{label}</span>
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/*  Left nav rail                                                             */
/* -------------------------------------------------------------------------- */

function NavRail({ items, collapsed, setCollapsed, activePath, onNavigate, t }) {
  // Mobile (< sm): the rail collapses to an icon strip but stays visible —
  // the old POC had a top-bar inline nav at every viewport, so existing
  // e2e tests still need a clickable "Audit" button on iPhone X.
  // Desktop: respects the user's expand/collapse preference.
  const mobileCollapsed = true;
  return (
    <nav
      aria-label="Primary"
      data-testid="nav-rail"
      className={`flex shrink-0 flex-col border-r border-slate-200 bg-white transition-[width] duration-150 ${
        collapsed ? 'sm:w-16' : 'sm:w-60'
      } w-16`}
    >
      <div className="flex-1 space-y-1 px-2 py-3">
        {items.map(({ id, to, label, Icon }) => {
          const isActive = activePath === to || activePath.startsWith(to + '/');
          return (
            <button
              key={id}
              type="button"
              onClick={() => onNavigate(to)}
              aria-current={isActive ? 'page' : undefined}
              aria-label={label}
              className={`group flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-navy-50 text-navy-900 ring-1 ring-navy-200'
                  : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
              }`}
              title={label}
            >
              <Icon
                className={`h-5 w-5 shrink-0 ${isActive ? 'text-navy-700' : 'text-slate-500'}`}
                strokeWidth={1.75}
                aria-hidden="true"
              />
              <span className={`truncate ${collapsed ? 'hidden' : 'hidden sm:inline'}`}>{label}</span>
            </button>
          );
        })}
      </div>
      <div className="hidden border-t border-slate-200 p-2 sm:block">
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          aria-label={collapsed ? t('nav.expand') : t('nav.collapse')}
          className="flex w-full items-center justify-center rounded-md px-2 py-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
          ) : (
            <ChevronLeft className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
          )}
        </button>
      </div>
    </nav>
  );
}
