"""add price_window_stats view

Revision ID: c6dedc59014b
Revises: cb9754b5988a
Create Date: 2026-08-30 19:58:38.910528

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c6dedc59014b'
down_revision: Union[str, Sequence[str], None] = 'cb9754b5988a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


VIEW_NAME = "price_window_stats"

# Plain SQL view (plan Section 7: "Transform layer: Plain SQL views" — window
# functions are a good fit here). Computed for both the 7d and 30d windows in
# one pass via CROSS JOIN, for every skin_variant that has at least one
# `listed` observation in its current window. `analysis/trend.py` reads this
# view and does nothing but confidence-tier arithmetic in Python.
CREATE_VIEW_SQL = """
CREATE VIEW price_window_stats AS
SELECT
    sv.id AS skin_variant_id,
    w.window_days,
    cur.avg_price,
    cur.stddev_price,
    cur.sample_count,
    prev.avg_price AS previous_avg_price
FROM skin_variants sv
CROSS JOIN (VALUES (7), (30)) AS w(window_days)
LEFT JOIN LATERAL (
    SELECT AVG(price) AS avg_price, STDDEV_SAMP(price) AS stddev_price, COUNT(*) AS sample_count
    FROM price_history ph
    WHERE ph.skin_variant_id = sv.id
      AND ph.event_type = 'listed'
      AND ph.observed_at >= NOW() - (w.window_days::text || ' days')::interval
) cur ON TRUE
LEFT JOIN LATERAL (
    SELECT AVG(price) AS avg_price
    FROM price_history ph
    WHERE ph.skin_variant_id = sv.id
      AND ph.event_type = 'listed'
      AND ph.observed_at >= NOW() - ((w.window_days * 2)::text || ' days')::interval
      AND ph.observed_at <  NOW() - (w.window_days::text || ' days')::interval
) prev ON TRUE
WHERE cur.sample_count > 0;
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(CREATE_VIEW_SQL)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"DROP VIEW {VIEW_NAME}")
