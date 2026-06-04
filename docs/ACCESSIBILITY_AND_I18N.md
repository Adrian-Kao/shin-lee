# Accessibility, Internationalisation & CJK Typography — PatentMind AI (2026-06-05)

> Author: a11y / i18n research agent. Audience: the frontend redesign sprint
> picking up after `docs/UX_RESEARCH.md` + `docs/PRODUCT_STRATEGY.md` §5+§6.
> Scope: the deep-dive for accessibility, internationalisation, Chinese (zh-TW)
> typography, English/US bilingual UX, mobile/tablet behaviour, and the
> testing protocol that gates them. **Read-only research — no frontend code
> touched.** The current `i18n.js` resource bundle (`zh-TW` default, English
> fallback, partial component coverage) is the starting point, not the
> destination.

This is a sibling document to `UX_RESEARCH.md` (what to build) and
`PRODUCT_STRATEGY.md` (why it matters commercially). It exists because TW
patent firms procuring legal AI in 2026 sit at the intersection of three
high-stakes requirements that generic SaaS a11y guides handle badly:

1. **Regulatory.** ADA Title II's WCAG 2.1 AA web rule landed in April 2024;
   the DOJ's compliance deadlines for state-and-local-government entities
   ran through 2026 and 2027, and downstream procurement clauses already
   reference WCAG 2.2 AA as the new floor ([DOJ web rule](https://www.ada.gov/resources/2024-03-08-web-rule/), [Level Access WCAG 2.2 guide](https://www.levelaccess.com/blog/wcag-2-2-aa-summary-and-checklist-for-website-owners/)).
   A TW patent firm prosecuting for a US state university client inherits
   those clauses.
2. **Demographic.** Median TW patent-attorney age sits in the 45-55 band —
   the population that needs ≥16 px body text, dark-mode tolerance, and
   keyboard shortcuts that don't collide with 微軟新注音 / 嘸蝦米 IME modal
   state.
3. **Linguistic.** Drafts mix Traditional Chinese narrative with English
   claim text, case IDs in Latin (`CASE-2025-001`), patent numbers in
   mixed-script (`TW202617461A`), and the 民國 calendar in formal letters.
   The font stack, line-height, punctuation rules and number formatters
   each have a TW-correct answer different from the generic Notion-style
   defaults.

The frontend agent should be able to open this doc alongside
`frontend/tailwind.config.js` and `frontend/src/lib/i18n.js` and ship
WCAG-2.2-AA components without further research.

---

## 1. WCAG 2.2 AA conformance plan

### 1.1 Conformance scope per surface

Not every screen needs the same bar. The redesign should explicitly
target the following levels (procurement asks for this in writing):

| Surface | Target | Reasoning |
|---|---|---|
| Login + landing | WCAG 2.2 AA | First-impression screens; ADA Title II floor for outside-counsel inheriting state-client work. |
| Analyze 3-pane (Input / Drafts / References) | WCAG 2.2 AA | Production work surface. |
| ClaimTree | WCAG 2.2 AA | Tree role + roving tabindex; AAA for focus appearance because it's keyboard-heavy. |
| DraftEditor (line-level provenance) | WCAG 2.2 AA + 1.4.6 AAA contrast | Citation pills must be readable for low-vision attorneys reviewing late at night. |
| AuditView + chain-verify | **WCAG 2.2 AAA where reachable** | This is the legally-significant surface. AAA contrast (7:1), AAA focus appearance (2.4.13), AAA target size (2.5.5 — 44×44). |
| Sign-off / final-submit modals | **WCAG 2.2 AAA** | Irreversible legal action. AAA error prevention (3.3.6) — explicit confirmation step. |
| Settings, profile, admin (Phase 4) | WCAG 2.2 AA | Standard. |
| Print stylesheet (PDF export) | WCAG 2.2 AA for screen-equivalent | Print itself isn't bound by WCAG, but the on-screen *Print Preview* is. |

WCAG 2.2 added nine success criteria over 2.1, of which the AA-level ones
that change our default component design are: **2.4.11 Focus Not Obscured
(Minimum)**, **2.5.7 Dragging Movements**, **2.5.8 Target Size (Minimum)**,
**3.2.6 Consistent Help**, **3.3.7 Redundant Entry**, **3.3.8 Accessible
Authentication (Minimum)** ([W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/),
[TestParty 2.2 implementation guide](https://testparty.ai/blog/wcag-22-new-success-criteria)).
The four most consequential for PatentMind are detailed below.

### 1.2 Colour-contrast audit of the navy palette

Strategy §5.2 froze the brand on `#1e3a8a` (Tailwind `blue-900`). Every
semantic-token pair needs verification against WCAG 2.2 **§1.4.3 Contrast
(Minimum)** for text and **§1.4.11 Non-text Contrast** for UI components
including status badges, focus rings, and form borders.

| Pair | Use | Ratio | Verdict |
|---|---|---|---|
| `#0f172a` ink on `#ffffff` surface | Body, headings | 19.6:1 | AAA |
| `#0f172a` on `#f8fafc` canvas | Body | 18.3:1 | AAA |
| `#64748b` ink-muted on `#ffffff` | Secondary text | 4.79:1 | AA body / fail AA Large |
| `#94a3b8` (slate-400) on `#ffffff` | **AVOID** | 2.84:1 | Fails everything; current code uses this for placeholders — replace with `#64748b`. |
| `#ffffff` on `#1e3a8a` brand | Primary CTA label | 10.3:1 | AAA |
| `#b45309` amber-700 on `#fef3c7` warn-bg | Deadline urgency chips | 4.55:1 | AA body / fail AA Large — add an icon glyph so meaning isn't colour-only. |
| `#047857` emerald-700 on `#ffffff` | "Verified" chip | 4.83:1 | AA body |
| `#b91c1c` red-700 on `#ffffff` | Danger chip | 5.94:1 | AA |
| `#1e3a8a` brand on `#eff6ff` info-bg | Info pill | 9.4:1 | AAA |

**Dark-mode pair** (must ship; long-session fatigue concern, §2):

| Pair | Use | Ratio |
|---|---|---|
| `#f1f5f9` on `#0f172a` | Body in dark | 16.2:1 (AAA) |
| `#94a3b8` on `#0f172a` | Muted in dark | 5.31:1 (AA) |
| `#60a5fa` blue-400 on `#0f172a` | CTA in dark | 7.16:1 (AAA) |
| `#fbbf24` amber-400 on `#0f172a` | Deadline in dark | 9.85:1 (AAA) |

**§1.4.11 non-text** rule: focus rings, form borders, status-dot
indicators, the unfocused-vs-focused delta of a button — all need ≥3:1
against their adjacent colour. The `#1e3a8a` ring on a `#ffffff` button
passes; an `#e2e8f0` border on `#ffffff` does NOT (1.36:1) and must be
replaced with `#cbd5e1` slate-300 (1.91:1 — still fails, so use
`#94a3b8` slate-400 at 2.84:1 — still fails). The honest answer is form
borders must be at least `#64748b` slate-500 (4.79:1) for default state
or accompanied by a label that survives without the border being visible
([Deque WCAG 2.2 examples](https://dequeuniversity.com/resources/wcag-2.2/)).

### 1.3 Focus indicator spec

WCAG 2.2 **§2.4.13 Focus Appearance (AAA)** is the spec we target across
AuditView and Sign-off; AA elsewhere. Rules:

- Minimum **3:1 contrast** between focused and unfocused states (or
  between the focus ring and adjacent colour).
- Minimum **2 CSS px solid** for the focus indicator (or equivalent area).
- **Never `outline: none` without a replacement.** Tailwind's preflight
  removes the default ring; the redesign must replace it project-wide
  with `focus-visible:ring-2 focus-visible:ring-blue-900
  focus-visible:ring-offset-2`. The current code does this on `Login.jsx`
  but only inconsistently elsewhere — every interactive element must be
  audited.
- **§2.4.11 Focus Not Obscured (Minimum) AA**: sticky headers, sticky
  toolbars, and the trust-bar must not cover the focused element.
  Implementation: when focus lands on an element under a sticky bar,
  `scroll-padding-top: 4rem` on the scroll container moves it into view.

### 1.4 Skip-links + landmark roles

Add to App shell, in this DOM order:

1. `<a href="#main" class="sr-only focus:not-sr-only ...">Skip to main</a>`
2. `<a href="#sidebar">Skip to navigation</a>` (when sidebar present)
3. `<header role="banner">` (TrustBar + AppHeader)
4. `<nav role="navigation" aria-label="Primary">` (left rail)
5. `<main id="main" role="main">` (the 3-pane Analyze grid)
6. `<aside role="complementary" aria-label="Audit chip">` (footer chip)
7. `<footer role="contentinfo">`

Each Analyze pane gets `role="region"` + `aria-label="OA input"` /
`"Drafts"` / `"References"` so a screen reader user can land on a pane
via the rotor (VO) or the Region list (NVDA).

### 1.5 Keyboard navigation map

The redesign should ship with this explicit tab order (see §3 for the
detailed keymap and shortcut palette).

```
Analyze 3-pane tab order:
┌──────────────────────────────────────────────────────────────┐
│ [1] Skip-link → [2] Lang switcher → [3] Role badge → [4] CmdK│
├─────────────┬──────────────────────────┬─────────────────────┤
│ [5] Tree    │ [9] Draft editor body    │ [13] Ref filter     │
│ root        │ (one tab-stop per line   │ [14] Ref list       │
│ [6] Tree    │  for keyboard line-edit) │ [15] Pop-out btn    │
│ filter      │ [10] Verify btn          │                     │
│ [7] Tree    │ [11] Sign-off btn        │                     │
│ search box  │ [12] Export USPTO btn    │                     │
│ [8] (roving │                          │                     │
│  inside)    │                          │                     │
├─────────────┴──────────────────────────┴─────────────────────┤
│ [16] Pinned shortcut bar (dismissible)                       │
└──────────────────────────────────────────────────────────────┘
```

`ClaimTree` uses **roving tabindex** (one tab-stop on the tree root,
arrow-keys to navigate within) per WAI-ARIA Authoring Practices Tree
pattern — NOT one tab-stop per node, which is unusable with 30+ claims.

### 1.6 Screen-reader testing matrix

WebAIM SR-User-Survey #10 ([2025 data](https://webaim.org/projects/screenreadersurvey10/))
puts NVDA at 65.6%, JAWS at 60.5% (respondents use multiple); on mobile
VoiceOver is 70.6%. Enterprise corp environments skew JAWS for legacy
Office-Add-in compatibility ([accessibility-test.org NVDA vs JAWS 2025](https://accessibility-test.org/blog/development/screen-readers/nvda-vs-jaws-vs-voiceover-2025-screen-reader-comparison/)).

Certify against this matrix; non-certified configurations are
"best-effort":

| Combo | Tier | Why |
|---|---|---|
| NVDA + Firefox (Windows) | **Certified** | Largest TW desktop SR base. |
| JAWS + Chrome (Windows) | **Certified** | Enterprise procurement floor. |
| VoiceOver + Safari (macOS) | **Certified** | Partner-on-iPad path. |
| VoiceOver + Safari (iOS) | Best-effort | Tablet review-only mode. |
| TalkBack + Chrome (Android) | Best-effort | Mobile read-only. |
| Narrator + Edge (Windows) | Untested | Skip in v1. |

Each release runs a 30-minute smoke pass on Certified rows. Quarterly
recruited-user review (§10) covers JAWS-on-Edge and TalkBack edge cases.

### 1.7 Automated tooling — CI gates

- **`@axe-core/react`** in dev mode, console-warns on every render.
- **`@axe-core/playwright`** invoked from `frontend/tests/e2e/smoke.spec.js`
  on every PR; threshold is **zero serious or critical** violations.
  Allowed-list (`moderate` is warning-only initially) is checked in to
  `frontend/.axerc.json`.
- **Storybook a11y addon** (`@storybook/addon-a11y`) on every component
  story; CI runs `test-storybook --browsers=chromium` with
  `parameters.a11y.test = 'error'` so a story with a violation fails
  the build ([Storybook a11y docs](https://storybook.js.org/docs/writing-tests/accessibility-testing)).
- **Pa11y** for marketing/landing URLs only (fast smoke).
- **Lighthouse CI** with accessibility score ≥ 95 gating PRs to `main`.

Together these catch roughly the 57% of WCAG issues automatable tools
detect ([axe-core dependents npm](https://www.npmjs.com/package/axe-core?activeTab=dependents),
[Accesify pipeline guide](https://www.accesify.io/blog/accessibility-testing-automation-axe-pa11y-lighthouse-ci/)).
The remainder go in the quarterly manual review (§10).

### 1.8 WCAG 2.2 new criteria — what changes for us

- **2.4.11 Focus Not Obscured (AA)**: sticky `TrustBar` + sticky pane
  headers cannot cover focused element → use `scroll-padding-top`.
- **2.5.7 Dragging Movements (AA)**: the planned drag-drop OA upload
  (`OAUpload.jsx`) must offer a single-pointer alternative (click → file
  picker). Already does; document it.
- **2.5.8 Target Size (Minimum, AA)**: 24×24 CSS px minimum, with
  spacing exception. Today's icon-only buttons in the header sit at
  16×16; redesign all to 24×24 minimum, 44×44 for primary touch zones
  on tablet (§8).
- **3.2.6 Consistent Help (A)**: the help icon/contact path appears in
  the same relative location on every page — anchor it bottom-right of
  the footer, always.
- **3.3.7 Redundant Entry (A)**: when a multi-step form re-asks for
  data the user already provided (Sign-off flow re-asks for case_id),
  pre-fill it.
- **3.3.8 Accessible Authentication (Minimum, AA)**: when Q12 OIDC ships,
  don't gate login on a cognitive function test (typing a CAPTCHA, copying
  a code from another app where the same app could deep-link). Magic-link
  email auth is compliant; SMS-OTP via a second device is too.

---

## 2. Patent-attorney-specific a11y considerations

Generic a11y guides target consumer SaaS. Patent attorneys' working
context shifts the defaults:

### 2.1 Aging-eye optics

UX research §3 references AIPLA + TW Patent Attorney Bar demographic
data; the median TW patent attorney is 45-55. Implications:

- **Default body text ≥ 16 px**, never 14. Current Tailwind defaults to
  16; verify nothing demotes (`text-sm` = 14 px, `text-xs` = 12 px are
  ONLY allowed for secondary metadata never primary content).
- **Default density = `comfortable`.** Provide a `compact` toggle in
  Settings; don't make it default (§2.2 below).
- **System font-scale respect.** Use `rem` everywhere, never `px` for
  text. Test at 200% zoom — the 3-pane layout must reflow to tabs or
  vertical stack without horizontal scroll (WCAG 1.4.10 Reflow).
- **Line-height 1.6 for body, 1.45 for headings** (§5 CJK rationale).
- **Minimum tap target on hovered icon buttons: 32×32** even on desktop
  — a partner with mild Parkinson's misses 24×24 buttons.

### 2.2 High-information-density tolerance

Counter-intuitive but well-documented: legal-practice users want MORE
on screen than typical SaaS, not less. UX research §2.1-2.6 shows
Patlytics / Solve / Harvey all ship dense layouts. The bottom-bar
"density: comfortable / compact / cosy" switch should:

- Default to `comfortable` (matches §2.1 above).
- Offer `compact` for users who explicitly want it — 32 px row height in
  ClaimTree vs 40 px, `p-3` cards vs `p-4`.
- Persist preference per-user (it's identity, not just session).
- Never go below 14 px body even in `compact` (still WCAG-friendly).

### 2.3 Long-session fatigue

Office Action response drafts run 30-90 minutes of focused work
(`UX_RESEARCH.md` §3). Mitigation:

- **Dark mode** — ship at launch, not as Phase 2. Use the palette in
  §1.2. Switch via system preference (`prefers-color-scheme`) and an
  explicit toggle that persists.
- **`prefers-reduced-motion`** — every animation respects it. The
  ClaimTree expand/collapse, the citation hover-preview slide-in, the
  page transitions — all gated by
  `@media (prefers-reduced-motion: reduce) { ... animation: none; }`.
- **No autoplay video / no animated loaders that pulse** — use a steady
  spinner or skeleton, not a heartbeat.
- **Colour-temperature**: dark mode uses cooler greys (avoid pure black
  `#000000`; use `#0f172a` slate-900 — softer at night).
- **Auto-save indicator quiet** — toast for save success appears for 2 s,
  not 5; reduces dopamine-hit fatigue.

### 2.4 Colour-blindness — never colour-alone

~8% of male attorneys have some form of CVD (deuteranomaly most
commonly). Every status indicator in PatentMind today uses colour as
the primary channel. Replace with **colour + icon + textual label**:

| State | Colour | Icon (lucide) | Label |
|---|---|---|---|
| Verified | emerald-700 | `<CheckCircle2>` | "Verified" |
| Flagged | amber-700 | `<AlertTriangle>` | "Review" |
| Failed | red-700 | `<XCircle>` | "Failed" |
| Pending | slate-500 | `<Clock>` | "Pending" |
| Confidential | blue-900 | `<Lock>` | "On-prem" |

Same rule for ClaimTree colouring (red=rejected, amber=cascade,
green=clean) — every node also carries a glyph and an `aria-label`
that names the state in words.

### 2.5 RSI / keyboard-everywhere

Attorneys type for a living; mouse-RSI is real. The redesign must reach
"can be operated by keyboard only" for every primary workflow:

- Login, Analyze, ClaimTree navigation, citation hover-preview, draft
  edit, verify, sign-off, audit-chain verify, language switch.
- The Cmd-K palette is the primary entry; see §3.3 below.

### 2.6 Multi-monitor reality

Many TW partners run dual 27" monitors (2560 × 1440 each). Implications:

- **Don't `max-w-7xl` cap aggressively.** The 3-pane Analyze must use
  the full width on `≥1920 px`; only the Login + Settings screens cap
  at 1280 px for readability.
- **Pop-out reference viewer** (UX research §4.4 wishlist) goes on
  monitor 2. Implement as `window.open` with `noopener` to a
  `/refs/:id?popout=1` route that strips the shell chrome.
- **Don't anchor modals to viewport centre when the viewport is 2560
  wide** — modals max-w-2xl + centered is fine.

---

## 3. Keyboard navigation spec

### 3.1 Per-view tab order

| View | First focus | Tab order summary |
|---|---|---|
| Login | username field | username → password → role-picker → submit → "forgot" link |
| Analyze 3-pane | Cmd-K hint | CmdK → ClaimTree (roving) → Drafts body (line-roving) → Refs filter → Pop-out → Footer chip |
| AuditView | "Verify now" button | Verify → Filter chips → Row 1 (roving down) → Hash-detail expand → Footer chip |
| DraftEditor | Last unsigned line | Line-roving (↑/↓), `Enter` enters edit-mode, `Esc` exits, `Shift-Enter` line-break in edit-mode |
| Sign-off modal | "Confirm" only after pre-check passes | Pre-check → Confirm → Cancel; focus-trap; `Esc` cancels |

### 3.2 Roving tabindex within ClaimTree

Pattern: WAI-ARIA Authoring Practices `tree` role.
- Tree root: `tabindex=0`, `role="tree"`, `aria-label="Claim dependency tree"`.
- Each node: `role="treeitem"`, `aria-level=N`, `aria-expanded=true/false`,
  `aria-selected=true/false`, `tabindex=-1` unless current.
- ↑/↓ moves focus between visible siblings; ←/→ collapses/expands;
  Home/End jump to first/last; `Enter` or `Space` selects (scrolls
  Drafts + References to that claim).
- Type-ahead: pressing a digit jumps to claim N; pressing letters jumps
  to next node whose claim-text starts with that string.

### 3.3 Cmd-K palette (Harvey-baseline)

The 2026 baseline ([Harvey getting started](https://help.harvey.ai/articles/getting-started-with-harvey)).
Spec:

- **Trigger**: `Cmd/Ctrl+K` (never Alt — TW IME conflict, §3.4).
- **Fallback trigger**: `/` from any non-input element (Linear pattern).
- **Dismiss**: `Esc` (always) or click outside.
- **Tabs inside the palette**: Cases, Drafts, Audit rows, Refs, Commands.
- **Top result auto-selected**; `Enter` activates; ↑/↓ navigates;
  `Tab` switches palette tabs.

### 3.4 IME-safe modifier policy

Taiwanese attorneys typing zh-TW use 微軟新注音, 嘸蝦米, or 自然輸入法.
All three reserve **Alt** for candidate-window navigation and IME
toggles. **Never bind Alt as the primary shortcut modifier.** Use Cmd
on macOS, Ctrl on Windows.

When a shortcut is unavoidably Alt (e.g. browser default `Alt+←` =
back), document it and pick a non-Alt PatentMind alternative. The
shortcut bar (§3.6) shows the current platform's keys only.

### 3.5 GitHub/Linear-style g-then-letter shortcuts

For mouse-free navigation:

- `g a` → Analyze
- `g u` → Audit
- `g c` → Cases (Phase 4)
- `g s` → Settings
- `g h` → Help
- `?` → open shortcut cheatsheet
- `Esc` → close any overlay
- `j` / `k` → next / prev row in tables
- `/` → focus filter input

Specific patent-tool shortcuts:

- `J` (capital) → jump to next citation in DraftEditor
- `K` (capital) → jump to previous citation
- `Cmd/Ctrl+Shift+E` → expand all reasoning panels in Drafts
- `Cmd/Ctrl+Enter` → run Verify on current draft
- `Cmd/Ctrl+Shift+S` → open sign-off modal (irreversible action gated
  behind an explicit Shift)
- `Cmd/Ctrl+.` → open the linked audit row of the current draft
- `Cmd/Ctrl+1/2/3` → focus Input / Drafts / References pane respectively
- `Cmd/Ctrl+,` → settings (matches macOS convention)

### 3.6 Pinned shortcut reference

Bottom-bar hint, dismissible per-session (re-shows on next login until
explicitly muted in Settings):

```
ClaimTree: ↑/↓ Tab to navigate    Cmd+K Search    J/K Jump citation    ? More
```

Shows platform-correct modifier (`⌘` on macOS, `Ctrl` on Win/Linux).
Detect via `navigator.userAgentData.platform` with `userAgent` fallback.

### 3.7 Shortcut conflict avoidance

Vetted against macOS, Windows, Chrome/Edge/Safari/Firefox defaults:

| Shortcut | Conflict | Mitigation |
|---|---|---|
| `Cmd+K` | Slack message-clear | Different app context; safe |
| `Cmd+J` | Chrome downloads | Documented conflict; our `J` (lowercase) is only active in DraftEditor, no modifier |
| `Cmd+.` | macOS stop | Off-by-default; require enabling in Settings on macOS |
| `Cmd+/` | Linear, VSCode comment toggle | Use `Cmd+?` instead |
| `Cmd+Enter` | Submit form (browser default) | Re-use intentionally for Verify (the "submit" of the workflow) |
| `Alt+anything` | TW IME | NEVER bind |

---

## 4. Screen-reader UX

### 4.1 Live regions

Three live regions, each with a specific role:

- `<div aria-live="polite" aria-atomic="true">` for non-urgent updates:
  "Draft saved", "Cached response loaded".
- `<div aria-live="assertive" aria-atomic="true">` for urgent: "Rate
  limit reached", "Verifier flagged 1 citation".
- `<div role="status">` for transient progress: "Verifying... 3/7
  citations checked".

Specific announcements (from `i18n.js` keys):

| Trigger | Politeness | Announcement |
|---|---|---|
| Verify completes ok | polite | "Verifier ran. 3 citations confirmed." |
| Verify finds mismatch | assertive | "1 citation flagged. Review required." |
| Sign-off succeeds | polite | "Draft signed by {{user}} at {{time}}." |
| Audit chain verify ok | polite | "Chain verified. {{rows}} rows passed." |
| Audit chain fail | assertive | "Chain mismatch at row {{n}}. Contact ops." |
| Redaction applied | polite | "{{count}} entities masked before LLM call." |
| Confidential auto-route | polite | "Routed to on-prem LLM (case ends in -CONF)." |

### 4.2 ClaimTree semantics

(See §3.2 for roving tabindex.) Additional roles:

- Tree root: `role="tree"`, `aria-multiselectable="false"`,
  `aria-label="Claim dependency tree, {{count}} claims"`.
- Each item: `role="treeitem"`, `aria-level`, `aria-posinset`,
  `aria-setsize`, `aria-expanded` (if has children), `aria-selected`.
- Status annotation goes in `aria-describedby`: "rejected under
  § 22-2", "cascade risk", "clean".

### 4.3 DraftEditor citation pills

The citation chip is a focusable link. ARIA:

- `role="link"` (it navigates to a reference)
- `aria-label="Cite: US 7,654,321, column 4 lines 12-18. Press Enter to
  open in references pane."`
- Hover-preview also opens on focus (`focus-visible`) — not hover-only,
  per WCAG 2.1.1 Keyboard.
- The preview tooltip is `role="tooltip"`, `id="tip-{{n}}"`,
  `aria-describedby` linked from the pill.

### 4.4 Toast vs banner

- **Toast** (transient, dismissible, status-message): `role="status"`,
  auto-dismisses 5 s, persists until SR finishes reading. Used for
  "Saved", "Copied".
- **Banner** (persistent until acknowledged, system-level): `role="alert"`
  for danger; `role="status"` for info. Used for "Backend down", "Token
  quota 80% used".

### 4.5 Modal focus trap + restoration

Every modal:
- Traps focus inside (`focus-trap-react` or equivalent).
- First focusable element is the destructive-action button NOT the
  cancel — partner reviewing a sign-off should land on Confirm, not
  Cancel; mitigates accidental dismissal via Esc by also requiring a
  second Esc to confirm dismissal.
- On close, restores focus to the trigger element.
- `Esc` closes (announcing "Modal closed" via polite live region).

### 4.6 Skip-link + landmark map

See §1.4. The skip-link is hidden via `sr-only` until focused
(`focus:not-sr-only`), then renders as a high-contrast pill at the
top-left.

---

## 5. Chinese (zh-TW) typography depth

This section is where TW patent-tool UX is won or lost. The defaults
the rest of the world uses are wrong for Traditional Chinese in three
specific ways: font selection, line-height, and CJK-Latin spacing.

### 5.1 Font stack — the TW-correct answer

```css
font-family:
  "Inter",                      /* Latin first, prevents Chinese-glyph fallback artifacts in case IDs */
  "Noto Sans TC",               /* primary zh-TW screen face */
  "PingFang TC",                /* macOS / iOS native; ships with system */
  "Microsoft JhengHei",         /* Windows native; "微軟正黑體" */
  -apple-system, BlinkMacSystemFont,
  "Segoe UI", Roboto, sans-serif;
```

**Do NOT use:**

- `"Microsoft YaHei"` — that's Simplified Chinese (微軟雅黑). Renders
  Simplified glyph variants of characters that have different
  Traditional forms (e.g. 「裏」 vs 「裡」, 「峯」 vs 「峰」). TW users
  notice instantly.
- `"Heiti TC"` — deprecated by Apple in 2015; falls back to PingFang
  anyway, but listing it shows you're working from a 2014 stack
  ([az-loc CJK font guide](https://www.az-loc.com/best-fonts-for-chinese-japanese-korean-websites/)).
- `"SimSun"` / `"NSimSun"` — Simplified Chinese serif; only acceptable
  in legacy print and never for screen.
- `"Microsoft YaHei UI"` — same as YaHei, plus the "UI" variant has
  worse hinting at small sizes than PingFang TC.
- Pure-Latin fonts as `font-family` start without a Chinese fallback —
  causes characters to render in browser-default serif, which on
  Windows is `SimSun` (wrong: Simplified).

**Why Inter first**: when a case ID like `CASE-2025-001-CONF` is
rendered mid-zh-TW paragraph, putting Inter first ensures the digits
and hyphens render in Inter's tabular-friendly Latin glyphs rather than
falling into Noto Sans TC's Latin set (which is correct but visually
heavier). The CJK characters in the same span fall through to Noto Sans
TC. ([Noto Sans TC Google Fonts](https://fonts.google.com/noto/specimen/Noto+Sans+TC),
[justfont 在網頁上呈現最高品質的字體](https://webfont.justfont.com/fonts)).

### 5.2 Line-height — 1.6 body, 1.45 headings

Chinese characters have no ascenders or descenders. Western typography
uses 1.4-1.5 for body to give Latin glyphs visual breathing room around
the descenders and ascenders that already do half the spacing work. CJK
glyphs are square-bodied — without the same x-height structure they
visually crowd at 1.4 even though the math says it's fine.

The TW typography community converges on **1.6 - 1.75 for body** and
**1.4-1.5 for headings** ([justfont 排版間距](https://learn.justfont.com/pocketbook/applications/layout-applications/spacings),
[黑暗執行緒 字型大小與行高](https://blog.darkthread.net/blog/font-size-n-line-height/)).
Implementation:

```css
:root {
  --leading-body: 1.6;
  --leading-heading: 1.45;
  --leading-claim-text: 1.7;   /* legal text needs MORE breathing room */
}
```

Tailwind: extend `lineHeight` in `tailwind.config.js` with
`'cjk-body': '1.6', 'cjk-tight': '1.45', 'claim': '1.7'`.

### 5.3 Mixed CJK + Latin spacing — the Pangu debate

This is the typography decision most likely to age badly if you choose
wrong.

The cosmetic case: a quarter-em space between CJK and Latin glyphs
(e.g. between 「請求項」 and 「12」 in 「請求項 12 被駁回」) is what
classic TW print typography expects. Vue's docs auto-insert it; Notion
doesn't; Linear has no policy.

Three implementation strategies:

1. **`pangu.js` server-side or build-time** ([vinta/pangu.space](https://github.com/vinta/pangu.space))
   — inserts actual U+0020 spaces into the string. Visually correct but
   **corrupts copy-paste fidelity** — if a user pastes their draft into
   USPTO Patent Center, the auto-inserted spaces become text artifacts.
   **Hard veto for patent drafts.**

2. **CSS `text-autospace`** — modern browsers (Chrome 120+ behind flag,
   shipping in 2025 per [Chrome i18n features blog](https://developer.chrome.com/blog/css-i18n-features)).
   Renders the spacing visually without modifying the text. **This is
   the right answer when browser support lands** ([MDN text-autospace](https://developer.mozilla.org/en-US/docs/Web/CSS/text-autospace)).
   Use behind `@supports` query; fall back to no spacing.

3. **No spacing** — fastest, no-risk default. Loses cosmetic polish in
   chrome but **wins on copy fidelity**.

**Recommendation**: option 3 globally (default), opt in to option 2
behind `@supports (text-autospace: ideograph-alpha)` for chrome UI text
(labels, tooltips, ClaimTree) where copy fidelity doesn't matter. **Never
in draft content or claim text** — copy fidelity is sacred for legal
documents.

The same logic applies to `text-spacing-trim: trim-start` — useful for
chrome UI labels, never inside draft content.

### 5.4 Punctuation — full-width vs half-width

| Context | Convention |
|---|---|
| zh-TW prose / UI labels | Full-width 「，。：；！？」 — what TW print uses |
| Claim text in zh-TW | Full-width — TIPO submissions are full-width |
| Case ID, patent number | Half-width — these are Latin tokens |
| Quoted English inside zh-TW | Half-width English punctuation around the English span, full-width zh punctuation around it: 該技術為「Office Action」（即「審查意見書」）。 |
| Bullet symbols | `．` (U+FF0E full-width period) NOT `·` (middle dot — that's Japanese convention) |
| Quotation marks | `「」` for outer, `『』` for nested (TW convention) — NOT `""` or 『「'』 |

When showing examiner-quoted English mid-zh-TW, wrap the English in
`<span lang="en">` so screen readers switch voice correctly (WCAG 3.1.2
Language of Parts) and `text-autospace` (if enabled, §5.3) correctly
spaces around it.

### 5.5 Tabular numerals — essential for IDs

Patent IDs (`TW202617461A`), case IDs (`CASE-2025-001`), audit hashes
(`0x4a3b…`), timestamps in the audit table — all must use
**proportional-tnum** so a stack of IDs aligns visually:

```css
.id, .hash, .timestamp, .audit-table td {
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1;
}
```

Tailwind has `font-variant-numeric` utilities; the redesign should
extend with `tabular-nums` applied to every monospace usage and every
table column showing numbers ([MDN font-variant-numeric](https://developer.mozilla.org/en-US/docs/Web/CSS/font-variant-numeric),
[Tailwind font-variant-numeric](https://tailwindcss.com/docs/font-variant-numeric)).
Inter (our primary Latin face) supports `tnum`; Noto Sans TC does too.

### 5.6 Vertical text — `writing-mode: vertical-rl`

TW formal court letters and 司法院 published opinions were historically
vertical; the government converted to horizontal in 2005 ([Wikipedia
horizontal/vertical CJK](https://en.wikipedia.org/wiki/Horizontal_and_vertical_writing_in_East_Asian_scripts)).
TIPO and TW courts now publish horizontal. Patent submissions are
horizontal.

**Recommendation**: do NOT support vertical for screen. For print, allow
a `vertical-rl` mode behind a hidden setting only if a specific firm
requests it for the printed receipt of formal letters — this is a P3
nice-to-have, not a launch requirement. The `writing-mode: vertical-rl`
CSS works, but Latin embedded in vertical CJK requires
`text-orientation: upright` for short tokens and `text-orientation: mixed`
for longer Latin spans ([W3C styling vertical CJK](https://www.w3.org/International/articles/vertical-text/)).
Skip until a customer asks.

### 5.7 Number formatting — TW conventions

Use `Intl.NumberFormat('zh-Hant-TW')`. Defaults:

- Thousands separator: `,` (1,234) — same as en-US. TW uses both `,` and
  no-separator in different contexts; `,` is safer for tabular data.
- Decimal separator: `.` (1.234).
- Currency: `Intl.NumberFormat('zh-Hant-TW', { style: 'currency',
  currency: 'TWD' })` → `NT$1,234`.
- Percentage: `Intl.NumberFormat('zh-Hant-TW', { style: 'percent' })`.

For draft content where the firm wants Chinese-locale numerals like
「一千二百三十四」, expose a per-tenant option but default to Arabic
digits — TIPO accepts Arabic, and Chinese numerals introduce ambiguity
in claim language.

### 5.8 民國 calendar (ROC era)

Many TW legal documents cite 民國 dates ("民國114年6月5日" = 2025-06-05).
JavaScript natively supports the ROC calendar in `Intl.DateTimeFormat`
([MUI roc adapter issue](https://github.com/mui/mui-x/issues/8323),
[MDN Intl.DateTimeFormat](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/DateTimeFormat/DateTimeFormat)):

```js
new Intl.DateTimeFormat('zh-Hant-TW', {
  calendar: 'roc',
  year: 'numeric', month: 'long', day: 'numeric'
}).format(new Date('2026-06-05'));
// "民國115年6月5日"
```

**Recommendation**: ship a `formatLegalDate(date, { era })` helper that
defaults to Gregorian for UI and accepts `{ era: 'roc' }` for printed
letters and TIPO-bound exports. Audit-row timestamps remain Gregorian
ISO 8601 (`2026-06-05T14:30:00+08:00`) for unambiguous parsing.

### 5.9 IME interaction — DON'T trap focus over candidates

The 微軟新注音 candidate window appears as a floating native overlay
above the focused input. Two concrete risks:

- **Focus traps in modals must not intercept Esc** while an IME
  composition is in progress (`event.isComposing === true`). The fix:

  ```js
  function onKeyDown(e) {
    if (e.isComposing || e.keyCode === 229) return;  // IME active
    if (e.key === 'Escape') closeModal();
  }
  ```

- **Cmd-K palette must not capture keystrokes** during IME composition.
  Same `isComposing` check before any global shortcut handler.

- **Roving tabindex in ClaimTree** must not consume arrow keys during
  IME composition in its filter input.

This is the single most common cause of bug reports from TW users
hitting a non-Chinese-first product.

---

## 6. English + US bilingual UX

### 6.1 Register — formal in drafts, plain in UI

USPTO Office Action responses use a specific formal register:
"Applicant respectfully submits that...", "Reconsideration is
respectfully requested...", "The Examiner's rejection of claim 1 under
35 U.S.C. § 103 is respectfully traversed...". The draft generator
must emit USPTO-formal in `lang="en"` content; UI labels stay plain
("Verify", "Sign-off", "Submit").

The current `i18n.js` shell strings are plain — keep that. When a
draft template loads via `draft_response.yaml`, it carries its own
register and is not subject to UI-label localisation.

### 6.2 US patent citation format

Citation typography for `lang="en"` content:

- `U.S. Pat. No. 12,345,678` — exactly that form. Implementation needs
  **non-breaking thin spaces** between `U.S.` and `Pat.` and within
  `Pat. No. 12,345,678`:
  ```
  U.S.&#8239;Pat.&#8239;No.&#8239;12,345,678
  ```
  (`&#8239;` = U+202F narrow no-break space). Prevents line-break
  inside the citation.
- `35 U.S.C. § 103` — same thin-space treatment; never line-break.
- `MPEP § 706.07` — same.
- Application numbers: `Application No.&#8239;15/123,456`.
- The pre-AIA two-letter prefix patents (`US 7,654,321`) get a
  non-breaking space too.

Build a `<Cite>` component that takes a structured `{ type: 'patent',
country: 'US', number: '12345678' }` and renders with correct
typography. Tests assert the rendered HTML contains the right
non-breaking space chars.

### 6.3 Date formats

| View | Locale | Format |
|---|---|---|
| zh-TW UI labels (`今天 6 月 5 日`) | `zh-Hant-TW` Gregorian | YYYY 年 M 月 D 日 |
| en UI labels | en-US | June 5, 2026 |
| zh-TW formal letter print | zh-Hant-TW ROC | 民國 115 年 6 月 5 日 |
| en formal letter print | en-US | June 5, 2026 |
| Audit timestamps | ISO 8601 (`2026-06-05T14:30:00+08:00`) | Unambiguous |
| Case detail "filed" / "due" headers | follows UI locale | — |
| Form date input | ISO date (`<input type="date">`) | Browser handles locale rendering |

**Rule**: never use slash-separated dates (`6/5/2026`) in UI — it's
ambiguous between US and ISO. If you must abbreviate, use `2026-06-05`.

### 6.4 Currency

The cost-meta chip currently shows USD only (Q18 token-cost circuit
breaker). Per-tenant setting `billing_currency` (`USD` or `TWD`) drives:

```js
const fmt = new Intl.NumberFormat(uiLocale, {
  style: 'currency',
  currency: tenant.billing_currency  // 'USD' or 'TWD'
});
fmt.format(0.42)
// 'NT$13.43' if TWD, '$0.42' if USD
```

Round half-away-from-zero to the locale's standard precision. Show
**both** when explicitly comparing ("Quota: $42.00 USD / NT$1,344
TWD") on the billing surface only.

---

## 7. i18n architecture (beyond the i18next scaffold)

The existing `i18n.js` is a good foundation but incomplete. The
production stance:

### 7.1 Locale-aware formatters

Centralise in `frontend/src/lib/format.js`:

```js
// Pseudocode shape
export const formatDate = (date, { locale, era, style }) => ...
export const formatNumber = (num, { locale }) => ...
export const formatCurrency = (num, { locale, currency }) => ...
export const formatList = (items, { locale, type }) => ...  // Intl.ListFormat
export const formatDateRange = (start, end, { locale }) => ...
```

**Never** concatenate strings to form dates or currency. Always go
through `Intl.*`.

### 7.2 Locale-aware sort

`Intl.Collator('zh-Hant-TW')` defaults to Unicode codepoint order —
which puts characters in a basically random visual order. Three options
when sorting Chinese strings:

- `pinyin` — alphabetical by Mandarin pronunciation (`Intl.Collator('zh-Hant-TW-u-co-pinyin')`).
- `stroke` — by character stroke count (`Intl.Collator('zh-Hant-TW-u-co-stroke')`).
- `zhuyin` — by Bopomofo order (subset of pinyin in practice).

**Recommendation**: stroke order for case lists (matches TW filing
conventions); pinyin for contact lists.

### 7.3 Pluralisation

Chinese has no grammatical plural ("1 case" and "2 cases" are
linguistically identical in zh). English does. Use i18next's
ICU plural format:

```json
"case_count": "{count, plural, one {# case} other {# cases}}"
```

```json
"case_count": "{count} 件案件"
```

Chinese can omit the plural rule entirely; English needs it. i18next's
ICU plugin handles both.

### 7.4 Pseudo-translation pipeline

Wrap every UI string at build-time to expose layout breakage. From the
`pseudo-l10n` workflow ([SimpleLocalize guide](https://simplelocalize.io/blog/posts/pseudo-localization-guide/),
[pseudo-l10n npm](https://www.npmjs.com/package/pseudo-l10n)):

```
"Verify"  →  "[Ⱳéŕíƒƴ]"             # markers + accents
"Sign off"  →  "[Ŝìǵń ôƒƒ ƒƒƒƒ]"     # markers + 30% expansion
```

CI step: generate `i18n.pseudo.json`, run Playwright against it at
multiple viewports, screenshot-diff against baseline. Catches:

- Strings with no marker → hardcoded (i18n bypass)
- UI clipping → text-overflow not handled
- Mis-aligned tables → fixed-width columns assuming en
- Truncated chips → `text-ellipsis` cuts mid-glyph

### 7.5 Translation-key naming convention

Current `i18n.js` uses nested dot paths (`common.shell.audit_chip.ok`).
Keep, with rules:

- Lowercase snake_case for keys.
- Group by **component**, not by **feature** — `analyze.tree.legend.rejected`
  not `tree.rejected_in_analyze_view`.
- Suffix `_label` for input labels, `_tooltip` for tooltips,
  `_aria` for ARIA-only strings.
- Plural keys end `_count`.
- Variables in `{{double_braces}}`.

When a single component has > 30 strings, co-locate the translation in
`Component.i18n.json` next to the JSX, not in the global `i18n.js`
resource bundle. The Phase 4 migration in `PRODUCT_STRATEGY.md` §6.2
should adopt this — splits the giant single-file bundle into per-
component shards.

### 7.6 Locale-fallback chain

```
zh-TW (primary)
  ↓ fallback
zh-Hant
  ↓ fallback
zh
  ↓ fallback
en (current default fallback)
```

i18next config: `fallbackLng: ['zh-Hant', 'zh', 'en']`. Helps when a
key is added in zh-TW but not zh-CN — currently we don't ship zh-CN,
but the chain is future-proof.

### 7.7 RTL-awareness (even though we don't support it)

We don't ship Arabic / Hebrew. But design tokens should NOT bake LTR
assumptions:

- Use logical properties: `padding-inline-start` not `padding-left`,
  `margin-block-end` not `margin-bottom`, `inset-inline-start` not
  `left`.
- Don't position with absolute `left/right` when `inset-inline-*` works.
- Icons that have direction (e.g. a "next" arrow) should be flipped
  with `transform: scaleX(var(--scale-x))` and `--scale-x: 1` in LTR,
  `-1` in RTL.

This costs nothing at LTR-shipping time and makes any future RTL trial
cheap. Tailwind's logical-property utilities are stable as of v3.3.

---

## 8. Mobile + tablet behaviour

Partner attorneys do most of their **review** on iPad; almost no
**input** happens on touch devices ([Patlytics multitasking blog](https://www.patlytics.ai/blog/a-smarter-multitasking-workspace-for-patent-prosecution)
implies the desktop-first stance the industry has converged on).
PatentMind's mobile strategy reflects that asymmetry.

### 8.1 Breakpoint plan

| Width | Mode | Capabilities |
|---|---|---|
| ≥ 1920 px | Full desktop, ambient | 3-pane + pop-out reference window on monitor 2 |
| 1280-1920 px | Full desktop | 3-pane standard |
| 1024-1280 px (iPad landscape, MBA 13") | Compact desktop | 3-pane with `compact` density auto |
| 768-1024 px (iPad portrait, iPad Mini) | **Review-only** | 2-pane (Drafts + Refs), Input tab collapsed; can sign-off, can verify, cannot enter long OA text |
| 360-768 px (phone) | **Read-only + notify** | Audit view + push notifications; "switch to desktop" message for any input |

### 8.2 Touch targets

- **WCAG 2.5.8 minimum: 24×24 CSS px.** Hard floor.
- **Recommended: 44×44 CSS px** (Apple HIG, also = WCAG 2.5.5 AAA;
  [Apple HIG accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility),
  [TestParty 2.5.8 guide](https://testparty.ai/blog/wcag-target-size-guide)).
- **PatentMind rule**: 44×44 for any touch-mode interaction (when
  `coarse pointer` media query matches); 24×24 floor on desktop with
  16 px clear-space padding.

```css
@media (pointer: coarse) {
  .icon-button { min-width: 44px; min-height: 44px; }
}
@media (pointer: fine) {
  .icon-button { min-width: 24px; min-height: 24px; padding: 8px; }
}
```

### 8.3 Hover-degradation rule

Every hover-only affordance MUST have a tap-equivalent:

- **Citation hover-preview** → tap to pin preview (closes on tap-outside).
- **Tooltip on icon-only button** → tap once shows label (announces via
  live region), tap-and-hold shows tooltip, tap a second time activates.
- **Hover-row-highlight in audit table** → use `:focus-within` and
  `:active` so keyboard / touch also get visual feedback.

### 8.4 Sticky toolbars

The 3-pane Analyze view sticky-pins the action bar at the bottom of the
Drafts pane on scroll (Verify / Sign-off / Export). Mobile review mode
pins it to the bottom of the viewport using `position: sticky;
bottom: env(safe-area-inset-bottom, 0)` for iOS notch + home-indicator
correctness.

### 8.5 Pull-to-refresh on Audit

Familiar mobile pattern. Implement on the AuditView mobile breakpoint
only. Don't do it on Drafts (it'd conflict with the scroll-pin of
unsigned lines).

### 8.6 Offline + cached read

iPad partners on a flight need to **review** an OA they pulled earlier.
Implementation:

- Cache the last 3 viewed drafts + audit rows in IndexedDB on the
  device after each fetch.
- Service worker for shell + read-only routes.
- Explicit "OFFLINE — cached at HH:MM" badge top-right when offline;
  banner is `role="status"`.
- **No offline edits**, ever. Audit chain integrity (`CLAUDE.md` §4
  invariants #2 + #4) requires every gateway write to land in real-time
  with a fresh hash. Sign-off and Verify disabled with a tooltip
  "Online required — audit chain must be live."

---

## 9. Print stylesheet

PatentMind drafts and audit chains need to print cleanly — TW partners
still print for partner-review markup, and the audit chain print-out
is the artifact for an internal compliance review.

### 9.1 Draft → A4 formal letter

```css
@media print {
  @page { size: A4; margin: 25mm 20mm 25mm 25mm; }
  body { font-family: "Source Serif 4", "Source Han Serif TC", "Noto Serif TC", "Songti TC", serif; }
  .draft { font-size: 12pt; line-height: 1.75; }
  .draft-header { display: block; font-weight: 700; font-size: 14pt; }
  .case-id, .patent-no { font-variant-numeric: tabular-nums; }
  .citation { font-style: normal; text-decoration: none; }   /* strip the screen hover-affordance */
  .citation::after { content: " [" attr(data-ref) "]"; font-size: 10pt; }
  .ui-only { display: none; }                                 /* hide CmdK hint, etc */
}
```

Serif typeface only for print (PRODUCT_STRATEGY §5.2 already aligned).
The font stack `"Source Han Serif TC", "Noto Serif TC", "Songti TC"`
covers macOS, Linux, Windows.

### 9.2 Audit chain → landscape table

```css
@media print {
  .audit-view { @page { size: A4 landscape; } }
  .audit-table { font-family: "JetBrains Mono", monospace; font-size: 9pt; }
  .audit-table th { border-bottom: 1.5pt solid #000; }
  .audit-table .hash { font-variant-numeric: tabular-nums; word-break: break-all; }
}
```

Hash chips must remain legible — `break-all` prevents one long hash
overflowing the page.

### 9.3 Confidential watermark

Cases with `_CONF` suffix get a diagonal watermark on every printed
page:

```css
.confidential::before {
  content: "機密 / CONFIDENTIAL";
  position: fixed;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%) rotate(-30deg);
  font-size: 96pt;
  font-weight: 800;
  color: rgba(15, 23, 42, 0.08);
  z-index: -1;
  pointer-events: none;
}
```

8% opacity is the sweet spot — visible enough to deter casual
forwarding, light enough not to interfere with reading.

### 9.4 Page break rules

```css
.claim, .citation, .audit-row { break-inside: avoid; }
h1, h2, h3 { break-after: avoid; }
.citation-pill { break-inside: avoid; }   /* don't split a citation across pages */
```

Citation pills splitting across a page break is the single most common
print bug in legal docs.

### 9.5 URL handling

Don't print bare URLs in body — bookmarks aren't useful on paper. Use
footnotes:

```css
@media print {
  a[href]::after { content: " [" target counter(footnote) "]"; }
  .footnotes { display: block; margin-top: 2rem; font-size: 9pt; }
}
```

Generate a footnote section listing every referenced URL with its
ordinal number.

---

## 10. Testing protocol

### 10.1 Per-PR (automated)

- `axe-core` Playwright run hits **zero serious / critical** violations
  on the touched routes.
- Storybook a11y addon zero violations on changed stories.
- Lighthouse a11y score ≥ 95 on `/login`, `/analyze`, `/audit`.
- Pseudo-locale visual regression (Playwright screenshot diff against
  `i18n.pseudo.json`).
- `npm run test:rtl-tokens` (pseudo-RTL CSS smoke).

### 10.2 Per-release (manual smoke, < 30 min)

- NVDA + Firefox: walk login → 3-pane → sign-off → audit.
- VoiceOver + Safari: same walk on macOS.
- Keyboard-only: complete one full OA analysis + sign-off, no mouse.
- 200% zoom: verify reflow.
- `prefers-reduced-motion`: verify animations stop.
- Dark mode: verify palette contrasts.

### 10.3 Quarterly recruited user review

Per-quarter budget: **~NT$50,000** (≈ USD 1,600) for participant
incentives + accessibility consultant.

- One low-vision attorney (screen-magnifier or screen-reader user).
- One keyboard-only attorney (RSI or mobility).
- One TW-attorney native zh-TW speaker (typography review).
- One US-attorney native en speaker (citation typography review).

Recruit via 中華視障路跑會, 障權盟 (the Taiwan Foundation for the Blind),
TIPA member lists for sighted reviewers. NT$5,000 incentive + travel.

### 10.4 Pseudo-locale visual regression in Playwright

```js
// Pseudocode
test.use({ locale: 'en-XA' });   // Chrome's built-in pseudo-locale
for (const route of ['/login', '/analyze', '/audit']) {
  await page.goto(route);
  await expect(page).toHaveScreenshot(`${route}-pseudo.png`, { maxDiffPixelRatio: 0.02 });
}
```

Run on every PR. Catches clipped buttons, fixed-width tables, missing
ARIA-label translations, hardcoded English strings.

### 10.5 Definition of done

A component is "a11y-done" when:

- All keyboard interactions work (tab, arrow, enter, esc).
- Screen reader announces role, name, state, and value.
- Focus visible at 3:1 contrast minimum.
- Touch targets ≥ 24 px desktop / 44 px touch.
- Zero `axe-core` serious/critical.
- Story with `a11y.test = 'error'` passes.
- Pseudo-locale screenshot matches baseline within 2%.
- Print stylesheet renders sanely (manual eyeball, A4 preview).

---

## Report — the calls the redesign reviewer should make first

> Budget < 400 words. Three lurking a11y violations the redesign agent
> is likely to miss; one i18n decision likely to age badly; one mobile
> feature worth shipping early.

**Three lurking a11y violations.**

1. **`ClaimTree` will ship without roving tabindex.** The natural React
   pattern is to spread `tabindex=0` on every visible node so that
   Tab cycles through them, which gives 30+ tab stops per claim list
   and makes keyboard navigation unusable for screen-reader users.
   The fix is non-obvious to a frontend engineer not steeped in
   WAI-ARIA — only the tree root gets tabindex 0, children get -1,
   focus moves via arrow keys (§3.2). Flag at PR review time.

2. **Citation hover-preview will be hover-only.** Today's `DraftEditor`
   uses inline-popover patterns. The redesign UX wants Granola-style
   hover-tooltips on citation pills. The default React popover library
   pattern is `onMouseEnter` only — which fails WCAG 2.1.1 Keyboard and
   2.5.7 Dragging Movements. Must also fire on `focus-visible` and stay
   open on `Esc-close-only`, with `aria-describedby` linkage (§4.3).

3. **`focus:outline-none` will reappear in `tailwind.config.js`** via a
   plugin or via someone "cleaning up the ugly focus ring." The redesign
   adds `focus-visible:ring-blue-900` correctly in some places (Login)
   but Tailwind's preflight removes the default outline globally. Every
   interactive class needs the explicit `focus-visible:ring-2
   focus-visible:ring-blue-900 focus-visible:ring-offset-2` shipped as
   a class composition (`@apply` in `index.css`), not relied on
   component-by-component (§1.3).

**The i18n decision most likely to age badly.** Auto-inserting `pangu.js`
spacing into draft content. Cosmetically tempting; corrupts copy
fidelity when attorneys paste into USPTO Patent Center, and there is
**no recovery path** once committed-to-storage drafts contain inserted
U+0020 spaces. Use CSS `text-autospace` for chrome only (§5.3). If a
designer pushes for "the Vue.js look" in drafts, escalate.

**The mobile feature worth shipping early to unlock the partner
persona.** **iPad review-only mode + offline-cached last-3-drafts**
(§8.6). Partners do their review-and-approval on tablet, often during
travel. Without this, our reach into the partner cohort caps at "the
junior shows the partner on a laptop." With it, sign-off-from-iPad
becomes a partner-level demo moment that converts at the procurement
meeting. Service-worker + IndexedDB + a polite-live-region "OFFLINE —
cached at HH:MM" banner is two sprints; ship it before three-pane
desktop polish.

---

## References

### WCAG 2.2 + a11y core
- [W3C WCAG 2.2 spec](https://www.w3.org/TR/WCAG22/)
- [DOJ ADA Title II web rule April 2024](https://www.ada.gov/resources/2024-03-08-web-rule/)
- [Level Access WCAG 2.2 AA checklist 2026](https://www.levelaccess.com/blog/wcag-2-2-aa-summary-and-checklist-for-website-owners/)
- [TestParty — WCAG 2.2 new success criteria implementation guide](https://testparty.ai/blog/wcag-22-new-success-criteria)
- [TestParty — 2.5.8 target size guide](https://testparty.ai/blog/wcag-target-size-guide)
- [Deque University WCAG 2.2 resources](https://dequeuniversity.com/resources/wcag-2.2/)
- [AllAccessible — WCAG 2.2 nine new criteria](https://www.allaccessible.org/blog/wcag-22-complete-guide-2025)
- [Vispero — new success criteria in WCAG 2.2](https://vispero.com/resources/new-success-criteria-in-wcag22/)

### Tooling — CI a11y pipeline
- [axe-core npm dependents](https://www.npmjs.com/package/axe-core?activeTab=dependents)
- [Storybook accessibility testing docs](https://storybook.js.org/docs/writing-tests/accessibility-testing)
- [Storybook addon-a11y](https://storybook.js.org/addons/@storybook/addon-a11y)
- [Accesify — axe + Pa11y + Lighthouse CI guide](https://www.accesify.io/blog/accessibility-testing-automation-axe-pa11y-lighthouse-ci/)
- [Ramotion — Pa11y + axe-core practical guide](https://www.ramotion.com/blog/practical-accessibility-testing-with-pa11y-and-axe-core/)
- [a5h.dev — a11y CI/CD for React](https://a5h.dev/post/how-to-test-for-a11y-in-react-app-cicd/)

### Screen readers
- [WebAIM Screen Reader User Survey #10](https://webaim.org/projects/screenreadersurvey10/)
- [accessibility-test.org — NVDA vs JAWS vs VoiceOver 2025](https://accessibility-test.org/blog/development/screen-readers/nvda-vs-jaws-vs-voiceover-2025-screen-reader-comparison/)
- [ExceedAbility — screen readers compared 2026](https://exceedability.com/screen-readers-compared.html)
- [Allyant — DOJ-approved screen readers](https://allyant.com/blog/6-doj-approved-screen-readers/)
- [Accessibility.build — SR testing guide](https://accessibility.build/guides/screen-reader-testing)

### Touch targets + mobile
- [Apple HIG accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- [LogRocket — accessible touch target sizes](https://blog.logrocket.com/ux-design/all-accessible-touch-target-sizes/)
- [Adrian Roselli — target size and 2.5.5](https://adrianroselli.com/2019/06/target-size-and-2-5-5.html)
- [DesignMonks — perfect mobile button size](https://www.designmonks.co/blog/perfect-mobile-button-size)
- [Medium — iOS accessibility guidelines 2025](https://medium.com/@david-auerbach/ios-accessibility-guidelines-best-practices-for-2025-6ed0d256200e)

### CJK typography
- [W3C Requirements for Chinese Text Layout (CLREQ)](https://www.w3.org/TR/2015/WD-clreq-20150723/)
- [W3C — Chinese Layout Gap Analysis](https://www.w3.org/TR/clreq-gap/)
- [W3C — styling vertical text](https://www.w3.org/International/articles/vertical-text/)
- [justfont — 排版間距](https://learn.justfont.com/pocketbook/applications/layout-applications/spacings)
- [justfont — 在網頁上呈現最高品質的字體](https://webfont.justfont.com/fonts)
- [justfont blog — 大眾字型學：更好看的排版教學](https://blog.justfont.com/2013/05/popular-typography-2/)
- [Wiwi.Blog — 有氣質的字距](https://wiwi.blog/blog/letter-spacing/)
- [黑暗執行緒 — 字型大小與行高](https://blog.darkthread.net/blog/font-size-n-line-height/)
- [Simular — 中文 CSS 排版原則指南](https://simular.co/blog/post/2-%E4%B8%AD%E6%96%87-css-%E6%8E%92%E7%89%88%E5%8E%9F%E5%89%87%E6%8C%87%E5%8D%97)
- [Typotheque — Typesetting CJK text](https://www.typotheque.com/articles/typesetting-cjk-text)
- [Asian Absolute — CJK typesetting 2025](https://asianabsolute.co.uk/blog/cjk-typesetting-challenges-workflows-and-best-practices/)
- [az-loc — best fonts for CJK websites](https://www.az-loc.com/best-fonts-for-chinese-japanese-korean-websites/)
- [Wikipedia — Horizontal and vertical writing in East Asian scripts](https://en.wikipedia.org/wiki/Horizontal_and_vertical_writing_in_East_Asian_scripts)

### CSS i18n properties
- [MDN — `text-autospace`](https://developer.mozilla.org/en-US/docs/Web/CSS/text-autospace)
- [MDN — `text-spacing-trim`](https://developer.mozilla.org/en-US/docs/Web/CSS/text-spacing-trim)
- [MDN — `font-variant-numeric`](https://developer.mozilla.org/en-US/docs/Web/CSS/font-variant-numeric)
- [MDN — `font-feature-settings`](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/font-feature-settings)
- [Chrome i18n CSS features](https://developer.chrome.com/blog/css-i18n-features)
- [Tailwind — font-variant-numeric utility](https://tailwindcss.com/docs/font-variant-numeric)
- [CSS-Tricks — font-variant-numeric](https://css-tricks.com/almanac/properties/f/font-variant-numeric/)
- [Caro Appleby — tabular numbers](https://www.caro.fyi/articles/tabular-nums/)
- [Sebastian De Deyne — tabular numbers](https://sebastiandedeyne.com/tabular-numbers/)

### Pangu spacing
- [vinta/pangu.space — GitHub](https://github.com/vinta/pangu.space)
- [pangu.js — SourceForge mirror](https://sourceforge.net/projects/pangu-js.mirror/)
- [Typst forum — Unicode report on text(cjk-latin-spacing)](https://forum.typst.app/t/unicode-drafts-a-report-on-text-cjk-latin-spacing/2446)
- [Hugo issue #10617 — native Pangu support](https://github.com/gohugoio/hugo/issues/10617)

### ROC / 民國 calendar
- [MDN — Intl.DateTimeFormat](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/DateTimeFormat/DateTimeFormat)
- [MUI-X issue #8323 — Taiwan ROC calendar adapter](https://github.com/mui/mui-x/issues/8323)
- [880831ian/taiwan-calendar — GitHub](https://github.com/880831ian/taiwan-calendar)

### Fonts
- [Google Fonts — Noto Sans TC](https://fonts.google.com/noto/specimen/Noto+Sans+TC)
- [Noto Fonts implementation guide](https://notofonts.github.io/noto-docs/website/use/)
- [Linguise — language switcher UX for non-Latin scripts](https://www.linguise.com/blog/guide/designing-language-switcher-ui-for-non-latin-script-users-best-practices-ux-tips/)

### Pseudo-localisation + i18n testing
- [SimpleLocalize — pseudo-localization guide](https://simplelocalize.io/blog/posts/pseudo-localization-guide/)
- [SimpleLocalize — complete i18n / l10n guide](https://simplelocalize.io/blog/posts/internationalization-guide-software-localization/)
- [pseudo-l10n npm](https://www.npmjs.com/package/pseudo-l10n)
- [Anton Antonov — pseudo-localization for automated i18n testing](https://medium.com/@AntonAntonov88/pseudo-localization-for-automated-i18n-testing-410d57ca65c6)
- [Jeremie Fleurant — Playwright + i18n E2E translations](https://medium.com/@jeremie.fleurant/using-translations-with-playwright-and-i18n-for-e2e-tests-ba90a667f309)

### Patent + TW context (cross-links)
- `docs/PRODUCT_STRATEGY.md` §5.2 + §6
- `docs/UX_RESEARCH.md` §3 (workflow), §5 (Phase 4 sprint), §5.8 bilingual UX hardening
- `CLAUDE.md` §4 invariants (audit chain, redaction, on-prem mapping)
- `frontend/src/lib/i18n.js` (current scaffold)
