"""Step 3: LOAD — read staging JSONL, upsert into relational tables."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import typer
from dotenv import load_dotenv
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.db.bootstrap import create_all
from src.db.session import get_session
from src.db.models import Vehicle, Listing, PriceHistory
from src.pipeline.utils import logger, staging_dir


def load():
    """Read staging JSONL and upsert into vehicle/listing/price_history."""
    load_dotenv()
    create_all()

    in_path = staging_dir() / "cleaned.jsonl"
    if not in_path.exists():
        logger.error("Staging file not found: %s", in_path)
        raise typer.Exit(code=2)

    loaded = 0

    with get_session() as session, in_path.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)

            source_site = rec.get("source_site")
            original_ad_id = rec.get("original_ad_id")
            if not source_site or not original_ad_id:
                continue

            url = rec.get("source_url")
            location = rec.get("location")

            recorded_at = datetime.fromisoformat(rec["scraped_at"])
            if recorded_at.tzinfo is None:
                recorded_at = recorded_at.replace(tzinfo=timezone.utc)

            # --- Upsert listing ---
            stmt = (
                pg_insert(Listing)
                .values(
                    source_site=source_site,
                    original_ad_id=original_ad_id,
                    url=url,
                    location=location,
                    is_active=True,
                    first_seen_at=recorded_at,
                    last_seen_at=recorded_at,
                )
                .on_conflict_do_update(
                    constraint="uq_listing_source_ad",
                    set_={
                        "url": url,
                        "location": location,
                        "is_active": True,
                        "last_seen_at": recorded_at,
                    },
                )
                .returning(Listing.id, Listing.vehicle_id)
            )

            listing_id, vehicle_id = session.execute(stmt).first()
            session.flush()

            # --- Create vehicle if listing has no vehicle_id yet ---
            if vehicle_id is None:
                vp = rec.get("vehicle") or {}
                v = Vehicle(
                    make=vp.get("make"),
                    model=vp.get("model"),
                    first_registration_year=vp.get("first_registration_year"),
                    mileage_km=vp.get("mileage_km"),
                    fuel_type=vp.get("fuel_type"),
                    vehicle_type=vp.get("vehicle_type"),
                    power_bhp=vp.get("power_bhp"),
                    transmission=vp.get("transmission"),
                    engine_size_l=vp.get("engine_size_l"),
                    color=vp.get("color"),
                    doors=vp.get("doors"),
                    seats=vp.get("seats"),
                    emission_class=vp.get("emission_class"),
                    ulez=vp.get("ulez"),
                    is_new_car=vp.get("is_new_car"),
                    is_taxi=vp.get("is_taxi"),
                )
                session.add(v)
                session.flush()

                session.execute(
                    update(Listing)
                    .where(Listing.id == listing_id)
                    .values(vehicle_id=v.id)
                )

            # --- Insert price history (skip duplicates) ---
            ph_stmt = (
                pg_insert(PriceHistory)
                .values(
                    listing_id=listing_id,
                    price=rec.get("price_amount"),
                    price_currency=rec.get("price_currency"),
                    recorded_at=recorded_at,
                )
                .on_conflict_do_nothing(constraint="uq_price_listing_time")
            )
            session.execute(ph_stmt)
            loaded += 1

        session.commit()

    logger.info("Load done: %d records upserted", loaded)
