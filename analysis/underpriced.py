"""Same-marketplace underpriced listings — a specific active listing priced
notably below that *same marketplace's* own recent rolling average for the
same skin_variant. This is a deliberate addition beyond the plan's original
two-signal framing (arbitrage across marketplaces, trend over time; plan
Section 1) — sometimes the deal is against a site's own recent history, not
another marketplace, and doesn't need a second marketplace to be meaningful.

Unlike analysis/trend.py's price_window_stats view (intentionally
marketplace-agnostic, since a broad trend is a cross-market question), the
baseline here is computed per (marketplace, skin_variant) — a listing is only
compared against its own marketplace's peers.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from analysis.trend import confidence_tier
from db.models import AnalysisResult, Listing
from db.session import SessionLocal

logger = logging.getLogger(__name__)

# Starting heuristic, same caveat as analysis/trend.py's tiering constants —
# not specified by the plan, tune once real data shows what's actually rare.
ZSCORE_THRESHOLD = 2.0  # used when the baseline has a usable std dev
FLAT_DISCOUNT_THRESHOLD = 0.15  # fallback when std dev is 0/undefined (e.g. n=1)

_BASELINE_QUERY = text(
    """
    SELECT marketplace, skin_variant_id,
           AVG(price) AS avg_price, STDDEV_SAMP(price) AS stddev_price, COUNT(*) AS sample_count
    FROM price_history
    WHERE event_type = 'listed' AND observed_at >= NOW() - INTERVAL '7 days'
    GROUP BY marketplace, skin_variant_id
    """
)


def run(session: Session | None = None, min_sample_count: int | None = None) -> int:
    owns_session = session is None
    session = session or SessionLocal()
    min_sample_count = min_sample_count if min_sample_count is not None else int(
        os.environ.get("SIGNAL_MIN_SAMPLE_COUNT", "10")
    )

    written = 0
    try:
        baselines = {(row.marketplace, row.skin_variant_id): row for row in session.execute(_BASELINE_QUERY).all()}

        active_listings = session.execute(
            select(Listing.id, Listing.marketplace, Listing.listing_id, Listing.skin_variant_id, Listing.listing_price).where(
                Listing.listing_price.is_not(None)
            )
        ).all()

        for listing in active_listings:
            baseline = baselines.get((listing.marketplace, listing.skin_variant_id))
            if baseline is None or not baseline.avg_price:
                continue

            discount_pct = (baseline.avg_price - listing.listing_price) / baseline.avg_price
            if discount_pct <= 0:
                continue  # at or above average — not a deal

            if baseline.stddev_price:
                z_score = (baseline.avg_price - listing.listing_price) / baseline.stddev_price
                is_underpriced = z_score >= ZSCORE_THRESHOLD
            else:
                # n=1, or every observation identical — can't compute a z-score,
                # so fall back to a flat percentage-below-average threshold.
                z_score = None
                is_underpriced = discount_pct >= FLAT_DISCOUNT_THRESHOLD

            if not is_underpriced:
                continue

            tier = confidence_tier(baseline.sample_count, relative_stddev=None, min_sample_count=min_sample_count)

            session.add(
                AnalysisResult(
                    skin_variant_id=listing.skin_variant_id,
                    metric_type="underpriced_listing",
                    window_days=7,
                    value=discount_pct,
                    sample_count=baseline.sample_count,
                    confidence_tier=tier,
                    details={
                        "marketplace": listing.marketplace,
                        "listing_pk": listing.id,
                        "marketplace_listing_id": listing.listing_id,
                        "listing_price": listing.listing_price,
                        "baseline_avg_price": baseline.avg_price,
                        "baseline_stddev_price": baseline.stddev_price,
                        "z_score": z_score,
                    },
                )
            )
            written += 1

        session.commit()
    finally:
        if owns_session:
            session.close()

    logger.info("wrote %d underpriced_listing rows", written)
    return written
