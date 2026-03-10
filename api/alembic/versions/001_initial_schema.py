"""initial schema

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-03-10 00:00:00.000000
"""

import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    route_mode = postgresql.ENUM(
        "loop",
        "point-to-point",
        "point-to-destination",
        name="route_mode",
        create_type=False,
    )
    route_priority = postgresql.ENUM(
        "highest-rated",
        "dining",
        "residential",
        "explore",
        name="route_priority",
        create_type=False,
    )

    bind = op.get_bind()
    route_mode.create(bind, checkfirst=True)
    route_priority.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "segments",
        sa.Column("id", sa.Text(), primary_key=True, nullable=False),
        sa.Column("geometry", Geometry("LINESTRING", srid=4326), nullable=False),
        sa.Column("osm_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ai_score", sa.Float(), nullable=True),
        sa.Column("ai_confidence", sa.Float(), nullable=True),
        sa.Column("user_score", sa.Float(), nullable=True),
        sa.Column("composite_score", sa.Float(), nullable=True),
        sa.Column("verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("rating_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("vibe_tag_counts", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "ratings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("segment_id", sa.Text(), sa.ForeignKey("segments.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("thumbs_up", sa.Boolean(), nullable=False),
        sa.Column("vibe_tags", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("segment_id", "user_id", name="uq_ratings_segment_user"),
    )

    op.create_table(
        "routes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("start_point", Geometry("POINT", srid=4326), nullable=False),
        sa.Column("end_point", Geometry("POINT", srid=4326), nullable=True),
        sa.Column("mode", route_mode, nullable=False),
        sa.Column("priority", route_priority, nullable=False),
        sa.Column("segment_ids", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("distance_m", sa.Float(), nullable=False),
        sa.Column("duration_s", sa.Integer(), nullable=False),
        sa.Column("avg_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_index("ix_segments_geometry", "segments", ["geometry"], postgresql_using="gist")
    op.create_index("ix_segments_composite_score", "segments", ["composite_score"])
    op.create_index("ix_ratings_segment_id", "ratings", ["segment_id"])
    op.create_index("ix_ratings_user_id", "ratings", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_ratings_user_id", table_name="ratings")
    op.drop_index("ix_ratings_segment_id", table_name="ratings")
    op.drop_index("ix_segments_composite_score", table_name="segments")
    op.drop_index("ix_segments_geometry", table_name="segments")

    op.drop_table("routes")
    op.drop_table("ratings")
    op.drop_table("segments")
    op.drop_table("users")

    route_priority = postgresql.ENUM(
        "highest-rated",
        "dining",
        "residential",
        "explore",
        name="route_priority",
    )
    route_mode = postgresql.ENUM(
        "loop",
        "point-to-point",
        "point-to-destination",
        name="route_mode",
    )

    bind = op.get_bind()
    route_priority.drop(bind, checkfirst=True)
    route_mode.drop(bind, checkfirst=True)
