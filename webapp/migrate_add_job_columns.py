"""
Run this once after setting up PostgreSQL to ensure the jobs table
has the user_id and retention_days columns added in the latest schema.

Usage:
    cd /home/appuser/OCR_gem_json/webapp
    python migrate_add_job_columns.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv(Path(__file__).parent / ".env", override=True)

from db import engine
from sqlalchemy import inspect, text

insp = inspect(engine)
existing_cols = {c["name"] for c in insp.get_columns("jobs")}

print("Current jobs columns:", sorted(existing_cols))

migrations = []

if "user_id" not in existing_cols:
    migrations.append(
        "ALTER TABLE jobs ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;"
    )
    print("→ Will add: user_id")
else:
    print("✓ user_id already exists")

if "retention_days" not in existing_cols:
    migrations.append(
        "ALTER TABLE jobs ADD COLUMN retention_days INTEGER NOT NULL DEFAULT 1;"
    )
    print("→ Will add: retention_days")
else:
    print("✓ retention_days already exists")

if not migrations:
    print("\nNothing to migrate — schema is up to date.")
    sys.exit(0)

with engine.begin() as conn:
    for sql in migrations:
        print(f"\nRunning: {sql}")
        conn.execute(text(sql))

print("\n✓ Migration complete.")
