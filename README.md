# Heycar Data Engineering Pipeline

> End-to-end ETL pipeline that scrapes used-car listings from the Heycar Trader API,
> cleans and stores them in a PostgreSQL data warehouse, and generates analysis reports.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Pipeline Steps](#pipeline-steps)
3. [Docker Infrastructure](#docker-infrastructure)
4. [Database Schema](#database-schema)
5. [Analysis Outputs](#analysis-outputs)
6. [Getting Started](#getting-started)
7. [Project Structure](#project-structure)

---

## Architecture

```
Heycar Trader API
       │
       ▼
 ┌─ Extract ──────────┐
 │  raw_data (JSONB)   │
 └─────────┬───────────┘
           ▼
 ┌─ Transform ────────┐
 │  data/staging/      │
 │  (cleaned JSONL)    │
 └─────────┬───────────┘
           ▼
 ┌─ Load ─────────────┐
 │  PostgreSQL         │
 │  vehicle · listing  │
 │  price_history      │
 └─────────┬───────────┘
           ▼
 ┌─ Analyze ──────────┐
 │  analysis/output/   │
 │  (CSV + PNG charts) │
 └─────────────────────┘
```

---

## Pipeline Steps

| Step | What happens | Key file |
|------|-------------|----------|
| **1. Extract** | Fetch listings from the Trader API, store full JSON in `raw_data` | `src/ingest/scraper.py` |
| **2. Transform** | Validate, deduplicate, normalize fields, write cleaned JSONL | `src/transform/extract_from_trader.py` |
| **3. Load** | Upsert into `vehicle`, `listing`, `price_history` tables | `src/pipeline/run_pipeline.py` |
| **4. Analyze** | Generate 7 CSV tables + PNG charts | `src/pipeline/run_pipeline.py` |

### Data Cleaning (Transform step)

- **Deduplication** — tracks seen ad IDs, skips duplicates within each batch
- **Validation** — rejects records missing critical fields (`id`, `price`)
- **Outlier filtering** — prices outside £500–£500k and mileage over 500k miles are rejected
- **Standardization** — make/model names normalized (e.g. "VW" → "Volkswagen")

### Why the Trader API?

The pipeline uses Heycar's internal Trader API (`api.uk.prod.group-mobility-trader.com`)
instead of scraping HTML. This is the same JSON API that heycar.com's frontend uses.

| Trader API | HTML Scraping |
|---|---|
| Structured JSON — 30+ fields | Fragile XPath/CSS selectors |
| Stable schema | Breaks on redesigns |
| One request = 20 listings | One request = 1 listing |
| VIN, finance, dealer info included | Often not visible in HTML |

---

## Docker Infrastructure

The project runs entirely in Docker. Four containers work together:

### Containers

| Container | Image | Purpose |
|---|---|---|
| `fix-perms` | `alpine` | **Init Helper** — Ensures data directories exist and are writable by Airflow |
| `heycar_postgres` | `postgres:16` | **Project database** — stores all scraped data (raw_data, vehicle, listing, price_history) |
| `airflow_postgres` | `postgres:16` | **Airflow metadata database** — stores DAG run history, task states, logs, and scheduler bookkeeping |
| `airflow-webserver` | Custom (Dockerfile.airflow) | **Airflow UI** — web interface to monitor and trigger pipeline runs (port 8080) |
| `airflow-scheduler` | Custom (Dockerfile.airflow) | **Airflow scheduler** — executes the DAG on the 6-hour cron schedule |

### Why two separate Postgres databases?

We use **two separate Postgres instances** to keep concerns cleanly separated:

- **`heycar_postgres`** — holds our actual project data (car listings, prices, vehicles). This is the data warehouse that we query for analysis.
- **`airflow_postgres`** — holds Airflow's internal metadata (which DAG runs happened, task logs, scheduler state). This is purely infrastructure — Airflow needs its own database to function.

Keeping them separate means:
- A problem in one database doesn't affect the other
- We can reset Airflow without losing scraped car data (and vice versa)
- Each database can be backed up and scaled independently

### Docker Volumes

| Volume | Mounted to | Purpose |
|---|---|---|
| `pgdata_heycar` | `heycar_postgres` | Persists car listing data across container restarts |
| `pgdata_airflow` | `airflow_postgres` | Persists Airflow metadata across container restarts |
| `airflow_logs` | Airflow containers | Stores task execution logs |

### Docker Network

All containers communicate over a shared network called `heycar_net`.
This allows containers to find each other by name (e.g. the pipeline connects
to `postgres_heycar` by hostname, not by IP address).

### Airflow Scheduling

- **Interval:** Every 6 hours (`0 */6 * * *`)
- **Why:** Used car listings change slowly — 4 snapshots/day is enough to catch price drops and new inventory, while being polite to the API
- **Safety:** `max_active_runs=1` prevents overlapping pipeline runs
- **Retries:** 2 retries with 5-minute delay

---

## Database Schema

4 tables in a normalized relational design:

| Table | Purpose | Key columns |
|---|---|---|
| `raw_data` | Immutable audit log | `raw_content` (JSONB), `scraped_at`, `processed_at` |
| `vehicle` | Canonical car attributes | `make`, `model`, `year`, `mileage_km`, `fuel_type`, `power_bhp`, `engine_size_l`, `color` |
| `listing` | Marketplace ad | `original_ad_id`, `source_site`, `location`, `is_active` |
| `price_history` | Price time-series | `price`, `price_currency`, `recorded_at` |

---

## Analysis Outputs

The pipeline generates 7 analyses (CSV + PNG charts):

1. **Average price by make** (top 15) — horizontal bar chart
2. **Price vs mileage** — scatter plot showing depreciation
3. **Market share by fuel type** — pie chart (petrol vs diesel vs BEV)
4. **Average price by body type** — horizontal bar chart
5. **Average price by location** — top 15 cities bar chart
6. **Supply by registration year** — bar chart of inventory age
7. **Average engine power by make** — which brands have the most powerful engines

---

## Getting Started

### Prerequisites

Make sure these are installed on your machine:

- [Git](https://git-scm.com/downloads)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Docker Compose)

### Step 1: Clone the repository

```bash
git clone https://github.com/auriol00/-Data-Engineering-Pipeline.git
cd -Data-Engineering-Pipeline
```

### Step 2: Create the environment file

```bash
cp .env.example .env
```

The defaults work out of the box for local development.

> **Note:** On the first run, a helper container (`airflow_fix_perms`) will automatically
> create the necessary data directories (`data/raw`, `analysis/output`, etc.) and set
> the correct permissions so Airflow can write to them.

### Step 3: Build and start all services

```bash
docker compose up -d --build
```

Wait ~30 seconds for all services to become healthy.

### Step 4: Open the Airflow UI

Go to [http://localhost:8080](http://localhost:8080) and log in:

- **Username:** `admin`
- **Password:** `admin`

You should see the `heycar_pipeline` DAG. It runs automatically every 6 hours,
or you can trigger it manually by clicking the ▶ play button.

### Step 5 (optional): Run steps manually

```bash
# Run inside the container (Recommended)
docker compose exec airflow-webserver python -m src.pipeline.cli extract --pages 2
docker compose exec airflow-webserver python -m src.pipeline.cli transform
docker compose exec airflow-webserver python -m src.pipeline.cli load
docker compose exec airflow-webserver python -m src.pipeline.cli analyze

# OR run locally on host (requires DB_HOST override)
# DB_HOST=localhost python3 -m src.pipeline.cli extract --pages 2
```

### Step 6: View the results

- **CSV files + charts:** `analysis/output/<run_folder>/`
- **Database:** connect to `localhost:5432` with the credentials from `.env`

### Stopping the pipeline

```bash
docker compose down       # stop containers (keep data)
docker compose down -v    # stop containers AND delete all data
```

---

## Project Structure

```
├── dags/
│   └── heycar_pipeline_dag.py     # Airflow DAG definition
├── src/
│   ├── db/
│   │   ├── models.py              # SQLAlchemy ORM models
│   │   ├── session.py             # Lazy engine + session factory
│   │   └── bootstrap.py           # create_all() + pgcrypto
│   ├── ingest/
│   │   └── scraper.py             # Trader API client
│   ├── transform/
│   │   ├── extract_from_trader.py # Field extraction + normalization
│   │   ├── normalize.py           # Type parsing + validation
│   │   └── standardize.py         # Make/model canonicalization
│   └── pipeline/
│       └── run_pipeline.py        # CLI: extract/transform/load/analyze
├── sql/
│   └── init_heycar.sql            # DDL for fresh database
├── analysis/output/               # Generated CSVs + PNGs
├── data/raw/                      # Raw JSON dumps
├── data/staging/                  # Cleaned JSONL per run
├── docker-compose.yml             # All services
├── Dockerfile.airflow             # Custom Airflow image
├── requirements.airflow.txt       # Python deps
├── .env.example                   # Environment template
└── README.md
```
