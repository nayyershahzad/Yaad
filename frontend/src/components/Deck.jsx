import React, { useState } from "react";

// Renders the deck shape returned by /capture and /decks/{hash}:
//   flashcards: [{ front, back }]
//   quiz:       [{ question, options[4], answer_index, explanation }]
//
// Default mode = study (flashcards + quiz tabs).
// When `challenge` is set, only the quiz runs and `onQuizComplete({ numCorrect,
// total })` fires once every question has been answered — used by the Challenges
// flow to score a run.
export default function Deck({ flashcards = [], quiz = [], challenge = false, onQuizComplete, forceQuiz = false }) {
  const [mode, setMode] = useState(forceQuiz ? "quiz" : "cards"); // cards | quiz

  if (challenge) {
    return <Quiz items={quiz} onComplete={onQuizComplete} />;
  }

  // Quiz-only embed (e.g. Dossier "Take chapter quiz"): no flashcard tab.
  if (forceQuiz && flashcards.length === 0) {
    return <Quiz items={quiz} />;
  }

  return (
    <div>
      <div className="seg">
        <button className={mode === "cards" ? "active" : ""} onClick={() => setMode("cards")}>
          Flashcards ({flashcards.length})
        </button>
        <button className={mode === "quiz" ? "active" : ""} onClick={() => setMode("quiz")}>
          Quiz ({quiz.length})
        </button>
      </div>
      {mode === "cards" ? <Flashcards cards={flashcards} /> : <Quiz items={quiz} />}
    </div>
  );
}

function Flashcards({ cards }) {
  const [i, setI] = useState(0);
  const [flipped, setFlipped] = useState(false);

  if (!cards.length) {
    return <div className="card center"><p className="muted">No flashcards on this page.</p></div>;
  }

  const card = cards[i];
  function go(delta) {
    setFlipped(false);
    setI((prev) => (prev + delta + cards.length) % cards.length);
  }

  return (
    <div className="card">
      <div className="flashcard-wrap">
        <div className="flashcard" onClick={() => setFlipped((f) => !f)}>
          <span className="side-label">{flipped ? "Back" : "Front — tap to flip"}</span>
          <div>{flipped ? card.back : card.front}</div>
        </div>
      </div>
      <div className="card-nav">
        <button className="btn-ghost" onClick={() => go(-1)}>‹ Prev</button>
        <span className="count">{i + 1} / {cards.length}</span>
        <button className="btn-ghost" onClick={() => go(1)}>Next ›</button>
      </div>
    </div>
  );
}

function Quiz({ items, onComplete }) {
  const [answers, setAnswers] = useState({}); // index -> chosen option index
  const [showResults, setShowResults] = useState(false); // normal-mode results summary

  if (!items.length) {
    return <div className="card center"><p className="muted">No quiz on this page.</p></div>;
  }

  function choose(qi, oi) {
    if (answers[qi] !== undefined) return; // lock after first answer
    const next = { ...answers, [qi]: oi };
    setAnswers(next);
    const done = Object.keys(next).length === items.length;
    if (done) {
      // When every question has an answer, tally and report (challenge mode only).
      if (onComplete) {
        const numCorrect = items.reduce(
          (acc, q, idx) => acc + (next[idx] === q.answer_index ? 1 : 0),
          0
        );
        onComplete({ numCorrect, total: items.length });
      } else {
        // Normal study mode: surface a results summary.
        setShowResults(true);
      }
    }
  }

  function tryAgain() {
    setAnswers({});
    setShowResults(false);
  }

  const answeredCount = Object.keys(answers).length;
  const numCorrect = items.reduce(
    (acc, q, idx) => acc + (answers[idx] === q.answer_index ? 1 : 0),
    0
  );

  // Normal-mode results summary (challenge mode never reaches here — it returns
  // via onComplete and the Challenges flow swaps the view).
  if (showResults && !onComplete) {
    const pct = Math.round((numCorrect / items.length) * 100);
    const emoji = pct >= 80 ? "🎉" : pct >= 50 ? "👍" : "💪";
    return (
      <div>
        <div className="card center result-card pop">
          <div className="result-emoji">{emoji}</div>
          <div className="result-score">{numCorrect} / {items.length}</div>
          <p className="muted">{pct}% correct</p>
          <button className="btn-primary" onClick={tryAgain}>↻ Try again</button>
        </div>
        {items.map((q, qi) => {
          const chosen = answers[qi];
          const correct = chosen === q.answer_index;
          return (
            <div className="card" key={qi}>
              <div className="quiz-q">
                <span className={correct ? "res-ok" : "res-no"}>{correct ? "✓" : "✗"}</span>{" "}
                {qi + 1}. {q.question}
              </div>
              {q.options.map((opt, oi) => {
                let cls = "opt";
                if (oi === q.answer_index) cls += " correct";
                else if (oi === chosen) cls += " wrong";
                return (
                  <div key={oi} className={cls}>
                    {String.fromCharCode(65 + oi)}. {opt}
                    {oi === q.answer_index ? "  ✓" : ""}
                  </div>
                );
              })}
              {q.explanation && <div className="explanation">{q.explanation}</div>}
            </div>
          );
        })}
      </div>
    );
  }

  return (
    <div>
      {onComplete && (
        <div className="quiz-progress">
          Answered {answeredCount} / {items.length}
        </div>
      )}
      {items.map((q, qi) => {
        const chosen = answers[qi];
        const answered = chosen !== undefined;
        return (
          <div className="card" key={qi}>
            <div className="quiz-q">{qi + 1}. {q.question}</div>
            {q.options.map((opt, oi) => {
              let cls = "opt";
              if (answered) {
                if (oi === q.answer_index) cls += " correct";
                else if (oi === chosen) cls += " wrong";
              }
              return (
                <button key={oi} className={cls} disabled={answered} onClick={() => choose(qi, oi)}>
                  {String.fromCharCode(65 + oi)}. {opt}
                </button>
              );
            })}
            {answered && q.explanation && <div className="explanation">{q.explanation}</div>}
          </div>
        );
      })}
    </div>
  );
}
