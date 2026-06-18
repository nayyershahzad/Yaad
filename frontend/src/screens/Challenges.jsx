import React, { useEffect, useState } from "react";
import {
  listChallenges,
  createChallenge,
  getChallenge,
  getDeck,
  listDecks,
  submitAttempt,
  getLeaderboard,
  me,
} from "../api.js";
import Deck from "../components/Deck.jsx";

// Top-level Challenges tab. Internal views:
//   list   — joinable challenges
//   create — pick one of your decks + title
//   take   — run the deck's quiz, score it, show rank
//   board  — leaderboard for a challenge
export default function Challenges({ onUnauthorized }) {
  const [view, setView] = useState("list");
  const [active, setActive] = useState(null); // challenge object for take/board

  function guard(err) {
    if (err && err.status === 401) {
      onUnauthorized();
      return true;
    }
    return false;
  }

  if (view === "create") {
    return (
      <CreateChallenge
        guard={guard}
        onDone={() => setView("list")}
        onCancel={() => setView("list")}
      />
    );
  }
  if (view === "take" && active) {
    return (
      <TakeChallenge
        challenge={active}
        guard={guard}
        onBack={() => setView("list")}
        onLeaderboard={() => setView("board")}
      />
    );
  }
  if (view === "board" && active) {
    return (
      <Leaderboard
        challenge={active}
        guard={guard}
        onBack={() => setView("list")}
      />
    );
  }

  return (
    <ChallengeList
      guard={guard}
      onCreate={() => setView("create")}
      onTake={(ch) => { setActive(ch); setView("take"); }}
      onBoard={(ch) => { setActive(ch); setView("board"); }}
    />
  );
}

// --------------------------------------------------------------------------- list
function ChallengeList({ guard, onCreate, onTake, onBoard }) {
  const [state, setState] = useState({ loading: true, items: [], error: "" });

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const items = await listChallenges();
        if (alive) setState({ loading: false, items, error: "" });
      } catch (err) {
        if (guard(err)) return;
        if (alive) setState({ loading: false, items: [], error: "Couldn't load challenges." });
      }
    })();
    return () => { alive = false; };
  }, []);

  return (
    <div>
      <div className="row-between" style={{ marginBottom: 14 }}>
        <h1>🏆 Challenges</h1>
        <button className="btn-primary auto" onClick={onCreate}>+ New</button>
      </div>
      {state.error && <p className="error">{state.error}</p>}
      {state.loading ? (
        <div className="card loading-wrap"><div className="spinner" /><p>Loading challenges…</p></div>
      ) : state.items.length === 0 ? (
        <div className="card center">
          <p className="muted">No open challenges yet. Create one from a deck and race your friends!</p>
          <button className="btn-primary" onClick={onCreate}>Create a challenge</button>
        </div>
      ) : (
        state.items.map((ch) => (
          <div className="card" key={ch.id}>
            <div className="challenge-head">
              <div className="challenge-title">{ch.title}</div>
              <span className="pill">{ch.attempt_count} {ch.attempt_count === 1 ? "play" : "plays"}</span>
            </div>
            {ch.description && <p className="muted" style={{ marginBottom: 10 }}>{ch.description}</p>}
            <div className="meta">by player #{ch.creator_user_id}</div>
            <div className="challenge-actions">
              <button className="btn-primary" onClick={() => onTake(ch)}>Join ▶</button>
              <button className="btn-ghost" onClick={() => onBoard(ch)}>🏅 Leaderboard</button>
            </div>
          </div>
        ))
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- create
function CreateChallenge({ guard, onDone, onCancel }) {
  const [decks, setDecks] = useState(null); // null while loading
  const [picked, setPicked] = useState(null); // content_hash
  const [title, setTitle] = useState("");
  const [desc, setDesc] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await listDecks();
        if (alive) setDecks(res.decks || []);
      } catch (err) {
        if (guard(err)) return;
        if (alive) { setDecks([]); setError("Couldn't load your decks."); }
      }
    })();
    return () => { alive = false; };
  }, []);

  async function save() {
    if (!picked || !title.trim()) return;
    setSaving(true);
    setError("");
    try {
      await createChallenge({
        title: title.trim(),
        description: desc.trim() || undefined,
        source_content_hash: picked,
      });
      onDone();
    } catch (err) {
      if (guard(err)) return;
      setError("Couldn't create that challenge. Try again.");
      setSaving(false);
    }
  }

  return (
    <div>
      <button className="btn-ghost" onClick={onCancel} style={{ marginBottom: 14 }}>‹ Cancel</button>
      <h1 style={{ marginBottom: 14 }}>Create a challenge</h1>
      {error && <p className="error">{error}</p>}

      <div className="card">
        <label>Title</label>
        <input
          type="text"
          placeholder="e.g. Cell Biology Sprint"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={200}
        />
        <label>Description (optional)</label>
        <input
          type="text"
          placeholder="Add a fun tagline"
          value={desc}
          onChange={(e) => setDesc(e.target.value)}
        />
      </div>

      <h2 style={{ margin: "4px 0 10px" }}>Pick a deck</h2>
      {decks === null ? (
        <div className="card loading-wrap"><div className="spinner" /><p>Loading decks…</p></div>
      ) : decks.length === 0 ? (
        <div className="card center"><p className="muted">You need a deck first. Scan a page to make one.</p></div>
      ) : (
        decks.map((d) => (
          <div
            key={d.content_hash}
            className={`card deck-row pickable ${picked === d.content_hash ? "picked" : ""}`}
            role="button"
            onClick={() => setPicked(d.content_hash)}
          >
            <div>
              <div>
                <span className="pill">{d.flashcards} cards</span>
                <span className="pill">{d.quiz} quiz</span>
              </div>
              <div className="meta" style={{ marginTop: 6, fontFamily: "monospace" }}>
                {d.content_hash.slice(0, 10)}…
              </div>
            </div>
            <div style={{ fontSize: 20 }}>{picked === d.content_hash ? "✅" : "○"}</div>
          </div>
        ))
      )}

      <button
        className="btn-primary mt"
        disabled={!picked || !title.trim() || saving}
        onClick={save}
      >
        {saving ? "Creating…" : "Create challenge 🚀"}
      </button>
    </div>
  );
}

// --------------------------------------------------------------------------- take
function TakeChallenge({ challenge, guard, onBack, onLeaderboard }) {
  const [phase, setPhase] = useState("loading"); // loading | playing | submitting | done | error
  const [deck, setDeck] = useState(null);
  const [startedAt] = useState(() => Date.now());
  const [result, setResult] = useState(null); // AttemptOut

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const d = await getDeck(challenge.source_content_hash);
        if (!alive) return;
        if (!d.quiz || d.quiz.length === 0) {
          setPhase("error");
          return;
        }
        setDeck(d);
        setPhase("playing");
      } catch (err) {
        if (guard(err)) return;
        if (alive) setPhase("error");
      }
    })();
    return () => { alive = false; };
  }, [challenge.source_content_hash]);

  async function finish({ numCorrect, total }) {
    setPhase("submitting");
    const duration = Math.max(0, Math.round((Date.now() - startedAt) / 1000));
    try {
      const res = await submitAttempt(challenge.id, {
        num_correct: numCorrect,
        total_questions: total,
        duration_seconds: duration,
      });
      setResult({ ...res, _numCorrect: numCorrect, _total: total, _duration: duration });
      setPhase("done");
    } catch (err) {
      if (guard(err)) return;
      setPhase("error");
    }
  }

  return (
    <div>
      <button className="btn-ghost" onClick={onBack} style={{ marginBottom: 14 }}>‹ Back to challenges</button>
      <h1 style={{ marginBottom: 6 }}>{challenge.title}</h1>

      {phase === "loading" && (
        <div className="card loading-wrap"><div className="spinner" /><p>Loading the quiz…</p></div>
      )}
      {phase === "error" && (
        <div className="card center"><p className="muted">This challenge's quiz isn't available right now.</p></div>
      )}
      {phase === "playing" && deck && (
        <>
          <p className="muted">Answer every question — we'll time your run.</p>
          <Deck challenge quiz={deck.quiz} onQuizComplete={finish} />
        </>
      )}
      {phase === "submitting" && (
        <div className="card loading-wrap"><div className="spinner" /><p>Scoring your run…</p></div>
      )}
      {phase === "done" && result && (
        <div className="card center result-card pop">
          <div className="result-emoji">{result.rank === 1 ? "🥇" : result.rank <= 3 ? "🎉" : "✅"}</div>
          <h2>{result._numCorrect} / {result._total} correct</h2>
          <div className="result-score">{result.score} pts</div>
          <p className="muted">
            Rank #{result.rank} · {result._duration}s
          </p>
          <button className="btn-primary" onClick={onLeaderboard}>🏅 See leaderboard</button>
          <button className="btn-ghost mt" onClick={onBack}>Back to challenges</button>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- leaderboard
function Leaderboard({ challenge, guard, onBack }) {
  const [state, setState] = useState({ loading: true, rows: [], error: "" });
  const [myId, setMyId] = useState(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [rows, meRes] = await Promise.all([
          getLeaderboard(challenge.id),
          me().catch(() => null),
        ]);
        if (!alive) return;
        setMyId(meRes ? meRes.user_id : null);
        setState({ loading: false, rows, error: "" });
      } catch (err) {
        if (guard(err)) return;
        if (alive) setState({ loading: false, rows: [], error: "Couldn't load the leaderboard." });
      }
    })();
    return () => { alive = false; };
  }, [challenge.id]);

  const medal = (rank) => (rank === 1 ? "🥇" : rank === 2 ? "🥈" : rank === 3 ? "🥉" : `#${rank}`);

  return (
    <div>
      <button className="btn-ghost" onClick={onBack} style={{ marginBottom: 14 }}>‹ Back to challenges</button>
      <h1 style={{ marginBottom: 4 }}>🏅 Leaderboard</h1>
      <p className="muted">{challenge.title}</p>
      {state.error && <p className="error">{state.error}</p>}
      {state.loading ? (
        <div className="card loading-wrap"><div className="spinner" /><p>Loading…</p></div>
      ) : state.rows.length === 0 ? (
        <div className="card center"><p className="muted">No plays yet. Be the first!</p></div>
      ) : (
        <div className="card lb-card">
          {state.rows.map((r) => {
            const isMe = myId != null && r.user_id === myId;
            return (
              <div className={`lb-row ${isMe ? "me" : ""} ${r.rank <= 3 ? "podium" : ""}`} key={`${r.user_id}-${r.rank}`}>
                <span className="lb-rank">{medal(r.rank)}</span>
                <span className="lb-name">
                  {isMe ? "You" : `Player #${r.user_id}`}
                  {r.duration_seconds != null && <span className="lb-time"> · {r.duration_seconds}s</span>}
                </span>
                <span className="lb-score">{r.score}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
