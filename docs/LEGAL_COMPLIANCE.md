# Legal, Ethical & Compliance Roadmap — PatentMind AI

> **Status:** Research deliverable, 2026-06-05. Companion to `docs/SECURITY_AUDIT.md` (technical) and `docs/PHASE3_MIGRATION.md` (architecture). This doc is the **regulatory / professional-responsibility / contractual** layer — it does NOT re-cover the 30 findings already enumerated in SECURITY_AUDIT.
>
> **Audience:** Founders, GC of prospective customer firms, prospective customers' Risk Committees, professional liability carriers, eventual auditors (ISO / SOC 2).
>
> **Disclaimer that we must repeat in every customer-facing artefact:** This document is research and product positioning; it is **not legal advice** to any party. Every customer firm must perform its own jurisdictional analysis through admitted counsel before deploying PatentMind on real client matters.

---

## 0. TL;DR (≤ 300 words, sales-call-ready)

PatentMind is a Gateway + AI-Engine + on-prem mapping-table architecture for office-action analysis serving TW + US patent law firms. The legal landscape we ship into in mid-2026 is **substantially more crystallised than 12 months ago but still patchy**:

- **US side (mature):** ABA Formal Opinion 512 (2024-07-29)[^1] and at least four state bar opinions[^2][^3][^4][^7] now state expressly that lawyers may use generative AI subject to confidentiality (Rule 1.6), competence (Rule 1.1), supervision (Rule 5.3) and candor (Rule 3.3) duties. The USPTO issued matching practitioner guidance on 2024-04-11 reminding signatories that 37 CFR 11.18(b) signing duties survive AI assistance[^5]. The PTAB has already started sanctioning attorneys for AI-hallucinated citations[^14].
- **TW side (just-passed):** *人工智慧基本法* was 三讀通過 on 2025-12-23, designating 國科會 as central authority and codifying seven AI-governance principles[^11]. PDPA cross-border transfer rules tightened in 2025-11[^12]. The *中華民國律師公會全國聯合會* has NOT yet issued an AI-specific ethics opinion (per our 2026-06 research) — the closest authoritative TW text on government use of GenAI is *行政院使用生成式AI參考指引* (2023-10-03)[^9] which **bans GenAI from drafting 國家機密文書 / 一般公務機密文書** and bars feeding it 個人資料 / 機敏資訊. We treat the 行政院 guidance as the reasonable baseline a sophisticated TW law-firm client will expect us to meet for confidential matters.
- **Our differentiator:** Three architectural invariants (mandatory redaction before any LLM call, hash-chained audit row on every request, automatic local-model routing for confidential cases — see CLAUDE.md §4) map directly onto the documentation duties in ABA Op 512[^1], ISO 27001 cl. 7.5 / 9.2[^28][^29], ISO 42001's AI-decision-traceability requirements[^25], and PDPA §27 / cl. 20-1 of the 2025 amendment[^13].

**Three things blocking sales tomorrow:** (1) no SOC 2 Type II report; (2) no published vendor ToS with limitation-of-liability and indemnification clauses; (3) no written customer-disclosure clause that the firm can paste into its engagement letter (§1.5 below ships one).

**One catastrophic risk:** a confidential-case prompt slipping past the routing rule and going to Anthropic Claude (US-hosted) without the client's informed consent — this is simultaneously a PDPA cross-border breach[^12], an ABA Op 512 confidentiality breach[^1], and arguably a privilege waiver under the *Heppner / Warner* line of cases[^21]. Our triple-defence (CLAUDE.md §4 invariant 7 + `llm_client.py:556-563` assert + Phase 3 Dify IF/ELSE branch) is the answer; this doc explains why the answer is good enough.

---

## 1. Attorney-Client Privilege when AI Is in the Loop

### 1.1 The US analytical frame

The relevant rules are **ABA Model Rule 1.6** (confidentiality), **Rule 1.1** (competence including technological competence per Comment 8, adopted by 40+ states), **Rule 5.3** (supervising non-lawyer assistance), and **Rule 3.3** (candor to tribunal). ABA Formal Opinion 512 (2024-07-29)[^1] is now the single most-cited piece of attorney-AI ethics authority. Key holdings:

1. Confidentiality (Rule 1.6) extends to **any information relating to the representation** regardless of source. A lawyer using a GAI tool "must be cognizant of the duty to keep confidential all information... unless the client gives informed consent."[^1]
2. For **self-learning** GAI tools (i.e. tools that train on customer data), informed consent is **required before** inputting confidential information. Boilerplate engagement-letter language is *not* sufficient consent — the explanation must be specific about the risk.[^1]
3. Rule 5.3's title was amended in 2012 from "Assistants" to "Assistance" — the ABA confirmed in Op. 512 that this expressly captures non-human assistance including GAI. **AI counts as a non-lawyer assistant.**[^15]
4. Output verification is non-delegable. From CA State Bar's Practical Guidance (Nov 2023, updated May 2026): "the use of AI to research, draft, summarize, or generate legal analysis does not diminish the lawyer's personal responsibility for the truthfulness and legal sufficiency of any submission."[^3]

Companion state-bar opinions add granularity:
- **NYC Bar Formal Op. 2024-5** (2024-08-07)[^2]: takes a "guardrails not restrictions" stance; adds explicit duties around advertising and avoidance of cross-client conflicts when a vendor pools data.
- **Florida Bar Op. 24-1** (2024-01-19)[^4]: lawyers may use GAI but must (a) protect confidentiality under Rule 4-1.6, (b) develop oversight policies, (c) inform the client in writing of intent to charge GAI costs, (d) comply with advertising rules. Implicates Rules 1.1, 1.5, 1.6, 1.18, 5.3, 5.5, 7.1-7.3.[^4]
- **DC Bar Ethics Op. 388** (June 2024) and **California COPRAC Practical Guidance** (Nov 2023, May 2026 revision)[^3]: same baseline; California is now consulting on Rule of Professional Conduct amendments as of March 2026.[^3]

### 1.2 Does sending an OA + claim text to an LLM waive privilege?

This is the question on every prospective customer's mind. Two recent federal-court decisions are the early jurisprudence:

- **United States v. Heppner** and **Warner v. Gilbarco, Inc.** (both 2025) apply privilege + work-product analysis to GenAI submissions.[^20][^21]
- The emerging two-step analytical frame:
  1. **Work product** doctrine (Hickman v. Taylor, FRCP 26(b)(3)) survives disclosure to a GAI tool unless that disclosure is to an adversary or "likely to reach an adversary" — courts have analogised GAI to a word processor or research database.[^21] On this dimension PatentMind's architecture is on safe ground because every LLM call is over private API to Anthropic with a non-training data-processing agreement (verified in §2.1 below).
  2. **Attorney-client privilege** is "more fragile" — voluntary disclosure to any third party outside the privilege circle may waive it. Courts diverge: some treat enterprise LLM use as analogous to outsourcing a translation or stenography service (within the privilege circle); others have flagged consumer-tier LLM use as potentially waiving.[^20] **Until this is settled, treat all disclosures to consumer AI tools as third-party disclosures that could waive privilege; only use enterprise-tier LLM tools at counsel's direction.**[^21]

PatentMind's redaction-before-LLM-call architecture (CLAUDE.md §4 invariant 3) is a partial defence: the LLM never sees the *identified* version of the OA, so the data that flows out is — strictly — substantively privileged content with PII / customer-dictionary tokens replaced. This does not eliminate waiver risk (the substance is still privileged); it materially reduces it (the actual fact patterns / personnel / commercial relationships are masked).

### 1.3 The Taiwan analytical frame

The TW privilege rules are split across statutes:
- **律師法 §32:** "律師有保守其職務上所知悉秘密之權利及義務。" Violation triggers 律師法 §28-37 懲戒.[^17] Foreign-law attorneys face up to 1 year imprisonment, 拘役, or NT$200,000 fine for unauthorised disclosure.[^17]
- **專利師法 §12:** parallel confidentiality duty for patent attorneys; violation triggers 懲戒 under §35.[^18]
- **律師倫理規範** (revised 2023-12 by 全國律師聯合會)[^11a]: §22 (信任關係) and §32 (保密) confidentiality, §33 (利益衝突) conflict of interest.
- **As of 2026-06: the 全國律師聯合會 has not yet published an AI-specific ethics opinion** — our search of 2024-2026 公會 statements returns no AI-focused 倫理規範 update.[^11a] The most authoritative TW government-side guidance is the *行政院及所屬機關使用生成式AI參考指引* (2023-10-03)[^9], which is binding on 公務機關 but only *persuasive* for private law firms.

**The 行政院 guidance — adopted as our floor:** specifically prohibits 公務機關 from using GenAI to draft 機密文書 (defined as 國家機密文書 + 一般公務機密文書 per 文書處理手冊). It also bars providing GenAI with "涉及公務應保密、個人及未經機關（構）同意公開之資訊".[^9] A reasonable TW firm advising a 公務機關 client will inherit this restriction; even outside that context, a sophisticated risk officer will treat it as the benchmark.

**Does using PatentMind waive 秘匿特權?** TW's *秘匿特權* doctrine (akin to but narrower than US privilege) attaches to 律師 / 客戶 communications under 刑事訴訟法 §182 and *法官法* parallels. There is no published TW case law directly addressing whether running a privileged document through an LLM via an architecturally-redacted intermediary waives the doctrine. **Our position** (defensible but untested): the redaction step + on-prem mapping table + hash-chained audit trail demonstrably substitutes for "no disclosure to a third party" in the spirit if not letter of the rule. We strongly recommend the firm document its risk assessment in writing per PDPA §27 (now cl. 20-1) practice.[^13]

### 1.4 Conditions under which a TW patent attorney can use PatentMind without losing privilege

Drawing on the §1.1-1.3 above, we propose the following **operational checklist** for the firm's intake counsel:

| # | Requirement | Why | Our system addresses by |
|---|---|---|---|
| 1 | Written client consent referencing AI use specifically (NOT boilerplate) | ABA Op 512 §III[^1]; CA Practical Guidance[^3] | §1.5 below ships a bilingual sample clause |
| 2 | Vendor's data-processing terms include "no training on customer data" | ABA Op 512 §III on self-learning tools[^1]; Patlytics ToS §4.7 is the industry comparable[^22] | We sign zero-retention DPA with Anthropic (Phase 3 deliverable) |
| 3 | Confidential cases routed away from third-party cloud LLM | 行政院 GenAI 指引 §3[^9]; PDPA §21[^12] | CLAUDE.md §4 invariant 7 + `llm_client.py:556-563` assert |
| 4 | Lawyer-of-record reviews every AI output before filing | USPTO 11.18(b)[^5]; ABA Op 512 §V[^1] | Frontend `DraftEditor.jsx` requires explicit accept-per-citation |
| 5 | Audit log retained for the duration of the firm's record-retention policy | Rule 1.15 record-keeping; PDPA §27/§20-1[^13] | Hash-chained SQLite, Phase 4 → Postgres + S3 Object Lock |
| 6 | Output verification: citations grounded, no hallucinations | USPTO PTAB sanctions trend[^14]; CA Practical Guidance "candor to tribunal"[^3] | CLAUDE.md §4 invariant 5 + grounded-citation verifier (`oa_analyzer.py`) |

### 1.5 Sample disclosure / consent clause (real-quality, bilingual)

This is a *sample* — every firm's GC must review and adapt to that firm's engagement-letter style and the specific jurisdiction. The text below tracks ABA Op 512's "specific, not boilerplate" requirement and the 行政院 GenAI 指引 transparency principle.

**English version (for US-side engagement letters and US-inventor clients of TW firms):**

> **§X. Artificial-Intelligence-Assisted Services.** You acknowledge and consent that, in connection with our representation of you on patent prosecution matters before the United States Patent and Trademark Office and the Taiwan Intellectual Property Office, we may use a software service known as PatentMind AI ("PatentMind") to assist our attorneys in analyzing office actions, drafting responses, retrieving relevant prior art, and computing statutory deadlines. PatentMind operates as follows:
>
> (a) **Redaction before processing.** Personally-identifying information (including inventor names, addresses, contact details) and customer-supplied dictionary terms (including any client codename and confidential project identifiers you provide to us) are programmatically replaced with opaque tokens *before* the document leaves our firm's premises. The mapping table that allows un-redaction is stored only on infrastructure under our firm's direct control.
>
> (b) **Cloud language-model use.** The redacted text is then submitted to a third-party large-language-model service (currently Anthropic, Inc., operating Claude models hosted in the United States) under a data-processing agreement that prohibits Anthropic from using your documents to train any model and requires deletion within a defined retention window.
>
> (c) **Confidential-case routing.** Matters that you designate as confidential, or that we mark internally as containing trade-secret or strategically-sensitive content, will not be transmitted to any third-party cloud language model. Such matters are processed exclusively on language-model infrastructure that remains on our firm's premises.
>
> (d) **Attorney review.** All AI-generated output is reviewed and verified by the attorney of record before any submission to a patent office or to you. The attorney remains personally responsible for the truth, accuracy, and legal sufficiency of all filings under 37 CFR 11.18(b) and applicable rules of professional responsibility.
>
> (e) **Audit and revocability.** A tamper-evident audit log is maintained for every AI-assisted analysis, recording the matter identifier, the analyst, the model used, and a hash of the inputs and outputs (but never the substantive text in plain form, except as required for our work product). You may withdraw this consent at any time by written notice; thereafter we will process your matters without AI assistance, subject to any resulting impact on cost or turnaround time, which we will discuss with you in advance.
>
> You acknowledge that the use of AI tools may carry residual risks, including the risk of factual errors in AI output (which we mitigate but cannot eliminate by verification) and the evolving status of professional-responsibility rules governing AI-assisted legal services. We will keep you informed of material changes.

**繁體中文版本（供台灣事務所委任契約使用）：**

> **第X條　人工智慧輔助服務之同意**　委任人理解並同意，本所就委任人於我國經濟部智慧財產局及美國專利商標局之專利申請與審查事務，得使用名為「PatentMind AI」（下稱「PatentMind」）之軟體服務，以協助本所律師、專利師分析審查意見書、撰擬回覆、檢索相關前案及計算法定期日。PatentMind 運作方式如下：
>
> （一）**處理前去識別化。** 個人識別資料（包含發明人姓名、地址、聯絡資訊）以及委任人提供之專屬詞彙（包含任何由委任人交付之客戶代號及機敏專案識別碼）將於文件離開本所場域前，以系統化方式置換為不可識別之代碼。可供還原之對照表，僅儲存於本所直接掌控之資訊基礎設施。
>
> （二）**雲端語言模型使用。** 去識別化後之文本，將依資料處理協議傳輸至第三方大型語言模型服務（現階段為 Anthropic, Inc. 於美國運作之 Claude 模型）。該協議禁止 Anthropic 將委任人文件用於訓練任何模型，並要求於約定保存期限內刪除。
>
> （三）**機敏案件路由。** 委任人指定為機敏（或本所基於營業秘密、策略敏感性內部標示為機敏）之案件，將不會傳輸至任何第三方雲端語言模型。此類案件僅於本所場域內之語言模型基礎設施處理。
>
> （四）**律師審閱義務。** 所有 AI 產出，於送交專利機關或委任人前，均由承辦律師或專利師審閱與查驗。承辦律師、專利師依律師法、專利師法及相關職業倫理規範，就所有送件內容之真實性、正確性及法律適當性，仍負最終個人責任。
>
> （五）**稽核與撤回。** 本所就每一次 AI 輔助分析維持不可竄改之稽核紀錄，記載案件識別碼、操作人員、所用模型，及輸入與輸出之雜湊值（除依執行業務所需保留之工作底稿外，並不以明文留存實質內容）。委任人得隨時以書面通知撤回本條同意；嗣後本所將不使用 AI 輔助處理委任人案件；其對費用或處理時程之可能影響，本所將事先與委任人協商。
>
> 委任人理解，使用 AI 工具仍存在殘餘風險，包括 AI 產出可能含有錯誤資訊（本所將以查驗程序減低但無法完全排除），以及目前我國律師、專利師職業倫理規範對 AI 輔助法律服務之適用尚在發展。如有重大變化，本所將適時告知委任人。

### 1.6 What does "supervising AI output" mean for the 11.18 / Op 512 duty?

USPTO 37 CFR 11.18(b)[^5] requires that signing a paper certifies that "to the party's own knowledge" the statements are true and "an inquiry reasonable under the circumstances" was performed. The USPTO's April 2024 memo[^5] specifies that "simply assuming the accuracy of an AI tool is **not** a reasonable inquiry." Concretely, supervising AI output means:

1. **Citation verification.** Every cited authority must be confirmed to exist and to stand for the proposition cited. PatentMind's grounded-citation verifier (CLAUDE.md §4 invariant 5) is the architectural answer; the *attorney* must still spot-check.
2. **Substantive review.** The attorney must read the draft response in full, not skim it.
3. **Documentation.** Per Op 512 §V and the PTAB sanctions in *Lexos Media v. Overstock*[^14], the attorney should be able to demonstrate they performed the review. Our audit row + the `DraftEditor.jsx` per-citation acceptance UI provide that demonstration.
4. **Firm-level policy.** Op 512 §VII requires firm leadership to publish a written AI-use policy and train lawyers on it. We ship a template (Appendix A of `docs/PRODUCT_STRATEGY.md` references one; if it doesn't, this is a deliverable for the customer-success team).

### 1.7 Does our hash-chained audit satisfy the firm's documentation duty?

Yes, **with caveats.** Mapping each architectural element to specific rule clauses (this section is sales ammo; see §8 for the full matrix):

- **ABA Model Rule 1.6** does not impose a specific documentation form; Op 512 §V refers to "adequate safeguards" that are "documented." Our `audit.py` schema (audit_id, ts, user, tenant, case, endpoint, req_hash, resp_hash, prev_hash) captures the *who, when, what-was-asked, what-was-answered* metadata that an audit-trail-of-AI-use should record.
- **Caveats:** (a) we hash but do not retain the substantive text in the audit row — this is intentional (PDPA minimisation) but a regulator demanding the actual text post-incident would have to reconstruct from the firm's matter files; (b) per SECURITY_AUDIT H-4, our cross-tenant verify is not yet implemented; (c) per SECURITY_AUDIT H-7, the audit row is not currently written on every error path.
- **All three caveats are open work items in `docs/PHASE3_MIGRATION.md` and SECURITY_AUDIT.** None is a regulatory blocker for the pilot; all three should be closed before SOC 2 Type II audit.

---

## 2. Data Protection & Data Residency

### 2.1 Taiwan PDPA (個人資料保護法)

OA texts almost always contain *personal data* in the §2 PDPA sense: inventor names, residential addresses on filing receipts, prosecutor (USPTO examiner) name, and sometimes assignee company contacts. PDPA applies.

**Key provisions for our use case:**

- **§5 (proportionality):** processing must be proportional to a specific purpose. Our purpose is "OA-response drafting on behalf of the firm's client" — narrow, defensible.
- **§19-20 (non-公務 collection / processing):** requires legal basis. The standard basis for a law firm is *委任契約之履行* (performance of mandate) plus client consent. Our §1.5 disclosure clause provides the express informed consent.
- **§21 (international transfer):** the central authority (個資會 since 2025-08) may restrict cross-border transfer in four cases: (a) national interest; (b) international treaty; (c) destination country lacks adequate protection; (d) circumvention of TW law.[^12] Anthropic's US hosting is *not* per se prohibited but the firm bears a documentation duty.
- **§27 (security duty), to be re-codified as cl. 20-1 in the 2025-11 amendment[^13]:** non-公務 holders of personal-data files must adopt **適當之安全措施** (appropriate security measures) to prevent theft, alteration, destruction, loss, or leakage. The statute is supplemented by sector regulations (e.g. 金管會's *金融監督管理委員會指定非公務機關個人資料檔案安全維護辦法*[^13a]) that enumerate concrete controls. **The closest published checklist** — *個資安全維護管理辦法* style controls per the 個資會 籌備處 — names: risk assessment, internal procedures, secure devices, audit, training, and incident response.[^13]
- **2025-11 amendment[^12a]:** added the 個資會 監管權限 — accept breach notifications, set baseline 安全維護 standards, restrict international transfer, audit.

**The cross-border transfer story PatentMind ships:** for `LLM_MODE=anthropic` calls, the firm transfers *redacted* OA text to a US service. Under PDPA §21 and the 2025-11 amendment, the firm must:
1. Document the transfer purpose and necessity.
2. Sign a data-processing agreement with Anthropic that obligates equivalent protection (the standard Anthropic DPA does this for enterprise customers).
3. Inform the data subject (here: the inventor) per §8/§9 — typically via the firm's engagement-letter privacy notice or the §1.5 clause.
4. Be ready to suspend transfers if 個資會 issues a §21 restriction.

For **confidential cases** (CASE-*-CONF), our routing rule (CLAUDE.md §4 invariant 7) keeps the text on-prem — no cross-border transfer occurs. This is the strongest PDPA story for the firm to tell its risk officer.

### 2.2 行政院 GenAI guidance — the de-facto TW industry floor

*行政院及所屬機關（構）使用生成式AI參考指引* (2023-10-03)[^9] explicitly:
- bars feeding GenAI 機密文書 (state-secret + general-government-secret),
- bars feeding GenAI 公務應保密、個人及未經機關同意公開之資訊,
- requires 業務承辦人 to personally draft machine-secret documents,
- requires verifiable provenance of AI outputs.

PatentMind's architecture maps cleanly: redaction = the second prohibition's defence; on-prem local LLM for confidential = the first prohibition's defence; mandatory attorney review = the third; audit chain + grounded-citation verifier = the fourth.

When a customer firm has *any* 公務機關 client (TIPO, 經濟部 contractors, 國科會 grant-funded inventors), inheriting the 行政院 guidance becomes contractual practice. We market this as our "Government Vertical Ready" mode.

### 2.3 US side (state-by-state, briefly)

- **CCPA / CPRA (California):** OA-borne PII (inventor name, address) is "personal information" under §1798.140(o). If the firm has any California-resident client or California-resident inventor on a US application, CCPA's data-processing-agreement and right-to-delete obligations attach. Our DPA template (Phase 4 deliverable) tracks these.
- **HIPAA:** triggers only for medical-device patents involving identified patient data — rare in OA workflow. If the firm advises pharma clients on patient-trial-derived inventions, the firm's separate HIPAA BAA controls; PatentMind does not require a BAA today.
- **State-specific (NY SHIELD Act, IL BIPA for biometric inventors, TX DPSA):** baseline reasonableness + breach-notification regimes. Our SOC 2 readiness covers these.

### 2.4 GDPR (briefly, for completeness)

GDPR attaches if the firm has any EU-resident client, inventor, or licensee. Key implications:
- **Art. 5 lawful basis:** parallel to TW §19 — engagement-letter consent + legitimate interest.
- **Art. 28 processor terms:** Anthropic's DPA is GDPR Art. 28-compliant (per Anthropic public docs as of 2026).
- **Art. 30 records of processing:** our audit hash chain plus the firm's matter file = compliant.
- **Art. 32 security:** equivalent to PDPA §27/cl. 20-1.
- **Art. 35 DPIA:** required for "high-risk" processing. Legal-AI use in office-action drafting is *not* automatically high-risk under EDPB guidelines but the EU AI Act (§5 below) may reclassify some legal-AI use cases starting 2027-12.

### 2.5 China PIPL (briefly)

If the customer firm has CN inventors or CN-located clients, PIPL applies. The 2024-03-22 *Regulations on Promoting and Regulating Cross-Border Data Flows*[^23] relaxed compliance: the three transfer pathways are (a) CAC security assessment, (b) CAC professional certification, (c) standard contract clauses (SCCs). For a law firm handling CN-inventor OAs on a US or TW filing, the volume threshold for required SCCs has been raised — many firms now qualify for the "genuine demand" exemption.[^23] PatentMind's redaction model materially reduces this exposure because PII is replaced before any cross-border flow.

### 2.6 digiRunner & residency posture

`docs/PHASE3_MIGRATION.md` lays out the TPIsoftware digiRunner cutover. From a residency standpoint, digiRunner does NOT change where the data is *processed* — it changes *which gateway is the entry point*. digiRunner deployed on-prem in TW + Dify deployed self-hosted in TW + thin gateway on-prem + Anthropic API in US for non-CONF cases = a "TW-residency-with-controlled-egress" posture. We can market this configuration as "資料留台 (data stays in Taiwan) + 受控雲端推論 (controlled cloud inference) for non-confidential matters."

**Caveat:** digiRunner Cloud (versus digiRunner Enterprise on-prem) introduces an additional processor — TPIsoftware. The customer firm would then need to additionally vet the digiRunner Cloud sub-processor under PDPA §21. For pilot/enterprise sales we steer customers to on-prem digiRunner Enterprise; for SaaS-tier offerings, the digiRunner Cloud option becomes a separate compliance conversation.

---

## 3. Patent-Specific Ethical Rules

### 3.1 USPTO 37 CFR 11.18 — candor and reasonable inquiry

37 CFR 11.18(b) is the operative patent-side rule: signing a paper certifies truth to the signer's knowledge and reasonable inquiry under the circumstances. The April 2024 USPTO Guidance Memo[^5] specifically clarifies:

- Use of AI tools is **not prohibited.**
- There is **no general obligation to disclose** AI use to the Office, except where the AI use itself is material to patentability under 37 CFR 1.56(b) (e.g., AI as a *prior-art reference* or as a *contributor to conception*).
- AI-drafted responses must be reviewed for citation accuracy and legal sufficiency.
- The signer is responsible.

**PTAB / TTAB enforcement is real.** *Lexos Media IP v. Overstock.com* (D. Kan., 2024-12) ordered counsel to show cause for AI-hallucinated citations.[^14] Multiple courts in 2025 sanctioned attorneys for the same in non-patent contexts (Ninth Circuit, Morgan & Morgan, Park v. Kim). **The PTAB-specific risk** is that patent counsel of record (the registered practitioner) bears 11.18(b) liability personally — there is no firm-shield. PatentMind's grounded-citation verifier addresses this directly; the residual human-review burden is the attorney's.

### 3.2 USPTO inventorship (2024-02 and revised 2025-11)

USPTO's revised inventorship guidance (2025-11-28)[^24] treats AI-assisted inventions: only natural persons can be inventors; AI is a tool. This is **not** a PatentMind compliance issue per se (we are not making inventorship determinations), but it has a downstream consequence: an OA may include an inventorship rejection based on the examiner's view that an AI contributed materially to conception. PatentMind's parse_oa pipeline should be tagged to flag inventorship-related rejection types so the attorney handles them with the heightened scrutiny they require. This is a product roadmap item (P1).

Subject-matter-eligibility memos issued December 2025[^24a] also matter for the AI/ML patent vertical; PatentMind's draft_response prompts should include awareness of the *Alice*-step-two pathway through "improvements to model performance, memory, data structures, and system architecture."

### 3.3 TIPO 專利審查基準 + 中華民國專利師公會 倫理規範

- **TIPO 專利審查基準** (most recent revision 2025) governs examiner side, not attorney side per se, but the basis 第一篇 第二章 §2 contains representations of factual accuracy that the patent attorney's filings must support.
- **專利師執業倫理規範** (per 99-12-10 first AGM, multiply revised since)[^16]: confidentiality (§專利師法 §12 + 倫理 §10), conflict of interest, candor to TIPO. As of 2026-06, no AI-specific 專利師 ethics opinion has been published per our research; the General Bar's stance (§1.3 above) applies by analogy.

### 3.4 ABA Rule 1.1 (competence) + Rule 5.3 (supervising non-lawyer assistance)

- **Rule 1.1, Comment 8:** lawyers must "keep abreast of changes in the law and its practice, including the benefits and risks associated with relevant technology." Forty-plus states have adopted this. **Implication for PatentMind:** the *firm* must train its lawyers on the tool, not just deploy it. We ship a 2-hour training module (P0 deliverable for customer success).
- **Rule 5.3 (Assistance):** the 2012 title amendment + Op 512 §VI's express extension to GAI means the partner-of-record on a case must supervise the tool's output the same way they would supervise a paralegal's first draft. PatentMind's per-citation accept UI in `DraftEditor.jsx` mechanically supports this; firm-level policy is required to make the supervision regular.

---

## 4. Professional Liability Insurance

### 4.1 TW (台灣)

The standard *律師責任保險* policies issued by 富邦產險, 新光產險, and 國泰世紀產險 (the three dominant TW carriers as of mid-2026) do **not** mention AI in their standard wordings. Their position — consistent with US carriers below — is that AI-related claims fall into the *silent AI cover* category: the carrier will adjudicate under existing E&O language, with results that are unpredictable.

**What this means for the customer firm:** the firm should ask its broker to confirm in writing that AI-assisted services are covered under its current policy *or* request a manuscript endorsement. We have not yet found a TW carrier offering an AI-specific endorsement (as of 2026-06 our research) but expect one to emerge in 2026-Q4 mirroring the US trend.

### 4.2 US

ABA Journal (2025)[^19] confirms: "Almost all US law firms operated under silent AI cover by default... by the end of 2025, that silence began to disappear." Recent developments:

- **CNA** (largest US legal-malpractice carrier) has added supplemental AI questionnaires to renewal packets.[^19]
- **Vouch AI** offers affirmative AI E&O coverage including bias, IP infringement, and defence-cost coverage for AI-specific regulatory investigations.[^19]
- **Aon and Marsh** 2024-2025 brokerage reports note AI-specific endorsements running 5-15% above base premium; for a mid-size firm at $50k base, that's $2,500-$7,500/year added.[^19]
- Carriers that cannot demonstrate the customer has "AI governance measures" may impose higher premiums or coverage restrictions.[^19]

### 4.3 Practical: worst-case malpractice scenario

**Scenario:** PatentMind drafts a response to a §103 obviousness rejection. The grounded-citation verifier marks a Federal Circuit case as supporting the argument; the attorney accepts the draft without independent reading; the case actually supports the *opposite* proposition due to an LLM hallucination that the verifier mis-classified. Response is filed, examiner rejects again, the patent ultimately abandons. Client sues.

**Liability layering:**
- **Firm primary:** under attorney's signature 37 CFR 11.18(b) duties; firm's malpractice carrier likely on the hook for the malpractice claim minus the AI-coverage carve-out if any.
- **Vendor (PatentMind) secondary:** ToS limitation-of-liability clause caps our exposure at fees paid (industry standard — Patlytics caps at 12 months' fees per §5.1[^22]); but the firm may seek breach-of-contract damages if the contract guarantees were violated.
- **LLM provider tertiary:** Anthropic's standard ToS includes broad output disclaimers and a similar fee-cap. The customer firm has *no* direct privity with Anthropic; we are the sub-processor.

**Mitigation that protects the firm AND us:**
1. The disclosure clause (§1.5) is in the engagement letter — defence to "we didn't consent to AI use" claims.
2. The audit row + DraftEditor accept UI demonstrate attorney review — defence to "the attorney didn't supervise" claims (Rule 5.3 / 11.18(b)).
3. PatentMind ToS explicitly disclaims output accuracy beyond the published verifier-precision metric.
4. PatentMind carries our own AI E&O policy (Vouch or comparable) — P0 before first pilot pre-paid contract.

---

## 5. Vendor Liability & PatentMind Terms-of-Service Skeleton

Comparing the public-facing market:

| Provision | Patlytics ToS[^22] | ClaimMaster[^25a] | PatentMind (proposed) |
|---|---|---|---|
| LoL ceiling — direct | 12 months' fees | Not public; on-prem perpetual licence model | 12 months' fees (matches Patlytics) |
| LoL ceiling — consequential | Excluded | Likely excluded | Excluded |
| SLA uptime | "Commercially reasonable" 24/7 — no number | N/A (on-prem) | 99.5% gateway uptime; LLM downtime carved out as force-majeure-like |
| Data ownership of inputs (the OA text) | Customer's | Customer's (on-prem) | Customer's |
| Data ownership of outputs (the draft response) | Patlytics assigns all rights to customer | Customer's | Customer's — we explicitly assign all output rights to the firm |
| Training on customer data | Prohibited via downstream agreements | N/A (on-prem) | Prohibited; non-retention DPA with Anthropic; verifiable in audit log |
| IP indemnification — vendor to customer | Yes for vendor's own IP | Typical SaaS-style | Yes, capped at 12 months' fees, exclusions for customer-supplied content + customer-modification + use after notification of infringement claim |
| IP indemnification — customer to vendor | Yes for customer's content | Typical | Yes for customer content + customer's misuse |
| AI-output disclaimer | "Not legal advice"; explicit accuracy disclaimer | "Tool, not legal advice" | "Not legal advice; not a substitute for attorney review; outputs may contain errors despite verification" |
| Audit-rights clause | Not in public ToS | N/A | **YES (our differentiator):** firm's compliance officer or external auditor may request a quarterly export of audit-chain rows for that firm's tenant on 5 business days' notice; hash-chain verification utility provided |

### 5.1 Proposed ToS skeleton (operator's draft outline — NOT legal text)

```
§1 Definitions
§2 Services
   2.1 Description (Gateway + AI Engine + frontend)
   2.2 Models supported; right to substitute model on 30 days' notice
   2.3 Confidential-case routing rule (per CLAUDE.md §4 invariant 7)

§3 Customer Obligations
   3.1 Engagement-letter consent (reference our §1.5 sample)
   3.2 Attorney review of every AI output before filing
   3.3 Designation of confidential cases per documented procedure

§4 Data Ownership
   4.1 Customer retains all rights in OA texts, mapping table, and outputs
   4.2 PatentMind assigns to Customer all rights in AI outputs we may
       generate in connection with Customer's matters
   4.3 PatentMind may use AGGREGATED, ANONYMISED telemetry for service
       improvement; explicitly EXCLUDES customer text, identities, and
       any data that could be re-identified

§5 Security
   5.1 Encryption (TLS in transit; AES-256 at rest)
   5.2 SOC 2 Type II report available under NDA; refreshed annually
   5.3 ISO 27001 certificate available
   5.4 Audit-chain export on request (§8 customer right)
   5.5 Breach notification within 72 hours (matches GDPR / PDPA 2025-11)

§6 SLA
   6.1 99.5% gateway availability (measured monthly)
   6.2 Force-majeure carve-out: upstream LLM provider outage,
       sustained > 30 min, is excluded from the SLA percentage
   6.3 Service credits scale 5%-25% of monthly fee per SLA tier breach

§7 Indemnification
   7.1 PatentMind indemnifies for third-party IP claims arising from
       PatentMind's OWN intellectual property in the software
   7.2 Customer indemnifies for third-party claims arising from
       Customer's input texts or Customer's use of outputs in
       breach of §3
   7.3 Carve-out: PatentMind has NO indemnification obligation for
       Anthropic / OpenAI / model-provider output-infringement claims;
       Customer bears that risk and may purchase first-party AI
       output-IP coverage separately

§8 Audit Rights (DIFFERENTIATOR)
   8.1 Customer's compliance officer or external auditor may request,
       on 5 business days' notice, an export of audit-chain rows for
       Customer's tenant for any defined date range
   8.2 PatentMind provides a hash-chain verification utility (CLI +
       documentation) free of charge
   8.3 ANY audit-chain export is itself logged in a meta-audit row
       (verifying the verifier, per ISO 27001 cl. 9.2)

§9 Limitation of Liability
   9.1 Aggregate liability capped at fees paid in preceding 12 months
   9.2 Consequential damages excluded (including loss of patent rights,
       loss of priority date) EXCEPT to the extent caused by
       PatentMind's gross negligence or wilful misconduct
   9.3 Excludes — for clarity — Anthropic / OpenAI output liability
       (already disclaimed by upstream provider)

§10 Term and Termination
    10.1 Annual term, auto-renewing; 90-day non-renewal notice
    10.2 Customer right to terminate for breach with 30-day cure
    10.3 Data return on termination: full export of audit chain +
         mapping table (decrypt key held by customer, never by us);
         deletion certificate within 30 days

§11 Governing Law / Venue
    11.1 For TW Customers: ROC law; arbitration by 中華民國仲裁協會 (CAA)
    11.2 For US Customers: Delaware law; AAA arbitration

§12 AI-specific provisions (CRITICAL — be explicit)
    12.1 Output disclaimer: outputs may contain factual errors despite
         our grounded-citation verifier (which has a published
         precision/recall — see Schedule A)
    12.2 No legal-advice representation: PatentMind is a tool, not a
         lawyer; we make no representation that outputs constitute
         legal advice
    12.3 Bias/fairness: PatentMind acknowledges that LLMs may produce
         biased outputs; we monitor per our internal AI Acceptable Use
         Policy and publish material updates
    12.4 Disclosure obligation: PatentMind will notify Customer within
         30 days of any material change to the underlying LLM provider,
         model, or training data the provider uses; Customer may
         terminate without penalty if the change is materially adverse

§13 Vendor's Sub-processor List
    13.1 Anthropic, Inc. (model inference, US-hosted, non-training DPA)
    13.2 [digiRunner / TPIsoftware] if Customer opts in to cloud variant
    13.3 [hosting provider, e.g. AWS / GCP / Sinica HPC]
    13.4 Material change to sub-processor list: 30 days' prior notice
```

This skeleton is **not legal text**. Before any external use it must be drafted by a qualified attorney (we recommend dual TW + DE counsel).

---

## 6. Certification & Audit Roadmap (24 months)

The matrix below estimates **cost, calendar effort, AND likely sales lift** per certification — the latter from our research-derived view of what enterprise legal procurement teams demand.

| Cert | Cost (USD) | Calendar | Effort (FTE-months) | Sales lift (qualitative) | Recommended timing |
|---|---|---|---|---|---|
| **SOC 2 Type II** (single Trust Service Criterion = Security) | $30k-$60k incl. audit firm | 6 mo prep + 6 mo observation + 1 mo report = ~13 mo | 4-6 | **Massive.** Required by ~every US enterprise-tier law firm procurement team[^26]. Without it, AmLaw 100 conversations don't start. | START NOW (T+0 to T+13) |
| **SOC 2 Type II** (full 5 TSC: Security + Availability + Processing Integrity + Confidentiality + Privacy) | $60k-$120k | T+13 to T+18 (add 5 mo to extend scope) | 2-3 | High for privacy-conscious firms. The "Confidentiality" criterion is the key one for legal-AI procurement. | T+13 → T+18 |
| **ISO 27001:2022** | $20k-$40k incl. audit body fees | 6-9 mo[^27] | 3-4 | High in TW + EU; required by some IPBA / AIPLA-affiliated firms. Significantly overlaps SOC 2 — start one, reuse 70%+ for the other.[^27] | T+6 → T+15 (parallel with SOC 2) |
| **ISO/IEC 42001:2023** (AI MS) | $20k-$60k[^25] | 4-9 mo from start; faster if 27001 already done[^25] | 2-4 | **Emerging differentiator.** AI-only vendors are starting to win procurement bake-offs on 42001. Patlytics already has it[^22]. **As of 2026-06, 42001 is the single fastest-moving differentiator.** | T+15 → T+22 |
| **TW BSI CNS 27001** | Modest add to ISO 27001 | Concurrent with ISO 27001 | 0.5 | Required by TW 公務機關 contractors; nice-to-have for private firms. | T+13 (file with BSI when ISO 27001 issued) |
| **USPTO Practitioner-Vetted Vendor list** | Free | N/A | 0 | The USPTO does NOT maintain a practitioner-vendor accreditation list as of 2026-06 (per our research). USPTO guidance is rule-based, not vendor-list-based. Re-check 2026-Q4. | Monitor |
| **TIPO 認證 for AI tools** | N/A | N/A | 0 | Per our research, TIPO does NOT operate an AI-tool registration scheme. The closest is the *人工智慧基本法*'s risk-classification framework being built by 數位部 per §16[^11], not yet operationalised as of 2026-06. | Monitor; engage 數位部 working group |
| **Singapore IPOS AI tool registration** | N/A | N/A | 0 | IPOS does not maintain an AI-tool registry as of 2026-06; Singapore's AI governance is principles-based under the Model AI Governance Framework. | Monitor |
| **EU AI Act — General Purpose AI Code of Practice signatory** (voluntary) | Staff time | Self-attestation | 1 | Low for legal-AI specifically (not GPAI provider); but signatory status signals seriousness. | T+18+ if EU customers materialise |

### 24-month sequenced pipeline

```
T+0          T+6          T+12         T+18         T+24
│            │            │            │            │
├─ SOC 2 Type II prep (6 mo) ──┤
│            ├─ SOC 2 observation (6 mo) ──┤
│            │            ├─ SOC 2 Type II report ✓
│            │            │
│            ├─ ISO 27001 (T+6→T+15) ────┤
│            │            │   ✓
│            │            │
│            │            ├─ SOC 2 full 5-TSC (T+13→T+18) ──┤ ✓
│            │            │            │
│            │            │            ├─ ISO 42001 (T+15→T+22) ──┤ ✓
│            │            │            │            │
│            │            │            │            ├─ EU AI Act
│            │            │            │            │   GPAI CoP
│            │            │            │            │   (T+22)
```

**Estimated all-in 24-month cert cost:** $130k - $280k (audit fees + consultant fees + internal effort proxy). Realistic plan for a 5-person engineering team: 2 founders + 1 engineer rotate through compliance work part-time, supplemented by a fractional CISO ($3-5k/mo retainer).

---

## 7. Regulatory Horizon Scan (12-24 months)

### 7.1 EU AI Act

The Act entered force 2024-08-01[^6]. Implementation timeline relevant to us:
- **2025-02-02:** prohibited practices + AI literacy obligations in force.[^6]
- **2025-08-02:** GPAI model obligations in force.[^6]
- **2026-08-02:** **originally** the high-risk system date. Per the **EU AI Act Omnibus (provisional political agreement 2026-05-07)**[^6a], Annex III high-risk system deadlines deferred to **2027-12-02**. Annex I embedded systems deferred to 2028-08-02.

**Does PatentMind fall into a high-risk Annex III category?** Annex III covers (a) biometric identification; (b) critical infrastructure; (c) education; (d) employment / HR; (e) essential services access; (f) law enforcement; (g) migration / border; (h) administration of justice and democratic processes. **Annex III(h) is the question:** is patent-prosecution AI "administration of justice"? The literal text talks about "AI intended to assist a judicial authority in researching and interpreting facts and the law and in applying the law" — a *patent office* is an administrative agency, not a judicial authority in the traditional sense. We assess: **probably not Annex III, but the Commission has discretion to add categories**. Worst case, the 2027-12-02 deadline gives us 18 months to prepare; ISO 42001 compliance pre-positions us well[^25].

### 7.2 US Federal — post-Biden EO 14110

EO 14110 was rescinded 2025-01-20[^8]. The Trump "Removing Barriers to American Leadership in AI" EO (2025-01-23) and follow-ons (June 2025 amendment, July 2025 AI Action Plan, November 2025 Genesis Mission)[^8] signal a deregulatory federal posture. **For legal-AI specifically, this means:**
- No federal AI-product registration regime expected near-term.
- NIST AI Risk Management Framework remains voluntary but is the de-facto baseline US enterprise procurement uses; our SOC 2 + ISO 27001 + ISO 42001 stack maps to the NIST AI RMF "Govern / Map / Measure / Manage" functions.
- State-level activity (CA SB 1047 attempts; Colorado AI Act 2024 in force from 2026; Texas TRAIGA 2025) is the active layer. **Colorado AI Act 2026** specifically may have disclosure requirements for "high-risk AI" used in employment, healthcare, financial, insurance, legal-services contexts — *legal services* is in the consumer-protection scope. We will monitor and adjust the §1.5 disclosure if required.

### 7.3 TW 人工智慧基本法

Passed 三讀 on 2025-12-23, effective 2026-Q3 (subordinate regulations under development by 國科會 + 數位部 as of 2026-06)[^11]. Key provisions for us:
- §3 designates 國科會 as central authority + 數位部 for digital domain.
- §4 enumerates 7 governance principles: 永續發展與福祉, 人類自主, 隱私保護與資料治理, 資安與安全, 透明與可解釋, 公平與不歧視, 問責.[^11] **All seven map to existing PatentMind invariants** — we'll ship a one-page mapping doc as marketing collateral.
- §16 directs 數位部 to build a **risk-classification framework**.[^11] Legal-AI is not pre-classified high-risk in the statute; subordinate regs will decide. **Action item:** monitor 數位部 risk-classification consultations Q3-Q4 2026 and submit comments if legal-AI is proposed for high-risk treatment.
- §13 covers data-sharing / governance — relevant if 國科會 starts subsidising AI-training on government corpora.

### 7.4 TIPO incoming rules

TIPO's 2024-12 公告 confirmed an AI-related-patent analysis with examination implications.[^16a] No vendor-side rules issued or announced; TIPO is following the JPO model (advisor program, case studies) rather than the EU's regulatory model.[^16a] **Probability of TIPO requiring vendor disclosure for AI-assisted filings:** low for 2026; possible 2027 if AIPLA/IPBA push for harmonisation.

### 7.5 ABA Formal Opinion updates

ABA Standing Committee on Ethics has signalled more opinions coming on AI-specific fee-billing, conflict-checking, and remote-attorney supervision. Watch the 2026-Q3 and 2027-Q1 cycles.

### 7.6 Net horizon assessment

Of the things that could break the product in 12-24 months:
- **Highest probability + highest impact:** TW 數位部 risk-classification frames legal-AI as 高風險 in the 人工智慧基本法 subordinate regs → triggers conformity-assessment requirements analogous to EU AI Act. **Mitigation:** ISO 42001 pre-emptively.
- **Lower probability + high impact:** Colorado-style state law adopted by NY or CA explicitly regulating legal-AI tools as covered consumer-protection products. **Mitigation:** disclosure clause + audit chain + zero-training already make us substantially compliant.
- **Higher probability + medium impact:** ABA or NY State Bar issues an opinion holding that boilerplate engagement-letter consent is insufficient for *patent-specific* AI use (because of the inventorship 35 USC 116 angle). **Mitigation:** our §1.5 clause is already specific, not boilerplate.

### 7.7 Of things that could unlock the product

- ISO 42001 becoming a sales-procurement default by 2027-Q2 (likely). We want our cert in hand by then.
- EU AI Act's Annex IV Code of Practice for GPAI providers cascading into preferred-vendor language used by EU clients — improbable but possible.
- A USPTO "trusted-vendor" registry analogous to FedRAMP — repeatedly rumoured but not announced as of 2026-06.

---

## 8. Audit-Trail-as-Compliance Positioning (the differentiator)

This is the section we cite in customer sales calls. The thesis: **PatentMind's three core invariants (CLAUDE.md §4 #3 mandatory redaction, #4 audit row per request, #7 confidential auto-routing) operationalise specific clauses of every major rule we touch.** Each invariant pulls multiple cert clauses' weight at once.

### Mapping matrix

| PatentMind invariant | ABA Rule 1.6 + Op 512 | ISO 27001:2022 | ISO 42001:2023 | TW PDPA §27 / cl. 20-1 | TW 人工智慧基本法 §4 |
|---|---|---|---|---|---|
| **#3 Mandatory redaction before LLM call** | Confidentiality preserved by minimising data sent to a third-party processor; informed-consent threshold lowered (Op 512 §III) because de-identified data is processed[^1] | Annex A.5.34 PII protection; A.8.10 information deletion | Annex B.5 lifecycle data governance; B.6 third-party data use | 適當之安全措施 §27(1)(b) — 界定個人資料之範圍; minimisation principle | 隱私保護與資料治理 |
| **#4 Audit row per request (hash-chained)** | Documentation duty (Op 512 §V: "documented adequate safeguards")[^1] + Rule 1.15 record-keeping | **Cl. 7.5 documented information** + **cl. 9.2 internal audit** + Annex A.5.27 logging[^28][^29] | **Cl. 7.5 documented information** + B.6.2.4 traceability of AI decisions[^25] | §27(1)(j) 使用紀錄、軌跡資料及證據保存[^13] | 透明與可解釋 + 問責 |
| **#7 Confidential auto-routing → local LLM** | Op 512 §III: informed-consent threshold can be met by *not* sending to third party for sensitive matters[^1] | Annex A.5.31 data classification + A.8.12 data leakage prevention | B.6.2.6 explainability + B.7 third-party AI use | §21 cross-border restriction self-imposed[^12] | 資安與安全 + 人類自主 |
| **#3+#4 combined (redacted text logged but reversible only on-prem)** | Maintains privilege chain-of-custody; counters waiver argument in *Heppner / Warner*[^21] | A.5.33 records protection + A.8.24 cryptography | B.6.2.2 input/output documentation | §27(1)(k) 整體持續改善 | 問責 |

### Concrete clause-by-clause walk

**ISO 27001 cl. 7.5 (Documented Information)[^28]:** requires the organisation to "create and maintain documented information necessary for effective ISMS operation," with strict control over versioning, access, and retention.
- Our `audit.py` rows are SHA-256-hash-chained (prev_row_hash links every row → previous row → genesis), append-only via SQLite triggers, scoped to tenant. The hash chain provides tamper-evidence: any modification breaks the chain at the point of tampering. The chain plus our `verify_chain()` walker is *exactly* the "documented information that is correct, complete, and protected" cl. 7.5 demands.
- **Gap:** documentation about the documentation. We need a written *Records Control Procedure* document. P1 deliverable.

**ISO 27001 cl. 9.2 (Internal Audit)[^29]:** requires planned-interval internal audits to verify ISMS conformance and effectiveness.
- The audit log itself is the *data feed* for the internal audit. The `AuditView.jsx` SPA component lets the firm's compliance officer (or our internal auditor) review event history and verify the chain.
- **Gap:** we need a quarterly internal audit schedule and a documented audit report template. P1 deliverable (sales-engineering rather than R&D).

**ISO 42001 (AI Management Systems, 2023)[^25]:** introduces controls specific to AI: Annex B.6 (lifecycle), B.7 (third-party AI), B.8 (data quality), B.9 (information for interested parties).
- B.6.2.2 (data for development and continuous learning), B.6.2.4 (system documentation), B.6.2.5 (logging) are addressed by our audit chain + prompt-YAML externalisation (`backend/ai_engine/prompts/*.yaml`) + RAG-index versioning.
- B.7 (third-party AI) is addressed by our Anthropic DPA + the sub-processor list in the ToS skeleton (§5.1 above).
- **Strong overlap with ISO 27001** — if we have 27001 first, ~70% of 42001 controls are pre-built.[^25]

**TW PDPA §27 / cl. 20-1 (2025-11 amendment)[^13]:** "適當之安全措施" — enumerated examples include (a) 配置管理人員及相當資源, (b) 界定個人資料之範圍, (c) 風險評估及管理機制, (d) 事故之預防、通報及應變機制, (e) 內部管理程序, (f) 資料安全管理及人員管理, (g) 教育訓練, (h) 設備安全管理, (i) 稽核機制, (j) 使用紀錄、軌跡資料及證據保存, (k) 整體持續改善.
- Our architecture and our cert roadmap together hit every one of (a) through (k). The audit chain alone covers (j). The redaction step covers (b) and contributes to (c). The cert program covers (a), (e), (f), (g), (i), (k). Incident-response (d) is the visible gap — P0 to write the IR playbook.

**TW 人工智慧基本法 §4[^11]:** "永續發展與福祉、人類自主、隱私保護與資料治理、資安與安全、透明與可解釋、公平與不歧視、問責."
- 人類自主: confidential cases never go to autonomous cloud LLM (#7); attorney review is mandatory (#4 documents it).
- 隱私保護與資料治理: redaction (#3) + mapping table on-prem (CLAUDE.md §9).
- 資安與安全: cert program + SOC 2 + ISO 27001.
- 透明與可解釋: audit chain (#4) + grounded-citation verifier (#5) + per-citation provenance in `DraftEditor.jsx`.
- 公平與不歧視: model behaviour monitored; per ToS §12.3 (above) we acknowledge LLM bias and have an internal monitoring policy.
- 問責: audit chain + assignable user_id per row + the attorney-of-record's 11.18(b) duty.

**ABA Op 512 §III (Confidentiality)[^1]:** "lawyers are responsible for knowing how GAI uses data and putting in place adequate safeguards." Our redaction + zero-training DPA + audit chain + confidential routing = "adequate safeguards" pattern that a hearing-bound bar disciplinary committee would find documented and reasonable.

### Why this is sales ammo

Most legal-AI vendors say "we're secure" and gesture at SOC 2 in PowerPoint. PatentMind says: "here's the architectural invariant, here's the audit row format, here's the SHA-256 hash chain, here's the verify utility, here's the clause-by-clause mapping to ISO 27001 cl. 7.5 / 9.2 and ISO 42001 B.6.2.4 and PDPA §27 (k), and here's a sample export from a real audit chain." That's a different conversation.

---

## 9. End report (≤ 400 words)

### Top 3 things that block sales tomorrow

1. **No SOC 2 Type II report.** Every US enterprise legal procurement team asks first; without it the conversation does not start[^26]. Mitigation: launch SOC 2 prep at T+0; first report at T+13. Bridge during prep: offer a SOC 2 Type I report (~$15k, 8 weeks) and our internal audit walkthrough.
2. **No published vendor ToS with the §5.1 skeleton fleshed out as legal text.** The customer's GC will want to redline the indemnification, LoL ceiling, and audit-rights clauses before pilot. Mitigation: TW + DE counsel draft sprint, 4 weeks, ~$25k. Without this, every prospect's procurement spins on a one-off MSA.
3. **No customer-facing engagement-letter clause.** Prospects ask "what do we put in our retainer to disclose AI use?" If we say "talk to your GC" they stall. The §1.5 bilingual sample above closes that gap *today*; we should publish it as a one-page PDF on the sales site, marked "sample only, requires GC review."

### Top 3 things to fix in 12 months

1. **Audit-chain gaps (SECURITY_AUDIT H-4 + H-7):** cross-tenant verify + error-path audit-row writes. These are the differences between "we have an audit chain" and "we pass ISO 27001 cl. 7.5 / 9.2 audit." Estimated 12 engineer-days.
2. **Incident-response (IR) playbook + breach-notification automation.** PDPA 2025-11 amendment requires 72-hour notification[^12a]; GDPR same; we have neither a playbook nor a tested rehearsal. PDPA §27 (d) explicitly enumerates 事故之預防、通報及應變機制 as an "適當之安全措施" component[^13]. 4-6 weeks with fractional CISO.
3. **ISO 42001 certification process.** Mid-2027 is the window where 42001 stops being a differentiator and starts being table stakes. Start prep T+9, certify by T+22. Even before cert, publish a public 42001-readiness statement.

### Single biggest "we'd be sued if this happened" risk

A confidential case (one marked or that should have been marked CASE-*-CONF) being **sent to Anthropic in the US in plaintext** because (a) the case was mis-classified at intake, (b) the routing rule had a code path that bypassed the assert, or (c) a third-party integration (Phase 3 Dify workflow) skipped the IF/ELSE branch. This is simultaneously a Rule 1.6 confidentiality breach[^1], a PDPA §21 cross-border violation potentially triggering 個資會 enforcement[^12], a privilege waiver under the *Heppner / Warner* line[^21], and a customer-side malpractice / breach-of-engagement-letter claim. Our defence is the triple-redundancy in CLAUDE.md §4 invariant 7 + `llm_client.py:556-563` defensive assert + Phase 3 Dify IF/ELSE branch, plus the audit-chain row that records `policy_decisions["local_llm_used"]` for every confidential request. The remaining residual risk is a misclassification at intake — addressed by mandatory dual-attorney sign-off on the case-confidentiality designation, which is a customer-side process and goes into the engagement-letter and the customer-onboarding training.

---

## Footnotes

[^1]: ABA Standing Committee on Ethics & Professional Responsibility, *Formal Opinion 512: Generative Artificial Intelligence Tools* (2024-07-29). https://www.americanbar.org/news/abanews/aba-news-archives/2024/07/aba-issues-first-ethics-guidance-ai-tools/ and PDF: https://www.lawnext.com/wp-content/uploads/2024/07/aba-formal-opinion-512.pdf
[^2]: New York City Bar Association Committee on Professional Ethics, *Formal Opinion 2024-5: Ethical Obligations of Lawyers and Law Firms Relating to the Use of Generative Artificial Intelligence* (2024-08-07). https://www.nycbar.org/reports/formal-opinion-2024-5-generative-ai-in-the-practice-of-law/ ; PDF: https://www.nycbar.org/wp-content/uploads/2024/08/20221329_GenerativeAILawPractice.pdf
[^3]: California State Bar Standing Committee on Professional Responsibility and Conduct (COPRAC), *Practical Guidance for the Use of Generative Artificial Intelligence in the Practice of Law* (approved 2023-11-23; revised 2026-05-14). https://www.calbar.ca.gov/sites/default/files/portals/0/documents/ethics/Generative-AI-Practical-Guidance.pdf ; March 2026 amendment proposals: https://www.calbar.ca.gov/public/public-meetings-comment/public-comment/public-comment-archives/2026-public-comment/proposed-amendments-rules-professional-conduct-related-artificial-intelligence
[^4]: Florida Bar, *Ethics Opinion 24-1* (2024-01-19). https://www.floridabar.org/the-florida-bar-news/proposed-advisory-opinion-24-1-regarding-lawyers-use-of-generative-artificial-intelligence-official-notice/ ; analysis: https://www.hinshawlaw.com/newsroom-updates-lfp-florida-bar-advisory-opinion-generative-ai-lawyers-ethical-caveats.html
[^5]: USPTO, *Guidance on Use of Artificial Intelligence-Based Tools in Practice Before the United States Patent and Trademark Office* (2024-04-11), 89 FR 25609. https://www.federalregister.gov/documents/2024/04/11/2024-07629/guidance-on-use-of-artificial-intelligence-based-tools-in-practice-before-the-united-states-patent ; USPTO announcement: https://www.uspto.gov/about-us/news-updates/uspto-issues-guidance-concerning-use-ai-tools-parties-and-practitioners
[^6]: EU Commission, *AI Act: Implementation Timeline*. https://ai-act-service-desk.ec.europa.eu/en/ai-act/timeline/timeline-implementation-eu-ai-act ; full implementation tracker: https://artificialintelligenceact.eu/implementation-timeline/
[^6a]: EU AI Act Omnibus political agreement, 2026-05-07 (reported via Cloud Security Alliance research note). https://labs.cloudsecurityalliance.org/research/csa-research-note-eu-ai-act-high-risk-compliance-deadline-20/
[^7]: DC Bar Ethics Opinion 388 (June 2024), summarised in https://www.americanbar.org/groups/business_law/resources/business-law-today/2024-october/aba-ethics-opinion-generative-ai-offers-useful-framework/
[^8]: *Trump Administration Issues Executive Order on Federal AI Policy Framework and State Law Pre-emption* (William Fry analysis): https://www.williamfry.com/knowledge/trump-administration-issues-executive-order-on-federal-ai-policy-framework-and-state-law-pre-emption/ ; Skadden post-rescission analysis: https://www.skadden.com/insights/publications/executive-briefing/ai-broad-biden-order-is-withdrawn ; July 2025 AI Action Plan: https://www.dwt.com/blogs/artificial-intelligence-law-advisor/2025/07/trump-ai-action-plan-infrastructure
[^9]: 行政院, *行政院及所屬機關（構）使用生成式AI參考指引* (民國112-10-03訂定). https://www.ey.gov.tw/Page/448DE008087A1971/40c1a925-121d-4b6b-8f40-7e9e1a5401f2 ; 國科會 全文: https://www.nstc.gov.tw/nstc/attachments/da74d556-5b1b-4cbd-9015-901cce87ff91
[^11]: 立法院 三讀通過《人工智慧基本法》(2025-12-23). 法源法律網: https://www.lawbank.com.tw/news/NewsContent.aspx?NID=211670.00 ; 數位部 新聞發布: https://moda.gov.tw/press/press-releases/18316 ; 國科會 新聞: https://www.nstc.gov.tw/folksonomy/detail/ed981806-1852-4b63-8dfd-9eea04157971?l=ch ; 條文分析: https://aiacademy.tw/news-ai-fundamental-act-futurecity/
[^11a]: 中華民國律師公會全國聯合會, *律師倫理規範* (民國72-12-18 通過; 多次修正). https://www.twba.org.tw/upload/content/20250625/c6aa5413303d4a7ebb23ab8f8b86a649/c6aa5413303d4a7ebb23ab8f8b86a649.pdf ; per our 2026-06 search, no AI-specific 公會 opinion published.
[^12]: 個人資料保護法 §21 (international transfer restriction). 全國法規資料庫: https://law.moj.gov.tw/LawClass/LawAll.aspx?PCode=I0050021 ; 跨境 AI 傳輸風險分析: https://www.headinglawyer.com/HD/2026/05/10/ai-%E6%B3%95%E5%BE%8B-3-ai-%E8%88%87%E5%80%8B%E8%B3%87%E6%B3%95%E6%A8%A1%E5%9E%8B%E8%A8%93%E7%B7%B4%E3%80%81%E8%B3%87%E6%96%99%E8%92%90%E9%9B%86%E3%80%81%E8%B7%A8%E5%A2%83%E5%82%B3%E8%BC%B8/
[^12a]: 2025-11 PDPA amendment (個資會 監管權限 / breach notification). 法源法律網: https://www.lawbank.com.tw/news/NewsContent.aspx?NID=211099.00 ; 個資會 籌備處: https://www.pdpc.gov.tw/
[^13]: 個資法 §27 安全維護義務 + 個資會 籌備處 解釋. https://www.pdpc.gov.tw/News_Content/188/834/ ; 條文及解釋: https://www.pdpc.gov.tw/News_Content/100/314/ ; 全國法規資料庫 條文: https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=I0050021&flno=27
[^13a]: 金融監督管理委員會 指定非公務機關個人資料檔案安全維護辦法 (sector implementation example). https://law.fsc.gov.tw/LawContent.aspx?id=GL000933
[^14]: *AI Hallucinations in Court Filings: A 2025 Review of Sanctions* — Sterne Kessler. https://www.sternekessler.com/news-insights/insights/ai-ip-year-in-reviewai-hallucinations-in-court-filings-and-orders-a-2025-review-of-sanctions-across-the-courts-and-rule-proposals/ ; Lexos Media v. Overstock (D. Kan.) reporting: https://www.abajournal.com/news/article/judge-orders-patent-attorneys-to-explain-ai-hallucinated-citations ; USPTO Director Vidal Feb 2024 memo coverage: https://www.foley.com/insights/publications/2024/02/uspto-warns-against-blind-reliance-artificial-intelligence/
[^15]: ABA Model Rule 5.3 + 2012 title amendment + Op 512 §VI analysis. https://www.fishmanhaygood.com/resources/ethical-rules-for-using-generative-ai-in-your-practice-model-rule-5-supervision-of-associates-and-non-lawyer-assistance/ ; https://www.letsaskclaire.com/legal/aba-model-rules-ai-compliance
[^16]: 中華民國專利師公會 *專利師執業倫理規範* (公會規章). https://www.twpaa.org.tw/about/about.asp?id=9 ; 專利師法 全國法規資料庫: https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=J0070034
[^16a]: TIPO, *我國人工智慧相關專利申請概況及申請人常見核駁理由分析* (2024-12 公告). https://www.tipo.gov.tw/tw/cp-85-859330-1189b-1.html ; 北美智權報 401期 USPTO/TIPO AI 指引比較: https://naipnews.naipo.com/43721/
[^17]: 律師法 (latest): https://law.moj.gov.tw/LawClass/LawAll.aspx?PCode=I0020006 ; 律師保密義務分析: https://markliu.org/legalethics5.pdf ; 律師對當事人保密義務 法觀人月刊 209: https://lawyer.get.com.tw/File/PDF/%E6%B3%95%E8%A7%80%E4%BA%BA/406406_%E6%A2%81%E5%BE%8B%E5%B8%AB%E7%B7%A8%E8%91%97%E6%B3%95%E5%BE%8B%E5%80%AB%E7%90%86%E5%AD%B8.pdf
[^18]: 專利師法 §12 + §35 懲戒. https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=J0070034
[^19]: *Does your professional liability insurance cover AI mistakes?* — ABA Journal (2025). https://www.americanbar.org/groups/journal/articles/2025/does-your-professional-liability-insurance-cover-ai-mistakes-dont-be-so-sure/ ; ABA Tort Trial & Insurance Practice — *The Evolving Landscape of AI Insurance*: https://www.americanbar.org/groups/tort_trial_insurance_practice/resources/brief/2025-fall/evolving-landscape-ai-insurance-empirical-insights-risks-policy-gaps/ ; Vouch AI / CNA discussion: https://legalaigovernance.com/resources/ai-liability-insurance/
[^20]: *AI, Privilege, and Work Product: The Current Legal Landscape and Practical Guidance* — Akerman LLP. https://www.akerman.com/en/perspectives/ai-privilege-and-work-product-the-current-legal-landscape-and-practical-guidance.html ; Perkins Coie on *Heppner / Warner / Gilbarco*: https://perkinscoie.com/insights/update/heppner-and-gilbarco-courts-apply-privilege-and-work-product-protection-generative
[^21]: K&L Gates, *Litigation Minute: Generative AI Data, Attorney-Client Privilege, and the Work-Product Doctrine* (2026-02-23). https://www.klgates.com/Litigation-Minute-Generative-AI-Data-Attorney-Client-Privilege-and-the-Work-Product-Doctrine-2-23-2026 ; White & Case overview: https://www.whitecase.com/insight-alert/attorney-client-privilege-and-work-product-age-generative-ai
[^22]: Patlytics Terms of Service: https://www.patlytics.ai/tos ; coverage analysis (data ownership, training, output): https://www.patlytics.ai/
[^23]: *China Officially Promulgates New Cross-Border Data Transfer Requirements* — Benesch (2024-03 reform analysis). https://www.beneschlaw.com/resources/china-officially-promulgates-new-cross-border-data-transfer-requirements.html ; Clifford Chance briefing: https://www.cliffordchance.com/content/dam/cliffordchance/briefings/2024/03/Client%20Briefing%20-%20China%20Revamps%20its%20Rules%20on%20Cross-border%20Data%20Transfer.pdf
[^24]: USPTO, *Revised Inventorship Guidance for AI-Assisted Inventions* (2025-11-28). https://www.federalregister.gov/documents/2025/11/28/2025-21457/revised-inventorship-guidance-for-ai-assisted-inventions ; USPTO portal: https://www.uspto.gov/subscription-center/2025/revised-inventorship-guidance-ai-assisted-inventions
[^24a]: Venable LLP, *The § 101 Reset for 2026: New USPTO Guidance on AI Eligibility* (2025-12 USPTO memo coverage). https://www.venable.com/insights/publications/2025/12/the-101-reset-for-2026
[^25]: ISO/IEC 42001:2023 — *Information technology — Artificial intelligence — Management system*. https://www.iso.org/standard/42001 ; cost / timeline: https://elevateconsult.com/insights/iso-42001-certification-timeline-budget-for-founders/ ; Vanta breakdown: https://www.vanta.com/collection/iso-42001/iso-42001-certification-cost ; structural overlap with ISO 27001: https://certbetter.com/blog/iso-42001-cost-what-ai-certification-actually-costs-in-2026
[^25a]: ClaimMaster product profile (on-prem patent proofreading tool — useful comparable). https://www.patentclaimmaster.com/ ; FAQ (on-prem security claim): https://www.patentclaimmaster.com/CMFAQ.html ; pricing/profile: https://www.softwareadvice.com/legal/claimmaster-profile/
[^26]: *Why Law Firms Should Only Work with SOC 2 Type II MSPs* — Onward Technologies: https://onwardtek.com/blog/law-firms-soc-2-type-ii-msp/ ; *Data Security in Legal AI: What to Know Before You Sign* — GC AI: https://gc.ai/blog/data-security-ai-legal-tech ; enterprise procurement perspective: https://sanalabs.com/agents-blog/enterprise-legal-ai-agents-law-firms-2025
[^27]: ISO 27001 + ISO 42001 reuse pattern. https://bastion.tech/learn/iso42001/certification-cost/ ; Polimity walkthrough: https://polimity.com/blog/iso-42001-certification-steps-cost-and-timelines-for-ai-compliance/
[^28]: ISO 27001:2022 Clause 7.5 (Documented Information). https://www.isms.online/iso-27001/requirements-2022/7-5-documented-information-2022/ ; DataGuard explainer: https://www.dataguard.com/iso-27001/clause-7-5-documented-information/
[^29]: ISO 27001:2022 Clause 9.2 (Internal Audit). https://hightable.io/iso-27001-clause-9-2-internal-audit/ ; WatchDog guide: https://watchdogsecurity.io/iso-27001/general-internal-audit

---

*End of legal/compliance roadmap. Doc owner: founders (until GC hire T+6). Refresh cadence: quarterly OR within 30 days of any material rule change (ABA, USPTO, TIPO, 國科會, EU AI Act subordinate regs, TW PDPA implementing rules). Next scheduled review: 2026-09-05.*
