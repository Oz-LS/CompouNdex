from datetime import datetime, timezone
from extensions import db


# ── Controlled vocabulary constants ──────────────────────────────────────────

LOCATIONS = [
    ("to_buy",    "To Buy"),
    ("cabinet_1", "Cabinet 1"),
    ("cabinet_2", "Cabinet 2"),
    ("solvents",  "Solvents"),
    ("acids",     "Acids"),
    ("bases",     "Bases"),
]

REAGENT_TYPES = [
    ("bought",   "Bought"),
    ("borrowed", "Borrowed"),
    ("homemade", "Labmade"),
]

QUANTITY_UNITS = ["g", "mg", "kg", "ml", "L", "units"]

PURITY_UNITS = ["%", "M", "mM", "g/L", "ppm", "ppb", "-"]


class InventoryItem(db.Model):
    """
    One physical batch or container group in the lab.
    A single Reagent may have multiple InventoryItems (different locations,
    brands, preparation dates, etc.).
    """
    __tablename__ = "inventory_items"

    id = db.Column(db.Integer, primary_key=True)

    # ── Foreign keys ──────────────────────────────────────────────────────────
    # Exactly one of reagent_id / mixture_id must be set.
    reagent_id = db.Column(
        db.Integer, db.ForeignKey("reagents.id"), nullable=True, index=True
    )
    mixture_id = db.Column(
        db.Integer, db.ForeignKey("mixtures.id"), nullable=True, index=True
    )

    # ── Location & type ───────────────────────────────────────────────────────
    location = db.Column(db.String(50), nullable=False)          # see LOCATIONS
    reagent_type = db.Column(db.String(20), nullable=True)       # see REAGENT_TYPES
                                                                  # NULL when location is "to_buy"

    # ── Quantity ──────────────────────────────────────────────────────────────
    quantity = db.Column(db.Float, nullable=False)
    quantity_unit = db.Column(db.String(20), nullable=False)     # see QUANTITY_UNITS
    num_containers = db.Column(db.Integer, nullable=False, default=1)

    # ── Purity / concentration ────────────────────────────────────────────────
    purity_value = db.Column(db.Float, nullable=True)            # NULL means "-"
    purity_unit = db.Column(db.String(20), nullable=True)        # see PURITY_UNITS

    # ── Provenance — conditionally required depending on reagent_type ─────────
    brand = db.Column(db.String(200), nullable=True)             # required: bought, to_buy
    item_code_link = db.Column(db.String(500), nullable=True)    # required: to_buy
    borrowed_from = db.Column(db.String(200), nullable=True)     # required: borrowed
    prepared_by = db.Column(db.String(200), nullable=True)       # required: homemade
    event_date = db.Column(db.Date, nullable=True)               # borrowed/prepared date

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = db.Column(db.Text, nullable=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    reagent = db.relationship("Reagent", back_populates="inventory_items", foreign_keys=[reagent_id])
    # mixture backref is defined on Mixture.inventory_items

    # ── Helpers ───────────────────────────────────────────────────────────────
    @property
    def is_mixture(self) -> bool:
        return self.mixture_id is not None

    @property
    def display_name(self) -> str:
        """Human-readable name for inventory list."""
        if self.mixture_id and self.mixture:
            return self.mixture.display_name
        if self.reagent_id and self.reagent:
            return self.reagent.display_name
        return f"Item #{self.id}"

    @property
    def location_label(self) -> str:
        return dict(LOCATIONS).get(self.location, self.location)

    @property
    def purity_display(self) -> str:
        if self.purity_value is None or self.purity_unit == "-":
            return "—"
        return f"{self.purity_value} {self.purity_unit}"

    @property
    def quantity_display(self) -> str:
        return f"{self.quantity} {self.quantity_unit}"

    def to_dict(self) -> dict:
        """Serialise to a JSON-safe dictionary for API responses."""
        return {
            "id": self.id,
            "reagent_id": self.reagent_id,
            "mixture_id": self.mixture_id,
            "is_mixture": self.is_mixture,
            "display_name": self.display_name,
            "location": self.location,
            "location_label": self.location_label,
            "reagent_type": self.reagent_type,
            "quantity": self.quantity,
            "quantity_unit": self.quantity_unit,
            "quantity_display": self.quantity_display,
            "num_containers": self.num_containers,
            "purity_value": self.purity_value,
            "purity_unit": self.purity_unit,
            "purity_display": self.purity_display,
            "brand": self.brand,
            "item_code_link": self.item_code_link,
            "borrowed_from": self.borrowed_from,
            "prepared_by": self.prepared_by,
            "event_date": self.event_date.isoformat() if self.event_date else None,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<InventoryItem #{self.id} — reagent_id={self.reagent_id} @{self.location}>"
