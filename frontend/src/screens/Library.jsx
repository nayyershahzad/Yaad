import React, { useCallback, useEffect, useState } from "react";
import { getDossiers, getRevisionSuggestion, listDecks, tagDeck, deleteDeck } from "../api.js";

// The Library: dossier-organized view of everything the user has scanned.
// Subject -> Chapters, each chapter a tappable card. Pages that were scanned
// without a subject/chapter tag don't appear in /dossiers, so we also surface
// a "Loose pages" group from /decks so they can be filed or cleared.
export default function Library({ onOpenChapter, onOpenPage, onUnauthorized }) {
  const [state, setState] = useState({ loading: true, subjects: [], error: "" });
  const [revision, setRevision] = useState(null);
  const [decks, setDecks] = useState([]);

  // Loads dossiers + decks together so a tag/delete can refresh both at once
  // (a filed page leaves the loose group and appears under its new dossier).
  const refresh = useCallback(async () => {
    try {
      const res = await getDossiers();
      setState({ loading: false, subjects: res.subjects || [], error: "" });
    } catch (err) {
      if (err.status === 401) { onUnauthorized(); return; }
      setState({ loading: false, subjects: [], error: "Couldn't load your library." });
    }
    try {
      const r = await listDecks();
      setDecks(r.decks || []);
    } catch (err) {
      if (err.status === 401) onUnauthorized();
      /* otherwise non-fatal */
    }
  }, [onUnauthorized]);

  useEffect(() => {
    let alive = true;
    refresh();
    (async () => {
      try {
        const r = await getRevisionSuggestion();
        if (alive && r) setRevision(r);
      } catch (err) {
        if (err.status === 401) onUnauthorized();
      }
    })();
    return () => { alive = false; };
  }, [refresh, onUnauthorized]);

  if (state.loading) {
    return (
      <div className="card loading-wrap"><div className="spinner" /><p>Loading your library…</p></div>
    );
  }

  const hasDossiers = state.subjects.length > 0;
  // Loose pages = untagged decks (no subject AND no chapter). Tagged pages
  // already show under their dossier, so excluding them avoids double-listing.
  const loosePages = decks.filter((d) => !d.subject && !d.chapter);

  return (
    <div>
      <h1 style={{ marginBottom: 14 }}>Your library</h1>
      {state.error && <p className="error">{state.error}</p>}

      {revision && (
        <div className="banner revision pop">
          <span>🔁 Time to revise <b>{revision.chapter}</b> of <b>{revision.subject}</b>!</span>
          <button className="btn-ghost auto" onClick={() => onOpenChapter(revision.subject, revision.chapter, true)}>
            Take quiz
          </button>
        </div>
      )}

      {!hasDossiers && loosePages.length === 0 && (
        <div className="card center">
          <p className="muted">No pages yet. Scan a page to start your library.</p>
        </div>
      )}

      {state.subjects.map((subj) => (
        <div className="subject-group" key={subj.subject}>
          <div className="subject-head">📚 {subj.subject}</div>
          {subj.chapters.map((ch) => (
            <div
              className="card chapter-card"
              key={ch.chapter}
              role="button"
              onClick={() => onOpenChapter(subj.subject, ch.chapter, false)}
            >
              <div className="chapter-main">
                <div className="chapter-title">{ch.chapter}</div>
                <div style={{ marginTop: 6 }}>
                  <span className="pill">{ch.page_count} pages</span>
                  <span className="pill">{ch.flashcard_count} cards</span>
                  <span className="pill">{ch.quiz_count} quiz</span>
                </div>
                <div className="meta" style={{ marginTop: 6 }}>
                  {ch.has_notes
                    ? <span className="notes-ready">✓ Notes ready</span>
                    : <span className="notes-pending">Notes on first open</span>}
                  {ch.last_scanned_at ? `  ·  ${new Date(ch.last_scanned_at).toLocaleDateString()}` : ""}
                </div>
              </div>
              <div style={{ fontSize: 22, color: "var(--navy)" }}>›</div>
            </div>
          ))}
        </div>
      ))}

      {loosePages.length > 0 && (
        <div className="subject-group">
          <div className="subject-head">📄 Loose pages (tap File to organize)</div>
          {loosePages.map((d) => (
            <LoosePage
              key={d.content_hash}
              deck={d}
              onOpen={() => onOpenPage(d.content_hash)}
              onChanged={refresh}
              onUnauthorized={onUnauthorized}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// A single untagged page: opens on tap, with File-into-chapter + Remove actions.
function LoosePage({ deck, onOpen, onChanged, onUnauthorized }) {
  const [mode, setMode] = useState("view"); // view | file
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [form, setForm] = useState({ subject: "", chapter: "", page_no: "" });

  async function fileIt(e) {
    e.preventDefault();
    if (!form.subject.trim() || !form.chapter.trim()) {
      setErr("Subject and chapter are required.");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await tagDeck(deck.content_hash, {
        subject: form.subject.trim(),
        chapter: form.chapter.trim(),
        page_no: form.page_no === "" ? undefined : Number(form.page_no),
      });
      await onChanged();
    } catch (e2) {
      if (e2.status === 401) { onUnauthorized(); return; }
      setErr("Couldn't file this page. Try again.");
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm("Remove this page from your library? This can't be undone.")) return;
    setBusy(true);
    setErr("");
    try {
      await deleteDeck(deck.content_hash);
      await onChanged();
    } catch (e2) {
      if (e2.status === 401) { onUnauthorized(); return; }
      setErr("Couldn't remove this page. Try again.");
      setBusy(false);
    }
  }

  const date = deck.scanned_at ? new Date(deck.scanned_at).toLocaleDateString() : "—";

  if (mode === "file") {
    return (
      <div className="card loose-file">
        <div className="loose-title">{deck.title}</div>
        <form onSubmit={fileIt}>
          <div className="tag-grid">
            <div>
              <label>Subject</label>
              <input type="text" value={form.subject} disabled={busy}
                onChange={(e) => setForm({ ...form, subject: e.target.value })} placeholder="e.g. Biology" />
            </div>
            <div>
              <label>Chapter</label>
              <input type="text" value={form.chapter} disabled={busy}
                onChange={(e) => setForm({ ...form, chapter: e.target.value })} placeholder="e.g. Cell Division" />
            </div>
            <div>
              <label>Page # (optional)</label>
              <input type="text" inputMode="numeric" value={form.page_no} disabled={busy}
                onChange={(e) => setForm({ ...form, page_no: e.target.value.replace(/[^0-9]/g, "") })} placeholder="e.g. 12" />
            </div>
          </div>
          {err && <p className="error">{err}</p>}
          <div className="loose-actions">
            <button type="button" className="btn-ghost" disabled={busy} onClick={() => { setMode("view"); setErr(""); }}>Cancel</button>
            <button type="submit" className="btn-primary auto" disabled={busy}>{busy ? "Filing…" : "📁 File"}</button>
          </div>
        </form>
      </div>
    );
  }

  return (
    <div className="card loose-row">
      <div className="loose-main" role="button" onClick={onOpen}>
        <div className="loose-title">{deck.title}</div>
        <div style={{ marginTop: 6 }}>
          <span className="pill">{deck.flashcards} cards</span>
          <span className="pill">{deck.quiz} quiz</span>
        </div>
        <div className="meta" style={{ marginTop: 6 }}>
          {date}
          {"  ·  "}
          <span className="hash-dim">{deck.content_hash.slice(0, 8)}</span>
        </div>
      </div>
      <div className="loose-btns">
        <button className="icon-btn" title="File into chapter" disabled={busy} onClick={() => setMode("file")}>📁</button>
        <button className="icon-btn danger" title="Remove" disabled={busy} onClick={remove}>🗑</button>
      </div>
      {err && <p className="error" style={{ flexBasis: "100%", margin: "8px 0 0" }}>{err}</p>}
    </div>
  );
}
