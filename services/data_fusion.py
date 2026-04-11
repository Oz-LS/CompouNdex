"""
Multi-source property fusion.

Takes raw property strings from ChemSpider, PubChem, and Wikidata, parses
every value with property_parser, and applies per-field merge strategies
to produce the single best representation for each field.

All sources are treated equally — no implicit priority.
"""
from __future__ import annotations
import re
from statistics import median

from services.property_parser import ParsedValue, parse_numerical, format_parsed

# Temperature fields
_TEMP_FIELDS = ("melting_point", "boiling_point", "dehydration_temp")
# Convergence tolerance for temperatures (K) — values within this range are averaged
_TEMP_TOL = 5.0
# Convergence tolerance for condition temperatures (density / solubility grouping, K)
_COND_TOL_DENSE = 2.0
_COND_TOL_SOL   = 5.0


# ── Public API ────────────────────────────────────────────────────────────────

def fuse_properties(sources: dict[str, dict]) -> dict:
    """
    Merge physicochemical properties from multiple sources.

    sources format:
      {
        "chemspider": {"melting_point": "175 °C", "solubility": "35.7 g/100 mL", ...},
        "pubchem":    {"melting_point": "175–177 °C", ...},
        "wikidata":   {"melting_point": ["448.15 K"], ...},  # lists OK
      }

    Returns a flat dict:
      melting_point, boiling_point, dehydration_temp,
      density, solubility, appearance
    """
    result = {}

    # ── Temperature fields ────────────────────────────────────────────────────
    for field in _TEMP_FIELDS:
        raws = _collect_raws(sources, field)
        result[field] = _fuse_temperature(raws, field)

    # ── Density ───────────────────────────────────────────────────────────────
    raws = _collect_raws(sources, "density")
    result["density"] = _fuse_density(raws)

    # ── Solubility (water + other solvents) ───────────────────────────────────
    water_raws = _collect_raws(sources, "solubility")
    other_raws = _collect_raws(sources, "solubility_other")
    result["solubility"] = _fuse_solubility(water_raws, other_raws)

    # ── Appearance (text) ─────────────────────────────────────────────────────
    app_raws = _collect_raws(sources, "appearance")
    result["appearance"] = _fuse_appearance(app_raws)

    return result


# ── Collectors ────────────────────────────────────────────────────────────────

def _collect_raws(sources: dict, field: str) -> list[str]:
    """
    Collect all non-None raw strings for a field from all sources.
    Wikidata returns lists; ChemSpider/PubChem return a single string or None.
    """
    raws = []
    for src_data in sources.values():
        if not src_data:
            continue
        val = src_data.get(field)
        if val is None:
            continue
        if isinstance(val, list):
            raws.extend(v for v in val if v)
        elif isinstance(val, str) and val:
            raws.append(val)
    return raws


# ── Temperature fusion ────────────────────────────────────────────────────────

def _fuse_temperature(raws: list[str], field: str) -> str | None:
    if not raws:
        return None

    parsed = [p for r in raws if (p := parse_numerical(r, "temperature")) is not None]
    if not parsed:
        return None

    # Separate decomp from normal
    decomp  = [p for p in parsed if p.is_decomp]
    normal  = [p for p in parsed if not p.is_decomp]

    # For dehydration_temp: prefer decomp values; for mp/bp: prefer normal
    if field == "dehydration_temp":
        candidates = decomp if decomp else normal
        is_decomp  = bool(decomp)
    else:
        candidates = normal if normal else decomp
        is_decomp  = not bool(normal) and bool(decomp)

    if not candidates:
        return None

    lo_vals = [p.lo for p in candidates]
    hi_vals = [p.hi for p in candidates if p.hi is not None]
    all_vals = lo_vals + hi_vals

    lo_min = min(all_vals)
    lo_max = max(all_vals)

    # Detect outliers: if any single value is >30 K from the median, discard it
    med = median(all_vals)
    filtered = [v for v in all_vals if abs(v - med) <= 30.0]
    if not filtered:
        filtered = all_vals

    lo_min = min(filtered)
    lo_max = max(filtered)
    spread = lo_max - lo_min

    prefix = "dec. " if is_decomp else ""

    # Collect qualifiers from the dominant set
    qualifiers = [p.qualifier for p in candidates if p.qualifier and p.qualifier not in ("dec.",)]
    qualifier  = qualifiers[0] if len(set(qualifiers)) == 1 else None
    qual_str   = f"{qualifier} " if qualifier else ""

    if spread <= _TEMP_TOL:
        # All values agree → report median
        val_k = median(filtered)
        return f"{prefix}{qual_str}{val_k:.1f} K"
    else:
        # Spread too wide → report range
        return f"{prefix}{qual_str}{lo_min:.1f}–{lo_max:.1f} K"


# ── Density fusion ────────────────────────────────────────────────────────────

def _fuse_density(raws: list[str]) -> str | None:
    if not raws:
        return None

    parsed = [p for r in raws if (p := parse_numerical(r, "density")) is not None]
    if not parsed:
        return None

    # Group by condition temperature (±2 K)
    groups: list[tuple[float | None, list[float]]] = []
    for p in parsed:
        placed = False
        for ct, vals in groups:
            if _same_cond(p.condition_temp, ct, _COND_TOL_DENSE):
                vals.append(p.lo)
                placed = True
                break
        if not placed:
            groups.append((p.condition_temp, [p.lo]))

    # Sort: known temperature ascending, None last
    groups.sort(key=lambda g: (g[0] is None, g[0] or 0.0))

    lines = []
    for ct, vals in groups:
        mean_val = sum(vals) / len(vals)
        if ct is not None:
            lines.append(f"{mean_val:.4f} g/mL at {ct:.0f} K")
        else:
            lines.append(f"{mean_val:.4f} g/mL")

    return "\n".join(lines) if lines else None


# ── Solubility fusion ─────────────────────────────────────────────────────────

def _fuse_solubility(water_raws: list[str], other_raws: list[str]) -> str | None:
    water_lines = _fuse_solubility_raws(water_raws, label=None)
    other_lines = _fuse_solubility_raws(other_raws, label="Other solvents")
    all_lines   = water_lines + other_lines
    return "\n".join(all_lines) if all_lines else None


def _fuse_solubility_raws(raws: list[str], label: str | None) -> list[str]:
    if not raws:
        return []

    parsed = [p for r in raws if (p := parse_numerical(r, "solubility")) is not None]
    if not parsed:
        return []

    # Group by condition temperature (±5 K)
    groups: list[tuple[float | None, list[float]]] = []
    for p in parsed:
        placed = False
        for ct, vals in groups:
            if _same_cond(p.condition_temp, ct, _COND_TOL_SOL):
                vals.append(p.lo)
                placed = True
                break
        if not placed:
            groups.append((p.condition_temp, [p.lo]))

    # Sort: 298 K (25 °C) first, then ascending, None last
    def _sort_key(g: tuple) -> tuple:
        ct = g[0]
        if ct is None:
            return (2, 0.0)
        if abs(ct - 298.15) <= 5.0:
            return (0, ct)
        return (1, ct)

    groups.sort(key=_sort_key)

    lines = []
    for ct, vals in groups:
        mean_val = sum(vals) / len(vals)
        prefix = f"{label}: " if label else ""
        if ct is not None:
            lines.append(f"{prefix}{mean_val:.1f} g/L at {ct:.0f} K")
        else:
            lines.append(f"{prefix}{mean_val:.1f} g/L")

    return lines


# ── Appearance fusion ─────────────────────────────────────────────────────────

def _fuse_appearance(raws: list[str]) -> str | None:
    if not raws:
        return None

    # Normalise for deduplication
    def _norm(s: str) -> str:
        return re.sub(r'[^\w\s]', '', s.lower()).strip()

    cleaned = [r.strip() for r in raws if r and r.strip()]
    if not cleaned:
        return None

    # Remove duplicates: if one value is a normalised substring of another, drop the shorter
    unique: list[str] = []
    norms = [_norm(s) for s in cleaned]
    for i, (s, n) in enumerate(zip(cleaned, norms)):
        dominated = any(
            j != i and n in norms[j] and len(norms[j]) > len(n)
            for j in range(len(norms))
        )
        if not dominated and s not in unique:
            unique.append(s)

    # Keep at most 2 descriptions
    kept = unique[:2]
    combined = " / ".join(kept)
    return combined[:600] if combined else None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _same_cond(a: float | None, b: float | None, tol: float) -> bool:
    """Return True if two condition temperatures are within tolerance."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol
