# UX Personas & User Journeys — PatentMind AI (2026-06-05)

> Companion to `docs/UX_RESEARCH.md` (competitor + 8-pattern deck) and `docs/PRODUCT_STRATEGY.md` (positioning + pricing). This doc goes deep on **who** we are designing for and **what their day looks like**. Designer should be able to draft screens from this without further interview.
>
> Method: 30+ public sources (May–June 2026), cross-referenced with the workflow primitives baked into `backend/gateway/` and `backend/ai_engine/`. Personas are composites — names invented, every behaviour traceable to a cited source or to our existing architectural decisions in `docs/DECISIONS.md`.

---

## 0. The cast in one paragraph

PatentMind serves two firm shapes — the **TW 200+ professional shop** (Lee and Li, Tai E, Tsai Lee & Chen, Saint Island, Formosa Transnational) and the **US small/mid IP boutique** (the under-30-attorney shops that file ~70% of US prosecution work outside AmLaw 100). Inside each shop, our daily users decompose into five archetypes: **the partner who signs**, **the attorney who drafts**, **the bilingual bridge who routes between Taipei and Alexandria**, **the paralegal / 助理工程師 who pre-chews everything**, and **the IT lead who approves the vendor**. The first four use the product. The fifth decides whether the first four ever see it. Lose any of the five and the deal dies — but only one of them ever signs the PO.

---

## 1. The five named personas

### 1.1 陳麗華 / Senior Equity Partner, IP Department / 52 / 24 yrs (TW)

> Status anchor. Decision authority. Lowest tolerance for "AI-y" UX. Reviews drafts on iPad between meetings — never at a desktop during business hours.

**Firm context.** Lee-and-Li-tier full-service firm: 800+ professionals across Taipei + Hsinchu, ~120 patent attorneys, client mix is 60% TW/JP semiconductor + LCD + biopharm (TSMC, MediaTek, AUO, Genentech APAC), 30% US/EU inbound (filed via US/EU correspondents into TIPO), 10% TW SMEs. The firm is on the [Chambers Greater China top tier and has explicit on-prem-only contracts with TSMC](https://chambers.com/office/lee-and-li-attorneys-at-law-taipei-taiwan-jurisdiction-greater-china-region-116:2315) ([Lee and Li firm profile](https://www.leeandli.com/EN/000000002.htm)).

**Education + licences.** NTU Law BA → Taipei Univ. LLM (智財權法組) → 專利師證書 #0xxx (passed in 2002, the second cohort after the [Patent Attorney Act took effect](https://law.moj.gov.tw/ENG/LawClass/LawAll.aspx?pcode=J0070034)). No USPTO Reg. — relies on US correspondent firms for US filings.

**Tech literacy (3/10).** Uses Outlook + Word + the firm's bespoke docketing (a 2008 in-house build wrapped around 智財局 IPNET). Has a personal ChatGPT-Plus account she does **not** mention to junior partners. Asks her secretary to "send me the PDF" rather than fetch it from SharePoint herself. iPad Pro 13" with Apple Pencil is her primary review device — she annotates drafts in PDF Expert, then her secretary takes the marked-up PDF and propagates the edits into Word.

**Daily tools today.** Outlook (calendar + email gateway), Word 2021 desktop, PDF Expert (iPad), TIPO IPNET portal (for status checks), 全國法規資料庫 / 法源, 工商時報 + IPRdaily 日報, LINE (client comms — yes, partners still use LINE for senior client touchpoints), the firm's docketing wrapper.

**Top 3 pains.**
1. Draft skeletons that "smell of AI" — overuse of "Furthermore," "It is noteworthy that," and the GPT cadence pattern. She has reputation skin in the game and won't sign a sentence she didn't write.
2. Junior attorneys re-doing prior-art searches she has already paid for and reviewed in a 2022 case for the same client family. The institutional memory leak.
3. Being asked to review 22 OAs across 3 days because everyone batches deadlines on the last extension day ([TW deadline is two months for domestic, three months for foreign with one extension](https://www.lexology.com/commentary/intellectual-property/taiwan/lee-and-li-attorneys-at-law/how-are-new-deadlines-calculated-for-office-action-reply-extensions)).

**Top 3 desires.**
1. A 90-second per-draft review surface that lets her say yes/no/redline without leaving iPad — "give me the three things that matter, not the 18-page draft."
2. Confidence that confidential client matters (TSMC, MediaTek) have never touched a US cloud endpoint, demonstrable to the client's IT in 30 seconds.
3. A way to teach the system her own redlines so the next draft on the same case family sounds like her, not like the junior who wrote v1.

**Quote.** *"AI 是給助理工程師的工具，不是給我用的。但是如果它能讓我少看 10 份初稿、又不會出包，那合夥人會議我就會幫它說話。" / "AI is for the assistant engineers, not for me. But if it lets me review 10 fewer drafts a month without screwing up, I'll back it at the partner meeting."*

**What makes her champion the tool.** Signing the draft from her iPad on the high-speed rail back to Hsinchu — once. The first time she can close a TSMC OA between meetings without calling her secretary, she will mention PatentMind in three partner committees within a week.

**What makes her silently uninstall after 2 weeks.** A single hallucinated cite passed through the verifier and into her signed draft. One. We do not get a second chance with this persona. Also: any UI element that looks like a chatbot. She read [Stanford HAI's "1 in 6 legal queries hallucinate" study](https://hai.stanford.edu/news/ai-trial-legal-models-hallucinate-1-out-6-or-more-benchmarking-queries) — partner reading lists circulate it.

**Anti-pattern.** Do NOT design a "Chat with PatentMind" surface for her. She does not type to AI. She reviews. Surface = "Open inbox of items needing your sign-off," not "Ask me anything."

---

### 1.2 林冠廷 / Mid-Career Patent Attorney, Semiconductor Group / 36 / 9 yrs (TW)

> The drafter. Drowning in OAs. Secret AI early-adopter. Will use ChatGPT inside the masking layer if we don't give her a better tool. This is the persona Journey B is built around.

**Firm context.** Same firm as 陳麗華 or one tier down (Tai E, Tsai Lee & Chen — ~270 professionals across 4 offices ([Tai E profile](https://www.ipstars.com/Firm/Tai-E-International-Patent-Law-Office-Taiwan/Profile/102270))). Semiconductor group, ~14 attorneys, clients are tier-2 fabs and IP-house licensors. Carries 35–55 active OAs at any moment — domestic + US/JP via US correspondents. AIPLA pegs **4.2 office actions per granted utility patent on average** ([Patlytics 2026 OA guide](https://www.patlytics.ai/blog/2026-guide-modern-office-action-patent-prosecution)); she absorbs ~12 OAs/month at fixed fee.

**Education + licences.** NTHU Materials Science BS → NCKU Law LLM (專利法組) → 專利師證書 #1xxx, passed 2019. Considering USPTO patent agent registration but the Office of Enrollment and Discipline restricts full registration to US citizens/residents, so she can at most get [limited recognition under 37 CFR § 11.9(b)](https://www.uspto.gov/learning-and-resources/patent-and-trademark-practitioners/becoming-patent-practitioner). She has not pursued it.

**Tech literacy (7/10).** Heavy Excel user (her personal OA-tracking spreadsheet has 47 columns), built her own VBA macros to auto-renumber claims in Word, uses ChatGPT-Plus and Claude.ai daily — pastes redacted OA text into both and compares outputs. Reads Hacker News, /r/patentlaw, IPWatchdog. Owns a Mac at home, Windows ThinkPad at work.

**Daily tools today.** Word (10+ hours/day), Outlook, the firm's docketing wrapper, Google Scholar + Espacenet + PatentScope + USPTO Public PAIR + 全球專利檢索 for prior-art recheck, ChatGPT-Plus + Claude.ai (against firm policy — she manually redacts), Notion (personal — claim-tree sketches), DeepL Pro for JP→ZH technical translation. Has tried Solve Intelligence's 14-day trial and hated the latency.

**Top 3 pains.**
1. Re-reading examiner citations she already read three months ago on a sister application — she has no per-case institutional memory layer.
2. The 90-minute "blank page → first draft paragraph" stall on §103 obviousness rejections. She knows the answer in her head; getting it into structured Word prose is the friction.
3. Firm IT blocked her from installing the [DeepIP Microsoft Word add-in](https://www.deepip.ai/blog/davinci-your-trusted-ai-patent-drafting-tool-now-in-microsoft-word) — she had a procurement-approved trial lined up and IT killed it citing "cloud data egress."

**Top 3 desires.**
1. "Draft skeleton in 3 minutes that I can iterate on" — not a finished draft (she wouldn't trust one), a structured starting point with rejection-by-rejection placeholders and pre-pulled citations.
2. A per-client / per-case "what arguments did we use last time" memory — searchable, jurisdiction-tagged.
3. Real keyboard shortcuts. She's a Vim user. Mouse-driven UI loses to ChatGPT in a side-by-side test for her.

**Quote.** *"ChatGPT 解得了 80% 的 §103，但我每次都要把客戶資料先 mask 過、再貼進去、再把答案 copy 出來。如果你們的東西能把這段流程包掉，我馬上 switch." / "ChatGPT solves 80% of §103 problems, but I have to manually mask client data, paste it in, copy the answer back out. If PatentMind wraps that loop, I switch tomorrow."*

**What makes her champion the tool.** A single moment where she runs a §103 response in 22 minutes that would have taken her 90, and the citations all check out under the verifier. She will Slack the whole semiconductor group screenshots within the hour. She is our viral seed.

**What makes her silently uninstall.** Latency >4s on every Analyze click. Word add-in lock-in (she needs browser editor parity). Forced workflow that doesn't let her edit the draft in-place. Slow citation hover. Any moment where she thinks "I could have just used ChatGPT for this."

**Anti-pattern.** Do NOT hide the prompts from her. She wants to see the prompt the system sent the LLM. Black-box AI loses to ChatGPT for her — at least with ChatGPT she controls the prompt. Our redacted-prompt-visibility (Q10) is a feature for her specifically.

---

### 1.3 Jessica Wang / US-Licensed Bilingual Counsel, Cross-Border Desk / 41 / 14 yrs (US/TW)

> The bridge. Drafts in English, reviews TW OAs in zh-TW, manages deadlines across UTC-5 (NY) and UTC+8 (Taipei). Routes work between her TW firm and the US correspondent.

**Firm context.** Either (a) US-licensed senior associate at a TW top-10 firm running their US-correspondent desk, or (b) Taipei-based foreign-trained partner at a US firm's TW office (Finnegan TW, Kirkland TW). Client mix: 70% TW-origin inventors filing into US (TSMC, MediaTek, GlobalWafers, ITRI spinouts), 30% US-origin filing into TW. Manages ~20 active matters spanning both jurisdictions.

**Education + licences.** Taipei Univ Law BA → Berkeley LLM → NY Bar (2014) → USPTO Reg. No. 7xxxx (passed registration exam 2015, US citizen). Did not sit 專利師 — under TW law she can practice as a foreign attorney within scope.

**Tech literacy (8/10).** Power user. Lives in Outlook + Word + the firm's docketing wrapper + USPTO Patent Center (for US filings) + TIPO IPNET (for TW). Uses two monitors at the office, MacBook at home, iPad for client calls. Has a personal Notion workspace with her own claim-construction case-law library. Pays for both ChatGPT-Plus and Claude Pro out of pocket. Wrote a [Public PAIR-replacement scraping script](https://www.waltmire.com/2014/03/13/viewing-patent-application-status-history-uspto-online-pair/) in Python because the Patent Center search is "slow garbage."

**Daily tools today.** Outlook calendar (deadlines on both NY + Taipei time, color-coded by jurisdiction), USPTO Patent Center, TIPO IPNET, Public PAIR via her scraper, Anaqua (the firm's official docketing), DeepL Pro, Westlaw + KeyCite, AILA's PALS for client-confidentiality, LINE + WhatsApp + Slack (depending on the client).

**Top 3 pains.**
1. **Translating TW OAs to send to US clients, and translating US OAs to send to TW inventors** — both directions, every week. Machine translation is "good enough for the gist, terrible for the legal-effect language."
2. **Dual-jurisdiction deadline math.** When a TW OA arrives, she needs to know: TW response date (two months for residents / [three months for foreign, with one possible extension](https://www.lexology.com/commentary/intellectual-property/taiwan/lee-and-li-attorneys-at-law/how-are-new-deadlines-calculated-for-office-action-reply-extensions)), US filing's continuation deadline if any, client-side internal review window, and her own travel + holiday roll-forward. Today this lives in her head + a sticky-note.
3. **Routing a TW-drafted argument to the US correspondent in a USPTO-ready format.** TW colleagues draft in zh-TW Word, she has to rewrite into US legal English + reformat to USPTO underline/strikethrough markup ([the post-2024 DOCX format](https://www.patentclaimmaster.com/blog/tutorial-switch-between-uspto-formatting-and-track-changes/)). She estimates this rewrite eats 1.5–2h per cross-border response.

**Top 3 desires.**
1. **One screen showing the TW timeline AND the US timeline for the same patent family**, side by side, with the soonest deadline in red. This does not exist in any tool she has tried.
2. **Bilingual draft view** — left pane the zh-TW source, right pane the en-US version, line-locked. Edits in either pane propagate (or at minimum highlight the affected line in the other).
3. **One-button "send to US correspondent" packet** — the draft in USPTO markup, the cited references with passages highlighted, the deadline math, the case ACL invitation. No more "compose email + attach 7 PDFs."

**Quote.** *"I'm the human glue between TIPO and USPTO. Anything that automates that glue is gold. Anything that breaks it because someone forgot zh-TW exists makes my month worse."*

**What makes her champion the tool.** A 90-second handoff to the US correspondent that previously took 2 hours. She is the persona who blogs on LinkedIn — wins here are inbound for us.

**What makes her silently uninstall.** Half-baked translation that her US correspondent rejects ("this isn't legal English"). Any moment where the system silently drops a zh-TW character or uses simplified instead of traditional. UI that assumes US-first navigation (e.g., the dashboard sorts by USPTO due date with TIPO due date as a secondary filter).

**Anti-pattern.** Do NOT auto-translate her drafts into the other language. SHOW the source and the target side-by-side, with the AI translation as a starting point she can override line-by-line. She has been burned by "helpful" auto-translation that silently changed 揭露 to 公開 in a §112 enablement argument.

---

### 1.4 王俊豪 / Senior Paralegal & 助理工程師 / 29 / 6 yrs (TW)

> Power user, not decision-maker. Does the first-pass OA read, prepares the draft skeleton, formats the filing, files it. The system's most frequent user. The persona PMs forget when they design for "the attorney."

**Firm context.** Same firm as 陳麗華 / 林冠廷. The TW patent-firm hierarchy is **partner → associate attorney → senior paralegal / 助理工程師 (assistant engineer with technical background, not a paralegal in the US sense) → junior paralegal**. The 助理工程師 role is unique to TW — a technical-degree holder who is on track to sit 專利師 but currently does the first-pass technical reading and draft preparation that a US attorney would otherwise own. [TW patent teams explicitly include "patent engineers" in addition to attorneys, agents, and paralegals](https://www.li-cai.com.tw/en/).

**Education + licences.** NCTU EE BS, no graduate degree, no 專利師 yet (taking 2026 exam, third attempt). Reports to a senior attorney; carries case-level institutional knowledge across her case load.

**Tech literacy (8/10).** The actual UI power user. Knows every 智財局 form by number. Has rebuilt the firm's claim-renumbering macros twice. Maintains the Excel spreadsheet that the entire group runs deadlines off. Has a Python script that scrapes IPNET for status changes.

**Daily tools today.** Word + Excel (all day), 智財局 IPNET (filing portal), TIPO 線上申請系統, the firm's docketing wrapper, Adobe Acrobat Pro (for the post-2024 DOCX → PDF/A conversion), Outlook, LINE Work, EVERSIGN for client signature capture, EndNote for cited-art library, [PubMed for biopharm prior art](https://www.tipo.gov.tw/en/cp-311-880718-aaeec-2.html).

**Top 3 pains.**
1. Manually re-typing the examiner's claim-rejection mapping into a spreadsheet from a scanned 初審審查意見通知函 PDF — the TIPO OAs are not always text-extractable and OCR garbles 數字 in chemistry claims.
2. Filing-system error rejection at TIPO — claim numbering off by one, missing 申請人 stamp, wrong revision marker. Every error means a re-file the next day and a "talk" with the attorney.
3. **Lack of credit.** She does most of the substantive prep but the partner sees only the attorney's name on the draft. AI tools that pretend the attorney did all the work make her invisible to firm leadership.

**Top 3 desires.**
1. A claim-tree + rejection-table view that the system populates from the OA PDF in 30 seconds. Not magic — just OCR + the structured extraction she already does manually.
2. A pre-flight check that flags TIPO format errors BEFORE she files (claim numbering, antecedent basis, marker consistency) — patterned on [ClaimMaster's antecedent-basis linter](https://www.patentclaimmaster.com/automation.html) but tuned for TIPO.
3. **Provenance that surfaces her contribution.** Our Q16 line-level provenance editor could be extended to attribute "drafted by 王俊豪, reviewed by 林冠廷, signed by 陳麗華" — this is a recruiting tool for her at her firm.

**Quote.** *"我做了 80% 的活，但 demo 給合夥人看的時候，畫面上只看到律師按一個按鈕。系統要記得我做了什麼，不然我永遠是看不見的人。" / "I do 80% of the work, but when they demo to partners the screen only shows the attorney clicking one button. The system needs to remember what I did, or I stay the invisible one."*

**What makes her champion the tool.** Her name surfacing in the audit chain (Q13) and in the provenance footer of every draft she touches. The first time her group head says "王 paralegal, your draft 預備 work cut my review time in half" — she becomes our internal advocate.

**What makes her silently uninstall.** A UI that assumes one-attorney-per-case. A UI that hides her from the audit trail. A UI that makes her re-type the rejections she already coded. A UI that auto-fills her name with the attorney's because "attorney" is the modeled role.

**Anti-pattern.** Do NOT design role-gated screens that hide functionality from her "for her protection." Junior paralegals in 2026 do more substantive work than US biglaw associates do in their first 2 years. Treat her as a power user, with audit on the back end.

---

### 1.5 Marcus Lin / IT & Compliance Lead (often Operations partner) / 47 / 17 yrs at the firm (TW)

> Gatekeeper. Tech-literate but not a developer. Signs the SOC 2 questionnaire. Decides whether 林冠廷 ever gets a PatentMind login. If we lose him in week 1, we lose the firm forever.

**Firm context.** Same firm. Shared role: half operations partner, half "the guy who runs IT" — common shape at TW firms where IT has 4–8 people total ([Lee and Li has 800+ employees, but the IT team is small](https://www.leeandli.com/EN/000000318.htm)). Reports to the managing partner. Owns the firm's data-residency posture, the [TIPO information-security audit response](https://www.tipo.gov.tw/), the SOC 2 vendor-management process, and any decision involving cloud egress of client data.

**Education + licences.** NTU CSIE BS (1999), part-time Politics LLM (info-security policy concentration). [CISSP](https://www.isc2.org/Certifications/CISSP). Sits on the firm's privileged-information committee. Familiar with TPIsoftware's [digiRunner gateway](https://www.gartner.com/reviews/product/digirunner) (already deployed at Taishin and EnTie Bank, possibly his firm).

**Tech literacy (9/10).** Reads vendor architecture diagrams. Can spot a stale TLS cert. Writes the security questionnaire responses himself rather than handing them to the vendor.

**Daily tools today.** ServiceNow (or equivalent — internal ticketing), Microsoft Defender + Sentinel, AD/Entra ID, [VMware vSphere or RHEL/Proxmox](https://www.proxmox.com/) for the on-prem stack, Veeam backups, [the firm's pet docketing system that he keeps alive with shell scripts](https://www.alt-legal.com/), Slack (internal), LINE Work (cross-firm), Cisco Webex for client calls, Confluence for runbooks. Reads [LawSites](https://www.lawnext.com/), [Hacker News](https://news.ycombinator.com/), [/r/sysadmin](https://reddit.com/r/sysadmin), [IAPP newsletters](https://iapp.org/) (post-2026 AI Basic Act).

**Top 3 pains.**
1. **Vendor security questionnaires** that take 4-8 weeks per vendor ([200+ questions per Workstreet 2026 data](https://www.workstreet.com/blog/security-compliance-questionnaires)). He runs 12-20 per year and most vendors fail his on-prem question on slide 6.
2. **Shadow IT.** 林冠廷 using ChatGPT-Plus on a personal account is a fireable offence under the firm's data policy. He knows half the attorneys are doing it. He cannot police it himself; he needs a sanctioned alternative.
3. **TIPO + TW AI Basic Act + GDPR + client-specific DPAs** — TSMC's vendor agreement explicitly forbids any data egress to US cloud regions. Most US legal-AI vendors cannot accommodate this. He has personally killed three vendor pilots in the last 18 months.

**Top 3 desires.**
1. An **on-prem-deployable SaaS** he can stand up inside the firm's VPN, with [customer-held encryption keys](https://www.lawnext.com/2026/05/lexisnexis-expands-lexis-with-protege-adding-agentic-skills-collaboration-workrooms-and-customer-held-encryption-keys.html), and an audit log he can hand to a TSMC auditor.
2. A **single architecture-diagram page** he can show the managing partner that answers "where does the data live, who has access, who's been logged." If we make him assemble that from PDFs we're out.
3. A **vendor SOC 2 Type 2 report**, ISO/IEC 27001 certificate, and [a SIG-Lite or CAIQ questionnaire pre-filled](https://www.workstreet.com/blog/security-compliance-questionnaires) on day 1.

**Quote.** *"I don't care how good your AI is. I care whether I can prove to TSMC's auditor that their data never left Taiwan and that I can rebuild who saw what after a breach. If you can show me that in one screen, we talk price."*

**What makes him champion the tool.** A 30-minute deployment-validation call where he sees: digiRunner-shaped gateway, on-prem Llama for confidential cases, hash-chained audit log he can curl, PII redaction with reversible mapping table that never leaves the firm. (Every single one of those is already in our architecture per `docs/DECISIONS.md` — we just need to surface it.)

**What makes him silently uninstall.** Any UI element that says "Powered by [US cloud vendor]" without a clear "your data is on-prem" badge nearby. A single 3rd-party JS CDN on the login page. An admin panel that he can't audit changes on. Cookie banners that don't pass [PIPC review](https://iapp.org/news/a/taiwan-s-strategic-leap-into-ai-enacting-the-ai-basic-act-to-foster-innovation-governance).

**Anti-pattern.** Do NOT make him the "secondary" persona in the UI. The trust band, the on-prem badge, the audit chain link, the data-residency footer — he should see his concerns addressed on every screen the attorneys see. This is what `docs/PRODUCT_STRATEGY.md` §7 calls "trust signaling everywhere"; for Marcus it is procurement-gating.

---

## 2. Three detailed user journeys

### Journey A — 陳麗華 reviews + approves on iPad between meetings (12 minutes)

**Setup.** It is Tuesday 14:38. She has finished a client meeting in conference room 5, the next meeting is at 14:50 in conference room 9 (4 minutes' walk away). She opens her iPad on the way down the corridor. She has 12 minutes to review and sign three OA responses — semiconductor client, fixed-fee billed in March, response due Friday.

**Device.** iPad Pro 13" landscape mode. Apple Pencil in her hand. Safari (the firm does not deploy native iPad apps for new vendors).

| Stage | What she does | What she feels | What the system shows | Pain (today) | Opportunity |
|---|---|---|---|---|---|
| 1. Open | Tap PatentMind bookmark; biometric (Face ID) unlock | Time-pressured | Dashboard with "3 items need your sign-off" pinned at top, sorted by deadline | Today: nothing — she'd ask secretary | Deep link from her secretary's "ready for sign-off" Outlook email straight to the right case |
| 2. Pick | Tap top item: "US 18/xxx,xxx — 林 drafted, 王 prepped" | Light curiosity | Case header with badges: `機密 / on-prem` + `verifier passed` + `audit ✓ chain at row 4,217` | Today: she opens the Word doc on iPad — has to scroll 18 pages to find the substance | Header trust band answers "is this safe to sign?" in 2 seconds |
| 3. Skim rejection summary | Reads spotlight: "§103 over Smith + Tanaka" + "examiner's primary concern: limitation 1c claim differentiation" | "OK this is the case I remember" | Q11 spotlight in 3 bullets above the draft | Today: she reads the OA from scratch | Spotlight is the 12-minute attention surface |
| 4. Read draft | Scroll the draft in iPad Safari, two-column layout for landscape | Wary of AI cadence | Draft with line-level provenance gutter: `林` / `王` / `AI suggested` colour-coded | Today: provenance is invisible | She trusts what `林` wrote; she scrutinizes what `AI suggested` |
| 5. Check citation | Tap the `[GROUNDED_REF_3]` superscript in the draft | "Did the AI cite something fake?" | Pop-over with the exact 18-word passage from Tanaka col 4 ll. 12-30, highlighted; one tap → opens full Tanaka PDF in a side sheet | Today: she would have to ask secretary for Tanaka; she'd skip the check | This is the trust moment. Cite hover-preview is her churn-or-stay test |
| 6. Make a redline | Tap a sentence, "Sounds AI", pencil-annotate "rephrase: examiner ignored 第1c項的方向性" | Engaged now | Inline editor surfaces a comment thread; redline annotates as her change with her signature | Today: she'd email a screenshot back to 林 | Comment routes to 林 immediately as a Q13 audit row |
| 7. Sign | Tap "Sign + lock for filing" — Face ID confirms | Done | Banner: "Signed. Audit row 4,218. Locked for 王 to file." | Today: signs PDF, secretary handles | Audit row hash visible — she trusts the chain |
| 8. Next case | Swipe-back to dashboard | Routine | Item 2 of 3 promoted to top | Today: no batched view | Time saved: 8 minutes vs the email loop |

**Pain heat-map** (today, 1=cool, 5=hot): Stage 1 → 2 | Stage 2 → 4 (no case context on iPad) | Stage 3 → 5 (she reads OAs from scratch) | Stage 4 → 4 (AI cadence detection is mental cycles) | Stage 5 → 5 (no citation check possible on iPad) | Stage 6 → 4 (email loop) | Stage 7 → 3 | Stage 8 → 2.

**Three UI improvements that move the needle**
1. **iPad-native trust band**: `機密` + on-prem + verifier + audit-row chip pinned to the screen at all viewport sizes. This single chip is what she sells internally.
2. **One-tap citation hover-preview that works with Apple Pencil tap** (not just mouse hover). Patent attorneys WILL try to verify on iPad; touch ergonomics matter.
3. **"Sign and lock" with biometric confirmation that writes a single audit row** — distinguishable from "save draft." The intentional ceremony of the lock signals legal weight.

**Watershed moment.** Stage 5 — the citation pop-over. If she taps and sees the actual Tanaka passage in <300ms with the right lines highlighted, she signs. If she taps and waits 2 seconds, or sees the wrong passage, or sees a generic chunk that doesn't quote the actual examiner cite, she closes the iPad and forwards the email to 林 with "please come see me." We lose the next three cases.

---

### Journey B — 林冠廷 drafts a §103 obviousness response from scratch (45 minutes)

**Setup.** Friday 10:14. Inbox: USPTO OA arrived overnight for a continuation she filed in January. Client wants response in two weeks (fixed-fee budget = 4h; she expects 7-9h actual). She has a 90-min open block before lunch. She closes Slack.

**Device.** Windows ThinkPad, dual-monitor (left: code editor / Word; right: PDFs / browser). Vim keybindings activated in Chrome via Vimium.

| Stage | What she does | What she feels | What the system shows | Pain (today) | Opportunity / Churn risk |
|---|---|---|---|---|---|
| 1. Open case | Cmd+K → search "US 18/xxx" → enter | Speedy | Case detail with timeline (filed Jan, prior OA Sept, this OA today) | Today: 4 clicks in docketing wrapper | Cmd+K parity with Linear/Harvey — table stakes ([Harvey getting started](https://help.harvey.ai/articles/getting-started-with-harvey)) |
| 2. Upload OA | Drag-drop the OA PDF onto the case | "Will this fail like Solve did?" | Spinner, then claim tree on the left, rejection table on the right, all auto-extracted in <8s | Today: she'd extract rejections by hand into Excel | **Churn risk: if extraction takes >15s, she opens ChatGPT instead** |
| 3. Read the rejections | Scrolls rejection table: §103 over Chen (Foxconn US filing) + Patel; §112(b) on dependent claim 7 antecedent | Pattern-matching | Each rejection row expands to show the examiner's specific quotation + the claim language; click → highlights the cited art in side sheet | Today: she'd flip 40 pages of OA PDF | Side-by-side claim/art view ([Patlytics workspace](https://www.patlytics.ai/blog/a-smarter-multitasking-workspace-for-patent-prosecution)) |
| 4. Re-check Chen prior art | Tap Chen US 17/xxx in rejection table | Wants to confirm the examiner's reading | Chen US 17/xxx renders with the cited passages pre-highlighted; she scrolls to col 6 ll. 22-31 | Today: she'd search Public PAIR, download Chen, ctrl-F the cite | **Churn risk: if Chen takes >5s to render, she opens Public PAIR. She has a script for it.** |
| 5. Spot a distinction | She notices Chen's catalyst loading is 2-5wt%, the claim is 8-12wt%. The examiner glossed this. | Excited (this is the case-winner) | She right-clicks the passage → "Add to argument: distinction" | Today: she'd write this on a sticky note | First moment that **beats ChatGPT** — she's mining the actual PDF, not pasting text |
| 6. Generate draft skeleton | Click "Draft response from rejections + distinctions" | Skeptical but hopeful | Loading <20s; draft appears with `[ATTORNEY_FILL]` placeholders where she should add her own argument; AI-generated sentences are colour-coded by source: `[REJ-1]`, `[REJ-2]`, `[GROUNDED_REF_3]` | Today: blank Word page | **Watershed moment** — see below |
| 7. Edit the §103 paragraph | Cmd+I to enter the AI suggestion, modifies it: "Chen 揭露 2-5wt%，與本案 8-12wt% 的範圍不重疊" | Flow state | Cursor in inline editor; provenance gutter flips that line from `AI` to `林` automatically; AI suggestion archived (one click to restore) | Today: would have ChatGPT in another tab | Inline edit with one-click restore — this is the trust gesture |
| 8. Run verifier | Click "Verify citations" | Tense — last hallucination check | Verifier returns: 4 cites grounded, 1 cite "loose paraphrase" with a suggested rewrite | Today: she'd do this manually | Verifier as a hard wall (Q14) — keeps her from the "ChatGPT made up a case" embarrassment |
| 9. Format for USPTO | Click "Export USPTO markup" | Mechanical | Underline/strikethrough Word doc downloads, claim renumbering verified | Today: she'd run her own VBA macros | [USPTO post-2024 DOCX format](https://www.patentclaimmaster.com/blog/tutorial-switch-between-uspto-formatting-and-track-changes/) — table stakes |
| 10. Assign to 王 for filing prep | Click "Hand off to 王" | Done | Case timeline updates: "drafted by 林, awaiting paralegal prep" | Today: she'd email 王 | Audit row, deadline propagates to 王's dashboard |

**Pain heat-map** (today, 1=cool, 5=hot): Stage 2 → 5 (extraction is the time-killer) | Stage 4 → 5 (PDF retrieval friction) | Stage 6 → 5 (blank page) | Stage 8 → 4 (manual citation check) | Stage 9 → 5 (USPTO format). Everything else is 2-3.

**Three UI improvements that move the needle**
1. **Cmd/Ctrl+K command palette wired to cases, rejections, and references** — Harvey-baseline; ChatGPT-tab-switch killer.
2. **"Draft skeleton with placeholders" mode** (not a finished draft). The placeholders signal "you do the lawyering, I'll handle the scaffolding" — exactly the [judgment-amplifier framing](https://ipwatchdog.com/2026/05/26/patent-law-firms-face-ai-reckoning/) the market is converging on.
3. **In-line restore of AI suggestion after edit.** Lawyers fear the irreversible. Restore is the safety net that lets them edit aggressively.

**Watershed moment.** Stage 6 — the draft skeleton. If it appears in <20s, has the right rejections in the right order, leaves `[ATTORNEY_FILL]` placeholders for her judgment, and the cites in the AI portions actually trace back to grounded passages → she switches from ChatGPT permanently. If it appears in 60s, or has hallucinated cites, or is a finished essay that she has to redline back to a skeleton → she has Claude open in the next tab within 3 minutes.

---

### Journey C — Jessica handles a TW OA destined for a US client, with US correspondent routing (~3 hours)

**Setup.** Thursday 09:00 TPE / Wednesday 21:00 NY. TW OA arrived overnight on a TSMC continuation that is part of a US patent family. She needs to: translate the OA gist for TSMC IP counsel in Hsinchu, draft TW response in zh-TW, route a US-strategy memo to Finnegan (US correspondent) for parallel review, ensure both TW + US deadlines are correctly computed.

| Stage | What she does | What she feels | What the system shows | Pain (today) | Opportunity / PatentMind-unique |
|---|---|---|---|---|---|
| 1. Open the case family view | Cmd+K → "TW I/yyyyyy" | Multi-jurisdiction nerves | Family view: TW application + US continuation + US parent, with a unified timeline across UTC+8 and UTC-5 | Today: two browser tabs, two docketing systems | **PatentMind-unique** — no competitor surfaces TW/US family together |
| 2. View deadlines | Glance at the deadline strip | Time-anchored | Strip shows: TW response due `2026-08-12` (foreign applicant 3mo); US IDS deadline `2026-07-30` (citing this TW OA back to USPTO); next-soonest in red | Today: spreadsheet math | Q17 multi-jurisdiction holiday roll-forward already exists in backend |
| 3. Translate OA gist for client | Click "Generate client summary" → choose `en-US, executive, 200 words` | Pragmatic | 200-word zh→en summary appears with cites back to the original 初審審查意見通知函 paragraph numbers | Today: she'd write this in DeepL + edit | DeepL doesn't keep paragraph-level provenance — this does |
| 4. Side-by-side OA view | Toggle "bilingual" | Surgical | Left pane: zh-TW OA original. Right pane: en translation. Cross-language hover: hover a zh phrase → highlights the en counterpart | Today: two PDFs side by side | Side-by-side cross-language is **PatentMind-unique** |
| 5. Draft TW response in zh-TW | Click "Draft TW response (zh-TW)" | Productive | Draft appears in zh-TW with placeholders; Q15 routes this through on-prem Llama because TSMC is `confidential` security level | Today: Word from scratch | Confidential routing badge visible (Q15) |
| 6. Draft US strategy memo for Finnegan | Click "Draft US-correspondent strategy memo (en-US)" | Bridging | A 500-word en memo: "TW examiner's §103 reading vs the US parent's claim-construction history, suggested mirror-amendments to keep US claims aligned" | Today: 90-min rewrite of TW analysis into US legal English | **PatentMind-unique** — converts TW analysis to US-correspondent-ready legal English |
| 7. Generate Finnegan packet | Click "Send to US correspondent" → "Finnegan IP" | Liberated | Packet builds: en memo + USPTO-markup-formatted draft claim amendments + cited refs + deadline math + secure case-ACL invitation for Finnegan attorney to log in to a workroom (Q12 ACL extension) | Today: email + 7 PDF attachments + 2 hour rewrite | This is the **2-hour-to-90-second moment** |
| 8. Audit log review | Glance at "case audit" | Reassured | Audit chain shows every action: client summary generated, on-prem routing for confidential, bilingual draft created, packet exported, ACL granted to Finnegan attorney | Today: nothing | Marcus loves this view |

**Pain heat-map** (today): Stage 1 → 4 | Stage 3 → 5 (translation) | Stage 6 → 5 (rewriting) | Stage 7 → 5 (packet assembly). Stage 8 is interesting because it doesn't exist today and Jessica doesn't know to ask for it — but Marcus does.

**Three UI improvements**
1. **Family view as primary navigation noun** — not "case", "family." TW + US co-pending applications belong on one screen. (Maps to §5 mental-model recommendation below.)
2. **Bilingual side-by-side editor** with line-locked translation — the single largest PatentMind moat outside on-prem.
3. **"Send to correspondent" packet** — the workflow no competitor has built. DeepIP's [collaboration blog](https://www.deepip.ai/blog/office-action-response-collaboration) identifies outside-counsel ↔ in-house handoff as the most broken part; TW↔US is even more broken than US↔US.

**Watershed moment.** Stage 7 — the packet. If it builds in <60s and Finnegan's attorney accepts the workroom invite without a "what is PatentMind" call, Jessica becomes our LinkedIn case study. If the markup is wrong, or Finnegan's IT bounces the ACL invite, or the bilingual draft has a wrong character → 90-min cleanup, she emails the next packet manually, and never trusts the feature again.

---

## 3. Jobs-to-be-done

### 陳麗華 (Senior Partner)
- **JTBD-1.** When an urgent OA response lands on my iPad between meetings, I want a 90-second trust signal (audit + verifier + on-prem routing + provenance) so I can sign without leaving the corridor. *Competitor coverage: Harvey provides a "thinking steps" trail; Lexis+ Workrooms ships a similar attestation. Neither is iPad-native.*
- **JTBD-2.** When a draft contains AI-suggested language, I want line-level provenance and one-tap rewrite so I never put my signature on a sentence I didn't write. *Competitor coverage: nobody. Q16 is our edge.*

### 林冠廷 (Mid-career Attorney)
- **JTBD-1.** When I open a fresh §103 OA, I want a structured rejection table + claim tree + cited-art pre-fetch in under 15 seconds, so I don't context-switch to ChatGPT. *Competitor coverage: Patlytics, Solve, DeepIP all attempt this; ChatGPT is the actual incumbent because it's faster.*
- **JTBD-2.** When I'm staring at a blank page, I want a placeholder-scaffolded draft skeleton I can edit aggressively, so I keep judgment ownership and never produce "AI-cadence" text. *Competitor coverage: most competitors generate finished essays; nobody intentionally ships scaffolds.*
- **JTBD-3.** When my draft cites prior art, I want a hard-wall verifier that fails closed on un-grounded cites, so I never embarrass myself with a fake citation. *Competitor coverage: CoCounsel ledger, Lexis Shepard's. Ours (Q14) is comparable and on-prem.*

### Jessica (Bilingual US Desk)
- **JTBD-1.** When a TW OA arrives that affects a US patent family, I want a unified TW+US deadline view and a US-correspondent-ready packet builder, so I stop reinventing the email-with-7-attachments workflow. *Competitor coverage: nobody. This is greenfield.*
- **JTBD-2.** When I draft bilingually, I want line-locked side-by-side editing with cross-language highlighting, so I never silently drop a critical zh term in the English version. *Competitor coverage: DeepL is closest but lacks legal context; legal-AI competitors don't do bilingual editing.*

### 王俊豪 (Senior Paralegal / 助理工程師)
- **JTBD-1.** When I receive a scanned 初審審查意見通知函, I want a 30-second OCR + rejection-table extraction so I stop re-typing examiner mappings into Excel. *Competitor coverage: Patlytics partially; ClaimMaster antecedent-basis lint.*
- **JTBD-2.** When I finalize a TIPO filing, I want a pre-flight check that flags format/numbering/marker errors so I don't get bounced by TIPO and called into the senior attorney's office. *Competitor coverage: ClaimMaster does this for USPTO; nobody does it for TIPO.*
- **JTBD-3.** When I contribute to a draft, I want my name in the provenance + audit chain so my partner sees the substantive work I did. *Competitor coverage: nobody surfaces this. Q13+Q16 are our edge.*

### Marcus (IT / Compliance Lead)
- **JTBD-1.** When a vendor pitches us, I want a 30-minute architecture review with on-prem deploy + customer-held keys + auditable data residency, so I can move past slide 6 of the vendor questionnaire. *Competitor coverage: Lexis+ Workrooms (May 2026) introduced [customer-held keys](https://www.lawnext.com/2026/05/lexisnexis-expands-lexis-with-protege-adding-agentic-skills-collaboration-workrooms-and-customer-held-encryption-keys.html). Harvey, Patlytics, DeepIP do not. PatentMind ships this from POC.*
- **JTBD-2.** When TSMC asks for a breach-postmortem-ready audit log, I want a tamper-evident chain I can hand off in 5 minutes, so I'm never the bottleneck to a client audit. *Competitor coverage: CoCounsel ledger is close but vendor-attested, not user-verifiable. Ours (Q13) is user-verifiable.*

---

## 4. Workflow ethnography — 林冠廷's typical Tuesday (8 am – 7 pm)

Sources: cross-referenced with [ABA TechReport 2024 — 30% AI adoption, ChatGPT 52% of legal AI use](https://www.americanbar.org/groups/law_practice/resources/tech-report/2024/2024-artificial-intelligence-techreport/); [Clio 2025 Legal Trends — 79% AI adoption, 80% planning to increase, 65% report higher work quality](https://www.clio.com/about/press/the-science-behind-smarter-law-clios-2025-legal-trends-report-reveals-how-technology-is-rewiring-the-way-lawyers-work/); [IPWatchdog 2026-05 on the AI squeeze](https://ipwatchdog.com/2026/05/15/patent-law-firms-face-ai-squeeze-as-clients-internalize-more-work/); [IP Author's "70% admin busywork" breakdown](https://ipauthor.com/patent-prosecution-workflow-ai/); /r/patentlaw working-life threads (commonly-cited 60-80 billable-hour weeks during deadline crunches); [Jobya's "Day in the life of an IP paralegal"](https://jobya.com/library/roles/b4t6w0i9/ip_paralegal/articles/b4t6w0i9_day_in_life_ip_paralegal).

```
07:55   MRT Songshan→Daan; reads Patently-O on phone
08:25   Coffee. Opens Outlook. 41 unread.
08:35   Triages email: 3 OAs arrived overnight (2 USPTO, 1 TIPO). Forwards to 王 for first-pass.
08:50   Opens docketing wrapper. Re-confirms this week's deadlines: 4 OAs, 2 filings, 1 review for partner.
09:10   First OA work-block. Opens PDF in Adobe + claim language in Word side-by-side. Pastes a chunk
        of the rejection into ChatGPT (incognito tab) with manual mask of client name. Annoyed she has
        to manually mask.
10:00   Stand-up with semiconductor group. 12 attorneys. Each: 1-min status. She's behind on 2 OAs.
10:15   Back to drafting. Stalled on §103 paragraph. Switches to Claude — different model often helps.
11:30   Quick call with 王 to align on the §112 antecedent-basis fix needed for TIPO filing this PM.
12:10   Lunch — 自助餐 around the corner. Scrolls Hacker News on phone.
13:00   Re-reads partner's redlines on a draft she submitted Monday. 陳麗華 changed 7 sentences with
        marginal notes "AI 味太重". Sighs. Updates draft, re-submits.
14:15   USPTO Public PAIR for prior art. Patent Center search "is slow garbage" today. Tries Espacenet,
        finds 1 missing reference.
15:00   Client call (LINE Work voice) — TSMC IP counsel asking about an old EP family. Pulls EP register
        via Espacenet.
15:45   Drafts §103 response from scratch. Blank page. Ninety minutes of struggle compressed into 35
        minutes of actual prose because she pastes redacted snippets into Claude. Done at 16:20.
16:25   Format conversion to USPTO underline/strikethrough. VBA macro fires. Manual fix for two cases
        the macro mangles. ~25 minutes — she calls this the "format tax."
17:05   Final read. Sends to 陳麗華 for sign-off. Updates docketing wrapper.
17:30   "Quick 30-min" with paralegal on TIPO filing → becomes 50 min.
18:30   Tries to leave. Email arrives: USPTO Patent Center filing rejection, claim numbering error. Re-files.
19:10   Leaves office. MRT home. Considers whether to apply to 王's group head's smaller spinout firm.
```

**Where PatentMind inserts itself.** Replace the mask-and-paste loop at 09:10 with a built-in Q10 redaction. Replace the model-shop at 10:15 with a routed multi-model call (Q15). Replace the format-tax at 16:25 with USPTO export. Replace the docketing-wrapper update at 17:05 with audit-chain automation. **Aggregate time saved: 90-130 minutes per OA day.**

**Where we must NOT insert ourselves.** The 09:50 triage to 王 — she trusts 王, not the system, for first-pass reads. The 13:00 partner-redline review — that's a human accountability moment we should observe but never automate. The 15:00 client call — never put PatentMind UI on a client-facing screen.

---

## 5. Mental-model alignment

Patent attorneys think in **claim trees**, **prior-art families**, **file wrappers (US) / 申請歷史檔案 (TW)** ([USPTO file-wrapper definition](https://blueironip.com/ufaqs/what-is-a-file-wrapper/), [MPEP §719](https://www.uspto.gov/web/offices/pac/mpep/s719.html)). Our UI right now thinks in **cases → OAs → drafts → audit**. Three mismatches:

**Mismatch 1: We call it "Case." They think "Family."**
A patent rarely lives alone. TW filing + US continuation + EP regional phase + JP divisional — these are one mental object. Jessica's Journey C dies if we model them as four separate cases. **Recommendation:** Promote "Family" to a primary navigation noun, with cases as members. `/family/:familyId` → list of jurisdictions × applications, unified timeline.

**Mismatch 2: We hide prior-art references inside the OA. They think "Reference is a citizen."**
An examiner-cited reference is reused across the family, across OAs, across years. 林's "I read Chen last March in a sister case" pain is a model mismatch — we treat Chen as a property of this OA, but she thinks of Chen as a recurring character with its own history. **Recommendation:** Promote "Prior-art reference" to a navigation noun. `/references/:refId` → every case in this tenant that cited it, every argument used, every distinction drawn. This is the **institutional memory layer** 陳麗華 wants.

**Mismatch 3: We show audit as a separate tab. They expect "prosecution history" inline.**
US attorneys live inside the file wrapper — every paper, every response, every rejection in chronological order. TW attorneys do the same with 申請歷史檔案. Our `AuditView` shows hash-chain trust signals but not the prosecution flow. **Recommendation:** Add a "Prosecution history" timeline view as the third tab of every case detail page (after Documents, before Audit). Show: original spec → claim amendments → each OA → each response → notice of allowance → maintenance. This is also where the **Q13 audit chain row appears beside each substantive event** — fusing trust with their existing mental model.

---

## 6. Anti-patterns + design rules

### What competitors do that we MUST NOT copy

- **ClaimMaster's overstuffed Word ribbon** (40+ buttons across 6 groups [in their automation tab](https://www.patentclaimmaster.com/automation.html)) — example of "more features = better." Patent attorneys are not Excel power users; ribbons exhaust them.
- **Anaqua's docket-first hierarchy** — every workflow starts at the docket, OA work is buried 3 clicks deep. Wrong for our personas; 林's primary verb is "draft," not "docket."
- **Generic "Chat with our AI"** (Lexis+ AI early launch, Harvey's Assistant) — patent attorneys do NOT want chat. They want forms with AI scaffolding. Chat is for general lawyers; patent attorneys want structured rejection tables.
- **Auto-submit / auto-file** — never auto-submit anything; everything is sign-off. The lock+sign ceremony is non-negotiable. (PatentPal's "one-click file" feature has been criticized in IPWatchdog comment threads as ethically risky.)
- **DeepIP's Word-add-in lock-in** — couples PatentMind to Office 365 licensing decisions and pushes Marcus into rejecting us because of cloud-egress concerns.
- **Patlytics' workspace pop-out flooding** — three floating windows by default ([Patlytics multitasking blog](https://www.patlytics.ai/blog/a-smarter-multitasking-workspace-for-patent-prosecution)) — beautiful in screenshots, awful on a 14" ThinkPad screen.
- **Harvey's "thinking trail" without verifier wall** — exposes process but doesn't fail closed; "1 in 6 hallucinations" study still applies.

### The 10 PatentMind Design Principles

1. **Judgment-amplifier, not labor-replacer.** Every AI output is a scaffold the attorney completes. We never claim to draft "the response" — we draft "a starting point."
2. **The lock is sacred.** Sign-off is a deliberate biometric or password-confirmed event with one audit row. No autosave masquerading as a signature.
3. **Provenance is gutter-rendered.** Every line in every draft shows who wrote it: 林 / 王 / AI suggested / 陳 redline. Always visible, never collapsed by default.
4. **Citations are hard-walled.** The verifier fails closed. Un-grounded cites cannot enter the export pipeline. The user sees the wall, can override only with explicit acknowledgement.
5. **The trust band is global.** On-prem badge + audit chain row + verifier status + redaction status visible on every screen the attorney sees. Marcus's concerns are the user's protection.
6. **Family is the noun.** TW + US + EP + JP variants of one invention live on one screen. Single-jurisdiction navigation is a degraded view, not the default.
7. **Cmd/Ctrl+K everywhere.** Power-user navigation is the way out of mouse-driven ChatGPT-tab-switch. Vim users keep the firm.
8. **Bilingual is line-locked.** Side-by-side zh + en editing with cross-language hover. Auto-translation is a draft, never a silent overwrite.
9. **Mask, then send.** No text leaves the gateway un-redacted. The redacted prompt is visible to the user before the LLM call — they trust what they can audit.
10. **The paralegal is a power user.** UI must surface 王's contribution in provenance and audit. Hiding the assistant engineer to "simplify" the screen costs us the firm's most frequent user.

---

## 7. Discovery validation plan

This persona work is hypothesis. Validate before sprinting.

### Five qualitative interviews × 60 min

Recruit via:
- **LinkedIn outreach** to 中華民國專利師公會 members (~1,200 registered as of 2025 per [TWPAA's directory](https://www.twpaa.org.tw/)). Filter on "patent attorney" + 5+ years + semiconductor/biopharm.
- **Sponsor a coffee corner** at TIPO's annual IP Day (April) and Asia IP Forum (October) — TWD 30,000 buys a 4-hour booth.
- **AIPLA Spring + Fall Meetings** for the US-licensed bilingual persona (Jessica equivalent).
- **NTU Law alumni network** for partner-level intros (陳麗華 equivalent).
- **Patently-O sponsored job-board ad** for US-side recruits (~$500/post per [Patently-O jobs rate](https://patentlyo.com/jobs)).

Target mix: 2 senior partners (TW), 2 mid-career attorneys (1 TW + 1 US), 1 bilingual US-desk attorney, 2 paralegals / 助理工程師, 1 IT/compliance lead.

### Interview guide (15 questions, bilingual)

1. 請描述上週三 (Wed) 的工作 — 每一段時間做什麼? (Diary recall)
2. 收到一份 OA 後，前 10 分鐘您做了什麼？
3. 一個 OA 從拿到到送出，總共花多少 hour? Fixed-fee 規定 vs 實際?
4. 您現在用的工具裡，哪一個讓您最痛？為什麼還沒換掉？
5. ChatGPT / Claude / Gemini 您用嗎？用在哪些階段？
6. 您試過哪些專利 AI 工具？哪些可以用、哪些卡住？
7. 在哪一刻您願意說「這個工具我會推薦給合夥人」？
8. 在哪一刻您會 silently uninstall？
9. 客戶 (TSMC、MediaTek、Genentech…) 對 AI 工具的態度是什麼？
10. 您的事務所 IT 對 AI vendor 採購流程是什麼？大約幾週？
11. 跨境 (TW↔US) 流程裡，哪一段最浪費時間？
12. 您看到 AI 草稿時，第一個檢查的是什麼？
13. 如果一個 AI 工具能保證 "您的客戶資料絕不出台灣"，這對您的決策權重是多少 (1-10)？
14. 您願意付多少 / 您的事務所願意付多少 per attorney per month?
15. 用 1-3 句話描述「理想的 OA 工具」。

(English mirror for Jessica + US-side recruits.)

### Diary study

3 participants × 2 weeks logging OA workflow. Daily 5-question form (Typeform): what OA stage you worked on, what tool you used, what friction you hit, what you copied between systems, what made you swear.

Compensation: TWD 8,000 per participant per week (= TWD 48,000 total) — slightly under the [TW patent attorney consult rate of TWD 6,000-12,000/hr](https://www.lexology.com/library/detail.aspx?g=fbc8ec3e-d24c-495c-970e-bee0a7597bf8) but matched for 2h/day commitment.

### Card-sort study for IA

24 cards × 8 categories (open card sort). Cards include: "case," "OA," "draft," "claim," "rejection," "prior-art reference," "family," "filing," "deadline," "audit," "verifier," "translation," "client," "partner sign-off," "paralegal handoff," "USPTO format," "TIPO format," "redaction," "on-prem badge," "settings," "dashboard," "team / ACL," "billing," "help." Use [Maze unmoderated card-sort](https://maze.co/) — runs USD 99/month.

Goal: validate the §5 mental-model recommendation (Family as primary noun, References as first-class citizens).

### Success criteria

- **Persona validation strong:** ≥4/5 interviewees confirm 3+ of the top-3 pains for their archetype, in their own words, unprompted.
- **Persona validation weak:** ≥3/5 interviewees describe a pain we didn't list in the top-3 — we revise.
- **Mental-model alignment confirmed:** ≥6/10 card-sort participants group "family / case / OA / reference" the way §5 predicts.
- **Watershed-moment confirmed:** ≥4/5 interviewees, when shown the Stage-6 draft-skeleton prototype, say "I'd switch from ChatGPT for this."
- **Procurement gating confirmed:** the IT lead interview surfaces ≥3 of the 5 trust signals (on-prem, customer-held keys, audit chain, redaction, residency badge) before being prompted.

### Budget

| Item | TWD | USD equiv |
|---|---:|---:|
| 5 interviews × 60 min (TWD 6,000 incentive each) | 30,000 | $1,000 |
| 3 × 2-week diary study | 48,000 | $1,600 |
| Card-sort tool (Maze, 2 months) | 6,000 | $200 |
| TIPO IP Day sponsorship | 30,000 | $1,000 |
| AIPLA Fall Meeting recruit booth | 60,000 | $2,000 |
| Patently-O job-board ad ×2 | 30,000 | $1,000 |
| Researcher time (50 hours @ NT$2,000/hr) | 100,000 | $3,300 |
| Transcription + translation services | 30,000 | $1,000 |
| **Total** | **334,000** | **~$11,100** |

---

## 8. References (additional to UX_RESEARCH §6)

- [中華民國專利師公會 (TWPAA)](https://www.twpaa.org.tw/)
- [Patent Attorney Act (Taiwan, English)](https://law.moj.gov.tw/ENG/LawClass/LawAll.aspx?pcode=J0070034)
- [Lee and Li firm profile](https://www.leeandli.com/EN/000000002.htm); [Lee and Li privacy stance](https://www.leeandli.com/EN/000000318.htm)
- [Tai E International Patent & Law Office](https://www.taie.com.tw/en/)
- [Tsai Lee & Chen Patent Attorneys & Attorneys at Law](https://www.worldtrademarkreview.com/rankings/wtr-1000/profile/firm/tsai-lee-chen-patent-attorneys-attorneys-at-law)
- [Chambers Greater China — Lee and Li](https://chambers.com/office/lee-and-li-attorneys-at-law-taipei-taiwan-jurisdiction-greater-china-region-116:2315)
- [Lexology — TW OA deadline extension rules (Lee and Li)](https://www.lexology.com/commentary/intellectual-property/taiwan/lee-and-li-attorneys-at-law/how-are-new-deadlines-calculated-for-office-action-reply-extensions)
- [In brief: patent prosecution in Taiwan (Lexology)](https://www.lexology.com/library/detail.aspx?g=fbc8ec3e-d24c-495c-970e-bee0a7597bf8)
- [Chambers Patent Litigation 2026 — Taiwan trends](https://practiceguides.chambers.com/practice-guides/patent-litigation-2026/taiwan/trends-and-developments)
- [USPTO — Becoming a patent practitioner](https://www.uspto.gov/learning-and-resources/patent-and-trademark-practitioners/becoming-patent-practitioner) and [registration exam](https://www.uspto.gov/learning-and-resources/patent-and-trademark-practitioners/becoming-patent-practitioner/registration)
- [Wysebridge — USPTO patent bar for foreign applicants](https://wysebridge.com/understanding-the-uspto-patent-bar-exam-process-for-foreign-applicants)
- [USPTO file wrapper (BlueIronIP)](https://blueironip.com/ufaqs/what-is-a-file-wrapper/); [MPEP §719](https://www.uspto.gov/web/offices/pac/mpep/s719.html); [USPTO Patent Center / PAIR overview (Waltmire)](https://www.waltmire.com/2014/03/13/viewing-patent-application-status-history-uspto-online-pair/)
- [IPWatchdog — patent law firms face AI squeeze (May 2026)](https://ipwatchdog.com/2026/05/15/patent-law-firms-face-ai-squeeze-as-clients-internalize-more-work/); [IPWatchdog — AI reckoning (May 2026)](https://ipwatchdog.com/2026/05/26/patent-law-firms-face-ai-reckoning/)
- [Clio 2025 Legal Trends Report press release](https://www.clio.com/about/press/the-science-behind-smarter-law-clios-2025-legal-trends-report-reveals-how-technology-is-rewiring-the-way-lawyers-work/); [2Civility summary](https://www.2civility.org/2025-clio-legal-trends-report/)
- [ABA 2024 TechReport — AI](https://www.americanbar.org/groups/law_practice/resources/tech-report/2024/2024-artificial-intelligence-techreport/); [ABA Journal coverage](https://www.abajournal.com/web/article/aba-tech-report-finds-that-ai-adoption-is-growing-but-some-are-hesitant); [LawSites](https://www.lawnext.com/2025/03/aba-tech-survey-finds-growing-adoption-of-ai-in-legal-practice-with-efficiency-gains-as-primary-driver.html)
- [Jeff Patton on pragmatic personas (StickyMinds)](https://www.stickyminds.com/article/how-pragmatic-personas-help-you-understand-your-end-user)
- [Indi Young — thinking styles](https://indiyoung.com/thinking-styles-research/); [UserInterviews interview](https://www.userinterviews.com/blog/thinking-styles-research-indi-young); [Andy Polaine retrospective](https://www.polaine.com/power-of-ten/indi-young-mental-models-and-thinking-styles/)
- [Stanford Legal Design Lab](https://law.stanford.edu/legal-design-lab/)
- [Gavel — Legal user design](https://www.gavel.io/resources/legal-user-design); [Adam Fard — IA for legal products](https://adamfard.com/blog/information-architecture-for-legal-product)
- [Jobya — A day in the life of an IP paralegal](https://jobya.com/library/roles/b4t6w0i9/ip_paralegal/articles/b4t6w0i9_day_in_life_ip_paralegal); [IP paralegal salary 2026 guide](https://www.paralegaledu.org/blog/intellectual-property-paralegal/); [ZipRecruiter — patent prosecution paralegal](https://www.ziprecruiter.com/Jobs/Patent-Prosecution-Paralegal)
- [Workstreet — security questionnaire stats](https://www.workstreet.com/blog/security-compliance-questionnaires); [Secureframe SOC 2 vs questionnaires](https://secureframe.com/blog/soc-2-vs-security-questionnaires)
- [Lexis+ Workrooms + customer-held keys (LawSites May 2026)](https://www.lawnext.com/2026/05/lexisnexis-expands-lexis-with-protege-adding-agentic-skills-collaboration-workrooms-and-customer-held-encryption-keys.html)
- [DeepIP — collaboration blog](https://www.deepip.ai/blog/office-action-response-collaboration); [DeepIP in Microsoft Word](https://www.deepip.ai/blog/davinci-your-trusted-ai-patent-drafting-tool-now-in-microsoft-word)
- [Patlytics 2026 OA guide](https://www.patlytics.ai/blog/2026-guide-modern-office-action-patent-prosecution); [Patlytics multitasking workspace](https://www.patlytics.ai/blog/a-smarter-multitasking-workspace-for-patent-prosecution)
- [IP Author — broken workflow blog](https://ipauthor.com/patent-prosecution-workflow-ai/)
- [TIPO English portal](https://www.tipo.gov.tw/en/) (deadline rules, deferred examination, IPC 2026.01); [Taiwan AI Basic Act (IAPP)](https://iapp.org/news/a/taiwan-s-strategic-leap-into-ai-enacting-the-ai-basic-act-to-foster-innovation-governance)
- [Stanford HAI — legal hallucination study](https://hai.stanford.edu/news/ai-trial-legal-models-hallucinate-1-out-6-or-more-benchmarking-queries)
- [Harvey design principles](https://www.harvey.ai/blog/how-we-approach-design-at-harvey); [Harvey getting started (⌘K)](https://help.harvey.ai/articles/getting-started-with-harvey)
- [ClaimMaster automation page](https://www.patentclaimmaster.com/automation.html); [ClaimMaster claim-tree blog](https://www.patentclaimmaster.com/blog/visualizing-claim-trees/); [USPTO ↔ track-changes conversion](https://www.patentclaimmaster.com/blog/tutorial-switch-between-uspto-formatting-and-track-changes/)
- [Lexology — TIPO Chinese translation of prior art](https://www.lexology.com/library/detail.aspx?g=c4d917e0-5eb2-4823-add9-e19097aee922)
- [ipnote.pro — Taiwan OA responding](https://ipnote.pro/taiwan/pt/services/patent-registration/patent-office-action-responding/)
- [TPIsoftware digiRunner Gartner Peer Insights](https://www.gartner.com/reviews/product/digirunner)
- [Patently-O job board](https://patentlyo.com/jobs)
- [Maze (card sort + unmoderated studies)](https://maze.co/)

---

*End of doc. ~5,300 words. Companion to UX_RESEARCH.md (competitor depth) and PRODUCT_STRATEGY.md (positioning). Authors of subsequent design specs should reference personas by name (e.g., "for 陳麗華's iPad review, the trust band must…") so the team builds a shared vocabulary.*
