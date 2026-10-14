"""Entrypoint: `uv run python -m ingestion.csfloat`

Polls CSFloat on CSFLOAT_POLL_INTERVAL_SECONDS and publishes normalized
listings to Kafka topic `raw.csfloat.listings`.
"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

from ingestion.common.publisher import ListingPublisher
from ingestion.common.runner import run_forever
from ingestion.csfloat.plugin import CSFloatPlugin

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> None:
    api_key = os.environ.get("CSFLOAT_API_KEY")
    if not api_key:
        print("CSFLOAT_API_KEY is not set (see .env.example)", file=sys.stderr)
        raise SystemExit(1)

    interval = float(os.environ.get("CSFLOAT_POLL_INTERVAL_SECONDS", "60"))
    recheck_per_poll = int(os.environ.get("CSFLOAT_RECHECK_PER_POLL", "20"))
    plugin = CSFloatPlugin(api_key=api_key, recheck_per_poll=recheck_per_poll)
    publisher = ListingPublisher(marketplace=plugin.marketplace)
    run_forever(plugin, publisher, interval_seconds=interval)


if __name__ == "__main__":
    main()
