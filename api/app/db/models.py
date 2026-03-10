from __future__ import annotations

import uuid

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID, ENUM
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


route_mode_enum = ENUM(
    "loop",
    "point-to-point",
    "point-to-destination",
    name="route_mode",
)

route_priority_enum = ENUM(
    "highest-rated",
    "dining",
    "residential",
    "explore",
    name="route_priority",
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Segment(Base):
    __tablename__ = "segments"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    geometry: Mapped[str] = mapped_column(Geometry("LINESTRING", srid=4326), nullable=False)
    osm_tags: Mapped[dict] = mapped_column(JSONB, nullable=False)
    ai_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    composite_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    vibe_tag_counts: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    last_updated: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Rating(Base):
    __tablename__ = "ratings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    segment_id: Mapped[str] = mapped_column(Text, ForeignKey("segments.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    thumbs_up: Mapped[bool] = mapped_column(Boolean, nullable=False)
    vibe_tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    start_point: Mapped[str] = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    end_point: Mapped[str | None] = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    mode: Mapped[str] = mapped_column(route_mode_enum, nullable=False)
    priority: Mapped[str] = mapped_column(route_priority_enum, nullable=False)
    segment_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    duration_s: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
