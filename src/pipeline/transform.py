"""Step 2: TRANSFORM — clean, validate, deduplicate, write staging JSONL."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import typer
from dotenv import load_dotenv
from sqlalchemy import select

from src.db.bootstrap import create_all
from src.db.session import get_session
from src.db.models import RawData
from src.transform.extract_from_trader import extract_ad_fields
from src.transform.standardize import canonical_make, canonical_model
from src.pipeline.utils import logger, staging_dir


# Validation: records missing these fields are rejected
REQUIRED_FIELDS = {"id", "price"}


def transform(limit: int = typer.Option(0, help="Max rows to process (0 = all)")):
    """Read unprocessed raw_data, clean & validate, write staging JSONL."""
    load_dotenv()
    create_all()

    out_path = staging_dir() / "cleaned.jsonl"
    ok = 0
    skipped = 0
    errors = 0
    seen_ad_ids: set[str] = set()  # Track IDs we've already processed to skip duplicates

    with get_session() as session, out_path.open("w", encoding="utf-8") as f:
        query = (
            select(RawData)
            .where(RawData.processed_at.is_(None))
            .order_by(RawData.scraped_at.asc())
        )
        rows = session.execute(query).scalars().all()

        if limit > 0:
            rows = rows[:limit]

        if not rows:
            logger.info("No unprocessed raw_data rows — nothing to transform")
            return

        logger.info("Transforming %d raw rows", len(rows))

        for row in rows:
            now = datetime.now(timezone.utc)
            try:
                extracted = extract_ad_fields(row.raw_content or {})

                # --- Validation: reject if critical fields are missing ---
                missing = REQUIRED_FIELDS - extracted.keys()
                if missing:
                    raise ValueError(f"Missing required fields: {missing}")

                ad_id = extracted["id"]

                # --- Deduplication: skip if we already saw this ad in this batch ---
                if ad_id in seen_ad_ids:
                    row.processed_at = now
                    row.error_log = "duplicate_in_batch"
                    skipped += 1
                    continue
                seen_ad_ids.add(ad_id)

                # --- Standardize make/model ---
                make = extracted.get("make")
                model = extracted.get("model")
                if make:
                    extracted["make"] = canonical_make(make)
                if model:
                    extracted["model"] = canonical_model(model)

                # --- Build staging record ---
                # Each record combines listing info + vehicle specs for the load step
                rec = {
                    "source_site": row.source_site,
                    "source_url": row.source_url,
                    "scraped_at": row.scraped_at.isoformat(),

                    # original_ad_id = the listing ID on the source website
                    # (used for deduplication across scraping runs)
                    "original_ad_id": ad_id,

                    "location": extracted.get("location"),
                    "price_amount": extracted.get("price"),
                    "price_currency": extracted.get("currency"),
                    "vehicle": {
                        "make": extracted.get("make"),
                        "model": extracted.get("model"),
                        "first_registration_year": extracted.get("year"),
                        "mileage_km": extracted.get("mileage"),
                        "fuel_type": extracted.get("fuel_type"),
                        "vehicle_type": extracted.get("body_type"),

                        # BHP = Brake Horsepower (engine power output)
                        "power_bhp": extracted.get("power_bhp"),

                        "transmission": extracted.get("transmission"),

                        # Engine displacement in litres (e.g. 2.0 = 2-litre engine)
                        "engine_size_l": extracted.get("engine_size_l"),

                        "color": extracted.get("color"),
                        "doors": extracted.get("doors"),
                        "seats": extracted.get("seats"),

                        # EU emission standard (euro4, euro5, euro6…)
                        "emission_class": extracted.get("emission_class"),

                        # ULEZ = Ultra Low Emission Zone (London)
                        "ulez": extracted.get("ulez"),

                        # New flags (Feb 2026)
                        "is_new_car": extracted.get("is_new_car"),
                        "is_taxi": extracted.get("is_taxi"),
                    },
                }

                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                row.processed_at = now
                row.error_log = None
                ok += 1

            except Exception as e:
                row.processed_at = now
                row.error_log = str(e)[:2000]
                errors += 1

        session.commit()

    logger.info("Transform done: ok=%d  skipped=%d  errors=%d  → %s", ok, skipped, errors, out_path)
