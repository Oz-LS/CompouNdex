"""
Reagent → dict serializer.

Split out from ``reagent_service`` so the conversion logic can be imported
without pulling in the full search/fetch stack, and so it can be tested
in isolation.
"""
from __future__ import annotations
import re

from models import Reagent
from services.mw_calculator import calculate_mw
from services.name_normalizer import classic_formula_from_hill

# Maximum synonyms included in the serialized output.
MAX_SYNONYMS = 5


def clean_iupac(name: str | None) -> str | None:
    """
    Return None for PubChem multi-component IUPAC names (semicolon-delimited,
    e.g. "iron(2+);sulfate;heptahydrate").  These are internal PubChem
    representations, not human-readable names suitable for display.
    """
    if not name or ";" in name:
        return None
    return name


def filter_solubility(raw: str | None) -> str | None:
    """
    Remove non-numeric lines from a stored solubility string.
    Handles both legacy plain text ("Very soluble") and the current
    "Water: X g/L at T K\nOther solvents: Y g/L" multi-line format.
    Returns None if nothing numeric survives.
    """
    if not raw:
        return None
    from services.property_parser import parse_numerical
    good = []
    for line in raw.split("\n"):
        stripped = re.sub(r'^(?:Water|Other solvents):\s*', '', line, flags=re.I).strip()
        if stripped and parse_numerical(stripped, "solubility") is not None:
            good.append(line)
    return "\n".join(good) if good else None


def reagent_to_dict(reagent: Reagent) -> dict:
    from services.hp_service import resolve_phrases

    # Molecular weight: recalculate from Hill formula for accuracy;
    # fall back to stored value for compounds whose formula wasn't parseable.
    hill = reagent.molecular_formula_hill
    mw = calculate_mw(hill) if hill else reagent.molecular_weight
    if mw is None:
        mw = reagent.molecular_weight
    if mw is not None:
        mw = round(mw, 3)

    return {
        "id":                     reagent.id,
        "cas_number":             reagent.cas_number,
        "ec_number":              reagent.ec_number,
        "iupac_name":             reagent.iupac_name,
        "stock_name":             reagent.stock_name,
        "traditional_name":       reagent.traditional_name,
        "retained_name":          reagent.retained_name,
        "display_name":           reagent.display_name,
        "name_notations": {
            "traditional": reagent.traditional_name,
            "iupac":       clean_iupac(reagent.iupac_name),
            "stock":       reagent.stock_name,
        },
        "synonyms":               (reagent.synonyms or [])[:MAX_SYNONYMS],
        "molecular_formula":         reagent.molecular_formula,
        "molecular_formula_hill":    reagent.molecular_formula_hill,
        "molecular_formula_classic": classic_formula_from_hill(
            reagent.molecular_formula_hill,
            reagent.hydration_degree,
        ),
        "molecular_weight":       mw,
        "melting_point":          reagent.melting_point,
        "boiling_point":          reagent.boiling_point,
        "dehydration_temp":       reagent.dehydration_temp,
        "solubility":             filter_solubility(reagent.solubility),
        "appearance":             reagent.appearance,
        "h_codes":                reagent.h_codes or [],
        "p_codes":                reagent.p_codes or [],
        "h_phrases":              resolve_phrases(reagent.h_codes or [], "h"),
        "p_phrases":              resolve_phrases(reagent.p_codes or [], "p"),
        "pictogram_codes":        reagent.pictogram_codes or [],
        "signal_word":            reagent.signal_word,
        "is_hydrate":             reagent.is_hydrate,
        "hydration_degree":       reagent.hydration_degree,
        "parent_cas":             reagent.parent_cas,
        "chemspider_id":          reagent.chemspider_id,
        "pubchem_cid":            reagent.pubchem_cid,
        "sds_documents":          [s.to_dict() for s in reagent.sds_documents],
    }
