from datetime import datetime, timezone
from extensions import db


SDS_SOURCES = [
    ("pubchem",     "PubChem (automatic)"),
    ("manual_url",  "Manual URL"),
    ("upload",      "Uploaded file"),
]


class SdsDocument(db.Model):
    """
    Safety Data Sheet associated with a reagent.
    A reagent may have multiple SDS entries (different suppliers, versions).
    Exactly one should have is_primary=True; the rest are archived alternatives.
    """
    __tablename__ = "sds_documents"

    id = db.Column(db.Integer, primary_key=True)

    # ── Foreign key ───────────────────────────────────────────────────────────
    reagent_id = db.Column(
        db.Integer, db.ForeignKey("reagents.id"), nullable=False, index=True
    )

    # ── Source metadata ───────────────────────────────────────────────────────
    source = db.Column(db.String(20), nullable=False)            # see SDS_SOURCES
    original_url = db.Column(db.String(1000), nullable=True)     # remote URL if applicable
    file_path = db.Column(db.String(500), nullable=True)         # relative path under static/sds/
    supplier = db.Column(db.String(200), nullable=True)

    # ── Flags ─────────────────────────────────────────────────────────────────
    is_primary = db.Column(db.Boolean, default=True, nullable=False)

    # ── Timestamps ────────────────────────────────────────────────────────────
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # ── Relationship ──────────────────────────────────────────────────────────
    reagent = db.relationship("Reagent", back_populates="sds_documents")

    # ── Helpers ───────────────────────────────────────────────────────────────
    @property
    def is_local(self) -> bool:
        """True if the SDS file is stored locally on the server."""
        return self.file_path is not None

    @property
    def display_source(self) -> str:
        return dict(SDS_SOURCES).get(self.source, self.source)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "reagent_id": self.reagent_id,
            "source": self.source,
            "display_source": self.display_source,
            "original_url": self.original_url,
            "file_path": self.file_path,
            "is_local": self.is_local,
            "supplier": self.supplier,
            "is_primary": self.is_primary,
            "uploaded_at": self.uploaded_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<SdsDocument #{self.id} — reagent_id={self.reagent_id} source={self.source}>"
