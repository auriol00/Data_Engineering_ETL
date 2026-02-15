"""Data normalization utilities.

Simple, focused functions that convert messy input values into clean types.
Each function handles None gracefully and returns None for unparseable input.
"""
from __future__ import annotations

import re


def parse_int(value) -> int | None:
    """Parse an integer from various input types (int, float, string)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        digits = re.findall(r"\d+", value.replace(",", ""))
        return int("".join(digits)) if digits else None
    return None


def parse_float(value) -> float | None:
    """Parse a float from various input types."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return None
    return None


def parse_price(value) -> int | None:
    """Parse a price value. Rejects obvious outliers (< £500 or > £500k)."""
    amount = parse_int(value)
    if amount is None:
        return None
    # Reject unrealistic prices (below £500 = test data, above £500k = data error)
    if amount < 500 or amount > 500_000:
        return None
    return amount


def parse_mileage(value) -> int | None:
    """Parse mileage in miles, convert to km. Rejects > 500k miles."""
    miles = parse_int(value)
    if miles is None:
        return None
    if miles < 0 or miles > 500_000:  # reject negative or impossibly high values
        return None
    return int(round(miles * 1.60934))  # API gives miles, we store km


def normalize_year(value) -> int | None:
    """Extract a 4-digit year from int, float, or date string like '2019-09-12'."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        y = int(value)
        return y if 1900 <= y <= 2100 else None
    if isinstance(value, str):
        s = value.strip()
        # YYYY or YYYY-MM-DD
        if len(s) >= 4 and s[:4].isdigit():
            y = int(s[:4])
            return y if 1900 <= y <= 2100 else None
    return None


def normalize_category(value) -> str | None:
    """Lowercase and collapse whitespace: 'Semi Auto' → 'semi auto'."""
    if not isinstance(value, str) or not value.strip():
        return None
    return re.sub(r"\s+", " ", value.strip().lower())
