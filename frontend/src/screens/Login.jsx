import React, { useState } from "react";
import { requestOtp, verifyOtp, setToken, ApiError } from "../api.js";

export default function Login({ onAuthed }) {
  const [step, setStep] = useState("email"); // email | code
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function detailReason(err) {
    if (err instanceof ApiError) {
      if (err.detail && typeof err.detail === "object") return err.detail.reason;
      if (typeof err.detail === "string") return err.detail;
    }
    return null;
  }

  async function sendOtp(e) {
    e.preventDefault();
    setError("");
    if (!email.trim()) return;
    setBusy(true);
    try {
      await requestOtp(email.trim());
      setStep("code");
    } catch (err) {
      const reason = detailReason(err);
      if (err.status === 429) {
        setError("Too many requests. Please wait a few minutes and try again.");
      } else if (reason === "otp_send_failed") {
        setError("We couldn't send the code right now. Try again shortly.");
      } else {
        setError("Could not send the code. Check the email and try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function submitCode(e) {
    e.preventDefault();
    setError("");
    const c = code.trim();
    if (c.length < 4) {
      setError("Enter the 6-digit code from your email.");
      return;
    }
    setBusy(true);
    try {
      const res = await verifyOtp(email.trim(), c);
      setToken(res.access_token);
      onAuthed();
    } catch (err) {
      const reason = detailReason(err);
      if (reason === "invalid_or_expired_code" || err.status === 400) {
        setError("That code is wrong or expired. Too many tries will lock it — request a new one.");
      } else if (err.status === 429) {
        setError("Too many attempts. Request a new code in a moment.");
      } else {
        setError("Verification failed. Please try again.");
      }
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  function restart() {
    setStep("email");
    setCode("");
    setError("");
  }

  return (
    <div className="card">
      <h1>Sign in</h1>
      <p className="muted">Snap a textbook page, get flashcards and a quiz. No password — we email you a code.</p>

      {error && <p className="error">{error}</p>}

      {step === "email" ? (
        <form onSubmit={sendOtp}>
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            inputMode="email"
            autoComplete="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <button className="btn-primary" type="submit" disabled={busy}>
            {busy ? "Sending…" : "Email me a code"}
          </button>
        </form>
      ) : (
        <form onSubmit={submitCode}>
          <label htmlFor="code">Enter the 6-digit code sent to {email}</label>
          <input
            id="code"
            className="otp"
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            placeholder="······"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            autoFocus
          />
          <button className="btn-primary" type="submit" disabled={busy}>
            {busy ? "Verifying…" : "Verify & sign in"}
          </button>
          <button className="btn-link" type="button" onClick={restart}>
            Use a different email
          </button>
        </form>
      )}
    </div>
  );
}
