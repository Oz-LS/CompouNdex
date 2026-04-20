"""
Re-fetch PubChem CID (by CAS) and GHS safety data for every reagent in the
database that has a CAS number.  This corrects stale CIDs stored by older
versions of the app and then re-fetches h_codes, p_codes, pictogram_codes,
and signal_word using the current extractor.

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
        if not r.cas_number:
            print(f"[{i}/{total}] (no CAS) — skipping")
            continue

        try:
            # Re-fetch CID by CAS to correct any stale/wrong CID stored in DB
            new_cid = pubchem_service.get_cid_by_cas(r.cas_number)
            if new_cid:
                if r.pubchem_cid != str(new_cid):
                    print(f"[{i}/{total}] {r.cas_number}  CID updated: {r.pubchem_cid} → {new_cid}")
                r.pubchem_cid = str(new_cid)

            cid = new_cid or (int(r.pubchem_cid) if r.pubchem_cid else None)
            if not cid:
                print(f"[{i}/{total}] {r.cas_number} — no CID found, skipping GHS")
                db.session.commit()
                continue

            safety = pubchem_service.get_safety_data(cid)
            r.h_codes         = safety["h_codes"]
            r.p_codes         = safety["p_codes"]
            r.pictogram_codes = safety["pictogram_codes"]
            r.signal_word     = safety["signal_word"]
            db.session.commit()
            print(
                f"[{i}/{total}] {r.cas_number}  "
                f"H: {r.h_codes}  pics: {r.pictogram_codes}"
            )
            updated += 1
        except Exception as exc:
            db.session.rollback()
            print(f"[{i}/{total}] {r.cas_number} — ERROR: {exc}")

    print(f"\nDone. Updated {updated}/{total} reagents.")
