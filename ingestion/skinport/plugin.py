"""Skinport plugin: implements MarketplacePlugin by polling SkinportClient and
mapping its response into the common NormalizedListing schema.

Skinport's public API is per-item aggregates, not individual listings, so
each (market_hash_name, version) becomes one "listing" whose price is the
item's current lowest ask and whose `quantity` is how many are on sale. No
float values are exposed, so these always land in the wear category's
default float bucket (see consolidator/float_buckets.py).

The full catalog (~13k priced skins) comes back on every poll and most prices
don't move between polls, so only items whose price or stock changed since
the last poll are published, plus each unchanged item once every
`reconfirm_after` so the consolidator's staleness sweep doesn't expire it.
An item that sold out or vanished is published once more as "delisted", so
its `listings` row stops counting as active instead of keeping a stale price
forever. (Skinport's aggregates don't say whether units sold or were pulled,
so there are no "sold" events from here.)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from ingestion.common.plugin import MarketplacePlugin
from ingestion.common.schema import WEAR_NAME_TO_CATEGORY, NormalizedListing
from ingestion.skinport.client import SkinportClient
from ingestion.skinport.models import SkinportItem

logger = logging.getLogger(__name__)

# CSFloat's plugin builds weapon/skin from `item_name`, which has no
# StatTrak™/Souvenir marker, so those would land in the plain skin's variant
# and get compared against plain-skin prices. Skipped until variants can tell
# them apart.
_SKIPPED_PREFIXES = ("StatTrak™ ", "★ StatTrak™ ", "Souvenir ")


class SkinportPlugin(MarketplacePlugin):
    marketplace = "skinport"

    def __init__(self, client_id: str, client_secret: str, reconfirm_after: timedelta = timedelta(hours=6)) -> None:
        self._client = SkinportClient(client_id=client_id, client_secret=client_secret)
        self._reconfirm_after = reconfirm_after
        # listing_id -> what was last published for it (only priced items).
        self._last_published: dict[str, NormalizedListing] = {}

    def fetch_listings(self) -> list[NormalizedListing]:
        current: dict[str, NormalizedListing] = {}
        for item in self._client.fetch_items():
            listing = self._normalize(item)
            if listing is not None:
                current[listing.listing_id] = listing

        if not current:
            # An empty catalog is an API hiccup, not every skin selling out at
            # once — don't clear every Skinport price over it.
            raise RuntimeError("skinport returned no priced skins")

        now = datetime.now(timezone.utc)
        published: list[NormalizedListing] = []
        last_published: dict[str, NormalizedListing] = {}
        for listing_id, listing in current.items():
            previous = self._last_published.get(listing_id)
            if self._should_publish(previous, listing, now):
                published.append(listing)
                last_published[listing_id] = listing
            else:
                last_published[listing_id] = previous  # keeps its observed_at for the reconfirm clock

        gone = [
            previous.model_copy(update={"event_type": "delisted", "quantity": 0, "observed_at": now})
            for listing_id, previous in self._last_published.items()
            if listing_id not in current
        ]

        self._last_published = last_published
        return published + gone

    def _should_publish(self, previous: NormalizedListing | None, listing: NormalizedListing, now: datetime) -> bool:
        return (
            previous is None
            or previous.listing_price != listing.listing_price
            or previous.quantity != listing.quantity
            or now - previous.observed_at >= self._reconfirm_after
        )

    def _normalize(self, item: SkinportItem) -> NormalizedListing | None:
        """Returns None for anything that isn't a priced, wear-graded, plain
        weapon skin — stickers, cases, agents, vanilla knives, sold-out items
        and StatTrak™/Souvenir variants (see _SKIPPED_PREFIXES).
        """
        if item.min_price is None or item.quantity <= 0:
            return None
        if item.market_hash_name.startswith(_SKIPPED_PREFIXES):
            return None

        name, _, wear_suffix = item.market_hash_name.rpartition(" (")
        wear_category = WEAR_NAME_TO_CATEGORY.get(wear_suffix.removesuffix(")"))
        if wear_category is None:
            return None

        weapon, _, skin_name = name.partition(" | ")
        if not skin_name:
            logger.warning("skipping skinport item %r: couldn't split into weapon/skin", item.market_hash_name)
            return None

        # Doppler phases share a market_hash_name and differ only by version.
        listing_id = f"{item.market_hash_name} [{item.version}]" if item.version else item.market_hash_name
        return NormalizedListing(
            marketplace=self.marketplace,
            listing_id=listing_id,
            weapon=weapon,
            skin_name=skin_name,
            wear_category=wear_category,
            listing_price=item.min_price,
            quantity=item.quantity,
            event_type="listed",
            raw_payload=item.model_dump(mode="json"),
        )
