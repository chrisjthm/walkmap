"""add pois table

Revision ID: 004_add_pois_table
Revises: 003_add_water_features_table
Create Date: 2026-03-13 00:00:00.000000
"""

import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "004_add_pois_table"
down_revision = "003_add_water_features_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pois",
        sa.Column("id", sa.Text(), primary_key=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("geometry", Geometry("GEOMETRY", srid=4326), nullable=False),
        sa.Column("osm_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.create_index(
        "ix_pois_geometry",
        "pois",
        ["geometry"],
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_index("ix_pois_geometry", table_name="pois")
    op.drop_table("pois")
