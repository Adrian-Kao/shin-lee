import React from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { I18nextProvider } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';

import App from './App.jsx';
import { ThemeProvider } from './lib/theme.jsx';
import i18n from './lib/i18n.js';
import { ToastViewport } from './lib/toast.jsx';
import { initSentry, SentryErrorBoundary } from './lib/sentry.jsx';
import './index.css';

// Day 5: init Sentry before render so React errors are captured by the boundary.
initSentry();

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <SentryErrorBoundary
      fallback={
        <div className="flex min-h-screen items-center justify-center p-6 text-center">
          <div className="max-w-md">
            <AlertTriangle
              className="mx-auto mb-3 h-12 w-12 text-amber-500"
              strokeWidth={1.5}
              aria-hidden="true"
            />
            <h1 className="mb-1 text-lg font-semibold">Something went wrong</h1>
            <p className="mb-4 text-sm text-slate-500">
              The error has been reported. Try refreshing the page.
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded-md bg-navy-900 px-4 py-2 text-sm font-medium text-white hover:bg-navy-700"
            >
              Reload
            </button>
          </div>
        </div>
      }
    >
      <I18nextProvider i18n={i18n}>
        <ThemeProvider>
          <BrowserRouter>
            <App />
            <ToastViewport />
          </BrowserRouter>
        </ThemeProvider>
      </I18nextProvider>
    </SentryErrorBoundary>
  </React.StrictMode>
);
