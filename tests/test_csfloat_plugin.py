"""Validates CSFloat raw->normalized mapping against the exact example
listing from https://docs.csfloat.com/ (GET /v1/listings), so the mapping is
checked against real documented field names/shapes rather than assumptions.
"""

from __future__ import annotations

import pytest

from ingestion.csfloat.models import CSFloatListing
from ingestion.csfloat.plugin import CSFloatPlugin

# Verbatim (trimmed of fields we don't consume) from docs.csfloat.com's example response.
DOCS_EXAMPLE_LISTING = {
    "id": "324288155723370196",
    "created_at": "2021-06-13T20:45:21.311794Z",
    "type": "buy_now",
    "price": 260000,
    "state": "listed",
    "min_offer_price": 221000,
    "item": {
        "asset_id": "22547095285",
        "def_index": 16,
        "paint_index": 449,
        "paint_seed": 700,
        "float_value": 0.02796577662229538,
        "market_hash_name": "M4A4 | Poseidon (Factory New)",
        "item_name": "M4A4 | Poseidon",
        "wear_name": "Factory New",
        "rarity": 5,
        "type": "skin",
    },
}


@pytest.fixture
def plugin() -> CSFloatPlugin:
    return CSFloatPlugin.__new__(CSFloatPlugin)  # skip __init__, no HTTP client needed


def test_normalize_docs_example(plugin: CSFloatPlugin) -> None:
    raw = CSFloatListing.model_validate(DOCS_EXAMPLE_LISTING)

    normalized = plugin._normalize(raw)

    assert normalized.marketplace == "csfloat"
    assert normalized.listing_id == "324288155723370196"
    assert normalized.weapon == "M4A4"
    assert normalized.skin_name == "Poseidon"
    assert normalized.wear_category == "FN"
    assert normalized.float_value == pytest.approx(0.02796577662229538)
    assert normalized.rarity == "5"
    assert normalized.listing_price == pytest.approx(2600.00)
    assert normalized.buy_order_price == pytest.approx(2210.00)
    assert normalized.event_type == "listed"
    assert normalized.raw_payload["id"] == "324288155723370196"


def test_normalize_rejects_unrecognized_wear_name(plugin: CSFloatPlugin) -> None:
    raw = CSFloatListing.model_validate(
        {**DOCS_EXAMPLE_LISTING, "item": {**DOCS_EXAMPLE_LISTING["item"], "wear_name": None}}
    )

    with pytest.raises(ValueError, match="no recognizable wear_name"):
        plugin._normalize(raw)


def test_normalize_rejects_non_listed_state(plugin: CSFloatPlugin) -> None:
    raw = CSFloatListing.model_validate({**DOCS_EXAMPLE_LISTING, "state": "sold"})

    with pytest.raises(ValueError, match="unexpected state"):
        plugin._normalize(raw)


def test_fetch_listings_filters_out_non_skin_items(plugin: CSFloatPlugin) -> None:
    # Confirmed live 2026-08-30: /listings also returns agents, stickers, etc.,
    # whose item_name would otherwise misparse (e.g. "Special Agent Ava | FBI").
    agent = {
        **DOCS_EXAMPLE_LISTING,
        "id": "agent-1",
        "item": {**DOCS_EXAMPLE_LISTING["item"], "type": "agent", "wear_name": None, "item_name": "Special Agent Ava | FBI"},
    }
    skin = DOCS_EXAMPLE_LISTING

    class _StubClient:
        def fetch_recent_listings(self):
            return [CSFloatListing.model_validate(agent), CSFloatListing.model_validate(skin)]

    plugin._client = _StubClient()

    listings = plugin.fetch_listings()

    assert len(listings) == 1
    assert listings[0].listing_id == "324288155723370196"
