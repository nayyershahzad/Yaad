import React, { useEffect, useRef } from "react";
import "../landing.css";

// Tiny scroll-reveal: adds .in when a [data-reveal] element scrolls into view.
function useScrollReveal() {
  useEffect(() => {
    const els = Array.from(document.querySelectorAll("[data-reveal]"));
    if (!("IntersectionObserver" in window) || els.length === 0) {
      els.forEach((el) => el.classList.add("in"));
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("in");
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.15 }
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);
}

// CSS/emoji owl mascot with an idle float.
function Owl() {
  return (
    <div className="owl" aria-hidden="true">
      <div className="owl-body">
        <div className="owl-ears">
          <span className="ear" />
          <span className="ear" />
        </div>
        <div className="owl-eyes">
          <span className="eye"><span className="pupil" /></span>
          <span className="eye"><span className="pupil" /></span>
        </div>
        <div className="owl-beak" />
        <div className="owl-wing left" />
        <div className="owl-wing right" />
      </div>
      <div className="owl-book">📖</div>
    </div>
  );
}

const FEATURES = [
  { icon: "📸", title: "Snap a page", body: "Point your camera at any textbook or notes page and Yaad pulls out the key stuff in seconds.", tone: "mint" },
  { icon: "🃏", title: "Auto-made flashcards", body: "Turn that page into a tidy deck of flashcards — no typing, no copy-paste.", tone: "peach" },
  { icon: "📝", title: "Quizzes that test you", body: "Yaad writes quick quizzes from your notes so you actually remember it.", tone: "lavender" },
  { icon: "🏆", title: "Challenges & leaderboards", body: "Earn streaks, climb the board, and race your class.", tone: "sky" },
  { icon: "👥", title: "Study with friends", body: "Share decks and revise together — studying is better with your crew.", tone: "mint" },
];

const STEPS = [
  { n: "1", icon: "📸", label: "Snap your page" },
  { n: "2", icon: "✨", label: "Yaad makes the deck" },
  { n: "3", icon: "🧠", label: "Quiz & remember" },
];

export default function Landing({ authed, onLogin, onOpenApp }) {
  useScrollReveal();
  const enterRef = useRef(null);

  return (
    <div className="landing">
      {/* top nav */}
      <header className="lp-nav">
        <span className="lp-brand"><img className="lp-logo" src="/yaad-logo.png" alt="" /> Yaad</span>
        {authed ? (
          <button className="lp-navbtn" onClick={onOpenApp}>Open app</button>
        ) : (
          <button className="lp-navbtn" onClick={onLogin}>Log in</button>
        )}
      </header>

      {/* hero */}
      <section className="lp-hero">
        <div className="blob blob-a" aria-hidden="true" />
        <div className="blob blob-b" aria-hidden="true" />
        <img className="lp-hero-logo" src="/yaad-logo.png" alt="Yaad — owl mascot peeking from behind a study card" />
        <h1 className="lp-title">
          Study that feels<br />like a game <span className="balloon">🎈</span>
        </h1>
        <p className="lp-sub">
          Snap a photo of your notes and Yaad turns it into flashcards and quizzes — instantly. Learning, minus the boring bits.
        </p>
        <button className="lp-cta wiggle" onClick={authed ? onOpenApp : onLogin}>
          {authed ? "Open app" : "Start learning free"} →
        </button>
        <p className="lp-cta-note">No password. We just email you a code.</p>
      </section>

      {/* how it works */}
      <section className="lp-steps" data-reveal>
        <h2 className="lp-h2">How it works</h2>
        <div className="steps-strip">
          {STEPS.map((s, i) => (
            <React.Fragment key={s.n}>
              <div className="step-card pop" style={{ animationDelay: `${i * 0.08}s` }}>
                <div className="step-emoji">{s.icon}</div>
                <div className="step-num">{s.n}</div>
                <div className="step-label">{s.label}</div>
              </div>
              {i < STEPS.length - 1 && <div className="step-arrow" aria-hidden="true">→</div>}
            </React.Fragment>
          ))}
        </div>
      </section>

      {/* features */}
      <section className="lp-features">
        <h2 className="lp-h2" data-reveal>Everything you need to ace it</h2>
        {FEATURES.map((f) => (
          <div className={`feature-card tone-${f.tone}`} data-reveal key={f.title}>
            <div className="feature-icon">{f.icon}</div>
            <div className="feature-text">
              <div className="feature-head">
                <h3>{f.title}</h3>
                {f.soon && <span className="soon-pill">Coming soon</span>}
              </div>
              <p>{f.body}</p>
            </div>
          </div>
        ))}
      </section>

      {/* stats */}
      <section className="lp-stats" data-reveal>
        <div className="stat"><span className="stat-num">10s</span><span className="stat-label">page → deck</span></div>
        <div className="stat"><span className="stat-num">0</span><span className="stat-label">passwords to remember</span></div>
        <div className="stat"><span className="stat-num">∞</span><span className="stat-label">things to learn</span></div>
      </section>

      {/* closing CTA */}
      <section className="lp-close" data-reveal ref={enterRef}>
        <div className="owl mini"><div className="owl-body">
          <div className="owl-ears"><span className="ear" /><span className="ear" /></div>
          <div className="owl-eyes"><span className="eye"><span className="pupil" /></span><span className="eye"><span className="pupil" /></span></div>
          <div className="owl-beak" />
          <div className="owl-wing left" /><div className="owl-wing right" />
        </div></div>
        <h2 className="lp-h2">Ready to actually enjoy revising?</h2>
        <button className="lp-cta wiggle" onClick={authed ? onOpenApp : onLogin}>
          {authed ? "Open app" : "Start learning free"} →
        </button>
      </section>

      <footer className="lp-footer">
        <span>🦉 Yaad</span>
        <span className="lp-footnote">Made for curious minds. Yaad — “remember”.</span>
      </footer>
    </div>
  );
}
