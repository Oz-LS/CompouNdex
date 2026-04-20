"""
Reagent service — orchestrates all search and data-fetch operations.

Data sourcing strategy:
  PRIMARY   — ChemSpider (when CHEMSPIDER_API_KEY is set):
                names, formula, physicochemical properties.
  SECONDARY — PubChem:
                GHS safety data, EC number, SDS URL, gap-fill.
  TERTIARY  — Wikidata:
                additional numeric property values for fusion.

  All three sources are fetched in parallel; a data_fusion layer merges
  them into the best combined result per field.

  Molar mass is calculated from the Hill formula (not fetched from APIs).

Disambiguation policy:
  - Name/formula searches ALWAYS return `ambiguous` when ≥2 distinct CAS
    numbers are found, even if one looks like a "clear" winner.
  - After a name search, related hydrated forms are automatically searched
    and included in the disambiguation list.
"""
from __future__ import annotations
import re
from concurrent.futures import ThreadPoolExecutor

from extensions import db
from models import Reagent, InventoryItem
from services import pubchem_service, chemspider_service, wikidata_service
from services.formula_utils import formula_hill_to_iupac
from services.hydration_service import (
    build_hydrated_name, build_hydrated_formula,
    resolve_hydrate, degree_to_suffix,
    HYDRATION_SUFFIXES,
)
from services.mw_calculator import calculate_mw
from services.data_fusion import fuse_properties
from services.name_normalizer import get_stock_name, classic_formula_from_hill

_CODE_LIKE = re.compile(r'^[\d\-\(\)\[\]]+$')
_EC_RE     = re.compile(r'^\d{3}-\d{3}-\d$')

# Regex that matches any known IUPAC hydration suffix at the END of a name.
# Built at import time from HYDRATION_SUFFIXES so it stays in sync automatically.
_HYDRATE_SUFFIX_RE = re.compile(
    r'\s+(?:' +
    '|'.join(re.escape(s) for s in sorted(HYDRATION_SUFFIXES.values(),
                                           key=len, reverse=True)) +
    r')$',
    re.IGNORECASE,
)

# Maximum synonyms stored per reagent
_MAX_SYNONYMS = 5

# Hydration degrees iterated by the name-based fallback in _find_hydrate_variants
# (most common forms first so early hits short-circuit the loop)
_FALLBACK_DEGREES = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 0.5, 1.5]


# ── Public search API ─────────────────────────────────────────────────────────

def search_by_cas(cas: str) -> dict:
    cas = cas.strip()
    if _EC_RE.match(cas):
        return _search_by_ec(cas)

    reagent = Reagent.query.filter_by(cas_number=cas).first()
    if reagent:
        _supplement_from_wikidata(reagent)
        return {"status": "ok", "result": reagent_to_dict(reagent)}

    if chemspider_service.is_available():
        reagent = _build_from_chemspider_cas(cas)
        if reagent:
            return {"status": "ok", "result": reagent_to_dict(reagent)}

    cid = pubchem_service.get_cid_by_cas(cas)
    if not cid:
        return {"status": "not_found",
                "message": f"No compound found for CAS {cas}."}
    reagent = _build_from_pubchem(cid, expected_cas=cas)
    if not reagent:
        return {"status": "not_found",
                "message": f"CAS {cas} found in PubChem but data could not be retrieved."}
    return {"status": "ok", "result": reagent_to_dict(reagent)}


def search_by_name(name: str, hydration: float | None = None) -> dict:
    name = name.strip()
    if hydration is not None:
        return _search_with_hydration("name", name, hydration)

    # Local cache — exact substring match
    local = _local_name_search(name)

    # Local cache — word-split fallback (handles "Vanadium oxide" → "Vanadium(IV) oxide")
    if not local:
        local = _local_name_search_words(name)

    if local:
        # Even for local hits, check for unretrieved hydrate siblings
        local_variants = [_variant_dict_from_reagent(r) for r in local]
        local_base_hills = list(dict.fromkeys(
            r.molecular_formula_hill for r in local
            if r.molecular_formula_hill and not r.is_hydrate
        ))
        extra = _find_hydrate_variants(name, {r.cas_number for r in local},
                                       base_hill_formulas=local_base_hills or None)
        all_variants = _dedup_variants(local_variants + extra)
        all_variants.sort(key=lambda v: v.get("molecular_weight") or float("inf"))
        if len(all_variants) == 1:
            reagent = Reagent.query.filter_by(
                cas_number=all_variants[0]["cas_number"]
            ).first()
            if reagent:
                _supplement_from_wikidata(reagent)
                return {"status": "ok", "result": reagent_to_dict(reagent)}
        return {"status": "ambiguous", "variants": all_variants[:10]}

    variants = []

    # ChemSpider (primary)
    if not variants and chemspider_service.is_available():
        csids = chemspider_service.search_by_name(name, max_results=10)
        if csids:
            cs_variants = _csids_to_variants(csids)
            variants.extend(cs_variants)

    # PubChem exact name search
    if not variants:
        cids = pubchem_service.get_cids_by_name(name, max_results=10)
        if cids:
            variants.extend(_cids_to_variants(cids))

    # PubChem autocomplete — expands imprecise queries like "vanadium oxide"
    # into specific names ("vanadium dioxide", "vanadium pentoxide", …)
    if not variants:
        cids = pubchem_service.get_cids_by_autocomplete(name, max_results=10)
        if cids:
            variants.extend(_cids_to_variants(cids))

    if not variants:
        return {"status": "not_found",
                "message": f"No compound named '{name}' was found."}

    # Add hydrated forms not already in the list
    existing_cas = {v["cas_number"] for v in variants if v.get("cas_number")}
    base_hills = list(dict.fromkeys(
        v["molecular_formula_hill"] for v in variants
        if v.get("molecular_formula_hill") and not _variant_looks_like_hydrate(v)
    ))
    extra = _find_hydrate_variants(name, existing_cas,
                                   base_hill_formulas=base_hills or None)
    variants = _dedup_variants(variants + extra)
    variants.sort(key=lambda v: v.get("molecular_weight") or float("inf"))

    # Single unique result → resolve directly, no ambiguity screen
    if len(variants) == 1:
        reagent = _get_or_create_by_variant(variants[0])
        if reagent:
            return {"status": "ok", "result": reagent_to_dict(reagent)}

    return {"status": "ambiguous", "variants": variants[:10]}


def search_by_formula(formula: str, hydration: float | None = None) -> dict:
    formula = formula.strip()
    if hydration is not None:
        return _search_with_hydration("formula", formula, hydration)

    local = Reagent.query.filter(
        Reagent.molecular_formula.ilike(formula)
    ).limit(10).all()

    if len(local) == 1:
        r = local[0]
        local_hills = ([r.molecular_formula_hill]
                       if r.molecular_formula_hill and not r.is_hydrate else [])
        extra = _find_hydrate_variants(formula, {r.cas_number},
                                       base_hill_formulas=local_hills or None)
        if not extra:
            _supplement_from_wikidata(r)
            return {"status": "ok", "result": reagent_to_dict(r)}
        all_variants = _dedup_variants([_variant_dict_from_reagent(r)] + extra)
        all_variants.sort(key=lambda v: v.get("molecular_weight") or float("inf"))
        return {"status": "ambiguous", "variants": all_variants[:10]}
    if len(local) > 1:
        return {"status": "ambiguous",
                "variants": [_variant_dict_from_reagent(r) for r in local]}

    variants = []
    if chemspider_service.is_available():
        csids = chemspider_service.search_by_formula(formula, max_results=10)
        if csids:
            variants.extend(_csids_to_variants(csids))

    if not variants:
        cids = pubchem_service.get_cids_by_formula(formula, max_results=10)
        if cids:
            variants.extend(_cids_to_variants(cids))

    if not variants:
        return {"status": "not_found",
                "message": f"No compound with formula '{formula}' was found."}

    variants = _dedup_variants(variants)
    if variants:
        existing_cas = {v["cas_number"] for v in variants if v.get("cas_number")}
        base_hills = list(dict.fromkeys(
            v["molecular_formula_hill"] for v in variants
            if v.get("molecular_formula_hill") and not _variant_looks_like_hydrate(v)
        ))
        extra = _find_hydrate_variants(formula, existing_cas,
                                       base_hill_formulas=base_hills or None)
        variants = _dedup_variants(variants + extra)
        variants.sort(key=lambda v: v.get("molecular_weight") or float("inf"))

    if len(variants) == 1:
        reagent = _get_or_create_by_variant(variants[0])
        if reagent:
            return {"status": "ok", "result": reagent_to_dict(reagent)}
    return {"status": "ambiguous", "variants": variants[:10]}


def repair_hydrate_links() -> int:
    """
    One-shot repair: walk every hydrate whose parent_cas is NULL and attempt
    to fill it via _find_parent_in_db.  Returns the number of records fixed.

    Call once after a schema migration, or expose as an admin endpoint:
        from services import reagent_service
        fixed = reagent_service.repair_hydrate_links()
    """
    orphans = Reagent.query.filter_by(is_hydrate=True, parent_cas=None).all()
    fixed = 0
    for hydrate in orphans:
        parent = _find_parent_in_db(hydrate)
        if parent:
            hydrate.parent_cas = parent.cas_number
            fixed += 1
    if fixed:
        db.session.commit()
    return fixed


def get_autocomplete_suggestions(query: str, max_results: int = 8) -> list[str]:
    if len(query) < 2:
        return []
    like = f"{query}%"
    results = (
        Reagent.query
        .filter(db.or_(
            Reagent.stock_name.ilike(like),
            Reagent.iupac_name.ilike(like),
            Reagent.cas_number.ilike(like),
        ))
        .limit(max_results)
        .all()
    )
    suggestions, seen = [], set()
    for r in results:
        for name in (r.stock_name, r.iupac_name):
            if name and name.lower() not in seen:
                seen.add(name.lower())
                suggestions.append(name)
    return suggestions[:max_results]


# ── get_or_create ─────────────────────────────────────────────────────────────

def get_or_create_by_cas(cas: str) -> Reagent | None:
    reagent = Reagent.query.filter_by(cas_number=cas).first()
    if reagent:
        return reagent
    if chemspider_service.is_available():
        reagent = _build_from_chemspider_cas(cas)
        if reagent:
            return reagent
    cid = pubchem_service.get_cid_by_cas(cas)
    if cid:
        return _build_from_pubchem(cid, expected_cas=cas)
    return None


# ── Related inventory ─────────────────────────────────────────────────────────

def get_related_inventory(cas: str) -> list[dict]:
    reagent = Reagent.query.filter_by(cas_number=cas).first()
    if not reagent:
        return []
    related_cas: set[str] = {cas}
    if reagent.is_hydrate and reagent.parent_cas:
        related_cas.add(reagent.parent_cas)
        siblings = Reagent.query.filter(
            Reagent.parent_cas == reagent.parent_cas,
            Reagent.cas_number != cas,
        ).all()
        related_cas.update(s.cas_number for s in siblings)
    else:
        hydrates = Reagent.query.filter_by(parent_cas=cas).all()
        related_cas.update(h.cas_number for h in hydrates)

    from sqlalchemy.orm import contains_eager
    items = (
        db.session.query(InventoryItem)
        .join(Reagent)
        .options(contains_eager(InventoryItem.reagent))
        .filter(Reagent.cas_number.in_(related_cas))
        .order_by(Reagent.cas_number, InventoryItem.location)
        .all()
    )
    result = []
    for item in items:
        d = item.to_dict()
        d["reagent_name"]     = item.reagent.display_name
        d["reagent_cas"]      = item.reagent.cas_number
        d["is_exact_match"]   = (item.reagent.cas_number == cas)
        d["is_hydrate"]       = item.reagent.is_hydrate
        d["hydration_degree"] = item.reagent.hydration_degree
        result.append(d)
    return result


# ── EC number lookup ──────────────────────────────────────────────────────────

def _search_by_ec(ec: str) -> dict:
    """Look up a compound by its EC number (EINECS/ELINCS, format xxx-xxx-x)."""
    # 1. Local Reagent DB
    reagent = Reagent.query.filter_by(ec_number=ec).first()
    if reagent:
        _supplement_from_wikidata(reagent)
        return {"status": "ok", "result": reagent_to_dict(reagent)}
    # 2. ChemSpider — EC numbers are indexed as external references / synonyms
    if chemspider_service.is_available():
        csids = chemspider_service.search_by_name(ec, max_results=1)
        if csids:
            reagent = _build_from_chemspider_csid(csids[0])
            if reagent:
                return {"status": "ok", "result": reagent_to_dict(reagent)}
    # 3. PubChem — EC numbers appear as synonyms for many compounds
    cids = pubchem_service.get_cids_by_name(ec, max_results=1)
    if cids:
        reagent = _build_from_pubchem(cids[0])
        if reagent:
            return {"status": "ok", "result": reagent_to_dict(reagent)}
    return {"status": "not_found",
            "message": f"No compound found for EC {ec}."}


# ── Hydrate variant search ────────────────────────────────────────────────────

def _variant_looks_like_hydrate(v: dict) -> bool:
    """Heuristic: True if this variant's display name contains a hydration suffix."""
    name_lower = (v.get("display_name") or "").lower()
    return any(sfx in name_lower for sfx in HYDRATION_SUFFIXES.values())


def _find_hydrate_variants(
    name: str,
    existing_cas: set[str],
    base_hill_formulas: list[str] | None = None,
) -> list[dict]:
    """
    Discover all hydrated sibling forms of a compound.

    Primary path (when base_hill_formulas provided):
      For each anhydrous Hill formula, compute the expected Hill formula for
      every degree in HYDRATION_SUFFIXES using build_hydrated_formula, then
      search PubChem by formula in parallel.  Inorganic hydrates have
      compositionally unique formulas, so each search returns ≤1 CID.

    Fallback path (no base_hill_formulas or primary finds nothing):
      Name-based suffix iteration — tries "{name} hydrate" then specific
      IUPAC suffix names (monohydrate, dihydrate, …).
    """
    variants: list[dict] = []
    seen_cas = set(existing_cas)  # local copy we extend as we find things

    # ── Primary path: formula computation ────────────────────────────────────
    if base_hill_formulas:
        # Build the ordered-unique set of all expected hydrated Hill formulas.
        # Skip degree 0.25: integer rounding in build_hydrated_formula gives a
        # wrong atom count for quarter-hydrate.
        hydrated_formulas: list[str] = list(dict.fromkeys(
            hydrated
            for base_hill in base_hill_formulas[:3]
            for degree in sorted(HYDRATION_SUFFIXES)
            if degree != 0.25
            for hydrated in [build_hydrated_formula(base_hill, degree)]
            if hydrated
        ))

        # Parallel formula searches (5 workers)
        def _search_hill(hill: str) -> list[int]:
            return pubchem_service.get_cids_by_formula(hill, max_results=1)

        with ThreadPoolExecutor(max_workers=5) as exe:
            cid_lists = list(exe.map(_search_hill, hydrated_formulas))

        found_cids = [lst[0] for lst in cid_lists if lst]
        if found_cids:
            props_list = pubchem_service.get_properties_batch(found_cids)

            # Parallel CAS resolution (3 workers — respects PubChem rate limit)
            def _resolve(props: dict) -> dict | None:
                syns = pubchem_service.get_synonyms(props["cid"])
                cas  = pubchem_service.get_cas_from_synonyms(syns)
                if not cas or cas in seen_cas:
                    return None
                hill = props.get("molecular_formula") or ""
                return {
                    "cid":                    props["cid"],
                    "cas_number":             cas,
                    "display_name":           props.get("title") or props.get("iupac_name") or cas,
                    "molecular_formula":      formula_hill_to_iupac(hill) or hill,
                    "molecular_formula_hill": hill or None,
                    "molecular_weight":       props.get("molecular_weight"),
                }

            with ThreadPoolExecutor(max_workers=3) as exe:
                for v in exe.map(_resolve, props_list):
                    if v and v["cas_number"] not in seen_cas:
                        variants.append(v)
                        seen_cas.add(v["cas_number"])

            if variants:
                return variants

    # ── Fallback path: name-based suffix iteration ────────────────────────────
    # Generic "{name} hydrate" first (catches compounds PubChem indexes generically)
    hydrate_query = f"{name} hydrate"
    if chemspider_service.is_available():
        csids = chemspider_service.search_by_name(hydrate_query, max_results=8)
        for v in _csids_to_variants(csids):
            if v.get("cas_number") and v["cas_number"] not in seen_cas:
                variants.append(v)
                seen_cas.add(v["cas_number"])
    else:
        cids = pubchem_service.get_cids_by_name(hydrate_query, max_results=8)
        for v in _cids_to_variants(cids):
            if v.get("cas_number") and v["cas_number"] not in seen_cas:
                variants.append(v)
                seen_cas.add(v["cas_number"])

    # Specific IUPAC suffix searches for the most common degrees
    for degree in _FALLBACK_DEGREES:
        hydrated_name = build_hydrated_name(name, degree)
        if not hydrated_name:
            continue
        if chemspider_service.is_available():
            csids = chemspider_service.search_by_name(hydrated_name, max_results=2)
            for v in _csids_to_variants(csids):
                if v.get("cas_number") and v["cas_number"] not in seen_cas:
                    variants.append(v)
                    seen_cas.add(v["cas_number"])
        else:
            cids = pubchem_service.get_cids_by_name(hydrated_name, max_results=2)
            for v in _cids_to_variants(cids[:2]):
                if v.get("cas_number") and v["cas_number"] not in seen_cas:
                    variants.append(v)
                    seen_cas.add(v["cas_number"])

    return variants


# ── Parent / hydrate linking helpers ─────────────────────────────────────────

def _strip_hydration_suffix(name: str) -> str | None:
    """
    Remove a trailing IUPAC hydration suffix from a compound name.
    Returns the stripped base name, or None if no suffix is found.

    Examples:
      "copper sulfate pentahydrate"  → "copper sulfate"
      "calcium chloride dihydrate"   → "calcium chloride"
      "sodium chloride"              → None
    """
    m = _HYDRATE_SUFFIX_RE.search(name)
    return name[:m.start()].strip() if m else None


def _subtract_water(hill_formula: str, degree: float) -> str | None:
    """
    Compute the anhydrous Hill formula by subtracting n·H₂O.
    Returns None if the formula cannot be parsed or the subtraction
    yields negative element counts (inconsistent data).

    Examples:
      _subtract_water("CuH10O9S", 5.0) → "CuO4S"   (CuSO4)
      _subtract_water("ClH4NaO2", 2.0) → "ClNa"     (NaCl)
    """
    from services.hydration_service import _parse_formula, _to_hill
    elements = _parse_formula(hill_formula)
    if not elements:
        return None
    h_sub = int(2 * degree + 0.5)   # same rounding as build_hydrated_formula
    o_sub = int(degree + 0.5)
    elems = dict(elements)
    elems['H'] = elems.get('H', 0) - h_sub
    elems['O'] = elems.get('O', 0) - o_sub
    if elems.get('H', 0) < 0 or elems.get('O', 0) < 0:
        return None                  # inconsistent: degree doesn't match formula
    elems = {k: v for k, v in elems.items() if v > 0}
    return _to_hill(elems) if elems else None


def _find_parent_in_db(reagent: Reagent) -> Reagent | None:
    """
    Try to find the anhydrous parent of a hydrate using two strategies:

    A) Name stripping — remove the hydration suffix from stock_name /
       iupac_name and look up the result in the local DB.

    B) Formula subtraction — subtract n·H₂O from the Hill formula and
       search the local DB by the resulting formula.

    Returns the parent Reagent, or None if not found.
    Works regardless of how the hydrate was originally discovered
    (name search, formula search, or direct CAS lookup).
    """
    # Strategy A: name-based
    for name in filter(None, [reagent.stock_name, reagent.iupac_name]):
        base = _strip_hydration_suffix(name)
        if not base:
            continue
        candidates = [
            r for r in _local_name_search(base)
            if not r.is_hydrate and r.cas_number != reagent.cas_number
        ]
        if len(candidates) == 1:
            return candidates[0]

    # Strategy B: formula-based (catches formula-search hydrates)
    if reagent.hydration_degree and reagent.molecular_formula_hill:
        parent_hill = _subtract_water(
            reagent.molecular_formula_hill, reagent.hydration_degree
        )
        if parent_hill:
            candidate = Reagent.query.filter(
                Reagent.molecular_formula_hill.ilike(parent_hill),
                Reagent.is_hydrate == False,
            ).first()
            if candidate:
                return candidate

    return None


# ── Local starting-database builder ──────────────────────────────────────────

# ── ChemSpider builders ───────────────────────────────────────────────────────

def _build_from_chemspider_cas(cas: str) -> Reagent | None:
    csids = chemspider_service.search_by_cas(cas)
    if not csids:
        return None
    return _build_from_chemspider_csid(csids[0], expected_cas=cas)


def _build_from_chemspider_csid(csid: int,
                                 expected_cas: str | None = None) -> Reagent | None:
    details = chemspider_service.get_record_details(csid)
    if not details:
        return None

    cas = expected_cas or chemspider_service.get_cas_number(csid)
    if not cas:
        syns = chemspider_service.get_synonyms(csid)
        cas  = pubchem_service.get_cas_from_synonyms(syns)
    if not cas:
        return None

    existing = Reagent.query.filter_by(cas_number=cas).first()
    if existing:
        return existing

    common_name   = details.get("common_name")
    hill_formula  = details.get("molecular_formula") or ""
    iupac_formula = formula_hill_to_iupac(hill_formula) or None

    # Resolve PubChem CID (needed for safety data and synonyms gap-fill)
    cid = pubchem_service.get_cid_by_cas(cas)

    # Parallel fetch: all sources simultaneously
    with ThreadPoolExecutor(max_workers=8) as exe:
        f_cs_phys   = exe.submit(chemspider_service.get_experimental_properties, csid)
        f_pub_props = exe.submit(pubchem_service.get_properties, cid) if cid else None
        f_pub_phys  = exe.submit(pubchem_service.get_experimental_properties, cid) if cid else None
        f_wiki      = exe.submit(wikidata_service.get_all_by_cas, cas)
        f_safety    = exe.submit(pubchem_service.get_safety_data, cid) if cid else None
        f_pub_syns  = exe.submit(pubchem_service.get_synonyms, cid) if cid else None
        f_cs_syns   = exe.submit(chemspider_service.get_synonyms, csid)
        f_iupac_cs  = exe.submit(chemspider_service.get_iupac_name, csid)

        cs_phys   = f_cs_phys.result()
        pub_props = f_pub_props.result() if f_pub_props else {}
        pub_phys  = f_pub_phys.result()  if f_pub_phys  else {}
        wiki      = f_wiki.result()
        safety    = f_safety.result() if f_safety else {
            "h_codes": [], "p_codes": [], "pictogram_codes": [], "signal_word": None,
        }
        pub_syns  = f_pub_syns.result() if f_pub_syns else []
        cs_syns   = f_cs_syns.result()
        iupac_cs  = f_iupac_cs.result()

    # Fuse physicochemical properties from all three sources
    phys = fuse_properties({
        "chemspider": cs_phys,
        "pubchem":    pub_phys,
        "wikidata":   wiki,
    })

    # Formula / MW
    # Priority: ChemSpider → PubChem → Wikidata
    if not hill_formula and pub_props.get("molecular_formula"):
        hill_formula  = pub_props["molecular_formula"]
        iupac_formula = formula_hill_to_iupac(hill_formula) or None
    if not hill_formula and wiki.get("formula"):
        hill_formula  = wiki["formula"]
        iupac_formula = formula_hill_to_iupac(hill_formula) or None
    mw = calculate_mw(hill_formula) if hill_formula else None

    # Names and synonyms
    # IUPAC name: PubChem → ChemSpider
    iupac = pub_props.get("iupac_name") or iupac_cs
    ec    = pubchem_service.get_ec_from_synonyms(pub_syns) if pub_syns else None
    wiki_syns = [s for s in wiki.get("synonyms", []) if s]
    synonyms = pubchem_service.pick_readable_synonyms(
        cs_syns + pub_syns + wiki_syns, max_n=_MAX_SYNONYMS
    )
    # Stock name: try Stock-notation normalisation; fall back to common name
    raw_name   = common_name or wiki.get("name")
    stock      = get_stock_name(raw_name, hill_formula)
    stock_name = stock or _best_stock_name(raw_name, iupac, [])

    reagent = Reagent(
        cas_number             = cas,
        ec_number              = ec,
        chemspider_id          = str(csid),
        pubchem_cid            = str(cid) if cid else None,
        iupac_name             = iupac,
        stock_name             = stock_name,
        traditional_name       = raw_name if (stock and stock != raw_name) else None,
        synonyms               = synonyms or None,
        molecular_formula      = iupac_formula,
        molecular_formula_hill = hill_formula or None,
        molecular_weight       = mw,
        melting_point          = phys.get("melting_point"),
        boiling_point          = phys.get("boiling_point"),
        dehydration_temp       = phys.get("dehydration_temp"),
        density                = phys.get("density"),
        solubility             = phys.get("solubility"),
        appearance             = phys.get("appearance"),
        h_codes                = safety["h_codes"],
        p_codes                = safety["p_codes"],
        pictogram_codes        = safety["pictogram_codes"],
        signal_word            = safety["signal_word"],
        is_hydrate             = False,
    )
    db.session.add(reagent)
    db.session.commit()
    _auto_detect_hydrate(reagent)   # fills is_hydrate / hydration_degree from name/formula
    _try_link_parent(reagent)       # fills parent_cas if parent already cached
    _try_link_children(reagent)     # retroactively links orphaned hydrates to this parent
    _try_sds(reagent)
    return reagent


def _build_from_pubchem(cid: int, expected_cas: str | None = None) -> Reagent | None:
    props    = pubchem_service.get_properties(cid)
    synonyms_raw = pubchem_service.get_synonyms(cid)
    cas      = expected_cas or pubchem_service.get_cas_from_synonyms(synonyms_raw)
    if not cas:
        return None

    existing = Reagent.query.filter_by(cas_number=cas).first()
    if existing:
        return existing

    ec   = pubchem_service.get_ec_from_synonyms(synonyms_raw)

    hill_formula  = props.get("molecular_formula") or ""
    iupac_formula = formula_hill_to_iupac(hill_formula) or None

    # Parallel fetch: PubChem props + Wikidata + safety
    with ThreadPoolExecutor(max_workers=3) as exe:
        f_pub_phys = exe.submit(pubchem_service.get_experimental_properties, cid)
        f_wiki     = exe.submit(wikidata_service.get_all_by_cas, cas)
        f_safety   = exe.submit(pubchem_service.get_safety_data, cid)

        pub_phys = f_pub_phys.result()
        wiki     = f_wiki.result()
        safety   = f_safety.result()

    # Fuse physicochemical properties from available sources (no ChemSpider here)
    phys = fuse_properties({
        "pubchem":  pub_phys,
        "wikidata": wiki,
    })

    # Formula / MW: PubChem → Wikidata fallback
    if not hill_formula and wiki.get("formula"):
        hill_formula  = wiki["formula"]
        iupac_formula = formula_hill_to_iupac(hill_formula) or None
    mw = calculate_mw(hill_formula) if hill_formula else None

    wiki_syns = [s for s in wiki.get("synonyms", []) if s]
    synonyms  = pubchem_service.pick_readable_synonyms(
        synonyms_raw + wiki_syns, max_n=_MAX_SYNONYMS
    )
    # Stock name: try Stock-notation normalisation; fall back to API title
    raw_name   = props.get("title") or wiki.get("name")
    stock      = get_stock_name(raw_name, hill_formula)
    stock_name = stock or _best_stock_name(raw_name, props.get("iupac_name"), synonyms_raw)

    reagent = Reagent(
        cas_number             = cas,
        ec_number              = ec,
        pubchem_cid            = str(cid),
        iupac_name             = props.get("iupac_name"),
        stock_name             = stock_name,
        traditional_name       = raw_name if (stock and stock != raw_name) else None,
        synonyms               = synonyms or None,
        molecular_formula      = iupac_formula,
        molecular_formula_hill = hill_formula or None,
        molecular_weight       = mw,
        melting_point          = phys.get("melting_point"),
        boiling_point          = phys.get("boiling_point"),
        dehydration_temp       = phys.get("dehydration_temp"),
        density                = phys.get("density"),
        solubility             = phys.get("solubility"),
        appearance             = phys.get("appearance"),
        h_codes                = safety["h_codes"],
        p_codes                = safety["p_codes"],
        pictogram_codes        = safety["pictogram_codes"],
        signal_word            = safety["signal_word"],
        is_hydrate             = False,
    )
    db.session.add(reagent)
    db.session.commit()
    _auto_detect_hydrate(reagent)
    _try_link_parent(reagent)
    _try_link_children(reagent)
    _try_sds(reagent)
    return reagent


# ── Variant helpers ───────────────────────────────────────────────────────────

def _csids_to_variants(csids: list[int]) -> list[dict]:
    """Convert a list of CSIDs to variant dicts for disambiguation."""
    variants = []
    batch = chemspider_service.get_record_details_batch(csids[:10])
    for det in batch:
        csid = det.get("csid")
        if not csid:
            continue
        cas = chemspider_service.get_cas_number(csid)
        if not cas:
            # Use ChemSpider's own /filter/inchikey endpoint
            inchikey = det.get("inchikey")
            if inchikey:
                cs_csids = chemspider_service.filter_by_inchikey(inchikey)
                if cs_csids:
                    cas = chemspider_service.get_cas_number(cs_csids[0])
            # Fallback to PubChem if still not found
            if not cas and inchikey:
                pc_cid = pubchem_service.get_cid_by_inchikey(inchikey)
                if pc_cid:
                    pub_syns = pubchem_service.get_synonyms(pc_cid)
                    cas = pubchem_service.get_cas_from_synonyms(pub_syns)
        if not cas:
            continue
        hill     = det.get("molecular_formula") or ""
        api_name = det.get("common_name") or cas
        stock    = get_stock_name(api_name, hill or None)
        variants.append({
            "csid":              csid,
            "cas_number":        cas,
            "display_name":      stock or api_name,
            "traditional_name":  api_name if (stock and stock != api_name) else None,
            "iupac_name":        None,
            "molecular_formula": formula_hill_to_iupac(hill) or hill,
            "molecular_formula_hill": hill or None,
            "molecular_weight":  det.get("molecular_weight"),
        })
    return variants


def _cids_to_variants(cids: list[int]) -> list[dict]:
    """Convert a list of PubChem CIDs to variant dicts."""
    props_list = pubchem_service.get_properties_batch(cids)
    variants = []
    for props in props_list:
        cid = props.get("cid")
        if not cid:
            continue
        syns = pubchem_service.get_synonyms(cid)
        cas  = pubchem_service.get_cas_from_synonyms(syns)
        if not cas:
            continue
        hill     = props.get("molecular_formula") or ""
        api_name = props.get("title") or props.get("iupac_name") or cas
        stock    = get_stock_name(api_name, hill or None)
        variants.append({
            "cid":               cid,
            "cas_number":        cas,
            "display_name":      stock or api_name,
            "traditional_name":  api_name if (stock and stock != api_name) else None,
            "iupac_name":        props.get("iupac_name"),
            "molecular_formula": formula_hill_to_iupac(hill) or hill,
            "molecular_formula_hill": hill or None,
            "molecular_weight":  props.get("molecular_weight"),
        })
    return variants


def _dedup_variants(variants: list[dict]) -> list[dict]:
    """Remove duplicates by CAS number, preserving order."""
    seen, result = set(), []
    for v in variants:
        cas = v.get("cas_number")
        if cas and cas not in seen:
            seen.add(cas)
            result.append(v)
    return result


def _variant_dict_from_reagent(r: Reagent) -> dict:
    return {
        "id":                     r.id,
        "cas_number":             r.cas_number,
        "display_name":           r.display_name,
        "traditional_name":       r.traditional_name,
        "iupac_name":             r.iupac_name,
        "molecular_formula":      r.molecular_formula,
        "molecular_formula_hill": r.molecular_formula_hill,
        "molecular_weight":       r.molecular_weight,
    }


def _get_or_create_by_variant(variant: dict) -> Reagent | None:
    cas = variant.get("cas_number")
    if not cas:
        return None
    existing = Reagent.query.filter_by(cas_number=cas).first()
    if existing:
        return existing
    csid = variant.get("csid")
    if csid and chemspider_service.is_available():
        return _build_from_chemspider_csid(csid, expected_cas=cas)
    cid = variant.get("cid")
    if not cid:
        cid = pubchem_service.get_cid_by_cas(cas)
    if cid:
        return _build_from_pubchem(cid, expected_cas=cas)
    return None


# ── get_or_create helpers ─────────────────────────────────────────────────────

def _get_or_create_by_csid(csid: int) -> Reagent | None:
    existing = Reagent.query.filter_by(chemspider_id=str(csid)).first()
    if existing:
        return existing
    return _build_from_chemspider_csid(csid)


def _get_or_create_by_pubchem_cid(cid: int) -> Reagent | None:
    existing = Reagent.query.filter_by(pubchem_cid=str(cid)).first()
    if existing:
        return existing
    return _build_from_pubchem(cid)


# ── Hydration resolution ──────────────────────────────────────────────────────

def _search_with_hydration(search_type: str, query: str, degree: float) -> dict:
    suffix = degree_to_suffix(degree)

    result = {"status": "not_found", "cid": None, "message": f"No compound found for degree {degree}."}

    if search_type == "name":
        # Name-based search only when a known IUPAC suffix exists
        hydrated_name = build_hydrated_name(query, degree)
        if hydrated_name:
            if chemspider_service.is_available():
                csids = chemspider_service.search_by_name(hydrated_name, max_results=3)
                if csids:
                    reagent = _get_or_create_by_csid(csids[0])
                    if reagent:
                        _mark_hydrate(reagent, degree, query, search_type)
                        return {"status": "ok", "result": reagent_to_dict(reagent)}

            cids = pubchem_service.get_cids_by_name(hydrated_name, max_results=3)
            if cids:
                reagent = _get_or_create_by_pubchem_cid(cids[0])
                if reagent:
                    _mark_hydrate(reagent, degree, query, search_type)
                    return {"status": "ok", "result": reagent_to_dict(reagent)}

        base_cids = pubchem_service.get_cids_by_name(query, max_results=1)
        result    = resolve_hydrate(query, base_cids[0] if base_cids else None, degree)

    else:
        hill = build_hydrated_formula(query, degree)
        if hill:
            cids = pubchem_service.get_cids_by_formula(hill, max_results=3)
            if cids:
                reagent = _get_or_create_by_pubchem_cid(cids[0])
                if reagent:
                    _mark_hydrate(reagent, degree, query, search_type)
                    return {"status": "ok", "result": reagent_to_dict(reagent)}

        n_str = str(int(degree)) if degree == int(degree) else str(degree)
        cids = pubchem_service.get_cids_by_formula(f"{query}.{n_str}H2O", max_results=3)
        if cids:
            reagent = _get_or_create_by_pubchem_cid(cids[0])
            if reagent:
                _mark_hydrate(reagent, degree, query, search_type)
                return {"status": "ok", "result": reagent_to_dict(reagent)}

        if chemspider_service.is_available() and hill:
            csids = chemspider_service.search_by_formula(hill, max_results=3)
            if csids:
                reagent = _get_or_create_by_csid(csids[0])
                if reagent:
                    _mark_hydrate(reagent, degree, query, search_type)
                    return {"status": "ok", "result": reagent_to_dict(reagent)}

        base_cids = pubchem_service.get_cids_by_formula(query, max_results=1)
        result    = resolve_hydrate(query, base_cids[0] if base_cids else None, degree)

    if result["status"] == "ok" and result["cid"]:
        reagent = _get_or_create_by_pubchem_cid(result["cid"])
        if reagent:
            _mark_hydrate(reagent, degree, query, search_type)
            return {"status": "ok", "result": reagent_to_dict(reagent)}

    return {"status": "hydration_not_found", "message": result["message"]}


def _mark_hydrate(reagent: Reagent, degree: float,
                  base_query: str, search_type: str = "name") -> None:
    if reagent.is_hydrate:
        return
    reagent.is_hydrate       = True
    reagent.hydration_degree = degree

    # Strategy 1: use the multi-method lookup (works for both name and formula searches)
    parent = _find_parent_in_db(reagent)
    if parent:
        reagent.parent_cas = parent.cas_number
    elif search_type == "name":
        # Strategy 2: fallback — the parent may not be cached yet, but the
        # base_query is the exact name the user typed; try a direct DB lookup.
        base = _local_name_search(base_query)
        if len(base) == 1 and not base[0].is_hydrate:
            reagent.parent_cas = base[0].cas_number

    db.session.commit()


# ── Local DB helpers ──────────────────────────────────────────────────────────

def _local_name_search(name: str) -> list[Reagent]:
    like = f"%{name}%"
    return (
        Reagent.query
        .filter(db.or_(
            Reagent.stock_name.ilike(like),
            Reagent.iupac_name.ilike(like),
            Reagent.retained_name.ilike(like),
        ))
        .limit(10)
        .all()
    )


def _local_name_search_words(name: str) -> list[Reagent]:
    """
    Fuzzy local search: splits name into individual words and requires ALL of
    them to appear (in any order, case-insensitive) somewhere in stock_name,
    iupac_name, or retained_name.

    "Vanadium oxide"  → words ["vanadium","oxide"]
      → matches "Vanadium(IV) oxide", "Vanadium(V) oxide", …
    "iron chloride"   → matches "Iron(II) chloride", "Iron(III) chloride", …

    Single-word queries are left to _local_name_search; this helper is only
    called when the exact-substring search finds nothing.
    """
    words = [w for w in name.strip().split() if len(w) >= 2]
    if len(words) < 2:
        return []

    # Build AND of OR-per-word conditions
    conditions = []
    for word in words:
        like = f"%{word}%"
        conditions.append(db.or_(
            Reagent.stock_name.ilike(like),
            Reagent.iupac_name.ilike(like),
            Reagent.retained_name.ilike(like),
        ))

    return (
        Reagent.query
        .filter(db.and_(*conditions))
        .limit(10)
        .all()
    )


def _best_stock_name(preferred: str | None, iupac: str | None,
                     synonyms: list[str]) -> str | None:
    if preferred:
        return preferred
    for syn in synonyms[:20]:
        if not _CODE_LIKE.match(syn) and len(syn) < 80:
            return syn
    return iupac


def _try_link_parent(reagent: Reagent) -> None:
    """
    If ``reagent`` is a hydrate with no parent_cas set, try to fill it
    using _find_parent_in_db.  Safe to call unconditionally after any save.
    """
    if not reagent.is_hydrate or reagent.parent_cas:
        return
    parent = _find_parent_in_db(reagent)
    if parent:
        reagent.parent_cas = parent.cas_number
        db.session.commit()


def _try_link_children(reagent: Reagent) -> None:
    """
    After saving a non-hydrate, scan every orphaned hydrate already in the
    DB and fill their parent_cas if they belong to this reagent.

    This closes the reverse gap: hydrates cached before their parent had no
    way to know the parent CAS until the parent was eventually searched.
    """
    if reagent.is_hydrate:
        return
    orphans = Reagent.query.filter_by(is_hydrate=True, parent_cas=None).all()
    changed = False
    for hydrate in orphans:
        parent = _find_parent_in_db(hydrate)
        if parent and parent.cas_number == reagent.cas_number:
            hydrate.parent_cas = reagent.cas_number
            changed = True
    if changed:
        db.session.commit()


def _auto_detect_hydrate(reagent: Reagent) -> None:
    """
    Detect hydration from the compound name or Hill formula when a reagent
    was fetched via a direct CAS lookup (which bypasses _mark_hydrate).

    Sets is_hydrate and hydration_degree, then commits if anything changed.
    A subsequent call to _try_link_parent will attempt to fill parent_cas.
    """
    if reagent.is_hydrate:
        return
    name = (reagent.stock_name or reagent.iupac_name or "").lower()
    # Sort longest suffix first so "pentahydrate" is matched before "hydrate"
    for degree, suffix in sorted(HYDRATION_SUFFIXES.items(),
                                  key=lambda kv: len(kv[1]), reverse=True):
        if name.endswith(suffix.lower()):
            reagent.is_hydrate       = True
            reagent.hydration_degree = degree
            db.session.commit()
            return
    # Fallback: dot-notation embedded in the Hill formula (e.g. "CuSO4·5H2O")
    hill = reagent.molecular_formula_hill or ""
    m = re.search(r'[·.](\d*(?:\.\d+)?)H2O', hill, re.IGNORECASE)
    if m:
        try:
            reagent.is_hydrate       = True
            reagent.hydration_degree = float(m.group(1)) if m.group(1) else 1.0
            db.session.commit()
        except (ValueError, TypeError):
            pass


def supplement_from_wikidata(reagent: Reagent) -> bool:
    """Public alias — called from blueprints that have a cached reagent object."""
    return _supplement_from_wikidata(reagent)


def _supplement_from_wikidata(reagent: Reagent) -> bool:
    """
    For an existing DB reagent that is missing physicochemical properties,
    fetch from Wikidata and fill in any None fields.  Also merges Wikidata
    synonyms that are not already stored.

    Also performs a lazy Stock-name normalisation pass for records created
    before the name_normalizer was introduced (no API call required for this).

    Returns True if anything was updated (triggers a DB commit).
    This is called lazily on every cached-reagent lookup so records created
    before any integration step are transparently enriched on first access.
    """
    if not reagent.cas_number:
        return False

    changed = False

    # ── Lazy Stock-name normalisation (local computation, no API call) ────────
    if reagent.traditional_name is None and reagent.stock_name:
        stock = get_stock_name(reagent.stock_name, reagent.molecular_formula_hill)
        if stock and stock != reagent.stock_name:
            reagent.traditional_name = reagent.stock_name
            reagent.stock_name = stock
            changed = True

    # ── Lazy formula backfill via PubChem (reliable; happens before early-return)
    if reagent.molecular_formula_hill is None:
        try:
            cid = reagent.pubchem_cid or pubchem_service.get_cid_by_cas(reagent.cas_number)
            if cid:
                if not reagent.pubchem_cid:
                    reagent.pubchem_cid = cid
                props = pubchem_service.get_properties(cid)
                hill  = props.get("molecular_formula") or ""
                if hill:
                    reagent.molecular_formula_hill = hill
                    reagent.molecular_formula      = formula_hill_to_iupac(hill) or None
                    changed = True
        except Exception:
            pass

    # ── Decide whether a Wikidata fetch is needed ─────────────────────────────
    _PHYS = ("melting_point", "boiling_point", "density", "solubility", "appearance")
    missing_phys = any(getattr(reagent, f) is None for f in _PHYS)
    if not missing_phys:
        if changed:
            db.session.commit()
        return changed

    try:
        wiki = wikidata_service.get_all_by_cas(reagent.cas_number)
    except Exception:
        if changed:
            db.session.commit()
        return changed

    # Fill missing physicochemical fields using single-source fusion
    phys = fuse_properties({"wikidata": wiki})
    for field in _PHYS:
        if getattr(reagent, field) is None and phys.get(field):
            setattr(reagent, field, phys[field])
            changed = True

    # Merge Wikidata synonyms (skos:altLabel) that are not already stored
    wiki_syns = [s for s in wiki.get("synonyms", []) if s]
    if wiki_syns:
        existing = list(reagent.synonyms or [])
        existing_lower = {s.lower() for s in existing}
        to_add = [s for s in wiki_syns if s.lower() not in existing_lower]
        if to_add:
            # Keep total ≤ _MAX_SYNONYMS
            combined = existing + to_add
            reagent.synonyms = combined[:_MAX_SYNONYMS]
            changed = True

    # Fill missing name / formula from Wikidata (fallback if PubChem CID absent)
    if reagent.stock_name is None and wiki.get("name"):
        reagent.stock_name = wiki["name"]
        changed = True
    if reagent.molecular_formula_hill is None and wiki.get("formula"):
        reagent.molecular_formula_hill = wiki["formula"]
        reagent.molecular_formula = formula_hill_to_iupac(wiki["formula"]) or None
        changed = True

    if changed:
        db.session.commit()
    return changed


def _try_sds(reagent: Reagent) -> None:
    try:
        from services import sds_service
        sds_service.fetch_and_store(reagent)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).debug(
            "SDS auto-fetch failed for %s: %s", reagent.cas_number, exc
        )


# ── Serialisation ─────────────────────────────────────────────────────────────
# Moved to services.reagent_serializer; re-exported here for backwards compat.
from services.reagent_serializer import (  # noqa: E402
    reagent_to_dict,
    clean_iupac as _clean_iupac,
    filter_solubility as _filter_solubility,
)
