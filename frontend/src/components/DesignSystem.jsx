import {
  Check,
  CheckCheck,
  Moon,
  Pencil,
  ShieldAlert,
  ShieldCheck,
  Sun,
  Undo2,
  AlertTriangle,
  X,
} from 'lucide-react';
import { Button } from './ui/button.jsx';
import { Badge, STATUS_TONE } from './ui/badge.jsx';
import { useTheme } from '../lib/theme.jsx';
import { toast } from '../lib/toast.jsx';

/**
 * PatentMind Design System — 內部視覺審稿頁（/design，免登入）。
 *
 * 每張卡都用「真實 token + 真實元件 class」render：色票直接取
 * tailwind.config.js 的 navy 階、Badge/Button 用 ui/ 的真元件、簽核三態
 * 用 index.css 的 ai-line/attorney-line。這頁就是 docs/DESIGN_SYSTEM.md
 * 的活文件 — 改了 token，這頁立刻反映；spec 與落地不會分家。
 *
 * 深淺色：右上角切換即時生效（ThemeProvider，與正式 app 共用同一份
 * localStorage 設定）。
 */

// 與 tailwind.config.js 的 navy 階一致 — 這裡重複列值是為了印出 hex 標籤
// （Tailwind class 印不出自己的 hex）。改 config 時同步改這裡。
const NAVY_SCALE = [
  ['50', '#eff6ff'],
  ['100', '#dbeafe'],
  ['200', '#bfdbfe'],
  ['300', '#93c5fd'],
  ['400', '#60a5fa'],
  ['500', '#3b82f6'],
  ['600', '#2563eb'],
  ['700', '#1d4ed8'],
  ['800', '#1e40af'],
  ['900', '#1e3a8a'],
];

const ACCENTS = [
  ['amber-400', '#fbbf24', '強調 / 警示底'],
  ['amber-500', '#f59e0b', '品牌琥珀（海報/簡報）'],
  ['emerald-600', '#059669', '成功 / 律師句'],
  ['rose-600', '#e11d48', '危險 / 剝除引用'],
  ['purple-600', '#9333ea', '機密路由'],
];

export default function DesignSystem() {
  const { theme, setTheme } = useTheme();
  const dark = theme === 'dark';

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-8 dark:bg-slate-950 md:px-10">
      <header className="mx-auto mb-8 flex max-w-6xl flex-wrap items-end justify-between gap-4">
        <div>
          <div className="mb-1 flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-md bg-navy-900 text-xs font-bold text-white dark:bg-navy-700">
              PM
            </span>
            <h1 className="text-2xl font-bold text-navy-900 dark:text-navy-100">
              PatentMind Design System
            </h1>
          </div>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            冷墨藍 × 琥珀 · 法律工作場景的保守色盤 · 活文件（與 ui/ 元件同源）· v1
          </p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setTheme(dark ? 'light' : 'dark')}
          className="gap-2"
          data-testid="ds-theme-toggle"
        >
          {dark ? (
            <Sun className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
          ) : (
            <Moon className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
          )}
          {dark ? '切換淺色' : '切換深色'}
        </Button>
      </header>

      <main className="mx-auto grid max-w-6xl gap-5 md:grid-cols-2">
        {/* 01 品牌色盤 */}
        <Card num="01" title="品牌色盤 — 冷墨 Navy 階">
          <div className="flex overflow-hidden rounded-md">
            {NAVY_SCALE.map(([step, hex]) => (
              <div key={step} className="flex-1">
                <div className="h-14" style={{ background: hex }} />
                <div className="px-1 py-1 text-center font-mono text-2xs text-slate-500 dark:text-slate-400">
                  {step}
                </div>
              </div>
            ))}
          </div>
          <Hint>
            主色 navy-900 (#1e3a8a) 用於頂欄 / 主按鈕；500 用於互動焦點；50–100 用於底色。
          </Hint>
        </Card>

        {/* 02 強調與語意原色 */}
        <Card num="02" title="強調色與語意原色">
          <div className="space-y-2">
            {ACCENTS.map(([name, hex, usage]) => (
              <div key={name} className="flex items-center gap-3">
                <div className="h-8 w-16 shrink-0 rounded" style={{ background: hex }} />
                <code className="w-28 shrink-0 font-mono text-xs text-slate-600 dark:text-slate-300">
                  {name}
                </code>
                <span className="text-xs text-slate-500 dark:text-slate-400">{usage}</span>
              </div>
            ))}
          </div>
        </Card>

        {/* 03 語意徽章矩陣 */}
        <Card num="03" title="語意徽章 — 7 tone × 3 variant（ui/badge.jsx）">
          <div className="space-y-2">
            {Object.keys(STATUS_TONE).map((tone) => (
              <div key={tone} className="flex flex-wrap items-center gap-2">
                <code className="w-24 shrink-0 font-mono text-2xs text-slate-400">{tone}</code>
                <Badge tone={tone}>soft</Badge>
                <Badge tone={tone} variant="solid">
                  solid
                </Badge>
                <Badge tone={tone} variant="outline">
                  outline
                </Badge>
              </div>
            ))}
          </div>
        </Card>

        {/* 04 中文字級階層 */}
        <Card num="04" title="中文字級階層（Inter + Noto Sans TC）">
          <div className="space-y-3">
            <div>
              <div className="text-2xl font-bold text-navy-900 dark:text-navy-100">
                專利答辯擬稿工作台
              </div>
              <TypeMeta>頁面主標 · text-2xl / bold / navy-900</TypeMeta>
            </div>
            <div>
              <div className="text-lg font-semibold text-slate-800 dark:text-slate-100">
                核駁理由分析結果
              </div>
              <TypeMeta>區塊標題 · text-lg / semibold</TypeMeta>
            </div>
            <div>
              <div className="text-sm font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                答辯策略 / STRATEGY
              </div>
              <TypeMeta>欄位標籤 · text-sm / tracking-wider / uppercase</TypeMeta>
            </div>
            <div>
              <div className="text-sm leading-7 text-slate-700 dark:text-slate-200">
                查系爭請求項所載之非均勻截面微流道結構，未見於引證一之揭露內容；引證一僅教示均勻截面之習知設計。
              </div>
              <TypeMeta>內文（公文）· text-sm / leading-7 — 行高放寬遷就中文密度</TypeMeta>
            </div>
            <div>
              <div className="text-xs text-slate-500 dark:text-slate-400">
                request: a1b2c3d4… · model: dify/qwen2.5:7b · tokens 5322
              </div>
              <TypeMeta>輔助資訊 · text-xs / slate-500</TypeMeta>
            </div>
          </div>
        </Card>

        {/* 05 按鈕 */}
        <Card num="05" title="按鈕（ui/button.jsx）">
          <div className="space-y-3">
            <Row label="variant">
              <Button variant="primary">分析 OA</Button>
              <Button variant="secondary">預覽 redaction</Button>
              <Button variant="link">檢視原文</Button>
            </Row>
            <Row label="size">
              <Button size="sm">sm</Button>
              <Button>default</Button>
              <Button size="xs" variant="secondary">
                xs
              </Button>
            </Row>
            <Row label="state">
              <Button disabled>匯出答辯稿（未簽核）</Button>
              <Button className="bg-emerald-600 text-white hover:bg-emerald-700">儲存</Button>
            </Row>
          </div>
        </Card>

        {/* 06 信任帶 chips */}
        <Card num="06" title="信任帶（AppShell trust band）">
          <div className="flex flex-wrap gap-2">
            <Badge tone="brand">🛡 資料遮罩：開啟</Badge>
            <Badge tone="neutral">🗄 資料保存於本地</Badge>
            <Badge tone="success">一般案件</Badge>
            <Badge tone="confidential">🔒 機密案 · Routing: Local LLM</Badge>
            <Badge tone="success">✓ 紀錄已驗證 · 29 筆</Badge>
          </div>
          <Hint>
            安全狀態常駐頂欄、不藏進設定頁；機密案整條變紫是「強制地端路由」的視覺證據。
          </Hint>
        </Card>

        {/* 07 核駁類型 */}
        <Card num="07" title="核駁類型徽章（DraftsPane）">
          <div className="flex flex-wrap gap-2">
            <span className="rounded bg-rose-100 px-2 py-0.5 font-mono text-xs text-rose-800 dark:bg-rose-900/40 dark:text-rose-300">
              102_novelty 新穎性
            </span>
            <span className="rounded bg-orange-100 px-2 py-0.5 font-mono text-xs text-orange-800 dark:bg-orange-900/40 dark:text-orange-300">
              103_obviousness 進步性
            </span>
            <span className="rounded bg-amber-100 px-2 py-0.5 font-mono text-xs text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
              112_indefiniteness 明確性
            </span>
            <span className="rounded bg-purple-100 px-2 py-0.5 font-mono text-xs text-purple-800 dark:bg-purple-900/40 dark:text-purple-300">
              101_subject_matter 標的適格
            </span>
          </div>
        </Card>

        {/* 08 簽核三態 */}
        <Card num="08" title="逐句簽核三態（DraftEditor · Q16）">
          <div className="space-y-2 text-sm">
            <SignoffLine
              n={1}
              cls="ai-line"
              pending
              text="Applicant respectfully traverses the rejection."
            />
            <SignoffLine n={2} cls="ai-line" accepted text="引證一未揭露非均勻截面微流道。">
              <span className="ml-2 inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
                <Check className="h-3.5 w-3.5" aria-hidden="true" /> AI 生成
              </span>
            </SignoffLine>
            <SignoffLine
              n={3}
              cls="attorney-line"
              accepted
              text="另查引證一之教示方向與系爭發明相反，具有教示遠離之情事。"
            >
              <span className="ml-2 inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
                <Check className="h-3.5 w-3.5" aria-hidden="true" /> 律師改寫
              </span>
            </SignoffLine>
            <SignoffLine n={4} cls="ai-line" excluded text="此段論述過於空泛，律師選擇排除。">
              <span className="ml-2 inline-flex items-center gap-1 text-xs text-rose-500 dark:text-rose-400">
                <X className="h-3.5 w-3.5" aria-hidden="true" /> 已排除
              </span>
            </SignoffLine>
          </div>
          <div className="mt-3 flex items-center gap-2 text-2xs text-slate-400 dark:text-slate-500">
            <span>快捷鍵：A 接受 · E 改寫 · X 排除 · U 撤銷</span>
            <span className="ml-auto inline-flex items-center gap-1 rounded border border-slate-200 px-1.5 py-0.5 dark:border-slate-700">
              <CheckCheck className="h-3 w-3" aria-hidden="true" /> 接受剩餘 N 句
            </span>
          </div>
        </Card>

        {/* 09 引用 pill */}
        <Card num="09" title="引用 pill（Q14 grounded citation）">
          <p className="text-sm leading-7 text-slate-700 dark:text-slate-200">
            The cited reference{' '}
            <button
              type="button"
              onClick={() => toast.success('正式版：點擊捲動右欄並高亮來源文獻卡')}
              className="mx-0.5 inline-block cursor-pointer rounded border border-navy-300 bg-navy-100 px-1.5 py-0.5 font-mono text-xs text-navy-800 transition-colors hover:bg-navy-200 dark:border-navy-700 dark:bg-navy-900/40 dark:text-navy-200"
            >
              [GROUNDED_REF_1]
            </button>{' '}
            does not teach a non-uniform cross-section, whereas{' '}
            <span className="mx-0.5 inline-block rounded border border-rose-300 bg-rose-100 px-1.5 py-0.5 font-mono text-xs text-rose-800 dark:border-rose-800 dark:bg-rose-900/40 dark:text-rose-300">
              CITATION_REMOVED
            </span>{' '}
            標記被 verifier 剝除的捏造引用。
          </p>
          <Hint>藍 pill 可點（跨欄連動）；紅 pill 是幻覺防線的可見證據，刻意不可互動。</Hint>
        </Card>

        {/* 10 驗證橫幅三態 */}
        <Card num="10" title="引證驗證橫幅三態（VerificationBanner · Q14）">
          <div className="space-y-2 text-xs">
            <BannerDemo
              tone="emerald"
              icon={<ShieldCheck className="h-4 w-4 shrink-0" aria-hidden="true" />}
              text="幻覺防線 · 2 個引用全部驗證通過 · grounded 2 · conf 93%"
            />
            <BannerDemo
              tone="rose"
              icon={<ShieldAlert className="h-4 w-4 shrink-0" aria-hidden="true" />}
              text="幻覺防線 · 已剝除 1 個查無實據的引用：[US9999999]"
            />
            <BannerDemo
              tone="slate"
              icon={<AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />}
              text="幻覺防線 · 無驗證資料（舊版後端回應）"
            />
          </div>
        </Card>

        {/* 11 DEGRADED */}
        <Card num="11" title="降級警示（DEGRADED · 不裝死原則）">
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>
              AI 引擎暫時無法連線，本結果由備援引擎產生（DEGRADED），僅供格式參考，不可作為法律分析依據。
            </span>
          </div>
          <Hint>降級結果絕不冒充真結果 — amber 警示 + audit row 同步帶 DEGRADED 標籤。</Hint>
        </Card>

        {/* 12 表單 */}
        <Card num="12" title="表單元素（InputPane）">
          <div className="space-y-3 text-sm">
            <div>
              <label className="mb-1 block text-xs text-slate-500 dark:text-slate-400">
                案件編號
              </label>
              <input
                defaultValue="CASE-2025-001"
                className="w-full rounded border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-navy-300 dark:border-slate-700 dark:bg-slate-900"
              />
            </div>
            <div className="rounded border-2 border-dashed border-slate-300 px-4 py-6 text-center text-xs text-slate-400 dark:border-slate-600 dark:text-slate-500">
              拖放 PDF / DOCX 到這裡，或 <span className="text-navy-600 underline dark:text-navy-300">瀏覽檔案</span>
              <div className="mt-1 text-2xs">PDF / DOCX · ≤ 30MB</div>
            </div>
            <label className="flex items-start gap-2 text-sm text-slate-700 dark:text-slate-200">
              <input type="checkbox" defaultChecked className="mt-0.5 h-4 w-4 rounded border-slate-300 dark:border-slate-600" />
              <span>我已逐項確認 / I have reviewed each item</span>
            </label>
          </div>
        </Card>

        {/* 13 Toast */}
        <Card num="13" title="Toast 通知（lib/toast.jsx）">
          <div className="flex flex-wrap gap-2">
            <Button size="xs" variant="secondary" onClick={() => toast.success('已匯出答辯稿（已簽核）')}>
              觸發 success
            </Button>
            <Button size="xs" variant="secondary" onClick={() => toast.error('匯出失敗：需律師簽核')}>
              觸發 error
            </Button>
          </div>
          <Hint>實際 toast 會出現在視窗右下角 — 按下去看真的。</Hint>
        </Card>

        {/* 14 進度條 + Skeleton */}
        <Card num="14" title="進度回饋（簽核進度 / 載入骨架）">
          <div className="space-y-3">
            <div>
              <div className="mb-1 flex justify-between text-2xs text-slate-400">
                <span>3/4 已決定 · 2 接受 · 1 排除</span>
                <span>75%</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
                <div className="h-full w-3/4 rounded-full bg-navy-500 dark:bg-navy-400" />
              </div>
            </div>
            <div className="space-y-2">
              <div className="h-3 w-2/3 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
              <div className="h-3 w-full animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
              <div className="h-3 w-1/2 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
            </div>
          </div>
        </Card>

        {/* 15 稽核表縮影 */}
        <Card num="15" title="稽核列縮影（AuditView · Q13）">
          <div className="mb-2 rounded border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300">
            ✓ 29 筆紀錄全部驗證通過，未發現竄改。
          </div>
          <table className="w-full text-left text-2xs">
            <thead className="text-slate-400 dark:text-slate-500">
              <tr>
                <th className="py-1 pr-2 font-medium">USER</th>
                <th className="py-1 pr-2 font-medium">ENDPOINT</th>
                <th className="py-1 pr-2 font-medium">模型</th>
                <th className="py-1 font-medium">政策</th>
              </tr>
            </thead>
            <tbody className="font-mono text-slate-600 dark:text-slate-300">
              <tr className="border-t dark:border-slate-700">
                <td className="py-1.5 pr-2">alice</td>
                <td className="py-1.5 pr-2">/v1/oa/analyze</td>
                <td className="py-1.5 pr-2">dify/qwen2.5:7b</td>
                <td className="py-1.5">
                  <Badge tone="success" className="px-1.5 py-0 text-2xs">authz ✓</Badge>{' '}
                  <Badge tone="success" className="px-1.5 py-0 text-2xs">quota ✓</Badge>
                </td>
              </tr>
              <tr className="border-t dark:border-slate-700">
                <td className="py-1.5 pr-2">carol</td>
                <td className="py-1.5 pr-2">/v1/oa/analyze</td>
                <td className="py-1.5 pr-2">—</td>
                <td className="py-1.5">
                  <Badge tone="error" className="px-1.5 py-0 text-2xs">authz ✕ 403</Badge>
                </td>
              </tr>
            </tbody>
          </table>
        </Card>

        {/* 16 服務四燈 + 行動 Header */}
        <Card num="16" title="服務狀態四燈 + 行動版頂欄縮影">
          <div className="mb-4 flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
            <span className="text-2xs">服務狀態</span>
            <Dot ok label="Gateway" />
            <Dot ok label="AI Engine" />
            <Dot ok label="digiRunner" />
            <Dot ok={false} label="Dify" />
          </div>
          <div className="overflow-hidden rounded-lg border dark:border-slate-700">
            <div className="flex items-center justify-between bg-navy-900 px-3 py-2 text-white dark:bg-navy-800">
              <span className="text-sm font-semibold">PatentMind AI</span>
              <span className="rounded bg-emerald-500/20 px-2 py-0.5 text-2xs text-emerald-300">
                ✓ 紀錄已驗證
              </span>
            </div>
            <div className="flex border-b text-center text-xs dark:border-slate-700">
              {['輸入', '草稿', '引證'].map((tab, i) => (
                <div
                  key={tab}
                  className={`flex-1 border-b-2 px-2 py-2 ${
                    i === 1
                      ? 'border-navy-600 font-medium text-navy-700 dark:text-navy-200'
                      : 'border-transparent text-slate-400'
                  }`}
                >
                  {tab}
                </div>
              ))}
            </div>
            <div className="px-3 py-4 text-2xs text-slate-400">（行動版單欄 + 頁籤切換）</div>
          </div>
        </Card>
      </main>

      <footer className="mx-auto mt-8 max-w-6xl text-center text-2xs text-slate-400 dark:text-slate-600">
        PatentMind Design System v1 · 與 docs/DESIGN_SYSTEM.md 對照 · 此頁不出現在正式導覽，僅供
        /design 直接訪問審稿
      </footer>
    </div>
  );
}

function Card({ num, title, children }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <h2 className="mb-4 flex items-baseline gap-2 text-sm font-semibold text-slate-800 dark:text-slate-100">
        <span className="font-mono text-xs text-amber-500">{num}</span>
        {title}
      </h2>
      {children}
    </section>
  );
}

function Hint({ children }) {
  return <p className="mt-3 text-2xs leading-relaxed text-slate-400 dark:text-slate-500">{children}</p>;
}

function TypeMeta({ children }) {
  return <div className="mt-0.5 font-mono text-2xs text-slate-400 dark:text-slate-500">{children}</div>;
}

function Row({ label, children }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <code className="w-16 shrink-0 font-mono text-2xs text-slate-400">{label}</code>
      {children}
    </div>
  );
}

function SignoffLine({ n, cls, text, pending, accepted, excluded, children }) {
  return (
    <div
      className={`group -mx-1 flex items-start gap-2 rounded px-1 py-0.5 ${
        pending ? 'border-l-2 border-amber-300 dark:border-amber-600' : 'border-l-2 border-transparent'
      }`}
    >
      <div className="w-5 pt-1 text-xs tabular-nums text-slate-400">{n}.</div>
      <div className="min-w-0 flex-1">
        <span
          className={`${cls} px-1 leading-7 ${
            excluded ? 'text-slate-400 line-through decoration-rose-400/60 dark:text-slate-500' : ''
          }`}
        >
          {text}
        </span>
        {children}
      </div>
      <div className="flex shrink-0 gap-1 pt-0.5 opacity-60">
        {!accepted && !excluded && (
          <ActionIcon cls="text-emerald-700 dark:text-emerald-400">
            <Check className="h-3.5 w-3.5" aria-hidden="true" />
          </ActionIcon>
        )}
        <ActionIcon cls="text-slate-600 dark:text-slate-300">
          <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
        </ActionIcon>
        {!excluded && (
          <ActionIcon cls="text-rose-600 dark:text-rose-400">
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </ActionIcon>
        )}
        {(accepted || excluded) && (
          <ActionIcon cls="text-slate-500 dark:text-slate-400">
            <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
          </ActionIcon>
        )}
      </div>
    </div>
  );
}

function ActionIcon({ cls, children }) {
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-1 text-xs ${cls}`}>{children}</span>
  );
}

function BannerDemo({ tone, icon, text }) {
  const cls = {
    emerald:
      'border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300',
    rose: 'border-rose-300 dark:border-rose-800 bg-rose-50 dark:bg-rose-950/40 text-rose-800 dark:text-rose-300',
    slate:
      'border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-800/50 text-slate-600 dark:text-slate-300',
  }[tone];
  return (
    <div className={`flex items-center gap-2 rounded-md border px-3 py-2 ${cls}`}>
      {icon}
      <span className="font-medium">{text}</span>
    </div>
  );
}

function Dot({ ok, label }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className={`h-2 w-2 rounded-full ${ok ? 'bg-emerald-500' : 'bg-slate-300 dark:bg-slate-600'}`} />
      {label}
    </span>
  );
}
