"""add parks table

Revision ID: 002_add_parks_table
Revises: 001_initial_schema
Create Date: 2026-03-12 00:00:00.000000
"""

import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "002_add_parks_table"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "parks",
        sa.Column("id", sa.Text(), primary_key=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("geometry", Geometry("GEOMETRY", srid=4326), nullable=False),
        sa.Column("osm_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.create_index("ix_parks_geometry", "parks", ["geometry"], postgresql_using="gist")


def downgrade() -> None:
    op.drop_index("ix_parks_geometry", table_name="parks")
    op.drop_table("parks")
