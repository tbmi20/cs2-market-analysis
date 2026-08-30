"""Entrypoint: `uv run python -m ingestion.skinport`

Publishes the stub catalog to raw.skinport.listings, same as the CSFloat
plugin publishes to raw.csfloat.listings — no consolidator changes needed to
handle this second marketplace (see plugin.py's docstring).
"""

from __future__ import annotations

import logging

from dotenv import load_dotenv

from ingestion.common.publisher import ListingPublisher
from ingestion.common.runner import run_forever
from ingestion.skinport.plugin import SkinportStubPlugin

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

STUB_POLL_INTERVAL_SECONDS = 300  # arbitrary — there's no real API to rate-limit against

if __name__ == "__main__":
    plugin = SkinportStubPlugin()
    publisher = ListingPublisher(marketplace=plugin.marketplace)
    run_forever(plugin, publisher, interval_seconds=STUB_POLL_INTERVAL_SECONDS)
