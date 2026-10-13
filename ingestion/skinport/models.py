"""Pydantic model for one entry of Skinport's GET /v1/items response.

Shape from https://docs.skinport.com/items, checked against a live call on
2026-10-13. The live response also carries an undocumented `version` field:
null for almost everything, but a phase/gem name ("Phase 2", "Ruby", ...) for
Doppler-family knives, which then appear once per version under the *same*
market_hash_name — so market_hash_name alone isn't a unique key.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SkinportItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    market_hash_name: str  # e.g. "★ Karambit | Doppler (Factory New)", "StatTrak™ AK-47 | Redline (Field-Tested)"
    version: str | None = None
    currency: str
    # An aggregate over every active listing of this item — Skinport's public
    # API exposes no individual listings and no float values.
    min_price: float | None = None  # null when quantity == 0
    suggested_price: float | None = None
    quantity: int
    item_page: str | None = None
    updated_at: int | None = None  # Unix epoch seconds
