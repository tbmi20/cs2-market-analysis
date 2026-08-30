"""Shared fixtures. `db_session` runs each test inside a transaction that's
rolled back afterward, against the real dev Postgres (docker compose up
postgres) — no mocking of SQL, but nothing persists between tests either.

Code under test (consolidator.consumer.process_batch, in particular) calls
session.commit() itself. `join_transaction_mode="create_savepoint"` makes
those inner commits only release a SAVEPOINT, so the outer `transaction`
still rolls everything back at teardown — the standard SQLAlchemy 2.0 recipe
for nesting a real service's commits inside a disposable test transaction.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from db.session import engine


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
