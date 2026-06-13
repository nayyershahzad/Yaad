"""
log_setup.py — one place to make app logs reach stderr/journald.

The app modules already use `logging.getLogger(__name__)`; without configuring the
root logger those INFO lines never surface under uvicorn (root defaults to WARNING).
configure() wires a stderr handler at LOG_LEVEL. Call it once at process start
(main.py, reconcile.py).
"""
from __future__ import annotations

import os
from logging.config import dictConfig

_configured = False


def configure() -> None:
    global _configured
    if _configured:
        return
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s | %(message)s"}},
        "handlers": {"stderr": {"class": "logging.StreamHandler",
                                "stream": "ext://sys.stderr", "formatter": "std"}},
        "root": {"handlers": ["stderr"], "level": level},
    })
    _configured = True
