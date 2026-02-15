"""SQLAlchemy models for the Heycar data warehouse.

Tables:
    raw_data      — immutable audit log of every API response
    vehicle       — canonical vehicle attributes (one per unique car)
    listing       — marketplace listing (links a vehicle to a seller)
    price_history — time-series price tracking per listing
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import text


Base = declarative_base()

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RawData(Base):
    """Immutable audit log — stores the full API response for every scrape."""
    __tablename__ = "raw_data"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    raw_content = Column(JSONB, nullable=False)

    scraped_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    source_site = Column(String(50), nullable=True)
    source_url = Column(Text, nullable=True)

    # Set by the transform step once this row is processed
    processed_at = Column(DateTime(timezone=True), nullable=True)
    error_log = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_raw_data_scraped_at", "scraped_at"),
        Index("ix_raw_data_source_site", "source_site"),
        Index("ix_raw_data_processed_at", "processed_at"),
    )


class Vehicle(Base):
    """Canonical vehicle attributes — one row per unique car."""
    __tablename__ = "vehicle"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))

    make = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    first_registration_year = Column(Integer, nullable=True)
    mileage_km = Column(Integer, nullable=True)

    fuel_type = Column(String(50), nullable=True)
    vehicle_type = Column(String(50), nullable=True)    # e.g. suv, hatchback

    # BHP = Brake Horsepower — standard measure of engine power output
    power_bhp = Column(Integer, nullable=True)

    transmission = Column(String(50), nullable=True)    # e.g. manual, semiauto

    # Engine displacement in litres, e.g. 2.0 means a 2-litre engine
    engine_size_l = Column(Numeric(3, 1), nullable=True)

    color = Column(String(50), nullable=True)
    doors = Column(Integer, nullable=True)
    seats = Column(Integer, nullable=True)

    # EU emission standard the car meets (euro4, euro5, euro6, etc.)
    emission_class = Column(String(20), nullable=True)

    # ULEZ = Ultra Low Emission Zone (London) — True if the car can
    # drive in the zone without paying an extra daily charge
    ulez = Column(Boolean, nullable=True)

    is_new_car = Column(Boolean, nullable=True)
    is_taxi = Column(Boolean, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    listings = relationship("Listing", back_populates="vehicle", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_vehicle_make_model_year", "make", "model", "first_registration_year"),
    )


class Listing(Base):
    """A marketplace listing — links a vehicle to a seller/source."""
    __tablename__ = "listing"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    vehicle_id = Column(UUID(as_uuid=True), ForeignKey("vehicle.id", ondelete="SET NULL"), nullable=True)

    # The listing ID from the source website (e.g. "15469060" from heycar)
    # Used to detect duplicates — same ad_id + source_site = same listing
    original_ad_id = Column(String(255), nullable=False)
    source_site = Column(String(50), nullable=False)
    url = Column(Text, nullable=True)

    location = Column(String(200), nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)

    first_seen_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    vehicle = relationship("Vehicle", back_populates="listings")
    prices = relationship("PriceHistory", back_populates="listing", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("source_site", "original_ad_id", name="uq_listing_source_ad"),
        Index("ix_listing_source_site", "source_site"),
        Index("ix_listing_location", "location"),
    )


class PriceHistory(Base):
    """Time-series price tracking — one row per (listing, timestamp)."""
    __tablename__ = "price_history"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    listing_id = Column(UUID(as_uuid=True), ForeignKey("listing.id", ondelete="CASCADE"), nullable=False)

    price = Column(Numeric(12, 2), nullable=True)
    price_currency = Column(String(3), nullable=True)  # e.g. "GBP"

    recorded_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    listing = relationship("Listing", back_populates="prices")

    __table_args__ = (
        Index("ix_price_history_listing_time", "listing_id", "recorded_at"),
        UniqueConstraint("listing_id", "recorded_at", name="uq_price_listing_time"),
    )
