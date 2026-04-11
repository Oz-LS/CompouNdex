"""
One-shot migration: add the traditional_name column to the reagent table.
Run once before starting the app after this update:

    /Users/lorenzo/Library/CloudStorage/GoogleDrive-lorenzo.sarasino@unito.it/Il\ mio\ Drive/Python/venv/bin/python migrate_traditional_name.py

The column was already added via sqlite3 on first deploy; this script is kept
for reference and for any fresh database setup.
"""
from app import create_app
from extensions import db

app = create_app()
with app.app_context():
    with db.engine.connect() as conn:
        try:
            conn.execute(db.text(
                "ALTER TABLE reagents ADD COLUMN traditional_name VARCHAR(500)"
            ))
            conn.commit()
            print("✓ Column 'traditional_name' added to reagents table.")
        except Exception as e:
            print(f"Skipped (column probably already exists): {e}")
