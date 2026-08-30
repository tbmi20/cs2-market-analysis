"""Entrypoint: `uv run python -m consolidator`"""

from __future__ import annotations

import logging

from dotenv import load_dotenv

from consolidator.consumer import run_forever

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

if __name__ == "__main__":
    run_forever()
