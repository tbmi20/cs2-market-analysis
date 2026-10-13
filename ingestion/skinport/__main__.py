"""Entrypoint: `uv run python -m ingestion.skinport`

Polls Skinport on SKINPORT_POLL_INTERVAL_SECONDS and publishes normalized
listings to Kafka topic `raw.skinport.listings`.
"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

from ingestion.common.publisher import ListingPublisher
from ingestion.common.runner import run_forever
from ingestion.skinport.plugin import SkinportPlugin

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> None:
    client_id = os.environ.get("SKINPORT_ID")
    client_secret = os.environ.get("SKINPORT_SECRET")
    if not client_id or not client_secret:
        print("SKINPORT_ID and SKINPORT_SECRET must both be set (see .env.example)", file=sys.stderr)
        raise SystemExit(1)

    # Skinport caches /v1/items for 5 minutes, so polling faster just re-reads the cache.
    interval = float(os.environ.get("SKINPORT_POLL_INTERVAL_SECONDS", "300"))
    plugin = SkinportPlugin(client_id=client_id, client_secret=client_secret)
    publisher = ListingPublisher(marketplace=plugin.marketplace)
    run_forever(plugin, publisher, interval_seconds=interval)


if __name__ == "__main__":
    main()
