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
// Capture with optional dossier tagging (subject/chapter/page_no sent as form fields).
export function captureImage(file, { subject, chapter, page_no } = {}) {
  const fd = new FormData();
  fd.append("file", file);
  if (subject != null && subject !== "") fd.append("subject", subject);
  if (chapter != null && chapter !== "") fd.append("chapter", chapter);
  if (page_no != null && page_no !== "") fd.append("page_no", String(page_no));
  return request("/capture", { method: "POST", body: fd, isForm: true });
}
// Capture a small PDF (<=5 pages). Each page becomes a deck filed into subject/chapter.
// Returns {pdf, count, subject, chapter, pages:[...], errors:[{page_no, reason}]}.
export function capturePdf(file, { subject, chapter, page_no } = {}) {
  const fd = new FormData();
  fd.append("file", file);
  if (subject != null && subject !== "") fd.append("subject", subject);
  if (chapter != null && chapter !== "") fd.append("chapter", chapter);
  if (page_no != null && page_no !== "") fd.append("page_no", String(page_no));
  return request("/capture/pdf", { method: "POST", body: fd, isForm: true });
}

// ---- decks ----
// Returns {count, decks:[{content_hash, title, subject, chapter, page_no,
// scanned_at, flashcards, quiz}]} — empty decks excluded server-side.
export function listDecks() {
  return request("/decks");
}
// Alias kept for callers that expect getDecks().
export const getDecks = listDecks;
export function getDeck(hash) {
  return request(`/decks/${encodeURIComponent(hash)}`);
}
// File a loose page into a subject/chapter (any field optional).
export function tagDeck(content_hash, { subject, chapter, page_no } = {}) {
  return request(`/decks/${encodeURIComponent(content_hash)}/tag`, {
    method: "POST",
    body: { subject, chapter, page_no },
  });
}
// Remove a page from the user's library.
export function deleteDeck(content_hash) {
  return request(`/decks/${encodeURIComponent(content_hash)}`, { method: "DELETE" });
}

// ---- dossiers ----
export function getDossiers() {
  return request("/dossiers");
}
export function getDossier(subject, chapter) {
  return request(`/dossiers/${encodeURIComponent(subject)}/${encodeURIComponent(chapter)}`);
}
// Subject-wide notes view (read-only; never triggers generation).
// Returns {subject, chapters_total, chapters_with_notes, chapters:[{chapter, has_notes, notes_md, notes_generated_at, page_count, quiz_count}]}.
export function getSubjectNotes(subject) {
  return request(`/dossiers/${encodeURIComponent(subject)}/notes`);
}
// Backfill notes for every chapter in a subject in one call.
// Returns {subject, generated, skipped, errors, chapters_with_notes}.
export function generateAllNotes(subject) {
  return request(`/dossiers/${encodeURIComponent(subject)}/notes/generate-all`, {
    method: "POST",
    body: {},
  });
}
export function regenerateNotes(subject, chapter) {
  return request(`/dossiers/${encodeURIComponent(subject)}/${encodeURIComponent(chapter)}/notes/regenerate`, {
    method: "POST",
    body: {},
  });
}
export function getRevisionSuggestion() {
  return request("/dossiers/revision-suggestion");
}

// ---- billing ----
export function billingStatus() {
  return request("/billing/status");
}
export function subscribe() {
  return request("/billing/subscribe", { method: "POST", body: {} });
}

// ---- challenges ----
export function createChallenge({ title, description, source_content_hash, scoring_rule, starts_at, ends_at } = {}) {
  return request("/challenges", {
    method: "POST",
    body: { title, description, source_content_hash, scoring_rule, starts_at, ends_at },
  });
}
export function listChallenges() {
  return request("/challenges");
}
export function getChallenge(challengeId) {
  return request(`/challenges/${challengeId}`);
}
export function submitAttempt(challengeId, { num_correct, total_questions, duration_seconds } = {}) {
  return request(`/challenges/${challengeId}/attempt`, {
    method: "POST",
    body: { num_correct, total_questions, duration_seconds },
  });
}
export function getLeaderboard(challengeId) {
  return request(`/challenges/${challengeId}/leaderboard`);
}

// ---- social: friends ----
export function requestFriend({ addressee_user_id, email } = {}) {
  return request("/social/friends/request", {
    method: "POST",
    body: { addressee_user_id, email },
  });
}
export function listFriendRequests() {
  return request("/social/friends/requests");
}
export function respondFriend(friendshipId, { action } = {}) {
  return request(`/social/friends/${friendshipId}/respond`, {
    method: "POST",
    body: { action },
  });
}
export function listFriends() {
  return request("/social/friends");
}

// ---- social: decks ----
export function shareDeck({ content_hash, visibility = "friends" } = {}) {
  return request("/social/decks/share", {
    method: "POST",
    body: { content_hash, visibility },
  });
}
// PUBLIC (no auth): fetch a deck shared by link/public visibility.
export function getSharedDeck(content_hash) {
  return request(`/social/shared/${encodeURIComponent(content_hash)}`, { auth: false });
}

// ---- social: feed ----
export function getFeed() {
  return request("/social/feed");
}
export function react(eventId, { reaction_type } = {}) {
  return request(`/social/feed/${eventId}/react`, {
    method: "POST",
    body: { reaction_type },
  });
}
export function unreact(eventId, reaction_type) {
  return request(`/social/feed/${eventId}/react/${encodeURIComponent(reaction_type)}`, {
    method: "DELETE",
  });
}
