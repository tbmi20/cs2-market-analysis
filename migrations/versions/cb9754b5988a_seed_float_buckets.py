"""seed float buckets

Revision ID: cb9754b5988a
Revises: ee4a1fc7b6cc
Create Date: 2026-08-30 19:37:35.203475

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cb9754b5988a'
down_revision: Union[str, Sequence[str], None] = 'ee4a1fc7b6cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Lightweight table handle for data-only migrations — see plan Section 5/2.
float_buckets = sa.table(
    "float_buckets",
    sa.column("bucket_label", sa.String),
    sa.column("min_float", sa.Float),
    sa.column("max_float", sa.Float),
    sa.column("is_default", sa.Boolean),
)

# The five standard wear categories — fallback bucket for any float that
# doesn't land in one of the premium sub-buckets below.
DEFAULT_BUCKETS = [
    {"bucket_label": "FN", "min_float": 0.00, "max_float": 0.07, "is_default": True},
    {"bucket_label": "MW", "min_float": 0.07, "max_float": 0.15, "is_default": True},
    {"bucket_label": "FT", "min_float": 0.15, "max_float": 0.38, "is_default": True},
    {"bucket_label": "WW", "min_float": 0.38, "max_float": 0.45, "is_default": True},
    {"bucket_label": "BS", "min_float": 0.45, "max_float": 1.00, "is_default": True},
]

# Extra granularity within those categories — checked first during bucket
# resolution (see plan Section 2).
PREMIUM_BUCKETS = [
    {"bucket_label": "Full FN", "min_float": 0.00, "max_float": 0.01, "is_default": False},
    {"bucket_label": "FN (upper)", "min_float": 0.01, "max_float": 0.03, "is_default": False},
    {"bucket_label": "FN (lower)", "min_float": 0.03, "max_float": 0.07, "is_default": False},
    {"bucket_label": "Min Wear", "min_float": 0.07, "max_float": 0.09, "is_default": False},
    {"bucket_label": "Field-Tested (key range)", "min_float": 0.15, "max_float": 0.18, "is_default": False},
    {"bucket_label": "Battle-Scarred (max)", "min_float": 0.90, "max_float": 1.00, "is_default": False},
]


def upgrade() -> None:
    """Upgrade schema."""
    op.bulk_insert(float_buckets, DEFAULT_BUCKETS + PREMIUM_BUCKETS)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(float_buckets.delete())
