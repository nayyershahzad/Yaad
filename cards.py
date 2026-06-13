"""
cards.py — turn extracted page text into a study deck (flashcards + MCQ quiz).

Primary: Groq llama-3.3-70b-versatile (free, JSON mode). Fallback: Gemini on a
Groq rate-limit/5xx. Output is validated against a strict Pydantic schema and the
LLM is retried once on bad JSON before falling through (mirrors the tiered pattern
in /opt/invoicegraph/pipeline/llm.py).

Called by /capture ONLY when a page has no cached PageContent — each unique page
is card-generated once, ever.
"""
from __future__ import annotations

import os
import re
import json
import asyncio
import logging

from pydantic import BaseModel, Field, ValidationError, field_validator

log = logging.getLogger(__name__)

GROQ_MODEL   = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

MAX_FLASHCARDS = 8
MAX_QUIZ = 5
_MIN_TEXT = 20  # below this, not worth an LLM call

_SYSTEM = (
    "You generate study material from a single textbook page. Respond with ONLY a "
    "JSON object, no markdown, matching exactly:\n"
    '{"flashcards":[{"front":"...","back":"..."}],'
    '"quiz":[{"question":"...","options":["a","b","c","d"],'
    '"answer_index":0,"explanation":"..."}]}\n'
    f"Produce up to {MAX_FLASHCARDS} flashcards and up to {MAX_QUIZ} quiz questions, "
    "grounded ONLY in the provided text. Each quiz item must have exactly 4 options "
    "and answer_index in 0..3. If the text has too little content, return empty arrays."
)


# ---- schema ---------------------------------------------------------------
class Flashcard(BaseModel):
    front: str
    back: str


class QuizItem(BaseModel):
    question: str
    options: list[str]
    answer_index: int
    explanation: str = ""

    @field_validator("options")
    @classmethod
    def _four_options(cls, v: list[str]) -> list[str]:
        if len(v) != 4:
            raise ValueError("quiz item must have exactly 4 options")
        return v

    @field_validator("answer_index")
    @classmethod
    def _index_in_range(cls, v: int) -> int:
        if not 0 <= v <= 3:
            raise ValueError("answer_index must be 0..3")
        return v


class Deck(BaseModel):
    flashcards: list[Flashcard] = Field(default_factory=list)
    quiz: list[QuizItem] = Field(default_factory=list)


class _RateLimit(Exception):
    pass


class _Unavailable(Exception):
    pass


def _parse_deck(raw: str) -> Deck:
    raw = re.sub(r"```json|```", "", raw or "").strip()
    data = json.loads(raw)  # raises JSONDecodeError on bad JSON
    # trim to caps before validation so an over-eager model doesn't bloat the deck
    if isinstance(data, dict):
        data["flashcards"] = (data.get("flashcards") or [])[:MAX_FLASHCARDS]
        data["quiz"] = (data.get("quiz") or [])[:MAX_QUIZ]
    return Deck.model_validate(data)


def _classify(e: Exception) -> None:
    s = str(e).lower()
    if "429" in s or "rate" in s or "quota" in s:
        raise _RateLimit(str(e))
    if any(x in s for x in ("500", "502", "503", "timeout", "unavailable")):
        raise _Unavailable(str(e))
    raise _Unavailable(f"unexpected: {e}")  # treat unknown as fall-through-able


# ---- providers (sync; run in a thread) ------------------------------------
def _groq_deck(text: str) -> Deck:
    from groq import Groq
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    try:
        resp = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "system", "content": _SYSTEM},
                      {"role": "user", "content": text}],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=4096,
        )
    except Exception as e:
        _classify(e)
    return _parse_deck(resp.choices[0].message.content)


def _gemini_deck(text: str) -> Deck:
    import google.generativeai as genai
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=_SYSTEM,
        generation_config={"response_mime_type": "application/json", "temperature": 0.0},
    )
    try:
        resp = model.generate_content(text)
    except Exception as e:
        _classify(e)
    return _parse_deck(getattr(resp, "text", "") or "")


def _generate_sync(text: str) -> tuple[Deck, str]:
    """Returns (deck, model_used). Groq first; Gemini on rate-limit/unavailable.
    Bad JSON / schema -> retry the same provider once before falling through."""
    tiers = [("groq", _groq_deck), ("gemini", _gemini_deck)]
    last = None
    for name, fn in tiers:
        for attempt in (1, 2):
            try:
                return fn(text), name
            except (_RateLimit, _Unavailable) as e:
                log.warning("[cards] %s unavailable: %s -> next provider", name, e)
                last = e
                break  # don't retry same provider on rate-limit; fall through
            except (json.JSONDecodeError, ValidationError) as e:
                log.warning("[cards] %s bad output (attempt %d): %s", name, attempt, e)
                last = e
                continue  # retry same provider once
    raise RuntimeError(f"card generation failed on all providers: {last}")


async def generate_cards(text: str) -> dict:
    """Return {"flashcards":[...], "quiz":[...], "model_used": str}. Empty deck
    (no LLM call) when there's too little text to be worth it."""
    if not text or len(text.strip()) < _MIN_TEXT:
        log.info("[cards] text too short (%d chars) — empty deck, no LLM call", len(text or ""))
        return {"flashcards": [], "quiz": [], "model_used": "none"}
    deck, model_used = await asyncio.to_thread(_generate_sync, text)
    log.info("[cards] %s -> %d flashcards, %d quiz", model_used, len(deck.flashcards), len(deck.quiz))
    return {**deck.model_dump(), "model_used": model_used}
