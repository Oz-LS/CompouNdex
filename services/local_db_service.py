"""
Tier-0 data source: the user's own pre-populated reagent database.

Loaded once at import time from reagent_starting_database.py.
Provides O(1) lookup by CAS and EC (via pre-built dicts) and
linear word-split search by name and formula.

All functions return raw compound dicts (same shape as the entries
in reagent_starting_database.COMPOUNDS) — callers are responsible
for converting them to Reagent objects via _build_from_local_db().
"""
from __future__ import annotations

try:
    from reagent_starting_database import BY_CAS, BY_EC, COMPOUNDS
    _available = True
except ImportError:
    BY_CAS: dict = {}
    BY_EC: dict = {}
    COMPOUNDS: list = []
    _available = False


def is_available() -> bool:
    """Return True when the starting database was successfully loaded."""
    return _available


def find_by_cas(cas: str) -> dict | None:
    """Return the compound dict for the given CAS number, or None."""
    return BY_CAS.get(cas.strip())


def find_by_ec(ec: str) -> dict | None:
    """Return the compound dict for the given EC number, or None."""
    return BY_EC.get(ec.strip())


def find_by_name(name: str) -> list[dict]:
    """
    Word-split search across name_traditional, name_stock, and name_iupac.
    All words in *name* must appear somewhere in the combined name fields
    (case-insensitive).  Returns up to 10 matching compound dicts.

    Examples
    --------
    "copper sulfate"  → matches entries whose names contain both words
    "vanadium oxide"  → matches "vanadium(IV) oxide", "vanadium(V) oxide", …
    """
    words = [w.lower() for w in name.strip().split() if len(w) >= 2]
    if not words:
        return []
    results = []
    for c in COMPOUNDS:
        combined = " ".join(filter(None, [
            c.get("name_traditional") or "",
            c.get("name_stock") or "",
            c.get("name_iupac") or "",
        ])).lower()
        if all(w in combined for w in words):
            results.append(c)
        if len(results) >= 10:
            break
    return results


def find_by_formula(formula: str) -> list[dict]:
    """
    Exact case-insensitive match against formula_hill.
    Returns up to 10 matching compound dicts.
    """
    f = formula.strip().lower()
    return [c for c in COMPOUNDS if (c.get("formula_hill") or "").lower() == f][:10]
