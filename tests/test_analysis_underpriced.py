"""Exercises the same-marketplace underpriced-listing module against
manually-inserted rows. Assertions are scoped to each test's own
skin_variant_id, since the real dev database has real csfloat data
coexisting in the same tables.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from analysis.underpriced import run
from db.models import AnalysisResult, Listing, PriceHistory, SkinVariant


def make_variant(db_session, **overrides) -> int:
    # "(underpriced-test)" marker avoids colliding with the real AWP | Asiimov
    # skin_variant already ingested from live CSFloat data in dev.
    defaults = dict(weapon="AWP", skin_name="Asiimov (underpriced-test)", wear_category="FT", float_bucket="FT")
    defaults.update(overrides)
    variant = SkinVariant(**defaults)
    db_session.add(variant)
    db_session.flush()
    return variant.id


def add_history(db_session, *, marketplace: str, variant_id: int, price: float, count: int = 1, days_ago: float = 1) -> None:
    observed_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    for _ in range(count):
        db_session.add(
            PriceHistory(
                marketplace=marketplace,
                skin_variant_id=variant_id,
                price=price,
                event_type="listed",
                observed_at=observed_at,
            )
        )
    db_session.flush()


def add_listing(db_session, *, marketplace: str, listing_id: str, variant_id: int, price: float, status: str = "active") -> int:
    listing = Listing(
        marketplace=marketplace,
        listing_id=listing_id,
        skin_variant_id=variant_id,
        listing_price=price,
        status=status,
    )
    db_session.add(listing)
    db_session.flush()
    return listing.id


def results_for(db_session, variant_id: int) -> list[AnalysisResult]:
    return list(
        db_session.execute(
            select(AnalysisResult).where(
                AnalysisResult.skin_variant_id == variant_id, AnalysisResult.metric_type == "underpriced_listing"
            )
        ).scalars()
    )


def test_flags_a_listing_priced_well_below_its_marketplace_baseline(db_session) -> None:
    variant_id = make_variant(db_session)
    # Baseline: several csfloat listings clustered around $100.
    add_history(db_session, marketplace="csfloat", variant_id=variant_id, price=100.0, count=9)
    # One active listing far below that.
    add_listing(db_session, marketplace="csfloat", listing_id="cheap-1", variant_id=variant_id, price=60.0)

    run(session=db_session, min_sample_count=10)

    results = results_for(db_session, variant_id)
    assert len(results) == 1
    assert results[0].details["listing_price"] == pytest.approx(60.0)
    assert results[0].value > 0  # discount_pct


def test_does_not_flag_a_listing_at_or_above_baseline(db_session) -> None:
    variant_id = make_variant(db_session, skin_name="Asiimov (not-cheap)")
    add_history(db_session, marketplace="csfloat", variant_id=variant_id, price=100.0, count=9)
    add_listing(db_session, marketplace="csfloat", listing_id="normal-1", variant_id=variant_id, price=105.0)

    run(session=db_session, min_sample_count=10)

    assert results_for(db_session, variant_id) == []


def test_does_not_compare_across_marketplaces(db_session) -> None:
    # A listing cheap relative to a DIFFERENT marketplace's baseline shouldn't
    # be flagged — only same-marketplace peers count (see module docstring).
    variant_id = make_variant(db_session, skin_name="Asiimov (cross-market)")
    add_history(db_session, marketplace="skinport", variant_id=variant_id, price=200.0, count=9)
    add_listing(db_session, marketplace="csfloat", listing_id="cf-only", variant_id=variant_id, price=100.0)

    run(session=db_session, min_sample_count=10)

    assert results_for(db_session, variant_id) == []


def test_does_not_flag_a_listing_no_longer_on_sale(db_session) -> None:
    variant_id = make_variant(db_session, skin_name="Asiimov (sold-cheap)")
    add_history(db_session, marketplace="csfloat", variant_id=variant_id, price=100.0, count=9)
    add_listing(db_session, marketplace="csfloat", listing_id="sold-cheap", variant_id=variant_id, price=60.0, status="sold")

    run(session=db_session, min_sample_count=10)

    assert results_for(db_session, variant_id) == []
