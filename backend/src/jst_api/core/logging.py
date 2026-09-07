"""Structured logging with PII redaction.

Traces and logs are treated as an untrusted-egress surface: anything that could
carry a traveller's free text or an API secret is redacted before it is emitted.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

_SECRET_KEYS = {
    "api_key",
    "openai_api_key",
    "anthropic_api_key",
    "google_maps_api_key",
    "authorization",
    "admin_token",
    "jwt_secret",
    "stripe_secret_key",
    "password",
    "token",
    "secret",
}

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
#: Phone numbers need explicit separators, and must not be preceded or followed by
#: a digit/date/time delimiter — otherwise ISO timestamps and IDs get redacted too.
_PHONE_RE = re.compile(
    r"(?<![\d\-:.T])(?:\+\d{1,3}[ -]?)?(?:\(\d{2,4}\)[ -]?|\d{2,4}[ -])\d{3,4}[ -]\d{3,4}(?![\d\-:.])"
)
_CARD_RE = re.compile(r"(?<!\d)(?:\d{4}[ -]){3}\d{3,4}(?!\d)|(?<!\d)\d{15,16}(?!\d)")
_PASSPORT_RE = re.compile(r"\b[A-Z]{1,2}\d{7,9}\b")

#: Keys whose values are structural, never user content.
_SKIP_KEYS = {
    "timestamp",
    "level",
    "event",
    "logger",
    "trace_id",
    "span_id",
    "analysis_id",
    "run_id",
}

REDACTED = "[redacted]"


def redact_text(value: str) -> str:
    value = _EMAIL_RE.sub("[email]", value)
    value = _CARD_RE.sub("[card]", value)
    value = _PASSPORT_RE.sub("[passport]", value)
    return _PHONE_RE.sub("[phone]", value)


def redact_value(key: str, value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "[truncated]"
    if key.lower() in _SECRET_KEYS:
        return REDACTED
    if key.lower() in _SKIP_KEYS:
        return value
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact_value(k, v, depth=depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(key, v, depth=depth + 1) for v in value]
    return value


def _redaction_processor(
    _logger: Any, _name: str, event_dict: MutableMapping[str, Any]
) -> Mapping[str, Any]:
    return {k: redact_value(k, v) for k, v in event_dict.items()}


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    logging.basicConfig(
        format="%(message)s", stream=sys.stdout, level=getattr(logging, level.upper(), logging.INFO)
    )
    renderer: Any = (
        structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redaction_processor,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
