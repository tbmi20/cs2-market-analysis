"""Entrypoint: `uv run python -m analysis`

One-shot recompute — no scheduler yet (that's build-order step 8, deferred
per plan Section 7: a simple cron/APScheduler job, not Airflow).
"""

from __future__ import annotations

import logging

from dotenv import load_dotenv

from analysis.trend import run

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

if __name__ == "__main__":
    count = run()
    print(f"wrote {count} analysis_results rows")
