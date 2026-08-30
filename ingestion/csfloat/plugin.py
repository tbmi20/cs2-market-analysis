"""CSFloat plugin: implements MarketplacePlugin by polling CSFloatClient and
mapping its raw response into the common NormalizedListing schema.
"""

from __future__ import annotations

import logging

from ingestion.common.plugin import MarketplacePlugin
from ingestion.common.schema import WEAR_NAME_TO_CATEGORY, NormalizedListing
from ingestion.csfloat.client import CSFloatClient
from ingestion.csfloat.models import CSFloatListing

logger = logging.getLogger(__name__)

CENTS_PER_UNIT = 100


class CSFloatPlugin(MarketplacePlugin):
    marketplace = "csfloat"

    def __init__(self, api_key: str) -> None:
        self._client = CSFloatClient(api_key=api_key)

    def fetch_listings(self) -> list[NormalizedListing]:
        raw_listings = self._client.fetch_recent_listings()
        listings: list[NormalizedListing] = []
        for raw in raw_listings:
            try:
                listings.append(self._normalize(raw))
            except ValueError as exc:
                # Don't let one malformed/unexpected item drop the whole batch.
                logger.warning("skipping csfloat listing %s: %s", raw.id, exc)
        return listings

    def _normalize(self, raw: CSFloatListing) -> NormalizedListing:
        if raw.state != "listed":
            raise ValueError(f"unexpected state {raw.state!r}")

        wear_category = WEAR_NAME_TO_CATEGORY.get(raw.item.wear_name or "")
        if wear_category is None:
            raise ValueError(f"unrecognized wear_name {raw.item.wear_name!r}")

        weapon, _, skin_name = raw.item.item_name.partition(" | ")
        if not skin_name:
            raise ValueError(f"couldn't split item_name {raw.item.item_name!r} into weapon/skin")

        return NormalizedListing(
            marketplace=self.marketplace,
            listing_id=raw.id,
            weapon=weapon,
            skin_name=skin_name,
            wear_category=wear_category,
            float_value=raw.item.float_value,
            rarity=str(raw.item.rarity) if raw.item.rarity is not None else None,
            listing_price=raw.price / CENTS_PER_UNIT,
            # min_offer_price is the seller's floor for offers, not a real order-book
            # bid — the closest thing CSFloat exposes to buy_order_price (see
            # ingestion/csfloat/models.py).
            buy_order_price=raw.min_offer_price / CENTS_PER_UNIT if raw.min_offer_price is not None else None,
            event_type="listed",
            raw_payload=raw.model_dump(mode="json"),
        )
