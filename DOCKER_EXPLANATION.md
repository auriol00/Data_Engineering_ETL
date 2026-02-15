# Docker Compose Explanation

This document explains every part of the `docker-compose.yml` file used in this project. The Goal is to make you a master of this configuration.

## 1. Services

The system is built from 5 services (containers) that work together:

### `postgres_heycar` (Project Database)
- **Image:** `postgres:16` (Official PostgreSQL image)
- **Purpose:** Stores the actual data scraped from Heycar (vehicles, listings, prices).
- **Port:** `5432` maps to host `5432`, so you can connect via DBeaver/TablePlus on `localhost:5432`.
- **Volumes:**
  - `pgdata_heycar:/var/lib/postgresql/data`: Persists data even if you delete the container.
  - `./sql:/docker-entrypoint-initdb.d:ro`: Runs `init_heycar.sql` automatically when the database is created for the first time.

### `postgres` (Airflow Database)
- **Image:** `postgres:16`
- **Purpose:** Stores Airflow's internal metadata (DAG runs, task logs, users).
- **Port:** `5433` maps to host `5433` (to avoid conflict with the project DB).
- **Why Separate?** Keeps infrastructure (Airflow) separate from business data (Heycar). You can blow up one without affecting the other.

### `airflow-init` (Initialization)
- **Purpose:** Runs once on startup to:
  1. Initialize the Airflow database (`airflow db migrate`).
  2. Create the admin user (`airflow users create`).
- **Lifecycle:** It runs, completes its job, and then stops (`restart: "no"`).
- **Dependencies:** Waits for both Postgres databases to be healthy before starting.

### `airflow-webserver` (UI)
- **Purpose:** The web interface you see at `http://localhost:8080`.
- **Command:** `airflow webserver`
- **Depends On:** Waits for `airflow-init` to finish successfully.

### `airflow-scheduler` (The Brain)
- **Purpose:** Checks the clock, triggers DAGs, and schedules tasks to run.
- **Command:** `airflow scheduler`
- **Depends On:** Waits for `airflow-init` to finish.

## 2. Advanced Concepts Used

### YAML Anchors (`<<: *airflow-common`)
You will see this block:
```yaml
x-airflow-common: &airflow-common
  build: ...
  environment: ...
  volumes: ...
```
And later:
```yaml
airflow-webserver:
  <<: *airflow-common
```
**Why?**
- `airflow-init`, `webserver`, and `scheduler` all need the **exact same** environment variables, volumes, and build settings.
- Instead of copying 30 lines of config 3 times (90 lines total), we define it once in `airflow-init` with `&airflow-common` and "paste" it into the other services with `<<: *airflow-common`.
- **Benefit:** If you need to add a new environment variable, you add it in ONE place, and all 3 services get it.

### Healthchecks
```yaml
healthcheck:
  test: ["CMD-SHELL", "pg_isready ..."]
  interval: 5s
  retries: 20
```
- **Purpose:** Docker checks if the database is actually ready to accept connections, not just "started".
- **Why important?** `airflow-init` waits for `condition: service_healthy` from the database. This prevents Airflow from crashing because it tried to connect before the database was ready.

## 3. Volumes & Networks

### Volumes
- `pgdata_heycar`: Persistent storage for project data.
- `pgdata_airflow`: Persistent storage for Airflow metadata.
- `airflow_logs`: Shared volume so the Scheduler, Webserver, and Workers can all see the same task logs.

### Networks
- `heycar_net`: A dedicated internal network where containers talk to each other.
- Service Discovery: The containers use names to talk. The `run_pipeline.py` script connects to host `postgres_heycar`, and Docker automatically resolves that to the correct internal IP address.

## 4. Environment Variables

We use an `.env` file to store secrets (passwords) and configuration.
- `env_file: .env`: Loads the file.
- `environment:`: Overrides specific variables or maps them to internal Docker names.

For example, `POSTGRES_DB: ${DB_NAME}` means "Take the value of DB_NAME from .env and pass it to the container as POSTGRES_DB".

---

**Summary:**
This setup is **production-grade** in structure but simplified for local use. It handles persistence, networking, initialization order, and configuration management cleanly.
