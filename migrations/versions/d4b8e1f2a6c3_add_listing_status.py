"""add listing status and removed_at

Revision ID: d4b8e1f2a6c3
Revises: 9a1d4c7e2b50
Create Date: 2026-10-13 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4b8e1f2a6c3'
down_revision: Union[str, Sequence[str], None] = '9a1d4c7e2b50'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('listings', sa.Column('status', sa.String(), server_default='active', nullable=False))
    op.add_column('listings', sa.Column('removed_at', sa.DateTime(), nullable=True))
    op.create_index('ix_listings_status_last_updated', 'listings', ['status', 'last_updated'], unique=False)
    # Before this column existed, a gone Skinport item was marked by a NULL
    # price. Stale CSFloat rows are left 'active' — the consolidator's
    # staleness sweep expires them once they pass LISTING_STALE_AFTER_HOURS.
    op.execute("UPDATE listings SET status = 'delisted', removed_at = last_updated WHERE listing_price IS NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("UPDATE listings SET listing_price = NULL WHERE status <> 'active'")
    op.drop_index('ix_listings_status_last_updated', table_name='listings')
    op.drop_column('listings', 'removed_at')
    op.drop_column('listings', 'status')
