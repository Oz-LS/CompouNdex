"""
Mixture service: create, serialise, and compute concentrations for lab mixtures.
"""
from __future__ import annotations

from extensions import db
from models import Reagent
from models.mixture import Mixture, MixtureComponent
from services.hp_service import resolve_phrases

# ── Unit conversion factors ────────────────────────────────────────────────────

_UNIT_TO_MOL: dict[str, float] = {
    "mol":  1.0,
    "mmol": 1e-3,
    "µmol": 1e-6,
}
_UNIT_TO_G: dict[str, float] = {
    "g":  1.0,
    "mg": 1e-3,
    "µg": 1e-6,
}
_UNIT_TO_L: dict[str, float] = {
    "L":  1.0,
    "mL": 1e-3,
    "µL": 1e-6,
}


# ── Private helpers ────────────────────────────────────────────────────────────

def _amount_to_mol(
    amount: float,
    unit: str,
    mw_g_per_mol: float | None,
) -> float | None:
    """Convert an amount to moles.  Returns None when MW is needed but missing."""
    if unit in _UNIT_TO_MOL:
        return amount * _UNIT_TO_MOL[unit]
    if unit in _UNIT_TO_G:
        if mw_g_per_mol:
            return (amount * _UNIT_TO_G[unit]) / mw_g_per_mol
        return None  # mass unit but no MW available
    return None  # volume unit — not applicable for solutes


def _total_volume_L(solvents: list[MixtureComponent]) -> float | None:
    """Sum all solvent volumes in litres.  Returns None if any unit is unrecognised."""
    total = 0.0
    for s in solvents:
        factor = _UNIT_TO_L.get(s.amount_unit)
        if factor is None:
            return None
        total += s.amount * factor
    return total if total > 0 else None


def _merge_ghs(
    components: list[MixtureComponent],
) -> tuple[list[str], list[str], list[str], str | None]:
    """
    Return (h_codes, p_codes, pictogram_codes, signal_word) as the union of
    all constituent reagents' GHS data.
    """
    h: set[str] = set()
    p: set[str] = set()
    pics: set[str] = set()
    sig: str | None = None

    for comp in components:
        r = db.session.get(Reagent, comp.reagent_id)
        if not r:
            continue
        h.update(r.h_codes or [])
        p.update(r.p_codes or [])
        pics.update(r.pictogram_codes or [])
        if r.signal_word == "Danger":
            sig = "Danger"
        elif r.signal_word == "Warning" and sig != "Danger":
            sig = "Warning"

    return sorted(h), sorted(p), sorted(pics), sig


# ── Public API ─────────────────────────────────────────────────────────────────

def create(data: dict) -> tuple[Mixture | None, dict]:
    """
    Create and persist a Mixture from the request payload.

    Returns (mixture, errors).  errors is empty on success.
    """
    errors: dict[str, str] = {}

    name = (data.get("name") or "").strip()
    if not name:
        errors["name"] = "Mixture name is required."

    raw_components: list[dict] = data.get("components") or []
    raw_solvents:   list[dict] = data.get("solvents")   or []

    if not raw_components:
        errors["components"] = "At least one compound is required."
    if not raw_solvents:
        errors["solvents"] = "At least one solvent is required."

    # Validate each component / solvent has a valid reagent_id and unit
    valid_solute_units  = set(_UNIT_TO_MOL) | set(_UNIT_TO_G)
    valid_solvent_units = set(_UNIT_TO_L)

    for i, comp in enumerate(raw_components):
        if not comp.get("reagent_id"):
            errors[f"component_{i}"] = "Compound not resolved."
        if comp.get("amount_unit") not in valid_solute_units:
            errors[f"component_{i}_unit"] = f"Invalid unit '{comp.get('amount_unit')}'."
        try:
            float(comp.get("amount", ""))
        except (TypeError, ValueError):
            errors[f"component_{i}_amount"] = "Amount must be a number."

    for i, solv in enumerate(raw_solvents):
        if not solv.get("reagent_id"):
            errors[f"solvent_{i}"] = "Solvent not resolved."
        if solv.get("amount_unit") not in valid_solvent_units:
            errors[f"solvent_{i}_unit"] = f"Invalid unit '{solv.get('amount_unit')}'."
        try:
            float(solv.get("amount", ""))
        except (TypeError, ValueError):
            errors[f"solvent_{i}_amount"] = "Amount must be a number."

    if errors:
        return None, errors

    mixture = Mixture(
        name        = name,
        description = (data.get("description") or "").strip() or None,
        author      = (data.get("author") or "").strip() or None,
        notes       = (data.get("notes") or "").strip() or None,
    )
    db.session.add(mixture)
    db.session.flush()  # get mixture.id before adding components

    for order, comp in enumerate(raw_components):
        db.session.add(MixtureComponent(
            mixture_id      = mixture.id,
            reagent_id      = int(comp["reagent_id"]),
            amount          = float(comp["amount"]),
            amount_unit     = comp["amount_unit"],
            is_solvent      = False,
            component_order = order,
        ))

    for order, solv in enumerate(raw_solvents):
        db.session.add(MixtureComponent(
            mixture_id      = mixture.id,
            reagent_id      = int(solv["reagent_id"]),
            amount          = float(solv["amount"]),
            amount_unit     = solv["amount_unit"],
            is_solvent      = True,
            component_order = order,
        ))

    db.session.commit()
    return mixture, {}


def to_dict(mixture: Mixture) -> dict:
    """Serialise a Mixture to a frontend-ready dict."""
    solutes  = [c for c in mixture.components if not c.is_solvent]
    solvents = [c for c in mixture.components if c.is_solvent]

    vol_L = _total_volume_L(solvents)

    # Solute component rows
    component_rows = []
    for comp in solutes:
        reagent = db.session.get(Reagent, comp.reagent_id)
        mw = reagent.molecular_weight if reagent else None
        mol = _amount_to_mol(comp.amount, comp.amount_unit, mw)
        conc_mM = (mol / vol_L * 1000.0) if (mol is not None and vol_L) else None
        component_rows.append({
            "reagent_id":       comp.reagent_id,
            "name":             reagent.display_name if reagent else f"Reagent #{comp.reagent_id}",
            "cas_number":       reagent.cas_number if reagent else None,
            "molecular_formula": reagent.molecular_formula if reagent else None,
            "molecular_weight": mw,
            "amount":           comp.amount,
            "amount_unit":      comp.amount_unit,
            "amount_mol":       round(mol, 9) if mol is not None else None,
            "concentration_mM": round(conc_mM, 6) if conc_mM is not None else None,
        })

    # Solvent rows
    solvent_rows = []
    for solv in solvents:
        reagent = db.session.get(Reagent, solv.reagent_id)
        volume_L = solv.amount * _UNIT_TO_L.get(solv.amount_unit, 0)
        solvent_rows.append({
            "reagent_id":  solv.reagent_id,
            "name":        reagent.display_name if reagent else f"Solvent #{solv.reagent_id}",
            "cas_number":  reagent.cas_number if reagent else None,
            "amount":      solv.amount,
            "amount_unit": solv.amount_unit,
            "volume_L":    volume_L,
        })

    h_codes, p_codes, pic_codes, signal_word = _merge_ghs(mixture.components)

    # Inventory items linked to this mixture
    inv_items = [item.to_dict() for item in mixture.inventory_items]

    return {
        "id":              mixture.id,
        "is_mixture":      True,
        "display_name":    mixture.display_name,
        "name":            mixture.name,
        "description":     mixture.description,
        "author":          mixture.author,
        "notes":           mixture.notes,
        "created_at":      mixture.created_at.isoformat(),
        "total_volume_L":  round(vol_L, 9) if vol_L is not None else None,
        "components":      component_rows,
        "solvents":        solvent_rows,
        "h_codes":         h_codes,
        "p_codes":         p_codes,
        "pictogram_codes": pic_codes,
        "signal_word":     signal_word,
        "h_phrases":       resolve_phrases(h_codes, "h"),
        "p_phrases":       resolve_phrases(p_codes, "p"),
        "inventory_items": inv_items,
    }
