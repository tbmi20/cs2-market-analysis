"""get_or_create for skin_variants — the canonical identity every listing,
price_history, and analysis_result row references instead of repeating
weapon/skin/bucket strings (see plan Section 5).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from consolidator.float_buckets import resolve_float_bucket
from db.models import SkinVariant


def get_or_create_skin_variant(
    session: Session,
    *,
    weapon: str,
    skin_name: str,
    wear_category: str,
    float_value: float | None,
) -> int:
    float_bucket = resolve_float_bucket(session, wear_category, float_value)

    stmt = (
        pg_insert(SkinVariant)
        .values(weapon=weapon, skin_name=skin_name, wear_category=wear_category, float_bucket=float_bucket)
        .on_conflict_do_nothing(index_elements=[SkinVariant.weapon, SkinVariant.skin_name, SkinVariant.float_bucket])
        .returning(SkinVariant.id)
    )
    variant_id = session.execute(stmt).scalar_one_or_none()
    if variant_id is not None:
        return variant_id

    # Conflict happened (variant already existed) — look up its id instead.
    return session.execute(
        select(SkinVariant.id).where(
            SkinVariant.weapon == weapon,
            SkinVariant.skin_name == skin_name,
            SkinVariant.float_bucket == float_bucket,
        )
    ).scalar_one()
