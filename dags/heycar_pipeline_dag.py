"""Airflow DAG for the Heycar data pipeline.

Schedule: every 6 hours (4× daily)
  - Used car listings change slowly — hourly is too aggressive
  - 6h gives 4 fresh snapshots/day to track price changes
  - Polite to the Trader API (no rate-limit risk)

Steps: extract → transform → load → analyze  (sequential)
"""
from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.operators.bash import BashOperator


default_args = {
    "owner": "heycar",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
    "depends_on_past": False,
}

with DAG(
    dag_id="heycar_pipeline",
    default_args=default_args,
    description="ETL pipeline: Trader API → PostgreSQL → Analysis",
    schedule_interval="0 */6 * * *",  # Every 6 hours
    start_date=pendulum.datetime(2025, 1, 1, tz="Europe/Berlin"),
    catchup=False,
    max_active_runs=1,  # Prevent overlapping runs
    tags=["heycar", "etl"],
) as dag:

    PROJECT = "/opt/airflow/project"

    # --pages 3 = fetch 3 pages × 20 listings = 60 listings per run
    extract = BashOperator(
        task_id="extract",
        bash_command=f"cd {PROJECT} && python -m src.pipeline.cli extract --pages 3",
    )

    transform = BashOperator(
        task_id="transform",
        bash_command=f"cd {PROJECT} && python -m src.pipeline.cli transform",
    )

    load = BashOperator(
        task_id="load",
        bash_command=f"cd {PROJECT} && python -m src.pipeline.cli load",
    )

    analyze = BashOperator(
        task_id="analyze",
        bash_command=f"cd {PROJECT} && python -m src.pipeline.cli analyze",
    )

    extract >> transform >> load >> analyze
