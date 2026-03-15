"""add pois geography gist index

Revision ID: 006_add_pois_geography_index
Revises: 005_add_segment_factors
Create Date: 2026-03-15 00:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "006_add_pois_geography_index"
down_revision = "005_add_segment_factors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_pois_geography",
        "pois",
        [sa.text("geography(geometry)")],
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_index("ix_pois_geography", table_name="pois")
