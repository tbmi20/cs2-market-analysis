"""Browse/filter step 1 (plan Section 2): pick a skin + wear category. The
float-range sub-filter is a separate step against /listings (see listings.py)
— this endpoint only surfaces the coarse weapon/skin/wear combinations that
currently have active listings.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.dependencies import get_db
from api.schemas import SkinOut
from db.models import Listing, SkinVariant

router = APIRouter()


@router.get("/skins", response_model=list[SkinOut])
def list_skins(
    q: str | None = Query(None, description="Case-insensitive substring match on weapon or skin_name"),
    db: Session = Depends(get_db),
) -> list[SkinOut]:
    query = (
        select(
            SkinVariant.weapon,
            SkinVariant.skin_name,
            SkinVariant.wear_category,
            func.count(Listing.id).label("active_listing_count"),
        )
        .join(Listing, Listing.skin_variant_id == SkinVariant.id)
        .where(Listing.status == "active")
        .group_by(SkinVariant.weapon, SkinVariant.skin_name, SkinVariant.wear_category)
    )
    if q:
        pattern = f"%{q}%"
        query = query.where((SkinVariant.weapon.ilike(pattern)) | (SkinVariant.skin_name.ilike(pattern)))
    query = query.order_by(SkinVariant.weapon, SkinVariant.skin_name, SkinVariant.wear_category)

    return [SkinOut.model_validate(row, from_attributes=True) for row in db.execute(query).all()]
