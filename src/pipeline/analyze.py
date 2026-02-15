"""Step 4: ANALYZE — generate CSV reports and PNG charts."""
from __future__ import annotations

from contextlib import closing

from dotenv import load_dotenv
import pandas as pd
import matplotlib

matplotlib.use("Agg")  # Non-interactive backend for Docker
import matplotlib.pyplot as plt

from src.db.bootstrap import create_all
from src.db.session import get_engine
from src.pipeline.utils import logger, analysis_dir


def analyze():
    """Generate CSV tables and PNG charts from the warehouse data."""
    load_dotenv()
    create_all()

    out_dir = analysis_dir()
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
