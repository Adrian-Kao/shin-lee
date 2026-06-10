// Shared Playwright route interceptors for the PatentMind SPA.
//
// The frontend talks to the gateway via the `/api/*` prefix (Vite proxies to
// :8010 in dev; CI does not run a backend at all). Each helper installs a
// `page.route()` that fulfils the request from a fixture so tests stay
// hermetic and finish in milliseconds.
//
// Every helper accepts the same Playwright `page` argument and returns either
// a Promise (when capture is requested) or void. Helpers are idempotent — call
// them in any order before the test navigates so the route is in place when
// the first request fires.

/**
 * Canonical demo identities (mirrors backend/gateway/auth.py _USERS).
 * Tests can override fields by spreading: { ...DEMO_USERS.alice, role: 'admin' }
 */
export const DEMO_USERS = {
  alice: {
    token: 'fake-token-alice',
    user_id: 'alice',
    tenant_id: 'tenant_a',
    role: 'attorney',
    display_name: 'Alice',
  },
  bob: {
    token: 'fake-token-bob',
    user_id: 'bob',
    tenant_id: 'tenant_a',
    role: 'paralegal',
    display_name: 'Bob',
  },
  carol: {
    token: 'fake-token-carol',
    user_id: 'carol',
    tenant_id: 'tenant_b',
    role: 'it_admin',
    display_name: 'Carol',
  },
  audit_dave: {
    token: 'fake-token-dave',
    user_id: 'audit_dave',
    tenant_id: 'tenant_a',
    role: 'auditor',
    display_name: 'Dave',
  },
};

/**
 * Mock POST /api/v1/auth/login. If `user` is the name of a demo user
 * (alice/bob/carol/audit_dave), return that fixture; otherwise treat `user`
 * as a full session object. To simulate failure, pass `{ status, body }`.
 */
export async function mockLogin(page, user, opts = {}) {
  const session =
    typeof user === 'string'
      ? DEMO_USERS[user]
      : user && typeof user === 'object' && user.user_id
        ? user
        : DEMO_USERS.alice;
  await page.route('**/api/v1/auth/login', (route) => {
    if (opts.status && opts.status >= 400) {
      route.fulfill({
        status: opts.status,
        contentType: 'application/json',
        body: JSON.stringify(opts.body ?? { detail: 'unauthorized' }),
      });
      return;
    }
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(session),
    });
  });
}

/** Stable default for /api/v1/quota — used after a successful login. */
export function defaultQuota(overrides = {}) {
  return {
    user_daily_used: 1500,
    user_daily_limit: 100000,
    tenant_monthly_used: 45000,
    tenant_monthly_cap: 5000000,
    circuit_breaker: {
      current_usd: 1.23,
      threshold_usd: 50,
      tripped: false,
    },
    ...overrides,
  };
}

export async function mockQuota(page, quota = defaultQuota()) {
  await page.route('**/api/v1/quota**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(quota),
    });
  });
}

/**
 * Build a minimal analysis fixture with `n` rejections (default 1).
 * Anything in `overrides` is shallow-merged after.
 */
export function defaultAnalysisResponse(overrides = {}) {
  return {
    request_id: '00000000-0000-0000-0000-deadbeef0001',
    oa: {
      oa_id: 'OA-2025-001',
      case_id: 'CASE-2025-001',
      tenant_id: 'tenant_a',
      received_date: '2025-04-15T00:00:00Z',
      deadline: '2025-07-15T00:00:00Z',
      raw_text_hash: 'a'.repeat(64),
      rejections: [
        {
          rejection_id: 'REJ-1',
          rejection_type: '103_obviousness',
          affected_claims: [1, 2, 3],
          cited_prior_art: ['US7654321', 'US6543210'],
          examiner_argument:
            'The combination of microchannels with non-uniform cross-section ' +
            'and copper construction yields predictable results.',
          confidence: 0.87,
        },
      ],
    },
    drafts: [
      {
        rejection_id: 'REJ-1',
        strategy:
          '主張 cited prior art US7654321 並未揭露非均勻截面，' +
          '組合教示不具動機。 [GROUNDED_REF_1]',
        draft_text:
          'Applicant respectfully traverses. The cited reference [GROUNDED_REF_1] ' +
          'does not teach a non-uniform cross-section microchannel as recited in ' +
          'claim 1.',
        grounded_citations: ['[GROUNDED_REF_1]'],
        confidence: 0.82,
        requires_attorney_review: true,
      },
    ],
    related_prior_art: [
      {
        patent_no: 'US7654321',
        section: 'claim_1',
        text:
          'A heat exchanger having a plurality of microchannels with uniform ' +
          'rectangular cross-section, fabricated from aluminum.',
        score: 0.913,
        metadata: {},
      },
      {
        patent_no: 'US6543210',
        section: 'spec_para_12',
        text:
          'Copper provides superior thermal conductivity in heat-transfer ' +
          'applications.',
        score: 0.781,
        metadata: {},
      },
    ],
    deadline_summary: {
      received_date: '2025-04-15T00:00:00Z',
      statutory_deadline: '2025-07-15T00:00:00Z',
      recommended_internal_deadline: '2025-07-08T00:00:00Z',
      days_remaining: 42,
      holiday_calendar_version: '2025.1',
      warnings: [],
    },
    cost_meta: {
      prompt_tokens: 1234,
      completion_tokens: 567,
      model: 'mock-llama3.1:8b',
      estimated_cost_usd: 0.0,
      cache_hit: false,
    },
    ...overrides,
  };
}

/**
 * Mock POST /api/v1/oa/analyze.
 *
 * - `response`: payload object OR `{ status, body }` for an error.
 * - Returns a Promise (assigned to `.capture` on the returned object) that
 *   resolves with the captured request body on first fire. Awaiting the
 *   function call itself only installs the route — the capture promise must
 *   be retrieved separately so callers don't accidentally block forever.
 *
 * Usage:
 *   await mockAnalyze(page);           // install only
 *   const captured = mockAnalyze(page).capture;  // capture later
 *   // ...or grab the promise inline without awaiting the install:
 *   const captured = mockAnalyze(page).capture;
 */
export function mockAnalyze(page, response = defaultAnalysisResponse()) {
  let resolveCapture;
  const capture = new Promise((r) => {
    resolveCapture = r;
  });
  // Fire-and-forget the route install. Playwright queues the route handler
  // before any subsequent action because page.route() is synchronous on the
  // client and the browser-side wiring lands in the same tick.
  const installed = page.route('**/api/v1/oa/analyze', (route) => {
    let body = null;
    try {
      body = route.request().postDataJSON();
    } catch {
      body = route.request().postData();
    }
    resolveCapture(body);
    if (response && response.status && response.status >= 400) {
      route.fulfill({
        status: response.status,
        contentType: 'application/json',
        body: JSON.stringify(response.body ?? { detail: 'server error' }),
      });
      return;
    }
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(response),
    });
  });
  // Make the returned value awaitable AND carry the capture promise. The
  // awaited path returns the install promise (resolves quickly); callers
  // that need to assert on the request body read `.capture` instead.
  installed.capture = capture;
  return installed;
}

/**
 * Mock POST /api/v1/oa/export (Q16 sign-off gate). Mirrors the real backend:
 * if the request body's `attorney_signoff` is not exactly true, respond 409
 * (the hard gate). Otherwise respond 200 with an assembled document built from
 * the accepted segments. Returns `{ capture }` — a promise resolving with the
 * first captured request body — so specs can assert on what was sent.
 */
export function mockExportDraft(page, opts = {}) {
  let resolveCapture;
  const capture = new Promise((r) => {
    resolveCapture = r;
  });
  const installed = page.route('**/api/v1/oa/export', (route) => {
    let body = null;
    try {
      body = route.request().postDataJSON();
    } catch {
      body = route.request().postData();
    }
    resolveCapture(body);

    if (opts.forceStatus) {
      route.fulfill({
        status: opts.forceStatus,
        contentType: 'application/json',
        body: JSON.stringify(opts.body ?? { detail: 'forced' }),
      });
      return;
    }

    // Replicate the real 409 hard gate.
    if (!body || body.attorney_signoff !== true) {
      route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({
          detail:
            "attorney sign-off required: tick '我已逐項確認' before export. No document was produced.",
        }),
      });
      return;
    }

    const segments = Array.isArray(body.segments) ? body.segments : [];
    const accepted = segments.filter((s) => s.accepted);
    const document = accepted.map((s) => s.text).join('\n');
    const summary = {
      total_segments: segments.length,
      accepted_segments: accepted.length,
      ai_generated: accepted.filter((s) => s.source === 'ai_generated').length,
      attorney_edited: accepted.filter((s) => s.source === 'attorney_edited').length,
      attorney_added: accepted.filter((s) => s.source === 'attorney_added').length,
    };
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        case_id: body.case_id,
        rejection_id: body.rejection_id ?? null,
        draft_set_id: body.draft_set_id ?? null,
        document,
        content_sha256: 'a'.repeat(64),
        provenance_summary: summary,
        signed_off_by: 'alice',
        attorney_signoff: true,
      }),
    });
  });
  installed.capture = capture;
  return installed;
}

/** Mock POST /api/v1/debug/redaction_preview. */
export async function mockRedactionPreview(
  page,
  response = {
    redacted: 'Sample redacted text [CASE_REF_1] contact [EMAIL_1].',
    rules_triggered: ['CASE_REF', 'EMAIL'],
  }
) {
  await page.route('**/api/v1/debug/redaction_preview', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(response),
    });
  });
}

/**
 * Mock POST /api/v1/oa/upload. Defaults to a successful 2-page extraction.
 * For multipart bodies Playwright cannot easily decode the file, so the
 * helper just acknowledges the request.
 */
export async function mockUpload(
  page,
  response = {
    extracted_text: 'EXTRACTED OA TEXT — MOCKED.\n\nClaim 1 is rejected under §103.',
    page_count: 2,
    char_count: 42,
    warnings: [],
    ocr_pages_used: 0,
    cost_meta: { estimated_cost_usd: 0 },
  }
) {
  await page.route('**/api/v1/oa/upload', (route) => {
    if (response && response.status && response.status >= 400) {
      route.fulfill({
        status: response.status,
        contentType: 'application/json',
        body: JSON.stringify(response.body ?? { detail: 'upload failed' }),
      });
      return;
    }
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(response),
    });
  });
}

/** Default fixture for /api/v1/audit/recent — two rows for the table. */
export function defaultAuditRows() {
  return [
    {
      audit_id: 'AUD-0001',
      timestamp_utc: '2025-04-15T10:30:00Z',
      timestamp_local: '2025-04-15T18:30:00+08:00',
      user_id: 'alice',
      tenant_id: 'tenant_a',
      case_id: 'CASE-2025-001',
      endpoint: '/v1/oa/analyze',
      request_hash: 'f'.repeat(64),
      response_hash: 'e'.repeat(64),
      masked_field_rules: ['CASE_REF', 'EMAIL', 'PHONE'],
      model_used: 'mock-llama3.1:8b',
      prompt_tokens: 1234,
      completion_tokens: 567,
      latency_ms: 245,
      policy_decisions: {
        rate_limit_passed: true,
        quota_passed: true,
        authz_passed: true,
        cache_hit: false,
        circuit_open: false,
      },
    },
    {
      audit_id: 'AUD-0002',
      timestamp_utc: '2025-04-15T10:35:00Z',
      timestamp_local: '2025-04-15T18:35:00+08:00',
      user_id: 'alice',
      tenant_id: 'tenant_a',
      case_id: 'CASE-2025-001',
      endpoint: '/v1/quota',
      request_hash: 'd'.repeat(64),
      response_hash: 'c'.repeat(64),
      masked_field_rules: [],
      model_used: null,
      prompt_tokens: null,
      completion_tokens: null,
      latency_ms: 12,
      policy_decisions: {
        rate_limit_passed: true,
        quota_passed: true,
        authz_passed: true,
        cache_hit: false,
        circuit_open: false,
      },
    },
  ];
}

export async function mockAuditRecent(page, rows = defaultAuditRows(), opts = {}) {
  await page.route('**/api/v1/audit/recent**', (route) => {
    if (opts.status && opts.status >= 400) {
      route.fulfill({
        status: opts.status,
        contentType: 'application/json',
        body: JSON.stringify(opts.body ?? { detail: 'forbidden' }),
      });
      return;
    }
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(rows),
    });
  });
}

export async function mockAuditVerify(page, broken = [], verified = 2) {
  // Wildcard trailing slash + query string (`?scope=tenant`).
  await page.route('**/api/v1/audit/verify**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ broken, verified }),
    });
  });
}

/**
 * Mock the AppShell footer's stack-status probes (StackStatus.jsx) so chip
 * states are deterministic regardless of what is actually listening on the
 * developer's machine (a real digiRunner on :18080 would otherwise flip the
 * chip green and break visual baselines).
 *
 * `gateway` controls the same-origin /api/v1/health JSON probe; the other
 * three are opaque no-cors reachability probes — fulfil = chip green,
 * abort = chip gray ("not detected").
 */
export async function mockStackProbes(
  page,
  { gateway = true, aiEngine = false, digirunner = false, dify = false } = {}
) {
  await page.route('**/api/v1/health', (route) =>
    route.fulfill({
      status: gateway ? 200 : 503,
      contentType: 'application/json',
      body: JSON.stringify({ ok: gateway, service: 'gateway' }),
    })
  );
  // One predicate route for all three external reachability probes — every
  // page.route() pattern adds per-request driver overhead on Vite dev-server
  // loads (hundreds of module requests), so keep the route count minimal.
  const upByPort = { 8011: aiEngine, 18080: digirunner, 8088: dify };
  await page.route(
    (url) => /^(127\.0\.0\.1|localhost)$/.test(url.hostname) && url.port in upByPort,
    (route) => {
      const up = upByPort[new URL(route.request().url()).port];
      return up
        ? route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' })
        : route.abort('connectionrefused');
    }
  );
}

/**
 * One-shot helper: install login + quota + analyze + audit mocks at once with
 * the default Alice session. Tests that don't need to assert on a specific
 * payload can call this and move on.
 */
export async function mockHappyPath(page, user = 'alice') {
  await mockLogin(page, user);
  await mockQuota(page);
  await mockRedactionPreview(page);
  await mockAnalyze(page);
  await mockAuditRecent(page);
  await mockAuditVerify(page);
}

/**
 * Capture every POST request body sent to /api/v1/*. Returns an object with
 * `.requests` (the array, populated live) and `.stop()` (remove the handler).
 * Use when you need to assert that a particular endpoint was called with a
 * particular body even if the mock above already fulfils it.
 */
export async function interceptApiCalls(page) {
  const requests = [];
  const handler = (req) => {
    const url = req.url();
    if (!/\/api\/v1\//.test(url)) return;
    let body = null;
    try {
      body = req.postDataJSON();
    } catch {
      body = req.postData();
    }
    requests.push({
      url,
      method: req.method(),
      body,
      headers: req.headers(),
    });
  };
  page.on('request', handler);
  return {
    requests,
    stop: () => page.off('request', handler),
  };
}

/**
 * Pre-seed React state so tests can skip the login UI: visit the SPA root,
 * mock login, click Alice's card, wait for /analyze. Returns when the
 * three-pane layout (or mobile tab strip) has rendered.
 *
 * Pass `path` to land somewhere other than /analyze afterwards.
 */
export async function loginAsAlice(page, path = '/analyze') {
  await mockLogin(page, 'alice');
  await mockQuota(page);
  await page.goto('/');
  await page.getByRole('button', { name: /Alice/ }).click();
  await page.waitForURL(/\/analyze/, { timeout: 5000 });
  if (path !== '/analyze') {
    await page.goto(path);
  }
}
