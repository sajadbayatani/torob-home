"""A request id, so one HTTP request can be followed through the logs.

Bound once by the middleware and read anywhere below it, so every LLM log line
carries the same id. Two inferences for one request then show up as two lines
with the same id and different callers, which is exactly what makes a duplicate
inference visible.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

_current: ContextVar[str] = ContextVar("request_id", default="-")


def new_request_id() -> str:
    """A short, readable id. Not a secret, and not derived from the user."""
    return uuid.uuid4().hex[:12]


def current() -> str:
    """The id of the request in progress, or ``-`` outside one."""
    return _current.get()


def bind(value: str) -> None:
    _current.set(value)


__all__ = ["bind", "current", "new_request_id"]
