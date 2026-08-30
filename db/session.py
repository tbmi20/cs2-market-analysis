"""Engine/session factory. Reads connection settings from environment
variables (see .env.example), shared by the consolidator, analysis modules,
and API — all of which only ever read/write Postgres directly.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()


def database_url() -> str:
    user = os.environ.get("DB_USER", "postgres")
    password = os.environ.get("DB_PASSWORD", "postgres")
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    name = os.environ.get("DB_NAME", "cs2_market")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


engine = create_engine(database_url(), future=True)
SessionLocal: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False)
