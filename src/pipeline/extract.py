"""Step 1: EXTRACT — fetch raw listings and store in raw_data."""
from __future__ import annotations

import typer
from dotenv import load_dotenv

from src.db.bootstrap import create_all
from src.db.session import get_session
from src.db.models import RawData
from src.ingest.scraper import scrape_batch
from src.pipeline.utils import logger


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
