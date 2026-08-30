"""FastAPI dependencies. `get_db` is overridden in tests to hand back a
transactional test session instead (see tests/conftest.py's db_session
fixture pattern) — this is the only thing routers depend on for data access.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from db.session import SessionLocal


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
