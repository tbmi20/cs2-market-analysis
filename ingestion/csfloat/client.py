"""Thin HTTP client for CSFloat's GET /v1/listings endpoint.

Known limitation (intentional, not an oversight): CSFloat's public docs
(https://docs.csfloat.com/) confirm the endpoint is cursor-paginated but don't
show where the next cursor comes from in the response (the payload is a bare
JSON array, no envelope object) or the exact rate-limit header names. Rather
than guess at those and risk silently doing the wrong thing, this client
fetches a single page per call, sorted by `most_recent`, so each poll picks up
whatever's newest — full catalog backfill via pagination is a follow-up once
those mechanics are confirmed against a live API key (see plan Section 10 /
project TODOs).
"""

from __future__ import annotations

import logging

import httpx

from ingestion.csfloat.models import CSFloatListing

logger = logging.getLogger(__name__)

BASE_URL = "https://csfloat.com/api/v1/listings"
PAGE_LIMIT = 50  # API max, per docs.csfloat.com

# Header names aren't documented; checked defensively so a miss is just a
# no-op rather than a crash. Confirm the real names from a live response
# before relying on this for anything more than a safety net.
_REMAINING_HEADER_CANDIDATES = ("x-ratelimit-remaining", "x-rate-limit-remaining")


class CSFloatClient:
    def __init__(self, api_key: str, timeout: float = 15.0) -> None:
        self._client = httpx.Client(headers={"Authorization": api_key}, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def fetch_recent_listings(self) -> list[CSFloatListing]:
        response = self._client.get(BASE_URL, params={"limit": PAGE_LIMIT, "sort_by": "most_recent"})
        self._log_rate_limit(response.headers)
        response.raise_for_status()
        return [CSFloatListing.model_validate(raw) for raw in response.json()]

    def _log_rate_limit(self, headers: httpx.Headers) -> None:
        for name in _REMAINING_HEADER_CANDIDATES:
            if name in headers:
                logger.debug("csfloat rate limit remaining (%s): %s", name, headers[name])
                return
