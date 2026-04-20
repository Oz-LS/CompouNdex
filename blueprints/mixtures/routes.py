"""
Mixtures blueprint — REST endpoints.

GET  /mixtures/<int:mix_id>              → render card template
GET  /mixtures/api/<int:mix_id>          → JSON mixture dict
POST /mixtures/api/create               → create mixture, return {status, mix_id}
POST /mixtures/api/<int:mix_id>/inventory → add InventoryItem for this mixture
DELETE /mixtures/api/<int:mix_id>        → delete mixture
"""
from flask import render_template, jsonify, request, redirect, url_for
from extensions import db
from models.mixture import Mixture
from models.inventory_item import InventoryItem
from services import mixture_service
from . import mixtures_bp


# ── Page ──────────────────────────────────────────────────────────────────────

@mixtures_bp.route("/<int:mix_id>", methods=["GET"])
def card(mix_id: int):
    mixture = db.session.get(Mixture, mix_id)
    if not mixture:
        return redirect(url_for("search.index"))
    return render_template("mixtures/card.html", active="search", mix_id=mix_id)


# ── API — get ─────────────────────────────────────────────────────────────────

@mixtures_bp.route("/api/<int:mix_id>", methods=["GET"])
def api_get(mix_id: int):
    mixture = db.session.get(Mixture, mix_id)
    if not mixture:
        return jsonify({"status": "error", "message": "Mixture not found."}), 404
    return jsonify({"status": "ok", "result": mixture_service.to_dict(mixture)})


# ── API — create ──────────────────────────────────────────────────────────────

@mixtures_bp.route("/api/create", methods=["POST"])
def api_create():
    data = request.get_json(force=True) or {}
    mixture, errors = mixture_service.create(data)
    if errors:
        return jsonify({"status": "error", "errors": errors}), 400
    return jsonify({"status": "ok", "mix_id": mixture.id}), 201


# ── API — add to inventory ────────────────────────────────────────────────────

@mixtures_bp.route("/api/<int:mix_id>/inventory", methods=["POST"])
def api_add_inventory(mix_id: int):
    mixture = db.session.get(Mixture, mix_id)
    if not mixture:
        return jsonify({"status": "error", "message": "Mixture not found."}), 404

    data = request.get_json(force=True) or {}
    num_containers = max(1, int(data.get("num_containers", 1)))
    notes = (data.get("notes") or "").strip() or None
    location = (data.get("location") or "cabinet_1").strip()

    # Derive quantity from total solvent volume
    from services.mixture_service import _total_volume_L
    solvents = [c for c in mixture.components if c.is_solvent]
    vol_L = _total_volume_L(solvents)

    item = InventoryItem(
        mixture_id     = mix_id,
        reagent_id     = None,
        location       = location,
        reagent_type   = "homemade",
        quantity       = round(vol_L, 6) if vol_L else 1.0,
        quantity_unit  = "L" if vol_L else "units",
        num_containers = num_containers,
        notes          = notes,
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({"status": "ok", "item": item.to_dict()}), 201


# ── API — delete ──────────────────────────────────────────────────────────────

@mixtures_bp.route("/api/<int:mix_id>", methods=["DELETE"])
def api_delete(mix_id: int):
    mixture = db.session.get(Mixture, mix_id)
    if not mixture:
        return jsonify({"status": "error", "message": "Mixture not found."}), 404
    if mixture.inventory_items:
        return jsonify({
            "status": "error",
            "message": (
                f"Cannot delete: mixture still has "
                f"{len(mixture.inventory_items)} inventory item(s). "
                "Remove them from inventory first."
            ),
        }), 409
    db.session.delete(mixture)
    db.session.commit()
    return jsonify({"status": "ok"})
