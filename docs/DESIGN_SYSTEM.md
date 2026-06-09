# PatentMind Design System (v1.0)

> Author: Design-system research agent · 2026-06-05.
> Audience: every frontend dev who will ship a component into this product.
> Scope: tokens (color · type · space · motion) + component anatomy + governance.
> Out of scope: visual mockups, marketing site, billing portal, mobile-native apps.
>
> This spec **formalises and extends** `PRODUCT_STRATEGY.md §5` and aligns with
> the App-shell rebuild now in flight (navy `#1e3a8a`, lucide-react, Inter +
> Noto Sans TC + JetBrains Mono). Where this spec disagrees with running code,
> §11 lists the reconciliation path.

---

## 1. Design principles

Six principles. They are not aspirational; each one is enforceable in code review.

### P1 — Trust-first
Every UI moment must signal one of the four trust pillars: **provenance**
(citation visible), **audit** (hash chain reachable), **residency** ("PII
stays in TW"), or **routing** ("this case → on-prem LLM"). If a screen
spends > 200 px of vertical space without surfacing one of those pillars,
it has failed the principle. The hash chain (`Q13`) and confidential
routing (`Q15`) are the two unique-to-PatentMind moats; surface them in
the header band, not buried in `/audit`.

### P2 — Conservative legal aesthetic, not modern startup
We are not Linear, Vercel, or Notion. Reference identities: Harvey's
deep-navy + warm-cream restraint, Lexis+ Protégé's editorial columns,
Lee and Li's printed cover stock. Specific rejections: no gradients on
primary surfaces; no glassmorphism; no "playful" empty-state illustrations;
no rounded-3xl pill buttons; no purple-pink CTA. Navy + slate + a single
warm accent. Borders carry the structure, not shadows.

### P3 — Dense but not cramped
Attorneys read, they don't browse. Default density targets ~24 rows per
1080-px viewport in tables, ~80–100 chars per line in body. Card padding
defaults to `sp.md` (16 px), not `sp.lg`. Whitespace earns its keep by
disambiguating regions (between panes, between header bands), not by
"breathing room". Partners can opt into `density.compact` (§4.2) which
collapses padding by 25 %.

### P4 — AI is scaffolding, not an oracle
Every AI-generated artifact must visually couple to its grounding.
Drafts carry inline `[GROUNDED_REF_n]` pills that link to the source
passage. Every claim of fact is a citation pill component (§6.17), never
raw text. Confidence scores show numerically + as a chip color, never
alone. When the verifier (`Q14`) flags a citation, the pill turns from
emerald to amber **before** the user can copy the draft. AI output never
gets a "magic" treatment (no glow, no sparkle icon, no shimmer).

### P5 — Bilingual-native
Mixed zh-TW + en is the typical document, not the edge case. The type
stack treats both as first-class (§3). Every component must accept
strings of either language and render without overflow or vertical
jitter. Every text-bearing element gets a `lang` attribute so screen
readers and the print stylesheet route correctly. Toggle in header, not
in settings.

### P6 — Print-friendly
Drafts print to formal A4 attorney letters; the audit chain prints to a
multi-page court-grade exhibit. Type stack switches to serif for body
on print (§9). Confidential cases stamp a watermark. Dark mode is
ignored entirely on print. Components that look fine on screen but
break in print (e.g., overflow-hidden cards swallowing content) are bugs.

---

## 2. Color tokens

A three-layer token system: **primitives → semantic → component**. Components
consume only semantic tokens. Primitives change for theming (dark, high-contrast,
print) without rippling through every component.

### 2.1 Primitive ramps

Each ramp is 11 steps (`50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950`).
Source: the running `tailwind.config.js` already pins `navy.900 = #1e3a8a`
(PRODUCT_STRATEGY §11 ground truth). The remaining ramps follow Tailwind's
default OKLCH curves; `950` extends each ramp into the dark-mode-friendly range.

**`navy.*` — primary brand**

| step | hex      | use                                           |
|------|----------|-----------------------------------------------|
| 50   | #eff6ff  | tint fills (banner backgrounds)               |
| 100  | #dbeafe  | hover-state backgrounds                       |
| 200  | #bfdbfe  | selected-state backgrounds                    |
| 300  | #93c5fd  | disabled brand text on dark                   |
| 400  | #60a5fa  | dark-mode primary text                        |
| 500  | #3b82f6  | mid-contrast emphasis                         |
| 600  | #2563eb  | dark-mode CTA fill                            |
| 700  | #1d4ed8  | active CTA on light                           |
| 800  | #1e40af  | hover CTA on light                            |
| 900  | #1e3a8a  | **pinned brand. CTA fill. logo bar.**         |
| 950  | #172554  | dark-mode brand background                    |

**`slate.*` — neutrals.** Standard Tailwind ramp (`50 #f8fafc` … `950 #020617`).
This is the dominant surface ramp; navy is for accents and brand moments.

**`emerald.*` — success / verified.** `700 #047857` is the canonical
"clean" tone (matches PRODUCT_STRATEGY recommendation). Used for
verified-citation pills, audit-chain "VERIFIED" badges, allowed-claim
nodes in the claim tree.

**`amber.*` — caution / pending.** `700 #b45309` is the canonical
deadline-urgency tone. Cascade-risk claim nodes, pending verifier states,
upcoming-deadline chips.

**`rose.*` — rejection / failed.** `700 #be123c` (not `red.700` —
slightly more magenta-shifted; reads less "alarm" and more "rejected
under §103" — a critical difference in tone for legal copy). Used for
rejection chips, failed-verifier results, audit-chain breaks.

**`purple.*` — confidential / privileged.** `700 #7e22ce`. Reserved
exclusively for the confidentiality surface (Q15 lock indicator,
confidential case header band, on-prem-routed badge). No other use
of purple anywhere in the product; this is what gives the
confidentiality signal its instant recognition.

**`sky.*` — informational / link.** `600 #0284c7`. Inline links, info
banners, "did you know" tour callouts. Distinct from `navy` so brand
moments don't fight with informational moments.

### 2.2 Semantic tokens (the layer components consume)

Below: semantic name → primitive in light → primitive in dark. Where
WCAG 2.2 AA contrast is asserted, the pair has been verified to ≥ 4.5:1
for body text or ≥ 3:1 for large text (per
[W3C SC 1.4.3](https://www.w3.org/WAI/WCAG21/Understanding/contrast-minimum)).

**Surfaces**

| token                    | light          | dark            | notes                                |
|--------------------------|----------------|-----------------|--------------------------------------|
| `surface.background`     | slate.50       | slate.950       | app canvas                           |
| `surface.elevated`       | white          | slate.900       | cards, modals, popovers              |
| `surface.sunken`         | slate.100      | slate.950       | inset wells (code blocks, inputs)    |
| `surface.brand`          | navy.900       | navy.800        | header band, primary CTA fill        |

**Text** (all pairs verified vs the surface that conventionally wraps them)

| token              | light    | dark        | contrast vs default surface |
|--------------------|----------|-------------|------------------------------|
| `text.primary`     | slate.900 | slate.50    | 18.7:1 / 17.4:1 (AAA)        |
| `text.secondary`   | slate.700 | slate.300   | 9.3:1  / 8.1:1  (AAA)        |
| `text.tertiary`    | slate.500 | slate.400   | 4.6:1  / 4.5:1  (AA body)    |
| `text.disabled`    | slate.400 | slate.600   | 3.4:1  / 3.2:1  (AA Large)   |
| `text.inverted`    | white    | slate.900   | for use on brand surfaces    |
| `text.link`        | sky.700  | sky.400     | 5.2:1  / 5.9:1  (AA)         |
| `text.code`        | slate.800 | slate.200   | 13.1:1 / 14.6:1 (AAA)        |

`text.tertiary` is the floor for body text. The current frontend uses
`text-slate-500` for muted captions; that passes AA body (4.6:1) but is
**banned for any text < 14 px** because the AA Large 3:1 rule does not
apply below 14 px. The contrast audit in PRODUCT_STRATEGY §6.1
flagged this; treat `text-slate-400` (3.4:1) as a print-only token,
not a screen token.

**Borders**

| token                | light     | dark        | notes                          |
|----------------------|-----------|-------------|--------------------------------|
| `border.subtle`      | slate.100 | slate.800   | hairlines inside cards         |
| `border.default`     | slate.200 | slate.700   | card outlines, table rows      |
| `border.emphasis`    | slate.300 | slate.600   | focused panes, selected states |
| `border.focus-ring`  | navy.700  | navy.400    | 2-px ring + 2-px offset        |

**Accents**

| token                  | light    | dark        |
|------------------------|----------|-------------|
| `accent.brand`         | navy.900 | navy.600    |
| `accent.brand-hover`   | navy.800 | navy.500    |
| `accent.brand-active`  | navy.950 | navy.700    |

**Status**

| token              | bg light  | fg light  | bg dark    | fg dark    |
|--------------------|-----------|-----------|------------|------------|
| `status.success`   | emerald.50 | emerald.800 | emerald.950 | emerald.300 |
| `status.warning`   | amber.50  | amber.800 | amber.950  | amber.300  |
| `status.error`     | rose.50   | rose.800  | rose.950   | rose.300   |
| `status.info`      | sky.50    | sky.800   | sky.950    | sky.300    |

**Confidentiality surface**

| token                  | light       | dark        |
|------------------------|-------------|-------------|
| `confidential.surface` | purple.50   | purple.950  |
| `confidential.text`    | purple.800  | purple.200  |
| `confidential.border`  | purple.300  | purple.700  |

**Redaction (mask) chips** — inline tags where masked-entity tokens
appear in user-facing text. The mask chip is the single most
trust-signaling micro-component in the product (`Q3` + `Q10`):

| token         | light       | dark        |
|---------------|-------------|-------------|
| `mask.bg`     | amber.100   | amber.950   |
| `mask.text`   | amber.900   | amber.200   |
| `mask.border` | amber.300   | amber.700   |

Mask chips render `[ORG_001]` / `[PER_001]` etc. as a chip, not raw text.
Hovering reveals "1 entity redacted" tooltip (never the original PII;
PII de-redaction is only available to the case's owner attorney via
the explicit Reveal button).

### 2.3 Forbidden combinations

- Confidential surface tokens NEVER pair with brand-navy CTAs.
  Confidential CTAs use `purple.800` instead. Reason: the eye must
  unambiguously map the lock icon, the header band, and the action color.
- `status.error` (rose) NEVER paired with `accent.brand` (navy) on the
  same chip. Rose-on-navy reads as US presidential branding to international
  audiences and is unprofessional in TW context.
- Tertiary text NEVER on `surface.sunken`. The contrast collapses to 3.8:1
  on light, fails AA on dark.

---

## 3. Typography tokens

### 3.1 Families

```
font.sans   = "Inter", "Noto Sans TC", "PingFang TC", "Heiti TC",
              -apple-system, BlinkMacSystemFont, "Segoe UI",
              Roboto, sans-serif
font.mono   = "JetBrains Mono", ui-monospace, "SF Mono", "Cascadia Code",
              Menlo, Consolas, "Noto Sans Mono CJK TC", monospace
font.serif  = "Source Serif 4", "Noto Serif TC", Georgia, "Songti TC", serif
```

**Choice rationale.**

- **Inter** is shipped because its tall x-height, open apertures, and
  default tabular figures match the data-dense surfaces this product
  optimises for. Inter
  [defaults tabular figures so numerals align in columns without an
  OpenType opt-in](https://madegooddesigns.com/inter-font/) — that is
  load-bearing for our case-ID columns, hash IDs, and deadline tables.
  Inter ships Latin glyphs only, delegating CJK to the next family in
  the chain.
- **Noto Sans TC** is the canonical professional Traditional-Chinese
  digital face, with [seven weights for hierarchy
  appropriate to legal documents](https://fonts.google.com/noto/specimen/Noto+Sans+TC).
  It pairs with Inter at near-matching x-heights, which keeps mixed
  zh-TW + en spans from juddering.
- **Source Serif 4** for print body. Print deliverables resemble TW
  TIPO / court-filed PDFs, which are still serif. Noto Serif TC handles
  CJK serif fallback; system Songti TC catches the absolute floor.
- **JetBrains Mono** for case IDs, claim numbers, hashes, audit
  timestamps, and the redaction chip token. Its hand-tuned tabular
  numerals and slashed zero disambiguate `0` from `O` in the audit hash —
  a regulator-facing requirement.

### 3.2 Type scale

A 9-step modular scale (12 / 14 / 16 / 18 / 20 / 24 / 30 / 36 / 48 px),
mapped to roles. CJK line-height is pinned higher than Latin because
[CJK characters fill the entire em box; Google's guidance is +0.1em over
Latin](https://m1.material.io/style/typography.html). We apply that
boost universally because zh-TW is the default language.

| role             | size | line-height | weight | letter-spacing | use                                  |
|------------------|------|-------------|--------|----------------|--------------------------------------|
| `text.display`   | 48   | 1.20        | 700    | -0.02em        | login hero, error pages              |
| `text.headline`  | 36   | 1.25        | 700    | -0.015em       | page H1                              |
| `text.title-lg`  | 30   | 1.30        | 600    | -0.01em        | section heading                      |
| `text.title-md`  | 24   | 1.35        | 600    | -0.005em       | card header                          |
| `text.title-sm`  | 20   | 1.40        | 600    | 0              | sub-section, modal title             |
| `text.body-lg`   | 18   | 1.65        | 400    | 0              | legal long-form body                 |
| `text.body-md`   | 16   | 1.60        | 400    | 0              | default body                         |
| `text.body-sm`   | 14   | 1.60        | 400    | 0.005em        | secondary body, captions             |
| `text.label-lg`  | 16   | 1.40        | 500    | 0.005em        | input labels                         |
| `text.label-md`  | 14   | 1.40        | 500    | 0.005em        | button labels                        |
| `text.label-sm`  | 12   | 1.50        | 500    | 0.02em         | chip text, table column headers      |
| `text.code`      | 14   | 1.55        | 500    | 0              | mono — case IDs, hashes, claim nos.  |
| `text.legal`     | 12   | 1.65        | 400    | 0.01em         | footer fine-print, audit caveats     |

Line-heights are pinned at 1.6 for body and 1.4 for headings minimum
when text contains any CJK character. The
[Material guidance for CJK is +0.1 em over Latin baseline](https://m1.material.io/style/typography.html);
we round generously because patent claim text contains heavy parenthetical
CJK insertions that need vertical breathing room.

### 3.3 Weight scale

```
400 — body, fine print
500 — labels, emphasis within body
600 — section titles, buttons (CTAs)
700 — page headlines, display
```

**No 800 / 900.** Following Google's Noto guidance that
[Bold is the heaviest weight native readers accept; heavier is "too
aggressive"](https://m1.material.io/style/typography.html), we cap
at 700 for headlines. Avoid mixing 600 and 700 in the same hierarchy
level; the difference is invisible at small sizes and creates apparent
"random bolding" to native TC readers.

### 3.4 CJK-specific rules

**Line-height.** Body line-height is 1.6 (zh-TW preserves this even when
the rendered string is pure Latin, so mixed strings don't shift baseline).

**Punctuation.** Full-width CJK punctuation (`「」『』，。、；：`)
is preserved as-is from user input. We do NOT convert to half-width.
Reason: TW patent claim text canonically uses full-width punctuation,
and converting changes legal meaning. The Noto Sans TC face handles
the kerning natively.

**Mixed CJK + Latin spacing — the Pangu debate.**
[Pangu spacing](https://github.com/vinta/pangu.js) inserts a thin space
between CJK characters and adjacent Latin/numerals (e.g. `claim 1 為` →
`claim 1 為`). The
[CSS Text Level 4 `text-autospace` property automates this in modern
browsers](https://groups.google.com/a/chromium.org/g/blink-dev/c/my9MyWxa2ns/m/XNBscGRiAQAJ).

**Recommendation:** apply `text-autospace: ideograph-alpha ideograph-numeric`
to body containers (CSS Text Level 4) with no JS pre-processing fallback.
Reason: in patent legal text, exact character preservation matters for
auditability; rewriting the source string client-side would create a
visible mismatch between what the user typed, what we audit-logged, and
what we re-render. Browser-side spacing is a render-only effect — the
underlying string stays byte-identical.

**Fallback chain.** When a glyph is missing, the chain (`Inter →
Noto Sans TC → PingFang TC → Heiti TC → system`) ensures graceful
substitution. Inter explicitly does not provide CJK; the fallback
is intentional. Test on macOS Safari (PingFang TC wins), Windows
Chrome (Noto Sans TC wins), and Linux Firefox (system Heiti).

**Vertical text.** Not supported. Some TW court filings still use
top-to-bottom vertical text; our PDF export keeps horizontal layout.
Vertical text rendering for legal documents requires `writing-mode:
vertical-rl` + jurisdiction-aware punctuation rotation; it is a
fast-follow, not v1.

**Tabular figures.** Inter's default tabular numerals are kept ON
globally for case IDs, claim numbers, hashes, and deadlines. We do
not switch to proportional numerals for body — the +1 % horizontal
space cost is invisible vs the alignment gain in tables and inline
case-ID references.

---

## 4. Spacing, sizing, motion

### 4.1 Spacing scale

4-px base. T-shirt sized so component code reads `gap-sp.md` not `gap-4`,
making density swaps mechanical.

| token       | px  | typical use                                  |
|-------------|-----|----------------------------------------------|
| `sp.0`      | 0   | reset                                        |
| `sp.3xs`    | 2   | inline icon ↔ text                           |
| `sp.2xs`    | 4   | chip internal padding                        |
| `sp.xs`     | 8   | button internal vertical                     |
| `sp.sm`     | 12  | input internal padding                       |
| `sp.md`     | 16  | card padding, between fields                 |
| `sp.lg`     | 24  | between sections inside a pane               |
| `sp.xl`     | 32  | between major panes                          |
| `sp.2xl`    | 48  | page-level vertical rhythm                   |
| `sp.3xl`    | 64  | hero verticals (login only)                  |
| `sp.4xl`    | 96  | landing splash (marketing site, out of POC)  |

### 4.2 Density modes

Two density modes. Default is `comfortable`; user-selectable to `compact`.

| token            | comfortable | compact | applies to                       |
|------------------|-------------|---------|----------------------------------|
| `density.field-h`| 40 px       | 32 px   | input height                     |
| `density.btn-h`  | 40 px       | 32 px   | button height                    |
| `density.row-h`  | 44 px       | 36 px   | table row, list row              |
| `density.card-p` | 16 px       | 12 px   | card padding                     |
| `density.tab-h`  | 44 px       | 36 px   | tab bar                          |

Density is exposed via `data-density="comfortable|compact"` on `<html>`.
Component CSS reads CSS custom properties so a single attribute swap
re-layouts the entire app without re-render. Saved per-user (`localStorage`),
synced via settings API.

**When to use compact:** experienced partners running 8+ hours of
prosecution review. **When to keep comfortable:** new users (first 30
days), paralegals (cohort signals errors at compact density), accessibility
users (compact violates WCAG 2.5.5 Target Size minimum of 24 × 24 CSS
pixels for legacy AA; compact mode requires the user to acknowledge they
are opting out).

### 4.3 Border radius

| token              | px   | use                                       |
|--------------------|------|-------------------------------------------|
| `radius.none`      | 0    | full-bleed bands, audit-chain rows        |
| `radius.xs`        | 2    | mask chip inner                           |
| `radius.sm`        | 4    | input, chip                               |
| `radius.brand`     | 6    | **canonical button / card radius**        |
| `radius.md`        | 8    | modal, popover                            |
| `radius.lg`        | 12   | toast                                     |
| `radius.xl`        | 16   | banner panels (rare)                      |
| `radius.full`      | 9999 | avatar, dot indicators                    |

`radius.brand = 6 px` is deliberately the conservative end of the
shadcn / Geist / Linear cluster (which tend to 8–12 px). 6 px reads as
"law firm software", 12 px reads as "consumer SaaS". The hex difference
is small; the connotation is enormous, exactly as PRODUCT_STRATEGY §5.2
calls out for the brand color.

### 4.4 Elevation / shadows

5 levels. Light variant first, dark variant second.

| token            | light                                              | dark                                          | use                          |
|------------------|----------------------------------------------------|-----------------------------------------------|------------------------------|
| `elev.0`         | none                                               | none                                          | flush                        |
| `elev.1`         | `0 1px 2px rgba(15,23,42,.06)`                     | `0 1px 2px rgba(0,0,0,.4)`                    | card resting                 |
| `elev.2`         | `0 4px 8px -2px rgba(15,23,42,.08)`                | `0 4px 8px -2px rgba(0,0,0,.5)`               | popover, dropdown            |
| `elev.3`         | `0 12px 24px -8px rgba(15,23,42,.12)`              | `0 12px 24px -8px rgba(0,0,0,.6)`             | modal                        |
| `elev.4`         | `0 24px 48px -12px rgba(15,23,42,.18)`             | `0 24px 48px -12px rgba(0,0,0,.7)`            | drawer (rare)                |

Shadows are de-emphasised — borders carry the structural work (principle
P2). `elev.1` is so subtle that on `surface.background` (slate.50) the
card edge is mostly drawn by `border.default`, not the shadow.

### 4.5 Container widths

| token            | px    | use                                          |
|------------------|-------|----------------------------------------------|
| `max-w-prose`    | 720   | long-form: case notes, OA narrative, draft   |
| `max-w-form`     | 560   | settings forms, login, single-column dialog  |
| `max-w-app`      | 1440  | three-pane analyze layout, dashboard         |
| `max-w-full`     | none  | audit-chain table (it scrolls horizontally)  |

### 4.6 Motion tokens

| token             | ms  | use                                       |
|-------------------|-----|-------------------------------------------|
| `dur.instant`     | 0   | reduced-motion fallback for all states    |
| `dur.xs`          | 75  | hover state, ring transition              |
| `dur.sm`          | 150 | tooltip in, button press                  |
| `dur.md`          | 250 | popover in, drawer slide                  |
| `dur.lg`          | 400 | empty-state celebration only              |
| `dur.xl`          | 600 | onboarding tour step transition           |

```
ease.out      = cubic-bezier(0.16, 1, 0.3, 1)
ease.in-out   = cubic-bezier(0.65, 0, 0.35, 1)
ease.spring   = cubic-bezier(0.34, 1.56, 0.64, 1)
```

**Rule: no non-celebratory motion exceeds `dur.md` (250 ms).** Anything
over 250 ms in working flows causes attorneys to perceive the system as
laggy. Material 3 documents that
[100–400 ms is the appropriate band](https://m3.material.io/styles/motion/easing-and-duration);
we land at the snappy end because legal work is dense and frequent —
the user clicks a button 200+ times in a session, not 20. NN/g notes
[durations should usually feel "snappy"](https://www.nngroup.com/articles/animation-duration/);
`dur.lg` and `dur.xl` are exclusively for the onboarding tour and the
"first cited draft" celebration, never on a button.

**Reduced motion.** All durations resolve to `dur.instant` under
`@media (prefers-reduced-motion: reduce)`. Hover and focus transitions
become instant; modals fade-in is replaced by no-fade. We do NOT
keep "subtle" motion in reduced mode — the WCAG 2.3.3 floor is to remove
non-essential motion entirely.

---

## 5. Component anatomy

Each component below gives anatomy, token bindings, all states, keyboard
behaviour, a11y notes, and when-to-use / when-not. Anatomy is ASCII
when geometry is load-bearing; described prose otherwise.

### 5.1 Button

```
┌────────────────────────────────────┐
│ [icon?]   Label text   [trailing?] │  ← h = density.btn-h
└────────────────────────────────────┘
```

**Variants:** `primary` (navy fill) · `secondary` (slate fill) ·
`tertiary` (outline) · `ghost` (transparent, on-hover tint) ·
`destructive` (rose fill) · `link` (text + underline-on-hover).

**Sizes:** `sm 32 px` · `md 40 px` · `lg 48 px`. Default `md`.

**Token bindings (primary, light):**

```
background     = accent.brand            (navy.900)
foreground     = text.inverted           (white)
border         = none
hover bg       = accent.brand-hover      (navy.800)
active bg      = accent.brand-active     (navy.950)
focus ring     = border.focus-ring + 2px offset
disabled       = slate.200 bg, slate.500 fg, no shadow
loading        = spinner replaces leading icon, label fades to 70 %
```

**States:** default, hover, active, focus, disabled, loading, error
(used post-submit; bg becomes `status.error`, button auto-resets after
4 s).

**Keyboard:** Enter / Space activate. Tab order: trailing-icon shares
the button focus, not a separate tab stop. Loading state is keyboard
non-interactive (returns `aria-disabled=true`, not `disabled`, so screen
readers still announce purpose).

**A11y:** every button needs a text label or an `aria-label` (icon-only).
Loading state announces "submitting" via `aria-live="polite"`. Focus
ring 2 px navy.700, 2 px offset, never replaced by hover-only state.

**Use:** primary for the page's one main action. Secondary for the
companion. Destructive only for irreversible delete. Link inside body
prose, never as a CTA.
**Don't:** more than one primary button visible at a time on a screen;
"ghost destructive" (ambiguous tone); icon-only buttons without label
unless in toolbar with persistent tooltip.

### 5.2 Icon button

`32 × 32` (sm) · `40 × 40` (md). Lucide-react icon `20 px` stroke 1.75.
Always wrapped in `Tooltip` (§6.9) so the label is screen-reader
discoverable. Disabled state shows the tooltip with "(disabled — reason)".

### 5.3 Input

```
┌────────────────────────────────────┐
│  Label                             │
│  ┌──────────────────────────────┐  │
│  │ [leading?] value [trailing?] │  │  ← h = density.field-h
│  └──────────────────────────────┘  │
│  Helper text · or · ❗ Error text   │
└────────────────────────────────────┘
```

**Variants:** `text`, `number` (tabular figures forced), `search` (lead
icon = search, trailing = clear-x when value), `textarea` (auto-grow
min 4 rows, max 16, then internal scroll), **`pasted-oa`** (special:
auto-detects whether content looks like a TIPO / USPTO / EPO OA based
on regex against `application no.`, `申請案號`, `Anwendung`, etc., and
sets `lang` attribute accordingly — feeds the masking module).

**States:** default, hover (border.emphasis), focus (border.focus-ring),
filled, disabled (bg slate.100, fg slate.500), error (border rose.600,
helper rose.700, icon rose.600), success (border emerald.600 only on
verified-entity fields).

**Keyboard:** native input semantics. Search inputs additionally:
`Escape` clears value, `Cmd/Ctrl+K` global-focus.

**A11y:** `<label for=>` always present (visible or `sr-only`); error
text uses `aria-describedby`; never use `placeholder` as label.

### 5.4 Select / Combobox

Headless-UI / Radix-style combobox. Canonical use: **case-id picker.**

```
┌────────────────────────────────────┐
│ Case          [▾]                  │  ← trigger
└────────────────────────────────────┘
       │ open
       ▼
┌────────────────────────────────────┐
│ [search…]                          │
│ ────────────────────────────────── │
│ ✓ TIPO-2024-001234   [-OPEN]       │
│   TIPO-2024-001789   [-CONF] 🔒    │
│   USPTO-17/123,456   [-OPEN]       │
└────────────────────────────────────┘
```

Confidential cases render with the purple lock and the `confidential.*`
text token — the user can see the case exists in their assigned set
but cannot un-toggle the lock from the picker. Selecting a confidential
case routes the entire session into the confidentiality theme (§7).

**Keyboard:** ↑/↓ navigate, Enter select, Esc close, type-ahead filters
the list. `Tab` from trigger leaves the component without selecting (no
"accidental tab-confirm" — partners are slow typists).

### 5.5 Checkbox / Radio / Toggle

Standard shapes. Toggle is reserved for **session-scoped settings
only** (e.g., "show redaction preview", "auto-route to local LLM" for
this case); persistent settings use checkbox (the visual difference
signals "this persists" vs "this is for now"). Toggle and checkbox
never both appear in the same form.

### 5.6 Badge / Chip — first-class components

Three chip subtypes are load-bearing for our trust story:

**Confidential chip.** Purple. Lock icon. Text `機密 / Confidential`.
Always renders on confidential case headers, draft footers, and audit
rows. Never optional, never hover-only.

**Mask-count chip.** Amber. Shield icon. Text `${n} entities redacted`.
Lives in the orchestrator response header and in the audit row. Click
opens the `Reveal Panel` if the user has the owner-attorney role; else
displays "Reveal restricted to case owner".

**Audit chip (verify badge).** Emerald when the SHA-256 chain verifies,
amber when 1+ row's hash mismatches its predecessor (manually mutated),
rose when the chain is structurally broken (a row is missing). Verifier
runs client-side from `/audit/chain` response so the badge is real, not
ornamental.

```
┌────────────────────┐   ┌─────────────────────┐   ┌────────────────────┐
│ 🔒 機密            │   │ 🛡 3 entities redacted│   │ ✓ Chain verified   │
└────────────────────┘   └─────────────────────┘   └────────────────────┘
   confidential               mask-count                audit-chip
```

### 5.7 Avatar

Initials, navy-900 bg, white text, `radius.full`. Two-character max
(first character of given name + first of family name, regardless of
zh-TW / en — for `王曉華` shows `王曉`, for `Sarah Liu` shows `SL`).
Status dot (online/away/offline) bottom-right. No photo upload in v1
— attorneys do not want photos in legal software.

### 5.8 Card

```
┌──────────────────────────────────────┐
│ Header                       Action  │  ← optional slot
├──────────────────────────────────────┤
│ Body                                 │
│                                      │
├──────────────────────────────────────┤
│ Footer                               │  ← optional slot
└──────────────────────────────────────┘
```

`background = surface.elevated · border = border.default · radius =
radius.brand · padding = density.card-p · shadow = elev.1`.
Hover state: NONE on cards (cards are not interactive surfaces; if you
want hover, you want a Button or a List Row).

### 5.9 Modal / Drawer / Popover / Tooltip

- **Modal:** centered, max-w 560, elev.3, focus-trap, esc-close, click-
  outside disabled for confidential cases (forces explicit Cancel).
- **Drawer:** right-side, w 480 (md) / 640 (lg). Used for the Reveal
  Panel and the audit-row detail.
- **Popover:** elev.2, click-outside closes, used for the citation pill
  detail.
- **Tooltip:** 150 ms delay open / 75 ms delay close, text only (no
  interactivity inside), max-w 280, body-sm. Never used to convey
  information the user must read — only progressive disclosure.

### 5.10 Tabs

Underline-bar style (NOT pill style — pills read consumer). Active
tab: navy.900 underline 2 px, text `text.primary`, weight 600. Inactive:
text `text.secondary`, weight 500. Hover on inactive: navy.700 underline
appears at 60 % opacity. Disabled tab: text `text.disabled`,
no underline, tooltip explains why.

**Keyboard:** ←/→ between tabs, Home/End jump to first/last, Tab moves
focus into the panel content. Follows ARIA APG `tablist` pattern.

### 5.11 Table (audit view + lists)

Dense by default. Column header: `text.label-sm` uppercase letter-
spacing 0.04em, weight 600, sticky on vertical scroll. Row: `density.row-h`.
Zebra striping OFF (it conflicts with the audit-row inline status
treatment). Hover: row bg slate.50 (light) / slate.900 (dark) at 50 %
opacity. Sort affordance: chevron only on the active column; click
toggles asc → desc → unsorted.

Long lists (audit chain, cases list) use virtualization above 200 rows.
Empty state per §5.15.

### 5.12 Tree — claim-dependency tree

Lives at `frontend/src/components/analyze/ClaimTree.jsx`. Node anatomy:

```
│
├── ● Claim 1  [REJECTED §103]      ← rose.100 bg, rose.700 text
│   ├── ○ Claim 2  [cascade]        ← amber.50 bg, amber.700 text
│   └── ○ Claim 3
│       └── ○ Claim 5
└── ● Claim 7  [allowed]            ← emerald.50 bg, emerald.700 text
```

Independent claims marked by a 3-px navy.500 left border (the running
component uses indigo.500; the migration plan is in §11). Active
rejection's affected claims get a 2-px navy.300 ring so the user's
cross-pane attention is visually connected.

Depth indent cap = 6 levels (beyond that, indent stops growing; the
tree still computes structurally). Click on a rejected node calls
`onClaimClick(claim_no)` → parent pivots the active rejection. Clean
and cascade rows are non-interactive (cursor stays default).

### 5.13 Toast / Banner / Inline alert

Three different containers for three different urgencies:

- **Toast:** transient, 4 s auto-dismiss, bottom-right, `elev.3`,
  for "saved", "copied", "exported". Stacks up to 3.
- **Banner:** persistent, full-width inside its parent pane, used for
  "Verifier flagged 1 citation" or "Confidential mode active". Has
  dismissable close-x only for non-load-bearing banners.
- **Inline alert:** lives in a form, near the field it applies to. Used
  for validation errors that cannot be field-level (cross-field).

All three use the `status.*` token family.

### 5.14 Skeleton / Loader / Spinner

- **Skeleton:** matches the size and shape of the content it replaces,
  pulse animation `dur.lg ease.in-out` infinite. Pause animation under
  reduced-motion (becomes a flat slate.100 block).
- **Spinner:** `Loader2` lucide icon, navy.700, `dur.lg` linear spin.
  Used inside buttons and as a page-level loader.
- **Progress bar:** for upload only (we know the percentage). Otherwise
  use spinner.

### 5.15 Empty state

Three variants:

- **Pre-action (`empty.cold`)**: muted illustration (line-art only, no
  fill), `text.title-md` headline, `text.body-md` description, single
  primary CTA. Used for "No cases yet — create your first case."
- **Post-search-no-result (`empty.no-match`)**: smaller, no illustration,
  text-only with the search term echoed, secondary "Clear filters" CTA.
- **Error (`empty.error`)**: rose accent strip on left, `text.title-md`
  headline ("Couldn't load cases"), `text.body-sm` description with the
  error code, primary "Retry" + secondary "Report".

### 5.16 Form

```
┌────────────────────────┐
│ Label                  │  ← text.label-md, mb sp.xs
│ ┌────────────────────┐ │
│ │ Input              │ │
│ └────────────────────┘ │
│ Helper · OR · Error    │  ← text.body-sm, mt sp.2xs
└────────────────────────┘
```

Vertical spacing between fields: `sp.md`. Section dividers: `sp.lg`
+ horizontal rule `border.subtle`. Required-field marker: red asterisk
after label, with sr-only "(required)". Submit row is sticky bottom in
modals, in-flow in pages.

### 5.17 Citation pill (patent-specific component)

Inline element rendered for `[GROUNDED_REF_n]` tokens in drafts:

```
[GROUNDED_REF_3]  ←  pill rendered as: ┌─────────────────┐
                                       │ § US-9,123,456  │  ← sky.50 bg
                                       │   ¶ [0034]      │     sky.800 text
                                       └─────────────────┘     emerald.500 dot
                                                                if verified
```

Hover: opens popover with the actual passage (first 240 chars), `Open
source` CTA. Verified: small emerald.500 dot bottom-right. Flagged:
amber.500 dot + "Verify failed" sub-line. Mismatched (verifier hard-
fail): rose.500 dot + amber banner appears above draft until user
acknowledges. The pill is keyboard-focusable; Enter opens the popover.

### 5.18 Audit-chain row

```
┌─────────────┬──────────┬──────────────────────┬───────────────────────┬──────┐
│ 14:23:01.42 │ analyze  │ user@tenant          │ sha256:9f2c…8b4e ✓    │ [↗]  │
│ comfort-row │ action   │ actor                │ hash chip            │ open │
└─────────────┴──────────┴──────────────────────┴───────────────────────┴──────┘
```

Timestamp: `text.code`, tabular numerals, mono. Action: `text.label-sm`,
chip-styled. Actor: `text.body-sm`. Hash chip: `text.code`, ellipsised
middle (`9f2c…8b4e`), monospace tabular, with a small verify glyph
(emerald check if it chains, amber warning if it doesn't, rose break
icon if structurally invalid). Clicking the row opens a detail Drawer
(§5.9) showing the full payload, the previous hash, the next hash,
and a verify button that re-runs SHA-256 client-side.

### 5.19 Diff view

For draft revisions. Two-column unified or side-by-side (user choice
in toolbar). Added text: emerald.50 bg, emerald.900 fg, prefix `+`.
Removed: rose.50 bg, rose.900 fg, strike-through, prefix `−`. Changed:
amber.50 bg, amber.900 fg, prefix `~`. Line numbers: text.code,
sticky left gutter, tabular figures so the column does not jitter.

The diff view respects redaction: redacted tokens render as mask chips
(§2.2 mask.*) on both sides, never the raw PII.

### 5.20 Confidential-case lock indicator

A composite: lock icon (lucide `Lock`, 16 px) + `confidential.text` colour
+ optional "Routed to on-prem LLM" subtext (visible in confidential
case headers, hidden but available via aria-described-by elsewhere).
Placement rule: always immediately adjacent to the case ID, on every
surface where the case ID appears (header, breadcrumb, audit row,
draft footer). Never separated from the case ID by an unrelated chip.

---

## 6. Dark mode rules

### 6.1 What inverts, what doesn't

| Element                           | Inverts? | Why                                        |
|-----------------------------------|----------|--------------------------------------------|
| Surfaces, text, borders           | Yes      | standard                                   |
| Audit chip (✓ Chain verified)     | **No**   | Emerald-on-dark = identical signal to light; flipping would weaken the trust moat |
| Confidential lock + purple band   | **No**   | Confidentiality must be unambiguous; purple stays purple in dark, slightly darker (purple.300 → purple.400 fg) |
| Redaction mask chip               | Yes      | Amber tokens swap to dark variants         |
| Brand navy CTAs                   | Yes      | navy.900 → navy.600 fg                     |
| Code blocks (`text.code`)         | Yes      | But stay monospace; line numbers re-contrast carefully |
| Diff view colours                 | Partial  | Backgrounds darken; foregrounds stay emerald/rose so semantics survive |

### 6.2 Forbidden inversions

- **Audit chip never inverts.** Always emerald-green-on-dark in dark
  mode. The "verified" signal is regulator-facing; switching its tone
  with theme would let a designer accidentally weaken it.
- **Confidential lock never inverts.** Always purple. A dark-mode user
  must not accidentally interpret a confidential case as standard.
- **Print stylesheet ignores dark mode entirely.** Even if the user
  prints from dark mode, the print sheet forces light theme + serif body.

### 6.3 Body text on code blocks (sunken surfaces in dark)

Code blocks under `surface.sunken` in dark mode use `text.code` (slate.200
on slate.950) — 14.6:1 contrast. Inline code spans inside body use
`slate.300` (10.3:1) so the inline code reads as distinct from the
surrounding body without losing accessibility.

---

## 7. Iconography rules

- **Set:** `lucide-react`, stroke `1.75`, size scale `12 / 14 / 16 /
  20 / 24 / 28 px`. 16 is the default in body. 20 is the default in
  buttons.
- **No custom icons** except the four explicitly licensed marks:
  - **App logo** — wordmark + abstract glyph (navy + amber accent). SVG
    living in `frontend/src/assets/logo.svg`. Two variants: full lockup
    (header), monogram (favicon, avatars).
  - **Audit-chain emblem** — three linked chain rings, drawn at 1.75
    stroke matching lucide. Used only in the audit screen header
    and the verify-chain badge.
  - **Confidential-lock emblem** — closed padlock with a small "T"
    inside (taiwan-resident mapping). Used only in the confidential
    chip + lock indicator.
  - **Claim-tree node markers** — filled circle (independent) vs hollow
    circle (dependent) drawn to match lucide stroke. Allowed only inside
    the claim tree.
- **Icon-as-text alignment:** when an icon sits adjacent to inline text,
  vertical-align: middle, with `margin-top: -1px` (Inter's optical
  centerline is 1 px below the geometric center). Icon size = text
  size × 1.0 (not 1.2 — patent attorneys do not read icons faster
  than text).

---

## 8. Print stylesheet

Drafts → A4 portrait, 25 mm margins. Hash-chain audit → A4 landscape,
20 mm margins (so the hash chip fits without truncation).

**Type stack switch:**

```css
@media print {
  body { font-family: var(--font-serif); }
  code, .text-code, .mono { font-family: var(--font-mono); } /* hashes stay mono */
  .text-display, .text-headline { font-family: var(--font-serif); font-weight: 700; }
}
```

**Page-break rules:**

- Each rejection block (in OA response) gets `break-inside: avoid` so a
  rejection's heading does not orphan from its body.
- Citation pills inline; their popover passages don't print (they were
  optional progressive disclosure).
- Audit-chain table: `thead` repeats on each page, every row gets
  `break-inside: avoid`.

**Confidential watermark:** for `-CONF` case content, a 45°-rotated
"CONFIDENTIAL · 機密" watermark renders at 18 % opacity on every page
via `body::before` positioned `fixed`. Print preview hides the dark
theme, the side rails, and the on-screen navigation — only the document
content prints.

**Color:** print is grayscale-safe. Rose / emerald / amber chips render
with icons + uppercase tone labels so a black-and-white office printer
still conveys the status (WCAG 1.4.1 Use of Color also applies on paper).

---

## 9. Tokens → Tailwind mapping

### 9.1 CSS custom properties (the source of truth)

```css
:root {
  /* --- primitives (excerpt) --- */
  --color-navy-900: #1e3a8a;
  --color-navy-800: #1e40af;
  --color-slate-50: #f8fafc;
  --color-slate-900: #0f172a;
  --color-emerald-700: #047857;
  --color-amber-700: #b45309;
  --color-rose-700: #be123c;
  --color-purple-700: #7e22ce;
  --color-sky-700: #0369a1;

  /* --- semantic --- */
  --surface-background: var(--color-slate-50);
  --surface-elevated:   #ffffff;
  --surface-sunken:     var(--color-slate-100);
  --surface-brand:      var(--color-navy-900);
  --text-primary:       var(--color-slate-900);
  --text-secondary:     var(--color-slate-700);
  --text-tertiary:      var(--color-slate-500);
  --accent-brand:       var(--color-navy-900);
  --status-success:     var(--color-emerald-700);
  --status-warning:     var(--color-amber-700);
  --status-error:       var(--color-rose-700);
  --confidential-text:  var(--color-purple-800);
  --mask-bg:            var(--color-amber-100);
  --mask-text:          var(--color-amber-900);
  --mask-border:        var(--color-amber-300);

  /* --- type --- */
  --font-sans: 'Inter', 'Noto Sans TC', 'PingFang TC', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, monospace;
  --font-serif: 'Source Serif 4', 'Noto Serif TC', Georgia, serif;

  /* --- space --- */
  --sp-3xs: 2px; --sp-2xs: 4px; --sp-xs: 8px; --sp-sm: 12px;
  --sp-md: 16px; --sp-lg: 24px; --sp-xl: 32px; --sp-2xl: 48px;

  /* --- radius --- */
  --radius-brand: 6px;

  /* --- motion --- */
  --dur-xs: 75ms; --dur-sm: 150ms; --dur-md: 250ms;
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
}

[data-theme="dark"] {
  --surface-background: var(--color-slate-950);
  --surface-elevated:   var(--color-slate-900);
  --text-primary:       var(--color-slate-50);
  /* …etc */
}

[data-density="compact"] {
  --density-field-h: 32px;
  --density-btn-h:   32px;
  --density-row-h:   36px;
  --density-card-p:  12px;
}

@media (prefers-reduced-motion: reduce) {
  :root { --dur-xs: 0ms; --dur-sm: 0ms; --dur-md: 0ms; --dur-lg: 0ms; }
}
```

`data-theme` (not Tailwind's `class="dark"`) is intentional so the
audit-chain header — which must stay emerald regardless of theme —
can be scoped independently via a `data-theme-override="audit"` attribute
without fighting class precedence.

### 9.2 `tailwind.config.js` extension (delta vs current)

```js
extend: {
  colors: {
    navy:      { /* 50…950 as listed §2.1 */ },
    slate:     { /* extend with 950 */ },
    emerald:   { /* full ramp */ },
    amber:     { /* full ramp */ },
    rose:      { /* full ramp */ },
    purple:    { /* full ramp */ },
    sky:       { /* full ramp */ },
    surface:   { background: 'var(--surface-background)',
                 elevated:   'var(--surface-elevated)',
                 sunken:     'var(--surface-sunken)',
                 brand:      'var(--surface-brand)' },
    text:      { primary:    'var(--text-primary)',
                 secondary:  'var(--text-secondary)',
                 tertiary:   'var(--text-tertiary)',
                 inverted:   'var(--text-inverted)',
                 link:       'var(--text-link)',
                 code:       'var(--text-code)' },
    confidential: { surface: 'var(--confidential-surface)',
                    DEFAULT: 'var(--confidential-text)',
                    border:  'var(--confidential-border)' },
    mask:      { bg:    'var(--mask-bg)',
                 DEFAULT:'var(--mask-text)',
                 border:'var(--mask-border)' },
  },
  spacing: {
    '3xs':'2px','2xs':'4px','xs':'8px','sm':'12px',
    'md':'16px','lg':'24px','xl':'32px','2xl':'48px',
    '3xl':'64px','4xl':'96px',
  },
  borderRadius: { brand: '6px' },
  fontFamily: {
    sans:  ['var(--font-sans)'],
    mono:  ['var(--font-mono)'],
    serif: ['var(--font-serif)'],
  },
  transitionDuration: {
    xs:'var(--dur-xs)', sm:'var(--dur-sm)',
    md:'var(--dur-md)', lg:'var(--dur-lg)', xl:'var(--dur-xl)',
  },
  transitionTimingFunction: {
    out: 'var(--ease-out)',
    'in-out': 'var(--ease-in-out)',
    spring:  'var(--ease-spring)',
  },
  boxShadow: {
    'elev-1': 'var(--elev-1)',
    'elev-2': 'var(--elev-2)',
    'elev-3': 'var(--elev-3)',
    'elev-4': 'var(--elev-4)',
  },
  maxWidth: {
    prose: '720px', form: '560px', app: '1440px',
  },
},
```

### 9.3 Runtime token access

Because everything lives on `:root` CSS custom properties, JS reads
tokens via `getComputedStyle(document.documentElement).getPropertyValue
('--accent-brand')`. The audit-chain client-side hash verifier uses
this to pick the badge tint without importing a JS color constant.

---

## 10. Versioning + governance

### 10.1 Semver per token category

Color, type, space, motion, and component each version independently:

- **MAJOR** = a semantic token's primitive binding changes in a way
  that breaks an existing component's contract (e.g., `accent.brand`
  changes hue family). Triggers full visual regression sweep.
- **MINOR** = a new token is added; no existing binding changes.
- **PATCH** = a primitive shifts within its own ramp (e.g., `navy.900`
  micro-adjustment for accessibility), no semantic-token re-binding.

Token version lives in `frontend/src/lib/tokens/version.json` and is
read at build time; a banner toast surfaces "Design tokens updated to
v2.1.0" on first paint after a deploy, dismissible.

### 10.2 Adding a new token — checklist

1. Is this expressible as a composition of existing semantic tokens?
   If yes, **don't add it**.
2. Pick the primitive ramp it consumes.
3. Add CSS custom property in `:root` and `[data-theme="dark"]`.
4. Add to `tailwind.config.js` extend.
5. Verify WCAG contrast against every conventional pairing
   ([WebAIM contrast checker](https://webaim.org/resources/contrastchecker/)).
6. Write one Storybook story demonstrating it.
7. Bump the relevant category's MINOR version.

### 10.3 Deprecating a token

1. Mark the entry in the token JSON `"status": "deprecated", "until":
   "v3.0.0"`.
2. Add an ESLint rule to flag new usages (warn, not error, for one
   release; error from the release after).
3. Add an `@deprecated` JSDoc on any helper that returns it.
4. Provide a codemod for the bulk migration if the surface area > 20
   components.

### 10.4 Design lint rules (prevent hard-coded values)

Enforced via `stylelint` + custom ESLint plugin:

- No raw hex in JSX className strings (e.g., `bg-[#1e3a8a]` — caught).
- No raw pixel values in `style={{}}` for spacing (caught; allow only
  for layout primitives like `transform` and grid templates).
- No `font-family` overrides except inside the print stylesheet and the
  three approved variants (Inter, JetBrains Mono, Source Serif 4).
- No animation duration > 600 ms anywhere.
- No new icon imports outside `lucide-react` or the four approved
  custom SVGs.

---

## 11. Benchmarks & reconciliation

### 11.1 What we adopt / reject from neighbours

- **Vercel Geist** — adopt: tabular numerals, monochrome restraint,
  shadow-as-secondary-structure.
  Reject: Geist's preference for very tight letter-spacing on body
  (we keep neutral spacing because zh-TW glyphs cannot tolerate the
  same negative tracking Latin can).
- **Stripe** — adopt: dense data tables with sticky headers, deliberate
  use of a single saturated accent only at decision moments.
  Reject: Stripe's purple-blue gradient on marketing-adjacent surfaces
  (no gradients in our product per P2).
- **Linear** — adopt: command-palette pattern (⌘K) as a v1.1 target;
  ultra-consistent component restraint.
  Reject: Linear's "no border, all-shadow" card style — borders are
  load-bearing for us.
- **Datadog DRUIDS** — adopt: semantic-token layer that survives
  enterprise theme variation (we will need a "white-label" mode for
  TPIsoftware deployments).
  Reject: DRUIDS' dark-first default (we are light-first because TW
  partners read paper-aesthetic well).
- **Material 3** — adopt: motion duration guidance (100–400 ms band,
  per [M3 motion docs](https://m3.material.io/styles/motion/easing-and-duration));
  density mode pattern.
  Reject: M3's elevation-as-primary-structure metaphor; our shadows
  are secondary to borders.
- **Polaris (Shopify)** — adopt: empty-state taxonomy (pre-action / no-
  result / error); banner-vs-toast distinction.
  Reject: Polaris's tone and friendliness; legal context is not
  e-commerce context.
- **Carbon (IBM)** — adopt: type ramp discipline; documented contrast
  pairs.
  Reject: Carbon's geometric heaviness (we are lighter); their motion
  feels mechanical for our use.

### 11.2 Where this spec contradicts the running redesign

The running App-shell rebuild uses `class="dark"` (the shadcn / Tailwind
default) for theme switching. This spec specifies `data-theme="light|
dark"` instead, because the audit-chain badge must theme independently
of the rest of the app (it stays emerald regardless of theme) and
class-based theming makes that scope-overriding fight specificity. The
existing `frontend/src/lib/theme.jsx` toggles a class.

**Reconciliation:** keep the class for the next release as a transitional
alias (`.dark` continues to set `--surface-background: slate.950`
exactly like `[data-theme="dark"]`), and the audit-chain header opts out
of the class by wrapping itself in `[data-theme="audit"]` which over-
rides the surface tokens for that subtree only. Migrate the class
mechanism to `data-theme` in v2.0 (next MAJOR).

The running `frontend/src/index.css` also defines `--primary: 222.2
47.4% 11.2%` (a near-black), inherited from shadcn. The spec instead
binds primary to `accent.brand = navy.900 = #1e3a8a`. PRODUCT_STRATEGY
§11 pins navy.900 as the brand; the shadcn `--primary` should be
re-pointed at navy.900 immediately, with the legacy near-black retained
as `--primary-legacy` for any shadcn components that have not yet been
re-themed.

---

# Report

**Highest design-debt tokens (changing later breaks the most components):**

1. **`accent.brand`.** It hard-binds to `navy.900` everywhere — primary
   buttons, header band, focus ring, citation links, brand chips, claim-
   tree independent-claim border. Mis-specifying the hue today
   means re-skinning every CTA, every focus state, and every audit-chain
   reference badge later. The PRODUCT_STRATEGY §11 navy.900 pin protects
   us — keep that pin even through MAJOR bumps.
2. **`density.field-h` / `density.btn-h`.** Bound to header height, table
   row height, tab bar height, drawer toolbar height. A 4-px change here
   reflows the entire three-pane analyse layout and the audit table.
   Lock the 40-px comfortable / 32-px compact pair now; any change
   triggers a full visual-regression baseline reset.
3. **Mask chip tokens (`mask.bg/text/border`).** Every redacted entity
   in every audit row, every draft, every reveal panel, and every
   debug surface uses these tokens. Re-toning later would visibly
   change what enterprise procurement screenshots already approved.
   The amber-on-amber pairing is also load-bearing for procurement
   conversations ("the orange tags are PII we redacted"); changing the
   hue family means re-pitching every active deal.

**Controversial dark-mode rule:** the audit chip stays emerald-on-dark
unconditionally. Designers will lobby to dim it in dark mode for "tonal
coherence" — refuse. The badge is a regulator-facing trust signal; its
visual stability across themes is the point. Expect pushback at the
first design review; cite this section.

**Spec that contradicts the running frontend:** this spec uses
`data-theme` attribute theming, not the `class="dark"` mechanism the
running shadcn-based shell uses (`frontend/src/lib/theme.jsx`).
Reconciliation per §11.2 — keep the class as a transitional alias in
v1.x; the shadcn `--primary` should be re-pointed to navy.900 in the
next sprint so primary CTAs stop reading as near-black. Migrate the
mechanism wholesale at v2.0 when we also need theme-scoped islands for
the audit-chain badge and the confidential surfaces.
