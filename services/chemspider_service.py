"""
ChemSpider RSC API v1 client (api.rsc.org).

PRIMARY data source for names, formula, MW and physicochemical properties.
PubChem is used for safety data (H/P, pictograms) and as fallback.

Endpoints used:
  POST /filter/name           — search by name (async)
  POST /filter/formula        — search by formula (async)
  POST /filter/inchikey       — search by InChIKey (async)
  GET  /filter/{qid}/status   — poll async query
  GET  /filter/{qid}/results  — retrieve CSIDs
  GET  /records/{id}/details  — formula, MW, commonName, SMILES, InChI
  POST /records/batch         — batch details (max 10)
  GET  /records/{id}/externalreferences — physicochemical props, CAS, IUPAC name, synonyms
  GET  /lookups/datasources   — list valid datasource names
"""
from __future__ import annotations
import logging
import re
import time
import requests
from flask import current_app

log = logging.getLogger(__name__)

BASE       = "https://api.rsc.org/compounds/v1"
TIMEOUT    = 10
POLL_MAX   = 10
POLL_DELAY = 1.0

_CAS_RE = re.compile(r'^\d{2,7}-\d{2}-\d$')

_PHYS_DATASOURCES = ",".join([
    "PhysProp",
    "NIST Chemistry WebBook",
    "Alfa Aesar",
    "Sigma-Aldrich",
    "Acros Organics",
])

_SOURCE_PRIORITY: dict[str, int] = {
    "PhysProp":               1,
    "NIST Chemistry WebBook": 2,
    "Alfa Aesar":             3,
    "Sigma-Aldrich":          4,
    "Acros Organics":         5,
}

_PROP_ALIASES: dict[str, list[str]] = {
    "melting_point": [
        "Melting Point", "Melting point", "melting point", "Melting Pt", "mp",
    ],
    "boiling_point": [
        "Boiling Point", "Boiling point", "boiling point", "Boiling Pt", "bp",
    ],
    "dehydration_temp": [
        "Decomposition", "Decomposition Temperature", "Dehydration Temperature",
    ],
    "density": [
        "Density", "density",
        "Specific Gravity", "specific gravity", "Density or Specific Gravity",
    ],
    "solubility": [
        "Solubility in water", "Water Solubility",
        "Solubility", "solubility", "Aqueous Solubility",
    ],
    "solubility_other": [
        "Solubility in organic solvents", "Organic Solubility",
        "Solubility (non-aqueous)",
    ],
    "appearance": [
        "Appearance", "appearance", "Physical Form", "physical form", "Color/Form",
    ],
}


# ── Availability ──────────────────────────────────────────────────────────────

def is_available() -> bool:
    try:
        return bool(current_app.config.get("CHEMSPIDER_API_KEY"))
    except RuntimeError:
        return False


def _headers() -> dict:
    return {
        "apikey": current_app.config.get("CHEMSPIDER_API_KEY", ""),
        "Content-Type": "application/json",
    }


# ── Low-level HTTP ────────────────────────────────────────────────────────────

def _post(path: str, body: dict) -> dict | None:
    try:
        r = requests.post(f"{BASE}/{path}", json=body,
                          headers=_headers(), timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json()
        log.info("chemspider POST %s -> HTTP %s", path, r.status_code)
    except requests.RequestException as e:
        log.warning("chemspider POST %s failed: %s", path, e)
    except ValueError as e:
        log.warning("chemspider POST %s JSON decode failed: %s", path, e)
    return None


def _get(path: str, params: dict = None) -> dict | None:
    try:
        r = requests.get(f"{BASE}/{path}", params=params,
                         headers=_headers(), timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json()
        log.info("chemspider GET %s -> HTTP %s", path, r.status_code)
    except requests.RequestException as e:
        log.warning("chemspider GET %s failed: %s", path, e)
    except ValueError as e:
        log.warning("chemspider GET %s JSON decode failed: %s", path, e)
    return None


# ── Async filter (shared) ─────────────────────────────────────────────────────

def _run_filter(endpoint: str, body: dict, max_results: int = 10) -> list[int]:
    if not is_available():
        return []
    resp = _post(endpoint, body)
    if not resp or "queryId" not in resp:
        return []
    qid = resp["queryId"]
    for _ in range(POLL_MAX):
        time.sleep(POLL_DELAY)
        status = _get(f"filter/{qid}/status")
        if not status:
            break
        s = status.get("status", "")
        if s == "Complete":
            res = _get(f"filter/{qid}/results",
                       params={"start": 0, "count": max_results})
            return res.get("results", []) if res else []
        if s in ("Failed", "Suspended"):
            break
    return []


# ── Search ────────────────────────────────────────────────────────────────────

def search_by_name(name: str, max_results: int = 10) -> list[int]:
    return _run_filter(
        "filter/name",
        {"name": name, "orderBy": "recordCount", "orderByDirection": "descending"},
        max_results,
    )


def search_by_formula(formula: str, max_results: int = 10) -> list[int]:
    return _run_filter(
        "filter/formula",
        {"formula": formula, "orderBy": "recordCount", "orderByDirection": "descending"},
        max_results,
    )


def search_by_cas(cas: str) -> list[int]:
    return _run_filter(
        "filter/name",
        {"name": cas, "orderBy": "recordCount", "orderByDirection": "descending"},
        max_results=5,
    )


def filter_by_inchikey(inchikey: str) -> list[int]:
    """
    Search using the dedicated POST /filter/inchikey endpoint.
    More reliable than passing InChIKey to the name filter.
    """
    return _run_filter(
        "filter/inchikey",
        {"inchikey": inchikey},
        max_results=3,
    )


# ── Lookups ───────────────────────────────────────────────────────────────────

# ── Record details ────────────────────────────────────────────────────────────

_DETAIL_FIELDS = [
    "CommonName", "Formula", "MolecularWeight",
    "NominalMass", "MonoisotopicMass",
    "InChI", "InChIKey", "SMILES",
]


def get_record_details(csid: int) -> dict:
    if not is_available():
        return {}
    data = _get(
        f"records/{csid}/details",
        params={"fields": ",".join(_DETAIL_FIELDS)},
    )
    if not data:
        return {}
    return {
        "csid":              csid,
        "common_name":       data.get("commonName") or data.get("CommonName"),
        "molecular_formula": data.get("formula")    or data.get("Formula"),
        "molecular_weight":  _to_float(
            data.get("molecularWeight") or data.get("MolecularWeight")
        ),
        "inchi":    data.get("inchi")    or data.get("InChI"),
        "inchikey": data.get("inchiKey") or data.get("InChIKey"),
        "smiles":   data.get("smiles")   or data.get("SMILES"),
    }


def get_record_details_batch(csids: list[int]) -> list[dict]:
    if not csids or not is_available():
        return []
    data = _post(
        "records/batch",
        {"recordIds": csids[:10], "fields": _DETAIL_FIELDS},
    )
    if not data or "records" not in data:
        return []
    return [
        {
            "csid":              rec.get("id"),
            "common_name":       rec.get("commonName"),
            "molecular_formula": rec.get("formula"),
            "molecular_weight":  _to_float(rec.get("molecularWeight")),
            "inchi":             rec.get("inchi"),
            "inchikey":          rec.get("inchiKey"),
        }
        for rec in data["records"]
    ]


# ── Physicochemical properties ─────────────────────────────────────────────────

def get_experimental_properties(csid: int) -> dict:
    """
    Returns melting_point, boiling_point, dehydration_temp, density,
    solubility, solubility_other, appearance from ChemSpider external references.
    Source priority: PhysProp > NIST > Alfa Aesar > Sigma-Aldrich > Acros.
    Raw strings are returned — normalisation is handled by data_fusion.
    """
    result: dict[str, str | None] = {k: None for k in _PROP_ALIASES}
    if not is_available():
        return result

    data = _get(
        f"records/{csid}/externalreferences",
        params={"datasources": _PHYS_DATASOURCES},
    )
    if not data:
        return result

    candidates: dict[str, list[tuple[int, str]]] = {k: [] for k in _PROP_ALIASES}

    for ref in data.get("externalReferences", []):
        prop_name  = (ref.get("propertyName") or "").strip()
        prop_value = (ref.get("value") or "").strip()
        source     = (ref.get("source") or "").strip()
        if not prop_name or not prop_value:
            continue
        priority = _SOURCE_PRIORITY.get(source, 99)
        for field, aliases in _PROP_ALIASES.items():
            if any(alias.lower() == prop_name.lower() for alias in aliases):
                candidates[field].append((priority, prop_value[:300]))
                break

    from services.pubchem_service import _SOL_KW_RE

    for field, cands in candidates.items():
        if not cands:
            continue
        best_value = sorted(cands, key=lambda x: x[0])[0][1]
        # No Kelvin conversion — normalisation is handled by data_fusion via property_parser.
        if field == "appearance":
            best_value = _SOL_KW_RE.sub("", best_value).strip(" ;,")
            if not best_value:
                continue  # only solubility text; discard
        result[field] = best_value

    # Return solubility and solubility_other separately — fusion handles combination
    return result


# ── CAS lookup ────────────────────────────────────────────────────────────────

def get_cas_number(csid: int) -> str | None:
    if not is_available():
        return None
    data = _get(f"records/{csid}/externalreferences",
                params={"datasources": "CAS Registry Numbers"})
    if not data:
        return None
    for ref in data.get("externalReferences", []):
        val = str(ref.get("value", "")).strip()
        if _CAS_RE.match(val):
            return val
    return None


# ── IUPAC name ────────────────────────────────────────────────────────────────

def get_iupac_name(csid: int) -> str | None:
    if not is_available():
        return None
    data = _get(f"records/{csid}/externalreferences",
                params={"datasources": "IUPAC"})
    if not data:
        return None
    refs = data.get("externalReferences", [])
    return refs[0].get("value") if refs else None


# ── Synonyms ──────────────────────────────────────────────────────────────────

def get_synonyms(csid: int) -> list[str]:
    if not is_available():
        return []
    data = _get(f"records/{csid}/synonyms")
    if not data:
        return []
    return [s.get("name", "") for s in data.get("synonyms", []) if s.get("name")]


# ── Utility ───────────────────────────────────────────────────────────────────

def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
