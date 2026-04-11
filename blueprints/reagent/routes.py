"""
Reagent Card blueprint.
Accessible from a search result or by clicking a CAS link in the inventory.
The GET /api/<cas> endpoint now triggers an external API fetch if the
reagent is not yet cached locally.
"""
import os
from flask import render_template, request, jsonify, current_app, abort
from werkzeug.utils import secure_filename
from extensions import db
from models import Reagent, InventoryItem, SdsDocument
from . import reagent_bp

ALLOWED_SDS_EXTENSIONS = {".pdf"}


def _allowed_sds(filename: str) -> bool:
    return os.path.splitext(filename)[1].lower() in ALLOWED_SDS_EXTENSIONS


# ── Page route ────────────────────────────────────────────────────────────────

@reagent_bp.route("/<cas>", methods=["GET"])
def card(cas):
    reagent = Reagent.query.filter_by(cas_number=cas).first()
    return render_template("reagent/card.html", active="", reagent=reagent, cas=cas)


# ── Reagent data API ──────────────────────────────────────────────────────────

@reagent_bp.route("/api/<cas>", methods=["GET"])
def api_get(cas):
    """
    Return the full reagent card data.
    If the reagent is not in the local DB, fetch it from PubChem/ChemSpider,
    save it, and return the result.  This means the first request for a new
    CAS number may take several seconds while the external APIs are queried.
    """
    from services import reagent_service

    reagent = Reagent.query.filter_by(cas_number=cas).first()
    if not reagent:
        # Trigger external fetch
        reagent = reagent_service.get_or_create_by_cas(cas)
        if not reagent:
            return jsonify({
                "status":  "not_found",
                "message": (
                    f"CAS {cas} could not be found in PubChem. "
                    "Verify the number or search by name."
                ),
            }), 404
    else:
        # Lazily backfill any fields that were missing when the record was
        # first saved (formula, Stock name, physical properties from Wikidata).
        reagent_service.supplement_from_wikidata(reagent)

    return jsonify({
        "status":  "ok",
        "reagent": reagent_service.reagent_to_dict(reagent),
    })


# ── Inventory sub-resource ────────────────────────────────────────────────────

@reagent_bp.route("/api/<cas>/inventory", methods=["GET"])
def api_inventory(cas):
    reagent = Reagent.query.filter_by(cas_number=cas).first()
    if not reagent:
        return jsonify({"items": []})
    items = (
        InventoryItem.query
        .filter_by(reagent_id=reagent.id)
        .order_by(InventoryItem.location)
        .all()
    )
    return jsonify({"items": [i.to_dict() for i in items]})


@reagent_bp.route("/api/<cas>/related_inventory", methods=["GET"])
def api_related_inventory(cas):
    """Return inventory items for this compound and all related forms."""
    from services import reagent_service
    items = reagent_service.get_related_inventory(cas)
    return jsonify({"items": items})

@reagent_bp.route("/api/<cas>/inventory", methods=["POST"])
def api_inventory_add(cas):
    reagent = Reagent.query.filter_by(cas_number=cas).first()
    if not reagent:
        return jsonify({"status": "error", "message": "Reagent not found."}), 404

    data   = request.get_json(force=True)
    errors = _validate_inventory_payload(data)
    if errors:
        return jsonify({"status": "error", "errors": errors}), 422

    purity_val = None
    if data.get("purity_value") not in (None, "", "-"):
        try:
            purity_val = float(data["purity_value"])
        except (ValueError, TypeError):
            purity_val = None

    new_qty        = float(data["quantity"])
    new_unit       = data["quantity_unit"]
    new_containers = int(data.get("num_containers", 1))
    new_location   = data["location"]
    new_rtype      = data.get("reagent_type") or None
    new_brand      = data.get("brand") or None
    new_punit      = data.get("purity_unit", "-")
    new_borrowed   = data.get("borrowed_from") or None
    new_prepared   = data.get("prepared_by") or None
    new_notes      = data.get("notes") or None

    # ── Duplicate detection ──────────────────────────────────────────────
    force_new = data.get("force_new", False)
    if not force_new:
        existing = InventoryItem.query.filter_by(
            reagent_id    = reagent.id,
            location      = new_location,
            reagent_type  = new_rtype,
            quantity       = new_qty,
            quantity_unit  = new_unit,
            purity_value   = purity_val,
            purity_unit    = new_punit,
            brand          = new_brand,
            borrowed_from  = new_borrowed,
            prepared_by    = new_prepared,
            notes          = new_notes,
        ).first()
        if existing:
            return jsonify({
                "status": "duplicate",
                "existing": existing.to_dict(),
                "message": (
                    f"An identical entry already exists in {new_location} "
                    f"with {existing.num_containers} container(s). "
                    "Merge or keep as separate entry?"
                ),
            }), 200

    item = InventoryItem(
        reagent_id     = reagent.id,
        location       = new_location,
        reagent_type   = new_rtype,
        quantity       = new_qty,
        quantity_unit  = new_unit,
        num_containers = new_containers,
        purity_value   = purity_val,
        purity_unit    = new_punit,
        brand          = new_brand,
        item_code_link = data.get("item_code_link") or None,
        borrowed_from  = new_borrowed,
        prepared_by    = new_prepared,
        event_date     = _parse_date(data.get("event_date")),
        notes          = new_notes,
    )
    db.session.add(item)
    db.session.commit()

    purity_str = (
        f", purity {item.purity_value} {item.purity_unit}"
        if item.purity_value is not None else ""
    )
    message = (
        f"Added to inventory: {item.num_containers} container(s) of "
        f"{item.quantity} {item.quantity_unit} of {reagent.display_name}"
        f"{purity_str}."
    )
    return jsonify({"status": "ok", "item": item.to_dict(), "message": message}), 201


@reagent_bp.route("/api/<cas>/inventory/<int:item_id>", methods=["PATCH"])
def api_inventory_update(cas, item_id):
    reagent = Reagent.query.filter_by(cas_number=cas).first()
    if not reagent:
        return jsonify({"status": "error", "message": "Reagent not found."}), 404

    item = db.session.get(InventoryItem, item_id)
    if not item or item.reagent_id != reagent.id:
        return jsonify({"status": "error", "message": "Item not found."}), 404

    data = request.get_json(force=True)
    updatable = [
        "location", "reagent_type", "quantity", "quantity_unit",
        "num_containers", "purity_value", "purity_unit",
        "brand", "item_code_link", "borrowed_from", "prepared_by", "notes",
    ]
    for field in updatable:
        if field not in data:
            continue
        val = data[field]
        if field == "quantity":
            if val not in (None, ""):
                setattr(item, field, float(val))
        elif field == "num_containers":
            if val not in (None, ""):
                setattr(item, field, int(val))
        elif field == "purity_value":
            if val in (None, "", "-"):
                item.purity_value = None
            else:
                try:
                    item.purity_value = float(val)
                except (ValueError, TypeError):
                    pass
        else:
            setattr(item, field, val)
    if "event_date" in data:
        item.event_date = _parse_date(data["event_date"])

    db.session.commit()
    return jsonify({"status": "ok", "item": item.to_dict()})


@reagent_bp.route("/api/<cas>/inventory/<int:item_id>", methods=["DELETE"])
def api_inventory_delete(cas, item_id):
    reagent = Reagent.query.filter_by(cas_number=cas).first()
    if not reagent:
        return jsonify({"status": "error", "message": "Reagent not found."}), 404

    item = db.session.get(InventoryItem, item_id)
    if not item or item.reagent_id != reagent.id:
        return jsonify({"status": "error", "message": "Item not found."}), 404

    db.session.delete(item)
    db.session.commit()
    return jsonify({"status": "ok"})


# ── SDS sub-resource ──────────────────────────────────────────────────────────

@reagent_bp.route("/api/<cas>/sds", methods=["GET"])
def api_sds_list(cas):
    reagent = Reagent.query.filter_by(cas_number=cas).first()
    if not reagent:
        return jsonify({"documents": []})
    return jsonify({"documents": [s.to_dict() for s in reagent.sds_documents]})


@reagent_bp.route("/api/<cas>/sds", methods=["POST"])
def api_sds_add(cas):
    reagent = Reagent.query.filter_by(cas_number=cas).first()
    if not reagent:
        return jsonify({"status": "error", "message": "Reagent not found."}), 404

    file     = request.files.get("file")
    url      = request.form.get("url", "").strip()
    supplier = request.form.get("supplier", "").strip() or None

    if not file and not url:
        return jsonify({"status": "error", "message": "Provide a file or a URL."}), 400

    file_path = None
    source    = "manual_url"

    if file:
        if not _allowed_sds(file.filename):
            return jsonify({"status": "error", "message": "Only PDF files are accepted."}), 400
        filename  = secure_filename(f"{cas}_{file.filename}")
        dest      = os.path.join(current_app.config["SDS_UPLOAD_FOLDER"], filename)
        file.save(dest)
        file_path = os.path.join("sds", filename)
        source    = "upload"

    # Demote any existing primary
    for existing in reagent.sds_documents:
        existing.is_primary = False

    sds = SdsDocument(
        reagent_id   = reagent.id,
        source       = source,
        original_url = url or None,
        file_path    = file_path,
        supplier     = supplier,
        is_primary   = True,
    )
    db.session.add(sds)
    db.session.commit()
    return jsonify({"status": "ok", "document": sds.to_dict()}), 201


# ── Private helpers ───────────────────────────────────────────────────────────

def _parse_date(value):
    if not value:
        return None
    from datetime import date
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _validate_inventory_payload(data: dict) -> dict:
    from models.inventory_item import LOCATIONS, QUANTITY_UNITS, REAGENT_TYPES
    errors = {}
    valid_locations = [loc[0] for loc in LOCATIONS]

    if not data.get("location") or data["location"] not in valid_locations:
        errors["location"] = "Please select a valid location."
    if data.get("quantity") in (None, ""):
        errors["quantity"] = "Quantity is required."
    else:
        try:
            float(data["quantity"])
        except (ValueError, TypeError):
            errors["quantity"] = "Quantity must be a number."
    if not data.get("quantity_unit") or data["quantity_unit"] not in QUANTITY_UNITS:
        errors["quantity_unit"] = "Please select a valid unit."
    if not data.get("num_containers"):
        errors["num_containers"] = "Number of containers is required."

    location = data.get("location")
    rtype    = data.get("reagent_type")
    valid_types = [t[0] for t in REAGENT_TYPES]

    if location == "to_buy":
        if not data.get("brand"):
            errors["brand"] = "Brand is required for 'To Buy' items."
    else:
        if not rtype or rtype not in valid_types:
            errors["reagent_type"] = "Please select a valid reagent type."
        if rtype == "bought" and not data.get("brand"):
            errors["brand"] = "Brand is required for bought reagents."
        elif rtype == "borrowed" and not data.get("borrowed_from"):
            errors["borrowed_from"] = "'Borrowed from' is required."
        elif rtype == "homemade" and not data.get("prepared_by"):
            errors["prepared_by"] = "'Prepared by' is required."

    return errors
