"""
Molecular formula notation converter.

Hill notation (returned by PubChem and ChemSpider):
  • Organic  (contains C): C first, H second, then rest alphabetical.
  • Inorganic (no C):      all elements alphabetical.

IUPAC / conventional inorganic notation (IUPAC Red Book 2005, §IR-4.4):
  Elements are ordered from least electronegative (electropositive,
  written first) to most electronegative (written last).

This function is a no-op for organic formulas (C present) because
Hill IS the accepted convention for organics.

For inorganics it converts cases like:
    ClH    → HCl
    ClNa   → NaCl
    Cl3Fe  → FeCl3
    H2O4S  → H2SO4
    BrH    → HBr
    H2O    → H2O   (unchanged — already correct)
    HNaO   → NaHO  (best effort; NaOH has ambiguous H position from formula alone)
"""
from __future__ import annotations
import re

# Pauling electronegativity values — lower = more electropositive = written first.
# Source: IUPAC / WebElements.
_EN: dict[str, float] = {
    'Fr': 0.70, 'Cs': 0.79, 'Rb': 0.82, 'K':  0.82, 'Ra': 0.89,
    'Ba': 0.89, 'Sr': 0.95, 'Na': 0.93, 'Li': 0.98, 'Ca': 1.00,
    'Eu': 1.20, 'La': 1.10, 'Ce': 1.12, 'Nd': 1.14, 'Gd': 1.20,
    'Tb': 1.10, 'Dy': 1.22, 'Ho': 1.23, 'Er': 1.24, 'Tm': 1.25,
    'Lu': 1.27, 'Y':  1.22, 'Sc': 1.36, 'Mg': 1.31, 'Th': 1.30,
    'Pu': 1.28, 'U':  1.38, 'Hf': 1.30, 'Zr': 1.33, 'Ti': 1.54,
    'Nb': 1.60, 'V':  1.63, 'Mn': 1.55, 'Ta': 1.50, 'Al': 1.61,
    'Zn': 1.65, 'Cr': 1.66, 'Fe': 1.83, 'Cd': 1.69, 'In': 1.78,
    'Ga': 1.81, 'Co': 1.88, 'Ni': 1.91, 'Cu': 1.90, 'Tl': 2.04,
    'Sn': 1.96, 'Pb': 2.33, 'Mo': 2.16, 'B':  2.04, 'H':  2.20,
    'Sb': 2.05, 'As': 2.18, 'Si': 1.90, 'Ge': 2.01, 'Bi': 2.02,
    'Te': 2.10, 'P':  2.19, 'W':  2.36, 'Se': 2.55, 'C':  2.55,
    'I':  2.66, 'S':  2.58, 'Br': 2.96, 'N':  3.04, 'Cl': 3.16,
    'O':  3.44, 'F':  3.98,
}

_FORMULA_RE = re.compile(r'([A-Z][a-z]?)(\d*)')


def _parse_flat(formula: str) -> dict[str, int]:
    elements: dict[str, int] = {}
    for m in _FORMULA_RE.finditer(formula):
        el  = m.group(1)
        cnt = int(m.group(2)) if m.group(2) else 1
        elements[el] = elements.get(el, 0) + cnt
    return elements


def _to_str(elements: dict[str, int], order: list[str]) -> str:
    return ''.join(
        el + (str(elements[el]) if elements[el] > 1 else '')
        for el in order
    )


def formula_hill_to_iupac(formula: str) -> str:
    """
    Return ``formula`` converted to IUPAC electronegativity ordering.
    Returns the input unchanged if it is empty, unparseable, or organic.
    """
    if not formula:
        return formula

    # Isolate the base formula from any hydration suffix (e.g. "·5H2O")
    suffix_m = re.search(r'[·\.](\d*(?:\.\d+)?H2O.*)$', formula, re.IGNORECASE)
    base_formula = formula[:suffix_m.start()] if suffix_m else formula
    suffix       = suffix_m.group(0) if suffix_m else ''

    elements = _parse_flat(base_formula)
    if not elements:
        return formula

    # Organic — C present: Hill IS the IUPAC convention, leave untouched.
    if 'C' in elements:
        return formula

    # Inorganic — sort by EN ascending; alphabetical tiebreak for unknown elements.
    _fallback = 99.0
    order = sorted(
        elements.keys(),
        key=lambda el: (_EN.get(el, _fallback), el),
    )
    return _to_str(elements, order) + suffix
