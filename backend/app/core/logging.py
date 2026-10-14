"""
Structured logging with sensitive-data redaction.

Configures JSON-style structured logging for production
and human-readable logging for development.
Redacts known secret patterns from log output.
"""

from __future__ import annotations

import logging
import re
import sys


# Patterns that look like secrets — redacted from log output
_SECRET_PATTERNS = [
    re.compile(r"(sk-[a-zA-Z0-9]{20,})", re.IGNORECASE),          # OpenAI-style
    re.compile(r"(AIza[a-zA-Z0-9_-]{30,})", re.IGNORECASE),       # Google-style
    re.compile(r"(sk-ant-[a-zA-Z0-9_-]{20,})", re.IGNORECASE),    # Anthropic-style
    re.compile(r"(Bearer\s+[a-zA-Z0-9._\-]+)", re.IGNORECASE),    # Bearer tokens
    re.compile(r"(api[_-]?key\s*[=:]\s*\S+)", re.IGNORECASE),     # key=value
]

_REDACTION = "[REDACTED]"


def redact_secrets(message: str) -> str:
    """Replace known secret patterns in a log message."""
    for pattern in _SECRET_PATTERNS:
        message = pattern.sub(_REDACTION, message)
    return message


class RedactingFormatter(logging.Formatter):
    """Formatter that redacts secrets from log output."""

    def format(self, record: logging.LogRecord) -> str:
        original = super().format(record)
        return redact_secrets(original)


def setup_logging(level: str = "info", is_development: bool = True) -> None:
    """Configure application-wide logging."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Clear existing handlers
    root = logging.getLogger()
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)

    if is_development:
        fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    else:
        fmt = '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}'

    handler.setFormatter(RedactingFormatter(fmt))
    root.addHandler(handler)
    root.setLevel(log_level)

    # Quiet noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("litellm").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger for a module."""
    return logging.getLogger(f"llm_router.{name}")
