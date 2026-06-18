import React, { useEffect, useState } from "react";
import { listDecks } from "../api.js";

export default function Decks({ onOpen, onUnauthorized }) {
  const [state, setState] = useState({ loading: true, decks: [], error: "" });

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await listDecks();
        if (alive) setState({ loading: false, decks: res.decks || [], error: "" });
      } catch (err) {
        if (err.status === 401) {
          onUnauthorized();
          return;
        }
        if (alive) setState({ loading: false, decks: [], error: "Couldn't load your decks." });
      }
    })();
    return () => { alive = false; };
  }, [onUnauthorized]);

  if (state.loading) {
    return (
      <div className="card loading-wrap">
        <div className="spinner" />
        <p>Loading decks…</p>
      </div>
    );
  }

  return (
    <div>
      <h1 style={{ marginBottom: 14 }}>Your decks</h1>
      {state.error && <p className="error">{state.error}</p>}
      {state.decks.length === 0 ? (
        <div className="card center">
          <p className="muted">No decks yet. Scan a page to create your first one.</p>
        </div>
      ) : (
        state.decks.map((d) => (
          <div className="card deck-row" key={d.content_hash} onClick={() => onOpen(d.content_hash)} role="button">
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
        ))
      )}
    </div>
  );
}
