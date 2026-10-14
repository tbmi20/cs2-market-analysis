"""Integration tests against the real dev Postgres (see conftest.db_session) —
these exercise actual SQL (on_conflict_do_update, the float_bucket queries),
not mocks, per the "prove it against real rows" approach from the plan's
build order.

Skin names below use a distinctive "(consolidator-test)" marker, and
assertions scope by skin_variant_id/listing_id rather than a blanket
marketplace filter, since the real dev database has genuine csfloat data
(and possibly live skinport data) coexisting in the same tables.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from consolidator.consumer import expire_stale_listings, process_batch, upsert_listing
from consolidator.float_buckets import resolve_float_bucket
from consolidator.skin_variants import get_or_create_skin_variant
from db.models import IngestionRun, Listing, PriceHistory, SkinVariant
from ingestion.common.schema import NormalizedListing


def make_listing(**overrides) -> NormalizedListing:
    defaults = dict(
        marketplace="csfloat",
        listing_id="test-listing-1",
        weapon="AK-47",
        skin_name="Redline (consolidator-test)",
        wear_category="FT",
        float_value=0.20,
        rarity="4",
        listing_price=50.0,
        buy_order_price=None,
        raw_payload={"id": "test-listing-1"},
        observed_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return NormalizedListing(**defaults)


def test_resolve_float_bucket_prefers_premium(db_session) -> None:
    # 0.02 falls inside "FN (upper)" (0.01-0.03), a premium sub-bucket of FN.
    assert resolve_float_bucket(db_session, "FN", 0.02) == "FN (upper)"


def test_resolve_float_bucket_falls_back_to_default(db_session) -> None:
    # 0.20 isn't in any premium bucket; falls back to the default FT range.
    assert resolve_float_bucket(db_session, "FT", 0.20) == "FT"


def test_resolve_float_bucket_top_of_range_is_inclusive(db_session) -> None:
    assert resolve_float_bucket(db_session, "BS", 1.0) == "Battle-Scarred (max)"


def test_get_or_create_skin_variant_is_idempotent(db_session) -> None:
    first = get_or_create_skin_variant(
        db_session, weapon="AWP", skin_name="Asiimov (consolidator-test)", wear_category="FT", float_value=0.20
    )
    second = get_or_create_skin_variant(
        db_session, weapon="AWP", skin_name="Asiimov (consolidator-test)", wear_category="FT", float_value=0.22
    )

    assert first == second
    count = db_session.execute(
        select(SkinVariant).where(SkinVariant.weapon == "AWP", SkinVariant.skin_name == "Asiimov (consolidator-test)")
    ).all()
    assert len(count) == 1


def test_upsert_listing_dedups_on_marketplace_and_listing_id(db_session) -> None:
    upsert_listing(db_session, make_listing(listing_price=50.0))
    upsert_listing(db_session, make_listing(listing_price=55.0))  # same listing_id, price changed

    rows = db_session.execute(
        select(Listing).where(Listing.marketplace == "csfloat", Listing.listing_id == "test-listing-1")
    ).all()
    assert len(rows) == 1
    listing = rows[0][0]
    assert listing.listing_price == 55.0

    # price_history is append-only — both observations should be kept.
    history = db_session.execute(select(PriceHistory).where(PriceHistory.skin_variant_id == listing.skin_variant_id)).all()
    assert len(history) == 2


def test_upsert_listing_records_buy_order_price_separately(db_session) -> None:
    upsert_listing(db_session, make_listing(listing_id="test-listing-3", listing_price=50.0, buy_order_price=42.0))

    listing = db_session.execute(
        select(Listing).where(Listing.marketplace == "csfloat", Listing.listing_id == "test-listing-3")
    ).scalar_one()
    history = db_session.execute(select(PriceHistory).where(PriceHistory.skin_variant_id == listing.skin_variant_id)).all()
    event_types = sorted(row[0].event_type for row in history)
    assert event_types == ["buy_order", "listed"]


def test_process_batch_logs_ingestion_run(db_session) -> None:
    process_batch(db_session, "csfloat", [make_listing(listing_id="test-listing-2")])

    # process_batch appends exactly one row per call — the newest one by id
    # is guaranteed to be the one just written (real csfloat runs may have
    # logged earlier rows for the same marketplace).
    latest = db_session.execute(
        select(IngestionRun).where(IngestionRun.marketplace == "csfloat").order_by(IngestionRun.id.desc()).limit(1)
    ).scalar_one()
    assert latest.status == "success"
    assert latest.records_ingested == 1


def get_listing(db_session, listing_id: str) -> Listing:
    return db_session.execute(
        select(Listing).where(Listing.marketplace == "csfloat", Listing.listing_id == listing_id)
    ).scalar_one()


def history_for(db_session, listing: Listing) -> list[tuple[str, float]]:
    rows = db_session.execute(
        select(PriceHistory).where(PriceHistory.skin_variant_id == listing.skin_variant_id).order_by(PriceHistory.id)
    ).scalars()
    return [(row.event_type, row.price) for row in rows]


def test_reobserving_unchanged_listing_adds_no_price_history(db_session) -> None:
    first_seen = datetime.now(timezone.utc) - timedelta(minutes=5)
    upsert_listing(db_session, make_listing(listing_id="test-reobserve", observed_at=first_seen))
    upsert_listing(db_session, make_listing(listing_id="test-reobserve"))

    listing = get_listing(db_session, "test-reobserve")
    assert history_for(db_session, listing) == [("listed", 50.0)]
    assert listing.last_updated > first_seen.replace(tzinfo=None)  # still refreshed


def test_sold_listing_records_sale_once_and_leaves_active(db_session) -> None:
    upsert_listing(db_session, make_listing(listing_id="test-sold"))
    upsert_listing(db_session, make_listing(listing_id="test-sold", event_type="sold", listing_price=48.0))
    upsert_listing(db_session, make_listing(listing_id="test-sold", event_type="sold", listing_price=48.0))  # redelivered

    listing = get_listing(db_session, "test-sold")
    assert listing.status == "sold"
    assert listing.removed_at is not None
    assert history_for(db_session, listing) == [("listed", 50.0), ("sold", 48.0)]


def test_delisted_listing_keeps_last_price_without_history(db_session) -> None:
    upsert_listing(db_session, make_listing(listing_id="test-delisted"))
    upsert_listing(db_session, make_listing(listing_id="test-delisted", event_type="delisted", listing_price=None))

    listing = get_listing(db_session, "test-delisted")
    assert listing.status == "delisted"
    assert listing.listing_price == 50.0
    assert history_for(db_session, listing) == [("listed", 50.0)]


def test_delisted_listing_never_seen_is_ignored(db_session) -> None:
    upsert_listing(db_session, make_listing(listing_id="test-never-seen", event_type="delisted"))

    assert db_session.execute(select(Listing).where(Listing.listing_id == "test-never-seen")).first() is None


def test_relisted_listing_is_active_with_a_new_price_point(db_session) -> None:
    upsert_listing(db_session, make_listing(listing_id="test-relisted"))
    upsert_listing(db_session, make_listing(listing_id="test-relisted", event_type="delisted"))
    upsert_listing(db_session, make_listing(listing_id="test-relisted"))

    listing = get_listing(db_session, "test-relisted")
    assert listing.status == "active"
    assert listing.removed_at is None
    assert history_for(db_session, listing) == [("listed", 50.0), ("listed", 50.0)]


def test_expire_stale_listings_only_expires_unobserved_active_rows(db_session) -> None:
    long_ago = datetime.now(timezone.utc) - timedelta(hours=72)
    upsert_listing(db_session, make_listing(listing_id="test-stale", observed_at=long_ago))
    upsert_listing(db_session, make_listing(listing_id="test-fresh"))
    upsert_listing(db_session, make_listing(listing_id="test-stale-sold", observed_at=long_ago))
    upsert_listing(db_session, make_listing(listing_id="test-stale-sold", event_type="sold", observed_at=long_ago))

    assert expire_stale_listings(db_session, timedelta(hours=48)) >= 1
    db_session.expire_all()

    stale = get_listing(db_session, "test-stale")
    assert stale.status == "expired"
    assert stale.last_updated == long_ago.replace(tzinfo=None)  # still "last observed", not bumped
    assert get_listing(db_session, "test-fresh").status == "active"
    assert get_listing(db_session, "test-stale-sold").status == "sold"


def test_expired_listing_reobserved_is_active_without_new_price_point(db_session) -> None:
    long_ago = datetime.now(timezone.utc) - timedelta(hours=72)
    upsert_listing(db_session, make_listing(listing_id="test-expired-back", observed_at=long_ago))
    expire_stale_listings(db_session, timedelta(hours=48))
    upsert_listing(db_session, make_listing(listing_id="test-expired-back"))

    db_session.expire_all()
    listing = get_listing(db_session, "test-expired-back")
    assert listing.status == "active"
    assert history_for(db_session, listing) == [("listed", 50.0)]
