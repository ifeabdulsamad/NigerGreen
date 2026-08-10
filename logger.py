"""Structured JSON logging (structlog) with request tracing helpers.

Every event carries: timestamp, event, question_hash, selected_table,
sql_hash, duration_ms, error_code — ready for forwarding to a log sink.
"""
from __future__ import annotations

import hashlib
import logging
import sys
from typing import Optional

import structlog


def setup_logging(level: str = "INFO", json: bool = True) -> None:
    """Configure structlog + stdlib logging once per process."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Keep stdlib loggers quiet unless configured.
    logging.basicConfig(level=numeric_level, format="%(message)s")
    for noisy in ("urllib3", "httpx", "openai", "litellm"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str = "naijagreen"):
    return structlog.get_logger(name)


def _digest(text: str) -> str:
    """Short stable hash used for trace fields (never for security)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def question_hash(question: str) -> str:
    return _digest(question)


def sql_hash(sql: str) -> str:
    return _digest(sql)
