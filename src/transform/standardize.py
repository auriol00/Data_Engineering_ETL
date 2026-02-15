"""Standardize make/model names to canonical forms.

Simple lookup tables that unify common variations.
"""
from __future__ import annotations

import re

# Common make variations → canonical form
_MAKE_MAP = {
    "MERCEDES": "Mercedes-Benz",
    "MERCEDES BENZ": "Mercedes-Benz",
    "MERCEDES-BENZ": "Mercedes-Benz",
    "VW": "Volkswagen",
    "VOLKSWAGEN": "Volkswagen",
    "BMW": "BMW",
    "B M W": "BMW",
}


def canonical_make(make: str | None) -> str | None:
    """Normalize make name: 'mercedes' → 'Mercedes-Benz'."""
    if not make:
        return None
    key = re.sub(r"\s+", " ", make.strip()).upper()
    return _MAKE_MAP.get(key, make.strip().title())


def canonical_model(model: str | None) -> str | None:
    """Normalize model name: collapse whitespace."""
    if not model:
        return None
    return re.sub(r"\s+", " ", model.strip())
