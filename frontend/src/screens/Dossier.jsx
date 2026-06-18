import React, { useEffect, useState } from "react";
import { getDossier, regenerateNotes, shareDeck } from "../api.js";
import Deck from "../components/Deck.jsx";
import Markdown from "../components/Markdown.jsx";

const SHARE_BASE = "https://yaad.engstech.com/shared/";

export default function Dossier({ subject, chapter, onBack, onOpenPage, onUnauthorized, startQuiz = false }) {
  const [state, setState] = useState({ loading: true, data: null, error: "" });
  const [regen, setRegen] = useState(false);
  const [view, setView] = useState(startQuiz ? "quiz" : "notes"); // notes | deck | quiz
  const [share, setShare] = useState({ open: false, busy: false, url: null, copied: false, error: "" });

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await getDossier(subject, chapter);
        if (alive) setState({ loading: false, data: res, error: "" });
      } catch (err) {
        if (err.status === 401) { onUnauthorized(); return; }
        if (alive) setState({
          loading: false, data: null,
          error: err.status === 404 ? "This chapter isn't available." : "Couldn't load this chapter.",
        });
      }
    })();
    return () => { alive = false; };
  }, [subject, chapter, onUnauthorized]);

  async function doRegen() {
    setRegen(true);
    try {
      const res = await regenerateNotes(subject, chapter);
      setState((s) => ({ ...s, data: res }));
      setView("notes");
    } catch (err) {
      if (err.status === 401) { onUnauthorized(); return; }
    } finally {
      setRegen(false);
    }
  }

  // Share the chapter's combined deck. The chapter's content lives across many
  // pages; we share the FIRST page's deck by link as the shareable artifact.
  async function doShareLink() {
    const firstHash = state.data?.pages?.[0]?.content_hash;
    if (!firstHash) return;
    setShare((s) => ({ ...s, busy: true, error: "" }));
    try {
      const res = await shareDeck({ content_hash: firstHash, visibility: "link" });
      setShare({ open: true, busy: false, url: SHARE_BASE + res.content_hash, copied: false, error: "" });
    } catch (err) {
      if (err.status === 401) { onUnauthorized(); return; }
      setShare((s) => ({ ...s, busy: false, error: "Couldn't create a share link." }));
    }
  }

  async function copyUrl() {
    try {
      await navigator.clipboard.writeText(share.url);
      setShare((s) => ({ ...s, copied: true }));
    } catch {
      setShare((s) => ({ ...s, copied: false }));
    }
  }

  if (state.loading) {
    return (
      <div>
        <button className="btn-ghost" onClick={onBack} style={{ marginBottom: 14 }}>‹ Back to library</button>
        <div className="card loading-wrap"><div className="spinner" /><p>Loading chapter…</p></div>
      </div>
    );
  }

  if (state.error || !state.data) {
    return (
      <div>
        <button className="btn-ghost" onClick={onBack} style={{ marginBottom: 14 }}>‹ Back to library</button>
        <p className="error">{state.error || "Couldn't load this chapter."}</p>
      </div>
    );
  }

  const d = state.data;

  return (
    <div>
      <button className="btn-ghost" onClick={onBack} style={{ marginBottom: 14 }}>‹ Back to library</button>

      <div className="card">
        <h1>Chapter {d.chapter}</h1>
        <p className="muted" style={{ marginBottom: 8 }}>{d.subject}</p>
        <div>
          <span className="pill">{d.pages.length} pages</span>
          <span className="pill">{d.flashcards.length} cards</span>
          <span className="pill">{d.quiz.length} quiz</span>
        </div>
      </div>

      <div className="seg seg-3">
        <button className={view === "notes" ? "active" : ""} onClick={() => setView("notes")}>📝 Notes</button>
        <button className={view === "deck" ? "active" : ""} onClick={() => setView("deck")}>🃏 Cards</button>
        <button className={view === "quiz" ? "active" : ""} onClick={() => setView("quiz")}>❓ Quiz</button>
      </div>

      {/* Share + regenerate actions */}
      <div className="card share-bar">
        <div>
          <div style={{ fontWeight: 600 }}>Share this chapter</div>
          <div className="meta">Anyone with the link can study it — no account needed.</div>
        </div>
        <button className="btn-primary auto" disabled={share.busy} onClick={doShareLink}>
          {share.busy ? "…" : "🔗 Share link"}
        </button>
      </div>
      {share.error && <p className="error">{share.error}</p>}
      {share.open && share.url && (
        <div className="card link-share pop">
          <label>Shareable link</label>
          <div className="link-row">
            <input type="text" readOnly value={share.url} onFocus={(e) => e.target.select()} />
            <button className="btn-ghost auto" onClick={copyUrl}>{share.copied ? "Copied ✓" : "Copy"}</button>
          </div>
        </div>
      )}

      {view === "notes" && (
        <div className="card">
          <div className="row-between" style={{ marginBottom: 10 }}>
            <h2 style={{ margin: 0 }}>Chapter notes</h2>
            <button className="btn-ghost auto" disabled={regen} onClick={doRegen}>
              {regen ? "Regenerating…" : "↻ Regenerate"}
            </button>
          </div>
          {regen ? (
            <div className="loading-wrap"><div className="spinner" /><p>Writing fresh notes…</p></div>
          ) : d.notes_md ? (
            <Markdown md={d.notes_md} />
          ) : (
            <p className="muted">
              {d.notes_error
                ? "Notes couldn't be generated right now. Tap Regenerate to retry."
                : "No notes yet — tap Regenerate to create them."}
            </p>
          )}
        </div>
      )}

      {view === "deck" && (
        d.flashcards.length === 0
          ? <div className="card center"><p className="muted">No flashcards in this chapter yet.</p></div>
          : <Deck flashcards={d.flashcards} quiz={[]} />
      )}

      {view === "quiz" && (
        d.quiz.length === 0
          ? <div className="card center"><p className="muted">No quiz questions in this chapter yet.</p></div>
          : <Deck flashcards={[]} quiz={d.quiz} forceQuiz />
      )}

      {/* Member pages — each opens its single-page DeckView */}
      <div className="card">
        <h2>Pages in this chapter</h2>
        {d.pages.map((p) => (
          <div className="deck-row pages-row" key={p.content_hash} onClick={() => onOpenPage(p.content_hash)} role="button">
            <div>
              <div style={{ fontWeight: 600 }}>
                {p.page_no != null ? `Page ${p.page_no}` : "Loose page"}
              </div>
              <div className="meta" style={{ marginTop: 4 }}>
                <span className="pill">{p.flashcard_count} cards</span>
                <span className="pill">{p.quiz_count} quiz</span>
                {p.scanned_at ? new Date(p.scanned_at).toLocaleDateString() : ""}
              </div>
            </div>
            <div style={{ fontSize: 22, color: "var(--navy)" }}>›</div>
          </div>
        ))}
      </div>
    </div>
  );
}
