"""The consolidator: the single Kafka consumer for every raw.*.listings
topic (see plan Section 3/4 — this is the fan-in point; analysis modules
downstream never touch Kafka, only Postgres).

Per batch of consumed messages, grouped by marketplace:
- resolve each listing's skin_variant (creating one if new)
- upsert into `listings` — (marketplace, listing_id) is unique, so this *is*
  the dedup: a repeat observation updates the existing row rather than
  inserting a duplicate
- append a `price_history` row per price observed (listing price, and buy
  order price if present)
- log one `ingestion_runs` row, powering the dashboard's freshness display
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import datetime, timezone

from confluent_kafka import Consumer
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


def upsert_listing(session: Session, listing: NormalizedListing) -> None:
    variant_id = get_or_create_skin_variant(
        session,
        weapon=listing.weapon,
        skin_name=listing.skin_name,
        wear_category=listing.wear_category,
        float_value=listing.float_value,
    )

    stmt = pg_insert(Listing).values(
        marketplace=listing.marketplace,
        listing_id=listing.listing_id,
        skin_variant_id=variant_id,
        float_value=listing.float_value,
        rarity=listing.rarity,
        listing_price=listing.listing_price,
        buy_order_price=listing.buy_order_price,
        quantity=listing.quantity,
        raw_payload=listing.raw_payload,
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
            "last_updated": stmt.excluded.last_updated,
        },
    )
    session.execute(stmt)

    if listing.listing_price is not None:
        session.add(
            PriceHistory(
                marketplace=listing.marketplace,
                skin_variant_id=variant_id,
                price=listing.listing_price,
                event_type="listed",
                observed_at=listing.observed_at,
            )
        )
    if listing.buy_order_price is not None:
        session.add(
            PriceHistory(
                marketplace=listing.marketplace,
                skin_variant_id=variant_id,
                price=listing.buy_order_price,
                event_type="buy_order",
                observed_at=listing.observed_at,
            )
        )


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

    try:
        while True:
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
