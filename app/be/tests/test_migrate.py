"""Tests for the migration runner (team_chat_mcp.migrate)."""

import sqlite3
import textwrap
from pathlib import Path

import pytest

from team_chat_mcp.migrate import run_migrations, _split_statements


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_conn() -> sqlite3.Connection:
    """Return an in-memory SQLite connection with WAL + foreign keys."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _write_migration(tmp_path: Path, name: str, sql: str) -> Path:
    """Write a .sql file into *tmp_path* and return the directory."""
    (tmp_path / name).write_text(textwrap.dedent(sql))
    return tmp_path


def _applied_names(conn: sqlite3.Connection) -> set[str]:
    """Return the set of migration names recorded in _migrations."""
    return {
        row[0] for row in conn.execute("SELECT name FROM _migrations").fetchall()
    }


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# _split_statements unit tests
# ---------------------------------------------------------------------------

class TestSplitStatements:
    def test_single_statement(self):
        stmts = _split_statements("CREATE TABLE t (id INT);")
        assert len(stmts) == 1
        assert "CREATE TABLE" in stmts[0]

    def test_multiple_statements(self):
        sql = "CREATE TABLE a (id INT);\nCREATE TABLE b (id INT);"
        stmts = _split_statements(sql)
        assert len(stmts) == 2

    def test_ignores_empty_and_whitespace(self):
        sql = "  ;  \n  ;  "
        stmts = _split_statements(sql)
        assert stmts == []

    def test_trailing_whitespace(self):
        sql = "CREATE TABLE t (id INT);  \n  "
        stmts = _split_statements(sql)
        assert len(stmts) == 1

    def test_semicolons_in_string_literal(self):
        sql = "INSERT INTO t VALUES ('hello; world');"
        stmts = _split_statements(sql)
        assert len(stmts) == 1
        assert "hello; world" in stmts[0]

    def test_comments_preserved(self):
        sql = "-- comment\nCREATE TABLE t (id INT);"
        stmts = _split_statements(sql)
        assert len(stmts) == 1


# ---------------------------------------------------------------------------
# run_migrations tests
# ---------------------------------------------------------------------------

class TestRunMigrationsSuccess:
    """Successful migration apply — schema created and _migrations row present."""

    def test_applies_single_migration(self, tmp_path):
        conn = _fresh_conn()
        _write_migration(tmp_path, "001_init.sql", """\
            CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT);
        """)

        applied = run_migrations(conn, migrations_dir=tmp_path)

        assert applied == ["001_init.sql"]
        assert _table_exists(conn, "widgets")
        assert "001_init.sql" in _applied_names(conn)

    def test_applies_multiple_migrations_in_order(self, tmp_path):
        conn = _fresh_conn()
        _write_migration(tmp_path, "001_init.sql", """\
            CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT);
        """)
        _write_migration(tmp_path, "002_add_col.sql", """\
            ALTER TABLE widgets ADD COLUMN color TEXT;
        """)

        applied = run_migrations(conn, migrations_dir=tmp_path)

        assert applied == ["001_init.sql", "002_add_col.sql"]
        # Verify the column was added by inserting a row with color.
        conn.execute("INSERT INTO widgets (name, color) VALUES ('w', 'red')")
        row = conn.execute("SELECT color FROM widgets").fetchone()
        assert row[0] == "red"

    def test_multi_statement_migration(self, tmp_path):
        conn = _fresh_conn()
        _write_migration(tmp_path, "001_multi.sql", """\
            CREATE TABLE a (id INTEGER PRIMARY KEY);
            CREATE TABLE b (id INTEGER PRIMARY KEY);
            CREATE INDEX idx_b ON b(id);
        """)

        applied = run_migrations(conn, migrations_dir=tmp_path)

        assert applied == ["001_multi.sql"]
        assert _table_exists(conn, "a")
        assert _table_exists(conn, "b")

    def test_bookkeeping_row_has_applied_at(self, tmp_path):
        conn = _fresh_conn()
        _write_migration(tmp_path, "001_init.sql", """\
            CREATE TABLE widgets (id INTEGER PRIMARY KEY);
        """)
        run_migrations(conn, migrations_dir=tmp_path)

        row = conn.execute(
            "SELECT applied_at FROM _migrations WHERE name='001_init.sql'"
        ).fetchone()
        assert row is not None
        assert row[0] is not None  # datetime string


class TestRunMigrationsFailureRollsBack:
    """Failing migration must not leave schema changes or _migrations rows."""

    def test_bad_sql_rolls_back_entire_migration(self, tmp_path):
        conn = _fresh_conn()
        _write_migration(tmp_path, "001_bad.sql", """\
            CREATE TABLE good_table (id INTEGER PRIMARY KEY);
            CREATE TABLE bad_table (id INTEGER PRIMARY KEY, CONSTRAINT bad CHECK(broken));
        """)

        with pytest.raises(sqlite3.OperationalError):
            run_migrations(conn, migrations_dir=tmp_path)

        # Neither the table nor the bookkeeping row should exist.
        assert not _table_exists(conn, "good_table")
        assert not _table_exists(conn, "bad_table")
        # _migrations table exists (created before loop) but has no rows.
        assert _applied_names(conn) == set()

    def test_second_migration_failure_preserves_first(self, tmp_path):
        """If migration 002 fails, migration 001 should still be recorded."""
        conn = _fresh_conn()
        _write_migration(tmp_path, "001_ok.sql", """\
            CREATE TABLE alpha (id INTEGER PRIMARY KEY);
        """)
        _write_migration(tmp_path, "002_fail.sql", """\
            CREATE TABLE beta (id INTEGER PRIMARY KEY);
            INSERT INTO nonexistent_table VALUES (1);
        """)

        with pytest.raises(sqlite3.OperationalError):
            run_migrations(conn, migrations_dir=tmp_path)

        # 001 committed successfully before 002 was attempted.
        assert _table_exists(conn, "alpha")
        assert "001_ok.sql" in _applied_names(conn)

        # 002 was rolled back — no table, no bookkeeping row.
        assert not _table_exists(conn, "beta")
        assert "002_fail.sql" not in _applied_names(conn)


class TestRunMigrationsIdempotent:
    """Re-running does not re-apply already-applied migrations or error."""

    def test_rerun_is_noop(self, tmp_path):
        conn = _fresh_conn()
        _write_migration(tmp_path, "001_init.sql", """\
            CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT);
        """)

        first_run = run_migrations(conn, migrations_dir=tmp_path)
        assert first_run == ["001_init.sql"]

        second_run = run_migrations(conn, migrations_dir=tmp_path)
        assert second_run == []

        # Table still exists, only one bookkeeping row.
        assert _table_exists(conn, "widgets")
        count = conn.execute("SELECT COUNT(*) FROM _migrations").fetchone()[0]
        assert count == 1

    def test_new_migration_applied_on_rerun(self, tmp_path):
        conn = _fresh_conn()
        _write_migration(tmp_path, "001_init.sql", """\
            CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT);
        """)
        run_migrations(conn, migrations_dir=tmp_path)

        # Add a second migration file and re-run.
        _write_migration(tmp_path, "002_add_col.sql", """\
            ALTER TABLE widgets ADD COLUMN color TEXT;
        """)
        second_run = run_migrations(conn, migrations_dir=tmp_path)

        assert second_run == ["002_add_col.sql"]
        assert _applied_names(conn) == {"001_init.sql", "002_add_col.sql"}

    def test_rerun_after_failure_applies_fixed_migration(self, tmp_path):
        """After a failed migration is fixed on disk, re-run should apply it."""
        conn = _fresh_conn()
        _write_migration(tmp_path, "001_init.sql", """\
            CREATE TABLE widgets (id INTEGER PRIMARY KEY);
        """)
        # 002 is broken initially.
        _write_migration(tmp_path, "002_broken.sql", """\
            THIS IS NOT VALID SQL;
        """)

        with pytest.raises(sqlite3.OperationalError):
            run_migrations(conn, migrations_dir=tmp_path)

        # Fix the migration on disk.
        (tmp_path / "002_broken.sql").write_text(
            "ALTER TABLE widgets ADD COLUMN fixed TEXT;"
        )

        second_run = run_migrations(conn, migrations_dir=tmp_path)
        assert second_run == ["002_broken.sql"]
        assert _applied_names(conn) == {"001_init.sql", "002_broken.sql"}


class TestRunMigrationsEdgeCases:
    """Edge-case coverage."""

    def test_empty_migrations_dir(self, tmp_path):
        conn = _fresh_conn()
        applied = run_migrations(conn, migrations_dir=tmp_path)
        assert applied == []
        assert _table_exists(conn, "_migrations")

    def test_non_sql_files_ignored(self, tmp_path):
        conn = _fresh_conn()
        (tmp_path / "README.md").write_text("# not a migration")
        (tmp_path / "001_init.sql").write_text(
            "CREATE TABLE t (id INTEGER PRIMARY KEY);"
        )
        applied = run_migrations(conn, migrations_dir=tmp_path)
        assert applied == ["001_init.sql"]

    def test_connection_usable_after_failed_migration(self, tmp_path):
        """Ensure the connection is not left in a broken transaction state."""
        conn = _fresh_conn()
        _write_migration(tmp_path, "001_bad.sql", "INVALID SQL GARBAGE;")

        with pytest.raises(sqlite3.OperationalError):
            run_migrations(conn, migrations_dir=tmp_path)

        # Connection should still be usable for normal operations.
        conn.execute("CREATE TABLE post_fail (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO post_fail VALUES (1)")
        assert conn.execute("SELECT id FROM post_fail").fetchone()[0] == 1
