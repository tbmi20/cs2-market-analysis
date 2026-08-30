"""Data-freshness display (plan Section 6/9): the most recent ingestion_runs
row per marketplace, regardless of status — a run that's failing repeatedly
should be visible as stale/broken, not silently omitted.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from api.dependencies import get_db
from api.schemas import FreshnessOut
from db.models import IngestionRun

router = APIRouter()


@router.get("/freshness", response_model=list[FreshnessOut])
def list_freshness(db: Session = Depends(get_db)) -> list[FreshnessOut]:
    latest = select(IngestionRun.marketplace, func.max(IngestionRun.started_at).label("max_started_at")).group_by(
        IngestionRun.marketplace
    ).subquery()

    query = select(IngestionRun).join(
        latest,
        and_(
            IngestionRun.marketplace == latest.c.marketplace,
            IngestionRun.started_at == latest.c.max_started_at,
        ),
    )

    return [
        FreshnessOut(
            marketplace=run.marketplace,
            last_successful_poll=run.finished_at if run.status == "success" else None,
            last_status=run.status,
            last_records_ingested=run.records_ingested,
        )
        for run in db.execute(query).scalars()
    ]
