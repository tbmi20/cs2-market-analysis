"""Common schema every marketplace plugin normalizes into before publishing to
Kafka. The consolidator only ever deals with this shape — it has no
marketplace-specific parsing logic (see plan Section 3/7).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

WearCategory = Literal["FN", "MW", "FT", "WW", "BS"]
EventType = Literal["listed", "sold", "buy_order"]

# Standard CS2 wear-name -> wear-category mapping, shared across marketplaces
# (this is a display-name convention, not the premium float_buckets config —
# see plan Section 2/5).
WEAR_NAME_TO_CATEGORY: dict[str, WearCategory] = {
    "Factory New": "FN",
    "Minimal Wear": "MW",
    "Field-Tested": "FT",
    "Well-Worn": "WW",
    "Battle-Scarred": "BS",
}


class NormalizedListing(BaseModel):
    """One observed listing, in the common shape the consolidator consumes.

    `float_bucket` resolution (premium sub-bucket vs. default wear category)
    happens in the consolidator against the `float_buckets` config table, not
    here — plugins have no Postgres access, by design (plan Section 3: "the
    database is the seam, not Kafka").
    """

    marketplace: str
    listing_id: str  # marketplace's own ID
    weapon: str
    skin_name: str
    wear_category: WearCategory
    float_value: float | None = None
    rarity: str | None = None
    listing_price: float | None = None  # ask, in the marketplace's base currency unit (not cents)
    buy_order_price: float | None = None  # bid, if the marketplace exposes one
    # Units on sale at listing_price: 1 for a real individual listing, more when a
    # marketplace only exposes per-item aggregates (Skinport's lowest ask + stock).
    quantity: int = 1
    event_type: EventType = "listed"
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_payload: dict  # untouched source response, stored as-is downstream
