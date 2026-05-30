import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

/**
 * App-shell i18n scaffolding (slice B).
 *
 * Only the shell strings are stubbed (title, nav, common buttons). Component
 * internals (Login.jsx / Analyze.jsx / etc.) still ship their original
 * bilingual strings — Phase 4 will migrate them.
 *
 * Default language is zh-TW per CLAUDE.md product context (Taiwan patent firms).
 */
const resources = {
  'zh-TW': {
    common: {
      app_title: 'PatentMind AI',
      app_tag_poc: 'POC',
      nav: {
        analyze: '分析',
        audit: 'Audit',
        cases: '案件',
      },
      buttons: {
        login: '登入',
        logout: '登出',
        submit: '送出',
        cancel: '取消',
      },
      coming_soon: '即將推出',
    },
  },
  en: {
    common: {
      app_title: 'PatentMind AI',
      app_tag_poc: 'POC',
      nav: {
        analyze: 'Analyze',
        audit: 'Audit',
        cases: 'Cases',
      },
      buttons: {
        login: 'Login',
        logout: 'Logout',
        submit: 'Submit',
        cancel: 'Cancel',
      },
      coming_soon: 'Coming soon',
    },
  },
};

i18n.use(initReactI18next).init({
  resources,
  lng: 'zh-TW',
  fallbackLng: 'en',
  defaultNS: 'common',
  ns: ['common'],
  interpolation: {
    escapeValue: false,
  },
  react: {
    useSuspense: false,
  },
});

export default i18n;
