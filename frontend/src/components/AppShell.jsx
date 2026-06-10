import React, { useEffect, useMemo, useState } from 'react';
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
  Languages,
  Sun,
  Moon,
} from 'lucide-react';

import { useAuditVerify } from '../api/queries.js';
import i18n, { htmlLangFor } from '../lib/i18n';
import { useTheme } from '../lib/theme.jsx';
import { Button } from './ui/button.jsx';
import { Badge } from './ui/badge.jsx';
import StackStatus from './StackStatus.jsx';

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

  // CHUNK-8 — poll chain verify so the chip reflects real state. P1③: this is
  // now a TanStack Query that SHARES its key (['audit','verify',scope]) with
  // the AuditView page, so the chip + the page no longer issue two separate
  // verify requests. Polls every 60s; only enabled for audit-capable roles.
  const verifyQ = useAuditVerify(session?.token, auditScope, {
    poll: true,
    enabled: canCallAudit,
  });
  const auditState = useMemo(() => {
    if (!canCallAudit) return { status: 'idle', verified: 0, broken: 0, error: null };
    if (verifyQ.error) {
      return { status: 'fail', verified: 0, broken: 0, error: verifyQ.error?.message || 'verify failed' };
    }
    if (!verifyQ.data) return { status: 'idle', verified: 0, broken: 0, error: null };
    // verify_global_chain returns broken as list[tuple]; verify_chain returns
    // list[str]. Length is the right signal either way.
    const brokenCount = Array.isArray(verifyQ.data.broken) ? verifyQ.data.broken.length : 0;
    return {
      status: brokenCount === 0 ? 'ok' : 'fail',
      verified: verifyQ.data.verified ?? 0,
      broken: brokenCount,
      error: null,
    };
  }, [canCallAudit, verifyQ.data, verifyQ.error]);

  const navItems = useMemo(
    () => [
      { id: 'analyze', to: '/analyze', label: t('nav.analyze'), Icon: FileSearch },
      { id: 'cases', to: '/cases', label: t('nav.cases'), Icon: Folder },
      { id: 'audit', to: '/audit', label: t('nav.audit'), Icon: ScrollText },
    ],
    [t]
  );

  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
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
      <ShellFooter t={t} />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Footer — integration stack status + build tag                            */
/* -------------------------------------------------------------------------- */

function ShellFooter({ t }) {
  // Sticky so the integration chips stay visible without scrolling — the
  // Analyze page is taller than the viewport and the chips are the demo's
  // "the whole stack is alive" cue. Solid background + border keeps content
  // legible when it slides underneath.
  return (
    <footer className="sticky bottom-0 z-20 border-t border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
      <div className="mx-auto flex max-w-[1920px] flex-wrap items-center gap-x-4 gap-y-1 px-4 py-1.5 sm:px-6">
        <StackStatus />
        <span className="ml-auto hidden text-2xs text-slate-400 sm:inline dark:text-slate-500">
          {t('landing.footer')}
        </span>
      </div>
    </footer>
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
        </div>

        <div className="ml-auto flex items-center gap-3">
          <LanguageToggle />
          <ThemeToggle />
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
                <div className="text-2xs text-navy-200">
                  <span className="font-mono">{session.tenant_id}</span>
                </div>
              </div>
              <span className="rounded-full bg-white/10 px-2 py-0.5 text-2xs font-medium uppercase tracking-wider text-navy-50 ring-1 ring-white/15">
                {t(roleKey, { defaultValue: session.role })}
              </span>
            </div>
          )}
          <Button
            type="button"
            variant="ghost"
            size="xs"
            onClick={onLogout}
            className="gap-1.5 bg-white/10 text-white ring-1 ring-white/15 hover:bg-white/20 hover:text-white"
            aria-label={t('buttons.logout')}
          >
            <LogOut className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
            <span className="hidden sm:inline">{t('buttons.logout')}</span>
          </Button>
        </div>
      </div>
    </header>
  );
}

/* -------------------------------------------------------------------------- */
/*  Language toggle — zh-TW / EN                                              */
/* -------------------------------------------------------------------------- */

const LANG_KEY = 'pm.lang';

function applyLanguage(lng) {
  i18n.changeLanguage(lng);
  if (typeof document !== 'undefined') {
    document.documentElement.lang = htmlLangFor(lng);
  }
  try {
    localStorage.setItem(LANG_KEY, lng);
  } catch {
    /* localStorage may be unavailable (private mode) — non-fatal. */
  }
}

function LanguageToggle() {
  const [lang, setLang] = useState(i18n.language || 'zh-TW');

  // Restore persisted choice once on mount.
  useEffect(() => {
    let saved = null;
    try {
      saved = localStorage.getItem(LANG_KEY);
    } catch {
      saved = null;
    }
    const initial = saved || i18n.language || 'zh-TW';
    applyLanguage(initial);
    setLang(initial);
  }, []);

  const choose = (lng) => {
    applyLanguage(lng);
    setLang(lng);
  };

  const isZh = (lang || '').startsWith('zh');

  return (
    <div
      className="hidden items-center gap-0.5 rounded-md bg-white/10 p-0.5 ring-1 ring-white/15 sm:flex"
      role="group"
      aria-label="Language"
    >
      <Languages
        className="ml-1 mr-0.5 h-3.5 w-3.5 text-navy-100"
        strokeWidth={1.75}
        aria-hidden="true"
      />
      <LangButton active={isZh} onClick={() => choose('zh-TW')} label="繁中" />
      <LangButton active={!isZh} onClick={() => choose('en')} label="EN" />
    </div>
  );
}

function ThemeToggle() {
  const { t } = useTranslation();
  const { theme, setTheme } = useTheme();
  const isDark = theme === 'dark';
  const label = isDark ? t('shell.theme.to_light') : t('shell.theme.to_dark');
  return (
    <button
      type="button"
      data-testid="theme-toggle"
      onClick={() => setTheme(isDark ? 'light' : 'dark')}
      aria-label={label}
      title={label}
      className="hidden items-center justify-center rounded-md bg-white/10 p-1.5 text-navy-50 ring-1 ring-white/15 hover:bg-white/20 sm:inline-flex"
    >
      {isDark ? (
        <Sun className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
      ) : (
        <Moon className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
      )}
    </button>
  );
}

function LangButton({ active, onClick, label }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded px-1.5 py-0.5 text-2xs font-medium transition-colors ${
        active ? 'bg-white text-navy-900' : 'text-navy-50 hover:bg-white/15'
      }`}
    >
      {label}
    </button>
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
      title={failed ? t('shell.audit_chip.fail') : t('shell.audit_chip.tooltip')}
    >
      <Icon className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
      <span>{label}</span>
      {rowsText && <span className="hidden font-mono text-2xs opacity-80 sm:inline">·{' '}{rowsText}</span>}
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
    <div className="border-b border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
      <div
        data-testid="trust-band"
        className="mx-auto flex max-w-[1920px] flex-wrap items-center gap-2 px-4 py-2 sm:px-6"
      >
        <TrustChip
          testId="trust-redaction"
          Icon={Shield}
          tone="brand"
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
          tone="neutral"
          label={t('shell.trust.mapping_default')}
          title={t('shell.trust.mapping_tooltip')}
        />
        <TrustChip
          testId="trust-routing"
          Icon={isConfidential ? Lock : Cloud}
          tone={isConfidential ? 'confidential' : 'success'}
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
          <div className="ml-auto flex items-center gap-1.5 font-mono text-2xs text-slate-500">
            <span>tenant</span>
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-700 dark:bg-slate-800 dark:text-slate-200">
              {session.tenant_id}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function TrustChip({ Icon, label, title, tone, testId }) {
  // Tone is now a semantic STATUS_TONE key (brand/neutral/success/confidential/
  // warning/error); the Badge component owns the tone→class mapping so it stays
  // in one place and every class string is static for the JIT scanner.
  return (
    <Badge data-testid={testId} title={title} tone={tone}>
      <Icon className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
      <span>{label}</span>
    </Badge>
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
      aria-label={t('nav.primary')}
      data-testid="nav-rail"
      className={`flex shrink-0 flex-col border-r border-slate-200 bg-white transition-[width] duration-150 dark:border-slate-700 dark:bg-slate-900 ${
        collapsed ? 'sm:w-16' : 'sm:w-60'
      } w-16`}
    >
      <div className="flex-1 space-y-1 px-2 py-3">
        {items.map(({ id, to, label, Icon }) => {
          const isActive = activePath === to || activePath.startsWith(to + '/');
          return (
            <Button
              key={id}
              type="button"
              variant="ghost"
              onClick={() => onNavigate(to)}
              aria-current={isActive ? 'page' : undefined}
              aria-label={label}
              title={label}
              className={`group w-full justify-start gap-3 px-3 py-2 ${
                isActive
                  ? 'bg-navy-50 text-navy-900 ring-1 ring-navy-200 hover:bg-navy-50 hover:text-navy-900 dark:bg-navy-900/40 dark:text-navy-100 dark:ring-navy-800 dark:hover:bg-navy-900/40 dark:hover:text-navy-100'
                  : ''
              }`}
            >
              <Icon
                className={`h-5 w-5 shrink-0 ${isActive ? 'text-navy-700 dark:text-navy-300' : 'text-slate-500 dark:text-slate-400'}`}
                strokeWidth={1.75}
                aria-hidden="true"
              />
              <span className={`truncate ${collapsed ? 'hidden' : 'hidden sm:inline'}`}>{label}</span>
            </Button>
          );
        })}
      </div>
      <div className="hidden border-t border-slate-200 p-2 sm:block dark:border-slate-700">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setCollapsed((c) => !c)}
          aria-label={collapsed ? t('nav.expand') : t('nav.collapse')}
          className="w-full text-slate-500 hover:text-slate-700"
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
          ) : (
            <ChevronLeft className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
          )}
        </Button>
      </div>
    </nav>
  );
}
