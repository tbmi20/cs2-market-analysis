"""Entrypoint: `uv run python -m analysis.scheduler`

Recompute scheduling (plan Section 7/9 step 8) — a simple interval job, not
Airflow: the batch jobs here are a handful of independent window-based
recomputes, not complex enough to justify Airflow's own scheduler/webserver/
metadata-DB. Revisit that call only if job count or retry/dependency
complexity actually grows.
"""

from __future__ import annotations

import logging
import os

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

from analysis import arbitrage, trend, underpriced

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def recompute_all() -> None:
    trend_count = trend.run()
    arbitrage_count = arbitrage.run()
    underpriced_count = underpriced.run()
    logger.info(
        "recompute: %d trend/volatility, %d arbitrage, %d underpriced_listing rows",
        trend_count,
        arbitrage_count,
        underpriced_count,
    )


def main() -> None:
    interval_seconds = int(os.environ.get("ANALYSIS_RECOMPUTE_INTERVAL_SECONDS", "300"))

    recompute_all()  # run once immediately rather than waiting a full interval on startup

    scheduler = BlockingScheduler()
    scheduler.add_job(recompute_all, "interval", seconds=interval_seconds)
    logger.info("scheduler started, recomputing every %ds", interval_seconds)
    scheduler.start()


if __name__ == "__main__":
    main()
