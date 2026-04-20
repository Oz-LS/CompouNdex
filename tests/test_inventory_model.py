"""Integration tests for the InventoryItem XOR constraint and cascade rules."""
import pytest

from extensions import db
from models import Reagent, InventoryItem
from models.mixture import Mixture


def _make_reagent(cas="50-00-0", name="Formaldehyde"):
    r = Reagent(cas_number=cas, stock_name=name)
    db.session.add(r)
    db.session.commit()
    return r


def _make_mixture(name="PBS 1x"):
    m = Mixture(name=name)
    db.session.add(m)
    db.session.commit()
    return m


def test_inventory_accepts_reagent_only(app):
    r = _make_reagent()
    item = InventoryItem(
        reagent_id=r.id,
        location="cabinet_1",
        reagent_type="bought",
        quantity=100,
        quantity_unit="g",
        num_containers=1,
        brand="Sigma",
    )
    db.session.add(item)
    db.session.commit()
    assert item.id is not None


def test_inventory_accepts_mixture_only(app):
    m = _make_mixture()
    item = InventoryItem(
        mixture_id=m.id,
        location="cabinet_1",
        reagent_type="homemade",
        quantity=1,
        quantity_unit="L",
        num_containers=1,
        prepared_by="lab",
    )
    db.session.add(item)
    db.session.commit()
    assert item.id is not None


def test_inventory_rejects_both_set(app):
    r = _make_reagent()
    m = _make_mixture()
    # Python-level validator fires first (before the DB CHECK).
    with pytest.raises(ValueError):
        InventoryItem(
            reagent_id=r.id,
            mixture_id=m.id,
            location="cabinet_1",
            quantity=1,
            quantity_unit="g",
            num_containers=1,
        )


def test_deleting_reagent_with_inventory_fails(app):
    r = _make_reagent()
    item = InventoryItem(
        reagent_id=r.id,
        location="cabinet_1",
        reagent_type="bought",
        quantity=10,
        quantity_unit="g",
        num_containers=1,
        brand="Sigma",
    )
    db.session.add(item)
    db.session.commit()

    # With the new cascade rules, this should raise rather than silently wipe.
    db.session.delete(r)
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()
