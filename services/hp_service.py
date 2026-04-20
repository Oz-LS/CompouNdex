"""
Local H/P phrase resolver.
Reads from the bundled hazard_phrases module (data/hazard_phrases.py).
All lookups are in-memory; no external calls required.
"""
from __future__ import annotations

import sys
import os

# Ensure the data directory is importable
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
if _DATA_DIR not in sys.path:
    sys.path.insert(0, _DATA_DIR)

from hazard_phrases import H_EN, P_EN, translate_phrase  # type: ignore


def _sort_key(code: str) -> tuple:
    """Sort key for H/P codes: numeric part of the first component."""
    import re
    first = re.split(r'[+/]', code)[0]
    m = re.search(r'\d+', first)
    return (int(m.group()) if m else 0, code)


def resolve_phrases(codes: list[str], kind: str = "h", lang: str = "en") -> list[dict]:
    """
    Resolve a list of raw codes (e.g. ["H301", "H300+H310"]) into
    a list of dicts: {"code": ..., "text": ...}.

    Steps applied before resolving:
    1. Deduplicate: remove any standalone code that already appears as a
       component inside a combined code (e.g. drop "P302" when "P302+P352"
       is present).
    2. Sort codes in ascending numeric order.

    ``kind`` is "h" or "p" — used only when code lookup is ambiguous.
    ``lang`` must be "en" (italian is available in the dict but not used in UI).
    """
    import re

    # Collect every individual component that appears inside a combined code
    covered: set[str] = set()
    for code in codes:
        parts = re.split(r'[+/]', code)
        if len(parts) > 1:
            covered.update(p.strip() for p in parts)

    # Keep a code only if it is NOT a lone component already covered above
    deduped = [c for c in codes if c.strip() not in covered]

    # Sort ascending by the numeric value of the first component
    deduped.sort(key=_sort_key)

    results = []
    for code in deduped:
        resolved = translate_phrase(code, lang)
        results.append(resolved)
    return results


def get_h_text(code: str) -> str | None:
    """Look up a single H code. Returns None if not found."""
    return H_EN.get(code)


def get_p_text(code: str) -> str | None:
    """Look up a single P code. Returns None if not found."""
    return P_EN.get(code)
