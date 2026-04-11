"""
Hydration service.
Maps numeric hydration degrees to IUPAC suffixes and drives the
two-step resolution strategy:
  1. Direct name search for "{base_name} {suffix}" via PubChem/ChemSpider.
  2. Fallback: query PubChem related-compound list for the anhydrous CID,
     then match by molecular formula stoichiometry.

For formula-based hydration searches (e.g. "CuSO4" + degree 5),
build_hydrated_formula() computes the Hill-notation hydrated formula
(e.g. "CuH10O9S") to enable formula endpoint searches.
"""
from __future__ import annotations
import re

HYDRATION_SUFFIXES: dict[float, str] = {
    0.25: "quarter hydrate",
    0.5:  "hemihydrate",
    1.0:  "monohydrate",
    1.5:  "sesquihydrate",
    2.0:  "dihydrate",
    2.5:  "hemipentahydrate",
    3.0:  "trihydrate",
    3.5:  "hemiheptahydrate",
    4.0:  "tetrahydrate",
    4.5:  "hemienneahydrate",
    5.0:  "pentahydrate",
    6.0:  "hexahydrate",
    7.0:  "heptahydrate",
    8.0:  "octahydrate",
    9.0:  "nonahydrate",
    10.0: "decahydrate",
}


def degree_to_suffix(degree: float) -> str | None:
    return HYDRATION_SUFFIXES.get(float(degree))


def build_hydrated_name(base_name: str, degree: float) -> str | None:
    suffix = degree_to_suffix(degree)
    return f"{base_name} {suffix}" if suffix else None


def build_hydrated_formula(base_formula: str, degree: float) -> str | None:
    """
    Compute the molecular formula of a hydrate in Hill notation.

    Examples:
      build_hydrated_formula("CuSO4", 5.0)  → "CuH10O9S"
      build_hydrated_formula("NaCl",  2.0)  → "ClH4NaO2"
      build_hydrated_formula("CaCl2", 6.0)  → "CaCl2H12O6"

    Only works for integer or half-integer degrees. Returns None if the
    base formula cannot be parsed or the degree is non-standard.
    """
    elements = _parse_formula(base_formula)
    if not elements:
        return None

    # Water: H2O — handle half-hydrates approximately
    n = degree
    h_add = int(2 * n + 0.5)  # traditional round-half-up (avoids banker's rounding)
    o_add = int(n + 0.5)

    elements["H"] = elements.get("H", 0) + h_add
    elements["O"] = elements.get("O", 0) + o_add

    return _to_hill(elements)


def _parse_formula(formula: str) -> dict[str, int] | None:
    """
    Parse a molecular formula string into {element: count}.
    Supports simple formulas like CuSO4, NaCl, Ca3(PO4)2.
    Does NOT support nested parentheses beyond one level.
    Returns None on parse failure.
    """
    # Strip dots and water suffix (e.g. "CuSO4.5H2O" → "CuSO4")
    formula = re.split(r'[·.]', formula)[0].strip()

    # Expand one level of parentheses: Ca3(PO4)2 → Ca3P2O8
    def expand_parens(f: str) -> str:
        def repl(m):
            inner = m.group(1)
            mult  = int(m.group(2)) if m.group(2) else 1
            inner_els = _parse_flat(inner)
            return "".join(
                el + (str(cnt * mult) if cnt * mult > 1 else "")
                for el, cnt in inner_els.items()
            )
        return re.sub(r'\(([^()]+)\)(\d*)', repl, f)

    formula = expand_parens(formula)
    elements = _parse_flat(formula)
    return elements if elements else None


def _parse_flat(formula: str) -> dict[str, int]:
    """Parse a flat (no parentheses) formula string."""
    elements: dict[str, int] = {}
    for m in re.finditer(r'([A-Z][a-z]?)(\d*)', formula):
        el  = m.group(1)
        cnt = int(m.group(2)) if m.group(2) else 1
        elements[el] = elements.get(el, 0) + cnt
    return elements


def _to_hill(elements: dict[str, int]) -> str:
    """
    Convert element dict to Hill notation string.
    Hill convention:
      - If C present: C first, H second, then others alphabetically.
      - If no C: all elements alphabetically (H treated like any other).
    """
    elems = dict(elements)
    result = ""
    if "C" in elems:
        for el in ("C", "H"):
            if el in elems:
                cnt = elems.pop(el)
                result += el + (str(cnt) if cnt > 1 else "")
    for el in sorted(elems):
        cnt = elems[el]
        result += el + (str(cnt) if cnt > 1 else "")
    return result


def resolve_hydrate(base_name: str, base_cid: int | None,
                    degree: float) -> dict:
    """
    Find the CID of the hydrated form of a compound.
    base_name can be a compound name or a formula (treated as synonym search).

    Resolution order:
      1. PubChem name search for "{base_name} {suffix}".
      2. PubChem related-compound CIDs with formula stoichiometry match.

    Returns {"status": "ok"|"not_found", "cid", "cas", "name", "message"}.
    """
    from services import pubchem_service

    suffix = degree_to_suffix(degree)
    hydrated_name = f"{base_name} {suffix}" if suffix else base_name

    # Step 1: direct name search (only when a known IUPAC suffix exists)
    if suffix:
        cids = pubchem_service.get_cids_by_name(hydrated_name, max_results=3)
        if cids:
            cid  = cids[0]
            cas  = _get_cas(cid)
            name = pubchem_service.get_properties(cid).get("title") or hydrated_name
            return {"status": "ok", "cid": cid, "cas": cas, "name": name, "message": ""}

    # Step 2: related-compound fallback (always attempted)
    if base_cid:
        related_cids = pubchem_service.get_related_cids(base_cid)
        if related_cids:
            batch = pubchem_service.get_properties_batch(related_cids[:20])
            for entry in batch:
                if _formula_has_n_waters(entry.get("molecular_formula", ""), degree):
                    cid  = entry["cid"]
                    cas  = _get_cas(cid)
                    name = entry.get("title") or hydrated_name
                    return {"status": "ok", "cid": cid, "cas": cas,
                            "name": name, "message": ""}

    return {
        "status":  "not_found",
        "cid":     None,
        "cas":     None,
        "name":    hydrated_name,
        "message": (
            f"No compound with stoichiometry '{hydrated_name}' was found "
            f"in the chemical databases."
        ),
    }


def _get_cas(cid: int) -> str | None:
    from services import pubchem_service
    synonyms = pubchem_service.get_synonyms(cid)
    return pubchem_service.get_cas_from_synonyms(synonyms)


def _formula_has_n_waters(formula: str, n: float) -> bool:
    if not formula:
        return False
    dot_m = re.search(r'[·.](\d*(?:\.\d+)?)H2O', formula)
    if dot_m:
        prefix = dot_m.group(1)
        count  = float(prefix) if prefix else 1.0
        return abs(count - n) < 0.01
    h_m = re.search(r'H(\d+)', formula)
    o_m = re.search(r'O(\d+)', formula)
    if h_m and o_m:
        implied = min(int(h_m.group(1)) // 2, int(o_m.group(1)))
        return abs(implied - n) < 1.5
    return False
