import React, { useEffect, useState } from "react";
import { isAuthed, clearToken } from "./api.js";
import Landing from "./screens/Landing.jsx";
import Login from "./screens/Login.jsx";
import Capture from "./screens/Capture.jsx";
import Decks from "./screens/Decks.jsx";
import DeckView from "./screens/DeckView.jsx";
import Billing from "./screens/Billing.jsx";
import Challenges from "./screens/Challenges.jsx";
import Friends from "./screens/Friends.jsx";
import Feed from "./screens/Feed.jsx";

// Reads ?billing=success|pending|error that billing.paypro_return redirects to,
// then strips it from the URL so a refresh doesn't re-show the banner.
function readBillingResult() {
  const p = new URLSearchParams(window.location.search);
  const v = p.get("billing");
  if (v && ["success", "pending", "error"].includes(v)) {
    p.delete("billing");
    const qs = p.toString();
    window.history.replaceState({}, "", window.location.pathname + (qs ? "?" + qs : ""));
    return v;
  }
  return null;
}

const BILLING_MSG = {
  success: { cls: "success", text: "Payment confirmed — Yaad Pro is active. Unlimited scans!" },
  pending: { cls: "pending", text: "Payment is processing. Your plan will update once it clears." },
  error: { cls: "error", text: "We couldn't confirm a payment. If you were charged, it'll reconcile shortly." },
};

export default function App() {
  const [authed, setAuthed] = useState(isAuthed());
  const [showLogin, setShowLogin] = useState(false); // logged-out: landing vs login screen
  const [tab, setTab] = useState("capture"); // capture | decks | billing
  const [openDeck, setOpenDeck] = useState(null); // content_hash or null
  const [billingResult, setBillingResult] = useState(null);

  useEffect(() => {
    setBillingResult(readBillingResult());
  }, []);

  // If a billing redirect landed us here, make sure billing tab is visible after login.
  useEffect(() => {
    if (billingResult && authed) setTab("billing");
  }, [billingResult, authed]);

  function onAuthed() {
    setAuthed(true);
  }
  function logout() {
    clearToken();
    setAuthed(false);
    setShowLogin(false);
    setOpenDeck(null);
    setTab("capture");
  }
  function onUnauthorized() {
    // Any 401 from an API call -> token is dead, drop to login.
    clearToken();
    setAuthed(false);
  }

  // Capture produced a deck and wants to show it.
  function showDeck(hash) {
    setOpenDeck(hash);
    setTab("decks");
  }

  if (!authed) {
    // A billing redirect should drop the visitor straight at the login form.
    const wantLogin = showLogin || !!billingResult;

    if (!wantLogin) {
      return (
        <div className="app landing-shell">
          <Landing
            authed={isAuthed()}
            onLogin={() => setShowLogin(true)}
            onOpenApp={() => setAuthed(true)}
          />
        </div>
      );
    }

    return (
      <div className="app">
        <div className="topbar">
          <span className="brand">Yaad</span>
          <div className="right">
            <button className="btn-ghost" onClick={() => setShowLogin(false)}>Back</button>
          </div>
        </div>
        <div className="content">
          {billingResult && (
            <div className={`banner ${BILLING_MSG[billingResult].cls}`}>
              {BILLING_MSG[billingResult].text}
            </div>
          )}
          <Login onAuthed={onAuthed} />
        </div>
      </div>
    );
  }

  let screen;
  if (openDeck) {
    screen = <DeckView hash={openDeck} onBack={() => setOpenDeck(null)} onUnauthorized={onUnauthorized} />;
  } else if (tab === "capture") {
    screen = <Capture onDeck={showDeck} goUpgrade={() => setTab("billing")} onUnauthorized={onUnauthorized} />;
  } else if (tab === "decks") {
    screen = <Decks onOpen={setOpenDeck} onUnauthorized={onUnauthorized} />;
  } else if (tab === "challenges") {
    screen = <Challenges onUnauthorized={onUnauthorized} />;
  } else if (tab === "social") {
    screen = <Social onUnauthorized={onUnauthorized} />;
  } else {
    screen = <Billing onUnauthorized={onUnauthorized} />;
  }

  return (
    <div className="app">
      <div className="topbar">
        <span className="brand">Yaad</span>
        <div className="right">
          <button className="btn-ghost" onClick={logout}>Sign out</button>
        </div>
      </div>
      <div className="content">
        {billingResult && (
          <div className={`banner ${BILLING_MSG[billingResult].cls}`}>
            {BILLING_MSG[billingResult].text}
          </div>
        )}
        {screen}
      </div>

      {!openDeck && (
        <nav className="tabbar">
          <button className={tab === "capture" ? "active" : ""} onClick={() => setTab("capture")}>
            <span className="ico">📷</span>Scan
          </button>
          <button className={tab === "decks" ? "active" : ""} onClick={() => setTab("decks")}>
            <span className="ico">🗂️</span>Decks
          </button>
          <button className={tab === "challenges" ? "active" : ""} onClick={() => setTab("challenges")}>
            <span className="ico">🏆</span>Compete
          </button>
          <button className={tab === "social" ? "active" : ""} onClick={() => setTab("social")}>
            <span className="ico">👥</span>Friends
          </button>
          <button className={tab === "billing" ? "active" : ""} onClick={() => setTab("billing")}>
            <span className="ico">⚙️</span>Account
          </button>
        </nav>
      )}
    </div>
  );
}

// Friends + Feed live under one tab with a segmented toggle.
function Social({ onUnauthorized }) {
  const [sub, setSub] = useState("feed"); // feed | friends
  return (
    <div>
      <div className="seg" style={{ marginBottom: 16 }}>
        <button className={sub === "feed" ? "active" : ""} onClick={() => setSub("feed")}>📣 Activity</button>
        <button className={sub === "friends" ? "active" : ""} onClick={() => setSub("friends")}>👥 Friends</button>
      </div>
      {sub === "feed"
        ? <Feed onUnauthorized={onUnauthorized} />
        : <Friends onUnauthorized={onUnauthorized} />}
    </div>
  );
}
