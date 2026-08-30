"""Pydantic response models — API output shapes only, distinct from
ingestion/common/schema.py's NormalizedListing (an ingestion-side concept).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SkinOut(BaseModel):
    weapon: str
    skin_name: str
    wear_category: str
    active_listing_count: int


class ListingOut(BaseModel):
    marketplace: str
    listing_id: str
    weapon: str
    skin_name: str
    wear_category: str
    float_bucket: str
    float_value: float | None
    listing_price: float | None
    buy_order_price: float | None
    last_updated: datetime


class AnalysisResultOut(BaseModel):
    skin_variant_id: int
    weapon: str
    skin_name: str
    wear_category: str
    float_bucket: str
    metric_type: str
    window_days: int | None
    value: float | None
    sample_count: int
    confidence_tier: str
    computed_at: datetime
    details: dict | None
    # True when sample_count is below SIGNAL_MIN_SAMPLE_COUNT — per plan
    # Section 2, suppression is a *display* decision, not a computation one:
    # the row (and its sample size) is still returned, just flagged so the
    # dashboard can render "not enough data" instead of a bare number.
    suppressed: bool


class FreshnessOut(BaseModel):
    marketplace: str
    last_successful_poll: datetime | None
    last_status: str | None
    last_records_ingested: int | None
