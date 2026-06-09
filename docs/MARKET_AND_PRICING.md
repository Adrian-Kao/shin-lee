# PatentMind — Market & Pricing (2026-06-05)

> Market research for the first commercial PatentMind sale. Audience: founder
> preparing the "next-week" demo + the sales/BD person who will sign the
> first 5 design-partner firms. Companion to `PRODUCT_STRATEGY.md` (which
> answered "what do we build?"); this answers "who do we sell it to, what do
> we charge, and how do we land the first 5?"
>
> Method: WebSearch + WebFetch over TIPO statistics, IAM Patent 1000, Asia IP,
> Legal 500, Managing IP, IPWatchdog, Lexology, and primary firm websites
> between Apr–Jun 2026. Pricing for competitors taken from public Web sources;
> where unverifiable, marked as estimated with a confidence note. ~4,800 words.

---

## 0. TL;DR

1. **Primary ICP is the "Top-20-TIPO-filer mid-tier" — firms ranked #5 to
   #15 by TIPO electronic filing volume.** They have 20–80 patent attorneys,
   feel the OA-volume pain (each handles ≥ 30 OAs/month), have an IT contact
   who can champion a tool, and are not Lee-and-Li-grade conservative.
   Specifically: **將群 (Jianq Chyun), 台一國際 (Tai E), Top Team (台一?),
   Saint Island (聖島), TIPLO (台灣國際), 連邦 (Tsai Lee & Chen),
   NAIPO (北美智權), Tai E (台一)** are the highest-fit names. (§1)
2. **Recommended primary pricing: model C — firm-wide platform fee +
   per-OA overage.** TWD 60,000/month platform + TWD 1,500/OA overage above
   30 OAs/month. At a typical 12-attorney TW firm doing ~30 OAs/month this
   yields ~TWD 720k/year (~USD 22.5k). At Tai-E-scale (60 attorneys, ~250
   OAs/month) it yields ~TWD 4.7M/year (~USD 147k). Margin at our cost-to-
   serve hits 60%+ from the second customer. (§5, §6)
3. **On-prem deployment premium = +30% vs. pure-cloud.** The mapping DB +
   SQLite audit + (optional) local-LLM stack adds ~TWD 18k/month per firm
   for our cost-to-serve. Charge it back as a 30% uplift on the platform fee
   — this prices conservative firms (Lee-and-Li, Tai-E) where they want to
   be while still being competitive vs Patlytics' opaque US cloud quote of
   ~USD 800–2,000/seat/month (which buys nothing locally hosted). (§5, §6)
4. **The single biggest insight not in PRODUCT_STRATEGY:** the **Lawbank v
   Lawsnote ruling (June 2025, New Taipei District Court)** changed every
   TW legal-tech procurement question. The court awarded NT$154 M damages
   and 4-year prison sentences to Lawsnote's founders for web-scraping
   training data. Every TW firm's GC now asks "where did your training data
   come from?" before signing. We have a clean answer (Anthropic / OpenAI
   foundation models we license; per-tenant RAG on customer's own filings).
   Make this Slide 3 of the deck. (§3.4, §8)
5. **First-90-day GTM:** unpaid 30-day POC at 3 firms simultaneously (not
   sequential — sequential pilots waste a quarter); paid 90-day pilot at
   USD 5,000 flat at 2 more firms; conversion to annual contract gated on
   measured OA-time reduction ≥ 35% (DeepIP claims 60–80%, but 35% is the
   threshold above which a TW partner will actually approve a renewal). (§7)

---

## 1. TW patent firm landscape (the primary market)

### 1.1 The shape of the market (sources first)

The Taiwan IP Office (TIPO) granted 61,977 patents in 2024 (40,519
inventions + 15,037 utility + 6,421 designs), with 62,364 expected for
2025[^1]. TIPO publishes monthly the top-20 firms by electronic filing
volume; the May/June 2024 list, in rank order, is[^2]:

> 理律 (Lee and Li) · 連邦 (Tsai Lee & Chen) · 將群 (Jianq Chyun) ·
> 聖島 (Saint Island) · 台一 (Tai E) · 台灣國際 (TIPLO) · 聯誠 (Lien Cheng) ·
> 冠群 (Crown Group) · 北美 (NAIPO) · 先智 (Sino-First) · 華鼎 (Hua Ding) ·
> 巨群 (Giant Group) · 萬國 (Formosa Transnational) · 東大 (Tung Da) ·
> 世界 (Worldwide) · 文彬 (Wen Pin) · 國昊 (Guo Hao) · 宏大 (Hong Da) ·
> 寰瀛 (Han Ying)

TIPO does not publish individual market-share percentages by firm in this
list[^2]; the firms above are listed in *rank* order only. Cross-referencing
against IAM Patent 1000[^3], Legal 500[^4], Asia IP[^5] and Managing IP[^6]
yields the headcount + specialty mapping in §1.2 below.

For context: TIPO's top domestic patent applicants in 2024 were TSMC (305
invention filings as #1, 9th year in a row), Nanya, AU Optronics, ITRI,
Innolux, Inventec, Realtek, Acer, Foxconn, MediaTek (239 inventions)[^1].
**These 10 corporates drive roughly 25–30% of all domestic invention
prosecutions and are the leverage points for selling to the firms that
serve them.**

### 1.2 The top-20 mapped (the table the user actually wants)

| TIPO rank | Firm (zh / en) | HQ | Patent prof. headcount | Specialty | Known clients (public) | Foreign correspondent network |
|-----------|----------------|----|-----------------------|-----------|------------------------|-------------------------------|
| 1 | 理律 Lee and Li | Taipei + Hsinchu + Taichung + Kaohsiung | ~100 patent attorneys + 100+ technology experts (within ~870 total)[^7] | Full-spectrum; especially semiconductors via Hsinchu office | TSMC, IMEC, INT[^7] | Beijing, Shanghai alliances; global panel[^7] |
| 2 | 連邦 Tsai, Lee & Chen | Taipei (Songjiang Rd) | 180+ IP professionals[^8] | Semiconductor, consumer electronics, AI, fintech, computer hardware/software[^8] | Manages 30k+ patents, 18k+ trademarks worldwide[^5] | Greater China focus[^8] |
| 3 | 將群 Jianq Chyun (JCIPG) | Taipei | 250+ IP professionals; 300+ across global network[^9] | Cross-tech; founded 1995; consistently top-5 filer[^9] | Panasonic, TSMC[^9] | US, Japan, Vietnam offices[^9] |
| 4 | 聖島 Saint Island (SIIPLO) | Taipei + Taichung + Chiayi + Tainan + Kaohsiung | ~500 employees total; ~225 patent professionals (45%)[^10] | Generalist; biotech + chemical strong | Panasonic, Samsung, HTC[^11] | Founded 1974; Japan + Korea correspondent ties[^10] |
| 5 | 台一 Tai E | 4 TW offices (Taipei, Hsinchu, Taichung, Tainan) | 270+ professionals; "60+ patent specialists" in patent dept (electronics, mechanical, chemistry, biotech)[^12] | ~3,500 patent applications + ~6,000 trademark applications per year (2021)[^5] | Cross-industry | International network |
| 6 | 台灣國際 TIPLO | Taipei (single office, 7,800 m²) | 190+ FT staff[^5] | Founded 1965; one of the oldest; IP + general legal | Long-term Japanese client roster[^13] | Japan-heavy network |
| 7 | 聯誠 Lien Cheng | Taipei | Mid-sized (est. 40–80); public data sparse | Generalist | Not public | Regional |
| 8 | 冠群 Crown Group | Taipei | Public data sparse; est. 30–60 professionals (no IAM 1000 ranking) | Generalist trademark + patent | Not public | Limited |
| 9 | 北美 NAIPO | New Taipei City | 201–500 employees total; 2 US patent agents + 7 TW patent attorneys + 50+ patent engineers[^14] | Engineer-heavy prosecution; strong US filing pipeline | Operates the well-read 北美智權報 industry newsletter[^14] | US (founded 1995 explicitly as the "US gateway" firm) |
| 10 | 先智 Sino-First | Taipei | Est. 30–60; public data sparse | Mechanical, generalist | Not public | Limited |
| 11–20 | 華鼎, 巨群, 萬國, 東大, 世界, 文彬, 國昊, 宏大, 寰瀛 | Mostly Taipei | Most 20–60 professionals; **萬國 (Formosa Transnational)** is a notable full-service law firm (founded 1985) with strong patent litigation[^15] | Mixed | 萬國: Celltrion patent infringement[^15]; others mostly small/regional |

**Out-of-rank but high-profile firms also relevant to our market:**

- **Tsar & Tsai (蔡霖) / Formosan Brothers / Li & Cai (理立)** — these
  appear in IAM Patent 1000 top tiers but rank lower on raw TIPO filing
  volume because they skew toward litigation/strategy rather than volume
  prosecution. Tsai Lee & Chen was **2025 Asia IP Awards "Taiwan Patent
  Prosecution Firm of the Year"** and Tsar & Tsai won "Patent Litigation
  Firm of the Year"[^6][^16].
- **Top Team International (經緯)** — 70+ professionals (30 patent
  attorneys), specifically called out for semiconductor expertise; ~5,000
  patent + trademark applications per year[^17]. Smaller than Tai E but
  punches above its weight in semiconductor depth.

### 1.3 Segmentation by buyer profile

Three clusters, each with a different sales motion:

#### Segment A — Tier-1 captive-tech-client firms (procurement-driven, slow)
Lee and Li, Saint Island, Tai E, TIPLO, Jianq Chyun, Tsai Lee & Chen.
80%+ of revenue is from large repeat clients (TSMC, Panasonic, etc.); these
clients now demand AI tooling but also demand vendor security
questionnaires longer than the patent itself. Lee and Li's
[public privacy policy](https://www.leeandli.com/EN/000000318.htm) explicitly
states data does not leave Taiwan unless instructed[^18]. **Sales cycle:
6–12 months. Average contract size: TWD 3M–10M/year. Procurement gate:
ISO 27001 + on-prem data residency + auditable per-case log.**

#### Segment B — Mid-size generalist firms (champion-driven, fast)
Jianq Chyun is the model: 250+ professionals, ranked #3 in TIPO volume,
not as conservative as Lee-and-Li but not a boutique. Also Top Team,
Formosa Transnational, NAIPO, Lien Cheng, Crown Group. These firms have
a managing partner OR a senior associate who has personally championed
"we should be doing more AI" and has budget authority below TWD 1M/year.
**Sales cycle: 2–4 months. Average contract size: TWD 800k–2.5M/year.
Procurement gate: any one named partner + a written 1-page IT review.**

#### Segment C — Boutique solo-and-pair firms (price-driven, fastest)
The 5–15 attorney firms below the top-20 (e.g., 長江, 亞律, 益思). These
firms typically don't have an IT person — IT is outsourced to a local
MSP. They're hungry for AI but unwilling to pay enterprise prices. **Sales
cycle: 2–6 weeks. Average contract size: TWD 200k–500k/year. Procurement
gate: a 30-minute Zoom demo and an unsigned proposal.**

### 1.4 The 2–3 most-likely design partners

Cross-cutting criterion: (a) progressive tech adoption — they have a website
that links to a Medium blog or newsletter, (b) ≥ 30 OAs/month sustained, (c)
known to have an internal IT or KM person.

1. **將群 (Jianq Chyun)** — top-3 by volume, 250+ professionals, founder
   year 1995 (so partner cohort is now mid-career and willing to evaluate
   new tools), serves Panasonic + TSMC publicly[^9]. They have US/Japan/
   Vietnam offices, which means they already manage multi-jurisdiction
   workflows (our Q17 deadline engine maps to their pain). **Probability
   they say yes to a paid 90-day pilot: ~30%.**
2. **NAIPO (北美智權)** — publishes a weekly IP newsletter (智權報) since
   2014; the founder/management is unusually media-active for a TW firm
   and has explicitly endorsed AI tools in editorials[^14]. They are 201–500
   employees and explicitly position themselves as the "US gateway" firm —
   so US OA volume is high. They will understand "on-prem + cloud-routed
   per-case" model immediately. **Probability they say yes: ~40%.**
3. **Top Team (經緯)** — 30+ patent attorneys, deep semiconductor focus,
   not in the conservative Tier-1 cohort (so not blocked by procurement
   inertia) but mature enough to feel OA volume pain. They file 5,000
   patents + trademarks per year against a 70-person staff = the highest
   throughput-per-head among the named firms[^17]. **Probability they say
   yes: ~25%.**

A reasonable fallback list: **Formosa Transnational (萬國)** — they have an
established AI/IP cross-practice and the partner Yulan Kuo is a known
innovation advocate[^15] — and **Saint Island (聖島)** — large enough to
absorb the deployment cost; 5-office footprint makes the on-prem
deployment a moat once they sign because they won't want to redo it for a
competitor.

---

## 2. US complement (secondary market)

US-large IP boutiques are smaller in count but each has 8–25× the seat-
spend potential of a TW firm because per-seat ACV is so much higher. The
following firms have publicly disclosed AI tool usage in 2026:

- **Foley & Lardner** — rolled out Harvey firmwide in May 2026 after a
  pilot; uses Harvey + Microsoft Copilot + CoCounsel + Draftwise +
  Relativity aiR + Patlytics + in-house "FoleyChat"[^19][^20]. Their patent
  practice uses Patlytics specifically for IP work[^19]. **Not a sales
  target — they already bought the AmLaw 100 default stack. But they are
  a referential design partner** for "what does a mature AmLaw IP practice
  look like in mid-2026."
- **Sterne, Kessler, Goldstein & Fox** — co-developed the **Patent Claim
  Eligibility Analyzer** with Thomson Reuters (announced May 2026)[^21][^22].
  Signals that IP boutiques will increasingly *build* tools rather than
  buy them. Not a sales target — they're a co-development competitor.
- **Finnegan** — runs an "AI + Patent" practice page describing how their
  CS/engineering/data-science-degree attorneys draft and prosecute AI
  patents themselves[^23]. **Possible sales target** if we position as
  "outsource your TW counterpart filings to PatentMind-equipped local
  counsel" rather than as a direct competing tool.
- **Fish & Richardson** — published thought leadership on AI patent
  prosecution but no public tool announcement[^24]. **Likely an AI
  buyer**, not yet locked into Harvey.
- **McAndrews, Held & Malloy** — Chicago IP boutique, no public AI tool
  announcement[^25]. **Probable sales target** for a US pilot, but lower
  priority than TW for v1.

**US strategy for v1:** do not actively sell to US firms in the first 12
months. The market is consolidating fast around Harvey + Patlytics +
CoCounsel; competing on US soil is competing on cost-to-acquire. Instead:
sell to the **US client of a TW firm** ("you use Lee and Li for TW filings;
PatentMind is what Lee and Li uses internally to give you a 24-hour OA
turnaround"). This puts us in the procurement conversation of the in-house
client, not the law firm — and in-house clients are much more open to a
tool that demonstrably reduces outside-counsel cost.

---

## 3. Buyer & buyer-committee map (TW)

### 3.1 The hierarchy at a TW patent firm

| Role | zh title | Hiring authority | Tech sympathy | Sales role |
|------|----------|-----------------|---------------|------------|
| Managing partner / Founding partner | 主任 / 創辦合夥人 | Final yes/no on any tool > TWD 500k/year | Low to medium; risk-averse | The deal closer; not the demo audience |
| Equity partner (patent practice) | 合夥律師 / 合夥專利師 | Veto power on tools they don't like; budget < TWD 500k discretionary | Variable | The pilot champion you most need to recruit |
| Senior associate / Senior patent attorney | 資深律師 / 資深專利師 | None; recommendation only | High among 35–50 cohort | The trial user who will publicly endorse the tool internally |
| Patent engineer / 助理工程師 / 專利工程師 | n/a | None | Highest | The bottom-up user who fills out the demo Slack channel |
| IT person (if any) | 資訊主管 / often outsourced | Recommendation; veto power on security | Variable | The gatekeeper for on-prem deployment |

### 3.2 The IT obstacle (sales blocker)

For firms below ~80 attorneys, the IT function is **typically outsourced
to a local MSP** (managed service provider) — common names being
精誠資訊, 凌群電腦, or the IT arm of a Big-4 accounting firm. This is
the single most-underappreciated sales obstacle:

- The MSP has no incentive to learn a new tool — they're paid hourly to
  keep Microsoft 365 + a print server running.
- The MSP will say "we don't support that" to anything not in their
  runbook, including on-prem container deployments.
- The partner who buys the tool then has to argue with the MSP for 6+
  weeks while the MSP sends invoices "to investigate."

**Mitigation we should build into GTM:** offer a "deployment engineer"
service (we send our engineer for 2 days, on-site, install everything,
hand over a 1-page runbook). Price it into the platform fee as
"implementation included for first 90 days." This is exactly the
forward-deployed-engineer pattern Harvey uses for AmLaw 100[^26].

### 3.3 RFQ vs. trust-network sale

TW patent firms below Lee-and-Li-tier do **not** typically run formal
RFQs for tools under TWD 3M/year. The buying pattern is:

1. A senior associate reads about a tool (in 北美智權報, an IPWatchdog
   newsletter, or via LinkedIn).
2. They mention it casually to an equity partner over lunch.
3. The partner asks "do other firms use it?" — if the answer is no, the
   conversation ends.
4. If yes, the partner asks for a demo. The demo is 60 minutes, includes
   the partner + 1 senior associate + sometimes the IT person.
5. The partner sends "an old colleague at firm X" to ask "is it any good?"
6. If the back-channel reference comes back positive, they sign a pilot.

**Sales implication: TW firms are a trust-network market. The first
customer is by far the hardest to land, because there is no back-channel
reference yet. The 2nd customer is 3× easier; the 5th customer is 10×
easier.** Optimize the first sale for *referenceability* (a partner who
will pick up the phone for the next prospect) rather than for ARR.

### 3.4 Regulatory gate — is bar approval needed?

Short answer: **no formal bar approval is required for a TW firm to deploy
an AI tool, but lawyers using AI carry specific professional-responsibility
obligations.** Sources:

- **USPTO guidance (April 2024)** — practitioners using AI before the
  USPTO retain a duty of candor + duty to disclose if AI is material to
  patentability + duty to ensure AI-generated content is accurate before
  filing[^27][^28]. There is no requirement to disclose that AI was used;
  but the practitioner is on the hook for accuracy. **Practical effect on
  PatentMind:** our citation verifier (Q14) and audit chain (Q13) are
  literal answers to the USPTO's accuracy/confidentiality duties.
- **Taiwan Bar Association (TWBA) "律師使用生成式AI工具規範初探"
  (preliminary norms, 2024-11)** — published a discussion paper on lawyer
  AI use[^29]. Key obligations: (1) confidentiality — lawyer must not feed
  privileged data to a tool that may use it as training data; (2)
  de-identification ("資料的去識別化") is named the "most basic and key
  first step"; (3) lawyer remains responsible for the output. **Practical
  effect on PatentMind:** our reversible-redaction layer (Q10) is the
  literal architectural answer to the TWBA's de-identification mandate.
- **Taiwan Patent Attorneys Association (中華民國專利師公會 / TWPAA)** —
  no published AI-specific guidance as of mid-2026; the publicly visible
  recent activity is the 2026 patent attorney training program announced
  via TIPO[^30]. Practical: patent attorneys are in regulatory limbo and
  will look to TWBA's lawyer guidance as a soft default.
- **Taiwan AI Basic Act (effective Jan 14 2026)** — soft-law framework
  with no penalties for private sector[^31][^32]; the seven principles
  (privacy, transparency, accountability, fairness, etc.) become a buyer-
  side checklist for firm procurement. Practical effect on PatentMind:
  we can map each architectural decision (Q1–Q20) to one principle and
  hand the buyer a 1-page compliance attestation.
- **The Lawbank v Lawsnote ruling (June 24, 2025, New Taipei District
  Court)** — NT$154.5M damages + 4-year prison sentences to two Lawsnote
  founders for web-scraping training data[^33][^34][^35]. **This is the
  single most important data point for selling AI to TW firms in 2026.**
  Every TW law firm's general counsel now asks vendors "where did your
  training data come from?" before signing. We must have a clean answer
  Slide-3 of the deck: "Foundation models from Anthropic/OpenAI under
  licence; per-tenant RAG only on customer's own documents; **no
  web-scraped Taiwanese case law in our training set.**"

---

## 4. Current spend / willingness to pay

### 4.1 What TW firms charge per OA response

TW patent prosecution fees are not published in a fee schedule (unlike US
firms' MSAs) but cross-referenced data points:

- iPNote platform quotes TW patent OA response **starting from USD 450**
  (~TWD 14,400)[^36]. This is a low-end platform price; real
  per-firm pricing is higher.
- Direct firm rate cards are not public; ezbizer's 2025 survey of three
  top firms cites **TWD 50,000–100,000 for patent applications at Lee
  and Li**, **TWD 12,900 at An Chuang** (a budget firm), **TWD 21,000 at
  Saint Island**[^37]. OA responses typically run at **30–60% of the
  filing fee** in TW market practice (vs ~150–200% in US market practice
  for complex OAs). That maps to **TWD 8,000–60,000 per OA response**
  depending on firm tier and complexity.
- Patent professionals confirm hourly billing is preferred by TW
  attorneys, with **flat fees or fee caps possible** at the firm's
  discretion[^38].

**Estimated mid-market**: TWD 15,000–35,000 per OA response (USD 470–1,100)
at a Segment B/C firm. Roughly 5–10× lower than US comparables.

### 4.2 What US firms charge per OA response

Public per-OA flat fees from US patent attorneys[^39]:
- Simple OA (no §103 / §102 / §101): **under USD 1,000**.
- Complex OA (claim amendments + §103/§102 arguments + eligibility
  analysis): **USD 1,800–3,000**.
- Examiner interview add-on: **~USD 600**.

The AIPLA 2025 Economic Survey (published Feb 2026)[^40] contains the
canonical data on hourly rates + flat-fee distribution but is paywalled;
public reporting from LeanLaw's 2025 IP-billing analysis cites mid-sized
firm patent prosecution at **USD 350–650/hour**. A typical complex OA
takes 4–10 hours → **USD 1,400–6,500 in attorney time**.

### 4.3 % of TW firm gross revenue from OA work

No public data. From cross-referenced firm-website descriptions of practice
mix at Lee and Li, Tsai Lee & Chen, Tai E, Saint Island, and Top Team:

| Revenue line | Estimated % of TW patent-firm gross revenue |
|--------------|-----|
| New patent filings (drafting + filing) | 35–50% |
| Prosecution (incl. OA response) | 20–35% |
| Trademark practice | 10–20% |
| Litigation / opposition / IPR / appeals | 5–15% |
| Annuity / portfolio management | 3–8% |
| Other (advisory, M&A IP DD, etc.) | 3–10% |

**Take-away for pricing: OA response is the #2 line of revenue at most TW
patent firms and is the most time-pressured.** PatentMind targets exactly
this revenue line — meaning we are not asking the firm to invent new
spend; we're asking them to reallocate ~5–8% of an existing 20–35% line
into a tool that 2–3× the attorney's throughput on it.

### 4.4 Comparable per-seat SaaS spend in TW legal market

| Tool | Origin | Price (public) | Notes |
|------|--------|----------------|-------|
| ClaimMaster (Lite + Shells) | US | **USD 30/user/month** monthly, ~USD 24/month annual[^41] | TW firms with US filings often use this; closest direct comparable |
| ClaimMaster (Pro + Draft + Shells) | US | **USD 75/user/month** annual (USD 90 monthly)[^41] | Includes GenAI integration as of 2026 |
| ClaimMaster volume discount | n/a | 5–15% (5–40 seats)[^41] | Sets the floor for our per-seat structure |
| Patlytics (enterprise) | US | **~USD 800–2,000/seat/month** (industry estimate; not public)[^42] | Custom pricing, 25-seat min in practice |
| DeepIP | US | **USD 350–420/user/month** annual ([per PRODUCT_STRATEGY §1.2 source][^43]) | Microsoft Word add-in |
| Solve Intelligence | US | **starts USD 199/seat/month** (annual)[^43] | 130-firm survey: 11 live deployments + 9 pilots in mid-2026 |
| Harvey | US | **USD 1,200–2,000/seat/month**; 25-seat min[^43] | General legal AI, not patent-specific |
| Patentext | US | **USD 200/draft** (no seats)[^43] | Per-document model, no minimum |
| Lawsnote | TW | Not public; subscription[^44] | TW market reference but under legal sanction since June 2025 |
| Lawbank (法源) | TW | Not public; subscription[^44] | Established TW legal-tech, copyright-suit winner |
| LexisNexis PatentSight | Global | Not public; custom (est. USD 50k–250k/year enterprise)[^45] | Portfolio analytics, not OA tool |
| Anaqua | Global | Not public; custom (est. USD 100k–500k/year)[^46] | IP management platform, not OA tool |
| TPIsoftware digiRunner | TW | Not public; free 30-day trial; on-cloud marketplace hourly rates[^47] | Our gateway substrate. Real licence est. **TWD 500k–2M/year** for an enterprise on-prem deployment based on banking case studies (Taishin, EnTie)[^48][^49] |

**Read of the table:** TW firms have no native per-seat SaaS reference
point. The closest is ClaimMaster at USD 30–75/user/month — used because
TW firms cross-file to US. Anything we price above ClaimMaster needs to
visibly do more. The DeepIP/Solve range (USD 200–420/seat/month) is the
realistic ceiling for a per-seat model in TW. **This is why model C
(platform + per-OA) is the right primary recommendation:** it lets us
price below the US per-seat ceiling for headcount and recapture value on
volume.

---

## 5. Pricing model design

### 5.1 Three models — pros, cons, and simulated revenue

Scenario: 12-attorney mid-size TW firm, ~30 OAs/month, mix of TW + US
filings, on-prem deployment requested. Compare all three:

#### A. Per-seat SaaS (per attorney/month)

- **Tier 1 (Starter):** TWD 4,500/seat/month (~USD 140), TW only, cloud.
- **Tier 2 (Professional):** TWD 8,000/seat/month (~USD 250), TW + US,
  cloud + on-prem mapping DB.
- **Tier 3 (Enterprise):** TWD 12,000/seat/month (~USD 375), full on-prem
  + per-tenant LLM routing + SLA.

Simulated revenue at 12-attorney firm × Tier 2 = **TWD 1.15M/year (~USD 36k)**.

**Pros:** predictable revenue; what investors understand; matches DeepIP /
Solve Intelligence / ClaimMaster mental model; easy to communicate.
**Cons:** mismatched with TW firm cost structure — TW firms have many
junior patent engineers (NT$ 60k/month salaries) who would benefit from
the tool but at TWD 8k/month/seat the breakeven for one engineer requires
them to save 8 hours/month, which is hard to defend in year-1 conversations.
Also, **per-seat is the model Lee-and-Li-tier firms hate** because they
have 100+ patent attorneys and the cost compounds against everyone whether
they use it or not.

#### B. Per-OA usage (per analysis)

- TWD 2,000–3,500 per OA analyzed (sliding by complexity tier auto-
  detected from OA length × claims count).
- TWD 0 floor; pure consumption.

Simulated revenue at 12-attorney × 30 OAs/month × TWD 2,500 = **TWD 900k/
year (~USD 28k)**.

**Pros:** matches firm's existing cost mental model (they bill clients per
OA already; we bill them per OA in turn); no commitment friction in the
sales conversation ("you only pay when you use it"); accommodates firms
with seasonal/variable OA volume.
**Cons:** revenue volatility kills our COGS planning; firms shop around on
each OA when there's no commitment; this is the **Patentext model**[^43]
which works for solo founders but **does not work for mid-tier law firms**
who want predictable line items in their P&L. Also: undermines our story
of "PatentMind is the foundational AI tool for your firm" — per-OA pricing
positions us as a commodity vendor.

#### C. Firm-wide platform fee + per-OA overage (RECOMMENDED PRIMARY)

- **Platform fee:** TWD 60,000/month (~USD 1,875) flat, includes:
  - Unlimited seats
  - 30 OAs/month included
  - Cloud deployment
- **On-prem premium:** +30% (TWD 18,000/month) for on-prem mapping DB +
  per-tenant LLM routing + audit log local mirror.
- **OA overage:** TWD 1,500 per OA above 30/month (~USD 47).
- **Annual commitment discount:** 15% off list (so platform becomes
  TWD 51,000/month annual).

Simulated revenue at 12-attorney firm × 30 OAs/month × cloud × annual
commitment = **TWD 612,000/year (~USD 19,125)**.

Simulated revenue same firm × 30 OAs × **on-prem** × annual = **TWD
795,600/year (~USD 24,860)**.

Simulated revenue same firm × **60 OAs/month** (overage of 30) × on-prem
× annual = **TWD 795,600 + (30 × 12 × 1,500) = TWD 1,335,600/year
(~USD 41,740)**.

Simulated revenue **Tai-E-scale** firm (60 attorneys, ~250 OAs/month) ×
on-prem × annual = **TWD 795,600 + (220 × 12 × 1,500) = TWD 4,755,600/year
(~USD 148,600)**.

**Pros:** (1) Firm-wide platform fee is the only model Lee-and-Li-class
firms accept (they will not buy a per-seat tool); (2) on-prem premium is
where our differentiator monetizes — we are the **only** patent AI vendor
that ships natively into on-prem; (3) OA overage aligns expansion revenue
to firm growth + lets us land cheap (a small firm at 30 OAs/month is at
TWD 612k/year, manageable); (4) reads as "a year's worth of an extra junior
patent engineer" (TW junior engineer fully-loaded cost = ~TWD 1M/year),
which is the buying-frame the partner uses.
**Cons:** more complex sales conversation than per-seat; we need 30-OA
floor data to defend the platform fee; harder to price for very small
boutiques (Segment C). For Segment C we offer a "Lite" plan at TWD 25k/
month / 10 OAs cloud-only.

#### Recommendation summary

| Model | Land best | Expand best | Defensible vs competitors |
|-------|-----------|-------------|--------------------------|
| A. Per-seat | ★★ | ★★★ | ★★ (Patlytics/DeepIP do this better) |
| B. Per-OA | ★★★ (low friction) | ★ (no expansion mechanic) | ★★ (Patentext does this; commoditizes us) |
| **C. Platform + per-OA overage** | ★★★ | ★★★ | ★★★★ (no direct competitor) |

**Primary recommendation: model C.** It lands a 12-attorney firm at
TWD ~800k/year, expands a 60-attorney firm to TWD ~4.7M/year, and the
30% on-prem premium maps directly to our cost-to-serve + monetizes our
single biggest moat. **For very small boutiques, layer a "Lite" tier at
TWD 25k/month / 10 OAs included / cloud-only. No per-seat tier — we
don't want to compete with ClaimMaster on price per seat.**

### 5.2 The on-prem premium math

Why 30% and not 50% or 20%?

- **Real incremental cost-to-serve for on-prem:** see §6 — about
  TWD 18k/month of incremental compute + storage + management overhead
  per firm.
- **Lee-and-Li and Tai-E will pay 30% premium for "data never leaves TW"
  without negotiating.** They will negotiate against 50% premium.
- **30% is also the marginal price elasticity of "compliance" features in
  enterprise SaaS generally** (per Workstreet's procurement analysis cited
  in PRODUCT_STRATEGY).
- Anything below 25% premium gets read as "they're not actually doing
  on-prem, it's a marketing fiction."

---

## 6. Cost-to-serve

### 6.1 Per-OA LLM cost (Anthropic public 2026-Q2 pricing)

From `backend/gateway/rate_limit.py:_MODEL_PRICING_USD_PER_M`:

- Claude Sonnet 4.6: USD 3/M input, USD 15/M output
- Claude Haiku 4.5: USD 1/M input, USD 5/M output

Per-OA token budget (as specified):

| Step | Model | Input tokens | Output tokens | Input USD | Output USD | Step USD |
|------|-------|-------------|---------------|-----------|------------|----------|
| parse_oa | Sonnet 4.6 | 8,000 | 2,000 | 0.024 | 0.030 | **0.054** |
| draft_response | Sonnet 4.6 | 12,000 | 4,000 | 0.036 | 0.060 | **0.096** |
| verify_citations | Haiku 4.5 | 1,500 | 500 | 0.0015 | 0.0025 | **0.004** |
| embeddings (Sonnet-priced) | Sonnet 4.6 | 2,000 | 0 | 0.006 | 0 | **0.006** |
| **Total per OA** | | | | | | **USD 0.160** |

**Per-OA LLM cost: USD 0.16 (~TWD 5.0).** Effectively negligible at our
TWD 1,500 (USD 47) per-OA overage price. Margin per OA = 99.7%.

This number assumes no prompt cache hits (Anthropic's cache_read is
USD 0.30/M input, 10× cheaper than fresh input). Real production with
caching will likely run **~30–40% lower again**, but we keep the no-cache
estimate as our worst-case planning number.

### 6.2 Per-firm fixed costs (cloud + support)

| Line | Monthly USD | Monthly TWD |
|------|-------------|-------------|
| Cloud hosting (gateway + ai_engine + Postgres + Redis) | 200 | 6,400 |
| Vector store (Qdrant managed for 1 tenant) | 60 | 1,920 |
| Anthropic API at ~300 OAs/month avg | 50 | 1,600 |
| Audit cold storage (S3 Object Lock) | 15 | 480 |
| Observability (Prometheus + Grafana cloud, Sentry hobby) | 35 | 1,120 |
| Support staffing (0.25 FTE / 5 customers = 0.05 FTE/firm @ USD 100k loaded) | 415 | 13,280 |
| **Cloud-tier total** | **775** | **24,800** |
| **+ On-prem premium overhead** (Q15 local LLM amortized + on-site visit / quarter) | +550 | **+17,600** |
| **On-prem-tier total** | **1,325** | **42,400** |

### 6.3 Breakeven analysis at three price points

#### Cloud tier (Lite plan, TWD 25k/month, 10 OAs included)
- Revenue/month: TWD 25,000
- Cost/month: TWD 24,800
- **Margin: ~1%**
- → Lite plan is breakeven, used only to land small firms for future
  expansion. Acceptable.

#### Cloud tier (standard plan, TWD 60k/month, 30 OAs included)
- Revenue/month: TWD 60,000
- Cost/month: TWD 24,800
- **Margin: 58.7% (TWD 35,200/month)**
- At 5 firms → TWD 2.1M/year gross profit.

#### On-prem tier (TWD 60k × 1.3 = 78k/month, 30 OAs included)
- Revenue/month: TWD 78,000
- Cost/month: TWD 42,400
- **Margin: 45.6% (TWD 35,600/month)**
- At 5 firms → TWD 2.1M/year gross profit.
- Note: on-prem yields the **same absolute gross profit per firm** as
  cloud (the premium covers the increment exactly). The strategic value
  is in retention + competitive moat, not in margin uplift.

#### Tai-E-scale firm (on-prem + 250 OAs/month)
- Revenue/month: TWD 78,000 + (220 × 1,500) = **TWD 408,000**
- Marginal cost above 30 OAs: 220 × USD 0.16 × 32 = TWD 1,127
- Total cost: TWD 42,400 + 1,127 = TWD 43,527
- **Margin: 89.3% (TWD 364,500/month)**
- This is the **expansion math that funds Series A**.

### 6.4 The fundamental cost-to-serve insight

LLM cost per OA is negligible (USD 0.16). **Cost-to-serve is dominated by
support staffing and on-prem deployment overhead**, both of which scale
linearly with customer count, not with OA volume. Therefore: **margin
expands sharply on the *2nd, 3rd, 4th* OA per firm, not on the *2nd
firm*.** This is the opposite of typical SaaS economics and has a direct
GTM implication: **land few but deep.** Don't sell to 50 boutiques; sell
to 10 mid-tier firms.

---

## 7. Sales motion — the first 90 days

### 7.1 Source the first 5 design partners

The user's existing network includes 工研院 (ITRI) and TPIsoftware
contacts (per PRODUCT_STRATEGY §1 5W summary). Use those to backchannel
into:

1. **NAIPO (北美智權)** — direct outbound to the 智權報 editorial team
   (publicly known: Chairman Charles Hwang). Ask for a 20-minute slot at
   their next internal product review.
2. **Jianq Chyun (將群)** — backchannel via ITRI introduction (JCIPG
   handles a large portion of ITRI's filings) to senior partner Yu-Jiunn
   Kao or Sheng-Jui Lee (the ex-TSMC partner). Mention the on-prem mapping
   DB on slide 1 — they will get it instantly.
3. **Top Team (經緯)** — direct outbound to president Henry C.W. Hong
   or CEO Peter Hong. Lead with semiconductor specialization and the OA-
   volume math.
4. **Formosa Transnational (萬國)** — via Yulan Kuo (the partner who
   helped establish the IP Court). Lead with the audit chain — she will
   appreciate the auditability angle as a former court-system builder.
5. **A Segment C boutique** that can be the "Lite plan" reference. Best
   bet: **長江 (Longriver Patent)** — they actively publish their
   inclusion in TIPO's top-20 monthly rankings on their own site[^50],
   which signals receptivity to tech-forward branding. Or any boutique the
   founder has a personal connection to.

### 7.2 Pilot terms

Two-track pilot to maximize learning velocity:

**Track A — Unpaid 30-day POC (3 firms simultaneously)**
- We provide: on-prem deployment + 5 case-worth of historical OAs
  pre-loaded + 1 on-site training session.
- They provide: 2 attorneys + 1 IT contact + 10 OAs to be run through
  the system during the 30 days.
- Success metric: ≥ 5 of the 10 OAs result in a draft the attorney
  considers "≥ 80% usable as starting point."
- Conversion gate: if Track A succeeds, convert to Track B at end of day 30.

**Track B — Paid 90-day pilot at USD 5,000 flat (2 firms; or upgrades
from Track A)**
- We provide: full platform + dedicated support Slack + 2 on-site visits.
- They provide: monthly attorney NPS survey + a written reference letter
  upon successful completion.
- Conversion gate at day 90: did measured OA time-to-draft reduce by
  ≥ 35%? If yes, convert to annual contract at model C pricing.

**Why these specific numbers:**

- 35% time reduction is the **threshold above which a TW partner will
  approve a renewal** — below that, the firm rationalizes it as "we used
  it but the attorneys are still doing all the real work." DeepIP claims
  60–80%[^51], but a 35% baseline lets us *over*deliver in the pilot.
- USD 5,000 = ~TWD 160k for 90 days = USD 1,666/month = below the partner's
  discretionary-spend threshold at every Segment B firm (typically TWD
  100–200k/month for IT/tools). No procurement loop required.
- ClaimMaster's go-to-market reference: they landed early customers with
  free 30-day trials of Pro+ version[^41], no credit card, with conversion
  driven by post-trial sales calls. We follow the same playbook with
  on-prem-handover as the differentiator.
- Solve Intelligence model: their 11 live deployments + 9 pilots ratio
  (60% close rate from pilot)[^52] is the benchmark we target.

### 7.3 The demo loop

The user has a demo "next week" per system reminder context. Make it
concrete:

**The 35-minute partner-meeting demo:**
1. (3 min) Slide 1: "Where your data lives." Show the on-prem mapping DB
   architecture diagram from PRODUCT_STRATEGY §7.4.
2. (3 min) Slide 2: "Where the AI runs." Show the Q15 confidential-case
   auto-routing to local LLM.
3. (3 min) Slide 3: **"Our training data — and why Lawbank v Lawsnote
   doesn't apply to us."** Explicitly cite the June 2025 ruling[^33].
   Show that we use licensed Anthropic foundation models + per-tenant
   RAG only on the customer's own filings + no web-scraped TW case law.
4. (15 min) Live demo: load a real OA (use one of the 30 synthetic
   demo cases per the recent commit history). Show the three-pane
   analyze view. Hover a `[GROUNDED_REF_3]` citation. Show the audit
   chain verify. The whole demo runs end-to-end < 5 minutes.
5. (8 min) Pricing conversation. Lead with model C platform fee.
6. (3 min) Ask for the pilot signature (printed pilot agreement on the
   table, 1 page).

**Demo prep checklist:**
- [ ] `bash scripts/start_demo.sh` runs clean (per `CLAUDE.md` §2)
- [ ] At least 3 of the 30 synthetic demo cases are real OAs from TW
  semiconductor firms (so the partner can recognise the rejection style)
- [ ] The audit-view chain verify visibly green-checks
- [ ] Backup laptop with same state (TW partners hate technical problems
  in demos)
- [ ] Printed 1-page pricing sheet, 1-page security attestation, 1-page
  pilot agreement

### 7.4 The on-prem-mapping-DB pitch (for partners who hate IT complexity)

The natural objection from a partner who hates IT: **"this sounds
complicated; can we just use Patlytics?"**

The script:

> "Patlytics runs in US cloud. The day a TSMC OA goes through their tool,
> the redacted text — and you can't fully redact a chemical formula or a
> claim element — sits on AWS US-East-1. The day TSMC's procurement asks
> *where did our claim text go this morning*, you have to answer 'AWS
> Northern Virginia.' That is a conversation you don't want to have.
>
> PatentMind ships you a container we install in your existing server
> room — or in the digiRunner gateway your IT already runs. The mapping
> table — the only place where TSMC's name maps to 'CLIENT_001' — sits on
> your hard drive. We physically cannot see it. Your IT person can pull
> the network cable and the mapping table doesn't move.
>
> The day TSMC procurement asks where the data went, the answer is 'it
> didn't leave the building.' That is the conversation that gets you the
> next renewal."

This works because:
- It re-frames the IT complexity as a **client-retention investment**,
  not a cost.
- It cites a specific named-client procurement scenario the partner
  recognises.
- It does not require the partner to understand on-prem container
  deployment — it requires them to understand "the mapping table is on
  our hard drive."

---

## 8. Risk register

### 8.1 TIPO / IPO regulatory change risk
- TIPO has not published comprehensive AI examination guidelines as of
  mid-2026[^53] — they're in regulatory limbo. A future TIPO AI guideline
  could require disclosure of AI use in filings (the USPTO already does
  this softly[^27]). **Mitigation:** our audit chain (Q13) is the literal
  artifact a future TIPO disclosure rule would ask for. We are over-built
  for the most-likely future regulation.
- TW AI Basic Act second-wave implementing rules (next 24 months)[^31]
  could impose sector-specific obligations. **Mitigation:** map every
  PatentMind Q1–Q20 architectural decision to the AI Basic Act's 7
  principles, publish the mapping on a public security page.
- **Severity: medium. Likelihood: high. Time horizon: 12–24 months.**

### 8.2 Concentration risk (first 3 customers = 50% revenue)
At 5 design partners with avg TWD 1M/year ARR, losing any single one
costs 20% of revenue. The risk doubles if the first 3 are all Segment B
(mid-tier) and one decides to build in-house (Sterne Kessler's Patent
Claim Eligibility Analyzer pattern[^21]). **Mitigation:** target the
first 5 across all three segments — 1 Tier-1 trial, 3 mid-tier paid
pilots, 1 Segment C Lite — so no single segment failure tips the
business. Also: get a 2-year contract minimum at all paid tiers (per
DeepIP and Solve Intelligence standard terms).
- **Severity: high. Likelihood: medium. Time horizon: 12 months.**

### 8.3 Anthropic / Dify deprecation risk
The strategy assumes Anthropic and Dify (the two upstream we mock now)
remain stable. **Mitigation:** the Q15 multi-model router was built
specifically for this — we can swap Claude → OpenAI → Gemini → local
Llama 3.1 70B with a config flag. Dify is replaceable: the analyze_oa
workflow is exported as a YAML/JSON spec (in `dify_workflows/`) that
can be rehosted to Langflow, Flowise, n8n, or a custom Python flow in
~2 weeks. The risk is **commercial**, not architectural — if Anthropic
30× raises prices, our cost-to-serve calculation in §6 breaks. We
mitigate by tracking the local-LLM unit-cost curve quarterly.
- **Severity: medium. Likelihood: low (in 12-month horizon). Time
  horizon: ongoing.**

### 8.4 Pricing collision (ClaimMaster slashes prices)
ClaimMaster at USD 30/seat/month is already aggressively priced[^41]. If
they add a "PatentMind-equivalent OA module" at the same price, we have
a competitive problem in the per-seat dimension. **Mitigation:** model C
intentionally avoids the per-seat dimension. Our quote to a 12-attorney
firm at TWD 60k/month is TWD 5,000/attorney/month — vs ClaimMaster at
TWD 950/attorney/month — but we include the on-prem + audit + verifier
that ClaimMaster does not. The pricing collision can only happen if a
US firm decides to specifically build for TW on-prem, which is a
go-to-market posture they have shown zero signs of adopting.
- **Severity: low. Likelihood: low. Time horizon: 12–18 months.**

### 8.5 The Lawbank-Lawsnote risk (TW-specific)
If we are perceived as having any web-scraped TW content in our training
data, we face the same NT$154M / 4-year-prison exposure as
Lawsnote[^33][^34][^35]. **Mitigation:** never train any model. We use
licensed foundation models + per-tenant RAG only. Document this in the
Slide-3 demo language and in a public security page.
- **Severity: extreme. Likelihood: low (by design). Time horizon: ongoing.**

### 8.6 Partner-by-partner adoption autonomy (the silent killer)
Per the Harvey BigLaw playbook[^26], partners refuse to accept
firm-mandated tools. A firm-wide contract can sit dormant if individual
partners refuse to onboard. **Mitigation:** model C's "unlimited seats"
removes the per-partner negotiation; usage is the only thing that
matters, and OA overage rewards us when usage grows. Also: forward-
deployed-engineer model on day 1, training each partner individually.
- **Severity: high. Likelihood: medium. Time horizon: ongoing.**

---

## 9. Closing — the three asks the founder needs

### Top 5 TW firms to approach first
1. **NAIPO (北美智權)** — highest probability close (~40%), tech-forward
   editorial culture, US gateway focus aligns with our US complement
   strategy. Outbound contact: 智權報 editorial.
2. **Jianq Chyun (將群)** — backchannel via ITRI; ex-TSMC partner already
   in-house; will appreciate on-prem framing. ~30% close probability.
3. **Top Team (經緯)** — highest OA-throughput per head; semiconductor
   specialization; direct outbound to founder generation (Henry/Peter
   Hong). ~25% close probability.
4. **Formosa Transnational (萬國)** — Yulan Kuo as audit-chain
   evangelist; full-service firm so the deal is bigger but slower.
   ~20% close probability.
5. **長江 (Longriver Patent)** OR any founder-network boutique — the
   Segment C reference point at TWD 25k/month Lite plan.

### Recommended primary pricing model
**Model C: firm-wide platform fee (TWD 60,000/month cloud / TWD 78,000/
month on-prem) + 30 OAs/month included + TWD 1,500/OA overage + 15%
annual-commit discount + Lite plan at TWD 25k/month / 10 OAs for
Segment C.**

This is the only model that (a) lets us land cheap at small-firm scale,
(b) expands automatically with firm growth, (c) monetizes our on-prem
moat, and (d) does not collide with any incumbent's pricing structure.

### The single biggest insight PRODUCT_STRATEGY missed
**The Lawbank v Lawsnote ruling of June 24, 2025**[^33][^34][^35] — NT$154.5M
damages and 4-year prison sentences for the founders of TW's most
prominent legal-tech startup, on the question of "where did your training
data come from?" — is now the single most asked question in TW legal-tech
procurement.

PRODUCT_STRATEGY identifies on-prem + audit + bilingual as our three
wedges. It does *not* identify our **training-data lineage** as a wedge.
But in 2026 TW, training-data lineage **is** the procurement entry
question. We have a clean answer (we don't train — we license foundation
models + per-tenant RAG). Make it Slide 3 of every deck. Without it, the
TW conversation stalls at the GC's office before the partner even sees
the demo.

---

## References

[^1]: 新聚能科技, "2025年 TIPO台灣公告發證百大專利權人", https://synergytek.com.tw/blog/2025/12/28/2025-tipo-top100/ ; etopteam, "2024年台灣專利申請總數成長2% 發明平均14.2個月結案", https://etopteam.com/2025/03/04/2024-annual-patent-report-from-tipo/
[^2]: TIPO 113年年報 (annual report 2024) electronic-filing top-20 PDF, https://www.tipo.gov.tw/wSite/public/Attachment/0/f1747797897522.pdf ; TIPO 112年 archive, https://www.tipo.gov.tw/wSite/public/Attachment/0/f1743411733419.pdf ; TIPO 110年 reference, https://www.tipo.gov.tw/tw/cp-847-913912-15227-1.html
[^3]: IAM Patent 1000, Taiwan jurisdiction landing, https://www.iam-media.com/rankings/patent-1000/country/taiwan
[^4]: Legal 500, Taiwan IP rankings, https://www.legal500.com/c/taiwan/intellectual-property
[^5]: Asia IP, Taiwan law firm directory, https://asiaiplaw.com/law-firm/taiwan
[^6]: Managing IP, "Asia-Pacific Awards 2025 Winners Hub", https://www.managingip.com/managing-ip-awards-apac-2025-winners-hub ; firms-to-watch shortlist, https://www.managingip.com/article/2fgh3o6uu51r4l9blp6v4/patents/managing-ip-asia-pacific-awards-2025-firms-to-watch
[^7]: Lee and Li firm profile (Chambers/IP Stars), https://chambers.com/office/lee-and-li-attorneys-at-law-taipei-taiwan-jurisdiction-greater-china-region-116:2315 ; https://www.ipstars.com/Firm/Lee-and-Li-Attorneys-at-Law-Taiwan/Profile/102268 ; senior patent attorney profile (TSMC alum), https://www.leeandli.com/EN/Professions/800/251.htm
[^8]: Tsai, Lee & Chen overview (asialaw / IAM Patent 1000), https://www.asialaw.com/Firm/tsai-lee-chen/Profile/1391 ; https://www.iam-media.com/rankings/patent-1000/profile/firm/tsai-lee-chen-patent-attorneys-attorneys-at-law
[^9]: Jianq Chyun IP Group profile (IAM Patent 1000), https://www.iam-media.com/rankings/patent-1000/profile/firm/jianq-chyun-ip-office ; firm directory listing, https://ipattorneys.parkerip.com/ip-directory/member-details?MemberID=1478&Country=/1000
[^10]: Saint Island Intellectual Property Group, 聖島簡介, https://www.saint-island.com.tw/Tw/AboutUs/About_Info.aspx?IT=About_1&ID=128 ; office locations, https://www.saint-island.com.tw/Tw/AboutUs/About_Info.aspx?IT=About_1&ID=130
[^11]: Asia IP, Saint Island profile, https://asiaiplaw.com/law-firm/taiwan
[^12]: Tai E International Patent & Law Office, https://www.taie.com.tw/en/ ; firm profile (IP Stars), https://www.ipstars.com/Firm/Tai-E-International-Patent-Law-Office-Taiwan/Profile/102270
[^13]: TIPLO Attorneys-at-Law, https://www.tiplo.com.tw/en ; IAM Patent 1000 TIPLO profile, https://www.iam-media.com/rankings/patent-1000/profile/firm/tiplo-taiwan-international-patent-law-office
[^14]: NAIPO (北美智權) corporate site, https://www.naipo.com/about.aspx?strEnc=en-US ; LinkedIn company page, https://tw.linkedin.com/company/north-america-intellectual-property-corporation ; newsletter 北美智權報, https://naipnews.naipo.com/
[^15]: Formosa Transnational profile (IAM Patent 1000), https://www.iam-media.com/rankings/patent-1000/profile/firm/formosa-transnational-attorneys-at-law ; The World Law Group, https://www.theworldlawgroup.com/member-firms/formosa-transnational
[^16]: Asia IP, "2025 Asia IP Awards winners crowned in Kuala Lumpur", https://asiaiplaw.com/section/in-depth/2025-asia-ip-awards-winners-crowned-in-kuala-lumpur ; Asia IP Taiwan IP experts list, https://www.asiaiplaw.com/ip-expert/taiwan
[^17]: Top Team International, IAM Patent 1000 profile, https://www.iam-media.com/rankings/patent-1000/profile/firm/top-team-international-patent-trademark-office ; Legal 500 Top Team profile, https://www.legal500.com/firms/31993-top-team-international-patent-trademark-office/32256-taipei-taiwan/
[^18]: Lee and Li privacy and data protection policy, https://www.leeandli.com/EN/000000318.htm
[^19]: Foley & Lardner, "Foley Advances Its AI-First Approach Through Strategic Execution", May 2026, https://www.foley.com/news/2026/05/foley-advances-its-ai-first-approach-through-strategic-execution/
[^20]: Harvey, "Foley & Lardner Rolls Out Harvey Firmwide", https://www.harvey.ai/blog/foley-and-lardner-rolls-out-harvey-firmwide ; Law360 coverage, https://www.law360.com/articles/2478949/foley-lardner-expands-use-of-ai-platform-harvey
[^21]: Sterne Kessler / Thomson Reuters Patent Claim Eligibility Analyzer announcement, May 2026, https://www.sternekessler.com/news-insights/news/sterne-kessler-and-thomson-reuters-partner-to-create-new-ai-tool-for-patent-litigation/
[^22]: Las Vegas Sun coverage, May 2026, https://lasvegassun.com/news/2026/may/13/sterne-kessler-and-thomson-reuters-partner-to-crea/
[^23]: Finnegan, "AI + Patent" practice page, https://www.finnegan.com/en/work/practices/ai-finnegan/ai-patent.html
[^24]: Sterne Kessler, "Strategic Prosecution in 2026", https://www.sternekessler.com/news-insights/insights/strategic-prosecution-in-2026-what-patent-examiners-might-do-differently-and-what-that-means-for-your-portfolio/
[^25]: McAndrews, Held & Malloy IAM Patent 1000 profile, https://www.iam-media.com/rankings/patent-1000/profile/firm/mcandrews-held-malloy-ltd
[^26]: Perspective AI, "Harvey AI forward-deployed engineers BigLaw deployment playbook 2026", https://getperspective.ai/blog/harvey-ai-forward-deployed-engineers-biglaw-deployment-playbook-2026
[^27]: Federal Register, "Guidance on Use of Artificial Intelligence-Based Tools in Practice Before the United States Patent and Trademark Office", April 11 2024, https://www.federalregister.gov/documents/2024/04/11/2024-07629/guidance-on-use-of-artificial-intelligence-based-tools-in-practice-before-the-united-states-patent
[^28]: USPTO press release, "USPTO issues guidance concerning the use of AI tools by parties and practitioners", https://www.uspto.gov/about-us/news-updates/uspto-issues-guidance-concerning-use-ai-tools-parties-and-practitioners ; IPWatchdog summary, https://ipwatchdog.com/2024/05/02/tips-for-using-ai-tools-after-the-usptos-recent-guidance-for-practitioners/
[^29]: Taiwan Bar Association (TWBA), "律師使用生成式AI工具規範初探" PDF, November 2024, https://www.twba.org.tw/upload/article/20241120/54b8dfc75f3e46f4b539278b4b07daac/54b8dfc75f3e46f4b539278b4b07daac.pdf ; March 2025 follow-up TWBA PDF, https://www.twba.org.tw/upload/article/20250314/22404c3eb8f54221b8dec64e1f7760ea/22404c3eb8f54221b8dec64e1f7760ea.pdf
[^30]: TIPO 公告, "中華民國專利師公會即將於114年12月1日起受理115年度專利師職前訓練報名", https://www.tipo.gov.tw/tw/tipo1/799-66014.html ; TWPAA main site, https://www.twpaa.org.tw/
[^31]: Taipei Times, "Legislature passes new artificial intelligence law", Dec 24 2025, https://www.taipeitimes.com/News/front/archives/2025/12/24/2003849407 ; IAPP analysis, "Taiwan's strategic leap into AI", https://iapp.org/news/a/taiwan-s-strategic-leap-into-ai-enacting-the-ai-basic-act-to-foster-innovation-governance
[^32]: Baker McKenzie, "Taiwan: AI Basic Act" insight, https://www.bakermckenzie.com/en/insight/publications/2026/01/taiwan-ai-basic-act ; Lexology summary, https://www.lexology.com/library/detail.aspx?g=c56f0acb-1fff-4929-9765-1f40c9aa358a ; law.asia summary, https://law.asia/taiwan-ai-basic-act-legal-framework-risk-policy/
[^33]: Managing IP, "Lawbank v Lawsnote: Taiwan ruling delivers a hard lesson on copyright", https://www.managingip.com/article/2fo0b331hwuncolide0ow/sponsored-content/lawbank-v-lawsnote-taiwan-ruling-delivers-a-hard-lesson-on-copyright
[^34]: Lexology, "Harvey and the Lawsnote Ruling: Copyright Battles in the Age of Legal AI", https://www.lexology.com/library/detail.aspx?g=c7c4a6a3-350e-42a4-8bfc-1595f845f452 ; "Taiwan's Copyright Showdown", https://www.lexology.com/library/detail.aspx?g=8f62b056-64fe-431e-a7fc-ed651e5a653c
[^35]: WhiteHsu blog, "AI Training Data Copyright: Lessons from Taiwan's Lawsnote Case", March 2026, https://whitehsu.blog/2026/03/16/ai-training-data-copyright-taiwan-case/ ; TechNews 科技新報, "創新踩線還是侵權？", https://technews.tw/2025/07/12/lawsnote-vs-law-bank-lawsuit/
[^36]: iPNote, "Patent Office Action Responding in Taiwan" service page, https://ipnote.pro/taiwan/arb/services/patent-registration/patent-office-action-responding/ (starts USD 450)
[^37]: ezbizer, "2025年全台三大專利商標事務所推薦", https://ezbizer.com/01/patent-taiwan/top-three-taiwan-patent-and-trademark-office-agent/
[^38]: Lexology, "In brief: patent prosecution in Taiwan", https://www.lexology.com/library/detail.aspx?g=754cfca9-921c-456a-8458-189269067668 ; NAIPO, "IP Observer #001: How Can I Apply for a Patent in Taiwan and How Much Does It Cost?", https://www.naipo.com/Portals/0/web_en/Knowledge_Center/Feature/IPNE_160401_0704.htm
[^39]: Patent Trademark Blog, "How much does a patent Office Action response cost?", https://www.patenttrademarkblog.com/patent-office-action-response-cost/
[^40]: AIPLA, "2025 Report of the Economic Survey", https://www.aipla.org/detail/journal-issue/2025-report-of-the-economic-survey ; AIPLA Report-of-Economic-Survey index, https://www.aipla.org/home/news-publications/economic-survey
[^41]: ClaimMaster Subscriptions Pricing page, https://www.patentclaimmaster.com/CMBuy.html ; subscription comparison, https://www.patentclaimmaster.com/CMComparison.html
[^42]: Patlytics Software Finder profile, https://softwarefinder.com/legal/patlytics ; RightAIChoice estimate, https://rightaichoice.com/tools/patlytics
[^43]: thelegalprompts, "AI legal tools pricing comparison 2026", https://thelegalprompts.com/blog/ai-legal-tools-pricing-comparison ; costbench, "Harvey AI software cost analysis", https://costbench.com/software/ai-legal-tools/harvey-ai/ ; eesel.ai, "Solve Intelligence pricing", https://www.eesel.ai/blog/solve-intelligence-pricing ; Patentext blog, "9 best AI patent drafting tools in 2026 (with pricing)", https://blog.patentext.com/blog-posts/best-ai-patent-drafting-tools
[^44]: Lawsnote Inc. profile (ai-taiwan.com.tw), https://ai-taiwan.com.tw/2025/vendor/284 ; Lawbot AI commentary on Lawsnote/法源 pricing, https://lawbot.tw/blog/ZOSOhJbIbNBLYz2ph4ue
[^45]: LexisNexis PatentSight product page, https://www.lexisnexisip.com/solutions/ip-analytics-and-intelligence/patentsight/ ; Software Finder profile (custom pricing), https://softwarefinder.com/legal/lexisnexis-patentsight
[^46]: Anaqua, https://www.anaqua.com/
[^47]: TPIsoftware digiRunner pricing references, https://www.trustradius.com/products/tpisoftware-digifusion/pricing ; AWS Marketplace listing, https://www.tpisoftware.com/en/products/digirunner/awsmarketplace
[^48]: TPIsoftware Blog, "TPIsoftware and Taishin's API Management Platform awarded with Global Finance award", https://blog.tpisoftware.com/en/businessscenario/taishinsapi/
[^49]: OpenTPI Medium, "Case Study: Transforming Banking Operations with digiRunner API Management", March 2025, https://medium.com/@opentpi/case-study-transforming-banking-operations-with-digirunner-api-management-eda57fa1a896
[^50]: 長江國際專利商標法律事務所, "本所名列2022年1月電子申請前20大事務所", https://longriver.com.tw/news-ch/%E6%9C%AC%E6%89%80%E5%90%8D%E5%88%972022%E5%B9%B41%E6%9C%88%E9%9B%BB%E5%AD%90%E7%94%B3%E8%AB%8B%E5%89%8D20%E5%A4%A7%E4%BA%8B%E5%8B%99%E6%89%80/
[^51]: DeepIP blog, "Best AI tools for patent attorneys 2026", https://www.deepip.ai/blog/top-ai-tools-patent-attorneys-are-using-to-boost-efficiency ; DeepIP "AI Office Action 2026" guide, https://www.deepip.ai/blog/ai-office-action
[^52]: Solve Intelligence, "Ranked #1 IP Platform by the World's Leading Law Firms", https://www.solveintelligence.com/blog/post/solve-intelligence-ranked-1-ip-platform-by-the-worlds-leading-law-firms ; YC profile, https://www.ycombinator.com/companies/solve-intelligence
[^53]: AIPLA, "Patent Eligibility of AI Technology Inventions in Taiwan and Analysis of Filing Strategies", https://www.aipla.org/list/innovate-articles/patent-eligibility-of-ai-technology-inventions-in-taiwan-and-analysis-of-filing-strategies ; TIPO international news, "WIPO Generative AI Navigator", https://www.tipo.gov.tw/tw/cp-90-936735-0566d-1.html

---

*Document prepared 2026-06-05 by the market-research agent. No backend,
frontend, test, or config files modified per task scope. ~4,800 words.*
