"""
Mixture service: create, serialise, and compute concentrations for lab mixtures.
"""
from __future__ import annotations

import re

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

def _parse_density(density_str: str | None) -> float | None:
    """Extract numeric density (g/mL) from strings like '1.05 g/mL', '0.789'."""
    if not density_str:
        return None
    m = re.match(r'^\s*(\d+\.?\d*(?:[eE][+-]?\d+)?)', str(density_str))
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _amount_to_mol(
    amount: float,
    unit: str,
    mw_g_per_mol: float | None,
    density_g_per_mL: float | None = None,
) -> float | None:
    """Convert an amount to moles.  Returns None when MW/density needed but missing."""
    if unit in _UNIT_TO_MOL:
        return amount * _UNIT_TO_MOL[unit]
    if unit in _UNIT_TO_G:
        if mw_g_per_mol:
            return (amount * _UNIT_TO_G[unit]) / mw_g_per_mol
        return None
    if unit in _UNIT_TO_L:
        if density_g_per_mL and mw_g_per_mol:
            vol_mL = amount * _UNIT_TO_L[unit] * 1000.0
            mass_g = vol_mL * density_g_per_mL
            return mass_g / mw_g_per_mol
        return None
    return None


def _amount_to_g(
    amount: float,
    unit: str,
    mw_g_per_mol: float | None = None,
    density_g_per_mL: float | None = None,
) -> float | None:
    """Convert an amount to grams."""
    if unit in _UNIT_TO_G:
        return amount * _UNIT_TO_G[unit]
    if unit in _UNIT_TO_MOL:
        if mw_g_per_mol:
            return amount * _UNIT_TO_MOL[unit] * mw_g_per_mol
        return None
    if unit in _UNIT_TO_L:
        if density_g_per_mL:
            vol_mL = amount * _UNIT_TO_L[unit] * 1000.0
            return vol_mL * density_g_per_mL
        return None
    return None


def _amount_to_L(
    amount: float,
    unit: str,
    density_g_per_mL: float | None = None,
    mw_g_per_mol: float | None = None,
) -> float | None:
    """Convert an amount to litres (for volume-unit compounds)."""
    if unit in _UNIT_TO_L:
        return amount * _UNIT_TO_L[unit]
    if unit in _UNIT_TO_G:
        if density_g_per_mL:
            mass_g = amount * _UNIT_TO_G[unit]
            return (mass_g / density_g_per_mL) / 1000.0
        return None
    if unit in _UNIT_TO_MOL:
        if density_g_per_mL and mw_g_per_mol:
            mass_g = amount * _UNIT_TO_MOL[unit] * mw_g_per_mol
            return (mass_g / density_g_per_mL) / 1000.0
        return None
    return None


def _compound_volume_L(solutes: list[MixtureComponent]) -> float:
    """Sum of volumes (in L) of solutes specified with volume units."""
    total = 0.0
    for c in solutes:
        if c.amount_unit in _UNIT_TO_L:
            total += c.amount * _UNIT_TO_L[c.amount_unit]
    return total


def _total_volume_L(
    solvents: list[MixtureComponent],
    solutes: list[MixtureComponent] | None = None,
) -> float | None:
    """
    Total solution volume in litres.

    If a filler solvent exists its ``amount`` already represents the target
    total volume, so we return that directly.  Otherwise we sum all solvent
    volumes plus any volume-unit compound volumes.
    """
    filler = next((s for s in solvents if s.is_filler), None)
    if filler:
        factor = _UNIT_TO_L.get(filler.amount_unit)
        if factor is None:
            return None
        val = filler.amount * factor
        return val if val > 0 else None

    comp_vol_L = _compound_volume_L(solutes) if solutes else 0.0
    total = comp_vol_L
    for s in solvents:
        factor = _UNIT_TO_L.get(s.amount_unit)
        if factor is None:
            return None
        total += s.amount * factor
    return total if total > 0 else None


def _filler_volume_L(
    solvents: list[MixtureComponent],
    solutes: list[MixtureComponent] | None = None,
) -> float | None:
    """
    Compute the filler solvent's actual volume in litres.

    Returns ``filler.amount − sum(other_solvent_volumes) − sum(volume_compound_volumes)``
    in litres, or ``None`` if there is no filler or the result would be negative.
    """
    filler = next((s for s in solvents if s.is_filler), None)
    if not filler:
        return None
    total_L = filler.amount * _UNIT_TO_L.get(filler.amount_unit, 0)
    others_L = _compound_volume_L(solutes) if solutes else 0.0
    for s in solvents:
        if s is filler:
            continue
        factor = _UNIT_TO_L.get(s.amount_unit)
        if factor is None:
            return None
        others_L += s.amount * factor
    result = total_L - others_L
    return result if result >= 0 else None


def _total_mass_g(
    all_comps: list[MixtureComponent],
    filler_vol_L: float | None,
) -> float | None:
    """
    Total solution mass in grams (needed for % m/m).
    Returns None if any component's mass cannot be determined.
    """
    total = 0.0
    for comp in all_comps:
        r = db.session.get(Reagent, comp.reagent_id)
        mw      = r.molecular_weight if r else None
        density = _parse_density(r.density if r else None)

        if comp.is_filler:
            if filler_vol_L is None or density is None:
                return None
            total += filler_vol_L * 1000.0 * density   # mL × g/mL
        else:
            mass_g = _amount_to_g(comp.amount, comp.amount_unit, mw, density)
            if mass_g is None:
                return None
            total += mass_g
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

    reagent_ids = {c.reagent_id for c in components if c.reagent_id}
    if not reagent_ids:
        return [], [], [], None
    reagents = {
        r.id: r
        for r in Reagent.query.filter(Reagent.id.in_(reagent_ids)).all()
    }

    for comp in components:
        r = reagents.get(comp.reagent_id)
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

    # Compounds accept mol/mass AND volume units
    valid_solute_units  = set(_UNIT_TO_MOL) | set(_UNIT_TO_G) | set(_UNIT_TO_L)
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

    filler_count = 0
    for i, solv in enumerate(raw_solvents):
        if not solv.get("reagent_id"):
            errors[f"solvent_{i}"] = "Solvent not resolved."
        if solv.get("amount_unit") not in valid_solvent_units:
            errors[f"solvent_{i}_unit"] = f"Invalid unit '{solv.get('amount_unit')}'."
        try:
            float(solv.get("amount", ""))
        except (TypeError, ValueError):
            errors[f"solvent_{i}_amount"] = "Amount must be a number."
        if solv.get("is_filler"):
            filler_count += 1

    if filler_count > 1:
        errors["solvents"] = "At most one solvent can be designated as filler."

    # Validate filler total >= sum of other solvent volumes + volume compounds
    if filler_count == 1 and not errors:
        filler_total_L = 0.0
        others_sum_L   = 0.0
        for solv in raw_solvents:
            try:
                amt = float(solv["amount"])
            except (TypeError, ValueError, KeyError):
                continue
            factor = _UNIT_TO_L.get(solv.get("amount_unit"), 0)
            if solv.get("is_filler"):
                filler_total_L = amt * factor
            else:
                others_sum_L += amt * factor
        # Also add volume from liquid compounds
        for comp in raw_components:
            try:
                amt = float(comp["amount"])
            except (TypeError, ValueError, KeyError):
                continue
            factor = _UNIT_TO_L.get(comp.get("amount_unit"), 0)
            others_sum_L += amt * factor
        if filler_total_L < others_sum_L:
            errors["filler_volume"] = (
                "Total solution volume must be ≥ the sum of other solvent and compound volumes."
            )

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
            is_filler       = bool(solv.get("is_filler", False)),
            component_order = order,
        ))

    db.session.commit()
    return mixture, {}


def to_dict(mixture: Mixture) -> dict:
    """Serialise a Mixture to a frontend-ready dict."""
    solutes  = [c for c in mixture.components if not c.is_solvent]
    solvents = [c for c in mixture.components if c.is_solvent]

    vol_L        = _total_volume_L(solvents, solutes)
    filler_vol_L = _filler_volume_L(solvents, solutes)
    total_mass   = _total_mass_g(mixture.components, filler_vol_L)

    # ── Solute component rows ──────────────────────────────────────────────
    component_rows = []
    for comp in solutes:
        reagent  = db.session.get(Reagent, comp.reagent_id)
        mw       = reagent.molecular_weight if reagent else None
        density  = _parse_density(reagent.density if reagent else None)

        mol      = _amount_to_mol(comp.amount, comp.amount_unit, mw, density)
        mass_g   = _amount_to_g(comp.amount, comp.amount_unit, mw, density)
        vol_c_L  = _amount_to_L(comp.amount, comp.amount_unit, density, mw)

        def _conc(numerator, denom):
            return numerator / denom if (numerator is not None and denom) else None

        conc_M      = _conc(mol,    vol_L)
        conc_mM     = conc_M * 1e3  if conc_M    is not None else None
        conc_g_L    = _conc(mass_g, vol_L)
        conc_ppm    = conc_g_L * 1e3  if conc_g_L  is not None else None  # mg/L
        conc_ppb    = conc_g_L * 1e6  if conc_g_L  is not None else None  # µg/L
        conc_pct_mv = (mass_g / (vol_L * 1000.0) * 100.0) \
                      if (mass_g is not None and vol_L) else None  # g / 100 mL
        conc_pct_vv = (vol_c_L / vol_L * 100.0) \
                      if (vol_c_L is not None and vol_L) else None
        conc_pct_mm = (mass_g / total_mass * 100.0) \
                      if (mass_g is not None and total_mass) else None

        def _r(v, n):
            return round(v, n) if v is not None else None

        component_rows.append({
            "reagent_id":            comp.reagent_id,
            "name":                  reagent.display_name if reagent else f"Reagent #{comp.reagent_id}",
            "cas_number":            reagent.cas_number if reagent else None,
            "molecular_formula":     reagent.molecular_formula if reagent else None,
            "molecular_weight":      mw,
            "density":               density,
            "amount":                comp.amount,
            "amount_unit":           comp.amount_unit,
            "amount_mol":            _r(mol,    9),
            "amount_g":              _r(mass_g, 6),
            "concentration_M":       _r(conc_M,      9),
            "concentration_mM":      _r(conc_mM,     6),
            "concentration_g_per_L": _r(conc_g_L,    6),
            "concentration_ppm":     _r(conc_ppm,    4),
            "concentration_ppb":     _r(conc_ppb,    2),
            "concentration_pct_mv":  _r(conc_pct_mv, 6),
            "concentration_pct_vv":  _r(conc_pct_vv, 6),
            "concentration_pct_mm":  _r(conc_pct_mm, 6),
        })

    # ── Solvent rows ───────────────────────────────────────────────────────
    solvent_rows = []
    for solv in solvents:
        reagent = db.session.get(Reagent, solv.reagent_id)
        if solv.is_filler:
            volume_L = filler_vol_L
        else:
            volume_L = solv.amount * _UNIT_TO_L.get(solv.amount_unit, 0)
        solvent_rows.append({
            "reagent_id":             solv.reagent_id,
            "name":                   reagent.display_name if reagent else f"Solvent #{solv.reagent_id}",
            "cas_number":             reagent.cas_number if reagent else None,
            "amount":                 solv.amount,
            "amount_unit":            solv.amount_unit,
            "volume_L":               volume_L,
            "is_filler":              solv.is_filler,
            "filler_volume_mL":       round(filler_vol_L * 1000, 2)
                                      if (solv.is_filler and filler_vol_L is not None) else None,
            "target_total_volume_mL": round(solv.amount * _UNIT_TO_L.get(solv.amount_unit, 0) * 1000, 2)
                                      if solv.is_filler else None,
        })

    # ── Disclaimer flags ───────────────────────────────────────────────────
    has_filler           = any(s.is_filler for s in solvents)
    non_filler_solvents  = [s for s in solvents if not s.is_filler]
    has_volume_compounds = any(c.amount_unit in _UNIT_TO_L for c in solutes)

    # Sources that contribute to volume (excluding filler itself)
    non_filler_liquid_sources = len(non_filler_solvents) + (
        sum(1 for c in solutes if c.amount_unit in _UNIT_TO_L)
    )

    # Without filler: disclaimer on total volume when 2+ liquids are summed
    mixing_disclaimer_on_total  = (not has_filler) and (non_filler_liquid_sources >= 2)
    # With filler: disclaimer on the filler's computed (~) volume
    mixing_disclaimer_on_filler = has_filler and (non_filler_liquid_sources >= 1)

    h_codes, p_codes, pic_codes, signal_word = _merge_ghs(mixture.components)

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
        "has_filler":                 has_filler,
        "has_volume_compounds":       has_volume_compounds,
        "multiple_solvents":          len(solvents) > 1,
        "mixing_disclaimer_on_total": mixing_disclaimer_on_total,
        "mixing_disclaimer_on_filler":mixing_disclaimer_on_filler,
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
