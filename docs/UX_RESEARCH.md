# UX Research — Patent OA AI Tools (2026-06-01)

> UX research for `patentmind-poc` (TW/US Office Action AI assistant). 60+ public URLs (May/June 2026). Method: WebSearch + WebFetch, cross-referenced. Audience: Phase 4 sprint planning.

---

## 1. Executive summary

**The five UX patterns every successful 2026 patent OA tool shares:**

1. **Anchored workspace, never tab-switch.** Patlytics, DeepIP, Solve Intelligence and IP Author all collapse OA text + cited references + draft editor + AI chat into a single, persistent layout. Tab-switching is the most frequently cited friction point. ([Patlytics multitasking blog](https://www.patlytics.ai/blog/a-smarter-multitasking-workspace-for-patent-prosecution), [IP Author](https://ipauthor.com/patent-prosecution-workflow-ai/))
2. **Citation grounding is now table-stakes, not a differentiator.** Every serious legal AI (Harvey, Lexis+ Protégé, CoCounsel) ships a "citation ledger" with hover preview + deep link to the exact passage. Stanford HAI's 2024 study (still cited in 2026 buyer guides) that "legal models hallucinate in 1 out of 6 queries" is the wedge that forced this. ([CoCounsel ledger](https://www.thomsonreuters.com/en-us/posts/innovation/cocounsel-legal-reimagined/), [Stanford HAI](https://hai.stanford.edu/news/ai-trial-legal-models-hallucinate-1-out-6-or-more-benchmarking-queries), [Shape of AI patterns](https://www.shapeof.ai/patterns/citations))
3. **Word add-in OR browser editor — pick one and commit.** DeepIP went all-in on Word. Solve Intelligence, Patlytics, Harvey went all-in on browser. The hybrid tools (PatentMaker, IP Author) are explicitly criticised for being "less sleek at any single task." ([Patentext 2026 ranking](https://blog.patentext.com/blog-posts/a-complete-list-of-ai-patent-tools), [DeepIP vs Solve Intelligence](https://www.lexology.com/library/detail.aspx?g=a945581a-89b2-45ca-9a37-894711af9cdc))
4. **Automated redlining converts to/from USPTO format.** Track-changes ↔ underline/strikethrough conversion is now expected (ClaimMaster, Patlytics, Patentbots). After USPTO Patent Center's 2024 DOCX change, this is no longer optional. ([ClaimMaster tutorial](https://www.patentclaimmaster.com/blog/tutorial-switch-between-uspto-formatting-and-track-changes/), [Patentbots](https://blog.patentbots.com/2018/09/new-features-track-changes-conversion.html))
5. **Global Ctrl/⌘+K palette as the primary entry point.** Harvey's `⌘K` "Global Search" jumps to vaults, threads, workflow agents. Lawyers conditioned by Linear/Notion expect it. ([Harvey getting started](https://help.harvey.ai/articles/getting-started-with-harvey))

**What `patentmind-poc` does well (don't regress):**
- Day 7 line-level provenance editor (`DraftEditor.jsx`) — every line tagged AI/attorney, with sign-off. This is **ahead of DeepIP/Solve Intelligence**, neither of which exposes per-line provenance.
- Hash-chained tamper-evident audit (`AuditView.jsx`) — only Lexis+ Protégé Workrooms (May 2026) ships anything comparable, and theirs is opaque "trust us" rather than user-verifiable.
- Reversible redaction with per-tenant dictionary (Q10) — no competitor exposes the masked-prompt to the user; we do, which builds trust.
- Verifier as a hard wall on citations (Q14) — matches CoCounsel's citation ledger philosophy.

**Biggest UX gaps:**
- **No claim dependency tree.** ClaimMaster, Patlytics, Solve all ship one. Easy P0 win.
- **No side-by-side OA / draft / cited-reference layout.** We have a vertical scroll. Patlytics, IP Author, Bluebeam-style split is the norm.
- **No command palette / global keyboard nav.** Harvey ⌘K is the 2026 baseline.
- **No automated redline export in USPTO underline/strikethrough format.** This is the literal output format the user has to submit.
- **No "cited reference pop-out viewer"** (Patlytics calls this out as the single highest-impact addition they shipped in 2026).

---

## 2. Competitor product walkthroughs

### 2.1 DeepIP

**Entry:** Native Microsoft Word add-in (AppSource). No browser app for OA work.

**Layout (reconstructed from press + reviews; DeepIP does not publish UI docs):**
```
+----------------------------+--------------------+
|                            | DeepIP task pane   |
|  Word document             |  OA summary        |
|  (response draft)          |   § 103 / § 102    |
|                            |  Cited art ▾       |
|                            |  Suggested args    |
+----------------------------+--------------------+
```

**OA flow:** Ribbon "Retrieve Office Action" → auto-pulls USPTO/EPO doc → extracts rejections → ranks objections by validity → surfaces cited passages → drafts arguments inside active doc.

**Notable wins:** Objection ranking for triage; one-click reference retrieval (kills the "flip 100s of pages" pain ([IP Author](https://ipauthor.com/patent-prosecution-workflow-ai/))); unified prosecution/drafting/harvesting environment.

**Pricing implication:** Enterprise (est. $200-400/seat/mo per 2026 buyer guides) — buys deep task pane + Microsoft 365 admin integration. Users already trained on Word.

**Sources:** [AI OA 2026 guide](https://www.deepip.ai/blog/ai-office-action) · [IPWatchdog press](https://ipwatchdog.com/press/deepip-revolutionizes-patent-office-actions-new-ai-powered-module/) · [AppSource](https://marketplace.microsoft.com/en-ie/product/office/WA200006965?tab=Overview) · [collaboration blog](https://www.deepip.ai/blog/office-action-response-collaboration)

---

### 2.2 Solve Intelligence

**Entry:** Browser editor at solveintelligence.com. "Works just like Word." Sign in → drafting.

**Layout (from reviews + product page):**
```
+----------------------------------+--------------+
|  Document editor (Word-like)     |  AI Copilot  |
|  spec / claims / OA response     |  side panel  |
|                                  |  Generate /  |
|                                  |  Search /    |
|                                  |  OA reply /  |
|                                  |  Citations   |
+----------------------------------+--------------+
```

**OA flow:** Drop OA + disclosure + references → auto-classifies §102/§103/§112 → drafts per-claim argument paragraphs → jurisdiction-aware EPO/USPTO/TIPO templates.

**Notable wins:** G2 reviewer "drafting time reduced by 60%+"; jurisdiction templates as a settings toggle (not separate SKUs); paragraph-level multi-source citations inline.

**Pricing implication:** Lower friction than DeepIP (no install) — good model for TW market where firms may lack firm-wide Office 365.

**Sources:** [product](https://www.solveintelligence.com/) · [G2](https://www.g2.com/products/solve-intelligence-patent-copilot/reviews) · [Lexology DeepIP vs Solve](https://www.lexology.com/library/detail.aspx?g=a945581a-89b2-45ca-9a37-894711af9cdc)

---

### 2.3 Harvey

**Entry:** Web app, left sidebar primary nav (5 items: Assistant / Vault / Workflow Agents / History / Library), plus collapsible Vault sub-sidebar.

**Key interactions:**
- **Ctrl/⌘+K Global Search** — jumps across vaults, threads, Workflow agents, ranked by recent activity.
- **One-click Workflow Agents** against an uploaded Vault — reusable, role-permissioned, shareable across practice groups (March 2026 update added review tables).
- **PowerPoint / Excel / PDF editing in the chat surface** (May 2026) — multi-format output without leaving the thread.

**Notable wins:** The 5-icon left rail is now de-facto (Lexis+ Protégé copied it Feb 2026). ⌘K is the 2026 baseline lawyers expect.

**Pricing implication:** ~$300-500/seat/mo. UI assumes long-lived "matters" with hundreds of docs (vault metaphor) — applies to in-house IP teams more than solo TW practitioners.

**Sources:** [platform](https://www.harvey.ai/platform) · [getting started](https://help.harvey.ai/articles/getting-started-with-harvey) · [Brief Mar 2026](https://www.harvey.ai/blog/the-brief-march-2026) · [Brief Apr 2026](https://www.harvey.ai/blog/the-brief-april-2026) · [GC AI review](https://gc.ai/blog/harvey-legal-ai-review) · [release notes May 2026](https://releasebot.io/updates/harvey)

---

### 2.4 PatentPal

**Entry point:** Browser (drag-and-drop) + Word/Visio/PowerPoint export.

**Layout:** Three-column. Left = feature list (claims → spec → figures → abstract). Center = generated content with inline-editable phrases. Right = figure preview.

**Key OA-adjacent feature:** *Claim → flowchart generator.* Takes the first independent method claim and emits a Visio/PowerPoint flowchart **plus the corresponding spec narrative**. Right-click on a figure to upload an illustration and apply labels that map to spec text.

**Notable UX wins:**
- Real-time spec regeneration as user edits phrases (immediate feedback loop).
- One-click multi-format export (Word + Visio + PPT) — eliminates the formatting tax.
- Labelled figures with semantic mapping to spec terms — directly relevant to our Vision-OCR roadmap (Q8).

**Pricing/UX implication:** Cheap (~$50-100/month tiers), aimed at solo + boutique. Heavy automation, light AI judgment — opposite of Harvey.

**Sources:**
- [PatentPal homepage](https://patentpal.com/)
- [7 New Features on PatentPal Draft](https://medium.com/patentpal/7-new-features-on-patentpal-draft-3b7811d51f95)
- [PatentPal playground](https://patentpal.com/playground/)

---

### 2.5 Lexis+ Protégé (rebranded from Lexis+ AI, Feb 2026)

**Entry point:** Web app, unified across research / drafting / Vault / Workrooms.

**Layout:** Harvey-style left rail (5 items: Assistant, Vault, Workflow, Workrooms, History). Center is a hybrid chat+document surface.

**Feb 2026 launch:** 300+ pre-built workflows + no-code workflow builder. **May 2026 expansion:** "Protégé Work" skills layer, agentic drafting agents, expanded Vault (up to 100K docs, accepts audio/video/image), and **Workrooms** for outside-counsel ↔ client collaboration with customer-held encryption keys.

**Notable UX wins:**
- **Workrooms** is the first real attempt at the "outside counsel ↔ in-house team handoff" pattern that DeepIP's [collaboration blog](https://www.deepip.ai/blog/office-action-response-collaboration) identifies as the single most broken part of OA work.
- Shepard's citation validation embedded inline in drafts — the highest bar for citation grounding.
- Customer-held encryption keys — relevant to our Q3 on-prem stance.

**Sources:**
- [LexisNexis launches Lexis+ with Protégé (LawSites Feb 2026)](https://www.lawnext.com/2026/02/lexisnexis-launches-lexis-with-protege-replacing-lexis-ai-with-an-end-to-end-workflow-platform.html)
- [Workrooms expansion (LawSites May 2026)](https://www.lawnext.com/2026/05/lexisnexis-expands-lexis-with-protege-adding-agentic-skills-collaboration-workrooms-and-customer-held-encryption-keys.html)
- [Lexis+ Protégé product page](https://www.lexisnexis.com/en-us/products/lexis-plus-protege.page)

---

### 2.6 Westlaw CoCounsel (now CoCounsel Legal Reimagined, Aug 2025)

**Entry point:** Web app. Tighter Westlaw integration after the Aug 2025 re-launch; Claude integration via Thomson Reuters x Anthropic deal expanded in May 2026.

**Key OA-relevant feature:** **patent-pending citation ledger** — every source the agent reads is logged, with the specific passages, traceable in one click. 1.9 B Westlaw docs + 1.4 B KeyCite signals as the grounding corpus.

**Notable UX wins:**
- "Plain language → agentic workflow" — user describes what they want, CoCounsel plans the steps. Less prompt engineering required than Harvey.
- **Deep Research** mode delivers full reports with every citation grounded in Westlaw.
- Citation ledger displayed as a sidebar that updates live as the agent works — attorneys see *what it read* before they see *what it wrote*.

**Sources:**
- [CoCounsel Legal Reimagined (TR Institute)](https://www.thomsonreuters.com/en-us/posts/innovation/cocounsel-legal-reimagined/)
- [TR + Anthropic partnership May 2026](https://www.thomsonreuters.com/en/press-releases/2026/may/thomson-reuters-and-anthropic-expand-partnership-to-connect-claude-with-cocounsel-legal)
- [Deep Research in Westlaw and CoCounsel](https://medium.com/tr-labs-ml-engineering-blog/deep-research-in-westlaw-and-cocounsel-building-agents-that-research-like-lawyers-508ad5c70e45)
- [Westlaw AI review 2026](https://www.aivortex.io/legal/ai-tools/westlaw-ai/)

---

### 2.7 NLPatent / Patentext

**NLPatent** is focused on **prior art search** rather than OA response. Natural-language input (full disclosures pasted in), document-level similarity ranking, "Ask NLPatent" Q&A surface. Claims 80% time reduction on prior art search. Relevant to us because OA response often *starts* with prior art re-search to find distinctions.

**Patentext** is an end-to-end filing service for startup founders — combines AI drafting with human attorneys. Less directly comparable; more a service-business model than a UX competitor.

**Sources:**
- [NLPatent homepage](https://www.nlpatent.com/)
- [NLPatent product FAQ](https://support.nlpatent.com/article/12-product-features-faq)
- [Patentext blog — best AI patent tools 2026](https://blog.patentext.com/blog-posts/best-ai-patent-drafting-tools)
- [Cypris: best AI patent search tools 2026](https://www.cypris.ai/insights/best-ai-patent-search-tools-in-2026-the-definitive-guide-for-r-d-and-innovation-teams)

---

## 3. Patent attorney workflow analysis

### Typical OA response week
Public sources don't publish granular task-time studies, but IP Author quantifies the macro picture as **"70% administrative busywork"** (OCRing PDFs, copy-pasting claim charts, searching for antecedent basis errors, manual claim ↔ prior art mapping) versus 30% strategic work. ([IP Author breakdown](https://ipauthor.com/patent-prosecution-workflow-ai/))

A typical fixed-fee OA case is estimated at 4 hours but "balloons to 10+ hours" in practice. AIPLA's bi-annual survey notes **4.2 office actions per granted utility patent** on average — so prosecution work is the dominant cost driver per case. ([Patlytics 2026 Guide](https://www.patlytics.ai/blog/2026-guide-modern-office-action-patent-prosecution))

### Where the time goes (synthesised from Patlytics + IP Author + DeepIP descriptions)
1. **Parsing the OA itself** — line-by-line mapping of examiner rejections to claim language. Cited as "consumes mental cycles before strategy work begins."
2. **Reference retrieval & review** — "often the most time-consuming part." Examiners cite long, dense documents; attorneys flip through hundreds of pages.
3. **Claim ↔ prior art comparison** — constant screen switching, "locating specific paragraphs" in PDFs.
4. **Drafting response from scratch** — blank-page syndrome; "massive time bottleneck for initial composition."
5. **Quality control** — typos, claim numbering errors, antecedent basis (these errors are unforced and embarrassing).
6. **Format conversion** — Word track-changes → USPTO underline/strikethrough.
7. **Internal review cycles** — outside counsel ↔ in-house ↔ inventor. "Comments exchanged over email."

### Pain points (cited from 2026 sources)
- **Tab-switching** — universal complaint across Patlytics, IP Author, DeepIP write-ups.
- **Fragmented tooling** — "constant switching between documents, static notes, and multiple claim versions, leading to lost context and increased errors." ([Patlytics 2026 Guide](https://www.patlytics.ai/blog/2026-guide-modern-office-action-patent-prosecution))
- **Formatting friction** — USPTO markup rules are "easy to get wrong."
- **Surface-level rejection analysis** — attorneys often skim, missing limitation-level issues that decide the case.
- **Review cycle thrash** — outside vs in-house priorities collide late in the process. ([DeepIP collaboration blog](https://www.deepip.ai/blog/office-action-response-collaboration))

### Collaboration pattern (junior → partner)
Most firms still run **email + Word + redline** loops. Lexis+ Workrooms (May 2026) and DeepIP's shared response environment are early attempts to consolidate. The proposed structured pattern is: (1) outside counsel drafts, (2) "examiner-style" automated review surfaces risk areas, (3) internal strategic review (no line-editing), (4) consolidated feedback through a single channel. This is the **3-stage review** pattern we should mirror. ([DeepIP collaboration](https://www.deepip.ai/blog/office-action-response-collaboration))

### Bottlenecks `patentmind-poc` can address
| Bottleneck | Our hook |
|---|---|
| OA parsing | Q11 spotlight rejections already structures this — extend to per-claim drilldown |
| Reference retrieval | Q7 Qdrant-shape vector store can fetch + score cited art on upload |
| Claim ↔ prior art comparison | We need a side-by-side view — biggest gap |
| Blank-page drafting | Q14 grounded draft already does this; need to expose "draft skeleton" before full draft |
| Format conversion | New: USPTO markup export |
| Internal review | Q13 audit + Q16 line-level provenance is the foundation for a Workrooms-style flow |

---

## 4. Patent-specific UI pattern library

### 4.1 Claim dependency tree
**Pattern:** Hierarchical tree, independent claims as roots, dependent claims branch from their parent. Click a node to jump to the claim text. ClaimMaster offers three views: bubble diagram, dynamic interactive map (hover shows claim text), and text tree. ([ClaimMaster blog](https://www.patentclaimmaster.com/blog/visualizing-claim-trees/))

```
Claim 1 (indep) ─── Claim 2 (dep. 1) ─── Claim 5 (dep. 2)
                ├── Claim 3 (dep. 1) ─── Claim 6 (dep. 3)
                └── Claim 4 (dep. 1)
Claim 7 (indep) ─── Claim 8 (dep. 7)
```

**Recommendation for us:** Render as collapsible tree in the OA response left rail. Color nodes by rejection status: red = rejected, yellow = objected, green = allowed/clean. Click node → scrolls draft + reference panes to the claim, highlights examiner's specific objection.

### 4.2 Citation grounding UI
**Pattern (Shape of AI taxonomy):** Four flavors —
- **Inline highlights** (Adobe Acrobat style): exact passages shown in source PDF.
- **Direct quotations** (Granola style): the specific quote pulled into the response.
- **Multi-source references** (Perplexity style): chips with favicon + title, synthesized.
- **Lightweight links** (Copy.ai style): bare URLs for verification.

Hover preview is the strongest interaction: Granola "provides a peek into the cited content when hovering, displaying paraphrases and direct quotes." Notion and Dovetail let users trace insights back to the source pane. ([Shape of AI citations](https://www.shapeof.ai/patterns/citations))

**Recommendation for us:** Inline footnote-style superscript `[¹US7654321:col 4 ll. 12-18]` in the draft. Hover → tooltip with the exact quoted passage. Click → opens the reference in the right pane scrolled to that passage. This matches CoCounsel's "citation ledger in one click."

### 4.3 Diff view for claim amendments
**Pattern:** Bidirectional conversion between Word track-changes (redline strikethrough) and USPTO markup (underline + strikethrough). Tools: ClaimMaster, Patentbots, and now Patlytics generate redlines automatically. USPTO Patent Center auto-converts since 2024. ([ClaimMaster tutorial](https://www.patentclaimmaster.com/blog/tutorial-switch-between-uspto-formatting-and-track-changes/))

**Recommendation for us:** Two-button toolbar above amendment editor: "[View: Track Changes]" / "[View: USPTO format]". Export defaults to USPTO. Show character-level diff (not just line-level) — patent attorneys care about specific word changes.

### 4.4 Side-by-side OA / response layout
**Pattern (Patlytics + Apryse WebViewer + Bluebeam):** Three-pane:
```
+-----------+-----------+----------------+
| OA text   | Response  | Cited refs     |
| (left)    | draft     | (right, popout |
| with      | (center)  |  to floating   |
| highlight |           |  window)       |
+-----------+-----------+----------------+
```
Synchronized scrolling, color-coded difference highlighting, full editing in any pane (Apryse WebViewer 11.12+). ([Apryse multi-viewer](https://apryse.com/blog/webviewer/compare-pdf-office-or-image-side-by-side-or-multi-tab-view), [Patlytics workspace](https://www.patlytics.ai/blog/a-smarter-multitasking-workspace-for-patent-prosecution))

**Recommendation for us:** Three-pane on ≥1280px screens, collapses to tabs below. The **pop-out cited reference viewer** Patlytics ships is a non-obvious win — lets attorneys pin a reference on a second monitor.

### 4.5 Patent figure annotation (Vision OCR fit — Q8)
**Pattern:** Detect reference numerals via OCR, map them to spec terms via ML, render bounding-box overlays on the figure. PatentLMM (Jan 2025) is the SOTA model; USPTO patent 11,080,910 covers the basic UI approach. Mistral Document AI's `box_annotation` is a useful reference. ([PatentLMM paper](https://arxiv.org/pdf/2501.15074), [USPTO 11,080,910](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11080910), [Mistral OCR cookbook](https://docs.mistral.ai/resources/cookbooks/mistral-ocr-data_extraction))

**Recommendation for us (Q8 roadmap):** When user hovers a reference number in the spec (e.g. "微通道 12"), highlight numeral "12" on the figure. Click the numeral on the figure → scroll spec to its definition. This is novel — no competitor surfaces this interaction.

---

## 5. Recommendations for `patentmind-poc`

### Must-have (Phase 4 sprint candidates)

| # | What to build | Why | Impact | Effort |
|---|---|---|---|---|
| 1 | **Three-pane side-by-side layout** (OA / draft / cited refs) with pop-out reference viewer | Universal pattern across Patlytics/IP Author/DeepIP. "Tab switching" is the #1 cited pain point. Our current vertical scroll forces context loss. | High | M |
| 2 | **Claim dependency tree in left rail**, color-coded by rejection status | ClaimMaster, Solve, Patlytics all ship this. Lets attorneys triage which rejections matter. Maps directly to our Q11 spotlight data — backend already has the info. | High | S |
| 3 | **Inline citation hover-preview + deep link** in draft | Citation grounding is 2026 table-stakes. Our Q14 verifier already produces the data; UX surface is missing. Hover tooltip + click-to-scroll right pane. | High | S |
| 4 | **USPTO markup export** (underline/strikethrough) toggle on `DraftEditor` | This is the literal output format the user submits to USPTO/TIPO. Today our draft is plain text → attorney has to reformat manually. ClaimMaster/Patentbots ship this. | High | S |
| 5 | **Cmd/Ctrl+K command palette** for global navigation (jump to case, view audit, switch language) | Harvey-set baseline. Lawyers conditioned by Linear/Notion. Removes mouse dependency for power users. | Medium | M |
| 6 | **"Examiner-style review" pre-submit check** (mirror of DeepIP collaboration pattern stage 2) — runs verifier + masking + provenance unsigned-line check, surfaces a single readiness score | Mirrors the 3-stage review pattern the industry is converging on. Repurposes our existing audit + provenance infra. | Medium | S |
| 7 | **Shared "Workroom" view** — case-scoped, role-aware (outside counsel / in-house / inventor) — even read-only V1 | Lexis+ Workrooms (May 2026) is the new bar. Outside-counsel ↔ in-house handoff is "the most broken part of OA work" per DeepIP. Our Q12 ACL + Q13 audit are the foundation. | Medium | M |
| 8 | **Bilingual UX hardening**: language switcher in header `正體中文 / English` (text labels, no flags); Noto Sans TC before Noto Sans for `font-family`; preserve scroll position on switch | Half our target users are TW. Current i18n is partial. Linguise guide: text labels > flags; native + English label pairing. | Medium | S |

### Nice-to-have (Phase 5+)

| # | What to build | Why | Impact | Effort |
|---|---|---|---|---|
| 9 | **Figure annotation overlay** (Q8) — hover spec → highlight numeral on figure | Novel; no competitor does this well. PatentLMM gives us the ML primitive. | Medium | L |
| 10 | **Claim chart auto-generation** — claim language vs cited prior art passages in tabular form | Patlytics ships this. Reusable artifact for the response. | Medium | M |
| 11 | **PDF preview pane with figure callouts** (already on roadmap; promote) | Eliminates the "open in another app" tax. | Medium | M |
| 12 | **Drag-and-drop OA upload** with file-type sniffing | Already noted as P2. Modern table-stakes. | Low | S |
| 13 | **Antecedent basis + claim numbering linter** — pre-submit | Removes #1 source of "unforced errors" cited in IP Author. Patentbots has shipped this since 2018; we have none. | Medium | M |
| 14 | **Workflow templates** ("§103 obviousness response", "§112 enablement response") — saved prompt presets | Lexis+ Protégé ships 300+. Solo TW attorneys want jurisdiction-specific starting points. | Medium | M |
| 15 | **Customer-held encryption keys for confidential cases** (extend Q15 LOCAL_LLM routing) | Lexis+ May 2026 update. Bigger TW firms with FAB clients will ask. | Low | L |

### Already done well — don't regress

| Feature | Maps to research finding |
|---|---|
| **Line-level provenance editor** (`DraftEditor.jsx`, Q16) | Beats DeepIP/Solve — neither exposes per-line AI/attorney attribution. Critical for the 3-stage review pattern. |
| **Hash-chained tamper-evident audit** (`AuditView.jsx`, Q13) | Closest analogue is CoCounsel's "citation ledger" but ours is *user-verifiable*. |
| **Reversible PII + customer-dictionary redaction** (Q10) | No competitor surfaces the masked prompt to user. Builds trust; relevant under TW PIPA + EU GDPR. |
| **Grounded citation verifier as hard wall** (Q14) | Matches CoCounsel philosophy. Stanford HAI 2024 study is still the wedge selling point in 2026 buyer guides. |
| **Per-tenant Qdrant vector store roadmap** (Q5/Q7) | Lexis+ Vault, Harvey Vault both use this model. We've designed it in. |
| **Confidential-routing to local LLM** (Q15) | Lexis+ Workrooms uses customer-held keys for same purpose. We get there with on-prem inference. |
| **Quota + cost circuit breaker** (Q18) | No competitor surfaces this to user. We do (`SECURITY_BADGE` chips in `Analyze.jsx`). Differentiator for procurement. |

---

## 6. References

### Competitor product pages & docs
- [DeepIP — patent prosecution](https://www.deepip.ai/products/patent-prosecution)
- [DeepIP — AI Office Action 2026 guide](https://www.deepip.ai/blog/ai-office-action)
- [DeepIP — collaboration blog](https://www.deepip.ai/blog/office-action-response-collaboration)
- [DeepIP — Microsoft AppSource](https://marketplace.microsoft.com/en-ie/product/office/WA200006965?tab=Overview)
- [Solve Intelligence — homepage](https://www.solveintelligence.com/)
- [Solve Intelligence — G2 reviews](https://www.g2.com/products/solve-intelligence-patent-copilot/reviews)
- [Harvey — platform](https://www.harvey.ai/platform)
- [Harvey — getting started](https://help.harvey.ai/articles/getting-started-with-harvey)
- [Harvey — The Brief March 2026](https://www.harvey.ai/blog/the-brief-march-2026)
- [Harvey — The Brief April 2026](https://www.harvey.ai/blog/the-brief-april-2026)
- [PatentPal — homepage](https://patentpal.com/)
- [PatentPal — 7 new features](https://medium.com/patentpal/7-new-features-on-patentpal-draft-3b7811d51f95)
- [Lexis+ with Protégé — product](https://www.lexisnexis.com/en-us/products/lexis-plus-protege.page)
- [Lexis+ Protégé launch — LawSites Feb 2026](https://www.lawnext.com/2026/02/lexisnexis-launches-lexis-with-protege-replacing-lexis-ai-with-an-end-to-end-workflow-platform.html)
- [Lexis+ Workrooms expansion — LawSites May 2026](https://www.lawnext.com/2026/05/lexisnexis-expands-lexis-with-protege-adding-agentic-skills-collaboration-workrooms-and-customer-held-encryption-keys.html)
- [CoCounsel Reimagined — TR Institute](https://www.thomsonreuters.com/en-us/posts/innovation/cocounsel-legal-reimagined/)
- [TR x Anthropic May 2026](https://www.thomsonreuters.com/en/press-releases/2026/may/thomson-reuters-and-anthropic-expand-partnership-to-connect-claude-with-cocounsel-legal)
- [Deep Research in CoCounsel — Medium](https://medium.com/tr-labs-ml-engineering-blog/deep-research-in-westlaw-and-cocounsel-building-agents-that-research-like-lawyers-508ad5c70e45)
- [NLPatent — product FAQ](https://support.nlpatent.com/article/12-product-features-faq)
- [Patentext — best AI patent tools 2026](https://blog.patentext.com/blog-posts/best-ai-patent-drafting-tools)
- [Patlytics — 2026 OA guide](https://www.patlytics.ai/blog/2026-guide-modern-office-action-patent-prosecution)
- [Patlytics — multitasking workspace](https://www.patlytics.ai/blog/a-smarter-multitasking-workspace-for-patent-prosecution)
- [IP Author — broken workflow + AI fix](https://ipauthor.com/patent-prosecution-workflow-ai/)
- [IPWatchdog — DeepIP press release](https://ipwatchdog.com/press/deepip-revolutionizes-patent-office-actions-new-ai-powered-module/)

### Comparison & buyer guides
- [Lexology — DeepIP vs Solve Intelligence 2026](https://www.lexology.com/library/detail.aspx?g=a945581a-89b2-45ca-9a37-894711af9cdc)
- [GC AI — Harvey review 2026](https://gc.ai/blog/harvey-legal-ai-review)
- [Cypris — best AI patent search tools 2026](https://www.cypris.ai/insights/best-ai-patent-search-tools-in-2026-the-definitive-guide-for-r-d-and-innovation-teams)
- [Westlaw AI Review 2026](https://www.aivortex.io/legal/ai-tools/westlaw-ai/)
- [Triangle IP — patent prosecution software 2026](https://triangleip.com/best-patent-prosecution-software/)

### UI patterns
- [ClaimMaster — visualizing claim trees](https://www.patentclaimmaster.com/blog/visualizing-claim-trees/)
- [ClaimMaster — USPTO ↔ track changes conversion](https://www.patentclaimmaster.com/blog/tutorial-switch-between-uspto-formatting-and-track-changes/)
- [Patentbots — track changes feature](https://blog.patentbots.com/2018/09/new-features-track-changes-conversion.html)
- [Apryse — multi-viewer mode](https://apryse.com/blog/webviewer/compare-pdf-office-or-image-side-by-side-or-multi-tab-view)
- [Everlaw — Difference Viewer](https://www.everlaw.com/blog/legal-technology/introducing-difference-viewer/)
- [Shape of AI — citation patterns](https://www.shapeof.ai/patterns/citations)
- [Lazarev — legaltech UX/UI principles](https://www.lazarev.agency/articles/legaltech-design)

### Citation grounding & hallucination
- [Stanford HAI — legal models hallucinate 1 in 6](https://hai.stanford.edu/news/ai-trial-legal-models-hallucinate-1-out-6-or-more-benchmarking-queries)
- [Hausfeld — AI hallucinations part 2](https://www.hausfeld.com/what-we-think/perspectives-blogs/part-2-ai-for-legal-professionals-hallucinations)
- [HalluGraph — Knowledge graph alignment for legal RAG](https://arxiv.org/pdf/2512.01659)
- [Assessing reliability of legal AI research tools — arXiv 2405.20362](https://arxiv.org/pdf/2405.20362)
- [AiOps School — citation grounding 2026 guide](https://aiopsschool.com/blog/citation-grounding/)

### Patent figure / OCR / Vision
- [PatentLMM — multimodal model for patent figures](https://arxiv.org/pdf/2501.15074)
- [USPTO 11,080,910 — reference numeral display via ML](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11080910)
- [Mistral OCR — data extraction cookbook](https://docs.mistral.ai/resources/cookbooks/mistral-ocr-data_extraction)

### Bilingual + accessibility
- [Noto Sans TC — Google Fonts](https://fonts.google.com/noto/specimen/Noto+Sans+TC)
- [Noto Sans implementation guidance](https://notofonts.github.io/noto-docs/website/use/)
- [Linguise — language switcher UX for non-Latin scripts](https://www.linguise.com/blog/guide/designing-language-switcher-ui-for-non-latin-script-users-best-practices-ux-tips/)
- [az-loc — best fonts for CJK websites 2026](https://www.az-loc.com/best-fonts-for-chinese-japanese-korean-websites/)
- [WCAG 2.1 spec](https://www.w3.org/TR/WCAG21/)
- [ADA Title II web rule April 2024](https://www.ada.gov/resources/2024-03-08-web-rule/)
- [Level Access — WCAG 2.1 AA checklist](https://www.levelaccess.com/resources/benchmark-ada-title-ii-compliance-the-must-have-wcag-checklist/)

### TW / TIPO context
- [Lexology — TIPO Chinese translation of prior art references](https://www.lexology.com/library/detail.aspx?g=c4d917e0-5eb2-4823-add9-e19097aee922)
- [ipnote.pro — Taiwan OA responding](https://ipnote.pro/taiwan/arb/services/patent-registration/patent-office-action-responding/)
- [Lawyer Monthly — Taiwan patent system 2024](https://www.lawyer-monthly.com/2024/12/taiwans-patent-system-key-differences-and-challenges-for-foreign-companies/)

### Industry surveys & economics
- [AIPLA 2023 Economic Survey (PDF)](https://fundamentalpatlit.com/wp-content/uploads/2024/02/AIPLA.pdf)
- [AIPLA Economic Survey 2017](https://www.aipla.org/detail/journal-issue/economic-survey-2017)
- [PARIS → LE-PARIS — patent response automation arXiv](https://arxiv.org/pdf/2402.00421)
- [Artificial Lawyer — 2026 predictions](https://www.artificiallawyer.com/2026/01/08/artificial-lawyer-predictions-2026/)
