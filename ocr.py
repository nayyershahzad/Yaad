"""
ocr.py — OCR a textbook-page image into clean text.

Primary: Gemini vision (gemini-2.0-flash). Fallback: local Tesseract when Gemini
is rate-limited/quota-exhausted/unavailable — so capture keeps working under a
shared free-tier key and we don't starve other apps' Gemini quota.

Called by /capture ONLY when the page isn't already in the ExtractedPage cache
(billing.register_scan -> ocr_needed). Each unique page is OCR'd once, ever.

Gemini SDK isolated here (+ cards.py fallback) so swapping the EOL
`google.generativeai` for `google.genai` later is a one-file change.
"""
from __future__ import annotations

import os
import io
import asyncio
import logging
import unicodedata

import google.generativeai as genai
import pytesseract
from PIL import Image

log = logging.getLogger(__name__)

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
TESSERACT_CONFIG = "--psm 6"
TESSERACT_LANG = os.getenv("TESSERACT_LANG", "eng")
# Which engine to try first. Default "tesseract" (free, local) so we don't lean on
# the shared free-tier Gemini key. Set OCR_PRIMARY=gemini once Yaad has its own key.
OCR_PRIMARY = os.getenv("OCR_PRIMARY", "tesseract").lower()

_OCR_PROMPT = (
    "You are an OCR engine. Transcribe ALL text from this image of a printed "
    "textbook/study page, verbatim, as clean Markdown. Preserve headings, lists, "
    "and reading order. Do not summarise, translate, or add commentary. If the "
    "image contains no readable text, return an empty string."
)


class OCRError(RuntimeError):
    """OCR failed on every available engine."""


class _Transient(Exception):
    """Gemini rate-limit / quota / unavailable -> try the fallback."""


def _looks_low_quality(text: str) -> bool:
    """Conservative garbage detector for OCR output.

    Returns True when `text` is likely unusable — so the rescue path can fire.
    Tuned so normal textbook prose passes and Tesseract gibberish fails; we err
    toward NOT flagging (a false negative just means no rescue, a false positive
    burns an LLM call). Three signals:
      - too short (< 25 non-space chars)
      - low alphabetic ratio (lots of symbol/digit noise)
      - few "plausible words" (alpha tokens of length >= 2)
    A legitimately short-but-clean page (mostly real words) is NOT flagged.
    """
    if text is None:
        return True
    stripped = text.strip()
    if len(stripped.replace(" ", "")) < 25:
        return True

    alpha = sum(c.isalpha() for c in stripped)
    nonspace = sum(not c.isspace() for c in stripped)
    if nonspace == 0:
        return True
    alpha_ratio = alpha / nonspace

    tokens = stripped.split()
    if not tokens:
        return True
    plausible = sum(1 for t in tokens if t.isalpha() and len(t) >= 2)
    plausible_ratio = plausible / len(tokens)

    # Garbage: very low alpha content OR very few real-looking words.
    if alpha_ratio < 0.55:
        return True
    if plausible_ratio < 0.45:
        return True
    return False


def _clean(text: str) -> str:
    """Normalize + collapse whitespace (mirrors invoicegraph pipeline/ocr.py)."""
    text = text.replace("\x00", "")
    text = unicodedata.normalize("NFKC", text)
    lines = text.splitlines()
    cleaned = "\n".join(" ".join(line.split()) for line in lines)
    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")
    return cleaned.strip()


def _open(image_bytes: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()  # force-decode now so a corrupt image fails loudly
        return img
    except Exception as e:
        raise OCRError(f"Unreadable image: {e}") from e


def _gemini(img: Image.Image) -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise _Transient("GEMINI_API_KEY not set")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name=GEMINI_MODEL)
    try:
        resp = model.generate_content([_OCR_PROMPT, img])
    except Exception as e:
        s = str(e).lower()
        if any(x in s for x in ("429", "quota", "rate", "resourceexhausted",
                                "500", "502", "503", "unavailable", "timeout")):
            raise _Transient(f"gemini transient: {str(e)[:120]}") from e
        raise OCRError(f"Gemini OCR failed: {e}") from e
    return _clean(getattr(resp, "text", "") or "")


def _tesseract(img: Image.Image) -> str:
    try:
        raw = pytesseract.image_to_string(img, lang=TESSERACT_LANG, config=TESSERACT_CONFIG)
    except Exception as e:
        raise OCRError(f"Tesseract OCR failed: {e}") from e
    return _clean(raw)


class _OCRResult:
    """Outcome of one pass over the OCR engines, with enough provenance for the
    rescue path to decide what to try next."""
    __slots__ = ("text", "engine", "gemini_tried", "gemini_failed")

    def __init__(self, text: str, engine: str, gemini_tried: bool, gemini_failed: bool):
        self.text = text          # best text we got (possibly empty)
        self.engine = engine      # engine that produced `text`, or "none"
        self.gemini_tried = gemini_tried    # did we actually call Gemini this round?
        self.gemini_failed = gemini_failed  # did Gemini fail transiently this round?


def _ocr_sync(image_bytes: bytes) -> _OCRResult:
    """Run engines per OCR_PRIMARY, tracking provenance. Does NOT raise on empty
    output — returns whatever it got (text may be ""), so the async layer owns
    the rescue + OCRError decision."""
    img = _open(image_bytes)
    order = ["gemini", "tesseract"] if OCR_PRIMARY == "gemini" else ["tesseract", "gemini"]
    gemini_tried = False
    gemini_failed = False
    for engine in order:
        try:
            if engine == "gemini":
                gemini_tried = True
                return _OCRResult(_gemini(img), "gemini", gemini_tried, gemini_failed)
            return _OCRResult(_tesseract(img), "tesseract", gemini_tried, gemini_failed)
        except (_Transient, OCRError) as e:
            if engine == "gemini":
                gemini_failed = True
            log.warning("[ocr] %s failed (%s) -> next engine", engine, e)
    return _OCRResult("", "none", gemini_tried, gemini_failed)


def _gemini_sync(image_bytes: bytes) -> str:
    """Re-read the image with the vision model (rescue path). Empty string on
    transient/SDK failure — the caller treats no-improvement as keep-original."""
    try:
        return _gemini(_open(image_bytes))
    except (_Transient, OCRError) as e:
        log.warning("[ocr] gemini vision rescue failed (%s)", e)
        return ""


def _better(candidate: str, current: str) -> bool:
    """True if `candidate` is a clear improvement over `current`: passes quality,
    or is meaningfully longer (and not itself empty)."""
    if not candidate.strip():
        return False
    if not _looks_low_quality(candidate):
        return True
    return len(candidate.strip()) > len(current.strip()) * 1.25


async def ocr_image(image_bytes: bytes, mime: str | None = None) -> str:
    """Return cleaned page text via the tiered engines, with a layered rescue when
    the result looks like garbage:
      1. Vision rescue — if Gemini wasn't already tried this round and a key is
         set, re-read the image with the vision model; use it if clearly better.
      2. Text rescue — if still low-quality but we have *some* text, run it
         through cards.repair_ocr_text() (LLM cleanup) and use the repaired text.
    Raises OCRError only when no engine produced any text AND repair produced
    nothing. Runs the sync SDKs in a thread so the event loop isn't blocked."""
    res = await asyncio.to_thread(_ocr_sync, image_bytes)
    text, engine = res.text, res.engine
    log.info("[ocr] engine=%s -> %d chars", engine, len(text))

    if text.strip() and not _looks_low_quality(text):
        return text

    log.info("[ocr] low-quality result (engine=%s, %d chars) — attempting rescue", engine, len(text))

    # 1. Vision rescue: only if Gemini wasn't already attempted (and isn't down).
    if not res.gemini_tried and not res.gemini_failed and os.environ.get("GEMINI_API_KEY"):
        rescued = await asyncio.to_thread(_gemini_sync, image_bytes)
        if _better(rescued, text):
            log.info("[ocr] rescue=gemini_vision -> %d chars (was %d)", len(rescued), len(text))
            text = rescued
            if not _looks_low_quality(text):
                return text

    # 2. Text rescue: clean whatever text we have with the LLM (best-effort).
    if text.strip():
        import cards  # lazy import to avoid any ocr<->cards import cycle
        repaired = await cards.repair_ocr_text(text)
        if repaired and repaired.strip() != text.strip():
            log.info("[ocr] rescue=llm_repair -> %d chars (was %d)", len(repaired), len(text))
            text = repaired

    if not text.strip():
        raise OCRError("all OCR engines and rescue produced no text")
    return text
