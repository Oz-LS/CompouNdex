#!/usr/bin/env python3
"""
download_pictograms.py — one-shot utility script.

Downloads the nine official GHS/CLP pictogram PNG files from the
UN/UNECE website and saves them to static/pictograms/ as:
    GHS01.png … GHS09.png

Run once from the project root:
    python download_pictograms.py

If a file already exists it is skipped.  The script requires only the
'requests' package (already in requirements.txt).
"""
import os
import sys
import requests

DEST_DIR = os.path.join(os.path.dirname(__file__), "static", "pictograms")

# Official UNECE GHS pictogram URLs (SVG converted to PNG by PubChem)
# PubChem hosts convenient 300×300 PNG versions that are freely available.
PICTOGRAMS = {
    "GHS01": "https://pubchem.ncbi.nlm.nih.gov/images/ghs/GHS01.svg.png",
    "GHS02": "https://pubchem.ncbi.nlm.nih.gov/images/ghs/GHS02.svg.png",
    "GHS03": "https://pubchem.ncbi.nlm.nih.gov/images/ghs/GHS03.svg.png",
    "GHS04": "https://pubchem.ncbi.nlm.nih.gov/images/ghs/GHS04.svg.png",
    "GHS05": "https://pubchem.ncbi.nlm.nih.gov/images/ghs/GHS05.svg.png",
    "GHS06": "https://pubchem.ncbi.nlm.nih.gov/images/ghs/GHS06.svg.png",
    "GHS07": "https://pubchem.ncbi.nlm.nih.gov/images/ghs/GHS07.svg.png",
    "GHS08": "https://pubchem.ncbi.nlm.nih.gov/images/ghs/GHS08.svg.png",
    "GHS09": "https://pubchem.ncbi.nlm.nih.gov/images/ghs/GHS09.svg.png",
}

TIMEOUT = 15


def main():
    os.makedirs(DEST_DIR, exist_ok=True)
    ok = skipped = failed = 0

    for code, url in PICTOGRAMS.items():
        dest = os.path.join(DEST_DIR, f"{code}.png")
        if os.path.isfile(dest):
            print(f"  [skip]  {code}.png already exists")
            skipped += 1
            continue
        try:
            resp = requests.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                f.write(resp.content)
            size = len(resp.content) // 1024
            print(f"  [ok]    {code}.png  ({size} KB)")
            ok += 1
        except Exception as e:
            print(f"  [fail]  {code}: {e}", file=sys.stderr)
            failed += 1

    print(f"\nDone: {ok} downloaded, {skipped} skipped, {failed} failed.")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
