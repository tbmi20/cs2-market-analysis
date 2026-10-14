"""Validates Skinport raw->normalized mapping and change-only publishing,
using item shapes taken from a live GET /v1/items response (2026-10-13).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from ingestion.skinport.models import SkinportItem
from ingestion.skinport.plugin import SkinportPlugin

LIVE_EXAMPLE_ITEM = {
    "market_hash_name": "★ Karambit | Urban Masked (Field-Tested)",
    "version": None,
    "currency": "USD",
    "suggested_price": 457.19,
    "item_page": "https://skinport.com/item/karambit-urban-masked-field-tested",
    "market_page": "https://skinport.com/market/knife/karambit?item=Urban%20Masked",
    "min_price": 409.66,
    "max_price": 1694.01,
    "mean_price": 736.31,
    "median_price": 420.78,
    "quantity": 4,
    "created_at": 1535988302,
    "updated_at": 1791897314,
}


def item(**overrides) -> SkinportItem:
    return SkinportItem.model_validate({**LIVE_EXAMPLE_ITEM, **overrides})


class _StubClient:
    def __init__(self) -> None:
        self.items: list[SkinportItem] = []

    def fetch_items(self) -> list[SkinportItem]:
        return self.items


@pytest.fixture
def plugin() -> SkinportPlugin:
    plugin = SkinportPlugin.__new__(SkinportPlugin)  # skip __init__, no HTTP client needed
    plugin._client = _StubClient()
    plugin._last_published = {}
    plugin._reconfirm_after = timedelta(hours=6)
    return plugin


def test_normalize_live_example(plugin: SkinportPlugin) -> None:
    normalized = plugin._normalize(item())

    assert normalized.marketplace == "skinport"
    assert normalized.listing_id == "★ Karambit | Urban Masked (Field-Tested)"
    assert normalized.weapon == "★ Karambit"  # same "★ " convention as CSFloat's item_name
    assert normalized.skin_name == "Urban Masked"
    assert normalized.wear_category == "FT"
    assert normalized.float_value is None
    assert normalized.listing_price == pytest.approx(409.66)
    assert normalized.quantity == 4
    assert normalized.raw_payload["suggested_price"] == pytest.approx(457.19)


def test_doppler_versions_get_distinct_listing_ids(plugin: SkinportPlugin) -> None:
    name = "★ Karambit | Doppler (Factory New)"
    phase_2 = plugin._normalize(item(market_hash_name=name, version="Phase 2"))
    ruby = plugin._normalize(item(market_hash_name=name, version="Ruby"))

    assert phase_2.listing_id != ruby.listing_id
    assert (phase_2.weapon, phase_2.skin_name) == (ruby.weapon, ruby.skin_name) == ("★ Karambit", "Doppler")


@pytest.mark.parametrize(
    "overrides",
    [
        {"market_hash_name": "Sticker | Titan (Holo) | Katowice 2014"},
        {"market_hash_name": "Special Agent Ava | FBI"},
        {"market_hash_name": "★ Karambit"},  # vanilla knife, no wear
        {"market_hash_name": "StatTrak™ AK-47 | Redline (Field-Tested)"},
        {"market_hash_name": "★ StatTrak™ Karambit | Fade (Factory New)"},
        {"market_hash_name": "Souvenir AWP | Dragon Lore (Factory New)"},
        {"min_price": None, "quantity": 0},
    ],
)
def test_normalize_skips_non_comparable_items(plugin: SkinportPlugin, overrides: dict) -> None:
    assert plugin._normalize(item(**overrides)) is None


def test_fetch_listings_publishes_only_changes(plugin: SkinportPlugin) -> None:
    redline = item(market_hash_name="AK-47 | Redline (Field-Tested)", min_price=30.0, quantity=50)
    plugin._client.items = [item(), redline]
    assert len(plugin.fetch_listings()) == 2  # first poll: everything

    plugin._client.items = [item(), redline.model_copy(update={"min_price": 29.5})]
    [changed] = plugin.fetch_listings()
    assert changed.listing_id == "AK-47 | Redline (Field-Tested)"
    assert changed.listing_price == pytest.approx(29.5)

    assert plugin.fetch_listings() == []  # nothing moved


def test_fetch_listings_delists_sold_out_item(plugin: SkinportPlugin) -> None:
    plugin._client.items = [item(), item(market_hash_name="AK-47 | Redline (Field-Tested)")]
    plugin.fetch_listings()

    plugin._client.items = [item(), item(market_hash_name="AK-47 | Redline (Field-Tested)", min_price=None, quantity=0)]
    [gone] = plugin.fetch_listings()

    assert gone.listing_id == "AK-47 | Redline (Field-Tested)"
    assert gone.event_type == "delisted"
    assert gone.listing_price == pytest.approx(409.66)  # last known ask, kept
    assert gone.quantity == 0
    assert plugin.fetch_listings() == []  # published once, not every poll


def test_fetch_listings_reconfirms_unchanged_items_periodically(plugin: SkinportPlugin) -> None:
    plugin._client.items = [item()]
    plugin.fetch_listings()
    assert plugin.fetch_listings() == []

    plugin._reconfirm_after = timedelta(0)
    [reconfirmed] = plugin.fetch_listings()
    assert reconfirmed.listing_id == "★ Karambit | Urban Masked (Field-Tested)"


def test_fetch_listings_raises_on_empty_catalog(plugin: SkinportPlugin) -> None:
    plugin._client.items = [item()]
    plugin.fetch_listings()

    plugin._client.items = []
    with pytest.raises(RuntimeError):
        plugin.fetch_listings()
    assert plugin._last_published  # previous state kept, nothing cleared
