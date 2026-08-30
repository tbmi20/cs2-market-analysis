"""Proves the "database is the seam" design (plan Section 3/9 step 4): this
analysis module is exercised purely against manually-inserted price_history
rows, with no Kafka, ingestion plugin, or consolidator involved at all.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from analysis.trend import confidence_tier, run
from db.models import AnalysisResult, PriceHistory, SkinVariant


def make_variant(db_session, **overrides) -> int:
    defaults = dict(weapon="AK-47", skin_name="Redline", wear_category="FT", float_bucket="FT")
    defaults.update(overrides)
    variant = SkinVariant(**defaults)
    db_session.add(variant)
    db_session.flush()
    return variant.id


def add_price_points(db_session, variant_id: int, *, price: float, count: int, days_ago: float) -> None:
    observed_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    for _ in range(count):
        db_session.add(
            PriceHistory(
                marketplace="csfloat",
                skin_variant_id=variant_id,
                price=price,
                event_type="listed",
                observed_at=observed_at,
            )
        )
    db_session.flush()


def test_confidence_tier_thresholds() -> None:
    assert confidence_tier(sample_count=5, relative_stddev=0.0, min_sample_count=10) == "low"
    assert confidence_tier(sample_count=15, relative_stddev=0.0, min_sample_count=10) == "medium"
    assert confidence_tier(sample_count=30, relative_stddev=0.0, min_sample_count=10) == "high"
    assert confidence_tier(sample_count=30, relative_stddev=0.9, min_sample_count=10) == "medium"


def test_run_computes_trend_and_volatility_from_manual_rows(db_session) -> None:
    variant_id = make_variant(db_session, weapon="AK-47", skin_name="Redline (test-trend)")

    # Current 7d window: 15 identical $100 observations 1-6 days ago.
    add_price_points(db_session, variant_id, price=100.0, count=15, days_ago=3)
    # Previous 7d window (7-14 days ago): 5 observations at $80.
    add_price_points(db_session, variant_id, price=80.0, count=5, days_ago=10)

    written = run(session=db_session, min_sample_count=10)
    assert written > 0

    results = db_session.execute(
        select(AnalysisResult).where(AnalysisResult.skin_variant_id == variant_id, AnalysisResult.window_days == 7)
    ).scalars().all()
    by_metric = {r.metric_type: r for r in results}

    assert by_metric["volatility"].value == 0.0  # identical prices -> zero std dev
    assert by_metric["volatility"].sample_count == 15
    assert by_metric["trend"].value == pytest.approx(0.25)  # (100-80)/80
    # 15 samples >= min(10) but < high-confidence multiplier (10*3=30), and not noisy.
    assert by_metric["trend"].confidence_tier == "medium"


def test_run_skips_trend_without_a_prior_window(db_session) -> None:
    variant_id = make_variant(db_session, weapon="AK-47", skin_name="Redline (test-no-history)")
    add_price_points(db_session, variant_id, price=100.0, count=12, days_ago=2)

    run(session=db_session, min_sample_count=10)

    results = db_session.execute(
        select(AnalysisResult).where(AnalysisResult.skin_variant_id == variant_id, AnalysisResult.window_days == 7)
    ).scalars().all()
    metric_types = {r.metric_type for r in results}
    assert metric_types == {"volatility"}  # no 'trend' — nothing to compare against


def test_run_marks_low_confidence_below_signal_threshold(db_session) -> None:
    variant_id = make_variant(db_session, weapon="AK-47", skin_name="Redline (test-low-n)")
    add_price_points(db_session, variant_id, price=100.0, count=3, days_ago=2)

    run(session=db_session, min_sample_count=10)

    result = db_session.execute(
        select(AnalysisResult).where(
            AnalysisResult.skin_variant_id == variant_id,
            AnalysisResult.window_days == 7,
            AnalysisResult.metric_type == "volatility",
        )
    ).scalar_one()
    assert result.confidence_tier == "low"
