"""SQLAlchemy ORM models — the canonical schema definition.

Mirrors plan/cs2-market-analysis-plan.md Section 5. Alembic migrations are
generated from this file (`alembic revision --autogenerate`); this file is
the source of truth, not the migration scripts.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SkinVariant(Base):
    """Canonical identity for a tradeable variant: weapon + skin + wear + float bucket.

    Referenced by Listing, PriceHistory, and AnalysisResult instead of repeating
    these strings in every row.
    """

    __tablename__ = "skin_variants"
    __table_args__ = (
        UniqueConstraint("weapon", "skin_name", "float_bucket"),
        Index("ix_skin_variants_browse", "weapon", "skin_name", "wear_category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    weapon: Mapped[str]
    skin_name: Mapped[str]
    wear_category: Mapped[str]  # FN/MW/FT/WW/BS — top-level browse filter
    float_bucket: Mapped[str]  # premium sub-bucket, or falls back to wear_category


class Listing(Base):
    """Current state: one row per active listing, upserted."""

    __tablename__ = "listings"
    __table_args__ = (
        UniqueConstraint("marketplace", "listing_id"),
        Index("ix_listings_variant_float", "skin_variant_id", "float_value"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    marketplace: Mapped[str]
    listing_id: Mapped[str]  # marketplace's own ID
    skin_variant_id: Mapped[int] = mapped_column(ForeignKey("skin_variants.id"))
    float_value: Mapped[float | None]  # raw float — drives the browse/filter range query directly
    rarity: Mapped[str | None]
    listing_price: Mapped[float | None]  # ask
    buy_order_price: Mapped[float | None]  # bid, if available
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)  # untouched source response
    first_seen: Mapped[datetime] = mapped_column(server_default=func.now())
    last_updated: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class PriceHistory(Base):
    """Append-only: one row per observed price point, never updated."""

    __tablename__ = "price_history"
    __table_args__ = (Index("ix_price_history_variant_time", "skin_variant_id", "observed_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    marketplace: Mapped[str]
    skin_variant_id: Mapped[int] = mapped_column(ForeignKey("skin_variants.id"))
    price: Mapped[float]
    event_type: Mapped[str]  # 'listed' | 'sold' | 'buy_order'
    observed_at: Mapped[datetime] = mapped_column(server_default=func.now())


class FloatBucket(Base):
    """Config: float bucket boundaries — both premium sub-buckets and the five
    default wear-category fallbacks. Adjustable without code changes.

    Resolution order: try non-default (premium) buckets first; if none match,
    fall back to the default bucket whose range contains the float.
    """

    __tablename__ = "float_buckets"

    bucket_label: Mapped[str] = mapped_column(primary_key=True)
    min_float: Mapped[float]
    max_float: Mapped[float]
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class MarketplaceFee(Base):
    """Config: fee schedule per marketplace."""

    __tablename__ = "marketplace_fees"

    marketplace: Mapped[str] = mapped_column(primary_key=True)
    seller_fee_pct: Mapped[float]
    notes: Mapped[str | None]  # e.g. wallet lock, currency conversion caveats


class AnalysisResult(Base):
    """Output of scheduled analysis modules."""

    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    skin_variant_id: Mapped[int] = mapped_column(ForeignKey("skin_variants.id"))
    metric_type: Mapped[str]  # 'trend' | 'arbitrage' | 'volatility'
    window_days: Mapped[int | None]  # e.g. 7, 30
    value: Mapped[float | None]
    sample_count: Mapped[int]
    confidence_tier: Mapped[str]  # 'low' | 'medium' | 'high'
    computed_at: Mapped[datetime] = mapped_column(server_default=func.now())


class IngestionRun(Base):
    """One row per ingestion poll attempt, per marketplace — powers the
    dashboard's data-freshness display and lets a silent polling failure be
    noticed.
    """

    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    marketplace: Mapped[str]
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    status: Mapped[str]  # 'success' | 'failed' | 'partial'
    records_ingested: Mapped[int | None]
    error_message: Mapped[str | None]
