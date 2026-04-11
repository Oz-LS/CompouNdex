"""
Name normalizer — converts API-returned compound names to IUPAC Stock notation
for inorganic compounds.

Three strategies (tried in order by get_stock_name):
  1. Traditional prefix substitution  ("ferric" → "Iron(III)")
  2. Arabic charge notation            ("copper(2+)" → "Copper(II)")
  3. Formula-based generation          (Hill formula → oxidation state → name)

For hydrated compounds a fourth path strips the IUPAC hydration suffix, applies
strategies 1-3 to the base name/formula, then re-appends the suffix.

Organic compounds (formulas with high C content) are left unchanged (None).
"""
from __future__ import annotations
import re


# ── Variable-charge metals: element → {oxidation_state: Stock name} ───────────

_VARIABLE_STOCK: dict[str, dict[int, str]] = {
    "Fe": {2: "Iron(II)",        3: "Iron(III)",       6: "Iron(VI)"},
    "Cu": {1: "Copper(I)",       2: "Copper(II)",      3: "Copper(III)"},
    "Mn": {2: "Manganese(II)",   3: "Manganese(III)",  4: "Manganese(IV)",
           6: "Manganese(VI)",   7: "Manganese(VII)"},
    "Cr": {2: "Chromium(II)",    3: "Chromium(III)",   6: "Chromium(VI)"},
    "Co": {2: "Cobalt(II)",      3: "Cobalt(III)"},
    "Ni": {2: "Nickel(II)",      3: "Nickel(III)",     4: "Nickel(IV)"},
    "Ti": {2: "Titanium(II)",    3: "Titanium(III)",   4: "Titanium(IV)"},
    "V":  {2: "Vanadium(II)",    3: "Vanadium(III)",   4: "Vanadium(IV)",
           5: "Vanadium(V)"},
    "Sn": {2: "Tin(II)",         4: "Tin(IV)"},
    "Pb": {2: "Lead(II)",        4: "Lead(IV)"},
    "Hg": {1: "Mercury(I)",      2: "Mercury(II)"},
    "Au": {1: "Gold(I)",         3: "Gold(III)"},
    "Pt": {2: "Platinum(II)",    4: "Platinum(IV)"},
    "Pd": {2: "Palladium(II)",   4: "Palladium(IV)"},
    "Tl": {1: "Thallium(I)",     3: "Thallium(III)"},
    "Ga": {1: "Gallium(I)",      3: "Gallium(III)"},
    "In": {1: "Indium(I)",       3: "Indium(III)"},
    "As": {3: "Arsenic(III)",    5: "Arsenic(V)"},
    "Sb": {3: "Antimony(III)",   5: "Antimony(V)"},
    "Bi": {3: "Bismuth(III)",    5: "Bismuth(V)"},
    "W":  {4: "Tungsten(IV)",    6: "Tungsten(VI)"},
    "Mo": {3: "Molybdenum(III)", 4: "Molybdenum(IV)", 6: "Molybdenum(VI)"},
    "Re": {4: "Rhenium(IV)",     7: "Rhenium(VII)"},
    "Os": {4: "Osmium(IV)",      8: "Osmium(VIII)"},
    "Ir": {3: "Iridium(III)",    4: "Iridium(IV)"},
    "Ru": {2: "Ruthenium(II)",   3: "Ruthenium(III)", 4: "Ruthenium(IV)"},
    "Rh": {3: "Rhodium(III)"},
    "Nb": {3: "Niobium(III)",    5: "Niobium(V)"},
    "Ta": {5: "Tantalum(V)"},
    "Ce": {3: "Cerium(III)",     4: "Cerium(IV)"},
    "Eu": {2: "Europium(II)",    3: "Europium(III)"},
    "U":  {3: "Uranium(III)",    4: "Uranium(IV)",    6: "Uranium(VI)"},
    "Th": {4: "Thorium(IV)"},
    "Tc": {4: "Technetium(IV)",  7: "Technetium(VII)"},
    "Po": {2: "Polonium(II)",    4: "Polonium(IV)"},
    "Ag": {2: "Silver(II)"},     # Ag⁺ (common) handled via _FIXED_NAME/_FIXED_CHARGES
}

# Fixed-charge metals: element → English name (no Roman numeral)
# Note: H is intentionally excluded — in inorganic salts H appears only inside
# polyatomic anions (OH⁻, HCO₃⁻, …), never as a free H⁺ cation.
_FIXED_NAME: dict[str, str] = {
    "Li": "Lithium",    "Na": "Sodium",       "K":  "Potassium",
    "Rb": "Rubidium",   "Cs": "Cesium",       "Fr": "Francium",
    "Be": "Beryllium",  "Mg": "Magnesium",    "Ca": "Calcium",
    "Sr": "Strontium",  "Ba": "Barium",       "Ra": "Radium",
    "Sc": "Scandium",   "Y":  "Yttrium",
    "Al": "Aluminium",  "Zn": "Zinc",
    "Ag": "Silver",     "Cd": "Cadmium",
    "Zr": "Zirconium",  "Hf": "Hafnium",
    "La": "Lanthanum",  "Pr": "Praseodymium", "Nd": "Neodymium",
    "Pm": "Promethium", "Sm": "Samarium",     "Gd": "Gadolinium",
    "Tb": "Terbium",    "Dy": "Dysprosium",   "Ho": "Holmium",
    "Er": "Erbium",     "Tm": "Thulium",      "Yb": "Ytterbium",
    "Lu": "Lutetium",
}

# Fixed oxidation state for each of the above (used in charge balance)
_FIXED_CHARGES: dict[str, int] = {
    "Li": +1, "Na": +1, "K": +1,  "Rb": +1, "Cs": +1, "Fr": +1,
    "Be":+2, "Mg": +2, "Ca": +2, "Sr": +2, "Ba": +2, "Ra": +2,
    "Sc":+3, "Y":  +3, "Al": +3, "Zn": +2, "Ag": +1, "Cd": +2,
    "Zr":+4, "Hf": +4,
    "La":+3, "Pr": +3, "Nd": +3, "Pm": +3, "Sm": +3,
    "Gd":+3, "Tb": +3, "Dy": +3, "Ho": +3, "Er": +3, "Tm": +3,
    "Yb":+3, "Lu": +3,
}

# All known metal elements (union of fixed + variable)
_ALL_METALS: frozenset[str] = frozenset(_FIXED_NAME) | frozenset(_VARIABLE_STOCK)

# Anion formula key → (charge, English name)
ANION_TABLE: dict[str, tuple[int, str]] = {
    # Monatomic
    "F":     (-1, "fluoride"),
    "Cl":    (-1, "chloride"),
    "Br":    (-1, "bromide"),
    "I":     (-1, "iodide"),
    "O":     (-2, "oxide"),
    "S":     (-2, "sulfide"),
    "Se":    (-2, "selenide"),
    "Te":    (-2, "telluride"),
    "N":     (-3, "nitride"),
    "P":     (-3, "phosphide"),
    "H":     (-1, "hydride"),
    # Polyatomic (longer keys matched first)
    "H2PO4": (-1, "dihydrogen phosphate"),
    "HPO4":  (-2, "hydrogen phosphate"),
    "HCO3":  (-1, "bicarbonate"),
    "S2O3":  (-2, "thiosulfate"),
    "Cr2O7": (-2, "dichromate"),
    "AsO4":  (-3, "arsenate"),
    "MnO4":  (-1, "permanganate"),
    "ClO4":  (-1, "perchlorate"),
    "ClO3":  (-1, "chlorate"),
    "ClO2":  (-1, "chlorite"),
    "CrO4":  (-2, "chromate"),
    "SO4":   (-2, "sulfate"),
    "SO3":   (-2, "sulfite"),
    "PO4":   (-3, "phosphate"),
    "NO3":   (-1, "nitrate"),
    "NO2":   (-1, "nitrite"),
    "CO3":   (-2, "carbonate"),
    "BO3":   (-3, "borate"),
    "SCN":   (-1, "thiocyanate"),
    "OCN":   (-1, "cyanate"),
    "ClO":   (-1, "hypochlorite"),
    "OH":    (-1, "hydroxide"),
    "CN":    (-1, "cyanide"),
}

# Traditional cation prefix word → Stock cation fragment (lowercase)
_TRADITIONAL_TO_STOCK: dict[str, str] = {
    "ferrous":      "iron(II)",       "ferric":       "iron(III)",
    "cuprous":      "copper(I)",      "cupric":       "copper(II)",
    "mercurous":    "mercury(I)",     "mercuric":     "mercury(II)",
    "stannous":     "tin(II)",        "stannic":      "tin(IV)",
    "plumbous":     "lead(II)",       "plumbic":      "lead(IV)",
    "manganous":    "manganese(II)",  "manganic":     "manganese(III)",
    "chromous":     "chromium(II)",   "chromic":      "chromium(III)",
    "cobaltous":    "cobalt(II)",     "cobaltic":     "cobalt(III)",
    "nickelous":    "nickel(II)",     "nickelic":     "nickel(III)",
    "aurous":       "gold(I)",        "auric":        "gold(III)",
    "palladous":    "palladium(II)",  "palladic":     "palladium(IV)",
    "platinous":    "platinum(II)",   "platinic":     "platinum(IV)",
    "cerous":       "cerium(III)",    "ceric":        "cerium(IV)",
    "vanadous":     "vanadium(III)",  "vanadic":      "vanadium(IV)",
    "titanous":     "titanium(III)",  "titanic":      "titanium(IV)",
    "thallous":     "thallium(I)",    "thallic":      "thallium(III)",
    "bismuthous":   "bismuth(III)",   "bismuthic":    "bismuth(V)",
    "arsenious":    "arsenic(III)",
    "stibious":     "antimony(III)",  "antimonic":    "antimony(V)",
    "argentic":     "silver(II)",
    "europous":     "europium(II)",   "europic":      "europium(III)",
    "uranous":      "uranium(IV)",    "uranic":       "uranium(VI)",
    "hypotitanous": "titanium(II)",
    "hypovanadous": "vanadium(II)",   "pervanadic":   "vanadium(V)",
    "gallous":      "gallium(I)",     "gallic":       "gallium(III)",
    "indous":       "indium(I)",      "indic":        "indium(III)",
}

# Arabic charge "(n+)" → Roman numeral
_ARABIC_TO_ROMAN: dict[int, str] = {
    1: "I", 2: "II", 3: "III", 4: "IV",
    5: "V", 6: "VI", 7: "VII", 8: "VIII",
}
_ARABIC_ION_RE = re.compile(r'\((\d+)\+\)')


# ── Public API ────────────────────────────────────────────────────────────────

def get_stock_name(api_name: str | None, hill_formula: str | None) -> str | None:
    """
    Return the Stock-notation name for an inorganic compound, or None if the
    compound is organic or cannot be reliably normalised.

    Resolution order:
      1. Traditional prefix substitution  ("ferric chloride" → "Iron(III) chloride")
      2. Arabic ion notation              ("copper(2+) sulfate" → "Copper(II) sulfate")
      3. Formula-based generation         (Hill formula → charge balance → name)
      4. Hydrate fallback                 (strip suffix → normalise base → re-append)
    """
    if hill_formula and not _seems_inorganic(hill_formula):
        return None

    if api_name:
        result = normalize_traditional(api_name)
        if result:
            return result
        result = _normalize_arabic_ions(api_name)
        if result:
            return result

    if hill_formula:
        result = stock_from_formula(hill_formula)
        if result:
            return result

    # Hydrate fallback: strip suffix, try name + formula on the base
    if api_name and hill_formula:
        return _try_stock_for_hydrate(api_name, hill_formula)

    return None


def normalize_traditional(name: str) -> str | None:
    """
    Replace known traditional-prefix cation words with their Stock equivalents.
    Case-insensitive; first character of result is uppercased.

      "Cupric chloride"            → "Copper(II) chloride"
      "Ferric sulfate nonahydrate" → "Iron(III) sulfate nonahydrate"

    Returns None if no known traditional prefix is found.
    """
    words = name.split()
    new_words = []
    found = False
    for w in words:
        key = w.lower().rstrip(".,;:")
        if key in _TRADITIONAL_TO_STOCK:
            new_words.append(_TRADITIONAL_TO_STOCK[key])
            found = True
        else:
            new_words.append(w.lower())
    if not found:
        return None
    result = " ".join(new_words)
    return result[0].upper() + result[1:] if result else None


def stock_from_formula(hill_formula: str) -> str | None:
    """
    Generate a Stock name deterministically from a Hill formula.

    Works for compounds with exactly one metal and one recognisable anion type.
    Returns None for multi-metal compounds, unrecognised anions, non-integer
    oxidation states, or formulas that fail to parse.
    """
    from services.hydration_service import _parse_formula

    elements = _parse_formula(hill_formula)
    if not elements:
        return None

    metals = [el for el in elements if el in _ALL_METALS]
    if len(metals) != 1:
        return None
    metal       = metals[0]
    metal_count = elements[metal]

    remaining = {el: cnt for el, cnt in elements.items() if el != metal}
    if not remaining:
        return None

    match = _match_anion(remaining)
    if not match:
        return None
    anion_name, anion_charge, anion_count = match

    # Charge balance: metal_count × q + anion_count × anion_charge = 0
    numerator   = -(anion_count * anion_charge)
    denominator = metal_count
    if numerator % denominator != 0:
        return None
    metal_charge = numerator // denominator

    # Fixed-charge metal → name without Roman numeral
    if metal in _FIXED_CHARGES and metal_charge == _FIXED_CHARGES[metal]:
        cation_name = _FIXED_NAME[metal]
    elif metal in _VARIABLE_STOCK:
        charge_map = _VARIABLE_STOCK[metal]
        if metal_charge not in charge_map:
            return None
        cation_name = charge_map[metal_charge]
    else:
        return None

    return f"{cation_name} {anion_name}"


# ── Private helpers ───────────────────────────────────────────────────────────

def _seems_inorganic(hill_formula: str) -> bool:
    """
    True when the formula is likely inorganic.  C-free → always True.
    C-present → inorganic only when C atoms ≤ metal atom count
    (covers carbonates, cyanides, carbides without catching organics).
    """
    from services.hydration_service import _parse_formula
    elements = _parse_formula(hill_formula)
    if not elements:
        return True
    if "C" not in elements:
        return True
    c_count     = elements["C"]
    metal_count = sum(v for k, v in elements.items() if k in _ALL_METALS)
    return bool(metal_count) and c_count <= metal_count


def _normalize_arabic_ions(name: str) -> str | None:
    """
    Convert PubChem-style arabic charge notation to Roman numerals.
    "copper(2+) sulfate" → "Copper(II) sulfate"
    Returns None if no "(n+)" pattern is present.
    """
    if not _ARABIC_ION_RE.search(name):
        return None

    def repl(m: re.Match) -> str:
        n     = int(m.group(1))
        roman = _ARABIC_TO_ROMAN.get(n)
        return f"({roman})" if roman else m.group(0)

    result = _ARABIC_ION_RE.sub(repl, name)
    return result[0].upper() + result[1:] if result else None


def _try_stock_for_hydrate(api_name: str, hill_formula: str) -> str | None:
    """
    Handle hydrated compounds: strip the IUPAC hydration suffix, normalise the
    base via name-based then formula-based methods, then re-append the suffix.
    The anhydrous Hill formula is derived by subtracting n·H₂O.
    """
    from services.hydration_service import HYDRATION_SUFFIXES, _parse_formula, _to_hill

    name_lower = api_name.lower()
    for degree, suffix in sorted(HYDRATION_SUFFIXES.items(),
                                  key=lambda kv: -len(kv[1])):
        sfx_lower = " " + suffix.lower()
        if not name_lower.endswith(sfx_lower):
            continue

        base_name = api_name[: -len(sfx_lower)].strip()

        # 1. Name-based approaches on the base
        base_stock = (normalize_traditional(base_name)
                      or _normalize_arabic_ions(base_name))
        if base_stock:
            return f"{base_stock} {suffix}"

        # 2. Formula-based: subtract n·H₂O, name the anhydrous residue
        elements = _parse_formula(hill_formula)
        if elements:
            h_sub = int(2 * degree + 0.5)
            o_sub = int(degree + 0.5)
            anhydrous = dict(elements)
            anhydrous["H"] = anhydrous.get("H", 0) - h_sub
            anhydrous["O"] = anhydrous.get("O", 0) - o_sub
            if anhydrous.get("H", 0) >= 0 and anhydrous.get("O", 0) >= 0:
                anhydrous = {k: v for k, v in anhydrous.items() if v > 0}
                if anhydrous:
                    base_stock = stock_from_formula(_to_hill(anhydrous))
                    if base_stock:
                        return f"{base_stock} {suffix}"
        break  # only the first (longest) matching suffix
    return None


def classic_formula_from_hill(
    hill_formula: str | None,
    hydration_degree: float | None = None,
) -> str | None:
    """
    Return the 'classic' inorganic formula string built from a Hill formula.

    Examples
    --------
    Hill "FeSO4",    no hydrate  → "FeSO4"
    Hill "FeH14O11S", degree=7   → "FeSO4·7H2O"
    Hill "Fe2O12S3", no hydrate  → "Fe2(SO4)3"
    Hill "CaH2O2",   no hydrate  → "Ca(OH)2"
    Hill "AlCl3",    no hydrate  → "AlCl3"

    Returns None for organic compounds, multi-metal compounds, or formulas that
    don't map to a recognised metal + anion structure.
    """
    from services.hydration_service import _parse_formula

    if not hill_formula:
        return None
    if not _seems_inorganic(hill_formula):
        return None

    elements = _parse_formula(hill_formula)
    if not elements:
        return None

    # Strip water if a hydration degree is given
    suffix = ""
    if hydration_degree and hydration_degree > 0:
        h_sub = int(2 * hydration_degree + 0.5)
        o_sub = int(hydration_degree + 0.5)
        anhydrous = dict(elements)
        anhydrous["H"] = anhydrous.get("H", 0) - h_sub
        anhydrous["O"] = anhydrous.get("O", 0) - o_sub
        if anhydrous.get("H", 0) < 0 or anhydrous.get("O", 0) < 0:
            return None
        anhydrous = {k: v for k, v in anhydrous.items() if v > 0}
        if not anhydrous:
            return None
        elements = anhydrous
        # Format suffix: ·H2O, ·2H2O, ·0.5H2O …
        n = hydration_degree
        if n == int(n):
            n_int = int(n)
            n_pfx = "" if n_int == 1 else str(n_int)
        else:
            n_pfx = str(n)
        suffix = f"\u00b7{n_pfx}H\u2082O"  # ·nH₂O  (middle dot, subscript 2)

    result = _build_classic_from_elements(elements)
    if result is None:
        return None
    return result + suffix


def _build_classic_from_elements(elements: dict[str, int]) -> str | None:
    """
    Build a classic inorganic formula string from an element-count dict.

    Finds the single metal cation and the matching anion from ANION_TABLE,
    then assembles: metal(count) + anion(count), with parentheses around
    polyatomic anions when their count > 1.

    Returns None when the dict does not map to one metal + one anion type.
    """
    metals = [el for el in elements if el in _ALL_METALS]
    if len(metals) != 1:
        return None
    metal       = metals[0]
    metal_count = elements[metal]

    remaining = {el: cnt for el, cnt in elements.items() if el != metal}
    if not remaining:
        return None

    # Find matching anion key and count (longest key first, same logic as _match_anion)
    anion_key   = None
    anion_count = None
    for key, (_charge, _name) in sorted(ANION_TABLE.items(), key=lambda x: -len(x[0])):
        anion_els = _parse_simple(key)
        if set(anion_els) != set(remaining):
            continue
        ratios: set[int] = set()
        valid = True
        for el, cnt in anion_els.items():
            rem = remaining.get(el, 0)
            if cnt == 0 or rem % cnt != 0:
                valid = False
                break
            ratios.add(rem // cnt)
        if valid and len(ratios) == 1:
            n = next(iter(ratios))
            if n > 0:
                anion_key   = key
                anion_count = n
                break

    if anion_key is None:
        return None

    # metal part: "Fe", "Fe2", "Al2", …
    metal_str = metal + (str(metal_count) if metal_count > 1 else "")

    # anion part: polyatomic gets parentheses when count > 1
    anion_els = _parse_simple(anion_key)
    is_poly   = len(anion_els) > 1

    if is_poly and anion_count > 1:
        anion_str = f"({anion_key}){anion_count}"
    elif is_poly:
        anion_str = anion_key          # e.g. "OH" when n=1
    else:
        anion_str = anion_key + (str(anion_count) if anion_count > 1 else "")

    return metal_str + anion_str


def _parse_simple(formula: str) -> dict[str, int]:
    """Parse a simple (no-parentheses) formula string into {element: count}."""
    result: dict[str, int] = {}
    for m in re.finditer(r'([A-Z][a-z]?)(\d*)', formula):
        el = m.group(1)
        if el:
            result[el] = result.get(el, 0) + (int(m.group(2)) if m.group(2) else 1)
    return result


def _match_anion(remaining: dict[str, int]) -> tuple[str, int, int] | None:
    """
    Match a remaining-elements dict to known_anion × n.
    Returns (anion_name, anion_charge, n) or None.
    Tries longer keys first so polyatomics take priority over monatomics.
    """
    for key, (charge, name) in sorted(ANION_TABLE.items(), key=lambda x: -len(x[0])):
        anion_els = _parse_simple(key)
        if set(anion_els) != set(remaining):
            continue
        ratios: set[int] = set()
        valid = True
        for el, cnt in anion_els.items():
            rem = remaining.get(el, 0)
            if cnt == 0 or rem % cnt != 0:
                valid = False
                break
            ratios.add(rem // cnt)
        if valid and len(ratios) == 1:
            n = next(iter(ratios))
            if n > 0:
                return (name, charge, n)
    return None
