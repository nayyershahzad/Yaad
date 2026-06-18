import React, { useEffect, useState } from "react";
import { getDossiers, getRevisionSuggestion, listDecks } from "../api.js";

// The Library: dossier-organized view of everything the user has scanned.
// Subject -> Chapters, each chapter a tappable card. Pages that were scanned
// without a subject/chapter tag don't appear in /dossiers, so we also surface
// an "Untagged pages" group from /decks for discoverability.
export default function Library({ onOpenChapter, onOpenPage, onUnauthorized }) {
  const [state, setState] = useState({ loading: true, subjects: [], error: "" });
  const [revision, setRevision] = useState(null);
  const [taggedHashes, setTaggedHashes] = useState(null);
  const [untagged, setUntagged] = useState([]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await getDossiers();
        if (alive) setState({ loading: false, subjects: res.subjects || [], error: "" });
      } catch (err) {
        if (err.status === 401) { onUnauthorized(); return; }
        if (alive) setState({ loading: false, subjects: [], error: "Couldn't load your library." });
      }
    })();
    // Revision suggestion (best-effort, null = hide).
    (async () => {
      try {
        const r = await getRevisionSuggestion();
        if (alive && r) setRevision(r);
      } catch (err) {
        if (err.status === 401) onUnauthorized();
      }
    })();
    // Untagged pages: anything in /decks not represented by a dossier page.
    (async () => {
      try {
        const r = await listDecks();
        if (alive) setUntagged(r.decks || []);
      } catch { /* non-fatal */ }
    })();
    return () => { alive = false; };
  }, [onUnauthorized]);

  if (state.loading) {
    return (
      <div className="card loading-wrap"><div className="spinner" /><p>Loading your library…</p></div>
    );
  }

  const hasDossiers = state.subjects.length > 0;
  const looseDecks = untagged; // shown as a fallback bucket below

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

      {!hasDossiers && looseDecks.length === 0 && (
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

      {looseDecks.length > 0 && (
        <div className="subject-group">
          <div className="subject-head">🗂️ All scanned pages</div>
          {looseDecks.map((d) => (
            <div className="card deck-row" key={d.content_hash} onClick={() => onOpenPage(d.content_hash)} role="button">
              <div>
                <div>
                  <span className="pill">{d.flashcards} cards</span>
                  <span className="pill">{d.quiz} quiz</span>
                </div>
                <div className="meta" style={{ marginTop: 6 }}>
                  {d.scanned_at ? new Date(d.scanned_at).toLocaleDateString() : "—"}
                  {"  ·  "}
                  <span style={{ fontFamily: "monospace" }}>{d.content_hash.slice(0, 10)}…</span>
                </div>
              </div>
              <div style={{ fontSize: 22, color: "var(--navy)" }}>›</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
