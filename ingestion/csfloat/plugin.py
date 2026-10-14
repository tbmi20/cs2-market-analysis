"""CSFloat plugin: implements MarketplacePlugin by polling CSFloatClient and
mapping its raw response into the common NormalizedListing schema.

The `most_recent` feed only ever shows a listing while it's new, so on its
own it never reveals a later price change, sale or delisting. Every listing
the feed surfaces is therefore tracked, and each poll also rechecks the
`recheck_per_poll` tracked listings checked longest ago by id: a listing
that's still up is re-published (the consolidator records a price point only
if the price moved), one that sold or was pulled is published as such and
dropped from tracking.

Tracking is in-memory, so a restart forgets it — the consolidator's staleness
sweep expires those orphaned rows instead.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from itertools import islice, takewhile

import httpx

from ingestion.common.plugin import MarketplacePlugin
from ingestion.common.schema import WEAR_NAME_TO_CATEGORY, EventType, NormalizedListing
from ingestion.csfloat.client import CSFloatClient
from ingestion.csfloat.models import CSFloatListing

logger = logging.getLogger(__name__)

CENTS_PER_UNIT = 100

# Rechecks stop when fewer requests than this are left in the rate-limit
# window, so the feed itself never runs out (the client would otherwise
# sleep until the window resets, up to a day away).
RATE_LIMIT_RESERVE = 2000


class CSFloatPlugin(MarketplacePlugin):
    marketplace = "csfloat"

    def __init__(self, api_key: str, recheck_per_poll: int = 20) -> None:
        self._client = CSFloatClient(api_key=api_key)
        self._recheck_per_poll = recheck_per_poll
        # Listing ids believed on sale, least recently checked first.
        self._tracked: OrderedDict[str, None] = OrderedDict()

    def fetch_listings(self) -> list[NormalizedListing]:
        listings: list[NormalizedListing] = []
        seen_now: set[str] = set()
        for raw in self._client.fetch_recent_listings():
            # /listings also returns agents, stickers, cases, etc. (confirmed live
            # 2026-08-30) — routinely skipped, not worth a log line each time.
            if raw.item.type != "skin":
                continue
            listing = self._try_normalize(raw)
            if listing is not None:
                listings.append(listing)
                seen_now.add(listing.listing_id)
                self._tracked[listing.listing_id] = None
                self._tracked.move_to_end(listing.listing_id)  # just seen, so checked

        listings.extend(self._recheck_oldest(seen_now))
        return listings

    def _recheck_oldest(self, seen_now: set[str]) -> list[NormalizedListing]:
        remaining = self._client.listing_rate_limit_remaining
        if remaining is not None and remaining < RATE_LIMIT_RESERVE:
            logger.warning("csfloat rate limit low (%d left), skipping rechecks this poll", remaining)
            return []

        listings: list[NormalizedListing] = []
        # This poll's feed listings sit at the end — reaching them means
        # everything older has been covered.
        to_check = list(islice(takewhile(lambda i: i not in seen_now, self._tracked), self._recheck_per_poll))
        for listing_id in to_check:
            try:
                raw = self._client.fetch_listing(listing_id)
            except httpx.HTTPError as exc:
                logger.warning("recheck of csfloat listing %s failed, retrying later: %s", listing_id, exc)
                self._tracked.move_to_end(listing_id)
                continue

            listing = self._try_normalize(raw) if raw is not None else None
            if listing is not None and listing.event_type == "listed":
                self._tracked.move_to_end(listing_id)
            else:
                # Sold/delisted, or gone entirely (404) — a 404 carries no item
                # to publish, so its row is left to the staleness sweep.
                del self._tracked[listing_id]
            if listing is not None:
                listings.append(listing)

        logger.info("csfloat: rechecked %d listings, tracking %d", len(to_check), len(self._tracked))
        return listings

    def _try_normalize(self, raw: CSFloatListing) -> NormalizedListing | None:
        try:
            return self._normalize(raw)
        except ValueError as exc:
            # A *skin* item that didn't parse is worth knowing about — it
            # likely means a format assumption below needs revisiting.
            logger.warning("skipping csfloat listing %s: %s", raw.id, exc)
            return None

    def _normalize(self, raw: CSFloatListing) -> NormalizedListing:
        wear_category = WEAR_NAME_TO_CATEGORY.get(raw.item.wear_name or "")
        if wear_category is None:
            # A "skin" item can still lack a wear_name — a vanilla/no-paint knife, e.g.
            raise ValueError(f"no recognizable wear_name ({raw.item.wear_name!r}) — likely a vanilla/unpainted item")

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
            event_type=_event_type_for_state(raw.state),
            raw_payload=raw.model_dump(mode="json"),
        )


def _event_type_for_state(state: str) -> EventType:
    if state == "listed":
        return "listed"
    if state == "sold":
        return "sold"
    # 'delisted', plus any undocumented state — none of them is on sale.
    return "delisted"
