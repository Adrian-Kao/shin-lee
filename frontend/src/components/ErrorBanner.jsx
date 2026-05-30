import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle } from 'lucide-react';

const RATE_LIMIT_COUNTDOWN_SEC = 30;

function classifyError(err, t) {
  if (!err) return null;
  const status = err.status ?? null;

  if (status === 401) {
    return { message: t('errors.session_expired'), retryable: false, requiresLogin: true };
  }
  if (status === 403) {
    return { message: t('errors.no_access'), retryable: false };
  }
  if (status === 413) {
    return { message: t('errors.file_too_large'), retryable: false };
  }
  if (status === 429) {
    return { message: t('errors.rate_limited'), retryable: true, countdown: true };
  }
  if (status === 500 || status === 502 || status === 503) {
    return { message: t('errors.server_busy'), retryable: true };
  }
  if (status === null || status === undefined || status === 0) {
    return { message: t('errors.network'), retryable: true };
  }
  if (status >= 400 && status < 500) {
    const detail = (err.body && typeof err.body === 'object' && err.body.detail) || err.message;
    return { message: detail || t('errors.request_failed'), retryable: false };
  }
  return { message: t('errors.unexpected'), retryable: false, showDetails: true };
}

export default function ErrorBanner({ error, onRetry, onDismiss, onLogin }) {
  const { t } = useTranslation();
  const info = classifyError(error, t);
  const [countdown, setCountdown] = useState(0);

  useEffect(() => {
    if (info?.countdown) setCountdown(RATE_LIMIT_COUNTDOWN_SEC);
    else setCountdown(0);
  }, [error, info?.countdown]);

  useEffect(() => {
    if (countdown <= 0) return undefined;
    const id = setInterval(() => setCountdown((c) => (c > 0 ? c - 1 : 0)), 1000);
    return () => clearInterval(id);
  }, [countdown]);

  if (!info) return null;

  const retryDisabled = info.countdown && countdown > 0;
  const showRetry = info.retryable && typeof onRetry === 'function';
  const showLogin = info.requiresLogin && typeof onLogin === 'function';
  const rawMessage =
    error && typeof error === 'object' ? error.message || String(error) : String(error || '');

  return (
    <div
      role="alert"
      className="flex flex-col gap-2 rounded-md border border-rose-200 bg-rose-50 p-3 text-rose-700 sm:flex-row sm:items-start sm:gap-3"
    >
      <AlertCircle className="mt-0.5 h-5 w-5 flex-shrink-0" aria-hidden="true" />

      <div className="min-w-0 flex-1">
        <p className="break-words text-sm leading-5">{info.message}</p>
        {info.showDetails && rawMessage && (
          <details className="mt-1 text-xs text-rose-600/80">
            <summary className="cursor-pointer select-none">
              {t('errors.technical_details')}
            </summary>
            <pre className="mt-1 whitespace-pre-wrap break-words font-mono text-[11px]">
              {rawMessage}
            </pre>
          </details>
        )}
      </div>

      <div className="flex flex-shrink-0 flex-wrap gap-2 self-start sm:self-auto">
        {showLogin && (
          <button
            type="button"
            onClick={onLogin}
            className="rounded bg-rose-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-rose-700"
          >
            {t('errors.login_again')}
          </button>
        )}
        {showRetry && (
          <button
            type="button"
            onClick={onRetry}
            disabled={retryDisabled}
            className="rounded border border-rose-300 bg-white px-2.5 py-1 text-xs font-medium text-rose-700 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {retryDisabled ? t('errors.retry_in', { seconds: countdown }) : t('errors.retry')}
          </button>
        )}
        {typeof onDismiss === 'function' && (
          <button
            type="button"
            onClick={onDismiss}
            className="rounded border border-rose-200 bg-white px-2.5 py-1 text-xs font-medium text-rose-600 hover:bg-rose-100"
          >
            {t('errors.dismiss')}
          </button>
        )}
      </div>
    </div>
  );
}
