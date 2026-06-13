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


def _ocr_sync(image_bytes: bytes) -> tuple[str, str]:
    img = _open(image_bytes)
    try:
        return _gemini(img), "gemini"
    except _Transient as e:
        log.warning("[ocr] Gemini unavailable (%s) -> Tesseract fallback", e)
        return _tesseract(img), "tesseract"


async def ocr_image(image_bytes: bytes, mime: str | None = None) -> str:
    """Return cleaned page text. Gemini first, Tesseract on transient Gemini
    failure. Raises OCRError only if every engine fails. Runs the sync SDKs in a
    thread so the event loop isn't blocked."""
    text, engine = await asyncio.to_thread(_ocr_sync, image_bytes)
    log.info("[ocr] engine=%s -> %d chars", engine, len(text))
    return text
