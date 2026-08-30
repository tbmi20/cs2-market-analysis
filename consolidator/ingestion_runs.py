"""Logs one row to ingestion_runs per processed batch — powers the
dashboard's data-freshness display and surfaces a silently-failing poll
(see plan Section 5/6).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from db.models import IngestionRun


def log_ingestion_run(
    session: Session,
    marketplace: str,
    started_at: datetime,
    *,
    status: str,
    records_ingested: int,
    error_message: str | None = None,
) -> None:
    session.add(
        IngestionRun(
            marketplace=marketplace,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            status=status,
            records_ingested=records_ingested,
            error_message=error_message,
        )
    )
