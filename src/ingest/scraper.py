"""Scraper for the Heycar Trader API.

Fetches used-car listings from Heycar's internal search API and returns
them as ScrapedListing objects ready for raw_data storage.

Why the Trader API?
  - Structured JSON (no HTML parsing)
  - Stable schema (doesn't break on frontend redesigns)
  - Rich data: 30+ fields per listing (spec, pricing, dealer, location)
  - Built-in pagination
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Internal Heycar API — same endpoint the website frontend calls
TRADER_BASE = "https://api.uk.prod.group-mobility-trader.com"
HEYCAR_BASE = "https://heycar.com"

# Which data fields to request from the API (controls what's in each listing)
SEARCH_FIELDS = (
    "field=stock-condition&field=price&field=monthly-price&field=make&field=model"
    "&field=fuel-type&field=body-type&field=color&field=gear-box&field=doors"
    "&field=seats&field=finance-product&field=engine-size"
    "&field=eligible-products&field=fuel-consumption"
)

# Mimic a browser request so the API doesn't reject us
HEADERS = {
    "accept": "application/json,text/plain,*/*",
    "user-agent": "Mozilla/5.0",
    "origin": "https://heycar.com",
    "referer": "https://heycar.com/uk/autos?stock-condition=used",
}


class ScrapedListing(BaseModel):
    """One listing as returned by the scraper — stored as-is into raw_data."""
    source: str = "heycar"
    source_ad_id: str
    canonical_url: str
    scraped_at: datetime
    raw_payload: dict[str, Any] = Field(default_factory=dict)


def _search_url(page: int, page_size: int = 20) -> str:
    return (
        f"{TRADER_BASE}/i15/search?{SEARCH_FIELDS}"
        f"&page={page}&size={page_size}"
        f"&stock-condition=used&sort=i15_uk_elo"
    )


def _fetch_page(page: int, page_size: int = 20) -> list[dict]:
    """Fetch one page of listings from the Trader API. Returns content items."""
    url = _search_url(page, page_size)
    try:
        # timeout=25s — generous limit to avoid hanging on slow responses
        resp = requests.get(url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.warning("Trader API request failed for page %d", page, exc_info=True)
        return []

    content = data.get("content", [])
    if not isinstance(content, list):
        return []

    logger.info("Page %d: fetched %d items", page, len(content))
    return content


def _to_listing(item: dict, scraped_at: datetime) -> ScrapedListing | None:
    """Convert one API content item to a ScrapedListing, or None if unusable."""
    # The Trader API provides a numeric ID and a slug-based heycarId
    ad_id = item.get("id")
    heycar_id = item.get("heycarId")
    if not ad_id:
        return None

    # Build canonical URL from heycarId (slug), fall back to numeric id
    slug = heycar_id or str(ad_id)
    url = f"{HEYCAR_BASE}/uk/autos/{slug}"

    return ScrapedListing(
        source="heycar",
        source_ad_id=str(ad_id),
        canonical_url=url,
        scraped_at=scraped_at,
        raw_payload=item,
    )


def scrape_batch(pages: int = 1, page_size: int = 20) -> list[ScrapedListing]:
    """Scrape multiple pages and return deduplicated listings.

    pages    — how many pages to fetch (each page = 20 listings)
    page_size — max 20 per the API (don't increase)
    """
    results: list[ScrapedListing] = []
    seen_ids: set[str] = set()
    scraped_at = datetime.now(timezone.utc)

    for page in range(pages):
        items = _fetch_page(page, page_size)
        for item in items:
            listing = _to_listing(item, scraped_at)
            if listing is None:
                continue
            if listing.source_ad_id in seen_ids:
                continue
            seen_ids.add(listing.source_ad_id)
            results.append(listing)

    logger.info("Scrape complete: %d unique listings from %d pages", len(results), pages)
    return results
