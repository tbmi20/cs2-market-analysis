"""Float bucket resolution: given a float value and a wear category, find the
`float_buckets` config row to use — a premium sub-bucket takes priority over
the wear category's own default bucket (see plan Section 2/5).

Ranges are treated as half-open [min, max) — e.g. "FN (lower)" (0.03-0.07)
and "Min Wear" (0.07-0.09) share the boundary 0.07, which would otherwise
match both rows non-deterministically — except the very top bucket of each
tier, whose max is inclusive so float_value == 1.0 still resolves.
"""

from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from db.models import FloatBucket


def _in_range(float_value: float):
    return and_(
        FloatBucket.min_float <= float_value,
        or_(float_value < FloatBucket.max_float, FloatBucket.max_float >= 1.0),
    )


def resolve_float_bucket(session: Session, wear_category: str, float_value: float | None) -> str:
    """Returns a bucket_label.

    Falls back to `wear_category` itself if `float_value` is missing (some
    items — gloves, knives without a float — may not expose one) or doesn't
    land in any configured range. The default buckets are meant to cover
    [0, 1] completely, so that fallback should be rare, but a gap or a bad
    float value shouldn't take down ingestion.
    """
    if float_value is not None:
        premium = session.execute(
            select(FloatBucket.bucket_label).where(FloatBucket.is_default.is_(False), _in_range(float_value)).limit(1)
        ).scalar_one_or_none()
        if premium is not None:
            return premium

        default = session.execute(
            select(FloatBucket.bucket_label).where(FloatBucket.is_default.is_(True), _in_range(float_value)).limit(1)
        ).scalar_one_or_none()
        if default is not None:
            return default

    return wear_category
