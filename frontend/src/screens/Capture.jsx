import React, { useRef, useState } from "react";
import { captureImage, capturePdf, ApiError } from "../api.js";
import Deck from "../components/Deck.jsx";

function isPdf(file) {
  return file.type === "application/pdf" || /\.pdf$/i.test(file.name || "");
}

export default function Capture({ onDeck, goUpgrade, onUnauthorized }) {
  const cameraRef = useRef(null);
  const galleryRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [busyKind, setBusyKind] = useState("image"); // image | pdf
  const [error, setError] = useState("");
  const [result, setResult] = useState(null); // {content_hash, flashcards, quiz, ...}
  const [pdfResult, setPdfResult] = useState(null); // {count, subject, chapter, pages, errors}
  const [subject, setSubject] = useState("");
  const [chapter, setChapter] = useState("");
  const [pageNo, setPageNo] = useState("");
  const [filedUnder, setFiledUnder] = useState(null); // {subject, chapter}

  function openCamera() {
    cameraRef.current?.click();
  }
  function openGallery() {
    galleryRef.current?.click();
  }

  function mapImageError(err) {
    const reason = err instanceof ApiError && err.detail && typeof err.detail === "object" ? err.detail.reason : null;
    if (err.status === 415 || reason === "unsupported_type") {
      return "That file type isn't supported. Use a JPG, PNG, or WebP photo.";
    } else if (err.status === 413 || reason === "file_too_large") {
      return "That image is too large. Try a smaller photo.";
    } else if (err.status === 429) {
      return "You're scanning too fast. Wait a moment and try again.";
    } else if (err.status === 503 || reason === "ocr_unavailable" || reason === "cards_unavailable") {
      return "Our reader is busy right now. Your free page wasn't used — try again in a minute.";
    } else if (reason === "empty_file") {
      return "That file looks empty. Pick a photo and try again.";
    }
    return "Something went wrong processing that page. Try again.";
  }

  async function onFile(e) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting same file
    if (!file) return;
    setError("");
    setResult(null);
    setPdfResult(null);
    const tags = {
      subject: subject.trim(),
      chapter: chapter.trim(),
      page_no: pageNo.trim(),
    };

    if (isPdf(file)) {
      setBusyKind("pdf");
      setBusy(true);
      try {
        const res = await capturePdf(file, tags);
        setPdfResult(res);
        setFiledUnder(
          (res.subject || res.chapter || tags.subject || tags.chapter)
            ? { subject: res.subject || tags.subject || "Unsorted", chapter: res.chapter || tags.chapter || "Loose pages" }
            : null
        );
      } catch (err) {
        if (err.status === 401) { onUnauthorized(); return; }
        if (err.status === 402) {
          setError("You've used all your free pages. Upgrade to keep scanning.");
          goUpgrade();
          return;
        }
        const reason = err instanceof ApiError && err.detail && typeof err.detail === "object" ? err.detail : {};
        if (err.status === 422 || reason.reason === "pdf_too_many_pages") {
          const max = reason.max ?? 5;
          const got = reason.got;
          setError(`PDFs can be up to ${max} pages — yours has ${got ?? "more"}. Split it and try again.`);
        } else if (err.status === 413 || reason.reason === "file_too_large") {
          const mb = reason.max_mb;
          setError(mb ? `That PDF is too large (max ${mb} MB). Try a smaller file.` : "That PDF is too large. Try a smaller file.");
        } else if (err.status === 415 || reason.reason === "unsupported_type") {
          setError("That file type isn't supported here. Upload a PDF or use Take photo for images.");
        } else if (reason.reason === "bad_pdf" || reason.reason === "empty_pdf" || reason.reason === "empty_file") {
          setError("We couldn't read that PDF. Make sure it's a valid file and try again.");
        } else if (err.status === 429) {
          setError("You're scanning too fast. Wait a moment and try again.");
        } else {
          setError("Something went wrong processing that PDF. Try again.");
        }
      } finally {
        setBusy(false);
      }
      return;
    }

    setBusyKind("image");
    setBusy(true);
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
      setError(mapImageError(err));
    } finally {
      setBusy(false);
    }
  }

  if (busy) {
    return (
      <div className="card loading-wrap">
        <div className="spinner" />
        {busyKind === "pdf" ? (
          <>
            <p>Processing your PDF…</p>
            <p className="muted">Up to a few seconds per page. Hang tight.</p>
          </>
        ) : (
          <>
            <p>Reading your page…</p>
            <p className="muted">OCR + generating cards. This can take a moment.</p>
          </>
        )}
      </div>
    );
  }

  if (pdfResult) {
    const pages = pdfResult.pages || [];
    const errs = pdfResult.errors || [];
    const added = pages.length;
    const where = filedUnder ? filedUnder.chapter : (pdfResult.chapter || "your library");
    return (
      <div>
        <div className="card pop">
          <h2>PDF imported</h2>
          {added > 0 ? (
            <div className="banner success" style={{ marginBottom: 12 }}>
              📚 Added {added} page{added === 1 ? "" : "s"} to <b>{where}</b>
              {filedUnder ? <> · {filedUnder.subject}</> : null}
            </div>
          ) : (
            <p className="muted">No pages could be turned into decks from that PDF.</p>
          )}
          {errs.length > 0 && (
            <div className="banner pending" style={{ marginBottom: 12 }}>
              {errs.length} page{errs.length === 1 ? "" : "s"} couldn't be processed:
              <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                {errs.map((er) => (
                  <li key={er.page_no}>Page {er.page_no} — {er.reason}</li>
                ))}
              </ul>
            </div>
          )}
          <p className="muted">Find these in your <b>Library</b> and tap <b>Notes</b> to study them.</p>
          <button className="btn-ghost" onClick={() => { setPdfResult(null); setFiledUnder(null); }}>Scan another page</button>
        </div>
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
        <p className="muted">Take a photo, pick an image, or upload a PDF (up to 5 pages, 20 MB). We'll turn it into flashcards and a quiz.</p>
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

        <div className="capture-zone" onClick={openCamera} role="button">
          <div className="big">📷</div>
          <div>Tap to take a photo of your page</div>
        </div>

        {/* Camera: images only, opens rear camera on mobile. */}
        <input
          ref={cameraRef}
          className="hidden-input"
          type="file"
          accept="image/*"
          capture="environment"
          onChange={onFile}
        />
        {/* Gallery / files: existing image OR a PDF, no camera. */}
        <input
          ref={galleryRef}
          className="hidden-input"
          type="file"
          accept="image/*,application/pdf"
          onChange={onFile}
        />

        <div className="capture-actions">
          <button className="btn-primary auto" onClick={openCamera}>📷 Take photo</button>
          <button className="btn-ghost auto" onClick={openGallery}>🖼 Choose from gallery</button>
        </div>
        <p className="muted" style={{ marginTop: 8 }}>
          Gallery accepts images or PDFs. PDFs file every page into the chapter above.
          <br /><strong>PDF limit: up to 5 pages · 20 MB.</strong> Larger PDFs are declined — split them first.
        </p>
      </div>
    </div>
  );
}
