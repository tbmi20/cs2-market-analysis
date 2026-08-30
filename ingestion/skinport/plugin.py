"""STUB — not a real Skinport integration. There's no client.py/models.py
here because there's no real API call: this returns a small hardcoded set of
fake listings so the arbitrage module (analysis/arbitrage.py) has a second
marketplace to compare against, per plan Section 9 step 5 ("once a second
marketplace plugin exists (or can be stubbed with fake data...)").

It deliberately implements the exact same MarketplacePlugin interface as
CSFloatPlugin and needs zero consolidator changes to plug in — proving the
fan-in architecture from plan Section 4, not just asserting it.

A couple of entries intentionally reuse weapon/skin/float values seen in real
CSFloat data (as of 2026-08-30) so a real arbitrage gap actually appears once
both are ingested — replace this whole file with a real client once Skinport
integration happens for real (plan Section 10).
"""

from __future__ import annotations

from datetime import datetime, timezone

from ingestion.common.plugin import MarketplacePlugin
from ingestion.common.schema import NormalizedListing

# (listing_id, weapon, skin_name, wear_category, float_value, price) — fixed
# listing_ids so repeated polls upsert the same rows rather than piling up
# duplicates, same as a real marketplace's stable listing IDs would.
_FAKE_CATALOG = [
    ("stub-1", "AK-47", "Slate", "FN", 0.045, 40.00),
    ("stub-2", "USP-S", "Kill Confirmed", "BS", 0.58, 65.00),
    ("stub-3", "AWP", "Asiimov", "FT", 0.20, 75.00),
]


class SkinportStubPlugin(MarketplacePlugin):
    marketplace = "skinport"

    def fetch_listings(self) -> list[NormalizedListing]:
        now = datetime.now(timezone.utc)
        return [
            NormalizedListing(
                marketplace=self.marketplace,
                listing_id=listing_id,
                weapon=weapon,
                skin_name=skin_name,
                wear_category=wear_category,
                float_value=float_value,
                listing_price=price,
                event_type="listed",
                observed_at=now,
                raw_payload={"stub": True, "listing_id": listing_id},
            )
            for listing_id, weapon, skin_name, wear_category, float_value, price in _FAKE_CATALOG
        ]
