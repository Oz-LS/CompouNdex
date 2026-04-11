"""
Strict numerical property parser and unit normaliser.

Accepts only values that contain a parseable number.
Qualitative strings ("Very soluble", "Freely soluble", etc.) are rejected
and return None.

Field types: "temperature", "solubility", "density"

Normalised units:
  temperature  → K
  solubility   → g/L
  density      → g/mL
"""
from __future__ import annotations
import re
from dataclasses import dataclass


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class ParsedValue:
    qualifier:      str | None    # ">", "<", "≥", "≤", "~", "≈", "dec."
    lo:             float          # normalised primary value
    hi:             float | None   # upper bound of a range (normalised), else None
    unit:           str            # "K", "g/L", "g/mL"
    condition_temp: float | None   # condition temperature in K (e.g. from "(20 °C)")
    is_decomp:      bool = False   # True when "dec." / "decomposes" prefix present


# ── Temperature unit patterns ─────────────────────────────────────────────────

# Matches "°C", "° C", "°c", "deg C", "degC", "degrees C", "degree C", "ºC", "° c"
_UNIT_C = r'(?:°|º|deg(?:rees?)?\.?\s*)[\s]*[Cc]\b'
# Matches "°F", "deg F", etc.
_UNIT_F = r'(?:°|º|deg(?:rees?)?\.?\s*)[\s]*[Ff]\b'
# Matches "K", "k", "kelvin"
_UNIT_K = r'(?:K\b|kelvin\b)'

_TEMP_UNIT = rf'(?:{_UNIT_C}|{_UNIT_F}|{_UNIT_K})'

# Solubility units (ordered longest first for reliable matching)
_SOL_UNITS = [
    (r'g\s*/\s*100\s*mL',  10.0),        # g/100 mL → g/L  ×10
    (r'g\s*/\s*100\s*g',   10.0),        # g/100 g  ≈ g/L  ×10 (approximate)
    (r'mg\s*/\s*mL',        1.0),        # mg/mL = g/L     ×1
    (r'mg\s*/\s*kg',        0.001),      # mg/kg → g/L     ÷1000
    (r'mg\s*/\s*L',         0.001),      # mg/L → g/L      ÷1000
    (r'g\s*/\s*mL',      1000.0),        # g/mL → g/L      ×1000
    (r'g\s*/\s*kg',         1.0),        # g/kg ≈ g/L      ×1  (water ~1 kg/L)
    (r'g\s*/\s*L',          1.0),        # g/L  as-is
    (r'g\s*/\s*cm3',     1000.0),        # g/cm³ → g/L     ×1000
    (r'µg\s*/\s*mL',      0.001),        # µg/mL → g/L     ÷1000
]

# Density units
_DEN_UNITS = [
    (r'g\s*/\s*cm3',     1.0),           # g/cm³ as-is
    (r'g\s*/\s*mL',      1.0),           # g/mL as-is
    (r'kg\s*/\s*m3',     0.001),         # kg/m³ → g/mL   ÷1000
    (r'kg\s*/\s*L',      1.0),           # kg/L = g/mL
    (r'g\s*/\s*L',       0.001),         # g/L → g/mL     ÷1000
]

# Qualifier prefix
_QUAL_RE = re.compile(r'^([>≥<≤~≈]+)\s*', re.UNICODE)

# Decomposition prefix variants
_DECOMP_RE = re.compile(
    r'(?:dec(?:ompos(?:es?|ition))?\.?\s+(?:at\s+)?|decomposes?\s+at\s+)',
    re.IGNORECASE,
)

# Range separator: "175–180", "175-180", "175 to 180"
_RANGE_SEP = r'\s*(?:–|-|to)\s*'

# Numeric: integer or decimal, optional leading minus
_NUM = r'-?\d+(?:\.\d+)?'

# Condition temperature: "(at 20 °C)", "(20°C)", "at 25 °C", "@ 25°C"
_COND_RE = re.compile(
    rf'(?:\(?\s*at\s+|@\s*|\(\s*)({_NUM})\s*({_TEMP_UNIT})\s*\)?',
    re.IGNORECASE,
)


# ── Public API ────────────────────────────────────────────────────────────────

def parse_numerical(raw: str, field: str) -> ParsedValue | None:
    """
    Parse a raw property string and return a normalised ParsedValue, or None
    if the string contains no usable numeric value.

    field: "temperature" | "solubility" | "density"
    """
    if not raw or not isinstance(raw, str):
        return None
    # Must contain at least one digit
    if not re.search(r'\d', raw):
        return None

    raw = raw.strip()

    if field == "temperature":
        return _parse_temperature(raw)
    if field == "solubility":
        return _parse_with_units(raw, _SOL_UNITS, "g/L")
    if field == "density":
        return _parse_with_units(raw, _DEN_UNITS, "g/mL")
    return None


def format_parsed(p: ParsedValue) -> str:
    """
    Produce a human-readable string from a ParsedValue.
    Examples:
      "dec. 383.1 K"
      "> 500.0 g/L"
      "373.1–374.0 K"
      "35.7 g/L at 293 K"
    """
    qual = ""
    if p.qualifier and p.qualifier != "dec.":
        qual = p.qualifier + " "
    prefix = "dec. " if p.is_decomp else ""

    if p.hi is not None:
        val = f"{p.lo:.1f}–{p.hi:.1f} {p.unit}"
    else:
        val = f"{p.lo:.1f} {p.unit}"

    cond = f" at {p.condition_temp:.0f} K" if p.condition_temp is not None else ""
    return f"{prefix}{qual}{val}{cond}"


# ── Temperature parser ────────────────────────────────────────────────────────

def _parse_temperature(raw: str) -> ParsedValue | None:
    # Detect decomposition prefix
    is_decomp = False
    s = raw
    dm = _DECOMP_RE.match(s)
    if dm:
        is_decomp = True
        s = s[dm.end():]

    # Qualifier (>, <, ~, ≈, etc.)
    qualifier = None
    qm = _QUAL_RE.match(s)
    if qm:
        qualifier = qm.group(1)
        s = s[qm.end():]

    # Range: "175–180 °C"
    range_pat = re.compile(
        rf'({_NUM}){_RANGE_SEP}({_NUM})\s*({_TEMP_UNIT})',
        re.IGNORECASE,
    )
    rm = range_pat.search(s)
    if rm:
        lo_raw = float(rm.group(1))
        hi_raw = float(rm.group(2))
        unit_str = rm.group(3)
        lo_k = _to_kelvin(lo_raw, unit_str)
        hi_k = _to_kelvin(hi_raw, unit_str)
        if lo_k is None:
            return None
        return ParsedValue(
            qualifier=qualifier, lo=lo_k, hi=hi_k,
            unit="K", condition_temp=None, is_decomp=is_decomp,
        )

    # Single value: "175 °C"
    single_pat = re.compile(
        rf'({_NUM})\s*({_TEMP_UNIT})',
        re.IGNORECASE,
    )
    sm = single_pat.search(s)
    if sm:
        val = float(sm.group(1))
        unit_str = sm.group(2)
        k = _to_kelvin(val, unit_str)
        if k is None:
            return None
        return ParsedValue(
            qualifier=qualifier, lo=k, hi=None,
            unit="K", condition_temp=None, is_decomp=is_decomp,
        )

    return None


# ── Generic numeric + unit parser (solubility / density) ─────────────────────

def _parse_with_units(raw: str, unit_table: list[tuple[str, float]],
                      out_unit: str) -> ParsedValue | None:
    # Extract condition temperature first (so we don't confuse it with the main value)
    cond_k: float | None = None
    cm = _COND_RE.search(raw)
    if cm:
        ct_val  = float(cm.group(1))
        ct_unit = cm.group(2)
        cond_k  = _to_kelvin(ct_val, ct_unit)
        # Remove condition clause from the string before parsing the main value
        raw_no_cond = raw[:cm.start()] + raw[cm.end():]
    else:
        raw_no_cond = raw

    # Qualifier
    qualifier = None
    s = raw_no_cond.strip()
    qm = _QUAL_RE.match(s)
    if qm:
        qualifier = qm.group(1)
        s = s[qm.end():]

    for unit_pat, factor in unit_table:
        # Range with this unit
        range_pat = re.compile(
            rf'({_NUM}){_RANGE_SEP}({_NUM})\s*(?:{unit_pat})',
            re.IGNORECASE,
        )
        rm = range_pat.search(s)
        if rm:
            lo = float(rm.group(1)) * factor
            hi = float(rm.group(2)) * factor
            return ParsedValue(qualifier=qualifier, lo=lo, hi=hi,
                               unit=out_unit, condition_temp=cond_k)

        # Single value with this unit
        single_pat = re.compile(
            rf'({_NUM})\s*(?:{unit_pat})',
            re.IGNORECASE,
        )
        sm = single_pat.search(s)
        if sm:
            lo = float(sm.group(1)) * factor
            return ParsedValue(qualifier=qualifier, lo=lo, hi=None,
                               unit=out_unit, condition_temp=cond_k)

    return None


# ── Unit → Kelvin ─────────────────────────────────────────────────────────────

def _to_kelvin(value: float, unit_str: str) -> float | None:
    u = unit_str.strip().lower()
    if re.match(r'k(?:elvin)?$', u):
        return value
    if re.match(r'(?:°|º|deg(?:rees?)?\.?\s*)[\s]*c$', u):
        return value + 273.15
    if re.match(r'(?:°|º|deg(?:rees?)?\.?\s*)[\s]*f$', u):
        return (value + 459.67) * 5.0 / 9.0
    return None
