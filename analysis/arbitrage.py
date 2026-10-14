"""Cross-marketplace arbitrage: compares each marketplace's current cheapest
active listing for the same skin_variant (plan Section 1: arbitrage is
"comparing two current facts", so this reads `listings` — the current-state
table — not price_history/price_window_stats, which trend/volatility use).

Needs >= 2 marketplaces with data for a skin_variant to produce anything
(plan Section 10) — in practice csfloat vs. skinport. Skinport rows carry
no float, so prices are compared per (weapon, skin, wear category) rather
than per float-bucketed skin_variant: the premium sub-buckets cover all of
Factory New, so a CSFloat FN listing would otherwise never meet a Skinport
one. Results are recorded against the wear category's default-bucket
variant.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from itertools import combinations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from analysis.trend import confidence_tier
from consolidator.skin_variants import get_or_create_skin_variant
from db.models import AnalysisResult, Listing, MarketplaceFee, SkinVariant
from db.session import SessionLocal

logger = logging.getLogger(__name__)


def run(session: Session | None = None, min_sample_count: int | None = None) -> int:
    owns_session = session is None
    session = session or SessionLocal()
    min_sample_count = min_sample_count if min_sample_count is not None else int(
        os.environ.get("SIGNAL_MIN_SAMPLE_COUNT", "10")
    )

    written = 0
    try:
        fees = {row.marketplace: row.seller_fee_pct for row in session.execute(select(MarketplaceFee)).scalars()}

        rows = session.execute(
            select(
                SkinVariant.weapon,
                SkinVariant.skin_name,
                SkinVariant.wear_category,
                Listing.marketplace,
                func.min(Listing.listing_price).label("min_price"),
                # Sum, not count: one Skinport row stands for `quantity` units on sale.
                func.sum(Listing.quantity).label("active_count"),
            )
            .join(SkinVariant, Listing.skin_variant_id == SkinVariant.id)
            .where(Listing.status == "active", Listing.listing_price.is_not(None))
            .group_by(SkinVariant.weapon, SkinVariant.skin_name, SkinVariant.wear_category, Listing.marketplace)
        ).all()

        by_skin: dict[tuple[str, str, str], dict[str, tuple[float, int]]] = defaultdict(dict)
        for row in rows:
            by_skin[(row.weapon, row.skin_name, row.wear_category)][row.marketplace] = (row.min_price, row.active_count)

        for (weapon, skin_name, wear_category), marketplaces in by_skin.items():
            if len(marketplaces) < 2:
                continue  # arbitrage needs >= 2 sources

            skin_variant_id = get_or_create_skin_variant(
                session, weapon=weapon, skin_name=skin_name, wear_category=wear_category, float_value=None
            )

            for (mp_a, stats_a), (mp_b, stats_b) in combinations(marketplaces.items(), 2):
                written += _record_pair(session, skin_variant_id, mp_a, stats_a, mp_b, stats_b, fees, min_sample_count)

        session.commit()
    finally:
        if owns_session:
            session.close()

    logger.info("wrote %d arbitrage rows", written)
    return written


def _record_pair(
    session: Session,
    skin_variant_id: int,
    mp_a: str,
    stats_a: tuple[float, int],
    mp_b: str,
    stats_b: tuple[float, int],
    fees: dict[str, float],
    min_sample_count: int,
) -> int:
    price_a, count_a = stats_a
    price_b, count_b = stats_b
    if price_a <= price_b:
        cheap_mp, cheap_price, cheap_count = mp_a, price_a, count_a
        expensive_mp, expensive_price, expensive_count = mp_b, price_b, count_b
    else:
        cheap_mp, cheap_price, cheap_count = mp_b, price_b, count_b
        expensive_mp, expensive_price, expensive_count = mp_a, price_a, count_a

    expensive_fee_pct = fees.get(expensive_mp)
    if expensive_fee_pct is None:
        logger.warning("no marketplace_fees row for %r — skipping arbitrage for skin_variant %s", expensive_mp, skin_variant_id)
        return 0

    # Buy on the cheap marketplace, sell on the expensive one — only the sell
    # side's fee is modeled; there's no buyer-fee field (plan Section 5).
    # Trade-hold friction (plan Section 10 — still an open, undecided
    # question) is deliberately NOT applied: this is the raw net-of-fees gap.
    net_gap = expensive_price * (1 - expensive_fee_pct / 100) - cheap_price
    if net_gap <= 0:
        return 0  # the fee alone eats the whole spread — not a real opportunity

    sample_count = min(cheap_count, expensive_count)  # liquidity proxy: thin listings = fragile opportunity
    tier = confidence_tier(sample_count, relative_stddev=None, min_sample_count=min_sample_count)

    session.add(
        AnalysisResult(
            skin_variant_id=skin_variant_id,
            metric_type="arbitrage",
            window_days=None,
            value=net_gap,
            sample_count=sample_count,
            confidence_tier=tier,
            details={
                "cheap_marketplace": cheap_mp,
                "cheap_price": cheap_price,
                "cheap_active_listings": cheap_count,
                "expensive_marketplace": expensive_mp,
                "expensive_price": expensive_price,
                "expensive_active_listings": expensive_count,
                "expensive_seller_fee_pct": expensive_fee_pct,
                "gap_pct": net_gap / cheap_price,
            },
        )
    )
    return 1
