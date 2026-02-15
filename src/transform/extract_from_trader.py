"""Extract and normalize fields from a Trader API listing payload.

This is the core transform logic — it reads the raw JSON stored in raw_data
and returns a flat dict of cleaned, normalized fields ready for staging.

The Trader API nests data in several sub-objects:
  item["pricing"]  → price, currency
  item["details"]  → year, mileage, previousOwners
  item["spec"]     → bodyType, fuelType, gearbox, color, engineSize, bhp, doors, seats, emissionClass, ulez
  item["dealer"]   → name, city, county, postCode
  item["make"]     → {"id": "bmw", "label": "BMW"}
  item["model"]    → {"id": "3-series", "label": "3 Series"}
"""
from __future__ import annotations

from typing import Any

from src.transform.normalize import (
    normalize_category,
    normalize_year,
    parse_int,
    parse_price,
    parse_mileage,
    parse_float,
)


def _label(obj: Any) -> str | None:
    """Extract a human-readable label from a string or {label: ...} object."""
    if isinstance(obj, str) and obj.strip():
        return obj.strip()
    if isinstance(obj, dict):
        for key in ("label", "name", "displayName", "display"):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def _dealer_location(raw: dict) -> str | None:
    """Build full location string from dealer info: 'City, County, Postcode'."""
    dealer = raw.get("dealer")
    if not isinstance(dealer, dict):
        return None

    parts: list[str] = []
    for key in ("city", "county"):
        val = dealer.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())

    postcode = dealer.get("postCode") or dealer.get("postcode")
    if isinstance(postcode, str) and postcode.strip():
        parts.append(postcode.strip())

    return ", ".join(parts) if parts else None


def extract_ad_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract canonical fields from a Trader API content item.

    Returns a flat dict with only non-None values. Missing or unparseable
    fields are silently omitted — the load step handles NULLs gracefully.
    """
    out: dict[str, Any] = {}

    # --- Identity ---
    ad_id = raw.get("id")
    if ad_id is not None:
        out["id"] = str(ad_id)

    # --- Make / Model ---
    make = _label(raw.get("make"))
    model = _label(raw.get("model"))
    if make:
        out["make"] = make
    if model:
        out["model"] = model

    # --- Pricing (nested under "pricing") ---
    pricing = raw.get("pricing", {})
    if isinstance(pricing, dict):
        out["price"] = parse_price(pricing.get("price"))
        currency = pricing.get("currency")
        if isinstance(currency, str) and currency.strip():
            out["currency"] = currency.strip().upper()

    # --- Details (nested under "details") ---
    details = raw.get("details", {})
    if isinstance(details, dict):
        out["mileage"] = parse_mileage(details.get("mileage"))
        out["year"] = normalize_year(details.get("year"))
        out["previous_owners"] = parse_int(details.get("previousOwners"))

    # --- Spec (nested under "spec") ---
    spec = raw.get("spec", {})
    if isinstance(spec, dict):
        out["body_type"] = normalize_category(spec.get("bodyType"))
        out["fuel_type"] = normalize_category(spec.get("fuelType"))
        out["transmission"] = normalize_category(spec.get("gearbox"))
        out["color"] = normalize_category(spec.get("color"))

        # EU emission standard (euro4, euro5, euro6…) — indicates how clean the engine is
        out["emission_class"] = normalize_category(spec.get("emissionClass"))

        # ULEZ = Ultra Low Emission Zone (London); True = no extra daily charge
        out["ulez"] = spec.get("ulez") if isinstance(spec.get("ulez"), bool) else None

        # Engine displacement in litres (e.g. 2.0 = 2-litre engine)
        out["engine_size_l"] = parse_float(spec.get("engineSize"))

        # BHP = Brake Horsepower — standard measure of engine power
        out["power_bhp"] = parse_int(spec.get("bhp"))

        out["doors"] = parse_int(spec.get("doors"))
        out["seats"] = parse_int(spec.get("seats"))

        # Backfill year from spec if not in details
        if out.get("year") is None:
            out["year"] = normalize_year(spec.get("firstRegistrationDate"))

    # --- Location ---
    out["location"] = _dealer_location(raw)

    # --- Dealer name ---
    dealer = raw.get("dealer", {})
    if isinstance(dealer, dict):
        name = dealer.get("name") or dealer.get("displayName")
        if isinstance(name, str) and name.strip():
            out["dealer_name"] = name.strip()

    # --- Flags (top-level booleans in Trader API) ---
    if isinstance(raw.get("isNewCar"), bool):
        out["is_new_car"] = raw["isNewCar"]
    if isinstance(raw.get("isTaxi"), bool):
        out["is_taxi"] = raw["isTaxi"]

    # Remove None values — keep the output clean
    return {k: v for k, v in out.items() if v is not None}
