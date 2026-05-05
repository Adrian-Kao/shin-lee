// API client — the only place that knows the gateway URL contract.
// Production: wrap in a TanStack Query layer; POC stays plain fetch.

const BASE = '/api'; // proxied by vite to http://localhost:8000

export class ApiError extends Error {
  constructor(status, message, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function call(path, { method = 'GET', body, token, headers = {} } = {}) {
  const fullHeaders = { 'Content-Type': 'application/json', ...headers };
  if (token) fullHeaders.Authorization = `Bearer ${token}`;
  const res = await fetch(BASE + path, {
    method,
    headers: fullHeaders,
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!res.ok) throw new ApiError(res.status, data?.detail || res.statusText, data);
  return data;
}

export const api = {
  health:   () => call('/v1/health'),
  login:    (user_id) => call('/v1/auth/login', { method: 'POST', body: { user_id } }),
  quota:    (token, case_id) => call(`/v1/quota?case_id=${encodeURIComponent(case_id || '')}`, { token }),
  analyze:  (token, payload) => call('/v1/oa/analyze', {
              method: 'POST',
              token,
              body: payload,
              headers: { 'X-Case-Id': payload.case_id }
            }),
  redactionPreview: (token, text, case_id) => call('/v1/debug/redaction_preview', {
              method: 'POST', token, body: { text },
              headers: { 'X-Case-Id': case_id }
            }),
  auditRecent:  (token, case_id) => call('/v1/audit/recent?limit=50', {
              token, headers: { 'X-Case-Id': case_id || 'CASE-2025-001' }
            }),
  auditVerify:  (token, case_id) => call('/v1/audit/verify', {
              token, headers: { 'X-Case-Id': case_id || 'CASE-2025-001' }
            }),
};
