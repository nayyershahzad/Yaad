import React, { useEffect, useState } from "react";
import { getSharedDeck } from "../api.js";
import Deck from "../components/Deck.jsx";

// PUBLIC, no-login view rendered when the URL path is /shared/{content_hash}.
// Fetches the deck via the no-auth endpoint and shows a sign-up CTA.
export default function SharedDeck({ hash }) {
  const [state, setState] = useState({ loading: true, deck: null, error: "" });

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await getSharedDeck(hash);
        if (alive) setState({ loading: false, deck: res, error: "" });
      } catch (err) {
        if (alive) setState({
          loading: false, deck: null,
          error: err.status === 404 ? "This shared deck isn't available." : "Couldn't load this deck.",
        });
      }
    })();
    return () => { alive = false; };
  }, [hash]);

  function goHome() {
    window.location.href = "/";
  }

  return (
    <div className="app">
      <div className="topbar">
        <span className="brand">Yaad</span>
        <div className="right">
          <button className="btn-ghost" onClick={goHome}>Get Yaad</button>
        </div>
      </div>
      <div className="content">
        {state.loading && (
          <div className="card loading-wrap"><div className="spinner" /><p>Loading shared deck…</p></div>
        )}
        {state.error && (
          <div className="card center">
            <p className="error">{state.error}</p>
            <button className="btn-primary" onClick={goHome}>Explore Yaad</button>
          </div>
        )}
        {state.deck && (
          <>
            <div className="card pop">
              <h1>Shared deck</h1>
              <p className="muted" style={{ marginBottom: 0 }}>
                Shared by <b>{state.deck.shared_by}</b> · {state.deck.flashcards?.length || 0} cards · {state.deck.quiz?.length || 0} quiz
              </p>
            </div>
            <Deck flashcards={state.deck.flashcards || []} quiz={state.deck.quiz || []} />
            <div className="card center cta-card">
              <div className="result-emoji">🦉</div>
              <h2 style={{ marginBottom: 6 }}>Make your own decks</h2>
              <p className="muted">Snap any textbook page and Yaad turns it into flashcards + a quiz, free during early access.</p>
              <button className="btn-primary" onClick={goHome}>Sign up for Yaad</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
