from datetime import datetime, timezone
from extensions import db


class Reagent(db.Model):
    """
    Canonical record for a chemical compound.
    Populated on first search and served from local cache for all subsequent lookups.
    """
    __tablename__ = "reagents"

    id = db.Column(db.Integer, primary_key=True)

    # ── Identifiers ──────────────────────────────────────────────────────────
    cas_number    = db.Column(db.String(20),  unique=True, nullable=False, index=True)
    ec_number     = db.Column(db.String(20),  nullable=True)
    chemspider_id = db.Column(db.String(50),  nullable=True)
    pubchem_cid   = db.Column(db.String(50),  nullable=True)

    # ── Names ─────────────────────────────────────────────────────────────────
    iupac_name       = db.Column(db.String(500), nullable=True)
    stock_name       = db.Column(db.String(500), nullable=True)
    traditional_name = db.Column(db.String(500), nullable=True)
    retained_name    = db.Column(db.String(500), nullable=True)
    # Top synonyms (JSON list of strings, max ~15 entries)
    synonyms      = db.Column(db.JSON,        nullable=True)

    # ── Chemical data ─────────────────────────────────────────────────────────
    # molecular_formula: IUPAC/electronegativity order (converted by formula_utils)
    # molecular_formula_hill: original Hill notation as returned by the API
    molecular_formula      = db.Column(db.String(200), nullable=True)
    molecular_formula_hill = db.Column(db.String(200), nullable=True)
    molecular_weight       = db.Column(db.Float,       nullable=True)  # g/mol

    # ── Physicochemical properties ────────────────────────────────────────────
    # Stored as strings to preserve annotations like "dec.", ">", "~", etc.
    melting_point    = db.Column(db.String(100), nullable=True)
    boiling_point    = db.Column(db.String(100), nullable=True)
    dehydration_temp = db.Column(db.String(100), nullable=True)  # for hydrates
    density          = db.Column(db.String(100), nullable=True)
    solubility       = db.Column(db.String(500), nullable=True)
    appearance       = db.Column(db.String(600), nullable=True)

    # ── Safety ────────────────────────────────────────────────────────────────
    h_codes         = db.Column(db.JSON,        nullable=True)
    p_codes         = db.Column(db.JSON,        nullable=True)
    pictogram_codes = db.Column(db.JSON,        nullable=True)
    signal_word     = db.Column(db.String(20),  nullable=True)
    gestis_url      = db.Column(db.String(500), nullable=True)

    # ── Hydration ─────────────────────────────────────────────────────────────
    is_hydrate       = db.Column(db.Boolean, default=False, nullable=False)
    hydration_degree = db.Column(db.Float,   nullable=True)
    parent_cas       = db.Column(db.String(20), nullable=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    # SDS docs are tightly bound to the reagent — cascade OK.
    sds_documents = db.relationship(
        "SdsDocument", back_populates="reagent", cascade="all, delete-orphan"
    )
    # Inventory is critical lab data; do NOT cascade delete.  Deleting a
    # reagent that still has inventory items will raise an IntegrityError.
    inventory_items = db.relationship(
        "InventoryItem", back_populates="reagent", passive_deletes="all"
    )

    # ── Helpers ───────────────────────────────────────────────────────────────
    @property
    def display_name(self) -> str:
        return self.stock_name or self.iupac_name or self.retained_name or self.cas_number

    @property
    def primary_sds(self):
        return next(
            (s for s in self.sds_documents if s.is_primary),
            self.sds_documents[0] if self.sds_documents else None,
        )

    def __repr__(self) -> str:
        return f"<Reagent {self.cas_number} — {self.display_name}>"
