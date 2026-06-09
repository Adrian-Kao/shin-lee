# PatentMind — MVP to Product Strategy (2026-06-05)

> Author: Strategy research agent. Audience: the frontend redesign agent that will
> ship the next sprint. Scope: turn the POC into something a TW or US patent firm
> will actually pay for. Read-only research — no code touched.

---

## 0. TL;DR (the 7 bullets your sprint-planning email needs)

1. **Current state: dangerously demo-shaped.** The frontend is a single-flow
   "login → analyze → audit" POC. It has no account self-serve, no settings,
   no billing surface, no admin, no notification center, no real cases list,
   no in-app help, and only partial i18n. None of those gaps stop a demo —
   every one of them stops a sale. Procurement security questionnaires now
   contain [200+ questions and add 4-8 weeks to enterprise SaaS sales cycles](https://www.workstreet.com/blog/security-compliance-questionnaires);
   if our UI can't *visibly* answer "where does the data live, who saw it,
   how is it logged," we never get to the demo.
2. **Top 3 must-ship-pre-launch frontend gaps:**
   (a) **Cases list + Case detail** (the only screen that signals "this is a
   real product, not a hello-world"); (b) **Settings + Profile + tenant admin
   panel** with RBAC for the 4 roles already in the backend (Attorney /
   Paralegal / IT Admin / Auditor); (c) **First-run onboarding tour** with a
   < 5-minute "time to first analyzed OA" — [B2B SaaS PLG benchmarks
   require activation in under 1-7 days](https://www.userpilot.com/saas-product-metrics/),
   and [if users don't activate in 3 days, conversion probability drops 68%](https://www.userpilot.com/saas-product-metrics/).
3. **Top 3 trust signals to surface:** (a) **Audit chain visible from
   anywhere** — the SHA-256 hash-chained log is our biggest moat and is
   currently buried in a tab Dave-the-auditor accesses; bring "tamper-evident"
   into the result header. (b) **"Confidential — routed to on-prem LLM"
   badge** on every case (Q15 enforces it; UI doesn't surface it).
   (c) **Mapping table residency badge** — "PII never left Taiwan" in the
   footer of every analysis. These are the three things [BigLaw procurement
   asks about first in 2026](https://getperspective.ai/blog/harvey-ai-forward-deployed-engineers-biglaw-deployment-playbook-2026):
   data boundaries, governance, reviewable audit trail.
4. **Recommended pricing model: hybrid per-seat + per-OA, no freemium, opt-out
   14-day trial.** [Per-seat enterprise legal AI ranges from $50-$1,500/seat-month](https://thelegalprompts.com/blog/ai-legal-tools-pricing-comparison);
   [Patentext-style per-draft pricing starts at $200/draft](https://blog.patentext.com/blog-posts/best-ai-patent-drafting-tools).
   For TW firms with 5-30 patent attorneys, hybrid wins: $150-$300/seat-month
   floor + $30-$50/OA over quota. [Opt-out trials convert at ~31% vs opt-in's
   ~9%](https://www.amraandelma.com/free-trial-conversion-statistics/) — but
   law firms WILL NOT enter a credit card. Solution: sales-assisted trial
   that *behaves* like opt-out (PO/MSA gates the conversion event, no
   credit card).
5. **Activation hook = "first cited draft in under 5 minutes."** Patent
   attorneys' AI "aha moment" is not speed — it's [finding a citation they
   would have missed and seeing the prior-art passage land in their draft
   with provenance intact](https://www.deepip.ai/blog/top-ai-tools-patent-attorneys-are-using-to-boost-efficiency).
   Design the onboarding so users see a draft response with a clickable
   `[GROUNDED_REF_n]` citation, then hover and see the actual prior-art
   sentence highlighted. That's the conversion moment.
6. **Single biggest competitive wedge: on-prem + tamper-evident audit + TW
   bilingual.** Harvey, Patlytics, DeepIP, Solve Intelligence all run in US
   cloud. [Lee and Li's privacy policy explicitly states data does not leave
   Taiwan unless instructed](https://www.leeandli.com/EN/000000318.htm);
   that's not a Lee-and-Li quirk, that's the procurement floor for the top
   10 TW patent firms. TPIsoftware's digiRunner (which we mock as our
   gateway) is [already on Gartner Peer Insights and just rebranded as an
   "AI gateway" with on-prem deployments at Taishin Bank and EnTie Bank](https://www.gartner.com/reviews/product/digirunner).
   We are the only patent AI tool that ships natively into this on-prem stack.
   Lead with that.
7. **Visual identity: conservative law firm, NOT modern startup.** Harvey
   defines design as ["deeply familiar, yet unmistakably modern… polish and
   precision is synonymous with credibility"](https://www.harvey.ai/blog/how-we-approach-design-at-harvey).
   For TW firms (median founding year 1965-1985, partner-driven culture),
   tilt harder toward "familiar" than "modern". Specific: dark navy
   (`#1e293b` slate-800 we already use) over indigo accents; Noto Sans TC
   for body, monospace for case IDs / claim numbers; serif headings only
   inside printed PDF exports; never use the playful CDN-Tailwind defaults
   for client-facing screens.

---

## 1. Market positioning (TW + US, 2026)

### 1.1 The market shape

- **AI in legal practice is no longer optional.** [Individual AI use among
  legal professionals jumped to 69% in early 2026 — more than doubling in a
  single year](https://www.deepip.ai/blog/top-ai-tools-patent-attorneys-are-using-to-boost-efficiency).
  [Patent litigation audiences show near-universal AI use, higher than the
  30% the ABA's 2024 survey reported for all lawyers](https://www.law.berkeley.edu/research/bclt/bcltevents/26th-annual-berkeley-stanford-advanced-patent-law-institute/ep-summary-26apli/day-2-panel-5-litigation-ai-tools-and-litigation/).
- **Patent AI is consolidating to a top 5.** [Harvey now counts 42% of AmLaw
  100 firms as customers](https://www.fastcompany.com/91502697/harvey-most-innovative-companies-2026)
  but is general legal AI, not patent-specific. The patent-specific top tier
  is Patlytics (40%+ AmLaw 100, [$40M Series B April 2026, total $65M raised
  in 2.5 years](https://www.alleywatch.com/2026/04/patlytics-ai-patent-platform-ip-lifecycle-management-legal-tech-paul-lee/)),
  DeepIP ($25M Series B March 2026, total $40M), Solve Intelligence
  ([$40M Series B Dec 2025 led by M12 and Thomson Reuters Ventures, total
  $55M](https://www.solveintelligence.com/blog/post/solve-intelligence-raises-40m-series-b-to-build-ai-for-patents-and-launches-charts)),
  Rowan, Patentext.
- **Market size.** [Patent analytics market is $1.34B in 2026, projected
  $3.4B by 2032 at 12.3% CAGR](https://www.alleywatch.com/2026/04/patlytics-ai-patent-platform-ip-lifecycle-management-legal-tech-paul-lee/).
  The [legal practice management software market is $2.06B in 2024 growing
  to $4.81B by 2030 at 15.20% CAGR](https://www.thelawgpt.com/blog/legal-practice-management-software).
- **The market is shifting from general legal AI → domain-specific.**
  [The legal market is pulling away from general-purpose legal AI toward
  domain-specific AI built for discrete legal subfields; firms that adopt
  specialized tools outperform those trying to retrofit broad legal tech
  platforms](https://natlawreview.com/article/85-predictions-ai-and-law-2026).
  Patent AI is the canonical example. This is a tailwind for us.

### 1.2 Pricing benchmarks (the most important table in this doc)

| Tool / class | Model | Price (USD) | Source |
|---|---|---|---|
| Harvey | Per-seat, annual | $1,200-$1,500/seat-month (mid-market), $1,500-$2,000+ (AmLaw 100), 25-seat min | [costbench.com](https://costbench.com/software/ai-legal-tools/harvey-ai/) |
| Harvey | Annual all-in (50-attorney firm) | $720k - $1.2M / year | [costbench.com](https://costbench.com/software/ai-legal-tools/harvey-ai/) |
| Patlytics | Enterprise per-seat | not public; reports of $300-$500/seat-month | [softwarefinder.com](https://softwarefinder.com/legal/patlytics) |
| DeepIP | Per-seat | $350-$420/user-month, annual | [thelegalprompts.com](https://thelegalprompts.com/blog/ai-legal-tools-pricing-comparison) |
| Solve Intelligence | Per-seat tier | starts $199/month | [eesel.ai](https://www.eesel.ai/blog/solve-intelligence-pricing) |
| Patentext | Per-draft | $200/draft, no seats, no minimum | [patentext.com](https://blog.patentext.com/blog-posts/best-ai-patent-drafting-tools) |
| Task tools (per-OA response) | Per-document | $25-$100 starter tiers, $49/OA-response export | [thelegalprompts.com](https://thelegalprompts.com/blog/ai-legal-tools-pricing-comparison) |
| AI.Law | Hybrid | per-case + per-seat | [ai.law/pricing](https://www.ai.law/pricing/) |

**Read of the table.** The market has bifurcated. Top tier (Harvey, Patlytics,
DeepIP) is per-seat enterprise contracts with 25-seat minimums and 6-month
sales cycles — [Harvey's typical sales cycle runs 6+ months with initial
quotes negotiable down 40-60%](https://thelegalprompts.com/blog/ai-legal-tools-pricing-comparison).
Bottom tier (Patentext, task tools) is per-document, no commitment. **There
is a clear gap in the middle for hybrid: per-seat floor + per-OA usage above
quota, with no 25-seat minimum**, that fits TW firms with 5-30 patent
attorneys and US small/mid IP boutiques. That is our pricing target.

### 1.3 Who's buying, who's holding off

**Buying:**

- AmLaw 100 + larger boutiques. [Harvey's 42% of AmLaw 100 is the proxy](https://www.fastcompany.com/91502697/harvey-most-innovative-companies-2026).
  Patlytics customers include [Canon, Rivian, Xerox, Asahi Kasei, TaylorMade,
  plus 40%+ AmLaw 100](https://www.alleywatch.com/2026/04/patlytics-ai-patent-platform-ip-lifecycle-management-legal-tech-paul-lee/).
- Corporate in-house IP teams that need to internalize work pressure-tested
  against outside counsel. [In-house teams will treat outside counsel's AI
  posture as a procurement requirement in 2026](https://gc.ai/blog/best-legal-ai-tools-for-in-house-counsel).
- TW firms with cross-border practice (Lee and Li, Tai E, Saint Island).
  [Lee and Li has ~860 employees including 100+ patent attorneys and 100+
  technology experts](https://chambers.com/office/lee-and-li-attorneys-at-law-taipei-taiwan-jurisdiction-greater-china-region-116:2315).
  [Tai E has 270+ professionals across four TW offices](https://www.ipstars.com/Firm/Tai-E-International-Patent-Law-Office-Taiwan/Profile/102270).

**Holding off:**

- Sub-10-attorney firms where ROI math fails at $300/seat-month (this is
  the Patentext-style per-draft segment).
- Firms under partner-by-partner adoption autonomy. [BigLaw deployment
  needs forward-deployed engineers because three structural features —
  strict confidentiality, on-prem/private-cloud data residency, partner-by-
  partner adoption autonomy — make self-serve SaaS rollouts mathematically
  impossible](https://getperspective.ai/blog/harvey-ai-forward-deployed-engineers-biglaw-deployment-playbook-2026).
- TW firms with no English-fluent IT (we win here by shipping zh-TW first).

**Why they're holding off:** [The primary objection in IPWatchdog's May 2026
analysis is client overconfidence in AI capabilities, creating unrealistic
cost expectations — clients assume AI dramatically reduces labor and want
the savings passed through](https://ipwatchdog.com/2026/05/15/patent-law-firms-face-ai-squeeze-as-clients-internalize-more-work/).
For firms, [the differentiator between winners and losers is repositioning
value around strategy and judgment rather than throughput](https://ipwatchdog.com/2026/05/26/patent-law-firms-face-ai-reckoning/).
Our UI should reinforce "judgment-amplifier" framing, not "labor-replacer."

### 1.4 TW-specific gates

- **TIPO does not publish AI examination guidelines yet** — it published a
  [determination procedure for AI-related patent applications](https://www.aipla.org/list/innovate-articles/patent-eligibility-of-ai-technology-inventions-in-taiwan-and-analysis-of-filing-strategies)
  but [no comprehensive AI examination guidelines](https://www.aipla.org/list/innovate-articles/patent-eligibility-of-ai-technology-inventions-in-taiwan-and-analysis-of-filing-strategies).
  Practical effect: TW firms are free to use AI for OA response drafting
  but have no regulatory cover. They lean conservative. We need to
  *visibly* be conservative.
- **Taiwan's AI Basic Act took effect January 14, 2026.** [It establishes
  the government's foundational stance on AI as a guiding framework for
  future regulation](https://iapp.org/news/a/taiwan-s-strategic-leap-into-ai-enacting-the-ai-basic-act-to-foster-innovation-governance).
  Practical effect for us: data residency claims need to be auditable, not
  marketing.
- **2026 TIPO operational changes:** [Deferred Substantive Examination
  guidelines take effect Jan 1, 2026](https://www.lexology.com/library/detail.aspx?g=54a2481d-467e-406f-b38b-f7ccc9a6f07d);
  [IPC version 2026.01 starts March 6, 2026](https://www.tipo.gov.tw/en/tipo2/324.html);
  [Industry Collaborative Patent Interview Pilot extended through Dec 31,
  2026](https://www.tipo.gov.tw/en/tipo2/324-21836.html). UI must let
  jurisdiction-aware deadline rules be hot-swapped without redeploy.

---

## 2. The MVP → product gap (annotated audit)

The product audit is structured against the [27-item SaaS launch checklist](https://infinitysky.ai/blog/saas-launch-checklist-before-going-live)
and the [B2B legal SaaS hybrid PLG/SLG model](https://www.growthspreeofficial.com/blogs/plg-product-led-growth-b2b-saas-hybrid-2026).

### 2.1 What we have (good)

| Area | State | Comment |
|---|---|---|
| Three-pane analyze workspace | Done (Day 8E) | InputPane / DraftsPane / ReferencesPane with desktop grid, mobile tab strip. Good. |
| Login + role-based demo users | Done | 4 roles: Attorney / Paralegal / IT Admin / Auditor. Demo style, not production. |
| Audit log view + chain verify | Done | But buried in a separate route; auditor-only mental model. |
| Result summary bar (policy chips + deadline) | Done | This is good trust signaling. Keep. |
| Mobile responsive (xl breakpoint) | Done | But the breakpoint is 1280px — most attorney monitors are 1920px wide, so this is fine for desktop, but tablet usage in TW firms (iPad Pro on partner desks) is unaccounted for. |
| Skeleton + error banners + empty states (partial) | Done | EmptyState component exists; not used in cases list (no cases list). |
| i18n scaffold (react-i18next) | Partial | Shell strings only; component bodies still ship bilingual hardcoded strings in JSX (see Analyze.jsx tabs "輸入 / Input"). |
| Toast + Sentry stub | Done | Good. |

### 2.2 What we lack — must-ship-pre-launch

These are the items that prevent a sale. Not a single one is optional.

| # | Item | Why it's blocking | Effort |
|---|---|---|---|
| MS-1 | **Cases list page** | Currently `/cases` is a 🚧 placeholder. No attorney runs one case. Without this, the product is provably a demo. | M |
| MS-2 | **Case detail page** (timeline, documents, deadlines per case) | Q17 deadline logic is per-case. Q12 ACL is per-case. The whole product is per-case. We have no per-case home. | L |
| MS-3 | **Settings page** (profile, language, notifications, password reset) | [WCAG 2.1 AA requires user-controllable interface](https://www.oomphinc.com/insights/wcag-2026-compliance/). Procurement requires admin can rotate user credentials. | M |
| MS-4 | **Tenant admin panel** (user list, role assignment, quota dashboard, dictionary upload) | Q10 mentions "per-tenant uploadable JSON dictionary" — there is no UI to upload it. Tenant admin is who actually buys. | L |
| MS-5 | **Notification center** (in-app: deadline approaching, case status change, quota threshold, audit anomaly) | [Legal practice management market sized $2.06B → $4.81B by 2030 because deadline-tracking is the killer feature](https://www.thelawgpt.com/blog/legal-practice-management-software). Q17 generates deadlines; nothing tells the attorney. | M |
| MS-6 | **First-run onboarding tour** (≤ 5 steps, dismissible, ends on completed first analysis) | [Activation in <7 days is the B2B PLG floor; 3-day non-activation = 68% probability drop](https://www.userpilot.com/saas-product-metrics/). | M |
| MS-7 | **Account self-serve signup + magic-link auth** | [Even at $500k ACV, 39% of B2B buyers want self-serve digital eval](https://www.growthspreeofficial.com/blogs/plg-product-led-growth-b2b-saas-hybrid-2026). Currently 4 hard-coded demo users. | L |
| MS-8 | **Password reset / 2FA UI** | Procurement security questionnaires reject systems without account self-recovery. CLAUDE.md Q12 lists OIDC/SAML/magic-link as TODO. | M |
| MS-9 | **Help center / in-app docs + contextual tooltips** | Patent attorneys are not paid to read documentation. Tooltips on §22-2 / §103 / "grounded citation" are required. | M |
| MS-10 | **Print / PDF export of response draft** | The output of this tool is a document. There is no export. Attorneys WILL paste into Word until we ship native export. | S |
| MS-11 | **Trust banner in header** (data residency, audit-chain status, on-prem routing for confidential cases) | This is our single biggest competitive wedge per §1.3, currently invisible. | S |
| MS-12 | **i18n full coverage (no hardcoded bilingual JSX)** | TW firms WILL evaluate the English mode and the zh-TW mode separately. Mixed strings ("輸入 / Input") read as POC. | M |

### 2.3 What we lack — fast-follow (post-MVP launch, pre-Series-A)

| # | Item | Why | Effort |
|---|---|---|---|
| FF-1 | **Billing / subscription dashboard** with Stripe billing | Required to convert trial → paid; backend has no Stripe integration. | L |
| FF-2 | **Bulk OA upload (drag-drop 10+ files)** | Q4 "Case Management" placeholder bullets explicitly promise this. | M |
| FF-3 | **Audit log filtering / search / export (CSV/PDF)** | Auditor workflow needs this; currently a flat 50-row table. | M |
| FF-4 | **Keyboard shortcuts cheat sheet** | [Lawyers save 8 days/year on keyboard shortcuts; LegalBoard exists specifically for this](https://www.attorneyatwork.com/365-office-keyboard-shortcuts/). Power users expect ⌘K command palette. | S |
| FF-5 | **Dark mode** | Token bar in `index.css` already uses CSS vars; finish the migration. Low value for TW firms; high value for in-house tech-co IP teams. | S |
| FF-6 | **Drag-and-drop OA upload zone in main analyze view** | Currently a button in InputPane. | S |
| FF-7 | **Saved-prompt / template library** per tenant | Power-user feature. Differentiates from Harvey. | M |
| FF-8 | **In-app changelog / "what's new" panel** | Drives feature discovery; standard. | S |

### 2.4 What we lack — Phase 5+ (post-Series-A, scale phase)

| # | Item | Why | Effort |
|---|---|---|---|
| P5-1 | Multi-language doc previews (CJK + EN) inside the references pane | RAG hits in Patlytics already do this for prior-art docs. | L |
| P5-2 | Workflow builder / agent canvas | [TPIsoftware showcases AI agent / workflow orchestration as the next step for digiRunner](https://www.prnewswire.com/apac/news-releases/tpisoftware-at-computex-2026-showcases-all-in-one-solutions-for-enterprise-ai-adoption-302782921.html). Following their roadmap is free distribution. | XL |
| P5-3 | Slack / Teams integration for deadline alerts | Standard B2B integration. | M |
| P5-4 | Mobile native app (iOS for partner approvals) | Only after 100 customers. | L |
| P5-5 | White-label / co-brand for firms | Lee-and-Li-class firms will demand this. | M |

---

## 3. The "aha moment" + activation flow

### 3.1 What the aha moment is

Per [DeepIP's 2026 attorney-flow analysis](https://www.deepip.ai/blog/top-ai-tools-patent-attorneys-are-using-to-boost-efficiency)
and [the IPWatchdog "AI-Agile IP Counselor" piece](https://ipwatchdog.com/2026/03/01/patent-prosecutor-ai-agile-ip-counselor-high-stakes-crossroads/):
the moment a patent attorney commits to an AI tool is **not the moment it
saves time** — it's the moment they realize the tool surfaced a piece of
prior art they would have missed, OR formulated a counter-argument they
hadn't considered, and the citation traces back cleanly to a real document.

Concretely: a TW patent attorney handling a §103 obviousness rejection looks
at a draft response and sees `[GROUNDED_REF_3]` linking to a 2018
microfluidics paper they hadn't read; they hover, see the actual passage
highlighted; they realize the rejection's "predictable results" argument is
defeated by the unexpected boundary-layer behavior in that paper. That's
the conversion event.

The corollary: **speed is the unlock, but provenance is the lock-in.** Speed
is replicable by every competitor; provenance fidelity is not, because it
depends on the verifier and the hash-chained audit (Q13 + Q14) that we
already built.

### 3.2 First-time experience flow (recommended)

```
[1] Magic-link signup        ────────────────► instant magic-link to email
    "Just your work email."                   "Click to sign in. No password to remember."

[2] One-screen onboarding    ────────────────► 4 cards, you pick 1
    "What brought you here?"                  □ Office Action response  ← preselected
                                              □ Prior-art search
                                              □ Claim drafting
                                              □ Just exploring

[3] Sample case loaded       ────────────────► CASE-DEMO-001 pre-loaded with
    "Try it on a real OA."                    a US §103 rejection + sample PDF
                                              "Click Analyze, ~30s."

[4] Analysis result          ────────────────► three-pane layout (existing)
    "Here's what you'd ship."                  + first-time blue dots:
                                              ① "policy chips: your tenant's gates"
                                              ② "draft cites real prior art →
                                                  hover any [GROUNDED_REF_n]"
                                              ③ "deadline calculated for your
                                                  jurisdiction (TW + holidays)"

[5] Provenance hover         ────────────────► tooltip shows real prior-art
    "This is the lock-in."                    sentence highlighted in the cited
                                              document. THIS IS THE AHA MOMENT.

[6] Run it on YOUR OA        ────────────────► drag-drop upload + case-create
    "Now do one of yours."                    inline. Goal: < 5 min from step 1.

[7] Save → cases page        ────────────────► first case lands on dashboard.
    "You've shipped a draft."                  trial counter starts.
```

ASCII wireframe of step [4] — the activation screen:

```
┌─────────────────────────────────────────────────────────────────────┐
│ PM  PatentMind   [Analyze] Audit  Cases  Settings   alice  ▾ Logout │
├─────────────────────────────────────────────────────────────────────┤
│ ✓RPM  ✓Quota  ✓Authz  ⚡Cache  ✓Breaker      期日: 2026-07-30 [55天] │
│ 🔒 On-prem routing   📍 Data: Taiwan   📝 Audit: chain ✓ verified   │
├──────────────┬───────────────────────────────┬──────────────────────┤
│ Input (30%)  │ Drafts (40%)                  │ References (30%)     │
│              │                               │                      │
│ Case:        │ ┌───────────────────────────┐ │ [GROUNDED_REF_1]     │
│ DEMO-001     │ │ Tab: §103 Rejection (1/3) │ │ US7654321            │
│              │ ├───────────────────────────┤ │ "...microchannels    │
│ Target:      │ │ Counterargument:          │ │ with uniform cross-  │
│ US17/123456  │ │                           │ │ section achieve..."  │
│              │ │ The cited reference       │ │   ┊ hover here ┊     │
│ OA (PDF):    │ │ [GROUNDED_REF_1] does not │ │   ┊ to see passage ┊ │
│ ✓ 4 pages    │ │ teach non-uniform cross-  │ │                      │
│ ✓ no PII     │ │ section, which Applicant  │ │ [GROUNDED_REF_2]     │
│              │ │ shows yields unexpected   │ │ US6543210            │
│ [Analyze]    │ │ boundary-layer ...        │ │ "...copper substrate │
│              │ │                           │ │ provides thermal..." │
│  ⓘ click any │ │ [Edit] [Export PDF] [Copy]│ │                      │
│  citation →  │ └───────────────────────────┘ │ Filter: §103 only ▾  │
└──────────────┴───────────────────────────────┴──────────────────────┘
                    ⓘ "Hover any [GROUNDED_REF_n] —
                       this is your defense against a hallucination."
```

The bottom-of-screen tooltip is the marketing message. That tooltip is the
single most valuable thing on this screen.

---

## 4. Required pages we don't have (with scope + effort)

Effort scale: **S** = 1-2 days, **M** = 3-5 days, **L** = 1-2 weeks.

### 4.1 Dashboard (`/dashboard`) — **M**

Default landing page after login (replaces redirect-to-/analyze).

Scope:
- "Welcome back, Alice" header with tenant + role.
- 4 KPI tiles: open cases, deadlines this week, OA quota used, audit events 24h.
- "Cases needing your attention" — sortable by next deadline.
- Recent activity feed (5 most recent audit rows scoped to user, formatted).
- CTA buttons: "New case", "Upload OA".

Files: NEW `frontend/src/pages/Dashboard.jsx`, route in `App.jsx`,
backend `/dashboard/stats` endpoint summarizing existing data.

Dep: `/cases` API list endpoint exists at server; expand response.

### 4.2 Cases list (`/cases`) — **M**

Replaces 🚧 placeholder.

Scope:
- Table: Case ID, Title, Jurisdiction, Stage (filed/under-review/responded),
  Next Deadline (with urgency color), Owner, Last Activity.
- Filters: jurisdiction, stage, owner, deadline-window.
- Search by case ID or title.
- New-case button → modal with case-ID, jurisdiction, target patent, security
  level (normal / confidential — confidential triggers Q15 local-LLM routing).
- Bulk action: assign owner, archive.

Files: NEW `frontend/src/pages/CasesList.jsx`, NEW
`frontend/src/components/cases/CaseRow.jsx`, NEW backend `/cases` CRUD endpoints.

Dep: backend exposes `cases` table (currently implicit via case_id field).

### 4.3 Case detail (`/cases/:caseId`) — **L**

Scope:
- Header: case ID, title, badges (jurisdiction, stage, security level,
  on-prem routing if confidential).
- Timeline panel: filed → 1st OA → response → 2nd OA → response → reexam.
- Documents panel: list of OAs, drafts, prior-art references uploaded for
  this case. Click → opens preview (PDF viewer for source docs, the existing
  three-pane for drafts).
- Deadlines panel: all upcoming + roll-forward calculations + holiday markers.
- Audit panel: case-scoped audit subset (current view is tenant-wide).
- Team panel: who has access (Q12 ACL), with add/remove (admin only).

Files: NEW `frontend/src/pages/CaseDetail.jsx`, NEW
`frontend/src/components/cases/{Timeline,Documents,Deadlines,Team}Panel.jsx`,
backend new endpoints `/cases/:id`, `/cases/:id/timeline`,
`/cases/:id/audit`.

Dep: backend persists case-level metadata (currently inferred from case_id).
**This is the page that signals "real product."**

### 4.4 Settings (`/settings`) — **M**

Scope:
- Tabs: Profile, Notifications, Language & Region, Security, API access.
- Profile: name, email, avatar, role display.
- Notifications: deadline alerts on/off + threshold (3 days, 7 days, 14
  days); email digest frequency; in-app sound on/off.
- Language: zh-TW / en / ja toggle (ja is roadmap), default jurisdiction.
- Security: 2FA enrollment (TOTP), active sessions list with revoke,
  password change.
- API access: list of issued API tokens, scopes, last used, revoke.

Files: NEW `frontend/src/pages/Settings.jsx` + 5 tab components, backend
`/user/me` GET+PATCH, `/user/notifications-config`, `/user/sessions`,
`/user/tokens`.

### 4.5 Admin panel (`/admin`) — **L**

Visible only to `IT Admin` role (Carol).

Scope:
- Users tab: list, invite-by-email (magic-link), role assignment, deactivate.
- Quota tab: per-user RPM / monthly token / cost-circuit-breaker config (Q18).
- Mask dictionary tab: upload customer-mapping JSON (Q10), preview redaction
  rules, edit per-tenant additions.
- Security level tab: configure which security levels route to on-prem LLM
  (Q15 `LOCAL_LLM_FOR_SECURITY_LEVELS`).
- Audit tab: tenant-wide audit with filter + CSV export + chain-verify.
- Billing tab (stub for FF-1).

Files: NEW `frontend/src/pages/Admin.jsx` + 6 tab components, backend
`/admin/*` endpoints with role-gate middleware. RBAC must be enforced
server-side; UI hiding is not security.

### 4.6 Billing (`/billing` — fast-follow) — **L**

Punted to fast-follow. Stripe integration with: plan picker, payment method,
invoice history, current-period usage, upgrade/downgrade flow with proration.

### 4.7 Help center (`/help`) — **M**

Scope:
- Search box (Algolia or local Lunr).
- Categories: getting started, OA analysis, citations & provenance,
  deadlines, security, troubleshooting.
- Contextual tooltips throughout the app calling into the same content.
- Contact support button → in-app form that creates a ticket
  (just email-to-team for MVP).
- Embedded Loom-style explainer videos (record from the activation flow §3.2).

Files: NEW `frontend/src/pages/Help.jsx`, NEW `frontend/src/help/*.mdx`
content, NEW Help button in header, NEW tooltip system using
`@radix-ui/react-tooltip`.

### 4.8 Onboarding tour — **M**

Not a page; a layer.

Scope:
- 5-7 step tour driven by `react-joyride` or `intro.js`.
- Triggered on first login OR via "Show tour again" in Settings.
- Steps walk the §3.2 flow.
- Tracks completion in localStorage + backend `user.onboarding_completed_at`.

Files: NEW `frontend/src/lib/onboarding.jsx`, MOD `App.jsx` to mount.

### 4.9 Quick summary table

| Page | Status | Effort | Owner gate | Phase |
|---|---|---|---|---|
| Login | done | — | — | — |
| Dashboard | NEW | M | any user | MS |
| Cases list | placeholder | M | any user (ACL-filtered) | MS |
| Case detail | NEW | L | ACL on case_id | MS |
| Analyze | done | — | — | — |
| AuditView | done; needs filter | M (extend) | Auditor + Admin | FF |
| Settings | NEW | M | self | MS |
| Profile | merged into Settings | — | — | — |
| Admin | NEW | L | IT Admin role | MS |
| Billing | NEW | L | IT Admin role | FF |
| Help center | NEW | M | any user | MS |
| Onboarding tour | NEW | M | all new users | MS |

---

## 5. Visual identity recommendations

### 5.1 Reference shots

**Harvey** ([harvey.ai/platform](https://www.harvey.ai/platform), [harvey.ai/blog/how-we-approach-design-at-harvey](https://www.harvey.ai/blog/how-we-approach-design-at-harvey)):
deep navy + warm off-white, generous whitespace (think 80px section padding),
serif display headings (likely a custom variant of GT Sectra or similar)
paired with a sans-serif body, monospace for code/citations. Their three
principles literally are: "Design With Domain Awareness", "Make the Complex
Feel Effortless", "Design With Intention". They surface "a clear paper
trail of Harvey's thinking steps and citations" — they explicitly call out
that not being a black box is the trust signal.

**Lexis+ AI** (Reed Elsevier): editorial-newspaper aesthetic. Serif body
type for long-form, conservative red accent (`#a00000`), columnar layout
that signals "this is research, not chat". Strong typography hierarchy.

**DeepIP** ([deepip.ai](https://www.deepip.ai/)): corporate IP firm
aesthetic. Lives inside Microsoft Word, so visual identity is Office-adjacent
— neutral gray panels, blue ribbon-style accents, system fonts. Conservative.

**Patlytics** ([patlytics.ai](https://www.patlytics.ai/)): more startup-leaning
than DeepIP. Bright accent (teal/cyan), generous use of data viz, claim-chart
heavy. Strong for visual evidence patterns.

**Solve Intelligence** ([solveintelligence.com](https://www.solveintelligence.com/)):
developer-first plain. White background, minimal chrome, the document is
the UI. Browser-based editor — looks like a stripped-down Notion.

### 5.2 Recommended palette and typography for PatentMind

**Why "conservative law firm" beats "modern startup" for TW patent firms:**
TW top-10 patent firms have median founding decades 1965 (Lee and Li),
1980s (Tai E, Saint Island). Partner cohorts are 50-70 years old. They
read printed documents and have IT admins who deploy on-prem. Their
existing software stack — Townes, PAS, internal Word templates — is
Office-2016-aesthetic. We are not Notion, we are not Slack. We are an
auditable, conservative tool that happens to be AI-powered.

**Palette (CSS custom properties — replace current Tailwind defaults):**

```
--color-bg:        #f8fafc   slate-50    (canvas)
--color-surface:   #ffffff               (cards, panes)
--color-border:    #e2e8f0   slate-200
--color-ink:       #0f172a   slate-900   (body text)
--color-ink-muted: #64748b   slate-500   (secondary text)
--color-brand:     #1e3a8a   blue-900    (primary CTAs — more conservative than indigo-600)
--color-brand-fg:  #ffffff
--color-accent:    #b45309   amber-700   (deadline urgency, audit warnings — used SPARINGLY)
--color-success:   #047857   emerald-700 (verified states; reduces saturation vs emerald-500)
--color-danger:    #b91c1c   red-700
--color-info-bg:   #eff6ff   blue-50
--color-warn-bg:   #fef3c7   amber-100
```

Replace current `bg-indigo-600` brand with `--color-brand` (`#1e3a8a`).
Indigo is for startups; navy is for law firms. The hex difference is
small; the connotation is enormous.

**Typography stack:**

```css
/* Body (zh-TW + en mixed) */
font-family:
  'Inter',
  'Noto Sans TC',
  'PingFang TC',
  'Heiti TC',
  -apple-system, BlinkMacSystemFont,
  'Segoe UI', Roboto, 'Helvetica Neue',
  sans-serif;

/* Monospace (case IDs, claim numbers, hashes, audit timestamps) */
font-family:
  'JetBrains Mono', 'SF Mono', 'Cascadia Code',
  'Source Code Pro', Menlo, Consolas,
  'Noto Sans Mono CJK TC', monospace;

/* Print / PDF export only (NOT screen) */
font-family:
  'Source Serif 4', 'Georgia',
  'Noto Serif TC', 'Songti TC', serif;
```

[Noto Sans TC + PingFang TC is the established stack for professional
Traditional Chinese digital content](https://www.az-loc.com/best-fonts-for-chinese-japanese-korean-websites/);
[Noto Sans TC offers 7 weights for hierarchy in business documents](https://fonts.google.com/noto/specimen/Noto+Sans+TC).
Serif for printed PDF only — TW courts and TIPO submissions are still
PDF-with-serif. Keep that aesthetic boundary clean.

**Spacing scale:** stick with Tailwind's 4-point grid (already in code).
Bump page-level section padding from `py-3` (12px) to `py-4` (16px) in
header to add gravitas. Keep card padding at `p-4` for density (these
are working screens, not landing pages).

**Iconography:** lucide-react (already in code). Replace
emoji icons (`🚧`, `📋`) with proper lucide icons — TW partners will read
emoji as "unprofessional toy".

### 5.3 What needs to change in our current frontend (visual)

- `bg-indigo-600` brand color → swap to `bg-blue-900` / `--color-brand`.
- The amber "POC" badge in the header → remove for production builds
  (gate behind `import.meta.env.DEV`).
- Emoji in placeholders (`🚧`, `📋`, `📎`) → lucide icons.
- Header height: increase from `py-3` (currently ~52px) to `py-4` (~60px).
  Gives the brand weight.
- Card border radius: standardize to `rounded-lg` (8px). Currently mixed
  `rounded` (4px) and `rounded-lg` (8px).
- Drop the gradient on the Login page hero (`from-indigo-700 via-indigo-800
  to-slate-900`) — replace with solid `bg-slate-900` + subtle navy texture.
  Gradients read "consumer SaaS"; solid navy reads "law firm".

---

## 6. Accessibility checklist (WCAG 2.1 AA)

Why this section is not optional: [the DOJ adopted WCAG 2.1 Level AA for
ADA Title II in April 2024, with compliance deadlines in April 2026 / 2027
/ 2028 for various government entity sizes](https://www.oomphinc.com/insights/wcag-2026-compliance/).
Law firms procuring tech for state-or-local-government clients
**must include WCAG 2.1 AA language in vendor contracts** —
[per court vendor procurement guidance from NCSC](https://www.ncsc.org/resources-courts/what-courts-need-know-about-doj-digital-accessibility-rule-compliance-deadline).
A patent firm doing work for a state university (common for IP teaching
hospitals) inherits this requirement. WCAG 2.1 AA in our procurement
answer is table stakes.

### 6.1 Specific items to audit (run before launch)

**Tooling:**

- `axe-core` browser extension OR `@axe-core/react` in dev mode.
- Lighthouse accessibility audit (target ≥ 95).
- Keyboard-only navigation walkthrough (no mouse for an hour).
- NVDA (Windows) + VoiceOver (Mac) screen-reader passes on critical paths.

**Known issues in current code (from audit):**

1. **Three-pane layout (Day 8E `Analyze.jsx` line 199):** desktop uses
   `xl:grid xl:grid-cols-[3fr_4fr_3fr]`. Screen readers will read all
   three columns sequentially. Need landmark roles (`role="region"`
   `aria-label`) on each pane and a "skip to drafts" link at the top.
2. **Mobile tab bar (`MobileTabBar`):** tabs use `<button>` but lack
   `role="tab"`, `aria-selected`, `aria-controls`, and a `<div role="tablist">`
   parent. Fails WCAG 4.1.2 Name/Role/Value.
3. **Policy chips in `ResultSummaryBar`:** color-coded (emerald/amber/rose)
   without text equivalent for color-blind users. Add icons + sr-only text.
   Fails WCAG 1.4.1 Use of Color.
4. **Citation hover provenance** (future feature §3.2): if implemented as
   hover-only it's keyboard-inaccessible. Must be focusable + Enter-activatable.
   WCAG 2.1.1 Keyboard.
5. **Login page color-coded busy state:** `Loader2` spinner shown without
   `aria-live` region; busy screen-readers won't announce. Add
   `aria-live="polite"` to busy indicator. WCAG 4.1.3 Status Messages.
6. **Audit table:** lacks `<caption>`, no `scope="col"` on `<th>`.
   WCAG 1.3.1 Info and Relationships.
7. **Form inputs in `InputPane`:** check every input has an associated
   `<label htmlFor>`. Visual labels exist (`mb-1 block text-xs`) but
   `for/id` association is what assistive tech reads.
8. **Color contrast:** `text-slate-500` on `bg-white` is 4.55:1 — passes
   AA for body but fails AA Large. `text-slate-400` is 3.40:1 — fails.
   Audit every "muted text" instance.
9. **Focus indicators:** Login.jsx has good `focus-visible:ring-2`. Audit
   that every interactive element across the app has equivalent. Default
   browser focus ring is removed by Tailwind reset.
10. **Skip-to-content link:** add as first element of every page.

### 6.2 i18n recommendations (TW bilingual)

[TW patent firms have mixed audiences](https://www.legal500.com/firms/30810-lee-and-li-attorneys-at-law/30366-taipei-taiwan/):
TW attorneys read zh-TW comfortably, foreign-trained associates and US
co-counsel read en. Documents themselves are often mixed (claim text in
English even in TW patents because TW patents are typically translations
of US originals).

**Recommendation: default zh-TW, English toggle in header (not in deep
settings).** Current `i18n.js` defaults to `zh-TW` — keep that. Add a
visible `中文 / EN` toggle in the header. Reasoning: hiding the language
toggle in Settings adds 3 clicks; the English-reading associate sees a
zh-TW first-load and bounces.

**Within a single document view (claim text in en + commentary in zh-TW):**
do NOT auto-translate. Render mixed-language naturally. The Noto Sans TC
+ Inter stack handles both. Use `lang="zh-TW"` and `lang="en"` attributes
on text spans so screen readers switch voices correctly. WCAG 3.1.2
Language of Parts.

**Completion gap:** current i18n covers shell strings only (`common.app_title`,
`common.nav.*`, `common.landing.*`). Component bodies — Analyze.jsx,
AuditView.jsx, InputPane.jsx tabs — still ship hardcoded bilingual strings
like `'分析'` and `'Audit'`. **Migrate everything to t() before launch.**

---

## 7. Trust signaling — surface our hidden differentiators

CLAUDE.md §4 lists 8 design invariants, of which 7 are hidden from the UI.
This is malpractice. We built a hash-chained audit and a redaction system
that's structurally better than Harvey's, and the demo doesn't show it.

### 7.1 Audit chain UI: "tamper-evident" without scaring users

[Tamper-evident audit trails are the procurement trust signal of 2026 —
SOC 2 auditors now ask for proof nobody silently deleted records, and a
mutable DB table doesn't satisfy them](https://www.sachith.co.uk/audit-trails-and-tamper-evidence-scaling-strategies-practical-guide-feb-22-2026/).
Our SHA-256 chain (CLAUDE.md Q13) is that proof. Surface it like this:

**Header micro-badge (visible on every page):**

```
📝 Audit: 1,247 events · chain ✓     [click → /audit]
```

The number ticks up live. Color is success-green when verified, amber
"verify pending" between auto-verify runs. Click goes to audit view.
The fact that the number is *visible* communicates "every action is recorded"
without saying it.

**Tooltip on hover:**

> Every request creates one tamper-evident audit row.
> Hash chain verifies in <1s; auto-checked hourly.
> Compatible with SOC 2 / ISO 27001 / TW Personal Data Protection Act.

**On the AuditView page itself:** add a hero metric block above the table:

```
1,247  total events           ✓ chain verified  2 min ago
   47  high-risk events       [filter]
    0  tampering detected     since 2026-04-01
```

Don't scare users. Don't say "tampering" without "0 detected".

### 7.2 Redaction visibility: when to show the masked prompt vs hide it

CLAUDE.md §4 invariant 3: "Redaction is mandatory before any LLM call."
This is a HUGE trust signal for attorneys who fear PII leakage.

**Always-visible chip in the InputPane (above the OA text area):**

```
🛡️ PII detected: 3 fields (email, phone, applicant)
   ↳ replaced with placeholders before LLM call    [preview]
```

Click `[preview]` opens a modal showing the redacted text side-by-side with
the original, with placeholders highlighted. This is the
`/api/redaction/preview` endpoint that already exists.

For confidential cases, show even more aggressively:

```
🛡️ Confidential mode: redaction + on-prem routing
   ✓ Email/phone/applicant replaced
   ✓ Applicant dictionary (12 entries) applied
   ✓ Routed to local LLM (TW VPC, no egress)
```

### 7.3 Confidential routing: "this case is going to on-prem LLM" status

Currently invisible. CLAUDE.md §4 invariant 7 says confidential cases auto-
route to local LLM (Q15 `LOCAL_LLM_FOR_SECURITY_LEVELS`). Surface it.

**On the Case detail header, persistent badge:**

```
[Confidential]  [On-prem LLM]  [Audit ✓]  [TW data residency]
```

Each badge is clickable → opens a side-drawer explaining the policy. The
fact that a case is confidential and pinned to on-prem is the procurement
killer feature. Make it visible on every screen, not just the result.

### 7.4 On-prem mapping table: communicating to procurement

CLAUDE.md §9 "Don't store mapping table outside on-prem" is the technical
invariant. Procurement-facing communication:

**Footer of every page (or in the AuditView header):**

```
Data residency: 🇹🇼 Taiwan (on-prem)  |  Mapping table: TPIsoftware digiRunner gateway  |  No cross-border egress
```

**Settings → Security tab includes a "Data flow diagram" link** — opens a
modal with a static SVG showing the data flow with a region boundary (Taiwan)
drawn around the gateway + mapping DB. This becomes a printable artifact
that goes into the procurement security questionnaire response.

[BigLaw procurement specifically demands traceability of outputs and
clarity on data handling](https://gc.ai/blog/best-legal-ai-tools-for-in-house-counsel)
in 2026. A printable diagram is the artifact that goes in the answer.

---

## 8. Pricing & activation model recommendation

### 8.1 Free trial

**Length: 14 days.** [62% of SaaS products use 14-day trials — long enough
to see value, short enough to create urgency. 14% use 7 days; 14% use 30
days](https://www.amraandelma.com/free-trial-conversion-statistics/).
For legal AI, longer-feeling 30 days reduces urgency too much; 7 days is
too tight for a partner who's only in office 3 days/week.

**Type: opt-out feel without credit card.** [Opt-out (CC required) trials
convert at 31% vs 9% for opt-in](https://www.amraandelma.com/free-trial-conversion-statistics/).
But law firms will not enter a card. Solution: gate the trial signup
behind a brief MSA / NDA click-through that captures organization details
+ DUNS-equivalent + billing-contact email. The friction matches CC entry
psychologically, and the conversion is a sales-assisted invoice, not a
Stripe charge.

**Trial limits:**

- Up to 3 active cases.
- Up to 25 OA analyses total.
- All features unlocked (do NOT feature-gate; [time-based trials convert
  ~2x better than feature-limited](https://www.amraandelma.com/free-trial-conversion-statistics/)).
- Confidential routing AVAILABLE in trial — this is the trust differentiator;
  hiding it defeats the purpose.

**Trial activation criteria (the metrics to optimize):**

- D1: first OA analyzed.
- D3: first draft exported.
- D7: 5 OAs analyzed cumulatively OR second team member invited.
- D14: trial-end nudge with sales contact.

### 8.2 Paid tiers

| Tier | Target | Price | Includes |
|---|---|---|---|
| **Solo** | 1-2 attorneys | $250/seat/mo annual ($300 monthly) | 20 OAs/seat/mo, US + TW jurisdictions, email support |
| **Firm** | 3-30 attorneys | $200/seat/mo annual + $40/OA over quota | 30 OAs/seat/mo, all jurisdictions, in-app chat, custom mask dictionary |
| **Enterprise** | 30+ attorneys, on-prem | Contact sales (target $180/seat/mo + $30/OA, custom volume) | Unlimited quota, on-prem deployment, dedicated support, SSO/SAML, audit S3 archive |

**Reasoning:**

- $200-$250/seat/mo sits ABOVE Solve Intelligence's $199 entry but BELOW
  DeepIP's $350. We're more expensive than the cheap alternative, much
  cheaper than the enterprise alternative, and the per-OA usage overage
  prevents "5-attorney firm runs 5,000 OAs" pricing collapse.
- The Solo tier exists to convert sub-3-attorney boutiques that would
  otherwise go to Patentext per-draft. Pricing is high enough to not
  cannibalize Firm.
- Enterprise tier is the on-prem-and-SSO bucket. [Harvey's similar tier
  prices at $1,500+/seat/mo](https://costbench.com/software/ai-legal-tools/harvey-ai/);
  we're explicitly the value alternative for non-AmLaw-100 firms.

### 8.3 Per-seat vs per-OA vs per-tenant cap

**Why hybrid wins:**

- Pure per-seat under-prices high-volume firms (a Patlytics-style claim-chart
  shop runs 200 OAs/seat/mo, not 30).
- Pure per-OA terrifies CFOs ("budget is a function of usage I don't
  control"). [Per-document pricing is increasing but still polarizing](https://thelegalprompts.com/blog/ai-legal-tools-pricing-comparison).
- Per-tenant cap leaves money on the table for big-firm seats.

Hybrid (per-seat floor + per-OA over quota) is what [Clio's 2026 pricing
analysis](https://www.clio.com/resources/ai-for-lawyers/legal-ai-tool-pricing/)
identifies as the emerging consensus. Match it.

### 8.4 Hand-off path: trial → paid

**SMB (Solo, Firm tiers): trial → in-app upgrade with Stripe + MSA acceptance.**

**Enterprise: trial → sales-assisted close.**

- Trigger sales touch when: 3+ users on trial OR 15+ OAs analyzed OR
  user clicks "Request enterprise pricing" OR confidential-mode used >5
  times.
- Sales motion: 30-minute demo of the admin panel + security artifacts
  (data flow diagram, hash-chain video, SOC 2 status), 30-day extended
  trial with sandboxed live cases, MSA + DPA template, invoice billing.
- Average enterprise legal SaaS sales cycle is [4-8 weeks for security
  review alone](https://www.workstreet.com/blog/security-compliance-questionnaires);
  budget 90 days from trial-end to PO.

---

## 9. Concrete next-sprint frontend chunks

For the redesign agent. Each chunk is sized to fit in a single AI session.
Effort: **S** = 4-8h, **M** = 1-2 days, **L** = 3-5 days.

### CHUNK-1 — App shell refactor: add header trust band, navy palette, lucide icons

- **Scope:** swap indigo-600 brand → blue-900 (`--color-brand`).
  Replace emoji in headers/placeholders with lucide icons.
  Move language toggle (中文 / EN) into header. Remove POC badge in
  production build. Add audit-chain micro-badge ("📝 Audit: N events ·
  chain ✓") next to user menu, with tooltip.
- **Files:** MOD `frontend/src/index.css` (add CSS vars), MOD
  `frontend/src/components/Analyze.jsx` Header,
  `frontend/src/components/AuditView.jsx` header, NEW
  `frontend/src/components/AppShell.jsx` to consolidate.
- **Effort:** M
- **Depends on:** none
- **Priority:** P0

### CHUNK-2 — Dashboard page + KPI tiles + recent activity

- **Scope:** NEW `/dashboard` route, default after login. 4 KPI tiles
  (open cases, deadlines this week, OAs used, audit events 24h), a
  "Cases needing attention" table (top 5 by deadline), recent activity
  feed (last 5 audit events scoped to user).
- **Files:** NEW `frontend/src/pages/Dashboard.jsx`, NEW
  `frontend/src/components/dashboard/*.jsx` (KpiTile, AttentionList,
  ActivityFeed), MOD `App.jsx` to default to /dashboard, MOD
  `api/client.js` to add `dashboardStats()`.
- **Effort:** M
- **Depends on:** CHUNK-1 (shell), backend `/dashboard/stats` (new endpoint).
- **Priority:** P0

### CHUNK-3 — Cases list page (replaces /cases placeholder)

- **Scope:** sortable/filterable table of cases with deadline urgency
  coloring, new-case modal, ACL-filtered server-side. Empty state with
  "Create your first case" CTA.
- **Files:** REPLACE `/cases` placeholder in `App.jsx`, NEW
  `frontend/src/pages/CasesList.jsx`, NEW
  `frontend/src/components/cases/{CaseRow,NewCaseModal,CaseFilters}.jsx`,
  MOD `api/client.js` to add `casesList()`, `casesCreate()`.
- **Effort:** M
- **Depends on:** CHUNK-1, backend `/cases` CRUD endpoints (new).
- **Priority:** P0

### CHUNK-4 — Case detail page

- **Scope:** `/cases/:caseId` page with header (case ID + badges:
  jurisdiction, stage, security level, on-prem routing), timeline panel,
  documents panel, deadlines panel, case-scoped audit panel, team panel
  (admin-only edit).
- **Files:** NEW `frontend/src/pages/CaseDetail.jsx`, NEW
  `frontend/src/components/cases/{Timeline,Documents,Deadlines,Team,SecurityBadges}Panel.jsx`,
  MOD `api/client.js` to add `caseGet()`, `caseTimeline()`, `caseAudit()`.
- **Effort:** L
- **Depends on:** CHUNK-3.
- **Priority:** P0

### CHUNK-5 — Settings page with 5 tabs (Profile / Notifications / Language / Security / API)

- **Scope:** tabbed settings page. Profile = name/email/avatar/role.
  Notifications = deadline-alert thresholds, email digest cadence, in-app
  sound. Language = zh-TW / en toggle, default jurisdiction. Security = 2FA
  enrollment (TOTP), active sessions list with revoke, password change.
  API access = token list with scopes.
- **Files:** NEW `frontend/src/pages/Settings.jsx`, NEW
  `frontend/src/components/settings/{ProfileTab,NotificationsTab,LanguageTab,SecurityTab,ApiTab}.jsx`,
  MOD `api/client.js` for `/user/me`, `/user/notifications-config`,
  `/user/sessions`, `/user/tokens`, `/user/2fa/enroll`.
- **Effort:** L (split into M+S if needed)
- **Depends on:** CHUNK-1; backend new endpoints.
- **Priority:** P0

### CHUNK-6 — Admin panel (IT Admin role only)

- **Scope:** `/admin` route gated to IT Admin role. Six tabs: Users
  (invite, role assignment, deactivate), Quota (per-user RPM / token /
  cost limits), Mask Dictionary (upload JSON, preview), Security Level
  (configure on-prem routing), Audit (tenant-wide + CSV export), Billing
  (stub).
- **Files:** NEW `frontend/src/pages/Admin.jsx`, NEW
  `frontend/src/components/admin/{UsersTab,QuotaTab,MaskTab,SecurityTab,AuditTab,BillingTab}.jsx`,
  MOD `App.jsx` for role-gated route, MOD `api/client.js` for `/admin/*`
  endpoints.
- **Effort:** L
- **Depends on:** CHUNK-5 (shares form components).
- **Priority:** P0

### CHUNK-7 — Onboarding tour + sample case auto-load

- **Scope:** `react-joyride` driven 5-step tour. Triggered on first
  login. Auto-loads CASE-DEMO-001 (preseeded). Steps walk: policy chips
  → cite hover → deadline → trust badges → "now upload yours". Records
  completion in user profile.
- **Files:** NEW `frontend/src/lib/onboarding.jsx`, MOD `App.jsx` to
  mount, MOD `Analyze.jsx` to honor "?tour=1" query param, NEW seed
  data `data/demo_cases.json`.
- **Effort:** M
- **Depends on:** CHUNK-1 (badges referenced in tour); existing Analyze
  layout.
- **Priority:** P0

### CHUNK-8 — Trust band: redaction chip, on-prem badge, data residency footer

- **Scope:** InputPane gets persistent "🛡️ PII detected: N fields"
  chip with [preview] button. Result header gets badges: Confidential /
  On-prem LLM / Audit ✓ / 🇹🇼 Taiwan residency. Page footer shows the
  same residency line. AuditView header gets metric block
  (total / high-risk / tampering=0).
- **Files:** NEW `frontend/src/components/trust/{RedactionChip,SecurityBadges,ResidencyFooter,AuditMetrics}.jsx`,
  MOD `Analyze.jsx`, MOD `AuditView.jsx`, MOD `analyze/InputPane.jsx`.
- **Effort:** M
- **Depends on:** existing API endpoints (`/api/redaction/preview` exists).
- **Priority:** P0 (this is the activation moment + sales differentiator).

### CHUNK-9 — Notification center

- **Scope:** bell icon in header with unread count; dropdown shows recent
  notifications (deadline approaching for case X in N days; quota
  threshold; audit anomaly). Click → goes to case detail / quota page /
  audit view. SSE or polling backend.
- **Files:** NEW `frontend/src/components/notifications/{NotificationBell,NotificationList,NotificationItem}.jsx`,
  MOD `api/client.js` for `/notifications`, MOD AppShell to mount bell.
- **Effort:** M
- **Depends on:** CHUNK-1.
- **Priority:** P1

### CHUNK-10 — i18n full coverage + zh/en header toggle

- **Scope:** migrate every hardcoded string in Analyze.jsx, AuditView.jsx,
  InputPane.jsx, DraftsPane.jsx, ReferencesPane.jsx to `t()`. Add the
  toggle button in header (CHUNK-1 plumbing). Persist choice to user
  profile. Add `lang="zh-TW" | lang="en"` attributes on mixed-language
  text spans.
- **Files:** MOD `frontend/src/lib/i18n.js` (expand resources), MOD all
  components with hardcoded strings.
- **Effort:** M
- **Depends on:** CHUNK-1.
- **Priority:** P0

### CHUNK-11 — PDF export of response draft

- **Scope:** "Export PDF" button in DraftsPane. Server-side generation
  using existing draft + citation lookup. PDF includes draft text +
  inline citations (numbered) + reference list with prior-art URLs +
  audit hash + case ID. Header watermark "PatentMind draft — attorney
  review required".
- **Files:** NEW `frontend/src/components/analyze/ExportPDFButton.jsx`,
  backend NEW `/api/draft/export-pdf` endpoint using WeasyPrint or
  ReportLab.
- **Effort:** M
- **Depends on:** CHUNK-4 indirectly (case-scoped context).
- **Priority:** P0

### CHUNK-12 — Help center + contextual tooltips

- **Scope:** `/help` route with searchable MDX content (getting started,
  citations, deadlines, security). Help button in header. Add tooltip
  system using `@radix-ui/react-tooltip` for §22-2 / §103 / "grounded
  citation" / "hash chain" / etc. wherever those terms appear in UI.
- **Files:** NEW `frontend/src/pages/Help.jsx`, NEW
  `frontend/src/help/*.mdx`, NEW
  `frontend/src/components/HelpTooltip.jsx`, MOD multiple components
  to wrap technical terms.
- **Effort:** M
- **Depends on:** CHUNK-1.
- **Priority:** P1

---

### Chunk priority summary

**Ship in next sprint (P0):** CHUNK-1, CHUNK-2, CHUNK-3, CHUNK-4, CHUNK-5,
CHUNK-6, CHUNK-7, CHUNK-8, CHUNK-10, CHUNK-11. 10 chunks, ~6 weeks of
focused work.

**Sprint+1 (P1):** CHUNK-9, CHUNK-12.

**Fast-follow:** Billing dashboard, audit log filtering/export, dark mode,
bulk upload, drag-drop, keyboard shortcuts.

### Top 5 chunks for the redesign agent to start FIRST

(In order. Each one unblocks others.)

1. **CHUNK-1** — App shell refactor. Everything else hangs off it.
2. **CHUNK-8** — Trust band. This is the activation moment AND the sales
   differentiator. Cheap to ship, biggest value lift.
3. **CHUNK-3** — Cases list. Without this we're a demo, full stop.
4. **CHUNK-2** — Dashboard. Default landing page. Sets the tone.
5. **CHUNK-7** — Onboarding tour. Drives activation in the first 5 minutes.

---

## 10. Single biggest "MVP can't sell" → "product that sells" risk

**The risk is not technical. It's that we already won on the differentiator
and we don't know it.**

Every other patent AI tool ([Harvey](https://www.harvey.ai/), [Patlytics](https://www.patlytics.ai/),
[DeepIP](https://www.deepip.ai/), [Solve Intelligence](https://www.solveintelligence.com/),
Rowan, Patentext) runs in US cloud. None of them ships natively into a
TW on-prem digiRunner deployment. None of them has a SHA-256 hash-chained
audit that customers can independently verify. None of them has a
redaction-mapping table that lives behind a tenant's firewall.

We have all three. **We built them in Phase 1 and forgot to surface them
in the UI.** A buyer who walks through our app today sees an indigo-themed
React SPA with a POC badge in the header that says "internal demo only".
They do not see "tamper-evident", "on-prem", "🇹🇼 data residency", or
"confidential routing". The procurement-deciding partner who needs to
answer their 200-question security questionnaire opens our app, sees
**nothing** that distinguishes us from a ChatGPT wrapper, and goes back
to Harvey.

**The single biggest risk is that we ship CHUNK-1 through CHUNK-7
(the page-completeness work) and forget to ship CHUNK-8 (the trust band).
Then we have a complete product that looks identical to a complete
competitor.**

CHUNK-8 is two days of work and it is the most important two days in this
sprint. Build the trust band FIRST after the shell refactor.

Corollary risk: the team treats the existing audit + redaction + on-prem
routing as "compliance backend" rather than "marketing surface". Every
single one of those three is a sales artifact disguised as a security
feature. Make them visible. Make them clickable. Make them brag.

---

## 11. References

### Patent AI market & competitors
- [Patlytics raises $40M Series B - AlleyWatch](https://www.alleywatch.com/2026/04/patlytics-ai-patent-platform-ip-lifecycle-management-legal-tech-paul-lee/)
- [Best AI Patent Drafting Tools 2026 - Patlytics](https://www.patlytics.ai/blog/best-ai-patent-drafting-tools-of-2026)
- [Best AI Tools for Patent Attorneys 2026 - DeepIP](https://www.deepip.ai/blog/top-ai-tools-patent-attorneys-are-using-to-boost-efficiency)
- [Solve Intelligence Series B and Charts launch](https://www.solveintelligence.com/blog/post/solve-intelligence-raises-40m-series-b-to-build-ai-for-patents-and-launches-charts)
- [Best AI Patent Drafting Tools 2026 (with pricing) - Patentext](https://blog.patentext.com/blog-posts/best-ai-patent-drafting-tools)
- [Solve Intelligence vs DeepIP comparison](https://blog.patentext.com/blog-posts/solve-intelligence-vs-deepip)
- [Solve Intelligence vs Patlytics comparison](https://blog.patentext.com/blog-posts/solve-intelligence-vs-patlytics)
- [Every AI patent tool in 2026 - Patentext](https://blog.patentext.com/blog-posts/a-complete-list-of-ai-patent-tools)
- [Best AI Patent Tools 2026 Practitioner's Guide - PatentSolve](https://patentsolve.com/blog/best-ai-patent-tools-2026)
- [Best Legal Software for Patent Writing 2026 - SoftwareFinder](https://softwarefinder.com/resources/best-legal-software-patent-writing)

### Pricing benchmarks
- [Harvey AI Pricing 2026 - CostBench](https://costbench.com/software/ai-legal-tools/harvey-ai/)
- [Legal AI Pricing 2026: Harvey vs CoCounsel vs Clio - The Legal Prompts](https://thelegalprompts.com/blog/ai-legal-tools-pricing-comparison)
- [Legal AI Tools Pricing Comparison 2026 - Elephas](https://elephas.app/resources/legal-ai-tools-pricing-comparison)
- [Solve Intelligence Pricing - eesel.ai](https://www.eesel.ai/blog/solve-intelligence-pricing)
- [What's Driving Legal AI Pricing in 2026 - Clio](https://www.clio.com/resources/ai-for-lawyers/legal-ai-tool-pricing/)
- [AI.Law Pricing](https://www.ai.law/pricing/)

### Trial / activation / conversion benchmarks
- [SaaS Free Trial Conversion Benchmarks 2026 - Amra and Elma](https://www.amraandelma.com/free-trial-conversion-statistics/)
- [B2B SaaS Trial-to-Paid Benchmarks 2026 - GrowthSpree](https://www.growthspreeofficial.com/blogs/b2b-saas-trial-to-paid-conversion-rate-benchmarks-2026-by-trial-type-acv-length-credit-card)
- [SaaS Product Metrics - Userpilot](https://www.userpilot.com/saas-product-metrics/)
- [SaaS Empty State Design - Pixxen](https://pixxen.com/saas-empty-state-design/)

### Industry analysis (TW + US + procurement)
- [Patent Law Firms Face the AI Squeeze - IPWatchdog](https://ipwatchdog.com/2026/05/15/patent-law-firms-face-ai-squeeze-as-clients-internalize-more-work/)
- [Patent Law Firms Face an AI Reckoning - IPWatchdog](https://ipwatchdog.com/2026/05/26/patent-law-firms-face-ai-reckoning/)
- [Patent Prosecutor or AI-Agile IP Counselor - IPWatchdog](https://ipwatchdog.com/2026/03/01/patent-prosecutor-ai-agile-ip-counselor-high-stakes-crossroads/)
- [85 Predictions for AI and the Law in 2026 - National Law Review](https://natlawreview.com/article/85-predictions-ai-and-law-2026)
- [BCLT Berkeley-Stanford Advanced Patent Law Institute](https://www.law.berkeley.edu/research/bclt/bcltevents/26th-annual-berkeley-stanford-advanced-patent-law-institute/ep-summary-26apli/day-2-panel-5-litigation-ai-tools-and-litigation/)
- [Harvey Most Innovative Companies 2026 - Fast Company](https://www.fastcompany.com/91502697/harvey-most-innovative-companies-2026)
- [Harvey AI Forward Deployed Engineers - Perspective AI](https://getperspective.ai/blog/harvey-ai-forward-deployed-engineers-biglaw-deployment-playbook-2026)
- [Best Legal AI Tools for In-House Counsel 2026 - GC AI](https://gc.ai/blog/best-legal-ai-tools-for-in-house-counsel)

### Taiwan-specific
- [Lee and Li firm profile - Chambers 2026](https://chambers.com/office/lee-and-li-attorneys-at-law-taipei-taiwan-jurisdiction-greater-china-region-116:2315)
- [Lee and Li Privacy Policy](https://www.leeandli.com/EN/000000318.htm)
- [Lee and Li Legal 500 ranking](https://www.legal500.com/firms/30810-lee-and-li-attorneys-at-law/30366-taipei-taiwan/)
- [Tai E Firm Profile - IP STARS](https://www.ipstars.com/Firm/Tai-E-International-Patent-Law-Office-Taiwan/Profile/102270)
- [Saint Island Firm Profile - IP STARS](https://www.ipstars.com/Firm/Saint-Island-International-Patent-Law-Offices-Taiwan/Profile/102269)
- [Taiwan AI Basic Act - IAPP](https://iapp.org/news/a/taiwan-s-strategic-leap-into-ai-enacting-the-ai-basic-act-to-foster-innovation-governance)
- [TIPO Deferred Substantive Examination 2026 - Lexology](https://www.lexology.com/library/detail.aspx?g=54a2481d-467e-406f-b38b-f7ccc9a6f07d)
- [TIPO IPC 2026.01](https://www.tipo.gov.tw/en/tipo2/324.html)
- [TIPO Industry Collaborative Pilot extension](https://www.tipo.gov.tw/en/tipo2/324-21836.html)
- [Patent Eligibility of AI Technology in Taiwan - AIPLA](https://www.aipla.org/list/innovate-articles/patent-eligibility-of-ai-technology-inventions-in-taiwan-and-analysis-of-filing-strategies)
- [TPIsoftware COMPUTEX 2026 - PR Newswire](https://www.prnewswire.com/apac/news-releases/tpisoftware-at-computex-2026-showcases-all-in-one-solutions-for-enterprise-ai-adoption-302782921.html)
- [digiRunner Gartner Peer Insights](https://www.gartner.com/reviews/product/digirunner)

### Visual design & UX patterns
- [How We Approach Design at Harvey](https://www.harvey.ai/blog/how-we-approach-design-at-harvey)
- [Rebuilding Harvey's Design System](https://www.harvey.ai/blog/rebuilding-harveys-design-system-from-the-ground-up)
- [Best Fonts for Chinese, Japanese, Korean Websites - AZ Loc](https://www.az-loc.com/best-fonts-for-chinese-japanese-korean-websites/)
- [Noto Sans Traditional Chinese - Google Fonts](https://fonts.google.com/noto/specimen/Noto+Sans+TC)

### Security & procurement
- [Security Compliance Questionnaires Complete Guide 2026 - Workstreet](https://www.workstreet.com/blog/security-compliance-questionnaires)
- [Vendor Security Assessment Enterprise Checklist - Iterators](https://www.iteratorshq.com/blog/vendor-security-assessment-the-enterprise-checklist-saas-startups-miss/)
- [SOC 2 vs ISO 27001 2026 - SOC 2 Auditors](https://soc2auditors.org/insights/soc-2-vs-iso-27001/)
- [ISO 42001 vs SOC 2 vs ISO 27001 - Knowlee](https://www.knowlee.ai/blog/iso-42001-vs-soc2-vs-iso-27001-comparison)
- [Audit Trails and Tamper Evidence Practical Guide - Sachith](https://www.sachith.co.uk/audit-trails-and-tamper-evidence-scaling-strategies-practical-guide-feb-22-2026/)
- [Best Platforms for Immutable Audit Trails 2026 - Pactvera](https://www.pactvera.com/best-platforms-for-immutable-audit-trails-in-2026/)

### Accessibility (WCAG 2.1 AA)
- [WCAG 2026 Compliance Guide - Oomph](https://www.oomphinc.com/insights/wcag-2026-compliance/)
- [DOJ Digital Accessibility Rule - NCSC](https://www.ncsc.org/resources-courts/what-courts-need-know-about-doj-digital-accessibility-rule-compliance-deadline)
- [New Digital Accessibility Requirements 2026 - BBK Law](https://bbklaw.com/resources/new-digital-accessibility-requirements-in-2026)
- [ADA Title II 2026 Update - Aberdeen](https://aberdeen.io/blog/2026/04/07/ada-title-iis-2026-update-what-changed-and-what-didnt/)

### Go-to-market & onboarding
- [PLG for B2B SaaS 2026 Hybrid Self-Serve + Sales-Led - GrowthSpree](https://www.growthspreeofficial.com/blogs/plg-product-led-growth-b2b-saas-hybrid-2026)
- [SaaS Launch Checklist - Infinity Sky AI](https://infinitysky.ai/blog/saas-launch-checklist-before-going-live)
- [Legal Practice Management Software Guide 2026 - TheLawGPT](https://www.thelawgpt.com/blog/legal-practice-management-software)
- [Keyboard Shortcuts for Lawyers - Attorney at Work](https://www.attorneyatwork.com/365-office-keyboard-shortcuts/)

---

*End of strategy doc. Hand off to frontend redesign agent. Start with
CHUNK-1, then CHUNK-8. Make trust visible.*
