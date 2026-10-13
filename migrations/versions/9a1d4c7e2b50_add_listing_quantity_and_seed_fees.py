"""add listing quantity and seed marketplace fees

Revision ID: 9a1d4c7e2b50
Revises: 0f3b0e3c0a7d
Create Date: 2026-10-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert


# revision identifiers, used by Alembic.
revision: str = '9a1d4c7e2b50'
down_revision: Union[str, Sequence[str], None] = '0f3b0e3c0a7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

marketplace_fees = sa.table(
    "marketplace_fees",
    sa.column("marketplace", sa.String),
    sa.column("seller_fee_pct", sa.Float),
    sa.column("notes", sa.String),
)

# Standard seller fees as of 2026-10 — analysis/arbitrage.py skips any
# marketplace without a row here. Edit the rows directly to adjust; reruns
# won't overwrite them.
FEES = [
    {"marketplace": "csfloat", "seller_fee_pct": 2.0, "notes": "Standard sale fee"},
    {"marketplace": "skinport", "seller_fee_pct": 8.0, "notes": "Standard seller fee; Skinport prices are requested in USD"},
]


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('listings', sa.Column('quantity', sa.Integer(), server_default='1', nullable=False))
    op.execute(pg_insert(marketplace_fees).values(FEES).on_conflict_do_nothing(index_elements=["marketplace"]))


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(marketplace_fees.delete().where(marketplace_fees.c.marketplace.in_([f["marketplace"] for f in FEES])))
    op.drop_column('listings', 'quantity')
