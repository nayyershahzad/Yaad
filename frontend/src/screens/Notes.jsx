import React, { useCallback, useEffect, useState } from "react";
import { getDossiers, getSubjectNotes, generateAllNotes } from "../api.js";
import Markdown from "../components/Markdown.jsx";

// Notion-style AI notes, organized by subject.
// Top level: list of subjects (derived from /dossiers).
// Tapping a subject opens its read-only notes view (/dossiers/{subject}/notes)
// with a "Generate all notes" button that backfills every chapter in one tap.
export default function Notes({ onOpenChapter, onUnauthorized }) {
  const [state, setState] = useState({ loading: true, subjects: [], error: "" });
  const [openSubject, setOpenSubject] = useState(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await getDossiers();
        if (alive) setState({ loading: false, subjects: res.subjects || [], error: "" });
      } catch (err) {
        if (err.status === 401) { onUnauthorized(); return; }
        if (alive) setState({ loading: false, subjects: [], error: "Couldn't load your notes." });
      }
    })();
    return () => { alive = false; };
  }, [onUnauthorized]);

  if (openSubject) {
    return (
      <SubjectNotes
        subject={openSubject}
        onBack={() => setOpenSubject(null)}
        onOpenChapter={onOpenChapter}
        onUnauthorized={onUnauthorized}
      />
    );
  }

  if (state.loading) {
    return <div className="card loading-wrap"><div className="spinner" /><p>Loading your notes…</p></div>;
  }

  return (
    <div>
      <h1 style={{ marginBottom: 14 }}>📝 Notes</h1>
      {state.error && <p className="error">{state.error}</p>}

      {state.subjects.length === 0 ? (
        <div className="card center">
          <p className="muted">
            No subjects yet. Scan a page and tag it with a <b>Subject</b> and <b>Chapter</b> —
            then tap <b>✨ Generate all notes</b> here to build a full notebook in one go.
          </p>
        </div>
      ) : (
        state.subjects.map((subj) => {
          const chapterCount = subj.chapters?.length || 0;
          const withNotes = (subj.chapters || []).filter((c) => c.has_notes).length;
          return (
            <div
              className="card chapter-card"
              key={subj.subject}
              role="button"
              onClick={() => setOpenSubject(subj.subject)}
            >
              <div className="chapter-main">
                <div className="chapter-title">📚 {subj.subject}</div>
                <div style={{ marginTop: 6 }}>
                  <span className="pill">{chapterCount} chapter{chapterCount === 1 ? "" : "s"}</span>
                  <span className="pill">{withNotes} with notes</span>
                </div>
              </div>
              <div style={{ fontSize: 22, color: "var(--navy)" }}>›</div>
            </div>
          );
        })
      )}
    </div>
  );
}

function SubjectNotes({ subject, onBack, onOpenChapter, onUnauthorized }) {
  const [state, setState] = useState({ loading: true, data: null, error: "" });
  const [gen, setGen] = useState({ busy: false, msg: "", error: "" });

  const load = useCallback(async () => {
    try {
      const res = await getSubjectNotes(subject);
      setState({ loading: false, data: res, error: "" });
    } catch (err) {
      if (err.status === 401) { onUnauthorized(); return; }
      setState({ loading: false, data: null, error: "Couldn't load notes for this subject." });
    }
  }, [subject, onUnauthorized]);

  useEffect(() => { load(); }, [load]);

  async function doGenerateAll() {
    setGen({ busy: true, msg: "", error: "" });
    try {
      const res = await generateAllNotes(subject);
      await load();
      const parts = [];
      if (res.generated) parts.push(`Generated ${res.generated} new chapter note${res.generated === 1 ? "" : "s"}`);
      if (res.skipped) parts.push(`${res.skipped} skipped (too little text)`);
      if (res.errors?.length) parts.push(`${res.errors.length} failed`);
      setGen({
        busy: false,
        msg: parts.length ? parts.join(" · ") : "Everything is already up to date.",
        error: "",
      });
    } catch (err) {
      if (err.status === 401) { onUnauthorized(); return; }
      setGen({ busy: false, msg: "", error: "Couldn't generate notes right now. Try again." });
    }
  }

  if (state.loading) {
    return (
      <div>
        <button className="btn-ghost" onClick={onBack} style={{ marginBottom: 14 }}>‹ All subjects</button>
        <div className="card loading-wrap"><div className="spinner" /><p>Loading notes…</p></div>
      </div>
    );
  }

  if (state.error || !state.data) {
    return (
      <div>
        <button className="btn-ghost" onClick={onBack} style={{ marginBottom: 14 }}>‹ All subjects</button>
        <p className="error">{state.error || "Couldn't load notes for this subject."}</p>
      </div>
    );
  }

  const d = state.data;
  const chapters = d.chapters || [];

  return (
    <div>
      <button className="btn-ghost" onClick={onBack} style={{ marginBottom: 14 }}>‹ All subjects</button>

      <div className="card">
        <h1 style={{ marginBottom: 4 }}>📚 {d.subject}</h1>
        <p className="muted" style={{ marginBottom: 12 }}>
          {d.chapters_with_notes} of {d.chapters_total} chapter{d.chapters_total === 1 ? "" : "s"} have notes
        </p>
        <button className="btn-primary" disabled={gen.busy} onClick={doGenerateAll}>
          {gen.busy ? "Writing notes…" : "✨ Generate all notes"}
        </button>
        {gen.busy && (
          <div className="loading-wrap" style={{ marginTop: 12 }}>
            <div className="spinner" />
            <p className="muted">Building your notebook — a few seconds per chapter.</p>
          </div>
        )}
        {gen.msg && <div className="banner success" style={{ marginTop: 12 }}>✓ {gen.msg}</div>}
        {gen.error && <p className="error" style={{ marginTop: 12 }}>{gen.error}</p>}
      </div>

      {chapters.length === 0 ? (
        <div className="card center"><p className="muted">No chapters in this subject yet.</p></div>
      ) : (
        chapters.map((ch) => (
          <ChapterNote
            key={ch.chapter}
            subject={d.subject}
            chapter={ch}
            onOpenChapter={onOpenChapter}
          />
        ))
      )}
    </div>
  );
}

function ChapterNote({ subject, chapter, onOpenChapter }) {
  const [open, setOpen] = useState(false);
  const hasNotes = chapter.has_notes && chapter.notes_md;

  return (
    <div className="card">
      <div className="row-between" style={{ alignItems: "flex-start" }}>
        <div
          role={hasNotes ? "button" : undefined}
          onClick={hasNotes ? () => setOpen((o) => !o) : undefined}
          style={{ cursor: hasNotes ? "pointer" : "default", flex: 1 }}
        >
          <div className="chapter-title">{chapter.chapter}</div>
          <div style={{ marginTop: 6 }}>
            <span className="pill">{chapter.page_count} pages</span>
            <span className="pill">{chapter.quiz_count} quiz</span>
            {hasNotes
              ? <span className="notes-ready">✓ Notes ready</span>
              : <span className="notes-pending">Not generated yet</span>}
          </div>
        </div>
        {hasNotes ? (
          <button className="btn-ghost auto" onClick={() => setOpen((o) => !o)}>
            {open ? "Hide" : "Read"}
          </button>
        ) : (
          <button className="btn-ghost auto" onClick={() => onOpenChapter(subject, chapter.chapter, false)}>
            Generate
          </button>
        )}
      </div>

      {hasNotes && open && (
        <div style={{ marginTop: 12, borderTop: "1px solid var(--line, #eee)", paddingTop: 12 }}>
          <Markdown md={chapter.notes_md} />
        </div>
      )}
    </div>
  );
}
