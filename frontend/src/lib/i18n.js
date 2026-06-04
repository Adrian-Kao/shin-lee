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
        expand: '展開導覽',
        collapse: '收合導覽',
      },
      shell: {
        audit_chip: {
          ok: '已驗證鏈',
          checking: '驗證中…',
          fail: '鏈不一致 — 請聯絡 Ops',
          rows: '{{rows}} 列',
        },
        role_badge: {
          attorney: '律師',
          paralegal: '法務助理',
          it_admin: 'IT 管理',
          auditor: '稽核',
        },
        trust: {
          redaction_default: '自動遮罩啟用',
          redaction_active: '已遮罩 {{count}} 項實體',
          redaction_tooltip:
            'PII / 客戶字典於每次 LLM 呼叫前強制套用（CLAUDE.md §4 不可違反）。',
          mapping_default: '映射表本地端',
          mapping_tooltip:
            '對應表存於 data/redaction_mapping.db；不離開本地端（CLAUDE.md §9）。',
          routing_auto: '路由：自動',
          routing_confidential: '路由：本地 LLM（機密）',
          routing_tooltip_auto:
            '一般案件可走雲端模型；含 -CONF 字尾的案件號將強制改走 on-prem LLM。',
          routing_tooltip_conf:
            'CASE 字尾為 -CONF：依 CLAUDE.md §4 不可違反第 7 條強制路由 on-prem LLM。',
        },
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
        switch_to_paste: '改貼文字',
        switch_to_upload: '改用上傳',
        docx_no_preview: 'DOCX 無法預覽；抽出文字將顯示於下方',
        uploading: '上傳中...',
        change_file: '換一個',
        file_selected: '已選擇檔案',
        toast_success: '已抽出 {{pages}} 頁，文字已填入下方',
      },
      landing: {
        tagline: 'AI 輔助專利答辯草擬 — Office Action 自動分析與草稿生成',
        value_classify: 'OA 自動分類（§22-2 進步性 / §26-2 明確性 等 7 種）',
        value_grounded: 'RAG grounded 引證，每段引用必有先前技術出處',
        value_deadline: '自動計算法定期日（TW + US，含假日 roll-forward）',
        value_compliance: '自動 redaction + audit chain（事務所合規）',
        pick_user: '選擇 demo 身分',
        poc_note: 'POC 預設無密碼。正式版接 OIDC / SAML / magic link（Q12）',
        footer: 'POC · v0.3 · 內部 demo only',
      },
      placeholder: {
        cases_title: '案件管理 — Coming Soon',
        cases_subtitle: 'Phase 4 將整合的功能',
        cases_bullet_1: '拖拽上傳多份 OA（一次處理 N 件）',
        cases_bullet_2: '案件 timeline 視覺化（初審 → 答辯 → 再審 → 駁回 → 訴願）',
        cases_bullet_3: '與外部 docketing 系統同步（PAS / Townes）',
        back_to_analyze: '回分析頁',
      },
      errors: {
        session_expired: '工作階段過期，請重新登入',
        no_access: '您沒有此案件的存取權限。請確認 case_id 與您的登入身分相符',
        file_too_large: '檔案太大。上限 30MB',
        rate_limited: '請求過於頻繁，請稍候再試',
        server_busy: '伺服器忙線中',
        network: '連線失敗。檢查網路與後端是否運行',
        request_failed: '請求失敗',
        unexpected: '未預期錯誤',
        retry: '重試',
        dismiss: '關閉',
        login_again: '登入',
        retry_in: '{{seconds}} 秒後可重試',
        technical_details: '技術細節',
      },
      empty: {
        no_result_title: '準備分析',
        no_result_desc: '左側輸入或上傳 OA，點「分析 OA」開始',
        no_result_hint: 'Demo 預設 CASE-2025-001（Alice 有權限）',
        no_audit_title: '尚無 audit 紀錄',
        no_audit_desc: '完成任何 API 呼叫後會在此顯示',
      },
      audit: {
        hero: {
          rows_label: '稽核總列數',
          mismatches_label: '不一致數',
          last_verified_label: '最近驗證時間',
          never_verified: '尚未驗證',
        },
        verify_now: '立即驗證鏈',
        verifying: '驗證中…',
        verify_passed: '{{rows}} 列全部通過 hash 驗證，無 tampering 痕跡。',
        verify_failed: '發現 {{count}} 列被竄改：{{rows}}',
      },
      analyze: {
        pane_input: '輸入 OA / Input',
        pane_drafts: '草稿 / Drafts',
        pane_refs: '引證 / References',
        claim_tree: {
          title: '請求項依賴樹',
          claims: '項',
          legend: {
            rejected: '駁回',
            cascade: '連帶風險',
            clean: '無駁回',
          },
        },
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
        expand: 'Expand navigation',
        collapse: 'Collapse navigation',
      },
      shell: {
        audit_chip: {
          ok: 'Chain verified',
          checking: 'Verifying…',
          fail: 'Chain mismatch — contact ops',
          rows: '{{rows}} rows',
        },
        role_badge: {
          attorney: 'Attorney',
          paralegal: 'Paralegal',
          it_admin: 'IT Admin',
          auditor: 'Auditor',
        },
        trust: {
          redaction_default: 'Auto-mask active',
          redaction_active: '{{count}} entities masked',
          redaction_tooltip:
            'PII and customer dictionaries are applied before any LLM call (CLAUDE.md §4 invariant).',
          mapping_default: 'Mapping table on-prem',
          mapping_tooltip:
            'Reversal map stored at data/redaction_mapping.db — NEVER leaves on-prem (CLAUDE.md §9).',
          routing_auto: 'Routing: Auto',
          routing_confidential: 'Routing: Local LLM (confidential)',
          routing_tooltip_auto:
            'Standard cases may use cloud models; cases ending in -CONF auto-route to the on-prem LLM.',
          routing_tooltip_conf:
            'Case ID ends in -CONF: routed to the on-prem LLM per CLAUDE.md §4 invariant #7.',
        },
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
        switch_to_paste: 'Paste text instead',
        switch_to_upload: 'Upload file instead',
        docx_no_preview: 'DOCX preview not supported; extracted text will appear below',
        uploading: 'Uploading...',
        change_file: 'Change file',
        file_selected: 'File selected',
        toast_success: 'Extracted {{pages}} pages, text loaded below',
      },
      landing: {
        tagline: 'AI-assisted patent OA response — automatic analysis & draft generation',
        value_classify: 'Auto-classify rejections (§22-2 obviousness, §26-2 antecedent basis, +5)',
        value_grounded: 'RAG-grounded citations — every quote points to real prior art',
        value_deadline: 'Auto-compute statutory deadlines (TW + US, holiday roll-forward)',
        value_compliance: 'Auto redaction + audit chain (law firm compliance)',
        pick_user: 'Pick a demo identity',
        poc_note: 'POC has no password. Production wires OIDC / SAML / magic link (Q12)',
        footer: 'POC · v0.3 · internal demo only',
      },
      placeholder: {
        cases_title: 'Case Management — Coming Soon',
        cases_subtitle: 'Phase 4 features',
        cases_bullet_1: 'Drag-drop multiple OAs (batch processing)',
        cases_bullet_2: 'Case timeline visualization (filing → response → reexam → final)',
        cases_bullet_3: 'Sync with external docketing systems (PAS / Townes)',
        back_to_analyze: 'Back to Analyze',
      },
      errors: {
        session_expired: 'Session expired. Please log in again.',
        no_access: 'You do not have access to this case. Verify case_id matches your identity.',
        file_too_large: 'File too large. Maximum 30MB.',
        rate_limited: 'Too many requests. Please wait and retry.',
        server_busy: 'Server busy.',
        network: 'Connection failed. Check network and backend.',
        request_failed: 'Request failed.',
        unexpected: 'Unexpected error.',
        retry: 'Retry',
        dismiss: 'Dismiss',
        login_again: 'Login',
        retry_in: 'Retry in {{seconds}}s',
        technical_details: 'Technical details',
      },
      empty: {
        no_result_title: 'Ready to analyze',
        no_result_desc: 'Enter or upload an OA on the left, then click "Analyze OA"',
        no_result_hint: 'Demo defaults to CASE-2025-001 (Alice has access)',
        no_audit_title: 'No audit records yet',
        no_audit_desc: 'Will appear here after any API call completes',
      },
      audit: {
        hero: {
          rows_label: 'Audit rows',
          mismatches_label: 'Mismatches',
          last_verified_label: 'Last verified',
          never_verified: 'Not verified yet',
        },
        verify_now: 'Verify chain now',
        verifying: 'Verifying…',
        verify_passed: 'All {{rows}} rows passed hash verification — no tampering detected.',
        verify_failed: '{{count}} rows tampered: {{rows}}',
      },
      analyze: {
        pane_input: 'Input',
        pane_drafts: 'Drafts',
        pane_refs: 'References',
        claim_tree: {
          title: 'Claim dependency tree',
          claims: 'claims',
          legend: {
            rejected: 'Rejected',
            cascade: 'Cascade',
            clean: 'Clean',
          },
        },
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
