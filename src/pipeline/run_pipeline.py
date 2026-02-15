"""Pipeline CLI — the four ETL steps: extract → transform → load → analyze.

Each step is a standalone Typer command that can be run independently:
    python -m src.pipeline.run_pipeline extract --pages 2
    python -m src.pipeline.run_pipeline transform
    python -m src.pipeline.run_pipeline load
    python -m src.pipeline.run_pipeline analyze
"""
from __future__ import annotations

import json
import logging
import os
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import typer
from dotenv import load_dotenv
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.db.bootstrap import create_all
from src.db.session import get_session, get_engine
from src.db.models import RawData, Vehicle, Listing, PriceHistory
from src.ingest.scraper import scrape_batch
from src.transform.extract_from_trader import extract_ad_fields
from src.transform.standardize import canonical_make, canonical_model

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("heycar.pipeline")

app = typer.Typer(no_args_is_help=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_run_id() -> str:
    """Build a folder name from the current local time (Europe/Berlin).

    Using local time instead of Airflow's UTC-based run ID so folder
    names match the wall-clock time the user sees.
    Example: 'run_2026-02-12_01-09'
    """
    from zoneinfo import ZoneInfo  # stdlib since Python 3.9

    now = datetime.now(ZoneInfo("Europe/Berlin"))
    return now.strftime("run_%Y-%m-%d_%H-%M")


def _staging_dir() -> Path:
    d = Path("data/staging") / _safe_run_id()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _analysis_dir() -> Path:
    d = Path("analysis/output") / _safe_run_id()
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Step 1: EXTRACT — fetch raw listings and store in raw_data
# ---------------------------------------------------------------------------

@app.command()
def extract(pages: int = typer.Option(1, help="Number of list pages to fetch")):
    # pages = how many API pages to scrape (1 page = 20 listings)
    # In the DAG we use --pages 3 → fetches 60 listings per run
    """Fetch listings from the Trader API and store full JSON in raw_data."""
    load_dotenv()
    create_all()

    batch = scrape_batch(pages=pages)
    logger.info("Scraped %d listings", len(batch))



    inserted = 0
    with get_session() as session:
        for item in batch:
            session.add(
                RawData(
                    raw_content=item.raw_payload,
                    scraped_at=item.scraped_at,
                    source_site=item.source,
                    source_url=str(item.canonical_url),
                    processed_at=None,
                    error_log=None,
                )
            )
            inserted += 1
        session.commit()

    logger.info("Extract done: %d rows inserted into raw_data", inserted)


# ---------------------------------------------------------------------------
# Step 2: TRANSFORM — clean, validate, deduplicate, write staging JSONL
# ---------------------------------------------------------------------------

# Validation: records missing these fields are rejected
REQUIRED_FIELDS = {"id", "price"}


@app.command()
def transform(limit: int = typer.Option(0, help="Max rows to process (0 = all)")):
    """Read unprocessed raw_data, clean & validate, write staging JSONL."""
    load_dotenv()
    create_all()

    out_path = _staging_dir() / "cleaned.jsonl"
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


# ---------------------------------------------------------------------------
# Step 3: LOAD — read staging JSONL, upsert into relational tables
# ---------------------------------------------------------------------------

@app.command()
def load():
    """Read staging JSONL and upsert into vehicle/listing/price_history."""
    load_dotenv()
    create_all()

    in_path = _staging_dir() / "cleaned.jsonl"
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


# ---------------------------------------------------------------------------
# Step 4: ANALYZE — generate CSV reports and PNG charts
# ---------------------------------------------------------------------------

@app.command()
def analyze():
    """Generate CSV tables and PNG charts from the warehouse data."""
    load_dotenv()
    create_all()

    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")  # Non-interactive backend for Docker
    import matplotlib.pyplot as plt

    out_dir = _analysis_dir()
    engine = get_engine()

    def query_to_csv(name: str, sql: str) -> pd.DataFrame:
        """Run a SQL query, save to CSV, return the DataFrame."""
        try:
            with engine.connect() as conn:
                df = pd.read_sql_query(sql, conn)
        except Exception:
            with closing(engine.raw_connection()) as raw:
                df = pd.read_sql_query(sql, raw)

        path = out_dir / f"{name}.csv"
        df.to_csv(path, index=False)
        logger.info("Wrote %s (%d rows)", path, len(df))
        return df

    # -----------------------------------------------------------------------
    # Analysis 1: Average price by make (top 15)
    # -----------------------------------------------------------------------
    df_make = query_to_csv("avg_price_by_make", """
        SELECT v.make,
               COUNT(*) AS listings,
               ROUND(AVG(ph.price)::numeric, 0) AS avg_price
        FROM price_history ph
        JOIN listing l ON l.id = ph.listing_id
        JOIN vehicle v ON v.id = l.vehicle_id
        WHERE ph.price IS NOT NULL AND v.make IS NOT NULL
        GROUP BY v.make
        ORDER BY listings DESC
        LIMIT 15;
    """)

    if not df_make.empty:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.barh(df_make["make"], df_make["avg_price"], color="#2563eb")
        ax.set_xlabel("Average Price (£)")
        ax.set_title("Average Price by Make (Top 15)")
        ax.invert_yaxis()
        fig.tight_layout()
        fig.savefig(out_dir / "avg_price_by_make.png", dpi=150)
        plt.close(fig)

    # -----------------------------------------------------------------------
    # Analysis 2: Price vs mileage (depreciation scatter)
    # -----------------------------------------------------------------------
    df_scatter = query_to_csv("price_vs_mileage", """
        SELECT v.make, v.mileage_km, ph.price
        FROM price_history ph
        JOIN listing l ON l.id = ph.listing_id
        JOIN vehicle v ON v.id = l.vehicle_id
        WHERE ph.price IS NOT NULL
          AND v.mileage_km IS NOT NULL
          AND v.mileage_km > 0;
    """)

    if not df_scatter.empty:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.scatter(
            df_scatter["mileage_km"] / 1000,
            df_scatter["price"],
            alpha=0.4, s=10, color="#059669",
        )
        ax.set_xlabel("Mileage (×1000 km)")
        ax.set_ylabel("Price (£)")
        ax.set_title("Price vs Mileage — Depreciation Overview")
        fig.tight_layout()
        fig.savefig(out_dir / "price_vs_mileage.png", dpi=150)
        plt.close(fig)

    # -----------------------------------------------------------------------
    # Analysis 3: Market share by fuel type (pie chart)
    # -----------------------------------------------------------------------
    df_fuel = query_to_csv("market_share_by_fuel", """
        SELECT v.fuel_type, COUNT(*) AS listings
        FROM listing l
        JOIN vehicle v ON v.id = l.vehicle_id
        WHERE v.fuel_type IS NOT NULL
        GROUP BY v.fuel_type
        ORDER BY listings DESC;
    """)

    if not df_fuel.empty:
        fig, ax = plt.subplots(figsize=(8, 8))
        # Don't label tiny slices to avoid clutter
        labels = [
            f"{r.fuel_type} ({r.listings})" if r.listings > len(df_fuel)*0.02 else ""
            for r in df_fuel.itertuples()
        ]
        ax.pie(df_fuel["listings"], labels=labels, autopct=lambda p: f'{p:.1f}%' if p > 2 else '', startangle=140)
        ax.set_title("Market Share by Fuel Type")
        fig.tight_layout()
        fig.savefig(out_dir / "market_share_by_fuel.png", dpi=150)
        plt.close(fig)

    # -----------------------------------------------------------------------
    # Analysis 8: New vs Used Price Comparison
    # -----------------------------------------------------------------------
    df_new = query_to_csv("new_vs_used_price", """
        SELECT
            CASE WHEN v.is_new_car THEN 'New' ELSE 'Used' END as condition,
            COUNT(*) as count,
            ROUND(AVG(ph.price)::numeric, 0) as avg_price
        FROM price_history ph
        JOIN listing l ON l.id = ph.listing_id
        JOIN vehicle v ON v.id = l.vehicle_id
        WHERE ph.price IS NOT NULL
        GROUP BY v.is_new_car;
    """)

    if not df_new.empty:
        fig, ax = plt.subplots(figsize=(6, 6))
        bars = ax.bar(df_new["condition"], df_new["avg_price"], color=["#ca8a04", "#2563eb"])
        ax.set_ylabel("Average Price (£)")
        ax.set_title("New vs. Used Price Comparison")
        ax.bar_label(bars, fmt="£%.0f")
        fig.tight_layout()
        fig.savefig(out_dir / "new_vs_used_price.png", dpi=150)
        plt.close(fig)

    # -----------------------------------------------------------------------
    # Analysis 9: Taxi Usage Check
    # -----------------------------------------------------------------------
    query_to_csv("taxi_check", """
        SELECT make, model, count(*) as taxi_count
        FROM vehicle
        WHERE is_taxi = true
        GROUP BY make, model
        ORDER BY taxi_count DESC;
    """)

    # -----------------------------------------------------------------------
    # Analysis 4: Average price by body type
    # -----------------------------------------------------------------------
    # Simple question: "Which body types are most expensive on average?"
    df_body = query_to_csv("avg_price_by_body_type", """
        SELECT v.vehicle_type AS body_type,
               COUNT(*)                          AS listings,
               ROUND(AVG(ph.price)::numeric, 0)  AS avg_price
        FROM price_history ph
        JOIN listing l  ON l.id = ph.listing_id
        JOIN vehicle  v ON v.id = l.vehicle_id
        WHERE ph.price IS NOT NULL
          AND v.vehicle_type IS NOT NULL
        GROUP BY v.vehicle_type
        ORDER BY avg_price DESC
        LIMIT 10;
    """)

    if not df_body.empty:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.barh(df_body["body_type"], df_body["avg_price"], color="#6366f1")
        ax.set_xlabel("Average Price (£)")
        ax.set_title("Average Price by Body Type")
        ax.invert_yaxis()
        fig.tight_layout()
        fig.savefig(out_dir / "avg_price_by_body_type.png", dpi=150)
        plt.close(fig)

    # -----------------------------------------------------------------------
    # Analysis 5: Average price by location (top 15 cities)
    # -----------------------------------------------------------------------
    df_loc = query_to_csv("avg_price_by_location", """
        SELECT l.location,
               COUNT(*) AS listings,
               ROUND(AVG(ph.price)::numeric, 0) AS avg_price
        FROM price_history ph
        JOIN listing l ON l.id = ph.listing_id
        WHERE ph.price IS NOT NULL AND l.location IS NOT NULL
        GROUP BY l.location
        HAVING COUNT(*) >= 3
        ORDER BY avg_price DESC
        LIMIT 15;
    """)

    if not df_loc.empty:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.barh(df_loc["location"], df_loc["avg_price"], color="#d97706")
        ax.set_xlabel("Average Price (£)")
        ax.set_title("Average Price by Location (Top 15)")
        ax.invert_yaxis()
        fig.tight_layout()
        fig.savefig(out_dir / "avg_price_by_location.png", dpi=150)
        plt.close(fig)

    # -----------------------------------------------------------------------
    # Analysis 6: Supply by registration year
    # -----------------------------------------------------------------------
    df_year = query_to_csv("supply_by_year", """
        SELECT v.first_registration_year AS year, COUNT(*) AS listings
        FROM listing l
        JOIN vehicle v ON v.id = l.vehicle_id
        WHERE v.first_registration_year IS NOT NULL
          AND v.first_registration_year >= 2010
        GROUP BY v.first_registration_year
        ORDER BY v.first_registration_year;
    """)

    if not df_year.empty:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.bar(df_year["year"].astype(str), df_year["listings"], color="#7c3aed")
        ax.set_xlabel("Registration Year")
        ax.set_ylabel("Number of Listings")
        ax.set_title("Supply by Registration Year")
        plt.xticks(rotation=45, ha="right")
        fig.tight_layout()
        fig.savefig(out_dir / "supply_by_year.png", dpi=150)
        plt.close(fig)

    # -----------------------------------------------------------------------
    # Analysis 7: Average engine power by make
    # -----------------------------------------------------------------------
    # Simple question: "Which car brands have the most powerful engines?"
    df_hp = query_to_csv("avg_power_by_make", """
        SELECT v.make,
               COUNT(*)                          AS listings,
               ROUND(AVG(v.power_bhp)::numeric, 0) AS avg_bhp
        FROM vehicle v
        JOIN listing l ON l.vehicle_id = v.id
        WHERE v.power_bhp IS NOT NULL
          AND v.make IS NOT NULL
        GROUP BY v.make
        HAVING COUNT(*) >= 3
        ORDER BY avg_bhp DESC
        LIMIT 15;
    """)

    if not df_hp.empty:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.barh(df_hp["make"], df_hp["avg_bhp"], color="#ef4444")
        ax.set_xlabel("Average Engine Power (BHP)")
        ax.set_title("Average Engine Power by Make (Top 15)")
        ax.invert_yaxis()
        fig.tight_layout()
        fig.savefig(out_dir / "avg_power_by_make.png", dpi=150)
        plt.close(fig)

    logger.info("Analysis complete — output: %s", out_dir)


if __name__ == "__main__":
    app()
