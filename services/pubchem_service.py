"""
PubChem PUG REST / PUG View API client.
"""
from __future__ import annotations
import logging
import re
import time
import requests

log = logging.getLogger(__name__)

PUG_BASE  = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
VIEW_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"
TIMEOUT   = 12
_DELAY    = 0.25

_CAS_RE = re.compile(r'^\d{2,7}-\d{2}-\d$')
_EC_RE  = re.compile(r'^\d{3}-\d{3}-\d$')


# ── Low-level HTTP ────────────────────────────────────────────────────────────

def _get(url: str, params: dict = None) -> dict | None:
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            time.sleep(3)
            resp = requests.get(url, params=params, timeout=TIMEOUT)
            return resp.json() if resp.status_code == 200 else None
        log.info("pubchem %s -> HTTP %s", url, resp.status_code)
    except requests.RequestException as e:
        log.warning("pubchem request failed for %s: %s", url, e)
    except ValueError as e:
        log.warning("pubchem JSON decode failed for %s: %s", url, e)
    return None


def _pug(path: str, params: dict = None) -> dict | None:
    time.sleep(_DELAY)
    return _get(f"{PUG_BASE}/{path}", params)


def _view(cid: int, heading: str | None = None) -> dict | None:
    time.sleep(_DELAY)
    params = {"heading": heading} if heading else {}
    return _get(f"{VIEW_BASE}/data/compound/{cid}/JSON", params)


# ── CID lookup ────────────────────────────────────────────────────────────────

def get_cid_by_cas(cas: str) -> int | None:
    data = _pug(f"compound/name/{requests.utils.quote(cas)}/cids/JSON")
    cids = _extract_cids(data)
    return cids[0] if cids else None


def get_cid_by_inchikey(inchikey: str) -> int | None:
    data = _pug(f"compound/inchikey/{requests.utils.quote(inchikey)}/cids/JSON")
    cids = _extract_cids(data)
    return cids[0] if cids else None


def get_cids_by_name(name: str, max_results: int = 10) -> list[int]:
    data = _pug(
        f"compound/name/{requests.utils.quote(name)}/cids/JSON",
        params={"name_type": "complete"},
    )
    cids = _extract_cids(data)
    if not cids:
        data = _pug(f"compound/name/{requests.utils.quote(name)}/cids/JSON")
        cids = _extract_cids(data)
    return cids[:max_results]


def get_cids_by_autocomplete(name: str, max_results: int = 10) -> list[int]:
    """
    Use PubChem's autocomplete endpoint to expand a partial/imprecise name
    into a list of suggested compound names, then resolve each to a CID.

    Example: "Vanadium oxide" → ["vanadium dioxide", "vanadium pentoxide", …]
             → [14814, 14811, …]

    Returns an empty list if the autocomplete endpoint is unavailable or
    returns no suggestions.
    """
    try:
        resp = requests.get(
            f"https://pubchem.ncbi.nlm.nih.gov/rest/autocomplete/compound/"
            f"{requests.utils.quote(name)}/JSON",
            params={"limit": max_results * 2},
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            return []
        suggestions: list[str] = resp.json().get("dictionary_terms", {}).get("compound", [])
    except Exception:
        return []

    cids: list[int] = []
    seen: set[int] = set()
    # Resolve each suggestion to a CID (parallel would be ideal but keep it simple)
    for suggestion in suggestions:
        if len(cids) >= max_results:
            break
        batch = get_cids_by_name(suggestion, max_results=1)
        for cid in batch:
            if cid not in seen:
                seen.add(cid)
                cids.append(cid)
    return cids


def get_cids_by_formula(formula: str, max_results: int = 10) -> list[int]:
    data = _pug(
        f"compound/fastformula/{requests.utils.quote(formula)}/cids/JSON",
        params={"MaxRecords": max_results},
    )
    return _extract_cids(data)[:max_results]


def _extract_cids(data: dict | None) -> list[int]:
    if not data:
        return []
    return data.get("IdentifierList", {}).get("CID", [])


# ── Basic properties ──────────────────────────────────────────────────────────

_PROPS = "MolecularFormula,MolecularWeight,IUPACName,Title"


def get_properties(cid: int) -> dict:
    data = _pug(f"compound/cid/{cid}/property/{_PROPS}/JSON")
    if not data:
        return {}
    props = data.get("PropertyTable", {}).get("Properties", [{}])[0]
    return {
        "molecular_formula": props.get("MolecularFormula"),
        "molecular_weight":  _to_float(props.get("MolecularWeight")),
        "iupac_name":        props.get("IUPACName"),
        "title":             props.get("Title"),
    }


def get_properties_batch(cids: list[int]) -> list[dict]:
    if not cids:
        return []
    time.sleep(_DELAY)
    cid_str = ",".join(str(c) for c in cids)
    data = _get(f"{PUG_BASE}/compound/cid/{cid_str}/property/{_PROPS}/JSON")
    if not data:
        return []
    return [
        {
            "cid":               p.get("CID"),
            "molecular_formula": p.get("MolecularFormula"),
            "molecular_weight":  _to_float(p.get("MolecularWeight")),
            "iupac_name":        p.get("IUPACName"),
            "title":             p.get("Title"),
        }
        for p in data.get("PropertyTable", {}).get("Properties", [])
    ]


# ── Synonyms ──────────────────────────────────────────────────────────────────

def get_synonyms(cid: int) -> list[str]:
    data = _pug(f"compound/cid/{cid}/synonyms/JSON")
    if not data:
        return []
    info = data.get("InformationList", {}).get("Information", [{}])[0]
    return info.get("Synonym", [])


def get_cas_from_synonyms(synonyms: list[str]) -> str | None:
    for s in synonyms:
        if _CAS_RE.match(s.strip()):
            return s.strip()
    return None


def get_ec_from_synonyms(synonyms: list[str]) -> str | None:
    for s in synonyms:
        if _EC_RE.match(s.strip()):
            return s.strip()
    return None


def pick_readable_synonyms(synonyms: list[str], max_n: int = 12) -> list[str]:
    """
    Return up to max_n human-readable synonyms.  Skips:
      - CAS / EC numbers, InChI strings, InChIKey
      - SMILES-like strings (long, all-caps/symbols, no spaces)
      - Database registry codes: DTXSID…, CHEBI:…, SCHEMBL…, etc.
      - Strings where every letter is uppercase (shouting / identifier style),
        e.g. "FERROUS SULFATE HEPTAHYDRATE" or "DTXSID9040344"
    """
    _skip = re.compile(
        r'^('
        r'\d[\d\-]+\d'                           # CAS / EC numbers
        r'|InChI='                               # InChI strings
        r'|[A-Z]{14}-[A-Z]{10}-[A-Z]'           # InChIKey
        r'|[A-Z0-9@\[\]\(\)/\\=#\+\-]{20,}'     # SMILES-like (long, no spaces)
        r'|DTXSID\w+'                            # EPA DSSTox IDs
        r'|CHEBI:\d+'                            # ChEBI IDs
        r'|SCHEMBL\d+'                           # SureChEMBL IDs
        r'|[A-Z]{2,}\d{4,}'                     # Generic code pattern (e.g. DB00950)
        r')$'
    )
    result, seen = [], set()
    for s in synonyms:
        s = s.strip()
        if not s or _skip.match(s):
            continue
        # Skip strings where every letter character is uppercase (database identifiers,
        # all-caps duplicates).  Allows short acronyms (≤4 letters) like "EDTA".
        letters = [c for c in s if c.isalpha()]
        if len(letters) > 4 and all(c.isupper() for c in letters):
            continue
        key = s.lower()
        if key not in seen:
            seen.add(key)
            result.append(s)
        if len(result) >= max_n:
            break
    return result


# ── GHS / safety ─────────────────────────────────────────────────────────────

_H_RE  = re.compile(r'\b((?:EUH|H)\d{3}(?:[+](?:EUH|H)\d{3})*)\b', re.IGNORECASE)
_P_RE  = re.compile(r'\b(P\d{3}(?:[+]P\d{3})*)\b',                  re.IGNORECASE)
_GHS_RE = re.compile(r'(GHS\d+)',                                     re.IGNORECASE)


def get_safety_data(cid: int) -> dict:
    empty = {"h_codes": [], "p_codes": [], "pictogram_codes": [], "signal_word": None}

    # Primary: GHS Classification section — extract only the first source block
    # to avoid aggregating codes from minority company classifications.
    data = _view(cid, "GHS Classification")
    result = _extract_first_ghs_block(data) if data else empty.copy()

    # Fallback: full compound view, strict markup-only extraction.
    if not result["h_codes"] and not result["pictogram_codes"]:
        data2 = _view(cid)
        if data2:
            result2 = _extract_safety_strict(data2)
            if result2["h_codes"] or result2["pictogram_codes"]:
                result = result2

    return result


def _extract_first_ghs_block(data: dict) -> dict:
    """
    Extract safety data from only the FIRST source block inside the
    'GHS Classification' section of a PUG View response.

    PubChem stores data from multiple companies/registries in the same section.
    Each block starts with a 'Pictogram(s)' item (or 'Signal' when there are
    no pictograms).  We stop processing when a second such item appears so we
    only get the primary/curated classification and avoid minority codes.
    """
    h_codes, p_codes = [], []
    h_seen, p_seen = set(), set()
    pic_codes: set[str] = set()
    signal_word: str | None = None

    for sec in _deep_find(data, "GHS Classification"):
        signal_count = 0
        pictogram_count = 0

        for info in sec.get("Information", []):
            name = info.get("Name", "")
            swm_list = info.get("Value", {}).get("StringWithMarkup", [])

            # Detect start of a new source block — stop before processing it.
            if name == "Pictogram(s)":
                pictogram_count += 1
                if pictogram_count > 1:
                    break
            elif name == "Signal":
                signal_count += 1
                if signal_count > 1:
                    break

            if name == "Signal":
                for swm in swm_list:
                    s = swm.get("String", "").strip()
                    if s in ("Danger", "Warning") and signal_word is None:
                        signal_word = s

            elif name == "Pictogram(s)":
                for swm in swm_list:
                    for markup in swm.get("Markup", []):
                        m = _GHS_RE.search(markup.get("URL", ""))
                        if m:
                            pic_codes.add(m.group(1))

            elif name == "GHS Hazard Statements":
                for swm in swm_list:
                    for m in _H_RE.finditer(swm.get("String", "")):
                        c = m.group(1).upper()
                        if c not in h_seen:
                            h_seen.add(c)
                            h_codes.append(c)

            elif name == "Precautionary Statement Codes":
                for swm in swm_list:
                    for m in _P_RE.finditer(swm.get("String", "")):
                        c = m.group(1).upper()
                        if c not in p_seen:
                            p_seen.add(c)
                            p_codes.append(c)

        if h_codes or pic_codes:
            break

    return {
        "h_codes":         h_codes,
        "p_codes":         p_codes,
        "pictogram_codes": sorted(pic_codes),
        "signal_word":     signal_word,
    }


def _extract_safety_strict(data: dict) -> dict:
    """Fallback extractor for full compound data — uses markup and URL scan only."""
    h_codes, p_codes = [], []
    h_seen, p_seen = set(), set()

    for extra in _markup_extras(data, "GHSHazard"):
        m = _H_RE.match(extra.strip())
        if m:
            c = m.group(1).upper()
            if c not in h_seen: h_seen.add(c); h_codes.append(c)

    for url in _deep_find_key(data, "URL"):
        if isinstance(url, str):
            m = re.search(r'/ghs/#((?:EUH|H)\d{3})', url, re.IGNORECASE)
            if m:
                c = m.group(1).upper()
                if c not in h_seen: h_seen.add(c); h_codes.append(c)
            m = re.search(r'/ghs/#(P\d{3}(?:[+]P\d{3})*)', url, re.IGNORECASE)
            if m:
                c = m.group(1).upper()
                if c not in p_seen: p_seen.add(c); p_codes.append(c)

    for extra in _markup_extras(data, "GHSPrecautionary"):
        m = _P_RE.match(extra.strip())
        if m:
            c = m.group(1).upper()
            if c not in p_seen: p_seen.add(c); p_codes.append(c)

    pic_codes: set[str] = set()
    for url in _deep_find_key(data, "URL"):
        if isinstance(url, str):
            m = _GHS_RE.search(url)
            if m: pic_codes.add(m.group(1))

    signal_word = None
    for sec in _deep_find(data, "Signal"):
        s = _first_string(sec)
        if s in ("Danger", "Warning"):
            signal_word = s
            break

    return {
        "h_codes":         h_codes,
        "p_codes":         p_codes,
        "pictogram_codes": sorted(pic_codes),
        "signal_word":     signal_word,
    }


# ── Experimental physicochemical properties ───────────────────────────────────

_PROP_MAP = {
    "melting_point":    ["Melting Point"],
    "boiling_point":    ["Boiling Point"],
    "dehydration_temp": ["Decomposition", "Dehydration Temperature",
                         "Decomposition Temperature"],
    "density":          ["Density", "Density or Specific Gravity"],
    "solubility":       ["Water Solubility", "Solubility"],
    "solubility_other": ["Solubility in Organic Solvents",
                         "Solubility in Non-Aqueous Solvents"],
    "appearance":       ["Appearance", "Color/Form"],
}

# Strip solubility-related clauses from appearance text (e.g. from Color/Form).
# Matches:
#   - keyword-based: "; soluble in water", "; miscible with alcohol", etc.
#   - numeric unit ONLY after a separator (avoids mangling leading numbers)
_SOL_KW_RE = re.compile(
    r'[;,]?\s*(?:(?:slightly |very |freely |practically )?(?:in)?soluble'
    r'|miscible|immiscible'
    r'|dissolves\b)'
    r'[^;]*'
    r'|[;,]\s*\d+(?:\.\d+)?\s*g\s*/\s*(?:100\s*)?(?:mL|L)[^;]*',
    re.I,
)


def get_experimental_properties(cid: int) -> dict:
    """
    Fetch experimental physicochemical properties.
    Returns raw strings (no Kelvin conversion) — normalisation is handled
    by data_fusion via property_parser.
    Most recently dated value is preferred when multiple exist.
    """
    result = {k: None for k in _PROP_MAP}

    for heading in ("Experimental Properties", "Chemical and Physical Properties"):
        data = _view(cid, heading)
        if not data:
            continue

        for field, headings in _PROP_MAP.items():
            if result[field]:
                continue
            for h in headings:
                for sec in _deep_find(data, h):
                    candidates = _collect_candidates(sec)
                    if candidates:
                        best = sorted(candidates, key=lambda x: x[1], reverse=True)[0][0]
                        best = best[:300]
                        if field == "appearance":
                            best = _SOL_KW_RE.sub("", best).strip(" ;,")
                            if not best:
                                continue  # only solubility text; skip this section
                        result[field] = best
                        break
                if result[field]:
                    break

        # Also try headings that contain "Melting" or "Boiling" as fuzzy fallback
        for field, exact_headings in (("melting_point", ["Melting Point"]),
                                       ("boiling_point", ["Boiling Point"])):
            if result[field]:
                continue
            for sec in _deep_find_fuzzy(data, exact_headings[0].split()[0]):
                candidates = _collect_candidates(sec)
                if candidates:
                    best = sorted(candidates, key=lambda x: x[1], reverse=True)[0][0]
                    best = best[:300]
                    result[field] = best
                    break

        if all(result.values()):
            break

    # Return solubility and solubility_other separately — fusion handles combination
    return result


def _collect_candidates(section: dict) -> list[tuple[str, str]]:
    candidates = []
    for info in section.get("Information", []):
        val = _first_string_from_info(info)
        if not val:
            continue
        ref = info.get("Reference", "")
        year_m = re.search(r'\b(20\d{2}|19\d{2})\b', str(ref))
        year = year_m.group(1) if year_m else ""
        candidates.append((val, year))
    return candidates


def _first_string_from_info(info: dict) -> str | None:
    for swm in info.get("Value", {}).get("StringWithMarkup", []):
        s = swm.get("String", "").strip()
        if s:
            return s
    return None


# ── SDS URL ───────────────────────────────────────────────────────────────────

_SDS_KW = re.compile(r'safety.data.sheet|[^a-z]sds[^a-z]|msds', re.IGNORECASE)

def get_sds_url(cid: int) -> str | None:
    data = _view(cid, "Safety and Hazards")
    if not data:
        return None
    for url in _deep_find_key(data, "URL"):
        if isinstance(url, str) and _SDS_KW.search(url):
            return url
    for url in _deep_find_key(data, "URL"):
        if isinstance(url, str) and url.lower().endswith(".pdf"):
            return url
    return None


# ── Related compounds ─────────────────────────────────────────────────────────

def get_related_cids(cid: int) -> list[int]:
    data = _pug(
        f"compound/cid/{cid}/cids/JSON",
        params={"relationship": "parent_or_has_parent_compound"},
    )
    return _extract_cids(data)


# ── Traversal helpers ─────────────────────────────────────────────────────────

def _deep_find(obj, heading: str) -> list[dict]:
    found = []
    if isinstance(obj, dict):
        if obj.get("TOCHeading") == heading:
            found.append(obj)
        for v in obj.values():
            found.extend(_deep_find(v, heading))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_deep_find(item, heading))
    return found


def _deep_find_fuzzy(obj, keyword: str) -> list[dict]:
    """Find sections whose TOCHeading contains keyword (case-insensitive)."""
    found = []
    kw = keyword.lower()
    if isinstance(obj, dict):
        heading = obj.get("TOCHeading", "")
        if kw in heading.lower():
            found.append(obj)
        for v in obj.values():
            found.extend(_deep_find_fuzzy(v, keyword))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_deep_find_fuzzy(item, keyword))
    return found


def _deep_find_key(obj, key: str) -> list:
    found = []
    if isinstance(obj, dict):
        if key in obj:
            found.append(obj[key])
        for v in obj.values():
            found.extend(_deep_find_key(v, key))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_deep_find_key(item, key))
    return found


def _all_strings_recursive(obj) -> list[str]:
    strings = []
    if isinstance(obj, dict):
        if "StringWithMarkup" in obj:
            for swm in obj["StringWithMarkup"]:
                s = swm.get("String", "").strip()
                if s:
                    strings.append(s)
        for v in obj.values():
            strings.extend(_all_strings_recursive(v))
    elif isinstance(obj, list):
        for item in obj:
            strings.extend(_all_strings_recursive(item))
    return strings


def _markup_extras(obj, markup_type: str) -> list[str]:
    extras = []
    if isinstance(obj, dict):
        if obj.get("Type") == markup_type and "Extra" in obj:
            extras.append(obj["Extra"])
        for v in obj.values():
            extras.extend(_markup_extras(v, markup_type))
    elif isinstance(obj, list):
        for item in obj:
            extras.extend(_markup_extras(item, markup_type))
    return extras


def _first_string(section: dict) -> str | None:
    for info in section.get("Information", []):
        for swm in info.get("Value", {}).get("StringWithMarkup", []):
            s = swm.get("String", "").strip()
            if s:
                return s
    return None


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
