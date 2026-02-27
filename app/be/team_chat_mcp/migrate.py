"""Numbered SQL migration runner for team chat DB."""

import os
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def run_migrations(conn: sqlite3.Connection) -> list[str]:
    """Apply pending migrations. Returns list of applied migration filenames."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS _migrations ("
        "  name TEXT PRIMARY KEY,"
        "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ")"
    )
    applied = {
        row[0] for row in conn.execute("SELECT name FROM _migrations").fetchall()
    }

    sql_files = sorted(f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql"))
    newly_applied: list[str] = []

    for filename in sql_files:
        if filename in applied:
            continue
        sql = (MIGRATIONS_DIR / filename).read_text()
        conn.executescript(sql)
        conn.execute("INSERT INTO _migrations (name) VALUES (?)", (filename,))
        conn.commit()
        newly_applied.append(filename)

    return newly_applied
