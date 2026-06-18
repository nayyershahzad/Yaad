import React, { useEffect, useState } from "react";
import {
  listFriends,
  listFriendRequests,
  requestFriend,
  respondFriend,
  ApiError,
} from "../api.js";

// Friends management: accepted friends, incoming requests (accept/block),
// and an "add friend" input (by email — the backend resolves it to a user).
export default function Friends({ onUnauthorized }) {
  const [friends, setFriends] = useState([]);
  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");
  const [addMsg, setAddMsg] = useState(null); // {ok, text}
  const [adding, setAdding] = useState(false);

  function guard(err) {
    if (err && err.status === 401) { onUnauthorized(); return true; }
    return false;
  }

  async function load() {
    try {
      const [f, r] = await Promise.all([listFriends(), listFriendRequests()]);
      setFriends(f.friends || []);
      setRequests(r.requests || []);
      setError("");
    } catch (err) {
      if (guard(err)) return;
      setError("Couldn't load friends.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function add() {
    const e = email.trim().toLowerCase();
    if (!e) return;
    setAdding(true);
    setAddMsg(null);
    try {
      await requestFriend({ email: e });
      setAddMsg({ ok: true, text: "Request sent! 🎉" });
      setEmail("");
    } catch (err) {
      if (guard(err)) return;
      const reason = err instanceof ApiError && err.detail && typeof err.detail === "object" ? err.detail.reason : null;
      if (err.status === 404 || reason === "user_not_found") {
        setAddMsg({ ok: false, text: "No Yaad user with that email." });
      } else if (reason === "cannot_friend_self") {
        setAddMsg({ ok: false, text: "That's you! 🙂" });
      } else if (err.status === 409 || reason === "friendship_already_exists") {
        setAddMsg({ ok: false, text: "You're already connected (or have a pending request)." });
      } else {
        setAddMsg({ ok: false, text: "Couldn't send that request." });
      }
    } finally {
      setAdding(false);
    }
  }

  async function respond(id, action) {
    try {
      await respondFriend(id, { action });
      await load();
    } catch (err) {
      if (guard(err)) return;
      setError("Couldn't update that request.");
    }
  }

  return (
    <div>
      <h1 style={{ marginBottom: 14 }}>👥 Friends</h1>
      {error && <p className="error">{error}</p>}

      <div className="card">
        <label>Add a friend by email</label>
        <input
          type="email"
          placeholder="friend@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        {addMsg && <p className={addMsg.ok ? "ok-msg" : "error"}>{addMsg.text}</p>}
        <button className="btn-primary" disabled={!email.trim() || adding} onClick={add}>
          {adding ? "Sending…" : "Send request"}
        </button>
      </div>

      {loading ? (
        <div className="card loading-wrap"><div className="spinner" /><p>Loading…</p></div>
      ) : (
        <>
          {requests.length > 0 && (
            <>
              <h2 style={{ margin: "4px 0 10px" }}>Requests</h2>
              {requests.map((r) => (
                <div className="card friend-row" key={r.friendship_id}>
                  <div className="avatar">{(r.requester.email || "?")[0].toUpperCase()}</div>
                  <div className="friend-name">{r.requester.email}</div>
                  <div className="friend-actions">
                    <button className="btn-primary auto" onClick={() => respond(r.friendship_id, "accept")}>Accept</button>
                    <button className="btn-ghost auto" onClick={() => respond(r.friendship_id, "block")}>Block</button>
                  </div>
                </div>
              ))}
            </>
          )}

          <h2 style={{ margin: "12px 0 10px" }}>Your crew ({friends.length})</h2>
          {friends.length === 0 ? (
            <div className="card center"><p className="muted">No friends yet. Add someone above to study together!</p></div>
          ) : (
            friends.map((f) => (
              <div className="card friend-row" key={f.id}>
                <div className="avatar">{(f.email || "?")[0].toUpperCase()}</div>
                <div className="friend-name">{f.email}</div>
              </div>
            ))
          )}
        </>
      )}
    </div>
  );
}
