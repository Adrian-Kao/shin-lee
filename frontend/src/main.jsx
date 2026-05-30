import React from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { I18nextProvider } from 'react-i18next';

import App from './App.jsx';
import { ThemeProvider } from './lib/theme.jsx';
import i18n from './lib/i18n.js';
import { ToastViewport } from './lib/toast.jsx';
import './index.css';

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <I18nextProvider i18n={i18n}>
      <ThemeProvider>
        <BrowserRouter>
          <App />
          <ToastViewport />
        </BrowserRouter>
      </ThemeProvider>
    </I18nextProvider>
  </React.StrictMode>
);
