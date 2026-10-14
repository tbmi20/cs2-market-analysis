"""Browse/filter step 2 (plan Section 2): within a skin + wear category,
sub-filter by an arbitrary float range. Filters `listings.float_value`
directly — independent of the discrete float_buckets used by the analysis
pipeline, per the plan's explicit design note.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.dependencies import get_db
from api.schemas import ListingOut
from db.models import Listing, SkinVariant

router = APIRouter()


@router.get("/listings", response_model=list[ListingOut])
def list_listings(
    weapon: str = Query(...),
    skin_name: str = Query(...),
    wear_category: str | None = Query(None),
    marketplace: str | None = Query(None),
    float_min: float | None = Query(None, ge=0, le=1),
    float_max: float | None = Query(None, ge=0, le=1),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[ListingOut]:
    query = (
        select(
            Listing.marketplace,
            Listing.listing_id,
            SkinVariant.weapon,
            SkinVariant.skin_name,
            SkinVariant.wear_category,
            SkinVariant.float_bucket,
            Listing.float_value,
            Listing.listing_price,
            Listing.buy_order_price,
            Listing.last_updated,
        )
        .join(SkinVariant, SkinVariant.id == Listing.skin_variant_id)
        .where(SkinVariant.weapon == weapon, SkinVariant.skin_name == skin_name, Listing.status == "active")
    )
    if wear_category:
        query = query.where(SkinVariant.wear_category == wear_category)
    if marketplace:
        query = query.where(Listing.marketplace == marketplace)
    if float_min is not None:
        query = query.where(Listing.float_value >= float_min)
    if float_max is not None:
        query = query.where(Listing.float_value <= float_max)

    query = query.order_by(Listing.listing_price.asc()).limit(limit).offset(offset)

    return [ListingOut.model_validate(row, from_attributes=True) for row in db.execute(query).all()]
