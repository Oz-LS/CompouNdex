from flask import render_template, request, jsonify
from . import search_bp


@search_bp.route("/", methods=["GET"])
def index():
    return render_template("search/index.html", active="search")


# ── CAS search ────────────────────────────────────────────────────────────────

@search_bp.route("/api/cas", methods=["GET"])
def api_search_cas():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"status": "error", "message": "Missing query parameter."}), 400

    from services import reagent_service
    result = reagent_service.search_by_cas(q)
    return jsonify(result)


# ── Name search ───────────────────────────────────────────────────────────────

@search_bp.route("/api/name", methods=["GET"])
def api_search_name():
    q         = request.args.get("q", "").strip()
    hydration = _parse_hydration(request.args.get("hydration"))
    if not q:
        return jsonify({"status": "error", "message": "Missing query parameter."}), 400

    from services import reagent_service
    result = reagent_service.search_by_name(q, hydration)
    return jsonify(result)


# ── Formula search ────────────────────────────────────────────────────────────

@search_bp.route("/api/formula", methods=["GET"])
def api_search_formula():
    q         = request.args.get("q", "").strip()
    hydration = _parse_hydration(request.args.get("hydration"))
    if not q:
        return jsonify({"status": "error", "message": "Missing query parameter."}), 400

    from services import reagent_service
    result = reagent_service.search_by_formula(q, hydration)
    return jsonify(result)


# ── Autocomplete (local DB) ───────────────────────────────────────────────────

@search_bp.route("/api/autocomplete", methods=["GET"])
def api_autocomplete():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify({"suggestions": []})

    from services import reagent_service
    suggestions = reagent_service.get_autocomplete_suggestions(q)
    return jsonify({"suggestions": suggestions})


# ── Disambiguate: return variant list for a fuzzy name ────────────────────────

@search_bp.route("/api/disambiguate", methods=["GET"])
def api_disambiguate():
    """
    Called when the frontend wants to pre-fetch variants without doing a
    full search (e.g. on modal open).  Delegates to the name search with
    the expectation that it returns 'ambiguous'.
    """
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"status": "error", "message": "Missing query parameter."}), 400

    from services import reagent_service
    result = reagent_service.search_by_name(q)

    # If the search already resolved to a single result, still return it
    return jsonify(result)


# ── Private helpers ───────────────────────────────────────────────────────────

def _parse_hydration(value: str | None) -> float | None:
    if not value:
        return None
    try:
        v = float(value)
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None
