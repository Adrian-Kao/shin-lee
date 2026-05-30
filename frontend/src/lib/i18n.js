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
      upload: {
        drop_zone: '拖放 PDF / DOCX 到這裡，或',
        browse: '瀏覽檔案',
        invalid_type: '只支援 PDF 或 DOCX',
        too_large: '檔案太大（>30MB）',
        upload_button: '上傳',
        cancel_button: '取消',
        retry_button: '重試',
        use_this_text: '使用此文字',
        extracting: '伺服器處理中... (掃描頁需 OCR，可能 10-30 秒)',
        success: '已抽出 {{pages}} 頁 / {{chars}} 字',
        ocr_used: '{{count}} 頁透過 OCR（成本 ${{cost}}）',
        loaded_chip: '從 {{filename}} 載入 ({{pages}} 頁)',
        switch_to_paste: '📋 改貼文字',
        switch_to_upload: '📎 改用上傳',
        docx_no_preview: 'DOCX 無法預覽；抽出文字將顯示於下方',
        uploading: '上傳中...',
        change_file: '換一個',
        file_selected: '已選擇檔案',
      },
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
      upload: {
        drop_zone: 'Drop PDF / DOCX here, or',
        browse: 'browse files',
        invalid_type: 'Only PDF or DOCX supported',
        too_large: 'File too large (>30MB)',
        upload_button: 'Upload',
        cancel_button: 'Cancel',
        retry_button: 'Retry',
        use_this_text: 'Use this text',
        extracting: 'Server processing... (scanned pages need OCR, may take 10-30s)',
        success: 'Extracted {{pages}} pages / {{chars}} chars',
        ocr_used: '{{count}} pages via OCR (cost ${{cost}})',
        loaded_chip: 'Loaded from {{filename}} ({{pages}} pages)',
        switch_to_paste: '📋 Paste text instead',
        switch_to_upload: '📎 Upload file instead',
        docx_no_preview: 'DOCX preview not supported; extracted text will appear below',
        uploading: 'Uploading...',
        change_file: 'Change file',
        file_selected: 'File selected',
      },
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
