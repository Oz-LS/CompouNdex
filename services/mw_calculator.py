"""
Molecular weight calculator from Hill formula.

Uses IUPAC 2021 standard atomic weights (Table 1, abridged standard values).
Returns MW in g/mol rounded to 3 decimal places.

Formula parsing is delegated to hydration_service._parse_formula, which
handles:
  - Flat formulas: NaCl, CuSO4, H2O
  - One level of parentheses: Ca3(PO4)2, Al2(SO4)3
  - Dot-hydrate notation (stripped, since Hill formulas already include water atoms)
"""
from __future__ import annotations

# IUPAC 2021 standard atomic weights (Table 1, abridged values, g/mol).
# Source: IUPAC Commission on Isotopic Abundances and Atomic Weights, 2021.
ATOMIC_WEIGHTS: dict[str, float] = {
    "H":   1.008,
    "He":  4.003,
    "Li":  6.941,
    "Be":  9.012,
    "B":  10.811,
    "C":  12.011,
    "N":  14.007,
    "O":  15.999,
    "F":  18.998,
    "Ne": 20.180,
    "Na": 22.990,
    "Mg": 24.305,
    "Al": 26.982,
    "Si": 28.086,
    "P":  30.974,
    "S":  32.060,
    "Cl": 35.450,
    "Ar": 39.948,
    "K":  39.098,
    "Ca": 40.078,
    "Sc": 44.956,
    "Ti": 47.867,
    "V":  50.942,
    "Cr": 51.996,
    "Mn": 54.938,
    "Fe": 55.845,
    "Co": 58.933,
    "Ni": 58.693,
    "Cu": 63.546,
    "Zn": 65.380,
    "Ga": 69.723,
    "Ge": 72.630,
    "As": 74.922,
    "Se": 78.971,
    "Br": 79.904,
    "Kr": 83.798,
    "Rb": 85.468,
    "Sr": 87.620,
    "Y":  88.906,
    "Zr": 91.224,
    "Nb": 92.906,
    "Mo": 95.950,
    "Tc": 98.000,
    "Ru": 101.070,
    "Rh": 102.906,
    "Pd": 106.420,
    "Ag": 107.868,
    "Cd": 112.414,
    "In": 114.818,
    "Sn": 118.710,
    "Sb": 121.760,
    "Te": 127.600,
    "I":  126.904,
    "Xe": 131.293,
    "Cs": 132.905,
    "Ba": 137.327,
    "La": 138.905,
    "Ce": 140.116,
    "Pr": 140.908,
    "Nd": 144.242,
    "Pm": 145.000,
    "Sm": 150.360,
    "Eu": 151.964,
    "Gd": 157.250,
    "Tb": 158.925,
    "Dy": 162.500,
    "Ho": 164.930,
    "Er": 167.259,
    "Tm": 168.934,
    "Yb": 173.045,
    "Lu": 174.967,
    "Hf": 178.490,
    "Ta": 180.948,
    "W":  183.840,
    "Re": 186.207,
    "Os": 190.230,
    "Ir": 192.217,
    "Pt": 195.084,
    "Au": 196.967,
    "Hg": 200.592,
    "Tl": 204.383,
    "Pb": 207.200,
    "Bi": 208.980,
    "Po": 209.000,
    "At": 210.000,
    "Rn": 222.000,
    "Fr": 223.000,
    "Ra": 226.000,
    "Ac": 227.000,
    "Th": 232.038,
    "Pa": 231.036,
    "U":  238.029,
    "Np": 237.000,
    "Pu": 244.000,
    "Am": 243.000,
    "Cm": 247.000,
    "Bk": 247.000,
    "Cf": 251.000,
    "Es": 252.000,
    "Fm": 257.000,
    "Md": 258.000,
    "No": 259.000,
    "Lr": 262.000,
    "Rf": 267.000,
    "Db": 268.000,
    "Sg": 271.000,
    "Bh": 272.000,
    "Hs": 270.000,
    "Mt": 278.000,
    "Ds": 281.000,
    "Rg": 282.000,
    "Cn": 285.000,
    "Nh": 286.000,
    "Fl": 289.000,
    "Mc": 290.000,
    "Lv": 293.000,
    "Ts": 294.000,
    "Og": 294.000,
}


def calculate_mw(hill_formula: str) -> float | None:
    
    if not hill_formula:
        return None
    from services.hydration_service import _parse_formula
    elements = _parse_formula(hill_formula)
    if not elements:
        return None
    mw = 0.0
    for el, count in elements.items():
        weight = ATOMIC_WEIGHTS.get(el)
        if weight is None:
            return None   # unknown element
        mw += weight * count
    return round(mw, 3)
