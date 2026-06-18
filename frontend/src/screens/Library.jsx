import React, { useCallback, useEffect, useState } from "react";
import { getDossiers, getRevisionSuggestion, listDecks, tagDeck, deleteDeck } from "../api.js";

// The Library: a Notion/Drive-style folder tree of everything scanned.
// Subjects are collapsible folders; chapters are tidy rows inside them.
// Pages scanned without a subject/chapter tag don't appear in /dossiers, so we
// also surface an "Unfiled" folder (from /decks) where they can be filed or removed.
export default function Library({ onOpenChapter, onOpenPage, onUnauthorized }) {
  const [state, setState] = useState({ loading: true, subjects: [], error: "" });
  const [revision, setRevision] = useState(null);
  const [decks, setDecks] = useState([]);
  // Per-folder open/closed state, keyed by subject name (and "__unfiled__").
  // Absent key = default open; we only store explicit toggles.
  const [closed, setClosed] = useState({});

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

  const toggle = useCallback((key) => {
    setClosed((c) => ({ ...c, [key]: !c[key] }));
  }, []);

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

      {state.subjects.map((subj) => {
        const isOpen = !closed[subj.subject];
        const n = subj.chapters.length;
        return (
          <div className="folder" key={subj.subject}>
            <button
              className="folder-head"
              aria-expanded={isOpen}
              onClick={() => toggle(subj.subject)}
            >
              <span className={`folder-chevron ${isOpen ? "open" : ""}`}>▸</span>
              <span className="folder-icon">📚</span>
              <span className="folder-name">{subj.subject}</span>
              <span className="folder-count">{n} {n === 1 ? "chapter" : "chapters"}</span>
            </button>

            {isOpen && (
              <div className="folder-body">
                {subj.chapters.map((ch) => (
                  <div
                    className="tree-row chapter-row"
                    key={ch.chapter}
                    role="button"
                    onClick={() => onOpenChapter(subj.subject, ch.chapter, false)}
                  >
                    <span className="tree-icon">📄</span>
                    <div className="tree-main">
                      <div className="tree-label">{ch.chapter}</div>
                      <div className="tree-meta">{chapterMeta(ch)}</div>
                    </div>
                    {ch.has_notes && <span className="notes-badge">📝 Notes</span>}
                    <span className="tree-caret">›</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}

      {loosePages.length > 0 && (
        <div className="folder">
          <button
            className="folder-head"
            aria-expanded={!closed.__unfiled__}
            onClick={() => toggle("__unfiled__")}
          >
            <span className={`folder-chevron ${!closed.__unfiled__ ? "open" : ""}`}>▸</span>
            <span className="folder-icon">📂</span>
            <span className="folder-name">Unfiled</span>
            <span className="folder-count">
              {loosePages.length} {loosePages.length === 1 ? "page" : "pages"}
            </span>
          </button>

          {!closed.__unfiled__ && (
            <div className="folder-body">
              <p className="folder-hint">Tap 📁 to file a page into a chapter.</p>
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
      )}
    </div>
  );
}

// Builds the single quiet meta line for a chapter: "1 page · 8 cards · 5 quiz".
function chapterMeta(ch) {
  const parts = [
    `${ch.page_count} ${ch.page_count === 1 ? "page" : "pages"}`,
    `${ch.flashcard_count} cards`,
    `${ch.quiz_count} quiz`,
  ];
  return parts.join(" · ");
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
  const meta = `${deck.flashcards} cards · ${deck.quiz} quiz · ${date}`;

  if (mode === "file") {
    return (
      <div className="loose-file">
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
    <div className="tree-row loose-tree-row">
      <span className="tree-icon">📄</span>
      <div className="tree-main" role="button" onClick={onOpen}>
        <div className="tree-label">{deck.title}</div>
        <div className="tree-meta">{meta}</div>
      </div>
      <div className="loose-btns">
        <button className="icon-btn" title="File into chapter" disabled={busy} onClick={() => setMode("file")}>📁</button>
        <button className="icon-btn danger" title="Remove" disabled={busy} onClick={remove}>🗑</button>
      </div>
      {err && <p className="error" style={{ flexBasis: "100%", margin: "8px 0 0" }}>{err}</p>}
    </div>
  );
}
