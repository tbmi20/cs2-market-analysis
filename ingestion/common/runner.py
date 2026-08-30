"""Generic poll loop: runs a plugin on a fixed interval and publishes each
batch. Retry/backoff is intentionally simple here — the plugin interface and
Kafka fan-in are the point of this step; smarter scheduling is Section 9
step 8's job, later, and likely lives outside the plugin entirely.
"""

from __future__ import annotations

import logging
import time

from ingestion.common.plugin import MarketplacePlugin
from ingestion.common.publisher import ListingPublisher

logger = logging.getLogger(__name__)


def run_forever(plugin: MarketplacePlugin, publisher: ListingPublisher, interval_seconds: float) -> None:
    while True:
        started = time.monotonic()
        try:
            listings = plugin.fetch_listings()
            publisher.publish(listings)
            logger.info("%s: published %d listings", plugin.marketplace, len(listings))
        except Exception:
            logger.exception("%s: poll failed, will retry next tick", plugin.marketplace)

        elapsed = time.monotonic() - started
        time.sleep(max(0.0, interval_seconds - elapsed))
