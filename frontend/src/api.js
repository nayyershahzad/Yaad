// Same-origin API client. nginx proxies /auth, /capture, /decks, /billing
// to the FastAPI app, so every path here is relative (no host hardcoded).

const TOKEN_KEY = "yaad_jwt";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(t) {
  if (t) localStorage.setItem(TOKEN_KEY, t);
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}
export function isAuthed() {
  return !!getToken();
}

// Thrown by request() so callers can branch on HTTP status (e.g. 402, 401).
export class ApiError extends Error {
  constructor(status, detail, message) {
    super(message || `HTTP ${status}`);
    this.status = status;
    this.detail = detail; // may be a string or an object {reason, ...}
  }
}

async function request(path, { method = "GET", body, auth = true, isForm = false } = {}) {
  const headers = {};
  if (auth) {
    const t = getToken();
    if (t) headers["Authorization"] = `Bearer ${t}`;
  }
  let payload = body;
  if (body !== undefined && !isForm) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  const resp = await fetch(path, { method, headers, body: payload });

  let data = null;
  const ct = resp.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    data = await resp.json().catch(() => null);
  } else {
    data = await resp.text().catch(() => null);
  }

  if (!resp.ok) {
    const detail = data && typeof data === "object" ? data.detail ?? data : data;
    throw new ApiError(resp.status, detail, `Request failed: ${resp.status}`);
  }
  return data;
}

// ---- auth ----
export function requestOtp(email) {
  return request("/auth/request-otp", { method: "POST", body: { email }, auth: false });
}
export function verifyOtp(email, code) {
  return request("/auth/verify-otp", { method: "POST", body: { email, code }, auth: false });
}
export function me() {
  return request("/auth/me");
}

// ---- capture ----
export function capture(file) {
  const fd = new FormData();
  fd.append("file", file);
  return request("/capture", { method: "POST", body: fd, isForm: true });
}

// ---- decks ----
export function listDecks() {
  return request("/decks");
}
export function getDeck(hash) {
  return request(`/decks/${encodeURIComponent(hash)}`);
}

// ---- billing ----
export function billingStatus() {
  return request("/billing/status");
}
export function subscribe() {
  return request("/billing/subscribe", { method: "POST", body: {} });
}
