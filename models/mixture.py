"""
Mixture models: Mixture and MixtureComponent.

A Mixture represents a lab-prepared solution (e.g. a pH buffer) that has no
CAS number.  It is composed of one or more reagents (solutes) and one or more
solvents, each with an amount and unit.  The service layer calculates the
molar concentration of each solute and merges the GHS safety data from all
constituents.
"""
from __future__ import annotations

from datetime import datetime

from extensions import db


class MixtureComponent(db.Model):
    """One row per reagent/solvent used in a mixture."""
    __tablename__ = "mixture_components"

    id              = db.Column(db.Integer, primary_key=True)
    mixture_id      = db.Column(
        db.Integer,
        db.ForeignKey("mixtures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reagent_id      = db.Column(
        db.Integer,
        db.ForeignKey("reagents.id"),
        nullable=False,
    )
    amount          = db.Column(db.Float, nullable=False)
    amount_unit     = db.Column(db.String(10), nullable=False)
    # mol / mmol / µmol / g / mg / µg   for solutes
    # L   / mL   / µL                   for solvents
    is_solvent      = db.Column(db.Boolean, default=False, nullable=False)
    is_filler       = db.Column(db.Boolean, default=False, nullable=False)
    component_order = db.Column(db.Integer, default=0, nullable=False)

    reagent = db.relationship("Reagent")

    def to_dict(self) -> dict:
        return {
            "id":              self.id,
            "reagent_id":      self.reagent_id,
            "amount":          self.amount,
            "amount_unit":     self.amount_unit,
            "is_solvent":      self.is_solvent,
            "is_filler":       self.is_filler,
            "component_order": self.component_order,
        }


class Mixture(db.Model):
    """A lab-prepared solution with no CAS number."""
    __tablename__ = "mixtures"

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    author      = db.Column(db.String(200), nullable=True)
    notes       = db.Column(db.Text, nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at  = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    components = db.relationship(
        "MixtureComponent",
        backref="mixture",
        cascade="all, delete-orphan",
        order_by="MixtureComponent.component_order",
    )
    inventory_items = db.relationship(
        "InventoryItem",
        backref="mixture",
        cascade="all, delete-orphan",
        foreign_keys="InventoryItem.mixture_id",
    )

    @property
    def display_name(self) -> str:
        return self.name or f"Mixture #{self.id}"
