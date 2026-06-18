import React, { useRef, useState } from "react";
import { captureImage, ApiError } from "../api.js";
import Deck from "../components/Deck.jsx";

export default function Capture({ onDeck, goUpgrade, onUnauthorized }) {
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null); // {content_hash, flashcards, quiz, ...}
  const [subject, setSubject] = useState("");
  const [chapter, setChapter] = useState("");
  const [pageNo, setPageNo] = useState("");
  const [filedUnder, setFiledUnder] = useState(null); // {subject, chapter}

  function pick() {
    inputRef.current?.click();
  }

  async function onFile(e) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting same file
    if (!file) return;
    setError("");
    setResult(null);
    setBusy(true);
    const tags = {
      subject: subject.trim(),
      chapter: chapter.trim(),
      page_no: pageNo.trim(),
    };
    try {
      const res = await captureImage(file, tags);
      setResult(res);
      setFiledUnder(
        tags.subject || tags.chapter
          ? { subject: tags.subject || "Unsorted", chapter: tags.chapter || "Loose pages" }
          : null
      );
    } catch (err) {
      if (err.status === 401) {
        onUnauthorized();
        return;
      }
      if (err.status === 402) {
        // free quota exhausted -> push to upgrade
        setError("You've used all your free pages. Upgrade to keep scanning.");
        goUpgrade();
        return;
      }
      const reason = err instanceof ApiError && err.detail && typeof err.detail === "object" ? err.detail.reason : null;
      if (err.status === 415 || reason === "unsupported_type") {
        setError("That file type isn't supported. Use a JPG, PNG, or WebP photo.");
      } else if (err.status === 413 || reason === "file_too_large") {
        setError("That image is too large. Try a smaller photo.");
      } else if (err.status === 429) {
        setError("You're scanning too fast. Wait a moment and try again.");
      } else if (err.status === 503 || reason === "ocr_unavailable" || reason === "cards_unavailable") {
        setError("Our reader is busy right now. Your free page wasn't used — try again in a minute.");
      } else if (reason === "empty_file") {
        setError("That file looks empty. Pick a photo and try again.");
      } else {
        setError("Something went wrong processing that page. Try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  if (busy) {
    return (
      <div className="card loading-wrap">
        <div className="spinner" />
        <p>Reading your page…</p>
        <p className="muted">OCR + generating cards. This can take a moment.</p>
      </div>
    );
  }

  if (result) {
    const empty = (result.flashcards?.length || 0) === 0 && (result.quiz?.length || 0) === 0;
    return (
      <div>
        <div className="card pop">
          <h2>Your new deck</h2>
          {filedUnder && (
            <div className="banner success" style={{ marginBottom: 12 }}>
              📁 Filed under <b>{filedUnder.chapter}</b> · {filedUnder.subject}
            </div>
          )}
          <p className="muted">
            {result.deck_cached ? "Loaded from cache. " : "Freshly generated. "}
            {result.flashcards?.length || 0} flashcards · {result.quiz?.length || 0} quiz questions
          </p>
          <button className="btn-ghost" onClick={() => { setResult(null); setFiledUnder(null); }}>Scan another page</button>
          {result.content_hash && (
            <button className="btn-link" onClick={() => onDeck(result.content_hash)}>
              Open in Library
            </button>
          )}
        </div>
        {empty ? (
          <div className="card center">
            <p className="muted">There wasn't enough readable text on that page to build a deck. Try a clearer photo.</p>
          </div>
        ) : (
          <Deck flashcards={result.flashcards} quiz={result.quiz} />
        )}
      </div>
    );
  }

  return (
    <div>
      <div className="card">
        <h1>Scan a page</h1>
        <p className="muted">Take a photo of a textbook or notes page. We'll turn it into flashcards and a quiz.</p>
        {error && <p className="error">{error}</p>}

        <div className="tag-grid">
          <div>
            <label htmlFor="cap-subject">Subject</label>
            <input
              id="cap-subject"
              type="text"
              placeholder="e.g. Biology"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="cap-chapter">Chapter</label>
            <input
              id="cap-chapter"
              type="text"
              placeholder="e.g. Cell Structure"
              value={chapter}
              onChange={(e) => setChapter(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="cap-page">Page #</label>
            <input
              id="cap-page"
              type="number"
              inputMode="numeric"
              placeholder="e.g. 42"
              value={pageNo}
              onChange={(e) => setPageNo(e.target.value)}
            />
          </div>
        </div>
        <p className="muted" style={{ marginTop: -4 }}>
          Optional, but tagging keeps your library tidy — pages group into chapters automatically. ✨
        </p>

        <div className="capture-zone" onClick={pick} role="button">
          <div className="big">📷</div>
          <div>Tap to take a photo or choose an image</div>
        </div>
        <input
          ref={inputRef}
          className="hidden-input"
          type="file"
          accept="image/*"
          capture="environment"
          onChange={onFile}
        />
        <button className="btn-primary mt" onClick={pick}>Open camera</button>
      </div>
    </div>
  );
}
