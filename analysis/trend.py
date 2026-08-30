"""Rolling average / trend / volatility / confidence-tier analysis — reading
only from the `price_window_stats` view (Postgres), no Kafka or ingestion
plugin involved. This is the module plan Section 9 step 4 asks to prove
against manually-inserted rows, to demonstrate "the database is the seam"
(plan Section 3): it has zero knowledge of how price_history got populated.

Writes two analysis_results rows per (skin_variant, window) that has data:
- 'volatility' — relative std dev (stddev/mean) of price in the window
- 'trend' — % change vs. the prior window of the same length, only when a
  prior window's average exists (an item with no history that far back just
  doesn't get a trend row yet)

analysis_results has no uniqueness constraint (see plan Section 5), so this
is safe to run repeatedly — each run appends a fresh snapshot stamped with
computed_at rather than overwriting the last one.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import text
from sqlalchemy.orm import Session

from db.models import AnalysisResult
from db.session import SessionLocal

logger = logging.getLogger(__name__)

# Starting heuristic for confidence tiering — the plan (Section 6) only says
# "derived from n + relative std. dev", not the actual cutoffs. Tune these
# once real ingested data shows what "noisy" looks like for this market.
HIGH_CONFIDENCE_SAMPLE_MULTIPLIER = 3
NOISY_RELATIVE_STDDEV_CUTOFF = 0.5

_QUERY = text(
    "SELECT skin_variant_id, window_days, avg_price, stddev_price, sample_count, previous_avg_price"
    " FROM price_window_stats"
)


def confidence_tier(sample_count: int, relative_stddev: float | None, min_sample_count: int) -> str:
    if sample_count < min_sample_count:
        return "low"
    high_sample = sample_count >= min_sample_count * HIGH_CONFIDENCE_SAMPLE_MULTIPLIER
    noisy = relative_stddev is not None and relative_stddev > NOISY_RELATIVE_STDDEV_CUTOFF
    return "high" if high_sample and not noisy else "medium"


def run(session: Session | None = None, min_sample_count: int | None = None) -> int:
    """Computes trend + volatility for every skin_variant with current-window
    price_history data. Returns the number of analysis_results rows written.
    """
    owns_session = session is None
    session = session or SessionLocal()
    min_sample_count = min_sample_count if min_sample_count is not None else int(
        os.environ.get("SIGNAL_MIN_SAMPLE_COUNT", "10")
    )

    written = 0
    try:
        for row in session.execute(_QUERY).all():
            relative_stddev = (
                row.stddev_price / row.avg_price if row.stddev_price is not None and row.avg_price else None
            )
            tier = confidence_tier(row.sample_count, relative_stddev, min_sample_count)

            session.add(
                AnalysisResult(
                    skin_variant_id=row.skin_variant_id,
                    metric_type="volatility",
                    window_days=row.window_days,
                    value=relative_stddev,
                    sample_count=row.sample_count,
                    confidence_tier=tier,
                )
            )
            written += 1

            if row.previous_avg_price:
                pct_change = (row.avg_price - row.previous_avg_price) / row.previous_avg_price
                session.add(
                    AnalysisResult(
                        skin_variant_id=row.skin_variant_id,
                        metric_type="trend",
                        window_days=row.window_days,
                        value=pct_change,
                        sample_count=row.sample_count,
                        confidence_tier=tier,
                    )
                )
                written += 1

        session.commit()
    finally:
        if owns_session:
            session.close()

    logger.info("wrote %d analysis_results rows", written)
    return written
