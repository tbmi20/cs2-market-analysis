"""Entrypoint: `uv run python -m analysis`

One-shot recompute of every analysis module — no scheduler yet (that's
build-order step 8, deferred per plan Section 7: a simple cron/APScheduler
job, not Airflow).
"""

from __future__ import annotations

import logging

from dotenv import load_dotenv

from analysis import arbitrage, trend, underpriced

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

if __name__ == "__main__":
    trend_count = trend.run()
    arbitrage_count = arbitrage.run()
    underpriced_count = underpriced.run()
    print(
        f"wrote {trend_count} trend/volatility, {arbitrage_count} arbitrage, "
        f"{underpriced_count} underpriced_listing rows"
    )
