"""
Label Cart blueprint.
Cart lives in the Flask session — cleared when the browser session ends.

Each cart entry:
  entry_id, reagent_id, cas_number, display_name,
  format_size, copies, is_prepared,
  qty_display, purity_display         ← populated when added from reagent card
"""
import io
import uuid
from flask import (
    render_template, request, jsonify, session,
    send_file, current_app
)
from models import Reagent
from extensions import db
from . import labels_bp

LABEL_FORMATS = ["1kg", "500g", "100g", "20g", "1g"]
CART_KEY      = "label_cart"


def _get_cart() -> list:
    return session.get(CART_KEY, [])


def _save_cart(cart: list) -> None:
    session[CART_KEY] = cart
    session.modified  = True


# ── Page ──────────────────────────────────────────────────────────────────────

@labels_bp.route("/", methods=["GET"])
def index():
    return render_template("labels/index.html", active="labels",
                           cart=_get_cart(), formats=LABEL_FORMATS)


# ── Cart CRUD ─────────────────────────────────────────────────────────────────

@labels_bp.route("/api/cart", methods=["GET"])
def api_cart_list():
    return jsonify({"cart": _get_cart()})


@labels_bp.route("/api/cart", methods=["POST"])
def api_cart_add():
    data        = request.get_json(force=True)
    reagent_id  = data.get("reagent_id")
    mixture_id  = data.get("mixture_id")
    fmt         = data.get("format_size", "100g")
    copies      = max(1, int(data.get("copies", 1)))
    is_prepared = bool(data.get("is_prepared", False))
    qty_display = data.get("qty_display", "")
    purity_display = data.get("purity_display", "")

    if fmt not in LABEL_FORMATS:
        return jsonify({"status": "error", "message": "Invalid payload."}), 400

    cart = _get_cart()

    if mixture_id:
        from models.mixture import Mixture
        mixture = db.session.get(Mixture, int(mixture_id))
        if not mixture:
            return jsonify({"status": "error", "message": "Mixture not found."}), 404
        # Merge if same mixture + format already in cart
        existing = next(
            (e for e in cart
             if e.get("mixture_id") == int(mixture_id)
             and e["format_size"] == fmt),
            None,
        )
        if existing:
            existing["copies"] += copies
            _save_cart(cart)
            return jsonify({"status": "ok", "entry_id": existing["entry_id"],
                            "cart_count": len(cart), "merged": True})
        entry = {
            "entry_id":      str(uuid.uuid4()),
            "mixture_id":    int(mixture_id),
            "reagent_id":    None,
            "cas_number":    None,
            "display_name":  mixture.display_name,
            "format_size":   fmt,
            "copies":        copies,
            "is_prepared":   is_prepared,
            "qty_display":   qty_display,
            "purity_display": purity_display,
        }
        cart.append(entry)
        _save_cart(cart)
        return jsonify({"status": "ok", "entry_id": entry["entry_id"],
                        "cart_count": len(cart)})

    if not reagent_id:
        return jsonify({"status": "error", "message": "Invalid payload."}), 400

    reagent = db.session.get(Reagent, reagent_id)
    if not reagent:
        return jsonify({"status": "error", "message": "Reagent not found."}), 404

    # Merge if same reagent + format already in cart
    existing = next(
        (e for e in cart
         if e.get("reagent_id") == reagent_id
         and e["format_size"] == fmt),
        None,
    )
    if existing:
        existing["copies"] += copies
        _save_cart(cart)
        return jsonify({"status": "ok", "entry_id": existing["entry_id"],
                        "cart_count": len(cart), "merged": True})

    entry = {
        "entry_id":      str(uuid.uuid4()),
        "reagent_id":    reagent_id,
        "mixture_id":    None,
        "cas_number":    reagent.cas_number,
        "display_name":  reagent.display_name,
        "format_size":   fmt,
        "copies":        copies,
        "is_prepared":   is_prepared,
        "qty_display":   qty_display,
        "purity_display": purity_display,
    }
    cart.append(entry)
    _save_cart(cart)
    return jsonify({"status": "ok", "entry_id": entry["entry_id"],
                    "cart_count": len(cart)})


@labels_bp.route("/api/cart/status/<int:item_id>", methods=["GET"])
def api_cart_status(item_id):
    """Return cart entries for a specific reagent or mixture."""
    kind = request.args.get("kind", "reagent")
    key = "mixture_id" if kind == "mixture" else "reagent_id"
    cart = _get_cart()
    entries = [e for e in cart if e.get(key) == item_id]
    return jsonify({"entries": entries})


@labels_bp.route("/api/cart/<entry_id>", methods=["PATCH"])
def api_cart_update(entry_id):
    data  = request.get_json(force=True)
    cart  = _get_cart()
    entry = next((e for e in cart if e["entry_id"] == entry_id), None)
    if not entry:
        return jsonify({"status": "error", "message": "Entry not found."}), 404

    for field in ("format_size", "copies", "is_prepared",
                  "qty_display", "purity_display"):
        if field in data:
            val = data[field]
            if field == "format_size" and val not in LABEL_FORMATS:
                continue
            if field == "copies":
                val = max(1, int(val))
            entry[field] = val

    _save_cart(cart)
    return jsonify({"status": "ok", "entry": entry})


@labels_bp.route("/api/cart/<entry_id>", methods=["DELETE"])
def api_cart_remove(entry_id):
    cart = [e for e in _get_cart() if e["entry_id"] != entry_id]
    _save_cart(cart)
    return jsonify({"status": "ok", "cart_count": len(cart)})


@labels_bp.route("/api/cart/clear", methods=["POST"])
def api_cart_clear():
    _save_cart([])
    return jsonify({"status": "ok"})


# ── PDF generation ────────────────────────────────────────────────────────────

@labels_bp.route("/api/generate", methods=["POST"])
def api_generate():
    from services import reagent_service, label_service

    cart = _get_cart()
    if not cart:
        return jsonify({"status": "error", "message": "Cart is empty."}), 400

    data         = request.get_json(force=True) or {}
    selected_ids = data.get("entries")          # list of entry_ids or None
    if selected_ids:
        cart = [e for e in cart if e["entry_id"] in selected_ids]
    if not cart:
        return jsonify({"status": "error", "message": "No matching entries."}), 400

    # Build reagents_by_id map
    reagents_by_id: dict[int, dict] = {}
    for e in cart:
        rid = e.get("reagent_id")
        if not rid or rid in reagents_by_id:
            continue
        reagent = db.session.get(Reagent, rid)
        if reagent:
            reagents_by_id[rid] = reagent_service.reagent_to_dict(reagent)

    # Build mixtures_by_id map
    from models.mixture import Mixture
    from services import mixture_service
    mixtures_by_id: dict[int, dict] = {}
    for e in cart:
        mid = e.get("mixture_id")
        if not mid or mid in mixtures_by_id:
            continue
        mixture = db.session.get(Mixture, mid)
        if mixture:
            mixtures_by_id[mid] = mixture_service.to_dict(mixture)

    try:
        pdf_bytes = label_service.generate_pdf(
            cart,
            reagents_by_id,
            static_folder=current_app.static_folder,
            mixtures_by_id=mixtures_by_id,
        )
    except Exception as e:
        current_app.logger.error(f"Label PDF generation failed: {e}")
        return jsonify({"status": "error",
                        "message": f"PDF generation failed: {e}"}), 500

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name="labels.pdf",
    )
