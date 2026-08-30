"""Exercises the arbitrage module against manually-inserted rows — no real
Skinport integration involved (see ingestion/skinport/plugin.py's stub).

Assertions are scoped to each test's own skin_variant_id rather than the
global `written` count, since the real dev database has actual csfloat data
(and possibly live skinport-stub data) coexisting in the same tables.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from analysis.arbitrage import run
from db.models import AnalysisResult, Listing, MarketplaceFee, SkinVariant


def make_variant(db_session, **overrides) -> int:
    # "(arbitrage-test)" marker avoids colliding with the real AK-47 | Slate
    # skin_variant already ingested from live CSFloat data in dev.
    defaults = dict(weapon="AK-47", skin_name="Slate (arbitrage-test)", wear_category="FN", float_bucket="FN (lower)")
    defaults.update(overrides)
    variant = SkinVariant(**defaults)
    db_session.add(variant)
    db_session.flush()
    return variant.id


def add_listing(db_session, *, marketplace: str, listing_id: str, variant_id: int, price: float) -> None:
    db_session.add(
        Listing(
            marketplace=marketplace,
            listing_id=listing_id,
            skin_variant_id=variant_id,
            listing_price=price,
        )
    )
    db_session.flush()


def set_fee(db_session, marketplace: str, seller_fee_pct: float) -> None:
    # marketplace_fees already has real seeded rows (csfloat, skinport) —
    # upsert so this works regardless of whether one exists, and the
    # savepoint rollback still restores whatever was there before the test.
    stmt = pg_insert(MarketplaceFee).values(marketplace=marketplace, seller_fee_pct=seller_fee_pct)
    stmt = stmt.on_conflict_do_update(
        index_elements=[MarketplaceFee.marketplace], set_={"seller_fee_pct": stmt.excluded.seller_fee_pct}
    )
    db_session.execute(stmt)
    db_session.flush()


def results_for(db_session, variant_id: int) -> list[AnalysisResult]:
    return list(
        db_session.execute(
            select(AnalysisResult).where(AnalysisResult.skin_variant_id == variant_id, AnalysisResult.metric_type == "arbitrage")
        ).scalars()
    )


def test_detects_arbitrage_across_two_marketplaces(db_session) -> None:
    variant_id = make_variant(db_session)
    set_fee(db_session, "csfloat", 0.0)
    set_fee(db_session, "skinport", 0.0)
    add_listing(db_session, marketplace="csfloat", listing_id="cf-1", variant_id=variant_id, price=54.45)
    add_listing(db_session, marketplace="skinport", listing_id="sp-1", variant_id=variant_id, price=40.00)

    run(session=db_session, min_sample_count=10)

    results = results_for(db_session, variant_id)
    assert len(results) == 1
    result = results[0]
    assert result.value == pytest.approx(14.45)
    assert result.details["cheap_marketplace"] == "skinport"
    assert result.details["expensive_marketplace"] == "csfloat"
    assert result.confidence_tier == "low"  # sample_count=1 < min_sample_count=10


def test_fee_can_erase_the_spread(db_session) -> None:
    # skinport is the pricier ("expensive"/sell) side here, so its fee is the
    # one that applies — set it steep enough to wipe out the raw gap.
    variant_id = make_variant(db_session, skin_name="Slate (fee-test)")
    set_fee(db_session, "csfloat", 0.0)
    set_fee(db_session, "skinport", 50.0)
    add_listing(db_session, marketplace="csfloat", listing_id="cf-2", variant_id=variant_id, price=40.00)
    add_listing(db_session, marketplace="skinport", listing_id="sp-2", variant_id=variant_id, price=54.45)

    run(session=db_session, min_sample_count=10)

    assert results_for(db_session, variant_id) == []


def test_no_arbitrage_row_with_only_one_marketplace(db_session) -> None:
    variant_id = make_variant(db_session, skin_name="Slate (single-market)")
    set_fee(db_session, "csfloat", 0.0)
    add_listing(db_session, marketplace="csfloat", listing_id="cf-3", variant_id=variant_id, price=54.45)

    run(session=db_session, min_sample_count=10)

    assert results_for(db_session, variant_id) == []


def test_skips_when_marketplace_fee_missing(db_session) -> None:
    # Fake marketplace names with no seeded marketplace_fees row at all
    # (unlike csfloat/skinport, which always have a placeholder row — see
    # migrations/versions/cb9754b5988a and the skinport stub's seed insert).
    variant_id = make_variant(db_session, skin_name="Slate (no-fee-row)")
    add_listing(db_session, marketplace="fakemarket_a", listing_id="fa-1", variant_id=variant_id, price=54.45)
    add_listing(db_session, marketplace="fakemarket_b", listing_id="fb-1", variant_id=variant_id, price=40.00)

    run(session=db_session, min_sample_count=10)

    assert results_for(db_session, variant_id) == []
