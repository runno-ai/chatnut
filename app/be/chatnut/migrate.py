"""Numbered SQL migration runner for team chat DB."""

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _split_statements(sql: str) -> list[str]:
    """Split a SQL script into individual non-empty statements.

    Uses sqlite3's own parser to correctly handle semicolons inside
    string literals, comments, etc.  Falls back to naive semicolon
    splitting only when the internal API is unavailable.
    """
    statements: list[str] = []
    remainder = sql.strip()
    while remainder:
        try:
            # complete_statement tells us if the text so far is one or
            # more complete SQL statements.  We grow a window until it
            # reports True, then split.
            for end in range(1, len(remainder) + 1):
                if sqlite3.complete_statement(remainder[:end]):
                    stmt = remainder[:end].strip()
                    if stmt and stmt != ";":
                        statements.append(stmt)
                    remainder = remainder[end:].strip()
                    break
            else:
                # Remaining text never completed — treat as one statement
                stmt = remainder.strip()
                if stmt and stmt != ";":
                    statements.append(stmt)
                break
        except Exception:
            # Fallback: naive split (unlikely but safe)
            for part in remainder.split(";"):
                part = part.strip()
                if part:
                    statements.append(part)
            break
    return statements


def run_migrations(
    conn: sqlite3.Connection,
    migrations_dir: Path | None = None,
) -> list[str]:
    """Apply pending migrations atomically. Returns list of applied filenames.

    Each migration's DDL/DML and its ``_migrations`` bookkeeping row are
    executed inside a single transaction so that a crash between them
    cannot leave the database in an inconsistent state.

    Parameters
    ----------
    conn:
        An open SQLite connection.
    migrations_dir:
        Directory containing numbered ``.sql`` files.  Defaults to the
        ``migrations/`` directory next to this package.
    """
    if migrations_dir is None:
        migrations_dir = MIGRATIONS_DIR

    # Switch to manual transaction control so our explicit BEGIN/COMMIT/
    # ROLLBACK calls are not confused by Python's implicit transaction
    # management.  Restore the original isolation_level on exit.
    orig_isolation = conn.isolation_level
    conn.isolation_level = None
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _migrations ("
            "  name TEXT PRIMARY KEY,"
            "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ")"
        )

        applied = {
            row[0]
            for row in conn.execute("SELECT name FROM _migrations").fetchall()
        }

        sql_files = sorted(
            f for f in os.listdir(migrations_dir) if f.endswith(".sql")
        )
        newly_applied: list[str] = []

        for filename in sql_files:
            if filename in applied:
                continue
            sql = (migrations_dir / filename).read_text()
            statements = _split_statements(sql)
            try:
                # Execute all migration statements + bookkeeping INSERT
                # inside one explicit transaction.
                conn.execute("BEGIN")
                for stmt in statements:
                    conn.execute(stmt)
                conn.execute(
                    "INSERT INTO _migrations (name) VALUES (?)", (filename,)
                )
                conn.execute("COMMIT")
            except Exception:
                # Roll back so that neither the schema changes nor the
                # bookkeeping row persist.
                conn.execute("ROLLBACK")
                logger.exception("Migration %s failed — rolled back", filename)
                raise
            newly_applied.append(filename)
    finally:
        conn.isolation_level = orig_isolation

    return newly_applied
