"""Database session dependency wiring for the API layer."""

from __future__ import annotations

from app.db.session import get_db  # noqa: F401  (re-exported for FastAPI)
