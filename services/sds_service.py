"""
SDS (Safety Data Sheet) service.
Handles automatic retrieval from PubChem and local file storage.
"""
from __future__ import annotations
import os
import requests
from flask import current_app
from extensions import db
from models import SdsDocument, Reagent

TIMEOUT = 15


def fetch_and_store(reagent: Reagent) -> SdsDocument | None:
    """
    Attempt to automatically find and download an SDS for the reagent:
      1. Query PubChem for an SDS URL (requires pubchem_cid to be set).
      2. Download the PDF and save to static/sds/<cas>.pdf.
      3. Persist an SdsDocument record and return it.

    Returns the new (or existing primary) SdsDocument, or None on failure.
    """
    # Return existing primary SDS immediately — no re-download needed
    existing = next((s for s in reagent.sds_documents if s.is_primary), None)
    if existing:
        return existing

    if not reagent.pubchem_cid:
        return None

    from services import pubchem_service
    url = pubchem_service.get_sds_url(int(reagent.pubchem_cid))
    if not url:
        return None

    pdf_bytes = _download_pdf(url)
    if not pdf_bytes:
        return None

    file_path = _save_pdf(reagent.cas_number, pdf_bytes)

    sds = SdsDocument(
        reagent_id=reagent.id,
        source="pubchem",
        original_url=url,
        file_path=file_path,
        is_primary=True,
    )
    db.session.add(sds)
    db.session.commit()
    return sds


def _download_pdf(url: str) -> bytes | None:
    try:
        resp = requests.get(url, timeout=TIMEOUT, allow_redirects=True)
        content_type = resp.headers.get("Content-Type", "").lower()
        if resp.status_code == 200 and ("pdf" in content_type or url.lower().endswith(".pdf")):
            return resp.content
    except requests.RequestException:
        pass
    return None


def _save_pdf(cas: str, data: bytes) -> str:
    """Save bytes to static/sds/<cas>.pdf; return relative path."""
    folder = current_app.config["SDS_UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    safe_cas  = cas.replace("/", "_")
    filename  = f"{safe_cas}.pdf"
    full_path = os.path.join(folder, filename)
    with open(full_path, "wb") as f:
        f.write(data)
    return os.path.join("sds", filename)
