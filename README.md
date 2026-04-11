# Reagentario

A web-based inventory and safety management system for a university chemistry laboratory.

Built with **Python / Flask**, **Bootstrap 5**, **SQLite / SQLAlchemy**, and **ReportLab**.  
Designed to run on [PythonAnywhere Free tier](https://www.pythonanywhere.com).

---

## Features

| Section | Description |
|---|---|
| **Search** | Search by CAS, name, or formula. Hydration degree support. Autocomplete from local cache. Disambiguation modal for ambiguous names. Data fetched from PubChem and ChemSpider on first lookup, then cached locally. |
| **Inventory** | Track reagents by location (cabinets, solvents, acids, bases, to-buy list). Separate column layouts for in-lab vs. to-buy items. Inline note editing. CSV export. |
| **Label Cart** | Session-based label cart. Generate CLP-compliant A4 PDFs in five sizes (1 kg → 1 g). Phrase text auto-suppressed on small formats. |
| **Guidelines** | Inline PDF viewer and Markdown renderer. Sidebar document list. Stub AI assistant endpoint for future RAG integration. |

---

## Quick Start (local development)

### 1. Clone / unzip and create a virtual environment

```bash
cd reagentario
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Download GHS pictogram PNGs (optional but recommended)

```bash
python download_pictograms.py
```

This saves `GHS01.png … GHS09.png` to `static/pictograms/`.  
Labels fall back to a vector diamond symbol if PNGs are absent.

### 4. Configure environment variables (optional)

Copy `.flaskenv` and edit as needed. Minimum required for ChemSpider:

```
CHEMSPIDER_API_KEY=your_key_here
```

The app works without a ChemSpider key — it will use PubChem only.

### 5. Start the development server

```bash
flask run
```

The database (`reagentario.db`) and all required directories are created
automatically on first startup. No migrations needed during development.

Open [http://127.0.0.1:5000](http://127.0.0.1:5000).

---

## PythonAnywhere Deployment

1. Upload (or `git clone`) the project to your PythonAnywhere home directory.
2. Create a virtual environment and install dependencies:
   ```bash
   mkvirtualenv reagentario --python=python3.11
   pip install -r requirements.txt
   ```
3. In the PythonAnywhere **Web** tab:
   - Set **Source code** to the project directory.
   - Set **WSGI configuration file** to point at `wsgi.py` in the project.
   - Set **Virtualenv** to the environment created above.
4. Set environment variables in the **WSGI file** or via the PythonAnywhere
   **Environment variables** panel:
   ```
   SECRET_KEY=<a long random string>
   CHEMSPIDER_API_KEY=<your key>      # optional
   FLASK_ENV=production
   ```
5. Reload the web app.

---

## Directory Structure

```
reagentario/
├── app.py                    # Application factory
├── config.py                 # Dev / Prod config classes
├── extensions.py             # SQLAlchemy, Flask-Migrate
├── wsgi.py                   # PythonAnywhere WSGI entry point
├── .flaskenv                 # Local dev environment variables
├── requirements.txt
├── download_pictograms.py    # One-shot GHS PNG downloader
│
├── blueprints/
│   ├── search/               # Search page + API
│   ├── inventory/            # Inventory table + CSV export
│   ├── reagent/              # Reagent card + inventory CRUD + SDS
│   ├── labels/               # Label cart + PDF generation
│   └── guidelines/           # Document viewer + RAG stub
│
├── models/
│   ├── reagent.py            # Reagent (cached from PubChem/ChemSpider)
│   ├── inventory_item.py     # Physical batches in the lab
│   └── sds_document.py       # Safety Data Sheets
│
├── services/
│   ├── pubchem_service.py    # PubChem PUG REST/View client
│   ├── chemspider_service.py # ChemSpider RSC API client
│   ├── reagent_service.py    # Orchestrator: search, fetch, cache
│   ├── hydration_service.py  # Hydration degree → IUPAC suffix + resolution
│   ├── hp_service.py         # Local H/P phrase lookup
│   ├── sds_service.py        # SDS auto-download and storage
│   ├── label_service.py      # ReportLab PDF label generation
│   └── rag_service.py        # RAG stub (future LLM integration)
│
├── data/
│   └── hazard_phrases.py     # Bilingual EN/IT H and P phrase dictionary
│
├── static/
│   ├── css/main.css
│   ├── pictograms/           # GHS01.png … GHS09.png (run download_pictograms.py)
│   ├── sds/                  # Auto-downloaded SDS PDF files
│   └── guidelines/           # Place .pdf and .md guideline files here
│
└── templates/
    ├── base.html
    ├── search/index.html
    ├── inventory/index.html
    ├── reagent/card.html
    ├── labels/index.html
    ├── guidelines/index.html
    └── errors/  (404, 500, generic)
```

---

## Adding Guidelines

Drop any `.pdf` or `.md` file into `static/guidelines/`.  
Files are listed automatically; filenames like `02_waste_management.md` are
displayed as "Waste Management" in the sidebar.

---

## Migrating to PostgreSQL

1. Change `DATABASE_URL` in your environment:
   ```
   DATABASE_URL=postgresql://user:pass@host/dbname
   ```
2. Replace `db.Column(db.JSON, ...)` definitions (already compatible)  
   and run:
   ```bash
   flask db migrate -m "migrate to postgres"
   flask db upgrade
   ```

No model changes are required.

---

## License

For internal laboratory use. Adapt as needed.
