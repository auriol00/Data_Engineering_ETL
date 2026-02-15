"""Shared utility functions for the pipeline modules."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("heycar.pipeline")


def safe_run_id() -> str:
    """Build a folder name from the current local time (Europe/Berlin).

    Using local time instead of Airflow's UTC-based run ID so folder
    names match the wall-clock time the user sees.
    Example: 'run_2026-02-12_01-09'
    """
    from zoneinfo import ZoneInfo  # stdlib since Python 3.9

    now = datetime.now(ZoneInfo("Europe/Berlin"))
    return now.strftime("run_%Y-%m-%d_%H-%M")


def staging_dir() -> Path:
    """Return path to staging directory for current run, creating it if needed."""
    d = Path("data/staging") / safe_run_id()
    d.mkdir(parents=True, exist_ok=True)
    return d


def analysis_dir() -> Path:
    """Return path to analysis output directory for current run, creating it if needed."""
    d = Path("analysis/output") / safe_run_id()
    d.mkdir(parents=True, exist_ok=True)
    return d
