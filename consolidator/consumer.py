"""The consolidator: the single Kafka consumer for every raw.*.listings
topic (see plan Section 3/4 — this is the fan-in point; analysis modules
downstream never touch Kafka, only Postgres).

Per batch of consumed messages, grouped by marketplace:
- resolve each listing's skin_variant (creating one if new)
- upsert into `listings` — (marketplace, listing_id) is unique, so this *is*
  the dedup: a repeat observation updates the existing row rather than
  inserting a duplicate. The message's event_type moves the row between
  'active', 'sold' and 'delisted'
- append a `price_history` row only for a price point that's new — a new or
  relisted listing, a price change, or a sale — not for every re-observation
- log one `ingestion_runs` row, powering the dashboard's freshness display

Separately, a periodic sweep expires 'active' listings that no observation
has confirmed for LISTING_STALE_AFTER_HOURS.
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from confluent_kafka import Consumer
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from consolidator.ingestion_runs import log_ingestion_run
from consolidator.skin_variants import get_or_create_skin_variant
from db.models import Listing, PriceHistory
from db.session import SessionLocal
from ingestion.common.schema import NormalizedListing

logger = logging.getLogger(__name__)

# librdkafka treats a subscription starting with "^" as a regex.
TOPIC_PATTERN = r"^raw\..+\.listings$"


# How long an 'active' listing can go without any marketplace observation
# before it's expired. Plugins re-confirm what they track well inside this
# (CSFloat rechecks by id, Skinport re-publishes unchanged items), so this
# mainly catches listings an ingester stopped tracking — e.g. after a restart,
# which drops their in-memory state.
DEFAULT_STALE_AFTER_HOURS = 48
EXPIRE_SWEEP_INTERVAL_SECONDS = 600

_STATUS_FOR_EVENT = {"listed": "active", "sold": "sold", "delisted": "delisted"}


def upsert_listing(session: Session, listing: NormalizedListing) -> None:
    """Applies one observation to the listing's current-state row, and
    appends price_history only when it carries a price point we don't
    already have — re-observing an unchanged listing just refreshes
    `last_updated`, so long-lived listings don't outweigh short-lived ones
    in the trend/underpriced baselines.
    """
    existing = session.execute(
        select(Listing.listing_price, Listing.buy_order_price, Listing.status).where(
            Listing.marketplace == listing.marketplace, Listing.listing_id == listing.listing_id
        )
    ).one_or_none()

    if existing is None and listing.event_type == "delisted":
        return  # gone before we ever saw it on sale — nothing worth recording

    variant_id = get_or_create_skin_variant(
        session,
        weapon=listing.weapon,
        skin_name=listing.skin_name,
        wear_category=listing.wear_category,
        float_value=listing.float_value,
    )

    status = _STATUS_FOR_EVENT[listing.event_type]
    listing_price = listing.listing_price
    if listing_price is None and existing is not None:
        listing_price = existing.listing_price  # a removal keeps the last known ask

    stmt = pg_insert(Listing).values(
        marketplace=listing.marketplace,
        listing_id=listing.listing_id,
        skin_variant_id=variant_id,
        float_value=listing.float_value,
        rarity=listing.rarity,
        listing_price=listing_price,
        buy_order_price=listing.buy_order_price,
        quantity=listing.quantity,
        raw_payload=listing.raw_payload,
        status=status,
        removed_at=None if status == "active" else listing.observed_at,
        last_updated=listing.observed_at,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Listing.marketplace, Listing.listing_id],
        set_={
            "skin_variant_id": stmt.excluded.skin_variant_id,
            "float_value": stmt.excluded.float_value,
            "rarity": stmt.excluded.rarity,
            "listing_price": stmt.excluded.listing_price,
            "buy_order_price": stmt.excluded.buy_order_price,
            "quantity": stmt.excluded.quantity,
            "raw_payload": stmt.excluded.raw_payload,
            "status": stmt.excluded.status,
            "removed_at": stmt.excluded.removed_at,
            "last_updated": stmt.excluded.last_updated,
        },
    )
    session.execute(stmt)

    for event_type, price in _new_price_points(listing, existing, listing_price):
        session.add(
            PriceHistory(
                marketplace=listing.marketplace,
                skin_variant_id=variant_id,
                price=price,
                event_type=event_type,
                observed_at=listing.observed_at,
            )
        )


def _new_price_points(listing: NormalizedListing, existing, listing_price: float | None) -> list[tuple[str, float]]:
    if listing.event_type == "sold":
        if listing_price is None or (existing is not None and existing.status == "sold"):
            return []  # no price to record, or a redelivered sale
        return [("sold", listing_price)]
    if listing.event_type != "listed":
        return []

    # A sold/delisted row coming back is a genuine relist. An 'expired' one
    # isn't — we only lost track of it — so it's treated like any other
    # re-observation.
    relisted = existing is None or existing.status in ("sold", "delisted")
    points = []
    if listing.listing_price is not None and (relisted or listing.listing_price != existing.listing_price):
        points.append(("listed", listing.listing_price))
    if listing.buy_order_price is not None and (relisted or listing.buy_order_price != existing.buy_order_price):
        points.append(("buy_order", listing.buy_order_price))
    return points


def expire_stale_listings(session: Session, stale_after: timedelta) -> int:
    """Marks 'active' listings that no observation has confirmed within
    `stale_after` as 'expired', so they stop counting as on sale.
    """
    result = session.execute(
        update(Listing)
        .where(Listing.status == "active", Listing.last_updated < func.now() - stale_after)
        # Pin last_updated: it means "last observed", and the column's
        # onupdate would otherwise bump it to now.
        .values(status="expired", removed_at=func.now(), last_updated=Listing.last_updated)
    )
    return result.rowcount


def process_batch(session: Session, marketplace: str, listings: list[NormalizedListing]) -> None:
    started_at = datetime.now(timezone.utc)
    try:
        for listing in listings:
            upsert_listing(session, listing)
        log_ingestion_run(session, marketplace, started_at, status="success", records_ingested=len(listings))
        session.commit()
        logger.info("consolidated %d %s listings", len(listings), marketplace)
    except Exception as exc:
        session.rollback()
        logger.exception("failed to process batch for %s", marketplace)
        log_ingestion_run(session, marketplace, started_at, status="failed", records_ingested=0, error_message=str(exc))
        session.commit()


def _drain(consumer: Consumer, poll_timeout: float) -> list[NormalizedListing]:
    """Collect whatever's currently available: one blocking poll to wait for
    at least one message, then non-blocking polls until the topic goes quiet.
    """
    messages: list[NormalizedListing] = []
    msg = consumer.poll(poll_timeout)
    while msg is not None:
        if msg.error():
            logger.error("kafka error: %s", msg.error())
        else:
            try:
                messages.append(NormalizedListing.model_validate_json(msg.value()))
            except Exception:
                logger.exception("failed to parse message, skipping")
        msg = consumer.poll(0)
    return messages


def _run_expiry_sweep(stale_after: timedelta) -> None:
    session = SessionLocal()
    try:
        expired = expire_stale_listings(session, stale_after)
        session.commit()
        if expired:
            logger.info("expired %d listings not observed in %s", expired, stale_after)
    except Exception:
        session.rollback()
        logger.exception("expiry sweep failed, will retry next interval")
    finally:
        session.close()


def run_forever(bootstrap_servers: str | None = None, poll_timeout: float = 1.0) -> None:
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap_servers or os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
            "group.id": "consolidator",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([TOPIC_PATTERN])
    logger.info("subscribed to %s, waiting for messages", TOPIC_PATTERN)

    stale_after = timedelta(hours=float(os.environ.get("LISTING_STALE_AFTER_HOURS", DEFAULT_STALE_AFTER_HOURS)))
    last_sweep = float("-inf")

    try:
        while True:
            if time.monotonic() - last_sweep >= EXPIRE_SWEEP_INTERVAL_SECONDS:
                _run_expiry_sweep(stale_after)
                last_sweep = time.monotonic()

            batch = _drain(consumer, poll_timeout)
            if not batch:
                continue

            by_marketplace: dict[str, list[NormalizedListing]] = defaultdict(list)
            for listing in batch:
                by_marketplace[listing.marketplace].append(listing)

            session = SessionLocal()
            try:
                for marketplace, listings in by_marketplace.items():
                    process_batch(session, marketplace, listings)
            finally:
                session.close()

            consumer.commit(asynchronous=False)
    finally:
        consumer.close()
