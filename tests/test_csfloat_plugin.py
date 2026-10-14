"""Validates CSFloat raw->normalized mapping against the exact example
listing from https://docs.csfloat.com/ (GET /v1/listings), so the mapping is
checked against real documented field names/shapes rather than assumptions.
"""

from __future__ import annotations

from collections import OrderedDict

import httpx
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


def listing(**overrides) -> CSFloatListing:
    return CSFloatListing.model_validate({**DOCS_EXAMPLE_LISTING, **overrides})


class _StubClient:
    def __init__(self) -> None:
        self.recent: list[CSFloatListing] = []
        self.by_id: dict[str, CSFloatListing | None | Exception] = {}
        self.fetched_ids: list[str] = []
        self.listing_rate_limit_remaining: int | None = None

    def fetch_recent_listings(self) -> list[CSFloatListing]:
        return self.recent

    def fetch_listing(self, listing_id: str) -> CSFloatListing | None:
        self.fetched_ids.append(listing_id)
        result = self.by_id[listing_id]
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def plugin() -> CSFloatPlugin:
    plugin = CSFloatPlugin.__new__(CSFloatPlugin)  # skip __init__, no HTTP client needed
    plugin._client = _StubClient()
    plugin._recheck_per_poll = 2
    plugin._tracked = OrderedDict()
    return plugin


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


@pytest.mark.parametrize(
    ("state", "event_type"),
    [("listed", "listed"), ("sold", "sold"), ("delisted", "delisted"), ("refunded", "delisted")],
)
def test_normalize_maps_state_to_event_type(plugin: CSFloatPlugin, state: str, event_type: str) -> None:
    assert plugin._normalize(listing(state=state)).event_type == event_type


def test_fetch_listings_filters_out_non_skin_items(plugin: CSFloatPlugin) -> None:
    # Confirmed live 2026-08-30: /listings also returns agents, stickers, etc.,
    # whose item_name would otherwise misparse (e.g. "Special Agent Ava | FBI").
    agent = {
        **DOCS_EXAMPLE_LISTING,
        "id": "agent-1",
        "item": {**DOCS_EXAMPLE_LISTING["item"], "type": "agent", "wear_name": None, "item_name": "Special Agent Ava | FBI"},
    }
    skin = DOCS_EXAMPLE_LISTING

    plugin._client.recent = [CSFloatListing.model_validate(agent), CSFloatListing.model_validate(skin)]

    listings = plugin.fetch_listings()

    assert len(listings) == 1
    assert listings[0].listing_id == "324288155723370196"


def test_recheck_publishes_changes_and_stops_tracking_removed_listings(plugin: CSFloatPlugin) -> None:
    plugin._client.recent = [listing(id="repriced"), listing(id="sold"), listing(id="delisted"), listing(id="gone")]
    plugin.fetch_listings()
    plugin._client.recent = []
    plugin._recheck_per_poll = 4
    plugin._client.by_id = {
        "repriced": listing(id="repriced", price=250000),
        "sold": listing(id="sold", state="sold"),
        "delisted": listing(id="delisted", state="delisted"),
        "gone": None,  # 404
    }

    published = {l.listing_id: l for l in plugin.fetch_listings()}

    assert published["repriced"].event_type == "listed"
    assert published["repriced"].listing_price == pytest.approx(2500.00)
    assert published["sold"].event_type == "sold"
    assert published["delisted"].event_type == "delisted"
    assert "gone" not in published  # nothing to publish; the staleness sweep expires it
    assert list(plugin._tracked) == ["repriced"]


def test_recheck_rotates_through_least_recently_checked(plugin: CSFloatPlugin) -> None:
    plugin._client.recent = [listing(id=i) for i in ("a", "b", "c")]
    plugin.fetch_listings()
    assert plugin._client.fetched_ids == []  # just seen in the feed, no need to recheck yet

    plugin._client.recent = []
    plugin._client.by_id = {i: listing(id=i) for i in ("a", "b", "c")}
    plugin.fetch_listings()
    plugin.fetch_listings()

    assert plugin._client.fetched_ids == ["a", "b", "c", "a"]


def test_recheck_failure_keeps_tracking(plugin: CSFloatPlugin) -> None:
    plugin._client.recent = [listing(id="flaky")]
    plugin.fetch_listings()
    plugin._client.recent = []
    plugin._client.by_id = {"flaky": httpx.ConnectError("boom")}

    assert plugin.fetch_listings() == []
    assert list(plugin._tracked) == ["flaky"]


def test_recheck_skipped_when_rate_limit_low(plugin: CSFloatPlugin) -> None:
    plugin._client.recent = [listing()]
    plugin.fetch_listings()
    plugin._client.recent = []
    plugin._client.listing_rate_limit_remaining = 10

    plugin.fetch_listings()

    assert plugin._client.fetched_ids == []
