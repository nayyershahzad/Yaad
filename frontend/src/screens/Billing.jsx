import React, { useEffect, useState } from "react";
import { billingStatus, subscribe } from "../api.js";

export default function Billing({ onUnauthorized }) {
  const [state, setState] = useState({ loading: true, status: null, error: "" });
  const [subBusy, setSubBusy] = useState(false);
  const [subError, setSubError] = useState("");

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const s = await billingStatus();
        if (alive) setState({ loading: false, status: s, error: "" });
      } catch (err) {
        if (err.status === 401) {
          onUnauthorized();
          return;
        }
        if (alive) setState({ loading: false, status: null, error: "Couldn't load your plan." });
      }
    })();
    return () => { alive = false; };
  }, [onUnauthorized]);

  async function onSubscribe() {
    setSubError("");
    setSubBusy(true);
    try {
      const res = await subscribe();
      if (res?.payment_url) {
        // Hand off to PayPro Click2Pay; they redirect back to /?billing=...
        window.location.href = res.payment_url;
      } else {
        setSubError("Couldn't start checkout. Try again.");
        setSubBusy(false);
      }
    } catch (err) {
      if (err.status === 401) {
        onUnauthorized();
        return;
      }
      setSubError("Couldn't start checkout. Try again.");
      setSubBusy(false);
    }
  }

  if (state.loading) {
    return (
      <div className="card loading-wrap">
        <div className="spinner" />
        <p>Loading your plan…</p>
      </div>
    );
  }

  const s = state.status;
  const active = s?.active;
  const remaining = s?.free_sheets_remaining; // null = unlimited
  const beta = !!s?.beta_free;

  return (
    <div>
      <h1 style={{ marginBottom: 14 }}>Your plan</h1>
      {state.error && <p className="error">{state.error}</p>}

      {beta && s?.beta_message && (
        <div className="banner success pop">{s.beta_message}</div>
      )}

      {s && (
        <div className="card">
          <h2>{active ? "Yaad Pro" : beta ? "Early access" : "Free"}</h2>
          {beta ? (
            <p className="muted">Unlimited scans — free right now during beta. No payment needed yet. 🎉</p>
          ) : active ? (
            <p className="muted">
              Unlimited scans.{" "}
              {s.period_end ? `Renews / ends ${new Date(s.period_end).toLocaleDateString()}.` : ""}
            </p>
          ) : (
            <p className="muted">
              {remaining === null
                ? "Unlimited scans."
                : `${remaining} free ${remaining === 1 ? "page" : "pages"} remaining.`}
            </p>
          )}
        </div>
      )}

      {/* Pricing card. During beta we de-emphasize the subscribe button. */}
      {s && !active && (
        <div className={`card ${beta ? "beta-plan" : ""}`}>
          <h2>Yaad Pro</h2>
          <div className="price-tag">{s.price_pkr} PKR<span className="price-per">/mo</span></div>
          {beta ? (
            <>
              <p className="muted">Free during early access — no payment needed yet.</p>
              {subError && <p className="error">{subError}</p>}
              <button className="btn-link center" onClick={onSubscribe} disabled={subBusy}>
                {subBusy ? "Starting checkout…" : "Subscribe early anyway"}
              </button>
            </>
          ) : (
            <>
              <p className="muted">
                Unlimited page scans for {s.price_pkr} PKR every {s.period_days} days.
              </p>
              {subError && <p className="error">{subError}</p>}
              <button className="btn-primary" onClick={onSubscribe} disabled={subBusy}>
                {subBusy ? "Starting checkout…" : `Subscribe — ${s.price_pkr} PKR`}
              </button>
              <p className="muted center mt">You'll be taken to PayPro to pay securely.</p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
