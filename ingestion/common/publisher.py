"""Thin Kafka producer wrapper. Each marketplace publishes to its own topic
(`raw.<marketplace>.listings`) — the fan-in happens at the consolidator, which
is the only Kafka consumer (see plan Section 3/4).
"""

from __future__ import annotations

import logging
import os

from confluent_kafka import KafkaError, Message, Producer

from ingestion.common.schema import NormalizedListing

logger = logging.getLogger(__name__)


class ListingPublisher:
    def __init__(self, marketplace: str, bootstrap_servers: str | None = None) -> None:
        self.topic = f"raw.{marketplace}.listings"
        servers = bootstrap_servers or os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        self._producer = Producer({"bootstrap.servers": servers})

    def _delivery_callback(self, err: KafkaError | None, msg: Message) -> None:
        if err is not None:
            logger.error("delivery failed for %s: %s", msg.key(), err)

    def publish(self, listings: list[NormalizedListing]) -> None:
        for listing in listings:
            self._producer.produce(
                self.topic,
                key=listing.listing_id,
                value=listing.model_dump_json(),
                callback=self._delivery_callback,
            )
        # Non-blocking poll to trigger queued delivery callbacks, then a bounded
        # flush so a poll cycle doesn't return before its batch is actually sent.
        self._producer.poll(0)
        remaining = self._producer.flush(timeout=10)
        if remaining:
            logger.warning("%d messages still queued after flush timeout", remaining)
