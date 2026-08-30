"""Pydantic models for CSFloat's raw /listings response.

Only the fields the plugin actually maps are declared; `extra="ignore"` so an
API field we don't use yet doesn't break validation. Shape taken from
https://docs.csfloat.com/ (GET /v1/listings) — a bare JSON array of listing
objects, each with a nested `item`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CSFloatItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    def_index: int
    float_value: float | None = None
    market_hash_name: str
    item_name: str  # e.g. "M4A4 | Poseidon" — weapon and skin, no wear suffix
    wear_name: str | None = None  # e.g. "Factory New"; null for anything that isn't a worn skin
    rarity: int | None = None
    # /listings returns every item type CSFloat sells, not just weapon skins —
    # confirmed live 2026-08-30: also 'agent', 'sticker', and presumably
    # 'case'/'key'/'graffiti'/etc. `type == "skin"` is the reliable filter;
    # `wear_name is None` alone isn't (a vanilla/no-paint knife is also
    # type="skin" with no wear_name, and should still be skipped, just for a
    # different reason — see plugin.py).
    type: str | None = None


class CSFloatListing(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    created_at: str
    type: str  # 'buy_now' | 'auction'
    price: int  # cents
    state: str  # 'listed' when active; other values exist but aren't documented
    item: CSFloatItem
    min_offer_price: int | None = None  # seller's floor for offers — not a real order-book bid,
    # but the closest thing CSFloat exposes; mapped to NormalizedListing.buy_order_price as an
    # approximation (see ingestion/csfloat/plugin.py).
