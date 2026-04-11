"""
Wikidata SPARQL client for physicochemical properties, name, and formula.

All data is fetched with a single SPARQL query per compound,
identified by CAS number (P231).

Endpoint: https://query.wikidata.org/sparql (free, no authentication required)

Numeric property values are returned as lists of raw strings ready for
property_parser (e.g. ["357 g/L at 293 K", "448.15 K"]).
An empty list means no value was found in Wikidata.

Unit QIDs are verified against the Wikidata SPARQL endpoint.
Mol-based units (mol/L, mol/kg) are skipped — they cannot be converted
without a molar mass.
"""
from __future__ import annotations
import time
import requests

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
TIMEOUT = 20
_DELAY  = 0.2   # polite delay

# ── Verified Wikidata unit QID → (unit string for property_parser, field type)
# field type: "temperature" | "solubility" | "density"
# Units that cannot be converted (mol-based) are absent — they'll be skipped.
_UNIT_MAP: dict[str, tuple[str, str]] = {
    # Temperature
    "Q11579":   ("K",          "temperature"),   # kelvin
    "Q25267":   ("°C",         "temperature"),   # degree Celsius
    "Q42289":   ("°F",         "temperature"),   # degree Fahrenheit
    # Density
    "Q13147228":  ("g/cm3",   "density"),        # gram per cubic centimetre
    "Q844211":    ("kg/m3",   "density"),        # kilogram per cubic metre → g/mL ÷1000
    "Q101877596": ("g/mL",    "density"),        # gram per millilitre
    # Solubility
    "Q834105":   ("g/L",       "solubility"),     # gram per litre
    "Q21061369": ("g/kg",      "solubility"),     # gram per kilogram (≈ g/L for water)
    "Q60606516": ("g/kg",      "solubility"),     # gram per kilogram of solvent
    "Q21127659": ("g/100g",    "solubility"),     # gram per 100 gram of solvent (≈ g/100 mL)
    "Q55726194": ("mg/L",      "solubility"),     # milligram per litre
    "Q21091747": ("mg/kg",     "solubility"),     # milligram per kilogram (trace solubility)
}

# Extend property_parser unit table for g/kg and g/100g if not already there
# (These are handled by injecting the unit string directly into the raw value.)

# SPARQL — fetches English label, alternative labels (synonyms), Hill formula,
# colour (P462), and all numeric properties with optional condition temperature (P2076).
# Uses UNION + BIND so each property branch is explicit (avoids the
# dynamic ?prop trick which is unsupported in Blazegraph).
_SPARQL = """
SELECT ?label ?altLabel ?formula ?color ?fieldName ?value ?unit ?condTemp ?condUnit WHERE {{
  ?item wdt:P231 "{cas}" .
  OPTIONAL {{ ?item rdfs:label ?label . FILTER(LANG(?label) = "en") }}
  OPTIONAL {{ ?item skos:altLabel ?altLabel . FILTER(LANG(?altLabel) = "en") }}
  OPTIONAL {{ ?item wdt:P274 ?formula }}
  OPTIONAL {{
    ?item wdt:P462 ?colorItem .
    ?colorItem rdfs:label ?color .
    FILTER(LANG(?color) = "en")
  }}
  OPTIONAL {{
    {{
      ?item p:P2101 ?stmt .
      ?stmt psv:P2101 [ wikibase:quantityAmount ?value ; wikibase:quantityUnit ?unit ] .
      BIND("melting_point" AS ?fieldName)
    }} UNION {{
      ?item p:P2102 ?stmt .
      ?stmt psv:P2102 [ wikibase:quantityAmount ?value ; wikibase:quantityUnit ?unit ] .
      BIND("boiling_point" AS ?fieldName)
    }} UNION {{
      ?item p:P2054 ?stmt .
      ?stmt psv:P2054 [ wikibase:quantityAmount ?value ; wikibase:quantityUnit ?unit ] .
      BIND("density" AS ?fieldName)
    }} UNION {{
      ?item p:P2177 ?stmt .
      ?stmt psv:P2177 [ wikibase:quantityAmount ?value ; wikibase:quantityUnit ?unit ] .
      BIND("solubility" AS ?fieldName)
    }}
    OPTIONAL {{
      ?stmt pq:P2076 ?cn .
      ?cn wikibase:quantityAmount ?condTemp ;
          wikibase:quantityUnit   ?condUnit .
    }}
  }}
}}
"""


def get_all_by_cas(cas: str) -> dict:
    """
    Single SPARQL query returning:
      name      — English rdfs:label (str | None)
      formula   — Hill formula from P274 (str | None)
      synonyms  — English skos:altLabel list (list[str])
      appearance — P462 colour label(s) joined (str | None)
      + numeric physicochemical properties as lists of raw strings
        (melting_point, boiling_point, density, solubility)
    """
    empty = {
        "name":             None,
        "formula":          None,
        "synonyms":         [],
        "melting_point":    [],
        "boiling_point":    [],
        "dehydration_temp": [],
        "density":          [],
        "solubility":       [],
        "solubility_other": [],
        "appearance":       None,
    }
    if not cas:
        return empty

    try:
        rows = _query(cas)
    except Exception:
        return empty

    name:     str | None = None
    formula:  str | None = None
    synonyms: list[str]  = []
    colors:   list[str]  = []
    props: dict[str, list[str]] = {
        k: [] for k in ("melting_point", "boiling_point",
                        "dehydration_temp", "density", "solubility")
    }

    for row in rows:
        # Name (take first non-None)
        if name is None:
            lbl = (row.get("label") or {}).get("value")
            if lbl:
                name = lbl.strip()

        # Alternative labels (synonyms) — collect unique values
        alt = (row.get("altLabel") or {}).get("value")
        if alt:
            alt = alt.strip()
            if alt and alt not in synonyms and alt != name:
                synonyms.append(alt)

        # Formula (take first non-None)
        if formula is None:
            frm = (row.get("formula") or {}).get("value")
            if frm:
                formula = frm.strip()

        # Colour (P462 label)
        col = (row.get("color") or {}).get("value")
        if col:
            col = col.strip()
            if col and col not in colors:
                colors.append(col)

        # Property value
        field = (row.get("fieldName") or {}).get("value")
        if not field or field not in props:
            continue

        value_str = (row.get("value") or {}).get("value", "")
        unit_uri  = (row.get("unit")  or {}).get("value", "")
        unit_qid  = unit_uri.rsplit("/", 1)[-1]
        unit_info = _UNIT_MAP.get(unit_qid)
        if not unit_info or not value_str:
            continue

        unit_str, _ = unit_info
        try:
            val = float(value_str)
        except ValueError:
            continue

        raw = f"{val} {unit_str}"

        # Condition temperature
        cond_val_str = (row.get("condTemp") or {}).get("value", "")
        cond_uri     = (row.get("condUnit") or {}).get("value", "")
        cond_qid     = cond_uri.rsplit("/", 1)[-1]
        cond_info    = _UNIT_MAP.get(cond_qid)
        if cond_val_str and cond_info:
            cond_unit_str, _ = cond_info
            try:
                cond_val = float(cond_val_str)
                raw += f" at {cond_val} {cond_unit_str}"
            except ValueError:
                pass

        if raw not in props[field]:
            props[field].append(raw)

    # Build appearance string from collected colours (e.g. "white", "blue")
    appearance = ", ".join(colors) if colors else None

    return {**empty, **props,
            "name": name, "formula": formula,
            "synonyms": synonyms, "appearance": appearance}


# ── SPARQL helper ─────────────────────────────────────────────────────────────

def _query(cas: str) -> list[dict]:
    time.sleep(_DELAY)
    sparql = _SPARQL.format(cas=cas.replace('"', ''))
    headers = {
        "Accept":     "application/sparql-results+json",
        "User-Agent": "reagentario/1.0 (lab inventory)",
    }
    resp = requests.get(
        SPARQL_ENDPOINT,
        params={"query": sparql, "format": "json"},
        headers=headers,
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        return []
    return resp.json().get("results", {}).get("bindings", [])
