"""
Re-fetch GHS safety data (h_codes, p_codes, pictogram_codes, signal_word)
for every reagent in the database that has a pubchem_cid.

Run from the project root:
    ./venv/bin/python scripts/refresh_ghs.py
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from extensions import db
from models import Reagent
from services import pubchem_service

app = create_app("development")

with app.app_context():
    reagents = Reagent.query.all()
    total = len(reagents)
    updated = 0

    for i, r in enumerate(reagents, 1):
        if not r.pubchem_cid:
            print(f"[{i}/{total}] {r.cas_number} — no CID, skipping")
            continue

        try:
            safety = pubchem_service.get_safety_data(r.pubchem_cid)
            r.h_codes         = safety["h_codes"]
            r.p_codes         = safety["p_codes"]
            r.pictogram_codes = safety["pictogram_codes"]
            r.signal_word     = safety["signal_word"]
            db.session.commit()
            print(
                f"[{i}/{total}] {r.cas_number}  "
                f"H: {r.h_codes}  P: {r.p_codes}"
            )
            updated += 1
        except Exception as exc:
            db.session.rollback()
            print(f"[{i}/{total}] {r.cas_number} — ERROR: {exc}")

    print(f"\nDone. Updated {updated}/{total} reagents.")
