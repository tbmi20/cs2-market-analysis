"""Thin HTTP client for Skinport's GET /v1/items endpoint.

Per https://docs.skinport.com/ (checked 2026-10-13):
- Auth is HTTP Basic with `clientId:clientSecret`. /v1/items itself doesn't
  require it, but sending it ties requests to the account's API key.
- `Accept-Encoding: br` is mandatory for /v1/items — httpx only decodes it
  with the `brotli` package installed (it's a project dependency for this).
- Rate limit is 8 requests / 5 minutes, and responses are cached server-side
  for 5 minutes, so polling more often than that returns the same data.
- The whole catalog comes back in one response (~25k items) — no pagination.
"""

from __future__ import annotations

import httpx

from ingestion.skinport.models import SkinportItem

BASE_URL = "https://api.skinport.com/v1/items"
CS2_APP_ID = 730
# CSFloat prices are USD; asking Skinport for USD too keeps cross-marketplace
# comparisons (analysis/arbitrage.py) like-for-like without FX conversion.
CURRENCY = "USD"


class SkinportClient:
    def __init__(self, client_id: str, client_secret: str, timeout: float = 60.0) -> None:
        self._client = httpx.Client(
            auth=httpx.BasicAuth(client_id, client_secret),
            headers={"Accept-Encoding": "br"},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def fetch_items(self) -> list[SkinportItem]:
        response = self._client.get(BASE_URL, params={"app_id": CS2_APP_ID, "currency": CURRENCY})
        response.raise_for_status()
        return [SkinportItem.model_validate(raw) for raw in response.json()]
