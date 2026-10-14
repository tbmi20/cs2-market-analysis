"""Thin HTTP client for CSFloat's GET /v1/listings endpoint.

Confirmed against a live authenticated call on 2026-08-30 (CSFloat's public
docs at https://docs.csfloat.com/ don't show this — the docs describe a bare
array, but the real response is an envelope):
- Response body: `{"data": [<listing>, ...], "cursor": "<opaque string>"}`
- Rate-limit headers: `x-ratelimit-limit`, `x-ratelimit-remaining`,
  `x-ratelimit-reset` (the last is a Unix epoch seconds timestamp, not a
  relative "seconds remaining" value)

GET /v1/listings/{id} (confirmed live 2026-10-13) returns the bare listing
object — no envelope — for listings that are no longer on sale too, with
`state` set to e.g. "sold" or "delisted".

Rate limits are per endpoint (observed 2026-10-13): 200 per window for the
/listings feed, 50000 for /listings/{id}, the latter resetting about a day out.
"""

from __future__ import annotations

import logging
import time

import httpx

from ingestion.csfloat.models import CSFloatListing

logger = logging.getLogger(__name__)

BASE_URL = "https://csfloat.com/api/v1/listings"
PAGE_LIMIT = 50  # API max, per docs.csfloat.com

_REMAINING_HEADER = "x-ratelimit-remaining"
_RESET_HEADER = "x-ratelimit-reset"


class CSFloatClient:
    def __init__(self, api_key: str, timeout: float = 15.0) -> None:
        self._client = httpx.Client(headers={"Authorization": api_key}, timeout=timeout)
        # /listings/{id}'s own budget, from its latest response; None until the first call.
        self.listing_rate_limit_remaining: int | None = None

    def close(self) -> None:
        self._client.close()

    def fetch_recent_listings(self, *, max_pages: int = 5) -> list[CSFloatListing]:
        """Follows cursor pagination, sorted by `most_recent`, up to
        `max_pages` pages per call (so each poll cycle catches up on new
        listings without an unbounded number of requests if a lot landed
        since the last poll).
        """
        listings: list[CSFloatListing] = []
        cursor: str | None = None

        for _ in range(max_pages):
            params: dict[str, str | int] = {"limit": PAGE_LIMIT, "sort_by": "most_recent"}
            if cursor:
                params["cursor"] = cursor

            response = self._client.get(BASE_URL, params=params)
            self._respect_rate_limit(response.headers)
            response.raise_for_status()

            body = response.json()
            page = body.get("data", [])
            if not page:
                break

            listings.extend(CSFloatListing.model_validate(raw) for raw in page)

            cursor = body.get("cursor")
            if not cursor or len(page) < PAGE_LIMIT:
                break  # short page or no cursor => this was the last page

        return listings

    def fetch_listing(self, listing_id: str) -> CSFloatListing | None:
        """Current state of one listing, or None if CSFloat no longer knows it."""
        response = self._client.get(f"{BASE_URL}/{listing_id}")
        self.listing_rate_limit_remaining = self._respect_rate_limit(response.headers)
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        response.raise_for_status()
        return CSFloatListing.model_validate(response.json())

    def _respect_rate_limit(self, headers: httpx.Headers) -> int | None:
        """Sleeps out an exhausted window; returns the remaining count, if sent."""
        remaining = headers.get(_REMAINING_HEADER)
        reset_at = headers.get(_RESET_HEADER)
        if remaining is None or reset_at is None:
            return None

        if int(remaining) <= 0:
            wait_for = max(0.0, float(reset_at) - time.time())
            logger.warning("csfloat rate limit exhausted, sleeping %.1fs until reset", wait_for)
            time.sleep(wait_for)
        return int(remaining)
