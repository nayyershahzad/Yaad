import React, { useEffect, useState } from "react";
import { isAuthed, clearToken } from "./api.js";
import Login from "./screens/Login.jsx";
import Capture from "./screens/Capture.jsx";
import Decks from "./screens/Decks.jsx";
import DeckView from "./screens/DeckView.jsx";
import Billing from "./screens/Billing.jsx";

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
    return (
      <div className="app">
        <div className="topbar"><span className="brand">Yaad</span></div>
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
          <button className={tab === "billing" ? "active" : ""} onClick={() => setTab("billing")}>
            <span className="ico">⭐</span>Plan
          </button>
        </nav>
      )}
    </div>
  );
}
