"""Serves the latest analysis_results snapshot per (skin_variant, metric_type,
window_days) — analysis_results is append-only (plan Section 5), so "current"
means the newest computed_at within that group, not the whole history.

Suppression (plan Section 2/6: hide sub-threshold metrics on the dashboard
rather than showing a misleading number) happens here, not in the analysis
modules — they always write a row with its real sample_count and confidence
tier; this is where "suppressed" gets computed and attached, so the frontend
can render "not enough data" using the real sample size rather than nothing.
"""

from __future__ import annotations

import os
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from api.dependencies import get_db
from api.schemas import AnalysisResultOut
from db.models import AnalysisResult, SkinVariant

router = APIRouter()

MetricType = Literal["trend", "volatility", "arbitrage", "underpriced_listing"]


def _signal_min_sample_count() -> int:
    return int(os.environ.get("SIGNAL_MIN_SAMPLE_COUNT", "10"))


@router.get("/analysis", response_model=list[AnalysisResultOut])
def list_analysis_results(
    metric_type: MetricType = Query(...),
    window_days: int | None = Query(None, description="Required for 'trend'/'volatility'; ignored otherwise"),
    skin_variant_id: int | None = Query(None),
    include_suppressed: bool = Query(True, description="If false, drop below-threshold rows entirely instead of flagging them"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[AnalysisResultOut]:
    group_cols = (AnalysisResult.skin_variant_id, AnalysisResult.metric_type, AnalysisResult.window_days)
    latest = select(*group_cols, func.max(AnalysisResult.computed_at).label("max_computed_at")).where(
        AnalysisResult.metric_type == metric_type
    )
    if window_days is not None:
        latest = latest.where(AnalysisResult.window_days == window_days)
    if skin_variant_id is not None:
        latest = latest.where(AnalysisResult.skin_variant_id == skin_variant_id)
    latest = latest.group_by(*group_cols).subquery()

    query = (
        select(AnalysisResult, SkinVariant)
        .join(SkinVariant, SkinVariant.id == AnalysisResult.skin_variant_id)
        .join(
            latest,
            and_(
                AnalysisResult.skin_variant_id == latest.c.skin_variant_id,
                AnalysisResult.metric_type == latest.c.metric_type,
                # window_days is NULL for arbitrage/underpriced_listing — plain
                # `==` never matches NULL, so use NULL-safe comparison.
                AnalysisResult.window_days.is_not_distinct_from(latest.c.window_days),
                AnalysisResult.computed_at == latest.c.max_computed_at,
            ),
        )
        .order_by(AnalysisResult.value.desc().nullslast())
        .limit(limit)
    )

    min_sample_count = _signal_min_sample_count()
    results = []
    for analysis_result, skin_variant in db.execute(query).all():
        suppressed = analysis_result.sample_count < min_sample_count
        if suppressed and not include_suppressed:
            continue
        results.append(
            AnalysisResultOut(
                id=analysis_result.id,
                skin_variant_id=analysis_result.skin_variant_id,
                weapon=skin_variant.weapon,
                skin_name=skin_variant.skin_name,
                wear_category=skin_variant.wear_category,
                float_bucket=skin_variant.float_bucket,
                metric_type=analysis_result.metric_type,
                window_days=analysis_result.window_days,
                value=analysis_result.value,
                sample_count=analysis_result.sample_count,
                confidence_tier=analysis_result.confidence_tier,
                computed_at=analysis_result.computed_at,
                details=analysis_result.details,
                suppressed=suppressed,
            )
        )
    return results
