"""Shared API helpers: error envelope + dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db


def db_session(session: Session = Depends(get_db)) -> Session:
    return session


def commit(session: Session) -> Session:
    """Persist everything the command layer wrote (explicit, per command)."""
    session.commit()
    return session


class ApiError(HTTPException):
    def __init__(self, message: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.message = message


__all__ = ["ApiError", "commit", "db_session", "get_db"]
