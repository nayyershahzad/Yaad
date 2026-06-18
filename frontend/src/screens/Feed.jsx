import React, { useEffect, useState } from "react";
import { getFeed, react, unreact } from "../api.js";

// Reaction palette: type -> emoji. The backend stores the named type; we render
// the emoji. "like"/"fire"/"clap" cover the brief.
const REACTIONS = [
  { type: "like", emoji: "👍" },
  { type: "fire", emoji: "🔥" },
  { type: "clap", emoji: "👏" },
];
const EMOJI = Object.fromEntries(REACTIONS.map((r) => [r.type, r.emoji]));

function actorName(actor, isMe) {
  if (isMe) return "You";
  return actor.email;
}

function eventLine(ev, isMe) {
  const who = actorName(ev.actor, isMe);
  switch (ev.event_type) {
    case "shared_deck":
      return { emoji: "🃏", text: `${who} shared a deck` };
    case "completed_challenge":
      return { emoji: "🏆", text: `${who} completed a challenge` };
    case "earned_streak":
      return { emoji: "🔥", text: `${who} kept a streak going` };
    default:
      return { emoji: "✨", text: `${who} did something` };
  }
}

export default function Feed({ onUnauthorized }) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  function guard(err) {
    if (err && err.status === 401) { onUnauthorized(); return true; }
    return false;
  }

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await getFeed();
        if (alive) { setEvents(res.events || []); setError(""); }
      } catch (err) {
        if (guard(err)) return;
        if (alive) setError("Couldn't load the feed.");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  // Toggle a reaction, optimistically updating counts + my_reactions.
  async function toggle(ev, type) {
    const mine = new Set(ev.my_reactions || []);
    const had = mine.has(type);
    const counts = { ...(ev.reactions || {}) };
    const cur = counts[type] || 0;

    // optimistic
    if (had) {
      mine.delete(type);
      if (cur <= 1) delete counts[type]; else counts[type] = cur - 1;
    } else {
      mine.add(type);
      counts[type] = cur + 1;
    }
    setEvents((list) => list.map((e) =>
      e.id === ev.id ? { ...e, reactions: counts, my_reactions: [...mine], reacted: mine.size > 0 } : e
    ));

    try {
      if (had) await unreact(ev.id, type);
      else await react(ev.id, { reaction_type: type });
    } catch (err) {
      if (guard(err)) return;
      // revert on failure by reloading just this view's data
      try {
        const res = await getFeed();
        setEvents(res.events || []);
      } catch { /* ignore */ }
    }
  }

  return (
    <div>
      <h1 style={{ marginBottom: 14 }}>📣 Activity</h1>
      {error && <p className="error">{error}</p>}
      {loading ? (
        <div className="card loading-wrap"><div className="spinner" /><p>Loading feed…</p></div>
      ) : events.length === 0 ? (
        <div className="card center">
          <p className="muted">Nothing here yet. Share a deck or play a challenge — and add friends to see theirs!</p>
        </div>
      ) : (
        events.map((ev) => {
          // We can't know which actor is "me" from the feed alone, so we never
          // special-case; emails read fine. (Self events still show your email.)
          const line = eventLine(ev, false);
          const mine = new Set(ev.my_reactions || []);
          return (
            <div className="card feed-event" key={ev.id}>
              <div className="feed-head">
                <div className="avatar">{(ev.actor.email || "?")[0].toUpperCase()}</div>
                <div className="feed-body">
                  <div className="feed-text"><span className="feed-emoji">{line.emoji}</span>{line.text}</div>
                  {ev.created_at && <div className="meta">{new Date(ev.created_at).toLocaleString()}</div>}
                </div>
              </div>
              <div className="reactions">
                {REACTIONS.map((r) => {
                  const count = (ev.reactions || {})[r.type] || 0;
                  const active = mine.has(r.type);
                  return (
                    <button
                      key={r.type}
                      className={`react-btn ${active ? "active" : ""}`}
                      onClick={() => toggle(ev, r.type)}
                    >
                      <span className="react-emoji">{r.emoji}</span>
                      {count > 0 && <span className="react-count">{count}</span>}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}
