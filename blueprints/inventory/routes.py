from flask import render_template, request, jsonify
from extensions import db
from models import InventoryItem, Reagent
from models.mixture import Mixture
from models.inventory_item import LOCATIONS, QUANTITY_UNITS, PURITY_UNITS
from . import inventory_bp


# ── Page ──────────────────────────────────────────────────────────────────────

@inventory_bp.route("/", methods=["GET"])
def index():
    location_filter = request.args.get("location", "all")
    search_query    = request.args.get("q", "").strip()

    # outerjoin so mixture items (reagent_id IS NULL) are included
    query = (
        db.session.query(InventoryItem)
        .outerjoin(Reagent, InventoryItem.reagent_id == Reagent.id)
        .outerjoin(Mixture, InventoryItem.mixture_id == Mixture.id)
        .order_by(InventoryItem.location, Reagent.stock_name, Mixture.name)
    )
    if location_filter and location_filter != "all":
        query = query.filter(InventoryItem.location == location_filter)
    if search_query:
        like = f"%{search_query}%"
        query = query.filter(
            db.or_(
                Reagent.cas_number.ilike(like),
                Reagent.stock_name.ilike(like),
                Reagent.iupac_name.ilike(like),
                Reagent.molecular_formula.ilike(like),
                Mixture.name.ilike(like),
            )
        )
    items = query.all()

    return render_template(
        "inventory/index.html",
        active="inventory",
        items=items,
        locations=LOCATIONS,
        location_filter=location_filter,
        search_query=search_query,
    )


# ── API — list ─────────────────────────────────────────────────────────────────

@inventory_bp.route("/api/items", methods=["GET"])
def api_list():
    location_filter = request.args.get("location", "all")
    q = request.args.get("q", "").strip()
    query = (
        db.session.query(InventoryItem)
        .outerjoin(Reagent, InventoryItem.reagent_id == Reagent.id)
        .outerjoin(Mixture, InventoryItem.mixture_id == Mixture.id)
    )
    if location_filter and location_filter != "all":
        query = query.filter(InventoryItem.location == location_filter)
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Reagent.cas_number.ilike(like),
                Reagent.stock_name.ilike(like),
                Reagent.molecular_formula.ilike(like),
                Mixture.name.ilike(like),
            )
        )
    items = query.order_by(InventoryItem.location, Reagent.stock_name, Mixture.name).all()
    return jsonify({"items": [i.to_dict() for i in items]})


# ── API — update ───────────────────────────────────────────────────────────────

@inventory_bp.route("/api/items/<int:item_id>", methods=["PATCH"])
def api_update(item_id):
    item = db.session.get(InventoryItem, item_id)
    if not item:
        return jsonify({"status": "error", "message": "Item not found."}), 404

    data = request.get_json(force=True)
    updatable = [
        "location", "reagent_type", "quantity", "quantity_unit",
        "num_containers", "purity_value", "purity_unit",
        "brand", "item_code_link", "borrowed_from", "prepared_by", "notes",
    ]
    for field in updatable:
        if field in data:
            setattr(item, field, data[field] if data[field] != "" else None)

    if "event_date" in data:
        item.event_date = _parse_date(data["event_date"])

    db.session.commit()
    return jsonify({"status": "ok", "item": item.to_dict()})


# ── API — delete ───────────────────────────────────────────────────────────────

@inventory_bp.route("/api/items/<int:item_id>", methods=["DELETE"])
def api_delete(item_id):
    item = db.session.get(InventoryItem, item_id)
    if not item:
        return jsonify({"status": "error", "message": "Item not found."}), 404
    db.session.delete(item)
    db.session.commit()
    return jsonify({"status": "ok"})


# ── Private helpers ────────────────────────────────────────────────────────────

def _parse_date(value):
    if not value:
        return None
    from datetime import date
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


# ── CSV export ─────────────────────────────────────────────────────────────────

@inventory_bp.route("/export/csv")
def export_csv():
    """
    Download the entire inventory (current filter applied) as a CSV file.
    """
    import csv
    import io as _io
    from flask import make_response

    location_filter = request.args.get("location", "all")
    q = request.args.get("q", "").strip()

    query = (
        db.session.query(InventoryItem)
        .outerjoin(Reagent, InventoryItem.reagent_id == Reagent.id)
        .outerjoin(Mixture, InventoryItem.mixture_id == Mixture.id)
    )
    if location_filter and location_filter != "all":
        query = query.filter(InventoryItem.location == location_filter)
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Reagent.cas_number.ilike(like),
                Reagent.stock_name.ilike(like),
                Reagent.molecular_formula.ilike(like),
                Mixture.name.ilike(like),
            )
        )
    items = query.order_by(InventoryItem.location, Reagent.stock_name, Mixture.name).all()

    show_location = (not location_filter) or location_filter == "all"

    buf = _io.StringIO()
    writer = csv.writer(buf)
    header = ["Name", "IUPAC Name", "Formula", "CAS", "EC"]
    if show_location:
        header.append("Location")
    header += [
        "Reagent Type",
        "Quantity", "Num Containers",
        "Concentration",
        "Brand", "Item Code/Link",
        "Borrowed From", "Prepared By", "Date",
        "Notes",
    ]
    writer.writerow(header)
    for item in items:
        r = item.reagent
        row = [
            item.display_name,
            r.iupac_name if r else "",
            r.molecular_formula if r else "",
            r.cas_number if r else "",
            r.ec_number if r else "",
        ]
        if show_location:
            row.append(item.location_label)
        qty_str = f"{item.quantity} {item.quantity_unit}" if item.quantity is not None else ""
        conc_str = (f"{item.purity_value} {item.purity_unit}"
                    if item.purity_value is not None and item.purity_unit and item.purity_unit != "-"
                    else "")
        row += [
            item.reagent_type or "",
            qty_str,
            item.num_containers,
            conc_str,
            item.brand or "",
            item.item_code_link or "",
            item.borrowed_from or "",
            item.prepared_by or "",
            item.event_date.isoformat() if item.event_date else "",
            item.notes or "",
        ]
        writer.writerow(row)

    resp = make_response(buf.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = "attachment; filename=inventory.csv"
    return resp
