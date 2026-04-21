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

_H_RE     = re.compile(r'\b((?:EUH|H)\d{3}(?:[+](?:EUH|H)\d{3})*)\b', re.IGNORECASE)
_P_RE     = re.compile(r'\b(P\d{3}(?:[+]P\d{3})*)\b',                  re.IGNORECASE)
_GHS_RE   = re.compile(r'(GHS\d+)',                                     re.IGNORECASE)
# Percentage-qualified codes used in ECHA aggregated blocks, e.g. "H301 (86.2%)".
_H_PCT_RE = re.compile(r'\b((?:EUH|H)\d{3})\s*\(\s*([\d.]+)\s*%\s*\)', re.IGNORECASE)
_P_PCT_RE = re.compile(r'\b(P\d{3}(?:[+]P\d{3})*)\s*\(\s*([\d.]+)\s*%\s*\)', re.IGNORECASE)

# Source-ranking heuristics applied to Reference metadata
# (SourceName + " " + Name + " " + Description).
_RANK_HARMONISED      = re.compile(
    r'regulation\s*\(ec\)\s*no\s*1272/2008|annex\s*vi|harmoni[sz]ed',
    re.IGNORECASE,
)
_RANK_NITE            = re.compile(r'nite[\s-]cmc',           re.IGNORECASE)
_RANK_ECHA_AGGREGATED = re.compile(
    r'aggregated|summary|classifications?\s+from\s+\d+',
    re.IGNORECASE,
)
_RANK_ECHA            = re.compile(r'echa|notification',       re.IGNORECASE)

# Percentage threshold for aggregated ECHA blocks when used as the *primary*
# source (no harmonised / NITE-CMC available).
_AGG_PCT_THRESHOLD = 50.0
# Stricter threshold used when *merging* aggregated data on top of an
# official/curated primary block to fill SDS-style gaps (e.g. flammability
# codes that harmonised classifications sometimes omit).
_MERGE_PCT_THRESHOLD = 70.0

# GHS H-code → pictogram mapping (per UN GHS Rev. 9 / EU CLP Annex I).
# Used to keep pictograms consistent with the H-code list after a merge:
# pictograms derived from merged H codes only, never copied blindly from
# aggregated-block pictograms (which are a union across all company
# notifications and aren't threshold-gated).
_H_TO_PICTOGRAM: dict[int, str] = {
    **{n: "GHS01" for n in range(200, 206)},                                         # explosives
    **{n: "GHS02" for n in (220, 221, 222, 223, 224, 225, 226, 228,
                             240, 241, 242, 250, 251, 260, 261)},                    # flammable
    **{n: "GHS03" for n in (270, 271, 272)},                                         # oxidiser
    **{n: "GHS04" for n in (280, 281)},                                              # gas under pressure
    **{n: "GHS05" for n in (290, 314, 318)},                                         # corrosive
    **{n: "GHS06" for n in (300, 301, 310, 311, 330, 331)},                          # acute tox 1–3
    **{n: "GHS07" for n in (302, 312, 315, 317, 319, 332, 335, 336)},                # exclamation
    **{n: "GHS08" for n in (304, 334, 340, 341, 350, 351, 360, 361,
                             370, 371, 372, 373)},                                   # health hazard
    **{n: "GHS09" for n in range(400, 412)},                                         # environment
}


def get_safety_data(cid: int) -> dict:
    empty = {"h_codes": [], "p_codes": [], "pictogram_codes": [], "signal_word": None}

    # Primary: GHS Classification section — group Information items by
    # ReferenceNumber and pick the highest-priority source block (harmonised
    # > NITE-CMC > single-source notification > ECHA aggregated with pct filter).
    data = _view(cid, "GHS Classification")
    result = _extract_primary_ghs_block(data) if data else empty.copy()

    # Fallback: full compound view, strict markup-only extraction.
    if not result["h_codes"] and not result["pictogram_codes"]:
        data2 = _view(cid)
        if data2:
            result2 = _extract_safety_strict(data2)
            if result2["h_codes"] or result2["pictogram_codes"]:
                result = result2

    return result


def _extract_primary_ghs_block(data: dict) -> dict:
    """
    Extract safety data from the highest-priority source block of the
    'GHS Classification' section.

    PubChem stacks classifications from multiple companies/registries in the
    same section.  Each `Information` item carries a `ReferenceNumber` that
    ties it to an entry in the section's `Reference[]` array, so grouping by
    that number cleanly separates source blocks.  We then rank blocks by
    source authority and extract codes from the first block that has data.
    """
    empty = {"h_codes": [], "p_codes": [], "pictogram_codes": [], "signal_word": None}

    ref_by_num = _build_reference_map(data)
    for sec in _deep_find(data, "GHS Classification"):
        blocks = _group_ghs_blocks(sec, ref_by_num)
        if not blocks:
            continue
        blocks.sort(key=_rank_ghs_block)

        primary: dict | None = None
        primary_was_aggregated = False
        for block in blocks:
            aggregated = _is_aggregated(block["ref"])
            result = _extract_block_codes(block["items"], aggregated)
            if result["h_codes"] or result["pictogram_codes"]:
                primary = result
                primary_was_aggregated = aggregated
                break

        if primary is None:
            continue

        # Fill-in merge: if primary is an official/curated block, top up with
        # codes present at ≥ _MERGE_PCT_THRESHOLD in the best-ranked ECHA
        # aggregated block.  Catches SDS-style codes omitted by harmonised
        # classifications (e.g. flammability H226 for DMF, H361 for toluene).
        # Skip when the primary already IS an aggregated block.
        # Pictograms are derived from the merged H codes — we don't copy the
        # aggregated block's pictogram list, which is a union across all
        # companies and would introduce pictograms with no matching H code.
        if not primary_was_aggregated:
            for block in blocks:
                if not _is_aggregated(block["ref"]):
                    continue
                topup = _extract_block_codes(block["items"], aggregated=True,
                                              pct_threshold=_MERGE_PCT_THRESHOLD)
                added_h: list[str] = []
                for c in topup["h_codes"]:
                    if c not in primary["h_codes"]:
                        primary["h_codes"].append(c)
                        added_h.append(c)
                for c in topup["p_codes"]:
                    if c not in primary["p_codes"]:
                        primary["p_codes"].append(c)
                if added_h:
                    implied = _pictograms_for_h_codes(added_h)
                    if implied:
                        primary["pictogram_codes"] = sorted(
                            set(primary["pictogram_codes"]) | implied
                        )
                break  # only merge with the best-ranked aggregated block

        return primary

    return empty


def _build_reference_map(data: dict) -> dict[int, dict]:
    """
    Collect every Reference entry found anywhere in the response, keyed by
    ReferenceNumber.  In PUG View the section-specific Reference array lives
    at data['Record']['Reference'] (not inside each Section), so we walk the
    whole tree.
    """
    ref_by_num: dict[int, dict] = {}
    for ref in _deep_find_key(data, "Reference"):
        if isinstance(ref, list):
            for r in ref:
                if isinstance(r, dict):
                    rn = r.get("ReferenceNumber")
                    if rn is not None and rn not in ref_by_num:
                        ref_by_num[rn] = r
    return ref_by_num


def _group_ghs_blocks(section: dict, ref_by_num: dict[int, dict]) -> list[dict]:
    """
    Group `Information` items by ReferenceNumber.  Preserves first-appearance
    order.  References are resolved against the precomputed `ref_by_num` map.

    Returns [{"ref_num": int, "ref": dict|None, "items": [info, ...]}, ...].
    Items with no ReferenceNumber are bucketed together under key -1.
    """
    blocks_map: dict[int, dict] = {}
    order: list[int] = []
    for info in section.get("Information", []) or []:
        rn = info.get("ReferenceNumber")
        if rn is None:
            rn = -1
        if rn not in blocks_map:
            blocks_map[rn] = {"ref_num": rn, "ref": ref_by_num.get(rn), "items": []}
            order.append(rn)
        blocks_map[rn]["items"].append(info)

    return [blocks_map[rn] for rn in order]


def _ref_text(ref: dict | None) -> str:
    if not ref:
        return ""
    return " ".join(str(ref.get(k, "") or "") for k in
                    ("SourceName", "Name", "Description"))


def _rank_ghs_block(block: dict) -> tuple[int, int]:
    """Lower rank = higher priority.  Ties broken by ReferenceNumber order."""
    text = _ref_text(block.get("ref"))
    rn   = block.get("ref_num", 0) or 0
    if _RANK_HARMONISED.search(text):
        return (0, rn)
    if _RANK_NITE.search(text):
        return (1, rn)
    if _RANK_ECHA.search(text) and not _RANK_ECHA_AGGREGATED.search(text):
        return (2, rn)
    if _RANK_ECHA_AGGREGATED.search(text) or _RANK_ECHA.search(text):
        return (3, rn)
    return (9, rn)


def _is_aggregated(ref: dict | None) -> bool:
    return bool(_RANK_ECHA_AGGREGATED.search(_ref_text(ref)))


def _pictograms_for_h_codes(h_codes: list[str]) -> set[str]:
    """
    Derive GHS pictogram codes from a list of H codes using `_H_TO_PICTOGRAM`.
    Handles combined codes like 'H302+H312'.  Unknown H numbers are ignored.
    """
    pics: set[str] = set()
    for full in h_codes:
        for h in full.split("+"):
            m = re.match(r'H(\d{3})$', h.strip().upper())
            if not m:
                continue
            pic = _H_TO_PICTOGRAM.get(int(m.group(1)))
            if pic:
                pics.add(pic)
    return pics


def _codes_from_string(s: str, pct_re: re.Pattern, plain_re: re.Pattern,
                       aggregated: bool, pct_threshold: float) -> list[str]:
    """
    Extract hazard/precautionary codes from a single string.

    For aggregated blocks, prefer the percentage-qualified regex and drop
    codes below `pct_threshold`.  If the string has no percentage markers,
    fall back to the plain regex — the block's "aggregated" flag was a
    misclassification or the codes aren't percent-annotated.
    """
    if aggregated:
        pct_matches = list(pct_re.finditer(s))
        if pct_matches:
            out = []
            for m in pct_matches:
                try:
                    pct = float(m.group(2))
                except ValueError:
                    continue
                if pct >= pct_threshold:
                    out.append(m.group(1).upper())
            return out
    return [m.group(1).upper() for m in plain_re.finditer(s)]


def _extract_block_codes(items: list[dict], aggregated: bool,
                         pct_threshold: float = _AGG_PCT_THRESHOLD) -> dict:
    """Extract h_codes, p_codes, pictogram_codes, signal_word from one block."""
    h_codes, p_codes = [], []
    h_seen, p_seen = set(), set()
    pic_codes: set[str] = set()
    signal_word: str | None = None

    for info in items:
        name = info.get("Name", "")
        swm_list = info.get("Value", {}).get("StringWithMarkup", [])

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
                for c in _codes_from_string(swm.get("String", ""),
                                             _H_PCT_RE, _H_RE,
                                             aggregated, pct_threshold):
                    if c not in h_seen:
                        h_seen.add(c)
                        h_codes.append(c)

        elif name == "Precautionary Statement Codes":
            for swm in swm_list:
                for c in _codes_from_string(swm.get("String", ""),
                                             _P_PCT_RE, _P_RE,
                                             aggregated, pct_threshold):
                    if c not in p_seen:
                        p_seen.add(c)
                        p_codes.append(c)

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
