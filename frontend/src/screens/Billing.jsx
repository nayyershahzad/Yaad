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

  return (
    <div>
      <h1 style={{ marginBottom: 14 }}>Your plan</h1>
      {state.error && <p className="error">{state.error}</p>}

      {s && (
        <div className="card">
          <h2>{active ? "Yaad Pro" : "Free"}</h2>
          {active ? (
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

      {!active && s && (
        <div className="card">
          <h2>Upgrade to Pro</h2>
          <p className="muted">
            Unlimited page scans for {s.price_pkr} PKR every {s.period_days} days.
          </p>
          {subError && <p className="error">{subError}</p>}
          <button className="btn-primary" onClick={onSubscribe} disabled={subBusy}>
            {subBusy ? "Starting checkout…" : `Subscribe — ${s.price_pkr} PKR`}
          </button>
          <p className="muted center mt">You'll be taken to PayPro to pay securely.</p>
        </div>
      )}
    </div>
  );
}
